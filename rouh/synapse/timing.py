"""Where the time went inside a trace, as plain text for the Synapse chat tools.

Petar, 4 October 2026: the chat tools should say where the time goes inside a
question, not just its totals. Everything needed is already written down by
`trace.py`: every step with its ms, and every call with its ms and the moment
it ended. So this only reads.

A call is put under the step whose time it ended in (the innermost one, when
steps nest). That is read from `synapse.call` rather than from a step's own
`data.calls`, because a step may write a list of its own under that key (the
seed rerank does) and because only the call rows say when each call ended,
which is what tells calls that ran side by side from calls that ran one after
another.
"""
from __future__ import annotations

import statistics

from . import db

SLACK_MS = 5  # rounding between the database's clock and a step's own ms

# The fields of a step's data worth a line, by step name, in the order said.
FIELDS = {
    "understand": ("model",),
    "embed_query": ("model", "dims", "words_only"),
    "search": ("db_ms", "words", "meaning", "fused"),
    "rerank": ("candidates", "normal", "shape", "ranked", "fallback"),
    "seeds": ("seeds", "diversity"),
    "walk": ("db_ms", "ms", "expansions", "gathered", "tokens", "budget", "stop"),
    "pack": ("items", "tokens"),
    "rules": ("tokens",),
    "checkpoint": ("action", "opened", "searched_again", "added"),
    "checkpoint_shadow": ("p_enough", "backend", "fallback"),
    "use": ("shown", "cited"),
}
LABELS = {"db_ms": "db ms", "ms": "own ms", "words": "word hits", "meaning": "meaning hits", "fused": "fused",
          "expansions": "expansions", "stop": "stop", "seeds": "seeds", "items": "items", "tokens": "tokens",
          "budget": "budget", "gathered": "gathered", "candidates": "candidates", "normal": "normal",
          "ranked": "ranked", "fallback": "fallback", "shape": "shape", "dims": "dims", "words_only": "words only",
          "model": "model", "action": "action", "opened": "opened", "searched_again": "searched again",
          "added": "added", "p_enough": "p enough", "backend": "backend", "shown": "shown", "cited": "cited",
          "diversity": "diversity"}


def _ms(v) -> int:
    return int(round(float(v or 0)))


def load(dataset_id: str, trace_id: str) -> dict | None:
    """One of the dataset's traces, its steps and its calls, with every time in ms from the trace's start."""
    t = db.row("SELECT id, dataset_id, kind, title, status, ms, cost_usd, summary, started_at FROM synapse.trace "
               "WHERE dataset_id = %s AND id = %s::uuid", (str(dataset_id), str(trace_id)))
    if not t:
        return None
    t["steps"] = db.rows(
        "SELECT s.seq, s.name, s.title, s.status, s.ms, s.cost_usd, s.data, "
        "extract(epoch FROM s.started_at - t.started_at) * 1000 AS start_ms "
        "FROM synapse.trace_step s JOIN synapse.trace t ON t.id = s.trace_id WHERE s.trace_id = %s ORDER BY s.seq",
        (t["id"],))
    t["calls"] = db.rows(
        "SELECT c.id, c.kind, c.purpose, c.backend, c.model, c.ms, c.tokens_in, c.tokens_out, c.cost_usd, c.ok, "
        "c.error, extract(epoch FROM c.at - t.started_at) * 1000 AS end_ms "
        "FROM synapse.call c JOIN synapse.trace t ON t.id = c.trace_id WHERE c.trace_id = %s ORDER BY c.id",
        (t["id"],))
    for c in t["calls"]:
        c["end"] = float(c.pop("end_ms") or 0)
        c["start"] = c["end"] - _ms(c["ms"])
        c["step"] = None
    for st in t["steps"]:
        st["start"] = float(st.pop("start_ms") or 0)
        st["end"] = st["start"] + _ms(st["ms"])
        st["calls"] = []
        st["data"] = st.get("data") or {}
    for c in t["calls"]:
        # Strictly inside a step beats the slack at another's edge; among
        # steps it is strictly inside, the innermost (latest begun) wins.
        near = [(max(st["start"] - c["end"], c["end"] - st["end"], 0), -st["start"], st) for st in t["steps"]]
        near = [n for n in near if n[0] <= SLACK_MS]
        if near:
            st = min(near, key=lambda n: n[:2])[2]
            st["calls"].append(c)
            c["step"] = st["seq"]
    for c in t["calls"]:
        c["beside"] = sorted({o["purpose"] or o["kind"] for o in t["calls"] if o is not c and _overlap(c, o)})
    t["query"] = db.row("SELECT id, ms_pack, ms_total FROM synapse.query WHERE dataset_id = %s AND trace_id = %s",
                        (t["dataset_id"], t["id"]))
    t["eval_run"] = db.value("SELECT id FROM synapse.eval_run WHERE dataset_id = %s AND trace_id = %s",
                             (t["dataset_id"], t["id"]))
    return t


