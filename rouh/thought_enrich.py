"""A thought's enriched version: researched, thought through, expanded, with a visual explainer.

Petar, 14 October 2026 (fr_f2b63641423a): "that thoughts feature - I would love it if when you
receive a new one, you go out and research and think about it and expand it and make a new task
with visual explainer that I can click from the thought list page and detail page and see the
enriched version".

So every new thought (`thoughts.capture`, wherever it came from) is taken further by itself:

- **A task of its own.** Rouh makes a numbered task for it, the way it makes a goal's
  (`owning.new_task`), with his words in `the-original-thought.md`, and files it into the project
  it belongs in (`runtime.NewTasks`) before anything is asked of the run, so the run is told the
  folder the task will stay in. It is a task like any other: in the task browser, on the board,
  with its run under it.
- **A run that writes the enriched version.** The person's own assistant, through the one start
  path (`starting.start`, preset `assistant_job`), owned by that task: it researches the thought,
  thinks it through and writes the task's first step, whose page opens with his words exactly as
  he said them and goes on to the expanded write-up and a visual explainer, made with the
  workspace's own `bb-visual-explainer`. Nothing new draws it: a step's page is what Rouh already
  shows best.
- **The thought keeps track.** `starting` from the moment it is kept, `running` once the run took
  it, then `done` with the page, or `failed` with why. A finished run is handed here by whatever
  reports it (`assistant_job.Lander._goal_step_done`, which both landers share), and a run that
  ended without being handed here is read off its row (`settle`), so a thought never says
  Enriching for ever. A failed one can be tried again, in the same task.
- **And researched again whenever he asks.** Petar, 15 October 2026: "Can you give me a button to
  force research again manually?" Research again starts a fresh run in the same task, which
  writes its next step and leaves the earlier enriched version as it was; the earlier one stays
  the one the thought opens until the new one is made. A thought kept before there was any of
  this is researched the first time the same way.

The thought itself is never touched by any of it: its words, title and topics are the person's,
and the enriched version sits beside them.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import re
import time
from pathlib import Path

from . import owner as _owner
from . import workspace_repo

log = logging.getLogger("rouh.thought_enrich")

#: The states a thought's enriched version is in. "" is a thought kept before there was one.
STATES = ("starting", "running", "done", "failed")
#: How long a new thought waits before its run is started, in seconds: a thought said as
#: "thought: ..." is kept by code before the model reads it, and the model then gives it a
#: title and topics a moment later (`thoughts.capture`). The task is named after that title.
SETTLE = 20.0
#: A thought still "starting" this long after it was kept never got a run: Rouh restarted in
#: between. It says so, and can be tried again.
NEVER_STARTED = 15 * 60
#: A run that has ended but was never handed here is given this long for its landing to arrive
#: before the thought is read off what is on disk.
LANDING_GRACE = 10 * 60
#: The task's note with the person's words, beside the steps.
WORDS_FILE = "the-original-thought.md"

_STEP = re.compile(r"^\d+-\d+\.")


class Hooks:
    """What the runtime lends: starting a run, and telling everyone a task was made and filing it."""

    start = None       # async (**fields) -> {"id": ...}; raises starting.CannotStart
    made_task = None   # async (task_id) -> None: announced, then filed into its project


hooks = Hooks()

#: The runs being started, so that a thought is never started twice at once.
_starting: set[int] = set()
_tasks: set[asyncio.Task] = set()


# --- what the page is told --------------------------------------------------------------------


def _task(task_id: str):
    from . import owning

    st = owning.store()
    if st is None or not task_id:
        return None
    with contextlib.suppress(Exception):
        return st.get_task(task_id)
    return None


def view(t) -> dict | None:
    """The enriched version, as the page draws it, or None for a thought that has none."""
    state = t.enrich_state or ""
    if not state:
        return None
    task = _task(t.enrich_task)
    out = {"state": state, "why": t.enrich_why or "", "started_at": t.enrich_at,
           "done_at": t.enrich_done_at, "run": t.enrich_run or "", "task": None, "page": "", "address": ""}
    if task is not None:
        out["task"] = {"id": task.id, "number": task.number, "title": task.title, "folder": task.folder or ""}
    if t.enrich_page and task is not None and task.folder:
        # The newest enriched version made, which is still there to open while it is being
        # researched again, or after a fresh pass failed.
        rel = f"{task.folder}/{t.enrich_page}"
        out["page"] = rel
        # The page on the canvas, inside its task, as a task's address opens one (`address.js`).
        out["address"] = "/task/" + "/".join(rel.split("/"))
    return out


# --- finding the page ---------------------------------------------------------------------------


def _root() -> str:
    from .config import config

    root = getattr(config, "assistant_repo", "") or ""
    return root if root and os.path.isdir(root) else ""


def _inside(rel: str, folder: str) -> str:
    """`rel` as a path inside the task's folder, or "" when it is not in it."""
    rel = str(rel or "").strip().strip("/")
    if rel.startswith("workspace/"):
        rel = rel[len("workspace/"):]
    if not folder or not rel.startswith(folder.rstrip("/") + "/"):
        return ""
    return rel[len(folder.rstrip("/")) + 1:]


