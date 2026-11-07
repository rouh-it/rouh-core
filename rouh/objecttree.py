"""The workspace as a tree of objects, and the words in its files.

The person's workspace used to be a flat list: `tasks/NN.name`, every task
beside every other, with a category written down for each in
`_categories.json`. On 21 September 2026 it became a tree, and this module is
the join between that tree on disk and the rows in `objects.py`.

    workspace/
      work/                     a project, owned by nothing: a group
        acme/                   a project, owned by Work
          06.hiring-devs/       a task, owned by Acme
            06-03.round-three/  a task, owned by task 6
      private/
        personal/
          38.home-garden/
            38-01.soil-and-planting/

Three rules and no fourth: a project may own projects and tasks, a task may own
tasks, and a task may never own a project. There is no group object anywhere.
Work and Personal are ordinary top-level projects, and a project at the top with
no owner is a group, because that is what being at the top means.

## What makes a folder an object

**A folder with `.object.json` in it is an object, and nothing else is.** The
sidecar holds four things - a stable id, the type, the title and the owner's id
- and that is the whole of it. Which means the tree is self-describing: a walk
that finds sidecars finds the objects, at any depth, without knowing anything
about what folders are called, and a folder that is not an object (`source-code`,
`images`, `temp`) is skipped by the same rule that finds the ones that are.

The names still matter once, when a sidecar is first written for a folder that
has never had one (`ensure_sidecars`): under a project, `NN.name` is a task;
inside a task, `NN-MM.name` is a step, which is a task nested in a task; a
project is named rather than guessed at; and anything else is a folder and
stays one. After that the file is the answer and the name is only a name,
which is what lets a folder be renamed without the object becoming a different
object.

## Why most ids are a uuid and some are not

The sidecar's id is generated once and then never derived from anything again,
which is what makes it stable when a folder is renamed or moved. For a project
and for a step that is a uuid, because neither has ever had a name the rest of
Rouh calls it by.

**A numbered task keeps the id it already has.** `tasks/30.jarvis` has been
`task-30` everywhere in this machine since step four - `artifacts.task_id`
mints it, cards are filed under it, a conversation is owned by it - and minting
a uuid beside it would give the same task two identities to join on, which is
the one thing `objects.py` exists to be rid of. So a task folder named `NN.name`
is `task-NN`, written into the sidecar once like any other id.

A step's number is not unique - the workspace has two `30-12` folders and two
`30-20` folders - so a step is a uuid rather than `task-30-12`, and its `number`
column is left empty. `number` is the one the person says out loud, and they
never say a step's.

## The files own the words

Every AGENTS.md, every note and every built `index.html` stays a file on disk,
in git. None of that text goes into the database as the truth, because Claude
Code writes it with Read, Edit, Grep and Glob, and a bespoke API for editing a
paragraph would be used worse - and because the whole point of bringing the
workspace in with its 380 commits was to keep `git log --follow` and `git blame`
working on every line.

What the database gets is a **derived index**: for each object, the full text of
its own files and a sha256 of each. `reindex` rebuilds it from disk. It is
throwaway by design - lose it and it comes back - and it buys two things that
are hard without it: one search over everything, and a way to see that a file
has changed under a row.
"""
from __future__ import annotations

# Django first, before anything below that reads the database. This module is
# also a command a person runs (`python -m rouh.objecttree`), and then nothing
# else has set Django up by the time `objects` is imported; inside the server,
# where it already is, this does nothing.
from .project import setup as _setup_django

_setup_django()

import argparse
import contextlib
import hashlib
import html
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import unicodedata
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from django.db import DatabaseError, IntegrityError

from . import fileutil, instructions, objects, steps, taskrecord, workspace
from .config import WORKSPACE_MAP, config

log = logging.getLogger("rouh.objecttree")

#: The one file that makes a folder an object.
SIDECAR = ".object.json"

#: The files in a task's or a step's folder that say how it is organised
#: rather than what it holds: its name and where it is filed (`.object.json`).
#: A rename, a move or a renumber rewrites it and adds nothing to the work, so
#: neither it nor the folder's own date (which moves when it is replaced in
#: place, or a step folder is renamed) counts as the task being changed. Its
#: tags, steps and question are its row's (`rouh/taskmeta.py`), not a file's. Petar, 22 October 2026 (fr_ec1052293fb0): "Only content
#: inside that has been edited should nudge it up and update latest changes
#: date." Read by the task browser (`objectindex._facts`) and the rail
#: (`owning._artifact_at`), so the two lists agree.
ORGANISING = frozenset({SIDECAR})

#: The whole mapping, written when the tree was reshaped: old path, new path,
#: object id, type, owner id. At the workspace root, committed. The name is
#: `config.WORKSPACE_MAP`, because config has to know it as well: it is what
#: says a folder is a workspace Rouh can draw.
MAP_FILE = WORKSPACE_MAP

#: A task folder: the number the person says out loud, then its name.
TASK_FOLDER = re.compile(r"^(\d+)\.(.+)$")

#: A step folder written the way the workspace has written them since task 17:
#: the task's number, the step's number, the name.
STEP_FOLDER = re.compile(r"^(\d+)-(\d+)\.(.+)$")

#: What a step folder is called, at its loosest: a number and then anything.
#: The early tasks numbered their steps `01-store-extraction` and
#: `02-price-analysis`, and task 01 holds task 02's files in
#: `02.parts-manuals`. All of those are steps; `results`, `context`,
#: `source`, `vendor` and `screenshots` are not, and the number in front is
#: the whole of the difference.
STEP_NAME = re.compile(r"^\d+[-.]")

#: Folders that are never an object and are never walked into looking for one.
#: A step's `source-code` is the step's, not a task of its own.
NOT_OBJECTS = {
    "source-code", "temp", "images", "node_modules", ".git", ".venv", "venv",
    "__pycache__", "assets", "data", "img", "fonts",
}

#: Folders the content index does not read at all. Narrower than the one
#: above on purpose: `source-code` holds the scripts that built a page and is
#: worth searching, while `temp` is scratch by definition and `node_modules`
#: is somebody else's code.
NOT_INDEXED = {
    "temp", "node_modules", ".git", ".venv", "venv", "__pycache__",
    ".playwright-mcp",
}

#: What the content index reads. Anything else in a folder - a picture, a PDF,
#: a database - is a file the object has and not words anybody can search.
TEXT_SUFFIXES = {
    ".md", ".markdown", ".txt", ".html", ".htm", ".css", ".js", ".mjs", ".json",
    ".py", ".sh", ".yml", ".yaml", ".toml", ".csv", ".sql", ".svg",
}

#: A file bigger than this is indexed by its hash and the first of its words,
#: rather than whole. A built page with a picture inlined can be megabytes.
TEXT_MAX_BYTES = 1_200_000

#: The markup that is never words anybody searches for.
MARKUP = {".html", ".htm", ".svg"}
_SCRIPTS = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.I | re.S)
_COMMENTS = re.compile(r"<!--.*?-->", re.S)
_TAGS = re.compile(r"<[^>]+>")
_SPACES = re.compile(r"\s+")

class Refused(ValueError):
    """The tree would not take it, and the message says why."""


@dataclass
class Node:
    """One object, as the folder says it is."""

    rel: str                      # where it is, relative to the workspace root
    type: str                     # project or task
    id: str
    title: str
    owner: str | None             # the owner's id, or None at the top
    number: int | None = None
    slug: str = ""
    created_at: float | None = None
    children: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# The sidecars
# ---------------------------------------------------------------------------


def submodules(root: str | Path) -> set[str]:
    """Every path in `.gitmodules`, which is what says "another repository".

    Read rather than guessed at, and read from the file rather than from the
    folder's contents. "An empty folder" was the first answer, because a
    submodule that has not been checked out is empty and that is the shape
    task 08 has on this server - and then the first thing that wrote a file
    into it made it stop being another repository, and the object vanished off
    the screen. The file says what the file says whatever is on disk.
    """
    path = Path(root) / ".gitmodules"
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return set()
    return {found.strip() for found in
            re.findall(r"^\s*path\s*=\s*(.+)$", text, re.M)}


def another_repo(folder: Path, root: str | Path) -> bool:
    """Whether that folder is a git repository of its own rather than ours.

    Task 08 is: a property project is its own repository, kept here
    as a submodule, and the workspace's own rule is that a task which is its
    own repository is never written into.
    """
    try:
        rel = str(folder.resolve().relative_to(Path(root).resolve()))
    except ValueError:
        return False
    return rel in submodules(root) or (folder / ".git").exists()


def sidecar_path(folder: Path, root: str | Path) -> Path:
    """Where a folder's sidecar is, which is inside it unless it cannot be.

    A folder that is another repository gets its sidecar **beside** it instead,
    named after it: `.object.08.property-project.json` in the project
    that owns it. Nothing is written into the other repository, which is the
    workspace's own rule, and the object still exists, has an id, has an owner
    and is on the screen with everything else.
    """
    if another_repo(folder, root):
        return folder.parent / f".object.{folder.name}.json"
    return folder / SIDECAR


def read_sidecar(folder: Path, root: str | Path) -> dict | None:
    """What a folder says it is, or None when it says nothing."""
    path = sidecar_path(folder, root)
    try:
        with open(path, encoding="utf-8") as fh:
            body = json.load(fh)
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        raise Refused(f"{path} is not readable as JSON: {exc}") from exc
    if not isinstance(body, dict) or body.get("type") not in objects.NESTS:
        raise Refused(f"{path} does not say whether it is a project or a task")
    return body


def write_sidecar(folder: Path, node: dict, root: str | Path) -> None:
    """Write one sidecar, in the four fields and that order, atomically."""
    body = {"id": node["id"], "type": node["type"], "title": node["title"],
            "owner": node["owner"]}
    path = sidecar_path(folder, root)
    fileutil.write_json_atomic(path, body, end="\n", spare=path.with_name(path.name + ".new"),
                               tidy=False, indent=2, ensure_ascii=False)


def new_id(name: str, type: str, *, inside_a_task: bool) -> str:
    """The id a folder gets the first time it is given a sidecar.

    A numbered task under a project keeps `task-NN`, which is what the rest of
    this machine already calls it. Everything else is a uuid, generated once
    and written down, so a rename is a rename rather than a new object.

    A step is always a uuid, and that is load-bearing rather than tidy. Step
    numbers repeat - the workspace has two `30-12` folders and two `30-20` -
    and task 01 holds task 02's files in a folder called
    `02.parts-manuals`, which read as a number would be `task-2`, with
    `03.parts-pdfs` beside it colliding head-on with
    `03.market-research`. A step has no number anybody says out loud, so it
    gets no name made out of one.

    **`artifacts.task_id` is what makes the name, and it is asked rather than
    copied.** There are not two rules here; there was, for one day, and it cost
    a task browser that would not draw at all. This function stripped the
    leading zero and answered `task-1`, and `artifacts.task_id` kept it and
    answered `task-01`, which is what every row in the live database has been
    called since cards were first filed under one. So importing the map onto a
    database that already knew these tasks tried to make a second row with the
    same number, and SQLite refused it: `UNIQUE constraint failed: task.number`,
    on every one of the eight single-digit tasks.
    """
    if type == "task" and not inside_a_task and TASK_FOLDER.match(name):
        from . import artifacts

        return artifacts.task_id(name)
    return str(uuid.uuid4())


def is_a_task(name: str, *, inside_a_task: bool) -> bool:
    """Whether a folder's name says it is a task, given where it sits.

    Under a project a task is `NN.name`, the number the person says out loud.
    Inside a task anything starting with a number is a step, which is a task
    nested in a task, and anything else - `results`, `context`, `source`,
    `vendor`, `texts`, `screenshots` - is a folder holding something and stays
    one.
    """
    return bool(STEP_NAME.match(name) if inside_a_task else TASK_FOLDER.match(name))


