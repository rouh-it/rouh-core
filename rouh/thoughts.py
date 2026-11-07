"""Thoughts: the person's own thoughts, kept in their words, listed, and found again.

Petar, 12 October 2026: "If I have random thoughts that come to my mind and I want you to remember
them reliably what feature would you use to handle that?" Rouh kept that night's as a note in Synapse
Master, which is found by search and nowhere else, and said there was no list of his thoughts; he
answered "But that is exactly what I was interested in getting solved". So:

- **A thought is its own kind of thing**, a row of `thoughts` (`models.Thought`): his words exactly as
  he said them, with only obvious dictation slips mended and never a summary in their place, a short
  title, when he said it, how it came (said aloud, typed, on Telegram, a Telegram voice note), the
  topics Rouh read in it, and whether it is open, developed or archived.
- **A line of thinking grows**: a thought can follow up an earlier one (`follows`), and the earlier
  one lists what followed it. When a new thought is close to an earlier one, `related` names it, and
  Rouh links the two when it is clearly the same line.
- **It is listed**: the Thoughts page (`thoughtspage.js`, `/thoughts`) has them newest first by month,
  with search and a topic filter, each readable whole, to edit, archive and follow up.
- **And copied into Synapse Master** as an item tagged as a thought (source `rouh-thoughts`, key
  `thought:<id>`, `meta.thought`), so synapse_query finds it and Synapse connects it to everything
  else. The row here is the thought: the copy is written from it and never read back, so nothing done
  in Synapse ever deletes or changes a thought. A copy deleted in Synapse on purpose is not made again
  (D60), and the thought stays here.

Rouh keeps one with `capture_thought` and reads, edits, archives and shows them with `thoughts`
(`tools.py`). A message that starts with "thought:" or "idea:" is kept by code before the model reads
it (`prefixed`), so such a thought is never lost to a turn that went another way.
"""
from __future__ import annotations

import contextvars
import logging
import re
import time
from datetime import datetime, timezone

from . import clock, thought_enrich

log = logging.getLogger("rouh.thoughts")

#: How a thought came, and how the page says it.
SOURCES = {"voice": "Said aloud", "typed": "Typed", "telegram": "Telegram", "voice_note": "Telegram voice note"}
STATUSES = ("open", "developed", "archived")
#: Its copy in Synapse Master (`synapse/ingest.py` keeps it out of the rules a note can make).
SOURCE = "rouh-thoughts"
#: The most characters one thought may have.
MOST = 20_000
TITLE_MOST = 120
TAGS_MOST = 6
TAG_MOST = 40
#: The same words kept again within this many seconds are the same thought: what code kept from a
#: "thought:" message, and the model keeping it again with a title and topics, are one.
SAME_WITHIN = 30 * 60

#: How the person's message in this turn came, set where it arrives (`runtime.Session`,
#: `telegram_chat`): voice, typed, telegram or voice_note.
HOW: contextvars.ContextVar[str] = contextvars.ContextVar("rouh_thought_how", default="")

#: "thought: ..." or "idea: ..." at the start of a message. Said aloud, the colon is often heard as a
#: comma, a full stop or a dash; typed, only the colon counts, so "Thought, could you..." stays a request.
_TYPED = re.compile(r"^\s*(?:thought|idea)\s*:\s*(.+)$", re.IGNORECASE | re.DOTALL)
_SPOKEN = re.compile(r"^\s*(?:thought|idea)\s*[:\-\u2013\u2014,.]\s*(.+)$", re.IGNORECASE | re.DOTALL)


class NotFound(LookupError):
    pass


# --- words -------------------------------------------------------------------------------------


def prefixed(text: str, *, spoken: bool = False) -> str:
    """The words after "thought:" or "idea:" at the start of a message, or "" when it does not start so."""
    got = (_SPOKEN if spoken else _TYPED).match(str(text or ""))
    return got.group(1).strip() if got else ""


