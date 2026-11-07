"""Hybrid search: words and meaning, in one round trip, fused by rank (D36).

Every list costs what its answer costs, never what the dataset holds (Petar, 3
October 2026: ready for 10,000 items now and 100,000 later).

- **Words**: PostgreSQL full text over the passages, in English and Bulgarian
  word forms and plain lower case, with the question also written in the other
  alphabet (Ivaylo and Ивайло). The question's lexemes are looked up in
  `synapse.df` (how many passages hold each one), and only the rarest of
  them, as many as fit `words_cap` passages between them, draw the candidates
  from the GIN index; when even the rarest word is that common, its most recent
  passages are taken (time-led index). Those candidates alone are ranked: by
  every question word they hold, weighted by its rarity (BM25's idf), plus
  `ts_rank` for how often, and only the short list gets a point for a title
  that looks like the question (letter groups, for misspellings). The words
  are OR'd, because a question is not a list of words that must all appear.
  That is the 'capped' words list; Tune > Search > words_backend chooses it,
  'bm25' (BM25 in PostgreSQL, which also finds passages holding most of the
  question's words together before falling back to the most recent ones) or
  'pg_search' (ParadeDB's BM25 index, where PostgreSQL loads it): card 1125's
  first change, measured by `synapse_bench`.
- **Meaning**: the nearest passages to the question's vector (pgvector HNSW,
  built with m 32 and ef_construction 128 and searched 100 deep since card
  1125's measurements, with iterative scans on so a filter cannot starve it, D38), among the
  vectors of the model the question was embedded with, and no other: two
  models' numbers mean nothing to each other, so a passage still holding
  another model's vector (`vectors.py`) is found by its words only.
- **Permissions in the scan** (D38): each passage carries its item's reader set
  (`can_read`, kept by triggers from `synapse.reader`, migration 0071), so the
  filter is a column of the row being scanned, never a lookup per candidate.
  Each result is then checked once, by the rule itself (`readable_rule_sql`)
  and `synapse.reaches` (a person of the owner's people set counts only when
  this dataset links to it), and anything that fails is dropped and counted.
- **Recent first** (Tune, off unless it measures well): both lists over the
  last `recent_days` days first, and the older items only when that finds too
  little, merged by score.
- **Fusion**: each list gives 1 / (k + rank), k = 60 to start.

Rules are never searched (D59); they load with what they govern.
"""
from __future__ import annotations

import math
import re
import time

from . import db, text as tx

NEVER_SEARCHED = ["rule"]
NO_IDS = ["00000000-0000-0000-0000-000000000000"]


def readable_sql(alias: str = "i") -> str:
    """Readable by the asker, by the item's stored reader set (migration 0071): one parameter, the
    asker's principals (`readers_for`).

    `can_read` is the rule of `readable_rule_sql` kept as a value: the item's readers, and while
    it is special or unlabelled (no model has read it yet, so it may be special) only its owner.
    """
    return f"({alias}.can_read && %s::text[])"


def readable_rule_sql(alias: str = "i") -> str:
    """The rule itself, read from `synapse.reader` (D38, D60); for checking results, once each.

    Takes the asker's principals twice: once for the readers, once for the
    owner of a special item, which only its owner's questions may reach.
    An asker limited to some of the owner's silos asks with sided principals
    (`<silo>:<id>`, `rouh/silos.py`): they reach a reader only on an item in one
    of those silos (`synapse.unscoped`), and never the owner, so nothing special
    or unlabelled either.
    """
    return (f"(EXISTS (SELECT 1 FROM synapse.reader r WHERE r.dataset_id = {alias}.dataset_id "
            f"AND r.item_id = {alias}.id AND r.principal = ANY(synapse.unscoped(%s::text[], {alias}.silos))) "
            f"AND ({alias}.sensitivity NOT IN ('special', 'unlabelled') OR {alias}.owner = ANY(%s)))")


def readers_for(asker: str) -> list[str]:
    """Whom an asker reads as: themselves and everyone, each under every silo of theirs when the asker is
    limited to some (`in:<keys>:<id>`, `rouh/silos.py`), which an item carries only for the silos it is in
    (migrations 0133 and 0134)."""
    from .. import silos

    return silos.principals(asker)


def parse_vec(value) -> list[float] | None:
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        return [float(x) for x in value]
    s = str(value).strip().strip("[]")
    return [float(x) for x in s.split(",")] if s else None


#: The dataset's own model, for a vector whose model the caller did not say.
LIVE_MODEL = "(SELECT d.vec_model FROM synapse.dataset d WHERE d.id = %s)"


def _model_sql(model: str | None) -> tuple[str, list]:
    """`= <the model>`, the one said or else the dataset's own, with its parameter."""
    return ("= %s", [model]) if model else ("= " + LIVE_MODEL, [])


def scope(ds_id: str) -> list[str]:
    """The datasets an item of this one may be read from: itself and its owner's people set."""
    return [str(x) for x in (db.value("SELECT synapse.scope(%s)", (ds_id,)) or [ds_id])]


def tsquery_term(lexeme: str) -> str:
    """One lexeme as tsquery text, quoted: it is matched as it is, with no dictionary."""
    return "'" + lexeme.replace("\\", "\\\\").replace("'", "''") + "'"


def idf(df: int, n: int) -> float:
    """BM25's inverse document frequency."""
    return math.log(1 + (max(n, df) - df + 0.5) / (df + 0.5))


