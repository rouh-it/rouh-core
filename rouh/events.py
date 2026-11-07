"""The event log: everything done in Rouh and by it, one row each, kept to be studied.

Petar, 10 October 2026: "Okay, build it. For now track everything in the way we should
to be able to take full advantage of it. This will be big as we will be recording
everything. Think scalability. Databases, etc. For now put an extra tab in the
settings/stats and show me some basic numbers so I get a feel that we are collecting.
Later will be developing features and analysis based on that."

One foundation, two views later: how Rouh is used (where the person presses, what they
open, how much they write) and what work is done (by whom, of what kind, for how long
and how it ended). Both are rows of one table, `analytics.event` (migration 0115), and
`EVENTS.md` is the design: volumes, partitions, retention, and the way to a columnar
store if it is ever needed.

* **One way in.** The page sends batches to `/api/events` (`rouh/static/track.js`,
  read by `take`); the server's own code calls `emit`. Both only queue rows in memory.
  One thread writes them, a few hundred at a time in one statement, every couple of
  seconds, so nothing anybody waits for ever waits on this. If the database is away
  the rows are dropped and counted, never raised: an event is never worth an error.
* **A fixed list of names.** `NAMES` is every kind of event there is, and whether the
  page may send it. A name not on it is refused, so the log never fills with spellings.
* **Never what was typed or said.** Counts, lengths, durations and ids only. `props`
  goes through `clean`, which drops any key that names content (text, body, value,
  password ...) and any long string, and the page never reads a field's value in the
  first place: it counts characters as they are typed.
* **Everybody's own.** Every row carries `org_id` and `user_id`, and every read names
  both: Settings, Stats shows the signed-in person their own numbers only.
* **Rollups.** `rollup` adds what arrived since it last ran into `event_hourly` and
  `object_daily`, under a lock so two never race, a minute at a time from the writer's
  thread and once more before Stats is read. The page reads only those.
"""
from __future__ import annotations

import atexit
import collections
import json
import logging
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

log = logging.getLogger("rouh.events")

#: The shape of a row. Raised when a column's meaning changes, so rows written before
#: can still be read the way they were meant.
VERSION = 1

#: Who did what an event names. For work that runs for a while (`job.*`, `run.*`) it
#: is who set the work going, on its start and on its end alike, so the two pair up.
ACTORS = ("person", "rouh", "job", "run", "delegate", "system")

#: Where it came from.
SOURCES = ("web", "telegram", "mail", "voice", "scheduler", "server")


@dataclass(frozen=True)
class Kind:
    #: Whether the page may send it. Everything else only the server's own code says.
    page: bool
    about: str


