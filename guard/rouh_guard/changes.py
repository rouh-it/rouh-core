"""The change step and its undo points: how a change of a Rouh's own code goes live.

Part of the protected core (guard/README.md; task 98, step 98-23). A Rouh changes its own code
freely - a gene, a skill, a fix it noticed - as commits in /code. A change goes live only through
here:

1. **propose(commit)**: the commit is checked in a folder of its own, as a user that can write
   nothing of the guard's (``checks.py``): the frozen security checks, then the Rouh's own checks.
   A gene in it whose manifest says ``needs_guard`` newer than this core waits instead, and is
   tried again when a newer core arrives.
2. If it passes, an **undo point** is saved: the commit fetched into the guard's own copy of the
   history (``/guard/history.git``, ref ``refs/points/<n>``), which the Rouh cannot reach, so it
   cannot rewrite or delete one. /code's main is moved to it, and the core (and the worker, when
   the one program changed) are told to start again on it.
3. If it fails, nothing goes live. When the Rouh had already moved main to it, main is put back
   and the commit is kept on a branch ``refused/<time>``, so nothing is lost.

**undo(point)** puts /code back to any undo point, from the guard's copy if /code no longer has
it. **verify** is asked by the core's start script: a /code whose main was moved without the
guard is checked first, and work not committed is kept on a branch ``set-aside/<time>``, so what
runs is always an undo point.

The guard cannot restart a container: no container has the Docker socket. It writes
``state.json`` into the guard-signal volume, which the start scripts (the guard's own) read, and
each restarts its container's program when its number moves; Docker's own restart policy does the
rest.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import time
from pathlib import Path

from . import VERSION, satisfies

log = logging.getLogger("rouh-guard")

ROUH = ["setpriv", "--reuid=10001", "--regid=10001", "--init-groups", "--"]
SAFE = {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "safe.directory", "GIT_CONFIG_VALUE_0": "*"}
#: Paths whose change means the worker's program changed too.
WORKER_PATHS = ("one/", "deploy/", "bin/", "mcp-servers.json")
MOST_EVENTS = 200


def _git(*args: str, cwd: str | Path, as_rouh: bool = True, check: bool = False) -> subprocess.CompletedProcess:
    pre = ROUH if as_rouh and os.getuid() == 0 else []
    r = subprocess.run([*pre, "git", *args], cwd=str(cwd), capture_output=True, text=True,
                       env={**os.environ, **SAFE, "GIT_TERMINAL_PROMPT": "0", "HOME": "/tmp"})
    if check and r.returncode:
        raise RuntimeError(f"git {args[0]}: {(r.stderr or r.stdout).strip()[-300:]}")
    return r


def _now() -> float:
    return round(time.time(), 1)


class Changes:
    def __init__(self, code: Path, state: Path, signal: Path, *, check=None):
        self.code = code
        self.state = state
        self.signal = signal
        self.history = state / "history.git"
        self.file = state / "points.json"
        self.lock = asyncio.Lock()
        self.busy = ""
        self._check = check
        self.data = {"points": [], "current": None, "events": [], "pending": [], "restart": {"core": 0, "worker": 0},
                     "notice": None}

    @classmethod
    def from_environment(cls) -> "Changes":
        return cls(Path(os.environ.get("ROUH_APP_DIR", "/code")), Path(os.environ.get("ROUH_GUARD_STATE", "/guard")),
                   Path(os.environ.get("ROUH_GUARD_SIGNAL", "/run/guard-signal")))

    # --- what is kept -----------------------------------------------------------------------

    def _load(self) -> None:
        if self.file.is_file():
            try:
                self.data.update(json.loads(self.file.read_text()))
            except ValueError:
                log.error("points.json could not be read; its copy is kept beside it")
                self.file.rename(self.file.with_suffix(f".unreadable-{int(time.time())}"))

    def _save(self) -> None:
        self.data["events"] = self.data["events"][-MOST_EVENTS:]
        tmp = self.file.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=1, ensure_ascii=False))
        os.chmod(tmp, 0o600)
        tmp.replace(self.file)
        self._signal()

    def _signal(self) -> None:
        """What the start scripts read: the point that should run, and when to start again."""
        cur = self.point(self.data.get("current"))
        out = {"point": cur["n"] if cur else None, "commit": cur["commit"] if cur else "",
               "restart": self.data["restart"], "notice": self.data.get("notice"), "version": VERSION}
        self.signal.mkdir(parents=True, exist_ok=True)
        tmp = self.signal / ".state.tmp"
        tmp.write_text(json.dumps(out, ensure_ascii=False))
        os.chmod(tmp, 0o644)
        tmp.replace(self.signal / "state.json")

    def _event(self, what: str, said: str, **more) -> None:
        self.data["events"].append({"at": _now(), "what": what, "said": said, **more})
        log.info("%s: %s", what, said)

    def point(self, n) -> dict | None:
        for p in self.data["points"]:
            if p["n"] == n:
                return p
        return None

    def points(self) -> list[dict]:
        return [dict(p, current=p["n"] == self.data.get("current")) for p in reversed(self.data["points"])]

    def status(self) -> dict:
        cur = self.point(self.data.get("current"))
        return {"code": {"point": cur, "head": self.head(), "clean": self.clean()},
                "busy": self.busy, "pending": self.data["pending"], "events": self.data["events"][-20:][::-1],
                "notice": self.data.get("notice")}

    # --- /code ------------------------------------------------------------------------------

    def head(self) -> str:
        r = _git("rev-parse", "--verify", "-q", "HEAD^{commit}", cwd=self.code)
        return r.stdout.strip() if r.returncode == 0 else ""

    def clean(self) -> bool:
        r = _git("status", "--porcelain", "--untracked-files=normal", cwd=self.code)
        return r.returncode == 0 and not r.stdout.strip()

    def resolve(self, ref: str) -> str:
        if not ref or ref.startswith("-"):
            return ""
        r = _git("rev-parse", "--verify", "-q", f"{ref}^{{commit}}", cwd=self.code)
        return r.stdout.strip() if r.returncode == 0 else ""

    def _keep(self, commit: str, n: int) -> None:
        """The commit into the guard's own copy of the history, as undo point n."""
        _git("fetch", "-q", str(self.code), f"{commit}:refs/points/{n}", cwd=self.history, check=True)

    def _move(self, commit: str) -> None:
        """/code's main to `commit`, its working files to match, nothing of anyone's lost."""
        if not self.resolve(commit):
            n = next((p["n"] for p in self.data["points"] if p["commit"] == commit), None)
            if n is None:
                raise RuntimeError(f"{commit[:12]} is in neither /code nor the guard's copy")
            _git("fetch", "-q", str(self.history), f"refs/points/{n}", cwd=self.code, check=True)
        _git("checkout", "-q", "-f", "-B", "main", commit, cwd=self.code, check=True)
        _git("clean", "-q", "-f", "-d", cwd=self.code, check=True)

    def _restart(self, old: str, new: str) -> list[str]:
        who = ["core"]
        if old and new:
            r = _git("diff", "--name-only", old, new, cwd=self.code)
            if r.returncode or any(f.startswith(WORKER_PATHS) for f in r.stdout.split()):
                who.append("worker")
        else:
            who.append("worker")
        for w in who:
            self.data["restart"][w] = int(self.data["restart"].get(w, 0)) + 1
        return who

    def _set_aside(self, kind: str) -> str:
        """Work not committed, or a commit refused, kept on a branch of its own; its name."""
        name = f"{kind}/{time.strftime('%Y%m%d-%H%M%S', time.gmtime())}"
        _git("switch", "-q", "-c", name, cwd=self.code, check=True)
        if not self.clean():
            _git("add", "-A", cwd=self.code, check=True)
            _git("-c", "user.name=Rouh", "-c", "user.email=rouh@localhost", "commit", "-q", "-m",
                 "Set aside by the protected core: not committed when Rouh started", cwd=self.code, check=True)
        return name

    # --- the start ------------------------------------------------------------------------------

    async def start(self) -> None:
        self.state.mkdir(parents=True, exist_ok=True)
        os.chmod(self.state, 0o711)
        if not (self.history / "HEAD").is_file():
            self.history.mkdir(parents=True, exist_ok=True)
            os.chown(self.history, 10001, 10001)
            _git("init", "-q", "--bare", str(self.history), cwd=self.history, check=True)
        # The guard's git works as rouh's user inside the guard's own box; nothing else mounts it.
        subprocess.run(["chown", "-R", "10001:10001", str(self.history)], check=False)
        self._load()
        if not self.data["points"]:
            head = self.head()
            if head:
                self._keep(head, 1)
                self.data["points"].append({"n": 1, "commit": head, "at": _now(), "kind": "first",
                                            "why": "the code this Rouh had when its protected core first started",
                                            "by": "the protected core", "checked": None})
                self.data["current"] = 1
                self._event("first", f"Undo point 1 is {head[:12]}, the code this Rouh started with.")
        self._save()
        if self.data["pending"]:
            asyncio.create_task(self._retry_pending())

    async def _retry_pending(self) -> None:
        for p in list(self.data["pending"]):
            if all(satisfies(n) for n in p.get("needs", {}).values()):
                self.data["pending"].remove(p)
                self._save()
                await self.propose(p["commit"], p.get("why", ""), by="the protected core, once it was new enough")

    # --- the contract's calls ---------------------------------------------------------------

    def _needs(self, commit: str) -> dict:
        """Each gene in the commit whose manifest needs a newer protected core: {gene: need}."""
        out = {}
        r = _git("ls-tree", "--name-only", commit, "rouh/genes/manifests/", cwd=self.code)
        for path in r.stdout.split():
            if not path.endswith(".json"):
                continue
            body = _git("show", f"{commit}:{path}", cwd=self.code).stdout
            try:
                need = json.loads(body).get("needs_guard")
            except ValueError:
                continue
            if need and not satisfies(str(need)):
                out[Path(path).stem] = str(need)
        return out

    async def propose(self, ref: str, why: str = "", *, by: str = "the Rouh", update: dict | None = None) -> dict:
        commit = self.resolve(ref)
        if not commit:
            return {"ok": False, "refused": f"/code has no commit {str(ref)[:40]!r}"}
        async with self.lock:
            cur = self.point(self.data.get("current"))
            if cur and cur["commit"] == commit:
                return {"ok": True, "point": cur, "said": "That is the code that runs already."}
            needs = self._needs(commit)
            if needs:
                self.data["pending"] = [p for p in self.data["pending"] if p["commit"] != commit]
                self.data["pending"].append({"commit": commit, "why": why, "by": by, "needs": needs, "at": _now()})
                said = ("Waiting for a Rouh update: " + "; ".join(f"the gene {g} needs the protected core {n}"
                                                               for g, n in needs.items()) + f", and this one is {VERSION}.")
                self._event("waiting", said, commit=commit)
                if self.head() == commit and cur:
                    kept = self._set_aside("waiting")
                    self._move(cur["commit"])
                    said += f" It is kept on {kept} meanwhile."
                self._save()
                return {"ok": False, "refused": said, "waiting": True}
            self.busy = f"checking {commit[:12]}"
            self._save()
            try:
                checked = await asyncio.to_thread(self._check or self._default_check, commit)
            finally:
                self.busy = ""
            if not checked["ok"]:
                names = "; ".join(f"{f['name']}: {f['why']}"[:300] for f in checked["failed"][:6])
                said = f"{commit[:12]} did not pass its checks, so it does not run. What failed: {names}"
                if self.head() == commit and cur:
                    kept = self._set_aside("refused")
                    self._move(cur["commit"])
                    said += f" It is kept on the branch {kept}."
                self._event("refused", said, commit=commit, why=why, by=by)
                self._save()
                return {"ok": False, "refused": said, "failed": checked["failed"]}
            if update is not None:
                from . import updatecheck

                self.busy = f"proving master change {commit[:12]}"
                self._save()
                try:
                    proof = await asyncio.to_thread(updatecheck.run, self.code, cur["commit"], commit, update, self.state)
                finally:
                    self.busy = ""
                if not proof["ok"]:
                    said = "; ".join(f["why"] for f in proof["failed"])
                    self._event("refused", said, commit=commit, why=why, by=by)
                    self._save()
                    return {"ok": False, "refused": said, "failed": proof["failed"]}
                checked["passed"] += proof["passed"]
            n = max((p["n"] for p in self.data["points"]), default=0) + 1
            self._keep(commit, n)
            old = cur["commit"] if cur else ""
            self._move(commit)
            point = {"n": n, "commit": commit, "at": _now(), "kind": "change", "why": why or self._subject(commit),
                     "by": by, "checked": {"passed": checked["passed"], "seconds": checked.get("seconds")},
                     "before": cur["n"] if cur else None}
            self.data["points"].append(point)
            self.data["current"] = n
            self.data["notice"] = None
            who = self._restart(old, commit)
            self._event("change", f"Undo point {n}: {point['why'][:200]} ({commit[:12]}), checked "
                                  f"({checked['passed']} checks passed). {', '.join(who).capitalize()} start again on it.",
                        point=n)
            self._save()
            return {"ok": True, "point": point, "restarts": who}

    def _subject(self, commit: str) -> str:
        return _git("log", "-1", "--format=%s", commit, cwd=self.code).stdout.strip()[:300]

    def _default_check(self, commit: str) -> dict:
        from . import checks

        return checks.run(self.code, commit, say=lambda s: log.info("%s", s))

    async def undo(self, n, *, by: str = "the Rouh", kind: str = "undo", said: str = "") -> dict:
        try:
            n = int(n)
        except (TypeError, ValueError):
            return {"ok": False, "refused": "name an undo point by its number"}
        async with self.lock:
            p = self.point(n)
            if p is None:
                return {"ok": False, "refused": f"there is no undo point {n}"}
            cur = self.point(self.data.get("current"))
            if cur and cur["n"] == n and self.head() == p["commit"]:
                return {"ok": True, "point": p, "said": "That is the code that runs already."}
            if not self.clean():
                kept = self._set_aside("set-aside")
                self._event("set-aside", f"Work not committed in /code was kept on {kept}.")
            old = self.head()
            self._move(p["commit"])
            self.data["current"] = n
            p["live"] = _now()
            who = self._restart(old, p["commit"])
            text = said or f"Put back to undo point {n} ({p['commit'][:12]}), by {by}."
            self._event(kind, text, point=n, by=by, before=cur["n"] if cur else None)
            self.data["notice"] = None
            if kind == "doctor":
                self.data["notice"] = {"id": int(time.time()), "said": text, "point": n,
                                       "from": cur["n"] if cur else None}
            self._save()
            return {"ok": True, "point": p, "restarts": who, "said": text}

    async def verify(self, who: str) -> dict:
        """The start scripts ask before they run /code: is it the undo point that should run?"""
        cur = self.point(self.data.get("current"))
        head = self.head()
        if not head:
            return {"ok": False, "refused": "/code holds no commit"}
        if cur is None:
            await self.start()
            cur = self.point(self.data.get("current"))
        said = []
        if not self.clean():
            async with self.lock:
                kept = self._set_aside("set-aside")
                self._move(head)
                self._event("set-aside", f"Work not committed in /code when the {who or 'Rouh'} started was kept on {kept}.")
                self._save()
                said.append(f"Work not committed was kept on {kept}.")
        if cur and head != cur["commit"]:
            got = await self.propose(head, "", by=f"the {who or 'Rouh'}'s start: main was moved without the guard")
            said.append(got.get("refused") or f"The new commit {head[:12]} passed and is undo point {got['point']['n']}.")
        cur = self.point(self.data.get("current"))
        if cur is not None:
            # Which code each container really started on, and when: the doctor's clock starts here.
            self.data.setdefault("started", {})[who or "core"] = {"point": cur["n"], "at": _now()}
            self._save()
        return {"ok": True, "point": cur, "commit": cur["commit"] if cur else head, "said": " ".join(said)}

    def started(self, who: str, n: int) -> float | None:
        """When `who` started on undo point n since it last went live, or None if it has not yet:
        a core still stopping, or still migrating for the code before, has not run point n."""
        got = (self.data.get("started") or {}).get(who) or {}
        p = self.point(n)
        if p is None or got.get("point") != n:
            return None
        at = float(got.get("at") or 0)
        return at if at >= max(p["at"], float(p.get("live") or 0)) else None

    def doctor_target(self) -> dict | None:
        """The point the doctor would go back to: the one that ran before the current one."""
        cur = self.point(self.data.get("current"))
        if not cur or cur.get("kind") not in ("change",) or cur.get("doctored"):
            return None
        return self.point(cur.get("before"))

    def mark_doctored(self, n: int) -> None:
        p = self.point(n)
        if p is not None:
            p["doctored"] = _now()
            self._save()
