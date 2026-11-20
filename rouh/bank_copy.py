"""Pay an invoice from the inbox card: the bank account, the amount and the reference, each with Copy.

Built by the nightly feature run, night 49 of the ledger (20 November 2026, task 94).
An invoice or a payment request by email is paid by copying three things into the bank's app: the
account (an IBAN of 22 or more characters), the amount and the reference the payee asked for. On a
phone that is three careful selections in the payee's words, and an IBAN mistyped by one character
fails, while a payment with no reference is chased later.

So, while its switch is on, a message opened on the inbox card (Rouh's own inbox or the person's
read-only one) that gives a bank account in its own words has one more row near the top: who is to
be paid, the account in fours (checked by its own sum, `rouh/iban_read.py`; one that fails it is not
shown), its BIC when given, the amount the email asks for and the reference (the invoice number or
the payment reference it names), each with its own Copy button. Read in plain rules, no model.
Nothing is kept: it is read from the message each time it is opened, a press only puts it on the
person's own clipboard and is counted, and nothing is sent anywhere.

**Whose.** The opened message, in the person's own inbox card, by `org_id` and `user_id`.

**Its switch** is `bank_copy` (`rouh/switches.py`): off, the card has no such row.
"""
from __future__ import annotations

import email.utils
import logging
import re

from . import iban_read

log = logging.getLogger("rouh.bank_copy")

SWITCH = "bank_copy"
TITLE = "Pay an invoice from the inbox card: the bank account, amount and reference, each with Copy"

_REFERENCES = (
    # What the payee asked to be written on the payment comes first, an invoice's number after.
    re.compile(r"(?im)\b(?:payment reference|reference(?: number| no\.?)?|ref\.?|основание(?: за плащане)?)"
               r"\s*[:#№]?\s*(?P<ref>[A-Z0-9][A-Z0-9/._-]{2,24})\b"),
    re.compile(r"(?im)\b(?:invoice(?: number| no\.?| #)?|фактура(?: №| номер)?)\s*[:#№]?\s*(?:№\s*)?"
               r"(?P<ref>[A-Z0-9][A-Z0-9/._-]{2,24})\b"),
)
_TOTAL = re.compile(
    r"(?im)\b(?:total(?: due| amount| to pay)?|amount(?: due| to pay| payable)?|balance due|to pay|please pay|"
    r"сума(?: за плащане)?|общо(?: за плащане)?|за плащане)\b[^\n\d€$£]{0,30}(?P<line>[^\n]{1,60})")


def on(who) -> bool:
    from . import switches

    if who is None:
        return False
    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def _words(found: dict) -> str:
    from . import ghosts, inbox

    body = str(found.get("body") or "")
    if not body and found.get("html"):
        body = inbox.html_text(str(found["html"]))
    return str(found.get("subject") or "") + "\n" + (ghosts.own_words(body)[:8000] or body[:8000])


def _amount(text: str) -> str:
    from . import renewal_notice

    for hit in _TOTAL.finditer(text):
        got = renewal_notice.amount(hit.group("line"))
        if got:
            return got
    return renewal_notice.amount(text)


def _reference(text: str, accounts: list[str]) -> str:
    for hit in (h for pattern in _REFERENCES for h in pattern.finditer(text)):
        ref = hit.group("ref").strip("._-")
        if not any(ch.isdigit() for ch in ref) or iban_read.plain(ref) in accounts or len(ref) < 3:
            continue
        if any(iban_read.plain(ref) in one for one in accounts):
            continue
        return ref
    return ""


def figures(amount: str) -> str:
    """The amount as a bank's form takes it: 1250.00 for "€1,250.00", 1250,00 for "1 250,00 лв"."""
    raw = re.sub(r"[^\d.,]", "", amount or "").strip(".,")
    if "," in raw and "." in raw:
        return raw.replace(",", "") if raw.rfind(".") > raw.rfind(",") else raw.replace(".", "")
    if re.fullmatch(r"\d{1,3}(?:,\d{3})+", raw):
        return raw.replace(",", "")
    return raw


def shown(who, found: dict) -> dict | None:
    """What the opened message's row says, or None."""
    if not on(who):
        return None
    text = _words(found)
    accounts = iban_read.found(text)
    if not accounts:
        return None
    name, address = email.utils.parseaddr(str(found.get("from") or ""))
    holder = iban_read.holder(text)
    payee = holder or (name.strip().strip('"') or address)
    rows = [{"what": "account", "label": "Bank account (IBAN)", "value": iban_read.spaced(one),
             "copy": iban_read.plain(one)} for one in accounts[:2]]
    bic = iban_read.bic(text)
    if bic:
        rows.append({"what": "bic", "label": "BIC", "value": bic, "copy": bic})
    amount = _amount(text)
    if amount:
        rows.append({"what": "amount", "label": "Amount", "value": amount,
                     "copy": figures(amount)})
    reference = _reference(text, accounts)
    if reference:
        rows.append({"what": "reference", "label": "Reference", "value": reference, "copy": reference})
    said = f"To pay {payee[:80]}" + (": two accounts are given, check which one to use" if len(accounts) > 1 else "")
    return {"said": said, "payee": payee[:80], "rows": rows}


def copied(who, what: str = "") -> None:
    """A Copy pressed: counted, nothing else."""
    from . import evolution

    log.info("pay an invoice from the inbox card: %s copied", what or "a detail")
    evolution.used(SWITCH, "copied", who=who, detail=str(what or "")[:40])


__all__ = ["SWITCH", "TITLE", "copied", "figures", "on", "shown"]
