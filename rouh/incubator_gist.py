"""The Incubator's summaries: what Rouh writes once about each idea so a reader gets it at a glance.

Petar, 7 November 2026: "titles are not very meaningful, because they are short, so I need extra
information to quickly ramp me up to speed and different levels of depth". So every idea gets, from its
own words, written once by the model on the Models page's "Summing up the Incubator's ideas" and kept on
the row (`IncubatorIdea.gist`), never on each view:

- `line`: one plain sentence, what this is and why it matters (the list's first level, under the title);
- `problem`, `helps`, `in_use`, `vision`: the problem, who it helps, what it looks like in use, and what
  it would make Rouh at its best (the second level, "At a glance", and the top of the idea's page);
- `size` small, medium or large, with `size_why`: how big a build it is, shown beside the score and never
  part of it (the score has no part for effort, by Petar's choice of 4 November 2026);
- `alike`: the numbers of the ideas it reads as the same thing as.

An idea is summed up a few seconds after it is added (with its score, `incubator_score._drain`), and
Mutations' beat writes any that are missing or whose words changed since (`sweep`), ideas still to be
decided first. The original words are never changed.

Lookalikes (`lookalikes`) are what the model named, joined with the ideas whose words are close
(a TF-IDF cosine over title, line and the start of the text, standard library only), leaving out a pair
already merged or linked, and a pair the person said is not the same (the page's own setting, `apart`).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import re
import threading
import time

log = logging.getLogger("rouh.incubator_gist")

USE = "incubator_gist"
SIZES = ("small", "medium", "large")
BATCH = 8
AT_ONCE = 4
TEXT_MOST = 3500
#: Statuses summed up first by the sweep: the ideas still waiting for a decision.
FIRST = ("new", "triaged", "parked", "go", "in_build")

SYSTEM = """You write short summaries of ideas in the Incubator, the person's one list of ideas for new genes (abilities) and mutations (changes to abilities it has) of Rouh, their personal AI assistant. Rouh runs their mail, calendar, tasks, memory (Synapse), voice, background jobs and its own code. The person decides from your words which ideas to build, so make each idea understandable in seconds by someone who has forgotten it.

Titles are short and often the name of a task, so never repeat the title: say what it is.

For every idea, answer in plain words a college student knows (explain any term in a few words), present tense, no hype, no marketing, no emoji:
- line: one sentence, at most 22 words: what this is and why it matters.
- problem: one or two sentences: what goes wrong or is missing today.
- helps: one short sentence: who it helps and when.
- in_use: one or two sentences: what it looks like in use, as a moment the person would see.
- vision: one sentence: what it makes possible at its best.
- size: small (a day or less of building), medium (a few days) or large (a week or more, or many parts), and size_why: one short reason.
- alike: the ids of other ideas in the whole list that are the same idea said another way, or so close that one should be merged into the other. Only real duplicates, usually none. Never the idea itself.

When the words do not say something, write what they imply and keep it short; never invent facts, names or numbers.

Answer with JSON alone, no other words:
{"ideas": [{"id": "INC-12", "line": "...", "problem": "...", "helps": "...", "in_use": "...", "vision": "...", "size": "small", "size_why": "...", "alike": ["INC-40"]}]}
Every idea you were given must be in the answer, once, by its id."""


def _fingerprint(row) -> str:
    """What a summary was written from: the title and the words. A new one is written when it changes."""
    text = f"{row.title}\n{(row.original or '')[:TEXT_MOST]}"
    return hashlib.sha1(text.encode("utf-8", "ignore")).hexdigest()[:12]


def is_current(row) -> bool:
    g = row.gist or {}
    return bool(g.get("line")) and g.get("for") == _fingerprint(row)


def view(row) -> dict:
    """What the page and the model are given of an idea's summary; {} when there is none yet."""
    g = row.gist or {}
    if not g.get("line"):
        return {}
    return {k: g.get(k) or "" for k in ("line", "problem", "helps", "in_use", "vision", "size", "size_why")} | {
        "stale": g.get("for") != _fingerprint(row), "at": g.get("at"), "model": g.get("model") or ""}


