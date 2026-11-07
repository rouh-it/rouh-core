"""The nightly code refactoring run: up to ten refactors a night side by side, while the owner sleeps.

Petar, 15 October 2026, by voice: "Every night at 3, start a refactoring job. Similar to the new
genes job where you look around and decided to do new genes by crushing a list, I would like that
you look at code and select things to refactor. Pick few things that can be refactored in parallel
or one major thing so it doesn't break too many things. The goal is to keep code well organized
instead of layered bozocity due to added hundreds of features. We will be scaling the gene creating
so we don't want the code to become a disaster. We are going open source soon, so it needs to get
in shape." The refactors go to main and are deployed without his approval, and "I want to have a
list of what else to refactor and a list of what was refactored. We will be recording those for
automatic improvements later."

Petar, 18 October 2026, by voice: "Instead of three, try to find 10 different refactoring jobs
that can run in parallel. You can run less than ten if you think a bigger refactoring job will
give us great gain and it is worth it, and others can't run in parallel. This will allow us to do
full architecture changes not just marginal updates." So a night plans up to ten refactors that
share no file, starts each as a worker of its own in its own worktree, lands each alone as it
passes, and writes the task's shared files itself, once, at the end (`brief_for`).

Built like the nightly feature run (`rouh/nightly_feature.py`), and much smaller: it signs up for
nothing, pays for nothing and asks nothing.

**When.** A row of Rouh's own scheduled work, a reminder of kind `server` whose job is
`nightly_refactor` (`ensure`), daily at 03:00 on the person's clock, an hour after the feature
run, so it is on Clockwork as "Rouh's own server job: Nightly code refactoring run" and is
paused, resumed or moved there like the others. Never a chat turn: a scheduled turn may not start
a run that changes Rouh (`rouh/protected.py`).

**It never runs beside the feature run.** If the feature run's night is still going, or is still
landing its work (its run "saving"), the refactoring night waits for it (`waits_for`) and starts
the moment it has ended, checked every two minutes. Two hours on (05:00), as the task's rules say,
it starts anyway to survey only and refactor nothing. A night whose home task is not in the
workspace yet waits for that the same way, and is given up after those two hours. A waiting night is a row in
`nightly_refactor_nights`, so the wait outlives the restart a landing's deploy makes: Rouh takes
every waiting night up again as it starts (`resume`).

**What.** `start` writes the night's row first, so there is always a row, and starts one run of
the one program in its own checkout of Rouh's code, on the model the Models page picks for
"Nightly refactoring run" (its tier there): Claude Code for a
Claude model, Codex for an OpenAI one, each on its subscription, as the feature run is
(`nightly_feature.engine`), and at the level that comes with its model (`modelstandard.effort`).
Its brief is fixed here (`brief_for`) and names the home task's files: refactoring-rules.md
(the owner's, which they revise), notes.md, and the two ledgers, to-refactor.json and refactored.json.
Each refactor is a worker's one commit, landed alone through land.sh, so each can be reverted
alone and one that fails is dropped without holding up the others.

**What it tells Rouh.** One tool, `refactor_done` in the `rouh` MCP server every run has
(`rouh/worker_mcp.py`, answered here by `act`, only for a night's own run): what was refactored,
the commits, and the result. That is the Clockwork line, and so the morning brief's Report, with
an Undo there that starts a run reverting exactly that night's commits (`undo`).

**Whose.** Every row carries `user_id` and `org_id` and every query names both. The endpoint the
tool reaches (`/internal/refactoring`) answers only a caller on this machine, and a run id that is
a night's.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from pathlib import Path
from typing import Any

from . import owner, workspace_repo

log = logging.getLogger("rouh.nightly_refactor")

JOB = "nightly_refactor"
TITLE = "Nightly code refactoring run"
#: What the row says on Clockwork, under its title.
WHAT = "Look at the code, pick refactors from the list, do them, and record what was done"
AT = "03:00"
#: The home task's folder ends with this, wherever it is filed.
SLUG = "nightly-code-refactoring-run"
#: The Models page pick it runs on (`modeldefaults.USES`).
USE = "nightly_refactor_run"
#: The home task's files the run reads and keeps.
RULES, NOTES, TODO, DONE = "refactoring-rules.md", "notes.md", "to-refactor.json", "refactored.json"
#: How long a night waits for the feature run before it starts anyway, to survey only and refactor
#: nothing (refactoring-rules.md: "If it has still not landed by 05:00, refactor nothing tonight"),
#: and for its home task before it gives the night up.
WAIT_HOURS = 2
#: How often a waiting night looks again, in seconds.
WAIT_EVERY = 120
#: How long after the feature run's row is said a night with no row yet counts as starting.
STARTING_SECONDS = 600
#: A run's states that mean it has finished its work and landed what it had: a run of the one
#: program that ended its turn waits at its prompt, "idle"; while it lands it is "saving".
ENDED = ("idle", "done", "failed", "killed", "lost", "reaped")
#: What a night may say it came to.
OUTCOMES = ("refactored", "nothing", "failed")
COMMIT = re.compile(r"[0-9a-f]{7,40}")


class Refused(ValueError):
    """A request this module will not carry out, with the reason."""


class Hooks:
    """What the runtime lends this module. None until the runtime sets it."""

    #: async (**starting.start kwargs) -> {"id", ...}: `starting.start` with the runtime's
    #: config, crew and one program.
    start = None


hooks = Hooks()
#: The night rows a wait is running for in this process, so a night is never waited twice.
_waiting: set[int] = set()


def _models():
    from . import models

    return models


def _whose(who) -> dict:
    return {"user_id": str(who.user_id), "org_id": str(who.org_id)}


def _model(who) -> str:
    from . import modeldefaults

    return modeldefaults.use_model(USE, str(who.org_id) if who is not None else None)


def engine(who) -> str:
    """The agent a night's runs are: the one that can be the model picked for them."""
    from .config import is_openai

    model = _model(who)
    return "codex" if model and is_openai(model) else "claude"


