"""When others are free: asked in words, Rouh reads colleagues' free and busy times and says when
everybody can meet.

Built by the nightly feature run, night 33, 4 November 2026 (task 94). In one Google Workspace each
person's main calendar shows the others when it is busy, and nothing else, unless they hid it: that
is what Google Calendar's "Find a time" reads. Rouh could not: its calendar tools read only the
calendars shared with its own account, so "when are Todor and Ivaylo both free on Thursday?" was
answered with the person's own calendar and a guess about everybody else's, or a suggestion to
look in Google Calendar. Times offered from the person's own calendar alone (night 13's Times to
offer) were rejected as something Rouh can do when asked; this is the part it could not.

So, while its switch is on, the tool **when_free** asks Google's free/busy query
(`Calendar.free_busy`) for each address named and for the person's own main calendar, over the
days asked (the next five working days when none are said), and answers with:

- the times when everybody named is free, at least as long as the meeting, inside working hours on
  the person's clock (9:00 to 18:00 unless asked otherwise), weekdays only unless weekends are
  asked for, at most eight, each said with its day;
- each person's busy times in that window, briefly;
- whose calendar Google would not show, and why (outside the Workspace, or hidden), so a time is
  never said to suit somebody whose calendar was not read.

No model is asked. Nothing is changed or sent: booking is create_calendar_event, as before.

**Whose.** The connected Google account's free/busy query, by `org_id` and `user_id`; Google says
only busy or free, never what the event is.

**Its switch** is `when_free` (`rouh/switches.py`): off, the tool is not offered and refuses.
The reading underneath, `read` and `common_free`, is shared with Not booked over someone busy
(`rouh/busy_guard.py`).
"""
from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta

SWITCH = "when_free"
TITLE = "When others are free: colleagues' free and busy times read, and the times everybody can meet"
TOOL_NAME = "when_free"

#: The most people asked about at once, the most free times said, and the longest window read.
MOST_PEOPLE = 20
MOST_TIMES = 8
MOST_DAYS = 31
#: Free times start on these minutes of the hour.
STEP = timedelta(minutes=30)

DESCRIPTION = (
    "Read when other people are free or busy - colleagues in the same Google Workspace, by their "
    "email addresses - together with the person's own calendar, and say the times when everybody "
    "can meet. Use it whenever the question is when someone else (not only the person) is free, "
    "or when a meeting with them could be; find an address with search_contacts first. It reads "
    "only busy and free, never what the events are, and says whose calendar Google would not show "
    "(people outside the Workspace usually). It books nothing: create_calendar_event does that.")

SCHEMA = {
    "type": "object",
    "properties": {
        "people": {"type": "array", "items": {"type": "string"},
                   "description": "Their email addresses."},
        "start": {"type": "string",
                  "description": "The first day or moment to look from, ISO (2026-11-12 or "
                                 "2026-11-12T13:00). Today when left out."},
        "end": {"type": "string",
                "description": "The last day or moment to look to, ISO. Five working days on when left out."},
        "minutes": {"type": "integer", "description": "How long the meeting is. 30 when left out."},
        "day_starts": {"type": "string", "description": "Working hours start, HH:MM on the person's clock. 09:00."},
        "day_ends": {"type": "string", "description": "Working hours end, HH:MM on the person's clock. 18:00."},
        "weekends": {"type": "boolean", "description": "Look on Saturdays and Sundays too."},
        "without_me": {"type": "boolean",
                       "description": "Leave the person's own calendar out (they are not in the meeting)."},
    },
    "required": ["people"],
}

#: Google's reasons, in a person's words.
TROUBLE = {
    "notFound": "Google would not show it: outside your Workspace, or never shared",
    "groupTooBig": "it is a group too big for Google to read",
    "tooManyCalendarsRequested": "too many calendars were asked at once",
    "internalError": "Google could not read it just now",
}


def on(who) -> bool:
    from . import switches

    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def _hhmm(value, fallback: time) -> time:
    m = re.fullmatch(r"\s*(\d{1,2})(?::(\d{2}))?\s*", str(value or ""))
    if not m or int(m.group(1)) > 23:
        return fallback
    return time(int(m.group(1)), int(m.group(2) or 0))


def window(start, end, zone, now: datetime | None = None) -> tuple[datetime, datetime]:
    """The moments to look between: from now or the day named, to the end named or five working days on."""
    from .google_api import when_given

    now = (now or datetime.now(zone)).astimezone(zone)
    begin = when_given(start, zone) if start else None
    if isinstance(begin, date) and not isinstance(begin, datetime):
        begin = datetime.combine(begin, time(0), zone)
    begin = max(begin or now, now)
    finish = when_given(end, zone) if end else None
    if isinstance(finish, date) and not isinstance(finish, datetime):
        finish = datetime.combine(finish + timedelta(days=1), time(0), zone)
    if finish is None or finish <= begin:
        day, working = begin.date(), 0
        while working < 5:
            day += timedelta(days=1)
            if day.weekday() < 5:
                working += 1
        finish = datetime.combine(day + timedelta(days=1), time(0), zone)
    return begin, min(finish, begin + timedelta(days=MOST_DAYS))