def title_of(folder: Path, name: str, *, listed: bool = True) -> str:
    """The title for a folder, from its task's list of steps or its own name.

    A step's display title is written in its task's list of steps, in the
    task's meta (`rouh/taskmeta.py`), and is the name the person gave it rather than the
    folder they happened to type.
    """
    from . import taskmeta

    written = (taskmeta.steps_of(folder.parent).get(name) or {}) if listed else {}
    written = written.get("title") if isinstance(written, dict) else None
    if isinstance(written, str) and written.strip():
        return written.strip()
    return steps._words(name) or name


def _skip(name: str) -> bool:
    return name.startswith(".") or name in NOT_OBJECTS


def ensure_sidecars(root: str | Path, *, titles: dict[str, str] | None = None,
                    listed: bool = True) -> int:
    """Give every folder that is an object a sidecar, and leave the rest alone.

    Walks down from the top-level project folders. A folder that already has a
    sidecar keeps its id, whatever else has changed about it: the id is the
    identity and is never made twice. How many were written is the answer.

    **Three ways a folder is an object, and no fourth.** It already has a
    sidecar; or `titles` names it, which is how a project is declared; or its
    name is a numbered task under a project or a numbered step inside a task.
    Everything else - `source-code`, `images`, `results`, a folder somebody
    made to hold something - is a folder, and stays one.

    `titles` is keyed by the path relative to the root and says what each
    project is called, because a project's title is not its folder name: `acme`
    is "ACME", not "Acme". A project added later is declared the same way, or by
    writing its `.object.json` by hand.

    `listed` False names a new step by its folder alone, without asking its task's
    meta: for a workspace being built before any database is behind it.
    """
    root = Path(root)
    titles = titles or {}
    written = 0

    def walk(folder: Path, owner: str | None, inside_a_task: bool) -> None:
        nonlocal written
        rel = str(folder.relative_to(root))
        have = read_sidecar(folder, root)
        if have is None:
            if rel in titles:
                type = "project"
            elif is_a_task(folder.name, inside_a_task=inside_a_task):
                type = "task"
            else:
                return      # a folder, and not an object
            have = {"id": new_id(folder.name, type, inside_a_task=inside_a_task),
                    "type": type,
                    "title": titles.get(rel) or title_of(folder, folder.name, listed=listed),
                    "owner": owner}
            write_sidecar(folder, have, root)
            written += 1
        elif have.get("owner") != owner:
            have["owner"] = owner
            write_sidecar(folder, have, root)
            written += 1
        if another_repo(folder, root):
            return          # its insides are its own repository's business
        for child in sorted(folder.iterdir()):
            if child.is_dir() and not child.is_symlink() and not _skip(child.name):
                walk(child, have["id"], have["type"] == "task")

    for top in sorted(root.iterdir()):
        if not top.is_dir() or _skip(top.name):
            continue
        # A top-level folder is part of the tree because it is named as one, or
        # because it already has a sidecar. The workspace root also holds
        # control files, `_context`, `bin` and the retired proxy, and none of
        # those is an object.
        if top.name in titles or (top / SIDECAR).is_file():
            walk(top, None, False)
    return written


# ---------------------------------------------------------------------------
# The tree, read back off the disk
# ---------------------------------------------------------------------------


def read_tree(root: str | Path) -> list[Node]:
    """Every object folder under the root, parents before children.

    The sidecars are the whole of what is read: a folder with one is an object,
    a folder without one is not, and the owner is the nearest folder above it
    that has one. Nothing here reads a folder's name to decide anything.
    """
    root = Path(root)
    out: list[Node] = []

    def walk(folder: Path, owner: str | None, inside_a_task: bool) -> None:
        here = owner
        deeper = inside_a_task
        side = read_sidecar(folder, root)
        if side is not None:
            name = folder.name
            # Only a task under a project has a number. A step's number is not
            # unique and is not what anybody calls it, and `task.number` is
            # unique in the schema, so leaving it empty is the truth rather
            # than a gap.
            number = None
            if side["type"] == "task" and not inside_a_task and TASK_FOLDER.match(name):
                number = int(TASK_FOLDER.match(name).group(1))
            out.append(Node(
                rel=str(folder.relative_to(root)), type=side["type"], id=side["id"],
                title=side.get("title") or name, owner=side.get("owner"),
                number=number, slug=name))
            here = side["id"]
            deeper = side["type"] == "task"
        if another_repo(folder, root):
            return
        for child in sorted(folder.iterdir()):
            if child.is_dir() and not child.is_symlink() and not _skip(child.name):
                walk(child, here, deeper)

    for top in sorted(root.iterdir()):
        if top.is_dir() and not _skip(top.name):
            walk(top, None, False)
    return out


# ---------------------------------------------------------------------------
# The migration map
# ---------------------------------------------------------------------------


def first_seen(repo: str | Path, prefix: str) -> dict[str, float]:
    """When git first saw each file under a prefix, in one pass of the log.

    One `git log` for the whole workspace rather than one per folder: 380
    commits read once, against 400 objects asked one at a time.

    Rename detection is on, which is what makes the answer the date that
    matters. Without it the commit that reshaped the tree would look like 1,319
    files being added at once, and every task in the workspace would have been
    born on 21 September 2026. With it those are renames, `--diff-filter=A`
    passes over them, and what comes back is the day each file was really
    written - under the path it had then, which is why the lookup is by old
    path.
    """
    seen: dict[str, float] = {}
    try:
        out = subprocess.run(
            ["git", "log", "--reverse", "--format=@%at", "--name-only",
             "--find-renames", "--diff-filter=A", "--", prefix],
            cwd=str(repo), capture_output=True, text=True, timeout=600)
    except (OSError, subprocess.SubprocessError):
        return seen
    when = 0.0
    for line in out.stdout.splitlines():
        if line.startswith("@"):
            when = float(line[1:] or 0)
        elif line.strip():
            seen.setdefault(line.strip(), when)
    return seen


def old_path_of(rel: str, old_prefix: str = "tasks") -> str:
    """Where an object was before the tree was reshaped, or "" for a project.

    A task was at `tasks/NN.name`, and a step was inside it under a path that
    did not change, so the old path is the new one from the numbered task
    folder downwards with `tasks/` in front of it.
    """
    parts = Path(rel).parts
    for at, part in enumerate(parts):
        if TASK_FOLDER.match(part):
            return "/".join((old_prefix, *parts[at:]))
    return ""


def build_map(root: str | Path, repo: str | Path | None = None,
              old_prefix: str = "tasks") -> dict:
    """The whole mapping, as it is written to `_migration-map.json`.

    One entry per object: where it was before the tree was reshaped, where it
    is now, its id, its type, the id of whatever owns it, and the day git first
    saw anything in it. A project has no old path, because a project is what
    the reshaping made, and its date is the earliest of what it holds.
    """
    root = Path(root)
    repo = Path(repo) if repo else root
    inside = "" if repo.resolve() == root.resolve() else (
        str(root.resolve().relative_to(repo.resolve())) + "/")
    born = first_seen(repo, inside or ".")

    def dates_under(where: str) -> list[float]:
        # The exact path as well as everything under it: a task that is its
        # own repository is one gitlink in the log and has no files of its own.
        want = f"{inside}{where}"
        return [when for path, when in born.items()
                if where and (path == want or path.startswith(want + "/"))]

    nodes = read_tree(root)
    entries = []
    for node in nodes:
        old = old_path_of(node.rel, old_prefix) if node.type == "task" else ""
        # The old path first, because that is the name the log holds for
        # everything that was here before the reshaping. A task written since
        # then was never at `tasks/`, and the log holds it where it is, so the
        # new path is asked when the old one answers nothing. Without this a
        # task added after 21 September 2026 has no date at all.
        dates = dates_under(old) or dates_under(node.rel)
        entries.append({
            "old_path": old,
            "new_path": node.rel,
            "id": node.id,
            "type": node.type,
            "owner": node.owner,
            "title": node.title,
            "number": node.number,
            "slug": Path(node.rel).name,
            "created_at": min(dates) if dates else None,
        })

    # A project's date is the earliest date of anything under it, worked out
    # from the bottom up so a project of projects gets one too.
    by_id = {e["id"]: e for e in entries}
    for entry in sorted(entries, key=lambda e: -len(Path(e["new_path"]).parts)):
        owner = by_id.get(entry["owner"] or "")
        if owner is None or entry["created_at"] is None:
            continue
        if owner["created_at"] is None or entry["created_at"] < owner["created_at"]:
            owner["created_at"] = entry["created_at"]

    return {
        "about": (
            "Every object in this workspace: where it was before the tree was "
            "reshaped on 21 September 2026, where it is now, its stable id, "
            "whether it is a project or a task, and the id of whatever owns it. "
            "The same four fields are in each folder's .object.json; this file "
            "is all of them at once, and is what the database is imported from."
        ),
        "written_at": time.time(),
        "objects": entries,
    }


def read_map(root: str | Path) -> dict:
    """The committed mapping, or a refusal saying it is not there."""
    path = Path(root) / MAP_FILE
    try:
        with open(path, encoding="utf-8") as fh:
            body = json.load(fh)
    except (OSError, ValueError) as exc:
        raise Refused(f"{path} could not be read: {exc}") from exc
    if not isinstance(body, dict) or not isinstance(body.get("objects"), list):
        raise Refused(f"{path} does not hold a list of objects")
    return body


# ---------------------------------------------------------------------------
# Into the database
# ---------------------------------------------------------------------------


def import_map(root: str | Path, store: objects.ObjectStore) -> dict:
    """Make the database say exactly what the tree says, and answer with counts.

    Rows first, then the links, because a link needs both ends to be there. Run
    it twice and the second run writes nothing new: a row that is already there
    is updated to match the folder, and `attach` is one upsert.
    """
    body = read_map(root)
    entries = body["objects"]
    made = {"project": 0, "task": 0}
    changed = 0
    now = time.time()

    for entry in entries:
        type, ident = entry["type"], entry["id"]
        created = entry.get("created_at") or now
        if type == "project":
            if store.get_project(ident) is None:
                store.create_project(entry["title"], id=ident, number=entry.get("number"),
                                     slug=entry.get("slug") or "",
                                     status="open",
                                     folder=entry["new_path"], created_at=created,
                                     updated_at=now)
                made["project"] += 1
            else:
                store.update_project(ident, title=entry["title"],
                                     number=entry.get("number"),
                                     slug=entry.get("slug") or "",
                                     folder=entry["new_path"], updated_at=now)
                changed += 1
        else:
            if store.get_task(ident) is None:
                # Not started: the map says where a task is, never how far along
                # it is, which is the row's alone (`rouh/taskrecord.py`). What a
                # job said about it before it had a row is made now.
                store.create_task(entry["title"], id=ident, number=entry.get("number"),
                                  slug=entry.get("slug") or "", state="not-started",
                                  folder=entry["new_path"], created_at=created,
                                  updated_at=now, origin={})
                taskrecord.apply_pending(store, ident)
                made["task"] += 1
            else:
                # The title its folder says, where it says one: a task renamed
                # since the map was written has its new name in its
                # `.object.json` (`owning.rename`), and the map's line is the
                # name it had then.
                title = _title_on_disk(Path(root), entry["new_path"]) or entry["title"]
                # Never its status: until 6 October 2026 this put the map's
                # word for it back over every task's row whenever the map
                # grew, and only the next read of the files set them right
                # again.
                store.update_task(ident, title=title, number=entry.get("number"),
                                  slug=entry.get("slug") or "",
                                  folder=entry["new_path"], updated_at=now)
                changed += 1

    types = {e["id"]: e["type"] for e in entries}
    linked = 0
    for entry in entries:
        owner = entry.get("owner")
        if not owner:
            continue
        if owner not in types:
            raise Refused(f"{entry['new_path']} names an owner that is not in the map:"
                          f" {owner}")
        store.attach(types[owner], owner, entry["type"], entry["id"])
        linked += 1

    return {"projects": made["project"], "tasks": made["task"],
            "updated": changed, "links": linked, "objects": len(entries)}


