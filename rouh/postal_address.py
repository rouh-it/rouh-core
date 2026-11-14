"""A contact's postal address: read, searched and written, as the phone's own Address field.

Built by the nightly feature run, night 43 of the ledger (14 November 2026, task 94).
An iPhone contact has addresses (vCard's ADR: home, work, any label), and Rouh never read them: asked
"what is Nina's office address" for a courier, a gift or a visit, search_contacts did not say it; asked
"who do I know in Plovdiv", the search matched names, numbers, emails and companies, never a city; asked
"put her new office, 12 Vitosha Blvd, Sofia, on her card", save_contact had no field for it. So ‹he›
opened Contacts on the phone and read or typed it there.

So, while its switch is on:

- **read**: search_contacts and show_contact say each contact's postal addresses with their labels, and
  the contact card on the screen shows each as a row, a new one or one taken off marked like a number;
- **searched**: a search whose words are in somebody's address (a city, a street, a country) finds them
  too, after the matches by name, number, email or company (`found`);
- **written**: save_contact takes `add_addresses` (street, city, postal code, region, country and a
  label) and `remove_addresses`, written to ADR on the card in iCloud (`vcard.Changes`), shown first and
  saved only on the person's yes, like every other field.

Off, nothing is said or shown about an address, a search does not look at addresses, and an address asked
to be written is not: the model is told the gene is switched off. No model is asked.

**Whose.** The person's own contacts, by `org_id` and `user_id`. An address lives on the card in iCloud
and in Rouh's copy of it (the card's own vCard text); nothing else is kept.

**Its switch** is `postal_address` (`rouh/switches.py`).
"""
from __future__ import annotations

import logging

log = logging.getLogger("rouh.postal_address")

SWITCH = "postal_address"
TITLE = "A contact's postal address: read, searched and written"

#: The shortest words an address is searched by.
SHORTEST = 3

#: What the model may give for one address.
PARTS_SCHEMA = {
    "type": "object",
    "properties": {
        "street": {"type": "string", "description": "The street and number, with a flat or floor."},
        "city": {"type": "string"},
        "postal_code": {"type": "string"},
        "region": {"type": "string", "description": "A state, county or province, when it has one."},
        "country": {"type": "string"},
        "label": {"type": "string", "description": "home, work, or the person's own word for it."},
    },
}


def on(who=None) -> bool:
    from . import switches

    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def _from_vcard(text: str) -> list[dict]:
    from . import vcard

    if not text:
        return []
    try:
        return vcard.addresses_of(vcard.Card.parse(text))
    except vcard.BadField:
        return []


def _bare(addresses) -> list[dict]:
    return [{"address": str(a.get("address") or ""), "label": str(a.get("label") or "") or "address"}
            for a in addresses or [] if isinstance(a, dict) and str(a.get("address") or "").strip()]


def of(person) -> list[dict]:
    """The postal addresses of a contact (a card of Rouh's copy, a `vcard.Person` or a card's fields),
    each {"address": one line, "label"}, or [] while the switch is off."""
    if not on():
        return []
    if isinstance(person, dict):
        if person.get("addresses") is not None:
            return _bare(person.get("addresses"))
        return _bare(_from_vcard(str(person.get("vcard") or "")))
    got = getattr(person, "addresses", None)
    if got is not None:
        return _bare(got)
    card = getattr(person, "card", None)
    return of(card) if isinstance(card, dict) else []


def found(who, query: str, skip: set[str], limit: int) -> list[dict]:
    """The cards with an address holding the query's words, none of `skip`. Synchronous: it reads the
    database."""
    from . import evolution, vcard
    from .synapse.sources import contacts

    words = [w for w in vcard.normalise(query).split() if len(w) >= SHORTEST]
    if not words or not on(who) or limit <= 0:
        return []
    out = []
    for card in contacts.all_cards(str(who.user_id), str(who.org_id)):
        if str(card.get("id")) in skip:
            continue
        for one in _from_vcard(str(card.get("vcard") or "")):
            text = vcard.normalise(one["address"])
            also = vcard.latin(one["address"])
            if all(w in text or vcard.latin(w) in also for w in words):
                out.append(card)
                break
        if len(out) >= limit:
            break
    if out:
        evolution.used(SWITCH, "found", who=who, detail=f"{len(out)} by their address")
    return out


def to_changes(args: dict) -> tuple[list[dict], list[str]]:
    """save_contact's add_addresses and remove_addresses, as `vcard.Changes` takes them."""
    from . import vcard

    add = []
    for item in args.get("add_addresses") or []:
        if isinstance(item, str):
            item = {"street": item}
        if not isinstance(item, dict):
            continue
        parts = {k: " ".join(str(item.get(k) or "").split()) for k in vcard.ADDRESS_PARTS}
        if not vcard.address_line(parts):
            raise vcard.BadField("An address needs at least a street, a city or a country.")
        add.append({"parts": parts, "label": " ".join(str(item.get("label") or "").split())})
    remove = [" ".join(str(v).split()) for v in args.get("remove_addresses") or [] if str(v or "").strip()]
    return add, remove


def allowed(who, args: dict) -> tuple[dict, str]:
    """(the arguments save_contact goes on with, why not): off, addresses are taken out of them, and a
    save that asked for nothing but an address is told the gene is switched off."""
    asked_for = [k for k in ("add_addresses", "remove_addresses") if args.get(k)]
    if not asked_for:
        return args, ""
    if who is not None and on(who):
        confirmed = args.get("confirmed") is True or str(args.get("confirmed") or "").lower() == "true"
        if confirmed:
            from . import evolution

            evolution.used(SWITCH, "written", who=who,
                           detail=f"{args.get('name') or args.get('contact_id') or 'a contact'}: an address")
        return args, ""
    rest = {k: v for k, v in args.items() if k not in ("add_addresses", "remove_addresses")}
    asked = {k for k, v in rest.items() if v not in (None, "", [], False)} - {"confirmed", "contact_id",
                                                                            "even_if_known"}
    if not asked:
        return rest, ("A contact's postal address is switched off (Evolution, Mutations), so it was not "
                      "written. Nothing was saved.")
    return rest, ""


__all__ = ["PARTS_SCHEMA", "SWITCH", "TITLE", "allowed", "found", "of", "on", "to_changes"]
