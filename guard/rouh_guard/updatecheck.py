"""The protected proof of one adapted master change, before its undo point is made.

Proof programs run as the check user with no live credentials. Security assertions must name
the same checks and show vulnerable before and safe afterwards; a crash is never a reproduction.
Database changes additionally pass database_update's fresh-backup and real-copy gate.

From core 1.1 (17 November 2026) every file the Rouh says it copied exactly is checked here against
the release commit itself, which the Rouh fetches into /code beside the proposal: its blob in the
proposed commit must be the release's, hash for hash. A change that is nothing but such copies, of
files that were in this Rouh exactly as the change found them, is the released change itself, so it
needs no adapting job's proof, unless it changes the database.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from .checks import CHECK_USER


def tree(code: Path, commit: str, into: Path) -> None:
    into.mkdir(parents=True)
    archive = subprocess.run(["git", "-c", "safe.directory=*", "-C", str(code), "archive", commit],
                             capture_output=True, check=True)
    subprocess.run(["tar", "-xf", "-", "-C", str(into)], input=archive.stdout, check=True)



def readonly(tree: Path) -> None:
    """Checks may write their scratch data, never the code later given a live connection."""
    for folder, dirs, files in os.walk(tree, followlinks=False):
        for name in files + dirs:
            path = Path(folder) / name
            os.chown(path, 0, 0, follow_symlinks=False)
            if not path.is_symlink():
                os.chmod(path, 0o555 if path.is_dir() or path.stat().st_mode & 0o111 else 0o444)
        os.chown(folder, 0, 0)
        os.chmod(folder, 0o555)


def env(data: Path, db: dict | None = None) -> dict:
    out = {"PATH": "/opt/venv/bin:/extra/python3.12/bin:/usr/local/bin:/usr/bin:/bin", "HOME": str(data),
           "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1", "ROUH_DATA_DIR": str(data),
           "ROUH_LOG_DIR": str(data / "logs"), "ROUH_WORKSPACE": str(data / "workspace"),
           "ROUH_KEYS_DIR": str(data / "keys"), "ROUH_SELF_UPDATE": "0", "ROUH_BROWSER": "0",
           "ROUH_DELEGATE": "0", "ROUH_ENCRYPTION_KEY_FILE": str(data / "no-encryption-key"),
           "ROUH_DB_PASSWORD_FILE": str(data / "no-db-password"), "DJANGO_SETTINGS_MODULE": "rouh.project.settings"}
    if db:
        out.update({"ROUH_DB_" + k: str(v) for k, v in db.items()})
    return out


def run_program(program: Path, cwd: Path, environment: dict, *args: str, user: int = CHECK_USER) -> subprocess.CompletedProcess:
    pre = ["setpriv", f"--reuid={user}", f"--regid={user}", "--clear-groups", "--"] if os.getuid() == 0 else []
    return subprocess.run([*pre, "python", str(program), *args], cwd=cwd, env={**environment, "PYTHONPATH": str(cwd)},
                          text=True, capture_output=True, timeout=1200)


def security_result(result) -> dict:
    for line in result.stdout.splitlines():
        if line.startswith("ROUH-SECURITY "):
            return json.loads(line.removeprefix("ROUH-SECURITY "))
    raise ValueError("the security proof returned no named security assertions")


def _git(code: Path, *args: str) -> str:
    from .changes import _git as git

    r = git(*args, cwd=code)
    return r.stdout.strip() if r.returncode == 0 else ""


def _blob(code: Path, commit: str, path: str) -> str:
    """mode and hash of path at commit, "" when it is not there."""
    got = _git(code, "ls-tree", commit, "--", path).split("\t", 1)[0].split()
    return f"{got[0]} {got[2]}" if len(got) == 3 else ""


def exact(code: Path, before: str, after: str, evidence: dict) -> bool:
    """Check every exact copy against the release commit; whether the change is nothing else.
    Raises ValueError when a copy is not the release's."""
    copies = evidence.get("exact") or {}
    if not isinstance(copies, dict) or not copies:
        return False
    master = str(evidence.get("master") or "")
    if not master or _git(code, "rev-parse", "--verify", "-q", master + "^{commit}") != master:
        raise ValueError("the release commit of an exact copy is not beside the proposal in /code")
    start = _git(code, "rev-parse", "--verify", "-q", master + "^1^{commit}")
    released = set(_git(code, "diff", "--name-only", "--no-renames", start, master).splitlines()) if start else set()
    for path, blob in copies.items():
        want = _blob(code, master, path)
        got = _blob(code, after, path)
        if path not in released or (want.split()[1] if want else "") != str(blob or "") or got != want:
            raise ValueError(f"{path} is not an exact copy of the release {master[:12]}")
    changed = set(_git(code, "diff", "--name-only", "--no-renames", before, after).splitlines())
    if evidence.get("merged") or evidence.get("model") or not changed <= set(copies):
        return False
    # Each copied file was here as the change found it (or as it leaves it): nothing of this Rouh's own lost.
    return all(_blob(code, before, p) in (_blob(code, start, p), _blob(code, master, p)) for p in copies)


def run(code: Path, before: str, after: str, evidence: dict, state: Path) -> dict:
    try:
        whole = exact(code, before, after, evidence)
    except Exception as exc:
        return {"ok": False, "passed": 0, "failed": [{"name": "exact copy", "why": str(exc)[-600:]}]}
    if whole and not evidence.get("database") and not str(evidence.get("proof") or "").strip():
        return {"ok": True, "passed": 1, "failed": []}
    work = Path(tempfile.mkdtemp(prefix="guard-update-"))
    try:
        old, new, data = work / "before", work / "after", work / "data"
        tree(code, before, old)
        tree(code, after, new)
        data.mkdir()
        proof = work / "proof.py"
        proof.write_text(str(evidence.get("proof") or ""))
        if not proof.stat().st_size:
            if evidence.get("database") or evidence.get("security") or evidence.get("model"):
                raise ValueError("the adapting job supplied no proof for this change")
            return {"ok": True, "passed": 0, "failed": []}
        if os.getuid() == 0:
            os.chmod(work, 0o711)
            readonly(old)
            readonly(new)
            os.chown(proof, 0, 0)
            os.chmod(proof, 0o444)
            os.chown(data, CHECK_USER, CHECK_USER)
        environment = env(data)
        # Ordinary logic checks have no database access. A database proof runs on the real copy below.
        if not evidence.get("database"):
            if evidence.get("security"):
                was = run_program(proof, old, environment)
                b = security_result(was)
                expected = not evidence.get("not_applicable", False)
                if was.returncode != (1 if expected else 0) or b.get("vulnerable") is not expected or not b.get("checks"):
                    raise ValueError("the security test did not show the hole in this Rouh before the change")
            now = run_program(proof, new, environment)
            if now.returncode:
                raise ValueError("master's adapted change test failed: " + (now.stdout + now.stderr)[-1200:])
            if evidence.get("security"):
                a = security_result(now)
                if a.get("vulnerable") is not False or a.get("checks") != b.get("checks"):
                    raise ValueError("the same security assertions did not show the hole closed afterwards")
        else:
            from . import database_update

            database_update.run(new, proof, evidence.get("database_plan") or {}, state, after,
                                before=old, security=evidence.get("security", False),
                                not_applicable=evidence.get("not_applicable", False))
        return {"ok": True, "passed": 1, "failed": []}
    except Exception as exc:
        return {"ok": False, "passed": 0, "failed": [{"name": "master change proof", "why": str(exc)[-1600:]}]}
    finally:
        shutil.rmtree(work, ignore_errors=True)