# ---------------------------------------------------------------------------
# Checking it both ways
# ---------------------------------------------------------------------------


def has_map(root: str | Path) -> bool:
    """Whether this workspace has been reshaped and carries its mapping."""
    return bool(root) and (Path(root) / MAP_FILE).is_file()


def ensure_imported(root: str | Path, store: objects.ObjectStore) -> dict | None:
    """Take the tree in the first time Rouh is asked to draw it.

    Nothing runs the import by hand on a server, and nothing should: a
    workspace with a mapping in it and no rows for it is a workspace that has
    not been read yet, and reading it is what this does. It is skipped the
    moment the rows are there, so it costs one query on every later call.

    It is skipped once every object in the mapping has a row, rather than once
    the first one does. A workspace grows: a task written since the last import
    is a new line in the mapping and would otherwise never be read, and a task
    whose row was made before the tree existed - `task-50`, whose row pointed
    at a `tasks/` path that is not there any more - would go on pointing at
    nothing. One query answers it, over rows the caller is about to read anyway.

    A workspace with no mapping is not one Rouh draws, and this does nothing
    at all for it.
    """
    if not has_map(root):
        return None
    try:
        wanted = {entry["id"] for entry in read_map(root)["objects"]}
    except (Refused, KeyError, TypeError):
        return None
    if not wanted or wanted <= {row["id"] for row in store.objects()}:
        return None
    return import_map(root, store)


# ---------------------------------------------------------------------------
# The repairs the tree makes to itself
# ---------------------------------------------------------------------------
#
# `ensure_imported` above is how a workspace gets into the database the first
# time. This is the other half: what to do when the two have already come
# apart, which they had by 23 September 2026 in three ways the person could
# see on one screen.
#
# It runs wherever the tree is about to be drawn, because that is the moment
# a repair is worth anything, and it is cheap: one pass over the rows the
# caller is reading anyway, and it writes nothing at all when there is nothing
# wrong, which is every call after the first.


def _sidecar_id(root: Path, folder: str) -> str:
    """The id the folder itself says it has, or "" when it says nothing."""
    if not folder:
        return ""
    try:
        said = read_sidecar(root / folder, root)
    except (Refused, OSError):
        return ""
    return str((said or {}).get("id") or "")


def _title_on_disk(root: Path, folder: str) -> str:
    """The title the folder itself says it has, or "" when it says nothing."""
    if not folder:
        return ""
    try:
        said = read_sidecar(root / folder, root)
    except (Refused, OSError):
        return ""
    return str((said or {}).get("title") or "")


def _unshadow(root: Path, store: objects.ObjectStore, rows: dict) -> list[str]:
    """One folder, one object: any second row claiming a folder is removed.

    **This is what was wrong with Research and Personal.** Both are projects
    in the private column, and both had a *task* row pointing at the project's
    own folder as well - `task-research` at `private/research`, `task-personal` at
    `private/personal` - minted by `artifacts.ensure_task` from the parent of a
    page it was taking in. The task browser drew each of them as a task nobody
    had filed, under "Not sorted", carrying the eleven and the five tasks of
    the project it was standing in front of. Clicking one gave the project's
    contents, because it was the project's folder; dragging one did nothing a
    person could make sense of, because the project was not going anywhere.

    The sidecar decides, because the sidecar is what makes a folder an object
    and it names exactly one id. Where there is no sidecar to ask, a project
    keeps the folder: a project is a folder the person made and a task can
    always be given another one.

    What the loser owned is given to the keeper first - everything it owned,
    the pages and the chats as well as the tasks - and the row goes after with
    no cascade, so nothing is orphaned and nothing is taken away.
    """
    gone: list[str] = []
    claims: dict[str, list[str]] = {}
    for ident, row in rows.items():
        folder = str(row.get("folder") or "")
        if folder:
            claims.setdefault(folder, []).append(ident)
    for folder, idents in claims.items():
        if len(idents) < 2:
            continue
        said = _sidecar_id(root, folder)
        keeper = said if said in idents else next(
            (i for i in idents if rows[i]["type"] == "project"), idents[0])
        kind_of_keeper = rows[keeper]["type"]
        for ident in idents:
            if ident == keeper:
                continue
            for kind, child in store.children_of(rows[ident]["type"], ident):
                if not objects.may_own(kind_of_keeper, kind):
                    continue
                with contextlib.suppress(objects.Refused, DatabaseError):
                    store.attach(kind_of_keeper, keeper, kind, child)
            store.delete(rows[ident]["type"], ident, cascade=False)
            gone.append(ident)
            log.info("%s was a second row for the folder %s, which is %s: it is "
                     "gone and what it held is now %s's", ident, folder, keeper,
                     keeper)
    return gone


def _retitle_from_disk(root: Path, store: objects.ObjectStore,
                       rows: dict) -> list[str]:
    """A project whose sidecar has been renamed under it follows the sidecar.

    The folder is the derived half for nearly everything, and the one thing it
    is not derived about is what it says it is: `.object.json` is committed, it
    travels with the workspace, and a rename made in it is an inbound change to
    take in rather than an override to argue with. `conversations.reconcile`
    has done exactly this for a numbered task's title since the tree was
    reshaped; this is the same rule for a project, and it is how **Private
    became Personal** - two committed files and no migration to run by hand.

    Projects only. A task's title is also written in its folder's name and in
    its meta, and `reconcile` already owns that argument.
    """
    changed: list[str] = []
    for ident, row in rows.items():
        if row["type"] != "project":
            continue
        said = _title_on_disk(root, str(row.get("folder") or ""))
        if not said or said == (row["title"] or ""):
            continue
        store.update_project(ident, title=said, updated_at=time.time())
        changed.append(ident)
        log.info("the project %s is called %r on disk and %r in the database: "
                 "the database follows it", ident, said, row["title"])
    return changed


def _give_it_a_folder(root: Path, store: objects.ObjectStore, rows: dict,
                      owners: dict, ident: str, home: str) -> str:
    """One task row with no folder gets the folder it should have had.

    Written out exactly the way `create` writes one - the row is already there,
    so this is step two of that function and nothing else - and put inside
    `home`, the project it is to live in.

    A task with no folder is a task nothing can be done to: it cannot be
    opened, because there is no page anywhere to open; and it cannot be moved,
    because `move` has nothing to move and says so. "Weekend plans" was one
    of those, made by **New task** on 22 September 2026, and the whole of what
    the person could do with it was drag it somewhere and read the refusal.
    """
    row = rows[ident]
    holder = rows.get(home) if home else None
    parent = str((holder or {}).get("folder") or "") if holder else ""
    number = row.get("number")
    for _try in range(5):
        if number is None:
            number = store.next_task_number()
        name = f"{number}.{slug_of(row['title'] or row.get('slug') or '')}"
        rel = f"{parent}/{name}" if parent else f"{UNFILED}/{name}"
        if (root / rel).exists():
            number = None
            continue
        try:
            store.update_task(ident, number=number, slug=name, folder=rel)
        except IntegrityError:
            number = None
            continue
        _write_object(root, rel, ident, "task", row["title"], home or None, number)
        if holder is not None and owners.get(ident) != home:
            with contextlib.suppress(objects.Refused, DatabaseError):
                store.attach("project", home, "task", ident)
        row["folder"], row["number"], row["slug"] = rel, number, name
        log.info("%s had no folder in the workspace, so it was given %s", ident, rel)
        return rel
    log.warning("%s could not be given a folder in the workspace", ident)
    return ""


def _columns_are_folders(root: Path, store: objects.ObjectStore, rows: dict,
                         owners: dict) -> list[str]:
    """A project at the top with no folder is given one, beside Work and Personal.

    A project at the top is a column: the task browser draws every one of them
    as one (`objectindex._Tree.tops`), and Manage projects offers each of them
    as a place a project can go. Work and Personal are folders of the
    workspace, `work/` and `private/`, with an `.object.json` naming them.

    **This is what was wrong with Rouh.** 🪸Rouh was a chat folder the person
    made in the sidebar on 19 September 2026, and moving the chats onto the
    object model made it a project row with no folder - one of the person's
    own projects for chats - at the top. So it was a column and not one: Manage
    projects listed it beside Work and Personal and refused every press on it
    ("It has no folder in the workspace, so nothing in the workspace can go
    inside it"), and the task browser, which draws only a column that has a
    folder to file into, left it out. Petar, 29 September 2026: "get
    understanding of what kind of model Rouh is and if it is the same object
    type as work and personal and make it if it is not".

    So it is made one. Its row keeps its id, which is what every chat filed
    under it points at, so nothing it holds moves. Where a folder at the top
    already names that id - one committed to main, as `rouh/` was - that folder
    is the one it takes; otherwise one is written out the way `create` writes
    one, named for its title. The picture at the front of a sidebar project's
    name is left off the folder's title, because a folder of the workspace is
    drawn with the folder picture and its plain name, as Work and Personal are.
    """
    from . import chats

    made: list[str] = []
    for ident, row in rows.items():
        if row["type"] != "project" or row.get("folder") or owners.get(ident):
            continue
        rel = next((kid.name for kid in sorted(root.iterdir())
                    if kid.is_dir() and not _skip(kid.name)
                    and _sidecar_id(root, kid.name) == ident), "")
        title = " ".join((row["title"] or "").split())
        while title and chats.is_emoji(title[0]):
            title = title[1:].strip()
        title = title or row["title"] or "Project"
        if not rel:
            base = slug_of(title)
            rel = base
            for n in range(2, 50):
                if not (root / rel).exists():
                    break
                rel = f"{base}-{n}"
            else:
                log.warning("%s could not be given a folder in the workspace", ident)
                continue
            _write_object(root, rel, ident, "project", title, None, None)
        store.update_project(ident, title=_title_on_disk(root, rel) or title,
                             slug=rel, folder=rel, updated_at=time.time())
        row["folder"], row["slug"] = rel, rel
        made.append(ident)
        log.info("the project %s was at the top with no folder, so it is the column"
                 " %s in the workspace now", ident, rel)
    return made


def columns_are_folders(root: str | Path, store: objects.ObjectStore) -> list[str]:
    """`_columns_are_folders` on its own, for a project just made at the top.

    `tidy` does the same on its way to drawing the browser; this is for the
    sidebar's New project, so a project made at the top is a column with its
    folder from its first moment rather than from the next time the browser is
    opened. Never raises.
    """
    if not has_map(root):
        return []
    base = Path(root).resolve()
    try:
        with _one_at_a_time:
            rows, owners, _under = tree_now(store)
            made = _columns_are_folders(base, store, rows, owners)
    except Exception:
        log.exception("the columns at %s could not be given their folders", base)
        return []
    if made:
        _written()
        with contextlib.suppress(Exception):
            refresh(base, store, made)
    return made


def _no_project(rows: dict, owners: dict, ident: str) -> bool:
    """Whether this task is in no project: unowned, or under a column itself.

    A top-level project is a column - Work, Personal - and a task hanging
    straight off one of those is in none of the projects the person made, which
    is what the browser used to draw under "Not sorted".
    """
    owner = owners.get(ident)
    if owner is None:
        return True
    row = rows.get(owner)
    return row is not None and row["type"] == "project" and owners.get(owner) is None


