"""``python manage.py handover``: give an account a new password, delivered.

    manage.py handover <username> --email <address>

The password is made, sent by Telegram and by email, and only set once at
least one of them went (`rouh/handover.py`). It is never printed here.
"""
import os

from django.core.management.base import BaseCommand, CommandError

from rouh import handover


class Command(BaseCommand):
    help = "Make a password, deliver it by Telegram and email, and only then set it."

    def add_arguments(self, parser):
        parser.add_argument("username")
        parser.add_argument("--email", default="")

    def handle(self, *args, username="", email="", **options):
        # The delivery is async and reads the Google connection as it goes.
        os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
        try:
            went = handover.hand_over(username, email)
        except handover.NotDelivered as exc:
            raise CommandError(str(exc))
        self.stdout.write(f"The sign-in for {username} was delivered by {', '.join(went)}.")
