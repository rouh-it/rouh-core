"""Flights left open: a flight in the next two weeks that leaves ‹his› work calendar looking free,
said in the morning brief, with one press to block it as out of office.

Built by the nightly feature run, night 32, 4 November 2026 (task 94). Flights are put on a
calendar of their own or a family one (a shared calendar, or the one Gmail makes from a booking
email), not on the account's main calendar, which is the one colleagues and clients see when they
look for a time. So during a flight the main calendar says free, and a meeting can be booked into
it, or one already there is forgotten until the plane is boarding. Seeing both calendars side by
side ‹he› sees the flight; the people booking ‹him› see only the main one, and that is the part
nobody tells ‹him›.

So, while its switch is on, the morning brief has a section **Flights left open**, read afresh
from Google each time the page opens, with no model:

- **Which.** Timed events of the next fourteen days, on any calendar the account sees, that are
  flights: Gmail's own flight events, or a title that says flight, has a plane in it, a flight
  number or two airport codes. Only one that the main calendar does not already cover with an
  event of its own (the flight itself, an out-of-office, or any busy event over all of it).
- **What it says.** The flight, its day and times and which calendar it is on, that the main
  calendar shows ‹him› free then, and the meetings with other people already on the main
  calendar in that time, which still stand.
- **Block it as out of office** puts Google's own out-of-office on the main calendar from the
  flight's start to its end (`Calendar.block`), called "Flying: <the flight>", which declines
  new invitations for that time with a short note; the line then says it is blocked, with a link.
  **Not needed** puts the line away, with Undo.

**Whose.** The connected Google account's calendars (`org_id` and `user_id`) and ‹his› own
settings (`user_settings`, `flight_open`). Nothing is sent by Rouh; Google declines what comes.

**Its switch** is `flight_open` (`rouh/switches.py`): off, the section is not there and the
route refuses.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from datetime import datetime, timedelta

log = logging.getLogger("rouh.flight_open")

SWITCH = "flight_open"
TITLE = ("Flights left open: a flight that leaves your work calendar looking free, in the morning "
         "brief, with one press to block it as out of office")
#: The person's own setting: {line key: {"put": seconds} or {"blocked": seconds, "link": ...}}.
KEPT = "flight_open"
DAYS = 14
MOST = 6
ACTS = ("block", "put", "undo")

#: Words that make a title a flight.
_WORDS = re.compile(r"\b(flight|flug|vol|vuelo|volo|полет|полёт)\b|✈|🛫|🛬", re.I)
#: A flight number, such as LH 1427 or FR8341, said beside a word that is not a time.
_NUMBER = re.compile(r"\b(?:[A-Z]{2}|[A-Z]\d|\d[A-Z])\s?\d{2,4}\b")
#: Two airport codes, such as SOF - FRA or SOF→MUC or SOF to LHR.
_ROUTE = re.compile(r"\b[A-Z]{3}\s*(?:-|–|—|→|->|>|to)\s*[A-Z]{3}\b")
#: The message Google sends with what it declines during a flight.
MESSAGE = "I am on a flight at this time and cannot join. I will reply when I land."


def on(who) -> bool:
    from . import switches

    if who is None:
        return False
    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def is_flight(event: dict) -> bool:
    """Whether one event, as `Calendar.events` gives it, is a flight."""
    if event.get("all_day") or not isinstance(event.get("start"), datetime) \
            or not isinstance(event.get("end"), datetime):
        return False
    length = event["end"] - event["start"]
    if length < timedelta(minutes=30) or length > timedelta(hours=20):
        return False
    if event.get("kind") == "fromGmail" and re.search(r"flight|✈", event.get("title") or "", re.I):
        return True
    title = event.get("title") or ""
    return bool(_WORDS.search(title) or _ROUTE.search(title)
                or (_NUMBER.search(title) and not re.search(r"\b\d{1,2}:\d{2}\b", title)))


def _key(event: dict) -> str:
    ident = f"{event.get('calendar_id')}|{event.get('id')}|{event['start'].isoformat()}"
    return "f-" + hashlib.sha256(ident.encode()).hexdigest()[:16]


def kept(who) -> dict[str, dict]:
    from .models import UserSetting

    value = (UserSetting.objects.filter(user_id=str(who.user_id), org_id=who.org_id or "", name=KEPT)
             .values_list("value", flat=True).first())
    try:
        held = json.loads(value) if value else {}
    except (TypeError, ValueError):
        held = {}
    return {str(k): v for k, v in held.items() if isinstance(v, dict)} if isinstance(held, dict) else {}


def _keep(who, held: dict) -> None:
    from .models import UserSetting

    UserSetting.objects.bulk_create(
        [UserSetting(user_id=str(who.user_id), org_id=who.org_id or "", name=KEPT,
                     value=json.dumps(held), updated_at=time.time())],
        update_conflicts=True, unique_fields=["user_id", "name"],
        update_fields=["org_id", "value", "updated_at"])


def _covered(flight: dict, main: list[dict]) -> bool:
    """Whether busy events of the main calendar cover the whole flight, five minutes either side."""
    start, end = flight["start"], flight["end"]
    slack = timedelta(minutes=5)
    spans = sorted((one["start"], one["end"]) for one in main
                   if isinstance(one.get("start"), datetime) and one.get("busy", True)
                   and one.get("my_response") != "declined" and one.get("kind") != "workingLocation")
    reach = start + slack
    for begin, finish in spans:
        if begin > reach:
            break
        reach = max(reach, finish)
    return reach >= end - slack


def _day_words(start: datetime, now: datetime) -> str:
    if start.date() == now.date():
        return "today"
    if start.date() == (now + timedelta(days=1)).date():
        return "tomorrow"
    if start - now < timedelta(days=6):
        return start.strftime("%A")
    return start.strftime("%A %-d %B")


async def found(who, google, *, now: datetime | None = None) -> dict | None:
    """{items, count} for the brief, or None when there is nothing to say."""
    from asgiref.sync import sync_to_async

    from . import clock

    if google is None:
        return None
    services = google(who)
    if services is None:
        return None
    calendar = services.calendar
    zone = clock.zone_of(who)
    now = (now or datetime.now().astimezone()).astimezone(zone)
    got = await calendar.events(now, now + timedelta(days=DAYS), limit=250)
    events = [one for one in got.get("events") or [] if one.get("status") != "cancelled"]
    main_id = str((await calendar.about("primary")).get("id") or "")
    main = [one for one in events if one.get("calendar_id") == main_id]
    held = await sync_to_async(kept)(who)
    out = []
    for one in events:
        if not is_flight(one) or one["end"] <= now:
            continue
        key = _key(one)
        line = held.get(key) or {}
        if line.get("put"):
            continue
        if line.get("blocked") and time.time() - float(line["blocked"]) > 12 * 3600:
            # Said as blocked the day it was pressed, and not again.
            continue
        if not line.get("blocked") and (one.get("calendar_id") == main_id or _covered(one, main)):
            continue
        start, end = one["start"].astimezone(zone), one["end"].astimezone(zone)
        clashes = [m for m in main if m.get("guests") and m.get("my_response") != "declined"
                   and isinstance(m.get("start"), datetime) and m["start"] < one["end"]
                   and m["end"] > one["start"] and m.get("kind") not in ("outOfOffice", "focusTime")]
        out.append({
            "key": key, "title": one.get("title") or "a flight", "calendar": one.get("calendar") or "",
            "calendar_id": one.get("calendar_id") or "", "event_id": one.get("id") or "",
            "start": start.timestamp(), "end": end.timestamp(), "day": _day_words(start, now),
            "time": f"{start:%H:%M} to {end:%H:%M}" + ("" if start.date() == end.date()
                                                       else f" on {end:%A}"),
            "link": one.get("link") or "",
            "clashes": [{"title": m.get("title") or "a meeting",
                         "time": m["start"].astimezone(zone).strftime("%H:%M"),
                         "link": m.get("link") or ""} for m in clashes[:5]],
            "blocked": float(line.get("blocked") or 0) or None,
            "blocked_link": str(line.get("link") or ""),
        })
    if not out:
        return None
    out.sort(key=lambda i: i["start"])
    return {"items": out[:MOST], "count": len(out)}


async def again(who, brief: dict, google=None) -> None:
    """The section as the page opens, put on the brief it is sent with; gone when off or empty."""
    from asgiref.sync import sync_to_async

    brief.pop("flight_open", None)
    try:
        if who is None or not await sync_to_async(on)(who):
            return
        got = await found(who, google)
    except Exception:  # noqa: BLE001 - the rest of the brief is drawn without it
        log.exception("the flights left open could not be read")
        return
    if got:
        from . import evolution

        brief["flight_open"] = {"ok": True, "source": "Calendar", **got}
        await sync_to_async(evolution.used)(SWITCH, "shown", who=who,
                                           detail=f"{got['count']} flights left open")


class Refused(ValueError):
    """What cannot be done with a flight's line, in a sentence."""


