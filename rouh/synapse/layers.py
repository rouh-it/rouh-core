"""Layers for heavily connected people and topics (D53 to D55).

Three kinds of layer item, each an X-ray whose claims cite the items below them
through `built_from` links, so a profile opens onto a topic layer, which opens
onto a thread, which opens onto the raw item:

- a **thread** layer once a thread has 4 items (starting value), updated on every new item;
- a **topic** layer for a person and topic pair once they share 10 items,
  updated at most once an hour;
- a **profile** for a person or topic with 30 items, at most once a day.

A layer is never rewritten (D54): the helper model is shown its current claims
and the new material and returns operations, add, replace claim i or retire
claim i with a reason, which code applies, keeping the old version first and
refusing to retire more than a quarter of the claims in one pass.

A layer is built only from items every one of its readers may see, and its
readers are the readers common to all of them (D55, D60).
"""
from __future__ import annotations

import math
from datetime import datetime, timezone

from . import ai, datasets, db, ingest, text as tx, vectors
from .db import Json
from .trace import Trace

OPS_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["gist", "ops"],
    "properties": {
        "gist": {"type": "string"},
        "ops": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["op", "claim", "c", "k", "s", "from", "why", "open"],
            "properties": {
                "op": {"type": "string", "enum": ["add", "replace", "retire"]},
                "claim": {"type": "integer"}, "c": {"type": "string"},
                "k": {"type": "string", "enum": ingest.CLAIM_KINDS},
                "s": {"type": "string", "enum": ingest.STRENGTHS},
                "from": {"type": "array", "items": {"type": "integer"}},
                "why": {"type": "string"}, "open": {"type": "boolean"}}}},
    },
}

OPS_INSTRUCTIONS = """You keep one layer of Synapse, a personal memory: a short X-ray of {what}, at most {size} claims, one sentence each, at most 30 words, with doubts kept as claims of their own.

You are shown the layer's CURRENT CLAIMS (numbered from 0) and the SOURCE ITEMS (numbered in brackets). Return operations, never a rewrite:
- add: a new claim, citing in "from" the source item numbers it rests on (at least one).
- replace: claim i (in "claim") is replaced by a new one, because a source changed or contradicts it; cite the sources.
- retire: claim i is no longer true or useful; say why.
Do not repeat a claim that is already there. Kinds: fact, ask, promise, decision, caveat, disagreement, open, rule; strength strong, moderate, mixed or weak; open is true for an ask or promise not done. For add use claim -1. gist: the layer's answer in one sentence. Open asks and promises come first."""


def _layer_key(kind: str, *ids) -> str:
    return f"{kind}:" + ":".join(str(i) for i in ids)


def _existing(ds_id: str, key: str) -> dict | None:
    return db.row("SELECT * FROM synapse.item WHERE dataset_id = %s AND kind = 'layer' AND source_key = %s "
                  "AND deleted_at IS NULL", (ds_id, key))


def _pending(ds_id: str, key: str) -> bool:
    return bool(db.value("SELECT count(*) FROM synapse.job WHERE dataset_id = %s AND kind = 'layer' "
                         "AND done_at IS NULL AND payload->>'key' = %s", (ds_id, key)))


def _rate_delay(layer: dict | None, minutes: float) -> float:
    if not layer or minutes <= 0:
        return 0.0
    last = (layer.get("meta") or {}).get("updated_at")
    if not last:
        return 0.0
    try:
        when = datetime.fromisoformat(last)
    except ValueError:
        return 0.0
    gone = (datetime.now(timezone.utc) - when).total_seconds()
    return max(0.0, minutes * 60 - gone)


