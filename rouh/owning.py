"""Who owns what, and the one operation that changes it.

`objects.py` holds the five things and the one link table; this is where the
rest of Rouh reaches them. Step five is the step that turned the other four
tables on, so everything here is about the same two sentences:

**An orphan is legal and is the default.** A run, a chat, a task and an
artifact are each made on their own, owned by nothing, and that is not a
half-made state to be tidied up later. It is what most of them stay.

**Attaching is one operation, for every pair the ranking allows.** There is no
"file a chat", "move a run under a task" and "put a card in a project": there
is `objects.attach`, one upsert against the partial unique index, and this
module is the thin layer that decides what a person may be offered, not what
the database will take. The ranking - project > task > chat > run > artifact -
is enforced in `objects.py`, by Python and by a CHECK constraint, and an
illegal pair is refused there rather than filtered out here.

What the interface can ask for
------------------------------

`snapshot` is the whole of what the page is told: the tasks, the projects, and
the workspaces and policies a new run may be started with. `under` is what one
object owns, walked down the ranking, which is how attaching a run to a task
moves its diff, its artifacts and its cost under that task without anything
being copied anywhere: they were the run's all along, and the run is now the
task's.

Where the rows come from
------------------------

The database is the source of truth, and each of the five has exactly one
writer:

* a **project** and a **chat** are rows of their own, written by
  `conversations.py`, which is where the conversations have lived since step
  three. Nothing is mirrored into them from anywhere and nothing here writes
  one;
* a numbered **task** is a folder in the person's workspace taken in as a row,
  as `task-30`, because 30 is what the person says out loud - and written back
  out from that row, which is the direction that matters;
* a **run** is `starting.py`'s, and an **artifact** is `artifacts.py`'s.

`ensure_task` in `artifacts.py` is what makes a task row, called rather than
written again here: step four already had to make those rows so that a card
filed into a folder had an owner, and a second way of making them would be a
second identity for the same thing, which is the whole problem this model
exists to be rid of.

`sync` is the tasks alone now, and is cheap enough to call whenever the page is
told about them. It never takes an owner away that a person gave.

A task made here is a task like any other: `new_task` goes through
`objecttree.create`, so it takes the next number, has a folder written out of
its row, and is then filed into a project by the model. It used to be a row
with none of that, on the reasoning that the task browser would not show it;
the browser shows every task row there is, so what that really made was a line
nothing could open and nothing could move.
"""
from __future__ import annotations

import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Iterable, Mapping

from . import answering, conversations, forks, objects, runs, waiting

log = logging.getLogger("rouh.owning")

#: What a person may be offered as the owner of each kind, in the order the
#: dialog lists them. Straight out of `objects.RANK`: anything above it may own
#: it.
#:
#: **A project is on this list too, because a project may own a project.** That
#: is half of the nesting the hierarchy is made of and it was missing here
#: while the dialog was written for a ranking with nothing nesting in itself,
#: so a project was the one thing on the screen that could not be filed
#: anywhere. The other half, a task owning a task, is deliberately not offered:
#: every task the dialog lists is a numbered one, a task inside a task is a
#: step and a step has no number, so the one thing that choice could do is take
#: a number away (`objecttree.move` refuses it in those words).
OWNERS_FOR: dict[str, tuple[str, ...]] = {
    kind: tuple(k for k in objects.KINDS if objects.RANK[k] < objects.RANK[kind])
    for kind in objects.KINDS if objects.RANK[kind] > 0
}
OWNERS_FOR["project"] = ("project",)

#: The one artifact every run has as soon as it has changed anything: what it
#: did to the files. Owned by the run and made by the run, so it travels with
#: it - which is the whole of "attaching a run to a task moves its diff".
DIFF_TITLE = "What it changed"


def store() -> objects.ObjectStore | None:
    """The one open store, which is the run register's. None when it is off."""
    return runs.store()


# ---------------------------------------------------------------------------
# Bringing the rows up to date from their one writer
# ---------------------------------------------------------------------------


def sync(*, tasks: bool = True) -> None:
    """Make sure every numbered task has its row. Never raises.

    Called wherever the page is about to be told about the objects. It is only
    the tasks: a project and a chat have been rows of their own since step
    three, written by `conversations.py` and not mirrored from anywhere, and a
    sync that copied them from themselves would have nothing to say - except
    the one thing it did say, which was to give an untitled chat a title and
    stop the automatic naming ever reaching it.

    The tasks are read off the person's workspace, which is a walk of a
    directory, so `tasks` is False where only the chats are being sent.
    Everything the walk finds is an inbound change taken into the rows, and a
    row whose folder has gone has it written out again: the database is the
    truth and the folders are the derived half (`conversations.reconcile`).
    """
    if store() is None:
        return
    try:
        if tasks:
            conversations.reconcile()
    except Exception:
        log.exception("could not bring the task rows up to date")


def _epoch(value: Any) -> float | None:
    return runs._epoch(value)


# ---------------------------------------------------------------------------
# Making things on their own
# ---------------------------------------------------------------------------


def new_task(title: str) -> objects.Task | None:
    """A task, through the one create path. None when there is no store.

    **It used to be a row and nothing else** - no number, no folder, no
    project - on the reasoning that a task of its own is in nobody's workspace
    and the task browser would not show it. The browser showed it anyway: it
    lists every task row there is, so a task made with **New task** landed on
    the board under "Not sorted" as a line that could not be opened, because
    there was no folder to open, and could not be moved, because `move` has
    nothing to move and says so. "Weekend plans", 22 September 2026, was
    exactly that, and the whole of what the person could do with it was drag
    it onto Miscellaneous and read the refusal.

    So a task made here is a task like any other: `objecttree.create` writes
    the row, the number, the folder, the sidecar and the AGENTS.md, and the
    filing model then puts it under the project it belongs in
    (`server.NewTasks`). On a machine with no workspace on it there is nothing
    to write a folder into, and there the row on its own is still the answer.
    """
    from . import objecttree

    st = store()
    if st is None:
        return None
    title = str(title or "").strip()[:200] or "A task"
    root = _workspace()
    if root and objecttree.has_map(root):
        try:
            made = objecttree.create(root, st, type="task", title=title)
            return st.get_task(made["id"])
        except (objecttree.Refused, OSError):
            log.exception("a task folder could not be made for %r", title)
    return st.create_task(title)


# ---------------------------------------------------------------------------
# Deleting, which is the one path for every type
# ---------------------------------------------------------------------------
#
# The person asked for this on 22 September 2026: "We should be able to delete
# items of all types - chats, runs, tasks, projects. Delete cascades if there
# are relationships."
#
# So there is one delete here and the type is an argument, rather than a delete
# per surface that each remembers a different amount. `plan` is what a person
# is shown before it happens, `remove` is what happens, and both walk the same
# `owns` edges in the same order, so the sentence somebody reads and the write
# that follows can never be about different things.
#
# What `remove` is responsible for, over and above the rows:
#
#   * the bytes of every artifact that goes - a card written out as a step, a
#     built page - because the file is the derived half of that row and has
#     nothing to be derived from once the row is gone;
#   * the folder of every workspace project and task that goes, and its line in
#     the workspace's map file, or `objecttree.ensure_imported` would read that
#     file on the next page load and put the row straight back;
#   * the step's line in its task's meta, for the same reason.
#
# What it is not responsible for is stopping a run that is still going. That is
# asynchronous, it belongs to whoever owns the terminal - the crew for a worker,
# the one program for a run of its own - and `runtime.py` does it before calling
# here, off the list `plan` hands it.

#: What each type is called in the sentence a person reads, one and many.
WORDS: dict[str, tuple[str, str]] = {
    "project": ("project", "projects"),
    "task": ("task", "tasks"),
    "chat": ("chat", "chats"),
    "run": ("run", "runs"),
    # "artifact" and not "card". It was "card" while a card was the only one
    # anybody ever saw; since the workspace's built pages take themselves in
    # (`artifacts.register_tree_pages`) most of them are pages, and a project
    # holding twenty explainers and one card does not hold 21 cards.
    "artifact": ("artifact", "artifacts"),
}

#: The same, for what a task holds: a task inside a task is its subtask.
SUBTASK_WORDS: dict[str, tuple[str, str]] = dict(WORDS, task=("subtask", "subtasks"))

