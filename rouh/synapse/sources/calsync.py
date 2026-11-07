"""Every calendar event, kept in Synapse Master, all the time (5 October 2026).

Petar, by voice: "calendar - go ahead and sync continuously with synapse on all calendar events" (Drive
waits until he has tidied it). So every event on every calendar Rouh's Google account can read is an item
of kind `event` in his Synapse Master, kept as the calendar has it:

- **Which calendars.** Every one on the account's list that it may read: its own, and every calendar
  shared with it (the owner's own calendar, birthdays, public holidays). One row of
  `synapse.calendar_sync` each (migration 0083), found again every hour (`discover`), so a calendar shared
  later is kept without anybody asking. A calendar shared as free and busy only has no events to read: it
  has a row that says so and nothing else. One that leaves the list stops being read; what it had stays.
- **The first time** a calendar is listed a page at a time, every event in it, past and future, with the
  page token saved after each page, so a restart carries on from the page it was on. A repeating event is
  one item with its rule; an occurrence moved or changed on its own is an item of its own. Those items go
  on the queue's backfill lane, which never takes a slot live work needs.
- **Then, every minute**, Google's sync token for that calendar is asked what changed since: new events,
  changed ones (stored again only when Google's `updated` moved) and deleted ones, which are deleted here
  with everything made from them. Only after a change is written is the token moved on, so a restart reads
  the same changes again and nothing is taken twice. When Google no longer honours a token (its 410), the
  calendar is listed whole again and checked.
- **Every night** each calendar's whole list is compared with what Synapse holds of it: what is missing is
  stored and what the calendar no longer has is deleted (`reconcile`).

An event's key is `gcal:<calendar id>:<event id>`. Its meta carries `start`, `end`, `place`, `attendees` (the
`event` kind's own fields), `from` (the organiser) and `to` (the guests), which code links to people as it
links an email's sender and recipients, and `gcal` (the calendar, Google's ids, `updated`, the series and
its rule). Its text says what a person would read on the event. The owner is its only reader. An event
deleted in Synapse by a person is kept out (D60) and never written back to the calendar: the calendar is
the truth, and nothing here writes to it.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import threading
import time
from datetime import date, datetime, timezone

from ... import clock
from .. import db
from ..db import Json

log = logging.getLogger("rouh.synapse.calendar")

SOURCE = "gcal"
#: How often each calendar's changes are read (seconds).
POLL_SECONDS = float(os.environ.get("SYNAPSE_CALENDAR_POLL_SECONDS") or 60)
#: A calendar with no good read for this long is flagged.
STALE_MINUTES = 15
#: Pages of the first listing per beat, `PAGE` events each, so changes on other calendars are never held up.
PAGES_PER_BEAT = 4
PAGE = 250
#: How often the calendar list is read again for calendars shared since (seconds).
DISCOVER_EVERY = 3600
#: The nightly check runs after this hour, on the installation's own clock (`clock.DEFAULT`), which an
#: event's text is said in too. It was Sofia, written here, until 20 October 2026.
RECONCILE_HOUR = 3
ZONE = clock.DEFAULT
#: One event's text, at most.
TEXT_MAX = 20_000

_started = False
_start_lock = threading.Lock()
_wake = threading.Event()
_discovered: dict[str, float] = {}


def key_of(calendar_id: str, event_id: str) -> str:
    return f"gcal:{calendar_id}:{event_id}"


def prefix_of(calendar_id: str) -> str:
    return f"gcal:{calendar_id}:"


# ---------------------------------------------------------------------------------------------
# rows
# ---------------------------------------------------------------------------------------------

def ready() -> bool:
    return bool(db.value("SELECT to_regclass('synapse.calendar_sync') IS NOT NULL"))


def rows(dataset_id: str | None = None, enabled_only: bool = True) -> list[dict]:
    sql = "SELECT * FROM synapse.calendar_sync WHERE true"
    params: list = []
    if dataset_id:
        sql += " AND dataset_id = %s"
        params.append(str(dataset_id))
    if enabled_only:
        sql += " AND enabled"
    return db.rows(sql + " ORDER BY dataset_id, name", params)


def row_of(dataset_id: str, calendar_id: str) -> dict | None:
    return db.row("SELECT * FROM synapse.calendar_sync WHERE dataset_id = %s AND calendar_id = %s",
                  (str(dataset_id), calendar_id))


def _set(dataset_id: str, calendar_id: str, **fields) -> None:
    if not fields:
        return
    cols = ", ".join(f"{k} = %s" for k in fields)
    db.run(f"UPDATE synapse.calendar_sync SET {cols}, updated_at = now() WHERE dataset_id = %s AND calendar_id = %s",
           [Json(v) if isinstance(v, (dict, list)) else v for v in fields.values()] + [str(dataset_id), calendar_id])


# ---------------------------------------------------------------------------------------------
# reaching Google, from a thread of Synapse's own
# ---------------------------------------------------------------------------------------------

class NotReadable(RuntimeError):
    """The calendar cannot be read now: Google is not connected, or the connection needs the person."""


def _connected(ds: dict) -> bool:
    try:
        return bool(db.value("SELECT 1 FROM google_connections WHERE user_id = %s AND org_id = %s LIMIT 1",
                             (str(ds["user_id"]), str(ds["org_id"]))))
    except Exception:  # noqa: BLE001
        return False


def _open(ds: dict):
    """(a `google_api.Calendar` acting as the Master's owner, the owner). Made fresh for each use: Google's
    clients keep asyncio locks, which belong to the event loop that made them."""
    from ...config import config
    from ...encryption import SecretBox
    from ...google_api import GoogleClients
    from ...google_oauth import GoogleAuth
    from ...google_store import GoogleStore
    from ...tenancy import Identity, Tenancy

    if not _connected(ds):
        raise NotReadable("Google is not connected for this account, so no calendar can be read.")
    who = None
    with contextlib.suppress(Exception):
        who = Tenancy().identity_of(str(ds["user_id"]))
    who = who or Identity(user_id=str(ds["user_id"]), org_id=str(ds["org_id"]))
    box = SecretBox(config.encryption_key, data_dir=config.data_dir)
    auth = GoogleAuth(GoogleStore(None, box), config)
    return GoogleClients(auth, config).for_user(who).calendar, who


def _run(who, coro):
    """Requests to Google, on an event loop of this thread's own. The token store is Django's, read
    from inside that loop, which Rouh's own process already allows; a command is let do the same."""
    from ...tenancy import speaking

    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    with speaking(who):
        return asyncio.run(coro)


def _status(exc: Exception) -> int:
    return int(getattr(exc, "status", 0) or 0)


async def _page(cal, calendar_id: str, *, page: str = "", sync_token: str = "", deleted: bool = False) -> dict:
    params: dict = {"maxResults": PAGE}
    if sync_token:
        params["syncToken"] = sync_token
    else:
        params["showDeleted"] = "true" if deleted else "false"
    if page:
        params["pageToken"] = page
    return await cal._call("GET", cal._event_path(calendar_id), params=params)


# ---------------------------------------------------------------------------------------------
# which calendars
# ---------------------------------------------------------------------------------------------

def discover(ds: dict, *, force: bool = False) -> dict:
    """The account's calendar list: a row for each calendar, new ones kept from now on."""
    if not force and time.time() - _discovered.get(str(ds["id"]), 0) < DISCOVER_EVERY:
        return {"skipped": True}
    cal, who = _open(ds)
    listed = _run(who, cal.calendars())
    _discovered[str(ds["id"])] = time.time()
    seen, added = set(), []
    for c in listed:
        seen.add(c["id"])
        readable = c["access"] != "freeBusyReader"
        had = row_of(ds["id"], c["id"])
        if had is None:
            db.run("INSERT INTO synapse.calendar_sync (dataset_id, calendar_id, name, access, enabled, state, error) "
                   "VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                   (str(ds["id"]), c["id"], c["name"], c["access"], readable, "" if readable else "busy only",
                    "" if readable else "shared as free and busy only, so its events cannot be read"))
            if readable:
                added.append(c["name"])
        else:
            fields = {"name": c["name"], "access": c["access"], "on_list": True}
            if not readable and had["enabled"]:
                fields.update(enabled=False, state="busy only",
                              error="shared as free and busy only now, so its events cannot be read")
            elif readable and had["state"] == "busy only":
                fields.update(enabled=True, state="", error="")
                added.append(c["name"])
            _set(ds["id"], c["id"], **fields)
    for r in rows(ds["id"], enabled_only=False):
        if r["calendar_id"] not in seen and r["on_list"]:
            _set(ds["id"], r["calendar_id"], on_list=False, enabled=False,
                 error="no longer on the account's calendar list; what it had is kept")
    if added:
        log.info("Synapse calendar: now keeping %s", ", ".join(added))
        wake()
    return {"calendars": len(listed), "added": added}