def queue_for(ds: dict, item_id: str, s, trace=None) -> dict:
    """Which layers this item touches, and the jobs that will update them."""
    item = ingest.get_item(ds["id"], item_id) or {}
    meta = item.get("meta") or {}
    queued, waiting = [], []

    def want(kind: str, key: str, subject: dict, threshold: int, count: int, minutes: float, extra: dict):
        if count < threshold:
            waiting.append({"layer": kind, "of": subject.get("title"), "items": count, "needs": threshold})
            return
        layer = _existing(ds["id"], key)
        if _pending(ds["id"], key):
            queued.append({"layer": kind, "of": subject.get("title"), "items": count, "note": "already queued"})
            return
        delay = _rate_delay(layer, minutes)
        job = ingest.enqueue(ds["id"], "layer", priority=6, delay_s=delay,
                             payload={"layer": kind, "key": key, "subject": subject.get("id"),
                                      "new_item": item_id, **extra})
        queued.append({"layer": kind, "of": subject.get("title"), "items": count, "job": job,
                       "update": "update by diff" if layer else "first build",
                       "waits_s": int(delay)})

    if meta.get("thread") and item.get("kind") != "layer":
        n = db.value("SELECT count(*) FROM synapse.item WHERE dataset_id = %s AND meta->>'thread' = %s AND "
                     "deleted_at IS NULL AND kind <> 'layer'", (ds["id"], meta["thread"])) or 0
        want("thread", _layer_key("thread", meta["thread"]), {"id": None, "title": f"thread {meta['thread']}"},
             int(s.layer_thread), int(n), 0, {"thread": meta["thread"]})
    # Everyone on the item but the dataset's own person (whose contact was tier 2 before people were items).
    people = db.rows("SELECT c.id, c.title FROM synapse.link l JOIN synapse.item c ON c.id = l.dst "
                     "WHERE l.dataset_id = %s AND l.src = %s AND l.type IN ('from', 'to', 'cc') "
                     "AND c.kind = 'person' AND c.id::text <> %s", (ds["id"], item_id, str(datasets.me(ds))))
    topics = db.rows("SELECT t.id, t.title FROM synapse.link l JOIN synapse.item t ON t.dataset_id = l.dataset_id "
                     "AND t.id = l.dst WHERE l.dataset_id = %s AND l.src = %s AND l.type = 'about' "
                     "AND t.kind = 'topic' AND t.deleted_at IS NULL", (ds["id"], item_id))
    for p in people:
        for t in topics:
            n = db.value("SELECT count(DISTINCT a.src) FROM synapse.link a JOIN synapse.link b ON b.dataset_id = a.dataset_id "
                         "AND b.src = a.src WHERE a.dataset_id = %s AND a.dst = %s AND a.type IN ('from','to','cc') "
                         "AND b.dst = %s AND b.type = 'about'", (ds["id"], p["id"], t["id"])) or 0
            want("topic", _layer_key("topic", p["id"], t["id"]),
                 {"id": p["id"], "title": f"{p['title']} × {t['title']}"}, int(s.layer_topic), int(n),
                 float(s.topic_layer_minutes), {"person": p["id"], "topic": t["id"]})
    for subject in people + topics:
        n = db.value("SELECT count(DISTINCT l.src) FROM synapse.link l JOIN synapse.item i ON i.dataset_id = l.dataset_id "
                     "AND i.id = l.src WHERE l.dataset_id = %s AND l.dst = %s AND l.type <> 'built_from' "
                     "AND i.kind <> 'layer' AND i.deleted_at IS NULL", (ds["id"], subject["id"])) or 0
        want("profile", _layer_key("profile", subject["id"]), subject, int(s.layer_profile), int(n),
             float(s.profile_layer_minutes), {})
    return {"queued": queued, "not_yet": waiting,
            "thresholds": {"thread": int(s.layer_thread), "topic": int(s.layer_topic), "profile": int(s.layer_profile)}}


def queue_rebuild(ds: dict, layer_id: str, why: str) -> dict:
    layer = ingest.get_item(ds["id"], layer_id)
    if not layer:
        return {}
    meta = layer.get("meta") or {}
    payload = {"layer": meta.get("layer"), "key": layer["source_key"], "subject": meta.get("subject"),
               "thread": meta.get("thread"), "person": meta.get("person"), "topic": meta.get("topic"), "why": why}
    job = ingest.enqueue(ds["id"], "layer", priority=3, payload=payload)
    return {"layer": layer["title"], "job": job, "why": why}


