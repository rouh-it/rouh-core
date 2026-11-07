"""The tiny map (D13 to D18): the one thing that loads every turn.

Nothing lists items. The map is three short sections:

- AREAS: the areas there are, each with one line a helper model writes from the
  area's own claims (code lists them; the model only writes the words, D16).
  An item's area is the owner's when given, otherwise the one the X-ray call
  named (`ingest.area_step`); a new name the model proposes counts here only
  once `area_min_items` items propose it, and until then they are General;
- ACTIVE NOW: what was touched or is waiting in the last 7 days, by code;
- the OWNER'S WORDS: terms the owner uses with a private meaning, proposed by
  the ingest call and added once 3 items use them.

The test for every line: would removing it ever change what the model goes
looking for? It is capped at about 600 words and 1,200 tokens by code (D15),
rebuilt on change at most every 10 minutes (D17), every version kept, and built
per viewer from only what that viewer may see: an area they cannot read is not
on their map at all, not even its name (D18). The owner can pin or edit a line
(D16), and a pinned line is never dropped.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from . import ai, datasets, db, text as tx
from .db import Json
from .trace import Trace

AREA_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["areas"],
    "properties": {"areas": {"type": "array", "items": {
        "type": "object", "additionalProperties": False, "required": ["area", "line"],
        "properties": {"area": {"type": "string"}, "line": {"type": "string"}}}}},
}


def queue(ds: dict, s, *, force: bool = False) -> dict:
    from . import ingest

    pending = db.value("SELECT count(*) FROM synapse.job WHERE dataset_id = %s AND kind = 'map' AND done_at IS NULL",
                       (ds["id"],))
    if pending:
        return {"queued": False, "note": "a map rebuild is already waiting"}
    last = db.value("SELECT max(made_at) FROM synapse.map WHERE dataset_id = %s", (ds["id"],))
    delay = 0.0
    if last is not None and not force:
        gone = (datetime.now(timezone.utc) - last).total_seconds()
        delay = max(0.0, float(s.map_rebuild_minutes) * 60 - gone)
    job = ingest.enqueue(ds["id"], "map", priority=8, delay_s=delay)
    return {"queued": True, "job": job, "waits_s": int(delay),
            "rule": f"at most every {int(s.map_rebuild_minutes)} minutes (D17)"}


def _readable(viewer: str) -> str:
    return ("EXISTS (SELECT 1 FROM synapse.reader r WHERE r.dataset_id = i.dataset_id AND r.item_id = i.id "
            "AND r.principal IN (%s, 'everyone'))")


def _cut(line: str, most: int) -> str:
    w = line.split()
    return " ".join(w[:most]) + ("..." if len(w) > most else "")


def build(ds: dict, viewer: str | None = None, *, by: str = "worker", why: str = "") -> dict:
    s = datasets.settings(ds)
    owner = datasets.owner_of(ds)
    viewer = viewer or datasets.me(ds)
    from . import people
    trace = Trace(ds["id"], "map", f"Map for {people.name_of(viewer)}", by=by)
    try:
        with trace.step("areas", "Areas, listed by code (D16), only those the viewer can read (D18)") as st:
            areas = db.rows(
                "SELECT coalesce(nullif(i.meta->>'area', ''), 'General') AS area, count(*) AS items, "
                "max(i.said_at) AS last FROM synapse.item i WHERE i.dataset_id = %s AND i.deleted_at IS NULL "
                f"AND i.kind NOT IN ('person', 'topic', 'layer', 'rule') AND {_readable(viewer)} "
                "GROUP BY 1 ORDER BY count(*) DESC", (ds["id"], viewer))
            streams = db.rows(
                "SELECT i.kind, count(*) AS items FROM synapse.item i WHERE i.dataset_id = %s AND i.deleted_at IS NULL "
                f"AND i.kind NOT IN ('person', 'topic', 'layer', 'rule') AND {_readable(viewer)} GROUP BY 1 ORDER BY 2 DESC",
                (ds["id"], viewer))
            hidden = db.rows(
                "SELECT DISTINCT coalesce(nullif(i.meta->>'area', ''), 'General') AS area FROM synapse.item i "
                f"WHERE i.dataset_id = %s AND i.deleted_at IS NULL AND NOT {_readable(viewer)}", (ds["id"], viewer))
            hidden = [h["area"] for h in hidden if h["area"] not in {a["area"] for a in areas}]
            st.data.update({"areas": areas, "streams": streams, "left_out_for_this_viewer": len(hidden)})
        with trace.step("area_lines", "Area lines written by the helper model where missing or stale (D16)") as st:
            # An area's line is written from what this viewer may read, and kept
            # per viewer, so nobody's map describes an area from items they
            # cannot see (D18).
            lines = _area_lines(ds, viewer)
            need = []
            for a in areas[:int(s.map_areas)]:
                have = lines.get(a["area"])
                count_then = int(((have or {}).get("text") or "").split("|")[-1]) if have and "|" in have["text"] else 0
                if have and (have["pinned"] or abs(int(a["items"]) - count_then) < 50):
                    continue
                need.append(a)
            st.data["written"] = []
            if need:
                blocks, used = [], []
                for a in need:
                    claims = db.rows(
                        "SELECT i.id, coalesce(i.xray->>'gist', i.title) AS gist FROM synapse.item i WHERE i.dataset_id = %s "
                        "AND coalesce(nullif(i.meta->>'area', ''), 'General') = %s AND i.deleted_at IS NULL AND "
                        f"i.kind NOT IN ('person','topic','rule') AND {_readable(viewer)} ORDER BY i.tier DESC, i.said_at DESC LIMIT 12",
                        (ds["id"], a["area"], viewer))
                    blocks.append(f"AREA {a['area']} ({a['items']} items):\n" + "\n".join("- " + c["gist"] for c in claims))
                    used += [c["id"] for c in claims]
                # The items whose words went into the call, so a deletion finds it (D60, step 5).
                got = ai.generate(model=s.helper_model, name="map_areas", purpose="map_areas", trace=trace, items=used,
                                  owner=owner, schema=AREA_SCHEMA,
                                  instructions=("Write one line per area for a tiny map that tells a model what each "
                                                f"area of a person's memory holds, at most {int(s.map_line_words)} words, "
                                                "plain: the kinds of things and the main subjects in it, never a private "
                                                "detail, a number or an amount. Keep the area names exactly."),
                                  text="\n\n".join(blocks), max_tokens=1500)
                for row in got.get("areas") or []:
                    match = next((a for a in need if a["area"].lower() == str(row.get("area", "")).lower()), None)
                    if not match:
                        continue
                    text = _cut(str(row.get("line") or ""), int(s.map_line_words)) + f"|{match['items']}"
                    db.run("INSERT INTO synapse.map_line (dataset_id, section, key, text, by) VALUES (%s, 'areas', %s, %s, 'model') "
                           "ON CONFLICT (dataset_id, section, key) DO UPDATE SET text = excluded.text, made_at = now() "
                           "WHERE NOT synapse.map_line.pinned", (ds["id"], f"{viewer}:{match['area']}", text))
                    st.data["written"].append({"area": match["area"], "line": text.split("|")[0]})
            lines = _area_lines(ds, viewer)
        with trace.step("active", "Active now, by code: touched or waiting in the last days (D16)") as st:
            since = datetime.now(timezone.utc) - timedelta(days=int(s.active_days))
            active = db.rows(
                "SELECT i.id, i.title, i.kind, i.said_at, i.xray, i.meta FROM synapse.item i WHERE i.dataset_id = %s "
                "AND i.deleted_at IS NULL AND i.kind NOT IN ('person', 'topic', 'layer', 'rule') AND i.said_at >= %s "
                f"AND {_readable(viewer)} ORDER BY i.tier DESC, i.said_at DESC LIMIT 60", (ds["id"], since, viewer))

            def waiting(it):
                return any(c.get("k") in ("ask", "promise") and c.get("open")
                           for c in ((it.get("xray") or {}).get("claims") or []))
            active.sort(key=lambda it: (not waiting(it), -(it["said_at"].timestamp() if it["said_at"] else 0)))
            act_lines = []
            seen_threads = set()
            for it in active:
                thread = (it.get("meta") or {}).get("thread")
                if thread and thread in seen_threads:
                    continue
                seen_threads.add(thread)
                gist = ((it.get("xray") or {}).get("gist") or it["title"])
                line = _cut(f"{it['title']}: {gist}", int(s.map_line_words))
                if waiting(it):
                    line += " (open)"
                act_lines.append({"line": line, "id": it["id"], "date": tx.item_date(it)})
                if len(act_lines) >= int(s.map_active):
                    break
            st.data.update({"since": since.isoformat(), "lines": act_lines})
        with trace.step("terms", "The owner's words, once 3 items use them (D16)") as st:
            terms = db.rows("SELECT w.norm, min(w.term) AS term, max(w.meaning) AS meaning, max(w.area) AS area, "
                            "count(DISTINCT w.item_id) AS items FROM synapse.word_proposal w JOIN synapse.item i ON "
                            "i.dataset_id = w.dataset_id AND i.id = w.item_id WHERE w.dataset_id = %s AND i.deleted_at IS NULL "
                            f"AND {_readable(viewer)} GROUP BY w.norm HAVING count(DISTINCT w.item_id) >= %s ORDER BY 5 DESC",
                            (ds["id"], viewer, int(s.term_min_items)))
            # A line of words pinned by hand in the lab. In Master such a line is moved into the person's Vocabulary
            # as it is next read (`rouh/vocabulary.py`, since 30 October 2026), which is found when a message uses
            # it, not loaded with the map.
            pinned = db.rows("SELECT * FROM synapse.map_line WHERE dataset_id = %s AND section = 'words' "
                             "AND coalesce(meta->>'off', 'false') <> 'true'", (ds["id"],))
            st.data.update({"terms": terms, "pinned": [p["text"] for p in pinned], "bar": int(s.term_min_items),
                            "waiting": db.rows("SELECT min(term) AS term, count(DISTINCT item_id) AS items FROM "
                                               "synapse.word_proposal WHERE dataset_id = %s GROUP BY norm HAVING "
                                               "count(DISTINCT item_id) < %s", (ds["id"], int(s.term_min_items)))})
        with trace.step("assemble", "Assembled and held to the cap by code (D15)") as st:
            out_areas = []
            for a in areas[:int(s.map_areas)]:
                row = lines.get(a["area"])
                line = row["text"].split("|")[0] if row else f"{a['items']} items"
                out_areas.append({"text": f"- {a['area']}: {line}", "pinned": bool(row and row["pinned"])})
            out_active = [{"text": f"- {a['line']}", "pinned": False, "id": a["id"]} for a in act_lines]
            out_words = [{"text": f"- \"{p['text'].split('=')[0].strip()}\" = {p['text'].split('=', 1)[1].strip() if '=' in p['text'] else ''}",
                          "pinned": True} for p in pinned]
            out_words += [{"text": _cut(f"- \"{t['term']}\" = {t['meaning']}" + (f" ({t['area']})" if t["area"] else ""),
                                        int(s.map_line_words) + 4), "pinned": False} for t in terms
                          if tx.norm(t["term"]) not in {tx.norm(p["text"].split("=")[0]) for p in pinned}]
            out_words = out_words[:int(s.map_terms)]
            owner_name = ds.get("owner_name") or "the owner"
            dropped = []

            def render():
                return ("AREAS\n" + "\n".join(x["text"] for x in out_areas) +
                        "\nACTIVE NOW\n" + ("\n".join(x["text"] for x in out_active) or "- nothing in the last days") +
                        f"\n{owner_name.upper()}'S WORDS\n" + ("\n".join(x["text"] for x in out_words) or "- none yet"))
            text = render()
            for section in (out_words, out_active, out_areas):
                while tx.tokens(text) > int(s.map_token_cap):
                    removable = [x for x in section if not x["pinned"]]
                    if not removable:
                        break
                    section.remove(removable[-1])
                    dropped.append(removable[-1]["text"])
                    text = render()
            st.data.update({"text": text, "words": tx.words(text), "tokens": tx.tokens(text),
                            "cap": int(s.map_token_cap), "target_words": int(s.map_words), "dropped_for_cap": dropped})
        version = int(db.value("SELECT coalesce(max(version), 0) FROM synapse.map WHERE dataset_id = %s AND viewer = %s",
                               (ds["id"], viewer)) or 0) + 1
        db.run("INSERT INTO synapse.map (dataset_id, viewer, version, text, lines, tokens, why) VALUES "
               "(%s, %s, %s, %s, %s::jsonb, %s, %s)",
               (ds["id"], viewer, version, text, Json({"areas": out_areas, "active": out_active, "words": out_words}),
                tx.tokens(text), why or "rebuilt on change"))
        trace.finish("done", version=version, tokens=tx.tokens(text))
        return {"ok": True, "version": version, "text": text}
    except Exception as exc:
        trace.finish("failed", error=f"{type(exc).__name__}: {exc}")
        raise


def current(ds: dict, viewer: str | None = None) -> dict | None:
    viewer = viewer or datasets.me(ds)
    return db.row("SELECT * FROM synapse.map WHERE dataset_id = %s AND viewer = %s ORDER BY version DESC LIMIT 1",
                  (ds["id"], viewer))


def text_for(ds: dict, viewer: str) -> str:
    """The map a question is answered with: the viewer's own, built now if there is none yet."""
    got = current(ds, viewer)
    if got:
        return got["text"]
    try:
        return build(ds, viewer, by="query", why="first question from this viewer")["text"]
    except Exception:  # noqa: BLE001
        return ""


def _area_lines(ds: dict, viewer: str) -> dict:
    """This viewer's area lines, by area, and the owner's pinned ones for everyone."""
    out = {}
    for r in db.rows("SELECT * FROM synapse.map_line WHERE dataset_id = %s AND section = 'areas'", (ds["id"],)):
        key = r["key"]
        if key.startswith(viewer + ":"):
            out[key[len(viewer) + 1:]] = r
        elif ":" not in key and r["pinned"]:
            out.setdefault(key, r)
    return out


def pin(ds: dict, section: str, key: str, text: str, pinned: bool = True) -> None:
    db.run("INSERT INTO synapse.map_line (dataset_id, section, key, text, pinned, by) VALUES (%s, %s, %s, %s, %s, 'owner') "
           "ON CONFLICT (dataset_id, section, key) DO UPDATE SET text = excluded.text, pinned = excluded.pinned, "
           "by = 'owner', made_at = now()", (ds["id"], section, key, text[:300], pinned))


def unpin(ds: dict, section: str, key: str) -> None:
    db.run("DELETE FROM synapse.map_line WHERE dataset_id = %s AND section = %s AND key = %s", (ds["id"], section, key))
