"""Time before its date: a task whose notes say it is due soon offers the free time left before
that date on ‹his› calendar, and puts focus time there in one press.

Built by the nightly feature run, night 32, 4 November 2026 (task 94). A task's notes say when
its work is due ("the proposal is due by Friday 14 November"), and ‹his› calendar says how the days
before it are already filling with meetings, but nothing puts the two together: the date is seen
in the task, the meetings in the calendar, and how much time is really left for the work is
worked out by eye, if at all, usually the day before. A block on the calendar is the only thing
that keeps that time from being taken, and making one means leaving the task, opening the
calendar, finding a gap and naming the event.

So, while its switch is on, a task's own page has a short section near the end, **Time before
its date**, only when its notes' Where this stands name a date something is due by that comes in
the next `AHEAD_DAYS` days (read the way Dates your tasks wait on reads them, `rouh/task_dates.py`):

- the date and the line that says it, and **Find time**, which reads ‹his› main calendar from now
  to that date and says how many working hours (09:00 to 18:00 on weekdays, on ‹his› clock) are
  still free, and offers up to `MOST` two-hour gaps, one a day, the soonest first;
- **Block it** beside each puts Google's own focus time there (`Calendar.block`), called "Focus:
  <the task>", with the task's address in it, declining new invitations for that time and setting
  Google Chat to do not disturb; the line then says it is blocked, with a link.

No model is asked. Nothing is sent: Google declines what comes in that time by itself.

**Whose.** The task's own notes in the owner's workspace and the connected Google account's main
calendar (`org_id` and `user_id`); only the owner signed in sees or presses it.

**Its switch** is `task_time` (`rouh/switches.py`): off, no section is drawn and the press is
refused.
"""
from __future__ import annotations

import hashlib
import html
import json
import logging
from datetime import date, datetime, time, timedelta
from pathlib import Path

log = logging.getLogger("rouh.task_time")

SWITCH = "task_time"
TITLE = ("Time before its date: a task due soon offers the free time left before its date on "
         "your calendar, and puts focus time there in one press")
NOTES = "AGENTS.md"
#: How far ahead a due date makes the section; the most gaps offered; a block's length.
AHEAD_DAYS = 21
MOST = 3
MINUTES = 120
#: The working day, on his clock.
DAY_START, DAY_END = time(9, 0), time(18, 0)


def on(who) -> bool:
    from . import switches

    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def _read(root, rel: str) -> str:
    try:
        return (Path(str(root)) / rel / NOTES).read_text(encoding="utf-8")
    except OSError:
        return ""


def _title(root, rel: str) -> str:
    try:
        got = json.loads((Path(str(root)) / rel / ".object.json").read_text(encoding="utf-8"))
        if got.get("title"):
            return str(got["title"])
    except (OSError, ValueError):
        pass
    for line in _read(root, rel).splitlines()[:5]:
        if line.startswith("# "):
            return line[2:].strip()
    return rel.rstrip("/").split("/")[-1]


def due(root, rel: str, today: date) -> dict | None:
    """The nearest date the task's Where this stands says something is due by, in the next
    `AHEAD_DAYS` days and not today: {on, words}, or None."""
    from . import task_dates

    coming = [one for one in task_dates.found_in(_read(root, rel), today)
              if 0 < (one["on"] - today).days <= AHEAD_DAYS]
    if not coming:
        return None
    coming.sort(key=lambda one: one["on"])
    return coming[0]


def _key(rel: str, on_day: date) -> str:
    return "t-" + hashlib.sha256(f"{rel}|{on_day.isoformat()}".encode()).hexdigest()[:16]


def section(person, root, rel: str) -> str:
    """The section on a task's own page; "" when off, nobody is signed in, or nothing is due soon."""
    from . import clock, steps

    if person is None or not rel or steps.is_step(rel):
        return ""
    try:
        if not on(person):
            return ""
        today = datetime.now(clock.zone_of(person)).date()
        found = due(root, rel, today)
    except Exception:  # noqa: BLE001 - the page is drawn without it
        log.exception("the due date of %s could not be read", rel)
        return ""
    if found is None:
        return ""
    day = found["on"]
    days = (day - today).days
    said = f"{day:%A} {day.day} {day:%B}" + (" (tomorrow)" if days == 1 else f" (in {days} days)")
    return (f'<section class="oset otime" id="tkTime" aria-label="Time before its date" '
            f'data-key="{_key(rel, day)}">'
            f'<h2 class="divider">Time before its date</h2>'
            f'<p class="otime-due">Due <b>{html.escape(said)}</b>: '
            f'{html.escape(found["words"])}</p>'
            f'<p class="otime-acts"><button type="button" class="obtn otime-find" hidden>Find time'
            f'</button></p><div class="otime-said" role="status"></div></section>')


