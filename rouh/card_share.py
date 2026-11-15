"""Send their contact card: a saved contact on a card in the chat is one press from going into any app
as a real contact card (a vCard), with their numbers, emails and addresses.

Built by the nightly feature run, night 44 of the ledger (15 November 2026, task 94).
Passing somebody's details on (to a colleague, an assistant, a friend) meant opening Contacts on the
phone, finding them again and pressing Share Contact, or copying the numbers out of Rouh one by one.
Nights 42 and 43 made a contact card's numbers one press from ringing and its addresses one press from
Maps (`rouh/card_call.py`, `rouh/card_directions.py`); this does the same for the card itself.

So, while its switch is on, a contact card that shows a saved iCloud contact as it is (show_contact, a
contact just saved) marks itself `share` (`mark`), and the page draws **Send their card** under it
(`contactShare` in `cards.js`). Pressing it fetches the contact's vCard from Rouh's own copy of the card
(`GET /api/contact-card/<id>`, `rouh/web/card_share.py`, scoped to the person, the photo left out so it
stays small), and on a phone hands it to the share sheet, so it goes into Telegram, Messages or Mail in
one more press; at a desk, where there is no share sheet for files, it downloads `<their name>.vcf`.
Rouh sends nothing itself. A contact not saved yet, turned down, or Rouh's own contact with no iCloud
card has no Send their card.

**Whose.** The person's own contacts, by `org_id` and `user_id`; nothing is kept but the count of uses
(`evolution.used`).

**Its switch** is `card_share` (`rouh/switches.py`): off, the card has no Send their card and the address
says it is switched off.
"""
from __future__ import annotations

import re

SWITCH = "card_share"
TITLE = "Send their contact card: a contact's vCard to any app in one press"

#: Lines of a vCard that are left out of the copy sent: the picture, as a page of base64.
_LEFT_OUT = ("PHOTO", "X-ABCROP-RECTANGLE")


def on(who=None) -> bool:
    from . import switches

    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def mark(block: dict, person=None, who=None) -> dict:
    """The contact block, marked for Send their card when the switch is on and it is a saved iCloud card."""
    if block.get("state") in ("unsaved", "declined") or not block.get("contact"):
        return block
    if person is not None and getattr(person, "card", None) is None:
        return block          # Rouh's own contact: there is no card on the phone to send
    if getattr(person, "is_me", False):
        return block
    if on(who):
        block["share"] = True
    return block


def _unfolded(text: str) -> list[str]:
    out: list[str] = []
    for line in str(text or "").replace("\r\n", "\n").split("\n"):
        if line[:1] in (" ", "\t") and out:
            out[-1] += line[1:]
        elif line:
            out.append(line)
    return out


def without_photo(text: str) -> str:
    """The vCard text with its picture left out, CRLF line ends as vCard wants."""
    keep = []
    for line in _unfolded(text):
        name = re.split(r"[;:]", line.split(".", 1)[-1] if re.match(r"^item\d+\.", line, re.I) else line, 1)[0]
        if name.upper() in _LEFT_OUT:
            continue
        keep.append(line)
    return "\r\n".join(keep) + "\r\n"


def file_name(name: str) -> str:
    clean = re.sub(r"[^\w .'-]+", "", str(name or ""), flags=re.UNICODE).strip() or "contact"
    return clean[:60] + ".vcf"


def card_for(who, contact_id: str) -> tuple[str, str] | None:
    """(the vCard text, the file name) of the person's own contact, or None. Counts the use. Synchronous:
    it reads the database."""
    from . import evolution
    from .synapse.sources import contacts

    if who is None or not on(who):
        return None
    card = contacts.one(str(who.user_id), str(who.org_id), contact_id)
    if card is None or not str(card.get("vcard") or "").strip():
        return None
    evolution.used(SWITCH, "sent", who=who, detail="Send their card from a contact card")
    return without_photo(str(card["vcard"])), file_name(card.get("name") or "")


__all__ = ["SWITCH", "TITLE", "card_for", "file_name", "mark", "on", "without_photo"]
