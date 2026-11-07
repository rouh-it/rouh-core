"""``python manage.py job_watch``: whether each of Rouh's scheduled jobs really ran and worked
last time (`rouh/job_watch.py`), one line a job.

    python manage.py job_watch            the owner's jobs, checked now
    python manage.py job_watch --json     the same, as JSON

In the containers, from the machine: docker compose exec core python manage.py job_watch
"""
from __future__ import annotations

import json
import os

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Whether each of Rouh's scheduled jobs really ran and worked last time."

    def add_arguments(self, parser):
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **opts):
        os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
        from rouh import job_watch, telegram
        from rouh.tenancy import Tenancy

        owner = telegram.phone_owner(Tenancy())
        if owner is None:
            raise CommandError("This Rouh has no owner yet, so it has no scheduled jobs.")
        got = job_watch.check(owner)
        if opts["json"]:
            self.stdout.write(json.dumps(got, indent=2))
            return
        for j in got["jobs"]:
            mark = {True: "ok  ", False: "FAIL", None: "--  "}[j["ok"]]
            self.stdout.write(f"{mark} {j['title']}" + (f": {j['why']}" if j["why"] else "")
                              + (f" (last started {j['last_at']})" if j["last_at"] else ""))
        self.stdout.write(got["human"])
