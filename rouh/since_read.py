"""Since you last read it: when a page has changed since its owner last saw it, a button that says what.

Built by the nightly feature run, night 18, 21 October 2026 (task 94, idea I-110), as one more tool
for Ask AI on a page, `changed_since_read`, that answered "what changed since I last read this?".
Petar, 27 October 2026, asking it to change (mutation request 5): "This don't work from user
experience point. I would never think of writing that, I am blind. What maybe would work is to
track if anything has changed since I last saw it, and if yes, then show me a button that would
generate those changes. I done want this generation of summary to happen in advance. Also in order
for this to happen, that means you save a version each time I visit in the database, which I guess
is cheap enough".

So this is version 2, and it works the way Google Docs' "See new changes" does:

- **Every visit is kept.** Each time the owner opens a page of the workspace on Rouh's canvas, its
  words are kept in a `PageRead` row (`page_reads`), one row a visit: opens closer together than
  `VISIT_GAP` are one visit, and its row is brought up to date at each of them, so it holds the
  page as it was the last time they had it in front of them (`seen`).
- **A button only when it changed.** When the words now differ from the visit before this one, the
  canvas bar shows **What changed** (`whatChangedTouch` in runs.js). A change to the page's look
  alone is not a change. With no earlier visit, or nothing changed, there is no button.
- **Nothing made in advance.** Pressing it asks the page's Ask AI, in the column beside the page,
  "What changed since I last saw this page?", with the passages added and taken out since that
  visit and the saves made in between (`note`). The answer is Ask AI's own, in that one turn: no
  model call of this gene's own, and none before the press.

The tool of version 1 is gone: it waited for a question nobody would think to ask.
`opens` and `last_read`, which read the owner's opens of a page from the event log, stay, for the
genes that use them (`rouh/others_changed.py`, `rouh/task_docs.py`).

**Whose.** Only the owner's own visits, by `org_id` and `user_id`, and only for the owner, who is
the one reading a page on Rouh's canvas.

**Its switch** is `since_read` (`rouh/switches.py`): off, no visit is kept and there is no button.
"""
from __future__ import annotations

import difflib
import hashlib
import html as html_module
import logging
import re
import time
from html.parser import HTMLParser

log = logging.getLogger("rouh.since_read")

SWITCH = "since_read"
#: Opens closer together than this are one visit: the visit the reader is on now is not "last".
VISIT_GAP = 30 * 60
#: How far back an earlier read is looked for in the event log (`opens`).
LOOK_BACK_DAYS = 120
#: The most passages added, and taken out, handed to Ask AI; and the longest passage.
MOST_PASSAGES = 40
PASSAGE_MOST = 400
#: The most of a page's words kept for one visit.
MOST_TEXT = 400_000
#: The visits kept of one page; older ones are let go.
VISITS_KEPT = 30
#: What the button asks, as the owner would.
QUESTION = "What changed since I last saw this page?"

def on(org_id=None) -> bool:
    from . import switches

    return switches.on(SWITCH, org_id or None)


def _names_for(doc: str) -> list[str]:
    """The object ids an open of this page is logged under (`events.place_of`)."""
    doc = doc.strip("/")
    names = [doc]
    if doc.endswith("/index.html"):
        names.append(doc[: -len("/index.html")])
    return names


def opens(who, doc: str, *, now: float | None = None) -> list[float]:
    """When the reader opened this page, newest first, over the last `LOOK_BACK_DAYS`."""
    from django.db import connection

    now = now or time.time()
    with connection.cursor() as cur:
        cur.execute(
            "SELECT extract(epoch FROM occurred_at) FROM analytics.event "
            "WHERE org_id = %s AND user_id = %s AND name = 'ui.open' "
            "AND object_id = ANY(%s) AND occurred_at > to_timestamp(%s) "
            "ORDER BY occurred_at DESC LIMIT 500",
            [str(who.org_id), str(who.user_id), _names_for(doc),
             now - LOOK_BACK_DAYS * 86400])
        return [float(row[0]) for row in cur.fetchall()]


