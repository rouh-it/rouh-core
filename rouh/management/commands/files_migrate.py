"""``python manage.py files_migrate``: move every file kept the old way into its home now.

Rouh does this by itself once, a little after it starts (`rouh/filestore.py`, `start`); this is the
same move, for whoever wants it done at once or wants to see the counts. Files are moved, never
copied, and a link is left at each old path.

    python manage.py files_migrate
    python manage.py files_migrate --empty-bin     and empty the bin of files past their days
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from rouh import filestore


class Command(BaseCommand):
    help = "Move files kept the old way into their chat's, task's or project's folder."

    def add_arguments(self, parser):
        parser.add_argument("--empty-bin", action="store_true")

    def handle(self, *args, **opts):
        done = filestore.migrate()
        self.stdout.write(f"Moved {done['moved']} files into {filestore.root()}; "
                          f"{done['failed']} could not be moved.")
        if opts["empty_bin"]:
            self.stdout.write(f"Emptied {filestore.empty_bin()} files from the bin.")
