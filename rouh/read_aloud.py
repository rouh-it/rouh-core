"""Read this message aloud: the speaker icon under a message in the conversation.

Petar, 12 November 2026 (fr_fc456cc390af): "For each message I receive, I have little icons
underneath. The last one is the time. Can you add one more so that when I press it, I will hear
what the conversation has said?"

So every answer in the conversation has a speaker after its clock (`fitActs` in
rouh/static/app/transcript.js), and a press on it reads that message out. It is said the way an
answer is said while it is being written, and by the same parts:

- **the same voice**, the runtime's own `speech.Voice` (``runtime.voice``), so the ElevenLabs
  voice, model and rate are the ones every spoken answer has;
- **the same pieces**, cut by the turn's own sentence splitter (`brain._split_sentences`), each
  with its task numbers said as their names (`searching.spoken`), one request to the voice each,
  as `Turn._speak_loop` does;
- **the same speaker on the page**: the bytes are PCM16 mono, played through the page's one
  AudioContext and its output (`app/readaloud.js`).

What is different is only what it is not tied to: no turn, no tab's voice switch. It is one
explicit press, so it is said whether or not answers are spoken as they are written, and it says
nothing to any other tab.

What the page sends is the message's words as they were written, Markdown and all, which is what
the voice is given while an answer is being written too; the few marks that would otherwise be
read out as words - a link's address, a code fence, a table's bars - are taken out here first.
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import AsyncIterator

log = logging.getLogger("rouh.read_aloud")

#: The most of a message read out at once. A message longer than this is read to here.
MOST = 20000

_FENCE = re.compile(r"```.*?(```|$)", re.S)
_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_URL = re.compile(r"<?https?://[^\s<>()]*[^\s<>().,;:!?'\"]>?")
_FOOTNOTE = re.compile(r"\[\^?\d+\]")
_RULE = re.compile(r"^\s*(\|?\s*:?-{3,}:?\s*)+\|?\s*$", re.M)
_HEAD = re.compile(r"^\s{0,3}#{1,6}\s*", re.M)
_BULLET = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+", re.M)
_QUOTE = re.compile(r"^\s*>\s?", re.M)
_MARKS = re.compile(r"(\*\*|__|\*|`|~~)")


def words_to_say(text: str) -> str:
    """The message as words for the ear: Markdown's marks taken out, each line kept a line."""
    text = str(text or "")[:MOST]
    text = _FENCE.sub(" ", text)
    text = _IMAGE.sub(r"\1", text)
    text = _LINK.sub(r"\1", text)
    text = _URL.sub(" ", text)
    text = _FOOTNOTE.sub("", text)
    text = _RULE.sub("", text)
    text = _HEAD.sub("", text)
    text = _BULLET.sub("", text)
    text = _QUOTE.sub("", text)
    text = _MARKS.sub("", text)
    # A table's cells, said one after the other.
    text = re.sub(r"[ \t]*\|[ \t]*", ", ", text)
    text = re.sub(r"(,[ \t]*){2,}", ", ", text)
    text = re.sub(r"^[, \t]+|[, \t]+$", "", text, flags=re.M)
    text = re.sub(r"[ \t]+([.,;:!?])", r"\1", text)
    # A heading or a list item ends without a stop; a line is a pause, so it gets one.
    lines = [ln.strip() for ln in text.splitlines()]
    out = []
    for ln in lines:
        if not ln:
            continue
        if ln[-1] not in ".!?…:;,":
            ln += "."
        out.append(ln)
    return "\n".join(out)


def pieces(text: str) -> list[str]:
    """What is sent to the voice, one request each: the turn's own sentences."""
    from .brain import _split_sentences

    said, rest = _split_sentences(words_to_say(text) + "\n")
    if rest.strip():
        said.append(rest.strip())
    return [s for s in said if any(ch.isalnum() for ch in s)]


async def stream(text: str, voice) -> AsyncIterator[bytes]:
    """The message in Rouh's voice, PCM16 mono at the voice's rate, as it comes."""
    from . import searching

    for piece in pieces(text):
        try:
            piece = await asyncio.to_thread(searching.spoken, piece)
        except Exception:
            log.exception("could not say the task numbers in a sentence by name")
        async for chunk in voice.stream(piece):
            yield chunk


__all__ = ["MOST", "pieces", "stream", "words_to_say"]
