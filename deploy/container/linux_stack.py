#!/usr/bin/env python3
"""Rouh on a Linux machine: a signed release from rouh.land, checked, and put in place by one command.

What Rouh for Mac's updater does by itself (StackUpdater, in rouh-it/rouh-mac), for a Linux machine
the person looks after (task 158). Until 29 October 2026 that was steps 4, 6 and 7 of
INSTALL-LINUX-VM.md done by hand, and nothing stopped a stack that failed its check from starting.

    linux_stack.py update [--dir DIR] [--release FILE]   the newest release of this Rouh's line
    linux_stack.py apply  [--dir DIR]                    the Rouh's own stack file again, after its check
    linux_stack.py back   [--dir DIR]                    the release before, on the images kept for it
    linux_stack.py status [--dir DIR]
    linux_stack.py restore [NAME] [--dir DIR]           a nightly copy of the database put back (the newest)
    linux_stack.py import BUNDLE [--dir DIR] [--release FILE]
                                                       an existing Rouh brought into a fresh stack

An update, in this order; nothing is started before the last step, and a failure anywhere before
it changes nothing:

1. the release: rouh.land's newest of this Rouh's line (or --release FILE), its signature checked with
   the public key in mac_release.py beside this, then its shape (mac_release.check_release). One
   that is not newer than the release in use, or that failed here before, changes nothing;
2. its images pulled, beside the ones that run;
3. the database saved (pg_dump into DIR/backups, the two newest kept), when a release is in use and
   its stack runs PostgreSQL;
4. the new base checked with this Rouh's own code and the release's own protected core (its
   check-base.sh, read out of the release's guard image), when the Rouh has code already;
5. the stack chosen: the Rouh's own stack folder, read out of its code volume, resolved by this
   machine's Compose sealed in a container that sees only that folder and the two settings files
   (so no file of the machine can be folded into it), and held to the release's own allow-list by
   the protected core's own check (stackpolicy.py), run out of the release's guard image, pinned by
   digest, with no network. Refused, the last of its own that passed; else the release's own;
6. that stack started, and every part waited for; not healthy, the release before and its stack
   are put back and started again.

The check runs out of the release's guard image, not out of this checkout or the Rouh's /code:
the Rouh can change its /code, and this checkout may be newer or older than the release, so the
only check that is surely the release's own is the one in the image its signature names.

DIR (~/rouh by default) holds the person's settings file, .env (INSTALL-LINUX-VM.md, step 5), which
this never writes, and what this keeps: releases/ (current.json, previous.json, failed.json, each
checked again whenever it is read), stack/ (release.env, the release's reference.yml and policy,
the Rouh's own stack folder as last read and the last of it that passed, stack.json - the stack
in use, resolved, with the settings in it, so only its owner may read it - and applied.json, where
it came from and what was refused) and backups/.

Needs Python 3.12, openssl 3 and Docker with Compose; standard library only. Run it from a checkout
of rouh-core at the commit of a release, never from a main nobody checked: this file and
mac_release.py decide which releases are trusted.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mac_release  # noqa: E402

# The bundle an existing Rouh is exported as (rouh/bundle.py, standard library only), read from
# the checkout this runs from.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from rouh import bundle as rouh_bundle  # noqa: E402

#: How many jobs pg_restore runs at once when an existing Rouh is brought in.
IMPORT_JOBS = max(1, int(os.environ.get("ROUH_IMPORT_JOBS", "4") or 4))
#: The stack's name, its containers' and volumes' prefix: "rouh", unless ROUH_STACK_PROJECT names a
#: second stack on the same machine (the Creator Rouh's rehearsal beside the real one, task 161).
PROJECT = os.environ.get("ROUH_STACK_PROJECT", "rouh")
if not re.fullmatch(r"[a-z][a-z0-9]{0,30}", PROJECT):
    raise SystemExit(f"ROUH_STACK_PROJECT must be a short name of small letters and digits, not {PROJECT!r}")
CODE_VOLUME, EXTRA_VOLUME = f"{PROJECT}_code", f"{PROJECT}_extra"
#: What must run healthy, of those the stack has (Rouh for Mac's StackFiles.guardedServices), and
#: the parts that run once on each start and exit (StackFiles.oneShots).
WATCHED = ("core", "keyproxy", "guard", "worker", "checkdb", "postgres")
ONE_SHOTS = ("worker-perms", "guard-init", "code-install")
HEALTH_TIMEOUT = float(os.environ.get("ROUH_HEALTH_TIMEOUT", "600"))
LOOK_EVERY = float(os.environ.get("ROUH_LOOK_EVERY", "10"))
#: The Compose that resolves the Rouh's own stack file sees only these of this shell's settings,
#: so a ${VARIABLE} in it cannot take anything else of the person's environment into a container.
#: The most of the Rouh's own stack folder read out of its code volume.
MAX_OWN_STACK = 50 * 1024 * 1024
CLEAN_ENV = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "XDG_RUNTIME_DIR", "DOCKER_HOST", "DOCKER_CONFIG", "DOCKER_CONTEXT")}


class Stop(Exception):
    """Nothing changed, for this reason."""


def say(line: str) -> None:
    print(line, flush=True)


def run(args: list[str], *, input: bytes | None = None, timeout: float = 1800, check: bool = False) -> subprocess.CompletedProcess:
    r = subprocess.run(args, input=input, capture_output=True, timeout=timeout, env=CLEAN_ENV)
    if check and r.returncode:
        raise Stop(f"{' '.join(args[:3])} failed: {(r.stderr or r.stdout).decode(errors='replace').strip()[-400:]}")
    return r


class Machine:
    def __init__(self, root: Path):
        self.root = root
        self.settings = root / ".env"
        self.releases = root / "releases"
        self.stack = root / "stack"
        self.backups = root / "backups"
        for d in (self.releases, self.stack, self.backups):
            d.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(root, 0o700)
        self.release_env = self.stack / "release.env"
        self.reference = self.stack / "reference.yml"
        self.policy = self.stack / "stack-policy.json"
        self.own, self.own_good = self.stack / "own", self.stack / "own-good"
        self.stack_file = self.stack / "stack.json"
        self.applied = self.stack / "applied.json"
        self._user: str | None = None

    # ------------------------------------------------------------ releases on disk

    def read_release(self, name: str) -> tuple[dict, bytes] | None:
        """A release kept here, checked again: a file changed on disk is trusted no more than the network."""
        f = self.releases / name
        if not f.exists():
            return None
        data = f.read_bytes()
        try:
            return mac_release.check_release(json.loads(data)), data
        except (ValueError, KeyError, json.JSONDecodeError) as e:
            raise Stop(f"releases/{name} is not a release this trusts ({e}); nothing changed")

    def failed(self) -> list[int]:
        f = self.releases / "failed.json"
        return json.loads(f.read_text()) if f.exists() else []

    def mark_failed(self, version: int) -> None:
        (self.releases / "failed.json").write_text(json.dumps(sorted(set(self.failed()) | {version})) + "\n")

    def make_current(self, data: bytes) -> None:
        cur = self.releases / "current.json"
        if cur.exists():
            (self.releases / "previous.json").write_bytes(cur.read_bytes())
        cur.write_bytes(data)

    # ------------------------------------------------------------ Compose

    def compose(self, file: Path, *args: str, env: Path | None = None) -> list[str]:
        return ["docker", "compose", "--project-name", PROJECT, "-f", str(file),
                "--env-file", str(self.settings), "--env-file", str(env or self.release_env), *args]

    @staticmethod
    def release_env_text(r: dict, settings: Path) -> str:
        """release.env, as Rouh for Mac writes it (StackUpdater.releaseEnv)."""
        i = r["images"]
        lines = [f"# Made by linux_stack.py from the signed release {r['version']} (base {r['level']}). Never edited by hand.",
                 f"ROUH_BASE_IMAGE={i['base']}", f"ROUH_GUARD_IMAGE={i['guard']}", f"ROUH_POSTGRES_IMAGE={i['postgres']}",
                 f"ROUH_SETTINGS_FILE={settings}"]
        if (r.get("code") or {}).get("commit"):
            lines.append(f"ROUH_RELEASE_COMMIT={r['code']['commit']}")
        return "\n".join(lines) + "\n"

    def resolve(self, file: Path, env: Path | None = None) -> tuple[dict | None, str]:
        """The release's own stack file, which its signature vouches for, resolved here. With
        --no-env-resolution, as Rouh for Mac resolves, so an env_file stays visible to the check."""
        r = run(self.compose(file, "config", "--format", "json", "--no-env-resolution", env=env), timeout=120)
        return _resolved(r)

    def user(self) -> str:
        """Who a sealed container runs as to read this user's files: this user, or, with rootless
        Docker, which maps the container's root to this user, root."""
        if self._user is None:
            info = run(["docker", "info", "--format", "{{.SecurityOptions}}"], timeout=30).stdout.decode(errors="replace")
            self._user = "0:0" if "rootless" in info else f"{os.getuid()}:{os.getgid()}"
        return self._user

    def resolve_sealed(self, folder: Path, base: str) -> tuple[dict | None, str]:
        """The Rouh's own stack file, resolved by this machine's own Compose inside a sealed container
        on the release's base: no network, nothing written, and nothing of the machine to read but
        the stack's own folder and the two settings files, each at its own path. Compose reads any
        file a stack file names while it resolves (env_file, label_file, include, extends) and folds
        it in; here a file of the machine is simply not there, so such a stack cannot be resolved
        and is refused, and its contents never reach the resolved file (task 158).

        Returns (None, why) for a stack file that cannot be resolved; Stop when the sealed Compose
        cannot run at all, so a Docker that misbehaves never swaps the Rouh's stack."""
        plugin = run(["docker", "info", "--format",
                      '{{range .ClientInfo.Plugins}}{{if eq .Name "compose"}}{{.Path}}{{end}}{{end}}'], timeout=30)
        binary = plugin.stdout.decode(errors="replace").strip()
        if plugin.returncode or not binary.startswith("/"):
            raise Stop("this machine's Docker Compose could not be found to resolve Rouh's own stack file; nothing changed")
        seal = ["docker", "run", "--rm", "-i", "--network", "none", "--read-only", "--cap-drop", "ALL",
                "--security-opt", "no-new-privileges:true", "--user", self.user(), "--tmpfs", "/tmp", "-e", "HOME=/tmp",
                "-v", f"{binary}:/opt/compose:ro", "-v", f"{folder}:{folder}:ro",
                "-v", f"{self.settings}:{self.settings}:ro", "-v", f"{self.release_env}:{self.release_env}:ro",
                # With an empty environment: the base image sets ROUH_PORT and forty other settings for
                # the core, and Compose takes the environment before the settings file, so a Rouh's own
                # ROUH_PORT was read as the image's 8021 (the Creator Rouh's rehearsal, task 161).
                "--entrypoint", "/usr/bin/env", base, "-i", "HOME=/tmp", "/opt/compose"]
        works = run(seal + ["version"], timeout=60)
        if works.returncode:
            raise Stop("this machine's Docker Compose could not run sealed on the release's base "
                       f"({(works.stderr or works.stdout).decode(errors='replace').strip()[-200:]}); nothing changed")
        r = run(seal + ["--project-name", PROJECT, "-f", str(folder / "compose.yml"), "--env-file", str(self.settings),
                        "--env-file", str(self.release_env), "config", "--format", "json", "--no-env-resolution"], timeout=120)
        return _resolved(r)

    # ------------------------------------------------------------ the Rouh's own stack

    def read_own(self, base: str, into: Path) -> bool:
        """The Rouh's own stack folder, out of its code volume. False when it has none; Stop when it
        has one that could not be read, so a Docker that misbehaves never swaps the Rouh's stack.

        Unpacked by Python's tarfile with the "data" filter: the Rouh writes this volume, so a
        path out of the folder, a link or a device in the archive is refused, not followed."""
        _wipe(into)
        if run(["docker", "volume", "inspect", CODE_VOLUME], timeout=30).returncode:
            return False
        got = run(["docker", "run", "--rm", "--network", "none", "-v", f"{CODE_VOLUME}:/code:ro", "--entrypoint", "sh", base,
                   "-c", "[ -f /code/deploy/stack/compose.yml ] || exit 3; tar -C /code/deploy/stack -cf - ."], timeout=120)
        if got.returncode == 3:
            return False
        if got.returncode or not got.stdout:
            raise Stop(f"Rouh's own stack folder could not be read ({got.stderr.decode(errors='replace').strip()[-300:]}); nothing changed")
        if len(got.stdout) > MAX_OWN_STACK:
            raise Stop(f"Rouh's own stack folder is over {MAX_OWN_STACK // 2**20} MB, which no stack folder needs; nothing changed")
        into.mkdir(parents=True, mode=0o700)
        try:
            with tarfile.open(fileobj=io.BytesIO(got.stdout)) as t:
                t.extractall(into, filter="data")
        except (tarfile.TarError, OSError) as e:
            say(f"The Rouh's own stack folder could not be unpacked ({e}); it is taken as refused")
            _wipe(into)
            return True
        return True

    def policy_check(self, guard: str, own: Path, resolved: dict, reference: dict) -> list[str]:
        """The protected core's own check, out of the release's guard image, against the release's
        allow-list: every refusal in a sentence, none when it may be applied. A check that could not
        run, or answered anything else, is a Stop: nothing changes, rather than the Rouh's own stack
        being swapped for the release's because of a Docker that misbehaved."""
        work = self.stack / "check"
        _wipe(work)
        work.mkdir(mode=0o700)
        (work / "own.json").write_text(json.dumps(resolved))
        (work / "reference.json").write_text(json.dumps(reference))
        (work / "stack-policy.json").write_text(self.policy.read_text())
        # Only what the check reads is mounted, read-only: these three, and the stack folder at its
        # own path, so a build's context in the resolved file names the same folder inside and out.
        # Rootless Docker maps the container's root to this user; elsewhere this user's own id reads them.
        user = self.user()
        try:
            r = run(["docker", "run", "--rm", "--network", "none", "--read-only", "--cap-drop", "ALL",
                     "--security-opt", "no-new-privileges:true", "--user", user,
                     "-v", f"{work}:{work}:ro", "-v", f"{own}:{own}:ro", "--entrypoint", "python", guard,
                     "-I", "/opt/rouh-guard/rouh_guard/stackpolicy.py", "check",
                     "--stack", str(own), "--reference", str(work / "reference.json"),
                     "--resolved", str(work / "own.json"), "--resolved-reference", str(work / "reference.json"),
                     "--policy", str(work / "stack-policy.json")], timeout=120)
        finally:
            _wipe(work)
        out = r.stdout.decode(errors="replace")
        refused = [line[len("refused: "):] for line in out.splitlines() if line.startswith("refused: ")]
        if r.returncode == 0 and "The stack file may be applied." in out:
            return []
        if r.returncode == 1 and refused:
            return refused
        raise Stop(f"the stack check could not run ({(r.stderr or r.stdout).decode(errors='replace').strip()[-300:]}); nothing changed")

    def prepare(self, r: dict) -> dict:
        """Chooses the stack for release r, the way Rouh for Mac's prepareStack does, and writes it as
        stack.json with r's release.env, reference and policy. Starts nothing."""
        self.release_env.write_text(self.release_env_text(r, self.settings))
        self.reference.write_text(r["compose"])
        self.policy.write_text(r["policy"])
        ref, why = self.resolve(self.reference)
        if ref is None:
            raise Stop(f"the release's own stack file: {why}")
        guard, base = r["images"]["guard"], r["images"]["base"]
        refused: list[str] = []
        chosen = None
        if self.read_own(base, self.own):
            own, why = self.resolve_sealed(self.own, base) if (self.own / "compose.yml").is_file() else (None, "it has no compose.yml")
            if own is None:
                refused = [f"Rouh's own stack file could not be read. {why}"]
            else:
                refused = self.policy_check(guard, self.own, own, ref)
                if not refused:
                    chosen = ("own", own)
                    _wipe(self.own_good)
                    _copy(self.own, self.own_good)
        if chosen is None and (self.own_good / "compose.yml").is_file():
            good, _ = self.resolve_sealed(self.own_good, base)
            if good is not None and not self.policy_check(guard, self.own_good, good, ref):
                chosen = ("last-good", good)
        source, stack = chosen or ("release", ref)
        self.stack_file.write_text(json.dumps(stack, indent=1))
        os.chmod(self.stack_file, 0o600)
        applied = {"source": source, "release": r["version"], "refused": refused, "at": int(time.time())}
        self.applied.write_text(json.dumps(applied, indent=1) + "\n")
        for line in refused:
            say(f"refused: {line}")
        say({"own": "The stack in use is Rouh's own.",
             "last-good": "Rouh's own stack file was refused; the last of its own that passed is used.",
             "release": "The stack in use is the release's own" + (", because Rouh's own was refused." if refused else ".")}[source])
        return applied

    # ------------------------------------------------------------ starting, and waiting

    def up(self) -> None:
        r = run(self.compose(self.stack_file, "up", "--detach", "--remove-orphans"), timeout=1800)
        if r.returncode:
            # Said, not swallowed: a part Compose would not start is the reason the wait that
            # follows ends unhealthy (the Creator Rouh's rehearsal, task 161).
            say("Compose did not start every part: "
                + (r.stderr or r.stdout).decode(errors="replace").strip().splitlines()[-1][-300:])

    def healthy(self) -> bool:
        stack = json.loads(self.stack_file.read_text())
        watched = [s for s in WATCHED if s in (stack.get("services") or {})]
        end = time.monotonic() + HEALTH_TIMEOUT
        while True:
            seen = _ps(run(self.compose(self.stack_file, "ps", "--all", "--format", "json"), timeout=60).stdout)
            if any(s in seen and seen[s].get("State") == "exited" and int(seen[s].get("ExitCode") or 0) != 0 for s in ONE_SHOTS):
                return False
            if all(seen.get(s, {}).get("State") == "running" and seen[s].get("Health") == "healthy" for s in watched):
                return True
            if time.monotonic() >= end:
                return False
            time.sleep(LOOK_EVERY)

    def keep(self) -> dict:
        """What prepare changes, kept to put back: the files, and the own stack folders a kept
        stack.json may build from."""
        kept = {f: f.read_bytes() if f.exists() else None for f in (self.stack_file, self.release_env, self.applied,
                                                                     self.reference, self.policy)}
        for d in (self.own, self.own_good):
            k = self.stack / f".kept-{d.name}"
            _wipe(k)
            if d.is_dir():
                _copy(d, k)
            kept[d] = k if d.is_dir() else None
        return kept

    def put_back(self, kept: dict) -> None:
        for f, data in kept.items():
            if isinstance(data, Path):
                _wipe(f)
                data.rename(f)
            elif data is None:
                _wipe(f) if f.is_dir() else f.unlink(missing_ok=True)
            else:
                f.write_bytes(data)

    def drop(self, kept: dict) -> None:
        for data in kept.values():
            if isinstance(data, Path):
                _wipe(data)

    # ------------------------------------------------------------ the database

    def backup(self, level: str) -> Path | None:
        """The database, saved before a switch. Found by Compose's own labels rather than by a stack
        file, so a machine set up by hand, which has none of this tool's yet, is saved too."""
        found = run(["docker", "ps", "-q", "--filter", f"label=com.docker.compose.project={PROJECT}",
                     "--filter", "label=com.docker.compose.service=postgres"], timeout=30).stdout.decode().split()
        if not found:
            stack = json.loads(self.stack_file.read_text()) if self.stack_file.exists() else None
            if stack is not None and "postgres" not in (stack.get("services") or {}):
                say("No PostgreSQL in the stack in use: no database to save. Its data volumes are kept as they are.")
                return None
            raise Stop("Rouh's database is not running, so it could not be saved first; start Rouh, then update again. Nothing changed")
        box = found[0]
        out = self.backups / f"{time.strftime('%Y%m%d-%H%M%S', time.gmtime())}-{level}.dump"
        inside = "/tmp/rouh-backup.dump"
        dump = run(["docker", "exec", box, "pg_dump", "-U", "rouh", "-d", "rouh", "-Fc", "-f", inside], timeout=3600)
        cp = run(["docker", "cp", f"{box}:{inside}", str(out)], timeout=3600) if not dump.returncode else dump
        run(["docker", "exec", box, "rm", "-f", inside], timeout=60)
        if cp.returncode or not out.is_file():
            out.unlink(missing_ok=True)
            raise Stop(f"Rouh's database could not be saved first ({(cp.stderr or cp.stdout).decode(errors='replace').strip()[-300:]}); nothing changed")
        os.chmod(out, 0o600)
        for old in sorted(p for p in self.backups.iterdir() if not p.name.startswith("."))[:-2]:
            old.unlink()
        say(f"Saved Rouh's database to {out}")
        return out

    def code_check(self, r: dict) -> None:
        if run(["docker", "volume", "inspect", CODE_VOLUME], timeout=30).returncode:
            say("No code yet: nothing to check the new base with.")
            return
        i = r["images"]
        got = run(["docker", "run", "--rm", "--network", "none", "--entrypoint", "cat", i["guard"],
                   "/opt/rouh-guard/bin/check-base.sh"], timeout=120, check=True)
        script = self.stack / "check-base.sh"
        script.write_bytes(got.stdout)
        args = ["bash", str(script), "--base", i["base"], "--guard", i["guard"], "--code-volume", CODE_VOLUME,
                "--postgres", i["postgres"], "--name", "rouh-check"]
        if not run(["docker", "volume", "inspect", EXTRA_VOLUME], timeout=30).returncode:
            args += ["--extra-volume", EXTRA_VOLUME]
        c = run(args, timeout=3600)
        script.unlink(missing_ok=True)
        last = [line for line in c.stdout.decode(errors="replace").splitlines() if line.startswith("ROUH-CHECK ")]
        if not last:
            raise Stop(f"the check of base {r['level']} could not run ({(c.stderr or c.stdout).decode(errors='replace').strip()[-300:]}); "
                       "nothing changed, and it is tried again next time")
        if c.returncode:
            self.mark_failed(r["version"])
            raise Stop(f"base {r['level']} did not pass this Rouh's own checks, so nothing changed: {last[-1][:600]}")
        say(f"Base {r['level']} passed this Rouh's own checks")


