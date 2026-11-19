"""The update step brought up to date by the protected core itself (core 1.1, 17 November 2026).

Core 1.1.1 (19 November 2026): the update step is brought to the release's whenever it is behind,
not only when it lacks exact copies, so a fix to how the update step reads a change reaches a Rouh
whose update is stuck behind the very change it misreads.

A Rouh takes released changes with its own update step, ``rouh/code_evolution.py``, which is part
of its own code. Until 17 November 2026 that step handed any file it could not copy whole to a
model as text, so a vendored three.js of 700 KB on one line never came in, and the 35 changes
after it waited behind it. The fixed update step is itself a released change, and it would have
waited behind the same one.

So the protected core, which a Rouh cannot edit and which reaches every Rouh by the signed release,
carries the way out. Once it runs, it looks whether the Rouh's update step copies files exactly
(the line ``EXACT_COPIES = 1`` in ``rouh/code_evolution.py``). When it does not, and the newest
release's does, the core copies exactly the files the release names as its update step
(``UPDATE_STEP`` there), blob for blob, over the Rouh's own, through the ordinary change step: the
checks, an undo point the person can put back in Meta, Changes, and the core started again on it.

- Only files the Rouh never changed itself are replaced: each must be, byte for byte, a version that
  shared main once had. A Rouh that changed its own update step keeps it, and the core says so.
- Nothing else of the Rouh's code is touched. Everything else still comes through the Rouh's own
  update, which now copies each released file exactly (``rouh/code_evolution.py``).
- It needs nothing from anyone: it looks a couple of minutes after the core starts, and every six
  hours after until the Rouh's update step has it. ``ROUH_GUARD_UPDATE_STEP=0`` turns it off.
- The newest release is rouh.land's (``ROUH_CODE_RELEASE_URL``), its code shared main on GitHub
  (``ROUH_CODE_MASTER``), both through the key proxy, as the first start's install reads them.
"""
from __future__ import annotations

import ast
import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

from . import VERSION
from .changes import ROUH, SAFE

log = logging.getLogger("rouh-guard")

MARK = re.compile(r"^EXACT_COPIES\s*=\s*1\s*(?:#.*)?$", re.M)
STEP = "rouh/code_evolution.py"
REF = "refs/rouh/update-step/main"
#: How far back shared main is read for the versions it once had of a file.
HISTORY = 4000


def on() -> bool:
    return os.environ.get("ROUH_GUARD_UPDATE_STEP", "1") != "0"


def release_url() -> str:
    site = (os.environ.get("ROUH_SITE_URL") or "https://rouh.land").strip().rstrip("/")
    return os.environ.get("ROUH_CODE_RELEASE_URL") or f"{site}/mac/code/release.json"


def sources() -> list[str]:
    own = os.environ.get("ROUH_CODE_MASTER", "").strip()
    return [own] if own else ["https://github.com/rouh-land/rouh-core.git"]


