"""Every attempt to make Synapse better, one row each (Petar, 5 October 2026).

Petar asked by voice for a nightly loop that makes Synapse better by itself, so that when he writes a
message in any Rouh chat, Rouh already has what Synapse Master knows about it, quickly and accurately.
Each night one idea is tried (`rouh/synapse/nightly.py`), and whatever becomes of it, this table says so:
the ideas considered, the one chosen and why, the hypothesis, what was changed (commits, files), the
benchmark's every measure before and after, the model spend and the time, a conclusion, the outcome, any
decision only the owner can make with its options, and one paragraph in plain English for the morning brief.

The rows before the loop are backfilled from task 85's notes (`BACKFILL`), each marked `source =
'backfilled'` with the note it came from, so the first night already knows what was tried and with which
numbers.

The table is `synapse.attempt` (migration 0087). It is a person's: every row carries `org_id` and
`user_id`, and every query here names both (AGENTS.md, "Whose data is it"). Code is synchronous, to be
called on a thread from async code, like the rest of `rouh/synapse/`.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from .. import db
from ..db import Json

#: Named for the old path (`rouh/synapse/improvements.py`), so the log reads as it did before the move.
log = logging.getLogger("rouh.synapse.improvements")

#: What each outcome is called on the page, in the tool and in the brief.
OUTCOMES = {
    "running": "Running",
    "kept": "Kept",
    "kept_experience": "Kept for the experience",
    "discarded": "Discarded",
    "needs_decision": "Needs ‹owner›'s decision",
    "failed": "Failed",
    "baseline": "Baseline",
}
DONE = ("kept", "kept_experience", "discarded", "needs_decision", "failed", "baseline")

#: The fields a worker may write, and which of them are JSON.
TEXT_FIELDS = ("chosen", "why_chosen", "earlier", "hypothesis", "benchmark", "benchmark_version",
               "conclusion", "report", "run_id", "mode", "notes_ref")
JSON_FIELDS = ("ideas", "changes", "before", "after", "decision", "experience")
NUMBER_FIELDS = ("spend_usd", "duration_s")

#: A running attempt older than this, whose worker has not written it, is called failed.
STALE_HOURS = 10

#: The benchmark's measures (`evalbench.py`): label, unit, and which way is better. Each set's are the same,
#: as `inbox.recall` and `master.recall`; the bare key is both sets together.
MEASURES = {
    "recall": ("Recall: gold items in the pack", "share", "higher"),
    "answer": ("Answer correctness: key facts the answer states", "share", "higher"),
    "citation": ("Citations that support what they are cited for", "share", "higher"),
    "right": ("Questions wholly right", "count", "higher"),
    "p50_ms": ("Time to pack, median", "ms", "lower"),
    "p95_ms": ("Time to pack, slowest 5%", "ms", "lower"),
    "tokens": ("Tokens the pack adds to the turn, average", "tokens", "lower"),
    "cost_per_question_usd": ("Cost per question", "usd", "lower"),
    "leaks": ("Permission leaks", "count", "lower"),
    "questions": ("Questions", "count", ""),
    "errors": ("Questions that failed", "count", "lower"),
}
SET_NAMES = {"inbox": "Inbox set", "master": "Master set"}

#: The measures the morning paragraph names, in this order, when they moved.
HEADLINE = ("recall", "answer", "citation", "p95_ms", "cost_per_question_usd", "tokens", "leaks")
#: The same, as the morning paragraph says them.
PLAIN = {"recall": "the share of the right memory found", "answer": "the share of key facts in the answers",
         "citation": "citations that hold up", "p95_ms": "the slowest lookups", "cost_per_question_usd": "the cost per question",
         "tokens": "the tokens added to each turn", "leaks": "permission leaks"}


# --- reading -----------------------------------------------------------------------------------

def ready() -> bool:
    return bool(db.value("SELECT to_regclass('synapse.attempt') IS NOT NULL"))


def listing(org_id: str, user_id: str, limit: int = 200) -> list[dict]:
    """The person's attempts, newest first."""
    return db.rows("SELECT * FROM synapse.attempt WHERE org_id = %s AND user_id = %s ORDER BY number DESC LIMIT %s",
                   (str(org_id), str(user_id), int(limit)))


def one(org_id: str, user_id: str, number) -> dict | None:
    try:
        n = int(number)
    except (TypeError, ValueError):
        return None
    return db.row("SELECT * FROM synapse.attempt WHERE org_id = %s AND user_id = %s AND number = %s",
                  (str(org_id), str(user_id), n))


def latest(org_id: str, user_id: str, *, source: str | None = None) -> dict | None:
    if source:
        return db.row("SELECT * FROM synapse.attempt WHERE org_id = %s AND user_id = %s AND source = %s "
                      "ORDER BY number DESC LIMIT 1", (str(org_id), str(user_id), source))
    return db.row("SELECT * FROM synapse.attempt WHERE org_id = %s AND user_id = %s ORDER BY number DESC LIMIT 1",
                  (str(org_id), str(user_id)))


def running(org_id: str, user_id: str) -> list[dict]:
    return db.rows("SELECT * FROM synapse.attempt WHERE org_id = %s AND user_id = %s AND outcome = 'running' "
                   "ORDER BY number", (str(org_id), str(user_id)))


# --- writing -----------------------------------------------------------------------------------

def start(org_id: str, user_id: str, *, mode: str = "full", source: str = "nightly", run_id: str = "",
          chosen: str = "") -> dict:
    """A new attempt, running from now, with the next number. Two at once take two numbers."""
    for _ in range(5):
        try:
            with db.atomic():
                n = int(db.value("SELECT coalesce(max(number), 0) + 1 FROM synapse.attempt WHERE org_id = %s "
                                 "AND user_id = %s", (str(org_id), str(user_id))))
                return db.row(
                    "INSERT INTO synapse.attempt (org_id, user_id, number, mode, source, run_id, chosen, started_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, now()) RETURNING *",
                    (str(org_id), str(user_id), n, mode, source, run_id, chosen))
        except Exception as exc:  # noqa: BLE001 - a number taken by another start a moment ago
            if "attempt_number_once" not in str(exc):
                raise
    raise RuntimeError("No number could be taken for a new attempt.")


