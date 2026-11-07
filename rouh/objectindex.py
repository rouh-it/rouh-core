"""The task browser, drawn from the database rather than from the folders.

**This is the task browser. There is no other one.** Until 21 September 2026
there were two: the workspace's own index page, which walked `tasks/NN.name`
and read `_categories.json`, and this one. That page, its code
(`_askai/server.py`), the file it read and the service that served it are all
gone; `/srv/assistant`, the separate workspace they belonged to, is archived
and moved aside at `/srv/assistant.retired`, and `workspace/README.md` says how
to bring it back.

What replaced it was a list, and a list is not what that page was. So on 22
September 2026 the page itself came back - the two columns, the category
buttons with their counts, the search, the keyboard, opening a task's steps in
place, the fold past fifty, and dragging a task onto a button to move it - and
it is drawn out of the object rows instead. `taskbrowser.css` and
`taskbrowser.js` beside this file are that page; this module is what feeds them,
and `objectindex_write.py` what writes back what they ask for. The panels and
rows of a task's own page are drawn in `objectindex_panels.py`; every name in
those two is still reached here, as `objectindex.<name>`.

**`_categories.json` is not read and not written.** Every question it used to
answer is answered by the `object` rows and the `owns` links:

    side        a top-level project: Work and Personal
    category    a project inside one of those
    a task's    the project that owns it
    category
    a move      `objecttree.move`: the `owns` link, then `git mv` of the folder

Two things the old page had are gone because the model has no place for them.
A category's colour was a field in that file; here it is worked out from the
project's place in its column, so a colour cannot drift from a category that
was renamed, unless the person picks one in Manage projects, which is kept on
the project (`project.color`) and wins. And Claude's "guess" mark - a task filed by the model rather than
by the person - was a flag in that file with nothing behind it in the object
model; a task either is filed under a project or is not.

`has_tree` below is what is left of the switch between the two pages, and it is
not a switch any more: it asks whether a workspace has a `_migration-map.json`,
which is the same question `config._workspace_root` asks, and it means "this is
a workspace Rouh can draw".

What a row links to
-------------------

**A task, a step and a project open to their own page, always**:
`/workspace/_task/<its folder>/`, which `task_page` draws out of the same rows.
Until 23 September 2026 a row opened whatever the object had built instead -
its `index.html`, or the one other page in its folder - and a page listing it
only when it had built nothing. Petar found that confusing and said why: the
page a step built was the main thing a press gave him and was also listed
again among the task's artifacts, it took a while to see those were the same
thing, and with two pages in a folder there was no saying which one a press
would open. So a press opens the object.

**A task's page is its subtasks and what is its own, and nothing else**, since
24 September 2026 (`_level`). Until then it was sections by kind - every page
the task and its steps had built, then every document of all of them, then
the chats, the runs and the cards - and a step with a page, two notes and a
folder was four lines in three sections. Petar, on task 61: "there are too
many things, and it is too scattered." So each subtask is one line that opens
its own page, exactly the same shape one level down, with a button on it for
the page it built; and under the subtasks is what belongs to this level alone.
Every link there is a file that is really there; nothing here invents one.

Why the page is inert at its own address
----------------------------------------

`/workspace/` is served to a signed-in session and drawn in a frame on Rouh's
canvas, sandboxed, with `connect-src 'none'`. A sandboxed page cannot fetch, so
it cannot save anything by itself. It hands each change to the page around it,
which is signed in and makes the request (`pages.FILE_MESSAGE`, `fileRelay` in
app.js, and `POST /api/workspace/filing`). Opened at its own address there is
no page around it, so the browser says so and is read-only rather than offering
buttons that would fail.
"""
from __future__ import annotations

import html
import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote, unquote

from . import (addressing, answering, archiving, artifacts, clock, docview, instructions,
               keeping, objects, objecttree, pages, steps, task_origin, taskicons, taskmeta,
               xray)

log = logging.getLogger(__name__)

#: Under `pages.ROUTE`, the address one object's own page is at: the index is
#: `/workspace/` itself and an object is `/workspace/_task/<its folder>/`. No
#: file in the workspace can be reached at either, because `pages.py` serves
#: only the top folders in `pages.TOPS` and this is not one of them.
TASK_PREFIX = "_task/"

#: How many objects deep the page draws before it stops indenting. Depth is
#: enforced on the screen rather than in the schema, and this is the screen.
MAX_DEPTH = 6

#: The colours a category is drawn in, in order. A project takes the one at
#: its place in its own column, so the colours inside a column are always
#: different from one another, which is where they are compared.
PALETTE = ("blue", "amber", "teal", "rose", "violet", "green", "slate")

#: A colour picked by hand that is not one of those: `#rrggbb`, and nothing
#: else, because it is written into a style attribute on the page.
_HEX = re.compile(r"#[0-9a-f]{6}")

#: The order the columns are read in, by folder name, and with them the order
#: of the buttons across the top and of the headings in the move menu.
#:
#: Written down rather than worked out, because there is nothing to work it out
#: from: both top-level projects were imported in the same instant and neither
#: carries a number, so the only rule available was the alphabet, and the
#: alphabet puts the private one first. Petar reads work first and said so, and
#: the retired page had the same two names in the same order in its own code
#: (`DEFAULT_SIDES` in the workspace's `_askai/server.py`). A top-level project
#: not named here comes after these, by name.
#:
#: These are **folder names and not titles.** The second column is called
#: Personal on screen since 23 September 2026, and its folder is still
#: `private/`: a folder name is the address of every page under it and of every
#: link into it, and RENAME.md's rule is that what a person reads changes and
#: what a machine reads does not.
COLUMNS = ("work", "private")

#: What the two files beside this one are called. They are put into the page
#: rather than linked: the page is sandboxed and has an origin of its own, so
#: the browser would fetch them without Rouh's sign-in and be refused.
HERE = Path(__file__).resolve().parent / "static"
SHEET = "taskbrowser.css"
SCRIPT = "taskbrowser.js"

#: The one menu every three dots in Rouh open, how it looks and what it does,
#: put into these pages ahead of their own sheet and script, so a menu on a
#: page in a frame is the same menu as one on the page around it (`menu.js`).
MENU_SHEET = "menu.css"
MENU_SCRIPT = "menu.js"

#: The one drawing of a filter label, its eye and its count (`labels.js`, `labels.css`), shared with
#: the Incubator's list, put into these pages ahead of their own sheet and the task browser's script.
LABELS_SHEET = "labels.css"
LABELS_SCRIPT = "labels.js"

#: The script that makes a project's own page work: the box at the top that
#: starts a chat, the three dots, the instructions, and the files. A task's
#: page has none of it.
PROJECT_SCRIPT = "projectpage.js"

#: And the one a task's or a step's own page has: its Start chat button,
#: floating in the bottom right corner, which is the one thing on that page
#: that asks Rouh for anything.
TASK_SCRIPT = "taskpage.js"

#: A task's icon in front of its title, and the picker a press on it opens (`rouh/taskicons.py`),
#: put into the task browser and a task's page, ahead of their own scripts.
ICON_SCRIPT = "taskicon.js"

#: The one drawing of a decision (`rouh/decisions.py`), put into a task's and a step's
#: page as it is into Rouh's own, so a question looks and answers the same everywhere.
DECISION_SCRIPT = "decision.js"
DECISION_SHEET = "decision.css"

#: A goal's own page, and the script that draws its streams (`goal_page`).
GOAL_DOC = "goal.md"
GOAL_SCRIPT = "goalpage.js"

#: A task's folder, among the folders on the way down to one of its steps: a
#: number and a dot. A step is a number, a dash and more (`30-01.the-build`),
#: so the first folder named this way is the task the rest belong to. The same
#: rule, in the same words, as `TASK_NAME` in app.js, which is how the page
#: works out whose conversation a step's page is beside.
TASK_FOLDER = re.compile(r"^\d+\.")

#: Where a project's instructions are kept. Not a column: a project's notes
#: have been a file in its folder since the workspace was reshaped - a
#: `CLAUDE.md` until 26 September 2026 and an `AGENTS.md` since
#: (`rouh/instructions.py`) - the model's own search already reads every one
#: of them (`workspace.search_files`), and a worker started in that folder is
#: handed it by Claude Code or Codex without anybody arranging it. A second
#: copy in the database would be a second answer to the same question.
INSTRUCTIONS = instructions.NAME

#: The longest instructions a project may be given from this page. Long enough
#: for a page of house rules, short enough that the field is never mistaken for
#: a document: a document is a file in the project, which is what the files
#: below it are for.
INSTRUCTIONS_MAX = 20_000


def files_key(project_id: str) -> str:
    """Where a project's own files are kept in the attachment store.

    The same store a chat's attachments are in, under a key of its own, so a
    project's files and a conversation's can never be handed one another's:
    `attachments.safe_id` takes this whole string as one path segment and a
    project id is a uuid, so no chat id can ever spell one of these.
    """
    return f"project-{project_id}"


def task_files_key(task_id: str) -> str:
    """Where a task's or a subtask's own files are kept in the attachment store.

    Beside a project's (`files_key`) and for the same reasons: the person's
    uploads are never written into the workspace, where a deploy would reset
    them and a move would leave them behind, but kept under the task's id,
    which a move or a rename never changes. The prefix is not a project's, so
    neither can be handed the other's files.
    """
    return f"task-{task_id}"


SEARCH_ICON = (
    '<svg viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" '
    'stroke-width="1.6"><circle cx="7" cy="7" r="4.5"/><path d="M10.5 10.5 14 14"/></svg>'
)

#: How near two moments are, in seconds, to be the same moment when the tasks
#: are put in order of when they were last worked on (`index_data`).
SAME_MINUTE = 60

#: How a task's state is said on its pill. `open` is every task nobody has said
#: anything about, so the page draws no pill for it.
STATE_WORDS = {"waiting": "Waiting", "done": "Done", "open": "Open",
               # Waiting, and answered from its page: on the job now (`_asking`).
               "answered": "Answered",
               # A goal's step Rouh marked done with nothing made (`goals.is_hollow`).
               "hollow": "Nothing made"}


def has_tree(root) -> bool:
    """Whether this workspace is the reshaped one, with objects in it."""
    return bool(root) and os.path.isfile(os.path.join(str(root), objecttree.MAP_FILE))


def _asset(name: str) -> str:
    """One of the front-end files in `static/`, or "" when it cannot be read."""
    try:
        return (HERE / name).read_text(encoding="utf-8")
    except OSError:
        log.warning("the task browser is drawn without %s: it could not be read", name)
        return ""


def _facts(root, folder: str) -> tuple[str, list[tuple[str, str]], float]:
    """One folder, in one pass: its own page, its other pages, and its date.

    `index.html` is the page an object has built, which is what the workspace
    has written for years. A folder with no `index.html` and exactly one other
    page is that page: the early tasks named a page after themselves
    (`bricklink-analysis.html`) and there is no ambiguity about which it is.
    Two or more and they are all listed as other pages instead.

    The date is the newest of the files directly in it, which is what
    "changed" means to a reader: a task whose step was rewritten this morning
    reads as today. Not the folder's own date and not the files that only say
    how it is organised (`objecttree.ORGANISING`): renaming, moving, labelling,
    pinning or archiving a task leaves its place in the list where it was.
    """
    if not folder:
        return "", [], 0.0
    here = os.path.join(str(root), folder)
    index, others, newest = "", [], 0.0
    try:
        with os.scandir(here) as entries:
            for entry in entries:
                try:
                    if not entry.is_file():
                        continue
                    if entry.name not in objecttree.ORGANISING:
                        newest = max(newest, entry.stat().st_mtime)
                except OSError:
                    continue
                if not entry.name.lower().endswith(".html"):
                    continue
                if entry.name.lower() == "index.html":
                    index = pages.url_for(f"{folder}/{entry.name}")
                else:
                    others.append((entry.name, pages.url_for(f"{folder}/{entry.name}")))
    except OSError:
        return "", [], 0.0
    others.sort()
    if not index and len(others) == 1:
        index, others = others[0][1], []
    return index, others, newest


def stamp(when: float, now: datetime) -> str:
    """`12 Aug`, or `12 Aug 25` once the year stops being obvious."""
    if not when:
        return ""
    at = datetime.fromtimestamp(when)
    tail = "" if at.year == now.year else f" {at:%y}"
    return f"{at.day} {at:%b}{tail}"


def _changed_on(when: float, now: datetime) -> str:
    """When a task or a subtask last changed, at the right of its name, with
    the whole moment on a hover. "" when there is no date to give."""
    said = stamp(when, now)
    at = clock.moment(when) if said else None
    if at is None:
        return ""
    full = f"Last changed on {at.day} {at:%B %Y} at {at:%H:%M}"
    return (f'<time class="owhen" datetime="{at:%Y-%m-%d}" title="{full}">'
            f'{html.escape(said)}</time>')


def _was_line(store, ident: str, changed: str) -> str:
    """The date at the right of a task's name, with the numbers it had before a move in
    front of it, quietly: "Was 98-02 · 3 days ago" (`rouh/moving.py`). Just the date for a
    task no move has renumbered."""
    try:
        was = store.numbers_before().get(ident, []) if ident else []
    except Exception:                                   # pragma: no cover - reported
        log.exception("the numbers %s had before could not be read", ident)
        was = []
    if not was:
        return changed
    said = ", ".join(was)
    tip = (f"It was {said} before it was moved, and searching {was[-1]} still finds it"
           if len(was) == 1 else
           f"It was {said} before it was moved, and searching any of them still finds it")
    inner = changed.replace('<time class="owhen"', "<time", 1) if changed else ""
    return (f'<span class="owhen"><span class="owas" title="{html.escape(tip, quote=True)}">'
            f'Was {html.escape(said)}</span>{" · " + inner if inner else ""}</span>')


def _step_number(row) -> str:
    """What a step is called on its line: `19-04` out of `19-04.packages`.

    A step has no `number` of its own - step numbers repeat across the
    workspace and `task.number` is unique - so the name is where it is, and a
    folder that is not named that way simply has none.
    """
    slug = str(row.get("slug") or "")
    head = slug.split(".", 1)[0]
    return head if head and head.replace("-", "").isdigit() else ""


def _sorting(row) -> tuple:
    """Newest first: the highest number, then the folder name.

    Highest number first rather than by date, which is what the retired page
    settled on and for the reason it wrote down: it does not reshuffle the
    whole column when somebody edits an old file. That is still the rule for
    a task's steps, which are a sequence, and not for the tasks on the board,
    which go by when they were last worked on (`index_data`).

    A task has its number on it. A step has none - step numbers repeat across
    the workspace and `task.number` is unique - so its number is the one in its
    folder name, and a folder not named that way sorts last.
    """
    number = row.get("number")
    if number is None:
        head = _step_number(row).replace("-", "")
        number = int(head) if head.isdigit() else -1
    return (-number, str(row.get("slug") or ""))


def _projects_in_order(tree) -> list[tuple[dict, str]]:
    """Every project under a column, with the column it is in, in the order
    the page lists them: by name, not newest first, because a column's buttons
    are read as a list and a reader looking for Research wants it where R is,
    each followed by the projects inside it. The columns themselves are not
    in it: a column is not a category and has no colour."""
    out: list[tuple[dict, str]] = []

    def walk(ident: str, side: str, depth: int) -> None:
        if depth > 12:
            return
        for row in sorted(tree.kids(ident, "project"),
                          key=lambda r: (r["title"] or r["slug"] or "").lower()):
            out.append((row, side))
            walk(row["id"], side, depth + 1)

    for top in tree.tops():
        walk(top["id"], top["id"], 0)
    return out


def project_colors(tree, picked: dict[str, str] | None = None) -> dict[str, str]:
    """The colour of every project inside a column, by id: the one picked by
    hand in Manage projects (`project.color`) when there is one, and otherwise
    the one its place in its column gives it, from `PALETTE`. Each is a name
    from `PALETTE` or `#rrggbb`, the two forms `_coloured` lets through. This
    is the one place a project's colour is worked out, so the task browser and
    the Control Room (`rouh/controlroom.py`) always draw a project the same.
    A column (Work, Personal) has none, and is not in it."""
    if picked is None:
        picked = {}
    out: dict[str, str] = {}
    seats: dict[str, int] = {}
    for row, side in _projects_in_order(tree):
        seat = seats.get(side, 0)
        seats[side] = seat + 1
        out[row["id"]] = picked.get(row["id"]) or PALETTE[seat % len(PALETTE)]
    return out


def task_faces(store: objects.ObjectStore, ids) -> dict[str, dict]:
    """How each of these tasks looks wherever it is shown, by id: its icon as the pages are sent
    it (`taskicons.shown`) and `color`, the colour of the nearest project above it
    (`project_colors`), or "" for one straight in a column. One read of the tree for all of them."""
    wanted = [i for i in dict.fromkeys(ids or ()) if i]
    if not wanted:
        return {}
    tree = _Tree(store)
    colours = project_colors(tree, store.colors())
    out: dict[str, dict] = {}
    for ident in wanted:
        row = tree.rows.get(ident)
        if row is None:
            continue
        colour, up, depth = "", tree.owner.get(ident), 0
        while up and depth < 24:
            if up in colours:
                colour = colours[up]
                break
            up, depth = tree.owner.get(up), depth + 1
        out[ident] = dict(_icon_of(tree.icons, row), color=colour)
    return out


class _Tree:
    """The rows and the `owns` links, read once and asked many times."""

    def __init__(self, store: objects.ObjectStore) -> None:
        self.rows = {row["id"]: row for row in store.objects()}
        # Every task's and step's icon (`rouh/taskicons.py`), which the `object` view has not.
        self.icons = store.task_icons()
        self.under: dict[str, list[str]] = {}
        self.owner: dict[str, str] = {}
        # The chats each task holds, which are not in the tree but are where
        # the work on a task is talked through (`_worked_on`).
        self.chats: dict[str, list[str]] = {}
        for src_type, src_id, dst_type, dst_id in store.owns_edges():
            if dst_type in objects.NESTS and dst_id in self.rows and src_id in self.rows:
                self.under.setdefault(src_id, []).append(dst_id)
                self.owner[dst_id] = src_id
            elif src_type == "task" and dst_type == "chat":
                self.chats.setdefault(src_id, []).append(dst_id)

    def kids(self, ident: str, type: str | None = None) -> list[dict]:
        found = [self.rows[k] for k in self.under.get(ident, [])
                 if type is None or self.rows[k]["type"] == type]
        return sorted(found, key=_sorting)

    def tops(self) -> list[dict]:
        """The projects at the top, which is what a column is, in `COLUMNS`."""
        def where(row) -> tuple:
            slug = (row.get("slug") or row.get("folder") or "").lower()
            named = COLUMNS.index(slug) if slug in COLUMNS else len(COLUMNS)
            return (named, (row["title"] or "").lower())

        return sorted((r for r in self.rows.values()
                       if r["type"] == "project" and r["id"] not in self.owner),
                      key=where)


