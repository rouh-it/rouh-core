"""A frozen copy of Synapse Master, for the benchmark (Petar, 5 October 2026).

Master re-syncs every ten minutes, so a benchmark scored on it would drift from night to night. So the benchmark
runs on a snapshot: a lab dataset, "Benchmark: Synapse Master (frozen)", owned by Master's owner, holding Master's items
as they were at one moment with their X-rays, passages and vectors, links, readers, identities and map, copied
in SQL with new ids. No model is called for the copy.

It is marked `frozen` (migration 0088): nothing stores into it, edits it or deletes from it
(`ingest.FROZEN_WORDS`), the lab does not delete it, no sync reads it, and a nightly run never changes it.
Synapse's code is the same for Master and the copy, so a change measured on the copy carries over to Master.

The copy is taken only once Master's backfill lane has nothing left to read, and every gold item that gets an
X-ray must have one (`freeze` refuses otherwise, and says which).
"""
from __future__ import annotations

import logging

from . import db, people

log = logging.getLogger(__name__)

NAME = "Benchmark: Synapse Master (frozen)"

ITEM_COLUMNS = ("kind", "source", "source_key", "title", "raw", "body", "said_at", "stored_at", "updated_at", "tier",
                "tier_why", "sensitivity", "sensitivity_why", "meta", "xray", "xray_by", "xray_dropped", "status",
                "version", "tier_by", "tier_signals", "mentions", "mentions_gold")
#: `lexemes`, where pg_search is installed, is generated from `words`, so it is never copied.
PASSAGE_COLUMNS = ("seq", "text", "words", "vec", "from_xray", "embed_model", "part", "sha256", "meta")
LINK_COLUMNS = ("type", "strength", "base_strength", "origin", "made_by", "claim_idx", "why", "evidence", "made_at",
                "checked_at")


def waiting(src: dict) -> dict:
    """What Master still has to read: backfill-lane model jobs not done, and X-rayable items with no X-ray."""
    jobs = db.value("SELECT count(*) FROM synapse.job WHERE dataset_id = %s AND done_at IS NULL AND lane = 'backfill'",
                    (src["id"],)) or 0
    unread = db.value("SELECT count(*) FROM synapse.item WHERE dataset_id = %s AND deleted_at IS NULL AND kind NOT IN "
                      "('person', 'topic', 'layer', 'rule') AND (xray IS NULL OR xray::text IN ('{}', 'null'))",
                      (src["id"],)) or 0
    return {"backfill_jobs": int(jobs), "items_without_xray": int(unread)}


def existing(org_id: str, user_id: str) -> dict | None:
    return db.row("SELECT * FROM synapse.dataset WHERE org_id = %s AND user_id = %s AND frozen AND name = %s "
                  "ORDER BY created_at DESC LIMIT 1", (str(org_id), str(user_id), NAME))


