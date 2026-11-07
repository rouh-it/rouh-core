"""Checking one proposed commit of a Rouh's code, inside the guard (``changes.py``).

The commit's files are copied out of /code into a folder of their own, and checked there as a
user that can write nothing of the guard's (``CHECK_USER``, 10004): the frozen security checks
(``frozen/run.py``), then the Rouh's own checks (``python -m rouh.selfcheck --only own``), against
the stack's throwaway PostgreSQL (``checkdb``), in a database made for this check and dropped
after it. No key, nothing of the person's: the frozen runner refuses any database holding an
account, and the check's environment has no key in it.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
CHECK_USER = 10004
#: How long one check may take, the frozen and the own checks together.
TIMEOUT = float(os.environ.get("ROUH_GUARD_CHECK_SECONDS", "1500"))


def _db(name: str, make: bool) -> str:
    """Makes (or drops) the check's own database on checkdb; "" or why it could not."""
    import psycopg

    kw = dict(host=os.environ.get("ROUH_GUARD_CHECK_DB", "checkdb"), port="5432", dbname="postgres",
              user="rouh", password="check", connect_timeout=5, autocommit=True)
    end, why = time.monotonic() + 90, ""
    while time.monotonic() < end:
        try:
            with psycopg.connect(**kw) as c:
                c.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
                if make:
                    c.execute(f'CREATE DATABASE "{name}"')
            return ""
        except psycopg.OperationalError as e:
            why = str(e).strip().splitlines()[0] if str(e).strip() else "it does not answer"
            time.sleep(2)
    return f"the check's throwaway database did not answer: {why}"


def _last_line(text: str) -> dict | None:
    for line in reversed(text.splitlines()):
        if line.startswith("ROUH-CHECK "):
            try:
                return json.loads(line[len("ROUH-CHECK "):])
            except ValueError:
                return None
    return None


def run(code: Path, commit: str, say=print) -> dict:
    """The check of `commit` of the repository at `code`: {"ok", "passed", "failed", "seconds"}."""
    began = time.monotonic()
    work = Path(tempfile.mkdtemp(prefix="guard-check-", dir=os.environ.get("ROUH_GUARD_TMP", "/tmp")))
    tree, data = work / "code", work / "data"
    tree.mkdir()
    data.mkdir()
    name = "check_" + commit[:12]
    failed: list[dict] = []
    passed = 0
    try:
        arch = subprocess.run(["git", "-c", "safe.directory=*", "-C", str(code), "archive", "--format=tar", commit],
                              capture_output=True)
        if arch.returncode:
            return {"ok": False, "passed": 0, "seconds": 0.0, "failed": [{
                "name": "the change can be read", "why": arch.stderr.decode(errors="replace").strip()[-300:]}]}
        subprocess.run(["tar", "-x", "-C", str(tree)], input=arch.stdout, check=True)
        subprocess.run(["chown", "-R", f"{CHECK_USER}:{CHECK_USER}", str(work)], check=True)
        why = _db(name, True)
        if why:
            return {"ok": False, "passed": 0, "seconds": 0.0,
                    "failed": [{"name": "the check could run", "why": why}]}
        env = {
            "PATH": "/opt/venv/bin:/extra/python3.12/bin:/usr/local/bin:/usr/bin:/bin",
            "HOME": str(data), "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1",
            "ROUH_DB_HOST": os.environ.get("ROUH_GUARD_CHECK_DB", "checkdb"), "ROUH_DB_USER": "rouh",
            "ROUH_DB_NAME": name, "ROUH_DB_PASSWORD": "check", "ROUH_EXTRA": "/extra",
        }
        drop = ["setpriv", f"--reuid={CHECK_USER}", f"--regid={CHECK_USER}", "--clear-groups", "--"]
        steps = (
            ("the frozen security checks",
             ["python", "-I", str(HERE / "frozen" / "run.py"), "--code", str(tree)], {"ROUH_CHECK_DATA": str(data / "frozen")}),
            ("this Rouh's own checks",
             ["python", "-m", "rouh.selfcheck", "--only", "own"], {"ROUH_CHECK_DATA": str(data / "own")}),
        )
        for label, cmd, more in steps:
            if label == "this Rouh's own checks" and not (tree / "rouh" / "selfcheck" / "__init__.py").is_file():
                failed.append({"name": label, "why": "its code has no rouh/selfcheck, so nothing can show it works"})
                continue
            left = TIMEOUT - (time.monotonic() - began)
            say(f"checking {commit[:12]}: {label}")
            try:
                r = subprocess.run(drop + cmd, cwd=str(tree), env={**env, **more}, capture_output=True,
                                   text=True, timeout=max(30.0, left))
            except subprocess.TimeoutExpired:
                failed.append({"name": label, "why": f"it took longer than {int(TIMEOUT // 60)} minutes"})
                continue
            got = _last_line(r.stdout)
            if got is None:
                failed.append({"name": label, "why": "it stopped before saying how it went: "
                               + (r.stdout + r.stderr).strip()[-400:]})
                continue
            passed += int(got.get("passed") or 0)
            failed += [{"name": f.get("name", "a check"), "why": f.get("why", "")} for f in got.get("failed") or []]
            if not got.get("ok") and not got.get("failed"):
                failed.append({"name": label, "why": "it did not pass"})
        return {"ok": not failed and passed > 0, "passed": passed, "failed": failed,
                "seconds": round(time.monotonic() - began, 1)}
    finally:
        _db(name, False)
        shutil.rmtree(work, ignore_errors=True)