def _effort(who) -> str:
    """The level the night's model thinks at, which comes with the model
    (`modelstandard.effort`): GPT-6.1 Sol at high, Opus 5.5 at medium."""
    from . import modelstandard

    model = _model(who)
    return modelstandard.effort(model) if model else ""


def one_fields(who, agent: str) -> dict:
    """What else the one program is told about a night's run: its level, on Codex."""
    effort = _effort(who) if agent == "codex" else ""
    return {"effort": effort} if effort else {}


def worker_for(who, agent: str) -> str:
    """`worker_line` for this person's night: the model and level the night itself runs on."""
    return worker_line(agent, _model(who) or "", _effort(who))


# --- the home task ------------------------------------------------------------------------------


def task_folder(root: str | None = None) -> str:
    """The home task's folder inside the workspace, "rouh/assistant/118.nightly-code-refactoring-run",
    or "" while it is not there. A task filed under another slug is still found by its name."""
    if root is None:
        from .config import config

        root = config.assistant_repo
    base = Path(root or "")
    if not base.is_dir():
        return ""
    found = (sorted((base / "rouh" / "assistant").glob(f"*.{SLUG}"))
             or sorted(base.glob(f"**/*.{SLUG}"))
             or sorted(p for p in (base / "rouh" / "assistant").glob("*.*")
                       if re.fullmatch(r"\d+\.[a-z0-9-]*nightly[a-z0-9-]*refactor[a-z0-9-]*", p.name)))
    for one in found:
        if one.is_dir():
            return one.relative_to(base).as_posix()
    return ""


# --- the scheduled row --------------------------------------------------------------------------


def ensure(who) -> Any | None:
    """The person's row for the nightly refactoring run, made daily at 03:00 on their clock the
    first time. It is made whether or not the home task is there yet: a night waits for it. A
    row the owner paused or moved stays as they left it."""
    from . import clock, reminders

    got = reminders.server_row(who, JOB)
    if got is not None:
        return got
    with clock.person(who):
        when = reminders.moment_of(AT)
    row = reminders.add_server(who, job=JOB, title=TITLE, what=WHAT, first=when, repeat="daily")
    log.info("the nightly refactoring run is scheduled for %s/%s at %s (reminder %s)",
             who.org_id, who.user_id, AT, row.id)
    return row


def said(who, line: str) -> None:
    """Clockwork's line for the row, and so the morning brief's Report."""
    from . import reminders

    scheduled = reminders.server_row(who, JOB)
    if scheduled is not None:
        reminders.said(scheduled.id, line)


# --- the nights ---------------------------------------------------------------------------------


def run_state(run_id: str) -> str:
    """A run's state in the run list's words, or "" when the register has no row."""
    from . import runs

    row = runs.get(run_id) if run_id else None
    return runs.status_of(row) if row is not None else ""