def freeze(src: dict, *, gold_keys: list[str] = (), name: str = NAME) -> dict:
    """Copy `src` into a new frozen dataset of the same owner, in one transaction. Returns the new dataset and counts.

    Refuses while the backfill lane still has Master's items to read, or when a gold item that gets an X-ray has
    none, so the snapshot never freezes a half-read memory."""
    w = waiting(src)
    if w["backfill_jobs"]:
        raise ValueError(f"Master's backfill lane still has {w['backfill_jobs']} items to read; take the snapshot "
                         "once it has finished.")
    if gold_keys:
        bad = db.rows("SELECT source_key, kind FROM synapse.item WHERE dataset_id = %s AND deleted_at IS NULL AND "
                      "source_key = ANY(%s) AND kind NOT IN ('person', 'topic', 'layer', 'rule') AND "
                      "(xray IS NULL OR xray::text IN ('{}', 'null'))", (src["id"], list(gold_keys)))
        if bad:
            raise ValueError("These gold items have no X-ray yet: " + ", ".join(r["source_key"] for r in bad))
        have = {r["source_key"] for r in db.rows("SELECT source_key FROM synapse.item WHERE dataset_id = %s AND "
                                                 "deleted_at IS NULL AND source_key = ANY(%s)",
                                                 (src["id"], list(gold_keys)))}
        missing = sorted(set(gold_keys) - have)
        if missing:
            raise ValueError("These gold items are not in Master: " + ", ".join(missing))
    cols = ", ".join(ITEM_COLUMNS)
    pcols = ", ".join(PASSAGE_COLUMNS)
    lcols = ", ".join(LINK_COLUMNS)
    with db.atomic():
        new = db.row(
            "INSERT INTO synapse.dataset (org_id, user_id, name, about, owner_name, tuning, vec_model, role, frozen) "
            "SELECT org_id, user_id, %s, %s, owner_name, tuning, vec_model, 'data', true FROM synapse.dataset "
            "WHERE id = %s RETURNING *",
            (name, f"A frozen copy of {src['name']}, taken once for the benchmark: never synced, and never changed by "
                   "a nightly run. " + f"{people.owner_name_of(src) or 'The owner'} is its only owner.", src["id"]))
        db.run("CREATE TEMP TABLE snap_map (old uuid PRIMARY KEY, new uuid NOT NULL DEFAULT uuidv7()) ON COMMIT DROP")
        db.run("INSERT INTO snap_map (old) SELECT id FROM synapse.item WHERE dataset_id = %s AND deleted_at IS NULL "
               "ORDER BY id", (src["id"],))
        # A principal is a person's item id or 'everyone'; the owner the same.
        remap = "coalesce((SELECT m.new::text FROM snap_map m WHERE m.old::text = {0}), {0})"
        n_items = db.run(
            f"INSERT INTO synapse.item (id, dataset_id, owner, {cols}) "
            f"SELECT m.new, %s, {remap.format('i.owner')}, {', '.join('i.' + c for c in ITEM_COLUMNS)} "
            "FROM synapse.item i JOIN snap_map m ON m.old = i.id", (new["id"],))
        n_readers = db.run(
            f"INSERT INTO synapse.reader (dataset_id, item_id, principal) "
            f"SELECT %s, m.new, {remap.format('r.principal')} FROM synapse.reader r JOIN snap_map m ON m.old = r.item_id "
            "WHERE r.dataset_id = %s", (new["id"], src["id"]))
        n_passages = db.run(
            f"INSERT INTO synapse.passage (dataset_id, item_id, {pcols}) "
            f"SELECT %s, m.new, {', '.join('p.' + c for c in PASSAGE_COLUMNS)} FROM synapse.passage p "
            "JOIN snap_map m ON m.old = p.item_id WHERE p.dataset_id = %s ORDER BY p.id", (new["id"], src["id"]))
        n_links = db.run(
            f"INSERT INTO synapse.link (dataset_id, src, dst, {lcols}) "
            f"SELECT %s, a.new, b.new, {', '.join('l.' + c for c in LINK_COLUMNS)} FROM synapse.link l "
            "JOIN snap_map a ON a.old = l.src JOIN snap_map b ON b.old = l.dst WHERE l.dataset_id = %s",
            (new["id"], src["id"]))
        n_ids = db.run(
            "INSERT INTO synapse.identity (scope_id, item_id, type, value, shown, source, made_at) "
            "SELECT %s, m.new, x.type, x.value, x.shown, x.source, x.made_at FROM synapse.identity x "
            "JOIN snap_map m ON m.old = x.item_id WHERE x.scope_id = %s", (new["id"], src["id"]))
        db.run(f"INSERT INTO synapse.map (dataset_id, viewer, version, text, lines, tokens, why, made_at) "
               f"SELECT %s, {remap.format('viewer')}, version, text, lines, tokens, why, made_at FROM synapse.map "
               "WHERE dataset_id = %s", (new["id"], src["id"]))
        db.run("INSERT INTO synapse.map_line (dataset_id, section, key, text, pinned, by, made_at, meta) "
               "SELECT %s, section, key, text, pinned, by, made_at, meta FROM synapse.map_line WHERE dataset_id = %s",
               (new["id"], src["id"]))
        db.run("UPDATE synapse.dataset SET me_id = (SELECT m.new FROM snap_map m WHERE m.old = %s) WHERE id = %s",
               (src.get("me_id"), new["id"]))
    new = db.row("SELECT * FROM synapse.dataset WHERE id = %s", (new["id"],))
    counts = {"items": n_items, "readers": n_readers, "passages": n_passages, "links": n_links, "identities": n_ids}
    log.info("froze %s as %s: %s", src["name"], new["id"], counts)
    return {"dataset": new, "counts": counts, "waiting_at_copy": w}