def query_terms(scope_ids: list[str], query: str) -> tuple[list[dict], int]:
    """The question's lexemes in the three configurations, each with how many passages hold it."""
    other = tx.other_alphabet(query)
    words_query = (query + " " + other).strip()
    got = db.rows(
        "WITH v AS (SELECT to_tsvector('english', %s) || to_tsvector('synapse.bg', %s) "
        "                  || to_tsvector('simple', %s) AS v), "
        "lx AS MATERIALIZED (SELECT DISTINCT u.lexeme FROM v, unnest(v.v) u), "
        + COUNTS.format(lexemes="SELECT lexeme FROM lx") +
        "SELECT lx.lexeme, coalesce(c.df, 0) AS df FROM lx LEFT JOIN counts c ON c.lexeme = lx.lexeme",
        (words_query, query, words_query, scope_ids, scope_ids))
    return got, passages_in(scope_ids)


def passages_in(scope_ids: list[str]) -> int:
    return int(db.value("SELECT synapse.df(%s::uuid[], '')", (scope_ids,)) or 0)


def rare_terms(ds_id: str, item_id: str, scope_ids: list[str], n: int) -> list[dict]:
    """An item's `n` rarest words: the lexemes of its own passages that the fewest other passages
    hold, and at least one does. Read from its first two passages and its X-ray, so a long document
    costs what a short email does. A word's forms count once (agree, agreed: their English stem,
    which every passage holds too). Numbers, English stop words and words under three letters are
    left out."""
    return db.rows(
        "WITH mine AS MATERIALIZED (SELECT u.lexeme, count(*) AS own FROM synapse.passage p, unnest(p.words) u "
        "              WHERE p.dataset_id = %s AND p.item_id = %s AND (p.from_xray OR p.seq <= 2) "
        "              AND length(u.lexeme) >= 3 AND u.lexeme !~ '^[0-9.,:/-]+$' GROUP BY u.lexeme), "
        "stems AS MATERIALIZED (SELECT DISTINCT x.stem FROM mine m, LATERAL (SELECT min(s.lexeme) AS stem "
        "              FROM unnest(to_tsvector('english', m.lexeme)) s) x "
        "              WHERE x.stem IS NOT NULL AND length(x.stem) >= 3), "
        + COUNTS.format(lexemes="SELECT stem FROM stems") +
        "SELECT c.lexeme, c.df - m.own::int AS df FROM counts c JOIN mine m ON m.lexeme = c.lexeme "
        "WHERE c.df - m.own >= 1 ORDER BY 2, 1 LIMIT %s",
        (ds_id, item_id, scope_ids, scope_ids, int(n)))


#: How many passages hold each of some lexemes, in one go: two index scans over (scope, lexeme), one
#: on the folded counts and one on what has not been folded yet. Takes the scope twice.
COUNTS = ("counts AS (SELECT lexeme, sum(df)::int AS df FROM ("
          " SELECT t.lexeme, t.df FROM synapse.term_df t WHERE t.scope_id = ANY(%s::uuid[]) "
          "   AND t.lexeme = ANY(ARRAY({lexemes})) "
          " UNION ALL SELECT d.lexeme, d.n FROM synapse.term_delta d WHERE d.scope_id = ANY(%s::uuid[]) "
          "   AND d.lexeme = ANY(ARRAY({lexemes}))) x GROUP BY lexeme) ")


def pick_terms(terms: list[dict], cap: int, most: int) -> tuple[list[dict], bool]:
    """The rarest terms whose passages, together, fit under `cap`; at least the rarest one.
    Says too whether even that one is commoner than the cap."""
    ordered = sorted((t for t in terms if int(t["df"]) > 0), key=lambda t: (int(t["df"]), t["lexeme"]))
    picked, total = [], 0
    for t in ordered[:most]:
        if picked and total + int(t["df"]) > cap:
            break
        picked.append(t)
        total += int(t["df"])
    return picked, bool(picked) and int(picked[0]["df"]) > cap


def _filters(alias: str, *, scope_ids, readers, kinds_out, only, excluded, since, before) -> tuple[str, list]:
    """The conditions every list shares, all on the passage row itself."""
    sql = (f"{alias}.dataset_id = ANY(%s::uuid[]) AND {alias}.can_read && %s::text[] "
           f"AND NOT ({alias}.kind = ANY(%s::text[])) "
           f"AND (cardinality(%s::text[]) = 0 OR {alias}.kind = ANY(%s::text[])) "
           f"AND NOT ({alias}.item_id = ANY(%s::uuid[]))")
    params = [scope_ids, readers, kinds_out, only, only, excluded]
    if since is not None:
        sql += f" AND {alias}.said_at >= %s"
        params.append(since)
    if before is not None:
        sql += f" AND ({alias}.said_at < %s OR {alias}.said_at IS NULL)"
        params.append(before)
    return sql, params


#: How the words list finds and ranks its passages (Tune > Search, card 1125 change 1, 4 October 2026).
WORDS_BACKENDS = ("capped", "bm25", "pg_search")


def words_list(query: str, terms: list[dict], n_passages: int, *, keep: int, cap: int, most: int,
               title_query: str | None = None, backend: str = "capped", k1: float = 1.2, b: float = 0.75,
               **where) -> tuple[list[dict], dict]:
    """The words list, by `backend`: 'capped' (the rarest terms' short lists, scored by idf and
    ts_rank, as on 4 October 2026), 'bm25' (BM25 in PostgreSQL, see `_words_bm25`) or 'pg_search'
    (ParadeDB's BM25 index, where it is built; otherwise 'bm25', and it says so)."""
    if backend == "pg_search":
        if pg_search_ready():
            return _words_pg_search(query, terms, n_passages, keep=keep, title_query=title_query, **where)
        got, info = _words_bm25(query, terms, n_passages, keep=keep, cap=cap, most=most, title_query=title_query,
                                k1=k1, b=b, **where)
        info["backend_note"] = "pg_search is not loaded in this database, so BM25 in PostgreSQL ranked instead"
        return got, info
    if backend == "bm25":
        return _words_bm25(query, terms, n_passages, keep=keep, cap=cap, most=most, title_query=title_query,
                           k1=k1, b=b, **where)
    return _words_capped(query, terms, n_passages, keep=keep, cap=cap, most=most, title_query=title_query, **where)


