"""Storing many items at once: an import (Petar, 3 October 2026: 100,000 emails in hours, not a week).

One item stored after another waited for each one's model part, about 7 seconds
an item, so 100,000 emails would have taken eight days. Here:

- **Code's part** of many items runs at once, `import_concurrency` at a time
  (16 to start), each item tried up to `import_retries` times when it fails on
  something that may pass (a deadlock, a person made by two items at once, a
  dropped connection). An item refused for what it is (a deleted key, say) is
  not tried again. Each is searchable by its words the moment it is stored.
- **The model's part** (embedding, link candidates, the X-ray and its judgement
  links) goes on the queue's backfill lane (`worker`), which never takes a
  slot live mail needs. With `wait`, this process adds the same number of slots
  of its own (`worker.drain`), a batch at a time, so the import is done when
  this returns; Rouh's own worker takes any it leaves. One whose model part
  failed is queued again, up to the same number of tries.
- **The day's spend cap** (`import_cap_usd`): no new item is started once the
  organisation has spent that much on Synapse today, and the queue holds the
  backfill until tomorrow. A rerun skips what is stored, so it carries on.

A unit is a list of payloads stored in order, one after another: an email,
then its files, so each file's `attached` link finds its email.
"""
from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from django.db import connection

from . import datasets, db, ingest, worker

log = logging.getLogger("rouh.synapse.batch")


def _transient(exc: Exception) -> bool:
    """Worth another try: anything but a mistake in what was sent."""
    return not isinstance(exc, (ValueError, TypeError, KeyError))


