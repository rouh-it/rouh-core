"""Which project a new task belongs in, decided by a small model.

Petar, 22 September 2026: "New tasks should be automatically sorted in my
folders. You can use a small model to do that. Haiku. To help with that, add a
description for each project including editing and creating. This description
will help with classification."

So a task that nobody filed is filed here, the moment it is made:

    a new task  ->  every project and what it is for  ->  the one it goes in

**The person's own words are what decides it.** Each project carries a
description they wrote (`project.description`, edited in Manage projects on the
task browser), and that sentence is the whole of what the model is given about
that project, beside its name and which column it is in. A project nobody has
described is still offered - its name is often enough - and the point of the
field is that "Buy" and "Misc" stop being a coin toss.

**Nothing is guessed, and nothing is left nowhere.** The model answers with one
project's folder or with `none`, and anything else - an answer that names no
project, an answer that is a sentence, a model that is not configured, one that
is overloaded, one that is slow - ends in the same place: `fallback` below,
which is Miscellaneous. That is new on 23 September 2026 and it replaced
leaving the task in `unfiled/` under a **Not sorted** heading at the top of the
task browser, because Petar asked for that heading gone: "We should not have a
section called Not sorted. The AI should be sorting whether a task is in one
project or another. The projects themselves are manually defined by me."

He did not say where a task the model cannot place should go, so this is the
choice made on his behalf, written down here so it can be changed in one line:
**it goes to Miscellaneous** (`config.filing_fallback`), which is the project
that already means "somewhere, not nowhere", and one drag puts it right. The
alternative - a bucket on the screen for work nobody has filed - is the thing
he asked to be rid of.

Whatever happens here, the task exists and is on the board: filing runs after
the task is made and never in front of it.

**Miscellaneous is not a decision, it is where a task waits.** So a task the
fallback placed is offered to the model again if it is asked about twice, and
the person dragging it somewhere else is the ordinary end of it.

**It is only ever the first word.** The task keeps its own line in the browser
and every way of moving it by hand still works - the drag onto a project
button, the move menu, Manage projects - so a filing the person disagrees with
costs them one drag.

**Only what the person has not already decided.** A task made inside a project,
or promoted out of a chat that was already filed under one, is never asked
about: somebody has said where that belongs.

**And the person saying where is not a thing to be sorted at all.** Petar, 24
September 2026, after "put those in a new task, Team Messaging, part of Acme
project" made task 61 in `unfiled/` and left this model to move it a minute
later: it should have been made in the right place from the start. So a
project named out loud is found here (`find`), by its name or its path, among
the projects that really exist, and the task is made inside it or moved into
it at once. A name that fits no project, or more than one, is said back to the
model with the list, and nothing is made: guessing is this model's job and
only when nobody said. A task placed that way is never asked about afterwards,
even when the place is Miscellaneous (`placed_by_person`).

Which model. The one the Models page has for filing, either company's
(`rouh/llm.py`); the standard starts it on Cheaper, because this is a labelling
job and not a piece of thinking.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from dataclasses import dataclass

log = logging.getLogger("rouh.filing")

#: How long the model may take to file one task. Nobody is waiting on it - the
#: task is already made, already numbered and already on the screen - but a
#: request that never comes back would hold a filing open for ever, and the
#: fallback is a perfectly good answer.
TIMEOUT = 20.0

#: How much of a project's description the model is given. A description is a
#: sentence or two about what belongs in a project; anything past this is
#: somebody using the field for something else, and it is read, not obeyed.
MAX_DESCRIPTION = 600

#: And how much of what the task is about. The title first, then the start of
#: the conversation it came out of where there was one. A pasted stack trace
#: files no better for having been read whole.
MAX_ABOUT = 1200

#: What the model answers when nothing fits. Written down because it is the
#: answer that matters most: `fallback` below is the safe end of this.
NOTHING = "none"

SYSTEM = """You file new work into projects, and you answer with one line and nothing else.

You are given a piece of work and the list of projects it could be filed under.
Each project is one line:

    <folder> | <column> | <name> | what belongs in it, in the owner's words

Answer with the folder of the one project the work belongs in, exactly as it is
written in the list, and nothing else. No sentence, no reasoning, no quotation
marks, no markdown.

Answer `none` if no project is a good home for it. `none` is a real answer and
often the right one: the work then goes to the owner's catch-all project, where
they will see it and can file it themselves, which is far better than it being
put somewhere they will not look. Do not stretch to make something fit.

What decides it is what the owner said the project is for. Where they said
nothing, the project's name is all there is, and a name that plainly covers the
work is enough. Where two fit, take the more specific."""

#: What the model is asked, with the work and the projects under it.
ASK = """The work:

{about}

The projects:

{projects}

