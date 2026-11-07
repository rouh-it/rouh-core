"""The Incubator's scores: which idea is worth building first, from parts a person can read and change.

Petar, 4 November 2026: "go implement it. lets see how it feels", and "zero friction on action, the
bottle neck should be only my decision". So every idea of the Incubator (`rouh/incubator.py`) has a
score, and the score is worked out from its parts, never stored:

    Score = Impact² × Confidence × Frequency × Pain × Stars × Clarity ÷ Risk

- **Impact**, 1 to 5, squared (1 to 25), so it weighs most: how much better Rouh gets when the idea
  works. An idea that unblocks other ideas has its impact raised; there is no separate part for it.
- **Confidence**, 50% to 100%: how sure we are that the idea matters.
- **Frequency**, 1 to 4: how often the person would feel it (4 daily, 3 weekly, 2 now and then,
  1 once), together with demand, how often the idea came back (`came_back`: ideas merged into it, the
  other sources it is known from, chats it is linked to, a nightly run proposing it again). Demand
  raises frequency; it is not a part of its own.
- **Pain**: ×2 broken today, ×1.5 annoying, ×1 nice to have.
- **Stars**, 1 to 3, multiplying by 1, 1.5 or 2. Rouh suggests stars for every idea
  (`stars_suggested`); the person's own (`stars_mine`) win when they are set.
- **Clarity**, ×0.9 to ×1, a light weight: could a job build it from what is written?
- **Risk**, ÷1 to ÷1.5, a light weight: could it break memory, mail, security or money?

There is no part for effort, on purpose.

**Who sets what.** Rouh's model, on the use "Scoring the Incubator's ideas" (the Smart tier to start
with, `model_standard.json`), writes every part with a one-line reason, and the suggested stars
(`score`, in batches). A part set by hand - on the page, in a chat on the person's word, from
`rouh-incubator` - is kept beside Rouh's own value as `mine`, and a re-score never changes it: it
only refreshes Rouh's value and reason under it. The same holds for the person's stars.

**When.** An idea added by any road - the page, the Incubator's chat, the nightly run, the import -
is queued (`queue`) and scored in the background a moment later, with others that came in at the
same time; Mutations' beat scores any idea still without a score (`sweep`). Every idea can be scored
again, all at once or one by one (`start_all`, `rescore`).
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
import time

log = logging.getLogger("rouh.incubator_score")

#: The Models page's use for it (`modeldefaults.USES`).
USE = "incubator_score"

#: The parts of a score, in the order the page shows them: the id, the name, what it asks, and the
#: values it can take (a range, or the values themselves with their words).
PARTS: tuple[dict, ...] = (
    {"id": "impact", "name": "Impact", "line": "How much better Rouh gets when it works; squared, so it weighs most. "
     "An idea that unblocks other ideas is raised.", "min": 1, "max": 5, "step": 1,
     "words": {1: "a little", 2: "some", 3: "clearly better", 4: "much better", 5: "a step change"}},
    {"id": "confidence", "name": "Confidence", "line": "How sure we are that it matters.", "min": 0.5, "max": 1.0,
     "step": 0.05},
    {"id": "frequency", "name": "Frequency", "line": "How often it would be felt, and how often the idea came back.",
     "min": 1, "max": 4, "step": 1, "words": {1: "once", 2: "now and then", 3: "weekly", 4: "daily"}},
    {"id": "pain", "name": "Pain", "line": "Broken today, annoying, or just nice to have.",
     "values": (1.0, 1.5, 2.0), "words": {1.0: "nice to have", 1.5: "annoying", 2.0: "broken today"}},
    {"id": "clarity", "name": "Clarity", "line": "Could a job build it from what is written? A light weight.",
     "min": 0.9, "max": 1.0, "step": 0.05},
    {"id": "risk", "name": "Risk", "line": "Could it break memory, mail, security or money? Divides; a light weight.",
     "min": 1.0, "max": 1.5, "step": 0.25},
)
PART_IDS = tuple(p["id"] for p in PARTS)
BY_PART = {p["id"]: p for p in PARTS}
#: What each number of stars multiplies the score by.
STAR_FACTOR = {1: 1.0, 2: 1.5, 3: 2.0}

FORMULA = "Impact² × Confidence × Frequency × Pain × Stars × Clarity ÷ Risk"

#: How many ideas one request scores, how many requests run at once, and how much of an idea's own
#: words each is given (the rest is said to be there).
BATCH = 8
AT_ONCE = 4
TEXT_MOST = 5000


def clean(part: str, value, *, strict: bool = False):
    """A part's value, held to its scale; ValueError when it is not one. `strict`, for a value set by
    hand: one off the scale is refused rather than moved onto it."""
    p = BY_PART.get(part)
    if p is None:
        raise ValueError(f"part is one of: {', '.join(PART_IDS)}, or stars.")
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{p['name']} is a number.") from None
    if part == "confidence" and v > 1.0:
        v = v / 100.0  # 80 means 80%
    lo, hi = (min(p["values"]), max(p["values"])) if "values" in p else (p["min"], p["max"])
    if strict and not (lo - 1e-9 <= v <= hi + 1e-9):
        raise ValueError(f"{p['name']} is from {lo:g} to {hi:g}" + (" (or 50 to 100 percent)" if part == "confidence" else "") + ".")
    if "values" in p:
        return min(p["values"], key=lambda x: abs(x - v))
    v = max(p["min"], min(p["max"], v))
    if p.get("step") == 1:
        return int(round(v))
    return round(v, 2)


def clean_stars(value) -> int | None:
    if value in (None, "", 0, "0", False):
        return None
    try:
        n = int(round(float(value)))
    except (TypeError, ValueError):
        raise ValueError("stars is 1, 2 or 3, or 0 to clear them.") from None
    if n < 1 or n > 3:
        raise ValueError("stars is 1, 2 or 3, or 0 to clear them.")
    return n


def value_of(parts: dict, part: str):
    got = (parts or {}).get(part) or {}
    if "mine" in got and got["mine"] is not None:
        return got["mine"]
    return got.get("rouh")


def compute(parts: dict, stars_suggested, stars_mine) -> float | None:
    """The score from its parts, or None while any part is missing. The page works it out the same way
    (`incubatorpage.js`, `scoreOf`)."""
    vals = {p: value_of(parts, p) for p in PART_IDS}
    stars = stars_mine or stars_suggested
    if any(v is None for v in vals.values()) or not stars:
        return None
    return (vals["impact"] ** 2 * vals["confidence"] * vals["frequency"] * vals["pain"]
            * STAR_FACTOR.get(int(stars), 1.0) * vals["clarity"] / max(1.0, vals["risk"]))


def explain(v: dict) -> str:
    """One idea's score as the model and a terminal read it: the score, each part with its reason and
    whose it is, and the formula with its numbers."""
    if v.get("score") is None:
        return "Not scored yet."
    parts = v.get("parts") or {}
    lines = [f"Score {round(v['score'])} = {FORMULA}"]
    for p in PARTS:
        got = parts.get(p["id"]) or {}
        mine = got.get("mine") is not None
        lines.append(f"- {p['name']} {_shown(p['id'], got.get('v'))}"
                     + (f" (set by {got.get('by') or 'hand'}; Rouh said {_shown(p['id'], got.get('rouh'))})" if mine else "")
                     + (f": {got['why']}" if got.get("why") else ""))
    who = "yours" if v.get("stars_mine") else "Rouh's suggestion"
    lines.append(f"- Stars {v.get('stars')} ({who}" + (f"; Rouh suggests {v.get('stars_suggested')}" if v.get("stars_mine") else "")
                 + ")" + (f": {v['stars_why']}" if v.get("stars_why") else ""))
    lines.append("= " + numbers(v))
    cb = v.get("came_back") or {}
    if cb.get("total"):
        lines.append(f"It came back {cb['total']} times: " + ", ".join(
            f"{n} {w}" for w, n in (("merged into it", cb.get("merged")), ("other sources", cb.get("sources")),
                                     ("chats", cb.get("chats")), ("proposed again", cb.get("proposed"))) if n) + ".")
    return "\n".join(lines)


def _shown(part: str, value) -> str:
    if value is None:
        return "–"
    if part == "confidence":
        return f"{round(float(value) * 100)}%"
    if part in ("impact", "frequency"):
        return str(int(value))
    return f"{float(value):g}"


def numbers(v: dict) -> str:
    """The formula with this idea's numbers in it."""
    parts = v.get("parts") or {}
    g = {p: (parts.get(p) or {}).get("v") for p in PART_IDS}
    if any(x is None for x in g.values()) or not v.get("stars"):
        return ""
    return (f"{int(g['impact'])}² × {float(g['confidence']):g} × {int(g['frequency'])} × {float(g['pain']):g} × "
            f"{STAR_FACTOR[int(v['stars'])]:g} × {float(g['clarity']):g} ÷ {float(g['risk']):g} = {round(v['score'])}")


