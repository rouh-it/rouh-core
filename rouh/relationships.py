"""Relationships between contacts: who somebody is to another contact, or to the person themselves.

The person, 17 November 2026 (INC-553, fr_20a7f3788d84), in their own words: "also we should build
relationships types between contacts. pet of, wife of, ex bf, brother, friends, coworkers, tennis buddies,
strangers, unknown.... I don't know whatever makes sense. maybe a bunch of popular ones and then custom ones
possible too. what do you think?"

So a contact can be linked to another contact, or to the person ("me"), with a named type:

- **One link, two sides.** A link is kept once (`models.ContactRelation`) with what each side is to the
  other: Sara "Wife of" Tom, and Tom "Husband of" Sara. Each contact's card lists its links in its own
  words, "Wife of: Tom" on Sara's and "Husband of: Sara" on Tom's. A link that reads the same both ways
  (friend, coworker, tennis buddy) has the same words on both sides.
- **Types ready to pick, and the person's own.** `PRESETS` are the common types, each with its other
  side ("Pet of" and "Owner of"). Where the other side depends on who they are ("Brother of" a sister or
  a brother) it is the plain word ("Sibling of"), and the person can change it. A type the person makes up
  is kept for reuse once used (`models.RelationType`), with the other side's words they gave, which are
  the same words unless they said otherwise.
- **The person themselves** is "me" at either end, so "stranger" and "unknown" are links to them
  ("Stranger to: You"), and so is "Tom is my tennis buddy". Their own contact card lists them too.
- **A pet** is a contact like any other: a contact of Rouh's own needs no address book entry.

Set on the contact card (`static/personrelations.js`, `web/relationships.py`) or in chat or by voice
(the tool `contact_relationships`). Rouh's own, never written to iCloud; the phone's own Related name
field is `rouh/related_people.py`, which is text on the card and not a link between contacts.

**Whose.** Every row by `org_id` and `user_id`, and both ends are checked to be the person's own contacts.
No model is asked.
"""
from __future__ import annotations

import logging
import time

log = logging.getLogger("rouh.relationships")

#: The person themselves, at either end of a link.
ME = "me"

#: How long a type's words may be.
MAX_LABEL = 60

#: The common types, each with what the other side is. Picked from on the card, matched in chat.
PRESETS: list[tuple[str, str]] = [
    ("Partner of", "Partner of"),
    ("Wife of", "Husband of"),
    ("Husband of", "Wife of"),
    ("Ex-partner of", "Ex-partner of"),
    ("Ex-boyfriend of", "Ex-girlfriend of"),
    ("Ex-girlfriend of", "Ex-boyfriend of"),
    ("Mother of", "Child of"),
    ("Father of", "Child of"),
    ("Parent of", "Child of"),
    ("Child of", "Parent of"),
    ("Brother of", "Sibling of"),
    ("Sister of", "Sibling of"),
    ("Sibling of", "Sibling of"),
    ("Friend of", "Friend of"),
    ("Best friend of", "Best friend of"),
    ("Coworker of", "Coworker of"),
    ("Manager of", "Reports to"),
    ("Reports to", "Manager of"),
    ("Neighbour of", "Neighbour of"),
    ("Tennis buddy of", "Tennis buddy of"),
    ("Pet of", "Owner of"),
    ("Owner of", "Pet of"),
    ("Stranger to", "Stranger to"),
    ("Unknown to", "Unknown to"),
]

_PRESET = {label.lower(): inverse for label, inverse in PRESETS}

#: What the tool says it does.
DESCRIPTION = (
    "Relationships between the person's contacts, or between a contact and the person themselves (contact "
    "id \"me\"): wife of, brother of, friend of, coworker of, tennis buddy of, pet of, stranger to, or any "
    "type the person makes up. For 'Tom is my tennis buddy' (add, contact_id Tom's id, other_id me, type "
    "'Tennis buddy of'), 'Sara is Tom's wife' (add, Sara, Tom, 'Wife of'), 'who are my coworkers' (list, "
    "contact_id me, type 'coworker'), 'who is Rex's owner' (list, contact_id Rex), and to change or take one "
    "off (change or remove, with relationship_id from list). type is what contact_id is to other_id; the "
    "other side's words come by themselves for the common types (Wife of / Husband of, Pet of / Owner of) "
    "and are the same words otherwise, unless other_type is given. Find ids with search_contacts first. "
    "Each link shows on both contacts' cards, worded from each side. Only the person's own word sets one.")

SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["add", "change", "remove", "list"]},
        "contact_id": {"type": "string",
                       "description": "The contact (from search_contacts), or \"me\" for the person."},
        "other_id": {"type": "string", "description": "add: the other contact, or \"me\"."},
        "type": {"type": "string",
                 "description": "add/change: what contact_id is to other_id, such as 'Wife of' or 'Tennis "
                                "buddy of'. list: only the links of this type (what the other party is)."},
        "other_type": {"type": "string",
                       "description": "add/change: what other_id is to contact_id, when it differs and is not "
                                      "a common type's own other side."},
        "relationship_id": {"type": "integer", "description": "change/remove: the link's number, from list."},
    },
    "required": ["action"],
}


# --- words ---------------------------------------------------------------------------------------------


def clean(label) -> str:
    """A type's words as kept: one space between words, at most `MAX_LABEL` long, a capital first."""
    said = " ".join(str(label or "").split())[:MAX_LABEL].strip()
    return said[:1].upper() + said[1:] if said else ""


def _key(label: str) -> str:
    """What a type is matched by: lower case, without "of"/"to" at the end or an "s" of the plural."""
    words = " ".join(str(label or "").lower().replace("-", " ").split()).split()
    if words and words[0] in ("my", "a", "an", "the"):
        words = words[1:]
    if len(words) > 1 and words[-1] in ("of", "to"):
        words = words[:-1]
    out = " ".join(words)
    for end, put in (("sses", "ss"), ("shes", "sh"), ("ches", "ch"), ("xes", "x"), ("ies", "y"), ("s", "")):
        if out.endswith(end) and not out.endswith("ss") and len(out) > 3:
            out = out[: -len(end)] + put
            break
    return out


def is_preset(label: str) -> bool:
    return clean(label).lower() in _PRESET


def _who(user_id, org_id) -> tuple[str, str]:
    user_id, org_id = str(user_id or ""), str(org_id or "")
    if not user_id or not org_id:
        raise ValueError("A relationship belongs to a person in an organisation.")
    return user_id, org_id


def types(user_id: str, org_id: str) -> list[dict]:
    """Every type there is to pick: the person's own first, the latest used first, then the common ones."""
    from .models import RelationType

    user_id, org_id = _who(user_id, org_id)
    out = [{"label": r.label, "inverse": r.inverse or r.label, "own": True}
           for r in RelationType.objects.filter(user_id=user_id, org_id=org_id).order_by("-used_at", "label")
           if r.label.lower() not in _PRESET]
    return out + [{"label": label, "inverse": inverse, "own": False} for label, inverse in PRESETS]


def inverse_of(user_id: str, org_id: str, label: str) -> str:
    """The other side's words for a type: a common type's own, else what the person gave last time, else the
    same words."""
    from .models import RelationType

    label = clean(label)
    if label.lower() in _PRESET:
        return _PRESET[label.lower()]
    got = RelationType.objects.filter(user_id=user_id, org_id=org_id, label__iexact=label).first()
    return (got.inverse or got.label) if got is not None else label


def _remember(user_id: str, org_id: str, label: str, inverse: str) -> None:
    """A type the person made up, kept for reuse, with the other side's words as they gave them."""
    from .models import RelationType

    for one, other in ((label, inverse), (inverse, label)):
        if not one or one.lower() in _PRESET:
            continue
        got = RelationType.objects.filter(user_id=user_id, org_id=org_id, label__iexact=one).first()
        if got is None:
            RelationType.objects.create(user_id=user_id, org_id=org_id, label=one,
                                        inverse="" if other == one else other, used_at=time.time())
        else:
            got.inverse = "" if other.lower() == one.lower() else other
            got.used_at = time.time()
            got.save(update_fields=["inverse", "used_at"])
        if one == inverse:
            break


# --- the people at each end --------------------------------------------------------------------------


