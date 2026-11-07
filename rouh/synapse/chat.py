"""The Synapse chat, and the tools Rouh has in it.

Petar, 4 October 2026 (fr_df883b2daae8): "I should have a chat for the entire
synapse, not for a specific dataset. When I'm in the synapse, the chat on the
left should be the usual synapse chat, and then I can fork anything I want for
different datasets, different features, or anything like that."

So each person has one Synapse chat (`general`), opened beside the lab
whatever is on the canvas, and named for Synapse rather than for a dataset.
Its tools act on the dataset open on the screen this minute, which the page
tells it (`general`), or on any of the person's datasets named in the tool's
`dataset` argument. A fork of it is Rouh's own fork (`rouh/forks.py`): it
carries the conversation above it and is laid out beside it. The first time a
fork answers it is written down with the dataset that was open then, and it
stays on that dataset whatever the screen shows later; a fork made on the
homepage follows the screen like the chat it came off. The chats each dataset
had before this (`synapse.dataset.chat_id`) keep acting on their own dataset.

In these chats, and only there, Rouh has tools that act on Synapse: add
items, make up test data, edit and delete items, ask a question and explain
the walk, change the numbers, run the evaluation set, explain why an item
was or was not found, and read any trace with where its time went. They never touch Rouh's real memory (the remember tool,
contacts, the workspace, mail), and everything they do is a trace the
debugger beside the chat shows as it happens.
"""
from __future__ import annotations

import logging
import time

from . import datasets, db, evaluate, ingest, learning, numbers, people, recall, search, text as tx, timing

log = logging.getLogger("rouh.synapse.chat")

PREFIX = "synapse_"
TITLE = "\N{BRAIN} Synapse"
_cache: dict[str, tuple[float, dict | None]] = {}


def general(who, dataset_id: str | None = None) -> str:
    """The person's one Synapse chat, made the first time it is wanted or again
    if it was deleted, with the dataset on the screen noted on it ("" for the
    homepage). `dataset_id` must already be the person's (`datasets.mine`)."""
    from .. import conversations

    org, user = str(who.org_id), str(who.user_id)
    row = db.row("SELECT chat_id FROM synapse.chat WHERE org_id = %s AND user_id = %s AND general",
                  (org, user))
    chat = row["chat_id"] if row else ""
    if chat:
        try:
            gone = conversations.store().get_chat(chat) is None
        except Exception:  # noqa: BLE001 - not known to be gone, so kept
            gone = False
        if gone:
            db.run("DELETE FROM synapse.chat WHERE chat_id = %s", (chat,))
            chat = ""
    if not chat:
        chat = conversations.new_chat(title=TITLE)
        db.run("INSERT INTO synapse.chat (chat_id, org_id, user_id, general, dataset_id) "
               "VALUES (%s, %s, %s, true, %s::uuid)", (chat, org, user, dataset_id or None))
    else:
        db.run("UPDATE synapse.chat SET dataset_id = %s::uuid WHERE chat_id = %s "
               "AND dataset_id IS DISTINCT FROM %s::uuid", (dataset_id or None, chat, dataset_id or None))
    # What every chat of the family acts on may have moved with the screen.
    _cache.clear()
    return chat


def _place(chat_id: str, depth: int = 0) -> dict | None:
    """Where a chat stands in Synapse, or None when it is no Synapse chat.

    `ds` is the dataset its tools act on (None on the homepage), `general`
    whether it is the person's one Synapse chat, `pinned` whether it keeps its
    own dataset whatever the screen shows."""
    from .. import forks

    if not chat_id or depth > forks.DEEP:
        return None
    row = db.row("SELECT * FROM synapse.chat WHERE chat_id = %s", (chat_id,))
    if row:
        place = {"chat": chat_id, "org_id": row["org_id"], "user_id": row["user_id"],
                 "general": bool(row["general"]), "pinned": False, "ds": None}
        if row["dataset_id"]:
            place["ds"] = datasets.by_id(row["dataset_id"])
            place["pinned"] = not row["general"] and place["ds"] is not None
        elif not row["general"]:
            up = _place(forks.parent_of(chat_id), depth + 1)
            place["ds"] = up["ds"] if up else None
        return place
    old = datasets.by_chat(chat_id)
    if old:
        return {"chat": chat_id, "org_id": old["org_id"], "user_id": old["user_id"],
                "general": False, "pinned": True, "ds": old}
    # A fork answering for the first time: it takes the dataset its parent is
    # on this minute and keeps it.
    up = _place(forks.parent_of(chat_id), depth + 1)
    if not up:
        return None
    ds = up["ds"]
    db.run("INSERT INTO synapse.chat (chat_id, org_id, user_id, dataset_id) VALUES (%s, %s, %s, %s::uuid) "
           "ON CONFLICT (chat_id) DO NOTHING", (chat_id, up["org_id"], up["user_id"], ds["id"] if ds else None))
    return {"chat": chat_id, "org_id": up["org_id"], "user_id": up["user_id"],
            "general": False, "pinned": ds is not None, "ds": ds}


def place_of_chat(chat_id: str) -> dict | None:
    if not chat_id:
        return None
    now = time.time()
    got = _cache.get(chat_id)
    if got and now - got[0] < 30:
        return got[1]
    try:
        place = _place(chat_id) if db.ready() else None
    except Exception:  # noqa: BLE001
        place = None
    _cache[chat_id] = (now, place)
    return place


def dataset_of_chat(chat_id: str) -> dict | None:
    place = place_of_chat(chat_id)
    return place["ds"] if place else None


def forget(chat_id: str) -> None:
    _cache.pop(chat_id, None)


def current() -> dict | None:
    """Where the chat being answered stands in Synapse, or None."""
    from ..memory import ANSWERING

    return place_of_chat(ANSWERING.get())


def _names(place: dict) -> list[str]:
    return [r["name"] for r in db.rows(
        "SELECT name FROM synapse.dataset WHERE org_id = %s AND user_id = %s ORDER BY role = 'people', created_at",
        (place["org_id"], place["user_id"]))]


def _counts(ds: dict) -> str:
    counts = db.row("SELECT count(*) FILTER (WHERE kind NOT IN ('person','topic','layer')) AS items, "
                    "count(*) FILTER (WHERE kind = 'layer') AS layers FROM synapse.item WHERE dataset_id = %s "
                    "AND deleted_at IS NULL", (ds["id"],)) or {}
    return f"{counts.get('items', 0)} items, {counts.get('layers', 0)} layers"


