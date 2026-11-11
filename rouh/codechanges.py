"""Changes: what this Rouh's own code is, how a change of it goes live, and how it is put back.

Task 98, step 98-23 (24 October 2026). In a container a Rouh has a protected core beside it
(``guard/README.md``): a change of its code goes live only through the core's change step, which
checks it, keeps an undo point the Rouh cannot delete, and starts Rouh again on it, and a doctor
that puts the code back when Rouh stops answering right after a change. This module is the
Rouh's side of that, through ``rouh/guardface.py``:

* ``public(who)`` is what Meta, Changes shows (``/anatomy/meta/changes``, ``changespage.js``):
  the protected core and its contracts, the undo point that runs, every undo point, changes
  waiting for a newer core, and what the doctor last did.
* ``undo(who, n)`` puts the code back to undo point ``n``: an administrator's press only.
* ``Watch`` picks up a change a run proposes. A run in the worker cannot reach the core's socket,
  and only reads /code, so it works in a clone and leaves its commits as a git bundle in the shared
  folder ``/run/one/proposals`` (``guard/bin/rouh-propose``); this fetches them into /code and
  proposes them, and writes the core's answer back beside the bundle for the run to read. It tells
  the person only when a change did not go live, or waits for a Rouh update, and once when the
  doctor put the code back; a change that passed and is live is an undo point on Changes, unsaid.

A Rouh with no protected core beside it (the server it runs on, a test world) says so, and
changes reach it through land.sh as before.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
import subprocess
import time
import uuid
from pathlib import Path

from . import guardface

log = logging.getLogger("rouh.codechanges")

ROUTE = "/anatomy/meta/changes"
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$")


class Refused(ValueError):
    """A press that is not done, with the reason as a sentence."""


def proposals_dir() -> Path:
    return Path(os.environ.get("ROUH_PROPOSALS_DIR", "/run/one/proposals"))


def code_dir() -> Path:
    return Path(os.environ.get("ROUH_APP_DIR") or Path(__file__).resolve().parents[1])


def _admin(who) -> None:
    if who is None:
        raise Refused("Sign in first.")
    if not getattr(who, "is_admin", False):
        raise Refused("Only an administrator of this Rouh puts its code back.")


def public(who) -> dict:
    """Meta, Changes: everything about this Rouh's code and its protected core."""
    if who is None:
        raise Refused("Sign in first.")
    if not guardface.here():
        return {"guard": False, "said": "This Rouh has no protected core beside it: it runs on a server, "
                                        "where changes of its code land through land.sh."}
    try:
        status = guardface.ask("status")
        points = guardface.ask("points").get("points") or []
    except guardface.Unavailable as exc:
        return {"guard": True, "answering": False, "said": f"The protected core did not answer: {exc}"}
    return {"guard": True, "answering": True, "version": status.get("version"),
            "contracts": status.get("contracts") or {}, "code": status.get("code") or {},
            "busy": status.get("busy") or "", "pending": status.get("pending") or [],
            "events": status.get("events") or [], "doctor": status.get("doctor") or {},
            "notice": status.get("notice"), "points": points,
            "admin": bool(getattr(who, "is_admin", False))}


def undo(who, n: int) -> dict:
    _admin(who)
    try:
        got = guardface.ask("undo", point=int(n), by=f"{getattr(who, 'name', '') or 'a person'}, on Changes",
                            timeout=120.0)
    except guardface.Refused as exc:
        raise Refused(str(exc)) from None
    except guardface.Unavailable as exc:
        raise Refused(f"The protected core did not answer: {exc}") from None
    return {"said": got.get("said") or f"Put back to undo point {n}. Rouh starts again on it in a moment."}


# --- a run's proposals -----------------------------------------------------------------------


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-c", "safe.directory=*", *args], cwd=str(code_dir()),
                          capture_output=True, text=True)


def _write(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False))
    tmp.replace(path)


def take(bundle: Path) -> dict:
    """One proposal: its commits into /code, then the protected core's answer."""
    name = bundle.stem
    meta_file = bundle.with_suffix(".json")
    try:
        meta = json.loads(meta_file.read_text()) if meta_file.is_file() else {}
    except ValueError:
        meta = {}
    why = str(meta.get("why") or "")[:500]
    ref = f"refs/proposals/{name}"
    if not NAME.match(name):
        return {"ok": False, "refused": "a proposal's name is letters, digits, dots and dashes"}
    got = _git("fetch", "-q", str(bundle), f"+HEAD:{ref}")
    if got.returncode:
        return {"ok": False, "refused": "its commits could not be read into this Rouh's code: "
                                        + (got.stderr or got.stdout).strip()[-300:]}
    commit = _git("rev-parse", ref).stdout.strip()
    base = _git("rev-parse", "HEAD").stdout.strip()
    if base and commit and _git("merge-base", "--is-ancestor", commit, base).returncode == 0:
        # Already in the code that runs (asked again after a restart, say): proposing it again
        # could only move the code back.
        try:
            point = (guardface.ask("status").get("code") or {}).get("point")
        except (guardface.Refused, guardface.Unavailable):
            point = None
        return {"ok": True, "commit": commit, "point": point, "said": "It is already in the code that runs."}
    if base and commit and _git("merge-base", "--is-ancestor", base, commit).returncode != 0:
        # Made on top of older code: another change went live while this one waited its turn.
        # Running it would take that change out again (11 November 2026: undo point 174 was made on
        # 172 while 173 was being checked, and put 173's change out of the code that ran). The run's
        # landing fits it on top of the code that runs and hands it over again (bin/rouh-land).
        return {"ok": False, "commit": commit, "moved_on": base,
                "refused": f"it is not on top of the code that runs ({base[:12]}): another change went live "
                           "while it waited, so it has to be fitted on top of that one first"}
    try:
        answer = guardface.ask("propose", commit=commit, why=why, by=str(meta.get("by") or "a run")[:80],
                               timeout=3600.0)
    except guardface.Refused as exc:
        return {"ok": False, "commit": commit, "refused": str(exc)}
    except guardface.Unavailable as exc:
        return {"ok": False, "commit": commit, "error": str(exc)}
    _keep_landing(str(meta.get("by") or ""),
                  (_git("rev-list", "--reverse", f"{base}..{commit}").stdout.split() if base else []) or [commit])
    return {"ok": True, "commit": commit, "point": answer.get("point"), "said": answer.get("said", "")}