def update(org_id: str, user_id: str, number, fields: dict) -> dict:
    """Write what a worker found onto its attempt. Unknown fields are refused, by name.

    An outcome other than running finishes the attempt: `finished_at` is set when it was not given, and
    `duration_s` from the start when it was not given either."""
    row = one(org_id, user_id, number)
    if row is None:
        raise ValueError(f"There is no attempt {number}.")
    unknown = sorted(k for k in fields if k not in (*TEXT_FIELDS, *JSON_FIELDS, *NUMBER_FIELDS, "outcome",
                                                     "started_at", "finished_at"))
    if unknown:
        raise ValueError("These are not fields of an attempt: " + ", ".join(unknown))
    sets, params = [], []
    for k, v in fields.items():
        if k == "outcome":
            if v not in OUTCOMES:
                raise ValueError("outcome is one of " + ", ".join(OUTCOMES))
            sets.append("outcome = %s")
            params.append(v)
        elif k in JSON_FIELDS:
            sets.append(f"{k} = %s::jsonb")
            params.append(Json(v if v is not None else ({} if k != "ideas" else [])))
        elif k in NUMBER_FIELDS:
            sets.append(f"{k} = %s")
            params.append(None if v in (None, "") else (float(v) if k == "spend_usd" else int(float(v))))
        elif k in ("started_at", "finished_at"):
            sets.append(f"{k} = %s")
            params.append(v)
        else:
            sets.append(f"{k} = %s")
            params.append(str(v if v is not None else "").replace("\u2014", "-"))
    if fields.get("outcome") in DONE:
        if "finished_at" not in fields:
            sets.append("finished_at = coalesce(finished_at, now())")
        if "duration_s" not in fields:
            sets.append("duration_s = coalesce(duration_s, extract(epoch FROM now() - started_at)::int)")
    sets.append("updated_at = now()")
    db.run(f"UPDATE synapse.attempt SET {', '.join(sets)} WHERE org_id = %s AND user_id = %s AND number = %s",
           (*params, str(org_id), str(user_id), int(row["number"])))
    return one(org_id, user_id, row["number"])


def fail(org_id: str, user_id: str, number, why: str) -> dict:
    """An attempt that could not go on, said in words: the row is always written, whatever stopped it."""
    why = " ".join(str(why or "Something stopped it.").split())
    return update(org_id, user_id, number, {
        "outcome": "failed", "conclusion": why,
        "report": f"Last night's Synapse attempt did not finish: {why[0].lower() + why[1:] if why else why}"})


def _last_said(run_id: str) -> str:
    """What a run said as it ended, from the run register (its last message, as the list shows it), so a
    night whose worker could not write its row still has the worker's own reason on it."""
    try:
        from ... import runs

        row = runs.get(run_id)
    except Exception:  # noqa: BLE001
        return ""
    if row is None:
        return ""
    return " ".join(str(row.detail or row.summary or "").split())[:400]


def settle(org_id: str, user_id: str, *, run_state=None) -> list[int]:
    """Attempts left running that nothing will finish now, called failed with the reason.

    `run_state(run_id)` answers a run's state from the run register ("running", "done", "failed", or "" when
    unknown). A run that ended without writing its attempt, and an attempt older than `STALE_HOURS`, are both
    failed here, so a morning never shows a night as still running."""
    settled = []
    for row in running(org_id, user_id):
        state = ""
        if run_state is not None and row.get("run_id"):
            try:
                state = str(run_state(row["run_id"]) or "")
            except Exception:  # noqa: BLE001
                state = ""
        started = row.get("started_at")
        age_h = (datetime.now(timezone.utc) - started).total_seconds() / 3600 if started else 0
        why = ""
        if state and state not in ("running", "starting", "waiting", "queued"):
            said = _last_said(row["run_id"])
            why = (f"Its worker, run {row['run_id']}, ended ({state}) without writing what it found"
                   + (f". It said: {said}" if said else ", so what it did is not known; its run's own report has "
                      "whatever it said."))
        elif age_h >= STALE_HOURS:
            why = (f"Its worker{(' (run ' + row['run_id'] + ')') if row.get('run_id') else ''} had not written what "
                   f"it found {STALE_HOURS} hours after it started.")
        if why:
            fail(org_id, user_id, row["number"], why)
            settled.append(int(row["number"]))
    return settled


# --- the measures, in words ---------------------------------------------------------------------

def _split(key: str) -> tuple[str, str]:
    """`inbox.recall` as ("inbox", "recall"); a bare key as ("", key)."""
    part, _, rest = str(key).partition(".")
    return (part, rest) if rest and part in SET_NAMES else ("", key)


def label_of(key: str) -> str:
    part, base = _split(key)
    label = MEASURES[base][0] if base in MEASURES else key
    return f"{SET_NAMES[part]}: {label[0].lower() + label[1:]}" if part else label


def _better(key: str) -> str:
    key = _split(key)[1]
    """Which way is better: the catalogue's, or for a backfilled measure, read from its name (times, costs,
    calls and leaks lower; shares, cases right and things found higher)."""
    if key in MEASURES:
        return MEASURES[key][2]
    k = key.lower()
    if any(w in k for w in ("(ms)", "(s)", "cost", "($)", "calls", "leaks", "build", "tokens", "cpu")):
        return "lower"
    if any(w in k for w in ("(%)", "right", "found", "items/s", "ready", "holding")):
        return "higher"
    return ""


def fmt(key: str, value) -> str:
    """One measure's value as a person reads it: 62%, 340 ms, $0.0004, 3."""
    if value is None or value == "":
        return "-"
    if isinstance(value, (list, dict)):
        return str(value)
    key = _split(key)[1]
    unit = MEASURES[key][1] if key in MEASURES else ""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    if unit == "share":
        return f"{v * 100:.1f}%"
    if unit == "ms":
        return f"{v:,.0f} ms"
    if unit == "usd":
        return f"${v:.5f}" if v < 0.01 else f"${v:,.4f}"
    if unit in ("tokens", "count"):
        return f"{v:,.0f}"
    return f"{v:g}" if isinstance(value, float) else str(value)


def compare(before: dict, after: dict) -> list[dict]:
    """Every measure in either, with both values and which way it moved; both sets together first, then each set.

    An `_reference` in `after` (the earlier inbox-only run beside the first baseline) is shown beside its measures
    as `reference_text`, for reference, never as the figure to beat."""
    before, after = before or {}, after or {}
    ref = after.get("_reference") or {}
    names = [k for k in list(before) + list(after) if not str(k).startswith("_")]
    keys = [k for k in MEASURES if k in names]
    for part in SET_NAMES:
        keys += [f"{part}.{k}" for k in MEASURES if f"{part}.{k}" in names]
    keys += [k for k in names if k not in keys and k != "messages"]
    seen, out = set(), []
    for k in keys:
        if k in seen:
            continue
        seen.add(k)
        b, a = before.get(k), after.get(k)
        moved = ""
        try:
            fb, fa = float(b), float(a)
            if fa != fb and _better(k):
                moved = "better" if (fa > fb) == (_better(k) == "higher") else "worse"
            elif fa == fb:
                moved = "same"
        except (TypeError, ValueError):
            pass
        m = {"key": k, "label": label_of(k), "before": b, "after": a,
             "before_text": fmt(k, b), "after_text": fmt(k, a), "moved": moved}
        part, base = _split(k)
        if ref and part == ref.get("set", "inbox") and base in ref:
            m["reference_text"] = fmt(base, ref[base])
        out.append(m)
    return out


