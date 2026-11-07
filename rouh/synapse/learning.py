"""Learning from what was used (D57, D76).

For every question a person asked, `use` says which items were shown, by which
path, and which the answer cited. Weekly in the spec, and on a press here: each
link on the path to a cited item moves up 0.05; each link on a path only to
items shown 10 or more times and never cited moves down 0.05. A link never
moves more than 0.3 from where it was made, and a code link never goes under
0.2. Background packs and evaluation runs never count, nor anything a night of
dreaming asked, and no decision model judges what was used: citations are the
only signal (D76, D92). A night of dreaming makes these same moves as a stage of
its own, one change each with Undo (`dreaming.py`).
"""
from __future__ import annotations

from . import datasets, db
from .trace import Trace


#: Questions that never count: a background pack, an evaluation run, and anything a night of dreaming
#: asked (D92: dreaming never learns from its own output).
NOT_COUNTED = ("eval", "dream")


def _unlearned(ds_id: str) -> list[dict]:
    return db.rows("SELECT u.id, u.item_id, u.cited, u.path FROM synapse.use u LEFT JOIN synapse.query q "
                   "ON q.id = u.query_id WHERE u.dataset_id = %s AND u.engaged AND NOT u.learned "
                   "AND coalesce(q.by, '') <> ALL(%s)", (ds_id, list(NOT_COUNTED)))


def plan(ds: dict, s=None) -> dict:
    """The moves usage feedback would make now, without making them: each link with where it is, where it
    would go and why. `apply` makes them; a night of dreaming makes them too, one change each with Undo."""
    s = s or datasets.settings(ds)
    rows = _unlearned(ds["id"])
    shows = {r["item_id"]: r for r in db.rows(
        "SELECT u.item_id, count(*) AS shown, sum(CASE WHEN u.cited THEN 1 ELSE 0 END) AS cited FROM synapse.use u "
        "LEFT JOIN synapse.query q ON q.id = u.query_id WHERE u.dataset_id = %s AND u.engaged "
        "AND coalesce(q.by, '') <> ALL(%s) GROUP BY u.item_id", (ds["id"], list(NOT_COUNTED)))}
    up, down = {}, {}
    for r in rows:
        for link in r.get("path") or []:
            if r["cited"]:
                up[link] = up.get(link, 0) + 1
            else:
                info = shows.get(r["item_id"]) or {}
                if int(info.get("shown") or 0) >= int(s.learn_min_shows) and int(info.get("cited") or 0) == 0:
                    down[link] = down.get(link, 0) + 1
    moves = []
    for link_id in set(up) | set(down):
        link = db.row("SELECT l.*, s.title AS src_title, d.title AS dst_title FROM synapse.link l "
                      "JOIN synapse.item s ON s.dataset_id = l.dataset_id AND s.id = l.src "
                      "JOIN synapse.item d ON d.id = l.dst "
                      "WHERE l.dataset_id = %s AND l.id = %s", (ds["id"], link_id))
        if not link:
            continue
        delta = float(s.learn_step) if link_id in up else -float(s.learn_step)
        lo = float(link["base_strength"]) - float(s.learn_max)
        hi = float(link["base_strength"]) + float(s.learn_max)
        if link["origin"] == "code":
            lo = max(lo, float(s.learn_code_floor))
        new = max(0.0, min(1.0, max(lo, min(hi, float(link["strength"]) + delta))))
        moves.append({"id": link["id"], "src": link["src"], "dst": link["dst"], "type": link["type"],
                      "link": f"{link['src_title']} {link['type']} {link['dst_title']}",
                      "from": round(float(link["strength"]), 3), "to": round(new, 3),
                      "moved": abs(new - float(link["strength"])) > 1e-9,
                      "why": ("on the path to a cited item" if delta > 0 else
                              f"only led to items shown {s.learn_min_shows}+ times and never cited")
                      if abs(new - float(link["strength"])) > 1e-9 else "already at its limit"})
    return {"rows": len(rows), "questions": len({r["id"] for r in rows}), "moves": moves}


def mark_learned(ds_id: str) -> int:
    return db.run("UPDATE synapse.use SET learned = true WHERE dataset_id = %s AND engaged AND NOT learned",
                  (ds_id,))


def apply(ds: dict, *, by: str = "page") -> dict:
    s = datasets.settings(ds)
    trace = Trace(ds["id"], "learn", "Learning from what was used (D57)", by=by)
    with trace.step("read", "Questions a person asked, not yet learned from") as st:
        got = plan(ds, s)
        st.data.update({"rows": got["rows"], "questions": got["questions"]})
    changed = []
    with trace.step("apply", "Links moved, within their limits") as st:
        for m in got["moves"]:
            if m["moved"]:
                db.run("UPDATE synapse.link SET strength = %s, checked_at = now() WHERE id = %s", (m["to"], m["id"]))
            changed.append({k: m[k] for k in ("id", "link", "from", "to", "why")})
        mark_learned(ds["id"])
        st.data.update({"changed": changed, "step": s.learn_step, "max_drift": s.learn_max,
                        "code_floor": s.learn_code_floor})
    trace.finish("done", changed=len(changed))
    return {"ok": True, "trace": trace.id, "changed": changed}
