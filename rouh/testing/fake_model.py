"""A stand-in for the Messages API, so a test can read what was really sent.

Rouh talks to the model through Anthropic's own SDK, and the SDK is what
turns a message into bytes on the wire. A test that replaces `run_turn`, or
patches the client, never sees those bytes: it proves that Rouh meant to send
a picture, not that a picture was sent.

So this is a real HTTP server that speaks enough of `POST /v1/messages` to be
the other end of that SDK. Point `ANTHROPIC_BASE_URL` at it and Rouh is
unchanged - same client, same serialisation, same streaming - while every
request body lands in a directory as a file the test can open.

The reply is not fixed text. It is written from what actually arrived: the
sizes and digests of the images, the words found inside the PDF, the first line
of each text file. That is what lets a browser test assert on screen that the
file reached the model, rather than asserting it against a mock it wrote itself.

It also calls a tool when the person's own words tell it to. A line like

    TOOL delegate_task {"task": "sleep 600", "title": "A long job"}

typed into the box comes back as a real `tool_use` block, so a test can drive a
whole tool turn - Rouh runs the tool, sends the result back, and this answers
in words - without a real model deciding anything. The words the test types are
the trigger, so the test reads as what the person did. Several `TOOL` lines in
one message are called one after another, a round each, the way a real model
reads something and then draws it.

And it stands in for Anthropic's web search and web fetch, and it stands in for
them honestly: it applies the rule that broke them. A server tool is only the
model's to call when its `allowed_callers` says `direct`. Without that, and
with a code execution tool declared beside it, the tool exists only as a
function inside the code sandbox, and that sandbox has no network - which is
exactly why Rouh answered a question about today's prices from memory. So
when the tools in the request are wrong this server refuses to search and says
it is answering from memory, and when they are right it really fetches the page
over HTTP and answers out of the bytes that came back. A test can then tell the
two apart from the screen.

And it has a context window, as the real one does: a request longer than the
model it names can read is refused with the real API's own 400 and its own
words (`too_long`), so what a reader is told about a page too big for the
model can be seen on screen.

And it has a prompt cache, as the real one does, kept by the same rule: a
prefix is written at the blocks marked `cache_control` and read back by a later
request whose prompt is the same up to there, byte for byte (`cache_usage`).
The usage on every reply says what was read, what was written and what was
sent at the full price, and every request's numbers are also written down one
line each beside the requests (`usage_file`). A change that moves a breakpoint,
or puts something in front of one that changes between requests, shows here as
it would on the bill.

    python -m rouh.testing.fake_model --port 8099 --record /tmp/requests
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import functools
import hashlib
import itertools
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from ..heartbeat import NOTE_HEAD as HEARTBEAT_NOTE
from ..reminders import NOTHING_NEW, SCHEDULED, THEIR_WORDS
from ..turnmarks import (ANSWER_NOW, CUT_OFF_MID_THOUGHT, FINISHED,
                         STILL_THINKING, is_note)

#: Whom every world belongs to, by the name the prompts call them
#: (`rouh/testing/browser.py`, `OWNER`). Rouh writes its prompts with marks
#: (`rouh/owner.py`) and fills them in on the way out (`rouh/llmlog.py`), so what
#: arrives here says "Alex" where the live server's prompts say its own owner's
#: name, and "the owner" where nobody could be told.
OWNER = "Alex"
#: The owner, as a prompt names them once its marks are filled in.
ME = r"(?:Alex|[Tt]he owner)"
#: Each of Rouh's marks as a pattern: the name, or a pronoun for whoever set one.
_MARKS = {
    "‹owner›": ME, "‹Owner›": ME,
    "‹owner_full›": r"(?:Alex Morgan|Alex|[Tt]he owner)",
    "‹company›": r"(?:Example Co|Alex's company|[Tt]he owner's company)",
    "‹he›": r"(?:he|she|they|Alex|[Tt]he owner)", "‹He›": r"(?:He|She|They|Alex|The owner)",
    "‹him›": r"(?:him|her|them|Alex|the owner)",
    "‹his›": r"(?:his|her|their|Alex's|[Tt]he owner's)", "‹His›": r"(?:His|Her|Their|Alex's|The owner's)",
    "‹himself›": r"(?:himself|herself|themself|themselves)",
}


@functools.lru_cache(maxsize=None)
def _owned(phrase: str) -> "re.Pattern[str]":
    """A phrase written with Rouh's marks, as a pattern for the text that arrives with them filled in."""
    return re.compile("".join(_MARKS.get(part, re.escape(part))
                              for part in re.split(r"(‹\w+›)", phrase) if part))


def says(phrase: str, text: str) -> bool:
    """Whether `text` holds `phrase`, its marks filled in for whoever the owner is."""
    return bool(_owned(phrase).search(text or ""))


def partition(text: str, phrase: str) -> tuple[str, str, str]:
    """`str.partition` for a phrase written with marks."""
    found = _owned(phrase).search(text or "")
    if not found:
        return text or "", "", ""
    return text[:found.start()], found.group(0), text[found.end():]


def _sse(kind: str, payload: dict) -> bytes:
    return f"event: {kind}\ndata: {json.dumps(payload)}\n\n".encode()


#: The usage numbers on a `message_delta`. Both counts are given because the
#: real API gives both. The Messages API's `MessageDeltaUsage` has every field
#: optional, so a delta that sends only `output_tokens` leaves `input_tokens`
#: as None, and a reader that adds it to a running total raises inside the
#: stream and abandons the turn - which looks like the feature being broken and
#: cost an afternoon on 17 September 2026.
DELTA_USAGE = {"input_tokens": 1, "output_tokens": 1}


#: What makes this stand-in call a tool. The person types it, so a test never
#: has to reach past the page to start a job. The pattern finds the name and
#: where the arguments start; `tool_lines` reads the arguments.
TOOL_LINE = re.compile(r"TOOL\s+([A-Za-z_][A-Za-z0-9_]*)\s+(\{)")
#: Rouh's answer, given by the test in so many words (see `REPLY:` where the reply is made).
REPLY_LINE = re.compile(r"(?m)(?:^|\s)REPLY:\s*(.+)$")

#: With this word beside them, every `TOOL` line is called in the same reply,
#: side by side, the way a real model asks for lookups that do not depend on
#: each other; without it they are called one a round.
TOGETHER_LINE = re.compile(r"\bTOGETHER\b")

#: How a test makes the model refuse to answer. Typed into the box like
#: everything else here, so a test of what an overloaded model costs the
#: person is still a test of what the person does.
#:
#:   OVERLOAD 2                 the next two requests carrying these words
#:                              come back 529
#:   OVERLOAD 99 model=model-one
#:                              only when that model is the one being asked,
#:                              which is how a fallback chain is driven
#:   BADREQUEST                 400, every time, for the failures that do not
#:                              pass however often they are asked
#:   SPENTCAP                   400, every time, in Anthropic's own words for
#:                              an account past its monthly spending limit
#:   DROP 2                     the next two requests answer 200, open their
#:                              stream, and then break inside it with an
#:                              `error` event, which is how a real model that
#:                              becomes overloaded after the headers have gone
#:                              says so (`anthropic/_streaming.py`). The status
#:                              is 200 on this one, because the request itself
#:                              did not fail - that is the whole difference
#:                              from OVERLOAD, and the difference that ended
#:                              Petar's turn on 22 September 2026.
#:   DROP 99 billing_error      the same shape with a reason that does not
#:                              pass, so a test can show it is not hammered
OVERLOAD_LINE = re.compile(r"OVERLOAD\s+(\d+)(?:\s+model=(\S+))?")
BADREQUEST_LINE = re.compile(r"\bBADREQUEST\b")
SPENTCAP_LINE = re.compile(r"\bSPENTCAP\b")
SPENTCAP_WORDS = ("You have reached your specified API usage limits. "
                  "You will regain access on 2026-11-01 at 00:00 UTC.")
DROP_LINE = re.compile(r"DROP\s+(\d+)(?:\s+([a-z_]+_error))?")

#: What this stand-in thinks, when the request asks it to think. Written to
#: be unmistakable: a sentence with a made-up word in it, so a test that finds
#: it anywhere can say exactly where it leaked from.
THINKING = ("Let me work through this. The person is asking about SNORKELWEFT, "
            "so first I should check what they already told me, then decide "
            "whether to call a tool. I will not say any of this out loud.")


def thinking_asked_for(body: dict) -> bool:
    """Whether this request has extended thinking on."""
    asked = body.get("thinking")
    return isinstance(asked, dict) and asked.get("type") in ("adaptive", "enabled")


#: And how a test makes it never answer at all. The request is taken, the
#: stream is opened, and nothing else is ever written: the turn is left open,
#: which is what a test about a process dying mid-turn needs there to be.
HANG_LINE = re.compile(r"\bHANG\b")

#: How long one of those holds the connection before giving up on itself, in
#: seconds. Long enough that no test waits it out, short enough that a
#: forgotten one does not hold a port for the rest of the run.
HANG_SECONDS = 600

#: The first line of what the model is told about the turn marks. Its presence
#: in the system prompt is what makes this stand-in write one: it obeys the
#: instruction it was actually given rather than one it assumed, so a request
#: without the marks in it comes back without a mark.
# The first line of the rule "turn-marks", which a turn of words from the microphone is told, as a new Rouh starts
# with it (`rouh/rule_defaults_fallback.json`).
MARK_INSTRUCTION = next(r["text"] for r in __import__("rouh.ruledefaults", fromlist=["fallback"]).fallback()["rules"]
                        if r["key"] == "turn-marks").strip().splitlines()[0]

#: How a test makes this stand-in say the person had not finished asking.
#: The person's own words ask for it, the same way `TOOL` and `SLOWLY` do, and
#: for a spoken test those words are what the stand-in transcriber heard.
#:
#:   NOTFINISHED     cut off mid-sentence: the reply is the mark and nothing else
#:   STILLTHINKING   announced and not said yet: the same
#:   THATSALL        finished, whatever came before it
#:
#: The last of them in what they have said is the one that counts, because
#: every utterance joins the one before it: somebody who says "start a new
#: task" and then finishes the sentence is still carrying the first half of it
#: around, and a model that read only the first half would never answer.
MARKS_BY_WORD = {"NOTFINISHED": CUT_OFF_MID_THOUGHT,
                 "STILLTHINKING": STILL_THINKING,
                 "THATSALL": FINISHED}
MARK_WORDS = re.compile(r"\b(%s)\b" % "|".join(MARKS_BY_WORD))


def turn_mark(body: dict) -> str:
    """The mark this reply starts with, or "" when none was asked for."""
    if MARK_INSTRUCTION not in _flat(body.get("system")):
        return ""
    messages = body.get("messages") or []
    if messages and is_note(messages[-1]):
        # Rouh's own software has asked for an answer to what there is,
        # whatever state the words are in, and has said to start the reply
        # with the finished mark. A real model does as it is told there, so
        # this does too - otherwise a question nobody is going to add to would
        # never be answered at all.
        return FINISHED
    found = MARK_WORDS.findall(last_user_text(body))
    return MARKS_BY_WORD[found[-1]] if found else FINISHED


#: A fresh id for every tool call, the way the real API gives one.
#:
#: It was one fixed string until 19 September 2026, and that was invisible
#: until something kept state per call: the work tree holds a node per
#: tool_use_id, so two calls sharing an id were one node, the second call was
#: dropped as a duplicate of the first, and a test that called the same tool
#: twice saw the second call never appear on the orb.
_call_ids = (f"toolu_fake{n:04d}" for n in itertools.count(1))

#: How many failures are left to serve, by the exact words that asked for
#: them. Keyed on the whole line so two tests in one process do not share a
#: countdown.
_overloads: dict[str, int] = {}


def failing(body: dict) -> tuple[int, str, str] | None:
    """The status this request should come back as, and why, or nothing.

    A retry re-sends the identical body, so counting down here counts the
    retries: `OVERLOAD 2` fails, fails, then answers.
    """
    said = " ".join(b.get("text") or "" for b in last_user_blocks(body)
                    if b.get("type") == "text")
    if SPENTCAP_LINE.search(said):
        return 400, "invalid_request_error", SPENTCAP_WORDS
    if BADREQUEST_LINE.search(said):
        return 400, "invalid_request_error", "invalid_request_error"
    found = OVERLOAD_LINE.search(said)
    if not found:
        return None
    wanted_model = found.group(2)
    if wanted_model and body.get("model") != wanted_model:
        return None
    key = said.strip()
    if key not in _overloads:
        _overloads[key] = int(found.group(1))
    if _overloads[key] > 0:
        _overloads[key] -= 1
        return 529, "overloaded_error", "overloaded_error"
    return None


#: The same countdown for the stream that breaks in the middle, kept apart
#: from `_overloads` so one line can ask for both.
_drops: dict[str, int] = {}


def dropping(body: dict) -> str:
    """The error type this request's stream should break with, or "".

    The response is still 200 and the stream still opens; what comes down it
    is an `error` event instead of the reply. Counted down like `failing`, so
    `DROP 2` breaks twice and then answers.
    """
    said = " ".join(b.get("text") or "" for b in last_user_blocks(body)
                    if b.get("type") == "text")
    found = DROP_LINE.search(said)
    if not found:
        return ""
    key = said.strip()
    if key not in _drops:
        _drops[key] = int(found.group(1))
    if _drops[key] <= 0:
        return ""
    _drops[key] -= 1
    return found.group(2) or "overloaded_error"


#: And what makes it take its time. A turn that can be stopped part way through
#: has to last long enough to be stopped part way through: with this in the
#: question the answer is written a word at a time, over ten seconds or so,
#: which is a turn a person would really reach for Escape during. The words
#: come out faster than `fake_voice.py` can say them, on purpose, so the page
#: is always several seconds of audio ahead of the speaker - which is the state
#: a real reply is in when somebody stops it, and the backlog a stop has to
#: throw away.
SLOW_MARK = "SLOWLY"

#: What it says while it takes its time. Whole sentences, each comfortably over
#: `brain.MIN_SPOKEN_CHARS`, so the splitter hands them to the voice one at a
#: time rather than saving them all up for the end.
SLOW_ANSWER = (
    "I am going through the whole list for you now and it will take a moment. "
    "The first job you asked about finished earlier this morning without any trouble. "
    "The second one is still running and has not reported anything back yet. "
    "The third one stopped part way and left its notes behind in its folder. "
    "The fourth one has not been started at all and is waiting on the one before it. "
    "I will carry on down the list and tell you about each one as I reach it."
)

#: And what makes it say back the notes it was sent. A note Rouh's own
#: software writes into a conversation without starting a turn - an archive
#: pressed on the inbox card (`runtime.InboxNotes`) - is only ever read by the
#: turn after it, and this stand-in steps over notes (`last_user_blocks`), so
#: nothing on the screen could show it arrived. With this word in the question
#: the answer is every note in the request, oldest first, or "Notes I was sent:
#: none" when there are none.
NOTES_LINE = re.compile(r"\bNOTES\b")


def asks_for_notes(body: dict) -> bool:
    said = " ".join(b.get("text") or "" for b in last_user_blocks(body)
                    if b.get("type") == "text")
    return bool(NOTES_LINE.search(said))


def notes_said(body: dict) -> str:
    """Every note of Rouh's own in the request, but the one that asks for an answer now."""
    notes = []
    for message in body.get("messages") or []:
        if message.get("role") != "user" or not is_note(message):
            continue
        flat = _flat(message.get("content"))
        if flat != " ".join(ANSWER_NOW.split()):
            notes.append(flat)
    return ("Notes I was sent: " + " | ".join(notes)) if notes else "Notes I was sent: none"


#: How long a word takes to arrive while it is being slow.
SLOW_WORD_SECONDS = 0.15

#: And what makes it answer at length, in Markdown: headings, bold, a list, a
#: link, a table and a code fence, over nine thousand characters. It is what
#: an answer sent to the phone has to be split for, and plain text made of,
#: so `rouh/telegram_chat.py` can be watched doing both.
LONG_LINE = re.compile(r"\bLONGANSWER\b")


def asks_for_long(body: dict) -> bool:
    said = " ".join(b.get("text") or "" for b in last_user_blocks(body)
                    if b.get("type") == "text")
    return bool(LONG_LINE.search(said))


def long_answer() -> str:
    """A long answer, every part of it numbered so a split can be read back whole."""
    parts = ["# The long answer\n\nHere is **everything**, in *twenty* parts, with "
             "`nothing` left out. See [the plan](https://example.com/plan) first.\n"]
    for n in range(1, 21):
        parts.append(
            f"## Part {n}\n\n"
            f"- Point {n}.1 is about __the first thing__ and it goes on for a while so "
            "that the answer is long enough to need more than one message on a phone.\n"
            f"- Point {n}.2 is about the second thing, which matters just as much as the "
            "first one and takes about as many words to say properly.\n"
            f"- Point {n}.3 closes the part, and says that part {n} is over.\n\n"
            "| What | How many |\n|---|---|\n"
            f"| Apples | {n * 3} |\n| Pears | {n * 5} |\n\n"
            f"```\nprint('part {n}')\n```\n")
    parts.append("That is the end of the long answer.")
    return "\n".join(parts)


def is_slow(body: dict) -> bool:
    """Did the person ask this stand-in to take its time?

    The last thing the person actually said decides it, and only that. Looking
    anywhere further back would make every later turn in the same conversation
    slow as well, because the words that asked for it are still in the history.
    Messages carrying nothing but tool results are stepped over rather than
    counted: by the time a tool has answered, the question is two messages back
    and still the question being answered. So is a note from Rouh's own
    software, for the reason `last_user_blocks` gives.
    """
    for msg in reversed(body.get("messages") or []):
        if msg.get("role") != "user" or (is_note(msg) and not is_step_note(msg)
                                         and not is_clock_note(msg)):
            continue
        content = msg.get("content")
        if isinstance(content, str):
            return SLOW_MARK in content
        texts = [b.get("text") or "" for b in content or []
                 if isinstance(b, dict) and b.get("type") == "text"]
        if not texts:
            continue
        return any(SLOW_MARK in t for t in texts)
    return False


