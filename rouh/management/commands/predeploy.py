"""``python manage.py predeploy``: what the deploy does before it restarts Rouh.

`deploy/rouh.sh` runs this with the new code checked out and the old process
still serving, and restarts Rouh only if it succeeds; if it fails, the deploy
puts the old commit back and restarts that. So everything here either
finishes or leaves the old Rouh running as it was:

1. **The database exists.** On the server, the first time, it is made:
   PostgreSQL's role `rouh`, a password made once and kept in a file only root
   can read (`config.db_password_file`), and the database `rouh` owned by it,
   sorting text by code point as SQLite did. Only as root, only on this
   machine's own PostgreSQL, and only when the database cannot be reached as
   it is configured.
2. **The schema is the code's**: `migrate`.
3. **The data has moved.** If the SQLite file Rouh kept everything in until
   23 September 2026 is still there and has not been moved, the old service is
   stopped - so nothing more is written to the file - and every row is copied
   in (`rouh/sqlite_import.py`). Downtime starts here, and Petar accepted it.
4. **The owner has his sign-in.** Once, ever: a new password for this
   install's owner is sent by Telegram and by email and only then set
   (`rouh/handover.py`). If it went nowhere, this fails and the deploy puts
   the old Rouh back, because switching to a system nobody has the password
   to is the one outcome worse than not switching.

Each step says one line about itself; the last line is the summary the deploy
log keeps.
"""
from __future__ import annotations

import getpass
import json
import os
import secrets
import shutil
import subprocess
import time

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import OperationalError, connections

from rouh import handover, sqlite_import
from rouh.config import config