def hide_claims_from(ds: dict, layer_id: str, item_id: str) -> dict:
    """Until a layer is rebuilt, its claims that cite a deleted item are hidden (D60, step 3)."""
    layer = ingest.get_item(ds["id"], layer_id)
    if not layer:
        return {}
    x = dict(layer.get("xray") or {})
    claims = x.get("claims") or []
    kept = [c for c in claims if item_id not in (c.get("from_ids") or [])]
    x["claims"] = kept
    db.run("UPDATE synapse.item SET xray = %s::jsonb WHERE id = %s", (Json(x), layer_id))
    return {"layer": layer["title"], "claims_hidden": len(claims) - len(kept), "claims_left": len(kept)}


def _sources(ds: dict, payload: dict) -> list[dict]:
    kind = payload.get("layer")
    me = datasets.me(ds)
    readable = ("AND EXISTS (SELECT 1 FROM synapse.reader r WHERE r.dataset_id = i.dataset_id AND r.item_id = i.id "
                "AND r.principal IN (%s, 'everyone'))")
    if kind == "thread":
        return db.rows("SELECT i.* FROM synapse.item i WHERE i.dataset_id = %s AND i.meta->>'thread' = %s AND "
                       f"i.deleted_at IS NULL AND i.kind <> 'layer' {readable} ORDER BY i.said_at",
                       (ds["id"], payload.get("thread"), me))
    if kind == "topic":
        return db.rows("SELECT DISTINCT i.* FROM synapse.item i JOIN synapse.link a ON a.dataset_id = i.dataset_id "
                       "AND a.src = i.id JOIN synapse.link b ON b.dataset_id = i.dataset_id AND b.src = i.id "
                       "WHERE i.dataset_id = %s AND a.dst = %s AND a.type IN ('from','to','cc') AND b.dst = %s AND "
                       f"b.type = 'about' AND i.deleted_at IS NULL AND i.kind <> 'layer' {readable} ",
                       (ds["id"], payload.get("person"), payload.get("topic"), me))
    # profile: prefer the layers below, then the items themselves.
    below = db.rows("SELECT i.* FROM synapse.item i JOIN synapse.link l ON l.dataset_id = i.dataset_id AND l.src = i.id "
                    "WHERE i.dataset_id = %s AND i.kind = 'layer' AND l.type = 'about' AND l.dst = %s "
                    "AND i.deleted_at IS NULL AND i.meta->>'layer' IN ('topic', 'thread')", (ds["id"], payload.get("subject")))
    items = db.rows("SELECT DISTINCT i.* FROM synapse.item i JOIN synapse.link l ON l.dataset_id = i.dataset_id "
                    "AND l.src = i.id WHERE i.dataset_id = %s AND l.dst = %s AND l.type <> 'built_from' "
                    f"AND i.kind NOT IN ('layer', 'rule') AND i.deleted_at IS NULL {readable} ",
                    (ds["id"], payload.get("subject"), me))
    items.sort(key=lambda r: str(r.get("said_at") or ""), reverse=True)
    return below + items[:60]


