"""Goals: working out how to reach something, and then doing the steps.

Petar, 27 September 2026, the first time he had a real goal to put in:

    "Goals should be mostly about designing the plan and action and analyzing
    difficulties and who will do them and how and helping with the
    difficulties ... The goal will essentially become one task with a
    label/Tag Goal (not folder) and will have its sub tasks and sub-sub-tasks
    just the same as our system is designed ... the value of this section is
    to organize/invent the path/journey steps, and try to do as much as
    possible of the easy ones and try to help as much as possible with the
    difficult ones."

Until then a goal was a count - five times a week, twenty pages a day - with a
check-in reminder, a row of its own in a table of its own (6c601a1). That is
gone (migration 0033). What a goal is now:

- **One numbered task, tagged.** Its meta (`rouh/taskmeta.py`) carries `"tags": ["goal"]`
  and a `"goal"` block: the stage it is at, why it needs help rather than just
  being done, and the chat it is worked out in. It is filed under a project
  like any task, found in the task browser like any task, and opened like any
  task. `TAG` is the one word, and `is_goal` the one test of it.
- **What the person knows about it is `goal.md`** in its folder, in their own
  words, written once when it is made. It is a file of the task's, so it is on
  the task's own page, in git and in grep.
- **The plan is its subtasks**, and a step's own parts are sub-subtasks, made
  through `objecttree.create` like any other. What makes one a step of a plan
  is a `"goal_step"` block in its meta: who does it, how, the hard part
  and what to do about it, and when Rouh should do it (`run`).
- **It has one chat, its own**, owned by the task, titled with a target. The
  first thing in it is Rouh reading what the person wrote and asking what it
  needs to know - including why this is a goal they need help with - and
  `plan_goal` is how Rouh then writes the plan (`tools.py`). It is the only
  chat a goal ever has (see the streams, below).

A step Rouh can do is done now, at a time, or after another step is done
(`RUN_MODES`). "Now" is a background run of its own (`brief_for_step`,
`timekeeper.do_step`); "at" is a reminder of kind `do` in the goal's chat
(`rouh/reminders.py`), whose turn starts that run when it is due; "after"
waits here and is started the moment the step it waits on is marked done
(`timekeeper.step_status`).

A step is complete when what it is for has happened. Petar, 27 September
2026 (fr_a5668026d08d): "a step to be completed, means two things: Rouh did
its job, but then the step is completed as part of the journey to the goal ...
Research the best tool to transcribe ... task is complete only where the
software has been chosen". So a step whose real deliverable is his - a
decision, or an action only he can take - is not complete when Rouh's part
of it is: it waits on him (`ROUH_DONE`), with what is left for him, until he
has done it.

And nothing else waits on him. Petar, 4 October 2026 (fr_5404edbbea30): "the
goals are so setup that after each step rouh does it requires my approval and
confirmation. Please remove that. If rouh feels it did the job, I don't have
to approve it or check it. I only should make decisions or actions rouh can't
do. Not verify work". So when Rouh says its part is done and nothing is left
that only he can decide or do, the step is complete (`done_by` "rouh"), the
count goes up and the steps after it start, with no Mark complete asked of
him; there is no such thing as a step asking him to review Rouh's work
(`KINDS`). When Rouh cannot tell whether a step worked, it says so and why,
and the step waits on him as stuck, never as a check. He can still Reopen a
step, or have Rouh do it again, if he does not like what it did.
A step may say what has to be true for it to be complete (`outcome`).

A goal has a page of its own (`PAGE`, drawn by `goalpage.js`), and its task's
page lists it as one thing among its chats and subtasks. Petar, 27 September
2026 (fr_b083c37a634d): "the homepage should remain with list of things
(chats, subtasks, etc), and just like HTML can be clicked the goal can be
clicked to go to the specialized page ... manage things that can go in
parallel streams ... at every stream I should see that it is waiting on me to
unblock it - decision or action that AI can't take." So the steps are laid
out in **streams** (`STREAMS`): each an order of steps that follow one
another, and the streams side by side, going on at the same time. Rouh
proposes them when it plans (a step's `stream`), and the person moves steps
between them and within them on the goal's page (`arrange`). A stream's
first step not yet complete is where it stands (`stream_view`): Rouh on it,
Rouh able to go on by itself, or waiting on the person, with what it needs
from them and what has been prepared for it.

The streams really do go on at the same time. Petar, 27 September 2026
(fr_a25fe6a202a3), looking at a plan that sat waiting for him to say go:
"whatever the plan, should start executing in parallel all tasks that are in
different streams. Basically streams are groups that are not blocking each
other and can work in parallel." So the moment a plan is written, every
stream whose next step Rouh can take up (`can_start`) is started, side by side
(`timekeeper.start_streams`); a stream whose next step only the person can
take waits on them. Inside a stream the steps still follow one another: the
next is started once the one before is complete.

A goal has exactly one chat, and a stream is never one. For an afternoon on
27 September 2026 every stream was worked in a chat of its own, because turns
in one chat follow one another; goal 67's sidebar filled up with chats that
looked like one per subtask. Petar, the same day: "the main chat is the one
for the entire goal. each stream or tasks should be managed by the system,
and be executed in parallel runs and result most of the times in visual
explainer htmls + decisions and actions I have to do." So a step Rouh takes
up is a background run like any job (`starting.start`, the assistant's
preset), owned by the goal's task, drawn on the orb, reporting to the goal's
chat, and the streams go on side by side because runs do. What a run is asked
for (`brief_for_step`) is a visual explainer page in the step's own folder
(`EXPLAINER`), which is the step's result on its own page, and, where it
needs him, the decision (what is decided, the options) or the action that is
his (`read_step_result`). When it finishes (`run_finished`) that is what the
goal's page and the step's page show as waiting on him, and one short line in
the goal's own chat says what finished and what now needs him. Nothing is
drawn as cards in a chat for it. The stream chats made that afternoon are
kept, readable under the goal on its task's page and out of the chat list
(`retire_stream_chats`); nothing new is written to `STREAM_CHATS`.

The words and numbers the page draws are worked out here, once, so the page and
what Rouh is told about a goal cannot disagree.
"""
from __future__ import annotations

import asyncio
import contextlib
import contextvars
import copy
import json
import logging
import re
import time
from datetime import date
from pathlib import Path

from . import owner, protected, workspace_repo

log = logging.getLogger("rouh.goals")

#: The tag that makes a task a goal. Written into its meta as `tags`.
TAG = "goal"

#: Where a goal is. Understanding: Rouh has read it and is asking. Planned: it
#: has steps.
STAGES = ("understanding", "planned")

#: A step's own status, the workspace's words for it (`taskrecord.STATUSES`, less stopped).
STATUSES = ("not-started", "in-progress", "waiting", "done")

#: Other words for a status, as a model might say it.
STATUS_WORDS = {"started": "in-progress", "doing": "in-progress", "todo": "not-started",
                "blocked": "waiting", "finished": "done", "complete": "done"}

#: In a step's `goal_step` block: Rouh has done its part and the step waits on
#: the person for a decision or an action only they can take - {"at": seconds,
#: "left": words}. Never for a look over Rouh's work (fr_5404edbbea30).
ROUH_DONE = "rouh_done"

#: Who does a step. Anybody else is named in their own words ("An accountant").
#: "Together" alone was the page's word for the third until 27 September 2026,
#: and Petar could not tell what it meant (fr_89eebb50bd23): "I dint understand
#: what together means. Whatever it is, I have no way to follow through." So
#: it names both of them, and `WHO_MEANS` says what that asks of him.
#:
#: The fourth is a quest's (`rouh/quests.py`), for a goal whose task also
#: carries one. Petar, 6 October 2026, of quest 89: "please make a goal for
#: this quest. it is hard to organize like that and also for me to track and
#: understand and support". The quest's own beats do the work; the goal lays
#: it out beside his decisions so he can follow it. So a step of the quest's
#: is never started as a run of the goal's (`can_start`, `timekeeper.do_step`),
#: which would be a second executor beside the quest, and asks nothing of him.
QUEST = "quest"
#: The person whose goal it is. Written "owner" since 20 October 2026; a step
#: written before says "petar", which is read as "owner" (`held_who`).
OWNER = "owner"
WHO = {"rouh": "Rouh", OWNER: "You", "together": "You and Rouh", QUEST: "Rouh's quest"}

#: What each of those means for the person, beside the name on a step's page
#: and in its tooltip on the Goals page, with the way to act on it.
WHO_MEANS = {
    "rouh": "Rouh does it by itself: now, at a time you pick, or once another step is "
            "complete. When Rouh has done it, it is complete; nothing is asked of you.",
    OWNER: "This one is yours to do. Mark it complete when it is, and Rouh starts "
             "anything that was waiting on it.",
    "together": "You and Rouh do this one together. Start it with Rouh: Rouh does its part "
                "in the background and asks you only for the decision or action that is "
                "yours.",
    QUEST: "Rouh's quest does this one, in the beats the heartbeat gives it, inside the "
           "quest's own budget and rules. The goal never starts it by itself; the quest "
           "marks it complete when it is done, and nothing is asked of you.",
}

#: The same, as Rouh reads it in the plan, where "You" would be Rouh itself.
WHO_FOR_MODEL = {"rouh": "done by you, Rouh", OWNER: "done by the person",
                 "together": "done by the person and you together",
                 QUEST: "done by the quest this goal's task carries, in its own beats; "
                        "never started as a run for the goal"}

#: How Rouh gets to a step it can do.
RUN_MODES = ("now", "at", "after")

#: What a step asks of the person, in its `goal_step` block as `kind`, with
#: `ask` saying it in a line and, for a decision, `options` to choose from.
#: Petar, 27 September 2026 (fr_14155d5f5e95), of step 67-02, the research
#: into ways to capture meetings, which asked him to "Look at what Rouh made
#: and say whether this step is complete": "this is wrong. I shouldn't just
#: read the research. I should pick a software to capture our voice meetings.
#: that is a decision, not just action ... you should be very careful whta the
#: deliverable on each step is". So a step says which it is: something he
#: does, or something he decides. A third kind, Rouh's work he looks over
#: ("review"), was taken out on 4 October 2026 (fr_5404edbbea30): "I only
#: should make decisions or actions rouh can't do. Not verify work". A step
#: that asks nothing of him has no kind, and an old step of kind review reads
#: as one that asks nothing (`_kind`).
KINDS = ("action", "decision")

#: What each kind is called where the step says what it needs from him.
KIND_LABELS = {"action": "Your action", "decision": "Your decision"}

MAX_OPTIONS = 8

ABOUT_FILE = "goal.md"

#: A goal's own page is its `goal.md`, opened: the one thing on the task's
#: page that is the goal, as a page Rouh built is its page. At that address
#: the goal is drawn whole rather than the file read (`objectindex.goal_page`).
PAGE = ABOUT_FILE

#: A step's explainer: what Rouh does in it with what it made, and what the
#: person does with where and how, as a page rather than a Markdown file.
#: Petar, 27 September 2026 (fr_e2dde690a576): "html explainer page in this
#: subtask. currently. i am getting md file, which I don't like". A page Rouh
#: wrote into the step under this name is it; otherwise it is drawn fresh
#: from the step at its folder's `EXPLAINER_DOC` (`objectindex.step_explainer`).
EXPLAINER = "explainer.html"
EXPLAINER_DOC = "explainer"

#: A step's How to do it page: what the person does, with inputs of their own
#: and Mark as complete, apart from Rouh's research (`objectindex.step_yours`).
#: Petar, 27 September 2026 (fr_6acc50075110): "both buttons RESULTS and HOW
#: do to it lead to the same page. the page is the research of Rouh. So
#: "results" is correct. How to do it, should be an entirely different HTML
#: page that has instructions and inputs for me. that's where "Mark as
#: complete" should be if I don't want to do anything."
YOURS_DOC = "your-part"

#: In a step's `goal_step` block: what the person wrote on that page, and the
#: option they picked for a decision (`change_step`).
NOTE = "your_note"
CHOICE = "your_choice"
MAX_NOTE = 4000

#: In a step's `goal_step` block: the person's part as steps to take, in
#: order, each {"text", "done"}, ticked one by one on the How to do it page
#: (`tick_your_step`). Petar, 28 September 2026 (fr_84b6c5266a52), on that
#: page of a step where he sets a tool up himself: "for stuff like that I need
#: step by step instructions on all the points. and ability to check
#: "complete" on each step." Written by Rouh (`goal_step` your_steps, or a
#: step's run under `RESULT_STEPS`); ticking every one does not complete the
#: step, which stays his own Mark as complete.
YOUR_STEPS = "your_steps"
MAX_YOUR_STEPS = 30
MAX_YOUR_STEP = 600

#: In the goal block: its streams, in order, each {"id", "name", "steps"},
#: steps being the ids of its top-level steps in the order they follow.
STREAMS = "streams"

#: In the goal block, from 27 September 2026 only: the chat each stream was
#: worked in, {stream id: chat id}. Nothing writes it any more; it is read once,
#: to take those chats out of the chat list (`retire_stream_chats`), and cleared.
STREAM_CHATS = "stream_chats"

#: In a step's `goal_step` block: the background run last started on it, and
#: whose it was (a user id), so its end finds the step (`step_of_job`).
JOB = "job"

#: In the goal block: the person paused it, {"at": seconds}. Asked for on 2
#: October 2026, after reading how OpenAI's Dots are controlled: a goal is a
#: responsibility Rouh carries on with between conversations, so the person
#: can hold it - nothing starts by itself until they resume it - and steer it.
PAUSED = "paused"

#: In the goal block: the person's redirect, {"text", "at"}: what they want
#: done differently from now on, told to every run started after it.
DIRECTION = "direction"
MAX_DIRECTION = 1200

#: What Rouh may do for a goal, as the goal's page says it under Where it
#: stands. Not a setting: each line is a rule enforced elsewhere, and read
#: here so the page cannot claim more or less than the code does. A turn
#: nobody started may do anything but two groups (`rouh/protected.py`); a
#: step's run is told the same two (`brief_for_step`, `protected.WORDS`);
#: and a step whose deliverable is the person's decision or action waits on
#: them (`ROUH_DONE`).
BOUNDARIES = (
    {"key": "alone", "label": "By itself",
     "words": "Research, use your connected apps, send mail as Rouh, change the calendar, "
              "share and publish, as background runs owned by this goal, and plan the next "
              "steps. It tells you everything it did."},
    {"key": "asks", "label": "Hands to you",
     "words": "Paying, buying, booking, submitting a form or an application, or signing up: "
              "it gets it ready to that step, hands it to you and tells your phone."},
    {"key": "yours", "label": "Never by itself",
     "words": "Deleting anything for good, changing Rouh itself, its rules or permissions, "
              "signing in, codes and card details, and the decisions that are yours. A step "
              "Rouh has done is complete without asking you."},
)

