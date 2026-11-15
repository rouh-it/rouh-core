"""The people around a contact: their assistant, their manager, their partner, read, searched and
written, as the phone's own Related name field.

Built by the nightly feature run, night 44 of the ledger (15 November 2026, task 94).
An iPhone contact can name the people around them (vCard's X-ABRELATEDNAMES: assistant, manager,
spouse, partner, child, parent, brother, sister, friend, or any label), and Rouh never read them: asked
"who is Nina's assistant" to get time with her, or "whose assistant is Tom Reyes" when Tom writes,
search_contacts did not say; asked "Tom Reyes is Nina's assistant, put it on her card", save_contact had
no field for it. So ‹he› opened Contacts on the phone and read or typed it there, or did not keep it.

So, while its switch is on:

- **read**: search_contacts and show_contact say the people each contact names, with their labels
  ("assistant: Tom Reyes"), and the contact card on the screen shows each as a row, a new one or one
  taken off marked like a number;
- **searched**: a search for a name that is somebody's related name finds that contact too ("Tom Reyes"
  finds Nina Park, whose assistant he is), after the matches by name, number, email or company (`found`);
- **written**: save_contact takes `add_related` (a name and a label) and `remove_related`, written to the
  card in iCloud (`vcard.Changes`), shown first and saved only on the person's yes, like every other field.

Off, nothing is said or shown about a related name, a search does not look at them, and one asked to be
written is not: the model is told the gene is switched off. No model is asked beyond the chat's own turn.

**Whose.** The person's own contacts, by `org_id` and `user_id`. A related name lives on the card in
iCloud and in Rouh's copy of it (the card's own vCard text); nothing else is kept.

**Its switch** is `related_people` (`rouh/switches.py`).
"""
from __future__ import annotations

import unicodedata

SWITCH = "related_people"
TITLE = "The people around a contact: related names read, searched and written"

#: The shortest name a related name is searched by.
SHORTEST = 3

#: What the model may give for one related name.
ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "The person's name, as the contact should show it."},
        "label": {"type": "string",
                  "description": "Who they are to the contact: assistant, manager, spouse, partner, child, "
                                 "parent, mother, father, brother, sister, friend, or the person's own word."},
    },
    "required": ["name"],
}


def on(who=None) -> bool:
    from . import switches

    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def _from_vcard(text: str) -> list[dict]:
    from . import vcard

    if not text:
        return []
    try:
        return vcard.related_of(vcard.Card.parse(text))
    except vcard.BadField:
        return []


def _bare(items) -> list[dict]:
    return [{"name": " ".join(str(i.get("name") or "").split()), "label": str(i.get("label") or "") or "related"}
            for i in items or [] if isinstance(i, dict) and str(i.get("name") or "").strip()]


def of(person) -> list[dict]:
    """The people a contact names (a card of Rouh's copy, a `vcard.Person` or a card's fields), each
    {"name", "label"}, or [] while the switch is off."""
    if not on():
        return []
    if isinstance(person, dict):
        if person.get("related") is not None:
            return _bare(person.get("related"))
        return _bare(_from_vcard(str(person.get("vcard") or "")))
    got = getattr(person, "related", None)
    if got is not None:
        return _bare(got)
    card = getattr(person, "card", None)
    return of(card) if isinstance(card, dict) else []


def _plain(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", str(text or ""))
    return " ".join("".join(c for c in decomposed if not unicodedata.combining(c)).casefold().split())


def found(who, query: str, skip: set[str], limit: int) -> list[dict]:
    """The cards that name somebody whose name holds the query's words, none of `skip`. Synchronous: it
    reads the database."""
    from . import evolution
    from .synapse.sources import contacts

    words = [w for w in _plain(query).split() if len(w) >= SHORTEST]
    if not words or not on(who) or limit <= 0:
        return []
    out = []
    for card in contacts.all_cards(str(who.user_id), str(who.org_id)):
        if str(card.get("id")) in skip:
            continue
        for one in _from_vcard(str(card.get("vcard") or "")):
            if all(w in _plain(one["name"]).split() or w in _plain(one["name"]) for w in words):
                out.append(card)
                break
        if len(out) >= limit:
            break
    if out:
        evolution.used(SWITCH, "found", who=who, detail=f"{len(out)} by somebody around them")
    return out


def to_changes(args: dict) -> tuple[list[dict], list[str]]:
    """save_contact's add_related and remove_related, as `vcard.Changes` takes them."""
    from . import vcard

    add = []
    for item in args.get("add_related") or []:
        if isinstance(item, str):
            item = {"name": item}
        if not isinstance(item, dict):
            continue
        name = " ".join(str(item.get("name") or "").split())
        if not name:
            raise vcard.BadField("A related name needs a name.")
        add.append({"name": name, "label": " ".join(str(item.get("label") or "").split()).lower()})
    remove = [" ".join(str(v).split()) for v in args.get("remove_related") or [] if str(v or "").strip()]
    return add, remove


def allowed(who, args: dict) -> tuple[dict, str]:
    """(the arguments save_contact goes on with, why not): off, related names are taken out of them, and a
    save that asked for nothing but a related name is told the gene is switched off."""
    asked_for = [k for k in ("add_related", "remove_related") if args.get(k)]
    if not asked_for:
        return args, ""
    if who is not None and on(who):
        confirmed = args.get("confirmed") is True or str(args.get("confirmed") or "").lower() == "true"
        if confirmed:
            from . import evolution

            evolution.used(SWITCH, "written", who=who,
                           detail=f"{args.get('name') or args.get('contact_id') or 'a contact'}: a related name")
        return args, ""
    rest = {k: v for k, v in args.items() if k not in ("add_related", "remove_related")}
    asked = {k for k, v in rest.items() if v not in (None, "", [], False)} - {"confirmed", "contact_id",
                                                                            "even_if_known"}
    if not asked:
        return rest, ("The people around a contact is switched off (Evolution, Mutations), so the related "
                      "name was not written. Nothing was saved.")
    return rest, ""


__all__ = ["ITEM_SCHEMA", "SWITCH", "TITLE", "allowed", "found", "of", "on", "to_changes"]
