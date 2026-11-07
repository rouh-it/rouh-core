"""A question, from the words asked to the answer with citations (D36 to D50, D56, D59).

1. **Understand** (D50): the answer model, with the map and the rules in front of
   it, writes the search query and its filters. It is the turn's first request;
   there is no separate planning call.
2. **Embed** the query, **search** words and meaning, fuse (D36).
3. Optionally **rerank** the top 100 with a decision model, fused as a third list (D70).
4. **Seeds**: 20, the search's best in its order (diversity, D47, is off since
   attempt 35); in a background pack about an incoming item, the fixed order
   of D56 first: open asks and promises between its sender and the owner,
   recent threads on the same subjects, the topic layers, the sender's profile.
5. **Walk** (D41 to D45, D71), frame by frame.
6. **Pack** (D46): grouped by how each item was reached, open asks and promises
   first, compact lines numbered [1], [2] for this answer only (D11, D23).
7. **Rules** (D59): every rule attached to what is in play, never searched: the account's own, and those
   for the context item, the pack's own people and tasks, and what the pack's items are in or from. Each is
   numbered after the pack, so an answer can cite the rule it follows like any item (attempt 32).
8. **Checkpoint** (D50): the answer model reads the pack and answers, opens up to
   3 raw items, or searches again; a decision model asks in shadow whether the
   pack was enough, and nothing acts on it (D72).
9. **Answer**, citing [n]; code checks every number was in the pack, and writes
   down which items were shown and which were used (D57).
"""
from __future__ import annotations

import concurrent.futures
import math
import operator
import re
import time

from . import ai, datasets, db, mapping, people, personrefs, search, taskrefs, text as tx, vectors
from .db import Json
from .trace import Trace
from .walk import Walk, facts_of

UNDERSTAND_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["query", "kinds", "why", "map_enough"],
    "properties": {"query": {"type": "string"},
                   "kinds": {"type": "array", "items": {"type": "string"}},
                   "why": {"type": "string"},
                   "map_enough": {"type": "boolean"}},
}

UNDERSTAND_INSTRUCTIONS = (
    "Write the search query Synapse should run for this question: the words and names most likely to appear in "
    "what answers it, in the owner's own words from the map where they apply. kinds may narrow it (mail, note, "
    "doc, task, event, person, topic, layer), or be empty. map_enough is true only when the MAP alone answers "
    "the question fully and exactly (such as which areas there are, or what is active now), so no search is "
    "needed; when in doubt it is false.")

#: Without the map (`map_on` off, D85) there is nothing that could be enough without a search.
UNDERSTAND_NO_MAP = (
    "Write the search query Synapse should run for this question: the words and names most likely to appear in "
    "what answers it. kinds may narrow it (mail, note, doc, task, event, person, topic, layer), or be empty. "
    "map_enough is always false.")

ANSWER_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["action", "open", "query", "answer", "cited", "enough_why"],
    "properties": {"action": {"type": "string", "enum": ["answer", "open", "recall"]},
                   "open": {"type": "array", "items": {"type": "integer"}},
                   "query": {"type": "string"},
                   "answer": {"type": "string"},
                   "cited": {"type": "array", "items": {"type": "integer"}},
                   "enough_why": {"type": "string"}},
}

ANSWER_INSTRUCTIONS = """You are Rouh, answering {owner} from Synapse, their memory. You are given the MAP (what areas exist and what is active), the RULES that apply (always follow them), and a PACK of items found for this question, each numbered [n] for this answer only. The RULES are numbered after the pack: when what you say, or what you do, comes from a rule, cite its number like an item's.

Decide one of three things:
- answer: answer from the pack. Cite every fact with the number of the item it comes from, like [3] or [2][5]. Never cite a number that is not in the pack. Kinds in capitals (ASK, PROMISE, OPEN, CAVEAT) are doubts and asks worth saying.
- open: when the answer depends on an item's exact words, ask to open up to {raw} items' raw text by number.
- recall: when the pack is about the wrong thing or too thin, give a narrower or different search query.
The GIST and claim lines are Synapse's summary of an item and leave out exact details: links, IDs, codes, numbers, amounts, times, seats, addresses, names in lists, contract clauses. WORDS are an item's whole text; PASSAGES are only the parts of a long item that matched the question. So before you say an item does not hold something, look in its WORDS, and if it shows only PASSAGES or nothing of its own words, open it. Say that Synapse has nothing on it, citing nothing, only when neither the pack nor what you opened holds the answer.
You may open or recall at most {extra} more times; after that you must answer. Put the numbers you used in cited. enough_why says in one line why the pack was or was not enough. Plain language, no em dashes."""


def _owner(ds):
    return datasets.owner_of(ds)


def rules_in_play(ds: dict, asker: str, context_item: dict | None, gathered_ids: list[str]) -> list[dict]:
    """Every rule attached to what is in play, plus the account-wide ones (D59).

    In play is the context item and what it is from, in or about, and the pack's first 40 items, each itself
    and what it is in or from. The items themselves count since attempt 32: before, only what they link to
    did, so a pack holding a contact never loaded the rule written for that contact (their default address)."""
    targets = set()
    if context_item:
        targets.add(context_item["id"])
        for l in db.rows("SELECT dst FROM synapse.link WHERE dataset_id = %s AND src = %s AND type IN ('from', 'in', 'about')",
                         (ds["id"], context_item["id"])):
            targets.add(l["dst"])
    first = [str(g) for g in gathered_ids[:40]]
    if first:
        targets |= set(first)
        for l in db.rows("SELECT DISTINCT dst FROM synapse.link WHERE dataset_id = %s AND src = ANY(%s::uuid[]) "
                         "AND type IN ('in', 'from')", (ds["id"], first)):
            targets.add(l["dst"])
    readers = search.readers_for(asker)
    rules = db.rows(
        "SELECT DISTINCT i.id, i.title, i.body, i.meta, (i.meta->>'scope') AS scope, i.stored_at FROM synapse.item i "
        "LEFT JOIN synapse.link l ON l.dataset_id = i.dataset_id AND l.src = i.id AND l.type = 'rule_for' "
        "WHERE i.dataset_id = %s AND i.kind = 'rule' AND i.deleted_at IS NULL AND "
        # A rule kept to written or spoken replies is how a turn of Rouh's replies, not an answer's (`rules.MODES`).
        "coalesce(i.meta->>'mode', '') = '' AND "
        # One turned off on the Rules page is told to nothing (`rules.set_on`).
        "coalesce(i.meta->>'off', 'false') <> 'true' AND "
        # Only a rule that reaches Synapse's answers (`rules.reach`): none with a place in a conversation's
        # prompt or a condition only a conversation turn has, and none kept to other work by its own `in`.
        "NOT i.meta ? 'place' AND (coalesce(i.meta->'when', '{}'::jsonb) - 'in') = '{}'::jsonb AND "
        "(NOT coalesce(i.meta->'when', '{}'::jsonb) ? 'in' OR i.meta->'when'->'in' ? 'synapse') AND "
        f"{search.readable_sql('i')} AND (i.meta->>'scope' = 'account' OR l.dst = ANY(%s::uuid[]))",
        (ds["id"], readers, [str(t) for t in targets] or ["00000000-0000-0000-0000-000000000000"]))
    # The account's own first, then those for something in play, each in the order they were written.
    rules.sort(key=lambda r: (r.get("scope") != "account", str(r.get("stored_at") or ""), str(r["id"])))
    names: dict = {}
    if rules:
        for t in db.rows("SELECT l.src, t.title FROM synapse.link l JOIN synapse.item t ON t.id = l.dst "
                         "WHERE l.dataset_id = %s AND l.src = ANY(%s::uuid[]) AND l.type = 'rule_for' ORDER BY t.title",
                         (ds["id"], [r["id"] for r in rules])):
            names.setdefault(t["src"], []).append(t["title"])
    return [{"id": r["id"], "text": r["body"] or r["title"], "title": r["title"],
             "account": r.get("scope") == "account",
             "for": "the whole account" if r.get("scope") == "account" else ", ".join(names.get(r["id"], []))}
            for r in rules]


