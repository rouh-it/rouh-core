"""``python manage.py import_sqlite``: the data Rouh kept before PostgreSQL.

    manage.py import_sqlite                      the configured file, once
    manage.py import_sqlite --from <file>        another one
    manage.py import_sqlite --check              the whole move, then undone

`rouh/sqlite_import.py` is the whole of it and says what moves and what does
not. ``--check`` is how the move is proved against a copy of the real file
before the deploy does it for real: every row goes in, every constraint is
checked at the end, and then the transaction is rolled back.
"""
import json

from django.core.management.base import BaseCommand, CommandError

from rouh import sqlite_import
from rouh.config import config


class Command(BaseCommand):
    help = "Copy everything Rouh kept in SQLite into PostgreSQL, once."

    def add_arguments(self, parser):
        parser.add_argument("--from", dest="source", default="",
                            help="the SQLite file; the data directory's own by default")
        parser.add_argument("--check", action="store_true",
                            help="do the whole move and then undo it")

    def handle(self, *args, source="", check=False, **options):
        path = source or config.legacy_sqlite_path
        if not check and sqlite_import.done() is not None:
            self.stdout.write("Already moved; nothing to do.")
            return
        try:
            said = sqlite_import.run(path, keep=not check)
        except sqlite_import.ImportFailed as exc:
            raise CommandError(f"Nothing was imported: {exc}")
        self.stdout.write(json.dumps(said, indent=2, sort_keys=True))
        self.stdout.write("Checked and rolled back." if check else "Moved.")
