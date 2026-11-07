"""The thinking half of Rouh: one turn of conversation, streamed.

Why a hand-written loop rather than the SDK's tool runner:

- The reply has to reach the voice as it is written, sentence by sentence. If we
  wait for the whole answer the person hears nothing for several seconds and the
  illusion of a conversation is gone.
- A turn has to be abandonable mid-sentence. When the person starts talking over
  Rouh, the model stream, the speech synthesis and the audio already queued in
  the browser all have to stop at once.
- Server-side tools can end a turn with `pause_turn`, which has to be resumed by
  re-sending. The Python tool runner exits silently in that case and returns a
  truncated answer.
- A page web_fetch could not read is read again in a browser in the middle of
  the reply, which means stopping the stream at the failed fetch and carrying
  the turn on from there (`rouh/fetchfallback.py`).

None of those are things the runner exposes, so the loop is written out here.
"""
from __future__ import annotations

import asyncio
import contextlib
import contextvars
import json
import logging
import re
import time
import uuid
from typing import Awaitable, Callable

import anthropic

from . import (attachments, chatkinds, citing, clock, context_editing, costs, demo, events,
               fetchfallback, heartbeat, keeping, llmlog, location, modelstandard, promptcache, replymode,
               retrying, rouhlinks, servercalls, telegram_chat, toolsearch, turnmarks, turntrace, untrusted,
               worklabel)
from . import memory as memory_mod
from .config import (GOOGLE, PROVIDER_NAMES, XAI, effort_for, is_openai, luna_ready, model_name,
                     provider_of, thinking_for)
from .stopping import STOP_NOTE
from .version import get_version

log = logging.getLogger("rouh.brain")


class _Stopped(Exception):
    """The person pressed Stop while this was being waited on."""


def _is_stopped(stop: asyncio.Event | None) -> bool:
    return stop is not None and stop.is_set()


async def _first_of(work: asyncio.Future, stop: asyncio.Event | None):
    """Wait for `work`, unless the person stops the turn first.

    Raises :class:`_Stopped` in that case, with `work` left exactly as it was:
    what happens to it next is the caller's decision, and it is not the same
    decision for a model stream as it is for a round of tool calls.

    When both land together the work wins. It is finished, its result is real,
    and the stop is seen a moment later at the top of the loop instead.

    The `except` below is not tidiness, it is the whole of what makes this safe
    to put in the middle of a turn. A turn can still be cancelled outright from
    outside - barge-in, or switching to another chat while an answer is
    arriving - and `await something` passes that cancellation on to whatever is
    being awaited, while `asyncio.wait` deliberately does not. Without this the
    stream carried on reading and carried on emitting into a page that had
    moved on: pressing New chat while an answer was streaming put the last chat's
    answer into the new chat, drawn over the empty column. Found by
    a browser driven live, which does exactly that.
    """
    if stop is None:
        return await work
    waiting = asyncio.ensure_future(stop.wait())
    try:
        done, _ = await asyncio.wait({work, waiting}, return_when=asyncio.FIRST_COMPLETED)
    except asyncio.CancelledError:
        # Awaited rather than only cancelled: whoever cancelled this turn is
        # waiting for it to be over, and it is not over while something is
        # still streaming words at the browser.
        work.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await work
        raise
    finally:
        waiting.cancel()
    if work in done:
        return work.result()
    raise _Stopped()


#: Tool calls left running after the turn that asked for them was stopped. The
#: event loop keeps only a weak reference to a task, so without somewhere to
#: hold them they can be collected half way through - and half way through is
#: inside a tool that may be starting a background job.
_finishing: set = set()


def _let_it_finish(work: asyncio.Future) -> None:
    """Let a round of tool calls run on, and throw away what it gives back.

    Never cancelled. A tool call that has reached `assistant_job`,
    `delegate_task` or the one program has already handed work over, and the
    person stopping Rouh is not stopping that work. What it returns is simply
    never sent to a model, because the turn that wanted it is over.
    """
    _finishing.add(work)

    def done(task):
        _finishing.discard(task)
        if not task.cancelled() and task.exception() is not None:
            log.warning("a tool of a stopped turn failed: %s", task.exception())

    work.add_done_callback(done)


# A sentence ends at . ? ! … or a newline. Three things must not end one:
# a single initial ("A. Morgan"), a common abbreviation, and a decimal point.
# The decimal needs no rule of its own - the trailing (\s+|$) already refuses
# "3.5", because the character after the point is a digit and not a space.
# An earlier (?<!\d) here was worse than useless: it also blocked every
# sentence that ends in a number, which for an assistant that talks about money
# is most of them.
_ABBREV = r"(?<!\b[A-Z])(?<!\bMr)(?<!\bMrs)(?<!\bDr)(?<!\bSt)(?<!\bvs)(?<!\bNo)(?<!\be\.g)(?<!\bi\.e)"
_SENTENCE_END = re.compile(rf"{_ABBREV}([.!?…])(\s+|$)|(\n+)")

# Below this, a sentence is joined to the next one instead of being spoken
# alone: "Sure." on its own arrives clipped and with the wrong intonation.
MIN_SPOKEN_CHARS = 25
# Above this with no sentence end in sight, break at a comma or a space anyway,
# so a long unpunctuated stretch does not hold the voice silent.
FORCE_BREAK_CHARS = 320

# What a conversation is told. Until 21 October 2026 it was written here: `SYSTEM`, one long string, and
# a dozen paragraphs beside it added by which tools a turn had. Petar, that night: "lets move those to the
# rules please". Every word of it is a rule on the Rules page now, a rule of the person's in Synapse Master
# like any other (`rouh/rules.py`; until 30 October 2026 Rouh's own were "built-in", kept apart), and
# `Brain._system` puts them together with the live context only the code knows (`rouh/prompting.py`).
#
# Where the tool catalogue and the person's rules without a place of their own go among the rules placed in
# the cached part: after every placed rule they may overrule, before the turn marks.
CATALOGUE_AT = 160
PERSONAL_AT = 200
# Where Rouh's own address goes among them, and the date and the time in the part told with the clock.
OWN_MAIL_AT = 12
CLOCK_AT = 10
# And where the person's rules for a written or a spoken reply go in the part told with the clock: after this
# turn's own line, before the turn marks, last because the model reads the end of a system prompt best.
REPLY_RULES_AT = 910
#: The lines of live context a turn on the stage in demo mode is still told: the genes on offer and
#: whether Rouh may draft one, which are Rouh's own and nobody's life (`rouh/demo.py`).
_STAGE_CONTEXT = frozenset({140, 150})


#: The goals part of this turn's first system prompt, worked out at the start of the turn beside
#: the router rather than after it (`Brain.run_turn`): {"chat": ..., "text": ...}, used once.
GOALS_EARLY: contextvars.ContextVar[dict | None] = contextvars.ContextVar("rouh_goals_early", default=None)


def _goals_block(chat_id: str = "") -> str:
    """The goals in a few lines, and the whole of this chat's own, or ""."""
    early = GOALS_EARLY.get()
    if early is not None and early.get("chat") == chat_id and "text" in early:
        # Once: a later round of the same turn reads them again, since a step
        # marked done in it changes them.
        return early.pop("text")
    try:
        from . import goals

        return goals.block(chat_id)
    except Exception:  # noqa: BLE001 - a line of context is never worth a turn
        log.exception("the goals could not be read for the prompt")
        return ""


def _inboxes_line() -> str:
    """Which inbox is whose, or "" where no Google connection is wired in."""
    from . import inboxes

    if not inboxes.ready():
        return ""
    return inboxes.prompt_line()


def _subtask_block(chat_id: str = "") -> str:
    """A subtask's parent as background, or a task's notes from its subtasks."""
    if not chat_id:
        return ""
    from . import subtasknotes

    return subtasknotes.prompt_block(chat_id)


def _fork_task_block(chat_id: str = "") -> str:
    """Which task a fork of a task's chat is part of, or ""."""
    if not chat_id:
        return ""
    from . import forks

    return forks.task_block(chat_id)


def _task_files_block(chat_id: str = "") -> str:
    """The files uploaded to this chat's task, or ""."""
    if not chat_id:
        return ""
    from . import objectindex

    return objectindex.files_block(chat_id)


def _rules_parts(memory, situation=None) -> list[tuple[str, dict]]:
    """The person's rules and words, each section with which rules it holds (`rules.prompt_parts`); the old
    facts when that fails."""
    try:
        from . import rules

        return rules.prompt_parts(memory.answering_chat() or "", situation)
    except Exception:
        log.exception("the rules could not be read for the prompt; the old memory is said instead")
        old = memory.facts_block(keeping.project_names()).strip("\n")
        return [(old, {"key": "rules:old-memory", "title": "The old memory",
                       "why": "the Rules page could not be read"})] if old else []


def _reply_parts(mode: str, situation=None) -> list[tuple[str, dict]]:
    """The person's rules for this turn's reply, written or spoken (`rules.reply_parts`)."""
    from . import rules

    return rules.reply_parts(mode, situation)


def _master_now():
    """The person's Master for this turn, with the defaults every Rouh starts with taken in
    (`ruledefaults.ensure`); None when it cannot be read, and the prompt is put together without rules."""
    try:
        from . import ruledefaults, rules

        ds = rules.master()
        ruledefaults.ensure(ds)
        return ds
    except Exception:  # noqa: BLE001 - a turn is never lost to its rules
        log.exception("Synapse Master could not be read for the rules")
        return None



def _plain(user_content) -> str:
    """The words of what the person said, whether a string or blocks."""
    if isinstance(user_content, str):
        return user_content
    return " ".join(str(b.get("text") or "") for b in user_content or []
                    if isinstance(b, dict) and b.get("type") == "text")


def start_seeds(session_id: str, user_content):
    """The seed lookup on the person's message (D84), on a thread of its own, as a `messageseeds.Pending`, or
    None when there are no words."""
    text = _plain(user_content).strip()
    if not text:
        return None
    import contextvars
    import functools

    from .synapse import messageseeds

    # Handed to a thread now, not when the loop next gets round to a coroutine: the first message of a new
    # chat keeps the loop busy for about 300 ms (measured in a world), and `asyncio.to_thread` would only
    # start the lookup after that. The context goes with it, so it knows whose turn it is.
    early: dict = {}
    run = functools.partial(contextvars.copy_context().run, messageseeds.for_turn, session_id, text,
                            time.monotonic(), early)
    return messageseeds.Pending(asyncio.get_running_loop().run_in_executor(None, run), early)


async def seeds_for_turn(session_id: str, seeds, began: float) -> str:
    """What the lookup found, if it is back by now or within `message_seed_wait_ms` more; never longer.
    A lookup still running is left to finish on its thread, and its result waits for the turn's next
    request (`late_seeds`); the tasks the message names by number, which it finds first and without a
    vector, go now if it has them (attempt 22)."""
    if seeds is None:
        return ""
    from .synapse import messageseeds

    ready = seeds.done()
    waited = time.monotonic()
    named = None
    try:
        got = await asyncio.wait_for(asyncio.shield(seeds.future), messageseeds.wait_seconds())
    except asyncio.TimeoutError:
        got = "late"
        seeds.future.add_done_callback(lambda done: messageseeds.note_after(session_id, done))
        if seeds.early.get("block"):
            named = seeds.early.get("named")
    waited_ms = int((time.monotonic() - waited) * 1000)
    messageseeds.note(session_id, got, ready=ready, waited_ms=waited_ms,
                      prep_ms=int((waited - began) * 1000), named=named)
    if isinstance(got, dict):
        seeds.sent = "all"
        return got.get("block", "")
    if named:
        seeds.sent = "named"
        return seeds.early["block"]
    return ""


def late_seeds(session_id: str, seeds) -> str:
    """What a lookup that missed the first request found, once it is back: for the turn's next request.
    Only what the first request did not already carry: after the named tasks alone, only the matches."""
    from .synapse import messageseeds

    if seeds.sent == "all":
        return ""
    try:
        got = seeds.result()
    except Exception:  # noqa: BLE001 - `for_turn` never raises; this is only belt and braces
        return ""
    block = (got.get("match_block") if seeds.sent == "named" else got.get("block")) \
        if isinstance(got, dict) else ""
    seeds.sent = "all"
    if not block:
        return ""
    messageseeds.note_late(session_id, got)
    return "(Rouh's software, not the person:) " + block