def _me_id(user_id: str, org_id: str) -> str:
    from .people import People

    try:
        me = People().me(user_id, org_id)
    except Exception:  # noqa: BLE001 - no contact of their own is fine: "me" still is them
        me = None
    return me.id if me is not None else ""


def end(user_id: str, org_id: str, said) -> str:
    """One end of a link as kept: "me" for the person (by the word or their own contact's id), else the id of
    one of their contacts. ValueError when it is nobody of theirs."""
    from .people import People

    said = str(said or "").strip()
    if said.lower() in ("me", "myself", "self", "you"):
        return ME
    if not said:
        raise ValueError("Say which contact.")
    person = People().person(user_id, org_id, said)
    if person is None or not person.id:
        raise ValueError(f"There is no contact with the id {said}. Search for them first.")
    if person.is_me or person.id == _me_id(user_id, org_id):
        return ME
    return person.id


def _names(user_id: str, org_id: str, ids) -> dict[str, dict]:
    """{id: {"name", "organisation"}} for contacts of the person's own, in one query."""
    from .synapse import db
    from .synapse.sources import contacts

    ids = sorted({str(i) for i in ids if i and i != ME})
    if not ids:
        return {}
    ds = contacts.master_of(user_id, org_id, make=False)
    if ds is None:
        return {}
    from .people import _person

    out: dict[str, dict] = {}
    for row in db.rows("SELECT * FROM synapse.item WHERE dataset_id = %s AND kind = 'person' AND deleted_at IS NULL "
                       "AND id = ANY(%s::uuid[])", (ds["id"], ids)):
        one = _person(row)
        if one is not None:
            out[one.id] = {"name": one.name or "(no name)", "organisation": one.organisation}
    return out


def _side(row, me: str) -> dict:
    """A link as `me` (one of its ends) reads it."""
    mine = row.a == me
    return {"id": row.id, "is": row.a_is if mine else row.b_is, "other": row.b if mine else row.a,
            "other_is": row.b_is if mine else row.a_is}


def of(user_id: str, org_id: str, person_id: str) -> list[dict]:
    """Every link of one contact (or of "me"), as their card reads it: {"id", "is", "other": {"id", "name",
    "me"}, "other_is"}, in the order they were made."""
    from django.db.models import Q

    from .models import ContactRelation

    user_id, org_id = _who(user_id, org_id)
    me = end(user_id, org_id, person_id)
    rows = list(ContactRelation.objects.filter(Q(a=me) | Q(b=me), user_id=user_id, org_id=org_id)
                .order_by("created_at", "id"))
    sides = [_side(r, me) for r in rows]
    names = _names(user_id, org_id, [s["other"] for s in sides])
    out = []
    for s in sides:
        other = s["other"]
        if other == ME:
            s["other"] = {"id": ME, "name": "You", "me": True}
        elif other in names:
            s["other"] = {"id": other, "me": False, **names[other]}
        else:
            continue                    # a contact no longer there: its link is not shown
        out.append(s)
    return out


def view(user_id: str, org_id: str, person) -> dict:
    """What a contact card draws: the contact's links and the types to pick from."""
    person_id = ME if getattr(person, "is_me", False) else end(user_id, org_id, getattr(person, "id", person))
    return {"person": person_id, "rows": of(user_id, org_id, person_id), "types": types(user_id, org_id)}


# --- writing -------------------------------------------------------------------------------------------


def add(user_id: str, org_id: str, contact, other, label, other_label=None, *, by: str = "card") -> dict:
    """`contact` is `label` to `other`. The other side's words are `other_label`, else the type's own. A link
    between the same two with the same words is changed rather than made twice. Answers it as `contact`
    reads it. ValueError says what is wrong."""
    from django.db import transaction
    from django.db.models import Q

    from .models import ContactRelation

    user_id, org_id = _who(user_id, org_id)
    a, b = end(user_id, org_id, contact), end(user_id, org_id, other)
    if a == b:
        raise ValueError("A contact cannot have a relationship with themselves. Pick somebody else.")
    a_is = clean(label)
    if not a_is:
        raise ValueError("Say what kind of relationship it is: pick one or type your own.")
    b_is = clean(other_label) or inverse_of(user_id, org_id, a_is)
    now = time.time()
    with transaction.atomic():
        same = (ContactRelation.objects.select_for_update()
                .filter(user_id=user_id, org_id=org_id)
                .filter(Q(a=a, b=b, a_is__iexact=a_is) | Q(a=b, b=a, b_is__iexact=a_is)).first())
        if same is not None:
            if same.a == a:
                same.a_is, same.b_is = a_is, b_is
            else:
                same.b_is, same.a_is = a_is, b_is
            same.updated_at = now
            same.save(update_fields=["a_is", "b_is", "updated_at"])
            row = same
        else:
            row = ContactRelation.objects.create(user_id=user_id, org_id=org_id, a=a, b=b, a_is=a_is, b_is=b_is,
                                                 by=by, created_at=now, updated_at=now)
        _remember(user_id, org_id, a_is, b_is)
    return _said_row(user_id, org_id, row, a)


