"""``python manage.py rouh_link``: Rouh Link from a shell (`rouh/link/`, task 189).

    python manage.py rouh_link                         this Rouh on the link: name, address, connections
    python manage.py rouh_link card                    its signed Rouh card
    python manage.py rouh_link invite [--trust known] [--for <label>] [--note ...]
                                                        a connect link (and nothing else is changed)
    python manage.py rouh_link accept <link> [--trust known]
                                                        bring another Rouh's connect link here
    python manage.py rouh_link log [--check]           the signed log, and whether it holds
    python manage.py rouh_link test-birth              a throwaway world only: give it a born identity
                                                        without rouh.land (needs ROUH_LINK_TEST_BIRTH=1
                                                        and a loopback ROUH_PUBLIC_URL)

In the containers, from the machine: docker compose exec core python manage.py rouh_link
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from urllib.parse import urlsplit

from django.core.management.base import BaseCommand, CommandError


def _org() -> str:
    from rouh.link import me as _me

    org = _me.only_org()
    if org is None:
        raise CommandError("There is no one born Rouh here.")
    return org


class Command(BaseCommand):
    help = "Rouh Link from a shell: status, card, connect links, the log."

    def add_arguments(self, parser):
        parser.add_argument("what", nargs="?", default="status")
        parser.add_argument("link", nargs="?", default="")
        parser.add_argument("--trust", default="known")
        parser.add_argument("--for", dest="for_label", default="")
        parser.add_argument("--note", default="")
        parser.add_argument("--check", action="store_true")
        parser.add_argument("--json", action="store_true")
        parser.add_argument("--org", default="")

    def handle(self, *args, **o):
        os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
        what = o["what"]
        if what == "test-birth":
            return self._test_birth(o["org"])
        from rouh.link import card, log, me as _me, peers, spaces

        org = o["org"] or _org()
        if what == "status":
            me = _me.me(org)
            got = {"name": me.tagged, "label": me.label, "address": me.address,
                   "settings": _me.settings(org), "peers": peers.listing(org), "spaces": spaces.listing(org)}
            self.stdout.write(json.dumps(got, indent=1, default=str) if o["json"] else
                              f"{me.tagged} ({me.label}) at {me.address or 'no address yet'}\n"
                              + "\n".join(f"  {p['name']} [{p['state']}, {p['trust_word']}] {p['address']}" for p in got["peers"])
                              + f"\n  {len(got['spaces'])} shared space(s)")
        elif what == "card":
            self.stdout.write(json.dumps(card.build(org), indent=1))
        elif what == "invite":
            got = peers.invite(org, trust_level=o["trust"], for_label=o["for_label"], note=o["note"])
            got.pop("qr", None)
            self.stdout.write(json.dumps(got, indent=1) if o["json"] else got["link"])
        elif what == "accept":
            got = asyncio.run(peers.accept(org, o["link"], trust_level=o["trust"]))
            self.stdout.write(json.dumps(got, indent=1, default=str))
        elif what == "log":
            if o["check"]:
                self.stdout.write(json.dumps(log.verify_chain(org)))
            for e in log.entries(org, most=50):
                self.stdout.write(f"{e['seq']:>5} {time.strftime('%Y-%m-%d %H:%M', time.localtime(e['at']))} {e['plain']}")
        else:
            raise CommandError(f"What is {what!r}? status, card, invite, accept, log or test-birth.")

    def _test_birth(self, org: str) -> None:
        """A born identity with no rouh.land, for a throwaway test world only."""
        if os.environ.get("ROUH_LINK_TEST_BIRTH") != "1":
            raise CommandError("Only in a throwaway test world: set ROUH_LINK_TEST_BIRTH=1.")
        host = urlsplit(os.environ.get("ROUH_PUBLIC_URL", "")).hostname or ""
        if host not in ("127.0.0.1", "localhost"):
            raise CommandError("Only in a throwaway test world on this machine (ROUH_PUBLIC_URL on 127.0.0.1).")
        from rouh import birth, names
        from rouh.encryption import box
        from rouh.models import Organisation, RouhBirth

        org = org or str(Organisation.objects.order_by("created_at").values_list("id", flat=True).first() or "")
        if not org:
            raise CommandError("No organisation here yet.")
        if birth.current(org) is not None:
            self.stdout.write(f"already born: {birth.current(org).name}")
            return
        seed, pub = birth.new_key()
        rseed, rpub = birth.new_key()
        now = time.time()
        body = {"kind": "rouh-birth", "v": 2, "birth_key": birth._b64(pub), "recovery_key": birth._b64(rpub),
                "born_at": birth._iso(now)}
        stmt = birth.statement(body, {"birth": seed, "recovery": rseed})
        n = names.derive(pub)
        name = n.words
        RouhBirth.objects.create(org_id=org, state="born", name=name, tag=n.tag, born_at=now, birth_key=birth._b64(pub),
                                 birth_statement=stmt, daily_public=birth._b64(pub),
                                 daily_private=box().seal(birth._b64(seed)), daily_since=now,
                                 recovery_public=birth._b64(rpub), updated_at=now)
        self.stdout.write(f"born for the test: {name} ·{n.tag}")
