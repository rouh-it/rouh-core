"""Dreaming: a nightly pass that compares Synapse's items over time (Petar, 5 October 2026; D86 to D92).

Synapse keeps every item and works out what matters when a question is asked, so OpenClaw's dreaming, which
promotes memories from a short-term tier to a long-term one, has nothing to do here, and nothing rewrites the
memory every night either. What Synapse lacked was a pass that compares items written at different times:
old facts won over new ones (the oldest code given as the latest, a landing time read from a deleted event),
open asks never closed, import mistakes piled up (a receipt stored four times, facts X-rayed as rules,
sensitivity inconsistent inside a thread), and usage feedback had to be run by hand.

**A night** (`run`), on Synapse Master at 04:00 on the backfill lane, or any dataset from the lab's Dream now:

1. **Gather** (code): the items made or changed since the last night, the oldest items no night has read yet
   (`dream_backfill_items`), and each one's neighbours: the same thread, the same person, the same task, the
   same topic, links one hop out, and the closest by words and meaning. Each item with its neighbours is a
   group; a group is never a subset of one already taken. Code also finds a thread whose items disagree on
   sensitivity, which needs no model.
2. **Judge** (the model, Dreaming's on the Models page, structured output): each group returns proposals only, each with
   its kind, the item and claim numbers, a one-sentence reason and quotes. Code checks every quote against
   the stored text, exactly as an X-ray's quotes are checked, and drops a proposal whose quotes fail, and
   one that breaks a rule of its kind (an older "new" item, a closed ask closed again).
3. **Learn**: the usage feedback (`learning.plan`, D57), each move a change of its own.
4. **Guard** (D89): a night that would change more than `dream_guard_share` of any area's claims or of its
   scope applies none of it and keeps every change waiting, and says so.
5. **Apply** (code): the only stage that writes. Replaced claims, closed asks, kept promises and link moves
   apply by themselves (`dream_auto_*`); merges, kind changes and sensitivity wait for Petar's Approve or
   Reject; contradictions are only shown. Before anything is applied, the previous state of every touched
   claim, link and item field is saved on the change (`before`), so one change or a whole night is undone
   exactly. Nothing edits or deletes an item's text: a replaced or closed claim is a `claim_note` beside it.

**The rules, in code (D88 to D92).** The model decides and code applies; the model never writes. Only Apply
writes. A night's spend stops at `dream_cap_usd`, cleanly. Dreaming never learns from its own output: the
judge reads items without any dream note, a quote must be in an item's own stored text, and nothing a night
asked counts as usage. A change is visible only to someone who can read every item it names (`readers`, the
intersection); a special item never meets an item its readers cannot all read in one judge call; deleting an
item removes every change and note that depends on it (`forget_item`).

**Retrieval** reads the notes (`notes_for`, `annotate`): a replaced claim is left to a marker when the claim
that replaced it is in the pack ("FACT (replaced 3 Oct by [n])"), and the newer item is brought into the pack
when the asker may read it; a closed ask is never under OPEN ASKS AND PROMISES; an item whose claims were
replaced ranks lower, and a duplicate kept as an alias gives way to its canonical item. Answers still cite
the items, never a note.
"""
from __future__ import annotations

import concurrent.futures
import difflib
import logging
import threading
import time
from datetime import datetime, timezone

from . import datasets, db, learning, search, text as tx
from .db import Json
from .trace import Trace

log = logging.getLogger("rouh.synapse.dreaming")

#: Every kind of change a night makes, in the order the page shows them.
KINDS = ("superseded", "ask_closed", "promise_kept", "duplicate", "misfiled_rule", "contradiction",
         "sensitivity_mismatch", "link_strength")
#: The kinds the model proposes; sensitivity is found by code, link moves come from usage feedback.
MODEL_KINDS = ("superseded", "ask_closed", "promise_kept", "duplicate", "misfiled_rule", "contradiction")
KIND_WORDS = {"superseded": "replaced", "ask_closed": "asks closed", "promise_kept": "promises kept",
              "duplicate": "duplicates", "misfiled_rule": "rule fixes", "contradiction": "contradictions",
              "sensitivity_mismatch": "sensitivity", "link_strength": "links"}
#: Which setting lets a kind apply by itself (D91); a kind with none is only ever shown.
AUTO_SETTING = {"superseded": "dream_auto_replaced", "ask_closed": "dream_auto_closed",
                "promise_kept": "dream_auto_closed", "link_strength": "dream_auto_links",
                "duplicate": "dream_auto_duplicates", "misfiled_rule": "dream_auto_kinds",
                "sensitivity_mismatch": "dream_auto_sensitivity"}
STATES = ("applied", "waiting", "rejected", "undone", "shown")
#: Never the subject of a night: people, topics and layers are made from items, rules are the owner's own.
NOT_DREAMED = ("person", "topic", "layer", "rule")
LEVEL = {"normal": 0, "private": 1, "special": 2}
NEW_KINDS = ("fact", "decision", "caveat", "open")
#: A run left `running` this long is a run a restart cut off.
STALE_HOURS = 6
#: The benchmark's frozen copy of Master (`snapshot.py`) is never dreamed over: nothing may change it.
FROZEN = ("This dataset is the benchmark's frozen copy of Synapse Master: nothing changes it, so it is never "
          "dreamed over.")
#: Draws a night on the orb (`runtime.OwnWork.note`), set by Rouh at start-up; None in a script.
orb = None


# --- the judge's words and its answer ------------------------------------------------------------

INSTRUCTIONS = """You compare the items of one person's memory, Synapse, written at different times, and propose corrections to how they are read. You never change anything yourself: code checks every quote you give against the items' stored text and applies only what passes.

Propose only what the items' own words show. The kinds:
- superseded: a claim (old_item, old_claim) is replaced by a later item's claim (new_item, new_claim): a newer code, a changed date or time, a changed price or amount, a cancelled or deleted event, a decision changed. new_item must be later than old_item. changed_on is the date the change was made, YYYY-MM-DD (the later item's date when nothing else says).
- ask_closed: an ASK claim marked open (old_item, old_claim) was answered or done, as a later item shows (new_item, and new_claim or -1).
- promise_kept: a PROMISE claim marked open was kept, as a later item shows.
- duplicate: old_item and new_item are the same thing stored twice: the same receipt, the same message, a forwarded copy of it. Two items with the same title and the same text are a duplicate. Never two different things about the same subject.
- misfiled_rule: a RULE claim (old_item, old_claim) is not a standing instruction from the owner but a fact, a contract term or a description; new_kind says what it is.
- contradiction: two current claims in different items disagree (old_item and old_claim, new_item and new_claim) and neither clearly replaces the other, such as two people giving different dates.

Never propose: anything joining two different things, a later item that only repeats the old value, an ask closed only by being asked again, a value replaced by a guess or an opinion, or anything about a claim that is already closed. Most groups need nothing: then return no proposals.

For each proposal:
- quotes: at least one short quote from every item it names, copied word for word from that item's TEXT or a claim's q, exactly as written. A proposal whose quotes are not in its items is thrown away.
- reason: one plain sentence of at most 30 words saying what changed and how the items show it. No em dashes.
- question, answer_before, answer_after: a question this change affects and its answer before and after the change, a few words each; all three empty when no question fits.
Unused numbers are -1 and unused text is empty."""

SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["proposals"],
    "properties": {"proposals": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["kind", "old_item", "old_claim", "new_item", "new_claim", "changed_on", "new_kind", "reason",
                     "quotes", "question", "answer_before", "answer_after"],
        "properties": {
            "kind": {"type": "string", "enum": list(MODEL_KINDS)},
            "old_item": {"type": "integer"}, "old_claim": {"type": "integer"},
            "new_item": {"type": "integer"}, "new_claim": {"type": "integer"},
            "changed_on": {"type": "string"},
            "new_kind": {"type": "string", "enum": [""] + list(NEW_KINDS)},
            "reason": {"type": "string"},
            "quotes": {"type": "array", "items": {
                "type": "object", "additionalProperties": False, "required": ["item", "quote"],
                "properties": {"item": {"type": "integer"}, "quote": {"type": "string"}}}},
            "question": {"type": "string"}, "answer_before": {"type": "string"}, "answer_after": {"type": "string"},
        }}}},
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _when(item: dict):
    return item.get("said_at") or item.get("stored_at")


def _ts(value) -> float:
    if not value:
        return 0.0
    if isinstance(value, datetime):
        return value.timestamp()
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _day(value) -> str:
    if not value:
        return ""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value[:10]
    return value.strftime("%Y-%m-%d")


def claims_of(item: dict) -> list[dict]:
    return list(((item.get("xray") or {}).get("claims")) or [])


def render(n: int, item: dict, *, text_chars: int = 700) -> str:
    """One item as the judge reads it: never a dream note (D92), every claim numbered with its quote."""
    meta = item.get("meta") or {}
    when = item.get("said_at")
    head = [str(item.get("kind") or "item")]
    if when:
        head.append(when.strftime("%-d %b %Y %H:%M") if isinstance(when, datetime) else str(when)[:16])
    who = tx._people(meta)
    if who:
        head.append(who)
    if item.get("title"):
        head.append(f'"{item["title"]}"')
    if meta.get("area"):
        head.append(f"area {meta['area']}")
    lines = [f"[{n}] " + " · ".join(head)]
    x = item.get("xray") or {}
    if x.get("gist"):
        lines.append(f"    GIST: {x['gist']}")
    for i, c in enumerate(claims_of(item)):
        line = f"    c{i} " + tx.claim_line(c)
        if c.get("q"):
            line += f' q: "{c["q"]}"'
        lines.append(line)
    body = " ".join((item.get("raw") or item.get("body") or "").split())
    if body:
        most = text_chars if claims_of(item) else text_chars * 2
        lines.append("    TEXT: " + body[:most] + ("..." if len(body) > most else ""))
    return "\n".join(lines)


# --- settings and rows -------------------------------------------------------------------------

def ready() -> bool:
    try:
        return bool(db.value("SELECT to_regclass('synapse.dream') IS NOT NULL"))
    except Exception:  # noqa: BLE001
        return False


def auto(s, kind: str) -> bool:
    key = AUTO_SETTING.get(kind)
    return bool(key and s.get(key, False))


def running(ds_id: str) -> dict | None:
    """The night of this dataset still running or queued, or None (one that a restart cut off is called failed)."""
    db.run("UPDATE synapse.dream SET status = 'failed', finished_at = now(), "
           "stopped_why = 'Rouh stopped while it was running, so it never finished.' "
           "WHERE dataset_id = %s AND status IN ('running', 'queued') AND started_at < now() - make_interval(hours => %s)",
           (ds_id, STALE_HOURS))
    return db.row("SELECT * FROM synapse.dream WHERE dataset_id = %s AND status IN ('running', 'queued') "
                  "ORDER BY number DESC LIMIT 1", (ds_id,))


