"""Contacts with no company: every contact whose Company is empty, with what it should say.

Built by the nightly feature run, night 38 of the ledger (9 November 2026, task 94).
The Company field is the one a phone shows under a name when it rings, so ‹owner› fills it for every
contact: the company, or for somebody with none a few words saying who they are. Contacts made in a
hurry, from a business card, from a meeting, from a phone call, are left without it, and the phone
then rings with a name ‹he› may not place. Asking Rouh "which of my contacts have no company" could not
be answered: search_contacts finds people by words, at most 25, and never by a field that is empty.

So, while its switch is on, the tool `no_company` reads every card of ‹his› iCloud contacts (Rouh's
own copy in Synapse Master, `synapse/sources/contacts.all_cards`, the same one search_contacts reads),
and lists those whose organisation is empty, each with what it should most likely say:

- **from another contact at the same company**: a work address whose domain other contacts share, and
  those contacts have a company: that company, the one most of them have;
- **from their address**: a work domain no other contact has, read as a name ("northwind.test" is
  "Northwind"), said as a guess;
- **who they are to you**: a personal address or none, where Rouh's own note of who they are to ‹him›
  is offered when it has one, and otherwise nothing is guessed.

Nothing is written here. The model offers the list and fills the ones ‹he› says yes to with
save_contact, which shows each contact before it saves. No model is asked inside the tool.

**Whose.** The person's own contacts, by `org_id` and `user_id`.

**Its switch** is `no_company` (`rouh/switches.py`): off, the tool says it is switched off.
"""
from __future__ import annotations

import logging
from collections import Counter

log = logging.getLogger("rouh.no_company")

SWITCH = "no_company"
TITLE = "Contacts with no company: every contact whose Company is empty, with what it should say"

#: How many contacts are listed in one answer, of each kind.
LISTED = 40

DESCRIPTION = (
    "Every one of the person's iCloud contacts whose Company (organisation) is empty, counted from all "
    "of them, not a search: the Company field is what the phone shows when they call, so the person "
    "fills it for everybody (a company, or for somebody with none a few words on who they are). Each "
    "comes with what it should most likely say: from another contact at the same company, guessed from "
    "a work address, or for a personal contact what Rouh knows of who they are. Use it for 'which "
    "contacts have no company', 'clean up my contacts' companies'. It changes nothing: offer to fill "
    "the ones the person says yes to, each with save_contact (its contact id and organisation).")


def on(who) -> bool:
    from . import switches

    if who is None:
        return False
    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def _work_domain(address: str) -> str:
    from .meeting_hours import FREE_MAIL

    domain = str(address or "").strip().lower().rpartition("@")[2]
    return "" if not domain or "." not in domain or domain in FREE_MAIL else domain


def name_of(domain: str) -> str:
    """A company's likely name from its domain: "mail.northwind-labs.co.uk" is "Northwind Labs"."""
    parts = [p for p in str(domain or "").lower().split(".") if p]
    if len(parts) >= 3 and parts[-2] in ("co", "com", "org", "net", "ac", "gov") and len(parts[-1]) == 2:
        parts = parts[:-2]
    elif len(parts) >= 2:
        parts = parts[:-1]
    core = parts[-1] if parts else ""
    return " ".join(w.capitalize() for w in core.replace("_", "-").split("-") if w)


