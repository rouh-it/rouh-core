"""People mentioned in an item's text, read in its X-ray call and kept as raw material.

Petar, 4 October 2026, by voice: prepare for a future feature that turns the
people an item's text mentions into person items, without building the matching
or making anyone yet. Q21 stays open: a pasted email's people sit inside its
text, and nothing here links them or makes them.

So the one X-ray call (D82, still one call per item) also returns
`people_mentioned` and `unattributed_identifiers`, code checks each quote the
way a claim's quote is checked (D10) and keeps a person whose quote fails,
flagged, and the result is stored on the item as data (`synapse.item.mentions`,
migration 0070). It is never embedded as a passage, never searched, never
resolved against the people set: no `synapse.identity` row, no person item and
no link comes from it. It is the raw material for people-from-text (Q21).

- `INSTRUCTIONS` and `SCHEMA` are the part of the X-ray call's instructions and
  structured output that asks for them (`ingest.XRAY_INSTRUCTIONS`).
- `check` turns the model's answer into what is stored, with every check result.
- `merge` joins a long document's sections' people with the whole call's.
- `score` compares stored people with an item's gold people (`synapse.item.mentions_gold`)
  for Evaluate: precision and recall by name and by identifier.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone

from . import text as tx

#: The stored shape's version, so a later change can tell old rows from new.
VERSION = 1

NOTE = ("Raw material for the future people-from-text feature (Q21). Nothing is linked, matched or made from "
        "it: no person item, no identity and no link.")

INSTRUCTIONS = """people_mentioned: every person the item's text names, one entry each, in the order they first appear. Read only the text itself: the ITEM line (kind, from, to, cc, subject) is code's and already known, so never take a person, an email, a phone or a handle from it; someone in it counts only where the text names them too, and then with only what the text says. Only individual people: never an organisation, a team or a shared mailbox on its own. The owner, {me}, counts only where the text names them explicitly (such as "Hi {me}" or a signature), never just because they receive the item. Text may be in any language, Bulgarian included: keep names exactly as written, in their own script. For each person: first_name; last_name; full_name_as_written (the fullest form of the name as it appears); name_latin (a Latin transliteration when the name is written in Cyrillic or another non-Latin script, else null); emails, phones and handles exactly as written, each only when the text makes plain it is this person's (such as "Daria, daria@x.example" or their own signature block); organisation; role_or_title; relationship_hint (a few words on how they stand to the sender or owner, such as "sender's lawyer"); is_sender_or_recipient (true when they wrote or receive the item, false when only mentioned, null when unclear); quote (a short span copied word for word from the text where the person appears); confidence that this is a real person named here (high, medium or low). Anything the text does not say is null or an empty list, never guessed.
unattributed_identifiers: every email address, phone number or handle in the text that is not plainly one person's (an address several people read, a general mailbox, a number nobody is said to own): kind (email, phone or handle), value exactly as written, quote (copied word for word, where it appears) and why, in a few words. An identifier goes in exactly one place: on its person, or here, never guessed onto someone."""

_NULLABLE = {"type": ["string", "null"]}
_LIST = {"type": "array", "items": {"type": "string"}}

PERSON = {
    "type": "object", "additionalProperties": False,
    "required": ["first_name", "last_name", "full_name_as_written", "name_latin", "emails", "phones", "handles",
                 "organisation", "role_or_title", "relationship_hint", "is_sender_or_recipient", "quote",
                 "confidence"],
    "properties": {
        "first_name": _NULLABLE, "last_name": _NULLABLE, "full_name_as_written": {"type": "string"},
        "name_latin": _NULLABLE, "emails": _LIST, "phones": _LIST, "handles": _LIST,
        "organisation": _NULLABLE, "role_or_title": _NULLABLE, "relationship_hint": _NULLABLE,
        "is_sender_or_recipient": {"type": ["boolean", "null"]}, "quote": {"type": "string"},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
    },
}

IDENTIFIER = {
    "type": "object", "additionalProperties": False, "required": ["kind", "value", "quote", "why"],
    "properties": {"kind": {"type": "string", "enum": ["email", "phone", "handle"]}, "value": {"type": "string"},
                   "quote": {"type": "string"}, "why": {"type": "string"}},
}

#: The two top-level fields the X-ray call's structured output gains.
SCHEMA = {"people_mentioned": {"type": "array", "items": PERSON},
          "unattributed_identifiers": {"type": "array", "items": IDENTIFIER}}