def master_block() -> str:
    """For every chat that is not Synapse's: what Synapse Master is and how Rouh uses it."""
    ds = master_for_turn()
    if not ds:
        return ""
    return (
        f"Synapse Master: your own memory in Synapse, the dataset \"{ds['name']}\": every task "
        "of the person's, with its state, project, the step's ask and outcome and its notes, kept in step with "
        "the tasks every ten minutes, with what is inside them (files, chats, cards), every chat, Rouh's email, every "
        "event on every calendar Rouh can read (past and future, kept in step every minute), every meeting in the "
        "meeting library with its transcript, and everyone the person knows. Use it to remember: when the person asks about past work, a task, a decision, who someone "
        "is, when they last met someone or what happened, call synapse_query with the "
        "question and read what it brings back (it answers with the memory itself, cited by number; quote it, "
        "never invent past it), or synapse_find for an item by its words. synapse_add stores something worth "
        "keeping that is no task (a fact, a decision, a note) when the person asks you to remember it there; "
        "synapse_edit and synapse_delete change or remove an item, synapse_why says why something was or was "
        "not found, synapse_trace, synapse_settings, synapse_eval and synapse_learn operate it. These tools act "
        "on Synapse Master unless given another dataset's name. Each thing in it is labelled with the person's silos "
        "(one, several or none yet); the silos, their names and what decides each are set in Settings, Silos. When the "
        "person says which silo something is in (\"that's family\"), set it with synapse_edit's silos, or "
        "update_contact_profile's for a contact, by the silo's name; a name that is no silo is said back, never made "
        "up. synapse_query and synapse_find take a silo to search first. The Synapse lab at /synapse shows every step. "
        "Every night at 02:00 one idea to make Synapse better is tried and measured; synapse_improvements lists "
        "those attempts and reads one (\"what did last night's attempt do\": attempt latest), and the lab's "
        "Improvements page at /synapse/improvements shows them. Every night at 04:00 (when its schedule is on) Synapse "
        "dreams over Master: it compares what changed with what came before, marks claims a newer item replaced and "
        "asks a later item answered (by itself, each with Undo), and keeps merges of duplicates, rules that are "
        "facts and sensitivity changes waiting for the person; synapse_dream reads a night (\"what did last night's "
        "dream do\": action read, night latest), what waits (action waiting), or runs one now (action run), and the "
        "lab's Dreams page shows each night.")


def prompt_block(chat_id: str) -> str:
    place = place_of_chat(chat_id)
    if not place:
        return master_block()
    ds = place["ds"]
    if place["general"]:
        where = ("this is the Synapse chat, the one chat for the whole of Synapse, beside the Synapse lab on the "
                 "canvas. ")
        where += (f"The dataset open on the screen now is \"{ds['name']}\" ({_counts(ds)}), and the synapse_ tools "
                  "act on it unless one is given another dataset's name. " if ds else
                  "No dataset is open: the person is on Synapse's homepage, so name the dataset in a synapse_ "
                  "tool's dataset argument. ")
    elif place["pinned"]:
        where = (f"this chat is about the Synapse dataset \"{ds['name']}\" ({_counts(ds)}), and the synapse_ "
                 "tools act on it whatever is open on the screen, unless one is given another dataset's name. ")
    else:
        where = ("this chat is a fork of the Synapse chat. " +
                 (f"The dataset open on the screen now is \"{ds['name']}\" ({_counts(ds)}), and the synapse_ tools "
                  "act on it unless one is given another dataset's name. " if ds else
                  "No dataset is open, so name the dataset in a synapse_ tool's dataset argument. "))
    names = _names(place)
    return (
        "Synapse lab: " + where +
        ("The person's datasets: " + "; ".join(f"\"{n}\"" for n in names) + ". " if names else "") +
        "Synapse is the new memory being built and tested (task 85); it is a lab, separate from your real memory. "
        "The synapse_ tools act on one dataset each: synapse_add stores items, synapse_generate makes up fictional "
        "test data, synapse_find looks items up, synapse_edit and synapse_delete change them, synapse_query asks it a "
        "question and explains the walk, synapse_why says why an item was or was not found, synapse_trace reads any "
        "past trace step by step with where its time went, synapse_settings reads "
        "and changes its numbers, synapse_eval runs or extends its evaluation set, synapse_learn applies the usage "
        "feedback, synapse_dream runs a night of dreaming on it or reads one. Never use remember, forget or "
        "list_memory for Synapse: those are Rouh's real memory. Everything "
        "these tools do appears in the debugger as it happens, so say briefly what you did and point at it there. "
        "Data you make up must be fictional: never real people's mail. No em dashes.")


#: Outside Synapse's own chats the tools act on the person's master dataset (`master.py`), and these
#: are offered there: all but synapse_generate, which makes up fictional data and so never writes
#: into the memory Rouh really uses.
OUTSIDE = ("synapse_add", "synapse_find", "synapse_edit", "synapse_delete", "synapse_query", "synapse_why",
           "synapse_settings", "synapse_eval", "synapse_trace", "synapse_learn", "synapse_improvements", "synapse_dream")
_master_seen: dict[tuple, tuple[float, dict | None]] = {}


def _who() -> tuple[str, str] | None:
    """The person this turn is for: the one speaking, or the only person when nobody is (a reminder,
    Telegram), as the rest of Rouh's tools find them."""
    from .. import tenancy

    who = tenancy.speaker()
    if who is None:
        try:
            who = tenancy.Tenancy().only_person()
        except Exception:  # noqa: BLE001
            who = None
    return (str(who.org_id), str(who.user_id)) if who else None


def master_for_turn() -> dict | None:
    """The master dataset of the person this turn is for, or None (looked up at most every 30 s)."""
    from . import master

    who = _who()
    if not who:
        return None
    seen = _master_seen.get(who)
    if seen and time.time() - seen[0] < 30:
        return seen[1]
    try:
        got = master.of(*who) if db.ready() else None
    except Exception:  # noqa: BLE001
        got = None
    _master_seen[who] = (time.time(), got)
    return got


def _place_outside() -> dict | None:
    """A place for a chat that is not Synapse's: the person, with their master dataset on it."""
    ds = master_for_turn()
    if not ds:
        return None
    return {"chat": "", "org_id": ds["org_id"], "user_id": ds["user_id"], "general": False, "pinned": True,
            "ds": ds, "outside": True}