# --- writing them ------------------------------------------------------------------------------------


def _block(row) -> str:
    from . import incubator

    text = row.original or row.title
    if len(text) > TEXT_MOST:
        text = text[:TEXT_MOST] + f"\n[... {len(row.original) - TEXT_MOST:,} more characters]"
    head = [f"### {incubator.code(row.number)}: {row.title}",
            f"Kind: {incubator.KIND_NAMES.get(row.kind, row.kind)}" + (f", of the gene {row.gene}" if row.gene else ""),
            f"Category: {incubator.CATEGORY_NAMES.get(row.category, row.category or 'none')}",
            f"Status: {incubator.STATUS_NAMES.get(row.status, row.status)}",
            "Came from: " + ", ".join(incubator.SOURCE_NAMES.get(s, s) for s in (row.sources or [row.source]))
            + (f" (as {row.ref})" if row.ref else "")]
    if row.notes:
        head.append("Notes: " + row.notes[:1200])
    return "\n".join(head) + "\n\nThe idea, as it was written:\n" + text


def _whole_list(who) -> str:
    from . import incubator

    rows = incubator._rows(who).exclude(status="merged").order_by("number").values_list("number", "title", "gist")
    return "\n".join(f"{incubator.code(n)} {t[:110]}" + (f" - {(g or {}).get('line', '')[:120]}" if (g or {}).get("line") else "")
                     for n, t, g in rows)