def _is_page(inner: str) -> bool:
    parts = inner.split("/")
    return len(parts) == 2 and bool(_STEP.match(parts[0])) and parts[1].lower() == "index.html"


def _step_key(path: Path):
    head = path.name.split(".", 1)[0].split("-")
    return tuple(int(x) if x.isdigit() else 0 for x in head)


def find_page(folder: str, files=(), final: str = "", *, earlier: str = "") -> str:
    """The enriched page, inside the task's folder: the one the run named, else one it committed,
    else the newest step's page on disk that is not `earlier`, the version made before this run.
    "" when there is none."""
    from .assistant_job import PAGE_LINE

    named = PAGE_LINE.search(final or "")
    picks = ([named.group("path")] if named else []) + sorted((str(f) for f in files or [] if f), reverse=True)
    root = _root()
    found = [inner for inner in (_inside(rel, folder) for rel in picks)
             if inner and _is_page(inner) and (not root or (Path(root) / folder / inner).is_file())]
    # What it made fresh before the earlier version it may also have touched.
    for inner in [x for x in found if x != earlier] + found:
        return inner
    if root and folder:
        here = Path(root) / folder
        with contextlib.suppress(OSError):
            for step in sorted((p for p in here.iterdir() if p.is_dir() and _STEP.match(p.name)),
                               key=_step_key, reverse=True):
                if (step / "index.html").is_file() and f"{step.name}/index.html" != earlier:
                    return f"{step.name}/index.html"
    return ""


# --- the brief ----------------------------------------------------------------------------------


