"""Every email address of one person, as one list: the contact card and the profile draw the same rows.

Petar, 27 October 2026, of his own contact card and his profile in Anatomy: "this is a big mess". The card
showed the addresses on the iCloud card at the top and the ones Rouh knew otherwise further down, as
"known to Rouh" rows and again under Also known as, and the profile listed the card's addresses under a
heading that said "Connected" and then all of them again under "Your email addresses, for mail". Two
lists of the same thing, and a word that meant the card was picked read as if each address were a mailbox
connected to Rouh.

So there is one list, made here, and one component that draws it (`static/personaddresses.js`), on the
contact card (`apple_contacts.profile_card`) and on the profile (`web/mycard.py`) alike. Each row is:

- **the address**, and **its label exactly as the iCloud card has it** (home, work, other, iCloud, or a
  label the person made up, `vcard.Card.label_of`), or none for an address that is not on the card;
- **where it comes from**: the iCloud card, the person's Rouh account, or known only to Rouh (mail,
  Slack, meetings, or added by hand);
- **its silo** (`rouh/silos.py`): the rule on that one address, which the row's chip changes in place
  (`set_silo`), or the rule on its domain, shown as such; mail from or to the address is labelled with it;
- **for the person's own addresses, whether it is a connected mailbox**: "Connected" only when a mailbox
  of theirs is really connected to Rouh through an integration (a Google mailbox, `models.ReadMailbox`),
  "Needs connecting again" when Google withdrew it, and otherwise "Not connected", with Connect where an
  integration can connect it (`connectable`). Rouh's own address is said to be Rouh's.

Nothing here writes to iCloud. Labels are only read, and a change of an address on the card goes through
`save_contact` (`vcard`), which keeps every label it does not touch.
"""
from __future__ import annotations

import logging
import threading
import time
import urllib.parse

log = logging.getLogger("rouh.person_addresses")

#: Where each row comes from, as the row says it.
ICLOUD, ACCOUNT, ROUH = "icloud", "account", "rouh"
SOURCE_WORDS = {ICLOUD: "iCloud card", ACCOUNT: "your Rouh account", ROUH: "known only to Rouh"}

#: A mailbox's state, for the person's own addresses only.
CONNECTED, RECONNECT, NOT_CONNECTED, ROUHS = "connected", "reconnect", "not_connected", "rouh"
MAILBOX_WORDS = {CONNECTED: "Connected", RECONNECT: "Needs connecting again",
                 NOT_CONNECTED: "Not connected", ROUHS: "Rouh's own address"}

#: Domains Google's own mail is on, whatever their mail servers say.
GOOGLE_DOMAINS = {"gmail.com", "googlemail.com"}
#: How long what a domain's mail servers said is believed, and how long one look may take.
MX_TTL = 24 * 3600.0
MX_WAIT = 1.5

_mx: dict[str, tuple[float, bool]] = {}
_mx_lock = threading.Lock()


def _addr(value) -> str:
    return str(value or "").strip().lower()


def google_hosted(domain: str) -> bool:
    """Whether mail at this domain is Google's (Gmail, or Google Workspace by its mail servers), which is
    the one kind of mailbox Rouh can connect today. Remembered a day; nothing known is no."""
    domain = _addr(domain).strip(".")
    if not domain:
        return False
    if domain in GOOGLE_DOMAINS:
        return True
    now = time.monotonic()
    with _mx_lock:
        got = _mx.get(domain)
        if got and now - got[0] < MX_TTL:
            return got[1]
    hosted = False
    try:
        import dns.resolver

        answer = dns.resolver.resolve(domain, "MX", lifetime=MX_WAIT)
        hosted = any(str(r.exchange).rstrip(".").lower().endswith(("google.com", "googlemail.com"))
                     for r in answer)
    except Exception:  # noqa: BLE001 - no answer is not Google's
        hosted = False
    with _mx_lock:
        _mx[domain] = (now, hosted)
    return hosted


def connect_url(address: str) -> str:
    """Where Connect goes for one of the person's own addresses: Google's account chooser, read-only,
    with that address put forward (`web/mailboxes.start`)."""
    return "/auth/mailbox/start?" + urllib.parse.urlencode({"hint": address})


def _mailboxes(user_id: str, org_id: str) -> dict[str, bool]:
    """address -> whether Google withdrew it, for every mailbox of the person's connected to Rouh."""
    from .models import ReadMailbox

    return {_addr(r["email"]): bool(r["needs_reconnect"]) for r in
            ReadMailbox.objects.filter(user_id=str(user_id), org_id=str(org_id)).values("email", "needs_reconnect")
            if r["email"]}