#: Every kind of event there is. A new one is added here, with what its fields mean.
NAMES: dict[str, Kind] = {
    # --- the page (`rouh/static/track.js`) ---
    "page.loaded": Kind(True, "Rouh was opened or reloaded in a tab. props: width, height, touch, "
                              "standalone (installed as an app), path."),
    "page.shown": Kind(True, "The tab came back into sight."),
    "page.hidden": Kind(True, "The tab went out of sight or was closed. duration_ms: how long it "
                              "had been in sight."),
    "ui.click": Kind(True, "A press of a control. object: control and its key (its data-nav, "
                           "id, data-act, ...); props.area the region it is in, props.on_type and "
                           "props.on_id the card, chat, run or project it was pressed on, "
                           "props.host for a link out of Rouh."),
    "ui.open": Kind(True, "The address changed: something was opened. object: what, read from "
                          "the address (task, step, project, file, chat, run, card, settings, place); "
                          "props.path."),
    "ui.typed": Kind(True, "A spell of typing in one field. count: characters typed; props.deleted, "
                           "props.pasted: characters deleted and pasted; duration_ms: time spent "
                           "typing; object: field and its key. Never what was typed."),
    "ui.tap": Kind(True, "A tap made while a text field had the focus that did not go as a tap "
                         "should (`rouh/static/press.js`). object: the control; props.why: moved, "
                         "long, gone, not typing, cancelled, no button (landed beside one: "
                         "props.landed, props.gap), or after keyboard (the browser pressed it soon "
                         "after the field lost the focus: props.since_blur, "
                         "props.taps_while_typing); props.x, y, ms, fingers, and the screen: vvh, "
                         "vvtop, scale, ih, ch, top. Never what was typed."),
    # --- the server ---
    "chat.message_sent": Kind(False, "A person's message reached Rouh. count: its length in "
                                     "characters; source: web, voice or telegram. Never its words."),
    "chat.forked": Kind(False, "A chat was forked. object: the new chat; props.from_chat."),
    "turn.finished": Kind(False, "Rouh finished answering. duration_ms: from the start of the "
                                 "answer to its end; props.ok, props.spoken; actor: person when "
                                 "the person asked, rouh when a note of Rouh's software did."),
    "tool.called": Kind(False, "Rouh's model called a tool. object: tool and its name; "
                               "duration_ms: how long it ran; props.ok."),
    "job.started": Kind(False, "A background job was started. object: job and its id."),
    "job.finished": Kind(False, "A background job ended. duration_ms: how long it ran; "
                                "props.outcome."),
    "run.started": Kind(False, "A run of the one program was started from Rouh. object: run."),
    "run.finished": Kind(False, "A run of the one program ended. duration_ms; props.outcome."),
    "mail.handled": Kind(False, "An email that arrived was handled. object: mail and its id; "
                                "props.outcome."),
    "reminder.fired": Kind(False, "A reminder or timed piece of work came due. object: reminder."),
    "decision.answered": Kind(False, "A decision waiting on somebody was answered. object: decision; "
                                     "actor: person, or delegate for a trusted contact."),
    "share.opened": Kind(False, "A person opened a page or task shared with them by email. Kept "
                                "under the ids of the owner whose share it is; actor: delegate; "
                                "object: share and a short hash of its token, never the token "
                                "(`rouh/share_opens.py`)."),
    "schedule.ran": Kind(False, "Scheduled work ran: a heartbeat beat, a morning brief, a nightly "
                                "job. object: work and what it was; duration_ms; props.outcome."),
}

#: How many rows may wait in memory before the oldest new ones are dropped.
MAX_WAITING = 50_000
#: How many rows go in one statement, and how often the writer looks.
BATCH = 500
FLUSH_EVERY = 2.0
#: How often the writer's thread fills in the rollups.
ROLL_EVERY = 60.0
#: How long after a row arrives before a rollup counts it: long enough that no write
#: still in flight is passed over.
ROLL_LAG = timedelta(seconds=10)
#: An event says when it happened; a clock that is off by more than this is not
#: believed, and the time it arrived is used. Keeps every row inside the months
#: `ensure_partitions` has made.
BEHIND = timedelta(days=1)
AHEAD = timedelta(minutes=5)
#: The most the page may send at once.
PAGE_BATCH = 200

_NAME = re.compile(r"^[a-z][a-z0-9_]{0,23}$")
_KEY = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
#: A key with any of these words in it is never kept: it would be what somebody wrote,
#: said or holds secret. An id of one is fine (`message_id`), its words are not.
_NEVER = frozenset(("text", "body", "content", "value", "values", "password", "secret", "token",
                    "message", "subject", "query", "prompt", "html", "title", "words", "said",
                    "typed", "transcript", "answer", "reply", "note", "comment", "email", "phone",
                    "address", "card", "iban", "otp", "code"))
_ALLOWED_TAIL = frozenset(("id", "ids", "count", "len", "length", "chars", "ms", "n", "kind", "type"))
#: The longest string `props` keeps. Anything longer is likely to be somebody's words.
LONGEST = 200
#: The most a row's `props` may weigh, as JSON.
HEAVIEST = 4000

COLUMNS = ("id", "occurred_at", "org_id", "user_id", "session_id", "chat_id", "actor", "source",
           "name", "object_type", "object_id", "duration_ms", "count", "props", "v")


class Refused(ValueError):
    """What the page sent cannot be kept, with what to say about it."""


