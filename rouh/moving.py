"""Move, in the three dots on a task's or a subtask's page.

Petar, 29 September 2026 (fr_2c31bc88941c): "As another function too the dot
dot dot menu- move. We want to be able to move any subtask or task to any
other task or project. If moved to project it becomes top level task with the
next available number".

So Move opens a picker in Rouh (`moveOpen` in app.js) listing every project
and every task and subtask in the workspace, and what it asks for is here:

- `destinations` - every place the task at one folder could go, in the order
  the picker draws them. The task itself and everything inside it are listed
  but cannot be picked, and neither can the place it is now, so the picker
  says why rather than leaving them out. A column (Work, Personal, Rouh) is a
  heading and not a place: a task straight in a column is in no project, and
  `objecttree.tidy` would file it into Miscellaneous a moment later.
- `move` - the move itself, through `objecttree.move` with `renumber`: into a
  task it becomes that task's next subtask, into a project a subtask becomes a
  task with the next free number, and the subtasks inside it take the new
  number in front of theirs.

Petar, 22 October 2026 (fr_676c7ad596fd): "I want subtasks to be able to be
promoted to normal tasks, moved to another task, and moved to a brand-new
task." So `move` takes two more places beside an id: ``+task``, its own task
in the project its task is in (`promote`, "Promote to task"), and ``+new``, the
first subtask of a new task made there with its name (`to_new_task`, "Move to
new task"). Both are in the subtask's three dots, and a subtask is dragged onto
another task in the task browser. Every number a move takes away is kept on
the row (`remember`, `task.numbers_before`), so searching the number the person
remembers finds it under the one it has now (`ObjectStore.task_called`), and
its page says what it was (`objectindex._was_line`).

Which task is moving is always the folder Rouh framed, never anything the
page inside the frame says (`taskPageAct` in app.js), and where it goes is an
id or, for a subtask no row has heard of yet, a folder the server checks is a
subtask before it takes it in (`owning.task_at`).
"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path

from . import archiving, objects, objecttree, owning, pages

log = logging.getLogger("rouh.moving")

#: The number a subtask's folder starts with, as the person says it.
_NUMBER = re.compile(r"^(\d+(?:-\d+)?)(?=[-.])")


def _clean(folder: str) -> str:
    return "/".join(p for p in str(folder or "").split("/") if p and p != "..")


def _label(row: dict | None, folder: str) -> str:
    """What the person calls it: `62`, or a subtask's `62-09`."""
    if row is not None and row.get("number") is not None:
        return str(row["number"])
    # `62-09.x` is 62-09, and one of the early tasks' `01-setup-complete` is 01.
    found = _NUMBER.match(folder.rsplit("/", 1)[-1])
    return found.group(1) if found else ""


def _title(root: Path, row: dict | None, folder: str) -> str:
    from . import objectindex

    if row is not None and row.get("number") is not None:
        return str(row.get("title") or folder.rsplit("/", 1)[-1])
    try:
        title, _about = objectindex._step_title(str(root), folder, row)
    except Exception:                                   # pragma: no cover - reported
        log.exception("the title of %s could not be read", folder)
        title = ""
    return title or (row or {}).get("title") or folder.rsplit("/", 1)[-1]


def _step_folders(root: Path, folder: str) -> list[str]:
    """The subtask folders directly in a task's folder, as the task page finds them."""
    try:
        with os.scandir(root / folder) as found:
            return sorted(e.name for e in found
                          if e.is_dir(follow_symlinks=False)
                          and not e.name.startswith(".")
                          and e.name not in objecttree.NOT_OBJECTS
                          and objecttree.is_a_task(e.name, inside_a_task=True))
    except OSError:
        return []