#: What a goal's one stream is called before anybody has split it.
FIRST_STREAM = "The plan"

MAX_STREAMS = 8
MAX_STREAM_NAME = 40
MAX_NAME = 120
MAX_ABOUT = 20000
MAX_FIELD = 1200
MAX_STEPS = 12
MAX_PARTS = 8


class Refused(ValueError):
    """A sentence to say back, rather than a goal half made."""


# --- where things are -----------------------------------------------------------


def _store():
    from . import owning

    return owning.store()


def _root() -> str:
    from . import owning

    return owning._workspace()


#: Every task's meta by folder, read once for the length of a `listing` (`_metas_read_once`).
_METAS_NOW: contextvars.ContextVar[dict | None] = contextvars.ContextVar("rouh_goal_metas", default=None)


@contextlib.contextmanager
def _metas_read_once():
    """Inside this, `_meta` answers from one read of every task's meta (`metas_at`) rather than
    with three queries a task: the goals listing, which reads nothing but writes nothing either,
    read some 240 of them for four goals, and the system prompt asks for it every turn
    (23 October 2026). A folder no row names is read on its own as before."""
    if _METAS_NOW.get() is not None:
        yield
        return
    from .models import Task

    try:
        found = metas_at(Task.objects.exclude(folder="").values_list("folder", flat=True))
    except Exception:  # noqa: BLE001 - one at a time still answers
        log.exception("every task's meta could not be read at once")
        found = None
    token = _METAS_NOW.set(found)
    try:
        yield
    finally:
        _METAS_NOW.reset(token)


def _meta(folder: Path) -> dict:
    """A goal's or a step's meta (`rouh/taskmeta.py`), with its
    status as its row says it.

    The status is the row's, never the meta's (`rouh/taskrecord.py`): it is put
    in under "status" here so everything below reads a step as one dict, and
    `_write_meta` takes it out again on the way back and hands it to the row.
    """
    from . import taskmeta, taskrecord

    root = _root()
    known = _METAS_NOW.get()
    if known is not None and root:
        # By its words, without asking the disk: the folders asked about here are the
        # workspace's own, written as the root and the row's folder (`_folder`).
        base, said = str(root).rstrip("/") + "/", str(folder)
        rel = said[len(base):].strip("/") if said.startswith(base) else ""
        if rel in known:
            return copy.deepcopy(known[rel])
    body = taskrecord.strip(taskmeta.get(folder, root or None))
    said = taskrecord.status_at(folder, root) if root else ""
    if said:
        body["status"] = said
    return body


def metas_at(folders) -> dict[str, dict]:
    """`_meta` for many workspace folders at once, by folder, in one query: for each, the row
    `taskmeta.task_id` would find (the newest made with that folder), its meta without the
    status and the status as the row says it. A folder no row names is not in the answer, and
    is read with `_meta`, by its `.object.json`. The decisions read every waiting and every
    finished task this way, which was three queries a task - 864 of them on every task page
    opened on the first Rouh (23 October 2026)."""
    from . import taskrecord
    from .models import Task

    wanted = [f for f in dict.fromkeys(str(f or "").strip().strip("/") for f in folders) if f]
    if not wanted:
        return {}
    out: dict[str, dict] = {}
    for row in (Task.objects.filter(folder__in=wanted).order_by("folder", "-created_at", "id")
                .values("folder", "meta", "status")):
        if row["folder"] in out:
            continue
        body = taskrecord.strip(row["meta"]) if isinstance(row["meta"], dict) else {}
        body = dict(body) if isinstance(body, dict) else {}
        if row["status"]:
            body["status"] = str(row["status"])
        out[row["folder"]] = body
    return out


def _write_meta(folder: Path, meta: dict) -> None:
    """The meta put on the row without the status, and the status, if it moved, to the row."""
    from . import taskmeta, taskrecord

    status = taskrecord.word(meta.get("status")) if isinstance(meta, dict) else ""
    if not taskmeta.write(folder, taskrecord.strip(meta), _root() or None):
        log.warning("no task at %s to write a goal's meta on", folder)
    if status:
        _set_status(folder, status)


def _set_status(folder: Path, status: str) -> None:
    """The row of the goal or step in this folder told its status, if it is not that already."""
    from .models import Task

    root = _root()
    if not root:
        return
    try:
        rel = folder.resolve().relative_to(Path(root).resolve()).as_posix()
    except (ValueError, OSError):
        return
    row = Task.objects.filter(folder=rel).values("id", "status").first()
    if row is not None and row["status"] != status:
        _store().update_task(row["id"], status=status)


def _folder(task) -> Path | None:
    root = _root()
    if not root or task is None or not task.folder:
        return None
    return Path(root) / task.folder


def is_goal(meta: dict) -> bool:
    tags = meta.get("tags") if isinstance(meta, dict) else None
    return isinstance(tags, list) and any(str(t).strip().lower() == TAG for t in tags)


def page_address(goal) -> str:
    """Rouh's address for a goal's own page, as a chat or the Goals list opens it."""
    return "/task/" + (goal.folder or "") + "/" + PAGE if getattr(goal, "folder", "") else ""


def _one_line(text, limit: int = MAX_FIELD) -> str:
    return " ".join(str(text or "").split())[:limit]


def _words(text, limit: int = MAX_FIELD) -> str:
    """Kept as written, lines and all, only trimmed."""
    text = str(text or "").replace("\r\n", "\n").strip()
    return re.sub(r"\n{3,}", "\n\n", text)[:limit]


# --- making one -------------------------------------------------------------------


def create(name: str, about: str) -> dict:
    """A goal: a numbered task, tagged, with what the person knows in `goal.md`.

    The chat is the caller's to make (`timekeeper.set_goal`, through the
    runtime), and `attach_chat` writes down which it is. Raises Refused in words to say back.
    """
    from . import owning

    name = _one_line(name, MAX_NAME)
    about = _words(about, MAX_ABOUT)
    if not name:
        raise Refused("Give the goal a short name.")
    if not about:
        raise Refused("Write what you know about it - the more the better.")
    task = owning.new_task(name)
    folder = _folder(task)
    if task is None or folder is None or not folder.is_dir():
        raise Refused("There is no workspace on this machine to keep a goal in.")
    meta = _meta(folder)
    tags = [t for t in meta.get("tags") or [] if isinstance(t, str)]
    if TAG not in tags:
        tags.append(TAG)
    meta["tags"] = tags
    meta["goal"] = {"stage": "understanding", "why": "", "chat": "",
                    "created_at": time.time()}
    _write_meta(folder, meta)
    from . import steps

    path = folder / ABOUT_FILE
    path.write_text(owner.say(f"# {name}\n\nWhat ‹owner› knows about this goal, in ‹his› own words.\n\n"
                    f"{about}\n"), encoding="utf-8")
    steps.own_as_workspace(path, Path(_root()))
    return {"task": task, "folder": folder}


def attach_chat(task, chat_id: str) -> None:
    """Remember which chat is the goal's own. The runtime made it the task's."""
    folder = _folder(task)
    if folder is None:
        return
    meta = _meta(folder)
    block = meta.get("goal") if isinstance(meta.get("goal"), dict) else {}
    block["chat"] = chat_id
    meta["goal"] = block
    _write_meta(folder, meta)


# --- finding one ----------------------------------------------------------------


def _goal_tasks() -> list:
    """Every numbered task tagged a goal, newest first.

    Every task, with no limit: `list_tasks` stops at the 200 newest rows unless told
    otherwise, and steps are rows too, so once 200 tasks and steps had been made after the
    newest goal every goal fell off this list and the Goals page, the goals tool, finding a
    goal and finishing its steps all said there were none (found 4 November 2026). The
    metas are read in one query (`_metas_read_once`), not three a task.
    """
    st = _store()
    root = _root()
    if st is None or not root:
        return []
    found = []
    with _metas_read_once():
        for task in st.list_tasks(limit=None):
            if task.number is None or not task.folder:
                continue
            if is_goal(_meta(Path(root) / task.folder)):
                found.append(task)
    found.sort(key=lambda t: -(t.number or 0))
    return found


def find(said) -> tuple[object | None, str]:
    """The goal meant by its task number, its id, or words of its name."""
    said = str(said or "").strip().lstrip("#")
    goals = _goal_tasks()
    if not said:
        if len(goals) == 1:
            return goals[0], ""
        return None, "Which goal? Give its task number or words of its name."
    for g in goals:
        if said == str(g.number) or said == g.id:
            return g, ""
    words = set(re.findall(r"\w+", said.lower()))
    scored = []
    for g in goals:
        title = g.title.lower()
        hit = len(words & set(re.findall(r"\w+", title))) + (2 if said.lower() in title else 0)
        if hit:
            scored.append((hit, g))
    scored.sort(key=lambda s: -s[0])
    if not scored:
        return None, f"No goal matches {said!r}. Call goals to see them."
    if len(scored) > 1 and scored[0][0] == scored[1][0]:
        names = ", ".join(f'{g.number} "{g.title}"' for _s, g in scored[:4])
        return None, f"More than one goal matches {said!r}: {names}. Give its number."
    return scored[0][1], ""


def goal_of_chat(chat_id: str):
    """The goal this conversation belongs to, or None."""
    if not chat_id:
        return None
    st = _store()
    if st is None:
        return None
    owner = st.owner_of("chat", chat_id)
    if not owner or owner[0] != "task":
        return None
    task = st.get_task(owner[1])
    return task if task is not None and is_goal(_meta(_folder(task) or Path("/-"))) else None


def _parts(task_id: str) -> list:
    """A step's or a goal's own steps, leaving out one archived: a step taken off the plan
    is archived, never deleted (`rouh/delegation.py`, the task browser's Archive)."""
    st = _store()
    out = []
    for _kind, ident in st.children_of("task", task_id, "task"):
        row = st.get_task(ident)
        if row is not None and not getattr(row, "archived_at", None):
            out.append(row)
    return out


def _all_steps(goal) -> list[tuple[object, dict, int]]:
    """Every step and part under a goal, in order, as (row, meta, depth)."""
    out = []

    def walk(task_id: str, depth: int) -> None:
        for row in _parts(task_id):
            out.append((row, _meta(_folder(row) or Path("/-")), depth))
            if depth < 2:
                walk(row.id, depth + 1)

    walk(goal.id, 1)
    return out


def find_step(goal, said):
    """A step of this goal by its id, its place in the plan ("2.1"), or its title."""
    said = str(said or "").strip()
    everything = _all_steps(goal)
    for row, _m, _d in everything:
        if said == row.id:
            return row, ""
    place = said.lower().removeprefix("step").strip()
    for s in _flat(view(goal)["steps"]):
        if s["n"] == place:
            return next(r for r, _m, _d in everything if r.id == s["id"]), ""
    words = set(re.findall(r"\w+", said.lower()))
    scored = sorted(((len(words & set(re.findall(r"\w+", r.title.lower()))), r)
                     for r, _m, _d in everything), key=lambda s: -s[0])
    if scored and scored[0][0] and (len(scored) == 1 or scored[0][0] > scored[1][0]):
        return scored[0][1], ""
    return None, f"No single step of \"{goal.title}\" matches {said!r}; give its id."


# --- the plan ---------------------------------------------------------------------


def held_who(value) -> str:
    """Who does a step, as a step's block or a view holds it: "petar", written before
    20 October 2026, is "owner" (`owner.word`); nothing is the owner."""
    said = str(value or "").strip()
    if not said or said.lower() in owner.LEGACY:
        return OWNER
    return said


def _owner_names() -> tuple[str, ...]:
    """The owner's own names, lower case, as a model may write them for who."""
    try:
        found = owner.resolve()
    except Exception:  # noqa: BLE001 - the words "owner" and "the person" still work
        return ()
    if found is None:
        return ()
    return tuple(n.lower() for n in (found.name, found.full_name) if n)


def _who(value) -> str:
    said = _one_line(value, 60)
    low = said.lower()
    if low in ("rouh", "ai", "assistant", "jarvis", "you (rouh)", "me"):
        return "rouh"
    if low in (OWNER, "the owner", "petar", "person", "the person", "user", "you", "him", "her",
               "them") or (low and low in _owner_names()):
        return OWNER
    if low in ("together", "both", "owner and rouh", "rouh and owner", "petar and rouh",
               "rouh and petar", "the person and rouh", "rouh and the person"):
        return "together"
    if low in ("quest", "the quest", "rouh's quest", "rouh’s quest", "its quest"):
        return QUEST
    return said or OWNER


def _step_block(spec: dict) -> dict:
    who, prep = _who(spec.get("who")), _words(spec.get("prep"))
    if who == OWNER and prep:
        # Rouh has a part in it now: getting it ready. Together is the step
        # whose part Rouh does by itself, then says what is left for him.
        who = "together"
    return {"who": who,
            "prep": prep,
            "how": _words(spec.get("how")),
            "challenge": _words(spec.get("challenge")),
            "solution": _words(spec.get("solution")),
            "outcome": _words(spec.get("outcome")),
            "kind": _kind(spec.get("kind")),
            "ask": _words(spec.get("ask"), 400),
            "options": _options(spec.get("options")),
            "where": _one_line(spec.get("where"), 400),
            YOUR_STEPS: _your_steps(spec.get("your_steps")),
            "run": {}}


def _your_steps(value, was=()) -> list[dict]:
    """The person's steps, each {"text", "done"}: a list of lines, or lines of
    words, numbered or not. A step whose words are the same as one already
    there keeps its tick, so rewording the others never unticks it."""
    if isinstance(value, str):
        value = value.splitlines()
    if not isinstance(value, (list, tuple)):
        return []
    ticked = {_step_key(x.get("text")) for x in (was or ())
              if isinstance(x, dict) and x.get("done")}
    out = []
    for item in value:
        said = item.get("text") if isinstance(item, dict) else item
        said = re.sub(r"^\s*(?:[-*\u2022]|\d{1,2}[.)])\s+", "", str(said or ""))
        said = _one_line(said, MAX_YOUR_STEP)
        if said:
            out.append({"text": said, "done": _step_key(said) in ticked
                        or (isinstance(item, dict) and bool(item.get("done")))})
    return out[:MAX_YOUR_STEPS]


def _step_key(text) -> str:
    return " ".join(str(text or "").lower().split())


def tick_your_step(step, index: int, text: str, done: bool) -> list[dict]:
    """One of the person's steps ticked, or unticked, on the How to do it page.

    `text` is the step as the page drew it: if the list was rewritten since,
    the tick is refused rather than landing on another step."""
    folder = _folder(step)
    if folder is None:
        raise Refused("That step has no folder to keep it in.")
    meta = _meta(folder)
    block = meta.get("goal_step") if isinstance(meta.get("goal_step"), dict) else {}
    items = _your_steps(block.get(YOUR_STEPS))
    if not 0 <= index < len(items) or _step_key(items[index]["text"]) != _step_key(text):
        raise Refused("The steps have changed since this page was drawn. Open it again.")
    items[index]["done"] = bool(done)
    block[YOUR_STEPS] = items
    meta["goal_step"] = block
    _write_meta(folder, meta)
    return items


