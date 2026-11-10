"""A new number in their signature: an email from a contact whose signature has a phone number their
contact does not, told at once, with one press that adds it.

Built by the nightly feature run, night 39 of the ledger (10 November 2026, task 94).
People change phones and jobs, and the first place a new number shows is the signature under their
next email. ‹owner›'s contacts are what ‹his› phone shows when they ring, so a number missing from a
contact is a call ‹he› will not recognise, or a call ‹he› cannot make from the car. Nobody reads
signatures against the address book: copying the number over meant opening the contact by hand.

So, while its switch is on, when an email from a person reaches Rouh's inbox (`rouh/mail_alerts.py`),
Rouh reads the phone numbers in its signature (`rouh/sig_phones.py`, plain rules, no model) and the
sender's contact in ‹his› iCloud contacts (Rouh's own copy in Synapse Master, found by the address).
A number the contact does not have, by its last nine digits, is told in a notice, there and then:
"Dana Reed's signature has +359 88 765 4321 (mobile), not on their contact, which has +44 20 7946
0000." Its button **Add it to their contact** adds the number to that contact in iCloud, with the
label the signature gave it, and says it was added in a notice of its own; a notice left alone
changes nothing. The same number for the same contact is told once, ever.

A sender who is no contact, or whose contact already has every number, is said nothing about; so is
mail from a machine, a list or ‹his› own address.

**Whose.** The person's own contacts and notices, by `org_id` and `user_id`; what was told is kept
in `user_settings` (`new_number`), at most the last 200.

**Its switch** is `new_number` (`rouh/switches.py`): off, nothing is read and the button's address
says it is switched off.
"""
from __future__ import annotations

import email.utils
import hashlib
import json
import logging
import time

log = logging.getLogger("rouh.new_number")

SWITCH = "new_number"
TITLE = "A new number in their signature: a phone number a contact does not have, added in one press"

HELD = "new_number"
#: How many told numbers are kept, newest last.
KEPT = 200


def on(who) -> bool:
    from . import switches

    if who is None:
        return False
    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def _ids(who) -> tuple[str, str]:
    return str(getattr(who, "user_id", "") or ""), str(getattr(who, "org_id", "") or "")


def _held(who) -> dict:
    from .models import UserSetting

    user_id, org_id = _ids(who)
    value = (UserSetting.objects.filter(user_id=user_id, org_id=org_id, name=HELD)
             .values_list("value", flat=True).first())
    try:
        held = json.loads(value) if value else {}
    except (TypeError, ValueError):
        held = {}
    return held if isinstance(held, dict) else {}


def _put(who, held: dict) -> None:
    from .models import UserSetting

    user_id, org_id = _ids(who)
    if len(held) > KEPT:
        held = dict(sorted(held.items(), key=lambda kv: kv[1].get("at") or 0)[-KEPT:])
    UserSetting.objects.bulk_create(
        [UserSetting(user_id=user_id, org_id=org_id, name=HELD, value=json.dumps(held), updated_at=time.time())],
        update_conflicts=True, unique_fields=["user_id", "name"], update_fields=["org_id", "value", "updated_at"])


def key_of(contact_id: str, number: str) -> str:
    from .sig_phones import digits

    return "nn-" + hashlib.sha256(f"{contact_id}|{digits(number)[-9:]}".encode()).hexdigest()[:16]


def one(who, key: str) -> dict | None:
    got = _held(who).get(key)
    return got if isinstance(got, dict) else None


def mark(who, key: str, **fields) -> None:
    held = _held(who)
    if key in held:
        held[key] = dict(held[key], **fields)
        _put(who, held)


def _contact_of(who, address: str) -> dict | None:
    """The sender's contact, by an address on it; None when they are nobody's contact."""
    from .synapse.sources import contacts

    user_id, org_id = _ids(who)
    address = address.strip().lower()
    for card in contacts.all_cards(user_id, org_id):
        for e in card.get("emails") or []:
            if str(e.get("address") if isinstance(e, dict) else e).strip().lower() == address:
                return card
    return None


def _numbers(card: dict) -> list[str]:
    return [str(p.get("number") if isinstance(p, dict) else p) for p in card.get("phones") or []]


def missing(card: dict, body: str) -> list[str]:
    """The signature's numbers the contact does not have."""
    from .sig_phones import phones, same

    have = _numbers(card)
    return [n for n in phones(body) if not any(same(n, h) for h in have)]


