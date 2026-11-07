"""Guests who have not said yes: ‹his› meetings today and tomorrow that nobody invited has accepted,
or that somebody declined, said in the morning brief, with a note to exactly those guests one press
away.

Built by the nightly feature run, night 34, 6 November 2026 (task 94). A meeting ‹he› organises
looks the same in the calendar whether its guests said yes or never answered. Google emails ‹him›
a decline, among the rest of ‹his› mail, and says nothing at all about a guest who never
answered, so the first sign that a call will not happen is an empty call at its start, or a guest
who had never seen the invitation. The guests' answers are in every event Rouh reads
(`responseStatus`), and nothing read them.

So, while its switch is on, the morning brief has a section **Guests who have not said yes**, read
afresh from Google each time the page opens, with no model:

- **Which.** Timed meetings from now to the end of tomorrow on ‹his› main calendar that ‹he›
  organises, not declined or cancelled by ‹him›, with at least one guest who is not ‹him› (rooms
  and optional guests aside), where somebody declined, or nobody has accepted or said maybe.
- **What it says.** The meeting, its day and time, and who declined and who has not answered, by
  name; a meeting nobody has accepted says so first.
- **Write to them in Gmail** opens Gmail's own new-message window in ‹his› own mailbox, to exactly
  the guests who have not said yes, with the meeting and its time filled in, for ‹him› to send or
  not. **Not needed** (‹he› already knows they are coming) puts the line away, with Undo. A line
  put away is not said again for that meeting.

**Whose.** The connected Google account's main calendar (`org_id` and `user_id`) and ‹his› own
settings (`user_settings`, `not_said_yes`).

**Its switch** is `not_said_yes` (`rouh/switches.py`): off, the section is not there and the route
refuses.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import datetime, timedelta
from urllib.parse import quote, urlencode

log = logging.getLogger("rouh.not_said_yes")

SWITCH = "not_said_yes"
TITLE = ("Guests who have not said yes: your meetings today and tomorrow that nobody has accepted, "
         "or somebody declined, in the morning brief")
#: The person's own setting: {line key: {"put": seconds}}.
KEPT = "not_said_yes"
MOST = 6
ACTS = ("put", "undo", "wrote")
YES = ("accepted", "tentative")


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


def _key(event: dict) -> str:
    ident = f"{event.get('calendar_id')}|{event.get('id')}"
    return "y-" + hashlib.sha256(ident.encode()).hexdigest()[:16]


def guests(event: dict) -> list[dict]:
    """The people asked to come who are not the calendar's own owner: rooms, resources and
    optional guests aside."""
    return [g for g in event.get("guests") or []
            if not g.get("this_calendar") and not g.get("resource") and not g.get("optional")
            and g.get("email")]


def _name(guest: dict) -> str:
    return str(guest.get("name") or guest.get("email") or "").strip()


def unanswered(event: dict) -> dict | None:
    """{declined, waiting, nobody} for one event, as `Calendar.events` gives it, when it is a meeting
    of ‹his› whose guests have not said yes; None when it is not one, or all is well."""
    if event.get("all_day") or not isinstance(event.get("start"), datetime):
        return None
    if event.get("status") == "cancelled" or event.get("kind") not in ("default", "", None):
        return None
    if not event.get("mine") or event.get("my_response") == "declined":
        return None
    asked = guests(event)
    if not asked:
        return None
    declined = [g for g in asked if g.get("response") == "declined"]
    waiting = [g for g in asked if g.get("response") not in YES and g.get("response") != "declined"]
    nobody = not any(g.get("response") in YES for g in asked)
    if not declined and not nobody:
        return None
    return {"declined": declined, "waiting": waiting, "nobody": nobody, "asked": asked}


def _names(people: list[dict]) -> str:
    names = [_name(g) for g in people]
    if len(names) <= 3:
        return " and ".join(names) if len(names) <= 2 else ", ".join(names[:-1]) + " and " + names[-1]
    return ", ".join(names[:3]) + f" and {len(names) - 3} more"


def _day_words(start: datetime, now: datetime) -> str:
    if start.date() == now.date():
        return "today"
    return "tomorrow"


def compose_link(inbox: str, to: list[str], title: str, when: str, *, declined: bool = False) -> str:
    """Gmail's own new-message window in ‹his› mailbox, to those guests, about the meeting, filled
    in for ‹him› to send or not: to the ones who have not answered, or, when every one left has
    declined, to them, asking for another time."""
    if declined:
        body = (f"Hi,\n\nI saw you can't make \"{title}\", {when}. "
                "Would another time suit you, or should we go ahead without you?\n\nThanks\n")
    else:
        body = (f"Hi,\n\nJust checking you can make \"{title}\", {when}. "
                "Could you accept the invitation, or let me know if another time suits you "
                "better?\n\nThanks\n")
    asked = {"view": "cm", "fs": "1", "to": ",".join(to), "su": title, "body": body}
    if inbox:
        asked = {"authuser": inbox, **asked}
    return "https://mail.google.com/mail/?" + urlencode(asked, quote_via=quote)


async def found(who, google, *, now: datetime | None = None) -> dict | None:
    """{items, count} for the brief, or None when there is nothing to say."""
    from asgiref.sync import sync_to_async

    from . import clock, inboxes

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
    mine = await sync_to_async(inboxes.theirs)(who)
    inbox = mine[0].email if mine else ""
    out = []
    fine = 0
    for one in got.get("events") or []:
        if one["start"] <= now:
            continue
        key = _key(one)
        if (held.get(key) or {}).get("put"):
            continue
        said = unanswered(one)
        if said is None:
            if one.get("mine") and guests(one) and not one.get("all_day") \
                    and one.get("my_response") != "declined":
                fine += 1  # his meeting with guests, and somebody has said yes
            continue
        start = one["start"].astimezone(zone)
        end = one["end"].astimezone(zone) if isinstance(one.get("end"), datetime) else None
        day = _day_words(start, now)
        at = f"{start:%H:%M}" + (f" to {end:%H:%M}" if end and end.date() == start.date() else "")
        title = one.get("title") or "a meeting"
        # The ones who have not answered are asked to; when nobody is left to answer, the ones
        # who declined are asked for another time.
        ask = said["waiting"] or said["declined"]
        out.append({
            "key": key, "title": title, "start": start.timestamp(), "day": day, "time": at,
            "nobody": said["nobody"], "asked": len(said["asked"]),
            "declined": _names(said["declined"]) if said["declined"] else "",
            "declined_n": len(said["declined"]),
            "waiting": _names(said["waiting"]) if said["waiting"] else "",
            "waiting_n": len(said["waiting"]),
            "link": one.get("link") or "",
            "write": compose_link(inbox, [g["email"] for g in ask], title,
                                  f"{day} at {start:%H:%M}", declined=not said["waiting"]),
            "write_to": "declined" if not said["waiting"] else "waiting",
            "calendar_id": one.get("calendar_id") or main_id,
        })
    if not out:
        return None
    out.sort(key=lambda i: i["start"])
    return {"items": out[:MOST], "count": len(out), "fine": fine}


async def again(who, brief: dict, google=None) -> None:
    """The section as the page opens, put on the brief it is sent with; gone when off or empty."""
    from asgiref.sync import sync_to_async

    brief.pop("not_said_yes", None)
    try:
        if who is None or not await sync_to_async(on)(who):
            return
        got = await found(who, google)
    except Exception:  # noqa: BLE001 - the rest of the brief is drawn without it
        log.exception("the guests who have not said yes could not be read")
        return
    if got:
        from . import evolution

        brief["not_said_yes"] = {"ok": True, "source": "Calendar", **got}
        await sync_to_async(evolution.used)(SWITCH, "shown", who=who,
                                           detail=f"{got['count']} meetings whose guests have not said yes")


def act(who, key: str, what: str) -> dict:
    """Not needed (put away), Undo, or Write to them pressed (counted, nothing kept)."""
    from . import evolution

    if what == "wrote":
        evolution.used(SWITCH, "wrote", who=who,
                       detail="opened a note to guests who had not said yes")
        return {"ok": True}
    held = kept(who)
    if what == "put":
        held[key] = {"put": time.time()}
        _keep(who, held)
        evolution.used(SWITCH, "put", who=who, detail="said the guests of a meeting are coming")
        return {"ok": True}
    held.pop(key, None)
    _keep(who, held)
    return {"ok": True}


__all__ = ["ACTS", "KEPT", "SWITCH", "TITLE", "act", "again", "compose_link", "found", "guests",
           "on", "unanswered"]
