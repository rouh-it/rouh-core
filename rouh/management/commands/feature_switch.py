"""``python manage.py feature_switch``: read or turn a feature's on/off switch (`rouh/switches.py`).

The same switches as Evolution, Mutations (a gene's on its row, every other under Other
switches), and the nightly feature run's `nightly_switch` tool. With no name it lists them; with a
name and on or off it turns that one.

    python manage.py feature_switch
    python manage.py feature_switch calendar_digest off
    python manage.py feature_switch calendar_digest on --org org-default

`--org` is only needed on an install with more than one organisation.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from rouh import switches


class Command(BaseCommand):
    help = "List the feature switches, or turn one on or off."

    def add_arguments(self, parser):
        parser.add_argument("name", nargs="?", default="")
        parser.add_argument("state", nargs="?", choices=("on", "off"))
        parser.add_argument("--org", default="")

    def handle(self, *args, **opts):
        org = opts["org"] or None
        if opts["name"]:
            if not opts["state"]:
                raise CommandError("Say on or off after the switch's name.")
            try:
                switches.set_on(opts["name"], opts["state"] == "on", by="manage.py", org_id=org)
            except switches.Refused as exc:
                raise CommandError(str(exc)) from None
        rows = switches.listing(org)
        if not rows:
            self.stdout.write("No feature switches yet.")
        for row in rows:
            self.stdout.write(f"{row['name']}: {'on' if row['on'] else 'off'}"
                              + (f"  ({row['title']})" if row["title"] else ""))
