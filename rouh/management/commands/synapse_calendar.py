"""``python manage.py synapse_calendar``: every calendar event kept in Synapse Master (`rouh/synapse/calsync.py`).

    python manage.py synapse_calendar status            # each calendar: state, kept, last read, last check
    python manage.py synapse_calendar sync              # find calendars and read each one now
    python manage.py synapse_calendar reconcile         # each calendar's whole list against Synapse's, fixed

Rouh itself reads every calendar every minute and checks each one every night; these are for looking and
for doing it now. On the server, run it with Rouh's environment, as Rouh's other commands are run (README).
"""
from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from rouh.synapse import calsync, datasets, master


class Command(BaseCommand):
    help = "Calendar events kept in Synapse Master: where each calendar stands, or read or check them now."

    def add_arguments(self, parser):
        parser.add_argument("action", choices=["status", "sync", "reconcile"])
        parser.add_argument("--user", default="1")
        parser.add_argument("--org", default="")

    def handle(self, *args, **o):
        from rouh.models.accounts import User

        user = User.objects.filter(id=o["user"]).first()
        if user is None:
            raise CommandError(f"There is no account {o['user']}.")
        ds = master.of(o["org"] or str(user.org_id or "org-default"), str(user.id))
        if not ds:
            raise CommandError("There is no Synapse Master for that account yet.")
        if o["action"] == "sync":
            self.stdout.write(json.dumps({"discover": calsync.discover(ds, force=True)}, default=str))
            for row in calsync.rows(ds["id"]):
                got = calsync.beat_one(datasets.by_id(row["dataset_id"]) or ds, row)
                self.stdout.write(f"{row['name']}: {json.dumps(got, default=str)}")
        elif o["action"] == "reconcile":
            for row in calsync.rows(ds["id"]):
                if row["state"] == "synced":
                    self.stdout.write(f"{row['name']}: {json.dumps(calsync.reconcile(ds, row, by='command'), default=str)}")
        for h in calsync.health(ds["id"]):
            self.stdout.write(f"- {h['calendar']}: {h['state']}{' (stopped)' if not h['enabled'] else ''}, "
                              f"{h['kept']} kept, {h['read_by_model']} read, last read "
                              f"{h['last_ok_at'] or 'never'}{', ' + h['error'] if h['error'] else ''}")