def _words_capped(query: str, terms: list[dict], n_passages: int, *, keep: int, cap: int, most: int,
                  title_query: str | None = None, **where) -> tuple[list[dict], dict]:
    """Candidates from the rarest terms' short lists, then ranked (see the top); 4 October 2026."""
    known = [t for t in terms if int(t["df"]) > 0]
    picked, common = pick_terms(known, cap, most)
    info = {"terms": len(terms), "known": len(known), "picked": [t["lexeme"] for t in picked],
            "picked_df": sum(int(t["df"]) for t in picked), "common": common, "cap": cap}
    if not picked:
        return [], info
    cond, params = _filters("p", **where)
    pick_q = " | ".join(tsquery_term(t["lexeme"]) for t in picked)
    all_q = " | ".join(tsquery_term(t["lexeme"]) for t in known)
    weights = [round(idf(int(t["df"]), n_passages), 5) for t in known]
    order = "ORDER BY p.said_at DESC NULLS LAST" if common else ""
    sql = f"""
    WITH cand AS (
      SELECT p.item_id, p.words FROM synapse.passage p
      WHERE p.words @@ %s::tsquery AND {cond}
      {order} LIMIT %s
    ),
    scored AS (
      SELECT c.item_id, max((SELECT coalesce(sum(t.w), 0) FROM unnest(%s::tsquery[], %s::float8[]) AS t(q, w)
                             WHERE c.words @@ t.q) + ts_rank(c.words, %s::tsquery)) AS score
      FROM cand c GROUP BY c.item_id ORDER BY score DESC LIMIT %s
    )
    SELECT s.item_id, s.score + 0.2 * word_similarity(%s, i.title) AS score
    FROM scored s JOIN synapse.item i ON i.id = s.item_id
    """
    got = db.rows(sql, [pick_q, *params, int(cap), [tsquery_term(t["lexeme"]) for t in known], weights, all_q,
                        int(keep), title_query if title_query is not None else query])
    got.sort(key=lambda r: -float(r["score"]))
    info["candidates_capped"] = common
    info["backend"] = "capped"
    return got, info


_avgdl_seen: dict[tuple, tuple[float, float]] = {}


def avgdl(scope_ids: list[str]) -> float:
    """The average passage length BM25 normalises by: distinct words per passage over the latest
    5,000 passages of the scope, worked out again every ten minutes."""
    key = tuple(sorted(scope_ids))
    seen = _avgdl_seen.get(key)
    if seen and time.time() - seen[1] < 600:
        return seen[0]
    got = float(db.value("SELECT avg(length(words)) FROM (SELECT words FROM synapse.passage WHERE "
                         "dataset_id = ANY(%s::uuid[]) ORDER BY id DESC LIMIT 5000) x", (scope_ids,)) or 0) or 100.0
    _avgdl_seen[key] = (got, time.time())
    return got


#: Words that meet in a passage: at most this many of the question's commoner words are combined.
TOGETHER_MOST = 6


def _together(rest: list[dict]) -> tuple[str, int, list[str]]:
    """A tsquery for passages holding most of `rest` together: every group of all but one of them
    (or both, when there are two), as a GIN index answers an AND by intersecting short lists."""
    from itertools import combinations

    group = [t["lexeme"] for t in rest[:TOGETHER_MOST]]
    need = len(group) if len(group) <= 2 else len(group) - 1
    parts = ["(" + " & ".join(tsquery_term(w) for w in combo) + ")" for combo in combinations(group, need)]
    return " | ".join(parts), need, group


