"""What each kind of item must carry: one registry, checked whenever an item is stored or edited.

Petar, 3 October 2026: one unified model. Everything Synapse knows is a
`synapse.item` with a kind, never a table per kind (D21). Every item has the
same columns: kind, owner, readers, a date (`said_at`), a title, its searchable
text (passages), a source and a source key. What one kind needs beyond that
lives in `meta`, and is listed here: the fields it must have, the ones it may
have, and what each must look like. `check` is the one place that says whether
an item's meta is good enough to keep; `ingest.store`, `ingest.edit` and
`people` call it before anything is written.

A kind that is not listed has no requirements beyond the common columns.
`person` is registered fully. `event` and `place` are registered with their
requirements only: nothing imports them yet, so the pattern is there when
something does.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

#: What every item has, whatever its kind: columns, not meta.
COMMON = ("kind", "owner", "readers", "said_at", "title", "passages", "source", "source_key")

#: Where a person came from (decision 5). Synapse never syncs anyone back anywhere.
ORIGINS = ("icloud", "synapse")


def _text(v) -> bool:
    return isinstance(v, str) and bool(v.strip())


def _text_list(v) -> bool:
    return isinstance(v, list) and all(isinstance(x, str) for x in v)


def _when(v) -> bool:
    return isinstance(v, str) and bool(re.match(r"^\d{4}-\d{2}-\d{2}", v))


def _birthday(v) -> bool:
    # A full date, or month and day only when the year is not known (vCard's "--03-12").
    return isinstance(v, str) and bool(re.match(r"^(\d{4}|-)-\d{2}-\d{2}$", v.strip()))


def _number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _coordinates(v) -> bool:
    return (isinstance(v, (list, tuple)) and len(v) == 2 and all(_number(x) for x in v)
            and -90 <= v[0] <= 90 and -180 <= v[1] <= 180)


def _dict(v) -> bool:
    return isinstance(v, dict)


def _list_of_dicts(v) -> bool:
    return isinstance(v, list) and all(isinstance(x, dict) for x in v)


def _bool(v) -> bool:
    return isinstance(v, bool)


@dataclass(frozen=True)
class Field:
    name: str
    test: object
    says: str


@dataclass(frozen=True)
class Kind:
    name: str
    about: str
    required: tuple = field(default_factory=tuple)
    optional: tuple = field(default_factory=tuple)
    #: Rules across fields, each (test on the whole meta, what it says when it fails).
    rules: tuple = field(default_factory=tuple)

    def fields(self) -> dict[str, Field]:
        return {f.name: f for f in self.required + self.optional}


def F(name, test, says) -> Field:
    return Field(name, test, says)


REGISTRY: dict[str, Kind] = {
    "person": Kind(
        "person", "A person: matched by their addresses, phone numbers and names (synapse.identity), never by name alone.",
        required=(
            F("origin", lambda v: v in ORIGINS, "where they came from: 'icloud' (a card in iCloud) or "
                                                 "'synapse' (met in an item, matching nobody)"),
            F("name", _text, "their name, as text"),
        ),
        optional=(
            F("emails", _text_list, "a list of addresses"),
            F("phones", _text_list, "a list of phone numbers"),
            F("organisation", lambda v: isinstance(v, str), "text"),
            F("birthday", _birthday, "YYYY-MM-DD, or --MM-DD when the year is not known"),
            F("relationship", lambda v: isinstance(v, str), "who they are to the owner, in the owner's words"),
            F("research", lambda v: isinstance(v, str), "what the web says about them, as Markdown"),
            F("research_confirmed", _bool, "true or false"),
            F("old", _list_of_dicts, "the old contacts they came from: [{contact_id, uid, href, etag, ...}]"),
            F("handle", lambda v: isinstance(v, str), "the short name the lab addresses them by"),
            F("known", _bool, "true when the owner marked them as known"),
            F("value", _number, "how much they matter, from 0 to 1, computed by code from their links"),
            F("value_parts", _dict, "what the value was computed from"),
            F("likely_same", _list_of_dicts, "people who are probably the same, not merged: [{id, why}]"),
            F("made_by", lambda v: isinstance(v, str), "what made the person"),
            F("made_from", lambda v: isinstance(v, str), "the item they were first met in"),
            F("made_why", lambda v: isinstance(v, str), "why they were made"),
            F("imported_at", lambda v: isinstance(v, str), "when the import last wrote them"),
            F("icloud", _dict, "their card in iCloud: {href, uid, etag, vcard, phones, emails, ...} "
                               "(synapse/contacts.py); edits of a person with one are written to iCloud"),
            F("icloud_gone", _dict, "the card they had in iCloud, gone from it"),
            F("note", lambda v: isinstance(v, str), "the note on their card"),
            F("own_emails", _text_list, "addresses Rouh knows for them that are not on their card"),
            F("relationship_at", _number, "when the relationship was written, epoch seconds"),
            F("researched_at", _number, "when the research was written, epoch seconds"),
            F("is_me", _bool, "true for the owner's own person"),
        ),
        rules=(
            (lambda m: m.get("origin") != "icloud" or bool(m.get("old") or m.get("icloud") or m.get("icloud_gone")),
             "a person from iCloud carries their card (icloud) or the old contact they came from (old)"),
        ),
    ),
    "event": Kind(
        "event", "Something that happens at a time: a meeting, a call, a trip.",
        required=(F("start", _when, "when it starts, YYYY-MM-DD or a full ISO time"),),
        optional=(
            F("end", _when, "when it ends, YYYY-MM-DD or a full ISO time"),
            F("place", lambda v: isinstance(v, str), "where, as text or a place item's id"),
            F("attendees", _text_list, "who comes: person item ids or addresses"),
        ),
        rules=((lambda m: not m.get("end") or not m.get("start") or str(m["end"]) >= str(m["start"]),
                "an event cannot end before it starts"),),
    ),
    "meeting": Kind(
        "meeting", "A meeting from the meeting library: its summary, decisions and action items as the library wrote "
                   "them, and its transcript as passages of their own (synapse/meetings.py).",
        required=(F("meeting", lambda v: isinstance(v, dict) and bool(v.get("id")),
                    "the library's own facts: {id, revision, state, participants, readers, speakers, ...}"),),
        optional=(
            F("start", _when, "when it started, a full ISO time"),
            F("end", _when, "when it ended, a full ISO time"),
            F("attendees", _text_list, "the addresses of who took part"),
        ),
    ),
    "vocabulary": Kind(
        "vocabulary", "An entry of the person's vocabulary: a word or a nickname of theirs and what they mean by "
                      "it, found when a message uses it (rouh/vocabulary.py). A meaning, never an instruction.",
        required=(F("term", _text, "the word, as text"), F("meaning", _text, "what it means, as text")),
        optional=(
            F("aliases", _text_list, "other names for the same thing, a list of text"),
            F("context", _list_of_dicts, "what it is about: [{type, id, name}], a person, task or project"),
        ),
    ),
    "place": Kind(
        "place", "A place: an office, a venue, a city.",
        required=(F("name", _text, "its name, as text"),),
        optional=(
            F("address", lambda v: isinstance(v, str), "its address, as text"),
            F("coordinates", _coordinates, "[latitude, longitude], in degrees"),
        ),
    ),
}


def kind(name: str) -> Kind | None:
    return REGISTRY.get(name)


def check(kind_name: str, meta: dict) -> list[str]:
    """What is wrong with this meta for this kind, in words; empty when it is good to keep."""
    k = REGISTRY.get(kind_name)
    if k is None:
        return []
    meta = meta or {}
    problems = []
    for f in k.required:
        if f.name not in meta or meta[f.name] in (None, "", []):
            problems.append(f"A {k.name} needs {f.name}: {f.says}.")
        elif not f.test(meta[f.name]):
            problems.append(f"A {k.name}'s {f.name} must be {f.says}; it was {meta[f.name]!r}.")
    for f in k.optional:
        if meta.get(f.name) not in (None, "", []) and not f.test(meta[f.name]):
            problems.append(f"A {k.name}'s {f.name} must be {f.says}; it was {meta[f.name]!r}.")
    for test, says in k.rules:
        try:
            ok = test(meta)
        except Exception:  # noqa: BLE001 - a rule that cannot read the meta fails
            ok = False
        if not ok:
            problems.append(f"A {k.name}: {says}.")
    return problems


def fill(kind_name: str, meta: dict, *, title: str = "", said_at=None) -> dict:
    """What code can fill in itself before checking: a person's or a place's name is its title,
    and an event typed into the lab starts when it was said."""
    meta = dict(meta or {})
    if kind_name in ("person", "place") and not meta.get("name") and title:
        meta["name"] = title
    if kind_name == "event" and not meta.get("start") and said_at is not None:
        meta["start"] = said_at.isoformat() if hasattr(said_at, "isoformat") else str(said_at)
    return meta


def catalogue() -> list[dict]:
    """The registry as the debugger shows it."""
    return [{"kind": k.name, "about": k.about, "common": list(COMMON),
             "required": [{"name": f.name, "says": f.says} for f in k.required],
             "optional": [{"name": f.name, "says": f.says} for f in k.optional],
             "rules": [says for _t, says in k.rules]} for k in REGISTRY.values()]