def _kind(value) -> str:
    said = str(value or "").strip().lower()
    # "review" and "check" were a kind until 4 October 2026, and ask nothing now.
    return said if said in KINDS else {"choose": "decision", "choice": "decision",
                                       "decide": "decision", "do": "action"}.get(said, "")


def _options(value) -> list[str]:
    """A decision's options, one line each: a list, or lines of words."""
    if isinstance(value, str):
        value = value.splitlines()
    if not isinstance(value, (list, tuple)):
        return []
    out = [_one_line(o, 200) for o in value]
    return [o for o in out if o][:MAX_OPTIONS]


def plan(goal, *, why: str = "", steps=(), add: bool = False) -> list:
    """Write the plan as subtasks, and their parts as sub-subtasks.

    A goal that already has a plan is only added to with `add`, never written
    over: a step is a folder that may hold work by now, and a second plan on
    top of the first would be two plans. Returns the rows made, in order.
    """
    from . import objecttree

    if not isinstance(steps, (list, tuple)) or not steps:
        raise Refused("A plan needs steps: give them in order.")
    if len(steps) > MAX_STEPS:
        raise Refused(f"At most {MAX_STEPS} steps; put the rest inside them as parts.")
    if _parts(goal.id) and not add:
        raise Refused("This goal has a plan already. Change its steps with goal_step, or "
                      "pass add to put more steps after them.")
    wrong = plan_problems(steps)
    if wrong:
        raise Refused("Fix these and write the plan again. " + " ".join(wrong))
    root, st = _root(), _store()
    made = []
    # Each top-level step and the stream Rouh put it in, in order.
    placed: list[tuple[str, str]] = []

    def one(owner_id: str, spec, depth: int) -> None:
        if not isinstance(spec, dict):
            spec = {"title": spec}
        title = _one_line(spec.get("title"), 160)
        if not title:
            raise Refused("Every step needs a title.")
        row = objecttree.create(root, st, type="task", title=title, owner=owner_id)
        task = st.get_task(row["id"])
        folder = _folder(task)
        meta = _meta(folder)
        meta["status"] = "not-started"
        meta["goal_step"] = _step_block(spec)
        _write_meta(folder, meta)
        made.append(task)
        if depth == 1:
            placed.append((task.id, _one_line(spec.get("stream"), MAX_STREAM_NAME)))
        inner = spec.get("steps") or spec.get("parts") or ()
        if depth < 2 and isinstance(inner, (list, tuple)):
            for part in list(inner)[:MAX_PARTS]:
                one(task.id, part, depth + 1)

    for spec in steps:
        one(goal.id, spec, 1)
    folder = _folder(goal)
    meta = _meta(folder)
    block = meta.get("goal") if isinstance(meta.get("goal"), dict) else {}
    block["stage"] = "planned"
    if why:
        block["why"] = _words(why)
    saved = _saved_streams(block)
    if saved or any(name for _i, name in placed):
        block[STREAMS] = _placed_in(saved, placed)
    # A plan with no streams named is split by Rouh straight after, in the
    # same tool call (`unsplit`, `split`), so a goal never reaches its page
    # as one stream waiting for somebody to split it.
    meta["goal"] = block
    if meta.get("status") in (None, "", "not-started"):
        meta["status"] = "in-progress"
    _write_meta(folder, meta)
    return made


# Petar, 27 September 2026, of goal 67's plan, where one step was
# "Research purpose-built tools and choose a pilot": "after research for tools
# (3) I need to make a decision - which tool are we going to use. those are two
# steps. I am guessing there is also implementation in the form of signup,
# settings, api etc. also - even if there a task for me, Rouh should have done
# prep work for me to support me." So a plan is checked as it is written
# (`plan_problems`, `plan_notes`): a decision step is the person's, so the research
# behind it is a step of its own before it; every step that asks something of
# the person says in `prep` what Rouh gets ready for it first, and Rouh does
# that part by itself (a person's step with prep is the two of them together);
# and a choice nothing after it carries out is pointed out, because choosing a
# tool or a supplier is followed by setting it up.
#
# Petar, 18 October 2026, when his decisions list flooded: a decision step is
# planned for him only when the goal truly cannot go on without his choice -
# money, sending or publishing in his name, something that cannot be undone,
# or what only he knows. Every other choice is Rouh's: its research step ends
# with its recommendation and the plan goes on with it. So research and
# choosing are no longer always two steps, and every decision step he is given
# still passes the gate in front of the decisions (`rouh/decision_gate.py`).

def _spec(spec) -> dict:
    return spec if isinstance(spec, dict) else {"title": spec}


def _inner(spec: dict) -> list:
    inner = spec.get("steps") or spec.get("parts") or ()
    return list(inner)[:MAX_PARTS] if isinstance(inner, (list, tuple)) else []


def plan_problems(steps) -> list[str]:
    """What is wrong with a plan's steps, as sentences to Rouh, or [].

    Two things are refused (see `KINDS`): a decision given to Rouh, which asks
    nothing of the person and so is no decision step, and a step that asks
    something of the person with nothing Rouh gets ready for it. A part needs
    no prep of its own when its step has one: that covers its parts."""
    out = []

    def check(spec, place: str, covered: bool) -> None:
        spec = _spec(spec)
        title = _one_line(spec.get("title"), 160) or "(no title)"
        who, kind = _who(spec.get("who")), _kind(spec.get("kind"))
        prep = _words(spec.get("prep"))
        if kind == "decision" and who in ("rouh", QUEST):
            out.append(f"Step {place} “{title}” is a decision given to you, and a step of "
                       "yours asks nothing of the person: leave kind out. When you can "
                       "choose, the step ends with your recommendation written on its page "
                       "and the plan goes on with it. Only when the goal truly cannot go on "
                       "without their choice - it spends money, sends or publishes in their "
                       "name, cannot be undone, or needs something only they know - is it "
                       "the person's decision (who owner, kind decision, ask saying what is "
                       "decided, prep saying the brief you put in front of them: the options "
                       "side by side and your recommendation), with your research a step "
                       "before it.")
        elif who not in ("rouh", QUEST) and not prep and not covered:
            out.append(f"Step {place} “{title}” asks something of "
                       f"{'the person' if who in (OWNER, 'together') else who} with "
                       "nothing prepared for it. Say in prep what you get ready first, "
                       "so it is never handed over cold: a brief, a checklist, a draft, "
                       "the form filled in as far as you can, the settings to choose.")
        for i, part in enumerate(_inner(spec), 1):
            check(part, f"{place}.{i}", covered or bool(prep))

    for i, spec in enumerate(steps or (), 1):
        check(spec, str(i), False)
    return out


def plan_notes(steps) -> list[str]:
    """What Rouh is asked to look at again in a plan it has just written.

    Not refused, because only Rouh can tell: the last step is a choice, and
    nothing after it carries the choice out. Choosing a tool, a service or a
    supplier is followed by taking it on - an account, its settings, connecting
    it, and checking it works - and those are steps too."""
    steps = [_spec(s) for s in steps or ()]
    if not steps:
        return []
    last = steps[-1]
    inner = _inner(last)
    if _kind((_spec(inner[-1]) if inner else last).get("kind")) != "decision":
        return []
    return [f"The plan ends on a choice, step {len(steps)} “{_one_line(last.get('title'), 160)}”, "
            "and nothing after it carries the choice out. If choosing means taking "
            "something on - a tool, a service, a supplier - add the steps that set it "
            "up with plan_goal and add: signing up or opening the account, the settings "
            "or configuration, connecting it (API access, keys, permissions), and "
            "checking it really works, each with what you prepare for the person first."]


# --- streams ---------------------------------------------------------------------
#
# Which steps follow one another and which go on at the same time. Only the
# top-level steps are placed: a step's parts are the step's own, in its order.


def _stream_id() -> str:
    import secrets

    return "s" + secrets.token_hex(3)


def _saved_streams(block: dict) -> list[dict]:
    """The streams as the goal block keeps them, each checked for shape."""
    out = []
    for one in (block.get(STREAMS) if isinstance(block.get(STREAMS), list) else []):
        if not isinstance(one, dict):
            continue
        steps = [str(i) for i in (one.get("steps") or []) if isinstance(i, str) and i]
        out.append({"id": str(one.get("id") or "") or _stream_id(),
                    "name": _one_line(one.get("name"), MAX_STREAM_NAME),
                    "steps": steps})
    return out


def _placed_in(streams: list[dict], placed: list[tuple[str, str]]) -> list[dict]:
    """New steps put into the streams they were named for, in order.

    A name already there is that stream; a new name is a new stream beside the
    others; no name at all is the stream the step before it went into, or the
    last one, or the first stream of a goal that has none yet.
    """
    streams = [dict(s, steps=list(s["steps"])) for s in streams]
    last = streams[-1] if streams else None
    for ident, name in placed:
        into = None
        if name:
            into = next((s for s in streams if s["name"].lower() == name.lower()), None)
            if into is None and len(streams) < MAX_STREAMS:
                into = {"id": _stream_id(), "name": name, "steps": []}
                streams.append(into)
        into = into or last
        if into is None:
            into = {"id": _stream_id(), "name": FIRST_STREAM, "steps": []}
            streams.append(into)
        into["steps"].append(ident)
        last = into
    return streams


def streams_of(block: dict, top_ids: list[str]) -> list[dict]:
    """The streams as they stand: every top-level step in exactly one, in order.

    What was saved, less steps that are not there any more; a step in none of
    them (made before streams were, or by hand) goes at the end of the last
    one, so nothing of the plan is ever off the page. A goal nobody has split
    is one stream.
    """
    here = set(top_ids)
    seen: set[str] = set()
    out = []
    for one in _saved_streams(block):
        steps = [i for i in one["steps"] if i in here and i not in seen]
        seen.update(steps)
        if steps:
            out.append(dict(one, steps=steps))
    left = [i for i in top_ids if i not in seen]
    if left:
        if out:
            out[-1]["steps"].extend(left)
        else:
            # Always the same id, so a page and a press agree on it before
            # anything has been saved.
            out.append({"id": "s000000", "name": FIRST_STREAM, "steps": left})
    return out


def arrange(goal, said) -> list[dict]:
    """The person's arrangement of the steps into streams, kept.

    `said` is the streams in order, each {"id", "name", "steps"}, as the page
    sends them. Only this goal's own top-level steps are kept, each once; an
    empty stream is dropped; a step left out is put back at the end, so a
    change on the page can move steps and never lose one. Returns the streams
    kept."""
    if not isinstance(said, list) or not said:
        raise Refused("Give the streams, in order.")
    if len(said) > MAX_STREAMS:
        raise Refused(f"At most {MAX_STREAMS} streams side by side.")
    folder = _folder(goal)
    if folder is None:
        raise Refused("That goal has no folder to keep its streams in.")
    top = [row.id for row in _parts(goal.id)]
    here = set(top)
    seen: set[str] = set()
    kept = []
    for n, one in enumerate(said):
        if not isinstance(one, dict):
            continue
        steps = []
        for ident in one.get("steps") or []:
            ident = str(ident or "")
            if ident in here and ident not in seen:
                steps.append(ident)
                seen.add(ident)
        if not steps:
            continue
        name = _one_line(one.get("name"), MAX_STREAM_NAME) or f"Stream {n + 1}"
        ident = str(one.get("id") or "")
        kept.append({"id": ident if re.fullmatch(r"s[0-9a-f]{6}", ident) else _stream_id(),
                     "name": name, "steps": steps})
    meta = _meta(folder)
    block = meta.get("goal") if isinstance(meta.get("goal"), dict) else {}
    block[STREAMS] = streams_of({STREAMS: kept}, top)
    meta["goal"] = block
    _write_meta(folder, meta)
    return block[STREAMS]


# --- splitting a plan into streams ---------------------------------------------
#
# Petar, 27 September 2026, looking at a goal planned before streams, drawn as
# one: "the streams should be split by itself. anything that can be done in
# parallel should be done in parallel ... every task or list of tasks in a
# stream ends with completion or request for my interaction." So Rouh splits a
# plan into streams when it plans (each step's `stream`), and when the model
# planning it named none, splits it at once, before the tool call returns
# (`tools._plan_goal`). After that the streams are the person's: moved and
# renamed by hand on the goal's page, or rearranged by Rouh the way the person
# says in their own words (`split` with `ask`).
#
# Petar, 27 September 2026 (fr_f9eb62fe270a), on goal 67, planned into five
# streams that a deploy then took away: "It was supposed to be split in
# streams from the get-go ... we shouldn't have a button Split into streams.
# But I should be able to: 1) be able to manage streams on this screen
# naturally. 2) be able to tell ai how to reorder streams and tasks in
# there." So the page has no Split button: it has the streams, which move,
# rename and reorder by hand, and a line to tell Rouh how to arrange them.
#
# Never by itself. Until 27 September 2026 the page split any plan with no
# streams saved the moment it opened, and every deploy put the server's
# copy of its plan back to main's, which had none: so the next time the page was
# open the person's own arrangement was split over again, six times in half
# an hour on goal 67 (fr_48647091affa, "once plan is made it shouldn't be
# changed on its own all the time"). The page no longer splits on its own,
# and since 22 October 2026 what it keeps is the goal's row, which no deploy
# touches (`rouh/taskmeta.py`).

SPLIT_SYSTEM = (
    "You split the steps of a plan into streams. A stream is steps that must happen "
    "one after another; different streams go on at the same time. Put every step that "
    "does not wait on another in a stream of its own, so as much as possible happens "
    "in parallel, and keep a step after the step it needs. A stream should end where "
    "it needs the person - a decision or an action only they can take - or where its "
    "part of the goal is complete. When the person says how they want the streams or "
    "the steps in them arranged, do exactly that and nothing more: every stream and "
    "step they did not mention stays as it is now, with its name, in its order. The "
    "streams are listed top to bottom in the order you give them. Use every step id "
    "exactly once. Name each stream in one to three words. Never use the em dash. "
    "Answer with one JSON object and nothing else: "
    "{\"streams\": [{\"name\": ..., \"steps\": [step ids in order]}]}.")

SPLIT_TIMEOUT = 60.0

#: What the steps to split are introduced with, a line each as `id | who | title`.
SPLIT_STEPS = "The steps to split, one a line, as id | who | title:"


#: What the streams as they stand are introduced with, a line each as `name: ids`.
SPLIT_NOW = "The streams as they are now, top to bottom, as name: step ids in order:"
#: And what the person asked for, in their own words.
SPLIT_ASK = "What the person asked:"


