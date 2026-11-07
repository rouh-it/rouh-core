"""A task's status and its summary: kept in Rouh's database, and nowhere else.

Petar, 6 October 2026, by voice: "well we want the database to be the source. and we don't
want 2 copies of the same thing. so if we have status and summary in db, don't have that in
the files." Until that day both were lines in a file in each task's folder, which Rouh copied
into the task's row whenever it read the tree again (`conversations.reconcile`). Since then:

- **The row is the only copy.** `task.status` holds the workspace's five words
  (not-started, in-progress, waiting, stopped, done) and `task.state` what they come to in
  three; `task.summary` the 50 to 90 words. No file carries either, nothing reads one
  there, and nothing writes one back.
- **Every change goes through the store's `update_task`**, which writes it down in
  `task_change` with when, who, the run it came from, and the old and new value. That is
  the history git used to give.
- **There is one way in from outside Rouh**, `rouh-task` (`bin/rouh-task` in Rouh's code), for a job, a run of the
  one program, a terminal on this machine, and a copy of the workspace on another computer:

      rouh-task status 58 waiting
      rouh-task summary 58 "What it is. Where it stands. What is open."
      rouh-task show 58

  On this machine it posts to `/internal/task`, which only this machine may reach
  (`rouh/web/taskapi.py`); from anywhere else to `/api/task` with a key made by
  `manage.py task_token add`. When it cannot reach Rouh it says so and fails. It never
  writes a file instead.
- **A task Rouh has no row for yet** - one a job made in its own checkout and has not
  landed - is answered with the id its `.object.json` gives: the change is kept as pending
  against that id (`task_change.pending`) and made the moment a row with that id is taken
  in (`apply_pending`).
- **`_tasks.md` is a view** of the rows, written again after every change
  (`rouh/tasklist.py`). It is for reading.

A task's steps, groups, arrows, tags and question are its meta, kept in its row in the same
way (`rouh/taskmeta.py`).
"""
from __future__ import annotations

import contextlib
import contextvars
import logging
import re
import time
from pathlib import Path

from .models.objects import STATUS_STATE, TASK_STATUSES

log = logging.getLogger(__name__)

STATUSES = TASK_STATUSES

#: The other words for a status the workspace has always understood (`pages._STATUS_WORDS`),
#: and the ones a person or a model is likely to say.
WORDS = {"new": "not-started", "to-do": "not-started", "todo": "not-started",
         "not-started": "not-started", "open": "not-started",
         "started": "in-progress", "working": "in-progress", "doing": "in-progress",
         "in-progress": "in-progress",
         "waiting-on-you": "waiting", "waiting-on-owner": "waiting",
         "waiting-on-petar": "waiting",   # what files written before 20 October 2026 may say
         "blocked": "waiting",
         "paused": "stopped", "stopped": "stopped",
         "finished": "done", "complete": "done", "completed": "done", "done": "done"}

#: How long a summary may be, in words, before it is refused. The workspace asks for 50
#: to 90; this is the line past which it is plainly the task's notes, not its summary.
MOST_WORDS = 150

_ACTING: contextvars.ContextVar[tuple[str, str] | None] = contextvars.ContextVar(
    "taskrecord_acting", default=None)


class Refused(ValueError):
    """The change was not made, and the message says why in words a person can act on."""


def word(raw) -> str:
    """A status in the five words, from any of the ways it is written, or ""."""
    if not isinstance(raw, str):
        return ""
    key = re.sub(r"[\s_]+", "-", raw.strip().lower())
    key = WORDS.get(key, key)
    return key if key in STATUSES else ""


def tidy_summary(text: str) -> str:
    """A summary's lines stripped, with no blank line at either end or two in a row."""
    lines = [line.strip() for line in str(text or "").replace("\r", "").split("\n")]
    out: list[str] = []
    for line in lines:
        if line or (out and out[-1]):
            out.append(line)
    while out and not out[-1]:
        out.pop()
    return "\n".join(out)


@contextlib.contextmanager
def acting(by: str, run: str = ""):
    """Every task change inside this is written down as made by `by`, from `run`."""
    token = _ACTING.set((str(by or ""), str(run or "")))
    try:
        yield
    finally:
        _ACTING.reset(token)


def who_is_acting(by: str | None = None, run: str | None = None) -> tuple[str, str]:
    """Who a change is by, and the run it came from, for its line in `task_change`."""
    now = _ACTING.get()
    if by is None:
        by = now[0] if now else "rouh"
    if run is None:
        run = now[1] if now else ""
    return str(by or "rouh"), str(run or "")


def _store():
    from . import objects

    return objects.shared_store(even_when_off=True)


