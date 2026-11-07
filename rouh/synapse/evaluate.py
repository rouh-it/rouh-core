"""The evaluation set and its runs (section 15, D77, D79).

Each question says who asks it, from where (a context item, as a mail case
would), the gold items a right answer needs, and the key facts it must hold.
A question marked `forbidden` must NOT be answerable: its gold items are the
ones the asker may not reach, and the right result is nothing (the permission
gate).

A run asks every question under one or more configurations and measures, per
configuration:

- **recall at budget**: the share of gold items in the pack;
- **citation correctness**: the share of cited items that support what they are
  cited for, checked by a judge model never of the family that ranked or answered (D77);
- **answer correctness**: the share of key facts the answer holds, same judge;
- **time to pack**, median and slowest 5%, and **cost** per question;
- **leaks**: forbidden items that reached a pack;
- **decision-model privacy**: hosted decision calls that held an item above
  normal, which must be zero (D67).

Two configurations side by side are D79's with-and-without comparison; the
gate for switching a point on is recall up 3 points with nothing else worse.
Evaluation runs are background work: they never teach the links (D57).
"""
from __future__ import annotations

import re
import statistics
import time

from . import ai, datasets, db, numbers, people, recall, text as tx
from .db import Json
from .trace import Trace

JUDGE_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["citations", "facts"],
    "properties": {
        "citations": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["n", "supported", "why"],
            "properties": {"n": {"type": "integer"}, "supported": {"type": "boolean"}, "why": {"type": "string"}}}},
        "facts": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["fact", "present"],
            "properties": {"fact": {"type": "string"}, "present": {"type": "boolean"}}}},
    },
}

PRESETS = {
    "current": {"label": "As tuned now", "override": {}},
    "without": {"label": "Without decision models", "override": {"decision_models": False}},
    "with": {"label": "With decision models, seed rerank on", "override": {"decision_models": True, "seed_rerank": True,
                                                                         "live_timeout_ms": 5000},
             "note": "The live time limit is raised to 5 s so the generative backend can answer the rerank."},
    "background": {"label": "Background pack (frontier scoring)", "override": {"decision_models": True},
                   "mode": "background"},
    "recent_first": {"label": "Recent first (last 90 days, older when weak)", "override": {"recent_first": True},
                     "note": "Search starts with the last recent_days days and adds older items only when that finds "
                             "too little (Tune > Search). Off by default until this says recall holds."},
    "map_on": {"label": "Map on", "override": {"map_on": True},
               "note": "The map loaded into the question (D85); every question is searched."},
    "map_skip": {"label": "Map on, skipping the search when it answers", "override": {"map_on": True,
                                                                                     "map_skip_search": True},
                 "note": "As Map on, and a question the map alone answers is not searched (D85)."},
    "map_off": {"label": "Map off", "override": {"map_on": False},
                "note": "No map: the search query and the answer are written without it (D85). Run it beside Map on "
                        "to see whether the map earns its place."},
}


def questions(ds: dict) -> list[dict]:
    rows = db.rows("SELECT * FROM synapse.eval_question WHERE dataset_id = %s ORDER BY grp, id", (ds["id"],))
    ids = {g for r in rows for g in r.get("gold") or []} | {r["context_item"] for r in rows if r.get("context_item")}
    titles = {r["id"]: r["title"] for r in db.rows(
        "SELECT id, title FROM synapse.item WHERE dataset_id = %s AND id = ANY(%s::uuid[])",
        (ds["id"], list(ids) or ["00000000-0000-0000-0000-000000000000"]))}
    names = people.names([r["asker"] for r in rows])
    for r in rows:
        r["asker_name"] = names.get(r["asker"], people.name_of(r["asker"]))
        r["gold_titles"] = [titles.get(g, "(deleted)") for g in r.get("gold") or []]
        r["context_title"] = titles.get(r.get("context_item")) if r.get("context_item") else None
    return rows


def _resolve(ds: dict, refs) -> list[str]:
    out = []
    for ref in refs or []:
        ref = str(ref).strip()
        if not ref:
            continue
        row = db.row("SELECT id FROM synapse.item WHERE dataset_id = %s AND (id::text = %s OR source_key = %s) "
                     "AND deleted_at IS NULL LIMIT 1", (ds["id"], ref, ref))
        if row:
            out.append(row["id"])
    return out


