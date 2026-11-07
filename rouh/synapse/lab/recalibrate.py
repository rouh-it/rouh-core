"""Recalibrating before an idea, so that every night tries one (Petar, 15 October 2026, fr_8b9087ffb325).

Until then a night whose Synapse code had changed since the last judged night only measured main and tried
nothing: nine of the first eleven nightly attempts (#19, #20 and #23 to #29) were such measuring nights,
because Petar changes something under `rouh/synapse/` nearly every day. He asked that every night try a gene
mutation, and that a night whose code changed recalibrate first and then go on to its idea.

**Why the split was there, and what of it still holds.** It was never about trusting a baseline measured the
same night: the opposite holds. Unjudged recall gave the same figure on both passes of the same code every
night, and drifted up to two points from one night to the next on code that found the same memory, from
outside `rouh/synapse` (#25 to #29), so main's unjudged passes are measured the same night either way. The
judge wobbles about four points of answer correctness on identical packs (#26 +4.1, #27 -4.1), whether the
two judged passes are a night apart or an hour. The split was the budget: a judged pass is about $3.50 and a
night has $5, so only one pass a night could be judged, and a changed code took it.

**What a recalibration is, then** (`decide`):

- main's Synapse code is run unjudged twice, and the last judged code (`plan`: the commit whose `rouh/synapse`
  tree it was) is run unjudged beside it, the same night: free, about a minute;
- if every question finds the same memory on both (`same_memory`), the code change is off the benchmark's
  path, and the last judged figures are carried over as tonight's judged `before`: nothing is judged, and the
  idea's own judged pass fits the night's $5 as it always did. Every changed-code night from #23 to #29 found
  the same memory on all 103 questions (#23 on 102, one tied item swapping run to run);
- if the memory differs, main is judged once, as before, and that is the `before`. The idea is still tried,
  and its own judged pass makes the night about $7, which the brief allows for this case and the report says;
- if main's passes look wrong (`problems`: a question failed, something leaked, the passes disagree with
  each other, recall fell far below the last judged night's), nothing is judged against them: the night
  records what it measured and why it stopped, and that is the only measuring night there is now.

Read only: it writes nothing; the worker writes what `decide` returns onto its attempt (`synapse_attempt`).
"""
from __future__ import annotations

import json
from pathlib import Path

from ... import gitutil
from .. import evalbench
from . import improvements

REPO = Path(__file__).resolve().parent.parent.parent.parent

#: Questions whose memory may change from one pass of the same code to the next (a tie between two items
#: swapping, #23), left out of the comparison; more than this and the passes are not steady enough to compare.
UNSTEADY_MAX = 3
#: How far the packs' average size may differ between the two codes and still be the same memory.
TOKENS_TOLERANCE = 0.01
#: Recall this far below the last judged night's unjudged recall means main looks wrong, not drifted.
RECALL_DROP_MAX = 0.05
#: Outcomes whose `after` describes main as it was that night; for the others main is the `before`.
MAIN_IS_AFTER = ("kept", "kept_experience", "baseline")


# --- what tonight needs --------------------------------------------------------------------------

def _judged(m) -> bool:
    return isinstance(m, dict) and m.get("answer") is not None and bool(m.get("_synapse_code"))


def judged_for(org_id: str, user_id: str, code: str) -> dict | None:
    """The newest attempt whose judged measures are of this very code: {"attempt", "side", "measures"}."""
    if not code or code == "unknown" or code.endswith("+changes"):
        return None
    for row in improvements.listing(org_id, user_id):
        if row.get("source") == "backfilled" or row.get("outcome") in ("running", "failed"):
            continue
        for side in ("after", "before"):
            m = row.get(side) or {}
            if _judged(m) and m["_synapse_code"] == code:
                return {"attempt": int(row["number"]), "side": side, "measures": m}
    return None


def last_judged(org_id: str, user_id: str) -> dict | None:
    """The newest night's judged measures of main, whatever its code: {"attempt", "side", "measures"}."""
    for row in improvements.listing(org_id, user_id):
        if row.get("source") == "backfilled" or row.get("outcome") in ("running", "failed"):
            continue
        side = "after" if row.get("outcome") in MAIN_IS_AFTER else "before"
        m = row.get(side) or {}
        if _judged(m):
            return {"attempt": int(row["number"]), "side": side, "measures": m}
    return None