def _seed_ids(seeds) -> list[str]:
    """The items a seed look-up that is back found, which recall's block need not say again."""
    if seeds is None or not seeds.done():
        return []
    try:
        back = seeds.result()
    except Exception:  # noqa: BLE001
        return []
    if not isinstance(back, dict):
        return []
    return [x["id"] for x in (back.get("named") or []) + (back.get("strong") or [])]


def start_recall(session_id: str, user_content, emit, *, note: bool = False, seeds=None, root=None,
                 keep=None):
    """Automatic recall on the person's own words, started the moment the turn is, as a
    `recalling.MessageMemory` (which also follows the message's seed look-up, `seeds`), or None.

    Whose words count (`rouh/synapse/autorecall.py`, Petar, 6 and 10 October 2026): a message the person wrote
    or said themselves (`signups.PERSON_TURN`, their own Telegram included); and, in a turn a note started,
    only a Clockwork reminder or scheduled work of theirs coming due (`autorecall.WORDS`) or an email from
    one of their own addresses that Gmail authenticated (`mail_turn.MailTurn.recall_words`), on those words
    and not the note's. Never a job's report, the heartbeat or anybody else's email, and never in Synapse's
    own chats. Its look-ups are twigs on the turn's line on the orb (`orb_only`) and bars on the message's
    timeline in the chat (`recall` on the socket); `keep` keeps that timeline with the message."""
    from . import mail_turn, recalling, signups
    from .synapse import autorecall

    words, source = "", "message"
    if not note:
        if signups.PERSON_TURN.get():
            words = _plain(user_content).strip()
    else:
        words, source = autorecall.WORDS.get().strip(), "clockwork"
        mail = mail_turn.CURRENT.get()
        if not words and mail is not None and mail.from_owner:
            words, source = (mail.recall_words or "").strip(), "email"
    if not words:
        return None
    memory = recalling.MessageMemory(session_id, words, emit, asyncio.get_running_loop(), seeds=seeds,
                                     root=root, source=source, keep=keep)
    memory.start(words)
    return memory


async def memory_for_turn(session_id: str, seeds, recall, began: float) -> tuple[str, str]:
    """What the turn's first request carries from Synapse Master: the seeds' block and recall's.

    Petar, by voice, 10 October 2026: "I definitely don't want answers to be limited to 2.5 seconds. At the
    very least, we can do better than that." Until then recall was cut off 2.5 s into the turn and whatever
    was not back was thrown away.

    The seeds are waited for as they always were (`seeds_for_turn`); recall up to `recall_wait_ms` from the
    moment the message came (`recalling.MessageMemory.first`). Seeds that came back while recall was being
    waited for go in too, and what recall says is not what the seeds already said.

    How long the turn waited here is a bar of its own on its timeline, and from here to the first
    request another (`turntrace.Trace.waited`, `ready`), so no time before the answer is unexplained."""
    trace = turntrace.current()
    since = time.time()
    try:
        return await _memory_for_turn(session_id, seeds, recall, began)
    finally:
        if trace is not None:
            trace.waited("Waiting for memory", since)
            trace.ready()


async def _memory_for_turn(session_id: str, seeds, recall, began: float) -> tuple[str, str]:
    found = await seeds_for_turn(session_id, seeds, began)
    if recall is None:
        return found, ""
    await recall.wait_first()
    if seeds is not None and seeds.sent != "all" and seeds.done():
        try:
            got = seeds.result()
        except Exception:  # noqa: BLE001
            got = None
        rest = (got.get("match_block") if seeds.sent == "named" else got.get("block")) \
            if isinstance(got, dict) else ""
        seeds.sent = "all"
        if rest:
            found = "\n\n".join(b for b in (found, rest) if b)
            log.info("seeds for %s: back while recall was waited for, so in the first request after all",
                     session_id)
    if seeds is not None and seeds.sent == "all":
        recall.seeds_given("in_time")
    return found, await recall.first(_seed_ids(seeds))


async def late_memory(session_id: str, seeds, recall) -> str:
    """What came back after the turn's first request, for the request after a round of tools: the seeds that
    missed it, and whatever recall's look-ups found since (`recalling.MessageMemory.late`). "" for nothing."""
    parts = []
    if seeds is not None and seeds.done() and seeds.sent != "all":
        block = late_seeds(session_id, seeds)
        if block:
            parts.append(block)
            if recall is not None:
                recall.seeds_given("late")
    if recall is not None:
        try:
            more = await asyncio.to_thread(recall.late)
        except Exception:  # noqa: BLE001 - more memory is never worth a turn
            log.exception("automatic recall's late block could not be made")
            more = ""
        if more:
            parts.append(more)
    return "\n\n".join(parts)


def _recall_on() -> bool:
    """Whether automatic recall is on, so the built-in rule about its block is told."""
    try:
        from .synapse import autorecall
        from .synapse import chat as synapse_chat

        ds = synapse_chat.master_for_turn()
        return bool(ds and autorecall.on(ds["org_id"]))
    except Exception:  # noqa: BLE001 - a paragraph is never worth a turn
        log.exception("whether recall is on could not be decided")
        return False



def _synapse_block(chat_id: str = "") -> str:
    """The open Synapse dataset, in its own chat, or ""."""
    if not chat_id:
        return ""
    try:
        from .synapse import chat as synapse_chat

        return synapse_chat.prompt_block(chat_id)
    except Exception:  # noqa: BLE001 - a line of context is never worth a turn
        log.exception("the Synapse dataset could not be read for the prompt")
        return ""


def _incubator_block(chat_id: str = "") -> str:
    """In the Incubator's own chat, what it is and what the list holds; "" in any other."""
    if not str(chat_id or "").startswith("incubator-"):
        return ""
    from . import incubator

    return incubator.prompt_block(chat_id)


def _gene_offers_block(chat: str) -> str:
    """Mutations' kept genes on offer (`rouh/evolution.py`), for a turn the person
    started: never a note of Rouh's own, an unattended turn, the heartbeat's or a mail's."""
    try:
        from . import evolution, mail_turn, protected
        from .tenancy import speaker

        if (heartbeat.held() or heartbeat.TURN_NOTE.get() or protected.UNATTENDED.get()
                or chat in heartbeat.CHATS or mail_turn.now() is not None):
            return ""
        who = speaker()
        return evolution.offers_block(who) if who is not None else ""
    except Exception:  # noqa: BLE001 - a line of context is never worth a turn
        log.exception("the genes on offer could not be put in the prompt")
        return ""


def _gene_drafts_line(chat: str) -> str:
    """May Rouh offer to draft a gene (`rouh/genedraft.py`): only when the person said so, and only in a
    turn they started."""
    try:
        from . import genedraft, mail_turn, protected
        from .tenancy import speaker

        if (heartbeat.held() or heartbeat.TURN_NOTE.get() or protected.UNATTENDED.get()
                or chat in heartbeat.CHATS or mail_turn.now() is not None):
            return ""
        return genedraft.prompt_line(speaker())
    except Exception:  # noqa: BLE001 - a line of context is never worth a turn
        log.exception("the genes on the fly line could not be put in the prompt")
        return ""


def _plain_words_block(chat: str, user_content, note: bool = False) -> str:
    """Plain words (`rouh/plain_words.py`): the rule for every turn, and the terms the person asked
    the meaning of. A term is kept only from a turn they started, never a note, the heartbeat's,
    an unattended turn or a mail's."""
    try:
        from . import mail_turn, plain_words, protected
        from .tenancy import speaker

        who = speaker()
        if not (note or heartbeat.held() or heartbeat.TURN_NOTE.get() or protected.UNATTENDED.get()
                or chat in heartbeat.CHATS or mail_turn.now() is not None):
            plain_words.notice(who, _plain(user_content))
            # The owner's own confusions go on Trials' list of problems, from the same reading.
            from . import trials

            if getattr(who, "is_admin", False):
                trials.owner_said(who, _plain(user_content), chat=chat)
        return plain_words.block(who)
    except Exception:  # noqa: BLE001 - a line of context is never worth a turn
        log.exception("plain words could not be put in the prompt")
        return ""


def _asked_again_block(chat: str, user_content) -> str:
    """A request the person keeps typing by hand, offered once as Clockwork work (`rouh/asked_again.py`):
    only in a turn they started, never a note, the heartbeat's, an unattended turn or a mail's."""
    try:
        from . import asked_again, mail_turn, protected
        from .tenancy import speaker

        if (heartbeat.held() or heartbeat.TURN_NOTE.get() or protected.UNATTENDED.get()
                or chat in heartbeat.CHATS or mail_turn.now() is not None):
            return ""
        return asked_again.for_turn(speaker(), _plain(user_content))
    except Exception:  # noqa: BLE001 - a line of context is never worth a turn
        log.exception("asked again could not be put in the prompt")
        return ""


def _meetings_block() -> str:
    """When to read a meeting with meeting_search and meeting_read, for a person who may read any, or ""."""
    try:
        from .synapse import meetings

        return meetings.prompt_line()
    except Exception:  # noqa: BLE001 - a line of context is never worth a turn
        log.exception("the meeting library's line could not be made for the prompt")
        return ""


def _own_mail() -> str:
    """This installation's own address, said in the prompt as a live value (`inbox.own`), and the others that
    reach the same inbox; "" when it has none."""
    from .inbox import own

    mine = own()
    if not mine:
        return ""
    others = mine[1:]
    return mine[0] + (f"; {', '.join(others)} {'reaches' if len(others) == 1 else 'reach'} the same inbox"
                      if others else "")


def _born_name(org: str) -> tuple[str, str] | None:
    """This Rouh's own name and the day it was born, for the rule that names it
    (`rouh/birth.py`), or None before its birth."""
    try:
        from datetime import datetime

        from . import birth

        row = birth.current(org)
        if row is None:
            return None
        day = datetime.fromtimestamp(row.born_at, clock.zone())
        return row.name, f"{day.day} {day.strftime('%B %Y')}"
    except Exception:  # noqa: BLE001 - a line of context is never worth a turn
        log.exception("the Rouh's own name could not be read for the prompt")
        return None


def _nickname_now(org: str) -> str:
    """The nickname the person this turn is for gave this Rouh, on top of "Rouh" (Rouh profile,
    `birth.set_human_names`), or "" when they gave none or the turn is nobody's."""
    try:
        from . import birth
        from .tenancy import speaker

        who = speaker()
        return birth.nickname(org, who.user_id) if who is not None and org else ""
    except Exception:  # noqa: BLE001 - a line of context is never worth a turn
        log.exception("the nickname this Rouh was given could not be read for the prompt")
        return ""


def _new_rouh(org: str) -> bool:
    """Whether the chat is to take the owner through the rest of setting up (`firstrun.guiding`)."""
    try:
        from .web import firstrun

        return firstrun.guiding(org)
    except Exception:  # noqa: BLE001
        log.exception("the first run could not be read for the prompt")
        return False


def _rouh_hosts() -> str:
    """This installation's own public addresses, for the built-in rule about links to Rouh
    (`config.public_host_list`)."""
    from .config import config

    hosts = config.public_host_list()
    return "".join(f"{h}, " for h in hosts[:-1]) + (f"{hosts[-1]} or " if hosts else "")


def _luna_names(model) -> dict:
    """The model answering when it is not Claude, for the built-in rule that says which: Luna, or
    any other of OpenAI's on the list (`config.OPENAI_CHOICES`), each of which answers through
    `rouh/luna.py`, or one of Google's or xAI's (`rouh/compat.py`), with whose it is."""
    from .config import LUNA, model_name

    model = model if isinstance(model, str) and model else LUNA
    name = model_name(model)
    return {"name": name, "model": "GPT-6 Luna" if model == LUNA else name,
            "company": PROVIDER_NAMES.get(provider_of(model), "")}



def _tool_names(tools) -> set[str]:
    try:
        return set(tools.names()) if tools is not None else set()
    except Exception:
        return set()