#: What a night says of a run that ended in each state without saying what it did.
_STOPPED = {"failed": "failed", "lost": "was lost", "killed": "was stopped by hand",
            "reaped": "was stopped at its time limit"}


def _ending(run_id: str, state: str, why: str = "", exit_code: Any = None) -> str:
    """How a night's run ended, in one plain sentence, with its own reason: never "no reason".

    Until 6 November 2026 a run that never started (Codex not signed in, nights 17 to 22) ended
    the night with nothing on its row, and the morning said only that it "left no reason", while
    the run list had the reason all along."""
    did = _STOPPED.get(state) or "ended its turn without calling refactor_done"
    why = " ".join(str(why or "").split())
    if why.startswith("Codex, "):
        # The run list's "who pays" ahead of the reason, and alone when it had no reason.
        why = why.split(" · ", 1)[1] if " · " in why else ""
    code = f" with exit code {exit_code}" if exit_code not in (None, "", 0) else ""
    if why:
        return f"its run {run_id} {did}{code}: {why}"[:900]
    return f"its run {run_id} {did}{code}, and neither it nor the one program said why"


def _ending_from_register(run_id: str, state: str) -> str:
    from . import runs

    row = runs.get(run_id)
    return _ending(run_id, state, getattr(row, "detail", "") if row is not None else "",
                   getattr(row, "exit_code", None) if row is not None else None)


def settle(who) -> None:
    """Nights whose run has finished are ended; one whose run never said what it did keeps how
    the run ended, and says it on Clockwork."""
    m = _models()
    for night in m.NightlyRefactorNight.objects.filter(**_whose(who), state="running"):
        state = run_state(night.run_id) if night.run_id else ""
        if state not in ENDED:
            continue
        fields: dict = {"state": "ended"}
        if not night.outcome and not night.why:
            fields["why"] = _ending_from_register(night.run_id, state)
        _update(night, **fields)
        if "why" in fields:
            said(who, line_of(night))
    # Nights ended before their run's reason was kept: given it now, the newest few only.
    for night in (m.NightlyRefactorNight.objects.filter(**_whose(who), state="ended", outcome="", why="")
                  .exclude(run_id="").order_by("-number")[:5]):
        _update(night, why=_ending_from_register(night.run_id, run_state(night.run_id) or "ended"))


def run_ended(run: dict) -> None:
    """The one program says a run stopped (`runs.one_run`): if it is a night's own run and the night
    has no outcome, the whole of the program's reason is kept on it (the run list keeps only its
    first 160 characters) and said on Clockwork, so the morning brief says why."""
    run_id = str(run.get("id") or "")
    state = str(run.get("state") or "").lower()
    if state not in _STOPPED:
        return
    row = night_of_run(run_id)
    if row is None or row.outcome:
        return
    why = _ending(run_id, state, str(run.get("ended_why") or ""), run.get("exit_code"))
    if row.why == why:
        return
    _update(row, why=why, **({"state": "ended"} if row.state == "running" else {}))
    said(_who_of(row), line_of(row))


def night(who, number) -> Any | None:
    return _models().NightlyRefactorNight.objects.filter(**_whose(who), number=int(number)).first()


def latest(who) -> Any | None:
    return _models().NightlyRefactorNight.objects.filter(**_whose(who)).order_by("-number").first()


def _new_night(who):
    from django.db import IntegrityError

    m = _models()
    for _ in range(3):
        last = (m.NightlyRefactorNight.objects.filter(**_whose(who)).order_by("-number")
                .values_list("number", flat=True).first()) or 0
        try:
            return m.NightlyRefactorNight.objects.create(
                **_whose(who), number=last + 1, state="waiting", started_at=time.time())
        except IntegrityError:
            continue
    raise RuntimeError("the night's number could not be taken")


def _update(row, **fields) -> None:
    _models().NightlyRefactorNight.objects.filter(id=row.id).update(**fields)
    for key, value in fields.items():
        setattr(row, key, value)


