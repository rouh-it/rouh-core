"""Shared until a day: a file is shared with somebody for a while, and Google takes their access away
by itself on the day asked.

Built by the nightly feature run, night 47 of the ledger (18 November 2026, task 94).
A deck for a client's meeting, a draft for an outside reviewer, figures for a supplier: each is shared
for the days it is needed and stays open to them for good, because nobody remembers to take it off
afterwards (night 46's Taken off your files does it when asked, weeks later, if anybody asks).
Google Drive can end a person's access by itself on a day (a permission's `expirationTime`), the way
Share, Settings, "Access expires" does in Drive, but Rouh could only share for good: "share the deck
with Dana until Friday" was shared for ever, and the "until Friday" was lost.

So, while its switch is on, `share_drive_file` takes `until` for each person: a day (the end of that
day on ‹his› clock) or a time. Rouh shares the file with them at what was asked and Google ends it
then by itself, with nothing for Rouh or ‹him› to remember; the answer says the day. Who can open a
file (`list_drive_permissions`) says, for each person whose access ends, when it ends. A day that has
passed, or more than a year ahead (Google's own limit), is refused before anything is shared.

No model is asked; nothing is kept: the end is Google's, on the file.

**Whose.** The person's Google connection, by `org_id` and `user_id`.

**Its switch** is `share_until` (`rouh/switches.py`): off, `until` is refused, so nobody is shared a
file for good that was asked to have it for a while.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

SWITCH = "share_until"
TITLE = "Shared until a day: Google ends a person's access to a file on the day asked"

#: Google refuses an end more than a year ahead.
MOST = timedelta(days=365)

#: Said to the model in share_drive_file's person.
FIELD = {"type": "string",
         "description": ("When their access ends by itself, when the person asked for it for a while "
                         "(\"until Friday\", \"for two weeks\"): a day as 2026-11-21, which ends at the "
                         "end of that day on the person's clock, or a time as 2026-11-21T18:00. Google "
                         "takes the access away then. Leave out for access with no end.")}


def on(who) -> bool:
    from . import switches

    if who is None:
        return False
    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def expires(value, zone, now: datetime | None = None) -> datetime:
    """The moment access given `until` ends, in UTC. A day ends at its last minute on the person's
    clock. Raises ValueError, with the words to say, for a moment passed or past Google's year."""
    from .google_api.calendar import when_given

    text = str(value or "").strip()
    try:
        given = when_given(text, zone)
    except Exception as exc:  # noqa: BLE001 - CannotDoThat says what it could not read
        raise ValueError(str(exc)) from None
    if given is None:
        raise ValueError("Say until when, as a day such as 2026-11-21.")
    if isinstance(given, datetime):
        end = given
    elif isinstance(given, date):
        end = datetime.combine(given, time(23, 59), tzinfo=zone)
    else:  # pragma: no cover - when_given gives one of the two
        raise ValueError(f"{text!r} is not a day.")
    end = end.astimezone(timezone.utc)
    now = now or datetime.now(timezone.utc)
    if end <= now:
        raise ValueError(f"{text} has already passed, so nobody can be given the file until then.")
    if end - now > MOST:
        raise ValueError(f"{text} is more than a year away, and Google ends access at most a year ahead: "
                         "share it with no end, or until a nearer day.")
    return end


def rfc3339(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def day_said(moment: datetime | str, zone) -> str:
    """The end in the person's words: "the end of Friday 21 November", or the time."""
    if isinstance(moment, str):
        try:
            moment = datetime.fromisoformat(moment.replace("Z", "+00:00"))
        except ValueError:
            return moment
    local = moment.astimezone(zone)
    day = f"{local:%A} {local.day} {local:%B}"
    if local.year != datetime.now(zone).year:
        day += f" {local.year}"
    if (local.hour, local.minute) == (23, 59):
        return "the end of " + day
    return f"{day} at {local:%H:%M}"


__all__ = ["FIELD", "MOST", "SWITCH", "TITLE", "day_said", "expires", "on", "rfc3339"]
