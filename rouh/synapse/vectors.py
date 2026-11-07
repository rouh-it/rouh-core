"""Which model a dataset's vectors are, and moving them to another, safely.

Two embedding models' numbers mean nothing to each other: a question embedded
by voyage-4 and compared with a passage embedded by OpenAI gives a cosine that
looks like a score and is noise. So:

- **A dataset's vectors are one model's**, named on the dataset
  (`synapse.dataset.vec_model`). Everything stored is embedded with it,
  every question is embedded with it, and search reads only vectors of the
  model the question was made with (`search.py`). A passage that somehow holds
  another model's vector is found by its words only until it is swept.
- **A move is explicit**: somebody starts it, from the dataset's Vectors panel
  or `manage.py synapse_vectors move`. It never starts because a setting
  changed.
- **A move never touches what search reads until it is done and checked.**
  Each passage's new vector goes into a column beside the old one
  (`vec_next`), a batch at a time on Synapse's queue, so a restart, a rate
  limit or a failure stops it where it is and it carries on from there.
- **It is checked before search uses it**: every passage has a new vector,
  each has 1,024 numbers and is not empty, and a sample of passages, asked as
  questions in the new model, find themselves near the top
  (`verify`). Only then are the two columns swapped, in one transaction, so
  search goes from all-old to all-new at once.
- **Nothing is thrown away**: the old vectors stay in `vec_prev`, and
  `put_back` swaps them back.

The state of a move is `synapse.dataset.vec_move`: `{"state": "moving" |
"switched" | "failed" | "put_back", "from", "to", ...}`.
"""
from __future__ import annotations

import logging
import math
import time

from .. import clock
from . import ai, db
from .db import Json

log = logging.getLogger("rouh.synapse.vectors")

#: The fewest of the sampled passages that must find themselves in the top
#: `SELF_TOP` when asked as a question, for a move to be switched over.
SELF_PASS = 0.75
SELF_TOP = 5
SAMPLE = 8
#: How long one queue job keeps moving before it hands over to the next, so
#: the queue's ten-minute lock never runs out under it.
JOB_SECONDS = 300
#: A move that fails this many batches running stops and says why.
MAX_FAILS = 5


def live_model(ds_id: str) -> str:
    """The model this dataset's vectors are, read now."""
    return db.value("SELECT vec_model FROM synapse.dataset WHERE id = %s", (ds_id,)) or ""


def _move(ds_id: str) -> dict:
    return db.value("SELECT vec_move FROM synapse.dataset WHERE id = %s", (ds_id,)) or {}


def _set_move(ds_id: str, move: dict) -> None:
    db.run("UPDATE synapse.dataset SET vec_move = %s::jsonb WHERE id = %s", (Json(move), ds_id))


# --- what everything else calls ---------------------------------------------------------

def store(ds: dict, rows: list[dict], *, trace=None, purpose: str, items=(), owner=None) -> dict:
    """Embed these passages (`{"id", "text"}`) in the dataset's own model and keep them.

    A passage whose dataset changed model while it was being embedded is not
    written with the old one: it is embedded again in the new.
    """
    if not rows:
        return {"passages": 0, "model": live_model(ds["id"])}
    first: list[float] = []
    model = ""
    total = len(rows)
    for _ in range(2):
        model = live_model(ds["id"])
        vectors = ai.embed([r["text"] for r in rows], model=model, trace=trace, purpose=purpose,
                           items=items, owner=owner, input_type="document")
        first = first or (vectors[0] if vectors else [])
        missed = []
        for r, v in zip(rows, vectors):
            n = db.run("UPDATE synapse.passage p SET vec = %s::halfvec, embed_model = %s "
                       "WHERE p.id = %s AND p.dataset_id = %s AND %s = (SELECT d.vec_model FROM synapse.dataset d "
                       "WHERE d.id = p.dataset_id)", (db.vec(v), model, r["id"], ds["id"], model))
            if not n:
                missed.append(r)
        if not missed:
            break
        rows = missed
    return {"passages": total, "model": model, "dims": len(first),
            "stored_as": "halfvec (2 bytes a number)", "sample": [round(x, 4) for x in first[:12]],
            "norm": round(math.sqrt(sum(x * x for x in first)), 4) if first else 0}


