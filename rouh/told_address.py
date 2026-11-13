"""A new address they told you: an email from a contact that says, in its words, that their email
address is now another one, told at once, with one press that puts it on their contact.

Built by the nightly feature run, night 42 of the ledger (13 November 2026, task 94).
People who change jobs or domains say so from the old address: "Please note my new email address is
dana@brightline.test", "from now on please write to me at ...". Night 40's A new address for a contact
sees only an email written *from* the new address; this one, written from the old, was said nothing
about, and the card went on holding the address that would bounce weeks later.

So, while its switch is on, when an email from a person reaches Rouh's inbox (`rouh/mail_alerts.py`)
and the sender is a contact (by the address it came from), Rouh reads the email's own words, quoted
replies and the signature left out, for an address announced as theirs (`announced`, plain rules, no
model): "my new (email) address is X", "my email is changing to X", "please use X from now on",
"write to me at X going forward", "you can reach me at X instead", and the Bulgarian "новият ми имейл
е X", "пишете ми на X". An address already on their contact, their own sender address, ‹his› own
mailboxes and a machine's address are never told. Then a notice says so: "Dana Reed says her new
address is dana@brightline.test; her contact has dana.reed@northwind.test." Its buttons:

- **Add it to their contact** puts the new address on the card in iCloud, labelled work;
- **Add it, take the old one off**, when the email came from an address on the card, also takes that
  address off, so the next email does not go to the one that will stop working.

A notice left alone changes nothing. The same address for the same contact is told once, ever.

**Whose.** The person's own contacts and notices, by `org_id` and `user_id`; what was told is kept in
`user_settings` (`told_address`), at most the last 200.

**Its switch** is `told_address` (`rouh/switches.py`): off, nothing is read and the buttons' address
says it is switched off.
"""
from __future__ import annotations

import email.utils
import hashlib
import json
import logging
import re
import time

log = logging.getLogger("rouh.told_address")

SWITCH = "told_address"
TITLE = "A new address they told you: an announced email address put on their contact in one press"

HELD = "told_address"
#: How many told addresses are kept, newest last.
KEPT = 200

_ADDRESS = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

#: Words before an address that make it the sender's new one.
_BEFORE = re.compile(
    r"(?:\bnew\s+(?:e-?mail|email|mail|work)?\s*(?:address|e-?mail|email)\b[^.\n]{0,30}\b(?:is|will be|:)"
    r"|\b(?:e-?mail|email|address)\b[^.\n]{0,20}\b(?:is changing|has changed|changes|will change|changed|"
    r"is moving|has moved|moved)\s+to"
    r"|\bfrom now on\b[^.\n]{0,40}\b(?:at|to|use)"
    r"|\bgoing forward\b[^.\n]{0,40}\b(?:at|to|use)"
    r"|\bplease\s+(?:use|update\b[^.\n]{0,40}\bto|write to me at|email me at|reach me at|contact me at)"
    r"|\b(?:новият|новия)\s+ми\s+(?:имейл|мейл|е-мейл|адрес)[^.\n]{0,20}\b(?:е|ще бъде)"
    r"|\b(?:пишете|пиши)\s+ми\s+(?:на|занапред на|вече на))\s*:?\s*$", re.I)

#: Words after an address that make it the sender's new one.
_AFTER = re.compile(r"^\W{0,3}\s*(?:from now on|going forward|from today|in future|in the future|instead|"
                    r"from (?:monday|next week|the \d+\w*)|занапред|от днес|вече)\b", re.I)
#: Words before an address that ask to be reached there (only with _AFTER).
_REACH = re.compile(r"\b(?:use|write to me at|email me at|reach me at|contact me at|at|to|на)\s*:?\s*$", re.I)

#: Where an email's own words end: a quoted reply, a forward, or the sign-off.
_QUOTE_HEAD = re.compile(r"^(?:on .{4,200} wrote:|-{2,}\s*(?:original|forwarded) message|from:\s|"
                         r"на .{4,120} написа:)", re.I)


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
    return "ta-" + hashlib.sha256(f"{contact_id}|{address.strip().lower()}".encode()).hexdigest()[:16]


def one(who, key: str) -> dict | None:
    got = _held(who).get(key)
    return got if isinstance(got, dict) else None


def mark(who, key: str, **fields) -> None:
    held = _held(who)
    if key in held:
        held[key] = dict(held[key], **fields)
        _put(who, held)


def own_words(body: str) -> str:
    """The email's own words: up to a quoted reply or a forward, with quoted lines left out."""
    out = []
    for line in str(body or "").splitlines():
        stripped = line.strip()
        if _QUOTE_HEAD.match(stripped):
            break
        if stripped.startswith(">"):
            continue
        out.append(line)
    return "\n".join(out)