def split_text(v: dict, ask: str = "") -> str:
    lines = [f'{s["id"]} | {s["who"]} | {s["title"]}' for s in v["steps"]]
    out = f"{detail_for_model(v)}\n\n{SPLIT_STEPS}\n" + "\n".join(lines)
    if ask:
        now = [f'{lane["name"]}: {", ".join(lane["steps"])}' for lane in v["streams"]]
        out += f"\n\n{SPLIT_NOW}\n" + "\n".join(now) + f"\n\n{SPLIT_ASK} {ask}"
    return out


def unsplit(goal) -> bool:
    """Whether a goal's plan has more than one step and none of them is in a
    stream kept for it: none saved, or only streams of steps not there now."""
    folder = _folder(goal)
    block = _meta(folder).get("goal") if folder is not None else None
    block = block if isinstance(block, dict) else {}
    top = {row.id for row in _parts(goal.id)}
    kept = {i for one in _saved_streams(block) for i in one["steps"]}
    return len(top) > 1 and not (top & kept)


def split_guess(v: dict) -> list[dict]:
    """Streams without a model: each ends at the first step that needs the person.

    The plan is read in order, and a step the person does, or does with Rouh,
    closes the stream it is in; the next step starts another beside it."""
    out: list[dict] = []
    current: list[dict] = []
    for s in v["steps"]:
        current.append(s)
        if s["who"] != "rouh":
            out.append({"name": _one_line(current[-1]["title"], MAX_STREAM_NAME),
                        "steps": [x["id"] for x in current]})
            current = []
    if current:
        out.append({"name": _one_line(current[-1]["title"], MAX_STREAM_NAME),
                    "steps": [x["id"] for x in current]})
    return out


def read_split(said: str, v: dict) -> list[dict] | None:
    """The streams out of what the model wrote, or None when they cannot be used."""
    found = re.search(r"\{.*\}", said or "", re.S)
    try:
        body = json.loads(found.group(0)) if found else None
    except ValueError:
        return None
    streams = body.get("streams") if isinstance(body, dict) else None
    if not isinstance(streams, list) or not streams:
        return None
    ids = {s["id"] for s in v["steps"]}
    named = [i for one in streams if isinstance(one, dict)
             for i in (one.get("steps") or []) if i in ids]
    return streams if named else None


async def split(goal, ask: str = "", *, org_id: str | None = None) -> tuple[list[dict], bool]:
    """Split the plan into streams and keep them. Returns them, and whether
    Rouh split it (False: the guess, because Rouh could not be asked or read).

    With `ask`, the person's own words for how to arrange them, Rouh changes
    the streams as they stand the way they said. There is no guess for that:
    when Rouh cannot be asked or read, nothing changes and it is refused.

    Asked of the model the Models page has for splitting a goal, whichever
    company's it is (`rouh/llm.py`)."""
    from . import llm

    ask = _words(ask, 2000)
    v = await asyncio.to_thread(view, goal)
    if not v["steps"]:
        raise Refused("There is no plan to arrange yet.")
    streams = None
    try:
        got = await llm.ask("goal_split", system=SPLIT_SYSTEM,
                            messages=[{"role": "user", "content": split_text(v, ask)}],
                            max_tokens=2000, org_id=org_id, subject=str(goal.id),
                            timeout=SPLIT_TIMEOUT)
        streams = read_split(got.text, v)
    except asyncio.CancelledError:
        raise
    except Exception as exc:                      # noqa: BLE001 - the guess instead
        log.warning("a goal's plan could not be split by Rouh: %s", exc)
    by_rouh = streams is not None
    if ask and not by_rouh:
        raise Refused("Rouh could not be asked just now, so nothing was changed. "
                      "Try again in a moment.")
    if ask:
        # A stream kept under its name keeps its id, so what is open on the
        # page stays open.
        was = {lane["name"].lower(): lane["id"] for lane in v["streams"]}
        streams = [dict(one, id=was.get(str(one.get("name") or "").lower(), ""))
                   for one in streams if isinstance(one, dict)]
    kept = await asyncio.to_thread(arrange, goal, streams or split_guess(v))
    return kept, by_rouh


def put_in_stream(goal, step, name: str = "", *, after=None, first: bool = False) -> None:
    """One step moved where the person said, and nothing else moved.

    Into the stream of this name, made if it is new, or with no name into the
    stream of the step it goes `after`; right after that step, at the start
    with `first`, or else at the end. Every other step stays where it is.
    """
    name = _one_line(name, MAX_STREAM_NAME)
    if not name and after is None:
        raise Refused("Name the stream, or the step it goes after.")
    top = [row.id for row in _parts(goal.id)]
    if step.id not in top:
        raise Refused("Only a step of the plan goes in a stream, not a part of one.")
    if after is not None and after.id not in top:
        raise Refused("A step goes after another step of the plan, not a part of one.")
    if after is not None and after.id == step.id:
        raise Refused("A step cannot go after itself.")
    block = _meta(_folder(goal) or Path("/-")).get("goal") or {}
    streams = [dict(s, steps=[i for i in s["steps"] if i != step.id])
               for s in streams_of(block, top)]
    if name:
        into = next((s for s in streams if s["name"].lower() == name.lower()), None)
        if into is None:
            if len([s for s in streams if s["steps"]]) >= MAX_STREAMS:
                raise Refused(f"At most {MAX_STREAMS} streams side by side.")
            into = {"id": _stream_id(), "name": name, "steps": []}
            streams.append(into)
        if after is not None and after.id not in into["steps"]:
            raise Refused(f"\u201c{after.title}\u201d is not in the stream \u201c{into['name']}\u201d.")
    else:
        into = next(s for s in streams if after.id in s["steps"])
    if after is not None:
        into["steps"].insert(into["steps"].index(after.id) + 1, step.id)
    elif first:
        into["steps"].insert(0, step.id)
    else:
        into["steps"].append(step.id)
    arrange(goal, streams)


def rename_stream(goal, step, name: str) -> str:
    """The stream this step is in, given a new name. Returns the name it had."""
    name = _one_line(name, MAX_STREAM_NAME)
    if not name:
        raise Refused("Give the stream its new name.")
    top = [row.id for row in _parts(goal.id)]
    if step.id not in top:
        raise Refused("Only a step of the plan is in a stream, not a part of one.")
    block = _meta(_folder(goal) or Path("/-")).get("goal") or {}
    streams = streams_of(block, top)
    into = next(s for s in streams if step.id in s["steps"])
    was = into["name"]
    into["name"] = name
    arrange(goal, streams)
    return was


def read_deadline(said) -> str:
    """A deadline as the day it falls on, "2026-12-31", or "" for none.

    Raises Refused for anything that is not a day, so a wrong one is said
    back rather than kept."""
    text = str(said or "").strip()[:10]
    if not text or text.lower() in ("none", "no", "clear"):
        return ""
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        raise Refused("Give the deadline as a day, like 2026-12-31.") from None


def set_deadline(goal, said) -> str:
    """Give the goal a deadline, or take it away with "". Returns what is kept.

    Petar, 27 September 2026 (fr_b7586f638301), of the list of goals: "their
    titles only and if they have a deadline". A goal had nothing to say it was
    due until then; it is in the goal block, like the rest of what a goal is."""
    day = read_deadline(said)
    folder = _folder(goal)
    if folder is None:
        raise Refused("That goal has no folder to keep a deadline in.")
    meta = _meta(folder)
    block = meta.get("goal") if isinstance(meta.get("goal"), dict) else {}
    if day:
        block["deadline"] = day
    else:
        block.pop("deadline", None)
    meta["goal"] = block
    _write_meta(folder, meta)
    return day


def deadline_words(day: str, today: date | None = None) -> tuple[str, str]:
    """"31 Dec 2026" and how far off it is - "in 95 days", "tomorrow",
    "today", "3 days ago" - or two empty strings for no deadline."""
    try:
        when = date.fromisoformat(day) if day else None
    except ValueError:
        when = None
    if when is None:
        return "", ""
    today = today or date.today()
    left = (when - today).days
    said = when.strftime("%-d %b %Y")
    if left == 0:
        return said, "today"
    if left == 1:
        return said, "tomorrow"
    if left == -1:
        return said, "yesterday"
    return said, (f"in {left} days" if left > 0 else f"{-left} days ago")


def _goal_block(goal) -> tuple[Path, dict, dict]:
    folder = _folder(goal)
    if folder is None:
        raise Refused("That goal has no folder to keep this in.")
    meta = _meta(folder)
    block = meta.get("goal") if isinstance(meta.get("goal"), dict) else {}
    return folder, meta, block


def is_paused(goal) -> bool:
    """Whether the person paused this goal (`PAUSED`): nothing of it starts by itself."""
    folder = _folder(goal)
    if folder is None:
        return False
    block = _meta(folder).get("goal")
    return isinstance(block, dict) and isinstance(block.get(PAUSED), dict)


def set_paused(goal, paused: bool) -> bool:
    """Pause the goal, or let it go on. Returns whether it changed.

    Paused, nothing of the goal starts by itself or from Rouh: no stream, no
    step set to follow another, no step set for a time (`timekeeper.pause`).
    A run already under way is not stopped, the way pausing a dot leaves its
    delegated work running; it finishes and says so in the goal's chat."""
    folder, meta, block = _goal_block(goal)
    if paused == isinstance(block.get(PAUSED), dict):
        return False
    if paused:
        block[PAUSED] = {"at": int(time.time())}
    else:
        block.pop(PAUSED, None)
    meta["goal"] = block
    _write_meta(folder, meta)
    return True


def scheduled_reminders(goal) -> list[str]:
    """The reminder of every step of the goal set for a time (`RUN_MODES` "at"),
    read from the steps themselves rather than the view, which drops one it has
    no reminder row for."""
    out = []
    for _row, m, _d in _all_steps(goal):
        b = m.get("goal_step") if isinstance(m.get("goal_step"), dict) else {}
        run = b.get("run") if isinstance(b.get("run"), dict) else {}
        if run.get("mode") == "at" and run.get("reminder"):
            out.append(str(run["reminder"]))
    return out


def set_direction(goal, text: str) -> str:
    """The person's redirect, kept on the goal (`DIRECTION`), or cleared with "".

    Every run started for a step from then on is told it first
    (`brief_for_step`), and so is Rouh whenever the goal is in front of it
    (`detail_for_model`), so the plan bends to it without anybody rewriting it."""
    said = _words(text, MAX_DIRECTION)
    folder, meta, block = _goal_block(goal)
    if said:
        block[DIRECTION] = {"text": said, "at": int(time.time())}
    else:
        block.pop(DIRECTION, None)
    meta["goal"] = block
    _write_meta(folder, meta)
    return said


def note_to_redirect(v: dict, said: str) -> str:
    """What Rouh is told in the goal's chat when the person redirects it."""
    return (
        f"The person redirected the goal \"{v['title']}\" (task {v['number']}) from its page. "
        f"In their words:\n\n{said}\n\n"
        "Look over the plan against that. Where it asks for it, change, add or rearrange "
        "steps with goal_step or plan_goal (add), and in two or three short sentences say "
        "what you changed and what stays. Runs already under way keep going; every run "
        "started from now on is told this direction. "
        + ("The goal is paused: change the plan, but start nothing; the person resumes it "
           "from its page." if v.get("paused") else protected.WORDS))


#: Who said a step is complete, in its `goal_step` block as `done_by`: the
#: person, or Rouh when its part was the whole of the step (fr_5404edbbea30).
DONE_BY = ("person", "rouh")


def is_complete(meta: dict) -> bool:
    """Done, and said so by the person or by Rouh. A step Rouh marked done
    before 27 September 2026 has no `done_by`, and is complete unless it is
    hollow (`view`); `settle` gives it one."""
    block = meta.get("goal_step") if isinstance(meta.get("goal_step"), dict) else {}
    return meta.get("status") == "done" and block.get("done_by") in DONE_BY


def change_step(step, *, title=None, status=None, who=None, how=None, challenge=None,
                solution=None, outcome=None, left=None, run=None, where=None,
                kind=None, ask=None, options=None, prep=None, job=None, stuck=None,
                note=None, choice=None, your_steps=None, by_person: bool = False) -> dict:
    """Change one step. Returns its block as it now is.

    `by_person` is the person on the page: their own wording (`WORDING`), which
    marks the step theirs and Rouh is told to follow it (`brief_for_step`), or their
    Mark complete. Done from Rouh is the step complete, unless `left` says a
    decision or an action only the person can take: then it is Rouh's part
    done, and the step waits on them for that (`ROUH_DONE`).
    """
    folder = _folder(step)
    meta = _meta(folder)
    block = meta.get("goal_step") if isinstance(meta.get("goal_step"), dict) else {}
    if status is not None:
        status = STATUS_WORDS.get(str(status).strip().lower(), str(status).strip().lower())
        if status not in STATUSES:
            raise Refused(f"status is one of {', '.join(STATUSES)}.")
        block.pop("done_by", None)
        block.pop(ROUH_DONE, None)
        block.pop("stuck", None)
        if status == "done" and by_person:
            block["done_by"] = "person"
        elif status == "done" and _words(left):
            status = "waiting"
            block[ROUH_DONE] = {"at": int(time.time()), "left": _words(left)}
        elif status == "done":
            block["done_by"] = "rouh"
        meta["status"] = status
        if status in ("done", "waiting") and (block.get("run") or {}).get("mode") == "now":
            block["run"] = {}
        _store().update_task(step.id, status=status)
    if who is not None:
        block["who"] = _who(who)
    for key, value in (("how", how), ("challenge", challenge), ("solution", solution),
                       ("outcome", outcome), ("prep", prep)):
        if value is not None:
            block[key] = _words(value)
    if where is not None:
        block["where"] = _one_line(where, 400)
    if kind is not None:
        block["kind"] = _kind(kind)
    if options is not None:
        block["options"] = _options(options)
    if your_steps is not None:
        # Written again, the steps whose words did not change stay ticked.
        block[YOUR_STEPS] = _your_steps(your_steps, block.get(YOUR_STEPS) or ())
    if ask is not None:
        ask = _words(ask, 400)
        if by_person and ask and ask != block.get("ask"):
            block["asked_by"] = "person"
        elif not ask:
            block.pop("asked_by", None)
        block["ask"] = ask
    if run is not None:
        block["run"] = run
    if job is not None:
        block[JOB] = job
    # What the person wrote on the step's How to do it page, and the option
    # they picked; empty takes it off.
    for key, value in ((NOTE, note), (CHOICE, choice)):
        if value is not None:
            said = _words(value, MAX_NOTE if key == NOTE else 400)
            if said:
                block[key] = said
            else:
                block.pop(key, None)
    if stuck:
        # Why Rouh's run stopped on it, for as long as it waits (`run_finished`).
        block["stuck"] = _words(stuck, 600)
    if by_person and any(v is not None for v in (title, how, challenge, solution, kind, ask,
                                                 options, outcome)):
        block["worded_by"] = "person"
    meta["goal_step"] = block
    _write_meta(folder, meta)
    if title is not None and _one_line(title, 160):
        _store().update_task(step.id, title=_one_line(title, 160))
    return block