def _keep_landing(by: str, commits: list[str]) -> None:
    """Which run a change came from, for the gene log (`rouh/genelog.py`, `landings`), the same line
    land.sh writes as it pushes on the server (`keep_landing`): the time, the run, its commits."""
    import time

    from .config import config

    run = by[4:].strip() if by.startswith("run ") else ""
    if not run or not commits:
        return
    try:
        folder = Path(config.land_dir)
        folder.mkdir(parents=True, exist_ok=True)
        with open(folder / "landed.tsv", "a", encoding="utf-8") as fh:
            fh.write(f"{int(time.time())}\t{run}\t{' '.join(commits)}\n")
    except OSError:
        log.warning("which run a change came from could not be written down", exc_info=True)


#: This start of Rouh, written beside every proposal it is checking.
THIS_START = uuid.uuid4().hex


def _left_by_an_earlier_start(result: Path) -> bool:
    """A proposal still "checking" whose Rouh was started again meanwhile - by the change before it
    going live, which restarts the core - never gets its answer written by that Rouh: this one asks
    the protected core again. The core answers at once if the change is already the code that runs."""
    try:
        got = json.loads(result.read_text())
    except (OSError, ValueError):
        return False
    return got.get("state") == "checking" and got.get("by") != THIS_START


def quiet(got: dict) -> tuple[str, str] | None:
    """What the person is told about one proposal's answer, as (title, body), or None for a
    change that passed its checks and is live: that one is only an undo point on Changes."""
    if got.get("ok") or got.get("moved_on"):
        # A change made on older code is fitted again and handed over by its own landing.
        return None
    refused = str(got.get("refused") or "")
    if refused.startswith("Waiting for a Rouh update"):
        return "A change of Rouh's code waits for a Rouh update", refused[:900]
    return "A change of Rouh's code did not go live", (refused or str(got.get("error") or ""))[:900]


class Watch:
    """Picks up proposals and the doctor's notice, every few seconds, where there is a core."""

    def __init__(self, every: float = 10.0) -> None:
        self.every = every
        self.task: asyncio.Task | None = None

    def start(self) -> None:
        if not guardface.here():
            return
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self._loop(), name="codechanges")

    async def stop(self) -> None:
        if self.task is not None:
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self.task
            self.task = None

    async def _loop(self) -> None:
        await asyncio.sleep(5)
        while True:
            try:
                await self.once()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - one bad look never stops the next
                log.exception("the look for proposed changes stumbled; continuing")
            await asyncio.sleep(self.every)

    async def once(self) -> None:
        await self._notice()
        folder = proposals_dir()
        if not folder.is_dir():
            return
        for bundle in sorted(folder.glob("*.bundle")):
            result = bundle.with_suffix(".result.json")
            if result.exists() and not _left_by_an_earlier_start(result):
                continue
            _write(result, {"state": "checking", "at": time.time(), "by": THIS_START})
            got = await asyncio.to_thread(take, bundle)
            got.update(state="done", at=time.time())
            _write(result, got)
            await self._tell(got)

    async def _tell(self, got: dict) -> None:
        """Tell the person only what needs them or went wrong.

        Petar, 3 November 2026: "They don't carry information or action ... I don't need to
        know about it." A change that passed its checks and is live as an undo point is not
        told at all: the point is kept and listed on Changes, which is where to look. A change
        that did not go live, or waits for a Rouh update, still is, and so is the doctor's
        putting the code back (`_notice`)."""
        from . import notices

        said = quiet(got)
        if said is None:
            return
        title, body = said
        await notices.notify(title=title, body=body, link=ROUTE, link_label="Changes", kind="rouh",
                             key=f"codechange-{str(got.get('commit') or '')[:12]}")

    async def _notice(self) -> None:
        """What the doctor did, said once."""
        from . import notices

        signal = Path(os.environ.get("ROUH_GUARD_SIGNAL", "/run/guard-signal")) / "state.json"
        try:
            notice = json.loads(signal.read_text()).get("notice")
        except (OSError, ValueError):
            return
        if not notice or not notice.get("id"):
            return
        seen = Path(os.environ.get("ROUH_DATA_DIR", "/data/rouh")) / "guard-notice-seen"
        with contextlib.suppress(OSError):
            if seen.read_text().strip() == str(notice["id"]):
                return
        await notices.notify(title="The doctor put Rouh's code back", body=str(notice.get("said") or "")[:900],
                             link=ROUTE, link_label="Changes", kind="rouh", key=f"doctor-{notice['id']}",
                             phone_text=str(notice.get("said") or "")[:500])
        seen.parent.mkdir(parents=True, exist_ok=True)
        seen.write_text(str(notice["id"]))
