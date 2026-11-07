"""The five things Rouh is made of, and the one table that joins them.

**All five are live.** Step one of this model was the storage layer with
nothing reading it. Step two made every kind of running work one type, so
`runs.py` writes and reads `run` for real - a background worker, a run of the
one program, and a sub-agent inside either - and the task list, `check_tasks`,
`one_runs`, `what_is_running` and the orb are all answered from it. Step three
moved the conversations, so a chat is a row of `chat` with its turns in
`message`, a piece of numbered work is a row of `task`, and one `owns` link
joins them, which is what replaced a thread being matched to a task by its
name (`conversations.py`). Step four made every output one type, so
`artifacts.py` writes and reads `artifact`: a card on the screen, a numbered
step in the workspace and a built `index.html` page are one kind of row with
one kind of history. Step five turned the last of them on: `owning.py` is where
the rest of Rouh reaches ownership, and `starting.py` is the one call that
makes a run.

**The database is the source of truth**: the worktrees, the logs, the branches,
the task folders, the step folders and the built pages on disk are a supportive
structure written out from it, never read back in as the truth, and where the
two disagree the row wins and what is on disk is an inbound change to
reconcile.

Three of the five are written from somewhere else on this machine, each with
exactly one writer, and `owning.sync` is where that happens: a project is a
chat folder, a chat is a conversation (`conversations.py`), and a numbered task
is a folder in the person's workspace, taken in as a row and written back out
from it. Every `create_*` here takes an `id` for that reason - the object
already has a name everything else calls it by, and minting a second one would
give us two identities to join on, which is the problem this model exists to be
rid of.

The whole of this module is behind `config.object_model_enabled`: ask
`enabled()` first. There is no second implementation behind that flag any more;
off means these tables are not read or written at all. The one exception is the
conversations, which have had nowhere else to live since step three and so open
the store whatever the flag says (`shared_store(even_when_off=True)`).

## The five objects are five objects

A project, a task, a chat, a run and an artifact each have their own table,
their own create, read, update and delete, and no foreign key to one another.
That is the whole point of the design: the thing that used to be "a card lives
inside a chat" or "a step lives inside a task" became a rule nobody could bend
when the person wanted the same card under two tasks, or a run that outlived
the conversation that started it. Here, nothing owns anything by virtue of
where it is stored.

The one exception is `run.parent_run_id`, because a sub-agent inside a run is
not a separate run that happens to be related: it is that run's own child, and
the parent's id is a column rather than a row in the link table so a run can be
walked down without a join.

## Everything else is a link

One table, `link`, holds every relationship there is:

    owns   the one relationship that is ownership
    made   run -> artifact, many to many: this run drew this
    from   run -> chat, many to one: this conversation started it
    about  anything -> task, many to many: this is about that

`owns` is special and is the invariant this module exists to protect.

**An object has at most one owner, and the database says so.** Not Python: a
partial unique index, `link_one_owner`, on `link(dst_type, dst_id)` where the
relation is `owns`. A second owner for the same object cannot be written by
this module, by a later module, by a migration or by somebody at a `psql`
prompt. Having no owner at all is legal and is what everything created here
starts as.

**Ownership points down this ranking, and two types nest inside themselves:**

    project > task > chat > run > artifact

A project may own a project, a task, a chat, a run or an artifact. A task may
own a task, a chat, a run or an artifact, and **never a project**. A chat may
own a run or an artifact, and never a chat and never a task. A run may own an
artifact, and never a chat, a task or another run: run nesting is
`parent_run_id`, not a link. An artifact owns nothing.

Those three sentences are the hierarchy the person settled on 21 September
2026, and the thing to notice is what is not in them. **There is no group
object.** Work and Personal are ordinary top-level projects, and anything at the
top with no owner is a group, because being at the top is the whole of what a
group is. How deep the nesting may go is a decision for the screen; the schema
has no opinion about depth.

**A cycle is refused rather than impossible.** While nothing could own its own
rank, every `owns` edge went from a lower number to a higher one, a walk down
strictly decreased, and no walk could return to where it began. Two types that
nest end that: three projects can be written into a ring where each owns the
next and none is under anything. So `attach` walks up from the proposed owner
before it writes an edge between two objects of the same type, in the same
transaction, and refuses the edge if the child is already above it. Every other
edge still cannot make a cycle and is not walked. The `CHECK` constraint on
`link` says the rest of the rule again in SQL - down the ranking, or a project
to a project or a task to a task, and never a thing to itself - for the sake of
whoever comes at this table with a write that did not go through Python.

## The files own the words, and this holds a copy

`content_file` is the one thing here that is not the truth. Every AGENTS.md,
every note and every built page is a file on disk, in git, written and edited
with Read, Edit, Grep and Glob, and none of that text is stored here as the
truth: what is stored is the full text and a sha256 of each file, rebuilt from
disk by `objecttree.py`, and PostgreSQL's full-text vector of that text, which
the database keeps in step with it by itself. It buys one search over
everything and makes a file that has drifted from its row something this
database can see. Delete every row of it and the rebuild puts them all back.

The other three relations are references and never ownership. A run's `from`
link to a chat says which conversation asked for it; it does not make the chat
the run's owner, and deleting the chat leaves the run exactly where it was.

## Deleting an owner deletes what it owns

Deleting a project, a task, a chat or a run deletes everything under it, all
the way down: `delete` walks the `owns` edges from the thing being deleted and
takes the whole subtree with it, in one transaction. Deleting the project Work
deletes its tasks, their chats, those chats' runs and every artifact any of
them owns.

**The walk is here and nowhere above it.** For a few hours on 22 September 2026
`conversations.delete_project` had a walk of its own, because a project taking
its chats with it was wanted before this module could do it. That is gone:
one cascade, in one transaction, for every type, rather than each caller that
wants one writing the loop again and getting a different amount of it right.

That is the person's rule, asked for on 22 September 2026 in these words:
*"We should be able to delete items of all types - chats, runs, tasks,
projects. Delete cascades if there are relationships."* It reverses what this
module did until then, which was to sweep the `owns` rows and leave the
children behind as orphans. The reason it reverses is the one the person gave:
a thing that owns another thing is where that thing lives, and tidying away a
project that still leaves forty chats loose in the database is not a delete,
it is a mess with a nicer list.

What that means in practice, and what it does not:

- **Ownership is followed. A reference never is.** `made`, `from` and `about`
  are references and hold nothing in place: deleting a chat leaves a run that
  came `from` it exactly where it was, and deleting a run leaves the artifacts
  it `made` alone unless it also owned them. Only `owns` cascades, because
  only `owns` is where something lives.
- **A run's sub-agents go with it.** `parent_run_id` is the one ownership that
  is a column rather than an edge, and it is walked with the rest: a sub-agent
  inside a run is part of that run, so deleting the run deletes it. This was
  `ON DELETE SET NULL` while an orphan was the rule; now the walk reaches
  sub-runs before the database ever has to, and the `SET NULL` is what keeps a
  row that some other path deleted from becoming an error.
- **Nothing is left pointing at nothing.** Every link row that touched
  anything in the subtree goes with it, at either end, and `sweep_links`
  answers the question "is there a link to something that is not here" for the
  whole table at once.
- **A cycle cannot spin it.** The walk carries the set of what it has already
  seen, so a ring written into the file before `attach` refused rings is a
  stop rather than a hang, and `LIMIT_CASCADE` is the second stop.

Two things still cascade in SQL, because they cannot exist alone and never
could:

- `message` belongs to its chat. A message with no chat is not a message.
- `artifact_version` belongs to its artifact. A version with no artifact is a
  body of text nobody can name.

Both are `ON DELETE CASCADE` in the schema, and the database carries them out
(`rouh/migrations/0002_database_rules.py`): Django's own models cannot say
`ON DELETE` to PostgreSQL, so the foreign keys are made there by hand and the
model fields say `DO_NOTHING` (`rouh/models/objects.py`).

`artifact_version.made_by_run` stays `ON DELETE SET NULL`: who wrote a body is
a note and never a hold, so a version whose run is deleted keeps its body and
forgets the name. It may never block a delete.

**What is on disk is the caller's to remove.** This module deletes rows. The
step folders, the built pages, the task folders in the workspace and the
worktree a run worked in are written out from these rows and are swept by
`owning.remove`, which is the one delete path the rest of Rouh calls and
which asks this one to do the rows.

## What is deliberately not here yet

**Tenancy.** Every row Rouh keeps on somebody's behalf carries an `org_id` or
a `user_id` and is queried scoped, and AGENTS.md is not negotiable about it.
These tables have neither. That was easy to defend while they were the shape
and nothing else; now that they hold real runs and real chats it is a debt, and
the columns and the scoped queries are a job of their own rather than a line to
add in passing. Nothing here may be given to a second organisation until they
land.

**A sweep.** There is none, and there is not to be one. Nothing in this
module or anywhere above it deletes an object because time passed: an orphan is
legal and is the ordinary state of most things here, so a sweep that deleted
them would be deleting the default. A chat goes when a person deletes it and at
no other moment, which is the person's own decision of 22 September 2026:
"Remove deleting chats at 90 days. No automatic removal." The clock that used
to archive a quiet chat after a month and delete it after three is gone with
it, query and all.

## Where it is kept

PostgreSQL, through Django, like everything else Rouh keeps, since 23
September 2026. The tables are the models in `rouh/models/objects.py` and keep
the names they had; the schema is Django's migrations, and nothing here creates
or alters a table any more. Until that day this was one SQLite file shared with
the rest of Rouh, in WAL mode, with a store that grew its own tables with
`ALTER TABLE` when it found a column missing and counted its one-time repairs in
the file's `user_version`. Those repairs had all run on the server's file by
the time its rows were copied across (it said `user_version = 2`), so none of
them is carried over: running them again would take off every pin the person
has put on a task since.
"""
from __future__ import annotations

import contextlib
import logging
import re
import threading
import time
import uuid
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from functools import reduce
from operator import and_, or_

from django.db import DatabaseError, connection, transaction
from django.db.models import Case, Count, F, IntegerField, Max, Q, Value, When
from django.db.models.functions import Greatest, Length, Substr

from .config import config
from .models import objects as tables
# The vocabulary lives beside the columns it constrains, in the models, so the
# CHECK constraints the migration made and the checks this module makes are
# one list and cannot drift apart. It is named here again so that every caller
# that has always said `objects.KINDS` or `objects.OWNS` still can.
from .models.objects import (AGENTS, ARTIFACT_KINDS, CHAT_STATES, KINDS, NESTS, OWNS,
                             POLICIES, RANK, RELS, RUN_KINDS, RUN_STATES, STATE_STATUS,
                             STATUS_STATE,
                             TASK_STATES, TASK_STATUSES, WORD_BREAKS)

log = logging.getLogger("rouh.objects")


# `RANK` is the ranking ownership points down, `NESTS` the two types that nest
# inside themselves, `KINDS` what may appear at either end of a link, `OWNS`
# and `RELS` the four relations, and the rest the words each column may hold:
# all of them are in `rouh/models/objects.py`, with what they mean. The
# hierarchy they describe - Work and Personal as ordinary top-level projects,
# no group object, a project owning a project and a task a task - is the one
# the person settled on 21 September 2026.

#: What each reference joins, checked before it is written. `about` is the wide
#: one on purpose: anything may be about a task, including another task.
REF_ENDS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "made": (("run",), ("artifact",)),
    "from": (("run",), ("chat",)),
    "about": (KINDS, ("task",)),
}

#: What **stopping** is, per type, and it is the whole of what the red dot on
#: the three tabs of the rail means: the thing is not working any more and it
#: is the person's turn. Finished, ended badly, and stopped to ask a question
#: are all of them, because all three are something to go and look at; only
#: work actually going on is left out.
#:
#: A task's `open` and a run's `running` are the two that are not here, and
#: that is the point. The dot used to be on while a job ran, which is the one
#: moment there is nothing for anybody to do about it.
STOPPED: dict[str, tuple[str, ...]] = {
    "task": ("waiting", "done"),
    "run": ("waiting", "conflict", "done", "failed"),
}


def news_since() -> float:
    """The moment from which something finishing is news: when the person's
    account was made. 0.0 when there is no account yet.

    **Never looked at is not the same as not seen.** A mark of 0 says the
    person has not opened a thing, and that is true of everything on the day
    they arrive: the workspace they were given, with every page already
    written in it and every task already waiting or done. Read as "finished
    after they last looked", each of those was news, so a person who had
    signed in for the first time and pressed nothing had a red dot on the
    Tasks tab counting fifty-one tasks - "a red dot before I have done
    anything" (a new user, relayed by Petar on 24 September 2026). What had
    happened before they had an account is how things were when they came,
    not something that happened to them, so a dot only ever counts what
    finished after this moment as well as after the last look.

    The rows here are one person's (see Tenancy in this module's notes), so
    that person is this install's first account. When the rows carry a
    `user_id` this becomes that user's own account and nothing else changes.
    """
    from .models.accounts import User

    try:
        first = (User.objects.filter(is_active=True).order_by("date_joined")
                 .values_list("date_joined", flat=True).first())
    except DatabaseError:
        log.exception("could not read when the first account was made")
        return 0.0
    return first.timestamp() if first else 0.0


#: What a cascade may not take: a set of (type, id) pairs, or None for the
#: ordinary case of nothing being spared. `owning.KEEP` is the only one there
#: is, and it holds General.
Keep = set[tuple[str, str]] | frozenset[tuple[str, str]] | None

#: The most objects one delete may take with it. Not a policy about how much a
#: person may delete: a stop, for a walk that has found something wrong. The
#: whole of this database on the server is a few hundred objects, so a cascade
#: of ten thousand is a ring the walk cannot see or a bug, and either way the
#: right thing is to stop and say so in the log rather than to spin.
LIMIT_CASCADE = 10000


def may_own(owner_type: str, child_type: str) -> bool:
    """Whether that pair of types is an ownership the model allows."""
    if RANK[owner_type] < RANK[child_type]:
        return True
    return owner_type == child_type and owner_type in NESTS


def enabled() -> bool:
    """Whether anything may read or write this store.

    Off by default, and nothing asks yet: no route, no tool and no page. The
    first caller of this module asks this first, and does what it did before
    when the answer is no.
    """
    return bool(config.object_model_enabled)


class Refused(ValueError):
    """The store would not do it, and the message says why.

    A ValueError because that is what the rest of Rouh raises when what it
    was handed is not a thing it can store - see `google_store.check_client_id`.
    """


class UnknownKind(Refused):
    """A type that is not one of project, task, chat, run, artifact."""


class NotDownward(Refused):
    """An ownership that does not point down the ranking.

    Which is to say a cycle waiting to happen, and the reason there is no
    cycle check anywhere in this module.
    """


class _Unset:
    """Not given: leave the column as it is, or do not filter on it."""

    __slots__ = ()

    def __repr__(self) -> str:                               # pragma: no cover
        return "UNSET"


#: The difference between "set this column to NULL" and "do not touch this
#: column", which `None` alone cannot say.
UNSET = _Unset()