def _ds_or_say(args=None):
    place = current() or _place_outside()
    if not place:
        return None, ("These tools work in the Synapse chat and its forks, and in every chat once the person "
                      "has a Synapse Master (manage.py synapse_master make).")
    named = " ".join(str((args or {}).get("dataset") or "").split())
    if named:
        ds = db.row("SELECT * FROM synapse.dataset WHERE org_id = %s AND user_id = %s "
                    "ORDER BY lower(name) = lower(%s) DESC, similarity(name, %s) DESC LIMIT 1",
                    (place["org_id"], place["user_id"], named, named))
        if ds and (ds["name"].lower() == named.lower() or db.value("SELECT similarity(%s, %s) >= 0.3",
                                                                    (ds["name"], named))):
            return ds, ""
        return None, f"There is no dataset called {named}. The datasets: " + "; ".join(_names(place)) + "."
    if place["ds"]:
        return place["ds"], ""
    return None, ("No dataset is open on the screen. Name one in the dataset argument; the datasets: "
                  + "; ".join(_names(place)) + ".")


def _limit():
    """The silos the reader of this turn may see, or None for no limit (`rouh/silos.py`)."""
    from .. import silos

    return silos.limit_now()


def _limited_asker(ds: dict, asked=None) -> str | None:
    """Who a question is asked as: as given (the owner when nobody is), and under the turn's silos when its
    reader is limited to some, whoever they said they were."""
    from .. import silos

    limit = _limit()
    if limit is None:
        return asked or None
    return silos.asker(limit, people.asker_id(ds, asked or None))


def _readable(ds: dict) -> tuple[str, list]:
    """The extra condition on an item looked up by id, key or title for a reader limited to some silos: the
    readers check itself (`search.readable_sql`), so nothing of another silo is found by its id either."""
    if _limit() is None:
        return "", []
    return " AND " + search.readable_sql("synapse.item"), [search.readers_for(_limited_asker(ds))]


def _find(ds: dict, ref: str) -> dict | None:
    ref = (ref or "").strip()
    if not ref:
        return None
    cond, more = _readable(ds)
    got = db.row("SELECT * FROM synapse.item WHERE dataset_id = %s AND deleted_at IS NULL AND "
                 "(id::text = %s OR id::text LIKE %s OR source_key = %s)" + cond + " LIMIT 1",
                 (ds["id"], ref, ref + "%", ref, *more))
    if got or people.UUID.match(ref):
        # An id that is not there is nothing, never whichever title looks most like an id.
        return got
    return db.row("SELECT * FROM synapse.item WHERE dataset_id = %s AND deleted_at IS NULL AND kind NOT IN ('person')"
                  + cond + " ORDER BY similarity(title, %s) DESC LIMIT 1", (ds["id"], *more, ref))


def _wait_job(job_id: int, most: float = 180.0) -> None:
    began = time.time()
    while time.time() - began < most:
        if db.value("SELECT done_at IS NOT NULL FROM synapse.job WHERE id = %s", (job_id,)):
            return
        time.sleep(1.0)


def _short(item: dict) -> str:
    # The whole id: ids are time-ordered, so their first eight characters are shared by everything stored in the
    # same minutes, and four different items of one find all read "id 01a10853".
    from .. import silos

    label = silos.names_of_keys(item.get("silos") or [])
    if item.get("kind") == "vocabulary":
        from .. import vocabulary

        meta = item.get("meta") or {}
        return (vocabulary.line({"term": meta.get("term") or item["title"], "meaning": meta.get("meaning") or "",
                                 "aliases": meta.get("aliases") or []})[2:]
                + f" (vocabulary, {vocabulary.DEFINITION}; id {item['id']}" + (f", in {label}" if label else "") + ")")
    return (f"{item['title']} ({item['kind']}, key {item['source_key']}, id {item['id']}"
            + (f", in {label}" if label else "") + ")")


def add(args, emit=None):
    ds, why = _ds_or_say(args)
    if not ds:
        return why
    items = args.get("items") or []
    if not items and args.get("text"):
        items = [args]
    out = []
    from .. import silos

    for i, it in enumerate(items[:30]):
        # A thread comes only from a source that carries one, never from the model.
        it = {k: v for k, v in it.items() if k != "thread"}
        # Its silos, as the person said them, are the item's label (and `scope` is a rule's own, meta.scope).
        label = it.pop("silos", None)
        if label:
            keys, missing = silos.parse(ds["user_id"], ds["org_id"], label)
            if missing:
                out.append(f"- not stored: {silos.unknown_said(ds['user_id'], ds['org_id'], missing)}")
                continue
            label = keys
        got = ingest.store(ds, it, by="chat", wait=i < 3)
        if not got.get("ok"):
            out.append(f"- not stored: {got.get('why')}")
            continue
        if label:
            silos.set_item(ds, got["item"], label, why="the person said so as it was stored")
        row = ingest.get_item(ds["id"], got["item"]) or {}
        links = db.value("SELECT count(*) FROM synapse.link WHERE dataset_id = %s AND (src = %s OR dst = %s)",
                         (ds["id"], got["item"], got["item"]))
        claims = len(((row.get("xray") or {}).get("claims")) or [])
        state = (f"tier {row.get('tier')}, {claims} X-ray claims, {links} links" if i < 3
                 else "stored and searchable by words; its X-ray and links are on the queue")
        out.append(f"- {_short(row)}: {state}")
    return f"Stored {len(out)} item(s) in {ds['name']}:\n" + "\n".join(out)


GEN_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["items"],
    "properties": {"items": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["kind", "title", "text", "from", "to", "days_ago", "area"],
        "properties": {"kind": {"type": "string", "enum": ["mail", "note", "doc", "event", "task"]},
                       "title": {"type": "string"}, "text": {"type": "string"}, "from": {"type": "string"},
                       "to": {"type": "array", "items": {"type": "string"}}, "days_ago": {"type": "integer"},
                       "area": {"type": "string"}}}}},
}


