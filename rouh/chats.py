"""What a chat is called, and who decides it.

A chat starts untitled and gets its name from its own first exchange, so the
list of them reads like a list of things that happened rather than a list of
timestamps. The rule for a title is short enough to say in one line:

    an emoji, then two to five words, and nothing else.

The emoji is not decoration. The list in the middle column is scanned, not
read, and a leading emoji is what the eye lands on before any of the words: a
column of "Server migration", "Server mail" and "Server invoice" is three
identical rows, and a column of the same three with a lorry, an envelope and a
receipt in front of them is not. So every title has one, including the one a
chat carries before the model has seen it (`memory.UNTITLED`), and a title that
comes back without one is given one here rather than being let through - a list
where some rows are indented by an emoji and some are not looks broken.

The model is asked for the title through the same SDK as everything else, which
is why a test with the stand-in model in front of Anthropic
(`testing/fake_model.py`) sees the request and answers it.

What is deliberately not here: any of this is allowed to fail. A chat with no
title is a chat that says "New chat", which is worse than a good title and far
better than a turn that did not answer because naming it went wrong. Every
failure is logged and swallowed.
"""
from __future__ import annotations

import logging
import unicodedata

log = logging.getLogger("rouh.chats")

#: Asked of the model, and of nothing else. Deliberately not the assistant's
#: own system prompt: this is not Rouh talking to the person, it is a
#: labelling job, and the assistant's prompt would have it answer in sentences.
SYSTEM = (
    "You name conversations. You are given the first exchange of one and you "
    "answer with a title for it, and with nothing else.\n"
    "\n"
    "The rules for a title:\n"
    "- It starts with exactly one emoji, and the emoji matches what the "
    "conversation is about.\n"
    "- Then two to five words saying what it is about. Not a sentence, no full "
    "stop, no quotation marks.\n"
    "- Name the subject, not the shape of it: \"Server migration\", never "
    "\"User asks about a migration\".\n"
    "- Answer in the language the person is using.\n"
    "\n"
    "Examples of the whole answer:\n"
    "\N{DELIVERY TRUCK} Server migration\n"
    "\N{BAR CHART} September revenue\n"
    "\N{SEEDLING} Balcony tomatoes"
)

#: What the model is asked, with the exchange under it. One message rather than
#: a replay of the conversation: the model is labelling a transcript, not
#: joining in, and a replayed conversation invites it to answer the person's
#: question instead of naming it.
ASK = (
    "Name this conversation. Remember: one emoji, then two to five words, and "
    "nothing else.\n\n{exchange}"
)

#: How much of the chat the title is written from. The first exchange is what a
#: chat is about; what came after is where it wandered to, and a title that
#: follows the wandering changes under the person every turn.
TURNS = 4

#: And how much of each turn. A pasted stack trace is not a better title for
#: having been read whole.
CHARS = 600

#: How long the model may take. It runs beside a turn the person is waiting on
#: and its answer is a nicety, so it gets a short rope and no retry.
TIMEOUT = 20.0

#: The emoji put in front of a title that came back without one. Something that
#: means "this is a conversation" and nothing more specific, because by then
#: nothing is known about what would have been more specific.
FALLBACK_EMOJI = "\N{SPEECH BALLOON}"

#: Where in Unicode an emoji is. `unicodedata` has no "is this an emoji", and
#: the property files that would answer it are not in the standard library, so
#: these are the blocks emoji actually come from - the pictographs, the
#: dingbats, the arrows and symbols that carry emoji presentation, and the
#: regional indicators that make a flag. A character outside them is a letter,
#: a digit or punctuation, and the title needs an emoji put in front of it.
EMOJI_RANGES = (
    (0x1F000, 0x1FAFF),   # mahjong through the newest pictographs
    (0x1F1E6, 0x1F1FF),   # regional indicators (flags)
    (0x2600, 0x27BF),     # miscellaneous symbols and dingbats
    (0x2B00, 0x2BFF),     # arrows and stars
    (0x2190, 0x21FF),     # arrows
    (0x2700, 0x27BF),     # dingbats
    (0xFE0F, 0xFE0F),     # the variation selector that makes one of these an emoji
    (0x00A9, 0x00A9),     # (c)
    (0x00AE, 0x00AE),     # (R)
    (0x203C, 0x3299),     # the scattered older symbols with emoji presentation
)


