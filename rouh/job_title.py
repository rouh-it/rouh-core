"""A contact's job title: read, searched and written, as the phone's own Job title field.

Built by the nightly feature run, night 42 of the ledger (13 November 2026, task 94).
An iPhone contact has a Job title (vCard's TITLE), and Rouh never read it: asked "what is Nina's
title", search_contacts did not say it; asked "put Head of Operations as her title", save_contact had
no field for it; asked "who do I know who is a lawyer", the search matched names, numbers, addresses
and companies, never titles. Night 41's A new company in their signature reads a title from a
signature and could not keep it.

So, while its switch is on:

- **read**: search_contacts and show_contact say each contact's job title, and the contact card on
  the screen shows it as a row, its change marked like the company's (`apple_contacts._rows`);
- **searched**: a search whose words are in somebody's job title finds them too, after the matches
  by name, number, address or company (`found`);
- **written**: save_contact takes `title`, which writes TITLE on the card in iCloud (`vcard.Changes`),
  shown first and saved only on the person's yes, like every other field.

Off, nothing is said or shown about a title, a search does not look at titles, and a title asked to
be written is not: the model is told the gene is switched off. No model is asked.

**Whose.** The person's own contacts, by `org_id` and `user_id`. The title lives on the card in
iCloud and in Rouh's copy of it (the card's own vCard text); nothing else is kept.

**Its switch** is `job_title` (`rouh/switches.py`).
"""
from __future__ import annotations

import logging
import unicodedata

log = logging.getLogger("rouh.job_title")

SWITCH = "job_title"
TITLE = "A contact's job title: read, searched and written"

#: The shortest words a title is searched by.
SHORTEST = 3


def on(who=None) -> bool:
    from . import switches

    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def _from_vcard(text: str) -> str:
    from . import vcard

    if not text:
        return ""
    try:
        return " ".join(vcard.Card.parse(text).value("TITLE").split())
    except vcard.BadField:
        return ""


def of(person) -> str:
    """The job title of a contact (a card of Rouh's copy, a `vcard.Person` or a card's fields), or ""
    while the switch is off."""
    if not on():
        return ""
    if isinstance(person, dict):
        if person.get("title") is not None:
            return " ".join(str(person.get("title") or "").split())
        return _from_vcard(str(person.get("vcard") or ""))
    got = getattr(person, "title", None)
    if got is not None:
        return " ".join(str(got).split())
    card = getattr(person, "card", None)
    return of(card) if isinstance(card, dict) else ""


def _plain(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", str(text or ""))
    return " ".join("".join(c for c in decomposed if not unicodedata.combining(c)).casefold().split())


def found(who, query: str, skip: set[str], limit: int) -> list[dict]:
    """The cards whose job title holds the query's words, none of `skip`. Synchronous: it reads the
    database."""
    from . import evolution
    from .synapse.sources import contacts

    words = [w for w in _plain(query).split() if len(w) >= SHORTEST]
    if not words or not on(who) or limit <= 0:
        return []
    out = []
    for card in contacts.all_cards(str(who.user_id), str(who.org_id)):
        if str(card.get("id")) in skip:
            continue
        title = _plain(_from_vcard(str(card.get("vcard") or "")))
        if title and all(w in title for w in words):
            out.append(card)
            if len(out) >= limit:
                break
    if out:
        evolution.used(SWITCH, "found", who=who, detail=f"{len(out)} by their job title")
    return out


def allowed(who, args: dict) -> tuple[dict, str]:
    """(the arguments save_contact goes on with, why not): off, a title is taken out of them, and a
    save that asked for nothing but a title is told the gene is switched off."""
    if "title" not in args or args.get("title") is None:
        return args, ""
    if who is not None and on(who):
        confirmed = args.get("confirmed") is True or str(args.get("confirmed") or "").lower() == "true"
        if confirmed:
            from . import evolution

            evolution.used(SWITCH, "written", who=who,
                           detail=f"{args.get('name') or args.get('contact_id') or 'a contact'}: a job title")
        return args, ""
    rest = {k: v for k, v in args.items() if k != "title"}
    asked = {k for k, v in rest.items() if v not in (None, "", [], False)} - {"confirmed", "contact_id",
                                                                            "even_if_known"}
    if not asked:
        return rest, ("A contact's job title is switched off (Evolution, Mutations), so it was not written. "
                      "Nothing was saved.")
    return rest, ""


__all__ = ["SWITCH", "TITLE", "allowed", "found", "of", "on"]