def queue(ds: dict, *, by: str = "page") -> dict:
    """A night, asked for now: its row at once (so the page can show it waiting) and its job on the
    backfill lane, ahead of the backfill's own items. One at a time per dataset."""
    from . import ingest, worker

    if ds.get("frozen"):
        return {"ok": False, "why": FROZEN}
    busy = running(ds["id"])
    if busy:
        return {"ok": False, "dream": busy["id"], "number": busy["number"],
                "why": f"Night {busy['number']} is still {'waiting to start' if busy['status'] == 'queued' else 'running'}."}
    s = datasets.settings(ds)
    row = _new_row(ds, by, s, status="queued")
    ingest.enqueue(ds["id"], "dream", payload={"dream": row["id"], "by": by}, priority=1, lane="backfill")
    worker.poke()
    return {"ok": True, "dream": row["id"], "number": row["number"]}


def _new_row(ds: dict, by: str, s, status: str = "running") -> dict:
    with db.atomic():
        db.run("SELECT pg_advisory_xact_lock(hashtext(%s))", ("dream:" + str(ds["id"]),))
        number = int(db.value("SELECT coalesce(max(number), 0) + 1 FROM synapse.dream WHERE dataset_id = %s",
                              (ds["id"],)) or 1)
        return db.row("INSERT INTO synapse.dream (dataset_id, number, by, status, cap_usd) VALUES (%s, %s, %s, %s, %s) "
                      "RETURNING *", (ds["id"], number, by, status, float(s.dream_cap_usd)))


def _save(dream_id: str, **fields) -> None:
    sets, params = [], []
    for k, v in fields.items():
        sets.append(f"{k} = %s" + ("::jsonb" if isinstance(v, (dict, list)) else ""))
        params.append(Json(v) if isinstance(v, (dict, list)) else v)
    params.append(dream_id)
    db.run(f"UPDATE synapse.dream SET {', '.join(sets)} WHERE id = %s", params)


def _orb(kind: str, dream: dict, ds: dict, what: str = "") -> None:
    if orb is None:
        return
    try:
        orb({"type": kind, "where": "rouh", "id": f"dream-{dream['id']}", "name": "synapse_dream", "ok": True,
             "what": f"Dreaming over {ds['name']}", "detail": what})
    except Exception:  # noqa: BLE001 - the orb is never a reason a night fails
        log.debug("could not draw the night on the orb", exc_info=True)


# --- 1. gather ---------------------------------------------------------------------------------

ELIGIBLE = ("i.deleted_at IS NULL AND i.alias_of IS NULL AND i.status <> 'deleted' "
            f"AND i.kind NOT IN {tuple(NOT_DREAMED)!r}")
ITEM_COLS = ("i.id, i.kind, i.title, i.raw, i.body, i.said_at, i.stored_at, i.updated_at, i.sensitivity, i.owner, "
             "i.meta, i.xray, i.can_read, i.source, i.source_key, i.dreamed_at")


def _items(ds_id: str, ids) -> dict[str, dict]:
    ids = [str(i) for i in ids if i]
    if not ids:
        return {}
    return {r["id"]: r for r in db.rows(f"SELECT {ITEM_COLS} FROM synapse.item i WHERE i.dataset_id = %s "
                                        "AND i.id = ANY(%s::uuid[])", (ds_id, ids))}


def scope_of(ds: dict, s, since) -> dict:
    """What a night reads: what changed since the last one, and the oldest items no night has read."""
    changed = []
    if since is not None:
        changed = [r["id"] for r in db.rows(
            f"SELECT i.id FROM synapse.item i WHERE i.dataset_id = %s AND {ELIGIBLE} AND "
            "(i.stored_at > %s OR i.updated_at > %s OR (i.xray_by->>'at')::timestamptz > %s) "
            "ORDER BY coalesce(i.said_at, i.stored_at) LIMIT 5000", (ds["id"], since, since, since))]
    taken = set(changed)
    backfill = [r["id"] for r in db.rows(
        f"SELECT i.id FROM synapse.item i WHERE i.dataset_id = %s AND {ELIGIBLE} AND i.dreamed_at IS NULL "
        "AND (i.xray IS NOT NULL OR i.status = 'ready') ORDER BY coalesce(i.said_at, i.stored_at), i.id LIMIT %s",
        (ds["id"], int(s.dream_backfill_items) + len(taken)))]
    backfill = [i for i in backfill if i not in taken][:int(s.dream_backfill_items)]
    return {"changed": changed, "backfill": backfill}


def _near(ds_id: str, ids: list[str], seed: dict, most: int) -> list[str]:
    """Of `ids`, the `most` nearest in time to the seed."""
    if not ids:
        return []
    got = _items(ds_id, ids)
    at = _ts(_when(seed))
    ranked = sorted((i for i in ids if i in got), key=lambda i: abs(_ts(_when(got[i])) - at))
    return ranked[:most]


def neighbours(ds: dict, seed: dict, s, me: str) -> list[tuple[str, str]]:
    """The items worth comparing with one item, each with why, best first (D87)."""
    ds_id = ds["id"]
    out: dict[str, str] = {}
    meta = seed.get("meta") or {}

    def take(ids, why, most=None):
        for i in ids[:most] if most else ids:
            if i and i != seed["id"] and i not in out:
                out[i] = why
    eligible = f"SELECT i.id FROM synapse.item i WHERE i.dataset_id = %s AND {ELIGIBLE} AND i.id <> %s "
    # Stored twice: the same title, the same kind (a receipt four times).
    if seed.get("title"):
        take([r["id"] for r in db.rows(eligible + "AND i.kind = %s AND lower(i.title) = lower(%s) LIMIT 6",
                                       (ds_id, seed["id"], seed["kind"], seed["title"]))], "the same title")
    if meta.get("thread"):
        take(_near(ds_id, [r["id"] for r in db.rows(eligible + "AND i.meta->>'thread' = %s LIMIT 60",
                                                      (ds_id, seed["id"], str(meta["thread"])))], seed, 6),
             "the same thread")
    hop = db.rows("SELECT CASE WHEN l.src = %s THEN l.dst ELSE l.src END AS other, l.type FROM synapse.link l "
                  "JOIN synapse.item i ON i.dataset_id = l.dataset_id AND i.id = CASE WHEN l.src = %s THEN l.dst ELSE l.src END "
                  f"WHERE l.dataset_id = %s AND (l.src = %s OR l.dst = %s) AND {ELIGIBLE} "
                  "ORDER BY l.strength DESC LIMIT 12", (seed["id"], seed["id"], ds_id, seed["id"], seed["id"]))
    take([h["other"] for h in hop if h["type"] in ("updates", "contradicts", "follows_up", "continues", "reply_to",
                                                    "in_thread", "attached")], "linked to it")
    # The same task, the same topic: items linked the same way to the same thing.
    for link_type, why, most in (("in", "the same task", 3), ("about", "the same topic", 2)):
        targets = [r["dst"] for r in db.rows(
            "SELECT l.dst FROM synapse.link l WHERE l.dataset_id = %s AND l.src = %s AND l.type = %s LIMIT 4",
            (ds_id, seed["id"], link_type))]
        for t in targets:
            # A topic or task with thousands of items is a hub: only the few nearest in time to this item.
            take(_linked_near(ds_id, t, (link_type,), seed, most), why)
        if link_type == "in":
            take([t for t in targets if t in _eligible_ids(ds_id, targets)], "its task")
    # The same person, in any role: an ask from Sam and the owner's answer to him are the same person's.
    people_of = [r["dst"] for r in db.rows(
        "SELECT DISTINCT l.dst FROM synapse.link l WHERE l.dataset_id = ANY(synapse.scope(%s)) AND l.src = %s "
        "AND l.type IN ('from', 'to', 'cc') AND l.dst::text <> %s LIMIT 6", (ds_id, seed["id"], me))]
    for person in people_of:
        take(_linked_near(ds_id, person, ("from", "to", "cc"), seed, 3), "the same person")
    if int(s.dream_matches) > 0:
        words = " ".join([seed.get("title") or "", (seed.get("xray") or {}).get("gist") or ""]).strip() \
            or " ".join((seed.get("raw") or "").split()[:40])
        vec = search.item_vectors(ds_id, [seed["id"]]).get(seed["id"])
        try:
            found = search.hybrid(ds_id, words, vec, asker=me, settings=s, depth=int(s.dream_matches) + 6,
                                  exclude_ids=[seed["id"]], exclude_kinds=NOT_DREAMED)
            ids = [f["item_id"] for f in found["items"]]
            take([i for i in ids if i in _eligible_ids(ds_id, ids)], "close by words and meaning",
                 int(s.dream_matches))
        except Exception:  # noqa: BLE001 - the search is one source of neighbours among six
            log.debug("the closest-matches search failed for %s", seed["id"], exc_info=True)
    return list(out.items())[:int(s.dream_neighbours)]


def _linked_near(ds_id: str, target: str, types: tuple, seed: dict, most: int) -> list[str]:
    """Items linked to `target` by one of `types`, the `most` nearest in time to the seed."""
    return [r["src"] for r in db.rows(
        "SELECT x.src FROM (SELECT DISTINCT ON (l.src) l.src, abs(extract(epoch FROM coalesce(i.said_at, i.stored_at) "
        "- %s::timestamptz)) AS gap FROM synapse.link l JOIN synapse.item i ON i.dataset_id = l.dataset_id AND i.id = l.src "
        f"WHERE l.dataset_id = %s AND l.dst = %s AND l.type = ANY(%s) AND l.src <> %s AND {ELIGIBLE} ORDER BY l.src) x "
        "ORDER BY x.gap NULLS LAST LIMIT %s", (_when(seed), ds_id, target, list(types), seed["id"], int(most)))]


def _eligible_ids(ds_id: str, ids) -> set[str]:
    ids = [str(i) for i in ids if i]
    if not ids:
        return set()
    return {r["id"] for r in db.rows(f"SELECT i.id FROM synapse.item i WHERE i.dataset_id = %s AND i.id = ANY(%s::uuid[]) "
                                     f"AND {ELIGIBLE}", (ds_id, ids))}


def _may_meet(a: dict, b: dict) -> bool:
    """Whether two items may sit in one judge call: a special item only with items of its own owner that
    nobody but its own readers may read."""
    for x, y in ((a, b), (b, a)):
        if x.get("sensitivity") == "special":
            if y.get("owner") != x.get("owner") or not set(y.get("can_read") or []) <= set(x.get("can_read") or []):
                return False
    return True


def keep_apart(members: list[dict]) -> list[dict]:
    """A special item never meets, in one judge call, another owner's item or one read by anybody it is not
    read by (D92): the seed stays, and each neighbour joins only if it may meet everything already in."""
    kept: list[dict] = []
    for m in members:
        if all(_may_meet(m, k) for k in kept):
            kept.append(m)
    return kept