# --------------------------------------------------------------------------
# What a row may hold
# --------------------------------------------------------------------------


def _key_ok(key: str) -> bool:
    if not _KEY.match(key):
        return False
    parts = key.split("_")
    if parts[-1] in _ALLOWED_TAIL and len(parts) > 1:
        return True
    return not any(p in _NEVER for p in parts)


def _scalar(value):
    if value is None or isinstance(value, bool):
        return True, value
    if isinstance(value, int):
        return True, max(-(2 ** 53), min(2 ** 53, value))
    if isinstance(value, float):
        return (value == value and abs(value) != float("inf")), value
    if isinstance(value, str):
        return len(value) <= LONGEST, value
    return False, None


def clean(props, *, depth: int = 0) -> dict:
    """What of `props` may be kept: short values under keys that name no content.

    The guard behind the rule, not the rule itself: nothing that sends an event should
    be holding a person's words in the first place.
    """
    if not isinstance(props, dict):
        return {}
    out: dict = {}
    for key, value in list(props.items())[:40]:
        key = str(key)
        if not _key_ok(key):
            continue
        if isinstance(value, dict) and depth == 0:
            inner = clean(value, depth=1)
            if inner:
                out[key] = inner
            continue
        if isinstance(value, (list, tuple)):
            kept = []
            for item in list(value)[:20]:
                ok, item = _scalar(item)
                if ok:
                    kept.append(item)
            out[key] = kept
            continue
        ok, value = _scalar(value)
        if ok:
            out[key] = value
    if depth == 0 and len(json.dumps(out, ensure_ascii=False, default=str)) > HEAVIEST:
        return {"dropped": "too big"}
    return out


def uuid7(ms: int | None = None) -> str:
    """A time-ordered id (RFC 9562, version 7), so ids sort the way rows were made."""
    ms = int(time.time() * 1000) if ms is None else int(ms)
    rand = int.from_bytes(os.urandom(10), "big")
    value = ((ms & ((1 << 48) - 1)) << 80) | (0x7 << 76) | (((rand >> 62) & 0xFFF) << 64) \
        | (0b10 << 62) | (rand & ((1 << 62) - 1))
    return str(uuid.UUID(int=value))


def _when(at, now: datetime) -> datetime:
    """When it happened, believed only within `BEHIND` and `AHEAD` of now."""
    if isinstance(at, datetime):
        when = at if at.tzinfo else at.replace(tzinfo=timezone.utc)
    elif isinstance(at, (int, float)) and not isinstance(at, bool) and at == at:
        seconds = at / 1000 if at > 1e11 else at
        try:
            when = datetime.fromtimestamp(seconds, timezone.utc)
        except (OverflowError, OSError, ValueError):
            return now
    else:
        return now
    if when < now - BEHIND or when > now + AHEAD:
        return now
    return when


def _short(value, longest: int = 300) -> str:
    text = "" if value is None else str(value)
    return text[:longest]


def _number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = int(round(float(value)))
    except (TypeError, ValueError, OverflowError):
        return None
    return max(-(2 ** 62), min(2 ** 62, number))


#: Stands for the install owner in a queued row, until the writer knows who that is.
OWNER = "\x00owner"


def _row(name: str, *, org_id: str, user_id: str, actor: str, source: str, at=None,
         session_id: str = "", chat_id: str = "", object_type: str = "", object_id: str = "",
         duration_ms=None, count=None, props=None, ident: str = "") -> tuple:
    now = datetime.now(timezone.utc)
    object_type = str(object_type or "")
    if object_type and not _NAME.match(object_type):
        object_type = ""
    return (ident or uuid7(), _when(at, now), _short(org_id, 64),
            user_id if user_id == OWNER else _short(user_id, 64),
            _short(session_id, 64), _short(chat_id, 128), actor, source, name, object_type,
            _short(object_id) if object_type else "", _number(duration_ms), _number(count),
            json.dumps(clean(props), ensure_ascii=False, default=str), VERSION)


# --------------------------------------------------------------------------
# Writing
# --------------------------------------------------------------------------