def _moves(row: dict) -> tuple[list[str], list[str]]:
    better, worse = [], []
    for m in compare(row.get("before") or {}, row.get("after") or {}):
        part, base = _split(m["key"])
        if base not in HEADLINE or not m["moved"] or m["moved"] == "same" or (part and m["moved"] != "worse"):
            continue
        plain = PLAIN.get(base, m["label"].lower())
        words = (f"{plain} went from {m['before_text']} to {m['after_text']}"
                 + (f" on the {SET_NAMES[part].lower()}" if part else ""))
        (better if m["moved"] == "better" else worse).append(words)
    return better, worse


def recalibration(row: dict) -> dict | None:
    """What a night did first because Synapse's code had changed (`recalibrate.decide`), or None."""
    for side in ("before", "after"):
        rec = (row.get(side) or {}).get("_recalibrated")
        if isinstance(rec, dict) and rec.get("needed"):
            return rec
    return None


def paragraph(row: dict) -> str:
    """The morning's paragraph about one attempt: the worker's own when it wrote one, else made from the row,
    led by the recalibration when the night made one."""
    if (row.get("report") or "").strip():
        return row["report"].strip()
    from .recalibrate import words_of

    first = words_of(recalibration(row))
    said = _paragraph(row)
    return f"{first} {said}" if first and row.get("outcome") not in ("running", "failed") else said


def _paragraph(row: dict) -> str:
    outcome = row.get("outcome") or "running"
    idea = (row.get("chosen") or "").strip().rstrip(".")
    if outcome == "running":
        return (f"Last night's Synapse attempt (number {row['number']}) is still running"
                + (f": it is trying {idea[0].lower() + idea[1:]}." if idea else "."))
    if outcome == "failed":
        return f"Last night's Synapse attempt did not finish. {row.get('conclusion') or ''}".strip()
    if outcome == "baseline":
        a = row.get("after") or {}
        n = a.get("questions")
        parts = []
        if a.get("recall") is not None:
            parts.append(f"Synapse found {fmt('recall', a['recall'])} of the right memory for "
                         + (f"{int(n)} test questions" if n else "the test questions"))
        if a.get("answer") is not None:
            parts.append(f"answers held {fmt('answer', a['answer'])} of the key facts"
                         + (f", and {int(a['right'])} were wholly right" if a.get("right") is not None else ""))
        if a.get("inbox.answer") is not None and a.get("master.answer") is not None:
            parts.append(f"{fmt('answer', a['inbox.answer'])} on the mail questions and "
                         f"{fmt('answer', a['master.answer'])} on the rest of the memory")
        if a.get("p95_ms") is not None:
            parts.append(f"the slowest lookups took {fmt('p95_ms', a['p95_ms'])}")
        if a.get("leaks") is not None:
            parts.append("nothing leaked" if not a["leaks"] else f"{int(a['leaks'])} item{'s' if int(a['leaks']) != 1 else ''} leaked")
        said = "; ".join(parts)
        rec = recalibration(row)
        if rec and not rec.get("trusted"):
            return ("No idea was tried, because nothing can be judged against figures that look wrong"
                    + (f". What was measured: {said}." if said else ".") + " Nothing was changed.")
        return ("Synapse was measured without changing anything, to set the starting point for the nights to come"
                + (f": {said}." if said else ".") + " Nothing was changed, so there is nothing to keep or undo.")
    if outcome == "kept_experience":
        x = row.get("experience") or {}
        ev = (x.get("evidence") or [{}])[0]
        said = [f"Last night's change was kept because it makes Rouh better to use: {x.get('expected') or idea}."]
        if ev.get("message"):
            said.append(f"For example, when you wrote \"{ev['message']}\", before: {str(ev.get('before', '')).rstrip('.')}; "
                        f"now: {str(ev.get('after', '')).rstrip('.')}.")
        said.append("No benchmark number moved. It is live already; just say if you want it undone.")
        return " ".join(said)
    better, worse = _moves(row)
    said = [f"Last night's Synapse idea was {idea[0].lower() + idea[1:]}." if idea else "Last night Synapse tried an idea."]
    if better:
        said.append("Better: " + "; ".join(better) + ".")
    if worse:
        said.append("Worse: " + "; ".join(worse) + ".")
    said.append({"kept": "It worked and was kept, so it is live now.",
                 "discarded": "It did not help enough, so it was not kept and nothing changed.",
                 "needs_decision": "It needs your decision before anything changes."}.get(outcome, ""))
    d = row.get("decision") or {}
    if d.get("question"):
        opts = "; ".join(o.get("label", "") + (f" ({o['detail']})" if o.get("detail") else "")
                         for o in d.get("options") or [])
        said.append(f"The decision: {d['question']}" + (f" The options: {opts}." if opts else ""))
    return " ".join(s for s in said if s)


def view(row: dict) -> dict:
    """One attempt as the page draws it and the tool reads it."""
    out = {k: row.get(k) for k in ("number", "mode", "source", "notes_ref", "run_id", "ideas", "chosen", "why_chosen",
                                   "earlier", "hypothesis", "changes", "benchmark", "benchmark_version", "before",
                                   "after", "conclusion", "outcome", "decision", "report", "experience")}
    out["started_at"] = row["started_at"].isoformat() if row.get("started_at") else None
    out["finished_at"] = row["finished_at"].isoformat() if row.get("finished_at") else None
    out["spend_usd"] = float(row["spend_usd"]) if row.get("spend_usd") is not None else None
    out["duration_s"] = row.get("duration_s")
    out["outcome_words"] = OUTCOMES.get(row.get("outcome") or "", row.get("outcome") or "")
    out["measures"] = compare(row.get("before") or {}, row.get("after") or {})
    out["reference"] = (row.get("after") or {}).get("_reference") or None
    out["paragraph"] = paragraph(row)
    from .recalibrate import words_of

    rec = recalibration(row)
    out["recalibration"] = {**rec, "words": words_of(rec)} if rec else None
    return out


def summary_line(row: dict) -> str:
    """One line for a list: "#18 Baseline, 5 Oct: current main measured"."""
    from ... import clock

    when = row["started_at"].astimezone(clock.zone()).strftime("%-d %b") if row.get("started_at") else ""
    head = f"#{row['number']} {OUTCOMES.get(row['outcome'], row['outcome'])}, {when}"
    what = (row.get("chosen") or "").strip() or "(no idea chosen yet)"
    return f"{head}: {what}" + (" [backfilled from notes]" if row.get("source") == "backfilled" else "")


