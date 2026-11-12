"""Every meeting in the meeting library, kept in Synapse Master (9 October 2026).

Petar, by voice, "build it": Synapse Master keeps itself in step with the meeting library at
`MEETING_LIBRARY_URL` (task 67), his own edits to transcripts included. The library always holds the
original. Synapse keeps a copy it can search, never edits that copy, and replaces it from the library
whenever the library changes. Nothing here writes to the library, sends a recap or changes a meeting.

**What the library offers** (its half was built beside this one, to one contract): every meeting has a
whole-number `revision` that goes up by one on any change (transcript, speaker, summary, decisions,
action items, category, participants, readers, being withdrawn); `GET /api/v1/changes?since=&limit=`
lists the changes in order; `GET /api/v1/meetings/<id>` is one meeting whole; and a signed webhook,
`meeting.changed`, is posted to `/api/hooks/meeting-library` with `X-Library-Signature: sha256=<HMAC of
the raw body>` and a timestamp. It is read with the library's own key, `Authorization: Bearer ml_...`.

**Settings** are `MEETING_LIBRARY_URL`, `MEETING_LIBRARY_KEY` and `MEETING_LIBRARY_WEBHOOK_SECRET`, from
`/etc/rouh/meeting-library.env` or Rouh's environment, read again on every beat. Until the address and
the key are there the sync is on and waiting, and the lab says why; without the secret every webhook is
refused and polling alone keeps it in step. In the containers they are the stack's settings file, and
`MEETING_LIBRARY_URL` is the library's public HTTPS address, which the core reaches directly (its `edge`
network). Rouh never reads the library's database, only this API, so the library can run on any server:
on 1 November 2026 it moved off the machine Rouh runs on, and only the address changed.

**When a meeting is read again.**
- A webhook is only a signal: it is checked (signature, a timestamp within five minutes, and a
  signature never seen before, or 401), and the meeting is queued. The meeting itself is always fetched.
- The revision guard: a revision at or below the one Synapse holds is never acted on.
- A meeting ready for the first time is read at once. One Synapse already holds is read only after ten
  minutes with no further change, so ten name fixes in a row are one update. A withdrawal is at once.
- Every ten minutes `/changes` is read from the last change seen, which catches a missed webhook.
- Every night at 03:30 on the owner's clock, before the 04:00 dream, every meeting's
  revision is compared with Synapse's, and any that differ are queued.
- The first time, every meeting the library holds is read (the backfill), on the queue's backfill lane.

**What is kept.** One item per meeting, kind `meeting`, key `meeting:<id>`. Its text is the title, the
date, who took part, the category, and the library's own summary, decisions and action items, as they
are: Synapse never extracts them again. That item gets the usual single X-ray call. The transcript is
passages of their own (`part` 'transcript', migration 0110), one or more speaker turns each, cut by the
time they cover and never by their words, so an edit moves no boundary; each keeps its segment ids,
first and last millisecond and speakers, and the sha256 of its words. They are embedded and found by
their words, Bulgarian word forms too, and never X-rayed one by one. On an edit only passages whose hash
changed are embedded again, and the ones gone are deleted. The X-ray runs again only when the meeting's
own text changed (summary, decisions, action items, participants, title, date or category).

**Links.** The meeting to its calendar event (`recorded`), by the event's id, or by the meeting link and
start time; to the people who took part (`attended`) or were invited (`invited`), by address; to a
speaker (`spoke`) only once the library says that speaker is confirmed, so a renamed speaker's old link
goes and the new one comes.

**Readers, the part that matters most.** The owner of Master reads every meeting. Anyone else
reads one only when their address is among the meeting's readers in the library; the library's own
administrator rights are never carried over. A change of readers changes the item, every passage (the
`can_read` they copy from it), the topics it named and the layers built from it, in the same update.
Sensitivity comes from the category: hiring is private, anything about health is special, and the rest
is normal unless the X-ray says higher.

**Withdrawn** means the item, its passages and everything derived from them are deleted the way
Synapse deletes (`ingest.delete`): X-ray, layers, links, indexes and logged prompts.

Rouh's chat reads meetings with two tools of its own, `meeting_search` and `meeting_read`, held to the
same readers; and the Synapse lab shows every update in Activity and the sync's state on its homepage.
"""
from __future__ import annotations

import contextlib
import hashlib
import hmac
import json
import logging
import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlsplit
from zoneinfo import ZoneInfo

from .. import db
from ..db import Json

log = logging.getLogger("rouh.synapse.meetings")

SOURCE = "meeting-library"
#: The part a meeting's transcript passages are (migration 0110).
PART = "transcript"
NAMES = ("MEETING_LIBRARY_URL", "MEETING_LIBRARY_KEY", "MEETING_LIBRARY_WEBHOOK_SECRET")
ENV_FILE = "/etc/rouh/meeting-library.env"
#: How often `/changes` is read when nothing else wakes the sync (seconds).
POLL_SECONDS = float(os.environ.get("SYNAPSE_MEETINGS_POLL_SECONDS") or 600)
#: How long a meeting Synapse already holds must go unchanged before it is read again (seconds).
QUIET_SECONDS = float(os.environ.get("SYNAPSE_MEETINGS_QUIET_SECONDS") or 600)
#: How often the queue is looked at for meetings that are due (seconds).
BEAT_SECONDS = float(os.environ.get("SYNAPSE_MEETINGS_BEAT_SECONDS") or 20)
#: A webhook's timestamp may be this far from now, either way (seconds).
SKEW_SECONDS = 300
#: The signatures of webhooks taken are kept this long, so one sent again is refused.
HOOK_KEEP_DAYS = 30
#: The nightly check, on the owner's clock, before the 04:00 dream (`dreaming.AT`).
CHECK_AT = (3, 30)
#: Meetings are said in their text on one clock, the installation's own (`clock.DEFAULT`,
#: `ROUH_DEFAULT_ZONE`), which is also whose clock the nightly check is on when the owner's is not
#: known. It was Sofia, written here, until 20 October 2026; the live machine's setting says Sofia.


def _zone() -> ZoneInfo:
    from ... import clock

    return clock.DEFAULT


#: Which account's Master keeps the library: the installation's first account unless
#: `SYNAPSE_MEETINGS_USER` names another.
OWNER_USER = os.environ.get("SYNAPSE_MEETINGS_USER") or "1"
PAGE = 200
#: Meetings read again per pass, before the loop looks round again.
PER_BEAT = 25
#: A transcript passage covers about this much time; a speaker's turn longer than it is cut at a segment.
WINDOW_MS = 120_000
#: ... and never more than this many words, however fast they spoke.
MOST_WORDS = 450
#: How many lines of what happened lately the lab shows.
RECENT = 30

_started = False
_start_lock = threading.Lock()
_wake = threading.Event()


def key_of(meeting_id) -> str:
    return f"meeting:{meeting_id}"


# ---------------------------------------------------------------------------------------------
# settings: the file, or Rouh's environment
# ---------------------------------------------------------------------------------------------

def _env_file() -> str:
    return os.environ.get("MEETING_LIBRARY_ENV_FILE") or ENV_FILE


def _read_env_file(path: str) -> dict:
    out: dict = {}
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                name, value = line.split("=", 1)
                name = name.strip().removeprefix("export ").strip()
                value = value.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                    value = value[1:-1]
                out[name] = value
    except OSError:
        return {}
    return out


def settings() -> dict:
    """The library's address, key and webhook secret, and which are missing. Never logged or shown."""
    path = _env_file()
    filed = _read_env_file(path)
    got = {n: (os.environ.get(n) or filed.get(n) or "").strip() for n in NAMES}
    url = got["MEETING_LIBRARY_URL"].rstrip("/")
    url = re.sub(r"/api/v1$", "", url)
    return {"url": url, "key": got["MEETING_LIBRARY_KEY"], "secret": got["MEETING_LIBRARY_WEBHOOK_SECRET"],
            "missing": [n for n in NAMES if not got[n]], "file": path, "file_exists": os.path.exists(path)}


def off_words(cfg: dict | None = None) -> str:
    """Why the sync is waiting, in a sentence, or "" when it can run."""
    cfg = cfg or settings()
    if cfg["url"] and cfg["key"]:
        return ""
    where = (f"{cfg['file']} does not exist yet" if not cfg["file_exists"] else
             f"{cfg['file']} does not have {' or '.join(n for n in cfg['missing'] if n != NAMES[2])}")
    return (f"The meeting library is not set up: {where}, and Settings has none either. The owner sets its "
            "address and key in Anatomy, Connections, Keys, Meeting library; the sync is on and waiting and "
            "starts by itself once they are there.")


def where(cfg: dict | None = None) -> str:
    """The library's host, for the lab: never its key."""
    cfg = cfg or settings()
    return urlsplit(cfg["url"]).netloc if cfg["url"] else ""


# ---------------------------------------------------------------------------------------------
# reaching the library
# ---------------------------------------------------------------------------------------------

class NotSetUp(RuntimeError):
    """The library's address or key is not on this server yet."""


class NotFound(RuntimeError):
    """The library says there is no such meeting for this key (404)."""


class Gone(RuntimeError):
    """The library says the meeting is gone (410)."""


def _get(path: str, params: dict | None = None) -> dict:
    import httpx

    cfg = settings()
    if not cfg["url"] or not cfg["key"]:
        raise NotSetUp(off_words(cfg))
    r = httpx.get(cfg["url"] + path, params=params or None, timeout=30,
                  headers={"Authorization": f"Bearer {cfg['key']}", "Accept": "application/json"})
    if r.status_code == 404:
        raise NotFound(f"the library has no {path} for this key (404)")
    if r.status_code == 410:
        raise Gone(f"the library says {path} is gone (410)")
    if r.status_code >= 400:
        raise RuntimeError(f"the library answered {r.status_code} to {path}: {r.text[:200]}")
    got = r.json()
    if not isinstance(got, dict):
        raise RuntimeError(f"the library answered {path} with something that is not an object")
    return got


def read_changes(since: int, limit: int = PAGE) -> dict:
    return _get("/api/v1/changes", {"since": int(since), "limit": int(limit)})


def fetch(meeting_id) -> dict:
    return _get(f"/api/v1/meetings/{quote(str(meeting_id), safe='')}")


def listing(offset: int, limit: int = PAGE) -> dict:
    return _get("/api/v1/meetings", {"limit": int(limit), "offset": int(offset), "scope": "all"})


# ---------------------------------------------------------------------------------------------
# rows
# ---------------------------------------------------------------------------------------------

def ready() -> bool:
    return bool(db.value("SELECT to_regclass('synapse.meeting_sync') IS NOT NULL"))


def ensure() -> list[dict]:
    """The Masters that keep the library: the owner's (`OWNER_USER`), given its row the first time it is wanted."""
    if not ready():
        return []
    if db.value("SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'synapse' "
                "AND table_name = 'dataset' AND column_name = 'master')"):
        db.run("INSERT INTO synapse.meeting_sync (dataset_id) SELECT id FROM synapse.dataset WHERE master "
               "AND user_id = %s ON CONFLICT DO NOTHING", (OWNER_USER,))
    return db.rows("SELECT * FROM synapse.meeting_sync WHERE enabled ORDER BY added_at")


