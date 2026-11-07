"""The budgeted best-first walk (D41 to D47, D71), recorded frame by frame.

An item n reached along a path from a seed is scored

    score(n) = R(n) × P(n) × H(n) × product over the path's links of (strength × T(type) × d)

- R, relevance: a seed's fused search score scaled so the best seed is 1; an
  item reached by a link, the cosine of its best passage to the question,
  mapped from 0.2 (scores 0) to 0.8 (scores 1). Times 1.5 when it is in the
  context's task or from its sender (D48). In a background walk only, R is the
  average of that and a decision model's probability that it helps (D71).
- P, the prior: tier (0.2, 0.6, 1.0) times recency (mail and chat halve every
  180 days, never under 0.3) times 0.5 if another item updates it.
- H, the hub mark-down: sqrt(50 / links) for an item with more than 50 links.
- T(type), 1 for every type to start; d, hop decay, 0.5.

The best item is taken out of the queue and expanded: its links (both
directions, both ends readable by the asker) are fetched in one query, each
neighbour scored, and those within 0.6 of the best neighbour and over the floor
of 0.02, at most 6, are queued; one that holds the question's rare words (a
name, a product, used in at most 200 passages) is relevant by them as well
as by meaning, and is queued however far below the best neighbour it scores
(attempt 38). A branch stops after 3 expansions that add
nothing new; everything stops at the token budget, 300 expansions, 1.5 seconds
of database time, or when the best left scores under 0.05.

Every expansion is a frame: what was taken out and why, every neighbour with
its score taken apart and whether it was kept, the queue after, the budget used.
The debugger plays them back one at a time.
"""
from __future__ import annotations

import heapq
import math
import time
from datetime import datetime, timezone

from . import ai, db, search, text as tx

MAX_FRAMES = 400

#: The links that join one mail of a conversation to another (`mail_thread`).
THREAD_TYPES = ("in_thread", "reply_to", "continues", "follows_up")


def _age_days(when) -> float:
    if not when:
        return 0.0
    if isinstance(when, str):
        try:
            when = datetime.fromisoformat(when.replace("Z", "+00:00"))
        except ValueError:
            return 0.0
    return max(0.0, (datetime.now(timezone.utc) - when).total_seconds() / 86400.0)


def facts_of(ds_id: str, ids) -> dict[str, dict]:
    """What the score needs of each item: kind, tier, date, degree, updated-by, readers."""
    ids = [str(i) for i in ids if i]
    if not ids:
        return {}
    got = db.rows(
        "SELECT i.id, i.kind, i.title, i.tier, i.said_at, i.sensitivity, i.owner, i.meta, i.xray, i.body, "
        " (SELECT count(*) FROM synapse.link l WHERE l.dataset_id = %s AND (l.src = i.id OR l.dst = i.id)) AS degree, "
        " (SELECT count(*) FROM synapse.link l WHERE l.dataset_id = %s AND l.dst = i.id AND l.type = 'updates') AS updated, "
        # A night of dreaming's notes (D86): how many of its claims a newer item replaced, and whether it is
        # a duplicate kept as another item's alias.
        " i.alias_of, (SELECT count(*) FROM synapse.claim_note n WHERE n.dataset_id = i.dataset_id AND n.item_id = i.id "
        "  AND n.note = 'replaced') AS replaced "
        # A person of the owner's people set is in play wherever this dataset links to them (decision 7).
        "FROM synapse.item i WHERE i.dataset_id = ANY(synapse.scope(%s)) AND i.id = ANY(%s::uuid[])",
        (ds_id, ds_id, ds_id, ids))
    return {r["id"]: r for r in got}