def as_text(row: dict) -> str:
    """Everything about one attempt, as the model reads it in `synapse_improvements`."""
    v = view(row)
    lines = [summary_line(row),
             f"Started {v['started_at'] or '-'}, finished {v['finished_at'] or '-'}; mode {v['mode']}; "
             f"source {v['source']}" + (f" ({v['notes_ref']})" if v["notes_ref"] else "")
             + (f"; worker run {v['run_id']}" if v["run_id"] else "")]
    if v["ideas"]:
        lines.append("Ideas considered:")
        for i in v["ideas"]:
            if isinstance(i, dict):
                lines.append(f"- {i.get('idea', '')}" + (f" ({i['note']})" if i.get("note") else ""))
            else:
                lines.append(f"- {i}")
    for k, word in (("why_chosen", "Why this one"), ("earlier", "What earlier attempts suggested"),
                    ("hypothesis", "Hypothesis")):
        if v[k]:
            lines.append(f"{word}: {v[k]}")
    ch = v["changes"] or {}
    if ch:
        lines.append("Changed: " + str(ch.get("summary") or "")
                     + (f" Commits: {', '.join(ch.get('commits') or [])}." if ch.get("commits") else "")
                     + (f" Files: {', '.join(ch.get('files') or [])}." if ch.get("files") else "")
                     + (f" Branch: {ch['branch']}." if ch.get("branch") else ""))
    rec = v.get("recalibration")
    if rec:
        lines.append(f"Recalibration ({rec.get('how')}): {rec['words']}"
                     + (f" Found {rec['same_memory']}." if rec.get("same_memory") else "")
                     + (f" Changed since: {'; '.join(rec.get('commits') or [])}." if rec.get("commits") else ""))
    if v["benchmark"]:
        lines.append(f"Benchmark: {v['benchmark']} {v['benchmark_version']}".strip())
    if v["measures"]:
        lines.append("Measures (before -> after):")
        lines += [f"- {m['label']}: {m['before_text']} -> {m['after_text']}" + (f" ({m['moved']})" if m["moved"] else "")
                  for m in v["measures"]]
    ref = v.get("reference")
    if ref:
        lines.append(f"For reference only, not the figure to beat: {ref.get('label', '')} (run {ref.get('run', '')}): "
                     + ", ".join(f"{label_of(k)} {fmt(k, ref[k])}" for k in MEASURES if k in ref))
    x = v.get("experience") or {}
    if x.get("expected"):
        lines.append(f"Experience gain expected: {x['expected']}")
        for e in x.get("evidence") or []:
            lines.append(f"- \"{e.get('message', '')}\": before: {e.get('before', '')} | after: {e.get('after', '')}")
        if x.get("page"):
            lines.append(f"Evidence page: /workspace/{x['page']}")
    if v["spend_usd"] is not None or v["duration_s"] is not None:
        lines.append(f"Model spend ${v['spend_usd'] or 0:.4f}; took {int(v['duration_s'] or 0) // 60} min")
    if v["conclusion"]:
        lines.append(f"Conclusion: {v['conclusion']}")
    d = v["decision"] or {}
    if d.get("question"):
        lines.append(f"Decision needed: {d['question']}")
        lines += [f"- {o.get('label', '')}: {o.get('detail', '')}" for o in d.get("options") or []]
        if d.get("answer"):
            lines.append(f"‹owner› decided: {d['answer']}")
    lines.append(f"Morning report: {v['paragraph']}")
    return "\n".join(lines)


def tool(org_id: str, user_id: str, args: dict) -> str:
    """`synapse_improvements`: list the attempts, or read one (a number, or "latest")."""
    if not ready():
        return "The attempts table is not in this database yet (migration 0087)."
    which = str((args or {}).get("attempt") or "").strip().lstrip("#").lower()
    if which:
        row = latest(org_id, user_id, source="nightly") if which in ("latest", "last", "last night") else \
            one(org_id, user_id, which)
        if row is None and which in ("latest", "last", "last night"):
            row = latest(org_id, user_id)
        if row is None:
            return f"There is no attempt {which}."
        return as_text(row)
    rows = listing(org_id, user_id, int((args or {}).get("limit") or 30))
    if not rows:
        return "No attempt to improve Synapse has been recorded yet."
    return ("Attempts to improve Synapse, newest first (the Improvements page in the Synapse lab shows each; read one "
            "with attempt):\n" + "\n".join("- " + summary_line(r) for r in rows))


# --- the rows before the loop, from task 85's notes ---------------------------------------------

#: A path in the workspace.
NOTES = "rouh/assistant/85.rouh-memory/85-02.synapse-lab-first-version/"
SIX = NOTES + "85-02.six-scaling-changes.md"
BENCH = "synapse_bench"


def _t(text: str) -> str:
    return " ".join(text.split())