def add_question(ds: dict, question: str, *, gold=(), facts=(), asker: str = "", context: str = "",
                 forbidden: bool = False, group: str = "") -> dict:
    ctx = _resolve(ds, [context])[0] if context and _resolve(ds, [context]) else None
    row = db.row("INSERT INTO synapse.eval_question (dataset_id, question, context_item, asker, gold, facts, forbidden, grp) "
                 "VALUES (%s, %s, %s, %s, %s::uuid[], %s::jsonb, %s, %s) RETURNING id",
                 (ds["id"], question.strip()[:1000], ctx, people.asker_id(ds, asker),
                  _resolve(ds, gold), Json([f for f in facts if str(f).strip()]), bool(forbidden), group[:60]))
    return {"ok": True, "id": row["id"]}


def update_question(ds: dict, qid: int, fields: dict) -> dict:
    q = db.row("SELECT * FROM synapse.eval_question WHERE dataset_id = %s AND id = %s", (ds["id"], int(qid)))
    if not q:
        return {"ok": False, "why": "no such question"}
    if fields.get("keep_facts_as"):
        sets = dict(q.get("facts_sets") or {})
        sets.setdefault(str(fields["keep_facts_as"]), q["facts"])     # a kept set is never overwritten
        db.run("UPDATE synapse.eval_question SET facts_sets = %s::jsonb WHERE id = %s", (Json(sets), q["id"]))
    gold = _resolve(ds, fields["gold"]) if "gold" in fields else q["gold"]
    db.run("UPDATE synapse.eval_question SET question = %s, gold = %s::uuid[], facts = %s::jsonb, forbidden = %s, "
           "asker = %s, grp = %s WHERE id = %s",
           (fields.get("question", q["question"]), gold, Json(fields.get("facts", q["facts"])),
            bool(fields.get("forbidden", q["forbidden"])),
            people.asker_id(ds, fields["asker"]) if fields.get("asker") else q["asker"],
            fields.get("group", q["grp"]), q["id"]))
    return {"ok": True}


def delete_question(ds: dict, qid: int) -> None:
    db.run("DELETE FROM synapse.eval_question WHERE dataset_id = %s AND id = %s", (ds["id"], int(qid)))


def start(ds: dict, presets: list[str], *, by: str = "page", only: list[int] | None = None,
          configs: list[dict] | None = None) -> dict:
    """A run of the set under presets, or under named configurations of any numbers
    (`{"label": ..., "override": {...}}`), each a pass of its own. Every improvement is
    measured that way: a baseline, each change alone, then all together (Petar, 4 October 2026)."""
    from .ingest import enqueue

    chosen = [dict(PRESETS[p], key=p) for p in presets if p in PRESETS]
    for i, c in enumerate(configs or []):
        override = {k: numbers.clean(k, v) for k, v in (c.get("override") or {}).items()}
        chosen.append({"key": f"custom{i + 1}", "label": str(c.get("label") or f"Configuration {i + 1}")[:80],
                       "override": override, **({"mode": c["mode"]} if c.get("mode") else {})})
    configs = chosen or [dict(PRESETS["current"], key="current")]
    if len({c["label"] for c in configs}) != len(configs):
        raise ValueError("Each configuration needs a label of its own: the summary is keyed by them.")
    run_id = db.value("INSERT INTO synapse.eval_run (dataset_id, label, configs, by) VALUES (%s, %s, %s::jsonb, %s) "
                      "RETURNING id", (ds["id"], " vs ".join(c["label"] for c in configs), Json(configs), by))
    enqueue(ds["id"], "eval", priority=5, payload={"run": run_id, "only": only or []})
    return {"ok": True, "run": run_id, "configs": [c["label"] for c in configs]}


def _family(model: str) -> str:
    m = (model or "").lower()
    for fam in ("gpt-6", "gpt-5", "gpt-4.1", "gpt-4o", "claude"):
        if m.startswith(fam):
            return fam
    return m.split("-")[0]


_STOP = set("the and for are was were has have had with that this from into what which who whom when where why how "
            "your you our not but its his her their they them she him can will would may also only than then there "
            "here about been being does did done".split())


