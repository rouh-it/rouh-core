"""The queue of Synapse's background work (D52, D61).

The spec has one worker service, `rouh-memory-worker`, taking jobs with
`FOR UPDATE SKIP LOCKED`. In this lab the same loop runs inside Rouh's own
process, in a thread, so nothing new has to be installed on the server; the
jobs, their table and the locking are the spec's. A job a restart cut off is
taken again (its lock is older than ten minutes), up to three tries.

Two lanes (migration 0071). `live` is everything a person or live mail is
waiting on, and has its own `WORKERS` slots. `backfill` is an import's model
parts: they run on slots of their own (`BACKFILL_WORKERS` here, and as many
more as an import adds with `drain`), taken a batch at a time, so a backfill
of 100,000 emails never takes a slot a live item needs and never queues in
front of one. A dataset whose organisation has spent its `import_cap_usd` today
has its backfill held until tomorrow.

Kinds: `ingest` (the model's part of storing), `reingest` (an edit's), `embed`
(a person or topic item's vector), `layer`, `map`, `eval`, `seed`,
`revector` (a share of moving a dataset's vectors to another model, or sweeping
up after one, `vectors.py`), `icloud_push`/`icloud_delete` (`contacts.py`), and
`mail_add`/`mail_delete`/`mail_labels` (one Gmail message, `gmailsync.py`), and `dream` (a night of
dreaming, on the backfill lane, `dreaming.py`).
"""
from __future__ import annotations

import logging
import os
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from django.db import connection

from . import db

log = logging.getLogger("rouh.synapse.worker")

WORKERS = 4
BACKFILL_WORKERS = int(os.environ.get("SYNAPSE_BACKFILL_WORKERS") or 4)
MAX_TRIES = 3
_started = False
_lock = threading.Lock()
_wake = threading.Event()
_pool: ThreadPoolExecutor | None = None
_backfill: ThreadPoolExecutor | None = None
_busy = 0
_busy_backfill = 0
_me = f"{socket.gethostname()}:{os.getpid()}"


def poke() -> None:
    _wake.set()


def release_dead() -> int:
    """Jobs locked by a process of this machine that is gone, given back now rather than when their
    lock is ten minutes old (card 1125, change 5): a restart of Rouh no longer holds an item's links
    back for ten minutes. The try it was on is not counted. Returns how many were given back."""
    host = socket.gethostname()
    mine = db.rows("SELECT DISTINCT locked_by FROM synapse.job WHERE done_at IS NULL AND locked_by LIKE %s",
                   (host + ":%",))
    dead = []
    for r in mine:
        parts = str(r["locked_by"]).split(":")
        try:
            pid = int(parts[1])
        except (IndexError, ValueError):
            continue
        if pid == os.getpid():
            continue
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            dead.append(r["locked_by"])
        except PermissionError:
            continue  # alive, another user's
    if not dead:
        return 0
    n = db.run("UPDATE synapse.job SET locked_by = NULL, locked_at = NULL, tries = greatest(0, tries - 1), "
               "error = 'given back: the worker that held it had stopped' WHERE done_at IS NULL "
               "AND locked_by = ANY(%s)", (dead,))
    log.info("Synapse gave back %s jobs held by workers that had stopped: %s", n, ", ".join(dead))
    return n


def start() -> None:
    """Start the loop once per process."""
    global _started, _pool, _backfill
    with _lock:
        if _started:
            return
        _started = True
        _pool = ThreadPoolExecutor(max_workers=WORKERS, thread_name_prefix="synapse-job")
        _backfill = ThreadPoolExecutor(max_workers=BACKFILL_WORKERS, thread_name_prefix="synapse-backfill")
        threading.Thread(target=_loop, name="synapse-worker", daemon=True).start()
    # Gmail kept in Synapse Master, read every minute and on Gmail's push (`gmailsync.py`).
    from . import gmailsync

    gmailsync.start()
    # Every calendar event kept in Synapse Master, read every minute (`calsync.py`).
    from . import calsync

    calsync.start()
    # Every meeting in the meeting library kept in Synapse Master (`meetings.py`).
    from . import meetings

    meetings.start()


