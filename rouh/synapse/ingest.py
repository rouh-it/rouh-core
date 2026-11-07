"""Storing, editing and deleting an item, every step written down.

**Storing** (D52: nothing in the hot path waits for a model). The part done at
once, by code, in under a second: the raw item, kept whole with nothing cut from
it (D25), the signals for its tier (D80), its readers (D60), its passages and
their words (D24), and the links that come straight from the data (D30). The
item is searchable by words from that moment. The rest is a job on the queue
(`worker`): the embeddings (D37), the link candidates and their screening (D31,
D74), and one helper call that reads the signals with the whole item and returns
its X-ray, judgement links, tier with a one-line reason, sensitivity and area
(D9, D82), then the quote check (D10),
topics (D34), standing rules (D59), the words for the map (D16), and the layer
and map jobs that follow (D54, D17). Both halves are one trace. Every item but a
person or a topic gets an X-ray (`xray_min_words` is 0, D8). No decision call is
made unless Tune turns decision models on (off since 4 October 2026): an item with
no X-ray gets the helper model's tier call (D80) and keeps its sensitivity as it
came, and the sensitivity suggestions (D75) and short-item links (D74) are decision
calls, so they run only with decision models on, to compare.

**Editing** (D27, D33) keeps the old version, re-cuts and re-embeds, rebuilds
the X-ray, re-checks the item's own judgement links (keep, change or drop),
recomputes its code links, and rebuilds the layers built from it.

**Deleting** (D60) tombstones the item at once, then removes its passages,
vectors, links, readers and use rows, hides and rebuilds every layer claim that
cited it, redacts it from the logged prompts, rebuilds the map, deletes the raw
copy last, and searches every table for its phrases to prove nothing is left.
"""
from __future__ import annotations

import difflib
import json
import logging
import re
import threading
import time
from datetime import datetime, timezone

from . import ai, datasets, db, kinds, mentions, numbers, people, search, text as tx, vectors
from .db import Json
from .trace import Trace

log = logging.getLogger("rouh.synapse.ingest")