def _words(text: str) -> str:
    """The person's words as they are: spaces tidied inside each line, the lines and paragraphs kept."""
    out: list[str] = []
    for line in str(text or "").replace("\r", "").replace("\x00", "").split("\n"):
        line = " ".join(line.split())
        if line or (out and out[-1]):
            out.append(line)
    words = "\n".join(out).strip()
    if not words:
        raise ValueError("A thought needs its words.")
    if len(words) > MOST:
        raise ValueError(f"A thought is at most {MOST} characters.")
    return words


def code_title(words: str) -> str:
    """A title when none was given: the first sentence, up to eight words."""
    first = re.split(r"(?<=[.!?])\s", " ".join(str(words or "").split()), maxsplit=1)[0]
    cut = first.split()
    title = " ".join(cut[:8]).rstrip(".,;:!?")
    # A title starts with a capital, whatever the words do; the words themselves are left as they were said.
    title = title[:1].upper() + title[1:]
    return (title + ("…" if len(cut) > 8 else ""))[:TITLE_MOST]


def _title(title: str, words: str) -> str:
    title = " ".join(str(title or "").split()).strip(" \"'“”")[:TITLE_MOST]
    return title or code_title(words)


def clean_tags(tags) -> list[str]:
    """At most six short topics, each once whatever its case."""
    if isinstance(tags, str):
        tags = tags.split(",")
    out: list[str] = []
    seen: set[str] = set()
    for t in tags or []:
        t = " ".join(str(t or "").split()).strip(" #,")[:TAG_MOST]
        if t and t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out[:TAGS_MOST]


def _same(a: str, b: str) -> bool:
    def norm(s: str) -> str:
        return " ".join(re.findall(r"\w+", s.lower()))
    return norm(a) == norm(b)


# --- whose --------------------------------------------------------------------------------------


def _mine(who):
    from .models import Thought

    return Thought.objects.filter(org_id=str(who.org_id), user_id=str(who.user_id))


def _get(who, ident):
    try:
        ident = int(str(ident).strip().lstrip("#"))
    except (TypeError, ValueError):
        raise NotFound("There is no such thought.") from None
    t = _mine(who).filter(id=ident).first()
    if t is None:
        raise NotFound(f"There is no thought {ident}.")
    return t


# --- what one is, as the page and the model read it -----------------------------------------------


def view(t, *, titles: dict | None = None, after: list | None = None) -> dict:
    """One thought, whole: what the page draws and the model is told."""
    titles = titles or {}
    follows = None
    if t.follows:
        follows = {"id": t.follows, "title": titles.get(t.follows, "")}
    return {"id": t.id, "words": t.words, "title": t.title, "said_at": t.said_at, "source": t.source,
            "source_said": SOURCES.get(t.source, t.source), "tags": list(t.tags or []), "status": t.status,
            "follows": follows, "followed_by": after or [], "chat": t.chat_id or "",
            "synapse": bool(t.synapse_item), "synced": bool(t.synapse_at and t.synapse_at >= t.updated_at),
            "made_at": t.made_at, "updated_at": t.updated_at, "archived_at": t.archived_at,
            "address": f"/thoughts/{t.id}", "enriched": thought_enrich.view(t)}


def _views(rows, every) -> list[dict]:
    for r in rows:
        # One still being enriched whose run ended without saying so is read off its run.
        if r.enrich_state in ("starting", "running"):
            try:
                thought_enrich.settle(r)
            except Exception:  # noqa: BLE001 - read again next time
                log.exception("thought %s: its enrichment could not be read off its run", r.id)
    titles = {r.id: r.title for r in every}
    after: dict[int, list] = {}
    for r in sorted(every, key=lambda r: r.said_at):
        if r.follows:
            after.setdefault(r.follows, []).append({"id": r.id, "title": r.title, "said_at": r.said_at,
                                                    "status": r.status})
    return [view(r, titles=titles, after=after.get(r.id, [])) for r in rows]


def _matches(t, words: list[str]) -> bool:
    hay = " ".join([t.title or "", t.words or "", " ".join(t.tags or [])]).lower()
    return all(w in hay for w in words)


