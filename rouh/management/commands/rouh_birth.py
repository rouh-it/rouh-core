"""``python manage.py rouh_birth``: where this Rouh stands with its birth, read only.

    python manage.py rouh_birth                 born or not, its name and tag, how long it has lived,
                                                whether its recovery words still wait to be shown,
                                                whether it is registered on rouh.land

It never prints a key or a recovery word, and never gives birth: a birth is a Rouh's registration
with rouh.land, asked for by its owner on Your profile or in the first run, so it is never done from
a terminal or by a job.
"""
import json

from django.core.management.base import BaseCommand

from rouh import birth
from rouh.models import DEFAULT_ORG_ID


class Command(BaseCommand):
    help = "Where this Rouh stands with its birth (read only; never a key or a word)."

    def add_arguments(self, parser):
        parser.add_argument("--org", default=DEFAULT_ORG_ID, help="the organisation (default: the first)")

    def handle(self, org, **_):
        self.stdout.write(json.dumps(birth.status(str(org)), indent=2, ensure_ascii=False))