def groups_of(ds: dict, seeds: list[str], s, me: str, *, stop=None) -> list[dict]:
    """Each seed with its neighbours; a group that only repeats one already taken is left out."""
    out, seen = [], []
    items = _items(ds["id"], seeds)
    for sid in seeds:
        if stop is not None and stop():
            break
        seed = items.get(sid)
        if seed is None:
            continue
        near = neighbours(ds, seed, s, me)
        got = _items(ds["id"], [n for n, _ in near])
        members = [seed] + [got[n] for n, _ in near if n in got]
        members = keep_apart(members)
        ids = frozenset(m["id"] for m in members)
        if len(ids) < 2 or any(ids <= old for old in seen):
            continue
        seen.append(ids)
        why = dict(near)
        out.append({"seed": sid, "members": members, "why": [why.get(m["id"], "the item itself") for m in members]})
    return out


def sensitivity_groups(ds: dict, ids: list[str]) -> list[dict]:
    """Code's own finding: threads whose items disagree on sensitivity, raised to the highest, never lowered."""
    threads = [r["t"] for r in db.rows("SELECT DISTINCT i.meta->>'thread' AS t FROM synapse.item i WHERE i.dataset_id = %s "
                                       "AND i.id = ANY(%s::uuid[]) AND coalesce(i.meta->>'thread', '') <> ''",
                                       (ds["id"], ids or ["00000000-0000-0000-0000-000000000000"]))]
    out = []
    for t in threads:
        members = db.rows(f"SELECT {ITEM_COLS} FROM synapse.item i WHERE i.dataset_id = %s AND i.meta->>'thread' = %s "
                          f"AND {ELIGIBLE} AND i.sensitivity IN ('normal', 'private', 'special') "
                          "ORDER BY coalesce(i.said_at, i.stored_at)", (ds["id"], t))
        levels = {m["sensitivity"] for m in members}
        if len(levels) < 2:
            continue
        top = max(levels, key=lambda v: LEVEL[v])
        out.append({"thread": t, "members": members, "to": top,
                    "raise": [m for m in members if LEVEL[m["sensitivity"]] < LEVEL[top]]})
    return out


def duplicate_pairs(ds: dict, ids: list[str]) -> list[dict]:
    """Code's own finding, besides the model's: an item stored again with the same kind and title and the same
    words (a receipt imported twice). Each later copy is proposed as an alias of the first; it waits for Petar."""
    ids = ids or ["00000000-0000-0000-0000-000000000000"]
    rows = db.rows(f"SELECT {ITEM_COLS} FROM synapse.item i WHERE i.dataset_id = %s AND {ELIGIBLE} AND i.title <> '' "
                   "AND (i.kind, lower(i.title)) IN (SELECT kind, lower(title) FROM synapse.item WHERE dataset_id = %s "
                   "AND id = ANY(%s::uuid[])) ORDER BY i.stored_at, i.id", (ds["id"], ds["id"], ids))
    by: dict[tuple, list[dict]] = {}
    for r in rows:
        by.setdefault((r["kind"], (r["title"] or "").lower()), []).append(r)
    out = []
    for same in by.values():
        if len(same) < 2:
            continue
        first = same[0]
        a = tx.norm(first.get("raw") or "")
        for other in same[1:]:
            b = tx.norm(other.get("raw") or "")
            if not a or not b or difflib.SequenceMatcher(None, a[:3000], b[:3000], autojunk=False).ratio() < 0.97:
                continue
            line = next((ln.strip() for ln in (first.get("raw") or "").splitlines()
                         if len(ln.strip()) >= 8 and _quote_ok(ln.strip(), first) and _quote_ok(ln.strip(), other)), "")
            if not line:
                continue
            out.append({"kind": "duplicate", "old_item": other["id"], "new_item": first["id"], "old_claim": None,
                        "new_claim": None, "reason": f"The same {first['kind']} was stored twice, word for word: "
                                                     f"\"{first['title']}\". The first is kept, the copy becomes its alias.",
                        "evidence": [{"item": first["id"], "quote": line[:200]}, {"item": other["id"], "quote": line[:200]}],
                        "payload": {"alike": 1.0, "found_by": "code"}, "effect": {}})
    return out


# --- 2. judge and check --------------------------------------------------------------------------

def _quote_ok(quote: str, item: dict) -> bool:
    """D10's check, word for word after normalising, against the item's own stored text: never a note."""
    return len(tx.norm(quote)) >= 3 and tx.quote_found(quote, item.get("raw") or item.get("body") or "")


def check(p: dict, members: list[dict]) -> tuple[dict | None, str]:
    """One proposal held to its kind's rules and its quotes; the change it makes, or None and why not."""
    kind = p.get("kind")
    if kind not in MODEL_KINDS:
        return None, "an unknown kind"

    def at(n):
        return members[n - 1] if isinstance(n, int) and 1 <= n <= len(members) else None
    old, new = at(p.get("old_item")), at(p.get("new_item"))
    if old is None:
        return None, "no such item"
    if kind != "misfiled_rule" and (new is None or new["id"] == old["id"]):
        return None, "it names one item where it needs two"
    quotes = [q for q in p.get("quotes") or [] if isinstance(q, dict)]
    named = {old["id"]} | ({new["id"]} if new is not None and kind != "misfiled_rule" else set())
    good, bad = [], []
    for q in quotes:
        it = at(q.get("item"))
        if it is None or it["id"] not in named:
            bad.append(q)
            continue
        (good if _quote_ok(str(q.get("quote") or ""), it) else bad).append({"item": it["id"], "quote": q.get("quote")})
    if bad:
        return None, f"{len(bad)} of its quotes {'is' if len(bad) == 1 else 'are'} not in the items"
    if {g["item"] for g in good} != named:
        return None, "it has no quote from every item it names"
    oc = claims_of(old)
    oi = p.get("old_claim")
    old_claim = oc[oi] if isinstance(oi, int) and 0 <= oi < len(oc) else None
    nc = claims_of(new) if new is not None else []
    ni = p.get("new_claim")
    new_claim = nc[ni] if isinstance(ni, int) and 0 <= ni < len(nc) else None
    later = new is not None and _ts(_when(new)) >= _ts(_when(old)) - 60
    change = {"kind": kind, "old_item": old["id"], "new_item": new["id"] if new is not None else None,
              "old_claim": oi if old_claim is not None else None,
              "new_claim": ni if new_claim is not None else None,
              "reason": " ".join(str(p.get("reason") or "").split())[:400], "evidence": good,
              "payload": {"old_text": (old_claim or {}).get("c", ""), "old_k": (old_claim or {}).get("k", ""),
                          "new_text": (new_claim or {}).get("c", ""), "new_k": (new_claim or {}).get("k", "")},
              "effect": {k: " ".join(str(p.get(k2) or "").split())[:300] for k, k2 in
                         (("question", "question"), ("before", "answer_before"), ("after", "answer_after"))}}
    if kind == "superseded":
        if old_claim is None:
            return None, "the replaced claim is not one of the item's claims"
        if not later:
            return None, "the replacing item is older than the one it replaces"
        change["payload"]["changed_on"] = _valid_day(p.get("changed_on")) or _day(_when(new))
    elif kind in ("ask_closed", "promise_kept"):
        if old_claim is None or old_claim.get("k") not in ("ask", "promise"):
            return None, "the claim closed is not an ask or a promise"
        if not old_claim.get("open"):
            return None, "the ask or promise was already closed"
        if not later:
            return None, "the item that closes it is older than the ask"
        change["kind"] = "ask_closed" if old_claim["k"] == "ask" else "promise_kept"
        change["payload"]["changed_on"] = _day(_when(new))
    elif kind == "duplicate":
        if old.get("kind") != new.get("kind"):
            return None, "the two items are of different kinds"
        a, b = tx.norm(old.get("raw") or "")[:3000], tx.norm(new.get("raw") or "")[:3000]
        same = difflib.SequenceMatcher(None, a, b, autojunk=False).ratio() if a and b else 0.0
        if same < 0.6 and not (a and b and (a in b or b in a)):
            return None, f"their texts are only {same:.0%} alike"
        # The canonical item is the one stored first; the other is kept as its alias.
        first, second = sorted([old, new], key=lambda m: (_ts(m.get("stored_at")), str(m["id"])))
        change.update({"old_item": second["id"], "new_item": first["id"], "old_claim": None, "new_claim": None})
        change["payload"].update({"alike": round(same, 3)})
    elif kind == "misfiled_rule":
        if old_claim is None or old_claim.get("k") != "rule":
            return None, "the claim is not a rule"
        to = p.get("new_kind") if p.get("new_kind") in NEW_KINDS else "fact"
        change.update({"new_item": None, "new_claim": None})
        change["payload"]["to_kind"] = to
    elif kind == "contradiction":
        if old_claim is None or new_claim is None:
            return None, "a contradiction names one claim in each item"
    return change, ""


