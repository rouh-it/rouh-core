"""Already in your contacts: a person who is in ‹his› contacts is not added as a second card.

Built by the nightly feature run, night 42 of the ledger (13 November 2026, task 94).
Asked to add somebody, Rouh's save_contact made a new card every time it was given no contact id,
even for somebody already there under the same address or number: the only check was a card added
in the same thread in the last ten minutes. The second card is the one Contacts kept twice (night 39)
finds weeks later, after the phone has shown the wrong one when they rang.

So, while its switch is on, before a new contact is looked at or saved, Rouh's own copy of ‹his›
iCloud contacts (Synapse Master, `synapse/sources/contacts.all_cards`, the copy search_contacts reads)
is read for a card that is the same person:

- **the same address**: an email address being added is on a card;
- **the same number**: a number being added is on a card, by its last nine digits, a switchboard (a
  number on three or more cards) aside;
- **the same name**: the same words in the name, in any order, accents and case aside
  (`same_contact.name_key`), unless both say a company and the companies differ.

Then nothing is made and nothing is drawn: the model is told the card, its id and why it is the same
person, and to add what is new to that card with its id. ``even_if_known`` makes the second card on
purpose, for two people who share a name. No model is asked.

**Whose.** The person's own contacts, by `org_id` and `user_id`. Nothing is kept.

**Its switch** is `known_contact` (`rouh/switches.py`): off, a new contact is made as before.
"""
from __future__ import annotations

import logging

log = logging.getLogger("rouh.known_contact")

SWITCH = "known_contact"
TITLE = "Already in your contacts: a person who is there is not added as a second card"

#: The argument that makes the second card anyway.
ANYWAY = "even_if_known"

#: At most this many cards are named.
NAMED = 3


def on(who) -> bool:
    from . import switches

    if who is None:
        return False
    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def _wanted(args: dict) -> tuple[str, list[str], list[str], str]:
    """(the name, the addresses, the numbers, the company) a new contact is asked for with."""
    def items(key: str, what: str) -> list[str]:
        out = []
        for item in args.get(key) or []:
            value = item.get(what) if isinstance(item, dict) else item
            value = str(value or "").strip()
            if value:
                out.append(value)
        return out

    return (str(args.get("name") or "").strip(), [a.lower() for a in items("add_emails", "address")],
            items("add_phones", "number"), str(args.get("organisation") or "").strip())


def matches(cards: list[dict], args: dict) -> list[tuple[dict, str]]:
    """The cards that are the person a new contact is asked for, each with why: [(card, why)]."""
    from .same_contact import SWITCHBOARD, _emails, _org, _phones, _plain, _tail, name_key

    name, emails, phones, company = _wanted(args)
    tails = {_tail(p) for p in phones} - {""}
    held: dict[str, int] = {}
    for c in cards:
        for t in {_tail(p) for p in _phones(c)} - {""}:
            held[t] = held.get(t, 0) + 1
    key = name_key(name)
    found: list[tuple[dict, str]] = []
    for c in cards:
        why = ""
        same_mail = sorted(set(emails) & set(_emails(c)))
        same_tail = sorted(t for t in tails & ({_tail(p) for p in _phones(c)} - {""})
                           if held.get(t, 0) < SWITCHBOARD)
        if same_mail:
            why = f"the same address, {same_mail[0]}"
        elif same_tail:
            number = next(p for p in _phones(c) if _tail(p) == same_tail[0])
            why = f"the same number, {number}"
        elif key and name_key(c.get("name") or "") == key:
            theirs = _org(c)
            if company and theirs and _plain(company) != _plain(theirs) \
                    and _plain(company) not in _plain(theirs) and _plain(theirs) not in _plain(company):
                continue          # Two people with one name, at two companies.
            why = "the same name"
        if why:
            found.append((c, why))
    order = {"the same address": 0, "the same number": 1, "the same name": 2}
    found.sort(key=lambda cw: order.get(cw[1].split(",")[0], 3))
    return found


def _card_said(card: dict) -> str:
    bits = []
    if card.get("organisation"):
        bits.append(str(card["organisation"]))
    bits += [str(p.get("number") if isinstance(p, dict) else p) for p in card.get("phones") or []]
    bits += [str(e.get("address") if isinstance(e, dict) else e) for e in card.get("emails") or []]
    return f"{card.get('name') or '(no name)'} (id {card['id']})" + (f": {'; '.join(bits)}" if bits else "")


def said(found: list[tuple[dict, str]], name: str) -> str:
    first, why = found[0]
    lines = [f"Not added: {name or 'that person'} is already in the contacts, by {why}."]
    for card, because in found[:NAMED]:
        lines.append(f"- {_card_said(card)}, by {because}")
    if len(found) > NAMED:
        lines.append(f"- and {len(found) - NAMED} more")
    lines.append(
        "Nothing was saved and no card was drawn. Tell the person they are already there, and on which "
        f"card. To add what is new, call save_contact with contact_id {first['id']} and only the new "
        "fields (add_phones, add_emails, organisation, birthday), which shows the change before it is "
        f"saved. Only if the person says this is somebody else, call it again with {ANYWAY} true.")
    return "\n".join(lines)


def check(who, args: dict) -> str:
    """Why a new contact is not made, or "" to make it. Synchronous: it reads the database."""
    from . import evolution
    from .synapse.sources import contacts

    if args.get("contact_id") or not on(who):
        return ""
    if args.get(ANYWAY) is True or str(args.get(ANYWAY) or "").strip().lower() == "true":
        return ""
    cards = contacts.all_cards(str(who.user_id), str(who.org_id))
    found = matches(cards, args)
    if not found:
        return ""
    name = str(args.get("name") or "").strip()
    evolution.used(SWITCH, "held", who=who, detail=f"{name or found[0][0].get('name')}: {found[0][1]}")
    return said(found, name)


__all__ = ["ANYWAY", "SWITCH", "TITLE", "check", "matches", "on", "said"]
