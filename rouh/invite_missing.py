"""Invitations not in your calendar: a meeting invitation in ‹his› mail that never reached ‹his›
calendar, said in the morning brief, with one press to put it there.

Built by the nightly feature run, night 33, 4 November 2026 (task 94). Google Calendar can add an
invitation to the calendar by itself only when the sender is known, or only once ‹he› answers the
email ("Add invitations to my calendar", a setting since July 2022, which many organisations made
their default against invitation spam), so an invitation from somebody ‹he› has never written to
(a new client, a conference, a supplier on Outlook) can stay an email with an invite.ics on it,
and the calendar looks free at that time. ‹He› sees the email once, among the rest; nobody
says that the meeting is not on the calendar, and the first sign is the reminder that never comes.

So, while its switch is on, the morning brief has a section **Invitations not in your calendar**,
read afresh each time the page opens, with no model:

- **Which.** Invitations in ‹his› own inboxes (the read-only mailboxes, `rouh/inboxes.py`) from the
  last `DAYS` days, read from their calendar part (`rouh/invites.py`): a new or changed invitation
  for a time still to come, from somebody else, not cancelled since, whose meeting is on none of
  the calendars the connected Google account sees, by its UID or by its title and start.
- **What it says.** The meeting, its day and time on ‹his› clock, who sent it, where or the call,
  and which inbox it came to.
- **Put it in my calendar** puts it on the main calendar as the same meeting, by its UID, the way
  Gmail does itself (Google's events.import): a later change or cancellation from the sender then
  finds it. Nobody is emailed; the email's own Yes or No still answers the sender.
  **Not needed** puts the line away, with Undo.

**Whose.** ‹His› own inboxes, read only, and the connected account's calendars, by `org_id` and
`user_id`; what ‹he› put away or put in is ‹his› own setting (`user_settings`, `invite_missing`).

**Its switch** is `invite_missing` (`rouh/switches.py`): off, the section is not there and the
route refuses.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import datetime, timedelta

from . import invites

log = logging.getLogger("rouh.invite_missing")

SWITCH = "invite_missing"
TITLE = ("Invitations not in your calendar: a meeting invitation in your mail that never reached "
         "your calendar, in the morning brief, with one press to put it there")
#: The person's own setting: {line key: {"put": seconds} or {"added": seconds, "link": ...}}.
KEPT = "invite_missing"
#: How far back mail is read, in days; how far ahead a meeting is looked at; how much is read and shown.
DAYS = 21
AHEAD = 60
MOST = 30
SHOWN = 6
ACTS = ("add", "put", "undo")
#: The searches that find invitations: Gmail names a calendar part invite.ics or the like.
SEARCHES = ("filename:ics", "subject:invitation")
#: How long what was read is kept before it is read again, in seconds.
FRESH = 300

_messages: dict[str, dict] = {}
_found: dict[str, tuple[float, list[dict]]] = {}


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


def key_of(uid: str) -> str:
    return "i-" + hashlib.sha256(uid.encode()).hexdigest()[:16]


async def _read(who, zone) -> list[dict]:
    """Every invitation in the person's own inboxes in the last `DAYS` days, the newest version of
    each meeting: [{invite, message, inbox, at}], kept for `FRESH` seconds."""
    from asgiref.sync import sync_to_async

    from . import inboxes

    held = _found.get(str(who.user_id))
    if held and time.time() - held[0] < FRESH:
        return held[1]
    newest: dict[str, dict] = {}
    for box in await sync_to_async(inboxes.theirs)(who):
        if box.needs_reconnect:
            continue
        try:
            opened = await sync_to_async(inboxes.open_one)(who, box)
        except Exception as exc:  # noqa: BLE001 - one inbox that cannot be opened leaves the rest
            log.info("%s could not be opened: %r", box.said(), exc)
            continue
        ids: list[str] = []
        for search in SEARCHES:
            try:
                rows = await opened.gmail.recent(MOST, f"newer_than:{DAYS}d {search}")
            except Exception as exc:  # noqa: BLE001
                log.info("the invitations in %s could not be searched: %r", box.said(), exc)
                continue
            ids += [r.get("id") or "" for r in rows if r.get("id") and r.get("id") not in ids]
        for mid in ids[:MOST]:
            cache = f"{box.email}|{mid}"
            if cache not in _messages:
                try:
                    _messages[cache] = await opened.gmail.message(mid)
                except Exception as exc:  # noqa: BLE001
                    log.info("the email %s could not be read: %r", mid, exc)
                    continue
            message = _messages[cache]
            for part in message.get("calendar") or []:
                try:
                    text = await opened.gmail.calendar_text(mid, part)
                except Exception:  # noqa: BLE001
                    continue
                for one in invites.parse(text, zone):
                    if not one.uid or one.recurrence_id:
                        continue
                    was = newest.get(one.uid)
                    at = float(message.get("at") or 0)
                    if was is None or (one.sequence, at) > (was["invite"].sequence, was["at"]):
                        newest[one.uid] = {"invite": one, "message": message, "inbox": box.email, "at": at}
    out = list(newest.values())
    _found[str(who.user_id)] = (time.time(), out)
    return out


def _mine(who, boxes: list[str]) -> set[str]:
    out = {str(b).lower() for b in boxes if b}
    email = str(getattr(who, "email", "") or "").lower()
    if email:
        out.add(email)
    return out


async def _on_calendar(calendar, one: invites.Invite) -> bool:
    """Whether a calendar the account sees already holds this meeting: its UID, or its title at its start."""
    start, end = one.start, one.end or one.start
    if not isinstance(start, datetime):
        return True  # a whole-day entry is not a meeting to miss; nothing is said of it
    got = await calendar.events(start - timedelta(minutes=1), end + timedelta(minutes=1), limit=100)
    for ev in got.get("events") or []:
        if ev.get("ical_uid") and ev["ical_uid"] == one.uid:
            return True
        if isinstance(ev.get("start"), datetime) and abs((ev["start"] - start).total_seconds()) < 60 \
                and (ev.get("title") or "").strip().lower() == (one.title or "").strip().lower():
            return True
    return False


def _service(link: str) -> str:
    """Which service a call link is on, as a person names it."""
    host = link.split("/")[2].lower() if link.count("/") >= 2 else ""
    for part, name in (("teams.", "Teams"), ("zoom.", "Zoom"), ("meet.google", "Google Meet"),
                       ("webex", "Webex"), ("whereby", "Whereby"), ("gotomeeting", "GoTo Meeting"),
                       ("jit.si", "Jitsi"), ("chime", "Chime")):
        if part in host:
            return name
    return host


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
    got = await _read(who, zone)
    if not got:
        return None
    held = await sync_to_async(kept)(who)
    boxes = sorted({g["inbox"] for g in got})
    me = _mine(who, boxes)
    try:
        me.add(str((await calendar.about("primary")).get("id") or "").lower())
    except Exception:  # noqa: BLE001 - the inboxes' own addresses are enough
        pass
    out = []
    for entry in got:
        one: invites.Invite = entry["invite"]
        if one.method not in ("REQUEST", "PUBLISH", "ADD") or one.cancelled:
            continue
        if not isinstance(one.start, datetime) or one.start <= now or one.start > now + timedelta(days=AHEAD):
            continue
        if one.organiser and one.organiser.email.lower() in me:
            continue
        key = key_of(one.uid)
        line = held.get(key) or {}
        if line.get("put"):
            continue
        if line.get("added") and time.time() - float(line["added"]) > 12 * 3600:
            continue
        if not line.get("added") and await _on_calendar(calendar, one):
            continue
        start = one.start.astimezone(zone)
        end = one.end.astimezone(zone) if isinstance(one.end, datetime) else None
        message = entry["message"]
        sender = one.organiser
        out.append({
            "key": key, "title": one.title or message.get("subject") or "a meeting",
            "day": _day_words(start, now), "start": start.timestamp(),
            "time": f"{start:%H:%M}" + (f" to {end:%H:%M}" if end and end.date() == start.date() else ""),
            "who": (sender.name or sender.email) if sender else str(message.get("from") or ""),
            "email": sender.email if sender else "",
            "where": (one.where or "")[:160], "call": one.call,
            "theirs": "" if start.utcoffset() == one.start.utcoffset() else invites.their_clock(one),
            "call_on": _service(one.call),
            "guests": len(one.guests), "inbox": entry["inbox"], "message": message.get("id") or "",
            "subject": str(message.get("subject") or "")[:200],
            "changed": one.sequence > 0,
            "added": float(line.get("added") or 0) or None, "added_link": str(line.get("link") or ""),
        })
    if not out:
        return None
    out.sort(key=lambda i: i["start"])
    return {"items": out[:SHOWN], "count": len(out)}


async def again(who, brief: dict, google=None) -> None:
    """The section as the page opens, put on the brief it is sent with; gone when off or empty."""
    from asgiref.sync import sync_to_async

    brief.pop("invite_missing", None)
    try:
        if who is None or not await sync_to_async(on)(who):
            return
        got = await found(who, google)
    except Exception:  # noqa: BLE001 - the rest of the brief is drawn without it
        log.exception("the invitations not in the calendar could not be read")
        return
    if got:
        from . import evolution

        brief["invite_missing"] = {"ok": True, "source": "Gmail and Calendar", **got}
        await sync_to_async(evolution.used)(SWITCH, "shown", who=who,
                                           detail=f"{got['count']} invitations not in the calendar")


class Refused(ValueError):
    """What cannot be done with an invitation's line, in a sentence."""