def claims_for(answer: str, n: int) -> str:
    """What the answer says with [n]: its sentences that carry [n], or the whole answer if none do."""
    parts = re.split(r"(?<=[.!?])\s+(?!\[)|(?<=\])\s+(?=[A-Z*-])|\n+", answer or "")
    mine = [p for p in parts if f"[{n}]" in p]
    return " ".join(mine) or answer or ""


def _terms(text: str) -> dict[str, int]:
    """The words a passage should share with a claim; ones with digits (codes, amounts, times) weigh 3."""
    out = {}
    for w in re.findall(r"[\w@./:-]+", (text or "").lower()):
        w = w.strip(".:-/")
        digit = any(c.isdigit() for c in w)
        if w in _STOP or (len(w) < 3 and not digit) or re.fullmatch(r"\d{1,2}", w):
            continue
        out[w] = 3 if digit else 1
    return out


def evidence(ds: dict, item_id: str, raw: str, claim: str, limit: int) -> tuple[str, str]:
    """An item's own words for the judge: whole when it fits, else the passages that best
    match what the answer says with it, in their order (D77, revised 4 October 2026: the
    first 1,500 characters left facts deep in a receipt or a PDF looking unsupported)."""
    whole = " ".join((raw or "").split())
    if len(whole) <= limit:
        return whole, "whole"
    chunks = [" ".join(r["text"].split()) for r in db.rows(
        "SELECT text FROM synapse.passage WHERE dataset_id = ANY(synapse.scope(%s)) AND item_id = %s "
        "AND NOT from_xray ORDER BY seq", (ds["id"], item_id))]
    if not chunks:
        chunks = [whole[k:k + 1200] for k in range(0, len(whole), 1000)]
    want = _terms(claim)
    scored = sorted(range(len(chunks)), key=lambda k: -sum(w for t, w in want.items() if t in chunks[k].lower()))
    keep, size = [], 0
    for k in scored:
        if size + len(chunks[k]) > limit and keep:
            continue
        keep.append(k)
        size += len(chunks[k])
    return "\n...\n".join(chunks[k][:limit] for k in sorted(keep)), \
        f"{len(keep)} of {len(chunks)} parts that best match what the answer says with it, of {len(whole)} characters"


def pick_judge(model: str, ranked_by: list[str], answered_by: list[str], version: str = "v2") -> tuple[str, str]:
    """D77, revised 4 October 2026: a judge of the family that ranked the pack or wrote the answer agrees
    with itself. Until 18 October 2026 such a judge was swapped for the first free one of a list here;
    since then the judge is the one the Models page has for Synapse's judge, always (Petar: "Whatever we
    select here should be the one called. No exceptions."), and a judge of such a family is said, beside
    the result, rather than swapped. Version v1 counts only the ranker's family, kept for measuring."""
    if version == "v1":
        answered_by = []
    taken = {_family(m) for m in list(ranked_by) + list(answered_by) if m}
    if _family(model) not in taken:
        return model, ""
    who = ", ".join(sorted({m for m in list(ranked_by) + list(answered_by) if m and _family(m) == _family(model)}))
    return model, (f"{model} judged, though it is of the family that ranked or answered this question ({who}), "
                   "so it may be lenient (D77): put Synapse's judge on another company's model on the Models page.")


JUDGE_INSTRUCTIONS = (
    "You check an answer. For each cited number, say whether that cited item really supports what the answer "
    "says with it. Judge from the item's own words; a long item is quoted in the parts that best match what the "
    "answer says with it. An item with no words of its own says what it was shown as. For each key fact, say "
    "whether the answer states it. A fact is present when the answer states its substance, in any words: a "
    "name, a number, a link or a code must be the same, but wording, order and spelling of ordinary words may "
    "differ. Judge each fact on its own claim only: a fact that names no date, day or time is not failed because "
    "the answer leaves out a date, day or time; a fact that is itself a date, day or time needs it. A fact the "
    "answer contradicts is not present. Be strict about wrong names, numbers, links and contradictions.")

#: The judge's instructions before 4 October 2026 (`judge_version` v1).
JUDGE_INSTRUCTIONS_V1 = (
    "You check an answer. For each cited number, say whether that cited item really supports what the answer "
    "says with it. Judge from the item's own words; a long item is quoted in the parts that best match what the "
    "answer says with it. An item with no words of its own says what it was shown as. For each key fact, say "
    "whether the answer states it (in any words). Be strict.")


