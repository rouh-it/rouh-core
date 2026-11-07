"""``python manage.py synapse_benchmark``: Synapse's fixed benchmark (`rouh/synapse/evalbench.py`, `snapshot.py`).

    python manage.py synapse_benchmark status                 # the frozen dataset, its questions, the fingerprint
    python manage.py synapse_benchmark freeze                 # take the frozen copy of Master, once, and install
                                                              # the 103 questions in it (refused while Master's
                                                              # backfill lane is reading, or a gold item lacks its X-ray)
    python manage.py synapse_benchmark check                  # every gold item there, every asker known, and each
                                                              # must-not-answer question's gold unreadable by its asker
    python manage.py synapse_benchmark run --json out.json    # one judged pass, both sets (about $2.40)
    python manage.py synapse_benchmark run --no-judge --passes 2
                                                              # recall, time, tokens, cost and leaks only (cents)
    python manage.py synapse_benchmark run --set master --only 101,102 -v 2

A pass measures the code of the checkout it is run from against the frozen dataset, read only. On the server,
run it with Rouh's environment:
``deploy/with-rouh-env.sh <checkout> /var/www/rouh/.venv/bin/python manage.py synapse_benchmark run ...``
In the containers, from the machine: ``docker compose exec core python manage.py synapse_benchmark ...`` (a run in the
worker cannot reach the database: `deploy/with-rouh-env.sh` says so and stops).
"""
from __future__ import annotations

import json
import os

from django.core.management.base import BaseCommand, CommandError

from rouh.synapse import db, evalbench, master, people, snapshot


class Command(BaseCommand):
    help = "Synapse's fixed benchmark: freeze Master once, check it, and run the 103 questions on it."

    def add_arguments(self, parser):
        parser.add_argument("action", choices=["status", "freeze", "check", "run"])
        parser.add_argument("--user", default="1")
        parser.add_argument("--org", default="")
        parser.add_argument("--passes", type=int, default=1)
        parser.add_argument("--no-judge", action="store_true", help="no answer and no judge: retrieval measures only")
        parser.add_argument("--set", choices=["both", "inbox", "master"], default="both")
        parser.add_argument("--only", default="", help="question ids in the frozen dataset, comma separated")
        parser.add_argument("--json", default="", help="write every pass, whole, and the pooled measures here")

    def handle(self, *args, **o):
        os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
        org = o["org"] or self._org_of(o["user"])
        user = str(o["user"])
        act = o["action"]
        if act == "freeze":
            src = master.of(org, user)
            if not src:
                raise CommandError("There is no Synapse Master for that account.")
            if snapshot.existing(org, user):
                raise CommandError(f'"{snapshot.NAME}" exists already; it is taken once. Its questions: status.')
            bench = evalbench.load()
            keys = sorted({k for st in evalbench.SETS for q in bench["sets"][st]
                           for k in q["gold"] + ([q["context"]] if q.get("context") else [])})
            try:
                got = snapshot.freeze(src, gold_keys=keys)
            except ValueError as exc:
                raise CommandError(str(exc)) from None
            inst = evalbench.install(got["dataset"], bench)
            self.stdout.write(f"Frozen as {got['dataset']['id']}: {json.dumps(got['counts'])}; "
                              f"{inst['installed']} questions installed; fingerprint {evalbench.fingerprint()}.")
            return
        try:
            ds = evalbench.frozen(org, user)
        except RuntimeError as exc:
            raise CommandError(str(exc)) from None
        if act == "status":
            n = db.value("SELECT count(*) FROM synapse.eval_question WHERE dataset_id = %s", (ds["id"],))
            items = db.value("SELECT count(*) FROM synapse.item WHERE dataset_id = %s", (ds["id"],))
            self.stdout.write(f"{ds['name']} ({ds['id']}), taken {ds['created_at']:%Y-%m-%d %H:%M} UTC, {items} items, "
                              f"{n} questions, fingerprint {evalbench.fingerprint()}")
            return
        if act == "check":
            self._check(ds)
            return
        sets = evalbench.SETS if o["set"] == "both" else (o["set"],)
        only = [int(x) for x in o["only"].split(",") if x.strip()] or None
        say = (lambda line: self.stdout.write(line)) if int(o.get("verbosity") or 1) >= 2 else None
        results = []
        for n in range(max(1, o["passes"])):
            got = evalbench.run(org, user, judge=not o["no_judge"], sets=sets, only=only, log=say)
            results.append(got)
            self._summary(got, n + 1)
        if o["json"]:
            with open(o["json"], "w") as fh:
                json.dump({"passes": results, "pooled": evalbench.pooled(results)}, fh, ensure_ascii=False, indent=1,
                          default=str)
            self.stdout.write(f"Written to {o['json']}")

    def _check(self, ds: dict) -> None:
        """Every must-not-answer question's gold is out of its asker's reach, by the rule itself."""
        from rouh.synapse import evaluate, search

        problems = 0
        for q in evaluate.questions(ds):
            if not q.get("forbidden"):
                continue
            principals = search.readers_for(q["asker"])
            readable = db.rows(f"SELECT i.title FROM synapse.item i WHERE i.dataset_id = %s AND i.id = ANY(%s::uuid[]) "
                               f"AND {search.readable_rule_sql('i')}", (ds["id"], q.get("gold") or [], principals,
                                                                         principals))
            name = people.name_of(q["asker"])
            if readable:
                problems += 1
                self.stdout.write(f"PROBLEM {q['id']} ({name}): may read {', '.join(r['title'] for r in readable)}")
            else:
                self.stdout.write(f"ok {q['id']} {name}: none of its {len(q.get('gold') or [])} gold items is readable")
        self.stdout.write(f"{problems} problems")

    def _summary(self, got: dict, n: int) -> None:
        self.stdout.write(f"Pass {n}: {got['benchmark']} v{got['version']} ({got['fingerprint']}), "
                          f"{'judged' if got['judged'] else 'not judged'}, {got['seconds']} s, ${got['spend_usd']:.4f}")
        for part, s in got["summary"].items():
            self.stdout.write(f"  {part:8} {json.dumps(s)}")

    @staticmethod
    def _org_of(user_id: str) -> str:
        from rouh.models.accounts import User

        user = User.objects.filter(id=user_id).first()
        if user is None:
            raise CommandError(f"There is no account {user_id}.")
        return str(user.org_id or "org-default")
