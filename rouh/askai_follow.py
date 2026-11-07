"""Follow-ups stay where you were: after Ask AI changes a page, the next words are read as being
about the part it just changed.

Built by the nightly feature run, night 24, 27 October 2026 (task 94, idea I-145). On 26 October
2026, on the company site's page (task 61), Ask AI was asked to put new copy in the "One map, not
a black box." section and stretch its illustration across the page, and did. The next words were
"Great but the height of the process is half the size, same width", and Ask AI halved the four
process boxes of another page of the site, which also has a "process" in it. Its answer said what
it changed but not where, and the writer asked "Wait what did you change? I meant the box below
"One map.." copy, not sure what section you changed". Ask AI's follow-up turns carry the thread's
words and the page as it is now, but nothing says which part of the page the last change was in:
the model has to work it out again from its own summary, and a word like "the process" matches
more than one part of a long page.

So, while its switch is on, one thing changes, and nothing is drawn on any screen: a question in
a thread whose last change to the page still stands gets one more block at the end of its turn
(`note`): where that change was, by the heading above it and the words it now has there, and
that words which name no part of the page ("it", "that box", "great, but") mean that part, and
that the answer says by its heading which part it changed. Where a change is (`where`) is found
from the page as the change left it, by code: the element it touched, the heading it is under,
and its own words as a reader sees them. Show me where (`rouh/askai_show.py`) uses the same.

**No model call of its own.** The block is words in the turn Ask AI was going to send anyway,
after the question, so the cached system prompt is never changed.

**Whose.** The thread's own change (`AskEdit`, by the reader's `user_id` and `org_id`, the page
and the thread), read only.

**Its switch** is `askai_follow` (`rouh/switches.py`): off, every turn is sent exactly as before.
"""
from __future__ import annotations

import html
import json
import logging
import re

log = logging.getLogger("rouh.askai_follow")

#: The gene's switch (`rouh/switches.py`).
SWITCH = "askai_follow"
TITLE = ("Follow-ups stay where you were: after Ask AI changes a page, words like \"it\" or "
         "\"great, but\" are read as being about the part it just changed")
#: The most of a changed part's own words carried, in characters.
WORDS_MOST = 220

_HEADING = re.compile(r"<h([1-6])\b[^>]*>(.*?)</h\1\s*>", re.I | re.S)
_HIDDEN = re.compile(r"<(script|style|template|svg)\b.*?</\1\s*>|<!--.*?-->", re.I | re.S)
_TAG = re.compile(r"<[^>]+>")


def on(who) -> bool:
    from . import switches

    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def words_of(source: str) -> str:
    """Markup as a reader sees its words: scripts, styles and tags out, entities read, spaces one."""
    text = _TAG.sub(" ", _HIDDEN.sub(" ", str(source or "")))
    return " ".join(html.unescape(text).split())


def _changed_at(before: str, after: str) -> tuple[int, int]:
    """Where in ``after`` the two first and last differ, as (start, end)."""
    same, most = 0, min(len(before), len(after))
    while same < most and before[same] == after[same]:
        same += 1
    tail = 0
    while tail < most - same and before[-1 - tail] == after[-1 - tail]:
        tail += 1
    return same, max(same, len(after) - tail)


def where(before: str, after: str, parts=None) -> dict:
    """Where one change to a page is, in the page as it left it.

    ``{"tag", "text", "nth", "heading"}``: the element it touched, its own words as a reader sees
    them (cut to `WORDS_MOST`), which of the elements of that tag with those same words it is,
    counted from the top from 0, and the heading it is under, or in. Empty strings where a thing
    cannot be found; never raises."""
    from . import pages

    out = {"tag": "", "text": "", "nth": 0, "heading": ""}
    try:
        if isinstance(parts, str):
            parts = json.loads(parts) if parts else []
        if parts:
            first = min(parts, key=lambda p: int(p.get("at") or 0))
            start = int(first.get("at") or 0)
            end = start + len(str(first.get("after") or ""))
        else:
            start, end = _changed_at(before, after)
        spans = pages.element_spans(after)
        found = pages.enclosing(spans, start + 1, end)
        if found is not None and found[2] not in ("html", "head", "body"):
            lo, hi, tag = found
            text = words_of(after[lo:hi])
            out["tag"] = tag
            out["text"] = text[:WORDS_MOST]
            if text:
                out["nth"] = sum(1 for s, e, name in spans
                                 if name == tag and s < lo and words_of(after[s:e]) == text)
        inside = _HEADING.search(after, start, max(start, end))
        above = None
        for m in _HEADING.finditer(after, 0, start):
            above = m
        found_h = inside or above
        if found_h is not None:
            out["heading"] = words_of(found_h.group(2))[:160]
    except Exception:  # noqa: BLE001 - a turn is sent without it
        log.exception("where a change to a page was could not be read")
    return out


def last_change(who, doc: str, thread_id) -> dict | None:
    """The thread's last change to this page that still stands, with where it is, or None."""
    from .models import AskEdit

    try:
        row = (AskEdit.objects
               .filter(thread_id=int(thread_id), user_id=who.user_id, org_id=who.org_id,
                       doc=doc, kind="", undone_at__isnull=True)
               .order_by("-id").values("id", "summary", "before", "after", "parts").first())
    except (TypeError, ValueError):
        return None
    if not row:
        return None
    return dict(where(row["before"], row["after"], row["parts"]),
                edit=int(row["id"]), summary=row["summary"] or "")


def note(who, doc: str, thread_id, can_edit: bool) -> str:
    """The block a follow-up turn ends with, or "" (off, nothing to say, or the page cannot be
    changed by this reader)."""
    if not can_edit or not thread_id or who is None:
        return ""
    try:
        if not on(who):
            return ""
        got = last_change(who, doc, thread_id)
    except Exception:  # noqa: BLE001 - the turn is sent as it was
        log.exception("the last change in an Ask AI thread could not be read")
        return ""
    if not got or not (got["heading"] or got["text"]):
        return ""
    place = (f"in the part of the page under the heading “{got['heading']}”"
             if got["heading"] else "in one part of the page")
    now = f", where it now reads: “{got['text']}”" if got["text"] else ""
    said = f" ({got['summary']})" if got["summary"] else ""
    from . import evolution

    evolution.used(SWITCH, "followed", who=who,
                   detail=f"told Ask AI its last change was under {got['heading'] or 'the page'}")
    return ("<last_change>\n"
            f"Your last change to this page in this conversation{said} was {place}{now}.\n"
            "When the reader's words do not name the part of the page they mean (\"it\", "
            "\"that box\", \"the process\", \"great, but ...\"), they mean the part you just "
            "changed: change that part. Change another part only when they name it, and if "
            "you cannot tell, ask which they mean. In your answer, say which part of the page "
            "you changed, by its heading.\n"
            "</last_change>")


__all__ = ["SWITCH", "TITLE", "last_change", "note", "on", "where", "words_of"]
