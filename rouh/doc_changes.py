"""What changed in a Google Doc since a day: the words added, taken out and changed, who changed
them, and the comments made since, read from Drive's own versions.

Built by the nightly feature run, night 20, 23 October 2026 (task 94, idea I-119). Preparing for a
client's meeting on 22 October 2026, ‹he› pasted three of the client's Google Docs into a chat and
asked Rouh to "look at changes" in them; ‹his› work tasks link Google Docs by the dozen (one task
of ‹his› links fifteen). Rouh could read a document only as it is now (`read_doc`): which words
are new since the last meeting, who wrote them and what the comments say was beyond it, so the
request went to a job that wrote scripts against Drive for twenty minutes, and the reading of the
two later documents was lost on the way.

So, while its switch is on, Rouh has the tool `doc_changes`: "what changed in Tom's site plan since
the 15th" reads the document's saved versions in Drive (`Drive.revisions`), takes the version
saved last before that day and the document as it is now, and says, by plain comparison in code
with no model call of its own:

- who saved changes since then, and when;
- each paragraph added, taken out or changed, in the document's own words;
- every comment made or answered since then, with the words it is on, whether it is resolved,
  and its replies.

**Whose.** The documents the connected Google account can open, as `read_doc` reads them. It reads
and changes nothing.

**Its switch** is `doc_changes` (`rouh/switches.py`): off, the tool says so and reads nothing.
"""
from __future__ import annotations

import asyncio
import difflib
import logging
import re
from collections import Counter
from datetime import datetime, timedelta, timezone

log = logging.getLogger("rouh.doc_changes")

SWITCH = "doc_changes"
#: Left without a day, the changes of the last week.
DEFAULT_DAYS = 7
#: The most paragraphs said, the longest each is said, and the most said in all.
MOST_PARTS = 40
PART_CHARS = 500
MOST_CHARS = 14000
MOST_COMMENTS = 30


def on(who) -> bool:
    from . import switches

    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def _when(value: str) -> datetime | None:
    value = str(value or "").strip()
    if not value:
        return None
    try:
        at = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return at if at.tzinfo else at.replace(tzinfo=timezone.utc)


def since_from(given: str, now: datetime | None = None) -> datetime:
    """The moment to compare from: a day or a moment as given, or a week ago."""
    from . import clock

    now = now or clock.now()
    text = str(given or "").strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        day = datetime.fromisoformat(text)
        return day.replace(tzinfo=now.tzinfo)
    at = _when(text)
    return at if at is not None else now - timedelta(days=DEFAULT_DAYS)


def _said(at: datetime | None) -> str:
    from . import clock

    if at is None:
        return "an unknown time"
    here = at.astimezone(clock.now().tzinfo)
    return f"{here.day} {here:%B %Y}, {here:%H:%M}"


def _clip(text: str, most: int = PART_CHARS) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= most else text[: most - 1].rstrip() + "…"


def _paragraphs(text: str) -> list[str]:
    return [" ".join(line.split()) for line in str(text or "").replace("\r", "").split("\n")
            if line.strip()]


def compare(before: str, after: str) -> list[str]:
    """Each paragraph added, taken out or changed between two texts, in their own words."""
    old, new = _paragraphs(before), _paragraphs(after)
    out: list[str] = []
    for op, a1, a2, b1, b2 in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        if op == "equal":
            continue
        gone, came = old[a1:a2], new[b1:b2]
        if op == "replace" and len(gone) == len(came):
            for was, now in zip(gone, came):
                out.append(f"Changed: «{_clip(was)}» became «{_clip(now)}»")
            continue
        out += [f"Taken out: «{_clip(one)}»" for one in gone]
        out += [f"Added: «{_clip(one)}»" for one in came]
    return out


async def changes(google, named: str, since: str = "", *, who=None) -> str:
    """What the doc_changes tool says about one document since a day."""
    from . import evolution

    blocked = google.not_ready_because()
    if blocked:
        return blocked
    said = await read(google.services(), named, since)
    await asyncio.to_thread(evolution.used, SWITCH, "read", who=who,
                            detail="what changed in a Google Doc, asked in a chat")
    return said