class Question:
    """The person's words, written down once and not before.

    Nothing of a turn reaches the database until the model has read the mark
    and said the question was whole (`rouh/turnmarks.py`), because a question
    stored before that is a fragment stored for ever: they paused mid-thought,
    the turn was abandoned, and half a sentence is left in the conversation for
    every later turn to read.

    Every other ending writes it down, whatever became of the answer. A turn
    that really happened and left no trace of what was asked is a conversation
    with an answer and no question in front of it - and the person, who can see
    their own words on the screen, opens their phone and finds them gone.
    """

    def __init__(self, memory, session_id: str, content, taken=None, slot=None,
                 note: bool = False, spoken: bool = False):
        self.memory = memory
        self.session_id = session_id
        self.content = content
        self.taken = taken
        #: Which exchange this question belongs to and which try it is
        #: (`memory.Slot`). An empty one is a question asked for the first
        #: time, and it becomes its own exchange the moment it is written.
        self.slot = slot if slot is not None else memory_mod.Slot()
        #: Not the person's words at all but a note of Rouh's own software,
        #: written down as one so it is never drawn under their name
        #: (`memory.Memory.add_message`).
        self.note = note
        #: Said aloud, into the microphone or as a voice note, rather than
        #: typed (`rouh/replymode.py`), kept on the row as `spoken`.
        self.spoken = spoken
        self.written = False
        #: The message's memory under way (`recalling.MessageMemory`), told the row's id once it has one.
        self.recall = None

    def write(self) -> None:
        """Put it in the conversation, if it is not there already."""
        if self.written:
            return
        self.written = True
        mine = self.memory.add_message(
            self.session_id, "user", self.content, spoken=self.spoken,
            root=self.slot.root, version=self.slot.version,
            # A later try takes over here and nowhere else, in the same
            # transaction that writes the new question, so the exchange is
            # never without a live version of itself.
            supersede=self.slot.version > 1, note=self.note)
        if self.slot.root is None:
            self.slot.root = mine
        # What its look-ups in Master did is kept with it from now on (`rouh/recalling.py`).
        if self.recall is not None and not self.note:
            self.recall.written(mine)
        # Their words stop being pending the moment they are written down.
        if self.taken is not None:
            self.taken(mine)


#: The most a plain answer's conversation may be, in characters, to be one of the Rouh
#: pool's double calls: about 20,000 tokens, so a second model reading it costs cents.
DOUBLE_MOST_CHARS = 80_000


