"""What somebody said, turned into work, with nobody in the middle.

The board has two columns and there used to be two people-sized gaps between
them. A person left a feedback; somebody had to open the board, read it, press
*Turn this into a feature request*, write the title and how the solution should
work, and then press *Start a run for this*. Both presses were the whole of the
delay, and neither of them was a decision anybody was actually making: Petar,
22 September 2026 - "the feedbacks should be automatically converted to feature
requests and should automatically be put in RUNS to be completed."

So this module is those two presses, done by the machine, the moment the
feedback lands and again on a beat afterwards.

    a feedback arrives  ->  read it  ->  a feature request  ->  a run
                        ->  the run ends  ->  the card says so

**Reading it is a model call and nothing else is.** The model is given what the
person wrote, where they were when they wrote it and what they attached, and
answers with three fields: what kind of thing it is, a title, and how the
solution should work. That last one is what the run is briefed with, so it is
the field worth spending the tokens on. Everything else here is plain code.

**A reading is never the person's words.** The feedback row is not touched -
what somebody said stays what they said - and the request says on its face that
a machine wrote it (`automatic`), so the run is briefed with both: the reading,
and underneath it the sentence the person actually typed. If the reading is
wrong the words are right there to correct it from.

**Nothing here may fail to convert.** A model that is not configured, is
overloaded, is slow or answers something that is not JSON all end in the same
place: `guess`, which writes a serviceable request out of the feedback itself.
A feedback that was never converted because the clever path broke is exactly
the feedback nobody ever sees again, and that is the failure this exists to
stop.

**Starting the run may fail, and then it is tried again.** A machine with no
worker and no one program cannot start anything, and that is a fact about the
machine rather than about the request: the reason is written on the row
(`run_note`), the card says it, and the sweep tries again. It gives up after
`MAX_TRIES` so a request that can never start is not asked for ever.

**A backlog is worked through, not dumped.** One sweep converts everything
waiting, because a board that is right is the point of it, and starts at most
`MAX_STARTS_PER_SWEEP` runs, because each of those is a real agent in a real
checkout. Seven feedbacks left over a fortnight become seven feature requests
at once and seven runs over the next few beats. A feedback somebody writes now
is never held back by it: the immediate path starts its run straight away.

**The sweep is the second half of the promise.** Immediately is what the person
asked for and is what a submission gets, but a process that was restarted
mid-conversion, a run that would not start, a feedback written while the model
was down - each of those is a card that would sit there for good. So every
`sweep_minutes` this walks every organisation's board and picks up whatever was
left: feedback with nothing made from it, and automatic requests with no run.
Petar, in the same breath: "immediately or you can check every 5 minutes.
immediately looks good to me, but also maybe there could be a sweep every so
many minutes?" - so it is both.

**And the run ending is the last of them.** Three of the four links were
written down and the fourth was not, so a card whose work had been built and
landed hours before still read Building with "run done" printed underneath it:
the board could see the run had finished and the status never moved. Petar,
23 September 2026 - "It is looking like the features get built indeed but they
don't get marked Done. They stay building. Their status should change after
they are done." `settle` is that, and a run that ends badly is said as plainly
as one that worked, because an eternal spinner is the worse of the two lies.
It runs on the sweep, so the board is right whether or not anybody is looking,
and again on every read of the board, so somebody who *is* looking sees the
card turn the moment the run's own line does.

**What is left alone.** A feature request somebody wrote by hand is never
started by the sweep. The person is in the middle of writing it, the Start box
is right there under it, and starting a run under somebody who is still typing
is not automation, it is interference. Only what came out of a feedback -
`from_feedback` - is carried the rest of the way by itself.

**And the run can be switched off on its own.** Petar, 23 September 2026 -
"give me a toggle that turns off automatic build. keep converting feedback to
features, but if the toggle is off, don't build them - immediately on submit
and on a cronjob." So the third link has a switch per organisation
(`GeneTherapyStore.autobuild`), and the first two do not: a feedback is still
read and a request still written, and the request waits, `proposed` with no
run, for somebody to press Start or for the switch to go back on. Both paths
that start a run by itself - the submission and the sweep - start it in
`Converter._start`, and that is where the switch is read, right before the
run would be asked for. Turned back on, the sweep picks up what waited, a few
at a time, exactly as it picks up any backlog. Nothing about starting a run by
hand is behind it.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Iterable

from . import gene_therapy as gt
from . import runs

log = logging.getLogger("rouh.triage")

#: How long the model may take to read one feedback. Nobody is waiting on this
#: - the drawer has already said thank you - but a request that never comes
#: back would hold a conversion open for ever, and the fallback below is a
#: perfectly good answer.
TIMEOUT = 45.0

#: The most the reading may be. A "how it should work" longer than this is the
#: model writing the implementation instead of describing it, and the run is
#: the thing that gets to decide how it is built.
MAX_BODY = 4000
MAX_TITLE = 120

#: The most runs one sweep starts. Converting is cheap and every feedback
#: waiting is converted on the first beat, because a board that is right is
#: the point of it; starting is not cheap - each one is a real agent in a real
#: checkout - so a backlog becomes runs over a few beats rather than all at
#: once. A submission is never held back by this: the immediate path starts its
#: run the moment the feedback lands.
MAX_STARTS_PER_SWEEP = 3

#: How many times a run is started for one request before it is left alone.
#: Each try is a real attempt at a real runner, so this is small: five failures
#: five minutes apart is a machine that cannot run it, not a flake.
MAX_TRIES = 5

#: What the ending of the run building a request means for the request. The
#: words on the left are the task list's own (`runs.status_of`), which is what
#: the card already reads off the register and prints under itself, so the
#: status and the line beneath it can never disagree about the same run.
#:
#: `idle` is in here beside `done` and is not an oversight: a run of the one
#: program that has finished its turn has built the thing and landed it, and is
#: sitting at its prompt waiting to be spoken to again. That is the state every
#: one of the stuck cards in the report was in. The words that are *not* here -
#: starting, running, waiting - are a run still in flight, and a card in front
#: of one of those is right to say it is being built.
ENDINGS: dict[str, str] = {
    "done": "shipped", "idle": "shipped",
    "failed": "failed", "lost": "failed", "killed": "failed",
    # Stopped at the one program's time limit: whatever it built, it did not
    # finish by itself, so the card is not called shipped.
    "reaped": "failed",
}

#: The preset a run made this way is started under: Rouh's own code, the one
#: program first and a worker here if there is no program
#: (`starting.PRESETS["improve_myself"]`). Feedback on the board is feedback
#: about Rouh, which is why the Start box on a card already chose Rouh's own
#: code before anybody automated it.
PRESET = "improve_myself"


SYSTEM = """You read feedback about Rouh and decide what is going to be done about it.

