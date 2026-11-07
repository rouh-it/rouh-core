"""``python manage.py rules``: what Rouh always follows, and the old memory (`rouh/rules.py`).

    python manage.py rules                              # counts: rules, Vocabulary entries, old facts
    python manage.py rules propose --file proposals.json --user 1
        # where each old fact is proposed to go: {"<fact id>": {"home": "rule" | "vocabulary" | "note" | "drop",
        #   "text": ..., "for": [{"type", "id", "name"}], "term": ..., "meaning": ..., "why": ...}}

    python manage.py rules apply --file plan.json --user 1
        # tag, move or split the person's rules as they asked: [{"id", "defaults"?, "group"?,
        #   "split"?: [{"text", "defaults"?, "group"?}, ...]}]; a split keeps the words, every piece of them in
        #   order and nothing else, the first piece staying the rule itself

The person applies or changes each proposal on the Rules page; this only proposes.
On the server, run it with Rouh's environment, as Rouh's other commands are run (README).
"""
from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Say where the rules stand, or propose where each old fact goes."

    def add_arguments(self, parser):
        parser.add_argument("action", nargs="?", default="status", choices=["status", "propose", "apply"])
        parser.add_argument("--file", default="")
        parser.add_argument("--user", default="1")
        parser.add_argument("--org", default="")

    def handle(self, *args, **o):
        from rouh import rules, vocabulary
        from rouh.models.accounts import User

        user = User.objects.filter(id=o["user"]).first()
        if user is None:
            raise CommandError(f"There is no account {o['user']}.")
        org = o["org"] or str(user.org_id or "org-default")
        if o["action"] == "propose":
            if not o["file"]:
                raise CommandError("Say which file: --file proposals.json")
            with open(o["file"], encoding="utf-8") as f:
                got = json.load(f)
            self.stdout.write(f"Proposed a home for {rules.propose(got)} of {len(got)} old facts.")
        ds = rules.master(str(user.id), org)
        if o["action"] == "apply":
            if not o["file"]:
                raise CommandError("Say which file: --file plan.json")
            with open(o["file"], encoding="utf-8") as f:
                plan = json.load(f)
            self.stdout.write(json.dumps(_apply(ds, plan), indent=1, ensure_ascii=False))
            return
        everything = rules.rules(ds)
        old = rules.old_facts()
        self.stdout.write(json.dumps({
            "rules_every_turn": sum(1 for r in everything if r["every_turn"]),
            "rules_for_something": sum(1 for r in everything if not r["every_turn"]),
            "vocabulary": len(vocabulary.entries(ds)), "old_facts": len(old),
            "old_with_a_proposal": sum(1 for f in old if f["proposal"].get("why"))}))


def _apply(ds: dict, plan: list) -> dict:
    """Each step of the plan, all of it checked before any of it is done."""
    from rouh import rules

    by = "the owner's request of 30 October 2026, applied by a job"
    have = {r["id"]: r for r in rules.rules(ds, every=True)}
    for step in plan:
        r = have.get(str(step.get("id") or ""))
        if r is None:
            raise CommandError(f"There is no rule {step.get('id')}.")
        pieces = step.get("split") or []
        if pieces and " ".join(" ".join(p["text"] for p in pieces).split()) != " ".join(r["text"].split()):
            raise CommandError(f"The split of {r['id']} does not keep its words, all of them and in order.")
    done = []
    for step in plan:
        ref, r = f"r:{step['id']}", have[str(step["id"])]
        pieces = step.get("split") or []
        if pieces:
            rules.edit_rule(ds, r["id"], pieces[0]["text"].strip(), by=by)
            for p in pieces[1:]:
                made = rules.add_rule(ds, p["text"].strip(), r["for"], by=by, group=str(p.get("group") or r["group"]),
                                      origin=r["origin"] or rules.origin_of("agents", "Split from one of your rules by a job."))
                if p.get("defaults"):
                    rules.set_defaults(ds, f"r:{made['id']}", True, by=by)
                done.append({"split_from": r["id"], "made": made["id"]})
            step = {**{k: v for k, v in step.items() if k != "split"},
                    **{k: pieces[0][k] for k in ("defaults", "group") if k in pieces[0]}}
        if "defaults" in step:
            rules.set_defaults(ds, ref, bool(step["defaults"]), by=by)
        if step.get("group") and step["group"] != r["group"]:
            rules.set_group(ds, ds["org_id"], ref, step["group"], by=by)
        done.append({"id": r["id"], "defaults": step.get("defaults"), "group": step.get("group")})
    return {"done": done}
