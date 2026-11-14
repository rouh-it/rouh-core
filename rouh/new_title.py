"""A new job title in their signature: an email from a contact who now signs with a job title their
contact does not say, told at once, with one press that changes it.

Built by the nightly feature run, night 43 of the ledger (14 November 2026, task 94).
People are promoted and change roles without changing employer, and the first place the new role shows
is the signature under their next email. Night 41's A new company in their signature (`rouh/new_company.py`)
tells a new employer, and reads the title beside it only to drop it; night 42's A contact's job title
(`rouh/job_title.py`) made the card's Job title readable and writable. Nobody read the two against
each other, so a card kept saying "Operations Manager" for somebody who has run the department for a year.

So, while its switch is on, when an email from a person reaches Rouh's inbox (`rouh/mail_alerts.py`),
Rouh reads the job title under the sender's own name in its signature (`new_company.company_in`, plain
rules, no model). When their contact (Rouh's copy of ‹his› iCloud contacts, found by the address) holds a
job title and the signature gives another one, at the same company (or with no company on either side), a
notice says so there and then: "Nina Park now signs as Head of Operations; their contact says Operations
Manager." Its button **Change it on their contact** writes the new title to that contact in iCloud and
says so in a notice of its own; a notice left alone changes nothing. The same title for the same contact
is told once, ever.

A card with no job title is said nothing about (that would be every contact with a signature, once), and
so is a new company: night 41's gene tells that. A sender who is no contact, and mail from a machine, a
list or ‹his› own address, are said nothing about either.

**Whose.** The person's own contacts and notices, by `org_id` and `user_id`; what was told is kept in
`user_settings` (`new_title`), at most the last 200.

**Its switch** is `new_title` (`rouh/switches.py`): off, nothing is read and the button's address says it is
switched off.
"""
from __future__ import annotations

import email.utils
import hashlib
import json
import logging
import re
import time
import unicodedata

log = logging.getLogger("rouh.new_title")

SWITCH = "new_title"
TITLE = "A new job title in their signature: a contact's job title changed in one press"

HELD = "new_title"
#: How many told titles are kept, newest last.
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


def _plain(text: str) -> str:
    text = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode() or str(text or "")
    return " ".join(re.findall(r"\w+", text.lower()))


def same_title(a: str, b: str) -> bool:
    """Whether two ways of writing a job title are the same one: case, accents, punctuation and "&" for
    "and" aside."""
    def clean(text: str) -> str:
        return _plain(str(text or "").replace("&", " and "))
    return bool(clean(a)) and clean(a) == clean(b)


def key_of(contact_id: str, title: str) -> str:
    return "nt-" + hashlib.sha256(f"{contact_id}|{_plain(title)}".encode()).hexdigest()[:16]


def one(who, key: str) -> dict | None:
    got = _held(who).get(key)
    return got if isinstance(got, dict) else None


def mark(who, key: str, **fields) -> None:
    held = _held(who)
    if key in held:
        held[key] = dict(held[key], **fields)
        _put(who, held)


def card_title(card: dict) -> str:
    """The job title on a card of Rouh's copy, read from its own vCard text, whatever job_title's switch."""
    from . import vcard

    try:
        return " ".join(vcard.Card.parse(str(card.get("vcard") or "")).value("TITLE").split())
    except vcard.BadField:
        return ""


def find(who, message: dict, own: list[str] = ()) -> tuple[dict | None, str, str]:
    """(the sender's contact, the title in the signature, the title on the card), or (None, "", "")."""
    from . import new_company
    from .new_number import is_a_person

    if not is_a_person(message, own):
        return None, "", ""
    named, sender = email.utils.parseaddr(message.get("from", ""))
    card = new_company._contact_of(who, (sender or "").strip().lower())
    if card is None:
        return None, "", ""
    body = message.get("body") or ""
    title, company = new_company.company_in(body, card.get("name") or named or "")
    if not title and named and named != card.get("name"):
        title, company = new_company.company_in(body, named)
    title = " ".join(str(title or "").split()).strip(" ,.")
    was = card_title(card)
    if not title or not was or same_title(title, was) or len(title) > 80:
        return None, "", ""
    org = str(card.get("organisation") or "")
    if company and not new_company.same_company(company, org):
        return None, "", ""          # a new employer: night 41's gene tells that
    if not company and org and not re.search(re.escape(_plain(org)), _plain(body)):
        return None, "", ""          # no company beside it, and the card's is nowhere in the email
    return card, title, was


async def seen(who, message: dict, *, mailbox: str = "", own: list[str] = ()) -> str:
    """An email from a contact whose signature gives a job title their contact does not, told: the sentence
    for the mail log, or "" when there is nothing to tell or the switch is off."""
    import asyncio

    from asgiref.sync import sync_to_async

    from . import evolution, notices

    if not await asyncio.to_thread(on, who):
        return ""
    card, title, was = await sync_to_async(find)(who, message, list(own) + [mailbox])
    if card is None:
        return ""
    key = key_of(card["id"], title)
    held = await sync_to_async(_held)(who)
    if key in held:
        return ""
    name = card.get("name") or (email.utils.parseaddr(message.get("from", ""))[0] or "").strip() or "They"
    text = f"{name} now signs as {title}; their contact says {was}."
    subject = str(message.get("subject") or "").strip()
    if subject:
        text += f" It was under their email “{subject[:80]}”."
    link = f"/mail/new-title/{key}"
    said = await notices.notify(title=f"A new job title for {name}", body=text, link=link,
                                link_label="Change it on their contact",
                                links=[{"label": "Change it on their contact", "href": link}],
                                kind="mail", key=key, who=who)
    if said is None:
        return ""
    held[key] = {"contact": card["id"], "name": name, "title": title, "was": was,
                 "sender": (email.utils.parseaddr(message.get("from", ""))[1] or "").lower(),
                 "at": time.time(), "changed": False}
    await sync_to_async(_put)(who, held)
    await sync_to_async(evolution.used)(SWITCH, "told", who=who, detail=f"{name}: a new job title")
    return f"{name}'s signature gives {title}, not the job title on their contact: you were told in a notice."


async def change(who, key: str, desk) -> tuple[bool, str]:
    """Change it on their contact, pressed: (done, what to say)."""
    from asgiref.sync import sync_to_async

    from . import evolution, notices

    told = await sync_to_async(one)(who, key)
    if told is None:
        return False, "That is not a job title Rouh told you about."
    name, title = told.get("name") or "them", told.get("title") or ""
    if told.get("changed"):
        return True, f"{name}'s contact already says {title}."
    if desk is None:
        return False, "iCloud contacts are not connected, so the job title could not be changed."
    done = await desk.save({"contact_id": told["contact"], "title": title}, who)
    words = str(getattr(done, "text", "") or done)
    ok = words.startswith("Changed") or "already reads that way" in words
    if not ok:
        return False, words.split(" It reaches")[0][:300]
    await sync_to_async(mark)(who, key, changed=True, changed_at=time.time())
    await sync_to_async(evolution.used)(SWITCH, "changed", who=who, detail=f"{name}: job title changed")
    was = told.get("was") or ""
    said = (f"{name}'s contact now says {title}" + (f", not {was}" if was else "")
            + ". It reaches your phone when it next syncs with iCloud.")
    await notices.notify(title=f"Changed on {name}'s contact", body=said, kind="mail", key=key + "-changed",
                         who=who)
    return True, said


__all__ = ["HELD", "SWITCH", "TITLE", "card_title", "change", "find", "key_of", "on", "one", "same_title", "seen"]
