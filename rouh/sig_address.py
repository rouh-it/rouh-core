"""A new address in their signature: an email from a contact who now signs from a postal address their
contact does not have, told at once, with one press that puts it on their card.

Built by the nightly feature run, night 44 of the ledger (15 November 2026, task 94).
Offices move, and nobody writes to say so: the first place the new office shows is the address under
the sender's name in their next email. Night 43 made the card's postal address readable and writable
(`rouh/postal_address.py`, vCard's ADR), and nights 41 and 43 read a new company and a new job title out
of the signature; nobody read the address there against the one on the card, so a courier, a gift or a
visit went to an office they had left.

So, while its switch is on, when an email from a person reaches Rouh's inbox (`rouh/mail_alerts.py`),
Rouh reads the postal address in the sender's signature (`address_in`, plain rules, no model). When
their contact (Rouh's copy of ‹his› iCloud contacts, found by the address it came from) has a postal
address and the signature gives another one, at the same company (or with no company named), a notice
says so there and then: "Nina Park now signs from 40 Market Street, BS1 4DJ Bristol; their contact has
12 Old Road, BS2 0JA Bristol." Its buttons:

- **Add it to their contact** puts the new address on the card in iCloud, labelled work;
- **Add it, take the old one off**, when the card has one address, also takes that one off.

A notice left alone changes nothing. The same address for the same contact is told once, ever.
A card with no address is said nothing about (that would be every contact with a signature, once:
saving one from an email is Their address saved with them, `rouh/address_saved.py`), and so is a new
company, which night 41's gene tells. A sender who is no contact, and mail from a machine, a list or
‹his› own address, are said nothing about either.

`address_in` is also how Their address saved with them reads a new sender's address.

**Whose.** The person's own contacts and notices, by `org_id` and `user_id`; what was told is kept in
`user_settings` (`sig_address`), at most the last 200.

**Its switch** is `sig_address` (`rouh/switches.py`): off, nothing is read and the buttons' address
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

log = logging.getLogger("rouh.sig_address")

SWITCH = "sig_address"
TITLE = "A new address in their signature: a contact's postal address added in one press"

HELD = "sig_address"
#: How many told addresses are kept, newest last.
KEPT = 200

#: A word that makes a line a street, in the languages ‹his› mail comes in.
_STREET_WORD = (r"street|st|road|rd|avenue|ave|av|boulevard|blvd|bd|lane|ln|way|square|sq|place|pl|drive|dr|"
                r"court|ct|terrace|quay|wharf|row|close|crescent|parkway|highway|hwy|plaza|"
                r"strasse|straße|str|gasse|platz|weg|allee|ring|damm|rue|via|viale|piazza|calle|avenida|"
                r"plein|straat|gracht|laan|ulitsa|ul|bul|ул|бул|улица|булевард|пл|ж\.к")
#: "40 Market Street", "Suite 3, 221 Baker St."
_NUMBER_FIRST = re.compile(rf"\d+[a-zA-Z]?\b[\w .'/-]*?\b(?:{_STREET_WORD})\b\.?", re.I)
#: "Hauptstraße 5", "ul. Vitosha 12", "бул. Витоша 12", "Rue de Rivoli 10", "Keizersgracht 123".
_WORD_FIRST = re.compile(
    rf"(?:\b(?:{_STREET_WORD})\b\.?\s+[\w .'-]{{1,40}}?|\w{{2,}}(?:strasse|straße|gasse|platz|weg|allee|straat|"
    rf"gracht|laan))\s+\d+[a-zA-Z]?\b", re.I)
#: A postal code beside a city: UK's, five or four digits, the Dutch "1017 AB".
_UK_CODE = re.compile(r"\b([A-Z]{1,2}\d[A-Z\d]? ?\d[A-Z]{2})\b")
_DIGIT_CODE = re.compile(r"\b(\d{4,5}(?: ?[A-Z]{2}\b)?)\b")
#: What makes a line not part of an address.
_NOT_ADDRESS = re.compile(r"@|https?://|www\.|\b(?:tel|phone|mobile|mob|fax|cell|direct)\b\s*[.:]?|\b[mtfp]\s*:",
                          re.I)
#: Countries, as a signature ends with one.
COUNTRIES = {
    "uk": "United Kingdom", "united kingdom": "United Kingdom", "england": "United Kingdom",
    "usa": "United States", "us": "United States", "united states": "United States",
    "germany": "Germany", "deutschland": "Germany", "bulgaria": "Bulgaria", "българия": "Bulgaria",
    "france": "France", "netherlands": "Netherlands", "the netherlands": "Netherlands", "spain": "Spain",
    "italy": "Italy", "portugal": "Portugal", "ireland": "Ireland", "austria": "Austria",
    "switzerland": "Switzerland", "belgium": "Belgium", "poland": "Poland", "romania": "Romania",
    "greece": "Greece", "sweden": "Sweden", "denmark": "Denmark", "norway": "Norway", "finland": "Finland",
    "canada": "Canada", "australia": "Australia", "israel": "Israel", "turkey": "Turkey",
    "united arab emirates": "United Arab Emirates", "uae": "United Arab Emirates", "singapore": "Singapore",
}


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


def key_of(contact_id: str, line: str) -> str:
    return "sa-" + hashlib.sha256(f"{contact_id}|{_plain(line)}".encode()).hexdigest()[:16]


def one(who, key: str) -> dict | None:
    got = _held(who).get(key)
    return got if isinstance(got, dict) else None


def mark(who, key: str, **fields) -> None:
    held = _held(who)
    if key in held:
        held[key] = dict(held[key], **fields)
        _put(who, held)


def _is_street(text: str) -> bool:
    text = text.strip()
    return bool(_NUMBER_FIRST.fullmatch(text) or _WORD_FIRST.fullmatch(text)
                or _NUMBER_FIRST.match(text) or _WORD_FIRST.match(text))


def _town(text: str) -> tuple[str, str]:
    """(postal code, city) from a piece like "BS1 4DJ Bristol", "Bristol BS1 4DJ", "10115 Berlin", "Sofia 1000"."""
    text = " ".join(text.split()).strip(" ,.")
    for pattern in (_UK_CODE, _DIGIT_CODE):
        found = pattern.search(text)
        if found:
            city = (text[:found.start()] + " " + text[found.end():]).strip(" ,.-")
            city = " ".join(city.split())
            if city and not re.search(r"\d", city) and len(city.split()) <= 4:
                return found.group(1), city
    if re.fullmatch(r"[^\W\d_][^\d]{1,40}", text) and len(text.split()) <= 4:
        return "", text
    return "", ""


def _country(text: str) -> str:
    return COUNTRIES.get(" ".join(text.lower().split()).strip(" ,."), "")


def parse(pieces: list[str]) -> dict | None:
    """The parts of an address from its pieces in order (a street first), or None when it is not one for
    certain: a street and at least a city or a postal code."""
    pieces = [p.strip(" ,.;|") for p in pieces if p and p.strip(" ,.;|")]
    at = next((i for i, p in enumerate(pieces) if _is_street(p)), -1)
    if at < 0:
        return None
    street = pieces[at]
    code = city = country = region = ""
    for piece in pieces[at + 1:at + 5]:
        if not country and _country(piece):
            country = _country(piece)
            continue
        if city:
            if not region and re.fullmatch(r"[^\W\d_][^\d]{1,30}", piece) and len(piece.split()) <= 3:
                region = piece
            continue
        code, city = _town(piece)
        if not city and not code:
            # "Suite 300" after the street belongs to it.
            if re.match(r"(?:suite|floor|unit|apt|office|fl|ет|етаж|офис)\b", piece, re.I):
                street = f"{street}, {piece}"
                continue
            break
    if not city and not code:
        return None
    return {"street": street, "city": city, "region": region, "postal_code": code, "country": country}


def address_in(body: str, name: str = "") -> dict | None:
    """The postal address in the email's signature, as ADR's parts, or None. Plain rules, no model.

    Read from the signature (the last lines of the sender's own words); when `name` is given and found
    there, only what is under it. The address is one line split by commas or bars ("40 Market Street,
    Bristol BS1 4DJ, UK") or a street line with its town (and a country) on the lines after it."""
    from .new_company import _name_line
    from .sig_phones import signature

    lines = [ln.strip() for ln in signature(body or "").splitlines()]
    if name:
        at = _name_line(lines, name)
        if at >= 0:
            lines = lines[at + 1:]
    for i, line in enumerate(lines):
        if not line or _NOT_ADDRESS.search(line) or len(line) > 140:
            continue
        pieces = [p for p in re.split(r"\s*[,|·•]\s*|\s{3,}", line) if p.strip()]
        if not any(_is_street(p) for p in pieces):
            continue
        after = []
        for more in lines[i + 1:i + 4]:
            if not more or _NOT_ADDRESS.search(more):
                break
            after += [p for p in re.split(r"\s*[,|·•]\s*", more) if p.strip()]
        found = parse(pieces) or parse(pieces + after)
        if found is None:
            continue
        # A town on the line after a lone street is read, a second street is not.
        if not (found["city"] or found["postal_code"]):
            continue
        return found
    return None


def line_of(parts: dict) -> str:
    from . import vcard

    return vcard.address_line(parts)


def card_addresses(card: dict) -> list[dict]:
    """The postal addresses on a card of Rouh's copy, read from its own vCard text, whatever
    postal_address's switch."""
    from . import vcard

    try:
        return vcard.addresses_of(vcard.Card.parse(str(card.get("vcard") or "")))
    except vcard.BadField:
        return []


def _street_same(a: dict, b: dict) -> bool:
    from . import vcard

    return vcard.same_address(str(a.get("street") or ""), str(b.get("street") or ""))


def find(who, message: dict, own: list[str] = ()) -> tuple[dict | None, dict | None, list[dict]]:
    """(the sender's contact, the new address's parts, the addresses on the card), or (None, None, [])."""
    from . import new_company, vcard
    from .new_number import is_a_person

    if not is_a_person(message, own):
        return None, None, []
    named, sender = email.utils.parseaddr(message.get("from", ""))
    card = new_company._contact_of(who, (sender or "").strip().lower())
    if card is None:
        return None, None, []
    have = card_addresses(card)
    if not have:
        return None, None, []
    body = message.get("body") or ""
    parts = address_in(body, card.get("name") or named or "")
    if parts is None:
        return None, None, []
    line = line_of(parts)
    if any(vcard.same_address(line, h["address"]) or _street_same(parts, h.get("parts") or {}) for h in have):
        return None, None, []
    _title, company = new_company.company_in(body, card.get("name") or named or "")
    if company and not new_company.same_company(company, card.get("organisation") or ""):
        return None, None, []      # a new employer: night 41's gene tells that
    return card, parts, have


async def seen(who, message: dict, *, mailbox: str = "", own: list[str] = ()) -> str:
    """An email from a contact whose signature gives a postal address their card does not have, told: the
    sentence for the mail log, or "" when there is nothing to tell or the switch is off."""
    import asyncio

    from asgiref.sync import sync_to_async

    from . import evolution, notices

    if not await asyncio.to_thread(on, who):
        return ""
    card, parts, have = await sync_to_async(find)(who, message, list(own) + [mailbox])
    if card is None or parts is None:
        return ""
    line = line_of(parts)
    key = key_of(card["id"], line)
    held = await sync_to_async(_held)(who)
    if key in held:
        return ""
    name = card.get("name") or (email.utils.parseaddr(message.get("from", ""))[0] or "").strip() or "They"
    text = f"{name} now signs from {line}; their contact has " + "; ".join(h["address"] for h in have[:2]) + "."
    subject = str(message.get("subject") or "").strip()
    if subject:
        text += f" It was under their email “{subject[:80]}”."
    link = f"/mail/new-address-sig/{key}"
    links = [{"label": "Add it to their contact", "href": link}]
    if len(have) == 1:
        links.append({"label": "Add it, take the old one off", "href": link + "?replace=1"})
    said = await notices.notify(title=f"{name} signs from a new address", body=text, link=link,
                                link_label="Add it to their contact", links=links,
                                kind="mail", key=key, who=who)
    if said is None:
        return ""
    held[key] = {"contact": card["id"], "name": name, "parts": parts, "line": line,
                 "old": have[0]["address"] if len(have) == 1 else "",
                 "at": time.time(), "added": False}
    await sync_to_async(_put)(who, held)
    await sync_to_async(evolution.used)(SWITCH, "told", who=who, detail=f"{name}: a new postal address")
    return f"{name}'s signature gives {line}, not the address on their contact: you were told in a notice."


async def add(who, key: str, desk, *, replace: bool = False) -> tuple[bool, str]:
    """Add it to their contact (or Add it, take the old one off), pressed: (done, what to say)."""
    from asgiref.sync import sync_to_async

    from . import evolution, notices

    told = await sync_to_async(one)(who, key)
    if told is None:
        return False, "That is not an address Rouh told you about."
    name, line = told.get("name") or "them", told.get("line") or ""
    if told.get("added"):
        return True, f"{name}'s contact already has {line}."
    if desk is None:
        return False, "iCloud contacts are not connected, so the address could not be added."
    args = {"contact_id": told["contact"], "add_addresses": [dict(told.get("parts") or {}, label="work")]}
    old = told.get("old") or ""
    if replace and old:
        args["remove_addresses"] = [old]
    done = await desk.save(args, who)
    words = str(getattr(done, "text", "") or done)
    ok = words.startswith("Changed") or "already reads that way" in words
    if not ok:
        return False, words.split(" It reaches")[0][:300]
    await sync_to_async(mark)(who, key, added=True, added_at=time.time(), replaced=bool(replace and old))
    if replace and old:
        await sync_to_async(evolution.used)(SWITCH, "replaced", who=who,
                                            detail=f"{name}: a postal address added, the old one taken off")
    else:
        await sync_to_async(evolution.used)(SWITCH, "added", who=who, detail=f"{name}: a postal address added")
    said = f"{name}'s contact now has {line} as their work address"
    said += f", and {old} is off it." if replace and old else "."
    said += " It reaches your phone when it next syncs with iCloud."
    await notices.notify(title=f"{name}'s contact changed", body=said, kind="mail", key=key + "-added", who=who)
    return True, said


__all__ = ["COUNTRIES", "HELD", "SWITCH", "TITLE", "add", "address_in", "card_addresses", "find", "key_of",
           "line_of", "on", "one", "parse", "seen"]