Rouh is a voice assistant with a browser interface. The feedback was written by
the person who uses it, from inside it. What you write is handed straight to a
coding run, which will build it, prove it in a real browser and land it, with
nobody in between reading it first. So what you write is the brief.

Answer with one JSON object and nothing else:

{"kind": "feature|bug|improvement|question",
 "title": "a short line naming the thing, not a sentence",
 "body": "how the solution should work"}

kind:
- "bug" when something is broken or wrong.
- "feature" when something that does not exist should exist.
- "improvement" when something exists and should be better or different.
- "question" when they asked something rather than asked for something.

title: two to eight words, naming the subject. No full stop, no quotation
marks, no "User wants". "The Gene therapy board converts by itself", never
"Request to make feedback convert".

body: a few short paragraphs, the brief the run works from.
- Say first what the person wanted, in your own words, plainly.
- Then say how the solution should work: what should happen, where, and what
  the person should see afterwards. Be concrete about the screen.
- Say what is genuinely unclear rather than inventing a requirement. The run
  can read their words underneath yours.
- Never invent a file name, a function or a design you have not been told
  about. You have not seen the code.
- Never use an em dash. Use a plain dash.

Answer in the language the person wrote in. JSON only: no markdown fence, no
sentence before it, no sentence after it."""

#: What is put in front of the person's own words. The page is in here because
#: "this is wrong" means the screen that was in front of them, and without it
#: nobody can tell which screen that was.
ASK = """Here is one piece of feedback.

{context}

What they wrote:

{body}