#: Who set each piece of running work going, by its id, for the event that says it
#: ended: started by the person or by Rouh, on both ends. Kept in memory only, the
#: last few thousand; work that outlives a restart ends as `default` says.
_STARTERS: collections.OrderedDict[str, str] = collections.OrderedDict()
_STARTERS_KEPT = 5000


def started(kind: str, ident: str, *, actor: str, **fields) -> None:
    """`job.started` or `run.started`, remembering who started it for its end."""
    ident = str(ident or "")
    if ident:
        _STARTERS[ident] = actor
        while len(_STARTERS) > _STARTERS_KEPT:
            _STARTERS.popitem(last=False)
    emit(f"{kind}.started", actor=actor, object_type=kind, object_id=ident, **fields)


def started_by(ident: str, default: str) -> str:
    """Who set this work going, if this process saw it start."""
    return _STARTERS.get(str(ident or ""), default)



def emit(name: str, *, who=None, user_id: str | None = None, org_id: str | None = None,
         actor: str = "rouh", source: str = "server", at=None, session_id: str = "",
         chat_id: str = "", object_type: str = "", object_id="", duration_ms=None, count=None,
         props: dict | None = None, owner: bool = False) -> None:
    """Keep one event the server saw. Never raises, never waits.

    `who` is whose it is (an `Identity`); without one, the person this context belongs
    to (`tenancy.speaker`), and without that, `user_id` and `org_id` as given. `owner`
    says that work nobody signed in asked for (a job, a run, the phone, the clock) is
    the install owner's, found by the writer (`telegram.phone_owner`) so the caller
    never waits on the database. An event with nobody's ids is still kept, as the
    system's.
    """
    try:
        if name not in NAMES:
            log.warning("an event called %r is not one of events.NAMES, and was not kept", name)
            return
        if actor not in ACTORS:
            actor = "system"
        if source not in SOURCES:
            source = "server"
        if who is None and user_id is None:
            from .tenancy import speaker

            who = speaker()
        if who is not None:
            user_id = user_id if user_id is not None else getattr(who, "user_id", "")
            org_id = org_id if org_id is not None else getattr(who, "org_id", "")
        if not user_id and owner:
            user_id, org_id = OWNER, ""
        WRITER.put([_row(name, org_id=org_id or "", user_id=user_id or "", actor=actor,
                         source=source, at=at, session_id=session_id, chat_id=chat_id,
                         object_type=object_type, object_id=object_id, duration_ms=duration_ms,
                         count=count, props=props)])
    except Exception:  # noqa: BLE001 - an event is never worth an error
        log.warning("an event could not be kept", exc_info=True)


def take(who, body) -> dict:
    """Keep what a page sent: `{session, events: [{id, name, at, ...}]}`.

    Whose it is comes from the sign-in, never from the body; the page may only say it
    is the person, from the web, and only the names `NAMES` marks as the page's.
    """
    from .tenancy import GUEST_ORG

    if who is None:
        raise Refused("Sign in first.")
    if str(who.org_id) == GUEST_ORG:
        raise Refused("A guest's page sends no events.")
    if not isinstance(body, dict):
        raise Refused("Send {session, events}.")
    got = body.get("events")
    if not isinstance(got, list):
        raise Refused("Send {session, events}.")
    session = _short(body.get("session"), 64)
    rows, refused = [], 0
    for event in got[:PAGE_BATCH]:
        if not isinstance(event, dict) or not NAMES.get(str(event.get("name"))) \
                or not NAMES[str(event.get("name"))].page:
            refused += 1
            continue
        name = str(event["name"])
        ident = ""
        try:
            ident = str(uuid.UUID(str(event.get("id"))))
        except (ValueError, TypeError, AttributeError):
            ident = ""
        props = event.get("props") if isinstance(event.get("props"), dict) else {}
        object_type, object_id = str(event.get("object_type") or ""), event.get("object_id") or ""
        if name == "ui.open" and not object_type:
            object_type, object_id = place_of(str(props.get("path") or ""), str(props.get("chat") or ""))
        rows.append(_row(name, org_id=str(who.org_id), user_id=str(who.user_id), actor="person",
                         source="web", at=event.get("at"), session_id=session,
                         chat_id=_short(event.get("chat_id"), 128), object_type=object_type,
                         object_id=object_id, duration_ms=event.get("duration_ms"),
                         count=event.get("count"), props=props, ident=ident))
    refused += max(0, len(got) - PAGE_BATCH)
    if rows:
        WRITER.put(rows)
    return {"taken": len(rows), "refused": refused}


