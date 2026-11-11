"""Their card to pass on: a contact made into a card file (.vcf) to attach to an email, with only what
is meant to be passed on.

Built by the nightly feature run, night 40 of the ledger (11 November 2026, task 94).
Introducing somebody, passing on a supplier, giving a colleague the right person at a client: the
details go in an email, and the other side copies each field into their phone by hand. A card file
is one tap to save on any phone. Rouh could not make one: `send_mail` attaches files, but nothing
made a file of a contact. And the iCloud card itself must never go whole: ‹owner›'s contacts carry
private notes (an ЕГН, how ‹he› knows them), birthdays and photos.

So, while its switch is on, the tool `contact_card` takes one contact (by its id, or by name, found
among ‹his› iCloud contacts in Rouh's own copy, `synapse/sources/contacts`) and writes a vCard 3.0
file of it with the name, company, job title, phone numbers, email addresses and web address only,
each with its label. The notes, birthday, photo, postal addresses, related people, its iCloud id
and every other field are left out. The file is written under `/tmp` (`DIR`, a folder per person),
where `send_mail` and `draft_mail` may take a file from (`rouh/mailfiles.py`), and the model is told
to name it in `attachments`. Nothing is sent and nothing in the contacts changes.

No model is asked.

**Whose.** The person's own contacts, by `org_id` and `user_id`; the file is under a folder named
for the person's own id, and only the name of the contact is in its file name.

**Its switch** is `contact_card` (`rouh/switches.py`): off, the tool says it is switched off.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re

log = logging.getLogger("rouh.contact_card")

SWITCH = "contact_card"
TITLE = "Their card to pass on: a contact as a .vcf file to attach, without your notes"

#: Where the files are written: under /tmp, which an email may carry files from.
DIR = "/tmp/rouh-contact-cards"

#: The lines of a card that are passed on. Everything else stays behind.
KEPT = {"VERSION", "N", "FN", "ORG", "TITLE", "ROLE", "TEL", "EMAIL", "URL"}

#: The lines that are never passed on, said by name in the answer when the card had them.
LEFT_OUT = {"NOTE": "the notes", "BDAY": "the birthday", "PHOTO": "the photo", "ADR": "the postal addresses",
            "X-ABRELATEDNAMES": "the related people", "X-SOCIALPROFILE": "the social profiles",
            "NICKNAME": "the nickname", "X-ABDATE": "the dates"}

DESCRIPTION = (
    "Makes one of the person's contacts into a card file (.vcf), to attach to an email so the other "
    "side saves it on their phone in one tap: for 'send Ilina Dana's contact', 'introduce them and "
    "attach his card', 'pass on the supplier's details'. Give contact_id (from search_contacts) or "
    "name. Only the name, company, job title, phone numbers, email and web addresses go on it: the "
    "contact's notes, birthday, photo and postal addresses are left out. It sends nothing: name the "
    "path it gives in attachments of send_mail or draft_mail.")

SCHEMA = {"type": "object", "properties": {
    "contact_id": {"type": "string", "description": "The contact's id, as search_contacts gave it."},
    "name": {"type": "string", "description": "Or the contact's name, when there is no id."}}}


def on(who) -> bool:
    from . import switches

    if who is None:
        return False
    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def _plain(text: str) -> str:
    from .same_contact import _plain as plain

    return " ".join("".join(c if c.isalnum() else " " for c in plain(text)).split())


def find(cards: list[dict], *, contact_id: str = "", name: str = "") -> tuple[dict | None, list[dict]]:
    """(the card, []) when one is meant, (None, the cards it could be) when several, (None, []) for none."""
    said = str(contact_id or "").strip().lower()
    if said[:1] in ("c", "p") and said[1:].isdigit():      # c12, as search_contacts may write it
        said = said[1:]
    if said:
        got = next((c for c in cards if str(c.get("id")) == said), None)
        if got is not None:
            return got, []
    wanted = _plain(name)
    if not wanted:
        return None, []
    from .same_contact import name_key

    exact = [c for c in cards if _plain(c.get("name") or "") == wanted]
    if not exact and name_key(name):
        exact = [c for c in cards if name_key(c.get("name") or "") == name_key(name)]
    if len(exact) == 1:
        return exact[0], []
    if exact:
        return None, exact
    words = wanted.split()
    some = [c for c in cards if all(w in _plain(c.get("name") or "").split() for w in words)]
    if len(some) == 1:
        return some[0], []
    return None, some


def card_text(card: dict) -> tuple[str, list[str]]:
    """The card file's text, and what was left out of it, said as a person reads it."""
    from . import vcard

    left: list[str] = []
    raw = str(card.get("vcard") or "")
    try:
        whole = vcard.Card.parse(raw) if raw else None
    except vcard.BadField:
        whole = None
    if whole is not None:
        kept_groups = {p.group.lower() for p in whole.props if p.name in KEPT and p.group}
        props = []
        for p in whole.props:
            if p.name in KEPT and p.name != "VERSION":
                props.append(p)
            elif p.name == "X-ABLABEL" and p.group.lower() in kept_groups:
                props.append(p)
            elif p.name in LEFT_OUT and LEFT_OUT[p.name] not in left:
                left.append(LEFT_OUT[p.name])
        if not any(p.name == "FN" for p in props):
            props.insert(0, vcard.Prop(name="FN", value=vcard.escape(card.get("name") or ""), params=[]))
        out = vcard.Card([vcard.Prop(name="VERSION", value="3.0", params=[]), *props])
        return out.text(), left
    # No card text kept: made from what Rouh holds of the contact.
    lines = ["BEGIN:VCARD", "VERSION:3.0", "FN:" + vcard.escape(card.get("name") or "")]
    if card.get("organisation"):
        lines.append("ORG:" + vcard.escape(card["organisation"]))
    for p in card.get("phones") or []:
        number = str(p.get("number") if isinstance(p, dict) else p).strip()
        if number:
            kind = "CELL" if "mobile" in str((p.get("label") if isinstance(p, dict) else "") or "").lower() else "VOICE"
            lines.append(f"TEL;TYPE={kind}:{number}")
    for e in card.get("emails") or []:
        address = str(e.get("address") if isinstance(e, dict) else e).strip()
        if address:
            lines.append(f"EMAIL;TYPE=INTERNET:{address}")
    lines.append("END:VCARD")
    if card.get("note"):
        left.append("the notes")
    if card.get("birthday"):
        left.append("the birthday")
    return "".join(vcard.fold(line) + "\r\n" for line in lines), left