#: Jobs of one item that never run side by side: each writes the item's X-ray passage, links and
#: status, and two at once collided on the X-ray passage (card 1125's benchmark, 4 October 2026).
ONE_AT_A_TIME = "('ingest', 'reingest')"


def _claim(lane: str = "live", n: int = 1, dataset_id: str | None = None, me: str | None = None) -> list[dict]:
    """Up to `n` jobs of one lane, locked for this worker; `dataset_id` keeps to one dataset.

    An item's ingest or reingest is taken only when none of that item is running and no older one is
    waiting that could run now, so one item's model part never runs twice at once (the others wait
    their turn; one held until tomorrow, or out of tries, holds nothing back)."""
    got = db.rows(
        "UPDATE synapse.job SET locked_by = %s, locked_at = now(), started_at = coalesce(started_at, now()), "
        "tries = tries + 1 WHERE id IN ("
        " SELECT j.id FROM synapse.job j WHERE j.done_at IS NULL AND j.lane = %s AND j.not_before <= now() "
        " AND j.tries < %s AND (j.locked_by IS NULL OR j.locked_at < now() - interval '10 minutes') "
        " AND (%s::uuid IS NULL OR j.dataset_id = %s::uuid) "
        f" AND NOT (j.kind IN {ONE_AT_A_TIME} AND j.item_id IS NOT NULL AND EXISTS ("
        "   SELECT 1 FROM synapse.job o WHERE o.dataset_id = j.dataset_id AND o.item_id = j.item_id "
        f"  AND o.kind IN {ONE_AT_A_TIME} AND o.done_at IS NULL AND o.id <> j.id AND "
        "   ((o.locked_by IS NOT NULL AND o.locked_at >= now() - interval '10 minutes') OR "
        f"   (o.id < j.id AND o.locked_by IS NULL AND o.not_before <= now() AND o.tries < {MAX_TRIES})))) "
        " ORDER BY j.priority, j.not_before, j.id FOR UPDATE SKIP LOCKED LIMIT %s) RETURNING *",
        (me or _me, lane, MAX_TRIES, dataset_id, dataset_id, int(n)))
    if lane == "backfill":
        got = [j for j in got if not _over_cap(j)]
    return got


_cap_seen: dict[str, tuple[float, bool]] = {}


def spent_today(org_id: str) -> float:
    """What Synapse has cost this organisation today, every dataset and every call."""
    return float(db.value("SELECT coalesce(sum(c.cost_usd), 0) FROM synapse.dataset d JOIN synapse.call c ON "
                          "c.dataset_id = d.id AND c.at >= date_trunc('day', now()) WHERE d.org_id = %s",
                          (org_id,)) or 0.0)


def _over_cap(job: dict) -> bool:
    """A backfill job of a dataset whose organisation is at today's cap goes back until tomorrow."""
    from . import datasets

    ds = datasets.by_id(job["dataset_id"])
    if ds is None:
        return False
    cap = float(datasets.settings(ds).get("import_cap_usd", 100.0))
    key = str(ds["org_id"])
    seen = _cap_seen.get(key)
    if seen is None or time.time() - seen[0] > 30:
        seen = (time.time(), spent_today(key) >= cap)
        _cap_seen[key] = seen
    if not seen[1]:
        return False
    db.run("UPDATE synapse.job SET locked_by = NULL, tries = tries - 1, "
           "not_before = date_trunc('day', now()) + interval '1 day', "
           "error = %s WHERE id = %s", (f"held until tomorrow: today's backfill spend cap of ${cap:g} is reached",
                                        job["id"]))
    return True


FOLD_EVERY = 10.0
_folded = 0.0


def fold() -> int:
    """The word counts' deltas folded into their totals (migration 0071); one process at a time does it."""
    global _folded
    _folded = time.time()
    try:
        return int(db.value("SELECT synapse.term_fold()") or 0)
    except Exception:  # noqa: BLE001 - a schema without it, or a moment's trouble: next time
        log.exception("could not fold Synapse's word counts")
        return 0


#: How often the loop gives back jobs of stopped workers: at once when it starts, then this often.
RELEASE_EVERY = 300.0
_released = 0.0


def _release() -> None:
    global _released
    _released = time.time()
    try:
        release_dead()
    except Exception:  # noqa: BLE001 - next time
        log.exception("could not give back Synapse jobs of stopped workers")