def _words_bm25(query: str, terms: list[dict], n_passages: int, *, keep: int, cap: int, most: int,
                title_query: str | None = None, k1: float = 1.2, b: float = 0.75, **where) -> tuple[list[dict], dict]:
    """BM25 in PostgreSQL, its work bounded by the cap and never by how often a word is used.

    Candidates come three ways, in order, each from the GIN index and at most `cap` passages:
    1. every passage holding one of the rarest terms, as many terms as fit `cap` between them (all
       of them: nothing is cut, so these are ranked exactly);
    2. when even the rarest term is commoner than the cap, which is where the capped list gives up:
       passages holding most of the question's words together (all but one of the rarest six, each
       in at most a quarter of the passages), which the index answers by intersecting their lists,
       so an old item that alone holds four ordinary words of the question is found however common
       each word is;
    3. only when those find fewer than the list needs: the rarest term's most recent passages, as before.
    Then each candidate is scored by BM25 over every question word it holds: the word's rarity
    (idf), how often the passage uses it, saturating (k1), against the passage's length (b), so a
    short passage about a word beats a long one that mentions it once, and a common word counts
    for almost nothing. A title that looks like the question adds as before."""
    known = sorted((t for t in terms if int(t["df"]) > 0), key=lambda t: (int(t["df"]), t["lexeme"]))[:most]
    picked, common = pick_terms(known, cap, most)
    info = {"backend": "bm25", "terms": len(terms), "known": len(known), "picked": [t["lexeme"] for t in picked],
            "picked_df": sum(int(t["df"]) for t in picked), "common": common, "cap": cap, "k1": k1, "b": b}
    if not known:
        return [], info
    cond, params = _filters("p", **where)
    sources, sparams = [], []
    if picked and not common:
        sources.append(f"(SELECT p.id, p.item_id, p.words, 1 AS way FROM synapse.passage p "
                       f"WHERE p.words @@ %s::tsquery AND {cond} LIMIT %s)")
        sparams += [" | ".join(tsquery_term(t["lexeme"]) for t in picked), *params, int(cap)]
    # Only where the capped list gives up (even the rarest word is commoner than the cap), and only
    # words that still say something: in at most a quarter of the passages.
    together = [t for t in known if int(t["df"]) <= max(1, n_passages) / 4] if common else []
    if len(together) >= 2:
        tq, need, group = _together(together)
        info["together"] = {"words": group, "need": need}
        sources.append(f"(SELECT p.id, p.item_id, p.words, 2 AS way FROM synapse.passage p "
                       f"WHERE p.words @@ %s::tsquery AND {cond} LIMIT %s)")
        sparams += [tq, *params, int(cap)]
    lexemes = [t["lexeme"] for t in known]
    weights = [round(idf(int(t["df"]), n_passages), 5) for t in known]
    dl = avgdl(where["scope_ids"])
    info["avgdl"] = round(dl, 1)

    def ranked(src_sql: str, src_params: list) -> list[dict]:
        sql = f"""
        WITH raw AS ({src_sql}),
        cand AS (SELECT DISTINCT ON (id) id, item_id, words, way FROM raw ORDER BY id, way),
        scored AS (
          SELECT c.item_id, min(c.way) AS way, max(bm.s) AS score FROM cand c CROSS JOIN LATERAL (
            SELECT coalesce(sum(w.w[array_position(w.lx, u.lexeme)]
                     * (coalesce(array_length(u.positions, 1), 1) * (%s + 1))
                     / (coalesce(array_length(u.positions, 1), 1) + %s * (1 - %s + %s * length(c.words) / %s))), 0) AS s
            FROM unnest(ts_filter(setweight(c.words, 'A', %s::text[]), '{{a}}')) u,
                 (SELECT %s::text[] AS lx, %s::float8[] AS w) w) bm
          GROUP BY c.item_id ORDER BY score DESC LIMIT %s
        )
        SELECT s.item_id, s.way, s.score + 0.2 * word_similarity(%s, i.title) AS score
        FROM scored s JOIN synapse.item i ON i.id = s.item_id
        """
        return db.rows(sql, [*src_params, float(k1), float(k1), float(b), float(b), float(dl), lexemes, lexemes,
                             weights, int(keep), title_query if title_query is not None else query])

    got = ranked(" UNION ALL ".join(sources), sparams) if sources else []
    if len(got) < keep and common:
        # Too little from the words together, and even the rarest is commoner than the cap: its most
        # recent passages, as the capped list takes them.
        first = known[0]
        more = ranked(f"SELECT p.id, p.item_id, p.words, 3 AS way FROM synapse.passage p WHERE p.words @@ %s::tsquery "
                      f"AND {cond} ORDER BY p.said_at DESC NULLS LAST LIMIT %s",
                      [tsquery_term(first["lexeme"]), *params, int(cap)])
        seen = {r["item_id"] for r in got}
        got += [r for r in more if r["item_id"] not in seen]
        info["recent_of"] = first["lexeme"]
    got.sort(key=lambda r: -float(r["score"]))
    got = got[:keep]
    info["candidates_capped"] = common
    info["found_by"] = {"by the rarest words": sum(1 for r in got if r["way"] == 1),
                        "by most of the words together": sum(1 for r in got if r["way"] == 2),
                        "by being the most recent with the rarest word": sum(1 for r in got if r["way"] == 3)}
    return [{"item_id": r["item_id"], "score": r["score"]} for r in got], info


_pg_search_seen: list = []


def pg_search_ready() -> bool:
    """Whether ParadeDB's BM25 index over the passages is built here (it needs pg_search loaded
    with shared_preload_libraries, which Rouh's own PostgreSQL does not have)."""
    if not _pg_search_seen or time.time() - _pg_search_seen[1] > 60:
        ok = bool(db.value("SELECT to_regclass('synapse.passage_bm25') IS NOT NULL"))
        _pg_search_seen[:] = [ok, time.time()]
    return bool(_pg_search_seen[0])


def _pg_query(lexemes: list[str]) -> str:
    return " OR ".join('"' + w.replace("\\", "\\\\").replace('"', '\\"') + '"' for w in lexemes)


def _pg_filters(alias: str, *, scope_ids, readers, kinds_out, only, excluded, since, before) -> tuple[str, list]:
    """`_filters` written so every condition is answered inside the pg_search index: a condition it
    cannot push down is checked against the table for every match instead, measured at ten times
    the time (card 1125, 4 October 2026)."""
    sql = (f"{alias}.dataset_id = ANY(%s::uuid[]) AND {alias}.can_read @@@ pdb.term_set(%s::text[]) "
           f"AND NOT ({alias}.kind @@@ pdb.term_set(%s::text[])) AND NOT ({alias}.item_id = ANY(%s::uuid[]))")
    params = [scope_ids, readers, kinds_out, excluded]
    if only:
        sql += f" AND {alias}.kind @@@ pdb.term_set(%s::text[])"
        params.append(list(only))
    if since is not None:
        sql += f" AND {alias}.said_at >= %s"
        params.append(since)
    if before is not None:
        sql += f" AND ({alias}.said_at < %s OR {alias}.said_at IS NULL)"
        params.append(before)
    return sql, params