def _worked_on(store: objects.ObjectStore, tree: _Tree) -> dict[str, float]:
    """When each task and step was last worked on, by id, as far as the
    database knows it. Its folder's date is the rest, and is read off the disk.

    When it was made; when it last stopped, which is `closed_at` and is written
    at the moment it went to waiting or done; and when something was last said
    in a conversation it holds, which is the clock the chats list is ordered by
    and moves on every message. Talking in task 45 is working on task 45. A
    conversation with nothing said in it is not counted, because a chat made
    by opening a task is opening it and not using it.

    **Never `updated_at`.** It is Rouh's bookkeeping, rewritten on every row at
    once whenever the workspace's map grows (`objecttree.import_map`), and read
    as a touch it made every task the map knew look worked on in the same
    second. These are the same clocks, for the same reasons, as the rail's
    list of tasks (`owning.snapshot`, `byTouched` in app.js), so the two lists
    agree about what was worked on last.
    """
    said = store.message_counts()
    talked = {chat.id: float(chat.last_activity or 0.0)
              for chat in store.list_chats(limit=None) if said.get(chat.id)}
    out: dict[str, float] = {}
    for task in store.list_tasks(limit=None):
        when = float(task.created_at or 0.0)
        if task.state in objects.STOPPED["task"] and task.closed_at:
            when = max(when, float(task.closed_at))
        for chat_id in tree.chats.get(task.id, ()):
            when = max(when, talked.get(chat_id, 0.0))
        out[task.id] = when
    return out


# --------------------------------------------------------------------------
# What the page is given
# --------------------------------------------------------------------------