# ---------------------------------------------------------------- the commands


def switch(m: Machine, r: dict, *, going_back: str) -> bool:
    """Puts release r's stack in place and starts it. Healthy: True, and what was kept is dropped.
    Not healthy, or anything going wrong on the way, even an interruption: what was there before is
    put back and started again, and False (or the error) comes back. going_back names what runs then."""
    kept = m.keep()
    started = False
    try:
        m.prepare(r)
        started = True
        m.up()
        if m.healthy():
            m.drop(kept)
            return True
    except BaseException:
        m.put_back(kept)
        if started:
            say(f"Stopped part way; {going_back} is started again")
            m.up()
        raise
    m.put_back(kept)
    m.up()
    say(f"Not healthy within {int(HEALTH_TIMEOUT // 60)} minutes; {going_back} runs again: "
        + ("every part is healthy" if m.healthy() else "not every part is healthy"))
    return False


def newest_release(release_file: str | None, line: str) -> tuple[dict, bytes]:
    """rouh.land's newest release of the line (or the file given), its signature and shape checked."""
    if release_file:
        data = Path(release_file).read_bytes()
    else:
        try:
            data = json.dumps(mac_release._get(f"/mac/release/{line}.json")).encode()
        except mac_release.FetchError as e:
            raise Stop(f"refused: rouh.land did not hand out the newest release: {e}; nothing changed")
    try:
        new = mac_release.check_release(json.loads(data))
    except (ValueError, KeyError, json.JSONDecodeError) as e:
        raise Stop(f"refused: the release is not one this trusts ({e}); nothing changed")
    if new.get("channel") != mac_release.CHANNEL:
        raise Stop(f"refused: a release of the channel {new.get('channel')!r}, not {mac_release.CHANNEL!r}; nothing changed")
    return new, data


