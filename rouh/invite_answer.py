"""Answer the invitation from the email: an invitation opened on the inbox card has Yes, Maybe and No,
with ‹his› answer so far, and one press answers it.

Built by the nightly feature run, night 45 of the ledger (16 November 2026, task 94).
‹He› reads mail on Rouh's inbox card. An invitation there was words and an invite.ics: to answer it,
‹he› went to Gmail or Calendar, found the same meeting and pressed Yes there. Invitations you have
not answered (night 36, `rouh/not_answered.py`) answers from the morning brief, for today and tomorrow
only; nothing answered from the email itself.

So, while its switch is on, an email opened on the inbox card that carries a calendar invitation
(`rouh/invites.py`) for a meeting still to come, which is on one of the calendars Rouh's Google account
sees with ‹him› as a guest (found by its UID, `Calendar.events`), shows one line: the meeting, when on
‹his› clock, ‹his› answer so far, and **Yes**, **Maybe** and **No**. A press answers the invitation in
the calendar (`Calendar.change`, `response`), and Google tells the organiser, as Yes in Gmail does.
The line then says the answer. ‹His› own meetings, cancellations, a meeting already gone and an
invitation that is on no calendar (Invitations not in your calendar, night 33, is for that) show
nothing.

The invitation and the meeting are read again on the server when a button is pressed, never taken from
the page. No model is asked and nothing is kept.

**Whose.** The person's own inbox card and Google connection, by `org_id` and `user_id`.

**Its switch** is `invite_answer` (`rouh/switches.py`): off, the line is not there and a press is refused.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

log = logging.getLogger("rouh.invite_answer")

SWITCH = "invite_answer"
TITLE = "Answer the invitation from the email: Yes, Maybe or No on the inbox card"

ANSWERS = {"accepted": "Yes", "tentative": "Maybe", "declined": "No"}
SAID = {"accepted": "you said yes", "tentative": "you said maybe", "declined": "you said no",
        "needsAction": "you have not answered yet", "": "you have not answered yet"}


def on(who) -> bool:
    from . import switches

    if who is None:
        return False
    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


async def _invitation(gmail, found: dict, zone):
    from . import invites

    now = datetime.now(zone)
    for part in found.get("calendar") or []:
        try:
            text = await gmail.calendar_text(found.get("id") or "", part)
        except Exception:  # noqa: BLE001 - one part that cannot be read leaves the rest
            continue
        for one in invites.parse(text, zone):
            if one.method not in ("REQUEST", "PUBLISH", "ADD") or one.cancelled or not one.uid:
                continue
            if not isinstance(one.start, datetime) or one.start <= now:
                continue
            return one
    return None


async def _event(calendar, one) -> dict | None:
    """The meeting on a calendar the account sees, with the person as a guest, or None."""
    end = one.end if isinstance(one.end, datetime) else one.start + timedelta(hours=1)
    got = await calendar.events(one.start - timedelta(minutes=1), end + timedelta(minutes=1), limit=100)
    for ev in got.get("events") or []:
        if ev.get("ical_uid") != one.uid or ev.get("mine") or ev.get("status") == "cancelled":
            continue
        if not any(g.get("this_calendar") for g in ev.get("guests") or []):
            continue
        return ev
    return None


def _when(start: datetime, zone) -> str:
    start = start.astimezone(zone)
    now = datetime.now(zone)
    if start.date() == now.date():
        day = "today"
    elif start.date() == (now + timedelta(days=1)).date():
        day = "tomorrow"
    elif start - now < timedelta(days=6):
        day = start.strftime("%A")
    else:
        day = start.strftime("%A %-d %B")
    return f"{day} at {start:%H:%M}"


async def shown(who, gmail, calendar, found: dict) -> dict | None:
    """The line for an opened email, or None: {said, title, answer, choices}."""
    from asgiref.sync import sync_to_async

    from . import clock

    if not found.get("calendar") or calendar is None:
        return None
    if not await sync_to_async(on)(who):
        return None
    zone = clock.zone_of(who)
    one = await _invitation(gmail, found, zone)
    if one is None:
        return None
    ev = await _event(calendar, one)
    if ev is None:
        return None
    answer = ev.get("my_response") or "needsAction"
    title = ev.get("title") or one.title or "the meeting"
    return {"said": f"Invitation: {title}, {_when(ev['start'], zone)}; {SAID.get(answer, SAID[''])}.",
            "title": title, "answer": answer,
            "choices": [{"when": k, "label": v} for k, v in ANSWERS.items()]}


async def answer(who, gmail, calendar, found: dict, what: str) -> tuple[bool, str, str]:
    """Yes, Maybe or No pressed: (done, what to say, the answer now)."""
    from asgiref.sync import sync_to_async

    from . import clock, evolution

    if what not in ANSWERS:
        return False, "Yes, Maybe or No: say which.", ""
    zone = clock.zone_of(who)
    one = await _invitation(gmail, found, zone)
    if one is None:
        return False, "This email has no invitation still to come.", ""
    ev = await _event(calendar, one)
    if ev is None:
        return False, "That meeting is not on your calendar, so there is no invitation there to answer.", ""
    _before, after, _changes = await calendar.change(ev["calendar_id"], ev["id"], response=what, notify=True)
    now = after.get("my_response") or what
    await sync_to_async(evolution.used)(SWITCH, "answered", who=who,
                                       detail=f"{ANSWERS[what]} to an invitation, from the email")
    organiser = (after.get("organiser_name") or after.get("organiser") or "the organiser").strip()
    said = (f"Invitation: {after.get('title') or one.title}, {_when(after['start'], zone)}; "
            f"{SAID.get(now, SAID[''])}. Google tells {organiser}.")
    return True, said, now


__all__ = ["ANSWERS", "SWITCH", "TITLE", "answer", "on", "shown"]
