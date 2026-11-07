"""Archiving a task or a subtask, and bringing it back.

Petar, 29 September 2026 (fr_08e097dbe815): "I think I need an archive on the
task browser. At least on top level tasks ... After we have some archived
tasks, we can click archive and see and search those instead of the live
ones. Ideally, we should also have archive for the sub-tasks ... I imagine
everything that belongs to a sub task also gets archived along with it, so we
don't have left over artifacts."

**Archiving hides and deletes nothing.** The task keeps its row, its folder,
its chats and its pages; it leaves the live lists - the task browser, a task's
own page's Subtasks, the rail's tasks and the pickers drawn from them - and is
kept in the task browser's Archive, and under Archived on its parent's page,
where it can be opened, searched and brought back.

**What goes with it is everything under it.** A task's subtasks, however deep,
are archived in the same instant and carry the same moment in `archived_at`.
That moment is what brings back exactly what went: unarchiving a task brings
back the subtasks archived with it and leaves one that was archived on its own
before, which is still archived as the person left it. What else a task holds -
its chats, its runs, its cards, its files - is reached only through the task
and its page, so it goes out of sight with the task without being touched.
"""
from __future__ import annotations

import logging
import time

from . import objects, owning, tasklist

log = logging.getLogger(__name__)


def _store() -> objects.ObjectStore | None:
    """The one object store, as the task browser opens it (`objectindex._store`)."""
    return objects.shared_store(even_when_off=True)


def archived(st: objects.ObjectStore | None = None) -> dict[str, float]:
    """Every archived task and step by id, with when; {} with no store."""
    st = st if st is not None else _store()
    if st is None:
        return {}
    try:
        return st.archived_tasks()
    except Exception:                        # pragma: no cover - reported
        log.exception("which tasks are archived could not be read")
        return {}


def archived_folders(st: objects.ObjectStore | None = None) -> set[str]:
    """The folder of every archived task and step, as the workspace names it; empty with no store.

    For the lists read off the folders rather than the rows: the canvas's
    breadcrumb lists a task's steps, and every task, out of `rouh/steps.py`,
    and an archived one is left out of its menu like everywhere else.
    """
    st = st if st is not None else _store()
    kept = archived(st)
    if not kept:
        return set()
    try:
        return {str(row["folder"]) for row in st.objects()
                if row["type"] == "task" and row["id"] in kept and row.get("folder")}
    except Exception:                        # pragma: no cover - reported
        log.exception("where the archived tasks are could not be read")
        return set()


def archive(task_id: str, on: bool = True) -> dict:
    """Archive one task and everything under it, or bring it back.

    What it answers is what the task browser's `change` answers: ``ok``, and
    ``did`` or ``why`` in words for the person.
    """
    st = _store()
    row = st.get_task(task_id) if st is not None and task_id else None
    if row is None:
        return {"ok": False, "why": "There is no task here with that id."}
    name = f"{row.number} · {row.title}" if row.number is not None else row.title
    kept = archived(st)
    under = owning._tasks_under(st, row.id)
    if on:
        if row.id in kept:
            return {"ok": True, "did": f"{name} was already archived"}
        now = time.time()
        st.set_archived([row.id] + [k for k in under if k not in kept], now)
        tasklist.changed()
        return {"ok": True, "did": f"Archived {name}"}
    at = kept.get(row.id)
    if at is None:
        return {"ok": True, "did": f"{name} is not archived"}
    st.set_archived([row.id] + [k for k in under if kept.get(k) == at], None)
    tasklist.changed()
    return {"ok": True, "did": f"Brought {name} back"}