def _words_pg_search(query: str, terms: list[dict], n_passages: int, *, keep: int, title_query: str | None = None,
                     **where) -> tuple[list[dict], dict]:
    """ParadeDB's BM25 (Tantivy): every question word, top `keep` passages by block-max WAND,
    which skips blocks that cannot reach the top, so the work follows `keep`, not the matches.
    Indexed over the same word forms the GIN index holds (`synapse.lexeme_text`), so English,
    Bulgarian and plain forms match as they do everywhere else."""
    known = [t["lexeme"] for t in terms if int(t["df"]) > 0]
    info = {"backend": "pg_search", "terms": len(terms), "known": len(known), "picked": known,
            "picked_df": sum(int(t["df"]) for t in terms if int(t["df"]) > 0), "common": False}
    if not known:
        return [], info
    cond, params = _pg_filters("p", **where)
    got = db.rows(
        f"WITH top AS (SELECT p.item_id, pdb.score(p.id) AS s FROM synapse.passage p WHERE p.lexemes @@@ %s AND {cond} "
        f"ORDER BY pdb.score(p.id) DESC LIMIT %s), "
        "best AS (SELECT item_id, max(s) AS s FROM top GROUP BY item_id) "
        "SELECT b.item_id, b.s + 0.2 * word_similarity(%s, i.title) AS score FROM best b "
        "JOIN synapse.item i ON i.id = b.item_id ORDER BY 2 DESC LIMIT %s",
        [_pg_query(known), *params, int(keep) * 2, title_query if title_query is not None else query, int(keep)])
    return got, info


def meaning_list(v: str, model_is: str, model_params: list, *, keep: int, **where) -> list[dict]:
    """The meaning list: the nearest passages, best cosine per item."""
    cond, params = _filters("p", **where)
    got = db.rows(
        f"SELECT p.item_id, 1 - (p.vec <=> %s::halfvec) AS cos FROM synapse.passage p "
        f"WHERE {cond} AND p.vec IS NOT NULL AND p.embed_model {model_is} "
        f"ORDER BY p.vec <=> %s::halfvec LIMIT %s",
        [v, *params, *model_params, v, int(keep) * 3])
    best: dict[str, float] = {}
    for r in got:
        best[r["item_id"]] = max(best.get(r["item_id"], -2.0), float(r["cos"]))
    return [{"item_id": k, "score": c} for k, c in sorted(best.items(), key=lambda kv: -kv[1])[:int(keep)]]


def check_results(ds_id: str, ids, readers: list[str]) -> set[str]:
    """The results the asker may read and this dataset reaches, by the rule itself: once each."""
    ids = list({str(i) for i in ids})
    if not ids:
        return set()
    got = db.rows(
        "SELECT i.id FROM synapse.item i WHERE i.id = ANY(%s::uuid[]) AND i.dataset_id = ANY(synapse.scope(%s)) "
        "AND i.deleted_at IS NULL AND synapse.reaches(%s, i.dataset_id, i.id) AND " + readable_rule_sql("i"),
        (ids, ds_id, ds_id, readers, readers))
    return {r["id"] for r in got}


def fuse(lists: dict[str, list[dict]], k: float) -> list[dict]:
    fused: dict[str, dict] = {}
    for name, lst in lists.items():
        for rank, r in enumerate(lst, start=1):
            f = fused.setdefault(r["item_id"], {"item_id": r["item_id"], "rrf": 0.0, "ranks": {}, "scores": {}})
            f["rrf"] += 1.0 / (k + rank)
            f["ranks"][name] = rank
            f["scores"][name] = round(float(r["score"]), 4)
    return sorted(fused.values(), key=lambda f: -f["rrf"])


def _merge(first: list[dict], more: list[dict], keep: int) -> list[dict]:
    seen = {r["item_id"] for r in first}
    both = first + [r for r in more if r["item_id"] not in seen]
    return sorted(both, key=lambda r: -float(r["score"]))[:keep]