def judge(ds: dict, s, q: dict, answer: dict, pack_items: list[dict], ranked_by: list[str], trace,
          shown_lines: dict | None = None, answered_by: list[str] | None = None) -> dict:
    """D77: the judge is never the model, backend family or weights that ranked or answered."""
    version = str(s.judge_version)
    model, note = pick_judge(str(s.judge_model), ranked_by, answered_by or [str(s.answer_model)], version)
    cited = [i for i in pack_items if i["n"] in (answer.get("cited") or [])]
    # A person lives in the owner's people set, not in this dataset, so look in its scope (as the pack does).
    facts = db.rows("SELECT id, title, raw FROM synapse.item WHERE dataset_id = ANY(synapse.scope(%s)) "
                    "AND id = ANY(%s::uuid[])",
                    (ds["id"], [i["id"] for i in cited] or ["00000000-0000-0000-0000-000000000000"]))
    by_id = {f["id"]: f for f in facts}
    limit = int(s.judge_evidence_chars)
    blocks = []
    for i in cited:
        f = by_id.get(i["id"]) or {}
        shown = (shown_lines or {}).get(i["n"]) or ""
        words, how = evidence(ds, i["id"], f.get("raw") or "", claims_for(answer.get("text") or "", i["n"]), limit)
        blocks.append(f"[{i['n']}] {f.get('title') or i.get('title') or ''}\n"
                      f"SHOWN TO THE ANSWER MODEL AS:\n{shown or '(not recorded)'}\n"
                      f"ITS OWN WORDS ({how}):\n{words or 'none: Synapse wrote this item from others (a layer or a '
                                                         'profile), so what it was shown as is all it says'}")
    text = (f"QUESTION: {q['question']}\n\nANSWER:\n{answer.get('text') or ''}\n\nCITED ITEMS:\n" +
            ("\n\n".join(blocks) or "none") + "\n\nKEY FACTS THE ANSWER SHOULD HOLD:\n" +
            ("\n".join(f"- {f}" for f in q.get("facts") or []) or "none"))
    got = ai.generate(model=model, name="judge", purpose="judge", trace=trace, owner=datasets.owner_of(ds),
                      schema=JUDGE_SCHEMA, max_tokens=2000,
                      instructions=JUDGE_INSTRUCTIONS_V1 if version == "v1" else JUDGE_INSTRUCTIONS, text=text,
                      items=[i["id"] for i in cited])
    cits = got.get("citations") or []
    fct = got.get("facts") or []
    return {"model": got.get("_model") or model, "note": note,
            "citation_correctness": (sum(1 for c in cits if c.get("supported")) / len(cits)) if cits else None,
            "answer_correctness": (sum(1 for f in fct if f.get("present")) / len(fct)) if fct else None,
            "citations": cits, "facts": fct}


def with_facts(q: dict, name: str) -> dict:
    """The question scored against a kept set of key facts (`key_facts`), or its current ones."""
    if name == "current":
        return q
    kept = (q.get("facts_sets") or {}).get(name)
    return dict(q, facts=kept) if kept is not None else q


