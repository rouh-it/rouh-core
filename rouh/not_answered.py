"""Invitations you have not answered: meetings somebody else invited ‹him› to, today and tomorrow,
that ‹he› never said yes, maybe or no to, said in the morning brief with Yes, Maybe and No.

Built by the nightly feature run, night 36 (Rouh's brief called it night 35), 7 November 2026 (task
94). Night 34's Guests who have not said yes reads the answers of the guests of ‹his› own meetings.
The other side of the same gap was left: a meeting somebody else organises, where ‹he› is the one
who has not answered. Google draws it faded among the rest of the day, nothing lists it, and the
organiser does not know whether ‹he› is coming until the call starts. ‹His› own answer is in every
event Rouh reads (`my_response`), and nothing read it.

So, while its switch is on, the morning brief has a section **Invitations you have not answered**,
read afresh from Google each time the page opens, with no model:

- **Which.** Timed meetings from now to the end of tomorrow on ‹his› main calendar that somebody
  else organises, not cancelled, where ‹his› own answer is still "needs action".
- **What it says.** The meeting, its day and time, who invited ‹him›, and how many of the others
  have said yes, so ‹he› sees who is waiting on ‹him› and how soon.
- **Yes, Maybe and No** answer the invitation in ‹his› calendar, as Google Calendar's own buttons
  do, and Google tells the organiser. **Not now** puts the line away, with Undo, answering nothing.

**Whose.** The connected Google account's main calendar (`org_id` and `user_id`) and ‹his› own
settings (`user_settings`, `not_answered`).

**Its switch** is `not_answered` (`rouh/switches.py`): off, the section is not there and the route
refuses.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import datetime, timedelta

log = logging.getLogger("rouh.not_answered")

SWITCH = "not_answered"
TITLE = ("Invitations you have not answered: meetings somebody else invited you to, today and "
         "tomorrow, that you never answered, in the morning brief with Yes, Maybe and No")
#: The person's own setting: {line key: {"put": seconds} or {"answered": response, "at": seconds}}.
KEPT = "not_answered"
MOST = 6
ANSWERS = {"accepted": "Yes", "tentative": "Maybe", "declined": "No"}
ACTS = (*ANSWERS, "put", "undo")
YES = ("accepted", "tentative")


class Refused(ValueError):
    """What cannot be done with an invitation's line, in a sentence."""


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

    # Lines of meetings long past are let go, so the setting never grows.
    cut = time.time() - 14 * 86400
    held = {k: v for k, v in held.items() if float(v.get("put") or v.get("at") or 0) > cut}
    UserSetting.objects.bulk_create(
        [UserSetting(user_id=str(who.user_id), org_id=who.org_id or "", name=KEPT,
                     value=json.dumps(held), updated_at=time.time())],
        update_conflicts=True, unique_fields=["user_id", "name"],
        update_fields=["org_id", "value", "updated_at"])


def key_of(calendar_id: str, event_id: str) -> str:
    ident = f"{calendar_id}|{event_id}"
    return "a-" + hashlib.sha256(ident.encode()).hexdigest()[:16]


def waiting(event: dict) -> bool:
    """Whether one event, as `Calendar.events` gives it, is an invitation of somebody else's that
    this calendar has not answered."""
    if event.get("all_day") or not isinstance(event.get("start"), datetime):
        return False
    if event.get("status") == "cancelled" or event.get("kind") not in ("default", "", None):
        return False
    if event.get("mine"):
        return False
    return event.get("my_response") == "needsAction"


def _others(event: dict) -> list[dict]:
    return [g for g in event.get("guests") or []
            if not g.get("this_calendar") and not g.get("resource") and g.get("email")]


def _day_words(start: datetime, now: datetime) -> str:
    return "today" if start.date() == now.date() else "tomorrow"