def _mmr(cands: list[dict], vectors: dict, take: int, lam: float) -> tuple[list[dict], list[dict]]:
    """Maximal marginal relevance over the fused list (D47).

    Each vector is made unit length once, and each candidate keeps its highest similarity to what is
    chosen so far, so a round compares the pool with the one item just chosen and nothing else: pool
    times seeds products, where comparing with every chosen item each round took 1.5 seconds of every
    pack (measured on Rouh inbox, 4 October 2026)."""
    chosen, log = [], []
    pool = list(cands)
    best = max((c["rrf"] for c in pool), default=1.0) or 1.0
    unit = {}
    for c in pool:
        v = vectors.get(c["item_id"])
        if v:
            n = math.sqrt(sum(x * x for x in v)) or 1.0
            unit[c["item_id"]] = [x / n for x in v]
    red: dict = {c["item_id"]: None for c in pool}
    while pool and len(chosen) < take:
        scored = []
        for c in pool:
            rel = c["rrf"] / best
            r = red[c["item_id"]] or 0.0
            scored.append((lam * rel - (1 - lam) * r, rel, r, c))
        scored.sort(key=lambda t: -t[0])
        m, rel, r, c = scored[0]
        chosen.append(c)
        log.append({"id": c["item_id"], "relevance": round(rel, 4), "redundancy": round(r, 4), "mmr": round(m, 4)})
        pool.remove(c)
        just = unit.get(c["item_id"])
        for o in pool:
            u = unit.get(o["item_id"])
            # An item with no vector is as unlike everything as can be counted: 0.
            sim = sum(map(operator.mul, u, just)) if (u and just) else 0.0
            if red[o["item_id"]] is None or sim > red[o["item_id"]]:
                red[o["item_id"]] = sim
    return chosen, log


def _by_rank(cands: list[dict], take: int) -> tuple[list[dict], list[dict]]:
    """The fused list's first `take`, as `_mmr` gives them at a weight of 1.0, with the same log."""
    chosen = cands[:take]
    best = max((c["rrf"] for c in chosen), default=1.0) or 1.0
    return chosen, [{"id": c["item_id"], "relevance": round(c["rrf"] / best, 4), "redundancy": 0.0,
                     "mmr": round(c["rrf"] / best, 4)} for c in chosen]


def _context_seeds(ds: dict, ctx: dict, asker: str) -> list[dict]:
    """D56's fixed order for a background pack about an incoming item."""
    meta = ctx.get("meta") or {}
    sender = tx.address_of(meta.get("from") or "")
    # Claims name people as the X-ray writes them, by first name (`who`, `to`).
    me = datasets.me_word(ds)
    them = datasets.principal(sender[0]) if sender[0] else ""
    who = people.find_address(ds, meta.get("from") or "") if meta.get("from") else None
    out = []
    # 1. Open asks and promises between the sender and the owner.
    if them:
        for r in db.rows("SELECT id, title, xray FROM synapse.item WHERE dataset_id = %s AND deleted_at IS NULL "
                         "AND xray IS NOT NULL AND kind <> 'layer' AND id <> %s ORDER BY said_at DESC LIMIT 300",
                         (ds["id"], ctx["id"])):
            for c in (r.get("xray") or {}).get("claims") or []:
                named = set(c.get("who") or []) | set(c.get("to") or [])
                if c.get("k") in ("ask", "promise") and c.get("open") and them in named and me in named:
                    out.append({"id": r["id"], "R": 1.0, "why": "an open ask or promise between them (D56, 1)"})
                    break
    # 2. Recent threads on the same subjects: thread layers about the same topics.
    topics = [r["dst"] for r in db.rows("SELECT dst FROM synapse.link WHERE dataset_id = %s AND src = %s AND type = 'about'",
                                        (ds["id"], ctx["id"]))]
    if topics:
        for r in db.rows("SELECT DISTINCT i.id FROM synapse.item i JOIN synapse.link l ON l.dataset_id = i.dataset_id "
                         "AND l.src = i.id WHERE i.dataset_id = %s AND i.kind = 'layer' AND i.meta->>'layer' = 'thread' "
                         "AND i.deleted_at IS NULL AND l.type = 'built_from' AND l.dst IN (SELECT src FROM synapse.link "
                         "WHERE dataset_id = %s AND type = 'about' AND dst = ANY(%s::uuid[])) LIMIT 6",
                         (ds["id"], ds["id"], topics)):
            out.append({"id": r["id"], "R": 0.9, "why": "a recent thread on the same subject (D56, 2)"})
        # 3. What we know about the subject: topic layers.
        for r in db.rows("SELECT DISTINCT i.id FROM synapse.item i JOIN synapse.link l ON l.dataset_id = i.dataset_id "
                         "AND l.src = i.id WHERE i.dataset_id = %s AND i.kind = 'layer' AND i.deleted_at IS NULL "
                         "AND l.type = 'about' AND l.dst = ANY(%s::uuid[]) LIMIT 6", (ds["id"], topics)):
            out.append({"id": r["id"], "R": 0.85, "why": "a topic layer for the same subject (D56, 3)"})
    # 4. Their profile.
    if who:
        for r in db.rows("SELECT i.id FROM synapse.item i JOIN synapse.link l ON l.dataset_id = i.dataset_id AND l.src = i.id "
                         "WHERE i.dataset_id = %s AND i.kind = 'layer' AND i.meta->>'layer' = 'profile' AND l.dst = %s "
                         "AND i.deleted_at IS NULL", (ds["id"], who["id"])):
            out.append({"id": r["id"], "R": 0.8, "why": "the sender's profile (D56, 4)"})
    seen, uniq = set(), []
    for x in out:
        if x["id"] not in seen:
            seen.add(x["id"])
            uniq.append(x)
    readable = {r["id"] for r in db.rows(
        f"SELECT i.id FROM synapse.item i WHERE i.dataset_id = ANY(synapse.scope(%s)) AND i.id = ANY(%s::uuid[]) "
        f"AND {search.readable_rule_sql('i')}",
        (ds["id"], list(seen) or ["00000000-0000-0000-0000-000000000000"], search.readers_for(asker),
         search.readers_for(asker)))}
    return [x for x in uniq if x["id"] in readable]


def _silo_first(ds: dict, fused: list[dict], prefer: str) -> tuple[list[dict], dict]:
    """The fused list with the items of one silo first, then those in no silo, then the rest, each group in
    its own order: nothing is dropped, so the rest is still there when it helps (`rouh/silos.py`)."""
    have = {r["id"]: list(r["silos"] or []) for r in db.rows(
        "SELECT id, silos FROM synapse.item WHERE dataset_id = ANY(synapse.scope(%s)) AND id = ANY(%s::uuid[])",
        (ds["id"], [f["item_id"] for f in fused]))}

    def rank(f) -> int:
        got = have.get(f["item_id"], [])
        return 0 if prefer in got else 1 if not got else 2

    ordered = sorted(fused, key=rank)
    counts = {"first": 0, "not_known": 0, "other_silos": 0}
    for f in fused:
        counts[("first", "not_known", "other_silos")[rank(f)]] += 1
    return ordered, {"silo": prefer, **counts,
                     "note": "Items of that silo come first, then the ones in no silo, then the rest; none is dropped."}


def _boost_ids(ds: dict, ctx: dict | None) -> set:
    """Items in the context's task, or from its sender (D48)."""
    if not ctx:
        return set()
    ids = set()
    targets = [r["dst"] for r in db.rows("SELECT dst FROM synapse.link WHERE dataset_id = %s AND src = %s AND "
                                         "type IN ('in', 'from', 'in_thread')", (ds["id"], ctx["id"]))]
    if targets:
        for r in db.rows("SELECT src FROM synapse.link WHERE dataset_id = %s AND dst = ANY(%s::uuid[]) AND "
                         "type IN ('in', 'from', 'in_thread')", (ds["id"], targets)):
            ids.add(r["src"])
        ids |= set(targets)
    return ids


