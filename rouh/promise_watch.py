"""If it does not come: one press on an email that promises something by a day, and Rouh looks for it
the morning after that day, saying only if it has not come.

Built by the nightly feature run, night 32 of this Rouh (the ledger's night 36), 7 November 2026
(task 94). "I'll send you the signed contract by Friday": read on the inbox card, a promise like
this was something ‹owner› had to remember to check on Saturday. Remind me (night 34,
`rouh/inbox_remind.py`) brings an email back at a time whatever happened; nothing waited for the
promised day and looked first, so a reminder came back for things that had long arrived.

So, while its switch is on, an email opened on the inbox card (Rouh's own inbox or the person's
read-only one) whose sender wrote that they will do something by a day still ahead
(`rouh/mail_promises.py`, plain rules, no model) has one more row: the sentence, and **If it has
not come by <day>, tell me**. A press makes one reminder on Clockwork (`rouh/reminders.py`), in the
conversation the card is in, at 09:00 the morning after that day on the person's clock. At that
moment Rouh is handed the email by its sender, subject and id, and told to look for anything from
that sender since: when something came, it says so in one line; when nothing did, it says what was
promised and when, and offers to draft a short follow-up, sending nothing unless asked. Nothing in
the mailbox changes, so it works on the read-only inbox too; the reminder is seen, changed or
stopped on Clockwork like any other.

**Whose.** The reminder is the person's own (`org_id` and `user_id`), made in the card's thread.

**Its switch** is `promise_watch` (`rouh/switches.py`): off, the card has no such row and the ask is
refused.
"""
from __future__ import annotations

import logging
from datetime import datetime, time as clock_time, timedelta

log = logging.getLogger("rouh.promise_watch")

SWITCH = "promise_watch"
TITLE = ("If it does not come: on an email that promises you something by a day, one press, and Rouh looks "
         "for it the morning after and tells you only if it has not come")
LOOK_AT = 9


def on(who) -> bool:
    from . import switches

    if who is None:
        return False
    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def first(found: dict, zone, now: datetime | None = None) -> dict | None:
    """The first promise in an email, by a day today or ahead: {sentence, due, when}, or None."""
    from . import mail_promises
    from .inbox import message_text

    if "SENT" in (found.get("labels") or []):
        return None
    at = found.get("at")
    try:
        sent = datetime.fromtimestamp(float(at), zone).date() if at else None
    except (TypeError, ValueError):
        sent = None
    now = now or datetime.now(zone)
    sent = sent or now.date()
    for one in mail_promises.promises(message_text(found), sent):
        if one["due"] >= now.date():
            return one
    return None


def moment(due, zone) -> datetime:
    """09:00 the morning after the promised day, on the person's clock."""
    return datetime.combine(due + timedelta(days=1), clock_time(LOOK_AT, 0), zone)


def shown(who, found: dict) -> dict | None:
    """What an opened message offers: {sentence, day, at, label}, or None."""
    from . import clock

    if not on(who):
        return None
    zone = clock.zone_of(who)
    got = first(found, zone)
    if got is None:
        return None
    at = moment(got["due"], zone)
    day = got["due"].strftime("%A")
    if (got["due"] - datetime.now(zone).date()).days >= 7:
        day = f"{got['due']:%A} {got['due'].day} {got['due']:%B}"
    return {"sentence": got["sentence"], "day": day, "due": got["due"].isoformat(),
            "at": f"{at:%A} {at.day} {at:%B}, {at:%H:%M}",
            "label": f"If it has not come by {day}, tell me"}


def make(who, *, found: dict, chat: str, inbox: str, read_only: bool) -> dict:
    """The reminder for one email's promise. Raises ValueError in words to say back."""
    from . import clock, composing, evolution, reminders
    from .inbox import sender

    zone = clock.zone_of(who)
    got = first(found, zone)
    if got is None:
        raise ValueError("This email promises nothing by a day still ahead.")
    at = moment(got["due"], zone)
    name, address = sender(found.get("from"))
    who_from = name or address or "an unknown sender"
    subject = composing.one_line(found.get("subject")) or "(no subject)"
    message_id = str(found.get("id") or "")
    where = (f"my own inbox {inbox} (connected read-only)" if read_only
             else f"the inbox {inbox}" if inbox else "Rouh's inbox")
    sent = datetime.fromtimestamp(float(found.get("at") or 0), zone) if found.get("at") else None
    title = f"Has it come? {who_from}: {subject}"[:200]
    what = (f"If it does not come, pressed on the inbox card: {who_from}"
            + (f" <{address}>" if address and address != who_from else "")
            + (f" wrote on {sent:%A} {sent.day} {sent:%B}" if sent else " wrote")
            + f', subject "{subject}", in {where}, message id {message_id}: "{got["sentence"]}" '
            f"That was due {got['due']:%A} {got['due'].day} {got['due']:%B}. "
            f"Look in that inbox for anything from {address or who_from} since that email (mail_find, "
            "read_mail). If what they promised came, say so in one short line and nothing else. If it did "
            "not, tell me plainly that it has not come, what they promised and when, and offer to draft a "
            "short follow-up; do not send anything unless I ask.")
    row = reminders.add(who, what=what, title=title, kind="remind", chat_id=chat or "",
                        first=at, repeat="once",
                        asked=[f"Tell me if what {who_from} promised by {got['due']:%A} has not come"])
    evolution.used(SWITCH, "watched", who=who, detail=f"due {got['due'].isoformat()}")
    said = (f"Rouh will look for it on {at:%A} at {at:%H:%M} and tell you only if nothing has come "
            f"from {name or address or 'them'}.")
    return {"id": message_id, "watched": True, "said": said, "reminder": getattr(row, "id", None)}


__all__ = ["LOOK_AT", "SWITCH", "TITLE", "first", "make", "moment", "on", "shown"]
