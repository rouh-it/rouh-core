"""The nightly Synapse run: one idea a night, measured, kept only when it helps (Petar, 5 October 2026).

Petar asked by voice for a recursive self-improvement loop for Synapse, serving one goal: when he writes a
message in any Rouh chat, Rouh already has what Synapse Master knows about it, quickly and accurately.

**When.** At 02:00 on the owner's own clock, every night, as a row of Rouh's own scheduled work: a reminder of
kind `server` whose job is `synapse_nightly` (`ensure`). So it is on the Reminders page and in `upcoming`,
and he pauses it, resumes it or moves it the way he does any reminder (`change_scheduled`). It is never a
chat turn: a scheduled turn may not change Rouh (`rouh/protected.py`), and this changes Rouh.

**What.** `start` writes the night's attempt row first (`improvements.start`), so there is always a row, and
starts one worker of the kind `improve_myself` starts (`starting.start`, preset `improve_myself`): a run in
its own checkout of Rouh's code that lands through `land.sh` when it ends. The worker follows the standing
brief in the folder above, `nightly_brief.md`, told tonight's attempt number and mode. It writes its findings
onto the row itself (`manage.py synapse_attempt`). `full` is a night as designed; `baseline` only measures
current main and records it, which is how the loop was first run by hand.

**Every night tries an idea** (Petar, 15 October 2026). A full night whose Synapse code changed since the last
judged night recalibrates first (`recalibrate.py`) and then goes on to its idea against that fresh before, where
until then it only measured. It measures and tries nothing only when the recalibration looked wrong, and says why.

**Always a row.** A worker that could not be started is written down as failed with the reason, here; one
that ended without writing its row is called failed by `improvements.settle`, which the morning brief, the
lab and the next night all run first.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable

#: Named for the old path (`rouh/synapse/nightly.py`), so the log reads as it did before the move.
log = logging.getLogger("rouh.synapse.nightly")

JOB = "synapse_nightly"
#: What the row says on the Reminders page.
WHAT = "Try one idea to make Synapse better, measure it, and keep it only if it helps"
#: Its line on the Reminders page and in the morning brief (`reminders.title_of`).
TITLE = "Synapse nightly improvement run"
AT = "02:00"
MODES = ("full", "baseline")
BRIEF = Path(__file__).resolve().parent.parent / "nightly_brief.md"


# --- the scheduled row --------------------------------------------------------------------------

def ensure(who) -> Any | None:
    """The person's row for the nightly run, made once (daily at 02:00 on their clock) and never again.

    A row the owner paused or moved stays as they left it; a deleted one is made again, since it is Rouh's own job
    and pausing is how it is stopped. Only for a person with a Synapse Master."""
    from ... import clock, reminders
    from .. import db, master

    if not db.ready() or not master.of(str(who.org_id), str(who.user_id)):
        return None
    got = reminders.server_row(who, JOB)
    if got is not None:
        return got
    with clock.person(who):
        first = reminders.moment_of(AT)
    row = reminders.add_server(who, job=JOB, title=TITLE, what=WHAT, first=first, repeat="daily")
    log.info("the nightly Synapse run is scheduled for %s/%s at %s on their clock (reminder %s)",
             who.org_id, who.user_id, AT, row.id)
    return row


def brief_for(attempt: dict, mode: str, rule: str = "") -> str:
    """The standing brief, and tonight's particulars after it, and `rule`: what an unattended run may see of
    the person's silos (`silos.run_rule`)."""
    standing = BRIEF.read_text()
    tonight = (
        "\n\n## Tonight\n\n"
        f"- Your attempt is number **{attempt['number']}**, already written as running: "
        f"`synapse_attempt update {attempt['number']} --user {attempt['user_id']} ...` writes onto it.\n"
        f"- Mode: **{mode}**. "
        + ("Measure current main and record it as a baseline, then stop: no idea is chosen and no code changes. "
           "Run the benchmark once judged and twice not judged, and the scale gate once; write `before` and `after` "
           "(the same pooled numbers, with the per-set measures), outcome `baseline`, the spend and a one-paragraph "
           "report, and end."
           if mode == "baseline" else
           "A full night: read, think, choose one idea, measure, keep or discard, record. If main's Synapse code "
           "changed since the last judged night (`synapse_nightly plan` says), recalibrate first (step 4) and then "
           "go on to the idea: a changed code alone never makes tonight a measuring night.")
        + f"\n- Account: user {attempt['user_id']}, organisation {attempt['org_id']}.\n"
        "- Write the row before you end your turn, whatever happened. If something stops you, write outcome "
        "`failed` and say what stopped it.\n")
    # An unattended run on Rouh itself sees only the silos runs see (`rouh/silos.py`). The benchmark's frozen
    # copy of Master is the one exception: it is measured whole, and what it is asked stays in its log.
    from ... import owner

    # A worker's brief leaves Rouh here, so the owner's marks in the standing brief are filled in for them.
    return owner.say(standing + tonight + rule.replace(" or not known, and keep", " or not known outside the "
                                                       "benchmark's own measurements, and keep"), attempt["user_id"])