def listing(who, *, q: str = "", tag: str = "", archived: bool = False, limit: int | None = None) -> dict:
    """Their thoughts, newest first: the archived ones only when asked for, which then are all there is.

    Returns the thoughts, every topic with how many open thoughts carry it, and the counts."""
    every = list(_mine(who).order_by("-said_at", "-id"))
    shown = [t for t in every if (t.status == "archived") == bool(archived)]
    words = [w for w in re.findall(r"\w+", str(q or "").lower()) if w]
    if words:
        shown = [t for t in shown if _matches(t, words)]
    tag = " ".join(str(tag or "").split()).lower()
    if tag:
        shown = [t for t in shown if tag in {x.lower() for x in t.tags or []}]
    if limit:
        shown = shown[:limit]
    tags: dict[str, list] = {}
    for t in every:
        if t.status == "archived":
            continue
        for x in t.tags or []:
            got = tags.setdefault(x.lower(), [x, 0])
            got[1] += 1
    return {"thoughts": _views(shown, every),
            "tags": [{"tag": name, "count": n} for name, n in sorted(tags.values(), key=lambda v: (-v[1], v[0].lower()))],
            "counts": counts_of(every)}


def counts_of(every) -> dict:
    out = {s: 0 for s in STATUSES}
    for t in every:
        out[t.status] = out.get(t.status, 0) + 1
    out["kept"] = out["open"] + out["developed"]
    return out


def counts(who) -> dict:
    return counts_of(list(_mine(who).only("status")))


def one(who, ident) -> dict:
    t = _get(who, ident)
    every = list(_mine(who))
    return _views([t], every)[0]


# --- keeping and changing -----------------------------------------------------------------------


def capture(who, words: str, *, title: str = "", tags=(), source: str = "", follows=None, chat: str = "",
            said_at: float | None = None) -> tuple[dict, bool]:
    """Keep a thought. Returns it and whether it is new: the same words kept again within half an hour
    are the same thought, given the title and topics this time brings."""
    from .models import Thought

    words = _words(words)
    tags = clean_tags(tags)
    source = source if source in SOURCES else (HOW.get() if HOW.get() in SOURCES else "typed")
    earlier = None
    if follows not in (None, "", 0):
        earlier = _get(who, follows)
        # A follow-up is on the same line of thinking: given no topics of its own, it has the earlier one's.
        tags = tags or clean_tags(earlier.tags or [])
    now = time.time()
    for t in _mine(who).filter(made_at__gte=now - SAME_WITHIN).exclude(status="archived"):
        if _same(t.words, words):
            changed = False
            if title and " ".join(title.split()) != t.title:
                t.title = _title(title, words)
                changed = True
            if tags and tags != list(t.tags or []):
                t.tags = clean_tags(list(t.tags or []) + tags)
                changed = True
            if earlier is not None and earlier.id != t.id and not t.follows:
                t.follows = earlier.id
                changed = True
            if changed:
                t.updated_at = now
                t.save()
            return one(who, t.id), False
    t = Thought.objects.create(org_id=str(who.org_id), user_id=str(who.user_id), words=words,
                               title=_title(title, words), said_at=float(said_at or now), source=source,
                               tags=tags, status="open", follows=earlier.id if earlier else None,
                               chat_id=str(chat or ""), made_at=now, updated_at=now)
    return one(who, t.id), True


def edit(who, ident, *, words=None, title=None, tags=None, status=None) -> dict:
    t = _get(who, ident)
    if words is not None:
        t.words = _words(words)
    if title is not None:
        t.title = _title(title, t.words)
    if tags is not None:
        t.tags = clean_tags(tags)
    if status is not None:
        set_status(t, status)
    t.updated_at = time.time()
    t.save()
    return one(who, t.id)


def set_status(t, status: str) -> None:
    status = str(status or "").strip().lower()
    if status not in STATUSES:
        raise ValueError("A thought is open, developed or archived.")
    if status == "archived" and t.status != "archived":
        t.archived_at = time.time()
    if status != "archived":
        t.archived_at = None
    t.status = status


