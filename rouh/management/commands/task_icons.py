"""``python manage.py task_icons``: give every task and step its emoji (`rouh/taskicons.py`).

Rouh does this by itself for every task with none, the moment it starts and whenever a task is
made. This is for picking them again by hand:

    python manage.py task_icons            # every task with no icon yet
    python manage.py task_icons --all      # every task, over whatever icon each has
    python manage.py task_icons --guess    # without the model, from the titles' words alone

The emoji come from the model the Models page has for Task icons, and from the titles' words
where it cannot be asked.
"""
from __future__ import annotations

import asyncio

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Give every task and step an emoji in front of its title."

    def add_arguments(self, parser):
        parser.add_argument("--all", action="store_true", dest="every",
                            help="pick again for every task, over the icon each has")
        parser.add_argument("--guess", action="store_true",
                            help="from the titles' words alone, without asking a model")

    def handle(self, *args, every=False, guess=False, **options):
        from rouh import objects, taskicons

        if guess:
            store = objects.shared_store(even_when_off=True)
            written = 0
            for ident, title, _above in store.tasks_for_icons(every=every, limit=None):
                if store.set_task_icon(ident, taskicons.guess(title), only_if_none=not every,
                                       by=taskicons.BY):
                    written += 1
        else:
            written = asyncio.run(taskicons.fill(every=every))
        self.stdout.write(f"{written} task icon{'' if written == 1 else 's'} written")
