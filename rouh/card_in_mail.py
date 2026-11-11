"""A contact card in an email: a .vcf somebody sent, saved to ‹his› contacts in one press from the email
itself, onto the card ‹he› already has for that person when there is one.

Built by the nightly feature run, night 40 of the ledger (11 November 2026, task 94).
An assistant passes on her boss's details, a supplier introduces a new account manager, a colleague
forwards the plumber: the details come as a contact card attached to the email. Saving it meant
downloading the file and opening it on a phone, and asking Rouh did nothing, because nothing read a
card file into the contacts. Opened on a phone, it also makes a second card for somebody already
there.

So, while its switch is on, an email opened on the inbox card that carries a card file (a `.vcf`, or
a part sent as `text/vcard` or `text/x-vcard`) has a line under it, worked out as it opens: whose card
it is (`vcard.read`, the reader iCloud's cards are read with) and what it holds, and whether that
person is in ‹his› contacts already, found by an address on the card or, failing that, by the same
name on exactly one contact (`same_contact.name_key`). For somebody new, **Save <name> to contacts** writes
the card as a new contact in iCloud with its name, company, numbers and addresses; for somebody
there, **Add to <name>'s contact** adds only the numbers and addresses their contact lacks. A card
with nothing new says so, with no button. The press reads the email and its card again on the
server, never from the page. A card's notes, birthday and photo are not copied: they are the
sender's, not ‹his›.

No model is asked.

**Whose.** The person's own mail and contacts, by `org_id` and `user_id`.

**Its switch** is `card_in_mail` (`rouh/switches.py`): off, there is no line and the press is refused.
"""
from __future__ import annotations

import logging

log = logging.getLogger("rouh.card_in_mail")

SWITCH = "card_in_mail"
TITLE = "A contact card in an email: saved to your contacts in one press"

KINDS = ("text/vcard", "text/x-vcard", "text/directory")
#: The largest card file read; a card with a big photo in it is still under this.
MOST = 512 * 1024


def on(who) -> bool:
    from . import switches

    if who is None:
        return False
    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def part_of(found: dict) -> dict | None:
    """The first card file on the message, as `Gmail.message` lists its attachments, or None."""
    for one in found.get("attachments") or []:
        name = str(one.get("name") or "").lower()
        kind = str(one.get("type") or "").lower()
        if (name.endswith(".vcf") or kind in KINDS) and int(one.get("size") or 0) <= MOST:
            return one
    return None


def person_of(data: bytes):
    """The card file's person (`vcard.Person`), or None when it is not a card of one person."""
    from . import vcard

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("latin-1")
    try:
        person = vcard.read(text)
    except vcard.BadField:
        return None
    if person.kind != "individual" or not (person.name or "").strip():
        return None
    if not person.phones and not person.emails:
        return None
    return person


def _addresses(person) -> list[str]:
    return [str(e.get("address") or "").strip().lower() for e in person.emails if "@" in str(e.get("address") or "")]


def contact_of(cards: list[dict], person) -> dict | None:
    """The contact this card is: by an address on both, else by the same name on exactly one contact."""
    from .same_contact import _emails, name_key

    mine = set(_addresses(person))
    by_address = [c for c in cards if mine & set(_emails(c))]
    if by_address:
        return by_address[0]
    wanted = name_key(person.name)
    named = [c for c in cards if wanted and name_key(c.get("name") or "") == wanted]
    return named[0] if len(named) == 1 else None


def new_on(card: dict, person) -> tuple[list[dict], list[dict]]:
    """(the numbers, the addresses) on the card file that the contact lacks."""
    from .same_contact import _emails, _phones
    from .sig_phones import same

    have_numbers, have_addresses = _phones(card), set(_emails(card))
    phones = [p for p in person.phones if not any(same(p.get("number") or "", h) for h in have_numbers)]
    emails = [e for e in person.emails if str(e.get("address") or "").strip().lower() not in have_addresses]
    return phones, emails


def _list(person, phones=None, emails=None) -> str:
    phones = person.phones if phones is None else phones
    emails = person.emails if emails is None else emails
    bits = [f"{p.get('number')}" + (f" ({p.get('label')})" if p.get("label") else "") for p in phones[:4]]
    bits += [str(e.get("address")) for e in emails[:3]]
    return ", ".join(bits)


