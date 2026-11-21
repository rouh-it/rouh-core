"""Three genes on a run's head, for building Rouh faster (night 50 of the ledger, 21 November 2026).

Built by the nightly feature run, task 94, for the person's guidance that half of what is built
helps build Rouh faster. A run of the one program that changes Rouh is opened on the canvas
(`app/runs.js`, `oneRenderHead`): its state, its model, "Saved to main at abc1234", its terminal.
Three things were missing from it, each a gene of its own with its own switch:

- **Live or not live** (`run_live`, shows up by itself). Landing deploys, and only the deployed
  commit counts as done (AGENTS.md, "Done means deployed"). The one program has what `land.sh`
  said on its `work.landed` entry (`deployed`, `deploy`, `deploy_reason`), but the run kept only the
  sha, so the head said "Saved to main" for work that was on main and not served. Now the run keeps
  them (`one/views.py`, `_on_work_landed`) and the head says "live" or "NOT live: <the reason>".
- **Its changed files** (`run_files`, you ask for it). The run keeps the files its landing took
  (`files`, up to 200), and only a model asked with `what_changed` ever read them. Now the head
  has "N files changed", which opens the list under it.
- **Finish it** (`run_carry`, changes how you work). A run that ended with work left
  (`unfinished`, its `left` such as "it left 1 commit") or landed and is not live was carried on by
  typing a message into it. Now its head says what it left and has a Finish it button, which sends
  the run one fixed message to commit, land and see it live, the same as typing it.

The page is told which of the three are on (`on_for`, `PAGE_SWITCHES` in `rouh/web/views.py`), and
each reports its use through `POST /api/run-head` (`rouh/web/run_head.py`). No model, nothing kept
by Rouh: what is shown is the run's own record in the one program.
"""
from __future__ import annotations

#: Each gene's switch, its title, and the one event it reports.
GENES: dict[str, tuple[str, str]] = {
    "run_live": ("Live or not live, on a run's head", "seen"),
    "run_files": ("A run's changed files, one press from its head", "opened"),
    "run_carry": ("Finish it: a run that ended with work left, carried on with one press", "pressed"),
}

#: The message Finish it sends the run (`app/runs.js`); the same words for every run.
FINISH = ("Finish this work: commit everything that is left, land it with ./land.sh, and read "
          "its last sentence. If it is not live, say why and fix it. End by saying what land.sh "
          "said.")


def on_for(who) -> list[str]:
    """The switches of the three that are on for this person's organisation, for the page."""
    from . import switches

    if who is None:
        return []
    org = getattr(who, "org_id", None) or None
    return [name for name in GENES if switches.on(name, org)]


def used(who, switch: str, run: str) -> bool:
    """One of the three used on a run's head: counted, nothing else. False for one not known or off."""
    from . import evolution, switches

    if switch not in GENES or who is None:
        return False
    if not switches.on(switch, getattr(who, "org_id", None) or None):
        return False
    detail = str(run or "")[:40]
    if switch == "run_live":
        evolution.used("run_live", "seen", who=who, detail=detail)
    elif switch == "run_files":
        evolution.used("run_files", "opened", who=who, detail=detail)
    else:
        evolution.used("run_carry", "pressed", who=who, detail=detail)
    return True