def tidy(root: str | Path, store: objects.ObjectStore) -> dict:
    """Put right whatever the tree and the rows disagree about. Never raises.

    Four repairs, in this order because each needs the one before it:

    0. **a column with no folder** - a project at the top that is a row and
       nothing else is given its folder beside Work and Personal
       (`_columns_are_folders`);
    1. **two rows for one folder** - one of them goes, and what it held moves
       to the one the folder itself names (`_unshadow`);
    2. **a project renamed in its committed sidecar** - the row follows it
       (`_retitle_from_disk`);
    3. **a task in no project** - it goes into the fallback, folder and all,
       and one with no folder at all is given one on the way
       (`_give_it_a_folder`), so it can be opened and dragged like every other
       task on the board.

    The third is what makes the board honest now that there is no "Not sorted"
    heading on it. A task in no project has nowhere to be drawn, and a task
    that is not drawn is worse than one under a heading nobody likes, so the
    answer is that there is no such task rather than that the page hides it.
    It costs nothing on a workspace that is already in order.

    It cannot take a decision away from the model that files a new task,
    because Miscellaneous is not a decision: `server.NewTasks` goes on asking
    about a task that is sitting in the fallback and moves it when it has an
    answer.

    Called wherever the browser is about to be drawn. It is a read and nothing
    else on every call but the first, so it costs one pass over rows the
    caller has already asked for.
    """
    counts = {"columns": 0, "unshadowed": 0, "retitled": 0, "given_a_folder": 0,
              "filed": 0}
    if not has_map(root):
        return counts
    base = Path(root).resolve()
    fresh: list[str] = []
    try:
        with _one_at_a_time:
            rows, owners, _under = tree_now(store)
            columns = _columns_are_folders(base, store, rows, owners)
            counts["columns"] = len(columns)
            fresh.extend(columns)
            gone = _unshadow(base, store, rows)
            counts["unshadowed"] = len(gone)
            if gone:
                rows, owners, _under = tree_now(store)
            counts["retitled"] = len(_retitle_from_disk(base, store, rows))
            adrift = [ident for ident, row in rows.items()
                      if row["type"] == "task" and _no_project(rows, owners, ident)]
            if adrift:
                from . import filing

                home = filing.where_it_goes(store)
                if home and rows.get(home, {}).get("folder"):
                    for ident in adrift:
                        if not (rows[ident].get("folder") or ""):
                            if _give_it_a_folder(base, store, rows, owners,
                                                 ident, home):
                                counts["given_a_folder"] += 1
                                fresh.append(ident)
                            continue
                        # It has a folder, so it moves the one move path's
                        # way: the link first, then `git mv`, so the history
                        # keeps following the folder. A refusal is said out
                        # loud rather than swallowed: it is the one shape of
                        # this that does not mend itself, and it would
                        # otherwise be tried again on every page load with
                        # nothing anywhere saying why.
                        try:
                            move(base, store, ident, home)
                        except (Refused, OSError, objects.Refused) as exc:
                            log.warning("%s is in no project and could not be "
                                        "filed into %s: %s", ident, home, exc)
                            continue
                        counts["filed"] += 1
                        log.info("%s was in no project, so it was filed into %s",
                                 ident, home)
    except Exception:
        # Derived work on a page somebody is waiting for: a repair that cannot
        # be made is never a reason the board does not draw.
        log.exception("the workspace tree at %s could not be tidied", base)
        return counts
    if any(counts.values()):
        log.info("the workspace tree was tidied: %s", counts)
        _written()
    if fresh:
        # A folder written a moment ago has files in it nothing has read.
        with contextlib.suppress(Exception):
            refresh(base, store, fresh)
    return counts


def ensure_indexed(root: str | Path, store: objects.ObjectStore) -> dict | None:
    """Build the derived content index the first time, if nobody ever has.

    The rows and the links take themselves in (`ensure_imported`); the content
    index did not, and so on this server it was empty from the day stage four
    shipped until stage five looked at it: 241 object rows, 238 owner links,
    and **nought files indexed**, because `reindex` is a command and no command
    is run on a server. `drift` said every indexed file still hashed to what
    the index held, which is true of nothing and was the one answer that did
    not read like a gap.

    So it builds itself, once, on the same rule as the import: nothing there
    means it has not been read yet, and reading it is what this does. It is
    skipped in one query the moment any file is indexed, so the cost of asking
    is a `SELECT` on every later call.

    **It is not for a request to call.** Indexing the workspace reads every
    file of every object - thousands of them, hundreds of megabytes - which is
    seconds of work, so it belongs on a thread at start-up and nowhere near a
    page somebody is waiting for. `refresh` is the one a create and a move
    call, and it only ever touches what changed.
    """
    if not has_map(root):
        return None
    try:
        if store.content_counts()[0]:
            # Built, but perhaps before every CLAUDE.md became an AGENTS.md
            # (26 September 2026, `rouh/instructions.py`): then it names files
            # that are not there any more, and search opens nothing. Built
            # again once, the first time Rouh starts after the rename.
            gone = [p for p in store.content_paths_named(instructions.OLD_NAME)
                    if not (Path(root) / p).is_file()]
            if not gone:
                return None
            log.info("the content index names %d %s file(s) that are not there any "
                     "more, so it is being built again", len(gone), instructions.OLD_NAME)
            counts = reindex(root, store)
            log.info("the content index: %s file(s) under %s object(s)",
                     counts["files"], counts["objects"])
            return counts
    except DatabaseError:
        return None
    log.info("the content index is empty, so it is being built from %s", root)
    counts = reindex(root, store)
    log.info("the content index: %s file(s) under %s object(s)",
             counts["files"], counts["objects"])
    return counts


def verify(root: str | Path, store: objects.ObjectStore) -> dict:
    """Does the database say what the tree says, and is it a tree at all.

    Four questions, and the answer names every object that fails one:

    - every object folder on disk has a row;
    - every row that names a folder has that folder on disk. A row that names
      no folder at all is not in the tree and is not claiming to be: a chat
      folder in the rail is a `project` row with nothing on disk behind it, and
      calling that a disagreement would make this say the workspace and the
      database had come apart every time somebody made one;
    - nothing is owned twice, which the database itself refuses but which is
      asked again here because a file can be older than the index that refuses
      it;
    - following ownership upwards from every object reaches a top with no
      owner, so there is no ring.
    """
    root = Path(root)
    on_disk = {node.id: node for node in read_tree(root)}
    rows = {row["id"]: row for row in store.objects()}

    missing_row = sorted(rel for ident, node in on_disk.items()
                         if ident not in rows for rel in [node.rel])
    missing_folder = []
    wrong_folder = []
    for ident, row in rows.items():
        if not row["folder"]:
            continue
        node = on_disk.get(ident)
        if node is None:
            missing_folder.append(f"{row['type']} {ident} ({row['folder']})")
        elif node.rel != row["folder"]:
            wrong_folder.append(f"{ident}: the row says {row['folder']!r},"
                                f" the disk says {node.rel!r}")
        elif not (root / row["folder"]).is_dir():
            missing_folder.append(f"{row['type']} {ident} ({row['folder']})")

    owners: dict[str, list[str]] = {}
    for src_type, src_id, dst_type, dst_id in store.owns_edges():
        if dst_type in objects.NESTS:
            owners.setdefault(dst_id, []).append(src_id)
    owned_twice = sorted(f"{ident} is owned by {', '.join(who)}"
                         for ident, who in owners.items() if len(who) > 1)

    rings = []
    for ident in rows:
        seen = {ident}
        at = (owners.get(ident) or [None])[0]
        while at is not None:
            if at in seen:
                rings.append(f"{ident} is inside itself, through {at}")
                break
            seen.add(at)
            at = (owners.get(at) or [None])[0]

    wrong_owner = []
    for ident, row in rows.items():
        for who in owners.get(ident, []):
            owner_row = rows.get(who)
            if owner_row is None:
                continue
            if not objects.may_own(owner_row["type"], row["type"]):
                wrong_owner.append(f"a {owner_row['type']} owns a {row['type']}:"
                                   f" {who} owns {ident}")

    tops = sorted(rows[i]["title"] for i in rows if not owners.get(i))
    counts = {
        "folders": len(on_disk),
        "rows": len(rows),
        "projects": sum(1 for r in rows.values() if r["type"] == "project"),
        "tasks": sum(1 for r in rows.values() if r["type"] == "task"),
        "owns_links": sum(len(v) for v in owners.values()),
        "at_the_top": tops,
    }
    problems = {
        "folders_with_no_row": missing_row,
        "rows_with_no_folder": sorted(missing_folder),
        "rows_pointing_elsewhere": sorted(wrong_folder),
        "owned_twice": owned_twice,
        "rings": sorted(set(rings)),
        "owners_the_rules_refuse": sorted(wrong_owner),
    }
    return {"counts": counts, "problems": problems,
            "ok": not any(problems.values())}


# ---------------------------------------------------------------------------
# Making one, and moving one
# ---------------------------------------------------------------------------
#
# **This is the one create path and the one move path, and there is no other.**
# Reading the tree was solved on 21 September 2026 and writing it was not:
# everything that made an object still made a folder first, picked its number
# by reading the folder names beside it, and left the rows to catch up. So two
# things answered "what is the next number" - a walk on disk and a column - and
# they disagreed the moment anything was renamed.
#
# Now the row is made first, in one transaction with its owner link
# (`objects.create_owned`), and the folder, the AGENTS.md and the `.object.json`
# are written out of that row. A move is the same shape the other way up: the
# link table first, then `git mv`, so the history keeps following the folder.
#
# The three rules are asked at the point of the write and nowhere else: a
# project may own projects and tasks, a task may own tasks, and **a task may
# never own a project**. `objects.may_own` is where they live; this asks it and
# turns a no into a sentence a person can read.


#: One create or move at a time in this process. The number of a step is not a
#: unique column - step numbers repeat across the workspace, there are two
#: `30-12` folders - so the thing that keeps two filings from picking the same
#: one is this lock and, behind it, a `mkdir` that refuses a folder already
#: there. A numbered task has the unique index on `task.number` as well.
_one_at_a_time = threading.RLock()

#: Told whenever the shape of the tree on disk changes here - an object made,
#: moved or removed - and handed nothing, because what changed is read back off
#: the checkout. The running server puts its save in it (`rouh/saving.py`), so
#: what Rouh makes reaches main; the command a job runs in its own checkout puts
#: nothing, because that job's commit is its save.
WRITTEN: list = []


def _written() -> None:
    for tell in WRITTEN:
        with contextlib.suppress(Exception):
            tell()


def _highest_on_disk(root: Path) -> int:
    """The highest task number any folder in the workspace carries, or 0.

    A numbered task's folder is `NN.slug`; a step's is `NN-NN.slug` and is not
    counted. Nothing below a step is walked: that is where the pages and their
    pictures are, and there is no task in there.
    """
    top = 0
    for dirpath, dirnames, _files in os.walk(root):
        keep = []
        for name in dirnames:
            if _skip(name) or name in ("node_modules", "source-code", ".git"):
                continue
            found = re.match(r"^(\d+)\.", name)
            if found:
                top = max(top, int(found.group(1)))
            keep.append(name)
        # Below a step there is nothing numbered, only what the step made.
        dirnames[:] = [] if re.match(r"^\d+-\d+\.", os.path.basename(dirpath)) else keep
    return top


#: Where an object with no owner goes: a task made before anybody has said
#: which project it belongs to. A conversation promoted into work is that - it
#: has a number the moment it is promoted and no project until it is filed.
#:
#: **Nothing stays here.** Until 23 September 2026 the task browser drew what
#: was here under a "Not sorted" heading above the two columns, and that
#: heading is gone: a task that landed here is filed within seconds by the
#: model that reads what each project is for, and one it cannot place goes to
#: the fallback (`rouh/filing.py`). Anything still here when the tree is next
#: read is filed by `tidy` above, so this is the few seconds between a task
#: being made and being filed and is never a place work sits.
#:
#: It was `tasks/` until 21 September 2026, which was every task's folder while
#: the workspace was flat; there is no `tasks/` in the tree, so a task written
#: there would be a folder nothing draws and nothing walks.
UNFILED = "unfiled"