Answer with one folder from that list, or `none`."""


@dataclass(frozen=True)
class Choice:
    """One project a task could be filed into, as the model is shown it."""

    id: str
    #: Where it is in the workspace, which is what the model answers with:
    #: unique by construction, and readable in a log afterwards.
    folder: str
    name: str
    #: The top-level project it sits under - Work, Personal - which is context
    #: for the model and is never the answer: a task is filed into a project
    #: inside a column, never into the column itself.
    column: str
    description: str = ""
    #: When the project was made, which is what settles which of two projects
    #: with the same name is the fallback (`fallback`). Never shown to the model.
    created_at: float = 0.0

    def line(self) -> str:
        said = " ".join((self.description or "").split())[:MAX_DESCRIPTION]
        return f"{self.folder} | {self.column} | {self.name} | {said}"


def choices(store, *, for_tasks: bool = True) -> list[Choice]:
    """Every project a new task may be filed into, with what it is for.

    A project inside a column, and it must be a folder. That is exactly what
    the task browser draws as a button and what a task can be dragged onto
    (`objectindex.index_data`): a top-level project is a column and not one of
    the person's projects, and a project with no folder is one of their own for
    filing chats, which has nowhere for a task's folder to go.

    `for_tasks=False` drops that last condition and nothing else, for a caller
    that is not filing a task. A kept note goes in a project by its id and not
    by its folder (`rouh/keeping.py`), so one of the person's own projects for
    chats holds one perfectly well. A column is still not a project either way.
    """
    if store is None:
        return []
    rows = {row["id"]: row for row in store.objects() if row["type"] == "project"}
    owner: dict[str, str] = {}
    for _src_type, src_id, dst_type, dst_id in store.owns_edges():
        if dst_type == "project" and dst_id in rows and src_id in rows:
            owner[dst_id] = src_id
    said = store.descriptions()

    def column_of(ident: str) -> str:
        seen = 0
        while ident in owner and seen < len(rows):
            ident = owner[ident]
            seen += 1
        row = rows.get(ident)
        return (row["title"] or row["slug"] or "") if row else ""

    out = []
    for ident, row in rows.items():
        if ident not in owner or (for_tasks and not (row.get("folder") or "")):
            continue
        out.append(Choice(id=ident, folder=row["folder"],
                          name=row["title"] or row["slug"] or ident,
                          column=column_of(ident),
                          description=said.get(ident, ""),
                          created_at=float(row.get("created_at") or 0.0)))
    # In the order the task browser draws them, Work before Personal, so the
    # list the model reads is the list the person sees (`objectindex.COLUMNS`,
    # which is where that order is written down and argued).
    from .objectindex import COLUMNS

    def where(one: Choice) -> tuple:
        column = one.column.lower()
        return (COLUMNS.index(column) if column in COLUMNS else len(COLUMNS),
                column, one.name.lower())

    out.sort(key=where)
    return out


def fallback(offered: list[Choice]) -> str:
    """The project a task goes in when nothing else decided. "" for none.

    `config.filing_fallback` names it by folder - `misc` - and it is matched
    against each project's folder first and then against its name, so the
    person renaming Misc to Miscellaneous in Manage projects keeps it working
    and so does moving it to the other column.

    **Where two projects answer to it, the one made first is the fallback.**
    A folder is named for its project, so a second Misc made in the other
    column is a second `misc`, and until 25 September 2026 the first of them
    in the order the browser draws them won - Work before Personal - so making
    Misc under Work, which Petar asked for in fr_a943e8b83fe8, quietly made it
    the place every task nobody filed went, personal ones included. The one
    that was there first is the one that has been Miscellaneous all along, and
    a project made later with the same name is a project of its own and not a
    new home for everything else. Two made in the same instant, which only an
    import can do, go by folder so the answer is the same on every call.

    "" is a real answer and means this workspace has no project to fall back
    on. It happens on a machine with no projects at all, and there the task
    stays where it landed, because putting it somewhere would mean inventing a
    project nobody asked for.
    """
    from .config import config

    want = " ".join(str(config.filing_fallback or "").split()).lower().strip("/")
    if not want or not offered:
        return ""

    def first(ones: list[Choice]) -> str:
        return min(ones, key=lambda one: (one.created_at, one.folder)).id

    by_folder = [one for one in offered
                 if one.folder.lower().strip("/").split("/")[-1] == want]
    if by_folder:
        return first(by_folder)
    by_name = [one for one in offered if one.name.lower() == want]
    if by_name:
        return first(by_name)
    log.info("no project is named %r, so there is nothing to fall back on", want)
    return ""


def where_it_goes(store) -> str:
    """The fallback project's id for a caller that has no list yet. "" for none."""
    return fallback(choices(store))


