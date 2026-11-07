"""Jobs in the person's assistant workspace, and what happens when one stops.

The workspace is the repository the person's assistant works in, and the
person's assistant is these jobs: Claude Code (or Codex) running as workers on
this server, never software the person runs on a computer of their own. Where
it is, is the installation's setting (``ROUH_WORKSPACE``); it is a repository
of its own, beside Rouh's code and never inside it. (Until 21 September 2026 it
was also kept on a laptop and synced through GitHub, from 21 September to 21
October 2026 it was ``workspace/`` inside Rouh's code; neither is so now.) The
person's own assistant does all of their real work; Rouh is the voice, the screen and the manager of the assistant's jobs,
and answers only quick things itself.

A job is an ordinary crew job with the ``assistant`` profile. It runs as the
``assistant`` Linux user, in its own checkout of that repository, on the
person's Claude subscription, and it follows the workspace's own rules, so it
ends the way a terminal session would: whatever the request needed, committed.

When it stops, its commits are moved onto main and pushed (``CrewManager.land``),
and the deploy that follows brings them to the copy this machine serves. Then its
result goes on the screen and Rouh says it out loud, whatever kind of result it
is:

- it made a page: the page itself, opened on the canvas once this machine's
  copy of the workspace has it (``WorkspaceCopy``), and no card - it is found
  again on its task's own page, on its subtask's line (`objectindex._level`)
- it changed files but made no page: a card with its summary and the files
- it changed nothing, because it only answered: a card with the answer
- its work collides with a change made on main while it ran: it is sent back,
  with no card and nothing said, to fix the clash itself, and its next stop
  lands it the normal way; a "Needs you" card goes up only when it cannot be
  sent back, or when that second try collides too

The workspace knows nothing about any of this. Rouh reaches in; the workspace
never reaches back.
"""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

from . import (artifacts, browser_handoff, citing, conflicts, conversations, follow_through, job_phone, mail_flow,
               notices, outbox, pages, run_report, runs, task_origin, thought_enrich)
from . import steps as steps_module
from .crew import WorkerProfile, _run, _running_as_root
from .memory import ANSWERING, answering_in

log = logging.getLogger("rouh.assistant_job")

PROFILE = "assistant"

#: What ``CrewManager.land`` says when a job has no commits it has not landed.
NOTHING_NEW = "nothing new to land"

#: How many times a fresh job is started to redo work whose own worker is gone
#: before the person is asked instead. One: a second redo that collided the same
#: way is a sign the two changes are answers to the same question, and that is
#: exactly what the person is there to decide.
REDO_TRIES = 1

#: How many times a job is sent back to fix one clash itself before the person
#: is asked. One, so it can never go round for ever.
FIX_TRIES = 1

#: How many changed files a card lists before it says "and N more".
FILES_SHOWN = 12

PROFILE_INSTRUCTIONS = (
    "This is a job in the person's assistant workspace, running as the Linux user "
    "`assistant`. Work only inside this checkout. Commit on this branch as the "
    "workspace's own rules say, but do not push and do not switch to main: when "
    "you stop, Rouh lands your commits on main through `land.sh`, which is the "
    "only thing here allowed to push. If your work collides with something that "
    "landed while you worked, you are sent both sides and asked to reconcile them "
    "yourself rather than the job being abandoned."
)

BRIEF = """{request}

---

## Where this came from

The person asked Rouh, their voice assistant, for this, by voice or typed, instead of typing it to you in the terminal. You are their assistant and this is their workspace, so handle it exactly as you would in the terminal, under the rules in its AGENTS.md. It can be anything: a question to answer, a document, a draft, a plan, code, a change to a file, or a page. Where those rules call for them, that includes the task and step folders, testing, the task's AGENTS.md, its status and its summary, and the commit. A task's status and summary are kept in Rouh's database and nowhere else: change them with `rouh-task status <number> <status>` and `rouh-task summary <number> "<50 to 90 words>"`, run from inside the workspace, never in a file and never in `_tasks.md`, which Rouh generates from its database. A task's steps, groups, arrows, tags and question are its meta, also kept in Rouh's database: see it with `rouh-task meta <number>` and change it with `rouh-task meta <number> merge '<JSON>'`. If `rouh-task` says it could not reach Rouh, say so in your last message rather than writing either anywhere else.

{where_it_is} It is a tree: Work and Personal are projects at the top, each category is a project inside one of them, and a task sits under the project that owns it, so a task is `{ws}work/acme/19.pricing` rather than `tasks/19.pricing`. Which project holds which task is written twice on purpose - the folder the task is in, and a row in Rouh's object database - and `{ws}README.md` explains the whole of it.

**Do not make a task or a step folder by hand.** The database allocates the number, and a folder you make yourself will take one that is already taken. Make it with the command, which writes the row and then the folder, the `.object.json` and the `AGENTS.md` out of that row:

    rouh objecttree create "What it is called" --type task --owner <the owner's id>
    rouh objecttree move <id> --to <the new owner's id>
    rouh objecttree tree      # every object and its id
    rouh objecttree verify    # the folders and the rows still agree

Writing the words - the task's AGENTS.md, its summary (50 to 90 words: what it is, where it stands, what is open, set with `rouh-task summary`), the step's page - is still yours; all but the summary are files like any other. Rouh shows a `.md` by its file name and never by the heading inside it, so name every `.md` you write for what is in it, in a few plain words after its step's number: `61-01.site-plan-and-copy.md`, never `61-01.notes.md` or `61-01.what-was-done.md`.

Nobody can answer a question while you work. Where something is unclear, make the sensible choice, say in your last message which choice you made, and carry on.

Never end your work with a question for the person, and never put one in a task's meta or put a task in waiting, unless the work they asked for has truly stopped without them and the answer is theirs to give: it spends money, sends or publishes in their name, cannot be undone, or needs a fact only they have. Otherwise choose yourself and end with your recommendation, on the step's page, in the task's AGENTS.md and in your last message. Research ends with a recommendation, never with "buy now or later?" or "which direction?". Rouh keeps any other question from them: ‹owner› asked for that on 18 October 2026, when ‹his› decisions list was flooded with questions nobody needed.

## What Rouh needs from you

1. Commit everything you changed before you stop. If the request needed no change, change nothing.
2. Other jobs work in this workspace at the same time and save to main while you work. So just before you commit, run `git fetch origin main`. If the step number you picked is now taken on `origin/main` (`git ls-tree --name-only origin/main {ws}<the task's folder>/` lists its steps), take the next free number instead. Change every reference to it before you commit: the folder, its notes and page, the task's AGENTS.md, and the step's entry in the task's meta (`rouh-task meta`). Never `_tasks.md`: Rouh writes that file out of its database and saves it itself.
3. If you made a page, the first line of your last message names it, as a path inside the workspace, exactly like this:

PAGE: private/personal/38.trip-planning/38-01.the-step/index.html

4. Your last message says plainly what you did or what you found, in two or three sentences. If the request was a question, those sentences are the answer. They are shown on the screen and read out loud.
5. If what you found came from the web, say where each thing came from, the way your agent instructions say: on a page, its Sources and a number after every finding; in your last message, the page's number in square brackets after each thing you took from it, like [2], and at the very end a line that says Sources with those pages numbered under it, `2. [Its title](https://its.exact/address)`. Every page you used, and only those. Rouh draws those numbers as footnotes on the screen and never reads them out.
"""