CLAIM_KINDS = ["fact", "ask", "promise", "decision", "caveat", "disagreement", "open", "rule"]
STRENGTHS = ["strong", "moderate", "mixed", "weak"]
SENSITIVITY_RANK = {"normal": 0, "unlabelled": 1, "private": 1, "special": 2}
RULE_WORDS = re.compile(r"\s*(from now on|always|never|every time|whenever)\b", re.I)
SPECIAL_AREAS = ("health", "money", "legal", "finance")
TIER_PENDING = "pending: the tier call has not answered yet (D80)"
BULK = re.compile(r"\b(unsubscribe|newsletter|no-?reply|noreply|do not reply|digest|promotion)\b", re.I)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _when(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        got = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return got if got.tzinfo else got.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _list(value) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [v.strip() for v in re.split(r"[;,]\s*(?![^<]*>)", value) if v.strip()]
    return [str(v).strip() for v in value if str(v).strip()]


# ---------------------------------------------------------------------------------------
# small helpers over the tables
# ---------------------------------------------------------------------------------------

def get_item(ds_id: str, item_id: str) -> dict | None:
    try:
        return db.row("SELECT * FROM synapse.item WHERE dataset_id = %s AND id = %s::uuid", (ds_id, str(item_id)))
    except Exception:  # noqa: BLE001
        return None


def find_by_key(ds_id: str, key: str) -> dict | None:
    if not key:
        return None
    return db.row("SELECT * FROM synapse.item WHERE dataset_id = %s AND source_key = %s "
                  "AND deleted_at IS NULL ORDER BY stored_at LIMIT 1", (ds_id, key))


def readers_of(ds_id: str, item_id: str) -> list[str]:
    return [r["principal"] for r in db.rows(
        "SELECT principal FROM synapse.reader WHERE dataset_id = %s AND item_id = %s ORDER BY principal",
        (ds_id, item_id))]


def set_readers(ds_id: str, item_id: str, readers: list[str]) -> None:
    db.run("DELETE FROM synapse.reader WHERE dataset_id = %s AND item_id = %s", (ds_id, item_id))
    for p in sorted(set(readers)):
        db.run("INSERT INTO synapse.reader (dataset_id, item_id, principal) VALUES (%s, %s, %s) "
               "ON CONFLICT DO NOTHING", (ds_id, item_id, p))


def add_link(ds_id: str, src: str, dst: str, link_type: str, strength: float, *, origin: str,
             made_by: str = "", claim_idx: int | None = None, why: str = "", evidence: dict | None = None) -> dict:
    """One typed, weighted link, or the same link brought up to date."""
    if not src or not dst or src == dst:
        return {}
    got = db.row(
        "INSERT INTO synapse.link (dataset_id, src, dst, type, strength, base_strength, origin, made_by, "
        "claim_idx, why, evidence) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb) "
        "ON CONFLICT (dataset_id, src, dst, type) DO UPDATE SET strength = excluded.strength, "
        "base_strength = excluded.base_strength, origin = excluded.origin, made_by = excluded.made_by, "
        "claim_idx = excluded.claim_idx, why = excluded.why, evidence = excluded.evidence, checked_at = now() "
        "RETURNING id, (xmax = 0) AS made",
        (ds_id, src, dst, link_type, float(strength), float(strength), origin, made_by, claim_idx,
         why[:500], Json(evidence or {})))
    return got or {}


def link_rows(ds_id: str, item_id: str) -> list[dict]:
    return db.rows(
        "SELECT l.*, s.title AS src_title, s.kind AS src_kind, d.title AS dst_title, d.kind AS dst_kind "
        "FROM synapse.link l JOIN synapse.item s ON s.dataset_id = l.dataset_id AND s.id = l.src "
        "JOIN synapse.item d ON d.id = l.dst "
        "WHERE l.dataset_id = %s AND (l.src = %s OR l.dst = %s) ORDER BY l.type, l.strength DESC",
        (ds_id, item_id, item_id))


def get_in_scope(ds: dict, item_id: str) -> dict | None:
    """An item of this dataset, or a person of its owner's people set (decision 7)."""
    try:
        return db.row("SELECT * FROM synapse.item WHERE dataset_id = ANY(synapse.scope(%s)) AND id = %s::uuid",
                      (ds["id"], str(item_id)))
    except Exception:  # noqa: BLE001
        return None


def derive(ds_id: str, child_table: str, child_id: str, item_ids) -> None:
    for item_id in set(str(i) for i in item_ids if i):
        db.run("INSERT INTO synapse.derived (dataset_id, child_table, child_id, item_id) VALUES (%s, %s, %s, %s)",
               (ds_id, child_table, str(child_id), item_id))


def enqueue(ds_id: str, kind: str, *, item_id: str | None = None, trace_id: str | None = None,
            payload: dict | None = None, priority: int = 5, delay_s: float = 0, lane: str = "live") -> int:
    """A job on the queue; `lane` 'backfill' for an import's work, which never takes a live slot.

    An item's ingest or embed asked for again while the same job still waits, not started, is that
    job (card 1125, change 5): it runs once, at the sooner of the two priorities, and its trace is
    the first one's (a job with a trace of its own, as a new item's is, or a payload, is always new).
    A job already running is not waited for: the new one runs after it, because
    the item may have changed since it started (`worker._claim` keeps one job of an item at a time)."""
    from . import worker

    lane = "backfill" if lane == "backfill" else "live"

    def insert() -> int:
        return db.value(
            "INSERT INTO synapse.job (dataset_id, kind, item_id, trace_id, payload, priority, not_before, lane) "
            "VALUES (%s, %s, %s, %s, %s::jsonb, %s, now() + make_interval(secs => %s), %s) RETURNING id",
            (ds_id, kind, item_id, trace_id, Json(payload or {}), priority, float(delay_s), lane))

    if not (item_id and kind in SAME_JOB_KINDS and not payload and not trace_id):
        # Nothing it could be the same as (a new item's job carries its trace): one statement, as before.
        job = insert()
    else:
        with db.atomic():
            db.run("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"synapse.job:{ds_id}:{item_id}:{kind}",))
            waiting = db.row(
                "SELECT id FROM synapse.job WHERE dataset_id = %s AND item_id = %s AND kind = %s "
                "AND done_at IS NULL AND locked_by IS NULL AND payload = '{}'::jsonb ORDER BY id LIMIT 1",
                (ds_id, item_id, kind))
            if waiting:
                db.run("UPDATE synapse.job SET priority = least(priority, %s), lane = CASE WHEN %s = 'live' "
                       "THEN 'live' ELSE lane END, not_before = least(not_before, now() + make_interval(secs => %s)) "
                       "WHERE id = %s", (priority, lane, float(delay_s), waiting["id"]))
                job = waiting["id"]
            else:
                job = insert()
    worker.poke()
    return job


#: Jobs that mean the same thing however often they are asked for: an item's model part, its vectors.
SAME_JOB_KINDS = ("ingest", "embed")


def release(job_id: int | None) -> None:
    """A job `store` or `edit` held (`hold`), let go now: its caller has added what it had to."""
    from . import worker

    if job_id:
        db.run("UPDATE synapse.job SET not_before = least(not_before, now()) WHERE id = %s AND done_at IS NULL",
               (job_id,))
        worker.poke()


def person_for(ds: dict, who: str, item: dict | None = None, *, readers=None,
               made_by: str = "") -> tuple[dict | None, str]:
    """The person an address in an item is (decision 8): looked up by identifier first, made with
    origin 'synapse' when it matches nobody. Replaced `contact_for` on 3 October 2026."""
    return people.resolve(ds, who, made_from=str((item or {}).get("id") or ""), readers=readers, made_by=made_by)


# ---------------------------------------------------------------------------------------
# storing: the part code does at once
# ---------------------------------------------------------------------------------------

FROZEN_WORDS = ("This dataset is a frozen benchmark snapshot (rouh/synapse/snapshot.py): nothing is stored into it, "
                "edited or deleted, so its numbers stay comparable night after night.")


def store(ds: dict, payload: dict, *, by: str = "page", wait: bool = False, lane: str = "live",
          hold: bool = False) -> dict:
    """Store one item: code's part now, the model's part as a job. Returns the item and trace ids.

    The item is found by its words the moment this returns. `lane` 'backfill' puts the model's part
    (embedding, link candidates, the X-ray and its judgement links) on the queue's backfill lane, as an
    import does, so it never delays live mail (`worker`). `hold` keeps the model's part from starting
    until the caller has added what is its own and lets it go (`release`), as the meeting sync does
    with a transcript's passages (`meetings.py`); if it never does, the job runs five minutes later."""
    if ds.get("frozen"):
        return {"ok": False, "why": FROZEN_WORDS}
    s = datasets.settings(ds)
    kind = str(payload.get("kind") or "note").strip().lower()
    if kind == "contact":
        kind = "person"
    if kind not in numbers.KINDS or kind in ("layer",):
        kind = "note"
    if kind == "person":
        return store_person(ds, payload, by=by)
    # A NUL is refused in any PostgreSQL text or JSON value, and a file can hold one (a minified script
    # did): taken out, so it never stops the item from being stored.
    raw = str(payload.get("text") or payload.get("raw") or "").replace("\x00", "")
    title = " ".join(str(payload.get("title") or "").replace("\x00", "").split())[:300]
    given = bool(title)
    if not given:
        title = code_title(raw, kind)
    source = str(payload.get("source") or "lab")[:80]
    key = str(payload.get("source_key") or payload.get("key") or "").strip()[:300]
    if not key:
        import uuid
        key = f"{kind}-{uuid.uuid4().hex[:10]}"
    existing = db.row("SELECT id, deleted_at FROM synapse.item WHERE dataset_id = %s AND source = %s "
                      "AND source_key = %s", (ds["id"], source, key))
    if existing and existing.get("deleted_at") is None and _list(payload.get("attached_to")):
        # The same file on another email: one item, linked to each email it came on.
        return attach(ds, existing["id"], _list(payload.get("attached_to")), by=by)
    if existing and existing.get("deleted_at") is None:
        # The same thing arriving twice is an update, not a duplicate (D22).
        # Only a given title replaces the one it has; otherwise the model's part writes it again.
        return edit(ds, existing["id"], {"text": raw, **({"title": title} if given else {}), **{
            k: v for k, v in payload.items() if k not in ("text", "raw", "title")}}, by=by, hold=hold)
    if existing:
        # A tombstone keeps the key so a re-sync does not bring it back (D60, step 6).
        return {"ok": False, "why": "That item was deleted, and its source key is kept so it is not "
                                    "stored again. Give it a new key to store it as new."}
    said_at = _when(payload.get("said_at")) or _now()
    meta = {k: payload[k] for k in ("from", "to", "cc", "thread", "reply_to", "task", "project", "area",
                                    "headers", "starred", "rule_for", "scope", "attached_to", "email",
                                    "file_name", "language", "status", "known", "start", "end", "place", "attendees",
                                    "name", "address", "coordinates", "file_type", "file_size", "sha256",
                                    "file_read", "file_mtime", "messages", "card_version", "gmail", "gcal",
                                    "meeting", "slack")
            if payload.get(k) not in (None, "", [])}
    for field in ("to", "cc", "rule_for", "attached_to"):
        if field in meta:
            meta[field] = _list(meta[field])
    if kind == "topic":
        meta["norm"] = _norm_topic(title)
    if meta.get("area"):
        meta["area"] = _area_name(meta["area"])
        meta["area_by"] = "owner"
    meta["title_by"], meta["title_why"] = ("given", "it came with the item") if given else (
        "code", "none came with the item, so code took the first words of the text until the model writes one")
    meta = kinds.fill(kind, meta, title=title, said_at=said_at)
    problems = kinds.check(kind, meta)
    if problems:
        return {"ok": False, "why": " ".join(problems)}
    owner = people.reader_id(ds, payload.get("owner")) if payload.get("owner") else None
    if not owner or owner == people.EVERYONE:
        owner = datasets.me(ds)
    trace = Trace(ds["id"], "store", f"Store: {title}", by=by)
    try:
        return _store_code_part(ds, s, trace, payload, kind=kind, raw=raw, title=title, source=source, key=key,
                                said_at=said_at, meta=meta, owner=owner, by=by, wait=wait, lane=lane, hold=hold)
    except Exception as exc:
        # Said on the run, not left running: an import tries the item again (`batch`).
        trace.finish("failed", error=f"{type(exc).__name__}: {exc}"[:500])
        raise


def _store_code_part(ds: dict, s, trace, payload: dict, *, kind: str, raw: str, title: str, source: str, key: str,
                     said_at, meta: dict, owner: str, by: str, wait: bool, lane: str, hold: bool = False) -> dict:
    started = time.time()

    with trace.step("raw", "The raw item, kept unchanged") as st:
        # Nothing is cut (D25, revised 4 October 2026): quoted replies and
        # signatures are context, so the whole text is what is searched.
        body = raw
        st.data.update({"kind": kind, "title": title, "title_by": meta["title_by"], "title_why": meta["title_why"],
                        "area": meta.get("area") or "", "area_by": meta.get("area_by") or "",
                        "source": source, "source_key": key,
                        "said_at": said_at.isoformat(), "meta": meta, "raw": raw[:20000],
                        "words": tx.words(raw), "chars": len(raw)})
    with trace.step("clean", "Nothing cut: the whole text is kept (D25)") as st:
        st.data.update({"words": tx.words(body), "chars": len(body),
                        "note": "Code cuts nothing from the text. Quoted replies, signatures and everything "
                                "else stay in, and the whole text becomes the passages, the words searched, "
                                "the embeddings and what the X-ray reads, the same for every kind of item."})

    parents = [p for p in (find_by_key(ds["id"], k) for k in _list(meta.get("attached_to"))) if p]
    if parents and not _list(payload.get("readers")) and not payload.get("sensitivity"):
        # A file is read by whoever reads the email it came on, at that email's sensitivity.
        payload = {**payload, **_parents_say(ds["id"], parents)}
    with trace.step("readers", "Readers by code, and sensitivity only if it was given with the item (D60)") as st:
        readers = people.reader_ids(ds, _list(payload.get("readers"))) or [owner]
        sens, sens_why = code_sensitivity(payload, meta)
        st.data.update({"readers": readers, "reader_names": [people.name_of(r) for r in readers],
                        "sensitivity": sens, "why": sens_why,
                        "note": "Readers decide who may see it, in every query (D38). Sensitivity "
                                "only adds restrictions; it is never the permission check. Code does not "
                                "guess it from words: the model sets it when it reads the item (X-ray)."})

    item = db.row(
        "INSERT INTO synapse.item (dataset_id, kind, source, source_key, title, raw, body, said_at, tier, "
        "tier_why, tier_by, tier_signals, sensitivity, sensitivity_why, owner, meta, status) VALUES (%s, %s, %s, "
        "%s, %s, %s, %s, %s, 1, %s, 'pending', NULL, %s, %s::jsonb, %s, %s::jsonb, 'stored') RETURNING *",
        (ds["id"], kind, source, key, title, raw, body, said_at, TIER_PENDING, sens,
         Json(_given_why(payload, sens_why)), owner, Json(meta)))
    trace.set_item(item["id"])
    set_readers(ds["id"], item["id"], readers)
    if payload.get("gold_people"):
        set_mentions_gold(ds["id"], item["id"], payload["gold_people"])

    with trace.step("words", "Passages and their words, searchable at once (D24, D52)") as st:
        made = write_passages(ds["id"], item["id"], title, body, s)
        st.data.update({"passages": made, "size_tokens": s.passage_tokens, "overlap": s.passage_overlap,
                        "configs": ["english", "synapse.bg (Bulgarian word forms)", "simple"]})

    with trace.step("code_links", "Links from the data, written by code (D30)") as st:
        made = code_links(ds, item, s)
        st.data.update({"links": made, "count": len(made)})

    if kind == "rule":
        with trace.step("rule", "A standing rule, attached, never searched (D59)") as st:
            st.data.update({"rule_for": meta.get("rule_for") or [], "scope": meta.get("scope") or "",
                            "note": "Rules load whenever what they govern is in play, and are never "
                                    "ranked, decayed or cut by a budget."})

    db.run("UPDATE synapse.item SET status = 'words' WHERE id = %s", (item["id"],))
    trace.summary.update({"code_ms": int((time.time() - started) * 1000)})
    with trace.step("queued", "The model's part, queued (D52)") as st:
        # A caller that waits runs the job itself; the delay keeps the queue's
        # own worker from taking it first.
        job = enqueue(ds["id"], "ingest", item_id=item["id"], trace_id=trace.id, priority=4,
                      delay_s=300 if (wait or hold) else 0, lane=lane)
        st.data.update({"job": job, "lane": "backfill" if lane == "backfill" else "live",
                        "note": "The tier call, embedding, link candidates, X-ray and judgement links run on the "
                                "queue" + (" (backfill lane: an import's work, which never takes a slot live "
                                           "items need)" if lane == "backfill" else "")
                                + "; the item is already found by its words."})
    db.run("UPDATE synapse.trace SET status = 'queued' WHERE id = %s", (trace.id,))
    if wait:
        from . import worker
        worker.run_job_now(job)
    return {"ok": True, "item": item["id"], "trace": trace.id, "job": job}


def set_mentions_gold(ds_id: str, item_id: str, gold) -> dict | None:
    """An item's gold people for Evaluate: the people_mentioned its X-ray should find (Q21).

    `{"people": [{"name", "emails", "phones", "handles"}], "unattributed": [{"kind", "value"}]}`;
    anything else, or nothing at all, clears it. Never read by the X-ray call itself."""
    clean = None
    if isinstance(gold, dict) and (gold.get("people") or gold.get("unattributed")):
        def strings(v):
            return [str(x).strip() for x in (v or []) if str(x).strip()]
        clean = {"people": [{"name": " ".join(str(p.get("name") or "").split()),
                             **{k: strings(p.get(k)) for k in ("emails", "phones", "handles")}}
                            for p in gold.get("people") or [] if isinstance(p, dict) and str(p.get("name") or "").strip()],
                 "unattributed": [{"kind": u.get("kind") if u.get("kind") in ("email", "phone", "handle") else "email",
                                   "value": str(u.get("value") or "").strip()}
                                  for u in gold.get("unattributed") or [] if isinstance(u, dict) and u.get("value")]}
    db.run("UPDATE synapse.item SET mentions_gold = %s::jsonb WHERE dataset_id = %s AND id = %s",
           (Json(clean) if clean else None, ds_id, item_id))
    return clean


def store_person(ds: dict, payload: dict, *, by: str = "page") -> dict:
    """A person typed or pasted into the lab: looked up by their address or phone first, made in the
    dataset's people home otherwise. Code only; no model call (decision 10)."""
    title = " ".join(str(payload.get("title") or payload.get("name") or "").split())[:200]
    raw = str(payload.get("text") or payload.get("raw") or "")
    emails = [e for e in [people.norm_email(x) for x in _list(payload.get("email")) + _list(payload.get("emails"))] if e]
    phones = [p for p in [people.norm_phone(x) for x in _list(payload.get("phone")) + _list(payload.get("phones"))] if p]
    found = re.findall(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", raw)
    emails += [e for e in (people.norm_email(x) for x in found) if e and e not in emails]
    title = title or (tx.first_sentence(raw, 6) if raw and not found else "") or (emails[0] if emails else "")
    if not title and not phones:
        return {"ok": False, "why": "A person needs a name, an address or a phone number."}
    scope = people.home(ds)
    trace = Trace(scope["id"], "store", f"Person: {title or phones[0]}", by=by)
    with trace.step("match", "Matched by their identifiers first, never by name alone (decision 3)") as st:
        pid, how = None, ""
        for t, vals in (("email", emails), ("phone", phones)):
            for v in vals:
                pid = pid or people.find(scope["id"], t, v)
                how = how or (f"{t} {v}" if pid else "")
        st.data.update({"emails": emails, "phones": phones, "matched": bool(pid), "by": how or "nothing matched"})
    if pid:
        trace.set_item(pid)
        for e in emails:
            people.add_identity(scope["id"], pid, "email", e, e, f"typed into the lab ({by})")
        for p in phones:
            people.add_identity(scope["id"], pid, "phone", p, p, f"typed into the lab ({by})")
        if title:
            people.add_identity(scope["id"], pid, "name", people.norm_name(title), title, f"typed into the lab ({by})")
        trace.finish("done", matched=how)
        return {"ok": True, "item": pid, "trace": trace.id, "matched": how}
    with trace.step("made", "A new person, origin synapse (decision 5)") as st:
        readers = people.reader_ids(ds, _list(payload.get("readers"))) or [people.EVERYONE]
        try:
            person = people.create(scope, name=title or phones[0], origin="synapse", emails=emails, phones=phones,
                                   readers=readers, why=f"typed into the lab ({by})",
                                   extra={"known": True} if payload.get("known") else None,
                                   owner=datasets.me(ds) if scope["id"] == ds["id"] else None)
        except ValueError as exc:
            st.data["refused"] = str(exc)
            trace.finish("failed", error=str(exc))
            return {"ok": False, "why": str(exc), "trace": trace.id}
        trace.set_item(person["id"])
        st.data.update({"person": person["id"], "name": person["title"], "readers": readers,
                        "likely_same": people.flag_same_name(scope["id"], person["id"]),
                        "note": "Words only: no vector until something links to them (decision 10)."})
    trace.finish("done")
    return {"ok": True, "item": person["id"], "trace": trace.id}


def code_title(raw: str, kind: str) -> str:
    """The title code makes when none is given: the text's first words."""
    return tx.first_sentence(raw, 12) or kind


def title_by(item: dict) -> str:
    """Who made an item's title: 'given', 'code' or 'model'. Items stored before the flag
    count as code-made when their title is what code would make, or is cut off with '...'."""
    by = (item.get("meta") or {}).get("title_by")
    if by in ("given", "code", "model"):
        return by
    title = item.get("title") or ""
    if title == code_title(item.get("raw") or "", item.get("kind") or "") or title.endswith("..."):
        return "code"
    return "given"


def _model_title(value) -> str:
    title = " ".join(str(value or "").split()).strip(" \"'.")
    words = title.split()
    return " ".join(words[:14])[:160] if words else ""


def write_title(ds: dict, item: dict, xray: dict, trace, *, editing: bool) -> tuple[str, dict]:
    """The title the X-ray call wrote, used only when the item's title was not given."""
    by = title_by(item)
    proposed = _model_title(xray.get("_title"))
    info = {"before": item.get("title"), "by_before": by, "proposed": proposed}
    if by == "given":
        info.update({"after": item.get("title"), "by": "given",
                     "why": "a title the person gave, or that came with the item, is never overwritten"})
        return "Title kept: given", info
    if not proposed:
        info.update({"after": item.get("title"), "by": by, "why": "the model wrote no title, so the one there stays"})
        return f"Title kept: {by}", info
    meta = dict(item.get("meta") or {})
    meta.update({"title_by": "model", "title_why": f"written by {xray.get('_model') or 'the helper model'} "
                                                   "in the X-ray call, because no title was given"})
    db.run("UPDATE synapse.item SET title = %s, meta = %s::jsonb WHERE id = %s", (proposed, Json(meta), item["id"]))
    item["title"], item["meta"] = proposed, meta
    if not editing:
        trace.set_title(f"Store: {proposed}")
    info.update({"after": proposed, "by": "model", "why": meta["title_why"]})
    return "Title written by the model", info


def _area_name(value) -> str:
    """An area's name as kept: one line, no quote marks, at most 4 words and 40 characters."""
    words = " ".join(str(value or "").split()).strip(" \"'.").split()
    return " ".join(words[:4])[:40]


def _media_words(s) -> set[str]:
    raw = str((s or {}).get("area_not_media") or numbers.BY_KEY["area_not_media"].value)
    return {w.strip().lower() for w in raw.split(",") if w.strip()}


def area_guard(name: str, s) -> dict:
    """An area the model named, held to D83: an area is a part of the owner's life or work, never how an
    item came or what kind it is. A name made only of `area_not_media` words is refused (`name` is ""),
    those words at either end are taken off, and anything else is kept as it was said."""
    said = _area_name(name)
    media = _media_words(s)
    words = said.split()
    plain = [re.sub(r"[^\w-]", "", w).lower() for w in words]
    lo, hi = 0, len(words)
    while lo < hi and (plain[lo] in media or not plain[lo]):
        lo += 1
    while hi > lo and (plain[hi - 1] in media or not plain[hi - 1]):
        hi -= 1
    kept = " ".join(words[lo:hi]).strip(" ,;:-&()")
    if not any(ch.isalpha() for ch in kept):
        kept = ""
    if not said:
        return {"name": "", "said": "", "changed": False, "why": ""}
    if not kept:
        return {"name": "", "said": said, "changed": True,
                "why": f"{said} names how an item came or what kind it is, not a part of the owner's life or "
                       "work, so it is refused (D83)"}
    if kept != said:
        return {"name": kept, "said": said, "changed": True,
                "why": f"{said} has words that name how an item came or what kind it is, so it is kept as "
                       f"{kept} (D83)"}
    return {"name": said, "said": said, "changed": False, "why": ""}


def silos_step(ds: dict, item: dict, xray: dict, trace) -> None:
    """The silos the X-ray call read the item to be in, chosen from the owner's own (`rouh/silos.py`),
    written only where nothing stronger set them: silos Petar gave, or ones the item's source decides, are
    kept as they are. A name the model gave that is no silo is dropped, and said in the trace."""
    from .. import silos

    said = xray.get("_silos")
    if said is None:
        return
    row = db.row("SELECT silos, silos_by FROM synapse.item WHERE id = %s", (item["id"],)) or {}
    by, now = row.get("silos_by") or "", list(row.get("silos") or [])
    uid, oid = ds["user_id"], ds["org_id"]
    got, dropped = [], []
    for name in said if isinstance(said, list) else [said]:
        found = silos.find(uid, oid, name)
        if found is None:
            dropped.append(str(name))
        elif found.key not in got:
            got.append(found.key)
    got = silos.ordered(uid, oid, got)
    if by in (silos.BY_PERSON, silos.BY_SOURCE):
        with trace.step("silos", f"Silos kept: set by {'the owner' if by == 'person' else 'its source'}") as st:
            st.data.update({"silos": now, "by": by, "model_said": said})
        return
    if not got:
        if by == silos.BY_MODEL:
            db.run("UPDATE synapse.item SET silos = '{}', silos_by = '', silos_why = '' WHERE id = %s", (item["id"],))
        with trace.step("silos", "Silos: the item does not say") as st:
            st.data.update({"silos": [], "by": "", "before": now, "not_silos": dropped})
        return
    db.run("UPDATE synapse.item SET silos = %s::text[], silos_by = 'model', silos_why = %s WHERE id = %s",
           (got, "the X-ray read it", item["id"]))
    item["silos"] = got
    with trace.step("silos", f"Silos: {silos.said(uid, oid, got)}, as the X-ray read it") as st:
        st.data.update({"silos": got, "by": "model", "before": now, "not_silos": dropped})


def silos_line(ds: dict) -> str:
    """The owner's silos as the X-ray is shown them: each name, and what its words say it covers."""
    from .. import silos

    out = []
    for s_ in silos.of_ds(ds):
        out.append(s_.name + (f" ({', '.join(s_.words[:24])})" if s_.words else ""))
    return "; ".join(out) or "none"


def area_by(item: dict) -> str:
    """Who set an item's area: 'owner', 'model', or '' when it has none. An area stored before
    the flag came with the item, so it counts as the owner's."""
    meta = item.get("meta") or {}
    by = meta.get("area_by")
    if by in ("owner", "model"):
        return by
    return "owner" if meta.get("area") else ""


AREA_KINDS = "('person', 'topic', 'layer', 'rule')"


def area_list(ds_id: str, except_item: str | None = None, s=None) -> list[dict]:
    """The dataset's areas for the X-ray call: the real ones in use, then the proposed ones still waiting,
    each with its item count. The map counts the same items (`mapping.build`). Read from
    `synapse.area_count` (migration 0075), so it costs the 60 rows it shows, not the dataset.
    An area whose name is a medium or a kind (D83) is never shown, so it is never chosen again: an
    "Email" made before the guard would otherwise take every later email, as it did on 4 October 2026."""
    own = _own_area(ds_id, except_item)
    got = _counted(ds_id, "real", own, 40) + _counted(ds_id, "waiting", own, 20)
    return [a for a in got if area_guard(a["name"], s)["name"] == a["name"]]


def proposals(ds_id: str, except_item: str | None = None, *, limit: int = 100) -> list[dict]:
    """New areas the model proposed that are not real yet, each with how many items propose it."""
    return _counted(ds_id, "waiting", _own_area(ds_id, except_item), limit)


def _own_area(ds_id: str, item_id: str | None) -> tuple[str, str] | None:
    """The (state, area) an item is counted in, if it is counted in one."""
    if not item_id:
        return None
    it = get_item(ds_id, item_id)
    if not it or it.get("deleted_at") is not None or it["kind"] in ("person", "topic", "layer", "rule"):
        return None
    m = it.get("meta") or {}
    if m.get("area"):
        return "real", str(m["area"]).lower()
    if m.get("area_proposed"):
        return "waiting", str(m["area_proposed"]).lower()
    return None


def _counted(ds_id: str, state: str, own: tuple[str, str] | None, limit: int) -> list[dict]:
    """The top `limit` areas of one state, without the one item asked about (it may be in one already)."""
    own = own[1] if own and own[0] == state else None
    got = db.rows("SELECT key, name, items FROM synapse.area_count WHERE dataset_id = %s AND state = %s AND items > 0 "
                  "ORDER BY items DESC, name LIMIT %s", (ds_id, state, int(limit) + 1))
    out = []
    for r in got:
        n = int(r["items"]) - (1 if r["key"] == own else 0)
        if n > 0:
            out.append({"name": r["name"], "items": n, "state": state})
    out.sort(key=lambda a: (-a["items"], a["name"]))
    return out[:int(limit)]


def area_line(a: dict) -> str:
    n = int(a["items"])
    items = f"{n} item" + ("" if n == 1 else "s")
    return f"{a['name']} ({items})" if a["state"] == "real" else f"{a['name']} ({items}, proposed, not an area yet)"


def _raise_for_area(item: dict, area: str) -> dict | None:
    """A model-set area in health, money, legal or finance makes the item special, as code_sensitivity
    does for a given area. It only ever raises; readers stay the permission check."""
    if area.lower() not in SPECIAL_AREAS:
        return None
    before = item.get("sensitivity") or "unlabelled"
    if SENSITIVITY_RANK.get(before, 1) >= SENSITIVITY_RANK["special"]:
        return None
    why = dict(item.get("sensitivity_why") or {})
    why["area"] = f"in the {area} area, which the model chose"
    db.run("UPDATE synapse.item SET sensitivity = 'special', sensitivity_why = %s::jsonb WHERE id = %s",
           (Json(why), item["id"]))
    item["sensitivity"], item["sensitivity_why"] = "special", why
    return {"before": before, "after": "special", "why": why["area"]}


def _set_area(item: dict, area: str, why: str) -> dict:
    """Write a model-chosen area onto an item; returns what changed in its sensitivity, if anything."""
    meta = dict(item.get("meta") or {})
    meta.pop("area_proposed", None)
    meta.update({"area": area, "area_by": "model", "area_why": why})
    db.run("UPDATE synapse.item SET meta = %s::jsonb WHERE id = %s", (Json(meta), item["id"]))
    item["meta"] = meta
    return {"sensitivity": _raise_for_area(item, area)}


def area_step(ds: dict, item: dict, xray: dict, s, trace) -> None:
    """The area the X-ray call named (D16): kept when the owner set one, used when it is an area the
    dataset has, or proposed when it is new, and made real once `area_min_items` items propose it."""
    from . import mapping

    meta = dict(item.get("meta") or {})
    by = area_by(item)
    before = meta.get("area") or ""
    guard = area_guard(xray.get("_area"), s)
    said = guard["name"]
    bar = int(s.area_min_items)
    model = xray.get("_model") or "the helper model"
    info = {"before": before or "General", "set_by_before": by or "nobody",
            "the_model_said": guard["said"] or "nothing",
            "areas_shown": [area_line(a) for a in xray.get("_areas_shown") or []], "bar": bar}
    if guard["changed"]:
        info["guard"] = {"said": guard["said"], "kept": said or "nothing", "why": guard["why"]}

    if by == "owner":
        info.update({"after": before or "General", "set_by": "owner",
                     "note": f"The owner set this item's area to {before or 'none (General)'}, so the model's "
                             f"suggestion ({said or 'none'}) is shown here and not used. What the owner sets "
                             "is never changed by the model."})
        with trace.step("area", "Area kept: set by the owner (D16)") as st:
            st.data.update(info)
        return
    if not said or said.lower() == "general":
        refused = guard["changed"] and not said
        info.update({"after": before or "General", "set_by": by or "nobody",
                     "note": (f"The model named {guard['said']}, which says how the item came or what kind it "
                              "is, not a part of the owner's life or work, so code refused it (D83) and the item "
                              f"stays where it was: {before or 'General'}." if refused else
                              f"The model named no area for this item, so it stays where it was: {before or 'General'}.")})
        with trace.step("area", "Area refused: a medium or a kind is never an area (D83)" if refused else
                        "Area kept: the model named none (D16)") as st:
            st.data.update(info)
        return

    real = db.value("SELECT meta->>'area' FROM synapse.item WHERE dataset_id = %s AND deleted_at IS NULL "
                    f"AND kind NOT IN {AREA_KINDS} AND lower(meta->>'area') = lower(%s) AND id <> %s "
                    "ORDER BY stored_at LIMIT 1", (ds["id"], said, item["id"]))
    if real:
        if before == real:
            info.update({"after": real, "set_by": "model",
                         "note": f"The model put this item in {real} again, where it already was. Nothing changes."})
            with trace.step("area", "Area kept: the model chose the same one (D16)") as st:
                st.data.update(info)
            return
        changed = _set_area(item, real, f"chosen by {model} in the X-ray call, from the areas the dataset has")
        info.update({"after": real, "set_by": "model", **changed,
                     "map": mapping.queue(ds, s),
                     "note": f"No area came with this item, so the model chose one the dataset already has: {real}. "
                             "The item is now in that area on the map, and the map is marked to be rebuilt."
                             + (" The area is one of health, money, legal or finance, so the item's sensitivity "
                                "was raised to special." if changed["sensitivity"] else "")})
        with trace.step("area", "Area chosen by the model: one the dataset has (D16)") as st:
            st.data.update(info)
        return

    # A new name: proposed on the item, which stays under General until enough items propose it.
    meta.pop("area", None)
    meta.pop("area_by", None)
    meta.update({"area_proposed": said, "area_why": f"proposed by {model} in the X-ray call"})
    db.run("UPDATE synapse.item SET meta = %s::jsonb WHERE id = %s", (Json(meta), item["id"]))
    item["meta"] = meta
    waiting = db.rows("SELECT id, title, meta, sensitivity, sensitivity_why FROM synapse.item WHERE dataset_id = %s "
                      f"AND deleted_at IS NULL AND kind NOT IN {AREA_KINDS} AND coalesce(meta->>'area', '') = '' "
                      "AND lower(meta->>'area_proposed') = lower(%s) ORDER BY stored_at", (ds["id"], said))
    info.update({"proposed": said, "items_proposing": len(waiting)})
    if len(waiting) < bar:
        if before:
            info["map"] = mapping.queue(ds, s)
        info.update({"after": "General", "set_by": "nobody yet",
                     "note": f"No area came with this item and none of the dataset's real areas fit, so the model proposed "
                             f"a new one: {said}. A new area becomes real only once {bar} items propose it, and so "
                             f"far {len(waiting)} {'does' if len(waiting) == 1 else 'do'}, so this item stays under "
                             "General for now with the proposal kept on it." + (f" It was in {before} before." if before else "")})
        with trace.step("area", "Area proposed by the model, waiting (D16)") as st:
            st.data.update(info)
        return

    # Enough items propose it: it becomes a real area, spelt the way most of them spell it.
    spellings: dict[str, int] = {}
    for w in waiting:
        name = (w.get("meta") or {}).get("area_proposed") or said
        spellings[name] = spellings.get(name, 0) + 1
    name = max(spellings, key=lambda k: spellings[k])
    info.update({"after": name, "set_by": "model", "made_real": name,
                 "note": f"No area came with this item and none of the dataset's real areas fit, so the model proposed "
                         f"{said}. With this item, {len(waiting)} items propose it, which reaches the bar of {bar}, "
                         f"so {name} becomes a real area on the map. Every item that proposed it moves into it, "
                         "one step each below, and the map is marked to be rebuilt."
                         + (f" This item was in {before} before." if before else "")})
    with trace.step("area", "A new area made real (D16)") as st:
        st.data.update(info)
    for w in waiting:
        changed = _set_area(w, name, f"proposed by the model, and made a real area once {len(waiting)} items "
                                     f"proposed it (at least {bar})")
        if str(w["id"]) == str(item["id"]):
            item["meta"], item["sensitivity"] = w["meta"], w["sensitivity"]
        with trace.step("area_move", f"Moved into the new area {name} (D16)") as st:
            st.data.update({"item": str(w["id"]), "item_title": w["title"], "from": "General", "to": name,
                            "set_by": "model", **changed,
                            "note": f"This item had proposed {name} and waited under General. Now that the area "
                                    f"is real, it moves into it."
                                    + (" The area is one of health, money, legal or finance, so its sensitivity "
                                       "was raised to special." if changed["sensitivity"] else "")})
    with trace.step("area_map", "The map marked for a rebuild: an area changed (D17)") as st:
        st.data.update(mapping.queue(ds, s))


def write_passages(ds_id: str, item_id: str, title: str, body: str, s) -> int:
    """The item's text pieces, numbered 1, 2, 3 in order (seq), with no ceiling.

    The X-ray passage is not one of them: it is marked by `from_xray`, has no
    seq, and is left alone here (migration 0067). Neither are passages of another
    part, such as a meeting's transcript (`meetings.py`, migration 0110), which
    their own code keeps."""
    parts = tx.passages(body, int(s.passage_tokens), int(s.passage_overlap)) or [title or " "]
    with db.atomic():
        db.run("DELETE FROM synapse.passage WHERE dataset_id = %s AND item_id = %s AND NOT from_xray "
               "AND part = ''", (ds_id, item_id))
        # One statement for all of them, so the word counts (`term_delta`, migration 0071) get one
        # row per word for the whole item.
        words = [f"{title} {part}" if seq == 1 else part for seq, part in enumerate(parts, start=1)]
        db.run("INSERT INTO synapse.passage (dataset_id, item_id, seq, text, words) "
               "SELECT %s, %s, n, t, to_tsvector('english', w) || to_tsvector('synapse.bg', w) || "
               "to_tsvector('simple', w || ' ' || %s) FROM unnest(%s::text[], %s::text[]) "
               "WITH ORDINALITY AS x(t, w, n)",
               (ds_id, item_id, tx.other_alphabet(title), parts, words))
    return len(parts)


AUTOMATIC = re.compile(r"no-?reply|newsletter|notifications?@|mailer", re.I)
SIGNAL_COUNT_CAP = 1000


def code_signals(ds: dict, kind: str, meta: dict, body: str, s, *, source: str = "",
                 source_key: str = "", item_id: str | None = None) -> dict:
    """Everything code can tell about an item for its tier call (D80). It decides nothing: these
    are facts the model weighs with the text, never verdicts. Replaced `code_tier` (D58's rules)
    on 4 October 2026."""
    me = datasets.me(ds)
    headers = meta.get("headers") if isinstance(meta.get("headers"), dict) else {}
    sender = str(meta.get("from") or "")
    s_name, s_addr = tx.address_of(sender)
    to, cc = _list(meta.get("to")), _list(meta.get("cc"))
    who = people.find_address(ds, sender) if sender else None
    w_meta = (who or {}).get("meta") or {}
    sig = {"kind": kind, "source": source, "sender_name": s_name, "sender_address": s_addr,
           "to": to, "cc": cc, "recipients": len(to) + len(cc),
           "sender_is_owner": bool(who and str(who["id"]) == str(me)),
           "sender_known_contact": bool(meta.get("known") or w_meta.get("origin") == "icloud"
                                        or w_meta.get("known") is True),
           "sender_contact": ""}
    if who:
        # Decision 8: a known contact is a person imported from the contacts, or one the owner marked known.
        sig["sender_contact"] = (who.get("title") or "") + (
            ", imported from the contacts" if w_meta.get("origin") == "icloud" else
            ", marked known" if w_meta.get("known") is True else ", met in an item")
    seen = replied = 0
    if who:
        # Counted up to SIGNAL_COUNT_CAP: the signal needs "how many, roughly", and a sender of
        # thousands of items must not cost thousands of rows on every item they send.
        seen = db.value("SELECT count(*) FROM (SELECT 1 FROM synapse.item i JOIN synapse.link l ON l.dataset_id = "
                        "i.dataset_id AND l.src = i.id AND l.type = 'from' WHERE i.dataset_id = %s AND l.dst = %s "
                        "AND i.deleted_at IS NULL AND i.id::text <> %s LIMIT %s) x",
                        (ds["id"], who["id"], str(item_id or ""), SIGNAL_COUNT_CAP)) or 0
        replied = db.value("SELECT count(*) FROM (SELECT DISTINCT i.id FROM synapse.item i JOIN synapse.link t ON "
                           "t.dataset_id = i.dataset_id AND t.src = i.id AND t.type IN ('to', 'cc') JOIN synapse.link f "
                           "ON f.dataset_id = i.dataset_id AND f.src = i.id AND f.type = 'from' WHERE i.dataset_id = %s "
                           "AND t.dst = %s AND f.dst::text = %s AND i.deleted_at IS NULL LIMIT %s) x",
                           (ds["id"], who["id"], str(me), SIGNAL_COUNT_CAP)) or 0
    sig.update({"sender_items": int(seen), "owner_replies_to_sender": int(replied),
                "sender_often_unanswered": bool(who) and int(seen) >= int(s.junk_sender_count) and not replied,
                "often_unanswered_from": int(s.junk_sender_count)})
    sig.update({"list_unsubscribe": bool(headers.get("list_unsubscribe")),
                "precedence": str(headers.get("precedence") or ""),
                "auto_submitted": str(headers.get("auto_submitted") or ""),
                "gmail_category": str(headers.get("category") or ""),
                # Where Gmail keeps it now (`gmailsync`): spam and the Bin are Gmail's own judgement.
                "gmail_folder": str((meta.get("gmail") or {}).get("folder") or "")
                if isinstance(meta.get("gmail"), dict) else ""})
    auto = AUTOMATIC.search(s_addr or "")
    sig["automatic_address"] = auto.group(0).lower() if auto else ""
    sig["bulk_words_near_top"] = sorted({m.lower() for m in BULK.findall((body or "")[:400])})
    sig.update({"starred": bool(meta.get("starred")), "task": str(meta.get("task") or ""),
                "project": str(meta.get("project") or "")})
    thread = str(meta.get("thread") or "")
    sig.update({"thread": thread, "thread_items": 0, "owner_replied_in_thread": False})
    if thread:
        sig["thread_items"] = int(db.value("SELECT count(*) FROM synapse.item WHERE dataset_id = %s AND "
                                           "meta->>'thread' = %s AND deleted_at IS NULL AND id::text <> %s",
                                           (ds["id"], thread, str(item_id or ""))) or 0)
        sig["owner_replied_in_thread"] = bool(db.value(
            "SELECT count(*) FROM synapse.item WHERE dataset_id = %s AND meta->>'thread' = %s AND owner = %s "
            "AND deleted_at IS NULL AND lower(split_part(coalesce(meta->>'from', ''), ' ', 1)) = %s",
            (ds["id"], thread, me, datasets.me_word(ds))))
    sig["words"] = tx.words(body)
    sig["attachments"] = int(db.value("SELECT count(*) FROM synapse.item WHERE dataset_id = %s AND "
                                      "meta->'attached_to' ? %s AND deleted_at IS NULL",
                                      (ds["id"], source_key)) or 0) if source_key else 0
    sig["attached_to"] = ", ".join(_list(meta.get("attached_to")))
    sig["area"] = str(meta.get("area") or "")
    if meta.get("junk_because"):
        sig["rouh_junk_check"] = str(meta["junk_because"])
    return sig


def _yes(v) -> str:
    return "yes" if v else "no"


def signal_lines(sig: dict, title: str = "", said_at=None) -> str:
    """The signals as compact lines (D11), the way the tier call reads them."""
    s = sig
    if s.get("sender_address") or s.get("sender_name"):
        sender = (f"{s.get('sender_name')} <{s.get('sender_address')}>" if s.get("sender_address")
                  else s.get("sender_name"))
        about = ("the owner" if s.get("sender_is_owner") else
                 "known contact" + (f" ({s['sender_contact']})" if s.get("sender_contact") else "")
                 if s.get("sender_known_contact") else
                 "not a known contact" + (f" ({s['sender_contact']})" if s.get("sender_contact") else ""))
        sender_line = f"from: {sender} · {about}"
    else:
        sender_line = "from: no sender (added by the owner, not received)"
    lines = [f"kind: {s.get('kind')} · source: {s.get('source') or 'unknown'}"
             + (f" · said {tx.short_date(said_at)}" if said_at else ""),
             sender_line,
             f"to: {', '.join(s.get('to') or []) or 'none'} · cc: {', '.join(s.get('cc') or []) or 'none'}"
             f" · {s.get('recipients', 0)} recipients"]
    if s.get("sender_address") or s.get("sender_name"):
        lines.append(f"sender history: {s.get('sender_items', 0)} earlier items from them, the owner wrote to them "
                     f"{s.get('owner_replies_to_sender', 0)} times"
                     + (f" · often unanswered ({s.get('often_unanswered_from')} or more with no reply)"
                        if s.get("sender_often_unanswered") else ""))
    bulk = [b for b in ("List-Unsubscribe" if s.get("list_unsubscribe") else "",
                        f"precedence {s['precedence']}" if s.get("precedence") else "",
                        f"auto-submitted {s['auto_submitted']}" if s.get("auto_submitted") else "") if b]
    lines.append(f"headers: {', '.join(bulk) or 'none bulk'} · gmail category: {s.get('gmail_category') or 'none'}"
                 + (f" · gmail folder: {s['gmail_folder']}" if s.get("gmail_folder") else ""))
    lines.append(f"automatic-looking address: {s.get('automatic_address') or 'no'} · bulk words near the top: "
                 f"{', '.join(s.get('bulk_words_near_top') or []) or 'none'}")
    lines.append(f"starred: {_yes(s.get('starred'))} · task: {s.get('task') or 'none'} · "
                 f"project: {s.get('project') or 'none'} · area: {s.get('area') or 'none'}")
    n = s.get("thread_items", 0) + 1
    lines.append(f"thread: {n} item{'s' if n != 1 else ''}, the owner replied in it: "
                 f"{_yes(s.get('owner_replied_in_thread'))}" if s.get("thread") else "thread: none")
    lines.append(f"size: {s.get('words', 0)} words, {s.get('attachments', 0)} attachments"
                 + (f" · it is an attachment of {s['attached_to']}" if s.get("attached_to") else ""))
    if s.get("rouh_junk_check"):
        lines.append(f"rouh junk check: {s['rouh_junk_check']}")
    if title:
        lines.append(f"title: {title}")
    return "\n".join(lines)


TIER_INSTRUCTIONS = """You decide the tier of one item in Synapse, the personal memory of {owner}. Your tier decides what happens to it:

2, important: what {owner} is likely to act on or ask about later: a person he deals with writing to him about something real, a thread he is in, work on a task or project, his own notes, rules, decisions and plans.
1, normal: worth finding by meaning later, but not something he is likely to act on: general information, a personal or work message of little weight, a receipt or account notice he may need to look up.
0, junk: newsletters, marketing, automatic notifications and bulk mail nobody will ask about. A tier 0 item is still found by its exact words, but it is never embedded, never read and never linked, so a wrong 0 is costly: choose 0 only when the item is clearly bulk or automatic.

SIGNALS were gathered by code. They are facts about the item, never verdicts: weigh them with the text. When torn between two tiers, choose the higher one.
Answer with tier (0, 1 or 2) and why: one line of at most {words} words, in plain English, saying what decided it, such as "Maria, a known contact, asks {owner} to approve the logo pages for a task." Never use an em dash."""

TIER_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["tier", "why"],
               "properties": {"tier": {"type": "string", "enum": ["0", "1", "2"]}, "why": {"type": "string"}}}

#: The fallback's question when the helper model cannot answer: a decision model picks a tier and says
#: what the item is, which is the nearest it comes to a reason (D80).
TIER_OPTIONS = ["2, important: something the owner is likely to act on or ask about",
                "1, normal: worth finding later, not important",
                "0, junk: bulk, marketing or an automatic notification"]
WHAT_OPTIONS = ["a message from a person to the owner", "the owner's own note, rule, task or plan",
                "a personal or work message from someone not yet known", "a receipt, order or account notice",
                "a newsletter or marketing", "an automatic notification", "none of these"]


def _cap(text: str, tokens: int) -> str:
    """The first `tokens` of a text, by the spec's rule of thumb of 1.3 tokens a word."""
    words = (text or "").split()
    keep = max(1, int(tokens / 1.3))
    return " ".join(words[:keep]) + (" [cut]" if len(words) > keep else "")


def tier_call(ds: dict, item: dict, sig: dict, s, trace, owner) -> dict:
    """The tier call (D80): a model reads the signals and the text and decides the tier, with a reason.

    The helper model answers it, because it writes a reason. If it cannot, a decision model is asked
    through `ai.decide` (its backend, cost cap and fallback as for every decision point). If neither
    answers, the item is tier 1, with why. Never 0 without a model having said so."""
    who = people.owner_name_of(ds) or "the owner"
    words = int(s.tier_reason_words)
    shown = signal_lines(sig, item.get("title") or "", item.get("said_at")) + "\n---\n" + \
        _cap(" ".join((item.get("body") or "").split()), int(s.tier_text_tokens))
    out = {"read": shown, "tried": []}
    try:
        got = ai.generate(model=s.helper_model, name="tier_call", purpose="tier", trace=trace, items=[item["id"]],
                          owner=owner, instructions=TIER_INSTRUCTIONS.format(owner=who, words=words),
                          text="SIGNALS:\n" + shown, schema=TIER_SCHEMA, max_tokens=2000,
                          timeout=120.0)
        tier = int(str(got.get("tier")))
        if tier not in (0, 1, 2):
            raise ValueError(f"the model answered tier {got.get('tier')!r}")
        why = " ".join(str(got.get("why") or "").replace(chr(0x2014), " - ").split())
        why_words = why.split()
        why = " ".join(why_words[:words + 10]) if why else "the model gave no reason"
        out.update({"tier": tier, "why": why, "by": "model", "backend": "openai", "model": got.get("_model"),
                    "cost": got.get("_cost", 0.0), "ms": got.get("_ms", 0)})
        out["tried"].append({"by": "helper model", "model": got.get("_model"), "ok": True})
        return out
    except Exception as exc:  # noqa: BLE001 - the fallback below says why
        out["tried"].append({"by": "helper model", "model": s.helper_model, "ok": False,
                             "error": f"{type(exc).__name__}: {exc}"[:300]})
    got = ai.decide("tier", "SIGNALS:\n" + shown, [
        ai.Choice("tier", f"Which tier should this item be in, for {who}?", TIER_OPTIONS),
        ai.Choice("what", "What is this?", WHAT_OPTIONS)],
        ceiling=item["sensitivity"] if item["sensitivity"] != "unlabelled" else "private",
        settings=s, trace=trace, items=[item["id"]], owner=owner)
    out["decision"] = got
    a, b = got["answers"].get("tier"), got["answers"].get("what")
    if a:
        pick, conf = a["pick"], a["confidence"]
        tier = 2 - TIER_OPTIONS.index(pick)
        what = f"{b['pick']} ({b['confidence']:.2f}); " if b else ""
        out.update({"backend": got.get("backend"), "model": got.get("model"), "cost": got.get("cost", 0.0),
                    "ms": got.get("ms", 0)})
        out["tried"].append({"by": "decision model", "backend": got.get("backend"), "ok": True})
        if conf >= float(s.tier_fallback_confidence) or tier == 1:
            out.update({"tier": tier, "by": "decision",
                        "why": f"{what}a decision model, which writes no reason, picked tier {tier} at {conf:.2f}"})
        else:
            out.update({"tier": 1, "by": "decision",
                        "why": f"{what}a decision model leaned to tier {tier} at only {conf:.2f}, under "
                               f"{s.tier_fallback_confidence}, so tier 1"})
        return out
    out["tried"].append({"by": "decision model", "backend": got.get("backend"), "ok": False,
                         "error": got.get("fallback") or "no answer"})
    out.update({"tier": 1, "by": "none", "backend": "", "model": "", "cost": got.get("cost", 0.0) or 0.0,
                "why": "no model could make the tier call, so tier 1 until it is asked again: "
                       + "; ".join(t.get("error", "") for t in out["tried"] if not t.get("ok"))[:400]})
    return out


def code_sensitivity(payload: dict, meta: dict) -> tuple[str, str]:
    """Sensitivity as code knows it when the item is stored: only what came with it.

    Code never guesses it from words: a word list flagged so much that its flags were
    ignored (Petar, 3 October 2026). The model sets it when it reads the item (the
    X-ray call). Until then the item is unlabelled, which is kept off hosted decision
    models and shown to nobody but its owner, like a special item."""
    said = str(payload.get("sensitivity") or "").lower()
    if said in ("normal", "private", "special"):
        return said, "given with the item"
    area = str(meta.get("area") or "").lower()
    if area in SPECIAL_AREAS:
        return "special", f"in the {area} area, given with the item"
    return "unlabelled", ("not given with the item, so it waits for the model to read it; until then it "
                          "is kept off hosted models and shown only to its owner")


def _given_why(payload: dict, code_why: str) -> dict:
    why = {"code": code_why}
    said = str(payload.get("sensitivity") or "").lower()
    if said in ("normal", "private", "special"):
        why["given"] = said
    return why


def _parents_say(ds_id: str, parents: list[dict]) -> dict:
    """The readers and sensitivity a file takes from the emails it came on: every reader of
    any of them, and the highest level any of them has been given or read at."""
    readers = sorted({r for p in parents for r in readers_of(ds_id, p["id"])})
    levels = [p.get("sensitivity") for p in parents if p.get("sensitivity") in SENSITIVITY_RANK
              and p.get("sensitivity") != "unlabelled"]
    out = {"readers": readers} if readers else {}
    if levels:
        out["sensitivity"] = _ceiling(levels)
    return out


def attach(ds: dict, item_id: str, keys: list[str], *, by: str = "page") -> dict:
    """A file already stored, arriving on more emails: those emails are added to what it is
    attached to and linked, and their readers and sensitivity added to its own. Nothing is
    read again: the same bytes are the same words."""
    item = get_item(ds["id"], item_id)
    meta = dict(item.get("meta") or {})
    had = _list(meta.get("attached_to"))
    meta["attached_to"] = list(dict.fromkeys(had + keys))
    parents = [p for p in (find_by_key(ds["id"], k) for k in meta["attached_to"]) if p]
    said = _parents_say(ds["id"], parents)
    db.run("UPDATE synapse.item SET meta = %s::jsonb, updated_at = now() WHERE id = %s", (Json(meta), item_id))
    readers = sorted(set(readers_of(ds["id"], item_id)) | set(said.get("readers") or []))
    set_readers(ds["id"], item_id, readers)
    now, raised = item.get("sensitivity") or "unlabelled", ""
    if said.get("sensitivity") and (now == "unlabelled" or SENSITIVITY_RANK[said["sensitivity"]] > SENSITIVITY_RANK.get(now, 0)):
        raised = said["sensitivity"]
        why = dict(item.get("sensitivity_why") or {})
        why.update({"given": raised, "code": "the level of an email it is attached to"})
        db.run("UPDATE synapse.item SET sensitivity = %s, sensitivity_why = %s::jsonb WHERE id = %s",
               (raised, Json(why), item_id))
    s = datasets.settings(ds)
    made = []
    for parent in parents:
        got = add_link(ds["id"], item_id, parent["id"], "attached", s.code_strength("attached"), origin="code",
                       made_by="code", why="attached to that message")
        made.append({"to": parent.get("title"), "to_id": parent["id"], "new": bool(got.get("made"))})
    trace = Trace(ds["id"], "edit", f"Attached again: {item['title']}", by=by, item_id=item_id)
    with trace.step("attached", "The same file on another email: one item, linked to each email (attached)") as st:
        st.data.update({"attached_to": meta["attached_to"], "new_keys": [k for k in keys if k not in had],
                        "links": made, "readers": readers, "sensitivity_raised_to": raised or None})
    trace.finish("done", attached=True)
    return {"ok": True, "item": item_id, "trace": trace.id, "attached": True}


def _raise_attachments(item: dict, level: str) -> None:
    """An email's files are never below the email's own sensitivity: once its level is known,
    a file attached to it that is lower, or not labelled yet, is raised to it."""
    if level not in ("normal", "private", "special") or not item.get("source_key"):
        return
    for f in db.rows("SELECT id, sensitivity, sensitivity_why FROM synapse.item WHERE dataset_id = %s AND "
                     "meta->'attached_to' ? %s AND deleted_at IS NULL", (item.get("dataset_id"), item["source_key"])):
        if f["sensitivity"] != "unlabelled" and SENSITIVITY_RANK.get(f["sensitivity"], 0) >= SENSITIVITY_RANK[level]:
            continue
        why = dict(f.get("sensitivity_why") or {})
        why.update({"given": level, "code": f"raised to the level of the email it is attached to, {item.get('title')}"})
        db.run("UPDATE synapse.item SET sensitivity = %s, sensitivity_why = %s::jsonb WHERE id = %s",
               (level, Json(why), f["id"]))


def relink_senders(ds: dict, item: dict) -> list[dict]:
    """An item's sender links made again by code, as `code_links` makes them now: its links to people as
    sender, recipient or copy taken off first. For `people.repair_list_people`."""
    db.run("DELETE FROM synapse.link WHERE dataset_id = %s AND src = %s AND type IN ('from', 'to', 'cc') "
           "AND origin = 'code'", (ds["id"], item["id"]))
    return code_links(ds, item, datasets.settings(ds))


def code_links(ds: dict, item: dict, s) -> list[dict]:
    """Sender, recipients, copies, thread, reply, attachment, task, identity and rule links (D30)."""
    ds_id, meta, made = ds["id"], item.get("meta") or {}, []
    persons = []

    def link(dst, link_type, why):
        if not dst:
            return
        got = add_link(ds_id, item["id"], dst["id"], link_type, s.code_strength(link_type), origin="code",
                       made_by="code", why=why)
        made.append({"type": link_type, "to": dst.get("title") or dst.get("source_key"), "to_id": dst["id"],
                     "strength": s.code_strength(link_type), "why": why, "new": bool(got.get("made"))})
        if dst.get("kind") == "person":
            made[-1]["person"] = {"origin": (dst.get("meta") or {}).get("origin"), "how": dst.get("_how", "")}
            persons.append(dst["id"])

    def person(who):
        got, how = person_for(ds, who, item)
        if got:
            got["_how"] = {"email": "matched by address", "phone": "matched by phone",
                           "name seen before": "the same bare name as before", "made": "new, origin synapse"}.get(how, how)
        return got

    # One sender, or several: a Slack day is everybody who wrote in it that day (`slack.master_items`), each
    # with their Slack address where Slack gives one. A list was taken for one sender, called by the list
    # itself, until 22 October 2026 (`people.repair_list_people`).
    for who in (_list(meta["from"]) if isinstance(meta.get("from"), list) else [meta.get("from")]):
        if who:
            link(person(who), "from", "the sender's address" if "@" in str(who) else "the sender, by name")
    for who in _list(meta.get("to")):
        link(person(who), "to", "a recipient's address")
    for who in _list(meta.get("cc")):
        link(person(who), "cc", "copied")
    if meta.get("thread"):
        root = db.row("SELECT id, title, source_key FROM synapse.item WHERE dataset_id = %s AND meta->>'thread' = %s "
                      "AND id <> %s AND deleted_at IS NULL AND kind <> 'layer' ORDER BY said_at, stored_at LIMIT 1",
                      (ds_id, meta["thread"], item["id"]))
        if root and (item.get("said_at") is None or True):
            link(root, "in_thread", f"thread {meta['thread']}")
    if meta.get("reply_to"):
        link(find_by_key(ds_id, meta["reply_to"]), "reply_to", "answers that message")
    for field in ("task", "project"):
        if meta.get(field):
            link(find_by_key(ds_id, meta[field]), "in", f"belongs to {meta[field]}")
    for parent in _list(meta.get("attached_to")):
        link(find_by_key(ds_id, parent), "attached", "attached to that message")
    if item["kind"] == "rule":
        targets = _list(meta.get("rule_for"))
        for target in targets:
            found = find_by_key(ds_id, target)
            if found is None and not target.startswith("task:"):
                # Synapse Master keeps a task under the key task:<its id>, and a rule names the task by its id.
                found = find_by_key(ds_id, f"task:{target}")
            if found is None and "@" in target:
                found = person(target)
            if found is None:
                found = db.row("SELECT * FROM synapse.item WHERE dataset_id = %s AND kind IN ('topic','task',"
                               "'project') AND lower(title) = lower(%s) AND deleted_at IS NULL LIMIT 1", (ds_id, target))
            if found is None:
                pid = people.reader_id(ds, target, create_new=False)
                found = people.get(people.home_id(ds), pid) if pid and pid != people.EVERYONE else None
            link(found, "rule_for", f"governs {target}")
    if item["kind"] == "meeting":
        # Its calendar event, who took part or was invited, and its confirmed speakers (`meetings.py`).
        from . import meetings

        for dst, link_type, why in meetings.links_for(ds, item):
            link(dst, link_type, why)
    if persons:
        people.linked(ds, persons)
    return made


# ---------------------------------------------------------------------------------------
# storing: the model's part, on the queue
# ---------------------------------------------------------------------------------------

XRAY_INSTRUCTIONS = """You read one item for Synapse, a personal memory, and return its X-ray, its judgement links, its tier, sensitivity, area and silos, any standing rules and the people its text names, in one answer.

The X-ray (never a summary):
- gist: the item's answer in one sentence, at most {words} words.
- claims: flat, one sentence each, at most {words} words, about {n} of them (at least {lo}, at most {hi}). Doubts are claims of their own. Kinds: fact, ask (someone asks someone for something), promise (someone commits to something), decision, caveat, disagreement, open (something not settled), rule (a standing instruction meant to hold for every future case, such as "from now on, copy Elena on invoices" or "always reply to her alone"; a one-off request about this piece of work is an ask, never a rule). Strength: strong, moderate, mixed or weak. Each claim has q, a quote copied word for word from the item that it rests on, short, exactly as written; a claim whose quote is not in the item is thrown away. who and to are first names, lower case. due is a date as YYYY-MM-DD or "". open is true for an ask or promise not yet done.

Judgement links: only to the numbered CANDIDATES, by their number. Types: about (the item is about that topic, person or task), follows_up (continues it without being a reply), continues (the same conversation as that earlier item, such as a reply to it or the next message between the same people on the same matter, when nothing else ties them), contradicts (says the opposite on some claim), updates (replaces something it said: a new date, a new price). Strength weak, medium or strong. At most {links}. claim is the index of the claim it rests on, or -1. Do not link to a candidate merely because it shares a word.
topics: at most 2 topics the item is about; fewer is fine, and none is right when nothing lasting applies. A topic is a broad, lasting subject or area of work that many items will be about over months, the way a person would file things: such as onboarding, fundraising, hiring, legal, or a named project. Never an event, a date, a single meeting or call, a person, an organisation (people and organisations are contacts, linked on their own), a one-off piece of work, or two subjects joined in one name. EXISTING TOPICS and PROPOSED TOPICS list the names already in use: whenever one of them fits, use it with its exact name, and propose a new short name (1 to 3 words) only when none does.
topics_refused: the narrower names you considered and did not propose, each with why (such as: a single meeting, a person, an organisation, a date, two subjects). Usually short or empty.
sensitivity: normal, private, or special (health, money, legal, private contact details, another person's personal life), with a short reason.
tier: important, normal or junk, and tier_why: one line of at most {tier_words} words, in plain English, saying what decided it, such as "Maria, a known contact, asks for approval of the logo pages for a task." important: something the owner is likely to act on or ask about later, such as a person they deal with writing about something real, a thread they are in, work on a task or project, or their own notes, rules, decisions and plans. normal: worth finding by meaning later, but not something they are likely to act on, such as general information, a message of little weight, a receipt or account notice. junk: newsletters, marketing, automatic notifications and bulk mail nobody will ask about; a junk item is never linked or searched by meaning, so choose junk only when it is clearly bulk or automatic. SIGNALS, when given, were gathered by code: facts about the item, never verdicts; weigh them with the text. When torn between two tiers, choose the higher.
rules: indexes of claims that are standing instructions.
terms: words or names the owner uses with a private meaning (a project nickname, an internal name), with what each means. Usually none.
recheck: only when EXISTING LINKS are listed: for each, keep, change (with the new type and strength) or drop.
title: a plain title of about 3 to 10 words, in the item's own language, saying what the item is, the way a person would file it (such as "Quote for the new office chairs" or "Maria asks to move Friday's call"). Not its first words, no addresses, no quote marks.
silos: which of the owner's silos the item belongs to, each by its exact name from SILOS (the parts of their life they keep apart, with what each covers): the one it is about, several only when it is plainly about each, and an empty list when the item does not say. Decide by what it is about, never by who wrote it, and never name a silo that is not listed.
area: the broad part of the owner's life or work the item belongs to, as a short name (such as a company or client by its name, Team, Family, Home, Health, Money, or a product the owner builds). An area is what the item is about, never how it arrived or what kind of thing it is: never Email, Mail, Inbox, Messages, Chat, Tasks, Projects, Files, Documents, Attachments, Calendar, Notes or the like, even when every item so far came the same way. EXISTING AREAS lists the dataset's areas and the new names already proposed for one: choose the one that fits this item best, with its exact name, and prefer the most specific one that fits over a broad one. Propose a new short name of 1 to 3 words only when none of them fits, and leave it empty when nothing in the item says which part of the owner's life or work it belongs to.
"""
# People mentioned (4 October 2026, Q21 kept open): raw material only, see `mentions`.
XRAY_INSTRUCTIONS += mentions.INSTRUCTIONS

XRAY_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["title", "gist", "claims", "links", "topics", "topics_refused", "sensitivity", "sensitivity_why",
                 "tier", "tier_why", "rules", "terms", "recheck", "area", "silos"] + list(mentions.FIELDS),
    "properties": {
        "title": {"type": "string"},
        "area": {"type": "string"},
        "silos": {"type": "array", "items": {"type": "string"}},
        "gist": {"type": "string"},
        "claims": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["c", "k", "s", "q", "who", "to", "due", "open"],
            "properties": {"c": {"type": "string"}, "k": {"type": "string", "enum": CLAIM_KINDS},
                           "s": {"type": "string", "enum": STRENGTHS}, "q": {"type": "string"},
                           "who": {"type": "array", "items": {"type": "string"}},
                           "to": {"type": "array", "items": {"type": "string"}},
                           "due": {"type": "string"}, "open": {"type": "boolean"}}}},
        "links": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["target", "type", "strength", "claim", "why"],
            "properties": {"target": {"type": "integer"},
                           "type": {"type": "string", "enum": list(numbers.JUDGEMENT_TYPES)},
                           "strength": {"type": "string", "enum": ["weak", "medium", "strong"]},
                           "claim": {"type": "integer"}, "why": {"type": "string"}}}},
        "topics": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["name", "strength"],
            "properties": {"name": {"type": "string"},
                           "strength": {"type": "string", "enum": ["weak", "medium", "strong"]}}}},
        "topics_refused": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["name", "why"],
            "properties": {"name": {"type": "string"}, "why": {"type": "string"}}}},
        "sensitivity": {"type": "string", "enum": ["normal", "private", "special"]},
        "sensitivity_why": {"type": "string"},
        "tier": {"type": "string", "enum": ["junk", "normal", "important"]},
        "tier_why": {"type": "string"},
        "rules": {"type": "array", "items": {"type": "integer"}},
        "terms": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["term", "meaning"],
            "properties": {"term": {"type": "string"}, "meaning": {"type": "string"}}}},
        "recheck": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["link", "verdict", "type", "strength", "why"],
            "properties": {"link": {"type": "integer"},
                           "verdict": {"type": "string", "enum": ["keep", "change", "drop"]},
                           "type": {"type": "string", "enum": list(numbers.JUDGEMENT_TYPES)},
                           "strength": {"type": "string", "enum": ["weak", "medium", "strong"]},
                           "why": {"type": "string"}}}},
        **mentions.SCHEMA,
    },
}


