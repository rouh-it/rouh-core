"""Not put on twice: a meeting already on the calendar at that time is not booked a second time.

Built by the nightly feature run, night 38 of the ledger (9 November 2026, task 94).
Rouh books meetings for ‹owner› from what ‹he› says, from an email, from a forwarded flight, from a
job carried on after a pause. Each of those can ask for something that is already there: the client
sent their own invitation an hour ago, the same flight came in two forwarded emails, a job that was
stopped half way runs its booking again. create_calendar_event made a second event every time, and
with guests Google emailed each of them a second invitation, so the other side saw two meetings and
had to ask which one was real.

So, while its switch is on, before create_calendar_event makes an event, Rouh reads the calendars the
account can see around the time asked (`Calendar.events`, GET only). An event already there is the
same one when it starts within `MINUTES` minutes of the new one (or on the same day, for whole days),
‹he› has not declined it, and either its title says the same thing (one title inside the other, or
most of their words shared) or the new guests are all on it already. Then nothing is made and nobody
is emailed: Rouh is told which event is there, on which calendar, with its link, and says so. A
second one really wanted is booked with `even_if_twice`.

No model is asked, nothing is kept and nothing is changed.

**Whose.** The person's own Google connection, by `org_id` and `user_id`.

**Its switch** is `not_twice` (`rouh/switches.py`): off, an event is booked as asked.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta

log = logging.getLogger("rouh.not_twice")

SWITCH = "not_twice"
TITLE = "Not put on twice: a meeting already on the calendar at that time is not booked a second time"

#: Two timed events are the same one only when they start this close together, in minutes.
MINUTES = 30
#: Share of the shorter title's words the other must have, for two titles to say the same thing.
SHARED = 0.6

FIELD = {"type": "boolean",
         "description": "Make it although an event with the same title or the same guests is already on the "
                        "calendar at that time: only when the person says they want a second one, after being told."}

#: Words that say nothing about which meeting it is.
_EMPTY = {"a", "an", "the", "and", "with", "for", "of", "to", "on", "in", "at", "call", "meeting", "sync",
          "catch", "up", "catch-up", "chat", "re", "fw", "fwd", "-", "/", "&", "x", "<>", "+"}


def on(who) -> bool:
    from . import switches

    if who is None:
        return False
    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def _words(title: str) -> set[str]:
    return {w for w in re.findall(r"[\w'+-]+", str(title or "").lower()) if w not in _EMPTY}


def same_title(one: str, other: str) -> bool:
    """Whether two titles say the same thing: one inside the other, or most words shared."""
    a = " ".join(str(one or "").lower().split())
    b = " ".join(str(other or "").lower().split())
    if not a or not b:
        return False
    if a == b or (min(len(a), len(b)) >= 4 and (a in b or b in a)):
        return True
    wa, wb = _words(a), _words(b)
    if not wa or not wb:
        return False
    return len(wa & wb) / min(len(wa), len(wb)) >= SHARED


def _guests_on(event: dict) -> set[str]:
    out = {str(g.get("email") or "").lower() for g in event.get("guests") or [] if g.get("email")}
    if event.get("organiser"):
        out.add(str(event["organiser"]).lower())
    return out


def _declined(event: dict) -> bool:
    return str(event.get("my_response") or "").lower() == "declined"


def same_event(event: dict, *, title: str, start, guests: list[str], own: list[str]) -> str:
    """Why `event` is the one being booked again ("title" or "guests"), or "" when it is not."""
    if _declined(event) or event.get("status") == "cancelled":
        return ""
    there = event.get("start")
    if there is None or start is None:
        return ""
    if isinstance(start, datetime) != isinstance(there, datetime):
        return ""
    if isinstance(start, datetime):
        if abs((there - start).total_seconds()) > MINUTES * 60:
            return ""
    elif there != start:
        return ""
    if same_title(title, event.get("title") or ""):
        return "title"
    mine = {str(a or "").lower() for a in own if a}
    wanted = {str(g or "").strip().lower() for g in guests or []} - mine
    if wanted and wanted <= _guests_on(event):
        return "guests"
    return ""


def said(event: dict, why: str) -> str:
    """What the model is told when nothing was made."""
    from .google_api import said_span

    when = said_span(event["start"], event["end"], event["all_day"])
    on_it = [str(g.get("email")) for g in event.get("guests") or [] if g.get("email")][:6]
    because = ("with the same title" if why == "title" else "with every guest asked for already on it")
    return ("Not added, and nobody was emailed: it is already on the calendar. "
            f"{event['title']!r}, {when}, on the calendar {event.get('calendar') or 'of the account'}, "
            f"{because}"
            + (f" (guests: {', '.join(on_it)})" if on_it else "")
            + f" - event id {event.get('id')} on calendar {event.get('calendar_id')}"
            + (f" - {event['link']}" if event.get("link") else "")
            + ". Tell the person it was there already and give its link. Only if they say they want a "
              "second one, call create_calendar_event again with even_if_twice.")


async def check(calendar, *, title: str, start, end, minutes, guests: list[str], own: list[str],
                zone) -> tuple[str, dict | None]:
    """(what to tell the model, the event already there) or ("", None) when it is new."""
    from .google_api import event_span

    a, b = event_span(start, end, minutes)
    if isinstance(a, datetime):
        lo, hi = a - timedelta(minutes=MINUTES), a + timedelta(minutes=MINUTES)
    else:
        day = a if isinstance(a, date) else a.date()
        lo = datetime(day.year, day.month, day.day, tzinfo=zone)
        hi = lo + timedelta(days=1)
    got = await calendar.events(lo, hi, limit=50)
    for event in got.get("events") or []:
        why = same_event(event, title=title, start=a, guests=guests, own=own)
        if why:
            return said(event, why), event
    return "", None


__all__ = ["FIELD", "MINUTES", "SWITCH", "TITLE", "check", "on", "same_event", "same_title", "said"]
