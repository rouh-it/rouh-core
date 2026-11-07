"""Rouh's own checks: what a Rouh runs on itself before it moves onto a newer base image.

Petar, 23 October 2026: "latest" means only patch-level fixes to what Rouh runs on, and before a
Rouh switches to a newer base it runs that Rouh's own tests and the security tests, with its own
code, and switches only if they pass. This package is those tests. It is part of Rouh's code, so
it lives in each Rouh's own /code and goes wherever that code goes: a Rouh whose genes changed its
code is checked with its own code, never with the release's.

    python -m rouh.selfcheck              # everything, as the base check runs it
    python -m rouh.selfcheck --only security

It is run in a throwaway container: the new base image, the Rouh's /code mounted read-only, a
throwaway PostgreSQL beside it, and no network, no keys and nothing of the person's
(guard/bin/rouh-check, and the Mac app's `StackUpdater.check`). It never writes to the
code, and the only database it touches is the throwaway one, which it migrates itself.

Two groups, each a list of named checks with one plain sentence about what it proves:

- **own** (`own.py`): the code imports on this base, Django and the migrations agree, every
  model call still goes through the LLM service, the database migrates from empty, and Rouh's
  server starts and answers its health page.
- **security** (`security.py`): text from mail and pages cannot break out of its wrapper, every
  action that needs the person's yes is still refused without it, and one person's or
  organisation's data cannot be read by another.

A check that cannot even run (no database, say) is a failure, not a pass: a base nobody could
check is not switched to. What is already known to be missing is said as a **known gap**, kept
in `KNOWN_GAPS` with the reason, so it is never hidden and never blocks every update until it is
built.

The last line it prints is one line of JSON after ``ROUH-CHECK ``, which the Mac app and the
patch job read: ``{"ok": bool, "passed": n, "failed": [{"name", "why"}], "gaps": [...]}``.

Where a gene update will come in: a gene that adds an ability adds its own checks here, as a
module of this package named in `GROUPS`, in the same commit as the ability, so the next base is
checked against it too.

This is the one committed suite of Rouh's Python, on Petar's instruction of 23 October 2026
(AGENTS.md, "What is never asked of you"): it is not a regression suite of the repository, and
nobody runs it for a change it has nothing to do with.
"""
from __future__ import annotations

import json
import time
import traceback
from dataclasses import dataclass, field
from typing import Callable

#: The groups, in the order they run, and the module each lives in.
GROUPS = ("own", "security")

#: What is known to be missing, said on every run and never failed: (name, why).
KNOWN_GAPS = (
    ("chats and tasks are not separated per person",
     "the object store that holds chats, tasks and cards has no org_id or user_id yet "
     "(rouh/objects.py), and /api/transcript reads any chat by its id for any signed-in user; "
     "an installation is one person's until they are, so nothing here is shared yet"),
    ("approval prompts are off unless an installation lists tools",
     "the yes/no prompt before a tool runs covers only ROUH_CONFIRM_TOOLS, which is empty by "
     "default; what is always refused without the person's own words is checked instead"),
)


class Failed(AssertionError):
    """A check's plain reason for failing."""


@dataclass
class Check:
    group: str
    name: str
    proves: str
    run: Callable[[], None]
    needs_db: bool = False


@dataclass
class Report:
    passed: list[str] = field(default_factory=list)
    failed: list[dict] = field(default_factory=list)
    seconds: float = 0.0

    @property
    def ok(self) -> bool:
        return not self.failed and bool(self.passed)

    def line(self) -> str:
        return "ROUH-CHECK " + json.dumps({
            "ok": self.ok, "passed": len(self.passed), "failed": self.failed,
            "gaps": [name for name, _ in KNOWN_GAPS], "seconds": round(self.seconds, 1),
        }, ensure_ascii=False)


_CHECKS: list[Check] = []


def check(group: str, name: str, proves: str, *, needs_db: bool = False):
    """Registers a check. `proves` is the one sentence said beside it."""
    def put(fn):
        _CHECKS.append(Check(group, name, proves, fn, needs_db))
        return fn
    return put


def expect(ok, why: str) -> None:
    if not ok:
        raise Failed(why)


def checks(only: str = "") -> list[Check]:
    import importlib

    for g in GROUPS:
        importlib.import_module(f"{__name__}.{g}")
    return [c for c in _CHECKS if not only or c.group == only]


def run(only: str = "", say=print, db_ready: bool = True) -> Report:
    began = time.monotonic()
    report = Report()
    for c in checks(only):
        if c.needs_db and not db_ready:
            report.failed.append({"name": c.name, "group": c.group,
                                  "why": "it needs a database and none could be reached"})
            say(f"FAIL  {c.group}: {c.name} - it needs a database and none could be reached")
            continue
        started = time.monotonic()
        try:
            c.run()
        except Failed as e:
            report.failed.append({"name": c.name, "group": c.group, "why": str(e)[:600]})
            say(f"FAIL  {c.group}: {c.name} - {e}")
            continue
        except Exception as e:  # noqa: BLE001 - a check that breaks is a check that failed
            why = f"{type(e).__name__}: {e}"
            report.failed.append({"name": c.name, "group": c.group, "why": why[:600]})
            say(f"FAIL  {c.group}: {c.name} - it broke: {why}")
            say("      " + traceback.format_exc().strip().replace("\n", "\n      ")[-2000:])
            continue
        report.passed.append(c.name)
        say(f"ok    {c.group}: {c.name} ({time.monotonic() - started:.1f} s) - {c.proves}")
    for name, why in KNOWN_GAPS:
        say(f"gap   {name}: {why}")
    report.seconds = time.monotonic() - began
    return report
