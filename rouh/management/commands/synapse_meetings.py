"""``python manage.py synapse_meetings``: the meeting library kept in Synapse Master (`rouh/synapse/meetings.py`).

    python manage.py synapse_meetings status          # settings present (never their values), kept, queued, lately
    python manage.py synapse_meetings poll            # read the library's changes now, and the meetings due
    python manage.py synapse_meetings backfill        # every meeting the library holds, read now (again with --again)
    python manage.py synapse_meetings check           # every meeting's revision against Synapse's, now
    python manage.py synapse_meetings sync 42         # read meeting 42 again now, whatever its revision
    python manage.py synapse_meetings drain           # run the queue until nothing is due, then wait for the X-rays

Rouh does all of this by itself; these are for looking and for doing it now. On the server, run it with
Rouh's environment, as Rouh's other commands are run (README).
"""
from __future__ import annotations

import json
import time

from django.core.management.base import BaseCommand, CommandError

from rouh.synapse import db, meetings, master


class Command(BaseCommand):
    help = "The meeting library kept in Synapse Master: where it stands, or read it now."

    def add_arguments(self, parser):
        parser.add_argument("action", choices=["status", "poll", "backfill", "check", "sync", "drain"])
        parser.add_argument("meeting", nargs="?", default="")
        parser.add_argument("--user", default=meetings.OWNER_USER)
        parser.add_argument("--org", default="")
        parser.add_argument("--again", action="store_true", help="With backfill: list everything again from the start.")
        parser.add_argument("--wait", type=int, default=0, help="With drain: wait this many seconds at most for the "
                                                                "model's part of what was stored.")

    def handle(self, *args, **o):
        from rouh.models.accounts import User

        user = User.objects.filter(id=o["user"]).first()
        if user is None:
            raise CommandError(f"There is no account {o['user']}.")
        ds = master.of(o["org"] or str(user.org_id or "org-default"), str(user.id))
        if not ds:
            raise CommandError("There is no Synapse Master for that account yet.")
        meetings.ensure()
        row = meetings.row_of(ds["id"])
        if row is None:
            raise CommandError("That Master does not keep the meeting library (synapse.meeting_sync has no row for it).")
        act = o["action"]
        if act != "status" and meetings.off_words():
            raise CommandError(meetings.off_words())
        if act == "poll":
            self.stdout.write(json.dumps(meetings.beat_one(ds, row, force_poll=True), default=str))
        elif act == "backfill":
            if o["again"]:
                meetings._set(ds["id"], backfill_state="", backfill_offset=0)
                row = meetings.row_of(ds["id"])
            self.stdout.write(json.dumps(meetings.backfill(ds, row), default=str))
        elif act == "check":
            self.stdout.write(json.dumps(meetings.check(ds, by="command"), default=str))
        elif act == "sync":
            if not o["meeting"]:
                raise CommandError("Which meeting? Give its number in the library.")
            meetings.queue_now(ds["id"], o["meeting"], by="command")
            q = db.row("SELECT * FROM synapse.meeting_queue WHERE dataset_id = %s AND meeting_id = %s",
                       (str(ds["id"]), o["meeting"]))
            self.stdout.write(json.dumps(meetings.process_one(ds, q), default=str))
        elif act == "drain":
            began = time.time()
            while True:
                got = meetings.process_due(ds, most=50)
                self.stdout.write(json.dumps(got))
                if not got["more"]:
                    break
            while o["wait"] and time.time() - began < o["wait"]:
                left = db.value("SELECT count(*) FROM synapse.job j JOIN synapse.item i ON i.id = j.item_id WHERE "
                                "j.dataset_id = %s AND j.done_at IS NULL AND i.source = %s", (str(ds["id"]),
                                                                                             meetings.SOURCE))
                if not left:
                    break
                self.stdout.write(f"{left} model parts of meetings still on the queue")
                time.sleep(10)
        h = meetings.health(ds["id"]) or {}
        self.stdout.write(f"Settings: {'present' if h.get('on') else 'missing ' + ', '.join(h.get('missing') or [])} "
                          f"({h.get('file')}); library {h.get('library') or '-'}; webhook {h.get('webhook')}")
        if h.get("why_off"):
            self.stdout.write(h["why_off"])
        self.stdout.write(f"Kept: {h.get('meetings')} meetings ({h.get('read_by_model')} X-rayed), {h.get('passages')} "
                          f"transcript passages ({h.get('passages_embedded')} embedded); in step {h.get('in_sync')}, "
                          f"behind {h.get('behind')}, new waiting {h.get('new_waiting')}")
        self.stdout.write(f"Backfill: {h.get('backfill_state')} {json.dumps(h.get('backfill') or {}, default=str)}; "
                          f"last poll {h.get('last_poll_ok_at') or 'never'} (change {h.get('since_seq')}); last webhook "
                          f"{h.get('last_event_at') or 'never'}; last check {h.get('last_check_at') or 'never'}")
        cost = h.get("cost") or {}
        self.stdout.write(f"Cost: {cost.get('stores')} meetings brought in for ${cost.get('stores_usd', 0):.4f} "
                          f"(${cost.get('per_meeting', 0):.4f} each); {cost.get('edits')} updates for "
                          f"${cost.get('edits_usd', 0):.4f}")
        if h.get("error"):
            self.stdout.write(f"Error: {h['error']}")
        for r in (h.get("recent") or [])[:10]:
            self.stdout.write(f"- {r.get('at')}: {r.get('said')}")