def update(m: Machine, release_file: str | None) -> int:
    cur = m.read_release("current.json")
    if cur is None and (m.root / "release.json").exists():
        # A machine set up by hand (INSTALL-LINUX-VM.md before this): its release, if it is one, is the one in use.
        data = (m.root / "release.json").read_bytes()
        try:
            cur = mac_release.check_release(json.loads(data)), data
            say(f"Taken as the release in use: release.json, base {cur[0]['level']}")
        except (ValueError, KeyError, json.JSONDecodeError):
            cur = None
    new, data = newest_release(release_file, cur[0]["line"] if cur else mac_release.CHANNEL)
    if cur and new["line"] != cur[0]["line"]:
        raise Stop(f"refused: a release of line {new['line']}, and this Rouh is on line {cur[0]['line']}; nothing changed")
    if cur and new["version"] <= cur[0]["version"]:
        say(f"Up to date: base {cur[0]['level']}, release {cur[0]['version']}")
        return 0
    if new["version"] in m.failed():
        raise Stop(f"release {new['version']} failed here before and is not tried again; nothing changed")
    say(f"Updating to base {new['level']}, release {new['version']}" + (f", from base {cur[0]['level']}" if cur else ""))

    next_env = m.stack / "release.next.env"
    next_env.write_text(m.release_env_text(new, m.settings))
    next_ref = m.stack / "reference.next.yml"
    next_ref.write_text(new["compose"])
    try:
        run(m.compose(next_ref, "pull", "--quiet", env=next_env), check=True)
    finally:
        next_env.unlink(missing_ok=True)
        next_ref.unlink(missing_ok=True)
    if cur:
        m.backup(new["level"])
    m.code_check(new)
    if not cur:
        # A first start: nothing to go back to, and its first start may take longer than the wait.
        m.prepare(new)
        m.up()
        m.make_current(data)
        well = m.healthy()
        if not well:
            # A first start fills the database and the worker's home, and a part can be refused
            # once while another is still on its way: started once more, and waited for again.
            say("Not every part is healthy yet: starting the stack once more")
            m.up()
            well = m.healthy()
        say(f"Started base {new['level']} (release {new['version']}): " + ("every part is healthy" if well else
            f"not every part is healthy after {int(HEALTH_TIMEOUT // 60)} minutes; `status` and Compose's logs say more"))
        return 0
    if not (m.releases / "current.json").exists():
        (m.releases / "current.json").write_bytes(cur[1])   # the hand-set-up machine's, so it becomes previous.json
    if switch(m, new, going_back=f"base {cur[0]['level']}"):
        m.make_current(data)
        say(f"Updated to base {new['level']} (release {new['version']}): every part is healthy")
        return 0
    m.mark_failed(new["version"])
    return 1