class Brain:
    def __init__(self, cfg, memory, tools, files=None):
        self.cfg = cfg
        self.memory = memory
        self.tools = tools
        self.files = files or attachments.Attachments(cfg.data_dir)
        # max_retries=0 on purpose. The SDK retries too, and two layers of
        # backoff round one request is three HTTP calls per attempt, a wait
        # nobody chose, and a count nothing can reason about. The policy lives
        # in `rouh/retrying.py`, which knows the one thing the SDK cannot:
        # whether this attempt has already said something out loud.
        #
        # Every request it sends is written down, tries and all (`llmlog.py`).
        # Made again whenever the key changes, so a key kept on the first run's
        # page (`claude_signin.keep_key`) reaches the next turn with no restart.
        self._client = None
        self._client_key: str | None = None
        #: How big the window of each chat's last request was, in tokens, from
        #: the API's own numbers. The next turn in that chat trims to its
        #: budget from this before its first request, because a turn is never
        #: trimmed to a budget between two of its own (`_edit_context`).
        self._windows: dict[str, int] = {}

    @property
    def client(self):
        """Anthropic's client for the key this Rouh has now (see `__init__`)."""
        key = self.cfg.anthropic_api_key
        if self._client is None or key != self._client_key:
            self._client = llmlog.client(key, max_retries=0)
            self._client_key = key
        return self._client

    def _thinking(self, model: str) -> dict | None:
        """The thinking to ask `model` for, or nothing to send.

        Turned on by hand (`ROUH_THINKING`), for any model, as it always was.
        Otherwise only for a model that thinks whether or not it is asked,
        where saying so changes nothing but that what it thought comes back as
        words rather than as an empty block (`config.thinking_for`).
        """
        display = getattr(self.cfg, "thinking_display", "") or "summarized"
        if getattr(self.cfg, "thinking", False):
            return {"type": "adaptive", "display": display}
        return thinking_for(model, display)

    def system_text(self, openai: bool = False) -> str:
        """The system prompt as plain text, for anything that reads it back.

        `openai` is the prompt a turn answered by Luna is given, which differs
        from Claude's only in the rules kept to an OpenAI model: which model it
        is ("model-luna") and the web with one tool ("web-luna").
        """
        return "\n\n".join(block["text"] for block in self._system(openai=openai))

    def _tool_plan(self, entries, model: str) -> toolsearch.Plan:
        """What a request to this model declares: the tools and their catalogue."""
        return toolsearch.anthropic_plan(
            entries, model=model, wanted=getattr(self.cfg, "tool_search", "regex"),
            always=getattr(self.cfg, "tools_always_loaded", ()))

    def _system(self, plan: toolsearch.Plan | None = None,
                openai: bool | str = False, seeds: str = "", recall: str = "",
                asked: str = "") -> list[dict]:
        """The system prompt as two blocks: the part that is the same for every
        turn, cached, and the clock after it, which is not.

        Every word of it that is an instruction is a rule on the Rules page
        (`rouh/rules.py`), each told where its row says it applies: those with
        a place of their own at that place (`rules.placed`), the rest in the
        person's sections. Everything else in it is live context the code
        works out, named as such in what the request was told
        (`prompting.told`).

        `plan` is the turn's tools (`rouh/toolsearch.py`), whose catalogue goes
        into the cached part: one line per tool, the same from one turn to the
        next, in front of the person's rules, which change more often.

        `openai` is the one Luna is given (`rouh/luna.py`): the rules kept to
        an OpenAI model are told instead of Claude's.

        `seeds` are what the person's message found in Synapse Master
        (`seeds_for_turn`), for this turn alone, after the clock, and
        `recall` what automatic recall found about what it names
        (`memory_for_turn`), after them."""
        from . import owner, prompting, rules as rules_mod
        from .modeldefaults import org_now

        names = _tool_names(getattr(self, "tools", None))
        # Which kind of model answers: Claude, OpenAI's (Luna's loop), or Google's or xAI's
        # (`rouh/compat.py`), which is given no web tool, so no rule about one is told.
        kind = "claude" if not openai else (
            "other" if isinstance(openai, str) and provider_of(openai) in (GOOGLE, XAI) else "luna")
        if kind == "other":
            names = {n for n in names if n not in ("web_search", "web_fetch", "code_execution")}
        # How this turn came and how its reply goes out, written or spoken (`rouh/replymode.py`).
        mode = replymode.NOW.get()
        chat = self.memory.answering_chat() or ""
        org = org_now()
        mine = _own_mail()
        flags = {"own_mail" if mine else "no_own_mail"}
        # Its own name, once it is born, and the rest of setting up for a few days after its
        # first run (`rouh/birth.py`, `rouh/web/firstrun.py`).
        born = _born_name(org)
        if born:
            flags.add("born")
        # A nickname the person gave it on top of "Rouh", which it answers to as well.
        nick = _nickname_now(org)
        if nick:
            flags.add("nicknamed")
        if _new_rouh(org):
            flags.add("new_rouh")
        if untrusted.rule_needed(names):
            flags.add("untrusted")
        if _recall_on() and not demo.on_stage():
            flags.add("autorecall")
        situation = prompting.Situation(
            tools=frozenset(names), provider=kind, reply=mode.reply,
            heard=mode.heard, marks=mode.marks,
            channel="telegram" if telegram_chat.FROM_PHONE.get() is not None else "", flags=frozenset(flags))
        # On the stage in demo mode none of the person's own rules or words is told: the answer is
        # drawn as it is in front of an audience (`rouh/demo.py`).
        ds = _master_now()
        personal = [] if demo.on_stage() else _rules_parts(self.memory, situation)
        values = {"own_mail": mine, "rouh_name": born[0] if born else "", "born_day": born[1] if born else "",
                  "rouh_nickname": nick,
                  "app_dir": self.cfg.app_dir, "version": get_version()["human_readable"],
                  "repo": getattr(self.cfg, "assistant_repo", "") or "the folder configured for it",
                  "reading": "web_search" if openai else "web_search and\nweb_fetch",
                  "hosts": _rouh_hosts(),
                  "finished": turnmarks.FINISHED, "cut_off": turnmarks.CUT_OFF_MID_THOUGHT,
                  "still_thinking": turnmarks.STILL_THINKING}
        if openai:
            values.update(_luna_names(openai))
        cached = prompting.Prompt(situation, "cached", values, placed=rules_mod.placed(ds, "cached"))
        # Rouh's own address is a live value, not a rule (until 30 October 2026 the rule "own-mail").
        cached.at(OWN_MAIL_AT)
        if mine:
            cached.context(f"Your own email address is {mine}.", "Rouh's own email address", "rouh/inbox.py")
        cached.at(CATALOGUE_AT)
        if plan is not None and plan.catalogue:
            cached.add(plan.catalogue, kind="catalogue", key="rouh/toolsearch.py", title="The tool catalogue",
                       why="made from the tool registry for this request's tools; never a rule")
        # The person's own rules and words, word for word, after every built-in rule they can overrule, and
        # before the turn marks, which are last on purpose: the rule about the very first character of every
        # reply, and the model reads the end of a system prompt best (`rouh/turnmarks.py`).
        cached.at(PERSONAL_AT)
        for words, meta in personal:
            cached.add(words, kind="personal", **meta)
        text, segments = cached.finish(say=owner.say)
        prompting.keep(org, text, segments)

        # The part told with the clock: the person's clock, not this machine's (`clock.zone`).
        now = clock.now()
        turn = prompting.Prompt(situation, "turn", {
            "came": replymode.came(mode), "today": now.strftime("%A, %d %B %Y"), "now": now.strftime("%H:%M"),
            "place": clock.place(), "offset": clock.offset(now), "finished": turnmarks.FINISHED,
            "cut_off": turnmarks.CUT_OFF_MID_THOUGHT, "still_thinking": turnmarks.STILL_THINKING},
            placed=rules_mod.placed(ds, "turn"))
        # The date and the time are live values, not a rule; what to make of them is the rule after them.
        turn.at(CLOCK_AT)
        turn.context(f"Today is {now.strftime('%A, %d %B %Y')}. The time is {now.strftime('%H:%M')} where the "
                     f"person is, on {clock.place()} time, which is UTC{clock.offset(now)}.",
                     "The date and the time", "rouh/clock.py")
        for at, label, source, block in (
                # Where the person is, when they shared it in Settings.
                (20, "Where the person is", "rouh/location.py", location.prompt_line),
                # Which inbox is whose. Here and not in the cached part, because the person connects or
                # disconnects a mailbox in Settings at any time.
                (30, "Which inbox is whose", "rouh/inboxes.py", _inboxes_line),
                # The goals, and the whole of this chat's own: a step marked done changes it.
                (40, "The person's goals", "rouh/goals.py", lambda: _goals_block(chat)),
                # A subtask's parent as background, or a task's notes from its subtasks.
                (50, "The task's family", "rouh/subtasknotes.py", lambda: _subtask_block(chat)),
                # A fork of a task's chat says which task it is part of, which it may carry no words of.
                (55, "The task a fork is part of", "rouh/forks.py", lambda: _fork_task_block(chat)),
                # The files uploaded to this chat's task: one uploaded mid-conversation is known at once.
                (60, "The task's files", "rouh/objectindex.py", lambda: _task_files_block(chat)),
                # A Synapse dataset's own chat says which dataset is open.
                (70, "The open Synapse dataset", "rouh/synapse/chat.py", lambda: _synapse_block(chat)),
                # The Incubator's own chat says that it is, and what its list holds (`rouh/incubator.py`).
                (75, "The Incubator's chat", "rouh/incubator.py", lambda: _incubator_block(chat)),
                # The meeting library's meetings the person may read.
                (80, "The meeting library", "rouh/synapse/meetings.py", _meetings_block),
                # What the person's message found in Synapse Master (`rouh/synapse/messageseeds.py`).
                (90, "What the message found in Synapse", "rouh/synapse/messageseeds.py", lambda: seeds),
                # What automatic recall found, in its untrusted box (`rouh/synapse/autorecall.py`).
                (100, "Background memory", "rouh/synapse/autorecall.py", lambda: recall),
                # A turn from the phone: what was lately sent there (`telegram_chat.prompt_now`). Its
                # instruction is the built-in rule before it.
                (120, "What was sent to the phone", "rouh/telegram_chat.py", telegram_chat.prompt_now),
                # What the heartbeat noted silently since the person last talked to Rouh, once.
                (130, "What the heartbeat noted", "rouh/heartbeat.py", lambda: heartbeat.prompt_block(
                    chat, str((llmlog.current() or {}).get("turn_id") or ""))),
                # Kept genes on offer, only in a turn the person started (`evolution.offers_block`).
                (140, "Genes on offer", "rouh/evolution.py", lambda: _gene_offers_block(chat)),
                # Whether Rouh may offer to draft a gene, as the person set it (`genedraft`).
                (150, "Genes on the fly", "rouh/genedraft.py", lambda: _gene_drafts_line(chat)),
                # A request typed again and again, offered once as scheduled work, and plain words.
                (160, "Asked again, and plain words", "rouh/asked_again.py", lambda: asked)):
            turn.at(at)
            if demo.on_stage() and at not in _STAGE_CONTEXT:
                # What only the person's own life fills in, left out on the stage (`rouh/demo.py`).
                continue
            try:
                got = block()
            except Exception:  # noqa: BLE001 - a line of context is never worth a turn
                log.exception("%s could not be put in the prompt", label)
                got = ""
            if got:
                turn.context(got, label, source)
        # Last of all: how this turn reached them and how the reply reaches them (a built-in rule), the
        # person's rules for a written or a spoken reply, and the turn marks for words heard by the
        # microphone, the only ones that stop mid-thought. Here and not in the cached part, so a chat moving
        # between typing and talking reads the rest from the cache, and last because the model reads the end
        # of a system prompt best, which matters most for the mark on the very first character of a reply.
        turn.at(REPLY_RULES_AT)
        try:
            for words, meta in ([] if demo.on_stage() else _reply_parts(mode.reply, situation)):
                turn.add(words, kind="personal", **meta)
        except Exception:  # noqa: BLE001 - the rest of the prompt is still told
            log.exception("the rules for this reply could not be put in the prompt")
        said, told = turn.finish(say=owner.say)
        prompting.keep(org, said, told)
        # The breakpoint is on the first block, and it caches the tools with
        # it: everything in front of it is the same for every turn of every
        # chat until a rule changes or Rouh is deployed again.
        return [{"type": "text", "text": text, "cache_control": dict(promptcache.LONG)},
                {"type": "text", "text": said}]

    async def run_turn(
        self,
        session_id: str,
        user_content,
        emit: Callable[[dict], Awaitable[None]],
        on_sentence: Callable[[str], Awaitable[None]] | None = None,
        model: "str | None | asyncio.Future[str]" = None,
        stop: asyncio.Event | None = None,
        answer_now: bool = False,
        taken: Callable[[int], None] | None = None,
        slot: memory_mod.Slot | None = None,
        note: bool = False,
        steer: Callable[[], list[dict]] | None = None,
        turn_id: str = "",
        heard: str = "typed",
    ) -> str:
        """Run one turn to completion. Raises CancelledError if interrupted.

        The model says whether the person has finished asking before it answers,
        by starting its reply with one of three marks (`rouh/turnmarks.py`).
        A finished question is answered exactly as it always was, with the mark
        taken off the front. An unfinished one raises
        :class:`turnmarks.Unfinished` and leaves nothing behind it at all:
        nothing said, nothing shown, and nothing written to the conversation,
        so that what the person says next joins the same question rather than
        following half of it.

        `answer_now` is the other side of that: the wait has run out, or they
        have pressed Finish or send, so the request carries a note saying to
        answer what there is and the reply is taken whatever mark it starts
        with. `taken` is called, once, the moment their words are written down,
        which is what tells the caller those words are no longer pending.

        `note` says `user_content` is not the person's words but a note of
        Rouh's own software - a finished job's report, a run's question - and
        it is written down as one (`memory.Memory.add_message`).

        `stop` is the person's Stop control (`rouh/stopping.py`). It is read
        at every point this loop can be left cleanly - before each model call,
        while a response is still streaming, and before and while the tools of
        a round are running - and the turn is abandoned at the first of those
        it reaches. What that means is exact: no further model call, no further
        tool call, and nothing more spoken. Tool calls already in flight are
        left to finish, because their work is already happening and some of it
        was handed to a background worker, but their results are dropped rather
        than sent back to the model.

        `steer` hands over what the person sent while this turn was running,
        oldest first, and takes it off the queue: a list of `{id, content}`,
        empty when there is nothing (`runtime.Turn.take_waiting`). It is asked
        at the points the model can take something new without anything being
        cut short - before the first request, and once the results of a round
        of tools are back, before the model decides what to do next - and what
        it hands over goes into the conversation there, as the person's own
        messages (`_take_steer`). A tool already running is never interrupted
        for it. What is still waiting when the answer ends is the next turn's,
        which is the caller's to start.

        Everything the turn asks of a model is one turn in the log of requests,
        under this chat: its own requests, tries and all, and whatever a tool
        it calls asks, a subagent's lookups among them (`rouh/llmlog.py`).

        `heard` is how the person's words came - `voice`, `voice_note`,
        `typed`, `telegram` or `note` - and with whether the reply is spoken
        (`on_sentence`) it says how the reply is made, written or spoken, and
        whether the turn marks are asked for (`rouh/replymode.py`).
        """
        mode = replymode.of(replymode.heard_as(heard, note=note), spoken_reply=on_sentence is not None,
                            answer_now=answer_now)
        # This turn's own context: every prompt it builds, Claude's or Luna's, reads it (`Brain._system`).
        replymode.NOW.set(mode)
        # And the words it answers, which name who it is about before they are in the conversation
        # (`rules.involved_people`).
        from . import rules as rules_mod

        rules_mod.TURN_WORDS.set(_plain(user_content))
        question = Question(self.memory, session_id, user_content, taken, slot, note=note,
                            spoken=mode.spoken_in)
        # The cheap seed lookup in Synapse Master, started now so that it runs
        # beside everything the turn does before its first request (D84).
        # Neither on the stage in demo mode, which is told nothing of the person's memory (`rouh/demo.py`).
        stage = demo.on_stage()
        seeds = None if note or stage else start_seeds(session_id, user_content)
        # And automatic recall of what the message is about, beside it, on the
        # person's own words only (`start_recall`): their message, or a
        # reminder of theirs or an email of theirs that started a note.
        recall = None if stage else start_recall(
            session_id, user_content, emit, note=note, seeds=seeds,
            root=question.slot.root if question.slot.again else None,
            keep=getattr(self.memory, "note_recall", None))
        question.recall = recall
        # A chat on Auto hands its model over as the router's decision still being
        # made (`rouh/modelrouter.py`), and it is waited for only now, so it runs
        # beside the look-ups just started rather than in front of them. A router
        # that fails leaves the chat's own fallback to answer.
        # The goals part of the system prompt, which reads every goal and its plan,
        # worked out beside the router too rather than after it (`_goals_block`).
        goals_early = asyncio.ensure_future(asyncio.to_thread(_goals_block, session_id))
        if asyncio.isfuture(model):
            pending = model
            trace = turntrace.current()
            since = time.time()
            try:
                model = await pending
            except asyncio.CancelledError:
                pending.cancel()
                raise
            except Exception:
                log.exception("the router's decision for %s was lost", session_id)
                model = None
            if trace is not None:
                trace.waited("Waiting for the model decision", since)
        try:
            GOALS_EARLY.set({"chat": session_id, "text": await goals_early})
        except Exception:  # noqa: BLE001 - the prompt reads them itself then
            GOALS_EARLY.set(None)
        try:
            with llmlog.about(purpose="turn", session_id=session_id,
                              turn_id=turn_id or "turn-" + uuid.uuid4().hex[:12]):
                return await self._turn(session_id, user_content, emit, on_sentence,
                                        model, stop, answer_now, question, seeds, recall,
                                        steer)
        except (turnmarks.Unfinished, asyncio.CancelledError):
            # Two endings that leave the question unwritten on purpose. An
            # unfinished mark means it is not a whole question yet; being
            # cancelled means the person talked over the answer, and their
            # words are still pending so that what they say next joins them.
            # Either way, writing them down here would be writing them twice.
            raise
        except BaseException:
            # Anything else - a model that would not answer, a key that is not
            # there, a bug of ours. They asked, so the conversation says so.
            question.write()
            raise
        finally:
            # Whatever its look-ups have still to bring goes to the next message
            # in this chat (`recalling.MessageMemory.over`).
            if recall is not None:
                recall.over()

    async def _turn(
        self,
        session_id: str,
        user_content,
        emit: Callable[[dict], Awaitable[None]],
        on_sentence: Callable[[str], Awaitable[None]] | None,
        model: str | None,
        stop: asyncio.Event | None,
        answer_now: bool,
        question: Question,
        seeds=None,
        recall=None,
        steer=None,
    ) -> str:
        """One turn, with `run_turn` above holding the rule about the question."""
        # How long each part of the turn took, from here, for the line in the
        # log and the row in `spend` (`_timed`). Monotonic, because a turn is
        # a stretch of time and the wall clock can be moved under it.
        began = time.monotonic()
        timing = {"first_token": None, "first_text": None, "first_word": None,
                  "requests": 0, "loaded": []}
        if on_sentence is not None:
            speak = on_sentence

            async def on_sentence(sentence: str) -> None:
                if timing["first_word"] is None:
                    timing["first_word"] = time.monotonic() - began
                await speak(sentence)
        # What this chat is sent, by its kind (`rouh/chatkinds.py`): General a
        # window of its newest messages with the old tool results trimmed, and
        # every other chat the whole of its conversation, as it was said.
        rules = chatkinds.profile(session_id, self.cfg)
        # And who answers: the model the turn was started with, which is its
        # chat's tier's (`chatkinds.model_for`), or worked out here for a caller
        # that did not say. How deeply it thinks comes with the model
        # (`modelstandard.effort`), whichever model that is.
        model = model or chatkinds.model_for(session_id, self.cfg)
        level = modelstandard.effort(model)
        # An OpenAI model, when the chat's tier is one (`rouh/modeldefaults.py`).
        # Its turn is a loop of its own over OpenAI's Responses API
        # (`rouh/luna.py`), so nothing below this changes for Anthropic's.
        # A Google or xAI model: a loop of its own over their Chat Completions APIs
        # (`rouh/compat.py`), with the organisation's own key for that provider.
        if provider_of(model) in (GOOGLE, XAI):
            from . import providerkeys

            if providerkeys.has(provider_of(model)):
                from . import compat
                return await compat.turn(self, session_id, user_content, emit, on_sentence,
                                         model, stop, answer_now, question, rules=rules,
                                         timing=timing, began=began, level=level, seeds=seeds,
                                         recall=recall, steer=steer)
            log.warning("%s was asked for and there is no %s key; not answering", model,
                        provider_of(model))
            raise RuntimeError(f"{model_name(model)} cannot answer here: there is no "
                               f"{PROVIDER_NAMES[provider_of(model)]} key. Add one in Anatomy, Rouh Land Account, Models.")
        if is_openai(model):
            if luna_ready(self.cfg):
                from . import luna
                return await luna.turn(self, session_id, user_content, emit, on_sentence,
                                       model, stop, answer_now, question, rules=rules,
                                       timing=timing, began=began, level=level, seeds=seeds,
                                       recall=recall, steer=steer)
            # No key to ask it with. Never another model instead (Petar, the evening
            # of 18 October 2026: "Whatever we select here should be the one called.
            # No exceptions."): the turn fails, saying why, and the Models page says
            # the same beside the use.
            log.warning("%s was asked for and there is no OPENAI_API_KEY; not answering", model)
            raise RuntimeError(f"{model_name(model)} cannot answer here: there is no OpenAI key. "
                               "Pick another model for this chat on the Models page.")
        # An exchange being answered again is asked from where it was asked the
        # first time: the window stops in front of it, so the model is not
        # shown its own old answer to the very question it is being asked.
        # On a thread, as the system prompt below: on the loop they held every tab.
        history = await asyncio.to_thread(
            self.memory.history, session_id, rules.history, before=question.slot.root,
            # A fork carries what it came off the way that chat is sent itself.
            limit_of=lambda chat: chatkinds.profile(chat, self.cfg).history)
        log.info("a %s turn in %s, with %s of history, on %s",
                 rules.kind, session_id,
                 f"all {len(history)} messages" if rules.history < 0
                 else f"the newest {len(history)} messages", model)
        messages = history + [{"role": "user", "content": user_content}]
        noted = answer_now and replymode.NOW.get().marks
        if noted:
            # Only where the marks were asked for: a typed message is finished
            # by being sent, and there is no mark to tell it to start with.
            # On the request and never in the database: this is Rouh's own
            # software talking, and the conversation is between two other
            # people. `turnmarks.is_note` is how anything that does read it
            # back can tell.
            messages = messages + [{"role": "user", "content": turnmarks.ANSWER_NOW}]
        # What goes into the transcript is the small marker for each attached
        # file; what goes to the model is the file itself, read from disk here
        # and never kept in the database. Storing the first and expanding the
        # second is the order that keeps those two apart.
        messages = attachments.hydrate(messages, self.files)
        # A chat Luna answered in before the box went back to Claude carries
        # Luna's footnotes in the shape Rouh keeps them, which is not a shape
        # Anthropic takes back. Only those are touched; a chat Claude alone
        # has answered comes through as the very same list.
        messages = citing.for_anthropic(messages)

        # Every tool is declared and, unless the config says otherwise, every
        # one is deferred: the model is handed a search tool and a catalogue,
        # and loads what it needs (`rouh/toolsearch.py`). Which mode depends on
        # the model, so a fallback to one that cannot defer gets its own plan.
        entries = self.tools.entries()
        plan = self._tool_plan(entries, model)
        # A search in the history names the tools it loaded, and a name this
        # request does not declare is a 400 on this turn and every one after.
        messages = toolsearch.clean_references(messages, plan.declared)
        # Once a turn, and not once a request. It carries the time to the
        # minute and the facts remembered so far, so rebuilt before every round
        # of tools it changed under a turn that crossed a minute or saved a
        # fact. Opus 5.5 binds its thinking to the system prompt it was written
        # under and refuses to be handed that thinking back under another one,
        # on the accounts it enforces that for: the turn would stop, mid-answer,
        # on a 400. And every round trip of the turn reads the one before it
        # out of the prompt cache only while nothing in front of it has
        # changed (`rouh/promptcache.py`).
        found, remembered = await memory_for_turn(session_id, seeds, recall, began)
        # The asked-again offer and plain words, worked out once a turn. Named `again`, not
        # `asked`, which is the model the request asks for below.
        again = "" if question.note else await asyncio.to_thread(_asked_again_block, session_id,
                                                                 user_content)
        plain = await asyncio.to_thread(_plain_words_block, session_id, user_content, question.note)
        if plain:
            again = (again + "\n\n" + plain) if again else plain
        system = await asyncio.to_thread(self._system, plan, seeds=found, recall=remembered, asked=again)
        spoken_buffer = ""
        full_text: list[str] = []
        # The words of the response being streamed right now. Everything a
        # finished response said is stored whole, from `final.content`, the
        # moment it arrives; this is the part that has not reached the database
        # yet, and it is what a stop has to store for itself.
        this_call: list[str] = []
        # Whether this turn did anything but answer in words: any tool of Rouh's or of
        # Anthropic's. Only a turn that did nothing else may be a double call (`_double`).
        acted = False
        usage = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0,
                 "cache_write_1h": 0, "trimmed": 0, "calls": []}
        # What the window holds before the first request goes out. The history
        # that came back from the database is whole, tool results and all, and
        # in General most of those are pages nobody will read again. See
        # `rouh/context_editing.py` for why the bodies go and the words stay.
        # This is the one place General's window is trimmed, to its age and,
        # if its last request went past the budget, to its size. Every other
        # chat goes out exactly as it was said (`rouh/chatkinds.py`).
        #
        # After `usage` exists, not before it: what this pass trims is part of
        # what the turn did, and the line under the answer says so.
        messages = await self._edit_context(
            messages, emit, rules, window=self._windows.get(session_id, 0), usage=usage)
        # The conversation as it stands before the first tool is called. Every
        # round trip of this turn sends it again, byte for byte, so its last
        # block is a breakpoint on each of them: the first request writes it to
        # the prompt cache and every later one reads it back
        # (`rouh/promptcache.py`).
        #
        # Its last block that is part of the conversation, which is not always
        # its last block. A question answered now carries `ANSWER_NOW` after
        # it, on the request and never in the database, so a mark on that note
        # was a prefix no later turn could send: the next turn's history has
        # the answer where this one had the note, and read nothing back. Every
        # turn of a topic chat, which is sent whole, wrote its whole history to
        # the cache again at more than the full price. On the question, the
        # next turn reads everything up to it out of the cache instead; the
        # note is still marked on the first request as its newest message.
        anchor = len(messages) - (2 if noted else 1)
        restarts = 0
        stopped = False
        # Only the first reply of a turn judges the question: by the time a
        # tool result has come back the question has been answered as finished
        # already, and the mark on what follows is stripped and no more. Off
        # altogether when the answer was asked for outright.
        judging = not answer_now

        container_id: str | None = None
        # Which of Anthropic's own tools each server call was, by its id, so
        # the line that says it finished names it as the line that said it
        # started did: a search's result block is not called what it searched
        # with.
        server_names: dict[str, str] = {}
        # A page web_fetch could not read is read again in a browser, and the
        # reply carries on from what the browser read; a link to Rouh itself
        # is read inside Rouh instead, never outside (`rouh/fetchfallback.py`).
        second = fetchfallback.Second(getattr(self.tools, "browsing", None), links=self.tools)
        sent_at = time.monotonic()
        first = True
        while True:
            # Before the request is even built. A stop that lands between the
            # tools coming back and the next question going out must not spend
            # another model call.
            if _is_stopped(stop):
                stopped = True
                break
            # Anything the person sent while this turn was getting ready, or
            # while it was waiting for the last turn to end, goes in under the
            # question before the model has read anything. In front of the note
            # that asks for an answer now, which is the request's own and says
            # nothing about what they asked. Not while the model is still to
            # say whether the question is whole (`judging`): that question is
            # not written down yet, and these must not be written above it.
            if first and not judging:
                taken = await self._take_steer(session_id, question, steer, emit)
                if taken:
                    messages[anchor + 1:anchor + 1] = taken
                    anchor += len(taken)
            first = False
            # Every call of Anthropic's own with its result where the API looks
            # for it, or not sent at all: one that lost its result is a 400 on
            # this request and, once stored, on every turn of the chat after it
            # (`rouh/servercalls.py`). The newest reply's calls may still be
            # waiting for this request, and are left to it.
            messages = servercalls.repair(messages, in_flight=True, where=session_id)
            asked = model
            request = dict(
                model=asked,
                max_tokens=self.cfg.max_tokens,
                system=system,
                # With its breakpoints: the start of the turn, and the newest
                # round of tool results, which the next request reads back.
                # A tool a search loaded is in that conversation, where the
                # search happened, so it is read back with the rest of it.
                messages=promptcache.marked(messages, anchor),
                tools=plan.tools,
            )
            # How deeply to think, but only to a model that takes the question.
            # Haiku 4.5 can be a tier's model, and an effort level is a 400
            # there, and a 400 is a turn that says nothing at all rather than a
            # turn that thinks less. See `takes_effort` in config.py. At the
            # level that comes with the model (`level` above).
            effort = effort_for(asked, level)
            if effort:
                request["output_config"] = {"effort": effort}
            # Thinking, carried across the tool calls inside this turn. It is
            # on the request rather than only on the first one because the
            # loop below re-sends `messages` with the thinking blocks in it,
            # which is what makes the reasoning after a tool result continue
            # the reasoning before it rather than start again.
            #
            # Adaptive, with no budget: the model decides how much to think
            # and `effort` is the dial. A fixed budget_tokens is refused
            # outright by this family of models.
            #
            # None of it is ever spoken, and none of it is ever written to the
            # transcript. See `_without_thinking` below for the second of
            # those and the stream loop for the first: only `text_delta` ever
            # reaches the voice or the screen. What it thought is in the log of
            # requests and nowhere else (`rouh/llmlog.py`).
            #
            # Decided again for each model the retries below fall back to,
            # like the effort: see `_thinking`.
            thinking = self._thinking(asked)
            if thinking:
                request["thinking"] = thinking
            # Code execution runs in a sandbox on Anthropic's side, and that
            # sandbox has an id. When the code it ran itself called another
            # tool, the next request in the same turn is rejected outright
            # without that id: "container_id is required when there are pending
            # tool uses generated by code execution with tools". The turn then
            # dies with a 400 and the person gets no answer at all, which is
            # what "open the page at example.com and tell me what it says" did.
            if container_id:
                request["container"] = container_id

            assistant_blocks = []
            stop_reason = None
            this_call = []
            # Anthropic's own tool calls in this response, by block index:
            # (call id, tool name, the pieces of its input so far).
            server_calls: dict[int, tuple[str, str, list[str]]] = {}
            # And what came back to them, by block index, until the block closes.
            server_results: dict[int, object] = {}
            # The first characters of this reply, held until the mark can be
            # read off them. One attempt each: a retry writes its reply again
            # from the beginning, mark and all.
            front: turnmarks.Reading | None = None
            # The pages this response cites, numbered as it cites them, so
            # every thing it says off a page carries that page's number and
            # the answer ends with the list (`rouh/citing.py`). One per
            # attempt, like the mark: a retry numbers its reply from the start.
            cited = citing.Numbering()

            async def pump():
                """Stream one response, and give back the finished message.

                A function of its own so that the stop can cancel it. Cancelling
                here leaves the `async with` below, which closes the response
                mid-stream: the model stops being read and stops being paid
                for, and no more words reach the voice.
                """
                nonlocal spoken_buffer, front, cited, judging, acted
                front = turnmarks.Reading()
                cited = citing.Numbering()
                # The text blocks that have put words on the screen, by index:
                # only those take a footnote, so a number never lands in front
                # of the words it belongs after.
                wrote: set[int] = set()
                async with self.client.messages.stream(**request) as stream:
                    async for event in stream:
                        if timing["first_token"] is None and event.type in (
                                "content_block_start", "content_block_delta"):
                            timing["first_token"] = time.monotonic() - sent_at
                        if event.type == "content_block_start":
                            # Web search, web fetch and code execution run on
                            # Anthropic's side, inside this turn. They never
                            # reach the tool loop below, so without this they
                            # were invisible: asking Rouh to look something up
                            # produced no sign that anything was happening.
                            block = event.content_block
                            kind = getattr(block, "type", "")
                            if kind == "server_tool_use":
                                acted = True
                                # A call is an answer, so the question is
                                # written before its line is drawn and kept:
                                # otherwise a search run ahead of any words
                                # was filed under the answer before, and read
                                # back above the question (fr_f8a1bebc7237).
                                question.write()
                                judging = False
                                name = getattr(block, "name", "server_tool")
                                said = worklabel.describe_step(name, getattr(block, "input", None))
                                await emit({
                                    "type": "tool_start",
                                    "id": getattr(block, "id", ""),
                                    "name": name,
                                    "input": "",
                                    "what": said["what"],
                                    "detail": said["detail"],
                                    "where": "rouh",
                                })
                                # Its input streams in after this; kept to say
                                # what was searched once the block closes.
                                server_calls[event.index] = (getattr(block, "id", ""), name, [])
                                server_names[getattr(block, "id", "")] = name
                            elif kind.endswith("_tool_result"):
                                # Answered when the block closes, below.
                                server_results[event.index] = block
                        if event.type == "content_block_delta" and event.index in server_calls:
                            if getattr(event.delta, "type", "") == "input_json_delta":
                                server_calls[event.index][2].append(event.delta.partial_json or "")
                        elif event.type == "content_block_stop" and event.index in server_calls:
                            call_id, name, pieces = server_calls.pop(event.index)
                            try:
                                args = json.loads("".join(pieces))
                            except ValueError:
                                args = None
                            if isinstance(args, dict):
                                said = worklabel.describe_step(name, args)
                                await emit({
                                    "type": "tool_update",
                                    "id": call_id,
                                    "name": name,
                                    # What the call was really sent, which is
                                    # what the line opens onto: the query a
                                    # search went out with, the address a
                                    # fetch read. `tool_start` could not carry
                                    # it, because it had not arrived yet.
                                    "input": _shallow(args),
                                    "what": said["what"],
                                    "detail": said["detail"],
                                    "where": "rouh",
                                })
                        elif event.type == "content_block_stop" and event.index in server_results:
                            # The result names the call it answers, so the
                            # pairing is exact rather than by arrival order.
                            # Read as the stream put the block together, so
                            # what came back is whole however it was sent.
                            block = server_results.pop(event.index)
                            block = getattr(event, "content_block", None) or block
                            kind = getattr(block, "type", "")
                            # A page it read is only named by its title in
                            # what cites it; this is where its address is.
                            if kind == "web_fetch_tool_result":
                                cited.read(block)
                            if kind == "tool_search_tool_result":
                                timing["loaded"] += toolsearch.loaded_by(block)
                            came = _server_result(block)
                            answered = getattr(block, "tool_use_id", "")
                            await emit({
                                "type": "tool_end",
                                "id": answered,
                                "name": server_names.get(answered) or kind[: -len("_tool_result")],
                                "ok": came["ok"],
                                "summary": came["summary"],
                                "results": came["results"],
                                "where": "rouh",
                            })
                            # A page web_fetch could not get. The reply stops
                            # here, and the model with it, once nothing else
                            # of Anthropic's in it is still running: it is
                            # read in a browser below, and the model goes on
                            # from that rather than without the page.
                            so_far = stream.current_message_snapshot.content
                            second.note(block, so_far, messages)
                            if second.due(so_far):
                                return stream.current_message_snapshot
                        if (event.type == "content_block_stop" and event.index in wrote
                                and getattr(getattr(event, "content_block", None), "type", "") == "text"):
                            # The words of this block are all out, and the
                            # pages it was written from are known: its number
                            # goes straight after it. On the screen and in the
                            # answer, never to the voice - a footnote is read,
                            # not heard.
                            mark = cited.cite(event.content_block)
                            if mark:
                                full_text.append(mark)
                                await emit({"type": "assistant_delta", "text": mark})
                        if event.type == "content_block_delta" and event.delta.type == "text_delta":
                            piece = front.take(event.delta.text)
                            if front.unfinished and judging:
                                # They had not finished asking. Leaving here
                                # closes the stream unread: the model stops
                                # being paid for, and nothing of this turn was
                                # ever said, shown or written down.
                                raise turnmarks.Unfinished(front.mark)
                            if not piece:
                                continue        # still holding the mark back
                            # Their words are theirs from here: the mark said
                            # to answer, so the question is a question.
                            question.write()
                            wrote.add(event.index)
                            if timing["first_text"] is None:
                                timing["first_text"] = time.monotonic() - began
                            full_text.append(piece)
                            this_call.append(piece)
                            await emit({"type": "assistant_delta", "text": piece})
                            if on_sentence:
                                spoken_buffer += piece
                                sentences, spoken_buffer = _split_sentences(spoken_buffer)
                                for s in sentences:
                                    await on_sentence(s)
                    return await stream.get_final_message()

            # One request, with the retries around it. The retries are only
            # ever around this: by the time a request goes out, every tool it
            # depends on has already run and its result is in `messages`, so
            # sending that list again sends the same words again and never
            # sends a second email. See `rouh/retrying.py`.
            #
            # Only ever the model this turn is using, the Models page's. There was a
            # chain of fallbacks from the config (`ROUH_MODEL_FALLBACKS`) until the
            # evening of 18 October 2026, when Petar asked that whatever is selected
            # is the one called, with no exceptions: a model that will not answer
            # fails the turn, saying why, rather than handing it to another.
            chain = [asked]
            which = 0
            attempt = 0
            final = None
            unthought = False
            while True:
                attempt += 1
                asked = chain[which]
                request["model"] = asked
                # The effort rule is decided per model and not once per turn,
                # for the same reason it is decided above: a fallback can be a
                # model that refuses an effort level, and a 400 there is a turn
                # that says nothing at all rather than one that thinks less.
                effort = effort_for(asked, level)
                if effort:
                    request["output_config"] = {"effort": effort}
                else:
                    request.pop("output_config", None)
                thinking = self._thinking(asked)
                if thinking:
                    request["thinking"] = thinking
                else:
                    request.pop("thinking", None)
                # Whether this attempt has already put words in front of the
                # person. It is the one thing that makes a retry unsafe: the
                # reply is streamed to the voice sentence by sentence, so an
                # attempt that spoke and then broke has already spoken.
                said_before = len(full_text)
                # A fresh attempt starts from nothing. `pump` closes over both
                # of these, so they are emptied in place rather than rebound.
                this_call.clear()
                server_calls.clear()
                server_results.clear()
                second.forget()
                # The tools and the catalogue are the plan of the model this
                # attempt asks, and only differ from the turn's when a fallback
                # cannot defer tools at all.
                if toolsearch.mode_for(asked, getattr(self.cfg, "tool_search", "regex")) != plan.mode:
                    other = self._tool_plan(entries, asked)
                    request["tools"] = other.tools
                    request["system"] = self._system(other, seeds=found, recall=remembered,
                                                     asked=again)
                else:
                    request["tools"] = plan.tools
                    request["system"] = system
                timing["requests"] += 1
                sent_at = time.monotonic()
                # The request goes out inside `pump`, a task of its own, which
                # takes which try this is with it into the log of requests.
                with llmlog.about(attempt=attempt):
                    reading = asyncio.ensure_future(pump())
                try:
                    final = await _first_of(reading, stop)
                    break
                except _Stopped:
                    # Mid-stream. Whatever words arrived are kept and stored
                    # below; nothing after this point is said, and no further
                    # request goes out for this turn. A stop is never retried:
                    # the person asked for it to end.
                    reading.cancel()
                    with contextlib.suppress(asyncio.CancelledError, Exception):
                        await reading
                    stopped = True
                    break
                except (anthropic.APIStatusError, anthropic.APIConnectionError) as exc:
                    spoke = len(full_text) > said_before
                    if not unthought and retrying.is_unbound_thinking(exc):
                        # Something in front of this turn's thinking changed
                        # between two of its requests - a trim of the window
                        # past its budget does that - and the model will not
                        # take the thinking back under it. Asked again without
                        # any, the answer carries on from the tool results
                        # rather than stopping on a 400. Once: a second refusal
                        # is not this, and is left to the rest of this handler.
                        unthought = True
                        messages = _unthought(messages)
                        request["messages"] = promptcache.marked(messages, anchor)
                        log.warning("%s: its thinking was bound to an earlier window; "
                                    "asking again without it", asked)
                        continue
                    if retrying.is_wrong_model(exc) and which + 1 < len(chain):
                        which += 1
                        attempt = 0
                        log.warning("%s: %s; trying %s instead", asked, exc, chain[which])
                        continue
                    if retrying.should_retry(exc, attempt=attempt,
                                             said_anything=spoke):
                        seconds = retrying.delay_for(attempt, exc)
                        log.warning("%s", retrying.said(
                            exc, model=asked, attempt=attempt, seconds=seconds))
                        await retrying.wait(seconds)
                        # A stop that lands during the wait ends the turn
                        # rather than spending another request on it.
                        if _is_stopped(stop):
                            stopped = True
                            break
                        continue
                    if not spoke and which + 1 < len(chain):
                        # This model is not answering. The next one in the
                        # chain gets the same request, from the start.
                        which += 1
                        attempt = 0
                        log.warning("%s gave up (%s); falling back to %s",
                                    asked, exc, chain[which])
                        continue
                    question.write()    # they asked; the failure is ours
                    over = retrying.overflowed(exc)
                    if over is not None:
                        # More than the model can read. Never cut to fit: the
                        # person is told, and the words stay on the screen
                        # until they close them (`rouh/chatkinds.py`).
                        log.warning("%s is more than %s can read, and was not answered: %s",
                                    session_id, asked, retrying.api_words(exc))
                        await emit({"type": "error", "fatal": False, "lasting": True,
                                    "message": chatkinds.too_long(session_id, asked, *over)})
                        return "".join(full_text)
                    log.exception("model call failed")
                    # The spending limit stays on screen until it is closed,
                    # like a chat past its window: it lasts until someone acts.
                    await emit({"type": "error", "message": _friendly(exc),
                                "fatal": False,
                                "lasting": retrying.capped(exc) is not False})
                    return "".join(full_text)

            # The inner loop is one request and its retries; this is the turn.
            if stopped:
                break

            # The reply is real, so the question was finished - whether the
            # mark said so, or the model went straight to a tool without
            # writing anything at all. Before the answer is stored, always, or
            # the conversation has an answer in front of its question.
            question.write()
            judging = False
            # The list its numbers point at, under the last of its words and
            # above anything one of Rouh's own tools draws next. Written, not
            # spoken, like the numbers themselves.
            sources = cited.listing()
            if sources:
                full_text.append(sources)
                await emit({"type": "assistant_delta", "text": sources})
            assistant_blocks = final.content
            stop_reason = final.stop_reason
            # Stopped at a page web_fetch could not read: no stop reason, and
            # the reply ends in a call of Rouh's own for that page, answered
            # below like any other. Its usage is what the stream had said by
            # then, which is all of its input and not quite all of its output.
            cut = stop_reason is None and bool(second.waiting)
            if cut:
                assistant_blocks = [*assistant_blocks, *second.calls()]
            else:
                second.forget()
            container = getattr(final, "container", None)
            if container is not None and getattr(container, "id", None):
                container_id = container.id
            # Cache writes cost a quarter more than sending the same tokens
            # once and reads cost a tenth, so both have to be counted or the
            # price on the screen is wrong in both directions at once. And
            # each request is kept as well as the sum of them, because what
            # caching saves shows in how the second request of a turn differs
            # from the first.
            took = costs.tokens_of(final.usage)
            for key in ("input", "output", "cache_read", "cache_write", "cache_write_1h"):
                usage[key] += took[key]
            usage["calls"].append(took)
            log.info("request %d of the turn: %s", len(usage["calls"]), costs.call_said(took))
            # Which model actually answered. It is not always the one the turn
            # began with: a turn can fall through to the next one in the chain, and the
            # two are not the same price.
            usage["model"] = request["model"]
            # The size of the window that request actually went out with, from
            # the API's own numbers rather than an estimate of ours.
            window = context_editing.window_tokens(final.usage)
            self._windows[session_id] = window

            messages.append({"role": "assistant", "content": assistant_blocks})
            # What this turn sends back to the model keeps the thinking; what
            # goes in the database does not. Thinking belongs to the turn it
            # happened in: it is what got from one tool result to the next,
            # and it is of no use to a conversation next week. Keeping it out
            # of the database is also what keeps it out of the transcript,
            # out of every later window, and out of anything that reads the
            # history back.
            self.memory.add_message(
                session_id, "assistant",
                _without_marks(_without_thinking(_serialisable(assistant_blocks))),
                root=question.slot.root, version=question.slot.version)
            # Stored whole, so a stop from here on has nothing of its own to keep.
            this_call = []

            if stop_reason == "refusal":
                detail = getattr(final, "stop_details", None)
                note = getattr(detail, "explanation", None) or "I can't help with that one."
                await emit({"type": "assistant_delta", "text": note})
                if on_sentence:
                    await on_sentence(note)
                full_text.append(note)
                break

            if stop_reason == "model_context_window_exceeded":
                # The window filled while the answer was being written. What it
                # wrote is kept and shown; the person is told why it stops.
                log.warning("%s filled %s's window part way through an answer",
                            session_id, request["model"])
                await emit({"type": "error", "fatal": False, "lasting": True,
                            "message": chatkinds.filled(session_id, request["model"])})
                break

            if stop_reason == "pause_turn":
                # A server-side tool ran long and the turn was parked. Re-send to
                # pick it up; cap the restarts so a loop cannot run away.
                restarts += 1
                if restarts > 5:
                    break
                continue

            if not cut:
                if stop_reason != "tool_use":
                    break

                calls = [b for b in assistant_blocks if getattr(b, "type", None) == "tool_use"]
                if not calls:
                    break

            acted = True
            # Between the model asking for a tool and the tool being called.
            if _is_stopped(stop):
                stopped = True
                break

            # A reply that was cut has only Rouh's own calls to answer, one a
            # page, and what the browser read is each one's result
            # (`rouh/fetchfallback.py`).
            running = asyncio.ensure_future(
                second.run(emit) if cut else
                self._run_tools(calls, emit, entries=entries, loaded=timing["loaded"]))
            try:
                results = await _first_of(running, stop)
            except _Stopped:
                # The calls of this round are left running on purpose. Some of
                # them have already started a background worker or a run, and
                # the person stopped Rouh, not the work it handed over. What
                # they give back is dropped: the turn that asked for it is over.
                _let_it_finish(running)
                stopped = True
                break
            # A file a tool showed is kept as its marker and read in on the request.
            stored = results
            if _shows_files(stored):
                results = attachments.hydrate([{"role": "user", "content": stored}],
                                              self.files)[0]["content"]
            messages.append({"role": "user", "content": results})
            # Stored before the trim, never after: what goes in the database is
            # the whole result, and the trimming is only ever about what this
            # request carries.
            self.memory.add_message(session_id, "user", stored,
                                    root=question.slot.root,
                                    version=question.slot.version)
            # A seed lookup that was not back for the first request rides on
            # this one, after the tool results, at no wait at all, and so does
            # whatever automatic recall found since (`late_memory`); only on
            # the request, never in the database (D84, and Petar, 10 October
            # 2026: nothing looked up is dropped).
            #
            # Never after the results of a reply in which one of Anthropic's own
            # calls is still waiting. Asked for beside one of Rouh's tools, it
            # is run only once the request after them goes out, and only when
            # that request ends in tool results alone: with the seeds after
            # them the API refused the request outright, the turn said nothing,
            # and the reply stored with the waiting call broke the chat's next
            # turn too (6 October 2026). The seeds wait for a round with
            # nothing waiting, or go with the next message.
            if not servercalls.pending(assistant_blocks):
                later = await late_memory(session_id, seeds, recall)
                if later:
                    messages[-1] = {"role": "user", "content": list(results) + [
                        {"type": "text", "text": later}]}
                # And what the person sent while those tools ran, after their
                # results and before the model decides what to do next, which
                # is the first moment it can change course without anything
                # being cut short. Held back by the same rule as the seeds: a
                # message of theirs after the results of a reply with one of
                # Anthropic's own calls still waiting is refused outright.
                messages.extend(await self._take_steer(session_id, question, steer, emit))
            # Not trimmed to the budget here, between two requests of the same
            # turn: that would change what every later request of it has
            # already had cached. The next turn does it, before it starts. Only
            # General's window, about to be more than the model can read at
            # all, is trimmed now, because then the choice is a cache written
            # again or no answer. Any other chat goes on whole, and if the next
            # request is more than the model can read, the person is told.
            ceiling = context_editing.ceiling(request["model"])
            if rules.trims and window > ceiling:
                messages = await self._edit_context(messages, emit, rules, window=window,
                                                    budget=ceiling, by_age=False,
                                                    usage=usage)

        if stopped:
            question.write()
            return await self._abandon(session_id, this_call, full_text, emit,
                                       question.slot)

        if on_sentence and spoken_buffer.strip():
            await on_sentence(spoken_buffer.strip())

        text = "".join(full_text).strip()
        # What the turn cost, in tokens and in money, from the API's own
        # numbers. Written down and sent to the page, because nobody could
        # see what a turn cost and so nobody could tell an expensive habit
        # from a cheap one until the bill arrived (`rouh/costs.py`).
        spent = costs.summarise(usage, usage.get("model") or model)
        spent["trimmed"] = usage.get("trimmed", 0)
        spent.update(_timed(timing, plan.mode))
        with contextlib.suppress(Exception):
            self.memory.note_spend(session_id, spent)
        log.info("turn cost: %s", costs.said(spent))
        log.info("turn timing: %s", _said_timing(spent))
        await emit({"type": "assistant_done", "text": text,
                    "usage": usage, "spent": spent})
        if not acted and text:
            self._double(session_id, system, messages, text, request, usage)
        return text

    def _double(self, session_id: str, system, messages: list, text: str, request: dict,
                usage: dict) -> None:
        """Maybe make this plain answer one of the Rouh pool's double calls (`llm.double`):
        only a turn that answered in words and did nothing else, and only one small
        enough that a second model reading it costs little. Never raises."""
        try:
            from . import chatkinds, llm

            def words(content) -> str:
                if isinstance(content, str):
                    return content
                return "\n".join(b.get("text", "") for b in content or []
                                 if isinstance(b, dict) and b.get("type") == "text")

            plain = [{"role": m.get("role"), "content": words(m.get("content"))}
                     for m in messages if isinstance(m, dict)]
            plain = [m for m in plain if m["content"].strip()]
            said_system = words(system) if not isinstance(system, str) else system
            if sum(len(m["content"]) for m in plain) + len(said_system) > DOUBLE_MOST_CHARS:
                return
            model = str(request.get("model") or "")
            effort = str((request.get("output_config") or {}).get("effort") or "")
            first = llm.Answer(text=text, model=model, effort=effort,
                               usage={"input_tokens": usage.get("input", 0),
                                      "output_tokens": usage.get("output", 0)})
            llm.double(chatkinds.use_for(session_id), first, system=said_system,
                       messages=plain, max_tokens=4000)
        except Exception:
            log.exception("a double call for a turn in %s could not be started", session_id)

    async def _take_steer(self, session_id: str, question: Question, steer,
                          emit) -> list[dict]:
        """What the person sent while this turn was running, taken in now.

        Each message is written into the conversation where it is taken, as
        one of theirs in the same exchange, so the conversation read back is
        in the order the model read it: the answer so far, their message, and
        the rest of the answer after it. Their question is written first if
        it is not yet, because these come after it. Every tab in the chat is
        told which messages were taken and which rows they became
        (`steer_taken`), and moves them to where they were read.

        Handed back as the messages to add to this turn's request, files and
        all (`attachments.hydrate`).
        """
        waiting = steer() if steer is not None else []
        if not waiting:
            return []
        question.write()
        taken: list[dict] = []
        out: list[dict] = []
        for one in waiting:
            row = self.memory.add_message(session_id, "user", one["content"],
                                          root=question.slot.root,
                                          version=question.slot.version)
            taken.append({"id": one.get("id") or "", "message_id": row,
                          "text": one.get("text") or "",
                          "attachments": one.get("files") or []})
            out.append({"role": "user", "content": one["content"]})
        log.info("took in %d message(s) the person sent during the turn in %s",
                 len(taken), session_id)
        await emit({"type": "steer_taken", "taken": taken, "root": question.slot.root})
        return attachments.hydrate(out, self.files)

    async def _abandon(self, session_id: str, this_call: list[str],
                       full_text: list[str], emit,
                       slot: memory_mod.Slot | None = None) -> str:
        """Close a turn the person stopped, so the conversation stays coherent.

        Two things are written down. The half-finished words, if the stop
        landed mid-sentence, because they were said out loud and on screen and
        a history that denies them is a history the next turn will contradict.
        Then the note in the person's place (`stopping.STOP_NOTE`), which is
        what tells the next turn that the one before it was stopped rather than
        finished.

        Deliberately no `assistant_done`. That message is what is spoken, what
        is mirrored to the other screens and what the page draws as a finished
        answer, and none of those is true of a turn that was stopped.
        """
        partial = "".join(this_call).strip()
        root = slot.root if slot is not None else None
        version = slot.version if slot is not None else 1
        if partial:
            self.memory.add_message(session_id, "assistant",
                                    [{"type": "text", "text": partial}],
                                    root=root, version=version)
        self.memory.add_message(session_id, "user", [{"type": "text", "text": STOP_NOTE}],
                                root=root, version=version)
        await emit({"type": "stopped", "text": partial})
        return "".join(full_text).strip()

    async def _edit_context(self, messages: list, emit, rules: chatkinds.Profile, *,
                            window: int = 0, budget: int | None = None,
                            by_age: bool = True, usage: dict | None = None) -> list:
        """Take the stale tool results out of the window, keeping everything else.

        General's alone: `rules` is the chat's profile, and a chat that is not
        General is handed back exactly as it came (`rouh/chatkinds.py`).

        Called where a turn begins, on the history that came back from the
        database: the old results go by age, and if `window` - the size of
        this chat's last request - is over the budget, recent ones go too, a
        few at a time. Never between two requests of a turn, which is what
        keeps each of them readable out of the prompt cache, except with
        `by_age` off and `budget` at the model's own ceiling, when the window
        is about to be more than the model can read.

        A failure here must never end a turn. The worst case of a trim that
        does not happen is an expensive request; the worst case of one that
        raises is the person getting no answer at all.
        """
        if not rules.trims:
            return messages
        keep = rules.keep_messages
        min_body = rules.min_body
        if budget is None:
            budget = rules.budget_tokens
        did = {"results": 0, "characters": 0}
        try:
            if by_age:
                messages, one = context_editing.trim(messages, keep_messages=keep,
                                                     min_body=min_body)
                for key in did:
                    did[key] += one[key]
            # Over budget, the recent results go too, a few at a time.
            over = context_editing.how_many_to_trim(window, budget) if window else 0
            if over:
                messages, one = context_editing.trim(messages, keep_messages=2,
                                                     min_body=min_body, at_most=over)
                for key in did:
                    did[key] += one[key]
        except Exception:                      # a trim must not cost an answer
            log.exception("the context could not be trimmed")
            return messages
        if not did["results"]:
            return messages
        if usage is not None:
            usage["trimmed"] = usage.get("trimmed", 0) + did["results"]
        log.info("context: %s", context_editing.describe(did))
        # Said on the wire so the page can show it, and so a person watching
        # can see why a long conversation stopped growing.
        await emit({"type": "context_edited", "results": did["results"],
                    "characters": did["characters"], "window": window})
        return messages

    async def _run_tools(self, calls, emit, *, entries=None, loaded=None) -> list[dict]:
        """Run every requested tool at once and return all results in one message.

        They go back in a single user message on purpose: splitting tool results
        across several messages teaches the model to stop asking for more than
        one at a time, and it is slower for no gain.

        `entries` are the turn's tools, for the search this process runs itself
        (`toolsearch.CLIENT_SEARCH`), which is answered here rather than by the
        registry: it is not a tool of Rouh's but the way the model reaches them.
        What it loads is added to `loaded`.
        """

        async def search(block):
            args = block.input if isinstance(block.input, dict) else {}
            said = worklabel.describe_step(block.name, args)
            await emit({"type": "tool_start", "id": block.id, "name": block.name,
                        "input": _shallow(args), "what": said["what"],
                        "detail": said["detail"], "where": "rouh"})
            names = toolsearch.find(entries or [], args.get("query"), args.get("limit"))
            if loaded is not None:
                loaded.extend(names)
            await emit({"type": "tool_end", "id": block.id, "name": block.name, "ok": True,
                        "summary": toolsearch.said_loaded(names),
                        "results": [{"title": name, "url": ""} for name in names],
                        "where": "rouh"})
            return {"type": "tool_result", "tool_use_id": block.id,
                    "content": toolsearch.anthropic_search_result(names)}

        async def one(block):
            if block.name == toolsearch.CLIENT_SEARCH and entries is not None:
                return await search(block)
            said = worklabel.describe_step(block.name, block.input)
            await emit(
                {
                    "type": "tool_start",
                    "id": block.id,
                    "name": block.name,
                    # A command goes whole and with its secrets hidden,
                    # because it is all its line in the chat shows.
                    "input": (worklabel.command_input(block.name, block.input)
                              or _shallow(block.input)),
                    "what": said["what"],
                    "detail": said["detail"],
                    "where": "rouh",
                }
            )
            began = time.monotonic()
            try:
                # The call's own id goes with it, so a tool that has to be
                # asked about can say which call the question is about and the
                # orb can draw the waiting on that call's own twig.
                out = await self.tools.call(block.name, block.input, emit,
                                            call_id=block.id)
                ok, payload = True, out
            except Exception as exc:  # a failing tool must not end the turn
                log.exception("tool %s failed", block.name)
                ok, payload = False, f"{type(exc).__name__}: {exc}"
            # Which tool, how long and whether it worked; never what it was given or said.
            events.emit("tool.called", actor="rouh",
                        source="telegram" if telegram_chat.FROM_PHONE.get() is not None else "server",
                        object_type="tool", object_id=block.name, owner=True,
                        duration_ms=(time.monotonic() - began) * 1000, props={"ok": ok})
            # What a command printed, whole, for the line that shows it
            # under the command. Every other call has only its summary, and a
            # command's is made from the output with its secrets hidden, or
            # the line above the output would show the key it hides.
            output = worklabel.command_output(block.name, payload)
            # How much it gave back, on its bar of the turn's timeline (`rouh/turntrace.py`).
            trace = turntrace.current()
            if trace is not None:
                trace.tool_sized(block.id, len(payload) if isinstance(payload, str) else len(str(payload)))
            await emit(
                {
                    "type": "tool_end",
                    "id": block.id,
                    "name": block.name,
                    "ok": ok,
                    # A link to Rouh read inside Rouh says what it read in its
                    # first line, in Rouh's words, before the page's own box.
                    # So does a YouTube transcript, whether it was stored or
                    # transcribed just now (`rouh/youtube_store.py`).
                    "summary": _summarise(str(payload).split("\n", 1)[0]
                                          if block.name in _FIRST_LINE_SAYS and ok
                                          else output or payload),
                    **({"output": output} if output is not None else {}),
                    "where": "rouh",
                }
            )
            return {
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": _result_content(payload),
                **({"is_error": True} if not ok else {}),
            }

        return list(await asyncio.gather(*(one(b) for b in calls)))