@dataclass(frozen=True)
class Project:
    """A body of work. Owns whatever is filed under it, including projects.

    Owned by a project or by nothing at all. A project with no owner is what
    the person calls a group: Work and Personal are two of them, and there is
    no group object anywhere, because being at the top is the whole of what a
    group is.
    """

    id: str
    number: int | None
    slug: str
    title: str
    status: str
    folder: str
    pinned: bool
    created_at: float
    updated_at: float | None
    #: What belongs in here, in the person's own words. Written by them and
    #: read by the model that files a new task (`rouh/filing.py`).
    description: str = ""
    #: The colour the person picked, or empty for the one its place gives it.
    color: str = ""


@dataclass(frozen=True)
class Task:
    """Something that has to be done, with the number people say out loud."""

    id: str
    number: int | None
    slug: str
    title: str
    state: str
    folder: str
    pinned: bool
    created_at: float
    updated_at: float | None
    #: When it last stopped - went to waiting or done - as Rouh saw it happen
    #: (`update_task`). None for a task that has never stopped in front of
    #: Rouh, which includes one that was already waiting or done when it was
    #: taken in from the workspace.
    closed_at: float | None
    #: When the person last looked at it: after it stopped, or after its
    #: artifact was made ready to display. 0 is never, which is what a task
    #: that has done neither reads as too.
    seen_at: float = 0.0
    #: When it was archived, or None while it is live (`rouh/archiving.py`).
    archived_at: float | None = None
    #: What it is, where it stands and what is open, in 50 to 90 words, kept
    #: here and nowhere else (`rouh/taskrecord.py`), and the paragraph
    #: `_tasks.md` is generated with (`rouh/tasklist.py`).
    summary: str = ""
    #: How far along it is in the workspace's five words (`TASK_STATUSES`),
    #: of which `state` is the three-word summary. Kept here and nowhere else.
    status: str = "not-started"
    #: The picture in front of its title: one emoji, or the file name of a picture uploaded
    #: for it, or "" for none picked yet (`rouh/taskicons.py`).
    icon: str = ""


@dataclass(frozen=True)
class Chat:
    """A conversation. Its messages are its own and go when it goes.

    Two clocks, and they are two on purpose: `last_spoke` is when anything was
    last said here, and `last_activity` is when the person last used it - a
    turn, or editing the chat: a title, a project, a pin - and is what the list
    is ordered by. Opening a chat to read it moves neither. Neither expires
    anything.
    """

    id: str
    title: str | None
    state: str
    pinned: bool
    unread: bool
    last_spoke: float
    last_activity: float
    created_at: float


@dataclass(frozen=True)
class Run:
    """An agent doing something, once. `parent_run_id` is a sub-agent's parent.

    Every kind of running work is one of these since `runs.py`: a background
    worker, a run of the one program, and a sub-agent inside either of those,
    which is a run with its parent's id on it.
    """

    id: str
    parent_run_id: str | None
    title: str
    brief: str
    agent: str
    workspace: str
    policy: str
    state: str
    phase: str
    detail: str
    archived: bool
    pinned: bool
    question: str | None
    branch: str | None
    worktree: str | None
    exit_code: int | None
    cost_usd: float | None
    started_at: float
    updated_at: float | None
    ended_at: float | None
    #: When the person last looked at it after it stopped, or archived it.
    seen_at: float = 0.0
    #: What it was for, in one plain sentence, written from its brief as it
    #: starts and shown once it has finished well (`rouh/runsummary.py`).
    summary: str = ""
    #: "mutation", "everyday", or "" when nothing has said yet (`runs.kind_of`).
    kind: str = ""


@dataclass(frozen=True)
class Artifact:
    """Something a person looks at: a card, a page, a document, a diff, a file, a picture."""

    id: str
    kind: str
    title: str
    path: str | None
    mime: str | None
    head_version: int
    pinned: bool
    created_at: float


@dataclass(frozen=True)
class Message:
    """One turn in a chat. Cascades with the chat, because it is part of it."""

    id: str
    chat_id: str
    seq: int
    role: str
    body: str


@dataclass(frozen=True)
class ArtifactVersion:
    """One version of an artifact. Cascades with the artifact, for the same reason."""

    artifact_id: str
    version: int
    body: str | None
    made_by_run: str | None


@dataclass(frozen=True)
class Link:
    """One row of the link table: one relationship between two objects."""

    id: str
    rel: str
    src_type: str
    src_id: str
    dst_type: str
    dst_id: str
    created_at: float


def _new_id(kind: str) -> str:
    """An id that says what it is, the way `memory.new_chat` makes one."""
    return f"{kind}-{uuid.uuid4().hex[:12]}"


def _one_of(value: str, allowed: tuple[str, ...], what: str) -> str:
    if value not in allowed:
        raise Refused(f"{what} is one of {', '.join(allowed)}, and not {value!r}")
    return value


def _kind(value: str, what: str = "an object type") -> str:
    if value not in RANK:
        raise UnknownKind(f"{what} is one of {', '.join(KINDS)}, and not {value!r}")
    return value


def _text(value):
    """A piece of text PostgreSQL will store, and anything else as it is.

    PostgreSQL refuses a NUL character anywhere in a text column, and SQLite
    never minded one, so a title or a body that has always been storable -
    words read out of a file that turned out to be half binary, a line off a
    terminal - would stop being storable on the day the data moved. One
    character is given up rather than the whole write: the NUL becomes the
    replacement character, which says on the screen that something was there.
    """
    if isinstance(value, str) and "\x00" in value:
        return value.replace("\x00", "\ufffd")
    return value


def _project(row) -> Project:
    return Project(id=row["id"], number=row["number"], slug=row["slug"],
                   title=row["title"], status=row["status"], folder=row["folder"],
                   pinned=bool(row["pinned"]),
                   created_at=row["created_at"], updated_at=row["updated_at"],
                   description=row["description"] or "",
                   color=row.get("color") or "")


#: A task's columns but its meta, which every ordinary read of a task leaves out: it is
#: read on its own (`task_meta`, `task_metas`), and the list of tasks is read far more often
#: than any task's steps and arrows.
_TASK_COLUMNS = tuple(f.attname for f in tables.Task._meta.concrete_fields if f.name != "meta")


def _vals(rows):
    """`.values()`, without a task's meta."""
    return rows.values(*_TASK_COLUMNS) if rows.model is tables.Task else rows.values()


def number_said(parts: Sequence[int]) -> str:
    """A task's or a subtask's number as it is written down: `62`, `62-09`, `62-09-03`."""
    parts = [int(p) for p in parts]
    return "-".join([str(parts[0])] + [f"{p:02d}" for p in parts[1:]]) if parts else ""


def _task(row) -> Task:
    return Task(id=row["id"], number=row["number"], slug=row["slug"], title=row["title"],
                state=row["state"], folder=row["folder"], pinned=bool(row["pinned"]),
                created_at=row["created_at"], updated_at=row["updated_at"],
                closed_at=row["closed_at"], seen_at=row["seen_at"] or 0.0,
                archived_at=row.get("archived_at"), summary=row.get("summary") or "",
                status=row.get("status") or STATE_STATUS.get(row["state"], "not-started"),
                icon=row.get("icon") or "")


def _chat(row) -> Chat:
    return Chat(id=row["id"], title=row["title"], state=row["state"],
                pinned=bool(row["pinned"]), unread=bool(row["unread"]),
                last_spoke=row["last_spoke"], last_activity=row["last_activity"],
                created_at=row["created_at"])


def _run(row) -> Run:
    return Run(id=row["id"], parent_run_id=row["parent_run_id"], title=row["title"],
               brief=row["brief"], agent=row["agent"], workspace=row["workspace"],
               policy=row["policy"], state=row["state"], phase=row["phase"],
               detail=row["detail"], archived=bool(row["archived"]),
               pinned=bool(row["pinned"]), question=row["question"],
               branch=row["branch"], worktree=row["worktree"], exit_code=row["exit_code"],
               cost_usd=row["cost_usd"], started_at=row["started_at"],
               updated_at=row["updated_at"], ended_at=row["ended_at"],
               seen_at=row["seen_at"] or 0.0, summary=row.get("summary") or "",
               kind=row.get("kind") or "")


def _artifact(row) -> Artifact:
    return Artifact(id=row["id"], kind=row["kind"], title=row["title"], path=row["path"],
                    mime=row["mime"], head_version=row["head_version"],
                    pinned=bool(row["pinned"]), created_at=row["created_at"])


def _message(row) -> Message:
    return Message(id=row["id"], chat_id=row["chat_id"], seq=row["seq"],
                   role=row["role"], body=row["body"])


def _version(row) -> ArtifactVersion:
    return ArtifactVersion(artifact_id=row["artifact_id"], version=row["version"],
                           body=row["body"], made_by_run=row["made_by_run"])


def _link(row) -> Link:
    return Link(id=row["id"], rel=row["rel"], src_type=row["src_type"],
                src_id=row["src_id"], dst_type=row["dst_type"], dst_id=row["dst_id"],
                created_at=row["created_at"])


#: How a row of each table becomes the object it stands for.
_OF: dict[str, Callable] = {
    "project": _project, "task": _task, "chat": _chat,
    "run": _run, "artifact": _artifact,
}

#: The model behind each of the five, and behind the two children and the link.
_TABLE: dict[str, type] = {
    "project": tables.Project, "task": tables.Task, "chat": tables.Chat,
    "run": tables.Run, "artifact": tables.Artifact,
}

#: The columns of a version row, under the names `_version` reads. The model
#: calls the run that wrote it `made_by_run_id`, because it is a foreign key to
#: a run; the column and every caller call it `made_by_run`.
_VERSION_COLUMNS = ("artifact_id", "version", "body", "made_by_run_id")

#: The columns of the content index a caller is ever handed. `search` is the
#: database's own vector of the body and is nobody's business but the query's.
_CONTENT_COLUMNS = ("object_id", "path", "sha256", "bytes", "modified", "body", "indexed_at")


def _version_of(values: dict) -> ArtifactVersion:
    return ArtifactVersion(artifact_id=values["artifact_id"], version=values["version"],
                           body=values["body"], made_by_run=values["made_by_run_id"])


def _at(*values) -> float | None:
    """When something was last worked on: the first of these that is set.

    Every one of the five has a different column for it - a chat was last
    spoken in, a run was last heard from, an artifact was made - and a search
    result has one date on every row, so this is where the five become one.
    """
    for value in values:
        if value is not None:
            return float(value)
    return None


#: What a search result needs off a row, per type. The name, the date the row
#: is sorted and drawn by, the pin, and whichever of `folder` and `path` says
#: where the thing is. `find` fills the rest in.
_SEARCH_ROW: dict[str, Callable] = {
    "project": lambda r: {"title": r["title"], "number": r["number"],
                          "state": r["status"], "folder": r["folder"] or "",
                          "pinned": bool(r["pinned"]),
                          "at": _at(r["updated_at"], r["created_at"])},
    "task": lambda r: {"title": r["title"], "number": r["number"],
                       "state": r["state"], "folder": r["folder"] or "",
                       "archived": r.get("archived_at") is not None,
                       "pinned": bool(r["pinned"]),
                       "at": _at(r["updated_at"], r["created_at"])},
    "chat": lambda r: {"title": r["title"] or "", "state": r["state"],
                       "pinned": bool(r["pinned"]),
                       "at": _at(r["last_spoke"], r["created_at"])},
    "run": lambda r: {"title": r["title"], "state": r["state"],
                      "archived": bool(r["archived"]),
                      "pinned": bool(r["pinned"]),
                      "at": _at(r["updated_at"], r["ended_at"], r["started_at"])},
    "artifact": lambda r: {"title": r["title"], "kind": r["kind"],
                           "path": r["path"] or "", "pinned": bool(r["pinned"]),
                           "at": _at(r["created_at"])},
}


#: Artifacts the search box never lists. A `diff` is the "What it changed" every
#: run keeps (`owning.record_diff`): the same title on every one of them, a body
#: that is a list of file paths, and nothing it can be drawn as. So a search for
#: "what", for a file's name or for a task's number turned up a page of rows
#: that all said "What it changed" and opened to nothing. Petar, 30 September
#: 2026 (fr_7d5e5a358d70): "They are useless if I click on them, there is no
#: content. If there is nothing valuable, they should be removed". The run they
#: belong to is a result in its own right, and its screen is where what it
#: changed is read.
UNSEARCHED: tuple[str, ...] = ("diff",)


def _every(words: Sequence[str], *columns: str) -> Q:
    """Every word somewhere in one of these columns, whatever its case.

    The search box's question, asked of the names and the short texts. It was
    SQLite's LIKE until 23 September 2026, which ignored case for the English
    alphabet only; PostgreSQL's ignores it for every alphabet, so a Cyrillic
    title is found whichever way it was typed, which is the one way the answer
    is wider than it was. The words are matched as they are, never as a
    pattern: `%` and `_` in a word are the characters themselves.
    """
    per = [reduce(and_, [Q(**{f"{column}__icontains": word}) for word in words])
           for column in columns]
    return reduce(or_, per)


def _rows(sql: str, params: Sequence = ()) -> list[dict]:
    """A raw query's rows, as dictionaries keyed by column name."""
    with connection.cursor() as cur:
        cur.execute(sql, list(params))
        names = [column[0] for column in cur.description]
        return [dict(zip(names, row)) for row in cur.fetchall()]


def _limit(limit) -> int | None:
    """A LIMIT as SQLite read one: nothing, or a negative number, is no limit."""
    if limit is None:
        return None
    limit = int(limit)
    return None if limit < 0 else limit


def _cut(queryset, limit):
    """A queryset with a LIMIT on it, or without one when there is none."""
    top = _limit(limit)
    return queryset if top is None else queryset[:top]


#: One word of a search, as the content index cuts words: a run of letters and
#: digits. Python's `[^\W_]` is the same class as the index's `[:alnum:]`.
_WORD = re.compile(r"[^\W_]+")


def indexable(words: Sequence[str]) -> bool:
    """Whether the full-text index can be asked for these words.

    Every one of them needs a letter or a digit in it: a word that is nothing
    but punctuation is not a word the index holds, and is looked for by
    reading the text instead.
    """
    return bool(words) and all(_WORD.search(w) for w in words)


#: How many words a snippet of a file holds, and what goes either side of one
#: that stops short of the start or the end of the file. Twelve and the spaced
#: ellipsis are what SQLite's `snippet()` was asked for until 23 September 2026.
SNIPPET_WORDS = 12
SNIPPET_ELLIPSIS = " \u2026 "

#: The order a list of projects or tasks comes back in: newest first, and
#: among rows made in the same instant - the whole workspace was taken in at
#: one moment - parent folders before the folders inside them. Every list here
#: ends on a column that cannot tie, the id at the last: SQLite broke a tie by
#: the order the rows were written in, which PostgreSQL has no notion of, and
#: a list that shuffled itself between two reads would move rows under a
#: person's finger. For projects and tasks the folder gives the order SQLite
#: gave, on every tie in the server's own rows.
_NEWEST_NESTED = ("-created_at", "folder", "id")

