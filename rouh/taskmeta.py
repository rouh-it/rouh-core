"""What a task keeps beside its status and its summary: its meta, in the task's row.

Petar, 22 October 2026: "that should not be in this file, should be in DB". A task's meta is
its steps' titles, descriptions and groups (`steps`), the `groups` and the `arrows` between
steps, its `tags`, a goal's `goal` and a goal step's `goal_step` block, a waiting task's
`question` and a cleared one's `question_cleared`, and the replies the owner sends from his own
mail (`sends_himself`).

- **The row is the only copy.** `task.meta` holds that whole value as JSON, None for a task
  that keeps none. Every reader and writer asks this module.
- **Every change is one locked read and write** (`ObjectStore.change_task_meta`), written
  down in `task_change` with when, who, the run it came from, and the old and new value.
- **There is one way in from outside Rouh**, `rouh-task meta` (`bin/rouh-task`), for a job, a
  run and a terminal, the same door as a task's status and summary (`rouh/taskrecord.py`).

The status and the summary are never put in here (`taskrecord.strip`).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)

#: When the database last could not be reached from this process, so a walk of many folders
#: with no database behind it (a workspace being built before its world has one) asks once
#: rather than waiting on every folder. Asked again after `RETRY` seconds.
_UNREACHED = [0.0]
RETRY = 30.0


def _store():
    import time

    from . import objects

    if time.monotonic() - _UNREACHED[0] < RETRY:
        return None
    try:
        st = objects.shared_store(even_when_off=True)
    except Exception:
        st = None
    if st is None:
        _UNREACHED[0] = time.monotonic()
    return st


def _root(root=None) -> str:
    if root:
        return str(root)
    from . import owning

    return owning._workspace() or ""


def _rel(folder, root: str) -> str:
    """The folder as the workspace names it, or "" when it is not in the workspace."""
    path = Path(str(folder))
    if path.is_absolute():
        if not root:
            return ""
        try:
            path = path.resolve().relative_to(Path(root).resolve())
        except (OSError, ValueError):
            return ""
    rel = "/".join(p for p in path.as_posix().split("/") if p and p != ".")
    return "" if ".." in rel.split("/") else rel


def task_id(folder, root=None) -> str:
    """The id of the task or step in this folder, or "" when no row is there.

    The row with that folder, and otherwise the id the folder's `.object.json` gives, when
    a row has it: a folder moved by hand is still the same task.
    """
    root = _root(root)
    rel = _rel(folder, root)
    st = _store()
    if st is None or not rel:
        return ""
    try:
        row = st.by_folder("task", rel)
    except Exception:
        log.exception("could not look up the task at %s", rel)
        return ""
    if row is not None:
        return row.id
    try:
        from . import objecttree

        said = objecttree.read_sidecar(Path(root) / rel, root) or {}
    except Exception:
        said = {}
    ident = str(said.get("id") or "") if said.get("type") == "task" else ""
    return ident if ident and st.get_task(ident) is not None else ""


def _clean(meta):
    from . import taskrecord

    return taskrecord.strip(meta) if isinstance(meta, dict) else None


# --- reading --------------------------------------------------------------------------------


def of(ident: str) -> dict | None:
    """One task's meta by its id: None when it has none."""
    st = _store()
    if st is None or not ident:
        return None
    return st.task_meta(ident)


def read(folder, root=None) -> dict | None:
    """The meta of the task in this folder, None when it has none or there is no task."""
    root = _root(root)
    ident = task_id(folder, root)
    return of(ident) if ident else None


def get(folder, root=None) -> dict:
    """The same, as a dict whatever there is: {} for none."""
    return read(folder, root) or {}


def has(folder, root=None) -> bool:
    """Whether the task in this folder keeps a meta at all: a step is noted only in a task
    that keeps a list of its steps."""
    return read(folder, root) is not None


def every() -> dict[str, dict]:
    """Every task's and step's meta, by id, in one read: for a list of all of them."""
    st = _store()
    return st.task_metas() if st is not None else {}


def by_folder() -> dict[str, dict]:
    """Every task's and step's meta, by the folder its row names."""
    st = _store()
    if st is None:
        return {}
    metas = st.task_metas()
    if not metas:
        return {}
    from .models import Task

    folders = dict(Task.objects.filter(id__in=list(metas)).values_list("id", "folder"))
    return {folders[i]: m for i, m in metas.items() if folders.get(i)}


def steps_of(folder, root=None) -> dict:
    """What a task's meta says about each of its steps, by folder name."""
    found = get(folder, root).get("steps")
    return found if isinstance(found, dict) else {}


def tags_of(meta) -> list[str]:
    """A meta's tags, in lower case."""
    tags = meta.get("tags") if isinstance(meta, dict) else None
    return [str(t).strip().lower() for t in tags if str(t).strip()] if isinstance(tags, list) else []


# --- changing -------------------------------------------------------------------------------