def step_state(step) -> tuple[str, dict]:
    """A step's status and its block as they are, for `put_back`."""
    import copy

    meta = _meta(_folder(step))
    block = meta.get("goal_step") if isinstance(meta.get("goal_step"), dict) else {}
    return str(meta.get("status") or "not-started"), copy.deepcopy(block)


def put_back(step, was: tuple[str, dict]) -> None:
    """A step as it stood before a run that never started (`timekeeper.do_step`)."""
    status, block = was
    folder = _folder(step)
    meta = _meta(folder)
    meta["status"] = status
    block["run"] = {}
    meta["goal_step"] = block
    _store().update_task(step.id, status=status)
    _write_meta(folder, meta)


# --- the person's own wording -----------------------------------------------------
#
# Petar, 27 September 2026, looking at a plan Rouh had just written: "I should
# be able to have an extra option to correct what it says there and to steer it
# in my direction before submitting it be done." So a step can be changed before
# it is started - typed over on the page, or rewritten by Rouh from what he says
# he wants different - as many times as he likes, and what is started is what
# he ended with. Nothing is saved until he saves it or starts it.
#
# And the same day (fr_14155d5f5e95), of a step waiting on him that asked the
# wrong thing: "I should be able to change stuff if something I see is wrong".
# So what a step asks of him - its kind, the words, a decision's options - and
# what has to be true for it to be complete are his to change too, on any step
# not yet complete, and what he wrote is what the step asks from then on.

#: The parts of a step the person can reword, as the page sends them.
WORDING = ("title", "kind", "ask", "options", "outcome", "how", "challenge", "solution")


def read_wording(said) -> dict:
    """A step's wording as the page sent it, trimmed the way a step keeps it.

    Only what was sent is kept: a page from before a part was there to change
    leaves it as it is."""
    said = said if isinstance(said, dict) else {}
    out = {"title": _one_line(said.get("title"), 160)}
    for key in ("how", "challenge", "solution", "outcome"):
        if key in said:
            out[key] = _words(said.get(key))
    if "kind" in said:
        out["kind"] = _kind(said.get("kind"))
    if "ask" in said:
        out["ask"] = _words(said.get("ask"), 400)
    if "options" in said:
        out["options"] = _options(said.get("options"))
    if not out["title"]:
        raise Refused("A step needs a title.")
    return out


def reword(step, wording: dict) -> None:
    """Keep the person's wording on the step."""
    change_step(step, by_person=True, **read_wording(wording))


REVISE_SYSTEM = (
    "You rewrite one step of a plan the way the person asks. The plan is for one "
    "of their goals, and you wrote the step yourself; they want it changed before "
    "it is done. Change what they ask for, keep what they did not mention, write "
    "plainly and briefly in the same voice, and never use the em dash. Answer with "
    "one JSON object and nothing else: {\"title\": ..., \"kind\": ..., \"ask\": ..., "
    "\"options\": [...], \"outcome\": ..., \"how\": ..., \"challenge\": ..., "
    "\"solution\": ...}, where kind is what the step asks of the person - action "
    "(something only they can do), decision (something they choose), or empty when it "
    "asks nothing of them, never a look over Rouh's work - ask is that in a line, "
    "starting with the verb, options are "
    "what a decision chooses between, outcome is what has to be true for the step to "
    "be complete, how is what will be done and how, challenge is the hard part and "
    "solution is what to do about it. Any but title may be empty.")

REVISE_TIMEOUT = 60.0


def revise_text(v: dict, step: dict, wording: dict, ask: str) -> str:
    """What the model is asked: the goal, its plan, the step as it stands, the ask."""
    return (f"{detail_for_model(v)}\n\n"
            f"The step to change is {step['n']}. As it stands now, with any changes "
            f"the person has typed:\n{json.dumps(wording, ensure_ascii=False, indent=1)}\n\n"
            f"What the person wants changed, in their words:\n{ask}")


def read_revision(said: str) -> dict | None:
    """The JSON object out of what the model wrote, or None."""
    found = re.search(r"\{.*\}", said or "", re.S)
    if not found:
        return None
    try:
        body = json.loads(found.group(0))
    except ValueError:
        return None
    if not isinstance(body, dict):
        return None
    try:
        return read_wording(body)
    except Refused:
        return None


async def revise(v: dict, step: dict, wording: dict, ask: str, *, who=None) -> dict:
    """The step rewritten the way the person asked, by the model the Models page
    has for it, whichever company's (`rouh/llm.py`). Saves nothing.

    Raises Refused, in words to say back, when there is no answer to show.
    """
    from . import llm

    wording = read_wording(wording)
    ask = _words(ask, 2000)
    if not ask:
        raise Refused("Say what to change first.")
    try:
        got = await llm.ask("goal_revise", system=REVISE_SYSTEM,
                            messages=[{"role": "user", "content": revise_text(v, step, wording, ask)}],
                            max_tokens=2000, who=who, purpose="goal_step_revise",
                            subject=str(step.get("id") or ""), timeout=REVISE_TIMEOUT)
    except llm.Cannot as exc:
        raise Refused(f"Rouh cannot be asked here ({exc}). Change the words yourself.") from None
    except asyncio.CancelledError:
        raise
    except Exception as exc:                      # noqa: BLE001 - said back instead
        log.warning("a goal step could not be rewritten: %s", exc)
        raise Refused("Rouh could not rewrite it just now. Try again, or change the "
                      "words yourself.") from exc
    out = read_revision(got.text)
    if out is None:
        raise Refused("Rouh's answer could not be read. Try again, or change the words "
                      "yourself.")
    return out


def waiting_on(goal, step_id: str) -> list:
    """The steps set to be done once this one is: run after it, and not started."""
    out = []
    for row, meta, _d in _all_steps(goal):
        block = meta.get("goal_step") or {}
        run = block.get("run") or {}
        if (run.get("mode") == "after" and run.get("after") == step_id
                and str(meta.get("status") or "not-started") in ("not-started", "")):
            out.append(row)
    return out


def goal_above(step):
    """The goal a step or part belongs to, walking up."""
    st = _store()
    seen = 0
    current = step
    while current is not None and seen < 6:
        owner = st.owner_of("task", current.id)
        if not owner or owner[0] != "task":
            return None
        current = st.get_task(owner[1])
        if current is not None and is_goal(_meta(_folder(current) or Path("/-"))):
            return current
        seen += 1
    return None


def of_step(step) -> tuple[dict, dict] | None:
    """The goal a step's task belongs to and the step, both as the Goals page
    draws them, or None for a task that is not a step of a goal.

    For the step's own page (`objectindex._goal_step_panel`), which until 27
    September 2026 said "Nothing in this yet" and nothing else: the Goals
    page's Open took the person there, and it was a dead end."""
    if step is None or not isinstance(_meta(_folder(step) or Path("/-")).get("goal_step"), dict):
        return None
    goal = goal_above(step)
    if goal is None:
        return None
    v = view(goal)
    s = step_in(v, step.id)
    return (v, s) if s is not None else None


# --- what a step leaves behind ----------------------------------------------------
#
# Petar, 27 September 2026, on step 67-02 "Compare ways to capture meetings and
# voice": "This task also says done but there's nothing there - no research no
# HTML page with results no nothing." The research had been done: Rouh drew it
# as card 857 in the goal's chat and marked the step done. But a card drawn in
# that chat belongs to the goal (`artifacts.owner_for`), so the step's own page
# - the one the Goals page opens - had nothing on it, and step 67-01's menu of
# AI uses (card 856) had gone the same way.
#
# So what Rouh draws while it does a step is written into the step's own folder
# as its page (`steps.STEP_FILE`, the card's blocks, which read back as the same
# card), and the card is recorded as that page, so revising it rewrites the
# file. And a step Rouh does is never marked done by Rouh with nothing to show
# for it: `goal_step` refuses, and says what to do instead.

#: What a step's folder holds that is its bookkeeping, not its work.
_KEEPING = frozenset({"AGENTS.md", ABOUT_FILE})


def result_of(step) -> str:
    """The file in a step's own folder that is its result, by name, or "".

    Its `index.html` first, then the page Rouh wrote for it, then any other
    file. Folders are not results: a step's parts are folders inside it.
    """
    from . import steps

    folder = _folder(step)
    if folder is None:
        return ""
    try:
        names = sorted(p.name for p in folder.iterdir()
                       if p.is_file() and not p.name.startswith(".")
                       and p.name not in _KEEPING)
    except OSError:
        return ""
    for want in ("index.html", steps.STEP_FILE):
        if want in names:
            return want
    return names[0] if names else ""


def _turn_began(chat_id: str, upto: int | None = None) -> int | None:
    """The message a turn in this chat began with: the last one that was not a tool's answer.

    `upto` is a message of that turn; left out, the turn is the one going on now.
    """
    from .models.memory import TranscriptMessage

    rows = TranscriptMessage.objects.filter(session_id=chat_id, role="user", live=True)
    if upto is not None:
        rows = rows.filter(id__lte=upto)
    for ident, content in rows.order_by("-id").values_list("id", "content")[:200]:
        try:
            body = json.loads(content)
        except (TypeError, ValueError):
            return ident
        if not isinstance(body, list) or not any(
                isinstance(b, dict) and b.get("type") == "tool_result" for b in body):
            return ident
    return None


def _drawn_in_turn(goal, chat_id: str, upto: int | None = None) -> list:
    """The cards drawn in the goal's chat during one turn, not yet written anywhere.

    Oldest first, as (row, spec). A card a step has already been given, or one
    filed as a numbered step by the person, has a path and is not taken again.
    """
    from . import artifacts

    st = _store()
    began = _turn_began(chat_id, upto) if chat_id else None
    if st is None or began is None:
        return []
    found = {}
    for owner in (("task", goal.id), ("chat", chat_id)):
        for row, head in st.heads(kind="card", owner=owner, limit=100):
            at = artifacts._anchor(head.body if head else None)
            if row.path or at is None or at < began or (upto is not None and at > upto):
                continue
            where = artifacts.chats_drawn_in({row.id: head.body if head else None})
            if where.get(row.id) == chat_id:
                found[row.id] = (row, artifacts._spec_of(head))
    return sorted(found.values(), key=lambda pair: (pair[0].created_at, pair[0].id))


def file_result(goal, step, chat_id: str, upto: int | None = None) -> str:
    """Write what Rouh drew for a step in this turn into the step, as its page.

    Returns the file's name, or "" when nothing was drawn. One card is written
    as it is, and remembered as that page, so a later revision of the card
    rewrites it (`artifacts.revise`). Several are written one after the other
    under the step's name.
    """
    from . import objecttree, steps

    root = _root()
    drawn = _drawn_in_turn(goal, chat_id, upto)
    if not root or not drawn or not step.folder:
        return ""
    if len(drawn) == 1:
        row, spec = drawn[0]
        title, blocks = spec.get("title") or row.title, list(spec.get("blocks") or [])
    else:
        title, blocks = step.title, []
        for row, spec in drawn:
            head = "## " + _one_line(spec.get("title") or row.title, 160)
            if spec.get("description"):
                head += "\n\n" + _words(spec["description"])
            blocks.append({"block": "text", "text": head})
            blocks.extend(spec.get("blocks") or [])
    try:
        steps.rewrite_step(root, step.folder, title, blocks)
    except (steps.Refused, OSError):
        log.exception("what was drawn for step %s could not be written into it", step.id)
        return ""
    if len(drawn) == 1:
        _store().update_artifact(drawn[0][0].id, path=f"{step.folder}/{steps.STEP_FILE}")
    objecttree._written()
    log.info("step %s: %d card(s) written into %s as its page", step.id, len(drawn),
             step.folder)
    return steps.STEP_FILE


def is_hollow(step) -> bool:
    """A step Rouh does, marked done, with nothing in its folder to show for it."""
    meta = _meta(_folder(step) or Path("/-"))
    return (str(meta.get("status") or "") == "done" and not is_complete(meta)
            and (meta.get("goal_step") or {}).get("who") == "rouh" and not result_of(step))


def done_pill(step) -> str:
    """What a task list says for a step of a goal whose status is done, in
    `objectindex.STATE_WORDS`' terms: "hollow" for one Rouh marked done with
    nothing made, else "": done is complete, whoever said so (`DONE_BY`).
    Only the step's folder is read, so anything with a `folder` will do."""
    return "hollow" if is_hollow(step) else ""


def needs_a_result(step, *, who=None) -> str:
    """Why Rouh may not mark this step done yet, or "" when it may.

    Only a step Rouh does needs something to show: a step the person did is
    theirs to call done. `who` is who the same call is making it.
    """
    meta = _meta(_folder(step) or Path("/-"))
    block = meta.get("goal_step") or {}
    doer = _who(who) if who is not None else held_who(block.get("who"))
    # A step of theirs Rouh gets ready (`prep`) has that on the record too.
    if not (doer == "rouh" or (doer == "together" and block.get("prep"))) or result_of(step):
        return ""
    return ("Nothing you made for this step is on the record, so it would read as done "
            "with nothing behind it. Put the result on the screen in this turn with "
            "show_on_screen - whatever you draw while doing a step is written into the "
            "step as its page - and then mark it done. If the person did it "
            "themselves, pass who as owner. If it cannot be finished now, mark it "
            "waiting and say what is left.")


#: What a step asks when all it asks is a look over Rouh's work (`settle`).
_LOOK_OVER = re.compile(r"\s*(?:look|review|check|confirm|verify|approve|read|see|go "
                        r"over|glance|skim|say whether|tell rouh whether)\b", re.I)


def settle() -> list:
    """Steps that were waiting on the person only to look over Rouh's work,
    made complete, and steps Rouh marked done before `done_by` was kept, given
    Rouh as theirs. Petar, 4 October 2026 (fr_5404edbbea30): "If rouh feels it
    did the job, I don't have to approve it or check it." A step waiting on a
    decision or an action of his, or on what he wrote into it himself, is left
    as it is. Runs when Rouh starts, and is a no-op once done. Returns
    [(goal, step)] for each step made complete now, for what follows it to start."""
    out = []
    for goal in _goal_tasks():
        for row, meta, _d in _all_steps(goal):
            block = meta.get("goal_step")
            if not isinstance(block, dict):
                continue
            status = str(meta.get("status") or "")
            if status == "done" and block.get("done_by") not in DONE_BY:
                if not is_hollow(row):
                    block["done_by"] = "rouh"
                    meta["goal_step"] = block
                    _write_meta(_folder(row), meta)
                continue
            mark = block.get(ROUH_DONE)
            if (status != "waiting" or not isinstance(mark, dict)
                    or _kind(block.get("kind")) or block.get("asked_by") == "person"):
                continue
            said = str(mark.get("left") or block.get("ask") or "")
            if str(block.get("kind") or "") != "review":
                if said:
                    # No kind, and something said as left: it may be a decision.
                    continue
            elif said and not _LOOK_OVER.match(said):
                # Called a review, but what it asks is something he does - "Use
                # it for two weeks and say what to change" - so it is his action.
                block["kind"] = "action"
                meta["goal_step"] = block
                _write_meta(_folder(row), meta)
                continue
            change_step(row, status="done", left="")
            log.info("step %s of goal %s waited only on a review, and is complete", row.id,
                     goal.id)
            out.append((goal, row))
    return out


