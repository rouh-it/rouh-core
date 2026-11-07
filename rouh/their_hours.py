"""Not in their night: a meeting with a guest abroad is not booked into their early morning or night.

Built by the nightly feature run, night 31 (the ledger's night 35), 6 November 2026 (task 94).
"Book a call with Marco on Thursday at three" was booked at three on the person's clock, and the
invitation went out. If Marco lives seven hours behind, that is eight in the morning for him at best,
and a call at nine is two in the morning: the first anybody knew was his decline, or an email asking
for later, and a second round of invitations. Google shows each guest the time on their own clock,
but only after the invitation has gone; Rouh never looked before.

The guest's own mail says where they are: the Date line of their newest email carries the clock it
was written on (`rouh/their_clock.py`, the same reading). So, while its switch is on, before
create_calendar_event books a timed event with guests (a move with update_calendar_event is not
checked yet), each
guest's clock is read from their newest email in the person's mailboxes, and when the meeting starts
before `EARLIEST` or ends after `LATEST` on a guest's clock, nothing is booked or moved and nobody is
emailed: Rouh says the meeting's time on that guest's clock, and the hours that are inside both
days, so the person picks another in a word. `even_if_their_night` books it as asked, when they say so.

A guest on the person's own clock, or whose mail says no clock (+0000, a server's), is not checked.
A whole-day event is not checked. No model is asked. It reads only From and Date lines.

**Whose.** The person's own mailboxes, by `org_id` and `user_id`, in their own turns only.

**Its switch** is `their_hours` (`rouh/switches.py`): off, a meeting is booked as asked.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

log = logging.getLogger("rouh.their_hours")

SWITCH = "their_hours"
TITLE = ("Not in their night: a meeting with a guest abroad is not booked before 08:00 or after 20:00 "
         "on the guest's own clock without saying so")

#: A guest's day, on their own clock, in minutes after midnight.
EARLIEST = 8 * 60
LATEST = 20 * 60
SECONDS = 8.0

FIELD = {"type": "boolean",
         "description": "Book it at the time asked although it falls before 08:00 or after 20:00 on a guest's "
                        "own clock: only when the person says so after being told."}


def on(who) -> bool:
    from . import switches

    if who is None:
        return False
    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def _minutes(moment: datetime) -> int:
    return moment.hour * 60 + moment.minute


def outside(start: datetime, end: datetime, offset: int) -> tuple[datetime, datetime] | None:
    """(the start and end on the guest's clock) when the meeting is outside their day, else None."""
    theirs = timezone(timedelta(minutes=offset))
    a, b = start.astimezone(theirs), end.astimezone(theirs)
    ends = _minutes(b) if b.date() == a.date() else 24 * 60 + _minutes(b)
    if _minutes(a) < EARLIEST or ends > LATEST:
        return a, b
    return None


def both_days(offsets: list[int], mine: int) -> str:
    """The hours on the person's clock that fall inside every guest's day and the person's own."""
    lo = max([EARLIEST] + [EARLIEST - (o - mine) for o in offsets])
    hi = min([LATEST] + [LATEST - (o - mine) for o in offsets])
    if hi - lo < 30:
        return "There is no hour inside both your working day and theirs; ask which they prefer."
    return f"Inside both days: from {lo // 60:02d}:{lo % 60:02d} to {hi // 60:02d}:{hi % 60:02d} on your clock."


async def check(who, guests: list[str], start, end, zone) -> str:
    """"" when it may be booked, or why not. Never raises, never longer than `SECONDS`."""
    from asgiref.sync import sync_to_async

    from . import evolution, their_clock

    try:
        if not isinstance(start, datetime) or not isinstance(end, datetime) or not guests:
            return ""
        if not await asyncio.to_thread(on, who):
            return ""
        if start.tzinfo is None:
            start, end = start.replace(tzinfo=zone), end.replace(tzinfo=zone)
        off = start.astimezone(zone).utcoffset()
        mine = int((off.total_seconds() if off else 0) // 60)
        found = await asyncio.wait_for(their_clock.find(who, guests), SECONDS)
    except Exception as exc:  # noqa: BLE001 - booked as asked when the check cannot be made
        log.info("not in their night: the look did not finish: %s", exc)
        return ""
    lines, offsets = [], []
    for one in found:
        if one["offset"] == mine:
            continue
        got = outside(start, end, one["offset"])
        if got is None:
            continue
        a, b = got
        offsets.append(one["offset"])
        who_ = f"{one['name']} <{one['address']}>" if one.get("name") else one["address"]
        lines.append(f"- {who_} writes from {their_clock.utc_said(one['offset'])} (the clock on their own "
                     f"newest email): {start.astimezone(zone).strftime('%H:%M')} to "
                     f"{end.astimezone(zone).strftime('%H:%M')} on your clock is {a.strftime('%H:%M')} to "
                     f"{b.strftime('%H:%M')} on theirs, {a.strftime('%A')}.")
    if not lines:
        return ""
    await sync_to_async(evolution.used)(
        SWITCH, "held", who=who, detail=", ".join(one["address"] for one in found)[:200])
    return ("Not booked yet, and nobody was emailed: the meeting falls outside the working day "
            f"({EARLIEST // 60:02d}:00 to {LATEST // 60:02d}:00) of a guest on another clock.\n"
            + "\n".join(lines) + "\n" + both_days(offsets, mine)
            + " Tell the person, and offer a time inside both days; book it as asked with even_if_their_night "
              "only if they say so.")


__all__ = ["EARLIEST", "FIELD", "LATEST", "SWITCH", "TITLE", "both_days", "check", "on", "outside"]