def _valid_day(value) -> str:
    try:
        return datetime.strptime(str(value or "").strip()[:10], "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError:
        return ""


class _Shared:
    """The night's trace as each judge thread sees it: one call written at a time, and the spend counted, so
    the cap holds while calls run side by side. Its ids make the logged prompt findable by a deletion (D60)."""

    def __init__(self, trace, lock, spent):
        self.trace, self.lock, self.spent = trace, lock, spent
        self.dataset_id, self.id = trace.dataset_id, trace.id

    def call(self, **kw) -> dict:
        with self.lock:
            self.spent["usd"] += float(kw.get("cost") or 0)
            self.spent["calls"] += 1
            return self.trace.call(**kw)


def judge(ds: dict, group: dict, s, trace, lock, spent) -> dict:
    """One group asked of the model; its proposals checked. Never writes."""
    from . import ai

    members = group["members"]
    text = "\n".join(render(n + 1, m) for n, m in enumerate(members))
    try:
        got = ai.generate(model=s.dream_model, instructions=INSTRUCTIONS, text="ITEMS:\n" + text,
                          schema=SCHEMA, name="dream_proposals", purpose="dream", trace=_Shared(trace, lock, spent),
                          items=[m["id"] for m in members], owner=datasets.owner_of(ds), max_tokens=3000)
        ok, error, cost = True, "", float(got.get("_cost") or 0)
    except Exception as exc:  # noqa: BLE001 - one group failing never stops the night
        got, ok, error, cost = {"proposals": []}, False, f"{type(exc).__name__}: {exc}", 0.0
    kept, dropped = [], []
    for p in got.get("proposals") or []:
        change, why = check(p, members)
        if change is None:
            dropped.append({"kind": p.get("kind"), "reason": p.get("reason"), "why": why})
        else:
            kept.append(change)
    return {"kept": kept, "dropped": dropped, "ok": ok, "error": error, "cost": cost}


# --- 3. apply, and undo -----------------------------------------------------------------------------

def readers_of(ds_id: str, ids) -> list[str]:
    """Who may see a change: the readers every one of its items has (D92, as derived things take)."""
    got = _items(ds_id, ids)
    common = None
    for i in ids:
        r = set((got.get(str(i)) or {}).get("can_read") or [])
        common = r if common is None else common & r
    return sorted(common or [])


def _area(ds_id: str, ids) -> str:
    for it in _items(ds_id, ids).values():
        a = (it.get("meta") or {}).get("area")
        if a:
            return str(a)
    return ""


def _insert(ds: dict, dream_id: str, ch: dict, state: str) -> dict:
    ids = [i for i in (ch.get("items") or [ch.get("old_item"), ch.get("new_item")]) if i]
    return db.row(
        "INSERT INTO synapse.dream_change (dataset_id, dream_id, kind, state, items, readers, area, old_item, old_claim, "
        "new_item, new_claim, reason, evidence, payload, effect) VALUES (%s, %s, %s, %s, %s::uuid[], %s, %s, %s, %s, %s, "
        "%s, %s, %s::jsonb, %s::jsonb, %s::jsonb) RETURNING *",
        (ds["id"], dream_id, ch["kind"], state, ids, readers_of(ds["id"], ids), _area(ds["id"], ids),
         ch.get("old_item"), ch.get("old_claim"), ch.get("new_item"), ch.get("new_claim"), ch.get("reason") or "",
         Json(ch.get("evidence") or []), Json(ch.get("payload") or {}), Json(ch.get("effect") or {})))


def apply_change(ds: dict, change: dict, *, by: str = "dream") -> dict:
    """Make one change, saving first exactly what it touches (D90). Only this and `undo_change` write."""
    kind, p = change["kind"], change.get("payload") or {}
    before: dict = {}
    with db.atomic():
        if kind in ("superseded", "ask_closed", "promise_kept", "misfiled_rule"):
            item = _items(ds["id"], [change["old_item"]]).get(str(change["old_item"]))
            if item is None:
                return {"ok": False, "why": "its item is gone"}
            note = {"superseded": "replaced", "ask_closed": "closed", "promise_kept": "closed",
                    "misfiled_rule": "kind"}[kind]
            before["notes"] = "added"
            db.run("INSERT INTO synapse.claim_note (dataset_id, item_id, claim_idx, claim_text, note, by_item, by_claim, "
                   "changed_on, kind_now, readers, change_id) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                   (ds["id"], change["old_item"], int(change["old_claim"]), p.get("old_text") or "", note,
                    change.get("new_item"), change.get("new_claim"), p.get("changed_on") or None,
                    p.get("to_kind") or "", change.get("readers") or [], change["id"]))
            if kind == "misfiled_rule":
                # A rule item made from that very claim (`ingest.write_rules`) stops being a rule with it.
                made = db.rows("SELECT id, kind FROM synapse.item WHERE dataset_id = %s AND kind = 'rule' AND "
                               "deleted_at IS NULL AND meta->>'made_from' = %s AND (raw = %s OR body = %s)",
                               (ds["id"], str(change["old_item"]), p.get("old_text") or "", p.get("old_text") or ""))
                before["rule_items"] = [{"id": r["id"], "kind": r["kind"]} for r in made]
                for r in made:
                    db.run("UPDATE synapse.item SET kind = 'note' WHERE id = %s", (r["id"],))
        elif kind == "duplicate":
            got = db.row("SELECT alias_of FROM synapse.item WHERE dataset_id = %s AND id = %s",
                         (ds["id"], change["old_item"]))
            if got is None:
                return {"ok": False, "why": "its item is gone"}
            before["alias_of"] = {str(change["old_item"]): got["alias_of"]}
            db.run("UPDATE synapse.item SET alias_of = %s WHERE dataset_id = %s AND id = %s",
                   (change["new_item"], ds["id"], change["old_item"]))
        elif kind == "sensitivity_mismatch":
            to = p.get("to")
            before["sensitivity"] = {}
            for r in p.get("raise") or []:
                it = db.row("SELECT sensitivity, sensitivity_why FROM synapse.item WHERE dataset_id = %s AND id = %s",
                            (ds["id"], r["id"]))
                if it is None or LEVEL.get(it["sensitivity"], 0) >= LEVEL.get(to, 0):
                    continue  # never lowered, and never raised past where it already is
                before["sensitivity"][r["id"]] = {"level": it["sensitivity"], "why": it["sensitivity_why"]}
                why = dict(it["sensitivity_why"] or {})
                why["dream"] = f"raised to {to} by a night of dreaming: another item of its thread is {to}"
                why["set_by"] = "dreaming, to match its thread"
                db.run("UPDATE synapse.item SET sensitivity = %s, sensitivity_why = %s::jsonb WHERE dataset_id = %s "
                       "AND id = %s", (to, Json(why), ds["id"], r["id"]))
        elif kind == "link_strength":
            got = db.row("SELECT strength FROM synapse.link WHERE dataset_id = %s AND id = %s", (ds["id"], p.get("link")))
            if got is None:
                return {"ok": False, "why": "the link is gone"}
            before["strength"] = {str(p["link"]): float(got["strength"])}
            db.run("UPDATE synapse.link SET strength = %s, checked_at = now() WHERE dataset_id = %s AND id = %s",
                   (float(p["to"]), ds["id"], p["link"]))
        elif kind == "contradiction":
            return {"ok": False, "why": "a contradiction is only shown, never resolved"}
        db.run("UPDATE synapse.dream_change SET state = 'applied', before = %s::jsonb, applied_at = now(), "
               "decided_at = CASE WHEN %s = 'dream' THEN decided_at ELSE now() END, "
               "decided_by = CASE WHEN %s = 'dream' THEN decided_by ELSE %s END WHERE id = %s",
               (Json(before), by, by, by, change["id"]))
    return {"ok": True}


def undo_change(ds: dict, change: dict, *, by: str = "page", state: str = "undone") -> dict:
    """Put back exactly what one applied change touched; a field changed since by something else is left."""
    if change["state"] != "applied":
        return {"ok": False, "why": f"It is {change['state']}, not applied."}
    b = change.get("before") or {}
    left = []
    with db.atomic():
        db.run("DELETE FROM synapse.claim_note WHERE change_id = %s", (change["id"],))
        for r in b.get("rule_items") or []:
            db.run("UPDATE synapse.item SET kind = %s WHERE dataset_id = %s AND id = %s AND kind = 'note'",
                   (r["kind"], ds["id"], r["id"]))
        for item_id, was in (b.get("alias_of") or {}).items():
            n = db.run("UPDATE synapse.item SET alias_of = %s WHERE dataset_id = %s AND id = %s AND alias_of = %s",
                       (was, ds["id"], item_id, change.get("new_item")))
            if not n:
                left.append(item_id)
        to = (change.get("payload") or {}).get("to")
        for item_id, was in (b.get("sensitivity") or {}).items():
            n = db.run("UPDATE synapse.item SET sensitivity = %s, sensitivity_why = %s::jsonb WHERE dataset_id = %s "
                       "AND id = %s AND sensitivity = %s", (was["level"], Json(was["why"] or {}), ds["id"], item_id, to))
            if not n:
                left.append(item_id)
        p = change.get("payload") or {}
        for link_id, was in (b.get("strength") or {}).items():
            n = db.run("UPDATE synapse.link SET strength = %s WHERE dataset_id = %s AND id = %s AND abs(strength - %s) < 1e-6",
                       (was, ds["id"], link_id, float(p.get("to") or 0)))
            if not n:
                left.append(link_id)
        db.run("UPDATE synapse.dream_change SET state = %s, decided_at = now(), decided_by = %s, "
               "payload = payload || %s::jsonb WHERE id = %s",
               (state, by, Json({"undo_left": left} if left else {}), change["id"]))
    return {"ok": True, "left": left}


def _visible(viewer: list[str]) -> str:
    return "c.readers && %s::text[]"


def change_row(ds: dict, change_id, viewer: list[str]) -> dict | None:
    try:
        return db.row(f"SELECT c.* FROM synapse.dream_change c WHERE c.dataset_id = %s AND c.id = %s AND {_visible(viewer)}",
                      (ds["id"], int(change_id), viewer))
    except (TypeError, ValueError):
        return None


def decide(ds: dict, change_id, verdict: str, viewer: list[str], *, by: str = "page") -> dict:
    """Approve, Reject or Undo one change, as the person who can see it."""
    ch = change_row(ds, change_id, viewer)
    if ch is None:
        return {"ok": False, "why": "There is no such change."}
    if verdict == "undo":
        got = undo_change(ds, ch, by=by)
    elif verdict == "approve":
        if ch["state"] != "waiting":
            return {"ok": False, "why": f"It is {ch['state']}, not waiting."}
        got = apply_change(ds, ch, by=by)
    elif verdict == "reject":
        if ch["state"] not in ("waiting", "shown"):
            return {"ok": False, "why": f"It is {ch['state']}, not waiting."}
        db.run("UPDATE synapse.dream_change SET state = 'rejected', decided_at = now(), decided_by = %s WHERE id = %s",
               (by, ch["id"]))
        got = {"ok": True}
    else:
        return {"ok": False, "why": "Approve, reject or undo."}
    _refresh_counts(ds, ch["dream_id"])
    return got


def decide_group(ds: dict, dream_id: str | None, kind: str, verdict: str, viewer: list[str], *, by: str = "page") -> dict:
    """Approve all or Reject all of one kind's waiting changes, on one night or (no night) across every night."""
    rows = db.rows(f"SELECT c.id FROM synapse.dream_change c WHERE c.dataset_id = %s AND c.state = 'waiting' AND c.kind = %s "
                   f"AND (%s::uuid IS NULL OR c.dream_id = %s::uuid) AND {_visible(viewer)} ORDER BY c.id",
                   (ds["id"], kind, dream_id, dream_id, viewer))
    done = sum(1 for r in rows if decide(ds, r["id"], verdict, viewer, by=by).get("ok"))
    return {"ok": True, "done": done}