def archive(who, ident, *, back: bool = False) -> dict:
    t = _get(who, ident)
    set_status(t, "open" if back else "archived")
    t.updated_at = time.time()
    t.save()
    return one(who, t.id)


def link(who, ident, follows) -> dict:
    """Make one thought a follow-up of an earlier one; `follows` empty takes the link away."""
    t = _get(who, ident)
    if follows in (None, "", 0):
        t.follows = None
    else:
        earlier = _get(who, follows)
        if earlier.id == t.id:
            raise ValueError("A thought cannot follow itself.")
        # Never a circle: the earlier one may not already follow this one, however far back.
        seen, at = set(), earlier
        while at is not None and at.follows and at.id not in seen:
            seen.add(at.id)
            if at.follows == t.id:
                raise ValueError(f"Thought {earlier.id} already follows this one.")
            at = _mine(who).filter(id=at.follows).first()
        t.follows = earlier.id
    t.updated_at = time.time()
    t.save()
    return one(who, t.id)


# --- what it is close to --------------------------------------------------------------------------

_COMMON = set("""a about above after again against all am an and any are as at be because been before being
below between both but by can could did do does doing down during each few for from further had has have
having he her here hers him his how i if in into is it its itself just like may me might more most my
myself no nor not now of off on once only or other our out over own really same she should so some such
than that the their them then there these they this those through to too under until up very was we were
what when where which while who whom why will with would you your thought idea think thinking realized
realise realize maybe something someone thing things get got make made one way time""".split())


def _terms(t) -> dict[str, str]:
    """Its words that say something, each by its root ("simulat" for simulation, simulated and simulate), with
    the word as it was first written."""
    out: dict[str, str] = {}
    for w in re.findall(r"[a-zA-Z\u0400-\u04FF][\w'-]{2,}", f"{t.title} {t.words}".lower()):
        if w not in _COMMON:
            out.setdefault(_stem(w), w)
    return out


def _stem(w: str) -> str:
    for end in ("ations", "ation", "ings", "ing", "ies", "ed", "es", "s", "ly"):
        if len(w) > len(end) + 3 and w.endswith(end):
            w = w[: -len(end)]
            break
    return w[:7]


def related(who, ident, *, limit: int = 3) -> list[dict]:
    """Earlier thoughts that share topics or several words with this one, closest first."""
    t = _get(who, ident)
    mine = _terms(t)
    tags = {x.lower() for x in t.tags or []}
    out = []
    for o in _mine(who).exclude(id=t.id).exclude(status="archived").filter(said_at__lte=t.said_at + 1):
        shared_tags = tags & {x.lower() for x in o.tags or []}
        shared = set(mine) & set(_terms(o))
        score = 2 * len(shared_tags) + len(shared)
        if (shared_tags and shared) or len(shared) >= 3:
            tag_roots = {_stem(x) for x in shared_tags}
            words = sorted(mine[r] for r in shared if r not in tag_roots)
            out.append((score, o, sorted(shared_tags), words))
    out.sort(key=lambda x: (-x[0], -x[1].said_at))
    return [{"id": o.id, "title": o.title, "said_at": o.said_at, "tags": st, "words": sw[:6],
             "follows_it": t.follows == o.id}
            for _s, o, st, sw in out[:limit]]


# --- for the model --------------------------------------------------------------------------------


def said_when(at: float, zone=None) -> str:
    from .reminders import DAY_NAMES

    when = datetime.fromtimestamp(float(at), timezone.utc)
    if zone is not None:
        when = when.astimezone(zone)
    return f"{DAY_NAMES[when.weekday()]} {when.day} {when.strftime('%B %Y')} at {when.strftime('%H:%M')}"


