"""``python manage.py synapse_mail``: Gmail kept in Synapse Master (`rouh/synapse/gmailsync.py`).

    python manage.py synapse_mail status                      # each inbox's sync: history, backfill, queue, failures
    python manage.py synapse_mail status --json               # the same, whole
    python manage.py synapse_mail add alex@example.com --user 1  # keep another inbox (Rouh's own: add rouh)
    python manage.py synapse_mail remove alex@example.com      # stop keeping one; what is stored stays
    python manage.py synapse_mail read                        # read every inbox's Gmail history now
    python manage.py synapse_mail reconcile --inbox rouh@example.com [--wait 600] [--quiet]
                                                              # Gmail's whole list against Synapse's, fixed;
                                                              # --quiet sends no Telegram note
    python manage.py synapse_mail count --inbox rouh@example.com
                                                              # the two counts only, nothing changed

Rouh itself reads every inbox every minute and on Gmail's push, and checks each one every night;
these are for looking and for doing it now. `--user` names whose Synapse Master it is; left out, it
is the installation's one account, and with more than one it has to be given. On the server, run it with Rouh's environment, as
Rouh's other commands are run (README).
"""
from __future__ import annotations

import json
import os

from django.core.management.base import BaseCommand, CommandError

from rouh.synapse import gmailsync, master


def _when(v) -> str:
    return v.astimezone().strftime("%d %b %H:%M:%S") if v else "never"


class Command(BaseCommand):
    help = "Gmail kept in Synapse Master: where each inbox stands, add or stop one, read or check it now."

    def add_arguments(self, parser):
        parser.add_argument("action", choices=["status", "add", "remove", "read", "reconcile", "count"])
        parser.add_argument("address", nargs="?", default="", help="add/remove: the inbox ('rouh' for Rouh's own)")
        parser.add_argument("--inbox", default="", help="reconcile/count: the inbox; every kept one when left out")
        parser.add_argument("--user", default="",
                            help="the account whose Synapse Master it is, by id; the installation's "
                                 "one account when left out")
        parser.add_argument("--org", default="", help="the organisation; the account's own when left out")
        parser.add_argument("--wait", type=float, default=None, help="reconcile: seconds to wait for its fixes")
        parser.add_argument("--quiet", action="store_true", help="reconcile: no Telegram note whatever it finds")
        parser.add_argument("--json", action="store_true", help="status: everything, as JSON")

    def handle(self, *args, **o):
        os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
        o["user"] = str(o["user"] or "").strip() or self._only_account()
        org = o["org"] or self._org_of(o["user"])
        ds = master.of(org, o["user"])
        if not ds:
            raise CommandError("There is no Synapse Master for that account yet: manage.py synapse_master make.")
        if o["action"] == "status":
            got = gmailsync.health(ds["id"])
            if o["json"]:
                self.stdout.write(json.dumps(got, indent=1, default=str))
                return
            if not got:
                self.stdout.write("No inbox is kept in Synapse Master. Add one with: synapse_mail add rouh")
            for x in got:
                self._say(x)
            return
        if o["action"] == "add":
            try:
                got = gmailsync.add(ds, o["address"], by="command")
            except ValueError as exc:
                raise CommandError(str(exc)) from None
            self.stdout.write(f"Kept now: {got['inbox']} ({got['kind']}). Rouh reads it within a minute; the "
                              "backfill of everything in it starts then.")
            return
        if o["action"] == "remove":
            n = gmailsync.remove(ds, o["address"])
            self.stdout.write("Stopped. What is stored stays." if n else "That inbox was not kept.")
            return
        wanted = gmailsync.clean_inbox(o["inbox"])
        kept = [r for r in gmailsync.rows() if str(r["dataset_id"]) == str(ds["id"])
                and (not wanted or r["inbox"] == wanted)]
        if not kept:
            raise CommandError("No such inbox is kept in that Synapse Master.")
        for row in kept:
            if o["action"] == "read":
                self.stdout.write(f"{row['inbox']}: {json.dumps(gmailsync.beat_one(ds, row), default=str)}")
            elif o["action"] == "count":
                gmail, who = gmailsync._open(ds, row["inbox"])
                ids, drafts = gmailsync.gmail_ids(gmail, who)
                live, dead = gmailsync.synapse_ids(str(ds["id"]), row["inbox"])
                self.stdout.write(json.dumps({
                    "inbox": row["inbox"], "gmail_in_anywhere_without_drafts": len(ids), "drafts": len(drafts),
                    "synapse_emails": len(live), "deleted_in_synapse": len(dead),
                    "missing_from_synapse": len(ids - live - dead), "extra_in_synapse": len(live - ids)}))
            else:
                got = gmailsync.reconcile(ds, row["inbox"], wait=o["wait"], notify=not o["quiet"], by="command",
                                          on_progress=lambda n: self.stdout.write(f"  waiting for {n} jobs"))
                self.stdout.write(json.dumps(got, default=str))

    def _say(self, x: dict) -> None:
        b, it, w, r = x["backfill"], x["items"], x["watch"], x["reconcile"] or {}
        lines = [f"{x['inbox']}: {'stopped' if not x['enabled'] else 'STALE: ' + x['flag'] if x['stale'] else 'in step'}",
                 f"  last history read  {_when(x['last_history_ok_at'])} {json.dumps(x['last_history_counts'])}",
                 f"  last push          {_when(x['last_push_at'])}",
                 f"  read to history id {x['history_id'] or '-'}",
                 f"  backfill           {b['state']}, {b['listed']} listed, done: {b['done']}"
                 + (f", error: {b['error']}" if b["error"] else ""),
                 f"  kept               {it.get('mail', 0)} emails {json.dumps(x['folders'])}, {it.get('files', 0)} files, "
                 f"{it.get('deleted', 0)} deleted, {it.get('read_by_model', 0)} read by the model",
                 f"  waiting            {json.dumps(x['jobs'])} jobs, {x['model_parts_waiting']} model parts",
                 f"  failures           {x['retrying']} being retried, {x['failed_7d']} failed in 7 days"
                 + (f" (last: {x['last_failure']})" if x["last_failure"] else "")
                 + (f"; history not read {x['history_failures']} times running: {x['history_error']}"
                    if x["history_failures"] else ""),
                 f"  gmail's push       {w['by'] or '-'} until {_when(w['expires_at'])}" + (f" ({w['error']})" if w["error"] else ""),
                 f"  last reconcile     {_when(x['last_reconcile_at'])} "
                 + json.dumps({k: v for k, v in r.items() if k != "examples"}),
                 f"  cost so far        ${x['cost_usd']:.4f}"]
        self.stdout.write("\n".join(lines))

    @staticmethod
    def _only_account() -> str:
        from rouh.tenancy import Tenancy

        who = Tenancy().only_person()
        if who is None:
            raise CommandError("Whose Synapse Master? Give --user: this installation has more than one "
                               "account, or none.")
        return str(who.user_id)

    @staticmethod
    def _org_of(user_id: str) -> str:
        from rouh.models.accounts import User

        user = User.objects.filter(id=user_id).first()
        if user is None:
            raise CommandError(f"There is no account {user_id}.")
        return str(user.org_id or "org-default")
