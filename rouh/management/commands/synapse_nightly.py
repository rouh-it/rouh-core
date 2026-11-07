"""``python manage.py synapse_nightly``: the nightly Synapse run, by hand (`rouh/synapse/nightly.py`).

    python manage.py synapse_nightly status                   # its row on the Reminders page, and the last attempts
    python manage.py synapse_nightly start --mode baseline    # start tonight's worker now, only measuring main
    python manage.py synapse_nightly start                    # a full night, now
    python manage.py synapse_nightly settle                   # call attempts nothing will finish failed, with why
    python manage.py synapse_nightly ensure                   # its row on the Reminders page, and the backfill,
                                                              # as Rouh makes them at start-up
    python manage.py synapse_nightly plan                     # whether tonight recalibrates before its idea, and
                                                              # against which commit (`rouh/synapse/recalibrate.py`)
    python manage.py synapse_nightly recalibrate --main main.json --old old.json --json before.json
                                                              # the recalibration's verdict and the attempt's before,
                                                              # from `synapse_benchmark run --json` files (add
                                                              # --judged judged.json when main had to be judged)

Rouh starts it by itself at 02:00 on the person's clock; this is for starting it now and for looking. A worker
is a run of the one program, so this must run as root, with Rouh's environment:
``deploy/with-rouh-env.sh <checkout> /var/www/rouh/.venv/bin/python manage.py synapse_nightly start --mode baseline``
In the containers, from the machine: ``docker compose exec core python manage.py synapse_nightly ...`` (a run in the
worker cannot reach the database: `deploy/with-rouh-env.sh` says so and stops).
"""
from __future__ import annotations

import asyncio
import json
import os

from django.core.management.base import BaseCommand, CommandError

from rouh.synapse import improvements, nightly, recalibrate


class Command(BaseCommand):
    help = "The nightly Synapse run: where it stands, start it now, or settle what nothing will finish."

    def add_arguments(self, parser):
        parser.add_argument("action", choices=["status", "start", "settle", "ensure", "plan", "recalibrate"])
        parser.add_argument("--user", default="1", help="the account whose Synapse Master it is")
        parser.add_argument("--mode", default="full", choices=list(nightly.MODES))
        parser.add_argument("--main", default="", help="recalibrate: main's unjudged passes (synapse_benchmark --json)")
        parser.add_argument("--old", default="", help="recalibrate: the last judged code's unjudged passes")
        parser.add_argument("--judged", default="", help="recalibrate: main's judged pass, when it had to be judged")
        parser.add_argument("--json", default="", help="plan, recalibrate: write the whole answer here as JSON")

    def handle(self, *args, **o):
        os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
        from rouh import reminders
        from rouh.tenancy import Tenancy

        who = Tenancy().identity_of(str(o["user"]))
        if who is None:
            raise CommandError(f"There is no account {o['user']}.")
        org, user = str(who.org_id), str(who.user_id)
        if o["action"] == "settle":
            got = improvements.settle(org, user, run_state=nightly.run_state)
            self.stdout.write(f"Settled: {', '.join(map(str, got)) or 'nothing'}.")
            return
        if o["action"] == "ensure":
            made = improvements.backfill(org, user)
            row = nightly.ensure(who)
            self.stdout.write(f"Backfilled {made} attempts; " + (f"scheduled as reminder {row.id}." if row is not None
                                                                 else "not scheduled: no Synapse Master."))
            return
        if o["action"] == "plan":
            got = recalibrate.plan(org, user)
            self._out(got, o["json"])
            self.stdout.write(got["words"])
            return
        if o["action"] == "recalibrate":
            if not o["main"]:
                raise CommandError("recalibrate needs --main: main's unjudged passes, from synapse_benchmark run --json.")
            judged = recalibrate.passes_of(o["judged"]) if o["judged"] else []
            if len(judged) > 1:
                raise CommandError("--judged holds one judged pass of main.")
            try:
                got = recalibrate.decide(org, user, main=recalibrate.passes_of(o["main"]),
                                         old=recalibrate.passes_of(o["old"]) if o["old"] else None,
                                         judged=judged[0] if judged else None)
            except ValueError as exc:
                raise CommandError(str(exc)) from None
            self._out(got, o["json"])
            self.stdout.write(f"{got['verdict']}: {got['words']}")
            return
        if o["action"] == "status":
            row = reminders.server_row(who, nightly.JOB)
            if row is None:
                self.stdout.write("Not scheduled: Rouh schedules it at start-up for everyone with a Synapse Master.")
            else:
                v = reminders.view(row)
                self.stdout.write(f"Reminder {row.id}: {v['repeats']}, {v['state']}, next {v['when'] or '-'}; "
                                  f"last time: {v['last_said'] or 'never'}")
            for r in improvements.listing(org, user, 5):
                self.stdout.write("  " + improvements.summary_line(r))
            return
        from rouh.config import config
        from rouh.one_client import OneClient

        nightly.ensure(who)
        got = asyncio.run(nightly.start(who, mode=o["mode"], cfg=config, crew=None, one=OneClient(),
                                        run_state=nightly.run_state))
        self.stdout.write(improvements.summary_line(got) + (f" (run {got['run_id']})" if got.get("run_id") else ""))
        if got.get("outcome") == "failed":
            raise CommandError(got.get("conclusion") or "It could not start.")

    def _out(self, got: dict, path: str) -> None:
        if path:
            with open(path, "w") as fh:
                json.dump(got, fh, ensure_ascii=False, indent=1, default=str)
            self.stdout.write(f"Written to {path}")
