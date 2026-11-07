"""The example datasets, so there is something to explore on the first day.

Both are fictional from end to end: every person, company, address and number
was made up for them (`seeds/*.json`), and none of it comes from anybody's real mail.

- **Northwind Studio**: a small design and software studio, with a bank pilot
  priced and signed, a hire, a relaunch date that moved, team notes, a private
  health note, a newsletter and a Bulgarian email.
- **Maria's logo case**: the spec's Maria test (D56), a freelance designer with
  many threads over four months, so her thread, topic and profile layers form
  and the ten Maria questions can be run.

Each also has its `dream` items (5 October 2026): an old and a new code, a moved
date, an answered ask, a receipt stored twice, a rule that is really a fact, a
contradiction and a thread with mixed sensitivity, so a night of dreaming has one
of every kind to find (`dreaming.py`), and `dream_eval` asks for the latest value
of each thing that changed. A set made before them gets them from the Dreams page
(`add_dream_examples`).

Dates are kept as days before today, so the sets are always recent. Items are
stored oldest first and each waits for its own model part, so a newer email
finds the older ones already X-rayed when its links are chosen.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

from . import datasets, db, evaluate, ingest, people, worker
from .trace import Trace

HERE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seeds")
EXAMPLES = {"northwind": "northwind.json", "maria": "maria.json"}


def load(key: str) -> dict:
    with open(os.path.join(HERE, EXAMPLES[key]), encoding="utf-8") as fh:
        return json.load(fh)


def examples() -> list[dict]:
    out = []
    for key in EXAMPLES:
        d = load(key)
        out.append({"key": key, "name": d["name"], "about": d["about"],
                    "items": len(d["items"]) + len(d.get("dream") or []),
                    "questions": len(d["eval"]) + len(d.get("dream_eval") or [])})
    return out


def create(who, key: str, *, by: str = "page") -> dict:
    if key not in EXAMPLES:
        return {"ok": False, "why": "There is no such example."}
    d = load(key)
    ds = datasets.create(who, d["name"], d["about"], example=key, owner_name=d.get("owner_name") or "")
    ingest.enqueue(ds["id"], "seed", priority=1, payload={"example": key, "by": by})
    return {"ok": True, "dataset": ds["id"]}


def seed_on_first_visit(who) -> list[str]:
    """Both examples, once per person, the first time they open Synapse."""
    name = f"seeded:{who.user_id}"
    if db.value("SELECT count(*) FROM synapse.backend_status WHERE org_id = %s AND name = %s", (str(who.org_id), name)):
        return []
    db.run("INSERT INTO synapse.backend_status (org_id, name, status, said) VALUES (%s, %s, 'done', 'examples made') "
           "ON CONFLICT DO NOTHING", (str(who.org_id), name))
    if db.value("SELECT count(*) FROM synapse.dataset WHERE org_id = %s AND user_id = %s",
                (str(who.org_id), str(who.user_id))):
        return []
    return [create(who, key, by="seed").get("dataset") for key in EXAMPLES]


def fill(ds: dict, key: str, *, only: str = "") -> dict:
    d = load(key)
    if only == "dream":
        # A set made before the dream examples: only those, and their questions (`add_dream_examples`).
        have = _keys(ds)
        d = dict(d, topics=[], items=[it for it in d.get("dream") or [] if it["key"] not in have],
                 eval=d.get("dream_eval") or [])
    else:
        d = dict(d, items=list(d["items"]) + list(d.get("dream") or []),
                 eval=list(d["eval"]) + list(d.get("dream_eval") or []))
    trace = Trace(ds["id"], "seed", f"Filling the example set {d['name']}" + (" with the dream examples" if only else ""),
                  by="seed")
    now = datetime.now(timezone.utc)
    stored = 0
    with trace.step("plan", "What goes in, oldest first") as st:
        topics = d.get("topics") or []
        items = sorted(d["items"], key=lambda it: -int(it.get("days_ago") or 0))
        st.data.update({"topics": [t["title"] for t in topics], "items": len(items), "questions": len(d["eval"])})
    with trace.step("people", "The example's own people, from its addresses, before anything is stored") as st:
        whos = []
        for it in items:
            whos += [it.get("from")] + ingest._list(it.get("to")) + ingest._list(it.get("cc"))
        st.data["people"] = people.seed_people(ds, whos)
    for t in topics:
        ingest.store(ds, dict(t, source_key=t["key"], said_at=(now - timedelta(days=int(t.get("days_ago") or 0))).isoformat()),
                     by="seed", wait=True)
    for i, it in enumerate(items):
        said = now - timedelta(days=int(it.get("days_ago") or 0), hours=max(0, 8 - (i % 8)), minutes=i)
        payload = {k: v for k, v in it.items() if k not in ("key", "days_ago", "text")}
        payload.update({"source_key": it["key"], "text": it["text"], "said_at": said.isoformat()})
        worker.heartbeat(ds["id"], "seed")
        got = ingest.store(ds, payload, by="seed", wait=True)
        stored += 1 if got.get("ok") else 0
        with trace.step("item", f"Stored {it['key']}: {it.get('title', '')}") as st:
            st.data.update({"ok": got.get("ok"), "item": got.get("item"), "trace": got.get("trace")})
    with trace.step("eval", "The evaluation set") as st:
        made = 0
        for q in d["eval"]:
            evaluate.add_question(ds, q["q"], gold=q.get("gold") or [], facts=q.get("facts") or [],
                                  asker=q.get("asker") or "", context=q.get("context") or "",
                                  forbidden=bool(q.get("forbidden")), group=q.get("grp") or "")
            made += 1
        st.data["questions"] = made
    trace.finish("done", stored=stored)
    # The map, now that everything is in, rather than ten minutes on (D17).
    from . import mapping
    try:
        mapping.build(ds, why="the example set is filled")
    except Exception:  # noqa: BLE001 - the queue will make it later
        pass
    return {"ok": True, "stored": stored}


def _keys(ds: dict) -> set[str]:
    return {r["source_key"] for r in db.rows("SELECT source_key FROM synapse.item WHERE dataset_id = %s "
                                             "AND deleted_at IS NULL", (ds["id"],))}


def dream_examples_missing(ds: dict) -> int:
    """How many of an example set's dream examples it does not have yet."""
    key = ds.get("example") or ""
    if key not in EXAMPLES:
        return 0
    have = _keys(ds)
    return sum(1 for it in load(key).get("dream") or [] if it["key"] not in have)


def add_dream_examples(ds: dict) -> dict:
    """The dream examples, put into an example set made before them, on the queue like a set's own filling."""
    key = ds.get("example") or ""
    if key not in EXAMPLES:
        return {"ok": False, "why": "Only the two example sets have dream examples."}
    if not dream_examples_missing(ds):
        return {"ok": False, "why": "It has every dream example already."}
    if db.value("SELECT 1 FROM synapse.job WHERE dataset_id = %s AND kind = 'seed' AND done_at IS NULL", (ds["id"],)):
        return {"ok": True, "queued": False, "why": "They are being added already."}
    ingest.enqueue(ds["id"], "seed", priority=1, payload={"example": key, "by": "page", "only": "dream"})
    worker.poke()
    return {"ok": True, "queued": True}
