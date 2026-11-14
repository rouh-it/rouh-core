"""Directions from their contact card: every postal address on a contact card in the chat is one press
from the way there in Maps.

Built by the nightly feature run, night 43 of the ledger (14 November 2026, task 94).
Going to somebody's office or home meant copying the address off their card into Maps on the phone.
Night 42's Call from their contact card made each number one press from ringing; tonight's A contact's
postal address (`rouh/postal_address.py`) put addresses on the card, and this does the same for them.

So, while its switch is on, a contact card that shows a contact as it is (show_contact, a contact just
saved) with a postal address marks itself `directions` (`mark`): the page draws each address as a link to
directions in Google Maps, with Directions beside it (`contactDirections` in `cards.js`), which opens the
Maps app on a phone. Rouh is told only that the press happened, to count the gene's use
(`POST /api/card-directions`, `rouh/web/card_directions.py`), and the address never travels there. A
contact not saved yet, or turned down, has no Directions: it is a look at a change, not a place to go.

It shows only addresses, so it needs A contact's postal address on to have anything to draw.

**Whose.** Nothing is kept but the count of uses (`evolution.used`).

**Its switch** is `card_directions` (`rouh/switches.py`): off, an address on a card is plain words.
"""
from __future__ import annotations

SWITCH = "card_directions"
TITLE = "Directions from their contact card: each address one press from Maps"


def on(who=None) -> bool:
    from . import switches

    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def mark(block: dict, who=None) -> dict:
    """The contact block, marked for directions when the switch is on and it has an address to go to."""
    if block.get("state") in ("unsaved", "declined"):
        return block
    if not any(r.get("kind") == "postal" and r.get("change") != "removed" for r in block.get("rows") or []):
        return block
    if on(who):
        block["directions"] = True
    return block


def pressed(who) -> bool:
    """Directions pressed on a contact card: counted, when the switch is on."""
    from . import evolution

    if not on(who):
        return False
    evolution.used(SWITCH, "directions", who=who, detail="Directions from a contact card")
    return True


__all__ = ["SWITCH", "TITLE", "mark", "on", "pressed"]