#: The run states that mean something is still going and has to be stopped
#: before its record is taken away.
STILL_GOING: tuple[str, ...] = ("running", "waiting", "conflict")

#: What a cascade may never take, however deep under the thing being deleted
#: it is. There is one: **General**, the thread everything with no home yet is
#: said in, so a project holding it is still a project that can be deleted and
#: General comes out of it unowned rather than going with it.
#:
#: It is a set rather than a check in `plan`, because the same set is handed to
#: the walk that counts and to the walk that deletes (`objects.owned_tree`),
#: and a thing spared by one and taken by the other is the confirmation lying.
KEEP: frozenset[tuple[str, str]] = frozenset({("chat", conversations.GENERAL)})


def _count_words(counts: Mapping[str, int], forked: int = 0,
                 words: Mapping[str, tuple[str, str]] | None = None) -> str:
    """The counts as a person says them, in the ranking's own order.

    "1 chat". "2 tasks and 1 chat". "1 task, 1 chat and 3 cards". `forked` is
    how many forks hang off the chats among them, said straight after the
    chats, because that is what they are attachments to (`rouh/forks.py`).
    `words` is another name for a kind: a task under a task is a subtask.
    """
    words = words or WORDS
    said = []
    for kind in objects.KINDS:
        many = counts.get(kind) or 0
        if many:
            one, lots = words[kind]
            said.append(f"{many} {one if many == 1 else lots}")
        if kind == "chat" and forked:
            said.append(f"{forked} {'fork' if forked == 1 else 'forks'}")
    if len(said) > 1:
        said[-1] = "and " + said[-1]
    return (", ".join(said[:-1]) + " " + said[-1]) if len(said) > 1 else "".join(said)


def _forks_of(st: objects.ObjectStore, targets) -> tuple[list[str], list[tuple[str, str]]]:
    """The forks hanging off every chat among `targets`, and what they own.

    A fork is owned by nothing - it is filed nowhere and is in no list - but
    it is an attachment to the chat it came off, and a chat that goes takes
    its forks with it, however deep (`rouh/forks.py`). Asked before anything
    is deleted: the database lets go of a fork's row the moment its parent
    goes, and what hung there could not be found afterwards.
    """
    hanging = forks.under([at_id for at_type, at_id in targets if at_type == "chat"])
    held: list[tuple[str, str]] = []
    for fork_id in hanging:
        held.extend(st.owned_tree("chat", fork_id, keep=KEEP))
    return hanging, held


def _may_not_go(kind: str, obj_id: str) -> str:
    """Why this one may not be deleted, or an empty string when it may.

    There is exactly one thing here that may never go, and it is the one the
    delete a chat had of its own always refused: General is the thread
    everything with no home yet is said in, so deleting it would be deleting
    the place the next thing lands.

    Asked in `plan` and again in `remove`, because the page is not what decides
    this: a message can be sent by anything at all, and a refusal that lives in
    the dialog is a refusal that is not there.
    """
    if kind not in objects.KINDS:
        return f"There is no such thing as a {kind}."
    if (kind, obj_id) in KEEP:
        return ("General is the thread that is always there, and it is never "
                "deleted: it is where anything with no home yet is said.")
    return ""


def task_at(folder: str) -> str:
    """The id of the task or subtask whose folder this is, or "".

    How a task's own page names what its three dots act on: the page is at the
    folder, and the page around it reads the folder off the address it framed
    (`taskPageAct` in app.js), never off anything the page says.
    """
    folder = "/".join(p for p in str(folder or "").split("/") if p)
    st = store()
    if st is None or not folder or ".." in folder.split("/"):
        return ""
    try:
        row = st.by_folder("task", folder)
        if row is None:
            return _take_in_step(st, folder)
    except Exception:
        log.exception("could not look up the task at %s", folder)
        return ""
    return row.id


def _take_in_step(st: objects.ObjectStore, folder: str, depth: int = 0) -> str:
    """A subtask that is a folder and nothing else, given the row it lacks.

    Most subtasks are: a job writes its step folder by hand, and the rows
    never hear of it (`objectindex._step_on_disk`). Its page is drawn all the
    same, and its three dots have to rename it and delete it like any other,
    which the one path for both does from a row. So it is taken in: the id
    and the title its `.object.json` says, where it has one, owned by the task
    it is inside - taken in first the same way, when it is a folder alone
    too. Exactly what the folder already says, and nothing more. "" for a
    folder that is not a subtask inside a task.
    """
    from . import objecttree

    root = _workspace()
    parent, _, name = folder.rpartition("/")
    if (not root or not parent or depth > MAX_STEPS_DEEP
            or name in objecttree.NOT_OBJECTS
            or not objecttree.is_a_task(name, inside_a_task=True)):
        return ""
    base = Path(root)
    path = base / folder
    try:
        if path.is_symlink() or not path.is_dir() or base.resolve() not in path.resolve().parents:
            return ""
    except OSError:
        return ""
    over = st.by_folder("task", parent)
    over_id = over.id if over is not None else _take_in_step(st, parent, depth + 1)
    if not over_id:
        return ""
    try:
        said = objecttree.read_sidecar(path, base) or {}
    except Exception:
        said = {}
    ident = str(said.get("id") or "") if said.get("type", "task") == "task" else ""
    if ident and (st.get_task(ident) is not None or st.get_project(ident) is not None):
        # Its id is somebody else's row already: a copy of a folder. Not this.
        ident = ""
    title = objecttree.title_of(path, name) or str(said.get("title") or "").strip()
    from . import task_origin

    row = st.create_owned("task", title, owner=("task", over_id), id=ident or None,
                          slug=name, folder=folder, origin=task_origin.under(over_id))
    log.info("took in the subtask at %s as %s, so it can be renamed or deleted",
             folder, row.id)
    return row.id


def label_of(kind: str, obj_id: str) -> str:
    """What to call one object in a sentence: its name, with a task's number."""
    said = describe(kind, obj_id) or {}
    name = str(said.get("label") or obj_id)
    number = said.get("number")
    return f"{number} {name}" if number is not None else name


def plan(kind: str, obj_id: str) -> dict:
    """What deleting this would take with it, in words a person can read.

    Answered before anything is written and shown in the confirmation, so
    nobody deletes a project and finds out afterwards that forty chats went
    with it. The counts are the `owns` subtree, which is exactly what `remove`
    deletes.

    `running` is the runs in that subtree that are still going. They are
    stopped first, by their own owner, and the sentence says so.
    """
    st = store()
    if st is None:
        return {"ok": False, "why": "The object model is not on."}
    refused = _may_not_go(kind, obj_id)
    if refused:
        return {"ok": False, "why": refused}
    row = {"project": st.get_project, "task": st.get_task, "chat": st.get_chat,
           "run": st.get_run, "artifact": st.get_artifact}[kind](obj_id)
    if row is None:
        return {"ok": False, "why": "It is not here any more."}
    held = st.owned_tree(kind, obj_id, keep=KEEP)
    hanging, under_forks = _forks_of(st, [*held, (kind, obj_id)])
    counts: dict[str, int] = {}
    running: list[dict] = []
    for at_type, _at_id in [*held, *under_forks]:
        counts[at_type] = counts.get(at_type, 0) + 1
    if kind == "task" and getattr(row, "folder", ""):
        # And the subtasks that are folders and nothing else, which go with
        # the folder as surely as the ones with rows (`_take_in_step`).
        known = {getattr(st.get_task(i), "folder", "") for t, i in held if t == "task"}
        loose = _step_folders(row.folder) - known
        if loose:
            counts["task"] = counts.get("task", 0) + len(loose)
    in_it: list[dict] = []
    for at_type, at_id in [*held, *under_forks, (kind, obj_id)]:
        if at_type != "run":
            continue
        run_row = st.get_run(at_id)
        if run_row is None:
            continue
        said = {"id": at_id, "title": run_row.title, "policy": run_row.policy,
                "state": run_row.state, "going": run_row.state in STILL_GOING}
        in_it.append(said)
        if said["going"]:
            running.append(said)
    # What a task holds is its subtasks, which is what the person calls them.
    also = _count_words(counts, len(hanging), SUBTASK_WORDS if kind == "task" else None)
    one = WORDS[kind][0]
    if kind == "task" and (st.owner_of("task", obj_id) or ("",))[0] == "task":
        one = "subtask"
    # The person's own words for this, on 22 September 2026: `"test project"
    # and all of its chats will be permanently deleted. This can't be undone.`
    # The name is already on the line above it in the dialog, so this is the
    # rest of that sentence with the real counts in it, and the last clause is
    # the dialog's own red line.
    sentence = (f"Its {also} will be permanently deleted." if also
                else f"Nothing else belongs to this {one}.")
    if getattr(row, "folder", ""):
        held_files = _folder_words(row.folder) if kind == "task" else ""
        sentence += (f" Its folder in the workspace goes with it, and everything in it:"
                     f" {held_files}." if held_files
                     else " Its folder in the workspace goes with it.")
    if running:
        sentence += (" One run under it is still going and will be stopped first."
                     if len(running) == 1 else
                     f" {len(running)} runs under it are still going and will be"
                     " stopped first.")
    return {"ok": True, "kind": kind, "id": obj_id, "label": label_of(kind, obj_id),
            "what": one, "counts": counts, "also": also, "sentence": sentence,
            # Every chat and every run in the subtree, named: the page shows
            # the counts, and the server has work to do for each one before
            # and after the rows go - a terminal to stop, a tape to throw
            # away - which it cannot do from a number.
            "chats": [at_id for at_type, at_id in [*held, (kind, obj_id)]
                      if at_type == "chat"] + hanging
                     + [at_id for at_type, at_id in under_forks if at_type == "chat"],
            "forks": len(hanging),
            "runs": in_it, "running": running,
            "total": len(held) + len(hanging) + len(under_forks) + 1}