def build(ds: dict, payload: dict, *, by: str = "worker") -> dict:
    """Build or update one layer by diff (D54)."""
    s = datasets.settings(ds)
    owner = datasets.owner_of(ds)
    kind = payload.get("layer")
    key = payload.get("key")
    sources = _sources(ds, payload)
    layer = _existing(ds["id"], key)
    subject = ingest.get_in_scope(ds, payload.get("subject")) if payload.get("subject") else None
    if kind == "thread":
        name = f"Thread layer: {sources[0]['title'] if sources else payload.get('thread')}"
    elif kind == "topic":
        topic = ingest.get_item(ds["id"], payload.get("topic")) or {}
        name = f"Topic layer: {(subject or {}).get('title', '')} × {topic.get('title', '')}"
    else:
        name = f"Profile: {(subject or {}).get('title', '')}"
    trace = Trace(ds["id"], "layer", name, by=by, item_id=layer["id"] if layer else None)
    size = int({"thread": s.layer_thread_claims, "topic": s.layer_topic_claims}.get(kind, s.layer_profile_claims))
    try:
        with trace.step("sources", "What the layer is built from (D53, D55)") as st:
            readers = None
            for src in sources:
                r = set(ingest.readers_of(ds["id"], src["id"]))
                readers = r if readers is None else readers & (r | ({"everyone"} if "everyone" in r else set()))
            readers = sorted(readers or {datasets.me(ds)})
            st.data.update({"layer": kind, "sources": [{"title": x["title"], "kind": x["kind"]} for x in sources],
                            "count": len(sources), "readers": readers, "why": payload.get("why") or "",
                            "note": "Readers are the ones common to every source (D55): a layer never "
                                    "shows anyone more than all of its sources would."})
        if not sources:
            trace.finish("done", note="nothing to build from")
            return {"ok": True, "empty": True}
        current = ((layer or {}).get("xray") or {}).get("claims") or []
        with trace.step("ops", "Operations from the helper model, never a rewrite (D54)") as st:
            listing = "\n".join(f"{i}: {tx.claim_line(c)}" for i, c in enumerate(current)) or "none yet"
            src_lines = "\n".join(tx.compact(i + 1, x, raw_chars=600) for i, x in enumerate(sources))
            what = {"thread": "one email thread", "topic": "what a person and the owner have said on one topic",
                    "profile": "who a person or topic is to the owner"}.get(kind, "a layer")
            got = ai.generate(model=s.helper_model, name="layer_ops", purpose=f"layer_{kind}", trace=trace,
                              items=[x["id"] for x in sources], owner=owner, schema=OPS_SCHEMA,
                              instructions=OPS_INSTRUCTIONS.format(what=what, size=size),
                              text=f"CURRENT CLAIMS:\n{listing}\n\nSOURCE ITEMS:\n{src_lines}", max_tokens=5000)
            st.data.update({"model": got.get("_model"), "ops": got.get("ops") or [], "gist": got.get("gist")})
        with trace.step("apply", "Code applies them, at most a quarter retired in one pass (D54)") as st:
            ops = got.get("ops") or []
            cap = max(1, math.floor(len(current) * float(s.layer_removal_cap))) if current else 0
            removing = [o for o in ops if o["op"] in ("retire", "replace") and 0 <= o.get("claim", -1) < len(current)]
            refused = []
            if len(removing) > cap:
                refused = removing[cap:]
                removing = removing[:cap]
            new = list(current)
            retired = []
            for o in removing:
                i = o["claim"]
                old = current[i]
                retired.append({"claim": old.get("c"), "op": o["op"], "why": o.get("why")})
                new[i] = None
                if o["op"] == "replace":
                    new.append(_claim(o, sources))
            for o in ops:
                if o["op"] == "add":
                    new.append(_claim(o, sources))
            new = [c for c in new if c and c.get("from_ids")]
            new.sort(key=lambda c: (0 if c.get("k") in ("ask", "promise") and c.get("open") else 1))
            new = new[:size]
            st.data.update({"before": len(current), "after": len(new), "retired": retired,
                            "refused_over_cap": [o.get("claim") for o in refused], "cap": cap,
                            "added": [c["c"] for c in new if c not in current]})
        with trace.step("store", "The layer stored, its old version kept, built_from links written") as st:
            xray = {"x": 1, "gist": got.get("gist") or "", "claims": new, "layer": kind}
            meta = {"layer": kind, "subject": payload.get("subject"), "thread": payload.get("thread"),
                    "person": payload.get("person"), "topic": payload.get("topic"),
                    "updated_at": datetime.now(timezone.utc).isoformat(), "sources": len(sources)}
            by_info = {"model": got.get("_model"), "at": meta["updated_at"], "purpose": f"layer_{kind}"}
            if layer:
                db.run("INSERT INTO synapse.item_version (dataset_id, item_id, version, title, raw, meta, xray, xray_by, "
                       "keep_until, why) VALUES (%s, %s, %s, %s, '', %s::jsonb, %s::jsonb, %s::jsonb, "
                       "now() + make_interval(days => %s), 'layer update')",
                       (ds["id"], layer["id"], layer["version"], layer["title"], Json(layer.get("meta") or {}),
                        Json(layer.get("xray")), Json(layer.get("xray_by") or {}), int(s.version_days)))
                db.run("UPDATE synapse.item SET xray = %s::jsonb, xray_by = %s::jsonb, meta = %s::jsonb, title = %s, "
                       "version = version + 1, updated_at = now(), said_at = now() WHERE id = %s",
                       (Json(xray), Json(by_info), Json(meta), name, layer["id"]))
                layer_id = layer["id"]
            else:
                row = db.row("INSERT INTO synapse.item (dataset_id, kind, source, source_key, title, raw, body, tier, "
                             "tier_why, sensitivity, owner, meta, xray, xray_by, status, said_at) VALUES "
                             "(%s, 'layer', 'synapse', %s, %s, '', '', 2, 'a layer', %s, %s, %s::jsonb, %s::jsonb, "
                             "%s::jsonb, 'ready', now()) RETURNING id",
                             (ds["id"], key, name, ingest._ceiling([x["sensitivity"] for x in sources]),
                              datasets.me(ds), Json(meta), Json(xray), Json(by_info)))
                layer_id = row["id"]
            trace.set_item(layer_id)
            ingest.set_readers(ds["id"], layer_id, readers)
            db.run("DELETE FROM synapse.link WHERE dataset_id = %s AND src = %s AND type = 'built_from'", (ds["id"], layer_id))
            for src in sources:
                ingest.add_link(ds["id"], layer_id, src["id"], "built_from", s.code_strength("built_from"),
                                origin="code", made_by="code", why="this layer was built from it")
            if payload.get("subject"):
                ingest.add_link(ds["id"], layer_id, payload["subject"], "about", float(s.strength_strong),
                                origin="code", made_by="code", why=f"the {kind} layer of it")
            if payload.get("topic"):
                ingest.add_link(ds["id"], layer_id, payload["topic"], "about", float(s.strength_strong),
                                origin="code", made_by="code", why=f"the {kind} layer of it")
            ingest.derive(ds["id"], "item", layer_id, [x["id"] for x in sources])
            db.run("DELETE FROM synapse.passage WHERE dataset_id = %s AND item_id = %s", (ds["id"], layer_id))
            joined = name + "\n" + xray["gist"] + "\n" + "\n".join(tx.claim_line(c) for c in new)
            db.run("INSERT INTO synapse.passage (dataset_id, item_id, seq, text, words, from_xray) VALUES "
                   "(%s, %s, NULL, %s, to_tsvector('english', %s) || to_tsvector('synapse.bg', %s) || "
                   "to_tsvector('simple', %s), true)", (ds["id"], layer_id, joined, joined, joined, joined))
            passage = db.value("SELECT id FROM synapse.passage WHERE dataset_id = %s AND item_id = %s",
                               (ds["id"], layer_id))
            vectors.store(ds, [{"id": passage, "text": joined}], trace=trace, purpose="embed_layer",
                          items=[layer_id], owner=owner)
            st.data.update({"layer_id": layer_id, "claims": len(new), "built_from": len(sources),
                            "version": (layer or {}).get("version", 0) + 1})
        trace.finish("done", claims=len(new))
        return {"ok": True, "layer": layer_id}
    except Exception as exc:
        trace.finish("failed", error=f"{type(exc).__name__}: {exc}")
        raise


def _claim(o: dict, sources: list[dict]) -> dict:
    ids = [sources[n - 1]["id"] for n in o.get("from") or [] if 1 <= n <= len(sources)]
    return {"c": o.get("c", ""), "k": o.get("k", "fact"), "s": o.get("s", "moderate"), "open": bool(o.get("open")),
            "from": [n for n in o.get("from") or [] if 1 <= n <= len(sources)], "from_ids": ids}