def generate(args, emit=None):
    from . import ai
    from datetime import datetime, timedelta, timezone

    ds, why = _ds_or_say(args)
    if not ds:
        return why
    count = max(1, min(25, int(args.get("count") or 5)))
    s = datasets.settings(ds)
    owner = people.owner_name_of(ds) or "the owner"
    got = ai.generate(model=s.helper_model, name="test_data", purpose="test_data", owner=datasets.owner_of(ds),
                      schema=GEN_SCHEMA, max_tokens=12000,
                      instructions=(f"Make up {count} fictional items for a test memory belonging to {owner}. Every "
                                    "person, company and address is invented (use .example addresses, like "
                                    "'Name Surname <name@company.example>'). Emails between people have from and to; "
                                    "notes and docs have from empty and to empty. A reply says in its words which "
                                    "earlier message it answers. Realistic, specific facts: dates, amounts, asks, "
                                    "decisions, and some doubts. Plain text, no em dashes."),
                      text=f"WHAT TO MAKE: {args.get('description') or 'a varied week of work mail'}")
    now = datetime.now(timezone.utc)
    stored = []
    for it in got.get("items") or []:
        payload = dict(it)
        payload["text"] = payload.get("text", "").replace("—", "-").replace("–", "-")
        payload["said_at"] = (now - timedelta(days=int(it.get("days_ago") or 0))).isoformat()
        if not payload.get("from"):
            payload.pop("from", None)
            payload.pop("to", None)
        r = ingest.store(ds, payload, by="chat")
        if r.get("ok"):
            stored.append(payload.get("title"))
    return (f"Made up and stored {len(stored)} fictional items in {ds['name']}; their X-rays and links are being made "
            "on the queue, which the debugger's Activity shows:\n" + "\n".join(f"- {t}" for t in stored))


#: What a find may be handed its words as. The tool's schema says `words`, and models also send `query`, `text`
#: or a list: on 6 October 2026 one sent `words` while the code read only `query`, found no words, and so listed
#: the thirty newest items of Master, Bulgarian public holidays of 2031, as if they matched "BLUF offer".
FIND_WORDS = ("words", "query", "text", "q", "search")
#: The most a find lists, and the most of an item it shows when it is asked for one by its id or key.
FIND_MOST = 30
READ_CHARS = 6000


def find_words(args: dict) -> list[str]:
    """The words a find was given, however it was given them."""
    for key in FIND_WORDS:
        got = (args or {}).get(key)
        if isinstance(got, (list, tuple)):
            got = " ".join(str(x) for x in got)
        if str(got or "").strip():
            return str(got).split()
    return []


def _for_the_turn(tool: str, ds: dict, **facts) -> None:
    """A look-up a tool of a turn of Rouh's made, for the turn's timeline and its record (`turntrace.noted_synapse`)."""
    from .. import turntrace

    trace = turntrace.current()
    if trace is None:
        return
    try:
        trace.noted_synapse(dict(facts, tool=tool, dataset=str(ds["id"]), ids=list(facts.get("ids") or [])[:100]))
    except Exception:  # noqa: BLE001 - the record is never worth the answer
        log.debug("a look-up could not be put on the turn's timeline", exc_info=True)


def find(args, emit=None):
    """Items that hold every word, in their title or text, newest first (`search.containing`); one item whole
    when the words are its id or its key; the newest only when asked for with `newest`. Never anything that
    does not hold the words: no words and no `newest` is a question back, not a list."""
    ds, why = _ds_or_say(args)
    if not ds:
        return why
    words = find_words(args)
    try:
        limit = max(1, min(FIND_MOST, int(args.get("limit") or FIND_MOST)))
    except (TypeError, ValueError):
        limit = FIND_MOST
    if not words:
        if not args.get("newest"):
            return ("No words to look for. Give synapse_find the words an item must hold (words), or newest: true "
                    "for the newest items.")
        cond, more = _readable(ds)
        first, side = _silo_order(ds, args)
        if first is None:
            return side[0]
        rows = db.rows("SELECT id, kind, title, source_key, said_at, tier, meta, silos FROM synapse.item "
                       "WHERE dataset_id = %s AND deleted_at IS NULL AND kind NOT IN ('person', 'topic', 'layer')"
                       + cond + f" ORDER BY {first}said_at DESC NULLS LAST LIMIT %s", (ds["id"], *more, *side, limit))
        return _found_lines(rows) or "The dataset is empty."
    if len(words) == 1:
        one = _item_by_ref(ds, words[0])
        if one:
            return _whole(one)
    readers = search.readers_for(_limited_asker(ds)) if _limit() is not None else None
    first, said = _first_silo(ds, args)
    if first is None:
        return said
    began = time.monotonic()
    rows = search.containing(ds["id"], words, limit=limit, readers=readers, silo_first=first)
    _for_the_turn("synapse_find", ds, words=" ".join(words)[:200], ms=int((time.monotonic() - began) * 1000),
                  count=len(rows), ids=[str(r["id"]) for r in rows])
    if not rows:
        return f"Nothing holds every one of: {' '.join(words)}."
    return _found_lines(rows)


def _first_silo(ds: dict, args: dict) -> tuple[str | None, str]:
    """The silo a find or a question puts first: `silo`, by name or key, or else `scope`, the work or personal
    of before silos, which is the silo with that key or name (`rouh/silos.py`). ("", "") for none, and
    (None, why) for a name that is no silo, which is said back rather than guessed."""
    from .. import silos

    said = args.get("silo") or args.get("scope") or ""
    if not str(said).strip() or silos._norm(said) in silos.NONE_WORDS or silos._norm(said) == "both":
        return "", ""
    got = silos.find(ds["user_id"], ds["org_id"], said)
    if got is None:
        return None, silos.unknown_said(ds["user_id"], ds["org_id"], [str(said)])
    return got.key, ""


def _silo_order(ds: dict, args: dict) -> tuple[str | None, list]:
    """An ORDER BY that puts one silo's items first, when a find was given a silo; (None, [why]) for a
    name that is no silo."""
    first, said = _first_silo(ds, args)
    if first is None:
        return None, [said]
    if not first:
        return "", []
    return "(CASE WHEN %s = ANY(silos) THEN 0 WHEN cardinality(silos) = 0 THEN 1 ELSE 2 END), ", [first]


def _found_lines(rows: list[dict]) -> str:
    return "\n".join(f"- {_short(r)}, {tx.item_date(r)}, tier {r['tier']}" for r in rows)


def _item_by_ref(ds: dict, ref: str) -> dict | None:
    """The item whose whole id or key this is, or None: never a guess by its title."""
    cond, more = _readable(ds)
    if people.UUID.match(ref):
        return db.row("SELECT * FROM synapse.item WHERE dataset_id = %s AND id = %s::uuid AND deleted_at IS NULL"
                      + cond, (ds["id"], ref, *more))
    if ":" in ref:
        return db.row("SELECT * FROM synapse.item WHERE dataset_id = %s AND source_key = %s AND deleted_at IS NULL"
                      + cond + " LIMIT 1", (ds["id"], ref, *more))
    return None