def undo_night(ds: dict, number, viewer: list[str], *, by: str = "page") -> dict:
    """Every change a night applied, put back newest first; what still waits is withdrawn with it."""
    night = db.row("SELECT * FROM synapse.dream WHERE dataset_id = %s AND number = %s", (ds["id"], int(number)))
    if night is None:
        return {"ok": False, "why": "There is no such night."}
    applied = db.rows(f"SELECT c.* FROM synapse.dream_change c WHERE c.dream_id = %s AND c.state = 'applied' "
                      f"AND {_visible(viewer)} ORDER BY c.id DESC", (night["id"], viewer))
    undone = sum(1 for c in applied if undo_change(ds, c, by=by).get("ok"))
    withdrawn = db.run(f"UPDATE synapse.dream_change c SET state = 'undone', decided_at = now(), decided_by = %s "
                       f"WHERE c.dream_id = %s AND c.state IN ('waiting', 'shown') AND {_visible(viewer)}", (by, night["id"], viewer))
    # The night is as if it never ran: what it read is unread again, so the next night reads it afresh (what
    # Petar rejected stays rejected and is never proposed again).
    reread = db.run("UPDATE synapse.item SET dreamed_at = NULL WHERE dataset_id = %s AND dreamed_at >= %s "
                    "AND dreamed_at <= coalesce(%s, now())", (ds["id"], night["started_at"], night["finished_at"]))
    _save(night["id"], undone_at=_now())
    _refresh_counts(ds, night["id"])
    return {"ok": True, "undone": undone, "withdrawn": withdrawn, "unread_again": reread}


def forget_item(ds_id: str, item_id: str) -> dict:
    """An item deleted (D60): every change that depends on it is put back and removed, with its notes and
    quotes, and every change that pointed at it as the newer or canonical item too (D92)."""
    rows = db.rows("SELECT * FROM synapse.dream_change WHERE dataset_id = %s AND %s::uuid = ANY(items) ORDER BY id DESC",
                   (ds_id, item_id))
    ds = {"id": ds_id}
    undone = 0
    for c in rows:
        if c["state"] == "applied":
            undone += 1 if undo_change(ds, c, by="deletion").get("ok") else 0
    removed = db.run("DELETE FROM synapse.dream_change WHERE dataset_id = %s AND %s::uuid = ANY(items)", (ds_id, item_id))
    for d in {c["dream_id"] for c in rows}:
        _refresh_counts(ds, d)
    return {"changes_removed": removed, "undone_first": undone}


# --- the night ------------------------------------------------------------------------------------

#: A night run with `hold`: nothing applies by itself, every change waits for Petar (`manage.py synapse_dream run
#: --hold`), for a night to look at before anything of it reaches an answer.
HOLD = {key: False for key in set(AUTO_SETTING.values())}


def run(ds: dict, *, by: str = "page", dream_id: str | None = None, hold: bool = False) -> dict:
    """One night, start to end. Returns its row. Never raises for a model's failure: the row says it."""
    from . import worker

    if ds.get("frozen"):
        log.warning("refused to dream over the frozen dataset %s", ds["id"])
        return {}
    s = datasets.settings(ds, HOLD if hold else None)
    if dream_id:
        night = db.row("SELECT * FROM synapse.dream WHERE dataset_id = %s AND id = %s", (ds["id"], dream_id))
        if night is None:
            return {}
        if night["status"] != "queued":
            if night["status"] == "running":
                _save(night["id"], status="failed", finished_at=_now(),
                      stopped_why="Rouh stopped while it was running, so it never finished.")
            return night
        _save(night["id"], status="running", started_at=_now(), cap_usd=float(s.dream_cap_usd))
        night = dict(night, status="running")
    else:
        busy = running(ds["id"])
        if busy:
            return busy
        night = _new_row(ds, by, s)
    me = datasets.me(ds)
    viewer = search.readers_for(me)
    trace = Trace(ds["id"], "dream", f"Dream {night['number']}", by=by)
    _save(night["id"], trace_id=trace.id)
    began = time.time()
    _orb("tool_start", night, ds, "gathering what changed")
    spent = {"usd": 0.0, "calls": 0}
    lock = threading.Lock()
    stopped = ""
    try:
        last = db.row("SELECT started_at FROM synapse.dream WHERE dataset_id = %s AND number < %s AND status IN "
                      "('done', 'stopped') ORDER BY number DESC LIMIT 1", (ds["id"], night["number"]))
        since = last["started_at"] if last else None
        # --- 1. gather
        with trace.step("gather", "Gather: what changed since the last night, the oldest unread, and their neighbours") as st:
            sc = scope_of(ds, s, since)
            seeds = sc["changed"] + sc["backfill"]
            _save(night["id"], stage="gather", since=since,
                  progress={"stage": "gather", "seeds": len(seeds)})
            groups = groups_of(ds, seeds, s, me, stop=lambda: worker.heartbeat(ds["id"], "dream") and False)
            scope_ids = sorted({m["id"] for g in groups for m in g["members"]} | set(seeds))
            sens = sensitivity_groups(ds, scope_ids)
            scope = {"changed": len(sc["changed"]), "backfill": len(sc["backfill"]),
                     "neighbours": len(set(scope_ids) - set(seeds)), "items": len(scope_ids), "groups": len(groups),
                     "since": since.isoformat() if since else None}
            st.data.update({**scope, "first_night": since is None, "example_groups": [
                {"seed": g["members"][0]["title"], "with": [f"{m['title']} ({w})" for m, w in zip(g["members"][1:], g["why"][1:])]}
                for g in groups[:12]],
                "threads_with_mixed_sensitivity": [{"thread": g["thread"], "to": g["to"],
                                                    "items": [m["title"] for m in g["members"]]} for g in sens]})
            _save(night["id"], scope=scope)
        # --- 2. judge
        changes: list[dict] = []
        dropped: list[dict] = []
        cap = float(s.dream_cap_usd)
        with trace.step("judge", f"Judge: {s.dream_model} proposes for each group, code checks every quote") as st:
            _orb("tool_update", night, ds, f"comparing {len(groups)} groups")
            _save(night["id"], stage="judge", progress={"stage": "judge", "groups": len(groups), "done": 0})
            pool = concurrent.futures.ThreadPoolExecutor(max_workers=max(1, int(s.dream_concurrency)),
                                                         thread_name_prefix="synapse-dream")
            done, failed = 0, 0
            try:
                pending = list(groups)
                running_now: set = set()
                while pending or running_now:
                    while pending and len(running_now) < max(1, int(s.dream_concurrency)):
                        avg = spent["usd"] / spent["calls"] if spent["calls"] else 0.002
                        if spent["usd"] + avg * (len(running_now) + 1) > cap:
                            stopped = (f"The night's spend cap of ${cap:g} was reached after {spent['calls']} of "
                                       f"{len(groups)} groups, so it stopped there and kept what it had judged.")
                            pending = []
                            break
                        g = pending.pop(0)
                        running_now.add(pool.submit(_judge_in_thread, ds, g, s, trace, lock, spent))
                    if not running_now:
                        break
                    finished, running_now = concurrent.futures.wait(running_now, timeout=30,
                                                                    return_when=concurrent.futures.FIRST_COMPLETED)
                    worker.heartbeat(ds["id"], "dream")
                    for f in finished:
                        got = f.result()
                        done += 1
                        failed += 0 if got["ok"] else 1
                        changes += got["kept"]
                        dropped += got["dropped"]
                    _save(night["id"], cost_usd=round(spent["usd"], 6),
                          progress={"stage": "judge", "groups": len(groups), "done": done, "found": len(changes)})
                    if done % 10 == 0:
                        _orb("tool_update", night, ds, f"{done} of {len(groups)} groups compared")
            finally:
                pool.shutdown(wait=True)
            st.data.update({"groups": len(groups), "judged": done, "calls_failed": failed, "proposed": len(changes) + len(dropped),
                            "passed": len(changes), "dropped": dropped[:60], "spent": round(spent["usd"], 6),
                            "cap": cap, "stopped": stopped})
        changes = _dedupe(ds, changes, viewer)
        for g in sens:
            changes.append({"kind": "sensitivity_mismatch", "items": [m["id"] for m in g["members"]],
                            "old_item": g["raise"][0]["id"], "new_item": max(g["members"], key=lambda m: LEVEL[m["sensitivity"]])["id"],
                            "reason": f"The items of one thread are {', '.join(sorted({m['sensitivity'] for m in g['members']}, key=LEVEL.get))}; "
                                      f"the lower ones are raised to {g['to']}, never lowered.",
                            "evidence": [], "effect": {},
                            "payload": {"thread": g["thread"], "to": g["to"],
                                        "raise": [{"id": m["id"], "from": m["sensitivity"], "title": m["title"]} for m in g["raise"]],
                                        "levels": [{"id": m["id"], "level": m["sensitivity"], "title": m["title"]} for m in g["members"]]}})
        changes = _dedupe(ds, changes + duplicate_pairs(ds, scope_ids), viewer)
        changes = [c for c in changes if not _settled_before(ds, c)]
        # --- 3. usage feedback (D57) as a stage of the night
        with trace.step("learn", "Usage feedback: link strengths from what answers used (D57)") as st:
            got = learning.plan(ds, s)
            for m in got["moves"]:
                if m["moved"]:
                    changes.append({"kind": "link_strength", "items": [m["src"], m["dst"]], "old_item": m["src"],
                                    "new_item": m["dst"], "reason": f"{m['link']}: {m['why']}.", "evidence": [],
                                    "effect": {}, "payload": {"link": m["id"], "type": m["type"], "from": m["from"],
                                                              "to": m["to"], "link_words": m["link"]}})
            st.data.update({"questions": got["questions"], "moves": [m for m in got["moves"] if m["moved"]][:40]})
        # --- 4. the guard (D89)
        with trace.step("guard", f"Guard: at most {float(s.dream_guard_share):.0%} of an area's claims or of the night's scope") as st:
            guard = guard_check(ds, changes, scope_ids, s)
            st.data.update(guard)
        # --- 5. apply: the only stage that writes
        _save(night["id"], stage="apply", progress={"stage": "apply", "changes": len(changes)})
        _orb("tool_update", night, ds, f"applying {len(changes)} changes")
        with trace.step("apply", "Apply: the only stage that writes; what waits for the owner waits") as st:
            applied, waiting, shown = 0, 0, 0
            for ch in changes:
                if ch["kind"] == "contradiction":
                    _insert(ds, night["id"], ch, "shown")
                    shown += 1
                    continue
                row = _insert(ds, night["id"], ch, "waiting")
                if not guard["tripped"] and auto(s, ch["kind"]):
                    if apply_change(ds, row).get("ok"):
                        applied += 1
                        continue
                waiting += 1
            if any(c["kind"] == "link_strength" for c in changes):
                # The moves are changes now, waiting or applied: the next night does not plan them again.
                learning.mark_learned(ds["id"])
            st.data.update({"applied": applied, "waiting": waiting, "shown": shown,
                            "rule": "superseded, closed asks and promises and link moves apply by themselves; merges, "
                                    "kind changes and sensitivity wait; contradictions are only shown (D91)"})
        # Read: every seed a judged group started from, and every seed that made no group of its own (it was
        # alone, or all in a group already taken). A night the cap stopped leaves the rest for the next.
        judged = {g["seed"] for g in groups[:spent["calls"]]} | (set(seeds) - {g["seed"] for g in groups})
        db.run("UPDATE synapse.item SET dreamed_at = now() WHERE dataset_id = %s AND id = ANY(%s::uuid[])",
               (ds["id"], sorted(judged)))
        status = "stopped" if stopped else "done"
        _finish(ds, night, trace, began, spent, status=status, stopped=stopped, guard=guard, dropped=dropped)
    except Exception as exc:  # noqa: BLE001 - the row says what stopped it
        log.exception("the night of dreaming %s failed", night["id"])
        _save(night["id"], status="failed", finished_at=_now(), ms=int((time.time() - began) * 1000),
              cost_usd=round(spent["usd"], 6), stopped_why=f"It failed: {type(exc).__name__}: {exc}"[:500])
        trace.finish("failed", error=str(exc)[:300])
    finally:
        _orb("tool_end", night, ds)
    return db.row("SELECT * FROM synapse.dream WHERE id = %s", (night["id"],)) or {}