def prior(f: dict, s) -> tuple[float, dict]:
    if f.get("kind") == "person" and isinstance((f.get("meta") or {}).get("value"), (int, float)):
        # A person's prior is how much they matter, from their links (3 October 2026, decision 9).
        v = float(f["meta"]["value"])
        sup = float(s.superseded) if int(f.get("updated") or 0) > 0 else 1.0
        return v * sup, {"person_value": v, "value_parts": (f["meta"].get("value_parts") or {}),
                         "superseded": sup}
    tier = int(f.get("tier") or 1)
    base = [float(s.prior_junk), float(s.prior_normal), float(s.prior_important)][max(0, min(2, tier))]
    gm = (f.get("meta") or {}).get("gmail")
    if isinstance(gm, dict) and gm.get("folder") in ("spam", "trash"):
        # Gmail put it in spam or the Bin (`gmailsync`): the junk prior, whatever its tier says.
        return _junk_folder(f, s, base, tier, gm["folder"])
    rec = 1.0
    if f.get("kind") in ("mail", "chat_turn", "rouh_said", "event", "meeting"):
        age = _age_days(f.get("said_at"))
        rec = max(float(s.recency_floor), 0.5 ** (age / max(1.0, float(s.half_life_days))))
    sup = float(s.superseded) if int(f.get("updated") or 0) > 0 else 1.0
    dream = replaced_factor(f, s)
    out = {"tier": tier, "tier_prior": base, "recency": round(rec, 4), "superseded": sup}
    if dream != 1.0:
        out["replaced_by_dreaming"] = round(dream, 4)
    return base * rec * sup * dream, out


def replaced_factor(f: dict, s) -> float:
    """Ranking prefers the current claim (D86): an item whose claims a night of dreaming marked replaced is
    marked down by the superseded factor in the share of its claims replaced, and a duplicate kept as an
    alias by the whole of it, so its canonical item comes first."""
    if f.get("alias_of"):
        return float(s.superseded)
    n = int(f.get("replaced") or 0)
    if not n:
        return 1.0
    claims = len(((f.get("xray") or {}).get("claims")) or []) or n
    share = min(1.0, n / claims)
    return 1.0 - (1.0 - float(s.superseded)) * share


def _junk_folder(f: dict, s, was: float, tier: int, folder: str) -> tuple[float, dict]:
    base = float(s.prior_junk)
    age = _age_days(f.get("said_at"))
    rec = max(float(s.recency_floor), 0.5 ** (age / max(1.0, float(s.half_life_days))))
    sup = float(s.superseded) if int(f.get("updated") or 0) > 0 else 1.0
    return base * rec * sup, {"tier": tier, "tier_prior": base, "gmail_folder": folder, "tier_prior_before": was,
                              "recency": round(rec, 4), "superseded": sup}


def hub(f: dict, s) -> float:
    deg = int(f.get("degree") or 0)
    c = float(s.hub_constant)
    return 1.0 if deg <= c else math.sqrt(c / deg)


def relevance_of_cos(cos: float | None, s) -> float:
    if cos is None:
        return 0.0
    lo, hi = float(s.r_low), float(s.r_high)
    return max(0.0, min(1.0, (cos - lo) / max(1e-6, hi - lo)))


def _line_tokens(f: dict) -> int:
    return tx.tokens(tx.compact(0, f))


def _neighbours(ds_id: str, item_id: str, readers: list[str], asker: str) -> list[dict]:
    return db.rows(
        "SELECT l.id AS link_id, l.type, l.strength, l.origin, "
        " CASE WHEN l.src = %s THEN l.dst ELSE l.src END AS other, "
        " CASE WHEN l.src = %s THEN 'out' ELSE 'in' END AS dir "
        "FROM synapse.link l JOIN synapse.item o ON o.id = CASE WHEN l.src = %s THEN l.dst ELSE l.src END "
        "WHERE l.dataset_id = %s AND (l.src = %s OR l.dst = %s) AND o.deleted_at IS NULL AND o.kind <> 'rule' "
        f"AND {search.readable_sql('o')}", (item_id, item_id, item_id, ds_id, item_id, item_id, readers))