def _loop() -> None:
    global _busy, _busy_backfill
    time.sleep(2)
    while True:
        try:
            if not db.ready():
                connection.close()
                time.sleep(30)
                continue
            if time.time() - _released > RELEASE_EVERY:
                _release()
            if time.time() - _folded > FOLD_EVERY:
                fold()
            from . import master
            if master.due():
                # Every person's Synapse Master kept in step with the tasks and everything in them,
                # on a thread of its own (`master.start_sync`).
                master.start_sync()
            took = 0
            if _busy < WORKERS:
                for job in _claim("live", WORKERS - _busy):
                    with _lock:
                        _busy += 1
                    _pool.submit(_run, job, "live")
                    took += 1
            if _busy_backfill < BACKFILL_WORKERS:
                for job in _claim("backfill", BACKFILL_WORKERS - _busy_backfill):
                    with _lock:
                        _busy_backfill += 1
                    _backfill.submit(_run, job, "backfill")
                    took += 1
            connection.close()
            if not took:
                _wake.wait(3.0 if (_busy < WORKERS and _busy_backfill < BACKFILL_WORKERS) else 1.0)
                _wake.clear()
        except Exception:  # noqa: BLE001 - the loop never dies
            log.exception("the Synapse worker loop stumbled")
            connection.close()
            time.sleep(5)


def _finish(job: dict) -> None:
    try:
        run_job(job)
        db.run("UPDATE synapse.job SET done_at = now(), locked_by = NULL, error = '' WHERE id = %s", (job["id"],))
    except Exception as exc:  # noqa: BLE001
        log.exception("Synapse job %s (%s) failed", job["id"], job["kind"])
        try:
            tries = int(job.get("tries") or 0)
            done = "now()" if tries >= MAX_TRIES else "NULL"
            # A backfill job waits longer each time, so a rate limit has time to pass.
            wait = 20 if job.get("lane") != "backfill" else 20 * 2 ** max(0, tries - 1)
            db.run(f"UPDATE synapse.job SET error = %s, locked_by = NULL, done_at = {done}, "
                   "not_before = now() + make_interval(secs => %s) WHERE id = %s",
                   (f"{type(exc).__name__}: {exc}"[:2000], wait, job["id"]))
        except Exception:  # noqa: BLE001
            pass
    finally:
        connection.close()


def _run(job: dict, lane: str = "live") -> None:
    global _busy, _busy_backfill
    try:
        _finish(job)
    finally:
        with _lock:
            if lane == "backfill":
                _busy_backfill -= 1
            else:
                _busy -= 1
        poke()


def drain(ds_id: str, concurrency: int, *, stop=None, on_batch=None) -> dict:
    """Run one dataset's backfill jobs here, `concurrency` at a time, a batch at a time, until none is
    left that may run now (an import adds its own slots this way; the live lane is never touched).

    `stop()` is asked between batches; `on_batch(n_done)` hears after each."""
    me = _me + ":drain"
    done = 0
    pool = ThreadPoolExecutor(max_workers=max(1, int(concurrency)), thread_name_prefix="synapse-drain")
    running: set = set()
    try:
        while True:
            if stop is not None and stop():
                break
            if time.time() - _released > RELEASE_EVERY:
                _release()
            if time.time() - _folded > FOLD_EVERY:
                fold()
            from . import master
            if master.due():
                # Every person's Synapse Master kept in step with the tasks and everything in them,
                # on a thread of its own (`master.start_sync`).
                master.start_sync()
            free = int(concurrency) - len(running)
            jobs = _claim("backfill", free, dataset_id=ds_id, me=me) if free > 0 else []
            connection.close()
            for job in jobs:
                running.add(pool.submit(_finish, job))
            if not running:
                if not db.value("SELECT 1 FROM synapse.job WHERE dataset_id = %s AND lane = 'backfill' AND "
                                "done_at IS NULL AND tries < %s AND not_before <= now() + interval '2 minutes' "
                                "LIMIT 1", (ds_id, MAX_TRIES)):
                    break
                connection.close()
                time.sleep(2)
                continue
            finished = {f for f in running if f.done()}
            if not finished:
                time.sleep(0.2)
                continue
            running -= finished
            done += len(finished)
            if on_batch is not None:
                on_batch(done)
    finally:
        for f in running:
            f.result()
        pool.shutdown(wait=True)
        connection.close()
    return {"done": done}


