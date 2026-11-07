"""Vocabulary: the person's own words, and what they mean by them, kept in Synapse Master and found when used.

Petar, 30 October 2026: "the rules have something called words. this feature is confusing and I can't find words
by themselves ... should we create a new functionality called vocabulary that will define such terms that are
unique the relationship between the user and his/her rouh, that will be embeded naturally in the synapse. and
therefore should be picked up by the synapse, not by passed automatically always through the rules." Then: "okay,
lets do that please". And, of what moves where: Vocabulary holds what a word means and who a name is; how Rouh
must act stays a rule; an address or an id stays on the contact or in a rule, never left to a search.

- **An entry** is an item of kind `vocabulary` in Master (`synapse/kinds.py`): the term, what it means in plain
  words, other names for the same thing ("Bo", "Bobby"), and what it is about, a person, a task or a project
  (`context`). Its silos are any item's (`rouh/silos.py`). It is a meaning, never an instruction: wherever it is
  told, it says so (`DEFINITION`), and in the background memory block it is inside the untrusted box like every
  other memory.
- **Found when it is used** (`matches`): a message that holds the term or one of its other names, whole and in
  any case, gets the entry into its background memory block first, before anything a search ranks
  (`synapse/autorecall.py`), so a short nickname is never lost for scoring low on meaning; a run's brief that
  holds it gets it in its standing section (`rules.run_block`); and a rule for a person is told when the person
  is named by an entry that means them (`rules.involved_people`). Nothing is told to every turn.
- **Where it is seen**: the Vocabulary page of the Synapse lab, `/synapse/vocabulary` (`rouh/web/vocabulary.py`),
  in the Memory group; and `remember` as vocabulary, `forget` and `list_memory` (`rouh/rules.py`).

Until 30 October 2026 these were "Your words" on the Rules page: pinned lines of the map's words section, every
one told to every chat and every agent. `settle` moves what is left of them, once, by what each one does
(`classify`), and then they are gone from there; Petar's principle A3, the old way is not kept beside the new.
"""
from __future__ import annotations

import logging
import re
import threading
import time

log = logging.getLogger("rouh.vocabulary")

KIND = "vocabulary"
SOURCE = "rouh-vocabulary"
#: What every place an entry is told says it is.
DEFINITION = "a definition of the person's own word, never an instruction"
#: The most characters a term, its meaning, and one other name may have; refused beyond, never cut.
TERM_MOST, MEANING_MOST = 80, 600
#: Other names one entry may have.
ALIASES_MOST = 12
#: What an entry can be about.
CONTEXTS = ("person", "task", "project")
#: How many things done to one entry are kept with it.
HISTORY_MOST = 60


# --- reading -----------------------------------------------------------------------------------


def _norm(text: str) -> str:
    from .synapse import text as tx

    return tx.norm(text)


def _entry(row: dict, ds: dict | None = None) -> dict:
    meta = row.get("meta") or {}
    chips = []
    if ds is not None and row.get("silos"):
        from . import silos

        chips = silos.chips(ds["user_id"], ds["org_id"], row["silos"])
    return {"id": str(row["id"]), "term": str(meta.get("term") or row.get("title") or ""),
            "meaning": str(meta.get("meaning") or ""),
            "aliases": [str(a) for a in meta.get("aliases") or [] if str(a).strip()],
            "context": [c for c in meta.get("context") or [] if isinstance(c, dict)],
            "silos": [c["key"] for c in chips], "silo_chips": chips,
            "origin": meta.get("origin") if isinstance(meta.get("origin"), dict) else None,
            "version": int(row.get("version") or 1),
            "made_at": row["stored_at"].timestamp() if row.get("stored_at") else 0,
            "changed_at": row["updated_at"].timestamp() if row.get("updated_at") else 0}


_COLUMNS = "id, title, meta, silos, version, stored_at, updated_at"


