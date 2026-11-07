"""Synapse's fixed benchmark: 103 questions on a frozen copy of Synapse Master (Petar, 5 October 2026).

It serves one goal: when Petar writes a message in any Rouh chat, Rouh already has what Synapse Master knows
about it, quickly and accurately. Petar chose the measure himself:

- **The inbox set, 53 questions**: the Rouh inbox evaluation of 4 October 2026, the 50 written from Rouh's mail
  and files plus his own 20 to 22 (`85-02.rouh-inbox-evaluation-set.md`). Its dataset was deleted that night;
  Master holds the same mail and files, so each gold item is remapped to its Master item, by Gmail message id
  for a mail and by sha256 for a file. With all of Master competing in the search it is harder than it was, so
  the earlier inbox-only scores (`REFERENCE`) are shown beside it for reference, never as the figure to beat.
- **The Master set, 50 questions** over what Master holds besides mail: tasks and their files, chats and cards,
  people, calendar, decisions and notes, worded the way Petar types in a chat
  (`source-code/synapse-master-eval-questions.json`).

Both sets live in one file, `synapse_eval_v1.json`, gold named by source key, and run against one frozen
dataset, "Benchmark: Synapse Master (frozen)" (`snapshot.py`), which nothing syncs or changes. The questions are
the owner's own (their mail, tasks and people), so the file is kept outside the repository since 20 October 2026:
`<ROUH_DATA_DIR>/synapse/benchmarks/synapse_eval_v1.json`, or wherever `SYNAPSE_BENCHMARK_FILE` says (`MANIFEST`).
An installation without it has no benchmark, and says so.

**What is measured** is the lab's own evaluation (`evaluate.ask_one`): the question goes through
`recall.run`, the path `synapse_query` takes in every chat, and a judge of another family reads the answer
(D77). For each set and both together: recall of the gold items in the pack, citation, answer correctness,
time to pack p50 and p95, tokens the pack adds to the turn, cost per question, permission leaks (must stay 0),
and how many questions were wholly right.

**Never moved by a night.** The judge's rules and the key facts are pinned here (`PINNED`: the judge's v2
rules, the current key facts), and every result carries a fingerprint of the questions, this file and the
evaluation's code (`fingerprint`), and the model that judged (`judge_model`). A night that changes any of them has
changed the benchmark: an attempt of its own. The judge's model is the Models page's for Synapse's judge, like
every model Rouh asks since 18 October 2026 (Petar: "No exceptions"); until then it was pinned here to Claude
Opus 5, so a result judged by another model is not compared with one judged by it.

**Spend.** A judged pass of all 103 cost $3.51 on 5 October 2026, nearly all of it the judge; an unjudged pass
(`run(judge=False)`: recall, time, tokens, leaks, no answer) costs a hundredth of a cent. Under a $5 night only one
pass can be judged, so the brief says how a night spends it (`nightly_brief.md`). Time differs between the two kinds
of pass (an unjudged pack took about 1.1 s at the median against 0.66 s), so time is compared like with like.
"""
from __future__ import annotations

import concurrent.futures
import hashlib
import json
import statistics
import subprocess
import time
from pathlib import Path

from . import datasets, db, evaluate, people, snapshot
from ..config import _env, config

HERE = Path(__file__).resolve().parent


def _manifest() -> Path:
    """Where the owner's benchmark is: never in the repository, because its questions are their own life."""
    named = _env("SYNAPSE_BENCHMARK_FILE")
    if named:
        return Path(named)
    return Path(config.data_dir) / "synapse" / "benchmarks" / "synapse_eval_v1.json"


MANIFEST = _manifest()
NAME = "synapse_eval"
SETS = ("inbox", "master")

#: The judge's rules and the facts it judges against, pinned so no Tune change or night moves the measure.
#: Its model is the Models page's (Synapse's judge), written on every result as `judge_model`.
PINNED = {"judge_version": "v2", "key_facts": "current"}
PARALLEL = 4

#: The newest inbox-only run before this benchmark, for reference (85-02.rouh-inbox-evaluation-set.md, run
#: 01a105ea, configuration "4 Both": Claude Opus 5 judge, facts one claim to a line; 53 questions on the
#: Rouh inbox dataset alone). Not the figure to beat: the same questions now search all of Master.
REFERENCE = {"run": "01a105ea-e838-7950-848b-732dc61e2c73", "label": "Rouh inbox alone, 4 October 2026",
             "recall": 0.973, "citation": 0.980, "answer": 0.794, "p50_ms": 540, "p95_ms": 580,
             "cost_per_question_usd": 0.0012, "leaks": 0}


