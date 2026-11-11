"""A new address for a contact: an email from somebody in ‹his› contacts, written from an address that
is on none of their cards, told at once, with one press that adds it to their contact.

Built by the nightly feature run, night 40 of the ledger (11 November 2026, task 94).
People change jobs, and companies change domains. The first email from a person's new address is a
stranger to Rouh: every contact lookup goes by address (who they are, How you know them, A new number
in their signature), so none of them knows it is Dana Reed, and Save them as a contact (night 39)
would offer a second card for her. ‹owner› did not change her address and nobody told ‹him›; the
card goes on holding the old one, and the next search by address finds nobody.

So, while its switch is on, when an email from a person reaches Rouh's inbox (`rouh/mail_alerts.py`),
and its address is on none of ‹his› iCloud contacts (Rouh's own copy in Synapse Master), Rouh looks
for a contact with the sender's name: the same words, in any order, with accents and case aside
(`same_contact.name_key`), and exactly one card with it, so two people of one name are never mixed
up. Then a notice says so, there and then: "Dana Reed wrote from dana@brightline.test, which is not
on her contact; the contact has dana.reed@northwind.test (Northwind). A new company?" Its button
**Add it to their contact** adds the address to that card in iCloud, labelled work, and says so in a
notice of its own. A notice left alone changes nothing. The same address for the same contact is
told once, ever.

Mail from a machine, a list or ‹his› own address, from somebody whose name is on no card or on
several, or whose name is one word, is said nothing about.

No model is asked.

**Whose.** The person's own contacts and notices, by `org_id` and `user_id`; what was told is kept in
`user_settings` (`new_address`), at most the last 200.

**Its switch** is `new_address` (`rouh/switches.py`): off, nothing is read and the button's address
says it is switched off.
"""
from __future__ import annotations

import email.utils
import hashlib
import json
import logging
import time

log = logging.getLogger("rouh.new_address")

SWITCH = "new_address"
TITLE = "A new address for a contact: a contact writing from an address not on their card, added in one press"

HELD = "new_address"
#: How many told addresses are kept, newest last.
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


def key_of(contact_id: str, address: str) -> str:
    return "na-" + hashlib.sha256(f"{contact_id}|{address.strip().lower()}".encode()).hexdigest()[:16]


def one(who, key: str) -> dict | None:
    got = _held(who).get(key)
    return got if isinstance(got, dict) else None


def mark(who, key: str, **fields) -> None:
    held = _held(who)
    if key in held:
        held[key] = dict(held[key], **fields)
        _put(who, held)


def _emails(card: dict) -> list[str]:
    from .same_contact import _emails as emails

    return emails(card)


def match(cards: list[dict], name: str, address: str) -> dict | None:
    """The one card that is this sender by name, when the address is on no card; else None."""
    from .same_contact import name_key

    address = address.strip().lower()
    if any(address in _emails(c) for c in cards):
        return None
    wanted = name_key(name)
    if not wanted:
        return None
    named = [c for c in cards if name_key(c.get("name") or "") == wanted]
    return named[0] if len(named) == 1 else None


def find(who, message: dict, own: list[str] = ()) -> tuple[dict | None, str, str]:
    """(their contact, the new address, the name it came under), or (None, "", "")."""
    from .new_number import is_a_person
    from .synapse.sources import contacts

    if not is_a_person(message, own):
        return None, "", ""
    name, address = email.utils.parseaddr(message.get("from", ""))
    address, name = (address or "").strip().lower(), (name or "").strip().strip('"')
    if not name or "@" not in address:
        return None, "", ""
    user_id, org_id = _ids(who)
    card = match(contacts.all_cards(user_id, org_id), name, address)
    return (card, address, name) if card else (None, "", "")


def sentence(card: dict, address: str) -> str:
    name = card.get("name") or "They"
    have = _emails(card)
    org = str(card.get("organisation") or "").strip()
    text = f"{name} wrote from {address}, which is not on their contact"
    if have:
        text += f"; the contact has {', '.join(have[:2])}" + (f" ({org})" if org else "") + "."
    else:
        text += ", which has no email address" + (f" ({org})" if org else "") + "."
    old = {a.split("@", 1)[1] for a in have if "@" in a}
    if old and address.split("@", 1)[1] not in old:
        text += " A new company, perhaps: check the company on their contact too."
    return text


async def seen(who, message: dict, *, mailbox: str = "", own: list[str] = ()) -> str:
    """An email from a contact at an address not on their card, told: the sentence for the mail log, or ""
    when there is nothing to tell or the switch is off."""
    import asyncio

    from asgiref.sync import sync_to_async

    from . import evolution, notices

    if not await asyncio.to_thread(on, who):
        return ""
    card, address, came_as = await sync_to_async(find)(who, message, list(own) + [mailbox])
    if card is None:
        return ""
    key = key_of(card["id"], address)
    held = await sync_to_async(_held)(who)
    if key in held:
        return ""
    name = card.get("name") or came_as
    text = sentence(card, address)
    subject = str(message.get("subject") or "").strip()
    if subject:
        text += f" It was their email “{subject[:80]}”."
    link = f"/mail/new-address/{key}"
    said = await notices.notify(title=f"A new address for {name}", body=text, link=link,
                                link_label="Add it to their contact",
                                links=[{"label": "Add it to their contact", "href": link}],
                                kind="mail", key=key, who=who)
    if said is None:
        return ""
    held[key] = {"contact": card["id"], "name": name, "address": address, "at": time.time(), "added": False}
    await sync_to_async(_put)(who, held)
    await sync_to_async(evolution.used)(SWITCH, "told", who=who, detail=f"{name}: a new address")
    return f"{name} wrote from {address}, which is not on their contact: you were told in a notice."


async def add(who, key: str, desk) -> tuple[bool, str]:
    """Add it to their contact, pressed: (done, what to say)."""
    from asgiref.sync import sync_to_async

    from . import evolution, notices

    told = await sync_to_async(one)(who, key)
    if told is None:
        return False, "That is not an address Rouh told you about."
    name, address = told.get("name") or "them", told.get("address") or ""
    if told.get("added"):
        return True, f"{address} is already on {name}'s contact."
    if desk is None:
        return False, "iCloud contacts are not connected, so the address could not be added."
    done = await desk.save({"contact_id": told["contact"],
                            "add_emails": [{"address": address, "label": "work"}]}, who)
    words = str(getattr(done, "text", "") or done)
    ok = words.startswith("Changed") or "already reads that way" in words
    if not ok:
        return False, words.split(" It reaches")[0][:300]
    await sync_to_async(mark)(who, key, added=True, added_at=time.time())
    await sync_to_async(evolution.used)(SWITCH, "added", who=who, detail=f"{name}: a new address")
    said = f"Added {address} to {name}'s contact. It reaches your phone when it next syncs with iCloud."
    await notices.notify(title=f"Added to {name}'s contact", body=said, kind="mail", key=key + "-added", who=who)
    return True, said


__all__ = ["HELD", "SWITCH", "TITLE", "add", "find", "key_of", "match", "on", "one", "seen", "sentence"]