def ask_one(ds: dict, s, q: dict, config: dict, trace, *, judge_it: bool = True) -> dict:
    """One question of a run under one configuration: asked, measured and judged. The row a run keeps for it.

    `judge_it` False asks and measures it (recall, time, tokens, cost, leaks) with no answer and no judge, for
    the benchmark's cheap repeat passes (`evalbench.py`). It is then asked as a model calling `synapse_query`
    in a chat asks it, and scored on what that model is handed (24 October 2026): recall is of the gold in
    the fitted pack, `numbers_ok` is the share of the gold found whose [n] in the handed text is that item's,
    and `handed_tokens` is the whole text counted as the model counts it. `config["understand"]` turns the
    understand step on for such a pass (off unless said, as for a model calling it)."""
    override = config.get("override") or {}
    q = with_facts(q, str(s.key_facts))
    began = time.time()
    try:
        got = recall.run(ds, q["question"], asker=q["asker"], context_item_id=q.get("context_item"),
                         mode=config.get("mode", "live"), override=override, by="eval",
                         label=f"eval {config['label']}", engaged=False, answer=judge_it,
                         understand=config.get("understand") if not judge_it else None, handed=not judge_it)
    except Exception as exc:  # noqa: BLE001
        return {"question": q["id"], "error": str(exc)}
    query = db.row("SELECT * FROM synapse.query WHERE id = %s", (got["query"],))
    pack = query.get("pack") or {}
    answer = query.get("answer") or {}
    in_pack = {i["id"] for i in (answer.get("pack_items") or pack.get("items") or [])}
    gold = set(q.get("gold") or [])
    handed = numbers_ok = None
    if not judge_it:
        text = recall.handed_text(pack)
        handed = tx.handed(text) + recall.HANDED_HEAD
        # The account's own rules are not handed with the pack: every turn is told them already.
        shown = [i for i in pack.get("items") or [] if not i.get("account")]
        mine = {i["id"]: i for i in shown if i["id"] in gold}
        numbered = {i["n"]: i["id"] for i in shown}
        ok = [g for g, i in mine.items() if str(i.get("lines") or "").startswith(f"[{i['n']}] ")
              and i["lines"] in text and numbered.get(i["n"]) == g]
        numbers_ok = round(len(ok) / len(mine), 4) if mine else None
    if q.get("forbidden"):
        leaked = sorted(gold & in_pack)
        rec = 1.0 if not leaked else 0.0
    else:
        leaked = []
        rec = (len(gold & in_pack) / len(gold)) if gold else None
    ranked_by = [r["model"] for r in db.rows(
        "SELECT DISTINCT model FROM synapse.call WHERE trace_id = %s AND kind = 'decide' AND ok",
        (query["trace_id"],))]
    shown = {i["n"]: i.get("lines") for i in (pack.get("items") or []) + ((pack.get("more") or {}).get("items") or [])}
    answered_by = [r["model"] for r in db.rows(
        "SELECT DISTINCT model FROM synapse.call WHERE trace_id = %s AND kind = 'generate' "
        "AND purpose IN ('understand', 'answer') AND ok", (query["trace_id"],))] or [str(s.answer_model)]
    j = judge(ds, s, q, answer, answer.get("pack_items") or [], ranked_by, trace, shown, answered_by) \
        if (judge_it and answer.get("text") and not q.get("forbidden")) else {}
    hosted_bad = db.value(
        "SELECT count(*) FROM synapse.call c WHERE c.trace_id = %s AND c.kind = 'decide' AND "
        "c.backend = 'openai_decisions' AND EXISTS (SELECT 1 FROM synapse.item i WHERE i.dataset_id = c.dataset_id "
        "AND i.id = ANY(c.items) AND i.sensitivity <> 'normal')", (query["trace_id"],)) or 0
    # Searches this question made: the first unless the map alone answered it (D85), and one
    # more for each time the checkpoint searched again.
    skipped = bool((query.get("walk") or {}).get("skipped"))
    said_enough = db.value("SELECT data->>'map_said_enough' FROM synapse.trace_step WHERE trace_id = %s "
                           "AND name = 'understand' LIMIT 1", (query["trace_id"],)) == "true"
    again = sum(1 for r in answer.get("rounds") or [] if r.get("action") == "recall")
    return {"question": q["id"], "text": q["question"], "query": got["query"], "recall": rec,
            "search_skipped": skipped, "searches": (0 if skipped else 1) + again,
            "map_said_enough": said_enough,
            "gold_found": sorted(gold & in_pack), "gold_missed": sorted(gold - in_pack) if not q.get("forbidden") else [],
            "leaked": leaked, "forbidden": q.get("forbidden"),
            "citation_correctness": j.get("citation_correctness"),
            "answer_correctness": j.get("answer_correctness"), "judge": j,
            "ms_pack": query.get("ms_pack"), "ms_total": query.get("ms_total"), "tokens": pack.get("tokens"),
            "handed_tokens": handed, "numbers_ok": numbers_ok,
            "cost": float(query.get("cost_usd") or 0), "hosted_above_normal": int(hosted_bad),
            "answer": answer.get("text"), "seconds": round(time.time() - began, 1)}