def _split_sentences(buf: str) -> tuple[list[str], str]:
    """Pull speakable chunks off the front of a growing buffer.

    Returns the chunks ready to be spoken and whatever is left over, which stays
    in the buffer until more text arrives or the turn ends.

    A short sentence is not emitted on its own - the search simply carries on to
    the next boundary and the two are spoken together.
    """
    out: list[str] = []
    start = 0
    search = 0
    while True:
        m = _SENTENCE_END.search(buf, search)
        if not m:
            break
        cut = m.end()
        search = cut
        candidate = buf[start:cut].strip()
        if len(candidate) < MIN_SPOKEN_CHARS:
            continue  # too short alone: absorb the next sentence too
        out.append(candidate)
        start = cut

    # No boundary in a long stretch: break at the last comma, then the last
    # space, so the voice keeps up with a model writing a long unpunctuated run.
    tail = buf[start:]
    while len(tail) > FORCE_BREAK_CHARS:
        window = tail[:FORCE_BREAK_CHARS]
        cut = max(window.rfind(", "), window.rfind("; "))
        if cut < MIN_SPOKEN_CHARS:
            cut = window.rfind(" ")
        if cut < MIN_SPOKEN_CHARS:
            break
        out.append(tail[: cut + 1].strip())
        tail = tail[cut + 1 :]
        start = len(buf) - len(tail)

    return out, buf[start:]