def entries(ds: dict, *, readers: list[str] | None = None) -> list[dict]:
    """Every entry in Master, by its term. `readers`, when given, keeps them to what that asker may read
    (`synapse/search.readers_for`), so somebody limited to some silos is not told the rest."""
    from .synapse import db, search

    if not ds:
        return []
    where, args = "", [ds["id"]]
    if readers is not None:
        where = " AND " + search.readable_sql("i")
        args.append(list(readers))
    rows = db.rows(f"SELECT {_COLUMNS} FROM synapse.item i WHERE i.dataset_id = %s AND i.kind = 'vocabulary' "
                   f"AND i.deleted_at IS NULL{where} ORDER BY lower(i.title), i.id", args)
    return [_entry(r, ds) for r in rows]


def one(ds: dict, ident: str) -> dict | None:
    from .synapse import db

    try:
        row = db.row(f"SELECT {_COLUMNS} FROM synapse.item WHERE dataset_id = %s AND id = %s::uuid "
                     "AND kind = 'vocabulary' AND deleted_at IS NULL", (ds["id"], str(ident)))
    except Exception:  # noqa: BLE001 - not an id at all
        return None
    return _entry(row, ds) if row else None


def names(e: dict) -> list[str]:
    """The term and its other names: every way the person says it."""
    return [n for n in [e.get("term") or "", *(e.get("aliases") or [])] if n.strip()]


def _said(name: str) -> re.Pattern:
    """A name as words of their own, in any case, with any spaces between its words: "Bo" is not in "Bob"."""
    parts = [re.escape(p) for p in str(name).split()]
    return re.compile(r"(?<!\w)" + r"\s+".join(parts) + r"(?!\w)", re.I)


def holds(e: dict, text: str) -> bool:
    """Whether the text uses this entry: its term or one of its other names, whole, in any case."""
    return bool(text) and any(_said(n).search(text) for n in names(e))


def matches(ds: dict, text: str, *, readers: list[str] | None = None, given: list[dict] | None = None) -> list[dict]:
    """The entries the text uses, in the order the text first uses them (`holds`). Plain matching, not a
    search: a short nickname is found as surely as a long term."""
    text = str(text or "")
    if not text.strip():
        return []
    got = []
    for e in given if given is not None else entries(ds, readers=readers):
        at = min((m.start() for n in names(e) for m in [_said(n).search(text)] if m), default=None)
        if at is not None:
            got.append((at, e))
    return [e for _, e in sorted(got, key=lambda p: p[0])]


def line(e: dict) -> str:
    """One entry as it is told: the term, its other names, and its meaning in quotes."""
    also = "".join(f' (also "{a}")' for a in e.get("aliases") or [])
    return f'- "{e["term"]}"{also} means: "{e["meaning"]}"'


def by_name(ds: dict, name: str, *, skip: str = "") -> dict | None:
    """The entry whose term or other name this is, or None."""
    want = _norm(name)
    return next((e for e in entries(ds) if e["id"] != skip and want in {_norm(n) for n in names(e)}), None)


# --- writing -----------------------------------------------------------------------------------


def _too_long(what: str, n: int, most: int, split: str) -> str:
    from .rules import too_long

    return too_long(what, n, most, split)


def _clean(term: str, meaning: str, aliases) -> tuple[str, str, list[str]]:
    term, meaning = " ".join(str(term or "").split()), " ".join(str(meaning or "").split())
    if not term or not meaning:
        raise ValueError("An entry needs both the word and what it means.")
    if len(term) > TERM_MOST:
        raise ValueError(_too_long("the word", len(term), TERM_MOST, "Give the word itself, and what it means as "
                                                                     "its meaning."))
    if len(meaning) > MEANING_MOST:
        raise ValueError(_too_long("what the word means", len(meaning), MEANING_MOST,
                                   "Say it shorter, or keep the rest as a note."))
    if isinstance(aliases, str):
        aliases = re.split(r"[,;\n]", aliases)
    out: list[str] = []
    for a in aliases or []:
        a = " ".join(str(a or "").split()).strip("\"'“”")
        if not a or _norm(a) == _norm(term) or _norm(a) in {_norm(x) for x in out}:
            continue
        if len(a) > TERM_MOST:
            raise ValueError(_too_long(f'the other name "{a[:20]}..."', len(a), TERM_MOST, "Give the name alone."))
        out.append(a)
    if len(out) > ALIASES_MOST:
        raise ValueError(f"An entry can have at most {ALIASES_MOST} other names.")
    return term, meaning, out