#: What task 85 already documents with numbers, oldest first. Times are when the change was committed, on
#: Sofia's clock, which is what the notes and the commits say; durations are left out where no note gives one.
BACKFILL: list[dict] = [
    {
        "started_at": "2026-10-04T01:00:00+03:00", "finished_at": "2026-10-04T01:26:00+03:00",
        "chosen": "One model call per item: the X-ray call also decides tier, sensitivity and area (D82)",
        "ideas": [{"idea": "Keep the separate tier call and sensitivity questions"},
                  {"idea": "Ask the X-ray call for tier, sensitivity and area too", "note": "chosen"},
                  {"idea": "A cheap decision model for the tier (D73)", "note": "kept for reference only"}],
        "why_chosen": _t("Asking the call that already reads the item costs almost nothing more, while the separate "
                         "calls added a median 2.7 s and about $0.00029 an item."),
        "hypothesis": _t("One call is cheaper and faster per item and agrees with the separate calls on tier and "
                         "sensitivity most of the time."),
        "changes": {"summary": "The X-ray call returns tier, sensitivity and area; the separate calls stay behind two "
                               "Tune settings, off.", "commits": ["0a8d5ad9"], "files": ["rouh/synapse/ingest.py",
                                                                                       "rouh/synapse/numbers.py"]},
        "benchmark": "one-call benchmark (64 items, real OpenAI)", "benchmark_version": "4 Oct 2026",
        "before": {"Cost per item ($)": 0.00080, "Median time per item (s)": 8.0},
        "after": {"Cost per item ($)": 0.00052, "Median time per item (s)": 5.3,
                  "Tier agreement with the separate call": "61 of 64",
                  "Sensitivity agreement (special or not)": "48 of 64"},
        "spend_usd": None, "duration_s": None, "outcome": "kept",
        "conclusion": _t("One call is about a third cheaper and about 2.7 s faster per item; tier agreed on 61 of 64; "
                         "all 16 sensitivity disagreements were the separate questions calling business money "
                         "special. The owner decided it (D82)."),
        "report": _t("The idea was to have the one model call that reads an item also decide its importance, its "
                     "sensitivity and its area, instead of three separate calls. It worked: cost per item went from "
                     "about $0.00080 to $0.00052 and the median time from about 8 seconds to 5.3 seconds, and the "
                     "importance agreed with the old way on 61 of 64 items. It was kept."),
        "notes_ref": NOTES + "85-02.one-call-benchmark.md",
    },
    {
        "started_at": "2026-10-04T03:01:00+03:00", "finished_at": "2026-10-04T06:13:00+03:00",
        "chosen": "Mail attachments become items of their own, linked to their email",
        "ideas": [{"idea": "Each file an item of its own with an attached link", "note": "chosen"},
                  {"idea": "Append a file's words to its email's text"},
                  {"idea": "Leave files out"}],
        "why_chosen": _t("Answers that live only inside a PDF could not be found at all, and the same file on three "
                         "emails should be one item."),
        "hypothesis": "A question whose answer is only inside an attachment is answered from it, cited first.",
        "changes": {"summary": "rouh/synapse/mailfiles.py: every file part an item (doc when read, file when not), "
                               "one item per sha256, an attached link per email, the email's readers and level as a "
                               "floor.", "commits": ["0bcd3b30"], "files": ["rouh/synapse/mailfiles.py",
                                                                           "rouh/synapse/ingest.py",
                                                                           "rouh/web/synapse.py"]},
        "benchmark": "mail-files-check.py and one question from inside a file", "benchmark_version": "4 Oct 2026",
        "before": {"Email files kept as items": 0, "Attached links": 0},
        "after": {"Email files kept as items": 9, "Attached links": 16, "File parts skipped with a reason": 3,
                  "Checks passed": "24 of 24", "Question answered only from a PDF": "yes, cited first"},
        "spend_usd": 0.059, "duration_s": 390, "outcome": "kept",
        "conclusion": _t("19 file parts in Gmail became 9 items with 16 attached links; 3 skipped (a signature logo "
                         "twice, a bounce icon); a client's provisioning question was answered from the PDF in "
                         "8.6 s for $0.0013."),
        "report": _t("The idea was to keep every email attachment as its own item, linked to its email. It worked: "
                     "9 files with 16 links came in for $0.059, all 24 checks passed, and a question whose answer is "
                     "only inside a PDF was answered from it. It was kept."),
        "notes_ref": NOTES + "85-02.rouh-inbox-attachments.md",
    },
    {
        "started_at": "2026-10-04T03:30:00+03:00", "finished_at": "2026-10-04T04:21:00+03:00",
        "chosen": "People mentioned in an item's text, read in the same X-ray call and kept as data (Q21)",
        "ideas": [{"idea": "Read the people in the X-ray call, keep them as data, link nobody", "note": "chosen"},
                  {"idea": "A separate call for people"},
                  {"idea": "Make person items and links straight away", "note": "left for Q21"}],
        "why_chosen": "The owner asked to prepare for people from text without matching anybody yet.",
        "hypothesis": "The same call finds the people a text names, at a modest extra cost.",
        "changes": {"summary": "people_mentioned and unattributed_identifiers in the X-ray's output, quotes and "
                               "identifiers checked by code, kept on synapse.item.mentions (migration 0070).",
                    "commits": ["91e99915"], "files": ["rouh/synapse/mentions.py", "rouh/synapse/ingest.py"]},
        "benchmark": "people-mentioned cost (71 items, real gpt-6-luna)", "benchmark_version": "4 Oct 2026",
        "before": {"Tokens in per X-ray": 4043, "Tokens out per X-ray": 520, "Cost per X-ray, list ($)": 0.00066,
                   "Median time (s)": 5.1, "95th percentile time (s)": 7.2},
        "after": {"Tokens in per X-ray": 4714, "Tokens out per X-ray": 752, "Cost per X-ray, list ($)": 0.00085,
                  "Median time (s)": 7.4, "95th percentile time (s)": 9.4,
                  "Names found on gold items": "15 of 15", "Identifiers right on gold items": "6 of 6"},
        "spend_usd": None, "duration_s": None, "outcome": "kept",
        "conclusion": _t("About $0.18 more per 1,000 X-rays and 2.3 s more per call; every name and identifier on "
                         "the four gold items right. Four items is too few to say more."),
        "report": _t("The idea was to have the model that reads each item also note the people its text names. It "
                     "worked on the test items, finding 15 of 15 names, at about 28% more cost per read ($0.00066 to "
                     "$0.00085) and 2.3 seconds more. It was kept."),
        "notes_ref": NOTES + "85-02.people-mentioned.md",
    },
    {
        "started_at": "2026-10-04T14:51:00+03:00", "finished_at": "2026-10-04T16:15:00+03:00",
        "chosen": "Card 1125 change 1: BM25 with early stopping for the words list",
        "ideas": [{"idea": "capped: the rarest words' passages, capped at 2,000", "note": "as it was"},
                  {"idea": "bm25: BM25 in PostgreSQL over the GIN index", "note": "chosen"},
                  {"idea": "pg_search: ParadeDB's Tantivy index", "note": "best, but needs a PostgreSQL restart"}],
        "why_chosen": "Old items asked for by ordinary words were lost by the capped list, and the slowest searches took seconds.",
        "hypothesis": "BM25 finds old and short items the capped list lost, without slowing the usual search.",
        "changes": {"summary": "The words list ranks by BM25 in PostgreSQL by default; pg_search selectable.",
                    "commits": ["749b6a38", "228fc7e2"], "files": ["rouh/synapse/search.py"]},
        "benchmark": BENCH, "benchmark_version": "v2, 1,000,000 fictional items",
        "before": {"Ranking cases right (%)": 51.1, "Old item, four ordinary words": "0 of 20",
                   "Short item about a word": "1 of 15", "Slowest planted searches p95 (ms)": 3997,
                   "Search p95 (ms)": 158.1, "Database CPU per search (ms)": 90.0, "Leaks": 0},
        "after": {"Ranking cases right (%)": 77.8, "Old item, four ordinary words": "15 of 20",
                  "Short item about a word": "15 of 15", "Slowest planted searches p95 (ms)": 223,
                  "Search p95 (ms)": 171.0, "Database CPU per search (ms)": 73.8, "Leaks": 0},
        "spend_usd": 0, "duration_s": None, "outcome": "kept",
        "conclusion": "Ranking 51.1% to 77.8% at 1,000,000 (74.8% to 93.3% at 100,000), search p95 about the same.",
        "report": _t("The idea was a better way to rank search results by their words (BM25). It worked: on a "
                     "million test items the share of ranking cases right went from 51.1% to 77.8%, and the slowest "
                     "searches from about 4 seconds to 0.2 seconds, with no leaks. It was kept."),
        "notes_ref": SIX,
    },
    {
        "started_at": "2026-10-04T16:15:00+03:00", "finished_at": "2026-10-04T16:30:00+03:00",
        "chosen": "Card 1125 change 2: link candidates find the same file by its hash, and an item by its key",
        "ideas": [{"idea": "Keep each upload's sha256 and look it up", "note": "chosen"},
                  {"idea": "Five, eight or ten rare words for link candidates", "note": "no difference; eight stays"}],
        "why_chosen": "An upload kept no hash, so the same file stored twice was never linked.",
        "hypothesis": "Link candidates hold the link they should more often.",
        "changes": {"summary": "Uploads keep their sha256; migration 0073 indexes it and the lookup by key.",
                    "commits": ["353765ed"], "files": ["rouh/synapse/ingest.py", "rouh/migrations/0073_synapse_link_lookups.py"]},
        "benchmark": BENCH, "benchmark_version": "v2, 100,000 and 1,000,000 fictional items",
        "before": {"Link candidates holding the link, 100,000 (%)": 94.1, "Link candidates holding the link, 1,000,000 (%)": 83.5},
        "after": {"Link candidates holding the link, 100,000 (%)": 100, "Link candidates holding the link, 1,000,000 (%)": 89.4},
        "spend_usd": 0, "duration_s": None, "outcome": "kept",
        "conclusion": "Link candidate recall 94.1% to 100% at 100,000 and 83.5% to 89.4% at 1,000,000.",
        "report": _t("The idea was to recognise the same file stored twice by its fingerprint. It worked: links found "
                     "went from 94.1% to 100% on 100,000 test items. It was kept."),
        "notes_ref": SIX,
    },
    {
        "started_at": "2026-10-04T16:30:00+03:00", "finished_at": "2026-10-04T17:03:00+03:00",
        "chosen": "Card 1125 change 3: readers in the index",
        "ideas": [{"idea": "An index on the readers column"}, {"idea": "Keep the filter in the same scan", "note": "as it was"}],
        "why_chosen": "The card proposed it for permission filtering at scale.",
        "hypothesis": "An index on readers makes a non-owner's searches faster.",
        "changes": {"summary": "Nothing: the filter already saves work.", "commits": ["4677c9d7"], "files": []},
        "benchmark": BENCH, "benchmark_version": "v2, 1,000,000 fictional items",
        "before": {"Vera's search p50 with the filter (ms)": "134 to 141"},
        "after": {"Vera's search p50 with the filter widened to everyone (ms)": 159, "Leaks": 0},
        "spend_usd": 0, "duration_s": None, "outcome": "discarded",
        "conclusion": "The reader filter already makes the search faster, so an index on it has nothing to win; none was added.",
        "report": _t("The idea was an index on who may read each item. It was measured and not needed: searches "
                     "with the reader filter already took 134 to 141 ms against 159 ms without it. Nothing changed."),
        "notes_ref": SIX,
    },
    {
        "started_at": "2026-10-04T16:39:00+03:00", "finished_at": "2026-10-04T19:25:00+03:00",
        "chosen": "The vector index searched 100 deep and built with 32 links per node (found by the baseline)",
        "ideas": [{"idea": "ef_search 40, 100 or 200"}, {"idea": "Rebuild HNSW with m 32, ef_construction 128", "note": "chosen with ef_search 100"}],
        "why_chosen": "Meaning-only questions found their own item 40% of the time at 1,000,000 though an exact scan finds it.",
        "hypothesis": "A deeper search and a better connected graph find meaning-only questions again.",
        "changes": {"summary": "hnsw_ef_search 100 by default; migration 0076 rebuilds the index with m 32.",
                    "commits": ["aadac2a8", "cc2205e0"], "files": ["rouh/synapse/search.py", "rouh/migrations/0076_synapse_vector_graph.py"]},
        "benchmark": BENCH, "benchmark_version": "v2, 1,000,000 fictional items",
        "before": {"Meaning-only questions found (%)": 40, "Ranking cases right (%)": 77.8, "Vera's meaning-only (%)": 45,
                   "Index build (min)": 18},
        "after": {"Meaning-only questions found (%)": 100, "Ranking cases right (%)": 94.1, "Vera's meaning-only (%)": 95,
                  "Search p95 (ms)": 119, "Link candidates p95 (ms)": 49, "Index build (min)": 81, "Leaks": 0},
        "spend_usd": 0, "duration_s": None, "outcome": "kept",
        "conclusion": "Meaning-only 40% to 100%, ranking 77.8% to 94.1%, same index size, four and a half times the build time.",
        "report": _t("The idea was to make the search by meaning look deeper and use a better connected index. It "
                     "worked: questions found by meaning alone went from 40% to 100% on a million test items, and "
                     "ranking from 77.8% to 94.1%. It was kept."),
        "notes_ref": SIX,
    },
    {
        "started_at": "2026-10-04T16:39:00+03:00", "finished_at": "2026-10-04T17:30:00+03:00",
        "chosen": "Card 1125 change 4: recent items first, from a hot window of 90 days",
        "ideas": [{"idea": "Recent first with hot-window indexes"}, {"idea": "All-time search", "note": "kept"}],
        "why_chosen": "The card proposed a hot partition to make searches faster.",
        "hypothesis": "Searching the last 90 days first is faster without losing answers.",
        "changes": {"summary": "Measured only; recent_first stays off and nothing was partitioned.",
                    "commits": ["b11f6830"], "files": []},
        "benchmark": BENCH, "benchmark_version": "v2, 1,000,000 fictional items",
        "before": {"Search p95 (ms)": 132.2, "Link candidates p95 (ms)": 57.9, "Ranking cases right (%)": 81.5,
                   "Links found (%)": 89.4, "Traversal chains walked": "all"},
        "after": {"Search p95 (ms)": 46.9, "Link candidates p95 (ms)": 40.2, "Ranking cases right (%)": 20.7,
                  "Links found (%)": 75.3, "Traversal chains walked": "none"},
        "spend_usd": 0, "duration_s": None, "outcome": "discarded",
        "conclusion": "Three to four times faster and lost most old answers (20.7% of ranking cases against 81.5%); rejected.",
        "report": _t("The idea was to search recent items first. It was faster (slowest searches 47 ms instead of 132 "
                     "ms) but lost old answers: ranking cases right fell from 81.5% to 20.7%. It was not kept."),
        "notes_ref": SIX,
    },
    {
        "started_at": "2026-10-04T16:42:00+03:00", "finished_at": "2026-10-04T17:35:00+03:00",
        "chosen": "Card 1125 change 5: an idempotent one-at-a-time queue that recovers a stopped worker's jobs, and area counts by trigger",
        "ideas": [{"idea": "One job per item per ask, claimed once, released when its worker dies", "note": "chosen"},
                  {"idea": "Area counts kept by trigger instead of counting every item", "note": "chosen"}],
        "why_chosen": "The same item asked for twice made two X-ray calls, and a stopped worker's items waited 10 minutes.",
        "hypothesis": "No double work, quick recovery, and a faster queue.",
        "changes": {"summary": "Queue dedupe and claim, worker.release_dead, migration 0074; area counts table, migration 0075.",
                    "commits": ["a8f284cb", "7185f7ac", "507b566e"], "files": ["rouh/synapse/worker.py", "rouh/synapse/ingest.py"]},
        "benchmark": BENCH + " --writes", "benchmark_version": "v2, 100,000 and 1,000,000 fictional items",
        "before": {"X-ray calls for the same 20 items asked twice": 40, "Stopped worker's 20 items ready in 60 s": 0,
                   "Queue at 1,000,000, 4 workers (items/s)": 3.1, "Queue at 100,000 (items/s)": 19.5},
        "after": {"X-ray calls for the same 20 items asked twice": 20, "Stopped worker's 20 items ready in 60 s": 20,
                  "Queue at 1,000,000, 4 workers (items/s)": 31.0, "Queue at 100,000 (items/s)": 34.2},
        "spend_usd": 0, "duration_s": None, "outcome": "kept",
        "conclusion": "No double X-ray calls, a stopped worker's items ready in under a second, queue ten times faster at 1,000,000.",
        "report": _t("The idea was to make the work queue do each item once and pick up after a stopped worker. It "
                     "worked: 20 items asked for twice made 20 calls instead of 40, and the queue ran 31 items a "
                     "second instead of 3.1 on a million test items. It was kept."),
        "notes_ref": SIX,
    },
    {
        "started_at": "2026-10-04T17:39:00+03:00", "finished_at": "2026-10-04T19:30:00+03:00",
        "chosen": "Card 1125 change 6: the scale gate (synapse_bench --gate)",
        "ideas": [{"idea": "A gate that measures 1, 10 and 50 million and says PASS, FAIL or NOT MEASURED", "note": "chosen"}],
        "why_chosen": "The card's targets needed one command that says whether a size passes.",
        "hypothesis": "1,000,000 items pass the card's targets.",
        "changes": {"summary": "synapse_bench --gate; sizes the disk or memory cannot take are never started.",
                    "commits": ["305c3441"], "files": ["rouh/synapse/benchmark.py", "rouh/management/commands/synapse_bench.py"]},
        "benchmark": BENCH + " --gate", "benchmark_version": "v2, final code bcb18538",
        "before": {},
        "after": {"1,000,000: link candidates p95 (ms, target 50)": 48.9, "1,000,000: search p95 (ms, target 300)": 112.4,
                  "1,000,000: leaks": 0, "1,000,000": "PASS (narrowly)", "10,000,000": "not measured (disk)",
                  "50,000,000": "not measured (disk)"},
        "spend_usd": 0, "duration_s": None, "outcome": "kept",
        "conclusion": "1,000,000 passes narrowly; 10 and 50 million need several hundred GB more disk.",
        "report": _t("The idea was one command that says whether Synapse meets its speed targets at a given size. "
                     "It was built: a million test items pass, link lookups at 48.9 ms against a 50 ms target, "
                     "searches at 112 ms against 300 ms, with no leaks. It was kept."),
        "notes_ref": SIX,
    },
    {
        "started_at": "2026-10-04T20:11:00+03:00", "finished_at": "2026-10-04T21:13:00+03:00",
        "chosen": "pg_search turned on: PostgreSQL restarted with it, and the words list ranks with it by default",
        "ideas": [{"idea": "bm25 in PostgreSQL", "note": "the fallback"}, {"idea": "pg_search preloaded", "note": "chosen by the owner"}],
        "why_chosen": "It ranked best at 100,000 and needed a PostgreSQL restart, which was the owner's call; it was made.",
        "earlier": "Change 1 left pg_search measured best and waiting for this decision.",
        "hypothesis": "pg_search ranks more cases right and searches faster than bm25 in PostgreSQL.",
        "changes": {"summary": "shared_preload_libraries = pg_search, the extension installed by postgres, migration "
                               "0078's column and index, pg_search as the default words backend.",
                    "commits": ["592bd98e", "ce65a68e"], "files": ["rouh/synapse/search.py", "rouh/migrations/0078_synapse_pg_search.py"]},
        "benchmark": BENCH, "benchmark_version": "v2, 100,000 fictional items",
        "before": {"Ranking cases right (%)": 92.6, "Search p95 (ms)": 61.9, "Link candidates p95 (ms)": 33.9, "Leaks": 0},
        "after": {"Ranking cases right (%)": 97.8, "Search p95 (ms)": 39.9, "Link candidates p95 (ms)": 30.6, "Leaks": 0},
        "spend_usd": 0, "duration_s": None, "outcome": "kept",
        "decision": {"question": "Restart PostgreSQL with pg_search preloaded?",
                     "options": [{"label": "Yes", "detail": "a 2-second restart; the meeting library's worker restarts by itself"},
                                 {"label": "No", "detail": "stay on bm25 in PostgreSQL"}],
                     "answer": "Yes, on 4 October 2026"},
        "conclusion": "Ranking 92.6% to 97.8% and search p95 62 to 40 ms at 100,000; back in 2 seconds after the restart.",
        "report": _t("The idea was to turn on a better search engine inside the database (pg_search), which needed "
                     "a restart you approved. It worked: ranking cases right went from 92.6% to 97.8% and the "
                     "slowest searches from 62 ms to 40 ms on 100,000 test items. It was kept."),
        "notes_ref": SIX,
    },
    {
        "started_at": "2026-10-04T20:20:00+03:00", "finished_at": "2026-10-04T21:12:00+03:00",
        "chosen": "An item's rarest words found by stemming its text once (the 'next step' of change 6)",
        "ideas": [{"idea": "Keep each item's rarest words when it is stored", "note": "would only move the cost"},
                  {"idea": "Stem the item's text once instead of each word form", "note": "built and measured"}],
        "why_chosen": "Finding an item's rarest words was 47 ms of link candidates' p95 at 1,000,000.",
        "hypothesis": "Stemming once makes the rare-word step faster without changing which words it finds.",
        "changes": {"summary": "Built behind a Tune setting, measured, then taken out again.",
                    "commits": ["642bf1cd", "3f655ce3"], "files": ["rouh/synapse/search.py"]},
        "benchmark": BENCH, "benchmark_version": "v2, 100,000 fictional items",
        "before": {"Rare-word step p50 (ms)": 1.2, "Rare-word step p95 (ms)": 3},
        "after": {"Rare-word step p50 (ms)": 1.2, "Rare-word step p95 (ms)": 3, "Same rare words": "289 of 300 items"},
        "spend_usd": 0, "duration_s": None, "outcome": "discarded",
        "conclusion": "The same time and nearly the same words; with no gain it was taken out.",
        "report": _t("The idea was a quicker way to find each item's rarest words. It made no difference (1.2 ms "
                     "either way on 100,000 test items), so it was taken out again."),
        "notes_ref": SIX,
    },
    {
        "started_at": "2026-10-05T02:00:00+03:00", "finished_at": "2026-10-05T04:32:00+03:00",
        "chosen": "Areas are never the medium (D83): the X-ray call is told so, and code refuses kind-only names",
        "ideas": [{"idea": "Tell the X-ray call an area is part of life or work", "note": "chosen"},
                  {"idea": "A code check that refuses names made of medium words", "note": "chosen (area_not_media)"}],
        "why_chosen": "Rouh's inbox import put all 104 emails in one area called Email.",
        "hypothesis": "Mail is filed by subject, not by being mail.",
        "changes": {"summary": "The X-ray instructions and area_not_media in Tune > Map.", "commits": ["47f8b02b"],
                    "files": ["rouh/synapse/ingest.py", "rouh/synapse/numbers.py"]},
        "benchmark": "areas-all-mail-test.py (18 fictional emails)", "benchmark_version": "5 Oct 2026",
        "before": {"Areas made": 2, "Emails in one catch-all area": "14 of 18", "Test": "fails"},
        "after": {"Areas made": 5, "Test": "passes"},
        "spend_usd": None, "duration_s": None, "outcome": "kept",
        "decision": {"question": "Should the 3,026 items in Master's area Projects be read again so they get real areas?",
                     "options": [{"label": "Yes", "detail": "about $3 of model calls"},
                                 {"label": "No", "detail": "they keep the area Projects; new items are filed properly"}]},
        "conclusion": "The old code made 2 areas with 14 of 18 emails in one; the new code makes 5 real areas.",
        "report": _t("The idea was to stop Synapse filing everything under a catch-all area like Email. It worked on "
                     "18 test emails: 5 real areas instead of 2, with 14 of 18 in one. It was kept. One decision is "
                     "yours: whether to read the 3,026 items in the area Projects again, for about $3."),
        "notes_ref": NOTES + "85-02.areas-seeds-and-the-map.md",
    },
    {
        "started_at": "2026-10-05T02:30:00+03:00", "finished_at": "2026-10-05T04:32:00+03:00",
        "chosen": "A seed lookup on every message (D84): Master searched by words and meaning, no walk, no model",
        "ideas": [{"idea": "Seeds on every message, held to a cosine bar", "note": "chosen"},
                  {"idea": "Only when Rouh calls synapse_query", "note": "as it was"}],
        "why_chosen": "The owner asked whether every message should be supported by an immediate Synapse search.",
        "hypothesis": "Strong matches help the turn and cost almost nothing.",
        "changes": {"summary": "rouh/synapse/messageseeds.py; seeds at cosine 0.60 or more, at most 3 and 600 tokens, "
                               "the turn waits at most 100 ms.", "commits": ["47f8b02b"],
                    "files": ["rouh/synapse/messageseeds.py", "rouh/brain.py"]},
        "benchmark": "200 of the owner's real messages, judged by Claude Opus 5", "benchmark_version": "5 Oct 2026",
        "before": {},
        "after": {"Messages that got seeds (of 200)": 79, "Seeds useful (%)": 66, "Seeds noise (%)": 10,
                  "Lookup median (ms)": 232, "Lookup p95 (ms)": 329, "Search alone median (ms)": 26},
        "spend_usd": None, "duration_s": None, "outcome": "kept",
        "decision": {"question": "How long may a turn wait for the seeds?",
                     "options": [{"label": "100 ms", "detail": "as now; they almost never reach the first request"},
                                 {"label": "250 ms", "detail": "78% reach the first request"},
                                 {"label": "350 ms", "detail": "97% reach the first request"}]},
        "conclusion": "Two thirds of seeds useful; Voyage's vector is most of the time, so they usually arrive after the first request.",
        "report": _t("The idea was to look up every message you send in Synapse Master before Rouh answers. Of 200 "
                     "past messages, 79 got matches and two thirds of those were useful. It was kept. One decision "
                     "is yours: how long a turn may wait for them, 100 ms as now, 250 ms or 350 ms."),
        "notes_ref": NOTES + "85-02.areas-seeds-and-the-map.md",
    },
    {
        "started_at": "2026-10-05T03:00:00+03:00", "finished_at": "2026-10-05T04:32:00+03:00",
        "chosen": "The map measured on and off (D85), and skipping the search when the map answers",
        "ideas": [{"idea": "Map on"}, {"idea": "Map off"}, {"idea": "Map on, skipping the search when it answers"}],
        "why_chosen": "The owner asked whether the map is worth having at a million items.",
        "hypothesis": "The map helps answers, and skipping the search when it answers saves time safely.",
        "changes": {"summary": "map_on and map_skip_search in Tune > Map; skipping stays off.", "commits": ["47f8b02b"],
                    "files": ["rouh/synapse/recall.py", "rouh/synapse/numbers.py"]},
        "benchmark": "Evaluate: Northwind (8) and Maria (11), 3 passes each", "benchmark_version": "5 Oct 2026",
        "before": {"Northwind answer (%), map off": 90.5, "Maria recall (%), map off": 90.7, "Maria answer (%), map off": 86.1},
        "after": {"Northwind answer (%), map on": 97.6, "Maria recall (%), map on": 78.4, "Maria answer (%), map on": 88.0,
                  "Searches skipped, all answered wrong": 3},
        "spend_usd": None, "duration_s": None, "outcome": "kept",
        "conclusion": "The map stays (answers a little better, within noise); skipping the search was wrong all 3 times, so it is off.",
        "report": _t("The idea was to check whether Synapse's small map of your life earns its place. Answers were a "
                     "little better with it (Northwind 90.5% to 97.6%), and skipping the search when the map seemed "
                     "to answer was wrong all 3 times. The map was kept and skipping stays off."),
        "notes_ref": NOTES + "85-02.areas-seeds-and-the-map.md",
    },
]


def backfill(org_id: str, user_id: str) -> int:
    """The rows task 85's notes document, once per person: nothing when any backfilled row is there already."""
    if not ready():
        return 0
    if db.value("SELECT EXISTS (SELECT 1 FROM synapse.attempt WHERE org_id = %s AND user_id = %s AND source = 'backfilled')",
                (str(org_id), str(user_id))):
        return 0
    made = 0
    for spec in BACKFILL:
        row = start(org_id, user_id, mode="full", source="backfilled", chosen=spec["chosen"])
        fields = {k: v for k, v in spec.items() if k not in ("chosen",)}
        fields.setdefault("decision", {})
        update(org_id, user_id, row["number"], fields)
        made += 1
    log.info("backfilled %d Synapse attempts for %s/%s from task 85's notes", made, org_id, user_id)
    return made


def epoch(value) -> float | None:
    """A timestamp column as seconds since 1970, for the brief, which keeps times that way."""
    return value.timestamp() if value else None
