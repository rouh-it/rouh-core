"""The core scrubs the private reasoning already kept in the model request log, by itself.

Petar, 11 November 2026: "I am not supposed to run manually commands", then "yes please" to Rouh
running the cleanup itself. Commit a5da7acf stopped new rows of `llm_requests` and `llm_pieces`
keeping OpenAI's ``encrypted_content`` and Anthropic's thinking signatures and
``redacted_thinking`` data, which nobody can read, and added ``manage.py scrub_encrypted_reasoning``
for the rows already there (about 11.4 GB were stored, task 161-09). A job cannot run that
command: it works in the worker container, which never reaches the live database
(`CONTAINERS.md`, walls.worker-no-database). An earlier try ran the cleanup as a migration at
start-up and held Rouh down for more than 14 minutes, so nothing here runs in ``migrate`` or
holds start-up or the health page up.

So the core runs it, on a thread of its own:

- **Late.** `runtime._reasoning_scrub_loop` starts it `START_AFTER` seconds after the core is up,
  and only when it is not done. A job can start it sooner with ``core_command``
  (`rouh/core_commands.py`).
- **Small and paced.** `llmlog.scrub_historical_reasoning` with `BATCH` rows a transaction and
  `PAUSE` seconds between batches, on a background thread (`db.base.BACKGROUND`) that gives its
  connection back after every batch, so the conversation never waits on it.
- **Resumable.** After every committed batch its place (the last request id, then the last piece
  hash), its counts and its times are written to `state_path`, in the data directory. A restart,
  a deploy or a crash carries on from there; a batch done twice changes nothing the second time.
- **Done once.** When both tables are read to the end it runs ordinary ``VACUUM`` (never
  ``VACUUM FULL``, which locks the table) on each, writes the sizes after, and marks itself done.
  A done scrub is never started again by the loop: new rows are already safe.

    python manage.py scrub_encrypted_reasoning --status     what the core's scrub has done so far
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time

log = logging.getLogger("rouh.reasoning_scrub")

#: Seconds after the core starts before the scrub starts, so start-up and health are never held.
START_AFTER = 300
#: Rows a transaction. A row of either table can hold a whole long message, so far smaller than
#: the command's default: a batch stays small in memory and its transaction short.
BATCH = 100
#: Seconds between batches, so the rest of Rouh always gets the database between them.
PAUSE = 0.1
#: A batch's progress is said in Rouh's log once every this many batches.
SAY_EVERY = 50
#: The two tables, both vacuumed at the end.
TABLES = ("llm_requests", "llm_pieces")
#: Past every request id: what is passed once the requests are done, so only the pieces are read.
PAST_REQUESTS = 2 ** 62
#: The thread's name: background work for the pool (`rouh/project/db/base.py`).
THREAD = "maintenance-reasoning-scrub"

_lock = threading.Lock()
_thread: threading.Thread | None = None
_stop = threading.Event()


class Stopped(Exception):
    """The process is going down: the scrub stops after the batch it has committed."""


def state_path() -> str:
    from .config import config

    return os.path.join(config.data_dir, "maintenance", "reasoning_scrub.json")


def state() -> dict:
    """What the scrub has done so far, as kept: {} when it never started."""
    try:
        with open(state_path(), encoding="utf-8") as fh:
            got = json.load(fh)
    except (OSError, ValueError):
        return {}
    return got if isinstance(got, dict) else {}


def _save(st: dict) -> None:
    path = state_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    st["updated_at"] = time.time()
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".scrub-")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(st, fh, indent=1, sort_keys=True)
    os.replace(tmp, path)


def done() -> bool:
    return state().get("phase") == "done"


def running() -> bool:
    return _thread is not None and _thread.is_alive()


def sizes() -> dict:
    """The database's size and the two tables' (with their TOAST and indexes), in bytes."""
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_database_size(current_database())")
        out = {"database": int(cursor.fetchone()[0])}
        for table in TABLES:
            cursor.execute("SELECT pg_total_relation_size(%s::regclass)", (table,))
            out[table] = int(cursor.fetchone()[0])
    return out


def _gb(n) -> str:
    return f"{(n or 0) / 1e9:.2f} GB"


def describe(st: dict | None = None) -> str:
    """The scrub in a few plain sentences, for a job, a shell or the log."""
    st = state() if st is None else st
    if not st:
        return ("The core has not started the scrub yet. It starts by itself "
                f"{START_AFTER // 60} minutes after Rouh starts, or at once when a job asks with "
                "core_command scrub_encrypted_reasoning.")
    phase = st.get("phase", "")
    n = st.get("scrubbed") or {}
    seen = st.get("scanned") or {}
    lines = []
    when = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(st.get("started_at") or 0))
    lines.append(f"Phase: {phase}{' (running now)' if running() else ''}. Started {when}.")
    lines.append(f"Read so far: {seen.get('requests', 0):,} request rows and "
                 f"{seen.get('pieces', 0):,} piece rows.")
    lines.append(f"Scrubbed so far: {n.get('request_rows', 0):,} request rows "
                 f"({_gb(n.get('request_bytes'))}) and {n.get('piece_rows', 0):,} piece rows "
                 f"({_gb(n.get('piece_bytes'))}).")
    if st.get("total_requests") is not None:
        lines.append(f"About {st.get('total_requests', 0):,} request rows and "
                     f"{st.get('total_pieces', 0):,} piece rows to read in all "
                     "(PostgreSQL's estimate, from when it started).")
    lines.append(f"Resume point: request id {st.get('after_request_id', 0)}, piece hash "
                 f"{(st.get('after_piece_hash') or '(start)')[:16]}.")
    before, after = st.get("before") or {}, st.get("after") or {}
    if before:
        lines.append("Sizes before: database " + _gb(before.get("database")) + ", llm_requests "
                     + _gb(before.get("llm_requests")) + ", llm_pieces "
                     + _gb(before.get("llm_pieces")) + ".")
    if after:
        lines.append("Sizes after VACUUM: database " + _gb(after.get("database")) + ", llm_requests "
                     + _gb(after.get("llm_requests")) + ", llm_pieces "
                     + _gb(after.get("llm_pieces")) + ".")
    rate = st.get("rate_rows_s")
    if rate and phase in ("requests", "pieces"):
        left = max(0, (st.get("total_requests") or 0) - seen.get("requests", 0)) \
            + max(0, (st.get("total_pieces") or 0) - seen.get("pieces", 0))
        lines.append(f"Speed: about {rate:,.0f} rows a second, so roughly "
                     f"{left / rate / 60:,.0f} minutes left to read, then VACUUM.")
    if st.get("vacuum_s") is not None:
        lines.append(f"VACUUM took {st['vacuum_s']:.0f} seconds.")
    if st.get("error"):
        lines.append(f"Last error: {st['error']}")
    if st.get("finished_at"):
        lines.append("Finished " + time.strftime("%Y-%m-%d %H:%M UTC",
                                                 time.gmtime(st["finished_at"])) + ".")
    return "\n".join(lines)


def _estimates() -> dict:
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute("SELECT relname, GREATEST(reltuples, 0)::bigint FROM pg_class "
                       "WHERE relname = ANY(%s) AND relkind = 'r'", (list(TABLES),))
        got = dict(cursor.fetchall())
    return {"total_requests": int(got.get("llm_requests") or 0),
            "total_pieces": int(got.get("llm_pieces") or 0)}


def _vacuum() -> float:
    """Ordinary VACUUM (ANALYZE) on both tables, outside any transaction. Never VACUUM FULL."""
    from django.db import connection

    began = time.monotonic()
    if not connection.get_autocommit():
        raise RuntimeError("ordinary VACUUM needs autocommit")
    with connection.cursor() as cursor:
        for table in TABLES:
            log.info("the reasoning scrub: VACUUM %s", table)
            cursor.execute(f'VACUUM (ANALYZE) "{table}"')
    return time.monotonic() - began


def run(again: bool = False) -> dict:
    """The whole scrub, from where it last got to, to its end. Blocking: on its own thread."""
    from . import dbwork
    from .llmlog import scrub_historical_reasoning

    st = {} if again else state()
    if st.get("phase") == "done":
        return st
    try:
        if not st:
            st = {"phase": "requests", "started_at": time.time(), "after_request_id": 0,
                  "after_piece_hash": "", "scanned": {"requests": 0, "pieces": 0},
                  "scrubbed": {"request_rows": 0, "request_bytes": 0, "piece_rows": 0,
                               "piece_bytes": 0},
                  "before": sizes(), **_estimates()}
            _save(st)
            log.info("the reasoning scrub starts: %s", json.dumps(st["before"]))
        st["runs"] = int(st.get("runs") or 0) + 1
        st["resumed_at"] = time.time()
        st.pop("error", None)
        _save(st)
        dbwork.release()
        if st["phase"] in ("requests", "pieces"):
            base_scanned = dict(st["scanned"])
            base = dict(st["scrubbed"])
            began, batches = time.monotonic(), [0]

            def progress(stage, cursor_value, count, scanned, report):
                # Called after each batch has committed, outside its transaction.
                if stage == "requests":
                    st["after_request_id"] = int(cursor_value)
                else:
                    st["phase"] = "pieces"
                    st["after_piece_hash"] = cursor_value
                st["scanned"] = {k: base_scanned.get(k, 0) + scanned.get(k, 0)
                                 for k in ("requests", "pieces")}
                st["scrubbed"] = {k: base.get(k, 0) + report.get(k, 0) for k in base}
                read = scanned.get("requests", 0) + scanned.get("pieces", 0)
                st["rate_rows_s"] = read / max(0.001, time.monotonic() - began)
                _save(st)
                dbwork.release()
                batches[0] += 1
                if batches[0] % SAY_EVERY == 0:
                    log.info("the reasoning scrub: %s at %s, %s",
                             stage, str(cursor_value)[:16], json.dumps(st["scrubbed"]))
                if _stop.is_set():
                    raise Stopped()

            after_id = PAST_REQUESTS if st["phase"] == "pieces" else int(st["after_request_id"])
            scrub_historical_reasoning(batch_size=BATCH, pause=PAUSE, after_request_id=after_id,
                                       after_piece_hash=str(st.get("after_piece_hash") or ""),
                                       progress=progress)
            st["phase"] = "vacuum"
            st["read_done_at"] = time.time()
            _save(st)
            log.info("the reasoning scrub has read both tables: %s", json.dumps(st["scrubbed"]))
        if st["phase"] == "vacuum":
            dbwork.release()
            st["vacuum_s"] = _vacuum()
            st["after"] = sizes()
            st["phase"] = "done"
            st["finished_at"] = time.time()
            _save(st)
            log.info("the reasoning scrub is done: before %s, after %s",
                     json.dumps(st.get("before")), json.dumps(st["after"]))
        return st
    except Stopped:
        log.info("the reasoning scrub stopped with the process; it carries on at the next start")
        return st
    except Exception as exc:  # noqa: BLE001 - kept, and tried again from the saved place
        st["error"] = f"{type(exc).__name__}: {exc}"[:600]
        try:
            _save(st)
        except OSError:
            pass
        log.exception("the reasoning scrub failed; it carries on from its place later")
        return st
    finally:
        dbwork.release()


def start(again: bool = False) -> str:
    """Start the scrub on its own thread now, unless it is running or done. Never blocks.
    Returns "started", "running" or "done"."""
    global _thread
    with _lock:
        if running():
            return "running"
        if done() and not again:
            return "done"
        _stop.clear()
        _thread = threading.Thread(target=run, kwargs={"again": again}, name=THREAD, daemon=True)
        _thread.start()
        return "started"


def stop() -> None:
    """Ask the thread to stop after the batch it is on."""
    _stop.set()


__all__ = ["START_AFTER", "describe", "done", "run", "running", "sizes", "start", "state",
           "state_path", "stop"]
