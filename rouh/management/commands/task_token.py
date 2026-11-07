"""``python manage.py task_token``: the keys that let `rouh-task` reach Rouh from elsewhere.

A task's status and summary are kept in Rouh's database and nowhere else (`rouh/taskrecord.py`).
On this machine `rouh-task` reaches Rouh directly; anywhere else - another computer, with a copy of
the workspace of its own - it needs Rouh's address and a
key, which this makes. The key is shown once and only its hash is kept. It opens `/api/task`
and nothing else.

    python manage.py task_token add --user alex --name desk
    python manage.py task_token list
    python manage.py task_token revoke --user alex --name desk

Put what `add` prints into ``~/.config/rouh/task.json`` on that computer, as `rouh-task` says:
``{"url": "https://rouh.example.com", "token": "rouh_task_..."}``.
"""
from __future__ import annotations

import time

from django.core.management.base import BaseCommand, CommandError

from rouh import taskrecord


class Command(BaseCommand):
    help = "Make, list or revoke the keys bin/task uses to reach Rouh from elsewhere."

    def add_arguments(self, parser):
        parser.add_argument("action", choices=("add", "list", "revoke"))
        parser.add_argument("--user", default="", help="the account the key acts as")
        parser.add_argument("--name", default="", help="where it lives, such as laptop")

    def handle(self, *args, action="list", user="", name="", **options):
        from rouh.models import TaskToken, User

        if action == "list":
            rows = TaskToken.objects.order_by("created_at")
            names = dict(User.objects.values_list("id", "username"))
            for row in rows:
                state = ("revoked " + time.strftime("%Y-%m-%d", time.localtime(row.revoked_at))
                         if row.revoked_at else "live")
                used = (time.strftime("%Y-%m-%d %H:%M", time.localtime(row.last_used_at))
                        if row.last_used_at else "never")
                self.stdout.write(f"{names.get(int(row.user_id), row.user_id)}\t{row.name}\t"
                                  f"{state}\tlast used {used}")
            if not rows:
                self.stdout.write("no keys")
            return
        account = User.objects.filter(username=user).first() if user else None
        if account is None:
            raise CommandError("Say whose key it is with --user, by their username.")
        try:
            if action == "add":
                raw = taskrecord.make_token(str(account.id), str(account.org_id or ""), name)
                self.stdout.write(raw)
                self.stderr.write("Shown once. Put it in ~/.config/rouh/task.json on the machine "
                                  'that uses it: {"url": "<Rouh\'s address>", "token": "<this>"}')
                return
            gone = taskrecord.revoke_token(str(account.id), name)
        except taskrecord.Refused as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(f"revoked {gone} key(s)")
