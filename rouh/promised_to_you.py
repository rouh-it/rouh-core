"""Promised to you by mail: asked in words, what people promised the person by email, by a day.

Built by the nightly feature run, night 32 of this Rouh (the ledger's night 36), 7 November 2026
(task 94). "I'll send you the revised offer by Friday", "we will get back to you next week": what
people outside promise ‹owner› by email, by a day, sat in ‹his› inbox, and the first sign one had
not come was ‹him› remembering it. Owed to you (night 18, `rouh/owed_to_you.py`) does this for what
is promised in a recorded meeting, and Promises in Slack (`rouh/slack_promises.py`) for Slack; email
had nothing. Asked "what am I still waiting for?", Rouh could only list recent mail: it could not
tell which emails promised something, by when, and whether it came, without reading every one.

So the tool `promised_to_you`, while its switch is on, reads every mailbox the person has given
Rouh (its own connection and each read-only one, `ghosts.sources`), the inbox of the last `DAYS`
days (or as many as asked, at most `MOST_DAYS`), and finds each sentence a person wrote that
promises something by a day (`rouh/mail_promises.py`, plain rules, no model). It answers:

1. **Late, and nothing since:** the day has passed and the one who promised has not written to
   the person since, in any conversation. The oldest day first.
2. **Coming:** the day is today or ahead.
3. **Late, but they wrote since:** the day has passed and they wrote again, so it may have come;
   named shorter, to check.

Each with who, what they said in their words, the day and how late, the subject and a link to the
conversation in Gmail. Nothing is kept, changed or sent: it reads with GET alone.

**Whose.** The person's own mailboxes, by `org_id` and `user_id`. Refused in a contact's case.

**Its switch** is `promised_to_you` (`rouh/switches.py`): off, the tool says it is switched off.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime

log = logging.getLogger("rouh.promised_to_you")

SWITCH = "promised_to_you"
TITLE = ("Promised to you by mail: asked in words, what people promised you by email by a day, which "
         "days have passed with nothing from them since, and which are coming")
TOOL_NAME = "promised_to_you"
DAYS = 30
MOST_DAYS = 60
MOST_SAID = 15

DESCRIPTION = (
    "What people promised the person by email, by a day: every sentence in their inboxes (Rouh's own and the "
    "person's read-only ones) where somebody wrote they would send, do or answer something by a day (\"I'll "
    "send the offer by Friday\", \"ще ти изпратя договора утре\"), with the day worked out, whether it has "
    "passed, and whether that person has written since. Use it when the person asks what they are still "
    "waiting for, what people promised them, what has not come, or whether somebody delivered what they "
    "said. `days` is how far back (30 unless asked), `person` narrows it to one sender's name or address.")
SCHEMA = {
    "type": "object",
    "properties": {
        "days": {"type": "integer", "description": "How many days back to look, 1 to 60. 30 unless asked."},
        "person": {"type": "string", "description": "Only promises from this person: a name or an address."},
    },
}


def on(who) -> bool:
    from . import switches

    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def said(found: list[dict], zone, *, days: int, troubles: list[str], now: float | None = None) -> str:
    """The answer: late with nothing since, coming, then late with a later email from them."""
    from . import ghosts, mail_promises

    now = now or time.time()
    today = datetime.fromtimestamp(now, zone).date()
    late = sorted([one for one in found if one["due"] < today and not one["wrote_since"]], key=lambda i: i["due"])
    coming = sorted([one for one in found if one["due"] >= today], key=lambda i: i["due"])
    maybe = sorted([one for one in found if one["due"] < today and one["wrote_since"]], key=lambda i: i["due"])
    lines = [f"Promised to the person by email in the last {days} days, by a day: {len(found)}"
             + (" (none found)." if not found else
                f": {len(late)} late with nothing from them since, {len(coming)} still coming, "
                f"{len(maybe)} late but they wrote again since.")]

    def line(one: dict) -> str:
        who = f"{one['name']} <{one['email']}>" if one["name"] else one["email"]
        sent = datetime.fromtimestamp(one["at"], zone).strftime("%-d %B")
        return (f"- {who}, in their email of {sent} {one['subject']!r}: \"{one['sentence']}\" Due "
                f"{mail_promises.day_words(one['due'], today)} (they said \"{one['when']}\"). "
                f"Open: {ghosts.link_to(one['mailbox'], one['thread_id'])}")

    if late:
        lines.append("\nLate, and nothing from them since:")
        lines += [line(one) for one in late[:MOST_SAID]]
    if coming:
        lines.append("\nStill coming:")
        lines += [line(one) for one in coming[:MOST_SAID]]
    if maybe:
        lines.append("\nLate, but they have written to the person since, so it may have come (check):")
        lines += [line(one) for one in maybe[:MOST_SAID]]
    for one in troubles:
        lines.append(f"\nNot read: {one}")
    lines.append("\nRead in plain rules from what each person wrote themselves; a promise said without a day, "
                 "or on the phone, is not seen. Offer to draft a short follow-up for a late one only if the "
                 "person asks for it.")
    return "\n".join(lines)


async def answer(who, args: dict, zone) -> tuple[str, int]:
    """(the words for the model, how many promises were found)."""
    from asgiref.sync import sync_to_async

    from . import ghosts, mail_promises, runtime

    try:
        days = max(1, min(MOST_DAYS, int(args.get("days") or DAYS)))
    except (TypeError, ValueError):
        days = DAYS
    person = " ".join(str(args.get("person") or "").replace("(", " ").replace(")", " ").split())[:80]
    auth, cfg = runtime.mailbox_auth, runtime.config
    if auth is None:
        return "No mailbox is connected on this Rouh.", 0
    sources = await sync_to_async(ghosts.sources)(who, auth)
    if not sources:
        return ("No mailbox is connected: connect Google, or a read-only mailbox, in Settings.", 0)
    found: list[dict] = []
    troubles: list[str] = []
    for source in sources:
        if source.needs_reconnect:
            troubles.append(f"{source.email} needs connecting again in Settings.")
            continue
        try:
            reader = await sync_to_async(ghosts._reader)(who, auth, cfg, source)
            if reader is None:
                continue
            for one in await mail_promises.scan_received(reader, zone, days=days, person=person,
                                                          mailbox=source.email):
                found.append(dict(one, mailbox=source.email))
        except Exception as exc:  # noqa: BLE001 - one mailbox's trouble never stops the rest
            troubles.append(ghosts._say_trouble(exc, source.email))
    return said(found, zone, days=days, troubles=troubles), len(found)


__all__ = ["DESCRIPTION", "SCHEMA", "SWITCH", "TITLE", "TOOL_NAME", "answer", "on", "said"]