async def act(who, google, key: str, what: str, *, calendar_id: str = "", event_id: str = "") -> dict:
    """Block it as out of office, Not needed (put away), or Undo."""
    from asgiref.sync import sync_to_async

    from . import evolution

    held = await sync_to_async(kept)(who)
    if what == "block":
        if google is None or google(who) is None:
            raise Refused("Google is not connected.")
        calendar = google(who).calendar
        event = await calendar.event(calendar_id, event_id)
        if not is_flight(event) or _key(event) != key:
            raise Refused("That flight is not on the calendar as it was; open the brief again.")
        made = await calendar.block(kind="away", start=event["start"], end=event["end"],
                                    title=f"Flying: {event.get('title') or 'a flight'}"[:200],
                                    message=MESSAGE, decline="new")
        held[key] = {"blocked": time.time(), "link": made.get("link") or "", "id": made.get("id") or ""}
        await sync_to_async(_keep)(who, held)
        await sync_to_async(evolution.used)(SWITCH, "blocked", who=who,
                                           detail=f"blocked {str(event.get('title') or '')[:60]}")
        return {"ok": True, "link": made.get("link") or "", "id": made.get("id") or ""}
    if what == "put":
        held[key] = {**(held.get(key) or {}), "put": time.time()}
        await sync_to_async(_keep)(who, held)
        await sync_to_async(evolution.used)(SWITCH, "put", who=who, detail="said a flight needs no block")
        return {"ok": True}
    line = dict(held.get(key) or {})
    line.pop("put", None)
    if line:
        held[key] = line
    else:
        held.pop(key, None)
    await sync_to_async(_keep)(who, held)
    return {"ok": True}


__all__ = ["ACTS", "KEPT", "SWITCH", "TITLE", "Refused", "act", "again", "found", "is_flight", "on"]
