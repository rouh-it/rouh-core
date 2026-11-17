"""How many tokens a piece of a request comes to, counted on what is sent, without asking a provider.

Petar, 17 November 2026, of a fork of General whose "Parent chat history" said it came to over 500,000
tokens when its turns were about 110,000 in all: "let's fix the thing that counts so it counts correctly".
The old count was a quarter of the characters of what was stored. This counts the blocks a turn actually
sends (`memory.Memory.history`, `context_editing.lean`, `attachments.hydrate`), block by block:

- words by their kind of characters (`text`): Opus 5.5's tokenizer takes about two and a half letters of
  English to a token, a digit or a mark of punctuation to about one, and a letter of any other script to
  more than one;
- a tool call by its name and its arguments as JSON, and a tool result by its words, each with the few
  tokens the API puts round it;
- a picture by its pixels, as Anthropic counts them (width times height over 750, once it is made to fit
  1568 pixels on its long side), and a PDF by its pages.

It is an estimate, measured against Anthropic's own count (count_tokens) on real conversations: within a few
percent on a conversation, which is what a size in a panel needs. Asking the provider for each panel would
make opening it wait on the network, and the size shown has to be there the moment it is pressed.
"""
from __future__ import annotations

import base64
import json
import re

#: Tokens of a character, by kind: a letter of the Latin alphabet, a digit, a punctuation mark or symbol, and a
#: character of any other script; whitespace goes with the word beside it. Fitted on 42 pieces of a real
#: General (prose, tool arguments and results) against count_tokens for claude-opus-5-5 on 17 November 2026:
#: 7.5% off on a piece on average, half a percent over all of them.
LETTER = 0.385
DIGIT = 0.95
MARK = 0.78
OTHER = 1.2
#: A web search's or fetch's page, which comes back encrypted: tokens of one of its characters (measured the
#: same day: 0.351 and 0.355 on two windows).
ENCRYPTED = 0.35
#: The tokens round each message, each tool call and each tool result.
PER_MESSAGE = 4
PER_CALL = 12
PER_RESULT = 6
#: A picture's tokens: its pixels over this, once it fits `PICTURE_EDGE` on its long side.
PICTURE_PIXELS = 750
PICTURE_EDGE = 1568
PICTURE_MOST = 1_600
#: A PDF page, its words and its picture together.
PDF_PAGE = 1_800

_LETTER = re.compile(r"[A-Za-z]")
_DIGIT = re.compile(r"[0-9]")
_SPACE = re.compile(r"\s")


def text(s: str) -> int:
    """About how many tokens these words are."""
    if not s:
        return 0
    letters = len(_LETTER.findall(s))
    digits = len(_DIGIT.findall(s))
    space = len(_SPACE.findall(s))
    ascii_ = sum(1 for c in s if ord(c) < 128)
    marks = ascii_ - letters - digits - space
    other = len(s) - ascii_
    return max(1, round(letters * LETTER + digits * DIGIT + marks * MARK + other * OTHER))


def _picture(block: dict) -> int:
    """A picture's tokens, from its own pixels when they can be read."""
    try:
        from . import attachments

        data = base64.b64decode(str((block.get("source") or {}).get("data") or ""))
        size = attachments._picture_size(data)
    except Exception:  # noqa: BLE001 - a picture that cannot be measured is taken at its most
        size = None
    if not size:
        return PICTURE_MOST
    w, h = size
    scale = min(1.0, PICTURE_EDGE / max(w, h, 1))
    return max(1, min(PICTURE_MOST, round((w * scale) * (h * scale) / PICTURE_PIXELS)))


def _pdf(block: dict) -> int:
    try:
        data = base64.b64decode(str((block.get("source") or {}).get("data") or ""))
    except Exception:  # noqa: BLE001
        return PDF_PAGE
    pages = len(re.findall(rb"/Type\s*/Page(?![a-z])", data))
    return PDF_PAGE * max(1, pages)


def _field(block, name: str):
    return block.get(name) if isinstance(block, dict) else getattr(block, name, None)


def _server(b) -> int:
    """A block of a server tool's result (a web search's or fetch's): its encrypted pages by their length,
    and its words, titles and addresses as words."""
    if isinstance(b, dict):
        total = 0
        for k, v in b.items():
            if k == "encrypted_content" and isinstance(v, str):
                total += round(len(v) * ENCRYPTED)
            elif isinstance(v, str):
                total += text(v) if k not in ("type",) else 1
            else:
                total += _server(v)
        return total
    if isinstance(b, list):
        return sum(_server(v) for v in b)
    return 0


def content(c) -> int:
    """A message's content: a string, or a list of blocks."""
    if isinstance(c, str):
        return text(c)
    total = 0
    for b in c if isinstance(c, list) else []:
        kind = _field(b, "type")
        if kind == "text":
            total += text(str(_field(b, "text") or ""))
        elif kind in ("tool_use", "server_tool_use"):
            args = _field(b, "input")
            total += PER_CALL + text(str(_field(b, "name") or "")) + text(
                json.dumps(args, ensure_ascii=False) if args is not None else "")
        elif kind == "tool_result":
            total += PER_RESULT + content(_field(b, "content"))
        elif kind == "image":
            total += _picture(b if isinstance(b, dict) else {})
        elif kind == "document":
            total += _pdf(b if isinstance(b, dict) else {})
        elif kind in ("thinking", "redacted_thinking"):
            continue                      # never sent back from the history (`brain`)
        else:
            try:
                total += _server(b if isinstance(b, dict) else b.model_dump())
            except Exception:  # noqa: BLE001
                total += text(str(b))
    return total


def messages(msgs: list) -> int:
    """A list of messages, as the API is sent them."""
    return sum(PER_MESSAGE + content(_field(m, "content")) for m in msgs or [])