def mend() -> int:
    """Give every step Rouh marked done before this existed the page it drew for it.

    Found from the goal's chat: the `goal_step` call that marked the step done,
    and the cards drawn in the turn it was made in. Runs when Rouh starts, and
    is a no-op for a step that already has its result. Returns how many it wrote.
    """
    from .models.memory import TranscriptMessage

    wrote = 0
    for goal in _goal_tasks():
        chat = ((_meta(_folder(goal) or Path("/-")).get("goal") or {}).get("chat") or "")
        if not chat:
            continue
        hollow = {row.id: row for row, meta, _d in _all_steps(goal)
                  if str(meta.get("status") or "") == "done"
                  and (meta.get("goal_step") or {}).get("who") == "rouh"
                  and not result_of(row)}
        if not hollow:
            continue
        # The calls that marked a step done, newest first; the step is named
        # the ways the tool takes, by id, place or title (`find_step`).
        calls = (TranscriptMessage.objects
                 .filter(session_id=chat, role="assistant", live=True,
                         content__contains="goal_step")
                 .order_by("-id").values_list("id", "content"))
        for ident, content in calls:
            try:
                body = json.loads(content)
            except (TypeError, ValueError):
                continue
            for b in body if isinstance(body, list) else []:
                said = b.get("input") if isinstance(b, dict) else None
                if (not isinstance(said, dict) or b.get("type") != "tool_use"
                        or b.get("name") != "goal_step"
                        or str(said.get("status") or "").lower() != "done"):
                    continue
                row, _why = find_step(goal, said.get("step"))
                if row is None or row.id not in hollow:
                    continue
                del hollow[row.id]
                if file_result(goal, row, chat, upto=ident):
                    wrote += 1
    return wrote


# --- what the page draws and what Rouh is told ----------------------------------


def _about(folder: Path) -> str:
    try:
        text = (folder / ABOUT_FILE).read_text(encoding="utf-8")
    except OSError:
        return ""
    # The file's own heading and the line under it are the file's, not his words.
    parts = text.split("\n\n", 2)
    return parts[2].strip() if len(parts) == 3 and parts[0].startswith("# ") else text.strip()


def who_words(who: str) -> str:
    return WHO.get(who, who or "You")


def who_means(who: str) -> str:
    return WHO_MEANS.get(held_who(who), f"{who} does this one, not you or Rouh. Mark it "
                                        "complete when it is.")


def _run_view(run: dict, places: dict, titles: dict, reminders_by_id: dict) -> dict:
    from . import clock, reminders

    mode = (run or {}).get("mode") or ""
    if mode == "at":
        row = reminders_by_id.get(run.get("reminder"))
        when = clock.moment(row.next_at) if row is not None and row.next_at else None
        if row is None or row.state == "done" or when is None:
            return {}
        return {"mode": "at", "reminder": row.id, "at": row.next_at,
                "words": "Rouh does it " + reminders.spoken(when)}
    if mode == "after":
        after = run.get("after") or ""
        if after not in titles:
            return {}
        return {"mode": "after", "after": after,
                "words": f"Rouh does it once step {places.get(after, '')} "
                         f"“{titles[after]}” is complete"}
    if mode == "now":
        return {"mode": "now", "job": run.get("job") or "",
                "words": "Rouh is working on it in the background"}
    return {}


def view(goal, *, reminders_by_id: dict | None = None, delegates: bool = True) -> dict:
    """One goal as the page draws it and as `goals` tells Rouh.

    `delegates` False leaves out who decides for it (`_delegates`), the dearest part
    by far, for a reader that never says it: the system prompt (`block`)."""
    from . import pages

    folder = _folder(goal) or Path("/-")
    meta = _meta(folder)
    block = meta.get("goal") if isinstance(meta.get("goal"), dict) else {}
    everything = _all_steps(goal)
    # The plan in the order of its streams: the first stream's steps, then the
    # next one's, each step with its parts behind it.
    streams = streams_of(block, [r.id for r, _m, d in everything if d == 1])
    groups: dict[str, list] = {}
    current = None
    for entry in everything:
        if entry[2] == 1:
            current = groups.setdefault(entry[0].id, [])
        if current is not None:
            current.append(entry)
    stream_of = {i: one["id"] for one in streams for i in one["steps"]}
    everything = [e for one in streams for i in one["steps"] for e in groups.get(i, [])]
    titles = {r.id: r.title for r, _m, _d in everything}
    # Its place in the plan, "2" or "2.1": what the page and Rouh call a step.
    # The folder's own number is no use for that, because a part of a step is
    # numbered inside the task like a step is ("67-01" twice).
    places: dict[str, str] = {}
    top_n = part_n = 0
    for row, _m, depth in everything:
        if depth == 1:
            top_n, part_n = top_n + 1, 0
            places[row.id] = str(top_n)
        else:
            part_n += 1
            places[row.id] = f"{top_n}.{part_n}"
    reminders_by_id = reminders_by_id or {}

    def step_view(row, m, depth) -> dict:
        b = m.get("goal_step") if isinstance(m.get("goal_step"), dict) else {}
        status = str(m.get("status") or "not-started")
        result = result_of(row)
        rouh_done = b.get(ROUH_DONE) if isinstance(b.get(ROUH_DONE), dict) else None
        # A step Rouh does that says done with nothing to show for it, which
        # the page does not call done: Rouh does it again.
        hollow = (status == "done" and not is_complete(m) and b.get("who") == "rouh"
                  and not result)
        # Done is complete, whoever said so: a step Rouh marked done before
        # `done_by` was kept is Rouh's, unless it is hollow (fr_5404edbbea30).
        done_by = ((b.get("done_by") if b.get("done_by") in DONE_BY else "rouh")
                   if status == "done" and not hollow else "")
        if status != "waiting":
            rouh_done = None
        return {"id": row.id, "n": places[row.id], "title": row.title, "depth": depth,
                "folder": row.folder or "",
                "status": status if status in STATUSES else "in-progress",
                # What it made.
                "result": result, "hollow": hollow,
                "rouh_done": rouh_done is not None,
                # Who said it is complete: the person, or Rouh (`DONE_BY`).
                "done_by": done_by,
                "left": (b.get("ask") if b.get("asked_by") == "person" and b.get("ask")
                         else (rouh_done or {}).get("left") or ""),
                "outcome": b.get("outcome") or "",
                "stuck": (b.get("stuck") or "") if status == "waiting" and rouh_done is None
                         else "",
                "kind": b.get("kind") if b.get("kind") in KINDS else "",
                "ask": b.get("ask") or "",
                "options": _options(b.get("options")),
                # He wrote what the step asks of him: that is what it asks,
                # whatever Rouh said was left when it did its part.
                "ask_yours": b.get("asked_by") == "person" and bool(b.get("ask")),
                "who": held_who(b.get("who")), "who_words": who_words(held_who(b.get("who"))),
                "who_means": who_means(held_who(b.get("who"))),
                "how": b.get("how") or "", "challenge": b.get("challenge") or "",
                "solution": b.get("solution") or "",
                # What Rouh gets ready before the person's part.
                "prep": b.get("prep") or "",
                "where": b.get("where") or "",
                "yours": b.get("worded_by") == "person",
                "run": _run_view(b.get("run") or {}, places, titles, reminders_by_id),
                "page": pages.url_for("_task/" + row.folder) + "/" if row.folder else "",
                "stream": stream_of.get(row.id, ""),
                # The background run last started on it (`JOB`).
                "job": str((b.get(JOB) or {}).get("id") or "") if isinstance(b.get(JOB), dict)
                       else "",
                "prepared": _prepared(row, result),
                "explainer": explainer_href(row),
                # His own page for the step: what to do, inputs, Mark as complete.
                "yours_page": yours_href(row),
                "note": b.get(NOTE) or "",
                "choice": b.get(CHOICE) or "",
                # His part as steps to tick, and how many are ticked.
                "your_steps": _your_steps(b.get(YOUR_STEPS)),
                "parts": []}

    top: list[dict] = []
    by_id: dict[str, dict] = {}
    st = _store()
    for row, m, depth in everything:
        v = step_view(row, m, depth)
        by_id[row.id] = v
        owner = st.owner_of("task", row.id)
        if depth == 1 or not owner or owner[1] not in by_id:
            top.append(v)
        else:
            by_id[owner[1]]["parts"].append(v)
    flat = list(by_id.values())
    for v in flat:
        v["needs"] = needs_of(v)
        v["rouh_state"], v["your_state"] = part_states(v)
        v["your_words"] = your_words(v)
        if not v["your_state"]:
            # Nothing is asked of him in it, so there is no page of his part.
            v["yours_page"] = ""
    lanes = [stream_view(one, [by_id[i] for i in one["steps"] if i in by_id])
             for one in streams]
    paused = block.get(PAUSED) if isinstance(block.get(PAUSED), dict) else None
    for lane in lanes:
        head = by_id.get(lane["head"])
        # What Let Rouh go starts (`timekeeper.start_streams`): nothing while
        # the person has the goal paused.
        lane["startable"] = (paused is None and head is not None
                             and can_start(head, again=True))
        if paused is not None and lane["state"] in ("rouh", "set"):
            # Held: nothing of it starts until the person resumes the goal.
            lane["words"] = "Paused · " + lane["words"]
    done = sum(1 for v in flat if v["status"] == "done" and not v["hollow"])
    # A step under way is said apart from the done ones, so the count never
    # reads as more finished than the plan is (fr_589e6cd54be7).
    going = sum(1 for v in flat if v["status"] == "in-progress")
    yours = sum(1 for v in flat if v["rouh_done"])
    stage = block.get("stage") if block.get("stage") in STAGES else "understanding"
    challenges = sum(1 for v in flat if v["challenge"])
    deadline = str(block.get("deadline") or "")
    due, due_left = deadline_words(deadline)
    direction = block.get(DIRECTION) if isinstance(block.get(DIRECTION), dict) else {}
    return {
        "id": goal.id, "number": goal.number, "title": goal.title, "folder": goal.folder,
        "address": page_address(goal), "task_address": "/task/" + goal.folder,
        "stage": stage, "streams": lanes,
        "waiting_streams": sum(1 for lane in lanes if lane["state"] == "you"),
        "status": str(meta.get("status") or "not-started"),
        "about": _about(folder), "why": block.get("why") or "",
        "chat": block.get("chat") or "", "created_at": block.get("created_at") or 0,
        "steps": top, "count": len(flat), "done": done, "challenges": challenges,
        "rouh_can": sum(1 for v in flat if (v["who"] == "rouh" and not v["rouh_done"]
                                            and (v["status"] != "done" or v["hollow"]))
                        or preparing(v)),
        "going": going, "waiting_you": yours,
        # For the page's counts (`goalpage.js`): waiting on
        # something other than the person, and steps that are theirs to do
        # and not yet waiting on them to mark complete.
        "waiting": sum(1 for v in flat if v["status"] == "waiting" and not v["rouh_done"]),
        "yours": sum(1 for v in flat if v["who"] in (OWNER, "together")
                     and v["status"] != "done" and not v["rouh_done"]),
        "deadline": deadline if due else "", "deadline_words": due,
        "deadline_left": due_left,
        "progress_words": (f"{done} of {len(flat)} steps complete"
                           + (f", {going} under way" if going else "")
                           + (f", {yours} waiting on you" if yours else "") if flat else
                           "Rouh is asking you about it" if stage == "understanding"
                           else "No steps yet"),
        "paused": paused is not None, "paused_at": (paused or {}).get("at") or 0,
        "direction": str(direction.get("text") or ""),
        "direction_at": direction.get("at") or 0,
        "standing": standing(stage, lanes, by_id, paused=paused is not None,
                             done=done, count=len(flat)),
        "boundaries": [dict(b) for b in BOUNDARIES],
        # Who decides for it by the person's grant, and what they did (`rouh/delegation.py`).
        "delegates": _delegates(goal.id) if delegates else {"deciders": [], "acts": []},
    }


def _delegates(goal_id: str) -> dict:
    from . import delegation

    try:
        return delegation.on_work_any(goal_id=goal_id)
    except Exception:
        log.exception("who decides for goal %s could not be read", goal_id)
        return {"deciders": [], "acts": []}


def standing(stage: str, lanes: list[dict], by_id: dict, *, paused: bool, done: int,
             count: int) -> dict:
    """Where the goal stands, in one place: the page's Where it stands and Rouh's line.

    {"state", "words", "next", "decision"}: the state in a word or two; the
    next thing that happens, and who does it; and the first decision or
    action waiting on the person, with the step it is on, or {}. Read from
    the streams (`stream_view`), the person's need before Rouh's work, so
    what waits on them is never buried under what Rouh is busy with."""
    heads = [(lane, by_id.get(lane["head"])) for lane in lanes]
    yours = [(lane, h) for lane, h in heads if lane["state"] == "you" and h is not None]
    going = sum(1 for lane in lanes if lane["state"] == "going")
    decision = {}
    if yours:
        lane, h = yours[0]
        decision = {"step": h["id"], "n": h["n"], "title": h["title"],
                    "label": h["needs"]["label"], "words": h["needs"]["words"],
                    "options": h.get("options") or [], "more": len(yours) - 1}
    if stage == "understanding" and not by_id:
        return {"state": "asking", "words": "Rouh is asking you about it",
                "next": "Answer Rouh's questions in the goal's chat, and it lays out the plan.",
                "decision": {}}
    if count and done == count:
        return {"state": "complete", "words": "Every step is complete",
                "next": "Nothing is left to do.", "decision": {}}
    if not by_id:
        return {"state": "empty", "words": "No steps yet",
                "next": "Ask Rouh in the goal's chat to lay out the plan.", "decision": {}}
    if paused:
        nxt = ("Nothing starts until you resume it"
               + (f"; {going} run{'s' if going != 1 else ''} already under way will finish "
                  "and report here." if going else "."))
        return {"state": "paused", "words": "Paused", "next": nxt, "decision": decision}
    if yours:
        nxt = (f"{decision['label']} on step {decision['n']} \u201c{decision['title']}\u201d: "
               f"{decision['words']}")
        state, words = "you", ("Waiting on you" + (f", Rouh on {going} more" if going else ""))
    else:
        lane, h = next(((lane, h) for lane, h in heads if lane["state"] == "going"),
                       next(((lane, h) for lane, h in heads if lane["state"] in ("set", "rouh")),
                            next(((lane, h) for lane, h in heads if h is not None),
                                 (None, None))))
        if h is None:
            return {"state": "other", "words": "Waiting", "next": "", "decision": {}}
        state = {"going": "going", "set": "set", "rouh": "rouh"}.get(lane["state"], "other")
        words = {"going": "Rouh is on it", "set": "Rouh will carry on",
                 "rouh": "Rouh can carry on"}.get(state, lane["words"])
        nxt = {"going": f"Rouh is working on step {h['n']} \u201c{h['title']}\u201d in the "
                        "background.",
               "set": f"{lane['words']}: step {h['n']} \u201c{h['title']}\u201d.",
               "rouh": f"Rouh can take up step {h['n']} \u201c{h['title']}\u201d by itself."
               }.get(state, f"Step {h['n']} \u201c{h['title']}\u201d: {lane['words']}.")
    return {"state": state, "words": words, "next": nxt, "decision": decision}