def line(one: dict, now: datetime, zone, main_id: str) -> dict:
    """What the brief draws for one invitation."""
    start = one["start"].astimezone(zone)
    end = one["end"].astimezone(zone) if isinstance(one.get("end"), datetime) else None
    others = [g for g in _others(one) if not g.get("organiser")]
    said_yes = [g for g in others if g.get("response") in YES]
    organiser = (one.get("organiser_name") or one.get("organiser") or "").strip()
    soon = int((start - now).total_seconds() // 60)
    return {
        "key": key_of(one.get("calendar_id") or main_id, one.get("id") or ""),
        "event_id": one.get("id") or "",
        "calendar_id": one.get("calendar_id") or main_id,
        "title": one.get("title") or "a meeting",
        "start": start.timestamp(),
        "day": _day_words(start, now),
        "time": f"{start:%H:%M}" + (f" to {end:%H:%M}" if end and end.date() == start.date() else ""),
        "organiser": organiser,
        "others": len(others),
        "others_yes": len(said_yes),
        "in_minutes": soon,
        "link": one.get("link") or "",
        "video": one.get("video") or "",
    }


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
    until = (now + timedelta(days=2)).replace(hour=0, minute=0, second=0, microsecond=0)
    main_id = str((await calendar.about("primary")).get("id") or "")
    got = await calendar.events(now, until, calendar_ids=["primary"], limit=250)
    held = await sync_to_async(kept)(who)
    out = []
    for one in got.get("events") or []:
        if one["start"] <= now or not waiting(one):
            continue
        item = line(one, now, zone, main_id)
        if held.get(item["key"]):
            continue  # put away, or answered from here and Google not caught up yet
        out.append(item)
    if not out:
        return None
    out.sort(key=lambda i: i["start"])
    return {"items": out[:MOST], "count": len(out)}


async def again(who, brief: dict, google=None) -> None:
    """The section as the page opens, put on the brief it is sent with; gone when off or empty."""
    from asgiref.sync import sync_to_async

    brief.pop("not_answered", None)
    try:
        if who is None or not await sync_to_async(on)(who):
            return
        got = await found(who, google)
    except Exception:  # noqa: BLE001 - the rest of the brief is drawn without it
        log.exception("the invitations not answered could not be read")
        return
    if got:
        from . import evolution

        brief["not_answered"] = {"ok": True, "source": "Calendar", **got}
        await sync_to_async(evolution.used)(SWITCH, "shown", who=who,
                                           detail=f"{got['count']} invitations not answered")


async def act(who, google, key: str, what: str, *, calendar_id: str = "", event_id: str = "") -> dict:
    """Yes, Maybe or No (the answer, in the calendar), Not now (put away), or Undo."""
    from asgiref.sync import sync_to_async

    from . import evolution

    held = await sync_to_async(kept)(who)
    if what in ANSWERS:
        if google is None or google(who) is None:
            raise Refused("Google is not connected.")
        if key_of(calendar_id, event_id) != key:
            raise Refused("That invitation is not the one on the brief; open the brief again.")
        calendar = google(who).calendar
        event = await calendar.event(calendar_id or "primary", event_id)
        if event.get("mine"):
            raise Refused("That is your own meeting: there is no invitation to answer.")
        if event.get("status") == "cancelled":
            raise Refused("That meeting was cancelled.")
        _before, after, _changes = await calendar.change(calendar_id or "primary", event_id,
                                                         response=what, notify=True)
        held[key] = {"answered": what, "at": time.time()}
        await sync_to_async(_keep)(who, held)
        await sync_to_async(evolution.used)(SWITCH, "answered", who=who,
                                           detail=f"{ANSWERS[what]} to an invitation")
        organiser = (after.get("organiser_name") or after.get("organiser") or "").strip()
        return {"ok": True, "answer": ANSWERS[what], "my_response": after.get("my_response") or what,
                "organiser": organiser}
    if what == "put":
        held[key] = {"put": time.time()}
        await sync_to_async(_keep)(who, held)
        await sync_to_async(evolution.used)(SWITCH, "put", who=who,
                                           detail="put an unanswered invitation away")
        return {"ok": True}
    if (held.get(key) or {}).get("put"):
        held.pop(key, None)
        await sync_to_async(_keep)(who, held)
    return {"ok": True}


__all__ = ["ACTS", "ANSWERS", "KEPT", "SWITCH", "TITLE", "Refused", "act", "again", "found",
           "key_of", "line", "on", "waiting"]