#: What the X-ray call decides beside the X-ray itself (D82): its tier, sensitivity, area and, since 12 October
#: 2026, its silos (`rouh/silos.py`). `xray_instructions(False)` and `xray_schema(False)` ask without them, which
#: only the benchmark of 4 October 2026 does, to measure what asking for them adds.
ATTRIBUTE_FIELDS = ("tier", "tier_why", "sensitivity", "sensitivity_why", "area", "silos")
XRAY_TIER = {"junk": 0, "normal": 1, "important": 2}


def xray_instructions(attributes: bool = True, people: bool = True) -> str:
    """`people=False` leaves out the people mentioned, which only the measurement of 4 October 2026 does."""
    text = XRAY_INSTRUCTIONS
    if not people:
        text = "\n".join(line for line in text.split("\n") if not line.startswith(mentions.FIELDS))
        text = text.replace(" and the people its text names,", ",")
    if attributes:
        return text
    lines = [line for line in text.split("\n") if not line.startswith(("tier:", "sensitivity:", "area:", "silos:"))]
    return "\n".join(lines).replace(", its tier, sensitivity, area and silos,", "")


def xray_schema(attributes: bool = True, people: bool = True) -> dict:
    drop = (ATTRIBUTE_FIELDS if not attributes else ()) + (mentions.FIELDS if not people else ())
    if not drop:
        return XRAY_SCHEMA
    return {**XRAY_SCHEMA, "required": [k for k in XRAY_SCHEMA["required"] if k not in drop],
            "properties": {k: v for k, v in XRAY_SCHEMA["properties"].items() if k not in drop}}