#: Block kinds that are the model's reasoning and nobody else's business.
THINKING_BLOCKS = frozenset({"thinking", "redacted_thinking"})


def _without_thinking(blocks: list[dict]) -> list[dict]:
    """The same blocks with the reasoning taken out, for the database.

    Not for the request: the request keeps them, and has to, or the thinking
    after a tool result does not continue the thinking before it.
    """
    return [b for b in blocks
            if not (isinstance(b, dict) and b.get("type") in THINKING_BLOCKS)]


def _unthought(messages: list) -> list:
    """The window with every thinking block taken out, for the request.

    Only for the one case `retrying.is_unbound_thinking` names, where the
    thinking cannot be handed back as it is. The blocks the API gave back sit
    in the window as they came, so a block here can be the SDK's own object as
    well as a dict. A message that was nothing but thinking is left as it was,
    because a message with nothing in it is a 400 of its own.
    """
    out = []
    for message in messages:
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, list):
            kept = [b for b in content
                    if (b.get("type") if isinstance(b, dict) else getattr(b, "type", None))
                    not in THINKING_BLOCKS]
            if kept and len(kept) != len(content):
                message = {**message, "content": kept}
        out.append(message)
    return out


def _without_marks(blocks: list[dict]) -> list[dict]:
    """The same blocks with the turn mark taken off the front of the reply.

    The mark is stripped out of the stream on its way to the screen and the
    voice, but the finished message the API hands back still carries it, and
    that message is what goes in the database. Without this every answer is
    stored with a black circle in front of it, read back into every later
    window with one, and drawn in the transcript with one.

    Only the very first character of the whole reply can be a mark, so only the
    first block is looked at. A circle the person actually asked about, later
    on, is theirs and is left alone.

    A reply that is the mark and nothing else - the model marking the turn and
    going straight to a tool without writing a word - leaves an empty text
    block once the mark comes off, and the API refuses one of those
    ("messages: text content blocks must be non-empty"). It refuses it on every
    later turn rather than this one, because the window this turn sends is the
    one still in memory and only the stored copy is stripped. So the turn that
    makes it is the last one that works, and the chat is dead from the next
    question on. That is 2026-09-20, message 2797, which killed a live
    conversation for forty minutes.

    So the block is dropped rather than emptied. A text block with nothing in
    it says nothing the tool call beside it does not already say, and a message
    left with no blocks at all is fine: the API accepts an empty content list,
    checked against it rather than assumed.
    """
    out = list(blocks)
    first = out[0] if out else None
    text = first.get("text") if isinstance(first, dict) else None
    if isinstance(text, str) and text[:1] in turnmarks.MARKS:
        stripped = text[1:].lstrip(" ")
        if stripped:
            out[0] = dict(first, text=stripped)
        else:
            out.pop(0)
    return out