async def act(who, google, key: str, what: str) -> dict:
    """Put it in my calendar (add), Not needed (put away), or Undo."""
    from asgiref.sync import sync_to_async

    from . import clock, evolution

    held = await sync_to_async(kept)(who)
    if what == "add":
        if google is None or google(who) is None:
            raise Refused("Google is not connected.")
        zone = clock.zone_of(who)
        entry = next((g for g in await _read(who, zone) if key_of(g["invite"].uid) == key), None)
        if entry is None:
            raise Refused("That invitation is not in your mail as it was; open the brief again.")
        one: invites.Invite = entry["invite"]
        description = "\n\n".join(x for x in (
            f"Call: {one.call}" if one.call and one.call not in (one.description or "") else "",
            (one.description or "")[:6000],
            f"Put on the calendar by Rouh from the invitation emailed to {entry['inbox']}.") if x)
        made = await google(who).calendar.import_invite(
            uid=one.uid, title=one.title or "A meeting", start=one.start, end=one.end or one.start,
            where=one.where or one.call, description=description,
            organiser=one.organiser.email if one.organiser else "",
            organiser_name=one.organiser.name if one.organiser else "",
            guests=[{"email": g.email, "name": g.name,
                     "response": {"ACCEPTED": "accepted", "DECLINED": "declined",
                                  "TENTATIVE": "tentative"}.get(g.answer, "needsAction")}
                    for g in one.guests if g.email], sequence=one.sequence)
        held[key] = {"added": time.time(), "link": made.get("link") or "", "id": made.get("id") or ""}
        await sync_to_async(_keep)(who, held)
        await sync_to_async(evolution.used)(SWITCH, "added", who=who,
                                           detail=f"put {str(one.title or '')[:60]} in the calendar")
        return {"ok": True, "link": made.get("link") or "", "id": made.get("id") or ""}
    if what == "put":
        held[key] = {**(held.get(key) or {}), "put": time.time()}
        await sync_to_async(_keep)(who, held)
        await sync_to_async(evolution.used)(SWITCH, "put", who=who,
                                           detail="said an invitation needs no place in the calendar")
        return {"ok": True}
    line = dict(held.get(key) or {})
    line.pop("put", None)
    if line:
        held[key] = line
    else:
        held.pop(key, None)
    await sync_to_async(_keep)(who, held)
    return {"ok": True}


__all__ = ["ACTS", "KEPT", "SWITCH", "TITLE", "Refused", "act", "again", "found", "key_of", "on"]