def own_words(ds: dict, gathered: list[dict], facts: dict, s, query: str = "", qvec=None,
              qmodel: str | None = None) -> dict[str, str]:
    """Each pack item's own words, under its X-ray lines (D46, revised 4 October 2026).

    The X-ray keeps the gist and the claims, never an exact link, ID, card number,
    seat or clause, so an answer from X-ray lines alone says "nothing on it" about
    what the item plainly says. Best-scored items first, while `pack_words_tokens`
    lasts: a short item whole, a long one's passages that best match the question
    (meaning and words). An item with no claims already shows its text, so it only
    gets more of it. A meeting's transcript is passages of their own beside its
    text (`meetings.py`): its best ones come under its words, however short they are."""
    budget = int(s.pack_words_tokens)
    short = int(s.pack_words_short_chars)
    per_item = int(s.pack_passages_per_item)
    ids = [g["id"] for g in sorted(gathered, key=lambda g: -g["score"]) if g["id"] in facts]
    if budget <= 0 or not ids:
        return {}
    raws = {r["id"]: r for r in db.rows(
        "SELECT id, kind, length(coalesce(raw, '')) AS n, CASE WHEN length(coalesce(raw, '')) <= %s THEN raw END AS raw "
        "FROM synapse.item WHERE dataset_id = ANY(synapse.scope(%s)) AND id = ANY(%s::uuid[])", (short, ds["id"], ids))}
    long_ids = [i for i in ids if (raws.get(i) or {}).get("n", 0) > short or (raws.get(i) or {}).get("kind") == "meeting"]
    best: dict[str, list[dict]] = {}
    if long_ids and per_item > 0:
        v = db.vec(qvec) if qvec is not None else None
        got = db.rows(
            "WITH q AS (SELECT CASE WHEN numnode(plainto_tsquery('english', %s) || plainto_tsquery('simple', %s)) > 0 "
            "  THEN replace((plainto_tsquery('english', %s) || plainto_tsquery('simple', %s))::text, '&', '|')::tsquery "
            "  END AS w) "
            "SELECT p.item_id, p.part, p.seq, p.text, "
            " coalesce(CASE WHEN %s::halfvec IS NOT NULL AND p.vec IS NOT NULL AND p.embed_model = %s "
            "   THEN 1 - (p.vec <=> %s::halfvec) END, 0) "
            " + coalesce(CASE WHEN q.w IS NOT NULL THEN ts_rank_cd(p.words, q.w) END, 0) AS score "
            "FROM synapse.passage p, q WHERE p.dataset_id = ANY(synapse.scope(%s)) AND p.item_id = ANY(%s::uuid[]) "
            "AND NOT p.from_xray ORDER BY p.item_id, score DESC",
            (query, query, query, query, v, qmodel or "", v, ds["id"], long_ids))
        for r in got:
            # Up to `per_item` of each part: a meeting's transcript is counted apart from its text.
            if sum(1 for p in best.setdefault(r["item_id"], []) if p.get("part") == r.get("part")) < per_item:
                best[r["item_id"]].append(r)
    out, used = {}, 0
    for i in ids:
        f, r = facts[i], raws.get(i) or {}
        has_claims = bool(((f.get("xray") or {}).get("claims")))
        heard = [p for p in best.get(i) or [] if p.get("part")] if r.get("raw") is not None else []
        if r.get("raw") is not None:
            text = " ".join((r["raw"] or "").split())
            if (not text or (not has_claims and len(text) <= 900)) and not heard:
                continue
            block = "    WORDS: " + text if text and (has_claims or len(text) > 900) else ""
            if heard:
                # A meeting: what was said that best matches the question, from its transcript.
                parts = sorted(heard, key=lambda p: p["seq"] or 0)
                block += ("\n" if block else "") + (
                    f"    FROM THE TRANSCRIPT ({len(parts)} passages picked for the question):\n" +
                    "\n".join("    ... " + " ".join(p["text"].split()) + " ..." for p in parts))
        elif best.get(i):
            parts = sorted(best[i], key=lambda p: (p.get("part") or "", p["seq"] or 0))
            block = (f"    PASSAGES ({len(parts)} picked for the question, of {r['n']} characters):\n" +
                     "\n".join("    ... " + " ".join(p["text"].split()) + " ..." for p in parts))
        else:
            continue
        cost = tx.tokens(block)
        if used + cost > budget:
            continue
        out[i] = block
        used += cost
    return out


#: How many newer items a pack brings in because they replaced a claim of an item in it (D93), and from how
#: many of its best-scored items: a replaced claim of an item far down the pack is not worth another item's room.
NEWER_MOST = 5
NEWER_FROM_TOP = 5


def _newer_items(ds: dict, gathered: list[dict], facts: dict, principals: list[str] | None) -> list[dict]:
    """Items not in the pack that a night of dreaming says replaced a claim of one that is, and that the asker
    may read: brought in just after the item they replaced, so the current value is there to cite."""
    have = {g["id"] for g in gathered}
    score = {g["id"]: g["score"] for g in gathered}
    top = {g["id"] for g in sorted(gathered, key=lambda g: -g["score"])[:NEWER_FROM_TOP]}
    wanted: dict[str, float] = {}
    for item_id, f in facts.items():
        if item_id not in top:
            continue
        for n in (f.get("_notes") or {}).values():
            by = str(n.get("by_item") or "")
            if n.get("note") == "replaced" and by and by not in have:
                wanted[by] = max(wanted.get(by, 0.0), float(score.get(item_id, 0.0)))
    if not wanted:
        return []
    ok = {r["id"] for r in db.rows(
        "SELECT id FROM synapse.item i WHERE i.dataset_id = ANY(synapse.scope(%s)) AND i.id = ANY(%s::uuid[]) "
        "AND i.deleted_at IS NULL AND " + search.readable_sql("i"),
        (ds["id"], list(wanted), principals or search.readers_for(datasets.me(ds))))}
    ranked = sorted((i for i in wanted if i in ok), key=lambda i: -wanted[i])[:NEWER_MOST]
    return [{"id": i, "branch": "__newer__", "score": wanted[i] * 0.999, "path": []} for i in ranked]


#: Rouh's own bookkeeping beside a workspace's files: what a task or a page is, never what it says.
SIDECAR = re.compile(r"(^|/)(\.object\.json|[^/]*\.xray\.json|_tasks\.md)$")
#: A page's list of the pages it read: worth a place only when the question is about sources.
SOURCE_LIST = re.compile(r"(^|/)sources\.(json|md)$")
ABOUT_SOURCES = re.compile(r"\b(sources?|links?|urls?|references?|footnotes?|cit(?:e|ed|es|ing|ations?))\b", re.I)
#: A file Synapse could not read, which it describes by its name and size alone (`master._file_words`).
NOT_READ = re.compile(r"(?s)^(?:[^\n]*\n\s*)?A (?:picture|file): [^\n]*Its contents are not read as words\.\s*$")


def with_evidence(ds: dict, gathered: list[dict], question: str) -> tuple[list[dict], list[dict]]:
    """The walk's items that have something to read, and those left out, each with why: a picture or file
    Synapse could not read, which is only its name and size; Rouh's sidecars (`.object.json`, a page's
    `.xray.json`, `_tasks.md`); and a page's list of sources, unless the question is about sources. An item
    with words of its own, a caption, or text read from a picture stays, and the walk still went through
    every one (24 October 2026)."""
    if not gathered:
        return gathered, []
    rows = {r["id"]: r for r in db.rows(
        "SELECT id, kind, source_key, CASE WHEN kind = 'file' THEN left(coalesce(body, raw, ''), 600) END AS start, "
        "meta->>'caption' AS caption FROM synapse.item WHERE dataset_id = ANY(synapse.scope(%s)) "
        "AND id = ANY(%s::uuid[])", (ds["id"], [g["id"] for g in gathered]))}
    sources_asked = bool(ABOUT_SOURCES.search(question or ""))
    kept, out = [], []
    for g in gathered:
        r = rows.get(g["id"]) or {}
        key = str(r.get("source_key") or "")
        why = ""
        if r.get("kind") == "file" and not r.get("caption") and NOT_READ.match(str(r.get("start") or "")):
            why = "a file Synapse could not read: only its name and size"
        elif key.startswith("file:") and SIDECAR.search(key):
            why = "Rouh's own bookkeeping beside the files"
        elif key.startswith("file:") and SOURCE_LIST.search(key) and not sources_asked:
            why = "a page's list of sources, and the question is not about sources"
        if why:
            out.append({"id": g["id"], "key": key, "why": why})
        else:
            kept.append(g)
    return kept, out