def row_of(ds_id: str) -> dict | None:
    return db.row("SELECT * FROM synapse.meeting_sync WHERE dataset_id = %s", (str(ds_id),))


def _set(ds_id: str, **fields) -> None:
    if not fields:
        return
    cols = ", ".join(f"{k} = %s" for k in fields)
    db.run(f"UPDATE synapse.meeting_sync SET {cols}, updated_at = now() WHERE dataset_id = %s",
           [Json(v) if isinstance(v, (dict, list)) else v for v in fields.values()] + [str(ds_id)])


def _count(ds_id: str, what: str, n: int = 1) -> None:
    db.run("UPDATE synapse.meeting_sync SET counts = jsonb_set(counts, ARRAY[%s], to_jsonb(coalesce((counts->>%s)::int, "
           "0) + %s)) WHERE dataset_id = %s", (what, what, int(n), str(ds_id)))


def _said(ds_id: str, line: str, **data) -> None:
    """One line of what happened lately, newest first, for the lab."""
    entry = {"at": _now().isoformat(), "said": line, **data}
    db.run("UPDATE synapse.meeting_sync SET recent = (SELECT coalesce(jsonb_agg(e ORDER BY n), '[]'::jsonb) FROM "
           "jsonb_array_elements(jsonb_build_array(%s::jsonb) || recent) WITH ORDINALITY AS x(e, n) WHERE n <= %s) "
           "WHERE dataset_id = %s", (Json(entry), RECENT, str(ds_id)))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _when(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    with contextlib.suppress(ValueError, TypeError):
        got = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return got if got.tzinfo else got.replace(tzinfo=timezone.utc)
    return None


def _int(value) -> int | None:
    try:
        return int(value) if value is not None and str(value).strip() != "" else None
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------------------------
# the webhook: a signal, checked, and the meeting queued
# ---------------------------------------------------------------------------------------------

def _header(headers, *names) -> str:
    for n in names:
        v = headers.get(n) if hasattr(headers, "get") else None
        if v:
            return str(v).strip()
    return ""


def _moment_of(stamp: str) -> float | None:
    if not stamp:
        return None
    with contextlib.suppress(ValueError):
        n = float(stamp)
        return n / 1000.0 if n > 1e12 else n
    got = _when(stamp)
    return got.timestamp() if got else None


def verify(body: bytes, headers, secret: str, now: float | None = None) -> tuple[bool, str, str]:
    """(taken, why not, the digest to remember it by). A message is taken only when it is signed with the
    secret (the raw body, or the timestamp and the body, either way the library signs it), its timestamp is
    within five minutes, and its signature was never taken before."""
    if not secret:
        return False, "the webhook secret is not on this server, so no webhook can be checked", ""
    given = _header(headers, "X-Library-Signature", "x-library-signature")
    stamp = _header(headers, "X-Library-Timestamp", "x-library-timestamp", "X-Library-Time", "X-Timestamp")
    if not given:
        return False, "no X-Library-Signature", ""
    if not stamp:
        return False, "no timestamp", ""
    at = _moment_of(stamp)
    now = time.time() if now is None else now
    if at is None:
        return False, "a timestamp that cannot be read", ""
    if abs(now - at) > SKEW_SECONDS:
        return False, "a timestamp more than five minutes from now: an old message sent again, or a wrong clock", ""
    sig = given.split("=", 1)[1] if given.lower().startswith("sha256=") else given
    key = secret.encode()
    wanted = [hmac.new(key, body, hashlib.sha256).hexdigest(),
              hmac.new(key, stamp.encode() + b"." + body, hashlib.sha256).hexdigest()]
    if not any(hmac.compare_digest(sig.strip().lower(), w) for w in wanted):
        return False, "a signature that does not match", ""
    return True, "", hashlib.sha256(sig.strip().lower().encode()).hexdigest()


def _first_time(digest: str) -> bool:
    """True the first time a signature is taken; False when it was taken before (a replay)."""
    db.run("DELETE FROM synapse.meeting_hook WHERE seen_at < now() - make_interval(days => %s)", (HOOK_KEEP_DAYS,))
    return bool(db.value("INSERT INTO synapse.meeting_hook (digest) VALUES (%s) ON CONFLICT DO NOTHING RETURNING 1",
                         (digest,)))


def receive(body: bytes, headers) -> tuple[int, dict]:
    """`POST /api/hooks/meeting-library`: (status, answer). 401 for anything forged or sent again."""
    cfg = settings()
    rows = ensure()
    ok, why, digest = verify(body, headers, cfg["secret"])
    if ok and not _first_time(digest):
        ok, why = False, "a message already taken, sent again"
    if not ok:
        log.warning("meeting library webhook refused: %s", why)
        for r in rows:
            _count(r["dataset_id"], "webhooks_refused")
            _said(r["dataset_id"], f"A webhook was refused (401): {why}.", kind="refused")
        return 401, {"error": f"Refused: {why}."}
    try:
        data = json.loads(body.decode("utf-8"))
        mid = str(data["meeting_id"]).strip()
        revision = _int(data.get("revision"))
        state = str(data.get("state") or "").strip().lower()
        if not mid:
            raise ValueError("no meeting_id")
    except (ValueError, KeyError, TypeError, UnicodeDecodeError) as exc:
        db.run("DELETE FROM synapse.meeting_hook WHERE digest = %s", (digest,))
        return 400, {"error": f"That message could not be read: {exc}."}
    done = []
    try:
        for r in rows:
            done.append(hear(str(r["dataset_id"]), mid, revision, state, by="webhook"))
            _set(r["dataset_id"], last_event_at=_now())
            _count(r["dataset_id"], "webhooks")
    except Exception:
        # Not taken after all: the library sends it again, and that one is not a replay.
        db.run("DELETE FROM synapse.meeting_hook WHERE digest = %s", (digest,))
        raise
    wake()
    return 200, {"ok": True, "meeting_id": mid, "revision": revision, "queued": done}


# ---------------------------------------------------------------------------------------------
# the queue: heard of, and due
# ---------------------------------------------------------------------------------------------

def _stored(ds_id: str, meeting_id: str) -> dict | None:
    """The item Synapse keeps of a meeting: {id, revision, kept_out}, or None. A meeting a person deleted
    in Synapse is kept out (D60): never stored again, never written back."""
    row = db.row("SELECT id, deleted_at, meta->'meeting'->>'revision' AS revision FROM synapse.item WHERE "
                 "dataset_id = %s AND source = %s AND source_key = %s", (str(ds_id), SOURCE, key_of(meeting_id)))
    if not row:
        return None
    return {"id": str(row["id"]), "revision": _int(row["revision"]), "kept_out": row["deleted_at"] is not None}


def hear(ds_id: str, meeting_id, revision: int | None, state: str, *, by: str,
         changed_at=None) -> str:
    """A meeting changed: queued, or not, by the revision guard and the wait after edits. Says what it did."""
    mid = str(meeting_id).strip()
    state = (state or "").strip().lower()
    if not mid:
        return "nothing"
    have = _stored(ds_id, mid)
    if have and have["kept_out"]:
        return "kept out: deleted in Synapse by a person"
    if revision is not None and have and have["revision"] is not None and revision <= have["revision"]:
        if revision < have["revision"] or by == "webhook":
            # Said when it is news: a poll or a check naming the revision already taken is the usual.
            _count(ds_id, "old_ignored")
            _said(ds_id, f"Meeting {mid}: revision {revision} ignored, Synapse has revision {have['revision']}.",
                  meeting=mid, revision=revision, kind="ignored", by=by)
        return f"ignored: revision {revision} is not newer than the {have['revision']} Synapse has"
    if state == "processing":
        # The library is still working on it; its ready revision comes with a change of its own.
        return "not queued: still being processed in the library"
    if state == "withdrawn" and not have:
        db.run("DELETE FROM synapse.meeting_queue WHERE dataset_id = %s AND meeting_id = %s", (str(ds_id), mid))
        return "nothing to delete: Synapse never had it"
    now = _now()
    first = have is None
    at_once = first or state == "withdrawn"
    since = _when(changed_at) or now
    due = now if at_once else max(now, since + timedelta(seconds=QUIET_SECONDS))
    with db.atomic():
        db.run("INSERT INTO synapse.meeting_queue (dataset_id, meeting_id, revision, state, heard_by, due_at, heard) "
               "VALUES (%s, %s, %s, %s, %s, %s, 0) ON CONFLICT DO NOTHING", (str(ds_id), mid, revision, state, by, due))
        q = db.row("SELECT * FROM synapse.meeting_queue WHERE dataset_id = %s AND meeting_id = %s FOR UPDATE",
                   (str(ds_id), mid))
        if q["heard"] and revision is not None and q["revision"] is not None and revision <= q["revision"]:
            db.run("UPDATE synapse.meeting_queue SET heard_at = now() WHERE dataset_id = %s AND meeting_id = %s",
                   (str(ds_id), mid))
            return f"already queued at revision {q['revision']}"
        # A meeting already queued to be read at once stays at once; one Synapse holds waits for the quiet.
        due = min(q["due_at"], due) if (at_once and q["heard"]) else due
        lane_by = "backfill" if (q["heard_by"] == "backfill" or by == "backfill") and first else by
        db.run("UPDATE synapse.meeting_queue SET revision = %s, state = %s, heard_by = %s, heard_at = now(), "
               "heard = heard + 1, due_at = %s, error = '', tries = 0 WHERE dataset_id = %s AND meeting_id = %s",
               (revision if revision is not None else q["revision"], state or q["state"], lane_by, due,
                str(ds_id), mid))
    wait = (due - now).total_seconds()
    _count(ds_id, "heard")
    if wait > 1:
        _said(ds_id, f"Meeting {mid}: revision {revision if revision is not None else '?'} heard ({by}); it is read "
                     f"after {int(round(wait / 60.0)) or 1} minutes with no further change.",
              meeting=mid, revision=revision, kind="waits", by=by)
        return f"queued: read at {due.isoformat()} unless it changes again"
    return "queued: read now"


def queue_now(ds_id: str, meeting_id, *, by: str = "by hand") -> None:
    """Read one meeting again now, whatever its revision (a command, or the lab)."""
    db.run("INSERT INTO synapse.meeting_queue (dataset_id, meeting_id, heard_by, due_at) VALUES (%s, %s, %s, now()) "
           "ON CONFLICT (dataset_id, meeting_id) DO UPDATE SET due_at = now(), heard_by = excluded.heard_by, "
           "error = '', tries = 0", (str(ds_id), str(meeting_id)))
    wake()


# ---------------------------------------------------------------------------------------------
# polling, the backfill and the nightly check
# ---------------------------------------------------------------------------------------------

def poll(ds: dict, row: dict, *, by: str = "poll") -> dict:
    """`/changes` read from the last change seen; each one heard; the place moved on after."""
    since = int(row.get("since_seq") or 0)
    out = {"from": since, "changes": 0, "queued": 0}
    queued: set[str] = set()
    _set(ds["id"], last_poll_at=_now())
    while True:
        got = read_changes(since)
        changes = got.get("changes") or []
        for c in changes:
            said = hear(str(ds["id"]), c.get("meeting_id"), _int(c.get("revision")), str(c.get("state") or ""),
                        by=by, changed_at=c.get("changed_at"))
            if said.startswith("queued"):
                queued.add(str(c.get("meeting_id")))
            out["queued"] = len(queued)
        out["changes"] += len(changes)
        last = max([since] + [_int(c.get("seq")) or 0 for c in changes])
        nxt = _int(got.get("next_since"))
        nxt = max(last, nxt if nxt is not None else last)
        _set(ds["id"], since_seq=nxt)
        if not changes or nxt <= since:
            break
        since = nxt
    out["to"] = since
    _set(ds["id"], last_poll_ok_at=_now(), error="", failures=0)
    if out["changes"]:
        _said(ds["id"], f"Read {out['changes']} changes from the library ({by}); {out['queued']} meetings queued.",
              kind="poll", by=by)
    return out


def poll_due(row: dict) -> bool:
    last = row.get("last_poll_at")
    return last is None or (_now() - last).total_seconds() >= POLL_SECONDS


def backfill(ds: dict, row: dict) -> dict:
    """Every meeting the library holds now: its whole change list from the start, and its list of meetings
    for any that list does not name. Each one is read at once, on the queue's backfill lane."""
    _set(ds["id"], backfill_state="listing", backfill_started_at=row.get("backfill_started_at") or _now())
    got = poll(ds, {**row, "since_seq": 0 if row.get("backfill_state") != "listing" else row.get("since_seq") or 0},
               by="backfill")
    listed, extra, offset, unread = 0, 0, int(row.get("backfill_offset") or 0), ""
    try:
        while True:
            page = listing(offset)
            meetings = page.get("meetings") or []
            for m in meetings:
                mid = str(m.get("id") or m.get("meeting_id") or "").strip()
                if not mid:
                    continue
                listed += 1
                state = str(m.get("state") or "").lower()
                if m.get("withdrawn") is True:
                    state = "withdrawn"
                if _stored(str(ds["id"]), mid) is None and not db.value(
                        "SELECT 1 FROM synapse.meeting_queue WHERE dataset_id = %s AND meeting_id = %s",
                        (str(ds["id"]), mid)):
                    extra += hear(str(ds["id"]), mid, _int(m.get("revision")), state or "ready",
                                  by="backfill").startswith("queued")
            offset += len(meetings)
            _set(ds["id"], backfill_offset=offset)
            if len(meetings) < PAGE:
                break
    except Exception as exc:  # noqa: BLE001 - the changes are the backfill; the list only adds to them
        unread = f"the list of meetings was not read ({type(exc).__name__}: {str(exc)[:200]}); the changes were"
    summary = {"changes": got["changes"], "queued_from_changes": got["queued"], "listed": listed,
               "queued_from_list": extra, "done_at": _now().isoformat(), **({"note": unread} if unread else {})}
    _set(ds["id"], backfill_state="done", backfill_done_at=_now(), backfill=summary)
    _said(ds["id"], f"Backfill listed: {got['changes']} changes and {listed} meetings in the library; "
                    f"{got['queued'] + extra} meetings queued to be read.", kind="backfill")
    return summary


def check_due(ds: dict, row: dict, now: datetime | None = None) -> bool:
    """Once a night at 03:30 on the owner's clock, after the backfill."""
    if row.get("backfill_state") != "done":
        return False
    zone = owner_zone(ds)
    local = (now or _now()).astimezone(zone)
    if (local.hour, local.minute) < CHECK_AT:
        return False
    last = row.get("last_check_at")
    return last is None or last.astimezone(zone).date() < local.date()


def owner_zone(ds: dict) -> ZoneInfo:
    with contextlib.suppress(Exception):
        from ... import clock
        from ...tenancy import Tenancy

        who = Tenancy().identity_of(str(ds["user_id"]))
        if who is not None and clock.reported(who):
            return clock.zone_of(who)
    return _zone()


def check(ds: dict, *, by: str = "nightly") -> dict:
    """Every meeting's revision in the library against Synapse's; any that differ queued."""
    latest: dict[str, dict] = {}
    since = 0
    while True:
        got = read_changes(since)
        changes = got.get("changes") or []
        for c in changes:
            mid = str(c.get("meeting_id") or "").strip()
            rev = _int(c.get("revision"))
            if mid and (mid not in latest or (rev or 0) >= (latest[mid]["revision"] or 0)):
                latest[mid] = {"revision": rev, "state": str(c.get("state") or "").lower(),
                               "changed_at": c.get("changed_at")}
        nxt = _int(got.get("next_since"))
        last = max([since] + [_int(c.get("seq")) or 0 for c in changes])
        nxt = max(last, nxt if nxt is not None else last)
        if not changes or nxt <= since:
            break
        since = nxt
    have = {r["key"].split(":", 1)[1]: _int(r["revision"]) for r in db.rows(
        "SELECT source_key AS key, meta->'meeting'->>'revision' AS revision FROM synapse.item WHERE dataset_id = %s "
        "AND source = %s AND deleted_at IS NULL AND strpos(source_key, '#gone-') = 0", (str(ds["id"]), SOURCE))}
    differ, gone, missing = [], [], []
    for mid, m in latest.items():
        if m["state"] == "withdrawn":
            if mid in have:
                gone.append(mid)
        elif m["state"] == "ready" and have.get(mid) != m["revision"]:
            differ.append(mid)
    if latest:
        missing = [mid for mid in have if mid not in latest]
    held_back = ""
    if missing and len(missing) > max(3, len(have) // 5):
        # So many held here and named nowhere there is more likely a key that sees less than a library that
        # lost them: nothing is fetched to be deleted on that, and the lab says so.
        held_back = (f"{len(missing)} meetings kept here are not in the library's changes; that is too many to be "
                     "real, so none was queued (is the key one that sees every meeting?)")
        missing = []
    for mid in differ + gone:
        hear(str(ds["id"]), mid, latest[mid]["revision"], latest[mid]["state"], by=f"check ({by})",
             changed_at=latest[mid]["changed_at"])
    for mid in missing:
        # Held here and named nowhere in the library's changes: fetched, and the library's answer decides.
        hear(str(ds["id"]), mid, None, "missing", by=f"check ({by})")
    out = {"by": by, "at": _now().isoformat(), "library": len(latest), "synapse": len(have),
           "behind": len(differ), "withdrawn_still_here": len(gone), "missing_from_library": len(missing),
           "in_sync": sum(1 for mid, m in latest.items() if m["state"] == "ready" and have.get(mid) == m["revision"]),
           **({"held_back": held_back} if held_back else {})}
    _set(ds["id"], last_check_at=_now(), check_result=out)
    _said(ds["id"], f"Checked every meeting ({by}): {out['in_sync']} in step, {len(differ)} behind, {len(gone)} "
                    f"withdrawn still here, {len(missing)} not in the library's changes; those are queued.",
          kind="check", by=by)
    return out


# ---------------------------------------------------------------------------------------------
# one meeting, as the library has it
# ---------------------------------------------------------------------------------------------

def _name_of(v) -> str:
    if isinstance(v, dict):
        return " ".join(str(v.get("name") or v.get("label") or v.get("email") or "").split())
    return " ".join(str(v or "").split())


def _email_of(v) -> str:
    if isinstance(v, dict):
        person = v.get("person") if isinstance(v.get("person"), dict) else {}
        v = v.get("email") or person.get("email") or ""
    v = str(v or "").strip().lower()
    return v if "@" in v else ""


def _flag(p: dict, yes: tuple, no: tuple, field: str, default: bool) -> bool:
    if isinstance(p.get(field), bool):
        return p[field]
    for k in yes:
        if isinstance(p.get(k), bool):
            return p[k]
    for k in no:
        if isinstance(p.get(k), bool):
            return not p[k]
    return default


def _participants(raw) -> list[dict]:
    out = []
    for p in raw or []:
        if isinstance(p, str):
            p = {"name": p}
        if not isinstance(p, dict):
            continue
        role = str(p.get("attended") or p.get("role") or p.get("attendance") or "").lower().replace("_", " ")
        took = _flag(p, ("attended", "present"), ("invited_only",), "took_part",
                     not role or role in ("took part", "attended", "present", "speaker"))
        if role in ("invited", "invited only", "absent", "did not attend"):
            took = False
        kind = str(p.get("side") or p.get("kind") or "").lower()
        outside = _flag(p, ("external", "is_outside"), ("internal", "is_internal"), "outside", kind == "outside")
        name = _name_of(p) or _email_of(p)
        if not name:
            continue
        out.append({"name": name, "email": _email_of(p), "outside": bool(outside), "took_part": bool(took)})
    return out


def _readers(m: dict) -> tuple[list[str], bool]:
    raw = m.get("readers")
    admins = False
    emails: list = []
    if isinstance(raw, dict):
        emails = raw.get("emails") or raw.get("people") or raw.get("readers") or []
        admins = bool(raw.get("admins") or raw.get("administrators") or raw.get("admins_can_read")
                      or raw.get("administrators_can_see"))
    elif isinstance(raw, list):
        emails = raw
    for k in ("readers_admins", "admins_can_read", "administrators_can_see", "admins_can_see"):
        if isinstance(m.get(k), bool):
            admins = admins or m[k]
    out = sorted({e for e in (_email_of(x) for x in emails) if e})
    return out, admins


def _speakers(raw) -> dict:
    """label -> {name, email, confirmed}; a label the library has no confirmed person for is not confirmed."""
    out: dict = {}
    items = list(raw.items()) if isinstance(raw, dict) else [
        (str(s.get("label") or s.get("speaker") or ""), s) for s in raw or [] if isinstance(s, dict)]
    for label, v in items:
        label = str(label or "").strip()
        if not label:
            continue
        if v is None or v == "" or v is False:
            out[label] = {"name": "", "email": "", "confirmed": False}
            continue
        if isinstance(v, str):
            out[label] = {"name": " ".join(v.split()), "email": _email_of(v), "confirmed": True}
            continue
        person = v.get("person") if isinstance(v.get("person"), dict) else v
        name = _name_of(person) if person is not v else " ".join(str(v.get("name") or v.get("person") or "").split())
        if isinstance(v.get("person"), str):
            name = " ".join(v["person"].split())
        confirmed = v.get("confirmed")
        confirmed = bool(confirmed) if isinstance(confirmed, bool) else bool(name or _email_of(person))
        if name == label and not _email_of(person) and not isinstance(v.get("confirmed"), bool):
            confirmed = False
        out[label] = {"name": name, "email": _email_of(person), "confirmed": confirmed}
    return out


def _lines(raw) -> list[str]:
    """Decisions or action items as the library wrote them, one line each."""
    out = []
    for d in raw or []:
        if isinstance(d, str):
            text = " ".join(d.split())
        elif isinstance(d, dict):
            text = " ".join(str(d.get("text") or d.get("title") or d.get("what") or d.get("decision") or "").split())
            who = d.get("owner") or d.get("owner_name") or d.get("who") or d.get("assignee")
            who = _name_of(who) if who else ""
            if who and d.get("by_outside"):
                who += " (outside)"
            due = str(d.get("due") or d.get("due_date") or d.get("due_on") or "").strip()
            # Said only when it is news: an open action item and a decision that stands are the usual.
            status = str(d.get("state") or d.get("status") or "").strip().replace("_", " ")
            status = "" if status in ("open", "standing") else status
            extra = ", ".join(x for x in (who, f"due {due}" if due else "", status) if x)
            text = f"{text} ({extra})" if text and extra else text
        else:
            continue
        if text:
            out.append(text)
    return out


def _summary(m: dict) -> str:
    """The library's short summary, and its long one after it when it says more."""
    summary = m.get("summary")
    if isinstance(summary, dict):
        short, long = summary.get("short") or summary.get("text") or "", summary.get("long") or ""
    else:
        short, long = summary or m.get("summary_short") or "", m.get("summary_long") or ""
    short, long = str(short).strip(), str(long).strip()
    return f"{short}\n\n{long}".strip() if long and long != short else short


def _segments(raw) -> list[dict]:
    out = []
    for i, s in enumerate(raw or []):
        if not isinstance(s, dict):
            continue
        text = " ".join(str(s.get("text") or "").split())
        if not text:
            continue
        out.append({"id": str(s.get("segment_id") or s.get("id") or f"n{i}"),
                    "speaker": str(s.get("speaker") or s.get("label") or "").strip() or "Speaker",
                    "start_ms": _int(s.get("start_ms")), "end_ms": _int(s.get("end_ms")), "text": text, "n": i})
    return out


def normalise(m: dict) -> dict:
    """What the library said about one meeting, in the shape this file keeps; nothing is made up."""
    cat = m.get("category")
    category = _name_of(cat) if isinstance(cat, dict) else " ".join(str(cat or "").split())
    lang = m.get("language") or m.get("languages") or ""
    lang = ", ".join(str(x) for x in lang) if isinstance(lang, list) else str(lang)
    readers, admins = _readers(m)
    link = m.get("meeting_link") or m.get("link") or m.get("meeting_url") or m.get("join_url") or ""
    if isinstance(link, dict):
        link = link.get("url") or link.get("href") or ""
    return {"id": str(m.get("id") or m.get("meeting_id") or "").strip(), "revision": _int(m.get("revision")),
            "state": str(m.get("state") or "ready").strip().lower(),
            "title": " ".join(str(m.get("title") or "").split()) or "A meeting with no title",
            "started_at": str(m.get("started_at") or ""), "ended_at": str(m.get("ended_at") or ""),
            "language": lang.strip(), "category": category,
            "calendar_event_id": str(m.get("calendar_event_id") or "").strip(), "link": str(link).strip(),
            "participants": _participants(m.get("participants")), "readers": readers, "admins_can_read": admins,
            "summary": _summary(m), "next_meeting": " ".join(str(m.get("next_meeting") or "").split()),
            "ical_uid": str(m.get("ical_uid") or "").strip(), "decisions": _lines(m.get("decisions")),
            "action_items": _lines(m.get("action_items")), "speakers": _speakers(m.get("speakers")),
            "segments": _segments(m.get("segments"))}


def _said_when(start: datetime | None, end: datetime | None) -> str:
    if start is None:
        return "no time given"
    from ... import clock

    zone = _zone()
    a = start.astimezone(zone)
    text = a.strftime("%A %d %B %Y, %H:%M")
    if end is not None and end > start:
        b = end.astimezone(zone)
        text += " to " + (b.strftime("%H:%M") if b.date() == a.date() else b.strftime("%A %d %B %Y, %H:%M"))
    return text + f" ({clock.place(zone)} time)"


def head_text(mm: dict) -> str:
    """The meeting item's own text: what is X-rayed, as the library has it."""
    start, end = _when(mm["started_at"]), _when(mm["ended_at"])
    who = lambda p: f"{p['name']} <{p['email']}>" if p["email"] and p["email"] != p["name"] else p["name"]  # noqa: E731
    took = [who(p) + (" (outside)" if p["outside"] else "") for p in mm["participants"] if p["took_part"]]
    invited = [who(p) + (" (outside)" if p["outside"] else "") for p in mm["participants"] if not p["took_part"]]
    lines = [f"Meeting: {mm['title']}", f"When: {_said_when(start, end)}"]
    if mm["category"]:
        lines.append(f"Category: {mm['category']}")
    if mm["language"]:
        lines.append(f"Language: {mm['language']}")
    if took:
        lines.append("Took part: " + "; ".join(took))
    if invited:
        lines.append("Invited, did not take part: " + "; ".join(invited))
    if mm["link"]:
        lines.append(f"Meeting link: {mm['link']}")
    if mm["summary"]:
        lines += ["", "Summary:", mm["summary"]]
    if mm.get("next_meeting"):
        lines.append(f"Next meeting: {mm['next_meeting']}")
    if mm["decisions"]:
        lines += ["", "Decisions:"] + [f"- {d}" for d in mm["decisions"]]
    if mm["action_items"]:
        lines += ["", "Action items:"] + [f"- {a}" for a in mm["action_items"]]
    return "\n".join(lines)


def sensitivity_of(category: str) -> tuple[str, str]:
    c = (category or "").lower()
    if re.search(r"health|medic|doctor|clinic|здрав|медиц|лекар|болни", c):
        return "special", f"the library's category is {category}: anything about health is special"
    if re.search(r"hir|recruit|interview|candidat|наем|подбор|интервю|кандидат", c):
        return "private", f"the library's category is {category}: hiring is private"
    return "normal", (f"the library's category is {category}" if category else "the library gave no category") + \
        ": normal unless the X-ray reads it higher"


def _clock(ms: int | None) -> str:
    if ms is None:
        return "?"
    s = max(0, int(ms) // 1000)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60:02d}:{s % 60:02d}"


def speaker_name(mm: dict, label: str) -> str:
    sp = mm["speakers"].get(label) or {}
    return sp.get("name") if sp.get("confirmed") and sp.get("name") else label


def transcript_passages(mm: dict) -> list[dict]:
    """The transcript as passages: whole speaker turns, a passage closed at a turn once it covers
    `WINDOW_MS`, a long turn cut at a segment once it does. The cuts follow the clock alone (and a
    passage's words only past `MOST_WORDS`), so a corrected word or a renamed speaker moves no cut and
    changes only the passages it is in."""
    segs = sorted(mm["segments"], key=lambda s: (s["start_ms"] if s["start_ms"] is not None else -1, s["n"]))
    out: list[dict] = []
    now: list[dict] = []

    def close():
        if not now:
            return
        turns: list[list[dict]] = []
        for s in now:
            if turns and turns[-1][-1]["speaker"] == s["speaker"]:
                turns[-1].append(s)
            else:
                turns.append([s])
        text = "\n".join(f"[{_clock(t[0]['start_ms'])}] {speaker_name(mm, t[0]['speaker'])}: "
                         + " ".join(s["text"] for s in t) for t in turns)
        starts = [s["start_ms"] for s in now if s["start_ms"] is not None]
        ends = [s["end_ms"] for s in now if s["end_ms"] is not None]
        out.append({"text": text, "segments": [s["id"] for s in now],
                    "start_ms": min(starts) if starts else None, "end_ms": max(ends) if ends else None,
                    "speakers": list(dict.fromkeys(s["speaker"] for s in now))})
        now.clear()

    words = 0
    for s in segs:
        if now:
            began = now[0]["start_ms"]
            turn_starts = s["speaker"] != now[-1]["speaker"]
            over_time = began is not None and s["start_ms"] is not None and s["start_ms"] - began >= WINDOW_MS
            if (over_time and (turn_starts or s["start_ms"] - began >= WINDOW_MS)) or words >= MOST_WORDS:
                close()
                words = 0
        now.append(s)
        words += len(s["text"].split())
    close()
    return out


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_transcript(ds: dict, item_id: str, mm: dict) -> dict:
    """The transcript's passages, by their hash: kept as they are when their words are the same (their
    vectors kept), written new when they changed, deleted when they are gone. Never their words in the
    record, which a deletion would have to find again."""
    from .. import text as tx

    new = transcript_passages(mm)
    names = " ".join(dict.fromkeys(speaker_name(mm, label) for label in mm["speakers"]))
    extra = " ".join(x for x in (tx.other_alphabet(names), tx.other_alphabet(mm["title"])) if x)
    old = db.rows("SELECT id, seq, sha256 FROM synapse.passage WHERE dataset_id = %s AND item_id = %s AND part = %s "
                  "ORDER BY seq", (str(ds["id"]), item_id, PART))
    by_sha: dict[str, list[dict]] = {}
    for r in old:
        by_sha.setdefault(r["sha256"], []).append(r)
    keep, add = [], []
    for n, p in enumerate(new, start=1):
        sha = _sha(p["text"])
        if by_sha.get(sha):
            keep.append((by_sha[sha].pop(0)["id"], n, p, sha))
        else:
            add.append((n, p, sha))
    gone = [r["id"] for rows in by_sha.values() for r in rows]
    meta = lambda p: {"segments": p["segments"], "start_ms": p["start_ms"], "end_ms": p["end_ms"],  # noqa: E731
                      "speakers": p["speakers"]}
    with db.atomic():
        if gone:
            db.run("DELETE FROM synapse.passage WHERE id = ANY(%s)", (gone,))
        if keep:
            # Out of the way first, so a kept passage's new number never meets another's old one.
            db.run("UPDATE synapse.passage SET seq = seq + 1000000 WHERE id = ANY(%s)", ([k[0] for k in keep],))
        if add:
            db.run("INSERT INTO synapse.passage (dataset_id, item_id, part, seq, text, sha256, meta, words) "
                   "SELECT %s, %s, %s, n, t, h, m::jsonb, to_tsvector('english', t) || to_tsvector('synapse.bg', t) || "
                   "to_tsvector('simple', t || ' ' || %s) FROM unnest(%s::int[], %s::text[], %s::text[], %s::text[]) "
                   "AS x(n, t, h, m)",
                   (str(ds["id"]), item_id, PART, extra, [a[0] for a in add], [a[1]["text"] for a in add],
                    [a[2] for a in add], [json.dumps(meta(a[1])) for a in add]))
        for pid, n, p, _sha_ in keep:
            db.run("UPDATE synapse.passage SET seq = %s, meta = %s::jsonb WHERE id = %s", (n, Json(meta(p)), pid))
    return {"passages": len(new), "kept": len(keep), "new": len(add), "deleted": len(gone),
            "segments": len(mm["segments"]),
            "changed_passages": [{"seq": a[0], "segments": a[1]["segments"][:6],
                                  "from": _clock(a[1]["start_ms"]), "to": _clock(a[1]["end_ms"])} for a in add][:40]}


# ---------------------------------------------------------------------------------------------
# readers and links
# ---------------------------------------------------------------------------------------------

def reader_ids(ds: dict, mm: dict) -> list[str]:
    """The owner, always; and each address among the meeting's readers, as Master's person for it. The library's
    administrators are not carried over: nobody reads a meeting here for being an administrator there."""
    from .. import datasets, people

    out = [datasets.me(ds)]
    named = {p["email"]: p["name"] for p in mm["participants"] if p["email"] and p["name"] != p["email"]}
    named.update({sp["email"]: sp["name"] for sp in mm["speakers"].values() if sp["email"] and sp["name"]
                  and sp["confirmed"]})
    for e in mm["readers"]:
        # With its name when the meeting says it, so a reader met here first is a person with a name; made
        # readable by the owner alone until `people_readers` works out who else may (the meetings' own readers).
        person = people.resolve(ds, f"{named[e]} <{e}>" if named.get(e) else e, readers=[out[0]],
                                made_by=MADE_BY)[0]
        if person and str(person["id"]) not in out:
            out.append(str(person["id"]))
    return out


#: What the people this sync meets first say made them (`people.create`'s made_by).
MADE_BY = "meeting library"


def _met(ds: dict, item_id: str) -> set[str]:
    """The people a meeting names: those it links to and its readers."""
    return {str(r["id"]) for r in db.rows(
        "SELECT dst AS id FROM synapse.link WHERE dataset_id = %s AND src = %s AND type = ANY(%s) "
        "UNION SELECT principal::uuid FROM synapse.reader WHERE dataset_id = %s AND item_id = %s AND principal ~ "
        "'^[0-9a-f-]{36}$'", (str(ds["id"]), item_id, list(MEETING_LINKS), str(ds["id"]), item_id))}


def people_readers(ds: dict, pids) -> list[str]:
    """Who may read a person this sync made: the owner, and the readers of every meeting kept here that still names
    them. A meeting's people are words of the meeting, so nobody who may not read one of those meetings finds
    them, and when a meeting's readers change or it is withdrawn, its people change with it. A person met
    anywhere else first is not touched."""
    from .. import datasets, ingest, people

    me = datasets.me(ds)
    changed = []
    for pid in sorted({str(p) for p in pids if p}):
        person = db.row("SELECT id, title, meta FROM synapse.item WHERE dataset_id = %s AND id = %s AND kind = 'person' "
                        "AND deleted_at IS NULL", (people.home_id(ds), pid))
        if not person or (person.get("meta") or {}).get("made_by") != MADE_BY:
            continue
        want = {me} | {r["principal"] for r in db.rows(
            "SELECT DISTINCT r.principal FROM synapse.item i JOIN synapse.reader r ON r.dataset_id = i.dataset_id AND "
            "r.item_id = i.id WHERE i.dataset_id = %s AND i.source = %s AND i.deleted_at IS NULL AND (EXISTS ("
            "SELECT 1 FROM synapse.link l WHERE l.dataset_id = i.dataset_id AND l.src = i.id AND l.dst = %s) OR "
            "EXISTS (SELECT 1 FROM synapse.reader x WHERE x.dataset_id = i.dataset_id AND x.item_id = i.id AND "
            "x.principal = %s))", (str(ds["id"]), SOURCE, pid, pid))}
        if want != set(ingest.readers_of(people.home_id(ds), pid)):
            ingest.set_readers(people.home_id(ds), pid, sorted(want))
            changed.append(person["title"])
    return changed


def _event_for(ds: dict, mm: dict) -> tuple[dict | None, str]:
    ds_id = str(ds["id"])
    eid = mm.get("calendar_event_id") or ""
    if eid:
        got = db.row("SELECT * FROM synapse.item WHERE dataset_id = %s AND kind = 'event' AND source = 'gcal' AND "
                     "deleted_at IS NULL AND meta->'gcal'->>'event_id' = %s ORDER BY stored_at LIMIT 1", (ds_id, eid))
        if got:
            return got, f"the calendar event {eid}, by its id"
    uid = mm.get("ical_uid") or ""
    if uid:
        got = db.row("SELECT * FROM synapse.item WHERE dataset_id = %s AND kind = 'event' AND source = 'gcal' AND "
                     "deleted_at IS NULL AND meta->'gcal'->>'ical_uid' = %s ORDER BY stored_at LIMIT 1", (ds_id, uid))
        if got:
            return got, "the calendar event with its iCalendar UID"
    start = _when(mm.get("started_at"))
    link = (mm.get("link") or "").strip()
    if link and start is not None:
        code = re.sub(r"^https?://", "", link).split("?")[0].rstrip("/")
        got = db.row("SELECT * FROM synapse.item WHERE dataset_id = %s AND kind = 'event' AND source = 'gcal' AND "
                     "deleted_at IS NULL AND said_at BETWEEN %s AND %s AND (meta->'gcal'->>'meet' ILIKE %s OR raw "
                     "ILIKE %s) ORDER BY abs(extract(epoch FROM said_at - %s)) LIMIT 1",
                     (ds_id, start - timedelta(hours=2), start + timedelta(hours=2), f"%{code}%", f"%{code}%", start))
        if got:
            return got, f"the calendar event with the meeting link {code} near its start"
    return None, ""


def _speaker_person(ds: dict, sp: dict, item: dict) -> dict | None:
    from .. import ingest, people

    if sp.get("email"):
        return ingest.person_for(ds, f"{sp['name']} <{sp['email']}>" if sp.get("name") else sp["email"], item,
                                 readers=[item["owner"]], made_by=MADE_BY)[0]
    if sp.get("name"):
        pid = people.reader_id(ds, sp["name"], create_new=False)
        if pid and pid != people.EVERYONE:
            return people.get(people.home_id(ds), pid)
    return None


def links_for(ds: dict, item: dict) -> list[tuple[dict, str, str]]:
    """(the item linked to, the link's type, why) for a meeting, from what the library said (`ingest.code_links`)."""
    from .. import ingest

    mm = (item.get("meta") or {}).get("meeting") or {}
    out: list = []
    event, how = _event_for(ds, mm)
    if event:
        out.append((event, "recorded", f"the meeting recorded {how}"))
    for p in mm.get("participants") or []:
        if not p.get("email"):
            continue
        person = ingest.person_for(ds, f"{p['name']} <{p['email']}>" if p["name"] != p["email"] else p["email"],
                                   item, readers=[item["owner"]], made_by=MADE_BY)[0]
        if person:
            out.append((person, "attended" if p.get("took_part") else "invited",
                        "took part, by the library" if p.get("took_part") else "invited, by the library"))
    for label, sp in sorted((mm.get("speakers") or {}).items()):
        if not sp.get("confirmed"):
            continue
        person = _speaker_person(ds, sp, item)
        if person:
            out.append((person, "spoke", f"speaker {label}, confirmed in the library as {sp.get('name') or sp.get('email')}"))
    return out


MEETING_LINKS = ("recorded", "attended", "invited", "spoke")


def relink(ds: dict, item_id: str) -> dict:
    """A meeting's own links made again from what the library says now: a renamed speaker's old link goes
    and the new one comes. Only these four types; every other link is left as it is."""
    from .. import datasets, ingest, people

    s = datasets.settings(ds)
    item = ingest.get_item(str(ds["id"]), item_id)
    before = {(r["type"], str(r["dst"])) for r in db.rows(
        "SELECT type, dst FROM synapse.link WHERE dataset_id = %s AND src = %s AND type = ANY(%s)",
        (str(ds["id"]), item_id, list(MEETING_LINKS)))}
    want = {}
    for dst, t, why in links_for(ds, item):
        want[(t, str(dst["id"]))] = (dst, why)
    for t, dst in before - set(want):
        db.run("DELETE FROM synapse.link WHERE dataset_id = %s AND src = %s AND dst = %s AND type = %s",
               (str(ds["id"]), item_id, dst, t))
    for (t, dst_id), (dst, why) in want.items():
        ingest.add_link(str(ds["id"]), item_id, dst_id, t, s.code_strength(t), origin="code", made_by="code", why=why)
    touched = {d for _t, d in before ^ set(want)}
    if touched:
        people.linked(ds, [d for d in touched if d])
    names = people.names([d for _t, d in set(want) | before])
    return {"links": [{"type": t, "to": names.get(d, d)} for t, d in sorted(want)],
            "added": [f"{t} {names.get(d, d)}" for t, d in sorted(set(want) - before)],
            "removed": [f"{t} {names.get(d, d)}" for t, d in sorted(before - set(want))]}


def derived_readers(ds: dict, item_id: str, removed: set[str]) -> dict:
    """After a meeting's readers changed: its passages follow by themselves (`can_read`, migration 0071),
    the topics it named lose whoever lost the meeting, and the layers built from it are made again,
    which works their readers out again (D55)."""
    from .. import datasets, ingest, layers, mapping

    out = {"passages": db.value("SELECT count(*) FROM synapse.passage WHERE dataset_id = %s AND item_id = %s",
                                (str(ds["id"]), item_id)),
           "passages_not_following": db.value(
               "SELECT count(*) FROM synapse.passage p JOIN synapse.item i ON i.dataset_id = p.dataset_id AND i.id = "
               "p.item_id WHERE p.dataset_id = %s AND p.item_id = %s AND p.can_read IS DISTINCT FROM i.can_read",
               (str(ds["id"]), item_id))}
    topics = []
    if removed:
        for t in db.rows("SELECT DISTINCT t.id, t.title FROM synapse.link l JOIN synapse.item t ON t.dataset_id = "
                         "l.dataset_id AND t.id = l.dst WHERE l.dataset_id = %s AND l.src = %s AND l.type = 'about' "
                         "AND t.kind = 'topic' AND t.deleted_at IS NULL", (str(ds["id"]), item_id)):
            had = set(ingest.readers_of(str(ds["id"]), t["id"]))
            left = sorted(had - removed) or [datasets.me(ds)]
            if set(left) != had:
                ingest.set_readers(str(ds["id"]), t["id"], left)
                topics.append(t["title"])
    out["topics"] = topics
    jobs = []
    for r in db.rows("SELECT DISTINCT l.src AS id FROM synapse.link l JOIN synapse.item i ON i.dataset_id = l.dataset_id "
                     "AND i.id = l.src WHERE l.dataset_id = %s AND l.dst = %s AND l.type = 'built_from' "
                     "AND i.deleted_at IS NULL", (str(ds["id"]), item_id)):
        jobs.append(layers.queue_rebuild(ds, r["id"], "the readers of a meeting it was built from changed"))
    out["layers"] = len(jobs)
    with contextlib.suppress(Exception):
        out["map"] = mapping.queue(ds, datasets.settings(ds), force=True)
    return out


# ---------------------------------------------------------------------------------------------
# storing, updating and withdrawing one meeting
# ---------------------------------------------------------------------------------------------

def _meta_of(mm: dict, cfg: dict) -> dict:
    keep = {k: v for k, v in mm.items() if k not in ("segments",)}
    keep["page"] = f"{cfg['url']}/meetings/{quote(mm['id'], safe='')}" if cfg.get("url") else ""
    keep["head_sha"] = _sha(head_text(mm))
    keep["segments"] = len(mm["segments"])
    # Stored last, once the whole update is in: an update cut off half way is read again.
    keep["revision"] = None
    return keep


def _payload(ds: dict, mm: dict, cfg: dict) -> tuple[dict, str]:
    sens, sens_why = sensitivity_of(mm["category"])
    start, end = _when(mm["started_at"]), _when(mm["ended_at"])
    out = {"kind": "meeting", "title": mm["title"][:300], "text": head_text(mm), "source": SOURCE,
           "source_key": key_of(mm["id"]), "said_at": start.isoformat() if start else None,
           "meeting": _meta_of(mm, cfg), "readers": reader_ids(ds, mm), "sensitivity": sens,
           "attendees": [p["email"] for p in mm["participants"] if p["took_part"] and p["email"]]}
    if start:
        out["start"] = start.isoformat()
    if end:
        out["end"] = end.isoformat()
    return out, sens_why


def _finish_meta(ds: dict, item_id: str, mm: dict) -> None:
    db.run("UPDATE synapse.item SET meta = jsonb_set(meta, '{meeting,revision}', to_jsonb(%s::int)) || "
           "jsonb_build_object('meeting_synced_at', now()) WHERE dataset_id = %s AND id = %s",
           (mm["revision"] or 0, str(ds["id"]), item_id))


def _step_meeting(st, mm: dict, readers: list[str], sens: str, sens_why: str, cfg: dict) -> None:
    from .. import people

    st.data.update({"meeting": mm["id"], "revision": mm["revision"], "state": mm["state"], "library": where(cfg),
                    "title": mm["title"], "started_at": mm["started_at"], "category": mm["category"],
                    "participants": [{k: p[k] for k in ("name", "email", "outside", "took_part")}
                                     for p in mm["participants"]],
                    "readers": [people.name_of(r) for r in readers], "reader_addresses": mm["readers"],
                    "library_admins_can_read": mm["admins_can_read"],
                    "sensitivity": sens, "sensitivity_why": sens_why,
                    "speakers": {k: v for k, v in mm["speakers"].items()},
                    "note": "Taken as the library has it: the summary, decisions and action items are the library's "
                            "own and are never extracted again. Readers are the owner of Master and the addresses the library "
                            "lists; the library's administrators are not readers here."})


def store_new(ds: dict, mm: dict, *, lane: str, cfg: dict) -> dict:
    from .. import ingest
    from ..trace import Trace

    payload, sens_why = _payload(ds, mm, cfg)
    got = ingest.store(ds, payload, by="meeting library", lane=lane, hold=True)
    if not got.get("ok"):
        raise RuntimeError(got.get("why") or "it could not be stored")
    item_id = str(got["item"])
    trace = Trace(str(ds["id"]), "store", "", trace_id=got["trace"])
    try:
        with trace.step("meeting", "The meeting, as the library has it") as st:
            _step_meeting(st, mm, payload["readers"], payload["sensitivity"], sens_why, cfg)
        with trace.step("transcript", "The transcript as passages, by speaker turn and time; embedded, never "
                                      "X-rayed one by one") as st:
            changed = write_transcript(ds, item_id, mm)
            st.data.update(changed)
        with trace.step("people", "The people it names, readable only by readers of the meetings naming them") as st:
            st.data["readers_set_for"] = people_readers(ds, _met(ds, item_id))
        _finish_meta(ds, item_id, mm)
        trace.set_title(f"Meeting {mm['id']}, revision {mm['revision']}: {mm['title']} "
                        f"({changed['new']} transcript passages)")
    finally:
        db.run("UPDATE synapse.trace SET status = 'queued' WHERE id = %s", (trace.id,))
        ingest.release(got.get("job"))
    _count(ds["id"], "stored")
    _said(ds["id"], f"Meeting {mm['id']}: revision {mm['revision']} stored, {changed['passages']} transcript passages.",
          meeting=mm["id"], revision=mm["revision"], kind="stored", trace=str(trace.id))
    return {"stored": item_id, "trace": str(trace.id), **{k: changed[k] for k in ("passages", "new")}}


def update(ds: dict, have: dict, mm: dict, *, cfg: dict) -> dict:
    """A meeting Synapse holds, made what the library has now. The X-ray again only when its own text changed;
    the transcript's passages by their hash; readers, sensitivity and links as the library says."""
    from .. import datasets, ingest
    from ..trace import Trace

    item_id = have["id"]
    item = ingest.get_item(str(ds["id"]), item_id)
    old = (item.get("meta") or {}).get("meeting") or {}
    payload, sens_why = _payload(ds, mm, cfg)
    readers_before = set(ingest.readers_of(str(ds["id"]), item_id))
    readers_now = set(payload["readers"])
    met_before = _met(ds, item_id)
    head_changed = (payload["text"] != item["raw"] or payload["title"] != item["title"]
                    or _when(payload["said_at"]) != _when(item.get("said_at")))
    sens_changed = (old.get("category") or "") != mm["category"]
    job = None
    if head_changed:
        changes = {k: payload[k] for k in ("text", "title", "said_at", "meeting", "start", "end", "attendees")
                   if k in payload}
        changes["readers"] = payload["readers"]
        if sens_changed:
            # Only a new category gives a new level: a level the X-ray raised it to is not taken back.
            changes["sensitivity"] = payload["sensitivity"]
        got = ingest.edit(ds, item_id, changes, by="meeting library", hold=True)
        if not got.get("ok"):
            raise RuntimeError(got.get("why") or "it could not be edited")
        trace = Trace(str(ds["id"]), "edit", "", trace_id=got["trace"])
        job = got.get("job")
    else:
        trace = Trace(str(ds["id"]), "edit", f"Meeting {mm['id']}", by="meeting library", item_id=item_id)
    try:
        with trace.step("meeting", "The meeting, as the library has it now" + (
                "; its own text changed, so its X-ray is made again" if head_changed else
                "; its own text is the same, so its X-ray is kept")) as st:
            _step_meeting(st, mm, payload["readers"], payload["sensitivity"], sens_why, cfg)
            st.data.update({"revision_before": old.get("revision"), "text_changed": head_changed,
                            "readers_changed": readers_before != readers_now,
                            "sensitivity_given": payload["sensitivity"] if (sens_changed or head_changed) else None})
            if not head_changed:
                # One update: the meta, the readers and the level together, so every passage follows at once.
                with db.atomic():
                    meta = dict(item.get("meta") or {})
                    meta["meeting"] = payload["meeting"]
                    meta["attendees"] = payload["attendees"]
                    db.run("UPDATE synapse.item SET meta = %s::jsonb, updated_at = now() WHERE id = %s",
                           (Json(meta), item_id))
                    if readers_before != readers_now:
                        ingest.set_readers(str(ds["id"]), item_id, payload["readers"])
                    if sens_changed:
                        why = dict(item.get("sensitivity_why") or {})
                        why.update({"given": payload["sensitivity"], "code": sens_why})
                        db.run("UPDATE synapse.item SET sensitivity = %s, sensitivity_why = %s::jsonb WHERE id = %s",
                               (payload["sensitivity"], Json(why), item_id))
        with trace.step("transcript", "The transcript's passages, by their hash: only changed ones written and "
                                      "embedded again") as st:
            changed = write_transcript(ds, item_id, mm)
            st.data.update(changed)
        with trace.step("meeting_links", "Its calendar event, who took part, and its confirmed speakers") as st:
            st.data.update(relink(ds, item_id))
            st.data["people_readers_set_for"] = people_readers(ds, met_before | _met(ds, item_id))
        if readers_before != readers_now or sens_changed:
            with trace.step("meeting_readers", "Readers changed: the item, every passage and what was made from it") as st:
                st.data.update({"added": len(readers_now - readers_before), "removed": len(readers_before - readers_now),
                                **derived_readers(ds, item_id, readers_before - readers_now)})
        if not head_changed and changed["new"]:
            with trace.step("embedding", "The new and changed passages embedded; the rest keep their vectors") as st:
                st.data.update(ingest.embed_item(ds, item_id, datasets.settings(ds), trace, datasets.owner_of(ds)))
        _finish_meta(ds, item_id, mm)
        title = (f"Meeting {mm['id']}, revision {mm['revision']}: {mm['title']} ({changed['new']} passages changed"
                 + (", X-ray again" if head_changed else "") + ")")
        trace.set_title(title)
    finally:
        if job:
            db.run("UPDATE synapse.trace SET status = 'queued' WHERE id = %s", (trace.id,))
            ingest.release(job)
    if not job:
        trace.finish("done", meeting=mm["id"], revision=mm["revision"], passages_changed=changed["new"],
                     passages_deleted=changed["deleted"])
    _count(ds["id"], "updated")
    _said(ds["id"], f"Meeting {mm['id']}: revision {mm['revision']} in, {changed['new']} passages changed, "
                    f"{changed['deleted']} gone" + (", X-ray again" if head_changed else "") +
                    (", readers changed" if readers_before != readers_now else "") + ".",
          meeting=mm["id"], revision=mm["revision"], kind="updated", trace=str(trace.id))
    return {"updated": item_id, "trace": str(trace.id), "xray_again": head_changed, **{
        k: changed[k] for k in ("passages", "new", "deleted", "kept")}}


def withdraw(ds: dict, have: dict, meeting_id: str, revision: int | None) -> dict:
    """Withdrawn in the library: deleted here with everything made from it (`ingest.delete`). Its key is freed,
    so a meeting the library brings back is stored again."""
    from .. import ingest
    from ..trace import Trace

    met = _met(ds, have["id"])
    got = ingest.delete(ds, have["id"], by="meeting library")
    # Its people: readable now only by readers of the meetings that still name them.
    people_now = people_readers(ds, met)
    db.run("UPDATE synapse.item SET source_key = source_key || '#gone-' || floor(extract(epoch FROM now())) "
           "WHERE dataset_id = %s AND id = %s", (str(ds["id"]), have["id"]))
    if got.get("trace"):
        trace = Trace(str(ds["id"]), "delete", "", trace_id=got["trace"])
        with trace.step("meeting", "Withdrawn in the library") as st:
            st.data.update({"meeting": meeting_id, "revision": revision, "people_readers_set_for": people_now,
                            "note": "Deleted the way Synapse deletes: the item, its transcript passages, X-ray, "
                                    "links, layers, indexes and logged prompts. Its key is freed."})
        trace.set_title(f"Meeting {meeting_id}, revision {revision}: withdrawn, deleted")
        trace.finish("done")
    _count(ds["id"], "withdrawn")
    _said(ds["id"], f"Meeting {meeting_id}: withdrawn in the library (revision {revision}), deleted here with "
                    "everything made from it.", meeting=meeting_id, revision=revision, kind="withdrawn",
          trace=str(got.get("trace") or ""))
    return {"withdrawn": have["id"], "trace": got.get("trace")}


def process_one(ds: dict, q: dict) -> dict:
    """One queued meeting: fetched, guarded by its revision, and stored, updated or deleted."""
    cfg = settings()
    mid = str(q["meeting_id"])
    try:
        raw = fetch(mid)
    except Gone:
        raw = {"id": mid, "state": "withdrawn", "revision": q.get("revision")}
    except NotFound:
        if q.get("state") not in ("withdrawn", "missing"):
            raise
        raw = {"id": mid, "state": "withdrawn", "revision": q.get("revision")}
    mm = normalise({**raw, "id": raw.get("id") or mid})
    mm["id"] = mid
    have = _stored(str(ds["id"]), mid)
    out: dict
    if have and have["kept_out"]:
        out = {"skipped": "kept out: deleted in Synapse by a person"}
    elif mm["revision"] is not None and have and have["revision"] is not None and mm["revision"] <= have["revision"]:
        _count(ds["id"], "old_ignored")
        out = {"skipped": f"revision {mm['revision']} is not newer than the {have['revision']} Synapse has"}
    elif mm["state"] == "withdrawn":
        out = withdraw(ds, have, mid, mm["revision"]) if have else {"skipped": "withdrawn, and never kept here"}
    elif mm["state"] != "ready":
        out = {"skipped": f"the library says it is {mm['state'] or 'not ready'}"}
    elif have is None:
        out = store_new(ds, mm, lane="backfill" if q.get("heard_by") == "backfill" else "live", cfg=cfg)
    else:
        out = update(ds, have, mm, cfg=cfg)
    # Done with what was heard up to this revision; a newer one heard meanwhile stays queued, with its own wait.
    left = db.value("DELETE FROM synapse.meeting_queue WHERE dataset_id = %s AND meeting_id = %s AND "
                    "(revision IS NULL OR %s::int IS NULL OR revision <= %s::int) RETURNING 1",
                    (str(ds["id"]), mid, mm["revision"], mm["revision"]))
    if not left:
        db.run("UPDATE synapse.meeting_queue SET due_at = greatest(due_at, now() + interval '1 minute'), "
               "tries = tries + 1, error = %s WHERE dataset_id = %s AND meeting_id = %s",
               (f"the library still gave revision {mm['revision']}", str(ds["id"]), mid))
    return out


def process_due(ds: dict, most: int = PER_BEAT) -> dict:
    done, failed = 0, 0
    for q in db.rows("SELECT * FROM synapse.meeting_queue WHERE dataset_id = %s AND due_at <= now() "
                     "ORDER BY due_at, meeting_id LIMIT %s", (str(ds["id"]), int(most))):
        try:
            process_one(ds, q)
            done += 1
        except NotSetUp:
            raise
        except Exception as exc:  # noqa: BLE001 - one meeting never stops the others; tried again later
            log.warning("Synapse meetings: meeting %s not read: %s", q["meeting_id"], exc)
            failed += 1
            tries = int(q.get("tries") or 0) + 1
            db.run("UPDATE synapse.meeting_queue SET tries = %s, error = %s, due_at = now() + make_interval(secs => %s) "
                   "WHERE dataset_id = %s AND meeting_id = %s",
                   (tries, f"{type(exc).__name__}: {exc}"[:500], min(3600, 60 * 2 ** min(tries, 6)),
                    str(ds["id"]), q["meeting_id"]))
            _said(ds["id"], f"Meeting {q['meeting_id']}: not read ({type(exc).__name__}: {str(exc)[:160]}); tried again "
                            "later.", meeting=q["meeting_id"], kind="failed")
    more = bool(db.value("SELECT 1 FROM synapse.meeting_queue WHERE dataset_id = %s AND due_at <= now() LIMIT 1",
                         (str(ds["id"]),)))
    return {"done": done, "failed": failed, "more": more}


# ---------------------------------------------------------------------------------------------
# the beat
# ---------------------------------------------------------------------------------------------

def beat_one(ds: dict, row: dict, *, force_poll: bool = False) -> dict:
    """One Master's turn: the backfill or a poll when due, the night's check, and the meetings due."""
    name = f"synapse.meetings:{ds['id']}"
    if not db.value("SELECT pg_try_advisory_lock(hashtext(%s))", (name,)):
        return {"busy": True}
    out: dict = {}
    try:
        cfg = settings()
        why = off_words(cfg)
        if why:
            if row.get("error") != why:
                _set(ds["id"], error=why)
            return {"off": why}
        try:
            if row.get("backfill_state") != "done":
                out["backfill"] = backfill(ds, row)
            elif force_poll or poll_due(row):
                out["poll"] = poll(ds, row)
            now_row = row_of(ds["id"]) or row
            if check_due(ds, now_row):
                out["check"] = check(ds)
            out["queue"] = process_due(ds)
            if out["queue"]:
                # A meeting takes its calendar event's silos, or the meetings' rule (`rouh/silos.py`).
                from ... import silos
                silos.fill(ds, ("meetings",))
        except Exception as exc:  # noqa: BLE001 - said in the lab, and tried again next beat
            log.warning("Synapse meetings: the library could not be read: %s", exc)
            db.run("UPDATE synapse.meeting_sync SET failures = failures + 1, error = %s, updated_at = now() "
                   "WHERE dataset_id = %s", (f"{type(exc).__name__}: {exc}"[:500], str(ds["id"])))
            out["error"] = str(exc)
        return out
    finally:
        db.run("SELECT pg_advisory_unlock(hashtext(%s))", (name,))


def beat() -> bool:
    """Every Master's turn; True when there is more due at once."""
    from .. import datasets

    more = False
    for row in ensure():
        ds = datasets.by_id(row["dataset_id"])
        if ds is None:
            continue
        got = beat_one(ds, row)
        more = more or bool((got.get("queue") or {}).get("more"))
    return more


def wake() -> None:
    _wake.set()


def _loop() -> None:
    from django.db import connection

    time.sleep(10)
    while True:
        more = False
        try:
            if db.ready():
                more = beat()
        except Exception:  # noqa: BLE001 - the loop never dies
            log.exception("the Synapse meeting sync stumbled")
        finally:
            connection.close()
        if not more:
            _wake.wait(BEAT_SECONDS)
            _wake.clear()


def start() -> None:
    """The beat, once per process, on a thread of its own (`worker.start` starts it)."""
    global _started
    with _start_lock:
        if _started or os.environ.get("SYNAPSE_MEETINGS_SYNC", "1") == "0":
            return
        _started = True
    threading.Thread(target=_loop, name="synapse-meetings", daemon=True).start()


# ---------------------------------------------------------------------------------------------
# health, for the lab and the command
# ---------------------------------------------------------------------------------------------

def health(ds_id: str) -> dict | None:
    """The sync's state for the lab's homepage and `manage.py synapse_meetings status`."""
    if not ready():
        return None
    row = row_of(ds_id)
    if row is None:
        return None
    cfg = settings()
    kept = db.row("SELECT count(*) AS meetings, count(*) FILTER (WHERE xray IS NOT NULL) AS read FROM synapse.item "
                  "WHERE dataset_id = %s AND source = %s AND deleted_at IS NULL", (str(ds_id), SOURCE)) or {}
    passages = db.row("SELECT count(*) AS n, count(vec) AS embedded FROM synapse.passage WHERE dataset_id = %s "
                      "AND part = %s", (str(ds_id), PART)) or {}
    queue = db.rows("SELECT q.meeting_id, q.revision, q.state, q.heard_by, q.due_at, q.tries, q.error, "
                    "(SELECT 1 FROM synapse.item i WHERE i.dataset_id = q.dataset_id AND i.source = %s AND "
                    " i.source_key = 'meeting:' || q.meeting_id AND i.deleted_at IS NULL) IS NOT NULL AS held "
                    "FROM synapse.meeting_queue q WHERE q.dataset_id = %s ORDER BY q.due_at LIMIT 200",
                    (SOURCE, str(ds_id)))
    cost = db.row("SELECT count(*) FILTER (WHERE kind = 'store') AS stores, coalesce(sum(cost_usd) FILTER (WHERE kind = "
                  "'store'), 0) AS store_cost, count(*) FILTER (WHERE kind = 'edit') AS edits, coalesce(sum(cost_usd) "
                  "FILTER (WHERE kind = 'edit'), 0) AS edit_cost FROM synapse.trace WHERE dataset_id = %s AND by = "
                  "'meeting library' AND status = 'done'", (str(ds_id),)) or {}
    behind = [q for q in queue if q["held"]]
    return {"on": not off_words(cfg), "why_off": off_words(cfg), "missing": cfg["missing"], "file": cfg["file"],
            "library": where(cfg), "webhook": "on" if cfg["secret"] else "off: no MEETING_LIBRARY_WEBHOOK_SECRET",
            "since_seq": row["since_seq"], "backfill_state": row["backfill_state"] or "not started",
            "backfill": row["backfill"], "backfill_done_at": row["backfill_done_at"],
            "last_poll_at": row["last_poll_at"], "last_poll_ok_at": row["last_poll_ok_at"],
            "last_event_at": row["last_event_at"], "last_check_at": row["last_check_at"],
            "check": row["check_result"], "error": row["error"], "counts": row["counts"], "recent": row["recent"],
            "meetings": kept.get("meetings") or 0, "read_by_model": kept.get("read") or 0,
            "passages": passages.get("n") or 0, "passages_embedded": passages.get("embedded") or 0,
            "queued": len(queue), "behind": len(behind), "new_waiting": len(queue) - len(behind),
            "in_sync": max(0, int(kept.get("meetings") or 0) - len(behind)),
            "failing": [{"meeting": q["meeting_id"], "error": q["error"]} for q in queue if q["error"]][:10],
            "next_due": queue[0]["due_at"] if queue else None,
            "cost": {"stores": cost.get("stores") or 0, "per_meeting": (float(cost.get("store_cost") or 0) /
                                                                        max(1, int(cost.get("stores") or 0))),
                     "stores_usd": float(cost.get("store_cost") or 0), "edits": cost.get("edits") or 0,
                     "edits_usd": float(cost.get("edit_cost") or 0)},
            "poll_seconds": POLL_SECONDS, "quiet_seconds": QUIET_SECONDS, "check_at": "%02d:%02d" % CHECK_AT}


# ---------------------------------------------------------------------------------------------
# Rouh's two read tools: meeting_search and meeting_read
# ---------------------------------------------------------------------------------------------

def _who():
    from ... import tenancy

    who = tenancy.speaker()
    if who is None:
        with contextlib.suppress(Exception):
            who = tenancy.Tenancy().only_person()
    return who


def _datasets_for(who) -> list[dict]:
    """The Masters keeping the library, in the asker's own organisation."""
    if who is None or not ready():
        return []
    return db.rows("SELECT d.* FROM synapse.meeting_sync s JOIN synapse.dataset d ON d.id = s.dataset_id WHERE "
                   "s.enabled AND d.org_id = %s ORDER BY s.added_at", (str(who.org_id),))


def principals_for(ds: dict, who) -> list[str]:
    """Whose questions these are, as Master's people: the owner reads every meeting; anyone else only those
    whose readers hold their own address. Never 'everyone', and nothing for anyone not known by address."""
    from .. import datasets, people

    if who is None or str(who.org_id) != str(ds["org_id"]):
        return []
    if str(who.user_id) == str(ds["user_id"]):
        return [datasets.me(ds)]
    emails = {people.norm_email(who.email)} if getattr(who, "email", "") else set()
    with contextlib.suppress(Exception):
        from ...models.accounts import User

        u = User.objects.filter(id=who.user_id).first()
        if u is not None and u.email:
            emails.add(people.norm_email(u.email))
    out = []
    for e in sorted(x for x in emails if x):
        pid = people.find(people.home_id(ds), "email", e)
        if pid and pid not in out:
            out.append(str(pid))
    return out


#: Words of a question as a tsquery any of whose words may match: English, Bulgarian word forms and as written.
TSQUERY = ("(SELECT CASE WHEN numnode(plainto_tsquery('english', %s) || plainto_tsquery('synapse.bg', %s) || "
           "plainto_tsquery('simple', %s)) > 0 THEN replace((plainto_tsquery('english', %s) || "
           "plainto_tsquery('synapse.bg', %s) || plainto_tsquery('simple', %s))::text, '&', '|')::tsquery END AS w)")


def _meeting_line(it: dict) -> str:
    mm = (it.get("meta") or {}).get("meeting") or {}
    when = _when(mm.get("started_at") or it.get("said_at"))
    took = [p["name"] for p in mm.get("participants") or [] if p.get("took_part")]
    return (f"Meeting {mm.get('id')}: {it['title']}, {when.astimezone(_zone()).strftime('%a %d %b %Y %H:%M') if when else 'no date'}"
            + (f", {mm['category']}" if mm.get("category") else "")
            + (f"; took part: {', '.join(took[:8])}" if took else "")
            + (f"; {len(mm.get('decisions') or [])} decisions, {len(mm.get('action_items') or [])} action items"))


def search_meetings(ds: dict, principals: list[str], query: str, *, since=None, until=None, person: str = "",
                    limit: int = 8) -> list[dict]:
    """Meetings the asker may read, best match first: by their words, Bulgarian word forms too, in the
    meeting's own text and its transcript; with no words, the newest."""
    if not principals:
        return []
    like = f"%{person.strip().lower()}%" if person and person.strip() else None
    since, until = _when(since), _when(until)
    cond = ("i.dataset_id = %s AND i.kind = 'meeting' AND i.source = %s AND i.deleted_at IS NULL "
            "AND i.can_read && %s::text[] AND (%s::timestamptz IS NULL OR i.said_at >= %s::timestamptz) "
            "AND (%s::timestamptz IS NULL OR i.said_at < %s::timestamptz) AND (%s::text IS NULL OR "
            "lower((i.meta->'meeting'->'participants')::text) LIKE %s OR lower((i.meta->'meeting'->'speakers')::text) "
            "LIKE %s)")
    cp = [str(ds["id"]), SOURCE, principals, since, since, until, until, like, like, like]
    if not (query or "").strip():
        return db.rows(f"SELECT i.id, i.title, i.said_at, i.meta, NULL::text AS best, 0 AS score FROM synapse.item i "
                       f"WHERE {cond} ORDER BY i.said_at DESC NULLS LAST LIMIT %s", cp + [int(limit)])
    return db.rows(
        f"WITH q AS {TSQUERY}, hits AS ("
        " SELECT p.item_id, p.part, p.seq, p.text, ts_rank_cd(p.words, q.w) AS r FROM synapse.passage p, q "
        " WHERE q.w IS NOT NULL AND p.dataset_id = %s AND p.kind = 'meeting' AND NOT p.from_xray "
        " AND p.can_read && %s::text[] AND p.words @@ q.w), "
        "best AS (SELECT DISTINCT ON (item_id) item_id, part, seq, text, r, sum(r) OVER (PARTITION BY item_id) AS "
        " total FROM hits ORDER BY item_id, r DESC) "
        f"SELECT i.id, i.title, i.said_at, i.meta, b.text AS best, b.part, b.seq, b.total AS score FROM best b JOIN "
        f"synapse.item i ON i.id = b.item_id WHERE {cond} ORDER BY b.total DESC, i.said_at DESC LIMIT %s",
        [query] * 6 + [str(ds["id"]), principals] + cp + [int(limit)])


def _find_meeting(ds: dict, principals: list[str], ref: str) -> dict | None:
    ref = (ref or "").strip()
    if not ref or not principals:
        return None
    mid = re.sub(r"(?i)^meeting[: ]*", "", ref).strip()
    got = db.row("SELECT * FROM synapse.item i WHERE i.dataset_id = %s AND i.kind = 'meeting' AND i.deleted_at IS NULL "
                 "AND i.can_read && %s::text[] AND (i.source_key = %s OR i.id::text = %s OR i.id::text LIKE %s) LIMIT 1",
                 (str(ds["id"]), principals, key_of(mid), ref, ref + "%"))
    if got:
        return got
    if re.fullmatch(r"(?i)(meeting[: ]*)?\d+", ref):
        # Asked for by its number: that meeting, or none the asker may read; never another found by its words.
        return None
    found = search_meetings(ds, principals, ref, limit=1)
    if not found:
        found = db.rows("SELECT i.id FROM synapse.item i WHERE i.dataset_id = %s AND i.kind = 'meeting' AND "
                        "i.deleted_at IS NULL AND i.can_read && %s::text[] AND similarity(i.title, %s) > 0.2 "
                        "ORDER BY similarity(i.title, %s) DESC LIMIT 1", (str(ds["id"]), principals, ref, ref))
    if not found:
        return None
    return db.row("SELECT * FROM synapse.item WHERE dataset_id = %s AND id = %s", (str(ds["id"]), found[0]["id"]))


NOBODY = ("There is no meeting you can read here: the meeting library is not kept in a Synapse Master of your "
          "organisation, or none of its meetings lists your address among its readers.")


def tool_search(args, emit=None) -> str:
    """`meeting_search`: meetings the person may read, by what was said, decided or who was there."""
    who = _who()
    lines = []
    for ds in _datasets_for(who):
        principals = principals_for(ds, who)
        rows = search_meetings(ds, principals, str((args or {}).get("query") or ""), since=(args or {}).get("since"),
                               until=(args or {}).get("until"), person=str((args or {}).get("person") or ""),
                               limit=max(1, min(20, int((args or {}).get("limit") or 8))))
        for r in rows:
            line = "- " + _meeting_line(r)
            if r.get("best"):
                where_ = "transcript" if r.get("part") == PART else "summary"
                line += f"\n  best match ({where_}): " + " ".join(str(r["best"]).split())[:400]
            lines.append(line)
    if not lines:
        if not any(principals_for(ds, who) for ds in _datasets_for(who)):
            return NOBODY
        return "No meeting you can read matches that."
    return ("Meetings from the meeting library (read one whole with meeting_read and its number):\n"
            + "\n".join(lines))


#: What one meeting_read hands back of a transcript, at most (characters); `from` reads on.
READ_CHARS = 14_000


def tool_read(args, emit=None) -> str:
    """`meeting_read`: one meeting's summary, decisions, action items and transcript, by its number or by words."""
    args = args or {}
    who = _who()
    ref = str(args.get("meeting") or args.get("query") or "").strip()
    if not ref:
        return "Say which meeting: its number, or words to find it by."
    for ds in _datasets_for(who):
        principals = principals_for(ds, who)
        it = _find_meeting(ds, principals, ref)
        if not it:
            continue
        mm = (it.get("meta") or {}).get("meeting") or {}
        out = [_meeting_line(it)]
        if mm.get("page"):
            out.append(f"In the library: {mm['page']}")
        out.append("")
        out.append(it.get("raw") or "")
        what = str(args.get("part") or "all").lower()
        if what in ("all", "transcript"):
            start = max(1, int(args.get("from") or 1))
            rows = db.rows("SELECT seq, text FROM synapse.passage WHERE dataset_id = %s AND item_id = %s AND part = %s "
                           "AND seq >= %s AND can_read && %s::text[] ORDER BY seq",
                           (str(ds["id"]), it["id"], PART, start, principals))
            total = db.value("SELECT count(*) FROM synapse.passage WHERE dataset_id = %s AND item_id = %s AND part = %s",
                             (str(ds["id"]), it["id"], PART))
            out += ["", f"Transcript (passages {start} to {total}):" if rows else "Transcript: none kept."]
            used = 0
            for r in rows:
                if used + len(r["text"]) > READ_CHARS and used:
                    out.append(f"[... {total - r['seq'] + 1} more passages: meeting_read with from {r['seq']}]")
                    break
                out.append(r["text"])
                used += len(r["text"])
        return "\n".join(out)
    if not any(principals_for(ds, who) for ds in _datasets_for(who)):
        return NOBODY
    return "No meeting you can read matches that."


def declare(registry) -> None:
    registry._own(
        "meeting_search",
        "Find meetings from the meeting library that the person may read: by what was said in "
        "them (the transcript, Bulgarian or English), what was decided or agreed, their title, or who was there. "
        "Gives each meeting's number, title, date, who took part, and the best matching passage. With no query, "
        "the newest. Read only: nothing here changes a meeting or sends a recap.",
        {"type": "object", "properties": {
            "query": {"type": "string", "description": "Words to find, as they might have been said or written."},
            "person": {"type": "string", "description": "Only meetings with this person, by name or address."},
            "since": {"type": "string", "description": "Only meetings from this date on, YYYY-MM-DD."},
            "until": {"type": "string", "description": "Only meetings before this date, YYYY-MM-DD."},
            "limit": {"type": "integer", "description": "How many, at most (8)."}}},
        tool_search, area="synapse")
    registry._own(
        "meeting_read",
        "Read one meeting from the meeting library: its summary, decisions and action items as the library has "
        "them, who took part, and its transcript with times and speakers. meeting is its number (from "
        "meeting_search) or words to find it by; part is all (the default), summary or transcript; from reads a "
        "long transcript on from that passage. Read only.",
        {"type": "object", "properties": {
            "meeting": {"type": "string"},
            "part": {"type": "string", "enum": ["all", "summary", "transcript"]},
            "from": {"type": "integer"}}, "required": ["meeting"]},
        tool_read, area="synapse")


def prompt_line() -> str:
    """One line for the prompt, when the person may read any meeting."""
    with contextlib.suppress(Exception):
        who = _who()
        if any(principals_for(ds, who) for ds in _datasets_for(who)):
            return ("Meetings: every meeting in the meeting library (recorded and transcribed) "
                    "that the person may read is kept in step. For anything about a meeting itself, what was said, "
                    "who said it, what was decided or who took on what, use meeting_search to find it and "
                    "meeting_read to read its transcript, decisions and action items, and quote them; use "
                    "synapse_query for questions that cross meetings with mail, tasks, calendar and notes. Both are "
                    "read only: never offer to change a meeting or send a recap from here.")
    return ""


__all__ = ["SOURCE", "PART", "beat", "beat_one", "check", "declare", "fetch", "health", "hear", "key_of",
           "links_for", "normalise", "poll", "process_due", "process_one", "prompt_line", "receive", "relink",
           "settings", "start", "transcript_passages", "verify", "wake", "write_transcript"]
