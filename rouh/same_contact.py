"""Contacts kept twice: the people who are in ‹his› contacts more than once, and what each card has.

Built by the nightly feature run, night 39 of the ledger (10 November 2026, task 94).
A contact saved from an email, another saved from a business card, a third that came with a phone
change: the same person ends up on two or three cards, one with the work number, one with the
mobile, one with the company. When that person rings, the phone shows whichever card it found
first, sometimes the one with no company; a search finds one card and misses what the other holds.
Asking Rouh "which of my contacts are there twice" could not be answered: search_contacts finds
people by words, at most 25, and never compares the cards with each other.

So, while its switch is on, the tool `same_contact` reads every card of ‹his› iCloud contacts (Rouh's
own copy in Synapse Master, `synapse/sources/contacts.all_cards`, the same one search_contacts reads)
and groups the cards that are one person:

- **the same address**: an email address on both;
- **the same number**: a phone number on both, by its last nine digits (`sig_phones.same`), a
  company's switchboard shared by several people aside (a number on three or more cards is a
  switchboard, not a person);
- **the same name**: the same words in the name, in any order, with accents and case aside, and
  nothing on the cards that says they are two people (two different companies).

Each group says what every card has (company, numbers, addresses), which card has the most, and what
the others hold that it lacks. Nothing is written here: the model offers to put the group together
as one card, with save_contact on the card that has the most and delete_contact on the rest, each
of which shows the person the contact first. No model is asked inside the tool.

**Whose.** The person's own contacts, by `org_id` and `user_id`.

**Its switch** is `same_contact` (`rouh/switches.py`): off, the tool says it is switched off.
"""
from __future__ import annotations

import logging
import unicodedata
from collections import defaultdict

log = logging.getLogger("rouh.same_contact")

SWITCH = "same_contact"
TITLE = "Contacts kept twice: the people who are in your contacts more than once, and what each card has"

#: How many groups are listed in one answer.
LISTED = 30
#: A number on this many cards or more is a switchboard, not a person.
SWITCHBOARD = 3

DESCRIPTION = (
    "Every person who is in the person's iCloud contacts more than once, counted from all of the "
    "contacts, not a search: cards sharing an email address, a phone number (a company switchboard "
    "aside) or the same name. Each group says what every card holds (company, numbers, addresses), "
    "which card has the most and what the others have that it lacks. Use it for 'which contacts do "
    "I have twice', 'duplicate contacts', 'clean up my contacts'. It changes nothing: offer to put "
    "a group together as one card, with save_contact on the card that has the most (adding what the "
    "others hold) and then delete_contact on each of the others, only for the groups the person says "
    "yes to.")


def on(who) -> bool:
    from . import switches

    if who is None:
        return False
    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def _plain(text: str) -> str:
    """Lower case, with accents taken off: "José Álvarez" is "jose alvarez"."""
    decomposed = unicodedata.normalize("NFKD", str(text or ""))
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


def name_key(name: str) -> str:
    """The words of a name in any order: "Reed, Dana" and "Dana Reed" are one."""
    words = sorted(w for w in "".join(c if c.isalnum() else " " for c in _plain(name)).split() if w)
    return " ".join(words) if len(words) >= 2 else ""


def _emails(card: dict) -> list[str]:
    return [str(e.get("address") if isinstance(e, dict) else e).strip().lower()
            for e in card.get("emails") or [] if "@" in str(e.get("address") if isinstance(e, dict) else e)]


def _phones(card: dict) -> list[str]:
    return [str(p.get("number") if isinstance(p, dict) else p).strip() for p in card.get("phones") or []
            if str(p.get("number") if isinstance(p, dict) else p).strip()]


def _tail(number: str) -> str:
    from .sig_phones import digits

    d = digits(number)
    return d[-9:] if len(d) >= 7 else ""


def _org(card: dict) -> str:
    return " ".join(str(card.get("organisation") or "").split())