#: Room kept for the line that heads a group of the pack and the line breaks, in handed tokens per item.
FIT_SPARE = 4
#: What an item no model has read shows of its text when it goes in without its own words, in characters.
BARE_CHARS = 300


def _fitted(gathered: list[dict], facts: dict, fit: int, line_of, levels: tuple = (1,)) -> tuple[set, dict]:
    """Which items go in, and how much of each (`line_of(g, level)`, 0 the least), so the pack stays within
    `fit` handed tokens. First every item at level 0, best-scored first, while they fit; then, for each of
    `levels` in turn, best first, each item still at 0 raised to it while that fits. On the benchmark this
    kept far more of the gold at a budget than giving each item its words in turn (24 October 2026), and more
    again when level 0 is an item's gist and first claims, and the best items get their own words before the
    others get the rest of their claims (attempt 40). The best item always goes in. Returns the items kept
    and, for each, the level it got."""
    ranked = [g for g in sorted(gathered, key=lambda g: -g["score"]) if g["id"] in facts]
    keep, used, heads, cost_at, level = [], 0, set(), {}, {}
    for g in ranked:
        head = 0 if g["branch"] in heads else tx.handed("FOUND THROUGH: " + str(g["branch"])[:60])
        cost_at[g["id"]] = tx.handed(line_of(g, 0))
        cost = cost_at[g["id"]] + FIT_SPARE + head
        if keep and used + cost > fit:
            continue
        keep.append(g)
        used += cost
        heads.add(g["branch"])
        level[g["id"]] = 0
    for target in levels:
        for g in keep:
            if level[g["id"]]:
                continue
            more = tx.handed(line_of(g, target)) - cost_at[g["id"]]
            if more <= 0 or used + more <= fit:
                used += max(0, more)
                level[g["id"]] = target
    return {g["id"] for g in keep}, level


def build_pack(ds: dict, gathered: list[dict], titles: dict, start: int = 1, *, s=None, query: str = "",
               qvec=None, qmodel: str | None = None, asker: str | None = None, fit: int = 0) -> dict:
    """D46: grouped by how each item was reached, open asks and promises first.

    A night of dreaming's notes are read for the asker (D86, `dreaming.annotate`): a claim replaced by an item
    in the pack is reduced to a marker naming it, and the newer item is brought in when it is not there; a
    closed ask is never under OPEN ASKS AND PROMISES; a duplicate kept as an alias is left out when its
    canonical item is in the pack. `fit`, when given, is the most handed tokens the pack's text may come to
    (`_fitted`): the best-scored items, some without their own words or with only their first claims, and
    none cut in the middle."""
    from . import dreaming

    principals = search.readers_for(asker) if asker else None
    facts = facts_of(ds["id"], [g["id"] for g in gathered])
    dreaming.annotate(ds["id"], facts, principals)
    newer = _newer_items(ds, gathered, facts, principals)
    if newer:
        more = facts_of(ds["id"], [g["id"] for g in newer])
        dreaming.annotate(ds["id"], more, principals)
        facts.update(more)
        gathered = list(gathered) + newer
        titles = dict(titles, __newer__="a newer item that replaced a claim above (a night of dreaming)")
    present = {g["id"] for g in gathered}
    gathered = [g for g in gathered if not (facts.get(g["id"], {}).get("alias_of")
                                            and str(facts[g["id"]]["alias_of"]) in present)]
    words = own_words(ds, gathered, facts, s, query, qvec, qmodel) if s is not None else {}

    first_claims = int(getattr(s, "handed_first_claims", 0) or 0) if s is not None else 0

    asked = tx.question_stems(query) if first_claims else set()

    def line_of(n, g, refs, level=2):
        """An item's lines: whole (level 2), with its own words; or, to fit a budget, without them (1), and with
        no more of an item no model has read than `BARE_CHARS` of its text; or less again (0), only its first
        `handed_first_claims` claims (attempt 40)."""
        f, extra = facts[g["id"]], words.get(g["id"]) if level >= 2 else None
        if level <= 0 and first_claims:
            return tx.compact(n, f, raw_chars=BARE_CHARS, refs=refs, claims_at_most=first_claims,
                              claims_for=asked)
        if level <= 1:
            return tx.compact(n, f, raw_chars=BARE_CHARS, refs=refs)
        if extra and extra.startswith("    WORDS:") and not (f.get("xray") or {}).get("claims"):
            return tx.compact(n, f, raw_chars=int(s.pack_words_short_chars), refs=refs)
        return tx.compact(n, f, refs=refs) + ("\n" + extra if extra else "")

    level: dict = {}
    if fit:
        def sized(g, at):
            # Without first claims, level 0 is an item with all its claims, as until attempt 40.
            return line_of(99, g, {}, at if first_claims or at else 1)
        keep, level = _fitted(gathered, facts, int(fit), sized, levels=(2, 1) if first_claims else (2,))
        if not first_claims:
            level = {k: v or 1 for k, v in level.items()}
        gathered = [g for g in gathered if g["id"] in keep]

    def has_open(it):
        notes = it.get("_notes") or {}
        return any(tx.is_open(c, notes.get(i)) for i, c in enumerate((it.get("xray") or {}).get("claims") or []))
    # First the order and the numbers, so a line can name the item that replaced or closed one of its claims.
    order: list[tuple[str, dict]] = []
    first = [g for g in gathered if g["id"] in facts and has_open(facts[g["id"]])]
    for g in sorted(first, key=lambda x: -x["score"]):
        order.append(("OPEN ASKS AND PROMISES", g))
    done = {g["id"] for _, g in order}
    groups: dict[str, list[dict]] = {}
    for g in gathered:
        groups.setdefault(g["branch"], []).append(g)
    ranked = sorted(groups.items(), key=lambda kv: -max(x["score"] for x in kv[1]))
    for branch, members in ranked:
        for g in sorted(members, key=lambda x: -x["score"]):
            if g["id"] not in done and g["id"] in facts:
                order.append((f"FOUND THROUGH: {titles.get(branch, 'a seed')}", g))
                done.add(g["id"])
    refs = {g["id"]: start + k for k, (_, g) in enumerate(order)}

    items, blocks, head_now = [], [], None
    for head, g in order:
        if head != head_now:
            blocks.append(head)
            head_now = head
        n, f = refs[g["id"]], facts[g["id"]]
        line = line_of(n, g, refs, level.get(g["id"], 2))
        blocks.append(line)
        entry = {"n": n, "id": g["id"], "title": f["title"], "kind": f["kind"], "score": round(g["score"], 5),
                 "group": "open asks and promises" if head.startswith("OPEN") else titles.get(g["branch"], ""),
                 "path": g["path"], "lines": line, "tokens": tx.tokens(line)}
        if not head.startswith("OPEN"):
            entry["route"] = (" → ".join([titles.get(p["from"], "")[:40] + f" ({p['type']})" for p in g["path"]])
                              if g["path"] else "a search seed")
        if f.get("_notes"):
            entry["dream_notes"] = {str(i): {"note": x["note"], "by": refs.get(str(x.get("by_item") or ""))}
                                    for i, x in f["_notes"].items()}
        items.append(entry)
    text = "\n".join(blocks)
    return {"items": items, "text": text, "tokens": tx.tokens(text), "handed": tx.handed(text)}