def brief_of(t, task, zone=None) -> str:
    """What the run is told: the thought word for word, the task it writes into, and the page."""
    from . import thoughts

    said = thoughts.said_when(t.said_at, zone)
    how = thoughts.SOURCES.get(t.source, t.source).lower()
    number = task.number if task.number is not None else ""
    lines = [
        f"‹Owner› kept a new thought in Rouh, and wants it taken further: research it, think it "
        f"through, expand on it, and make the enriched version of it as a page with a visual "
        f"explainer that ‹he› opens from ‹his› Thoughts page.",
        "",
        "## The thought, in ‹his› own words",
        "",
        f"Thought {t.id}, “{t.title}”, kept {said} ({how}):",
        "",
        *("> " + line if line else ">" for line in t.words.split("\n")),
    ]
    if t.tags:
        lines += ["", "Topics Rouh read in it: " + ", ".join(t.tags) + "."]
    if t.follows:
        earlier = type(t).objects.filter(id=t.follows, org_id=t.org_id, user_id=t.user_id).first()
        if earlier is not None:
            lines += ["", f"It follows up ‹his› earlier thought {earlier.id}, “{earlier.title}”:", "",
                      *("> " + line if line else ">" for line in earlier.words.split("\n"))]
    lines += [
        "",
        "## Where it goes",
        "",
        f"Rouh has already made the task for it: task {number}, “{task.title}”, at "
        f"`{workspace_repo.in_run(task.folder)}` (its id is `{task.id}`), with ‹his› words in "
        f"`{task.folder}/{WORDS_FILE}`. Write the enriched version into that task as its "
        f"{'next' if t.enrich_page else 'first'} step, made with the command the rules below give "
        f"(`--type step --owner {task.id}`), with the step's page as its `index.html`, and do not "
        f"make another task. If the folder is not in your checkout, run `git pull --rebase origin "
        f"main` once. Write the task's AGENTS.md, its status and its summary the way the "
        f"workspace's rules say.",
    ]
    if t.enrich_page:
        lines += [
            "",
            "## Researched again",
            "",
            f"‹He› asked for it to be researched again. The task already has an enriched version, "
            f"`{task.folder}/{t.enrich_page}`: read it, leave it exactly as it is, and make this pass "
            f"a new step that goes further - research it afresh, look for what the earlier one "
            f"missed or got wrong, and think it through again rather than copying it.",
        ]
    lines += [
        "",
        "## The page",
        "",
        "Make it with the workspace's `bb-visual-explainer` skill, so it is a visual explainer "
        "rather than an essay, and readable on a phone. In it:",
        "",
        "1. ‹His› thought first, word for word, quoted and marked as ‹his›. Never reword it, and never "
        "change it anywhere else either: the thought itself stays as ‹he› said it.",
        "2. What it is really about: the idea said sharply in a sentence or two, and the questions "
        "it raises.",
        "3. What is known: research on the web - evidence for and against, prior work, who else "
        "has thought about it and what they concluded - each finding with its source, the way your "
        "agent instructions say.",
        "4. Your own thinking: where it leads, what it implies, what would show it right or wrong, "
        "and two or three concrete next steps ‹he› could take with it.",
        "5. At least one diagram drawn in the page itself (boxes and arrows, a map of the ideas "
        "around it, cause and effect) that makes the idea graspable at a glance.",
        "",
        "Nothing is to be sent to anybody, and nothing is bought or signed up for.",
    ]
    # A worker's brief, past the place model requests have the owner's marks filled in.
    return _owner.say("\n".join(lines), t.user_id)


# --- starting -----------------------------------------------------------------------------------


def _mine(who, ident: int):
    from .models import Thought

    return Thought.objects.filter(id=int(ident), org_id=str(who.org_id), user_id=str(who.user_id)).first()


def _set(t, **fields) -> None:
    for key, value in fields.items():
        setattr(t, key, value)
    type(t).objects.filter(id=t.id).update(**fields)


def mark_starting(who, ident: int, *, again: bool = False) -> bool:
    """Say at once that it is being enriched, before the run is started. False when it is already
    under way, or done and not asked for `again`, so it is never started twice. The enriched
    version it already has is kept until a new one is made."""
    t = _mine(who, ident)
    if t is None or t.enrich_state in ("starting", "running") or (t.enrich_state == "done" and not again):
        return False
    _set(t, enrich_state="starting", enrich_why="", enrich_run="", enrich_at=time.time(), enrich_done_at=None)
    return True


async def begin(who, ident: int, *, delay: float = SETTLE, again: bool = False) -> bool:
    """Enrich a thought that has just been kept, try a failed one again, or with `again` research
    one that is done once more. Returns once it says it is being enriched; the task and the run
    are made on a task of their own. False when there was nothing to begin."""
    ident = int(ident)
    if ident in _starting:
        return False
    _starting.add(ident)
    try:
        if not await asyncio.to_thread(lambda: mark_starting(who, ident, again=again)):
            _starting.discard(ident)
            return False
    except BaseException:
        _starting.discard(ident)
        raise
    job = asyncio.get_running_loop().create_task(_begin(who, ident, delay))
    _tasks.add(job)
    job.add_done_callback(_tasks.discard)
    return True


