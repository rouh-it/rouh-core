"""Agreed, not booked: a next meeting agreed in a meeting, not in the calendar, said in the brief.

Built by the nightly feature run, night 20, 23 October 2026 (task 94, idea I-118). The meeting
library ends a meeting's notes with the next meeting, when one was agreed ("Next meeting:
2026-10-29", `rouh/synapse/sources/meetings.py`). Ten of ‹his› twenty Work meetings from 28
September to 22 October 2026 named one, and four of those dates never reached ‹his› calendar:
a client's sync agreed for 8 October that next happened on 20 October, and three agreed for 29
October and 7 November with nothing booked. Nobody had said the date was agreed and not booked;
booking it was ‹his› to remember.

So, while its switch is on, the morning brief has a section **Agreed, not booked**, read afresh
every time the page opens, with no model:

- **Which.** ‹His› meetings from the library over the last `LOOK_BACK_DAYS`, the newest of each
  set of people from outside, whose next meeting is today or within `AHEAD_DAYS`, with no event
  in ‹his› calendar within a day of it that shares a guest from outside, their company, or the
  meeting's title (‹his› calendar events in Master, `notes_missing._rows`).
- **Each line.** When it was agreed for, in which meeting and on what day, and with whom. **Book
  it** puts the event on ‹his› usual calendar with the same title, the same length and the same
  guests as the meeting it was agreed in (its own calendar event, found by its start), at the
  time agreed or, with only a day, at the same time of day, with a video call, invitations from
  Google, and "added by Rouh" in its notes; the line then says it is booked, with the event's
  link. **Not needed** puts it away, with Undo.

**Whose.** ‹His› own Master, calendar and setting (`user_settings`, `next_meeting`), by `org_id`
and `user_id`. Nothing goes to anybody until ‹he› presses Book it.

**Its switch** is `next_meeting` (`rouh/switches.py`): off, the section is not there.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import re
import time
from datetime import date, datetime, timedelta

log = logging.getLogger("rouh.next_meeting")

SWITCH = "next_meeting"
#: How far back meetings are read, and how far ahead an agreed date is said, in days.
LOOK_BACK_DAYS = 45
AHEAD_DAYS = 28
#: How near the start of a calendar event must be to a library meeting's to be it, in minutes.
NEAR_MINUTES = 45
#: How far from the agreed day a booked event still counts as it, in hours.
NEAR_HOURS = 36
#: The person's own setting: {line key: {"state": "not_needed"|"booked", "at", "link"}}.
KEPT = "next_meeting"
MOST = 8

_NEXT = re.compile(r"^Next meeting:\s*(\d{4}-\d{2}-\d{2})(?:[ T](\d{1,2}):(\d{2}))?", re.M)
_EMAIL = re.compile(r"<([^<>\s]+@[^<>\s]+)>|\b([\w.+-]+@[\w-]+(?:\.[\w-]+)+)\b")
_PEOPLE_LINE = re.compile(r"^(?:Took part|Invited, did not take part):(.*)$", re.M)


class Refused(ValueError):
    """What cannot be done, in the words the page shows."""


def on(who) -> bool:
    from . import switches

    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def _key(meeting_id: str, day: str) -> str:
    return "m-" + hashlib.sha256(f"{meeting_id}\n{day}".encode()).hexdigest()[:16]


def agreed(body: str) -> tuple[date, tuple[int, int] | None] | None:
    """The next meeting a meeting's notes name: its day, and its hour and minute when said."""
    found = _NEXT.search(body or "")
    if not found:
        return None
    try:
        day = date.fromisoformat(found.group(1))
    except ValueError:
        return None
    hour = (int(found.group(2)), int(found.group(3))) if found.group(2) else None
    if hour and not (0 <= hour[0] < 24 and 0 <= hour[1] < 60):
        hour = None
    return day, hour


def _named(body: str) -> list[str]:
    """Every address the notes name among those who took part or were invited."""
    out: list[str] = []
    for line in _PEOPLE_LINE.findall(body or ""):
        for a, b in _EMAIL.findall(line):
            one = (a or b).strip().lower()
            if one and one not in out:
                out.append(one)
    return out


def _domain(address: str) -> str:
    return address.rsplit("@", 1)[-1].lower() if "@" in address else ""


