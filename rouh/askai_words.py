"""Where your words are: words quoted to Ask AI are found on the page before it changes anything.

Built by the nightly feature run, night 25, 28 October 2026 (task 94, idea I-153). On the company
site's page (task 61), a long page that holds every page of the site, the writer names the part
they mean by quoting its words, often cut short: "In the "Scale doesn't get easier.." section",
"Change the "One map.." section", "In the "Built for large organizations.." section". On 27
October the same thread also said "Confirm you understand what I am referencing before beginning
any changes" and "Stop and ask questions when needed if you are confused", and one change the
night before went to the wrong page of the site. Ask AI reads the page's source on every turn,
but finding which of several places a phrase is in, and that "Scale doesn't get easier.." is the
heading "Scale doesn't make this easier.", is left to the model, on a page of some hundred
thousand characters.

So, while its switch is on, a question to Ask AI from a reader who may change the page, with words
in double quotes, gets one more block at the end of its turn (`note`): for each quoted phrase
found on the page as it is now, how many places it is in, and for each the heading it is under
and the part of the page it is in (the nearest element with an id); a phrase cut short with ".."
that is not on the page word for word is given the heading nearest to it. When a phrase is in
more than one place, the block says to ask which before changing anything. Quoted words that are
nowhere on the page, such as new copy, are left out, so nothing is asked about them.

**No model call of its own.** The block is words in the turn Ask AI was going to send anyway,
after the question, so the cached system prompt is never changed.

**Whose.** The page the reader is on, which the caller has already checked they may change; the
block reads the page and nothing else.

**Its switch** is `askai_words` (`rouh/switches.py`): off, every turn is sent exactly as before.
"""
from __future__ import annotations

import difflib
import html
import logging
import re

log = logging.getLogger("rouh.askai_words")

#: The gene's switch (`rouh/switches.py`).
SWITCH = "askai_words"
TITLE = ("Where your words are: words you quote to Ask AI are found on the page first, and it "
         "asks which you mean when they are in more than one place")
#: The most phrases read out of one question, and places named for one phrase.
PHRASES_MOST, PLACES_MOST = 6, 5
#: How alike a cut-short phrase and a heading must be to be offered as the nearest.
NEAR_ENOUGH = 0.72

_QUOTED = re.compile(r"[\"“”„]([^\"“”„\n]{2,160}?)[\"“”]")
_SKIP = re.compile(r"<(script|style|template|svg)\b.*?</\1\s*>|<!--.*?-->", re.I | re.S)
_TAG = re.compile(r"<[^>]*>")
_HEADING = re.compile(r"<h([1-6])\b[^>]*>(.*?)</h\1\s*>", re.I | re.S)
_ID = re.compile(r"""\b(?:id|data-page)\s*=\s*["']([^"']{1,80})["']""", re.I)
_CUT = re.compile(r"(?:\.\.+|…)\s*$")
_FOLD = str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"', "–": "-", "—": "-",
                       " ": " "})


def on(who) -> bool:
    from . import switches

    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def _fold(text: str) -> str:
    return " ".join(str(text or "").translate(_FOLD).lower().split())


def phrases(question: str) -> list[tuple[str, bool]]:
    """The quoted phrases in a question, each with whether it was cut short (".." at its end)."""
    out: list[tuple[str, bool]] = []
    for m in _QUOTED.finditer(str(question or "")):
        raw = m.group(1).strip()
        cut = bool(_CUT.search(raw))
        words = _CUT.sub("", raw).strip(" ,;:")
        if len(words.split()) < 2 or any(_fold(words) == _fold(w) for w, _ in out):
            continue
        out.append((words, cut))
        if len(out) >= PHRASES_MOST:
            break
    return out


def _reading(source: str) -> tuple[str, list[int]]:
    """The page's words as a reader sees them, folded, and where in the source each character is."""
    text, at = [], []
    pos, spaced = 0, True
    blanked = _SKIP.sub(lambda m: " " * len(m.group(0)), source)
    for m in _TAG.finditer(blanked + "<>"):
        piece = html.unescape(blanked[pos:m.start()]).translate(_FOLD).lower()
        for ch in piece:
            if ch.isspace():
                if not spaced:
                    text.append(" ")
                    at.append(pos)
                    spaced = True
                continue
            text.append(ch)
            at.append(pos)
            spaced = False
        if not spaced:
            text.append(" ")
            at.append(m.start())
            spaced = True
        pos = m.end()
    return "".join(text), at


def _headings(source: str) -> list[tuple[int, int, str]]:
    from .askai_follow import words_of

    return [(m.start(), m.end(), words_of(m.group(2))[:160]) for m in _HEADING.finditer(source)]


