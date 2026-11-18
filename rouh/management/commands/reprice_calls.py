"""``python manage.py reprice_calls``: price the calls logged with no price only because their model
was on no price list, now that the model standard carries it.

    python manage.py reprice_calls            price them, and say how many, on which models and
                                              what that added, for each month and in all
    python manage.py reprice_calls --dry-run  only say it

Petar, 18 November 2026 (task 182): the model standard synced from rouh.land carries the prices,
so a call on a model rouh.land moved a use onto is priced from it (`rouh/costs.py`). A call that
failed or was stopped before it said what it used has nothing to price and is left as it is. Every
fetch of the standard does the same by itself (`modelstandard.fetch`, `llmlog.reprice`).
"""
from __future__ import annotations

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Price the calls logged with no price because their model was on no price list."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="only say what would be priced")

    def handle(self, *args, **opts):
        from rouh.llmlog import reprice

        got = reprice(apply=not opts["dry_run"])
        verb = "priced" if got["applied"] else "would be priced"
        self.stdout.write(f"{got['calls']} calls {verb}, ${got['dollars']:.2f} in all.")
        for model, m in sorted(got["models"].items(), key=lambda kv: -kv[1]["dollars"]):
            self.stdout.write(f"  {model}: {m['calls']} calls, ${m['dollars']:.2f}")
        for month, m in sorted(got["months"].items()):
            self.stdout.write(f"  {month}: {m['calls']} calls, ${m['dollars']:.2f}")