def one_call(item: dict, s) -> dict:
    """Which of the item's attributes its X-ray call decides (D82), worked out by code before any call.

    An item gets an X-ray when it is not a person or a topic and has at least `xray_min_words` words.
    Its tier and sensitivity then come from that one call, unless Tune switches the separate calls
    back on to compare. An item with no X-ray keeps the tier call (D80) and the suggestions (D75)."""
    n_words = tx.words(item.get("body") or "")
    gets = item["kind"] not in ("person", "topic") and n_words >= int(s.xray_min_words)
    return {"gets_xray": gets, "tier": gets and not s.xray_split_tier,
            "sensitivity": gets and not s.xray_split_sensitivity}


def _ceiling(sens_values) -> str:
    worst = "normal"
    for v in sens_values:
        if SENSITIVITY_RANK.get(v, 1) > SENSITIVITY_RANK.get(worst, 0):
            worst = v
    return worst


def _item_head(item: dict) -> str:
    meta = item.get("meta") or {}
    bits = [f"kind {item['kind']}", f"said {tx.item_date(item)}"]
    if meta.get("from"):
        bits.append(f"from {meta['from']}")
    if meta.get("to"):
        bits.append(f"to {', '.join(_list(meta['to']))}")
    if meta.get("cc"):
        bits.append(f"cc {', '.join(_list(meta['cc']))}")
    if item.get("title"):
        bits.append(f'subject "{item["title"]}"')
    return ", ".join(bits)


def model_part(ds: dict, item_id: str, trace_id: str | None, *, editing: dict | None = None) -> dict:
    """The job: everything after code's part. `editing` carries an edit's old links to re-check."""
    s = datasets.settings(ds)
    owner = datasets.owner_of(ds)
    item = get_item(ds["id"], item_id)
    if item is None or item.get("deleted_at") is not None:
        return {"ok": False, "why": "the item is gone"}
    trace = Trace(ds["id"], "store", "", trace_id=trace_id) if trace_id else Trace(
        ds["id"], "store", f"Store: {item['title']}", item_id=item_id, by="worker")
    me = datasets.me(ds)
    body = item.get("body") or ""
    n_words = tx.words(body)
    tier = int(item["tier"])
    summary = {"tier_before": tier}
    # One call (D82): an item that gets an X-ray has its tier, sensitivity and area decided in that
    # call, so the separate tier call (D80) and sensitivity suggestions (D75) run only for items with
    # no X-ray, or when Tune switches them back on to compare.
    plan = one_call(item, s)
    summary["one_call"] = plan["tier"] and plan["sensitivity"]
    before_by, before_why = item.get("tier_by") or "", item.get("tier_why") or ""
    try:
        # Gathered when the call is made, so a star, a task or a reply since is in them.
        sig = code_signals(ds, item["kind"], item.get("meta") or {}, body, s, source=item.get("source") or "",
                           source_key=item.get("source_key") or "", item_id=item_id)
        if plan["tier"]:
            # Read by the X-ray call below, which decides the tier; until it answers the tier is pending.
            db.run("UPDATE synapse.item SET tier_signals = %s::jsonb WHERE id = %s", (Json(sig), item_id))
        else:
            # --- the tier call (D80): code gathers the signals, a model decides --------------
            with trace.step("tier", "Tier: signals gathered by code, decided by a model (D80)") as st:
                st.data.update({"signals": sig, "before": tier, "before_by": before_by, "before_why": before_why})
                if plan["gets_xray"]:
                    st.data["note"] = ("Tune has the separate tier call on for items that get an X-ray, so it runs "
                                       "before the X-ray, as before 4 October 2026 (D82 keeps it to compare).")
                call = tier_call(ds, item, sig, s, trace, owner)
                if call["tier"] < 1 and item["kind"] == "meeting":
                    # A meeting is never junk: its transcript passages keep their vectors (`meetings.py`).
                    call.update({"tier": 1, "why": f"a meeting from the library is never junk (the call said: "
                                                   f"{call['why']})"})
                st.data.update({**call, "prior": [s.prior_junk, s.prior_normal, s.prior_important][call["tier"]]})
                tier = call["tier"]
                db.run("UPDATE synapse.item SET tier = %s, tier_why = %s, tier_by = %s, tier_signals = %s::jsonb "
                       "WHERE id = %s", (tier, call["why"], call["by"], Json(sig), item_id))
                item.update({"tier": tier, "tier_why": call["why"], "tier_by": call["by"]})
            summary.update({"tier_call": tier, "tier_by": call["by"]})

        # --- sensitivity suggestions (D75), for items with no X-ray -----------------------
        # A decision call, so only when Tune has decision models on: since 4 October 2026 none is made
        # by default, and an item's sensitivity is the model's read in its X-ray (D82).
        if not plan["sensitivity"] and ai.backend_for("sensitivity", s) != "off":
            with trace.step("sensitivity", "Sensitivity suggestions, which can only raise (D75)") as st:
                state = _item_head(item) + "\n\n" + " ".join(body.split())[:4000]
                questions = [ai.Noul("health", "Is this about someone's health?"),
                             ai.Noul("money", "Is this about someone's personal money: their bank, salary, debt or payments?"),
                             ai.Noul("legal", "Is this about a legal matter?"),
                             ai.Noul("contact", "Does it contain private contact details: a home address, a "
                                                "personal phone, an identity number?"),
                             ai.Noul("personal", "Is it about another person's personal life rather than work?")]
                got = ai.decide("sensitivity", state, questions, ceiling="special", settings=s, trace=trace,
                                items=[item_id], owner=owner)
                st.data["decision"] = got
                flagged = [q for q, a in (got.get("answers") or {}).items() if a.get("p_yes", 0) >= s.sensitivity_noul]
                suggestion = "special" if flagged else "normal"
                current = item["sensitivity"]
                final = _ceiling([current, suggestion])
                st.data.update({"flagged": flagged, "suggestion": suggestion, "before": current, "after": final,
                                "threshold": s.sensitivity_noul,
                                "note": "It can only make an item stricter, never settle or lower it; the "
                                        "model's read in the X-ray sets the level. Readers stay the permission check."
                                        + (" Tune has these suggestions on for items that get an X-ray too, to "
                                           "compare (D82)." if plan["gets_xray"] else "")})
                why = dict(item.get("sensitivity_why") or {})
                why["decision"] = {"flagged": flagged, "backend": got.get("backend")}
                db.run("UPDATE synapse.item SET sensitivity = %s, sensitivity_why = %s::jsonb WHERE id = %s",
                       (final, Json(why), item_id))
                item["sensitivity"] = final

        # A pending tier reads as normal until the X-ray call decides it (D82).
        reading = plan["tier"] or tier >= 1

        # --- embeddings (D37); tier 0 gets none (D58) ----------------------------------
        if reading:
            with trace.step("embedding", "Embeddings of the passages (D37)") as st:
                st.data.update(embed_item(ds, item_id, s, trace, owner))
        else:
            with trace.step("embedding", "No embedding: tier 0 is found by its words only (D58)") as st:
                st.data["skipped"] = True

        # --- candidates and screening (D31, D74) ----------------------------------------
        candidates, older_claims = [], []
        if reading and item["kind"] not in ("person",):
            with trace.step("candidates", "Link candidates: structure, the item's own vector, its rarest words (D31)") as st:
                candidates, info = link_candidates(ds, item, s, trace, owner)
                st.data.update(info)
            if n_words >= int(s.xray_min_words) and older_claims_wanted(s):
                with trace.step("contradiction_screen", "Older claims screened for contradictions (D74)") as st:
                    older_claims, info = contradiction_screen(ds, item, candidates, s, trace, owner)
                    st.data.update(info)

        # --- X-ray and judgement links (D9) or a short item's links (D74) -------------
        xray = None
        if reading and plan["gets_xray"]:
            title = ("X-ray, tier, sensitivity, area, judgement links and rules in one helper call (D9, D82)"
                     if plan["tier"] else "X-ray, judgement links, sensitivity and rules in one helper call (D9)")
            with trace.step("xray", title) as st:
                xray, out = xray_call(ds, item, candidates, older_claims, s, trace, owner, editing=editing,
                                      signals=signal_lines(sig, item.get("title") or "", item.get("said_at"))
                                      if plan["tier"] else "")
                st.data.update(out)
                # Stored as data on the item and nothing else (Q21): not a passage, not searched, not
                # resolved against the people set; no identity, person item or link is made from it.
                db.run("UPDATE synapse.item SET mentions = %s::jsonb WHERE id = %s", (Json(xray["_mentions"]), item_id))
            if plan["tier"]:
                with trace.step("tier", "Tier: signals gathered by code, decided in the X-ray call (D82)") as st:
                    call = xray_tier(xray, s)
                    st.data.update({"signals": sig, "before": tier, "before_by": before_by, "before_why": before_why,
                                    **call, "prior": [s.prior_junk, s.prior_normal, s.prior_important][call["tier"]],
                                    "note": "The X-ray call read code's signals with the whole item and decided the "
                                            "tier with its reason, in the same answer as the X-ray; no separate tier "
                                            "call was made (D82). Its cost and time are the X-ray step's."})
                    tier = call["tier"]
                    if tier < 1 and item["kind"] == "meeting":
                        # A meeting is never junk: its transcript passages keep their vectors (`meetings.py`).
                        call.update({"tier": 1, "why": f"a meeting from the library is never junk (the X-ray "
                                                       f"said: {call['why']})"})
                        tier = 1
                    db.run("UPDATE synapse.item SET tier = %s, tier_why = %s, tier_by = %s WHERE id = %s",
                           (tier, call["why"], call["by"], item_id))
                    item.update({"tier": tier, "tier_why": call["why"], "tier_by": call["by"]})
                summary.update({"tier_call": tier, "tier_by": call["by"]})
            if plan["sensitivity"]:
                with trace.step("sensitivity", "Sensitivity: read in the X-ray call, which only raises what came "
                                               "with the item (D60, D82)") as st:
                    st.data.update({**out["sensitivity"],
                                    "note": "The X-ray call set the level as it read the item. A level given with "
                                            "the item, or an owner-set area of health, money, legal or finance, "
                                            "can only raise it; a model-set area in those raises it too (area step). "
                                            "No separate sensitivity suggestions were asked (D82). Readers stay "
                                            "the permission check."})
            title_step, info = write_title(ds, item, xray, trace, editing=bool(editing))
            with trace.step("title", title_step) as st:
                st.data.update(info)
            summary["title_by"] = info["by"]
            area_step(ds, item, xray, s, trace)
            silos_step(ds, item, xray, trace)
            with trace.step("quote_check", "Every claim's quote checked by code (D10)") as st:
                xray, checked = quote_check(item, xray, s)
                st.data.update(checked)
            if tier < 1:
                # Junk, as the X-ray call read it (D82): found by its words only, never embedded or linked (D58).
                with trace.step("junk", "Tier 0: its vectors removed, no links, topics or rules (D58, D82)") as st:
                    dropped = db.run("UPDATE synapse.passage SET vec = NULL, embed_model = '' WHERE dataset_id = %s "
                                     "AND item_id = %s AND vec IS NOT NULL", (ds["id"], item_id))
                    stored = {k: v for k, v in xray.items() if not k.startswith("_")}
                    db.run("UPDATE synapse.item SET xray = %s::jsonb, xray_by = %s::jsonb, xray_dropped = %s "
                           "WHERE id = %s", (Json(stored), Json({"by": "model", "model": xray.get("_model"),
                                                                 "at": _now().isoformat(), "purpose": "xray"}),
                                             int(xray.get("dropped") or 0), item_id))
                    db.run("DELETE FROM synapse.passage WHERE dataset_id = %s AND item_id = %s AND from_xray",
                           (ds["id"], item_id))
                    st.data.update({"vectors_removed": dropped, "links_proposed_not_written": len(xray.get("_links") or []),
                                    "topics_not_written": [t.get("name") for t in xray.get("_topics") or []],
                                    "note": "The X-ray call called this item junk, so it is kept and found by its "
                                            "exact words only: the vectors made before the call are removed, and "
                                            "its judgement links, topics, rules and map words are not written. Its "
                                            "gist and claims stay on the item for anyone who opens it."})
            else:
                with trace.step("xray_passage", "The X-ray as a passage of its own (D24)") as st:
                    st.data.update(write_xray(ds, item, xray, s, trace, owner))
                with trace.step("judgement_links", "Judgement links written, with type and strength (D31, D32)") as st:
                    st.data.update(write_judgement_links(ds, item, xray, candidates, older_claims, s, editing=editing))
                with trace.step("topics", "Topics: reused, matched by meaning, proposed, made or refused (D34)") as st:
                    st.data.update(write_topics(ds, item, xray, s))
                with trace.step("rules", "Standing rules in the claims (D59)") as st:
                    st.data.update(write_rules(ds, item, xray, me, s))
                with trace.step("terms", "Words for the map (D16)") as st:
                    st.data.update(write_terms(ds, item, xray))
            if not plan["tier"] and XRAY_TIER.get(xray.get("_model_tier")) in (1, 2) and tier in (1, 2):
                # The separate tier call ran (Tune), so the X-ray only moves between 1 and 2, as before (D58).
                new_tier = XRAY_TIER[xray["_model_tier"]]
                if new_tier != tier:
                    # Both lines are kept: the X-ray's reading, and the tier call it moved (D58).
                    db.run("UPDATE synapse.item SET tier = %s, tier_why = %s, tier_by = 'xray' WHERE id = %s",
                           (new_tier, f"the helper model read it: {xray['_model_tier']} (the tier call had said "
                                      f"tier {tier}: {item.get('tier_why') or ''})", item_id))
                    tier = new_tier
        else:
            with trace.step("xray", "No X-ray: the raw text is short enough to be its own (D8)") as st:
                gist = (item["title"] + ": " if item.get("title") else "") + tx.first_sentence(body, int(s.claim_words))
                xray = {"x": 1, "gist": gist.strip(": "), "claims": [], "by": "code"}
                st.data.update({"skipped": tier < 1 or item["kind"] in ("person", "topic"),
                                "title": f"kept: {title_by(item)} (only the X-ray writes a title)", "words": n_words, "threshold": s.xray_min_words, "gist": xray["gist"],
                                "why": "tier 0" if tier < 1 else f"a {item['kind']}, which has no X-ray"
                                if item["kind"] in ("person", "topic") else
                                f"{n_words} words, under {s.xray_min_words}"})
                # No model read it, so it has no people mentioned (an older reading's are dropped).
                db.run("UPDATE synapse.item SET xray = %s::jsonb, xray_by = %s::jsonb, mentions = NULL WHERE id = %s",
                       (Json(xray), Json({"by": "code", "at": _now().isoformat()}), item_id))
            if item["kind"] == "note" and RULE_WORDS.match(body or "") and (item.get("owner") or me) == me:
                with trace.step("rules", "A short note worded as a standing instruction becomes a rule (D59)") as st:
                    st.data["made"] = [make_rule(ds, body.strip(), item, why="the owner's note, worded as a rule")]
            if tier >= 1 and candidates and item["kind"] not in ("person", "topic") \
                    and ai.backend_for("short_links", s) != "off":
                with trace.step("short_links", "A short item's about links, by a decision model (D74)") as st:
                    st.data.update(short_item_links(ds, item, candidates, s, trace, owner))
            if editing:
                with trace.step("recheck", "The item's judgement links re-checked (D33)") as st:
                    st.data.update(recheck_without_model(ds, item, editing))


        # --- layers and map (D53, D54, D17) -------------------------------------------
        with trace.step("layers", "Layers this item touches (D53, D54)") as st:
            from . import layers
            st.data.update(layers.queue_for(ds, item_id, s, trace))
        with trace.step("map", "The map marked for a rebuild (D17)") as st:
            from . import mapping
            st.data.update(mapping.queue(ds, s))
        db.run("UPDATE synapse.item SET status = 'ready', updated_at = now() WHERE id = %s", (item_id,))
        summary.update({"tier": tier, "claims": len((xray or {}).get("claims") or []),
                        "links": db.value("SELECT count(*) FROM synapse.link WHERE dataset_id = %s AND "
                                          "(src = %s OR dst = %s)", (ds["id"], item_id, item_id))})
        trace.finish("done", **summary)
        return {"ok": True, **summary}
    except Exception as exc:
        log.exception("Synapse could not finish storing %s", item_id)
        db.run("UPDATE synapse.item SET status = 'failed' WHERE id = %s", (item_id,))
        trace.finish("failed", error=f"{type(exc).__name__}: {exc}")
        return {"ok": False, "why": str(exc)}