def _step_folders(folder: str) -> set[str]:
    """Every subtask folder under a task's folder, however deep, as paths in
    the workspace."""
    from . import objecttree

    root = _workspace()
    found: set[str] = set()
    if not root or not folder:
        return found
    base = Path(root)
    want = [(folder, 0)]
    while want:
        at, depth = want.pop()
        if depth > MAX_STEPS_DEEP:
            continue
        try:
            names = sorted(os.listdir(base / at))
        except OSError:
            continue
        for name in names:
            path = base / at / name
            if (name in objecttree.NOT_OBJECTS or path.is_symlink() or not path.is_dir()
                    or not objecttree.is_a_task(name, inside_a_task=True)):
                continue
            found.add(f"{at}/{name}")
            want.append((f"{at}/{name}", depth + 1))
    return found


def _folder_words(folder: str) -> str:
    """What is written in a task's folder, as the delete dialog says it.

    Petar, 27 September 2026 (fr_3273da8d3be9), on deleting a task: it
    "deletes the associated items with it: chats, goal, subtasks, md files,
    source files and folders, agent md, html pages". The rows count the
    chats and the subtasks; this counts what is on disk, subtasks' folders
    included, because the whole folder goes. What makes a folder an object
    (`.object.json`) is not a file anybody wrote, and is left
    out of the count. "" when there is nothing, or nothing can be read.
    """
    from . import goals

    root = _workspace()
    if not root or not folder:
        return ""
    base = os.path.realpath(os.path.join(root, *str(folder).split("/")))
    if not base.startswith(os.path.realpath(root) + os.sep) or not os.path.isdir(base):
        return ""
    goal = False
    try:
        goal = goals.is_goal(goals._meta(Path(base)))
    except Exception:
        goal = False
    agents = os.path.isfile(os.path.join(base, "AGENTS.md"))
    md = pages_n = other = 0
    for at, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if d not in (".git", "node_modules", "__pycache__")]
        for name in files:
            if name in (".object.json", ".DS_Store"):
                continue
            if at == base and (name == "AGENTS.md" or (goal and name == "goal.md")):
                continue
            low = name.lower()
            if low.endswith(".md"):
                md += 1
            elif low.endswith((".html", ".htm")):
                pages_n += 1
            else:
                other += 1
    said = []
    if goal:
        said.append("its goal")
    if agents:
        said.append("its AGENTS.md")
    for many, one, lots in ((md, ".md file", ".md files"), (pages_n, "page", "pages"),
                            (other, "other file", "other files")):
        if many:
            said.append(f"{many} {one if many == 1 else lots}")
    if len(said) > 1:
        return ", ".join(said[:-1]) + " and " + said[-1]
    return "".join(said)


def remove(kind: str, obj_id: str) -> dict:
    """Delete an object, everything it owns, and what any of it wrote out.

    The rows first, in one transaction, then the disk, because the rows are the
    truth and what is on disk is written out from them: a file left behind by a
    failed unlink is litter, and a row left behind by a failed delete is the
    thing coming back on the next page load.
    """
    st = store()
    if st is None:
        return {"ok": False, "why": "The object model is not on."}
    refused = _may_not_go(kind, obj_id)
    if refused:
        return {"ok": False, "why": refused}
    label = label_of(kind, obj_id)
    # Everything the rows know about the disk, read before the rows go.
    targets = [*st.owned_tree(kind, obj_id, keep=KEEP), (kind, obj_id)]
    loose_steps = 0
    if kind == "task":
        top = st.get_task(obj_id)
        if top is not None and top.folder:
            known = {getattr(st.get_task(i), "folder", "") for t, i in targets if t == "task"}
            loose_steps = len(_step_folders(top.folder) - known)
    hanging, under_forks = _forks_of(st, targets)
    targets = [*under_forks, *targets]
    idents = [at_id for _at_type, at_id in targets] + hanging
    going = set(idents)
    files: list[str] = []
    folders: list[str] = []
    steps_of: list[tuple[str, str]] = []
    for at_type, at_id in targets:
        if at_type == "artifact":
            art = st.get_artifact(at_id)
            if art is not None and art.path:
                files.append(art.path)
        elif at_type in ("project", "task"):
            row = st.get_project(at_id) if at_type == "project" else st.get_task(at_id)
            if row is None or not row.folder:
                continue
            folders.append(row.folder)
            # A step is named in its task's meta, so it has to be
            # taken out of it - unless that task is going too, in which case
            # the file is about to be deleted and writing to it first is both
            # pointless and, because `git rm` refuses a modified file, the
            # thing that leaves the deletion unstaged.
            owner = st.owner_of(at_type, at_id)
            if not owner or owner[0] != "task" or owner[1] in going:
                continue
            held = st.get_task(owner[1])
            if held is not None and held.folder:
                steps_of.append((held.folder, row.folder.split("/")[-1]))
    try:
        gone = st.delete(kind, obj_id, keep=KEEP)
        # And the forks that hung off any chat that went, each with whatever
        # it owns. Deepest first, which is the order `forks.under` gives.
        if gone:
            for fork_id in hanging:
                gone = st.delete("chat", fork_id, keep=KEEP) + gone
    except objects.Refused as exc:
        return {"ok": False, "why": str(exc)}
    except Exception:
        log.exception("could not delete %s %s", kind, obj_id)
        return {"ok": False, "why": "That could not be deleted."}
    if not gone:
        return {"ok": False, "why": "It is not here any more."}
    # Never a link left pointing at something that is not there. `delete` leaves
    # none of its own; this is the whole table, every time, because it is one
    # query and a delete is the moment to ask.
    orphans = st.sweep_links()
    counts: dict[str, int] = {}
    # The subtree, and not the object itself: the sentence reads "and so is
    # everything under it", so the thing being deleted must not be counted
    # among what went with it.
    forked = 0
    for at_type, ident in gone:
        if (at_type, ident) == (kind, obj_id):
            continue
        if at_type == "chat" and ident in hanging:
            forked += 1
            continue
        counts[at_type] = counts.get(at_type, 0) + 1
    if loose_steps:
        counts["task"] = counts.get("task", 0) + loose_steps
    swept = _sweep_disk(files, folders, idents, steps_of)
    log.info("deleted %s %s and %d object(s) under it", kind, obj_id, len(gone) - 1)
    also = _count_words(counts, forked, SUBTASK_WORDS if kind == "task" else None)
    return {"ok": True, "kind": kind, "id": obj_id, "label": label,
            "gone": [{"type": t, "id": i} for t, i in gone], "counts": counts,
            "orphan_links": orphans,
            # Which workspace folders went, so a page showing one of them can
            # take itself off it. A task deleted while its own page was in the
            # canvas went on being drawn there, which is the deleted thing
            # still on the screen.
            "folders": swept,
            "did": f"\u201c{label}\u201d is gone." if not also else
                   f"\u201c{label}\u201d is gone, and so is everything under it: {also}."}


