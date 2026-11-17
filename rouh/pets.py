"""Pets as contacts of their own, each linked to the people they belong to.

Asked for on 17 November 2026 (feature request fr_1b40e4fc6a09, INC-552), in ‹owner›'s words: "you
should add to maria's contact that she has a dog - Clara. should clara become a contact too? ... I
envision soon images and tagging. vet and everything in it... I feel like pet type of contact is a good
idea. it is identity and it doesn't cost us anything".

So a contact is a person or a pet. A pet is a person item of Synapse Master like any other contact (so
search_contacts finds it, show_contact shows it, and everything that hangs off a contact can hang off it
later), told apart by one field of its own, `meta.pet`:

    {"species": "dog", "owners": ["<person id>", ...], "since": <epoch seconds>}

- **species** is what kind of animal, in the person's word: dog, cat, horse, or anything else.
- **owners** are the contacts it belongs to, one or more, by their id in Synapse Master; never a pet.
  The link is kept on the pet only, and a person's pets are read from it (`of_owner`), so the two sides
  can never disagree.
- Later, without reshaping it: `vet` (a contact's id, or the clinic's details), `records` (vaccinations and
  medical notes, each dated) and `photos` go into the same dict. None of them is built yet.

A pet is Rouh's own contact and **never reaches iCloud or the phone**: it has no card, so it has no
number to ring, no address to write to and no card to pass on, and the contact card offers none of them
(`apple_contacts.profile_card`). Whose: the person's own Synapse Master, by `user_id` and `org_id`, and an
owner must be a contact in the same Master.

Made and changed three ways, all through `save`: the tool `save_pet` from a chat ("Maria has a dog called
Clara"), Add a pet on a person's contact card, and Edit on a pet's own card (`runtime.contact_note`). No
model is asked.

**Its switch** is `pet_contacts` (`rouh/switches.py`): off, no pet is made or changed, and the cards say
nothing about pets.
"""
from __future__ import annotations

import time
import uuid

SWITCH = "pet_contacts"
TITLE = "Pet contacts: a pet is a contact of its own, linked to the people it belongs to"

#: The kinds offered first; any other word is kept as said.
SPECIES = ("dog", "cat", "horse", "rabbit", "bird", "fish", "other")

MAX_NAME = 120
MAX_SPECIES = 40

DESCRIPTION = (
    "Adds a pet as a contact of its own, linked to the contact or contacts it belongs to, or changes one: "
    "for 'Maria has a dog called Clara', 'Clara is a cat', 'Clara also belongs to Ivan'. A pet is Rouh's "
    "own contact and never goes to iCloud or the phone, so it needs no yes. First find each owner with "
    "search_contacts and pass their ids in owner_ids; to change a pet, pass its id as contact_id (a search "
    "finds pets too). A contact already there that is really a pet (a card on the phone named Clara) is made "
    "one by passing its contact_id with owner_ids, rather than adding a second. The pet's card is put on the screen, saying who it belongs to, and each owner's card "
    "lists it. Only ever on the person's own words in this conversation.")

SCHEMA = {"type": "object", "properties": {
    "contact_id": {"type": "string", "description": "The pet's id, to change a pet that is already there, or "
                                                    "a contact already there to make into a pet."},
    "name": {"type": "string", "description": "The pet's name, such as Clara."},
    "species": {"type": "string", "description": "What kind of animal: dog, cat, horse, rabbit, bird, fish, "
                                                 "or the person's own word."},
    "owner_ids": {"type": "array", "items": {"type": "string"},
                  "description": "The contacts it belongs to, by the ids search_contacts gives. Needed for a "
                                 "new pet; for one already there, these are added to its owners."},
    "remove_owner_ids": {"type": "array", "items": {"type": "string"},
                         "description": "Owners to take off a pet already there. It keeps at least one."}}}


def on(who=None) -> bool:
    from . import switches

    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def of(meta: dict | None) -> dict:
    """The pet's own field, or {} for a person."""
    got = (meta or {}).get("pet")
    return dict(got) if isinstance(got, dict) else {}