def _place(source: str, spans, heads, offset: int) -> dict:
    """The heading a point of the page is under, or in, and the nearest part of it with an id."""
    heading = ""
    for start, end, words in heads:
        if start > offset:
            break
        heading = words
    part = ""
    for start, end, name in spans:
        if start > offset:
            break
        if end > offset and name not in ("html", "head", "body"):
            got = _ID.search(source[start:source.find(">", start) + 1])
            if got:
                part = got.group(1)
    return {"heading": heading, "part": part}


def find(source: str, question: str) -> list[dict]:
    """Each quoted phrase of the question that is on the page, or cut short and near a heading.

    ``[{"said", "places": [{"heading", "part"}], "count", "nearest"}]``; a phrase that is
    nowhere on the page and was not cut short is left out. Never raises."""
    from . import pages

    out: list[dict] = []
    try:
        asked = phrases(question)
        if not asked or not source:
            return []
        text, at = _reading(source)
        spans = pages.element_spans(source)
        heads = _headings(source)
        for said, cut in asked:
            want = _fold(said)
            # A heading the words name is the part meant: "One map.." is the section whose
            # heading starts so, not every paragraph that says "one map".
            named = [(start, words) for start, _e, words in heads
                     if (_fold(words).startswith(want) if cut else want in _fold(words))]
            if named:
                places = []
                for start, words in named:
                    place = dict(_place(source, spans, heads, start), heading=words)
                    if place not in places:
                        places.append(place)
                out.append({"said": said + (".." if cut else ""), "count": len(named),
                            "places": places[:PLACES_MOST], "nearest": ""})
                continue
            hits, start = [], text.find(want)
            while start >= 0:
                hits.append(at[start])
                start = text.find(want, start + max(1, len(want)))
            if hits:
                places = []
                for offset in hits:
                    place = _place(source, spans, heads, offset)
                    if place not in places:
                        places.append(place)
                out.append({"said": said + (".." if cut else ""), "count": len(hits),
                            "places": places[:PLACES_MOST],
                            "nearest": ""})
                continue
            if not cut:
                continue
            best, score = "", 0.0
            for _s, _e, words in heads:
                folded = _fold(words)
                ratio = difflib.SequenceMatcher(None, want, folded[:len(want) + 12]).ratio()
                if ratio > score:
                    best, score = words, ratio
            if best and score >= NEAR_ENOUGH:
                out.append({"said": said, "count": 0, "places": [], "nearest": best})
    except Exception:  # noqa: BLE001 - the turn is sent without it
        log.exception("quoted words could not be looked for on the page")
        return []
    return out


def _where(place: dict) -> str:
    bits = []
    if place["heading"]:
        bits.append(f"under the heading “{place['heading']}”")
    if place["part"]:
        bits.append(f"in the part of the page with the id “{place['part']}”")
    return ", ".join(bits) or "in the page"


def note(who, source: str, question: str) -> str:
    """The block a turn ends with, or "" (off, no quoted words on the page, or nothing to read)."""
    if who is None or not source or not _QUOTED.search(str(question or "")):
        return ""
    try:
        if not on(who):
            return ""
    except Exception:  # noqa: BLE001 - the turn is sent as it was
        log.exception("the askai_words switch could not be read")
        return ""
    found = find(source, question)
    if not found:
        return ""
    lines, several = [], False
    for f in found:
        if f["nearest"]:
            lines.append(f"- “{f['said']}..” is not on the page word for word. The heading nearest "
                         f"to it is “{f['nearest']}”.")
            continue
        if f["count"] == 1 or len(f["places"]) == 1:
            times = "once" if f["count"] == 1 else f"{f['count']} times, all in one place"
            lines.append(f"- “{f['said']}” is on the page {times}: {_where(f['places'][0])}.")
            continue
        several = True
        named = "; ".join(_where(p) for p in f["places"])
        more = "" if len(f["places"]) >= f["count"] else f" ({f['count']} times in all)"
        lines.append(f"- “{f['said']}” is in {len(f['places'])} places{more}: {named}.")
    ask = ("When quoted words are in more than one place and the reader's other words do not say "
           "which they mean, ask which before changing anything. " if several else "")
    from . import evolution

    evolution.used(SWITCH, "located", who=who,
                   detail=f"found {len(found)} quoted phrase(s) on the page"
                          + (", one in several places" if several else ""))
    return ("<quoted_words>\n"
            "The words the reader put in quotes, found on the page as it is now:\n"
            + "\n".join(lines) + "\n"
            "Change the part the quoted words are in, and no other. " + ask
            + "In your answer, say which part you changed, by its heading.\n"
            "</quoted_words>")


__all__ = ["SWITCH", "TITLE", "find", "note", "on", "phrases"]