def older_claims_wanted(s) -> bool:
    return ai.backend_for("contradiction_screen", s) != "off" and int(s.contradiction_max) > 0


def embed_item(ds: dict, item_id: str, s, trace, owner) -> dict:
    rows = db.rows("SELECT id, text, from_xray FROM synapse.passage WHERE dataset_id = %s AND item_id = %s "
                   "AND vec IS NULL ORDER BY from_xray, seq", (ds["id"], item_id))
    if not rows:
        return {"passages": 0, "note": "nothing new to embed"}
    item = get_item(ds["id"], item_id) or {}
    texts = [((item.get("title") or "") + "\n" + r["text"]) if not r["from_xray"] else r["text"] for r in rows]
    return vectors.store(ds, [{"id": r["id"], "text": t} for r, t in zip(rows, texts)], trace=trace,
                         purpose="embed_passages", items=[item_id], owner=owner)


def _candidate_line(n: int, it: dict) -> str:
    return tx.compact(n, it, raw_chars=200)


def _identifiers(addresses) -> list[tuple[str, str]]:
    """Addresses, phones and bare names as identity keys, the way `people.resolve` reads them."""
    out = []
    for who in addresses:
        raw = str(who or "").strip()
        if not raw:
            continue
        if people.looks_like_phone(raw):
            out.append(("phone", people.norm_phone(raw)))
        else:
            name, addr = tx.address_of(raw)
            out.append(("email", people.norm_email(addr)) if addr else ("name", people.norm_name(name)))
    return [w for w in out if w[1]]


def _people_by_identifier(ds: dict, wanted: list[tuple[str, str]]) -> dict:
    """Who each identifier is, by exact lookups in `synapse.identity`, all in one query; nobody is made."""
    if not wanted:
        return {}
    got = db.rows(
        "SELECT DISTINCT ON (x.type, x.value) x.type, x.value, x.item_id FROM synapse.identity x "
        "JOIN synapse.item i ON i.dataset_id = x.scope_id AND i.id = x.item_id "
        "WHERE x.scope_id = %s AND (x.type, x.value) IN (SELECT * FROM unnest(%s::text[], %s::text[])) "
        "AND i.deleted_at IS NULL ORDER BY x.type, x.value, i.stored_at",
        (str(people.home_id(ds)), [w[0] for w in wanted], [w[1] for w in wanted]))
    return {(r["type"], r["value"]): str(r["item_id"]) for r in got}


def structure_candidates(ds: dict, item: dict, s) -> tuple[list[str], dict]:
    """What the data itself ties an item to, before any search (D30, D31): the items of its thread and
    the one it replies to, its files or the emails it came on and the other emails with the same file,
    any other item that is the same file by its hash, then the people it is from, to and copied to,
    and the people its text names when a model has read them. Every one an index lookup; at most `link_structure_max`, in that order. (The same file on
    several emails is one item, keyed by its hash, so its emails are the ones it came on.)"""
    ds_id, meta, me = ds["id"], item.get("meta") or {}, item["id"]
    found: list[str] = []
    why: dict[str, str] = {}

    def add(ids, reason):
        for x in ids:
            x = str(x)
            if x != str(me) and x not in why:
                found.append(x)
                why[x] = reason

    if meta.get("thread"):
        add([r["id"] for r in db.rows(
            "SELECT id FROM synapse.item WHERE dataset_id = %s AND meta->>'thread' = %s AND id <> %s "
            "AND deleted_at IS NULL AND kind <> 'layer' ORDER BY said_at DESC NULLS LAST LIMIT 10",
            (ds_id, meta["thread"], me))], "same thread")
    if meta.get("reply_to"):
        got = find_by_key(ds_id, str(meta["reply_to"]))
        add([got["id"]] if got else [], "the item it replies to")
    if item.get("source_key"):
        add([r["id"] for r in db.rows(
            "SELECT id FROM synapse.item WHERE dataset_id = %s AND meta->'attached_to' ? %s AND deleted_at IS NULL "
            "ORDER BY stored_at LIMIT 10", (ds_id, item["source_key"]))], "a file attached to it")
    parents = _list(meta.get("attached_to"))
    if parents:
        # A file is one item however many emails it came on (keyed by its hash), so these are every
        # email with the same file.
        add([r["id"] for r in db.rows(
            "SELECT id FROM synapse.item WHERE dataset_id = %s AND source_key = ANY(%s) AND deleted_at IS NULL "
            "LIMIT 10", (ds_id, parents))], "an email it came on")
    digest = str(meta.get("sha256") or "") or (str(item.get("source_key") or "")[7:]
                                               if str(item.get("source_key") or "").startswith("sha256:") else "")
    if digest:
        # The same file stored again as an item of its own: an upload, or a file off an email
        # (card 1125, change 2). Both indexed (migration 0073).
        add([r["id"] for r in db.rows(
            "SELECT id FROM synapse.item WHERE dataset_id = %s AND deleted_at IS NULL AND id <> %s AND "
            "((meta ? 'sha256' AND meta->>'sha256' = %s) OR source_key = %s) LIMIT 10",
            (ds_id, me, digest, "sha256:" + digest))], "the same file")
    named = []
    for p in ((item.get("mentions") or {}).get("people_mentioned") or [])[:10]:
        named += list(p.get("emails") or []) + list(p.get("phones") or [])
        if not (p.get("emails") or p.get("phones")) and p.get("full_name_as_written"):
            named.append(p["full_name_as_written"])
    groups = [("its sender", _identifiers([meta.get("from")])),
              ("a recipient", _identifiers(_list(meta.get("to")) + _list(meta.get("cc")))),
              ("named in its text", _identifiers(named))]
    who = _people_by_identifier(ds, [w for _, ws in groups for w in ws])
    for reason, ws in groups:
        add([who[w] for w in ws if w in who], reason)
    cap = int(s.link_structure_max)
    return found[:cap], {x: why[x] for x in found[:cap]}


def link_candidates(ds: dict, item: dict, s, trace, owner) -> tuple[list[dict], dict]:
    """Top 20 for the helper call (D31), each step costing what its answer costs, never the dataset's size:
    structure first (`structure_candidates`), then one nearest-neighbour search on the item's own vector,
    then the words of only its rarest terms (by how many passages hold each, `search.rare_terms`), fused
    by rank. With screening on, the top 100 go to a decision model first (D74)."""
    began = time.time()
    s_ids, s_why = structure_candidates(ds, item, s)
    asker = item.get("owner") or datasets.me(ds)
    pool_size = int(s.screen_from) if ai.backend_for("link_screen", s) != "off" else int(s.link_candidates)
    depth = max(pool_size, 20)
    scope_ids = search.scope(ds["id"])
    rare = search.rare_terms(ds["id"], item["id"], scope_ids, int(s.link_rare_terms))
    qvec = search.item_vectors(ds["id"], [item["id"]]).get(item["id"])
    found = search.hybrid(ds["id"], "", qvec, asker=asker, settings=s, exclude_ids=[item["id"]],
                          exclude_kinds=["layer"], depth=depth, terms=rare, cap=int(s.link_words_cap))
    trace.call(kind="db", purpose="link_candidates_search", backend="postgresql", ms=found["ms"])
    readable = search.check_results(ds["id"], s_ids, search.readers_for(asker))
    structure = [{"item_id": x, "score": 1.0} for x in s_ids if x in readable]
    k = float(s.rrf_k)
    lists = {"structure": structure,
             "meaning": [{"item_id": f["item_id"], "score": f["scores"]["meaning"]}
                         for f in sorted((f for f in found["items"] if "meaning" in f["ranks"]),
                                         key=lambda f: f["ranks"]["meaning"])],
             "words": [{"item_id": f["item_id"], "score": f["scores"]["words"]}
                       for f in sorted((f for f in found["items"] if "words" in f["ranks"]),
                                       key=lambda f: f["ranks"]["words"])]}
    fused = search.fuse(lists, k)
    pool = fused[:pool_size]
    details = search.items_by_id(ds["id"], [p["item_id"] for p in pool])
    pool = [dict(p, item=details[p["item_id"]], why=s_why.get(p["item_id"], "")) for p in pool
            if p["item_id"] in details]
    info = {"searched_with": "structure, the item's own vector, and its rarest words: "
                             + ", ".join(t["lexeme"] for t in rare),
            "rare_terms": rare, "structure": len(structure), "pool": len(pool),
            "words_list": found["words"], "meaning_list": found["meaning"], "db_ms": found["ms"],
            "had_vector": qvec is not None}
    take = int(s.link_candidates)
    if len(pool) > take and ai.backend_for("link_screen", s) != "off":
        state = ("NEW ITEM:\n" + _item_head(item) + "\n" + " ".join((item.get("body") or "").split())[:2500] +
                 "\n\nCANDIDATES:\n" + "\n".join(_candidate_line(i + 1, p["item"]) for i, p in enumerate(pool)))
        questions = [ai.Noul(f"c{i + 1}", f"Is the new item about the same thing as [{i + 1}], or does it continue it?")
                     for i in range(len(pool))]
        ceiling = _ceiling([item["sensitivity"]] + [p["item"]["sensitivity"] for p in pool])
        got = ai.decide_many("link_screen", state, questions, per_call=int(s.rerank_per_call), ceiling=ceiling,
                             settings=s, trace=trace, items=[item["id"]] + [p["item_id"] for p in pool], owner=owner)
        info["screen"] = {k: v for k, v in got.items() if k != "questions"}
        if got.get("answers"):
            for i, p in enumerate(pool):
                a = got["answers"].get(f"c{i + 1}")
                p["p_screen"] = round(a["p_yes"], 4) if a else None
            ranked = sorted(pool, key=lambda p: -(p.get("p_screen") if p.get("p_screen") is not None else -1))
            chosen = ranked[:take]
            info["screened"] = f"{len(pool)} screened to {len(chosen)} by the decision model"
        else:
            chosen = pool[:take]
            info["screened"] = "fallback: search's top " + str(take)
    else:
        chosen = pool[:take]
        info["screened"] = f"search's top {take} (screening off or nothing to screen)"
    info["chosen"] = [{"n": i + 1, "id": p["item_id"], "title": p["item"]["title"], "kind": p["item"]["kind"],
                       "rrf": round(p["rrf"], 4), "ranks": p["ranks"], "p_screen": p.get("p_screen"),
                       "structure": p.get("why") or ""}
                      for i, p in enumerate(chosen)]
    info["ms"] = int((time.time() - began) * 1000)
    return chosen, info


def contradiction_screen(ds: dict, item: dict, candidates: list[dict], s, trace, owner) -> tuple[list[dict], dict]:
    """Older facts, decisions and promises near this item, screened for contradiction (D74)."""
    chosen_ids = {c["item_id"] for c in candidates}
    neighbours = db.rows(
        "SELECT DISTINCT o.id, o.title, o.xray, o.sensitivity, o.said_at FROM synapse.item o "
        "JOIN synapse.link l ON l.dataset_id = o.dataset_id AND l.src = o.id "
        "WHERE o.dataset_id = %s AND o.deleted_at IS NULL AND o.id <> %s AND o.xray IS NOT NULL "
        "AND l.dst IN (SELECT dst FROM synapse.link WHERE dataset_id = %s AND src = %s "
        "  AND type IN ('about', 'in', 'from', 'to', 'in_thread')) "
        "ORDER BY o.said_at DESC NULLS LAST LIMIT 200", (ds["id"], item["id"], ds["id"], item["id"]))
    for c in candidates:
        if c["item"].get("xray") and c["item_id"] not in {n["id"] for n in neighbours}:
            neighbours.append({"id": c["item_id"], "title": c["item"]["title"], "xray": c["item"]["xray"],
                               "sensitivity": c["item"]["sensitivity"], "said_at": c["item"].get("said_at")})
    claims = []
    for n in neighbours:
        for idx, c in enumerate((n.get("xray") or {}).get("claims") or []):
            if c.get("k") in ("fact", "decision", "promise"):
                claims.append({"item_id": n["id"], "title": n["title"], "idx": idx, "claim": c,
                               "sensitivity": n["sensitivity"], "in_top": n["id"] in chosen_ids})
    claims = claims[:int(s.contradiction_pool)]
    info = {"older_claims": len(claims)}
    if not claims:
        info["note"] = "no older facts, decisions or promises near this item"
        return [], info
    state = ("NEW ITEM:\n" + _item_head(item) + "\n" + " ".join((item.get("body") or "").split())[:2500] +
             "\n\nOLDER CLAIMS:\n" + "\n".join(f"[{i + 1}] {tx.claim_line(c['claim'])}" for i, c in enumerate(claims)))
    questions = [ai.Noul(f"k{i + 1}", f"Does the new item contradict or replace [{i + 1}]?") for i in range(len(claims))]
    got = ai.decide_many("contradiction_screen", state, questions, per_call=30,
                         ceiling=_ceiling([item["sensitivity"]] + [c["sensitivity"] for c in claims]),
                         settings=s, trace=trace, items=[item["id"]] + [c["item_id"] for c in claims], owner=owner)
    info["decision"] = {k: v for k, v in got.items() if k not in ("questions",)}
    picked = []
    for i, c in enumerate(claims):
        a = (got.get("answers") or {}).get(f"k{i + 1}")
        c["p"] = round(a["p_yes"], 4) if a else None
        if a and a["p_yes"] >= s.contradiction_noul:
            picked.append(c)
    picked = sorted(picked, key=lambda c: -c["p"])[:int(s.contradiction_max)]
    info["picked"] = [{"item": c["title"], "claim": c["claim"].get("c"), "p": c["p"]} for c in picked]
    info["threshold"] = s.contradiction_noul
    return picked, info


def xray_prompt(ds: dict, item: dict, candidates: list[dict], older: list[dict], s, *, content: str, target: int,
                hi: int, editing: dict | None = None, signals: str = "", attributes: bool = True,
                people: bool = True) -> dict:
    """The X-ray call's instructions and text, as `xray_call` sends them (and the benchmark of 4 October
    2026). `signals` are code's tier signals (D80), given when this call decides the tier (D82)."""
    shown = topic_choices(ds["id"], item["id"], s)
    lines = [_candidate_line(i + 1, c["item"]) for i, c in enumerate(candidates)]
    base = len(candidates)
    for j, c in enumerate(older):
        lines.append(f"[{base + j + 1}] an older claim in \"{c['title']}\": {tx.claim_line(c['claim'])}")
    existing = ""
    if editing and editing.get("links"):
        existing = "\n\nEXISTING LINKS (re-check each):\n" + "\n".join(
            f"[L{i + 1}] {l['type']} {l['dst_title'] or l['dst_kind']} (strength {l['strength']:.2f})"
            for i, l in enumerate(editing["links"]))
    areas = area_list(ds["id"], item["id"], s) if attributes else []
    text = ((f"SIGNALS:\n{signals}\n\n" if signals else "") +
            f"ITEM ({_item_head(item)}):\n{content}\n\nCANDIDATES:\n" + ("\n".join(lines) or "none") +
            "\n\nEXISTING TOPICS: " + ("; ".join(t["name"] for t in shown["topics"]) or "none") +
            "\n\nPROPOSED TOPICS (not topics yet): " + ("; ".join(t["name"] for t in shown["proposals"]) or "none") +
            ("\n\nEXISTING AREAS: " + ("; ".join(area_line(a) for a in areas) or "none yet") if attributes else "")
            + ("\n\nSILOS: " + silos_line(ds) if attributes else "")
            + existing)
    instructions = xray_instructions(attributes, people).format(
        words=s.claim_words, n=target, lo=int(s.claims_min), hi=hi, links=int(s.judgement_links_max),
        tier_words=int(s.tier_reason_words), me=owner_first_name(ds))
    return {"instructions": instructions, "text": text, "shown": shown, "areas": areas,
            "schema": xray_schema(attributes, people)}


def owner_first_name(ds: dict) -> str:
    """The owner as the people-mentioned instructions name them: only counted when named (Q21)."""
    return (people.owner_name_of(ds).split() or ["the owner"])[0]


