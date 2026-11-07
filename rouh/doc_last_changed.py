"""Who last changed it: a Google document Rouh reads comes with when it was last changed, and by whom.

Built by the nightly feature run, night 23, 26 October 2026 (task 94, idea I-138). ‹His› company's
site copy is written in Google Docs by an outside writer, and before a meeting with him on
22 October 2026 ‹he› had to ask a chat "can you tell me if task 61 has been updated by him", and a
job went looking, file by file. Every time a chat, a job or Ask AI read one of those documents
with `read_doc`, it was given the words and nothing about them: not whether they were changed an
hour ago or a month ago, nor by whom. A job writing a briefing then had to find that out by itself
(task 61's notes carry "Tom made it at 13:25 UTC on 1 October 2026 and last changed it at 13:31",
looked up by hand).

So, while its switch is on, whatever reads a file through `read_doc` (a Google Doc, Sheet, Slides
deck or any file Drive can read out) is told, on the line under its title, when the file was last
changed, on ‹his› clock, how long ago that was, and who changed it, as Drive's own
`lastModifyingUser` says. One Drive call more, of a few fields, and no model.

**Whose.** The Google connection of whoever is speaking (`google.person()`, by `org_id` and
`user_id`); nothing is written anywhere.

**Its switch** is `doc_last_changed` (`rouh/switches.py`): off, `read_doc` says what it said before.
"""
from __future__ import annotations

import logging
import time

log = logging.getLogger("rouh.doc_last_changed")

SWITCH = "doc_last_changed"


def on(who) -> bool:
    from . import switches

    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def _ago(seconds: float) -> str:
    seconds = max(0.0, seconds)
    if seconds < 120:
        return "just now"
    minutes = int(seconds // 60)
    if minutes < 90:
        return f"{minutes} minutes ago"
    hours = int(round(seconds / 3600))
    if hours < 36:
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    days = int(round(seconds / 86400))
    if days < 60:
        return f"{days} days ago"
    months = int(round(days / 30.4))
    return f"about {months} months ago"


def said(change: dict, *, now: float | None = None, zone=None) -> str:
    """The line put under a file's title, or "" when Drive gave no time."""
    from . import clock

    at = clock.parse_utc(change.get("at") or "")
    if at is None:
        return ""
    zone = zone or clock.zone()
    here = at.astimezone(zone)
    when = (f"{here:%A} {here.day} {here:%B %Y} at {here:%H:%M} ({clock.place(zone)} time), "
            f"{_ago((now or time.time()) - at.timestamp())}")
    if change.get("me"):
        by = "by this Google account itself (Rouh's own)"
    elif change.get("who") and change.get("email"):
        by = f"by {change['who']} ({change['email']})"
    elif change.get("who") or change.get("email"):
        by = f"by {change.get('who') or change.get('email')}"
    else:
        by = "by somebody Drive does not name"
    return f"Last changed {when}, {by}."


async def line(google, file_id: str) -> str:
    """The line to put under a file's title when the switch is on, or ""."""
    import asyncio

    who = google.person()
    if who is None or not file_id or not await asyncio.to_thread(on, who):
        return ""
    try:
        change = await google.services().drive.last_change(file_id)
    except Exception as exc:  # noqa: BLE001 - the words are read whether or not their date is
        log.info("when %s was last changed could not be read: %r", file_id, exc)
        return ""
    out = said(change)
    if out:
        from . import evolution

        await asyncio.to_thread(evolution.used, SWITCH, "read", who=who,
                                detail="told who last changed a document it read")
    return out


__all__ = ["SWITCH", "line", "on", "said"]