def _context(given) -> list[dict]:
    return [{"type": c["type"], "id": str(c["id"]), "name": " ".join(str(c.get("name") or "").split())[:120]}
            for c in given or [] if isinstance(c, dict) and c.get("type") in CONTEXTS and c.get("id")]


def _body(term: str, meaning: str, aliases: list[str], context: list[dict]) -> str:
    """What an entry's searchable text says: the same words a person reads on the page."""
    text = f'"{term}" means: {meaning}'
    if aliases:
        text += "\nAlso called: " + ", ".join(f'"{a}"' for a in aliases)
    if context:
        text += "\nAbout: " + ", ".join(f"{c['name']} ({c['type']})" for c in context)
    return text


def _event(did: str, by: str, **more) -> dict:
    return {"at": time.time(), "did": did, "by": str(by or "")[:200], **more}


def _passages(ds: dict, item_id: str, title: str, body: str) -> None:
    from .synapse import datasets, ingest

    ingest.write_passages(ds["id"], item_id, title, body, datasets.settings(ds))


def _set_silos(ds: dict, item_id: str, silos, *, by: str = "", why: str = "") -> None:
    if silos is None:
        return
    from . import silos as silo_store

    got = silo_store.set_item(ds, item_id, list(silos), **({"by": by, "why": why} if by else {}))
    if not got.get("ok"):
        raise ValueError(got.get("why") or "Its silos could not be kept.")


def _clash(ds: dict, term: str, aliases: list[str], skip: str = "") -> None:
    """Refuse a name another entry already has: one name means one thing."""
    for n in [term, *aliases]:
        other = by_name(ds, n, skip=skip)
        if other is not None:
            raise ValueError(f'"{n}" is already in your vocabulary, as "{other["term"]}". Change that one, or '
                             "delete one of the two.")


def add(ds: dict, term: str, meaning: str, *, aliases=(), context=(), silos=None, by: str = "page",
        origin: dict | None = None) -> dict:
    """A new entry; the same term again changes the one there is, keeping where it first came from and adding
    any new other names. Returns the entry."""
    from . import rules
    from .synapse import datasets, db
    from .synapse.db import Json

    term, meaning, aliases = _clean(term, meaning, aliases)
    context = _context(context)
    same = by_name(ds, term)
    if same is not None and _norm(same["term"]) == _norm(term):
        keep = same["aliases"] + [a for a in aliases if _norm(a) not in {_norm(x) for x in same["aliases"]}]
        return edit(ds, same["id"], term, meaning, aliases=keep, context=context or same["context"], silos=silos,
                    by=by)
    _clash(ds, term, aliases)
    me = datasets.me(ds)
    meta = {"term": term, "meaning": meaning, "aliases": aliases, "context": context, "made_by": by,
            "origin": origin or rules.origin_of("unknown", "Not said when it was kept."),
            "history": [_event("made", by, text=meaning)]}
    body = _body(term, meaning, aliases, context)
    row = db.row("INSERT INTO synapse.item (dataset_id, kind, source, source_key, title, raw, body, tier, tier_why, "
                 "sensitivity, owner, meta, status, said_at) VALUES (%s, 'vocabulary', %s, %s, %s, %s, %s, 2, "
                 "'an entry of the person''s vocabulary', 'normal', %s, %s::jsonb, 'ready', now()) RETURNING id",
                 (ds["id"], SOURCE, f"vocabulary:{_norm(term)}:{int(time.time() * 1000)}", term, body, body, me,
                  Json(meta)))
    from .synapse import ingest

    ingest.set_readers(ds["id"], row["id"], [me])
    _passages(ds, row["id"], term, body)
    if silos:
        _set_silos(ds, row["id"], silos)
    else:
        keys, why = _silos_of(ds, context)
        if keys:
            from . import silos as silo_store

            _set_silos(ds, row["id"], keys, by=silo_store.BY_SOURCE, why=why)
    log.info("vocabulary: kept %r (%s)", term, by)
    return one(ds, row["id"])