def _seed_rerank(ds, question, fused, s, trace, owner) -> tuple[list[dict], dict]:
    cands = fused[:int(s.rerank_candidates)]
    facts = facts_of(ds["id"], [c["item_id"] for c in cands])
    hosted_ok = [c for c in cands if (facts.get(c["item_id"]) or {}).get("sensitivity") == "normal"]
    rest = [c for c in cands if c not in hosted_ok]
    info = {"candidates": len(cands), "normal": len(hosted_ok), "shape": s.rerank_shape}
    ranking = []
    lists = []
    for group, ceiling in ((hosted_ok, "normal"), (rest, "private")):
        if not group:
            continue
        state = f"QUESTION: {question}\n\nCANDIDATES:\n" + "\n".join(
            tx.compact(i + 1, facts[c["item_id"]], raw_chars=200) for i, c in enumerate(group) if c["item_id"] in facts)
        if s.rerank_shape == "choice":
            got = ai.decide("seed_rerank", state, [ai.Choice("best", "Which candidate helps most to answer the question?",
                                                             [f"[{i + 1}]" for i in range(len(group))])],
                            ceiling=ceiling, settings=s, trace=trace, live=True, items=[c["item_id"] for c in group],
                            owner=owner)
            probs = ((got.get("answers") or {}).get("best") or {}).get("probabilities") or {}
            scores = [(probs.get(f"[{i + 1}]", 0.0), c) for i, c in enumerate(group)]
        else:
            got = ai.decide_many("seed_rerank", state, [ai.Noul(f"c{i + 1}", f"Does [{i + 1}] help answer the question?")
                                                        for i in range(len(group))],
                                 per_call=int(s.rerank_per_call), ceiling=ceiling, settings=s, trace=trace, live=True,
                                 items=[c["item_id"] for c in group], owner=owner)
            scores = [(((got.get("answers") or {}).get(f"c{i + 1}") or {}).get("p_yes"), c) for i, c in enumerate(group)]
        lists.append({k: v for k, v in got.items() if k not in ("questions", "answers")})
        for p, c in scores:
            if p is not None:
                c["p_rerank"] = round(p, 4)
                ranking.append((p, c["item_id"]))
    ranking.sort(key=lambda t: -t[0])
    info["calls"] = lists
    info["ranked"] = len(ranking)
    if not ranking:
        info["fallback"] = "no decision scores came back, so the seeds are fused from words and meaning alone (D69)"
        return fused, info
    fused = search.add_list(fused, [r[1] for r in ranking], "decision", float(s.rrf_k))
    return fused, info


def _named_people(ds, question, fused, details, s, qvec, qmodel, asker) -> dict:
    """The people the question names, and their own mails, to be seeds besides the search's (attempt 30)."""
    began = time.time()
    who = personrefs.named(ds, question, fused, details, me=people.me(ds))
    readers = search.readers_for(asker)
    mails = personrefs.their_mails(ds, who["people"], qvec, readers=readers,
                                   take=int(s.person_mails), model=qmodel) if who["people"] else []
    # Mails that name them, written by and to others: an introduction, a hand-over (attempt 37).
    naming = personrefs.naming_mails(ds, who["people"], qvec, readers=readers, take=int(s.person_named_mails),
                                     model=qmodel, skip=[m["item_id"] for m in mails]) if who["people"] else []
    for m in naming:
        m["named"] = True
    return {"people": who["people"], "mails": mails + naming, "ms": int((time.time() - began) * 1000)}