def _git(*args: str, repo: Path = REPO) -> str:
    try:
        got = gitutil.run(repo, *args, timeout=30, safe_directory=False)
    except Exception:  # noqa: BLE001 - no git, no history to read
        return ""
    return got.stdout.strip() if got.returncode == 0 else ""


def commit_for(code: str, *, repo: Path = REPO, depth: int = 400) -> str:
    """The newest commit on this checkout's history whose `rouh/synapse` tree is `code`, or ""."""
    if not code or code == "unknown" or code.endswith("+changes"):
        return ""
    for sha in _git("log", "--format=%H", f"-n{depth}", "HEAD", "--", "rouh/synapse", repo=repo).split():
        # The tree a commit leaves behind is the one it changed to; the commit before the next change keeps it.
        if _git("rev-parse", f"{sha}:rouh/synapse", repo=repo).startswith(code):
            return sha
    return ""


def plan(org_id: str, user_id: str, *, repo: Path = REPO) -> dict:
    """Whether tonight recalibrates before its idea, and against what. Read only."""
    code = evalbench.synapse_code()
    same = judged_for(org_id, user_id, code)
    if same:
        return {"recalibrate": False, "code": code, "judged_by": same["attempt"], "side": same["side"],
                "words": f"Main's Synapse code {code} was judged by attempt {same['attempt']} ({same['side']}): "
                         "no recalibration tonight; those judged figures are the before."}
    last = last_judged(org_id, user_id)
    if not last:
        return {"recalibrate": True, "code": code, "from_attempt": None, "from_code": "", "from_commit": "",
                "commits": [], "words": "Nothing has been judged yet: judge main once as the before, then try an idea."}
    from_code = last["measures"]["_synapse_code"]
    sha = commit_for(from_code, repo=repo)
    commits = _git("log", "--format=%h %s", f"{sha}..HEAD", "--", "rouh/synapse", repo=repo).splitlines() if sha else []
    words = (f"Main's Synapse code {code} has not been judged. The last judged is attempt {last['attempt']}, "
             f"code {from_code}" + (f", which is commit {sha[:8]}" if sha else ", whose commit is not in this "
                                    "checkout's history") + ". ")
    if commits:
        words += f"{len(commits)} commit{'s' if len(commits) != 1 else ''} since changed rouh/synapse: " + \
                 "; ".join(commits[:8]) + ("; ..." if len(commits) > 8 else "") + ". "
    words += ("Tonight recalibrates first, then tries an idea: run that commit's code unjudged beside main's, then "
              "synapse_nightly recalibrate." if sha else
              "Tonight recalibrates first by judging main once, then tries an idea.")
    return {"recalibrate": True, "code": code, "from_attempt": last["attempt"], "from_side": last["side"],
            "from_code": from_code, "from_commit": sha, "commits": commits, "words": words}


# --- the passes ----------------------------------------------------------------------------------

def passes_of(path: str | Path) -> list[dict]:
    """The passes in a file `synapse_benchmark run --json` wrote."""
    got = json.loads(Path(path).read_text())
    return list(got.get("passes") or []) if isinstance(got, dict) else list(got)


def _memory(passes: list[dict]) -> tuple[dict, set, int]:
    """Each question's gold found, as the set of distinct answers over the passes; and the questions that failed."""
    seen: dict = {}
    failed = set()
    for p in passes:
        for r in p.get("rows") or []:
            q = r.get("question")
            if r.get("error"):
                failed.add(q)
                continue
            seen.setdefault(q, set()).add(tuple(sorted(r.get("gold_found") or [])))
    return seen, failed, len(passes)


def _mean(passes: list[dict], key: str):
    vals = [float(p["summary"]["combined"][key]) for p in passes
            if (p.get("summary") or {}).get("combined", {}).get(key) is not None]
    return sum(vals) / len(vals) if vals else None


def unsteady(passes: list[dict]) -> list:
    seen, _, _ = _memory(passes)
    return sorted((q for q, g in seen.items() if len(g) > 1), key=str)