def execute(ds: dict, run_id: str, only: list[int] | None = None) -> dict:
    run = db.row("SELECT * FROM synapse.eval_run WHERE id = %s AND dataset_id = %s", (run_id, ds["id"]))
    if not run:
        return {"ok": False}
    qs = questions(ds)
    if only:
        qs = [q for q in qs if q["id"] in set(only)]
    trace = Trace(ds["id"], "eval", f"Evaluation: {run['label']}", by=run["by"])
    db.run("UPDATE synapse.eval_run SET trace_id = %s WHERE id = %s", (trace.id, run_id))
    results = []
    summary = {}
    for config in run["configs"]:
        override = config.get("override") or {}
        s = datasets.settings(ds, override)
        rows = []
        for q in qs:
            from . import worker
            worker.heartbeat(ds["id"], "eval")
            with trace.step("question", f"{config['label']}: {q['question'][:80]}") as st:
                row = ask_one(ds, s, q, config, trace)
                st.data.update({k: v for k, v in row.items() if k != "judge"})
                rows.append(row)
            results.append({"config": config["label"], **rows[-1]})
            db.run("UPDATE synapse.eval_run SET results = %s::jsonb WHERE id = %s", (Json(results), run_id))
        summary[config["label"]] = _summarise(rows, s)
    with trace.step("summary", "Per configuration, against the gates (section 15, D79)") as st:
        labels = list(summary)
        if len(labels) >= 2:
            base = summary[labels[0]]
            for other in labels[1:]:
                o = summary[other]
                for key in ("citation", "answer"):
                    if base.get(key) is not None and o.get(key) is not None:
                        o[f"{key}_points_vs_first"] = round((o[key] - base[key]) * 100, 1)
                if base.get("recall") is not None and o.get("recall") is not None:
                    o["recall_points_vs_first"] = round((o["recall"] - base["recall"]) * 100, 1)
                    o["decision_gate"] = (o["recall_points_vs_first"] >= float(datasets.settings(ds).gate_decision_points)
                                          and (o.get("citation") or 0) >= (base.get("citation") or 0)
                                          and o.get("privacy", 0) == 0
                                          and all(o["gates"].get(g) for g in ("median", "p95", "cost", "leaks")))
        st.data["summary"] = summary
        st.data["order"] = labels
    db.run("UPDATE synapse.eval_run SET status = 'done', finished_at = now(), summary = %s::jsonb, results = %s::jsonb "
           "WHERE id = %s", (Json(summary), Json(results), run_id))
    trace.finish("done", configs=len(summary))
    return {"ok": True, "summary": summary}


def _summarise(rows: list[dict], s) -> dict:
    def mean(key):
        vals = [r[key] for r in rows if r.get(key) is not None]
        return round(sum(vals) / len(vals), 4) if vals else None
    packs = sorted(r["ms_pack"] for r in rows if r.get("ms_pack") is not None)
    p95 = packs[min(len(packs) - 1, int(round(0.95 * (len(packs) - 1))))] if packs else None
    median = statistics.median(packs) if packs else None
    normal = [r for r in rows if not r.get("forbidden")]
    recall_vals = [r["recall"] for r in normal if r.get("recall") is not None]
    out = {"questions": len(rows), "recall": round(sum(recall_vals) / len(recall_vals), 4) if recall_vals else None,
           "citation": mean("citation_correctness"), "answer": mean("answer_correctness"),
           "handed_tokens": mean("handed_tokens"), "numbers_ok": mean("numbers_ok"),
           "median_ms": median, "p95_ms": p95, "cost": mean("cost"),
           "leaks": sum(len(r.get("leaked") or []) for r in rows),
           "privacy": sum(int(r.get("hosted_above_normal") or 0) for r in rows),
           "errors": sum(1 for r in rows if r.get("error")),
           "searches": sum(int(r.get("searches") or 0) for r in rows),
           "searches_skipped": sum(1 for r in rows if r.get("search_skipped") and not r.get("searches")),
           "skipped_then_searched": sum(1 for r in rows if r.get("search_skipped") and r.get("searches")),
           "map_said_enough": sum(1 for r in rows if r.get("map_said_enough"))}
    out["gates"] = {
        "recall": out["recall"] is not None and out["recall"] >= float(s.gate_recall),
        "citation": out["citation"] is not None and out["citation"] >= float(s.gate_citation),
        "median": median is not None and median <= float(s.gate_median_s) * 1000,
        "p95": p95 is not None and p95 <= float(s.gate_p95_s) * 1000,
        "cost": out["cost"] is not None and out["cost"] <= float(s.gate_cost),
        "leaks": out["leaks"] == 0, "privacy": out["privacy"] == 0}
    return out