def view_parts(row) -> dict:
    """What `incubator.view` adds for the score: every part with its value, Rouh's, the hand-set one and
    its reason, the stars, and the score worked out."""
    raw = row.score_parts or {}
    parts = {}
    for p in PART_IDS:
        got = raw.get(p) or {}
        out = {"v": value_of(raw, p), "rouh": got.get("rouh"), "why": got.get("why") or ""}
        if got.get("mine") is not None:
            out.update(mine=got["mine"], by=got.get("by") or "", at=got.get("at"))
        parts[p] = out
    stars = row.stars_mine or row.stars_suggested
    return {"parts": parts, "stars_suggested": row.stars_suggested, "stars_mine": row.stars_mine,
            "stars": stars, "stars_why": (raw.get("stars") or {}).get("why") or "",
            "score": compute(raw, row.stars_suggested, row.stars_mine), "scored_at": row.scored_at,
            "scored_model": row.scored_model}


def facts() -> dict:
    """The scale, for the page's "How scores work" and its menus."""
    out = []
    for p in PARTS:
        item = {k: v for k, v in p.items() if k != "words"}
        if "values" in item:
            item["values"] = list(item["values"])
        if p.get("words"):
            item["words"] = {f"{k:g}" if isinstance(k, float) else str(k): w for k, w in p["words"].items()}
        out.append(item)
    return {"parts": out, "stars": {str(k): v for k, v in STAR_FACTOR.items()}, "formula": FORMULA}