def _gaps(busy: list[tuple[datetime, datetime]], start: datetime, end: datetime, zone):
    """Free working stretches between `start` and `end`: [(from, to)], on his clock."""
    busy = sorted(busy)
    out = []
    day = start.date()
    while day < end.date() or (day == end.date() and end.time() > DAY_START):
        if day.weekday() < 5:
            open_at = max(datetime.combine(day, DAY_START, tzinfo=zone), start)
            close_at = min(datetime.combine(day, DAY_END, tzinfo=zone), end)
            at = open_at
            for b0, b1 in busy:
                if b1 <= at or b0 >= close_at:
                    continue
                if b0 > at:
                    out.append((at, b0))
                at = max(at, b1)
            if at < close_at:
                out.append((at, close_at))
        day += timedelta(days=1)
    return [(a, b) for a, b in out if b > a]


def _round_up(moment: datetime) -> datetime:
    extra = (30 - moment.minute % 30) % 30
    return (moment + timedelta(minutes=extra)).replace(second=0, microsecond=0)


async def find(who, google, root, rel: str, *, now: datetime | None = None) -> dict:
    """{ok, hours, until, gaps: [{start, end, said}]} for the task's nearest coming date."""
    from . import clock, evolution
    from asgiref.sync import sync_to_async

    if google is None or google(who) is None:
        return {"ok": False, "error": "Google is not connected: connect it in Settings first."}
    zone = clock.zone_of(who)
    now = (now or datetime.now(zone)).astimezone(zone)
    found = await sync_to_async(due)(root, rel, now.date())
    if found is None:
        return {"ok": False, "error": "Its notes no longer name a date coming up."}
    calendar = google(who).calendar
    until = datetime.combine(found["on"], time(0, 0), tzinfo=zone)
    start = _round_up(now)
    got = await calendar.events(start, until, calendar_ids=["primary"], limit=250)
    busy = [(one["start"].astimezone(zone), one["end"].astimezone(zone))
            for one in got.get("events") or []
            if isinstance(one.get("start"), datetime) and one.get("busy", True)
            and one.get("my_response") != "declined" and one.get("kind") != "workingLocation"]
    stretches = _gaps(busy, start, until, zone)
    hours = sum((b - a).total_seconds() for a, b in stretches) / 3600
    offered, days = [], set()
    for a, b in stretches:
        if (b - a) >= timedelta(minutes=MINUTES) and a.date() not in days:
            days.add(a.date())
            end = a + timedelta(minutes=MINUTES)
            offered.append({"start": a.isoformat(), "end": end.isoformat(),
                            "said": (f"{a:%A} {a.day} {a:%B}, {a:%H:%M} to {end:%H:%M}")})
        if len(offered) >= MOST:
            break
    await sync_to_async(evolution.used)(SWITCH, "found", who=who,
                                       detail=f"{hours:.1f} free hours before {found['on']}")
    return {"ok": True, "hours": round(hours, 1), "until": f"{found['on']:%A} {found['on'].day} "
            f"{found['on']:%B}", "gaps": offered}


async def block(who, google, root, rel: str, start: str) -> dict:
    """Focus time on the main calendar from `start`, `MINUTES` long, for the task: {ok, said, link}."""
    from asgiref.sync import sync_to_async

    from . import clock, evolution

    if google is None or google(who) is None:
        return {"ok": False, "error": "Google is not connected: connect it in Settings first."}
    zone = clock.zone_of(who)
    try:
        begin = datetime.fromisoformat(start).astimezone(zone)
    except (TypeError, ValueError):
        return {"ok": False, "error": "Which time."}
    found = await sync_to_async(due)(root, rel, datetime.now(zone).date())
    if found is None or begin.date() >= found["on"] or begin < datetime.now(zone) - timedelta(minutes=5):
        return {"ok": False, "error": "That time is no longer before its date: press Find time again."}
    title = await sync_to_async(_title)(root, rel)
    made = await google(who).calendar.block(
        kind="focus", start=begin, end=begin + timedelta(minutes=MINUTES),
        title=f"Focus: {title}"[:200], decline="new",
        message="I am keeping this time for a piece of work that is due; can we find another time?")
    await sync_to_async(evolution.used)(SWITCH, "blocked", who=who,
                                       detail=f"{MINUTES} minutes before {found['on']}")
    return {"ok": True, "link": made.get("link") or "",
            "said": f"Focus time is on your calendar, {begin:%A} {begin:%H:%M} to "
                    f"{begin + timedelta(minutes=MINUTES):%H:%M}: Google declines new invitations then."}


__all__ = ["SWITCH", "TITLE", "block", "due", "find", "on", "section"]