def destinations(root, store: objects.ObjectStore, folder: str) -> dict:
    """Every place the task at `folder` could be moved to, and what it is.

    ``places`` is a list in drawing order, each ``{key, kind, label, title,
    depth, within, blocked}``: ``key`` is what `move` is handed back, a row's
    id or ``@`` and a folder; ``kind`` is ``column``, ``project`` or ``task``;
    ``blocked`` is "" or why it cannot be picked.
    """
    root = Path(str(root)).resolve()
    folder = _clean(folder)
    ident = owning.task_at(folder) if folder else ""
    if not ident:
        return {"ok": False, "why": "There is no task here to move."}
    rows, owners, under = objecttree.tree_now(store)
    me = rows.get(ident) or {}
    here = _clean(me.get("folder") or folder)
    kept = archiving.archived(store)
    by_folder = {str(r.get("folder") or ""): r for r in rows.values()
                 if r["type"] == "task" and r.get("folder")}
    parent = owners.get(ident)
    parent_folder = here.rpartition("/")[0]

    def why_not(key_id: str, at: str) -> str:
        if key_id == ident or at == here:
            return "This is the one you are moving"
        if at.startswith(here + "/"):
            return "It is inside the one you are moving"
        if (parent and key_id == parent) or (at and at == parent_folder):
            return "It is here now"
        return ""

    places: list[dict] = []

    def sort_projects(ids):
        return sorted((rows[k] for k in ids if rows[k]["type"] == "project"
                       and rows[k].get("folder")),
                      key=lambda r: (r["title"] or "").lower())

    def tasks_in(owner_id: str, depth: int, within: str) -> None:
        tops = [rows[k] for k in under.get(owner_id, [])
                if rows[k]["type"] == "task" and k not in kept and rows[k].get("folder")]
        tops.sort(key=lambda r: (-(r.get("number") or 0), (r["title"] or "").lower()))
        for row in tops:
            at = _clean(row["folder"])
            places.append({"key": row["id"], "kind": "task", "label": _label(row, at),
                           "title": _title(root, row, at), "depth": depth,
                           "within": within, "blocked": why_not(row["id"], at)})
            subtasks_in(row["id"], at, depth + 1,
                        f"{within} › {_label(row, at)} · {_title(root, row, at)}")

    def subtasks_in(owner_id: str, at: str, depth: int, within: str) -> None:
        found: dict[str, dict | None] = {}
        for name in _step_folders(root, at):
            path = f"{at}/{name}"
            found[path] = by_folder.get(path)
        for k in under.get(owner_id, []):
            row = rows[k]
            if row["type"] == "task" and row.get("folder"):
                found.setdefault(_clean(row["folder"]), row)
        for path in sorted(found, key=lambda p: (pages._step_key(p.rsplit("/", 1)[-1]), p)):
            row = found[path]
            if row is not None and row["id"] in kept:
                continue
            key = row["id"] if row is not None else "@" + path
            places.append({"key": key, "kind": "task", "label": _label(row, path),
                           "title": _title(root, row, path), "depth": depth,
                           "within": within,
                           "blocked": why_not(row["id"] if row else "", path)})
            subtasks_in(row["id"] if row else "", path, depth + 1,
                        f"{within} › {_label(row, path)}")

    def projects_in(owner_id: str, depth: int, within: str) -> None:
        for row in sort_projects(under.get(owner_id, [])):
            where = f"{within} › {row['title']}" if within else row["title"]
            places.append({"key": row["id"], "kind": "project", "label": "",
                           "title": row["title"], "depth": depth, "within": within,
                           "blocked": why_not(row["id"], _clean(row["folder"]))})
            projects_in(row["id"], depth + 1, where)
            tasks_in(row["id"], depth + 1, where)

    from . import objectindex

    for top in objectindex._Tree(store).tops():
        if not top.get("folder"):
            continue
        places.append({"key": top["id"], "kind": "column", "label": "",
                       "title": top["title"], "depth": 0, "within": "",
                       "blocked": "A task goes in one of its projects"})
        projects_in(top["id"], 1, top["title"])
    what = "subtask" if me.get("number") is None else "task"
    return {"ok": True, "id": ident, "what": what, "label": _label(me, here),
            "title": _title(root, me, here), "places": places}


