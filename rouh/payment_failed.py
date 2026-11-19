"""A payment that did not go through: a service's email that it could not take the money is told at once.

Built by the nightly feature run, night 48 of the ledger (19 November 2026, task 94).
A card expires, a bank refuses a charge abroad, a limit is reached: the service writes "Your payment
failed", "We couldn't charge your card", "Action required: update your payment method", and gives a
few days before it suspends the account. That email lands in Rouh's inbox among the machines' mail,
which Rouh passes over as junk (`mail_alerts.junk_because`), and the services a nightly run signs up
to write to `rouh+<service>@...`. Renews soon (night 35, `rouh/renewal_notice.py`) tells what is
about to charge, and leaves out on purpose an email about a charge that failed. Nobody read it, and
the first anybody knew was the service stopping.

So, while its switch is on, every email that reaches Rouh's inbox (`mail_alerts`, before it is
passed over) is read in plain rules, no model:

1. **It says a charge failed** (`FAILED`): "payment failed", "card was declined", "couldn't charge",
   "unable to process your payment", "past due", "update your payment method", "неуспешно плащане",
   ... and is not a receipt for a payment that went through after all (`RECOVERED`).
2. **By when**: the first date it names after the words that say what happens next ("suspended on",
   "will be cancelled", "we'll try again", "by", "within 7 days"), in the shapes Renews soon reads.
3. **How much** and **what**: the first amount it names, and the sender's name or its domain.

A notice says it at once (`rouh/notices.py`): what failed, for how much, what happens next and by
when, the address it came from (a payment that failed is the commonest shape of a phishing email,
so the notice offers the email itself, never a link out of it), and the address it came to when it
is one a nightly run signed up with, with Open the email. Left alone, it goes to the phone, as every
notice does. One email is told once.

**Whose.** Rouh's own connected inbox and the person it belongs to, by `org_id` and `user_id`.

**Its switch** is `payment_failed` (`rouh/switches.py`): off, nothing is read or told.
"""
from __future__ import annotations

import email.utils
import hashlib
import logging
import re
from datetime import date, datetime

from . import renewal_notice

log = logging.getLogger("rouh.payment_failed")

SWITCH = "payment_failed"
TITLE = "A payment that did not go through: a service's email that a charge failed is told at once"
OPENS = "payment_failed_opens"

FAILED = re.compile(
    r"\bpayment (?:has |was )?(?:failed|declined|unsuccessful|did(?: not|n't) go through|could not be processed)"
    r"|\b(?:card|payment method) (?:was |has been |got )?(?:declined|refused|rejected)\b"
    r"|\b(?:could ?n[o']t|could not|were unable to|was unable to|unable to|failed to) (?:charge|bill|process|collect)"
    r"(?: (?:your|the))? (?:card|payment|invoice|subscription)?"
    r"|\bfailed (?:payment|charge|transaction)\b|\bpast[ -]due\b|\boverdue (?:invoice|payment|balance)\b"
    r"|\bupdate (?:your |the )?(?:payment (?:method|details|information)|billing (?:details|information)|card)\b"
    r"|\b(?:payment|billing) (?:problem|issue|action required)\b|\binsufficient funds\b"
    r"|неуспешно плащане|плащането (?:е )?(?:неуспешно|отхвърлено|не (?:беше|е) успешно)"
    r"|картата (?:ви )?(?:е |беше )?(?:отхвърлена|отказана)|не успяхме да (?:таксуваме|удържим|обработим)",
    re.I)
#: The same email can say a charge went through after all, or be the receipt for it.
RECOVERED = re.compile(
    r"\b(?:payment (?:received|successful|confirmed)|thank(?:s| you) for your payment"
    r"|(?:was|has been) (?:successfully )?(?:paid|charged|processed)|receipt for|refund(?:ed)?)\b"
    r"|плащането е (?:получено|успешно)|разписка", re.I)
#: What happens next, read for its date.
NEXT = re.compile(
    r"\b(?:suspend\w*|cancel\w*|deactivat\w*|terminat\w*|downgrad\w*|paus\w*|interrupt\w*|lose access"
    r"|(?:try|retry|attempt) (?:again|the (?:payment|charge))|retry\w*|by|before|until|within|no later than)\b"
    r"|спир\w*|прекрат\w*|деактивир\w*|до\b", re.I)
#: Words for what happens next, said back in the notice.
_WHAT_NEXT = (("suspend", "the account is suspended"), ("deactivat", "the account is deactivated"),
              ("terminat", "the account is closed"), ("cancel", "the subscription is cancelled"),
              ("downgrad", "the plan is downgraded"), ("paus", "the service is paused"),
              ("lose access", "access stops"), ("retry", "it tries the card again"),
              ("try again", "it tries the card again"), ("attempt", "it tries the card again"))