def find(st, ref, *, ident: str = "", folder: str = ""):
    """The task row `ref` names, or None.

    `ref` is what a person or an agent would say: a number ("58"), a step's two numbers
    ("58-03"), an id ("task-58" or a uuid), or a folder in the workspace
    ("work/acme/19.pricing", with or without "workspace/" in front or a slash behind).
    `ident` and `folder`, when the caller could read them off the checkout it is in, are
    tried first, because they cannot be mistaken for anything else.
    """
    if st is None:
        return None
    for one in (ident, str(ref or "").strip()):
        if one:
            row = st.get_task(one)
            if row is not None:
                return row
    rows = None

    def every():
        nonlocal rows
        if rows is None:
            rows = st.list_tasks(limit=1_000_000)
        return rows

    for path in (folder, str(ref or "")):
        path = _folder_of(path)
        if path:
            found = next((r for r in every() if r.folder == path), None)
            if found is not None:
                return found
    said = str(ref or "").strip()
    if re.fullmatch(r"\d{1,4}", said):
        return next((r for r in every() if r.number == int(said)), None)
    step = re.fullmatch(r"(\d{1,4})[-.](\d{1,3})", said)
    if step:
        task = next((r for r in every() if r.number == int(step.group(1))), None)
        if task is None or not task.folder:
            return None
        lead = f"{int(step.group(1)):02d}-{int(step.group(2)):02d}."
        found = [r for r in every() if r.folder.startswith(task.folder + "/")
                 and r.folder.rsplit("/", 1)[-1].startswith(lead)]
        # Two steps can carry one pair of numbers - a goal numbers a step's parts inside
        # the task like its steps - and a guess between them is a change to the wrong one.
        return found[0] if len(found) == 1 else None
    return None


def _folder_of(path: str) -> str:
    """A folder as the rows name it: relative to the workspace, no slashes at either end."""
    path = str(path or "").strip().strip("/")
    if path.startswith("workspace/"):
        path = path[len("workspace/"):]
    return path if "/" in path else ""


def change(ref, *, status: str | None = None, summary: str | None = None,
           by: str, run: str = "", ident: str = "", folder: str = "") -> dict:
    """Change a task's status, its summary, or both, in its row. What happened, in words.

    Returns {"ok", "did", "task": {...as it now stands}} or {"ok", "did", "pending": True}
    for a task Rouh has no row for yet but whose id the caller gave. Raises `Refused` for
    anything it will not do: no such task, a word that is not a status, an empty or
    overlong summary.
    """
    if status is None and summary is None:
        raise Refused("Say what to change: a status, a summary, or both.")
    if status is not None:
        said = status
        status = word(status)
        if not status:
            raise Refused(f"{said!r} is not a status. A task is one of: {', '.join(STATUSES)}.")
    if summary is not None:
        summary = tidy_summary(summary)
        if not summary:
            raise Refused("A summary cannot be empty: say what the task is, where it stands "
                          "and what is open, in 50 to 90 words.")
        words = len(summary.split())
        if words > MOST_WORDS:
            raise Refused(f"That summary is {words} words, and a summary is 50 to 90. "
                          "What does not fit belongs in the task's AGENTS.md.")
    st = _store()
    if st is None:
        raise Refused("Rouh has no database here, so there is nowhere to keep it.")
    row = find(st, ref, ident=ident, folder=folder)
    if row is None:
        if ident and re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", ident):
            return _hold(ident, status, summary, by=by, run=run, ref=ref)
        raise Refused(f"Rouh has no task {ref}. Give its number, its folder, or run this "
                      "inside its folder so its .object.json can be read.")
    fields = {}
    if status is not None and status != row.status:
        fields["status"] = status
    if summary is not None and summary != row.summary:
        fields["summary"] = summary
    name = _name(row)
    if not fields:
        return {"ok": True, "did": f"{name} already says that", "task": view(row)}
    now = st.update_task(row.id, by=by, run=run, **fields) or row
    _changed()
    did = []
    if "status" in fields:
        did.append(f"{name} is {now.status} now (it was {row.status})")
    if "summary" in fields:
        did.append(f"{name} has a new summary")
    return {"ok": True, "did": "; ".join(did), "task": view(now)}


def _hold(ident: str, status, summary, *, by: str, run: str, ref) -> dict:
    """A change for a task that is not a row yet, kept against its id until it is."""
    from .models import TaskChange

    now = time.time()
    made = []
    for field, value in (("status", status), ("summary", summary)):
        if value is not None:
            made.append(TaskChange(task_id=ident, field=field, new=value, at=now,
                                   by=by, run=run, pending=True))
    TaskChange.objects.bulk_create(made)
    log.info("held %s change(s) for %s, which has no row yet", len(made), ident)
    return {"ok": True, "pending": True,
            "did": (f"Rouh has no row for {ref} yet, so the change is kept against its id "
                    f"{ident} and made the moment the task reaches Rouh")}