def _whole(item: dict) -> str:
    """One item, its words and all, for reading further after a find or Rouh's own recall."""
    text = str(item.get("body") or item.get("raw") or "")
    return (f"{_short(item)}, {tx.item_date(item)}, tier {item['tier']}\n" +
            (text[:READ_CHARS] + (f"\n... ({len(text) - READ_CHARS} more characters)" if len(text) > READ_CHARS else "")
             if text else "(no text)"))


def edit(args, emit=None):
    ds, why = _ds_or_say(args)
    if not ds:
        return why
    if _limit() is not None:
        return "Only the person changes what is in their memory."
    item = _find(ds, str(args.get("item") or ""))
    if not item:
        return "No item matches that."
    changes = {k: v for k, v in args.items() if k not in ("item", "thread", "dataset", "silos")
               and v not in (None, "")}
    labelled = ""
    if args.get("silos") is not None:
        # Its silos, as the person said them ("that's family"): the label alone, no new version.
        from .. import silos
        got = silos.set_item(ds, item["id"], args.get("silos"), why=str(args.get("why") or "")[:200] or "")
        if not got.get("ok"):
            return got.get("why") or "It could not be labelled."
        labelled = ((f"Put {_short(dict(item, silos=[]))} in {got['said']}" if got["silos"] else
                     f"Took {_short(dict(item, silos=[]))} out of every silo: its sources and the X-ray decide again")
                    + f" (it was in {got['was_said']})"
                    + (f"; {got['carried']} item(s) inside it follow it" if got.get("carried") else "") + ".")
        changes.pop("why", None)
        if not changes:
            return labelled
    changes.pop("why", None)
    from .. import protected
    if protected.away() and int(datasets.settings(ds).version_days or 0) < 1:
        # Nobody is watching: an edit is fine only because the old version is
        # kept (D27); a dataset that keeps none would lose it for good.
        return protected.refusal(protected.DELETION, "Editing an item whose old version is not kept")
    got = ingest.edit(ds, item["id"], changes, by="chat")
    if not got.get("ok"):
        return got.get("why") or "It could not be edited."
    if got.get("unchanged"):
        return "Nothing changed."
    from . import worker
    worker.run_job_now(got["job"])
    _wait_job(got["job"])
    steps = db.rows("SELECT name, data FROM synapse.trace_step WHERE trace_id = %s ORDER BY seq", (got["trace"],))
    said = []
    for st in steps:
        d = st.get("data") or {}
        if st["name"] == "judgement_links" and d.get("recheck"):
            said += [f"link {r['link']}: {r['verdict']}" for r in d["recheck"]]
        if st["name"] == "xray_diff":
            said.append(f"claims added {len(d.get('claims_added') or [])}, removed {len(d.get('claims_removed') or [])}")
        if st["name"] == "layers_rebuilt" and d.get("jobs"):
            said.append("layers queued to rebuild: " + ", ".join(j.get("layer", "") for j in d["jobs"] if j))
    return ((labelled + "\n") if labelled else "") + \
        f"Edited {_short(item)} (version {item['version'] + 1}).\n" + "\n".join("- " + s for s in said)


def delete(args, emit=None):
    ds, why = _ds_or_say(args)
    if not ds:
        return why
    item = _find(ds, str(args.get("item") or ""))
    if not item:
        return "No item matches that."
    got = ingest.delete(ds, item["id"], by="chat")
    steps = {st["name"]: st.get("data") or {} for st in db.rows(
        "SELECT name, data FROM synapse.trace_step WHERE trace_id = %s", (got.get("trace"),))}
    return (f"Deleted {item['title']}: {steps.get('indexes', {}).get('passages', 0)} passages, "
            f"{steps.get('links', {}).get('count', 0)} links, "
            f"{len(steps.get('layers', {}).get('layers') or [])} layers rebuilding, logged prompts redacted in "
            f"{steps.get('logged_prompts', {}).get('requests', 0)} requests; the phrase check found "
            f"{steps.get('check', {}).get('found_total', 0)} places left.")


def query(args, emit=None):
    ds, why = _ds_or_say(args)
    if not ds:
        return why
    ctx = _find(ds, str(args.get("context_item") or "")) if args.get("context_item") else None
    # In the lab a question is answered by Synapse's own answer model, which is what is being tested. In
    # Rouh's other chats the model calling the tool is the one answering: it gets the memory itself, fitted
    # to what it should be handed, and no second answer and no rewritten question, whatever it asks for. On
    # 24 October 2026 Opus passed answer: true in a chat, and three of gpt-6-luna's passes took 18.5 of the
    # question's 19.3 seconds, which it then read again (query 01a16c96).
    outside = current() is None
    answer = False if outside else (bool(args.get("answer")) if args.get("answer") is not None else True)
    first, said = _first_silo(ds, args)
    if first is None:
        return said
    override = (args.get("settings") or None) if _limit() is None else None
    understand = None
    if outside:
        understand = bool(datasets.settings(ds, override).understand_for_models)
    got = recall.run(ds, str(args.get("question") or ""), asker=_limited_asker(ds, args.get("asker") or None),
                     context_item_id=ctx["id"] if ctx else None, mode=args.get("mode") or "live",
                     by="rouh" if outside else "chat", override=override, answer=answer, silo=first,
                     understand=understand, handed=outside)
    q = db.row("SELECT * FROM synapse.query WHERE id = %s", (got["query"],))
    pack = q.get("pack") or {}
    answer = q.get("answer") or {}
    walk = q.get("walk") or {}
    from . import people
    found = [it for it in pack.get("items") or [] if it.get("kind") != "rule"]
    _for_the_turn("synapse_query", ds, question=str(args.get("question") or "")[:200], query=str(q["id"]),
                  trace=str(q["trace_id"]) if q.get("trace_id") else "", ms=q.get("ms_total"),
                  ms_pack=q.get("ms_pack"), count=len(found), ids=[str(it.get("id")) for it in found],
                  cost=float(q.get("cost_usd") or 0))
    if outside:
        text = recall.handed_text(pack)
        return (f"Query {str(q['id'])[:8]}: {len(found)} items, about {tx.handed(text):,} tokens, in "
                f"{q.get('ms_total')} ms. The memory it found, best first in each group, numbered (cite by "
                f"number). For more, ask again more narrowly, or synapse_find an item's words or its id to read "
                f"it whole:\n" + text)
    lines = [f"Query {str(q['id'])[:8]} asked as {people.name_of(q['asker'])}, {q['mode']}; pack of {len(found)} items, "
             f"{pack.get('tokens', 0)} tokens of {walk.get('budget')}; walk stopped because {walk.get('stop')}; "
             f"{walk.get('expansions')} expansions; {q.get('ms_pack')} ms to the pack, ${float(q.get('cost_usd') or 0):.4f}.",
             "Pack, best first in each group:"]
    for it in found[:15]:
        lines.append(f"[{it['n']}] {it['title']} (score {it['score']}, via {it.get('route') or it.get('group')})")
    lines.append("Answer: " + (answer.get("text") or "(none)"))
    lines.append("Used: " + (", ".join(f"[{u['n']}] {u['title']}" for u in answer.get("used") or []) or "nothing"))
    t = timing.load(ds["id"], q["trace_id"]) if q.get("trace_id") else None
    if t:
        lines.append(f"Trace {t['id']}.")
        lines.append(timing.describe(t, header=False))
    return "\n".join(lines)