def apply(m: Machine) -> int:
    cur = m.read_release("current.json")
    if cur is None:
        raise Stop("no release in use yet: run update first")
    before = m.stack_file.read_bytes() if m.stack_file.exists() else None
    kept = m.keep()
    try:
        m.prepare(cur[0])
    except BaseException:
        m.put_back(kept)
        raise
    if before == m.stack_file.read_bytes():
        m.drop(kept)
        say("Nothing to start: the stack in use is the same.")
        return 0
    m.put_back(kept)
    if switch(m, cur[0], going_back="the stack before"):
        say("Applied: every part is healthy")
        return 0
    return 1


def back(m: Machine) -> int:
    cur, prev = m.read_release("current.json"), m.read_release("previous.json")
    if not cur or not prev:
        raise Stop("there is no release before this one to go back to")
    if prev[0]["version"] in m.failed():
        raise Stop(f"the release before, base {prev[0]['level']}, failed here; there is nothing to go back to")
    if switch(m, prev[0], going_back=f"base {cur[0]['level']}"):
        m.mark_failed(cur[0]["version"])
        (m.releases / "current.json").write_bytes(prev[1])
        (m.releases / "previous.json").write_bytes(cur[1])
        say(f"Back on base {prev[0]['level']}. Base {cur[0]['level']} is not taken again by itself.")
        return 0
    say(f"Base {prev[0]['level']} did not come up healthy, so Rouh stays on base {cur[0]['level']}")
    return 1