async def _begin(who, ident: int, delay: float) -> None:
    from . import thoughts

    try:
        if delay:
            await asyncio.sleep(delay)
        try:
            await _start(who, ident)
        except Exception as exc:  # noqa: BLE001 - said on the thought, which can be tried again
            why = str(exc).strip() or type(exc).__name__
            log.warning("thought %s could not be enriched: %s", ident, why)
            t = await asyncio.to_thread(_mine, who, ident)
            if t is not None:
                await asyncio.to_thread(_set, t, enrich_state="failed", enrich_why=_said(why),
                                        enrich_done_at=time.time())
        await thoughts.tell(who)
    finally:
        _starting.discard(ident)


def _said(why: str) -> str:
    why = " ".join(str(why or "").split())
    if len(why) > 300:
        why = why[:299].rsplit(" ", 1)[0] + "…"
    return why if why.endswith((".", "!", "?", "…")) else why + "."


def _make_task(t):
    """The thought's own task, made now, or the one it already has when it is tried again."""
    from . import owning, steps

    task = _task(t.enrich_task)
    if task is not None and task.archived_at is None and task.folder:
        return task, False
    # Made by Thoughts, not by him: it is kept out of his own task list, under Made by Rouh
    # (`rouh/task_origin.py`), and its steps are Thoughts' too.
    from . import task_origin

    with task_origin.making("thoughts", f"the task of thought {t.id}"):
        task = owning.new_task(t.title or "A thought")
    root = _root()
    if task is None or not task.folder or not root:
        raise RuntimeError("There is no workspace on this machine to make its task in")
    path = Path(root) / task.folder / WORDS_FILE
    path.write_text(f"# The original thought\n\nThought {t.id}, kept in Rouh at /thoughts/{t.id}, in "
                    f"{_owner.say('‹owner›', t.user_id)}'s own words. Rouh keeps the thought itself; this is a copy for the steps "
                    f"here to start from, and it is never reworded.\n\n" + "\n".join(
                        "> " + line if line else ">" for line in t.words.split("\n")) + "\n",
                    encoding="utf-8")
    steps.own_as_workspace(path, Path(root))
    _set(t, enrich_task=task.id)
    return task, True


async def _start(who, ident: int) -> None:
    from . import clock, starting

    t = await asyncio.to_thread(_mine, who, ident)
    if t is None or t.enrich_state != "starting":
        return
    if hooks.start is None:
        raise RuntimeError("Background runs cannot be started here")
    task, new = await asyncio.to_thread(_make_task, t)
    if new and hooks.made_task is not None:
        # Announced and filed into its project before the run is told where it is, so the
        # folder it is told is the one it stays in.
        with contextlib.suppress(Exception):
            await hooks.made_task(task.id)
        task = await asyncio.to_thread(_task, task.id) or task
    brief = await asyncio.to_thread(brief_of, t, task, clock.zone_of(who))
    try:
        got = await hooks.start(brief=brief, title=(f"Research thought {t.id} again: {t.title}" if t.enrich_page
                                                    else f"Enrich thought {t.id}: {t.title}")[:80],
                                preset="assistant_job", owner=("task", task.id), org_id=str(who.org_id))
    except starting.CannotStart as exc:
        raise RuntimeError(f"The research could not be started: {exc}") from exc
    run = str((got or {}).get("id") or "")
    if not run:
        raise RuntimeError("The research could not be started: nothing took it")
    await asyncio.to_thread(_set, t, enrich_state="running", enrich_run=run)
    log.info("thought %s is being enriched by run %s in task %s (%s)", t.id, run, task.number, task.folder)


