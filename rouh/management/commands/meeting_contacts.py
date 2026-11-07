"""``python manage.py meeting_contacts``: the guests of his meetings, added to his iCloud contacts
(`rouh/meeting_contacts.py`).

    python manage.py meeting_contacts status                 # the switch, the backfill, the last passes
    python manage.py meeting_contacts backfill --dry-run     # who the last year's meetings would add
    python manage.py meeting_contacts backfill               # the once-only pass over the last year
    python manage.py meeting_contacts run [--dry-run]        # the pass Rouh runs by itself, now
    python manage.py meeting_contacts research --most 5      # the next five of the LinkedIn queue, now

Rouh runs the pass by itself every hour and soon after the calendar changes, and the backfill the
first time; these are for looking and for doing it now. On the server, run it with Rouh's
environment, as Rouh's other commands are run (README).
"""
from __future__ import annotations

import asyncio
import json
import os
import time

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "The guests of his meetings, added to his iCloud contacts: where it stands, or the pass now."

    def add_arguments(self, parser):
        parser.add_argument("action", choices=["status", "run", "backfill", "research"])
        parser.add_argument("--user", default="1", help="the account's id or username")
        parser.add_argument("--dry-run", action="store_true", help="say who would be added, and add nobody")
        parser.add_argument("--most", type=int, default=None,
                            help="add at most this many, or look up at most this many on LinkedIn")
        parser.add_argument("--gap", type=float, default=None,
                            help="seconds between one LinkedIn lookup and the next")

    def handle(self, *args, **o):
        from rouh import meeting_contacts
        from rouh.models.accounts import User
        from rouh.tenancy import Identity, Tenancy

        os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
        said = str(o["user"])
        user = (User.objects.filter(id=said).first() if said.isdigit()
                else User.objects.filter(username=said).first())
        if user is None:
            raise CommandError(f"There is no account {said}.")
        who = Tenancy().identity_of(str(user.id)) or Identity(user_id=str(user.id), org_id=str(user.org_id))
        if o["action"] == "status":
            self.stdout.write(json.dumps(meeting_contacts.status(who), indent=1, default=str))
            return
        self.stdout.write(json.dumps(asyncio.run(self._run(who, o)), indent=1, default=str, ensure_ascii=False))

    async def _run(self, who, o) -> dict:
        from rouh import clock, meeting_contacts
        from rouh.apple_contacts import AppleStore, ContactDesk
        from rouh.config import config
        from rouh.encryption import SecretBox
        from rouh.google_api import GoogleClients
        from rouh.google_audit import WriteLog
        from rouh.google_oauth import GoogleAuth
        from rouh.google_store import GoogleStore
        from rouh.tenancy import Tenancy, speaking

        if o["action"] == "research":
            from rouh import linkedin

            apify = linkedin.Apify(getattr(config, "apify_api_token", "") or "",
                                   getattr(config, "apify_url", "") or linkedin.APIFY_URL)
            began = time.time()
            with speaking(who), clock.person(who, clock.zone_of(who)):
                queued = meeting_contacts.queue_backfill(who)
                got = await meeting_contacts.drain(who, apify, most=o["most"], gap=o["gap"])
            return {"queued": queued, **got, "seconds": round(time.time() - began, 1),
                    "now": meeting_contacts.research_status(who)}
        box = SecretBox(config.encryption_key, data_dir=config.data_dir)
        clients = GoogleClients(GoogleAuth(GoogleStore(None, box), config), config)
        desk = ContactDesk(Tenancy(), AppleStore(box), config,
                           audit=WriteLog(config.logs_path, name="contacts-writes.log"))
        with speaking(who), clock.person(who, clock.zone_of(who)):
            calendar = clients.for_user(who).calendar
            began = time.time()
            if o["action"] == "backfill":
                report = await meeting_contacts.backfill(who, calendar=calendar, desk=desk, dry=o["dry_run"],
                                                         most=o["most"])
            else:
                report = await meeting_contacts.run(who, calendar=calendar, desk=desk, dry=o["dry_run"],
                                                    most=o["most"], wait=True)
        return {"said": report.said(), "seconds": round(time.time() - began, 1),
                "calendars": meeting_contacts.calendar_ids(who), "meetings": report.meetings,
                "added": report.added, "would_add": report.would_add, "failed": report.failed,
                "meetings_skipped": report.meetings_skipped,
                "meetings_skipped_titles": report.meetings_skipped_titles,
                "guests_skipped": report.guests_skipped, "guests_skipped_who": report.guests_skipped_who}