#: The two places `move` makes rather than finds: the subtask as a task of its
#: own, and as the first subtask of a new task.
PROMOTE, NEW_TASK = "+task", "+new"


def _said(label: str) -> str:
    """A number as it is kept: `62`, `62-09`, whatever zeros it was written with."""
    parts = [int(p) for p in re.findall(r"\d+", str(label or ""))]
    return objects.number_said(parts)


def remember(st: objects.ObjectStore, ident: str, was: str, now: str) -> None:
    """Keep `was` as a number the task `ident` was called by, when a move changed it."""
    was, now = _said(was), _said(now)
    if ident and was and was != now:
        st.add_number_before(ident, was)


def _project_of(rows: dict, owners: dict, ident: str) -> dict | None:
    """The project the task above this one is in: where it goes as a task of its own."""
    at, seen = owners.get(ident), set()
    while at is not None and at not in seen:
        seen.add(at)
        row = rows.get(at)
        if row is None:
            return None
        if row["type"] == "project":
            return row
        at = owners.get(at)
    return None


def promote(folder: str) -> dict:
    """The subtask at `folder` made a task of its own, with the next free task
    number, in the project its task is in. "Promote to task" in its dots."""
    return move(folder, PROMOTE)


def to_new_task(folder: str, name: str = "") -> dict:
    """A new task called `name`, with the subtask at `folder` as its first
    subtask: "Move to new task" in its dots. The task is made in the project
    the subtask's task is in. Petar, 22 October 2026: "instead I should be
    asked what the name of the task", so Rouh asks before it sends this
    (`askTaskName` in app.js); with no name it is called what the subtask is."""
    return move(folder, NEW_TASK, name)


def move(folder: str, where: str, name: str = "") -> dict:
    """Move the task at `folder` to `where`: a project's or a task's id, ``@``
    and a subtask's folder, or `PROMOTE` or `NEW_TASK`. What the task
    browser's `change` answers, with ``rel`` the folder it is at now. `name`
    is what the task `NEW_TASK` makes is called."""
    folder = _clean(folder)
    ident = owning.task_at(folder) if folder else ""
    if not ident:
        return {"ok": False, "why": "There is no task here to move."}
    where = str(where or "")
    if where in (PROMOTE, NEW_TASK):
        return _move_out(folder, ident, where, name)
    if where.startswith("@"):
        at = _clean(where[1:])
        # A subtask no row has heard of: only a folder that really is one,
        # inside a task, is taken in (`owning._take_in_step`).
        owner = owning.task_at(at) if at and "/" in at else ""
    else:
        owner = where
    if not owner:
        return {"ok": False, "why": "Pick where it should go."}
    st = owning.store()
    root = owning._workspace()
    if st is None or not root:
        return {"ok": False, "why": "There is no workspace on this machine."}
    rows, _owners, _under = objecttree.tree_now(st)
    target = rows.get(owner)
    if target is None:
        return {"ok": False, "why": "That place is not in the workspace any more."}
    if target["type"] == "project" and target["id"] not in _owners:
        return {"ok": False, "why": "A task goes in one of the projects, not straight "
                                    f"into {target['title']}."}
    if running := owning.running_in(ident):
        names = ", ".join(r["title"] or r["id"] for r in running[:3])
        return {"ok": False, "why": f"It cannot move while a job is working in it: {names}. "
                                    "Try again when it has finished."}
    return _moved(root, st, rows, ident, target, folder)