def hybrid(ds_id: str, query: str, qvec, *, asker: str, settings, exclude_kinds=(),
           exclude_ids=(), only_kinds=(), depth: int | None = None, model: str | None = None,
           terms: list[dict] | None = None, meaning: bool = True, cap: int | None = None) -> dict:
    """Both lists, fused. Returns `{"items": [...], "words": n, "meaning": n, "ms": n, ...}`.

    `model` is the model `qvec` was made with; nothing said means the
    dataset's own (`synapse.dataset.vec_model`). `terms` are lexemes with their
    counts to search with instead of the question's own (link candidates pass an
    item's rarest words)."""
    depth = int(depth or settings.get("list_depth", 60))
    k = float(settings.get("rrf_k", 60))
    cap = int(cap or settings.get("words_cap", 2000))
    most = int(settings.get("words_terms", 16))
    readers = readers_for(asker)
    began = time.time()
    scope_ids = scope(ds_id)
    if terms is None:
        terms, n_passages = query_terms(scope_ids, query)
        words_query = (query + " " + tx.other_alphabet(query)).strip()
    else:
        n_passages = passages_in(scope_ids)
        words_query = " ".join(t["lexeme"] for t in terms)
    where = {"scope_ids": scope_ids, "readers": readers,
             "kinds_out": list(NEVER_SEARCHED) + list(exclude_kinds), "only": list(only_kinds),
             "excluded": [str(x) for x in exclude_ids] or NO_IDS}
    v = db.vec(qvec) if (qvec is not None and meaning) else None
    model_is, model_params = _model_sql(model)
    model_params = model_params or [ds_id]
    keep = depth * 2  # the words list is cheap to keep long; a few may fail the check of each result
    ef_search = None
    if v is not None:
        db.run("SET hnsw.iterative_scan = 'relaxed_order'")
        # How many neighbours the HNSW search keeps while it walks the graph (pgvector's ef_search,
        # 40 by default); found at 1,000,000 fictional items to miss the nearest passage, 4 October 2026.
        ef_search = max(10, min(1000, int(settings.get('hnsw_ef_search', 100))))
        db.run(f"SET hnsw.ef_search = {ef_search}")

    backend = str(settings.get("words_backend", "pg_search"))
    k1, b = float(settings.get("bm25_k1", 1.2)), float(settings.get("bm25_b", 0.75))

    def lists(since=None, before=None):
        w, winfo = words_list(query, terms, n_passages, keep=keep, cap=cap, most=most, backend=backend, k1=k1, b=b,
                              **where, since=since, before=before)
        m = meaning_list(v, model_is, model_params, keep=depth + 10, **where, since=since, before=before) \
            if v is not None else []
        return w, m, winfo

    recent = None
    if settings.get("recent_first", False):
        days = int(settings.get("recent_days", 90))
        since = db.value("SELECT now() - make_interval(days => %s)", (days,))
        words, near, winfo = lists(since=since)
        found = len({r["item_id"] for r in words} | {r["item_id"] for r in near})
        best_cos = max((r["score"] for r in near), default=None)
        weak = found < int(settings.get("recent_enough", 20)) or (
            best_cos is not None and best_cos < float(settings.get("recent_cosine", 0.5)))
        recent = {"days": days, "found": found, "best_cosine": round(best_cos, 4) if best_cos is not None else None,
                  "weak": weak, "older_searched": weak}
        if weak:
            w2, m2, winfo2 = lists(before=since)
            words, near = _merge(words, w2, keep), _merge(near, m2, depth + 10)
            recent["older_found"] = len({r["item_id"] for r in w2} | {r["item_id"] for r in m2})
    else:
        words, near, winfo = lists()
    ok = check_results(ds_id, [r["item_id"] for r in words + near], readers)
    dropped = len({r["item_id"] for r in words + near} - ok)
    words = [r for r in words if r["item_id"] in ok][:depth]
    near = [r for r in near if r["item_id"] in ok][:depth]
    ms = int((time.time() - began) * 1000)
    items = fuse({"words": words, "meaning": near}, k)
    return {"items": items, "words": len(words), "meaning": len(near), "ms": ms,
            "query_words": words_query, "terms": winfo, "checked": len(ok) + dropped, "dropped": dropped,
            "recent": recent, "ef_search": ef_search, "lexemes": terms, "n_passages": n_passages}


def add_list(fused_items: list[dict], ranking: list[str], name: str, k: float) -> list[dict]:
    """A third list, fused in the same way (D70: the decision model's ranking)."""
    by = {f["item_id"]: f for f in fused_items}
    for rank, item_id in enumerate(ranking, start=1):
        f = by.get(item_id)
        if f is None:
            continue
        f["rrf"] += 1.0 / (k + rank)
        f["ranks"][name] = rank
    return sorted(by.values(), key=lambda f: -f["rrf"])


def items_by_id(ds_id: str, ids) -> dict[str, dict]:
    ids = [str(i) for i in ids if i]
    if not ids:
        return {}
    got = db.rows("SELECT id, kind, title, body, raw, said_at, tier, sensitivity, meta, xray, owner, "
                  "deleted_at, status, source_key FROM synapse.item "
                  "WHERE dataset_id = ANY(synapse.scope(%s)) AND id = ANY(%s::uuid[])", (ds_id, ids))
    return {r["id"]: r for r in got}


def item_vectors(ds_id: str, ids) -> dict[str, list[float]]:
    """One vector per item, in the dataset's own model: its X-ray passage's,
    or its first passage's."""
    ids = [str(i) for i in ids if i]
    if not ids:
        return {}
    got = db.rows("SELECT DISTINCT ON (item_id) item_id, vec::text AS vec FROM synapse.passage "
                  "WHERE dataset_id = ANY(synapse.scope(%s)) AND item_id = ANY(%s::uuid[]) AND vec IS NOT NULL "
                  f"AND embed_model = {LIVE_MODEL} "
                  "ORDER BY item_id, from_xray DESC, part, seq", (ds_id, ids, ds_id))
    return {r["item_id"]: parse_vec(r["vec"]) for r in got}


def cosines(ds_id: str, ids, qvec, model: str | None = None) -> dict[str, float]:
    """Each item's best cosine to the question: its X-ray passage or its
    passages, among the vectors of the question's model."""
    ids = [str(i) for i in ids if i]
    if not ids or qvec is None:
        return {}
    model_is, model_params = _model_sql(model)
    got = db.rows("SELECT item_id, max(1 - (vec <=> %s::halfvec)) AS cos FROM synapse.passage "
                  "WHERE dataset_id = ANY(synapse.scope(%s)) AND item_id = ANY(%s::uuid[]) AND vec IS NOT NULL "
                  f"AND embed_model {model_is} "
                  "GROUP BY item_id", (db.vec(qvec), ds_id, ids, *(model_params or [ds_id])))
    return {r["item_id"]: float(r["cos"]) for r in got}