#: What a stream's state is called on the page, and to Rouh.
STREAM_WORDS = {"done": "Complete", "you": "Waiting on you", "going": "Rouh is on it",
                "set": "Rouh will carry on", "rouh": "Rouh can go on by itself",
                "other": "Waiting on someone else", "empty": "Nothing in it"}


def needs_of(s: dict) -> dict:
    """What a step needs from the person before it can go on, or {}.

    `kind` is the step's own (`KINDS`): a decision - theirs to make, with
    the options - or an action, something only they can do. `words` says
    what, in a line: what the step asks of them (`ask`, theirs first when
    they wrote it), what Rouh said was left, or what has to be true for it
    to be complete. Never a look over what Rouh made (fr_5404edbbea30)."""
    if s["status"] == "done" and not s["hollow"]:
        return {}
    kind = s.get("kind") or ""
    ask = s.get("ask") or ""
    once = (f"{s['outcome'][0].lower()}{s['outcome'][1:]}" if s["outcome"] else "")
    if s["rouh_done"]:
        kind = kind or "decision"
        if s["left"]:
            words = s["left"]
        elif ask:
            words = ask
        elif once:
            words = f"Say it is complete once {once}"
        else:
            words = (f"Decide what comes of “{s['title']}”, and mark it complete. If this "
                     "step should ask something else of you, change it.")
        return {"kind": kind, "label": KIND_LABELS[kind], "words": words}
    if s["who"] == OWNER:
        kind = kind or "action"
        return {"kind": kind, "label": KIND_LABELS[kind],
                "words": ask or s["how"] or (f"{s['title']}, until {once}" if once else
                                             f"{s['title']}, then mark it complete.")}
    if preparing(s):
        # Rouh gets it ready first: nothing is asked of them until it has.
        return {}
    if s["who"] == "together" and not s["run"]:
        return {"kind": kind or "action", "label": "Start it with Rouh",
                "words": ask or "Rouh does its part in the background and says what is "
                                "left for you."}
    if s["status"] == "waiting" and s["who"] in ("rouh", "together"):
        return {"kind": "action", "label": "Rouh is stuck",
                "words": s.get("stuck") or "Rouh stopped on this and needs you to unblock "
                                           "it. Its explainer page says what for."}
    if s["who"] not in WHO:
        return {"kind": "action", "label": "Your action",
                "words": f"Get {s['who_words']} to do it: {s['title']}."}
    return {}


def preparing(s: dict) -> bool:
    """A step of theirs whose preparation (`prep`) Rouh has not finished yet."""
    return (s["who"] == "together" and bool(s.get("prep")) and not s["rouh_done"]
            and s["status"] in ("not-started", "in-progress") and not s["hollow"])


def stream_view(one: dict, steps: list[dict]) -> dict:
    """One stream as the page draws it: its steps, and where it stands.

    Where it stands is its first step not yet complete (`head`): complete
    when there is none; waiting on the person when that step needs them
    (`needs_of`); Rouh on it, set to carry on at a time or after a step, or
    able to go on by itself when the step is Rouh's."""
    head = next((s for s in steps if s["status"] != "done" or s["hollow"]), None)
    if not steps:
        state = "empty"
    elif head is None:
        state = "done"
    elif head["needs"]:
        state = "you"
    elif (head["run"] or {}).get("mode") == "now":
        state = "going"
    elif head["run"]:
        state = "set"
    elif head["who"] == "rouh" or preparing(head):
        state = "rouh"
    else:
        state = "other"
    words = STREAM_WORDS[state]
    if state == "set":
        words = head["run"]["words"]
    elif state == "rouh" and head["status"] == "in-progress":
        # Rouh's turn on it ended without its part done: it can take it up again.
        words = "Started, not finished · Rouh can carry on"
    elif state == "other" and head is not None:
        words = ("Rouh's quest carries it" if head["who"] == QUEST
                 else f"Waiting on {head['who_words']}")
    return {"id": one["id"], "name": one["name"], "steps": [s["id"] for s in steps],
            "head": head["id"] if head is not None else "", "state": state, "words": words,
            "done": sum(1 for s in steps if s["status"] == "done" and not s["hollow"]),
            # Rouh's steps that follow the head one after another, which Let
            # Rouh go sets going (`timekeeper.let_go`).
            "rouh_can": state == "rouh"}


def can_start(s: dict, *, again: bool = False) -> bool:
    """Whether Rouh can take this step up by itself now.

    A step that is Rouh's, or the person's and Rouh's together (Rouh does its
    part and says what is left for them), not yet started and not set for a
    time or to follow another step. `again` also takes one whose turn ended
    without its part done, or that was marked done with nothing to show,
    which only a press starts again: a plan starting by itself never does
    the same step twice."""
    if s["who"] not in ("rouh", "together") or s["run"] or s["rouh_done"]:
        return False
    if s["status"] == "not-started":
        return True
    return again and (s["status"] == "in-progress" or s["hollow"])


def lane_of(v: dict, step_id: str) -> dict | None:
    """The stream a step or a part of one is in."""
    for top in v["steps"]:
        if top["id"] == step_id or any(p["id"] == step_id for p in _flat(top["parts"])):
            return next((lane for lane in v["streams"] if top["id"] in lane["steps"]), None)
    return None


def _prepared(step, result: str) -> dict:
    """What has been made for a step, to put in front of the person.

    The files in its own folder, each with the address it opens at, which
    the step's explainer lists under what Rouh made (fr_b083c37a634d:
    "everything that has been prepared for me ... should be gathered and
    presented easily")."""
    from . import objectindex, pages

    folder = _folder(step)
    if folder is None:
        return {"files": []}
    try:
        names = sorted((p.name for p in folder.iterdir()
                        if p.is_file() and not p.name.startswith(".")
                        and p.name not in _KEEPING), key=lambda n: (n != result, n.lower()))
    except OSError:
        return {"files": []}
    files = []
    for name in names[:12]:
        page = name.lower().endswith((".html", ".htm"))
        files.append({"name": name, "page": page,
                      "href": (pages.url_for(f"{step.folder}/{name}") if page
                               else objectindex.doc_url(step.folder, name))})
    return {"files": files}


def explainer_href(step) -> str:
    """Where a step's explainer opens: the page Rouh wrote for it under
    `EXPLAINER`, or the one drawn from the step (`EXPLAINER_DOC`)."""
    from . import objectindex, pages

    if not getattr(step, "folder", ""):
        return ""
    folder = _folder(step)
    if folder is not None and (folder / EXPLAINER).is_file():
        return pages.url_for(f"{step.folder}/{EXPLAINER}")
    return objectindex.doc_url(step.folder, EXPLAINER_DOC)


def yours_href(step) -> str:
    """Where a step's How to do it page opens (`YOURS_DOC`)."""
    from . import objectindex

    if not getattr(step, "folder", ""):
        return ""
    return objectindex.doc_url(step.folder, YOURS_DOC)


def again_why(feedback: str) -> str:
    """What a run redoing a step is told first: the person looked at what was
    made and said what they did not like (`goalpage.js` Do it again)."""
    said = _words(feedback, 2000)
    if not said.endswith((".", "!", "?")):
        said += "."
    return ("The person looked at what was made for this step before and asked for it to "
            f"be done again. What they did not like, in their words: {said} Read what is already in "
            "the step's folder, keep what still holds, and redo the work so it answers "
            "that; write the explainer page again with the new result.")


def your_words(s: dict) -> str:
    """What the person does in a step, in a line: what it needs from them
    (`needs_of`), or, while Rouh is still on its part, what comes after it."""
    if s["status"] == "done" and not s["hollow"]:
        return ("You marked it complete." if s.get("done_by") == "person" else
                "Nothing: Rouh did it, and it is complete.")
    if s["needs"]:
        return s["needs"]["words"]
    if not s["your_state"]:
        return "Nothing: Rouh does it, and it is complete once Rouh has."
    once = (f" once {s['outcome'][0].lower()}{s['outcome'][1:]}" if s["outcome"] else "")
    if s["rouh_state"] in ("todo", "doing"):
        if s.get("ask"):
            return f"Once Rouh has done its part: {s['ask'][0].lower()}{s['ask'][1:]}"
        return ("Nothing yet. Once Rouh has done its part, it asks you only for a decision "
                "or an action that is yours, if one is left.")
    return f"Mark the step complete{once or ' when it is done'}."


def part_states(s: dict) -> tuple[str, str]:
    """Where Rouh's part and the person's part of a step stand, as the goal
    page's icons say it: todo, doing, done or blocked for Rouh's, "" when the
    step has no part for Rouh; todo or done for the person's, "" when nothing
    is asked of them: a step of Rouh's alone, with no decision or action of
    theirs in it, is complete when Rouh has done it (fr_5404edbbea30).

    Blocked is Rouh stopped on it and needing the person to go on."""
    complete = s["status"] == "done" and not s["hollow"]
    if s["who"] not in ("rouh", "together", QUEST):
        rouh = ""
    elif s["hollow"]:
        rouh = "todo"
    elif complete or s["rouh_done"]:
        rouh = "done"
    elif s["status"] == "waiting":
        rouh = "blocked"
    elif s["status"] == "in-progress" or (s["run"] or {}).get("mode") == "now":
        rouh = "doing"
    else:
        rouh = "todo"
    if (s["who"] in ("rouh", QUEST) and not s["rouh_done"] and not s["needs"]
            and not s.get("kind")
            and not s.get("ask_yours") and s.get("done_by") != "person"):
        return rouh, ""
    return rouh, "done" if complete else "todo"


def listing(who=None, *, delegates: bool = True) -> list[dict]:
    """Every goal, newest first, each with its plan.

    `who` names the person whose scheduled steps are read: a reminder is theirs
    (`reminders._mine`). The goals themselves are the workspace's, like every
    task in it. `delegates` is as for `view`.
    """
    with _metas_read_once():
        return _listing(who, delegates=delegates)


def _listing(who, *, delegates: bool) -> list[dict]:
    from . import reminders

    goals = _goal_tasks()
    if not goals:
        return []
    by_id = {}
    if who is not None:
        by_id = {r.id: r for r in reminders.rows(who, include_done=False)}
    views = [view(g, reminders_by_id=by_id, delegates=delegates) for g in goals]
    if who is not None:
        # A goal that is also a quest says on its steps what the quest's beats will do
        # next, from the one calculation the quest's page draws too (`rouh/questcheck.py`).
        from . import questcheck

        views = [questcheck.for_goal(who, v) for v in views]
    return views


def line_for_model(v: dict) -> str:
    return (f'Task {v["number"]} "{v["title"]}" - '
            + ("understanding it, asking the person" if v["stage"] == "understanding"
               else v["progress_words"])
            + (f', due {v["deadline"]}' if v.get("deadline") else "")
            + (", PAUSED by the person" if v.get("paused") else ""))


def plan_text(v: dict) -> str:
    """The plan as lines, for Rouh to read."""
    lines = []

    def put(s: dict, indent: str) -> None:
        if s["hollow"]:
            state = "marked done with nothing made - do it again"
        elif s["rouh_done"]:
            state = ("your part done, waiting on the person's decision or action"
                     + (f" ({s['left']})" if s["left"] else ""))
        elif s["status"] == "done":
            state = ("complete, the person said so" if s.get("done_by") == "person"
                     else "complete, you did it")
        else:
            state = s["status"]
        bits = [f'{indent}{s["n"]} [id {s["id"]}] {s["title"]} - {state}, '
                f'{WHO_FOR_MODEL.get(s["who"], "done by " + s["who_words"])}']
        if s["how"]:
            bits.append(f"how: {s['how']}")
        if s.get("prep"):
            bits.append(f"what you prepare for the person first: {s['prep']}")
        if s["challenge"]:
            bits.append(f"hard part: {s['challenge']}")
        if s["solution"]:
            bits.append(f"what to do about it: {s['solution']}")
        if s.get("kind"):
            bits.append(f"asks the person for: {s['kind']}")
        if s.get("ask"):
            bits.append(("the person wrote what it asks of them: " if s.get("ask_yours")
                         else "what it asks of the person: ") + s["ask"])
        if s.get("options"):
            bits.append("options: " + " | ".join(s["options"]))
        if s.get("your_steps"):
            ticked = sum(1 for x in s["your_steps"] if x["done"])
            bits.append(f"the person's steps ({ticked} of {len(s['your_steps'])} ticked): "
                        + " | ".join(("[x] " if x["done"] else "[ ] ") + x["text"]
                                     for x in s["your_steps"]))
        if s["outcome"]:
            bits.append(f"complete when: {s['outcome']}")
        if s.get("where"):
            bits.append(f"where: {s['where']}")
        if s.get("choice"):
            bits.append((f"the person chose: {s['choice']}"
                         if s["choice"] in (s.get("options") or [s["choice"]]) else
                         f"the person chose none of the options, and wants instead: {s['choice']}"))
        if s.get("note"):
            bits.append(f"the person wrote on it: {s['note']}")
        if s["run"]:
            bits.append(s["run"]["words"])
        if s.get("yours"):
            bits.append("worded by the person")
        lines.append("; ".join(bits))
        for p in s["parts"]:
            put(p, indent + "  ")

    by_id = {s["id"]: s for s in v["steps"]}
    lanes = v.get("streams") or []
    if len(lanes) > 1:
        # Said as streams once there is more than one: which steps follow one
        # another, and which go on at the same time.
        for lane in lanes:
            lines.append(f'Stream "{lane["name"]}" ({lane["words"].lower()}):')
            for ident in lane["steps"]:
                if ident in by_id:
                    put(by_id[ident], "  - ")
        return "\n".join(lines)
    for s in v["steps"]:
        put(s, "- ")
    return "\n".join(lines)