def is_a_person(message: dict, own: list[str] = ()) -> bool:
    from . import ghosts

    sender = (email.utils.parseaddr(message.get("from", ""))[1] or "").strip().lower()
    if not sender or "@" not in sender or ghosts.is_machine(sender):
        return False
    if sender in {str(a or "").lower() for a in own}:
        return False
    named = {"auto-submitted": message.get("auto_submitted") or "",
             "precedence": message.get("precedence") or "", "subject": message.get("subject") or ""}
    if ghosts.is_auto_reply(named) or str(message.get("precedence") or "").lower() in ("bulk", "list", "junk"):
        return False
    return not message.get("list_unsubscribe") and not message.get("list_id")


def find(who, message: dict, own: list[str] = ()) -> tuple[dict | None, list[str]]:
    """(the sender's contact, the numbers in the signature it does not have), or (None, [])."""
    if not is_a_person(message, own):
        return None, []
    sender = (email.utils.parseaddr(message.get("from", ""))[1] or "").strip().lower()
    card = _contact_of(who, sender)
    if card is None:
        return None, []
    return card, missing(card, message.get("body") or "")


async def seen(who, message: dict, *, mailbox: str = "", own: list[str] = ()) -> str:
    """An email from a contact whose signature has a number their contact lacks, told: the sentence for
    the mail log, or "" when there is nothing to tell or the switch is off."""
    import asyncio

    from asgiref.sync import sync_to_async

    from . import evolution, notices
    from .sig_phones import label_for

    if not await asyncio.to_thread(on, who):
        return ""
    card, new = await sync_to_async(find)(who, message, list(own) + [mailbox])
    if card is None or not new:
        return ""
    held = await sync_to_async(_held)(who)
    number = next((n for n in new if key_of(card["id"], n) not in held), "")
    if not number:
        return ""
    label = label_for(message.get("body") or "", number)
    name = card.get("name") or (email.utils.parseaddr(message.get("from", ""))[0] or "").strip() or "They"
    have = _numbers(card)
    text = (f"{name}'s signature has {number} ({label}), not on their contact"
            + (f", which has {', '.join(have[:2])}." if have else ", which has no number."))
    subject = str(message.get("subject") or "").strip()
    if subject:
        text += f" It was under their email “{subject[:80]}”."
    key = key_of(card["id"], number)
    link = f"/mail/new-number/{key}"
    title = f"A new number for {name}"
    said = await notices.notify(title=title, body=text, link=link, link_label="Add it to their contact",
                                links=[{"label": "Add it to their contact", "href": link}],
                                kind="mail", key=key, who=who)
    if said is None:
        return ""
    held[key] = {"contact": card["id"], "name": name, "number": number, "label": label,
                 "sender": (email.utils.parseaddr(message.get("from", ""))[1] or "").lower(),
                 "at": time.time(), "added": False}
    await sync_to_async(_put)(who, held)
    await sync_to_async(evolution.used)(SWITCH, "told", who=who, detail=f"{name}: a {label} number")
    return f"{name}'s signature has a number their contact does not ({number}): you were told in a notice."


async def add(who, key: str, desk) -> tuple[bool, str]:
    """Add It to their contact, pressed: (done, what to say)."""
    from asgiref.sync import sync_to_async

    from . import evolution, notices

    told = await sync_to_async(one)(who, key)
    if told is None:
        return False, "That is not a number Rouh told you about."
    name, number = told.get("name") or "them", told.get("number") or ""
    if told.get("added"):
        return True, f"{number} is already on {name}'s contact."
    if desk is None:
        return False, "iCloud contacts are not connected, so the number could not be added."
    done = await desk.save({"contact_id": told["contact"],
                            "add_phones": [{"number": number, "label": told.get("label") or "work"}]}, who)
    words = str(getattr(done, "text", "") or done)
    ok = words.startswith("Changed") or "already reads that way" in words
    if not ok:
        return False, words.split(" It reaches")[0][:300]
    await sync_to_async(mark)(who, key, added=True, added_at=time.time())
    await sync_to_async(evolution.used)(SWITCH, "added", who=who, detail=f"{name}: a {told.get('label')} number")
    said = f"Added {number} to {name}'s contact. It reaches your phone when it next syncs with iCloud."
    await notices.notify(title=f"Added to {name}'s contact", body=said, kind="mail", key=key + "-added", who=who)
    return True, said


__all__ = ["HELD", "SWITCH", "TITLE", "add", "find", "is_a_person", "key_of", "missing", "on", "one", "seen"]