def _moved(root, st: objects.ObjectStore, rows: dict, ident: str, target: dict,
           folder: str) -> dict:
    """The move itself, once everything has been asked, and the numbers it took away kept."""
    from . import filing

    me = rows.get(ident) or {}
    was = _label(me, _clean(me.get("folder") or folder))
    try:
        done = objecttree.move(root, st, ident, target["id"], renumber=True)
    except objecttree.Refused as exc:
        return {"ok": False, "why": str(exc)}
    except objects.Refused as exc:
        return {"ok": False, "why": str(exc)}
    except OSError:
        # What went wrong on disk is the log's; the person is told what it means.
        log.exception("%s could not be moved", ident)
        return {"ok": False, "why": "It could not be moved: its files could not be moved on "
                                    "the server. Nothing changed. Try again in a moment."}
    if not done.get("moved"):
        return {"ok": True, "did": "It is already there.", "rel": done.get("rel") or folder}
    if target["type"] == "project":
        # The person said where it belongs, so the filing model never moves
        # it after them.
        filing.placed_by_person(ident)
    now = done["rel"]
    name = now.rsplit("/", 1)[-1]
    called = (str(done["number"]) if done.get("number") is not None
              else _label(None, name))
    try:
        remember(st, ident, was, called)
        # The subtasks inside it that took the new number in front of theirs,
        # each taken in as a row where it was a folder alone, so it has
        # somewhere to keep what it was called.
        for at, old in zip(done.get("renumbered") or (), done.get("renumbered_from") or ()):
            inner = owning.task_at(at)
            if inner:
                remember(st, inner, _label(None, old), _label(None, at.rsplit("/", 1)[-1]))
    except Exception:                                   # pragma: no cover - reported
        # The move is done; only its search by the old number is lost.
        log.exception("the numbers %s had before its move could not be kept", ident)
    into = (f"{target['number']} · {target['title']}" if target.get("number") is not None
            else target["title"])
    return {"ok": True, "rel": now, "id": ident, "number": called,
            "did": f"Moved into {into}. It is {called} now."}


def _move_out(folder: str, ident: str, where: str, name: str = "") -> dict:
    """`PROMOTE` or `NEW_TASK`: a subtask out to the project its task is in, as a
    task of its own or as the first subtask of a task made there for it."""
    st = owning.store()
    root = owning._workspace()
    if st is None or not root:
        return {"ok": False, "why": "There is no workspace on this machine."}
    rows, owners, _under = objecttree.tree_now(st)
    me = rows.get(ident)
    parent = rows.get(owners.get(ident) or "")
    if me is None or parent is None or parent["type"] != "task":
        return {"ok": False, "why": "Only a subtask can be moved out of its task. "
                                    "This is a task already."}
    project = _project_of(rows, owners, ident)
    if project is None or project["id"] not in owners:
        return {"ok": False, "why": "Its task is in no project, so there is nowhere to put "
                                    "a new task. Move its task into a project first."}
    if running := owning.running_in(ident):
        names = ", ".join(r["title"] or r["id"] for r in running[:3])
        return {"ok": False, "why": f"It cannot move while a job is working in it: {names}. "
                                    "Try again when it has finished."}
    if where == PROMOTE:
        return _moved(root, st, rows, ident, project, folder)
    title = (" ".join(str(name or "").split())[:200]
             or _title(Path(str(root)), me, _clean(me.get("folder") or folder)))
    try:
        made = objecttree.create(root, st, type="task", title=title, owner=project["id"])
    except (objecttree.Refused, objects.Refused) as exc:
        return {"ok": False, "why": str(exc)}
    except OSError:
        log.exception("a new task for %s could not be made", ident)
        return {"ok": False, "why": "The new task could not be made: its files could not be "
                                    "written on the server. Nothing changed."}
    rows, _owners, _under = objecttree.tree_now(st)
    done = _moved(root, st, rows, ident, rows[made["id"]], folder)
    if not done.get("ok") or done.get("rel") == folder:
        # Nothing half-made: the task made for it goes again, empty as it is.
        try:
            st.delete_task(made["id"], cascade=False)
            objecttree.erase(root, [made["id"]], [made["rel"]])
        except Exception:                               # pragma: no cover - reported
            log.exception("the empty task %s could not be taken back", made["id"])
        return done if not done.get("ok") else {"ok": False, "why": "It could not be moved."}
    done["task"] = made["rel"]
    done["did"] = f"It is {done['number']} now, the first subtask of the new task {made['number']}."
    return done
