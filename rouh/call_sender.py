"""Call them from their email: an email opened on the inbox card from somebody whose number Rouh has
says so under the headers, with one press that rings it.

Built by the nightly feature run, night 41 of the ledger (12 November 2026, task 94).
Reading an email on the phone and deciding the quickest answer is a call meant leaving Rouh, opening
the phone's contacts and finding the person, or scrolling to the signature and copying the number.
Asked, Rouh can say the number but cannot ring it.

So, while its switch is on, an opened email from a person (not a machine, a list or ‹his› own
address) whose contact in ‹his› iCloud contacts has a phone number shows a line: "Call Dana Reed" and
each of their numbers, mobile first, at most three, each a `tel:` link that the phone rings in one
press. When the contact has no number, or the sender is no contact, the numbers in the email's own
signature are offered instead (`rouh/sig_phones.py`), said as from the signature. An email with no
number anywhere shows no line.

No model is asked, nothing is kept and nothing is changed: a press is only counted
(`card_inbox` `do: call_sender`), then the phone rings the number.

**Whose.** The person's own contacts, by `org_id` and `user_id`.

**Its switch** is `call_sender` (`rouh/switches.py`): off, there is no line.
"""
from __future__ import annotations

import email.utils
import logging
import re

log = logging.getLogger("rouh.call_sender")

SWITCH = "call_sender"
TITLE = "Call them from their email: the sender's number on the opened email, one press to ring"

#: How many numbers the line offers.
MOST = 3


def on(who) -> bool:
    from . import switches

    if who is None:
        return False
    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def tel(number: str) -> str:
    """The number as a `tel:` address: its plus and digits only."""
    return "tel:" + re.sub(r"[^+\d]", "", str(number or ""))


def _label(label: str) -> str:
    label = str(label or "").strip().lower()
    for word in ("mobile", "iphone", "cell", "work", "home", "main", "office"):
        if word in label:
            return "mobile" if word in ("iphone", "cell") else word
    return label[:16] if label and label.isprintable() else ""


def numbers_of(card: dict) -> list[dict]:
    """The contact's numbers, mobile first, each {number, label, tel}."""
    out = []
    for p in card.get("phones") or []:
        number = str(p.get("number") if isinstance(p, dict) else p).strip()
        if not re.sub(r"\D", "", number):
            continue
        out.append({"number": number, "label": _label(p.get("label") if isinstance(p, dict) else ""),
                    "tel": tel(number)})
    out.sort(key=lambda n: 0 if n["label"] == "mobile" else 1)
    return out[:MOST]


def shown(who, found: dict, own: list[str] = ()) -> dict | None:
    """What the opened message's line says, or None. Synchronous: it reads the database."""
    from .new_number import _contact_of, is_a_person
    from .sig_phones import label_for, phones

    if not on(who) or not is_a_person(found, own):
        return None
    named, sender = email.utils.parseaddr(found.get("from", ""))
    card = _contact_of(who, (sender or "").strip().lower())
    numbers = numbers_of(card) if card else []
    source = "contact"
    if not numbers:
        body = found.get("body") or ""
        numbers = [{"number": n, "label": label_for(body, n), "tel": tel(n)} for n in phones(body)][:MOST]
        numbers.sort(key=lambda n: 0 if n["label"] == "mobile" else 1)
        source = "signature"
    if not numbers:
        return None
    name = (card or {}).get("name") or " ".join(str(named or "").replace('"', "").split()) or sender
    said = f"Call {name}" + (":" if source == "contact" else ", from their signature:")
    return {"said": said, "name": name, "from": source, "numbers": numbers}


def pressed(who, how: str = "") -> None:
    """A number on the line pressed: counted, nothing else."""
    from . import evolution

    log.info("call them from their email: a %s number pressed", how[:20] or "")
    evolution.used(SWITCH, "called", who=who, detail=how[:40])


__all__ = ["MOST", "SWITCH", "TITLE", "numbers_of", "on", "pressed", "shown", "tel"]
