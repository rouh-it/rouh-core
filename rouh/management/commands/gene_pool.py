"""``python manage.py gene_pool``: where this Rouh stands with the Gene Pool, and joining it with an
invitation read from a file (`rouh/genepool.py`; task 141, step 141-09).

    python manage.py gene_pool                                  the membership, the sharing mode and
                                                                the review list's numbers; reads only
    python manage.py gene_pool join --invitation-file F --user NAME   (a Rouh born on rouh.land: no file)

A Rouh born on rouh.land, or registered there later, joins by itself (`genepool.join_at_birth`; task
141, step 141-15), and the page has no Join. `join` is for a Rouh the Pool's staff invited instead:
the invitation is read from a file and never printed, so it reaches no log, chat or transcript, and
the file is left as it was. Joining sends this Rouh's name and a key; no gene leaves until a person
approves it on Outgoing genes, `/evolution/pool/outgoing`, unless they chose Automatic there, and
none comes in unless a person installs it on Incoming genes, `/evolution/pool/incoming`.
"""
from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from rouh import genepool


class Command(BaseCommand):
    help = "Where this Rouh stands with the Gene Pool, or join it with an invitation from a file."

    def add_arguments(self, parser):
        parser.add_argument("action", nargs="?", default="status", choices=("status", "join"))
        parser.add_argument("--user", default="", help="the administrator it is done as (their username)")
        parser.add_argument("--invitation-file", default="")
        parser.add_argument("--url", default="", help=f"the Pool's address (default {genepool.DEFAULT_URL})")
        parser.add_argument("--key-file", default="", help="the Pool's public key, when it is not rouh.land's")

    def _who(self, username: str):
        from rouh.models import User
        from rouh.tenancy import Tenancy

        users = User.objects.filter(is_active=True, is_guest=False)
        user = users.filter(username=username).first() if username else (users.first() if users.count() == 1 else None)
        if user is None:
            raise CommandError("Say whose: --user <username> of an administrator.")
        who = next((m for m in Tenancy().members(str(user.org_id)) if m.user_id == str(user.id)), None)
        if who is None or not who.is_admin:
            raise CommandError(f"{user.username} is not an administrator of their organisation.")
        return who

    def handle(self, action, user, invitation_file, url, key_file, **_):
        who = self._who(user)
        org = str(who.org_id)
        if action == "join":
            path = Path(invitation_file) if invitation_file else None
            if path is not None and not path.is_file():
                raise CommandError("--invitation-file must name the file the invitation is in.")
            code = path.read_text().strip() if path else ""
            try:
                # The name is the Rouh's own from its birth, or "A Rouh": never typed (141-11).
                got = genepool.join(who, url=url, key_pem=Path(key_file).read_text() if key_file else "", invitation=code)
            except genepool.Refused as exc:
                raise CommandError(str(exc)) from None
            self.stdout.write(got["said"])
            return
        mem = genepool.membership(org)
        out = genepool.review_list(who)
        counts = ", ".join(f"{s['name']} {s['count']}" for s in out["shows"])
        self.stdout.write(f"{genepool.NAME}: " + (f"joined as {mem.name}, since {mem.joined_at:.0f}" if mem and mem.status == "member"
                                                   else "not joined"))
        self.stdout.write(f"outgoing: {genepool.MODE_NAMES[out['mode']]} ({genepool.MODES[out['mode']]})")
        take = genepool.incoming(org)
        self.stdout.write(f"incoming: {genepool.INCOMING_NAMES[take]} ({genepool.INCOMING[take]})")
        self.stdout.write(f"review list: {counts}")
