"""Bank details that changed: an email whose sender gives a bank account other than before is told at once.

Built by the nightly feature run, night 49 of the ledger (20 November 2026, task 94).
The commonest fraud against a company is not a hacked bank: it is an email from a supplier, a
landlord or a lawyer, often from their own mailbox taken over, saying "please note our new bank
details" or simply putting another IBAN on the invoice. Whoever pays it compares nothing, because
nothing shows that the account is not the one the same sender gave last month.

So, while its switch is on, every email somebody else sends to Rouh's inbox is read, in plain rules
and no model, for the bank accounts it gives (IBANs, checked by their own sum, `rouh/iban_read.py`),
in its own words and not in a quoted reply. Each is remembered against its sender: their domain
(northwind.test), or their whole address for a free-mail one (gmail.com, abv.bg). The first account
a sender gives is only remembered. When a later email from the same sender gives an account they
never gave before, a notice says it at once: who, which email, the account it gives now and the one
they gave before (by country and last four figures only), since when, and what to do: confirm the
new account with them by phone, on a number already known, before paying anything to it, with Open
the email (`/mail/bank-changed/<key>`). Nothing is changed in the mailbox, nothing is sent, and no
link out of the email is offered.

**Whose.** Kept in the person's own settings (`user_settings`, `bank_changed_seen`, by `org_id` and
`user_id`): for each sender, the accounts seen with the day first seen and the email's subject.

**Its switch** is `bank_changed` (`rouh/switches.py`): off, nothing is read or remembered.
"""
from __future__ import annotations

import email.utils
import hashlib
import json
import logging
import time
from datetime import date, datetime

from . import iban_read

log = logging.getLogger("rouh.bank_changed")

SWITCH = "bank_changed"
TITLE = "Bank details that changed: a sender's email giving another bank account than before is told at once"
SEEN = "bank_changed_seen"
OPENS = "bank_changed_opens"
#: Free mail: the sender is their whole address, not the domain anybody may have.
FREE_MAIL = {"gmail.com", "googlemail.com", "yahoo.com", "outlook.com", "hotmail.com", "live.com", "icloud.com",
             "me.com", "aol.com", "proton.me", "protonmail.com", "gmx.com", "gmx.de", "abv.bg", "mail.bg",
             "dir.bg", "yandex.ru", "mail.ru", "zoho.com"}
#: How many senders are remembered, the newest kept.
MOST = 500


def on(who) -> bool:
    from . import switches

    if who is None:
        return False
    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def sender_of(sender: str) -> tuple[str, str]:
    """(the key it is remembered by, the name to say) for an email's From."""
    name, address = email.utils.parseaddr(sender or "")
    address = (address or "").strip().lower()
    domain = address.split("@", 1)[1] if "@" in address else ""
    if not domain:
        return "", ""
    key = address if domain in FREE_MAIL else domain
    if domain in FREE_MAIL:
        said = name.strip().strip('"') or address
    else:
        parts = [p for p in domain.split(".") if p not in ("mail", "email", "billing", "invoices", "accounts", "em")]
        said = (parts[-2] if len(parts) >= 2 else domain).capitalize()
    return key, said[:60]


def accounts_in(message: dict) -> list[str]:
    from . import ghosts

    body = str(message.get("body") or "")
    words = ghosts.own_words(body)[:8000] or body[:8000]
    return iban_read.found(str(message.get("subject") or "") + "\n" + words)


def _ids(who) -> tuple[str, str]:
    return str(getattr(who, "user_id", "") or ""), str(getattr(who, "org_id", "") or "")


def _load(who, name: str) -> dict:
    from .models import UserSetting

    user_id, org_id = _ids(who)
    value = (UserSetting.objects.filter(user_id=user_id, org_id=org_id, name=name)
             .values_list("value", flat=True).first())
    try:
        held = json.loads(value) if value else {}
    except (TypeError, ValueError):
        held = {}
    return held if isinstance(held, dict) else {}


def _save(who, name: str, held: dict) -> None:
    from .models import UserSetting

    user_id, org_id = _ids(who)
    UserSetting.objects.bulk_create(
        [UserSetting(user_id=user_id, org_id=org_id, name=name, value=json.dumps(held), updated_at=time.time())],
        update_conflicts=True, unique_fields=["user_id", "name"], update_fields=["org_id", "value", "updated_at"])


def known(who, sender_key: str) -> dict:
    """The accounts a sender gave before: {iban: {"first", "subject"}}."""
    return dict((_load(who, SEEN).get(sender_key) or {}).get("accounts") or {})


