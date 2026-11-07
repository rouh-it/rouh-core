"""You meet them soon, said on their email: a message opened on the inbox card from somebody ‹he›
meets in the next days says when, with Open the meeting.

Built by the nightly feature run, night 36 (Rouh's brief called it night 35), 7 November 2026 (task
94). An email from somebody ‹he› has a meeting with on Thursday reads the same as any other: it is
answered in writing with what could wait for the call, or the call is prepared without it, because
nothing on the email says a meeting is coming. Finding out meant looking the sender up in the
calendar, which nobody does for every email.

So, while its switch is on, a message opened on the inbox card (Rouh's own inbox or ‹his› read-only
one) is checked against ‹his› main calendar for the next `DAYS` days: when its sender, or somebody
else on it (To and Cc, ‹him› aside), is a guest of a timed meeting there that is not cancelled or
declined, one quiet line under the message says "You meet Dana Reed tomorrow at 13:00: Pricing call
with Northwind", the soonest first, at most `MOST`, each with **Open the meeting**, which opens it in
Google Calendar. Nothing is kept, nobody is told, and no model is asked.

**Whose.** The connected Google account's main calendar, read with the person's own connection
(`org_id` and `user_id`).

**Its switch** is `meeting_soon` (`rouh/switches.py`): off, the line is not there.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta

log = logging.getLogger("rouh.meeting_soon")

SWITCH = "meeting_soon"
TITLE = "You meet them soon: an email opened on the inbox card says when you meet its sender or others on it"
#: How far ahead the calendar is read, in days, and how many meetings are said.
DAYS = 7
MOST = 3

_ADDRESS = re.compile(r"[A-Za-z0-9._%+'-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def on(who) -> bool:
    from . import switches

    if who is None:
        return False
    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def addresses(*fields) -> list[str]:
    """Every address in header fields, lowercased, once each, in order."""
    out: list[str] = []
    for field in fields:
        for one in _ADDRESS.findall(str(field or "")):
            low = one.lower()
            if low not in out:
                out.append(low)
    return out


def day_words(start: datetime, now: datetime) -> str:
    days = (start.date() - now.date()).days
    if days == 0:
        return "today"
    if days == 1:
        return "tomorrow"
    return f"on {start:%A} {start.day} {start:%B}"


def matches(events: list[dict], people: list[str], now: datetime, zone) -> list[dict]:
    """The meetings among `events` with any of `people` as a guest, soonest first."""
    want = set(people)
    out = []
    for one in events:
        start = one.get("start")
        if one.get("all_day") or not isinstance(start, datetime) or start <= now:
            continue
        if one.get("status") == "cancelled" or one.get("kind") not in ("default", "", None):
            continue
        if one.get("my_response") == "declined":
            continue
        met = []
        for g in one.get("guests") or []:
            address = str(g.get("email") or "").lower()
            if address in want and not g.get("this_calendar") and g.get("response") != "declined":
                met.append(str(g.get("name") or "").strip() or address)
        organiser = str(one.get("organiser") or "").lower()
        if organiser in want and not one.get("mine"):
            name = str(one.get("organiser_name") or "").strip() or organiser
            if name not in met:
                met.insert(0, name)
        if not met:
            continue
        local = start.astimezone(zone)
        out.append({"title": one.get("title") or "a meeting", "people": met,
                    "when": f"{day_words(local, now.astimezone(zone))} at {local:%H:%M}",
                    "at": local.timestamp(), "link": one.get("link") or "",
                    "video": one.get("video") or ""})
    out.sort(key=lambda m: m["at"])
    return out[:MOST]


def said(meeting: dict) -> str:
    names = meeting["people"]
    who = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
    return f"You meet {who} {meeting['when']}: {meeting['title']}"


async def shown(who, calendar, found: dict, *, own: list[str], now: datetime | None = None) -> dict | None:
    """What an opened message offers: {meetings: [{said, link, ...}]}, or None (off, or none)."""
    import asyncio

    from . import clock

    if calendar is None or not await asyncio.to_thread(on, who):
        return None
    mine = {str(a or "").lower() for a in own if a}
    people = [a for a in addresses(found.get("from"), found.get("to"), found.get("cc")) if a not in mine]
    if not people:
        return None
    zone = clock.zone_of(who)
    now = (now or datetime.now().astimezone()).astimezone(zone)
    got = await calendar.events(now, now + timedelta(days=DAYS), calendar_ids=["primary"], limit=250)
    meetings = matches(got.get("events") or [], people, now, zone)
    if not meetings:
        return None
    from . import evolution

    await asyncio.to_thread(evolution.used, SWITCH, "shown", who=who,
                            detail=f"{len(meetings)} meetings soon with people on an email")
    return {"meetings": [dict(m, said=said(m)) for m in meetings]}


def opened(who) -> None:
    """Open the meeting was pressed on the inbox card."""
    from . import evolution

    evolution.used(SWITCH, "opened", who=who, detail="opened a meeting from an email of somebody on it")


__all__ = ["DAYS", "MOST", "SWITCH", "TITLE", "addresses", "matches", "on", "opened", "said", "shown"]