def why(args, emit=None):
    ds, say = _ds_or_say(args)
    if not ds:
        return say
    item = _find(ds, str(args.get("item") or ""))
    if not item:
        return "No item matches that."
    qid = args.get("query_id")
    # A reader limited to some silos explains only questions asked as them, never the person's own.
    mine, who = (" AND asker = %s", [_limited_asker(ds)]) if _limit() is not None else ("", [])
    if qid:
        q = db.row("SELECT id FROM synapse.query WHERE dataset_id = %s AND id::text LIKE %s" + mine +
                   " ORDER BY created_at DESC LIMIT 1", (ds["id"], str(qid) + "%", *who))
    else:
        q = db.row("SELECT id FROM synapse.query WHERE dataset_id = %s AND status = 'done'" + mine +
                   " ORDER BY created_at DESC LIMIT 1", (ds["id"], *who))
    if not q:
        return "There is no question to explain yet; ask one with synapse_query first."
    got = recall.why_item(ds, q["id"], item["id"])
    return "\n".join(f"{k}: {v}" for k, v in got.items())


def settings(args, emit=None):
    ds, why = _ds_or_say(args)
    if not ds:
        return why
    changes = dict(args.get("set") or {})
    for key in args.get("reset") or []:
        changes[key] = None
    problems = []
    if changes:
        ds, problems = datasets.tune(ds, changes)
        from .trace import Trace
        t = Trace(ds["id"], "tune", "Numbers changed from the chat", by="chat")
        with t.step("tune", "Numbers changed") as st:
            st.data.update({"changes": changes, "problems": problems})
        t.finish("done")
    cat = numbers.catalogue(ds.get("tuning") or {})
    wanted = args.get("show") or []
    rows = [c for c in cat if c["changed"] or c["key"] in wanted or c["key"] in changes]
    if not rows and not wanted:
        rows = []
    said = "\n".join(f"- {c['key']} ({c['ref']}): {c['value']} (starting value {c['start']})" for c in rows)
    return ((("Problems: " + "; ".join(problems) + "\n") if problems else "") +
            (said or "Every number is at its starting value.") +
            ("" if changes else "\nKeys: " + ", ".join(n.key for n in numbers.NUMBERS)))


def eval_tool(args, emit=None):
    ds, why = _ds_or_say(args)
    if not ds:
        return why
    action = args.get("action") or "list"
    if action == "add":
        got = evaluate.add_question(ds, str(args.get("question") or ""), gold=args.get("gold") or [],
                                    facts=args.get("facts") or [], asker=args.get("asker") or "",
                                    context=args.get("context_item") or "", forbidden=bool(args.get("forbidden")))
        return f"Added question {got['id']}."
    if action == "run":
        got = evaluate.start(ds, args.get("presets") or ["without", "with"], by="chat")
        return (f"Started evaluation run {str(got['run'])[:8]}: {' vs '.join(got['configs'])}. It runs every question "
                "under each and shows the table on the Evaluate tab as it goes.")
    if action == "results":
        ref = str(args.get("run") or "").strip()
        run = db.row("SELECT * FROM synapse.eval_run WHERE dataset_id = %s AND id::text LIKE %s "
                     "ORDER BY started_at DESC LIMIT 1", (ds["id"], ref + "%"))
        if not run:
            return f"No run {ref} in {ds['name']}." if ref else "No run yet."
        return (f"Run {run['id']} ({run['status']}), {run['label']}:\n" + _eval_summary(run.get("summary") or {})
                + "\n" + timing.eval_breakdown(run))
    qs = evaluate.questions(ds)
    return "\n".join(f"{q['id']}. {q['question']} (gold: {', '.join(q['gold_titles'])}{', must not answer' if q['forbidden'] else ''})"
                     for q in qs) or "No questions yet."


def _eval_summary(summary: dict) -> str:
    if not summary:
        return "Still running; no summary yet."
    lines = []
    for label, m in summary.items():
        failed = [g for g, ok in (m.get("gates") or {}).items() if not ok]
        def v(key):
            return "-" if m.get(key) is None else m[key]
        bits = [f"{v('questions')} questions", f"recall {v('recall')}", f"citation {v('citation')}",
                f"answer {v('answer')}", f"median {v('median_ms')} ms", f"p95 {v('p95_ms')} ms",
                f"{timing.money(m.get('cost'))} a question", f"leaks {m.get('leaks')}", f"privacy {m.get('privacy')}",
                f"errors {m.get('errors')}"]
        if m.get("recall_points_vs_first") is not None:
            bits.append(f"recall {m['recall_points_vs_first']:+} points vs the first")
        if "decision_gate" in m:
            bits.append("decision gate " + ("passed" if m["decision_gate"] else "not passed"))
        bits.append("gates failed: " + (", ".join(failed) if failed else "none"))
        lines.append(f"{label}: " + "; ".join(bits) + ".")
    return "\n".join(lines)