def _sweep_disk(files: list[str], folders: list[str], idents: list[str],
                steps_of: list[tuple[str, str]]) -> list[str]:
    """Take away what the deleted rows had written out, and say what went.

    The rows are already gone by the time this runs, so nothing here can leave
    the database half deleted: the worst a failure costs is a file nobody can
    reach from anywhere, which is said in the log.
    """
    from . import objecttree, steps as steps_mod

    root = _workspace()
    if not root:
        return []
    for rel in files:
        _unlink(root, rel)
    for folder, name in steps_of:
        try:
            steps_mod.forget_step(os.path.join(root, *folder.split("/")), name,
                                  root)
        except Exception:
            log.exception("the step %s could not be taken out of %s", name, folder)
    if not folders:
        return []
    try:
        return objecttree.erase(root, idents, folders)["folders"]
    except Exception:
        log.exception("the folders %s could not be removed", folders)
        return []


def _unlink(root: str, rel: str) -> None:
    """One artifact's bytes, and the step folder holding them if it is now empty.

    Inside the workspace or not at all: `path` is written by this repository
    and is always relative to the workspace, and a path that climbs out of it
    is a bug worth refusing rather than following.
    """
    whole = os.path.realpath(os.path.join(root, *str(rel).split("/")))
    if not whole.startswith(os.path.realpath(root) + os.sep):
        log.warning("refusing to remove %s: it is outside the workspace", rel)
        return
    try:
        if os.path.isfile(whole):
            os.remove(whole)
        folder = os.path.dirname(whole)
        if os.path.isdir(folder) and not os.listdir(folder):
            os.rmdir(folder)
    except OSError:
        log.exception("could not remove the file %s", rel)


# ---------------------------------------------------------------------------
# Keeping one, and renaming one
# ---------------------------------------------------------------------------
#
# Every row of a search result offers the same five: open it, open it in a new
# tab, pin it, rename it, delete it. The first two are the page's, **delete is
# `remove` above** - one cascade for every type, with the confirmation that
# names what else goes - and these two are the rest, here for the reason
# everything else in this module is here: one place the rest of Rouh reaches
# the five objects, so that "keep this" means the same thing whichever list it
# was said from.
#
# **A chat is not one of these.** Its writer is `conversations.py` and stays
# the only one: renaming a chat puts an emoji in front of the name, and that is
# not a column. `rouh/runtime.py` sends a chat's rename down the path it had.


def pin(kind: str, obj_id: str, on: bool = True) -> dict:
    """Keep this, or stop keeping it. The same word on all five.

    A mark the person sets, and nothing more: nothing in Rouh is archived or
    deleted on a clock any more, so the pin is not a reprieve from anything.
    It is the person saying this one matters, and it is offered on every row
    of a search result, which is why `project` and `run` have the column that
    a chat, a task and an artifact already had.
    """
    return _write(kind, obj_id, "pinned", bool(on))


def mark_seen(kind: str, obj_id: str, deep: bool = False) -> dict:
    """The person has looked at this. Its dot goes out.

    What takes the red dot off one row of the rail, and off the tab above it
    once nothing unseen is left. Opening a task, a step or a run is the whole
    of what "seen" means here - there is nothing to confirm and nothing to
    dismiss - and archiving a run says it too, which `objects.update_run` does
    for itself because a run is archived from three different places.

    `deep` is the dot itself being pressed rather than the row, and a
    **project** is always deep: a dot on a project only ever means "something
    in here", so the only honest way to clear it is to clear what it was
    pointing at. Without `deep` a task is that task and nothing under it,
    which is what makes the trail worth following - it keeps its dot while a
    step inside it is still unseen, and the person can see how far down the
    new thing is.

    Nothing here asks whether the row has stopped. The page only sends this
    about one that has something to clear, and a mark on a row that is still
    working costs a write and nothing else: the register clears it again the
    moment that row does stop (`objects._unseen_again`), which is the
    behaviour anybody would want from it anyway.
    """
    if not deep and kind != "project":
        return _write(kind, obj_id, "seen_at", time.time())
    st = store()
    if st is None or not obj_id:
        return {"ok": False, "why": "There is nothing to mark seen."}
    if kind not in ("task", "project"):
        return {"ok": False, "why": "Only a task or a project holds anything."}
    ids = [obj_id] if kind == "task" else []
    ids.extend(_tasks_under(st, obj_id))
    # Every id is offered and only the tasks among them match: the store writes
    # to the task table, so a project id in the list simply updates nothing
    # rather than needing a second query to take it back out.
    got = st.mark_seen(ids)
    log.info("marked %d of %d thing(s) under the %s %s as seen",
             got, len(ids), kind, obj_id)
    return {"ok": True, "seen": got}


def mark_runs_seen(run_ids: Iterable[str]) -> int:
    """A whole list of runs looked at in one go, which is landing on the list.

    The dot on a run's card says which run wants looking at; the dot on the tab
    over the list says the list does. Arriving at the list answers the second,
    and that is one act about twenty rows rather than twenty presses: one
    write each, one message, and one task list broadcast at the end of it.

    Returns how many were actually written, which is nothing more than a line
    in the log: a run the register has forgotten is a no-op here, the way an
    unknown id is everywhere else on this path.
    """
    st = store()
    if st is None:
        return 0
    when = time.time()
    done = 0
    for run_id in run_ids:
        if not run_id:
            continue
        try:
            if st.update_run(run_id, seen_at=when) is not None:
                done += 1
        except Exception:
            log.exception("could not mark the run %s seen", run_id)
    if done:
        log.info("marked %d run(s) seen: the runs list was opened", done)
    return done


def _tasks_under(st: objects.ObjectStore, obj_id: str) -> list[str]:
    """Every task and step below one object, however deep, ids only."""
    under: dict[str, list[str]] = {}
    for _src_type, src_id, dst_type, dst_id in st.owns_edges():
        if dst_type in objects.NESTS:
            under.setdefault(src_id, []).append(dst_id)
    out: list[str] = []
    want = [(obj_id, 0)]
    seen: set[str] = {obj_id}
    while want:
        at, depth = want.pop()
        if depth > MAX_STEPS_DEEP + 4:
            continue
        for kid in under.get(at, ()):
            if kid in seen:
                continue
            seen.add(kid)
            out.append(kid)
            want.append((kid, depth + 1))
    return out


def rename(kind: str, obj_id: str, title: str) -> dict:
    """Give it another name, and write that name where the name is kept.

    For a run and an artifact the row is the whole of it. For a project or a
    task that is a folder in the workspace the folder says what it is too, in
    its `.object.json`, so the sidecar is written with the new title and the
    two cannot disagree. **The folder itself is not renamed**: its name is the
    address of every page under it and of every link into it, and moving it is
    `objecttree.move`, which is a different thing a person asks for in a
    different place.
    """
    title = " ".join(str(title or "").split())[:200]
    if not title:
        return {"ok": False, "why": "A name cannot be empty."}
    got = _write(kind, obj_id, "title", title)
    if got.get("ok"):
        _retitle_folder(kind, obj_id, title)
    return got


def _one_of_five(kind: str) -> str | None:
    """The kind, when it is one this module writes. A chat is not."""
    kind = str(kind or "")
    return kind if kind in ("project", "task", "run", "artifact") else None


def _write(kind: str, obj_id: str, column: str, value) -> dict:
    """One column of one row, whichever of the four tables it is in."""
    name = _one_of_five(kind)
    if name is None:
        return {"ok": False, "why": f"A {kind} is not changed here."}
    st = store()
    if st is None:
        return {"ok": False, "why": "The object model is not on."}
    update = {"project": st.update_project, "task": st.update_task,
              "run": st.update_run, "artifact": st.update_artifact}[name]
    try:
        row = update(obj_id, **{column: value})
    except objects.Refused as exc:
        return {"ok": False, "why": str(exc)}
    except Exception:
        log.exception("could not set %s on %s %s", column, name, obj_id)
        return {"ok": False, "why": "That could not be written down."}
    if row is None:
        return {"ok": False, "why": "It is not there any more."}
    return {"ok": True, "object": describe(name, obj_id),
            "pinned": bool(getattr(row, "pinned", False))}


