"""Meetings with no notes: a recorded kind of meeting the meeting library sent nothing for, said in the brief.

Built by the nightly feature run, night 19, 22 October 2026 (task 94, idea I-113). ‹His› meetings
reach Rouh from the meeting library with their notes, decisions and action items
(`rouh/synapse/sources/meetings.py`), and What to raise, What to raise remembers, After the meeting
and Owed to you all read them. When the recorder misses a meeting, or stops altogether, nothing says
so: on 22 October 2026 the newest notes in ‹his› Master were from 13 October, though ‹he› had video
meetings with people from outside on the 20th and the 21st, and every gene that reads the notes
went quiet without a word. ‹He› finds out only when ‹he› looks for notes that are not there, often
too late to write down what was agreed.

So, while its switch is on, the morning brief has a section **Meetings with no notes**, read afresh
every time the page opens, with no model:

- **Which.** Events of ‹his› own calendars in ‹his› Master (`synapse.item`, kind `event`, kept by the
  calendar sync) over the last `LOOK_BACK_DAYS`, that ended at least `QUIET_HOURS` ago, are not all
  day or cancelled, that ‹he› did not decline, that had a video call (a Meet link, or a Teams, Zoom
  or Webex link in their place or notes), with at least one guest from outside ‹his› company
  (`meeting_prep.outsiders`), and that no meeting from the library matches: not by the calendar's
  event id or iCal id, and not by a start within `NEAR_MINUTES` that shares a guest or the title.
- **Only when the library is in use**: it is set up here and has sent ‹him› notes at least once;
  otherwise there is nothing to miss.
- **What it says.** How many meetings have no notes and since when, and when the library last sent
  notes, so a recorder that stopped reads as one thing, not as several; then each meeting, with its
  day, time and who came from outside. **Not recorded** puts one away for good, with Undo, when
  ‹he› knows it was not meant to be; **Open the meeting library** goes to the library, where a
  recording is uploaded or the recorder is seen to.

**Whose.** ‹His› own Master and ‹his› own settings (`user_settings`, `notes_missing`), by `org_id`
and `user_id`. Nothing is sent and nothing is changed anywhere but that setting.

**Its switch** is `notes_missing` (`rouh/switches.py`): off, the section is not there.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import re
import time
from datetime import datetime, timedelta

log = logging.getLogger("rouh.notes_missing")

SWITCH = "notes_missing"
#: How far back the calendar is read, in days.
LOOK_BACK_DAYS = 7
#: How long after a meeting ends before its notes are missed: the library takes a while.
QUIET_HOURS = 3
#: How near in time a library meeting has to start to be the same meeting, in minutes.
NEAR_MINUTES = 45
#: The person's own setting: {line key: seconds it was put away}.
KEPT = "notes_missing"
MOST = 12

_VIDEO = re.compile(r"https?://(?:meet\.google\.com|[\w.-]*teams\.(?:microsoft|live)\.com|"
                    r"[\w.-]*zoom\.us|[\w.-]*webex\.com)/\S+", re.I)
_GUESTS = re.compile(r"^Guests:\s*(.*)$", re.M)
_GUEST = re.compile(r"\s*(?P<email>[^\s;()]+@[^\s;()]+)\s*\((?P<response>[A-Za-z]+)\)\s*")


def on(who) -> bool:
    from . import switches

    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def _key(event_key: str) -> str:
    return "n-" + hashlib.sha256(event_key.encode()).hexdigest()[:16]


def _meta(value) -> dict:
    if isinstance(value, str):
        with contextlib.suppress(ValueError):
            value = json.loads(value)
    return value if isinstance(value, dict) else {}


def _when(value) -> datetime | None:
    if not value or not isinstance(value, str) or "T" not in value:
        return None
    with contextlib.suppress(ValueError):
        at = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return at if at.tzinfo else at.astimezone()
    return None


_LABELLED = re.compile(r"^\s*(?P<label>.*?)\s*\((?P<response>[A-Za-z ]+)\)\s*$")


def _responses(body: str, attendees=None) -> dict[str, str]:
    """Every guest's answer, from the event's own "Guests:" line, by address.

    The calendar sync writes each guest there by their name when Google has one ("Dana Reed
    (declined)"), and by address only when it has not, in the order of the event's `attendees`,
    which are addresses. So a guest written by name is matched to the address in the same place
    of `attendees`; until 2 November 2026 only guests with no name were read, and a meeting the
    person declined was still counted as theirs whenever Google knew their name.
    """
    found = _GUESTS.search(body or "")
    out: dict[str, str] = {}
    entries = [one for one in (found.group(1).split(";") if found else []) if one.strip()]
    addresses = [str(a).strip().lower() for a in (attendees or [])]
    for n, one in enumerate(entries):
        guest = _GUEST.match(one)
        if guest:
            out[guest.group("email").strip().lower()] = guest.group("response")
            continue
        named = _LABELLED.match(one)
        if named and len(entries) == len(addresses):
            out[addresses[n]] = named.group("response").strip().split()[0]
    return out


def _video(meta: dict, body: str) -> str:
    gcal = meta.get("gcal") if isinstance(meta.get("gcal"), dict) else {}
    if gcal.get("meet"):
        return str(gcal["meet"])
    found = _VIDEO.search(f"{meta.get('place') or ''}\n{body or ''}")
    return found.group(0) if found else ""


def _rows(who, kind: str, since: datetime, limit: int) -> list[dict]:
    from .synapse import db, master

    if not db.ready():
        return []
    ds = master.of(str(who.org_id), str(who.user_id))
    if ds is None:
        return []
    extra, args = "", [ds["id"], kind]
    if kind == "meeting":
        from .synapse.sources import meetings as library

        extra, args = " AND source = %s", [*args, library.SOURCE]
    return db.rows(
        "SELECT id, title, body, said_at, meta FROM synapse.item WHERE dataset_id = %s "
        f"AND kind = %s{extra} AND deleted_at IS NULL AND said_at > %s "
        "ORDER BY said_at DESC LIMIT %s", (*args, since, limit))


def _last_notes(who) -> dict | None:
    """The newest meeting the library sent notes for, ever, or None when it never has."""
    rows = _rows(who, "meeting", datetime(2000, 1, 1).astimezone(), 1)
    if not rows:
        return None
    r = rows[0]
    said = r.get("said_at")
    return {"title": str(r.get("title") or "a meeting"),
            "at": said.timestamp() if hasattr(said, "timestamp") else 0.0}


def _library_meetings(who, since: datetime) -> list[dict]:
    out = []
    for r in _rows(who, "meeting", since - timedelta(days=1), 400):
        meta = _meta(r.get("meta"))
        meeting = meta.get("meeting") if isinstance(meta.get("meeting"), dict) else {}
        start = _when(meta.get("start")) or (r["said_at"] if hasattr(r.get("said_at"), "timestamp") else None)
        out.append({"start": start, "title": str(r.get("title") or "").strip().lower(),
                    "ids": {str(meeting.get(k) or "").strip() for k in ("ical_uid", "calendar_event_id")} - {""},
                    "people": {str(a).lower() for a in (meta.get("attendees") or [])}})
    return out


def _matched(event: dict, held: list[dict], own: set[str]) -> bool:
    for m in held:
        if event["ids"] & m["ids"]:
            return True
        if m["start"] is None or abs((m["start"] - event["start"]).total_seconds()) > NEAR_MINUTES * 60:
            continue
        if (event["people"] & m["people"]) - own or (m["title"] and m["title"] == event["title"].lower()):
            return True
    return False


def kept(who) -> dict[str, float]:
    from .models import UserSetting

    value = (UserSetting.objects.filter(user_id=str(who.user_id), org_id=who.org_id or "", name=KEPT)
             .values_list("value", flat=True).first())
    try:
        held = json.loads(value) if value else {}
    except (TypeError, ValueError):
        held = {}
    return {str(k): float(v) for k, v in held.items() if isinstance(v, (int, float))} \
        if isinstance(held, dict) else {}


def _keep(who, held: dict) -> None:
    from .models import UserSetting

    UserSetting.objects.bulk_create(
        [UserSetting(user_id=str(who.user_id), org_id=who.org_id or "", name=KEPT,
                     value=json.dumps(held), updated_at=time.time())],
        update_conflicts=True, unique_fields=["user_id", "name"],
        update_fields=["org_id", "value", "updated_at"])


def missing(who, *, now: datetime | None = None) -> dict | None:
    """{items, last, since} for the brief, or None when there is nothing to say."""
    from . import meeting_prep
    from .synapse.sources import meetings as library

    if not library.settings()["url"]:
        return None
    last = _last_notes(who)
    if last is None:
        return None
    now = now or datetime.now().astimezone()
    since = now - timedelta(days=LOOK_BACK_DAYS)
    own = {a.lower() for a in meeting_prep.own_addresses(who)}
    domains = meeting_prep.own_domains(own)
    held = _library_meetings(who, since)
    put_away = kept(who)
    seen, out = set(), []
    for r in _rows(who, "event", since - timedelta(days=1), 600):
        meta = _meta(r.get("meta"))
        gcal = meta.get("gcal") if isinstance(meta.get("gcal"), dict) else {}
        start, end = _when(meta.get("start")), _when(meta.get("end"))
        if start is None or end is None or gcal.get("all_day") or gcal.get("status") == "cancelled":
            continue
        if start < since or end > now - timedelta(hours=QUIET_HOURS):
            continue
        body = str(r.get("body") or "")
        answers = _responses(body, meta.get("attendees"))
        if any(answers.get(a) == "declined" for a in own):
            continue
        video = _video(meta, body)
        if not video:
            continue
        guests = [{"email": a, "response": answers.get(str(a).lower(), "")}
                  for a in (meta.get("attendees") or [])]
        outside = meeting_prep.outsiders(guests, own, domains)
        if not outside:
            continue
        # The same meeting is often on two calendars: one line for it.
        ident = str(gcal.get("ical_uid") or "") or f"{r.get('title')}|{start.isoformat()}"
        if ident in seen:
            continue
        seen.add(ident)
        event = {"start": start, "title": str(r.get("title") or "a meeting"),
                 "ids": {str(gcal.get(k) or "").strip() for k in ("ical_uid", "event_id")} - {""},
                 "people": {str(a).lower() for a in (meta.get("attendees") or [])}}
        if _matched(event, held, own):
            continue
        key = _key(ident)
        if key in put_away:
            continue
        out.append({"key": key, "title": event["title"], "start": start.timestamp(),
                    "end": end.timestamp(), "link": str(gcal.get("link") or ""),
                    "outside": [one["email"] for one in outside][:6]})
    if not out:
        return None
    out.sort(key=lambda i: i["start"], reverse=True)
    return {"items": out[:MOST], "count": len(out), "last": last,
            "library": library.settings()["url"]}


async def again(who, brief: dict) -> None:
    """The section as the page opens, put on the brief it is sent with; gone when off or empty."""
    from asgiref.sync import sync_to_async

    brief.pop("no_notes", None)
    try:
        if who is None or not await sync_to_async(on)(who):
            return
        found = await sync_to_async(missing)(who)
    except Exception:  # noqa: BLE001 - the rest of the brief is drawn without it
        log.exception("meetings with no notes could not be read")
        return
    if found:
        from . import evolution

        brief["no_notes"] = {"ok": True, "source": "Meeting library", **found}
        await sync_to_async(evolution.used)(SWITCH, "shown", who=who,
                                            detail=f"{found['count']} meetings with no notes")


def act(who, key: str, what: str) -> None:
    """Not recorded (kept), Undo (taken back), or Open the meeting library (only counted)."""
    from . import evolution

    if what == "library":
        evolution.used(SWITCH, "opened_library", who=who, detail="opened the meeting library from the brief")
        return
    held = kept(who)
    if what == "not_recorded":
        held[key] = time.time()
    else:
        held.pop(key, None)
    _keep(who, held)
    if what == "not_recorded":
        evolution.used(SWITCH, "not_recorded", who=who, detail="said a meeting was not recorded")


__all__ = ["KEPT", "SWITCH", "act", "again", "missing", "on"]