def index_data(store: objects.ObjectStore, root, names=(), person=None) -> dict:
    """Everything the task browser draws, as one object.

    `names` is what the person reading it is called, which is how their
    tasks' notes name them when they say what a task waits on
    (`waiting.ask_in`). `person` is who is reading it, whose "Others' tasks"
    switch it carries (`show_others`, `rouh/task_origin.py`).

    **Others' tasks and Rouh's are sent, marked.** A task or a step made for
    somebody else, or by one of Rouh's own processes, carries `made` - which
    kind, who it was for or which process, in words (`task_origin.public`) -
    and the page leaves it out of his own list until "Others' tasks" or "Made
    by Rouh" is pressed, as it leaves the archived ones out until the Archive
    is open, unless it is pinned or waiting on him. Petar, 15 October 2026:
    "I don't want those to pollute my workspace. Maybe like a toggle similar
    to Archive?", and 16 October 2026: "Whatever any process is doing should
    be created without me being the gate. I just don't want to see it by
    default in the task browser."

    Every project inside a column is a category, however deep it is nested, so
    a project inside a project has its own button rather than its tasks
    disappearing into its parent's. Every task under a project is a task on the
    board; everything under a task is one of its steps.

    **Only tasks are in it.** What a task holds that is not a task - its
    chats, its runs, its cards, the pages it built - is not sent, so the page
    has nothing to hang under a task but its steps. Until 24 September 2026 a
    task's chats, runs and cards were lines under it here as well, and a task
    with none of those and no steps still had an arrow when it had built more
    than one page. Petar: "a task in the task browser should have a chevron and
    subitems only if they are tasks. don't display artifacts, chats or any of
    that." Every one of them is on the task's own page, which is where a press
    on the task goes (`build_task`), so nothing left the product: it left the
    tree.

    **The task worked on last is first.** Until 24 September 2026 the tasks
    were in number order, highest first, which is what the retired page did so
    that editing an old file would not reshuffle a column. Petar asked for the
    reshuffle in as many words: "the tasks are not sorted by newest (edited,
    worked on, new content) on top." So a task goes by the last time anything
    happened to it or to any of its steps - a file in its folder written, a
    step filed, a stop, a word said in its conversation (`_worked_on`) - and
    the date on its line is that same moment, so the dates
    read newest first down every column. Two tasks last worked on in the same
    minute are in number order, which is every task nobody has touched since
    the workspace was copied onto the machine. **Organising it is not working
    on it**, since 22 October 2026: a rename, a colour, a label, a move, a pin
    or an archive changes no clock read here (`objecttree.ORGANISING`).
    """
    tree = _Tree(store)
    now = datetime.now()
    worked = _worked_on(store, tree)
    tops = tree.tops()
    sides = [{"id": row["id"], "name": row["title"]} for row in tops]
    top_ids = {row["id"] for row in tops}
    # What each project is for, in the person's own words. It is a column of
    # `project` and not of the `object` view the tree is read from, so it is
    # asked for in one query of its own. The page draws it in Manage projects,
    # and the model that files a new task reads the same words
    # (`rouh/filing.py`).
    said = store.descriptions()
    # Each project's colour: picked by hand in Manage projects, or the one its
    # place in its column gives it (`project_colors`).
    picked = store.colors()
    colours = project_colors(tree, picked)
    # Which tasks and steps are archived, and when (`rouh/archiving.py`). An
    # archived task is still sent, marked, because the page's Archive is where
    # it is kept; an archived step of a live task is not, because its task's
    # own page is where it is kept, under Archived.
    kept = archiving.archived(store)
    # Who made each task or step, where it was not the person.
    made_by = task_origin.origins(store)
    # Every task's meta, in one read: its tags (`rouh/taskmeta.py`).
    metas = taskmeta.every()
    # Each task's and step's icon, in front of its title (`rouh/taskicons.py`).
    icons = tree.icons
    # The numbers each was called by before a move renumbered it, so the
    # search finds 92-08 under the 103-01 it is now (`rouh/moving.py`).
    before = store.numbers_before()

    cats = [{"id": row["id"], "name": row["title"], "side": side,
             "color": colours[row["id"]],
             "picked": picked.get(row["id"], ""),
             "description": said.get(row["id"], "")}
            for row, side in _projects_in_order(tree)]

    def steps_of(row, depth: int, whole: bool = False) -> tuple[list[dict], float]:
        """One object's steps, newest first, each with its own steps inside
        it, and when the one of them worked on last was worked on. `whole`
        is an archived task's, which went into the Archive with every step it
        had, so none of them is left out."""
        out, newest = [], 0.0
        if depth > MAX_DEPTH:
            return out, newest
        for kid in tree.kids(row["id"], "task"):
            if kid["id"] in kept and not whole:
                continue
            _page, _others, when = _facts(root, kid.get("folder") or "")
            deeper, then = steps_of(kid, depth + 1, whole)
            own = max(when, worked.get(kid["id"], 0.0))
            newest = max(newest, own, then)
            out.append({
                "id": kid["id"],
                "num": _step_number(kid),
                "was": before.get(kid["id"], []),
                "title": kid["title"] or kid["slug"] or kid["id"],
                **_icon_of(icons, kid),
                "href": _own_page(kid),
                # Pinned to the Control Room (`rouh/pinning.py`): a step has
                # a pin of its own on its line, as its task has on its row.
                "pinned": bool(kid.get("pinned")),
                # Made for somebody else or by a process of Rouh's
                # (`rouh/task_origin.py`), or None for his own.
                "made": task_origin.public(made_by.get(kid["id"])),
                # When it was itself last worked on, which is how the page
                # finds the step touched last however deep it is (`latest`).
                "at": own,
                # Its own steps, all the way down, hanging under it on the
                # page the way a chat's forks hang under it. Tasks and nothing
                # else: its pages are the first lines of the step's own page,
                # which is where a press on the step goes, and so are its
                # chats, its runs and its cards. Until 10 October 2026 they
                # were one flat list under it, a single level deep on the
                # screen whatever their depth (Petar: "make them like chats.
                # I like how I can see the branching of chats").
                "kids": deeper,
            })
        return out, newest

    def latest_of(steps: list[dict]) -> str:
        """The id of the step worked on last, at any depth, or "" for none.

        To the minute, as the tasks are ordered (`SAME_MINUTE`), and of two
        in the same minute the one numbered later: steps a single git command
        wrote all have its second, and the last of a sequence is its newest.
        """
        best, key = "", None
        stack = list(steps)
        while stack:
            one = stack.pop()
            mine = (int(one["at"] // SAME_MINUTE),
                    [int(n) for n in one["num"].split("-") if n.isdigit()])
            if one["at"] and (key is None or mine > key):
                best, key = one["id"], mine
            stack.extend(one["kids"])
        return best

    tasks = []
    last: dict[str, float] = {}
    for row in tree.rows.values():
        if row["type"] != "task":
            continue
        held_by = tree.owner.get(row["id"])
        # A task under a task is a step of it, and is drawn there, not here.
        if held_by is not None and tree.rows[held_by]["type"] == "task":
            continue
        _page, _others, when = _facts(root, row.get("folder") or "")
        steps, then = steps_of(row, 1, row["id"] in kept)
        last[row["id"]] = max(when, then, worked.get(row["id"], 0.0))
        # Every page it and its subtasks built: off the disk and off the step
        # rows both (`places_of`). A step folder a job wrote by hand has no
        # row, and a step row can name a folder outside the task's own, and
        # either alone said "No page yet" about a task whose step held the
        # whole of what it had built.
        count = len(_page_files(root, places_of(
            root, row.get("folder") or "",
            [kid.get("folder") for kid in tree.kids(row["id"], "task")])))
        state = str(row.get("status") or "open")
        # Whether a waiting task has been answered from its page already
        # (`answering.py`), which makes its pill say Answered and keeps it out
        # of Waiting on you, or its question dismissed there, an answer with
        # nothing in it, which takes the pill off and keeps it out too. What
        # it asks is not sent: the browser shows the pill alone, and the
        # question is at the top of the task's own page.
        answered = None
        if state == "waiting":
            _question, _notes, line = answering.asked_of(root, row.get("folder") or "", names)
            answered = answering.answers_to({row["id"]: line}).get(row["id"])
        tasks.append({
            "id": row["id"],
            "dir": row.get("folder") or "",
            "n": row.get("number"),
            "was": before.get(row["id"], []),
            "name": row["title"] or row["slug"] or row["id"],
            **_icon_of(icons, row),
            # Its own page, never a file it built: see "What a row links to".
            "href": _own_page(row),
            # When it was last worked on, which is also what the list is in
            # the order of, so the dates read newest first down a column.
            "date": stamp(last[row["id"]], now),
            # How many pages it built, for the words on its line. Never lines
            # under it: see "Only tasks are in it" above.
            "pages": count,
            # What its arrow opens onto, and the only thing that gives it one.
            "steps": steps,
            # The step worked on last, however deep, which its line names and
            # its open tree marks, so the newest work is found without
            # opening every branch to look for it.
            "latest": latest_of(steps),
            "category": held_by if held_by is not None and held_by not in top_ids else None,
            "status": state,
            "status_label": STATE_WORDS.get(state, state),
            # Its tags, from its meta (`rouh/taskmeta.py`): "goal" makes it one of the
            # person's goals (`rouh/goals.py`), which the row says in a pill.
            "tags": taskmeta.tags_of(metas.get(row["id"])),
            "answered": answered.answer if answered else "",
            "dismissed": bool(answered and not answered.answer),
            # Archived, and when: it is in the Archive and not the live list.
            # Pinned to the Control Room (`rouh/pinning.py`).
            "pinned": bool(row.get("pinned")),
            "archived": row["id"] in kept,
            "archived_at": kept.get(row["id"], 0.0),
            "archived_on": stamp(kept[row["id"]], now) if row["id"] in kept else "",
            # Made for somebody else, and who, or by a process of Rouh's, and
            # which: out of his own list until "Others' tasks" or "Made by
            # Rouh" shows it (`rouh/task_origin.py`). None for his own.
            "made": task_origin.public(made_by.get(row["id"])),
        })
    # The one worked on last first, to the minute, and then the highest number
    # (see "The task worked on last is first" above). To the minute because a
    # folder's date is to the nanosecond: every task nobody has touched since
    # the workspace was checked out onto the machine was written by one git
    # command in the same second or two, and ordered by the fraction they
    # would stand in whatever order git wrote their files in, which reads to a
    # person as no order at all.
    tasks.sort(key=lambda t: (-int(last[t["id"]] // SAME_MINUTE),
                              -(t["n"] if t["n"] is not None else -1), t["dir"]))
    show = bool(person is not None and task_origin.showing(person.user_id, person.org_id))
    # Where a task goes when it is taken out of its project with the cross at the end of
    # the project's button: the project a task nobody filed goes to (`filing.fallback`).
    from . import filing

    try:
        fallback = filing.where_it_goes(store)
    except Exception:  # noqa: BLE001 - only the cross on a project is lost
        log.exception("the fallback project could not be read")
        fallback = ""
    # What the person approved for demo mode, by number, for Shown in demo and its dots
    # (`demo.browser_marks`); and outside demo mode no demo copy at all.
    from . import demo

    marks = demo.browser_marks(person)
    if not marks["demo"]:
        tasks = demo.hide_copies(tasks)
    return {"sides": sides, "categories": cats, "tasks": tasks, "show_others": show,
            # The view Save view kept for this person, which the page opens on.
            "saved_view": saved_view(person), "fallback": fallback, "demo": marks}


def _icon_of(icons: dict[str, str], row) -> dict:
    """A task's icon as the pages are sent it (`taskicons.shown`): `icon`, its emoji, or `img`,
    its picture as a data address."""
    return taskicons.shown(icons.get(row["id"], ""), row.get("title") or row.get("slug") or "")


def _own_page(row) -> str:
    """The object's own page here, or "" for a row with no folder yet.

    Nearly every object has a folder and so has a page here whether or not it
    has built one of its own. A row without one - a task made before its folder
    was written - is a name on the screen and not a link, because the only
    address that could be made for it answers "there is nothing filed there".
    """
    folder = row.get("folder") or ""
    return pages.url_for(TASK_PREFIX + folder) + "/" if folder else ""


# --------------------------------------------------------------------------
# One object's own page, drawn from the same rows
# --------------------------------------------------------------------------


#: How something under an object is said on its own line, and the order the
#: counts come in: the pages it built first, because a page is what the work
#: was for, then what nests, then the talking, then the work, then what came
#: out of it, then its files. One word for one and one for several, because
#: "1 chats" reads as a bug.
#:
#: A Markdown file is ".md" and never "notes", which is what it was called
#: until 24 September 2026. Petar: "replace the label notes with .md." It is
#: the one word here that is the same for one and for several.
KIND_WORDS = {"page": ("page", "pages"),
              "project": ("project", "projects"), "task": ("task", "tasks"),
              "subtask": ("subtask", "subtasks"),
              "step": ("step", "steps"), "document": ("document", "documents"),
              "chat": ("chat", "chats"), "run": ("run", "runs"),
              "card": ("card", "cards"), "note": ("rule", "rules"),
              "md": (".md", ".md"),
              "file": ("file", "files"), "folder": ("folder", "folders")}

#: What each kind is drawn with on its row. A glyph rather than a word, so a
#: list of forty reads as a shape down the left edge. Nothing that means
#: anything by itself: a tick beside a task would read as "done", which is
#: what the status pill on the same row is for.
#:
#: A page is the globe, and never a sheet of paper: it was the sheet 📄 until
#: 1 October 2026, a hair's breadth from a plain file's 📃, and Petar said
#: (fr_c72cbb0c4149) "icons on artifacts and HTML pages should be different.
#: HTML pages are more important and should be more visible". So its row is
#: tinted and its name heavier as well (`.orow[data-kind="page"]`).
KIND_MARKS = {"project": "\U0001F5C2", "task": "\u25AA", "chat": "\U0001F4AC",
              "run": "\u25B6", "card": "\u25C7", "artifact": "\u25C7",
              "page": "\U0001F310", "md": "\U0001F4DD", "folder": "\U0001F4C1",
              "file": "\U0001F4C3", "sources": "\U0001F4D1"}

#: What each kind of file is called on its row, so a list that holds more than
#: one says which is which: a page, a Markdown file, and what a subtask was
#: made with - its `source-code` folder, a data file beside it.
DOC_WORDS = {"page": "Page", "md": ".md", "folder": "Folder", "file": "File"}

#: Folders and files inside an object's folder that are never listed as its
#: documents: scratch the workspace does not keep (`temp/`) and what can be
#: made again (`node_modules/`, `__pycache__/`). None of it is what a step made.
NOT_DOCUMENTS = {"temp", "node_modules", "__pycache__", "venv", "dist"}

#: The most of one plain file drawn when it is opened to read, and the most
#: lines of a folder listed. Working files are small; a file the size of a
#: database is not one, and this is not the place to find that out.
FILE_LONGEST = 400_000
FOLDER_MOST = 300

#: The most of one notes file that is read to draw it. A task's notes are a
#: few pages long; a file a thousand times that is not notes, and the page is
#: not the place to find that out by drawing all of it.
DOC_LONGEST = 1_000_000

#: How many of one kind a section lists before it stops and says how many more
#: there are. Work holds four hundred chats all the way down and a page that
#: draws every one of them is a page nobody scrolls to the bottom of.
MOST_LISTED = 60

#: What a run's state is called on its row, in the words the rest of Rouh uses.
RUN_WORDS = {"running": "Running", "waiting": "Waiting", "conflict": "Waiting",
             "done": "Done", "failed": "Failed", "stopped": "Stopped"}


class _Under:
    """Everything under one object that is not a folder: its chats, its runs
    and what it has drawn, all the way down.

    The folders - the projects and the tasks - are `_Tree`'s, because they are
    the tree and are drawn nested. These are not nested and are not a tree:
    a chat under task 19 under Acme is in Acme, and what the person
    means by "the chats in this project" is all of them, however deep the task
    that owns one happens to sit. So they are walked down and grouped by kind,
    which is the same answer the project row in the rail counts
    (`conversations.projects`).
    """

    def __init__(self, store: objects.ObjectStore) -> None:
        self._store = store
        self._rows: dict[str, dict] = {}
        #: What every owned artifact's head version says, read the first time
        #: `page_of` is asked and not before: most pages never ask.
        self._bodies: dict[str, str] | None = None
        self.under: dict[tuple[str, str], list[tuple[str, str]]] = {}
        #: The other way round, for every kind and not only the folders: what
        #: holds this. `_mended` climbs it to find the folder an artifact's
        #: file is really in, which is the folder of the task that owns it.
        self.over: dict[tuple[str, str], tuple[str, str]] = {}
        for src_type, src_id, dst_type, dst_id in store.owns_edges():
            self.under.setdefault((src_type, src_id), []).append((dst_type, dst_id))
            self.over[(dst_type, dst_id)] = (src_type, src_id)

    def folder_over(self, kind: str, ident: str, tree: _Tree) -> str:
        """The folder of the nearest thing above this that has one."""
        at: tuple[str, str] | None = self.over.get((kind, ident))
        seen: set[tuple[str, str]] = set()
        while at is not None and at not in seen:
            seen.add(at)
            row = tree.rows.get(at[1])
            if row is not None and (row.get("folder") or ""):
                return str(row["folder"])
            at = self.over.get(at)
        return ""

    def loose(self, kind: str, ident: str) -> dict[str, list[tuple[str, str]]]:
        """What is under this, by kind, with the folders left out."""
        found: dict[str, list[tuple[str, str]]] = {}
        seen: set[tuple[str, str]] = set()

        def walk(at: tuple[str, str], depth: int) -> None:
            if depth > MAX_DEPTH:
                return
            for child in self.under.get(at, ()):
                if child in seen:
                    continue
                seen.add(child)
                if child[0] not in objects.NESTS:
                    found.setdefault(child[0], []).append(child)
                walk(child, depth + 1)

        walk((kind, ident), 0)
        return found

    def own(self, kind: str, ident: str) -> dict[str, list[tuple[str, str]]]:
        """What is under this and not under one of its subtasks, by kind.

        `loose` for one level of a task: a card drawn in a chat the task holds
        is the task's, and a chat a subtask holds is the subtask's, listed on
        its own page and counted on its line (`_level`).
        """
        found: dict[str, list[tuple[str, str]]] = {}
        seen: set[tuple[str, str]] = set()

        def walk(at: tuple[str, str], depth: int) -> None:
            if depth > MAX_DEPTH:
                return
            for child in self.under.get(at, ()):
                if child in seen or child[0] in objects.NESTS:
                    continue
                seen.add(child)
                found.setdefault(child[0], []).append(child)
                walk(child, depth + 1)

        walk((kind, ident), 0)
        return found

    def page_of(self, ident: str) -> str:
        """The workspace page a card shows and nothing else, or "".

        Such a card is that page, put on the screen in a conversation
        (`show_workspace_page`), and it keeps no path of its own - an
        artifact's path is the step file it was filed as. So what it shows is
        read out of its body, and every owned card's body is read at once.
        """
        return _only_a_page(self._heads().get(ident, ""))

    def _heads(self) -> dict[str, str]:
        if self._bodies is None:
            owned = {dst_id for kids in self.under.values()
                     for dst_type, dst_id in kids if dst_type == "artifact"}
            self._bodies = self._store.head_bodies(owned)
        return self._bodies

    def drawn_in(self, idents) -> dict[str, str]:
        """The chat each of these cards was drawn in, where that is known.

        A chat that owns the card drew it. Otherwise the card's own version
        names the message it came after, and that message is one chat's
        (`artifacts.chats_drawn_in`). A card that says neither is in no chat.
        """
        idents = list(idents)
        found = artifacts.chats_drawn_in({one: self._heads().get(one, "") for one in idents})
        for one in idents:
            holder = self.over.get(("artifact", one))
            if holder is not None and holder[0] == "chat":
                found[one] = holder[1]
        return found

    def row(self, kind: str, ident: str):
        """One chat, run or artifact, out of one read of all of that kind.

        All of them at once, the first time one is asked for: the browser and
        the rail both ask for every thing every task holds, and one query per
        thing was hundreds of them on every redraw.
        """
        if kind not in self._rows:
            lister = {"chat": self._store.list_chats, "run": self._store.list_runs,
                      "artifact": self._store.list_artifacts}.get(kind)
            self._rows[kind] = ({one.id: one for one in lister(limit=None)}
                                if lister else {})
        return self._rows[kind].get(ident)


def _only_a_page(body: str) -> str:
    """The workspace path of the one page a card's body shows, or "".

    A card is only a page when, links aside, it is one `frame` block pointing
    at a page of the workspace. The "Ready:" cards jobs drew until 23 September
    2026 have a summary around the page and are cards of their own.
    """
    try:
        spec = json.loads(body) if body else None
    except (TypeError, ValueError):
        return ""
    if not isinstance(spec, dict):
        return ""
    blocks = [b for b in spec.get("blocks") or []
              if isinstance(b, dict) and b.get("block") != "link"]
    if len(blocks) != 1 or blocks[0].get("block") != "frame":
        return ""
    href = str(blocks[0].get("href") or "")
    if not href.startswith(pages.ROUTE):
        return ""
    rel = unquote(href[len(pages.ROUTE):].split("?", 1)[0])
    return "" if not rel or rel.startswith(TASK_PREFIX) else rel


def _within(path: str, folder: str) -> bool:
    """Whether a workspace path is this folder or anything under it."""
    return bool(path and folder) and (path == folder or path.startswith(folder + "/"))


def _count_words(counts: dict[str, int]) -> str:
    """What is in this, in words, in the order the sections come in."""
    said = []
    for kind in ("page", "project", "task", "subtask", "step", "document", "chat", "run",
                 "card", "note", "md", "file", "folder"):
        many = counts.get(kind) or 0
        if many:
            one, lots = KIND_WORDS[kind]
            said.append(f'<span>{many} {one if many == 1 else lots}</span>')
    return "".join(said) or "<span>Nothing in it yet</span>"


def _section(title: str, many: int, rows: str, note: str = "", cls: str = "",
             cut: bool = True, tail: str = "") -> str:
    """One group of what is under an object, with its own count on its rule.

    ``cut`` says the rows stop at `MOST_LISTED` and the rest are counted
    underneath. Pages and documents are never cut, so they never say so.
    ``tail`` is what a section that cut its rows itself says instead.
    """
    more = tail or (f'<p class="omore">and {many - MOST_LISTED} more</p>'
                    if cut and many > MOST_LISTED else "")
    said = f'<p class="osaid">{html.escape(note)}</p>' if note else ""
    also = f" {cls}" if cls else ""
    return (f'<section class="oset{also}"><h2 class="divider">{html.escape(title)}'
            f'<span class="c">{many}</span></h2>{said}'
            f'<div class="rows">{rows}</div>{more}</section>')


def _its_emoji(name: str) -> tuple[str, str]:
    """A name's own emoji and the words after it, or ("", the name).

    A chat is named with one emoji in front of it on purpose (`rouh/chats.py`)
    and a project may be. That emoji is what the eye lands on, so it is the
    mark on the row rather than the first character of the words, and the row
    is not drawn with a picture twice.
    """
    from . import chats

    name = (name or "").strip()
    if not chats.starts_with_emoji(name):
        return "", name
    # One character, because in Python an astral emoji **is** one character.
    # A variation selector belongs to the character in front of it, and so
    # does a zero-width joiner and whatever it joins.
    wide = 1
    while len(name) > wide and name[wide] in ("\ufe0f", "\u200d"):
        wide += 2 if name[wide] == "\u200d" and len(name) > wide + 1 else 1
    return name[:wide], name[wide:].strip() or name


def _object_row(kind: str, where: str, name: str, meta: str = "",
                chip: str = "", number: str = "", extra: str = "") -> str:
    """One thing under this object, as a line that opens it.

    A link and not a button, whatever the thing is. A project and a task are
    pages and open in this frame; a chat, a run and a card are not pages at
    all, so their own addresses are handed up to Rouh, which opens each where
    it lives (`pages.follow_script`, and `frameGo` in app.js). One row, one
    address, and nothing here knows the difference.

    Every one of the five cells is written whether or not it has anything in
    it, because the row is a grid and a row that leaves a cell out is a row
    whose columns do not line up with the one above it.
    """
    mine, name = _its_emoji(name)
    mark = mine or KIND_MARKS.get(kind, "\u25C7")
    return (f'<a class="orow" href="{html.escape(where, quote=True)}" '
            f'data-kind="{html.escape(kind, quote=True)}"{extra}>'
            f'<span class="omark" aria-hidden="true">{mark}</span>'
            f'<span class="snum">{html.escape(number)}</span>'
            f'<span class="oname">{html.escape(name)}</span>'
            f'<span class="ochip">{chip}</span>'
            f'<span class="ometa-cell">{html.escape(meta)}</span></a>')


def _rerooted(path: str, folder: str) -> str:
    """The same file, under the folder it has since moved to.

    A `git mv` keeps the folder's own name and changes only what is above it,
    so the name is the seam: everything before it is where the folder used to
    be and everything after it is the file inside it. `private/personal/56.plans
    /56-01.x/index.html` under a task now at `private/misc/56.plans` is
    `private/misc/56.plans/56-01.x/index.html`.

    "" when the folder's name is nowhere in the path, which means this file was
    never in that folder and nothing here may guess where it went.
    """
    base = str(folder or "").rsplit("/", 1)[-1]
    if not base or not path:
        return ""
    if path.startswith(base + "/"):
        return folder + path[len(base):]
    at = path.find("/" + base + "/")
    return folder + path[at + 1 + len(base):] if at >= 0 else ""


def _mended(store: objects.ObjectStore, root, under: _Under, tree: _Tree,
            row) -> str:
    """One artifact's path, put right where the folder under it has moved.

    Every move rewrites these now (`objecttree.move`), and until 23 September
    2026 nothing did: a task filed into another project took its files with it
    and left every row naming one of them pointing at where they used to be.
    Pressing such a row asked for a file that is not there and Rouh drew a
    white page saying "the server said 404", which is the error the person
    reported that day. Fixing the move does nothing for the rows that are
    already wrong, and this is what does.

    So a path whose file is gone is looked at once, here, on the page that
    would have drawn the broken link: if the folder that owns it says where the
    file really is, and the file really is there, the row is put right and the
    good address is drawn. A path whose file is simply missing is left exactly
    as it is - nothing here invents a file, and a row that cannot be mended is
    still drawn, because a page that quietly dropped a line would be worse than
    one with a line that says 404.
    """
    path = str(getattr(row, "path", "") or "")
    if not path or not root:
        return path
    base = Path(str(root))
    try:
        if (base / path).exists():
            return path
    except OSError:
        return path
    folder = under.folder_over("artifact", row.id, tree)
    now = _rerooted(path, folder)
    if not now or now == path:
        return path
    try:
        if not (base / now).exists():
            return path
    except OSError:
        return path
    store.update_artifact(row.id, path=now)
    log.info("the artifact %s was at %s, which has moved to %s", row.id, path, now)
    return now


def doc_url(folder: str, name: str) -> str:
    """Where one notes file of a folder is read: on that object's own page."""
    return pages.url_for(TASK_PREFIX + folder) + "/?doc=" + quote(name, safe="")


def _read_head(path: Path, most: int) -> str:
    try:
        with open(path, "rb") as fh:
            return fh.read(most).decode("utf-8", "replace")
    except OSError:
        return ""


def documents(root, folder: str, *, instructions: bool = True) -> list[dict]:
    """Every page and every Markdown file directly in one folder.

    A project's documents, which are what is written in its own folder beside
    its tasks, and a task's own `.md` files for the line about it
    (`_doc_count`). A task's or a subtask's own page reads its folder itself
    (`_contents`).

    Each is ``{kind, name, title, href}``: ``kind`` is ``page`` for an
    ``.html`` and ``md`` for an ``.md``, ``name`` the file, ``title`` what it
    is called - a page's ``<title>``, a ``.md``'s file name, a ``step.md``'s
    own title - and ``href`` where a press opens it. A page opens as the page
    it is (`pages.url_for`); a ``.md`` opens on this object's own page, read
    (`docview`), because a ``.md`` is never served as a file.

    The page the object built comes first - ``index.html`` - then any other
    pages, then its `.md` files with a ``step.md`` first. Only this folder
    and not the ones under it.

    ``instructions`` False leaves its ``AGENTS.md`` out (or the ``CLAUDE.md``
    of a folder that has only that), which is what a project wants: its page
    has a button of its own for that file.
    """
    if not root or not folder:
        return []
    here = Path(str(root)) / folder
    try:
        with os.scandir(here) as found:
            # A link is not a document of this folder: what it points at is
            # somewhere else, and may not be in the workspace at all.
            names = [e.name for e in found if not e.name.startswith(".")
                     and not e.is_symlink() and e.is_file()]
    except OSError:
        return []
    out = []
    for name in names:
        low = name.lower()
        if low.endswith((".html", ".htm")):
            kind = "page"
            title = pages.title_of(here / name)
            href = pages.url_for(f"{folder}/{name}")
            rank = (0, 0 if low == "index.html" else 1, low)
        elif low.endswith(".md"):
            if not instructions and instructions_file(name):
                continue
            # Called by its file name, and not by the heading inside it
            # (`_md_title`).
            kind = "md"
            title = _md_title(here / name, name)
            href = doc_url(folder, name)
            rank = (1, 0 if low == docview.STEP_FILE else 1, low)
        else:
            continue
        out.append((rank, {"kind": kind, "name": name,
                           "title": title or name.rsplit(".", 1)[0], "href": href}))
    return [one for _rank, one in sorted(out, key=lambda pair: pair[0])]


def _doc_count(root, folder: str, kids=()) -> str:
    """"1 page", "2 pages and 1 .md": what a task holds, for a line about it.

    Its pages are every one it built, in its subtasks as well as its own
    folder (``kids`` are its step rows' folders, as `places_of` takes them);
    its `.md` files are its own.
    """
    pages_n = len(_page_files(root, places_of(root, folder, kids)))
    md_n = sum(1 for d in documents(root, folder) if d["kind"] == "md")
    said = []
    if pages_n:
        said.append(f"{pages_n} page" + ("" if pages_n == 1 else "s"))
    if md_n:
        said.append(f"{md_n} .md")
    return " and ".join(said)


# --------------------------------------------------------------------------
# What a task built, and what it was built with
# --------------------------------------------------------------------------
#
# Petar, 23 September 2026, on task 58: "the page is the main thing that is
# produced as result. everything else are pieces and leftovers - a chat that is
# useless once goal achieved, a md which is the work file, a card that is type
# 'here you go'. The most valuable thing is the HTML which is not accessible,
# and it should have been all the way on top of all the other content."
#
# Task 58's page said "1 document, 1 chat, 1 card" and its explainer was
# nowhere on it: the page was in its step's folder, the step had no row
# (the job wrote the folder itself), and this page listed only the files
# directly in the task's own folder and the steps the database knew. Task 56
# was the same from the other end: its step has a row, and the row's folder is
# in a second copy of the task under Personal, not in the folder the task's own
# row names under Misc. So where a task's work is, is both: every step folder
# on disk inside the task's folder, and every step the rows say is the task's,
# wherever its folder is (`places_of`). The task browser's count of its pages
# and a project's line for it read that one list; its own page reads the same
# two, one level at a time (`_subtasks`).


def _step_names(root, folder: str) -> list[str]:
    """The step folders directly inside this one, newest first.

    A step is what `objecttree` says one is inside a task: a folder whose name
    starts with a number. `source-code` and the rest are not, whatever is in
    them.
    """
    try:
        with os.scandir(Path(str(root)) / folder) as found:
            names = [e.name for e in found if not e.name.startswith((".", "_"))
                     and e.name not in objecttree.NOT_OBJECTS
                     and objecttree.is_a_task(e.name, inside_a_task=True)
                     and e.is_dir(follow_symlinks=False)]
    except OSError:
        return []
    return sorted(names, key=pages._step_key, reverse=True)


def _step_places(root, folder: str, depth: int = 1) -> list[tuple[str, str]]:
    """One step folder and every step inside it, as (path, step number)."""
    out = [(folder, steps.number_of(folder.rsplit("/", 1)[-1]))]
    if depth < MAX_DEPTH:
        for name in _step_names(root, folder):
            out += _step_places(root, f"{folder}/{name}", depth + 1)
    return out


def places_of(root, folder: str, kids=()) -> list[tuple[str, str, str]]:
    """Where one task's or step's work is, as (path, step number, reader).

    The folder itself first, with no number, then its steps newest first -
    the order its Steps are listed in - each followed by its own steps. Its
    steps are the step folders on disk inside it and the folders of the step
    rows it owns (``kids``), wherever those are: a step whose row says it is
    in another copy of the task is this task's step all the same.

    ``reader`` is the folder whose own page reads a working file of that
    place (`build_doc`): this one for everything inside it, and a step's own
    for a step that is somewhere else, which has a row and so a page.
    """
    if not root or not folder:
        return []
    tops = {f"{folder}/{name}": folder for name in _step_names(root, folder)}
    base = Path(str(root))
    for kid in kids:
        kid = str(kid or "")
        if kid and kid not in tops and not _within(kid, folder) and (base / kid).is_dir():
            tops[kid] = kid
    ordered = sorted(tops, reverse=True,
                     key=lambda at: (pages._step_key(at.rsplit("/", 1)[-1]), at))
    out = [(folder, "", folder)]
    for top in ordered:
        out += [(place, step, tops[top]) for place, step in _step_places(root, top)]
    return out


def _page_files(root, places) -> list[tuple[str, str, str]]:
    """Every page built in these places, as (place, step, file).

    Only what is there and would be served: an `.html` directly in the folder
    or in a step's, never one inside `source-code`, which is what a step was
    made from and not what it made. Within one place its `index.html` first,
    because that is the page the step built.
    """
    out = []
    for place, step, _reader in places:
        try:
            with os.scandir(Path(str(root)) / place) as found:
                names = [e.name for e in found if not e.name.startswith((".", "_"))
                         and e.name.lower().endswith((".html", ".htm"))
                         and not e.is_symlink() and e.is_file()]
        except OSError:
            continue
        names.sort(key=lambda n: (n.lower() != "index.html", n.lower()))
        out += [(place, step, name) for name in names]
    return out


def _step_words(root, task_folder: str) -> dict[str, dict]:
    """What a task's meta says about each of its steps, by folder name."""
    found = steps.listed_steps(Path(str(root)) / task_folder) if root else {}
    return {str(k): v for k, v in found.items() if isinstance(v, dict)}


def built_pages(root, places, titles: dict[str, str] | None = None) -> list[dict]:
    """The pages a task or a step built, which are what it was for.

    ``places`` is `places_of`'s answer for it. Each is ``{rel, href, step,
    title, about}``. A step's own `index.html` is
    that step: its number, the step's name - the row's when it has one
    (``titles``, by folder), else the one its task's meta gives it,
    else what its folder's sidecar says - and the one line its meta says
    about it. Any other page is called
    what its own `<title>` says. ``href`` is the page itself, which Rouh opens
    on the canvas at full width, exactly as `show_workspace_page` does.
    """
    base = Path(str(root)) if root else None
    if base is None:
        return []
    titles = titles or {}
    words: dict[str, dict[str, dict]] = {}
    out = []
    for place, step, name in _page_files(root, places):
        rel = f"{place}/{name}"
        title = about = ""
        if step and name.lower() == "index.html":
            over, _, own = place.rpartition("/")
            if over not in words:
                words[over] = _step_words(root, over)
            said = words[over].get(own) or {}
            title = (titles.get(place) or str(said.get("title") or "").strip()
                     or steps._title_of(base, base / place))
            about = _about(said.get("description"), title)
        title = title or pages.title_of(base / rel) or name.rsplit(".", 1)[0]
        out.append({"rel": rel, "href": pages.url_for(rel), "step": step,
                    "title": title, "about": about})
    return out


def _md_title(path: Path, name: str) -> str:
    """What a `.md` is called on the screen: its file name, and nothing else.

    It was the first heading inside it until 24 September 2026, so
    `61-01.notes.md` was listed as "The site plan and Sam's copy, as a site to
    click through" and opened under that name with the file's own name in
    small print, and the two never agreed. Petar: "It is annoying that the
    file name is not the same as the title, and I want those to be the same
    ... instead of synchronizing the title (the heading of the .md file) with
    the file name, we just have to have a more descriptive file name and use
    that as the name." So the name is the file's, and what makes it say
    something is the name a job gives a `.md` when it writes one (the
    agent instructions every agent starts with, `rouh/agent_instructions.py`, and the brief in
    `assistant_job.py`).

    A `step.md` is the one exception. It is a subtask's page, written by Rouh
    (`steps.py`), every one of them has the same file name, and its title is
    in its front matter.
    """
    if name.lower() == docview.STEP_FILE:
        return steps.parse(_read_head(path, 32768)).get("title") or ""
    return name


def _listed(entry: os.DirEntry) -> bool:
    """Whether one entry of a folder is shown to the person at all."""
    from . import workspace

    name = entry.name
    # A page's X-ray is part of the page, drawn over it (`rouh/xray.py`), and
    # not a file of its own to open.
    return not (name.startswith((".", "_")) or name in NOT_DOCUMENTS
                or name.lower().endswith(xray.SUFFIX)
                or name.lower().endswith(".pyc") or workspace.is_secret_name(name)
                or entry.is_symlink())


def _holds(path: Path) -> str:
    """What a folder holds, in words: "3 files", "4 files, 1 folder"."""
    files = folders = 0
    try:
        with os.scandir(path) as found:
            for entry in found:
                if not _listed(entry):
                    continue
                try:
                    if entry.is_dir(follow_symlinks=False):
                        folders += 1
                    else:
                        files += 1
                except OSError:
                    continue
    except OSError:
        return ""
    said = [f"{n} {word}" + ("" if n == 1 else "s")
            for n, word in ((files, "file"), (folders, "folder")) if n]
    return ", ".join(said) or "empty"


# --------------------------------------------------------------------------
# One level of a task: its subtasks, and what is its own
# --------------------------------------------------------------------------
#
# Petar, 24 September 2026, on task 61's page: "I want to restructure that
# page. This is not working out: there are too many things, and it is too
# scattered ... We end up with two kinds of information: Subtasks.
# Information that belongs specifically to that level."
#
# So a task's page, and a subtask's, is one level of the task: a subtask is
# one line, whatever it holds, and pressing it opens that subtask's own page,
# which is the same shape one level down - "like a folder, like a file
# system". What is directly in this level's folder, and the chats, runs and
# cards that belong to this level and not to one of its subtasks, are listed
# under the subtasks. A page is on it only when this level built one itself;
# a subtask's page is a button on the subtask's own line.


def _contents(root, folder: str) -> dict[str, list[str]]:
    """What is directly in one folder, by kind, each list in the order drawn.

    ``subtasks`` are the step folders in it (`objecttree.is_a_task`), each of
    which is a level with a page of its own; ``pages`` its `.html` files,
    `index.html` first; ``md`` its Markdown, `AGENTS.md` first; ``files``
    everything else; and ``folders`` the folders that are not subtasks, its
    `source-code` above all. What is never shown (`_listed`) is in none of
    them.
    """
    out: dict[str, list[str]] = {"subtasks": [], "pages": [], "md": [],
                                 "files": [], "folders": []}
    if not root or not folder:
        return out
    try:
        with os.scandir(Path(str(root)) / folder) as found:
            entries = [e for e in found if _listed(e)]
    except OSError:
        return out
    for entry in entries:
        name, low = entry.name, entry.name.lower()
        try:
            is_dir = entry.is_dir(follow_symlinks=False)
        except OSError:
            continue
        if is_dir:
            step = (name not in objecttree.NOT_OBJECTS
                    and objecttree.is_a_task(name, inside_a_task=True))
            out["subtasks" if step else "folders"].append(name)
        elif low.endswith((".html", ".htm")):
            out["pages"].append(name)
        elif low.endswith(".md"):
            out["md"].append(name)
        else:
            out["files"].append(name)
    for names in out.values():
        names.sort(key=str.lower)
    out["pages"].sort(key=lambda n: n.lower() != "index.html")
    out["md"].sort(key=lambda n: (not instructions_file(n), n.lower() != docview.STEP_FILE))
    return out


def _page_of(held: dict[str, list[str]]) -> str:
    """The one page a level built, by name, or "" when it has none.

    The rule the rail's dot has always used (`owning._artifact_at`): its
    `index.html`, else the only other page when there is exactly one, else
    the `step.md` Rouh wrote for it. A folder with two pages and neither of
    them `index.html` has no one page, so its line has no button, and its own
    page lists them both.
    """
    names = held["pages"]
    if names and names[0].lower() == "index.html":
        return names[0]
    if len(names) == 1:
        return names[0]
    for name in held["md"]:
        if name.lower() == docview.STEP_FILE:
            return name
    return ""


def _step_title(root, folder: str, row=None) -> tuple[str, str]:
    """A subtask's name and the one line said about it.

    The name is its row's when it has one, else the one its task's
    meta gives it, else what its folder's sidecar says: the same
    order `built_pages` reads them in. The line is the meta's.
    """
    parent, _, name = folder.rpartition("/")
    said = _step_words(root, parent).get(name) or {}
    title = str((row or {}).get("title") or "").strip() or str(said.get("title") or "").strip()
    if not title and root:
        base = Path(str(root))
        title = steps._title_of(base, base / folder)
    return title or name, _about(said.get("description"), title)


def _about(said, title: str) -> str:
    """The one line said about a subtask, or "" when it only says its name.

    A step Rouh filed from a card has its title written twice in
    meta, as its title and as its description, and the same words
    twice on one line read as a mistake (task 53, 24 September 2026).
    """
    about = str(said or "").strip()
    return "" if about.casefold() == str(title or "").strip().casefold() else about


def _over(tree: _Tree, row: dict):
    """What holds this, a row or a subtask that has none, or None."""
    if "over" in row:
        return row["over"]
    return tree.rows.get(tree.owner.get(str(row.get("id") or ""), ""))


def _called(tree: _Tree, row: dict) -> str:
    """Project, Task, or Subtask for a task inside a task."""
    if row.get("type") == "project":
        return "Project"
    over = _over(tree, row)
    return "Subtask" if over is not None and over.get("type") == "task" else "Task"


def _step_on_disk(tree: _Tree, root, rel: str) -> dict | None:
    """A subtask a job wrote as a folder and nothing else, as a row would say it.

    Most of them are: a job makes its step folder by hand, and the object
    rows never hear of it (task 61's three, on 24 September 2026). Such a
    subtask is still a level of its task with a page of its own, because a
    press on its line opens one. So a folder named as a step, directly inside
    a task or another subtask, is one, with no id, and ``over`` naming what
    holds it. None for anything else, which is what says there is nothing
    filed there.
    """
    parent, _, name = str(rel or "").rpartition("/")
    if (not root or not parent or name in objecttree.NOT_OBJECTS
            or not objecttree.is_a_task(name, inside_a_task=True)):
        return None
    over = _object_at(tree, root, parent)
    if over is None or over.get("type") != "task":
        return None
    base = Path(str(root))
    path = base / rel
    try:
        if path.is_symlink() or not path.is_dir() or base.resolve() not in path.resolve().parents:
            return None
    except OSError:
        return None
    title, _about = _step_title(root, rel)
    return {"id": "", "type": "task", "folder": rel, "slug": name, "title": title,
            "number": None, "status": "", "over": over}


def _object_at(tree: _Tree, root, rel: str) -> dict | None:
    """The object filed at this path: its row, or a subtask that has none."""
    here = next((r for r in tree.rows.values() if (r["folder"] or "") == rel), None)
    if here is not None or not rel:
        return here
    return _step_on_disk(tree, root, rel)


def subtask_within(root, folder: str, rest: str) -> tuple[str, str]:
    """The deepest subtask folder a path inside a task starts with, and the
    rest of the path under it.

    `addressing.inside` finds the deepest *row* an address starts with, and a
    subtask a job wrote by hand has none, so `/task/<task>/61-01.x` comes back
    as the task with ``61-01.x`` inside it. That is a level with a page of
    its own (`_step_on_disk`), so this walks on down through every such
    folder that is really there. ``(folder, rest)`` unchanged when there is
    none.
    """
    parts = [part for part in str(rest or "").split("/") if part]
    if not root or not folder:
        return folder, "/".join(parts)
    base = Path(str(root))
    at = folder
    while parts and parts[0] not in objecttree.NOT_OBJECTS \
            and objecttree.is_a_task(parts[0], inside_a_task=True):
        path = base / at / parts[0]
        try:
            if path.is_symlink() or not path.is_dir():
                break
        except OSError:
            break
        at = f"{at}/{parts.pop(0)}"
    return at, "/".join(parts)


def _changed(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _holds_words(counts: dict[str, int]) -> str:
    """"1 page · 2 .md · 1 folder": what one subtask holds, on its line."""
    said = []
    for kind in ("subtask", "page", "chat", "run", "card", "md", "file", "folder"):
        many = counts.get(kind) or 0
        if many:
            one, lots = KIND_WORDS[kind]
            said.append(f"{many} {one if many == 1 else lots}")
    return " · ".join(said) or "Nothing in it yet"


def _subtasks(root, tree: _Tree, under: _Under, here: dict, rel: str,
              depth: int = 1, kept: dict | None = None) -> list[dict]:
    """This level's subtasks, newest first, as their lines say them.

    The step folders on disk directly in its own folder, and the step rows it
    owns wherever their folders are: a subtask whose row names a folder in
    another copy of the task is this task's all the same (`places_of` has the
    same rule, and the reason for it). Each is ``{folder, href, num, title,
    about, chip, page, holds}``: ``href`` its own page, ``page`` the page it
    built (`_page_of`), or "", and ``holds`` what is in it, in words.

    And ``kids``, its own subtasks, the same shape, all the way down: the page
    hangs them under it the way a chat's forks hang under the chat
    (`_subtask_row`). Petar, 10 October 2026: "sub-sub tasks are not visible
    on the task list. Can you make them like chats?" Until then a task's page
    listed one level, and 89-10-02 was two presses away, behind 89-10.
    """
    ident = str(here.get("id") or "")
    if kept is None:
        kept = archiving.archived()
    rows = {str(r.get("folder") or "") or "#" + r["id"]: r
            for r in (tree.kids(ident, "task") if ident else [])}
    found: dict[str, dict | None] = {}
    for name in _contents(root, rel)["subtasks"]:
        folder = f"{rel}/{name}"
        found[folder] = rows.pop(folder, None)
    found.update(rows)
    ordered = sorted(found, reverse=True,
                     key=lambda at: (pages._step_key(at.rsplit("/", 1)[-1]), at))
    out = []
    for at in ordered:
        row = found[at]
        folder = "" if at.startswith("#") else at
        name = folder.rsplit("/", 1)[-1] if folder else ""
        title, about = (_step_title(root, folder, row) if folder
                        else (row["title"] or row["slug"] or row["id"], ""))
        held = _contents(root, folder)
        page = _page_of(held)
        counts = {"subtask": len(held["subtasks"]), "page": len(held["pages"]),
                  "md": len(held["md"]), "file": len(held["files"]),
                  "folder": len(held["folders"])}
        if page.lower() == docview.STEP_FILE:
            counts["page"], counts["md"] = 1, counts["md"] - 1
        if row is not None:
            inside = {f"{folder}/{n}" for n in held["subtasks"]}
            counts["subtask"] += sum(1 for k in tree.kids(row["id"], "task")
                                     if (k.get("folder") or "") not in inside)
            for kind, many in under.own("task", row["id"]).items():
                word = "card" if kind == "artifact" else kind
                counts[word] = counts.get(word, 0) + len(many)
        state = str((row or {}).get("status") or "")
        if state == "done":
            # A step of a goal done with nothing made is not called Done
            # (`goals.done_pill`).
            from . import goals

            try:
                state = goals.done_pill(SimpleNamespace(folder=folder)) or state
            except Exception:
                log.exception("whether step %s is complete could not be read", folder)
        out.append({
            "folder": folder,
            # Archived with its task or on its own (`rouh/archiving.py`): it is
            # listed under Archived and not with the live subtasks.
            "archived": row is not None and row["id"] in kept,
            "href": _own_page({"folder": folder}),
            "num": _step_number(row if row is not None else {"slug": name}),
            "title": title,
            # Its icon, in front of its title (`rouh/taskicons.py`), and its id, which a press
            # on the icon changes it by.
            "id": (row or {}).get("id") or "",
            "icon": taskicons.shown(tree.icons.get((row or {}).get("id") or "", ""), title),
            "about": about,
            "chip": (f'<span class="task-status" data-status="{html.escape(state)}">'
                     f'{html.escape(STATE_WORDS.get(state, state))}</span>'
                     if state and state != "open" else ""),
            "page": ("" if not page else doc_url(folder, page)
                     if page.lower() == docview.STEP_FILE
                     else pages.url_for(f"{folder}/{page}")),
            "holds": _holds_words(counts),
            # The page's own file in its folder, for the PDF in its three dots, and whether it
            # is pinned, for their Pin (`_subtask_dots`).
            "page_file": page,
            "pinned": bool((row or {}).get("pinned")),
            "kids": (_subtasks(root, tree, under, row if row is not None else {}, folder, depth + 1,
                               kept)
                     if folder and depth < MAX_DEPTH else []),
        })
    return out


def icon_mark(icon: dict, ident: str, title: str, cls: str) -> str:
    """A task's icon in front of its title on its page (`rouh/taskicons.py`): a press on it
    opens the icon picker (`taskicon.js`); for a folder with no row it is the icon alone.
    The same mark the task browser draws (`RouhTaskIcon.mark` in taskicon.js)."""
    face = (f'<img src="{html.escape(icon["img"], quote=True)}" alt="">' if icon.get("img")
            else html.escape(icon.get("icon") or ""))
    if not ident:
        return f'<span class="ticon {cls}" aria-hidden="true">{face}</span>'
    return (f'<span class="ticon {cls}" role="button" tabindex="0" '
            f'data-task="{html.escape(ident, quote=True)}" '
            f'data-title="{html.escape(title, quote=True)}" '
            f'aria-label="{html.escape("Change the icon of " + title, quote=True)}">{face}</span>')


def _subtask_row(one: dict, depth: int = 0, whole: bool = False, rel: str = "",
                 person=None) -> str:
    """One subtask, as one line that opens it, with its page on a button.

    The line is a link to the subtask's own page, stretched over the whole of
    it; the button is a link of its own on top, to the page the subtask
    built, so the page is one press away without going in first. Petar: "if I
    just want to see the HTML page for 6101, I can click that."
    """
    title = html.escape(one["title"])
    num = f'<span class="snum">{html.escape(one["num"])}</span>' if one["num"] else ""
    name = (f'<a class="oname" href="{html.escape(one["href"], quote=True)}">{title}</a>'
            if one["href"] else f'<span class="oname">{title}</span>')
    if one.get("icon"):
        name = icon_mark(one["icon"], one.get("id") or "", one["title"], "sicon") + name
    about = f'<span class="sabout">{html.escape(one["about"])}</span>' if one["about"] else ""
    said = " ".join(part for part in (one["num"], one["title"]) if part)
    go = (f'<a class="sgo" href="{html.escape(one["page"], quote=True)}" '
          f'aria-label="Open the page of {html.escape(said, quote=True)}">Open page'
          f'<span aria-hidden="true"> →</span></a>' if one["page"] else "")
    deep = f' data-depth="{min(depth, 4)}"' if depth else ""
    kids = "".join(_subtask_row(kid, depth + 1, whole, rel, person) for kid in one.get("kids") or ()
                   if whole or not kid["archived"])
    dots = _subtask_dots(one, rel, person)
    return (f'<div class="srow{" sdotted" if dots else ""}" data-kind="subtask"{deep}>'
            f'<div class="stext"><span class="shead">{num}{name}{one["chip"]}</span>'
            f'{about}<span class="sholds">{html.escape(one["holds"])}</span></div>'
            f'{go}{dots}<span class="schev" aria-hidden="true">›</span></div>' + kids)


def _page_rows(built: list[dict], dots=None) -> str:
    """The pages a task built, as the first thing on its page.

    Bigger than every other line on it, and one page alone is bigger still:
    a card the width of the page with the step's name on it, what it found in
    a line underneath, and the words that say what a press does. A link like
    every other row here, so a press hands the page up to Rouh, which opens
    it on the canvas at full width (`pages.follow_script`, `frameGo`).

    ``dots`` gives each its own three dots (`_item_line`), on Rouh's own page
    of the task: ``dots(row, one)``.
    """
    rows = []
    for one in built:
        about = (f'<span class="pabout">{html.escape(one["about"])}</span>'
                 if one["about"] else "")
        num = (f'<span class="snum">{html.escape(one["step"])}</span>'
               if one["step"] else "")
        rows.append(
            f'<a class="prow" href="{html.escape(one["href"], quote=True)}" '
            f'data-kind="page">'
            f'<span class="omark" aria-hidden="true">{KIND_MARKS["page"]}</span>'
            f'<span class="ptext"><span class="phead">{num}'
            f'<span class="oname">{html.escape(one["title"])}</span></span>{about}</span>'
            f'<span class="pgo">Open the page<span aria-hidden="true"> →</span></span>'
            f'</a>')
        if dots is not None:
            rows[-1] = dots(rows[-1], one)
    return "".join(rows)


def _kind_pill(word: str, kind: str = "") -> str:
    """What kind a line is, in one word. ".md" keeps its case: it is a name.

    ``kind`` is said on the pill itself where it is not on a row that says it,
    which is the heading of one file read (`build_doc`).
    """
    lc = " lc" if word.startswith(".") else ""
    said = f' data-kind="{html.escape(kind, quote=True)}"' if kind else ""
    return f'<span class="okind{lc}"{said}>{html.escape(word)}</span>'


def _artifact_where(row, path: str = "") -> str:
    """Where a card, a page or a document is opened.

    The bytes where it has them: a built `index.html` or a `step.md` is a real
    file in the workspace and `path` names it, so the page itself is what a
    press on it opens. Anything else - a card, which is blocks of JSON and not
    a file - is opened by its own address, on Rouh's canvas.
    """
    where = path or str(getattr(row, "path", "") or "")
    if where.lower().endswith((".html", ".htm")):
        return pages.url_for(where)
    return addressing.url_for("artifact", row.id)


def instructions_file(name: str) -> bool:
    """Whether a file of a folder is its instructions, by either name."""
    return instructions.is_instructions(name)


def instructions_of(root, folder: str) -> str:
    """What a project's `AGENTS.md` says, or "" when it has none."""
    if not root or not folder:
        return ""
    try:
        return instructions.in_folder(Path(str(root)) / folder).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def write_instructions(root, folder: str, said: str) -> dict:
    """Put a project's instructions in its `AGENTS.md`, or take the file away.

    Emptied means emptied: the file goes, rather than being left as a heading
    with nothing under it that every reader afterwards has to decide about.
    A `CLAUDE.md` the folder still had from before the rename goes too, once
    what it said has been written under the new name, so the folder is never
    left with two answers to the same question.
    """
    if not root or not folder:
        return {"ok": False, "why": "That project has no folder to write to."}
    here = Path(str(root)) / folder
    if not here.is_dir():
        return {"ok": False, "why": f"There is no folder at {folder}."}
    path = here / INSTRUCTIONS
    old = here / instructions.OLD_NAME
    text = str(said or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    try:
        if not text:
            path.unlink(missing_ok=True)
            old.unlink(missing_ok=True)
            return {"ok": True, "did": "the instructions are gone"}
        path.write_text(text[:INSTRUCTIONS_MAX] + "\n", encoding="utf-8")
        old.unlink(missing_ok=True)
    except OSError as exc:
        log.warning("%s could not be written: %s", path, exc)
        return {"ok": False, "why": f"{INSTRUCTIONS} could not be written: {exc}"}
    return {"ok": True, "did": "the instructions are written down"}


def _held():
    """The attachment store, which is where a project's own files are kept.

    Built here rather than reached for in `runtime.py`: this module is what
    decides that a project's files are attachments and under which key, and a
    second `Attachments` over the same directory is the same store.
    """
    from . import attachments
    from .config import config

    return attachments.Attachments(config.data_dir,
                                   readable_by=config.crew_user or None,
                                   group=config.attachments_group)


def _project_files(project_id: str) -> list[dict]:
    """The files attached to one project, oldest first, without their paths."""
    return _files_under(files_key(project_id))


def task_files(task_id: str) -> list[dict]:
    """The files uploaded to one task or subtask from its page, oldest first."""
    return _files_under(task_files_key(task_id)) if task_id else []


def _files_under(key: str) -> list[dict]:
    """The files kept under one key of the attachment store, as a page draws them.

    The path on disk is the server's own business and is deliberately left out,
    exactly as it is for a file attached in a chat (`server.attach`): the page
    opens a file by its address and has no use for where this machine keeps it.
    """
    out = []
    for record in _held().listing(key):
        out.append({"id": record["id"], "name": record["name"],
                    "size": int(record.get("size") or 0),
                    "kind": record.get("kind") or "file",
                    "media_type": record.get("media_type") or "",
                    "ts": float(record.get("ts") or 0),
                    "at": f"/attachments/{key}/{record['id']}"})
    return out


def _file_row(one: dict) -> str:
    """One file on a project's page, as the page is served.

    The cross that takes a file off is not here: it is drawn by
    `projectpage.js`, and only when Rouh is framing the page, so a page read at
    its own address never offers a button that could not work. The row itself
    is written here so the files are on the page whether or not a script runs.
    """
    from . import attachments

    return (f'<div class="orow frow" data-file="{html.escape(one["id"], quote=True)}">'
            f'<span class="omark" aria-hidden="true">\U0001F4CE</span>'
            f'<a class="oname" href="{html.escape(one["at"], quote=True)}" '
            f'target="_blank" rel="noopener">{html.escape(one["name"])}</a>'
            f'<span class="ometa-cell">'
            f'{html.escape(attachments.human_size(one["size"]))}</span>'
            f'</div>')


def _note_row(one: dict, now: datetime) -> str:
    """One thing Rouh was told to keep about this project.

    Not a link, because a kept note is not an object and has no address of its
    own: it is a rule in Synapse Master (`rouh/rules.py`) or an old `facts` row, read and changed on the Rules page under the
    person's name (`rouh/web/memory.py`). The label it was filed under is on
    the row because that is the word the model finds it again by, and it is
    what the person says when they want it changed.
    """
    return (f'<div class="orow nrow">'
            f'<span class="omark" aria-hidden="true">\U0001F4DD</span>'
            f'<span class="nkey">{html.escape(one["key"])}</span>'
            f'<span class="nsaid">{html.escape(one["value"])}</span>'
            f'<span class="ometa-cell">'
            f'{html.escape(stamp(one.get("updated_at") or one.get("created_at") or 0, now))}'
            f'</span></div>')


def _project_head(here: dict, described: str) -> str:
    """The part of a project's page that only a project has.

    In the order the person asked for on 23 September 2026, which is the order
    Claude's own project screen has them in: the name, what the project is
    for under it, and then the box that starts a chat - "the new chat is
    directly the input box at the very top and once you hit enter it opens that
    chat on a New screen". The two pills under that are the two things a
    project holds besides its work: the files attached to it and its
    instructions. The three dots at the top open Edit, which is the name and
    the description in one panel.

    Every one of these is inert markup until `projectpage.js` picks it up, and
    that script takes them off the page altogether when Rouh is not framing it:
    at its own address there is nothing signed in to hand a change to, so the
    page says it is read only rather than offering buttons that would fail.
    """
    name = here["title"] or here["slug"] or ""
    return (
        '<div class="pjbar">'
        '<button type="button" class="odots" id="pjMore" aria-haspopup="true" '
        'aria-expanded="false" aria-label="More for this project">⋯</button>'
        '<div class="menu pjmenu" id="pjMenu" role="menu" hidden>'
        '<button type="button" class="menu-item" id="pjEdit" role="menuitem" '
        'data-icon="edit">Edit</button>'
        '</div></div>'
        + (f'<p class="odesc" id="pjDesc">{html.escape(described)}</p>'
           if described else '<p class="odesc" id="pjDesc" hidden></p>')
        + '<form class="pjsay" id="pjSay">'
          '<label class="vh" for="pjWhat">Start a chat in this project</label>'
          f'<textarea id="pjWhat" rows="1" placeholder="Start a new chat in '
          f'{html.escape(name, quote=True)}"></textarea>'
          '<button type="submit" class="pjgo" aria-label="Start this chat">'
          '<svg viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" '
          'stroke-width="1.8"><path d="M3 8h9M8.5 4l4 4-4 4"/></svg></button>'
          '</form>'
    )


def talked_in(store: objects.ObjectStore, rel: str) -> objects.Task | None:
    """The numbered task whose conversation this object's page is beside.

    A task's own, and for a step the task it is a step of, however deep: a
    task has one conversation and its steps are talked about in it. That is
    the conversation Rouh opens beside a step's page (`pickThread` in app.js,
    from the same `TASK_FOLDER` rule), so it is the task this page's Start
    chat starts a chat about. None for anything that is not inside a
    numbered task.
    """
    parts = [part for part in str(rel or "").split("/") if part]
    for at, part in enumerate(parts):
        if TASK_FOLDER.match(part):
            try:
                return store.by_folder("task", "/".join(parts[: at + 1]))
            except Exception:
                log.exception("could not look up the task over %s", rel)
                return None
    return None


def build_task(store: objects.ObjectStore, root, rel: str, names=(),
               person=None) -> str | None:
    """One object's own page: what it is, and everything under it.

    Until 22 September 2026 this was a name in bold and one flat list of every
    folder underneath it, which is what the person meant by "the current
    project page is far too plain": a project holds chats, runs and what has
    been drawn as well as tasks, and none of those were on it at all, so
    anything in a project that was not a folder could be reached from nowhere.

    A project's page is still that: a header that says what it is, what is in
    it counted, and one section per kind - the projects inside it, its tasks,
    its documents, its conversations, its runs and its artifacts - with every
    line a link to that thing's own address. A task's page and a subtask's are
    one level of the task instead, its subtasks and what is its own (`_level`).

    None when nothing on this workspace is filed at that path, which is what
    tells the caller to say so rather than to draw an empty page. `names` is
    what the signed-in person is called (`_waiting_panel`), and ``person`` is
    who they are, whose download links a file's line carries (`_file_line`).
    """
    tree = _Tree(store)
    here = _object_at(tree, root, rel)
    if here is None:
        return None
    if str(here.get("type") or "task") != "project":
        return _level(store, root, tree, here, rel, names, person)

    # ---- the header ----
    _own, _others, when = _facts(root, rel)

    # ---- what is under it ----
    kids = tree.kids(here["id"])
    projects = [k for k in kids if k["type"] == "project"]
    tasks = [k for k in kids if k["type"] == "task"]
    under = _Under(store)
    loose = under.loose("project", here["id"])
    # A project's folder holds its tasks, and what is written in it besides
    # them is its documents.
    docs = documents(root, rel, instructions=False)
    # What was drawn under it, less what is one of its own documents: a card
    # that showed a page is recorded with that page's path, and listing it
    # again beside the page is the "same thing twice" Petar could not tell
    # apart on task 56.
    cards = []
    for _k, ident in loose.get("artifact", ()):
        row = under.row("artifact", ident)
        if row is None:
            continue
        path = _mended(store, root, under, tree, row) or under.page_of(ident)
        if _within(path, rel):
            continue
        cards.append((row, path))
    # What Rouh was told to keep about this project. Petar, 24 September 2026:
    # "Kept where? When I open the Kvadrat project, it is not there." It was
    # in the general memory with nothing saying so, and now a note kept in a
    # conversation filed under a project is that project's and is on this page
    # (`rouh/keeping.py`).
    notes = keeping.notes_of(here["id"])
    counts = {"project": len(projects), "task": len(tasks),
              "document": len(docs), "card": len(cards), "note": len(notes)}
    for other in ("chat", "run"):
        counts[other] = len(loose.get(other, ()))

    body = []
    if projects:
        body.append(_section(
            "Projects", len(projects),
            "".join(_object_row("project", _own_page(p), p["title"] or p["slug"] or p["id"],
                                p["folder"] or "")
                    for p in projects[:MOST_LISTED])))
    if tasks:
        # One line each, and its subtasks on its own page rather than nested
        # here. They were nested until 22 September 2026, which put two
        # hundred and thirty lines between a project's name and its first
        # conversation: the sections underneath were below the fold on a page
        # nobody scrolled.
        rows = []
        for one in tasks[:MOST_LISTED]:
            folder = one["folder"] or ""
            # Its subtasks as its own page counts them: the rows it owns and
            # the step folders a job wrote by hand, which have none.
            steps_under = len({f"{folder}/{name}" for name in _contents(root, folder)["subtasks"]}
                              | {k.get("folder") or "#" + k["id"] for k in tree.kids(one["id"])})
            now = str(one.get("status") or "")
            if now == "waiting":
                # Answered from its page, it is on the job now; its question
                # dismissed, it asks nothing (`_asking`).
                _question, _notes, line = answering.asked_of(root, folder, names)
                word = answering.answers_to({one["id"]: line}).get(one["id"])
                if word is not None:
                    now = "answered" if word.answer else ""
            chip = (f'<span class="task-status" data-status="{html.escape(now)}">'
                    f'{html.escape(STATE_WORDS.get(now, now))}</span>'
                    if now and now != "open" else "")
            # What is in it, in words, rather than where it is: the folder was
            # on this line until 23 September 2026 and was the one thing on it
            # nobody reads.
            inside = [f"{steps_under} subtask" + ("" if steps_under == 1 else "s")
                      ] if steps_under else []
            held_docs = _doc_count(root, folder,
                                   [kid.get("folder") for kid in tree.kids(one["id"], "task")])
            if held_docs:
                inside.append(held_docs)
            rows.append(_object_row(
                "task", _own_page(one),
                one["title"] or one["slug"] or one["id"],
                ", ".join(inside),
                chip,
                str(one["number"]) if one.get("number") is not None
                else _step_number(one)))
        body.append(_section("Tasks", len(tasks), "".join(rows)))

    if docs:
        body.append(_section(
            "Documents", len(docs),
            "".join(_object_row(d["kind"], d["href"], d["title"],
                                d["name"] if d["title"] != d["name"] else "",
                                _kind_pill(_file_word(d["name"]) if d["kind"] == "file"
                                           else DOC_WORDS[d["kind"]]))
                    for d in docs),
            "What is written in this project's own folder. A page opens as the page "
            "it is; a .md opens here, to read.", cls="odocs", cut=False))

    if counts["chat"]:
        body.append(_section("Chats", counts["chat"],
                             "".join(_chat_rows(under, loose["chat"][:MOST_LISTED]))))
    if counts["run"]:
        body.append(_section("Runs", counts["run"],
                             "".join(_run_rows(under, loose["run"][:MOST_LISTED]))))
    if cards:
        body.append(_section(
            "Cards", len(cards), "".join(_card_rows(cards[:MOST_LISTED])),
            "What Rouh drew in a conversation about this. A card opens by itself "
            "on Rouh's canvas, with a cross that brings you back here."))

    if notes:
        now = datetime.now()
        body.append(_section(
            "Rules", len(notes),
            "".join(_note_row(one, now) for one in notes),
            "What Rouh follows whenever this project comes up. Rules, under your own "
            "name, is where every rule is read and changed.", cls="onotes", cut=False))

    # ---- a project's own files ----
    #
    # Its own section rather than a line in the header, because a project with
    # a contract, a spreadsheet and three screenshots on it is a list like any
    # other list on this page. Files are the person's own uploads and are never
    # in the workspace: they are in the attachment store, under the project's
    # id, exactly as a file attached in a chat is under the chat's.
    held = _project_files(here["id"])
    rows = "".join(_file_row(one) for one in held)
    body.append(
        f'<section class="oset" id="pjFilesSet"{"" if held else " hidden"}>'
        f'<h2 class="divider">Files<span class="c" id="pjFileCount">'
        f'{len(held)}</span></h2>'
        f'<div class="rows" id="pjFileRows">{rows}</div></section>')

    said = ['<button type="button" class="obtn" id="pjAdd">Add files</button>',
            ('<button type="button" class="obtn" id="pjInstr">Instructions'
             '<span class="dot" id="pjInstrDot" hidden></span></button>')]

    # The description is the project's own column and is not on the `object`
    # view, which is the two kinds' common shape and has no room for one of
    # them. One read, on the one page that draws it.
    row = store.get_project(here["id"])
    described = str(getattr(row, "description", "") or "")
    head = (f'<header class="ohead pj">'
            f'<div class="eyebrow">project'
            f'{" &middot; " + html.escape(rel) if rel else ""}</div>'
            f'<h1 class="oname-big">'
            f'<span id="pjName">{html.escape(here["title"] or here["slug"] or rel)}</span>'
            f'</h1>'
            + _project_head(here, described)
            + f'<p class="ocounts">{_count_words(counts)}'
            f'{"<span>" + stamp(when, datetime.now()) + "</span>" if when else ""}</p>'
            f'<p class=\'olinks\'>{"".join(said)}</p>'
            f'</header>')

    return head + ("".join(body) or
                   '<p class="none">Nothing in this yet. A task, a document, a chat, a '
                   'run or a card filed here appears on this page.</p>')


def _chat_rows(under: _Under, found, drew: dict[str, int] | None = None,
               person=None) -> list[str]:
    """One line per chat. `drew` is how many cards each drew, for a list of
    chats alone, which says so on the line in place of the word "Chat".
    With ``person``, each line has its own three dots (`_chat_line`)."""
    rows = []
    for _k, ident in found:
        row = under.row("chat", ident)
        if row is None:
            continue
        if drew is None:
            chip = _kind_pill("Chat")
        else:
            many = drew.get(ident, 0)
            chip = (f'<span class="ocards">{many} card{"" if many == 1 else "s"}</span>'
                    if many else "")
        rows.append(_chat_line(
            _object_row("chat", addressing.url_for("chat", ident), row.title or "Untitled",
                        stamp(row.last_activity or row.created_at, datetime.now()), chip),
            row, person))
        rows.extend(_fork_rows(under, ident, person))
    return rows


def _fork_rows(under: _Under, chat_id: str, person=None) -> list[str]:
    """The forks of one chat, each a line indented under it.

    A fork is a side question asked of its chat and is in no list of its
    own (`rouh/forks.py`), so before 5 October 2026 a task's page never
    showed one, and the only way back into a fork was its mark in the
    middle of the conversation. Petar asked for them grouped under the chat
    they came off: each one a line, deeper for a fork of a fork, that opens
    it on its strip beside the chat. A fork detached from its chat is not
    one any more, and is not here (`forks.detach`).
    """
    from . import forks

    rows = []
    for ident, depth in forks.family(chat_id):
        row = under.row("chat", ident)
        if row is None:
            continue
        rows.append(_chat_line(_object_row(
            "fork", addressing.url_for("chat", ident), row.title or "Untitled",
            stamp(row.last_activity or row.created_at, datetime.now()),
            _kind_pill("Fork"),
            extra=f' data-depth="{min(depth, 4)}"'), row, person))
    return rows


def _run_rows(under: _Under, found) -> list[str]:
    rows = []
    for _k, ident in found:
        row = under.row("run", ident)
        if row is None:
            continue
        word = RUN_WORDS.get(str(row.state or ""), str(row.state or ""))
        chip = (f'<span class="task-status" data-status="{html.escape(str(row.state or ""))}">'
                f'{html.escape(word)}</span>' if word else _kind_pill("Run"))
        rows.append(_object_row("run", addressing.url_for("run", ident),
                                row.title or "Untitled",
                                stamp(row.started_at, datetime.now()), chip))
    return rows


def _card_rows(cards) -> list[str]:
    rows = []
    for row, path in cards:
        # A card is blocks and has no file. One that names a page somewhere
        # else in the workspace is that page, and says so.
        is_page = str(path or "").lower().endswith((".html", ".htm"))
        rows.append(_object_row("page" if is_page else "card",
                                _artifact_where(row, path),
                                row.title or "Untitled",
                                str(path) if is_page
                                else stamp(row.created_at, datetime.now()),
                                _kind_pill("Page" if is_page else "Card")))
    return rows


def _level(store: objects.ObjectStore, root, tree: _Tree, here: dict, rel: str,
           names=(), person=None) -> str:
    """One task's or one subtask's own page: its subtasks, and what is its own.

    Its name, with the date it last changed on the same line at the right,
    and under it, in this order, the order Petar asked for on 24 September
    2026 (fr_a52896d17de5): "move chats to the very top immediately under
    the title. Pages after that, decisions section, after that, subtasks
    after that, and finally 'Directly in this task'".

    - **Its chats**, newest first, each saying how many cards it drew. The
      conversations are where the work on a task is done and talked about,
      so they come first.
    - **Its page**, only when this level built one itself: its `index.html`,
      any other page in its own folder, or the `step.md` Rouh wrote for it.
    - **Its decision**: what a waiting task asks the person, as one compact
      card that opens in place into the whole box (`_waiting_panel`). There
      is no page of its own to go to: "decisions can be clicked to be
      expanded to a card, as we will not have additional pages."
    - **Its subtasks**, one line each, newest first (`_subtasks`). A press
      opens the subtask's own page, which is this same function one level
      down; the button on the line opens the page it built.
    - **What is directly in it**: the runs and cards that belong to this
      level and not to a subtask of it, then its `.md` files, its other files
      and its folders. A card that is one of the pages already on this page,
      its own or a subtask's, is not listed again: it is the page. Nor is a
      card one of the chats above drew: it is in that chat, and the chat's
      Cards lays all of them out (`artifacts.drawn_in`).

    The path and the counts that were under the name went the same day
    ("remove this: task · work/acme/61.messaging", and the counts):
    the breadcrumb already says where the task is, and each section counts
    its own.
    """
    under = _Under(store)
    ident = str(here.get("id") or "")
    called = _called(tree, here)
    over = _over(tree, here)
    now = datetime.now()

    # ---- the header ----
    shown = (str(here["number"]) if here.get("number") is not None
             else _step_number(here))
    number = f'<span class="num">{html.escape(shown)}</span>' if shown else ""
    state = str(here.get("status") or "")
    # What it asks the person, and whether they have answered it
    # (`_waiting_panel`). A task they have answered is waiting on the job that
    # took the answer in, and its pill says so rather than Waiting; one whose
    # question they dismissed asks nothing of them, and has no pill.
    asking = (_asking(root, rel, names, ident)
              if called == "Task" and state in ("waiting", "done") else None)
    pill = state
    if state == "waiting" and asking and asking[3] is not None:
        pill = "answered" if asking[3].answer else ""
    if state == "done" and ident:
        from . import goals

        try:
            pill = goals.done_pill(store.get_task(ident)) or pill
        except Exception:
            log.exception("whether step %s has anything to show could not be read", ident)
    status = (f'<span class="task-status" data-status="{html.escape(pill)}">'
              f'{html.escape(STATE_WORDS.get(pill, pill))}</span>'
              if pill and pill != "open" else "")
    status += _silo_chips(person, ident)
    _own, _others, when = _facts(root, rel)

    # ---- what is in it ----
    held = _contents(root, rel)
    subs = _subtasks(root, tree, under, here, rel)
    own = under.own("task", ident) if ident else {}
    base = Path(str(root)) if root else Path(".")

    # Its own page, and only its own: a subtask's is on the subtask's line.
    # Its own place in the Archive, if it has one: a pill beside its name,
    # and Unarchive in place of Archive in its menu (`_task_dots`).
    shelved = bool(ident) and ident in archiving.archived(store)
    # Who made it, when that was not him (`rouh/task_origin.py`): said beside its name,
    # and the menu offers to make it his own, somebody else's or Rouh's.
    made_for = task_origin.origins(store).get(ident) if ident else None
    built = []
    if held["pages"]:
        step = shown if called == "Subtask" else ""
        built = built_pages(root, [(rel, step, rel)],
                            {rel: here["title"]} if here.get("title") else None)
        for one in built:
            one["step"] = one["step"] or shown
    elif _page_of(held):
        name = _page_of(held)
        built = [{"rel": f"{rel}/{name}", "href": doc_url(rel, name), "step": shown,
                  "title": _md_title(base / rel / name, name) or here.get("title") or name,
                  "about": ""}]
    as_page = {one["rel"].rsplit("/", 1)[-1] for one in built}

    # A card that showed one of the pages on this page is recorded with that
    # page's path, and is that page: listing it again as well is the "same
    # thing twice" Petar could not tell apart on task 56.
    places = [rel] + [s["folder"] for s in subs if s["folder"]]
    held_cards = [card for _k, card in own.get("artifact", ())]
    # Which of this level's chats drew each card it holds, so a card drawn in
    # one is found there and not listed again under the chats.
    talked = {chat for _k, chat in own.get("chat", ())}
    drawn = {card: chat for card, chat in under.drawn_in(held_cards).items()
             if chat in talked}
    drew: dict[str, int] = {}
    cards = []
    for card in held_cards:
        row = under.row("artifact", card)
        if row is None:
            continue
        if card in drawn:
            if row.kind == "card":
                drew[drawn[card]] = drew.get(drawn[card], 0) + 1
            continue
        path = _mended(store, root, under, tree, row) or under.page_of(card)
        if any(_within(path, place) for place in places):
            continue
        cards.append((row, path))

    def last_said(found) -> float:
        row = under.row("chat", found[1])
        return (row.last_activity or row.created_at or 0.0) if row is not None else 0.0

    # Its chats, the one talked in last first.
    chats = sorted(own.get("chat", ()), key=last_said, reverse=True)

    rows, more = [], []

    def some(found: list, word: str) -> list:
        if len(found) > MOST_LISTED:
            many = len(found) - MOST_LISTED
            more.append(f"{many} {KIND_WORDS[word][0 if many == 1 else 1]}")
        return found[:MOST_LISTED]

    rows += _run_rows(under, some(own.get("run", []), "run"))
    rows += _card_rows(some(cards, "card"))
    # A goal's `goal.md` is its goal, which has a line of its own above.
    goal_row = _goal_row(store, ident, rel) if called == "Task" else ""
    mds = [n for n in held["md"] if n not in as_page
           and not (goal_row and n == GOAL_DOC)]
    for name in mds:
        rows.append(_item_line(
            _object_row("md", doc_url(rel, name), _md_title(base / rel / name, name)
                        or name, stamp(_changed(base / rel / name), now), _kind_pill(".md")),
            rel, name, person))
    for name in held["files"]:
        rows.append(_file_line(_object_row("file", doc_url(rel, name), name,
                                           stamp(_changed(base / rel / name), now),
                                           _kind_pill(_file_word(name))),
                               rel, name, person))
    for name in held["folders"]:
        rows.append(_object_row("folder", doc_url(rel, name), name,
                                _holds(base / rel / name), _kind_pill("Folder")))
    here_many = (len(own.get("run", ())) + len(cards) + len(mds) + len(held["files"])
                 + len(held["folders"]))

    body = []
    # The Slack channels linked to it, one small line each (`_slack_section`).
    if called == "Task":
        body.append(_slack_section(person, ident))
    # A step of a goal says what the step is before anything else: that is
    # what the Goals page's Open was pressed to see.
    step_of = _goal_step_panel(store, under, ident)
    if step_of:
        body.append(step_of)
    if chats:
        body.append(_section("Chats", len(chats),
                             "".join(_chat_rows(under, chats[:MOST_LISTED], drew, person)),
                             cls="ochats"))
    # A goal is one thing on its task's page, opened like a page: its streams
    # and what they wait on the person for are on a page of its own
    # (`goal_page`). Petar, 27 September 2026 (fr_b083c37a634d): "the
    # homepage should remain with list of things (chats, subtasks, etc), and
    # just like HTML can be clicked the goal can be clicked to go to the
    # specialized page."
    if goal_row:
        body.append(_section("Goal", 1, goal_row, cls="opages one ogoalrow", cut=False))
    if built:
        def page_dots(row: str, one: dict) -> str:
            inside = one["rel"][len(rel) + 1:] if one["rel"].startswith(rel + "/") else ""
            # A step's own page is called what the step is (`built_pages`), so renaming it
            # renames the step; any other page is called what its `<title>` says.
            names = ("step" if called == "Subtask" and inside.lower() == "index.html"
                     else "page" if inside.lower().endswith(".html") else "")
            return (_item_line(row, rel, inside, person, one["title"], rename=names)
                    if inside else row)

        body.append(_section("Page" if len(built) == 1 else "Pages", len(built),
                             _page_rows(built, page_dots),
                             cls="opages one" if len(built) == 1 else "opages", cut=False))
    # What it asks the person, drawn the one way every question is drawn
    # (`decision.js`): its decision, answered right here and on the Decisions
    # page alike (`rouh/decisions.py`). Only on Rouh's own page for its owner;
    # anywhere else - another account, the page at its own address with nobody
    # signed in - it is the box the page always had, which asks nothing of
    # anybody there.
    decided = _decision_of(person, "goal" if step_of else "task",
                           rel if step_of else ident) if (asking is not None or step_of) else None
    if decided is not None:
        body.append(_section("Decision", 1, _decision_mount(decided), cls="odecide", cut=False))
    elif asking is not None:
        # A task that is done draws it only when it still asks something,
        # which is then optional.
        panel = _waiting_panel(rel, shown, asking, state, into=_answered_in(ident))
        if panel:
            body.append(_section("Decision", 1, panel, cls="odecide", cut=False))
    # What its subtasks' own chats sent up to it (`rouh/subtasknotes.py`):
    # the decisions that belong to the whole task, each opening the chat it
    # was made in.
    sent_up = _sent_up(ident)
    if sent_up:
        body.append(_section("From its subtasks", len(sent_up),
                             "".join(_sent_up_row(one, now) for one in sent_up[:MOST_LISTED]),
                             cls="onotes"))
    if subs:
        body.append(_subtask_section(subs, whole=shelved, rel=rel, person=person))
    # What the person uploaded to it with Upload in its header, newest last,
    # just above what is directly in it (`_task_files_section`).
    body.append(_task_files_section(ident))
    if rows:
        body.append(_section(
            f"Directly in this {called.lower()}", here_many, "".join(rows), cls="oown",
            cut=False,
            tail=(f'<p class="omore">and {" and ".join(more)} more</p>' if more else "")))
    # What the sources of its pages, and its subtasks' pages, really say: Sources belongs to the
    # task and is reached from here, not from the navigation (`_sources_section`). Last of all,
    # below everything else on the page: Petar, 17 October 2026 (fr_68562c1ca11f), "on a task
    # page, sources should be at the very bottom. it is the last thing I would ever look at".
    checked = _sources_section(person, root, rel)
    if checked:
        body.append(checked)
    # And the Google documents its notes link to, each with What changed, last of all
    # (`rouh/task_docs.py`).
    from . import task_docs

    linked_docs = task_docs.section(person, root, rel)
    if linked_docs:
        body.append(linked_docs)
    # And the replies it drafted for the person to send from their own mail, until they are sent
    # (`rouh/to_send.py`).
    from . import to_send

    sends = to_send.section(person, root, rel)
    if sends:
        body.append(sends)
    # And what its notes' Where this stands still says is open, each with Done
    # (`rouh/open_items.py`).
    from . import open_items

    still = open_items.section(person, root, rel)
    if still:
        body.append(still)
    # And, when its notes say something is due soon, the free time left before that date
    # (`rouh/task_time.py`).
    from . import task_time

    soon = task_time.section(person, root, rel)
    if soon:
        body.append(soon)
    # And last of everything, its archived subtasks, closed until pressed (`_archive_section`).
    if subs:
        body.append(_archive_section(subs, whole=shelved, rel=rel, person=person))

    back = ""
    if over is not None and called == "Subtask":
        # The way up, one level, as a folder has: its task, or the subtask
        # it is in.
        up = (str(over["number"]) if over.get("number") is not None
              else _step_number(over))
        words = f"{_called(tree, over)} {up}".strip() + " · " + (
            over.get("title") or over.get("slug") or over.get("folder") or "")
        back = (f'<p class="oback"><a href="{html.escape(_own_page(over), quote=True)}">'
                f'<span aria-hidden="true">←</span> {html.escape(words)}</a></p>')
    # Its icon, as a Notion page has one, which a press changes (`rouh/taskicons.py`).
    titled = here["title"] or here["slug"] or rel
    face = (icon_mark(taskicons.shown(tree.icons.get(ident, ""), titled), ident, titled, "hicon")
            if ident else "")
    head = (f'<header class="ohead">{back}<div class="otitle">'
            f'<h1 class="oname-big"><span class="otname">{number}{face}'
            f'<span id="tkName">{html.escape(here["title"] or here["slug"] or rel)}</span>'
            f'</span>{status}{ARCHIVED_PILL if shelved else ""}{_for_pill(made_for)}</h1>'
            f'{_was_line(store, ident, _changed_on(when, now))}'
            f'{_task_dots(called, shelved, bool(here.get("pinned")), bool(ident), made_for)}</div>'
            f'</header>')
    return head + ("".join(body) or
                   '<p class="none">Nothing in this yet. A subtask, a page, a .md, a chat, '
                   'a run or a card filed here appears on this page.</p>')



def _doc_path(tree, root, rel: str, doc: str):
    """The object at ``rel``, and the file or folder ``doc`` names inside it,
    once every rule `build_doc` gives has passed: (object, name, parts, path),
    or None when nothing is filed at ``rel``. Refused or Missing otherwise."""
    from . import workspace

    here = _object_at(tree, root, rel)
    if here is None or not rel:
        return None
    name = str(doc or "")
    parts = name.split("/")
    if (not name or "\\" in name or "\x00" in name
            or any(not part or part.startswith(".") for part in parts)
            or name.lower().endswith((".html", ".htm"))):
        raise pages.Refused(f"{name or 'Nothing'} is not a working file of this folder.")
    base = (Path(str(root)) / rel).resolve()
    if instructions_file(name):
        # A link to a task's AGENTS.md opens its CLAUDE.md where that is all
        # the folder has yet (`rouh/instructions.py`), and the other way round.
        name = instructions.in_folder(Path(str(root)) / rel).name
        parts = [name]
    try:
        path = workspace.resolve(root, f"{rel}/{name}")
    except workspace.Refused as exc:
        raise pages.Refused(str(exc)) from None
    if base not in path.parents or not path.exists():
        raise pages.Missing(f"There is no {name} in {rel}.")
    return here, name, parts, path


def doc_download(root, rel: str, doc: str, raw: str = "") -> Path:
    """The working file ``doc`` of the object at ``rel``, to be saved to the
    reader's computer as it is on disk: its Download link (`build_doc`).

    Exactly the files `build_doc` would open to read, by the same rules, and
    never a folder: what a signed-in person could already open here is what
    they may take away, and nothing more. Share cannot reach it, for the same
    reason it cannot reach the reading view (`docview`).
    """
    if any(token in (raw or "").lower() for token in pages.ENCODED):
        raise pages.Refused("The address holds an encoded slash, backslash, percent sign, "
                            "dot or NUL, which is never followed.")
    rel = "/".join(part for part in str(rel or "").split("/") if part)
    found = _doc_path(_Tree(_ready(root)), root, rel, doc)
    if found is None:
        raise pages.Missing(f"There is nothing filed at {rel} in the workspace.")
    path = found[3]
    if not path.is_file():
        raise pages.Refused(f"{found[1]} is a folder, and only a file is downloaded.")
    return path


def build_doc(store: objects.ObjectStore, root, rel: str, doc: str,
              person=None) -> tuple[str, str] | None:
    """One working file of one object's folder, to read, and what it is called.

    None when nothing is filed at ``rel``. ``doc`` is a path inside that
    folder and nothing else - its `AGENTS.md`, a step's research notes at
    `58-01.should-we-adopt-it/58-01.research-notes.md`, that step's
    `source-code` - with no part empty or starting with a dot, no backslash
    or NUL, no name secrets are kept under, and where it resolves to, links
    followed, still inside that folder, so no name can reach a file anywhere
    else. `docview` says why these are read here and never served.

    Three shapes, because a step's working files are three things. Notes, a
    `.md`, are drawn as Markdown. A folder is listed, each line opening what
    it names. Anything else is shown as the text it is, or said not to be
    text. A page is never read here: it opens as the page it is.
    """
    tree = _Tree(store)
    found = _doc_path(tree, root, rel, doc)
    if found is None:
        return None
    here, name, parts, path = found
    low = parts[-1].lower()
    if path.is_dir():
        word, pill = "folder", "Folder"
        drawn, title = _folder_listing(root, rel, name, path, person), parts[-1]
    elif low.endswith(".md"):
        word, pill = "md", ".md"
        text = _read_head(path, DOC_LONGEST)
        if low == docview.STEP_FILE:
            drawn, title = docview.step_html(text)
        else:
            # Called by its file name (`_md_title`), so its own first heading
            # is the first thing in it and is drawn as such, not taken away
            # to be its name.
            drawn, title = docview.markdown_html(text), parts[-1]
        drawn = drawn or "<p class=dnote>This file is empty.</p>"
    else:
        word, pill = "file", _file_word(parts[-1])
        drawn, title = _plain_file(path), parts[-1]
    title = title or parts[-1]
    called = _called(tree, here)
    shown = (str(here["number"]) if here.get("number") is not None
             else _step_number(here))
    back = (f"{called} {shown}" if shown else called) + " \u00b7 " + (
        here["title"] or here["slug"] or rel)
    links = [(f'<a href="{html.escape(_own_page(here), quote=True)}">'
              f'<span aria-hidden="true">\u2190</span> {html.escape(back)}</a>')]
    # And the folder this is in, when that is a folder listed here and not
    # the object or one of its subtasks, so a file opened out of `source-code`
    # has the way back to `source-code` on it.
    inside = "/".join(parts[:-1])
    if inside and not objecttree.is_a_task(parts[-2], inside_a_task=True):
        links.append(f'<a href="{html.escape(doc_url(rel, inside), quote=True)}">'
                     f'<span aria-hidden="true">\u2190</span> {html.escape(parts[-2])}</a>')
    # A folder is a list like the one on the page it is in, and drawn as one:
    # an article's links are a paragraph's, coloured as links, and every line
    # here is one.
    drawn = (f'<section class="oset olist">{drawn}</section>' if word == "folder" else
             f'<article class="odoc{" ofile" if word == "file" else ""}">{drawn}</article>')
    body = (f'<header class="ohead"><p class="oback">{"".join(links)}</p>'
            f'<div class="eyebrow">{"<span class=lc>.md</span>" if word == "md" else word}'
            f' &middot; {html.escape(rel + "/" + name)}</div>'
            f'<h1 class="oname-big"><span>{html.escape(title)}</span>'
            f'{_kind_pill(pill, word)}</h1>'
            f'{_download(rel, name, person) if word == "file" else ""}</header>{drawn}')
    return body, (title if title == parts[-1] else f"{title} - {parts[-1]}")




# --------------------------------------------------------------------------
# The markup
# --------------------------------------------------------------------------


def title_at(store: objects.ObjectStore, rel: str, root=None) -> str:
    """What the object filed at this path is called.

    The page's own `<title>`, which is what the browser tab, a bookmark and
    Rouh's breadcrumb all read. It was the folder's last part until 22
    September 2026, so a page whose heading said "Pricing" was titled
    "19.pricing"; the object has a name and this is it. No number in front of
    it: the number is its own badge everywhere it is drawn, and the breadcrumb
    leaves this level out when it would only repeat the one above it. A
    subtask with no row is called what its task's meta calls it
    (`_step_on_disk`).
    """
    here = _object_at(_Tree(store), root, rel)
    return (here["title"] or here["slug"] or "") if here is not None else ""


#: A file read on the canvas - notes, a folder, a plain file - says how tall
#: it is, and Rouh makes the frame that tall and scrolls it with the canvas,
#: so the file runs down the page like any other page and the frame never
#: scrolls on its own (`tasksFlow` in app.js). Petar, 5 October 2026, on his
#: iPad, where a task's .md would not scroll at all (fr_0ce726bbcc5b): "Md
#: content should just go down the page and scroll should be the natural page
#: content". The body is what is measured, not the document: the document is
#: never shorter than the frame, so it would only ever grow.
FLOW_SCRIPT = (
    "<script>/* Put in by Rouh. How tall this page is, for the frame. */\n"
    "(function(){var p;try{p=window.parent}catch(e){return}if(!p||p===window)return;"
    "var last=-1;function say(){var b=document.body;if(!b)return;"
    "var h=Math.ceil(b.getBoundingClientRect().height);if(h===last)return;last=h;"
    "try{p.postMessage({type:'rouh-page-height',height:h},'*')}catch(e){}}"
    "if(window.ResizeObserver)new ResizeObserver(say).observe(document.body);"
    "addEventListener('load',say);addEventListener('resize',say);say()})();</script>")


def _shell(body: str, title: str, at: str | None, data: dict | None = None,
           named: str = "ROUH_TASKS", script: str = SCRIPT) -> bytes:
    """The page, with its style and its script put in rather than linked.

    Three pages come through here and each brings its own script: the task
    browser (`taskbrowser.js`, reading `ROUH_TASKS`), a project's own page
    (`projectpage.js`, reading `ROUH_PROJECT`), and a task's or a step's
    (`taskpage.js`, reading `ROUH_TASK`), whose one control is its Start chat
    button. A note being read brings none.
    """
    said = ""
    if data is not None:
        # `</script` inside a string would close this one; `<!--` would open a
        # comment. Both are escaped, which JSON leaves meaning what it meant.
        blob = (json.dumps(data, ensure_ascii=False)
                .replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026"))
        # A task's or a step's page may carry its decision (`_decision_mount`), drawn
        # by the one component that draws every decision (`decision.js`).
        decides = f"<script>{_asset(DECISION_SCRIPT)}</script>\n" if script == TASK_SCRIPT else ""
        # The icon in front of a task's title, and its picker (`taskicon.js`).
        icons = (f"<script>{_asset(ICON_SCRIPT)}</script>\n"
                 if script in (SCRIPT, TASK_SCRIPT) else "")
        labels = f"<script>{_asset(LABELS_SCRIPT)}</script>\n" if script == SCRIPT else ""
        said = (f"<script>window.{named} = {blob};</script>\n"
                f"<script>{_asset(MENU_SCRIPT)}</script>\n"
                f"{icons}{labels}{decides}"
                f"<script>{_asset(script)}</script>\n")
    sheets = _asset(MENU_SHEET) + _asset(LABELS_SHEET) + _asset(SHEET) + (
        _asset(DECISION_SHEET) if script == TASK_SCRIPT and data is not None else "")
    return pages.with_storage((
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{html.escape(title)}</title>"
        f"<style>{sheets}</style></head>"
        f"<body>{body}{said}</body></html>"
    ).encode(), at)


def _frame(data: dict, framed: bool) -> str:
    """The page around the board: the search and the buttons."""
    tasks = len(data["tasks"])
    # No heading, no "How this page works" and no Expand all over the search
    # box: Petar had them taken off on 1 October 2026 (fr_0bfea6b4153f), with
    # the line under it that counted the tasks in each column, so the list
    # starts higher on a phone. What the page is is said by the Rouh bar it
    # sits under, and by its own title.
    read = "" if framed else (
        '<p class="readonly">This page is open at its own address, away from '
        "Rouh, so it is read only: nothing on it can be moved or renamed from "
        "here. Open the task browser in Rouh to change anything.</p>")
    # The search, and on its line what is not a filter: Save view, Manage
    # projects and [?], which shows the keyboard's line under it, hidden until
    # pressed. Petar, 22 October 2026 (fr_d2222b1e45af): "This button along
    # with manage projects and [?] for keyboard shortcuts should be on the line
    # of the search. This way filter will be only filter, and the line with
    # keyboard shortcuts will be hidden by default."
    tools = (
        '<button type="button" class="tool saveview" id="saveView" title="Open the task browser on '
        'this view from now on: the labels hidden with their eye and the filters pressed">'
        'Save view</button>'
        '<button type="button" class="tool manage" id="manageBtn" title="Rename, move between the '
        'columns, add or delete projects">Manage projects</button>' if framed else "") + (
        '<button type="button" class="tool keys" id="keysBtn" aria-expanded="false" '
        'aria-controls="keysLine" title="Keyboard shortcuts" aria-label="Keyboard shortcuts">?</button>')
    return f"""{read}<div class="search" id="search">
  <div class="searchline"><label class="field" for="q">{SEARCH_ICON}<input id="q" type="search" autocomplete="off"
  spellcheck="false" placeholder="Filter by task, step, title or project"><kbd>/</kbd></label>{tools}</div>
  <div class="status" id="keysLine" hidden><span class="hint"><kbd>/</kbd> search <kbd>esc</kbd> clear
  <kbd>&#8593;</kbd><kbd>&#8595;</kbd> move <kbd>&#8592;</kbd><kbd>&#8594;</kbd> column <kbd>space</kbd> expand
  <kbd>enter</kbd> open{'<span>&middot; drag a task onto a label to add it, onto the &times; of the one pressed to take it off</span>' if framed else ''}</span></div>
  <div class="bar" id="bar" role="toolbar" aria-label="Filters"></div>
</div>
<main>
  <div id="notice" class="notice" hidden></div>
  <div id="board" class="board"></div>
  <div id="empty" hidden>{"Nothing matches. Clear the search, or press Esc to see every project."
                          if tasks else "Nothing has been filed into this workspace yet."}</div>
</main>
<div id="menu" class="menu" role="menu" hidden></div>
<div id="toast" class="toast" role="status" aria-live="polite" hidden></div>"""


def _store() -> objects.ObjectStore:
    store = objects.shared_store(even_when_off=True)
    if store is None:
        raise pages.Refused("The object store is not open on this machine.")
    return store


def _ready(root) -> objects.ObjectStore:
    if not has_tree(root):
        raise pages.Refused(
            "There is no workspace on this machine that Rouh can draw: no "
            f"{objecttree.MAP_FILE} under {root or 'nowhere'}.")
    store = _store()
    objecttree.ensure_imported(root, store)
    # And the repairs, in the same breath, because this is the one place that
    # reads the whole tree and there is no longer a heading on the page for
    # what is wrong with it to show up under (`objecttree.tidy`). It writes
    # nothing when there is nothing wrong, which is every call after the
    # first.
    objecttree.tidy(root, store)
    return store


def index_page(root, at: str | None = None, names=(), person=None) -> bytes:
    """The whole page, ready to be framed on the canvas.

    `at` is the address Rouh is framing it at, and is None when the page was
    asked for at its own address. Only a framed page can save anything, so it
    is also what decides whether the buttons that write are drawn at all.
    `names` is what the signed-in person is called, and `person` who they are
    (`index_data`).
    """
    store = _ready(root)
    data = index_data(store, root, names, person)
    data["framed"] = at is not None
    return _shell(_frame(data, at is not None), "The workspace", at, data)


def task_page(root, rel: str, raw: str = "", at: str | None = None,
              doc: str = "", names=(), person=None) -> bytes:
    """One object's own page, drawn from the rows the same way the index is.

    The browser links a task with no page of its own here, and so does a thread
    that is a task being opened from the rail, which asks for
    ``/workspace/_task/<the task>/``.

    ``raw`` is the address as it arrived, still encoded, and is checked before
    anything is done with it: an encoded slash, backslash, percent sign, dot or
    NUL is never followed, so nothing here can be decoded twice into a path
    somewhere else. ``pages.check`` makes the same refusal for a file, and this
    is the one route under ``/workspace/`` that does not go through it.

    ``names`` is what the signed-in person is called, for the panel at the top
    of a waiting task that says what it waits on them for (`_waiting_panel`).
    ``person`` is who is signed in, whose steps set for a time a goal's
    own page reads (`goal_data`).
    """
    low = (raw or "").lower()
    if any(token in low for token in pages.ENCODED):
        raise pages.Refused(
            "The address holds an encoded slash, backslash, percent sign, dot or NUL, "
            "which is never followed."
        )
    store = _ready(root)
    rel = "/".join(part for part in str(rel or "").split("/") if part)
    if rel and root and not (Path(root) / rel).is_dir():
        # A folder that is not there any more, though a row may still name it:
        # a job renamed `68.untitled-task` to `68.bluf-proposal` on 28 September
        # 2026, and for seven minutes every press on task 68 drew an empty page
        # under its old name, or a 404 for its step, until a reload read the
        # disk again. The rows follow the disk first, so `moved_to` can say
        # where it went and the page is redirected there (`workspace_page`).
        from . import conversations

        try:
            conversations.reconcile(str(root))
        except Exception:
            log.exception("the rows could not be brought up to date for %s", rel)
        # A row that still names it after that is a subtask whose folder went
        # and whose row stayed: 75-02's folder was moved into task 62 on 30
        # September 2026 under a row of its own, and task 75 went on listing
        # 75-02 as "Nothing in it yet". Its page was this 404, with no name and
        # no three dots, so the one thing it was good for, deleting it, could
        # not be done. Petar (fr_bb3ff32f17b9): "when there is nothing in it,
        # I still have to have the title and the three dots and the delete
        # option". So it is drawn from its row like any other, empty.
        try:
            kept = store.by_folder("task", rel)
        except Exception:
            log.exception("could not look up a row for the missing folder %s", rel)
            kept = None
        if kept is None:
            raise pages.Missing(f"There is nothing filed at {rel} in the workspace.")
    if doc == GOAL_DOC and _is_goal_folder(root, rel):
        # A goal's own page: the goal whole, not its notes read.
        return goal_page(store, root, rel, at, person)
    if doc == _explainer_doc():
        # A step's explainer, drawn from the step (`step_explainer`).
        return step_explainer(store, root, rel, at)
    if doc == _yours_doc():
        # A step's How to do it page, the person's own (`step_yours`).
        return step_yours(store, root, rel, at)
    if doc:
        # One of its files, read, rather than the object itself.
        got = build_doc(store, root, rel, doc, person)
        if got is None:
            raise pages.Missing(f"There is nothing filed at {rel} in the workspace.")
        return _shell(got[0] + (FLOW_SCRIPT if at is not None else ""), got[1], at)
    body = build_task(store, root, rel, names, person)
    if body is None:
        raise pages.Missing(f"There is nothing filed at {rel} in the workspace.")
    title = title_at(store, rel, root) or rel.split("/")[-1] or "The workspace"
    said = project_data(store, root, rel, at is not None)
    if said is not None:
        return _shell(body, title, at, said, named="ROUH_PROJECT",
                      script=PROJECT_SCRIPT)
    task = talked_in(store, rel)
    if task is None:
        return _shell(body, title, at)
    # A task's page: its Start chat button, which is Rouh's to act on and so
    # is not drawn at the page's own address, where there is no Rouh around
    # it. `about` is what a screen reader hears the chat is about: a subtask's
    # page starts a chat of the subtask's own (`taskChat` in app.js, since 29
    # September 2026, fr_3113364c29fa), and only a folder inside a step that
    # is not a subtask itself is still talked about in its task.
    if (task.folder or "") != rel:
        try:
            own = store.by_folder("task", rel)
        except Exception:
            log.exception("could not look up the subtask at %s", rel)
            own = None
        if own is not None:
            task = own
    if (task.folder or "") == rel:
        from . import subtasknotes

        step = subtasknotes.step_number(task) if task.number is None else ""
        about = f"subtask {step}" if step else "this task"
    else:
        about = f"task {task.number}" if task.number is not None else "its task"
    said = {"task": task.id, "about": about, "framed": at is not None}
    return _shell(body, title, at, said, named="ROUH_TASK", script=TASK_SCRIPT)


def moved_to(rel: str) -> str | None:
    """Where a numbered task's folder is now, when `rel` names where it was.

    A new task is made in `unfiled/` and filed into a project a moment later,
    and the tidy that files it runs inside the very request that asks for its
    page (`_ready`). Goal 67 was made on 27 September 2026, its page was asked
    for at `unfiled/67.meetings-capture-in-unified-system`, and that request
    moved it to `private/misc/` before it looked, so the person who had just
    made it was shown "not found". The number is what does not change when the
    folder does (`addressing.inside`), so the same path under wherever the task
    is now is the page that was meant. None when nothing moved.
    """
    store = objects.shared_store(even_when_off=True)
    parts = [part for part in str(rel or "").split("/") if part]
    task_at = addressing._task_at(parts)
    if store is None or task_at < 0:
        return None
    row = addressing._by_number(store, parts[task_at])
    folder = str(getattr(row, "folder", "") or "")
    if not folder or folder == "/".join(parts[:task_at + 1]):
        return None
    return "/".join([folder] + parts[task_at + 1:])


def goal_page(store: objects.ObjectStore, root, rel: str, at: str | None,
              person=None) -> bytes:
    """A goal's own page: its streams side by side, and what each waits on the
    person for, with what has been prepared for it (`goalpage.js`).

    At its task's `goal.md` (`goals.PAGE`), so it is opened from the task's
    page as a page is, has an address of its own, and the breadcrumb and Back
    treat it as one thing inside the task. What the person wrote, which is
    that file, is on it too."""
    task = store.by_folder("task", rel)
    goal = goal_data(task, person) if task is not None else None
    if goal is None:
        raise pages.Missing(f"There is no goal at {rel}.")
    goal["framed"] = at is not None
    goal["task_href"] = _own_page({"folder": rel})
    # Petar, 27 September 2026 (fr_11a135ffd563): "I can read 4 times the same
    # thing. up top is the task name. and it also says the goal. and it also
    # gives me the navigation to the two places upwards." So in Rouh, whose
    # bar above says all of that, the page opens on what he wrote and when it
    # is due, and nothing else. Opened at its own address, with no bar above
    # it, the way back to the task is the one thing kept.
    back = ""
    if at is None:
        shown = f"Task {task.number} · " if task.number is not None else "Task · "
        back = (f'<p class="oback"><a href="{html.escape(goal["task_href"], quote=True)}">'
                f'<span aria-hidden="true">←</span> {html.escape(shown + task.title)}</a></p>')
    body = (f'<header class="ohead gphead">{back}<div class="gp-top">'
            f'<div class="gp-about" id="goalAbout"></div>'
            f'<div class="gm-due" id="goalDue"></div></div></header>'
            f'<div class="gp" id="goalPage"><p class="none">Drawing the goal&hellip;</p></div>')
    return _shell(body, "Goal", at, goal, named="ROUH_GOAL", script=GOAL_SCRIPT)


#: How each part of a step stands, as the goal's page and the explainer say it
#: (`goals.part_states`, `PART` in goalpage.js), and the mark beside it.
PART_WORDS = {"todo": "To do", "doing": "Doing", "done": "Done", "blocked": "Blocked: needs you",
              # The person's part of a step that asks nothing of them (`goals.part_states`).
              "nothing": "Nothing asked of you"}
PART_MARK = {"todo": "", "doing": "", "done": "\u2713", "blocked": "!"}


def _explainer_doc() -> str:
    from . import goals

    return goals.EXPLAINER_DOC


def _yours_doc() -> str:
    from . import goals

    return goals.YOURS_DOC


def _part_mark(state: str) -> str:
    return (f'<span class="gp-mark m-{html.escape(state)}" aria-hidden="true">'
            f'{PART_MARK.get(state, "")}</span>')


def _where_html(where: str) -> str:
    """Where the person does a step: a link when it is an address, else its words."""
    if re.match(r"https?://\S+$", where or ""):
        return (f'<a href="{html.escape(where, quote=True)}" target="_blank" '
                f'rel="noopener noreferrer">{html.escape(where)}</a>')
    return html.escape(where or "")


def step_explainer(store: objects.ObjectStore, root, rel: str, at: str | None) -> bytes:
    """A step of a goal explained, as a page: what Rouh does in it and what it
    made, then what the person does, where, and the steps to take.

    Petar, 27 September 2026 (fr_e2dde690a576), on the goal's page: "A link to
    the results (html explainer page in this subtask. currently. i am getting
    md file, which I don't like.)" and "what is required of me to do, link to
    where I do it, steps described etc. that should be an html explainer page
    prepared for that task". So the goal's page links here from Rouh's part
    and from his, and the Markdown Rouh wrote is drawn inside it, never opened
    as a file. Drawn fresh each time, so it never disagrees with the step."""
    from . import goals, steps

    task = store.by_folder("task", rel)
    found = goals.of_step(task) if task is not None else None
    if found is None:
        raise pages.Missing(f"There is no step of a goal at {rel}.")
    v, s = found
    goal_href = doc_url(v["folder"], GOAL_DOC) if v["folder"] else ""
    esc = html.escape

    def state(words_of: str) -> str:
        return (f'{_part_mark(words_of)}<span class="gx-state s-{esc(words_of)}">'
                f'{esc(PART_WORDS.get(words_of, words_of))}</span>')

    def parts_list(parts: list, rouh: bool) -> str:
        if not parts:
            return ""
        lis = []
        for x in parts:
            st = x["rouh_state"] if rouh and x["rouh_state"] else x["your_state"]
            how = f'<span class="gx-part-how">{esc(x["how"])}</span>' if x["how"] else ""
            go = (f'<a class="gx-part-go" href="{esc(x["explainer"], quote=True)}">'
                  f'{"What it made" if rouh else "Open"}</a>' if x["explainer"] else "")
            lis.append(f'<li>{_part_mark(st)}<span class="gx-part-t">{esc(x["title"])}</span>'
                       f'<span class="gx-state s-{esc(st)}">{esc(PART_WORDS.get(st, st))}</span>'
                       f'{go}{how}</li>')
        return f'<ol class="gx-parts">{"".join(lis)}</ol>'

    rouh_parts = [x for x in s["parts"] if x["who"] in ("rouh", "together")]
    your_parts = [x for x in s["parts"] if x["who"] != "rouh"]
    body = []
    if s["rouh_state"] or rouh_parts:
        made = ""
        folder = goals._folder(task)
        if folder is not None and (folder / steps.STEP_FILE).is_file():
            try:
                drawn = docview.step_html(_read_head(folder / steps.STEP_FILE, DOC_LONGEST))[0]
            except (ValueError, TypeError):
                drawn = ""
            made = f'<div class="odoc gx-doc">{drawn}</div>' if drawn else ""
        others = [f for f in s["prepared"]["files"]
                  if f["name"] not in (steps.STEP_FILE, goals.EXPLAINER)]
        if others:
            made += ('<ul class="gx-files">' + "".join(
                f'<li><a href="{esc(f["href"], quote=True)}">'
                f'{"Open the page " if f["page"] else "Read "}{esc(f["name"])}</a></li>'
                for f in others) + "</ul>")
        if not made:
            made = ('<p class="gx-none">Nothing made yet. What Rouh finds or makes for this '
                    'step shows here.</p>' if s["rouh_state"] else "")
        # What Rouh gets ready for his part, when the step says (`goals.plan_problems`).
        how = (f'<p class="gx-p">{esc(s["prep"] or s["how"])}</p>'
               if (s["prep"] or s["how"]) and s["rouh_state"] else "")
        body.append(
            f'<section class="gx-sec" id="rouh"><h2 class="gx-h">What Rouh does'
            f'{state(s["rouh_state"]) if s["rouh_state"] else ""}</h2>{how}'
            f'{parts_list(rouh_parts, True)}'
            + (f'<h3 class="gx-sub">What Rouh made</h3>{made}' if made else "")
            + '</section>')
    you = [f'<p class="gx-p gx-need">{esc(s["your_words"])}</p>']
    if not s["your_state"]:
        # Nothing is asked of him in this step (`goals.part_states`).
        you = []
    if s.get("options") and s["your_state"] != "done":
        you.append('<ul class="gp-options" aria-label="The options">' + "".join(
            f"<li>{esc(o)}</li>" for o in s["options"]) + "</ul>")
    if (s["how"] and (s["prep"] or not s["rouh_state"])
            and s["how"] != s["your_words"]):
        you.append(f'<p class="gx-p">{esc(s["how"])}</p>')
    if s["where"]:
        you.append(f'<p class="gx-where"><strong>Where</strong> {_where_html(s["where"])}</p>')
    if your_parts:
        you.append(f'<h3 class="gx-sub">Steps to take</h3>{parts_list(your_parts, False)}')
    if s["outcome"] and s["your_state"] != "done":
        you.append(f'<p class="gx-when"><strong>Complete when</strong> {esc(s["outcome"])}</p>')
    if s["your_state"]:
        body.append(f'<section class="gx-sec gx-you" id="you"><h2 class="gx-h">What you do'
                    f'{state(s["your_state"])}</h2>{"".join(you)}</section>')
    if s["challenge"] or s["solution"]:
        hard = ""
        if s["challenge"]:
            hard += f'<dt class="h-hard">Hard part</dt><dd>{esc(s["challenge"])}</dd>'
        if s["solution"]:
            hard += f'<dt class="h-fix">What to do</dt><dd>{esc(s["solution"])}</dd>'
        body.append(f'<dl class="goal-hard gx-hard">{hard}</dl>')
    links = []
    if goal_href:
        links.append(f'<a href="{esc(goal_href, quote=True)}">The goal</a>')
    own = _own_page({"folder": rel})
    if own:
        links.append(f'<a href="{esc(own, quote=True)}">The step&rsquo;s own page</a>')
    body.append(f'<p class="gx-foot">{" &middot; ".join(links)}</p>')
    back = f'Goal &middot; {esc(v["title"])}'
    head = (f'<header class="ohead gphead"><p class="oback"><a href="{esc(goal_href, quote=True)}">'
            f'<span aria-hidden="true">&larr;</span> {back}</a></p>'
            f'<div class="eyebrow">step {esc(s["n"])} of the goal</div>'
            f'<h1 class="oname-big"><span>{esc(s["title"])}</span></h1></header>')
    return _shell(head + f'<div class="gx">{"".join(body)}</div>', s["title"], at)


def step_yours(store: objects.ObjectStore, root, rel: str, at: str | None) -> bytes:
    """A step of a goal as the person's own page: what they do, where, the
    steps to take, the hard part, a place to write and pick, and Mark as
    complete.

    Petar, 27 September 2026 (fr_6acc50075110), on the goal's page, whose
    Results and How to do it both opened Rouh's research: "How to do it,
    should be an entirely different HTML page that has instructions and
    inputs for me. that's where "Mark as complete" should be if I don't want
    to do anything." So the research stays on the explainer, linked from
    here, and this page is drawn from the step alone. What he writes and the
    option he picks are kept on the step (`goals.NOTE`, `goals.CHOICE`) and
    Rouh reads them with the plan. The buttons are drawn hidden and
    `taskpage.js` shows them and hands each press up, as on a step's own
    page (`_goal_step_panel`)."""
    from . import goals

    task = store.by_folder("task", rel)
    found = goals.of_step(task) if task is not None else None
    if found is None:
        raise pages.Missing(f"There is no step of a goal at {rel}.")
    v, s = found
    goal_href = doc_url(v["folder"], GOAL_DOC) if v["folder"] else ""
    esc = html.escape
    done = s["status"] == "done" and not s.get("hollow")
    body = []

    need = [f'<p class="gx-p gx-need">{esc(s["your_words"])}</p>']
    if s["where"]:
        need.append(f'<p class="gx-where"><strong>Where</strong> {_where_html(s["where"])}</p>')
    if s.get("your_steps"):
        need.append(_your_steps_html(s["your_steps"], done or at is None))
    your_parts = [x for x in s["parts"] if x["who"] != "rouh"]
    if your_parts:
        lis = []
        for x in your_parts:
            st = x["your_state"]
            go = (f'<a class="gx-part-go" href="{esc(x["yours_page"], quote=True)}">Open</a>'
                  if x.get("yours_page") else "")
            how = f'<span class="gx-part-how">{esc(x["how"])}</span>' if x["how"] else ""
            lis.append(f'<li>{_part_mark(st)}<span class="gx-part-t">{esc(x["title"])}</span>'
                       f'<span class="gx-state s-{esc(st)}">{esc(PART_WORDS.get(st, st))}</span>'
                       f'{go}{how}</li>')
        need.append(f'<h3 class="gx-sub">Steps to take</h3><ol class="gx-parts">{"".join(lis)}</ol>')
    if s["how"] and not s["rouh_state"] and s["how"] != s["your_words"]:
        need.append(f'<h3 class="gx-sub">How</h3><p class="gx-p">{esc(s["how"])}</p>')
    if s["outcome"] and not done:
        need.append(f'<p class="gx-when"><strong>Complete when</strong> {esc(s["outcome"])}</p>')
    if s["rouh_state"] and s["explainer"]:
        need.append(f'<p class="gx-when"><strong>Rouh&rsquo;s research</strong> '
                    f'<a href="{esc(s["explainer"], quote=True)}">Results</a></p>')
    # A step of Rouh's alone asks nothing of him, and says so rather than
    # drawing an empty To do (fr_5404edbbea30).
    mine = s["your_state"] or "nothing"
    body.append(f'<section class="gx-sec gx-you" id="you"><h2 class="gx-h">What you do'
                f'{_part_mark(mine)}<span class="gx-state s-{esc(mine)}">'
                f'{esc(PART_WORDS.get(mine, mine))}</span></h2>'
                f'{"".join(need)}</section>')
    if s["challenge"] or s["solution"]:
        hard = ""
        if s["challenge"]:
            hard += f'<dt class="h-hard">Hard part</dt><dd>{esc(s["challenge"])}</dd>'
        if s["solution"]:
            hard += f'<dt class="h-fix">What to do</dt><dd>{esc(s["solution"])}</dd>'
        body.append(f'<dl class="goal-hard gx-hard">{hard}</dl>')

    # What he writes and picks, and the one button that closes the step.
    inputs = []
    if s.get("options"):
        picks = "".join(
            f'<label class="gy-pick"><input type="radio" name="ogsChoice" '
            f'value="{esc(o, quote=True)}"{" checked" if o == s.get("choice") else ""}'
            f'{" disabled" if done else ""}> <span>{esc(o)}</span></label>'
            for o in s["options"])
        # Other, and what he wants in his own words. Petar, 28 September 2026
        # (fr_ffe5cf02cd16), on step 67-01, whose options were three
        # transcription engines and whose answer was Recall.ai and Soniox: "in
        # this case I want something else. So I have to have "OTHER" option so
        # we can keep going". His words go up as the choice itself
        # (`goals.CHOICE`), so a choice that is none of the options is one.
        own = s.get("choice") or ""
        other = bool(own) and own not in s["options"]
        off = " disabled" if done else ""
        picks += (f'<label class="gy-pick"><input type="radio" name="ogsChoice" value="" '
                  f'id="ogsOtherPick"{" checked" if other else ""}{off}> <span>Other</span></label>'
                  f'<div class="gy-other" id="ogsOtherBox"{"" if other else " hidden"}>'
                  f'<textarea id="ogsOther" rows="2" maxlength="400" aria-label="What you want '
                  f'instead"{off} placeholder="What you want instead, in your own words">'
                  f'{esc(own) if other else ""}</textarea></div>')
        inputs.append(f'<fieldset class="gy-picks"><legend>Your choice</legend>{picks}</fieldset>')
    inputs.append(
        '<label class="gy-field" for="ogsNote"><span>Your notes</span>'
        f'<textarea id="ogsNote" rows="4" maxlength="{goals.MAX_NOTE}"'
        f'{" disabled" if done else ""} placeholder="What you found, decided or did, or why '
        f'you are leaving it. Rouh reads this with the plan.">{esc(s.get("note") or "")}'
        '</textarea></label>')
    if done:
        acts = ('<button type="button" class="ogs-btn" data-goal-act="undone">Reopen</button>')
    elif not s["your_state"]:
        # Nothing of his to complete: Rouh completes it when it has done it.
        acts = ('<button type="button" class="ogs-btn" data-goal-act="note">Save</button>')
    else:
        acts = ('<button type="button" class="ogs-btn primary" data-goal-act="done">'
                'Mark as complete</button>'
                '<button type="button" class="ogs-btn" data-goal-act="note">Save</button>')
    body.append(f'<section class="gx-sec gy-mine" aria-label="Your inputs">'
                f'<h2 class="gx-h">Your inputs</h2>{"".join(inputs)}'
                f'<div class="ogs-acts" id="ogsActs" hidden>{acts}</div>'
                + ('' if at is not None else
                   '<p class="gx-none">Open this page in Rouh to save or complete it.</p>')
                + '</section>')
    links = []
    if goal_href:
        links.append(f'<a href="{esc(goal_href, quote=True)}">The goal</a>')
    own = _own_page({"folder": rel})
    if own:
        links.append(f'<a href="{esc(own, quote=True)}">The step&rsquo;s own page</a>')
    body.append(f'<p class="gx-foot">{" &middot; ".join(links)}</p>')
    back = f'Goal &middot; {esc(v["title"])}'
    head = (f'<header class="ohead gphead"><p class="oback"><a href="{esc(goal_href, quote=True)}">'
            f'<span aria-hidden="true">&larr;</span> {back}</a></p>'
            f'<div class="eyebrow">step {esc(s["n"])} of the goal &middot; how to do it</div>'
            f'<h1 class="oname-big"><span>{esc(s["title"])}</span></h1></header>')
    data = {"framed": at is not None, "task": task.id, "about": s["title"]}
    # Named for what it is, so the canvas's breadcrumb says it under the step.
    return _shell(head + f'<div class="gx">{"".join(body)}</div>', "How to do it", at, data,
                  named="ROUH_TASK", script=TASK_SCRIPT)


def _step_words_html(text: str) -> str:
    """One of the person's steps: its words, with `code` drawn as code and a
    web address as a link that opens beside Rouh."""
    out = []
    for i, bit in enumerate(re.split(r"`([^`]+)`", text or "")):
        if i % 2:
            out.append(f"<code>{html.escape(bit)}</code>")
            continue
        at = 0
        for m in re.finditer(r"https?://[^\s<>\"')]+[^\s<>\"').,;:!?]", bit):
            out.append(html.escape(bit[at:m.start()]))
            out.append(f'<a href="{html.escape(m.group(0), quote=True)}" target="_blank" '
                       f'rel="noopener noreferrer">{html.escape(m.group(0))}</a>')
            at = m.end()
        out.append(html.escape(bit[at:]))
    return "".join(out)


def _your_steps_html(items: list, shut: bool) -> str:
    """The person's part as steps to tick, in order, with how many are ticked
    (`goals.YOUR_STEPS`). Petar, 28 September 2026 (fr_84b6c5266a52): "step
    by step instructions on all the points. and ability to check "complete"
    on each step." A tick is kept the moment it is pressed (`taskpage.js`);
    `shut` draws them unpressable, on a step already complete or opened at
    its own address, where there is no Rouh to keep them."""
    esc = html.escape
    ticked = sum(1 for x in items if x["done"])
    lis = []
    for i, x in enumerate(items):
        lis.append(
            f'<li class="gy-step{" is-done" if x["done"] else ""}"><label class="gy-step-l">'
            f'<input type="checkbox" data-step="{i}" data-text="{esc(x["text"], quote=True)}"'
            f'{" checked" if x["done"] else ""}{" disabled" if shut else ""}>'
            f'<span class="gy-step-n">{i + 1}.</span>'
            f'<span class="gy-step-t">{_step_words_html(x["text"])}</span></label></li>')
    pct = round(100 * ticked / len(items)) if items else 0
    return (f'<div class="gy-steps-w" id="ogsSteps"><div class="gy-steps-head">'
            f'<h3 class="gx-sub">Step by step</h3>'
            f'<span class="gy-count" id="ogsCount" aria-live="polite">{ticked} of '
            f'{len(items)} done</span></div>'
            f'<div class="gy-bar" aria-hidden="true"><span id="ogsBar" style="width:{pct}%">'
            f'</span></div><ol class="gy-steps">{"".join(lis)}</ol></div>')


def goal_data(task, person=None) -> dict | None:
    """A goal whole, for its own page to draw (`goalpage.js`), or None for a
    task that is not a goal. It is the same `goals.view` Rouh is told and
    every open page is handed as the goal changes, so none of them disagree.
    """
    from . import goals, reminders

    folder = goals._folder(task)
    if folder is None or not goals.is_goal(goals._meta(folder)):
        return None
    try:
        by_id = ({r.id: r for r in reminders.rows(person, include_done=False)}
                 if person is not None else {})
        v = goals.view(task, reminders_by_id=by_id)
        if person is not None:
            from . import questcheck

            v = questcheck.for_goal(person, v)
    except Exception:
        log.exception("goal %s could not be read", task.id)
        return None
    v["chat_href"] = addressing.url_for("chat", v["chat"]) if v["chat"] else ""
    return v


def project_data(store: objects.ObjectStore, root, rel: str,
                 framed: bool) -> dict | None:
    """What a project's page hands to its own script, or None for a task.

    Everything the panels open with, so that pressing Edit or Instructions
    shows what is really saved rather than an empty box that would wipe it.
    """
    row = store.by_folder("project", rel)
    if row is None:
        return None
    return {"id": row.id, "name": row.title, "description": row.description or "",
            "instructions": instructions_of(root, rel),
            "folder": rel, "framed": bool(framed),
            "files": _project_files(row.id),
            "files_at": f"/attachments/{files_key(row.id)}/"}


# The panel and row markup of a task's pages, and what the page writes back,
# are modules of their own. They read what they need from this one, so they are
# imported here, at the bottom, once everything above is defined, and every name
# in them stays reachable as `objectindex.<name>`, as it was before they moved.
from .objectindex_panels import (  # noqa: E402, F401
    ARCHIVED_PILL, DOWNLOAD_ICON, PIN_SVG, SLACK_MARK, UPLOAD_SVG, WHOSE_ITEMS, _CHEVRON, _CROSS,
    _GOAL_STATUS, _HANDING_OVER, _PDF_ITEMS, _RUN_ASKING, _RUN_GOING, _SEND_ARROW, _answer_form,
    _answer_goes, _answered_in, _answered_panel, _asking, _asking_panel, _chat_line, _chat_named,
    _decision_mount, _decision_of, _decision_top, _dismiss, _dismissed_line, _dots_line,
    _dots_menu, _download, _file_line, _file_word, _folder_listing, _for_pill, _goal_row,
    _goal_step_panel, _is_goal_folder, _item_acts, _item_line, _job_said, _menu_item, _pin_button,
    _plain_file, _said_when, _sent_up, _sent_up_row, _silo_chips, _slack_section, _sources_section,
    _archive_section, _subtask_dots, _subtask_section, _task_dots, _task_files_section, _upload_button,
    _waiting_panel, _whose_items, slack_line)
from .objectindex_write import (  # noqa: E402, F401
    DESCRIPTION_MAX, FILES_TOLD, NAME_MAX, _colour, _coloured, _delete_project, _describe,
    _described, _drop_file, _drop_task_file, _files_block, _named, _remove_folder,
    SAVED_VIEW, attach_to_project, attach_to_task, change, files_block, icon_change, icon_upload,
    save_view, saved_view)