_NUMBERED = re.compile(r"^(\d+(?:-\d+)*)\.")


def place_of(path: str, chat: str = "") -> tuple[str, str]:
    """What an address names, as (object type, object id) (`rouh/addressing.py`).

    A task's address is its folder, so the deepest numbered folder in it is the task
    or the step, and anything under that is a file inside it.
    """
    from urllib.parse import unquote

    parts = [unquote(p) for p in str(path or "").split("?")[0].split("#")[0].split("/") if p]
    if not parts:
        return ("chat", chat) if chat else ("place", "home")
    head = parts[0]
    rest = parts[1:]
    if head in ("chat", "run") and rest:
        return head, rest[0]
    if head == "artifact" and rest:
        return "card", rest[0]
    if head == "project" and rest:
        return "project", "/".join(rest)
    if head == "task" and rest:
        deepest = -1
        for i, part in enumerate(rest):
            if _NUMBERED.match(part):
                deepest = i
        if deepest < 0:
            return "task", "/".join(rest)
        number = _NUMBERED.match(rest[deepest]).group(1)
        kind = "step" if "-" in number else "task"
        if deepest < len(rest) - 1:
            return "file", "/".join(rest)
        return kind, "/".join(rest[: deepest + 1])
    if head == "settings":
        return "settings", "/".join(rest) or "front"
    # Anatomy's pages are Settings' since 14 October 2026: a section by its own name, as each
    # group of Settings was, a group's page by the group's, and the status board as the front.
    if head == "anatomy":
        return "settings", "/".join(rest[1:]) or (rest[0] if rest else "front")
    if head in ("decisions", "quests", "brief", "synapse", "work") and rest:
        return {"decisions": "decision", "quests": "quest", "work": "quest"}.get(head, head), \
            "/".join(rest)
    return "place", head