def last_user_blocks(body: dict) -> list[dict]:
    """The content blocks of the last thing the person (or a tool) said.

    A message whose content is a plain string - which is what a typed line with
    nothing attached to it is - is read as one text block, so the caller has one
    shape to deal with rather than two.

    A note from Rouh's own software is stepped over rather than read as the
    person (`turnmarks.is_note`). One rides on the end of every request that
    asks for an answer now, and without this the words a test typed - `TOOL`,
    `SLOWLY`, an address to fetch - would be one message too far back to see.
    """
    for message in reversed(body.get("messages") or []):
        if message.get("role") != "user" or (is_note(message) and not is_mail_brief(message)
                                             and not is_clock_note(message)
                                             and not is_step_note(message)):
            continue
        content = message.get("content")
        if isinstance(content, str):
            return [{"type": "text", "text": content}]
        return [b for b in (content or []) if isinstance(b, dict)]
    return []


def tool_lines(text: str) -> list[tuple[str, dict]]:
    """Every `TOOL name {json}` in these words, in the order they were typed.

    Read with the JSON decoder rather than the pattern alone, so two of them on
    one line are two calls and not one call whose arguments run from the first
    brace to the last. One whose arguments are not a JSON object is skipped.
    """
    calls = []
    for found in TOOL_LINE.finditer(text or ""):
        try:
            args, _end = json.JSONDecoder().raw_decode(text, found.start(2))
        except ValueError:
            continue
        if isinstance(args, dict):
            calls.append((found.group(1), args))
    return calls


def wanted_tool(body: dict) -> tuple[str, dict] | None:
    """The next tool the person's words ask for, if the turn is still theirs.

    One call a round, in the order they were typed: `TOOL a {} TOOL b {}` is
    a, its result, then b, which is the shape of a real turn that reads the
    inbox and then draws what it found. A turn like that stores more than one
    question and one answer, and a stand-in that could only ever make one call
    hid everything that reads a turn as those two rows - the naming of a chat
    among them, until 24 September 2026.

    None once every one of them has had its result back, which is what ends
    the loop: the reply to the last result is words, or Rouh would call the
    same tools forever. The results counted are only this turn's, the ones
    after the person's own message, so a tool called in an earlier turn is not
    called again.
    """
    calls, answered, _said = _typed_calls(body)
    return calls[answered] if answered < len(calls) else None


def wanted_tools(body: dict) -> list[tuple[str, dict]]:
    """Every tool this reply calls: the next one, or all of them at once.

    With `TOGETHER` in the person's words, the first reply calls every `TOOL`
    line side by side and the one after their results is words. Without it,
    `wanted_tool`.
    """
    calls, answered, said = _typed_calls(body)
    if TOGETHER_LINE.search(said):
        return calls if answered == 0 else []
    return calls[answered:answered + 1]


def _typed_calls(body: dict) -> tuple[list[tuple[str, dict]], int, str]:
    """The `TOOL` lines in the person's last words, how many rounds of results
    have come back since, and the words themselves."""
    answered = 0
    for message in reversed(body.get("messages") or []):
        if message.get("role") != "user" or (is_note(message) and not is_mail_brief(message)
                                             and not is_clock_note(message)
                                             and not is_step_note(message)):
            continue
        content = message.get("content")
        blocks = ([{"type": "text", "text": content}] if isinstance(content, str)
                  else [b for b in (content or []) if isinstance(b, dict)])
        if any(b.get("type") == "tool_result" for b in blocks):
            answered += 1
            continue
        said = " ".join(b.get("text") or "" for b in blocks if b.get("type") == "text")
        if is_clock_note(message):
            # The person's own words a scheduled row keeps are quoted after its instruction
            # (`reminders.their_words`): what they said then, not something to do again now.
            said = said.split(THEIR_WORDS)[0]
        return tool_lines(said), answered, said
    return [], 0, ""


#: The generation of a model id, by family: "claude-sonnet-5" is 5.
#:
#: Searched rather than anchored, because a Bedrock or Vertex id puts the
#: vendor in front of the same name.
_GENERATION = re.compile(r"(?:sonnet|opus|fable|haiku)-(\d{1,2})(?!\d)")


def _generation(model: str) -> int:
    found = _GENERATION.search((model or "").lower())
    return int(found.group(1)) if found else 0


def refuses(body: dict) -> str:
    """Why the real API would answer this request with a 400, or "" if it would not.

    The rules a test cannot afford to take on trust. The models Rouh runs on
    now - Sonnet 5, which answers out loud, and Opus 5.5 - dropped the sampling
    parameters and the hand-sized thinking budget that every model before them
    took, and they do not ignore them: the request fails outright, every turn,
    and the person gets no answer at all.

    That is the whole failure this stands in for. A temperature left on a
    request, or extended thinking turned on by hand, is a one-line change that
    passes every unit test, answers nothing in front of the person, and is
    indistinguishable here from the model simply not replying. So this says no,
    in the shape the API says it, and a browser test that asks for an answer
    out loud catches it on the way past.

    Left deliberately narrow: only what Anthropic documents as rejected. A
    stand-in that invents a rule is worse than one that misses it.
    """
    # The real API refuses the whole request when two tools share a name. The
    # containers sent run_command twice on 31 October 2026 and every chat there
    # failed with exactly this, while the stand-in went on answering.
    names = [t.get("name") for t in body.get("tools") or [] if isinstance(t, dict)]
    if len(names) != len(set(names)):
        return "tools: Tool names must be unique."
    model = body.get("model") or ""
    thinking = body.get("thinking")
    if _generation(model) < 5:
        # The other way round, and the one nobody looks for: Haiku 4.5 is in
        # the picker beside the other two and takes neither an effort level nor
        # adaptive thinking. A request built for the model that answers most of
        # the time is a 400 here and the person gets silence.
        if (body.get("output_config") or {}).get("effort"):
            return ("output_config.effort: Extra inputs are not permitted. "
                    "This model does not support effort.")
        if isinstance(thinking, dict) and thinking.get("type") == "adaptive":
            return ("thinking.type: Input should be 'enabled' or 'disabled'. "
                    "Adaptive thinking arrived with the 4.6 generation.")
        return ""                       # everything else 4.5 and earlier takes
    for name in ("temperature", "top_p", "top_k"):
        if body.get(name) is not None:
            return (f"{name}: Extra inputs are not permitted. "
                    "This model does not support sampling parameters.")
    if isinstance(thinking, dict):
        if thinking.get("budget_tokens") is not None:
            return ("thinking.budget_tokens: Extra inputs are not permitted. "
                    "Use `output_config.effort` instead.")
        if thinking.get("type") == "enabled":
            return ("thinking.type: Input should be 'adaptive' or 'disabled'. "
                    "Extended thinking is not configured by hand on this model.")
        # Opus 5.5 thinks whether it is asked to or not: turned off, at any
        # effort, is a 400. Effort is the only dial it has.
        if thinking.get("type") == "disabled" and _thinks_always(model):
            return ("thinking.type: Input should be 'adaptive'. "
                    "Thinking cannot be disabled on this model; lower the effort instead.")
        # Opus 5 takes thinking turned off, but only up to effort high. Asked
        # to think its hardest with thinking off, it refuses the pair rather
        # than choosing one of them.
        effort = (body.get("output_config") or {}).get("effort")
        if (thinking.get("type") == "disabled" and "opus" in model.lower()
                and effort in ("xhigh", "max")):
            return f"thinking: Thinking may not be disabled at effort {effort}."
    # Nor will it be made to call a tool: it chooses, and a request that
    # chooses for it is refused.
    if (_thinks_always(model)
            and (body.get("tool_choice") or {}).get("type") in ("any", "tool")):
        return 'tool_choice: type "tool" and "any" are not supported for this model.'
    return ""


def _thinks_always(model: str) -> bool:
    """Opus 5.5, which took thinking-off and forced tool use away from Opus 5."""
    return "opus-5-5" in (model or "").lower()


#: About how many bytes of a request make one token. The real count is the
#: tokenizer's and is often nearer three for HTML; four keeps this stand-in
#: from refusing anything the real API would take, and a request made to be
#: too long is too long by far more than the difference.
BYTES_A_TOKEN = 4


def _attached_bytes(value) -> int:
    """The bytes of pictures and documents sent inline, which the real API
    counts by what they are and not by their length."""
    if isinstance(value, dict):
        if value.get("type") == "base64" and isinstance(value.get("data"), str):
            return len(value["data"])
        return sum(_attached_bytes(v) for v in value.values())
    if isinstance(value, list):
        return sum(_attached_bytes(v) for v in value)
    return 0


def context_window(model: str) -> int:
    """How many tokens the model reads at once: a million for Opus 5.5, Opus 5
    and Sonnet 5, two hundred thousand for Haiku 4.5."""
    return 1_000_000 if _generation(model) >= 5 else 200_000


def too_long(raw: bytes, body: dict) -> str:
    """The real API's refusal of a request past the model's context window, or "".

    Its own words, "prompt is too long: 1052341 tokens > 1000000 maximum",
    because those are what a reader of the refusal looks for
    (`askai.overflowed`). A page too big for the model is how a test gets
    here: nothing typed asks for it.
    """
    window = context_window(body.get("model") or "")
    tokens = (len(raw) - _attached_bytes(body)) // BYTES_A_TOKEN
    if tokens <= window:
        return ""
    return f"prompt is too long: {tokens} tokens > {window} maximum"


# --------------------------------------------------------------------------
# Standing in for the prompt cache.
# --------------------------------------------------------------------------

#: The most breakpoints the real API takes in one request. A fifth is a 400.
MOST_BREAKPOINTS = 4

#: How many blocks back a breakpoint looks for a prefix an earlier request
#: wrote. The real API counts a run of tool calls, or of tool results, as one
#: block; here every block is one, which only ever finds less than it would.
LOOKBACK = 20

#: The shortest prefix the real API writes, in tokens. Shorter, a breakpoint
#: writes nothing and says nothing about it. Opus 5 writes from 512 and Haiku
#: 4.5 from 4096; this is between, and far below any prompt of Rouh's.
MIN_CACHED = 1024

#: How long a prefix is kept, in seconds, from the request that last wrote or
#: read it, by the `ttl` its breakpoint named.
TTL_SECONDS = {"5m": 300, "1h": 3600}

#: The prefixes written so far: digest of the prompt up to a breakpoint ->
#: (when it goes, how long it lives). One for the whole server, as the real
#: one is one for a whole workspace.
_cached: dict[str, tuple[float, int]] = {}


def _ttl_of(block) -> int:
    """How long the breakpoint on this block keeps its prefix, or 0 for none."""
    mark = block.get("cache_control") if isinstance(block, dict) else None
    if not isinstance(mark, dict):
        return 0
    return TTL_SECONDS.get(mark.get("ttl") or "5m", TTL_SECONDS["5m"])