def change(user_id: str, org_id: str, relation_id, contact, label, other_label=None) -> dict:
    """A link's words changed, as `contact` (one of its ends) reads it. ValueError when it is not theirs."""
    from .models import ContactRelation

    user_id, org_id = _who(user_id, org_id)
    me = end(user_id, org_id, contact)
    row = _theirs(user_id, org_id, relation_id)
    if me not in (row.a, row.b):
        raise ValueError("That relationship is not one of this contact's.")
    mine = clean(label)
    if not mine:
        raise ValueError("Say what kind of relationship it is: pick one or type your own.")
    theirs = clean(other_label) or inverse_of(user_id, org_id, mine)
    if row.a == me:
        row.a_is, row.b_is = mine, theirs
    else:
        row.b_is, row.a_is = mine, theirs
    row.updated_at = time.time()
    row.save(update_fields=["a_is", "b_is", "updated_at"])
    _remember(user_id, org_id, mine, theirs)
    return _said_row(user_id, org_id, row, me)


def remove(user_id: str, org_id: str, relation_id) -> dict:
    """A link taken off both contacts. Answers it as it was, as its first contact read it."""
    user_id, org_id = _who(user_id, org_id)
    row = _theirs(user_id, org_id, relation_id)
    was = _said_row(user_id, org_id, row, row.a)
    row.delete()
    return was


def _theirs(user_id: str, org_id: str, relation_id):
    from .models import ContactRelation

    try:
        number = int(str(relation_id).strip())
    except (TypeError, ValueError):
        raise ValueError("Say which relationship, by its number.") from None
    row = ContactRelation.objects.filter(id=number, user_id=user_id, org_id=org_id).first()
    if row is None:
        raise ValueError(f"There is no relationship number {number}.")
    return row


def _said_row(user_id: str, org_id: str, row, me: str) -> dict:
    s = _side(row, me)
    names = _names(user_id, org_id, [row.a, row.b])
    name = lambda i: "you" if i == ME else (names.get(i) or {}).get("name") or "(gone)"  # noqa: E731
    s.update(contact=me, contact_name=name(me), other_name=name(s["other"]))
    return s


def sentence(s: dict) -> str:
    """A link in words, both sides: "Sara is Wife of Tom, and Tom is Husband of Sara (relationship 4)"."""
    def who(n):
        return "You" if n == "you" else n

    one = f"{who(s['contact_name'])} {'are' if s['contact_name'] == 'you' else 'is'} {s['is']} {s['other_name']}"
    if s["other_is"].lower() != s["is"].lower():
        one += (f", and {who(s['other_name'])} {'are' if s['other_name'] == 'you' else 'is'} "
                f"{s['other_is']} {s['contact_name']}")
    return one + f" (relationship {s['id']})"


# --- finding the other contact ------------------------------------------------------------------------