def _retitle_folder(kind: str, obj_id: str, title: str) -> None:
    """Write a renamed object's new title into its folder's `.object.json`.

    The sidecar is what a folder says it is, and `objecttree` reads it back to
    know what it found. Leaving it at the old title would be a row and a folder
    disagreeing about one thing, which is the exact shape of drift this model
    exists to be rid of. Never a reason a rename fails: the row is the truth,
    and a sidecar that could not be written is logged and left.
    """
    from . import objecttree

    if kind not in objects.NESTS:
        return
    st = store()
    row = None if st is None else (st.get_project(obj_id) if kind == "project"
                                   else st.get_task(obj_id))
    root = _workspace()
    if row is None or not row.folder or not root:
        return
    folder = Path(root) / row.folder
    try:
        said = objecttree.read_sidecar(folder, root)
        if said is None:
            return
        objecttree.write_sidecar(folder, dict(said, title=title), root)
        # Saved to main soon rather than at the next pass (`rouh/saving.py`),
        # so a deploy in between does not put the old name back on disk.
        objecttree._written()
    except Exception:
        log.warning("the row for %s %s was renamed but its .object.json was not",
                    kind, obj_id, exc_info=True)
    # A subtask is also named in its task's meta, which is what the
    # task's own page and the step's column read its title from
    # (`objecttree.title_of`), so the new name goes there too.
    owner = st.owner_of(kind, obj_id) if kind == "task" else None
    if not owner or owner[0] != "task":
        return
    held = st.get_task(owner[1])
    if held is None or not held.folder:
        return
    from . import steps as steps_mod
    try:
        steps_mod.retitle_step(Path(root) / held.folder, row.folder.split("/")[-1],
                               title, root)
    except Exception:
        log.warning("the subtask %s was renamed but its task's list of steps was not",
                    obj_id, exc_info=True)


# ---------------------------------------------------------------------------
# The one operation
# ---------------------------------------------------------------------------


def attach(kind: str, obj_id: str, owner_kind: str, owner_id: str) -> dict:
    """Give an object an owner. One upsert, the same one for every legal pair.

    Returns ``{"ok": True, "owner": {...}}`` or ``{"ok": False, "why": "..."}``
    with the store's own sentence, which says why the pair is refused.

    A chat has one owner like everything else, so attaching it to a task takes
    it out of the project it was in and attaching it to a project takes it away
    from its task. Which project a chat is in **is** this link since step
    three; there is no folder column beside it to keep in step.

    General is the one chat that is never given an owner: it is loose and
    stays loose (`conversations.GENERAL`, `conversations.let_general_go`).
    """
    st = store()
    if st is None:
        return {"ok": False, "why": "The object model is not on."}
    if kind == "chat" and obj_id == conversations.GENERAL:
        return {"ok": False, "why": "General is never in a project: it is where "
                "anything with no home yet is said, whichever project you work in."}
    try:
        st.attach(owner_kind, owner_id, kind, obj_id)
    except objects.Refused as exc:
        return {"ok": False, "why": str(exc)}
    except Exception:
        log.exception("could not attach %s %s to %s %s", kind, obj_id, owner_kind, owner_id)
        return {"ok": False, "why": "That could not be written down."}
    return {"ok": True, "owner": owner_of(kind, obj_id)}


def detach(kind: str, obj_id: str) -> dict:
    """Take an object's owner away, leaving it an orphan, which is legal.

    Nothing else happens. What it owns stays its own, a run keeps its diff and
    its cost, and a chat that is loose again is a chat like any other: nothing
    counts down over it, here or anywhere.
    """
    st = store()
    if st is None:
        return {"ok": False, "why": "The object model is not on."}
    try:
        st.detach(kind, obj_id)
    except objects.Refused as exc:
        return {"ok": False, "why": str(exc)}
    return {"ok": True, "owner": None}


def detach_fork_into(chat_id: str, task_id: str) -> dict:
    """Detach a fork from the chat it came off and file it under a task, as
    one step. The same answer `attach` gives.

    Petar, 6 October 2026 (fr_efa418fa7e82): "when I detach a chat I have to
    pick which task I move it to, or else I am not detaching. this is done to
    prevent loose chats". So there is no detach without a task: no task, an
    archived one or one that is not there is refused, and the fork is left
    exactly where it was, still laid out beside its parent.

    The task first and the cut after it. An attach that is refused leaves the
    fork a fork, and nothing has to be put back; the cut cannot be refused
    once the fork is known to be one (`forks.detach`).
    """
    st = store()
    if st is None:
        return {"ok": False, "why": "The object model is not on."}
    if not forks.parent_of(chat_id):
        return {"ok": False, "why": "That chat is not a fork beside another one any more."}
    if not task_id:
        return {"ok": False, "why": "Pick the task it goes to: a fork is only detached "
                "into a task, so no chat is left loose."}
    task = st.get_task(task_id)
    if task is None:
        return {"ok": False, "why": "That task is not there any more."}
    if task.archived_at is not None:
        return {"ok": False, "why": "That task is archived. Pick one that is still open."}
    got = attach("chat", chat_id, "task", task_id)
    if got.get("ok"):
        forks.detach(chat_id)
    return got


def owner_of(kind: str, obj_id: str) -> dict | None:
    """Who owns this, as the page reads it, or None when it is an orphan."""
    st = store()
    if st is None or not obj_id:
        return None
    try:
        found = st.owner_of(kind, obj_id)
    except objects.Refused:
        return None
    return describe(*found) if found else None


def describe(kind: str, obj_id: str,
             owners: Mapping[tuple[str, str], tuple[str, str]] | None = None) -> dict | None:
    """One object as a line the page can draw: its type, its id and its name.

    `owners` is every `owns` link, child to owner, when the caller has read
    them already (`decorate`), so a subtask's parent is found without asking
    the database again."""
    st = store()
    if st is None:
        return None
    getter = {"project": st.get_project, "task": st.get_task, "chat": st.get_chat,
              "run": st.get_run, "artifact": st.get_artifact}.get(kind)
    row = getter(obj_id) if getter else None
    if row is None:
        return {"type": kind, "id": obj_id, "label": obj_id, "number": None}
    number = getattr(row, "number", None)
    label = getattr(row, "title", None) or obj_id
    out = {"type": kind, "id": obj_id, "label": str(label), "number": number}
    if kind == "task":
        # A subtask says which task it is in, so the head of its chat can name
        # both and go up a level (`rouh/subtasknotes.py`).
        from . import subtasknotes

        out["folder"] = row.folder or ""
        if owners is None:
            parent = subtasknotes.describe_parent(obj_id)
        else:
            up = owners.get(("task", obj_id))
            parent = (describe(*up) if up is not None and up[0] == "task" else None)
            if parent is not None:
                parent["step"] = ("" if parent.get("number") is not None
                                  else subtasknotes.step_of_folder(parent.get("folder")))
                parent.pop("parent", None)
        if parent is not None:
            out["parent"] = parent
            out["step"] = subtasknotes.step_number(row)
    return out


# ---------------------------------------------------------------------------
# What is under something
# ---------------------------------------------------------------------------


def under(kind: str, obj_id: str, depth: int = 0) -> dict:
    """What this object owns, walked down the ranking, with the cost added up.

    Nothing is copied and nothing is moved: this is one query per level of the
    same `owns` rows `attach` writes. So a run attached to a task appears here
    the instant it is attached, with its diff and its artifacts under it,
    because those were the run's own and the run is now the task's.
    """
    st = store()
    out: dict[str, Any] = {"type": kind, "id": obj_id, "children": [], "cost_usd": 0.0}
    if st is None or depth > 4:
        return out
    try:
        pairs = st.children_of(kind, obj_id)
    except objects.Refused:
        return out
    total = 0.0
    for child_kind, child_id in pairs:
        node = describe(child_kind, child_id) or {}
        if child_kind == "run":
            row = st.get_run(child_id)
            if row is not None:
                node.update({"state": runs.status_of(row), "policy": row.policy,
                             "workspace": row.workspace, "branch": row.branch,
                             "cost_usd": row.cost_usd})
                total += float(row.cost_usd or 0.0)
        elif child_kind == "artifact":
            row = st.get_artifact(child_id)
            if row is not None:
                node.update({"kind": row.kind, "path": row.path,
                             "version": row.head_version,
                             "body": _head_body(st, row)})
        inner = under(child_kind, child_id, depth + 1)
        node["children"] = inner["children"]
        total += float(inner.get("cost_usd") or 0.0)
        out["children"].append(node)
    out["cost_usd"] = round(total, 4)
    return out


