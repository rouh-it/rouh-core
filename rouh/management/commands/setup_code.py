"""`python manage.py setup_code`: the setup code, for the `rouh` command on a Linux server.

Task 176, step 176-24. The `rouh` command (deploy/linux/rouh.py) runs this inside the core with
``docker compose exec``, so the code goes from the core's file to the owner's terminal and to
nothing else: not into ``docker logs``, which only the core's own start writes to.

    setup_code             the code, written afresh when there is none or it has expired
    setup_code --renew     a new code in place of the old one, which stops working at once
    setup_code --status    JSON: whether there is an owner, whether the code has expired, its hours

``rouh setup`` renews it every time it starts, so a code seen anywhere before, such as the line an
older core printed at its start, is dead by the time the wizard asks its first question.
"""
from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Print this Rouh's setup code (for the rouh command), renewing it when asked or when expired."

    def add_arguments(self, parser):
        parser.add_argument("--renew", action="store_true", help="write a new code; the old one stops working")
        parser.add_argument("--status", action="store_true", help="say, as JSON, whether there is an owner and a live code")

    def handle(self, *args, **opt):
        from rouh.web import firstrun

        if not firstrun.code_file():
            raise CommandError("This Rouh has no setup code (ROUH_FIRST_RUN_CODE_FILE is not set).")
        if opt["status"]:
            age = firstrun.code_age()
            owner = firstrun.the_owner()
            held = firstrun.record(owner) if owner is not None else {}
            self.stdout.write(json.dumps({
                "owner": owner is not None, "setup_done": bool(held.get("done_at")) or (owner is not None and not held),
                "kind": None if "connected" not in held else ("connected" if held["connected"] else "independent"),
                "code": age is not None, "expired": firstrun.code_expired(),
                "hours": firstrun.code_hours(), "age_seconds": None if age is None else int(age)}))
            return
        if opt["renew"] or not firstrun._code() or firstrun.code_expired():
            code = firstrun.new_code()
        else:
            code = firstrun._code()
        self.stdout.write(code)