async def read(services, named: str, since: str = "") -> str:
    """What changed in one document since a day, read with the connected Google services: the
    tool's words, and a task page's (`rouh/task_docs.py`)."""
    from .tools import _find_doc, _google_trouble

    named = (named or "").strip()
    if not named:
        return "Say which document, by its link, its id or its name in Drive."
    start = since_from(since)
    drive = services.drive
    try:
        file_id, _kind = await _find_doc(drive, named)
        about = await drive.metadata(file_id)
        saved = await drive.revisions(file_id)
        notes = await drive.comments(file_id)
    except Exception as exc:  # noqa: BLE001 - said in the words Google gave
        return _google_trouble(exc)
    for one in saved:
        one["when"] = _when(one["at"])
    saved = [one for one in saved if one["when"] is not None]
    saved.sort(key=lambda one: one["when"])
    lines = [f"{about['name']!r}" + (f" - {about['link']}" if about.get("link") else "")
             + f" - changes since {_said(start)}"]
    later = [one for one in saved if one["when"] > start]
    before = [one for one in saved if one["when"] <= start]
    if not saved:
        lines.append("Drive keeps no saved versions of it that this account can read, so what "
                     "changed cannot be told; only its comments are below.")
    elif not later:
        last = saved[-1]
        lines.append(f"Nothing was saved in it since then. It was last changed on "
                     f"{_said(last['when'])}" + (f" by {last['who']}" if last["who"] else "") + ".")
    else:
        by = Counter(one["who"] or "somebody" for one in later)
        lines.append(f"Saved {len(later)} time{'s' if len(later) != 1 else ''} since then, by "
                     + ", ".join(f"{name} ({count})" for name, count in by.most_common())
                     + f"; the last on {_said(later[-1]['when'])}.")
        try:
            now_text = (await drive.read(file_id)).get("text") or ""
            if before and before[-1]["export"]:
                then_text = await drive.revision_text(before[-1]["export"])
                lines.append(f"Compared with the version saved on {_said(before[-1]['when'])}"
                             + (f" by {before[-1]['who']}" if before[-1]["who"] else "") + ":")
            elif not before:
                then_text = ""
                lines.append("It was made after that day, so all of it is new:")
            else:
                then_text = None
        except Exception as exc:  # noqa: BLE001 - who changed it is still worth saying
            log.info("a version of %s could not be read: %r", file_id, exc)
            then_text = None
        if then_text is None:
            lines.append("Its earlier version could not be read back, so only who changed it is "
                         "known.")
        else:
            parts = compare(then_text, now_text)
            if not parts:
                lines.append("Its words are the same as then: what changed was its look, not its "
                             "text.")
            lines += [f"- {one}" for one in parts[:MOST_PARTS]]
            if len(parts) > MOST_PARTS:
                lines.append(f"- and {len(parts) - MOST_PARTS} more changes; read_doc has the "
                             "whole of it now.")
    fresh = [c for c in notes if (_when(c["changed"]) or _when(c["at"]) or start) > start]
    if fresh:
        lines.append(f"Comments made or answered since then: {len(fresh)}"
                     f" ({sum(1 for c in fresh if not c['resolved'])} open).")
        for c in fresh[:MOST_COMMENTS]:
            line = (f"- {c['who'] or 'Somebody'}, {_said(_when(c['at']))}"
                    + (", resolved" if c["resolved"] else ", open") + f": «{_clip(c['words'])}»")
            if c["on"]:
                line += f" on «{_clip(c['on'], 200)}»"
            for r in c["replies"]:
                line += f"; {r['who'] or 'somebody'} answered «{_clip(r['words'], 300)}»"
            lines.append(line)
    else:
        lines.append("No comment was made or answered since then.")
    text = "\n".join(lines)
    return text if len(text) <= MOST_CHARS else text[: MOST_CHARS - 1] + "…"


__all__ = ["SWITCH", "changes", "compare", "on", "read", "since_from"]