#: What a new numbered task's AGENTS.md says on the day it is made. The
#: workspace's own rule is that a task has one and that it reads with the
#: current position first, so this is the shortest thing that is true: nothing
#: has happened yet.
NEW_TASK_NOTES = """# {number}. {title}

**Status:** not started.

## Where this is

Nothing has been done yet. Made on {when}.
"""


# Cyrillic to Latin for a folder name: the official Bulgarian system (the
# Transliteration Act of 2009), with the Russian, Ukrainian, Serbian and
# Macedonian letters Bulgarian lacks added alongside. A Cyrillic title used to
# lose every letter and become "N.object"; "Годишна инвентаризация на склада"
# is now 6.godishna-inventarizatsiya-na-sklada.
_CYRILLIC = str.maketrans({
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ж": "zh",
    "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n",
    "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f",
    "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sht", "ъ": "a", "ь": "y",
    "ю": "yu", "я": "ya",
    # Russian and Belarusian
    "ё": "yo", "ы": "y", "э": "e", "ў": "u",
    # Ukrainian
    "є": "ye", "і": "i", "ї": "yi", "ґ": "g",
    # Serbian and Macedonian
    "ђ": "dj", "ћ": "c", "џ": "dz", "ј": "j", "љ": "lj", "њ": "nj",
    "ѓ": "gj", "ќ": "kj", "ѕ": "dz",
})


# Latin letters that are not a plain letter with an accent on it, so taking
# the accent off (below) leaves them as they were and they would be dropped.
_LATIN = str.maketrans({
    "ß": "ss", "æ": "ae", "œ": "oe", "ø": "o", "ł": "l", "đ": "d", "ð": "d",
    "þ": "th", "ı": "i", "ħ": "h", "ŋ": "ng",
})


def _dashed(said: str) -> str:
    said = re.sub(r"[^a-z0-9]+", "-", said).strip("-")
    return re.sub(r"-{2,}", "-", said)[:48].strip("-")


def slug_of(title: str) -> str:
    """A folder's slug from a title: lower case, words joined by dashes.

    One rule for a folder name, in one place. The emoji a chat's title starts
    with is not part of a folder name, and neither is a comma, so both come off
    here rather than becoming a row of dashes. Cyrillic is written in Latin
    letters first, so a Bulgarian title gives a name a person can read, and an
    accented Latin letter loses its accent rather than the letter: "Café
    Žižek" is cafe-zizek, where it was caf-i-ek.

    A title with nothing left after that is named for its pictures. Petar named
    a project "💸" on 13 October 2026 (fr_d4e957a75d90) and it became the
    folder `object`, as did every other title of emoji alone, so the second one
    in a column was refused with "There is already a folder at rouh/object". It
    would be `money-with-wings` now. A title in a script with no Latin spelling here,
    such as Chinese, is still "object", and `create` gives it a free name.
    """
    said = (title or "").lower().translate(_CYRILLIC).translate(_LATIN)
    said = "".join(ch for ch in unicodedata.normalize("NFKD", said)
                   if not unicodedata.combining(ch))
    slug = _dashed(said)
    if not slug:
        slug = _dashed(" ".join(
            unicodedata.name(ch, "").lower() for ch in (title or "")
            if unicodedata.category(ch).startswith("S")))
    return slug or "object"


def _free_folder(root: Path, rows: dict, rel: str) -> str:
    """`rel`, or `rel-2`, `rel-3` and on, whichever no folder and no row has.

    Two names can make one slug - "Sales" and "Sales!", or two titles in a
    script the slug cannot spell - and a project's folder has no number in
    front to tell them apart, so the second takes the next free one rather
    than being refused.
    """
    taken = {str(row.get("folder") or "") for row in rows.values()}
    base, n = rel, 1
    while (root / rel).exists() or rel in taken:
        n += 1
        rel = f"{base}-{n}"
    return rel


def tree_now(store: objects.ObjectStore) -> tuple[dict, dict, dict]:
    """The rows, who owns each, and what each owns. One pass, three answers."""
    rows = {row["id"]: row for row in store.objects()}
    owner: dict[str, str] = {}
    under: dict[str, list[str]] = {}
    for src_type, src_id, dst_type, dst_id in store.owns_edges():
        if dst_type in objects.NESTS and dst_id in rows and src_id in rows:
            owner[dst_id] = src_id
            under.setdefault(src_id, []).append(dst_id)
    return rows, owner, under


def _number_above(rows: dict, owner: dict, ident: str) -> int | None:
    """The number of the numbered task this sits inside, walking up.

    A step is called `30-06` because it is the sixth step of task 30, and a
    step of a step keeps the same front: what the person says out loud is the
    task's number, and everything under it wears it.
    """
    at: str | None = ident
    seen: set[str] = set()
    while at is not None and at not in seen:
        seen.add(at)
        row = rows.get(at)
        if row is None:
            return None
        if row.get("number") is not None:
            return int(row["number"])
        at = owner.get(at)
    return None


def _next_step_number(rows: dict, under: dict, owner_id: str,
                      task_number: int | None) -> str:
    """The next free step number inside a task, out of the rows.

    A step folder is `30-09.something`, so the next one is the highest second
    number among what this task already owns, plus one. Read off the rows'
    slugs - which are the folder names the rows themselves hold - rather than
    off a walk of the directory, because the rows are what the number is
    allocated from now and a folder somebody made by hand is a row by the time
    this is asked (`ensure_imported`).
    """
    highest = 0
    for child in under.get(owner_id, []):
        found = STEP_FOLDER.match(rows[child].get("slug") or "")
        if found and (task_number is None or int(found.group(1)) == task_number):
            highest = max(highest, int(found.group(2)))
    nth = highest + 1
    return f"{task_number}-{nth:02d}" if task_number is not None else f"{nth:02d}"


def _may_hold(owner_row: dict | None, type: str, what: str) -> None:
    """The three rules, at the point of the write, in a sentence.

    A project may own projects and tasks, a task may own tasks, and a task may
    never own a project. Nothing here is a new rule: `objects.may_own` is the
    rule, and this is what a refusal reads like on a screen.
    """
    if owner_row is None:
        return
    if not objects.may_own(owner_row["type"], type):
        raise Refused(
            f"“{owner_row['title']}” is a task, and a task may never hold a "
            f"project. A project goes under a project, or at the top on its own. "
            f"Put “{what}” somewhere else.")
    if not owner_row.get("folder"):
        raise Refused(
            f"“{owner_row['title']}” is one of your own projects for chats. "
            "It has no folder in the workspace, so nothing in the workspace can go "
            "inside it.")


def _write_object(root: Path, rel: str, ident: str, type: str, title: str,
                  owner: str | None, number: int | None) -> None:
    """The folder, its sidecar, and a task's AGENTS.md, written out of the row,
    and a task's empty list of steps put on the row.

    This direction and never the other: the row exists by the time anything is
    made on disk, so a folder here can never be an object the database has not
    heard of.
    """
    folder = root / rel
    folder.mkdir(parents=True)
    steps.own_as_workspace(folder, root)
    write_sidecar(folder, {"id": ident, "type": type, "title": title,
                           "owner": owner}, root)
    steps.own_as_workspace(sidecar_path(folder, root), root)
    if type == "task" and number is not None:
        page = folder / instructions.NAME
        page.write_text(NEW_TASK_NOTES.format(
            number=number, title=title,
            when=time.strftime("%-d %B %Y")), encoding="utf-8")
        steps.own_as_workspace(page, root)
        # A list of its steps, empty, which makes it a task that keeps one
        # (`steps.note_step`): its row's, never a file (`rouh/taskmeta.py`).
        from . import taskmeta

        taskmeta.change_id(ident, lambda was: was if was is not None else {"steps": {}})


def create(root: str | Path, store: objects.ObjectStore, *, type: str, title: str,
           owner: str = "") -> dict:
    """Make a project, a task or a step. The row first, then the folder.

    In this order, and the order is the whole of it:

    1. the id and the number are allocated out of the object rows, inside the
       transaction that writes the row and its `owns` link
       (`objects.create_owned`);
    2. the folder, the `.object.json` sidecar and, for a numbered task, its
       AGENTS.md are written out of that row;
    3. the content index for the new object is refreshed.

    Never the other way round, and never by reading the folder names beside it
    for the next free number. A numbered task takes the next free
    `task.number`, which is a unique column, so two creates in the same instant
    cannot both keep it: the second insert is refused and this asks again. A
    step takes the next number inside the task that owns it, and has no
    `number` of its own - step numbers repeat across the workspace and
    `task.number` is unique, so leaving it empty is the truth rather than a gap.

    `owner` is the id of whatever holds it, and "" is the top: a project with
    no owner is a group, and a task with no owner goes to `unfiled/` until
    somebody files it.
    """
    from . import artifacts

    root = Path(root).resolve()
    type = (type or "").strip().lower()
    if type not in objects.NESTS:
        raise Refused("An object in the workspace is a project or a task, "
                      "and nothing else.")
    title = " ".join(str(title or "").split())
    if not title:
        raise Refused("It needs a name.")
    with _one_at_a_time:
        ensure_imported(root, store)
        rows, owners, under = tree_now(store)
        owner_row = None
        if owner:
            owner_row = rows.get(owner)
            if owner_row is None:
                raise Refused(f"There is nothing in the workspace with the id {owner}.")
        _may_hold(owner_row, type, title)
        slug = slug_of(title)
        pair = ((owner_row["type"], owner_row["id"]) if owner_row else None)

        if type == "task" and (owner_row is None or owner_row["type"] == "project"):
            parent = owner_row["folder"] if owner_row else UNFILED
            row = None
            on_disk = _highest_on_disk(root)
            for _try in range(5):
                # And past any task already on disk that no row has taken in
                # yet: a job lands its task on main, the landing moves this
                # checkout onto it, and until something reads the tree again
                # the rows do not know. Handing out that number is how one
                # number came to be two tasks.
                number = max(store.next_task_number(), on_disk + 1)
                # And past a number a task gave up to go inside another task,
                # whose row is still called by it (`free_task_number`).
                while store.get_task(artifacts.task_id(f"{number}.x")) is not None:
                    number += 1
                name = f"{number}.{slug}"
                rel = f"{parent}/{name}"
                try:
                    row = store.create_owned(
                        "task", title, owner=pair, id=artifacts.task_id(name),
                        number=number, slug=name, folder=rel)
                    break
                except IntegrityError:
                    # Somebody else took that number between the read and the
                    # write. The unique index is what decides that race, and
                    # losing it is not losing the task: ask again.
                    log.warning("task number %s was taken; asking for the next", number)
            if row is None:
                raise Refused("No free task number could be found.")
            ident, number_of = row.id, row.number
        else:
            if type == "task":
                label = _next_step_number(
                    rows, under, owner_row["id"],
                    _number_above(rows, owners, owner_row["id"]))
                name = f"{label}.{slug}"
            else:
                name = slug
            rel = f"{owner_row['folder']}/{name}" if owner_row else name
            if type == "project":
                rel = _free_folder(root, rows, rel)
                name = rel.rsplit("/", 1)[-1]
            ident, number_of = str(uuid.uuid4()), None
            row = store.create_owned(type, title, owner=pair, id=ident, slug=name,
                                     folder=rel)

        try:
            if (root / rel).exists():
                raise Refused(f"There is already a folder at {rel}.")
            _write_object(root, rel, ident, type, title, owner or None, number_of)
            if owner_row is not None and owner_row["type"] == "task":
                # A step, so it goes in the task's list of steps as well: the
                # workspace's own rule is that a step missing from that list
                # lands in a "Not in a group yet" column on the task's page.
                steps.note_step(root / owner_row["folder"], name, title, root)
        except BaseException:
            # Nothing half-made. The row was the first thing written and it is
            # the first thing taken back, so a create that could not reach the
            # disk leaves the database exactly as it found it.
            #
            # Without the cascade, and it is the one place that asks for that:
            # a row made a moment ago owns nothing, and taking a create back is
            # not a person deleting anything.
            if type == "task":
                store.delete_task(ident, cascade=False)
            else:
                store.delete_project(ident)
            raise
        # The owner changed too where it keeps a list of its steps, so it is
        # indexed again beside the new object rather than left a step behind.
        refresh(root, store, [ident] + ([owner] if owner else []))
    log.info("made the %s %s at %s", type, ident, rel)
    _written()
    return {"id": ident, "type": type, "title": title, "rel": rel, "name": name,
            "number": number_of, "owner": owner or None}