# --- demand: how often an idea came back --------------------------------------------------------------


def came_back(who, rows=None) -> dict:
    """For each idea id: how often it came back, from ideas merged into it, the other sources it is
    known from, the chats it is linked to, and a nightly run proposing it again."""
    from django.db.models import Count

    from . import incubator

    Idea, Event = incubator._models()
    whose = incubator._whose(who)
    merged = dict(Idea.objects.filter(**whose, merged_into__isnull=False).values_list("merged_into")
                  .annotate(n=Count("id")))
    proposed = dict(Event.objects.filter(**whose, what="proposed_again").values_list("idea_id")
                    .annotate(n=Count("id")))
    out = {}
    for r in (rows if rows is not None else Idea.objects.filter(**whose)):
        srcs = len(set(r.sources or [r.source])) - 1
        chats = sum(1 for l in (r.links or []) if l.get("kind") == "chat")
        got = {"merged": int(merged.get(r.id, 0)), "sources": max(0, srcs), "chats": chats,
               "proposed": int(proposed.get(r.id, 0))}
        got["total"] = sum(got.values())
        out[r.id] = got
    return out


# --- changing a part or the stars by hand -------------------------------------------------------------


def set_stars(who, ident, stars, *, by: str = "you") -> dict:
    """The person's own stars, 1 to 3, or None to go back to Rouh's suggestion."""
    from . import incubator

    try:
        n = clean_stars(stars)
    except ValueError as exc:
        raise incubator.Refused(str(exc)) from None
    row = incubator.find(who, ident)
    was = row.stars_mine
    if was == n:
        return incubator.view(row)
    row.stars_mine, row.updated_at = n, time.time()
    row.save(update_fields=["stars_mine", "updated_at"])
    incubator._event(who, row.id, "stars", by=by, before={"stars": was}, after={"stars": n},
                     note="" if n else f"Back to Rouh's suggestion, {row.stars_suggested or '–'}.")
    return incubator.view(row)