# --- finishing ----------------------------------------------------------------------------------


def _of_run(run_id: str):
    from .models import Thought

    if not run_id:
        return None
    return Thought.objects.filter(enrich_run=str(run_id)).first()


async def run_finished(run_id: str, files=(), final: str = "", *, ok: bool = True, why: str = "",
                       copy=None, sha=None) -> bool:
    """A background run has ended. True when it was a thought's enrichment, and handled.

    Called by whatever reports a finished run (`assistant_job.Lander`, `one_jobs.OneLander`)
    before it draws or says anything: the thought says it, on the Thoughts page, and nothing is
    drawn in a chat. What it made is waited for in this machine's copy of the workspace first, so
    the page is there when the thought says it is ready."""
    t = await asyncio.to_thread(_of_run, run_id)
    if t is None:
        return False
    if t.enrich_state == "done":
        return True
    task = await asyncio.to_thread(_task, t.enrich_task)
    folder = task.folder if task is not None else ""
    if ok and copy is not None and folder:
        from .assistant_job import PAGE_LINE

        named = PAGE_LINE.search(final or "")
        made = [f"{folder}/{inner}" for inner in (_inside(f, folder) for f in
                ([named.group("path")] if named else []) + list(files or [])) if inner and _is_page(inner)]
        if made:
            with contextlib.suppress(Exception):
                await copy.update(made[0], sha)
    page = (await asyncio.to_thread(lambda: find_page(folder, files, final, earlier=t.enrich_page))
            if ok else "")
    if page:
        await asyncio.to_thread(_set, t, enrich_state="done", enrich_page=page, enrich_why="",
                                enrich_done_at=time.time())
    else:
        await asyncio.to_thread(_set, t, enrich_state="failed", enrich_done_at=time.time(), enrich_why=_said(
            ("The research run did not finish: " + why) if (not ok and why) else
            "The research run finished without making the enriched page"))
    log.info("thought %s: its enrichment run %s ended, %s", t.id, run_id, t.enrich_state)
    await _tell_owner(t)
    return True


async def _tell_owner(t) -> None:
    from types import SimpleNamespace

    from . import thoughts

    await thoughts.tell(SimpleNamespace(org_id=t.org_id, user_id=t.user_id))


def settle(t) -> bool:
    """Read a thought still being enriched off its run, for a run that ended without being handed
    here (stopped, lost, or Rouh restarted while it landed). True when it changed."""
    from . import runs

    now = time.time()
    if t.enrich_state == "starting":
        if t.id in _starting or now - float(t.enrich_at or now) < NEVER_STARTED:
            return False
        _set(t, enrich_state="failed", enrich_done_at=now,
             enrich_why="It never started: Rouh restarted before its research run began.")
        return True
    if t.enrich_state != "running" or not t.enrich_run:
        return False
    row = runs.get(t.enrich_run)
    if row is None:
        return False
    status = runs.status_of(row)
    ended = float(row.ended_at or row.updated_at or row.started_at or now)
    if status in ("failed", "lost", "killed"):
        pass
    elif status in ("done", "idle", "reaped") and now - ended >= LANDING_GRACE:
        pass
    else:
        return False
    task = _task(t.enrich_task)
    page = find_page(task.folder if task is not None else "", earlier=t.enrich_page)
    if page:
        _set(t, enrich_state="done", enrich_page=page, enrich_why="", enrich_done_at=now)
    else:
        _set(t, enrich_state="failed", enrich_done_at=now,
             enrich_why=("The research run stopped before it made the enriched page." if status in
                         ("failed", "lost", "killed") else
                         "The research run finished without making the enriched page."))
    return True


__all__ = ["LANDING_GRACE", "NEVER_STARTED", "SETTLE", "STATES", "WORDS_FILE", "begin", "brief_of", "find_page",
           "hooks", "mark_starting", "run_finished", "settle", "view"]