def xray_call(ds: dict, item: dict, candidates: list[dict], older: list[dict], s, trace, owner,
              *, editing: dict | None = None, signals: str = "") -> tuple[dict, dict]:
    body = item.get("body") or ""
    n_words = tx.words(body)
    target = max(int(s.claims_min), min(int(s.claims_max), int(round(n_words / max(1, int(s.claims_per_words))))))
    sections, section_people = [], []
    if n_words > int(s.long_doc_words):
        # A long document: X-rayed per section, then once as a whole (D8).
        parts = tx.passages(body, 2000, 0)
        for i, part in enumerate(parts):
            got = ai.generate(
                model=s.helper_model, name="section_xray", purpose="xray_section", trace=trace, items=[item["id"]],
                owner=owner, instructions=XRAY_INSTRUCTIONS.format(words=s.claim_words, n=int(s.claims_max), lo=2,
                                                                   hi=int(s.claims_max), links=0,
                                                                   tier_words=int(s.tier_reason_words),
                                                                   me=owner_first_name(ds)),
                text=f"ITEM SECTION {i + 1} of {len(parts)}:\n{part}\n\nCANDIDATES: none", schema=XRAY_SCHEMA)
            sections.append({"n": i + 1, "gist": got.get("gist", ""), "claims": got.get("claims") or []})
            section_people.append(got)
        doc_text = "\n".join(f"Section {x['n']}: {x['gist']}" for x in sections)
        content = f"DOCUMENT (in {len(parts)} sections), section gists:\n{doc_text}\n\nBEGINNING:\n{body[:6000]}"
        target = int(s.doc_claims_max)
    else:
        content = body[:16000]
    asked = xray_prompt(ds, item, candidates, older, s, content=content, target=target,
                        hi=int(s.claims_max) if not sections else int(s.doc_claims_max), editing=editing,
                        signals=signals)
    shown, areas, text, instructions = asked["shown"], asked["areas"], asked["text"], asked["instructions"]
    got = ai.generate(model=s.helper_model, name="xray", purpose="xray", trace=trace,
                      items=[item["id"]] + [c["item_id"] for c in candidates], owner=owner,
                      instructions=instructions, text=text, schema=XRAY_SCHEMA, max_tokens=6000)
    xray = {"x": 1, "gist": got.get("gist", ""), "claims": got.get("claims") or [],
            "about": [t["name"] for t in got.get("topics") or []], "said_at": str(item.get("said_at") or ""),
            "_links": got.get("links") or [], "_topics": got.get("topics") or [],
            "_topics_refused": got.get("topics_refused") or [], "_topics_shown": shown, "_rules": got.get("rules") or [],
            "_terms": got.get("terms") or [], "_recheck": got.get("recheck") or [],
            "_model_tier": got.get("tier"), "_tier_why": got.get("tier_why", ""), "_title": got.get("title", ""),
            "_sens": got.get("sensitivity"), "_sens_why": got.get("sensitivity_why", ""), "_model": got.get("_model"),
            "_area": got.get("area", ""), "_silos": got.get("silos"), "_areas_shown": areas,
            "_cost": got.get("_cost", 0.0), "_ms": got.get("_ms", 0)}
    # People its text names (Q21 open): checked and kept as data, never linked or made into anyone.
    xray["_mentions"] = mentions.check(item.get("raw") or body, mentions.merge(section_people + [got]),
                                       model=got.get("_model") or s.helper_model)
    if sections:
        xray["sections"] = sections
    out = {"model": got.get("_model"), "asked_claims": target, "candidates_shown": len(candidates),
           "areas_shown": [area_line(a) for a in areas],
           "topics_shown": [t["name"] for t in shown["topics"]],
           "proposals_shown": [t["name"] for t in shown["proposals"]],
           "older_claims_shown": len(older), "prompt_chars": len(text) + len(instructions),
           "signals_shown": bool(signals),
           "answer": {k: v for k, v in got.items() if not k.startswith("_")}}
    out["sensitivity"] = model_sensitivity(item, got)
    out["people_mentioned"] = xray["_mentions"]
    return xray, out


def xray_tier(xray: dict, s) -> dict:
    """The tier the X-ray call decided (D82), with its reason, as the tier call's answer is shaped (D80)."""
    said = xray.get("_model_tier")
    words = int(s.tier_reason_words)
    why = " ".join(str(xray.get("_tier_why") or "").replace(chr(0x2014), " - ").split())
    why = " ".join(why.split()[:words + 10]) if why else "the model gave no reason"
    if said not in XRAY_TIER:
        return {"tier": 1, "said": said or "", "by": "none", "model": xray.get("_model") or "",
                "why": f"the X-ray call gave no tier ({said!r}), so tier 1 until it is asked again"}
    return {"tier": XRAY_TIER[said], "said": said, "why": why, "by": "xray_call", "backend": "openai",
            "model": xray.get("_model") or s.helper_model}


def model_sensitivity(item: dict, got: dict) -> dict:
    """The X-ray's sensitivity decides the item's level (D60), unless a person gave one with the item.

    What can only raise it still does: a level given with the item (the model may raise it, never
    lower it), an owner-set area in health, money, legal or finance, and this run's sensitivity
    suggestions (D75). A model-set area raises it afterwards (`_raise_for_area`)."""
    said = got.get("sensitivity")
    before = item.get("sensitivity") or "unlabelled"
    why = dict(item.get("sensitivity_why") or {})
    if said not in ("normal", "private", "special"):
        return {"before": before, "after": before, "set_by": "", "why": "the model gave no sensitivity, so it stays"}
    floor, held = [said], []
    given = why.get("given")
    if given in ("normal", "private", "special"):
        floor.append(given)
        held.append(f"{given}, given with the item")
    meta = item.get("meta") or {}
    area = str(meta.get("area") or "").lower()
    if area in SPECIAL_AREAS and area_by(item) == "owner":
        floor.append("special")
        held.append(f"special, in the {area} area the owner set")
    if ((why.get("decision") or {}).get("flagged")):
        floor.append("special")
        held.append("special, raised by the sensitivity suggestions (D75)")
    final = _ceiling(floor)
    model_why = got.get("sensitivity_why", "")
    why.pop("helper", None)
    why["model"] = f"{said}: {model_why}" if model_why else said
    if given == final:
        why["set_by"] = "given with the item" + ("" if said == final else f", above the model's {said}")
    elif final == said:
        why["set_by"] = "the model, when it read the item"
    else:
        why["set_by"] = f"raised above the model's {said}: " + "; ".join(h for h in held if h.startswith(final))
    db.run("UPDATE synapse.item SET sensitivity = %s, sensitivity_why = %s::jsonb WHERE id = %s",
           (final, Json(why), item["id"]))
    item["sensitivity"], item["sensitivity_why"] = final, why
    _raise_attachments(item, final)
    return {"before": before, "after": final, "the_model_said": said, "model_why": model_why,
            "set_by": why["set_by"]}


def quote_check(item: dict, xray: dict, s) -> tuple[dict, dict]:
    raw = item.get("raw") or ""
    kept, dropped = [], []
    for c in xray.get("claims") or []:
        if tx.quote_found(c.get("q", ""), raw):
            kept.append(c)
        else:
            dropped.append(c)
    total = len(kept) + len(dropped)
    rejected = bool(total) and len(dropped) > total * float(s.quote_reject_share)
    info = {"claims": total, "kept": len(kept), "dropped": [{"c": c.get("c"), "q": c.get("q")} for c in dropped],
            "rejected": rejected,
            "rule": f"over {int(float(s.quote_reject_share) * 100)}% failing rejects the X-ray"}
    # Claims keep their index into the kept list; links name claims by that index.
    index_map, n = {}, 0
    for i, c in enumerate(xray.get("claims") or []):
        if c in kept:
            index_map[i] = n
            n += 1
    xray["_claim_map"] = index_map
    if rejected:
        xray["claims"] = []
        xray["rejected"] = f"{len(dropped)} of {total} quotes were not in the item, so it falls back to raw (D10)"
    else:
        xray["claims"] = kept
    xray["dropped"] = len(dropped)
    return xray, info


def write_xray(ds: dict, item: dict, xray: dict, s, trace, owner) -> dict:
    stored = {k: v for k, v in xray.items() if not k.startswith("_")}
    by = {"model": xray.get("_model") or s.helper_model, "asked": s.helper_model, "at": _now().isoformat(),
          "purpose": "xray", "cost": None}
    db.run("UPDATE synapse.item SET xray = %s::jsonb, xray_by = %s::jsonb, xray_dropped = %s WHERE id = %s",
           (Json(stored), Json(by), int(xray.get("dropped") or 0), item["id"]))
    db.run("DELETE FROM synapse.passage WHERE dataset_id = %s AND item_id = %s AND from_xray", (ds["id"], item["id"]))
    if not stored.get("claims") and not stored.get("gist"):
        return {"passage": False}
    joined = (stored.get("gist") or "") + "\n" + "\n".join(tx.claim_line(c) for c in stored.get("claims") or [])
    # The X-ray passage sits beside the text pieces, marked by from_xray and with no seq.
    db.run("INSERT INTO synapse.passage (dataset_id, item_id, seq, text, words, from_xray) VALUES "
           "(%s, %s, NULL, %s, to_tsvector('english', %s) || to_tsvector('synapse.bg', %s) || "
           "to_tsvector('simple', %s), true)", (ds["id"], item["id"], joined, joined, joined, joined))
    passage = db.value("SELECT id FROM synapse.passage WHERE dataset_id = %s AND item_id = %s AND from_xray",
                       (ds["id"], item["id"]))
    vectors.store(ds, [{"id": passage, "text": joined}], trace=trace, purpose="embed_xray", items=[item["id"]],
                  owner=owner)
    return {"passage": True, "text": joined, "model": by["model"]}


def write_judgement_links(ds: dict, item: dict, xray: dict, candidates: list[dict], older: list[dict], s,
                          *, editing: dict | None = None) -> dict:
    made, refused = [], []
    base = len(candidates)
    claim_map = xray.get("_claim_map") or {}
    for link in (xray.get("_links") or [])[:int(s.judgement_links_max)]:
        n = int(link.get("target") or 0)
        if 1 <= n <= base:
            target = candidates[n - 1]
            dst, title = target["item_id"], target["item"]["title"]
        elif base < n <= base + len(older):
            target = older[n - base - 1]
            dst, title = target["item_id"], target["title"]
        else:
            refused.append({"target": n, "why": "not one of the numbered candidates"})
            continue
        ltype = link.get("type")
        if ltype not in numbers.JUDGEMENT_TYPES:
            refused.append({"target": n, "why": f"{ltype} is not a judgement link type"})
            continue
        if ltype == "contradicts" and link.get("strength") == "weak":
            link["strength"] = "medium"     # D29: contradicts is 0.6 or 0.9
        if ltype == "updates":
            link["strength"] = "strong"     # D29: updates is 0.9
        if ltype == "continues" and link.get("strength") == "weak":
            link["strength"] = "medium"     # the same conversation is never a weak tie: 0.6 or 0.9
        strength = s.strength(link.get("strength", "medium"))
        claim = link.get("claim")
        claim = claim_map.get(int(claim)) if isinstance(claim, int) and claim >= 0 else None
        got = add_link(ds["id"], item["id"], dst, ltype, strength, origin="model",
                       made_by=xray.get("_model") or s.helper_model, claim_idx=claim, why=link.get("why", ""),
                       evidence={"bucket": link.get("strength"), "candidate": n})
        made.append({"type": ltype, "to": title, "to_id": dst, "strength": strength, "bucket": link.get("strength"),
                     "why": link.get("why", ""), "claim": claim, "new": bool(got.get("made"))})
    out = {"made": made, "refused": refused, "max": int(s.judgement_links_max)}
    if editing:
        out["recheck"] = apply_recheck(ds, item, xray, editing, s)
    return out


def apply_recheck(ds: dict, item: dict, xray: dict, editing: dict, s) -> list[dict]:
    """An edit's verdicts on the item's existing judgement links (D33)."""
    done = []
    old = editing.get("links") or []
    verdicts = {int(v.get("link", 0)): v for v in xray.get("_recheck") or []}
    for i, link in enumerate(old, start=1):
        v = verdicts.get(i) or {"verdict": "keep", "why": "not mentioned, so kept"}
        if v["verdict"] == "drop":
            db.run("DELETE FROM synapse.link WHERE id = %s", (link["id"],))
            done.append({"link": f"{link['type']} {link['dst_title']}", "verdict": "removed", "why": v.get("why")})
        elif v["verdict"] == "change":
            strength = s.strength(v.get("strength", "medium"))
            if v.get("type") != link["type"]:
                db.run("DELETE FROM synapse.link WHERE id = %s", (link["id"],))
                add_link(ds["id"], item["id"], link["dst"], v.get("type"), strength, origin="model",
                         made_by=xray.get("_model") or "", why=v.get("why", ""))
            else:
                db.run("UPDATE synapse.link SET strength = %s, base_strength = %s, checked_at = now(), why = %s "
                       "WHERE id = %s", (strength, strength, v.get("why", "")[:500], link["id"]))
            word = "weakened" if strength < link["strength"] else "strengthened" if strength > link["strength"] else "changed"
            done.append({"link": f"{link['type']} {link['dst_title']}", "verdict": word,
                         "from": link["strength"], "to": strength, "type": v.get("type"), "why": v.get("why")})
        else:
            db.run("UPDATE synapse.link SET checked_at = now() WHERE id = %s", (link["id"],))
            done.append({"link": f"{link['type']} {link['dst_title']}", "verdict": "kept", "why": v.get("why")})
    return done


def recheck_without_model(ds: dict, item: dict, editing: dict) -> dict:
    """A short item after an edit: no helper reads it, so its old judgement links stay as they were."""
    return {"kept": [f"{l['type']} {l['dst_title']}" for l in editing.get("links") or []],
            "note": "Under the X-ray threshold, so no helper call re-checks them; they are kept."}


def _norm_topic(name: str) -> str:
    return " ".join(tx.norm(name).split())


#: How many existing topics, and how many open proposals, the X-ray is shown by name (D34).
TOPICS_SHOWN = 50
#: At most this many topics are taken from one item's X-ray (D34).
TOPICS_PER_ITEM = 2

# A topic or a proposing item is shown to the model, and matched, only when every reader
# of this item can read it: no name leaks to an item's readers from an item they cannot see.
_SEEN_BY_ALL = ("NOT EXISTS (SELECT 1 FROM synapse.reader r WHERE r.dataset_id = %s AND r.item_id = %s "
                "AND NOT EXISTS (SELECT 1 FROM synapse.reader r2 WHERE r2.dataset_id = r.dataset_id "
                "AND r2.item_id = {other} AND r2.principal IN (r.principal, 'everyone')))")


def topic_choices(ds_id: str, item_id: str, s) -> dict:
    """D34: the topics and the open proposals this item's readers can all see, busiest and newest first."""
    topics = db.rows(
        "SELECT t.id, t.title AS name, t.meta->>'norm' AS norm, count(l.src) AS items, "
        "greatest(t.stored_at, max(l.made_at)) AS last FROM synapse.item t "
        "LEFT JOIN synapse.link l ON l.dataset_id = t.dataset_id AND l.dst = t.id AND l.type = 'about' "
        "WHERE t.dataset_id = %s AND t.kind = 'topic' AND t.deleted_at IS NULL AND "
        + _SEEN_BY_ALL.format(other="t.id") +
        " GROUP BY t.id ORDER BY count(l.src) DESC, last DESC LIMIT %s",
        (ds_id, ds_id, item_id, TOPICS_SHOWN))
    proposals = db.rows(
        "SELECT min(p.name) AS name, p.norm, count(DISTINCT p.item_id) AS items, max(p.at) AS last "
        "FROM synapse.topic_proposal p JOIN synapse.item i ON i.dataset_id = p.dataset_id AND i.id = p.item_id "
        "WHERE p.dataset_id = %s AND i.deleted_at IS NULL AND p.item_id <> %s "
        "AND p.at > now() - make_interval(days => %s) "
        "AND NOT EXISTS (SELECT 1 FROM synapse.item t WHERE t.dataset_id = p.dataset_id AND t.kind = 'topic' "
        "AND t.deleted_at IS NULL AND t.meta->>'norm' = p.norm) AND "
        + _SEEN_BY_ALL.format(other="p.item_id") +
        " GROUP BY p.norm ORDER BY count(DISTINCT p.item_id) DESC, max(p.at) DESC LIMIT %s",
        (ds_id, item_id, int(s.topic_bar_days), ds_id, item_id, TOPICS_SHOWN))
    return {"topics": [{"id": t["id"], "name": t["name"], "norm": t["norm"] or _norm_topic(t["name"])} for t in topics],
            "proposals": [{"name": p["name"], "norm": p["norm"]} for p in proposals]}


def _topic_cosines(ds: dict, names: list[str], targets: list[str], s) -> tuple[list[list[float]], str]:
    """Each proposed name's cosine to each target name, in the dataset's own embedding model, or why not."""
    model = vectors.live_model(ds["id"])
    if not names or not targets:
        return [], ""
    if not ai.can_embed(model):
        return [], f"no key for {model} on this machine: names are matched exactly only"
    try:
        vecs = ai.embed(names + targets, model=model, purpose="topic_match", input_type="document")
    except Exception as exc:  # noqa: BLE001 - exact names still match
        return [], f"{type(exc).__name__}: {exc}"[:200] + " - names are matched exactly only"

    def unit(v):
        n = sum(x * x for x in v) ** 0.5 or 1.0
        return [x / n for x in v]
    vecs = [unit(v) for v in vecs]
    mine, theirs = vecs[:len(names)], vecs[len(names):]
    return [[sum(a * b for a, b in zip(m, t)) for t in theirs] for m in mine], ""


def write_topics(ds: dict, item: dict, xray: dict, s) -> dict:
    """D34, revised 4 October 2026: at most 2 broad topics an item; a name links to an existing
    topic, or counts towards an open proposal, when it is spelt the same or means the same;
    a new topic is made only once enough items propose it."""
    linked, proposed, created, decisions = [], [], [], []
    readers = readers_of(ds["id"], item["id"])
    refused = [{"name": str(r.get("name") or ""), "by": "model", "why": str(r.get("why") or "")}
               for r in xray.get("_topics_refused") or [] if r.get("name")]
    # A re-read replaces what this item proposed; it never adds to it.
    db.run("DELETE FROM synapse.topic_proposal WHERE dataset_id = %s AND item_id = %s", (ds["id"], item["id"]))
    shown = xray.get("_topics_shown") or topic_choices(ds["id"], item["id"], s)
    contacts = {_norm_topic(r["title"]) for r in db.rows(
        "SELECT title FROM synapse.item WHERE dataset_id = %s AND kind = 'person' AND deleted_at IS NULL "
        "AND title <> ''", (ds["id"],))}
    wanted = []
    for t in xray.get("_topics") or []:
        name = " ".join(str(t.get("name") or "").split())[:80]
        if not name:
            continue
        norm = _norm_topic(name)
        if norm in contacts:
            refused.append({"name": name, "by": "code", "why": "the name of a contact: people and organisations are "
                                                               "linked as contacts, never as topics"})
        elif len(wanted) >= TOPICS_PER_ITEM:
            refused.append({"name": name, "by": "code", "why": f"over the limit of {TOPICS_PER_ITEM} topics an item"})
        elif norm not in {w["norm"] for w in wanted}:
            wanted.append({"name": name, "norm": norm, "strength": s.strength(t.get("strength", "medium"))})
    targets = [("topic", x) for x in shown["topics"]] + [("proposal", x) for x in shown["proposals"]]
    # A name spelt like a topic or an open proposal joins it as it always did, seen or not;
    # only a name spelt like none of them is matched by meaning, among those all readers can see.
    spelt = {}
    for w in wanted:
        topic = db.row("SELECT id, title AS name FROM synapse.item WHERE dataset_id = %s AND kind = 'topic' AND "
                       "deleted_at IS NULL AND meta->>'norm' = %s", (ds["id"], w["norm"]))
        if topic:
            spelt[w["norm"]] = ("topic", topic)
        elif db.value("SELECT 1 FROM synapse.topic_proposal WHERE dataset_id = %s AND norm = %s AND item_id <> %s "
                      "AND at > now() - make_interval(days => %s) LIMIT 1",
                      (ds["id"], w["norm"], item["id"], int(s.topic_bar_days))):
            spelt[w["norm"]] = ("proposal", {"name": w["name"], "norm": w["norm"]})
    loose = [w for w in wanted if w["norm"] not in spelt]
    sims, why_not = _topic_cosines(ds, [w["name"] for w in loose], [x["name"] for _, x in targets], s)
    bar = float(s.topic_match_cosine)
    for w in wanted:
        name, norm, strength = w["name"], w["norm"], w["strength"]
        how, similarity, closest = "new", None, ""
        if norm in spelt:
            kind, target = spelt[norm]
            how = "reused"
        else:
            kind, target = None, None
            row = sims[loose.index(w)] if sims else []
            if row:
                best = max(range(len(row)), key=lambda j: row[j])
                similarity, closest = round(row[best], 3), targets[best][1]["name"]
                if row[best] >= bar:
                    kind, target = targets[best]
                    how = "matched by meaning"
        if kind == "topic":
            topic = db.row("SELECT id, title FROM synapse.item WHERE dataset_id = %s AND id = %s AND deleted_at IS NULL",
                           (ds["id"], target["id"]))
            if topic:
                add_link(ds["id"], item["id"], topic["id"], "about", strength, origin="model",
                         made_by=xray.get("_model") or "", why=f"about the topic {topic['title']}")
                linked.append({"topic": topic["title"], "strength": strength})
                decisions.append({"proposed": name, "outcome": how + ", linked to the topic", "became": topic["title"],
                                  "similarity": similarity, "closest": closest})
                continue
        if kind == "proposal" and how == "matched by meaning":
            name, norm = target["name"], target["norm"]
        db.run("INSERT INTO synapse.topic_proposal (dataset_id, name, norm, item_id, strength) VALUES (%s, %s, %s, %s, %s)",
               (ds["id"], name, norm, item["id"], strength))
        props = db.rows("SELECT DISTINCT ON (item_id) item_id, strength, name FROM synapse.topic_proposal "
                        "WHERE dataset_id = %s AND norm = %s AND at > now() - make_interval(days => %s)",
                        (ds["id"], norm, int(s.topic_bar_days)))
        if len(props) >= int(s.topic_bar_items):
            topic_readers = None
            for p in props:
                r = set(readers_of(ds["id"], p["item_id"]))
                topic_readers = r if topic_readers is None else (topic_readers & r)
            topic_readers = sorted(topic_readers or set(readers))
            new = db.row("INSERT INTO synapse.item (dataset_id, kind, source, source_key, title, raw, body, tier, "
                         "tier_why, sensitivity, owner, meta, status) VALUES (%s, 'topic', 'synapse', %s, %s, %s, %s, 1, "
                         "'a topic', 'normal', %s, %s::jsonb, 'ready') RETURNING *",
                         (ds["id"], "topic:" + norm, name, name, name, datasets.me(ds),
                          Json({"norm": norm, "made_from": [p["item_id"] for p in props]})))
            set_readers(ds["id"], new["id"], topic_readers)
            db.run("INSERT INTO synapse.passage (dataset_id, item_id, seq, text, words) VALUES "
                   "(%s, %s, 1, %s, to_tsvector('english', %s) || to_tsvector('simple', %s))",
                   (ds["id"], new["id"], name, name, name))
            enqueue(ds["id"], "embed", item_id=new["id"], priority=6)
            for p in props:
                add_link(ds["id"], p["item_id"], new["id"], "about", float(p["strength"]), origin="model",
                         made_by=xray.get("_model") or "", why=f"about the topic {name}")
            derive(ds["id"], "item", new["id"], [p["item_id"] for p in props])
            created.append({"topic": name, "from_items": len(props), "readers": topic_readers})
            outcome = "made a topic"
        else:
            proposed.append({"topic": name, "proposals": len(props), "needs": int(s.topic_bar_items)})
            outcome = f"proposed, {len(props)} of the {int(s.topic_bar_items)} items it needs"
        lead = {"reused": "reused a proposal, ", "matched by meaning": "matched a proposal by meaning, "}.get(how, "new, ")
        decisions.append({"proposed": w["name"], "outcome": lead + outcome, "became": name, "similarity": similarity,
                          "closest": closest})
    return {"decisions": decisions, "refused": refused, "linked": linked, "proposed": proposed, "created": created,
            "shown": {"topics": len(shown["topics"]), "proposals": len(shown["proposals"])},
            "meaning": {"threshold": bar, "model": vectors.live_model(ds["id"]), "note": why_not},
            "rule": f"at most {TOPICS_PER_ITEM} topics an item; a name links when it is spelt or means the same "
                    f"(cosine {bar:.2f} or more); a new topic needs {int(s.topic_bar_items)} items within "
                    f"{int(s.topic_bar_days)} days"}