async def read(calendar, people, begin: datetime, finish: datetime, *, me: bool = True) -> dict[str, dict]:
    """{address or "you": {"busy": [(start, end)], "trouble": ""}}: Google's free/busy for each."""
    ids = (["primary"] if me else []) + [p for p in people if p.lower() != "primary"]
    got = await calendar.free_busy(ids, begin, finish)
    if me and "primary" in got:
        # The person first, in what is said, then the others in the order they were named.
        got = {"you": got.pop("primary"), **got}
    return got


def common_free(busy_lists, begin: datetime, finish: datetime, minutes: int, zone, *,
                day_starts: time = time(9), day_ends: time = time(18), weekends: bool = False,
                most: int = MOST_TIMES) -> list[tuple[datetime, datetime]]:
    """The times nobody in `busy_lists` is busy, `minutes` long, inside working hours, as
    (start, end) on the person's clock: each free stretch said once, from its first half hour."""
    length = timedelta(minutes=max(5, int(minutes or 30)))
    spans = sorted((a.astimezone(zone), b.astimezone(zone)) for busy in busy_lists for a, b in busy)
    out: list[tuple[datetime, datetime]] = []
    day = begin.astimezone(zone).date()
    while day <= finish.astimezone(zone).date() and len(out) < most:
        if weekends or day.weekday() < 5:
            open_at = max(datetime.combine(day, day_starts, zone), begin)
            close_at = min(datetime.combine(day, day_ends, zone), finish)
            # From the next half hour on, so a time is never offered as 10:07.
            rounded = open_at.replace(minute=0, second=0, microsecond=0)
            while rounded < open_at:
                rounded += STEP
            at = rounded
            while at + length <= close_at and len(out) < most:
                clash = next((b for a, b in spans if a < at + length and b > at), None)
                if clash is None:
                    # The whole free stretch from here, said as one time with how long it lasts.
                    stop = min([a for a, b in spans if a >= at + length] + [close_at])
                    out.append((at, stop))
                    at = stop
                    continue
                at = clash
                while (at - rounded) % STEP:
                    at += timedelta(minutes=1)
        day += timedelta(days=1)
    return out


def _span(a: datetime, b: datetime, now: datetime) -> str:
    if a.date() == now.date():
        day = "today"
    elif a.date() == now.date() + timedelta(days=1):
        day = "tomorrow"
    else:
        day = a.strftime("%A %-d %B")
    return f"{day} {a:%H:%M}-{b:%H:%M}"


def said_times(free, now: datetime) -> list[str]:
    return [_span(a, b, now) for a, b in free]


async def answer(calendar, args: dict, zone) -> tuple[str, dict]:
    """What when_free says, and what was found ({people, read, hidden, times})."""
    people = []
    for one in args.get("people") or []:
        one = str(one or "").strip().strip("<>")
        if one and "@" in one and one.lower() not in (p.lower() for p in people):
            people.append(one)
    people = people[:MOST_PEOPLE]
    if not people:
        return ("Say whose times to read, by their email addresses; search_contacts finds an address "
                "from a name."), {}
    minutes = max(5, min(int(args.get("minutes") or 30), 12 * 60))
    begin, finish = window(args.get("start"), args.get("end"), zone)
    me = not bool(args.get("without_me"))
    got = await read(calendar, people, begin, finish, me=me)
    read_ok = [k for k, v in got.items() if not v.get("trouble")]
    hidden = {k: v["trouble"] for k, v in got.items() if v.get("trouble")}
    starts, ends = _hhmm(args.get("day_starts"), time(9)), _hhmm(args.get("day_ends"), time(18))
    free = common_free([got[k]["busy"] for k in read_ok], begin, finish, minutes, zone,
                       day_starts=starts, day_ends=ends, weekends=bool(args.get("weekends")))
    now = datetime.now(zone)
    lines = [f"Free and busy from {begin:%A %-d %B %H:%M} to {finish:%A %-d %B %H:%M}, on your clock "
             f"({zone.key}), for a {minutes}-minute meeting between {starts:%H:%M} and {ends:%H:%M}"
             + ("" if args.get("weekends") else " on weekdays") + "."]
    names = list(read_ok)
    if not read_ok:
        lines.append("Nobody's calendar could be read, so no time can be said to suit anybody.")
    elif free:
        lines.append("Times when " + (", ".join(names) if len(names) > 1 else names[0])
                     + (" are" if len(names) > 1 else " is") + " all free (each from its start, as long as it lasts):")
        lines += [f"- {one}" for one in said_times(free, now)]
    else:
        lines.append("There is no time in that window when " + ", ".join(names) + " are all free for "
                     f"{minutes} minutes. Ask for a wider window or a shorter meeting.")
    for k in read_ok:
        busy = got[k]["busy"]
        if not busy:
            lines.append(f"{'You are' if k == 'you' else k + ' is'} free the whole time.")
            continue
        shown = [_span(a.astimezone(zone), b.astimezone(zone), now) for a, b in busy[:10]]
        more = f", and {len(busy) - 10} more" if len(busy) > 10 else ""
        lines.append(f"{'You are' if k == 'you' else k + ' is'} busy: " + "; ".join(shown) + more + ".")
    for k, why in hidden.items():
        lines.append(f"{k}: not read - {TROUBLE.get(why, why)}. No time above is known to suit them.")
    return "\n".join(lines), {"people": people, "read": read_ok, "hidden": list(hidden), "times": len(free)}


__all__ = ["DESCRIPTION", "SCHEMA", "SWITCH", "TITLE", "TOOL_NAME", "answer", "common_free", "on",
           "read", "said_times", "window"]