Answer with the JSON object and nothing else."""


@dataclass(frozen=True)
class Decision:
    """What is going to be done about one feedback."""

    kind: str
    title: str
    body: str
    #: How it was arrived at, for the log and for the line on the card.
    #: "the model" or "their own words".
    how: str


def _one_line(text: Any, limit: int) -> str:
    return " ".join(str(text or "").split())[:limit].strip()


# ---------------------------------------------------------------------------
# Reading one, with the model and without it
# ---------------------------------------------------------------------------


def context_lines(feedback: gt.Feedback, files: Iterable[gt.Attachment] = ()) -> str:
    """Everything about the feedback that is not the sentence itself."""
    lines = [f"Who wrote it: {feedback.author or 'somebody using Rouh'}"]
    if feedback.page:
        lines.append(f"The screen they were on: {feedback.page}")
    names = [f.name for f in files if f.name]
    if names:
        lines.append("What they attached: " + ", ".join(names[:10]))
    return "\n".join(lines)


def read_back(raw: str) -> Decision | None:
    """The model's answer as a decision, or None when there is nothing usable.

    Models answer a question like this with the object and sometimes with a
    fence or a sentence around it, so the first well formed object in the text
    is taken rather than the whole of it being required to parse. A field that
    is missing or empty is what makes this None: a half answer is worse than
    the fallback, because the fallback at least says nothing that is not in
    the person's own words.
    """
    text = (raw or "").strip()
    if not text:
        return None
    found = re.search(r"\{.*\}", text, re.S)
    if not found:
        return None
    try:
        got = json.loads(found.group(0))
    except Exception:
        return None
    if not isinstance(got, dict):
        return None
    kind = str(got.get("kind") or "").strip().lower()
    if kind not in gt.REQUEST_KINDS:
        kind = "improvement"
    title = _one_line(got.get("title"), MAX_TITLE)
    body = str(got.get("body") or "").strip()[:MAX_BODY]
    if not title or not body:
        return None
    return Decision(kind=kind, title=title, body=body, how="the model")


#: The words that say what kind of thing this is when nobody clever is
#: available. Deliberately few and deliberately obvious: this is a guess and it
#: is labelled as one on the card, so a wrong guess costs a word on a screen
#: and never a lost feedback.
_BUG_WORDS = re.compile(
    r"\b(bug|broken|broke|breaks|crash(?:es|ed)?|error|fail(?:s|ed|ing)?|"
    r"wrong|does ?n[o']t work|doesnt work|not working|stuck|hangs?|"
    r"грешка|не работи|счупен)\b", re.I)
_ASK_WORDS = re.compile(
    r"\b(should|could|can we|please add|i want|i'd like|id like|make it|"
    r"add a|add an|would be (?:good|nice|great)|искам|дай|добави)\b", re.I)
_QUESTION_WORDS = re.compile(r"\b(how do i|what is|why does|why is|can i|кога|защо|как)\b", re.I)


def guess(feedback: gt.Feedback) -> Decision:
    """A decision written out of the feedback itself, with no model at all.

    The fallback for every way the model can be unavailable, and a perfectly
    honest answer on its own: the title is the person's first line, the body
    says plainly that nobody has read this yet and that their words are the
    brief. Nothing here invents a requirement, which is exactly why it is safe
    to run unattended.
    """
    said = (feedback.body or "").strip()
    first = ""
    for line in said.splitlines():
        if line.strip():
            first = line.strip()
            break
    title = _one_line(first or "Feedback with nothing written in it", MAX_TITLE)
    if _BUG_WORDS.search(said):
        kind = "bug"
    elif _QUESTION_WORDS.search(said) or said.rstrip().endswith("?"):
        kind = "question"
    elif _ASK_WORDS.search(said):
        kind = "improvement"
    else:
        kind = "improvement"
    where = f" They were on {feedback.page} when they wrote it." if feedback.page else ""
    body = (
        "This was written from the person's own words, because the model that "
        "reads feedback could not be asked." + where + "\n\n"
        "Work out what they wanted from what they wrote, which is underneath, "
        "and build the smallest thing that gives it to them. If their words "
        "read more than one way, take the most useful reading and say in your "
        "report which one you took."
    )
    return Decision(kind=kind, title=title, body=body, how="their own words")


async def decide(feedback: gt.Feedback, files: Iterable[gt.Attachment] = (), *,
                 org_id: str | None = None) -> Decision:
    """Read one feedback. Never raises, and always answers with something.

    Asked of the model the Models page has for reading Gene therapy, for the
    feedback's organisation, whichever company's it is (`rouh/llm.py`), at the
    level that comes with it.
    """
    from . import llm

    asked = ASK.format(context=context_lines(feedback, files),
                       body=(feedback.body or "").strip())
    try:
        got = await llm.ask("triage", system=SYSTEM, messages=asked, max_tokens=1500,
                            org_id=org_id, subject=f"feedback {feedback.id}",
                            timeout=TIMEOUT, read_only=True)
        answer = read_back(got.text)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.warning("the model could not read feedback %s (%s); "
                    "using their own words", feedback.id, exc)
        return guess(feedback)
    if answer is None:
        log.warning("the model's reading of feedback %s was not usable; "
                    "using their own words", feedback.id)
        return guess(feedback)
    return answer


# ---------------------------------------------------------------------------
# The run ending
# ---------------------------------------------------------------------------


def queued(request: gt.FeatureRequest) -> bool:
    """Whether the sweep starts a run for this by itself, when building is on.

    `GeneTherapyStore.awaiting_run`'s WHERE clause, for one request already in
    hand: the board uses it to say which cards are waiting to be built rather
    than leaving a `proposed` with nothing under it to be read as stuck.
    """
    return (bool(request.from_feedback) and not request.run_id
            and request.status == "proposed" and request.run_tries < MAX_TRIES)


def settle(store: gt.GeneTherapyStore, org_id: str) -> int:
    """Take every request whose run has ended off `building`. How many moved.

    The last link of the chain at the top of this file. A run is started for a
    request and the card says Building; the run finishes, and until this
    nothing wrote that down, so the card went on saying Building for ever with
    its own run printing "done" one line below it.

    Three rules, and they are the whole of it.

    * **`building` is the only status this moves.** It is the machine's own
      word, written by `set_run`; `proposed`, `shipped`, `failed` and
      `declined` are somebody's decision and are left exactly where they were
      put. The rule is in the UPDATE itself (`GeneTherapyStore.run_ended`), not
      checked here, so two of these at once cannot both move the same card.
    * **A run the register cannot answer about is left alone.** Not "it must
      have failed": the register can be off altogether (`runs.enabled`) and a
      run can be forgotten, and neither of those is a fact about the work. The
      card already says which of the two it is.
    * **The feedback it came from is done when the request ships**, because
      the thing that person asked for exists now. Not when it failed - nothing
      was delivered - and never over a decision somebody made themselves.

    Plain and synchronous: two small queries and a read of the register per
    card still building, which is the same register read the board does for
    every card anyway.
    """
    moved = 0
    for request in store.building(org_id):
        row = runs.row_for(request.run_id)
        if row is None:
            continue
        ending = ENDINGS.get(str(row.get("status") or ""))
        if ending is None or not store.run_ended(org_id, request.id, ending):
            continue
        moved += 1
        log.info("feature request %s is %s: its run %s ended as %s",
                 request.id, ending, request.run_id, row.get("status"))
        if ending == "shipped" and request.from_feedback:
            store.feedback_done(org_id, request.from_feedback)
    return moved


def settle_quietly(store: gt.GeneTherapyStore, org_id: str) -> int:
    """`settle`, for a caller that is answering something else.

    The board's own routes call this while drawing a page. A board that could
    not be read because the register stumbled would be a worse bug than the
    one this fixes, so nothing it can raise reaches the reader: the sweep is
    behind it and will do the same work on its next beat.
    """
    try:
        return settle(store, org_id)
    except Exception:                                            # pragma: no cover
        log.exception("the requests still building could not be settled")
        return 0


# ---------------------------------------------------------------------------
# Doing it
# ---------------------------------------------------------------------------


class Converter:
    """The two presses nobody has to make any more.

    Handed a store and something that starts a run, and it knows nothing else
    about the server; the model it reads with is the Models page's (`decide`). `take_later` is the immediate path -
    the drawer's submission, converted while the person is still reading Thank
    you - and `sweep` is the beat behind it.
    """

    def __init__(self, store: gt.GeneTherapyStore, start_run: Callable[..., Awaitable[dict]],
                 *, read_with_model: bool = True,
                 on_change: Callable[[], Awaitable[None]] | None = None,
                 sweep_minutes: float = 5.0, enabled: bool = True) -> None:
        self.store = store
        self.start_run = start_run
        #: Whether a feedback is read with a model at all (the Models page's for
        #: reading Gene therapy, asked for each feedback so a change there reaches
        #: the next one read); off, it is built from the person's own words.
        self.read_with_model = bool(read_with_model)
        self.on_change = on_change
        self.sweep_minutes = max(0.5, float(sweep_minutes or 5.0))
        self.enabled = bool(enabled)
        #: The conversions running right now, held so the event loop cannot
        #: collect a task nobody is awaiting halfway through one.
        self._working: set[asyncio.Task] = set()
        #: One conversion at a time. Two of them would be two model calls and
        #: two runs started into the same machine, and the second would learn
        #: nothing the first did not.
        self._lock = asyncio.Lock()

    # --- the immediate path -------------------------------------------------

    def take_later(self, org_id: str, feedback: gt.Feedback) -> None:
        """Convert this one in the background. Returns at once.

        The drawer is answered before any of this happens: a person who has
        just written a sentence should not wait on a model reading it, and the
        board is told when it is done (`on_change`).
        """
        if not self.enabled:
            return
        task = asyncio.create_task(self._take_quietly(org_id, feedback))
        self._working.add(task)
        task.add_done_callback(self._working.discard)

    async def _take_quietly(self, org_id: str, feedback: gt.Feedback) -> None:
        try:
            await self.take(org_id, feedback)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("feedback %s could not be taken up", feedback.id)

    async def take(self, org_id: str, feedback: gt.Feedback) -> dict:
        """One feedback, all the way: read it, write the request, start the run.

        The run only when this organisation builds by itself; otherwise the
        request is written and left waiting (`_start`).
        """
        async with self._lock:
            made = await self._convert(org_id, feedback)
            if made is None:
                return {"converted": False}
            started = await self._start(org_id, made)
        await self._tell_them()
        return {"converted": True, "request": made.id, "run": started}

    # --- the beat behind it -------------------------------------------------

    async def sweep(self) -> dict:
        """Everything anybody has left behind, on every board.

        Anything the immediate path missed: a feedback written while this
        process was restarting, one whose conversion was cut off half way, a
        request whose run could not be started because there was nothing to
        start it with, and a run that has since ended without its card being
        told. Each organisation is asked about by name, which is the rule for
        every read of these tables.

        **Settling is not behind `enabled`.** That flag is about whether a
        feedback is read and given a run without anybody pressing anything. A
        request somebody started by hand from the board's own Start box is
        `building` just the same, and its run ends just the same, so a board
        with the automatic half turned off must still stop saying Building
        about work that is finished.

        **Nor is converting behind the board's own switch** (`autobuild`).
        That one holds back the run and nothing else, so a board that has
        stopped building still has every feedback on it read and written up;
        `_start` is where it is read, and the queue of requests waiting for a
        run is not even walked while it is off.
        """
        counted = {"converted": 0, "started": 0, "settled": 0}
        for org_id in await asyncio.to_thread(self.store.organisations):
            async with self._lock:
                counted["settled"] += await asyncio.to_thread(
                    settle_quietly, self.store, org_id)
                if not self.enabled:
                    continue
                for row in await asyncio.to_thread(self.store.unconverted, org_id):
                    made = await self._convert(org_id, row)
                    if made is None:
                        continue
                    counted["converted"] += 1
                    if (counted["started"] < MAX_STARTS_PER_SWEEP
                            and await self._start(org_id, made)):
                        counted["started"] += 1
                if not await asyncio.to_thread(self.store.autobuild, org_id):
                    continue
                for row in await asyncio.to_thread(self.store.awaiting_run, org_id,
                                                   max_tries=MAX_TRIES):
                    if counted["started"] >= MAX_STARTS_PER_SWEEP:
                        # The rest keep their place in the queue: they are
                        # still `proposed` with no run, so the next beat finds
                        # them exactly where this one left them.
                        break
                    if await self._start(org_id, row):
                        counted["started"] += 1
        if any(counted.values()):
            log.info("the feedback sweep converted %d, started %d and settled %d",
                     counted["converted"], counted["started"], counted["settled"])
            await self._tell_them()
        return counted

    async def sweeping(self) -> None:
        """The sweep, for ever, on its beat. Started by `server.startup`.

        Once at the start - a process that has just come up is exactly where a
        half-finished conversion is waiting - and then every `sweep_minutes`.
        It must never be the reason this process stops, so everything it can
        raise is logged and the beat goes on.
        """
        while True:
            try:
                await self.sweep()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("the feedback sweep stumbled; continuing")
            await asyncio.sleep(self.sweep_minutes * 60)

    # --- the two halves -----------------------------------------------------

    async def _convert(self, org_id: str, feedback: gt.Feedback) -> gt.FeatureRequest | None:
        """Read one feedback and write the feature request. None when it was not.

        The check that nothing has been made from it already is done here
        rather than by the caller, because both callers can race: a sweep that
        starts while a submission is still being read would otherwise write a
        second request for the same sentence.
        """
        already = await asyncio.to_thread(
            self.store.list_requests, org_id, from_feedback=feedback.id)
        if already:
            return None
        files = await asyncio.to_thread(self.store.files_for, gt.FEEDBACK, feedback.id)
        decision = (await decide(feedback, files, org_id=org_id) if self.read_with_model
                    else guess(feedback))
        made = await asyncio.to_thread(
            self.store.add_request, org_id=org_id, user_id=feedback.user_id,
            author=feedback.author, title=decision.title, body=decision.body,
            kind=decision.kind, from_feedback=feedback.id, automatic=True)
        # Picked up, and the left column says so without anybody reading the
        # right one against it. A feedback somebody has already marked done or
        # declined is left where it is: that was a decision, and this is not
        # the place to undo it.
        if feedback.status in ("new", "triaged"):
            await asyncio.to_thread(
                self.store.set_feedback_status, org_id, feedback.id, "planned")
        log.info("feedback %s became %s (%s), read by %s",
                 feedback.id, made.id, made.kind, decision.how)
        return made

    async def _start(self, org_id: str, request: gt.FeatureRequest) -> bool:
        """Start the run that builds it. False when it could not be started.

        The same `starting.start` every other run on this machine goes through,
        under the preset for a change to Rouh's own code, and briefed with
        exactly what is on the card: the reading, the person's own words
        underneath it, and every attached file by its path on disk.

        Every run this class starts is started here, so this is the one place
        the board's switch is read (`GeneTherapyStore.autobuild`), and it is read
        at the last moment rather than when the feedback arrived: a switch
        turned off while the model is still reading one holds that one back
        too. Off is not a failure. Nothing is written on the card and no try
        is counted, because nothing was tried; the request simply waits.
        """
        if request.run_id or request.status not in ("proposed", "building"):
            return False
        if request.run_tries >= MAX_TRIES:
            return False
        if not await asyncio.to_thread(self.store.autobuild, org_id):
            log.info("%s is waiting for a run: automatic build is off for %s",
                     request.id, org_id)
            return False
        source = await asyncio.to_thread(
            self.store.get_feedback, org_id, request.from_feedback) \
            if request.from_feedback else None
        brief = gt.compose_brief(
            request,
            files=await asyncio.to_thread(self.store.files_for, gt.REQUEST, request.id),
            source=source,
            source_files=(await asyncio.to_thread(
                self.store.files_for, gt.FEEDBACK, source.id) if source else ()),
        )
        try:
            started = await self.start_run(brief=brief, title=request.title,
                                           preset=PRESET, org_id=org_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            why = str(exc) or type(exc).__name__
            if request.run_tries + 1 >= MAX_TRIES:
                # The last try. Said on the card, because a card that goes on
                # saying "no run yet" while nothing is trying any more is the
                # kind of quiet stop that nobody notices for a month.
                why += (" It is not being tried again by itself; press Start a run"
                        " when there is something here to run it.")
            log.warning("no run could be started for %s: %s", request.id, why)
            await asyncio.to_thread(self.store.run_failed, org_id, request.id, why)
            return False
        run_id = str((started or {}).get("id") or "")
        if not run_id:
            await asyncio.to_thread(
                self.store.run_failed, org_id, request.id,
                "Whatever took it did not say which run it is.")
            return False
        await asyncio.to_thread(self.store.set_run, org_id, request.id, run_id)
        log.info("run %s started for %s", run_id, request.id)
        return True

    async def _tell_them(self) -> None:
        """Every open board, redrawn, without anybody reloading anything."""
        if self.on_change is None:
            return
        with contextlib.suppress(Exception):
            await self.on_change()