#: Nothing here writes what a job is told when its work clashes with main any
#: more. ``land.sh`` does, because it is the thing that knows what collided: it
#: hands back both sides, the files, the branch holding the work exactly as the
#: job wrote it and the sequence for reconciling the intent rather than the
#: text. ``rouh/conflicts.py`` holds the words. A template here as well was
#: how a job came to be told "keep both sides" about a conflict whose two sides
#: were answers to the same question.

#: The reports whose changed files are on main, so the task they are in is there to open.
LANDED = ("page", "files", "change")

#: The line a job writes to name the page it built, and the shape of a step's
#: own page among the files it changed. Both used to begin `tasks/`, which was
#: every task's folder while the workspace was flat; a task is under the
#: project that owns it since 21 September 2026, so both start at one of
#: `pages.TOPS` instead and take whatever depth follows. A step's page is still
#: the one inside a step folder inside a task folder, which is what stops a
#: picture in `source-code/` being reported as the deliverable.
_TOPS = "|".join(pages.TOPS)
PAGE_LINE = re.compile(
    rf"^\s*PAGE:\s*`?(?P<path>(?:{_TOPS})/\S+?/index\.html)`?\s*$", re.M)


def is_step_page(rel: str) -> bool:
    """Whether a changed file is a step's own deliverable page.

    `<a top>/.../NN.task/NN-MM.step/index.html`, at whatever depth the projects
    put the task at. It used to be said by counting - four parts, because a
    task was `tasks/NN.name` and a step one folder inside it - and counting
    stopped saying it when a task moved under the projects that own it. So the
    two folders above the file are looked at instead, which is what was always
    meant: a page in a step of a task. That is also what keeps a page built
    into `source-code/` from being reported as the deliverable.
    """
    parts = str(rel or "").split("/")
    if len(parts) < 4 or parts[-1].lower() != "index.html" or parts[0] not in pages.TOPS:
        return False
    return bool(steps_module._STEP_NAME.match(parts[-2])
                and steps_module._TASK_NAME.match(parts[-3]))


def make_profile(cfg) -> WorkerProfile:
    """The ``assistant`` profile, from the settings in config.py."""
    return WorkerProfile(
        name=PROFILE,
        run_as=cfg.assistant_user,
        run_home=cfg.assistant_home,
        worktrees_dir=Path(cfg.assistant_jobs),
        git_user=cfg.assistant_user,
        unset_env=("ANTHROPIC_API_KEY",),
        base="origin/main",
        instructions=PROFILE_INSTRUCTIONS,
        # The workspace Rouh serves is root's; a job's checkout is made from the
        # assistant's own, the one the one program makes its runs from.
        given_repo=cfg.assistant_repo or None,
        own_checkout=getattr(cfg, "workspace_space", "") or None,
    )


def compose_task(request: str) -> str:
    """A job's brief. It leaves Rouh for a worker, past the place model requests have the
    owner's marks filled in (`rouh/owner.py`), so they are filled in here, for the person
    whose request it is (the turn's, else the installation's one account)."""
    from . import owner

    return owner.say(BRIEF.format(request=request.strip(), **layout()))


def layout() -> dict:
    """Where a job's checkout holds the workspace: all of it, since the workspace became a
    repository of its own (21 October 2026), or `workspace/` in a checkout of Rouh's code,
    as it was before. A job's checkout is a worktree of whichever repository holds the
    workspace Rouh serves, so that repository says which (`rouh/workspace_repo.py`)."""
    from . import workspace_repo
    from .config import config

    prefix = workspace_repo.prefix(config.assistant_repo) if config.assistant_repo else ""
    if prefix:
        return {"ws": f"{prefix}/",
                "where_it_is": f"The workspace is `{prefix}/` inside this checkout."}
    return {"ws": "", "where_it_is": "This checkout is the person's workspace, a repository "
                                      "of its own with nothing of Rouh's code in it."}


#: A job's line on the task list while it fixes a clash it was sent back with.
FIXING = "Sent back to fix a clash with work saved to main while it ran"

#: And while a fresh job writes the change again, because this one is gone.
REDOING = "Its work collided with main and it had stopped, so job {id} is writing it again"


def fix_instruction(result) -> str:
    """What a job whose work clashes with main is sent.

    ``land.sh`` wrote it, from both sides of the collision, so this is only the
    fallback for the one case where it could not: no record, no brief, and still
    a job that has to be told something rather than left sitting.
    """
    written = str((result or {}).get("handback") or "").strip()
    if written:
        return written
    reason = re.sub(r"\s+", " ", str((result or {}).get("reason") or "")).strip() or "it did not say"
    return (
        "Rouh could not save your work to main: " + reason + "\n\n"
        "Fix it yourself, in this checkout, then stop. Run `git fetch origin main` "
        "and `git rebase origin/main` on your own branch, resolve every conflict so "
        "that both sides' intent survives - never drop one side to make the other "
        "apply - then `git add` the files and `git rebase --continue`. Run your own "
        "checks again, commit, and stop. Do not push: Rouh lands your work through "
        "`land.sh` when you stop."
    )


def pick_page(files, final_text: str = "") -> str | None:
    """Which page the job made: its own word first, then what it committed."""
    files = [f for f in (files or []) if f]
    named = PAGE_LINE.search(final_text or "")
    if named and (not files or named.group("path") in files):
        return named.group("path")
    # Not called `pages`, which is the module: the local used to shadow it here
    # and any use of the module inside this function would have found a list.
    built = sorted(f for f in files if is_step_page(f))
    if built:
        return built[-1]
    return named.group("path") if named else None