def move(root: str | Path, store: objects.ObjectStore, ident: str,
         owner: str = "", *, renumber: bool = False) -> dict:
    """Reparent an object: the link table first, then the folder with `git mv`.

    The one move path. Whatever files a card into a task, whatever the person
    drags on a screen, and the command below all come through here, so the
    one-owner index and the tree on disk can never say different things.

    In this order:

    1. the three rules are asked, and a move that would put a project inside a
       task is refused with a sentence saying why;
    2. the `owns` link is written, which is one upsert - so there is never a
       moment where the object has two owners or none - and a move that would
       put something inside itself is refused there;
    3. the folder is moved with `git mv`, so `git log --follow` and `git blame`
       go on reaching the commit that wrote each line. A workspace that is not
       a git checkout is moved with a plain rename instead;
    4. the row's folder, and the folder of everything under it, follow; so do
       the paths of every artifact whose file is in there, the sidecar's owner,
       and the content index for all of them.

    If the folder will not move, the link is put back, because a row that says
    one thing and a disk that says another is the state this whole stage exists
    to make impossible.

    `renumber` is the person's own Move, from the three dots on a task's or a
    subtask's page (`rouh/moving.py`). Petar, 29 September 2026
    (fr_2c31bc88941c): "We want to be able to move any subtask or task to any
    other task or project. If moved to project it becomes top level task with
    the next available number". So a task may go inside a task, and gives up
    its number to be that task's next subtask (`62-16`); a subtask put in a
    project takes the next free task number; and every subtask inside what
    moved takes the new number in front of its own (`61-02` becomes
    `62-02`). A task that already has a number and goes to another project
    keeps it, because it is the number the person says out loud. Without it,
    a folder keeps its name, and a numbered task is never put in a task.
    """
    root = Path(root).resolve()
    with _one_at_a_time:
        ensure_imported(root, store)
        rows, owners, under = tree_now(store)
        node = rows.get(ident)
        if node is None:
            raise Refused(f"There is nothing in the workspace with the id {ident}.")
        was = node.get("folder") or ""
        if not was:
            raise Refused(f"“{node['title']}” has no folder in the workspace, "
                          "so there is nothing to move.")
        owner_row = None
        if owner:
            owner_row = rows.get(owner)
            if owner_row is None:
                raise Refused(f"There is nothing in the workspace with the id {owner}.")
            if owner_row["id"] == ident:
                raise Refused("Nothing can be put inside itself.")
        _may_hold(owner_row, node["type"], node["title"])
        if (not renumber and owner_row is not None and owner_row["type"] == "task"
                and node.get("number") is not None):
            raise Refused(
                f"Task {node['number']} has a number you say out loud, and a step "
                "inside a task has none. Moving it there would take its number "
                "away, so it stays under a project.")

        # Inside itself. `objects.attach` refuses this too, in the same
        # transaction it would write the edge in, and that refusal names ids
        # rather than titles because that module has no screen in mind. This is
        # the one a person reads, so it is asked here first and says what they
        # pressed.
        at = owner_row["id"] if owner_row else None
        seen: set[str] = set()
        while at is not None and at not in seen:
            if at == ident:
                raise Refused(
                    f"\u201c{owner_row['title']}\u201d is already inside "
                    f"\u201c{node['title']}\u201d, so it cannot hold it as well.")
            seen.add(at)
            at = owners.get(at)

        name = was.rsplit("/", 1)[-1]
        number: int | None | _Keep = KEEP
        if renumber and node["type"] == "task":
            if owners.get(ident) == (owner_row["id"] if owner_row else None):
                return {"id": ident, "rel": was, "moved": False,
                        "how": "it is already there"}
            name, number = _renumbered(root, store, rows, owners, under, node,
                                       owner_row)
        if owner_row is None:
            to = f"{UNFILED}/{name}" if node["type"] == "task" else name
        else:
            to = f"{owner_row['folder']}/{name}"
        if to == was:
            # The folder is already where it belongs, and the link may not be.
            # A task folder written by hand is taken in as a row with no owner
            # (`conversations.reconcile`), and `tidy` filed task 58 into Misc
            # on every page load while this said "already there" and wrote
            # nothing: the log said it was filed, and the board, which draws
            # only a task that is in a project, never showed it.
            want = owner_row["id"] if owner_row else None
            if owners.get(ident) == want:
                return {"id": ident, "rel": was, "moved": False,
                        "how": "it is already there"}
            if owner_row is None:
                store.detach(node["type"], ident)
            else:
                try:
                    store.attach(owner_row["type"], owner_row["id"], node["type"], ident)
                except objects.Refused as exc:
                    raise Refused(str(exc)) from exc
            side = read_sidecar(root / was, root)
            if side is not None and side.get("owner") != want:
                side["owner"] = want
                write_sidecar(root / was, side, root)
                steps.own_as_workspace(sidecar_path(root / was, root), root)
            log.info("%s was already in %s, and is filed under %s now", ident, was,
                     want or "nothing")
            return {"id": ident, "rel": was, "moved": False, "owner": want,
                    "how": "it was already there, and is filed there now"}
        if node["type"] == "project":
            # A project moved to another column keeps its name where it can,
            # and takes the next free one where that column has it already.
            to = _free_folder(root, rows, to)
        if (root / to).exists():
            raise Refused(f"There is already a folder at {to}.")

        before = owners.get(ident)
        if owner_row is None:
            store.detach(node["type"], ident)
        else:
            try:
                store.attach(owner_row["type"], owner_row["id"], node["type"], ident)
            except objects.Refused as exc:
                raise Refused(str(exc)) from exc
        try:
            how = _move_folder(root, was, to)
        except BaseException:
            if before and before in rows:
                store.attach(rows[before]["type"], before, node["type"], ident)
            else:
                store.detach(node["type"], ident)
            raise

        # The subtasks inside it, where the number in front of theirs changed,
        # and what the task pages say about where each of them is.
        renamed: list[tuple[str, str, str]] = []
        if not isinstance(number, _Keep):
            old_front = (node.get("number") if node.get("number") is not None
                         else _number_above(rows, owners, before or ""))
            new_front = (number if number is not None
                         else _number_above(rows, owners, owner_row["id"]
                                            if owner_row else ""))
            if old_front is not None and new_front is not None \
                    and int(old_front) != int(new_front):
                renamed = _renumber_inside(root, to, int(old_front), int(new_front))
            _restep(root, was, to, node["title"], owner_row, renamed)

        def now_of(here: str) -> str:
            now = to + here[len(was):]
            for parent, old, new in renamed:
                at = f"{parent}/{old}"
                if now == at or now.startswith(at + "/"):
                    now = f"{parent}/{new}" + now[len(at):]
            return now

        # Every row whose folder was under the old path, this one included.
        moved = []
        for row in rows.values():
            here = row.get("folder") or ""
            if here == was or here.startswith(was + "/"):
                now = now_of(here)
                if row["type"] == "task":
                    change: dict = {"folder": now}
                    if now.rsplit("/", 1)[-1] != here.rsplit("/", 1)[-1]:
                        change["slug"] = now.rsplit("/", 1)[-1]
                    if row["id"] == ident and not isinstance(number, _Keep):
                        change["number"] = number
                    store.update_task(row["id"], **change)
                elif now.rsplit("/", 1)[-1] != here.rsplit("/", 1)[-1]:
                    store.update_project(row["id"], folder=now,
                                         slug=now.rsplit("/", 1)[-1])
                else:
                    store.update_project(row["id"], folder=now)
                moved.append(row["id"])

        # And every artifact whose bytes are a file under that folder. A page
        # built into a step is named by `artifact.path`, which is a file and
        # not a folder, so it was left behind by every move until 23 September
        # 2026: a task moved from Personal to Misc went on listing its own page
        # at the Personal address, and pressing it answered 404 on a white
        # screen. The folder moved, so the rows that name files in it move too.
        for art in store.artifacts_under(was):
            here = str(art.path or "")
            store.update_artifact(art.id, path=now_of(here))
        side = read_sidecar(root / to, root)
        if side is not None:
            side["owner"] = owner or None
            write_sidecar(root / to, side, root)
            steps.own_as_workspace(sidecar_path(root / to, root), root)
        # The content index names a file against the nearest object above it,
        # and a subtask with no `.object.json` of its own is part of its
        # task's files, not an object: so the objects it was inside and is
        # inside now are read again too. Until 1 October 2026 only the moved
        # rows were, and search went on finding such a subtask's pages at the
        # folder it had left, under the task it had left, and not at all
        # where it was.
        held = {_holder(root, was.rpartition("/")[0]), _holder(root, to.rpartition("/")[0])}
        refresh(root, store, list(dict.fromkeys(moved + sorted(h for h in held if h))))
        # And every share, comment and Ask AI row that names a page under
        # it, so a link somebody was sent keeps opening the same page
        # (`rouh/pageplaces.py`).
        from . import pageplaces

        pageplaces.moved(root, was, now_of)
    log.info("moved %s from %s to %s (%s)", ident, was, to, how)
    _written()
    done = {"id": ident, "rel": to, "was": was, "moved": True, "how": how,
            "owner": owner or None, "objects": len(moved)}
    if not isinstance(number, _Keep):
        done["number"] = number
        done["renumbered"] = [f"{parent}/{new}" for parent, _old, new in renamed]
        # And what each was called, in the same order: the numbers a move took
        # away are kept on the rows (`moving.remember`).
        done["renumbered_from"] = [old for _parent, old, _new in renamed]
    return done


def _holder(root: Path, folder: str) -> str:
    """The id of the nearest object at or above `folder`: whose files its files are."""
    parts = [p for p in str(folder or "").split("/") if p]
    while parts:
        try:
            side = read_sidecar(root.joinpath(*parts), root)
        except (Refused, OSError):
            side = None
        if side and side.get("id"):
            return str(side["id"])
        parts.pop()
    return ""


class _Keep:
    """A number `move` leaves as it is, which None cannot say: None is a
    number taken away."""


KEEP = _Keep()

#: What is in front of a task's or a step's name: `62.`, `62-09.`, and the
#: early tasks' `01-`. What follows it is the name, which a move keeps.
_FRONT = re.compile(r"^\d+(?:-\d+)?[-.]")


def _renumbered(root: Path, store: objects.ObjectStore, rows: dict, owners: dict,
                under: dict, node: dict, owner_row: dict | None) -> tuple[str, int | None | _Keep]:
    """The folder name a task moved by the person gets, and its number.

    Into a task, the next subtask number there and no number of its own. Into
    a project, the number it has when it has one, and the next free task
    number when it was a subtask.
    """
    name = str(node.get("folder") or "").rsplit("/", 1)[-1]
    rest = _FRONT.sub("", name, count=1) or name
    if owner_row is not None and owner_row["type"] == "task":
        front = _number_above(rows, owners, owner_row["id"])
        return f"{_next_step_label(root, rows, under, owner_row, front)}.{rest}", None
    if node.get("number") is not None:
        return name, KEEP
    number = free_task_number(root, store)
    return f"{number}.{rest}", number