def last_read(times: list[float], now: float) -> float | None:
    """The last open before the visit going on now, from `opens`, or None.

    The visit now is every open that follows the one before it within `VISIT_GAP`, going back
    from `now`; the open before that visit is the last read.
    """
    edge = now
    for at in times:
        if edge - at <= VISIT_GAP:
            edge = at
            continue
        return at
    return None


class _Text(HTMLParser):
    """A page's words, one block (heading, paragraph, item, cell) a line."""

    BLOCKS = {"p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "td", "th", "tr", "div",
              "section", "article", "blockquote", "pre", "dt", "dd", "figcaption", "br",
              "summary", "caption"}
    SKIP = {"script", "style", "noscript", "template", "svg", "head"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.lines: list[str] = []
        self._now: list[str] = []
        self._skip = 0

    def _flush(self):
        said = " ".join("".join(self._now).split())
        if said:
            self.lines.append(said)
        self._now = []

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        elif tag in self.BLOCKS:
            self._flush()

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self._skip = max(0, self._skip - 1)
        elif tag in self.BLOCKS:
            self._flush()

    def handle_data(self, data):
        if not self._skip:
            self._now.append(data)


def text_of(markup: str) -> list[str]:
    """The page's words as lines, for comparing two versions of it."""
    if not re.search(r"<[a-zA-Z!/]", markup or ""):
        return [" ".join(line.split()) for line in (markup or "").splitlines() if line.strip()]
    parser = _Text()
    try:
        parser.feed(markup or "")
        parser.close()
    except Exception:  # noqa: BLE001 - a page that does not parse is compared as it reads
        return [html_module.unescape(markup or "")]
    parser._flush()
    return parser.lines


def compare(before: list[str], after: list[str]) -> tuple[list[str], list[str]]:
    """The passages added and the passages taken out, in page order."""
    added, gone = [], []
    for op, a1, a2, b1, b2 in difflib.SequenceMatcher(None, before, after,
                                                       autojunk=False).get_opcodes():
        if op in ("replace", "delete"):
            gone += before[a1:a2]
        if op in ("replace", "insert"):
            added += after[b1:b2]
    return added, gone


def _cut(line: str) -> str:
    return line if len(line) <= PASSAGE_MOST else line[:PASSAGE_MOST - 1].rstrip() + "…"


def _when(at: float) -> str:
    from . import clock

    dt = clock.moment(at)
    return f"{dt:%a} {dt.day} {dt:%b}, {dt:%H:%M}" if dt else "an unknown time"


def _whose(who) -> dict:
    return {"org_id": str(who.org_id), "user_id": str(who.user_id)}


def _words(page) -> tuple[str, str]:
    """The page's words, one block a line, and their digest."""
    text = "\n".join(text_of(page.read_text("utf-8", "replace")))[:MOST_TEXT]
    return text, hashlib.sha256(text.encode("utf-8")).hexdigest()


def _visits(who, doc: str, now: float):
    """(the visit going on now or None, the visit before it or None)."""
    from .models import PageRead

    rows = list(PageRead.objects.filter(**_whose(who), rel=doc).order_by("-seen_at")[:2])
    if rows and now - rows[0].seen_at <= VISIT_GAP:
        return rows[0], (rows[1] if len(rows) > 1 else None)
    return None, (rows[0] if rows else None)


def seen(who, page, doc: str, *, now: float | None = None) -> dict:
    """The owner has `doc` open on the canvas: keep this visit, and say whether the page changed
    since the visit before it, for the button. Nothing at all while the switch is off."""
    from .models import PageRead

    if who is None or not on(getattr(who, "org_id", None)):
        return {"on": False}
    now = now or time.time()
    text, fp = _words(page)
    current, before = _visits(who, doc, now)
    started = current is None
    if started:
        current = PageRead.objects.create(**_whose(who), rel=doc, text=text, fp=fp,
                                          first_at=now, seen_at=now)
        old = list(PageRead.objects.filter(**_whose(who), rel=doc)
                   .order_by("-seen_at").values_list("id", flat=True)[VISITS_KEPT:])
        if old:
            PageRead.objects.filter(**_whose(who), id__in=old).delete()
    else:
        PageRead.objects.filter(**_whose(who), id=current.id).update(text=text, fp=fp, seen_at=now)
    changed = bool(before and before.fp != fp and not current.told_at)
    if changed and started:
        from . import evolution

        evolution.used(SWITCH, "offered", who=who, detail=f"{doc}: changed since {_when(before.seen_at)}")
    return {"on": True, "changed": changed,
            "since": before.seen_at if before else None,
            "when": _when(before.seen_at) if before else ""}


def _saves(root, org_id: str, doc: str, markup: str, since: float) -> list[str]:
    """Each change saved to the page after `since`, newest first, as a line: when, who, what."""
    from . import pagehistory

    try:
        entries = pagehistory.history(root, org_id, doc, markup)
    except Exception:  # noqa: BLE001 - the passages say what changed without them
        log.exception("since read: no history for %s", doc)
        return []
    return [f"- {_when(e.get('at') or 0)}, {e.get('who') or 'Somebody'}: "
            f"{e.get('summary') or 'a change'}"
            for e in entries if (e.get("at") or 0) > since and e.get("kind") != "start"][:20]


def note(cfg, who, page, doc: str, *, now: float | None = None) -> str:
    """What the question from What changed carries for Ask AI: the passages added and taken out
    since the visit before this one, and the saves in between. The press is a use. "" while the
    switch is off, and a plain line when there is nothing to compare with."""
    from . import evolution
    from .models import PageRead

    if who is None or not on(getattr(who, "org_id", None)):
        return ""
    now = now or time.time()
    try:
        current, before = _visits(who, doc, now)
        if before is None:
            return ("\n\n<since_last_seen>There is no earlier visit to this page on record, so "
                    "say that nothing can be compared yet.</since_last_seen>")
        markup = page.read_text("utf-8", "replace")
        added, gone = compare(before.text.splitlines(), text_of(markup))
        saves = _saves(cfg.assistant_repo, str(who.org_id), doc, markup, before.seen_at)
        if current is not None:
            PageRead.objects.filter(**_whose(who), id=current.id).update(told_at=now)
    except Exception:  # noqa: BLE001 - Ask AI is told and answers without it
        log.exception("since read: could not compare %s", doc)
        return ("\n\n<since_last_seen>What changed could not be worked out just now. Say so."
                "</since_last_seen>")
    evolution.used(SWITCH, "pressed", who=who,
                   detail=f"{doc}: {len(added)} added, {len(gone)} taken out since {_when(before.seen_at)}")
    lines = ["", "", "<since_last_seen>",
             f"The reader last saw this page on {_when(before.seen_at)}. Say what changed on it "
             "since then, in plain words, most important first, and stop. Say plainly when "
             "nothing in its words changed."]
    if saves:
        lines += ["", f"Changes saved since then, newest first ({len(saves)}):"] + saves
    if not added and not gone:
        lines += ["", "Its words read the same as then."]
    if added:
        lines += ["", f"Passages added or rewritten ({len(added)}):"]
        lines += [f"+ {_cut(one)}" for one in added[:MOST_PASSAGES]]
        if len(added) > MOST_PASSAGES:
            lines.append(f"... and {len(added) - MOST_PASSAGES} more.")
    if gone:
        lines += ["", f"Passages taken out or replaced ({len(gone)}):"]
        lines += [f"- {_cut(one)}" for one in gone[:MOST_PASSAGES]]
        if len(gone) > MOST_PASSAGES:
            lines.append(f"... and {len(gone) - MOST_PASSAGES} more.")
    lines.append("</since_last_seen>")
    return "\n".join(lines)


__all__ = ["QUESTION", "SWITCH", "compare", "last_read", "note", "on", "opens", "seen",
           "text_of"]