def _serialisable(blocks) -> list[dict]:
    out = []
    for b in blocks:
        if hasattr(b, "model_dump"):
            out.append(b.model_dump(exclude_none=True))
        elif isinstance(b, dict):
            out.append(b)
    return out


def _shallow(value, limit: int = 400):
    try:
        text = json.dumps(value)
    except Exception:
        text = str(value)
    return text[:limit]


def _result_content(payload):
    """A tool's result as a tool_result's content: its words, or its blocks when it shows a file."""
    if isinstance(payload, untrusted.Blocks):
        return list(payload)
    return payload if isinstance(payload, str) else json.dumps(payload)


def _shows_files(results) -> bool:
    """Whether any of these tool results carries a file's marker (`attachments.expand`)."""
    return any(isinstance(r, dict) and isinstance(r.get("content"), list)
               and any(isinstance(b, dict) and b.get("type") == "attachment" for b in r["content"])
               for r in results or [])


#: The tools whose answer's first line is Rouh's own account of it, which is what the line under
#: the call on screen shows rather than the first words of what came back.
_FIRST_LINE_SAYS = {rouhlinks.TOOL, "youtube_transcript"}


def _summarise(payload) -> str:
    # What is drawn on screen is what the page or the email actually said. The
    # marks round it are for the model, and a chip whose first line is
    # "<untrusted-content-a1b2c3d4 ...>" tells the person nothing at all.
    payload = untrusted.inner(payload)
    text = payload if isinstance(payload, str) else json.dumps(payload)
    text = " ".join(text.split())
    return text[:160] + ("…" if len(text) > 160 else "")


