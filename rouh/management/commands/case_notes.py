"""``python manage.py case_notes``: what the owner said about email cases, for tuning.

Every false alarm and real problem they marked on a case's page with their reason,
every step they re-ran and what they told it, and every question they asked there
and the answer (`MailCaseNote`, `rouh/case_trace.py`). A reader and nothing
else: a run tuning the pipeline starts here.

    python manage.py case_notes                   every note, newest first
    python manage.py case_notes --kind false_alarm
    python manage.py case_notes --json
"""
from __future__ import annotations

import json
from datetime import datetime

from django.core.management.base import BaseCommand

from rouh.models import MailCaseNote


class Command(BaseCommand):
    help = "Read the owner's notes on email cases: false alarms, real problems, re-runs, questions."

    def add_arguments(self, parser):
        parser.add_argument("--kind", choices=("false_alarm", "real_problem", "rerun", "fix",
                                               "question"))
        parser.add_argument("--limit", type=int, default=100)
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **opts):
        rows = MailCaseNote.objects.select_related("case").order_by("-at")
        if opts.get("kind"):
            rows = rows.filter(kind=opts["kind"])
        out = []
        for n in rows[: opts["limit"]]:
            out.append({"at": datetime.fromtimestamp(n.at).isoformat(timespec="seconds"),
                        "kind": n.kind, "step": n.step, "text": n.text, "answer": n.answer,
                        "case": n.case.key, "user_id": n.user_id, "org_id": n.org_id,
                        "sender": n.case.sender, "subject": n.case.subject,
                        "stage": n.case.stage})
        if opts["json"]:
            self.stdout.write(json.dumps(out, indent=2, ensure_ascii=False))
            return
        if not out:
            self.stdout.write("No notes yet.")
        for n in out:
            self.stdout.write(f"{n['at']}  {n['kind']:12} {n['step'] or '-':12} case {n['case']} "
                              f"({n['sender']}, {n['stage']})\n    {n['text']}"
                              + (f"\n    answer: {n['answer'][:400]}" if n["answer"] else ""))
