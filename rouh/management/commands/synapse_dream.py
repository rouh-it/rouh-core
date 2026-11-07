"""``python manage.py synapse_dream``: a night of dreaming, by hand (`rouh/synapse/dreaming.py`).

    python manage.py synapse_dream status                    # the nights of Synapse Master, newest first, and
                                                             # its schedule
    python manage.py synapse_dream run                       # a night on Synapse Master now, here, to its end
    python manage.py synapse_dream run --hold                # the same, applying nothing: every change waits
    python manage.py synapse_dream run --dataset <id>        # on another dataset of the same account
    python manage.py synapse_dream show 3                    # night 3 whole, as synapse_dream reads it
    python manage.py synapse_dream undo 3                    # every change night 3 applied, put back
    python manage.py synapse_dream schedule on|off           # the 04:00 row on the Reminders page, resumed or
                                                             # paused (made paused first if there is none)
    python manage.py synapse_dream examples --dataset <id>   # an example set's dream examples, if it lacks them

Rouh starts a night by itself at 04:00 on the person's clock once the schedule is on; this is for running one
now, reading it, and turning the schedule on after the evaluation gate. On the server, with Rouh's environment:
``deploy/with-rouh-env.sh <checkout> /var/www/rouh/.venv/bin/python manage.py synapse_dream status``
In the containers, from the machine: ``docker compose exec core python manage.py synapse_dream ...`` (a run in the
worker cannot reach the database: `deploy/with-rouh-env.sh` says so and stops).
"""
from __future__ import annotations

import os

from django.core.management.base import BaseCommand, CommandError

from rouh.synapse import datasets, db, dreaming, master, search


class Command(BaseCommand):
    help = "Dreaming over Synapse: run a night now, read one, undo one, or turn the nightly schedule on or off."

    def add_arguments(self, parser):
        parser.add_argument("action", choices=["status", "run", "show", "undo", "schedule", "examples"])
        parser.add_argument("what", nargs="?", default="", help="a night's number, or on/off for schedule")
        parser.add_argument("--user", default="1", help="the account whose Synapse it is")
        parser.add_argument("--dataset", default="", help="a dataset of that account; Synapse Master when left out")
        parser.add_argument("--hold", action="store_true", help="apply nothing: every change waits for Approve")

    def handle(self, *args, **o):
        os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
        from rouh.tenancy import Tenancy

        who = Tenancy().identity_of(str(o["user"]))
        if who is None:
            raise CommandError(f"There is no account {o['user']}.")
        if not dreaming.ready():
            raise CommandError("Dreaming's tables are not in this database yet (migration 0089).")
        ds = datasets.mine(o["dataset"], who) if o["dataset"] else master.of(str(who.org_id), str(who.user_id))
        if ds is None:
            raise CommandError("There is no such dataset for that account.")
        viewer = search.readers_for(datasets.me(ds))
        action = o["action"]
        if action == "schedule":
            from rouh import reminders

            if o["what"] not in ("on", "off"):
                raise CommandError("schedule on, or schedule off")
            row = dreaming.ensure(who)
            if row is None:
                raise CommandError("Not scheduled: there is no Synapse Master.")
            reminders.change(who, row.id, state="on" if o["what"] == "on" else "paused")
            v = dreaming.schedule(who)
            self.stdout.write(f"Reminder {v['id']}: {v['repeats']}, {v['state']}, next {v['when'] or '-'}.")
            return
        if action == "examples":
            from rouh.synapse import seeds

            got = seeds.add_dream_examples(ds)
            if not got.get("ok"):
                raise CommandError(got["why"])
            # Rouh's own worker stores them; a command never starts a worker of its own.
            self.stdout.write(f"Queued the dream examples for {ds['name']}: "
                              f"{seeds.dream_examples_missing(ds)} items, stored by Rouh's worker.")
            return
        if action == "status":
            got = dreaming.listing(ds, viewer)
            v = dreaming.schedule(who) if ds.get("master") else None
            self.stdout.write(f"{ds['name']}: " + (f"schedule {v['state']}, {v['repeats']}, next {v['when'] or '-'}"
                                                   if v else "no schedule") + f"; {got['waiting']} changes wait.")
            self.stdout.write(f"Health now: {got['health_now']}")
            for n in got["nights"][:10]:
                self.stdout.write(f"  night {n['number']} ({n['status']}, {n['by']}, ${float(n['cost_usd'] or 0):.4f}): "
                                  f"{n['summary'] or n['stopped_why'] or n['stage']}")
            return
        if action == "run":
            got = dreaming.run(ds, by=o["what"] or "command", hold=o["hold"])
            self.stdout.write(dreaming.tool(ds, {"action": "read", "night": str(got.get("number") or "latest")}))
            if got.get("status") == "failed":
                raise CommandError(got.get("stopped_why") or "It failed.")
            return
        number = o["what"] or str(db.value("SELECT max(number) FROM synapse.dream WHERE dataset_id = %s", (ds["id"],)) or "")
        if not number:
            raise CommandError("It has never been dreamed over.")
        if action == "show":
            self.stdout.write(dreaming.tool(ds, {"action": "read", "night": number}))
            return
        if action == "undo":
            got = dreaming.undo_night(ds, number, viewer, by="command")
            if not got.get("ok"):
                raise CommandError(got["why"])
            self.stdout.write(f"Night {number}: {got['undone']} changes put back, {got['withdrawn']} waiting ones withdrawn.")