def left_list(user_id: str, org_id: str, calendar_id: str) -> int:
    """A calendar the person took off the account's list in Settings stops being read now, not at the
    next `discover`: the same as one that leaves the list by itself, and what it had is kept."""
    if not ready():
        return 0
    found = db.rows("SELECT c.dataset_id FROM synapse.calendar_sync c JOIN synapse.dataset d ON d.id = c.dataset_id "
                    "WHERE d.user_id = %s AND d.org_id = %s AND c.calendar_id = %s",
                    (str(user_id), str(org_id), calendar_id))
    for r in found:
        _set(r["dataset_id"], calendar_id, on_list=False, enabled=False,
             error="taken off the account's calendar list in Settings; what it had is kept")
    return len(found)


# ---------------------------------------------------------------------------------------------
# one event
# ---------------------------------------------------------------------------------------------

def _moment(part: dict | None) -> tuple[str, datetime | None, bool]:
    """(what Google said, as ISO text; the moment, for said_at; whether it is a whole day)."""
    part = part or {}
    if part.get("dateTime"):
        with contextlib.suppress(ValueError):
            when = datetime.fromisoformat(part["dateTime"].replace("Z", "+00:00"))
            return part["dateTime"], when, False
    if part.get("date"):
        with contextlib.suppress(ValueError):
            d = date.fromisoformat(part["date"])
            return part["date"], datetime(d.year, d.month, d.day, tzinfo=ZONE), True
    return "", None, False


