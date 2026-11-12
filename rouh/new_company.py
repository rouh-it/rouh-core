"""A new company in their signature: an email from a contact who now signs with a company their contact
does not say, told at once, with one press that changes it.

Built by the nightly feature run, night 41 of the ledger (12 November 2026, task 94).
People move jobs, and the first place the new employer shows is the signature under their next email.
‹owner›'s rule is that a contact's Company is always filled, because it is one of the few things ‹his›
phone shows when somebody rings; a company that is two jobs old is a call ‹he› places wrongly. Nobody
reads signatures against the address book: changing it meant opening the contact by hand. Night 39 did
this for a new number (`rouh/new_number.py`) and night 40 for a new address (`rouh/new_address.py`).

So, while its switch is on, when an email from a person reaches Rouh's inbox (`rouh/mail_alerts.py`),
Rouh reads the company in its signature (`company_in`, plain rules, no model): the lines under the
sender's own name, "Title, Company", "Title at Company", "Title | Company", or a job title on one
line and the company on the next. When the sender's contact (Rouh's copy of ‹his› iCloud contacts,
found by the address) says another company, or none, a notice says so there and then: "Nina Park now
signs as Head of Operations at Northwind; their contact says Brightline." Its button **Change it on
their contact** writes the new company to that contact in iCloud and says so in a notice of its own;
a notice left alone changes nothing. The same company for the same contact is told once, ever.

A sender who is no contact, a signature with no company found for certain, and a company the contact
already says (with "Ltd", "Inc" and the like aside, or one inside the other) are said nothing about;
so is mail from a machine, a list or ‹his› own address.

**Whose.** The person's own contacts and notices, by `org_id` and `user_id`; what was told is kept
in `user_settings` (`new_company`), at most the last 200.

**Its switch** is `new_company` (`rouh/switches.py`): off, nothing is read and the button's address
says it is switched off.
"""
from __future__ import annotations

import email.utils
import hashlib
import json
import logging
import re
import time
import unicodedata

log = logging.getLogger("rouh.new_company")

SWITCH = "new_company"
TITLE = "A new company in their signature: a contact's company changed in one press"

HELD = "new_company"
#: How many told companies are kept, newest last.
KEPT = 200

#: Words that make a line a job title rather than a company.
_TITLE_WORDS = re.compile(
    r"(?<![\w])(?:head|chief|ceo|cto|cfo|coo|cmo|cio|founder|co-founder|cofounder|owner|partner|director|manager|"
    r"lead|leader|officer|president|vp|vice|engineer|developer|designer|architect|analyst|consultant|advisor|"
    r"adviser|specialist|coordinator|assistant|associate|executive|administrator|accountant|lawyer|attorney|"
    r"counsel|editor|producer|researcher|scientist|professor|teacher|intern|representative|rep|sales|"
    r"marketing|operations|account|product|project|programme|program|managing|senior|junior|principal|"
    r"secretary|treasurer|chair|chairman|chairwoman|board|member|team|управител|директор|мениджър|"
    r"ръководител|съосновател|основател|консултант|асистент|инженер|адвокат|счетоводител)(?![\w])", re.I)

#: The endings a company's name is written with or without.
_ENDINGS = re.compile(
    r"\b(?:ltd|limited|inc|incorporated|llc|llp|plc|gmbh|ag|sa|sas|srl|bv|nv|oy|ab|as|ead|eood|ood|ad|"
    r"co|corp|corporation|company|group|holding|holdings|еад|еоод|оод|ад)\b\.?", re.I)

#: A line that is no title and no company: an address, a link, a number, a sign-off.
_NOT_TEXT = re.compile(r"@|https?:|www\.|\.(?:com|net|org|io|co|bg|eu|uk|de)\b|\d{4,}|^(?:t|m|p|tel|mob|"
                       r"phone|mobile|fax|e|email|w|web)\s*[.:]", re.I)

#: Where a title and a company are written on one line.
_SPLIT = re.compile(r"\s+(?:at|@|в)\s+(?=[A-ZА-Я0-9])|\s*[|·•]\s*|\s+[-–—]\s+|,\s+")

#: Sign-off words: never a company.
_SIGN_OFF = re.compile(r"^(?:best|regards|kind regards|thanks|thank you|cheers|sincerely|all the best|"
                       r"warm regards|поздрави|с уважение|благодаря)\b", re.I)


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


def same_company(a: str, b: str) -> bool:
    """Whether two ways of writing a company are the same one: endings and punctuation aside, or one in
    the other."""
    pa, pb = _plain(_ENDINGS.sub(" ", a)), _plain(_ENDINGS.sub(" ", b))
    if not pa or not pb:
        return False
    return pa == pb or f" {pa} " in f" {pb} " or f" {pb} " in f" {pa} "


def key_of(contact_id: str, company: str) -> str:
    return "nc-" + hashlib.sha256(f"{contact_id}|{_plain(company)}".encode()).hexdigest()[:16]


def one(who, key: str) -> dict | None:
    got = _held(who).get(key)
    return got if isinstance(got, dict) else None


def mark(who, key: str, **fields) -> None:
    held = _held(who)
    if key in held:
        held[key] = dict(held[key], **fields)
        _put(who, held)


def _is_text(line: str) -> bool:
    line = line.strip()
    if not 2 <= len(line) <= 80 or len(line.split()) > 9:
        return False
    if _NOT_TEXT.search(line) or _SIGN_OFF.match(line):
        return False
    return bool(re.search(r"[A-Za-zА-Яа-я]", line))


def _is_title(text: str) -> bool:
    return bool(_TITLE_WORDS.search(text))