def species_of(meta: dict | None) -> str:
    return str(of(meta).get("species") or "").strip()


def owner_ids(meta: dict | None) -> list[str]:
    return [str(x) for x in of(meta).get("owners") or [] if str(x or "").strip()]


def said_species(species: str) -> str:
    """'a dog', 'an owl', 'a pet'."""
    word = (species or "").strip().lower()
    if not word or word == "other":
        return "a pet"
    return ("an " if word[:1] in "aeiou" else "a ") + word


def _clean_species(value) -> str:
    word = " ".join(str(value or "").split()).lower()[:MAX_SPECIES]
    return word


def _row(ds: dict, item_id: str, *, lock: bool = False) -> dict | None:
    from .synapse import db

    try:
        uuid.UUID(str(item_id))
    except (TypeError, ValueError):
        return None
    return db.row("SELECT * FROM synapse.item WHERE dataset_id = %s AND id = %s::uuid AND kind = 'person' "
                  "AND deleted_at IS NULL" + (" FOR UPDATE" if lock else ""), (ds["id"], str(item_id)))


def _owner_rows(ds: dict, ids) -> list[dict]:
    from .synapse import db

    ids = [str(x) for x in ids or []]
    good = []
    for one in ids:
        try:
            good.append(str(uuid.UUID(one)))
        except (TypeError, ValueError):
            continue
    if not good:
        return []
    rows = db.rows("SELECT * FROM synapse.item WHERE dataset_id = %s AND id = ANY(%s::uuid[]) AND kind = 'person' "
                   "AND deleted_at IS NULL", (ds["id"], good))
    order = {pid: n for n, pid in enumerate(good)}
    return sorted(rows, key=lambda r: order.get(str(r["id"]), 99))


def _face(row: dict) -> str:
    from . import people

    return people._photo_url(row)


def _brief(row: dict) -> dict:
    meta = row.get("meta") or {}
    out = {"id": str(row["id"]), "name": str(meta.get("name") or row.get("title") or "")}
    face = _face(row)
    if face:
        out["photo"] = face
    if of(meta):
        out["species"] = species_of(meta)
    return out


def owners(user_id: str, org_id: str, meta: dict | None) -> list[dict]:
    """The contacts a pet belongs to, each {id, name, photo}, in the order they were said."""
    from .synapse.sources import contacts

    ids = owner_ids(meta)
    if not ids or not user_id or not org_id:
        return []
    ds = contacts.master_of(user_id, org_id)
    return [_brief(r) for r in _owner_rows(ds, ids)]


def of_owner(user_id: str, org_id: str, person_id: str) -> list[dict]:
    """The pets a contact has, each {id, name, species, photo}, by name."""
    from .synapse import db
    from .synapse.sources import contacts

    if not person_id or not user_id or not org_id:
        return []
    ds = contacts.master_of(user_id, org_id)
    rows = db.rows("SELECT * FROM synapse.item WHERE dataset_id = %s AND kind = 'person' AND deleted_at IS NULL "
                   "AND meta->'pet'->'owners' ? %s ORDER BY lower(title)", (ds["id"], str(person_id)))
    return [_brief(r) for r in rows]


class Refused(ValueError):
    """Why a pet was not made or changed, in words."""