def line_for_model(v: dict, zone=None) -> str:
    bits = [f"thought {v['id']}: “{v['title']}”, {said_when(v['said_at'], zone)}, {v['source_said'].lower()}"]
    if v["tags"]:
        bits.append("topics " + ", ".join(v["tags"]))
    if v["status"] != "open":
        bits.append(v["status"])
    if v["follows"]:
        bits.append(f"follows thought {v['follows']['id']}")
    if v["followed_by"]:
        bits.append("followed up by " + ", ".join(f"thought {f['id']}" for f in v["followed_by"]))
    e = v.get("enriched")
    if e:
        task = f" in task {e['task']['number']}" if e.get("task") and e["task"].get("number") is not None else ""
        bits.append({"starting": "being enriched", "running": "being enriched" + task,
                     "done": "enriched version ready" + task + (f" at {e['page']}" if e.get("page") else ""),
                     "failed": "enrichment failed: " + (e.get("why") or "")}.get(e["state"], ""))
    return "; ".join(bits)


def detail_for_model(v: dict, zone=None) -> str:
    out = [line_for_model(v, zone), "Their words: " + v["words"]]
    if v["follows"]:
        out.append(f"It follows thought {v['follows']['id']}, “{v['follows']['title']}”.")
    for f in v["followed_by"]:
        out.append(f"Followed up by thought {f['id']}, “{f['title']}”, {said_when(f['said_at'], zone)}.")
    return "\n".join(out)


# --- the copy in Synapse Master -------------------------------------------------------------------


def mirror(t) -> str:
    """Write this thought into its person's Synapse Master: stored the first time, edited when its words
    or title changed, tagged as a thought either way. Returns what happened, in a word."""
    from .synapse import contacts, datasets, db, ingest
    from .synapse.db import Json

    ds = contacts.master_of(t.user_id, t.org_id)
    if ds is None or ds.get("frozen"):
        return "no master"
    key = f"thought:{t.id}"
    title = f"Thought: {t.title}"[:300]
    item = None
    if t.synapse_item:
        item = db.row("SELECT id, raw, title, source, source_key, deleted_at FROM synapse.item WHERE dataset_id = %s "
                      "AND id = %s::uuid", (ds["id"], t.synapse_item))
    if item is None:
        item = db.row("SELECT id, raw, title, source, source_key, deleted_at FROM synapse.item WHERE dataset_id = %s "
                      "AND source = %s AND source_key = %s", (ds["id"], SOURCE, key))
    if item is not None and item.get("deleted_at") is not None:
        # Deleted in Synapse on purpose: never made again there (D60). The thought itself stays.
        type(t).objects.filter(id=t.id).update(synapse_item=str(item["id"]), synapse_at=time.time())
        return "deleted in synapse"
    did, job = "same", None
    if item is None:
        me = datasets.me(ds)
        # Held until it is tagged, so the model's part reads it as a thought.
        got = ingest.store(ds, {"kind": "note", "title": title, "text": t.words, "source": SOURCE, "source_key": key,
                                "said_at": clock.utc_iso(float(t.said_at)), "readers": [me], "owner": me}, by="thoughts", hold=True)
        if not got.get("ok"):
            log.warning("thought %s could not be kept in Synapse: %s", t.id, got.get("why"))
            return "failed"
        item_id, did, job = str(got["item"]), "stored", got.get("job")
    else:
        item_id = str(item["id"])
        if item["source"] != SOURCE or item["source_key"] != key:
            db.run("UPDATE synapse.item SET source = %s, source_key = %s WHERE id = %s::uuid", (SOURCE, key, item_id))
        if (item.get("raw") or "") != t.words or (item.get("title") or "") != title:
            got = ingest.edit(ds, item_id, {"text": t.words, "title": title}, by="thoughts", hold=True)
            if not got.get("ok"):
                log.warning("thought %s could not be changed in Synapse: %s", t.id, got.get("why"))
                return "failed"
            did, job = "changed", got.get("job")
    tag = {"id": t.id, "tags": list(t.tags or []), "status": t.status, "source": t.source,
           "said": SOURCES.get(t.source, t.source), "follows": t.follows, "address": f"/thoughts/{t.id}"}
    db.run("UPDATE synapse.item SET meta = meta || %s::jsonb WHERE id = %s::uuid", (Json({"thought": tag}), item_id))
    ingest.release(job)
    if t.follows:
        earlier = type(t).objects.filter(id=t.follows).values_list("synapse_item", flat=True).first()
        if earlier:
            ingest.add_link(ds["id"], item_id, earlier, "follows_up", 1.0, origin="code", made_by="thoughts",
                            why=f"thought {t.id} follows up thought {t.follows}")
    type(t).objects.filter(id=t.id).update(synapse_item=item_id, synapse_at=time.time())
    return did