def _said_when(start: datetime | None, end_text: str, all_day: bool) -> str:
    if start is None:
        return "no time given"
    local = start.astimezone(ZONE)
    if all_day:
        day = local.strftime("%A %d %B %Y")
        if end_text and end_text != local.date().isoformat():
            with contextlib.suppress(ValueError):
                last = date.fromordinal(date.fromisoformat(end_text).toordinal() - 1)
                if last > local.date():
                    return f"all day, {day} to {last.strftime('%A %d %B %Y')}"
        return f"all day, {day}"
    return local.strftime("%A %d %B %Y, %H:%M") + f" ({clock.place(ZONE)} time)"


def _video_link(raw: dict) -> str:
    """The event's video call, so a recorded meeting finds its event by it (`meetings.py`)."""
    link = raw.get("hangoutLink") or ""
    if not link:
        for point in (raw.get("conferenceData") or {}).get("entryPoints") or []:
            if point.get("entryPointType") == "video" and point.get("uri"):
                link = point["uri"]
                break
    return str(link)


def payload_of(raw: dict, calendar: dict, owner_email: str = "") -> dict | None:
    """What Synapse stores for one event as Google has it, or None for one that was deleted."""
    from ...google_api import _text_of_html

    if raw.get("status") == "cancelled":
        return None
    start_text, start, all_day = _moment(raw.get("start"))
    end_text, _end, _ = _moment(raw.get("end"))
    title = (raw.get("summary") or "").strip() or "(no title)"
    me = (owner_email or "").lower()
    cal_id = str(calendar.get("calendar_id") or calendar.get("id") or "")
    organiser = (raw.get("organizer") or {})
    org_email = str(organiser.get("email") or "").lower()
    guests = [g for g in raw.get("attendees") or [] if g.get("email")]
    people = [g for g in guests if not g.get("resource") and not g.get("self")
              and str(g["email"]).lower() not in (me, cal_id.lower())
              and not str(g["email"]).endswith("calendar.google.com")]
    description = raw.get("description") or ""
    if "<" in description and ">" in description:
        description = _text_of_html(description)
    lines = [title, f"When: {_said_when(start, end_text, all_day)}"]
    if raw.get("location"):
        lines.append(f"Where: {raw['location'].strip()}")
    lines.append(f"Calendar: {calendar.get('name') or cal_id}")
    if org_email and not organiser.get("self"):
        lines.append(f"Organiser: {organiser.get('displayName') or ''} <{org_email}>".replace(": <", ": <"))
    if guests:
        lines.append("Guests: " + "; ".join(
            f"{g.get('displayName') or g['email']} ({g.get('responseStatus') or 'not answered'})" for g in guests))
    if raw.get("recurrence"):
        lines.append("Repeats: " + "; ".join(str(r) for r in raw["recurrence"]))
    if raw.get("recurringEventId"):
        lines.append("One occurrence of a repeating event, changed on its own.")
    if description.strip():
        lines.append("")
        lines.append(description.strip())
    text = "\n".join(lines)[:TEXT_MAX]
    payload = {
        "kind": "event", "title": title[:300], "text": text, "source": SOURCE,
        "source_key": key_of(cal_id, str(raw.get("id") or "")), "said_at": start.isoformat() if start else None,
        "start": start_text, "end": end_text, "place": (raw.get("location") or "").strip(),
        "attendees": [str(g["email"]).lower() for g in guests],
        "gcal": {"calendar_id": cal_id, "calendar": calendar.get("name") or "", "event_id": raw.get("id") or "",
                 "updated": raw.get("updated") or "", "status": raw.get("status") or "confirmed",
                 "all_day": all_day, "series": raw.get("recurringEventId") or "",
                 "recurrence": raw.get("recurrence") or [], "link": raw.get("htmlLink") or "",
                 "kind": raw.get("eventType") or "default", "meet": _video_link(raw),
                 "ical_uid": raw.get("iCalUID") or ""},
    }
    if org_email and not organiser.get("self") and org_email not in (me, cal_id.lower()) \
            and not org_email.endswith("calendar.google.com"):
        payload["from"] = org_email
    if people:
        payload["to"] = [str(g["email"]).lower() for g in people]
    if not payload["start"]:
        payload["start"] = (raw.get("created") or "")[:10] or datetime.now(timezone.utc).date().isoformat()
    return payload