def save(user_id: str, org_id: str, *, pet_id: str = "", name: str | None = None, species: str | None = None,
         add_owners=(), remove_owners=(), by: str = "rouh"):
    """Make a pet, or change one, and hand it back as a `people.Person`.

    A new pet needs a name and at least one owner; a pet is never left with none. An owner must be a contact
    of the same person, and never a pet. Refused says what is wrong; nothing is written then.
    """
    from . import people
    from .synapse import db, people as synapse_people
    from .synapse.sources import contacts

    if not user_id or not org_id:
        raise Refused("A pet belongs to a person in an organisation.")
    ds = contacts.master_of(user_id, org_id)
    adding = [str(x).strip() for x in add_owners or [] if str(x or "").strip()]
    removing = {str(x).strip().lower() for x in remove_owners or [] if str(x or "").strip()}
    found = {}
    for one in adding:
        row = contacts.person_by_id(user_id, org_id, one)
        if row is None:
            raise Refused(f"There is no contact with the id {one} to be its owner. Search for them first.")
        if of(row.get("meta")):
            raise Refused(f"{row.get('title') or one} is a pet, and a pet cannot own a pet.")
        found[str(row["id"])] = row
    clean_name = None if name is None else " ".join(str(name).split())[:MAX_NAME]
    clean_species = None if species is None else _clean_species(species)
    with db.atomic():
        if not pet_id:
            if not clean_name:
                raise Refused("A new pet needs a name.")
            if not found:
                raise Refused("A new pet needs at least one owner: a contact it belongs to.")
            meta_pet = {"species": clean_species or "", "owners": list(found), "since": time.time()}
            made = synapse_people.create(ds, name=clean_name, origin="synapse", owner=str(ds.get("me_id") or ""),
                                         readers=[str(ds.get("me_id") or "")] or None,
                                         extra={"pet": meta_pet}, source_key=f"pet:{uuid.uuid4()}",
                                         why="a pet, told Rouh")
            from . import evolution

            evolution.used(SWITCH, "pet_saved", detail="a new pet")
            return people._person(db.row("SELECT * FROM synapse.item WHERE id = %s", (made["id"],)))
        row = contacts.person_by_id(user_id, org_id, pet_id)
        row = _row(ds, str(row["id"]), lock=True) if row is not None else None
        if row is None:
            raise Refused(f"There is no contact with the id {pet_id}.")
        meta = dict(row.get("meta") or {})
        pet = of(meta)
        if not pet:
            # A contact already there - a card on the phone, say - said to be a pet: it becomes one, keeping
            # everything else it has. It needs an owner, and is never the person's own contact.
            if meta.get("is_me"):
                raise Refused("Your own contact cannot be a pet.")
            if not found:
                raise Refused(f"To make {row.get('title') or pet_id} a pet, say who it belongs to (owner_ids).")
            if of_owner(user_id, org_id, str(row["id"])):
                raise Refused(f"{row.get('title') or pet_id} has pets of their own, so they are not made a pet.")
            pet = {"species": "", "owners": [], "since": time.time()}
        if str(row["id"]) in found:
            raise Refused("A pet cannot belong to itself.")
        held = owner_ids(meta)
        held = [x for x in held if x.lower() not in removing] + [x for x in found if x not in held]
        if not held:
            raise Refused(f"{row.get('title') or 'The pet'} has to belong to somebody, so its last owner "
                          "was not taken off.")
        pet["owners"] = held
        if clean_species is not None:
            pet["species"] = clean_species
        meta["pet"] = pet
        title = row["title"]
        if clean_name:
            title = meta["name"] = clean_name
        contacts.write(ds, row, meta, title, by=by, why="a pet, changed")
        from . import evolution

        evolution.used(SWITCH, "pet_saved", detail="a pet changed")
        return people._person(db.row("SELECT * FROM synapse.item WHERE id = %s", (row["id"],)))


def said(user_id: str, org_id: str, person) -> list[str]:
    """Lines for the model about a contact's pets or a pet's owners, for search_contacts and show_contact."""
    meta = {"pet": (person.profile or {}).get("pet")} if person is not None else {}
    if of(meta):
        names = owners(user_id, org_id, meta)
        kind = species_of(meta)
        return [f"  a pet ({kind}), not a person: never called, messaged or written to" if kind and kind != "other"
                else "  a pet, not a person: never called, messaged or written to",
                "  belongs to: " + ("; ".join(f"{o['name']} (id {o['id']})" for o in names) or "nobody known")]
    pets = of_owner(user_id, org_id, person.id) if person is not None and person.id else []
    if not pets:
        return []
    return ["  pets: " + "; ".join(f"{p['name']} ({p.get('species') or 'pet'}, id {p['id']})" for p in pets)]


__all__ = ["DESCRIPTION", "SCHEMA", "SPECIES", "SWITCH", "Refused", "of", "of_owner", "owners", "save", "said"]
