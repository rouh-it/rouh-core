"""Invited Rouh, not you: a meeting invitation sent to Rouh's inbox and not to ‹him›, told the moment it
comes, with one press that puts it on ‹his› calendar.

Built by the nightly feature run, night 45 of the ledger (16 November 2026, task 94).
People arrange meetings with Rouh the way they would with an assistant: Rouh writes for ‹owner›, they
answer with a time, and the invitation goes back to the address that wrote to them, Rouh's, and to
nobody else. Google then puts it on the calendar of the account it was sent to, or nowhere, and ‹his›
own calendar looks free at that time. Invitations not in your calendar (night 33,
`rouh/invite_missing.py`) reads only ‹his› own inboxes; in Rouh's inbox the invitation became a mail
case like any email, and nothing looked at ‹his› calendar.

So, while its switch is on, when an email from somebody else reaches Rouh's inbox
(`rouh/mail_alerts.py`) carrying a calendar invitation (`rouh/invites.py`, the same reader the
mail uses) for a time still to come, and none of ‹his› own addresses (`my_card.own_addresses`) is
among its guests, Rouh reads ‹his› usual calendar (`Calendar.usual`) around that time. When the
meeting is not there, by its UID or by its title at its start, a notice says so at once: who invited
Rouh, to what, when on ‹his› clock, and where or on which call. Its button:

- **Put it on my calendar** puts it on ‹his› calendar as the same meeting, by its UID, as Gmail does
  (Google's events.import), so a later change or cancellation from the organiser finds it. Nobody is
  emailed.

A notice left alone changes nothing; the email goes on to its mail case as before. The same meeting
is told once, ever. An invitation ‹he› is on, a cancellation, one for a time already gone, and one
already on ‹his› calendar say nothing.

No model is asked.

**Whose.** Rouh's connected inbox and calendars and the person it belongs to, by `org_id` and
`user_id`; what was told is kept in `user_settings` (`rouh_invited`), at most the last `KEPT`.

**Its switch** is `rouh_invited` (`rouh/switches.py`): off, nothing is read and the button's address
says it is switched off.
"""
from __future__ import annotations

import email.utils
import hashlib
import json
import logging
import time
from datetime import datetime, timedelta

log = logging.getLogger("rouh.rouh_invited")

SWITCH = "rouh_invited"
TITLE = "Invited Rouh, not you: an invitation sent only to Rouh's inbox, told at once"

HELD = "rouh_invited"
KEPT = 200


def on(who) -> bool:
    from . import switches

    if who is None:
        return False
    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def _ids(who) -> tuple[str, str]:
    return str(getattr(who, "user_id", "") or ""), str(getattr(who, "org_id", "") or "")


def _held(who) -> dict:
    from .models import UserSetting

    user_id, org_id = _ids(who)
    value = (UserSetting.objects.filter(user_id=user_id, org_id=org_id, name=HELD)
             .values_list("value", flat=True).first())
    try:
        held = json.loads(value) if value else {}
    except (TypeError, ValueError):
        held = {}
    return held if isinstance(held, dict) else {}


def _put(who, held: dict) -> None:
    from .models import UserSetting

    user_id, org_id = _ids(who)
    if len(held) > KEPT:
        held = dict(sorted(held.items(), key=lambda kv: kv[1].get("at") or 0)[-KEPT:])
    UserSetting.objects.bulk_create(
        [UserSetting(user_id=user_id, org_id=org_id, name=HELD, value=json.dumps(held), updated_at=time.time())],
        update_conflicts=True, unique_fields=["user_id", "name"], update_fields=["org_id", "value", "updated_at"])


def key_of(uid: str) -> str:
    return "ri-" + hashlib.sha256(str(uid).encode()).hexdigest()[:16]


def one(who, key: str) -> dict | None:
    got = _held(who).get(key)
    return got if isinstance(got, dict) else None


def _mine(who) -> set[str]:
    from . import my_card

    user_id, org_id = _ids(who)
    out = {a.lower() for a in my_card.own_addresses(user_id, org_id) if a}
    email_of = str(getattr(who, "email", "") or "").lower()
    if email_of:
        out.add(email_of)
    return out


def invitation(text: str, zone, now: datetime, mine: set[str]):
    """The meeting to tell from an invitation's text, or None: a new invitation for a time still to
    come, from somebody else, with none of the person's addresses among its guests."""
    from . import invites

    for found in invites.parse(text, zone):
        if found.method not in ("REQUEST", "PUBLISH", "ADD") or found.cancelled:
            continue
        if not found.uid or not isinstance(found.start, datetime) or found.start <= now:
            continue
        if found.organiser and found.organiser.email.lower() in mine:
            continue
        if any(g.email.lower() in mine for g in found.guests if g.email):
            continue
        return found
    return None


async def _on_calendar(calendar, target: str, found) -> bool:
    start, end = found.start, found.end if isinstance(found.end, datetime) else found.start
    got = await calendar.events(start - timedelta(minutes=1), end + timedelta(minutes=1),
                                calendar_ids=[target], limit=100)
    for ev in got.get("events") or []:
        if ev.get("ical_uid") and ev["ical_uid"] == found.uid:
            return True
        if isinstance(ev.get("start"), datetime) and abs((ev["start"] - start).total_seconds()) < 60 \
                and (ev.get("title") or "").strip().lower() == (found.title or "").strip().lower():
            return True
    return False


def _day(start: datetime, now: datetime) -> str:
    if start.date() == now.date():
        return "today"
    if start.date() == (now + timedelta(days=1)).date():
        return "tomorrow"
    if start - now < timedelta(days=6):
        return start.strftime("%A")
    return start.strftime("%A %-d %B")