def line(cards: list[dict], person) -> dict:
    """What the opened email's line says: `said`, `name`, `kind` ("new" or "known") and `button`, the words on
    its button ("" when there is nothing to save)."""
    known = contact_of(cards, person)
    who = person.name + (f", {person.organisation}" if person.organisation else "")
    if known is None:
        return {"said": f"This email carries a contact card: {who}, {_list(person)}. Not in your contacts.",
                "name": person.name, "kind": "new", "button": f"Save {person.name} to contacts"}
    phones, emails = new_on(known, person)
    if not phones and not emails:
        return {"said": f"This email carries {person.name}'s contact card, and your contact "
                        f"{known.get('name')} already has everything on it.", "name": person.name, "kind": "known",
                "button": ""}
    return {"said": f"This email carries {person.name}'s contact card. Your contact {known.get('name')} lacks "
                    f"{_list(person, phones, emails)}.", "name": known.get("name") or person.name,
            "kind": "known", "button": f"Add to {known.get('name') or person.name}'s contact"}


async def read(gmail, found: dict):
    """The person on the message's card file, read from Gmail, or None."""
    part = part_of(found)
    if part is None:
        return None
    got = await gmail.attachment(found["id"], part["part"])
    data = got.get("data") or b""
    if len(data) > MOST:
        return None
    return person_of(data)


async def shown(who, gmail, found: dict) -> dict | None:
    """The line for an opened email, or None."""
    import asyncio

    from . import evolution
    from .synapse.sources import contacts

    if part_of(found) is None or not await asyncio.to_thread(on, who):
        return None
    cards = await asyncio.to_thread(contacts.all_cards, str(who.user_id), str(who.org_id))
    if not cards:
        return None          # iCloud contacts not connected: nothing to save into.
    person = await read(gmail, found)
    if person is None:
        return None
    said = line(cards, person)
    await asyncio.to_thread(evolution.used, SWITCH, "shown", who=who,
                            detail=said["kind"])
    return said


async def save(who, gmail, found: dict, desk) -> tuple[bool, str]:
    """Save to contacts or Add to their contact, pressed: (done, what the line says now)."""
    import asyncio

    from . import evolution
    from .synapse.sources import contacts

    if desk is None:
        return False, "iCloud contacts are not connected, so the card cannot be saved."
    person = await read(gmail, found)
    if person is None:
        return False, "This email carries no contact card that can be read."
    cards = await asyncio.to_thread(contacts.all_cards, str(who.user_id), str(who.org_id))
    known = contact_of(cards, person)
    if known is None:
        args = {"name": person.name, "add_phones": person.phones, "add_emails": person.emails}
        if person.organisation:
            args["organisation"] = person.organisation
        done = await desk.save(args, who)
        words = str(getattr(done, "text", "") or done)
        if not words.startswith("Added"):
            return False, words.split(" It reaches")[0][:300]
        await asyncio.to_thread(evolution.used, SWITCH, "saved", who=who, detail="a new contact")
        return True, f"Saved {person.name} to your contacts. It reaches your phone when it next syncs with iCloud."
    phones, emails = new_on(known, person)
    if not phones and not emails:
        return True, f"{known.get('name')}'s contact already has everything on the card."
    args = {"contact_id": known["id"], "add_phones": phones, "add_emails": emails}
    if person.organisation and not str(known.get("organisation") or "").strip():
        args["organisation"] = person.organisation
    done = await desk.save(args, who)
    words = str(getattr(done, "text", "") or done)
    if not (words.startswith("Changed") or "already reads that way" in words):
        return False, words.split(" It reaches")[0][:300]
    await asyncio.to_thread(evolution.used, SWITCH, "saved", who=who, detail="added to a contact")
    return True, (f"Added {_list(person, phones, emails)} to {known.get('name')}'s contact. "
                  "It reaches your phone when it next syncs with iCloud.")


__all__ = ["SWITCH", "TITLE", "contact_of", "line", "new_on", "on", "part_of", "person_of", "save", "shown"]
