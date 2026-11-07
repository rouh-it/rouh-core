"""``python manage.py rule_defaults``: the defaults every Rouh starts with (`rouh/ruledefaults.py`).

    python manage.py rule_defaults                      # what is in use, and what the last fetch said
    python manage.py rule_defaults fetch                # fetch them from rouh.land now
    python manage.py rule_defaults take --user 1        # take what is in use into that person's Master now
    python manage.py rule_defaults export --user 1 > defaults.json
        # the document of that person's rules tagged "defaults", for rouh.land to publish

To publish: export from the Rouh that sets them, copy the file to the site as rules/defaults.json, and deploy
the site, as the model standard is published (README, "What a conversation is told").
On the server, run it with Rouh's environment, as Rouh's other commands are run (README).
"""
from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Say, fetch, take in or export the defaults every Rouh starts with."

    def add_arguments(self, parser):
        parser.add_argument("action", nargs="?", default="status", choices=["status", "fetch", "take", "export"])
        parser.add_argument("--user", default="1")
        parser.add_argument("--org", default="")
        parser.add_argument("--revision", default="")

    def handle(self, *args, **o):
        from rouh import ruledefaults, rules
        from rouh.config import config
        from rouh.models.accounts import User

        if o["action"] == "status":
            doc = ruledefaults.current()
            self.stdout.write(json.dumps({"in_use": doc["revision"], "from": doc["source"], "rules": len(doc["rules"]),
                                          "last_fetch": ruledefaults.fetched_said()}, indent=1))
            return
        if o["action"] == "fetch":
            self.stdout.write(json.dumps(ruledefaults.fetch(config), indent=1))
            return
        user = User.objects.filter(id=o["user"]).first()
        if user is None:
            raise CommandError(f"There is no account {o['user']}.")
        ds = rules.master(str(user.id), o["org"] or str(user.org_id or "org-default"))
        if o["action"] == "take":
            self.stdout.write(json.dumps(ruledefaults.take(ds, ruledefaults.current())))
            return
        self.stdout.write(json.dumps(ruledefaults.export(ds, revision=o["revision"]), indent=1, ensure_ascii=False))