FIELDS = tuple(SCHEMA)


def _clean(value) -> str | None:
    if value is None:
        return None
    value = " ".join(str(value).replace(chr(0x2014), " - ").split())
    return value or None


def _strings(values) -> list[str]:
    out = []
    for v in values or []:
        v = _clean(v)
        if v and v not in out:
            out.append(v)
    return out


def _digits(phone: str) -> str:
    return re.sub(r"\D", "", phone or "")


def found_in(value: str, raw: str, kind: str = "") -> bool:
    """Whether an identifier is in the text: an address by its letters, a phone by its digits."""
    if not value:
        return False
    if kind == "phone":
        d = _digits(value)
        return len(d) >= 5 and d in _digits(raw)
    return value.strip().lower() in (raw or "").lower() or tx.quote_found(value, raw)


def check(raw: str, got: dict, *, model: str = "") -> dict:
    """What is stored: the model's people and identifiers, each quote checked by code (D10).

    A person whose quote is not in the text is kept and flagged (`quote_found` false), unlike a
    claim, because a name is still worth seeing; so is an identifier the text does not hold."""
    people, idents = [], []
    for p in got.get("people_mentioned") or []:
        if not isinstance(p, dict):
            continue
        entry = {k: _clean(p.get(k)) for k in ("first_name", "last_name", "full_name_as_written", "name_latin",
                                                 "organisation", "role_or_title", "relationship_hint", "quote")}
        entry.update({k: _strings(p.get(k)) for k in ("emails", "phones", "handles")})
        sor = p.get("is_sender_or_recipient")
        entry["is_sender_or_recipient"] = sor if isinstance(sor, bool) else None
        entry["confidence"] = p.get("confidence") if p.get("confidence") in ("high", "medium", "low") else "low"
        entry["quote_found"] = tx.quote_found(entry.get("quote") or "", raw)
        missing = [v for k, kind in (("emails", "email"), ("phones", "phone"), ("handles", "handle"))
                   for v in entry[k] if not found_in(v, raw, kind)]
        entry["identifiers_not_in_text"] = missing
        people.append(entry)
    for u in got.get("unattributed_identifiers") or []:
        if not isinstance(u, dict) or not _clean(u.get("value")):
            continue
        kind = u.get("kind") if u.get("kind") in ("email", "phone", "handle") else "handle"
        entry = {"kind": kind, "value": _clean(u.get("value")), "quote": _clean(u.get("quote")),
                 "why": _clean(u.get("why"))}
        entry["quote_found"] = tx.quote_found(entry.get("quote") or "", raw)
        entry["in_text"] = found_in(entry["value"], raw, kind)
        idents.append(entry)
    return {"v": VERSION, "model": model, "at": datetime.now(timezone.utc).isoformat(),
            "people_mentioned": people, "unattributed_identifiers": idents,
            "checks": {"people": len(people), "quotes_failed": sum(1 for p in people if not p["quote_found"]),
                       "identifiers_not_in_text": sum(len(p["identifiers_not_in_text"]) for p in people)
                       + sum(1 for u in idents if not u["in_text"]),
                       "unattributed": len(idents)},
            "note": NOTE}


def merge(parts: list[dict]) -> dict:
    """A long document's answers joined: sections first, then the whole; one entry per name."""
    people, idents, seen, seen_ids = [], [], set(), set()
    for got in parts:
        for p in got.get("people_mentioned") or []:
            key = name_key(p)
            if key and key in seen:
                continue
            seen.add(key)
            people.append(p)
        for u in got.get("unattributed_identifiers") or []:
            key = ident_key(u.get("kind") or "", u.get("value") or "")
            if key in seen_ids:
                continue
            seen_ids.add(key)
            idents.append(u)
    return {"people_mentioned": people, "unattributed_identifiers": idents}


# --- evaluation (gold people) -----------------------------------------------------------

def _fold(text: str) -> str:
    """A name for comparing: Latin letters (Cyrillic transliterated), no accents, lower case."""
    text = text or ""
    if re.search(r"[Ѐ-ӿ]", text):
        text = tx.other_alphabet(text)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    return " ".join(re.findall(r"[a-z]+", text))


