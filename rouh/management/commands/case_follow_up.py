"""``python manage.py case_follow_up <key>``: one more message to a case's sender, once.

For when the owner has asked, in their own words, for something more to reach the
person a finished case answered (card 1315: a contact's verified travel
comparison, after only a question had gone). It goes the case's own way
(`CaseDesk.send_follow_up`): on the case's channel, to the account or address
it came from while it is still theirs, written down whole on the case's page
and in the sent log, and never twice.

Without --send it only shows what the case already sent and what would go.

    manage.py case_follow_up <key> --text-file reply.txt
    manage.py case_follow_up <key> --text-file reply.txt --why "The owner asked ..." --send

On the server it runs with the service's own environment, as root, with
nothing reading the .env itself (the bot's settings and the Google tokens are
the service's):

    systemd-run --quiet --wait --pipe --collect \\
        -p EnvironmentFile=-/var/www/rouh/.env -p WorkingDirectory=/var/www/rouh/app \\
        /var/www/rouh/.venv/bin/python manage.py case_follow_up <key> --text-file ...

In the containers there is no systemd; the core already has Rouh's environment, so from the
machine (a run in the worker cannot reach the database, and cannot do this):

    docker compose cp reply.txt core:/tmp/reply.txt
    docker compose exec core python manage.py case_follow_up <key> --text-file /tmp/reply.txt
"""
from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Send one follow-up to a finished case's sender, on the case's own channel, once."

    def add_arguments(self, parser):
        parser.add_argument("key", help="the case's key, the end of its page's address")
        parser.add_argument("--text-file", required=True, help="the message, plain text")
        parser.add_argument("--why", default="", help="whose word it goes on, and why")
        parser.add_argument("--send", action="store_true", help="send it; without, only show")

    def handle(self, *args, key, text_file, why, send, **options):
        os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
        from rouh import mail_cases, sentlog
        from rouh.config import config
        from rouh.models import MailCase
        from rouh.telegram import Telegram
        from rouh.tenancy import Identity

        try:
            with open(text_file, encoding="utf-8") as fh:
                text = fh.read().strip()
        except OSError as exc:
            raise CommandError(f"The message could not be read: {exc}") from exc
        case = MailCase.objects.filter(key=key).first()
        if case is None:
            raise CommandError("There is no case with that key.")
        who = Identity(user_id=case.user_id, org_id=case.org_id)
        ups = (case.told or {}).get("follow_ups") or []
        self.stdout.write(f"Case {case.key}: {case.sender_name} <{case.sender}>, stage "
                          f"{case.stage}, attempt {case.attempt_no}.")
        self.stdout.write(f"Its reply went as {case.reply_message_id or '(none)'}:\n"
                          f"{case.sent_reply or '(nothing)'}\n")
        for one in ups:
            self.stdout.write(f"A follow-up was claimed before: {one}")
        self.stdout.write(f"What would go ({len(text)} characters):\n{text}\n")
        if not send:
            self.stdout.write("Nothing was sent: add --send to send it.")
            return
        sentlog.configure(config.logs_path)
        clients = None
        if not str(case.message_id or "").startswith("tg:"):
            from rouh.encryption import NotEncryptable, SecretBox
            from rouh.google_api import GoogleClients
            from rouh.google_oauth import GoogleAuth
            from rouh.google_store import GoogleStore

            try:
                box = SecretBox(config.encryption_key, data_dir=config.data_dir)
            except NotEncryptable as exc:
                raise CommandError(str(exc)) from exc
            store = GoogleStore(None, box)
            clients = GoogleClients(GoogleAuth(store, config), config)
        alerts = SimpleNamespace(
            cfg=config, _clients=clients,
            telegram=Telegram(getattr(config, "telegram_file", None),
                              api_base=getattr(config, "telegram_api_base", None)))
        desk = mail_cases.CaseDesk(alerts)
        try:
            sent_id = asyncio.run(desk.send_follow_up(who, key, text, why=why))
        except (ValueError, LookupError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(f"Sent, as {sent_id}. It is on the case's page and in "
                          f"{sentlog.path() or 'rouh.log'}.")