def _name_line(lines: list[str], name: str) -> int:
    """Which line of the signature is the sender's own name, or -1."""
    words = [w for w in _plain(name).split() if len(w) > 1]
    if not words:
        return -1
    first, last = words[0], words[-1]
    for at, line in enumerate(lines):
        got = _plain(line).split()
        if not got or len(got) > 5:
            continue
        if first in got and (last in got or len(words) == 1):
            return at
    return -1


def company_in(body: str, name: str) -> tuple[str, str]:
    """(the job title, the company) the signature gives under the sender's name; ("", "") when it says no
    company for certain."""
    from .sig_phones import signature

    lines = [ln.strip() for ln in signature(body).splitlines()]
    at = _name_line(lines, name)
    if at < 0:
        return "", ""
    after = []
    for line in lines[at + 1:at + 5]:
        if not line:
            if after:
                break
            continue
        if not _is_text(line):
            break
        after.append(line)
    if not after:
        return "", ""
    first = after[0]
    parts = [p.strip(" ,.") for p in _SPLIT.split(first) if p and p.strip(" ,.")]
    if len(parts) >= 2 and _is_title(parts[0]) and not _is_title(parts[-1]):
        return parts[0], parts[-1]
    if _is_title(first):
        if len(after) > 1 and not _is_title(after[1]):
            return first, after[1].strip(" ,.")
        return first, ""
    if len(after) > 1 and _is_title(after[1]):
        return after[1], first.strip(" ,.")
    return "", ""


def _contact_of(who, address: str) -> dict | None:
    from .new_number import _contact_of as by_address

    return by_address(who, address)


def find(who, message: dict, own: list[str] = ()) -> tuple[dict | None, str, str]:
    """(the sender's contact, the title, the company in the signature it does not say), or (None, "", "")."""
    from .new_number import is_a_person

    if not is_a_person(message, own):
        return None, "", ""
    named, sender = email.utils.parseaddr(message.get("from", ""))
    card = _contact_of(who, (sender or "").strip().lower())
    if card is None:
        return None, "", ""
    title, company = company_in(message.get("body") or "", card.get("name") or named or "")
    if not company and named and named != card.get("name"):
        title, company = company_in(message.get("body") or "", named)
    if not company or same_company(company, card.get("organisation") or ""):
        return None, "", ""
    return card, title, company


async def seen(who, message: dict, *, mailbox: str = "", own: list[str] = ()) -> str:
    """An email from a contact whose signature names a company their contact does not, told: the sentence
    for the mail log, or "" when there is nothing to tell or the switch is off."""
    import asyncio

    from asgiref.sync import sync_to_async

    from . import evolution, notices

    if not await asyncio.to_thread(on, who):
        return ""
    card, title, company = await sync_to_async(find)(who, message, list(own) + [mailbox])
    if card is None:
        return ""
    key = key_of(card["id"], company)
    held = await sync_to_async(_held)(who)
    if key in held:
        return ""
    name = card.get("name") or (email.utils.parseaddr(message.get("from", ""))[0] or "").strip() or "They"
    was = (card.get("organisation") or "").strip()
    signs = f"{title} at {company}" if title else company
    text = (f"{name} now signs as {signs}; their contact says "
            + (f"{was}." if was else "no company."))
    subject = str(message.get("subject") or "").strip()
    if subject:
        text += f" It was under their email “{subject[:80]}”."
    link = f"/mail/new-company/{key}"
    said = await notices.notify(title=f"A new company for {name}", body=text, link=link,
                                link_label="Change it on their contact",
                                links=[{"label": "Change it on their contact", "href": link}],
                                kind="mail", key=key, who=who)
    if said is None:
        return ""
    held[key] = {"contact": card["id"], "name": name, "company": company, "title": title, "was": was,
                 "sender": (email.utils.parseaddr(message.get("from", ""))[1] or "").lower(),
                 "at": time.time(), "changed": False}
    await sync_to_async(_put)(who, held)
    await sync_to_async(evolution.used)(SWITCH, "told", who=who, detail=f"{name}: a new company")
    return f"{name}'s signature names {company}, not the company on their contact: you were told in a notice."


async def change(who, key: str, desk) -> tuple[bool, str]:
    """Change it on their contact, pressed: (done, what to say)."""
    from asgiref.sync import sync_to_async

    from . import evolution, notices

    told = await sync_to_async(one)(who, key)
    if told is None:
        return False, "That is not a company Rouh told you about."
    name, company = told.get("name") or "them", told.get("company") or ""
    if told.get("changed"):
        return True, f"{name}'s contact already says {company}."
    if desk is None:
        return False, "iCloud contacts are not connected, so the company could not be changed."
    done = await desk.save({"contact_id": told["contact"], "organisation": company}, who)
    words = str(getattr(done, "text", "") or done)
    ok = words.startswith("Changed") or "already reads that way" in words
    if not ok:
        return False, words.split(" It reaches")[0][:300]
    await sync_to_async(mark)(who, key, changed=True, changed_at=time.time())
    await sync_to_async(evolution.used)(SWITCH, "changed", who=who, detail=f"{name}: company changed")
    was = told.get("was") or ""
    said = (f"{name}'s contact now says {company}" + (f", not {was}" if was else "")
            + ". It reaches your phone when it next syncs with iCloud.")
    await notices.notify(title=f"Changed on {name}'s contact", body=said, kind="mail", key=key + "-changed",
                         who=who)
    return True, said


__all__ = ["HELD", "SWITCH", "TITLE", "change", "company_in", "find", "key_of", "on", "one", "same_company",
           "seen"]
