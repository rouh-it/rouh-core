"""``python manage.py waiting_check``: every case and decision waiting for the owner has
something for them to press.

Petar, 11 October 2026, on a contact's itinerary: "It says waiting for me, but there is no obvious
action." Since then a case that waits for him names its action (MAIL.md, D16): its open
decision's main option, or Redo. This reads every case resting at "waiting for you" through
the very function its page draws it with (`CaseDesk.state_of`, `rouh/case_state.py`), and every
open decision, of every source, and says each one that has nothing to press. A reader and
nothing else: it judges nothing again, runs nothing and sends nothing.

    python manage.py waiting_check            each problem, one line; exit 1 when there is one
    python manage.py waiting_check --all      every waiting case and what it offers
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from rouh import case_state, decisions
from rouh.mail_cases import AWAITING, CaseDesk
from rouh.models import Decision, MailCase
from rouh.tenancy import Identity


class Command(BaseCommand):
    help = "Check that every case and decision waiting for the owner has something to press."

    def add_arguments(self, parser):
        parser.add_argument("--all", action="store_true", help="say every waiting case")

    def handle(self, *args, **opts):
        desk = CaseDesk(None)
        bad = []
        for case in MailCase.objects.filter(stage=AWAITING, merged_into__isnull=True) \
                .order_by("id"):
            who = Identity(user_id=case.user_id, org_id=case.org_id)
            state = desk.state_of(who, case)
            why = case_state.unactionable(state)
            said = (f"case {case.id} ({case.sender_name}, {case.key}): {state.words}; "
                    + (f"press {(state.action or {}).get('label')!r}" if state.action else
                       f"waits on {state.waits_on or 'nothing it says'}")
                    + f". {state.line}")
            if why:
                bad.append(f"{said} - {why}")
            elif opts["all"]:
                self.stdout.write("ok   " + said)
        for row in Decision.objects.filter(status__in=decisions.ANSWERABLE).order_by("id"):
            why = case_state.decision_unactionable(decisions.options_of(row.options))
            if why and (row.allow_other or row.answer_type == "text") and row.source != "mail":
                # Answered in the person's own words: that is something to press.
                why = ""
            if why:
                bad.append(f"decision {row.number or '#' + str(row.id)} ({row.source}, {row.title[:60]}): "
                           f"{why}")
        for line in bad:
            self.stdout.write("FAIL " + line)
        if bad:
            raise CommandError(f"{len(bad)} waiting with nothing to press.")
        self.stdout.write("Every case and decision waiting for you has something to press.")