def waits_for(who) -> str:
    """What tonight's night has to wait for before it may start, in words, or "" when nothing.

    The feature run's night that is still going or still landing (Petar: the refactor "waits
    for it rather than running alongside it"), and the home task while it is not in the workspace.
    """
    from . import nightly_feature, reminders

    nightly_feature.settle(who)
    # Both rows can fall due in one sweep of the clock, which says them side by side (the night
    # the owner's clock moved one time zone east, 15 October 2026, put 02:00 and 03:00 on one
    # instant): a feature row due now, or said in the last minutes with no night written since,
    # is a feature run starting.
    row = reminders.server_row(who, nightly_feature.JOB)
    if row is not None and row.state == "on":
        now = time.time()
        newest = (_models().NightlyFeatureNight.objects.filter(**_whose(who))
                  .order_by("-number").first())
        if (row.next_at and row.next_at <= now + 60) or (
                row.last_at and now - row.last_at < STARTING_SECONDS
                and (newest is None or newest.started_at < row.last_at - 5)):
            return "the feature run, due now, to start and land"
    busy = (_models().NightlyFeatureNight.objects.filter(**_whose(who), state="running")
            .order_by("-number").first())
    if busy is not None:
        state = run_state(busy.run_id) if busy.run_id else ""
        if state and state not in ENDED:
            return (f"night {busy.number} of the feature run (run {busy.run_id}) to "
                    + ("land its work" if state == "saving" else "finish and land"))
        if not state and time.time() - busy.started_at < STARTING_SECONDS:
            # Its row is written and its run is being started: no id, or none in the register yet.
            return f"night {busy.number} of the feature run to start and land"
    if not task_folder():
        return "its home task, “Nightly code refactoring run”, to be in the workspace"
    return ""


async def start(who, *, trying: bool = False) -> str:
    """Tonight's night: its row, then its run, or its wait. Returns Clockwork's line."""
    if hooks.start is None:
        return "could not start: Rouh's runs are not ready yet"
    await asyncio.to_thread(settle, who)
    m = _models()
    busy = await asyncio.to_thread(
        lambda: m.NightlyRefactorNight.objects.filter(**_whose(who), state__in=("waiting", "running"))
        .order_by("-number").first())
    if busy is not None:
        return (f"did not start another: night {busy.number} is still "
                + (f"waiting to start. {busy.why}".strip() if busy.state == "waiting"
                   else f"running as run {busy.run_id}"))
    row = await asyncio.to_thread(_new_night, who)
    wait = await asyncio.to_thread(waits_for, who)
    if wait:
        await asyncio.to_thread(_update, row, why=f"Waiting for {wait}.")
        _wait(who, row)
        return f"night {row.number} waits for {wait}, and starts the moment it has"
    return await _begin(who, row)


async def _begin(who, row, survey_only: str = "") -> str:
    """The night's run, started now; to survey only when `survey_only` says what it still waited
    for. Returns the line for Clockwork."""
    folder = await asyncio.to_thread(task_folder)
    from . import silos

    rule = await asyncio.to_thread(silos.run_rule, str(who.user_id), str(who.org_id))
    try:
        agent = await asyncio.to_thread(engine, who)
        got = await hooks.start(
            brief=owner.say(brief_for(row, folder, rule, survey_only,
                                      await asyncio.to_thread(worker_for, who, agent)), who),
            title=f"{TITLE}, night {row.number}",
            preset="improve_myself", agent=agent, use=USE, org_id=str(who.org_id),
            one_fields=await asyncio.to_thread(one_fields, who, agent) or None,
            # What the night makes is the nightly run's, not his (`rouh/task_origin.py`).
            made_by="process:nightly-refactor")
    except Exception as exc:  # noqa: BLE001 - the row says what stopped it
        log.exception("the nightly refactoring run could not be started")
        await asyncio.to_thread(_update, row, state="failed", why=f"The run could not be started: {exc}"[:600])
        return f"night {row.number} could not start: {exc}"
    run_id = str(got.get("id") or "")
    await asyncio.to_thread(_update, row, run_id=run_id, state="running", began_at=time.time(), why="")
    log.info("night %s of the nightly refactoring run started as run %s", row.number, run_id)
    if survey_only:
        return (f"started night {row.number} as run {run_id} to survey only, because it was still "
                f"waiting for {survey_only} after {WAIT_HOURS} hours")
    return f"started night {row.number} as run {run_id}; what it refactors is in the morning brief"