def status(m: Machine) -> int:
    cur = m.read_release("current.json")
    if not cur:
        say("No release in use yet.")
        return 0
    say(mac_release.describe_release(cur[0]))
    if m.applied.exists():
        a = json.loads(m.applied.read_text())
        say(f"  the stack in use: {a['source']}" + "".join(f"\n  refused: {x}" for x in a.get("refused") or []))
    return 0


def restore(m: Machine, name: str) -> int:
    """A nightly copy of the database put back: the core stopped, the copy restored by the backup
    part (guard/bin/rouh-backup restore), and the core started again."""
    if not m.stack_file.exists():
        raise Stop("no stack in use yet: run update first")
    stack = json.loads(m.stack_file.read_text())
    if "backup" not in (stack.get("services") or {}):
        raise Stop("the stack in use has no backup part, so it has no nightly copies to put back")
    run(m.compose(m.stack_file, "stop", "core"), timeout=300, check=True)
    try:
        r = run(m.compose(m.stack_file, "exec", "-T", "backup", "/opt/rouh-guard/bin/rouh-backup", "restore",
                          name or "newest"), timeout=3600)
        say((r.stdout + r.stderr).decode(errors="replace").strip()[-1200:])
    finally:
        run(m.compose(m.stack_file, "up", "--detach"), timeout=1800)
    if r.returncode:
        say("Nothing was put back; Rouh runs on as it was.")
        return 1
    say("Rouh is started again on the database as it was then: " + ("every part is healthy" if m.healthy() else
        "not every part is healthy yet; `status` and Compose's logs say more"))
    return 0