def same_memory(old: list[dict], new: list[dict]) -> dict:
    """Whether two codes found the same memory for every question: the same gold items in every steady question,
    nothing failing, no leak either side has that the other has not, and packs of the same size."""
    a, a_failed, _ = _memory(old)
    b, b_failed, _ = _memory(new)
    shaky = sorted({q for q, g in a.items() if len(g) > 1} | {q for q, g in b.items() if len(g) > 1}, key=str)
    both = sorted(set(a) & set(b), key=str)
    differ = [q for q in both if q not in shaky and a[q] != b[q]]
    missing = sorted(set(a) ^ set(b), key=str)
    t_old, t_new = _mean(old, "tokens"), _mean(new, "tokens")
    tokens_ok = t_old is None or t_new is None or abs(t_new - t_old) <= TOKENS_TOLERANCE * max(t_old, 1.0)
    leaks_ok = (_mean(old, "leaks") or 0) == (_mean(new, "leaks") or 0)
    n = len(set(a) | set(b) | a_failed | b_failed)
    matching = len([q for q in both if q not in shaky and a[q] == b[q]])
    same = (not differ and not missing and not a_failed and not b_failed and len(shaky) <= UNSTEADY_MAX
            and tokens_ok and leaks_ok and bool(both))
    words = f"the same memory for {matching} of {n} questions"
    if shaky:
        words += f", {len(shaky)} left out as unsteady from one pass to the next"
    if differ:
        words += f"; {len(differ)} found different memory"
    if a_failed or b_failed:
        words += f"; {len(a_failed | b_failed)} failed"
    if not tokens_ok:
        words += f"; packs of {t_old:,.0f} against {t_new:,.0f} tokens"
    if not leaks_ok:
        words += "; the leaks differ"
    return {"same": same, "questions": n, "matching": matching, "differ": differ, "unsteady": shaky,
            "missing": missing, "failed": sorted(a_failed | b_failed, key=str), "tokens_old": t_old,
            "tokens_new": t_new, "words": words}


def problems(new: list[dict], last: dict | None = None) -> list[str]:
    """What makes main's passes untrustworthy as a before, in words; empty when they are sound."""
    out = []
    if not new:
        return ["no pass of main was measured"]
    _, failed, _ = _memory(new)
    if failed:
        out.append(f"{len(failed)} question{'s' if len(failed) != 1 else ''} failed in main's passes")
    leaks = max(float((p.get("summary") or {}).get("combined", {}).get("leaks") or 0) for p in new)
    if leaks:
        out.append(f"main leaked {leaks:g} item{'s' if leaks != 1 else ''} to an asker who may not read them")
    shaky = unsteady(new)
    if len(shaky) > UNSTEADY_MAX:
        out.append(f"main's own passes found different memory for {len(shaky)} questions, so they are not steady")
    if any(p.get("judged") for p in new):
        out.append("main's unjudged passes include a judged one; run them with --no-judge")
    was = ((last or {}).get("measures") or {}).get("_unjudged", {}).get("recall")
    now = _mean(new, "recall")
    if was is not None and now is not None and float(was) - now > RECALL_DROP_MAX:
        out.append(f"main's recall fell from {float(was) * 100:.1f}% at attempt {last['attempt']} to {now * 100:.1f}% "
                   f"unjudged, more than {RECALL_DROP_MAX * 100:.0f} points: something on the benchmark's path broke")
    return out


def _spend(passes: list[dict]) -> float:
    return round(sum(float(p.get("spend_usd") or 0) for p in passes), 4)