class _Writer:
    """One thread that writes queued rows in batches, and keeps the rollups filled in."""

    def __init__(self) -> None:
        self._rows: collections.deque = collections.deque()
        self._cond = threading.Condition()
        self._thread: threading.Thread | None = None
        self._busy = False
        self._months_on = ""
        self._rolled = 0.0
        self.written = 0
        self.dropped = 0
        self.last_written = 0.0
        self.last_error = ""
        self._said_at = 0.0
        self._owner: tuple[str, str] = ("", "")
        self._owner_at = 0.0

    def put(self, rows: list) -> None:
        with self._cond:
            room = MAX_WAITING - len(self._rows)
            if room < len(rows):
                self.dropped += len(rows) - max(room, 0)
                rows = rows[: max(room, 0)]
            self._rows.extend(rows)
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._run, name="rouh-events", daemon=True)
                self._thread.start()
            if len(self._rows) >= BATCH:
                self._cond.notify_all()

    def waiting(self) -> int:
        return len(self._rows)

    def _run(self) -> None:
        while True:
            with self._cond:
                if len(self._rows) < BATCH:
                    self._cond.wait(FLUSH_EVERY)
                batch = [self._rows.popleft() for _ in range(min(BATCH, len(self._rows)))]
                self._busy = bool(batch)
            try:
                if batch:
                    self._write(batch)
                if time.monotonic() - self._rolled >= ROLL_EVERY:
                    self._rolled = time.monotonic()
                    rollup()
            except Exception as exc:  # noqa: BLE001 - never anybody's problem but the log's
                self._failed(len(batch), exc)
            finally:
                with self._cond:
                    self._busy = False
                    self._cond.notify_all()

    def _failed(self, n: int, exc: Exception) -> None:
        self.dropped += n
        self.last_error = f"{type(exc).__name__}: {str(exc)[:200]}"
        if time.monotonic() - self._said_at > 60:
            self._said_at = time.monotonic()
            log.warning("%d events could not be written: %s", n, self.last_error)
        try:
            from django.db import connection

            connection.close()
        except Exception:  # noqa: BLE001
            pass

    def _months(self) -> None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self._months_on != today:
            ensure_partitions()
            self._months_on = today

    def _owned(self, batch: list) -> list:
        """The rows marked as the install owner's, with the owner's ids put in."""
        if not any(row[3] == OWNER for row in batch):
            return batch
        if time.monotonic() - self._owner_at > 300 or not self._owner[0]:
            from . import runtime, telegram

            who = telegram.phone_owner(runtime.tenancy)
            self._owner = (str(who.user_id), str(who.org_id)) if who is not None else ("", "")
            self._owner_at = time.monotonic()
        user_id, org_id = self._owner
        return [(row[0], row[1], org_id, user_id) + row[4:] if row[3] == OWNER else row
                for row in batch]

    def _write(self, batch: list) -> None:
        from django.db import connection

        self._months()
        batch = self._owned(batch)
        cells = "(" + ",".join(["%s::jsonb" if c == "props" else "%s" for c in COLUMNS]) + ")"
        sql = (f"INSERT INTO analytics.event ({','.join(COLUMNS)}) VALUES "
               + ",".join([cells] * len(batch)) + " ON CONFLICT DO NOTHING")
        params = [cell for row in batch for cell in row]
        try:
            with connection.cursor() as cur:
                cur.execute(sql, params)
        except Exception as exc:  # noqa: BLE001
            if "no partition" not in str(exc):
                raise
            # A month nobody made yet (the clock passed midnight on the last day).
            ensure_partitions()
            with connection.cursor() as cur:
                cur.execute(sql, params)
        self.written += len(batch)
        self.last_written = time.time()

    def flush(self, timeout: float = 10.0) -> bool:
        """Wait until everything queued so far is written."""
        end = time.monotonic() + timeout
        with self._cond:
            if self._thread is None:
                return True
            self._cond.notify_all()
            while self._rows or self._busy:
                left = end - time.monotonic()
                if left <= 0:
                    return False
                self._cond.notify_all()
                self._cond.wait(min(left, 0.2))
        return True


WRITER = _Writer()


def start() -> None:
    """Start the writer's thread now, rather than at the first event."""
    WRITER.put([])

# What is still waiting when the process ends is written first.
atexit.register(WRITER.flush, 5.0)


def ensure_partitions(behind: int = 1, ahead: int = 3) -> int:
    """Make the months around now, if any is missing (migration 0115's function)."""
    from django.db import connection

    with connection.cursor() as cur:
        cur.execute("SELECT analytics.ensure_partitions(%s, %s)", [behind, ahead])
        return int(cur.fetchone()[0] or 0)


# --------------------------------------------------------------------------
# Rollups
# --------------------------------------------------------------------------

_ROLL_HOURLY = """
INSERT INTO analytics.event_hourly AS h
  (org_id, user_id, hour, name, actor, source, n, count_sum, duration_ms_sum, last_at)
SELECT org_id, user_id, date_trunc('hour', occurred_at, 'UTC'), name, actor, source,
       count(*), coalesce(sum(count), 0), coalesce(sum(duration_ms), 0), max(occurred_at)
  FROM analytics.event
 WHERE received_at > %(since)s AND received_at <= %(upto)s AND occurred_at >= %(floor)s
 GROUP BY 1, 2, 3, 4, 5, 6
ON CONFLICT (org_id, user_id, hour, name, actor, source) DO UPDATE
   SET n = h.n + EXCLUDED.n,
       count_sum = h.count_sum + EXCLUDED.count_sum,
       duration_ms_sum = h.duration_ms_sum + EXCLUDED.duration_ms_sum,
       last_at = greatest(h.last_at, EXCLUDED.last_at)
"""

