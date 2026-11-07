"""Read terminal input as the words and named keys a person typed."""
from __future__ import annotations

import re

from rouh import worklabel

_KEYS = {
    "\x1b[A": "<Up>", "\x1b[B": "<Down>", "\x1b[C": "<Right>", "\x1b[D": "<Left>",
    "\x1bOA": "<Up>", "\x1bOB": "<Down>", "\x1bOC": "<Right>", "\x1bOD": "<Left>",
    "\x1b[3~": "<Delete>", "\x1b[H": "<Home>", "\x1b[F": "<End>", "\x1b[Z": "<Shift-Tab>",
    "\x1b[5~": "<PageUp>", "\x1b[6~": "<PageDown>",
}
# Every sequence a terminal sends: its parameters may hold any of 0-9 : ; < = > ?,
# so a mouse report, ESC [<35;64;26M, is one sequence and is dropped, not written
# down as <Esc> and letters (15 September). An older terminal's mouse report is
# ESC [M and three bytes. A terminal's answers about itself, ESC ] ... and
# ESC P ..., are dropped too: a browser's terminal sends them by itself (D46).
_ESCAPE = re.compile(r"\x1b(?:\[M[\s\S]{3}|\[[0-?]*[ -/]*[@-~]|O[A-Z]|\[200~|\[201~"
                     r"|\][^\x07\x1b]*(?:\x07|\x1b\\)|P[\s\S]*?\x1b\\)?")


def typed_text(keys: bytes, limit: int = 3000) -> str:
    """What a person typed, as a person would write it down.

    Letters stay letters and Enter starts a new line. Keys that are not
    letters are named: <Esc>, <Up>, <Ctrl-C>. A backspace takes the last letter
    off, the way it did on the screen.
    """
    text = keys.decode("utf-8", "replace").replace("\x1b[200~", "").replace("\x1b[201~", "")
    out: list[str] = []
    i = 0
    while i < len(text):
        if text[i] == "\x1b":
            match = _ESCAPE.match(text, i)
            seq = match.group(0) if match else "\x1b"
            out.append(_KEYS.get(seq, "<Esc>" if seq == "\x1b" else ""))
            i += max(1, len(seq))
            continue
        ch = text[i]
        if ch in "\r\n":
            out.append("\n")
        elif ch in "\x7f\x08":
            if out and len(out[-1]) == 1 and out[-1] != "\n":
                out.pop()
            else:
                out.append("<Backspace>")
        elif ch == "\t":
            out.append("<Tab>")
        elif ord(ch) < 32:
            out.append(f"<Ctrl-{chr(ord(ch) + 64)}>")
        else:
            out.append(ch)
        i += 1
    said = "".join(out).strip("\n")
    said = worklabel.redact(said)
    return said if len(said) <= limit else said[-limit:]

