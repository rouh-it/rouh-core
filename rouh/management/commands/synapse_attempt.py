"""``python manage.py synapse_attempt``: the attempts to make Synapse better (`rouh/synapse/improvements.py`).

    python manage.py synapse_attempt list                       # newest first, one line each
    python manage.py synapse_attempt show 16                    # everything about one ("latest" for the newest)
    python manage.py synapse_attempt update 16 --json row.json  # write fields onto it, from a JSON object
    python manage.py synapse_attempt update 16 --set outcome=discarded --set spend_usd=0.71
    python manage.py synapse_attempt new --mode baseline --source hand
                                                                # a new attempt, running, and its number
    python manage.py synapse_attempt fail 16 --why "The benchmark would not start: ..."
    python manage.py synapse_attempt backfill                   # the rows task 85's notes document, once

The nightly worker writes its own row with these (`rouh/synapse/nightly_brief.md`). On the server, run it with
Rouh's environment: ``deploy/with-rouh-env.sh <checkout> /var/www/rouh/.venv/bin/python manage.py synapse_attempt ...``
In the containers, from the machine: ``docker compose exec core python manage.py synapse_attempt ...`` (a run in the
worker cannot reach the database: `deploy/with-rouh-env.sh` says so and stops).
"""
from __future__ import annotations

import json
import os

from django.core.management.base import BaseCommand, CommandError

from rouh.synapse import improvements


class Command(BaseCommand):
    help = "The attempts to make Synapse better: list, show, write onto one, start one, fail one."

    def add_arguments(self, parser):
        parser.add_argument("action", choices=["list", "show", "update", "new", "fail", "backfill"])
        parser.add_argument("number", nargs="?", default="", help="the attempt's number, or 'latest'")
        parser.add_argument("--user", default="1", help="the account whose attempts these are")
        parser.add_argument("--org", default="", help="the organisation; the account's own when left out")
        parser.add_argument("--json", default="", help="update: a file holding a JSON object of fields")
        parser.add_argument("--set", action="append", default=[], help="update: key=value (a JSON value or text)")
        parser.add_argument("--mode", default="full", choices=["full", "baseline"])
        parser.add_argument("--source", default="hand", help="new: nightly, hand or backfilled")
        parser.add_argument("--why", default="", help="fail: what stopped it")

    def handle(self, *args, **o):
        os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
        if not improvements.ready():
            raise CommandError("The attempts table is not in this database yet (migration 0087).")
        org, user = o["org"] or self._org_of(o["user"]), str(o["user"])
        act = o["action"]
        if act == "list":
            rows = improvements.listing(org, user)
            self.stdout.write("\n".join(improvements.summary_line(r) for r in rows) or "No attempts yet.")
            return
        if act == "backfill":
            self.stdout.write(f"Backfilled {improvements.backfill(org, user)} attempts.")
            return
        if act == "new":
            row = improvements.start(org, user, mode=o["mode"], source=o["source"])
            self.stdout.write(str(row["number"]))
            return
        row = self._row(org, user, o["number"])
        if act == "show":
            self.stdout.write(improvements.as_text(row))
            return
        if act == "fail":
            got = improvements.fail(org, user, row["number"], o["why"] or "It was stopped by hand.")
            self.stdout.write(improvements.summary_line(got))
            return
        fields = {}
        if o["json"]:
            with open(o["json"]) as fh:
                fields.update(json.load(fh))
        for pair in o["set"]:
            key, _, value = pair.partition("=")
            try:
                fields[key] = json.loads(value)
            except ValueError:
                fields[key] = value
        if not fields:
            raise CommandError("Nothing to write: give --json or --set.")
        try:
            got = improvements.update(org, user, row["number"], fields)
        except ValueError as exc:
            raise CommandError(str(exc)) from None
        self.stdout.write(improvements.summary_line(got))

    @staticmethod
    def _row(org: str, user: str, number: str) -> dict:
        if str(number).lower() in ("latest", "last"):
            row = improvements.latest(org, user)
        else:
            row = improvements.one(org, user, number)
        if row is None:
            raise CommandError(f"There is no attempt {number or '(none given)'}.")
        return row

    @staticmethod
    def _org_of(user_id: str) -> str:
        from rouh.models.accounts import User

        user = User.objects.filter(id=user_id).first()
        if user is None:
            raise CommandError(f"There is no account {user_id}.")
        return str(user.org_id or "org-default")