def run(ds: dict, question: str, *, asker: str | None = None, context_item_id: str | None = None,
        mode: str = "live", override: dict | None = None, by: str = "page", label: str = "",
        answer: bool = True, query_id: str | None = None, engaged: bool = True, silo: str = "",
        understand: bool | None = None, handed: bool = False) -> dict:
    """One question, all of it written down. Returns the query row's id and what it found.

    `answer` has Synapse's own answer model answer it, through the checkpoint (the Synapse chat and the lab).
    `understand` has the answer model write the search query first; with Synapse's answer unless said.
    `handed` is for a model that reads the pack itself (`synapse_query` in Rouh's other chats, the benchmark's
    retrieval passes): the pack is fitted to `handed_tokens`, the rules for what it found counted in, and
    `handed_text` is what that model is given (24 October 2026).

    `silo` (a silo's key) puts that silo's items first among the seeds and leaves the rest after them
    (`_silo_first`); an asker limited to some silos (`in:<keys>:<id>`, `rouh/silos.py`) reads only those,
    and gets no map, which names areas of every silo."""
    from .. import silos

    s = datasets.settings(ds, override)
    owner = _owner(ds)
    asker = people.asker_id(ds, asker)
    limit = silos.split(asker)[0]
    limited = "" if limit is None else (silos.said(ds["user_id"], ds["org_id"], limit) if limit else "no silo")
    prefer = silo if silo in silos.keys(ds["user_id"], ds["org_id"]) else ""
    people.ensure_values(ds)
    question = " ".join((question or "").split())[:2000]
    ctx = None
    if context_item_id:
        from .ingest import get_item
        ctx = get_item(ds["id"], context_item_id)
    mode = "background" if mode == "background" else "live"
    trace = Trace(ds["id"], "query", f"Question: {question[:120]}", by=by)
    if query_id:
        db.run("UPDATE synapse.query SET trace_id = %s WHERE id = %s", (trace.id, query_id))
    else:
        query_id = db.value(
            "INSERT INTO synapse.query (dataset_id, question, context_item, asker, mode, by, label, settings, trace_id, engaged) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s) RETURNING id",
            (ds["id"], question, ctx["id"] if ctx else None, asker, mode, by, label, Json(override or {}), trace.id,
             engaged))
    began = time.time()
    result: dict = {"query": query_id, "trace": trace.id}
    try:
        with trace.step("map_rules", "The map and the account-wide rules, loaded before anything (D14, D59)"
                        if s.map_on else "No map: the map is switched off for this question (D85)") as st:
            map_text = mapping.text_for(ds, asker) if s.map_on and not limited else ""
            st.data.update({"map": map_text if s.map_on and not limited else
                            ("(none: the asker is limited to " + limited + ")" if limited else "(off, D85)"),
                            "map_tokens": tx.tokens(map_text), "limited_to": limited, "silo_first": prefer,
                            "map_on": bool(s.map_on), "asker": asker,
                            "asker_name": people.name_of(asker),
                            "context": {"id": ctx["id"], "title": ctx["title"]} if ctx else None, "mode": mode})
        search_query = question
        map_enough = False
        tasks = None
        if understand is None:
            understand = answer
        if understand:
            with trace.step("understand", "The model writes the search query (D50, step 1)") as st:
                ctx_line = ""
                if ctx:
                    ctx_line = "\nCONTEXT ITEM (the question is asked about it):\n" + tx.compact("c", ctx, raw_chars=1500)
                got = ai.generate(model=s.answer_model, name="understand", purpose="understand", trace=trace, owner=owner,
                                  items=[ctx["id"]] if ctx else [],
                                  schema=UNDERSTAND_SCHEMA,
                                  instructions=UNDERSTAND_INSTRUCTIONS if map_text else UNDERSTAND_NO_MAP,
                                  text=(f"MAP:\n{map_text}\n\n" if map_text else "") + f"QUESTION: {question}{ctx_line}",
                                  max_tokens=600)
                search_query = (got.get("query") or question).strip() or question
                # The rewrite helps a question that names nothing ("which of my calendars has Rouh been given")
                # and loses the anchor of one that does ("what's going on with 58", "Who is Sam?"), so a
                # question that names a task by number or a person is searched as asked (attempt 46).
                if s.plain_when_named and search_query != question:
                    readers = search.readers_for(asker)
                    tasks = taskrefs.resolve(ds, question, readers) if s.task_numbers else []
                    names = [] if tasks else personrefs.names_someone(ds, question, readers=readers,
                                                                      me=people.me(ds))
                    if tasks or names:
                        st.data.update({"rewrite": search_query, "as_asked_because": (
                            "it names task " + ", ".join(str(x["number"]) for x in tasks)) if tasks
                            else "it names " + ", ".join(names[:5])})
                        search_query = question
                # The map alone answers it: no search when `map_skip_search` allows it, and the checkpoint can
                # still search if it was wrong (D85). The model's verdict is kept on the step either way.
                said_enough = bool(map_text) and bool(got.get("map_enough")) and not ctx
                # Only an answer can come from the map alone; a model reading the pack itself gets a search.
                map_enough = said_enough and bool(s.map_skip_search) and answer
                st.data.update({"query": search_query, "kinds": got.get("kinds") or [], "why": got.get("why"),
                                "model": got.get("_model"), "map_said_enough": said_enough,
                                "map_enough": map_enough})
        if map_enough:
            result.update(_map_only(ds, query_id, trace, search_query, s))
            rules_text, numbered = _rules_step(ds, asker, ctx, [], s, trace, start=1)
            result["pack"]["items"].extend(numbered)
            db.run("UPDATE synapse.query SET pack = %s::jsonb WHERE id = %s", (Json(result["pack"]), query_id))
            answer_out = _checkpoint_and_answer(ds, question, ctx, s, trace, owner, asker, map_text,
                                                rules_text, result["pack"], result.pop("walked"), query_id)
            result["answer"] = answer_out
            return _finish(ds, query_id, trace, s, mode, began, result, answer_out, engaged)
        pack_began = time.time()
        # A task or step the question names by its number (`taskrefs`): no search can match "seventy" to task
        # 70, so its number and title join the search query, and with them its files, steps, cards and chats are
        # found by words and meaning like anything else.
        named = tasks if tasks is not None else (
            taskrefs.resolve(ds, question, search.readers_for(asker)) if s.task_numbers else [])
        if named:
            search_query = f"{search_query} ({'; '.join(taskrefs.label(x) for x in named)})"
        with trace.step("embed_query", "The query's vector (D37)") as st:
            got_q = vectors.query(ds, search_query, trace=trace, owner=owner)
            qvec, qmodel = got_q["vec"], got_q["model"]
            st.data.update({"model": qmodel, "dims": len(qvec or []),
                            "sample": [round(x, 4) for x in (qvec or [])[:8]]})
            if qvec is None:
                st.data["words_only"] = got_q["why"]
        with trace.step("search", "Hybrid search: words and meaning, fused by rank (D36, D38)") as st:
            found = search.hybrid(ds["id"], search_query, qvec, asker=asker, settings=s,
                                  exclude_kinds=[], depth=int(s.list_depth), model=qmodel)
            trace.call(kind="db", purpose="hybrid_search", backend="postgresql", ms=found["ms"])
            fused = found["items"]
            details = facts_of(ds["id"], [f["item_id"] for f in fused[:int(s.rerank_candidates)]])
            st.data.update({"query": search_query, "words_query": found["query_words"], "words": found["words"],
                            "meaning": found["meaning"], "fused": len(fused), "k": s.rrf_k, "db_ms": found["ms"],
                            "top": [{"id": f["item_id"], "title": (details.get(f["item_id"]) or {}).get("title"),
                                     "kind": (details.get(f["item_id"]) or {}).get("kind"), "rrf": round(f["rrf"], 5),
                                     "ranks": f["ranks"], "scores": f["scores"]} for f in fused[:40]],
                            "asker_readers": search.readers_for(asker), "terms": found.get("terms"),
                            "checked": found.get("checked"), "dropped": found.get("dropped"),
                            "recent": found.get("recent"), "ef_search": found.get("ef_search"),
                            "named_tasks": [{"id": x["id"], "title": x["title"], "number": x["number"],
                                             "words": x["words"]} for x in named]})
        their = []
        if fused and (int(s.person_mails) > 0 or int(s.person_named_mails) > 0):
            with trace.step("named_people", "People the question names, and their own mails as seeds") as st:
                info = _named_people(ds, question, fused, details, s, qvec, qmodel, asker)
                their = info["mails"]
                st.data.update(info)
        if prefer and fused:
            with trace.step("silo_first", f"The {silos.said(ds['user_id'], ds['org_id'], [prefer])} silo first, "
                            "the rest after it") as st:
                fused, info = _silo_first(ds, fused, prefer)
                st.data.update(info)
        if s.seed_rerank and fused:
            with trace.step("rerank", "Seed rerank by a decision model, fused as a third list (D70)") as st:
                fused, info = _seed_rerank(ds, search_query, fused, s, trace, owner)
                st.data.update(info)
        with trace.step("seeds", "Seeds chosen with diversity (D42, D47)") as st:
            take = int(s.seeds)
            if float(s.diversity) >= 1.0:
                # No diversity: the search's best, in its order, with no vectors to read (attempt 35).
                chosen, mmr_log = _by_rank(fused, take)
            else:
                item_vecs = search.item_vectors(ds["id"], [f["item_id"] for f in fused[:max(60, take * 3)]])
                chosen, mmr_log = _mmr(fused[:max(60, take * 3)], item_vecs, take, float(s.diversity))
            best = max((c["rrf"] for c in chosen), default=1.0) or 1.0
            seeds = [{"id": c["item_id"], "R": c["rrf"] / best, "why": "search", "ranks": c["ranks"]} for c in chosen]
            # A named person's own mails are seeds besides the search's, never in place of them (attempt 30).
            have, k = {x["id"] for x in seeds}, float(s.rrf_k)
            by_id = {f["item_id"]: f for f in fused}
            for rank, m in enumerate(their, start=1):
                if m["item_id"] in have:
                    continue
                rrf = (by_id.get(m["item_id"]) or {}).get("rrf", 0.0) + 1.0 / (k + rank)
                seeds.append({"id": m["item_id"], "R": min(1.0, rrf / best),
                              "why": "names a named person" if m.get("named") else "named person",
                              "ranks": {**(by_id.get(m["item_id"]) or {}).get("ranks", {}), "person": rank}})
            fixed = []
            if ctx and mode == "background":
                fixed = _context_seeds(ds, ctx, asker)
                seen = {f["id"] for f in fixed}
                seeds = fixed + [x for x in seeds if x["id"] not in seen]
            st.data.update({"seeds": len(seeds), "diversity": s.diversity, "mmr": mmr_log, "fixed_order": [
                {"id": f["id"], "why": f["why"]} for f in fixed]})
        boost = _boost_ids(ds, ctx)
        with trace.step("walk", "The budgeted best-first walk (D41 to D45)") as st:
            rare = search.rare_lexemes(found.get("lexemes") or [], int(found.get("n_passages") or 0),
                                       int(s.walk_words_df)) if float(s.walk_words) > 0 else []
            w = Walk(ds, search_query, qvec, asker=asker, s=s, mode=mode, trace=trace, owner=owner, boost_ids=boost,
                     qmodel=qmodel, rare=rare)
            w.seed(seeds)
            walked = w.run()
            trace.call(kind="db", purpose="walk_lookups", backend="postgresql", ms=walked["db_ms"])
            st.data.update({k: walked[k] for k in ("stop", "tokens", "budget", "expansions", "db_ms", "ms")})
            st.data["rare_words"] = rare
            st.data["gathered"] = len(walked["gathered"])
            st.data["frames"] = len(walked["frames"])
            st.data["decisions"] = walked["decisions"]
        with trace.step("pack", "The pack: grouped, open asks first, numbered for this answer (D46, D11, D23)") as st:
            gathered, left_out = with_evidence(ds, walked["gathered"], question)
            fit = 0
            if handed and int(s.handed_tokens) > 0:
                # The rules for what it found are handed with it and never cut, so the pack makes room for them.
                theirs = [r for r in rules_in_play(ds, asker, ctx, [g["id"] for g in gathered]) if not r["account"]]
                fit = max(1, int(s.handed_tokens) - HANDED_HEAD - sum(tx.handed(_rule_line(99, r)) + 1 for r in theirs))
            pack = build_pack(ds, gathered, walked["titles"], s=s, query=search_query, qvec=qvec,
                              qmodel=qmodel, asker=asker, fit=fit)
            st.data.update({"items": len(pack["items"]), "tokens": pack["tokens"], "handed": pack["handed"],
                            "fit": fit or None, "text": pack["text"], "left_out": left_out})
        ms_pack = int((time.time() - pack_began) * 1000)
        in_pack = [it["id"] for it in pack["items"]] if fit else [g["id"] for g in gathered]
        rules_text, numbered = _rules_step(ds, asker, ctx, in_pack, s, trace, start=len(pack["items"]) + 1)
        # The rules are numbered after the pack and listed with its items, so a citation of one is checked like
        # any other; the pack's text is unchanged, since the rules are told to the answer under RULES.
        pack["items"].extend(numbered)
        db.run("UPDATE synapse.query SET walk = %s::jsonb, pack = %s::jsonb, ms_pack = %s WHERE id = %s",
               (Json({"frames": walked["frames"], "stop": walked["stop"], "titles": walked["titles"],
                      "seeds": seeds, "budget": walked["budget"], "tokens": walked["tokens"],
                      "expansions": walked["expansions"], "decisions": walked["decisions"]}),
                Json(pack), ms_pack, query_id))
        result.update({"pack": pack, "ms_pack": ms_pack, "stop": walked["stop"]})
        answer_out = {}
        if answer:
            answer_out = _checkpoint_and_answer(ds, question, ctx, s, trace, owner, asker, map_text, rules_text, pack,
                                                walked, query_id)
            result["answer"] = answer_out
        return _finish(ds, query_id, trace, s, mode, began, result, answer_out, engaged)
    except Exception as exc:
        db.run("UPDATE synapse.query SET status = 'failed', answer = %s::jsonb WHERE id = %s",
               (Json({"error": f"{type(exc).__name__}: {exc}"}), query_id))
        trace.finish("failed", error=f"{type(exc).__name__}: {exc}")
        raise