_ROLL_OBJECTS = """
INSERT INTO analytics.object_daily AS o
  (org_id, user_id, day, name, object_type, object_id, n, last_at)
SELECT org_id, user_id, (occurred_at AT TIME ZONE 'UTC')::date, name, object_type, object_id,
       count(*), max(occurred_at)
  FROM analytics.event
 WHERE received_at > %(since)s AND received_at <= %(upto)s AND occurred_at >= %(floor)s
   AND object_id <> ''
 GROUP BY 1, 2, 3, 4, 5, 6
ON CONFLICT (org_id, user_id, day, name, object_type, object_id) DO UPDATE
   SET n = o.n + EXCLUDED.n, last_at = greatest(o.last_at, EXCLUDED.last_at)
"""


def rollup() -> bool:
    """Add every row that arrived since the last time into the rollups.

    Additive and in one transaction with the mark of how far it got, so a row is
    counted exactly once. Only one runs at a time, anywhere: a second caller finds
    the lock taken and goes away, which is right, because the first is doing its work.
    """
    from django.db import connection, transaction

    with transaction.atomic():
        with connection.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_xact_lock(hashtext('analytics.rollup'))")
            if not cur.fetchone()[0]:
                return False
            cur.execute("SELECT through FROM analytics.rollup_state WHERE name = 'events'")
            got = cur.fetchone()
            since = got[0] if got else datetime(2000, 1, 1, tzinfo=timezone.utc)
            cur.execute("SELECT now()")
            upto = cur.fetchone()[0] - ROLL_LAG
            if upto <= since:
                return True
            # Rows are kept within `BEHIND` of their arrival, so older months are not read.
            floor = since - BEHIND - timedelta(days=1)
            args = {"since": since, "upto": upto, "floor": floor}
            cur.execute(_ROLL_HOURLY, args)
            cur.execute(_ROLL_OBJECTS, args)
            cur.execute("INSERT INTO analytics.rollup_state (name, through) VALUES ('events', %s) "
                        "ON CONFLICT (name) DO UPDATE SET through = EXCLUDED.through", [upto])
    return True


# --------------------------------------------------------------------------
# Reading, for Settings, Stats
# --------------------------------------------------------------------------

#: How far back the charts and lists look, in days.
DAYS = 30


def _rows(sql: str, params) -> list[tuple]:
    from django.db import connection

    with connection.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def _iso(value) -> str:
    return value.astimezone(timezone.utc).isoformat() if value else ""


