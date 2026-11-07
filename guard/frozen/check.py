"""The frozen checks' own small frame: a list of named checks, each with one plain sentence.

Kept apart from the Rouh's ``rouh.selfcheck`` on purpose: a Rouh may change that package, and
these checks must not move with it.
"""
from __future__ import annotations

import time
import traceback
from dataclasses import dataclass, field
from typing import Callable


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


CHECKS: list[Check] = []


def check(group: str, name: str, proves: str, *, needs_db: bool = False):
    def put(fn):
        CHECKS.append(Check(group, name, proves, fn, needs_db))
        return fn
    return put


def expect(ok, why: str) -> None:
    if not ok:
        raise Failed(why)


def run(say=print, db_ready: bool = True) -> Report:
    report = Report()
    for c in CHECKS:
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
    return report