def _wait(who, row) -> None:
    """Look again every two minutes until the night may start, then start it; give the night up
    after `WAIT_HOURS`. One wait per night in this process."""
    if row.id in _waiting:
        return
    _waiting.add(row.id)

    async def waiting() -> None:
        try:
            while True:
                await asyncio.sleep(WAIT_EVERY)
                fresh = await asyncio.to_thread(night, who, row.number)
                if fresh is None or fresh.state != "waiting":
                    return
                wait = await asyncio.to_thread(waits_for, who)
                if not wait:
                    line = await _begin(who, fresh)
                    await asyncio.to_thread(said, who, line)
                    return
                if time.time() - fresh.started_at > WAIT_HOURS * 3600:
                    if "feature run" in wait:
                        # The rules' 05:00: the night runs, but only to survey (`brief_for`).
                        line = await _begin(who, fresh, survey_only=wait)
                        await asyncio.to_thread(said, who, line)
                        return
                    why = f"It waited {WAIT_HOURS} hours for {wait}, so it gave this night up."
                    await asyncio.to_thread(_update, fresh, state="failed", why=why)
                    await asyncio.to_thread(said, who, f"night {fresh.number} did not run: {why}")
                    return
                if fresh.why != f"Waiting for {wait}.":
                    # What it waits for changed (the home task came, the feature run is landing).
                    await asyncio.to_thread(_update, fresh, why=f"Waiting for {wait}.")
                    await asyncio.to_thread(said, who, f"night {fresh.number} waits for {wait}, "
                                                       "and starts the moment it has")
        except Exception:
            log.exception("night %s of the nightly refactoring run stopped waiting", row.number)
        finally:
            _waiting.discard(row.id)

    asyncio.ensure_future(waiting())


def waiting(who) -> list:
    """Every night of this person's still waiting to start."""
    return list(_models().NightlyRefactorNight.objects.filter(**_whose(who), state="waiting"))


def resume(who, rows: list) -> None:
    """Each of these waiting nights waited for again: a restart (a landing's deploy) ended the
    last wait. Called in the event loop's thread, as Rouh starts."""
    for row in rows:
        _wait(who, row)


def worker_line(agent: str, model: str, effort: str = "") -> str:
    """How the night starts one of its workers: the same agent on the same model as itself, as a
    process of its own, so each worker has its own MCP servers and so its own browser."""
    if agent == "codex":
        level = f" -c model_reasoning_effort=\"{effort}\"" if effort else ""
        return (f"`codex exec --dangerously-bypass-approvals-and-sandbox -m {model}{level} "
                "-C <its worktree> -o <its scratch folder>/report.md \"<its brief>\"`")
    picked = f" --model {model}" if model else ""
    return (f"`claude -p --permission-mode bypassPermissions{picked} --mcp-config <the file your "
            "own --mcp-config names, .one/mcp.json in your checkout> \"<its brief>\"`, started "
            "in its worktree")


