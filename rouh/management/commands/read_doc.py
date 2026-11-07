"""``python manage.py read_doc``: what Rouh reads in one Google Doc, from a terminal.

The read_doc tool's own words about a document, read through one account's own
Google connection: every tab, the links kept, and the files it links to listed
with their ids. It is how somebody on the server checks what Rouh really sees
in a real document without asking it in a conversation, which is how reading
tabs and links was checked against a contact's documents on 24 September 2026.

    manage.py read_doc alex 1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789abcdefg
    manage.py read_doc alex "Homepage Copy" --tab "Headline v2 options"

It only reads. The same function answers a turn (`tools.read_doc`), so what it
prints is what the model is told, less the box that marks it as somebody
else's words.

On the server it has to run with the service's own environment, or it could
not open the connection's tokens, which are sealed with the service's key. The
deploy's database step runs that way already (`deploy/rouh.sh`), and so does
this, as root, with nothing reading the .env itself:

    systemd-run --quiet --wait --pipe --collect \\
        -p EnvironmentFile=-/var/www/rouh/.env -p WorkingDirectory=/var/www/rouh/app \\
        /var/www/rouh/.venv/bin/python manage.py read_doc alex <document>
"""
from __future__ import annotations

import asyncio
import os

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "What Rouh's read_doc says about one Google Doc, read as one account."

    def add_arguments(self, parser):
        parser.add_argument("username", help="the Rouh account whose Google connection reads it")
        parser.add_argument("document", help="the document id, its link, or its name in Drive")
        parser.add_argument("--tab", default="", help="one tab only, by its title or its id")

    def handle(self, *args, username, document, tab, **options):
        # The tool reads the Google connection from the event loop, as it does
        # in the server, which allows that for itself (`rouh/project/asgi.py`).
        os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
        from rouh import accounts
        from rouh.config import config
        from rouh.encryption import NotEncryptable, SecretBox
        from rouh.google_api import GoogleClients, GoogleDesk
        from rouh.google_oauth import GoogleAuth
        from rouh.google_store import GoogleStore
        from rouh.tenancy import Tenancy, speaking
        from rouh.tools import read_doc

        user = accounts.get_user(username)
        if user is None:
            raise CommandError(f"There is no account called {username}.")
        tenancy = Tenancy()
        who = tenancy.identity_of(str(user.pk))
        if who is None:
            raise CommandError(f"The account {username} is not active.")
        try:
            box = SecretBox(config.encryption_key, data_dir=config.data_dir)
        except NotEncryptable as exc:
            raise CommandError(str(exc)) from exc
        store = GoogleStore(None, box)
        desk = GoogleDesk(tenancy, store, GoogleClients(GoogleAuth(store, config), config))

        async def read() -> str:
            # The desk opens whoever is speaking, the same as in a turn.
            with speaking(who):
                return await read_doc(desk, document, tab)

        self.stdout.write(asyncio.run(read()))
