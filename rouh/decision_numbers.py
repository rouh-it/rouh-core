"""A decision's number: Decision 1, Decision 2, Decision 3, one person's in the order asked.

Petar, 18 October 2026: drop the letter-and-three-digit handles (a482). "The letters mean
nothing and confuse him, because similar decisions get different letters. Numbering should
be consecutive, not random." So every decision has a plain number, starting at 1 for each
person and going up by one (`Decision.number`, given in `decisions._Numbers`), shown as
"Decision 42", or "#42" where there is little room.

**Read tolerantly.** `read` takes what speech recognition or a thumb produces for one and
gives back the number: "42", "#42", "decision 42", "Decision #42", "number 42", "forty-two",
"decision forty two", "one hundred and five", "four two". A bare number names a decision only
where decisions are what is being talked about (the `decisions` tool's `id`, the Decisions
page's Find box, `/decisions/<number>`); anywhere else a number is a task's.

**The number is the only name.** The handles of 8 to 18 October 2026 (a482), and the ids a
background job was given for its ask until 29 October (r24), are not read: anything that is
not a number names no decision (Petar, 29 October 2026: "if we don't need the r24 format, just
get rid of it altogether").

Pure: nothing here touches the database.
"""
from __future__ import annotations

import re

_UNITS = {"zero": 0, "oh": 0, "o": 0, "nought": 0, "one": 1, "two": 2, "three": 3, "four": 4,
          "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9}
_TEENS = {"ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
          "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fourty": 40, "fifty": 50, "sixty": 60,
         "seventy": 70, "eighty": 80, "ninety": 90}

#: Words said around a reference that are not part of it: "decision 42", "number forty-two".
_AROUND = {"decision", "decisions", "number", "no", "nr", "num", "the", "id",
           "question", "approval", "action", "actions"}

#: The largest number read: a reference is never a year or a phone number.
MOST = 10_000_000


def called(number, kind: str = "") -> str:
    """How a decision is named in a sentence and on its page: "Decision 42". An action, a
    hands-on step only the person can do (`rouh/actions.py`), shares the numbers and is called
    "Action 430" (Petar, 7 November 2026: "this is not a decision ... mostly an action")."""
    word = "Action" if kind == "action" else "Decision"
    return f"{word} {number}" if number else word


def short(number) -> str:
    """How a decision is named where there is little room: "#42"."""
    return f"#{number}" if number else ""


def _words(text: str) -> list[str]:
    text = str(text or "").lower().strip()
    # "decision42" is a word and digits, written together.
    text = re.sub(r"(?<=[a-z])(?=\d)|(?<=\d)(?=[a-z])", " ", text)
    return [w for w in re.split(r"[\s\-_.,:;#'\"()]+", text) if w]


def _bare(words: list[str]) -> list[str]:
    while words and words[0] in _AROUND:
        words = words[1:]
    return words


def _spoken(words: list[str]) -> int | None:
    """A number said as one number: "forty two", "one hundred and five", "a thousand and
    six". None when it is not one, as "four two" or "four eighty-two" are not: those are
    said digit by digit (`_digits`)."""
    total, part, seen = 0, 0, False
    for i, w in enumerate(words):
        if w == "and" and seen:
            continue
        if w in _UNITS:
            if part % 10:
                return None
            part += _UNITS[w]
        elif w in _TEENS or w in _TENS:
            if part % 100:
                return None
            part += _TEENS.get(w) or _TENS[w]
        elif w == "hundred" and seen and part % 100 == part and part:
            part *= 100
        elif w == "thousand" and seen and (part or total == 0):
            total += (part or 1) * 1000
            part = 0
        elif w == "a" and not seen and i + 1 < len(words) and words[i + 1] in ("hundred", "thousand"):
            part = 1
        else:
            return None
        seen = True
    return total + part if seen else None


def _digits(words: list[str]) -> str | None:
    """Spoken or written digits, one after another, as a string of digits: "4 8 2",
    "four eight two", "482", "four eighty-two". None when anything in it is not a number."""
    out = ""
    i = 0
    while i < len(words):
        w = words[i]
        if w.isdigit():
            out += w
            i += 1
            continue
        if w in _UNITS:
            unit = _UNITS[w]
            if i + 1 < len(words) and words[i + 1] == "hundred":
                i += 2
                if i < len(words) and words[i] == "and":
                    i += 1
                rest, i = _below_hundred(words, i)
                out += f"{unit * 100 + (rest or 0):03d}"
                continue
            out += str(unit)
            i += 1
            continue
        if w in _TEENS or w in _TENS:
            n, i = _below_hundred(words, i)
            out += f"{n:02d}"
            continue
        return None
    return out or None


def _below_hundred(words: list[str], i: int) -> tuple[int | None, int]:
    """A number under a hundred at `i` ("eighty two", "twelve", "seven"), and where it ends."""
    if i >= len(words):
        return None, i
    w = words[i]
    if w.isdigit() and len(w) <= 2:
        return int(w), i + 1
    if w in _TEENS:
        return _TEENS[w], i + 1
    if w in _TENS:
        n = _TENS[w]
        if i + 1 < len(words) and words[i + 1] in _UNITS and _UNITS[words[i + 1]]:
            return n + _UNITS[words[i + 1]], i + 2
        return n, i + 1
    if w in _UNITS:
        return _UNITS[w], i + 1
    return None, i


def read(text) -> int | None:
    """The decision number a reference names, however it was said or typed, or None when it
    names none: "42", "#42", "decision 42", "forty-two", "one hundred and five", "four two".
    The reference is the whole of `text`; letters and digits (a482, r24) are not a number."""
    if isinstance(text, bool):
        return None
    if isinstance(text, int):
        return text if 0 < text < MOST else None
    words = _bare(_words(text))
    if not words:
        return None
    if all(w.isdigit() for w in words):
        n = int("".join(words))
    else:
        # Said as one number ("forty two"), or digit by digit ("four two").
        n = _spoken(words)
        if n is None:
            got = _digits(words)
            n = int(got) if got else None
    return n if n is not None and 0 < n < MOST else None
