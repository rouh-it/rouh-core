"""``python manage.py turn_records``: every turn's timings and results, as kept (`rouh/turnrecords.py`).

A reader and nothing else. With no arguments, today's turns of the installation's one person, one line
each: when, how it ended, which tier and model, the total, first token, first written and first spoken
word, and what it cost. With a turn's name, that one whole as JSON. ``--format json`` or ``csv`` exports
the days asked for whole, the same as ``/api/turns/export``.

    python manage.py turn_records                              today's, one line each
    python manage.py turn_records --from 2026-10-20 --to 2026-10-23 --format csv > turns.csv
    python manage.py turn_records --from 2026-10-23 --format json --chat chat-1a2b
    python manage.py turn_records turn-3c4d5e6f7a8b            one turn, whole
"""
from __future__ import annotations

import json
import sys

from django.core.management.base import BaseCommand, CommandError

from rouh import turnrecords
from rouh.models import TurnRecord


class Command(BaseCommand):
    help = "Read the kept record of every turn: one line each, one whole, or an export as JSON or CSV."

    def add_arguments(self, parser):
        parser.add_argument("turn", nargs="?", default="", help="one turn, whole, by its name")
        parser.add_argument("--from", dest="since", default=None, help="the first day, YYYY-MM-DD (today)")
        parser.add_argument("--to", dest="until", default=None, help="the last day, YYYY-MM-DD (the first)")
        parser.add_argument("--chat", default="", help="only this chat's turns")
        parser.add_argument("--user", default="", help="whose turns, by account id (the one person)")
        parser.add_argument("--format", default="lines", choices=("lines", "json", "csv"))

    def handle(self, *args, **options):
        if options["turn"]:
            row = TurnRecord.objects.filter(turn_id=options["turn"]).values().first()
            if row is None:
                raise CommandError(f"no turn {options['turn']}")
            sys.stdout.write(json.dumps(row, ensure_ascii=False, default=str, indent=1) + "\n")
            return
        who = self._who(options["user"])
        try:
            rows = turnrecords.export(who, options["since"], options["until"], chat=options["chat"])
        except ValueError as exc:
            raise CommandError(f"days are YYYY-MM-DD: {exc}") from exc
        if options["format"] == "json":
            sys.stdout.write(turnrecords.as_json(rows) + "\n")
        elif options["format"] == "csv":
            sys.stdout.write(turnrecords.as_csv(rows))
        else:
            for r in rows:
                f = turnrecords.flat(r)

                def ms(x):
                    return "-" if x is None else f"{x / 1000:.2f}s"

                sys.stdout.write(
                    f"{f['at'][:19]}  {r['turn_id']}  {f['status'] or '-':<9} {f['tier'] or '-':<8} "
                    f"{(f['model'] or '-')[:22]:<22} total {ms(f['total_ms'])}  first token {ms(f['first_token_ms'])}  "
                    f"word {ms(f['first_word_ms'])}  spoken {ms(f['first_spoken_ms'])}  "
                    f"${f['cost_usd'] or 0:.4f}  {f['tools']} tools\n")
            if not rows:
                sys.stdout.write("No turns kept for those days.\n")

    def _who(self, user: str):
        from rouh.tenancy import Tenancy

        if user:
            who = Tenancy().identity_of(user)
            if who is None:
                raise CommandError(f"no account {user}")
            return who
        who = Tenancy().only_person()
        if who is None:
            raise CommandError("this installation has more than one person: say whose with --user")
        return who
