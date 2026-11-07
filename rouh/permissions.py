"""Tools that have to be asked about first.

There was no approval layer here at all, and it worked because the tools are
narrow: `run_command` refuses anything that writes, writing goes to a worker
that leaves a log, and nothing else does much. That holds right up until a tool
does something real, and then the only options are to add it and hope, or not
to add it.

This is the third option. A tool named in `confirm_tools` stops before it runs,
the person is asked in one sentence, and it runs or does not run depending on
what they say. Everything not named behaves exactly as it did, which is the
whole of the compatibility promise: with nothing configured, nothing changes.

Where the question goes is the part worth getting right. Rouh already has one
place for "something has stopped and is waiting for a person": a worker that
asks turns red and dashed on the orb, breathing, with the words NEEDS YOU, and
the standing rule is that it is the one thing that must never be left alone. So
a gated tool waits in exactly that way rather than inventing a second kind of
waiting. The event carries the question and its two answers, the page draws it
under the turn, and the tool call's own node on the orb goes to `waiting`.

Three things that a spoken turn makes necessary:

- **It cannot wait for ever.** Nobody may be looking at the screen. The wait
  has a ceiling, and running out is a refusal with a reason, never a silent
  hang and never a yes.
- **The refusal is an answer, not an error.** The model is told plainly that
  the person said no, so it can say so and carry on, rather than treating it as
  a broken tool and trying again.
- **A yes is for this call only.** Nothing here remembers an answer. A tool
  worth asking about is worth asking about twice.
"""
from __future__ import annotations

import asyncio
import logging
import secrets

log = logging.getLogger("rouh.permissions")

#: How long a question waits for an answer before it is refused, in seconds.
#: Long enough to read one and press a button, short enough that a turn nobody
#: is watching ends rather than hanging.
TIMEOUT = 120.0

#: What the person is offered. Two answers, and they mean what they say.
ALLOW = "allow"
REFUSE = "refuse"

#: A third thing `ask` can come back with, which the person never chooses:
#: nobody answered. It is a refusal, and it is a different refusal, because
#: "they said no" and "they are not at the screen" are different things to say
#: back and the model should say the right one.
NO_ANSWER_AT_ALL = "no answer"

#: What the model is told when the answer is no. Written as an answer rather
#: than as a failure: a tool that reports an error gets tried again.
REFUSED = ("The person was asked to allow this and said no: {what}. It was not "
           "done and nothing was changed. Tell them it was not done, and do not "
           "ask again unless they bring it up.")

NO_ANSWER = ("The person was asked to allow this and did not answer within "
             "{seconds:.0f} seconds: {what}. It was not done and nothing was "
             "changed. They may not be at the screen. Say that it is waiting "
             "on them.")


def gated(cfg) -> frozenset[str]:
    """The tools that have to be asked about, from the configuration.

    Empty by default, and empty means nothing changes anywhere.
    """
    raw = getattr(cfg, "confirm_tools", "") or ""
    if not isinstance(raw, str):
        names = list(raw)
    else:
        names = raw.replace(",", " ").split()
    return frozenset(n.strip() for n in names if n.strip())


def what_for(name: str, said: dict) -> str:
    """What is about to happen, in the tool's own words.

    The same words that go on the orb, so the question on the screen and the
    twig in the corner say the same thing rather than two different things
    about one piece of work.
    """
    return (said.get("what") or f"Run {name}").strip()


def question_for(name: str, said: dict) -> str:
    """The one sentence the person is asked.

    "Sending an email to Bob. May I?" rather than "May I sending an email to
    Bob?". The labels are written as gerunds, because they describe work in
    progress on the orb, and no amount of lower-casing turns one of those into
    the middle of a question. Put in front of the asking instead, it reads.
    """
    return f"{what_for(name, said)}. May I?"


class Gate:
    """The questions waiting for an answer, and the answers coming back.

    One of these per process. It holds nothing but futures: a question that is
    answered, refused or timed out is gone from here, so a page that reloads
    and answers a question that has already expired is told so rather than
    silently doing nothing.
    """

    def __init__(self, timeout: float = TIMEOUT):
        self.timeout = timeout
        self._waiting: dict[str, asyncio.Future] = {}

    def pending(self) -> list[str]:
        return list(self._waiting)

    def answer(self, ask_id: str, allowed: bool) -> bool:
        """The person's answer. True if there was still a question to answer."""
        future = self._waiting.pop(ask_id, None)
        if future is None or future.done():
            return False
        future.set_result(bool(allowed))
        return True

    async def ask(self, name: str, said: dict, emit, *, call_id: str = "") -> str:
        """Ask, wait, and say what came back: `ALLOW`, `REFUSE` or `NO_ANSWER_AT_ALL`.

        Three answers rather than a yes and a no, because "they said no" and
        "nobody was there" are different things for the model to say back, and
        only one of them is worth mentioning that it is still waiting on.

        Never raises for a question that goes unanswered. It comes back a
        refusal, which is the same answer the person gave by walking away.
        """
        ask_id = "ask-" + secrets.token_hex(4)
        what = what_for(name, said)
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        self._waiting[ask_id] = future

        await emit({
            "type": "permission_ask",
            "id": ask_id,
            "call_id": call_id,
            "name": name,
            "question": question_for(name, said),
            "what": what,
            "detail": said.get("detail") or "",
            "choices": [ALLOW, REFUSE],
            "seconds": self.timeout,
            "where": "rouh",
        })
        try:
            allowed = await asyncio.wait_for(asyncio.shield(future), self.timeout)
        except asyncio.TimeoutError:
            allowed = None
        except asyncio.CancelledError:
            # The turn was abandoned, which a barge-in does routinely. The
            # question goes with it rather than being left on the screen.
            self._waiting.pop(ask_id, None)
            await emit({"type": "permission_done", "id": ask_id, "answer": REFUSE,
                        "where": "rouh"})
            raise
        finally:
            self._waiting.pop(ask_id, None)

        verdict = (NO_ANSWER_AT_ALL if allowed is None
                   else ALLOW if allowed else REFUSE)
        await emit({"type": "permission_done", "id": ask_id,
                    # The page has one thing to draw either way: it was not
                    # allowed. Why is for the model and for the log.
                    "answer": ALLOW if verdict == ALLOW else REFUSE,
                    "timed_out": verdict == NO_ANSWER_AT_ALL, "where": "rouh"})
        log.info("permission for %s: %s", name, verdict)
        return verdict

    def refusal(self, name: str, said: dict, verdict: str) -> str:
        """What the model is told, which is never that a tool failed."""
        what = what_for(name, said)
        if verdict == NO_ANSWER_AT_ALL:
            return NO_ANSWER.format(what=what, seconds=self.timeout)
        return REFUSED.format(what=what)