def query(ds: dict, text: str, *, trace=None, purpose: str = "embed_query", owner=None) -> dict:
    """A question's vector in the dataset's own model, or none and why.

    Search by words never needs one, so a question whose vector cannot be
    made - no key, Voyage refusing or out of reach - is answered by words
    alone, and the reason goes on the trace. It is never embedded with
    another model instead: those numbers would be compared with these.
    """
    model = live_model(ds["id"])
    if not ai.can_embed(model):
        return {"vec": None, "model": model, "why": f"no key for {model} on this machine: words only"}
    try:
        vec = ai.embed([text], model=model, trace=trace, purpose=purpose, owner=owner, input_type="query")[0]
    except Exception as exc:  # noqa: BLE001 - words still answer
        log.warning("Synapse could not embed a question with %s: %s", model, type(exc).__name__)
        return {"vec": None, "model": model, "why": f"{type(exc).__name__}: {exc}"[:300] + " - words only"}
    return {"vec": vec, "model": model, "why": ""}


# --- where a dataset stands -------------------------------------------------------------

def status(ds: dict) -> dict:
    ds_id = ds["id"]
    move = _move(ds_id)
    target = move.get("to") or ""
    model = live_model(ds_id)
    c = db.row(
        "SELECT count(*) AS passages, count(vec) AS vectors, "
        " count(*) FILTER (WHERE vec IS NOT NULL AND embed_model = %s) AS on_model, "
        " count(*) FILTER (WHERE vec IS NOT NULL AND embed_model <> %s) AS strays, "
        " count(*) FILTER (WHERE vec IS NOT NULL AND vec_next IS NOT NULL AND next_model = %s) AS staged, "
        " count(*) FILTER (WHERE vec_prev IS NOT NULL) AS kept "
        "FROM synapse.passage WHERE dataset_id = %s", (model, model, target, ds_id)) or {}
    return {"model": model, "move": move, "counts": c, "keys": {
        m: ai.can_embed(m) for m in (*ai.VOYAGE_MODELS, *ai.OPENAI_EMBED_MODELS)}}


# --- a move ---------------------------------------------------------------------------

def start(ds: dict, to: str, *, by: str = "page") -> dict:
    """Start moving this dataset's vectors to `to`, or carry on with a move
    that stopped. Says no rather than starting something it cannot finish."""
    if to not in ai.VOYAGE_MODELS + ai.OPENAI_EMBED_MODELS:
        return {"ok": False, "why": f"{to} is not an embedding model Synapse knows"}
    model = live_model(ds["id"])
    if to == model:
        return {"ok": False, "why": f"this dataset's vectors are already {to}"}
    if not ai.can_embed(to):
        return {"ok": False, "why": f"this machine has no key for {to}"}
    move = _move(ds["id"])
    carrying_on = move.get("state") in ("moving", "failed") and move.get("to") == to
    if move.get("state") == "moving" and move.get("to") != to:
        return {"ok": False, "why": f"a move to {move.get('to')} is under way; put it back or let it finish"}
    # A staged vector of some other model is no use to this move.
    db.run("UPDATE synapse.passage SET vec_next = NULL, next_model = '' WHERE dataset_id = %s "
           "AND next_model <> '' AND next_model <> %s", (ds["id"], to))
    move = {"state": "moving", "from": model, "to": to, "by": by,
            "started_at": move.get("started_at") if carrying_on else clock.utc_iso(timespec="seconds"),
            "carried_on_at": clock.utc_iso(timespec="seconds") if carrying_on else None, "fails": 0, "error": "",
            "verification": None}
    _set_move(ds["id"], move)
    _enqueue(ds["id"])
    return {"ok": True, "move": move, "carrying_on": carrying_on}


