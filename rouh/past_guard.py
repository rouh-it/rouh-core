"""Not booked in the past: a meeting asked for at a time that has already gone is held, and nobody emailed.

Built by the nightly feature run, night 45 of the ledger (16 November 2026, task 94).
Rouh books and moves meetings for ‹owner› from words: "Friday at ten", "the 3rd", "half past two".
Each can be read as a time already gone - last Friday rather than the coming one, the year left at
the one before, two o'clock read after two o'clock has passed - and create_calendar_event booked it
all the same. With guests, Google emailed every one of them an invitation for a time already gone,
and the next email had to put it right. update_calendar_event moved a meeting into the past the same
way. The guards before it (twice, busy, away, their night, a holiday) all look forward; none looked
at the clock.

So, while its switch is on, before create_calendar_event makes an event or update_calendar_event
moves one, the start is read against now on ‹his› own clock (`check`, plain arithmetic, no model): a
time more than `GRACE` minutes ago, or a whole day before today, is held. Nothing is made, nobody is
emailed, and Rouh is told when it was, what time it is now, and the time it most likely meant: the
same day and hour next week, when it was in the last seven days, or the same date next year, when it
was months ago. A meeting really wanted on the calendar after it happened, to log it, is booked with
`even_if_past`.

Nothing is kept and nothing is read but the clock.

**Whose.** The person's own clock (`clock.zone_of`), by `org_id` and `user_id`.

**Its switch** is `past_guard` (`rouh/switches.py`): off, a time is booked as asked.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

SWITCH = "past_guard"
TITLE = "Not booked in the past: a meeting at a time already gone is held"

#: A start this many minutes ago is still now: "a meeting now" asked a little late.
GRACE = 10

FIELD = {"type": "boolean",
         "description": "Book it although its time has already passed: only when the person says they "
                        "want a past meeting on the calendar (to log it), after being told it has passed."}


def on(who) -> bool:
    from . import switches

    if who is None:
        return False
    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def _said(moment) -> str:
    if isinstance(moment, datetime):
        return f"{moment:%A %-d %B %Y at %H:%M}"
    return f"{moment:%A %-d %B %Y}"


def meant(start, now: datetime):
    """The time it most likely meant, still to come: the same hour next week, or the same date next year."""
    today = now.date()
    if isinstance(start, datetime):
        if start.date() >= today - timedelta(days=7):
            later = start + timedelta(days=7)
            while later < now:
                later += timedelta(days=7)
            return later
        try:
            later = start.replace(year=today.year)
        except ValueError:  # 29 February
            later = start.replace(year=today.year, day=28)
        return later if later > now else later.replace(year=today.year + 1)
    if start >= today - timedelta(days=7):
        later = start + timedelta(days=7)
        while later < today:
            later += timedelta(days=7)
        return later
    try:
        later = start.replace(year=today.year)
    except ValueError:
        later = start.replace(year=today.year, day=28)
    return later if later >= today else later.replace(year=today.year + 1)


def check(start, zone, *, now: datetime | None = None, moving: bool = False) -> str:
    """Why not, when `start` has already passed on the person's clock; "" when it is still to come."""
    if start is None:
        return ""
    now = (now or datetime.now(zone)).astimezone(zone)
    if isinstance(start, datetime):
        start = start.astimezone(zone)
        if start >= now - timedelta(minutes=GRACE):
            return ""
    elif isinstance(start, date):
        if start >= now.date():
            return ""
    else:
        return ""
    likely = meant(start, now)
    if moving:
        lead = "Not moved, and nobody was emailed:"
    else:
        lead = "Not booked, and nobody was emailed:"
    return (f"{lead} {_said(start)} has already passed (it is now {now:%A %-d %B %Y, %H:%M} on the person's "
            f"clock). If {_said(likely)} was meant, give that time instead. Only if the person wants a past "
            f"meeting on the calendar on purpose, say it has passed and book it again with even_if_past.")


__all__ = ["FIELD", "GRACE", "SWITCH", "TITLE", "check", "meant", "on"]