def detail_for_model(v: dict) -> str:
    """A goal whole: what the person wrote, why it needs help, and its plan."""
    out = [f'Goal: task {v["number"]} "{v["title"]}" ({v["stage"]})'
           + (f', due {v["deadline"]} ({v["deadline_left"]})' if v.get("deadline") else
              ", no deadline") + ".",
           "What the person wrote about it:\n" + (v["about"][:6000] or "(nothing)")]
    if v["why"]:
        out.append("Why it needs help: " + v["why"])
    if v.get("direction"):
        out.append("The person redirected it, and this comes before anything in the plan it "
                   "contradicts: " + v["direction"])
    if v.get("paused"):
        out.append("The person has PAUSED this goal from its page. Start no step and no "
                   "stream (goal_step run now is refused); you may still talk it over and "
                   "change the plan. Only the person resumes it, from the goal's page.")
    st = v.get("standing") or {}
    if st.get("next"):
        out.append(f"Where it stands: {st['words']}. Next: {st['next']}")
    out.append("The plan:\n" + plan_text(v) if v["steps"] else "No plan yet.")
    return "\n\n".join(out)


def block(chat_id: str = "") -> str:
    """For the part of the system prompt that changes every turn.

    The goals in a line each, and the whole of the one this chat is about.
    """
    try:
        # Without who decides for each: nothing below says it, and reading it was
        # most of the five seconds every turn spent here before its first request,
        # on the loop every tab waits on (23 October 2026).
        views = listing(delegates=False)
    except Exception:
        log.exception("the goals could not be read")
        return ""
    if not views:
        return ""
    lines = "\n".join("- " + line_for_model(v) for v in views[:8])
    said = ("The person's goals (tasks tagged Goal; the plan is their steps, change a "
            "step with goal_step):\n" + lines)
    here = goal_of_chat(chat_id)
    if here is not None:
        v = next((x for x in views if x["id"] == here.id), None)
        if v is not None:
            said += ("\n\nThis conversation is the goal's own, and its only chat. Its "
                     "steps are not done here: each one you take up runs in the background "
                     "(goal_step with run now), its streams side by side, and a short line "
                     "lands here when one finishes. " + detail_for_model(v))
    return said


# --- the notes that start Rouh's turns ------------------------------------------


def note_to_understand(v: dict) -> str:
    """What Rouh is told when a goal has just been set: read it, and ask."""
    return (
        f"The person has just set a goal: \"{v['title']}\" (task "
        f"{v['number']}). This is its own chat. What they wrote about it:\n\n"
        f"{v['about'][:8000]}\n\n"
        "Your job now is to understand it, not to plan it yet. In a few short sentences "
        "say back what you understood, then ask the questions you need answered to make "
        "a good plan - at most five, the most important first, numbered. One of them "
        "must get at why this is a goal they need help with rather than something they "
        "would just do: what has stopped it so far, what makes it hard, or what they "
        "are unsure of. Do not make the plan in this answer. When they have answered, "
        "call plan_goal with the steps, who does each, the hard parts and what to do "
        "about them.")


#: The lines a step's run ends its last message with, which `read_step_result`
#: reads: the heading alone on its line, then one "Name: value" line each.
RESULT_HEAD = "STEP RESULT"

#: After those lines, the person's part as numbered steps (`YOUR_STEPS`).
RESULT_STEPS = "Steps"


def brief_for_step(goal_view: dict, step: dict, *, why: str) -> str:
    """What a background run is asked to do for one step (`timekeeper.do_step`).

    The step, the goal around it, where its explainer page goes, and the few
    lines to end on that say what now needs the person (`read_step_result`).
    """
    folder = step.get("folder") or ""
    parts = [f"{why} Do step {step['n']} of the goal \"{goal_view['title']}\" (task "
             f"{goal_view['number']}): \"{step['title']}\"."]
    if goal_view.get("direction"):
        parts.append("The person redirected the goal, and this comes before anything below "
                     f"it contradicts: {goal_view['direction'].rstrip('.')}.")
    from . import delegation

    decides = delegation.work_line_any(task_id=goal_view.get("id") or "")
    if decides:
        parts.append(decides + " So a decision you end on goes to them.")
    lane = lane_of(goal_view, step["id"])
    if lane is not None and len(goal_view.get("streams") or []) > 1:
        parts.append(f"It is in the stream \"{lane['name']}\". The other streams are "
                     "being worked by other runs at the same time, so do this step only.")
    if step["how"]:
        parts.append(f"How: {step['how']}")
    if step.get("prep"):
        parts.append(f"Your part is to get it ready for the person before anything is "
                     f"asked of them: {step['prep']} Do all of that you can, and leave them "
                     "only what really is theirs - the choice, the sign-in, the payment - "
                     "saying exactly what that is and where they do it.")
    if step["challenge"]:
        parts.append(f"The hard part: {step['challenge']} What to do about it: "
                     f"{step['solution'] or 'work it out.'}")
    if step.get("outcome"):
        parts.append(f"The step is complete when: {step['outcome']}")
    if step.get("ask"):
        parts.append(f"What it asks of the person ({step.get('kind') or 'action'}): "
                     f"{step['ask']}"
                     + (f" Options: {' | '.join(step['options'])}." if step.get("options")
                        else ""))
    if step.get("choice"):
        if step["choice"] in (step.get("options") or [step["choice"]]):
            parts.append(f"The person chose: {step['choice'].rstrip('.')}.")
        else:
            parts.append("The person chose none of the options, and wants instead, in their "
                         f"own words: {step['choice'].rstrip('.')}.")
    if step.get("note"):
        parts.append(f"What the person wrote on this step: {step['note']}")
    if step.get("yours"):
        parts.append("The person reworded this step themselves: do it the way it says "
                     "now, and leave what it asks of them as they wrote it.")
    parts.append(
        "\n\n## What to make\n\n"
        f"The step already has its folder: `{workspace_repo.in_run(folder)}/`. Do not make a task or a "
        "step folder, and do not write a new numbered step. Put what you make in that "
        f"folder, and above all one visual explainer page, `{workspace_repo.in_run(folder)}/{EXPLAINER}`: "
        "one self-contained HTML file that shows the person, at a glance, what you did "
        "and found - comparisons side by side, the numbers, what you recommend and why, "
        "your sources - and, at the top, what is now theirs to decide or do. That page is "
        "the step's result: it is what the step's own page opens. "
        + protected.WORDS + " Never change Rouh's own code, its settings or this server. "
        "This page replaces the PAGE line: do not write one."
        "\n\n## How to end\n\n"
        "End your last message with these lines, exactly this shape, and nothing after "
        "them:\n\n"
        f"{RESULT_HEAD}\n"
        "Status: done (you did it) or waiting (you could not do it without them, or you "
        "cannot tell whether it worked)\n"
        "Needs: decision, action or nothing\n"
        "Ask: one line starting with the verb: what they have to decide or do, and where; "
        "with waiting, what stopped you and why\n"
        "Options: for a decision, the choices, separated by |\n"
        f"{RESULT_STEPS}:\n"
        "1. the first thing they do, on its own line\n"
        "2. the next, and so on\n\n"
        "The steps are the person's part broken down so they can follow it with nothing "
        "else open, one concrete thing each, in order, and every point of it: each says "
        "exactly where (the address, the menu path, the button's name) and what to enter "
        "or choose, and they tick each one off on their page. Leave Steps out when there "
        "is nothing for them to do but look and say.\n\n"
        "A decision is what is decided and its options; an action is what only they can "
        "do (sign in, pay, approve). Never ask them to look over, check, confirm or "
        "approve what you made: they do not review your work. When you did the step and "
        "judge it done, say Status: done and Needs: nothing, and the step is complete "
        "and the goal carries on by itself. Ask for a decision or an action only when one "
        "really is theirs and you cannot take it. If you genuinely cannot tell whether "
        "what you did worked, say Status: waiting and, in Ask, what you could not tell "
        "and why.")
    return " ".join(parts[:-1]) + " " + parts[-1]


def read_step_result(final: str) -> dict:
    """The lines a step's run ended on, as {"status", "kind", "ask", "options",
    "your_steps"}.

    Anything missing is left out, and a run that wrote none of it is {}: its
    step is then judged by whether it made anything (`run_finished`)."""
    text = str(final or "")
    at = text.rfind(RESULT_HEAD)
    if at < 0:
        return {}
    out: dict = {}
    for line in text[at + len(RESULT_HEAD):].splitlines():
        name, colon, value = line.partition(":")
        if not colon:
            continue
        name, value = name.strip().strip("*- ").lower(), value.strip()
        if name == "status":
            word = value.split()[0].lower().strip(".,") if value else ""
            out["status"] = "waiting" if word in ("waiting", "blocked", "stuck") else "done"
        elif name == "needs":
            kind = _kind(value.split()[0] if value else "")
            if kind:
                out["kind"] = kind
            elif value.lower().startswith(("nothing", "none", "review")):
                # A review is nothing asked of the person (fr_5404edbbea30).
                out["kind"] = ""
        elif name == "ask" and value:
            out["ask"] = _words(value, 400)
        elif name == "options" and value:
            out["options"] = _options([o for o in value.split("|")])
        elif name == RESULT_STEPS.lower():
            break
    steps_at = re.search(rf"^\W*{RESULT_STEPS}\W*:\s*$", text[at:], re.M | re.I)
    if steps_at:
        lines = []
        for line in text[at + steps_at.end():].splitlines():
            if re.match(r"^\s*(?:\d{1,2}[.)]|[-*\u2022])\s+\S", line):
                lines.append(line)
            elif line.strip() and lines:
                break
        said = _your_steps(lines)
        if said:
            out["your_steps"] = [x["text"] for x in said]
    return out


def step_of_job(job_id: str):
    """The step a background run was started on, and its goal, or (None, None)."""
    if not job_id:
        return None, None
    for goal in _goal_tasks():
        for row, meta, _d in _all_steps(goal):
            job = (meta.get("goal_step") or {}).get(JOB)
            if isinstance(job, dict) and job.get("id") == job_id:
                return row, goal
    return None, None


def run_finished(step, final: str, *, ok: bool = True, why: str = "") -> dict:
    """A step's background run has ended: what it made is the step's, and the
    step says what now needs the person. Returns {"status", "needs", "result"}:
    "done" when the step is now complete, "yours" when Rouh's part is done and
    a decision or action of the person's is left, "waiting" when the run
    stopped, and "complete" when the person had already marked it so.

    Its part done, with a page or file in the step's folder to show for it,
    is the step complete, unless the run said a decision or an action is left
    for the person (`ROUH_DONE`); nothing waits on them to look it over
    (fr_5404edbbea30). A run that could not finish, made nothing, or could not
    tell whether it worked leaves the step waiting on the person with the
    reason, so the stream says it is stuck rather than that Rouh is on it."""
    said = read_step_result(final) if ok else {}
    result = result_of(step)
    meta = _meta(_folder(step) or Path("/-"))
    block = meta.get("goal_step") if isinstance(meta.get("goal_step"), dict) else {}
    theirs = block.get("worded_by") == "person" or block.get("asked_by") == "person"
    if is_complete(meta) and block.get("done_by") == "person":
        # Petar, 28 September 2026: "i keep marking it as completed, and it
        # keeps unmarking itself." He pressed Mark as complete at 12:59 while
        # step 67-01's run was still going, and when it ended at 13:01 it
        # turned the step back into Rouh's part done, waiting on him. Only the
        # person says a step is complete, and only the person takes it back
        # (Reopen): a run that ends after that leaves the step as it is, and
        # what it made is still the step's, on its page.
        change_step(step, run={})
        return {"status": "complete", "needs": "", "result": result}
    if ok and result and said.get("status") != "waiting":
        fields: dict = {}
        if not theirs:
            if said.get("kind"):
                fields["kind"] = said["kind"]
            if said.get("ask"):
                fields["ask"] = said["ask"]
            if said.get("options"):
                fields["options"] = said["options"]
        if said.get("your_steps"):
            # His part, step by step: instructions, never what he wrote.
            fields["your_steps"] = said["your_steps"]
        left = _left_for_person(block, said)
        change_step(step, status="done", left=left, run={}, **fields)
        return {"status": "yours" if left else "done", "needs": left, "result": result}
    if not ok:
        left = f"Rouh's run on this step could not finish: {why or 'it did not say why'}."
    elif not result:
        left = ("Rouh's run on this step ended without an explainer page or anything else "
                "in the step's folder" + (f": {said['ask']}" if said.get("ask") else "."))
    else:
        left = said.get("ask") or "Rouh's run stopped on this and needs you to unblock it."
    change_step(step, status="waiting", stuck=left, run={})
    return {"status": "waiting", "needs": left, "result": result}


def _left_for_person(block: dict, said: dict) -> str:
    """What a step's finished run leaves for the person, or "" when the step is
    complete: a decision or an action the run said is theirs (`read_step_result`),
    or the one they wrote into the step themselves and have not answered yet.
    A run that wrote no result lines is judged by the step: a step of Rouh's
    alone asks nothing, one with a decision or action in it asks that."""
    kind = said["kind"] if "kind" in said else (
        "" if block.get("who") == "rouh" else _kind(block.get("kind")))
    if kind in KINDS:
        return said.get("ask") or _words(block.get("ask"), 400) or {
            "decision": "Make the decision this step is for.",
            "action": "Do what is left of this step."}[kind]
    theirs = _kind(block.get("kind"))
    if (block.get("asked_by") == "person" and theirs and block.get("ask")
            and not block.get(CHOICE) and not block.get(NOTE)):
        return _words(block["ask"], 400)
    return ""


def retire_stream_chats() -> list[str]:
    """Take the chats streams were worked in out of the chat list, and forget them.

    From the afternoon of 27 September 2026, when every stream of a goal had a
    chat of its own (`STREAM_CHATS`). Nothing is deleted: each chat is marked
    archived, which the chat list leaves out (`conversations.all_chats`), and
    stays owned by the goal's task, so its history is read on the task's page
    and at its own address. The goal forgets which stream it was. Returns the
    chats taken out; a no-op once done."""
    st = _store()
    if st is None:
        return []
    gone = []
    for goal in _goal_tasks():
        folder = _folder(goal)
        if folder is None:
            continue
        meta = _meta(folder)
        block = meta.get("goal") if isinstance(meta.get("goal"), dict) else {}
        if STREAM_CHATS not in block:
            continue
        chats = block.get(STREAM_CHATS) if isinstance(block.get(STREAM_CHATS), dict) else {}
        for chat_id in chats.values():
            chat_id = str(chat_id or "")
            if chat_id and chat_id != block.get("chat") and st.get_chat(chat_id) is not None:
                st.update_chat(chat_id, state="archived")
                gone.append(chat_id)
        block.pop(STREAM_CHATS, None)
        meta["goal"] = block
        _write_meta(folder, meta)
    return gone


def _flat(items) -> list[dict]:
    out = []
    for s in items:
        out.append(s)
        out.extend(_flat(s["parts"]))
    return out


def step_in(v: dict, step_id: str) -> dict | None:
    def walk(items):
        for s in items:
            if s["id"] == step_id:
                return s
            found = walk(s["parts"])
            if found:
                return found
        return None

    return walk(v["steps"])