#: What a rule can come from on its own: the owner's own words, a note they wrote or their own mail (D59).
RULE_KINDS = ("note", "mail")
#: Synapse Master's copies of Rouh's tasks, files and cards: what a document says to do is the document's
#: content, never an instruction to Rouh, so it stays a claim of the item and is found with it. And a note
#: kept as a note (`rouh/rules.py`): the person chose a note, not a rule. And a thought (`rouh/thoughts.py`):
#: a musing is not an instruction, however it is worded.
CONTENT_SOURCES = ("rouh-task", "rouh-file", "rouh-card", "rouh-memory", "rouh-thoughts")
#: Rouh's chats. A rule said in one used to wait for the owner on the Rules page ("Said in a conversation,
#: waiting for you"); since 6 October 2026 it is kept as a claim of the chat and nothing more.
CHAT_SOURCES = ("rouh-chat",)


def write_rules(ds: dict, item: dict, xray: dict, me: str, s) -> dict:
    """D59: a rule the owner stated in their own note or mail becomes a rule item; anything else that sounds
    like a rule - a chat's, anybody else's mail, a document's, a task's, a file's or a card's - is kept as a
    claim of its item and makes nothing.

    Until 5 October 2026 any item the owner owned counted as the owner's words, and Synapse Master owns every
    file of the workspace, so 658 sentences of plans and instruction files became rules, 50 of them for the
    whole account, and every answer was told to follow them.

    Until 6 October 2026 a rule in a chat, or in somebody else's mail, waited for the owner in
    `meta.pending_rules`, listed on the Rules page as "Said in a conversation, waiting for you". Petar had it
    removed (fr_210b5ae6725a): "I get too much spam that produces too little value". What is already waiting
    is left on its items as it was; nothing new is added. A rule he wants, he says with `remember` or adds on
    the Rules page."""
    claims = xray.get("claims") or []
    claim_map = xray.get("_claim_map") or {}
    idxs = set()
    for i in xray.get("_rules") or []:
        if isinstance(i, int) and claim_map.get(i) is not None:
            idxs.add(claim_map[i])
    for i, c in enumerate(claims):
        if c.get("k") == "rule":
            idxs.add(i)
    if not idxs:
        return {"rules": [], "note": "no standing instructions in this item"}
    if item.get("source") in CONTENT_SOURCES + CHAT_SOURCES or item.get("kind") not in RULE_KINDS:
        return {"rules": [], "kept_as_claims": len(idxs),
                "note": "What a chat, a document, a task, a file or a card says to do is kept as its claims and "
                        "found with it, never made a rule (D59). Rules come from the owner's own note or mail."}
    sender = (item.get("meta") or {}).get("from") or ""
    who = people.find_address(ds, sender) if sender else None
    author = str(who["id"]) if who else (item.get("owner") or me) if not sender else "nobody:" + sender
    if author != me:
        return {"rules": [], "kept_as_claims": len(idxs),
                "note": f"Said by {people.name_of(author) if who else sender or 'somebody else'}, not the owner: "
                        "kept as its claims, never made a rule (D59)."}
    made = [make_rule(ds, claims[i].get("c", ""), item, why=f"stated by {people.name_of(author)} in this item")
            for i in sorted(idxs) if i < len(claims)]
    return {"made": made}


def make_rule(ds: dict, text: str, source_item: dict | None, *, why: str = "", targets: list[str] | None = None,
              origin: dict | None = None) -> dict:
    import uuid

    key = "rule-" + uuid.uuid4().hex[:10]
    meta: dict = {"made_from": source_item["id"] if source_item else None}
    if source_item and not targets:
        sm = source_item.get("meta") or {}
        targets = [t for t in (sm.get("task"), sm.get("project")) if t]
        if not targets and sm.get("from"):
            targets = [tx.address_of(sm["from"])[1]]
    if targets:
        meta["rule_for"] = targets
    else:
        meta["scope"] = "account"
    if source_item:
        # Made by Synapse on its own from what it read: flagged From agents on the Rules page, with what it read, and
        # put in a group by what it says (`rouh/rules.py`, `rouh/rule_groups.py`).
        from .. import rule_groups, rules

        what = "email" if source_item.get("kind") == "mail" else str(source_item.get("kind") or "item")
        title = " ".join(str(source_item.get("title") or "").split())[:80]
        meta.update({"origin": origin or rules.origin_of("agents", f"Synapse made it on its own from your {what}"
                                                                 + (f" “{title}”" if title else "") + "."),
                     "group": rule_groups.sort(text), "group_by": "rouh"})
    rule = db.row("INSERT INTO synapse.item (dataset_id, kind, source, source_key, title, raw, body, tier, tier_why, "
                  "sensitivity, owner, meta, status, said_at) VALUES (%s, 'rule', 'synapse', %s, %s, %s, %s, 2, 'a rule', "
                  "'normal', %s, %s::jsonb, 'ready', now()) RETURNING *",
                  (ds["id"], key, " ".join(text.split())[:200], text, text, datasets.me(ds), Json(meta)))
    set_readers(ds["id"], rule["id"], [datasets.me(ds)])
    s = datasets.settings(ds)
    links = code_links(ds, rule, s)
    if source_item:
        derive(ds["id"], "item", rule["id"], [source_item["id"]])
    return {"rule": text, "id": rule["id"], "for": meta.get("rule_for") or "the whole account",
            "links": [l["to"] for l in links], "why": why}


def write_terms(ds: dict, item: dict, xray: dict) -> dict:
    out = []
    for t in xray.get("_terms") or []:
        term = " ".join(str(t.get("term") or "").split())[:60]
        if not term:
            continue
        db.run("INSERT INTO synapse.word_proposal (dataset_id, term, norm, meaning, area, item_id) "
               "VALUES (%s, %s, %s, %s, %s, %s)", (ds["id"], term, tx.norm(term), str(t.get("meaning") or "")[:200],
                                                   (item.get("meta") or {}).get("area") or "", item["id"]))
        n = db.value("SELECT count(DISTINCT item_id) FROM synapse.word_proposal WHERE dataset_id = %s AND norm = %s",
                     (ds["id"], tx.norm(term)))
        out.append({"term": term, "meaning": t.get("meaning"), "items_so_far": n})
    return {"terms": out}


def short_item_links(ds: dict, item: dict, candidates: list[dict], s, trace, owner) -> dict:
    """Up to 3 `about` links to existing topics or tasks for an item with no X-ray (D74)."""
    pool = [c for c in candidates if c["item"]["kind"] in ("topic", "task", "project")][:int(s.short_link_pool)]
    if not pool:
        return {"skipped": True, "note": "no topics or tasks among the candidates"}
    if ai.backend_for("short_links", s) == "off":
        return {"skipped": True, "note": "the decision model is off for short items, so it gets code links only"}
    state = ("NEW ITEM:\n" + _item_head(item) + "\n" + (item.get("body") or "")[:2000] + "\n\nCANDIDATES:\n" +
             "\n".join(_candidate_line(i + 1, c["item"]) for i, c in enumerate(pool)))
    got = ai.decide_many("short_links", state,
                         [ai.Noul(f"c{i + 1}", f"Is the new item about [{i + 1}]?") for i in range(len(pool))],
                         per_call=30, ceiling=_ceiling([item["sensitivity"]] + [c["item"]["sensitivity"] for c in pool]),
                         settings=s, trace=trace, items=[item["id"]] + [c["item_id"] for c in pool], owner=owner)
    scored = []
    for i, c in enumerate(pool):
        a = (got.get("answers") or {}).get(f"c{i + 1}")
        scored.append((a["p_yes"] if a else 0.0, c))
    made = []
    for p, c in sorted(scored, key=lambda x: -x[0]):
        if p >= s.short_link_noul and len(made) < int(s.short_links_max):
            add_link(ds["id"], item["id"], c["item_id"], "about", float(s.strength_medium), origin="decision",
                     made_by=f"{got.get('backend')}:{got.get('model', '')}", why="a short item's about link",
                     evidence={"p_yes": round(p, 4)})
            made.append({"to": c["item"]["title"], "p_yes": round(p, 4)})
    return {"decision": {k: v for k, v in got.items() if k != "questions"},
            "scored": [{"to": c["item"]["title"], "p_yes": round(p, 4)} for p, c in scored],
            "made": made, "threshold": s.short_link_noul}


# ---------------------------------------------------------------------------------------
# editing (D27, D33)
# ---------------------------------------------------------------------------------------

def edit(ds: dict, item_id: str, changes: dict, *, by: str = "page", hold: bool = False) -> dict:
    if ds.get("frozen"):
        return {"ok": False, "why": FROZEN_WORDS}
    item = get_item(ds["id"], item_id)
    if item is None or item.get("deleted_at") is not None:
        return {"ok": False, "why": "There is no such item in this dataset."}
    if item["kind"] == "person":
        return edit_person(ds, item, changes, by=by)
    s = datasets.settings(ds)
    trace = Trace(ds["id"], "edit", f"Edit: {item['title']}", by=by, item_id=item_id)
    new_raw = str(changes.get("text") if changes.get("text") is not None else changes.get("raw", item["raw"]) or "")
    new_raw = new_raw.replace("\x00", "")  # as in `store`
    new_title = " ".join(str(changes.get("title") or item["title"]).split())[:300]
    meta = dict(item.get("meta") or {})
    for k in ("from", "to", "cc", "thread", "reply_to", "task", "project", "starred", "rule_for", "known",
              # What Synapse Master notices a change by (`master.py`): kept up to date by an edit too.
              "file_name", "file_type", "file_size", "file_mtime", "messages", "card_version", "gcal",
              # A meeting's own facts from the library (`meetings.py`).
              "meeting",
              # A Slack conversation's day: where, whose, and what it was when kept (`rouh/slack.py`).
              "slack"):
        if k in changes and changes[k] not in (None,):
            meta[k] = _list(changes[k]) if k in ("to", "cc", "rule_for") else changes[k]
    if changes.get("area") is not None:
        # The owner's area always wins: once they change it, the model never sets it again (D16).
        area = _area_name(changes["area"])
        if area != (meta.get("area") or ""):
            meta.pop("area_proposed", None)
            if area:
                meta["area"] = area
            else:
                meta.pop("area", None)
            meta.update({"area_by": "owner", "area_why": f"set by an edit ({by})" if area else
                         f"taken off by an edit ({by}), so the item stays under General"})
    if new_title != item["title"]:
        meta.update({"title_by": "given", "title_why": f"set by an edit ({by})"})
    said_at = _when(changes.get("said_at")) or item.get("said_at")
    for k in ("start", "end", "place", "attendees", "name", "address", "coordinates"):
        if k in changes and changes[k] not in (None,):
            meta[k] = _list(changes[k]) if k == "attendees" else changes[k]
    problems = kinds.check(item["kind"], kinds.fill(item["kind"], meta, title=new_title, said_at=said_at))
    if problems:
        return {"ok": False, "why": " ".join(problems)}
    with trace.step("diff", "What changed") as st:
        diff = list(difflib.unified_diff((item["raw"] or "").splitlines(), new_raw.splitlines(),
                                         "before", "after", lineterm="", n=1))
        meta_changed = {k: {"before": (item.get("meta") or {}).get(k), "after": meta.get(k)}
                        for k in set(meta) | set(item.get("meta") or {})
                        if meta.get(k) != (item.get("meta") or {}).get(k) and k != "pending_rules"}
        st.data.update({"diff": diff[:400], "title": {"before": item["title"], "after": new_title}
                        if new_title != item["title"] else None, "meta": meta_changed,
                        "readers": changes.get("readers")})
        # An item stored before nothing was cut (D25) has a body shorter than its raw text:
        # an edit that changes nothing else still makes its searchable text whole.
        whole_again = (item.get("body") or "") != new_raw
        if whole_again and not diff:
            st.data["note"] = ("The text is unchanged, but its searchable copy was trimmed from it under the old cutting rule, "
                               "so it is made whole again.")
        if not diff and not whole_again and new_title == item["title"] and not meta_changed \
                and not changes.get("readers") and not changes.get("sensitivity"):
            st.data["note"] = "Nothing changed, so nothing is rebuilt."
            trace.finish("done", unchanged=True)
            return {"ok": True, "item": item_id, "trace": trace.id, "unchanged": True}
    with trace.step("version", "The old version kept (D27)") as st:
        keep_days = int(s.version_days)
        db.run("INSERT INTO synapse.item_version (dataset_id, item_id, version, title, raw, meta, xray, xray_by, "
               "keep_until, why) VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, "
               "now() + make_interval(days => %s), %s)",
               (ds["id"], item_id, item["version"], item["title"], item["raw"], Json(item.get("meta") or {}),
                Json(item.get("xray")) if item.get("xray") is not None else None,
                Json(item.get("xray_by")) if item.get("xray_by") is not None else None, keep_days,
                f"edited by {by}"))
        st.data.update({"version": item["version"], "kept_days": keep_days,
                        "note": "Kept, not searchable; the X-ray before can be compared with the new one."})
    body = new_raw
    old_links = [l for l in link_rows(ds["id"], item_id) if l["src"] == item_id and l["origin"] in ("model", "decision")]
    with trace.step("rewrite", "The item rewritten, its passages and words made again from the whole text (D24, D25)") as st:
        old_passages = db.value("SELECT count(*) FROM synapse.passage WHERE dataset_id = %s AND item_id = %s",
                                (ds["id"], item_id))
        db.run("UPDATE synapse.item SET raw = %s, body = %s, title = %s, meta = %s::jsonb, said_at = %s, "
               "version = version + 1, updated_at = now(), status = 'words' WHERE id = %s",
               (new_raw, body, new_title, Json(meta), said_at, item_id))
        if changes.get("readers"):
            set_readers(ds["id"], item_id, people.reader_ids(ds, _list(changes["readers"])))
        if changes.get("sensitivity") in ("normal", "private", "special"):
            why = dict(item.get("sensitivity_why") or {})
            why.update({"given": changes["sensitivity"], "code": f"given with the edit, by {by}"})
            db.run("UPDATE synapse.item SET sensitivity = %s, sensitivity_why = %s::jsonb WHERE id = %s",
                   (changes["sensitivity"], Json(why), item_id))
        # Every passage of the item's own text and its X-ray passage; another part's, such as a meeting's
        # transcript, is its own code's to keep (`meetings.py`).
        db.run("DELETE FROM synapse.passage WHERE dataset_id = %s AND item_id = %s AND part = ''",
               (ds["id"], item_id))
        made = write_passages(ds["id"], item_id, new_title, body, s)
        st.data.update({"passages_before": old_passages, "passages_after": made,
                        "readers": readers_of(ds["id"], item_id),
                        "reader_names": [people.name_of(r) for r in readers_of(ds["id"], item_id)]})
    with trace.step("code_links", "Code links recomputed (D33)") as st:
        before = {(l["type"], l["dst"]) for l in link_rows(ds["id"], item_id) if l["src"] == item_id and l["origin"] == "code"}
        was_people = [l["dst"] for l in link_rows(ds["id"], item_id) if l["src"] == item_id and l["dst_kind"] == "person"]
        db.run("DELETE FROM synapse.link WHERE dataset_id = %s AND src = %s AND origin = 'code'", (ds["id"], item_id))
        item2 = get_item(ds["id"], item_id)
        made = code_links(ds, item2, s)
        after = {(l["type"], l["to_id"]) for l in made}
        gone = set(was_people) - {l["to_id"] for l in made}
        if gone:
            st.data["people_values"] = people.linked(ds, gone).get("values")
        st.data.update({"links": made, "added": [f"{t} {d}" for t, d in after - before],
                        "removed": [f"{t} {d}" for t, d in before - after], "kept": len(after & before)})
    with trace.step("layers_touched", "Layers built from this item, to rebuild (D54)") as st:
        layers_from = db.rows("SELECT DISTINCT l.src AS layer_id, i.title FROM synapse.link l JOIN synapse.item i "
                              "ON i.dataset_id = l.dataset_id AND i.id = l.src WHERE l.dataset_id = %s AND l.dst = %s "
                              "AND l.type = 'built_from' AND i.deleted_at IS NULL", (ds["id"], item_id))
        st.data["layers"] = [r["title"] for r in layers_from]
    with trace.step("queued", "The model's part queued: X-ray rebuilt, links re-checked") as st:
        job = enqueue(ds["id"], "reingest", item_id=item_id, trace_id=trace.id, priority=2,
                      delay_s=300 if hold else 0, payload={"links": [{k: l[k] for k in ("id", "type", "dst", "strength", "dst_title", "dst_kind")}
                                         for l in old_links],
                               "old_xray": item.get("xray"), "layers": [r["layer_id"] for r in layers_from]})
        st.data.update({"job": job, "judgement_links_to_recheck": len(old_links)})
    db.run("UPDATE synapse.trace SET status = 'queued' WHERE id = %s", (trace.id,))
    return {"ok": True, "item": item_id, "trace": trace.id, "job": job}


PERSON_FIELDS = ("organisation", "birthday", "note", "relationship", "research")