def _judge_in_thread(ds, group, s, trace, lock, spent) -> dict:
    from django.db import connection

    try:
        return judge(ds, group, s, trace, lock, spent)
    finally:
        connection.close()


def _dedupe(ds: dict, changes: list[dict], viewer: list[str]) -> list[dict]:
    """One change per claim and kind, and one per pair of duplicates, the first found kept."""
    out, seen = [], set()
    for c in changes:
        key = (c["kind"], c.get("old_item"), c.get("old_claim")) if c["kind"] != "duplicate" else \
            ("duplicate", c.get("old_item"))
        if c["kind"] == "contradiction":
            key = ("contradiction",) + tuple(sorted([f"{c['old_item']}:{c['old_claim']}", f"{c['new_item']}:{c['new_claim']}"]))
        if key in seen:
            continue
        # A claim closed or replaced counts once, whichever kind found it first.
        if c["kind"] in ("superseded", "ask_closed", "promise_kept") and ("claim", c["old_item"], c["old_claim"]) in seen:
            continue
        seen.add(key)
        if c["kind"] in ("superseded", "ask_closed", "promise_kept"):
            seen.add(("claim", c["old_item"], c["old_claim"]))
        out.append(c)
    return out


def _settled_before(ds: dict, c: dict) -> bool:
    """Already done or decided on an earlier night: an applied or waiting change of the same claim, or one
    Petar rejected (never proposed to him again)."""
    if c["kind"] == "duplicate":
        return bool(db.value("SELECT 1 FROM synapse.dream_change WHERE dataset_id = %s AND kind = 'duplicate' AND "
                             "state IN ('applied', 'waiting', 'rejected') AND old_item = %s AND new_item = %s LIMIT 1",
                             (ds["id"], c["old_item"], c["new_item"])))
    if c["kind"] == "sensitivity_mismatch":
        return bool(db.value("SELECT 1 FROM synapse.dream_change WHERE dataset_id = %s AND kind = 'sensitivity_mismatch' "
                             "AND state IN ('waiting', 'rejected') AND payload->>'thread' = %s AND payload->>'to' = %s "
                             "LIMIT 1", (ds["id"], c["payload"]["thread"], c["payload"]["to"])))
    if c["kind"] == "contradiction":
        return bool(db.value("SELECT 1 FROM synapse.dream_change WHERE dataset_id = %s AND kind = 'contradiction' AND "
                             "state IN ('shown', 'rejected') AND ((old_item = %s AND old_claim = %s AND new_item = %s AND "
                             "new_claim = %s) OR (old_item = %s AND old_claim = %s AND new_item = %s AND new_claim = %s)) LIMIT 1",
                             (ds["id"], c["old_item"], c["old_claim"], c["new_item"], c["new_claim"],
                              c["new_item"], c["new_claim"], c["old_item"], c["old_claim"])))
    return bool(db.value("SELECT 1 FROM synapse.dream_change WHERE dataset_id = %s AND old_item = %s AND old_claim = %s AND "
                         "((kind = %s AND state = 'rejected') OR (kind IN ('superseded', 'ask_closed', 'promise_kept', "
                         "'misfiled_rule') AND state IN ('applied', 'waiting') AND (kind = 'misfiled_rule') = %s)) LIMIT 1",
                         (ds["id"], c["old_item"], c.get("old_claim"), c["kind"], c["kind"] == "misfiled_rule")))


def touched(c: dict, claims: dict) -> tuple[list[str], int]:
    """The items a change alters (the old side only) and how many claims that is."""
    if c["kind"] == "link_strength":
        return [], 0
    if c["kind"] == "sensitivity_mismatch":
        # A level raised changes no claim, only who may read it: it counts against the night's scope.
        return [r["id"] for r in c["payload"].get("raise") or []], 0
    if c["kind"] == "duplicate":
        return [c["old_item"]], max(1, claims.get(c["old_item"], 0))
    if c["kind"] == "contradiction":
        return [], 0
    return [c["old_item"]], 1


def guard_check(ds: dict, changes: list[dict], scope_ids: list[str], s) -> dict:
    """D89: no night changes more than the share of any area's claims, or of its own scope. Tripped, it
    applies nothing and everything waits."""
    share = float(s.dream_guard_share)
    least = int(s.dream_guard_min_claims)
    ids = list({i for c in changes for i in (c.get("items") or [c.get("old_item")]) if i})
    info = {r["id"]: r for r in db.rows(
        "SELECT id, coalesce(meta->>'area', '') AS area, coalesce(jsonb_array_length(xray->'claims'), 0) AS claims "
        "FROM synapse.item WHERE dataset_id = %s AND id = ANY(%s::uuid[])",
        (ds["id"], ids or ["00000000-0000-0000-0000-000000000000"]))}
    claims = {i: int(r["claims"]) for i, r in info.items()}
    by_area: dict[str, int] = {}
    items_touched: set = set()
    for c in changes:
        its, n = touched(c, claims)
        items_touched |= set(its)
        if its and n:
            area = (info.get(its[0]) or {}).get("area") or ""
            by_area[area] = by_area.get(area, 0) + n
    totals = {r["area"]: int(r["claims"]) for r in db.rows(
        "SELECT coalesce(meta->>'area', '') AS area, sum(coalesce(jsonb_array_length(xray->'claims'), 0)) AS claims "
        f"FROM synapse.item i WHERE i.dataset_id = %s AND {ELIGIBLE} GROUP BY 1", (ds["id"],))}
    areas = []
    tripped_why = ""
    for area, n in sorted(by_area.items(), key=lambda kv: -kv[1]):
        total = totals.get(area, 0)
        frac = n / total if total else 1.0
        areas.append({"area": area or "(no area)", "changed": n, "claims": total, "share": round(frac, 3),
                      "checked": total >= least})
        if total >= least and frac > share and not tripped_why:
            tripped_why = (f"It would have changed {n} of the {total} claims in the area {area or '(no area)'} "
                           f"({frac:.0%}, more than {share:.0%}), so it applied none of it and everything waits for you.")
    in_scope = len(scope_ids)
    scope_frac = len(items_touched) / in_scope if in_scope else 0.0
    if not tripped_why and in_scope and scope_frac > share:
        tripped_why = (f"It would have changed {len(items_touched)} of the {in_scope} items it read ({scope_frac:.0%}, "
                       f"more than {share:.0%}), so it applied none of it and everything waits for you.")
    return {"tripped": bool(tripped_why), "why": tripped_why, "share": share, "areas": areas[:20],
            "scope": {"items": in_scope, "touched": len(items_touched), "share": round(scope_frac, 3)},
            "area_minimum_claims": least}


# --- what a night says ---------------------------------------------------------------------------

def health(ds: dict) -> dict:
    """The memory's health, after a night: what is still open, stored twice, flagged or replaced."""
    open_asks = int(db.value(
        "SELECT count(*) FROM synapse.item i, jsonb_array_elements(coalesce(i.xray->'claims', '[]'::jsonb)) "
        "WITH ORDINALITY AS c(claim, n) WHERE i.dataset_id = %s AND i.deleted_at IS NULL AND i.alias_of IS NULL "
        "AND c.claim->>'k' IN ('ask', 'promise') AND (c.claim->>'open')::boolean IS TRUE AND NOT EXISTS ("
        " SELECT 1 FROM synapse.claim_note n WHERE n.dataset_id = i.dataset_id AND n.item_id = i.id "
        " AND n.claim_idx = c.n - 1 AND n.note IN ('closed', 'replaced'))", (ds["id"],)) or 0)
    row = db.row(
        "SELECT (SELECT count(*) FROM synapse.item WHERE dataset_id = %s AND alias_of IS NOT NULL AND deleted_at IS NULL) AS aliases, "
        "(SELECT count(*) FROM synapse.dream_change WHERE dataset_id = %s AND kind = 'duplicate' AND state = 'waiting') AS dup_waiting, "
        "(SELECT count(*) FROM synapse.dream_change WHERE dataset_id = %s AND kind = 'contradiction' AND state = 'shown') AS contradictions, "
        "(SELECT count(*) FROM synapse.claim_note WHERE dataset_id = %s AND note = 'replaced') AS replaced, "
        "(SELECT count(*) FROM synapse.claim_note WHERE dataset_id = %s AND note = 'closed') AS closed",
        (ds["id"],) * 5) or {}
    return {"open_asks": open_asks, "duplicates": int(row.get("dup_waiting") or 0) + int(row.get("aliases") or 0),
            "aliases": int(row.get("aliases") or 0), "contradictions": int(row.get("contradictions") or 0),
            "replaced": int(row.get("replaced") or 0), "closed": int(row.get("closed") or 0)}


def _counts(dream_id: str) -> dict:
    out: dict = {}
    for r in db.rows("SELECT kind, state, count(*) AS n FROM synapse.dream_change WHERE dream_id = %s GROUP BY 1, 2",
                     (dream_id,)):
        out.setdefault(r["kind"], {})[r["state"]] = int(r["n"])
    return out


def _refresh_counts(ds: dict, dream_id: str) -> None:
    _save(dream_id, counts=_counts(dream_id), health=health(ds))


def _n(c: dict, kind: str, state: str | None = None) -> int:
    got = c.get(kind) or {}
    return int(got.get(state, 0)) if state else sum(int(v) for v in got.values())


def _money(usd: float) -> str:
    usd = float(usd or 0)
    if usd < 0.01:
        return f"{usd * 100:.2f} cents" if usd else "nothing"
    if usd < 1:
        cents = round(usd * 100)
        return f"{cents} cent{'s' if cents != 1 else ''}"
    return f"${usd:.2f}"


def _took(ms: int) -> str:
    s = int((ms or 0) / 1000)
    if s < 60:
        return f"{s} seconds"
    m = round(s / 60)
    return f"{m} minute{'s' if m != 1 else ''}"


def _plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


