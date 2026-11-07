"""Runs the frozen security checks against one copy of a Rouh's code.

    python -I /opt/rouh-guard/frozen/run.py --code /code [--wait-db 90]

Part of the protected core. Run by ``rouh-check`` (a new base, in a throwaway container) and by
the guard's change step (a proposed change, in the guard's own container, as a user that can
write nothing of the guard's). Like the Rouh's own ``rouh.selfcheck`` it takes no key, nothing
of the person's, and refuses any database that already holds an account, so it can never touch
a real Rouh's data. It migrates the throwaway database itself.

Its last line is ``ROUH-CHECK {json}``: ``{"ok", "passed", "failed": [{"name", "group", "why"}],
"gaps", "face"}``. Exit 0 only when every check passed.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent

#: Said on every run and never failed: what is known to be missing, with the reason.
KNOWN_GAPS = (
    "chats and tasks are not separated per person",
    "approval prompts are off unless an installation lists tools",
)


def _environment() -> None:
    data = Path(os.environ.get("ROUH_CHECK_DATA") or tempfile.mkdtemp(prefix="rouh-frozen-"))
    data.mkdir(parents=True, exist_ok=True)
    for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "ELEVENLABS_API_KEY", "VOYAGE_API_KEY",
                "YOUTUBE_API_KEY", "ROUH_TELEGRAM_TOKEN"):
        os.environ.pop(key, None)
    os.environ.update({
        "DJANGO_SETTINGS_MODULE": "rouh.project.settings",
        "ROUH_DATA_DIR": str(data / "data"),
        "ROUH_LOG_DIR": str(data / "logs"),
        "ROUH_WORKSPACE": str(data / "workspace"),
        "ROUH_DB_PASSWORD_FILE": str(data / "no-password-file.json"),
        "ROUH_TELEGRAM_FILE": str(data / "no-telegram.json"),
        "ROUH_BREVO_FILE": str(data / "no-brevo.json"),
        "ROUH_TELEGRAM_API_BASE": "http://127.0.0.1:1/no-telegram",
        "ROUH_ONE_SOCKET": str(data / "one.sock"),
        "ROUH_ONE_TOKEN": str(data / "voice.json"),
        "ROUH_KEYS_DIR": str(data / "keys"),
        "ROUH_GUARD_SOCKET": str(data / "no-guard.sock"),
        "ROUH_DELEGATE": "0",
        "ROUH_BROWSER": "0",
        "ROUH_SHELL": "0",
        "ROUH_SELF_UPDATE": "0",
        "ROUH_ALLOWED_HOSTS": "localhost,127.0.0.1",
        "PYTHONDONTWRITEBYTECODE": "1",
    })
    os.environ["ROUH_ENCRYPTION_KEY"] = base64.urlsafe_b64encode(os.urandom(32)).decode()
    os.environ["ROUH_SECRET_KEY"] = base64.urlsafe_b64encode(os.urandom(32)).decode()
    for d in ("data", "logs", "workspace", "keys"):
        (data / d).mkdir(exist_ok=True)


def _database(wait: float) -> str:
    """"" when the throwaway database answers and holds no account but the checks' own."""
    import psycopg

    kw = dict(host=os.environ.get("ROUH_DB_HOST", "127.0.0.1"), port=os.environ.get("ROUH_DB_PORT", "5432"),
              dbname=os.environ.get("ROUH_DB_NAME", "rouh"), user=os.environ.get("ROUH_DB_USER", "rouh"),
              password=os.environ.get("ROUH_DB_PASSWORD", ""), connect_timeout=3)
    end, why = time.monotonic() + wait, ""
    while True:
        try:
            with psycopg.connect(**kw) as c:
                found = c.execute("SELECT to_regclass('public.users')").fetchone()[0]
                if found and c.execute("SELECT count(*) FROM users WHERE username NOT LIKE 'check-%'").fetchone()[0]:
                    return ("the database already holds accounts, so it is not a throwaway one; "
                            "these checks make accounts of their own and are never run on a real Rouh's")
            return ""
        except psycopg.OperationalError as e:
            why = str(e).strip().splitlines()[0] if str(e).strip() else "it does not answer"
        if time.monotonic() >= end:
            return f"the throwaway database at {kw['host']} did not answer: {why}"
        time.sleep(1)


def main() -> int:
    ap = argparse.ArgumentParser(prog="frozen/run.py")
    ap.add_argument("--code", default="/code")
    ap.add_argument("--wait-db", type=float, default=90.0)
    a = ap.parse_args()
    code = Path(a.code).resolve()

    def result(passed, failed) -> int:
        out = {"ok": not failed and bool(passed), "passed": len(passed), "failed": failed,
               "gaps": list(KNOWN_GAPS), "face": "rouh.checkface"}
        print(f"{len(passed)} passed, {len(failed)} failed")
        print("ROUH-CHECK " + json.dumps(out, ensure_ascii=False))
        sys.stdout.flush()
        return 0 if out["ok"] else 1

    if not (code / "manage.py").is_file() or not (code / "rouh").is_dir():
        return result([], [{"name": "this Rouh answers the check face", "group": "security",
                            "why": f"there is no Rouh code at {code}"}])
    if not (code / "rouh" / "checkface.py").is_file():
        return result([], [{"name": "this Rouh answers the check face", "group": "security",
                            "why": "its code has no rouh/checkface.py, so the security checks cannot ask it anything"}])
    os.chdir(code)
    sys.path[:0] = [str(HERE), str(code)]
    _environment()
    why = _database(a.wait_db)
    if why.startswith("the database already holds"):
        print(f"refused: {why}")
        return 2
    if why:
        print(f"no database: {why}")
    import django

    django.setup()
    if not why:
        from django.core.management import call_command

        try:
            call_command("migrate", "--noinput", verbosity=0)
        except Exception as e:  # noqa: BLE001 - every check that needs it then says so
            print(f"note: the database did not migrate before the checks: {type(e).__name__}: {e}")
    import check
    import security  # noqa: F401 - registers the checks

    report = check.run(db_ready=not why)
    for gap in KNOWN_GAPS:
        print(f"gap   {gap}")
    return result(report.passed, report.failed)


if __name__ == "__main__":
    sys.exit(main())
