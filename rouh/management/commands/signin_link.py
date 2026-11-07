"""`python manage.py signin_link EMAIL`: the way in when every other way fails.

Run by an administrator on the machine Rouh runs on (in the containers,
``docker compose exec core python manage.py signin_link you@example.com``). It prints a one-time
sign-in link and a six-digit code for that address, sent to nobody: whoever runs it hands it over,
or opens it themselves. It works once, for 15 minutes unless ``--minutes`` says otherwise (at
most 60), and cancels any link sent to that address before it (`rouh/signin.py`, `issue`).

The link is printed on every name this Rouh answers on (``ROUH_PUBLIC_URL`` and, in the
containers, this machine's own port), so it opens wherever the person is. The code works on the
sign-in page after Continue, for a Rouh that sends mail.
"""
from __future__ import annotations

import os

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Print a one-time sign-in link and code for an email address that signs an account in."

    def add_arguments(self, parser):
        parser.add_argument("email")
        parser.add_argument("--minutes", type=int, default=15)

    def handle(self, *args, **opt):
        from rouh import signin
        from rouh.config import config

        try:
            got = signin.issue(opt["email"], minutes=opt["minutes"])
        except ValueError as exc:
            raise CommandError(str(exc)) from None
        bases = []
        if config.public_url:
            bases.append(config.public_url.rstrip("/"))
        port = os.environ.get("ROUH_PUBLISHED_PORT", "").strip()
        if port or not bases:
            bases.append(f"http://127.0.0.1:{port or '8420'}")
        minutes = max(1, min(int(opt["minutes"]), 60))
        self.stdout.write(f"A one-time sign-in for {signin.normal(opt['email'])} (account {got['user'].username}),"
                          f" for {minutes} minutes, once:")
        for base in bases:
            self.stdout.write("  " + base + got["path"])
        self.stdout.write(f"  or the code {got['code']} on the sign-in page, after Continue")