def _name_parts(p: dict) -> tuple[str, str]:
    first, last = _fold(p.get("first_name") or ""), _fold(p.get("last_name") or "")
    if not first:
        whole = (_fold(p.get("name_latin") or "") or _fold(p.get("full_name_as_written") or "")
                 or _fold(p.get("name") or "")).split()
        if whole:
            first, last = whole[0], last or (whole[-1] if len(whole) > 1 else "")
    return first, last


def name_key(p: dict) -> str:
    first, last = _name_parts(p)
    return (first + " " + last).strip()


def same_person(a: dict, b: dict) -> bool:
    """The same first name, and the same last name when both have one."""
    fa, la = _name_parts(a)
    fb, lb = _name_parts(b)
    return bool(fa) and fa == fb and (not la or not lb or la == lb)


def ident_key(kind: str, value: str) -> str:
    if kind == "phone":
        d = _digits(value)
        return "phone:" + (d[-9:] if len(d) >= 9 else d)
    return f"{kind}:{(value or '').strip().lower()}"


def _idents(p: dict) -> list[str]:
    return ([ident_key("email", v) for v in p.get("emails") or []] + [ident_key("phone", v) for v in p.get("phones") or []]
            + [ident_key("handle", v) for v in p.get("handles") or []])


def score_item(gold: dict, got: dict | None) -> dict:
    """One item's extraction against its gold: names matched one to one, then identifiers.

    An identifier counts as right when it is on the right person, or unattributed when the gold
    leaves it unattributed; on the wrong person, or guessed onto someone, it is wrong and missed."""
    gold_people = gold.get("people") or []
    got = got or {}
    found = got.get("people_mentioned") or []
    pairs, used = [], set()
    for gi, g in enumerate(gold_people):
        for fi, f in enumerate(found):
            if fi not in used and same_person(g, f):
                pairs.append((gi, fi))
                used.add(fi)
                break
    gold_ids, got_ids = set(), set()
    for gi, g in enumerate(gold_people):
        gold_ids |= {(gi, k) for k in _idents(g)}
    gold_ids |= {(None, ident_key(u.get("kind") or "email", u.get("value") or "")) for u in gold.get("unattributed") or []}
    to_gold = {fi: gi for gi, fi in pairs}
    for fi, f in enumerate(found):
        owner = to_gold.get(fi, ("extra", fi))
        got_ids |= {(owner, k) for k in _idents(f)}
    got_ids |= {(None, ident_key(u.get("kind") or "email", u.get("value") or ""))
                for u in got.get("unattributed_identifiers") or []}
    right = gold_ids & got_ids
    return {"names": {"gold": len(gold_people), "found": len(found), "matched": len(pairs),
                      "missed": [g.get("name") or name_key(g) for gi, g in enumerate(gold_people)
                                 if gi not in {a for a, _ in pairs}],
                      "extra": [f.get("full_name_as_written") or name_key(f) for fi, f in enumerate(found) if fi not in used]},
            "identifiers": {"gold": len(gold_ids), "found": len(got_ids), "right": len(right),
                            "missed": sorted(k for _, k in gold_ids - got_ids),
                            "wrong": sorted(k for _, k in got_ids - gold_ids)}}


def _ratio(a: int, b: int) -> float | None:
    return round(a / b, 4) if b else None


def score(rows: list[dict]) -> dict:
    """Precision and recall by name and by identifier over every item with gold people.

    `rows` are items with `mentions_gold` and `mentions`; one whose X-ray has no people yet (made
    before 4 October 2026) is listed as not read rather than counted as all missed."""
    per, names, ids = [], {"gold": 0, "found": 0, "matched": 0}, {"gold": 0, "found": 0, "right": 0}
    for r in rows:
        if r.get("mentions") is None:
            per.append({"item": r["id"], "title": r.get("title") or "", "read": False})
            continue
        s = score_item(r.get("mentions_gold") or {}, r.get("mentions"))
        for k in names:
            names[k] += s["names"][k]
        for k in ids:
            ids[k] += s["identifiers"][k]
        per.append({"item": r["id"], "title": r.get("title") or "", "read": True, **s})
    return {"items": len(rows), "read": sum(1 for p in per if p["read"]),
            "names": {**names, "precision": _ratio(names["matched"], names["found"]),
                      "recall": _ratio(names["matched"], names["gold"])},
            "identifiers": {**ids, "precision": _ratio(ids["right"], ids["found"]),
                            "recall": _ratio(ids["right"], ids["gold"])},
            "per_item": per}