def _read(text: str) -> dict:
    """The answer as {number: item}; {} when there is none to read."""
    text = str(text or "").strip()
    fence = re.search(r"```(?:json)?\s*(.+?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    a, b = text.find("{"), text.rfind("}")
    try:
        got = json.loads(text[a:b + 1]) if a >= 0 and b > a else None
    except ValueError:
        got = None
    items = got.get("ideas") if isinstance(got, dict) else got
    out = {}
    for item in items or []:
        if isinstance(item, dict):
            n = re.sub(r"\D", "", str(item.get("id") or ""))
            if n:
                out[int(n)] = item
    return out


def _words(v, most: int) -> str:
    return " ".join(str(v or "").split())[:most]


def _apply(row, item: dict, model: str, numbers: set) -> bool:
    line = _words(item.get("line"), 300)
    if not line:
        return False
    size = str(item.get("size") or "").strip().lower()
    alike = []
    for a in item.get("alike") or []:
        n = re.sub(r"\D", "", str(a))
        if n and int(n) != row.number and int(n) in numbers and int(n) not in alike:
            alike.append(int(n))
    row.gist = {"line": line, "problem": _words(item.get("problem"), 600), "helps": _words(item.get("helps"), 400),
                "in_use": _words(item.get("in_use"), 600), "vision": _words(item.get("vision"), 400),
                "size": size if size in SIZES else "", "size_why": _words(item.get("size_why"), 300),
                "alike": alike[:5], "for": _fingerprint(row), "at": time.time(), "model": str(model or "")[:120]}
    row.save(update_fields=["gist"])
    return True


async def write(who, ids) -> dict:
    """Sum these ideas (row ids) up with Rouh's model, in batches, a few at a time. What came of it."""
    from . import incubator, incubator_score, llm

    Idea, _ = incubator._models()
    ids = list(dict.fromkeys(int(i) for i in ids))
    tally = {"written": 0, "failed": 0, "errors": []}
    if not ids:
        return tally
    whole, numbers = await asyncio.to_thread(
        lambda: (_whole_list(who), set(incubator._rows(who).values_list("number", flat=True))))
    gate = asyncio.Semaphore(AT_ONCE)

    async def one_batch(batch):
        async with gate:
            rows = await asyncio.to_thread(lambda: list(Idea.objects.filter(**incubator._whose(who), id__in=batch)))
            if not rows:
                return
            ask = ("The whole list, for which ideas are the same (number, title, and its line when it has one):\n\n"
                   + whole + f"\n\n---\n\nSum up these {len(rows)} ideas:\n\n" + "\n\n".join(_block(r) for r in rows))
            try:
                got = await llm.ask(USE, system=SYSTEM, messages=ask, max_tokens=600 * len(rows) + 800, who=who,
                                    subject=", ".join(incubator.code(r.number) for r in rows)[:200], timeout=600,
                                    read_only=True)
            except Exception as exc:  # noqa: BLE001 - the rest go on; these are tried again on the beat
                log.warning("the Incubator could not sum up %d ideas: %s", len(rows), exc)
                tally["failed"] += len(rows)
                tally["errors"].append(str(exc)[:300])
                return
            answers = _read(got.text)
            ok = await asyncio.to_thread(lambda: sum(1 for r in rows if answers.get(r.number)
                                                     and _apply(r, answers[r.number], got.model, numbers)))
            tally["written"] += ok
            tally["failed"] += len(rows) - ok
            if ok:
                _forget()
                await incubator_score._announce()

    await asyncio.gather(*(one_batch(ids[i:i + BATCH]) for i in range(0, len(ids), BATCH)))
    return tally


def missing_ids(who) -> list[int]:
    """Ideas with no summary, or one written from words that changed since: those still to be decided
    first, then the rest, by number. Never a merged one, which opens from the idea it is in."""
    from . import incubator

    rows = incubator._rows(who).exclude(status="merged").only("id", "number", "status", "title", "original", "gist")
    todo = [r for r in rows if not is_current(r)]
    todo.sort(key=lambda r: (r.status not in FIRST, r.number))
    return [r.id for r in todo]


_RUN: dict = {}
_KEEP: set = set()


async def sweep(who) -> int:
    """Mutations' beat: a few batches of the summaries still missing. Not while a whole run is going."""
    key = (str(who.org_id), str(who.user_id))
    if (_RUN.get(key) or {}).get("running"):
        return 0
    ids = await asyncio.to_thread(missing_ids, who)
    if not ids:
        return 0
    return (await write(who, ids[:BATCH * AT_ONCE]))["written"]


async def start_all(who) -> dict:
    """Write every missing summary now, in the background. How far it is."""
    key = (str(who.org_id), str(who.user_id))
    now = _RUN.get(key) or {}
    if now.get("running"):
        return progress_of(who)
    ids = await asyncio.to_thread(missing_ids, who)
    state = {"running": bool(ids), "total": len(ids), "started": time.time(), "errors": []}
    _RUN[key] = state
    if ids:
        async def run():
            try:
                got = await write(who, ids)
                state["errors"] = got["errors"][:3]
            except Exception as exc:  # noqa: BLE001 - said on the progress
                log.exception("the Incubator's summaries failed")
                state["errors"] = [str(exc)[:300]]
            finally:
                state["running"] = False

        task = asyncio.get_running_loop().create_task(run())
        _KEEP.add(task)
        task.add_done_callback(_KEEP.discard)
    return await asyncio.to_thread(progress_of, who)


def progress_of(who) -> dict:
    from . import incubator

    rows = list(incubator._rows(who).exclude(status="merged").only("id", "title", "original", "gist"))
    state = _RUN.get((str(who.org_id), str(who.user_id))) or {}
    return {"running": bool(state.get("running")), "written": sum(1 for r in rows if is_current(r)), "all": len(rows),
            "errors": state.get("errors") or []}


# --- lookalikes ---------------------------------------------------------------------------------------

_STOP = set("""a about above after again all also an and any are as at be because been before being below between
both but by can could did do does doing done each else every few for from further get gets had has have having
he her here him his how i if in into is it its itself just let like make makes me more most much must my no nor
not now of off on once one only or other our out over own per same she should so some such than that the their
them then there these they this those through to too under until up us use used very was we were what when where
which while who whom why will with would yet you your rouh idea ideas new gene genes mutation step task page
pages person should could""".split())
_TOKEN = re.compile(r"[a-z][a-z0-9]{2,}")
_CACHE: dict = {}
_CACHE_LOCK = threading.Lock()
#: How close two ideas' words must be to be offered as lookalikes, by the cosine of their TF-IDF vectors.
CLOSE = 0.24


def _forget() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()


def _stem(w: str) -> str:
    for end in ("ings", "ing", "ies", "es", "ed", "s"):
        if len(w) > len(end) + 3 and w.endswith(end):
            return w[: -len(end)]
    return w


def _terms(row) -> list[str]:
    g = row.gist or {}
    text = " ".join([row.title, row.title, g.get("line") or "", g.get("problem") or "", (row.original or "")[:1500]])
    return [_stem(w) for w in _TOKEN.findall(text.lower()) if w not in _STOP]


def _close_words(rows) -> dict:
    """For each row id, the ids of rows whose words are close: [(other id, cosine)], closest first."""
    docs = {r.id: _terms(r) for r in rows}
    df: dict = {}
    for terms in docs.values():
        for t in set(terms):
            df[t] = df.get(t, 0) + 1
    n = max(1, len(docs))
    vecs, index = {}, {}
    for i, terms in docs.items():
        tf: dict = {}
        for t in terms:
            tf[t] = tf.get(t, 0) + 1
        v = {t: (1 + math.log(c)) * math.log(1 + n / df[t]) for t, c in tf.items() if df[t] < n * 0.2 or n < 10}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        vecs[i] = {t: x / norm for t, x in v.items()}
        for t in vecs[i]:
            index.setdefault(t, []).append(i)
    out = {}
    for i, v in vecs.items():
        dots: dict = {}
        for t, x in v.items():
            for j in index[t]:
                if j != i:
                    dots[j] = dots.get(j, 0.0) + x * vecs[j][t]
        best = sorted(((j, d) for j, d in dots.items() if d >= CLOSE), key=lambda p: -p[1])[:3]
        if best:
            out[i] = best
    return out


def lookalikes(who, rows, apart=()) -> dict:
    """For each row id, the ideas it looks like and has not been joined to yet: [{"number", "why"}], where
    why is "rouh" (the model named it) or "words" (their words are close). Merged ideas are left out, and
    so are pairs merged, linked, or said to be "not the same" (`apart`, pairs of numbers "12-40")."""
    from . import incubator

    rows = [r for r in rows if r.status != "merged"]
    by_id = {r.id: r for r in rows}
    by_number = {r.number: r for r in rows}
    sig = (len(rows), max((r.updated_at for r in rows), default=0),
           max(((r.gist or {}).get("at") or 0 for r in rows), default=0))
    key = (str(who.org_id), str(who.user_id))
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
    close = hit[1] if hit and hit[0] == sig else None
    if close is None:
        close = _close_words(rows)
        with _CACHE_LOCK:
            _CACHE[key] = (sig, close)
    apart = {str(p) for p in apart or ()}

    def joined(a, b) -> bool:
        if f"{min(a.number, b.number)}-{max(a.number, b.number)}" in apart:
            return True
        for x, y in ((a, b), (b, a)):
            for link in x.links or []:
                if link.get("kind") == "idea" and str(link.get("href") or "") == f"#{incubator.code(y.number)}":
                    return True
        return False

    out: dict = {}

    def add(a, b, why):
        if a.id == b.id or joined(a, b):
            return
        for x, y in ((a, b), (b, a)):
            have = out.setdefault(x.id, [])
            for h in have:
                if h["number"] == y.number:
                    if why == "rouh":
                        h["why"] = "rouh"
                    break
            else:
                have.append({"number": y.number, "why": why})

    for r in rows:
        for n in (r.gist or {}).get("alike") or []:
            other = by_number.get(int(n))
            if other is not None:
                add(r, other, "rouh")
    for i, best in close.items():
        if i in by_id:
            for j, _ in best:
                if j in by_id:
                    add(by_id[i], by_id[j], "words")
    for v in out.values():
        v.sort(key=lambda h: h["why"] != "rouh")
        del v[4:]
    return out


__all__ = ["SIZES", "USE", "lookalikes", "missing_ids", "progress_of", "start_all", "sweep", "view", "write"]
