"""Every operation on a dataset, written down step by step, for the debugger.

Petar asked to SEE how facts are stored, edited and retrieved. So storing an
item, editing it, deleting it, a question, a layer update, a map rebuild and an
evaluation are each a `trace`, and each part of the work is a `trace_step` with
what went in, what came out, how long it took and what it cost. Every model call
and every decision call inside a step is a `call` row as well, with its backend,
model, version, tokens, time and the items it held (D66: deletion can find the
calls that held an item).

The page reads these as they are written, so a step appears while the next one
is still running.
"""
from __future__ import annotations

import contextlib
import time

from . import db
from .db import Json


class Step:
    def __init__(self, trace: "Trace", name: str, title: str) -> None:
        self.trace = trace
        self.name = name
        self.title = title
        self.data: dict = {}
        self.cost = 0.0
        self.started = time.time()
        self.id = db.value(
            "INSERT INTO synapse.trace_step (trace_id, dataset_id, seq, name, title, status, data) "
            "VALUES (%s, %s, %s, %s, %s, 'running', '{}'::jsonb) RETURNING id",
            (trace.id, trace.dataset_id, trace.next_seq(), name, title))

    def save(self, status: str = "running") -> None:
        db.run("UPDATE synapse.trace_step SET data = %s::jsonb, status = %s, cost_usd = %s, ms = %s "
               "WHERE id = %s",
               (Json(self.data), status, round(self.cost, 6),
                int((time.time() - self.started) * 1000), self.id))


class Trace:
    """One operation, its steps and its calls."""

    def __init__(self, dataset_id: str, kind: str, title: str, *, by: str = "page",
                 item_id: str | None = None, trace_id: str | None = None) -> None:
        self.dataset_id = str(dataset_id)
        self.kind = kind
        self.cost = 0.0
        self.started = time.time()
        self._seq = 0
        self.step_now: Step | None = None
        self.summary: dict = {}
        if trace_id:
            self.id = trace_id
            self._seq = int(db.value("SELECT coalesce(max(seq), 0) FROM synapse.trace_step "
                                     "WHERE trace_id = %s", (trace_id,)) or 0)
            got = db.row("SELECT cost_usd FROM synapse.trace WHERE id = %s", (trace_id,))
            self.cost = float((got or {}).get("cost_usd") or 0)
            db.run("UPDATE synapse.trace SET status = 'running' WHERE id = %s", (trace_id,))
        else:
            self.id = db.value(
                "INSERT INTO synapse.trace (dataset_id, kind, item_id, title, by) "
                "VALUES (%s, %s, %s, %s, %s) RETURNING id",
                (self.dataset_id, kind, item_id, title, by))

    def next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def set_item(self, item_id: str) -> None:
        db.run("UPDATE synapse.trace SET item_id = %s WHERE id = %s", (item_id, self.id))

    def set_title(self, title: str) -> None:
        db.run("UPDATE synapse.trace SET title = %s WHERE id = %s", (title[:300], self.id))

    @contextlib.contextmanager
    def step(self, name: str, title: str):
        step = Step(self, name, title)
        outer, self.step_now = self.step_now, step
        try:
            yield step
        except Exception as exc:
            step.data.setdefault("error", f"{type(exc).__name__}: {exc}")
            step.save("failed")
            raise
        else:
            step.save("skipped" if step.data.get("skipped") else "done")
        finally:
            self.step_now = outer

    def call(self, *, kind: str, purpose: str, backend: str = "", model: str = "",
             version: str = "", ms: int | None = None, tokens_in: int = 0, tokens_out: int = 0,
             cost: float = 0.0, items=(), ok: bool = True, error: str = "") -> dict:
        """One model, decision, embedding or database call inside the current step."""
        cost = float(cost or 0.0)
        db.run("INSERT INTO synapse.call (dataset_id, trace_id, kind, purpose, backend, model, version, "
               "ms, tokens_in, tokens_out, cost_usd, items, ok, error) "
               "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::uuid[], %s, %s)",
               (self.dataset_id, self.id, kind, purpose, backend, model, version, ms,
                int(tokens_in or 0), int(tokens_out or 0), round(cost, 6),
                [str(i) for i in items if i], ok, error[:1000]))
        self.cost += cost
        if self.step_now is not None:
            self.step_now.cost += cost
            calls = self.step_now.data.setdefault("calls", [])
            calls.append({"kind": kind, "purpose": purpose, "backend": backend, "model": model,
                          "version": version, "ms": ms, "in": tokens_in, "out": tokens_out,
                          "cost": round(cost, 6), "ok": ok, "error": error[:300]})
            self.step_now.save()
        db.run("UPDATE synapse.trace SET cost_usd = %s WHERE id = %s", (round(self.cost, 6), self.id))
        return {"cost": cost, "ms": ms}

    def finish(self, status: str = "done", **summary) -> None:
        self.summary.update(summary)
        # From the trace's own start, which for an operation finished by a
        # job is the moment code's part began, not the moment the job did.
        db.run("UPDATE synapse.trace SET status = %s, finished_at = now(), "
               "ms = (extract(epoch FROM now() - started_at) * 1000)::int, cost_usd = %s, "
               "summary = summary || %s::jsonb WHERE id = %s",
               (status, round(self.cost, 6), Json(self.summary), self.id))