#: Run by the base image, as root in a box with no network, with the bundle on its stdin: the two
#: keys put where the core's start expects them, with the owner and mode it gives them
#: (guard/bin/rouh-core-entrypoint), and the data directory and the workspace into core-data, every
#: file given to rouh. Unpacked with tarfile's "data" filter, so nothing in a bundle can reach
#: outside the two folders; nothing of a key is ever printed.
PLACE = r"""
import os, sys, tarfile
TOP = sys.argv[1]
DATA, KEYS = "/data", "/keys"
DATA_DIR, WORKSPACE = DATA + "/rouh", DATA + "/workspace"
places = {TOP + "/data/": DATA_DIR, TOP + "/workspace/": WORKSPACE}
for d in (DATA, DATA_DIR, WORKSPACE):
    os.makedirs(d, exist_ok=True)
    os.chmod(d, 0o750)
os.chown(KEYS, 10001, 10002)
os.chmod(KEYS, 0o750)
counts = {"data": 0, "workspace": 0, "keys": 0, "links": 0}


# A task folder's `files`, Rouh's link into its file store (rouh/filestore.py), is a link to an
# absolute path, which tarfile's data filter refuses. One that points inside /data, where every
# stack keeps its store, is made again as it was; any other absolute link is left out, and
# counted. True when the member was dealt with here.
def store_link(m, root):
    if not (m.issym() and os.path.isabs(m.linkname)):
        return False
    name = os.path.normpath(m.name)
    target = os.path.normpath(m.linkname)
    if name.startswith("..") or os.path.isabs(name) or not target.startswith(DATA + "/"):
        counts["links"] += 1
        return True
    dest = os.path.join(root, name)
    parent = os.path.dirname(dest)
    os.makedirs(parent, exist_ok=True)
    real_root = os.path.realpath(root)
    if os.path.realpath(parent) != real_root and not os.path.realpath(parent).startswith(real_root + os.sep):
        counts["links"] += 1
        return True
    if os.path.islink(dest):
        os.unlink(dest)
    elif os.path.lexists(dest):
        counts["links"] += 1
        return True
    os.symlink(target, dest)
    counts["data" if root == DATA_DIR else "workspace"] += 1
    return True


def keep(path, src, mode):
    tmp = path + ".new"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as out:
        out.write(src.read().strip() + b"\n")
    os.chown(tmp, 10001, 10001)
    os.chmod(tmp, mode)
    os.replace(tmp, path)
    counts["keys"] += 1


with tarfile.open(fileobj=sys.stdin.buffer, mode="r|") as t:
    for m in t:
        if m.name == TOP + "/keys/encryption.key":
            keep(KEYS + "/encryption.key", t.extractfile(m), 0o400)
        elif m.name == TOP + "/keys/django-secret.key":
            keep(DATA_DIR + "/django-secret.key", t.extractfile(m), 0o600)
        else:
            for prefix, root in places.items():
                if m.name.startswith(prefix):
                    m.name = m.name[len(prefix):]
                    if m.islnk() and m.linkname.startswith(prefix):
                        m.linkname = m.linkname[len(prefix):]
                    if store_link(m, root):
                        break
                    t.extract(m, root, filter="data")
                    counts["data" if root == DATA_DIR else "workspace"] += 1
# The workspace's own remote, if it had one (GitHub, on a server), is kept under another name: in a
# stack, origin is the stack's own main, which the core's start makes from this workspace.
# Named by --git-dir, and with the search for a repository stopped at the volume, so git never
# looks above the workspace for one: a .git that is not a repository changes nothing at all.
if os.path.isdir(WORKSPACE + "/.git"):
    import subprocess
    env = {**os.environ, "GIT_CEILING_DIRECTORIES": DATA}
    git = ["git", "-c", "safe.directory=*", "--git-dir", WORKSPACE + "/.git", "--work-tree", WORKSPACE]
    real = subprocess.run(git + ["rev-parse", "--absolute-git-dir"], capture_output=True, text=True, env=env)
    if real.returncode == 0 and real.stdout.strip() == os.path.realpath(WORKSPACE + "/.git") and \
            subprocess.run(git + ["remote", "get-url", "origin"], capture_output=True, env=env).returncode == 0:
        subprocess.run(git + ["remote", "rename", "origin", "before-import"], capture_output=True, env=env)
for root in (DATA_DIR, WORKSPACE):
    for here, dirs, files in os.walk(root):
        for n in [here] + [os.path.join(here, x) for x in dirs + files]:
            os.lchown(n, 10001, 10001)
os.chown(DATA, 10001, 10001)
print("%(keys)d key(s), %(data)d entries of the data directory and %(workspace)d of the workspace" % counts
      + (", %(links)d link(s) to elsewhere left out" % counts if counts["links"] else ""))
"""


