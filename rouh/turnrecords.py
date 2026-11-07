"""Every turn's timings and results, kept for good, to weigh speed against quality later.

Petar, 23 October 2026: "every timing and result shown in the debug tables under each of
my messages saved permanently ... so I can later compare speed against quality and
optimise. For every chat message." The timeline under each reply (`rouh/turntrace.py`)
was drawn live and kept only as part of the "Model decision" line's row, which goes with
its chat; the turn's end, its first written and spoken word, its look-ups of Synapse and
what it cost altogether were not kept anywhere.

So each turn is one `TurnRecord` (`turn_records`), keyed by its chat, the person's
message it answers and the turn's own name, written when the turn ends and again when
anything arrives after it (a request's cost, the recall's trace in Synapse):

- **its timeline** whole (`trace`): the router's bar (model, how sure it was, the bar, its
  pick, timed out or fell back and why, cost), each memory bar, each request of the answer
  (first token, tokens read, cached and written, cost, its row in `llm_requests`), each tool
  (how long, whether it worked, how much it gave back), and how the turn ended. The reply's
  timeline is drawn from it after a reload (`memory.Memory._add_routes_to_transcript`);
- **its times**, from the message reaching the server: the end, the first token, the first
  written word and the first spoken word;
- **every look-up of Synapse** (`synapse`): the automatic recall's (each reader, each find,
  the items each found) and the turn's own `synapse_query` and `synapse_find`, each with its
  trace in Master's Activity and that trace's steps and calls, which are the step-by-step
  times `synapse/timing.py` reads;
- **the answer**: which tier and model wrote it, its rows in the chat and its words;
- **what it all cost** (`cost_usd`, and by part in `costs`), from the log of requests, which
  holds every request whole and is linked by the turn's name rather than copied: the turn's
  own requests and its tools' (`turn_id`), the router's (`subject`), and the recall's, through
  its trace;
- **room for quality** (`labels`): the person's correction, a thumb, a judge's score.

`export` reads them back by day or by range, as JSON or CSV, with each turn's requests
from the log beside it: `/api/turns/export` and `manage.py turn_records`.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import json
import logging
from decimal import Decimal

log = logging.getLogger("rouh.turnrecords")

#: The router's requests in the log, under the turn's name as their subject (`modelrouter.PURPOSE`).
ROUTER_PURPOSES = ("router_decisions", "router")
#: The most characters of an answer kept with its record; the whole of it is in the chat.
REPLY_CHARS = 20_000


def _decimal(x) -> Decimal | None:
    return None if x is None else Decimal(f"{float(x):.6f}")


def synapse_trace(trace_id: str) -> dict | None:
    """One trace in Synapse's Activity, as the record keeps it: its time and cost, and each step with its
    calls (`synapse.timing.load`, the step-by-step times of 13f80a7)."""
    from .synapse import db as sdb, timing

    if not trace_id:
        return None
    try:
        ds = sdb.value("SELECT dataset_id FROM synapse.trace WHERE id = %s::uuid", (str(trace_id),))
        t = timing.load(str(ds), str(trace_id)) if ds else None
    except Exception:  # noqa: BLE001 - a link that cannot be read is still a link
        log.debug("synapse trace %s could not be read", trace_id, exc_info=True)
        return None
    if not t:
        return None

    def n(x):
        return None if x is None else round(float(x), 6)

    return {"trace": str(t["id"]), "kind": t.get("kind"), "status": t.get("status"), "ms": t.get("ms"),
            "cost": n(t.get("cost_usd")),
            "steps": [{"name": st["name"], "title": st.get("title") or "", "status": st.get("status"),
                       "start_ms": int(st["start"]), "ms": st.get("ms"), "cost": n(st.get("cost_usd")),
                       "calls": [{"kind": c["kind"], "purpose": c.get("purpose") or "", "model": c.get("model") or "",
                                  "start_ms": int(c["start"]), "ms": c.get("ms"), "tokens_in": c.get("tokens_in"),
                                  "tokens_out": c.get("tokens_out"), "cost": n(c.get("cost_usd")),
                                  "ok": c.get("ok")} for c in st["calls"]]}
                      for st in t["steps"]]}


def _synapse(trace: dict, mem: dict | None, tools: list[dict], had: list[dict]) -> list[dict]:
    """Every look-up of Synapse the turn made: the recall's bars, then its tools', each trace read once."""
    seen = {str(e.get("trace")): e.get("stages") for e in had if e.get("trace") and e.get("stages")}

    def stages(tid):
        if not tid:
            return None
        if tid not in seen:
            seen[tid] = synapse_trace(tid)
        return seen[tid]

    out: list[dict] = []
    if isinstance(mem, dict):
        shift = int(round((float(mem.get("began") or trace.get("turn_at") or 0) -
                           float(trace.get("turn_at") or 0)) * 1000))
        recall_trace = str(mem.get("trace") or "")
        out.append({"source": "recall", "tool": "recall", "trace": recall_trace, "stages": stages(recall_trace),
                    "message": mem.get("msg"), "applies": mem.get("applies"), "wait_ms": mem.get("wait_ms"),
                    "first_ms": mem.get("first_ms"), "named": mem.get("named"), "named_ms": mem.get("named_ms"),
                    "pick": mem.get("pick"), "used": mem.get("used"), "tokens": mem.get("tokens"),
                    "seed_ids": mem.get("seed_ids") or []})
        for b in mem.get("bars") or []:
            sub = str(b.get("trace") or "")
            out.append({"source": "recall", "tool": b.get("tool"), "what": b.get("what"),
                        "start_ms": None if b.get("start_ms") is None else shift + int(b["start_ms"]),
                        "end_ms": None if b.get("end_ms") is None else shift + int(b["end_ms"]),
                        "outcome": b.get("outcome"), "error": b.get("error") or "", "count": b.get("count"),
                        "ids": b.get("ids") or [], "model": b.get("model") or "", "cost": b.get("cost"),
                        "tokens_in": b.get("tokens_in"), "tokens_out": b.get("tokens_out"),
                        **({"trace": sub, "stages": stages(sub)} if sub else {})})
    for e in tools:
        tid = str(e.get("trace") or "")
        out.append({"source": "tool", **e, **({"stages": stages(tid)} if tid else {})})
    return out


def costs(turn_id: str, synapse: list[dict], trace: dict) -> dict:
    """What the turn cost, by part, in dollars: its own requests and its tools' from the log of requests,
    the router's, and the recall's (its readers and look-ups, through their traces in Synapse)."""
    from django.db.models import Q

    from .models import LLMRequest

    by: dict[str, float] = {}
    priced = False
    for row in (LLMRequest.objects.filter(Q(turn_id=turn_id) | Q(subject=turn_id, purpose__in=ROUTER_PURPOSES))
                .values("purpose", "cost_usd")):
        if row["cost_usd"] is None:
            continue
        priced = True
        purpose = row["purpose"] or ""
        part = ("router" if purpose in ROUTER_PURPOSES else "answer" if purpose == "turn" else
                "synapse_tools" if purpose.startswith("synapse_") else "tools")
        by[part] = by.get(part, 0.0) + float(row["cost_usd"])
    # The recall runs before the turn's requests are named, so its cost is its traces'.
    recall = 0.0
    for e in synapse:
        if e.get("source") == "recall" and isinstance(e.get("stages"), dict) and e["stages"].get("cost") is not None:
            recall += float(e["stages"]["cost"])
    if not recall:
        recall = sum(float(e.get("cost") or 0) for e in synapse if e.get("source") == "recall")
    if recall:
        by["recall"] = recall
        priced = True
    if "router" not in by:
        router = next((lane for lane in trace.get("lanes") or [] if lane.get("kind") == "router"), None)
        if router and router.get("cost") is not None:
            by["router"] = float(router["cost"])
            priced = True
    out = {k: round(v, 6) for k, v in by.items()}
    if priced:
        out["total"] = round(sum(by.values()), 6)
    return out


def save(facts: dict) -> None:
    """Write one turn's record, whole, from what the turn knew when it ended (`runtime.Turn._record`):
    `turn_id`, `session_id`, `trace` (`Trace.snapshot` with `memory`, its recall timeline, and
    `synapse`, its tools' look-ups) and the rest of `TurnRecord`'s fields. Written again whenever
    something arrives after the turn, so the newest is always whole."""
    from .models import TranscriptMessage, TurnRecord

    turn_id = str(facts["turn_id"])
    trace = dict(facts.get("trace") or {})
    tools = list(trace.pop("synapse", None) or [])
    memory = trace.pop("memory", None)
    had = TurnRecord.objects.filter(turn_id=turn_id).values_list("synapse", flat=True).first() or []
    synapse = _synapse(trace, memory, tools, had)
    root, version = facts.get("root"), int(facts.get("version") or 1)
    reply_ids: list[int] = []
    words: list[str] = []
    if root is not None:
        for row in (TranscriptMessage.objects.filter(session_id=facts["session_id"], root=int(root),
                                                      version=version, role="assistant", note=False)
                    .order_by("id").values("id", "content")):
            reply_ids.append(int(row["id"]))
            try:
                content = json.loads(row["content"])
            except (TypeError, ValueError):
                continue
            if isinstance(content, str):
                words.append(content)
            elif isinstance(content, list):
                words.extend(str(b.get("text") or "") for b in content
                             if isinstance(b, dict) and b.get("type") == "text")
    reply = "\n\n".join(w for w in words if w.strip())
    spent = costs(turn_id, synapse, trace)
    fields = {k: facts.get(k) for k in ("session_id", "org_id", "user_id", "message_id", "root", "note", "heard",
                                        "started_at", "ended_at", "total_ms", "status", "error", "tier",
                                        "model", "mode")}
    fields = {k: v for k, v in fields.items() if v is not None}
    fields.update(version=version, first_token_ms=trace.get("first_token_ms"),
                  first_word_ms=trace.get("first_word_ms"), first_spoken_ms=trace.get("spoken_ms"),
                  reply_ids=reply_ids, reply_text=reply[:REPLY_CHARS], cost_usd=_decimal(spent.get("total")),
                  costs=spent, trace=trace, synapse=synapse)
    TurnRecord.objects.update_or_create(turn_id=turn_id, defaults=fields)


def traces_of(turn_ids) -> dict[str, dict]:
    """The kept timelines of these turns, by turn, for a chat read back."""
    from .models import TurnRecord

    wanted = {str(t).split("@", 1)[0] for t in turn_ids if t}
    if not wanted:
        return {}
    # With its own name, which the reply's Details link to its record by (app/turnline.js).
    return {row["turn_id"]: {**row["trace"], "turn_id": row["turn_id"]} for row in
            TurnRecord.objects.filter(turn_id__in=list(wanted)).values("turn_id", "trace") if row["trace"]}


# --- reading them back ------------------------------------------------------------------------------------


def _day_bounds(since: str | None, until: str | None, zone) -> tuple[float, float]:
    """Epoch seconds from the start of `since` to the end of `until` (YYYY-MM-DD, in `zone`), today by default."""
    today = dt.datetime.now(zone).date()
    a = dt.date.fromisoformat(since) if since else today
    b = dt.date.fromisoformat(until) if until else a
    if b < a:
        a, b = b, a
    start = dt.datetime.combine(a, dt.time(), zone)
    end = dt.datetime.combine(b + dt.timedelta(days=1), dt.time(), zone)
    return start.timestamp(), end.timestamp()


def _requests_of(turn_ids: list[str]) -> dict[str, list[dict]]:
    """Each turn's requests from the log, with their times on the turn's clock filled in by `export`."""
    from django.db.models import Q

    from .models import LLMRequest

    out: dict[str, list[dict]] = {}
    if not turn_ids:
        return out
    rows = (LLMRequest.objects.filter(Q(turn_id__in=turn_ids) | Q(subject__in=turn_ids, purpose__in=ROUTER_PURPOSES))
            .order_by("id").values("id", "turn_id", "subject", "purpose", "provider", "model", "served_model", "status",
                                   "stop_reason", "error", "started_at", "finished_at", "first_token_ms", "duration_ms",
                                   "input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens",
                                   "cost_usd", "attempt"))
    for r in rows:
        key = r["turn_id"] or r["subject"]
        r["cost_usd"] = None if r["cost_usd"] is None else float(r["cost_usd"])
        out.setdefault(key, []).append(r)
    return out


def export(identity, since: str | None = None, until: str | None = None, *, chat: str = "", turn: str = "",
           zone=None) -> list[dict]:
    """The records of the person's turns from the day `since` to the day `until` (YYYY-MM-DD, both in, in the
    person's zone; today when neither is given), oldest first, each with its requests from the log of requests
    (`requests`, each with `start_ms` on the turn's clock). Only theirs, in their organisation. With `turn`, that
    one turn's record whatever its day (the Details of a reply's timeline, app/turnline.js)."""
    from .models import TurnRecord

    if zone is None:
        from . import clock

        zone = clock.zone_of(identity)
    rows = TurnRecord.objects.filter(user_id=str(identity.user_id or ""), org_id=str(identity.org_id or ""))
    if turn:
        rows = rows.filter(turn_id=str(turn).split("@", 1)[0])
    else:
        start, end = _day_bounds(since, until, zone)
        rows = rows.filter(started_at__gte=start, started_at__lt=end)
    if chat:
        rows = rows.filter(session_id=chat)
    out = [dict(r) for r in rows.order_by("started_at").values()]
    requests = _requests_of([r["turn_id"] for r in out])
    for r in out:
        r["cost_usd"] = None if r["cost_usd"] is None else float(r["cost_usd"])
        r["at"] = dt.datetime.fromtimestamp(r["started_at"], zone).isoformat(timespec="milliseconds")
        reqs = requests.get(r["turn_id"], [])
        for q in reqs:
            q["start_ms"] = int(round((q["started_at"] - r["started_at"]) * 1000))
        r["requests"] = reqs
    return out


#: The columns of the CSV: one row per turn, the numbers worth sorting by; the JSON has everything.
CSV_COLUMNS = ("at", "turn_id", "session_id", "message_id", "root", "version", "heard", "status", "error", "tier",
               "model", "mode", "total_ms", "first_token_ms", "first_word_ms", "first_spoken_ms", "router_ms",
               "router_outcome", "router_easy", "router_bar", "router_cost", "recall_ms", "recall_items",
               "recall_cost", "requests", "tokens_in", "tokens_cached", "tokens_out", "tools", "tool_ms",
               "tools_failed", "synapse_tools", "cost_usd", "reply_chars", "labels", "reply_text")


def flat(r: dict) -> dict:
    """One record as one CSV row."""
    lanes = (r.get("trace") or {}).get("lanes") or []
    router = next((lane for lane in lanes if lane.get("kind") == "router"), {}) or {}
    route = (r.get("trace") or {}).get("route") or {}
    turn = [q for q in r.get("requests") or [] if q.get("purpose") == "turn"]
    tools = [lane for lane in lanes if lane.get("kind") == "tool"]
    recall = [e for e in r.get("synapse") or [] if e.get("source") == "recall" and e.get("tool") != "recall"]
    recall_ends = [e["end_ms"] for e in recall if e.get("end_ms") is not None]

    def took(lane):
        return None if lane.get("end_ms") is None else lane["end_ms"] - lane["start_ms"]

    return {
        **{k: r.get(k) for k in ("at", "turn_id", "session_id", "message_id", "root", "version", "heard", "status",
                                  "error", "tier", "model", "mode", "total_ms", "first_token_ms", "first_word_ms",
                                  "first_spoken_ms", "cost_usd")},
        "router_ms": took(router) if router else None,
        "router_outcome": router.get("outcome") or route.get("outcome") or "",
        "router_easy": router.get("easy"), "router_bar": router.get("bar"), "router_cost": router.get("cost"),
        "recall_ms": max(recall_ends) if recall_ends else None,
        "recall_items": len({i for e in recall for i in e.get("ids") or []}),
        "recall_cost": (r.get("costs") or {}).get("recall"),
        "requests": len(turn),
        # Everything the answer's requests read, from the cache and into it as well.
        "tokens_in": sum(int(q["input_tokens"] or 0) + int(q["cache_read_tokens"] or 0)
                         + int(q["cache_write_tokens"] or 0) for q in turn),
        "tokens_cached": sum(int(q["cache_read_tokens"] or 0) for q in turn),
        "tokens_out": sum(int(q["output_tokens"] or 0) for q in turn),
        "tools": len(tools), "tool_ms": sum(took(t) or 0 for t in tools),
        "tools_failed": sum(1 for t in tools if t.get("state") == "failed"),
        "synapse_tools": sum(1 for e in r.get("synapse") or [] if e.get("source") == "tool"),
        "reply_chars": len(r.get("reply_text") or ""),
        "labels": json.dumps(r.get("labels") or {}, ensure_ascii=False) if r.get("labels") else "",
        "reply_text": r.get("reply_text") or "",
    }


def as_csv(records: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=CSV_COLUMNS, extrasaction="ignore")
    w.writeheader()
    for r in records:
        w.writerow(flat(r))
    return buf.getvalue()


def as_json(records: list[dict]) -> str:
    return json.dumps(records, ensure_ascii=False, default=str, indent=1)