def _git(code: Path, *args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    pre = ROUH if os.getuid() == 0 else []
    return subprocess.run([*pre, "git", *args], cwd=str(code), capture_output=True, text=True, timeout=900,
                          env={**os.environ, **SAFE, "GIT_TERMINAL_PROMPT": "0", "HOME": "/tmp", **(env or {})})


def _out(code: Path, *args: str, env: dict | None = None) -> str:
    r = _git(code, *args, env=env)
    return r.stdout.strip() if r.returncode == 0 else ""


def _blob(code: Path, commit: str, path: str) -> str:
    """mode and hash of path at commit, "" when it is not there."""
    got = _out(code, "ls-tree", commit, "--", path).split("\t", 1)[0].split()
    return f"{got[0]} {got[2]}" if len(got) == 3 else ""


def step_files(text: str) -> list[str]:
    """The files the release names as its update step, read (never run) from its code_evolution.py."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "UPDATE_STEP" for t in node.targets):
            try:
                value = ast.literal_eval(node.value)
            except ValueError:
                return []
            files = [str(f) for f in value if isinstance(f, str)]
            if STEP not in files or any(not re.fullmatch(r"rouh/[A-Za-z0-9_/]+\.py", f) or ".." in f for f in files):
                return []
            return files
    return []


class UpdateStep:
    def __init__(self, changes) -> None:
        self.changes = changes
        self.file = Path(changes.state) / "update-step.json"
        self.last: dict = {}
        if self.file.is_file():
            try:
                self.last = json.loads(self.file.read_text())
            except ValueError:
                self.last = {}

    def status(self) -> dict:
        return {"on": on(), **self.last}

    def _keep(self, **fields) -> dict:
        self.last = {"at": round(time.time(), 1), "core": VERSION, **fields}
        tmp = self.file.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.last, indent=1, ensure_ascii=False))
        tmp.replace(self.file)
        return self.last

    def _release(self) -> str:
        req = urllib.request.Request(release_url(), headers={"User-Agent": f"rouh-guard/{VERSION}",
                                                             "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            got = json.loads(r.read(1024 * 1024))
        commit = str((got or {}).get("commit") or "")
        if not re.fullmatch(r"[0-9a-f]{40}", commit):
            raise ValueError("rouh.land's release names no commit")
        return commit

    def look(self) -> dict:
        """What there is to do, and the commit that does it when there is: {"what": done, wait,
        own, ready, ...}. Makes the commit in /code, moves nothing."""
        code, ch = Path(self.changes.code), self.changes
        head = ch.head()
        cur = ch.point(ch.data.get("current"))
        if not head or not cur or cur["commit"] != head or not ch.clean() or ch.busy:
            return {"what": "wait", "said": "the code that runs is busy or not yet an undo point"}
        here = _git(code, "show", f"{head}:{STEP}")
        if here.returncode:
            return {"what": "wait", "said": "this Rouh has no update step of its own yet (rouh-catch-up is its way)"}
        # Core 1.1.1: not only an update step without exact copies. Any update step that is behind the
        # release's, and that this Rouh never changed itself, is brought to the release's: on 19 November
        # 2026 85 changes waited behind one the update step misread as a security and database change,
        # and its fix was itself a released change that would have waited behind the same one.
        release = self._release()
        if release == self.last.get("release") and self.last.get("what") in ("done", "taken") \
                and _blob(code, head, STEP) == self.last.get("step_blob"):
            return {"what": "done", "said": "the update step is already the release's", "release": release,
                    "step_blob": self.last.get("step_blob")}
        if release == self.last.get("release") and self.last.get("what") == "own":
            return {"what": "wait", "said": self.last.get("said", ""), "release": release}
        why = ""
        for url in sources():
            r = _git(code, "fetch", "-q", "--no-tags", url, f"+refs/heads/main:{REF}")
            if r.returncode == 0:
                why = ""
                break
            why = (r.stderr or r.stdout).strip()[-300:]
        if why:
            raise ValueError(f"shared main could not be fetched: {why}")
        if _git(code, "merge-base", "--is-ancestor", release, REF).returncode:
            raise ValueError(f"the release {release[:12]} is not on shared main")
        theirs = _out(code, "show", f"{release}:{STEP}")
        if not MARK.search(theirs):
            return {"what": "wait", "said": "the newest release's update step does not copy files exactly yet",
                    "release": release}
        files = step_files(theirs)
        if not files:
            return {"what": "wait", "said": "the newest release names no update step files", "release": release}
        change = []
        for f in files:
            want, have = _blob(code, release, f), _blob(code, head, f)
            if not want:
                return {"what": "wait", "said": f"the release has no {f}", "release": release}
            if have == want:
                continue
            if have and not self._released(code, release, f, have.split()[1]):
                return {"what": "own", "release": release,
                        "said": f"this Rouh changed its own {f}, so the protected core leaves its update step as it is"}
            change.append((f, want))
        if not change:
            return {"what": "done", "said": "the update step is already the release's", "release": release,
                    "step_blob": _blob(code, head, STEP)}
        commit = self._commit(code, head, release, change)
        return {"what": "ready", "commit": commit, "on": head, "release": release, "files": [f for f, _ in change]}

    def _released(self, code: Path, release: str, f: str, blob: str) -> bool:
        """Whether blob is a version of f that shared main once had."""
        raw = _out(code, "log", f"-n{HISTORY}", "--format=", "--raw", "--no-abbrev", "--no-renames", release, "--", f)
        seen = set()
        for line in raw.splitlines():
            parts = line.split("\t", 1)[0].split()
            if len(parts) >= 4:
                seen.update(parts[2:4])
        return blob in seen

    def _commit(self, code: Path, head: str, release: str, change: list[tuple[str, str]]) -> str:
        """A commit on head with exactly the release's blobs of the update step, checked."""
        tmp = Path(tempfile.mkdtemp(prefix="guard-update-step-"))
        try:
            if os.getuid() == 0:
                os.chown(tmp, 10001, 10001)
            env = {"GIT_INDEX_FILE": str(tmp / "index"), "GIT_AUTHOR_NAME": "Rouh's protected core",
                   "GIT_AUTHOR_EMAIL": "rouh@localhost", "GIT_COMMITTER_NAME": "Rouh's protected core",
                   "GIT_COMMITTER_EMAIL": "rouh@localhost"}
            if _git(code, "read-tree", head, env=env).returncode:
                raise ValueError("the code that runs could not be read")
            for f, want in change:
                mode, blob = want.split()
                if _git(code, "update-index", "--add", "--cacheinfo", f"{mode},{blob},{f}", env=env).returncode:
                    raise ValueError(f"{f} could not be put in place")
            tree = _out(code, "write-tree", env=env)
            names = ", ".join(f for f, _ in change)
            message = (f"Rouh's update step from the release {release[:8]}, copied exactly by the protected core {VERSION}\n\n"
                       f"{names}: the release's own files, blob for blob, so that this Rouh's update copies each "
                       "released file exactly and takes the changes waiting behind one it could not.\n\n"
                       f"Rouh-update-step: {release}")
            commit = _out(code, "commit-tree", tree, "-p", head, "-m", message, env=env)
            if not re.fullmatch(r"[0-9a-f]{40}", commit):
                raise ValueError("the commit could not be made")
            for f, want in change:
                if _blob(code, commit, f) != want:
                    raise ValueError(f"{f} did not come out exactly as the release has it")
            if _git(code, "update-ref", "refs/rouh/update-step/commit", commit).returncode:
                raise ValueError("the commit could not be kept")
            return commit
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    async def once(self) -> dict:
        """One look, and the change through the change step when there is one."""
        try:
            got = await asyncio.to_thread(self.look)
        except Exception as exc:  # noqa: BLE001 - said, and looked at again later
            return self._keep(what="failed", said=str(exc)[-400:])
        if got["what"] != "ready":
            if got["what"] != "wait" or got.get("release"):
                return self._keep(**got)
            return got
        answer = await self.changes.propose(
            got["commit"], f"Rouh's update step from the release {got['release'][:8]}, copied exactly",
            by=f"the protected core {VERSION}", on=got["on"])
        if answer.get("ok"):
            log.info("the update step from %s is in place: %s", got["release"][:12], ", ".join(got["files"]))
            return self._keep(what="taken", release=got["release"], commit=got["commit"], files=got["files"],
                              step_blob=_blob(Path(self.changes.code), got["commit"], STEP),
                              point=(answer.get("point") or {}).get("n"),
                              said="the release's update step was copied exactly and runs")
        return self._keep(what="refused", release=got["release"], commit=got["commit"],
                          said=str(answer.get("refused") or answer.get("error") or "refused")[:600])

    async def watch(self, first: float | None = None, every: float | None = None) -> None:
        first = float(os.environ.get("ROUH_GUARD_UPDATE_STEP_FIRST", "120")) if first is None else first
        every = float(os.environ.get("ROUH_GUARD_UPDATE_STEP_EVERY", "21600")) if every is None else every
        await asyncio.sleep(first)
        while True:
            try:
                got = await self.once()
                if got.get("what") in ("done", "taken"):
                    log.info("the update step: %s", got.get("said"))
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - one bad look never stops the next
                log.exception("the update step's look stumbled")
            await asyncio.sleep(every)
