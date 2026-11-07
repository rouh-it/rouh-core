"""`python manage.py setup_link`: the address that opens this Rouh's first run, or signs its owner in.

For whoever runs Rouh's containers with Docker by hand, where nothing opens the page for them as
Rouh for Mac does: ``docker compose exec core python manage.py setup_link`` prints
``http://127.0.0.1:8420/setup?code=...``, and opening it does what Open Rouh in Rouh for Mac does
(`rouh/web/firstrun.py`). Each address works once: using it writes a new code.
"""
from __future__ import annotations

import os

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Print the address that opens this Rouh's first run, or signs its owner in."

    def handle(self, *args, **opt):
        from rouh.web import firstrun

        if not firstrun.code_file():
            raise CommandError("This Rouh has no setup code (ROUH_FIRST_RUN_CODE_FILE is not set): its owner "
                               "is made with python manage.py setup, and signs in with a password.")
        code = firstrun._code() or firstrun.new_code()
        port = os.environ.get("ROUH_PUBLISHED_PORT", "").strip() or "8420"
        self.stdout.write(f"http://127.0.0.1:{port}/setup?code={code}")