# ---------------------------------------------------------------------------
# A project the person named out loud
# ---------------------------------------------------------------------------


#: Tasks whose project the person named themselves, since this process started.
#: The model above is never asked about one of them, not even when the project
#: they named is the fallback: "put it in Misc" is a decision, and Miscellaneous
#: being where undecided work waits is exactly why that needs saying. In memory
#: because the model is only ever asked in the minute after a task is made
#: (`runtime.NewTasks`), and a restart asks nothing about old tasks.
_placed: set[str] = set()


def placed_by_person(task_id: str) -> None:
    """Remember that the person said where this task belongs."""
    if task_id:
        _placed.add(task_id)


def was_placed_by_person(task_id: str) -> bool:
    return task_id in _placed


@dataclass(frozen=True)
class Named:
    """What a project named out loud turned out to be.

    `choice` is the one project it names, or None; `why` is then the sentence
    for the model, which says what was wrong and which projects there are.
    """

    choice: Choice | None
    why: str = ""


def _key(said: str) -> str:
    """A name as it is compared: letters and digits, lower case, nothing else.

    So "ACME" is "Acme", "Acme Co" is "AcmeCo" and "acme-co" is the folder
    `acmeco`. That is spelling, not guessing: two names that differ only in
    their capitals and spaces are the same name said aloud. Nothing looser is
    matched - not a prefix, not a part of a word - because a near miss filed
    into the wrong project is the thing this exists to stop.
    """
    return re.sub(r"[^0-9a-z]+", "", (said or "").lower())


def _segments(said: str) -> list[str]:
    """A name or a path as the keys it is made of, outermost first.

    "Acme" is one; "work/acme", "Work > Acme" and
    "workspace/work/acme/" are two.
    """
    text = " ".join(str(said or "").split()).strip().strip("/")
    if text.lower().startswith("workspace/"):
        text = text[len("workspace/"):]
    return [key for key in (_key(part) for part in re.split(r"[/>›»]", text)) if key]


def _said_as(one: Choice) -> str:
    """One project, named the way the model is asked to say it back.

    Its folder in brackets, because the folder is what an answer names and is
    unique; nothing in brackets for one of the person's own projects for
    chats, which has no folder at all (`choices` with `for_tasks=False`).
    """
    return f"{one.name} ({one.folder})" if one.folder else one.name


def _listing(offered: list[Choice]) -> str:
    """Every project a task can go in, by column, as one sentence to read."""
    columns: dict[str, list[str]] = {}
    for one in offered:
        columns.setdefault(one.column or "Other", []).append(_said_as(one))
    return "; ".join(f"{column}: {', '.join(names)}" for column, names in columns.items())


def find(store, project: str, category: str = "", *, for_tasks: bool = True) -> Named:
    """The project the person named, among the projects that really exist.

    `project` is what they called it - a name such as Acme, Clients or Health,
    or its path in the workspace such as `work/acme` - and `category` is
    the column it sits in, Work or Personal, for when the name alone could be
    two projects. A path's parts and the category are matched from the project
    upwards, each against a project's title and its folder's name, so
    "Personal" in Personal and "private/personal" both find the project
    `private/personal` and nothing else.

    Only a project a task can live in is an answer, which is exactly the list
    the filing model is shown (`choices`): a column is not one, because a task
    straight under Work is in no project and is tidied into the fallback
    (`objecttree.tidy`); and a project for chats has no folder for a task to
    be written into. Naming either is said back with what to do instead.

    `for_tasks=False` is for a caller that is not filing a task and lets a
    project with no folder be the answer (`choices`).
    """
    said = " / ".join(part for part in (" ".join(str(category or "").split()),
                                        " ".join(str(project or "").split())) if part)
    want = _segments(category) + _segments(project)
    offered = choices(store, for_tasks=for_tasks)
    if not want:
        return Named(None, "No project was named.")
    if store is None or not offered:
        return Named(None, "There are no projects in the workspace on this machine, "
                           "so there is nowhere to put it.")
    rows = {row["id"]: row for row in store.objects() if row["type"] == "project"}
    owner: dict[str, str] = {}
    for _src_type, src_id, dst_type, dst_id in store.owns_edges():
        if dst_type == "project" and dst_id in rows and src_id in rows:
            owner[dst_id] = src_id

    def names(row: dict) -> set[str]:
        folder = str(row.get("folder") or "")
        return {key for key in (_key(row.get("title") or ""), _key(row.get("slug") or ""),
                                _key(os.path.basename(folder))) if key}

    def fits(ident: str) -> bool:
        if want[-1] not in names(rows[ident]):
            return False
        at, rest, seen = owner.get(ident), list(want[:-1]), 0
        while rest and at is not None and seen < len(rows):
            if rest[-1] in names(rows[at]):
                rest.pop()
            at, seen = owner.get(at), seen + 1
        return not rest

    found = [ident for ident in rows if fits(ident)]
    by_id = {one.id: one for one in offered}
    good = [by_id[ident] for ident in found if ident in by_id]
    if len(good) == 1:
        return Named(good[0])
    if len(good) > 1:
        return Named(None, (
            f"“{said}” fits {len(good)} projects: "
            + ", ".join(f"{one.name} in {one.column}"
                        + (f" ({one.folder})" if one.folder else "") for one in good)
            + ". Ask which one they mean, then give its path, such as "
            f"{good[0].folder or good[0].name}."))
    for ident in found:
        row = rows[ident]
        if ident not in owner and row.get("folder"):
            inside = [one for one in offered
                      if one.folder.startswith(f"{row['folder']}/")]
            return Named(None, (
                f"{row['title']} is a column, not a project: a task goes in one of "
                "the projects inside it, which are "
                + (", ".join(_said_as(one) for one in inside) or "none")
                + ". Ask which one they mean."))
        if for_tasks and not row.get("folder"):
            return Named(None, (
                f"{row['title']} is one of their projects for chats and has no folder "
                "in the workspace, so a task cannot go in it. The projects a task can "
                f"go in are these - {_listing(offered)}. Ask which one they mean."))
    if _segments(category) and _segments(project):
        elsewhere = find(store, project, for_tasks=for_tasks)
        if elsewhere.choice is not None:
            one = elsewhere.choice
            return Named(None, (
                f"{one.name} is in {one.column} ({one.folder}), not in "
                f"{' '.join(str(category).split())}. Ask whether that is the one they "
                "mean."))
    return Named(None, (
        f"No project is called “{said}”. The projects are these - "
        f"{_listing(offered)}. Ask which one they mean, or leave the project out."))