def read(cards: list[dict], notes: dict[str, str]) -> dict:
    """The contacts with no company, sorted into what can fill them. `notes` is Rouh's own note of who
    each is to the person, by contact id."""
    by_domain: dict[str, Counter] = {}
    for card in cards:
        org = " ".join(str(card.get("organisation") or "").split())
        if not org:
            continue
        for e in card.get("emails") or []:
            domain = _work_domain(e.get("address") if isinstance(e, dict) else e)
            if domain:
                by_domain.setdefault(domain, Counter())[org] += 1
    same, guessed, personal = [], [], []
    for card in cards:
        if " ".join(str(card.get("organisation") or "").split()):
            continue
        addresses = [str(e.get("address") if isinstance(e, dict) else e).strip()
                     for e in card.get("emails") or []]
        addresses = [a for a in addresses if "@" in a]
        line = {"id": card["id"], "name": card.get("name") or "(no name)", "emails": addresses,
                "phones": [str(p.get("number") if isinstance(p, dict) else p) for p in card.get("phones") or []]}
        domains = [d for d in (_work_domain(a) for a in addresses) if d]
        known = next((d for d in domains if by_domain.get(d)), "")
        if known:
            org, n = by_domain[known].most_common(1)[0]
            same.append(dict(line, suggest=org, why=f"{n} other contact{'s' if n != 1 else ''} at {known} "
                                                    f"{'have' if n != 1 else 'has'} it"))
        elif domains:
            guessed.append(dict(line, suggest=name_of(domains[0]), why=f"guessed from {domains[0]}"))
        else:
            note = " ".join(str(notes.get(card["id"]) or "").split())[:120]
            personal.append(dict(line, suggest=note, why="Rouh's note of who they are to you" if note else ""))
    return {"all": len(cards), "same": same, "guessed": guessed, "personal": personal}


def said(found: dict) -> str:
    """The tool's answer."""
    empty = len(found["same"]) + len(found["guessed"]) + len(found["personal"])
    if not found["all"]:
        return "There are no contacts to read: iCloud contacts are not connected, or the address book is empty."
    if not empty:
        return f"Every one of the {found['all']} contacts has a company. Nothing to fill."

    def row(one: dict) -> str:
        reach = ", ".join(one["emails"][:2] or one["phones"][:1]) or "no address or number"
        hint = f" -> {one['suggest']!r} ({one['why']})" if one.get("suggest") else ""
        return f"- {one['name']} [contact id {one['id']}], {reach}{hint}"

    out = [f"{empty} of the {found['all']} contacts have no company."]
    for key, head in (("same", "Can be filled from another contact at the same company"),
                      ("guessed", "A work address, the company guessed from it (say it is a guess)"),
                      ("personal", "Personal or no address: who they are to the person, in a few words")):
        group = found[key]
        if not group:
            continue
        out.append(f"\n{head} ({len(group)}):")
        out += [row(one) for one in group[:LISTED]]
        if len(group) > LISTED:
            out.append(f"- and {len(group) - LISTED} more")
    out.append("\nSay how many there are and the first few of each group, plainly. Offer to fill the first "
               "group as suggested in one go, and the others one by one; save only what the person says "
               "yes to, each with save_contact (contact_id, organisation). Never fill a guess without "
               "saying it is one, and never invent who a personal contact is.")
    return "\n".join(out)


def _notes(user_id: str, org_id: str) -> dict[str, str]:
    """Rouh's own note of who each contact is to the person, by the contact's id."""
    from .synapse import db
    from .synapse.sources import contacts

    ds = contacts.master_of(user_id, org_id, make=False)
    if ds is None:
        return {}
    rows = db.rows("SELECT id, meta->>'relationship' AS rel FROM synapse.item WHERE dataset_id = %s "
                   "AND kind = 'person' AND deleted_at IS NULL AND meta ? 'icloud' "
                   "AND coalesce(meta->>'relationship', '') <> ''", (ds["id"],))
    return {str(r["id"]): str(r["rel"] or "") for r in rows}


def answer(who) -> str:
    """Everything the tool does, as `who`. Synchronous: it reads the database."""
    from . import evolution
    from .synapse.sources import contacts

    if not on(who):
        return "Contacts with no company is switched off (Evolution, Mutations)."
    user_id, org_id = str(who.user_id), str(who.org_id)
    found = read(contacts.all_cards(user_id, org_id), _notes(user_id, org_id))
    empty = len(found["same"]) + len(found["guessed"]) + len(found["personal"])
    evolution.used(SWITCH, "asked", who=who, detail=f"{empty} of {found['all']} contacts with no company")
    return said(found)


__all__ = ["DESCRIPTION", "SWITCH", "TITLE", "answer", "name_of", "on", "read", "said"]
