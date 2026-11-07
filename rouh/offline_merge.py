"""Merging a page edited offline with the same page changed on the server meanwhile.

Petar, 12 October 2026 (card 1457): "Text edits made offline to workspace pages merge with
server-side changes when they do not overlap. Only real clashes come to Petar as decisions."

So this is a three-way merge by lines, the way version control does it: the text the device
started from (`base`), what the person made of it offline (`mine`), and what the page is on the
server now (`theirs`). Each side's changes are found against the base; changes that touch
different lines are both kept; a change made the same way on both sides is kept once; and two
different changes to the same lines, or to lines touching each other, are a clash, which is
handed back with both versions rather than guessed at. Nothing here writes anything.
"""
from __future__ import annotations

import difflib
from dataclasses import dataclass, field


@dataclass
class Merged:
    """What a merge came to: the merged text, or the places the two sides clash."""

    ok: bool
    text: str = ""
    #: Each clash as the base lines and both sides' versions of them.
    clashes: list[dict] = field(default_factory=list)


def _hunks(base: list[str], other: list[str]) -> list[tuple[int, int, list[str]]]:
    """Every change from base to other, as (start, end) in the base and the lines put there."""
    sm = difflib.SequenceMatcher(a=base, b=other, autojunk=False)
    return [(i1, i2, other[j1:j2]) for tag, i1, i2, j1, j2 in sm.get_opcodes() if tag != "equal"]


def _apply(base: list[str], lo: int, hi: int, hunks: list[tuple[int, int, list[str]]]) -> list[str]:
    """base[lo:hi] with the given hunks, all inside it, applied."""
    out, at = [], lo
    for i1, i2, lines in sorted(hunks, key=lambda h: (h[0], h[1])):
        out.extend(base[at:i1])
        out.extend(lines)
        at = i2
    out.extend(base[at:hi])
    return out


def merge(base: str, mine: str, theirs: str) -> Merged:
    """Three-way merge of whole texts, by lines."""
    if mine == theirs:
        return Merged(True, mine)
    if theirs == base:
        return Merged(True, mine)
    if mine == base:
        return Merged(True, theirs)
    b = base.splitlines(keepends=True)
    m = mine.splitlines(keepends=True)
    t = theirs.splitlines(keepends=True)
    tagged = sorted([(h, "m") for h in _hunks(b, m)] + [(h, "t") for h in _hunks(b, t)],
                    key=lambda x: (x[0][0], x[0][1]))
    # Group the changes into runs that overlap in the base. Two changes on neighbouring lines
    # are two places and both are kept; two insertions at the very same point are one place,
    # because which goes first is a guess.
    groups: list[list[tuple[tuple[int, int, list[str]], str]]] = []
    hi = -1
    last: tuple[int, int] = (-1, -1)
    for item in tagged:
        (i1, i2, _), _side = item
        both_insert = i1 == i2 == hi and last[0] == last[1] == hi
        if groups and (i1 < hi or both_insert):
            groups[-1].append(item)
            hi = max(hi, i2)
        else:
            groups.append([item])
            hi = i2
        last = (i1, i2)
    out: list[str] = []
    clashes: list[dict] = []
    at = 0
    for group in groups:
        lo = min(h[0] for h, _ in group)
        top = max(h[1] for h, _ in group)
        out.extend(b[at:lo])
        sides = {s for _, s in group}
        mine_part = _apply(b, lo, top, [h for h, s in group if s == "m"])
        theirs_part = _apply(b, lo, top, [h for h, s in group if s == "t"])
        if sides == {"m"}:
            out.extend(mine_part)
        elif sides == {"t"}:
            out.extend(theirs_part)
        elif mine_part == theirs_part:
            out.extend(mine_part)
        else:
            clashes.append({"line": lo + 1, "base": "".join(b[lo:top]),
                            "mine": "".join(mine_part), "theirs": "".join(theirs_part)})
            out.extend(theirs_part)
        at = top
    out.extend(b[at:])
    if clashes:
        return Merged(False, "", clashes)
    return Merged(True, "".join(out))