#: How much text either side of the first match is fetched to cut a snippet
#: from: enough for twelve words of any length anybody writes, and never the
#: whole of a file that may be a megabyte long.
_NEAR_BEFORE = 400
_NEAR_LENGTH = 1000


class ObjectStore:
    """The five objects, their two children, and the one table that joins them.

    PostgreSQL, through Django's ORM, with one lock around every write, which
    is the shape every other store in Rouh has. The lock is what keeps two
    writes in this process from racing over a read they both depend on - the
    next `seq` of a chat, the next version of an artifact, the walk up an
    ownership chain before an edge is written - and every write is one
    transaction, so a refusal half way through leaves nothing behind. Reads
    take no lock: every thread has a connection of its own, and PostgreSQL
    hands each of them what was committed.

    The foreign keys, their cascades and the ownership ranking are the
    database's, made by the migration (`rouh/migrations/0002_database_rules.py`).
    Nothing here makes or changes a table.
    """

    def __init__(self, db_path: str | None = None) -> None:
        # It used to be handed the SQLite file. There is one database now,
        # Django's, so the argument means nothing and is accepted so that a
        # caller written before the move still works.
        del db_path
        self._lock = threading.RLock()
        #: Whether words can be searched for through an index rather than by
        #: reading every file. It was a question until 23 September 2026 - a
        #: build of SQLite without FTS5 compiled in had no index - and it is
        #: always yes now: every PostgreSQL has full-text search, and the
        #: vector is a column of `content_file` the database keeps by itself.
        self.searchable = True
        self._fill_in_last_activity()

    def _fill_in_last_activity(self) -> None:
        """Give every chat that has no `last_activity` a sensible one.

        The newest thing said in it, falling back to when it was made - which
        is exactly what `last_spoke` already is, because `spoke` is the only
        thing that has ever moved it and `create_chat` starts it at the moment
        the chat was made. `max` of the two because an imported row is free to
        disagree, and a chat cannot sensibly have been used before it existed.

        Kept from the SQLite file, where it filled in the rows written before
        the column existed, because it is a repair and not a migration: it is
        idempotent, one statement that matches nothing once every row has a
        value, and it is what puts right a row that was copied across with a
        0 in it.
        """
        with self._writing():
            tables.Chat.objects.filter(last_activity__lte=0).update(
                last_activity=Greatest(F("last_spoke"), F("created_at")))

    def close(self) -> None:
        """Nothing to let go of any more.

        A SQLite file was held open by the store until 23 September 2026. The
        connections are Django's now, one per thread, and they belong to
        whoever else in that thread is using the database too, so this does
        not close them. It is kept because a check of somebody's own calls it.
        """

    # --- making things ------------------------------------------------------

    def create_owned(self, kind: str, title: str, *,
                     owner: tuple[str, str] | None = None,
                     id: str | None = None, number: int | None = None,
                     slug: str = "", status: str = "open", folder: str = "",
                     pinned: bool | None = None, created_at: float | None = None,
                     updated_at: float | None = None,
                     closed_at: float | None = None,
                     origin: dict | None = None) -> Project | Task:
        """A project or a task, and the link saying where it belongs, in one write.

        **Making an object and saying where it sits are one act, not two.** A
        create that committed and an `attach` that did not would leave an
        object at the top of the tree that nobody put it at, with a folder
        already written on disk under an owner the rows have never heard of -
        and the whole point of stage four is that the rows decide the
        hierarchy. So the row and its `owns` edge go in under one lock and one
        commit, and anything refused on the way - a number already taken, an
        upward link - leaves nothing at all behind.

        `owner` is `(type, id)` or None, and None is not a half-made state: a
        project at the top of the workspace is owned by nothing, and that is
        what being a group means.

        `create_project` and `create_task` are this with no owner, which is why
        there is one INSERT for each type here and not two.

        `pinned` left out means off, for a task as much as for a project.
        The pin is a mark the person sets with their own hand and never a
        reprieve from anything - nothing here is swept on a clock - and it is
        the same mark on all five, so that "keep this" is one thing on every
        row rather than a word that means nothing on two of them and everything
        on a third. A task was born pinned until 22 September 2026, which was
        harmless while nothing drew the mark and is not now that a pin lifts a
        row to the top of its list.

        A number or an id somebody else already has is refused by the database
        with Django's `IntegrityError`, which is what a caller catches to ask
        for the next number.

        A task is born knowing who made it (`rouh/task_origin.py`): `origin`
        when the caller says, else what the code making it says
        (`task_origin.making`), else the task it is a step of, else the
        person's own. Every task and step on this machine is made here, so
        none is made without it.
        """
        kept = bool(pinned)
        if kind == "project":
            row: Project | Task = Project(
                id=id or _new_id("project"), number=number, slug=slug, title=title,
                status=_one_of(status, TASK_STATES, "a project's status"),
                folder=folder, pinned=kept,
                created_at=created_at if created_at is not None else time.time(),
                updated_at=updated_at)
            made = tables.Project(
                id=row.id, number=row.number, slug=_text(row.slug), title=_text(row.title),
                status=row.status, folder=_text(row.folder), pinned=row.pinned,
                created_at=row.created_at, updated_at=row.updated_at)
        elif kind == "task":
            # Either word does: a state in three ("open") or a status in five
            # ("in-progress"). The row keeps both, the one the other's summary.
            if status in TASK_STATUSES:
                word = status
            else:
                word = "not-started" if status == "open" else STATE_STATUS.get(
                    _one_of(status, TASK_STATES, "a task's state"), "not-started")
            row = Task(
                id=id or _new_id("task"), number=number, slug=slug, title=title,
                state=STATUS_STATE[word], folder=folder,
                pinned=kept,
                created_at=created_at if created_at is not None else time.time(),
                updated_at=updated_at, closed_at=closed_at, seen_at=0.0, status=word)
            if origin is None:
                from . import task_origin

                above = (tables.Task.objects.filter(id=owner[1]).values_list("origin", flat=True)
                         .first() if owner is not None and owner[0] == "task" else None)
                origin = task_origin.at_birth(above, owner[1] if owner else "",
                                              owned_by_task=bool(owner and owner[0] == "task"))
            made = tables.Task(
                id=row.id, number=row.number, slug=_text(row.slug), title=_text(row.title),
                state=row.state, folder=_text(row.folder), pinned=row.pinned,
                created_at=row.created_at, updated_at=row.updated_at,
                closed_at=row.closed_at, seen_at=row.seen_at, status=row.status,
                origin=dict(origin or {}))
        else:
            raise UnknownKind(f"only a project and a task nest, so {kind!r} is not"
                              " made with an owner")
        if owner is not None:
            _kind(owner[0], "an owner type")
            if not may_own(owner[0], kind):
                raise NotDownward(
                    f"a {owner[0]} may not own a {kind}: ownership points down "
                    f"{' > '.join(KINDS)}, and only a project may own a project "
                    "and a task a task")
        with self._writing():
            made.save(force_insert=True)
            if owner is not None:
                self._must_be_there(owner[0], owner[1])
                tables.Link.objects.create(
                    id=_new_id("link"), rel=OWNS, src_type=owner[0], src_id=owner[1],
                    dst_type=kind, dst_id=row.id, created_at=time.time())
        if kind == "task":
            # Its icon, picked in the background within moments (`rouh/taskicons.py`).
            from . import taskicons

            taskicons.poke()
        return row

    def create_project(self, title: str, *, id: str | None = None,
                       number: int | None = None, slug: str = "",
                       status: str = "open", folder: str = "",
                       pinned: bool = False, created_at: float | None = None,
                       updated_at: float | None = None) -> Project:
        """A new project, owned by nothing, owning nothing.

        `id` is given rather than made for the reason `create_run` gives: when
        the thing already has a name the rest of this machine calls it by, the
        row keeps that name instead of minting a second one nothing could join
        on. A project taken in from the workspace is given the id written in
        its folder's `.object.json`, which is where that name is kept.
        """
        return self.create_owned("project", title, id=id, number=number, slug=slug,
                                 status=status, folder=folder, pinned=pinned,
                                 created_at=created_at, updated_at=updated_at)

    def create_task(self, title: str, *, id: str | None = None,
                    number: int | None = None, slug: str = "",
                    state: str = "open", folder: str = "", pinned: bool = False,
                    created_at: float | None = None,
                    updated_at: float | None = None,
                    closed_at: float | None = None,
                    origin: dict | None = None) -> Task:
        """A new task, owned by nothing and unpinned, like everything else.

        `id` is given rather than made when the task already has a name: a
        workspace task is `task-30` because 30 is what the person says out
        loud, and a second identity for it would be one more thing to drift.
        """
        return self.create_owned("task", title, id=id, number=number, slug=slug,
                                 status=state, folder=folder, pinned=pinned,
                                 created_at=created_at, updated_at=updated_at,
                                 closed_at=closed_at)

    def next_task_number(self) -> int:
        """The next task number nobody has used, out of the rows and nowhere else.

        The number is what the person says out loud - "open thirty" - and until
        21 September 2026 the next free one was found by reading the folder
        names in the workspace. It comes off `task.number` now, which is the
        column the unique index is on, so two creates in the same instant
        cannot both keep it: the second insert is refused and its caller asks
        again. A step has no number of this kind and is never counted here.
        """
        top = tables.Task.objects.aggregate(top=Max("number"))["top"]
        return int(top if top is not None else 0) + 1

    def create_chat(self, *, id: str | None = None, title: str | None = None,
                    state: str = "live", pinned: bool = False, unread: bool = False,
                    last_spoke: float | None = None,
                    last_activity: float | None = None,
                    created_at: float | None = None) -> Chat:
        """A new chat, owned by nothing. Both clocks start now unless told otherwise.

        `id` is given rather than made when the conversation already has one
        everything else calls it by: the id in the page's markup, the folder
        anything attached in it was stored under, the id a turn was written
        against. One conversation means one identity for it.

        `last_activity` follows `last_spoke` when it is not given, so a chat
        taken in from somewhere else - the move onto this model, a branch -
        lands in the list where its own history says it belongs rather than at
        the top of it.
        """
        now = time.time()
        spoke = last_spoke if last_spoke is not None else now
        row = Chat(id=id or _new_id("chat"), title=title,
                   state=_one_of(state, CHAT_STATES, "a chat's state"),
                   pinned=bool(pinned), unread=bool(unread),
                   last_spoke=spoke,
                   last_activity=last_activity if last_activity is not None else spoke,
                   created_at=created_at if created_at is not None else now)
        with self._writing():
            tables.Chat.objects.create(
                id=row.id, title=_text(row.title), state=row.state, pinned=row.pinned,
                unread=row.unread, last_spoke=row.last_spoke,
                last_activity=row.last_activity, created_at=row.created_at)
        return row

    def create_run(self, title: str, *, id: str | None = None, brief: str = "",
                   agent: str = "claude",
                   workspace: str = "", policy: str = "safe", state: str = "running",
                   phase: str = "", detail: str = "", archived: bool = False,
                   pinned: bool = False,
                   parent_run_id: str | None = None, question: str | None = None,
                   branch: str | None = None, worktree: str | None = None,
                   exit_code: int | None = None, cost_usd: float | None = None,
                   started_at: float | None = None, updated_at: float | None = None,
                   ended_at: float | None = None, kind: str = "") -> Run:
        """A new run, owned by nothing.

        `parent_run_id` is the only place one of the five objects points at
        another, and it says this run is a sub-agent inside that one. Raises
        `Refused` when the parent named is not a run that is here.

        `id` is given rather than made when the run already has a name
        everything else on this machine calls it by: a crewmate's id, the id
        the one program gave a run of its own, the id Claude Code gave a
        sub-agent. One kind of running work means one identity for it, so the
        register keeps the name the rest of the world uses instead of minting a
        second one nothing could join on. Left out, an id is made here.
        """
        now = time.time()
        row = Run(id=id or _new_id("run"), parent_run_id=parent_run_id, title=title,
                  brief=brief, agent=_one_of(agent, AGENTS, "an agent"),
                  workspace=workspace,
                  policy=_one_of(policy, POLICIES, "a policy"),
                  state=_one_of(state, RUN_STATES, "a run's state"),
                  phase=phase, detail=detail, archived=bool(archived),
                  pinned=bool(pinned), question=question, branch=branch, worktree=worktree,
                  exit_code=exit_code, cost_usd=cost_usd,
                  started_at=started_at if started_at is not None else now,
                  updated_at=updated_at if updated_at is not None else now,
                  ended_at=ended_at, kind=_one_of(kind, RUN_KINDS, "a run's kind"))
        with self._writing():
            if parent_run_id is not None and not self._there("run", parent_run_id):
                raise Refused(f"there is no run {parent_run_id!r} to be a sub-agent of")
            tables.Run.objects.create(
                id=row.id, parent_run_id=row.parent_run_id, title=_text(row.title),
                brief=_text(row.brief), agent=row.agent, workspace=_text(row.workspace),
                policy=row.policy, state=row.state, phase=_text(row.phase),
                detail=_text(row.detail), archived=row.archived, pinned=row.pinned,
                question=_text(row.question), branch=_text(row.branch),
                worktree=_text(row.worktree), exit_code=row.exit_code,
                cost_usd=row.cost_usd, started_at=row.started_at,
                updated_at=row.updated_at, ended_at=row.ended_at, kind=row.kind)
        return row

    def create_artifact(self, kind: str, title: str, *, id: str | None = None,
                        path: str | None = None,
                        mime: str | None = None, head_version: int = 1,
                        pinned: bool = False,
                        created_at: float | None = None) -> Artifact:
        """A new artifact, owned by nothing. Its bodies go in `add_version`.

        `id` is given rather than made when the thing already has a number the
        person says out loud. A card is `card-37` because 37 is what they ask
        for it by, and that number came from the screen history this model was
        migrated from, so a card kept its name across the move.
        """
        row = Artifact(id=id or _new_id("artifact"),
                       kind=_one_of(kind, ARTIFACT_KINDS, "an artifact's kind"),
                       title=title, path=path, mime=mime, head_version=head_version,
                       pinned=bool(pinned),
                       created_at=created_at if created_at is not None else time.time())
        with self._writing():
            tables.Artifact.objects.create(
                id=row.id, kind=row.kind, title=_text(row.title), path=_text(row.path),
                mime=_text(row.mime), head_version=row.head_version, pinned=row.pinned,
                created_at=row.created_at)
        return row

    # --- reading them back --------------------------------------------------

    def get_project(self, project_id: str) -> Project | None:
        row = self._one("project", project_id)
        return _project(row) if row else None

    def get_task(self, task_id: str) -> Task | None:
        row = self._one("task", task_id)
        return _task(row) if row else None

    def numbered_task(self, number: int) -> Task | None:
        """The task the person calls by this number, or None. The number is
        unique, so there is at most one."""
        row = _vals(_TABLE["task"].objects.filter(number=number)).first()
        return _task(row) if row else None

    def task_called(self, parts: Sequence[int]) -> Task | None:
        """The task or subtask a person means by 62, or by 62-16, or None.

        A task's number is its row's; a subtask has none, and is called by
        the start of its folder's name, `62-16.sharing-changes`, so that is
        where it is looked for, zeros in front of a part or not. Archived or
        not: a number is a name, and an archived task is still called by it.
        Two folders called the same are one of them, the live one first.
        """
        parts = [int(p) for p in parts]
        if not parts:
            return None
        if len(parts) == 1:
            found = self.numbered_task(parts[0])
            if found is not None:
                return found
        called = "-0*".join(str(p) for p in parts)
        where = Q(folder__regex=rf"(^|/)0*{called}(\.[^/]*)?$")
        if len(parts) > 1:
            # A step written the older way: its own number only, in its
            # task's folder, `11.winter-jacket/01-price-comparison`.
            over = "-0*".join(str(p) for p in parts[:-1])
            where |= Q(folder__regex=rf"(^|/)0*{over}\.[^/]*/0*{parts[-1]}([.-][^/]*)?$")
        row = _vals(_TABLE["task"].objects.filter(where)
                    .order_by(F("archived_at").asc(nulls_first=True),
                              F("updated_at").desc(nulls_last=True), "id")).first()
        if row is None:
            # A number nobody is called now may be one a move took away: the
            # task that was 92-08 is found under the number it has now
            # (`rouh/moving.py`, `numbers_before`).
            row = _vals(_TABLE["task"].objects
                        .filter(numbers_before__contains=[number_said(parts)])
                        .order_by(F("archived_at").asc(nulls_first=True),
                                  F("updated_at").desc(nulls_last=True), "id")).first()
        return _task(row) if row else None

    def get_chat(self, chat_id: str) -> Chat | None:
        row = self._one("chat", chat_id)
        return _chat(row) if row else None

    def tasks_owning_chats(self, chat_ids) -> dict[str, Task | None]:
        """For each of these chats that has an owner: the task that owns it, or None when its
        owner is not a task. A chat with no owner is not in the answer. Three queries at most."""
        ids = [c for c in dict.fromkeys(chat_ids or ()) if c]
        if not ids:
            return {}
        owners = dict((dst, (src_type, src_id)) for dst, src_type, src_id in
                      tables.Link.objects.filter(rel=OWNS, dst_type="chat", dst_id__in=ids)
                      .values_list("dst_id", "src_type", "src_id"))
        wanted = [src_id for src_type, src_id in owners.values() if src_type == "task"]
        tasks = ({row["id"]: _task(row) for row in _vals(tables.Task.objects.filter(id__in=wanted))}
                 if wanted else {})
        return {chat: (tasks.get(src_id) if src_type == "task" else None)
                for chat, (src_type, src_id) in owners.items()}

    def get_chats(self, chat_ids) -> dict[str, Chat]:
        """The chats that are there of these, by id, in one query."""
        ids = [c for c in dict.fromkeys(chat_ids or ()) if c]
        if not ids:
            return {}
        return {row["id"]: _chat(row) for row in _vals(tables.Chat.objects.filter(id__in=ids))}

    def get_run(self, run_id: str) -> Run | None:
        row = self._one("run", run_id)
        return _run(row) if row else None

    def get_artifact(self, artifact_id: str) -> Artifact | None:
        row = self._one("artifact", artifact_id)
        return _artifact(row) if row else None

    def by_folder(self, kind: str, folder: str) -> Project | Task | None:
        """The project or the task whose folder in the workspace is this one.

        The two that nest are the two that are folders, so they are the two
        that can be asked for by where they are; a chat, a run and an artifact
        have no folder and are never asked this. `rouh/addressing.py` is what
        asks, because a folder is what a task and a project are called in an
        address.
        """
        kind = _one_of(_kind(kind), NESTS, "a kind with a folder of its own")
        rel = str(folder or "").strip().strip("/")
        if not rel:
            return None
        row = _vals(_TABLE[kind].objects.filter(folder=rel)
                    .order_by("-created_at", "folder", "id")).first()
        if row is None:
            return None
        return (_project if kind == "project" else _task)(row)

    def list_projects(self, *, limit: int = 200) -> list[Project]:
        """Every project, newest first."""
        rows = _cut(tables.Project.objects.order_by(*_NEWEST_NESTED).values(), limit)
        return [_project(r) for r in rows]

    def descriptions(self) -> dict[str, str]:
        """What every project says it is for, by id, and only where it says one.

        One query rather than one per project: the task browser is redrawn
        whole every time anything in it changes, and the model that files a new
        task is given every project at once (`rouh/filing.py`). Both want the
        same small map. `description` is a column of `project` alone and not of
        the `object` view, so this is how anything reading the tree gets at it.
        """
        return dict(tables.Project.objects.exclude(description="")
                    .values_list("id", "description"))

    def colors(self) -> dict[str, str]:
        """The colour every project was given by hand, by id, and only where
        one was. The same one query as `descriptions`, for the same page."""
        return dict(tables.Project.objects.exclude(color="")
                    .values_list("id", "color"))

    def list_tasks(self, *, state: str | None = None, folder: str | None = None,
                   limit: int = 200) -> list[Task]:
        """Every task, newest first, narrowed by state or folder if asked."""
        rows = tables.Task.objects.all()
        if state is not None:
            rows = rows.filter(state=_one_of(state, TASK_STATES, "a task's state"))
        if folder is not None:
            rows = rows.filter(folder=folder)
        return [_task(r) for r in _cut(_vals(rows.order_by(*_NEWEST_NESTED)), limit)]

    def list_chats(self, *, state: str | None = None, limit: int = 200) -> list[Chat]:
        """Every chat, the one used most recently first.

        `last_activity` and not `last_spoke`: the list is ordered by the last
        time the person did something to a chat, which is speaking in it or
        editing it, and never by opening one to read it.
        """
        rows = tables.Chat.objects.all()
        if state is not None:
            rows = rows.filter(state=_one_of(state, CHAT_STATES, "a chat's state"))
        return [_chat(r) for r in
                _cut(rows.order_by("-last_activity", "id").values(), limit)]

    def list_runs(self, *, state: str | None = None, parent_run_id=UNSET,
                  limit: int = 200) -> list[Run]:
        """Every run, newest first.

        `parent_run_id` left out means every run whatever its parent; None means
        only the runs that are nobody's sub-agent; an id means that run's own
        sub-agents.
        """
        rows = tables.Run.objects.all()
        if state is not None:
            rows = rows.filter(state=_one_of(state, RUN_STATES, "a run's state"))
        if not isinstance(parent_run_id, _Unset):
            if parent_run_id is None:
                rows = rows.filter(parent_run_id__isnull=True)
            else:
                rows = rows.filter(parent_run_id=parent_run_id)
        return [_run(r) for r in _cut(rows.order_by("-started_at", "-id").values(), limit)]

    def newest_runs_where(self, keep, *, limit: int = 200) -> list[Run]:
        """The runs nobody started, among the newest `limit` of them, for which
        `keep(state, ended_at)` is true, newest first: the same answer as reading every one
        of those runs and keeping some, for the price of reading three columns of each and
        whole rows only of the few kept. The work tree and the conflict sweep ask several
        times a second, and read three hundred whole rows each time until 23 October 2026,
        on the loop every tab waits on."""
        newest = (tables.Run.objects.filter(parent_run_id__isnull=True)
                  .order_by("-started_at", "-id").values_list("id", "state", "ended_at"))
        wanted = [ident for ident, state, ended in _cut(newest, limit) if keep(state, ended)]
        if not wanted:
            return []
        return [_run(r) for r in tables.Run.objects.filter(id__in=wanted)
                .order_by("-started_at", "-id").values()]

    def list_artifacts(self, *, kind: str | None = None, limit: int = 200) -> list[Artifact]:
        """Every artifact, newest first, of one kind if asked."""
        rows = tables.Artifact.objects.all()
        if kind is not None:
            rows = rows.filter(kind=_one_of(kind, ARTIFACT_KINDS, "an artifact's kind"))
        return [_artifact(r) for r in
                _cut(rows.order_by("-created_at", "-id").values(), limit)]

    # --- changing them ------------------------------------------------------
    #
    # Every field left out is left alone, which is what UNSET is for: `None`
    # has to be able to mean "empty this column".

    def update_project(self, project_id: str, *, number=UNSET, slug=UNSET,
                       title=UNSET, status=UNSET, folder=UNSET, pinned=UNSET,
                       updated_at=UNSET, description=UNSET, color=UNSET) -> Project | None:
        """The project as it now stands, or None when there is no such project."""
        if not isinstance(status, _Unset):
            _one_of(status, TASK_STATES, "a project's status")
        self._set("project", project_id, {
            "number": number, "slug": slug, "title": title, "status": status,
            "folder": folder, "pinned": _as_flag(pinned), "updated_at": updated_at,
            "description": description, "color": color})
        return self.get_project(project_id)

    def update_task(self, task_id: str, *, number=UNSET, slug=UNSET, title=UNSET,
                    state=UNSET, folder=UNSET, pinned=UNSET, updated_at=UNSET,
                    closed_at=UNSET, seen_at=UNSET, summary=UNSET, status=UNSET,
                    by: str | None = None, run: str | None = None) -> Task | None:
        """The task as it now stands, or None when there is no such task.

        A number another task already has is refused by the database with
        Django's `IntegrityError`, and nothing is written.

        `status` is the five-word status and `state` its three-word summary;
        either may be given and the other follows it (`STATUS_STATE`), and a
        state given alone leaves a status that already means it as it is. A
        change to either the status or the summary is written down in
        `task_change`, with `by` and `run` saying who made it - or, left out,
        whoever `taskrecord.acting` says is acting now, or Rouh
        (`rouh/taskrecord.py`). This is the one place either changes.
        """
        before = None
        if not (isinstance(status, _Unset) and isinstance(state, _Unset)
                and isinstance(summary, _Unset)):
            before = self.get_task(task_id)
            if before is None:
                return None
        if not isinstance(status, _Unset):
            status = _one_of(status, TASK_STATUSES, "a task's status")
            if not isinstance(state, _Unset) and state != STATUS_STATE[status]:
                raise Refused(f"a task cannot be {status} and {state} at once")
            state = STATUS_STATE[status]
        elif not isinstance(state, _Unset):
            _one_of(state, TASK_STATES, "a task's state")
            if before is not None and STATUS_STATE.get(before.status) != state:
                status = STATE_STATUS[state]
        if not isinstance(summary, _Unset):
            summary = str(summary or "")
        if not isinstance(state, _Unset):
            _one_of(state, TASK_STATES, "a task's state")
            stops = self._stops_now("task", task_id, state)
            seen_at = self._unseen_again(seen_at, stops)
            # When it stopped is written down at the moment it stops, because
            # nothing else says so: `updated_at` moves every time Rouh tidies a
            # row, which is every row at once whenever the workspace's map
            # grows, and read as the stop it relit every waiting and done task
            # the person had already cleared (`owning._ready_at`).
            if stops and isinstance(closed_at, _Unset):
                closed_at = time.time()
        changes = []
        if before is not None:
            from . import taskrecord

            who, came_from = taskrecord.who_is_acting(by, run)
            now = time.time()
            for field, was, to in (("status", before.status, status),
                                   ("summary", before.summary, summary)):
                if not isinstance(to, _Unset) and to != was:
                    changes.append(tables.TaskChange(
                        task_id=task_id, field=field, old=was, new=to, at=now,
                        by=who, run=came_from))
        with self._writing():
            self._set("task", task_id, {
                "number": number, "slug": slug, "title": title, "state": state,
                "folder": folder, "pinned": _as_flag(pinned), "updated_at": updated_at,
                "closed_at": closed_at, "seen_at": seen_at, "summary": summary,
                "status": status})
            if changes:
                tables.TaskChange.objects.bulk_create(changes)
        return self.get_task(task_id)

    def mark_seen(self, task_ids: Iterable[str], when: float | None = None) -> int:
        """The person has now looked at these tasks or steps. One write.

        Many ids in one statement because a press clears a whole branch: the
        dot on a project means something under it is unseen, so clearing it is
        every task under that project at once, and forty separate updates for
        one press is forty chances for half of them to land. The ids come off
        the wire and are only ever parameters of the statement, never part of
        it.
        """
        ids = [str(one) for one in task_ids if one]
        if not ids:
            return 0
        now = time.time() if when is None else float(when)
        with self._writing():
            return int(tables.Task.objects.filter(id__in=ids).update(seen_at=now))

    def archived_tasks(self) -> dict[str, float]:
        """Every archived task and step, by id, with when it was archived.

        One read, because the task browser and the rail both ask it of every
        row at once, and the `object` view they walk has no column for it.
        """
        return {ident: float(at) for ident, at in
                tables.Task.objects.filter(archived_at__isnull=False)
                .values_list("id", "archived_at")}

    def task_origins(self) -> dict[str, dict]:
        """Who made each task and step, by id, for those where anything is said
        (`rouh/task_origin.py`). One read, as `archived_tasks` is, for the same reason."""
        return {ident: origin for ident, origin in
                tables.Task.objects.exclude(origin={}).values_list("id", "origin")
                if isinstance(origin, dict) and origin}

    def task_icons(self) -> dict[str, str]:
        """Every task's and step's icon that has one, by id, in one read (`rouh/taskicons.py`)."""
        return dict(tables.Task.objects.exclude(icon="").values_list("id", "icon"))

    def tasks_for_icons(self, *, every: bool = False,
                        limit: int | None = 200) -> list[tuple[str, str, str]]:
        """Up to `limit` tasks and steps with no icon yet, or with `every` all of them, newest
        first, each as its id, its title and the title of the task it is a step of ("" for
        none): what the icon picker fills (`taskicons.fill`)."""
        rows = tables.Task.objects.all() if every else tables.Task.objects.filter(icon="")
        rows = rows.order_by("-created_at", "id").values_list("id", "title", "slug")
        rows = list(rows if limit is None else rows[:limit])
        if not rows:
            return []
        above = dict(tables.Link.objects.filter(rel=OWNS, src_type="task", dst_type="task",
                                                dst_id__in=[r[0] for r in rows])
                     .values_list("dst_id", "src_id"))
        names = dict(tables.Task.objects.filter(id__in=set(above.values()))
                     .values_list("id", "title"))
        return [(ident, title or slug or ident, names.get(above.get(ident, ""), "") or "")
                for ident, title, slug in rows]

    def set_task_icon(self, task_id: str, icon: str, *, only_if_none: bool = False,
                      by: str | None = None, run: str | None = None) -> bool:
        """Give one task or step its icon: an emoji, or a picture's file name. Whether it was
        written: False for no such task, for the same icon again, and, with `only_if_none`,
        for a task that has one already, which is how a pick the model made in the background
        never lands over one the person made meanwhile. Every change is a row of `task_change`.
        """
        from . import taskrecord

        with self._writing():
            was = (tables.Task.objects.select_for_update().filter(id=task_id)
                   .values_list("icon", flat=True).first())
            if was is None or was == icon or (only_if_none and was):
                return False
            tables.Task.objects.filter(id=task_id).update(icon=_text(icon))
            who, came_from = taskrecord.who_is_acting(by, run)
            tables.TaskChange.objects.create(task_id=task_id, field="icon", old=was, new=icon,
                                             at=time.time(), by=who, run=came_from)
        return True

    def task_meta(self, task_id: str) -> dict | None:
        """This task's meta (`rouh/taskmeta.py`): None when it keeps none."""
        got = tables.Task.objects.filter(id=task_id).values_list("meta", flat=True).first()
        return got if isinstance(got, dict) else None

    def task_metas(self) -> dict[str, dict]:
        """Every task's and step's meta that has one, by id, in one read."""
        return {ident: meta for ident, meta in
                tables.Task.objects.filter(meta__isnull=False).values_list("id", "meta")
                if isinstance(meta, dict)}

    def numbers_before(self) -> dict[str, list[str]]:
        """Every task's and step's earlier numbers that has any, by id, oldest first: the
        numbers a move took away (`rouh/moving.py`)."""
        return {ident: [str(n) for n in was] for ident, was in
                tables.Task.objects.exclude(numbers_before__isnull=True)
                .exclude(numbers_before=[]).values_list("id", "numbers_before")
                if isinstance(was, list) and was}

    def add_number_before(self, task_id: str, number: str) -> list[str]:
        """Keep `number` as one this task was called by, after the ones kept already, and
        answer them all. One locked read and write; a number it has kept already, or none,
        changes nothing."""
        number = str(number or "").strip()
        with transaction.atomic():
            row = (tables.Task.objects.select_for_update().filter(id=task_id)
                   .values_list("numbers_before", flat=True).first())
            was = [str(n) for n in row] if isinstance(row, list) else []
            if number and number not in was:
                was.append(number)
                tables.Task.objects.filter(id=task_id).update(numbers_before=was)
        return was

    def change_task_meta(self, task_id: str, how, *, by: str | None = None,
                         run: str | None = None) -> tuple[bool, dict | None]:
        """Change one task's meta: `how` is given what it is now (a copy, or None) and
        answers what it is to be (a dict, or None for none at all).

        One read and one write under the row's lock, so two changes made at once are both
        kept rather than the second written over the first. A change that changes nothing is
        not written. Every change is a row of `task_change`, with the old and new value as
        JSON, and who made it (`taskrecord.who_is_acting`). Answers whether the task is
        there, and what its meta is afterwards.
        """
        import copy
        import json as _json

        from . import taskrecord

        with self._writing():
            row = (tables.Task.objects.select_for_update().filter(id=task_id)
                   .values_list("meta", flat=True))
            if not row.exists():
                return False, None
            was = row.first()
            was = was if isinstance(was, dict) else None
            to = how(copy.deepcopy(was))
            to = to if isinstance(to, dict) else None
            if to == was:
                return True, was
            tables.Task.objects.filter(id=task_id).update(meta=to)
            who, came_from = taskrecord.who_is_acting(by, run)

            def text(value):
                return "" if value is None else _json.dumps(value, ensure_ascii=False,
                                                            sort_keys=True)

            tables.TaskChange.objects.create(task_id=task_id, field="meta", old=text(was),
                                             new=text(to), at=time.time(), by=who,
                                             run=came_from)
        return True, to

    def set_archived(self, task_ids: Iterable[str], when: float | None) -> int:
        """Archive these tasks at `when`, or bring them back with None. One write.

        The ids are only ever parameters of the statement. Which ids go
        together - a task and whatever under it went with it - is
        `archiving.py`'s answer, not this one's.
        """
        ids = [str(one) for one in task_ids if one]
        if not ids:
            return 0
        with self._writing():
            return int(tables.Task.objects.filter(id__in=ids).update(archived_at=when))

    def update_chat(self, chat_id: str, *, title=UNSET, state=UNSET, pinned=UNSET,
                    unread=UNSET, last_spoke=UNSET, last_activity=UNSET,
                    created_at=UNSET) -> Chat | None:
        """The chat as it now stands, or None when there is no such chat.

        `created_at` is here for one caller and one moment: a row made as a
        placeholder for an `owns` link to point at, being filled in with what
        the conversation really was when the chats moved onto this table
        (`conversations.take_in_chat`). When a conversation began is not
        otherwise something a later write may rewrite.
        """
        if not isinstance(state, _Unset):
            _one_of(state, CHAT_STATES, "a chat's state")
        self._set("chat", chat_id, {
            "title": title, "state": state, "pinned": _as_flag(pinned),
            "unread": _as_flag(unread), "created_at": created_at,
            "last_spoke": last_spoke, "last_activity": last_activity})
        return self.get_chat(chat_id)

    def update_run(self, run_id: str, *, title=UNSET, brief=UNSET, summary=UNSET, state=UNSET,
                   phase=UNSET, detail=UNSET, archived=UNSET, pinned=UNSET,
                   agent=UNSET, workspace=UNSET,
                   policy=UNSET, question=UNSET, branch=UNSET, worktree=UNSET,
                   exit_code=UNSET, cost_usd=UNSET, updated_at=UNSET,
                   ended_at=UNSET, seen_at=UNSET, kind=UNSET) -> Run | None:
        """The run as it now stands, or None when there is no such run.

        `parent_run_id` is not changeable: which run a sub-agent belongs to is
        decided when it starts, and a run that moved under a different parent
        would make a lie of every cost already added up under the first. Nor is
        `started_at`, for the same reason: when a run began is not something a
        later message about it may rewrite.
        """
        # Whether the mark was the caller's own word, which nothing below may
        # overrule: `_unseen_again` answering 0.0 is this module deciding, and
        # is not the same thing.
        told = not isinstance(seen_at, _Unset)
        if not isinstance(state, _Unset):
            _one_of(state, RUN_STATES, "a run's state")
            seen_at = self._unseen_again(seen_at, self._stops_now("run", run_id, state))
        if not isinstance(policy, _Unset):
            _one_of(policy, POLICIES, "a policy")
        if not isinstance(agent, _Unset):
            _one_of(agent, AGENTS, "an agent")
        if not isinstance(kind, _Unset):
            _one_of(kind, RUN_KINDS, "a run's kind")
        # Putting a run out of the way is looking at it: the person has decided
        # about that run, which is the whole of what the dot was asking them to
        # do. After the rule above, and not before it, because archiving a run
        # that is still going stops it as well - one write that both ends it
        # and files it - and of those two the filing is the person's own act.
        if not isinstance(archived, _Unset) and archived and not told:
            seen_at = time.time()
        self._set("run", run_id, {
            "title": title, "brief": brief, "summary": summary, "state": state,
            "phase": phase, "detail": detail, "archived": _as_flag(archived),
            "pinned": _as_flag(pinned), "agent": agent,
            "workspace": workspace, "policy": policy,
            "question": question, "branch": branch, "worktree": worktree,
            "exit_code": exit_code, "cost_usd": cost_usd, "updated_at": updated_at,
            "ended_at": ended_at, "seen_at": seen_at, "kind": kind})
        return self.get_run(run_id)

    def kind_if_unknown(self, run_id: str, kind: str) -> bool:
        """Say which half of Metabolism a run is on, only where nothing has said yet.

        For the feeds, which see a run every time it changes and must never
        overrule what its start decided (`runs.kind_of`). True if it was written.
        """
        _one_of(kind, RUN_KINDS, "a run's kind")
        with self._writing():
            return tables.Run.objects.filter(id=run_id, kind="").update(kind=kind) > 0

    def update_artifact(self, artifact_id: str, *, title=UNSET, path=UNSET, mime=UNSET,
                        head_version=UNSET, pinned=UNSET) -> Artifact | None:
        """The artifact as it now stands, or None when there is no such artifact."""
        self._set("artifact", artifact_id, {
            "title": title, "path": path, "mime": mime, "head_version": head_version,
            "pinned": _as_flag(pinned)})
        return self.get_artifact(artifact_id)

    def _stops_now(self, kind: str, obj_id: str, state) -> bool:
        """Whether writing `state` is the moment this thing stops.

        The state has to actually move, and into a stopped one: the dozens of
        writes a stopped row goes on getting - a line of detail, an exit code,
        the same state said again by a folder - are not a stop, and treating
        them as one would put a dot back after the person had cleared it.
        """
        row = self._one(kind, obj_id)
        return (row is not None and row["state"] != state
                and state in STOPPED.get(kind, ()))

    @staticmethod
    def _unseen_again(seen_at, stops: bool):
        """Zero `seen_at` when this write is the moment the thing stops.

        The dot on the rail is one question - has something stopped that I have
        not looked at - and this is the half of the answer the person cannot
        give. **Every stop is a new one.** A run that finished, was opened, was
        carried on and finished again is a second thing to go and look at, and
        a mark left over from the first would be a dot that stayed off about
        it. So the mark is cleared by the change into a stopped state, and only
        by that change (`_stops_now`).

        `seen_at` given by the caller wins, so that the one write that says
        "the person has now seen this" is never undone by the state beside it.
        """
        if not isinstance(seen_at, _Unset):
            return seen_at
        return 0.0 if stops else seen_at

    # --- deleting them ------------------------------------------------------

    def owned_tree(self, kind: str, obj_id: str, *,
                   keep: Keep = None) -> list[tuple[str, str]]:
        """Everything this object owns, all the way down, deepest first.

        The `owns` edges, plus a run's sub-agents, which are owned by their
        parent through `parent_run_id` rather than through a row. Deepest
        first, so walking the answer and deleting as you go never takes an
        owner away before what it owned.

        It is the question the confirmation asks - "what else goes with it" -
        and the list `delete` deletes, so the sentence a person reads and the
        write that follows cannot be about different things.

        `keep` is the few things a cascade may never take, as (type, id)
        pairs. One of them is not walked into and not returned, so what it
        owns stays with it; when its owner goes it is simply unowned, which is
        legal and ordinary. There is one, and `owning.KEEP` names it: General,
        the thread that is always there.
        """
        _kind(kind)
        return self._owned_tree(kind, obj_id, keep)

    def _owned_tree(self, kind: str, obj_id: str,
                    keep: Keep = None) -> list[tuple[str, str]]:
        """The walk itself.

        Breadth first, with the set of what it has already seen carried along:
        a ring in the rows - one written before `attach` walked for rings -
        stops it rather than spinning it, and `LIMIT_CASCADE` stops a tree so
        wide that something else has gone wrong.
        """
        spared = keep or frozenset()
        found: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = {(kind, obj_id)}
        edge: list[tuple[str, str]] = [(kind, obj_id)]
        while edge and len(found) < LIMIT_CASCADE:
            at_type, at_id = edge.pop(0)
            kids = list(tables.Link.objects
                        .filter(rel=OWNS, src_type=at_type, src_id=at_id)
                        .order_by("created_at", "id").values_list("dst_type", "dst_id"))
            if at_type == "run":
                kids += [("run", sub) for sub in tables.Run.objects
                         .filter(parent_run_id=at_id).order_by("started_at", "id")
                         .values_list("id", flat=True)]
            for kid in kids:
                if kid in seen or kid in spared:
                    continue
                seen.add(kid)
                found.append(kid)
                edge.append(kid)
        if len(found) >= LIMIT_CASCADE:
            log.warning("the cascade under %s %s hit the limit of %d objects",
                        kind, obj_id, LIMIT_CASCADE)
        found.reverse()
        return found

    def delete(self, kind: str, obj_id: str, *, cascade: bool = True,
               keep: Keep = None) -> list[tuple[str, str]]:
        """Delete an object and everything it owns, in one transaction.

        The one delete in this module: `delete_project`, `delete_task`,
        `delete_chat`, `delete_run` and `delete_artifact` are all this, with
        the type written in, so there is one cascade and not five.

        Answers what went, deepest first and the object itself last, as
        (type, id) pairs. An empty list means there was nothing there to
        delete, which is not an error: two tabs pressing the same cross is an
        ordinary thing to happen.

        `cascade=False` deletes the one row and orphans what it owned, which
        is what this module did for everything until 22 September 2026. It is
        kept for the one caller that wants it - undoing a create that could
        not reach the disk - and for nothing else.

        `keep` is what the cascade may not take, and is `owned_tree`'s.

        A chat's messages and an artifact's versions go with it, and a deleted
        run's sub-agents and the versions it wrote let go of its name, and all
        four are the database's doing: `ON DELETE` on the foreign keys.
        """
        _kind(kind)
        with self._writing():
            if not self._there(kind, obj_id):
                return []
            targets = self._owned_tree(kind, obj_id, keep) if cascade else []
            targets.append((kind, obj_id))
            gone: list[tuple[str, str]] = []
            for at_type, at_id in targets:
                _kind(at_type)
                deleted, _ = _TABLE[at_type].objects.filter(id=at_id).delete()
                if deleted > 0:
                    gone.append((at_type, at_id))
                # Both ways round, always: the `owns` rows where it was the
                # owner and every row where it was the far end, so nothing is
                # left pointing at something that is not there.
                tables.Link.objects.filter(
                    Q(src_type=at_type, src_id=at_id) | Q(dst_type=at_type, dst_id=at_id)
                ).delete()
                # The derived index of that object's files, which is only
                # ever a copy of what is on disk and has nothing to be a copy
                # of once the object is gone.
                tables.ContentFile.objects.filter(object_id=at_id).delete()
        return gone

    def sweep_links(self) -> int:
        """Delete every link whose either end is not there, and say how many.

        `delete` leaves none, and this is the answer to "is that still true"
        for the whole table at once - after a migration, after a row somebody
        removed at a `psql` prompt, after anything that did not come through
        here. Nothing else in this module needs it to have been run.

        Every table and column name in the statement is one of this module's
        own constants, never anything a caller handed in.
        """
        sql = " UNION ALL ".join(
            f"SELECT id FROM link WHERE {end}_type='{kind}'"
            f" AND {end}_id NOT IN (SELECT id FROM {kind})"
            for kind in KINDS for end in ("src", "dst"))
        with self._writing():
            orphans = [row["id"] for row in _rows(sql)]
            if orphans:
                tables.Link.objects.filter(id__in=orphans).delete()
        if orphans:
            log.info("swept %d link(s) pointing at something that is not there",
                     len(orphans))
        return len(orphans)

    def delete_project(self, project_id: str, *, keep: Keep = None) -> bool:
        """Delete a project and everything under it."""
        return bool(self.delete("project", project_id, keep=keep))

    def delete_task(self, task_id: str, *, cascade: bool = True,
                    keep: Keep = None) -> bool:
        """Delete a task and everything under it: its steps, chats, runs, cards."""
        return bool(self.delete("task", task_id, cascade=cascade, keep=keep))

    def delete_chat(self, chat_id: str) -> bool:
        """Delete a chat, its messages, and everything it owns.

        A run that came `from` it is a reference and stays: only what the chat
        owns goes with it.
        """
        return bool(self.delete("chat", chat_id))

    def delete_run(self, run_id: str) -> bool:
        """Delete a run, its sub-agents, and everything it owns.

        Its artifacts go if it owned them. An artifact it only `made` - one
        somebody else owns - keeps its body and forgets who wrote it.
        """
        return bool(self.delete("run", run_id))

    def delete_artifact(self, artifact_id: str) -> bool:
        """Delete an artifact and its versions, which cannot exist alone."""
        return bool(self.delete("artifact", artifact_id))

    # --- ownership ----------------------------------------------------------

    def attach(self, owner_type: str, owner_id: str, child_type: str,
               child_id: str) -> Link:
        """Give an object an owner, in one statement.

        Attach, detach-and-reattach, and move are the same write: the partial
        unique index on `link(dst_type, dst_id)` means the child's existing
        `owns` row, whatever it is, is the row this conflicts with, and the
        upsert takes it over. So there is never a moment where an object has
        two owners or none, and there is no read-then-write to lose a race.

        Ownership points down `project > task > chat > run > artifact`, with
        one exception: **a project may own a project and a task may own a
        task**, which is the nesting the hierarchy is made of. Anything else
        raises `NotDownward`: a task may not own a project, a chat may not own
        a chat or a task, a run may not own a run, a chat or a task.

        The ranking used to make a cycle impossible on its own, and with two
        types nesting it no longer does: three projects can be written into a
        ring where each owns the next and none of them is under anything. So
        an edge between two objects of the same type walks up from the
        proposed owner first, inside the same transaction as the write, and
        refuses the edge if the child is already somewhere above it. Every
        other edge still cannot make a cycle and is not walked.
        """
        _kind(owner_type, "an owner's type")
        _kind(child_type, "a child's type")
        if not may_own(owner_type, child_type):
            raise NotDownward(
                f"a {owner_type} may not own a {child_type}: ownership points "
                f"down {' > '.join(KINDS)}, and only a project may own a project "
                "and a task a task"
            )
        if owner_type == child_type and owner_id == child_id:
            raise NotDownward(f"a {owner_type} may not own itself")
        now = time.time()
        with self._writing():
            self._must_be_there(owner_type, owner_id)
            self._must_be_there(child_type, child_id)
            if owner_type == child_type:
                self._refuse_a_circle(owner_type, owner_id, child_type, child_id)
            # The upsert against the partial unique index, as SQL, because it
            # is one statement that way and two in the ORM: PostgreSQL finds
            # the child's `owns` row by the index `link_one_owner` and moves it,
            # or writes the first one.
            with connection.cursor() as cur:
                cur.execute(
                    "INSERT INTO link (id, rel, src_type, src_id, dst_type, dst_id,"
                    " created_at) VALUES (%s, %s, %s, %s, %s, %s, %s)"
                    " ON CONFLICT (dst_type, dst_id) WHERE rel = 'owns'"
                    " DO UPDATE SET src_type = EXCLUDED.src_type,"
                    " src_id = EXCLUDED.src_id, created_at = EXCLUDED.created_at",
                    [_new_id("link"), OWNS, owner_type, owner_id, child_type, child_id,
                     now])
            row = tables.Link.objects.filter(
                rel=OWNS, dst_type=child_type, dst_id=child_id).values().first()
        if owner_type == "task" and child_type == "chat":
            # A chat turned into a task's, or filed under one: its files move into the task's
            # folder, and the list says so, in the same step (`rouh/filestore.py`).
            try:
                from . import filestore

                filestore.follow_chat(child_id, owner_id)
            except Exception:  # noqa: BLE001 - the chat is the task's either way
                log.exception("the files of chat %s did not follow it to task %s",
                              child_id, owner_id)
        return _link(row)

    def _refuse_a_circle(self, owner_type: str, owner_id: str,
                         child_type: str, child_id: str) -> None:
        """Refuse an edge that would put the child above itself.

        Walks from the proposed owner up its own chain of owners. Reaching the
        child means the edge closes a ring; reaching nothing means it does
        not. The walk is bounded by how many objects there are, so a ring
        already in the rows - one written before this check existed - stops it
        rather than spinning. The caller holds the lock and the transaction.
        """
        seen: set[tuple[str, str]] = set()
        at: tuple[str, str] | None = (owner_type, owner_id)
        while at is not None:
            if at == (child_type, child_id):
                raise NotDownward(
                    f"that would put {child_type} {child_id} inside itself: it is "
                    f"already above {owner_type} {owner_id}")
            if at in seen:
                return
            seen.add(at)
            up = (tables.Link.objects.filter(rel=OWNS, dst_type=at[0], dst_id=at[1])
                  .values_list("src_type", "src_id").first())
            at = (up[0], up[1]) if up else None

    def detach(self, child_type: str, child_id: str) -> bool:
        """Take an object's owner away, leaving it an orphan. True if it had one."""
        _kind(child_type, "a child's type")
        with self._writing():
            deleted, _ = tables.Link.objects.filter(
                rel=OWNS, dst_type=child_type, dst_id=child_id).delete()
        return deleted > 0

    def owner_of(self, child_type: str, child_id: str) -> tuple[str, str] | None:
        """Who owns this, as (type, id), or None. There is never more than one."""
        _kind(child_type, "a child's type")
        row = (tables.Link.objects.filter(rel=OWNS, dst_type=child_type, dst_id=child_id)
               .values_list("src_type", "src_id").first())
        return (row[0], row[1]) if row else None

    def children_of(self, owner_type: str, owner_id: str,
                    child_type: str | None = None) -> list[tuple[str, str]]:
        """What this owns, as (type, id) pairs, oldest first.

        Pairs rather than objects because what an owner holds is a mixture:
        `get_chat`, `get_run` and the rest turn a pair into the thing itself.
        """
        _kind(owner_type, "an owner's type")
        rows = tables.Link.objects.filter(rel=OWNS, src_type=owner_type, src_id=owner_id)
        if child_type is not None:
            rows = rows.filter(dst_type=_kind(child_type, "a child's type"))
        return [(t, i) for t, i in
                rows.order_by("created_at", "id").values_list("dst_type", "dst_id")]

    def homes(self, keys: Iterable[tuple[str, str]]) -> dict[tuple[str, str], tuple[str, str]]:
        """The task or project each of these lives in, as (type, id), by (type, id).

        Climbed up whatever ties a thing to where it came from, nearest
        first: its owner (a card is owned by a chat, the chat by a task); for
        a run, the run it is a sub-agent of and the chat that started it
        (`from`); for a card, the run that made it (`made`). The first task or
        project reached on the way up is the home. A task or a project is its
        own. Something none of those reach - a loose chat, and what only it
        made - is left out, and `rouh/searching.py` looks at what it says.

        One query per level and kind rather than one per key, because this
        is asked for a whole page of search results at once.
        """
        out: dict[tuple[str, str], tuple[str, str]] = {}
        at = {key: [key] for key in keys}
        seen = {key: {key} for key in at}
        for _ in range(8):
            climbing = {}
            for key, frontier in at.items():
                home = next((where for where in frontier if where[0] in NESTS), None)
                if home is not None:
                    out[key] = home
                elif frontier:
                    climbing[key] = frontier
            if not climbing:
                break
            up = self._ties_up({where for frontier in climbing.values() for where in frontier})
            at = {}
            for key, frontier in climbing.items():
                nxt = []
                for where in frontier:
                    for above in up.get(where, ()):
                        if above not in seen[key]:
                            seen[key].add(above)
                            nxt.append(above)
                at[key] = nxt[:12]
        return out

    def _ties_up(self, nodes: set[tuple[str, str]]) -> dict[tuple[str, str], list[tuple[str, str]]]:
        """What each of these came from, nearest first, for `homes`."""
        wanted: dict[str, set[str]] = {}
        for kind, ident in nodes:
            wanted.setdefault(kind, set()).add(ident)
        up: dict[tuple[str, str], list[tuple[str, str]]] = {}
        for kind, idents in wanted.items():
            for src_type, src_id, dst_id in (
                    tables.Link.objects.filter(rel=OWNS, dst_type=kind, dst_id__in=idents)
                    .values_list("src_type", "src_id", "dst_id")):
                up.setdefault((kind, dst_id), []).append((src_type, src_id))
        runs = wanted.get("run", set())
        if runs:
            for ident, parent in (tables.Run.objects.filter(id__in=runs)
                                  .exclude(parent_run_id__isnull=True).exclude(parent_run_id="")
                                  .values_list("id", "parent_run_id")):
                up.setdefault(("run", ident), []).append(("run", parent))
            for src_id, dst_id in (tables.Link.objects
                                   .filter(rel="from", src_type="run", src_id__in=runs,
                                           dst_type="chat")
                                   .values_list("src_id", "dst_id")):
                up.setdefault(("run", src_id), []).append(("chat", dst_id))
        cards = wanted.get("artifact", set())
        if cards:
            for src_id, dst_id in (tables.Link.objects
                                   .filter(rel="made", src_type="run", dst_type="artifact",
                                           dst_id__in=cards)
                                   .values_list("src_id", "dst_id")):
                up.setdefault(("artifact", dst_id), []).append(("run", src_id))
        return up

    def task_titles(self) -> list[tuple[str, str]]:
        """Every task, as (id, title)."""
        return list(_TABLE["task"].objects.values_list("id", "title"))

    def task_numbers(self) -> list[tuple[str, int | None, str]]:
        """Every task, as (id, number, folder): what `searching` reads names from."""
        return list(_TABLE["task"].objects.values_list("id", "number", "folder"))

    def rows_of(self, keys: Iterable[tuple[str, str]]) -> list[dict]:
        """These objects, each as a search hit that matched by its name.

        For what a search puts in front of the words it found, by what it is
        rather than by what it says (`searching.search` for a task's number).
        """
        return self._describe_found(
            {(kind, ident): {"type": kind, "id": ident, "matched": "title", "body": ""}
             for kind, ident in keys}, limit=None)

    # --- the references, which are never ownership --------------------------

    def add_ref(self, rel: str, src_type: str, src_id: str, dst_type: str,
                dst_id: str) -> Link:
        """Write one reference: `made`, `from` or `about`. Saying it twice is one row.

        `made` is run -> artifact, many to many. `from` is run -> chat, many to
        one: which conversation started the run. `about` is anything -> task,
        many to many. None of the three is ownership and none of them holds
        anything in place: the thing at either end can be deleted without the
        other noticing. Ownership is `attach`.
        """
        if rel == OWNS:
            raise Refused("ownership is attach(), so that it can only ever be one owner")
        _one_of(rel, RELS, "a relation")
        _kind(src_type, "a source's type")
        _kind(dst_type, "a destination's type")
        froms, tos = REF_ENDS[rel]
        if src_type not in froms or dst_type not in tos:
            raise Refused(
                f"{rel!r} goes from {' or '.join(froms)} to {' or '.join(tos)}, "
                f"and not from {src_type} to {dst_type}")
        now = time.time()
        with self._writing():
            self._must_be_there(src_type, src_id)
            self._must_be_there(dst_type, dst_id)
            # ON CONFLICT DO NOTHING: the same reference written twice is the
            # one row that is already there.
            tables.Link.objects.bulk_create(
                [tables.Link(id=_new_id("link"), rel=rel, src_type=src_type, src_id=src_id,
                             dst_type=dst_type, dst_id=dst_id, created_at=now)],
                ignore_conflicts=True)
            row = tables.Link.objects.filter(
                rel=rel, src_type=src_type, src_id=src_id, dst_type=dst_type,
                dst_id=dst_id).values().first()
        return _link(row)

    def refs(self, rel: str | None = None, *, src_type: str | None = None,
             src_id: str | None = None, dst_type: str | None = None,
             dst_id: str | None = None) -> list[Link]:
        """Whichever links match, oldest first. Everything given narrows it.

        Ask by `rel` for one kind of reference, by either end for everything
        touching an object. `rel='owns'` is answered too: this reads the whole
        table, and `owner_of` and `children_of` are the two questions worth
        having a name.
        """
        rows = tables.Link.objects.all()
        for column, value, what in (("rel", rel, "a relation"),
                                    ("src_type", src_type, "a source's type"),
                                    ("src_id", src_id, ""),
                                    ("dst_type", dst_type, "a destination's type"),
                                    ("dst_id", dst_id, "")):
            if value is None:
                continue
            if column == "rel":
                _one_of(value, RELS, what)
            elif column.endswith("_type"):
                _kind(value, what)
            rows = rows.filter(**{column: value})
        return [_link(r) for r in rows.order_by("created_at", "id").values()]

    # --- the two true children ----------------------------------------------

    def add_message(self, chat_id: str, role: str, body: str = "", *,
                    seq: int | None = None) -> Message:
        """One turn in a chat. Numbered after the last one unless told which.

        Goes when the chat goes: this is one of the two things in this module
        that cascade. A `seq` the chat already has is refused by the database
        with Django's `IntegrityError`, and nothing is written.
        """
        with self._writing():
            self._must_be_there("chat", chat_id)
            if seq is None:
                top = tables.ChatMessage.objects.filter(chat_id=chat_id).aggregate(
                    top=Max("seq"))["top"]
                seq = int(top or 0) + 1
            made = Message(id=_new_id("message"), chat_id=chat_id, seq=seq,
                           role=role, body=body)
            tables.ChatMessage.objects.create(
                id=made.id, chat_id=made.chat_id, seq=made.seq, role=_text(made.role),
                body=_text(made.body))
        return made

    def messages(self, chat_id: str, *, limit: int = 500) -> list[Message]:
        """A chat's turns, in the order they were said."""
        rows = tables.ChatMessage.objects.filter(chat_id=chat_id).order_by("seq").values()
        return [_message(r) for r in _cut(rows, limit)]

    def last_said(self, chat_ids: Iterable[str]) -> dict[str, str]:
        """Who said the last thing in each of these chats (its role), by chat id.

        One query for a handful of chats, for the Control Room's "Left off"
        line, which says whether the person or Rouh spoke last.
        """
        ids = [str(one) for one in chat_ids if one]
        if not ids:
            return {}
        rows = (tables.ChatMessage.objects.filter(chat_id__in=ids)
                .order_by("chat_id", "-seq").distinct("chat_id")
                .values_list("chat_id", "role"))
        return {chat: str(role or "") for chat, role in rows}

    def message_counts(self, chat_ids=None) -> dict[str, int]:
        """How many turns each chat has, as one query rather than one per chat.

        The list of conversations says how much was said in each, and asking
        that chat by chat is a query per row of a list that is drawn on every
        change to any of them. `chat_ids` counts only those chats.
        """
        found = tables.ChatMessage.objects.order_by()
        if chat_ids is not None:
            found = found.filter(chat_id__in=list(chat_ids))
        rows = (found.values("chat_id")
                .annotate(said=Count("id")).values_list("chat_id", "said"))
        return {chat: int(said) for chat, said in rows}

    def add_version(self, artifact_id: str, *, body: str | None = None,
                    made_by_run: str | None = None,
                    version: int | None = None) -> ArtifactVersion:
        """A new version of an artifact, and the head moves to it.

        `made_by_run` is a note of which run wrote it and holds nothing in
        place: deleting that run leaves this version with its body and without
        a name against it.
        """
        with self._writing():
            self._must_be_there("artifact", artifact_id)
            if made_by_run is not None:
                self._must_be_there("run", made_by_run)
            if version is None:
                top = tables.ArtifactVersion.objects.filter(
                    artifact_id=artifact_id).aggregate(top=Max("version"))["top"]
                version = int(top or 0) + 1
            made = ArtifactVersion(artifact_id=artifact_id, version=version, body=body,
                                   made_by_run=made_by_run)
            tables.ArtifactVersion.objects.create(
                artifact_id=made.artifact_id, version=made.version, body=_text(made.body),
                made_by_run_id=made.made_by_run)
            tables.Artifact.objects.filter(id=artifact_id, head_version__lt=version).update(
                head_version=version)
        return made

    def rewrite_version(self, artifact_id: str, *, body: str,
                        version: int | None = None) -> ArtifactVersion | None:
        """Write over a version where it stands, adding none.

        The one thing `add_version` is wrong for: a card the person is typing
        into (`rouh/composing.py`), where every second of typing would
        otherwise be a revision of its own and the card's history would be a
        reel of keystrokes rather than what it said. Everything else that
        changes a card adds a version, because everything else is a change
        somebody would want to look back at.
        """
        with self._writing():
            self._must_be_there("artifact", artifact_id)
            if version is None:
                row = tables.Artifact.objects.filter(id=artifact_id).values("head_version").first()
                version = int((row or {}).get("head_version") or 0)
            if not version:
                return None
            changed = tables.ArtifactVersion.objects.filter(
                artifact_id=artifact_id, version=version).update(body=_text(body))
            if not changed:
                return None
        return ArtifactVersion(artifact_id=artifact_id, version=version, body=body,
                               made_by_run=None)

    def versions(self, artifact_id: str) -> list[ArtifactVersion]:
        """Every version of an artifact, oldest first."""
        rows = (tables.ArtifactVersion.objects.filter(artifact_id=artifact_id)
                .order_by("version").values(*_VERSION_COLUMNS))
        return [_version_of(r) for r in rows]

    def version(self, artifact_id: str, version: int | None = None) -> ArtifactVersion | None:
        """One version of an artifact, or its head when none is named.

        The head is a column on the artifact rather than "the highest one", so
        a head that has been moved back to an earlier revision is answered
        with that revision and not with the newest body on file.
        """
        rows = tables.ArtifactVersion.objects.filter(artifact_id=artifact_id)
        if version is None:
            rows = rows.filter(version=F("artifact__head_version"))
        else:
            rows = rows.filter(version=version)
        row = rows.values(*_VERSION_COLUMNS).first()
        return _version_of(row) if row else None

    def head_bodies(self, artifact_ids: Iterable[str]) -> dict[str, str]:
        """The head version's body of each of these artifacts, in one query.

        For a reader that already has the artifacts and wants what a few
        hundred of them say without a query each: a task's page, deciding
        which of the cards under it are only a page it already lists.
        """
        ids = [str(one) for one in artifact_ids if one]
        if not ids:
            return {}
        rows = (tables.ArtifactVersion.objects
                .filter(artifact_id__in=ids, version=F("artifact__head_version"))
                .values_list("artifact_id", "body"))
        return {str(ident): body or "" for ident, body in rows}

    def artifact_at(self, path: str) -> Artifact | None:
        """The artifact whose bytes are that file, if one of them is.

        One file, one row. A step folder that is already an artifact's - the
        card that was written out into it - must not become a second artifact
        the first time somebody opens it, which would be two records of one
        thing all over again.
        """
        row = (tables.Artifact.objects.filter(path=path).order_by("created_at", "id")
               .values().first())
        return _artifact(row) if row else None

    def artifacts_under(self, folder: str) -> list[Artifact]:
        """Every artifact whose file is that folder, or is inside it.

        A folder that moves takes its files with it, so every row naming one of
        them has to follow. A task's folder is in `task.folder` and moves with
        the task; a page it built is in `artifact.path` and had nothing moving
        it at all, which is how a project page came to list a page whose address
        answered 404 (`objecttree.move`).

        The prefix is matched as the characters it is: a folder called
        `10%.something` does not match every path on the workspace. And it is
        matched with its case, as the folders on disk are: until 23 September
        2026 SQLite's LIKE matched `Tasks/` and `tasks/` as one prefix, which
        was never what a move meant.
        """
        rel = str(folder or "").strip().strip("/")
        if not rel:
            return []
        rows = (tables.Artifact.objects
                .filter(Q(path=rel) | Q(path__startswith=rel + "/"))
                .order_by("created_at", "id").values())
        return [_artifact(row) for row in rows]

    def heads(self, *, kind: str | None = None, owner: tuple[str, str] | None = None,
              unowned: bool = False, matching: str | None = None,
              before: str | None = None, limit: int = 200
              ) -> list[tuple[Artifact, ArtifactVersion | None]]:
        """Artifacts with the body of their head version, newest first.

        One query rather than one per artifact, because every reader of this
        table wants both halves: a canvas draws what a card says, a search
        matches the words in it, and a page written out to disk is the head's
        body. Asking for the artifacts and then asking again for each body is
        a page of the screen costing a query a card.

        `owner` narrows to what that object owns, through the link table, and
        is how "this chat's canvas" and "this task's steps" are asked for.
        `unowned` is the other side of it: the orphans, owned by nobody.
        `matching` matches the title or the head body, which is where a card's
        description is, whatever the case. `before` is an artifact's id and
        means everything older than it, so a reader scrolls back through the
        screen a page at a time rather than asking for the whole of it; an id
        that is not here is ignored rather than answered with nothing.

        SQL rather than the ORM, because the join and the row value below are
        the whole of what this is and are clearer written out.
        """
        where = ["TRUE"]
        params: list = []
        if kind is not None:
            where.append("a.kind = %s")
            params.append(_one_of(kind, ARTIFACT_KINDS, "an artifact's kind"))
        if owner is not None:
            owner_type, owner_id = owner
            where.append(
                "EXISTS (SELECT 1 FROM link l WHERE l.rel = 'owns'"
                " AND l.dst_type = 'artifact' AND l.dst_id = a.id"
                " AND l.src_type = %s AND l.src_id = %s)")
            params += [_kind(owner_type, "an owner's type"), owner_id]
        if unowned:
            where.append(
                "NOT EXISTS (SELECT 1 FROM link l WHERE l.rel = 'owns'"
                " AND l.dst_type = 'artifact' AND l.dst_id = a.id)")
        if matching and matching.strip():
            # A pattern as it always was, with its `%` and `_` meaning what
            # they mean in one, and with no escape character, as SQLite had
            # none: a backslash in what the person typed is a backslash.
            where.append("(a.title ILIKE %s ESCAPE '' OR v.body ILIKE %s ESCAPE '')")
            like = f"%{matching.strip()}%"
            params += [like, like]
        if before:
            edge = (tables.Artifact.objects.filter(id=before)
                    .values_list("created_at", "id").first())
            if edge is not None:
                # A row value, so two cards drawn in the same instant are
                # still strictly ordered and a page can never repeat one.
                where.append("(a.created_at, a.id) < (%s, %s)")
                params += [edge[0], edge[1]]
        top = _limit(limit)
        rows = _rows(
            "SELECT a.id, a.kind, a.title, a.path, a.mime, a.head_version, a.pinned,"
            " a.created_at, v.version AS head_v, v.body AS head_body,"
            " v.made_by_run AS head_run"
            " FROM artifact a LEFT JOIN artifact_version v"
            "   ON v.artifact_id = a.id AND v.version = a.head_version"
            " WHERE " + " AND ".join(where)
            + " ORDER BY a.created_at DESC, a.id DESC"
            + (" LIMIT %s" if top is not None else ""),
            (*params, *([top] if top is not None else [])))
        out: list[tuple[Artifact, ArtifactVersion | None]] = []
        for row in rows:
            head = None
            if row["head_v"] is not None:
                head = ArtifactVersion(artifact_id=row["id"], version=row["head_v"],
                                       body=row["head_body"], made_by_run=row["head_run"])
            out.append((_artifact(row), head))
        return out

    # --- the hierarchy, as one question -------------------------------------

    def objects(self, *, type: str | None = None) -> list[dict]:
        """Every project and every task, as the `object` view sees them.

        Plain dictionaries rather than `Project` and `Task`, because the
        callers that want this want the two together: the whole tree, checked
        against the folders on disk, counted. Asking about one of them is
        `list_projects` and `list_tasks`.

        Ordered by type, then number with the unnumbered first, then folder
        name, which is the order SQLite gave until 23 September 2026 and the
        one the task browser was drawn in; two steps with the same name in
        different tasks then go by where they are, parent folders first, and
        last by id, so the order never changes between two reads. The pin comes
        back as 1 or 0, as it did then, because these dictionaries go to the
        page as they are.
        """
        rows = tables.ObjectRow.objects.all()
        if type is not None:
            rows = rows.filter(type=_one_of(type, NESTS, "an object type"))
        out = []
        for row in rows.order_by("type", F("number").asc(nulls_first=True), "slug",
                                 "folder", "id").values():
            row["pinned"] = int(bool(row["pinned"]))
            out.append(row)
        return out

    def owns_edges(self) -> list[tuple[str, str, str, str]]:
        """Every `owns` link, as (owner type, owner id, child type, child id).

        The whole of the hierarchy in one read, for whoever has to check that
        it is a tree: nothing owned twice, which the database already refuses,
        and nothing owning itself round a ring, which is checked on the way in
        and is checked again here because the rows can be older than the check.
        """
        return [tuple(row) for row in
                tables.Link.objects.filter(rel=OWNS).order_by("created_at", "id")
                .values_list("src_type", "src_id", "dst_type", "dst_id")]

    # --- the derived content index ------------------------------------------

    def put_content(self, object_id: str, files: list[dict]) -> int:
        """Replace everything indexed for one object, in one transaction.

        Each file is a dict of `path`, `sha256`, `bytes`, `modified` and
        `body`. Replacing rather than merging is what makes this derived: a
        file that was deleted on disk leaves no row behind, because the rows
        for that object are all written afresh from what is there now.

        The search vector is the database's, worked out from the body as each
        row goes in (`rouh/models/objects.py`), so there is no second table to
        keep in step. Two things PostgreSQL will not take are put right here
        rather than let one file stop a whole object being indexed:

        - **A NUL character.** PostgreSQL refuses one anywhere in text, and a
          file that is half binary has them; each becomes a space in the words,
          which are only ever a copy of the file for searching, so the words
          either side of it stay two words.
        - **A vector too big to keep.** PostgreSQL caps one at a megabyte, and
          a file of nothing but distinct tokens could pass it. That file keeps
          its row, its hash and as much of its text as fits.
        """
        now = time.time()
        rows = [(object_id, file["path"], file["sha256"], file["bytes"], file["modified"],
                 str(file["body"] or "").replace("\x00", " "), now) for file in files]
        insert = ("INSERT INTO content_file (object_id, path, sha256, bytes, modified,"
                  " body, indexed_at) VALUES (%s, %s, %s, %s, %s, %s, %s)")
        with self._writing():
            tables.ContentFile.objects.filter(object_id=object_id).delete()
            try:
                # Raw rather than the ORM, so the vector the database has just
                # made is not handed back to Python row by row for nothing.
                with transaction.atomic(), connection.cursor() as cur:
                    cur.executemany(insert, rows)
            except DatabaseError:
                for row in rows:
                    self._put_one_content_file(insert, row)
        return len(files)

    @staticmethod
    def _put_one_content_file(insert: str, row: tuple) -> None:
        """One file of the content index, as much of it as PostgreSQL will index.

        Only reached when a batch was refused. The whole body first; then the
        first tenth of it, and the first hundredth; then no words at all, so
        the file is still there with its hash, which is what `drifted` reads.
        A row that is refused for any other reason is refused, as it would
        have been before.
        """
        body = row[5]
        for keep in (len(body), len(body) // 10, len(body) // 100, 0):
            try:
                with transaction.atomic(), connection.cursor() as cur:
                    cur.execute(insert, (*row[:5], body[:keep], row[6]))
            except DatabaseError:
                if keep == 0:
                    raise
                continue
            if keep < len(body):
                log.warning("%s is indexed with only the first %d of its %d characters:"
                            " PostgreSQL would not make a search vector of more",
                            row[1], keep, len(body))
            return

    def content_of(self, object_id: str, path: str | None = None) -> list[dict]:
        """What is indexed for one object, by path, or one file of it."""
        rows = tables.ContentFile.objects.filter(object_id=object_id)
        if path is not None:
            rows = rows.filter(path=path)
        return list(rows.order_by("path").values(*_CONTENT_COLUMNS))

    def content_paths_named(self, name: str, limit: int = 500) -> list[str]:
        """Paths in the content index whose file is called `name`, at most `limit`."""
        return list(tables.ContentFile.objects.filter(path__endswith="/" + name)
                    .values_list("path", flat=True)[:limit])

    def content_counts(self) -> tuple[int, int]:
        """How many files are indexed, and how many objects they belong to."""
        got = tables.ContentFile.objects.aggregate(
            files=Count("*"), objects=Count("object_id", distinct=True))
        return int(got["files"]), int(got["objects"])

    def search_content(self, query: str, *, limit: int = 40,
                       marks: tuple[str, str] = ("[", "]")) -> list[dict]:
        """Files whose words match, best match first.

        PostgreSQL's full-text search over the vector the database keeps of
        every body. Every word of the query has to be in the file, and a word
        with punctuation inside it - `rouh.example.com`, `app.js` - is those
        words one after the other, which is how SQLite's FTS5 read one until
        23 September 2026 and how the vector is cut (`rouh/models/objects.py`).
        Ranked by `ts_rank`, which is not FTS5's bm25, so two files that both
        match may come back in a different order than they did.

        A query that has no letters or digits in it at all is not something
        the index can be asked, and a query the database refuses for any other
        reason is no reason to answer nothing, so both are answered by reading
        every file for the words instead - the question FTS5's own fallback
        asked: each word somewhere in the file, whatever its case.

        `hit` is a few words of the file around the first match, with `marks`
        either side of each word that matched and an ellipsis on whichever end
        was cut, the way FTS5's `snippet()` made one. The square brackets are
        for a person reading the answer in a terminal (`objecttree search`);
        the search box asks for none, because the page marks the words itself
        and would otherwise draw both.
        """
        words = [w for w in (query or "").split() if w]
        if not words:
            return []
        if self.searchable and indexable(words):
            try:
                with transaction.atomic():
                    return self._search_index(words, limit, marks)
            except DatabaseError:
                log.debug("the full-text index would not take %r; scanning instead", query)
        rows = tables.ContentFile.objects.filter(
            reduce(and_, [Q(body__icontains=w) for w in words]))
        rows = rows.order_by("object_id", "path").annotate(hit=Substr("body", 1, 200))
        return list(_cut(rows.values("object_id", "path", "hit"), limit))

    def _search_index(self, words: list[str], limit, marks: tuple[str, str]) -> list[dict]:
        """The indexed half of `search_content`."""
        rows = near_matches(words, table="content_file", keys=("object_id", "path"),
                            limit=limit)
        return [{"object_id": row["object_id"], "path": row["path"],
                 "hit": snippet_of(row, words, marks)}
                for row in rows]

    # --- one search, over all five -------------------------------------------

    def find(self, words: Sequence[str], *, limit: int = 200) -> list[dict]:
        """Every object whose name or whose own words hold all of these words.

        The one query behind the search box. It is one method rather than five
        because the answer is one list: a person looking for "laptop" wants the
        chat, the task and the run called that, ranked together, and five
        callers each asking their own table would have to be merged by whoever
        called them anyway.

        What "its own words" means is different for each of the five, and each
        of them is the text that already exists rather than a copy made for
        searching:

        * a **chat** is what was said in it, in `message`;
        * a **project** and a **task** are the files in their folders, through
          the derived content index (`content_file` and the search vector the
          database keeps of it) - the same index `search_content` reads;
        * a **run** is its brief and the line it is showing;
        * an **artifact** is the body of its head version.

        Every row comes back in the same shape, with `matched` saying whether
        it was the name or the words, because the name is the better hit and
        the caller ranks on it. `body` is text to cut a snippet from and is
        empty for a name match, which `first_words` fills in for the few rows
        that are actually going to be drawn.

        Nothing here is a scan of anything large. The four tables of names are
        a thousand rows between them on this machine, the messages and the
        artifact bodies about two megabytes, and the nineteen megabytes of
        indexed files - the only part big enough to matter - is asked through
        the full-text index.
        """
        words = [w for w in (words or []) if w]
        if not words:
            return []

        found: dict[tuple[str, str], dict] = {}

        def keep(kind: str, ident: str, matched: str, body: str = "") -> None:
            """First hit for an object wins, and a name beats its own words."""
            was = found.get((kind, ident))
            if was is None:
                found[(kind, ident)] = {"type": kind, "id": ident,
                                        "matched": matched, "body": body}
            elif was["matched"] == "body" and matched == "title":
                was["matched"] = "title"

        # The names. `slug` is in with the title for a project and a task
        # because the folder name is what a person half-remembers.
        for ident, kind in (tables.ObjectRow.objects.filter(_every(words, "title", "slug"))
                            .values_list("id", "type")):
            keep(kind, ident, "title")
        for kind in ("chat", "run", "artifact"):
            rows = _TABLE[kind].objects.filter(_every(words, "title"))
            if kind == "artifact":
                rows = rows.exclude(kind__in=UNSEARCHED)
            for ident in rows.values_list("id", flat=True):
                keep(kind, ident, "title")

        # Their own words. A run's brief and its line are columns of the run
        # rather than a body somewhere else, so they are asked here.
        for ident, brief, detail in (tables.Run.objects
                                     .filter(_every(words, "brief", "detail"))
                                     .values_list("id", "brief", "detail")):
            keep("run", ident, "body", f"{brief} {detail}")
        # What was said in a chat: the newest turn that matches, because a
        # conversation is read from where it got to.
        for chat_id, body in (tables.ChatMessage.objects.filter(_every(words, "body"))
                              .order_by("chat_id", "-seq").values_list("chat_id", "body")):
            keep("chat", chat_id, "body", body)
        # An artifact is its head version and never an older one: an older
        # body is not what opening it would show.
        for ident, body in (tables.ArtifactVersion.objects
                            .filter(version=F("artifact__head_version"))
                            .exclude(artifact__kind__in=UNSEARCHED)
                            .filter(_every(words, "body"))
                            .values_list("artifact_id", "body")):
            keep("artifact", ident, "body", body or "")

        # And the files, through the index that already exists for them. The
        # best hit for each object is its first, because that list comes back
        # ranked.
        best: dict[str, str] = {}
        for hit in self.search_content(" ".join(words), limit=limit * 4,
                                       marks=("", "")):
            best.setdefault(str(hit["object_id"]), str(hit.get("hit") or ""))
        if best:
            for ident, kind in (tables.ObjectRow.objects.filter(id__in=list(best))
                                .values_list("id", "type")):
                keep(kind, ident, "body", best[ident])

        return self._describe_found(found, limit)

    def _describe_found(self, found: dict[tuple[str, str], dict],
                        limit: int) -> list[dict]:
        """Put the row on each hit: its name, its clock, its pin, where it is.

        One query per type rather than one per hit, for the reason `decorate`
        in `owning.py` gives: a list is not a place to ask the same table three
        hundred separate questions.
        """
        want: dict[str, list[str]] = {}
        for kind, ident in found:
            want.setdefault(kind, []).append(ident)
        out: list[dict] = []
        for kind, idents in want.items():
            for row in _vals(_TABLE[_kind(kind)].objects.filter(id__in=idents)
                             .order_by("id")):
                hit = dict(found[(kind, row["id"])])
                hit.update(_SEARCH_ROW[kind](row))
                out.append(hit)
        return ranked(out)[:limit]

    def first_words(self, kind: str, obj_id: str, chars: int = 400) -> str:
        """The start of what this object says, for a row that matched its name.

        Asked only for the handful of rows that are about to be drawn, because
        it is one query each. Empty when the object has nothing to say, which
        is ordinary: a chat nobody has spoken in yet has no words.
        """
        kind = _kind(kind)
        if kind == "chat":
            body = (tables.ChatMessage.objects.filter(chat_id=obj_id).exclude(body="")
                    .order_by("seq").values_list("body", flat=True).first())
        elif kind == "run":
            body = tables.Run.objects.filter(id=obj_id).values_list("brief", flat=True).first()
        elif kind == "artifact":
            body = (tables.ArtifactVersion.objects
                    .filter(artifact_id=obj_id, version=F("artifact__head_version"))
                    .values_list("body", flat=True).first())
        else:
            # What the object says about itself, in preference to what it
            # built: a task's AGENTS.md or its step.md is a sentence about
            # the work, and the index.html beside it starts with the
            # page's own menu and its Print button.
            body = (tables.ContentFile.objects.filter(object_id=obj_id)
                    .annotate(note=Case(When(path__iendswith=".md", then=Value(1)),
                                        default=Value(0), output_field=IntegerField()),
                              path_length=Length("path"))
                    .order_by("-note", "path_length", "path")
                    .values_list("body", flat=True).first())
        return (body or "")[:chars]

    # --- the plumbing -------------------------------------------------------

    @contextlib.contextmanager
    def _writing(self):
        """The lock, and a transaction that is committed or rolled back.

        Every write goes through here. A statement that fails - a duplicate
        `seq`, a second owner, an upward link - rolls back everything the
        write had done before it, so a refusal costs nothing and leaves
        nothing. Called inside a transaction a caller already has, it is a
        savepoint of that one, and a refusal here rolls back only this write.
        """
        with self._lock, transaction.atomic():
            yield

    def _one(self, kind: str, obj_id: str):
        return _vals(_TABLE[_kind(kind)].objects.filter(id=obj_id)).first()

    def _set(self, kind: str, obj_id: str, fields: dict) -> bool:
        """Write whichever columns were actually given. True if a row changed."""
        _kind(kind)
        given = {name: _text(value) for name, value in fields.items()
                 if not isinstance(value, _Unset)}
        if not given:
            return False
        with self._writing():
            return _TABLE[kind].objects.filter(id=obj_id).update(**given) > 0

    def _there(self, kind: str, obj_id: str) -> bool:
        """Whether that object is here."""
        return _TABLE[_kind(kind)].objects.filter(id=obj_id).exists()

    def _must_be_there(self, kind: str, obj_id: str) -> None:
        """A link to something that is not here is a typo, and says so.

        The link table has no foreign keys - it cannot, with five tables at
        either end - so this is what stands in for one. Without it a mistyped
        id is a row nobody ever notices.
        """
        if not self._there(kind, obj_id):
            raise Refused(f"there is no {kind} {obj_id!r}")


def _as_flag(value):
    """A pin, an unread mark or an archive as the column keeps it, leaving UNSET alone."""
    return value if isinstance(value, _Unset) else bool(value)


def ranked(hits: list[dict]) -> list[dict]:
    """Search hits in the order the search box shows them.

    A name that matched before words that matched, because the name is the
    better hit; among each, the one worked on most recently first. One order
    for every kind of hit, so that a file the person uploaded ranks against a
    chat exactly as a task does (`rouh/searching.py`).
    """
    return sorted(hits, key=lambda h: (0 if h.get("matched") == "title" else 1,
                                       -(h.get("at") or 0.0)))


def near_matches(words: Sequence[str], *, table: str, keys: Sequence[str],
                 columns: Sequence[str] = (), where: str = "", params: Sequence = (),
                 limit=None) -> list[dict]:
    """Rows whose words match, best first, with the stretch of each round the match.

    For a table with a `body` and the `search` vector the database keeps of
    it: `content_file`, and `uploaded_file` (`rouh/uploads.py`). Every word of
    the query has to be in the body, cut into words the way the vector is.
    `keys` and `columns` are carried through to each row; `where` narrows the
    rows asked, with `params` for it. Every name here is one of this code's
    own and never anything a person typed.

    The match and the rank are one query. The snippet is not `ts_headline`,
    which reads the whole of every file it is asked about and took two seconds
    over a common word on this workspace: the query finds where the first word
    is and fetches a thousand characters around it (`near`, starting at
    character `near_from` of a body `size` long), and `snippet_of` cuts the
    words out of those.

    Every word has to have a letter or a digit in it (`indexable`), which is
    the caller's to check: a query of nothing but punctuation is not something
    the index can be asked.
    """
    query = " && ".join(
        ["phraseto_tsquery('simple', regexp_replace(%s, %s, ' ', 'g'))"] * len(words))
    query_params: list = []
    for word in words:
        query_params += [word, WORD_BREAKS]
    # Where the first of the words is, as a word: not in the middle of a
    # longer one. Each word's first run of letters and digits is enough to
    # find the place, and has nothing in it a pattern would read as more.
    firsts = [_WORD.search(w).group(0) for w in words]
    at = ", ".join(
        ["NULLIF(regexp_instr(body, %s, 1, 1, 0, 'i', 1), 0)"] * len(firsts))
    at_params = [f"(?:^|[^[:alnum:]])({first})(?:[^[:alnum:]]|$)" for first in firsts]
    carried = ", ".join([*keys, *columns])
    order = ", ".join(keys)
    top = _limit(limit)
    return _rows(
        f"SELECT {carried}, rank, size, GREATEST(at - %s, 1) AS near_from,"
        " substr(body, GREATEST(at - %s, 1), %s) AS near"
        f" FROM (SELECT {carried}, body, rank, length(body) AS size,"
        f"             LEAST({at}) AS at"
        f"       FROM (SELECT {carried}, body, ts_rank(search, q) AS rank"
        f"             FROM {table}"
        f"            CROSS JOIN (SELECT {query} AS q) AS asked"
        "             WHERE search @@ q" + (f" AND ({where})" if where else "") +
        f"             ORDER BY rank DESC, {order}"
        + (" LIMIT %s" if top is not None else "") +
        "            ) AS matched) AS placed"
        f" ORDER BY rank DESC, {order}",
        (_NEAR_BEFORE, _NEAR_BEFORE, _NEAR_LENGTH, *at_params, *query_params, *params,
         *([top] if top is not None else [])))


def snippet_of(row: dict, words: Sequence[str], marks: tuple[str, str] = ("", ""),
               near: str | None = None) -> str:
    """A few words round the match, out of one row `near_matches` gave back.

    `near` is that row's stretch of text again when the caller has tidied it
    first; it has to be the same length, so the ellipses still fall where the
    body was really cut.
    """
    wanted = {token.lower() for w in words for token in _WORD.findall(w)}
    text = (row["near"] or "") if near is None else near
    return _snippet(text, int(row["near_from"] or 1), int(row["size"] or 0), wanted, marks)


def _snippet(near: str, near_from: int, size: int, wanted: set[str],
             marks: tuple[str, str]) -> str:
    """A few words of a file around the first match, as FTS5's `snippet()` cut one.

    `near` is the stretch of the file the query fetched, starting at character
    `near_from` (counted from 1) of a file `size` characters long. The words
    are runs of letters and digits, the same words the index holds; the text
    between them is kept as it is. Twelve words, starting a little before the
    first one that matched, with `marks` round every word that matched and an
    ellipsis on whichever end stops short of the file's.
    """
    tokens = list(_WORD.finditer(near))
    if not tokens:
        return near[:200]
    first = next((i for i, token in enumerate(tokens)
                  if token.group(0).lower() in wanted), 0)
    start = max(0, first - 3)
    end = min(len(tokens), start + SNIPPET_WORDS)
    out: list[str] = []
    at = tokens[start].start()
    for token in tokens[start:end]:
        out.append(near[at:token.start()])
        word = token.group(0)
        if word.lower() in wanted:
            out.append(f"{marks[0]}{word}{marks[1]}")
        else:
            out.append(word)
        at = token.end()
    cut_before = start > 0 or near_from > 1
    cut_after = end < len(tokens) or near_from - 1 + len(near) < size
    return ((SNIPPET_ELLIPSIS if cut_before else "") + "".join(out)
            + (SNIPPET_ELLIPSIS if cut_after else ""))


# ---------------------------------------------------------------------------
# The one store this process uses
# ---------------------------------------------------------------------------
#
# One store, made on first use, shared by everything that reads or writes these
# tables. The house shape is one process writing through one lock, and two
# stores is two locks that know nothing about each other, which is a way of
# having a race nobody can see in the code.

_shared_lock = threading.Lock()
_shared: ObjectStore | None = None


def shared_store(*, even_when_off: bool = False) -> ObjectStore | None:
    """The store, or None when the model is off or the database will not answer.

    None rather than an exception: every caller has something else to do when
    the answer is no, and a store that cannot be opened must never be the
    reason a tool call or a page fails.

    `even_when_off` is for the conversations, and for them only. The flag turns
    the runs and the artifacts back onto the paths they were on before, and
    both of those still have one; a conversation has not had one since step
    three, so hiding this store from it would hide the person's chats rather
    than fall back to anything (`rouh/conversations.py`).
    """
    global _shared
    if not (enabled() or even_when_off):
        return None
    with _shared_lock:
        if _shared is not None:
            return _shared
        try:
            store = ObjectStore()
        except Exception:                                    # pragma: no cover
            log.exception("the object store would not open; carrying on without it")
            _shared = None
            return None
        _shared = store
        return _shared


def close_shared() -> None:
    """Forget the store, so the next caller makes a new one.

    A check of somebody's own, and a test world, need this. There is no file to
    let go of any more: the database connections are Django's.
    """
    global _shared
    with _shared_lock:
        if _shared is not None:
            try:
                _shared.close()
            except Exception:                                # pragma: no cover
                pass
        _shared = None