def announced(body: str) -> list[str]:
    """The addresses the email's own words announce as the sender's new one, in order."""
    text = own_words(body)
    found: list[str] = []
    for m in _ADDRESS.finditer(text):
        address = m.group(0).strip(".").lower()
        start = text.rfind("\n\n", 0, m.start())
        before = text[max(start, m.start() - 160, 0):m.start()].replace("\n", " ")
        before = re.sub(r"[<(\[\"'“]+\s*$", "", before)
        after = text[m.end():m.end() + 40].replace("\n", " ")
        after = re.sub(r"^[>)\]\"'”]+", "", after)
        if _BEFORE.search(before) or (_AFTER.search(after) and _REACH.search(before)):
            if address not in found:
                found.append(address)
    return found


def _emails(card: dict) -> list[str]:
    from .same_contact import _emails as emails

    return emails(card)


def find(who, message: dict, own: list[str] = ()) -> tuple[dict | None, str, str]:
    """(the sender's contact, the new address they announce, the address it came from), or (None, "", "")."""
    from . import ghosts
    from .new_number import _contact_of, is_a_person

    if not is_a_person(message, own):
        return None, "", ""
    sender = (email.utils.parseaddr(message.get("from", ""))[1] or "").strip().lower()
    card = _contact_of(who, sender)
    if card is None:
        return None, "", ""
    mine = {str(a or "").strip().lower() for a in own}
    have = set(_emails(card))
    for address in announced(message.get("body") or ""):
        if address == sender or address in have or address in mine or ghosts.is_machine(address):
            continue
        return card, address, sender
    return None, "", ""


def sentence(card: dict, address: str, sender: str) -> str:
    name = card.get("name") or "They"
    have = _emails(card)
    text = f"{name} says their new address is {address}; their contact has "
    text += (", ".join(have[:2]) + "." if have else "no email address.")
    if sender in have:
        text += f" Their email came from {sender}, which may stop working."
    return text


async def seen(who, message: dict, *, mailbox: str = "", own: list[str] = ()) -> str:
    """An email from a contact announcing a new address, told: the sentence for the mail log, or "" when
    there is nothing to tell or the switch is off."""
    import asyncio

    from asgiref.sync import sync_to_async

    from . import evolution, notices

    if not await asyncio.to_thread(on, who):
        return ""
    card, address, sender = await sync_to_async(find)(who, message, list(own) + [mailbox])
    if card is None:
        return ""
    key = key_of(card["id"], address)
    held = await sync_to_async(_held)(who)
    if key in held:
        return ""
    name = card.get("name") or "They"
    text = sentence(card, address, sender)
    subject = str(message.get("subject") or "").strip()
    if subject:
        text += f" It was in their email “{subject[:80]}”."
    link = f"/mail/told-address/{key}"
    links = [{"label": "Add it to their contact", "href": link}]
    if sender in _emails(card):
        links.append({"label": f"Add it, take {sender} off", "href": link + "?replace=1"})
    said = await notices.notify(title=f"{name} has a new address", body=text, link=link,
                                link_label="Add it to their contact", links=links,
                                kind="mail", key=key, who=who)
    if said is None:
        return ""
    held[key] = {"contact": card["id"], "name": name, "address": address, "old": sender,
                 "at": time.time(), "added": False}
    await sync_to_async(_put)(who, held)
    await sync_to_async(evolution.used)(SWITCH, "told", who=who, detail=f"{name}: a new address announced")
    return f"{name} announced a new address, {address}: you were told in a notice."


async def add(who, key: str, desk, *, replace: bool = False) -> tuple[bool, str]:
    """Add it to their contact (and take the old one off), pressed: (done, what to say)."""
    from asgiref.sync import sync_to_async

    from . import evolution, notices

    told = await sync_to_async(one)(who, key)
    if told is None:
        return False, "That is not an address Rouh told you about."
    name, address, old = told.get("name") or "them", told.get("address") or "", told.get("old") or ""
    if told.get("added") and not (replace and not told.get("replaced")):
        return True, f"{address} is already on {name}'s contact."
    if desk is None:
        return False, "iCloud contacts are not connected, so the address could not be added."
    change = {"contact_id": told["contact"], "add_emails": [{"address": address, "label": "work"}]}
    if replace and old:
        change["remove_emails"] = [old]
    done = await desk.save(change, who)
    words = str(getattr(done, "text", "") or done)
    ok = words.startswith("Changed") or "already reads that way" in words
    if not ok:
        return False, words.split(" It reaches")[0][:300]
    await sync_to_async(mark)(who, key, added=True, replaced=bool(replace and old), added_at=time.time())
    if replace and old:
        await sync_to_async(evolution.used)(SWITCH, "replaced", who=who, detail=f"{name}: an announced address")
    else:
        await sync_to_async(evolution.used)(SWITCH, "added", who=who, detail=f"{name}: an announced address")
    said = f"Added {address} to {name}'s contact"
    said += f" and took {old} off." if replace and old else "."
    said += " It reaches your phone when it next syncs with iCloud."
    await notices.notify(title=f"{name}'s contact changed", body=said, kind="mail", key=key + "-added", who=who)
    return True, said


__all__ = ["HELD", "SWITCH", "TITLE", "add", "announced", "find", "key_of", "on", "one", "own_words", "seen",
           "sentence"]