def summary_text(night: dict) -> str:
    """The plain-language line at the top of a night, read from its changes as they stand now: what it found,
    what it applied, what still waits for Petar, what it cost and how long it took."""
    c = night.get("counts") or {}
    sc = night.get("scope") or {}
    when = "Last night" if night.get("by") == "schedule" else "This run"
    bits = []
    # Petar's words when it applied them, "found" when they wait (the guard, or a kind that waits by setting).
    for kind, done, found in (
            ("superseded", ("marked {n} fact as replaced", "marked {n} facts as replaced"),
             ("found {n} replaced fact", "found {n} replaced facts")),
            ("ask_closed", ("closed {n} ask", "closed {n} asks"), ("found {n} answered ask", "found {n} answered asks")),
            ("promise_kept", ("marked {n} promise as kept", "marked {n} promises as kept"),
             ("found {n} kept promise", "found {n} kept promises")),
            ("duplicate", ("merged {n} duplicate", "merged {n} duplicates"), ("found {n} duplicate", "found {n} duplicates")),
            ("misfiled_rule", ("made {n} rule a fact", "made {n} rules facts"),
             ("found {n} rule that is a fact", "found {n} rules that are facts")),
            ("sensitivity_mismatch", ("raised {n} thread to one sensitivity", "raised {n} threads to one sensitivity"),
             ("found {n} thread with mixed sensitivity", "found {n} threads with mixed sensitivity")),
            ("contradiction", ("{n} contradiction", "{n} contradictions"), ("{n} contradiction", "{n} contradictions")),
            ("link_strength", ("moved {n} link", "moved {n} links"), ("found {n} link to move", "found {n} links to move"))):
        n = _n(c, kind) - _n(c, kind, "rejected")
        if not n:
            continue
        applied = _n(c, kind, "applied") + _n(c, kind, "undone")
        words = done if applied >= n else found
        bits.append(words[0 if n == 1 else 1].format(n=n))
    if len(bits) > 1:
        bits[-1] = "and " + bits[-1]
    found_words = ", ".join(bits) if bits else "found nothing to change"
    waiting = sum(_n(c, k, "waiting") for k in c)
    read = sc.get("changed", 0)
    reads = (f"read {_plural(read, 'changed item')}" + (f" and {sc.get('backfill', 0)} it had not read before"
                                                       if sc.get("backfill") else "") + " and their neighbours"
             ) if (read or sc.get("backfill")) else "had nothing new to read"
    line = f"{when} Synapse {reads}, {found_words}"
    if waiting:
        line += f"; {_plural(waiting, 'change')} {'waits' if waiting == 1 else 'wait'} for you"
    elif bits and night.get("status") in ("done", "stopped"):
        line += "; nothing waits for you"
    line += f"; cost {_money(night.get('cost_usd'))}, took {_took(night.get('ms') or 0)}."
    if night.get("undone_at"):
        line += " You undid it later."
    return line


def _title(ds_id: str, item_id) -> str:
    if not item_id:
        return ""
    return db.value("SELECT title FROM synapse.item WHERE dataset_id = %s AND id = %s", (ds_id, item_id)) or "an item"


def diary(ds: dict, night: dict, dropped: list[dict], guard: dict, stopped: str) -> list[dict]:
    """What the night did, in sentences, a group at a time: why each kind of change was made."""
    rows = db.rows("SELECT * FROM synapse.dream_change WHERE dream_id = %s ORDER BY id", (night["id"],))
    by: dict[str, list[dict]] = {}
    for r in rows:
        by.setdefault(r["kind"], []).append(r)
    sc = night.get("scope") or {}
    if not sc.get("changed") and not sc.get("backfill"):
        out = [{"kind": "scope", "text": "Nothing was made or changed since the last night, and no night had left an "
                                         "older item unread, so there was nothing to compare."}]
    else:
        out = [{"kind": "scope", "text": (
            f"It read {_plural(sc.get('changed', 0), 'item')} made or changed since the last night"
            + (f" and {sc.get('backfill', 0)} older ones no night had read" if sc.get("backfill") else "")
            + f", with {_plural(sc.get('neighbours', 0), 'neighbour')} (the same thread, person, task or topic, linked, "
              f"or close by words and meaning), in {_plural(sc.get('groups', 0), 'group')}.")}]
    texts = {
        "superseded": "A newer item gave a new value, so the old claim is marked replaced and answers prefer the new one",
        "ask_closed": "A later item answered or did what was asked, so the ask is closed and no longer listed as open",
        "promise_kept": "A later item shows the promise was kept, so it is no longer listed as open",
        "duplicate": "The same thing was stored more than once; merging keeps the first and the others as its aliases, and waits for you",
        "misfiled_rule": "A claim read as a standing rule is really a fact or a contract term; the change of kind waits for you",
        "contradiction": "Two current claims disagree and neither clearly replaces the other; shown for you to read, never resolved",
        "sensitivity_mismatch": "Items of one thread were labelled differently; raising the lower ones to the highest waits for you",
        "link_strength": "What answers used moved the strength of the links on their paths, as synapse_learn does",
    }
    for kind in KINDS:
        got = by.get(kind) or []
        if not got:
            continue
        examples = []
        for r in got[:3]:
            p = r.get("payload") or {}
            if kind == "link_strength":
                examples.append(f"{p.get('link_words')} {p.get('from')} to {p.get('to')}")
            elif kind == "sensitivity_mismatch":
                examples.append(f"{len(p.get('raise') or [])} raised to {p.get('to')}")
            elif kind == "duplicate":
                examples.append(f"\"{_title(ds['id'], r['old_item'])}\" is \"{_title(ds['id'], r['new_item'])}\"")
            else:
                examples.append(f"\"{(p.get('old_text') or _title(ds['id'], r['old_item']))[:90]}\"")
        states = {}
        for r in got:
            states[r["state"]] = states.get(r["state"], 0) + 1
        out.append({"kind": kind, "text": f"{texts[kind]}: {_plural(len(got), 'change')} ("
                    + ", ".join(f"{v} {k}" for k, v in states.items()) + "), such as " + "; ".join(examples) + "."})
    if dropped:
        reasons: dict[str, int] = {}
        for d in dropped:
            reasons[d["why"]] = reasons.get(d["why"], 0) + 1
        out.append({"kind": "dropped", "text": f"Code threw away {_plural(len(dropped), 'proposal')} of the model's: "
                    + "; ".join(f"{n} because {w}" for w, n in sorted(reasons.items(), key=lambda kv: -kv[1])[:4]) + "."})
    if guard.get("tripped"):
        out.append({"kind": "guard", "text": guard["why"]})
    if stopped:
        out.append({"kind": "cap", "text": stopped})
    if len(out) == 1:
        out.append({"kind": "nothing", "text": "Nothing in what it read needed a change."})
    return out


def _finish(ds, night, trace, began, spent, *, status, stopped, guard, dropped) -> None:
    ms = int((time.time() - began) * 1000)
    row = db.row("SELECT * FROM synapse.dream WHERE id = %s", (night["id"],))
    row.update({"counts": _counts(night["id"]), "ms": ms, "cost_usd": round(spent["usd"], 6), "status": status})
    _save(night["id"], status=status, stage="done", finished_at=_now(), ms=ms, cost_usd=round(spent["usd"], 6),
          counts=row["counts"], health=health(ds), guard=guard, stopped_why=stopped,
          progress={"stage": "done"}, summary=summary_text(row), diary=diary(ds, row, dropped, guard, stopped))
    trace.finish("done", night=night["number"], changes=sum(_n(row["counts"], k) for k in row["counts"]),
                 cost=round(spent["usd"], 6), guard=guard.get("tripped"), stopped=bool(stopped))


# --- retrieval reads the notes ---------------------------------------------------------------------

def notes_for(ds_id: str, ids, principals: list[str] | None = None) -> dict[str, list[dict]]:
    """Every note on these items the asker may see (both items readable, D92), by item."""
    ids = [str(i) for i in ids if i]
    if not ids or not ready():
        return {}
    got = db.rows("SELECT n.item_id, n.claim_idx, n.claim_text, n.note, n.by_item, n.by_claim, n.changed_on, n.kind_now, "
                  "(SELECT b.title FROM synapse.item b WHERE b.dataset_id = n.dataset_id AND b.id = n.by_item) AS by_title "
                  "FROM synapse.claim_note n WHERE n.dataset_id = ANY(synapse.scope(%s)) AND n.item_id = ANY(%s::uuid[]) "
                  "AND (%s::text[] IS NULL OR n.readers && %s::text[]) ORDER BY n.id",
                  (ds_id, ids, principals, principals))
    out: dict[str, list[dict]] = {}
    for r in got:
        out.setdefault(r["item_id"], []).append(r)
    return out


def annotate(ds_id: str, facts: dict, principals: list[str] | None = None) -> dict:
    """Each item's live notes, by claim index, on `item["_notes"]`; a note whose claim has since changed
    (the item was edited or read again) is stale and left out."""
    notes = notes_for(ds_id, list(facts), principals)
    for item_id, rows in notes.items():
        it = facts.get(item_id)
        if it is None:
            continue
        claims = claims_of(it)
        live = {}
        for n in rows:
            i = int(n["claim_idx"])
            if 0 <= i < len(claims) and (not n["claim_text"] or claims[i].get("c") == n["claim_text"]):
                live[i] = n
        if live:
            it["_notes"] = live
    return facts


# --- views ------------------------------------------------------------------------------------------

def _item_brief(ds_id: str, ids) -> dict[str, dict]:
    got = _items(ds_id, ids)
    return {i: {"id": i, "title": r.get("title") or "(untitled)", "kind": r.get("kind"), "said_at": r.get("said_at"),
                "area": (r.get("meta") or {}).get("area") or "", "sensitivity": r.get("sensitivity"),
                "claims": claims_of(r), "gone": False} for i, r in got.items()}


def change_view(ds_id: str, r: dict, items: dict) -> dict:
    p = r.get("payload") or {}
    old, new = items.get(str(r.get("old_item") or "")), items.get(str(r.get("new_item") or ""))

    def side(it, claim_idx, text, k):
        if it is None:
            return None
        quotes = [e["quote"] for e in r.get("evidence") or [] if e.get("item") == it["id"]]
        return {"id": it["id"], "title": it["title"], "kind": it["kind"], "said_at": it["said_at"], "area": it["area"],
                "claim": claim_idx, "text": text, "claim_kind": k, "quotes": quotes, "sensitivity": it["sensitivity"]}
    return {"id": r["id"], "dream": r["dream_id"], "kind": r["kind"], "state": r["state"], "area": r.get("area") or "",
            "reason": r["reason"], "effect": r.get("effect") or {}, "payload": p, "made_at": r["made_at"],
            "decided_at": r.get("decided_at"), "decided_by": r.get("decided_by") or "",
            "old": side(old, r.get("old_claim"), p.get("old_text") or "", p.get("old_k") or ""),
            "new": side(new, r.get("new_claim"), p.get("new_text") or "", p.get("new_k") or ""),
            "left": p.get("undo_left") or []}