def _enqueue(ds_id: str, delay_s: float = 0) -> None:
    from . import ingest

    if db.value("SELECT count(*) FROM synapse.job WHERE dataset_id = %s AND kind = 'revector' "
                "AND done_at IS NULL AND locked_by IS NULL", (ds_id,)):
        return
    ingest.enqueue(ds_id, "revector", priority=7, delay_s=delay_s)


def _to_stage(ds_id: str, to: str, limit: int = 64) -> list[dict]:
    return db.rows("SELECT p.id, p.text, p.from_xray, p.item_id, i.title FROM synapse.passage p "
                   "JOIN synapse.item i ON i.dataset_id = p.dataset_id AND i.id = p.item_id "
                   "WHERE p.dataset_id = %s AND p.vec IS NOT NULL AND (p.vec_next IS NULL OR p.next_model <> %s) "
                   "ORDER BY p.id LIMIT %s", (ds_id, to, limit))


def _text_of(r: dict) -> str:
    """What a passage is embedded from: the same words `ingest.embed_item` uses."""
    return r["text"] if r["from_xray"] else ((r.get("title") or "") + "\n" + r["text"])


def work(ds: dict, *, seconds: float = JOB_SECONDS) -> dict:
    """One queue job's share of whatever this dataset's vectors need."""
    move = _move(ds["id"])
    if move.get("state") == "moving":
        return _carry_on(ds, move, seconds)
    return {"swept": sweep(ds)}


def _carry_on(ds: dict, move: dict, seconds: float) -> dict:
    from . import worker

    to = move["to"]
    began = time.time()
    staged = 0
    while time.time() - began < seconds:
        rows = _to_stage(ds["id"], to)
        if not rows:
            return {"staged": staged, **verify_and_switch(ds)}
        batch = ai._chunks([_text_of(r) for r in rows], to)[0]
        rows = rows[:len(batch)]
        try:
            vectors = ai.embed(batch, model=to, purpose="revector", owner=_owner(ds), input_type="document",
                               items=[r["item_id"] for r in rows])
        except Exception as exc:  # noqa: BLE001 - kept where it got to
            move = _move(ds["id"])
            move["fails"] = int(move.get("fails") or 0) + 1
            move["error"] = f"{type(exc).__name__}: {exc}"[:400]
            if move["fails"] >= MAX_FAILS:
                move["state"] = "failed"
                move["failed_at"] = clock.utc_iso(timespec="seconds")
                _set_move(ds["id"], move)
                return {"staged": staged, "failed": move["error"]}
            _set_move(ds["id"], move)
            _enqueue(ds["id"], delay_s=60)
            return {"staged": staged, "waiting": move["error"]}
        for r, v in zip(rows, vectors):
            db.run("UPDATE synapse.passage SET vec_next = %s::halfvec, next_model = %s WHERE id = %s "
                   "AND dataset_id = %s", (db.vec(v), to, r["id"], ds["id"]))
        staged += len(rows)
        move = _move(ds["id"])
        if move.get("state") != "moving" or move.get("to") != to:
            return {"staged": staged, "stopped": "the move was changed meanwhile"}
        move.update({"fails": 0, "error": "", "last_batch_at": clock.utc_iso(timespec="seconds")})
        _set_move(ds["id"], move)
        worker.heartbeat(ds["id"], "revector")
    _enqueue(ds["id"])
    return {"staged": staged, "more": True}


def _owner(ds: dict) -> dict:
    return {"user_id": ds["user_id"], "org_id": ds["org_id"]}