class Walk:
    def __init__(self, ds: dict, question: str, qvec, *, asker: str, s, mode: str = "live",
                 budget: int | None = None, trace=None, owner: dict | None = None,
                 boost_ids: set | None = None, qmodel: str | None = None, rare: list[dict] | None = None) -> None:
        self.ds, self.ds_id, self.question, self.qvec = ds, ds["id"], question, qvec
        self.qmodel = qmodel
        self.asker, self.s, self.mode = asker, s, mode
        self.readers = search.readers_for(asker)
        self.budget = int(budget or (s.budget_background if mode == "background" else s.budget_live))
        self.trace, self.owner = trace, owner
        self.boost_ids = boost_ids or set()
        # The question's rare words, with their weights (`search.rare_lexemes`): an item reached by a link that
        # holds them is relevant by them as well as by meaning (attempt 38).
        self.rare = {x["lexeme"]: float(x["weight"]) for x in (rare or [])} if float(s.walk_words) > 0 else {}
        self.queue: list = []
        self.counter = 0
        self.best_in_queue: dict[str, float] = {}
        self.gathered: list[dict] = []
        self.gathered_ids: set[str] = set()
        self.tokens = 0
        self.frames: list[dict] = []
        self.expansions = 0
        self.db_seconds = 0.0
        self.branch_empty: dict[str, int] = {}
        self.branch_stopped: dict[str, str] = {}
        self.titles: dict[str, str] = {}
        self.stop = ""
        self.started = time.time()
        self.decisions: list[dict] = []
        # What the walk has read of each item, by id: a seed's or a neighbour's facts are read once, and taking
        # the item out of the queue uses them rather than asking the database again (attempt 33).
        self.facts: dict[str, dict] = {}

    # --- scoring -----------------------------------------------------------------------

    def _db(self, fn, *a):
        t = time.time()
        out = fn(*a)
        self.db_seconds += time.time() - t
        return out

    def seed(self, seeds: list[dict]) -> None:
        """Seeds: `{"id", "R", "why", "ranks"}`, R already scaled so the best is 1."""
        facts = self._facts([x["id"] for x in seeds])
        frame_seeds = []
        for x in seeds:
            f = facts.get(x["id"])
            if not f:
                continue
            self.titles[x["id"]] = f["title"] or f["kind"]
            r = float(x["R"])
            boosted = x["id"] in self.boost_ids
            if boosted:
                r = min(1.0, r * float(self.s.context_boost))
            p, pw = prior(f, self.s)
            h = hub(f, self.s)
            score = r * p * h
            entry = {"id": x["id"], "score": score, "R": r, "P": p, "H": h, "pi": 1.0, "path": [],
                     "branch": x["id"], "why": x.get("why", "seed"), "prior": pw, "degree": f["degree"],
                     "boosted": boosted, "ranks": x.get("ranks", {}), "seed": True}
            self._push(entry)
            frame_seeds.append(self._public(entry, f))
        self.frames.append({"n": 0, "kind": "seeds", "seeds": frame_seeds, "queue": self._queue_top(),
                            "tokens": 0, "budget": self.budget,
                            "note": f"{len(frame_seeds)} seeds go into the queue by score (D42)."})

    def _public(self, e: dict, f: dict | None = None) -> dict:
        return {"id": e["id"], "title": self.titles.get(e["id"], ""), "kind": (f or {}).get("kind"),
                "score": round(e["score"], 5), "R": round(e["R"], 4), "P": round(e["P"], 4), "H": round(e["H"], 4),
                "pi": round(e["pi"], 5), "path": e["path"], "branch": e["branch"], "why": e.get("why", ""),
                "prior": e.get("prior"), "degree": e.get("degree"), "boosted": e.get("boosted", False),
                "cos": e.get("cos"), "p_yes": e.get("p_yes"), "words": e.get("words")}

    def _push(self, e: dict) -> None:
        if e["id"] in self.gathered_ids:
            return
        if self.best_in_queue.get(e["id"], -1) >= e["score"]:
            return
        self.best_in_queue[e["id"]] = e["score"]
        self.counter += 1
        heapq.heappush(self.queue, (-e["score"], self.counter, e))

    def _pop(self) -> dict | None:
        while self.queue:
            neg, _, e = heapq.heappop(self.queue)
            if e["id"] in self.gathered_ids:
                continue
            if self.best_in_queue.get(e["id"]) != e["score"]:
                continue
            if e["branch"] in self.branch_stopped:
                continue
            return e
        return None

    def _queue_top(self, n: int = 12) -> list[dict]:
        live = [e for _, _, e in sorted(self.queue) if e["id"] not in self.gathered_ids
                and self.best_in_queue.get(e["id"]) == e["score"] and e["branch"] not in self.branch_stopped]
        return [{"id": e["id"], "title": self.titles.get(e["id"], ""), "score": round(e["score"], 5)} for e in live[:n]]

    # --- the walk ------------------------------------------------------------------------

    def run(self) -> dict:
        s = self.s
        wave = int(s.frontier_wave) if self.mode == "background" else 1
        while True:
            if not self.queue or self._peek() is None:
                self.stop = self.stop or "nothing left in the queue"
                break
            best = self._peek()
            if best["score"] < float(s.weak_frontier):
                self.stop = f"the best item left scores {best['score']:.4f}, under {s.weak_frontier} (D44)"
                break
            if self.expansions >= int(s.max_expansions):
                self.stop = f"{self.expansions} expansions, the cap (D44)"
                break
            if self.mode == "live" and self.db_seconds > float(s.max_db_seconds):
                self.stop = f"{self.db_seconds:.2f} s of database time, over {s.max_db_seconds} s (D44)"
                break
            if self.mode == "background" and time.time() - self.started > float(s.background_seconds):
                self.stop = f"{int(time.time() - self.started)} s, the background budget (D45)"
                break
            opened = []
            for _ in range(wave):
                e = self._pop()
                if e is None:
                    break
                ok = self._gather(e)
                if not ok:
                    break
                opened.append(e)
            if self.stop:
                break
            if not opened:
                continue
            self._expand(opened)
        self.frames.append({"n": len(self.frames), "kind": "stop", "stop": self.stop, "tokens": self.tokens,
                            "budget": self.budget, "gathered": len(self.gathered), "expansions": self.expansions,
                            "db_ms": int(self.db_seconds * 1000), "queue": self._queue_top(),
                            "branches_stopped": [{"branch": self.titles.get(b, b), "why": w}
                                                 for b, w in self.branch_stopped.items()]})
        return {"gathered": self.gathered, "frames": self.frames[:MAX_FRAMES], "stop": self.stop,
                "tokens": self.tokens, "budget": self.budget, "expansions": self.expansions,
                "db_ms": int(self.db_seconds * 1000), "ms": int((time.time() - self.started) * 1000),
                "decisions": self.decisions, "titles": self.titles}

    def _peek(self) -> dict | None:
        while self.queue:
            neg, _, e = self.queue[0]
            if (e["id"] in self.gathered_ids or self.best_in_queue.get(e["id"]) != e["score"]
                    or e["branch"] in self.branch_stopped):
                heapq.heappop(self.queue)
                continue
            return e
        return None

    def _facts(self, ids) -> dict[str, dict]:
        """`facts_of` for these items, reading from the database only those the walk has not read yet."""
        need = [i for i in dict.fromkeys(str(i) for i in ids if i) if i not in self.facts]
        if need:
            self.facts.update(self._db(facts_of, self.ds_id, need))
        return {i: self.facts[i] for i in (str(x) for x in ids if x) if i in self.facts}

    def _gather(self, e: dict) -> bool:
        f = self._facts([e["id"]]).get(e["id"])
        if not f:
            return True
        cost = _line_tokens(f)
        if self.tokens + cost > self.budget:
            self.stop = (f"the token budget: {self.tokens} used of {self.budget}, and the next item "
                         f"({self.titles.get(e['id'], '')}) needs {cost} (D45)")
            return False
        self.tokens += cost
        e["tokens"] = cost
        self.gathered.append(e)
        self.gathered_ids.add(e["id"])
        return True

    def _expand(self, opened: list[dict]) -> None:
        s = self.s
        frame = {"n": len(self.frames), "kind": "expand", "opened": [], "neighbours": [], "decision": None}
        new_all = []
        for e in opened:
            self.expansions += 1
            links = self._db(_neighbours, self.ds_id, e["id"], self.readers, self.asker)
            parent_kind = (self.facts.get(e["id"]) or {}).get("kind")
            others = list({l["other"] for l in links})
            facts = self._facts(others)
            cos = self._db(search.cosines, self.ds_id, others, self.qvec, self.qmodel)
            held = self._db(search.words_held, self.ds_id, others, list(self.rare)) if self.rare else {}
            cands = []
            for l in links:
                o = l["other"]
                f = facts.get(o)
                if not f:
                    continue
                # A special or unlabelled item never goes into a pack for anyone but its owner (D60).
                if f.get("sensitivity") in ("special", "unlabelled") and (f.get("owner") or "") != self.asker:
                    continue
                self.titles[o] = f["title"] or f["kind"]
                c = cos.get(o)
                r = relevance_of_cos(c, s)
                words = held.get(o) or []
                if words:
                    r = max(r, float(s.walk_words) * min(1.0, sum(self.rare.get(x, 0.0) for x in words)))
                boosted = o in self.boost_ids
                if boosted:
                    r = min(1.0, r * float(s.context_boost))
                p, pw = prior(f, s)
                h = hub(f, s)
                t = s.type_factor(l["type"])
                if l["type"] in THREAD_TYPES and f.get("kind") == "mail" and parent_kind == "mail":
                    t *= float(s.mail_thread)
                d = float(s.hop_decay)
                step = float(l["strength"]) * t * d
                pi = e["pi"] * step
                score = r * p * h * pi
                cands.append({"id": o, "score": score, "R": r, "P": p, "H": h, "pi": pi, "cos": round(c, 4) if c is not None else None,
                              "words": sorted(words),
                              "path": e["path"] + [{"from": e["id"], "type": l["type"], "dir": l["dir"],
                                                    "strength": round(float(l["strength"]), 3), "T": t, "d": d,
                                                    "link": l["link_id"], "origin": l["origin"]}],
                              "branch": e["branch"], "prior": pw, "degree": f["degree"], "boosted": boosted,
                              "link": {"type": l["type"], "dir": l["dir"], "strength": float(l["strength"]),
                                       "origin": l["origin"], "T": t, "d": d}, "parent": e["id"]})
            # One item reached by several links keeps its best.
            best_of: dict[str, dict] = {}
            for c in cands:
                if c["id"] not in best_of or c["score"] > best_of[c["id"]]["score"]:
                    best_of[c["id"]] = c
            cands = sorted(best_of.values(), key=lambda c: -c["score"])
            frame["opened"].append(dict(self._public(e), tokens=e.get("tokens"), links=len(links)))
            new_all.extend(cands)
            if self.mode != "background":
                self._choose(e, cands, frame)
        if self.mode == "background":
            self._wave(opened, new_all, frame)
        frame.update({"queue": self._queue_top(), "tokens": self.tokens, "budget": self.budget,
                      "gathered": len(self.gathered), "expansions": self.expansions,
                      "db_ms": int(self.db_seconds * 1000)})
        if len(self.frames) < MAX_FRAMES:
            self.frames.append(frame)

    def _choose(self, parent: dict, cands: list[dict], frame: dict) -> None:
        """Width (D43), floor (D44) and nothing-new (D44) for one expanded item."""
        s = self.s
        best = cands[0]["score"] if cands else 0.0
        kept_new = 0
        kept = 0
        for c in cands:
            why = ""
            if c["id"] in self.gathered_ids:
                why = "already gathered"
            elif c["score"] < float(s.floor):
                why = f"under the floor {s.floor}"
            elif c["score"] < float(s.width_ratio) * best and not c.get("words"):
                # One that holds the question's rare words is kept however far below the best child it scores
                # (attempt 38): meaning alone puts the file that names the person asked about under the rest.
                why = f"under {s.width_ratio} of the best child ({best:.4f})"
            elif kept >= int(s.width_cap):
                why = f"past the width cap of {int(s.width_cap)}"
            out = dict(self._public(c), link=c["link"], parent=parent["id"], kept=not why, why=why)
            frame["neighbours"].append(out)
            if not why:
                kept += 1
                was = self.best_in_queue.get(c["id"])
                self._push(c)
                if was is None:
                    kept_new += 1
        b = parent["branch"]
        if kept_new == 0:
            self.branch_empty[b] = self.branch_empty.get(b, 0) + 1
            if self.branch_empty[b] >= int(s.nothing_new):
                self.branch_stopped[b] = (f"{self.branch_empty[b]} expansions in a row added nothing new (D44)")
                frame["branch_stopped"] = {"branch": self.titles.get(b, b), "why": self.branch_stopped[b]}
        else:
            self.branch_empty[b] = 0

    def _wave(self, opened: list[dict], cands: list[dict], frame: dict) -> None:
        """Background frontier scoring: one batched decision call per wave (D71)."""
        s = self.s
        fresh = [c for c in cands if c["id"] not in self.gathered_ids]
        uniq: dict[str, dict] = {}
        for c in fresh:
            if c["id"] not in uniq or c["score"] > uniq[c["id"]]["score"]:
                uniq[c["id"]] = c
        pool = sorted(uniq.values(), key=lambda c: -c["score"])[:int(s.frontier_max)]
        if pool and ai.backend_for("frontier", s) != "off":
            facts = facts_of(self.ds_id, [c["id"] for c in pool])
            state = (f"QUESTION: {self.question}\n\nCANDIDATES:\n" +
                     "\n".join(tx.compact(i + 1, facts[c["id"]], raw_chars=300) for i, c in enumerate(pool) if c["id"] in facts))
            ceiling = "normal"
            for c in pool:
                sens = (facts.get(c["id"]) or {}).get("sensitivity", "private")
                if {"normal": 0, "private": 1, "unlabelled": 1, "special": 2}.get(sens, 1) > \
                        {"normal": 0, "private": 1, "unlabelled": 1, "special": 2}.get(ceiling, 0):
                    ceiling = sens
            got = ai.decide_many("frontier", state, [ai.Noul(f"c{i + 1}", f"Does [{i + 1}] help with this?")
                                                     for i in range(len(pool))],
                                 per_call=30, ceiling=ceiling, settings=s, trace=self.trace,
                                 items=[c["id"] for c in pool], owner=self.owner)
            w = float(s.frontier_weight)
            for i, c in enumerate(pool):
                a = (got.get("answers") or {}).get(f"c{i + 1}")
                if a:
                    r_cos = relevance_of_cos(c.get("cos"), s)
                    c["p_yes"] = round(a["p_yes"], 4)
                    c["R"] = (1 - w) * r_cos + w * a["p_yes"]
                    c["score"] = c["R"] * c["P"] * c["H"] * c["pi"]
            info = {k: v for k, v in got.items() if k not in ("questions", "answers")}
            info["scored"] = len(pool)
            frame["decision"] = info
            self.decisions.append(info)
        by_parent: dict[str, list[dict]] = {}
        for c in pool:
            by_parent.setdefault(c["parent"], []).append(c)
        for e in opened:
            self._choose(e, sorted(by_parent.get(e["id"], []), key=lambda c: -c["score"]), frame)