def _item(ds_id: str, key: str) -> dict | None:
    return db.row("SELECT id, deleted_at, meta->'gcal'->>'updated' AS updated FROM synapse.item WHERE dataset_id = %s "
                  "AND source = %s AND source_key = %s", (str(ds_id), SOURCE, key))


def apply(ds: dict, raw: dict, calendar: dict, *, lane: str, by: str, out: dict, owner_email: str = "") -> None:
    """One event from Google: stored, stored again when it changed, deleted when it went. Never raises."""
    from .. import datasets, ingest

    cal_id = str(calendar.get("calendar_id") or calendar.get("id") or "")
    key = key_of(cal_id, str(raw.get("id") or ""))
    try:
        old = _item(ds["id"], key)
        payload = payload_of(raw, calendar, owner_email)
        if payload is None:
            if old and old["deleted_at"] is None:
                ingest.delete(ds, str(old["id"]), by=by)
                # Its key freed: gone from the calendar, not deleted by a person (D60 keeps a person's).
                db.run("UPDATE synapse.item SET source_key = source_key || '#gone-' || floor(extract(epoch FROM "
                       "now())) WHERE id = %s", (old["id"],))
                out["deleted"] = out.get("deleted", 0) + 1
            return
        if old and old["deleted_at"] is not None:
            out["kept_out"] = out.get("kept_out", 0) + 1
            return
        if old:
            if old["updated"] == payload["gcal"]["updated"]:
                out["same"] = out.get("same", 0) + 1
                return
            got = ingest.edit(ds, str(old["id"]), {k: v for k, v in payload.items()
                                                    if k not in ("kind", "source", "source_key")}, by=by)
            out["changed" if got.get("ok") else "failed"] = out.get("changed" if got.get("ok") else "failed", 0) + 1
            return
        me = datasets.me(ds)
        got = ingest.store(ds, {**payload, "readers": [me], "owner": me}, by=by, lane=lane)
        out["stored" if got.get("ok") else "failed"] = out.get("stored" if got.get("ok") else "failed", 0) + 1
        if not got.get("ok"):
            log.warning("Synapse calendar: %s not stored: %s", key, got.get("why"))
    except Exception:  # noqa: BLE001 - one event never stops the others
        log.exception("Synapse calendar: %s could not be kept", key)
        out["failed"] = out.get("failed", 0) + 1


