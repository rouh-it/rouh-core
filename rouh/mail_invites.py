"""Invitations read on your clock: a meeting invitation in an email is read from its calendar file.

Built by the nightly feature run, night 33, 4 November 2026 (task 94). A meeting invitation that
arrives by email carries the meeting itself in a calendar part (`text/calendar`, often shown by Gmail
as invite.ics): its time with its time zone, how long it is, the call link, who sent it, who else is
invited, and whether it is a new invitation, a change, a cancellation or somebody's answer. Rouh
read only the words beside it (`gmail._message_bodies`), and those are whatever the sender's program
wrote: Outlook and Teams often say no time at all, or say it in the sender's zone ("09:00 Pacific
Standard Time"), and a changed or cancelled meeting can look like the first invitation. Asked
"when is that meeting with Paola, my time?", Rouh could only guess from the words, or say it could
not see the time.

So, while its switch is on, whenever Rouh reads an email (`read_mail`, in Rouh's own inbox or the
person's read-only one), each calendar part in it is read (`rouh/invites.py`) and said after the
email's words, inside the same box as the email, because every word of it is the sender's:

- what it is: an invitation, a changed invitation, a cancellation, an answer (and whose);
- when, on the person's own clock, with how long it lasts, and the sender's own time beside it
  when the clocks differ;
- where, the call link (Teams, Zoom, Meet, Webex), who sent it and who is invited.

No model is asked. Nothing is kept, changed or sent: the calendar is not touched.

**Whose.** Only an email Rouh was already reading, in the inbox it was read from.

**Its switch** is `mail_invites` (`rouh/switches.py`): off, an email is read as before, words only.
"""
from __future__ import annotations

import logging

from . import invites

log = logging.getLogger("rouh.mail_invites")

SWITCH = "mail_invites"
TITLE = "Invitations read on your clock: a meeting invitation in an email read from its calendar file"


def on(who) -> bool:
    from . import switches

    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


async def said(gmail, found: dict, zone) -> tuple[str, int]:
    """(the words to put after the email's own, how many invitations were read).

    `gmail` is the mailbox the email was read from, `found` what `Gmail.message` gave. "" when the
    email carries no calendar part, or none that reads as one.
    """
    parts = found.get("calendar") or []
    if not parts:
        return "", 0
    blocks, count, seen = [], 0, set()
    for one in parts:
        try:
            text = await gmail.calendar_text(str(found.get("id") or ""), one)
        except Exception as exc:  # noqa: BLE001 - the email is said all the same
            log.info("a calendar part of %s could not be fetched: %s", found.get("id"), exc)
            continue
        for invite in invites.parse(text, zone):
            key = (invite.uid, invite.sequence, invite.method, str(invite.start))
            if key in seen:
                # Google sends the same invitation twice, inline and as invite.ics.
                continue
            seen.add(key)
            count += 1
            blocks.append(invites.described(invite, zone))
    if not blocks:
        return "", 0
    head = ("The meeting invitation in this email, read from its calendar file"
            if count == 1 else f"The {count} meeting invitations in this email, read from its calendar file")
    return "\n\n" + head + ":\n" + "\n\n".join(blocks), count


__all__ = ["SWITCH", "TITLE", "on", "said"]
