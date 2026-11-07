"""``python manage.py task_origin``: who made each task (`rouh/task_origin.py`).

    python manage.py task_origin list          every task made for somebody else or by one of
                                               Rouh's processes, and every one the owner said is
                                               their own, with why
    python manage.py task_origin log           every change, from `task_change`, oldest first
    python manage.py task_origin sweep         mark the tasks made for somebody else that are
                                               not marked yet (Rouh does this by itself, at its
                                               start and as tasks come in)
    python manage.py task_origin backfill      what each task's record says made it, as a dry
                                               run: counts by origin, and each one it would mark
    python manage.py task_origin backfill --write   the same, written
    python manage.py task_origin mine 90       the owner's own task
    python manage.py task_origin theirs 90     made for somebody else
    python manage.py task_origin rouhs 90      made by one of Rouh's processes
"""
from __future__ import annotations

import json
import time

from django.core.management.base import BaseCommand, CommandError

from rouh import task_origin


class Command(BaseCommand):
    help = "List, log, sweep, backfill or set who made each task."

    def add_arguments(self, parser):
        parser.add_argument("action", choices=("list", "log", "sweep", "backfill", "mine", "theirs",
                                               "rouhs"))
        parser.add_argument("task", nargs="?", default="",
                            help="a task's number, for mine, theirs or rouhs")
        parser.add_argument("--write", action="store_true",
                            help="with backfill: write what it found, rather than only say it")

    def handle(self, *args, action="list", task="", write=False, **options):
        from rouh.models import Task, TaskChange

        if action == "list":
            rows = Task.objects.exclude(origin={}).order_by("number", "folder")
            for row in rows:
                o = row.origin or {}
                said = ("the owner's own, they said so" if task_origin.mine(o) else
                        f"{task_origin.words(o)}{' <' + o['email'] + '>' if o.get('email') else ''}"
                        f" - {o.get('why') or ''} (by {o.get('by') or '?'})")
                self.stdout.write(f"{row.number if row.number is not None else '-'}\t{row.folder}\t{said}")
            if not rows:
                self.stdout.write("Nothing is said about any task: every one is the owner's own.")
            return
        if action == "log":
            for ch in TaskChange.objects.filter(field="origin").order_by("at"):
                when = time.strftime("%Y-%m-%d %H:%M", time.localtime(ch.at))
                new = json.loads(ch.new or "{}")
                folder = Task.objects.filter(id=ch.task_id).values_list("folder", flat=True).first()
                whose = "the owner's own" if task_origin.mine(new) else task_origin.words(new)
                self.stdout.write(f"{when}\t{folder or ch.task_id}\t{ch.by}\t{whose}")
            return
        if action == "sweep":
            done = task_origin.sweep()
            for line in done:
                self.stdout.write(line)
            self.stdout.write(f"{len(done)} marked.")
            return
        if action == "backfill":
            got = task_origin.backfill(write=write)
            for line in got["marked"]:
                self.stdout.write(line)
            self.stdout.write(("Marked " if write else "Would mark ") + f"{len(got['marked'])}. "
                              + ("Afterwards: " if write else "Would be afterwards: ")
                              + ", ".join(f"{k} {v}" for k, v in got["counts"].items()) + ".")
            return
        if not task.isdigit():
            raise CommandError("Say which task, by its number.")
        row = Task.objects.filter(number=int(task)).values_list("id", flat=True).first()
        if row is None:
            raise CommandError(f"There is no task {task}.")
        to = {"mine": "person", "theirs": "other", "rouhs": "process"}[action]
        got = task_origin.set_by_person(row, to)
        self.stdout.write(got.get("did") or got.get("why") or "")