def change_id(ident: str, how: Callable[[dict | None], dict | None], *,
              by: str | None = None, run: str | None = None) -> dict | None:
    """Change one task's meta by its id; what it is afterwards. `how` is handed a copy of
    what it is now (None for none) and answers what it is to be."""
    st = _store()
    if st is None or not ident:
        return None
    _there, now = st.change_task_meta(ident, lambda was: _clean(how(was)), by=by, run=run)
    return now


def change(folder, how: Callable[[dict | None], dict | None], root=None, *,
           by: str | None = None, run: str | None = None) -> dict | None:
    """The same for the task in a folder. None, and nothing changed, when there is none."""
    root = _root(root)
    ident = task_id(folder, root)
    if not ident:
        log.warning("no task at %s to change the meta of", _rel(folder, root) or folder)
        return None
    return change_id(ident, how, by=by, run=run)


def write(folder, meta: dict | None, root=None, *, by: str | None = None,
          run: str | None = None) -> bool:
    """Put this meta on the task in a folder in place of what it has. True when there is a
    task to put it on."""
    root = _root(root)
    ident = task_id(folder, root)
    if not ident:
        return False
    change_id(ident, lambda _was: meta, by=by, run=run)
    return True


def merge_parts(was: dict | None, part: dict) -> dict:
    """Part of a meta laid over the whole of one: what `rouh-task meta <task> merge` does.

    Each key it names takes its value, and a key it gives as null is taken out. `steps` is
    laid over step by step, so naming one step leaves the others as they were, and a step
    given as null is taken out.
    """
    out = dict(was or {})
    for key, value in (part or {}).items():
        if value is None:
            out.pop(key, None)
        elif key == "steps" and isinstance(value, dict) and isinstance(out.get("steps"), dict):
            steps = dict(out["steps"])
            for name, said in value.items():
                if said is None:
                    steps.pop(name, None)
                else:
                    steps[name] = said
            out["steps"] = steps
        else:
            out[key] = value
    return out


# --- from outside Rouh: `rouh-task meta` ----------------------------------------------------

#: The ways `rouh-task meta` changes a task's meta.
HOWS = ("set", "merge", "append")

#: The most a meta may be, as JSON. The largest in the workspace on 22 October 2026 was under
#: 60 KB; past this it is a task's notes, which belong in its AGENTS.md.
MOST_BYTES = 400_000


def from_outside(ref, how: str, value, *, key: str = "", by: str, run: str = "",
                 ident: str = "", folder: str = "") -> dict:
    """A change from `rouh-task meta` (`rouh/web/taskapi.py`). What happened, in words.

    ``set`` puts `value` in place of the whole meta (null for none at all); ``merge`` lays
    `value` over it (`merge_parts`); ``append`` adds `value` to the end of the list at `key`,
    making the list where there is none. Raises `taskrecord.Refused` for anything it will not
    do, saying why.
    """
    from . import taskrecord

    if how not in HOWS:
        raise taskrecord.Refused(f"{how!r} is not a way to change a meta: {', '.join(HOWS)}.")
    if how == "merge" and not isinstance(value, dict):
        raise taskrecord.Refused("merge takes a JSON object: the keys to put in, null for a "
                                 "key to take out.")
    if how == "set" and value is not None and not isinstance(value, dict):
        raise taskrecord.Refused("set takes a JSON object, or null for no meta at all.")
    if how == "append":
        key = str(key or "").strip()
        if not key:
            raise taskrecord.Refused("append needs the key of the list, such as sends_himself.")
    if len(json.dumps(value, ensure_ascii=False)) > MOST_BYTES:
        raise taskrecord.Refused(f"That is more than {MOST_BYTES // 1000} KB. What does not fit "
                                 "belongs in the task's AGENTS.md.")
    st = _store()
    if st is None:
        raise taskrecord.Refused("Rouh has no database here, so there is nowhere to keep it.")
    row = taskrecord.find(st, ref, ident=ident, folder=folder)
    if row is None:
        raise taskrecord.Refused(f"Rouh has no task {ref}. Make it with `rouh objecttree "
                                 "create` first, which gives it a row.")
    refused: list[str] = []

    def apply(was):
        if how == "set":
            return value
        if how == "merge":
            return merge_parts(was, value)
        out = dict(was or {})
        held = out.get(key)
        if held is None:
            held = []
        elif isinstance(held, dict):
            held = [held]
        elif not isinstance(held, list):
            refused.append(f"{key} is not a list in this task's meta, so nothing can be added "
                           "to it.")
            return was
        out[key] = list(held) + [value]
        return out

    before = of(row.id)
    after = change_id(row.id, apply, by=by, run=run)
    if refused:
        raise taskrecord.Refused(refused[0])
    name = taskrecord._name(row)
    did = (f"{name}'s meta already says that" if after == before
           else f"{name}'s meta is changed ({how})")
    return {"ok": True, "did": did, "meta": after}