def import_bundle(path: Path, compose: list[str], project: str, base: str, *, wait: float = 300) -> dict:
    """An existing Rouh's bundle (rouh/bundle.py) put into a fresh stack before its first start: its
    database restored into the stack's PostgreSQL, its encryption key into the keys volume as
    encryption.key, its Django key, data directory and workspace into core-data. compose is the
    stack's own Compose command (its files and settings files), project its name, base the
    release's base image. PostgreSQL runs only while the database is put in; nothing else starts."""
    try:
        about = rouh_bundle.read_about(str(path))
        say(f"The bundle is {rouh_bundle.describe(about)}.")
        rouh_bundle.check_dump(str(path), about)
    except rouh_bundle.NotABundle as e:
        raise Stop(f"{path} cannot be brought in: {e}; nothing changed")
    if not about.get("encryption_key"):
        say("It holds no encryption key: the Rouh it came from had sealed nothing, or kept its key elsewhere. "
            "Anything sealed in its database will not open here.")
    there = run(["docker", "ps", "-aq", "--filter", f"label=com.docker.compose.project={project}"], timeout=30).stdout.split()
    if there:
        raise Stop(f"the stack {project} has containers already: a Rouh is brought in only before a stack's first "
                   "start. Nothing changed")
    for vol in ("pgdata", "keys", "core-data"):
        if not run(["docker", "volume", "inspect", f"{project}_{vol}"], timeout=30).returncode:
            raise Stop(f"the stack {project} has its {vol} volume already, so it is not a fresh one: a Rouh is brought "
                       "in only before a stack's first start. Nothing changed (to start afresh and lose what is there: "
                       f"docker volume rm {project}_pgdata {project}_keys {project}_core-data)")
    for vol in ("pgdata", "keys", "core-data"):
        run(["docker", "volume", "create", "--label", f"com.docker.compose.project={project}",
             "--label", f"com.docker.compose.volume={vol}", f"{project}_{vol}"], timeout=60, check=True)

    say("Putting the database in")
    run(compose + ["up", "--detach", "--no-deps", "postgres"], timeout=600, check=True)
    try:
        end = time.monotonic() + wait
        while _ps(run(compose + ["ps", "--all", "--format", "json", "postgres"], timeout=60).stdout).get(
                "postgres", {}).get("Health") != "healthy":
            if time.monotonic() > end:
                raise Stop("PostgreSQL did not come up to take the database; the three volumes are left as they are")
            time.sleep(3)
        # Into the container whole first, so pg_restore reads a file it can seek in, with several jobs
        # at once (a 14 GB database: 10 minutes with four, against more than twice that with one).
        restore_sh = ("set -e; f=/tmp/rouh-import.dump; trap 'rm -f $f' EXIT; cat > $f; "
                      f"pg_restore -U rouh -d rouh --no-owner --no-privileges -j {IMPORT_JOBS} $f")
        with tarfile.open(path, mode="r:") as t, tempfile.TemporaryFile() as err:
            p = subprocess.Popen(compose + ["exec", "-T", "postgres", "sh", "-c", restore_sh], stdin=subprocess.PIPE,
                                 stdout=subprocess.DEVNULL, stderr=err, env=CLEAN_ENV)
            try:
                shutil.copyfileobj(t.extractfile(rouh_bundle.DUMP), p.stdin, 1 << 20)
            finally:
                p.stdin.close()
            code = p.wait(timeout=7200)
            err.seek(0)
            said = err.read().decode(errors="replace")
        errors = [line for line in said.splitlines() if "error:" in line]
        if code and not errors:
            raise Stop(f"the database could not be put in: {said.strip()[-400:]}")
        if errors:
            # Every one written down, never only counted.
            (Path(os.environ.get("ROUH_IMPORT_LOG_DIR") or tempfile.gettempdir()) / f"{project}-import-errors.txt").write_text(
                "\n".join(errors) + "\n")
        # Two things a server may have that PostgreSQL's image has not, each with Rouh's own way
        # round it: ParadeDB's pg_search (Rouh ranks its words in PostgreSQL itself,
        # rouh/synapse/search.py), and Hunspell's Bulgarian dictionary files (Synapse's word forms
        # fall back to plain lower-casing, as migration 0062 does on any machine without them).
        bulgarian = [line for line in errors if "tsearch_data" in line or "bg_hunspell" in line]
        other = [line for line in errors if line not in bulgarian
                 and not any(w in line for w in ("pg_search", "bm25", "paradedb", "schema \"pdb\""))]
        if other:
            raise Stop(f"{len(errors)} part(s) of the database could not be put in, so it is not brought in: "
                       + " | ".join(other[:4])[:900])
        if bulgarian:
            fix = ("DO $$ BEGIN IF to_regnamespace('synapse') IS NOT NULL AND NOT EXISTS (SELECT 1 FROM pg_ts_dict d "
                   "JOIN pg_namespace n ON n.oid = d.dictnamespace WHERE n.nspname = 'synapse' AND d.dictname = 'bg_hunspell') "
                   "THEN CREATE TEXT SEARCH DICTIONARY synapse.bg_hunspell (TEMPLATE = pg_catalog.simple); "
                   "IF EXISTS (SELECT 1 FROM pg_ts_config c JOIN pg_namespace n ON n.oid = c.cfgnamespace "
                   "WHERE n.nspname = 'synapse' AND c.cfgname = 'bg') THEN ALTER TEXT SEARCH CONFIGURATION synapse.bg "
                   "ALTER MAPPING FOR word, hword, hword_part WITH synapse.bg_hunspell, simple; END IF; END IF; END $$;")
            r = run(compose + ["exec", "-T", "postgres", "psql", "-v", "ON_ERROR_STOP=1", "-U", "rouh", "-d", "rouh", "-c", fix],
                    timeout=120)
            if r.returncode:
                raise Stop(f"Synapse's Bulgarian word forms could not be set up without their dictionary: "
                           f"{(r.stderr or r.stdout).decode(errors='replace').strip()[-300:]}")
            say("Synapse's Bulgarian word forms are plain lower-casing here: this PostgreSQL has no Hunspell "
                "Bulgarian dictionary.")
        if len(errors) > len(bulgarian):
            say(f"The database is in, but for {len(errors) - len(bulgarian)} part(s) of pg_search, which this PostgreSQL "
                "has not; Rouh ranks its words without it.")
    finally:
        run(compose + ["stop", "postgres"], timeout=300)
        run(compose + ["rm", "--force", "postgres"], timeout=300)

    say("Putting the keys and the files in")
    with open(path, "rb") as src:
        r = subprocess.run(["docker", "run", "--rm", "-i", "--network", "none", "--user", "0:0", "--cap-drop", "ALL",
                            "--cap-add", "CHOWN", "--cap-add", "DAC_OVERRIDE", "--cap-add", "FOWNER",
                            "--security-opt", "no-new-privileges:true",
                            "-v", f"{project}_keys:/keys", "-v", f"{project}_core-data:/data",
                            "--entrypoint", "python", base, "-I", "-c", PLACE, rouh_bundle.TOP],
                           stdin=src, capture_output=True, timeout=7200, env=CLEAN_ENV)
    if r.returncode:
        raise Stop(f"the keys and files could not be put in: {r.stderr.decode(errors='replace').strip()[-400:]}")
    said = r.stdout.decode(errors="replace").strip().splitlines()
    say(f"Brought in: the database, and {said[-1] if said else 'the files'}.")
    return about