#: Room kept in `handed_tokens` for the line `synapse_query` puts above the pack, and the labels around it.
HANDED_HEAD = 120
RULES_HEAD = "Rules for what it found (always follow them; cite by number):"


def _rule_line(n, r) -> str:
    """One rule as it is numbered: a rule written in lines or a list keeps them, each set in under its number."""
    return f"[{n}] " + str(r["text"]).replace("\n", "\n    ") + f" (for {r['for']})"


def handed_text(pack: dict) -> str:
    """What a model reading a question's pack itself is handed: the pack's lines, numbered, and the rules for
    what it found, numbered after them. The account's own rules are in every turn already, so not here."""
    text = str(pack.get("text") or "")
    theirs = [it["lines"] for it in pack.get("items") or [] if it.get("kind") == "rule" and not it.get("account")]
    return (text or "nothing") + (("\n" + RULES_HEAD + "\n" + "\n".join(theirs)) if theirs else "")


def _rules_step(ds, asker, ctx, gathered_ids, s, trace, *, start: int) -> tuple[str, list[dict]]:
    """The rules in play as the answer is told them, numbered from `start`, and each as a pack item."""
    with trace.step("rules", "Rules attached to what is in play, always loaded and numbered after the pack (D59)") as st:
        rules = rules_in_play(ds, asker, ctx, gathered_ids)
        lines, items = [], []
        for k, r in enumerate(rules):
            n = start + k
            line = _rule_line(n, r)
            lines.append(line)
            items.append({"n": n, "id": r["id"], "title": " ".join(str(r["title"] or r["text"]).split())[:120],
                          "kind": "rule", "score": 0.0, "group": "rules in play", "path": [],
                          "route": "a rule for the whole account" if r["account"] else f"a rule for {r['for']}",
                          "account": r["account"], "lines": line, "tokens": tx.tokens(line)})
        rules_text = "\n".join(lines)
        st.data.update({"rules": rules, "tokens": tx.tokens(rules_text), "numbered_from": start,
                        "budget": int(s.rules_account_tokens) + int(s.rules_item_tokens),
                        "over_budget": tx.tokens(rules_text) > int(s.rules_account_tokens) + int(s.rules_item_tokens),
                        "note": "Never searched, ranked, decayed or cut. Over budget, nothing is dropped; the "
                                "owner is asked to merge some."})
    return rules_text, items


def _map_only(ds, query_id, trace, search_query, s) -> dict:
    """A question the map alone answers (D85): no vector, no search, no walk, an empty pack. The checkpoint
    still sees the map and can search again (its recall action) when the map was not enough after all."""
    walked = {"gathered": [], "titles": {}, "frames": [], "stop": "the map answered it, so nothing was searched",
              "tokens": 0, "budget": int(s.budget_live), "expansions": 0, "decisions": []}
    said = ("Nothing was searched: the question looked answerable from the MAP alone. Answer from the MAP, citing "
            "nothing, or recall with a search query if the MAP does not answer it.")
    pack = {"items": [], "text": said, "tokens": tx.tokens(said)}
    with trace.step("search", "No search: the map alone answers it (D85)") as st:
        st.data.update({"query": search_query, "skipped": True,
                        "note": "The model that writes the search query said the map alone answers the question, so "
                                "nothing was searched. If the answer step finds the map was not enough, it searches "
                                "with its recall action, which shows as a checkpoint below."})
    db.run("UPDATE synapse.query SET walk = %s::jsonb, pack = %s::jsonb, ms_pack = 0 WHERE id = %s",
           (Json({**walked, "seeds": [], "skipped": True}), Json(pack), query_id))
    return {"pack": pack, "walked": walked, "ms_pack": 0, "stop": walked["stop"], "search_skipped": True}


def _finish(ds, query_id, trace, s, mode, began, result, answer_out, engaged) -> dict:
    with trace.step("use", "What was shown and what was used, for learning (D57)") as st:
        cited = set(answer_out.get("cited_ids") or [])
        all_items = answer_out.get("pack_items") or result["pack"]["items"]
        for rank, it in enumerate(all_items, start=1):
            db.run("INSERT INTO synapse.use (dataset_id, query_id, item_id, shown, cited, rank, path, engaged) "
                   "VALUES (%s, %s, %s, true, %s, %s, %s::jsonb, %s)",
                   (ds["id"], query_id, it["id"], it["id"] in cited, rank,
                    Json([p.get("link") for p in it.get("path") or [] if p.get("link")]), engaged))
        st.data.update({"shown": len(all_items), "cited": len(cited), "engaged": engaged,
                        "note": "Learning counts only questions a person asked, never background packs or "
                                "evaluation runs (D57)."})
    total = int((time.time() - began) * 1000)
    expires = None
    if mode == "background":
        expires = int(s.pack_days)
    db.run("UPDATE synapse.query SET status = 'done', ms_total = %s, cost_usd = %s, answer = %s::jsonb, "
           "expires_at = CASE WHEN %s::int IS NULL THEN NULL ELSE now() + make_interval(days => %s::int) END "
           "WHERE id = %s", (total, round(trace.cost, 6), Json(answer_out), expires, expires, query_id))
    trace.finish("done", ms_pack=result.get("ms_pack"), ms_total=total, items=len(result["pack"]["items"]),
                 cited=len(answer_out.get("cited_ids") or []))
    result.update({"ms_total": total, "cost": trace.cost})
    return result