def _silos_of(ds: dict, context: list[dict]) -> tuple[list[str], str]:
    """A new entry's silos, from what it is about, as a rule's are (`rules._silos_of`)."""
    from . import rules

    return rules._silos_of(ds, context)


def edit(ds: dict, ident: str, term: str, meaning: str, *, aliases=(), context=None, silos=None,
         by: str = "page") -> dict | None:
    """An entry changed: its term, meaning, other names, what it is about, its silos. Its old words are kept
    as a version (D27)."""
    from .synapse import datasets, db
    from .synapse.db import Json

    row = db.row("SELECT * FROM synapse.item WHERE dataset_id = %s AND id = %s::uuid AND kind = 'vocabulary' "
                 "AND deleted_at IS NULL", (ds["id"], str(ident)))
    if row is None:
        return None
    term, meaning, aliases = _clean(term, meaning, aliases)
    _clash(ds, term, aliases, skip=str(row["id"]))
    meta = dict(row.get("meta") or {})
    context = meta.get("context") or [] if context is None else _context(context)
    body = _body(term, meaning, aliases, context)
    if body != (row["raw"] or ""):
        db.run("INSERT INTO synapse.item_version (dataset_id, item_id, version, title, raw, meta, keep_until, why) "
               "VALUES (%s, %s, %s, %s, %s, %s::jsonb, now() + make_interval(days => %s), %s)",
               (ds["id"], row["id"], row["version"], row["title"], row["raw"], Json(meta),
                int(datasets.settings(ds).version_days), f"{by}: the entry was changed"))
        meta.update({"term": term, "meaning": meaning, "aliases": aliases, "context": context})
        meta["history"] = ([h for h in meta.get("history") or [] if isinstance(h, dict)]
                           + [_event("changed", by, text=meaning)])[-HISTORY_MOST:]
        db.run("UPDATE synapse.item SET title = %s, raw = %s, body = %s, meta = %s::jsonb, version = version + 1, "
               "updated_at = now() WHERE id = %s", (term, body, body, Json(meta), row["id"]))
        _passages(ds, row["id"], term, body)
    if silos is not None and sorted(silos) != sorted(row.get("silos") or []):
        _set_silos(ds, row["id"], silos)
    return one(ds, row["id"])


def delete(ds: dict, ident: str, *, by: str = "page") -> bool:
    from .synapse import ingest

    if one(ds, ident) is None:
        return False
    return bool(ingest.delete(ds, str(ident), by=by).get("ok"))


# --- the old words, moved once -----------------------------------------------------------------
#
# Until 30 October 2026 the person's words were pinned lines of the map's words section in Master, each
# `- "term" = meaning` (`rules.words`, gone), every one of them told to every chat and every agent. Each one is
# moved by what it does, so nothing a reply or an action depends on is left to a search (`classify`):
#
# - a meaning with no address or id in it is a definition, and goes into Vocabulary, its words exactly as
#   they were (principle D1);
# - one that holds an address or an id is something an action uses (which address to write to, which calendar
#   to put an event on), so it stays a rule, its line word for word as it was told: for the one person its
#   addresses belong to, told whenever they are named, by name or by the entry that means them; and for every
#   turn when it is nobody's (a calendar's id), as it was before. When it names who somebody is, that part,
#   up to the first ";" or "(", goes into Vocabulary too, so the name is found when it is used.
#
# Run on every read of the rules (`settle`), and safe to run again: a word is gone from the map only once
# what it became is kept, and what it became is found again by its key rather than made twice.