def _head_body(st: objects.ObjectStore, row: objects.Artifact) -> str:
    """The newest version's body, trimmed to what a panel can hold."""
    for version in reversed(st.versions(row.id)):
        if version.body:
            return version.body[:4000]
    return ""


# ---------------------------------------------------------------------------
# A run's diff, as the artifact it is
# ---------------------------------------------------------------------------


def record_diff(run_id: str, changes: Mapping[str, Any]) -> str | None:
    """Write what a run did to the files, as an artifact the run owns and made.

    One artifact per run, versioned: a run that is asked twice gets a second
    version rather than a second card, so "its diff" is one thing wherever it
    ends up. Owned by the run, so it walks with the run into whatever the run
    is attached to, and `made` by the run as well, which is the reference that
    survives the run being deleted.

    Returns the artifact's id, or None when there was nothing to say.
    """
    st = store()
    if st is None or not run_id or st.get_run(run_id) is None:
        return None
    body = _diff_body(changes)
    if not body:
        return None
    try:
        mine = [aid for kind, aid in st.children_of("run", run_id, "artifact")
                if (row := st.get_artifact(aid)) is not None and row.kind == "diff"]
        if mine:
            artifact_id = mine[0]
        else:
            artifact_id = st.create_artifact("diff", DIFF_TITLE).id
            st.attach("run", run_id, "artifact", artifact_id)
            st.add_ref("made", "run", run_id, "artifact", artifact_id)
        latest = st.versions(artifact_id)
        if latest and (latest[-1].body or "") == body:
            return artifact_id
        st.add_version(artifact_id, body=body, made_by_run=run_id)
        return artifact_id
    except objects.Refused:
        log.exception("the store would not take the diff of run %s", run_id)
        return None


def _diff_body(changes: Mapping[str, Any]) -> str:
    """What a run changed, in the words `what_task_changed` already answers in."""
    lines: list[str] = []
    for commit in list(changes.get("commits") or [])[:20]:
        lines.append(f"commit {commit}")
    for stat in list(changes.get("diffstat") or [])[:20]:
        lines.append(str(stat).strip())
    for path in list(changes.get("files") or [])[:20]:
        lines.append(str(path))
    for left in list(changes.get("uncommitted") or [])[:10]:
        lines.append(f"uncommitted {str(left).strip()}")
    if changes.get("in_main"):
        lines.append("landed on main")
    return "\n".join(line for line in lines if line)[:8000]


# ---------------------------------------------------------------------------
# When a piece of work finished, and whether anybody has seen that it did
# ---------------------------------------------------------------------------
#
# Petar, 22 September 2026: "we should consider what counts as new with regards
# to tasks. I believe when a task is completed - the artifact done and ready to
# display, that's when a task/step is ready."
#
# So that is what "new" is here, and nothing else is. A task or a step is new
# from the moment **its artifact is ready to display** until the person opens
# it, and `task.seen_at` is the other half of that sentence: the moment they
# last did. Neither half is a guess about attention - nothing here counts a row
# as seen because it was drawn on a screen - because a dot that clears itself
# while you are looking somewhere else is the dot Petar already has.
#
# A third thing bounds both halves: nothing that finished before the person
# had an account is new (`objects.news_since`). A mark of 0 means "never
# opened", and on the first day that is true of the whole workspace they were
# given, which is how a new user's first screen came to carry a red dot for
# fifty-one tasks before they had pressed anything.


#: The files that are a finished artifact: the page a person reads. `step.md`
#: is one because a step Rouh files as plain text has no built page and is
#: drawn from that file (`steps.py`, `canvasStep` in static/app.js).
#:
#: What is deliberately not here is every other file in the folder.
#: `.object.json` and `AGENTS.md` are Rouh's own bookkeeping and
#: are rewritten whenever a row and its folder disagree
#: (`conversations.write_out`), so counting them would mark a task finished
#: every time Rouh tidied up after itself.
STEP_FILE = "step.md"

#: How far the steps of a task are followed. A step may hold steps of its own -
#: a task nests in a task, which is what makes it a step - and in this
#: workspace they go two deep at the most. The stop is here so that a link put
#: in the wrong place can never turn this walk into a spin.
MAX_STEPS_DEEP = 6


def _artifact_at(root: str, folder: str) -> tuple[str, float, float]:
    """One folder, in one scan: its page, when that page was ready, when
    anything in it last changed.

    The page is `index.html` where there is one, the only other `.html` where
    there is exactly one - the early tasks named a page after themselves and
    there is no ambiguity about which it is - and `step.md` otherwise.

    The two clocks are not the same question and are deliberately not one
    number. **Ready** is when the artifact was last written, and is the only
    thing a dot is ever compared against. **Changed** is when anything at all
    in the folder moved, and is only ever an order: the list puts the work
    somebody touched last at the top, and an edit to a note is a touch.
    """
    from . import objecttree

    if not root or not folder:
        return "", 0.0, 0.0
    here = os.path.join(root, folder)
    pages_here: list[tuple[str, float]] = []
    step_at = 0.0
    changed = 0.0
    try:
        with os.scandir(here) as entries:
            for entry in entries:
                try:
                    if not entry.is_file():
                        continue
                    when = entry.stat().st_mtime
                except OSError:
                    continue
                # Not the folder's own date nor the files that say how it is
                # organised: a rename or a move is not a change to the work
                # (`objecttree.ORGANISING`).
                if entry.name not in objecttree.ORGANISING:
                    changed = max(changed, when)
                low = entry.name.lower()
                if low.endswith(".html"):
                    pages_here.append((entry.name, when))
                elif low == STEP_FILE:
                    step_at = when
    except OSError:
        return "", 0.0, 0.0
    pages_here.sort()
    page, ready = "", 0.0
    for name, when in pages_here:
        if name.lower() == "index.html":
            page, ready = name, when
            break
    if not page and len(pages_here) == 1:
        page, ready = pages_here[0]
    if not page and step_at:
        page, ready = STEP_FILE, step_at
    return (f"{folder}/{page}" if page else ""), ready, changed


def _ready_at(row: objects.Task, artifact: float) -> float:
    """When this task or step last finished, or 0 for one that never has.

    Two ways a thing finishes and both count, and this is where the red dot's
    two meanings become one number.

    A task **stops**: `objects.STOPPED` says what that is - waiting, or done -
    and it is the rule the rail's dot has counted by since 22 September 2026.
    A step never stops in that sense. It has no state of its own worth the
    name, because it is the record of work already done, so what finishes it
    is **its artifact being written**: the moment its page is ready to display
    is the moment there is something to go and read.

    Both come back as one clock, so both are compared against `seen_at` the
    same way. That matters for the second half of what a person does with
    these: a page rewritten after they read it is new again, and a flag could
    not say so.

    **The stop is `closed_at` and nothing else.** It used to fall back to
    `updated_at`, then `created_at`, and neither is a stop: `updated_at` is
    rewritten on every row whenever the workspace's map grows
    (`objecttree.import_map`), so on 24 September 2026 at 02:35 fourteen
    waiting and done tasks Petar had cleared the afternoon before were lit
    again with nothing having happened to any of them; and `created_at` made
    every task that came in already waiting or done look as though it had
    stopped the moment it was read. A task with no `closed_at` has not
    stopped in front of Rouh, and only its page can make it new.
    """
    when = float(artifact or 0.0)
    if row.state in objects.STOPPED.get("task", ()) and row.closed_at:
        when = max(when, float(row.closed_at))
    return when