def summary_from(final_text: str, limit: int = 600) -> str:
    """The job's closing words without the PAGE line, on one line, short enough to say.

    Without its Sources list too: this is what Rouh is handed to say, and a
    list of addresses is for the screen (`citing.split_sources`).
    """
    text = PAGE_LINE.sub("", final_text or "")
    text = citing.split_sources(text)[0]
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > limit:
        text = text[: limit - 1].rsplit(" ", 1)[0] + "..."
    return text


def answer_from(final_text: str, limit: int | None = None) -> str:
    """The job's closing words without the PAGE line, with its line breaks kept.

    An answer is the whole result when a job changed nothing, so it keeps its
    shape: a text block on a card is drawn as markdown, and a list stays a list.

    Whole unless a `limit` is given: these are the words of the report in the
    chat and on its card, and the owner asked on 3 November 2026 (fr_ca65f242fcbd)
    that those are never cut; until then they were cut at 4,000 characters. A
    notice passes its own limit and stays short. One that is cut is cut before
    its Sources list and never inside it, so every page a finding points at is
    still there to be pressed.
    """
    text = PAGE_LINE.sub("", final_text or "")
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    body, sources = citing.split_sources(text)
    if not limit:
        return (body + "\n\n" + sources).strip() if sources else body
    room = max(limit // 2, limit - len(sources) - 2) if sources else limit
    if len(body) > room:
        body = body[: room - 1].rsplit(" ", 1)[0] + "..."
    return (body + "\n\n" + sources).strip() if sources else body


def saved_files(files) -> str:
    """What a job that handed a step on had saved first, in words, or ""."""
    count = len([f for f in files or [] if f])
    if not count:
        return ""
    return f"{count} file{'' if count == 1 else 's'} in the workspace"


def fingerprint(text: str) -> str:
    """A short fixed name for a job's last message, so it is reported only once."""
    return hashlib.sha256((text or "").strip().encode("utf-8")).hexdigest()[:16]


def last_assistant_text(transcript_path: str | None, tail_bytes: int = 400_000) -> str:
    """The job's final message, read from its own transcript.

    Claude Code writes one JSON object per line and the last assistant message
    is near the end, so only the tail is read: a long job's transcript runs to
    megabytes.
    """
    if not transcript_path:
        return ""
    try:
        with Path(transcript_path).open("rb") as fh:
            fh.seek(0, 2)
            fh.seek(max(0, fh.tell() - tail_bytes))
            data = fh.read().decode("utf-8", "replace")
    except OSError:
        return ""
    for line in reversed(data.splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if not isinstance(entry, dict) or entry.get("type") != "assistant":
            continue
        message = entry.get("message")
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if isinstance(content, str):
            text = content
        else:
            text = "\n".join(
                block.get("text", "") for block in content or []
                if isinstance(block, dict) and block.get("type") == "text"
            )
        if text.strip():
            return text.strip()
    return ""


#: Where git looks for programs when WorkspaceCopy runs it. Nothing else of
#: Rouh's own environment goes with it; see WorkspaceCopy.
SAFE_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"


class WorkspaceCopy:
    """This machine's copy of the workspace, waited for when a page lands.

    Rouh shows pages from this copy, and a job's commits reach it a moment
    after they land, so before a finished page is opened on the canvas it is
    checked: it is there, it may be served, and it is from the landed commit
    or later, so an older version of a page the job rewrote is never shown as
    the new one. It is asked a few times, a couple of seconds apart, because
    landing and deploying take a little longer than opening a page.

    **It pulls nothing.** Until 22 September 2026 it ran the copy's own
    ``bin/sync``, because the workspace was a repository of its own kept level
    with GitHub on a 30-second timer and a landed commit had to be fetched
    before the page existed here. What brings a landed commit here now is
    ``land.sh`` itself: a landing of the workspace's own repository moves the
    live workspace onto what it pushed (``update-all.sh --workspace``), as the
    deploy did while the workspace was `workspace/` in Rouh's own checkout, and
    there is nothing left to fetch.

    Running it anyway would have been worse than useless. `bin/sync` worked out
    its repository from the folder it sits in, and that folder is inside the
    **rouh** checkout now, so it would have fetched, merged and
    ``git push``ed *rouh's* main - past ``land.sh``, which is the only thing
    allowed to push - and a rollback, which leaves the deployment behind
    origin/main, would have been fast-forwarded straight back onto the commit
    that was rolled back. The script went with the rest of the old side; this
    is the caller that went with it.

    Its one remaining command, the ``git`` in ``has``, still runs with an empty
    environment apart from HOME and PATH, and as the user that owns the copy
    when Rouh is root.
    """

    def __init__(self, repo, user: str | None = None, home: str | None = None, *,
                 tries: int = 6, pause: float = 2.0) -> None:
        self.repo = str(repo or "")
        self.user = (user or "").strip() or None
        self.home = home or (f"/home/{self.user}" if self.user else os.path.expanduser("~"))
        self.tries = max(1, int(tries))
        self.pause = pause

    def command(self, *argv: str) -> list[str]:
        """``argv`` with a clean environment, as the copy's owner when Rouh is root."""
        path = SAFE_PATH
        git_dir = os.path.dirname(shutil.which("git") or "")
        if git_dir and git_dir not in path.split(":"):
            path = f"{git_dir}:{path}"
        clean = ["env", "-i", f"HOME={self.home}", f"PATH={path}", "SYNC_NO_NOTIFY=1", *argv]
        if self.user and _running_as_root():
            return ["runuser", "-u", self.user, "--", *clean]
        return clean

    async def update(self, page: str, sha: str | None = None) -> bool:
        """True once ``page`` can be served from this copy, at ``sha`` or later.

        Waiting, and nothing else: the deploy is what brings the commit here,
        and this asks again until it has arrived or the tries run out.
        """
        if not self.repo:
            return False
        for attempt in range(self.tries):
            if attempt:
                await asyncio.sleep(self.pause)
            if await self.has(page, sha):
                return True
        log.warning("the workspace copy at %s still lacks %s at %s after %d tries",
                    self.repo, page, sha or "any commit", self.tries)
        return False

    async def has(self, page: str, sha: str | None = None) -> bool:
        """The page is here, may be served, and holds the commit ``sha``."""
        try:
            pages.check(self.repo, page)
        except pages.Refused:
            return False
        if not sha:
            return True
        try:
            rc, _, _ = await _run(self.command(
                "git", "-C", self.repo, "merge-base", "--is-ancestor", sha, "HEAD"), timeout=15)
        except Exception:
            return False
        return rc == 0


class Lander:
    """Lands an assistant job when it stops, and puts its result in front of the person.

    Every stop is landed, but a result is shown and said once: what was
    reported is kept on the job (``reported``, the fingerprint of its last
    message), so a second stop with no new commits and nothing new said stays
    silent. A job that is answered a follow-up and says something new is
    reported again, because that is a new result.

    A job whose work clashes with a change made on main while it ran is sent
    back to fix the clash itself (``_send_back``), with no card and nothing
    said. Its next stop lands it again the normal way. The person sees "Needs
    you" only when that second try clashes too, or when the job cannot be
    sent back at all. ``fix_tries`` on the job counts the tries for the clash
    in hand, and goes back to 0 once its work is on main.

    ``copy`` is this machine's copy of the workspace (``WorkspaceCopy``). With
    one, a finished page is opened on the canvas from that copy; without one,
    it is only said where the page was saved.
    """

    def __init__(
        self,
        crew,
        memory,
        broadcast: Callable[[dict], Awaitable[None]],
        announce: Callable[..., Awaitable[Any]],
        review_url: str,
        profile: str = PROFILE,
        *,
        copy: WorkspaceCopy | None = None,
    ) -> None:
        self.crew = crew
        self.memory = memory
        self.broadcast = broadcast
        self.announce = announce
        self.review_url = review_url or ""
        self.profile = profile
        self.copy = copy
        self._locks: dict[str, asyncio.Lock] = {}
        self._tasks: set[asyncio.Task] = set()
        #: What a goal step's run is handed to when it ends, instead of being
        #: reported on its own (`timekeeper.Timekeeper.run_finished`). None
        #: where there are no goals.
        self.goal_runs = None
        #: What tells every tab a chat has become a task's
        #: (`_task_made`). None where nobody is listening.
        self.task_chat_changed: Callable[[], Awaitable[Any]] | None = None
        #: Petar's phone (`rouh/telegram.py`), and the address Rouh is reached
        #: at from outside this machine, so a finished page is sent to him as
        #: a link he can tap (`rouh/job_phone.py`). None and "" where nothing
        #: is to be sent, which is every world that is not about it.
        self.telegram = None
        self.public_url = ""
        #: Whether a job that simply finished is sent to the phone as well as
        #: one that needs him (`config.phone_done_jobs`). Off unless set.
        self.phone_done = False

    async def _goal_step_done(self, run_id: str, final: str, files, sha=None, *,
                              ok: bool = True, why: str = "") -> bool:
        """Hand a finished run to its goal step, if it is one. True when it was.

        What it made is waited for in this machine's copy of the workspace
        first, so the step's page has it when the step says it is ready.

        A thought's enrichment run is handed to its thought the same way
        (`rouh/thought_enrich.py`): the thought says it, on the Thoughts page,
        and no card is drawn for it anywhere.
        """
        try:
            if await thought_enrich.run_finished(run_id, files, final, ok=ok, why=why,
                                                 copy=self.copy, sha=sha):
                return True
        except Exception:
            log.exception("run %s could not be handed to its thought", run_id)
        if self.goal_runs is None:
            return False
        try:
            if ok and self.copy is not None:
                made = sorted((f for f in files or [] if f.lower().endswith((".html", ".htm"))),
                              key=lambda f: not f.endswith("/explainer.html"))
                if made:
                    with contextlib.suppress(Exception):
                        await self.copy.update(made[0], sha)
            return bool(await self.goal_runs.run_finished(run_id, final, ok=ok, why=why))
        except Exception:
            log.exception("run %s could not be handed to its goal step", run_id)
            return False

    async def _task_made(self, run_id: str, files) -> None:
        """The chat that asked for this job becomes the chat of the task its
        landed work made, and every tab is told (`conversations.adopt_made_task`).
        Before the report, so the report lands in that task's chat."""
        try:
            task = await asyncio.to_thread(conversations.adopt_made_task, run_id, files)
        except Exception:
            log.exception("which task run %s made could not be worked out", run_id)
            return
        if task is not None and self.task_chat_changed is not None:
            with contextlib.suppress(Exception):
                await self.task_chat_changed()
        # A task it made for somebody outside, shared with them to edit as it lands, before
        # their result is sent (`rouh/requester_share.py`).
        from . import requester_share

        with contextlib.suppress(Exception):
            await asyncio.to_thread(conversations.reconcile)   # its folder taken in first
            # What a process's run made is that process's (`rouh/task_origin.py`), before
            # the sweep, which then marks whatever of it was made for somebody else.
            await asyncio.to_thread(task_origin.mark_run_work, run_id, files)
            for said in await requester_share.sweep():
                log.info("run %s: %s", run_id, said)

    def on_event(self, mate, kind: str, payload) -> None:
        """A crew listener. It returns at once, because the hook that called is waiting."""
        meta = getattr(mate, "meta", None) or {}
        if kind != "stop" or meta.get("profile") != self.profile:
            return None
        task = asyncio.create_task(self.land(mate.id, dict(payload or {})))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return None

    async def land(self, crew_id: str, payload: dict | None = None) -> dict:
        """Land a finished job's work and put what it found in front of the person.

        One landing per job at a time: a second stop arriving mid-push would
        otherwise replay the same commits twice.

        Everything the landing then writes down - the card, and the note handed
        to Rouh to say - belongs to the conversation the job was started from,
        and not to whichever one the person has open by the time it finishes.
        That is the whole of what `answering_in` is doing here; `_card` and
        `_say` both read it back (`runs.reports_to`).
        """
        lock = self._locks.setdefault(crew_id, asyncio.Lock())
        async with lock:
            with answering_in(runs.reports_to(crew_id)), outbox.reporting(crew_id):
                return await self._land(crew_id, payload)

    async def _land(self, crew_id: str, payload: dict | None) -> dict:
        """The landing itself, inside the lock and inside its own thread."""
        try:
            result = await self.crew.land(crew_id)
        except Exception as exc:
            log.exception("landing %s failed", crew_id)
            result = {"id": crew_id, "landed": False,
                      "reason": f"{type(exc).__name__}: {exc}"}
        mate = self.crew.get(crew_id)
        title = (getattr(mate, "title", "") or "the job").strip()
        meta = getattr(mate, "meta", None) or {}
        reported = meta.get("reported")
        final = last_assistant_text((payload or {}).get("transcript_path"))
        said = fingerprint(final)
        # A step it stopped at and handed to the live browser, kept on the job
        # for as long as it sits on it, which is what makes its row wait on the
        # person (`runs.crew_run`). Every stop writes it, so the next stop
        # without one takes it off again.
        handoff = browser_handoff.find(final)
        with contextlib.suppress(Exception):
            self.crew.set_meta(crew_id, handoff=handoff.as_dict() if handoff else None)

        if meta.get("fix_tries") and (result.get("landed")
                                      or result.get("reason") == NOTHING_NEW):
            # Its work is on main, or it has none left to save, so that
            # clash is over, and a later clash is sent back again.
            with contextlib.suppress(Exception):
                self.crew.set_meta(crew_id, fix_tries=0)

        if handoff is None and (result.get("landed") or result.get("reason") == NOTHING_NEW):
            if await self._goal_step_done(crew_id, final, result.get("files"),
                                          result.get("sha")):
                result["kind"] = "goal_step"
                return result
        if result.get("landed"):
            files = [f for f in result.get("files") or [] if f]
            await self._task_made(crew_id, files)
            page = pick_page(files, final)
            if handoff is not None:
                await self._show_handoff(crew_id, title, handoff, result,
                                         saved=saved_files(files))
            elif page:
                await self._show_page(crew_id, title, page, final, result)
            else:
                await self._show_files(crew_id, title, files, final, result)
        elif result.get("reason") == NOTHING_NEW:
            if reported is not None and (reported == said or not final):
                result["kind"] = "silent"
                return result
            if handoff is not None:
                await self._show_handoff(crew_id, title, handoff, result)
            else:
                await self._show_answer(crew_id, title, final, result)
        elif await self._send_back(crew_id, mate, title, result):
            return result
        elif await self._redo(crew_id, mate, title, result):
            return result
        elif result.get("needs_person"):
            # Rung six. The conflict record is written, and the question
            # reaches the person from one place, with both sides and the
            # four choices on it (`ConflictFeed` in runtime.py). A second
            # card saying "it could not be saved" would be the same news
            # twice, and the plainer half of it.
            result["kind"] = "conflict"
            log.warning("job %s needs the person to decide its conflict: %s",
                        crew_id, result.get("question") or result.get("reason"))
        else:
            await self._goal_step_done(crew_id, final, [], ok=False,
                                       why=str(result.get("reason") or ""))
            await self._show_needs_you(crew_id, title, result)

        if result.get("kind") in ("page", "files", "answer", "handoff"):
            with contextlib.suppress(Exception):
                self.crew.set_meta(crew_id, reported=said)
        await self._phone(crew_id, title, final, result)
        return result

    # --- work that clashes with main, sent back to the job ------------------

    async def _send_back(self, crew_id, mate, title, result) -> bool:
        """Rung four: hand the conflict back to the job that wrote the code.

        The job still holds its own context and its own worktree, so it is the
        one thing that can reconcile two intents rather than two texts, and the
        one thing that can prove the result in a browser afterwards. True when
        it went: no card goes up and nothing is said, because the job's next
        stop lands it again the normal way.

        False when it cannot go: ``land.sh`` has already said this one is the
        person's (twice failed, or both sides rewrote the same thing), the job
        was already sent back for this clash (``FIX_TRIES``), the work failed to
        land for some other reason entirely, or the job cannot take a message
        because it was stopped, lost or failed, or its window is gone or holds a
        program that has exited. Rung five, ``_redo``, takes the last of those.
        """
        if not result.get("clash") or result.get("needs_person"):
            return False
        tries = int((getattr(mate, "meta", None) or {}).get("fix_tries") or 0)
        if tries >= FIX_TRIES:
            log.info("assistant job %s clashes with main again after %d tries to fix it",
                     crew_id, tries)
            return False
        # "done" is a job that has stopped and sits at its prompt.
        if getattr(mate, "status", None) != "done" or not await self._window_alive(mate):
            log.info("assistant job %s clashes with main and cannot be sent back", crew_id)
            return False
        # Counted before it is sent: a send that was never counted is the one
        # way this could go round for ever, so no count means no send.
        try:
            self.crew.set_meta(crew_id, fix_tries=tries + 1)
        except Exception:
            log.exception("could not count the fix for %s, so it is not sent back", crew_id)
            return False
        try:
            await self.crew.send(crew_id, fix_instruction(result))
        except Exception:
            log.exception("could not send %s back to fix its clash", crew_id)
            return False
        if not self._went_through(crew_id):
            log.warning("%s was sent back to fix its clash, but the message sits unsent "
                        "on its prompt", crew_id)
            return False

        result.update(kind="sent_back", fix_tries=tries + 1)
        status = getattr(self.crew.get(crew_id), "status", None) or "running"
        with contextlib.suppress(Exception):
            self.crew._log_event(crew_id, "sent_back", status,
                                 {"try": tries + 1, "reason": result.get("reason"),
                                  "conflict": result.get("conflict")})
        log.info("assistant job %s clashes with main, so it was sent back to fix it "
                 "(try %d of %d)", crew_id, tries + 1, FIX_TRIES)
        # The task list last heard "done", from the stop. This is the job's
        # line on that list, not a card, and nothing is said.
        with contextlib.suppress(Exception):
            await self.broadcast({"type": "task", "id": crew_id, "status": status,
                                  "title": title, "detail": FIXING,
                                  "asking": False, "options": []})
        return True

    # --- rung five: the worker is gone, so redo rather than untangle -------

    async def _redo(self, crew_id, mate, title, result) -> bool:
        """Start a fresh job from the current main to write the change again.

        The worker that wrote the code is not there to reconcile anything, and
        resolving a stale patch by hand is the slower, worse half of the choice:
        on 20 September 2026 the thread-ownership fix was untangled twice and
        got nowhere, and reimplementing it on top of what was there took one
        pass. So a new job is started with the old commit message, the old diff
        and a summary of what landed in the meantime, and told to write the
        change again knowing what is there now.

        False when there is nothing to start from - no conflict record, no crew
        to start it with, or this work has already been redone once - and then
        the person is asked instead.
        """
        record_path = result.get("conflict")
        if (not result.get("clash") or result.get("needs_person")
                or not record_path or self.crew is None):
            return False
        record = self._record(record_path)
        if record is None:
            return False
        tries = int((getattr(mate, "meta", None) or {}).get("redo_tries") or 0)
        if tries >= REDO_TRIES:
            log.info("job %s has already been redone once; the person decides this one", crew_id)
            return False
        brief = conflicts.redo_brief(record, brief=getattr(mate, "task", "") or "")
        try:
            # Counted before it is started: a redo that was never counted is the
            # one way this could go round for ever.
            self.crew.set_meta(crew_id, redo_tries=tries + 1)
            fresh = await self.crew.spawn(
                task=brief, repo=getattr(mate, "repo", None) or None,
                mode=getattr(mate, "mode", "local-only"),
                title=f"Again: {title}"[:120],
                profile=(getattr(mate, "meta", None) or {}).get("profile") or None,
                in_play=(getattr(mate, "meta", None) or {}).get("in_play") or None,
            )
        except Exception:
            log.exception("could not start a fresh job to redo %s", crew_id)
            return False
        # The same request as the job it rewrites, so from the same conversation,
        # and it reports there too (`runs.came_from`). Its row is the crew's,
        # written as it was spawned (`runs.crew_run`).
        started_in = runs.chat_of(crew_id)
        if started_in:
            await asyncio.to_thread(runs.came_from, str(fresh.id), started_in)
        # And made by whoever made the first (`rouh/task_origin.py`).
        with contextlib.suppress(Exception):
            await asyncio.to_thread(task_origin.same_maker, crew_id, str(fresh.id))
        with contextlib.suppress(Exception):
            conflicts.set_state(record, conflicts.HANDBACK, redone_as=fresh.id)
        result.update(kind="redone", redo=fresh.id)
        log.info("job %s cannot fix its own clash, so %s is redoing it from main",
                 crew_id, fresh.id)
        with contextlib.suppress(Exception):
            await self.broadcast({"type": "task", "id": crew_id, "status": "done",
                                  "title": title, "detail": REDOING.format(id=fresh.id),
                                  "asking": False, "options": []})
        await self._say(
            f'[A job in the person\'s workspace finished, and its work would not go onto main: '
            f'"{title}". Another change landed there while it ran and the two collide, and the '
            f"job itself is no longer running to reconcile them, so a fresh job has been started "
            f"to write the change again on top of what is there now. Nothing is lost. Tell the "
            "person that in one short sentence. Do not start anything.]")
        return True

    @staticmethod
    def _record(where) -> dict | None:
        """The conflict record land.sh wrote, by its id or by its path."""
        found = conflicts.read(where) if "/" in str(where) else None
        if found is not None:
            return found
        for record in conflicts.read_all():
            if record.get("id") == str(where):
                return record
        return None

    async def _window_alive(self, mate) -> bool:
        """The job's window is there, and the program in it has not exited.

        Every job's window is kept after its program exits, so its last screen
        can still be read. Being listed is not enough.
        """
        tmux = getattr(self.crew, "tmux", None)
        session = getattr(mate, "session", None)
        name = getattr(mate, "window_name", None)
        if tmux is None or not session or not name:
            return False
        try:
            windows = await tmux.list_windows(None)
        except Exception:
            log.exception("could not list the windows to find %s", getattr(mate, "id", "?"))
            return False
        return any(w.get("session") == session and w.get("window_name") == name
                   and not w.get("dead") for w in windows)

    def _went_through(self, crew_id) -> bool:
        """Whether the message left the job's prompt, as ``send`` recorded it.

        ``send`` types the text in, presses Enter and records whether the
        prompt then cleared. Typed but never sent, the job would sit with it
        for ever while the task list said it was working.
        """
        events = getattr(self.crew, "events", None)
        if events is None:
            return True
        try:
            for event in reversed(events(crew_id, limit=5)):
                if event.get("kind") == "sent":
                    return (event.get("payload") or {}).get("submitted") is not False
        except Exception:
            log.exception("could not read whether the message to %s went through", crew_id)
        return True

    # --- the four results ---------------------------------------------------

    async def _show_page(self, crew_id, title, page, final, result) -> None:
        """A job that built a page: the page itself, and no card.

        Until 23 September 2026 this drew a "Ready:" card whose whole content
        was the job's summary around a tile that opened the page, and the page
        was then listed nowhere but inside that card. Petar, that day: the
        page "is the main thing that is produced as result", the card is "type
        'here you go'", and cards are for what he asked to see. So the page is
        opened on the canvas, full width, the way `show_workspace_page` opens
        one, and it stays on its task's own page, as the Open page button on
        its subtask's line and at the top of the subtask's own page
        (`objectindex._level`), which is where it is found again.
        """
        summary = summary_from(final)
        url = self.review_url + page if self.review_url else None
        # The page is opened from this machine's copy, so the copy has to have
        # it first: landing and deploying take a moment longer than this.
        here = False
        if self.copy is not None:
            try:
                here = await self.copy.update(page, result.get("sha"))
            except Exception:
                log.exception("bringing the workspace copy up to date for %s failed", page)
        if here:
            await self._open(page)
        # The page is the thing it made, and is opened rather than drawn. The
        # chat it was asked in still gets its report, so the conversation says
        # what came of it whenever it is next read (`run_report`).
        card_id = await self._card(
            f"Done: {title}",
            [{"block": "text", "text": summary}] if summary else [],
            foot={"ended": run_report.DONE, "page": page, "sha": result.get("sha") or "",
                  "touched": result.get("files") or ()})
        result.update(kind="page", page=page, url=url,
                      frame_url=pages.url_for(page) if here else None, card_id=card_id)
        with contextlib.suppress(Exception):
            self.crew.set_meta(crew_id, page=page, page_url=url)
        log.info("assistant job %s landed at %s, page %s%s", crew_id, result.get("sha"),
                 page, "" if here else ", not on this server yet")
        where = ("Its page is open on the canvas now, and its task's own page opens it "
                 "too." if here else
                 f"Its page is saved in the workspace at {page}, but this server does not "
                 "have it yet, so it could not be opened here; its task's own page will "
                 "open it once it arrives.")
        reported = f" Its report is card {card_id}." if card_id else ""
        await self._say(
            f'[A job in the person\'s workspace has finished: "{title}". {where}{reported} '
            f"What it did, in its own words: {summary or 'it did not say'} Tell the person "
            "in one or two short sentences that it is ready. Do not put the page on the "
            "screen again, draw no card for it, and do not start anything.]"
        )

    async def _open(self, page: str) -> None:
        """Open a page on the canvas, beside the conversation this report is in.

        The message `show_workspace_page` sends, on the screens standing in the
        thread the report belongs to and on no other, like every card a job
        drew: a job asked for this morning does not pull whatever is open now
        out from under the person. ``stay`` keeps that conversation beside the
        page rather than moving to the task's own, because what is said about
        the page is said here (`_say`), and a screen that moved away would
        drop it (`canvasMessage` in app.js).
        """
        # Nor anywhere for a run no conversation started: the page is on its
        # task's own page, and the Tasks list marks it (`runs.report_stays`).
        if runs.report_stays(outbox.REPORTING.get()):
            return
        said = {"type": "canvas", "mode": "tasks", "page": page, "stay": True}
        if ANSWERING.get():
            said["chat"] = ANSWERING.get()
        with contextlib.suppress(Exception):
            await self.broadcast(said)

    async def _show_files(self, crew_id, title, files, final, result) -> None:
        summary = summary_from(final)
        items = list(files[:FILES_SHOWN])
        if len(files) > FILES_SHOWN:
            items.append(f"and {len(files) - FILES_SHOWN} more")
        blocks: list[dict] = []
        if summary:
            blocks.append({"block": "text", "text": summary})
        if items:
            blocks.append({"block": "list", "items": items})
        blocks.append({"block": "text", "text": "Saved in the workspace."})
        card_id = await self._card(
            f"Done: {title}", blocks,
            foot={"ended": run_report.DONE, "sha": result.get("sha") or "", "touched": files})
        result.update(kind="files", card_id=card_id)
        count = f"{len(files)} file" + ("" if len(files) == 1 else "s")
        log.info("assistant job %s landed at %s, %s, no page", crew_id, result.get("sha"), count)
        await self._say(
            f'[A job in the person\'s workspace has finished: "{title}". It changed '
            f"{count} and made no page; card {card_id} lists them under its summary. "
            f"What it did, in its own words: {summary or 'it did not say'} Tell the "
            "person in one or two short sentences what it did. Do not start anything.]"
        )

    async def _show_answer(self, crew_id, title, final, result) -> None:
        answer = answer_from(final)
        text = answer or (
            "It finished without changing anything, and its last message could not be read."
        )
        card_id = await self._card(
            f"Answer: {title}", [{"block": "text", "text": text}],
            foot={"ended": run_report.DONE})
        result.update(kind="answer", card_id=card_id)
        log.info("assistant job %s finished and changed nothing", crew_id)
        spoken = summary_from(final, limit=1500)
        await self._say(
            f'[A job in the person\'s workspace has finished: "{title}". It changed '
            f"nothing, and its answer is on the screen as card {card_id}. Its answer, "
            f"in its own words: {spoken or 'it said nothing that could be read'} Give "
            "the person that answer in one or two short sentences. Do not start anything.]"
        )

    async def _show_needs_you(self, crew_id, title, result) -> None:
        reason = result.get("reason") or "it did not say why"
        card_id = await self._card(
            f"Needs you: {title}",
            [{"block": "text", "text": reason}],
            foot={"ended": run_report.STOPPED,
                  "why": "its work could not be moved onto main"},
        )
        result.update(kind="needs_you", card_id=card_id)
        log.warning("assistant job %s could not land: %s", crew_id, reason)
        await self._say(
            f'[The job "{title}" in the person\'s workspace stopped, but its work could '
            f"not be moved onto main: {reason} Tell the person in one or two short "
            "sentences.]"
        )

    async def _phone(self, job_id, title, final, result) -> None:
        """Tell him a job has finished, or needs him, with a link to open it.

        Called once a report has been drawn and said, whatever it was: a page,
        files, an answer, a change to Rouh, or a job that needs him. Every one
        of them drops in at the top of his screen as a notice
        (`rouh/notices.py`), and goes to his phone only if he leaves it there
        and it is one the phone is told of: a job that needs him always, a
        finished one only when `phone_done` says so. What it says is
        `job_phone.message_for`; that it is said once is `job_phone.claim`.
        Never raises: the job is finished either way.

        A run started from a chat leads to that chat, where its report is: the
        notice opens it, and the phone's message ends with its address, which
        is also what makes a reply to it on the phone go on in that chat
        (`telegram_chat`). Petar, 12 October 2026.

        And a run connected to a task offers every place it leads at once: its
        run, its chat, the task it worked on and the page it made, a button
        each (`run_report.destinations`). Petar, 13 October 2026
        (fr_677001efaa72): "I want all the existing options that result from
        this run and conclusion." The chat stays the swipe's one place.
        """
        # A night of the nightly feature run whose turn ended short of its target is not finished:
        # Rouh sends it back to work (`nightly_feature.watch`), so only what needs him is said now.
        needs_him = result.get("kind") in ("needs_you", "unfinished") or (
            result.get("kind") == "change" and not result.get("live"))
        if not needs_him:
            from . import nightly_feature

            try:
                if await asyncio.to_thread(nightly_feature.still_filling, job_id):
                    return
            except Exception:
                log.exception("job %s: could not read whether its night is still building", job_id)
        summary = summary_from(final)
        try:
            chat = await asyncio.to_thread(runs.report_chat, job_id)
        except Exception:
            log.exception("job %s: could not read which chat it was started from", job_id)
            chat = ""
        places = await asyncio.to_thread(
            run_report.destinations, job_id, chat=chat,
            page=str(result.get("page") or "") if result.get("kind") == "page" else "",
            # What it changed says which task only once it is on main.
            files=result.get("files") or () if result.get("kind") in LANDED else ())
        try:
            shown = job_phone.message_for(job_id, title, summary, result,
                                          self.public_url, done=True, chat=chat)
            phoned = job_phone.message_for(job_id, title, summary, result,
                                           self.public_url, done=self.phone_done, chat=chat)
            # Opened on the screen, the notice says every word the job closed with: the
            # phone's line or two cut with "..." was the whole of it until 10 October 2026,
            # and Petar's words were "in full with ellipsis ... that is not in full".
            # The chat is the notice's own link (`link=` below), so its words leave it out.
            whole = job_phone.message_for(job_id, title, answer_from(final, notices.BODY),
                                          result, self.public_url, done=True, whole=True)
        except Exception:
            log.exception("job %s: could not write its notice", job_id)
            return
        if shown is None:
            return
        what, text = shown
        try:
            if not await asyncio.to_thread(job_phone.claim, job_id, what):
                log.info("job %s: its notice for %s was given already", job_id, what)
                result["phoned"] = "already"
                return
        except Exception:
            log.exception("job %s: could not tell whether its notice had been given", job_id)
            return
        # A finished job is on the screen and nowhere else, unless the setting says the
        # phone is told of those too (`config.phone_done_jobs`). A change to Rouh that went
        # live names its commit, so a tab left behind by that deploy says Reload on this
        # notice instead of in a second one of its own (Petar, 11 October 2026,
        # fr_c09961ff435d: "These are two notifications for the same thing").
        live = result.get("kind") == "change" and result.get("live")
        said = await notices.phone(text, kind="job", key=f"job:{job_id}:{what}",
                                   link=run_report.chat_address(chat),
                                   phone_too=phoned is not None,
                                   whole=whole[1] if whole else "",
                                   deployed=str(result.get("sha") or "")[:7] if live else "",
                                   links=places)
        result["phoned"] = "on the screen" if said is not None else "failed"
        if said is not None and chat:
            await self._keep(chat, said)

    async def _keep(self, chat: str, said: dict) -> None:
        """The notice just said, kept in the chat it leads to as one of Rouh's messages.

        Petar, 12 October 2026 (fr_c8fb46a5a132): "when a run completes and the
        notification pops, the is a link go to chat. And I go there but there
        is no message. That same content in the notification needs to be
        posted in the chat for permanence. Otherwise notifications disappear
        and I can never reread then". Every word of it, its title first: done,
        failed or stopped alike, because whatever the notice said is what he
        followed it for. Once, because the notice is (`job_phone.claim` above,
        and its key). Drawn at once on every tab standing in that chat, and
        read back with the chat after that (`Memory.add_notice`). Never raises.
        """
        title = str(said.get("title") or "").strip()
        body = str(said.get("body") or "").strip()
        text = f"**{title}**\n\n{body}" if title and body else title or body
        try:
            row = await asyncio.to_thread(self.memory.add_notice, chat, text)
        except Exception:
            log.exception("the notice for chat %s could not be kept in it", chat)
            return
        if row is None:
            return
        with contextlib.suppress(Exception):
            await self.broadcast({"type": "transcript_add", "role": "assistant", "text": text,
                                  "ts": time.time(), "chat": chat, "id": row,
                                  "notice": True})

    async def _show_handoff(self, job_id, title, handoff, result, *, saved: str = "") -> None:
        """A job stopped at a step that is the person's and handed it to the live browser.

        Not a result: the job is open at its prompt and waiting on the person
        (`browser_handoff`). So the card says what the step is, and Rouh is
        told to open the page in its live browser, get it ready, hand it over
        and carry the job on once it comes back. Both go into General too
        for a run no conversation started, whose finished report is otherwise
        left on its run, because this is a job stopped on the person and not a
        report (`runs.report_stays`).
        """
        card_id = await self._card(**browser_handoff.card(handoff, title=title), always=True)
        result.update(kind="handoff", card_id=card_id, handoff=handoff.as_dict())
        log.info("job %s handed a step to the live browser: %s", job_id,
                 browser_handoff.statement_json(handoff))
        await browser_handoff.tell_phone(handoff, job=job_id, title=title)
        await self._say(browser_handoff.note(handoff, job=job_id, title=title, saved=saved),
                        needs_person=True)

    async def _card(self, title: str, blocks: list[dict], *, description: str = "",
                    always: bool = False, foot: dict | None = None) -> int | None:
        """Draw one card of a report in the chat it belongs to. Its id, or None.

        A report has no description: the one it had only said its title again
        ("the answer to ..." under "Answer: ..."), and Petar asked on 26
        October 2026 (fr_4241e4d596a4) for that line to go.

        `foot` is how the run ended and what it made, which put the same four
        facts under every report - what it was asked, how it ended, what it
        changed, and the link to its run (`run_report.footer`).
        """
        # A run no conversation started draws nothing: its report stays on the
        # run (`runs.report_stays`). What a job is stopped on is not a report,
        # and is drawn wherever it belongs (`always`).
        job = outbox.REPORTING.get()
        if runs.report_stays(job) and not always:
            return None
        if foot is not None and job:
            blocks = list(blocks) + await asyncio.to_thread(run_report.footer, job, **foot)
        spec = {"title": title, "description": description, "blocks": blocks}
        card_id = None
        drawn = dict(spec, at=time.time())
        with contextlib.suppress(Exception):
            # The same door every other card goes through, so the answer a job
            # came back with is kept and numbered like anything else on the
            # screen (`rouh/artifacts.keep`). Which thread it belongs to is on
            # the report already (`memory.ANSWERING`).
            card_id, drawn = await asyncio.to_thread(
                artifacts.keep, self.memory, spec)
        said = {"type": "ui", "spec": drawn}
        # And it is drawn on the screens standing in that thread and on no
        # other. The page throws away anything naming a conversation it is not
        # looking at (`handleMessage` in app.js), so a job asked for this
        # morning does not put a card over whatever is open now - it is in its
        # own thread, and it is there when they go back to it.
        if ANSWERING.get():
            said["chat"] = ANSWERING.get()
        with contextlib.suppress(Exception):
            await self.broadcast(said)
        return card_id

    async def _say(self, note: str, *, needs_person: bool = False) -> None:
        """Hand Rouh the note, in the thread this report belongs to.

        Which thread that is, is the one already on the report
        (`memory.ANSWERING`, set by `land` and by `one_jobs.OneLander.report`),
        so the card and the words said about it can never end up in two
        different conversations. A job no conversation started reports in
        General, and never in whichever chat is open (`runs.reports_to`).

        Whatever the job queued for the person to be emailed goes inside the
        note, subject, body and id, so Rouh has it in hand in the same turn
        (`rouh/outbox.py`). Which job that is, is on the report too
        (`outbox.REPORTING`, set beside the thread).

        A run no conversation started says nothing about the job at all: its
        report stays on the run (`runs.report_stays`). Only a note it queued to
        be emailed is still asked about in General, on its own
        (`outbox.on_its_own`). So is a step the job is stopped on and waiting
        for the person to do (`needs_person`, `_show_handoff`), which is said
        there like anywhere else.
        """
        job = outbox.REPORTING.get()
        # A job started for an email is that email's work, not news: its
        # report goes back to the email, which is handed to Rouh again to
        # finish (`mail_flow.reported`), rather than said as a job like any
        # other in the email's conversation.
        if job and not needs_person and await mail_flow.reported(job, note):
            return
        if runs.report_stays(job) and not needs_person:
            try:
                note = await asyncio.to_thread(outbox.on_its_own, job) if job else ""
            except Exception:
                note = ""
            if not note:
                log.info("job %s was started from no chat, so its report is left on its run",
                         job or "?")
                return
        else:
            with contextlib.suppress(Exception):
                note = await asyncio.to_thread(outbox.with_notes, job, note)
            # What Rouh said it would do once this job was done, and what was
            # added to the job while it ran (`rouh/follow_through.py`).
            if job and not needs_person:
                note = await asyncio.to_thread(follow_through.extend, note,
                                               chat=self.memory.answering_chat(), job=job)
        with contextlib.suppress(Exception):
            await self.announce(note, self.memory.answering_chat())