def file_name(name: str) -> str:
    plain = re.sub(r"[^\w .-]+", "", str(name or "").strip(), flags=re.UNICODE).strip(" .") or "Contact"
    return plain[:60] + ".vcf"


def write(who, card: dict) -> tuple[str, list[str]]:
    """The file written for `who`: (its path, what was left out)."""
    text, left = card_text(card)
    folder = os.path.join(DIR, hashlib.sha256(f"{who.org_id}|{who.user_id}".encode()).hexdigest()[:16])
    os.makedirs(folder, mode=0o700, exist_ok=True)
    path = os.path.join(folder, file_name(card.get("name") or ""))
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    os.chmod(path, 0o600)
    return path, left


def answer(who, args: dict) -> str:
    """Everything the tool does, as `who`. Synchronous: it reads the database and writes one file."""
    from . import evolution
    from .synapse.sources import contacts

    if not on(who):
        return "Their card to pass on is switched off (Evolution, Mutations)."
    cards = contacts.all_cards(str(who.user_id), str(who.org_id))
    if not cards:
        return "There are no contacts to read: iCloud contacts are not connected, or the address book is empty."
    card, could_be = find(cards, contact_id=str(args.get("contact_id") or ""), name=str(args.get("name") or ""))
    if card is None:
        if could_be:
            listed = "; ".join(f"{c.get('name')} ({c.get('organisation') or 'no company'}, contact id {c['id']})"
                               for c in could_be[:6])
            return f"Several contacts could be meant: {listed}. Ask which, then call contact_card with its contact_id."
        return "No contact by that name or id. Search for them with search_contacts first."
    path, left = write(who, card)
    evolution.used(SWITCH, "made", who=who, detail=f"{len(card.get('phones') or [])} numbers, "
                                                   f"{len(card.get('emails') or [])} addresses")
    has = ", ".join(filter(None, [card.get("organisation") and f"company {card['organisation']}",
                                  f"{len(card.get('phones') or [])} phone number(s)",
                                  f"{len(card.get('emails') or [])} email address(es)"]))
    out = (f"Made {card.get('name')}'s card, {os.path.basename(path)}, at {path}: the name, {has}. "
           + (f"Left out: {', '.join(left)}. " if left else "")
           + "Nothing was sent. To pass it on, call send_mail or draft_mail with this path in attachments; "
             "say whose card goes and that their private notes do not.")
    return out


__all__ = ["DESCRIPTION", "DIR", "SCHEMA", "SWITCH", "TITLE", "answer", "card_text", "find", "on", "write"]