def _views(ds: dict, rows: list[dict]) -> list[dict]:
    ids = {str(i) for r in rows for i in (r.get("items") or [])}
    for r in rows:
        for x in (r.get("payload") or {}).get("levels") or []:
            ids.add(str(x["id"]))
    items = _item_brief(ds["id"], ids)
    return [change_view(ds["id"], r, items) for r in rows]


def _night_brief(r: dict) -> dict:
    return {k: r.get(k) for k in ("id", "number", "trace_id", "by", "status", "stage", "progress", "started_at", "finished_at",
                                   "ms", "cost_usd", "cap_usd", "scope", "counts", "health", "guard", "stopped_why",
                                   "summary", "undone_at")}


def listing(ds: dict, viewer: list[str], s=None) -> dict:
    """The strip of nights, newest first, with what waits on each for the viewer, and the health chart."""
    s = s or datasets.settings(ds)
    running(ds["id"])
    nights = db.rows("SELECT * FROM synapse.dream WHERE dataset_id = %s ORDER BY number DESC LIMIT 60", (ds["id"],))
    waits = {r["dream_id"]: int(r["n"]) for r in db.rows(
        f"SELECT c.dream_id, count(*) AS n FROM synapse.dream_change c WHERE c.dataset_id = %s AND c.state = 'waiting' "
        f"AND {_visible(viewer)} GROUP BY 1", (ds["id"], viewer))}
    seen = {}
    for r in db.rows(f"SELECT c.dream_id, c.kind, c.state, count(*) AS n FROM synapse.dream_change c WHERE c.dataset_id = %s "
                     f"AND {_visible(viewer)} GROUP BY 1, 2, 3", (ds["id"], viewer)):
        seen.setdefault(r["dream_id"], {}).setdefault(r["kind"], {})[r["state"]] = int(r["n"])
    out = []
    for n in nights:
        b = _night_brief(n)
        if n["status"] in ("done", "stopped"):
            b["summary"] = summary_text(n)
        b["counts"] = seen.get(n["id"], {})
        b["waiting"] = waits.get(n["id"], 0)
        out.append(b)
    return {"nights": out, "waiting": sum(waits.values()), "health_now": health(ds),
            "settings": {**{k: s.get(k) for k in ("dream_cap_usd", "dream_guard_share", "dream_backfill_items",
                                                  *sorted(set(AUTO_SETTING.values())))},
                         # The Models page's, now (`numbers.MODEL_USES`).
                         "dream_model": s.dream_model},
            "kinds": [{"kind": k, "words": KIND_WORDS[k]} for k in KINDS]}


def night(ds: dict, number, viewer: list[str]) -> dict | None:
    try:
        row = db.row("SELECT * FROM synapse.dream WHERE dataset_id = %s AND number = %s", (ds["id"], int(number)))
    except (TypeError, ValueError):
        return None
    if row is None:
        return None
    rows = db.rows(f"SELECT c.* FROM synapse.dream_change c WHERE c.dream_id = %s AND {_visible(viewer)} ORDER BY c.id",
                   (row["id"], viewer))
    hidden = int(db.value("SELECT count(*) FROM synapse.dream_change WHERE dream_id = %s", (row["id"],)) or 0) - len(rows)
    out = _night_brief(row)
    if row["status"] in ("done", "stopped"):
        out["summary"] = summary_text(dict(row, counts=_counts(row["id"])))
    out.update({"diary": row.get("diary") or [], "changes": _views(ds, rows), "hidden": max(0, hidden),
                "applied_now": sum(1 for r in rows if r["state"] == "applied"),
                "waiting_now": sum(1 for r in rows if r["state"] == "waiting")})
    return out


def waiting(ds: dict, viewer: list[str]) -> dict:
    rows = db.rows(f"SELECT c.*, d.number AS night FROM synapse.dream_change c JOIN synapse.dream d ON d.id = c.dream_id "
                   f"WHERE c.dataset_id = %s AND c.state = 'waiting' AND {_visible(viewer)} ORDER BY d.number DESC, c.id",
                   (ds["id"], viewer))
    views = _views(ds, rows)
    for v, r in zip(views, rows):
        v["night"] = r["night"]
    return {"changes": views}


def for_item(ds: dict, item_id: str, viewer: list[str]) -> list[dict]:
    """The changes that touch one item, for the Dreams card on its page."""
    if not ready():
        return []
    try:
        rows = db.rows(f"SELECT c.*, d.number AS night FROM synapse.dream_change c JOIN synapse.dream d ON d.id = c.dream_id "
                       f"WHERE c.dataset_id = %s AND %s::uuid = ANY(c.items) AND {_visible(viewer)} "
                       "ORDER BY c.id DESC LIMIT 50", (ds["id"], str(item_id), viewer))
    except Exception:  # noqa: BLE001 - a malformed id has no changes
        return []
    views = _views(ds, rows)
    for v, r in zip(views, rows):
        v["night"] = r["night"]
    return views


# --- the schedule: a row of Rouh's own server work at 04:00 ----------------------------------------------

JOB = "synapse_dream"
WHAT = "Compare what changed in Synapse with what came before, and mark what is replaced or closed"
#: Its line on the Reminders page and in the morning brief (`reminders.title_of`).
TITLE = "Synapse nightly dreaming"
AT = "04:00"


def ensure(who, *, on: bool = False):
    """The person's row for the nightly dream on Synapse Master, made once (daily at 04:00 on their clock, after
    the 02:00 improvement attempt), paused until the evaluation gate turns it on (D86). A row Petar paused,
    resumed or moved stays as he left it."""
    from .. import clock, reminders
    from . import master

    if not db.ready() or not ready() or not master.of(str(who.org_id), str(who.user_id)):
        return None
    got = reminders.server_row(who, JOB)
    if got is not None:
        return got
    with clock.person(who):
        first = reminders.moment_of(AT)
    row = reminders.add_server(who, job=JOB, title=TITLE, what=WHAT, first=first, repeat="daily")
    if not on:
        reminders.change(who, row.id, state="paused")
    log.info("the nightly dream is scheduled for %s/%s at %s on their clock (reminder %s, %s)", who.org_id,
             who.user_id, AT, row.id, "on" if on else "paused")
    return reminders.server_row(who, JOB)


def schedule(who) -> dict | None:
    from .. import clock, reminders

    row = reminders.server_row(who, JOB)
    if row is None:
        return None
    with clock.person(who):
        v = reminders.view(row)
    return {"id": row.id, "state": v["state"], "when": v["when"], "repeats": v["repeats"],
            "last_said": v["last_said"], "last_day": v["last_day"], "last_time": v["last_time"]}


def start_scheduled(who) -> str:
    """At 04:00: tonight's dream on the person's Synapse Master, queued on the backfill lane."""
    from . import master

    ds = master.of(str(who.org_id), str(who.user_id))
    if ds is None:
        return "not started: there is no Synapse Master"
    got = queue(ds, by="schedule")
    if not got.get("ok"):
        return f"not started: {got['why']}"
    return f"started night {got['number']}; it is on the Synapse lab's Dreams page"


# --- the tool: synapse_dream ---------------------------------------------------------------------------

def tool(ds: dict, args: dict, *, by: str = "chat") -> str:
    """`synapse_dream`: run a night now, or read the latest or a given night, or what waits."""
    me = datasets.me(ds)
    viewer = search.readers_for(me)
    action = str(args.get("action") or "read")
    if action == "run":
        got = queue(ds, by=by)
        if not got.get("ok"):
            return got["why"] + " Read it with action read when it is done."
        return (f"Night {got['number']} of {ds['name']} is queued on the backfill lane and starts in a moment. It "
                "applies replaced claims, closed asks and link moves by itself and keeps merges, kind changes and "
                "sensitivity waiting; read it with action read, night latest, when it is done. Every step is in "
                "the lab's Dreams page.")
    if action == "waiting":
        rows = waiting(ds, viewer)["changes"]
        if not rows:
            return "Nothing waits for the person from any night."
        return f"{len(rows)} changes wait for the person:\n" + "\n".join(_change_line(v) for v in rows[:40])
    which = str(args.get("night") or "latest").strip().lower()
    if which in ("latest", "last", ""):
        number = db.value("SELECT max(number) FROM synapse.dream WHERE dataset_id = %s", (ds["id"],))
    else:
        number = which.lstrip("#")
    if not number:
        return f"{ds['name']} has never been dreamed over. Action run starts a night now."
    got = night(ds, number, viewer)
    if got is None:
        return f"There is no night {number}."
    lines = [f"Night {got['number']} of {ds['name']}, {got['status']}, started {_day(got['started_at'])} "
             f"(by {got['by']}), cost ${float(got['cost_usd'] or 0):.4f}, took {_took(got['ms'] or 0)}.",
             got.get("summary") or ""]
    if got["status"] in ("running", "queued"):
        pr = got.get("progress") or {}
        lines.append(f"Still {got['status']}: {pr.get('stage', '')} {pr.get('done', '')} of {pr.get('groups', '')}.")
    for d in got.get("diary") or []:
        lines.append("- " + d["text"])
    if got.get("stopped_why"):
        lines.append("Stopped: " + got["stopped_why"])
    for v in got["changes"][:30]:
        lines.append(_change_line(v))
    if len(got["changes"]) > 30:
        lines.append(f"... and {len(got['changes']) - 30} more on the Dreams page.")
    return "\n".join(l for l in lines if l)


def _change_line(v: dict) -> str:
    old, new = v.get("old") or {}, v.get("new") or {}
    what = {"superseded": f"replaced: \"{old.get('text')}\" ({old.get('title')}) by \"{new.get('text') or new.get('title')}\" ({new.get('title')}, {_day(new.get('said_at'))})",
            "ask_closed": f"ask closed: \"{old.get('text')}\" ({old.get('title')}), closed by {new.get('title')}",
            "promise_kept": f"promise kept: \"{old.get('text')}\" ({old.get('title')}), shown by {new.get('title')}",
            "duplicate": f"duplicate: {old.get('title')} is the same as {new.get('title')}",
            "misfiled_rule": f"rule that is a {v['payload'].get('to_kind', 'fact')}: \"{old.get('text')}\" ({old.get('title')})",
            "contradiction": f"contradiction: \"{old.get('text')}\" ({old.get('title')}) against \"{new.get('text')}\" ({new.get('title')})",
            "sensitivity_mismatch": f"thread raised to {v['payload'].get('to')}: " + ", ".join(
                r.get("title") or "" for r in v["payload"].get("raise") or []),
            "link_strength": f"link {v['payload'].get('link_words')}: {v['payload'].get('from')} to {v['payload'].get('to')}",
            }.get(v["kind"], v["kind"])
    night_no = f"night {v['night']}, " if v.get("night") else ""
    return f"- [{night_no}change {v['id']}, {v['state']}] {what}. Why: {v['reason']}"