def is_emoji(ch: str) -> bool:
    """Whether this one character reads as a picture rather than as text.

    Letters, digits and punctuation are never emoji whatever block they fall
    in, which is what the category check is for: the last range above is wide
    and would otherwise swallow ordinary CJK.
    """
    if not ch:
        return False
    if unicodedata.category(ch) in ("Lu", "Ll", "Lt", "Lm", "Lo", "Nd", "Nl"):
        return False
    point = ord(ch)
    return any(lo <= point <= hi for lo, hi in EMOJI_RANGES)


def starts_with_emoji(title: str) -> bool:
    title = (title or "").strip()
    return bool(title) and is_emoji(title[0])


def ensure_emoji(title: str) -> str:
    """One title, tidied of its whitespace and certain to start with a picture.

    Every title has one, wherever it came from: the model's, and the one the
    person typed over it. A list where some rows are indented by an emoji and
    some are not looks broken, and the picture is what the eye lands on before
    any of the words, which is the whole reason the rule exists. Somebody who
    wants a particular emoji types it and it is kept; somebody who types none
    gets the neutral one rather than a ragged list.

    "" in, "" out: that is a chat with no title, not a chat called nothing.
    """
    title = " ".join((title or "").split())
    if not title:
        return ""
    return title if starts_with_emoji(title) else f"{FALLBACK_EMOJI} {title}"


def tidy(raw: str, limit: int) -> str:
    """The model's answer as a title, or "" when there is nothing usable in it.

    Models answer a question like this with the answer and sometimes with a
    sentence around it, so the first non-empty line is taken and the wrapping
    that shows up in practice - quotation marks, a "Title:" label, a trailing
    full stop, a markdown bullet - is taken off. Then, if what is left does not
    start with an emoji, one is put in front of it, because a list where some
    rows have one and some do not is a list that looks broken.
    """
    line = ""
    for candidate in (raw or "").replace("\r", "").split("\n"):
        candidate = candidate.strip()
        if candidate:
            line = candidate
            break
    if not line:
        return ""
    for lead in ("- ", "* ", "#"):
        while line.startswith(lead):
            line = line[len(lead):].strip()
    low = line.lower()
    for label in ("title:", "chat title:", "name:"):
        if low.startswith(label):
            line = line[len(label):].strip()
            break
    line = line.strip("\"'“”‘’").strip()
    line = line.rstrip(".").strip()
    return ensure_emoji(line)[:limit].strip()


def exchange_text(transcript: list[dict], turns: int = TURNS) -> str:
    """The start of a chat, as the lines the model is asked to name.

    `transcript` is the chat's first turns, oldest first
    (`conversations.opening`), and never its last ones: the first exchange is
    what a chat is about.

    Empty when there is nothing to name yet, which is how a chat that has only
    a question in it and no answer is left alone until it has both: a title
    written from half an exchange is a title written from half the subject.
    Two questions and no answer are still half of one.
    """
    rows = [r for r in (transcript or []) if (r.get("text") or "").strip()][:turns]
    if len(rows) < 2 or not any(r.get("role") == "assistant" for r in rows):
        return ""
    lines = []
    for row in rows:
        who = "Rouh" if row.get("role") == "assistant" else "Person"
        said = " ".join((row.get("text") or "").split())[:CHARS]
        lines.append(f"{who}: {said}")
    return "\n".join(lines)


async def suggest(exchange: str, limit: int = 60, *, session_id: str = "") -> str:
    """Ask the model the Models page has for chat titles for one, whichever
    company's it is (`rouh/llm.py`). "" when it did not say."""
    from . import llm

    if not exchange.strip():
        return ""
    got = await llm.ask("chat_title", system=SYSTEM, messages=ASK.format(exchange=exchange),
                        max_tokens=64, session_id=session_id, timeout=TIMEOUT, read_only=True)
    return tidy(got.text, limit)