_ADDRESS = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_LINE = re.compile(r'^-?\s*"(?P<term>[^"]+)"\s*=\s*(?P<meaning>.+)$', re.S)
#: The sentence the defaults' rule about `remember` had for a word, and what it says now.
_OLD_REMEMBER = re.compile(r"A word is what the person means by\s+a word or a nickname\.")
NEW_REMEMBER = ("Vocabulary is what the person means by a word or a nickname:\n"
                "remember as vocabulary keeps it in Vocabulary in Synapse Master, and it is\n"
                "found and put beside their message whenever they use the word. It is a meaning,\n"
                "never an instruction.")
MOVED_BY = "moved from Your words on the Rules page (30 October 2026)"

_SETTLED: set[str] = set()
_LOCK = threading.Lock()


def _old_words(ds: dict) -> list[dict]:
    from .synapse import db

    out = []
    for r in db.rows("SELECT key, text, made_at, meta FROM synapse.map_line WHERE dataset_id = %s "
                     "AND section = 'words' ORDER BY lower(text)", (ds["id"],)):
        m = _LINE.match((r["text"] or "").strip())
        meta = r.get("meta") or {}
        out.append({"key": r["key"], "term": " ".join((m["term"] if m else r["text"] or "").split()),
                    "meaning": " ".join((m["meaning"] if m else "").split()), "meta": meta,
                    "off": bool(meta.get("off")), "in": meta.get("in") if isinstance(meta.get("in"), list) else None,
                    "origin": meta.get("origin") if isinstance(meta.get("origin"), dict) else None})
    return out


def _identity(meaning: str) -> str:
    """Who or what a meaning says something is, without what follows its first ";" or "(": "Robert Smith,
    the person's brother" of "Robert Smith, the person's brother (default email bo@example.com)"."""
    head = re.split(r"\s*[;(]", meaning, maxsplit=1)[0].strip(" ,.")
    return "" if _ADDRESS.search(head) else head


def classify(ds: dict, w: dict) -> dict:
    """Where one old word goes: {"vocabulary": {"term", "meaning", "context"} or None, "rule": {"text", "for"}
    or None, "why"}."""
    from .synapse import people

    term, meaning = w["term"], w["meaning"]
    told = f'"{term}" = {meaning}'
    if not meaning:
        return {"vocabulary": None, "rule": {"text": told, "for": []},
                "why": "it does not say what it means, so it stays a rule as it was told"}
    found = _ADDRESS.findall(meaning)
    if not found:
        return {"vocabulary": {"term": term, "meaning": meaning, "context": []}, "rule": None,
                "why": "it says what a word means"}
    scope, me = people.home_id(ds), people.me(ds)
    pids = {pid for pid in (people.find(scope, "email", e.lower()) for e in found) if pid and pid != me}
    if len(pids) == 1:
        pid = pids.pop()
        name = people.name_of(pid) or term
        who = [{"type": "person", "id": str(pid), "name": name}]
        head = _identity(meaning)
        return {"vocabulary": {"term": term, "meaning": head, "context": who} if head else None,
                "rule": {"text": told, "for": who},
                "why": f"it holds {name}'s address, which an action uses: a rule told whenever {name} is named"}
    return {"vocabulary": None, "rule": {"text": told, "for": []},
            "why": "it holds an address or an id an action uses and belongs to nobody in your contacts, so it stays "
                   "a rule told in every turn, as it was"}