def remember(who, sender_key: str, accounts: list[str], subject: str, day: date) -> None:
    held = _load(who, SEEN)
    one = held.get(sender_key) or {"accounts": {}}
    for iban in accounts:
        one["accounts"].setdefault(iban, {"first": day.isoformat(), "subject": subject[:160]})
    one["at"] = time.time()
    held[sender_key] = one
    if len(held) > MOST:
        held = dict(sorted(held.items(), key=lambda kv: kv[1].get("at") or 0)[-MOST:])
    _save(who, SEEN, held)


def key_of(message_id: str) -> str:
    return "bc-" + hashlib.sha256(str(message_id).encode()).hexdigest()[:16]


def _remember_open(who, key: str, where: dict) -> None:
    held = _load(who, OPENS)
    held[key] = dict(where, at=time.time())
    if len(held) > 200:
        held = dict(sorted(held.items(), key=lambda kv: kv[1].get("at") or 0)[-200:])
    _save(who, OPENS, held)


def opens(who, key: str) -> dict | None:
    return _load(who, OPENS).get(key)


def where_to(who, key: str) -> str:
    from . import ghosts

    got = opens(who, key) or {}
    if not got.get("thread"):
        return "https://mail.google.com/"
    return ghosts.link_to(got.get("mailbox") or "", got["thread"])


def _day(iso: str) -> str:
    try:
        return date.fromisoformat(iso).strftime("%-d %B %Y")
    except (TypeError, ValueError):
        return "before"


def words(said: str, address: str, subject: str, new: list[str], before: dict) -> tuple[str, str]:
    """The notice's title and body."""
    title = f"Bank details changed: {said}"
    now = " and ".join(iban_read.ending(one) for one in new)
    olds = sorted(before.items(), key=lambda kv: kv[1].get("first") or "")
    was = "; ".join(f"{iban_read.ending(iban)}, first in “{v.get('subject') or 'an email'}” on {_day(v.get('first'))}"
                    for iban, v in olds[:3])
    body = (f"{said}'s email “{subject[:160]}”, from {address}, gives a bank account they have not given "
            f"before: {now}. Their earlier emails gave {was}. "
            "A supplier's bank account that changes by email is the commonest invoice fraud, often sent "
            "from their own mailbox after somebody took it over. Before paying anything to the new "
            "account, confirm it with them by phone, on a number you already have and not one in this "
            "email.")
    return title, body


async def seen(who, message: dict, *, mailbox: str = "") -> str:
    """An email read for its bank accounts: the sentence for the mail log, or "" when there is nothing to say."""
    import asyncio

    from asgiref.sync import sync_to_async

    from . import clock, evolution, notices

    try:
        if not await asyncio.to_thread(on, who):
            return ""
        accounts = accounts_in(message)
        if not accounts:
            return ""
        sender_key, said = sender_of(str(message.get("from") or ""))
        if not sender_key:
            return ""
        today = datetime.now(clock.zone_of(who)).date()
        subject = str(message.get("subject") or "").strip() or "(no subject)"
        before = await sync_to_async(known)(who, sender_key)
        new = [one for one in accounts if one not in before]
        await sync_to_async(remember)(who, sender_key, accounts, subject, today)
        if not before:
            return f"{said} gave a bank account for the first time; remembered."
        if not new:
            return ""
        _name, address = email.utils.parseaddr(str(message.get("from") or ""))
        title, body = words(said, address.lower(), subject, new, before)
        key = key_of(message.get("id") or "")
        link = f"/mail/bank-changed/{key}"
        told = await notices.notify(
            title=title, body=body, link=link, link_label="Open the email",
            links=[{"label": "Open the email", "href": link}], kind="mail", key=key, who=who,
            phone_text=f"{title}. {body}", at_once=True)
        if told is None:
            return f"Bank details changed at {said}: told before, not told again."
        await sync_to_async(_remember_open)(who, key, {"thread": str(message.get("thread_id") or ""),
                                                       "mailbox": mailbox, "sender": said})
        await sync_to_async(evolution.used)(SWITCH, "told", who=who, detail=said[:200])
        return f"{said} gave a bank account they had not given before. You were told in a notice."
    except Exception as exc:  # noqa: BLE001 - the email is handled on without it
        log.info("bank details changed: the email could not be read: %s", exc)
        return ""


__all__ = ["FREE_MAIL", "SWITCH", "TITLE", "accounts_in", "key_of", "known", "on", "opens", "remember",
           "seen", "sender_of", "where_to", "words"]
