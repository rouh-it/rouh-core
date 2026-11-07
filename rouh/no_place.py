"""Meetings with nowhere to meet: ‹his› meetings in the next days that have guests but no place and
no call link, said in the morning brief, with one press to give one a Google Meet link.

Built by the nightly feature run, night 33 (second run), 5 November 2026 (task 94). A meeting put
on the calendar in a hurry, from a phone, by dragging a slot, or by an assistant, very often has
a time and guests and nothing else: no room, no address and no link. In the calendar it looks
like every other meeting, so nothing says it is missing until the minute it starts, when the
guests write "where are we meeting?" or wait on a call nobody made, and somebody makes a link and
pastes it into a chat.

So, while its switch is on, the morning brief has a section **Meetings with nowhere to meet**,
read afresh from Google each time the page opens, with no model:

- **Which.** Timed meetings of the next `DAYS` days on ‹his› main calendar that ‹he› organises,
  with at least one guest who is not ‹him› (rooms aside), not declined or cancelled, with no
  place, no call made with it (`hangoutLink`, `conferenceData`) and no call link in its
  description (`meet_link.has_place`).
- **What it says.** The meeting, its day and time, and who is invited.
- **Add a Meet link** asks Google for a Meet link on the meeting, the way Add Google Meet does
  (`Calendar.add_video`), and Google tells the guests of the change; the line then says it has one,
  with the link. **Not needed** (an in-person meeting everybody knows the place of, a phone call)
  puts the line away, with Undo.

**Whose.** The connected Google account's main calendar (`org_id` and `user_id`) and ‹his› own
settings (`user_settings`, `no_place`).

**Its switch** is `no_place` (`rouh/switches.py`): off, the section is not there and the route
refuses.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import datetime, timedelta

from .meet_link import has_place

log = logging.getLogger("rouh.no_place")

SWITCH = "no_place"
TITLE = ("Meetings with nowhere to meet: your meetings with guests and no place or call link, in the "
         "morning brief, with one press to add a Meet link")
#: The person's own setting: {line key: {"put": seconds} or {"added": seconds, "video": ...}}.
KEPT = "no_place"
#: How far ahead meetings are read, in days, and how many are shown.
DAYS = 3
MOST = 6
ACTS = ("add", "put", "undo")


def on(who) -> bool:
    from . import switches

    if who is None:
        return False
    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


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


def _key(event: dict) -> str:
    ident = f"{event.get('calendar_id')}|{event.get('id')}"
    return "p-" + hashlib.sha256(ident.encode()).hexdigest()[:16]


def _guests(event: dict) -> list[dict]:
    """The people invited who are not the calendar's own owner, rooms and resources aside."""
    return [g for g in event.get("guests") or []
            if not g.get("this_calendar") and not g.get("resource") and g.get("email")]


def nowhere(event: dict) -> bool:
    """Whether one event, as `Calendar.events` gives it, is a meeting of ‹his› with nowhere to meet."""
    if event.get("all_day") or not isinstance(event.get("start"), datetime):
        return False
    if event.get("status") == "cancelled" or event.get("kind") not in ("default", "", None):
        return False
    if not event.get("mine") or event.get("my_response") == "declined":
        return False
    if not _guests(event):
        return False
    return not has_place(event.get("where") or "", event.get("description") or "",
                         event.get("video") or "")


def _day_words(start: datetime, now: datetime) -> str:
    if start.date() == now.date():
        return "today"
    if start.date() == (now + timedelta(days=1)).date():
        return "tomorrow"
    return start.strftime("%A")


