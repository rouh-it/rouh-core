"""The Creator Rouh's push: a checked change of its code put on rouh-core's main (task 161).

Part of the protected core (guard/README.md). Every Rouh instance stops at "restart": a change a
run proposes is checked, kept as an undo point and put live (``changes.py``), and nothing goes
anywhere. The Creator Rouh, the maker's own, is where Rouh's code is made, so for it alone
one setting adds what used to be land.sh's push:

    ROUH_GUARD_UPSTREAM   the repository a checked change is pushed to, such as
                          git@github.com:rouh-it/rouh-core.git. Blank, as in every Rouh instance:
                          all of this is off, and the guard behaves exactly as before.

With it on, the guard:

1. **holds the key.** One SSH key, made here (``rouh-guard upstream-key``) in the guard's own
   volume (/guard/upstream), which nothing but the guard mounts, so no run and not the Rouh itself
   can read it. Its public half is put on rouh-core as a deploy key with write access through
   GitHub's API, so it can write to that one repository and nothing else. The guard reaches
   GitHub only through the key proxy, as everything does: ``rouh-connect`` to ssh.github.com:443,
   whose host key is pinned below.
2. **pushes a change only once it has proved itself**: the change step's checks passed, its undo
   point is saved, Rouh has started again on it and answered its health page (the doctor's look)
   for ``SETTLE`` seconds after it went live, and the doctor has not put it back. Never forced: if
   rouh-core's main moved meanwhile, the change's own commits are fitted onto it and that goes
   through the change step again, checks and all, before it is pushed. A change that fails the
   checks never reaches GitHub, because it never becomes an undo point.
3. **follows rouh-core's main.** Every ``EVERY`` seconds it fetches main, the base tags and the
   base workflow's failure refs into /code as ``refs/upstream/...``: a run's landing fits its work
   onto them (bin/rouh-land, creator.merge-runs), and the nightly base fixes read them
   (rouh/base_patches.py). A main that moved on past the code that runs - a base level merged at
   GitHub - is proposed like any change, so the Creator Rouh runs it only once it passed here too.
4. **pushes a base level** for the 00:40 job (``push_branch``): only a branch ``base-patch/<level>``,
   only a commit on top of rouh-core's main that changes nothing but deploy/container/base/, and
   only after the change step's checks pass on it. GitHub builds, signs and merges it from there,
   as before; the signing key stays at GitHub.

Turning it off is removing the setting and deleting the deploy key at GitHub: the Creator Rouh is
then a plain Rouh instance.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import subprocess
import time
from pathlib import Path

log = logging.getLogger("rouh-guard")

EVERY = float(os.environ.get("ROUH_GUARD_UPSTREAM_EVERY", "60"))
#: How long Rouh must have answered its health page on a change before the change is pushed.
SETTLE = float(os.environ.get("ROUH_GUARD_UPSTREAM_SETTLE", "120"))
BRANCH = "main"
BASE_BRANCH = re.compile(r"^base-patch/\d{1,3}\.\d{1,3}\.\d{1,4}$")
BASE_PATHS = ("deploy/container/base/",)
#: GitHub's own host key for ssh.github.com:443 (and github.com), pinned: a key GitHub does not
#: publish is refused, not learnt.
GITHUB_HOST_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl"
CONNECT = "/opt/rouh-guard/bin/rouh-connect"
ROUH_UID = 10001


def _now() -> float:
    return round(time.time(), 1)


class Upstream:
    def __init__(self, changes, doctor=None, *, url: str | None = None, home: Path | None = None):
        self.changes = changes
        self.doctor = doctor
        self.url = (os.environ.get("ROUH_GUARD_UPSTREAM", "") if url is None else url).strip()
        self.home = home or (changes.state / "upstream")
        self.key = self.home / "key"
        self.lock = asyncio.Lock()
        self.connect = os.environ.get("ROUH_GUARD_CONNECT", CONNECT)

    # --- what is kept -----------------------------------------------------------------------

    @property
    def on(self) -> bool:
        return bool(self.url)

    @property
    def data(self) -> dict:
        return self.changes.data.setdefault("upstream", {"pushed": None, "events": [], "fetched": None})

    def _event(self, what: str, said: str, **more) -> None:
        ev = self.data.setdefault("events", [])
        ev.append({"at": _now(), "what": what, "said": said, **more})
        del ev[:-50]
        self.changes._event(f"upstream-{what}", said, **more)
        self.changes._save()

    def status(self) -> dict:
        if not self.on:
            return {"on": False}
        pub = self.key.with_suffix(".pub")
        # Ready once the key is made: until then this Rouh behaves as any Rouh instance.
        return {"on": True, "ready": self.key.is_file(), "url": self.url,
                "key": pub.read_text().strip() if pub.is_file() else None,
                "pushed": self.data.get("pushed"), "fetched": self.data.get("fetched"),
                "events": self.data.get("events", [])[-10:][::-1]}

    # --- the key and git ------------------------------------------------------------------------

    def make_key(self) -> str:
        """The deploy key's public half, made once; the private half never leaves /guard/upstream."""
        if not self.on:
            raise RuntimeError("ROUH_GUARD_UPSTREAM is not set, so this Rouh pushes nowhere")
        self.home.mkdir(parents=True, exist_ok=True)
        if not self.key.is_file():
            subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "rouh-guard-upstream",
                            "-f", str(self.key)], check=True, capture_output=True)
        self._files()
        return self.key.with_suffix(".pub").read_text().strip()

    def _files(self) -> None:
        """ssh's settings for the guard's git: the key, the pinned host key, the key proxy."""
        (self.home / "known_hosts").write_text(f"github.com {GITHUB_HOST_KEY}\n[ssh.github.com]:443 {GITHUB_HOST_KEY}\n")
        (self.home / "ssh_config").write_text(
            "Host github.com\n  HostName ssh.github.com\n  Port 443\n"
            "Host *\n"
            f"  IdentityFile {self.key}\n  IdentitiesOnly yes\n"
            f"  UserKnownHostsFile {self.home / 'known_hosts'}\n  StrictHostKeyChecking yes\n"
            f"  ProxyCommand {self.connect} %h %p\n  BatchMode yes\n  ConnectTimeout 30\n")
        if os.getuid() == 0:
            for p in [self.home, *self.home.iterdir()]:
                os.chown(p, ROUH_UID, ROUH_UID)
        os.chmod(self.home, 0o700)
        for p in self.home.iterdir():
            if p.is_file():
                os.chmod(p, 0o600 if p.name in ("key", "ssh_config", "known_hosts") else 0o644)

    def git(self, *args: str, timeout: float = 600) -> subprocess.CompletedProcess:
        """git in /code, as Rouh's user (the owner of /code and of the key), reaching out only
        through the key proxy: ssh by rouh-connect, git:// by the same, https by HTTPS_PROXY."""
        from .changes import ROUH, SAFE

        if self.home.is_dir():
            self._files()
        pre = ROUH if os.getuid() == 0 else []
        env = {**os.environ, **SAFE, "GIT_TERMINAL_PROMPT": "0", "HOME": "/tmp",
               "GIT_SSH_COMMAND": f"ssh -F {self.home / 'ssh_config'}", "GIT_PROXY_COMMAND": self.connect}
        try:
            return subprocess.run([*pre, "git", *args], cwd=str(self.changes.code), capture_output=True, text=True,
                                  env=env, timeout=timeout)
        except subprocess.TimeoutExpired:
            return subprocess.CompletedProcess(args, 124, "", f"git {args[0]} took longer than {int(timeout)} s")

    def ref(self, name: str) -> str:
        r = self.git("rev-parse", "--verify", "-q", f"{name}^{{commit}}", timeout=30)
        return r.stdout.strip() if r.returncode == 0 else ""

    def _ancestor(self, a: str, b: str) -> bool:
        return self.git("merge-base", "--is-ancestor", a, b, timeout=60).returncode == 0

    # --- fetching ---------------------------------------------------------------------------

    def fetch(self) -> dict:
        """rouh-core's main, base tags and base failures into /code under refs/upstream/."""
        r = self.git("fetch", "-q", "--prune", "--no-tags", self.url,
                     f"+refs/heads/{BRANCH}:refs/upstream/heads/{BRANCH}",
                     "+refs/tags/base-*:refs/upstream/tags/base-*",
                     "+refs/base-failed/*:refs/upstream/base-failed/*")
        if r.returncode:
            # A repository with no base tags or failures yet: main alone.
            r = self.git("fetch", "-q", "--no-tags", self.url, f"+refs/heads/{BRANCH}:refs/upstream/heads/{BRANCH}")
        if r.returncode:
            return {"ok": False, "error": f"rouh-core could not be fetched: {(r.stderr or r.stdout).strip()[-300:]}"}
        main = self.ref(f"refs/upstream/heads/{BRANCH}")
        self.data["fetched"] = {"at": _now(), "main": main}
        self.changes._save()
        return {"ok": True, "main": main}

    # --- pushing a change -------------------------------------------------------------------

    def _settled(self, point: dict, now: float) -> bool:
        """The change went live, Rouh answers on it, and the doctor has not put it back."""
        if point.get("kind") != "change" or point.get("doctored"):
            return False
        if now - point["at"] < SETTLE:
            return False
        d = self.doctor
        if d is None:
            return True
        return d.failing_since is None and d.last_ok is not None and d.last_ok >= point["at"] + SETTLE

    async def once(self, now: float | None = None) -> dict | None:
        """One look: fetch, follow a main that moved on, push a change that has settled."""
        if not self.on or not self.key.is_file():
            return None
        now = time.time() if now is None else now
        async with self.lock:
            got = await asyncio.to_thread(self.fetch)
            if not got["ok"]:
                if self.data.get("last_error") != got["error"]:
                    self.data["last_error"] = got["error"]
                    self._event("fetch-failed", got["error"])
                return got
            self.data.pop("last_error", None)
            up = got["main"]
            cur = self.changes.point(self.changes.data.get("current"))
            if cur is None or self.changes.busy or self.changes.data.get("pending"):
                return None
            here = cur["commit"]
            seen, self.data["seen"] = self.data.get("seen"), up
            self.changes._save()
            if up == here or self._ancestor(here, up):
                # rouh-core's main moved on past what runs (a base level merged at GitHub, or a push
                # from elsewhere): it runs here only once it passed here too. Only when main itself
                # moved: an undo point a person or the doctor put back stays put.
                if up == here or up == seen:
                    return None
                res = await self.changes.propose(up, "rouh-core's main moved on", by="rouh-core's main")
                if res.get("ok"):
                    self._event("followed", f"rouh-core's main {up[:12]} passed here and runs as undo point "
                                            f"{res['point']['n']}.", commit=up)
                else:
                    self._event("follow-refused", f"rouh-core's main {up[:12]} did not pass here, so it does not "
                                                  f"run: {res.get('refused') or res.get('error')}", commit=up)
                return res
            if not self._settled(cur, now):
                return None
            if self._ancestor(up, here):
                return await asyncio.to_thread(self._push, cur)
            return await self._fit(cur, up)

    def _push(self, point: dict) -> dict:
        commit = point["commit"]
        r = self.git("push", "-q", self.url, f"{commit}:refs/heads/{BRANCH}")
        if r.returncode:
            why = (r.stderr or r.stdout).strip()[-300:]
            if self.data.get("last_error") != why:
                self.data["last_error"] = why
                self._event("push-failed", f"Undo point {point['n']} ({commit[:12]}) could not be pushed to rouh-core's "
                                           f"main; it is tried again: {why}", commit=commit)
            return {"ok": False, "error": why}
        self.git("update-ref", f"refs/upstream/heads/{BRANCH}", commit, timeout=30)
        self.data["seen"] = commit
        self.data["pushed"] = {"commit": commit, "at": _now(), "point": point["n"]}
        self.data.pop("last_error", None)
        self._event("pushed", f"Undo point {point['n']} ({commit[:12]}) passed its checks, ran healthy for "
                              f"{int(SETTLE)} s, and is on rouh-core's main.", commit=commit, point=point["n"])
        return {"ok": True, "pushed": commit}

    async def _fit(self, point: dict, up: str) -> dict:
        """rouh-core's main moved while the change was checked: its own commits onto main, checked again."""
        if self.data.get("fitting") == point["commit"]:
            return {"ok": False, "refused": "this change was already fitted once and did not take"}
        self.data["fitting"] = point["commit"]
        self.changes._save()
        fitted = await asyncio.to_thread(self._rebase, point["commit"], up)
        if not fitted.get("ok"):
            self._event("fit-failed", f"rouh-core's main moved on and undo point {point['n']} does not fit onto it "
                                      f"by itself ({fitted.get('why')}); the next run's landing fits it.",
                        commit=point["commit"])
            return fitted
        res = await self.changes.propose(fitted["commit"], f"{point['why'][:200]} (fitted onto rouh-core's main)",
                                         by="the protected core, fitting it onto rouh-core's main")
        if res.get("ok"):
            self._event("fitted", f"Undo point {point['n']} was fitted onto rouh-core's main as undo point "
                                  f"{res['point']['n']}; it is pushed once it has run healthy.", commit=fitted["commit"])
        return res

    def _rebase(self, commit: str, onto: str) -> dict:
        """The commits of `commit` that `onto` lacks, replayed onto it in a worktree of their own."""
        base = self.git("merge-base", commit, onto, timeout=60).stdout.strip()
        if not base:
            return {"ok": False, "why": "it shares no history with rouh-core's main"}
        tree = Path("/tmp") / f"fit-{int(time.time())}"
        r = self.git("worktree", "add", "-q", "--detach", str(tree), commit)
        if r.returncode:
            return {"ok": False, "why": r.stderr.strip()[-200:]}
        try:
            from .changes import ROUH, SAFE

            pre = ROUH if os.getuid() == 0 else []
            env = {**os.environ, **SAFE, "GIT_TERMINAL_PROMPT": "0", "HOME": "/tmp", "GIT_EDITOR": "true"}
            rb = subprocess.run([*pre, "git", "-c", "user.name=Rouh", "-c", "user.email=rouh@localhost", "rebase", "-q",
                                 "--empty=drop", "--onto", onto, base], cwd=str(tree), capture_output=True, text=True,
                                env=env, timeout=600)
            if rb.returncode:
                subprocess.run([*pre, "git", "rebase", "--abort"], cwd=str(tree), capture_output=True, env=env)
                return {"ok": False, "why": "its commits collide with what landed there"}
            head = subprocess.run([*pre, "git", "rev-parse", "HEAD"], cwd=str(tree), capture_output=True, text=True,
                                  env=env).stdout.strip()
            self.git("update-ref", f"refs/fitted/{head[:12]}", head, timeout=30)
            return {"ok": True, "commit": head}
        finally:
            self.git("worktree", "remove", "--force", str(tree), timeout=60)

    # --- the 00:40 base level -----------------------------------------------------------------

    async def push_branch(self, commit: str, branch: str, why: str = "") -> dict:
        if not self.on:
            return {"ok": False, "refused": "this Rouh pushes nowhere (ROUH_GUARD_UPSTREAM is not set)"}
        if not BASE_BRANCH.match(branch or ""):
            return {"ok": False, "refused": f"only a branch base-patch/<level> is pushed, not {str(branch)[:60]!r}"}
        sha = self.changes.resolve(commit)
        if not sha:
            return {"ok": False, "refused": f"/code has no commit {str(commit)[:40]!r}"}
        async with self.lock:
            got = await asyncio.to_thread(self.fetch)
            if not got["ok"]:
                return got
            up = got["main"]
            if not self._ancestor(up, sha):
                return {"ok": False, "refused": "a base level is pushed only on top of rouh-core's main as it is now"}
            files = self.git("diff", "--name-only", up, sha, timeout=60).stdout.split()
            other = [f for f in files if not f.startswith(BASE_PATHS)]
            if not files or other:
                return {"ok": False, "refused": "a base level changes deploy/container/base/ and nothing else"
                                                + (f"; this changes {', '.join(other[:5])}" if other else "")}
            self.changes.busy = f"checking base level {branch}"
            try:
                checked = await asyncio.to_thread(self.changes._check or self.changes._default_check, sha)
            finally:
                self.changes.busy = ""
            if not checked["ok"]:
                names = "; ".join(f"{f['name']}: {f['why']}"[:200] for f in checked["failed"][:4])
                self._event("base-refused", f"{branch} ({sha[:12]}) did not pass the checks here, so it is not pushed: "
                                            f"{names}", commit=sha)
                return {"ok": False, "refused": f"it did not pass its checks: {names}", "failed": checked["failed"]}
            level = branch.split("/", 1)[1]
            self.git("push", "-q", self.url, f":refs/base-failed/{level}")
            r = self.git("push", "-q", "--force", self.url, f"{sha}:refs/heads/{branch}")
            if r.returncode:
                why = (r.stderr or r.stdout).strip()[-300:]
                self._event("base-push-failed", f"{branch} could not be pushed: {why}", commit=sha)
                return {"ok": False, "error": why}
            self._event("base-pushed", f"{branch} ({sha[:12]}) passed its checks here and is pushed; GitHub builds, "
                                       f"checks and publishes it.", commit=sha)
            return {"ok": True, "pushed": sha, "branch": branch, "checked": checked.get("passed")}

    async def watch(self) -> None:
        while True:
            try:
                await self.once()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - one bad look never stops the watch
                log.exception("the look at rouh-core stumbled; it looks again")
            await asyncio.sleep(EVERY)