class MemTrace:
    """A trace kept in memory, for the judge's calls: their cost is counted, nothing is written."""

    def __init__(self, dataset_id: str) -> None:
        self.dataset_id, self.id, self.calls = str(dataset_id), None, []

    def call(self, **kw) -> dict:
        self.calls.append(kw)
        return {}

    def cost(self) -> float:
        return round(sum(float(c.get("cost") or 0) for c in self.calls), 6)


# --- the benchmark itself ----------------------------------------------------------------------

def load() -> dict:
    if not MANIFEST.is_file():
        raise RuntimeError(f"There is no Synapse benchmark on this installation: {MANIFEST} is not there "
                           "(SYNAPSE_BENCHMARK_FILE names another place).")
    return json.loads(MANIFEST.read_text())


def fingerprint() -> str:
    """The questions, this file and the evaluation's code: what a night must leave exactly as it found them."""
    h = hashlib.sha256()
    for p in (MANIFEST, Path(__file__), HERE / "evaluate.py"):
        h.update(p.read_bytes() if p.is_file() else b"")
    return h.hexdigest()[:16]


def synapse_code() -> str:
    """Which Synapse code a pass measured: the git tree of `rouh/synapse` at HEAD, and `+changes` when the working
    tree differs from it. Two passes with the same value measured the same code."""
    repo = HERE.parent.parent
    try:
        tree = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD:rouh/synapse"], capture_output=True,
                              text=True, timeout=10).stdout.strip()
        dirty = subprocess.run(["git", "-C", str(repo), "status", "--porcelain", "--", "rouh/synapse"],
                               capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:  # noqa: BLE001 - a checkout without git measures unknown code
        return "unknown"
    return (tree[:12] or "unknown") + ("+changes" if dirty else "")


def frozen(org_id: str, user_id: str) -> dict:
    ds = snapshot.existing(org_id, user_id)
    if not ds:
        raise RuntimeError(f'There is no "{snapshot.NAME}" yet: manage.py synapse_benchmark freeze makes it.')
    return ds


def install(ds: dict, bench: dict | None = None) -> dict:
    """The benchmark's questions as the frozen dataset's evaluation set, once. Refuses a gold key not in it."""
    bench = bench or load()
    have = db.value("SELECT count(*) FROM synapse.eval_question WHERE dataset_id = %s", (ds["id"],)) or 0
    if have:
        return {"installed": 0, "there": int(have)}
    keys = {k for st in SETS for q in bench["sets"][st] for k in q["gold"] + ([q["context"]] if q.get("context") else [])}
    found = {r["source_key"] for r in db.rows("SELECT source_key FROM synapse.item WHERE dataset_id = %s AND "
                                              "source_key = ANY(%s)", (ds["id"], sorted(keys)))}
    missing = sorted(keys - found)
    if missing:
        raise ValueError("Gold items not in the frozen dataset: " + ", ".join(missing))
    n = 0
    for st in SETS:
        for q in bench["sets"][st]:
            asker = q.get("asker") or ""
            if asker and people.asker_id(ds, asker).startswith("nobody:"):
                raise ValueError(f"{asker} is nobody in the frozen dataset's people, so question {q['id']} could "
                                 "not be asked as them.")
            evaluate.add_question(ds, q["q"], gold=q["gold"], facts=q["facts"], asker=asker,
                                  context=q.get("context") or "", forbidden=bool(q.get("forbidden")),
                                  group=f"{st}/{q['grp']}"[:60])
            n += 1
    return {"installed": n, "there": n}


# --- a pass ------------------------------------------------------------------------------------

def _summary(rows: list[dict], s) -> dict:
    out = evaluate._summarise(rows, s)
    ok = [r for r in rows if not r.get("error")]
    toks = [float(r["tokens"]) for r in ok if r.get("tokens") is not None]
    ms = sorted(float(r["ms_pack"]) for r in ok if r.get("ms_pack") is not None)
    right = 0
    for r in ok:
        if r.get("forbidden"):
            right += int(not r.get("leaked"))
        elif r.get("answer_correctness") is not None and r["answer_correctness"] >= 0.999:
            right += 1
    return {"questions": len(rows), "recall": out["recall"], "citation": out["citation"], "answer": out["answer"],
            "right": right if any(r.get("answer_correctness") is not None for r in ok) else None,
            "p50_ms": round(statistics.median(ms), 1) if ms else None,
            "p95_ms": ms[min(len(ms) - 1, int(round(0.95 * (len(ms) - 1))))] if ms else None,
            "tokens": round(sum(toks) / len(toks), 1) if toks else None,
            "handed_tokens": out["handed_tokens"], "numbers_ok": out["numbers_ok"],
            "cost_per_question_usd": out["cost"], "leaks": out["leaks"], "errors": out["errors"]}


def run(org_id: str, user_id: str, *, judge: bool = True, sets: tuple[str, ...] = SETS, only: list[int] | None = None,
        log=None) -> dict:
    """One pass of the benchmark on the frozen dataset, with this checkout's code. Returns the whole result."""
    began = time.time()
    ds = frozen(org_id, user_id)
    bench = load()
    install(ds, bench)
    s = datasets.settings(ds, PINNED)
    config = {"label": "benchmark", "override": dict(PINNED)}
    qs = [q for q in evaluate.questions(ds) if (q.get("grp") or "").split("/", 1)[0] in sets]
    if only:
        qs = [q for q in qs if q["id"] in set(only)]

    def one(q):
        from django.db import connection
        t = MemTrace(ds["id"])
        try:
            row = evaluate.ask_one(ds, s, q, config, t, judge_it=judge)
        except Exception as exc:  # noqa: BLE001 - one question failing is counted, not fatal
            row = {"question": q["id"], "error": f"{type(exc).__name__}: {exc}"[:300]}
        finally:
            connection.close()
        row["set"] = (q.get("grp") or "").split("/", 1)[0]
        row["grp"] = (q.get("grp") or "").split("/", 1)[-1]
        row["judge_spend"] = t.cost()
        return row

    rows = []
    with concurrent.futures.ThreadPoolExecutor(PARALLEL) as pool:
        for r in pool.map(one, qs):
            rows.append(r)
            if log:
                log(f"{r['set']:6} {r.get('question')} recall {r.get('recall')} answer {r.get('answer_correctness')} "
                    f"{int(r.get('ms_pack') or 0)} ms {r.get('error') or ''}")
    summary = {"combined": _summary(rows, s)}
    for st in sets:
        summary[st] = _summary([r for r in rows if r["set"] == st], s)
    spend = round(sum(float(r.get("cost") or 0) + float(r.get("judge_spend") or 0) for r in rows), 4)
    return {"benchmark": NAME, "version": bench["version"], "fingerprint": fingerprint(), "dataset": ds["id"],
            "synapse_code": synapse_code(), "judged": judge, "started_at": began, "seconds": round(time.time() - began, 1), "pinned": PINNED,
            "judge_model": s.judge_model,
            "spend_usd": spend, "summary": summary, "reference": REFERENCE, "rows": rows}


# --- as an attempt's before and after ----------------------------------------------------------

def measures(result: dict) -> dict:
    """A pass's summary, flat: the combined measures as they are, each set's as `inbox.recall` and so on."""
    out: dict = {}
    for part, s in result["summary"].items():
        for k, v in s.items():
            if k in ("questions", "errors") and part != "combined":
                continue
            out[k if part == "combined" else f"{part}.{k}"] = v
    out["_benchmark"] = f"{result['benchmark']} v{result['version']} ({result['fingerprint']})"
    out["_synapse_code"] = result.get("synapse_code") or ""
    return out


def pooled(results: list[dict]) -> dict:
    """Several passes as one before or after: each measure's mean over the passes that have it, and its range."""
    flat = [measures(r) for r in results]
    out: dict = {}
    for k in flat[0]:
        if k.startswith("_"):
            continue
        vals = [f[k] for f in flat if f.get(k) is not None]
        if not vals:
            out[k] = None
            continue
        out[k] = round(sum(vals) / len(vals), 6)
        if len(vals) > 1:
            out[f"_{k}_range"] = [min(vals), max(vals)]
    out["_benchmark"] = flat[0]["_benchmark"] + f", {len(results)} passes ({sum(1 for r in results if r['judged'])} judged)"
    out["_synapse_code"] = flat[0].get("_synapse_code", "")
    return out
