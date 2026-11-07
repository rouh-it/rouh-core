"""``python manage.py synapse_vectors``: which model each Synapse dataset's
vectors are, and moving them to another (`rouh/synapse/vectors.py`).

    python manage.py synapse_vectors                         # every dataset, where it stands
    python manage.py synapse_vectors check                   # ask Voyage for one vector
    python manage.py synapse_vectors move --all              # every dataset to voyage-4
    python manage.py synapse_vectors move --dataset <id> --to voyage-4
    python manage.py synapse_vectors put-back --dataset <id>

A move runs here, in this process, a batch at a time, and waits out Voyage's
rate limits: search keeps reading the old vectors until every passage has a
new one and the new ones have passed their check, then switches in one
transaction and keeps the old ones. Stopped half way, by anything, it carries
on from where it was when started again. Run on the server through
`systemd-run` with Rouh's own environment, so the key is read by Rouh and
never seen: nothing here prints a key.
"""
from __future__ import annotations

import time

from django.core.management.base import BaseCommand, CommandError

from rouh.synapse import ai, db, vectors, worker


class Command(BaseCommand):
    help = "Show or move the embedding model of Synapse's datasets."

    def add_arguments(self, parser):
        parser.add_argument("action", nargs="?", default="status", choices=["status", "check", "move", "put-back"])
        parser.add_argument("--dataset", action="append", default=[], help="a dataset id (more than once for more)")
        parser.add_argument("--all", action="store_true", help="every dataset not already on the model")
        parser.add_argument("--to", default=ai.VOYAGE_MODELS[0],
                            choices=list(ai.VOYAGE_MODELS + ai.OPENAI_EMBED_MODELS))
        parser.add_argument("--timeout", type=float, default=3600, help="seconds to keep moving, at most")

    def handle(self, *args, **o):
        if not db.ready():
            raise CommandError("Synapse's tables are not in this database (migration 0062).")
        action = o["action"]
        if action == "status":
            return self._status(self._datasets(o, every=True))
        if action == "check":
            return self._check()
        sets = self._datasets(o)
        if not sets:
            raise CommandError("Say which: --dataset <id>, or --all.")
        if action == "put-back":
            for ds in sets:
                self.stdout.write(f"{ds['name']}: {vectors.put_back(ds, by='manage.py')}")
            return self._status(sets)
        for ds in sets:
            self._move(ds, o["to"], o["timeout"])
        return self._status(sets)

    def _datasets(self, o, every: bool = False) -> list[dict]:
        if o["dataset"]:
            got = [db.row("SELECT * FROM synapse.dataset WHERE id = %s::uuid", (d,)) for d in o["dataset"]]
            missing = [d for d, g in zip(o["dataset"], got) if g is None]
            if missing:
                raise CommandError(f"no such dataset: {', '.join(missing)}")
            return got
        if o["all"] or every:
            return db.rows("SELECT * FROM synapse.dataset ORDER BY created_at")
        return []

    def _status(self, sets) -> None:
        for ds in sets:
            st = vectors.status(ds)
            c, m = st["counts"], st["move"]
            line = (f"{ds['id']}  {ds['name']}: searches {st['model']}, {c.get('on_model', 0)} of "
                    f"{c.get('passages', 0)} passages; {c.get('strays', 0)} of another model; "
                    f"{c.get('kept', 0)} old vectors kept")
            if m.get("state"):
                line += f"; move {m.get('from')} -> {m.get('to')}: {m['state']}"
                if m.get("state") == "moving":
                    line += f", {c.get('staged', 0)} made"
                if m.get("error"):
                    line += f" ({m['error']})"
                ck = m.get("verification") or {}
                if ck:
                    line += (f"; check {'passed' if ck.get('ok') else 'failed'}: {ck.get('found_themselves')} of "
                             f"{ck.get('sample')} found themselves in the top {ck.get('top')}")
            self.stdout.write(line)
        keys = {m: ai.can_embed(m) for m in ai.VOYAGE_MODELS + ai.OPENAI_EMBED_MODELS}
        self.stdout.write("keys on this machine: " + ", ".join(f"{m} {'yes' if k else 'no'}" for m, k in keys.items()))

    def _check(self) -> None:
        model = ai.VOYAGE_MODELS[0]
        if not ai.have_voyage():
            raise CommandError("VOYAGE_API_KEY is not set for this process.")
        from urllib.parse import urlsplit
        began = time.time()
        try:
            got = ai.embed(["Synapse checks that Voyage answers."], model=model, purpose="voyage_check",
                           input_type="query")
        except Exception as exc:  # noqa: BLE001
            raise CommandError(f"Voyage did not answer: {exc}") from None
        self.stdout.write(f"{model} answered at {urlsplit(ai.voyage_url()).netloc} with {len(got[0])} numbers "
                          f"in {int((time.time() - began) * 1000)} ms")

    def _move(self, ds: dict, to: str, timeout: float) -> None:
        if vectors.live_model(ds["id"]) == to:
            self.stdout.write(f"{ds['name']}: already {to}")
            return
        got = vectors.start(ds, to, by="manage.py")
        if not got.get("ok"):
            raise CommandError(f"{ds['name']}: {got.get('why')}")
        self.stdout.write(f"{ds['name']}: {'carrying on' if got.get('carrying_on') else 'moving'} to {to}")
        began = time.time()
        while time.time() - began < timeout:
            move = vectors._move(ds["id"])
            if move.get("state") != "moving":
                self.stdout.write(f"{ds['name']}: {move.get('state')}"
                                  + (f" ({move.get('error')})" if move.get("error") else ""))
                break
            job = db.value("SELECT id FROM synapse.job WHERE dataset_id = %s AND kind = 'revector' "
                           "AND done_at IS NULL AND not_before <= now() ORDER BY id LIMIT 1", (ds["id"],))
            if job:
                try:
                    worker.run_job_now(job)
                except Exception as exc:  # noqa: BLE001 - said, and the move says where it stopped
                    self.stdout.write(f"{ds['name']}: a batch failed: {exc}")
                if db.value("SELECT done_at IS NULL FROM synapse.job WHERE id = %s", (job,)):
                    time.sleep(5)       # Rouh's own worker has it
                self.stdout.write(f"{ds['name']}: {vectors.status(ds)['counts'].get('staged', 0)} made")
            else:
                time.sleep(5)
        # The sweep after a switch, here and now rather than on a queue nobody may be running.
        for job in db.rows("SELECT id FROM synapse.job WHERE dataset_id = %s AND kind = 'revector' "
                           "AND done_at IS NULL ORDER BY id", (ds["id"],)):
            if vectors._move(ds["id"]).get("state") != "moving":
                db.run("UPDATE synapse.job SET not_before = now() WHERE id = %s", (job["id"],))
                worker.run_job_now(job["id"])