def _trace_of(ds: dict, ref: str) -> tuple[str | None, str]:
    """The trace a reference means: 'latest question', 'latest eval', or the id (or its first characters)
    of an evaluation run, a question or a trace, in that order, so a run's id reads the run."""
    ref = " ".join((ref or "").lower().split()) or "latest question"
    if ref.startswith("latest"):
        if "eval" in ref or "run" in ref:
            got = db.value("SELECT trace_id FROM synapse.eval_run WHERE dataset_id = %s AND trace_id IS NOT NULL "
                           "ORDER BY started_at DESC LIMIT 1", (ds["id"],))
            return got, "" if got else f"{ds['name']} has no evaluation run yet."
        got = db.value("SELECT trace_id FROM synapse.query WHERE dataset_id = %s AND trace_id IS NOT NULL "
                       "ORDER BY created_at DESC LIMIT 1", (ds["id"],))
        return got, "" if got else f"{ds['name']} has no question yet."
    for table, made, own in (("eval_run", "started_at", "trace_id"), ("query", "created_at", "trace_id"),
                             ("trace", "started_at", "id")):
        rows = db.rows(f"SELECT id, {own} AS trace_id FROM synapse.{table} WHERE dataset_id = %s AND id::text LIKE %s "
                       f"AND {own} IS NOT NULL ORDER BY {made} DESC LIMIT 6", (ds["id"], ref + "%"))
        exact = [r for r in rows if str(r["id"]) == ref]
        if exact or len(rows) == 1:
            return (exact or rows)[0]["trace_id"], ""
        if rows:
            return None, (f"{ref} is the start of several {table.replace('_', ' ')} ids; give more of it: "
                          + ", ".join(str(r["id"]) for r in rows[:5]))
    return None, f"No trace, question or evaluation run {ref} in {ds['name']}."


def trace_tool(args, emit=None):
    ds, why = _ds_or_say(args)
    if not ds:
        return why
    tid, why = _trace_of(ds, str(args.get("trace") or ""))
    if not tid:
        return why
    t = timing.load(ds["id"], tid)
    if not t:
        return f"Trace {tid} is gone."
    if t.get("eval_run"):
        run = db.row("SELECT * FROM synapse.eval_run WHERE dataset_id = %s AND id = %s", (ds["id"], t["eval_run"]))
        return (f"Evaluation run {run['id']} ({run['status']}), {run['label']}.\n" + timing.describe(t) + "\n"
                + timing.eval_breakdown(run))
    q = t.get("query")
    said = ""
    if q:
        row = db.row("SELECT question, by FROM synapse.query WHERE dataset_id = %s AND id = %s", (ds["id"], q["id"]))
        said = f"Question {q['id']} ({row['by']}): {row['question']}\n"
    return said + timing.describe(t)


def learn(args, emit=None):
    ds, why = _ds_or_say(args)
    if not ds:
        return why
    got = learning.apply(ds, by="chat")
    return f"Applied learning: {len(got['changed'])} links considered.\n" + "\n".join(
        f"- {c['link']}: {c['from']} to {c['to']} ({c['why']})" for c in got["changed"][:20])


ITEM_SCHEMA = {"type": "object", "properties": {
    "text": {"type": "string", "description": "The item's raw text, unchanged."},
    "title": {"type": "string"}, "kind": {"type": "string", "enum": list(numbers.KINDS)},
    "from": {"type": "string", "description": "Sender, as 'Name <address>'."},
    "to": {"type": "array", "items": {"type": "string"}}, "cc": {"type": "array", "items": {"type": "string"}},
    "said_at": {"type": "string", "description": "ISO date when it was said."},
    "area": {"type": "string"},
    "readers": {"type": "array", "items": {"type": "string"}, "description": "First names who may see it, or everyone."},
    "sensitivity": {"type": "string", "enum": ["normal", "private", "special"]},
    "silos": {"type": "array", "items": {"type": "string"},
              "description": "The person's silos it is in, by name (Settings, Silos), only when they said which."},
    "rule_for": {"type": "array", "items": {"type": "string"}}}, "required": ["text"]}

#: The silo a find or a question puts first (`rouh/silos.py`), and the work or personal of before silos.
SILO_FIRST = {"type": "string",
              "description": "Search this one of the person's silos first, by its name (Settings, Silos: Work, "
                             "Personal, or any other they made), and the rest only after it: the silo the question "
                             "belongs to, or the one they asked for. Leave it out when no silo is clear."}
SCOPE_FIRST = {"type": "string", "enum": ["work", "personal"],
               "description": "When no silo is clear but the question is plainly work or plainly personal: that "
                              "side first, which is the Work or Personal silo."}


DATASET = {"type": "string", "description": "The name of the dataset to act on, when it is not the one this chat "
                                            "is on (the one open on the screen, or a fork's own)."}


