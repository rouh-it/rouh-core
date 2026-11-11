"""The protected proof of one adapted master change, before its undo point is made.

Proof programs run as the check user with no live credentials. Security assertions must name
the same checks and show vulnerable before and safe afterwards; a crash is never a reproduction.
Database changes additionally pass database_update's fresh-backup and real-copy gate.
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


def run(code: Path, before: str, after: str, evidence: dict, state: Path) -> dict:
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
            subprocess.run(["chown", "-R", f"{CHECK_USER}:{CHECK_USER}", str(work)], check=True)
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