# ---------------------------------------------------------------------------------------------
# reading a calendar
# ---------------------------------------------------------------------------------------------

def list_first(ds: dict, row: dict, pages: int = PAGES_PER_BEAT) -> dict:
    """The next pages of a calendar's first listing; once the last is in, its sync token is kept."""
    cal, who = _open(ds)
    out: dict = {}
    page, token = row.get("page_token") or "", ""
    owner = str(getattr(who, "email", "") or "")
    if row.get("state") != "listing":
        _set(ds["id"], row["calendar_id"], state="listing", page_token="", listed=0, listing_started_at=_now())
        page = ""
    listed = int(row.get("listed") or 0) if row.get("state") == "listing" else 0
    for _ in range(pages):
        got = _run(who, _page(cal, row["calendar_id"], page=page))
        items = got.get("items") or []
        for raw in items:
            apply(ds, raw, row, lane="backfill", by="calendar backfill", out=out, owner_email=owner)
        listed += len(items)
        page = got.get("nextPageToken") or ""
        token = got.get("nextSyncToken") or ""
        _set(ds["id"], row["calendar_id"], page_token=page, listed=listed)
        if not page:
            break
    if not page and token:
        _set(ds["id"], row["calendar_id"], state="synced", sync_token=token, page_token="", listed=listed,
             listed_at=_now(), last_ok_at=_now(), last_read_at=_now(), error="", failures=0, counts=out)
        out["listed"] = listed
        out["done"] = True
    return out


def read_changes(ds: dict, row: dict) -> dict:
    """What changed on a calendar since its sync token, written here; the token moved on after."""
    cal, who = _open(ds)
    out: dict = {}
    owner = str(getattr(who, "email", "") or "")
    page, token = "", row["sync_token"]
    while True:
        try:
            got = _run(who, _page(cal, row["calendar_id"], page=page, sync_token=row["sync_token"]))
        except Exception as exc:
            if _status(exc) == 410:
                # Google no longer honours the token: listed whole again, and checked once it is.
                _set(ds["id"], row["calendar_id"], state="", sync_token="", page_token="",
                     error="Google asked for the calendar to be read whole again (410)")
                return {"relist": True}
            raise
        for raw in got.get("items") or []:
            apply(ds, raw, row, lane="live", by="calendar", out=out, owner_email=owner)
        page = got.get("nextPageToken") or ""
        token = got.get("nextSyncToken") or token
        if not page:
            break
    _set(ds["id"], row["calendar_id"], sync_token=token, last_read_at=_now(), last_ok_at=_now(), error="",
         failures=0, counts=out)
    if out.get("stored") or out.get("changed"):
        # A new or changed invitation: its guests are looked up on LinkedIn soon (`meeting_people`).
        # And its guests added to his iCloud contacts (`meeting_contacts`).
        from ... import meeting_contacts, meeting_people

        meeting_people.poke()
        meeting_contacts.poke()
    return out