# ---------------------------------------------------------------------------
# What the page is told
# ---------------------------------------------------------------------------


_LEADING_NUMBER = re.compile(r"\d+(?:-\d+)*")


def _step_number(slug: str, above: str) -> str:
    """What a step is called on its line: `19-04` out of `19-04.packages`, and
    the whole of where it is when its folder says less than that.

    A step has no `number` of its own - step numbers repeat across the
    workspace and `task.number` is unique - so the name is where it is. The
    rail lists every task and every step on one flat line each (Petar, 23
    September 2026), so the number is the only thing on the line that says
    what a row is inside, and it has to say all of it. Most folders already
    do: `56-01.garden-shed-plans` is step 01 of task 56, and `56-01-01` is a
    step of that. The older ones say only their own place - `01-store-
    extraction` inside task 4, `02.parts-manuals` inside task 1 - and
    on a flat list "01" is a row of nothing, so the number of what holds it
    goes in front: `04-01`, `01-02`, and `01-02-01` under that.

    `above` is the holder's number as it is written in a folder name, two
    digits for a task. A folder with no number at all has none here either.
    The task browser keeps its own rule (`objectindex._step_number`), because
    there a step is drawn under its task and says only its own place.
    """
    head = _LEADING_NUMBER.match(str(slug or ""))
    own = head.group(0) if head else ""
    if not own or not above or own.startswith(above + "-"):
        return own
    return f"{above}-{own}"


class _TaskSnapshot:
    """The task tree and disk facts for one snapshot, never shared between calls."""

    def __init__(self, st: objects.ObjectStore) -> None:
        self.root = _workspace()
        self.rows = {t.id: t for t in st.list_tasks(limit=None)}
        self.since = objects.news_since()
        # What the person is called, which is what a waiting task's notes call
        # them when they say what it waits on them for (`waiting.names_of`).
        self.names = _names()
        # The tree, from the `owns` links: a step of a task is a task row owned by
        # a task, and that is the whole of what tells the two apart.
        self.under: dict[str, list[str]] = {}
        self.held_by: dict[str, str] = {}
        for src_type, src_id, dst_type, dst_id in st.owns_edges():
            if dst_type in objects.NESTS:
                self.under.setdefault(src_id, []).append(dst_id)
                self.held_by[dst_id] = src_id

        # The work, and not the steps of it, **at the top of the list**. A step is
        # drawn under the task that owns it instead, since 22 September 2026: it
        # has a dot of its own and there is nowhere else for that dot to be. It is
        # still kept out of `tasks` itself, because the owner dialog and the Start
        # box are drawn from that list and a picker offering two hundred steps
        # under the name of their folders is a picker nobody can use.
        #
        # What tells a step from a task is **being owned by a task**, not having no
        # number. It was the number until now, and that quietly took the loose
        # tasks with it: `new_task` makes one with no number and no folder on
        # purpose - "a task of its own, in no project" - so every task made with
        # New task was filtered out here and never appeared on the list the button
        # sits at the head of. Making something and watching nothing happen is the
        # whole of that bug.
        steps = {ident for ident, owner in self.held_by.items()
                 if self.rows.get(owner) is not None and ident in self.rows}
        # An archived task or step is not on this list, nor in the pickers drawn
        # from it: it is kept in the task browser's Archive, and under Archived on
        # its task's page (`archiving.py`). Its rows stay in `rows`, so a step of
        # an archived task is still known to be a step and is never mistaken for
        # a task of its own.
        self.hidden = {t.id for t in self.rows.values() if t.archived_at is not None}
        self.top = [t for t in self.rows.values()
                    if (t.number is not None or t.id not in steps) and t.id not in self.hidden]
        self.top_ids = {t.id for t in self.top}

        self.facts: dict[str, tuple[str, float, float]] = {}

    def _look(self, row: objects.Task) -> tuple[str, float, float]:
        if row.id not in self.facts:
            self.facts[row.id] = _artifact_at(self.root, row.folder)
        return self.facts[row.id]

    def _draw(self, row: objects.Task, depth: int, above: str = "") -> dict:
        """One task or step as the rail draws it, with whatever is under it.

        `new` is this row's own and nobody else's. The rail draws every task
        and every step as a line of its own, each with its own dot, and
        clears the one that was opened.

        `above` is the number of what holds this row, as a folder writes it,
        which is what a step's own number is written after (`_step_number`).
        """
        page, artifact, changed = self._look(row)
        ready = _ready_at(row, artifact)
        if depth:
            step = _step_number(row.slug or os.path.basename(row.folder or ""),
                                above)
            inside = step
        else:
            step = ""
            inside = f"{row.number:02d}" if row.number is not None else ""
        kids = [self._draw(self.rows[k], depth + 1, inside) for k in self.under.get(row.id, [])
                if k in self.rows and k not in self.top_ids and k not in self.hidden
                and depth < MAX_STEPS_DEEP]
        kids.sort(key=lambda k: -k["changed_at"])
        # When it was last worked on: its folder, its artifact or its stop,
        # and when it was made. **Never `updated_at`.** That is bookkeeping,
        # written on every row at once whenever the workspace's map grows
        # (`objecttree.import_map`), and read as a touch it put every task
        # the map knew at the top of the list in one tie and buried the ones
        # made since beneath them: on 24 September 2026 the seven red dots
        # of the night's work were the bottom rows of 253, under 245 rows
        # all "touched" at 02:35:07 when nothing had happened to any of them.
        # Petar: "at the very bottom I have the red dots on the new stuff we
        # did." The same rule, and the same reason, as `_ready_at` above.
        own = max(changed, ready, float(row.created_at or 0.0))
        moved = max([own] + [k["changed_at"] for k in kids])
        # What it is waiting on the person for, in its own notes' words: the
        # tooltip of the question mark on a waiting task's row in the rail
        # (`askMark`), and the same line the task browser writes under it
        # (`waiting.py`). Read only for a waiting row, which is a handful of
        # files, never all of them. The question as its meta puts it comes
        # first, and an answer already sent from the task's page takes the
        # mark off: it is waiting on the job that took the answer in now, not
        # on the person (`answering.py`). So does a question they dismissed.
        line, answered = "", None
        if row.state == "waiting":
            _question, _notes, line = answering.asked_of(self.root, row.folder or "", self.names)
            answered = answering.answers_to({row.id: line}).get(row.id)
        return {
            "id": row.id,
            "number": row.number,
            "step": step,
            "title": row.title,
            "state": row.state,
            "folder": row.folder,
            "pinned": bool(row.pinned),
            # Where its artifact is, so a press opens the finished thing
            # rather than a page listing it.
            "page": page,
            # `new` is this row's own: it has finished - stopped, or its
            # artifact written - since the person last looked at it, and
            # since they had an account at all.
            "new": ready > max(float(row.seen_at or 0.0), self.since),
            # And the plain mark beside it, which is what the rest of the page
            # already reads: whether they have looked at this at all since it
            # last stopped.
            "seen": bool(row.seen_at),
            "changed_at": moved,
            # And when this row itself last moved, not counting what is
            # under it, which is what the rail orders its flat list by: a step
            # written a minute ago is the line at the top, and the task that
            # holds it stays where its own last change puts it.
            "touched_at": own,
            # "" when it is not waiting, or its notes do not say what for.
            "asks": line,
            # What the person answered it, when they have and the job that
            # takes it in has not landed yet: "" otherwise.
            "answered": answered.answer if answered else "",
            # They closed its question without answering: it asks nothing of
            # them now, and nothing was sent anywhere.
            "dismissed": bool(answered and not answered.answer),
            "steps": kids,
        }

    def assemble(self) -> tuple[list[dict], dict[str, bool]]:
        drawn = [self._draw(t, 0) for t in self.top]
        for one in drawn:
            one["owned_by"] = owner_of("task", one["id"])
        # Petar, 22 September 2026: "the tasks and subtasks should be sorted by
        # latest being done/edited/modified/expanded." So the order is when the
        # work last moved, and a task counts whatever moved under it: filing a new
        # step into task 45 is task 45 being worked on, and a list that left it
        # where its own folder's date put it would bury the thing that just
        # happened. The pin is still over the top of this, on the page, where
        # every other list of the rail's puts it.
        drawn.sort(key=lambda t: -t["changed_at"])

        # A project shows a dot when anything under it is unseen, however deep:
        # project dot, task dot, step dot, which is the trail that was missing.
        # Walked here rather than on the page because the page has the tasks and
        # not the shape of the tree above them.
        unseen_under: dict[str, bool] = {}
        for one in drawn:
            if not _has_new(one):
                continue
            at = self.held_by.get(one["id"])
            seen_guard = 0
            while at and seen_guard < 20:
                if unseen_under.get(at):
                    break
                unseen_under[at] = True
                at = self.held_by.get(at)
                seen_guard += 1

        return drawn, unseen_under