def free_task_number(root: Path, store: objects.ObjectStore) -> int:
    """The next task number nobody has: not a row's, not a folder's, and not
    the one in front of a row's id (`task-61`), which a task put inside
    another task keeps after it has given its number up."""
    from . import artifacts

    number = max(store.next_task_number(), _highest_on_disk(root) + 1)
    while store.get_task(artifacts.task_id(f"{number}.x")) is not None:
        number += 1
    return number


def _next_step_label(root: Path, rows: dict, under: dict, owner_row: dict,
                     front: int | None) -> str:
    """The next subtask number inside a task, out of its rows and its folder.

    `_next_step_number` reads the rows alone, which is right for a step Rouh
    makes; most steps are folders a job wrote and no row has heard of, and a
    subtask moved in has to go after those too, or it lands on one of them.
    """
    names = [rows[c].get("slug") or "" for c in under.get(owner_row["id"], [])]
    names += [str(rows[c].get("folder") or "").rsplit("/", 1)[-1]
              for c in under.get(owner_row["id"], [])]
    try:
        with os.scandir(root / owner_row["folder"]) as found:
            names += [e.name for e in found if e.is_dir(follow_symlinks=False)]
    except OSError:
        pass
    highest = 0
    for name in names:
        step = STEP_FOLDER.match(name)
        if step and (front is None or int(step.group(1)) == front):
            highest = max(highest, int(step.group(2)))
        elif front is None and re.match(r"^(\d+)[-.]", name):
            highest = max(highest, int(re.match(r"^(\d+)", name).group(1)))
    nth = highest + 1
    return f"{front}-{nth:02d}" if front is not None else f"{nth:02d}"


def _renumber_inside(root: Path, top: str, old: int, new: int) -> list[tuple[str, str, str]]:
    """Every subtask folder under `top` that wears `old` in front, given `new`.

    Parents before their children, and each as (the folder it is in, now; its
    old name; its new name), which is the order `move` maps paths in. Only the
    folders that are subtasks are walked, the way `_contents` finds them: what
    a subtask made - its pages, its `source-code` - keeps its names.
    """
    done: list[tuple[str, str, str]] = []
    todo = [top]
    while todo:
        here = todo.pop(0)
        try:
            with os.scandir(root / here) as found:
                names = sorted(e.name for e in found
                               if e.is_dir(follow_symlinks=False) and not _skip(e.name)
                               and STEP_NAME.match(e.name))
        except OSError:
            continue
        for name in names:
            step = STEP_FOLDER.match(name)
            now = name
            if step and int(step.group(1)) == old:
                want = f"{new}-{step.group(2)}.{step.group(3)}"
                if not (root / here / want).exists():
                    _move_folder(root, f"{here}/{name}", f"{here}/{want}")
                    done.append((here, name, want))
                    now = want
            todo.append(f"{here}/{now}")
    return done


def _restep(root: Path, was: str, to: str, title: str, owner_row: dict | None,
            renamed: list[tuple[str, str, str]]) -> None:
    """What the tasks' lists of steps say, after a move by the person.

    The task it left stops naming it, the task it went into names it with what
    the old one said about it (its group is the old task's, and stays there),
    and every task one of its subtasks was renumbered in says the new name.
    """
    old_parent, _, old_name = was.rpartition("/")
    new_name = to.rsplit("/", 1)[-1]
    said = steps.listed_steps(root / old_parent).get(old_name) if old_parent else None
    if old_parent:
        steps.forget_step(root / old_parent, old_name, root)
    if owner_row is not None and owner_row["type"] == "task":
        about = said.get("description") if isinstance(said, dict) else None
        steps.note_step(root / owner_row["folder"], new_name, title, root,
                        description=about or None)
    for parent, old, new in renamed:
        steps.rename_step(root / parent, old, new, root)


def _git_root(root: Path) -> Path | None:
    """The git checkout the workspace is in, or None when it is not in one."""
    try:
        out = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=str(root),
                             capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    found = out.stdout.strip()
    return Path(found) if out.returncode == 0 and found else None


def _move_folder(root: Path, was: str, to: str) -> str:
    """Move an object's folder, with `git mv` wherever git knows the path.

    `git mv` rather than a rename, because the history has to keep following.
    The whole point of bringing this workspace in with its 380 commits was that
    `git log --follow` and `git blame` on any file in it still reach the commit
    that wrote the line, and a move git was not told about is a delete and an
    add. A workspace that is not a checkout - a copy a world stood up - is
    renamed instead, and says so.
    """
    (root / to).parent.mkdir(parents=True, exist_ok=True)
    repo = _git_root(root)
    if repo is not None:
        src = (root / was).relative_to(repo)
        dst = (root / to).relative_to(repo)
        done = subprocess.run(["git", "mv", "--", str(src), str(dst)],
                              cwd=str(repo), capture_output=True, text=True,
                              timeout=300)
        if done.returncode == 0:
            _move_beside(root, was, to)
            return "git mv"
        log.warning("git mv %s %s said: %s", src, dst, done.stderr.strip())
    os.rename(root / was, root / to)
    _move_beside(root, was, to)
    return "renamed"


def _move_beside(root: Path, was: str, to: str) -> None:
    """Carry a sidecar that sits beside its folder rather than inside it.

    A task that is its own git repository is never written into, so its
    `.object.json` lives in the project above it under the folder's name
    (`sidecar_path`). `git mv` of the folder knows nothing about that file, so
    it is moved here or the object loses its identity on the way.
    """
    old = root / was
    new = root / to
    beside = old.parent / f".object.{old.name}.json"
    if not beside.is_file():
        return
    want = new.parent / f".object.{new.name}.json"
    if beside.resolve() == want.resolve():
        return
    want.parent.mkdir(parents=True, exist_ok=True)
    repo = _git_root(root)
    if repo is not None:
        done = subprocess.run(
            ["git", "mv", "--", str(beside.relative_to(repo)), str(want.relative_to(repo))],
            cwd=str(repo), capture_output=True, text=True, timeout=120)
        if done.returncode == 0:
            return
    os.rename(beside, want)


# ---------------------------------------------------------------------------
# Taking one out of the workspace
# ---------------------------------------------------------------------------


def erase(root: str | Path, idents: Iterable[str], folders: Iterable[str]) -> dict:
    """Take deleted objects out of the workspace: their folders and the map.

    The other end of `create`, and it has to do both halves for the same reason
    that one does. The folder is obvious. The map file is not, and leaving it
    is what would make a delete come undone: `ensure_imported` reads
    `_migration-map.json` on the next page load, notices an id in it with no
    row, and writes the row again. A task deleted at four o'clock would be back
    at five past, with its number, under its old owner.

    So the entries go with the folders, in one write, and the rows are already
    gone by the time this is called. Nothing here raises: what is on disk is
    derived from the rows, and a folder that could not be removed is litter to
    be said in the log rather than a reason to put a deleted object back.

    A folder inside another folder being removed is skipped, because removing
    the outer one already took it.
    """
    root = Path(root).resolve()
    gone = {"folders": [], "left": [], "entries": 0}
    for rel in _outermost(folders):
        if _remove_folder(root, rel):
            gone["folders"].append(rel)
        elif _already_gone(root, rel):
            # A row whose folder had gone before it did (fr_bb3ff32f17b9, a
            # subtask moved away under a row of its own): nothing to remove,
            # and it is still a folder that went, so the page drawing it takes
            # itself off it (`canvasLeftBehind` in app.js).
            gone["folders"].append(rel)
        else:
            gone["left"].append(rel)
    gone["entries"] = _forget_in_map(root, set(idents), list(folders))
    if gone["folders"]:
        _written()
    return gone


def _outermost(folders: Iterable[str]) -> list[str]:
    """The folders to remove, with anything already inside one of them dropped."""
    clean = sorted({str(f).strip().strip("/") for f in folders if str(f).strip()},
                   key=lambda f: (len(Path(f).parts), f))
    keep: list[str] = []
    for rel in clean:
        if any(rel == held or rel.startswith(held + "/") for held in keep):
            continue
        keep.append(rel)
    return keep


def _already_gone(root: Path, rel: str) -> bool:
    """Whether nothing at all is at that path under the workspace."""
    if not rel or rel.startswith("/") or ".." in Path(rel).parts:
        return False
    return not os.path.lexists(root / rel)


def _inside(root: Path, rel: str) -> Path | None:
    """That folder, if it really is one and really is under the workspace."""
    if not rel or rel.startswith("/") or ".." in Path(rel).parts:
        log.warning("refusing to remove %r: it is not a path inside the workspace", rel)
        return None
    whole = (root / rel)
    try:
        real = whole.resolve()
    except OSError:
        return None
    if real == root or root not in real.parents:
        log.warning("refusing to remove %s: it is not inside %s", rel, root)
        return None
    return whole if whole.is_dir() and not whole.is_symlink() else None


def _remove_folder(root: Path, rel: str) -> bool:
    """One object's folder, with `git rm` wherever git knows the path.

    `git rm -r` rather than a plain delete, for the mirror of the reason
    `_move_folder` uses `git mv`: the removal is staged, so the next commit in
    the workspace says the folder was deleted instead of leaving it as an
    unstaged disappearance somebody has to notice. A workspace that is not a
    checkout, or a path git has never heard of, is removed outright.
    """
    whole = _inside(root, rel)
    if whole is None:
        return False
    repo = _git_root(root)
    if repo is not None:
        # `-f`, because a file edited since the last commit is still a file
        # that is being deleted on purpose: without it `git rm` refuses the
        # whole folder over one modified file and leaves the deletion
        # unstaged, which is a delete nobody committing the workspace would
        # notice. The rows are already gone; this is the derived half.
        done = subprocess.run(
            ["git", "rm", "-r", "-q", "-f", "--ignore-unmatch", "--",
             str(whole.relative_to(repo))],
            cwd=str(repo), capture_output=True, text=True, timeout=300)
        if done.returncode != 0:
            log.warning("git rm %s said: %s", rel, done.stderr.strip())
    # `git rm` leaves anything it did not track, and there is no repository at
    # all in a world stood up from a copy, so the folder is finished off here
    # either way.
    shutil.rmtree(whole, ignore_errors=True)
    # The sidecar of a task that is its own repository sits beside the folder
    # rather than inside it, so `git rm` of the folder never touched it.
    beside = whole.parent / f".object.{whole.name}.json"
    with contextlib.suppress(OSError):
        beside.unlink()
    if whole.exists():
        log.warning("the folder %s could not be removed", rel)
        return False
    # `git rm -r` takes away a parent directory it has just emptied, and the
    # parent here is the folder of the project this one was in - an object of
    # its own, with a row that is not being deleted. So it is put back: a
    # project whose last task goes is an empty project, not a missing one.
    with contextlib.suppress(OSError):
        whole.parent.mkdir(parents=True, exist_ok=True)
    log.info("removed the folder %s", rel)
    return True


