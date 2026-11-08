"""If I have not answered it, remind me: one press on an email that asks ‹him› something, and Rouh looks
the next working morning, reminding ‹him› only if ‹he› has not answered.

Built by the nightly feature run, night 33 of this Rouh (the ledger's night 37), 8 November 2026
(task 94). An email read on the inbox card that asks ‹owner› something, on a phone between two
meetings, is meant to be answered later, and then is not. Remind me (night 34,
`rouh/inbox_remind.py`) brings an email back at a time whatever happened, so it comes back for emails
‹he› answered long ago, from ‹his› laptop or ‹his› phone. If it does not come (night 36,
`rouh/promise_watch.py`) looks first, but for what others promised ‹him›.

So, while its switch is on, an email opened on the inbox card (Rouh's own inbox or the person's
read-only one), from a person, to ‹him›, that asks ‹him› something (`ghosts.the_ask`, plain rules,
no model), has one more row: what they asked, and **If I have not answered by tomorrow, remind me**
(Monday when the next day is a weekend). A press makes one reminder on Clockwork
(`rouh/reminders.py`), in the conversation the card is in, at 09:00 that morning on ‹his› clock. At
that moment Rouh is handed the email by its sender, subject, conversation and id, and told to look
whether ‹he› has written in that conversation, or to that sender, since: when ‹he› has, it says so
in one line; when not, it says what they asked and how long ago, and offers to draft the answer,
sending nothing unless asked. Nothing in the mailbox changes, so it works on the read-only inbox too;
the reminder is seen, changed or stopped on Clockwork like any other.

**Whose.** The reminder is the person's own (`org_id` and `user_id`), made in the card's thread.

**Its switch** is `answer_watch` (`rouh/switches.py`): off, the card has no such row and the ask is
refused.
"""
from __future__ import annotations

import logging
from datetime import datetime, time as clock_time, timedelta

log = logging.getLogger("rouh.answer_watch")

SWITCH = "answer_watch"
TITLE = ("If I have not answered it, remind me: one press on an email that asks you something, and Rouh looks "
         "the next morning and reminds you only if you have not answered")
LOOK_AT = 9
MOST_PEOPLE = 8


def on(who) -> bool:
    from . import switches

    if who is None:
        return False
    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def asked(found: dict, own: list[str]) -> str:
    """What an email from a person, to the person, asks of them, or "" when it is not such an email."""
    from . import ghosts
    from .inbox import message_text, sender

    labels = set(found.get("labels") or [])
    if labels & {"SENT", "DRAFT", "SPAM", "TRASH"}:
        return ""
    if found.get("list_unsubscribe") or found.get("list_id") or found.get("auto_submitted", "no") not in ("", "no") \
            or (found.get("precedence") or "").lower() in ("bulk", "list", "junk"):
        return ""
    _name, address = sender(found.get("from"))
    mine = {a.lower() for a in own if a}
    if not address or address.lower() in mine or ghosts.is_machine(address):
        return ""
    to, cc = ghosts.people(found.get("to", "")), ghosts.people(found.get("cc", ""))
    if len(to) + len(cc) > MOST_PEOPLE or (mine and not any(a.lower() in mine for _n, a in to)):
        return ""
    if found.get("calendar"):
        return ""
    return ghosts.the_ask(message_text(found))


def moment(now: datetime) -> datetime:
    """09:00 the next working morning on the person's clock: tomorrow, or Monday after a Friday."""
    day = now.date() + timedelta(days=1)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return datetime.combine(day, clock_time(LOOK_AT, 0), now.tzinfo)


def _day(at: datetime, now: datetime) -> str:
    return "tomorrow" if (at.date() - now.date()).days == 1 else f"{at:%A}"


def shown(who, found: dict, own: list[str]) -> dict | None:
    """What an opened message offers: {ask, at, label}, or None."""
    from . import clock

    if not on(who):
        return None
    ask = asked(found, own)
    if not ask:
        return None
    now = datetime.now(clock.zone_of(who))
    at = moment(now)
    return {"ask": ask, "at": f"{at:%A} {at.day} {at:%B}, {at:%H:%M}",
            "label": f"If I have not answered by {_day(at, now)}, remind me"}


def make(who, *, found: dict, own: list[str], chat: str, inbox: str, read_only: bool) -> dict:
    """The reminder for one email's question. Raises ValueError in words to say back."""
    from . import clock, composing, evolution, reminders
    from .inbox import sender

    ask = asked(found, own)
    if not ask:
        raise ValueError("This email does not ask you anything.")
    zone = clock.zone_of(who)
    now = datetime.now(zone)
    at = moment(now)
    name, address = sender(found.get("from"))
    who_from = name or address or "an unknown sender"
    subject = composing.one_line(found.get("subject")) or "(no subject)"
    message_id = str(found.get("id") or "")
    thread_id = str(found.get("thread_id") or "")
    where = (f"my own inbox {inbox} (connected read-only)" if read_only
             else f"the inbox {inbox}" if inbox else "Rouh's inbox")
    sent = datetime.fromtimestamp(float(found.get("at") or 0), zone) if found.get("at") else None
    title = f"Answered? {who_from}: {subject}"[:200]
    what = (f"If I have not answered it, remind me, pressed on the inbox card: {who_from}"
            + (f" <{address}>" if address and address != who_from else "")
            + (f" wrote on {sent:%A} {sent.day} {sent:%B}" if sent else " wrote")
            + f', subject "{subject}", in {where}, message id {message_id}'
            + (f", conversation {thread_id}" if thread_id else "")
            + f', and asked: "{ask}" Look in that inbox whether I have written in that conversation, or to '
            f"{address or who_from}, since that email (mail_find, read_mail; my own sent mail counts, from any "
            "of my addresses). If I have, say so in one short line and nothing else. If I have not, remind me "
            "plainly what they asked and how long ago, and offer to draft the answer; do not send anything "
            "unless I ask.")
    row = reminders.add(who, what=what, title=title, kind="remind", chat_id=chat or "",
                        first=at, repeat="once",
                        asked=[f"Remind me if I have not answered {who_from} by {_day(at, now)}"])
    evolution.used(SWITCH, "watched", who=who, detail=f"look {at.date().isoformat()}")
    said = (f"Rouh will look on {at:%A} at {at:%H:%M} and remind you only if you have not answered "
            f"{name or address or 'them'} by then.")
    return {"id": message_id, "watched": True, "said": said, "reminder": getattr(row, "id", None)}


__all__ = ["LOOK_AT", "SWITCH", "TITLE", "asked", "make", "moment", "on", "shown"]