def snapshot() -> dict:
    """The tasks, their steps, the projects, and what a new run may be started
    with.

    One message rather than four, for the same reason the chats and their
    folders are one: the page draws them together and half of it is not a
    picture of anything.
    """
    from . import starting

    sync()
    st = store()
    if st is None:
        return {"tasks": [], "projects": [], "workspaces": [], "policies": [],
                "owners_for": {}}
    drawn, unseen_under = _TaskSnapshot(st).assemble()

    return {
        # `pinned` is on every row because the rail draws the pinned ones
        # first and puts the mark on them, and because the row menu has to
        # know whether its first item reads Pin or Un-pin.
        # `seen` is the other mark, and both dots are drawn from it: whether
        # the person has looked at this task since it stopped. A flag rather
        # than the clock behind it, because the question the page asks of it
        # is "is there anything here I have not seen". `new` beside it is the
        # same question asked of this row's artifact as well, which is what a
        # step has instead of stopping.
        "tasks": drawn,
        # `folder` is what tells the two kinds of project apart: one of the
        # person's own projects for chats is a row and nothing else, and a
        # project of the workspace is a folder in the tree.
        "projects": [{"id": p.id, "title": p.title, "folder": p.folder,
                      "pinned": bool(p.pinned),
                      "new": bool(unseen_under.get(p.id))}
                     for p in st.list_projects(limit=200)],
        "workspaces": starting.workspaces(),
        "policies": list(objects.POLICIES),
        # The ranking itself, so the page has no copy of it to fall behind.
        # Generated from `objects.RANK`, which is where it lives.
        "owners_for": {kind: list(kinds) for kind, kinds in OWNERS_FOR.items()},
    }


def _names() -> tuple[str, ...]:
    """What the person this snapshot is for goes by: whoever is on the socket
    it is being made on (`tenancy.speaker`), or, made for no socket - a job
    finishing, a command - the install's one account. Nothing when there is
    no telling whose, which still finds "the person", "the user" and "you".

    The task browser's pages ask the same question of the request's own user,
    and both answer it with `waiting.names_of`, so a waiting task's row in the
    rail and the task browser never find two different questions in one
    task's notes. Until the two were joined up the rail read the notes with no
    name at all, and "**Waiting on Petar:** whether to start building ideas 1
    and 2 now" said nothing there for three of Petar's eleven waiting tasks.
    """
    from . import tenancy
    from .models import User

    try:
        who = tenancy.speaker() or tenancy.Tenancy().only_person()
        if who is None:
            return ()
        return waiting.names_of(User.objects.filter(pk=int(who.user_id)).first())
    except Exception:
        log.exception("could not tell whose names to read the waiting tasks with")
        return ()


def _has_new(row: Mapping[str, Any]) -> bool:
    """Whether this row or anything under it is finished and unseen."""
    if row.get("new"):
        return True
    return any(_has_new(kid) for kid in row.get("steps") or ())



# ---------------------------------------------------------------------------
# The two writes that change the shape of the workspace
# ---------------------------------------------------------------------------
#
# `objecttree.py` is the one create path and the one move path; this is where
# the task browser's filing reaches them (`objectindex.change`). Nothing here
# decides anything: it finds the workspace, calls, and turns a refusal into the
# same `{"ok": False, "why": ...}` the attach above hands back, so one sentence
# written in one place is what the person reads whichever way they asked.


def _workspace() -> str:
    """The person's workspace, if there is one on this machine to write into."""
    from .config import config

    root = config.assistant_repo or ""
    return root if root and os.path.isdir(root) else ""


def make(type: str, title: str, owner: str = "") -> dict:
    """Make a project, a task or a step, through the one create path."""
    from . import objecttree

    st = store()
    root = _workspace()
    if st is None or not root:
        return {"ok": False, "why": "There is no workspace on this machine."}
    try:
        made = objecttree.create(root, st, type=type, title=title, owner=owner)
    except objecttree.Refused as exc:
        return {"ok": False, "why": str(exc)}
    except OSError as exc:
        log.exception("a %s called %r could not be made", type, title)
        return {"ok": False, "why": f"It could not be written: {exc}"}
    return {"ok": True, "did": f"{made['title']} is at {made['rel']}", "made": made}


def move(ident: str, owner: str = "") -> dict:
    """Move an object under a different owner, through the one move path."""
    from . import objecttree

    st = store()
    root = _workspace()
    if st is None or not root:
        return {"ok": False, "why": "There is no workspace on this machine."}
    try:
        done = objecttree.move(root, st, ident, owner)
    except objecttree.Refused as exc:
        return {"ok": False, "why": str(exc)}
    except OSError as exc:
        log.exception("%s could not be moved", ident)
        return {"ok": False, "why": f"It could not be moved: {exc}"}
    if not done["moved"]:
        return {"ok": True, "did": "It is already there."}
    return {"ok": True, "did": f"{done['was']} is now {done['rel']} ({done['how']})",
            "moved": done}


def running_in(task_id: str) -> list[dict]:
    """The runs still working on this task, which a move would pull the floor from.

    Two ways a run is a task's: it is owned somewhere under it, or it was
    started from a conversation the task owns and carries only the `from`
    reference to it, which is how every job the voice starts is linked
    (`runtime.py`). Either one is working in a checkout that says the task's
    folder is where it was when the job began, and a folder moved under it
    makes its work land in the old place, or collide on the way in.
    """
    st = store()
    if st is None or not task_id:
        return []
    held = st.owned_tree("task", task_id, keep=KEEP)
    ids = {ident for kind, ident in held if kind == "run"}
    for kind, ident in held:
        if kind == "chat":
            ids.update(link.src_id for link in
                       st.refs("from", src_type="run", dst_type="chat", dst_id=ident))
    out = []
    for run_id in sorted(ids):
        row = st.get_run(run_id)
        if row is not None and row.state == "running":
            out.append({"id": run_id, "title": row.title})
    return out


def decorate(rows: Iterable[dict], kind: str, key: str = "id") -> list[dict]:
    """Put each row's owner, and the project over it, on a list the page has.

    One query for the whole list rather than one per row: the task list is
    rebuilt every time anything changes, and three hundred runs asking the
    same table three hundred separate questions is how a list gets slow
    without anybody noticing which change did it.

    `owned_by` is the thing directly above it, which may be a task, a chat or a
    project. `project_id` is the project the whole chain ends in, which is what
    a list groups by: a run under a task under Acme is in Acme, and
    nobody filed it there. It is the same walk `conversations._project_over`
    makes for a chat, over the same links, and it is "" for an orphan and for
    anything whose chain reaches the top without passing a project.
    """
    st = store()
    owners: dict[tuple[str, str], tuple[str, str]] = {}
    if st is not None:
        for link in st.refs(objects.OWNS):
            owners[(link.dst_type, link.dst_id)] = (link.src_type, link.src_id)

    def project_over(child_kind: str, child_id: str) -> str:
        walk = owners.get((child_kind, child_id))
        seen = 0
        while walk is not None and seen < len(objects.KINDS):
            if walk[0] == "project":
                return walk[1]
            walk = owners.get(walk)
            seen += 1
        return ""

    out = []
    # Many chats share one owner, and describing it is a read or two.
    described: dict[tuple[str, str], dict | None] = {}
    for row in rows:
        row = dict(row)
        ident = str(row.get(key) or "")
        found = owners.get((kind, ident))
        if found and found not in described:
            described[found] = describe(*found, owners=owners)
        row["owned_by"] = dict(described[found]) if found and described[found] else None
        row["project_id"] = project_over(kind, ident)
        out.append(row)
    return out