def set_part(who, ident, part: str, value, *, by: str = "you") -> dict:
    """A part set by hand, kept beside Rouh's own value; None gives it back to Rouh. "stars" is the
    person's stars."""
    from . import incubator

    part = str(part or "").strip().lower()
    if part == "stars":
        return set_stars(who, ident, value, by=by)
    try:
        v = None if value in (None, "") else clean(part, value, strict=True)
    except ValueError as exc:
        raise incubator.Refused(str(exc)) from None
    row = incubator.find(who, ident)
    parts = dict(row.score_parts or {})
    got = dict(parts.get(part) or {})
    was = got.get("mine")
    if was == v:
        return incubator.view(row)
    if v is None:
        for k in ("mine", "by", "at"):
            got.pop(k, None)
    else:
        got.update(mine=v, by=by, at=time.time())
    parts[part] = got
    row.score_parts, row.updated_at = parts, time.time()
    row.save(update_fields=["score_parts", "updated_at"])
    incubator._event(who, row.id, "part", by=by, before={"part": part, "value": was}, after={"part": part, "value": v},
                     note=f"{BY_PART[part]['name']} " + (f"set to {_shown(part, v)}" if v is not None else
                                                          f"given back to Rouh's {_shown(part, got.get('rouh'))}") + ".")
    return incubator.view(row)


# --- Rouh's scoring --------------------------------------------------------------------------------------

SYSTEM = """You score ideas in the Incubator, the person's one list of ideas for new genes (abilities) and mutations (changes to abilities it has) of Rouh, their personal AI assistant. Rouh runs their mail, calendar, tasks, memory (Synapse), voice, background jobs and its own code; it builds new abilities for itself from these ideas. The score decides what is built first, so be honest and spread the values: most ideas are not a 5.

For every idea you are given, answer each part with a value and one short reason (one line, under 25 words, plain words, about this idea):

- impact, a whole number 1 to 5: how much better Rouh gets for the person when the idea works. 1 a little, 2 some, 3 clearly better, 4 much better, 5 a step change. Raise it when the idea unblocks other ideas in the list (say which, by number).
- confidence, 0.5 to 1.0: how sure we are that the idea matters to the person. 0.5 a guess, 0.75 likely, 1.0 they said so plainly or it keeps coming back.
- frequency, a whole number 1 to 4: how often the person would feel it: 4 daily, 3 weekly, 2 now and then, 1 once. Raise it for demand: the idea came back (merged duplicates, other sources, chats, proposed again), or other ideas in the list ask for much the same thing.
- pain, exactly 1, 1.5 or 2: 2 when something is broken today, 1.5 when it is annoying, 1 when it is just nice to have.
- clarity, 0.9 to 1.0: could a background job build it from what is written? 1.0 clear, 0.95 mostly, 0.9 vague.
- risk, 1.0 to 1.5: could building it break memory, mail, security or money? 1.0 no, 1.25 some, 1.5 yes.
- stars, a whole number 1 to 3: the stars you suggest, the person's own priority as you read it: 3 they clearly want it, 2 they would like it, 1 no sign either way.

An idea that is Built, Rejected or Merged is scored the same way, on what the idea itself is worth: its status is not a reason to lower it.

There is no part for effort: never lower a score because an idea is big.

Answer with JSON alone, no other words:
{"ideas": [{"id": "INC-12", "impact": {"v": 3, "why": "..."}, "confidence": {"v": 0.8, "why": "..."}, "frequency": {"v": 3, "why": "..."}, "pain": {"v": 1.5, "why": "..."}, "clarity": {"v": 0.95, "why": "..."}, "risk": {"v": 1.0, "why": "..."}, "stars": {"v": 2, "why": "..."}}]}
Every idea you were given must be in the answer, once, by its id."""