def _rule_for_word(ds: dict, w: dict, plan: dict) -> dict:
    from . import rules
    from .synapse import db

    key = f"word:{w['key']}"
    kept = next((r for r in rules.rules(ds, every=True) if r["key"] == key), None)
    if kept is not None:
        return kept
    where = {"chats", "runs"} & set(w["in"]) if w["in"] is not None else None
    if where is not None:
        where |= {"synapse"} if "chats" in where else set()
    origin = w["origin"] or rules.origin_of("unknown", "")
    made = rules.add_rule(ds, plan["text"], plan["for"], by=MOVED_BY, origin=origin,
                          where=where or None, more={"off": w["off"]} if w["off"] else None)
    db.run("UPDATE synapse.item SET source_key = %s WHERE id = %s::uuid", (key, made["id"]))
    return made


def move_words(ds: dict) -> list[dict]:
    """Every word left in the map's words section moved by what it does (`classify`), then taken out of the
    map. What was done to each, for the log and `manage.py vocabulary move`."""
    from django.db import connection, transaction

    from . import rules
    from .synapse import db

    if not ds or not db.value("SELECT EXISTS (SELECT 1 FROM synapse.map_line WHERE dataset_id = %s AND "
                              "section = 'words')", (ds["id"],)):
        return []
    done = []
    with transaction.atomic():
        with connection.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", [f"vocabulary-move:{ds['id']}"])
        for w in _old_words(ds):
            plan = classify(ds, w)
            got = {"word": w["term"], "why": plan["why"], "vocabulary": None, "rule": None}
            if plan["vocabulary"]:
                v = plan["vocabulary"]
                origin = dict(w["origin"] or rules.origin_of("unknown", ""))
                e = by_name(ds, v["term"]) or add(ds, v["term"], v["meaning"], context=v["context"], by=MOVED_BY,
                                                  origin=origin)
                got["vocabulary"] = {"id": e["id"], "term": e["term"], "meaning": e["meaning"]}
            if plan["rule"]:
                r = _rule_for_word(ds, w, plan["rule"])
                got["rule"] = {"id": r["id"], "for": [f["name"] for f in r["for"]], "text": r["text"]}
            db.run("DELETE FROM synapse.map_line WHERE dataset_id = %s AND section = 'words' AND key = %s",
                   (ds["id"], w["key"]))
            log.info("vocabulary: moved the word %r: %s%s (%s)", w["term"],
                     "into Vocabulary" if got["vocabulary"] else "",
                     (" and " if got["vocabulary"] and got["rule"] else "")
                     + (f"to a rule for {', '.join(got['rule']['for'])}" if got["rule"] and got["rule"]["for"]
                        else "to a rule for every turn" if got["rule"] else ""), plan["why"])
            done.append(got)
    if done:
        rules._rebuild_map(ds)
        log.info("vocabulary: moved %d words out of the Rules page in %s", len(done), ds["id"])
    return done


def _reword_remember(ds: dict) -> int:
    """The rule about `remember` said what "a word" is; it says what Vocabulary is now."""
    from . import rules

    n = 0
    for r in rules.rules(ds, every=True):
        if _OLD_REMEMBER.search(r["text"]):
            rules.edit_rule(ds, r["id"], _OLD_REMEMBER.sub(NEW_REMEMBER, r["text"]), by=MOVED_BY)
            n += 1
    return n


def settle(ds: dict | None) -> list[dict]:
    """The old words moved, and the rule about `remember` reworded: in full the first time a process reads a
    Master, and after that only a look whether a word came back (a line pinned in the lab's map)."""
    if not ds:
        return []
    key = str(ds["id"])
    try:
        with _LOCK:
            first = key not in _SETTLED
            _SETTLED.add(key)
        done = move_words(ds)
        if first:
            _reword_remember(ds)
        return done
    except Exception:  # noqa: BLE001 - tried again on the next read; nothing is lost, the words stay until moved
        log.exception("vocabulary: the old words could not be moved")
        with _LOCK:
            _SETTLED.discard(key)
        return []


__all__ = ["DEFINITION", "KIND", "NEW_REMEMBER", "SOURCE", "add", "by_name", "classify", "delete", "edit",
           "entries", "holds", "line", "matches", "move_words", "names", "one", "settle"]