def reconcile(ds: dict, row: dict, *, by: str = "nightly") -> dict:
    """The calendar's whole list against Synapse's items of it: what is missing stored, what is gone deleted."""
    from .. import ingest

    cal, who = _open(ds)
    owner = str(getattr(who, "email", "") or "")
    google: dict[str, dict] = {}
    page = ""
    while True:
        got = _run(who, _page(cal, row["calendar_id"], page=page))
        for raw in got.get("items") or []:
            if raw.get("status") != "cancelled":
                google[key_of(row["calendar_id"], str(raw.get("id") or ""))] = raw
        page = got.get("nextPageToken") or ""
        if not page:
            break
    have = {r["source_key"]: r for r in db.rows(
        "SELECT id, source_key, deleted_at FROM synapse.item WHERE dataset_id = %s AND source = %s AND "
        "left(source_key, %s) = %s AND strpos(source_key, '#gone-') = 0",
        (str(ds["id"]), SOURCE, len(prefix_of(row["calendar_id"])), prefix_of(row["calendar_id"])))}
    out: dict = {"by": by, "at": _now().isoformat(), "calendar": len(google),
                 "synapse": sum(1 for r in have.values() if r["deleted_at"] is None)}
    missing = [k for k in google if k not in have]
    extra = [k for k, r in have.items() if k not in google and r["deleted_at"] is None]
    done: dict = {}
    for k in missing:
        apply(ds, google[k], row, lane="backfill", by=f"calendar check ({by})", out=done, owner_email=owner)
    for k in extra:
        try:
            ingest.delete(ds, str(have[k]["id"]), by=f"calendar check ({by})")
            db.run("UPDATE synapse.item SET source_key = source_key || '#gone-' || floor(extract(epoch FROM now())) "
                   "WHERE id = %s", (have[k]["id"],))
        except Exception:  # noqa: BLE001
            log.exception("Synapse calendar: %s could not be deleted", k)
    out.update({"missing": len(missing), "extra": len(extra),
                "deleted_in_synapse": sum(1 for r in have.values() if r["deleted_at"] is not None),
                "stored": done.get("stored", 0), "failed": done.get("failed", 0)})
    _set(ds["id"], row["calendar_id"], last_reconcile_at=_now(), reconcile=out)
    if missing or extra:
        log.info("Synapse calendar %s: checked, %d missing stored, %d gone deleted", row["name"], len(missing),
                 len(extra))
    return out


def reconcile_due(row: dict, now: float | None = None) -> bool:
    """Once a night, after RECONCILE_HOUR on the installation's clock, once the first listing is done."""
    if row.get("state") != "synced":
        return False
    local = datetime.fromtimestamp(time.time() if now is None else now, ZONE)
    if local.hour < RECONCILE_HOUR:
        return False
    last = row.get("last_reconcile_at")
    return last is None or last.astimezone(ZONE).date() < local.date()


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------------------------
# the beat
# ---------------------------------------------------------------------------------------------

def beat_one(ds: dict, row: dict) -> dict:
    """One calendar's turn: its first listing's next pages, or its changes, and the night's check. Only one
    process reads a calendar at a time (a lock on it), so a command run beside Rouh waits."""
    name = f"synapse.calendar.beat:{row['dataset_id']}:{row['calendar_id']}"
    if not db.value("SELECT pg_try_advisory_lock(hashtext(%s))", (name,)):
        return {"busy": True}
    out: dict = {}
    try:
        try:
            if row.get("state") == "synced":
                out["changes"] = read_changes(ds, row)
            else:
                out["listing"] = list_first(ds, row)
                if (out["listing"] or {}).get("done") and row.get("listed_at") is not None:
                    # Listed whole again after Google's 410: checked at once.
                    out["checked"] = reconcile(ds, row_of(ds["id"], row["calendar_id"]) or row, by="after a 410")
        except Exception as exc:  # noqa: BLE001 - said on the card, and tried again next beat
            log.warning("Synapse calendar %s: not read: %s", row.get("name"), exc)
            db.run("UPDATE synapse.calendar_sync SET last_read_at = now(), failures = failures + 1, error = %s, "
                   "updated_at = now() WHERE dataset_id = %s AND calendar_id = %s",
                   (f"{type(exc).__name__}: {exc}"[:500], str(row["dataset_id"]), row["calendar_id"]))
            out["error"] = str(exc)
            return out
        now_row = row_of(ds["id"], row["calendar_id"]) or row
        if reconcile_due(now_row):
            with contextlib.suppress(Exception):
                out["checked"] = reconcile(ds, now_row)
        if any((v or {}).get("stored") or (v or {}).get("changed") for v in out.values() if isinstance(v, dict)):
            # An event is labelled by its calendar, and a meeting by its event (`rouh/silos.py`).
            from ... import silos
            silos.fill(ds, ("events", "meetings"))
        return out
    finally:
        db.run("SELECT pg_advisory_unlock(hashtext(%s))", (name,))


