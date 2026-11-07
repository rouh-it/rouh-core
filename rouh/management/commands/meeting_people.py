"""``python manage.py meeting_people``: the guests of the coming meetings, looked up on LinkedIn
(`rouh/meeting_people.py`).

    python manage.py meeting_people status              # the switch, today's spend, the last calls
    python manage.py meeting_people run                 # the pass now, over the next week's meetings
    python manage.py meeting_people run --dry-run       # who it would look up, and nothing spent
    python manage.py meeting_people run --event ID      # one meeting, by its event id, past or coming
    python manage.py meeting_people meeting --event ID  # what is kept on each guest of one meeting

Rouh runs the pass by itself every hour and soon after the calendar changes; these are for looking
and for doing it now. On the server, run it with Rouh's environment, as Rouh's other commands are
run (README). Every LinkedIn lookup is counted against the same daily limit as Rouh's own.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import datetime, timedelta, timezone

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "The guests of the coming meetings, looked up on LinkedIn: where it stands, or the pass now."

    def add_arguments(self, parser):
        parser.add_argument("action", choices=["status", "run", "meeting"])
        parser.add_argument("--user", default="1", help="the account's id or username")
        parser.add_argument("--event", default="", help="one event id, as the calendar gives it")
        parser.add_argument("--calendar", default="", help="the calendar the event is on")
        parser.add_argument("--days", type=float, default=0, help="how many days ahead, default 7")
        parser.add_argument("--dry-run", action="store_true", help="say who would be looked up")
        parser.add_argument("--limit", type=int, default=None,
                            help="the most HarvestAPI runs today, instead of the daily limit")

    def handle(self, *args, **o):
        from rouh import meeting_people, switches
        from rouh.models.accounts import User
        from rouh.tenancy import Identity, Tenancy

        os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
        said = str(o["user"])
        user = (User.objects.filter(id=said).first() if said.isdigit()
                else User.objects.filter(username=said).first())
        if user is None:
            raise CommandError(f"There is no account {said}.")
        who = Tenancy().identity_of(str(user.id)) or Identity(user_id=str(user.id),
                                                               org_id=str(user.org_id))
        if o["action"] == "status":
            spent = meeting_people.spent_today(who)
            self.stdout.write(f"switch {meeting_people.SWITCH}: "
                              f"{'on' if switches.on(meeting_people.SWITCH, str(who.org_id)) else 'off'}")
            self.stdout.write(f"today ({spent['day']}): {spent['calls']} of {spent['most']} HarvestAPI runs, "
                              f"${spent['cost']:.3f}")
            for entry in (meeting_people._setting(who, meeting_people.CALLS).get("log") or [])[-15:]:
                when = datetime.fromtimestamp(entry["at"], timezone.utc).strftime("%Y-%m-%d %H:%M")
                self.stdout.write(f"  {when} {entry['runs']} x {entry['actor']} ${entry['cost']:.3f} "
                                  f"{entry['name']}: {entry['why']}")
            return
        self.stdout.write(json.dumps(asyncio.run(self._run(who, o)), indent=1, default=str))

    async def _run(self, who, o) -> dict:
        from rouh import clock, linkedin, meeting_people
        from rouh.config import config
        from rouh.encryption import SecretBox
        from rouh.google_api import GoogleClients
        from rouh.google_oauth import GoogleAuth
        from rouh.google_store import GoogleStore
        from rouh.tenancy import speaking

        box = SecretBox(config.encryption_key, data_dir=config.data_dir)
        clients = GoogleClients(GoogleAuth(GoogleStore(None, box), config), config)
        apify = linkedin.Apify(config.apify_api_token, config.apify_url) if config.apify_api_token else None
        with speaking(who), clock.person(who, clock.zone_of(who)):
            calendar = clients.for_user(who).calendar
            events = None
            if o["event"]:
                where = await calendar.find_event(o["event"], o["calendar"])
                events = [await calendar.event(where, o["event"])]
            if o["action"] == "meeting":
                if not events:
                    raise CommandError("Say which meeting with --event.")
                people = await asyncio.to_thread(meeting_people.attendee_view, who, events[0])
                return {"meeting": events[0]["title"], "start": events[0]["start"],
                        "guests": people}
            start = datetime.now(timezone.utc)
            end = start + timedelta(days=o["days"] or meeting_people.DAYS)
            began = time.time()
            report = await meeting_people.run(who, calendar=calendar, apify=apify, start=start, end=end,
                                              events=events, most=o["limit"], dry=o["dry_run"])
            return {"said": report.said(), "seconds": round(time.time() - began, 1),
                    "meetings": report.meetings, "guests": report.guests, "passed": report.passed,
                    "left": report.left, "large": report.large, "calls": report.calls,
                    "cost": report.cost,
                    "done": report.done}