def on(who) -> bool:
    from . import switches

    if who is None:
        return False
    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def read(message: dict, today: date) -> dict | None:
    """What the notice says, or None when the email says no charge failed."""
    from . import ghosts

    subject = str(message.get("subject") or "")
    body = str(message.get("body") or "")
    text = ghosts.own_words(body)[:4000] or body[:4000]
    found = FAILED.search(subject) or FAILED.search(text)
    if not found:
        return None
    if RECOVERED.search(subject) or (not FAILED.search(subject) and RECOVERED.search(text[:400])):
        return None
    at = message.get("at") or 0
    sent = datetime.fromtimestamp(at).date() if at else today
    whole = subject + "\n" + text
    due, then, retry = None, "", None
    for hit in NEXT.finditer(whole):
        got = renewal_notice.when(whole[hit.start(): hit.start() + 120], sent)
        if got is None or got < today:
            continue
        low = whole[max(0, hit.start() - 60): hit.end() + 60].lower()
        said = next((said for cue, said in _WHAT_NEXT if cue in low), "")
        if said == "it tries the card again":
            retry = retry or got
            continue
        if due is None or (said and not then):
            due, then = got, said
        if then:
            break
    if not then:
        low = whole.lower()
        then = next((said for cue, said in _WHAT_NEXT if cue in low and said != "it tries the card again"), "")
    if due is None and retry is not None and not then:
        due, then, retry = retry, "it tries the card again", None
    _name, address = email.utils.parseaddr(str(message.get("from") or ""))
    return {"service": renewal_notice.service_of(str(message.get("from") or "")), "due": due,
            "then": then, "retry": retry if retry != due else None, "amount": renewal_notice.amount(whole), "subject": subject[:200],
            "from": address.lower()[:120]}


def key_of(message_id: str) -> str:
    return "pf-" + hashlib.sha256(str(message_id).encode()).hexdigest()[:16]


def _ids(who) -> tuple[str, str]:
    return str(getattr(who, "user_id", "") or ""), str(getattr(who, "org_id", "") or "")


def _held(who) -> dict:
    import json

    from .models import UserSetting

    user_id, org_id = _ids(who)
    value = (UserSetting.objects.filter(user_id=user_id, org_id=org_id, name=OPENS)
             .values_list("value", flat=True).first())
    try:
        held = json.loads(value) if value else {}
    except (TypeError, ValueError):
        held = {}
    return held if isinstance(held, dict) else {}


def _remember(who, key: str, where: dict) -> None:
    import json
    import time

    from .models import UserSetting

    held = _held(who)
    held[key] = dict(where, at=time.time())
    if len(held) > 200:
        held = dict(sorted(held.items(), key=lambda kv: kv[1].get("at") or 0)[-200:])
    user_id, org_id = _ids(who)
    UserSetting.objects.bulk_create(
        [UserSetting(user_id=user_id, org_id=org_id, name=OPENS, value=json.dumps(held),
                     updated_at=time.time())],
        update_conflicts=True, unique_fields=["user_id", "name"],
        update_fields=["org_id", "value", "updated_at"])


def opens(who, key: str) -> dict | None:
    return _held(who).get(key)


def where_to(who, key: str) -> str:
    from . import ghosts

    got = opens(who, key) or {}
    if not got.get("thread"):
        return "https://mail.google.com/"
    return ghosts.link_to(got.get("mailbox") or "", got["thread"])


def words(got: dict, today: date, signed_up: str = "") -> tuple[str, str]:
    """The notice's title and body."""
    what = got["service"]
    title = f"Payment failed: {what}"
    body = f"{what} could not take " + (f"the payment of {got['amount']}." if got["amount"]
                                         else "a payment (the email does not say how much).")
    if got["due"] is not None:
        days = (got["due"] - today).days
        in_days = "today" if days == 0 else ("tomorrow" if days == 1 else f"in {days} days")
        on_day = f"{got['due'].strftime('%A %-d %B')} ({in_days})"
        body += (f" On {on_day} {got['then']}, unless the payment is put right." if got["then"]
                 else f" The email names {on_day} as the day to put it right by.")
    if got.get("retry") is not None:
        body += f" It tries the card again on {got['retry'].strftime('%A %-d %B')}."
    if got["due"] is None and got["then"]:
        body += f" If nothing is done, {got['then']}; the email names no day."
    body += f" The email: “{got['subject']}”, from {got['from'] or 'an address it does not give'}."
    if signed_up:
        body += f" It came to {signed_up}, an address a nightly run signed up with."
    body += (" Put the card right on the service's own site, signed in as usual; an email like this is "
             "also the commonest shape of a fake one, so check the sender before pressing anything in it.")
    return title, body


async def seen(who, message: dict, *, mailbox: str = "", signed_up: str = "") -> str:
    """A failed payment, told to the person: the sentence for the mail log, or "" when there is none."""
    import asyncio

    from asgiref.sync import sync_to_async

    from . import clock, evolution, notices

    try:
        if not await asyncio.to_thread(on, who):
            return ""
        today = datetime.now(clock.zone_of(who)).date()
        got = read(message, today)
        if got is None:
            return ""
        title, body = words(got, today, signed_up)
        key = key_of(message.get("id") or "")
        link = f"/mail/payment-failed/{key}"
        said = await notices.notify(
            title=title, body=body, link=link, link_label="Open the email",
            links=[{"label": "Open the email", "href": link}], kind="mail", key=key, who=who,
            phone_text=f"{title}. {body}")
        if said is None:
            return f"A failed payment to {got['service']}: told before, not told again."
        await sync_to_async(_remember)(who, key, {"thread": str(message.get("thread_id") or ""),
                                                  "mailbox": mailbox, "service": got["service"]})
        await sync_to_async(evolution.used)(SWITCH, "told", who=who, detail=got["service"][:200])
        return f"A payment that failed: {got['service']}. You were told in a notice."
    except Exception as exc:  # noqa: BLE001 - the email is handled on without it
        log.info("payment failed: the email could not be read: %s", exc)
        return ""


__all__ = ["FAILED", "RECOVERED", "SWITCH", "TITLE", "key_of", "on", "opens", "read", "seen",
           "where_to", "words"]