def _events(who, since: datetime) -> list[dict]:
    from .notes_missing import _meta, _rows, _when

    out = []
    for r in _rows(who, "event", since, 1500):
        meta = _meta(r.get("meta"))
        gcal = meta.get("gcal") if isinstance(meta.get("gcal"), dict) else {}
        start, end = _when(meta.get("start")), _when(meta.get("end"))
        if start is None or gcal.get("status") == "cancelled":
            continue
        out.append({"title": str(r.get("title") or "").strip(), "start": start,
                    "end": end or start + timedelta(minutes=30),
                    "people": [str(a).lower() for a in (meta.get("attendees") or [])],
                    "link": str(gcal.get("link") or "")})
    return out


def lines(who, *, now: datetime | None = None) -> list[dict]:
    """The agreed next meetings that are not in the calendar, soonest first."""
    from . import clock, meeting_prep
    from .notes_missing import _meta, _rows, _when

    now = now or clock.now()
    today = now.date()
    since = now - timedelta(days=LOOK_BACK_DAYS)
    own = {a.lower() for a in meeting_prep.own_addresses(who)}
    domains = meeting_prep.own_domains(own)
    events = _events(who, since - timedelta(days=1))
    held = kept(who)

    def outside(addresses) -> list[str]:
        return [a for a in addresses if a not in own and _domain(a) not in domains]

    newest: dict[frozenset, dict] = {}
    for r in _rows(who, "meeting", since, 400):
        body = str(r.get("body") or "")
        said = agreed(body)
        if said is None:
            continue
        meta = _meta(r.get("meta"))
        meeting = meta.get("meeting") if isinstance(meta.get("meeting"), dict) else {}
        start = _when(meta.get("start")) or (r["said_at"] if hasattr(r.get("said_at"), "timestamp") else None)
        end = _when(meta.get("end"))
        title = str(r.get("title") or "the meeting").strip()
        # The meeting's own calendar event, by its start: its guests are the ones to invite.
        own_event = None
        if start is not None:
            near = [e for e in events if abs((e["start"] - start).total_seconds()) <= NEAR_MINUTES * 60]
            own_event = next((e for e in near if e["title"].lower() == title.lower()), None) or \
                next((e for e in near if set(e["people"]) & set(_named(body))), None)
        guests = list(own_event["people"]) if own_event else _named(body)
        if not outside(guests):
            continue
        minutes = 30
        if own_event and own_event["end"] > own_event["start"]:
            minutes = int((own_event["end"] - own_event["start"]).total_seconds() // 60)
        elif start and end and end > start:
            minutes = int((end - start).total_seconds() // 60)
        minutes = max(15, min(240, round(minutes / 15) * 15 or 30))
        group = frozenset(_domain(a) for a in outside(guests))
        one = {"id": str(r["id"]), "title": title, "met_at": start.timestamp() if start else 0.0,
               "page": str(meeting.get("page") or ""), "day": said[0], "hour": said[1],
               "start": start, "guests": guests, "outside": outside(guests), "minutes": minutes}
        if group not in newest or one["met_at"] > newest[group]["met_at"]:
            newest[group] = one

    out = []
    for one in newest.values():
        day = one["day"]
        if day < today or day > today + timedelta(days=AHEAD_DAYS):
            continue
        if one["hour"]:
            at = datetime(day.year, day.month, day.day, *one["hour"], tzinfo=now.tzinfo)
        elif one["start"] is not None:
            local = one["start"].astimezone(now.tzinfo)
            at = datetime(day.year, day.month, day.day, local.hour, local.minute, tzinfo=now.tzinfo)
        else:
            at = datetime(day.year, day.month, day.day, 10, 0, tzinfo=now.tzinfo)
        middle = datetime(day.year, day.month, day.day, 12, 0, tzinfo=now.tzinfo)
        theirs = set(one["outside"])
        companies = {_domain(a) for a in theirs} - meeting_prep.PUBLIC_MAIL
        booked = any(
            abs((e["start"] - middle).total_seconds()) <= NEAR_HOURS * 3600
            and (theirs & set(e["people"]) or companies & {_domain(a) for a in e["people"]}
                 or e["title"].lower() == one["title"].lower())
            for e in events)
        key = _key(one["id"], day.isoformat())
        mark = held.get(key) or {}
        if mark.get("state") == "not_needed":
            continue
        if booked:
            # In the calendar now, whether booked from here or by hand: the calendar says it.
            continue
        out.append({"key": key, "title": one["title"], "met_at": one["met_at"], "page": one["page"],
                    "day": day.isoformat(), "at": at.timestamp(), "timed": bool(one["hour"]),
                    "minutes": one["minutes"], "with": one["outside"][:6],
                    "guests": one["guests"][:20],
                    "booked": mark.get("link") or ("yes" if mark.get("state") == "booked" else "")})
    out.sort(key=lambda i: i["at"])
    return out[:MOST]


def kept(who) -> dict:
    from .models import UserSetting

    value = (UserSetting.objects.filter(user_id=str(who.user_id), org_id=who.org_id or "", name=KEPT)
             .values_list("value", flat=True).first())
    try:
        held = json.loads(value) if value else {}
    except (TypeError, ValueError):
        held = {}
    return held if isinstance(held, dict) else {}


def _keep(who, held: dict) -> None:
    from .models import UserSetting

    UserSetting.objects.bulk_create(
        [UserSetting(user_id=str(who.user_id), org_id=who.org_id or "", name=KEPT,
                     value=json.dumps(held), updated_at=time.time())],
        update_conflicts=True, unique_fields=["user_id", "name"],
        update_fields=["org_id", "value", "updated_at"])


async def again(who, brief: dict) -> None:
    """The section as the page opens, put on the brief it is sent with; gone when off or empty."""
    from asgiref.sync import sync_to_async

    brief.pop("next_meeting", None)
    try:
        if who is None or not await sync_to_async(on)(who):
            return
        found = await sync_to_async(lines)(who)
    except Exception:  # noqa: BLE001 - the rest of the brief is drawn without it
        log.exception("agreed next meetings could not be read")
        return
    if found:
        from . import evolution

        brief["next_meeting"] = {"ok": True, "items": found, "source": "Meeting library"}
        await sync_to_async(evolution.used)(SWITCH, "shown", who=who,
                                            detail=f"{len(found)} agreed meetings not booked")


def mark(who, key: str, state: str) -> None:
    """Not needed, or Undo (state "")."""
    held = kept(who)
    if state:
        held[key] = {"state": state, "at": time.time()}
    else:
        held.pop(key, None)
    _keep(who, held)
    if state == "not_needed":
        from . import evolution

        evolution.used(SWITCH, "not_needed", who=who, detail="an agreed meeting put away as not needed")


async def book(who, google, key: str) -> dict:
    """Put the agreed meeting on the person's usual calendar, inviting the same guests."""
    from asgiref.sync import sync_to_async

    if not await sync_to_async(on)(who):
        raise Refused("Agreed, not booked is switched off.")
    item = next((one for one in await sync_to_async(lines)(who) if one["key"] == key), None)
    if item is None:
        raise Refused("That is not on the list any more. Open the brief again.")
    if item["booked"]:
        raise Refused("It is booked already.")
    if google is None:
        raise Refused("Google is not set up here, so nothing can be booked.")
    from . import clock, meeting_prep

    own = {a.lower() for a in meeting_prep.own_addresses(who)}
    guests = [a for a in item["guests"] if a not in own]
    met = clock.moment(item["met_at"]) if item["met_at"] else None
    agreed_in = f"{met.day} {met:%B %Y}" if met else ""
    notes = (f"Agreed in \"{item['title']}\"" + (f" on {agreed_in}" if agreed_in else "") + "."
             + (f"\nNotes: {item['page']}" if item["page"] else "") + "\n\nadded by Rouh")
    start = datetime.fromtimestamp(item["at"], clock.now().tzinfo)
    try:
        calendar = google(who).calendar
        made = await calendar.create(await calendar.calendar_id(""), title=item["title"], start=start,
                                     minutes=item["minutes"], description=notes, guests=guests,
                                     video=True, notify=True)
    except Exception as exc:  # noqa: BLE001 - said on the page, and nothing is marked
        log.info("an agreed meeting from the brief was not booked: %r", exc)
        said = re.sub(r"\s+", " ", str(exc)).strip()[:220]
        raise Refused("It was not booked" + (f": {said}" if said else ".")) from exc
    held = await sync_to_async(kept)(who)
    held[key] = {"state": "booked", "at": time.time(), "link": made.get("link") or "yes"}
    await sync_to_async(_keep)(who, held)
    from . import evolution, runtime

    audit = getattr(runtime, "google_audit", None)
    if audit is not None:
        with contextlib.suppress(Exception):
            audit.wrote("create_calendar_event", made.get("id") or "",
                        f"Put {item['title']!r} on the calendar for {start:%Y-%m-%d %H:%M}, "
                        f"inviting {', '.join(guests)} - an agreed next meeting, pressed on the brief",
                        user_id=who.user_id, org_id=who.org_id)
    await sync_to_async(evolution.used)(SWITCH, "booked", who=who, detail=f"booked {item['title']}")
    return {"link": made.get("link") or "", "guests": guests}


__all__ = ["KEPT", "Refused", "SWITCH", "agreed", "again", "book", "lines", "mark", "on"]
