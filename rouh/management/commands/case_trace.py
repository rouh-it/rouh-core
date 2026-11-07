"""``python manage.py case_trace <key>``: one email case, step by step, for a run fixing it.

The same trace the case page draws (`rouh/case_trace.py`), as text a run can
read: every step with its brief as sent, the tools it was offered, its tool
calls and what came back, its report, the routing rule by rule, the diagnosis
and the owner's notes. The brief on the case page names this command. A reader
and nothing else.

    python manage.py case_trace BFgn_2-ZtnWF1w6hqftMSz0t          the whole trace
    python manage.py case_trace BFgn_2-ZtnWF1w6hqftMSz0t --json   the same, as JSON
    python manage.py case_trace BFgn_2-ZtnWF1w6hqftMSz0t --request 1864
                                                                  one model request whole
"""
from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from rouh import case_trace, trusted
from rouh.models import MailCase


class Command(BaseCommand):
    help = "Read one email case's whole trace: what each step was given, said and decided."

    def add_arguments(self, parser):
        parser.add_argument("key", help="the case's key, the end of its page's address")
        parser.add_argument("--json", action="store_true", help="the trace as JSON")
        parser.add_argument("--request", type=int, help="one model request of the case, whole")

    def handle(self, *args, **opts):
        # The key is the case's own random address: it names one case, and the
        # case names whose it is, so everything below is asked for by them.
        case = MailCase.objects.filter(key=opts["key"]).first()
        if case is None:
            raise CommandError("There is no case with that key.")
        if opts.get("request"):
            got = case_trace.request_for(case, opts["request"])
            if got is None:
                raise CommandError("That request is not one of this case's.")
            self.stdout.write(json.dumps(got, indent=2, ensure_ascii=False, default=str))
            return
        contact = (trusted.TrustStore().get(case.user_id, case.org_id, case.contact_id)
                   if case.contact_id else None)
        trace = case_trace.build(case, contact_now=contact)
        if opts["json"]:
            self.stdout.write(json.dumps(trace, indent=2, ensure_ascii=False, default=str))
            return
        self.stdout.write(case_trace.trace_for_model(case, trace))
        self.stdout.write("\n\n# Model requests (read one whole with --request <id>)")
        for step in trace["steps"]:
            for turn in step.get("turns") or []:
                for call in turn["calls"]:
                    self.stdout.write(f"{step['id']}: request {call['id']} {call['when']} "
                                      f"{call['model']} {call['status']} "
                                      f"in {call['input_tokens']} out {call['output_tokens']} "
                                      f"${call['cost']:.4f}")