def decide(org_id: str, user_id: str, *, main: list[dict], old: list[dict] | None = None,
           judged: dict | None = None, repo: Path = REPO) -> dict:
    """Tonight's recalibration, from main's unjudged passes, the last judged code's unjudged passes beside them,
    and main's judged pass when there is one. Returns {"verdict", "before", "recalibrated", "words"}:

    - verdict `none`: main's code was judged already; `before` is those figures, with tonight's passes beside;
    - `carried`: the same memory, so the last judged figures are the before, nothing judged tonight;
    - `judge_main`: the memory differs (or there was nothing to compare), so main is judged once first; run
      this again with `judged` to get the before;
    - `judged`: main's judged pass is the before;
    - `off`: main's passes look wrong; `recalibrated.problem` says why. No idea is judged against them.
    """
    p = plan(org_id, user_id, repo=repo)
    pooled = evalbench.pooled(main) if main else {}
    trouble = problems(main, last_judged(org_id, user_id))
    rec = {k: p.get(k) for k in ("code", "from_attempt", "from_code", "from_commit", "commits")}
    rec["needed"] = bool(p["recalibrate"])
    rec["spend_usd"] = _spend(main) + _spend(old or []) + (float(judged.get("spend_usd") or 0) if judged else 0)
    if not p["recalibrate"]:
        same = judged_for(org_id, user_id, p["code"])
        before = {**{k: v for k, v in same["measures"].items() if k != "_unjudged"}, "_unjudged": pooled,
                  "_judged_from": f"attempt {same['attempt']} {same['side']} (judged on code {p['code']})"}
        if trouble:
            return {"verdict": "off", "before": before, "words": "Main's passes look wrong: " + "; ".join(trouble) + ".",
                    "recalibrated": {**rec, "how": "none", "trusted": False, "problem": "; ".join(trouble)}}
        return {"verdict": "none", "before": before, "recalibrated": None, "words": p["words"]}
    if trouble:
        return {"verdict": "off", "before": {"_unjudged": pooled},
                "recalibrated": {**rec, "how": "failed", "trusted": False, "problem": "; ".join(trouble)},
                "words": "The recalibration looks wrong, so no idea may be judged against it: " + "; ".join(trouble) + "."}
    cmp = same_memory(old, main) if old else None
    if cmp:
        rec["same_memory"] = cmp["words"]
    if judged:
        if not judged.get("judged"):
            raise ValueError("The judged pass given was not judged.")
        jt = problems([judged])
        jt = [t for t in jt if "judged one" not in t]
        m = evalbench.measures(judged)
        if jt or m.get("answer") is None:
            why = "; ".join(jt) or "the judged pass has no answer correctness"
            return {"verdict": "off", "before": {"_unjudged": pooled, "_judged_try": m},
                    "recalibrated": {**rec, "how": "failed", "trusted": False, "problem": why},
                    "words": f"Main's judged pass looks wrong, so no idea may be judged against it: {why}."}
        rec.update(how="judged", trusted=True, problem="")
        return {"verdict": "judged", "before": {**m, "_unjudged": pooled, "_recalibrated": rec},
                "recalibrated": rec, "words": f"Recalibrated by judging main once (${rec['spend_usd']:.2f} so far): "
                                               "that is the before. Now try an idea."}
    if cmp:
        if cmp["same"]:
            last = judged_for(org_id, user_id, p["from_code"]) or last_judged(org_id, user_id)
            before = {k: v for k, v in last["measures"].items() if k != "_unjudged"}
            rec.update(how="carried", trusted=True, problem="")
            before.update({"_unjudged": pooled, "_synapse_code": p["code"], "_recalibrated": rec,
                           "_judged_from": f"attempt {last['attempt']} {last['side']} (judged on code {p['from_code']}; "
                                           f"main's code {p['code']} found {cmp['words']})"})
            return {"verdict": "carried", "before": before, "recalibrated": rec,
                    "words": f"Recalibrated: main and the last judged code found {cmp['words']}, so attempt "
                             f"{last['attempt']}'s judged figures are the before, and nothing is judged for it. "
                             "Now try an idea."}
        return {"verdict": "judge_main", "before": {"_unjudged": pooled}, "recalibrated": {**rec, "how": "judged"},
                "words": f"Main and the last judged code found {cmp['words']}: judge main once (--judged), then "
                         "run this again."}
    return {"verdict": "judge_main", "before": {"_unjudged": pooled}, "recalibrated": {**rec, "how": "judged"},
            "words": ("There is no earlier code to compare with" if not p.get("from_commit") else
                      "The last judged code was not run beside main") + ": judge main once (--judged), then run this "
                     "again." + ("" if not p.get("from_commit") else f" (Or run {p['from_commit'][:8]}'s code unjudged "
                                 "and give it as --old: it is free.)")}


def words_of(rec: dict | None) -> str:
    """A recalibration in one plain sentence, for the morning paragraph and the page; "" when there was none."""
    if not rec or not rec.get("needed"):
        return ""
    since = f" since attempt {rec['from_attempt']} judged it" if rec.get("from_attempt") else ""
    if rec.get("how") == "carried":
        return (f"Synapse's code had changed{since}, so it was recalibrated first: the new code found the same memory "
                "as the old, so the last judged figures still held and nothing extra was spent.")
    if rec.get("how") == "judged":
        return (f"Synapse's code had changed{since} in a way the test notices, so it was recalibrated first: the "
                f"current version was measured and graded afresh (${float(rec.get('spend_usd') or 0):.2f}).")
    return (f"Synapse's code had changed{since}, and the recalibration did not hold up"
            + (f": {rec['problem']}" if rec.get("problem") else "") + ".")