def edit_person(ds: dict, item: dict, changes: dict, *, by: str = "page") -> dict:
    """A person's own fields, identifiers and readers, by code; their words again, and a vector
    only if something links to them (decision 10). `ds` is the dataset the person lives in."""
    pid = item["id"]
    meta = dict(item.get("meta") or {})
    trace = Trace(ds["id"], "edit", f"Edit person: {item['title']}", by=by, item_id=pid)
    name = " ".join(str(changes.get("title") or changes.get("name") or item["title"]).split())[:200]
    meta["name"] = name
    for k in PERSON_FIELDS:
        if changes.get(k) is not None:
            meta[k] = str(changes[k]).strip()
    if changes.get("known") is not None:
        meta["known"] = bool(changes["known"]) and changes["known"] not in ("false", "no", "0")
    new_emails = [e for e in (people.norm_email(x) for x in _list(changes.get("emails"))) if e]
    new_phones = [p for p in (people.norm_phone(x) for x in _list(changes.get("phones"))) if p]
    meta["emails"] = list(dict.fromkeys((meta.get("emails") or []) + new_emails))
    meta["phones"] = list(dict.fromkeys((meta.get("phones") or []) + new_phones))
    problems = kinds.check("person", meta)
    if problems:
        trace.finish("failed", error=" ".join(problems))
        return {"ok": False, "why": " ".join(problems), "trace": trace.id}
    with trace.step("diff", "What changed") as st:
        before = item.get("meta") or {}
        st.data["meta"] = {k: {"before": before.get(k), "after": meta.get(k)} for k in set(meta) | set(before)
                           if meta.get(k) != before.get(k)}
        if name != item["title"]:
            st.data["title"] = {"before": item["title"], "after": name}
    with trace.step("version", "The old version kept (D27)") as st:
        db.run("INSERT INTO synapse.item_version (dataset_id, item_id, version, title, raw, meta, keep_until, why) "
               "VALUES (%s, %s, %s, %s, %s, %s::jsonb, now() + make_interval(days => %s), %s)",
               (ds["id"], pid, item["version"], item["title"], item["raw"], Json(before),
                int(datasets.settings(ds).version_days), f"edited by {by}"))
        st.data["version"] = item["version"]
    with trace.step("identities", "Identifiers added: an address or a phone belongs to one person") as st:
        out = []
        for t, vals in (("email", new_emails), ("phone", new_phones)):
            for v in vals:
                got = people.add_identity(ds["id"], pid, t, v, v, f"added by an edit ({by})")
                out.append({"type": t, "value": v, "result": got if got in ("added", "had") else
                            f"already {people.name_of(got)}'s, so not added"})
                if got not in ("added", "had"):
                    meta[t + "s"] = [x for x in meta[t + "s"] if x != v]
        people.add_identity(ds["id"], pid, "name", people.norm_name(name), name, f"named so by an edit ({by})")
        st.data["identifiers"] = out
    body = people.person_text(meta, ds.get("owner_name") or "the owner")
    db.run("UPDATE synapse.item SET title = %s, raw = %s, body = %s, meta = %s::jsonb, version = version + 1, "
           "updated_at = now() WHERE id = %s", (name, body, body, Json(meta), pid))
    if changes.get("readers"):
        set_readers(ds["id"], pid, people.reader_ids(ds, _list(changes["readers"])))
    with trace.step("words", "Words again; a vector only once something links to them (decision 10)") as st:
        st.data["passages"] = people.write_words(ds["id"], pid, name, body + " " + tx.other_alphabet(name))
        st.data.update(people.linked(ds, [pid]))
        st.data["readers"] = [people.name_of(r) for r in readers_of(ds["id"], pid)]
    if ds.get("master") and before.get("icloud"):
        with trace.step("icloud", "A contact: the change written to iCloud, and so to the phone") as st:
            from . import contacts

            st.data["job"] = contacts.push_soon(ds, pid, before, meta, by=by)
    trace.finish("done")
    return {"ok": True, "item": pid, "trace": trace.id}


def model_part_of_edit(ds: dict, item_id: str, trace_id: str, payload: dict) -> dict:
    db.run("UPDATE synapse.item SET xray = NULL WHERE id = %s", (item_id,))
    got = model_part(ds, item_id, trace_id, editing={"links": payload.get("links") or []})
    trace = Trace(ds["id"], "edit", "", trace_id=trace_id)
    with trace.step("xray_diff", "The X-ray before and after") as st:
        new = (get_item(ds["id"], item_id) or {}).get("xray") or {}
        old = payload.get("old_xray") or {}
        before = [c.get("c") for c in old.get("claims") or []]
        after = [c.get("c") for c in new.get("claims") or []]
        st.data.update({"gist_before": old.get("gist"), "gist_after": new.get("gist"),
                        "claims_removed": [c for c in before if c not in after],
                        "claims_added": [c for c in after if c not in before],
                        "claims_kept": [c for c in after if c in before]})
    with trace.step("layers_rebuilt", "Layers built from it, rebuilt (D54)") as st:
        from . import layers
        jobs = [layers.queue_rebuild(ds, lid, "an item it was built from was edited") for lid in payload.get("layers") or []]
        st.data["jobs"] = jobs
    trace.finish("done" if got.get("ok") else "failed", **{k: v for k, v in got.items() if k != "ok"})
    return got


# ---------------------------------------------------------------------------------------
# deleting (D60)
# ---------------------------------------------------------------------------------------

def _phrases(raw: str) -> list[str]:
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", raw or "") if len(s.strip()) > 25]
    sentences.sort(key=len, reverse=True)
    return [s[:120] for s in sentences[:3]]


def delete(ds: dict, item_id: str, *, by: str = "page", scrub: bool = True) -> dict:
    """D60's deletion. `scrub=False` is for an item whose words are still in Master under another key, such as a
    workspace file that moved to another project: its words are not taken out of the logged prompts and the
    debugger's records, which would only cut them out of the moved copy's records too, and cost a pass over
    every record in the dataset for each such file (on 13 October 2026, 874 files of two moved tasks, about
    30 seconds each, held Rouh's page for hours)."""
    if ds.get("frozen"):
        return {"ok": False, "why": FROZEN_WORDS}
    item = get_item(ds["id"], item_id)
    if item is None or item.get("deleted_at") is not None:
        return {"ok": False, "why": "There is no such item in this dataset."}
    trace = Trace(ds["id"], "delete", f"Delete: {item['title']}", by=by, item_id=item_id)
    # Passages of another part than the item's own text, such as a meeting's transcript (`meetings.py`): their
    # words are not in the raw copy, so they are read now to be looked for and taken out of the logs too.
    other = [r["text"] for r in db.rows("SELECT text FROM synapse.passage WHERE dataset_id = %s AND item_id = %s "
                                        "AND part <> '' ORDER BY part, seq", (ds["id"], item_id))]
    phrases = _phrases(item["raw"]) + (_phrases("\n".join(other)) if other else [])
    with trace.step("tombstone", "Tombstoned: out of every search from this moment (D60, step 1)") as st:
        db.run("UPDATE synapse.item SET deleted_at = now(), status = 'deleted' WHERE id = %s", (item_id,))
        db.run("UPDATE synapse.job SET done_at = now(), error = 'the item was deleted' WHERE dataset_id = %s "
               "AND item_id = %s AND done_at IS NULL", (ds["id"], item_id))
        st.data.update({"source_key": item["source_key"], "kind": item["kind"]})
    if ds.get("master") and item["kind"] == "person" and (item.get("meta") or {}).get("icloud"):
        with trace.step("icloud", "A contact: deleted from iCloud too, and so from the phone") as st:
            from . import contacts

            st.data["job"] = contacts.delete_soon(ds, item, by=by)
    with trace.step("derived", "Everything built from it (D60, step 2)") as st:
        derived = db.rows("SELECT child_table, child_id FROM synapse.derived WHERE dataset_id = %s AND item_id = %s",
                          (ds["id"], item_id))
        layer_rows = db.rows("SELECT DISTINCT l.src AS id, i.title, i.meta FROM synapse.link l JOIN synapse.item i "
                             "ON i.dataset_id = l.dataset_id AND i.id = l.src WHERE l.dataset_id = %s AND l.dst = %s "
                             "AND l.type = 'built_from' AND i.deleted_at IS NULL", (ds["id"], item_id))
        rules_from = db.rows("SELECT id, title FROM synapse.item WHERE dataset_id = %s AND kind = 'rule' AND "
                             "meta->>'made_from' = %s AND deleted_at IS NULL", (ds["id"], item_id))
        st.data.update({"derived_rows": derived, "layers": [r["title"] for r in layer_rows],
                        "rules_made_from_it": [r["title"] for r in rules_from]})
    with trace.step("dreams", "Dreaming's changes and notes that depend on it, put back and removed (D92)") as st:
        from . import dreaming

        st.data.update(dreaming.forget_item(ds["id"], item_id) if dreaming.ready() else {"skipped": True})
    with trace.step("indexes", "Passages, vectors and words deleted (D60, step 2)") as st:
        counts = db.row("SELECT count(*) AS passages, count(vec) AS vectors FROM synapse.passage "
                        "WHERE dataset_id = %s AND item_id = %s", (ds["id"], item_id)) or {}
        db.run("DELETE FROM synapse.passage WHERE dataset_id = %s AND item_id = %s", (ds["id"], item_id))
        st.data.update(counts)
    with trace.step("links", "Links in and out deleted (D60, step 2)") as st:
        links = link_rows(ds["id"], item_id)
        linked_people = [l["dst"] for l in links if l["src"] == item_id and l["dst_kind"] == "person"]
        db.run("DELETE FROM synapse.link WHERE dataset_id = %s AND (src = %s OR dst = %s)", (ds["id"], item_id, item_id))
        st.data.update({"deleted": [{"type": l["type"], "from": l["src_title"], "to": l["dst_title"],
                                     "strength": l["strength"], "origin": l["origin"]} for l in links],
                        "count": len(links)})
        if item["kind"] == "person":
            # A person is linked from every dataset of their owner, and is matched by their identifiers.
            st.data["links_from_other_datasets"] = db.run("DELETE FROM synapse.link WHERE dst = %s", (item_id,))
            st.data["identities"] = db.run("DELETE FROM synapse.identity WHERE item_id = %s", (item_id,))
        if linked_people:
            st.data["people_values"] = people.linked(ds, linked_people).get("values")
    with trace.step("readers_use", "Readers, use rows and versions deleted (D60, step 2)") as st:
        readers = db.run("DELETE FROM synapse.reader WHERE dataset_id = %s AND item_id = %s", (ds["id"], item_id))
        uses = db.run("DELETE FROM synapse.use WHERE dataset_id = %s AND item_id = %s", (ds["id"], item_id))
        versions = db.run("DELETE FROM synapse.item_version WHERE dataset_id = %s AND item_id = %s", (ds["id"], item_id))
        props = db.run("DELETE FROM synapse.topic_proposal WHERE dataset_id = %s AND item_id = %s", (ds["id"], item_id))
        words = db.run("DELETE FROM synapse.word_proposal WHERE dataset_id = %s AND item_id = %s", (ds["id"], item_id))
        db.run("DELETE FROM synapse.derived WHERE dataset_id = %s AND item_id = %s", (ds["id"], item_id))
        st.data.update({"readers": readers, "use_rows": uses, "versions": versions, "topic_proposals": props,
                        "word_proposals": words})
    with trace.step("layers", "Layer claims citing it hidden, layers rebuilt without it (D60, step 3)") as st:
        from . import layers
        hidden = []
        for layer in layer_rows:
            hidden.append(layers.hide_claims_from(ds, layer["id"], item_id))
            layers.queue_rebuild(ds, layer["id"], "an item it was built from was deleted")
        for rule in rules_from:
            hidden.append({"rule": rule["title"], "kept": True,
                           "note": "A rule is the owner's own and stays; its source is gone."})
        st.data["layers"] = hidden
    with trace.step("queries", "Stored packs and answers that held it, redacted") as st:
        packs = db.rows("SELECT id FROM synapse.query WHERE dataset_id = %s AND pack::text LIKE %s",
                        (ds["id"], f"%{item_id}%"))
        for q in packs:
            redact_query(ds["id"], q["id"], item_id)
        st.data["queries"] = len(packs)
    with trace.step("map", "The map rebuilt (D60, step 4)") as st:
        from . import mapping
        st.data.update(mapping.queue(ds, datasets.settings(ds), force=True))
    if scrub:
        with trace.step("logged_prompts", "Logged prompts redacted (D60, step 5)") as st:
            st.data.update(redact_logs(ds, item_id, {**item, "raw": "\n".join([item.get("raw") or ""] + other)}))
        with trace.step("debugger_record", "Its words taken out of the debugger's own earlier record") as st:
            st.data.update(redact_traces(ds, item, trace.id))
            if other:
                st.data["transcript"] = redact_question_traces(ds, item_id, other, trace.id)
    else:
        with trace.step("words_kept", "Its words left in the logs and records: they are still in Master elsewhere") as st:
            st.data["why"] = "moved"
    with trace.step("raw", "The raw copy deleted last; the tombstone keeps id, key and date (D60, step 6)") as st:
        db.run("UPDATE synapse.item SET raw = '', body = '', title = '', xray = NULL, xray_by = NULL, "
               "meta = %s::jsonb WHERE id = %s", (Json({"deleted": True}), item_id))
        st.data.update({"kept": {"id": item_id, "source_key": item["source_key"],
                                 "said_at": str(item.get("said_at") or "")}})
    if not scrub:
        trace.finish("done", left=0)
        return {"ok": True, "item": item_id, "trace": trace.id}
    with trace.step("check", "Every table searched for its phrases (D60, the nightly check)") as st:
        st.data.update(phrase_check(ds, phrases))
    trace.finish("done", left=st.data.get("found_total", 0))
    return {"ok": True, "item": item_id, "trace": trace.id}


def _item_lines(item: dict) -> list[str]:
    lines = [l.strip() for l in re.split(r"\n+", item.get("raw") or "") if len(l.strip()) >= 20]
    lines += [s.strip() for s in re.split(r"(?<=[.!?])\s+", item.get("raw") or "") if len(s.strip()) >= 25]
    if len(item.get("body") or "") >= 20:
        lines.append(item["body"])
    x = item.get("xray") or {}
    for c in x.get("claims") or []:
        for key in ("c", "q"):
            if len(c.get(key) or "") >= 15:
                lines.append(c[key])
    if len(x.get("gist") or "") >= 20:
        lines.append(x["gist"])
    return sorted(set(lines), key=len, reverse=True)


class _Gentle:
    """Rests a background thread for as long as it has just worked. Matching words against every record is
    pure Python and holds the GIL, so without a rest the page's event loop waits behind it for every step
    (13 October 2026: /health took 48 seconds while one file's words were looked for). On the main thread
    it never sleeps, since the event loop would only wait longer."""

    BURST = 0.05

    def __init__(self) -> None:
        self.on = threading.current_thread() is not threading.main_thread()
        self.since = time.monotonic()

    def __call__(self) -> None:
        worked = time.monotonic() - self.since
        if self.on and worked >= self.BURST:
            time.sleep(worked)
            self.since = time.monotonic()


def redact_traces(ds: dict, item: dict, keep_trace: str) -> dict:
    """The store, edit and query records showed the item's words; they go too."""
    lines = _item_lines(item)
    variants = lines + [json.dumps(l, ensure_ascii=False)[1:-1] for l in lines]
    steps = db.rows("SELECT id, data::text AS data FROM synapse.trace_step WHERE dataset_id = %s AND trace_id <> %s",
                    (ds["id"], keep_trace))
    changed = 0
    rest = _Gentle()
    for st in steps:
        rest()
        new, hits = _redact_text(st["data"], variants)
        if hits:
            try:
                json.loads(new)
            except ValueError:
                new = json.dumps({"redacted": "this step held a deleted item's words"})
            db.run("UPDATE synapse.trace_step SET data = %s::jsonb WHERE id = %s", (new, st["id"]))
            changed += 1
    answers = db.rows("SELECT id, answer::text AS answer FROM synapse.query WHERE dataset_id = %s", (ds["id"],))
    answered = 0
    for q in answers:
        rest()
        new, hits = _redact_text(q["answer"], variants)
        if hits:
            db.run("UPDATE synapse.query SET answer = %s::jsonb WHERE id = %s", (new, q["id"]))
            answered += 1
    return {"steps_redacted": changed, "answers_redacted": answered}


def redact_question_traces(ds: dict, item_id: str, texts: list[str], keep_trace: str) -> dict:
    """The words of an item's other passages (a meeting's transcript) taken out of the records of the
    questions whose pack held the item: the only records that ever show those passages."""
    lines = _item_lines({"raw": "\n".join(texts)})
    variants = lines + [json.dumps(l, ensure_ascii=False)[1:-1] for l in lines]
    steps = db.rows("SELECT s.id, s.data::text AS data FROM synapse.trace_step s JOIN synapse.query q ON "
                    "q.trace_id = s.trace_id WHERE q.dataset_id = %s AND s.trace_id <> %s AND q.pack::text LIKE %s",
                    (ds["id"], keep_trace, f"%{item_id}%"))
    changed = 0
    rest = _Gentle()
    for st in steps:
        rest()
        new, hits = _redact_text(st["data"], variants)
        if hits:
            try:
                json.loads(new)
            except ValueError:
                new = json.dumps({"redacted": "this step held a deleted item's words"})
            db.run("UPDATE synapse.trace_step SET data = %s::jsonb WHERE id = %s", (new, st["id"]))
            changed += 1
    answered = 0
    for q in db.rows("SELECT id, answer::text AS answer FROM synapse.query WHERE dataset_id = %s AND pack::text LIKE %s",
                     (ds["id"], f"%{item_id}%")):
        new, hits = _redact_text(q["answer"] or "", variants)
        if hits:
            db.run("UPDATE synapse.query SET answer = %s::jsonb WHERE id = %s", (new, q["id"]))
            answered += 1
    return {"question_steps_redacted": changed, "answers_redacted": answered}


def redact_query(ds_id: str, query_id: str, item_id: str) -> None:
    """A stored pack held the item: its lines go, from the list and from the text."""
    q = db.row("SELECT pack FROM synapse.query WHERE id = %s", (query_id,))
    pack = (q or {}).get("pack") or {}
    for part in (pack, pack.get("more") or {}):
        for entry in part.get("items") or []:
            if entry.get("id") == item_id:
                if part.get("text") and entry.get("lines"):
                    part["text"] = part["text"].replace(entry["lines"], f"[{entry.get('n')}] [deleted]")
                entry["lines"] = "[deleted]"
                entry["title"] = "[deleted]"
    db.run("UPDATE synapse.query SET pack = %s::jsonb WHERE id = %s", (Json(pack), query_id))


def _redact_text(text: str, lines: list[str]) -> tuple[str, int]:
    hits = 0
    for line in lines:
        if line and line in text:
            hits += text.count(line)
            text = text.replace(line, "[deleted]")
    return text, hits


def redact_logs(ds: dict, item_id: str, item: dict) -> dict:
    """Find every logged model request that held the item, and take its words out (D60, step 5)."""
    traces = [r["trace_id"] for r in db.rows(
        "SELECT DISTINCT trace_id FROM synapse.call WHERE dataset_id = %s AND %s::uuid = ANY(items) "
        "AND trace_id IS NOT NULL", (ds["id"], item_id))]
    subjects = [f"synapse/{ds['id']}/{t}" for t in traces]
    lines = _item_lines(item)
    if not subjects or not lines:
        return {"requests": 0, "pieces": 0, "note": "no logged request held it"}
    return _redact_requests(subjects, lines)


def _redact_requests(subjects: list[str], lines: list[str]) -> dict:
    requests = db.rows("SELECT id, system_piece, message_pieces, text FROM llm_requests WHERE subject = ANY(%s)",
                       (subjects,))
    pieces_done, hits_total = set(), 0
    rest = _Gentle()
    for r in requests:
        rest()
        new_text, hits = _redact_text(r.get("text") or "", lines)
        if hits:
            db.run("UPDATE llm_requests SET text = %s WHERE id = %s", (new_text, r["id"]))
            hits_total += hits
        for digest in list(r.get("message_pieces") or []) + [r.get("system_piece")]:
            if not digest or digest in pieces_done:
                continue
            pieces_done.add(digest)
            piece = db.row("SELECT body FROM llm_pieces WHERE hash = %s", (digest,))
            if not piece:
                continue
            body = piece["body"] if isinstance(piece["body"], str) else json.dumps(piece["body"], ensure_ascii=False)
            new_body, hits = _redact_text(body, lines + [json.dumps(l, ensure_ascii=False)[1:-1] for l in lines])
            if hits:
                hits_total += hits
                db.run("UPDATE llm_pieces SET body = %s WHERE hash = %s", (new_body, digest))
    return {"requests": len(requests), "pieces_checked": len(pieces_done), "redacted_places": hits_total}


def redact_logs_for_dataset(ds: dict) -> int:
    try:
        items = db.rows("SELECT id, raw, body, xray FROM synapse.item WHERE dataset_id = %s AND kind NOT IN "
                        "('person', 'topic')", (ds["id"],))
        lines = []
        for it in items:
            lines += [l.strip() for l in re.split(r"\n+", it.get("raw") or "") if len(l.strip()) >= 30]
        lines = sorted(set(lines), key=len, reverse=True)[:3000]
        subjects = [r["subject"] for r in db.rows("SELECT DISTINCT subject FROM llm_requests WHERE subject LIKE %s",
                                                  (f"synapse/{ds['id']}/%",))]
        if not subjects or not lines:
            return 0
        return _redact_requests(subjects, lines).get("requests", 0)
    except Exception:  # noqa: BLE001 - the dataset still goes
        log.exception("the logged prompts of a deleted dataset could not be redacted")
        return 0


def phrase_check(ds: dict, phrases: list[str]) -> dict:
    """Search every table that could hold an item's words, for each of its phrases."""
    found, total = [], 0
    places = [("synapse.item", "raw || ' ' || body || ' ' || title || ' ' || coalesce(xray::text, '')", True),
              ("synapse.passage", "text", True), ("synapse.item_version", "raw || coalesce(xray::text, '')", True),
              ("synapse.query", "pack::text || answer::text", True),
              ("synapse.trace_step", "data::text", True),
              ("llm_requests", "coalesce(text, '')", False), ("llm_pieces", "body::text", False)]
    for phrase in phrases:
        row_counts = {}
        for table, column, scoped in places:
            sql = f"SELECT count(*) FROM {table} WHERE {column} LIKE %s"
            params = [f"%{phrase}%"]
            if scoped:
                sql += " AND dataset_id = %s"
                params.append(ds["id"])
            try:
                n = int(db.value(sql, params) or 0)
            except Exception:  # noqa: BLE001
                n = -1
            if n:
                row_counts[table] = n
        total += sum(v for v in row_counts.values() if v > 0)
        shown = " ".join(phrase.split()[:4]) + " ..."
        found.append({"phrase": shown, "found_in": row_counts})
    return {"phrases": found, "found_total": total,
            "note": "Each phrase is shown by its first words only, so this record does not keep it. "
                    "Every table should say nothing. Backups keep them until they expire (Q9)."}