def about_text(title: str, said: str = "") -> str:
    """What the task is, as the model is asked about it.

    The title is the task, and the start of the conversation it came out of is
    what the title was shortened from: a task called "Research" says nothing
    on its own, and the first exchange of its chat is what it was shortened
    from.
    """
    title = " ".join((title or "").split())
    lines = [f"Title: {title}" if title else "Title: (none)"]
    said = (said or "").strip()
    if said:
        lines.append("")
        lines.append("What was said about it:")
        lines.append(said[:MAX_ABOUT])
    return "\n".join(lines)


def read_back(raw: str, offered: list[Choice]) -> str:
    """The model's answer as one project id, or "" for no project at all.

    "" is every failure and also one success: `none`, which is the model saying
    this belongs nowhere yet. Both leave the task where it is, so they need not
    be told apart here.

    A model asked for one word answers with one word, and sometimes with a
    sentence round it or a fence over it. So the first non-empty line is taken,
    the wrapping that shows up in practice is stripped, and what is left is
    matched against the folder it was asked to answer with and then against the
    project's name. Nothing is matched loosely: a half-recognised answer would
    file work somewhere nobody chose.
    """
    line = ""
    for candidate in (raw or "").replace("\r", "").split("\n"):
        candidate = candidate.strip()
        if candidate:
            line = candidate
            break
    for lead in ("- ", "* ", "#", "`"):
        while line.startswith(lead):
            line = line[len(lead):].strip()
    line = line.strip("`").strip().strip("\"'“”‘’").strip()
    line = line.rstrip(".").strip()
    # Only ever the folder, so a model that answered the whole line it was
    # shown is still understood.
    line = line.split("|")[0].strip()
    if not line or line.lower() == NOTHING:
        return ""
    low = line.lower().strip("/")
    for one in offered:
        if one.folder.lower().strip("/") == low:
            return one.id
    for one in offered:
        if one.name.lower() == low or one.id.lower() == low:
            return one.id
    log.info("the filing model answered %r, which names no project it was offered", line)
    return ""


async def choose(about: str, offered: list[Choice], *, subject: str = "") -> str:
    """Ask which project this work goes in. The project's id, or "".

    Asked of the model the Models page has for filing, whichever company's it is
    (`rouh/llm.py`). Never raises: every way of not getting an answer is the same
    answer, which is that the task stays where it is.
    """
    from . import llm

    if not offered or not about.strip():
        return ""
    asked = ASK.format(about=about,
                       projects="\n".join(one.line() for one in offered))
    try:
        got = await llm.ask("filing", system=SYSTEM, messages=asked, max_tokens=64,
                            subject=subject, timeout=TIMEOUT, read_only=True)
    except asyncio.CancelledError:
        raise
    except Exception as exc:                      # noqa: BLE001 - never worth an error
        log.warning("the filing model could not be asked (%s); "
                    "the task is left where it is", exc)
        return ""
    return read_back(got.text, offered)
