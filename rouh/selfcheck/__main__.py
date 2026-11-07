"""python -m rouh.selfcheck [--only own|security]: Rouh's own checks and the security checks.

Run inside the throwaway check container (guard/bin/rouh-check). It refuses any database
that already holds an account, so it can never be pointed at a real Rouh's by mistake: it makes
its own test accounts and migrates the database it is given.
"""
from __future__ import annotations

import argparse
import base64
import os
import sys
import tempfile
import time
from pathlib import Path


def _environment() -> None:
    """Nothing of the person's: no keys, no live services, a data folder of its own."""
    data = Path(os.environ.get("ROUH_CHECK_DATA") or tempfile.mkdtemp(prefix="rouh-check-"))
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
        "ROUH_DELEGATE": "0",
        "ROUH_BROWSER": "0",
        "ROUH_SHELL": "0",
        "ROUH_SELF_UPDATE": "0",
        "ROUH_ALLOWED_HOSTS": "localhost,127.0.0.1",
        "PYTHONDONTWRITEBYTECODE": "1",
    })
    os.environ.setdefault("ROUH_ENCRYPTION_KEY", base64.urlsafe_b64encode(os.urandom(32)).decode())
    os.environ.setdefault("ROUH_SECRET_KEY", base64.urlsafe_b64encode(os.urandom(32)).decode())
    for d in ("data", "logs", "workspace", "keys"):
        (data / d).mkdir(exist_ok=True)


def _database(wait: float) -> str:
    """"" when the throwaway database answers and is empty of accounts, else why not."""
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
    ap = argparse.ArgumentParser(prog="python -m rouh.selfcheck")
    ap.add_argument("--only", choices=("own", "security"), default="")
    ap.add_argument("--wait-db", type=float, default=90.0)
    a = ap.parse_args()

    _environment()
    from rouh import selfcheck

    why = _database(a.wait_db)
    if why.startswith("the database already holds"):
        print(f"refused: {why}")
        return 2
    if why:
        print(f"no database: {why}")
    import django

    django.setup()
    if not why:
        # The schema first, so the checks that need it find it; the migration check says so
        # itself when this fails, so a failure here is not hidden.
        from django.core.management import call_command

        try:
            call_command("migrate", "--noinput", verbosity=0)
        except Exception as e:  # noqa: BLE001 - said by the migration check
            print(f"note: the database did not migrate before the checks: {type(e).__name__}: {e}")
    report = selfcheck.run(a.only, db_ready=not why)
    print(f"{len(report.passed)} passed, {len(report.failed)} failed, in {report.seconds:.0f} s")
    print(report.line())
    sys.stdout.flush()
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
