"""Remind me about this email: one press on a message opened on the inbox card brings it back at a
time, as a reminder Rouh acts on.

Built by the nightly feature run, night 34, 6 November 2026 (task 94). An email opened on the inbox
card that cannot be dealt with now was left unread as its own reminder, or forgotten. Gmail's
Snooze takes it out of the inbox and puts it back later, but that is a change to the mailbox, and
the person's own inbox is connected to Rouh read-only, so the card could not offer it.

So, while its switch is on, a message opened on the inbox card (Rouh's own inbox or the person's
read-only one) has **Remind me** with three times: **This evening** (18:00, offered until 17:00),
**Tomorrow morning** (09:00) and **Monday morning** (09:00 next Monday), on the person's clock.
A press makes one reminder on Clockwork (`rouh/reminders.py`), in the conversation the card is
in, that hands Rouh the email at that moment by its sender, subject and id: Rouh reads it then and
says what it asks of the person, on the phone as every reminder is. Nothing in the mailbox
changes, so it works on the read-only inbox too; the reminder is seen, changed or stopped on
Clockwork like any other. No model is asked at the press.

**Whose.** The reminder is the person's own (`org_id` and `user_id`), made in the card's thread.

**Its switch** is `inbox_remind` (`rouh/switches.py`): off, the card has no Remind me and the ask
is refused.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

log = logging.getLogger("rouh.inbox_remind")

SWITCH = "inbox_remind"
TITLE = "Remind me about this email: one press on the inbox card brings an email back at a time"
WHENS = ("evening", "morning", "monday")
WORDS = {"evening": "This evening", "morning": "Tomorrow morning", "monday": "Monday morning"}
#: "This evening" is offered until this hour.
EVENING_UNTIL = 17
EVENING_AT = 18
MORNING_AT = 9


def on(who) -> bool:
    from . import switches

    if who is None:
        return False
    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def moment(when: str, now: datetime) -> datetime | None:
    """When a choice falls, on the clock `now` is on; None for one not offered now."""
    day = now.replace(second=0, microsecond=0)
    if when == "evening":
        if now.hour >= EVENING_UNTIL:
            return None
        return day.replace(hour=EVENING_AT, minute=0)
    if when == "morning":
        return (day + timedelta(days=1)).replace(hour=MORNING_AT, minute=0)
    if when == "monday":
        ahead = (7 - now.weekday()) % 7 or 7
        return (day + timedelta(days=ahead)).replace(hour=MORNING_AT, minute=0)
    return None


def choices(who, now: datetime | None = None) -> list[dict]:
    """The times the card offers now, each {when, label, at}."""
    from . import clock

    now = now or datetime.now(clock.zone_of(who))
    out = []
    for one in WHENS:
        at = moment(one, now)
        if at is not None:
            out.append({"when": one, "label": WORDS[one], "at": f"{at:%a} {at:%H:%M}"})
    return out


def shown(who) -> dict | None:
    """What an opened message offers: {choices}, or None while the switch is off."""
    if not on(who):
        return None
    return {"choices": choices(who)}


def make(who, *, found: dict, when: str, chat: str, inbox: str, read_only: bool) -> dict:
    """The reminder for one email. Raises ValueError in words to say back."""
    from . import clock, composing, evolution, reminders
    from .inbox import sender

    zone = clock.zone_of(who)
    now = datetime.now(zone)
    at = moment(when, now)
    if at is None:
        raise ValueError("That time has passed for today: pick Tomorrow morning or Monday morning.")
    name, address = sender(found.get("from"))
    who_from = name or address or "an unknown sender"
    subject = composing.one_line(found.get("subject")) or "(no subject)"
    message_id = str(found.get("id") or "")
    where = (f"my own inbox {inbox} (connected read-only)" if read_only
             else f"the inbox {inbox}" if inbox else "Rouh's inbox")
    title = f"Back to the email from {who_from}: {subject}"[:200]
    what = (f"Remind me about this email, pressed on the inbox card: from {who_from}"
            + (f" <{address}>" if address and address != who_from else "")
            + f', subject "{subject}", in {where}, message id {message_id}. '
            "Read it then (read_mail, that id and that inbox) and tell me in a few plain words "
            "what it asks of me, and anything newer in its conversation.")
    row = reminders.add(who, what=what, title=title, kind="remind", chat_id=chat or "",
                        first=at.astimezone(zone), repeat="once",
                        asked=[f"Remind me about the email from {who_from} ({WORDS[when].lower()})"])
    evolution.used(SWITCH, "reminded", who=who, detail=f"{WORDS[when].lower()}")
    said = f"Rouh will bring it back {WORDS[when].lower()}, {at:%A} at {at:%H:%M}."
    return {"id": message_id, "reminded": True, "said": said, "reminder": getattr(row, "id", None)}


__all__ = ["SWITCH", "TITLE", "WHENS", "WORDS", "choices", "make", "moment", "on", "shown"]