def brief_for(row, folder: str, rule: str = "", survey_only: str = "", worker: str = "") -> str:
    """What the night's run is told. Fixed here: nothing a model says can start one with other words."""
    home = workspace_repo.for_code_run(folder)
    worker = worker or worker_line("claude", "")
    lines = [
        f"You are night {row.number} of the nightly code refactoring run, Rouh's own job at "
        f"{AT} on ‹owner›'s clock.",
        "",
        "How this run was first asked for, on 15 October 2026: \"Every night at 3, start a refactoring job. Similar to the new "
        "genes job where you look around and decided to do new genes by crushing a list, I would "
        "like that you look at code and select things to refactor. Pick few things that can be "
        "refactored in parallel or one major thing so it doesn't break too many things. The goal "
        "is to keep code well organized instead of layered bozocity due to added hundreds of "
        "features. We will be scaling the gene creating so we don't want the code to become a "
        "disaster. We are going open source soon, so it needs to get in shape.\"",
        "",
        "And on 18 October 2026: \"Instead of three, try to find 10 different refactoring jobs "
        "that can run in parallel. You can run less than ten if you think a bigger refactoring job "
        "will give us great gain and it is worth it, and others can't run in parallel. This will "
        "allow us to do full architecture changes not just marginal updates.\"",
        "",
        "‹Owner› has authorised your refactors going straight to main and being deployed, without "
        "asking ‹him›. Nobody approves anything tonight, and you never wait for anybody.",
        "",
        ("**Survey only tonight.** Rouh waited until now for "
         f"{survey_only}, which had still not happened {WAIT_HOURS} hours after this night's "
         "time. So, as refactoring-rules.md says, refactor nothing: survey, add what you find to "
         "the list, and say so in notes.md." if survey_only else
         "Rouh started you only once tonight's feature run had ended and landed its work, or "
         "none was running: you need not wait for it. Fetch origin/main and start from it."),
        "",
        "## Your home",
        "",
        f"Your home is the task `{home}`. Read these first, in this order:",
        "",
        f"1. `{home}/{RULES}`: ‹owner›'s rules for this run. ‹He› revises them; where they differ "
        "from this brief, they win, except that nothing lets you change what Rouh does.",
        f"2. `{home}/{NOTES}`: where the last night left off.",
        f"3. `{home}/{TODO}`: the list of what else to refactor.",
        f"4. `{home}/{DONE}`: the list of what was refactored, night by night.",
        f"5. `{home}/AGENTS.md`, and the repository's own AGENTS.md.",
        "",
        "Keep the ledgers' shape and fields exactly as the task's AGENTS.md says, and check them "
        "with `source-code/build_ledgers.py` there before every commit of them.",
        "",
        "## What a night does",
        "",
        "1. **Look.** Read Rouh's code (`rouh/`, `one/`, the page's script and styles) for what has "
        "grown in layers: a module that does several unrelated jobs, the same thing written in "
        "several places, a function hundreds of lines long, names that no longer say what a thing "
        "is, dead code nothing calls, a file too big to read. Look as hard for the architecture: "
        "modules to split or merge, a responsibility living in the wrong place, two systems doing "
        "one job where a newer one replaced an older one that was never removed. Add every new "
        f"candidate to {TODO}, large ones too, with where it is and why, including the ones you "
        "will not do tonight. Never add one that is already there or already in "
        f"{DONE}.",
        "2. **Plan.** Aim for up to ten refactors that run in parallel, each its own worker. Fewer "
        "is right when one bigger refactor gives a real gain and the others cannot run beside it. "
        "Full architecture changes are in scope, not only small clean-ups, and when a new system "
        "replaces an old one, the old one is removed in the same refactor. For each refactor, "
        "list every file it will change, including every importer it must update, then check "
        "the set with `python3 source-code/build_ledgers.py plan <the plan file>`: no file may be "
        "in two refactors, so they cannot collide when they land. Write the plan and why into "
        f"{NOTES} before you start any worker.",
        "3. **Start the workers, all at once.** Each refactor gets its own git worktree of "
        "origin/main, with `.venv-e2e` linked into it, and its own agent: " + worker + ". So "
        "each has a browser of its own. Its brief names its candidate, its files and nothing "
        f"else, {RULES}, and the checks below. A worker checks before, refactors, checks after "
        "and makes one commit in its worktree, and ends with a short report: what moved where, "
        "what each check said before and after, its commit, or why it gave up. A worker never "
        "lands, never changes a file outside its list (if it needs one, it stops and says so), "
        "never writes the task's files or its record (the ledgers, the notes, AGENTS.md, its meta, a step), "
        "and never calls `refactor_done`.",
        "4. **Land each one alone, as it is ready.** When a worker reports success, check that its "
        "commit changes only its own files (`git show --name-only`), then land it from its "
        "worktree with ./land.sh and read its last sentence. Its message starts \"refactor: \", "
        "says what moved and why, and ends with a `Gene:` line for each gene whose code it "
        "touched (AGENTS.md, \"Every change names its gene\"). A refactor whose checks did not "
        "say the same after, that changed another's file, or that is not live, is dropped: not "
        "landed, or reverted and the revert landed. Record why, and carry on with the others; "
        "one failing never holds up the rest.",
        f"5. **Record, once, at the end, yourself.** Each refactor, landed or dropped, goes into "
        f"{DONE}, with the night, the date, its commits, its files, the checks before and after, "
        "and its result: deployed, or on main and not live with the reason land.sh gave, or "
        f"failed and why; and its candidate's status in {TODO} changes, as refactoring-rules.md "
        "says. The night's step page says what each did. A big architecture change also gets a "
        "step page of its own in the task, saying what moved where and why. Rewrite "
        f"{NOTES} with where you left off and what the next night should look at. Commit the "
        "task's files in one commit and land it with ./land.sh.",
        "6. **Tell Rouh, last.** Call `refactor_done` in the `rouh` MCP server once: the outcome, "
        "a summary in a sentence or two of plain words, each item with its commits, and every "
        "commit the night landed. Rouh puts it in ‹owner›'s morning brief with an Undo that reverts "
        "exactly those commits, so name every one and no other.",
        "",
        "## The checks",
        "",
        "This repository keeps no test suite (AGENTS.md). ‹owner› asked for the full tests and "
        "browser checks before and after every refactor, so for this run they are these, run by "
        "each worker on its own refactor, in its own worktree and its own world:",
        "",
        "- `./e2e.sh visual`: the screenshot comparisons, made for exactly this (AGENTS.md, \"The "
        "screenshot comparisons\"). A screen that already failed before you changed anything must "
        "fail the same way after, and no other may.",
        "- `tools/typecheck/check.sh` and `python3 -m rouh.genes`, and `python3 -m rouh.mail_replay` "
        "when the mail code is touched.",
        "- `.venv-e2e/bin/python -m compileall -q rouh one`, and importing every module you touched.",
        "- The tests that were deleted on 20 September 2026 for the modules you touch: bring each "
        "back from git history into your checkout (AGENTS.md, \"There is no suite\"), run it with "
        "./e2e.sh before and after, and leave it out of every commit.",
        "- A drive over Playwright MCP of every place a person sees whose code you moved, in "
        "`./e2e.sh serve` (or the world it needs), as AGENTS.md says, before and after.",
        "",
        "Never commit a test, a screenshot or a scratch file. Keep scratch in your task's step "
        "`temp/` or your own scratch folder.",
    ]
    # An unattended run on Rouh itself sees only the silos runs see (`silos.run_rule`).
    return "\n".join(lines) + rule