def verify(ds: dict, to: str) -> dict:
    """Whether the staged vectors are fit to be searched, and what was looked at."""
    ds_id = ds["id"]
    c = db.row(
        "SELECT count(*) FILTER (WHERE vec IS NOT NULL) AS live, "
        " count(*) FILTER (WHERE vec IS NOT NULL AND (vec_next IS NULL OR next_model <> %s)) AS missing, "
        " count(*) FILTER (WHERE vec_next IS NOT NULL AND next_model = %s "
        "   AND vector_dims(vec_next::vector) <> %s) AS wrong_dims, "
        " count(*) FILTER (WHERE vec_next IS NOT NULL AND next_model = %s "
        "   AND l2_norm(vec_next) < 0.01) AS empty "
        "FROM synapse.passage WHERE dataset_id = %s", (to, to, ai.EMBED_DIMS, to, ds_id)) or {}
    out = {"at": clock.utc_iso(timespec="seconds"), "live": c.get("live", 0), "missing": c.get("missing", 0),
           "wrong_dims": c.get("wrong_dims", 0), "empty": c.get("empty", 0), "dims": ai.EMBED_DIMS,
           "sample": 0, "found_themselves": 0, "top": SELF_TOP}
    problems = []
    if out["missing"]:
        problems.append(f"{out['missing']} passages have no {to} vector yet")
    if out["wrong_dims"]:
        problems.append(f"{out['wrong_dims']} vectors are not {ai.EMBED_DIMS} numbers")
    if out["empty"]:
        problems.append(f"{out['empty']} vectors are empty")
    staged = db.rows("SELECT p.id, p.text, p.from_xray, i.title FROM synapse.passage p "
                     "JOIN synapse.item i ON i.dataset_id = p.dataset_id AND i.id = p.item_id "
                     "WHERE p.dataset_id = %s AND p.vec_next IS NOT NULL AND p.next_model = %s "
                     "AND length(p.text) >= 40 ORDER BY p.id", (ds_id, to))
    if not problems and len(staged) >= 2:
        step = max(1, len(staged) // SAMPLE)
        sample = staged[::step][:SAMPLE]
        # A question is a passage's opening words, not the whole of it, so
        # finding itself is a real test of the query side.
        asks = [" ".join(_text_of(r).split()[:40]) for r in sample]
        try:
            qvecs = ai.embed(asks, model=to, purpose="revector_check", owner=_owner(ds), input_type="query")
        except Exception as exc:  # noqa: BLE001
            problems.append(f"the check's questions could not be embedded: {type(exc).__name__}: {exc}"[:300])
            qvecs = []
        hits = 0
        for r, q in zip(sample, qvecs):
            top = db.rows("SELECT id FROM synapse.passage WHERE dataset_id = %s AND vec_next IS NOT NULL "
                          "AND next_model = %s ORDER BY vec_next <=> %s::halfvec LIMIT %s",
                          (ds_id, to, db.vec(q), SELF_TOP))
            hits += any(t["id"] == r["id"] for t in top)
        out["sample"], out["found_themselves"] = len(qvecs), hits
        if qvecs and hits / len(qvecs) < SELF_PASS:
            problems.append(f"only {hits} of {len(qvecs)} passages found themselves in the top {SELF_TOP}")
    out["ok"] = not problems
    out["problems"] = problems
    return out


def verify_and_switch(ds: dict) -> dict:
    move = _move(ds["id"])
    to = move.get("to")
    check = verify(ds, to)
    move = _move(ds["id"])
    move["verification"] = check
    if not check["ok"]:
        if check["missing"]:
            # Something new came in meanwhile: stage it and check again.
            _set_move(ds["id"], move)
            _enqueue(ds["id"])
            return {"verified": False, "again": True}
        move.update({"state": "failed", "failed_at": clock.utc_iso(timespec="seconds"), "error": "; ".join(check["problems"])})
        _set_move(ds["id"], move)
        return {"verified": False, "why": move["error"]}
    _set_move(ds["id"], move)
    return {"verified": True, **switch(ds)}


def switch(ds: dict) -> dict:
    """Search moves to the new vectors, all at once, keeping the old ones."""
    with db.atomic():
        move = db.value("SELECT vec_move FROM synapse.dataset WHERE id = %s FOR UPDATE", (ds["id"],)) or {}
        to = move.get("to")
        if move.get("state") != "moving" or not (move.get("verification") or {}).get("ok"):
            return {"switched": False, "why": "the move is not checked"}
        missing = db.value("SELECT count(*) FROM synapse.passage WHERE dataset_id = %s AND vec IS NOT NULL "
                           "AND (vec_next IS NULL OR next_model <> %s)", (ds["id"], to))
        if missing:
            return {"switched": False, "why": f"{missing} passages came in since the check"}
        n = db.run("UPDATE synapse.passage SET vec_prev = vec, prev_model = embed_model, vec = vec_next, "
                   "embed_model = next_model, vec_next = NULL, next_model = '' "
                   "WHERE dataset_id = %s AND vec_next IS NOT NULL AND next_model = %s", (ds["id"], to))
        move.update({"state": "switched", "switched_at": clock.utc_iso(timespec="seconds"), "switched": n})
        db.run("UPDATE synapse.dataset SET vec_model = %s, vec_move = %s::jsonb WHERE id = %s",
               (to, Json(move), ds["id"]))
    log.info("Synapse dataset %s now searches %d %s vectors (was %s)", ds["id"], n, to, move.get("from"))
    _enqueue(ds["id"], delay_s=5)
    return {"switched": True, "passages": n}


def put_back(ds: dict, *, by: str = "page") -> dict:
    """Undo a switched move: the old vectors back where search reads them."""
    move = _move(ds["id"])
    if move.get("state") == "moving":
        move.update({"state": "put_back", "put_back_at": clock.utc_iso(timespec="seconds"), "by_put_back": by})
        _set_move(ds["id"], move)
        db.run("UPDATE synapse.passage SET vec_next = NULL, next_model = '' WHERE dataset_id = %s", (ds["id"],))
        return {"ok": True, "note": "the move was stopped; search never left " + str(move.get("from"))}
    if move.get("state") != "switched":
        return {"ok": False, "why": "there is no switched move to put back"}
    old = move.get("from")
    with db.atomic():
        db.value("SELECT id FROM synapse.dataset WHERE id = %s FOR UPDATE", (ds["id"],))
        n = db.run("UPDATE synapse.passage SET vec = vec_prev, embed_model = prev_model, "
                   "vec_prev = vec, prev_model = embed_model "
                   "WHERE dataset_id = %s AND vec_prev IS NOT NULL AND prev_model = %s", (ds["id"], old))
        move.update({"state": "put_back", "put_back_at": clock.utc_iso(timespec="seconds"), "put_back": n, "by_put_back": by})
        db.run("UPDATE synapse.dataset SET vec_model = %s, vec_move = %s::jsonb WHERE id = %s",
               (old, Json(move), ds["id"]))
    _enqueue(ds["id"], delay_s=5)
    return {"ok": True, "passages": n, "model": old}


def sweep(ds: dict) -> int:
    """Embed again, in the dataset's own model, any passage holding another's."""
    model = live_model(ds["id"])
    if not ai.can_embed(model):
        return 0
    rows = db.rows("SELECT p.id, p.text, p.from_xray, p.item_id, i.title FROM synapse.passage p "
                   "JOIN synapse.item i ON i.dataset_id = p.dataset_id AND i.id = p.item_id "
                   "WHERE p.dataset_id = %s AND p.vec IS NOT NULL AND p.embed_model <> %s ORDER BY p.id LIMIT 200",
                   (ds["id"], model))
    if not rows:
        return 0
    got = store(ds, [{"id": r["id"], "text": _text_of(r)} for r in rows], purpose="revector_sweep",
                owner=_owner(ds), items=list({r["item_id"] for r in rows}))
    return int(got.get("passages") or 0)