class Command(BaseCommand):
    help = "Make the database ready for the code about to start, before the restart."

    def add_arguments(self, parser):
        parser.add_argument("--service", default="",
                            help="the systemd unit to stop before the data moves (rouh)")
        parser.add_argument("--systemctl", default="systemctl")
        parser.add_argument("--no-handover", action="store_true",
                            help="never send the owner a password, whatever the state")

    def handle(self, *args, service="", systemctl="systemctl", no_handover=False, **options):
        # The handover's delivery is async and reads the Google connection.
        os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
        said: list[str] = []

        said.append(self._database())
        said.append(self._extensions())
        call_command("migrate", interactive=False, verbosity=0)
        said.append("the schema is current")

        path = config.legacy_sqlite_path
        moved = False
        again = sqlite_import.stale(path)
        if sqlite_import.pending(path) or again:
            from rouh.models import User

            if User.objects.exists() and not again:
                said.append("PostgreSQL already has accounts, so the SQLite file was left alone")
            else:
                if service:
                    self._say(f"stopping {service}, so nothing more is written to {path}")
                    stopped = subprocess.run([systemctl, "stop", service],
                                             capture_output=True, text=True)
                    if stopped.returncode != 0:
                        raise CommandError(f"{service} would not stop: {stopped.stderr.strip()}")
                if again:
                    # A rollback put the Rouh from before the move back, and
                    # it wrote to the file since: that is the newer truth.
                    self._say("the SQLite file was written after the move, so it is moved again")
                    sqlite_import.forget_everything()
                try:
                    got = sqlite_import.run(path)
                except sqlite_import.ImportFailed as exc:
                    raise CommandError(f"the data did not move: {exc}")
                rows = sum(got["tables"].values())
                left = sum(got.get("left_out", {}).values())
                said.append(f"{rows} rows moved from SQLite in {got.get('seconds')}s"
                            + (f", {left} pointing at nothing left out" if left else ""))
                self._say(json.dumps(got["tables"], sort_keys=True))
                if handover.set_up_sign_in_with_google():
                    said.append(f"the default organisation signs in with Google from "
                                f"{handover.OWNER_SSO_DOMAIN}")
                moved = True

        if not no_handover:
            said.append(self._handover(moved))
        said.append(self._decisions())

        self._say("predeploy: " + "; ".join(s for s in said if s))

    def _decisions(self) -> str:
        """Every ask open at any source taken into Decisions (`manage.py decisions_migrate`),
        with its counts in the log. Petar, 5 October 2026: "also migrate the current
        decisions to the new decision platform". Never a reason to keep the old Rouh: what
        cannot be read here is taken in by Rouh itself at start."""
        from rouh import telegram
        from rouh.tenancy import Tenancy

        from .decisions_migrate import migrate, report

        try:
            who = telegram.phone_owner(Tenancy())
            if who is None:
                return "no owner yet, so no decisions to take in"
            got = migrate(who)
        except Exception as exc:  # noqa: BLE001 - the deploy goes on; Rouh syncs at start
            return f"the decisions were not taken in here ({type(exc).__name__}: {exc}); Rouh does it at start"
        self._say(report(got))
        return (f"decisions: {got['new']} taken in, "
                f"{sum(n['decisions_after'] for n in got['sources'].values())} open")

    def _say(self, line: str) -> None:
        self.stdout.write(line)
        self.stdout.flush()

    # --- the database ------------------------------------------------------------

    def _database(self) -> str:
        """Reach the database as configured, or make it and then reach it."""
        from rouh import dbwork

        # A database that is there but has no connection free (every slot taken, SQLSTATE
        # 53300) is not a database that is missing: it is waited for, for a minute, and never
        # "made", which would also set the role's password again. On 19 October 2026 a deploy
        # was rolled back for mistaking one for the other (task 137).
        until = time.monotonic() + 60
        while True:
            try:
                connections["default"].ensure_connection()
                return "the database answers"
            except OperationalError as exc:
                why = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
                if not dbwork.busy(exc):
                    break
                if time.monotonic() > until:
                    raise CommandError(f"the database is there but has no connection free ({why}); "
                                       "nothing was made or changed")
                self._say(f"the database has no connection free yet ({why}); waiting")
                connections["default"].close()
                time.sleep(3)
        if os.geteuid() != 0 or not shutil.which("runuser"):
            raise CommandError(f"the database cannot be reached ({why}), and only root "
                               "on the server makes it")
        if config.db_host not in ("127.0.0.1", "localhost", "::1"):
            raise CommandError(f"the database at {config.db_host} cannot be reached ({why}), "
                               "and only this machine's own is ever made here")
        self._say(f"the database cannot be reached yet ({why}); making it")
        password = self._password()
        role, name = config.db_user, config.db_name
        # Identifiers are checked, not quoted into shape: they come from this
        # file's own defaults or the service's environment, and anything else
        # is a mistake worth stopping on.
        for word in (role, name):
            if not word.replace("_", "").isalnum():
                raise CommandError(f"{word!r} is not a name this will make")
        script = f"""
\\set ON_ERROR_STOP on
SELECT 'CREATE ROLE {role} LOGIN' WHERE NOT EXISTS
    (SELECT FROM pg_roles WHERE rolname = '{role}')\\gexec
ALTER ROLE {role} WITH LOGIN PASSWORD :'pw';
SELECT 'CREATE DATABASE {name} OWNER {role} TEMPLATE template0 ENCODING ''UTF8'''
       ' LC_COLLATE ''C'' LC_CTYPE ''C.UTF-8''' WHERE NOT EXISTS
    (SELECT FROM pg_database WHERE datname = '{name}')\\gexec
"""
        made = subprocess.run(
            ["runuser", "-u", "postgres", "--", "psql", "-X", "-q", "-v", f"pw={password}",
             "-d", "postgres", "-f", "-"],
            input=script, capture_output=True, text=True, cwd="/")
        if made.returncode != 0:
            raise CommandError("PostgreSQL would not make the database: "
                               + (made.stderr or made.stdout).strip()[-400:])
        connection = connections["default"]
        connection.close()
        connection.settings_dict["PASSWORD"] = password
        try:
            connection.ensure_connection()
        except OperationalError as exc:
            raise CommandError(f"the database was made and still cannot be reached: {exc}")
        return f"the database {name} was made, owned by {role}"

    def _extensions(self) -> str:
        """The extensions Synapse's lab needs, made as PostgreSQL's own user.

        pgvector (`vector`) and `pg_trgm` may only be made by a superuser, and
        Rouh's own role is not one, so the migration that uses them
        (`0062_synapse_lab`) would stop here otherwise. Made before `migrate`,
        on this machine's own database only, and only when there is root to
        do it with; anywhere else the migration makes them itself or says why
        it cannot.
        """
        if os.geteuid() != 0 or not shutil.which("runuser"):
            return ""
        if config.db_host not in ("127.0.0.1", "localhost", "::1", ""):
            return ""
        name = config.db_name
        if not name.replace("_", "").isalnum():
            return ""
        made = subprocess.run(
            ["runuser", "-u", "postgres", "--", "psql", "-X", "-q", "-v", "ON_ERROR_STOP=1",
             "-d", name, "-c", "CREATE EXTENSION IF NOT EXISTS vector; "
                               "CREATE EXTENSION IF NOT EXISTS pg_trgm;"],
            capture_output=True, text=True, cwd="/")
        if made.returncode != 0:
            raise CommandError("PostgreSQL would not make the vector and pg_trgm extensions: "
                               + (made.stderr or made.stdout).strip()[-400:])
        return "the vector and pg_trgm extensions are there"

    def _password(self) -> str:
        """The role's password: the one in the file, or a new one written there."""
        kept = config.db_password_now()
        if kept:
            return kept
        folder = os.path.dirname(config.db_password_file)
        os.makedirs(folder, mode=0o700, exist_ok=True)
        made = secrets.token_urlsafe(32)
        fd = os.open(config.db_password_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"password": made}, fh)
            fh.write("\n")
        self._say(f"a password for the database role was made and kept in "
                  f"{config.db_password_file} (root only)")
        return made

    # --- the owner's sign-in ---------------------------------------------------------

    def _handover(self, just_moved: bool) -> str:
        from rouh import accounts
        from rouh.models import Handover

        owner = accounts.get_user(handover.OWNER_USERNAME)
        if owner is None:
            return ""
        if Handover.objects.exists():
            return ""
        self._say(f"sending {owner.username} a new password before the switch "
                  f"(run as {getpass.getuser()})")
        try:
            went = handover.hand_over(owner.username, handover.OWNER_EMAIL)
        except handover.NotDelivered as exc:
            raise CommandError(f"the switch is off: {exc}")
        return f"the sign-in for {owner.username} was delivered by {', '.join(went)}"