# --- the tool -----------------------------------------------------------------------------------


def night_of_run(run_id: str):
    """The night a run is the night's own run of, or None."""
    if not run_id or not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", run_id):
        return None
    return _models().NightlyRefactorNight.objects.filter(run_id=run_id).order_by("-id").first()


def _who_of(row):
    from .tenancy import Identity

    return Identity(user_id=str(row.user_id), org_id=str(row.org_id))


async def act(job: str, action: str, args: dict) -> dict:
    """One tool call from a run, answered {"ok", "text"}. Never raises."""
    row = await asyncio.to_thread(night_of_run, str(job or ""))
    if row is None:
        return {"ok": False, "refactor": False,
                "text": "This is not the nightly refactoring run, so its tool does nothing for it."}
    if action == "whoami":
        return {"ok": True, "refactor": True, "night": row.number, "actions": ["done"],
                "text": f"Night {row.number} of the nightly code refactoring run."}
    if action != "done":
        return {"ok": False, "text": f"There is no action {action!r}."}
    try:
        who = _who_of(row)
        text = await asyncio.to_thread(done, who, row, args if isinstance(args, dict) else {})
        return {"ok": True, "text": await asyncio.to_thread(owner.say, text, who)}
    except Refused as exc:
        return {"ok": False, "text": str(exc)}
    except Exception as exc:  # noqa: BLE001 - said to the run, never raised into Rouh
        log.exception("refactor_done for run %s failed", job)
        return {"ok": False, "text": f"That did not work: {type(exc).__name__}."}


def _words(value, most: int) -> str:
    return " ".join(str(value or "").split())[:most]


def _commits(value) -> list[str]:
    out: list[str] = []
    for one in value if isinstance(value, list) else []:
        sha = str(one or "").strip().lower()
        if COMMIT.fullmatch(sha) and sha not in out:
            out.append(sha)
    return out[:40]


def done(who, row, args: dict) -> str:
    """What the night refactored, kept on its row and said on Clockwork and in the brief."""
    outcome = str(args.get("outcome") or "").strip().lower()
    if outcome not in OUTCOMES:
        raise Refused("outcome is refactored, nothing or failed.")
    summary = _words(args.get("summary"), 800)
    if not summary:
        raise Refused("summary says what the night did, in a sentence or two of plain words.")
    items = []
    for one in (args.get("items") if isinstance(args.get("items"), list) else [])[:20]:
        if not isinstance(one, dict) or not _words(one.get("title"), 200):
            continue
        items.append({"id": _words(one.get("id"), 20), "title": _words(one.get("title"), 200),
                      "commits": _commits(one.get("commits")),
                      "files": [_words(f, 200) for f in (one.get("files") or [])[:30] if _words(f, 200)]
                      if isinstance(one.get("files"), list) else [],
                      "result": _words(one.get("result"), 300)})
    commits = _commits(args.get("commits"))
    for item in items:
        commits += [c for c in item["commits"] if c not in commits]
    if outcome == "refactored" and not commits:
        raise Refused("A night that refactored names the commits it landed, so Undo can revert them.")
    try:
        left = max(0, int(args.get("left") or 0))
    except (TypeError, ValueError):
        left = 0
    _update(row, outcome=outcome, summary=summary, items=items, commits=commits[:40], left=left,
            reported_at=time.time())
    said(who, line_of(row))
    return (f"Night {row.number} is recorded: {len(items)} item(s), {len(commits)} commit(s). It is "
            "in ‹owner›'s morning brief with an Undo that reverts those commits. Calling again "
            "before ‹he› reads it changes it.")


