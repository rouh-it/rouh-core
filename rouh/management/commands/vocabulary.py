"""``python manage.py vocabulary``: the person's Vocabulary in Synapse Master (`rouh/vocabulary.py`).

    python manage.py vocabulary --user 1            # every entry, and how many old words are still to move
    python manage.py vocabulary move --user 1       # move the old words now, saying what each became
    python manage.py vocabulary plan --user 1       # what moving them would do, changing nothing

The old words move by themselves the first time the rules are read; this says what happened, or makes it happen.
On the server, run it with Rouh's environment, as Rouh's other commands are run (README).
"""
from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "List the Vocabulary, or move the old words into it."

    def add_arguments(self, parser):
        parser.add_argument("action", nargs="?", default="status", choices=["status", "move", "plan"])
        parser.add_argument("--user", default="1")
        parser.add_argument("--org", default="")

    def handle(self, *args, **o):
        from rouh import rules, vocabulary
        from rouh.models.accounts import User

        user = User.objects.filter(id=o["user"]).first()
        if user is None:
            raise CommandError(f"There is no account {o['user']}.")
        ds = rules.master(str(user.id), o["org"] or str(user.org_id or "org-default"))
        if o["action"] == "plan":
            out = [{"word": w["term"], **vocabulary.classify(ds, w)} for w in vocabulary._old_words(ds)]
        elif o["action"] == "move":
            out = {"moved": vocabulary.move_words(ds), "remember_rule_reworded": vocabulary._reword_remember(ds)}
        else:
            out = {"entries": [{k: e[k] for k in ("id", "term", "aliases", "meaning", "context")}
                               for e in vocabulary.entries(ds)],
                   "old_words_left": len(vocabulary._old_words(ds))}
        self.stdout.write(json.dumps(out, indent=1, ensure_ascii=False, default=str))