def _timed(timing: dict, mode: str) -> dict:
    """How long a turn took to start answering, and what it loaded, for `spend`.

    `first_token` is from the turn's first request going out to the first
    thing streaming back, thinking included: what the model took. The other
    two are from the start of the turn, which is what the person waited:
    `first_text` to the first words on the screen and `first_word` to the
    first sentence handed to the voice. None where the turn never got there.
    """
    def ms(seconds):
        return None if seconds is None else int(round(seconds * 1000))

    loaded = list(dict.fromkeys(n for n in timing.get("loaded") or [] if n))
    return {"requests": int(timing.get("requests") or 0),
            "first_token_ms": ms(timing.get("first_token")),
            "first_text_ms": ms(timing.get("first_text")),
            "first_word_ms": ms(timing.get("first_word")),
            "tool_search": mode, "tools_loaded": loaded}


def _said_timing(spent: dict) -> str:
    """The turn's numbers in one line for the log, so any two can be compared."""
    def secs(ms):
        return "-" if ms is None else f"{ms / 1000:.2f}s"

    return (f"model={spent.get('model')} search={spent.get('tool_search')} "
            f"requests={spent.get('requests')} "
            f"input={spent.get('input', 0):,} cache_read={spent.get('cache_read', 0):,} "
            f"cache_write={spent.get('cache_write', 0):,} output={spent.get('output', 0):,} "
            f"first_token={secs(spent.get('first_token_ms'))} "
            f"first_text={secs(spent.get('first_text_ms'))} "
            f"first_word={secs(spent.get('first_word_ms'))} "
            f"loaded={','.join(spent.get('tools_loaded') or []) or '-'}")


#: The most results one line carries to the page. A search brings back about
#: ten, so this is only a ceiling against a reply nobody expected.
MAX_RESULTS = 20

#: Why one of Anthropic's own web tools could not do it, in words. The codes
#: are Anthropic's; one not named here is shown as it came.
_WEB_FAILED = {
    "too_many_requests": "too many at once, so it was turned away",
    "max_uses_exceeded": "this answer had already used every search it may",
    "query_too_long": "the query was too long",
    "invalid_input": "what it was given was not accepted",
    "invalid_tool_input": "what it was given was not accepted",
    "unavailable": "the service was not available",
    "url_too_long": "the address was too long",
    "url_not_allowed": "that address is not allowed",
    "url_not_accessible": "the page could not be reached",
    "unsupported_content_type": "the page is not something it can read",
    "execution_time_exceeded": "it took too long and was stopped",
}


def _as_data(value):
    """A block as plain dicts, whether the SDK parsed it into a model or not."""
    if hasattr(value, "model_dump"):
        return value.model_dump()
    return value if isinstance(value, dict) else {}


def _one_line(value, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _server_result(block) -> dict:
    """What one of Anthropic's own tools came back with, for its line on screen.

    `{"ok", "summary", "results"}`. `results` is the pages the call came back
    with, each `{"title", "url"}` and an `age` where the search gave one: every
    result of a web search, or the one page a web fetch read. A result of any
    other kind has none, and says only that it is done.

    Until 24 September 2026 none of this reached the page. The line said
    "web_search done" and opened onto two quote marks, while the query and all
    nine titles and addresses sat in the reply that went back to the model.
    """
    data = _as_data(block)
    kind = data.get("type") or ""
    came = data.get("content")
    if isinstance(came, dict) and str(came.get("type") or "").endswith("_error"):
        code = str(came.get("error_code") or "")
        return {"ok": False, "results": [],
                "summary": "failed: " + _WEB_FAILED.get(code, code or "no reason given")}
    if kind == "web_search_tool_result":
        found = [r for r in (came if isinstance(came, list) else [])
                 if isinstance(r, dict) and (r.get("url") or r.get("title"))]
        results = []
        for r in found[:MAX_RESULTS]:
            one = {"title": _one_line(r.get("title"), 300), "url": _one_line(r.get("url"), 2000)}
            if r.get("page_age"):
                one["age"] = _one_line(r["page_age"], 40)
            results.append(one)
        many = len(found)
        return {"ok": True, "results": results,
                "summary": ("no results" if not many else "1 result" if many == 1
                            else f"{many} results")}
    if kind == "tool_search_tool_result":
        # A search for tools: what it loaded, by name, each drawn as a line
        # of the result with no address to follow.
        names = toolsearch.loaded_by(data)
        return {"ok": True, "results": [{"title": name, "url": ""} for name in names],
                "summary": toolsearch.said_loaded(names)}
    if kind == "web_fetch_tool_result" and isinstance(came, dict):
        doc = came.get("content") if isinstance(came.get("content"), dict) else {}
        url = _one_line(came.get("url"), 2000)
        title = _one_line(doc.get("title"), 300)
        return {"ok": True, "results": [{"title": title, "url": url}] if url else [],
                "summary": title or url or "done"}
    return {"ok": True, "results": [], "summary": ""}


#: What each of Anthropic's error types is, said to the person. Only the ones
#: a person can do anything about, or wait out, are worth a sentence of their
#: own; the rest fall through to the status.
_SAID_OF = {
    "overloaded_error": "The model is overloaded and would not answer. "
                        "Ask me again in a moment.",
    "billing_error": "My API account will not take the request: it is a billing problem.",
    "permission_error": "My API key is not allowed to do that.",
    "not_found_error": "That model does not exist for my API key.",
}


def _friendly(exc: anthropic.APIStatusError) -> str:
    """The failure, in one sentence, for the screen and the voice.

    The status is only shown when the status is what failed. A failure that
    arrives inside a stream carries 200 - the response was already 200 when the
    stream opened - so the number there is worse than useless: on
    22 September 2026 an overloaded model reached the person as "The model call
    failed (200)", which reads as a bug in Rouh rather than a busy model.
    """
    if isinstance(exc, anthropic.RateLimitError):
        return "I'm being rate limited. Give me a moment."
    if isinstance(exc, anthropic.AuthenticationError):
        return "My API key is not being accepted."
    back = retrying.capped(exc)
    if back is not False:
        return retrying.capped_words(back)
    kind = retrying.error_type_of(exc)
    if kind in _SAID_OF:
        return _SAID_OF[kind]
    if retrying.is_failure_status(retrying.status_of(exc)):
        return f"The model call failed ({exc.status_code})."
    if kind:
        return f"The model call failed part way through: {kind.replace('_', ' ')}."
    return "The model call failed part way through, without saying why."