def _checkpoint_and_answer(ds, question, ctx, s, trace, owner, asker, map_text, rules_text, pack, walked, query_id):
    items = list(pack["items"])
    by_n = {it["n"]: it for it in items}
    opened_text: list[str] = []
    more_items: list[dict] = []
    rounds = []
    extra_left = int(s.extra_recalls)
    shadow_future = None
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)

    def shadow(pack_text, pack_items):
        from django.db import connection
        try:
            facts = facts_of(ds["id"], [i["id"] for i in pack_items])
            ceiling = "normal"
            rank = {"normal": 0, "private": 1, "unlabelled": 1, "special": 2}
            for f in facts.values():
                if rank.get(f.get("sensitivity"), 1) > rank.get(ceiling, 0):
                    ceiling = f.get("sensitivity")
            return ai.decide("checkpoint_shadow", f"QUESTION: {question}\n\nPACK:\n{pack_text[:24000]}",
                             [ai.Noul("enough", "Is what is in this pack enough to answer the question?")],
                             ceiling=ceiling, settings=s, trace=trace, items=[i["id"] for i in pack_items], owner=owner)
        finally:
            connection.close()
    if ai.backend_for("checkpoint_shadow", s) != "off":
        shadow_future = pool.submit(shadow, pack["text"], items)
    final = {}
    for round_no in range(int(s.extra_recalls) + 2):
        must = extra_left <= 0
        ctx_line = ("\n\nCONTEXT ITEM:\n" + tx.compact("c", ctx, raw_chars=2000)) if ctx else ""
        text = (f"MAP:\n{map_text}\n\nRULES:\n{rules_text or 'none'}\n\nQUESTION (asked by {datasets.principal(people.name_of(asker))}): {question}{ctx_line}"
                f"\n\nPACK:\n{pack['text'] if round_no == 0 else _pack_text(items)}" +
                ("\n\nOPENED RAW ITEMS:\n" + "\n\n".join(opened_text) if opened_text else "") +
                ("\n\nYou must answer now." if must else ""))
        with trace.step("checkpoint" if round_no == 0 else f"checkpoint_{round_no + 1}",
                        "The checkpoint: answer, open raw items, or search again (D50)" if round_no == 0 else
                        f"Checkpoint again, round {round_no + 1} (D50)") as st:
            got = ai.generate(model=s.answer_model, name="answer", purpose="answer", trace=trace, owner=owner,
                              items=[i["id"] for i in items], schema=ANSWER_SCHEMA, max_tokens=3000,
                              instructions=ANSWER_INSTRUCTIONS.format(owner=people.owner_name_of(ds) or "the owner",
                                                                      raw=int(s.raw_open_max), extra=max(0, extra_left)),
                              text=text)
            action = got.get("action") if not must else "answer"
            st.data.update({"action": action, "model": got.get("_model"), "enough_why": got.get("enough_why"),
                            "open": got.get("open"), "query": got.get("query")})
            rounds.append({"action": action, "why": got.get("enough_why")})
            if action == "open" and got.get("open"):
                for n in (got.get("open") or [])[:int(s.raw_open_max)]:
                    it = by_n.get(int(n))
                    if not it:
                        continue
                    row = db.row("SELECT raw, title FROM synapse.item WHERE dataset_id = %s AND id = %s", (ds["id"], it["id"]))
                    raw = (row or {}).get("raw") or ""
                    cut = " ".join(raw.split()[:int(int(s.raw_open_tokens) / 1.3)])
                    opened_text.append(f"[{n}] {row.get('title') if row else ''}:\n{cut}")
                st.data["opened"] = [int(n) for n in (got.get("open") or [])[:int(s.raw_open_max)]]
                extra_left -= 1
                continue
            if action == "recall" and got.get("query"):
                extra_left -= 1
                q2 = got["query"]
                got_q2 = vectors.query(ds, q2, trace=trace, owner=owner)
                qvec2 = got_q2["vec"]
                found = search.hybrid(ds["id"], q2, qvec2, asker=asker, settings=s, depth=int(s.list_depth),
                                      exclude_ids=[i["id"] for i in items], model=got_q2["model"])
                fb = max((f["rrf"] for f in found["items"][:int(s.seeds)]), default=1.0) or 1.0
                w = Walk(ds, q2, qvec2, asker=asker, s=s, mode="live", trace=trace, owner=owner, qmodel=got_q2["model"],
                         budget=int(s.budget_live) * 2)
                w.gathered_ids = {i["id"] for i in items}
                w.seed([{"id": f["item_id"], "R": f["rrf"] / fb, "why": "search again"} for f in found["items"][:int(s.seeds)]])
                more = w.run()
                extra = build_pack(ds, more["gathered"], more["titles"], start=len(items) + 1, s=s, query=q2,
                                   qvec=qvec2, qmodel=got_q2["model"], asker=asker)
                items.extend(extra["items"])
                for it in extra["items"]:
                    by_n[it["n"]] = it
                st.data.update({"searched_again": q2, "added": len(extra["items"]), "stop": more["stop"],
                                "budget": int(s.budget_live) * 2})
                more_items.extend(extra["items"])
                more_text = "\n".join(i["lines"] for i in more_items)
                db.run("UPDATE synapse.query SET pack = jsonb_set(pack, '{more}', %s::jsonb) WHERE id = %s",
                       (Json({"items": more_items, "text": more_text, "tokens": tx.tokens(more_text)}), query_id))
                continue
            final = got
            break
    words = final.get("answer") or ""
    cited_n = set(int(n) for n in final.get("cited") or [])
    cited_n |= {int(n) for n in re.findall(r"\[(\d+)\]", words)}
    valid = {n for n in cited_n if n in by_n}
    invalid = sorted(cited_n - valid)
    with trace.step("answer", "The answer, its citations checked by code (D23)") as st:
        st.data.update({"answer": words, "cited": sorted(valid), "not_in_pack": invalid,
                        "used": [{"n": n, "title": by_n[n]["title"], "id": by_n[n]["id"]} for n in sorted(valid)],
                        "rounds": rounds})
    shadow_out = None
    if shadow_future is not None:
        with trace.step("checkpoint_shadow", "Checkpoint shadow: a decision model's guess, logged only (D72)") as st:
            try:
                got = shadow_future.result(timeout=60)
                a = (got.get("answers") or {}).get("enough") or {}
                did = rounds[0]["action"] if rounds else "answer"
                shadow_out = {"p_enough": a.get("p_yes"), "backend": got.get("backend"), "why": got.get("why"),
                              "fallback": got.get("fallback"), "main_model_did": did,
                              "would_act": (a.get("p_yes") is not None and
                                            ((1 - a["p_yes"]) >= float(s.checkpoint_act)))}
                st.data.update(shadow_out)
            except Exception as exc:  # noqa: BLE001
                st.data["error"] = str(exc)
    pool.shutdown(wait=False)
    return {"text": words, "cited": sorted(valid), "not_in_pack": invalid,
            "cited_ids": [by_n[n]["id"] for n in sorted(valid)],
            "used": [{"n": n, "title": by_n[n]["title"], "id": by_n[n]["id"]} for n in sorted(valid)],
            "rounds": rounds, "shadow": shadow_out, "pack_items": [{"n": i["n"], "id": i["id"], "title": i["title"],
                                                                    "path": i.get("path")} for i in items]}


def _pack_text(items: list[dict]) -> str:
    """The pack's lines, without the rules, which the answer is told under RULES."""
    return "\n".join(i["lines"] for i in items if i.get("kind") != "rule")


def why_item(ds: dict, query_id: str, item_id: str) -> dict:
    """Why an item was or was not in a question's pack: its path, or where it fell out."""
    q = db.row("SELECT * FROM synapse.query WHERE dataset_id = %s AND id = %s", (ds["id"], query_id))
    if not q:
        return {"ok": False, "why": "no such question"}
    from .ingest import get_in_scope
    item = get_in_scope(ds, item_id) or {}
    out = {"item": item.get("title"), "question": q["question"], "asker": q["asker"],
           "asker_name": people.name_of(q["asker"])}
    pack = q.get("pack") or {}
    inside = [i for i in (pack.get("items") or []) + ((pack.get("more") or {}).get("items") or []) if i["id"] == item_id]
    if inside:
        it = inside[0]
        out.update({"in_pack": True, "n": it["n"], "group": it.get("group"), "score": it.get("score"),
                    "route": it.get("route") or "a search seed", "cited": item_id in ((q.get("answer") or {}).get("cited_ids") or [])})
    else:
        out["in_pack"] = False
    readable = db.value(f"SELECT count(*) FROM synapse.item i WHERE i.dataset_id = ANY(synapse.scope(%s)) AND i.id = %s "
                        f"AND {search.readable_rule_sql('i')}",
                        (ds["id"], item_id, search.readers_for(q["asker"]), search.readers_for(q["asker"])))
    if not readable:
        rd = db.value("SELECT array_agg(principal) FROM synapse.reader WHERE item_id = %s", (item_id,)) or []
        out["reason"] = (f"{people.name_of(q['asker'])} may not read it: its readers are "
                         f"{', '.join(people.name_of(r) for r in rd)}"
                         f"{' and it is special' if item.get('sensitivity') == 'special' else ''}"
                         f"{' and no model has read it yet' if item.get('sensitivity') == 'unlabelled' else ''} (D38, D60).")
        return out
    if item.get("kind") == "rule":
        out["reason"] = ("Rules are never searched; they load whenever what they govern is in play, and are numbered "
                         "after the pack (D59).")
        return out
    frames = (q.get("walk") or {}).get("frames") or []
    seen_as = []
    for fr in frames:
        if fr.get("kind") == "seeds":
            for sd in fr.get("seeds") or []:
                if sd["id"] == item_id:
                    seen_as.append({"frame": 0, "as": "seed", "score": sd["score"]})
        for nb in fr.get("neighbours") or []:
            if nb["id"] == item_id:
                seen_as.append({"frame": fr["n"], "as": "neighbour", "score": nb["score"], "kept": nb["kept"],
                                "why": nb["why"], "R": nb["R"], "P": nb["P"], "H": nb["H"], "pi": nb["pi"],
                                "link": nb.get("link")})
    out["seen"] = seen_as
    if not out.get("in_pack"):
        stop = (q.get("walk") or {}).get("stop")
        if not seen_as:
            out["reason"] = ("Search did not rank it among the seeds and no link from anything the walk opened "
                             f"reached it before the walk stopped ({stop}).")
        else:
            last = seen_as[-1]
            out["reason"] = (f"The walk reached it (score {last['score']}) but "
                             + (f"did not queue it: {last['why']}." if not last.get("kept") else
                                f"stopped before taking it out of the queue: {stop}."))
    return out