def _positions(body: dict) -> list[tuple[str, int, int]]:
    """The prompt the way the API reads it, one block at a time, in its order:
    the tools, the system prompt, then the messages.

    For each block: a digest of everything up to and including it, its size
    in tokens, and how long its breakpoint keeps it (0 for none). The digest
    leaves `cache_control` out, because a mark says where to cache and is not
    part of what is cached; and it starts from the model, because a cache is
    the model's own. A message whose content is a string is the one text
    block it is on the wire.
    """
    digest = hashlib.sha256(("model " + str(body.get("model") or "")).encode())
    out: list[tuple[str, int, int]] = []

    def take(lead: str, block) -> None:
        plain = ({k: v for k, v in block.items() if k != "cache_control"}
                 if isinstance(block, dict) else block)
        text = lead + json.dumps(plain, sort_keys=True, ensure_ascii=False)
        digest.update(text.encode())
        size = max(1, (len(text) - _attached_bytes(plain)) // BYTES_A_TOKEN)
        out.append((digest.hexdigest(), size, _ttl_of(block)))

    for tool in body.get("tools") or []:
        take("tool ", tool)
    system = body.get("system")
    if isinstance(system, str):
        system = [{"type": "text", "text": system}] if system else []
    for block in system or []:
        take("system ", block)
    # Thinking and effort are read ahead of the messages: changing either
    # misses the conversation's cache and keeps the prompt's.
    digest.update(json.dumps([body.get("thinking"),
                              (body.get("output_config") or {}).get("effort")],
                             sort_keys=True).encode())
    for message in body.get("messages") or []:
        content = message.get("content")
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
        for n, block in enumerate(content or []):
            take(("\n" + str(message.get("role")) + " ") if n == 0 else " ", block)
    return out


def server_call_refusal(body: dict) -> str:
    """The real API's 400 about a call of its own that lost its result, or "".

    Learned from the real API on 5 and 6 October 2026 (`llm_requests` 41425,
    51597, 53144, 53216, and the chats that went on fine around them): a
    `server_tool_use` is answered by a result block naming it in the same
    reply, or, asked for beside a tool of the caller's, by the reply after the
    tool results it waited for. A call still waiting in the newest reply is
    run when the request goes out, but only when nothing but tool results
    follows it; a line of text after them, or a new question after them in a
    later turn, is refused. Messages of one role next to each other are read
    as one, as the API reads them; the index said is the request's own, which
    is not always the one the API says (its numbering is its own).
    """
    merged: list[tuple[str, list]] = []
    first: list[int] = []
    for n, message in enumerate(body.get("messages") or []):
        content = message.get("content")
        blocks = ([{"type": "text", "text": content}] if isinstance(content, str)
                  else list(content or []))
        if merged and merged[-1][0] == message.get("role"):
            merged[-1][1].extend(blocks)
        else:
            merged.append((message.get("role"), blocks))
            first.append(n)

    def results(blocks) -> set:
        return {b.get("tool_use_id") for b in blocks
                if str(b.get("type", "")).endswith("_tool_result")
                and b.get("type") not in ("tool_result", "mcp_tool_result")}

    def only_results(blocks) -> bool:
        return bool(blocks) and all(b.get("type") == "tool_result" for b in blocks)

    for i, (role, blocks) in enumerate(merged):
        if role != "assistant":
            continue
        later = set()
        if (i + 2 < len(merged) and merged[i + 1][0] == "user"
                and only_results(merged[i + 1][1])):
            later = results(merged[i + 2][1])
        waiting = (i == len(merged) - 1
                   or (i == len(merged) - 2 and only_results(merged[-1][1])))
        for b in blocks:
            if b.get("type") != "server_tool_use" or waiting:
                continue
            if b.get("id") in results(blocks) or b.get("id") in later:
                continue
            name = b.get("name") or ""
            kind = "tool_search" if name.startswith("tool_search") else name
            return (f"messages.{first[i]}: `{name}` tool use with id `{b.get('id')}` was found "
                    f"without a corresponding `{kind}_tool_result` block")
    return ""


def cache_refusal(body: dict) -> str:
    """The real API's 400 about this request's breakpoints, or "".

    Two rules, both of them Anthropic's own: four breakpoints at most, and a
    prefix kept an hour never after one kept five minutes.
    """
    ttls = [ttl for _digest, _size, ttl in _positions(body) if ttl]
    if len(ttls) > MOST_BREAKPOINTS:
        return (f"A maximum of {MOST_BREAKPOINTS} blocks with cache_control may be "
                f"provided. Found {len(ttls)}.")
    shorter = 0
    for ttl in ttls:
        if shorter and ttl > shorter:
            return ("A cache_control block with ttl='1h' must not come after one "
                    "with ttl='5m'.")
        shorter = ttl if not shorter else min(shorter, ttl)
    return ""


def cache_usage(body: dict, now: float | None = None) -> dict:
    """What the real API would bill this request's input as, and its cache left
    as the request would leave it.

    Each breakpoint looks for a prefix already written at itself or up to
    `LOOKBACK` blocks before it, and the longest one found is read. Every
    breakpoint past that is written, and what is written is billed once, from
    the end of what was read to the last breakpoint. The rest is sent at the
    full price. A read keeps its prefix as long again.

    `{"input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens",
    "cache_creation"}`, the names the real usage has, the last of them how the
    writes split between the two lifetimes.
    """
    now = time.time() if now is None else now
    positions = _positions(body)
    upto, total = [], 0
    for _digest, size, _ttl in positions:
        total += size
        upto.append(total)
    marks = [n for n, (_digest, _size, ttl) in enumerate(positions) if ttl]
    hit = -1
    for mark in marks:
        for n in range(mark, max(-1, mark - LOOKBACK - 1), -1):
            kept = _cached.get(positions[n][0])
            if kept and kept[0] > now:
                hit = max(hit, n)
                break
    read = upto[hit] if hit >= 0 else 0
    if hit >= 0:
        _cached[positions[hit][0]] = (now + _cached[positions[hit][0]][1],
                                      _cached[positions[hit][0]][1])
    # Each stretch written is billed at the lifetime of the breakpoint that
    # ends it, and the usage says how the writes split between the two.
    split = {"ephemeral_5m_input_tokens": 0, "ephemeral_1h_input_tokens": 0}
    end = read
    for mark in marks:
        if mark > hit and upto[mark] >= MIN_CACHED:
            ttl = positions[mark][2]
            _cached[positions[mark][0]] = (now + ttl, ttl)
            key = ("ephemeral_1h_input_tokens" if ttl >= TTL_SECONDS["1h"]
                   else "ephemeral_5m_input_tokens")
            split[key] += upto[mark] - end
            end = upto[mark]
    written = end - read
    return {"input_tokens": total - end, "cache_read_input_tokens": read,
            "cache_creation_input_tokens": written, "cache_creation": split}


def usage_file(record_dir: str) -> str:
    """Where every request's usage is written down, a line of JSON each, beside
    the directory the requests themselves are written to: the file it was
    written under, its model, how many breakpoints it carried, and its usage."""
    return record_dir.rstrip("/") + "-usage.jsonl"


def an_offer_of_work(body: dict) -> str:
    """The real model's last sentence when the prompt says the person asked for this before
    (`rouh/asked_again.py`): the offer to do it as scheduled work, with the rhythm it was told."""
    system = body.get("system")
    text = (" ".join(b.get("text") or "" for b in system if isinstance(b, dict))
            if isinstance(system, list) else str(system or ""))
    found = re.search(r"Asked again: .*? from now on, (every [^,]+ at \d\d:\d\d)", text, re.S)
    if not found:
        return ""
    return (f" You have asked me for this before, so shall I do it for you by itself from now "
            f"on, {found.group(1)}, as scheduled work on Clockwork?")


def describe(body: dict) -> str:
    """What the last user message carried, in words a test can look for.

    Every fact here is read out of the request itself, so if the file did not
    arrive the sentence cannot mention it.

    The blocks come from `last_user_blocks`, which reads a message whose content
    is a plain string as one text block. A turn spoken to Rouh carries blocks;
    a question typed into the Ask AI drawer on a workspace page carries a string,
    which this used to describe as "nothing" - the stand-in saying the question
    had not arrived when it had.
    """
    said: list[str] = []
    for block in last_user_blocks(body):
        kind = block.get("type")
        if kind == "image":
            raw = base64.b64decode(block.get("source", {}).get("data", ""))
            said.append(
                f"image {block['source'].get('media_type', '?')} "
                f"{len(raw)} bytes sha256:{hashlib.sha256(raw).hexdigest()[:16]}"
            )
        elif kind == "document":
            raw = base64.b64decode(block.get("source", {}).get("data", ""))
            # The words a PDF draws are in plain view between brackets in
            # its content stream, which is enough to prove the pages came
            # across rather than a path to them.
            words = b" ".join(re.findall(rb"\(([ -~]{3,})\)", raw)[:8]).decode("ascii", "replace")
            said.append(
                f"document application/pdf {len(raw)} bytes "
                f"sha256:{hashlib.sha256(raw).hexdigest()[:16]} reading {words}"
            )
        elif kind == "text":
            # The whole block on one line, not its first line: a text file
            # arrives under a heading that names it, and the words of the
            # file itself are below that.
            flat = " ".join((block.get("text") or "").split())
            said.append("text " + flat[:400])
        elif kind == "tool_result":
            # What a tool handed back, on its way to the model. A real model
            # would read this and answer out of it, so saying it back is what
            # lets a browser test see a tool's answer arrive on the screen
            # rather than only on the tool's own chip, which is one truncated
            # line.
            said.append("tool result " + _flat(block.get("content"))[:1200])
    return "I received: " + ("; ".join(said) if said else "nothing")


# --------------------------------------------------------------------------
# Standing in for the model that names a chat.
# --------------------------------------------------------------------------

#: How a naming request is told apart from a turn of conversation: by the first
#: words of the system prompt `rouh/chats.py` sends. Nothing else this server
#: is asked says them.
NAMING = "You name conversations"

#: An emoji per subject, so the stand-in's titles are about the conversation
#: rather than all the same. Every title starts with one, which is the rule the
#: real model is given and the thing the page relies on.
TITLE_EMOJI = (
    ("migrat", "\N{DELIVERY TRUCK}"),
    ("orchestra", "\N{MUSICAL SCORE}"),
    ("mail", "\N{ENVELOPE}"),
    ("money", "\N{BAR CHART}"),
    ("revenue", "\N{BAR CHART}"),
    ("invoice", "\N{RECEIPT}"),
    ("tomato", "\N{SEEDLING}"),
    ("garden", "\N{SEEDLING}"),
    ("whale", "\N{SPOUTING WHALE}"),
)

#: When nothing in the conversation matches the table above.
TITLE_DEFAULT = "\N{SPIRAL NOTE PAD}"

#: Words that are how a question is asked rather than what it is about. A real
#: model names the subject; this one gets there by dropping these, so "tell me
#: about the orchestra migration" is titled "Orchestra migration" and not "tell me
#: about the".
TITLE_SKIP = frozenset(
    "tell me about the a an what is are can you could please i want to of do "
    "does did how much many why when who which for on in at it that this and "
    "or we us my our your should would there here".split())

#: What a recorded naming request's file name starts with. See the writing of
#: it below for why it is kept apart from the turns.
TITLE_FILE = "title-"


# --------------------------------------------------------------------------
# Standing in for the model that reads a feedback and decides what to build.
# --------------------------------------------------------------------------
#
# The same errand as naming a chat, and told apart the same way: by the first
# words of the system prompt `rouh/triage.py` sends. It answers with the JSON
# object that module parses, written out of the feedback that actually arrived,
# so a browser test that sees a feature request on the board knows the feedback
# reached the model rather than that a fixture guessed the same words.
#
# Every way this can fail is still a test's to ask for, in the person's own
# words, because the words are what arrive here: feedback with `BADREQUEST` in
# it is refused, and `OVERLOAD 2` is overloaded, which is how the path where
# the model cannot be asked - `triage.guess`, the person's own words - is
# driven from the drawer.

TRIAGE = "You read feedback about Rouh"

#: What a recorded triage request's file name starts with, so it is not read as
#: a turn of conversation either.
TRIAGE_FILE = "triage-"

#: Which kind this stand-in decides on, by the first pattern that matches what
#: was written. A real model reads the sentence; this gets close enough for a
#: test to tell one kind from another on the screen.
TRIAGE_KINDS = (
    (re.compile(r"(?i)\b(broken|crash|error|fails?|wrong|bug|does ?n.t work)\b"), "bug"),
    (re.compile(r"(?i)\b(how|why|what|when|which)\b.*\?"), "question"),
    (re.compile(r"(?i)\b(automatic|faster|better|instead|should)\b"), "improvement"),
)


def is_triage(body: dict) -> bool:
    return TRIAGE in _flat(body.get("system"))


def a_decision(body: dict) -> str:
    """The JSON `rouh/triage.read_back` reads, out of the feedback that arrived.

    Deliberately the whole shape, fence and all left off: the module takes the
    first object in the text, and answering with exactly one object is what the
    real model is told to do.
    """
    said = last_user_text(body)
    written = said.split("What they wrote:", 1)[-1]
    written = written.split("Answer with the JSON object", 1)[0].strip()
    first = ""
    for line in written.splitlines():
        if line.strip():
            first = line.strip()
            break
    kind = "feature"
    for pattern, named in TRIAGE_KINDS:
        if pattern.search(written):
            kind = named
            break
    words = [w for w in re.findall(r"[\w'\u0400-\u04ff-]+", first)
             if w.lower() not in TITLE_SKIP][:6]
    title = " ".join(words) if words else "Something they said"
    return json.dumps({
        "kind": kind,
        "title": title,
        "body": ("What they wanted: " + (first or "nothing was written") + "\n\n"
                 "How the solution should work: build the smallest thing that "
                 "gives them that, prove it in a real browser, and say on the "
                 "screen what changed."),
    })


# --------------------------------------------------------------------------
# Standing in for the model that rewrites a step of a goal (`goals.revise`).
# --------------------------------------------------------------------------
#
# Told apart by the first words of its system prompt, and answered out of what
# arrived: the step as it stood, with whatever the person had typed into it,
# and what they asked for. The ask is put at the front of the step's "how", so
# a test sees that both its typed words and its ask really travelled.
# "TITLE: words" in the ask renames the step as well.

# --------------------------------------------------------------------------
# Standing in for the model that says what a run was for.
# --------------------------------------------------------------------------
#
# Told apart by the first words of the system prompt `rouh/runsummary.py`
# sends, and answered out of what arrived: the first line of the brief that is
# words rather than a heading, as one sentence, so a test that sees it on a
# green run's card knows the brief really travelled to the model.

SUMMING = "You say what a piece of work is for"
SUMMARY_FILE = "summary-"


def is_summing(body: dict) -> bool:
    return SUMMING in _flat(body.get("system"))


def a_summary(body: dict) -> str:
    said = last_user_text(body)
    _, _, brief = said.partition("The brief:")
    brief = brief.rsplit("Answer with the one sentence.", 1)[0]
    for line in brief.splitlines():
        if line.strip().startswith("#"):
            continue
        line = line.strip().lstrip(">*- ").strip()
        if len(line) > 3:
            first = re.split(r"(?<=[.!?])\s", line, maxsplit=1)[0].rstrip(".!?")
            return f"Get this done: {first}."
    return "Get the job it was given done."


# --------------------------------------------------------------------------
# Standing in for the model that titles a reminder.
# --------------------------------------------------------------------------
#
# Told apart by the first words of `reminder_titles.SYSTEM`, and answered out of
# the reminder's own words: "TITLE: words" in them is the title, word for word;
# otherwise "Titled: " and their first five words, links left out, so a test
# that sees it on the Reminders page knows the words really travelled.

TITLING = "You give a reminder a title"
TITLING_FILE = "reminder-title-"


def is_titling(body: dict) -> bool:
    return TITLING in _flat(body.get("system"))


def a_reminder_title(body: dict) -> str:
    said = last_user_text(body)
    _, _, words = said.partition("The words:")
    words = words.rsplit("Answer with the title alone.", 1)[0]
    asked = re.search(r"TITLE:\s*([^.\n]+)", words)
    if asked:
        return asked.group(1).strip()
    kept = [w for w in re.sub(r"\(?https?://\S+", " ", words).split() if w.strip()]
    return "Titled: " + " ".join(kept[:5])


# --------------------------------------------------------------------------
# Standing in for the heartbeat's wake-up check (`heartbeat.wake_check`).
# --------------------------------------------------------------------------
#
# Told apart by the first words of `heartbeat.CHECK_SYSTEM`. It wakes the
# decision unless what it reads says `HEARTBEAT SLEEP` (put it in the
# heartbeat's own words, "Also, in your words", which every beat's note
# carries), and then it lets the beat sleep.

HEARTBEAT_CHECKING = "You are the wake-up check of Rouh's heartbeat."
HEARTBEAT_CHECK_FILE = "heartbeatcheck-"


def is_heartbeat_checking(body: dict) -> bool:
    return HEARTBEAT_CHECKING in _flat(body.get("system"))


def a_heartbeat_check(body: dict) -> str:
    if "HEARTBEAT SLEEP" in last_user_text(body):
        return json.dumps({"wake": False, "why": "The stand-in was told to let this beat sleep."})
    return json.dumps({"wake": True, "why": "The stand-in wakes every beat it is not told about."})


# --------------------------------------------------------------------------
# Standing in for What to raise before a meeting (`rouh/meeting_brief.py`).
# --------------------------------------------------------------------------
#
# Told apart by the first words of its instructions (`meeting_brief.ASK`). It
# answers from what it was given, so a world sees its own emails come back: the
# newest email's subject and sender are where things stand, the first sentence
# of each of the newest three is a point to raise, and a question mark in an
# email is something open. `MEETINGBRIEF NOTHING` in an email answers that the
# mail says nothing that bears on the meeting; `MEETINGBRIEF FAIL` answers with
# no object at all; and a line `MEETINGBRIEF SHAPED {...}` in an email is the
# answer, word for word, for a world that wants to show what a real reading looks like.
# Asked again with the owner's corrections (`meeting_brief.corrected_question`), it
# says where things stand as each of them, oldest first, before the rest, so a
# world sees what he typed come back; `MEETINGBRIEF FAIL` typed as a correction
# answers with no object, which is how a world sees a correction fail.
# With what it remembers (night 7, `raise_memory`), each fact he told it before is
# said first as "Remembered: ...", the standing names the newest earlier meeting,
# that meeting's first action item is the first point to raise, and its second is open.
# With Slack messages (22 October 2026, `meeting_slack.for_reading`), the standing says
# how many it read and who wrote the newest, and the newest is a point to raise.
# With documents attached to the invitation (night 31, `raise_attached`), the standing names
# the first, and its words after its first line are a point to raise.

MEETING_BRIEFING = "You prepare ‹owner› for a meeting with people from outside ‹his› company."
MEETING_BRIEF_FILE = "meetingbrief-"
#: The line his corrections follow in a question asked again (`meeting_brief.corrected_question`).
MEETING_BRIEF_CORRECTED = "inferred from them, ‹he› is right."
#: The line his kept facts follow in a question (`meeting_brief.question`, with what it remembers).
MEETING_BRIEF_FACTS = "What ‹owner› told Rouh about them before, first hand, oldest first:"


def is_meeting_briefing(body: dict) -> bool:
    return says(MEETING_BRIEFING, _flat(body.get("system")))


def a_meeting_brief(body: dict) -> str:
    said = last_user_text(body)
    shaped = re.search(r"MEETINGBRIEF SHAPED (\{.*\})\s*$", said, re.M)
    if shaped:
        return shaped.group(1)
    if "MEETINGBRIEF FAIL" in said:
        return "I could not make anything of these emails."
    if "MEETINGBRIEF NOTHING" in said:
        return json.dumps({"nothing": "The emails with them are about nothing this meeting "
                                      "is likely to touch."})
    heads = re.findall(r"(?m)^=== Email \d+: (.*?), from (.*?)(?: to .*?)?, subject “(.*)”$", said)
    bodies = re.findall(r"<untrusted-content-[0-9a-f]{8} source=\"an email, from [^\"]*\">\n(.*?)\n"
                        r"</untrusted-content-[0-9a-f]{8}>", said, re.S)
    first = [(" ".join(b.split()).split(". ")[0].strip(" .") + ".") if b.strip() else ""
             for b in bodies]
    # What it remembers (`meeting_brief.remembered_for`): his facts, and earlier meetings' notes.
    told = partition(said, MEETING_BRIEF_FACTS)[2].split("\n\n", 1)[0]
    facts = [line.strip() for line in re.findall(r"(?m)^\d+\. (.+)$", told)]
    met = re.findall(r"(?m)^=== Meeting \d+: (.*?), “(.*)”$", said)
    notes = re.findall(r"<untrusted-content-[0-9a-f]{8} source=\"a meeting's notes, from the meeting "
                       r"library\">\n(.*?)\n</untrusted-content-[0-9a-f]{8}>", said, re.S)
    actions = [re.findall(r"(?m)^- (.+)$", n.split("Action items:", 1)[1]) if "Action items:" in n else []
               for n in notes]
    slack_block = re.search(r"<untrusted-content-[0-9a-f]{8} source=\"Slack messages, from the people in them\">\n"
                            r"(.*?)\n</untrusted-content-[0-9a-f]{8}>", said, re.S)
    slack = re.findall(r"(?m)^- (.*?, \d{2}:\d{2}), (.*?), ([^,:]+): (.+)$", slack_block.group(1)) if slack_block else []
    # The documents attached to the invitation (night 31, `rouh/raise_attached.py`): how many it
    # read, and the first sentence of each is a point to raise.
    papers = re.findall(r"(?m)^=== Attached document \d+: “(.*)”$", said)
    paper_bodies = re.findall(r"<untrusted-content-[0-9a-f]{8} source=\"a document attached to the invitation\">\n"
                              r"(.*?)\n</untrusted-content-[0-9a-f]{8}>", said, re.S)
    if not heads and not met and not slack and not papers:
        return json.dumps({"nothing": "There were no emails to read."})
    if heads:
        when, sender, subject = heads[0]
        standing = (f"The stand-in read {len(heads)} email{'s' if len(heads) != 1 else ''}; "
                    f"the newest, “{subject}”, is from {sender.split(' <')[0]} on {when.split(',')[0]}.")
    else:
        standing = "The stand-in read no email."
    if met:
        standing += (f" It read {len(met)} earlier meeting{'s' if len(met) != 1 else ''}; the newest, "
                     f"“{met[0][1]}”, was on {met[0][0].split(',')[0]}.")
    if slack:
        standing += (f" It read {len(slack)} Slack message{'s' if len(slack) != 1 else ''}; the newest is "
                     f"{slack[0][2]}'s in {slack[0][1]}.")
    if papers:
        standing += (f" It read {len(papers)} document{'s' if len(papers) != 1 else ''} attached to the "
                     f"invitation; the first is “{papers[0]}”.")
    if facts:
        standing = " ".join(f"Remembered: {one.rstrip('.')}." for one in facts) + " " + standing
    if says(MEETING_BRIEF_CORRECTED, said):
        told = partition(said, MEETING_BRIEF_CORRECTED)[2].split("\n\n", 1)[0]
        fixed = [line.strip() for line in re.findall(r"(?m)^\d+\. (.+)$", told)]
        standing = " ".join(f"Corrected: {one.rstrip('.')}." for one in fixed) + " " + standing
    raised = [{"point": items[0], "why": f"From the meeting “{m[1]}”, {m[0].split(',')[0]}."}
              for m, items in zip(met, actions) if items][:1]
    raised += [{"point": m[3][:200], "why": f"Said in Slack by {m[2]}, {m[0].split(',')[0]}."} for m in slack[:1]]
    raised += [{"point": " ".join(b.split("\n", 1)[-1].split())[:200],
                "why": f"From “{t}”, attached to the invitation."}
               for t, b in zip(papers, paper_bodies) if b.strip()][:1]
    raised += [{"point": line, "why": f"From “{head[2]}”, {head[0].split(',')[0]}."}
               for line, head in zip(first, heads) if line.strip(".")]
    raised = raised[:3]
    opened = [{"what": item, "owed_by": "them", "since": m[0].split(",")[0]}
              for m, items in zip(met, actions) for item in items[1:2]]
    opened += [{"what": q.strip() + "?", "owed_by": OWNER, "since": head[0].split(",")[0]}
               for body_, head in zip(bodies, heads)
               for q in re.findall(r"([^.?!\n]{8,160})\?", body_)[:1]]
    opened = opened[:4]
    return json.dumps({"standing": standing, "open": opened,
                       "they_asked": first[0] if first else "",
                       "raise": raised,
                       "careful": "The stand-in is careful of nothing in particular.",
                       "nothing": ""}, ensure_ascii=False)


# --------------------------------------------------------------------------
# Standing in for Last said in Slack before a meeting (`rouh/meeting_slack.py`).
# --------------------------------------------------------------------------
#
# Told apart by the first words of its instructions (`meeting_slack.ASK`). For
# each guest it gives a line for each of their two newest messages that hold a
# question, a promise or a date, by the message's own number, so a world sees
# its own messages come back as lines with their links. `MEETINGSLACK NOTHING`
# in any message answers with no lines for anybody; `MEETINGSLACK FAIL`
# answers with no object at all; and `MEETINGSLACK WRONG` answers with a number
# that is no message of theirs, which must come back as no line. For a meeting
# with a subject ("Words that name its subject") it keeps only messages marked
# as naming it, and gives what they named as the tie, as the rule asks
# (fr_161adc2e5ef3); `MEETINGSLACK UNTIED` gives such a line no tie, which must
# come back as no line.

MEETING_SLACK = "You read what ‹owner› and the people coming to a meeting last said to each other in Slack."
MEETING_SLACK_FILE = "meetingslack-"


def is_meeting_slack(body: dict) -> bool:
    return says(MEETING_SLACK, _flat(body.get("system")))


def a_meeting_slack(body: dict) -> str:
    said = last_user_text(body)
    if "MEETINGSLACK FAIL" in said:
        return "I could not make anything of these messages."
    has_subject = "Words that name its subject:" in said
    people = []
    for head, block in re.findall(r"(?m)^=== (.*?): \d+ messages? with " + ME + r", newest first\n(.*?)"
                                  r"</untrusted-content-[0-9a-f]{8}>", said, re.S):
        email = head.rsplit("<", 1)[-1].rstrip(">")
        lines = []
        for n, when, where, who, text in re.findall(
                r"(?m)^\[(\d+)\] (\d+ \w+ [\d:]+), (.*?), ([^,:]+): (.*)$", block):
            if "MEETINGSLACK NOTHING" in said:
                break
            named = re.search(r"\(names ([^)]*)\)", where)
            if has_subject and not named:
                continue
            if "?" in text or re.search(r"(?i)\b(will|send|sign|friday|monday|tomorrow|by)\b", text):
                n = 9999 if "MEETINGSLACK WRONG" in said else int(n)
                tie = "" if "MEETINGSLACK UNTIED" in said else (named.group(1) if named else "")
                lines.append({"said": f"{who} on {when}: {text.strip()[:140]}", "message": n, "tie": tie})
            if len(lines) >= 2:
                break
        people.append({"email": email, "lines": lines})
    return json.dumps({"people": people}, ensure_ascii=False)


# --------------------------------------------------------------------------
# Standing in for the work after a meeting (`rouh/meeting_next.py`).
# --------------------------------------------------------------------------
#
# Told apart by the first words of its instructions (`meeting_next.ASK`). It
# answers from the notes it was given, so a world sees its own meeting come
# back: each action item that names the owner is a piece of work, filed in the
# first open task whose title shares a word with it. `MEETINGNEXT NOTHING` in
# the notes answers that the meeting calls for nothing; `MEETINGNEXT FAIL`
# answers with no object at all; and a line `MEETINGNEXT SHAPED {...}` in the
# notes is the answer, word for word.

MEETING_NEXT = "You read the notes of a meeting ‹owner› just had and say what work it calls for."
MEETING_NEXT_FILE = "meetingnext-"


def is_meeting_next(body: dict) -> bool:
    return says(MEETING_NEXT, _flat(body.get("system")))


def a_meeting_next(body: dict) -> str:
    said = last_user_text(body)
    shaped = re.search(r"MEETINGNEXT SHAPED (\{.*\})\s*$", said, re.M)
    if shaped:
        return shaped.group(1)
    if "MEETINGNEXT FAIL" in said:
        return "I could not make anything of these notes."
    if "MEETINGNEXT NOTHING" in said:
        return json.dumps({"work": [], "nothing": "The meeting calls for nothing Rouh could do by itself."})
    title = (re.search(r"The meeting: “(.*?)”", said) or [None, "the meeting"])[1]
    head, found, rest = partition(said, "‹Owner›'s open tasks")
    tasks = re.findall(r"(?m)^(\d+): (.+)$", rest if found else said)
    work = []
    for line in re.findall(r"(?m)^- (.+?\(" + ME + r"[^)]*\))\s*$", said)[:3]:
        item = re.sub(r"\s*\(" + ME + r"[^)]*\)$", "", line)
        due = re.search(r"due (\d{4}-\d{2}-\d{2})", line)
        words = {w.lower() for w in re.findall(r"[A-Za-z]{5,}", item)}
        task = next((n for n, t in tasks if words & {w.lower() for w in re.findall(r"[A-Za-z]{5,}", t)}), "")
        work.append({"do": " ".join(item.split(",")[0].split()[:11]), "why": f"From “{title}”: {item}.",
                     "brief": f"The stand-in's brief. Do this for {OWNER}: {item}.", "task": task,
                     "by": due.group(1) if due else ""})
    if not work:
        return json.dumps({"work": [], "nothing": f"No action item in the notes names {OWNER}."})
    return json.dumps({"work": work, "nothing": ""}, ensure_ascii=False)


# --------------------------------------------------------------------------
# Standing in for promises read in Slack (`rouh/slack_promises.py`).
# --------------------------------------------------------------------------
#
# Told apart by the first words of its instructions (`slack_promises.SYSTEM`). It answers from
# the messages it was given, so a world sees its own Slack come back: a NEW message that says
# "I'll" or "I will" and a day (today, tomorrow, a weekday, or a date written 2026-10-20) is a
# promise, made to the owner unless the owner wrote it; one that says "here you go", "done", "attached",
# "sent" or "signed" shows the first OPEN promise kept, and a promise made earlier in the same
# new messages. A line `PROMISES SHAPED {...}` in a message is the answer, word for word.

SLACK_PROMISES = "You read new Slack messages for ‹owner›'s assistant, Rouh, and find promises"
SLACK_PROMISES_FILE = "promises-"
_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_KEPT_WORDS = re.compile(r"\b(here you go|done|attached|sent|signed)\b", re.I)


def is_slack_promises(body: dict) -> bool:
    return says(SLACK_PROMISES, _flat(body.get("system")))


def a_slack_promises(body: dict) -> str:
    import datetime as dt

    said = last_user_text(body)
    shaped = re.search(r"PROMISES SHAPED (\{.*\})\s*$", said, re.M)
    if shaped:
        return shaped.group(1)
    line = re.compile(r"^\[([\d.]+)\] \w{3} (\d{4}-\d{2}-\d{2}) \d{2}:\d{2} (.+?)( \(" + ME + r"\))?"
                      r"(?: \(reply in the thread of \[[\d.]+\]\))?: (.*)$")
    new = said.split("NEW messages:", 1)[-1].split("Find promises in the NEW", 1)[0]
    open_ = re.findall(r"(?m)^(P\d+)\. ", said.split("NEW messages:", 1)[0])
    promises, kept = [], []
    for raw in new.splitlines():
        m = line.match(raw.strip())
        if not m:
            continue
        ts, day, who, theirs, text = m.groups()
        found = re.search(r"\bI(?:'ll| will) (.+?)(?: (?:by|on|before) )?\b(today|tomorrow|"
                          + "|".join(_WEEKDAYS) + r"|\d{4}-\d{2}-\d{2})\b", text, re.I)
        if not found:
            if _KEPT_WORDS.search(text):
                if promises and not promises[-1]["kept_ts"]:
                    promises[-1]["kept_ts"] = ts
                elif open_ and not kept:
                    kept.append({"promise": open_[0], "ts": ts, "why": "The stand-in read it as done."})
            continue
        what, when = found.group(1).strip().rstrip(",."), found.group(2).lower()
        what = re.sub(r"\s+(by|on|before)$", "", what)
        said_on = dt.date.fromisoformat(day)
        if when == "today":
            due = said_on
        elif when == "tomorrow":
            due = said_on + dt.timedelta(days=1)
        elif when in _WEEKDAYS:
            ahead = (_WEEKDAYS.index(when) - said_on.weekday()) % 7 or 7
            due = said_on + dt.timedelta(days=ahead)
        else:
            due = dt.date.fromisoformat(when)
        mine = bool(theirs)
        first = who.split()[0]
        promises.append({"ts": ts, "to": "Sam" if mine else OWNER, "to_owner": not mine,
                         "what": what, "due": due.isoformat(), "due_said": found.group(0).split(what)[-1].strip(),
                         "kept_ts": "",
                         "nudge": "" if mine else f"Hi {first}, a friendly check on what you said you would "
                                                  f"{what.replace('you', OWNER)}. Any news?"})
    return json.dumps({"promises": promises, "kept": kept}, ensure_ascii=False)


# --------------------------------------------------------------------------
# Standing in for the decisions read in a linked Slack channel (`rouh/slack_tasks.py`).
# --------------------------------------------------------------------------
#
# Told apart by the first words of its instructions (`slack_tasks.SYSTEM`). A NEW message that
# says "agreed", "decided", "final", "let's go with" or "we go with" settles a decision: who
# wrote it decided (the owner's name for their own), and the decision is the rest of the message after the
# word, as a sentence. Anything else is discussion. A line `DECISIONS SHAPED {...}` in a message
# is the answer, word for word.

SLACK_DECISIONS = "You read new messages in a Slack channel for ‹owner›'s assistant, Rouh, and find the decisions"
SLACK_DECISIONS_FILE = "decisions-"
_DECIDED = re.compile(r"\b(?:agreed|decided|final|let's go with|lets go with|we go with)\b[:,.!\s-]*(.*)", re.I)


def is_slack_decisions(body: dict) -> bool:
    return says(SLACK_DECISIONS, _flat(body.get("system")))


def a_slack_decisions(body: dict) -> str:
    said = last_user_text(body)
    shaped = re.search(r"DECISIONS SHAPED (\{.*\})\s*$", said, re.M)
    if shaped:
        return shaped.group(1)
    line = re.compile(r"^\[([\d.]+)\] \w{3} \d{4}-\d{2}-\d{2} \d{2}:\d{2} (.+?)( \(" + ME + r"\))?"
                      r"(?: \(reply in the thread of \[[\d.]+\]\))?: (.*)$")
    new = said.split("NEW messages:", 1)[-1].split("Find the decisions made in the NEW", 1)[0]
    decisions = []
    for raw in new.splitlines():
        m = line.match(raw.strip())
        if not m:
            continue
        ts, who, theirs, text = m.groups()
        found = _DECIDED.search(text)
        if not found or not found.group(1).strip():
            continue
        what = found.group(1).strip().rstrip(".")
        decisions.append({"ts": ts, "who": OWNER if theirs else who,
                          "decision": what[:1].upper() + what[1:] + "."})
    return json.dumps({"decisions": decisions}, ensure_ascii=False)


# --------------------------------------------------------------------------
# Standing in for a question already answered in a chat (`rouh/answered_in_chat.py`).
# --------------------------------------------------------------------------
#
# Told apart by the first words of its instructions (`answered_in_chat.ASK`).
# It answers from what it was given, so a world sees its own words come back:
# of the owner's messages that name an offered answer, or share two words of five
# letters or more with the question's title and question, and say a decision ("go with", "agree",
# "approve", "let's", "I want", "I'd like", "pick", "choose", "yes"), one that
# names an offered answer (all of its label's words) answers it with that
# answer, else the newest answers it in his own words, quoting the sentence
# that says it. `ANSWERED FAIL` in a message answers with
# no object at all, and a line `ANSWERED SHAPED {...}` in a message is the
# answer, word for word.

ANSWERED = "You check whether ‹owner› already answered a question that is waiting for ‹him› in Rouh's Decisions."
ANSWERED_FILE = "answered-"
_DECIDING = re.compile(r"\b(go with|agree|approve|let's|lets|i want|i'd like|pick|choose|yes)\b", re.I)


def is_answered(body: dict) -> bool:
    return says(ANSWERED, _flat(body.get("system")))


def an_answered(body: dict) -> str:
    said = last_user_text(body)
    shaped = re.search(r"ANSWERED SHAPED (\{.*\})\s*$", said, re.M)
    if shaped:
        return shaped.group(1).rstrip("”")
    if "ANSWERED FAIL" in said:
        return "I could not tell."
    head, _, rest = partition(said, "What ‹owner› said in ‹his› chats since, oldest first:")
    asked = {w.lower() for w in re.findall(r"[A-Za-z]{5,}", " ".join(
        re.findall(r"(?m)^(?:Title|Question): (.+)$", head)))}
    options = re.findall(r'(?m)^- id "([^"]+)": (.+?)(?: - .*)?$', head)
    def named(words):
        lowered = words.lower()
        return next((oid for oid, label in options
                     if re.findall(r"[A-Za-z0-9]{3,}", label)
                     and all(w.lower() in lowered for w in re.findall(r"[A-Za-z0-9]{3,}", label))), "")
    found = []
    for n, words in re.findall(r"(?ms)^\[(\d+)\].*?^" + ME + r" said: “(.*?)”\s*$", rest):
        if _DECIDING.search(words) and (
                named(words) or len(asked & {w.lower() for w in re.findall(r"[A-Za-z]{5,}", words)}) >= 2):
            found.append((int(n), words))
    if not found:
        return json.dumps({"answered": False, "message": 0, "quote": "", "option": "", "answer": "",
                           "why": "None of these messages gives an answer to this question."})
    n, words = next(((n, w) for n, w in reversed(found) if named(w)), found[-1])
    option = named(words)
    sentence = next((x.strip() for x in re.split(r"(?<=[.!?])\s+", words) if _DECIDING.search(x)), words)[:300]
    return json.dumps({"answered": True, "message": n, "quote": sentence, "option": option,
                       "answer": sentence, "why": "The stand-in reads a decision on this in that message."},
                      ensure_ascii=False)


# --------------------------------------------------------------------------
# Standing in for the gate in front of the decisions (`rouh/decision_gate.py`).
# --------------------------------------------------------------------------
#
# Told apart by the first words of its instructions (`decision_gate.SYSTEM`).
# It lets a question through when its risk is money, sending, publishing or
# irreversible, and keeps every other one from him, with Rouh's
# recommendation as its own. `GATE ASK` or `GATE CLEAR` anywhere
# in what it is given decides it outright, and `GATE FAIL` answers with no
# object at all.

GATE = "You are the gate in front of ‹owner›'s decisions list in Rouh, ‹his› assistant."
GATE_FILE = "gate-"


def is_gate(body: dict) -> bool:
    return says(GATE, _flat(body.get("system")))


def a_gate(body: dict) -> str:
    said = last_user_text(body)
    if "GATE FAIL" in said:
        return "I could not tell."
    risky = re.search(r"(?m)^Risk: (money|sending|publishing|irreversible)\b", said)
    asks = "GATE ASK" in said or (risky is not None and "GATE CLEAR" not in said)
    rec = re.search(r"(?m)^Rouh's recommendation: (.+?)(?: - .*)?$", said)
    return json.dumps({
        "verdict": "ask" if asks else "clear",
        "work": "stopped" if asks else "finished",
        "reason": ("The stand-in lets through what spends, sends, publishes or cannot be undone."
                   if asks else "The stand-in keeps back what can be changed later."),
        "recommendation": "" if asks else (rec.group(1) if rec else "Rouh goes on as it judges best.")},
        ensure_ascii=False)


# --------------------------------------------------------------------------
# Standing in for reading a job's request_from_rouh (`rouh/job_gateway.py`).
# --------------------------------------------------------------------------
#
# Told apart by the first words of its instructions (`job_gateway.ASK_SYSTEM`).
# A test says in the job's own words what it should decide: `NEEDS OWNER` makes
# it one question for the owner, `HAS TOOL <name>` names a tool the job has, and
# anything else cannot be had. The gap is the words after `GAP `, or the need's
# first words, so two jobs asking the same are one gap.

JOB_REQUEST = "You read one request a background job sent Rouh"
JOB_REQUEST_FILE = "job-request-"


def is_job_request(body: dict) -> bool:
    return says(JOB_REQUEST, _flat(body.get("system")))


def a_job_request(body: dict) -> str:
    said = last_user_text(body)
    need = (re.search(r"(?m)^Need: (.+)$", said) or [None, ""])[1]
    gap = re.search(r"GAP ([a-z0-9-]+)", said)
    gap = gap.group(1) if gap else "-".join(re.findall(r"[a-z0-9]+", need.lower())[:4])
    tool = re.search(r"HAS TOOL ([a-z_]+)", said)
    if tool:
        return json.dumps({"outcome": "tool", "tool": tool.group(1), "gap": gap,
                           "how": "Call it with what the work needs."})
    if "NEEDS OWNER" in said:
        # `HANDS ON` makes it something the owner does with their own hands: an action.
        hands = "HANDS ON" in said
        what = need.split(' NEEDS')[0].split(' HANDS')[0].rstrip('.')[:160]
        return json.dumps({"outcome": "owner", "gap": gap, "hands_on": hands,
                           "question": what + "." if hands else f"Can you give the job this: {what}?"})
    return json.dumps({"outcome": "cannot", "gap": gap,
                       "reason": "The stand-in finds nothing Rouh could give for it."})


# --------------------------------------------------------------------------
# Standing in for reading what waits on the person, and for a question asked on
# an action's page (`rouh/actions.py`).
# --------------------------------------------------------------------------
#
# Told apart by the first words of their instructions (`actions.READ_SYSTEM`,
# `actions.ASK_SYSTEM`). The reader calls it an action when its words say
# something hands-on (install, sign in, run, curl, on your phone, on your Mac),
# and writes its page from them by plain rules: what it asks as the one line,
# every web address in it a step that opens it, a command in backticks a step to
# run, and the story from the lines it was given. The asker answers from the
# page it was given, and says so.

ACTION_READ = "You read one thing that waits on a person, the owner of a personal assistant"
ACTION_READ_FILE = "action-read-"
ACTION_ASK = "You are Rouh, a personal assistant. The person you work for is looking at one ACTION"
ACTION_ASK_FILE = "action-ask-"
_HANDS = re.compile(r"\b(install|approve .{0,30} again|sign in|signs? .{0,20} in|log in|run (one|a|the)|curl|on your phone|"
                    r"on your mac|authori[sz]e)\b", re.I)


def is_action_read(body: dict) -> bool:
    return says(ACTION_READ, _flat(body.get("system")))


def is_action_ask(body: dict) -> bool:
    return says(ACTION_ASK, _flat(body.get("system")))


def an_action_read(body: dict) -> str:
    said = last_user_text(body)
    asks = (re.search(r"(?m)^What it asks: (.+)$", said) or [None, ""])[1].strip()
    title = (re.search(r"(?m)^Its title: (.+)$", said) or [None, ""])[1].strip()
    if not _HANDS.search(asks + " " + title):
        return json.dumps({"kind": "decision"})
    steps = []
    for url in dict.fromkeys(re.findall(r"https?://[^\s)\"'<>`]+", said)):
        steps.append({"text": f"Open {url.rstrip('.,')} and follow it.", "href": url.rstrip(".,"),
                      "link": "Open the page"})
    for cmd in dict.fromkeys(re.findall(r"`([^`]{4,300})`", said)):
        steps.append({"text": "Run this in Terminal on your Mac.", "command": cmd})
    if not steps:
        steps = [{"text": asks or title}]
    lines = [ln for ln in said.splitlines() if ln.strip()]
    asked = next((ln for ln in lines if ln.startswith("It was asked on")), "")
    need = next((ln[len("What it needed: "):] for ln in lines if ln.startswith("What it needed: ")), "")
    job = next((ln for ln in lines if ln.startswith("The job: ")), "")
    story = "\n\n".join(x for x in (
        f"A job needed this from you: {need.split('. ')[0][:200]}." if need else f"Rouh asked you: {asks}",
        job.replace("The job: ", "It was for the job ").split(". Started")[0] + "." if job else "",
        "Only you can do it, because it needs your own hands and your own account.") if x)
    do = asks if re.match(r"^[A-Z][a-z]+ ", asks) and not asks.endswith("?") else (title or asks)
    return json.dumps({"kind": "action", "do": do[:200], "minutes": 2, "steps": steps[:6],
                       "after": "The work that asked carries on, and checks it worked.",
                       "wait": "The work that asked stays stopped until you do it.",
                       "check": "Rouh runs the same check after you press Done, and tells you if it did not work.",
                       "story": story})


def an_action_answer(body: dict) -> str:
    said = last_user_text(body)
    q = (re.search(r"(?m)^Their question: (.+)$", said) or [None, ""])[1].strip()
    return (f"You asked: {q} From what the page says, you need nothing but your own account and "
            "the steps above, and it takes about two minutes. If a step does not answer as it "
            "says, press Not doing this or Do it another way and say what happened.")


# --------------------------------------------------------------------------
# Standing in for checking a page's sources (`rouh/source_check.py`).
# --------------------------------------------------------------------------
#
# Told apart by the first words of its instructions (`source_check.SYSTEM`).
# It reads each source the way the real one is told to, by plain word
# counting: a quotation in the page that is not in the passages, or a figure
# that is not, makes it "missing"; the words "SAYS OTHERWISE" in the passages
# make it "otherwise"; at least two thirds of the page's longer words in the
# passages make it "holds", at least a third "partly", fewer "missing". The
# quote is the passage's sentence that shares most words with the page.

SOURCES = "You check the sources of a research page that ‹owner›'s assistant wrote for ‹him›."
SOURCES_FILE = "sources-"


def is_sources(body: dict) -> bool:
    return says(SOURCES, _flat(body.get("system")))


def a_sources(body: dict) -> str:
    said = last_user_text(body)
    out = []
    for block in re.split(r"(?m)^(?=Source \[\d+\]:)", said):
        head = re.match(r"Source \[(\d+)\]:", block)
        if not head:
            continue
        claims = " ".join(re.findall(r"(?m)^- “(.*)”$", block))
        got = re.search(r"Passages from the source:\n“(.*)”\s*$", block, re.S)
        passage = got.group(1) if got else ""
        low = passage.lower()
        words = {w for w in re.findall(r"[a-z]{6,}", claims.lower())}
        numbers = set(re.findall(r"\d[\d.,]*\d|\d", claims))
        quoted = re.findall(r"[\"“]([^\"”]{8,})[\"”]", claims)
        share = (sum(1 for w in words if w in low) / len(words)) if words else 0
        if "SAYS OTHERWISE" in passage:
            verdict, why = "otherwise", "The source says the opposite of what the page says."
        elif any(q.lower() not in low for q in quoted) or any(n not in passage for n in numbers):
            verdict, why = "missing", "The quotation or figure the page gives is not in the source."
        elif share >= 2 / 3:
            verdict, why = "holds", "The source says what the page says."
        elif share >= 1 / 3:
            verdict, why = "partly", "The source says part of it, not all the page claims."
        else:
            verdict, why = "missing", "The source does not say what the page says."
        sentences = [x.strip(" …") for x in re.split(r"(?<=[.!?])\s+", passage) if x.strip(" …")]
        best = max(sentences, key=lambda x: sum(1 for w in words if w in x.lower()), default="")
        quote = " ".join(best.split()[:40]) if verdict != "missing" or best else ""
        out.append({"n": int(head.group(1)), "verdict": verdict, "quote": quote, "why": why})
    return json.dumps({"sources": out}, ensure_ascii=False)


# --------------------------------------------------------------------------
# Standing in for a question on a gene's card (`rouh/gene_questions.py`).
# --------------------------------------------------------------------------
#
# Told apart by the first words of its instructions (`gene_questions.SYSTEM`).
# It answers only out of the record it was sent, the way the real one is told
# to: the gene's name and what its original gene says it does, what was seen
# in its test install, and the mutation check; and for a follow-up, how many
# turns came before, so a test can see the topic was carried. Asked about
# something the record has no word for, it says the record does not say.

# --------------------------------------------------------------------------
# Standing in for the gene log's three models (`rouh/genelog.py`, `rouh/geneuse.py`,
# `rouh/genepool.py`).
# --------------------------------------------------------------------------
#
# Each is told apart by the first words of its system prompt and answers with
# the JSON its caller reads, worked out from what arrived, so a test sees the
# request really carried the genes and changes it was given:
#
# * the gene writer puts a change whose subject says NEW GENE to a new gene
#   named from the subject, one that says SUB GENE to a sub-gene of the first
#   gene it names, one that names a gene (its key or name) to that gene, one
#   about tests or instructions to no gene, and the rest to Rouh itself;
# * the evaluation scores each gene by its share of the person's uses;
# * the matcher picks the catalogue's families in the order given, says why
#   from the person's own most used gene, and proposes a fork for the first
#   when the person's words in the request say MAKE IT DIFFERENT.

GENE_WRITER = "You are Rouh's gene writer."
GENE_EVAL = "You evaluate how useful some of the genes of a person's AI assistant"
GENE_MATCH = "You match genes from the Gene Pool to one person"
GENE_LOG_FILE = "gene-log-"
#: A Rouh giving itself its second name (`rouh/birth.py`): answered from the facts it was given, so
#: a test sees they arrived; facts that say BAD SECOND NAME get a name the rules refuse.
SECOND_NAME = "giving yourself a second name"


def is_gene_log(body: dict) -> bool:
    said = _flat(body.get("system"))
    return GENE_WRITER in said or GENE_EVAL in said or GENE_MATCH in said or SECOND_NAME in said


def a_gene_log_answer(body: dict) -> str:
    said = _flat(body.get("system"))
    text = last_user_text(body)
    if SECOND_NAME in said:
        if "BAD SECOND NAME" in text:
            return json.dumps({"name": "Spirit Chief", "why": "It wanted a grand name."})
        days = re.search(r"(\d+) days ago", text)
        tasks = re.search(r"Tasks: (\d+)", text)
        return json.dumps({"name": "Keeper of Steps",
                           "why": f"In {days.group(1) if days else 'its'} days it kept "
                                  f"{tasks.group(1) if tasks else 'many'} tasks moving, one small step at a time."})
    if GENE_WRITER in said:
        genes = []
        for line in text.split("# The changes", 1)[0].splitlines():
            bits = [b.strip() for b in line.split("|")]
            if len(bits) >= 2 and re.fullmatch(r"[a-z][a-z0-9.-]*", bits[0]):
                genes.append((bits[0], bits[1].lower()))
        out = []
        for sha, subject in re.findall(r"## commit ([0-9a-f]+)\nsubject: (.*)", text):
            low = subject.lower()
            named = next((k for k, n in genes if k != "rouh" and (re.search(r"\b" + re.escape(k) + r"\b", low)
                                                                    or (n and n in low))), None)
            if "new gene" in low:
                name = re.sub(r"(?i)new gene:?", "", subject.split(":", 1)[-1]).strip() or "A new gene"
                out.append({"commit": sha, "gene": None, "contract_changed": False, "sub": None,
                            "new": {"name": name[:40], "what": f"It does what {subject!r} says.",
                                    "where": "In a chat", "tables": [], "accounts": [], "jobs": [],
                                    "remove": "Revert its commit."}, "why": "it made something new"})
            elif "sub gene" in low and named:
                out.append({"commit": sha, "gene": named, "contract_changed": True, "new": None,
                            "sub": {"name": subject.split(":", 1)[-1].strip()[:40], "what": f"Also: {subject}",
                                    "where": "Where it was, and in the brief", "tables": ["a_new_table"],
                                    "accounts": [], "jobs": [], "remove": "Revert its commit."},
                            "why": "it changed what the gene touches"})
            elif named:
                out.append({"commit": sha, "gene": named, "contract_changed": False, "new": None,
                            "sub": None, "why": f"its subject names {named}"})
            elif re.search(r"\b(tests?|agents\.md|instructions?)\b", low):
                out.append({"commit": sha, "gene": None, "contract_changed": False, "new": None,
                            "sub": None, "why": "tests and instructions are no gene"})
            else:
                out.append({"commit": sha, "gene": "rouh", "contract_changed": False, "new": None,
                            "sub": None, "why": "Rouh's own machinery"})
        return json.dumps(out)
    if GENE_EVAL in said:
        try:
            genes = json.loads(text)
        except ValueError:
            genes = []
        out = []
        for g in genes if isinstance(genes, list) else []:
            share = float(g.get("share_of_uses") or 0)
            out.append({"gene": g.get("gene"), "score": max(1, min(5, 1 + round(share * 8))),
                        "replaced": "looking it up by hand" if share else "",
                        "minutes": int(share * 300), "reason": f"It had {share:.0%} of the person's uses "
                                                                f"and was used on {g.get('days_used_of_30', 0)} days."})
        return json.dumps(out)
    m = re.search(r"# The Pool's genes\n(.*)", text, re.S)
    families = re.findall(r"^FAMILY (\S+) \| ([^|\n]+)", m.group(1) if m else "", re.M)
    nodes = re.findall(r"^  NODE (\S+) \| family (\S+) \|", m.group(1) if m else "", re.M)
    top = re.search(r"most used: ([^\n]+)", text)
    picks = []
    for i, (fid, name) in enumerate(families[:3]):
        node = next((n for n, f in nodes if f == fid), "")
        pick = {"family": fid, "node": node, "why": f"You use {top.group(1).split(',')[0].strip() if top else 'Rouh'} "
                                                    f"most, and {name.strip()} works beside it.", "fit": 5 - i}
        if i == 0 and "MAKE IT DIFFERENT" in text:
            pick["fork"] = "Make it send its summary to Telegram instead of email."
        picks.append(pick)
    return json.dumps(picks)



# --------------------------------------------------------------------------
# Standing in for the narration of a page (`rouh/page_listen.py`).
# --------------------------------------------------------------------------
#
# Told apart by the first words of its instructions (`page_listen.SYSTEM`). It
# answers out of the elements it was sent, so a world hears its own page come
# back: an opening that names the page and its sections, then a part for every
# heading and the elements under it, two at a time. `LISTENFAIL` on the page
# answers with no parts at all. It is written the way a real model writes a
# long one, a part at a time with a pause between them (`LISTEN_PART_S`), so a
# world shows the first part being said while the rest is still to come.

PAGE_LISTEN = "You turn a page into a narration that walks a listener through it"
PAGE_LISTEN_FILE = "listen-"
#: How long the stand-in waits before the first part, and between parts.
LISTEN_PART_S = 1.2


#: Picture descriptions (`imaging.with_conversation`): the description a
#: picture is drawn from, written from the chat before it.
PICTURE_PROMPT = "You write the description a picture is drawn from."
PICTURE_PROMPT_FILE = "picture-prompt-"


def is_picture_prompt(body: dict) -> bool:
    return says(PICTURE_PROMPT, _flat(body.get("system")))


def a_picture_prompt(body: dict) -> str:
    """The request, with what the conversation said about it written in, as a
    model that only copies does: every line of the person's and every earlier
    picture's description, so a picture drawn from it is seen to carry them.
    `PICTUREPROMPTFAIL` in the request is a model that fails."""
    said = last_user_text(body)
    head, _, rest = said.partition("The person now asks for a picture with these words:\n")
    request = rest.split("\n\nWrite the description", 1)[0].strip()
    if "PICTUREPROMPTFAIL" in request:
        raise ValueError("PICTUREPROMPTFAIL")
    earlier = []
    for line in head.splitlines():
        if line.startswith("Person: "):
            earlier.append(line.removeprefix("Person: ").strip())
        found = re.search(r"\[A picture Rouh drew, from the description: (.*?)\]", line)
        if found:
            earlier.append(found.group(1).strip())
    if not earlier:
        return request
    return f"{request}. As settled earlier in the conversation: " + " | ".join(earlier)


def is_page_listen(body: dict) -> bool:
    return says(PAGE_LISTEN, _flat(body.get("system")))


def a_narration(body: dict) -> str:
    said = last_user_text(body)
    if "LISTENFAIL" in said:
        return json.dumps({"parts": []})
    rows = [(int(n), kind, text.strip()) for n, kind, text in
            re.findall(r"(?m)^\[(\d+)\] (h[1-6]|\w+)[^:]*: (.*)$", said)]
    heads = [r for r in rows if re.fullmatch(r"h[2-4]|summary", r[1])]
    title = next((r for r in rows if r[1] == "h1"), rows[0] if rows else None)
    parts = []
    if title:
        names = ", ".join(h[2][:40] for h in heads[:4])
        parts.append({"say": f"This page is about {title[2][:80]}. It has {len(heads)} sections"
                             + (f": {names}" if names else "") + ". Let's go through them.",
                      "at": [title[0]]})
    group: list = []
    for row in rows:
        if title and row[0] == title[0]:
            continue
        if row in heads or len(group) == 2:
            if group:
                parts.append(group)
            group = []
        group.append(row)
    if group:
        parts.append(group)
    out = [p if isinstance(p, dict) else
           {"say": " ".join((("Next, " + r[2][:60] + ".") if r in heads else
                             (re.split(r"(?<=[.!?])\s", r[2])[0][:160])) for r in p),
            "at": [r[0] for r in p]} for p in parts]
    return json.dumps({"parts": out}, ensure_ascii=False)


# --------------------------------------------------------------------------
# Standing in for Define over a passage on a page (`rouh/definitions.py`).
# --------------------------------------------------------------------------
#
# Told apart by the first words of its instructions (`definitions.SYSTEM`). It
# answers out of what arrived, so the screen shows what was sent: the passage,
# the first words of the paragraph it is in, and how many words of the page
# went with it. It takes `DEFINE_WAIT_S` seconds, as a real model does, so the
# tooltip's waiting can be seen.

DEFINE = "A reader selected a passage on a page and pressed Define."
DEFINE_FILE = "define-"
DEFINE_WAIT_S = 1.5


def is_defining(body: dict) -> bool:
    return says(DEFINE, _flat(body.get("system")))


def a_definition(body: dict) -> str:
    said = last_user_text(body)
    passage = re.search(r"<passage>\n(.*?)\n</passage>", said, re.S)
    paragraph = re.search(r"<paragraph>\n(.*?)\n</paragraph>", said, re.S)
    page = re.search(r"<page>\n(.*?)\n</page>", said, re.S)
    words = (paragraph.group(1) if paragraph else "").split()
    return (f"Stand-in definition of \u201c{passage.group(1) if passage else ''}\u201d as this page "
            f"uses it, read with the paragraph that begins \u201c{' '.join(words[:8])}\u201d and "
            f"{len((page.group(1) if page else '').split())} words of the page.")


GENE_ASK = "You answer ‹owner›'s questions about one gene of ‹his› assistant Rouh"
GENE_ASK_FILE = "gene-question-"


def is_gene_question(body: dict) -> bool:
    return says(GENE_ASK, _flat(body.get("system")))


def a_gene_answer(body: dict) -> str:
    messages = body.get("messages") or []
    first = messages[0].get("content") if messages else ""
    record = first[0].get("text") if isinstance(first, list) and first else str(first or "")
    question = last_user_text(body).strip()
    if isinstance(first, list) and len(first) > 1 and len(messages) == 1:
        question = first[-1].get("text") or question
    card = re.search(r"# The gene's card\n+(\{.*?\n\})", record, re.S)
    original = re.search(r"# Original gene\n+(\{.*?\n\})", record, re.S)
    check = re.search(r"# Mutation check\n+(\{.*?\n\})", record, re.S)
    try:
        name = json.loads(card.group(1)).get("name") if card else "this gene"
    except ValueError:
        name = "this gene"
    try:
        does = json.loads(original.group(1)).get("does") if original else ""
    except ValueError:
        does = ""
    try:
        verdict = json.loads(check.group(1)).get("said") if check else ""
    except ValueError:
        verdict = ""
    earlier = sum(1 for m in messages if m.get("role") == "assistant")
    lead = f"(follow-up {earlier + 1} in this topic) " if earlier else ""
    if re.search(r"\b(price|cost in euros|weather)\b", question, re.I):
        return lead + f"The record of {name} does not say that, so I cannot tell you."
    return (lead + f"From the record of {name}: the original gene says it {does[:300] or 'has no description'}. "
            + (f"The mutation check says: {verdict[:300]} " if verdict else "")
            + f"You asked: \u201c{question[:200]}\u201d.")


# --------------------------------------------------------------------------
# Standing in for reading which profile a meeting guest is
# (`meeting_people.read_with_model`).
# --------------------------------------------------------------------------
#
# Told apart by the first words of its instructions (`meeting_people.
# WORDS_SYSTEM`). It reads the owner's words against the first guest's
# candidates the way the real one is told to: words that point at a capital
# letter pick the profile whose headline has that letter where the others
# have it small; "none" or "neither" says none of them; a word in exactly one
# profile picks that one; anything else asks back which one, naming them. A
# line `PICKWORDS SHAPED {...}` in his words is the answer, word for word.

# Automatic recall's second reader (`rouh/synapse/autorecall.py`, `ask`): the same reading as the stand-in
# for OpenAI gives (`fake_openai.recall_pick`), so the two companies agree unless a test says otherwise.
RECALL_PICK = "You read one message ‹owner› sent to Rouh, ‹his› assistant"
RECALL_PICK_FILE = "recallpick-"
#: `HAIKUSLOW` in the message makes this reader take `RECALL_SLOW_S` seconds, as `PICKSLOW` makes OpenAI's take
#: three, so both readers can be slower than the 2 s they were once cut off at.
RECALL_SLOW = "HAIKUSLOW"
RECALL_SLOW_S = 4.0


def is_recall_pick(body: dict) -> bool:
    return says(RECALL_PICK, _flat(body.get("system")))


def a_recall_pick(body: dict) -> str:
    from . import fake_openai

    system = body.get("system")
    lines = system if isinstance(system, str) else "\n".join(
        b.get("text") or "" for b in system or [] if isinstance(b, dict))
    content = (body.get("messages") or [{}])[-1].get("content")
    words = content if isinstance(content, str) else "\n".join(
        b.get("text") or "" for b in content or [] if isinstance(b, dict))
    return json.dumps(fake_openai.recall_pick(lines, words))


MEETING_PICK = "You read ‹owner›'s written answer to a question Rouh asked ‹him›: which LinkedIn"
MEETING_PICK_FILE = "meetingpick-"


def is_meeting_pick(body: dict) -> bool:
    return says(MEETING_PICK, _flat(body.get("system")))


def a_meeting_pick(body: dict) -> str:
    said = last_user_text(body)
    head, found, rest = partition(said, "‹Owner›'s answer, in ‹his› own words:")
    words = (rest if found else said).strip()
    shaped = re.search(r"PICKWORDS SHAPED (\{.*\})\s*$", words, re.M)
    if shaped:
        return shaped.group(1)
    first = said.split("Guest 2:", 1)[0]
    lines = re.findall(r"(?m)^Profile (\d+): (.+)$", first)
    if re.search(r"\b(none|neither|nobody)\b", words, re.I):
        return json.dumps({"picks": [], "none": [1], "ask": ""})
    pick = 0
    if re.search(r"capital", words, re.I):
        heads = [(int(n), (re.search(r"headline: ([^|]+)", line) or [None, ""])[1].split())
                 for n, line in lines]
        for n, head in heads:
            others = [h for m, h in heads if m != n]
            if any(len(h) == len(head) and any(a != b and a.lower() == b.lower() and a[:1].isupper()
                                               for a, b in zip(head, h)) for h in others):
                pick = n
                break
    else:
        found = [int(n) for n, line in lines
                 if any(len(w) > 3 and w in line for w in re.findall(r"[\w-]+", words))]
        pick = found[0] if len(found) == 1 else 0
    if pick:
        return json.dumps({"picks": [{"guest": 1, "profile": pick}], "none": [], "ask": ""})
    return json.dumps({"picks": [], "none": [], "ask": "Which one do you mean: " + " or ".join(
        f"profile {n}" for n, _ in lines) + "? They read the same to me."})


# --------------------------------------------------------------------------
# Standing in for the Control Room's naming pass (`rouh/controlroom.py`).
# --------------------------------------------------------------------------
#
# Told apart by the first words of its instructions (`controlroom.SYSTEM`). It
# answers from the cards it was given, so a world sees its own subjects come
# back: a topic card is named "<its subject> (stand-in)", or keeps the name it
# had; a card with no side is put on "work"; every card gets a headline that
# says it is the stand-in's and its number of tasks as its one key number. A
# line `CLUSTERS SHAPED {...}` anywhere in what it was given is the answer,
# word for word.

CLUSTER_NAMING = "You name the cards on the Control Room's map of what ‹owner› is working on."
CLUSTER_FILE = "clusters-"


def is_cluster_naming(body: dict) -> bool:
    return says(CLUSTER_NAMING, _flat(body.get("system")))


def a_cluster_naming(body: dict) -> str:
    said = last_user_text(body)
    shaped = re.search(r"CLUSTERS SHAPED (\{.*\})\s*$", said, re.M)
    if shaped:
        return shaped.group(1)
    try:
        asked = json.loads(said[said.index("{"):])
    except ValueError:
        return json.dumps({"cards": []})
    out = []
    for card in asked.get("cards") or []:
        tasks = card.get("tasks") or []
        subject = str(card.get("subject") or "").split(": ", 1)[-1]
        name = card.get("name_it_had") or f"{subject} (stand-in)"
        got = {"key": card.get("key"), "headline": f"Stand-in headline for {subject}",
               "numbers": [{"n": str(len(tasks)), "l": "tasks in it"}] if tasks else []}
        if card.get("kind") == "topic":
            got["name"] = name
        if card.get("side") == "unknown":
            got["side"] = "work"
        out.append(got)
    return json.dumps({"cards": out}, ensure_ascii=False)


REVISING = "You rewrite one step of a plan"
REVISE_FILE = "revise-"


def is_revising(body: dict) -> bool:
    return REVISING in _flat(body.get("system"))


def a_revision(body: dict) -> str:
    said = last_user_text(body)
    stands, _, ask = said.partition("What the person wants changed, in their words:")
    ask = " ".join(ask.split())
    found = re.search(r"\{.*\}", stands, re.S)
    try:
        step = json.loads(found.group(0)) if found else {}
    except ValueError:
        step = {}
    renamed = re.search(r"TITLE:\s*(.+?)(?:\.|$)", ask)
    if renamed:
        step["title"] = renamed.group(1).strip()
        ask = (ask[:renamed.start()] + ask[renamed.end():]).strip()
    if ask:
        step["how"] = ("As you asked: " + ask.rstrip(".") + ". "
                       + (step.get("how") or "")).strip()
    return json.dumps(step, ensure_ascii=False)


# --------------------------------------------------------------------------
# Standing in for the model that splits a goal's plan into streams
# (`goals.split`).
# --------------------------------------------------------------------------
#
# Told apart the same way, and answered out of the steps that arrived, a line
# each as `id | who | title`: a stream ends at each step that is not Rouh's,
# and is named for the step it ends at. "NOSPLIT" anywhere in the plan answers
# with words instead, so a test sees the guess taken in its place.
#
# With what the person asked (`goals.SPLIT_ASK`), it is the streams as they
# are now, changed as asked in two words it understands: "REVERSE" turns the
# order of the streams around, and "ONE" puts every step in one stream
# called Everything. Anything else hands them back as they were.

SPLITTING = "You split the steps of a plan into streams"
SPLIT_FILE = "split-"


def is_splitting(body: dict) -> bool:
    return SPLITTING in _flat(body.get("system"))


# --------------------------------------------------------------------------
# Standing in for the three questions the morning brief asks (`morning_brief.py`).
# --------------------------------------------------------------------------
#
# Told apart by the first words of their system prompts. The world news is
# answered by picking the last three stories of the feed, most significant
# last one first, so a test can see on screen that a pick was made rather than
# the feed's own first three shown. The AI news is answered out of the
# transcripts that arrived: an item per video, its headline "Video n:" and the
# first words said in it, and a video split in two when there are too few to
# make three items. BRIEFFAIL anywhere in a transcript answers with no object.
# Today in history is answered with what was found for the reader's own topics
# first, then the last things listed, so a pick shows as other than Wikipedia's own.

BRIEF_WORLD = "You pick the world news for a morning brief."
BRIEF_AI = "You write the AI news for a morning brief."
BRIEF_HISTORY = "You pick today in history for a morning brief."
#: What waits on the person in Slack (`rouh/slack_brief.py`): a place waits when what is not
#: answered in it asks a question, and what it asks is its last question's first eight words.
BRIEF_SLACK = "You read Slack for a morning brief."
BRIEF_FILE = "brief-"


def is_briefing(body: dict) -> bool:
    system = _flat(body.get("system"))
    return (BRIEF_WORLD in system or BRIEF_AI in system or BRIEF_HISTORY in system
            or BRIEF_SLACK in system)


def a_slack_reading(said: str) -> str:
    waiting = []
    for number, text in zip(*[iter(re.split(r"(?m)^=== (\d+): ", said)[1:])] * 2):
        unanswered = partition(text.partition("Not answered:")[2], "‹owner› said later")[0]
        asks = [line.split(": ", 1)[1] for line in unanswered.strip().splitlines()
                if ": " in line and "?" in line.split(": ", 1)[1]]
        if asks:
            waiting.append({"n": int(number), "what": " ".join(asks[-1].split()[:8])})
    return json.dumps({"waiting": waiting}, ensure_ascii=False)


def a_history_pick(said: str) -> str:
    """Today in history for the reader's topics: everything found for a topic of
    their own, under that topic, then the last things listed, under the first
    topic, five in all. NOTHING FITS as a topic picks none."""
    topics = [line[2:].strip() for line in said.partition("=== The reader's topics")[2].splitlines()
              if line.startswith("- ")]
    if not topics or "NOTHING FITS" in topics:
        return json.dumps({"picked": []})
    rows = re.findall(r"(?m)^(\d+)\. [^\[\n]*\[([^\]]*)\]", said)
    picked = [{"n": int(n), "topic": kind[len("found for "):]} for n, kind in rows
              if kind.startswith("found for ")][:5]
    for n, _ in reversed(rows):
        if len(picked) >= 5:
            break
        if all(one["n"] != int(n) for one in picked):
            picked.append({"n": int(n), "topic": topics[0]})
    return json.dumps({"picked": picked}, ensure_ascii=False)


def a_brief_part(body: dict) -> str:
    said = last_user_text(body)
    if BRIEF_SLACK in _flat(body.get("system")):
        return a_slack_reading(said)
    if BRIEF_WORLD in _flat(body.get("system")):
        count = len(re.findall(r"(?m)^\d+\. ", said))
        return json.dumps({"picked": [n for n in range(count, max(0, count - 3), -1)]})
    if BRIEF_HISTORY in _flat(body.get("system")):
        return a_history_pick(said)
    if "BRIEFFAIL" in said:
        return "I could not make anything of these."
    videos = re.split(r"(?m)^=== Video (\d+): ", said)[1:]
    items = []
    for number, text in zip(videos[0::2], videos[1::2]):
        heading, _, spoken = text.partition("\n")
        words = spoken.split()
        halves = [words] if len(videos) // 2 >= 3 else [words[:len(words) // 2],
                                                         words[len(words) // 2:]]
        for part in halves:
            items.append({"headline": f"Video {number}: " + " ".join(part[:8]),
                          "summary": " ".join(part[8:40]) or heading.strip(),
                          "video": int(number)})
    return json.dumps({"items": items[:5]}, ensure_ascii=False)


def a_split(body: dict) -> str:
    said = last_user_text(body)
    if "NOSPLIT" in said:
        return "I cannot split that."
    _, asked, rest = said.partition("What the person asked:")
    if asked:
        _, _, now = said.partition("as name: step ids in order:")
        now = now.partition("What the person asked:")[0]
        streams = []
        for line in now.strip().splitlines():
            name, _, ids = line.rpartition(":")
            if name:
                streams.append({"name": name.strip(),
                                "steps": [i.strip() for i in ids.split(",") if i.strip()]})
        if "REVERSE" in rest:
            streams.reverse()
        elif "ONE" in rest:
            streams = [{"name": "Everything",
                        "steps": [i for one in streams for i in one["steps"]]}]
        return json.dumps({"streams": streams}, ensure_ascii=False)
    _, _, lines = said.partition("as id | who | title:")
    lines = lines.partition("The streams as they are now")[0]
    streams, current = [], []
    for line in lines.strip().splitlines():
        parts = [p.strip() for p in line.split("|", 2)]
        if len(parts) != 3:
            continue
        current.append(parts[0])
        if parts[1] != "rouh":
            streams.append({"name": " ".join(parts[2].split()[:3]), "steps": current})
            current = []
    if current:
        streams.append({"name": "Rouh's own", "steps": current})
    return json.dumps({"streams": streams}, ensure_ascii=False)


# --------------------------------------------------------------------------
# Standing in for the model that files a new task into a project.
# --------------------------------------------------------------------------
#
# The third side errand, told apart the same way as the other two: by the first
# words of the system prompt `rouh/filing.py` sends. It answers with one
# project's folder, or with `none`.
#
# And it answers out of what actually arrived, like everything else here. The
# request carries the task and every project as a line of `folder | column |
# name | what belongs in it`, so the words of the task are matched against the
# words of each project's name and description, and the project sharing the
# most of them wins. Nothing matching anything at all is `none`.
#
# That is what makes a browser test of this worth running: a description typed
# into Manage projects really travels to the model and really decides where the
# task lands, rather than a fixture having agreed the answer in advance. Change
# the description and the answer changes with it.

FILING = "You file new work into projects"

#: What a recorded filing request's file name starts with, so it is not read as
#: a turn of conversation either.
FILING_FILE = "filing-"

#: Words too common to be evidence of anything. The same idea as `TITLE_SKIP`
#: and a shorter list, because a description is already only the words somebody
#: chose to write.
FILING_SKIP = frozenset(
    "the a an and or of to for in on at is are be with about it this that my "
    "your our their i we me new task title what was said them they anything "
    "everything something".split())


def is_filing(body: dict) -> bool:
    return FILING in _flat(body.get("system"))


def _filing_words(said: str) -> set:
    return {w.lower() for w in re.findall(r"[\w'\u0400-\u04ff-]{3,}", said or "")
            if w.lower() not in FILING_SKIP}


def a_filing(body: dict) -> str:
    """The folder of the project this work belongs in, or `none`.

    Read out of the one request: the work above "The projects:" and the project
    lines under it. The winner is the project whose name and description share
    the most words with the work, and a tie or no overlap at all is `none` -
    which is the answer `rouh/filing.py` treats as "leave it where it is".
    """
    said = last_user_text(body)
    work, _, rest = said.partition("The projects:")
    work = work.replace("The work:", " ")
    wanted = _filing_words(work)
    best, score, tied = "none", 0, False
    for line in rest.splitlines():
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 4 or "/" not in parts[0]:
            continue
        folder, name, description = parts[0], parts[2], parts[3]
        shared = len(wanted & _filing_words(name + " " + description))
        if shared > score:
            best, score, tied = folder, shared, False
        elif shared == score and shared:
            tied = True
    return "none" if tied or not score else best


# --------------------------------------------------------------------------
# A new email, handed to Rouh itself (`rouh/mail_alerts.py`).
# --------------------------------------------------------------------------
#
# Until 25 September 2026 a small model judged every new email here, and this
# stood in for it. Rouh itself handles each one now, in an ordinary turn whose
# question is a note from Rouh's own software (`mail_alerts.brief`). Notes are
# stepped over when the stand-in looks for what a test typed, so this one is
# let through: `TOOL name {json}` lines written in the email's own body are
# called one a round, exactly as if they had been typed, which is how a test
# makes Rouh research a sender, tell the owner on Telegram or answer the email.

MAIL_BRIEF = "A new email has arrived in"
#: How the note begins that hands an email back to Rouh to finish - the job
#: started for it has reported, or a stage is still owed (`mail_flow.resume_note`).
MAIL_BACK = "is back with you to finish"
#: The note that carries an email's case on after it was assessed: carrying
#: out what the owner approved, and checking it (`mail_cases.CASE_MARK`).
CASE_BRIEF = "An email case"


def is_mail_brief(message) -> bool:
    """The note that hands Rouh a new email, which a test drives through its body."""
    if not isinstance(message, dict) or message.get("role") != "user":
        return False
    content = message.get("content")
    if isinstance(content, list):
        content = " ".join(b.get("text") or "" for b in content if isinstance(b, dict))
    return isinstance(content, str) and (MAIL_BRIEF in content[:200]
                                         or MAIL_BACK in content[:300]
                                         or CASE_BRIEF in content[:200])


def is_clock_note(message) -> bool:
    """The note a reminder starts a turn with (`rouh/reminders.note_for`).

    Read like the person's own words for its `TOOL` lines, the way a mail
    brief is, so a test can schedule a job whose instruction calls a tool and
    watch what a turn nobody is watching may and may not do.
    """
    if not isinstance(message, dict) or message.get("role") != "user":
        return False
    content = message.get("content")
    if isinstance(content, list):
        content = " ".join(b.get("text") or "" for b in content if isinstance(b, dict))
    return isinstance(content, str) and (SCHEDULED in content[:300]
                                         or HEARTBEAT_NOTE in content[:300])


#: How the note that has Rouh do one step of a goal begins its ask
#: (`goals.note_to_do`), after the reason it is given.
STEP_NOTE = re.compile(r'Do step [0-9.]+ of the goal "')


def is_step_note(message) -> bool:
    """The note a goal's step is started with (`timekeeper.do_step`).

    Read like the person's own words, as a reminder's is, so the step's own
    words decide what the stand-in does: `SLOWLY` in how it is done makes the
    turn on it last, which is what shows two streams going on at once, and a
    `TOOL` line in them is called.
    """
    if not isinstance(message, dict) or message.get("role") != "user":
        return False
    content = message.get("content")
    if isinstance(content, list):
        content = " ".join(b.get("text") or "" for b in content if isinstance(b, dict))
    return isinstance(content, str) and bool(STEP_NOTE.search(content[:1200]))


#: What the stand-in says when a reminder is due, the way a model given the
#: note would: the reminder's own words, the check-in's question, or what a
#: job found. `NOTHINGNEW` in a job's instruction makes it find nothing.
def clock_answer(body: dict) -> str:
    """The answer to a reminder's note, or "" when the turn is not one, or is
    past it - a tool the note called has answered, and `describe` says so."""
    for message in reversed(body.get("messages") or []):
        if message.get("role") != "user":
            continue
        flat = _flat(message.get("content"))
        if flat == " ".join(ANSWER_NOW.split()):
            continue
        if not is_clock_note(message):
            return ""
        if HEARTBEAT_NOTE in flat[:300]:
            # A beat of the heartbeat (`rouh/heartbeat.py`): the TOOL lines in its note -
            # put in its plan or notebook, or in an event - are what it does, and then
            # it says one line.
            return "Heartbeat: one step taken, as the stand-in."
        said = re.findall(r'"([^"]+)"', flat)
        if "the person asked you to do this" in flat:
            what = said[0] if said else "the job"
            # The title is the first thing quoted and the description the next
            # (`reminders.note_for`); the word may be in either.
            if any("NOTHINGNEW" in one for one in said):
                return NOTHING_NEW
            return f"I did it: {what}. As the stand-in I found nothing real to report."
        # A reminder handed to Rouh to decide about (fr_0d01a6cf1316): the
        # stand-in decides to say it, and a TOOL line in it is what makes it
        # decide something else.
        handed = re.search(r'is due: "(.*?)"(?:, in detail: ".*")?\. It is handed to you', flat)
        if handed:
            return f"It is time: {handed.group(1)}"
        return f"It is time: {said[-1]}" if said else "It is time."
    return ""


#: How a pass over a page's comments is told apart (`rouh/commentpass.py`):
#: the words its system prompt uses for the job, and the name its request is
#: written under, so a test can open the request and see what the model was
#: shown.
COMMENT_PASS = "go through every open thread in one pass"
PASS_FILE = "comments-"

_THREAD = re.compile(r'<thread id="(\d+)">(.*?)</thread>', re.S)
_MESSAGE = re.compile(r'<message author="([^"]*)"([^>]*)>(.*?)</message>', re.S)
_ELEMENT = re.compile(r'<element tag="([^"]*)"[^>]*?(?:where="([^"]*)")?[^>]*>', re.S)
_WORDS = re.compile(r"<words>(.*?)</words>", re.S)
_OPTIONS = re.compile(r'<options id="(\d+)"[^>]*>(.*?)</options>', re.S)
_PART = re.compile(r'<part n="\d+" tag="[^"]*">\n(.*?)\n</part>', re.S)
_PERSON = re.compile(r'<person key="([^"]*)" name="([^"]*)"( owner="yes")?')
_FILE = re.compile(r'<file name="([^"]*)">')


def is_comment_pass(body: dict) -> bool:
    return COMMENT_PASS in _flat(body.get("system"))


def a_comment_pass(body: dict) -> dict:
    """The `answer_comments` call a pass reads, written out of the threads
    that arrived, so what the page then shows proves what the model was shown.

    - A thread whose last words agree ("I like that", "thanks", "agreed") is
      skipped, with the reason.
    - Any other thread is answered, with the element it is on, where it is on
      the page, the words of the comment, and how many notes came with it and
      which one was the project's shared background.
    - A thread whose last words ask something ("?") or ask for a decision tags
      the page's owner, who is given a decision to make.
    - A thread on an element with options is offered one more version: the
      default's markup with " - a third way" after its first words.
    """
    import html as html_lib

    said = last_user_text(body)
    people = [(k, html_lib.unescape(n), bool(o)) for k, n, o in _PERSON.findall(said)]
    owner = next(((k, n) for k, n, o in people if o), None)
    notes = [html_lib.unescape(n) for n in _FILE.findall(said)]
    background = next((n for n in notes if n.startswith("_context/")), "")
    out = []
    for thread_id, inside in _THREAD.findall(said):
        messages = _MESSAGE.findall(inside)
        if not messages:
            continue
        last = " ".join(html_lib.unescape(messages[-1][2]).split())
        low = last.lower()
        element = _ELEMENT.search(inside)
        tag = element.group(1) if element else "body"
        where = html_lib.unescape(element.group(2) or "") if element else ""
        words = _WORDS.search(inside)
        label = " ".join(html_lib.unescape(words.group(1)).split())[:40] if words else ""
        entry: dict = {"thread": int(thread_id)}
        if any(w in low for w in ("i like that", "thanks", "agreed")):
            entry["skip"] = "It agrees with the page, so there is nothing useful to add"
            out.append(entry)
            continue
        reply = (f"On this <{tag}> \u201c{label}\u201d{', ' + where if where else ''}: you "
                 f"wrote \u201c{last[:50]}\u201d. Read with {len(notes)} notes"
                 + (f", {background} among them" if background else "") + ".")
        entry["note"] = f"Answered the {tag}"
        if owner and ("?" in last or "decide" in low):
            reply = f"@{owner[1]} a decision for you. " + reply
            entry["tag"] = [owner[0]]
            entry["note"] += ", with a decision for " + owner[1]
        entry["reply"] = reply
        offered = _OPTIONS.search(inside)
        if offered:
            first = _PART.findall(offered.group(2))
            if first:
                markup = re.sub(r">([^<>]*[^<>\s][^<>]*)<",
                                lambda m: ">" + m.group(1).strip() + " - a third way<",
                                first[0], count=1)
                entry["option"] = {"options": int(offered.group(1)), "label": "A third way",
                                   "reason": "Between the two versions people weighed in "
                                             "this thread.",
                                   "versions": [markup]}
        out.append(entry)
    return {"threads": out, "summary": f"Went through {len(out)} threads."}


def is_naming(body: dict) -> bool:
    system = body.get("system")
    if isinstance(system, list):
        system = " ".join(b.get("text", "") for b in system if isinstance(b, dict))
    return NAMING in (system or "")


def a_title(body: dict) -> str:
    """A title for the exchange in this request, written out of the exchange.

    Read out of what actually arrived, like everything else this server says,
    so a test that sees a title on the screen knows the conversation reached
    the naming request rather than that a fixture guessed the same words.
    """
    said = last_user_text(body)
    person = ""
    for line in said.split("\n"):
        if line.startswith("Person:"):
            person = line[len("Person:"):].strip()
            break
    words = [w for w in re.findall(r"[\w'\u0400-\u04ff-]+", person)
             if w.lower() not in TITLE_SKIP][:4]
    emoji = TITLE_DEFAULT
    low = person.lower()
    for needle, mark in TITLE_EMOJI:
        if needle in low:
            emoji = mark
            break
    return f"{emoji} " + (" ".join(words) if words else "New chat")


def _flat(content) -> str:
    """A tool result's content as one line, whichever shape it arrived in.

    The SDK sends a string for a plain answer and a list of blocks for anything
    richer, and both reach here.
    """
    if isinstance(content, str):
        return " ".join(content.split())
    if isinstance(content, list):
        parts = []
        for one in content:
            if isinstance(one, dict) and one.get("type") == "text":
                parts.append(one.get("text") or "")
            elif isinstance(one, str):
                parts.append(one)
        return " ".join(" ".join(parts).split())
    return ""


# --------------------------------------------------------------------------
# Standing in for Anthropic's web search and web fetch.
# --------------------------------------------------------------------------

#: An address in what the person typed. web_fetch may only read a page whose
#: address is already in the conversation, and that is the rule here too.
URL_IN_TEXT = re.compile(r"https?://[^\s\"'<>)]+")

#: What a test asks for when it wants the web. Either an address to read or
#: these words; anything else and this server answers the way it always did.
ASKS_THE_WEB = re.compile(r"\b(search|look up|look it up|what does .* say)\b", re.I)

#: A search asked for with these words comes back with nothing, or with the
#: error Anthropic sends when it turns a search away, so both can be seen.
FINDS_NOTHING = re.compile(r"\bfinds nothing\b", re.I)
SEARCH_FAILS = re.compile(r"\bsearch fails\b", re.I)

#: Where a search asked for `SLOWLY` waits before its results come back, and
#: for how long: a real one takes a few seconds, and that is the time in which
#: the line says what is being searched for and that it is still searching.
SEARCHING = None
SEARCH_SECONDS = 4


def search_results(query: str, url: str) -> list[dict]:
    """What a search comes back with: three pages, each a title and an address.

    Shaped the way Anthropic sends them. An address the person typed is the
    first of them, so a test can put a real page there and open it from the
    line on screen.
    """
    first = url or "https://example.invalid/first"
    return [
        {"type": "web_search_result", "title": "A result", "url": first,
         "page_age": "2 days ago", "encrypted_content": "not-really-encrypted"},
        {"type": "web_search_result", "title": f"More about {query}"[:120],
         "url": "https://example.invalid/more", "page_age": None,
         "encrypted_content": "not-really-encrypted"},
        {"type": "web_search_result", "title": "A third page, with a much longer title "
                                               "than the others so it has to wrap",
         "url": "https://example.invalid/a/very/long/address/that/goes/on/and/on"
                "?so=it&has=to&be=cut&short=on&a=phone",
         "page_age": "1 week ago", "encrypted_content": "not-really-encrypted"},
    ]

#: Tool call ids have to differ from turn to turn. See web_blocks below.
_CALL_NUMBER = itertools.count(1)


def last_user_text(body: dict) -> str:
    """Everything the person said in the last user turn, as one string.

    A note from Rouh's own software is not the person, and is stepped over
    for the reason `last_user_blocks` gives.
    """
    for message in reversed(body.get("messages") or []):
        if message.get("role") != "user" or is_note(message):
            continue
        content = message.get("content")
        if isinstance(content, str):
            return content
        out = []
        for block in content or []:
            if isinstance(block, dict) and block.get("type") == "text":
                out.append(block.get("text") or "")
        return " ".join(out)
    return ""


def web_refusal(body: dict) -> str | None:
    """Why this request cannot search, in the words the broken Rouh used.

    Three things have to be true before Anthropic's side lets the model search
    for itself, and all three were false the day this was found:

    * web_search has to be in the request at all;
    * its ``allowed_callers`` has to include ``direct``, or it is not a tool
      the model has - it is a function inside the code execution sandbox;
    * no second code execution tool may be declared beside it, because then
      there are two sandboxes and the model reaches for the wrong one.

    None of those is enforced here for the sake of enforcing it. They are the
    difference between a search that runs and a search that comes back "network
    is unreachable", and a test has to be able to feel that difference.
    """
    tools = [t for t in (body.get("tools") or []) if isinstance(t, dict)]
    by_name = {t.get("name"): t for t in tools}
    for name in ("web_search", "web_fetch"):
        tool = by_name.get(name)
        if tool is None or "input_schema" in tool:
            return (f"I do not have {name}, so I am answering from memory and "
                    "the numbers may be out of date.")
        callers = tool.get("allowed_callers")
        if callers is not None and "direct" not in callers:
            return (f"{name} is only callable from inside the code sandbox here, "
                    "and that sandbox has no network. I am answering from memory "
                    "and the numbers may be out of date.")
    if "code_execution" in by_name:
        return ("There are two execution environments in this request, so my web "
                "tools are the sandbox's and not my own. I am answering from "
                "memory and the numbers may be out of date.")
    return None


def fetch_page(url: str, timeout: float = 10.0) -> tuple[str, str]:
    """Really read the page, over HTTP. Its title and its text.

    This is the one part of this file that is not a stand-in. The bytes that
    come back here are the bytes a test put on a real web server, fetched by a
    real request, and they are what ends up on Rouh's screen. That is what
    makes "it came off the page" a thing a test can prove rather than assert.
    """
    with urllib.request.urlopen(url, timeout=timeout) as answer:
        raw = answer.read(200_000)
    text = raw.decode("utf-8", "replace")
    title = ""
    found = re.search(r"<title[^>]*>(.*?)</title>", text, re.S | re.I)
    if found:
        title = " ".join(found.group(1).split())
    # Tags out, whitespace collapsed: what a reader would see.
    body_text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", text, flags=re.S | re.I)
    body_text = " ".join(re.sub(r"<[^>]+>", " ", body_text).split())
    return title or url, body_text


def page_items(url: str, timeout: float = 10.0) -> list[str]:
    """The things a page lists, one per `<li>`, in its own order.

    What a search that turned up several pages answers with: each of them is
    one thing found at that page, so each carries that page's citation.
    """
    with urllib.request.urlopen(url, timeout=timeout) as answer:
        raw = answer.read(200_000).decode("utf-8", "replace")
    items = []
    for found in re.findall(r"<li(?:\s[^>]*)?>(.*?)</li>", raw, re.S | re.I):
        said = " ".join(re.sub(r"<[^>]+>", " ", found).split())
        if said:
            items.append(said)
    return items


def _text(index: int, words: str, citation: dict | None = None):
    """One text block, cited the way the real API cites one when it is.

    The citation arrives as a `citations_delta` before the words, which is
    the order Anthropic streams them in; the SDK puts the two back together
    into a text block with `citations` on it, and that is what Rouh reads.
    """
    yield _block_start(index, {"type": "text", "text": ""})
    if citation is not None:
        yield _sse("content_block_delta", {
            "type": "content_block_delta", "index": index,
            "delta": {"type": "citations_delta", "citation": citation}})
    yield _sse("content_block_delta", {
        "type": "content_block_delta", "index": index,
        "delta": {"type": "text_delta", "text": words}})
    yield _block_stop(index)


#: The most things a search that turned up several pages answers with.
MOST_FOUND = 10


def _block_start(index: int, block: dict) -> bytes:
    return _sse("content_block_start", {
        "type": "content_block_start", "index": index, "content_block": block})


def _block_stop(index: int) -> bytes:
    return _sse("content_block_stop", {"type": "content_block_stop", "index": index})


def _input_json(index: int, args: dict) -> bytes:
    """A server tool's input, streamed the way Anthropic streams it.

    It arrives after the block has opened, which is why Rouh first says only
    "Searching the web" and learns the words a moment later. Sending it in one
    piece here still exercises that path.
    """
    return _sse("content_block_delta", {
        "type": "content_block_delta", "index": index,
        "delta": {"type": "input_json_delta", "partial_json": json.dumps(args)}})


def web_blocks(body: dict, first: int = 0):
    """The blocks a real turn with a search and a page read is made of.

    Yields SSE bytes, and `SEARCHING` where the stream is to wait, and returns
    nothing when the request is not about the web. A refusal comes back as
    plain text with no tool calls at all, because that is what a Rouh without
    working web tools does: it talks from memory.

    What it says off a page is cited to that page, in the shapes the real API
    uses, which is what Rouh numbers its footnotes from (`rouh/citing.py`).
    One address is read with web_fetch and quoted; several are a search that
    turned them all up, answered with the things they list, each cited to its
    own page.

    `first` is the index the first block takes: 1 when a thinking block went
    out before them, as it does in front of everything in a real reply.
    """
    said = last_user_text(body)
    urls = URL_IN_TEXT.findall(said)
    if not urls and not ASKS_THE_WEB.search(said):
        return

    refusal = web_refusal(body)
    if refusal:
        yield _block_start(first, {"type": "text", "text": ""})
        yield _sse("content_block_delta", {
            "type": "content_block_delta", "index": first,
            "delta": {"type": "text_delta", "text": refusal}})
        yield _block_stop(first)
        return

    index = first
    query = " ".join(said.split())[:120]
    # A new id for every call, and the new part at the end. The tree keeps a
    # call by the last ten characters of its id (`tree._short_tool_id`), and it
    # will not reopen one that has already closed. A fixed id therefore drew no
    # twigs at all on a second turn, and two ids that differed only near the
    # front drew the search and the page read as one twig.
    search_id = f"srvtoolu_websearch{next(_CALL_NUMBER):06d}"
    yield _block_start(index, {"type": "server_tool_use", "id": search_id,
                               "name": "web_search", "input": {},
                               "caller": {"type": "direct"}})
    yield _input_json(index, {"query": query})
    yield _block_stop(index)
    index += 1
    if SLOW_MARK in said:
        yield SEARCHING

    url = urls[0] if urls else ""
    nothing = FINDS_NOTHING.search(said)
    turned_away = SEARCH_FAILS.search(said)
    if len(urls) > 1 and not (nothing or turned_away):
        # Several pages named: a search that turned all of them up, and an
        # answer made of the things they list, each cited to its own page
        # with the address and title the result carried - which is how the
        # real API cites a search result.
        found = []
        for one in urls:
            try:
                title, _ = fetch_page(one)
                items = page_items(one)
            except (urllib.error.URLError, OSError, ValueError):
                title, items = one, []
            found.append((one, title, items))
        yield _block_start(index, {
            "type": "web_search_tool_result", "tool_use_id": search_id,
            "content": [{"type": "web_search_result", "title": title, "url": one,
                         "page_age": None, "encrypted_content": "not-really-encrypted"}
                        for one, title, _ in found]})
        yield _block_stop(index)
        index += 1
        listed = [(one, title, item) for one, title, items in found for item in items]
        listed = listed[:MOST_FOUND]
        yield from _text(index, f"Here are {len(listed)} things I found:\n\n")
        index += 1
        for n, (one, title, item) in enumerate(listed, 1):
            yield from _text(index, f"{n}. ")
            index += 1
            yield from _text(index, item, {
                "type": "web_search_result_location", "url": one, "title": title,
                "cited_text": item, "encrypted_index": f"not-really-{n}"})
            index += 1
            yield from _text(index, "\n")
            index += 1
        return

    yield _block_start(index, {
        "type": "web_search_tool_result", "tool_use_id": search_id,
        "content": ({"type": "web_search_tool_result_error",
                     "error_code": "too_many_requests"} if turned_away
                    else [] if nothing else search_results(query, url))})
    yield _block_stop(index)
    index += 1

    if nothing or turned_away:
        said_back = (f"The search for {query} was turned away." if turned_away
                     else f"The search for {query} found nothing.")
        yield _block_start(index, {"type": "text", "text": ""})
        yield _sse("content_block_delta", {
            "type": "content_block_delta", "index": index,
            "delta": {"type": "text_delta", "text": said_back}})
        yield _block_stop(index)
        return

    if not url:
        yield _block_start(index, {"type": "text", "text": ""})
        yield _sse("content_block_delta", {
            "type": "content_block_delta", "index": index,
            "delta": {"type": "text_delta", "text": f"I searched for {query}."}})
        yield _block_stop(index)
        return

    fetch_id = f"srvtoolu_webfetch{next(_CALL_NUMBER):06d}"
    yield _block_start(index, {"type": "server_tool_use", "id": fetch_id,
                               "name": "web_fetch", "input": {},
                               "caller": {"type": "direct"}})
    yield _input_json(index, {"url": url})
    yield _block_stop(index)
    index += 1

    # A name in the tool's `blocked_domains` is refused at once and never
    # fetched, as the real API does (checked 6 October 2026): Rouh's own names
    # are there (`rouh/rouhlinks.py`).
    blocked = next((t.get("blocked_domains") or [] for t in body.get("tools") or []
                    if isinstance(t, dict) and t.get("name") == "web_fetch"), [])
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    try:
        if any(host == b or host.endswith("." + b) for b in blocked):
            title, page, failed, code = url, "", "the domain is blocked", "url_not_allowed"
        else:
            title, page = fetch_page(url)
            failed, code = "", ""
    except (urllib.error.URLError, OSError, ValueError) as exc:
        title, page, failed = url, "", f"the page could not be read ({exc})"
        # What the real fetcher says when the site turns it away or does not
        # answer, which is what a page that refuses this server's plain HTTP
        # client is standing in for (`rouh/fetchfallback.py` reads it again
        # in a browser). Anything else is the fetcher's own failure.
        code = ("url_not_accessible" if isinstance(exc, urllib.error.URLError)
                else "unavailable")

    if failed:
        yield _block_start(index, {
            "type": "web_fetch_tool_result", "tool_use_id": fetch_id,
            "content": {"type": "web_fetch_tool_result_error",
                        "error_code": code}})
        yield _block_stop(index)
        index += 1
        answer = f"I could not read {url}: {failed}."
    else:
        yield _block_start(index, {
            "type": "web_fetch_tool_result", "tool_use_id": fetch_id,
            "content": {"type": "web_fetch_result", "url": url,
                        "retrieved_at": None,
                        "content": {"type": "document", "title": title,
                                    "source": {"type": "text", "media_type": "text/plain",
                                               "data": page[:100_000]}}}})
        yield _block_stop(index)
        index += 1
        # Said out of the page's own bytes, so a sentence on screen that names
        # what the page says cannot have come from anywhere else. And cited to
        # the page the way the real API cites a fetched one: by the document's
        # title, with no address of its own.
        yield from _text(index, f"{title} says: ")
        index += 1
        quoted = page[:600]
        yield from _text(index, quoted, {
            "type": "char_location", "cited_text": quoted, "document_index": 0,
            "document_title": title, "start_char_index": 0,
            "end_char_index": len(quoted)})
        return

    yield from _text(index, answer)


def build_app(record_dir: str) -> FastAPI:
    app = FastAPI()
    os.makedirs(record_dir, exist_ok=True)

    # A key is judged by its own words, the way the first run's brain screen meets real ones
    # (`rouh/web/firstrun.py`): one with WRONG in it is a key Anthropic does not know, and one
    # with NOCREDIT in it is a right key on an account with no credit.
    def _refused_key(request: Request, asking: bool):
        key = request.headers.get("x-api-key", "")
        if "WRONG" in key:
            return JSONResponse(status_code=401, content={
                "type": "error", "error": {"type": "authentication_error", "message": "invalid x-api-key"}})
        if asking and "NOCREDIT" in key:
            return JSONResponse(status_code=400, content={"type": "error", "error": {
                "type": "invalid_request_error",
                "message": "Your credit balance is too low to access the Anthropic API. Please go to "
                           "Plans & Billing to upgrade or purchase credits."}})
        return None

    @app.get("/v1/models")
    async def models_list(request: Request):
        refused = _refused_key(request, asking=False)
        if refused is not None:
            return refused
        return JSONResponse({"data": [{"type": "model", "id": "claude-haiku-4-5", "display_name": "Claude Haiku 4.5",
                                       "created_at": "2025-10-01T00:00:00Z"}],
                             "has_more": False, "first_id": "claude-haiku-4-5", "last_id": "claude-haiku-4-5"})

    @app.post("/v1/messages")
    async def messages(request: Request):
        raw = await request.body()
        try:
            body = json.loads(raw)
        except ValueError:
            body = {}
        refused = _refused_key(request, asking=True)
        if refused is not None:
            return refused
        # Keep the predicates eager and in their original order, including
        # the waits between them. Each case pairs its recording prefix and
        # text reply; the later cases join the same table after their waits.
        errands = (
            (is_naming(body), TITLE_FILE, a_title),
            (is_triage(body), TRIAGE_FILE, a_decision),
            (is_filing(body), FILING_FILE, a_filing),
        )
        naming = errands[0][0]
        # And a pass over a page's comments, which answers every thread in
        # one `answer_comments` call (`rouh/commentpass.py`).
        passing = is_comment_pass(body)
        # And a step of a goal rewritten the way the person asked.
        revising = is_revising(body)
        # And a goal's plan split into streams.
        splitting = is_splitting(body)
        # And the morning brief's picking of the news and condensing of videos.
        briefing = is_briefing(body)
        # And a run's one sentence about what it is for (`rouh/runsummary.py`).
        summing = is_summing(body)
        # And a reminder's one-line title (`rouh/reminder_titles.py`).
        titling = is_titling(body)
        # And the heartbeat's wake-up check (`heartbeat.wake_check`).
        hbchecking = is_heartbeat_checking(body)
        # And What to raise before a meeting (`rouh/meeting_brief.py`).
        meetingbriefing = is_meeting_briefing(body)
        # And Last said in Slack before a meeting (`rouh/meeting_slack.py`).
        meetingslack = is_meeting_slack(body)
        # And the work after a meeting (`rouh/meeting_next.py`).
        meetingnext = is_meeting_next(body)
        # And a question already answered in a chat (`rouh/answered_in_chat.py`).
        answered = is_answered(body)
        # And the gate in front of the decisions (`rouh/decision_gate.py`).
        gating = is_gate(body)
        # And Slack's messages read for promises (`rouh/slack_promises.py`).
        promising = is_slack_promises(body)
        # And a linked Slack channel's messages read for decisions (`rouh/slack_tasks.py`).
        deciding = is_slack_decisions(body)
        # And a page's sources checked (`rouh/source_check.py`).
        sourcing = is_sources(body)
        # And a question on a gene's card (`rouh/gene_questions.py`).
        geneasking = is_gene_question(body)
        # And the gene log's writer, evaluation and Pool matcher (`rouh/genelog.py`).
        genelogging = is_gene_log(body)
        # And which profile a meeting guest is, read from his words
        # (`meeting_people.read_with_model`).
        meetingpick = is_meeting_pick(body)
        # And automatic recall's second reader of a message.
        recallpick = is_recall_pick(body)
        if recallpick and RECALL_SLOW in json.dumps(body.get("messages") or []).split("THE MESSAGE:")[-1]:
            # A reading that is late, past the old 2 s limit (`autorecall.ask`).
            await asyncio.sleep(RECALL_SLOW_S)
        # And the Control Room's naming pass (`rouh/controlroom.py`).
        clusternaming = is_cluster_naming(body)
        # And Define over a passage on a page (`rouh/definitions.py`).
        # And a page told as a narration (`rouh/page_listen.py`).
        listening = is_page_listen(body)
        picturing = is_picture_prompt(body)
        defining = is_defining(body)
        if defining:
            await asyncio.sleep(DEFINE_WAIT_S)
        # Comment passes select a recording prefix but answer by a tool call
        # below, so text selection steps over them. Define records before
        # cluster naming, while cluster naming's text wins when both match.
        errands += (
            (passing, PASS_FILE, None),
            (revising, REVISE_FILE, a_revision),
            (splitting, SPLIT_FILE, a_split),
            (briefing, BRIEF_FILE, a_brief_part),
            (summing, SUMMARY_FILE, a_summary),
            (titling, TITLING_FILE, a_reminder_title),
            (hbchecking, HEARTBEAT_CHECK_FILE, a_heartbeat_check),
            (meetingbriefing, MEETING_BRIEF_FILE, a_meeting_brief),
            (meetingslack, MEETING_SLACK_FILE, a_meeting_slack),
            (meetingnext, MEETING_NEXT_FILE, a_meeting_next),
            (answered, ANSWERED_FILE, an_answered),
            (gating, GATE_FILE, a_gate),
            (is_job_request(body), JOB_REQUEST_FILE, a_job_request),
            (is_action_read(body), ACTION_READ_FILE, an_action_read),
            (is_action_ask(body), ACTION_ASK_FILE, an_action_answer),
            (promising, SLACK_PROMISES_FILE, a_slack_promises),
            (deciding, SLACK_DECISIONS_FILE, a_slack_decisions),
            (sourcing, SOURCES_FILE, a_sources),
            (geneasking, GENE_ASK_FILE, a_gene_answer),
            (listening, PAGE_LISTEN_FILE, a_narration),
            (picturing, PICTURE_PROMPT_FILE, a_picture_prompt),
            (genelogging, GENE_LOG_FILE, a_gene_log_answer),
            (meetingpick, MEETING_PICK_FILE, a_meeting_pick),
            (recallpick, RECALL_PICK_FILE, a_recall_pick),
            (defining, DEFINE_FILE, a_cluster_naming if clusternaming else a_definition),
            (clusternaming, CLUSTER_FILE, a_cluster_naming),
        )
        errand = any(matched for matched, prefix, _ in errands)
        # Written whole and unparsed: the point of this server is the bytes.
        #
        # A naming request is written under a name of its own. It is a side
        # errand that follows a turn rather than part of one, and it lands
        # whenever the model gets round to it, so a test reading "the last
        # request" for the picture it attached must not be handed the request
        # that asked for a title instead. `Live.model_requests` reads the
        # turns and `Live.title_requests` reads these.
        lead = next((prefix for matched, prefix, _ in errands if matched), "")
        name = f"{lead}{time.time():.6f}-{len(os.listdir(record_dir)):03d}.json"
        with open(os.path.join(record_dir, name), "wb") as fh:
            fh.write(raw)
        # Written down first and refused second, on purpose: the request that
        # was refused is the one somebody will have to read. That is true of
        # both kinds of refusal below.
        why = (refuses(body) or too_long(raw, body) or cache_refusal(body)
               or server_call_refusal(body))
        if why:
            return JSONResponse(status_code=400, content={
                "type": "error",
                "error": {"type": "invalid_request_error", "message": why},
            })
        # A refusal a test asked for in words, for the retries: a test about
        # them is a test about how many identical bodies went out.
        trouble = None if naming else failing(body)
        if trouble is not None:
            status, kind, words = trouble
            return JSONResponse(
                {"type": "error", "error": {"type": kind, "message": words}},
                status_code=status,
                # Nothing is waited out in a test that can help it.
                headers={"retry-after": "0"})
        # What this request reads out of the cache and writes to it, worked
        # out once it is certain to be answered, because a refused request
        # caches nothing. Written down a line each, beside the requests.
        cached = cache_usage(body)
        with open(usage_file(record_dir), "a", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "file": name, "model": body.get("model") or "",
                "breakpoints": sum(1 for _d, _s, ttl in _positions(body) if ttl),
                **cached}) + "\n")
        # Worked out before the stream opens, because by the time it is open
        # the status has already gone out as 200 and cannot be taken back -
        # which is the point of it.
        drop = "" if errand else dropping(body)
        hanging = not errand and bool(HANG_LINE.search(
            " ".join(b.get("text") or "" for b in last_user_blocks(body)
                     if b.get("type") == "text")))
        answer = next((answer for matched, _, answer in errands
                       if matched and answer is not None), None)
        reply = answer(body) if answer is not None else clock_answer(body) or describe(body)
        if not errand and asks_for_notes(body):
            reply = notes_said(body)
        if not errand and not naming:
            reply += an_offer_of_work(body)
        if not errand and asks_for_long(body):
            reply = long_answer()
        # The words a test wants Rouh's answer to be, typed on a line of their own:
        # "REPLY: Once it's done I'll email her." A real model writes its own; this
        # lets a test give Rouh a sentence to have said, after any TOOL lines run.
        told = None if errand else REPLY_LINE.search(_typed_calls(body)[2])
        if told:
            reply = told.group(1).strip()
        # Whether the person had finished asking, which the real model answers
        # with the first character of its reply (`rouh/turnmarks.py`). An
        # unfinished one writes the mark and nothing else at all: no words, no
        # tool, no thinking, and nothing for Rouh to say or store.
        mark = "" if errand else turn_mark(body)
        unfinished = mark in (CUT_OFF_MID_THOUGHT, STILL_THINKING)
        # Both ways a test drives this, worked out before the stream opens.
        # A `TOOL ...` line is the most deliberate of the two, so it wins.
        calls = [] if (errand or unfinished) else wanted_tools(body)
        if passing:
            calls = [("answer_comments", a_comment_pass(body))]
        call = calls[0] if calls else None
        thinks = not errand and not unfinished and thinking_asked_for(body)
        web = ([] if (errand or unfinished or call is not None)
               else list(web_blocks(body, 1 if thinks else 0)))
        slow = (not errand and not unfinished and call is None and not web
                and is_slow(body))
        if slow:
            reply = SLOW_ANSWER
        if unfinished:
            reply = mark
        elif mark:
            reply = f"{mark} {reply}"

        # The last word on the usage, which is the one the SDK keeps: the
        # three totals, the way the real API repeats them at the end.
        delta_usage = {**DELTA_USAGE, **{k: v for k, v in cached.items()
                                         if k != "cache_creation"}}
        # And what was written, about four characters a token, rather than
        # one: the cost of a turn and the log of requests (`rouh/llmlog.py`)
        # then have a sensible number to show for it in a world.
        written = (len(reply) + (len(THINKING) if thinks else 0)
                   + sum(len(json.dumps(args)) for _, args in calls))
        delta_usage["output_tokens"] = max(1, written // 4)

        if errand and not body.get("stream"):
            # Asked without a stream, as Synapse asks Claude for a structured answer (`synapse/ai.py`,
            # automatic recall's second reader): the whole message at once, as the real API sends it.
            return JSONResponse({
                "id": "msg_fake", "type": "message", "role": "assistant",
                "model": body.get("model", "claude-sonnet-5"),
                "content": [{"type": "text", "text": reply}],
                "stop_reason": "end_turn", "stop_sequence": None,
                "usage": {**{k: v for k, v in cached.items() if k != "cache_creation"},
                          "output_tokens": delta_usage["output_tokens"]}})

        def stream():
            start = {
                "type": "message_start",
                "message": {
                    "id": "msg_fake", "type": "message", "role": "assistant",
                    "model": body.get("model", "claude-sonnet-5"), "content": [],
                    "stop_reason": None, "stop_sequence": None,
                    "usage": {**cached, "output_tokens": 1},
                },
            }
            yield _sse("message_start", start)
            if drop:
                # Broken inside the stream, before a word of the reply. The
                # event is the shape the real API sends and the SDK turns it
                # into an `APIStatusError` whose status_code is 200, because
                # that is what this response's status is.
                yield _sse("error", {
                    "type": "error",
                    "error": {"details": None, "type": drop, "message": drop},
                    "request_id": "req_fake_dropped"})
                return
            # Thinking comes first in a real reply, before the words and
            # before any tool call, and it streams as `thinking_delta` and not
            # as `text_delta`. That difference is the whole of what keeps it
            # out of the voice, so this sends it the way the API does.
            if thinks:
                yield _sse("content_block_start", {
                    "type": "content_block_start", "index": 0,
                    "content_block": {"type": "thinking", "thinking": "",
                                      "signature": ""}})
                yield _sse("content_block_delta", {
                    "type": "content_block_delta", "index": 0,
                    "delta": {"type": "thinking_delta", "thinking": THINKING}})
                yield _sse("content_block_delta", {
                    "type": "content_block_delta", "index": 0,
                    "delta": {"type": "signature_delta", "signature": "fake-signature"}})
                yield _sse("content_block_stop", {"type": "content_block_stop", "index": 0})
            if hanging:
                # The turn is open and stays open. Nothing more is written, so
                # the server that is holding it is still holding it when a test
                # kills it, which is the whole point.
                time.sleep(HANG_SECONDS)
                return
            at = 1 if thinks else 0
            for n, (name, args) in enumerate(calls):
                yield _sse("content_block_start", {
                    "type": "content_block_start", "index": at + n,
                    "content_block": {"type": "tool_use", "id": next(_call_ids),
                                      "name": name, "input": {}}})
                # The input streams in as JSON text, the way the real API sends
                # it, so the SDK puts the block back together rather than being
                # handed one already assembled.
                yield _sse("content_block_delta", {
                    "type": "content_block_delta", "index": at + n,
                    "delta": {"type": "input_json_delta",
                              "partial_json": json.dumps(args)}})
                yield _sse("content_block_stop", {"type": "content_block_stop",
                                                  "index": at + n})
            if calls:
                yield _sse("message_delta", {
                    "type": "message_delta",
                    "delta": {"stop_reason": "tool_use", "stop_sequence": None},
                    "usage": delta_usage})
                yield _sse("message_stop", {"type": "message_stop"})
                return
            if web:
                for piece in web:
                    if piece is SEARCHING:
                        time.sleep(SEARCH_SECONDS)
                        continue
                    yield piece
            elif slow:
                # A word at a time, with a real pause between them, so the turn
                # is still being written and still being spoken while a test
                # reaches for Escape. Starlette runs a sync generator in a
                # thread, so sleeping here holds up nothing but this response.
                yield _sse("content_block_start", {
                    "type": "content_block_start", "index": at,
                    "content_block": {"type": "text", "text": ""}})
                for word in reply.split(" "):
                    yield _sse("content_block_delta", {
                        "type": "content_block_delta", "index": at,
                        "delta": {"type": "text_delta", "text": word + " "}})
                    time.sleep(SLOW_WORD_SECONDS)
                yield _sse("content_block_stop", {"type": "content_block_stop", "index": at})
            elif listening:
                # A part at a time, as a narration of a long page comes from a real model.
                yield _sse("content_block_start", {
                    "type": "content_block_start", "index": at,
                    "content_block": {"type": "text", "text": ""}})
                for piece in re.split(r'(?<=\}), (?=\{"say")', reply):
                    time.sleep(LISTEN_PART_S)
                    yield _sse("content_block_delta", {
                        "type": "content_block_delta", "index": at,
                        "delta": {"type": "text_delta", "text": piece + ", "}})
                yield _sse("content_block_stop", {"type": "content_block_stop", "index": at})
            else:
                yield _sse("content_block_start", {
                    "type": "content_block_start", "index": at,
                    "content_block": {"type": "text", "text": ""}})
                yield _sse("content_block_delta", {
                    "type": "content_block_delta", "index": at,
                    "delta": {"type": "text_delta", "text": reply}})
                yield _sse("content_block_stop", {"type": "content_block_stop", "index": at})
            yield _sse("message_delta", {
                "type": "message_delta",
                "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                "usage": delta_usage})
            yield _sse("message_stop", {"type": "message_stop"})

        return StreamingResponse(stream(), media_type="text/event-stream")

    return app


def main() -> None:
    import uvicorn

    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--record", required=True)
    args = ap.parse_args()
    uvicorn.run(build_app(args.record), host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