def _identity_emails(person) -> list[str]:
    """The addresses Synapse ties to the person beyond their card: met in mail, Slack, meetings, or linked."""
    ds_id = str((person.profile or {}).get("dataset_id") or "") if person is not None else ""
    if not ds_id or not person.id:
        return []
    try:
        from .synapse import db, people

        ds = db.row("SELECT * FROM synapse.dataset WHERE id = %s::uuid", (ds_id,))
        if ds is None:
            return []
        return [_addr(x["value"]) for x in people.identities(people.home_id(ds), person.id) if x["type"] == "email"]
    except Exception:  # noqa: BLE001 - the card's own addresses still stand
        log.exception("the addresses Synapse ties to %s could not be read", person.id)
        return []


def rows(user_id: str, org_id: str, person) -> list[dict]:
    """Every address of the person (`people.Person`), the card's first in the card's order."""
    from . import my_card, silos

    if person is None:
        return []
    me = bool(getattr(person, "is_me", False)) or my_card.is_my_card(user_id, org_id, person)
    out: dict[str, dict] = {}

    def add(address, source: str, label: str = "") -> None:
        key = _addr(address)
        if not key or "@" not in key:
            return
        row = out.get(key)
        if row is None:
            out[key] = {"address": str(address).strip(), "label": label, "sources": [source]}
        else:
            if source not in row["sources"]:
                row["sources"].append(source)
            if label and not row["label"]:
                row["label"] = label

    card = person.card or {}
    for one in card.get("emails") or []:
        if isinstance(one, dict):
            add(one.get("address"), ICLOUD, str(one.get("label") or ""))
    if me:
        add(my_card.account_address(user_id), ACCOUNT)
        for address in my_card.own_addresses(user_id, org_id):
            add(address, ROUH)
    tied = _identity_emails(person)
    for address in list(person.emails or []) + list(person.own_emails or []) + tied:
        add(address, ROUH)

    boxes = _mailboxes(user_id, org_id) if me else {}
    chips = {s.key: s.chip() for s in silos.of(user_id, org_id)}
    rules = silos.rule_map(user_id, org_id)
    shown = []
    for key, row in out.items():
        sources = [s for s in (ICLOUD, ACCOUNT, ROUH) if s in row["sources"]]
        if len(sources) > 1 and ROUH in sources:
            sources.remove(ROUH)            # known to Rouh too is no news for an address on the card
        row["sources"] = sources
        row["source_said"] = " · ".join(SOURCE_WORDS[s] for s in sources)
        silo, why = silos.of_address(user_id, org_id, key)
        row["silo"] = chips.get(silo) if silo in chips else None
        row["silo_by"] = ("address" if key in rules.get("sender", {}) else "domain") if row["silo"] else ""
        if row["silo_by"] == "domain":
            row["silo_why"] = f"from the rule on {why.removeprefix('the domain ')}"
        row["unlink"] = not me and ICLOUD not in sources and key in tied
        if me:
            if my_card.never_mine(key):
                row["mailbox"] = ROUHS
            elif key in boxes:
                row["mailbox"] = RECONNECT if boxes[key] else CONNECTED
            else:
                row["mailbox"] = NOT_CONNECTED
            row["mailbox_said"] = MAILBOX_WORDS[row["mailbox"]]
            domain = key.rsplit("@", 1)[-1]
            # A mailbox Google withdrew is one of Google's by definition; so is another address at the
            # domain of one already connected.
            if row["mailbox"] == RECONNECT or row["mailbox"] == NOT_CONNECTED and (
                    domain in {b.rsplit("@", 1)[-1] for b in boxes} or google_hosted(domain)):
                row["connect"] = connect_url(row["address"])
        shown.append(row)
    return shown


def choices(user_id: str, org_id: str) -> list[dict]:
    """Every silo an address can be put in, in the account's order."""
    from . import silos

    return [s.chip() for s in silos.of(user_id, org_id)]


def view(user_id: str, org_id: str, person) -> dict:
    """What the component draws: the rows, the silos to choose from, and whose they are."""
    from . import my_card

    return {"person": str(getattr(person, "id", "") or ""), "rows": rows(user_id, org_id, person),
            "silos": choices(user_id, org_id),
            "me": bool(person is not None and (getattr(person, "is_me", False)
                                               or my_card.is_my_card(user_id, org_id, person)))}


def set_silo(user_id: str, org_id: str, address: str, silo: str | None) -> dict:
    """One address put in one silo, or (None or "") taken out of it: the rule on that address
    (`silos.set_rule`, kind "sender"), which labels mail from it and to it. Everything is labelled again
    on a thread of its own (`silos.refill`)."""
    from . import silos

    got = silos.set_rule(user_id, org_id, "sender", address, silo or None)
    silos.refill(user_id, org_id)
    return got


__all__ = ["CONNECTED", "NOT_CONNECTED", "RECONNECT", "ROUHS", "choices", "connect_url", "google_hosted", "rows",
           "set_silo", "view"]