def _overlap(a: dict, b: dict) -> bool:
    return a["start"] < b["end"] - SLACK_MS and b["start"] < a["end"] - SLACK_MS


def _union(calls: list[dict]) -> int:
    """The wall time a set of calls covered, counting time they overlapped once."""
    spans = sorted((c["start"], c["end"]) for c in calls)
    total, cur = 0.0, None
    for s, e in spans:
        if cur and s <= cur[1]:
            cur[1] = max(cur[1], e)
        else:
            if cur:
                total += cur[1] - cur[0]
            cur = [s, e]
    if cur:
        total += cur[1] - cur[0]
    return int(round(total))


def _most_at_once(calls: list[dict]) -> int:
    marks = sorted([(c["start"], 1) for c in calls] + [(c["end"] - SLACK_MS, -1) for c in calls],
                   key=lambda m: (m[0], m[1]))
    now = most = 0
    for _, d in marks:
        now += d
        most = max(most, now)
    return most


def how_run(calls: list[dict]) -> str:
    """'one call', 'in sequence', 'in parallel' or 'partly in parallel, up to N at once'."""
    if len(calls) < 2:
        return "one call"
    most = _most_at_once(calls)
    if most <= 1:
        return "in sequence"
    if most >= len(calls):
        return "in parallel"
    return f"partly in parallel, up to {most} at once"


def _who(c: dict) -> str:
    return "/".join(x for x in (c.get("backend"), c.get("model")) if x) or "-"


def call_line(c: dict) -> str:
    bits = [f"{c['kind']} {c['purpose'] or '-'}", _who(c), f"{_ms(c['ms'])} ms"]
    if c.get("tokens_out"):
        bits.append(f"{c.get('tokens_in') or 0} in / {c['tokens_out']} out tokens")
    elif c.get("tokens_in"):
        bits.append(f"{c['tokens_in']} tokens")
    if float(c.get("cost_usd") or 0):
        bits.append(money(c["cost_usd"]))
    if not c.get("ok", True):
        bits.append("FAILED " + " ".join(str(c.get("error") or "").split())[:120])
    if c.get("beside"):
        bits.append("ran beside " + ", ".join(c["beside"]))
    return ", ".join(bits)


def money(v) -> str:
    v = float(v or 0)
    return f"${v:.4f}" if v >= 0.0001 or not v else f"${v:.6f}"


def _field(v) -> str:
    if isinstance(v, float):
        return f"{v:.3f}".rstrip("0").rstrip(".")
    if isinstance(v, list):
        return ",".join(str(x) for x in v) or "none"
    return " ".join(str(v).split())[:160]


def step_fields(st: dict) -> str:
    name = st["name"]
    if name.startswith("checkpoint_") and name[len("checkpoint_"):].isdigit():
        name = "checkpoint"
    keys = FIELDS.get(name, ())
    d = st["data"]
    out = [f"{LABELS.get(k, k)} {_field(d[k])}" for k in keys if d.get(k) not in (None, "", [])]
    if d.get("error"):
        out.append("error " + _field(d["error"]))
    return "; ".join(out)


def total_of(t: dict) -> int | None:
    q = t.get("query") or {}
    return _ms(q.get("ms_total") or (t.get("summary") or {}).get("ms_total") or t.get("ms")) or None


def describe(t: dict, *, header: bool = True) -> str:
    """Every step in order with its ms and status, its calls under it, and what no step accounts for."""
    lines = []
    if header:
        total = total_of(t)
        lines.append(f"Trace {t['id']} ({t['kind']}, {t['status']}): {t['title']}; "
                     f"{total if total is not None else '?'} ms, {money(t.get('cost_usd'))}.")
    lines.append("Where the time went (ms):")
    for st in t["steps"]:
        calls = st["calls"]
        head = f"{st['seq']}. {st['name']} {_ms(st['ms'])} ms {st['status']}"
        if calls:
            covered = _union(calls)
            head += (", 1 call" if len(calls) == 1 else
                     f", {len(calls)} calls {how_run(calls)}, {covered} ms wall")
            rest = _ms(st["ms"]) - covered
            if rest > 0:
                # An evaluation's question step spends the rest in the question's own trace.
                head += f", {rest} ms in " + ("the question's own trace" if st["data"].get("query") else "code")
        elif _ms(st["ms"]) >= 20:
            head += ", no calls, all in code"
        fields = step_fields(st)
        lines.append(head + (f" ({fields})" if fields else ""))
        for c in calls:
            lines.append("   - " + call_line(c))
    loose = [c for c in t["calls"] if c["step"] is None]
    if loose:
        lines.append("Calls that ended outside every step:")
        lines += ["   - " + call_line(c) for c in loose]
    total = total_of(t)
    steps_sum = sum(_ms(st["ms"]) for st in t["steps"])
    if total is not None:
        q = t.get("query") or {}
        pack = f"; to the pack {_ms(q['ms_pack'])} ms" if q.get("ms_pack") is not None else ""
        lines.append(f"Total {total} ms; steps add up to {steps_sum} ms; overhead not in any step "
                     f"{total - steps_sum} ms{pack}.")
    groups = [g for g in group_calls(t["calls"]) if g["n"] > 1]
    if groups:
        lines.append("Calls made more than once:")
        for g in groups:
            lines.append(f"   - {g['key']}: {g['n']} call{'s' if g['n'] != 1 else ''}, {g['sum']} ms summed, "
                         f"{g['wall']} ms wall, {g['how']}")
    return "\n".join(lines)


