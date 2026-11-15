"""Their address saved with them: a contact saved from an email carries the postal address its
signature gives.

Built by the nightly feature run, night 44 of the ledger (15 November 2026, task 94).
Night 39's Save them as a contact (`rouh/save_sender.py`) saves a new sender's name, address, company and
numbers from their email, and night 43 added their job title (`rouh/title_saved.py`); the office address
on the lines under them was read past, so the card on the phone had no address and filling it took a
second ask, or typing it on the phone. Night 43 made the card's postal address writable
(`rouh/postal_address.py`).

So, while its switch is on, nothing new is asked of anybody: **Save to contacts** on an email says the
address it found in the line of what saving adds ("work address 5 Harbour Road, 20457 Hamburg, Germany")
and writes it on the new card with the rest, labelled work.

Only an address found for certain in the sender's signature (`sig_address.address_in`, plain rules, no
model: a street, with a city or a postal code) is written. Off, a contact is saved exactly as before.

**Whose.** The person's own contacts, by `org_id` and `user_id`; nothing is kept beyond the card.

**Its switch** is `address_saved` (`rouh/switches.py`).
"""
from __future__ import annotations

SWITCH = "address_saved"
TITLE = "Their address saved with them: the signature's postal address on a contact saved from an email"


def on(who=None) -> bool:
    from . import switches

    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def for_new(who, body: str, name: str) -> dict | None:
    """The postal address a contact saved from their email carries, as ADR's parts: None while the switch
    is off or the signature gives none."""
    if who is None or not on(who):
        return None
    from .sig_address import address_in

    return address_in(body or "", name or "")


def line(parts: dict | None) -> str:
    from . import vcard

    return vcard.address_line(parts or {})


__all__ = ["SWITCH", "TITLE", "for_new", "line", "on"]
