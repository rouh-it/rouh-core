"""`python manage.py first_run_state`: how far this Rouh's owner is through the first run, as JSON.

For Rouh for Mac, which reads it in the core (``docker compose exec -T core python manage.py
first_run_state``) to tick its last setup step only once the owner is made and Rouh has a working key
for its chats, whichever company's it is, rather than when Claude Code happens to be signed in:

``{"owner": true, "next": "brain", "done": false}``. ``next`` is the screen the owner is on
(`rouh/web/firstrun.py`'s connect, you, born, words, brain; "you" too while there is no owner), "" once the first run is over.
Nothing secret is printed.
"""
from __future__ import annotations

import json

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Print how far the owner is through the first run, as JSON (for Rouh for Mac)."

    def handle(self, *args, **opt):
        from rouh.web import firstrun

        owner = firstrun.the_owner()
        if owner is None:
            state = {"owner": False, "next": "you", "done": False}
        else:
            screen = firstrun.next_screen(owner)
            state = {"owner": True, "next": screen, "done": not screen}
        self.stdout.write(json.dumps(state))