def _who(event: dict) -> str:
    names = [g.get("name") or g.get("email") for g in _guests(event)]
    if len(names) <= 3:
        return ", ".join(names)
    return ", ".join(names[:3]) + f" and {len(names) - 3} more"


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
    main_id = str((await calendar.about("primary")).get("id") or "")
    got = await calendar.events(now, now + timedelta(days=DAYS), calendar_ids=["primary"], limit=250)
    held = await sync_to_async(kept)(who)
    out = []
    for one in got.get("events") or []:
        if one["start"] <= now:
            continue
        key = _key(one)
        line = held.get(key) or {}
        if line.get("put"):
            continue
        if line.get("added"):
            if time.time() - float(line["added"]) > 12 * 3600:
                continue  # said as done the day it was pressed, and not again
        elif not nowhere(one):
            continue
        start = one["start"].astimezone(zone)
        end = one["end"].astimezone(zone) if isinstance(one.get("end"), datetime) else None
        out.append({
            "key": key, "title": one.get("title") or "a meeting",
            "calendar_id": one.get("calendar_id") or main_id, "event_id": one.get("id") or "",
            "start": start.timestamp(), "day": _day_words(start, now),
            "time": f"{start:%H:%M}" + (f" to {end:%H:%M}" if end and end.date() == start.date() else ""),
            "who": _who(one), "guests": len(_guests(one)), "link": one.get("link") or "",
            "added": float(line.get("added") or 0) or None, "video": str(line.get("video") or ""),
        })
    if not out:
        return None
    out.sort(key=lambda i: i["start"])
    return {"items": out[:MOST], "count": len(out)}


async def again(who, brief: dict, google=None) -> None:
    """The section as the page opens, put on the brief it is sent with; gone when off or empty."""
    from asgiref.sync import sync_to_async

    brief.pop("no_place", None)
    try:
        if who is None or not await sync_to_async(on)(who):
            return
        got = await found(who, google)
    except Exception:  # noqa: BLE001 - the rest of the brief is drawn without it
        log.exception("the meetings with nowhere to meet could not be read")
        return
    if got:
        from . import evolution

        brief["no_place"] = {"ok": True, "source": "Calendar", **got}
        await sync_to_async(evolution.used)(SWITCH, "shown", who=who,
                                           detail=f"{got['count']} meetings with nowhere to meet")


class Refused(ValueError):
    """What cannot be done with a meeting's line, in a sentence."""


async def act(who, google, key: str, what: str, *, calendar_id: str = "", event_id: str = "") -> dict:
    """Add a Meet link (add), Not needed (put away), or Undo."""
    from asgiref.sync import sync_to_async

    from . import evolution

    held = await sync_to_async(kept)(who)
    if what == "add":
        if google is None or google(who) is None:
            raise Refused("Google is not connected.")
        calendar = google(who).calendar
        event = await calendar.event(calendar_id or "primary", event_id)
        if _key(event) != key and _key({**event, "calendar_id": calendar_id}) != key:
            raise Refused("That meeting is not on the calendar as it was; open the brief again.")
        if event.get("video"):
            made = event  # it has one already: nothing is asked of Google, nobody is told twice
        elif not nowhere(event):
            raise Refused("That meeting has somewhere to meet now; open the brief again.")
        else:
            made = await calendar.add_video(calendar_id or "primary", event_id, notify=True)
        if not made.get("video"):
            raise Refused("Google did not give it a Meet link. Add one in Google Calendar.")
        held[key] = {"added": time.time(), "video": made.get("video") or ""}
        await sync_to_async(_keep)(who, held)
        await sync_to_async(evolution.used)(SWITCH, "added", who=who,
                                           detail=f"a Meet link on {str(event.get('title') or '')[:60]}")
        return {"ok": True, "video": made.get("video") or ""}
    if what == "put":
        held[key] = {**(held.get(key) or {}), "put": time.time()}
        await sync_to_async(_keep)(who, held)
        await sync_to_async(evolution.used)(SWITCH, "put", who=who,
                                           detail="said a meeting needs no place or link")
        return {"ok": True}
    line = dict(held.get(key) or {})
    line.pop("put", None)
    if line:
        held[key] = line
    else:
        held.pop(key, None)
    await sync_to_async(_keep)(who, held)
    return {"ok": True}


__all__ = ["ACTS", "KEPT", "SWITCH", "TITLE", "Refused", "act", "again", "found", "nowhere", "on"]