def rare_lexemes(terms: list[dict], n_passages: int, most_df: int) -> list[dict]:
    """The question's rare lexemes, held by at least one passage and at most `most_df`, each with its weight:
    its idf over the idf of a lexeme only one passage holds, so the rarest weighs 1 (attempt 38)."""
    top = idf(1, max(1, n_passages)) or 1.0
    return [{"lexeme": t["lexeme"], "df": int(t["df"]), "weight": round(idf(int(t["df"]), n_passages) / top, 4)}
            for t in terms or [] if 0 < int(t["df"]) <= most_df]


def words_held(ds_id: str, ids, lexemes: list[str]) -> dict[str, list[str]]:
    """Which of these lexemes each item's passages hold, matched as they are, with no dictionary."""
    ids = [str(i) for i in ids if i]
    if not ids or not lexemes:
        return {}
    got = db.rows("SELECT p.item_id, array_agg(DISTINCT t.lexeme) AS held FROM synapse.passage p "
                  "JOIN unnest(%s::text[], %s::tsquery[]) AS t(lexeme, q) ON p.words @@ t.q "
                  "WHERE p.dataset_id = ANY(synapse.scope(%s)) AND p.item_id = ANY(%s::uuid[]) GROUP BY p.item_id",
                  (list(lexemes), [tsquery_term(x) for x in lexemes], ds_id, ids))
    return {r["item_id"]: list(r["held"] or []) for r in got}


def _like(word: str) -> str:
    return "%" + word.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


#: How many passages may hold the word a find starts from before it is too common to start from, by Synapse's
#: count of passages holding each word (`term_df`): then the newest `WALK_FIRST` items are read first.
COMMON_DF = 3000
#: The newest items a find of only common words reads first; it reads every item holding its rarest word
#: only when fewer than it was asked for are among them.
WALK_FIRST = 1500


def _indexed(word: str) -> bool:
    """Whether the trigram indexes can look this word up: three letters or digits in a row. "🧩" or "AI" cannot,
    and is only ever checked on items another word found."""
    return re.search(r"[^\W_]{3}", word) is not None


def _commonness(ds_id: str, words: list[str]) -> list[int | None]:
    """About how many passages hold each word, from the counts the search keeps (`term_df`): the least of its
    words' counts in plain lower case, 0 for a word no passage holds as a whole word, None for one with no words."""
    scope_ids = scope(ds_id)
    got = db.rows(
        "WITH w AS (SELECT * FROM unnest(%s::int[], %s::text[]) AS w(n, word)), "
        "lx AS MATERIALIZED (SELECT w.n, u.lexeme FROM w, unnest(to_tsvector('simple', w.word)) u), "
        + COUNTS.format(lexemes="SELECT lexeme FROM lx") +
        "SELECT lx.n, min(coalesce(c.df, 0)) AS df FROM lx LEFT JOIN counts c ON c.lexeme = lx.lexeme GROUP BY lx.n",
        (list(range(len(words))), list(words), scope_ids, scope_ids))
    by = {int(r["n"]): int(r["df"]) for r in got}
    return [by.get(n) for n in range(len(words))]


def _holds(alias: str, ds_id: str, word: str) -> tuple[str, list]:
    """The item holds the word in its title, a passage of its own text, or, a rule, its text. The passage is a
    sub-select of one row, so it is read for this item alone and never turned into a scan of every passage."""
    w = _like(word)
    return (f"({alias}.title ILIKE %s OR (SELECT true FROM synapse.passage p WHERE p.dataset_id = %s "
            f"AND p.item_id = {alias}.id AND NOT p.from_xray AND p.text ILIKE %s LIMIT 1) "
            f"OR ({alias}.kind = 'rule' AND {alias}.body ILIKE %s))", [w, ds_id, w, w])


def _holding_any(ds_id: str, word: str) -> tuple[str, list]:
    """Every item holding the word, through the trigram indexes on titles and passages; a rule by its text."""
    w = _like(word)
    return ("SELECT t.id FROM synapse.item t WHERE t.dataset_id = %s AND t.title ILIKE %s "
            "UNION SELECT p.item_id FROM synapse.passage p WHERE p.dataset_id = %s AND NOT p.from_xray "
            "AND p.text ILIKE %s "
            "UNION SELECT r.id FROM synapse.item r WHERE r.dataset_id = %s AND r.kind = 'rule' "
            "AND r.deleted_at IS NULL AND r.body ILIKE %s", [ds_id, w, ds_id, w, ds_id, w])