def _idea_block(row, back: dict) -> str:
    from . import incubator

    text = row.original or row.title
    if len(text) > TEXT_MOST:
        text = text[:TEXT_MOST] + f"\n[... {len(row.original) - TEXT_MOST:,} more characters of the idea's own words]"
    links = [f"{l.get('kind')}: {l.get('label')}" for l in (row.links or [])[:15]]
    head = [f"### {incubator.code(row.number)}: {row.title}",
            f"Kind: {incubator.KIND_NAMES.get(row.kind, row.kind)}" + (f", of the gene {row.gene}" if row.gene else ""),
            f"Category: {incubator.CATEGORY_NAMES.get(row.category, row.category or 'none')}",
            f"Status: {incubator.STATUS_NAMES.get(row.status, row.status)}"
            + (f" (in its source: {row.source_status})" if row.source_status else ""),
            "Sources: " + ", ".join(incubator.SOURCE_NAMES.get(s, s) for s in (row.sources or [row.source]))
            + (f" (as {row.ref})" if row.ref else "")]
    if back.get("total"):
        head.append(f"Came back {back['total']} times: {back['merged']} merged into it, {back['sources']} other "
                    f"sources, {back['chats']} chats, proposed again {back['proposed']}.")
    if row.tags:
        head.append("Tags: " + ", ".join(row.tags))
    if row.notes:
        head.append("Notes: " + row.notes[:1500])
    if row.built_as:
        head.append("Became: " + row.built_as)
    if links:
        head.append("Links: " + "; ".join(links))
    return "\n".join(head) + "\n\nThe idea, as it was written:\n" + text


def _whole_list(who) -> str:
    """Every idea's number, status and title, so the scorer can see what an idea unblocks and repeats."""
    from . import incubator

    rows = incubator._rows(who).exclude(status="merged").order_by("number").values_list("number", "status", "title")
    return "\n".join(f"{incubator.code(n)} [{incubator.STATUS_NAMES.get(s, s)}] {t[:120]}" for n, s, t in rows)