def declare(registry) -> None:
    """Put the tools on Rouh's registry; `visible` keeps them to Synapse's chats."""
    def own(name, about, schema, fn, **kw):
        schema = dict(schema, properties=dict(schema.get("properties") or {}, dataset=DATASET))
        registry._own(name, about, schema, fn, **kw)

    own("synapse_add", "Store items in the open Synapse dataset. Each item's raw text is kept unchanged; "
        "Synapse makes its passages, embedding, X-ray and links, and the debugger shows every step.",
        {"type": "object", "properties": {"items": {"type": "array", "items": ITEM_SCHEMA}}, "required": ["items"]},
        add, area="synapse")
    own("synapse_generate", "Make up fictional test data and store it in the open Synapse dataset.",
        {"type": "object", "properties": {"description": {"type": "string"}, "count": {"type": "integer"}},
         "required": ["description"]}, generate, area="synapse")
    own("synapse_find", "Find items in the open Synapse dataset that hold every one of these words in their title or "
        "text, in any order, newest first; nothing when none does. One item's id or key as the words gives that item "
        "whole, to read it further. newest: true lists the newest items instead.",
        {"type": "object", "properties": {"words": {"type": "string", "description": "The words every item found "
                                                    "must hold, such as: BLUF offer."},
                                          "limit": {"type": "integer", "description": f"At most this many ({FIND_MOST})."},
                                          "newest": {"type": "boolean", "description": "List the newest items, "
                                                     "with no words."},
                                          "silo": SILO_FIRST, "scope": SCOPE_FIRST}}, find, area="synapse")
    own("synapse_edit", "Edit one item of the open Synapse dataset (by title, key or id): new text, title, readers or "
        "sensitivity. Synapse keeps the old version, re-checks its links and rebuilds its X-ray and layers. silos "
        "puts it in the person's silos, by name, when they say so (\"that's family\": [\"Family\"]), the whole set, "
        "and changes nothing else; an empty list takes it out of every silo; a task's silos carry everything inside it. "
        "A name that is no silo is said back, and nothing is made up.",
        {"type": "object", "properties": {"item": {"type": "string"}, "text": {"type": "string"},
                                          "title": {"type": "string"}, "readers": {"type": "array", "items": {"type": "string"}},
                                          "sensitivity": {"type": "string", "enum": ["normal", "private", "special"]},
                                          "silos": {"type": "array", "items": {"type": "string"},
                                                    "description": "The silos it is in, by name, as the person said."}},
         "required": ["item"]}, edit, area="synapse")
    own("synapse_delete", "Delete one item of the open Synapse dataset, with everything derived from it.",
        {"type": "object", "properties": {"item": {"type": "string"}}, "required": ["item"]}, delete, area="synapse")
    own("synapse_query", "Ask the open Synapse dataset a question. In Rouh's chats it hands back what memory "
        "holds on it, numbered for citing, for you to read and answer from: ask again more narrowly, or "
        "synapse_find, for more. In the Synapse chat it also explains the walk (the pack, the stop reason, "
        "where the time went step by step) and has Synapse's own model answer with citations. asker is who asks "
        "(a first name); context_item makes it a question about that item, as a mail case would; mode background "
        "is the deeper background pack.",
        {"type": "object", "properties": {"question": {"type": "string"}, "asker": {"type": "string"},
                                          "context_item": {"type": "string"}, "silo": SILO_FIRST,
                                          "scope": SCOPE_FIRST,
                                          "mode": {"type": "string", "enum": ["live", "background"]},
                                          "settings": {"type": "object", "description": "Numbers for this question only."},
                                          "answer": {"type": "boolean", "description": "In the Synapse chat only, "
                                                     "where it is on unless set off: also have Synapse's own answer "
                                                     "model answer it. Rouh's other chats always read the memory "
                                                     "themselves, so it does nothing there."}},
         "required": ["question"]}, query, area="synapse")
    own("synapse_why", "Explain why an item was or was not found by a question of the open Synapse dataset "
        "(the newest question unless query_id is given).",
        {"type": "object", "properties": {"item": {"type": "string"}, "query_id": {"type": "string"}},
         "required": ["item"]}, why, area="synapse")
    own("synapse_settings", "Read or change the open Synapse dataset's numbers (budget, decay, caps, thresholds, hub "
        "constant, reranker, decision models). set takes {key: value}; reset takes keys to put back to starting values.",
        {"type": "object", "properties": {"set": {"type": "object"}, "reset": {"type": "array", "items": {"type": "string"}},
                                          "show": {"type": "array", "items": {"type": "string"}}}},
        settings, area="synapse")
    own("synapse_eval", "The open Synapse dataset's evaluation set: list it, add a question with its gold items, run "
        "it (presets: current, without, with, background), or read the latest results, with each preset's per-step "
        "and per-call timing and each question's trace.",
        {"type": "object", "properties": {"action": {"type": "string", "enum": ["list", "add", "run", "results"]},
                                          "question": {"type": "string"}, "gold": {"type": "array", "items": {"type": "string"}},
                                          "facts": {"type": "array", "items": {"type": "string"}},
                                          "asker": {"type": "string"}, "context_item": {"type": "string"},
                                          "forbidden": {"type": "boolean"},
                                          "presets": {"type": "array", "items": {"type": "string"}},
                                          "run": {"type": "string", "description": "With results: the run's id or "
                                                  "its first characters; the latest run when left out."}}},
        eval_tool, area="synapse")
    own("synapse_trace", "Read any past trace of the open Synapse dataset step by step, with where the time went: "
        "every step's ms and status, every model, embedding, decision and database call under it (backend, model, "
        "ms, tokens, cost, run in sequence or in parallel), and the overhead no step accounts for. trace is a trace "
        "id, a question id or an evaluation run id (or the first characters of one), or 'latest question' or "
        "'latest eval'. Read only.",
        {"type": "object", "properties": {"trace": {"type": "string"}}}, trace_tool, area="synapse")
    own("synapse_learn", "Apply the usage feedback to the open Synapse dataset's link strengths (D57).",
        {"type": "object", "properties": {}}, learn, area="synapse")
    own("synapse_dream", "Dreaming, Synapse's nightly pass that compares items over time (04:00 on Master): "
        "action read (the default) reads a night, night latest or a number: what it read, what it marked replaced or "
        "closed, the duplicates, rules that are facts and sensitivity it keeps waiting, the contradictions it found, "
        "the link moves, cost and time, and every change with its reason; action waiting lists what waits for the "
        "person across nights; action run starts a night now on the backfill lane. Approve, Reject and Undo are on "
        "the lab's Dreams page.",
        {"type": "object", "properties": {"action": {"type": "string", "enum": ["read", "waiting", "run"]},
                                          "night": {"type": "string", "description": "latest, or a night's number."}}},
        dream_tool, area="synapse")
    registry._own("synapse_improvements", "The attempts to make Synapse better, one a night at 02:00 plus the ones "
                  "task 85 documented: with no attempt, the list newest first; with attempt (a number, or latest for "
                  "last night's), everything about one: the ideas considered, the one chosen and why, the hypothesis, "
                  "what changed, every measure before and after, spend and time, the conclusion, the outcome, any "
                  "decision that is ‹owner›'s, and the morning report. Read only.",
                  {"type": "object", "properties": {
                      "attempt": {"type": "string", "description": "A number, or latest for last night's."},
                      "limit": {"type": "integer", "description": "How many to list, newest first (30)."}}},
                  improvements_tool, area="synapse")


def dream_tool(args, emit=None):
    """A night of dreaming: run one now, or read the latest, a given night, or what waits (`dreaming.tool`)."""
    from . import dreaming

    ds, why = _ds_or_say(args)
    if not ds:
        return why
    if not dreaming.ready():
        return "Dreaming's tables are not in this database yet (migration 0089)."
    return dreaming.tool(ds, args or {}, by="chat")


def improvements_tool(args, emit=None):
    """The attempts to make Synapse better: the list, or one whole (`improvements.tool`)."""
    from . import improvements

    who = _who()
    if not who:
        return "Nobody is signed in for this turn, so there are no attempts to read."
    return improvements.tool(who[0], who[1], args or {})


#: All a reader limited to some of the person's silos may use: reading, kept to those silos.
LIMITED = ("synapse_find", "synapse_query", "synapse_why")


def visible(name: str) -> bool:
    """Synapse's tools: all of them in the Synapse chat, its forks and the chats datasets had before it;
    in every other chat, those of `OUTSIDE`, on the person's master dataset, once they have one. A turn
    whose reader is limited to some silos reads only (`LIMITED`)."""
    if not name.startswith(PREFIX):
        return True
    if _limit() is not None and name not in LIMITED:
        return False
    if current() is not None:
        return True
    return name in OUTSIDE and master_for_turn() is not None