def containing(ds_id: str, words, *, readers: list[str] | None = None, limit: int = 30,
               kinds_out=(), nearest: bool = False, silo_first: str = "") -> list[dict]:
    """Items that hold every one of these words in their title or their text, anywhere and in any order,
    as written (no stemming: "offer" finds "offers"), newest first: `synapse_find`, and automatic recall's
    look-ups by name (`autorecall`).

    No words is no items, never the newest of everything: on 6 October 2026 a find whose words never reached
    here listed thirty public holidays for "BLUF offer". `readers`, when given, keeps it to what that asker
    may read (`readers_for`); with none it is the dataset's owner looking at their own dataset, as the lab's
    tools do. `nearest` orders by how near to now an item is, rather than newest first, so a calendar's
    holidays five years out do not come before last week's mail. `silo_first` (a silo's key) lists that silo's
    items before the rest, then those in no silo (`rouh/silos.py`). A rule has no passages (D59) and is read by
    its text.

    How it is read (24 October 2026): every word looked up through the trigram indexes, each over every passage,
    took 4.3 s for "Chat Rouh Code Architecture" on Master's 16,400 items and 130,000 passages, because a word
    as common as "Rouh" (in 24,000 passages) made PostgreSQL read the whole passage table, once for each such
    word. So each word is weighed first, by Synapse's counts of how many passages hold it (`_commonness`): a
    word in fewer than `COMMON_DF` is looked up through the indexes as before, and a commoner one is checked
    only on the items those found (0.2 s). When every word is common, the
    newest `WALK_FIRST` items are read first, and every item holding the rarest only when fewer than `limit` of
    those hold all the words. Either way the items are the same, in the same order."""
    words = [w for w in (str(x).strip() for x in words or ()) if w][:8]
    if not words:
        return []
    where, params = ["i.dataset_id = %s", "i.deleted_at IS NULL"], [ds_id]
    if readers is not None:
        where.append(readable_sql("i"))
        params.append(list(readers))
    if kinds_out:
        where.append("NOT (i.kind = ANY(%s::text[]))")
        params.append(list(kinds_out))
    first, first_params = "", []
    if silo_first:
        first = "(CASE WHEN %s = ANY(i.silos) THEN 0 WHEN cardinality(i.silos) = 0 THEN 1 ELSE 2 END), "
        first_params = [silo_first]
    order = f" ORDER BY {first}{NEAREST if nearest else 'i.said_at DESC'} NULLS LAST"
    cols = "i.id, i.kind, i.title, i.source_key, i.said_at, i.tier, i.meta, i.silos"
    common = _commonness(ds_id, words)
    rank = sorted(range(len(words)), key=lambda n: (common[n] if common[n] is not None else 10 ** 9, -len(words[n])))
    looked = [n for n in rank if _indexed(words[n])]
    if not looked:
        # No word the indexes can look up ("🧩", "AI"): each is read as it always was.
        looked = rank
    # A word the indexes find in few passages is looked up through them, as always; a common one, or one they
    # cannot look up, is checked only on the items the others found.
    rare = [n for n in looked if int(common[n] or 0) < COMMON_DF] or looked[:1]
    holds, hold_params = [], []
    for n in rare:
        sql, more = _holding_any(ds_id, words[n])
        holds.append(f"i.id IN ({sql})")
        hold_params += more
    checks, check_params = [], []
    for n in rank:
        if n not in rare:
            sql, more = _holds("i", ds_id, words[n])
            checks.append(sql)
            check_params += more
    if int(common[rare[0]] or 0) >= COMMON_DF and _indexed(words[rare[0]]):
        # Only common words: the newest items are the likeliest to hold them all, so they are read first.
        sql, more = _holds("i", ds_id, words[rare[0]])
        got = db.rows(f"SELECT {cols} FROM (SELECT * FROM synapse.item i WHERE " + " AND ".join(where) +
                      order + " LIMIT %s) i WHERE " + " AND ".join([sql] + checks) + order + " LIMIT %s",
                      [*params, *first_params, WALK_FIRST, *more, *check_params, *first_params, int(limit)])
        if len(got) >= int(limit):
            return got
    sql = f"SELECT {cols} FROM synapse.item i WHERE " + " AND ".join(where[:2] + holds + where[2:] + checks) + order + " LIMIT %s"
    return db.rows(sql, [params[0], *hold_params, *params[1:], *check_params, *first_params, int(limit)])


#: Nearest to now first, either side of it.
NEAREST = "abs(extract(epoch FROM (i.said_at - now())))"

#: The links that tie an item to a person: who sent it, to whom, who came, who spoke, who it is about.
PERSON_LINKS = ["from", "to", "cc", "invited", "attended", "spoke", "about"]


def mentioning(ds_id: str, phrases, *, person: str | None = None, readers: list[str], limit: int = 8,
               kinds_out=("person", "rule", "topic")) -> list[dict]:
    """Items that hold any one of these phrases (a person's name, an address) in their title or text, or that a
    link ties to `person`, nearest to now first: automatic recall's look-up of somebody (`autorecall`).
    Each phrase is its own trigram look-up, put together by UNION: the same phrases OR'd in one condition
    took the planner 2.2 s instead of 0.1 (Master, 9 October 2026)."""
    phrases = [p for p in (str(x).strip() for x in phrases or ()) if len(p) >= 3][:6]
    if not phrases and not person:
        return []
    parts, params = [], []
    for p in phrases:
        parts.append("SELECT p.item_id AS id FROM synapse.passage p WHERE p.dataset_id = %s AND NOT p.from_xray "
                     "AND p.text ILIKE %s")
        parts.append("SELECT t.id FROM synapse.item t WHERE t.dataset_id = %s AND t.title ILIKE %s")
        params += [ds_id, _like(p), ds_id, _like(p)]
    if person:
        # Named `id` here too: a UNION takes its column names from its first part, and with no phrase (a
        # one-word name and no address) this is the first part.
        parts.append("SELECT l.src AS id FROM synapse.link l WHERE l.dataset_id = %s AND l.dst = %s::uuid "
                     "AND l.type = ANY(%s::text[])")
        params += [ds_id, person, PERSON_LINKS]
    sql = ("WITH hits AS (" + " UNION ".join(parts) + ") "
           "SELECT i.id, i.kind, i.title, i.source_key, i.said_at, i.tier, i.meta FROM synapse.item i "
           "JOIN hits h ON h.id = i.id WHERE i.dataset_id = %s AND i.deleted_at IS NULL "
           "AND NOT (i.kind = ANY(%s::text[])) AND " + readable_sql("i") +
           f" ORDER BY {NEAREST} NULLS LAST LIMIT %s")
    return db.rows(sql, [*params, ds_id, list(kinds_out), list(readers), int(limit)])