def find(user_id: str, org_id: str, query: str, *, skip: str = "", limit: int = 8) -> list[dict]:
    """Contacts a few words of their name or company find, for the card's picker: [{"id", "name",
    "organisation"}], those with an iCloud card first. `skip` is the contact whose card it is."""
    from .people import _person
    from .synapse import db
    from .synapse.sources import contacts

    user_id, org_id = _who(user_id, org_id)
    words = [w for w in str(query or "").lower().split() if w][:5]
    if not words:
        return []
    ds = contacts.master_of(user_id, org_id, make=False)
    if ds is None:
        return []
    where = " AND ".join(["(lower(title) LIKE %s OR lower(coalesce(meta->>'organisation', '')) LIKE %s "
                          "OR lower(coalesce(meta->'icloud'->>'organisation', '')) LIKE %s)"] * len(words))
    params: list = []
    for w in words:
        like = "%" + w.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        params += [like, like, like]
    rows = db.rows("SELECT * FROM synapse.item WHERE dataset_id = %s AND kind = 'person' AND deleted_at IS NULL "
                   f"AND {where} ORDER BY (meta ? 'icloud') DESC, title LIMIT %s", (ds["id"], *params, limit + 2))
    me = _me_id(user_id, org_id)
    out = []
    for row in rows:
        one = _person(row)
        if one is None or not one.id or one.id in (skip, me) or one.is_me:
            continue
        out.append({"id": one.id, "name": one.name or "(no name)", "organisation": one.organisation})
    return out[:limit]


# --- the tool --------------------------------------------------------------------------------------


def listing(user_id: str, org_id: str, contact: str = "", kind: str = "") -> str:
    """The links the tool reads back: one contact's (or the person's), or everybody's, of one type or all."""
    from .models import ContactRelation

    want = _key(kind)
    if contact:
        me = end(user_id, org_id, contact)
        rows = of(user_id, org_id, me)
        if want:
            rows = [r for r in rows if _key(r["other_is"]) == want or _key(r["is"]) == want]
        owner = "you" if me == ME else (_names(user_id, org_id, [me]).get(me) or {}).get("name", "them")
        whose = "your" if me == ME else owner + "'s"
        if not rows:
            return (f"No {kind.strip() + ' ' if want else ''}relationships on {whose} card yet.")
        lines = [f"{r['other']['name']} is {r['other_is']} {owner}"
                 + (f"; on {whose} card: {r['is']}: {r['other']['name']}" if r["is"] != r["other_is"] else "")
                 + f" (relationship {r['id']}, contact id {r['other']['id']})" for r in rows]
        return f"{len(rows)} on {whose} card:\n" + "\n".join("- " + line for line in lines)
    rows = list(ContactRelation.objects.filter(user_id=user_id, org_id=org_id).order_by("created_at", "id"))
    if want:
        rows = [r for r in rows if want in (_key(r.a_is), _key(r.b_is))]
    if not rows:
        return f"No {kind.strip() + ' ' if want else ''}relationships between contacts yet."
    return f"{len(rows)} relationships:\n" + "\n".join(
        "- " + sentence(_said_row(user_id, org_id, r, r.a)) for r in rows[:60])


def answer(user_id: str, org_id: str, args: dict, *, by: str = "chat") -> tuple[str, str]:
    """Everything the tool does: (what to say, the contact whose card to draw again or "")."""
    action = str(args.get("action") or "").strip().lower()
    contact = str(args.get("contact_id") or "").strip()
    try:
        if action == "list":
            return listing(user_id, org_id, contact, str(args.get("type") or "")), ""
        if action == "add":
            if not contact or not str(args.get("other_id") or "").strip():
                return "Say both contacts: contact_id and other_id (\"me\" for the person).", ""
            s = add(user_id, org_id, contact, args.get("other_id"), args.get("type"), args.get("other_type"), by=by)
            return "Kept: " + sentence(s) + ". It shows on both contacts' cards.", s["contact"]
        if action == "change":
            row = _theirs(user_id, org_id, args.get("relationship_id"))
            contact = contact or row.a
            s = change(user_id, org_id, row.id, contact, args.get("type"), args.get("other_type"))
            return "Changed: " + sentence(s) + ".", s["contact"]
        if action == "remove":
            s = remove(user_id, org_id, args.get("relationship_id"))
            return "Taken off both cards: " + sentence(s) + ".", s["contact"]
    except ValueError as e:
        return str(e), ""
    return "Say what to do: add, change, remove or list.", ""


__all__ = ["DESCRIPTION", "ME", "PRESETS", "SCHEMA", "add", "answer", "change", "clean", "end", "find",
           "inverse_of", "listing", "of", "remove", "sentence", "types", "view"]
