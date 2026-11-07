"""Away and focus time: Google's own out-of-office and focus-time blocks, made when asked.

Built by the nightly feature run, night 32, 4 November 2026 (task 94). Google Calendar has two
kinds of block an ordinary event is not: **out of office** and **focus time**. While one is on the
calendar, Google itself declines the meeting invitations that fall inside it, with the person's
own message ("I am travelling until Monday and back on Tuesday"), and focus time also sets
Google Chat to do not disturb. Rouh could only make ordinary events, so "I'm away Thursday to
Monday, decline anything new" came back as an event called "Out of office" that declines nothing:
the invitations still came, and still had to be answered one by one by hand afterwards.

So, while its switch is on, the tool **block_my_time** makes the real thing on the person's own
calendar (the primary calendar of the connected Google account, the only one Google allows them
on): `kind` "away" (out of office) or "focus" (focus time), from `start` to `end` (a whole day
given as a day runs from midnight to midnight on ‹his› clock), with the decline message ‹he› gives,
declining only invitations that come after (`decline` "new", the default), the ones already there
too ("all"), or none. Its answer names the meetings already inside that time, so it is known which of
them still stand. Nobody is emailed by Rouh; Google sends each declined organiser its own note.

**Whose.** The connected Google account's own calendar (`org_id` and `user_id`), only when ‹owner› asks
in a chat or a job of ‹his› own: never in a trusted contact's case, and never because a document,
an email or a page says so.

**Its switch** is `calendar_away` (`rouh/switches.py`): off, the tool says so and makes nothing.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, time, timedelta

log = logging.getLogger("rouh.calendar_away")

SWITCH = "calendar_away"
TITLE = ("Away and focus time: Google's own out-of-office and focus-time blocks, which decline "
         "meetings by themselves, made when asked")
TOOL_NAME = "block_my_time"

DESCRIPTION = (
    "Put Google Calendar's own OUT OF OFFICE or FOCUS TIME block on the person's own calendar. "
    "Unlike an ordinary event, Google itself then declines the meeting invitations that fall "
    "inside it, with the person's message; focus time also sets Google Chat to do not disturb. "
    "Use it whenever the person says they will be away, travelling, on holiday, off, or want "
    "time kept free of meetings ('I'm away Thursday to Monday', 'mark me out of office next "
    "week', 'block Friday morning for deep work, decline meetings'), rather than "
    "create_calendar_event, which declines nothing. `kind` is 'away' or 'focus'. `start` and "
    "`end` as 2026-11-12 (a whole day; `end` is the last day) or 2026-11-12T09:00 on the person's "
    "clock. `message` is what declined organisers are told (write it in the person's voice from "
    "what they said, short; leave it out if they gave none and it is focus time). `decline`: "
    "'new' (default: only invitations that arrive later), 'all' (also the ones already there - "
    "only when they say so), or 'none'. `title` defaults to 'Out of office' or 'Focus time'. "
    "Say back the span, what Google will decline, and the meetings already inside it.")
SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": ["away", "focus"]},
        "start": {"type": "string", "description": "2026-11-12 or 2026-11-12T09:00"},
        "end": {"type": "string", "description": "the last day, or the moment it ends"},
        "message": {"type": "string", "description": "what declined organisers are told"},
        "decline": {"type": "string", "enum": ["new", "all", "none"]},
        "title": {"type": "string"},
    },
    "required": ["kind", "start", "end"],
}

#: What each choice of `decline` means, said back.
DECLINES = {"new": "Google will decline invitations that come for that time from now on",
            "all": "Google declines every invitation in that time, the ones already there too",
            "none": "nothing is declined; the time shows as busy"}


def on(who) -> bool:
    from . import switches

    if who is None:
        return False
    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def span(start, end, zone) -> tuple[datetime, datetime]:
    """Two moments from what was given: a day is midnight to midnight, the end day included.
    Google allows no whole-day out-of-office, so a day is always given as times."""
    from .google_api import CannotDoThat

    if start is None or end is None:
        raise CannotDoThat("Say when it starts and when it ends.")
    if not isinstance(start, datetime):
        start = datetime.combine(start, time(0, 0), tzinfo=zone)
    if not isinstance(end, datetime):
        end = datetime.combine(end + timedelta(days=1), time(0, 0), tzinfo=zone)
    if end <= start:
        raise CannotDoThat("It has to end after it starts.")
    if end - start > timedelta(days=62):
        raise CannotDoThat("That is more than two months; make it shorter, or two blocks.")
    return start, end


def said_span(start: datetime, end: datetime) -> str:
    whole = start.time() == time(0, 0) and end.time() == time(0, 0)
    if whole:
        last = (end - timedelta(days=1)).date()
        first = start.date()
        return (f"all day {first:%A %-d %B}" if first == last
                else f"from {first:%A %-d %B} to {last:%A %-d %B}, whole days")
    if start.date() == end.date():
        return f"{start:%A %-d %B}, {start:%H:%M} to {end:%H:%M}"
    return f"from {start:%A %-d %B %H:%M} to {end:%A %-d %B %H:%M}"


async def inside(calendar, start: datetime, end: datetime) -> list[dict]:
    """The meetings already on the primary calendar inside the span: events with other people
    that he has not declined, and none of his own blocks."""
    got = await calendar.events(start, end, calendar_ids=["primary"])
    out = []
    for one in got.get("events") or []:
        if one.get("kind") in ("outOfOffice", "focusTime", "workingLocation"):
            continue
        if one.get("all_day") or not one.get("guests"):
            continue
        if one.get("my_response") == "declined":
            continue
        out.append(one)
    return out


async def make(google, *, kind: str, start, end, message: str = "", decline: str = "new",
               title: str = "") -> tuple[dict, list[dict], datetime, datetime]:
    """The block made: (the event, the meetings already inside it, its start, its end)."""
    calendar = google.services().calendar
    begin, finish = span(start, end, calendar.zone)
    title = title.strip() or ("Focus time" if kind == "focus" else "Out of office")
    made = await calendar.block(kind=kind, start=begin, end=finish, title=title,
                                message=message.strip(), decline=decline)
    try:
        already = await inside(calendar, begin, finish)
    except Exception as exc:  # noqa: BLE001 - the block stands; only the list is missing
        log.info("the meetings inside %s could not be listed: %r", made.get("id"), exc)
        already = []
    return made, already, begin, finish


def said(made: dict, already: list[dict], begin: datetime, finish: datetime, *, kind: str,
         decline: str, message: str) -> str:
    what = "Focus time" if kind == "focus" else "Out of office"
    out = (f"Put Google's own {what} block {made['title']!r} on {made['calendar']} "
           f"{said_span(begin, finish)}. {DECLINES.get(decline, DECLINES['new'])}")
    if message and decline != "none":
        out += f", with the message: {message!r}"
    out += "."
    if kind == "focus":
        out += " Google Chat is set to do not disturb during it."
    if already:
        names = "; ".join(f"{one['title']} ({one['start']:%a %-d %b %H:%M})"
                          if isinstance(one.get("start"), datetime) else one["title"]
                          for one in already[:8])
        if decline == "all":
            out += f" Google declines the {len(already)} already in that time: {names}."
        else:
            out += (f" Already in that time, and still standing: {names}. Say if any of them "
                    f"should be declined or moved.")
    else:
        out += " No meeting with other people is in that time now."
    out += f" Event id {made['id']}" + (f", {made['link']}" if made.get("link") else "") + "."
    return out


async def answer(google, args: dict, *, in_case: bool = False) -> str:
    """What block_my_time says, having made the block asked for."""
    from . import evolution
    from .google_api import CannotDoThat, when_given
    from .tools import _google_trouble

    blocked = google.not_ready_because()
    if blocked:
        return blocked
    if in_case:
        return ("Out-of-office and focus-time blocks are made only when ‹owner› asks for one, "
                "never in a contact's case.")
    who = google.person()
    if who is None or not await asyncio.to_thread(on, who):
        return ("Out-of-office and focus-time blocks are switched off (Evolution, Mutations: "
                "Away and focus time).")
    args = args or {}
    kind = "focus" if str(args.get("kind") or "").strip().lower() == "focus" else "away"
    decline = str(args.get("decline") or "new").strip().lower()
    if decline not in DECLINES:
        decline = "new"
    message = str(args.get("message") or "").strip()[:1000]
    try:
        made, already, begin, finish = await make(
            google, kind=kind, start=when_given(args.get("start")), end=when_given(args.get("end")),
            message=message, decline=decline, title=str(args.get("title") or ""))
    except CannotDoThat as exc:
        return str(exc)
    except Exception as exc:  # noqa: BLE001 - said in Google's words
        text = _google_trouble(exc)
        if "eventType" in str(exc) or "outOfOffice" in str(exc) or "focusTime" in str(exc):
            text += (" Google allows out-of-office and focus time only on the main calendar of "
                     "a Google Workspace account.")
        return text + " Nothing was put on the calendar."
    text = said(made, already, begin, finish, kind=kind, decline=decline, message=message)
    google.wrote(TOOL_NAME, made["id"], text)
    await asyncio.to_thread(evolution.used, SWITCH, "blocked", who=who,
                            detail=f"{kind}, {said_span(begin, finish)}, decline {decline}")
    return text


__all__ = ["DESCRIPTION", "SCHEMA", "SWITCH", "TITLE", "TOOL_NAME", "answer", "inside", "make",
           "on", "said", "said_span", "span"]