def beat() -> None:
    from .. import datasets

    if not ready():
        return
    for ds in db.rows("SELECT * FROM synapse.dataset WHERE master"):
        if not _connected(ds):
            continue
        with contextlib.suppress(Exception):
            discover(ds)
        for row in rows(ds["id"]):
            beat_one(datasets.by_id(row["dataset_id"]) or ds, row)


def wake() -> None:
    _wake.set()


def _loop() -> None:
    from django.db import connection

    time.sleep(10)
    while True:
        try:
            if db.ready():
                beat()
        except Exception:  # noqa: BLE001 - the loop never dies
            log.exception("the Synapse calendar sync stumbled")
        finally:
            connection.close()
        _wake.wait(POLL_SECONDS)
        _wake.clear()


def start() -> None:
    """The beat, once per process, on a thread of its own (`worker.start` starts it)."""
    global _started
    with _start_lock:
        if _started or os.environ.get("SYNAPSE_CALENDAR_SYNC", "1") == "0":
            return
        _started = True
    threading.Thread(target=_loop, name="synapse-calendar", daemon=True).start()


# ---------------------------------------------------------------------------------------------
# health
# ---------------------------------------------------------------------------------------------

def health(ds_id: str) -> list[dict]:
    """Each calendar's sync, for the lab's homepage and `manage.py synapse_calendar status`."""
    if not ready():
        return []
    out = []
    for r in rows(ds_id, enabled_only=False):
        items = db.row("SELECT count(*) FILTER (WHERE deleted_at IS NULL) AS kept, count(*) FILTER (WHERE deleted_at "
                       "IS NULL AND xray IS NOT NULL) AS read, count(*) FILTER (WHERE deleted_at IS NOT NULL AND "
                       "strpos(source_key, '#gone-') = 0) AS deleted FROM synapse.item WHERE dataset_id = %s AND "
                       "source = %s AND left(source_key, %s) = %s",
                       (str(ds_id), SOURCE, len(prefix_of(r["calendar_id"])), prefix_of(r["calendar_id"]))) or {}
        ok = r.get("last_ok_at")
        stale = bool(r["enabled"] and r["state"] == "synced" and
                     (ok is None or (_now() - ok).total_seconds() > STALE_MINUTES * 60))
        out.append({"calendar": r["name"], "calendar_id": r["calendar_id"], "access": r["access"],
                    "enabled": r["enabled"], "state": r["state"] or "not started", "listed": r["listed"],
                    "listed_at": r.get("listed_at"), "last_read_at": r.get("last_read_at"), "last_ok_at": ok,
                    "counts": r.get("counts") or {}, "error": r.get("error") or "", "failures": r["failures"],
                    "stale": stale, "kept": items.get("kept") or 0, "read_by_model": items.get("read") or 0,
                    "deleted_in_synapse": items.get("deleted") or 0, "reconcile": r.get("reconcile") or {},
                    "last_reconcile_at": r.get("last_reconcile_at")})
    return out


__all__ = ["SOURCE", "apply", "beat", "beat_one", "discover", "health", "key_of", "list_first", "payload_of",
           "read_changes", "reconcile", "row_of", "rows", "start", "wake"]