def run_job(job: dict) -> None:
    from . import datasets, evaluate, ingest, layers, mapping, seeds, vectors

    ds = datasets.by_id(job["dataset_id"])
    if ds is None:
        return
    kind = job["kind"]
    payload = job.get("payload") or {}
    if kind == "ingest":
        ingest.model_part(ds, job["item_id"], job.get("trace_id"))
    elif kind == "reingest":
        ingest.model_part_of_edit(ds, job["item_id"], job.get("trace_id"), payload)
    elif kind == "embed":
        s = datasets.settings(ds)
        ingest.embed_item(ds, job["item_id"], s, None, datasets.owner_of(ds))
    elif kind == "layer":
        layers.build(ds, payload)
    elif kind == "map":
        mapping.build(ds, payload.get("viewer"), why=payload.get("why") or "")
        for viewer in {r["viewer"] for r in db.rows("SELECT DISTINCT viewer FROM synapse.map WHERE dataset_id = %s",
                                                    (ds["id"],))} - {payload.get("viewer") or datasets.me(ds)}:
            mapping.build(ds, viewer, why="rebuilt with the owner's")
    elif kind == "eval":
        evaluate.execute(ds, payload["run"], payload.get("only") or [])
    elif kind == "seed":
        seeds.fill(ds, payload.get("example") or ds.get("example"), only=payload.get("only") or "")
    elif kind == "revector":
        vectors.work(ds)
    elif kind in ("icloud_push", "icloud_delete"):
        from . import contacts

        contacts.run_job(ds, job)
    elif kind in ("mail_add", "mail_delete", "mail_labels"):
        from . import gmailsync

        gmailsync.run_job(ds, job)
    elif kind == "dream":
        from . import dreaming

        dreaming.run(ds, by=payload.get("by") or "page", dream_id=payload.get("dream"))


def run_job_now(job_id: int) -> None:
    """Run one job here and now (the chat's tools wait for their own)."""
    job = db.row("UPDATE synapse.job SET locked_by = %s, locked_at = now(), started_at = coalesce(started_at, now()), "
                 "tries = tries + 1 WHERE id = %s "
                 "AND done_at IS NULL AND (locked_by IS NULL OR locked_at < now() - interval '10 minutes') RETURNING *",
                 (_me + ":now", job_id))
    if job is None:
        return
    try:
        run_job(job)
        db.run("UPDATE synapse.job SET done_at = now(), locked_by = NULL WHERE id = %s", (job_id,))
    except Exception as exc:  # noqa: BLE001
        db.run("UPDATE synapse.job SET error = %s, locked_by = NULL WHERE id = %s", (str(exc)[:2000], job_id))
        raise


def heartbeat(ds_id: str, kind: str) -> None:
    """A long job says it is still alive, so no other worker takes it again."""
    db.run("UPDATE synapse.job SET locked_at = now() WHERE dataset_id = %s AND kind = %s AND done_at IS NULL "
           "AND locked_by IS NOT NULL", (ds_id, kind))


def waiting(ds_id: str) -> dict:
    rows = db.rows("SELECT kind, lane, count(*) AS n FROM synapse.job WHERE dataset_id = %s AND done_at IS NULL "
                   "GROUP BY kind, lane", (ds_id,))
    failed = db.value("SELECT count(*) FROM synapse.job WHERE dataset_id = %s AND done_at IS NOT NULL AND error <> ''",
                      (ds_id,))
    waiting: dict[str, int] = {}
    backfill: dict[str, int] = {}
    for r in rows:
        waiting[r["kind"]] = waiting.get(r["kind"], 0) + r["n"]
        if r["lane"] == "backfill":
            backfill[r["kind"]] = r["n"]
    held = db.value("SELECT error FROM synapse.job WHERE dataset_id = %s AND done_at IS NULL AND lane = 'backfill' "
                    "AND error LIKE 'held until tomorrow%%' LIMIT 1", (ds_id,))
    return {"waiting": waiting, "backfill": backfill, "failed": failed or 0, "held": held or ""}
