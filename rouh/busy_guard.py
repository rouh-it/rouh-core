"""Not booked over someone busy: Rouh no longer books a meeting into a time a colleague is busy.

Built by the nightly feature run, night 33, 4 November 2026 (task 94). "Book a call with Todor and
Ivaylo on Thursday at three" was done as said: the invitation went out, and if Ivaylo was in
another meeting then, the first anybody knew was his decline, or an email asking to move it, and a
second round of invitations. Google shows a colleague's busy times inside one Workspace, and Rouh
never looked.

So, while its switch is on, before create_calendar_event makes an event with guests, or
update_calendar_event moves one that has guests, the guests' free/busy is read for that time
(`free_busy.read`, Google's free/busy query) and:

- if every guest whose calendar can be read is free, it is booked as before, and the answer says
  whose calendars were checked;
- if somebody is busy then, nothing is booked or moved, and nobody is emailed: Rouh says who is
  busy, from when to when, and the next times on the same and the following working days when
  everybody, the person included, is free for the same length, so the person picks one in a word;
- the person can still book it as asked: the tool's `even_if_busy` does that, when they say so.

A guest whose calendar Google will not show (somebody outside the Workspace) is named as not
checked, and does not stop the booking.

No model is asked. It reads only busy and free.

**Whose.** The connected Google account's free/busy query, by `org_id` and `user_id`.

**Its switch** is `busy_guard` (`rouh/switches.py`): off, events are booked as asked, unchecked.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from . import free_busy

log = logging.getLogger("rouh.busy_guard")

SWITCH = "busy_guard"
TITLE = "Not booked over someone busy: a meeting is not booked into a time a colleague is busy"

#: How far on the other times are looked for, in days, and how many are said.
AHEAD = 7
OFFERED = 4

#: Said to the model beside create_calendar_event's other fields.
FIELD = {"type": "boolean",
         "description": "Book it even though a guest is busy then. Only when the person says so, "
                        "after being told who is busy."}


def on(who) -> bool:
    from . import switches

    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


async def check(calendar, guests, start, end, zone, *, me: str = "", moving=None) -> tuple[str, str]:
    """(refusal, note): a refusal when a guest is busy then, with who and the next free times;
    otherwise "" and a short note of whose calendars were checked (or "" when none could be)."""
    if not isinstance(start, datetime) or not isinstance(end, datetime) or end <= start:
        return "", ""  # a whole-day event is not a meeting anybody is busy for
    people = [g for g in guests if "@" in g and g.lower() != (me or "").lower()]
    if not people:
        return "", ""
    got = await free_busy.read(calendar, people, start, end, me=False)
    busy = {}
    checked, hidden = [], []
    for one in people:
        entry = got.get(one) or {"trouble": "notFound"}
        if entry.get("trouble"):
            hidden.append(one)
            continue
        checked.append(one)
        clash = [(a, b) for a, b in entry.get("busy") or [] if a < end and b > start]
        if clash:
            busy[one] = clash
    hidden_words = (f" Not checked, as Google does not show their calendar: {', '.join(hidden)}."
                    if hidden else "")
    if not busy:
        if not checked:
            return "", hidden_words.strip()
        return "", (f"Checked first: {', '.join(checked)} "
                    + ("is" if len(checked) == 1 else "are all") + " free then." + hidden_words)
    minutes = int((end - start).total_seconds() // 60)
    # The other times: the same day from the start asked, and the days after, everybody included.
    begin = max(start.replace(hour=0, minute=0), datetime.now(zone))
    finish = begin + timedelta(days=AHEAD)
    every = await free_busy.read(calendar, checked, begin, finish, me=True)
    # The meeting being moved is not in anybody's way.
    lists = [[span for span in v["busy"] if not moving or span != moving]
             for v in every.values() if not v.get("trouble")]
    free = free_busy.common_free(lists, begin, finish, minutes, zone, most=OFFERED)
    now = datetime.now(zone)
    who = "; ".join(f"{one} is busy " + ", ".join(f"{a.astimezone(zone):%H:%M}-{b.astimezone(zone):%H:%M}"
                                                  for a, b in spans) for one, spans in busy.items())
    lines = [f"Not {'moved' if moving else 'booked'}, and nobody was emailed: {who}, on {start.astimezone(zone):%A %-d %B}, "
             f"across the {start.astimezone(zone):%H:%M}-{end.astimezone(zone):%H:%M} asked for."]
    if free:
        lines.append(f"Times when {', '.join(['you'] + checked)} are all free for {minutes} minutes "
                     "(each from its start):")
        lines += [f"- {one}" for one in free_busy.said_times(free, now)]
    else:
        lines.append(f"There is no time in the next {AHEAD} days when everybody is free for {minutes} minutes.")
    lines.append(("Move it to one of those" if moving else "Book one of those")
                 + ", or the time asked with even_if_busy if the person says to do it anyway."
                 + hidden_words)
    return "\n".join(lines), ""


__all__ = ["FIELD", "SWITCH", "TITLE", "check", "on"]