def group_calls(calls: list[dict]) -> list[dict]:
    by: dict[str, list[dict]] = {}
    for c in calls:
        by.setdefault(f"{c['kind']} {c['purpose'] or '-'} ({_who(c)})", []).append(c)
    out = []
    for key, cs in by.items():
        out.append({"key": key, "n": len(cs), "sum": sum(_ms(c["ms"]) for c in cs), "wall": _union(cs),
                    "how": how_run(cs), "max": max(_ms(c["ms"]) for c in cs)})
    return out


def _med(vals) -> int:
    return int(round(statistics.median(vals))) if vals else 0


def eval_breakdown(run: dict) -> str:
    """Per preset: each step's median and max ms across the run's questions, each call kind and
    purpose with its count and whether its calls ran in sequence or in parallel, and per question
    its total, its slowest step and the trace to read it in."""
    rows = run.get("results") or []
    if not rows:
        return "No question has finished in this run yet."
    eval_trace = load(run["dataset_id"], run["trace_id"]) if run.get("trace_id") else None
    judge_by_query = {}
    if eval_trace:
        for st in eval_trace["steps"]:
            q = (st["data"] or {}).get("query")
            if q:
                judge_by_query[str(q)] = sum(_ms(c["ms"]) for c in st["calls"] if c["purpose"] == "judge")
    lines = []
    presets: dict[str, list[dict]] = {}
    for r in rows:
        presets.setdefault(r.get("config") or "?", []).append(r)
    for label, rs in presets.items():
        lines.append(f"Preset {label}: {len(rs)} question{'s' if len(rs) != 1 else ''}.")
        traces = []
        for r in rs:
            tid = db.value("SELECT trace_id FROM synapse.query WHERE dataset_id = %s AND id = %s::uuid",
                           (run["dataset_id"], r["query"])) if r.get("query") else None
            traces.append((r, load(run["dataset_id"], tid) if tid else None))
        steps: dict[str, list[int]] = {}
        order: list[str] = []
        calls: dict[str, dict] = {}
        for _, t in traces:
            if not t:
                continue
            for st in t["steps"]:
                if st["name"] not in steps:
                    order.append(st["name"])
                steps.setdefault(st["name"], []).append(_ms(st["ms"]))
            for g in group_calls(t["calls"]):
                agg = calls.setdefault(g["key"], {"n": [], "ms": [], "wall": [], "how": set()})
                agg["n"].append(g["n"])
                agg["wall"].append(g["wall"])
                agg["how"].add(g["how"])
            for c in t["calls"]:
                key = f"{c['kind']} {c['purpose'] or '-'} ({_who(c)})"
                calls[key]["ms"].append(_ms(c["ms"]))
        if steps:
            lines.append("  Steps, median / max ms:")
            lines += [f"   - {n}: {_med(steps[n])} / {max(steps[n])}"
                      + (f" (in {len(steps[n])} of {len(rs)})" if len(steps[n]) != len(rs) else "") for n in order]
        if calls:
            lines.append("  Calls, per call median / max ms; per question count and wall ms:")
            for key, a in calls.items():
                hows = sorted(a["how"] - {"one call"}) or ["one call"]
                lines.append(f"   - {key}: {_med(a['ms'])} / {max(a['ms'])} ms; {_med(a['n'])} per question "
                             f"(max {max(a['n'])}), {_med(a['wall'])} ms wall median; {' or '.join(hows)}")
        lines.append("  Questions:")
        for r, t in traces:
            name = f"q{r.get('question')}"
            if r.get("error"):
                lines.append(f"   - {name}: failed, {_field(r['error'])}")
                continue
            if not t:
                lines.append(f"   - {name}: its trace is gone")
                continue
            slow = max(t["steps"], key=lambda s: _ms(s["ms"]), default=None)
            judge = judge_by_query.get(str(r.get("query")))
            lines.append(f"   - {name}: {total_of(t)} ms total, to the pack {r.get('ms_pack')} ms"
                         + (f", slowest step {slow['name']} {_ms(slow['ms'])} ms" if slow else "")
                         + (f", judge {judge} ms after it" if judge else "")
                         + f"; trace {t['id']} (query {r.get('query')})")
    if eval_trace:
        lines.append(f"The run's own trace: {eval_trace['id']}.")
    lines.append("Read any of these traces step by step with synapse_trace.")
    return "\n".join(lines)
