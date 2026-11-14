"""Save them as a contact: an email opened on the inbox card from somebody who is not in ‹his› contacts
says so, with one button that saves them, the company and the numbers in their signature included.

Built by the nightly feature run, night 39 of the ledger (10 November 2026, task 94).
Somebody new writes: a client's new colleague, a supplier, a person introduced. Their name, their
company and their phone are all in the email, and none of it is in ‹his› contacts, so their call next
week rings as a bare number. Saving them meant opening Contacts, typing the name, copying the address,
finding the number in the signature and working out what the Company field should say, the field
‹his› phone shows when they ring.

So, while its switch is on, an email opened on the inbox card (`rouh/inbox.py`) from a person, not a
machine or a list or ‹him›self, whose address is on none of ‹his› iCloud contacts (Rouh's own copy in
Synapse Master), says under its headers: "Kai Novak is not in your contacts." and what would be saved:
the name as the email gives it, the address, the company (from other contacts at the same work domain,
else guessed from the domain, `no_company`'s rules; none for a free-mail address) and the numbers in
the signature (`rouh/sig_phones.py`). Its button **Save to contacts** writes that card to iCloud, and
the line then says it was saved. Nothing is saved until the button is pressed, and the message is read
again on the server for the press, so the page never says what goes on the card.

No model is asked.

**Whose.** The person's own contacts and mail, by `org_id` and `user_id`.

**Its switch** is `save_sender` (`rouh/switches.py`): off, there is no line and no button.
"""
from __future__ import annotations

import email.utils
import logging
from collections import Counter

log = logging.getLogger("rouh.save_sender")

SWITCH = "save_sender"
TITLE = "Save them as a contact: somebody not in your contacts, saved from their email in one press"


def on(who) -> bool:
    from . import switches

    if who is None:
        return False
    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def _ids(who) -> tuple[str, str]:
    return str(getattr(who, "user_id", "") or ""), str(getattr(who, "org_id", "") or "")


def _name_of(header: str, address: str) -> str:
    """The sender's name as their email gives it; from the address when it gives none."""
    name = " ".join(str(email.utils.parseaddr(header or "")[0] or "").replace('"', "").split())
    if "," in name and len(name.split(",")) == 2:
        last, first = (p.strip() for p in name.split(","))
        name = f"{first} {last}".strip()
    if name and "@" not in name:
        return name
    local = address.partition("@")[0]
    parts = [p for p in local.replace("_", ".").replace("-", ".").split(".") if p.isalpha()]
    return " ".join(p.capitalize() for p in parts) if len(parts) >= 2 else ""


def company_for(address: str, cards: list[dict]) -> tuple[str, str]:
    """(the company, how it was found) for a new contact at this address, ("", "") for free mail."""
    from .no_company import _work_domain, name_of

    domain = _work_domain(address)
    if not domain:
        return "", ""
    seen: Counter = Counter()
    for card in cards:
        org = " ".join(str(card.get("organisation") or "").split())
        if not org:
            continue
        for e in card.get("emails") or []:
            if _work_domain(e.get("address") if isinstance(e, dict) else e) == domain:
                seen[org] += 1
    if seen:
        org, n = seen.most_common(1)[0]
        return org, f"as {n} other contact{'s' if n != 1 else ''} at {domain}"
    return name_of(domain), f"guessed from {domain}"


def known(cards: list[dict], address: str) -> bool:
    address = address.strip().lower()
    return any(str(e.get("address") if isinstance(e, dict) else e).strip().lower() == address
               for c in cards for e in c.get("emails") or [])


def card_for(found: dict, cards: list[dict], own: list[str] = (), who=None) -> dict | None:
    """What would be saved for the sender of `found`, or None when they are no new person."""
    from . import new_number
    from .sig_phones import label_for, phones

    if not new_number.is_a_person(found, own):
        return None
    address = (email.utils.parseaddr(found.get("from", ""))[1] or "").strip().lower()
    if not address or known(cards, address):
        return None
    name = _name_of(found.get("from", ""), address)
    if not name:
        return None
    org, how = company_for(address, cards)
    body = found.get("body") or ""
    numbers = [{"number": n, "label": label_for(body, n)} for n in phones(body)]
    # Their job title saved with them (night 43, `rouh/title_saved.py`): "" while its switch is off.
    from . import title_saved

    title = title_saved.for_new(who, body, name)
    return {"name": name, "address": address, "company": org, "company_how": how, "phones": numbers,
            "title": title}


def sentence(card: dict) -> str:
    bits = [card["address"]]
    if card.get("company"):
        bits.append(f"company {card['company']} ({card['company_how']})")
    if card.get("title"):
        bits.append(f"job title {card['title']}")
    bits += [f"{p['label']} {p['number']}" for p in card.get("phones") or []]
    return f"{card['name']} is not in your contacts. Saving them adds: " + "; ".join(bits) + "."


def _cards(who) -> list[dict]:
    from .synapse.sources import contacts

    user_id, org_id = _ids(who)
    return contacts.all_cards(user_id, org_id)


def shown(who, found: dict, own: list[str] = ()) -> dict | None:
    """What the opened message's line says, or None. Synchronous: it reads the database."""
    if not on(who):
        return None
    cards = _cards(who)
    if not cards:
        return None          # iCloud contacts not connected: nothing to save into.
    card = card_for(found, cards, own, who)
    if card is None:
        return None
    from . import new_address

    if new_address.on(who) and new_address.match(cards, *email.utils.parseaddr(found.get("from", ""))):
        # A new address for a contact (night 40): somebody already in the contacts under their name, at a
        # new address, is not offered a second card; the notice adds the address to the one they have.
        return None
    from . import evolution

    evolution.used(SWITCH, "shown", who=who, detail="with a company" if card["company"] else "no company")
    return {"said": sentence(card), "name": card["name"]}


async def save(who, found: dict, desk, own: list[str] = ()) -> tuple[bool, str]:
    """Save to contacts, pressed: (done, what the line says now)."""
    import asyncio

    from . import evolution

    if desk is None:
        return False, "iCloud contacts are not connected, so nobody can be saved."
    cards = await asyncio.to_thread(_cards, who)
    address = (email.utils.parseaddr(found.get("from", ""))[1] or "").strip().lower()
    if address and known(cards, address):
        return True, "They are in your contacts already."
    card = card_for(found, cards, own, who)
    if card is None:
        return False, "This sender cannot be saved as a person."
    args = {"name": card["name"], "add_emails": [{"address": card["address"], "label": "work" if card["company"]
                                                  else "home"}],
            "add_phones": card["phones"]}
    if card["company"]:
        args["organisation"] = card["company"]
    if card.get("title"):
        args["title"] = card["title"]
    done = await desk.save(args, who)
    words = str(getattr(done, "text", "") or done)
    if not words.startswith("Added"):
        return False, words.split(" It reaches")[0][:300]
    await asyncio.to_thread(evolution.used, SWITCH, "saved", who=who,
                            detail=f"{'with a company' if card['company'] else 'no company'}, "
                                   f"{len(card['phones'])} number(s)")
    if card.get("title"):
        # Their job title saved with them (night 43, `rouh/title_saved.py`).
        await asyncio.to_thread(evolution.used, "title_saved", "saved", who=who,
                                detail=f"{card['name']}: their job title went with it")
    company = f", {card['title']}" if card.get("title") else ""
    company += f", {card['company']}" if card["company"] else ""
    return True, (f"Saved {card['name']}{company} to your contacts. It reaches your phone when it next "
                  "syncs with iCloud.")


__all__ = ["SWITCH", "TITLE", "card_for", "company_for", "on", "save", "sentence", "shown"]