def mirror_now(ident: int) -> str:
    """`mirror` for one thought by its id, on a thread of its own; what a change calls."""
    from django.db import close_old_connections

    from .models import Thought

    close_old_connections()
    try:
        t = Thought.objects.filter(id=ident).first()
        return mirror(t) if t is not None else "gone"
    except Exception:  # noqa: BLE001 - the Master sync tries again
        log.exception("thought %s could not be copied into Synapse Master", ident)
        return "failed"


def sync_master(ds: dict) -> dict:
    """Every thought of this Master's owner whose copy is missing or older than it; the Master sync calls it."""
    from django.db.models import F, Q

    from .models import Thought

    out = {"thoughts": 0, "stored": 0, "changed": 0, "same": 0, "failed": 0, "deleted_kept_out": 0}
    rows = Thought.objects.filter(org_id=str(ds["org_id"]), user_id=str(ds["user_id"]))
    out["thoughts"] = rows.count()
    # Earliest first, so a follow-up finds the copy of what it follows.
    for t in rows.filter(Q(synapse_at__isnull=True) | Q(synapse_at__lt=F("updated_at"))).order_by("said_at"):
        try:
            did = mirror(t)
        except Exception:  # noqa: BLE001 - one never stops the others
            log.exception("thought %s could not be copied into Synapse Master", t.id)
            did = "failed"
        key = {"stored": "stored", "changed": "changed", "same": "same", "deleted in synapse": "deleted_kept_out"}
        out[key.get(did, "failed")] += 1
    return out


async def keep_prefixed(who, text: str, chat: str, *, source: str = "") -> dict | None:
    """A message starting "thought:" or "idea:" is always a thought: kept here by code, before the model
    reads it, and copied into Synapse Master. The model, told to keep it, finds it already kept and gives
    it a title and topics (`capture`). Its words are the ones after the colon. Never stops the turn."""
    import asyncio

    words = prefixed(text, spoken=source in ("voice", "voice_note") or HOW.get() == "voice")
    if not words or who is None:
        return None
    try:
        v, new = await asyncio.to_thread(lambda: capture(who, words, chat=chat, source=source))
        if new:
            # Its title and topics may still come from the model a moment later: the run waits for them.
            await thought_enrich.begin(who, v["id"])
        await asyncio.to_thread(mirror_now, v["id"])
        await tell(who)
        return v
    except Exception:  # noqa: BLE001 - the model still reads it, and keeps it
        log.exception("a message starting \"thought:\" could not be kept as a thought")
        return None


# --- every tab of theirs ----------------------------------------------------------------------------


async def tell(who) -> None:
    """Every open tab of this person's: the counts, and that the list moved."""
    import asyncio

    from . import runtime

    try:
        got = await asyncio.to_thread(counts, who)
        await runtime.push_person(who, {"type": "thoughts", **got})
    except Exception:  # noqa: BLE001 - a page reads them again when it opens
        log.exception("thoughts: the tabs could not be told")


__all__ = ["HOW", "MOST", "NotFound", "SOURCE", "SOURCES", "STATUSES", "archive", "capture", "clean_tags",
           "code_title", "counts", "detail_for_model", "said_when", "edit", "keep_prefixed", "line_for_model", "link", "listing", "mirror",
           "mirror_now", "one", "prefixed", "related", "sync_master", "tell", "view"]