def _read(text: str) -> dict:
    """The model's answer as {code: {part: (value, why)}}; {} when there is none to read."""
    text = str(text or "").strip()
    fence = re.search(r"```(?:json)?\s*(.+?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    a, b = text.find("{"), text.rfind("}")
    got = None
    if a >= 0 and b > a:
        try:
            got = json.loads(text[a:b + 1])
        except ValueError:
            got = None
    items = got.get("ideas") if isinstance(got, dict) else got
    out = {}
    for item in items or []:
        if not isinstance(item, dict):
            continue
        n = re.sub(r"\D", "", str(item.get("id") or ""))
        if n:
            out[int(n)] = item
    return out


def _apply(who, row, item: dict, model: str) -> bool:
    """One idea's answer written: each part's Rouh value and reason, the suggested stars. Never a value
    set by hand, and never the idea's words."""
    from . import incubator

    parts = dict(row.score_parts or {})
    for p in PART_IDS:
        said = item.get(p)
        if not isinstance(said, dict):
            said = {"v": said}
        try:
            v = clean(p, said.get("v"))
        except ValueError:
            return False
        got = dict(parts.get(p) or {})
        got.update(rouh=v, why=" ".join(str(said.get("why") or "").split())[:300])
        parts[p] = got
    st = item.get("stars")
    st = st if isinstance(st, dict) else {"v": st}
    try:
        stars = clean_stars(st.get("v")) or 1
    except ValueError:
        stars = 1
    parts["stars"] = {"why": " ".join(str(st.get("why") or "").split())[:300]}
    before = compute(row.score_parts or {}, row.stars_suggested, row.stars_mine)
    row.score_parts, row.stars_suggested = parts, stars
    row.scored_at, row.scored_model = time.time(), str(model or "")[:120]
    row.save(update_fields=["score_parts", "stars_suggested", "scored_at", "scored_model"])
    after = compute(parts, stars, row.stars_mine)
    incubator._event(who, row.id, "scored", by="Rouh", before={"score": round(before) if before is not None else None},
                     after={"score": round(after) if after is not None else None, "stars": stars},
                     note=f"Scored by {model}." if model else "")
    return True


async def score(who, ids, *, progress: dict | None = None) -> dict:
    """Score these ideas (row ids) with Rouh's model, in batches, a few at a time. What came of it."""
    from . import incubator, llm

    Idea, _ = incubator._models()
    ids = list(dict.fromkeys(int(i) for i in ids))
    if not ids:
        return {"scored": 0, "failed": 0}
    whole = await asyncio.to_thread(_whole_list, who)
    gate = asyncio.Semaphore(AT_ONCE)
    tally = {"scored": 0, "failed": 0, "errors": []}

    async def one_batch(batch: list[int]) -> None:
        async with gate:
            def gather():
                rows = list(Idea.objects.filter(**incubator._whose(who), id__in=batch))
                back = came_back(who, rows)
                return rows, "\n\n".join(_idea_block(r, back.get(r.id, {})) for r in rows)

            rows, blocks = await asyncio.to_thread(gather)
            if not rows:
                return
            ask = ("The whole list, for what each idea unblocks or repeats (number, status, title):\n\n" + whole
                   + f"\n\n---\n\nScore these {len(rows)} ideas:\n\n" + blocks)
            try:
                got = await llm.ask(USE, system=SYSTEM, messages=ask, max_tokens=900 * len(rows) + 1500, who=who,
                                    subject=", ".join(incubator.code(r.number) for r in rows)[:200], timeout=600)
            except Exception as exc:  # noqa: BLE001 - the rest go on; these are tried again later
                log.warning("the Incubator could not score %d ideas: %s", len(rows), exc)
                tally["failed"] += len(rows)
                tally["errors"].append(str(exc)[:300])
                if progress is not None:
                    progress["failed"] = progress.get("failed", 0) + len(rows)
                return
            answers = _read(got.text)

            def write():
                ok = 0
                for r in rows:
                    item = answers.get(r.number)
                    if item and _apply(who, r, item, got.model):
                        ok += 1
                return ok

            ok = await asyncio.to_thread(write)
            if ok:
                await _announce()
            tally["scored"] += ok
            tally["failed"] += len(rows) - ok
            if progress is not None:
                progress["done"] = progress.get("done", 0) + ok
                progress["failed"] = progress.get("failed", 0) + len(rows) - ok

    batches = [ids[i:i + BATCH] for i in range(0, len(ids), BATCH)]
    await asyncio.gather(*(one_batch(b) for b in batches))
    return tally


async def _announce() -> None:
    """Every open Incubator page reads the list again."""
    try:
        from . import runtime

        await runtime.Hub.broadcast({"type": "incubator_changed", "open": False, "number": 0})
    except Exception:  # noqa: BLE001 - the page reads the scores on its next look
        log.debug("the Incubator's pages could not be told", exc_info=True)


# --- the background: new ideas scored as they come, and a whole run on request --------------------------

_LOCK = threading.Lock()
#: Ideas waiting to be scored, by whose they are: {(org_id, user_id): {row id, ...}}.
_PENDING: dict = {}
#: A whole run, by whose: {"running", "total", "done", "failed", "started", "ended", "errors"}.
PROGRESS: dict = {}
_HOME: dict = {"loop": None, "task": None}
_KEEP: set = set()


def _key(who) -> tuple:
    return (str(who.org_id), str(who.user_id))


def queue(who, idea_id: int) -> None:
    """Score this idea soon, in the background. Safe from any thread; never raises."""
    try:
        with _LOCK:
            _PENDING.setdefault(_key(who), set()).add(int(idea_id))
        loop = _HOME.get("loop")
        if loop is not None and not loop.is_closed():
            loop.call_soon_threadsafe(_kick)
    except Exception:  # noqa: BLE001 - the beat scores it anyway
        log.debug("an idea could not be queued for scoring", exc_info=True)


def _kick() -> None:
    task = _HOME.get("task")
    if task is None or task.done():
        _HOME["task"] = asyncio.get_running_loop().create_task(_drain())


async def _drain() -> None:
    """The ideas queued, a few seconds after the last came in, so an import or a night's ideas go in
    batches rather than one request each."""
    from .tenancy import Tenancy

    await asyncio.sleep(8)
    while True:
        with _LOCK:
            work = {k: v for k, v in _PENDING.items() if v}
            _PENDING.clear()
        if not work:
            return
        for (org_id, user_id), ids in work.items():
            who = await asyncio.to_thread(lambda u=user_id: Tenancy().identity_of(u))
            if who is None or str(who.org_id) != org_id:
                continue
            try:
                await score(who, sorted(ids))
            except Exception:  # noqa: BLE001 - the beat tries again
                log.exception("the Incubator's new ideas could not be scored")
            try:
                # And summed up, once, for the list's line and its preview (`rouh/incubator_gist.py`).
                from . import incubator_gist

                missing = set(await asyncio.to_thread(incubator_gist.missing_ids, who))
                if missing & set(ids):
                    await incubator_gist.write(who, sorted(missing & set(ids)))
            except Exception:  # noqa: BLE001 - the beat tries again
                log.exception("the Incubator's new ideas could not be summed up")


def start() -> None:
    """Take the running loop, so ideas added from any thread are scored on it."""
    _HOME["loop"] = asyncio.get_running_loop()


def unscored_ids(who) -> list[int]:
    from . import incubator

    return list(incubator._rows(who).filter(scored_at__isnull=True).order_by("number").values_list("id", flat=True))


async def sweep(who) -> int:
    """Mutations' beat: any idea still without a score is scored. Not while a whole run is going, and
    at most a few batches a beat, so a Rouh without a model does not ask again and again."""
    if (PROGRESS.get(_key(who)) or {}).get("running"):
        return 0
    ids = await asyncio.to_thread(unscored_ids, who)
    if not ids:
        return 0
    got = await score(who, ids[:BATCH * AT_ONCE])
    return got["scored"]


async def start_all(who, *, force: bool = False) -> dict:
    """Score every idea (or, without force, every idea not scored yet) in the background, on this loop.
    What the run looks like now."""
    from . import incubator

    key = _key(who)
    now = PROGRESS.get(key) or {}
    if now.get("running"):
        return dict(now)

    def which():
        rows = incubator._rows(who)
        if not force:
            rows = rows.filter(scored_at__isnull=True)
        return list(rows.order_by("number").values_list("id", flat=True))

    ids = await asyncio.to_thread(which)
    state = {"running": bool(ids), "total": len(ids), "done": 0, "failed": 0, "started": time.time(),
             "ended": None if ids else time.time(), "force": bool(force), "errors": []}
    PROGRESS[key] = state
    if not ids:
        return dict(state)

    async def run():
        try:
            got = await score(who, ids, progress=state)
            state["errors"] = got.get("errors", [])[:5]
        except Exception as exc:  # noqa: BLE001 - said on the progress
            log.exception("the Incubator's whole scoring failed")
            state["errors"] = [str(exc)[:300]]
        finally:
            state["running"], state["ended"] = False, time.time()

    task = asyncio.get_running_loop().create_task(run())
    _KEEP.add(task)
    task.add_done_callback(_KEEP.discard)
    return dict(state)


def progress_of(who) -> dict:
    from . import incubator

    rows = incubator._rows(who)
    out = dict(PROGRESS.get(_key(who)) or {"running": False})
    out["scored"] = rows.filter(scored_at__isnull=False).count()
    out["all"] = rows.count()
    return out


async def rescore(who, ident) -> dict:
    """Score one idea again now. Parts and stars set by hand stay as they are."""
    from . import incubator

    row = await asyncio.to_thread(incubator.find, who, ident)
    got = await score(who, [row.id])
    if not got["scored"]:
        raise incubator.Refused("Rouh could not score it just now" + (f": {got['errors'][0]}" if got.get("errors") else ".")
                                + " Nothing of it was changed.")
    return await asyncio.to_thread(incubator.one, who, row.number)


__all__ = ["FORMULA", "PARTS", "compute", "explain", "queue", "rescore", "score", "set_part", "set_stars",
           "start_all", "sweep"]