def _forget_in_map(root: Path, idents: set[str], folders: list[str]) -> int:
    """Take the deleted objects out of `_migration-map.json`. Says how many went.

    By id, and by path as well: an object made since the map was last written
    has no entry, and one whose folder was inside a deleted folder has an entry
    that names a path which is not there any more.
    """
    path = root / MAP_FILE
    if not path.is_file():
        return 0
    try:
        body = read_map(root)
    except Refused:
        log.warning("%s could not be read, so nothing was taken out of it", path)
        return 0
    under = [f.strip("/") for f in folders if f.strip("/")]

    def goes(entry: dict) -> bool:
        if entry.get("id") in idents:
            return True
        where = str(entry.get("new_path") or "").strip("/")
        return bool(where) and any(where == rel or where.startswith(rel + "/")
                                   for rel in under)

    kept = [e for e in body["objects"] if not goes(e)]
    went = len(body["objects"]) - len(kept)
    if not went:
        return 0
    body["objects"] = kept
    body["written_at"] = time.time()
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(body, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
    except OSError:
        log.exception("%s could not be written", path)
        return 0
    log.info("took %d object(s) out of %s", went, path)
    return went


def refresh(root: str | Path, store: objects.ObjectStore,
            which: list[str] | None = None) -> dict:
    """Rebuild the content index for the objects that have just changed.

    The index is derived and throwaway, and it is also the thing that goes
    stale first: a folder that moved has a different path against every one of
    its files. So a create and a move each end here, with the ids they touched,
    rather than leaving the whole workspace to be rebuilt by somebody later.

    Nothing to refresh is nothing done, and deliberately not the whole
    workspace: `reindex` takes an empty `only` to mean everything, which is
    right for the command and would be a thousand files read by a create that
    happened to touch nothing.
    """
    if not which:
        return {"objects": 0, "files": 0}
    return reindex(root, store, only=which)


# ---------------------------------------------------------------------------
# The derived content index
# ---------------------------------------------------------------------------


def sha256_of(path: Path) -> tuple[str, int]:
    """The sha256 of a file's bytes, and how many there were."""
    digest = hashlib.sha256()
    size = 0
    with open(path, "rb") as fh:
        while True:
            block = fh.read(1 << 16)
            if not block:
                break
            size += len(block)
            digest.update(block)
    return digest.hexdigest(), size


def words_of(path: Path) -> str:
    """The words in a file, as a person would read them.

    A built page is markup, a style sheet, a script and often a picture
    inlined as base64, and none of that is anything anybody searches for. What
    goes into the index is what the page says: the scripts and styles taken
    out, the tags taken out, the entities turned back into characters. A Markdown
    note or a piece of source goes in as it is, because there every character
    is already something somebody wrote.
    """
    try:
        with open(path, "rb") as fh:
            raw = fh.read(TEXT_MAX_BYTES).decode("utf-8", "replace")
    except OSError:
        return ""
    if path.suffix.lower() not in MARKUP:
        return raw
    text = _COMMENTS.sub(" ", _SCRIPTS.sub(" ", raw))
    return _SPACES.sub(" ", html.unescape(_TAGS.sub(" ", text))).strip()


def files_of(root: Path, node: Node, others: set[str]) -> list[Path]:
    """The files that belong to one object and to no object inside it.

    A task's own notes and its built page are the task's. Its steps' files are
    its steps', and are indexed under them, which is what `others` keeps out.
    """
    folder = root / node.rel
    out: list[Path] = []

    def walk(at: Path) -> None:
        for child in sorted(at.iterdir()):
            if child.is_symlink():
                continue
            if child.is_dir():
                if child.name.startswith(".") or child.name in NOT_INDEXED:
                    continue
                if str(child.relative_to(root)) in others:
                    continue
                walk(child)
            elif child.is_file() and not child.name.startswith("."):
                out.append(child)

    if folder.is_dir() and not another_repo(folder, root):
        walk(folder)
    return out


def reindex(root: str | Path, store: objects.ObjectStore,
            only: str | list[str] | set[str] = "") -> dict:
    """Rebuild the content index from the files on disk.

    Every object's rows are written afresh, so a file that was deleted leaves
    nothing behind and a file that changed moves its hash and its words in the
    same write. `only` narrows it to one object id, or to several: a check of
    somebody's own wants one, and a move that carried a task and its twenty-six
    steps to a different path wants all twenty-seven, because every one of them
    has a different path against every one of its files now.
    """
    root = Path(root)
    wanted = {only} if isinstance(only, str) and only else set(only or ())
    tree = read_tree(root)
    others = {node.rel for node in tree}
    files = 0
    objects_done = 0
    for node in tree:
        if wanted and node.id not in wanted:
            continue
        rows = []
        for path in files_of(root, node, others - {node.rel}):
            if workspace.is_secret_name(path.name):
                continue
            digest, size = sha256_of(path)
            body = words_of(path) if path.suffix.lower() in TEXT_SUFFIXES else ""
            rows.append({
                "path": str(path.relative_to(root)),
                "sha256": digest,
                "bytes": size,
                "modified": path.stat().st_mtime,
                "body": body,
            })
        store.put_content(node.id, rows)
        files += len(rows)
        objects_done += 1
    return {"objects": objects_done, "files": files}


def drifted(root: str | Path, store: objects.ObjectStore) -> list[str]:
    """Files whose bytes no longer match the hash the index holds.

    Which is the whole reason the hash is there: the files own the words, so
    the index is always a moment behind them, and this says by how much.
    """
    root = Path(root)
    out = []
    for node in read_tree(root):
        for row in store.content_of(node.id):
            path = root / row["path"]
            if not path.is_file():
                out.append(f"{row['path']}: indexed, and no longer on disk")
                continue
            digest, _ = sha256_of(path)
            if digest != row["sha256"]:
                out.append(f"{row['path']}: the file has changed since it was indexed")
    return out


# ---------------------------------------------------------------------------
# The command
# ---------------------------------------------------------------------------


def default_root() -> str:
    """The workspace to work on when none is named.

    The one Rouh itself reads (`config._workspace_root`, the installation's
    `ROUH_WORKSPACE`), so this command and the running server never disagree
    about which workspace they are talking about. Where nothing is configured,
    the workspace this is run inside: the nearest folder up from here with the
    map in it, or a `workspace/` with the map in it right here, which is how a
    checkout from before the workspace had a repository of its own holds it.
    `bin/rouh` sets the first from the second for a run in a workspace.
    """
    if config.assistant_repo:
        return config.assistant_repo
    here = Path.cwd().resolve()
    for folder in (here, *here.parents):
        if (folder / MAP_FILE).is_file():
            return str(folder)
    if (here / "workspace" / MAP_FILE).is_file():
        return str(here / "workspace")
    return ""


def main(argv: list[str] | None = None, *, out=None, err=None) -> int:
    """The command, writing to `out` and `err` (standard output and error unless
    told), which is how Rouh runs it for a job that asked over `/internal/objecttree`
    (`rouh/web/objecttreeapi.py`) and hands back what it said."""
    out = out or sys.stdout
    err = err or sys.stderr

    def say(*words, file=None) -> None:
        print(*words, file=file or out)

    class Parser(argparse.ArgumentParser):
        """Its usage and its complaints to `out` and `err` as well, not to the server's log."""

        def _print_message(self, message, file=None):
            if message:
                (err if file is sys.stderr else out).write(message)

    ap = Parser(
        prog="rouh objecttree",
        description="The workspace as a tree of objects: sidecars, the map, "
                    "the rows, and the index of what the files say.")
    ap.add_argument("--root", default="", help="the workspace, if not the usual one")
    # `--db` named a SQLite file until 23 September 2026. There is one
    # database now, Django's, and the environment says which (`rouh/config.py`),
    # so the flag is still taken and means nothing.
    ap.add_argument("--db", default="", help=argparse.SUPPRESS)
    sub = ap.add_subparsers(dest="what", required=True)

    sides = sub.add_parser("sidecars", help="give every object folder a .object.json")
    sides.add_argument("--titles", default="",
                       help="JSON naming the top-level and project folders")

    mapped = sub.add_parser("map", help="write _migration-map.json from the tree")
    mapped.add_argument("--repo", default="", help="the git checkout, for the dates")

    made = sub.add_parser("create", help="make a project, a task or a step")
    made.add_argument("title")
    made.add_argument("--type", default="task", choices=sorted(objects.NESTS))
    made.add_argument("--owner", default="", help="the id of whatever holds it")

    moved = sub.add_parser("move", help="put an object under a different owner")
    moved.add_argument("id")
    moved.add_argument("--to", default="", help="the new owner's id, or nothing for the top")

    sub.add_parser("import", help="make the database say what the map says")
    sub.add_parser("verify", help="check the tree and the rows against each other")
    sub.add_parser("reindex", help="rebuild the content index from the files")
    sub.add_parser("drift", help="which files have changed since they were indexed")
    sub.add_parser("tree", help="print the hierarchy as the database holds it")

    found = sub.add_parser("search", help="search the content index")
    found.add_argument("words", nargs="+")

    args = ap.parse_args(argv)
    root = args.root or default_root()
    if not os.path.isdir(root):
        say(f"no workspace at {root}", file=err)
        return 2

    if args.what == "sidecars":
        titles = json.loads(args.titles) if args.titles else {}
        say(f"{ensure_sidecars(root, titles=titles)} sidecar(s) written under {root}")
        return 0

    if args.what == "map":
        body = build_map(root, args.repo or None)
        path = Path(root) / MAP_FILE
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(body, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        say(f"{len(body['objects'])} object(s) written to {path}")
        return 0

    store = objects.ObjectStore()

    if args.what == "create":
        try:
            made = create(root, store, type=args.type, title=args.title,
                          owner=args.owner)
        except Refused as exc:
            say(exc, file=err)
            return 1
        say(f"{made['type']} {made['id']} at {made['rel']}")
        return 0

    if args.what == "move":
        try:
            done = move(root, store, args.id, args.to)
        except Refused as exc:
            say(exc, file=err)
            return 1
        if not done["moved"]:
            say(f"{args.id} is already there")
            return 0
        say(f"{done['was']} -> {done['rel']} ({done['how']}),"
              f" {done['objects']} row(s) followed it")
        return 0

    if args.what == "import":
        counts = import_map(root, store)
        say(f"{counts['objects']} object(s) in the map: "
              f"{counts['projects']} project(s) and {counts['tasks']} task(s) made, "
              f"{counts['updated']} row(s) already there and brought up to date, "
              f"{counts['links']} owner link(s)")
        return 0

    if args.what == "verify":
        report = verify(root, store)
        counts = report["counts"]
        say(f"{counts['folders']} object folder(s) on disk, {counts['rows']} row(s): "
              f"{counts['projects']} project(s), {counts['tasks']} task(s), "
              f"{counts['owns_links']} owner link(s)")
        say("at the top, owned by nothing: " + ", ".join(counts["at_the_top"]))
        for what, who in report["problems"].items():
            if who:
                say(f"\n{what.replace('_', ' ')}: {len(who)}")
                for one in who[:40]:
                    say(f"  {one}")
        say("\nthe tree and the rows agree" if report["ok"]
              else "\nthey do not agree")
        return 0 if report["ok"] else 1

    if args.what == "reindex":
        counts = reindex(root, store)
        say(f"{counts['files']} file(s) indexed under {counts['objects']} object(s)")
        return 0

    if args.what == "drift":
        out = drifted(root, store)
        for one in out:
            say(one)
        say(f"{len(out)} file(s) have moved on from the index" if out
              else "every indexed file still hashes to what the index holds")
        return 0

    if args.what == "tree":
        rows = {row["id"]: row for row in store.objects()}
        under: dict[str | None, list[str]] = {}
        for src_type, src_id, dst_type, dst_id in store.owns_edges():
            if dst_type in objects.NESTS:
                under.setdefault(src_id, []).append(dst_id)
        tops = [i for i in rows if not any(i in kids for kids in under.values())]

        def show(ident: str, depth: int) -> None:
            row = rows.get(ident)
            if row is None:
                return
            number = f"{row['number']} " if row["number"] is not None else ""
            say(f"{'  ' * depth}{number}{row['title']} ({row['type']})")
            for kid in sorted(under.get(ident, []),
                              key=lambda k: (rows.get(k, {}).get("number") or 0,
                                             rows.get(k, {}).get("slug") or "")):
                show(kid, depth + 1)

        for top in sorted(tops, key=lambda i: rows[i]["title"]):
            show(top, 0)
        return 0

    if args.what == "search":
        hits = store.search_content(" ".join(args.words))
        rows = {row["id"]: row for row in store.objects()}
        for hit in hits:
            owner = rows.get(hit["object_id"], {}).get("title") or hit["object_id"]
            say(f"{hit['path']}  [{owner}]\n    {hit['hit'].strip()}")
        say(f"{len(hits)} file(s) match")
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