def store_many(ds: dict, units: list[list[dict]], *, by: str = "import", concurrency: int | None = None,
               retries: int | None = None, wait: bool = True, progress=None, lane: str = "backfill",
               mind_cap: bool = True) -> dict:
    """Store every unit, many at once. Returns a report: one row per payload, in the order given,
    with `ok`, `item`, `trace`, `tries` and `why` or `error`, and the totals.

    `lane` is where the model's parts go: the backfill lane for an import, the live one for an
    email that just arrived (`gmailsync`). `mind_cap` False stores even past the day's spend cap,
    for a caller the queue already holds to it (a backfill job is held at the cap when taken)."""
    s = datasets.settings(ds)
    concurrency = max(1, min(int(concurrency or s.get("import_concurrency", 16)), len(units) or 1))
    retries = max(1, int(retries or s.get("import_retries", 3)))
    cap = float(s.get("import_cap_usd", 100.0))
    org = str(ds["org_id"])
    began = time.time()
    spent_before = worker.spent_today(org)
    results: list[list[dict]] = [[] for _ in units]
    lock = threading.Lock()
    state = {"capped": mind_cap and spent_before >= cap, "checked": time.time(), "stored": 0, "storing": True}

    def over_cap() -> bool:
        if not mind_cap:
            return False
        with lock:
            if time.time() - state["checked"] < 10:
                return state["capped"]
            state["checked"] = time.time()
        capped = worker.spent_today(org) >= cap
        with lock:
            state["capped"] = state["capped"] or capped
        return capped

    def one(payload: dict) -> dict:
        rec = {"source_key": payload.get("source_key") or payload.get("key") or "", "tries": 0}
        for attempt in range(1, retries + 1):
            rec["tries"] = attempt
            began = db.value("SELECT now()")
            try:
                got = ingest.store(ds, payload, by=by, lane=lane)
                rec.update({"ok": bool(got.get("ok")), "item": str(got.get("item") or ""),
                            "trace": str(got.get("trace") or ""), "why": got.get("why") or "",
                            "attached_again": bool(got.get("attached")), "edited": bool(got.get("edited"))})
                rec.pop("error", None)
                return rec
            except Exception as exc:  # noqa: BLE001 - said in the report, and tried again when it may pass
                rec.update({"ok": False, "error": f"{type(exc).__name__}: {exc}"[:500]})
                connection.close()
                if not _transient(exc) or attempt == retries:
                    log.warning("Synapse import: %s failed after %s tries: %s", rec["source_key"], attempt, exc)
                    return rec
                # What this try left half made (its row written, code's part not finished) goes, so the next
                # try stores it whole instead of finding it and calling it an edit with nothing changed.
                if rec["source_key"]:
                    db.run("DELETE FROM synapse.item WHERE dataset_id = %s AND source = %s AND source_key = %s "
                           "AND status = 'stored' AND stored_at >= %s",
                           (ds["id"], str(payload.get("source") or "lab")[:80], rec["source_key"][:300], began))
                time.sleep(min(30.0, 0.5 * 2 ** attempt))
        return rec

    def unit(i: int) -> None:
        try:
            if over_cap():
                results[i] = [{"source_key": p.get("source_key") or "", "ok": False, "skipped": "cap",
                               "why": f"today's spend cap of ${cap:g} was reached before it started"}
                              for p in units[i]]
                return
            for p in units[i]:
                results[i].append(one(p))
            with lock:
                state["stored"] += 1
                n = state["stored"]
            if progress is not None:
                progress("stored", n, len(units))
        finally:
            connection.close()

    drained = {"done": 0}

    def drain_while_storing() -> None:
        # Model parts start as soon as their items are stored, beside the storing.
        try:
            while True:
                still = state["storing"]
                got = worker.drain(ds["id"], concurrency)
                drained["done"] += got["done"]
                if not still and not got["done"]:
                    return
                if not got["done"]:
                    time.sleep(1)
        finally:
            connection.close()

    drainer = threading.Thread(target=drain_while_storing, name="synapse-import-drain") if wait else None
    if drainer:
        drainer.start()
    with ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="synapse-import") as pool:
        list(pool.map(unit, range(len(units))))
    stored_s = time.time() - began
    state["storing"] = False
    if drainer:
        drainer.join()
    rows = [r for rs in results for r in rs]
    requeued = 0
    if wait:
        # A model part that failed (a model that would not answer, say) is queued again.
        for _ in range(retries - 1):
            items = [r["item"] for r in rows if r.get("ok") and r.get("item")]
            failed = [r["id"] for r in db.rows("SELECT id FROM synapse.item WHERE dataset_id = %s AND id = ANY(%s::uuid[]) "
                                               "AND status = 'failed'", (ds["id"], items or ingest.search.NO_IDS))]
            if not failed:
                break
            for item_id in failed:
                ingest.enqueue(ds["id"], "ingest", item_id=item_id, lane="backfill", priority=4,
                               payload={"again": "its model part failed during an import"})
            requeued += len(failed)
            drained["done"] += worker.drain(ds["id"], concurrency)["done"]
    traces = [r["trace"] for r in rows if r.get("trace")]
    cost = float(db.value("SELECT coalesce(sum(cost_usd), 0) FROM synapse.trace WHERE id = ANY(%s::uuid[])",
                          (traces or ingest.search.NO_IDS,)) or 0) if traces else 0.0
    status = {r["id"]: r["status"] for r in db.rows(
        "SELECT id, status FROM synapse.item WHERE dataset_id = %s AND id = ANY(%s::uuid[])",
        (ds["id"], [r["item"] for r in rows if r.get("item")] or ingest.search.NO_IDS))}
    for r in rows:
        if r.get("item"):
            r["status"] = status.get(r["item"], "")
    # The caller's connection is the caller's to give back: a mail job holds a session lock on
    # it for the whole message (`sources/gmailsync._held`), and closing it here let that go
    # half way through (task 137). A thread handed this by `asyncio.to_thread` gives its
    # connection back when the call ends (`rouh/dbwork.py`).
    return {"rows": rows, "units": len(units), "payloads": len(rows),
            "ok": sum(1 for r in rows if r.get("ok")), "failed": sum(1 for r in rows if not r.get("ok") and not r.get("skipped")),
            "skipped_cap": sum(1 for r in rows if r.get("skipped") == "cap"),
            "ready": sum(1 for r in rows if r.get("status") == "ready"),
            "model_failed": sum(1 for r in rows if r.get("status") == "failed"),
            "requeued": requeued, "model_parts_run_here": drained["done"], "concurrency": concurrency,
            "retries": retries, "store_s": round(stored_s, 2), "total_s": round(time.time() - began, 2),
            "cost_usd": round(cost, 6), "spent_today_before": round(spent_before, 6), "cap_usd": cap,
            "capped": state["capped"]}