def import_cmd(m: Machine, bundle: str, release_file: str | None) -> int:
    if m.read_release("current.json") is not None:
        raise Stop("this machine runs a Rouh already (releases/current.json): an existing Rouh is brought in only "
                   "before a stack's first start. Nothing changed")
    path = Path(bundle).expanduser().resolve()
    if not path.is_file():
        raise Stop(f"there is no bundle at {path}")
    r, _ = newest_release(release_file, mac_release.CHANNEL)
    say(f"Into a stack on base {r['level']} (release {r['version']})")
    m.release_env.write_text(m.release_env_text(r, m.settings))
    m.reference.write_text(r["compose"])
    for image in (r["images"]["postgres"], r["images"]["base"]):
        run(["docker", "pull", "--quiet", image], timeout=1800, check=True)
    import_bundle(path, m.compose(m.reference), PROJECT, r["images"]["base"])
    say("Start it with: linux_stack.py update. Its owner is the one it had; to sign in, open the address that "
        f"`docker compose -p {PROJECT} -f ~/rouh/stack/stack.json exec core python manage.py setup_link` prints. "
        "Delete the bundle once Rouh is up: it opens every saved login.")
    return 0


# ---------------------------------------------------------------- small helpers


def _resolved(r: subprocess.CompletedProcess) -> tuple[dict | None, str]:
    if r.returncode:
        return None, f"Compose could not read it: {(r.stderr or r.stdout).decode(errors='replace').strip()[-300:]}"
    try:
        return json.loads(r.stdout), ""
    except json.JSONDecodeError:
        return None, "Compose did not answer with JSON"


def _ps(out: bytes) -> dict:
    """compose ps --format json: one JSON array, or one object a line, by Compose's version."""
    text = out.decode(errors="replace").strip()
    rows = json.loads(text) if text.startswith("[") else [json.loads(x) for x in text.splitlines() if x.strip()]
    return {row.get("Service"): row for row in rows}


def _wipe(p: Path) -> None:
    if p.is_dir() and not p.is_symlink():
        shutil.rmtree(p)
    elif p.exists() or p.is_symlink():
        p.unlink()


def _copy(src: Path, dst: Path) -> None:
    shutil.copytree(src, dst, symlinks=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="linux_stack.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default=str(Path.home() / "rouh"), help="the folder of this Rouh's settings and releases")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("update").add_argument("--release", help="a signed release file, instead of rouh.land's newest")
    sub.add_parser("apply")
    sub.add_parser("back")
    sub.add_parser("status")
    sub.add_parser("restore").add_argument("name", nargs="?", default="", help="a copy rouh-backup list names; the newest without")
    imp = sub.add_parser("import")
    imp.add_argument("bundle", help="a bundle made by manage.py export_rouh (rouh/bundle.py)")
    imp.add_argument("--release", help="a signed release file, instead of rouh.land's newest")
    a = ap.parse_args(argv)
    root = Path(a.dir).expanduser().resolve()
    # Docker's -v takes "folder:folder:ro", so a colon or a comma in the folder's name would be read as more.
    if not re.fullmatch(r"[A-Za-z0-9._/ -]+", str(root)):
        say(f"Put the folder somewhere with a plain name (letters, digits, . _ - / and spaces): {root}")
        return 2
    if a.cmd != "status" and not (root / ".env").is_file():
        say(f"There is no settings file at {root / '.env'}: INSTALL-LINUX-VM.md, step 5.")
        return 2
    m = Machine(root)
    try:
        return {"update": lambda: update(m, a.release), "apply": lambda: apply(m), "back": lambda: back(m),
                "status": lambda: status(m), "restore": lambda: restore(m, a.name),
                "import": lambda: import_cmd(m, a.bundle, a.release)}[a.cmd]()
    except Stop as e:
        say(str(e))
        return 1
    except subprocess.TimeoutExpired as e:
        say(f"{' '.join(map(str, e.cmd[:3]))} took too long; what was there before is in place again")
        return 1


if __name__ == "__main__":
    sys.exit(main())
