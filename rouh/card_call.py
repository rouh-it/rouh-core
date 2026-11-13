"""Call from their contact card: every number on a contact card in the chat is one press from ringing,
with Text beside it.

Built by the nightly feature run, night 42 of the ledger (13 November 2026, task 94).
Asked "what is Sam's number", Rouh draws Sam's contact card with the number as plain words: on a phone
it was copied, the phone app opened and the number pasted, and Rouh, asked to ring it, could only say
it. Night 41's Call them from their email did this for an email on the inbox card.

So, while its switch is on, a contact card that shows a contact as it is (show_contact, a contact just
saved) marks itself callable (`mark`): the page draws each of its numbers as a `tel:` link, with Call
and Text (`sms:`) beside it (`contactBlock` in `cards.js`). The phone does the ringing; Rouh is told
only that the press happened, to count the gene's use (`POST /api/card-call`, `rouh/web/card_call.py`),
and the number never travels. A contact not saved yet, or turned down, has no Call: it is a look at a
change, not somebody to ring.

**Whose.** Nothing is kept but the count of uses (`evolution.used`).

**Its switch** is `card_call` (`rouh/switches.py`): off, a number on a card is plain words as before.
"""
from __future__ import annotations

SWITCH = "card_call"
TITLE = "Call from their contact card: each number one press from ringing, or a text"

#: What a press says it was, and the use it counts.
HOW = {"call": "called", "text": "texted"}


def on(who=None) -> bool:
    from . import switches

    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def mark(block: dict, who=None) -> dict:
    """The contact block, marked callable when the switch is on and it has a number to ring."""
    if block.get("state") in ("unsaved", "declined"):
        return block
    if not any(r.get("kind") == "phone" and r.get("change") != "removed" for r in block.get("rows") or []):
        return block
    if on(who):
        block["call"] = True
    return block


def pressed(who, how: str) -> bool:
    """A Call or a Text pressed on a contact card: counted, when the switch is on."""
    from . import evolution

    if how not in HOW or not on(who):
        return False
    if how == "text":
        evolution.used("card_call", "texted", who=who, detail="Text from a contact card")
    else:
        evolution.used("card_call", "called", who=who, detail="Call from a contact card")
    return True


__all__ = ["HOW", "SWITCH", "TITLE", "mark", "on", "pressed"]
