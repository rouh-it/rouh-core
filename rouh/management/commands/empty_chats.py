"""``python manage.py empty_chats``: which chats have nothing in them, and why.

A report and nothing else. It lists every chat with no messages, split the way
the one clean-up split them (`rouh/emptychats.py`): the ones that are provably
an empty chat opening a task left behind, and every other one with the reasons
it is not that. It deletes nothing; the clean-up ran once, in the deploy, as
`rouh/migrations/0004_remove_empty_task_chats.py`, and a chat is otherwise
only ever deleted by a person.
"""
from __future__ import annotations

import json
from datetime import datetime

from django.apps import apps
from django.core.management.base import BaseCommand

from rouh import emptychats
from rouh.config import config


class Command(BaseCommand):
    help = "List the chats with nothing in them, and whether each is an empty task chat."

    def add_arguments(self, parser):
        parser.add_argument("--json", action="store_true", help="say it as JSON")

    def handle(self, *args, **options):
        found = emptychats.survey(lambda name: apps.get_model("rouh", name),
                                  data_dir=config.data_dir)
        if options.get("json"):
            self.stdout.write(json.dumps(found, indent=2, ensure_ascii=False))
            return
        for label, rows in (("empty task chats, which the clean-up takes away",
                             found["remove"]),
                            ("empty chats left alone", found["keep"])):
            self.stdout.write(f"{label}: {len(rows)}")
            for row in rows:
                made = datetime.fromtimestamp(row["created_at"]).strftime("%Y-%m-%d %H:%M")
                self.stdout.write(f"  {row['id']}  {made}  {row['title'] or '(untitled)'}"
                                  f"  under {row['owner'] or 'nothing'}"
                                  f"{' (' + row['owner_title'] + ')' if row['owner_title'] else ''}")
                if row["why"]:
                    self.stdout.write(f"      {row['why']}")