def apply_pending(st, task_id: str) -> int:
    """Make the changes kept for a task that had no row, now that it has one. How many."""
    from .models import TaskChange

    held = list(TaskChange.objects.filter(task_id=task_id, pending=True).order_by("at", "id"))
    if not held:
        return 0
    latest: dict[str, TaskChange] = {}
    for one in held:
        latest[one.field] = one
    for field, one in latest.items():
        st.update_task(task_id, by=one.by, run=one.run, **{field: one.new})
    TaskChange.objects.filter(id__in=[one.id for one in held]).delete()
    log.info("made %s change(s) held for %s", len(latest), task_id)
    _changed()
    return len(latest)


def view(row) -> dict:
    """A task as `rouh-task show` prints it."""
    return {"id": row.id, "number": row.number, "title": row.title, "folder": row.folder,
            "status": row.status, "state": row.state, "summary": row.summary,
            "archived": row.archived_at is not None}


def history(task_id: str, limit: int = 20) -> list[dict]:
    """The latest changes to a task's status and summary, newest first."""
    from .models import TaskChange

    rows = (TaskChange.objects.filter(task_id=task_id, pending=False)
            .order_by("-at", "-id")[:max(1, int(limit))])
    return [{"field": r.field, "old": r.old, "new": r.new, "at": r.at, "by": r.by,
             "run": r.run} for r in rows]


def statuses() -> dict[str, str]:
    """Every task's and step's status, by id, in one read."""
    from .models import Task

    try:
        return dict(Task.objects.values_list("id", "status"))
    except Exception:
        log.exception("the tasks' statuses could not be read")
        return {}


def status_at(folder: Path | str, root: str | Path) -> str:
    """The status of the task or step in this folder of the workspace, or "" when no row is."""
    from .models import Task

    try:
        rel = Path(folder).resolve().relative_to(Path(root).resolve()).as_posix()
    except (ValueError, OSError):
        return ""
    try:
        got = Task.objects.filter(folder=rel).values_list("status", flat=True).first()
    except Exception:
        log.exception("the status of %s could not be read", rel)
        return ""
    return str(got or "")


def state_of(status: str) -> str:
    """What a five-word status comes to in three."""
    return STATUS_STATE.get(word(status) or status, "open")


def strip(meta: dict) -> dict:
    """A task's meta with no status and no summary in it, for writing back.

    Every writer of a meta goes through this (`rouh/taskmeta.py`), so the status and the
    summary, which are the row's own columns, are never kept twice.
    """
    if not isinstance(meta, dict):
        return meta
    out = {k: v for k, v in meta.items() if k not in ("status", "summary")}
    steps = out.get("steps")
    if isinstance(steps, dict):
        out["steps"] = {k: ({kk: vv for kk, vv in v.items() if kk != "status"}
                            if isinstance(v, dict) else v) for k, v in steps.items()}
    return out


def _name(row) -> str:
    if row.number is not None:
        return f"Task {row.number}"
    return "Step " + (row.folder.rsplit("/", 1)[-1] if row.folder else row.id)


def _changed() -> None:
    """`_tasks.md` written again, since what it says about a task may have moved."""
    from . import tasklist

    try:
        tasklist.changed()
    except Exception:
        log.exception("_tasks.md could not be written again")


# --- the key another computer uses ----------------------------------------------------------

#: What every key starts with, so one pasted into the wrong place is recognisable.
TOKEN_PREFIX = "rouh_task_"


def _hash(raw: str) -> str:
    import hashlib

    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def make_token(user_id: str, org_id: str, name: str) -> str:
    """A new key for `/api/task`, for one person. The key itself; only its hash is kept."""
    import secrets

    from .models import TaskToken

    name = " ".join(str(name or "").split())
    if not name:
        raise Refused("Give the key a name that says where it lives, such as laptop.")
    if TaskToken.objects.filter(user_id=str(user_id), name=name, revoked_at__isnull=True).exists():
        raise Refused(f"There is already a key called {name}; revoke it first.")
    raw = TOKEN_PREFIX + secrets.token_urlsafe(32)
    TaskToken.objects.create(user_id=str(user_id), org_id=str(org_id), name=name,
                             token_hash=_hash(raw), created_at=time.time())
    return raw


def token_owner(raw: str):
    """The live key this is, marked as used now, or None."""
    from .models import TaskToken

    raw = str(raw or "").strip()
    if not raw.startswith(TOKEN_PREFIX):
        return None
    row = TaskToken.objects.filter(token_hash=_hash(raw), revoked_at__isnull=True).first()
    if row is None:
        return None
    TaskToken.objects.filter(id=row.id).update(last_used_at=time.time())
    return row


def revoke_token(user_id: str, name: str) -> int:
    from .models import TaskToken

    return TaskToken.objects.filter(user_id=str(user_id), name=name,
                                    revoked_at__isnull=True).update(revoked_at=time.time())