async def seen(who, message: dict, services, *, mailbox: str = "") -> str:
    """An invitation in Rouh's inbox that leaves the person out, told: the sentence for the mail log,
    or "" when there is nothing to tell or the switch is off."""
    import asyncio

    from asgiref.sync import sync_to_async

    from . import clock, evolution, notices

    if not message.get("calendar") or services is None:
        return ""
    if not await asyncio.to_thread(on, who):
        return ""
    mine = await sync_to_async(_mine)(who)
    sender = email.utils.parseaddr(message.get("from", ""))[1].lower()
    if not sender or sender in mine or (mailbox and sender == mailbox.lower()):
        return ""
    zone = clock.zone_of(who)
    now = datetime.now(zone)
    found = None
    for part in message.get("calendar") or []:
        try:
            text = await services.gmail.calendar_text(message.get("id") or "", part)
        except Exception:  # noqa: BLE001 - one part that cannot be read leaves the rest
            continue
        found = invitation(text, zone, now, mine)
        if found is not None:
            break
    if found is None:
        return ""
    key = key_of(found.uid)
    held = await sync_to_async(_held)(who)
    if key in held:
        return ""
    calendar = services.calendar
    target = await calendar.usual()
    if await _on_calendar(calendar, target, found):
        return ""
    start = found.start.astimezone(zone)
    end = found.end.astimezone(zone) if isinstance(found.end, datetime) else None
    organiser = found.organiser
    by = (organiser.name or organiser.email) if organiser else (
        email.utils.parseaddr(message.get("from", ""))[0] or sender)
    title = found.title or str(message.get("subject") or "") or "a meeting"
    when = f"{_day(start, now)} at {start:%H:%M}" + (f" to {end:%H:%M}" if end and end.date() == start.date() else "")
    text = f"{by} sent the invitation for “{title[:120]}”, {when}, to Rouh only, and it is not on your calendar."
    if found.where:
        text += f" Where: {found.where[:120]}."
    elif found.call:
        text += " It has a call link."
    held[key] = {
        "uid": found.uid, "title": title[:200], "start": found.start.isoformat(),
        "end": (found.end if isinstance(found.end, datetime) else found.start + timedelta(hours=1)).isoformat(),
        "where": (found.where or found.call or "")[:300], "call": found.call or "",
        "description": (found.description or "")[:6000],
        "organiser": organiser.email if organiser else sender,
        "organiser_name": organiser.name if organiser else "",
        "guests": [{"email": g.email, "name": g.name,
                    "response": {"ACCEPTED": "accepted", "DECLINED": "declined",
                                 "TENTATIVE": "tentative"}.get(g.answer, "needsAction")}
                   for g in found.guests if g.email][:50],
        "sequence": found.sequence, "calendar": target, "mailbox": mailbox, "by": by,
        "at": time.time(), "added": False,
    }
    await sync_to_async(_put)(who, held)
    link = f"/mail/rouh-invited/{key}"
    said = await notices.notify(title=f"{by} invited Rouh, not you", body=text, link=link,
                                link_label="Put it on my calendar",
                                links=[{"label": "Put it on my calendar", "href": link}],
                                kind="mail", key=key, who=who)
    if said is None:
        return ""
    await sync_to_async(evolution.used)(SWITCH, "told", who=who, detail=f"{title[:60]}: invited Rouh only")
    return f"The invitation to {title[:80]!r} left the person out and is not on their calendar: told in a notice."


async def add(who, key: str, services) -> tuple[bool, str]:
    """Put it on my calendar, pressed: (done, what to say)."""
    from asgiref.sync import sync_to_async

    from . import evolution, notices

    told = await sync_to_async(one)(who, key)
    if told is None:
        return False, "That is not an invitation Rouh told you about."
    title = told.get("title") or "The meeting"
    if told.get("added"):
        return True, f"“{title}” is already on your calendar."
    if services is None:
        return False, "Google is not connected, so it could not be put on your calendar."
    description = "\n\n".join(x for x in (
        f"Call: {told['call']}" if told.get("call") and told["call"] not in (told.get("description") or "") else "",
        told.get("description") or "",
        f"Put on your calendar by Rouh from the invitation {told.get('by') or 'they'} sent to Rouh only.") if x)
    made = await services.calendar.import_invite(
        uid=told["uid"], title=title, start=datetime.fromisoformat(told["start"]),
        end=datetime.fromisoformat(told["end"]), where=told.get("where") or "", description=description,
        organiser=told.get("organiser") or "", organiser_name=told.get("organiser_name") or "",
        guests=told.get("guests") or [], sequence=int(told.get("sequence") or 0),
        calendar_id=told.get("calendar") or "primary")
    held = await sync_to_async(_held)(who)
    if key in held:
        held[key] = dict(held[key], added=True, added_at=time.time(), link=made.get("link") or "")
        await sync_to_async(_put)(who, held)
    await sync_to_async(evolution.used)(SWITCH, "added", who=who, detail=f"{title[:60]}: put on the calendar")
    said = f"“{title}” is on your calendar now, as the same meeting, so a change from the organiser reaches it. Nobody was emailed."
    links = [{"label": "Open it in Calendar", "href": made["link"]}] if made.get("link") else []
    await notices.notify(title="Put on your calendar", body=said, kind="mail", key=key + "-added",
                         links=links, link=made.get("link") or "", link_label="Open it in Calendar" if links else "",
                         who=who)
    return True, said


__all__ = ["HELD", "KEPT", "SWITCH", "TITLE", "add", "invitation", "key_of", "on", "one", "seen"]