def stats(who, *, zone=None) -> dict:
    """The signed-in person's own numbers, from the rollups, on their own clock."""
    from . import clock

    try:
        rollup()
    except Exception:  # noqa: BLE001 - the numbers so far are still worth showing
        log.warning("the event rollups could not be brought up to date", exc_info=True)
    tz = zone or clock.zone_of(who)
    org, user = str(who.org_id), str(who.user_id)
    local = datetime.now(tz)
    today = local.replace(hour=0, minute=0, second=0, microsecond=0)
    week = today - timedelta(days=today.weekday())
    first = today - timedelta(days=DAYS - 1)
    mine = "org_id = %(org)s AND user_id = %(user)s"
    p = {"org": org, "user": user, "today": today, "week": week, "first": first,
         "zone": getattr(tz, "key", "UTC"), "first_day": first.astimezone(timezone.utc).date()}

    total = _rows(f"""
        SELECT coalesce(sum(n) FILTER (WHERE hour >= %(today)s), 0),
               coalesce(sum(n) FILTER (WHERE hour >= %(week)s), 0),
               coalesce(sum(n), 0), max(last_at), min(hour)
          FROM analytics.event_hourly WHERE {mine}""", p)[0]

    per_day = dict(_rows(f"""
        SELECT (hour AT TIME ZONE %(zone)s)::date, sum(n)
          FROM analytics.event_hourly WHERE {mine} AND hour >= %(first)s
         GROUP BY 1""", p))
    days = []
    for i in range(DAYS):
        day = (first + timedelta(days=i)).date()
        days.append({"day": day.isoformat(), "n": int(per_day.get(day, 0))})

    names = [{"name": name, "n": int(n)} for name, n in _rows(f"""
        SELECT name, sum(n) FROM analytics.event_hourly WHERE {mine} AND hour >= %(first)s
         GROUP BY name ORDER BY 2 DESC, 1 LIMIT 12""", p)]

    sums = {name: (int(n), int(c), int(d)) for name, n, c, d in _rows(f"""
        SELECT name, sum(n), sum(count_sum), sum(duration_ms_sum)
          FROM analytics.event_hourly WHERE {mine} AND hour >= %(first)s
           AND name IN ('chat.message_sent', 'ui.typed', 'chat.forked', 'ui.click', 'ui.open',
                        'turn.finished', 'tool.called')
         GROUP BY name""", p)}

    work = {}
    for name, actor, n, d in _rows(f"""
        SELECT name, actor, sum(n), sum(duration_ms_sum)
          FROM analytics.event_hourly WHERE {mine} AND hour >= %(first)s
           AND name IN ('job.started', 'job.finished', 'run.started', 'run.finished')
         GROUP BY name, actor""", p):
        kind, step = name.split(".")
        row = work.setdefault((kind, actor), {"kind": kind, "actor": actor, "started": 0,
                                               "finished": 0, "duration_ms": 0})
        row[step] = int(n)
        if step == "finished":
            row["duration_ms"] = int(d)

    opened = [{"type": t, "id": i, "n": int(n), "last": _iso(last)} for t, i, n, last in _rows(f"""
        SELECT object_type, object_id, sum(n), max(last_at)
          FROM analytics.object_daily WHERE {mine} AND day >= %(first_day)s
           AND name = 'ui.open' AND object_type IN ('task', 'step', 'project')
         GROUP BY 1, 2 ORDER BY 3 DESC, 4 DESC LIMIT 10""", p)]

    tools = [{"tool": i, "n": int(n)} for i, n in _rows(f"""
        SELECT object_id, sum(n) FROM analytics.object_daily WHERE {mine} AND day >= %(first_day)s
           AND name = 'tool.called' GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT 15""", p)]

    size = _rows("""
        SELECT coalesce(sum(pg_total_relation_size(inhrelid)), 0)
          FROM pg_inherits WHERE inhparent = 'analytics.event'::regclass""", [])[0][0]
    # Everybody's rows, as the rollups have counted them: exact, and a small table.
    rows = _rows("SELECT coalesce(sum(n), 0) FROM analytics.event_hourly", [])[0][0]
    rolled = _rows("SELECT coalesce(pg_total_relation_size('analytics.event_hourly'), 0) "
                   "+ coalesce(pg_total_relation_size('analytics.object_daily'), 0)", [])[0][0]
    months = _rows("SELECT count(*) FROM pg_inherits WHERE inhparent = 'analytics.event'::regclass",
                   [])[0][0]

    def got(name):
        return sums.get(name, (0, 0, 0))

    return {
        "days": DAYS, "zone": p["zone"],
        "totals": {"today": int(total[0]), "week": int(total[1]), "all": int(total[2]),
                   "last": _iso(total[3]), "since": _iso(total[4])},
        "per_day": days,
        "names": names,
        "typing": {"messages": got("chat.message_sent")[0],
                   "message_chars": got("chat.message_sent")[1],
                   "typed_chars": got("ui.typed")[1],
                   "typing_ms": got("ui.typed")[2],
                   "clicks": got("ui.click")[0], "opens": got("ui.open")[0]},
        "forks": got("chat.forked")[0],
        "turns": {"n": got("turn.finished")[0], "duration_ms": got("turn.finished")[2]},
        "work": sorted(work.values(), key=lambda w: (w["kind"], w["actor"])),
        "opened": opened,
        "tools": tools,
        "storage": {"bytes": int(size), "rollup_bytes": int(rolled), "rows": int(rows),
                    "months": int(months)},
        "writer": {"written": WRITER.written, "dropped": WRITER.dropped,
                   "waiting": WRITER.waiting(), "last_written": WRITER.last_written},
    }
