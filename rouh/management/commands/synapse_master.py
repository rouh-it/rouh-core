"""``python manage.py synapse_master``: each person's Synapse Master (`rouh/synapse/master.py`).

    python manage.py synapse_master status                 # whose master exists, how many people and tasks
    python manage.py synapse_master make --user 1          # a new, empty Synapse Master
    python manage.py synapse_master sync --user 1          # bring every task and everything in it in now
                                                           # (the worker does it every 10 min)
    python manage.py synapse_master sync --user 1 --only files   # one part: tasks, files, chats or cards
    python manage.py synapse_master contacts --user 1      # how many of its people are contacts, and what waits for iCloud
    python manage.py synapse_master remove --dataset <id>  # delete a lab dataset (never Master), as its Delete does
    python manage.py synapse_master false-rules --user 1   # rules made out of documents' content (D59), counted
    python manage.py synapse_master false-rules --user 1 --delete   # and deleted

On the server, run it with Rouh's environment, as Rouh's other commands are run (README).
"""
from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from rouh.synapse import db, master


class Command(BaseCommand):
    help = "Make Synapse Master, bring every task into it, say where its contacts stand, or delete a lab dataset."

    def add_arguments(self, parser):
        parser.add_argument("action", choices=["status", "make", "sync", "contacts", "remove", "false-rules"])
        parser.add_argument("--delete", action="store_true", help="false-rules: delete them, not only count them")
        parser.add_argument("--dataset", default="", help="remove: the dataset's id")
        parser.add_argument("--user", default="1", help="the account's id")
        parser.add_argument("--org", default="", help="the organisation; the account's own when left out")
        parser.add_argument("--limit", type=int, default=0, help="sync: at most this many of each (a first try)")
        parser.add_argument("--only", default="", choices=["", "tasks", "files", "chats", "cards"])

    def handle(self, *args, **o):
        org = o["org"] or self._org_of(o["user"])
        if o["action"] == "status":
            rows = db.rows("SELECT d.org_id, d.user_id, d.name, d.id, (SELECT count(*) FROM synapse.item i WHERE "
                           "i.dataset_id = d.id AND i.kind = 'person') AS people, (SELECT count(*) FROM synapse.item i "
                           "WHERE i.dataset_id = d.id AND i.source = %s AND i.deleted_at IS NULL) AS tasks, "
                           "(SELECT count(*) FROM synapse.item i WHERE i.dataset_id = d.id AND i.source IN "
                           "('rouh-file', 'rouh-chat', 'rouh-card') AND i.deleted_at IS NULL) AS inside, "
                           "(SELECT count(*) FROM synapse.job j WHERE j.dataset_id = d.id AND j.done_at IS NULL) AS queued "
                           "FROM synapse.dataset d WHERE d.master", (master.SOURCE,))
            self.stdout.write(json.dumps(rows, indent=1, default=str) if rows else "No Synapse Master yet.")
            return
        if o["action"] == "make":
            got = master.make(org, o["user"])
            ds = got["dataset"]
            self.stdout.write(f"{'Made' if got['made'] else 'Already there'}: {ds['name']} ({ds['id']}), "
                              f"{got['people']} people.")
            return
        if o["action"] == "contacts":
            ds = master.of(org, o["user"])
            if not ds:
                raise CommandError("There is no Synapse Master for that account yet: make it first.")
            self.stdout.write(json.dumps(db.row(
                "SELECT (SELECT count(*) FROM synapse.item WHERE dataset_id = %s AND kind = 'person' AND deleted_at IS NULL "
                "AND meta ? 'icloud') AS contacts, (SELECT count(*) FROM synapse.item WHERE dataset_id = %s AND kind = "
                "'person' AND deleted_at IS NULL) AS people, (SELECT count(*) FROM synapse.job WHERE dataset_id = %s AND "
                "kind LIKE 'icloud_%%' AND done_at IS NULL) AS waiting_for_icloud, (SELECT count(*) FROM synapse.job WHERE "
                "dataset_id = %s AND kind LIKE 'icloud_%%' AND error <> '') AS failed",
                (ds["id"],) * 4), default=str))
            return
        if o["action"] == "false-rules":
            from rouh.synapse import ingest

            ds = master.of(org, o["user"])
            if not ds:
                raise CommandError("There is no Synapse Master for that account yet.")
            # Rules made automatically out of what a task, a file, a card or a chat says (before 5 October 2026,
            # `ingest.write_rules`). The items they came from keep every word and every claim.
            rows = db.rows(
                "SELECT r.id, p.source FROM synapse.item r JOIN synapse.item p ON p.id::text = r.meta->>'made_from' "
                "WHERE r.dataset_id = %s AND r.kind = 'rule' AND r.deleted_at IS NULL AND p.source = ANY(%s)",
                (ds["id"], list(ingest.CONTENT_SOURCES + ingest.CHAT_SOURCES)))
            by: dict[str, int] = {}
            for r in rows:
                by[r["source"]] = by.get(r["source"], 0) + 1
            self.stdout.write(f"{len(rows)} rules made from content: {json.dumps(by)}")
            if o["delete"]:
                gone = sum(1 for r in rows if ingest.delete(ds, str(r["id"]), by="false-rules").get("ok"))
                self.stdout.write(f"Deleted {gone}.")
            return
        if o["action"] == "remove":
            from rouh.synapse import datasets

            ds = datasets.by_id(o["dataset"]) if o["dataset"] else None
            if not ds or str(ds["user_id"]) != str(o["user"]) or str(ds["org_id"]) != org:
                raise CommandError("There is no such dataset of that account's: --dataset <id>.")
            got = datasets.remove(ds)
            if got.get("refused"):
                raise CommandError(got["refused"])
            self.stdout.write(f"Deleted {ds['name']} ({ds['id']}): {json.dumps(got, default=str)}")
            return
        ds = master.of(org, o["user"])
        if not ds:
            raise CommandError("There is no Synapse Master for that account yet: make it first.")
        fn = {"tasks": master.sync_tasks, "files": master.sync_files, "chats": master.sync_chats,
              "cards": master.sync_cards}.get(o["only"], master.sync_everything)
        got = fn(ds, by="command", limit=o["limit"] or None)
        self.stdout.write(json.dumps(got))

    @staticmethod
    def _org_of(user_id: str) -> str:
        from rouh.models.accounts import User

        user = User.objects.filter(id=user_id).first()
        if user is None:
            raise CommandError(f"There is no account {user_id}.")
        return str(user.org_id or "org-default")