def line_of(row) -> str:
    """The night in one line, for Clockwork and the morning brief's Report."""
    if row.undo_run_id:
        return f"night {row.number}'s refactors are being undone, by run {row.undo_run_id}"
    if row.outcome == "refactored":
        n = len(row.items or [])
        left = f"; {row.left} more on the list" if row.left else ""
        return (f"night {row.number} refactored {n or 'its'} {'thing' if n == 1 else 'things'} in "
                f"{len(row.commits or [])} commit{'' if len(row.commits or []) == 1 else 's'}: "
                f"{row.summary}{left}")
    if row.outcome == "nothing":
        return f"night {row.number} refactored nothing: {row.summary}"
    if row.outcome == "failed":
        return f"night {row.number} could not refactor: {row.summary}"
    return f"night {row.number}: {row.why or 'its run ended without saying what it did'}"


# --- the morning --------------------------------------------------------------------------------


def report_of(who, since: float) -> dict | None:
    """The newest night since the last brief, for the Report: what it did and whether Undo may
    be pressed."""
    row = latest(who)
    if row is None or (row.started_at or 0) < since:
        return None
    return {"number": row.number, "outcome": row.outcome or "", "summary": row.summary or "",
            "items": [{"title": i.get("title", ""), "result": i.get("result", ""),
                       "commits": i.get("commits", [])} for i in (row.items or [])],
            "commits": list(row.commits or []),
            "can_undo": bool(row.commits) and not row.undo_run_id,
            "undo_run": row.undo_run_id or ""}


def undo_brief(row, folder: str) -> str:
    listed = "\n".join(f"- {c}" for c in row.commits)
    items = "\n".join(f"- {i.get('title')}" + (f" ({', '.join(i.get('commits') or [])})"
                                                if i.get("commits") else "")
                      for i in (row.items or [])) or "- (the night named no items)"
    home = (workspace_repo.for_code_run(folder) if folder
            else "the home task of the nightly code refactoring run")
    return "\n".join([
        f"‹owner› pressed Undo on night {row.number} of the nightly code refactoring run, in ‹his› "
        "morning brief. Revert exactly that night's refactors and nothing else.",
        "",
        "The night's commits, as it named them:",
        "",
        listed,
        "",
        "Its items:",
        "",
        items,
        "",
        "1. `git revert` each of those commits, newest first. Where a later commit built on one, "
        "resolve it so the code does what it did before that night and keeps what came after. "
        "Prove Rouh works in a browser, as AGENTS.md says, and run `./e2e.sh visual`. Commit "
        f"(\"refactor: undo night {row.number}\", with its `Gene:` lines) and land it with "
        "./land.sh, which deploys it.",
        f"2. In `{home}`: mark night {row.number}'s items in {DONE} as reverted, with the date and "
        "\"by ‹owner›'s Undo\", keeping them; put each back in "
        f"{TODO} with a note that ‹owner› undid it, not to be done again without a new reason; and "
        f"write into {NOTES} what was undone. Commit and land those files with ./land.sh.",
    ])


async def undo(who, number: int) -> str:
    """Undo, from the morning brief: a run that reverts that night's commits."""
    row = await asyncio.to_thread(night, who, number)
    if row is None:
        raise Refused("There is no such night of the refactoring run.")
    if row.undo_run_id:
        return f"Night {row.number} is already being undone, by run {row.undo_run_id}."
    if not row.commits:
        raise Refused(f"Night {row.number} named no commits, so there is nothing to undo.")
    if hooks.start is None:
        raise Refused("Rouh's runs are not ready yet. Try again in a minute.")
    folder = await asyncio.to_thread(task_folder)
    agent = await asyncio.to_thread(engine, who)
    got = await hooks.start(brief=owner.say(undo_brief(row, folder), who), title=f"Undo nightly refactoring, night {row.number}",
                            preset="improve_myself", agent=agent, use=USE, org_id=str(who.org_id),
                            one_fields=await asyncio.to_thread(one_fields, who, agent) or None)
    run_id = str(got.get("id") or "")
    await asyncio.to_thread(_update, row, undo_run_id=run_id, undone_at=time.time())
    await asyncio.to_thread(said, who, line_of(row))
    return (f"Run {run_id} is reverting night {row.number}'s {len(row.commits)} "
            f"commit{'' if len(row.commits) == 1 else 's'}, and deploys when it is done.")