#: Why a night cannot measure anything where this Rouh runs, or "" when it can (`cannot_measure`).
IN_CONTAINERS = (
    "The nightly Synapse worker was not started, because in the containers it could not measure anything: its "
    "worker is kept off the database network on purpose and holds no database password, so it cannot reach the "
    "frozen benchmark copy of Synapse Master or this attempt's row, and the server's way in "
    "(deploy/with-rouh-env.sh, through systemd) does not exist there. How a job may reach the live database "
    "safely is Decision 422, which is the owner's; until it is answered, each night is written down as failed "
    "with this reason rather than as a failure with none.")


def cannot_measure() -> str:
    """Why tonight's worker could measure nothing, or "". On the server a worker reaches the live database
    through deploy/with-rouh-env.sh. In the containers (the protected core's socket is set) it cannot, unless
    the installation names a way that was agreed (ROUH_SYNAPSE_NIGHTLY_ROUTE, the answer to Decision 422)."""
    import os

    if (os.environ.get("ROUH_SYNAPSE_NIGHTLY_ROUTE") or "").strip():
        return ""
    if os.environ.get("ROUH_GUARD_SOCKET") or os.environ.get("ROUH_SHELL") == "worker":
        return IN_CONTAINERS
    return ""


async def start(who, *, mode: str = "full", cfg: Any = None, crew: Any = None, one: Any = None,
                emit: Callable | None = None, run_state: Callable[[str], str] | None = None) -> dict:
    """Tonight's attempt: its row, then its worker. Returns the attempt row; never raises."""
    import asyncio

    from ... import starting
    from . import improvements

    mode = mode if mode in MODES else "full"
    org, user = str(who.org_id), str(who.user_id)
    await asyncio.to_thread(improvements.settle, org, user, run_state=run_state)
    busy = await asyncio.to_thread(improvements.running, org, user)
    attempt = await asyncio.to_thread(improvements.start, org, user, mode=mode, source="nightly")
    if busy:
        return await asyncio.to_thread(improvements.fail, org, user, attempt["number"],
                                       f"Attempt {busy[0]['number']} was still running, so a second worker was not "
                                       "started on top of it.")
    blocked = cannot_measure()
    if blocked:
        log.warning("the nightly Synapse attempt %s was not started: %s", attempt["number"], blocked[:120])
        return await asyncio.to_thread(improvements.fail, org, user, attempt["number"], blocked)
    try:
        from ... import silos

        rule = await asyncio.to_thread(silos.run_rule, user, org)
        got = await starting.start(brief=brief_for(attempt, mode, rule), title=f"Synapse nightly #{attempt['number']}"
                                   + (" (baseline)" if mode == "baseline" else ""),
                                   preset="improve_myself", org_id=org, cfg=cfg, crew=crew, one=one, emit=emit,
                                   # Synapse's own nightly work (`rouh/task_origin.py`).
                                   made_by="process:synapse")
    except starting.CannotStart as exc:
        return await asyncio.to_thread(improvements.fail, org, user, attempt["number"],
                                       f"The worker could not be started: {exc}")
    except Exception as exc:  # noqa: BLE001 - the row says what stopped it
        log.exception("the nightly Synapse worker could not be started")
        return await asyncio.to_thread(improvements.fail, org, user, attempt["number"],
                                       f"The worker could not be started: {type(exc).__name__}: {exc}")
    run_id = str(got.get("id") or "")
    return await asyncio.to_thread(improvements.update, org, user, attempt["number"], {"run_id": run_id})


def run_state(run_id: str) -> str:
    """A run's state in the run list's words, or "" when the register has no row."""
    from ... import runs

    row = runs.get(run_id)
    return runs.status_of(row) if row is not None else ""


def said_line(attempt: dict) -> str:
    """What the Reminders page says it did last time, after "Last time, ...:"."""
    if attempt.get("outcome") == "failed":
        return f"attempt {attempt['number']} could not start: {attempt.get('conclusion') or 'see the Improvements page'}"
    return (f"started attempt {attempt['number']}" + (f" as run {attempt['run_id']}" if attempt.get("run_id") else "")
            + "; its result is on the Synapse lab's Improvements page")