def groups(cards: list[dict]) -> list[dict]:
    """The cards that are one person, each group with why: [{"cards": [...], "why": [...]}]."""
    cards = [c for c in cards if c.get("id")]
    parent = {c["id"]: c["id"] for c in cards}
    why: dict[str, set[str]] = defaultdict(set)

    def root(i: str) -> str:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def join(ids: list[str], because: str) -> None:
        ids = list(dict.fromkeys(ids))
        if len(ids) < 2:
            return
        first = root(ids[0])
        for other in ids[1:]:
            parent[root(other)] = first
        for one in ids:
            why[one].add(because)

    by_email, by_phone, by_name = defaultdict(list), defaultdict(list), defaultdict(list)
    for c in cards:
        for e in set(_emails(c)):
            by_email[e].append(c["id"])
        for t in {_tail(p) for p in _phones(c)} - {""}:
            by_phone[t].append(c["id"])
        key = name_key(c.get("name") or "")
        if key:
            by_name[key].append(c)
    for address, ids in by_email.items():
        join(ids, f"the same address, {address}")
    for tail, ids in by_phone.items():
        if len(set(ids)) < SWITCHBOARD:
            join(ids, "the same phone number")
    for _key, same in by_name.items():
        if len(same) < 2:
            continue
        companies = {_plain(_org(c)) for c in same if _org(c)}
        if len(companies) > 1:
            continue          # Two people with one name, at two companies.
        join([c["id"] for c in same], "the same name")
    out: dict[str, list[dict]] = defaultdict(list)
    for c in cards:
        out[root(c["id"])].append(c)
    found = []
    for members in out.values():
        if len(members) < 2:
            continue
        reasons = sorted({r for m in members for r in why[m["id"]]})
        found.append({"cards": members, "why": reasons})
    found.sort(key=lambda g: _plain(g["cards"][0].get("name") or ""))
    return found


def _richness(card: dict) -> tuple:
    return (bool(_org(card)), len(_phones(card)) + len(_emails(card)), bool(card.get("birthday")),
            len(card.get("note") or ""), float(card.get("changed_at") or 0))


def keeper(group: dict) -> dict:
    """The card that has the most: a company first, then the most numbers and addresses."""
    return max(group["cards"], key=_richness)


def lacks(keep: dict, other: dict) -> list[str]:
    """What `other` holds that `keep` does not."""
    from .sig_phones import same

    out = []
    if _org(other) and not _org(keep):
        out.append(f"company {_org(other)!r}")
    out += [f"number {p}" for p in _phones(other) if not any(same(p, k) for k in _phones(keep))]
    out += [f"address {e}" for e in _emails(other) if e not in _emails(keep)]
    if other.get("birthday") and not keep.get("birthday"):
        out.append(f"birthday {other['birthday']}")
    return out


def said(cards: list[dict], found: list[dict]) -> str:
    """The tool's answer."""
    if not cards:
        return "There are no contacts to read: iCloud contacts are not connected, or the address book is empty."
    if not found:
        return f"No one is in the contacts twice: each of the {len(cards)} contacts is a different person."
    extra = sum(len(g["cards"]) - 1 for g in found)
    out = [f"{len(found)} {'people are' if len(found) != 1 else 'person is'} in the contacts more than once "
           f"({extra} card{'s' if extra != 1 else ''} too many), of {len(cards)} contacts."]
    for g in found[:LISTED]:
        keep = keeper(g)
        out.append(f"\n{keep.get('name') or '(no name)'}: {len(g['cards'])} cards, {'; '.join(g['why'])}.")
        for c in g["cards"]:
            has = ", ".join(filter(None, [_org(c) and f"company {_org(c)!r}", ", ".join(_phones(c)[:3]),
                                          ", ".join(_emails(c)[:3])])) or "nothing but the name"
            if c is keep:
                out.append(f"- keep [contact id {c['id']}] {c.get('name') or '(no name)'}: {has}")
            else:
                more = lacks(keep, c)
                out.append(f"- [contact id {c['id']}] {c.get('name') or '(no name)'}: {has}"
                           + (f" -> adds {', '.join(more)}" if more else " -> nothing the first lacks"))
    if len(found) > LISTED:
        out.append(f"\nand {len(found) - LISTED} more.")
    out.append("\nSay how many people are there twice and who, plainly, with what the cards differ in. Offer "
               "to put each together as one card: save_contact on the card marked keep, adding what the "
               "others add, then delete_contact on each of the others, only for the people the person says "
               "yes to. Two cards with only the same name may be two people: ask before joining those.")
    return "\n".join(out)


def answer(who) -> str:
    """Everything the tool does, as `who`. Synchronous: it reads the database."""
    from . import evolution
    from .synapse.sources import contacts

    if not on(who):
        return "Contacts kept twice is switched off (Evolution, Mutations)."
    cards = contacts.all_cards(str(who.user_id), str(who.org_id))
    found = groups(cards)
    evolution.used(SWITCH, "asked", who=who, detail=f"{len(found)} people twice, of {len(cards)} contacts")
    return said(cards, found)


__all__ = ["DESCRIPTION", "SWITCH", "TITLE", "answer", "groups", "keeper", "lacks", "name_key", "on", "said"]
