"""Their job title saved with them: a contact saved or changed from an email carries the job title its
signature gives.

Built by the nightly feature run, night 43 of the ledger (14 November 2026, task 94).
Night 39's Save them as a contact (`rouh/save_sender.py`) saves a new sender's name, address, company and
numbers from their email, and night 41's A new company in their signature (`rouh/new_company.py`) changes a
contact's company to the one under their name; both read past the job title on the line beside it, so
the card on the phone said who employs them and never what they do there, and filling it took a second
ask. Night 42 made the card's Job title writable (`vcard.Changes.title`).

So, while its switch is on, nothing new is asked of anybody:

- **Save to contacts** on an email (save_sender) says the title it found ("job title Head of Operations")
  in the line of what saving adds, and writes it on the new card with the rest;
- **Change it on their contact** on a new company's notice (new_company) writes the job title signed
  beside the new company too, and says so.

Only a title found for certain under the sender's own name (`new_company.company_in`, plain rules, no
model) is written. Off, both save and change exactly as before. No model is asked.

**Whose.** The person's own contacts, by `org_id` and `user_id`; nothing is kept beyond the card.

**Its switch** is `title_saved` (`rouh/switches.py`).
"""
from __future__ import annotations

SWITCH = "title_saved"
TITLE = "Their job title saved with them: the signature's title on a contact saved or changed from an email"

#: The longest a title may be to be written.
LONGEST = 80


def on(who=None) -> bool:
    from . import switches

    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def from_signature(body: str, name: str) -> str:
    """The job title under `name` in the email's signature, or ""."""
    from .new_company import company_in

    title, _company = company_in(body or "", name or "")
    title = " ".join(str(title or "").split()).strip(" ,.")
    return title if 0 < len(title) <= LONGEST else ""


def for_new(who, body: str, name: str) -> str:
    """The title a contact saved from their email carries: "" while the switch is off."""
    if who is None or not on(who):
        return ""
    return from_signature(body, name)


__all__ = ["SWITCH", "TITLE", "for_new", "from_signature", "on"]
