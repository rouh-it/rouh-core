"""``python manage.py apple``: a person's Apple Contacts, from a terminal.

Settings is where a person connects their iCloud contacts. This is the same
thing for an administrator on the server when nobody is at a browser, and it
goes the same way, through `ContactDesk`: the password is checked with iCloud
before anything is kept, sealed with this instance's key, and never printed.

    manage.py apple status alex
    manage.py apple connect alex --apple-id alex@example.com --password-file FILE
    manage.py apple sync alex
    manage.py apple disconnect alex

The password is never taken from the command line, where every other user of
the machine can read it: it comes from ``--password-file``, or is asked for
without being echoed, or is read from standard input when that is not a
terminal.

On the server it has to run with the service's own environment, or it would
seal the password with a key the service does not have. The deploy's database
step runs that way already (`deploy/rouh.sh`), and so does this:

    systemd-run --quiet --wait --pipe --collect \\
        -p EnvironmentFile=-/var/www/rouh/.env -p WorkingDirectory=/var/www/rouh/app \\
        /var/www/rouh/.venv/bin/python manage.py apple status alex

A password sealed with the wrong key is not a silent failure either: the
service says in Settings that it cannot open it and asks for it again.
"""
from __future__ import annotations

import asyncio
import getpass
import sys

from django.core.management.base import BaseCommand, CommandError

from rouh import clock


class Command(BaseCommand):
    help = "A person's Apple Contacts: status, connect, sync, disconnect."

    def add_arguments(self, parser):
        parser.add_argument("action", choices=["status", "connect", "sync", "disconnect"])
        parser.add_argument("username", help="the Rouh account, e.g. alex")
        parser.add_argument("--apple-id", default="",
                            help="for connect: the Apple ID; the one already kept, or the "
                                 "account's own email, when left out")
        parser.add_argument("--password-file", default="",
                            help="for connect: a file holding the app-specific password")

    def handle(self, *args, action, username, apple_id, password_file, **options):
        from rouh import accounts
        from rouh.apple_contacts import AppleStore, ContactDesk
        from rouh.config import config
        from rouh.encryption import NotEncryptable, SecretBox
        from rouh.google_audit import WriteLog
        from rouh.tenancy import Tenancy

        user = accounts.get_user(username)
        if user is None:
            raise CommandError(f"There is no account called {username}.")
        tenancy = Tenancy()
        who = tenancy.identity_of(str(user.pk))
        if who is None:
            raise CommandError(f"The account {username} is not active.")
        try:
            box = SecretBox(config.encryption_key, data_dir=config.data_dir)
        except NotEncryptable as exc:
            raise CommandError(str(exc)) from exc
        desk = ContactDesk(tenancy, AppleStore(box), config,
                           audit=WriteLog(config.logs_path, name="contacts-writes.log"))

        if action == "connect":
            password = self._password(password_file)
            chosen = (apple_id or desk.store.summary(who.user_id, who.org_id)["apple_id"]
                      or who.email)
            try:
                said = asyncio.run(self._connect(desk, who, chosen, password))
            except ValueError as exc:
                raise CommandError(str(exc)) from exc
            self.stdout.write(said)
        elif action == "sync":
            outcome = asyncio.run(desk.sync(who))
            if outcome.skipped:
                raise CommandError(f"{username} has no Apple Contacts connection that can sync.")
            if outcome.error:
                raise CommandError(outcome.error)
        elif action == "disconnect":
            gone = asyncio.run(desk.disconnect(who))
            self.stdout.write("Disconnected." if gone else "There was nothing to disconnect.")
            return
        self.stdout.write(self._status(desk, who, username))

    @staticmethod
    async def _connect(desk, who, apple_id: str, password: str) -> str:
        said = await desk.connect(who, apple_id, password)
        await desk.finished(who)
        return said.split(" Rouh is fetching")[0]

    @staticmethod
    def _password(path: str) -> str:
        if path:
            try:
                with open(path, encoding="utf-8") as fh:
                    return fh.read().strip()
            except OSError as exc:
                raise CommandError(f"The password file cannot be read: {exc.strerror}.") from exc
        if sys.stdin.isatty():
            return getpass.getpass("App-specific password: ")
        return sys.stdin.readline().strip()

    @staticmethod
    def _status(desk, who, username: str) -> str:
        summary = desk.store.summary(who.user_id, who.org_id)
        if not summary["connected"]:
            return f"{username}: Apple Contacts are not connected."
        lines = [f"{username}: connected as {summary['apple_id']} since "
                 f"{clock.stamp(summary['connected_at'])}",
                 f"  contacts: {summary['contacts']}"]
        if summary["last_sync_at"]:
            lines.append(f"  last synced: {clock.stamp(summary['last_sync_at'])} "
                         f"({clock.ago(summary['last_sync_at'])}), "
                         f"{summary['last_sync_changed']} card(s) changed")
        else:
            lines.append("  last synced: never")
        if summary["last_error"] and summary["last_attempt_at"] >= summary["last_sync_at"]:
            lines.append(f"  trouble: {summary['last_error']}")
        return "\n".join(lines)
