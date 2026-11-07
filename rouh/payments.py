"""Payments: Rouh's card vault and Stripe, general, for any work to use.

Petar, 5 October 2026, splitting the heartbeat in three: "B. Payments: general, part of
the arsenal, in Settings at its own address (/settings/payments). Rouh's card vault and
Stripe key, for any work to use."

**The card vault.** The owner types each card themselves, on the Payments page: number, expiry,
CVC and name, under the billing entity it is for. They may keep several (14 October 2026, fr_392511bf4c9c:
"can you make multiple cards adding?"), each a `PaymentCard` row. The whole card,
security code included, is sealed with `encryption.SecretBox`, whose key is kept outside
the database: the code is kept because a checkout asks for it and nobody is there to type
it, and it is never shown again, anywhere. Beside the seal, in the clear, are only its
brand, last four, the name on it and its expiry month and year, and only the Payments
page shows those; everything else that names a card says its brand, last four and silo. The
number and the CVC never reach a model, a prompt, a tool result, a log line, the request
log, a transcript, a card on the screen, Telegram, mail, Synapse or an error message: the
one place they are opened is `_open_card`, for `fill_card` and `fill_card_in_run`, which
hand them straight to a checkout's fields (`browsing.Desk.fill_card`), and the outline of
the page read back after is scrubbed of them (`browsing.scrub_card`).

**Billing entities.** Who a card's purchases are billed to (14 October 2026,
fr_7c47d56e9a95: "we also need company details for the invoices- company, vat, and if
anything else is filled. We actually need to have multiple entities saved
[...]"). Each is a `BillingEntity`: a label
("Company A", "Personal"), an optional company name, VAT number, company registration
number and email for invoices, and the billing address. Every card belongs to one, and the
page lists the cards under it. When a card is filled into a checkout, its entity's address
and whichever of its company details are set go into the checkout's own fields
(`browsing.CARD_FIELDS`), and the details are said back to Rouh so it can type any the page
asks for elsewhere, such as behind a "buying as a business" box; a field left empty is
never filled or said, so a personal entity's invoice simply has no company or VAT line. A
purchase keeps who it was billed to as it was then (`CardCharge.billed_to`), so editing an
entity later changes no purchase already made. A card saved before entities kept its
billing address inside its seal: `carry_over` moves it into an entity, cards with the same
address into the same one, the first time the vault is read.

**Which card is filled.** The one Rouh is told to use by its last four (fill_card's
`card`). Otherwise the card of the purchase's silo (`rouh/silos.py`): a card may be for one
silo, picked on the Payments page (14 October 2026, fr_3c19cfb75db1: "add also silo to the
card. different purposes different cards... work for work"), and a purchase's silos are its
quest's task's, else its chat's task's or project's, else, in a run, the run's
(`silos_for`). With no card of that silo, or no silo known, it is the default: the card for
no silo saved most recently, which the Payments page marks, or, when every card is some
silo's, the one saved most recently (`card_in_use`). A silo may have several cards; the one
saved last is filled. With no silo set on any card, this is exactly the vault as it was.

**The caps are each card's own** (14 October 2026, fr_c29d7ddcee31: "Each card needs to
have a limit", and then "I have a spending cap but it needs to be per card"), enforced
here, in code, before the card is filled: the most one purchase on it may be, and the most
all of its purchases may be in a day and in the calendar month (`CAPS`). Each is set on the
Payments page, when the card is added (a purchase and a day start at 100 dollars, as the
vault's one pair of caps did, which every card saved before was given as its own) or at
any time after; an empty one is no cap of that kind, and a card with none says so. A
purchase that would cross one of the card's caps is refused, and no other card is filled
instead (`check_card_caps`). Under them are the quest's own cap per purchase
(`LongWork.spend_cap`, `rouh/quests.py`) and its budget. A purchase is written down before
the fill, with the card, the merchant, the amount, the reason and the quest, into
`card_charges` and that quest's ledger, and the owner gets a Telegram for each. Nothing is
bought because a page, an email or a file said to: only for the plan of the work being
done.

**The order button** is pressed by Rouh itself only for a purchase the owner asked for in their
own words (`rouh/purchases.py`, 17 October 2026: "Don't leave pay button for me"):
`place_order` checks, against the page as it is about to be pressed, that the card was
filled here for that purchase, that the order total the page shows is inside the card's
caps (`check_card_caps`, counting this purchase once) and within 10% of what was expected,
and that the delivery address is one of their shipping options. The charge then carries
`placed_at`, the total, what was bought and their words, and they get one notice for it, but
only once the page confirms the payment: from the press it is "confirming", "bank" while their
bank's 3-D Secure or app waits for them (sent to their Telegram at once), and "paid" or "failed"
when the shop's or the provider's page says so (`settle`, `rouh/purchases.py`, "Paid means
confirmed"). A shop
that takes the card only on its payment provider's page, after its own order button, goes in
two presses: `place_order` submits the order with a card picked as the way to pay, its charge
written then as "submitted" (`submitted_at`), and the card goes into that same charge on the
provider's page before its Pay is pressed; one left unpaid becomes "unpaid", and the owner is
told plainly that the shop has an unpaid order (`left_unpaid`). Rouh never types a one-time code, and never stores or types a password to sign in:
The owner signs in themselves, in the live browser. The one password it fills in is a new
account's, for a sign-up they authorized (`rouh/signups.py`).

**Stripe.** A restricted key, sealed the same way and shown masked, with the permissions
to make it with listed beside it (`STRIPE_PERMISSIONS`). Tools make products, prices and
payment links, each written down against the quest it is for (`StripeLink`), and
read payments and the balance. One action makes Rouh's own webhook endpoint at the address
Rouh is served on (`make_webhook`), keeps its signing secret sealed, and every event that
arrives is checked against it (`verify`) before anything is read from it; each payment is
written as money in, against the quest whose product or link it came from, and
the owner gets a Telegram. Refunds, payouts and account changes go to the heartbeat's approval
queue and run only on their yes (`heartbeat.APPROVED`). With no key set, every tool says so.

**The nightly feature run** (`rouh/nightly_feature.py`) is the one run of the one program
that may pay, without anybody's approval, where its owner set it up (Petar allowed his on 6 October 2026): up to
100 dollars a run in all, for at most two services, under the card's own caps as well. It
never sees the card. It opens the checkout in its own headless browser, which listens for
DevTools on loopback on a port Rouh chose for it, and asks with its `nightly_pay` tool;
`fill_card_in_run` checks every cap, writes the purchase down against the run, connects to
that browser, fills the card in and presses the button the run named, and clears the
card's fields again if they are still on the page afterwards, so the card is not in what
the run reads back. The run's model can still read a page it controls, so this keeps the
card out of its transcript rather than out of its reach; the caps are what are enforced.

Everything is keyed and queried by `org_id` and `user_id`: the card and the key are the
person's own.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import time
from decimal import Decimal
from urllib.parse import urlsplit

from . import clock, owner, quests
from .encryption import box as _box

log = logging.getLogger("rouh.payments")

#: What a new card's caps start at on the Payments page: the vault's one pair of caps as
#: they were (100 dollars each since 6 October 2026, so the nightly feature run's 100 a
#: run is not stopped at 50).
DEFAULT_PER_PURCHASE = Decimal("100")
DEFAULT_PER_DAY = Decimal("100")
#: Where Stripe's API is; a stand-in's address in a test world (`rouh/testing/fake_stripe.py`).
STRIPE_API = os.environ.get("ROUH_STRIPE_API_BASE", "https://api.stripe.com").rstrip("/")
#: Where Stripe sends its events here; the rest of the address is a random token.
HOOK_ROUTE = "/hooks/stripe/"
#: The events the webhook asks for.
HOOK_EVENTS = ("checkout.session.completed", "payment_intent.succeeded", "charge.refunded")
#: How old a signed event may be before it is refused, as Stripe's own libraries do.
HOOK_TOLERANCE = 300

#: The permissions the restricted key is made with, as the page lists them.
STRIPE_PERMISSIONS = {
    "write": ["Products", "Prices", "Payment Links", "Checkout Sessions", "Webhook Endpoints"],
    "read": ["Balance", "Charges", "Payment Intents", "Customers", "Events"],
    "none": ["Payouts", "Transfers", "Account settings", "everything else"],
}

NO_KEY = ("No Stripe key is set. ‹owner› adds a restricted key on the Payments page in "
          "Settings, /settings/payments.")
NO_CARD = "No card is in the vault. ‹owner› adds one on the Payments page in Settings."
NO_SUCH_CARD = "No card in the vault ends in those four digits."
NO_ENTITY = "Pick the billing entity this card is for, or add one first."
#: The states of a charge the caps count: filled into a checkout, an order submitted at a
#: shop that takes the card after it, its Pay pressed and awaiting the page's confirmation,
#: waiting for the owner's bank approval, paid, or pressed and never confirmed either way.
#: "void" never went through, "failed" was declined, and "unpaid" was an order submitted
#: and never paid.
COUNTED = ("filled", "submitted", "confirming", "bank", "paid", "unconfirmed")
#: The states of a charge whose Pay is not pressed yet.
UNPRESSED = ("filled", "submitted")
#: The states of a charge whose Pay was pressed and is not confirmed yet.
PRESSED = ("confirming", "bank")

#: A card's own caps: its field, what it is called where it is wrong, and how it is said.
CAPS = (("per_purchase", "The most a purchase", "a purchase"),
        ("per_day", "The most a day", "a day"),
        ("per_month", "The most a month", "a month"))


class Refused(ValueError):
    """A purchase or a Stripe call refused in code, with the reason, never with a card's digits.

    `fields`, when what is wrong belongs to fields of a form, maps each one's name to what
    is wrong with it, so the Payments page says each under its own field (fr_0bcd34587d67:
    "Errors should be field specific"). The reason is then all of them, one after another."""

    def __init__(self, message: str = "", fields: dict | None = None):
        self.fields = dict(fields or {})
        super().__init__(message or " ".join(self.fields.values()))


def _refuse_any(wrong: dict) -> None:
    """Refused naming every field in `wrong` at once, if there is any."""
    if wrong:
        raise Refused(fields=wrong)


# --- the rows ------------------------------------------------------------------------------

def _models():
    from . import models

    return models


def _whose(who) -> dict:
    return {"user_id": str(who.user_id), "org_id": str(who.org_id)}


def settings_of(who):
    """This person's row, made the first time. Never None."""
    row, _made = _models().PaymentSettings.objects.get_or_create(
        **_whose(who), defaults={"updated_at": time.time()})
    return row


def _save(row, **fields) -> None:
    fields["updated_at"] = time.time()
    _models().PaymentSettings.objects.filter(id=row.id).update(**fields)
    for key, value in fields.items():
        setattr(row, key, value)


# --- the card -----------------------------------------------------------------------------


def _digits(text) -> str:
    return re.sub(r"\D", "", str(text or ""))


def luhn(number: str) -> bool:
    total, odd = 0, False
    for ch in reversed(number):
        d = int(ch)
        if odd:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        odd = not odd
    return total % 10 == 0


def brand_of(number: str) -> str:
    n = number
    if n.startswith("4"):
        return "Visa"
    if re.match(r"^(5[1-5]|222[1-9]|22[3-9]\d|2[3-6]\d\d|27[01]\d|2720)", n):
        return "Mastercard"
    if re.match(r"^3[47]", n):
        return "American Express"
    if re.match(r"^(6011|65|64[4-9])", n):
        return "Discover"
    if re.match(r"^35(2[89]|[3-8]\d)", n):
        return "JCB"
    if re.match(r"^3(0[0-5]|[68])", n):
        return "Diners Club"
    return "Card"


def card_from(form: dict) -> dict:
    """The card as the owner typed it, checked; a Refused names each field that is wrong, never
    its value."""
    wrong = {}
    number = _digits(form.get("number"))
    if not number:
        wrong["number"] = "Type the card number."
    elif not 12 <= len(number) <= 19 or not luhn(number):
        wrong["number"] = "That card number is not a valid one. Check it and type it again."
    month = year = None
    exp = str(form.get("expiry") or "").strip()
    # MM/YY as the page writes it, or the bare digits if the slash never reached it.
    found = re.fullmatch(r"(\d{1,2})\s*/\s*(\d{2}|\d{4})", exp) or re.fullmatch(r"(\d{2})(\d{2}|\d{4})", exp)
    if found:
        month, year = int(found.group(1)), int(found.group(2))
    else:
        try:
            month, year = int(form.get("exp_month")), int(form.get("exp_year"))
        except (TypeError, ValueError):
            pass
    if year is not None and year < 100:
        year += 2000
    now = clock.now()
    if month is None or not 1 <= month <= 12 or not 2000 <= year <= 2100:
        wrong["expiry"] = "The expiry is the month and year, such as 08/29."
    elif (year, month) < (now.year, now.month):
        wrong["expiry"] = "That card has expired."
    cvc = _digits(form.get("cvc"))
    want = 4 if brand_of(number) == "American Express" else 3
    if len(cvc) != want:
        wrong["cvc"] = f"The security code is {want} digits."
    name = " ".join(str(form.get("name") or "").split())[:120]
    if not name:
        wrong["name"] = "Give the name on the card."
    _refuse_any(wrong)
    return {"number": number, "exp_month": month, "exp_year": year, "cvc": cvc, "name": name}


# --- billing entities -----------------------------------------------------------------------

#: A billing address's parts, as a card's seal and a checkout name them.
ADDRESS = ("line1", "line2", "city", "postal_code", "state", "country")
#: The company details an invoice carries when they are set, in the order they are said.
INVOICE = (("company", "Legal name"), ("vat", "VAT number"), ("reg_number", "Registration number"),
           ("email", "Invoice email"))
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


def _line(value, most: int = 120) -> str:
    return " ".join(str(value or "").split())[:most]


def entity_from(form: dict) -> dict:
    """A billing entity as the owner typed it, checked; a Refused names each field that is wrong."""
    wrong = {}
    label = _line(form.get("label"), 80)
    if not label:
        wrong["label"] = "Give the entity a trading name, the one you pick it by in Rouh, such as Personal."
    out = {"label": label, "company": _line(form.get("company"), 200),
           "vat": _line(form.get("vat"), 40), "reg_number": _line(form.get("reg_number"), 40),
           "email": _line(form.get("email"), 200)}
    if out["email"] and not _EMAIL.fullmatch(out["email"]):
        wrong["email"] = "That is not an email address. Leave it empty if invoices need none."
    address = form.get("address") if isinstance(form.get("address"), dict) else {}
    out.update({k: _line(address.get(k)) for k in ADDRESS})
    out["country"] = out["country"].upper()
    for key, said in (("line1", "Give the street."), ("city", "Give the city."),
                      ("postal_code", "Give the postcode."),
                      ("country", "Give the country, as its two letters, such as BG.")):
        if not out[key]:
            wrong[key] = said
    if out["country"] and not re.fullmatch(r"[A-Z]{2}", out["country"]):
        wrong["country"] = "The country is its two letters, such as BG or GB."
    _refuse_any(wrong)
    return out


def entities_of(who) -> list:
    """This person's billing entities, the first made first."""
    return list(_models().BillingEntity.objects.filter(**_whose(who)).order_by("created_at", "id"))


def entity_of(who, entity_id):
    """One of this person's entities by its id, or None."""
    try:
        entity_id = int(entity_id)
    except (TypeError, ValueError):
        return None
    return _models().BillingEntity.objects.filter(**_whose(who), id=entity_id).first()


def save_entity(who, form: dict):
    """A billing entity added, or the one named by `form["id"]` changed; the row."""
    fields = entity_from(form)
    now = time.time()
    if form.get("id") not in (None, ""):
        row = entity_of(who, form.get("id"))
        if row is None:
            raise Refused("That billing entity is not one of yours.")
        _models().BillingEntity.objects.filter(**_whose(who), id=row.id).update(
            **fields, updated_at=now)
        return entity_of(who, row.id)
    return _models().BillingEntity.objects.create(**_whose(who), **fields, created_at=now,
                                                  updated_at=now)


def delete_entity(who, entity_id):
    """An entity with no cards taken out; the row it was, or None if there is no such one.
    Refused while cards are under it: they are moved or removed first."""
    row = entity_of(who, entity_id)
    if row is None:
        return None
    held = _models().PaymentCard.objects.filter(**_whose(who), entity_id=row.id).count()
    if held:
        raise Refused(f"{row.label} still has {held} card{'' if held == 1 else 's'}. Move "
                      f"{'it' if held == 1 else 'them'} to another entity or remove "
                      f"{'it' if held == 1 else 'them'} first.")
    _models().BillingEntity.objects.filter(**_whose(who), id=row.id).delete()
    return row


def set_card_entity(who, card_id, entity_id):
    """One card moved under another of this person's entities; the card, or None if there
    is no such card of theirs."""
    entity = entity_of(who, entity_id)
    if entity is None:
        raise Refused("That billing entity is not one of yours.")
    try:
        card_id = int(card_id)
    except (TypeError, ValueError):
        return None
    done = _models().PaymentCard.objects.filter(**_whose(who), id=card_id).update(
        entity_id=entity.id)
    return _models().PaymentCard.objects.filter(**_whose(who), id=card_id).first() if done else None


def invoice_lines(entity) -> list[str]:
    """What an invoice to this entity carries, only what is set: the company details and
    the address in one line."""
    if entity is None:
        return []
    lines = [f"{label}: {getattr(entity, key)}" for key, label in INVOICE if getattr(entity, key)]
    lines.append(address_line(entity))
    return lines


def address_line(entity) -> str:
    town = " ".join(x for x in (entity.postal_code, entity.city) if x)
    return ", ".join(x for x in (entity.line1, entity.line2, town, entity.state, entity.country) if x)


def billed_to(entity) -> str:
    """An entity as a purchase and a message name it: its label, and its company if that
    says something more."""
    if entity is None:
        return ""
    company = entity.company
    return entity.label + (f" ({company})" if company and company.lower() != entity.label.lower()
                           else "")


def _sealed_address(row) -> dict:
    """A card's billing address as it was sealed with it before entities, for `carry_over`
    alone: the seal is opened, the address kept and the rest let go at once."""
    try:
        card = json.loads(_box().open_(row.sealed))
    except Exception:  # noqa: BLE001 - a seal that will not open has no address to carry
        log.warning("a card's seal could not be opened to carry its address over (card %s)", row.id)
        return {}
    address = card.get("address") if isinstance(card.get("address"), dict) else {}
    card = None
    return {k: _line(address.get(k)) for k in ADDRESS}


def carry_over(who) -> None:
    """Every card saved before billing entities given one: its sealed billing address made
    an entity, cards with the same address under the same one, so nothing typed is lost.
    A card whose seal holds no address is left for the owner to put under an entity."""
    m = _models()
    loose = list(m.PaymentCard.objects.filter(**_whose(who), entity_id__isnull=True)
                 .order_by("saved_at", "id"))
    if not loose:
        return
    have = entities_of(who)
    labels = {e.label for e in have}
    for card in loose:
        address = _sealed_address(card)
        if not address.get("line1"):
            continue
        address["country"] = address["country"].upper()[:2]
        found = next((e for e in have if not e.company and not e.vat
                      and all(getattr(e, k) == address[k] for k in ADDRESS)), None)
        if found is None:
            label, n = "Billing address", 2
            while label in labels:
                label, n = f"Billing address {n}", n + 1
            now = time.time()
            found = m.BillingEntity.objects.create(**_whose(who), label=label, **address,
                                                   created_at=now, updated_at=now)
            have.append(found)
            labels.add(label)
            log.info("a card's billing address was carried over into entity %s for user %s",
                     found.id, who.user_id)
        m.PaymentCard.objects.filter(**_whose(who), id=card.id).update(entity_id=found.id)


def _silo_said(who, value) -> str:
    """A silo key as picked: one of the account's, or "" for none; Refused otherwise."""
    from . import silos

    key = str(value or "").strip()
    if not key:
        return ""
    if key not in silos.keys(who.user_id, who.org_id):
        raise Refused("That silo is not one of yours. Pick one from the list, or no silo.")
    return key


def save_card(who, form: dict):
    """A new card added to the vault beside the others; the saved row, which holds no digits
    but its last four."""
    wrong = {}
    try:
        silo = _silo_said(who, form.get("silo"))
    except Refused as exc:
        wrong["silo"] = str(exc)
    entity = entity_of(who, form.get("entity"))
    if entity is None:
        wrong["entity"] = NO_ENTITY
    try:
        caps = caps_from(form)
    except Refused as exc:
        wrong.update(exc.fields)
    try:
        card = card_from(form)
    except Refused as exc:
        wrong.update(exc.fields)
    _refuse_any(wrong)
    row = _models().PaymentCard.objects.create(
        **_whose(who), sealed=_box().seal(json.dumps(card)), brand=brand_of(card["number"]),
        last4=card["number"][-4:], name=card["name"], exp_month=card["exp_month"],
        exp_year=card["exp_year"], saved_at=time.time(), silo=silo, entity_id=entity.id,
        **caps)
    card = None
    log.info("a card was saved to the vault for user %s (%s ending %s)", who.user_id,
             row.brand, row.last4)
    return row


def delete_card(who, card_id):
    """One card out of the vault; the row it was, or None if there is no such card of theirs."""
    try:
        card_id = int(card_id)
    except (TypeError, ValueError):
        return None
    row = _models().PaymentCard.objects.filter(**_whose(who), id=card_id).first()
    if row is None:
        return None
    _models().PaymentCard.objects.filter(**_whose(who), id=card_id).delete()
    log.info("a card was deleted from the vault for user %s (%s ending %s)", who.user_id,
             row.brand, row.last4)
    return row


def set_card_silo(who, card_id, silo):
    """One card made a silo's, or no silo's ("" for none); the row, or None if there is no
    such card of theirs."""
    silo = _silo_said(who, silo)
    try:
        card_id = int(card_id)
    except (TypeError, ValueError):
        return None
    done = _models().PaymentCard.objects.filter(**_whose(who), id=card_id).update(silo=silo)
    return _models().PaymentCard.objects.filter(**_whose(who), id=card_id).first() if done else None


def caps_from(form: dict) -> dict:
    """A card's caps as typed, {per_purchase, per_day, per_month}, each dollars or None for
    no cap of that kind, when it is left empty. A Refused names each field that is wrong."""
    out, wrong = {}, {}
    for key, what, _said in CAPS:
        value = form.get(key)
        if value in (None, "") or not str(value).strip():
            out[key] = None
            continue
        try:
            out[key] = quests.money_of(value, what, least="0.01")
        except ValueError as exc:
            wrong[key] = str(exc)
    _refuse_any(wrong)
    return out


def set_card_caps(who, card_id, form: dict):
    """One card's own caps set, each to dollars or to none; the row, or None if there is no
    such card of theirs."""
    caps = caps_from(form)
    try:
        card_id = int(card_id)
    except (TypeError, ValueError):
        return None
    done = _models().PaymentCard.objects.filter(**_whose(who), id=card_id).update(**caps)
    return _models().PaymentCard.objects.filter(**_whose(who), id=card_id).first() if done else None


def _since(period: str) -> float:
    """When today, or this calendar month, began."""
    now = clock.now().replace(hour=0, minute=0, second=0, microsecond=0)
    return (now.replace(day=1) if period == "month" else now).timestamp()


def card_spent(who, card, period: str, *, besides=None) -> Decimal:
    """What has been filled with this card today ("day") or this calendar month ("month"),
    voided purchases aside, and the purchase `besides` too when it is being checked again.
    A purchase from before purchases kept their card is counted by its brand and last four."""
    from django.db.models import Q, Sum

    found = _models().CardCharge.objects.filter(
        Q(card_id=card.id) | Q(card_id__isnull=True, brand=card.brand, last4=card.last4),
        **_whose(who), state__in=COUNTED, at__gte=_since(period))
    if besides is not None:
        found = found.exclude(id=besides)
    return Decimal(found.aggregate(n=Sum("amount"))["n"] or 0)


def caps_said(card) -> str:
    """A card's own caps as every message says them: "at most $100.00 a purchase and
    $100.00 a day", or "" for none."""
    said = [f"{quests.dollars(getattr(card, key))} {per}" for key, _what, per in CAPS
            if getattr(card, key) is not None]
    if not said:
        return ""
    return "at most " + (said[0] if len(said) == 1 else ", ".join(said[:-1]) + " and " + said[-1])


def check_card_caps(who, card, amount: Decimal, *, besides=None) -> None:
    """Refused, saying which, if this purchase would cross one of the card's own caps.
    `besides` is the purchase's own charge when it is checked again at the order button."""
    named = f"the {card.brand} ending {card.last4}"
    if card.per_purchase is not None and amount > Decimal(card.per_purchase):
        raise Refused(f"{quests.dollars(amount)} is over {named}’s cap of "
                      f"{quests.dollars(card.per_purchase)} a purchase. Nothing was filled.")
    for key, period, when in (("per_day", "day", "today"), ("per_month", "month", "this month")):
        cap = getattr(card, key)
        if cap is None:
            continue
        spent = card_spent(who, card, period, besides=besides)
        if spent + amount > Decimal(cap):
            raise Refused(f"{quests.dollars(amount)} would take {named} to "
                          f"{quests.dollars(spent + amount)} {when}, over its cap of "
                          f"{quests.dollars(cap)} a {period} ({quests.dollars(spent)} spent "
                          f"{when}). Nothing was filled.")


def cards_of(who) -> list:
    """This person's cards, the most recently saved first."""
    return list(_models().PaymentCard.objects.filter(**_whose(who)).order_by("-saved_at", "-id"))


def _silo_of(card, have) -> str:
    """A card's silo, if it is still one of the account's: a silo deleted from under it
    leaves the card for none."""
    return card.silo if card.silo and card.silo in have else ""


def _pick(cards: list, have, silos=()):
    """Out of `cards` (most recent first): the most recent of the first of `silos` that has
    one, else the default (the most recent card for no silo, else the most recent)."""
    for key in silos or ():
        for c in cards:
            if _silo_of(c, have) == key:
                return c
    return next((c for c in cards if not _silo_of(c, have)), cards[0])


def card_in_use(who, last4=None, silos=()):
    """The card to fill: the one ending in `last4` if it is said, else the card of the first
    of `silos` that has one, else the default (`_pick`). Refused if there is none."""
    from . import silos as silo_store

    cards = cards_of(who)
    if not cards:
        raise Refused(NO_CARD)
    said = _digits(last4)
    if said:
        cards = [c for c in cards if c.last4 == said[-4:]]
        if not cards:
            raise Refused(NO_SUCH_CARD + " The vault holds "
                          + ", ".join(f"{c.brand} ending {c.last4}" for c in cards_of(who)) + ".")
        return cards[0]
    return _pick(cards, set(silo_store.keys(who.user_id, who.org_id)), silos)


def silos_for(who, *, work=None, chat: str = "", run_id: str = "") -> list[str]:
    """The silos a purchase is made in, for picking its card: its quest's task's, else its
    chat's, else its run's; [] when none says. Never stops a purchase: a lookup that fails
    is no silo."""
    from . import silos

    uid, oid = str(who.user_id), str(who.org_id)
    try:
        if work is not None and work.task_id:
            got = silos.of_owner(uid, oid, "task", work.task_id)[0]
            if got:
                return got
        if chat:
            got = silos.of_chat(uid, oid, chat)[0]
            if got:
                return got
        if run_id:
            return silos.run_silos(uid, oid, [run_id]).get(str(run_id), [])
    except Exception:  # noqa: BLE001 - the default card is filled instead
        log.warning("a purchase's silo could not be read for user %s", uid, exc_info=True)
    return []


def card_said(who, card) -> str:
    """A card as a tool or a message names it: its brand and last four, and its silo's name."""
    from . import silos

    info = silos.by_key(who.user_id, who.org_id).get(card.silo) if card.silo else None
    return f"{card.brand} ending {card.last4}" + (f" ({info.name})" if info else "")


def entity_for(who, card):
    """The billing entity a card belongs to, carried over first if it has none yet; or None."""
    if card.entity_id is None:
        carry_over(who)
        card = _models().PaymentCard.objects.filter(**_whose(who), id=card.id).first() or card
    return entity_of(who, card.entity_id) if card.entity_id is not None else None


def billing_said(entity) -> str:
    """What Rouh is told after a fill about who it is billed to: never a card's digits."""
    if entity is None:
        return ""
    lines = invoice_lines(entity)
    said = f" Billed to {entity.label}: " + "; ".join(lines) + "."
    if entity.company or entity.vat or entity.reg_number:
        said += (" If the checkout asks for any of these where they were not filled, such as "
                 "behind a box for buying as a business, type them in exactly so the invoice "
                 "carries them; leave out what is not listed.")
    return said


def billing_values(who, last4=None, chat: str = "") -> tuple[dict | None, str]:
    """What a checkout's billing address is filled with (`browsing.Desk.fill_shipping`,
    `fill_billing`): the billing entity of the card that will pay, picked as fill_card picks
    it, with the owner's own name and phone as the person buying. Never the delivery address
    (fr_cd4ba48083df). (None, why) when there is no card, or its card has no billing entity
    with an address; a card's digits are never in it."""
    from . import shipping

    try:
        in_silos = [] if _digits(last4) else silos_for(who, chat=chat)
        card = card_in_use(who, last4, in_silos)
    except Refused as exc:
        return None, str(exc)
    entity = entity_for(who, card)
    if entity is None or not entity.line1:
        return None, (f"the {card_said(who, card)} has no billing entity with an address in the "
                      "vault")
    rec = shipping.recipient(who)
    first, _, last = (rec.get("name") or card.name or "").partition(" ")
    values = {k: getattr(entity, k) for k in ADDRESS}
    values.update({k: getattr(entity, k) for k, _label in INVOICE})
    values.update(given_name=first, family_name=last, phone=rec.get("phone") or "",
                  billed_to=billed_to(entity), address=address_line(entity),
                  card=card_said(who, card))
    return values, ""


#: Said when the card that pays has no billing address: Rouh asks rather than guess.
NO_BILLING = ("has no billing address in the vault, so whatever this page bills the order to "
              "would be a guess, and the delivery address is never used in its place. Ask ‹owner› "
              "for the billing address, or ask ‹him› to put the card under its billing entity on "
              "the Payments page, and do not place the order until it is there.")


def billing_wrong(entity, text: str, pay: dict, card_name: str = "the card") -> str:
    """Why an order may not be placed as the page bills it, or "" when it may: the card's
    billing entity has an address, and the billing address the page shows, in words or in
    its billing fields, is that address (fr_cd4ba48083df: BerryBase's "Billing address:
    Same as shipping address", under the office it was delivered to). A page that shows no
    billing address at all is not refused for it."""
    from . import purchases

    if entity is None or not entity.line1:
        return f"{card_name} " + NO_BILLING
    address = {k: getattr(entity, k) for k in ADDRESS}
    shown = purchases.billing_shown(text, address)
    typed = str((pay or {}).get("billed") or "")
    if shown in ("", "yes") and re.search(r"\d", typed) and not purchases.place_shown(typed, address):
        shown = "no"
    if shown not in ("no", "delivery"):
        return ""
    return ((f"the page bills the order to the delivery address (it says the billing address "
             f"is the same as the shipping address), and that is not the billing address of "
             f"{billed_to(entity)}, {address_line(entity)}." if shown == "delivery" else
             f"the billing address on this page is not the one of {billed_to(entity)}, "
             f"{address_line(entity)}.")
            + " Change the page's billing address to it: the shop's own Change billing address "
              "(or its box for a billing address of its own), then browser fill_billing, and "
              "come back to this page. If the page will not take it, tell ‹owner› and hand the "
              "browser over. An order is billed to the delivery address only when that is the "
              "billing address.")


def _open_card(row, entity=None) -> dict:
    """The card itself, for `fill_card` and `fill_card_in_run` and nothing else, with its
    billing entity's address and company details in place of anything sealed with it."""
    if row is None or not row.sealed:
        raise Refused(NO_CARD)
    card = json.loads(_box().open_(row.sealed))
    if entity is not None:
        card["address"] = {k: getattr(entity, k) for k in ADDRESS}
        card["invoice"] = {k: getattr(entity, k) for k, _label in INVOICE}
    # A card typed before the split (migration 0092 moved it as it was) names its parts
    # month, year and csc.
    card.setdefault("exp_month", card.get("month"))
    card.setdefault("exp_year", card.get("year"))
    card.setdefault("cvc", card.get("csc"))
    card.setdefault("address", {})
    return card


def task_ref(said) -> str:
    """A workspace task a purchase is for, as kept with it: "122", or "122-04" for a step;
    "" when nothing that reads as one was said."""
    m = re.search(r"\b(\d{1,5})(?:-(\d{1,3}))?\b", str(said or ""))
    if not m:
        return ""
    return m.group(1) + (f"-{int(m.group(2)):02d}" if m.group(2) else "")


def check_purchase(who, *, amount, work, card) -> Decimal:
    """The amount, if this purchase is inside every one of the card's own caps and the
    quest's; Refused saying which, if not."""
    amount = quests.money_of(amount, "amount", least="0.01")
    check_card_caps(who, card, amount)
    if work is not None:
        if amount > Decimal(work.spend_cap):
            raise Refused(f"{quests.dollars(amount)} is over “{work.title}”'s own cap of "
                          f"{quests.dollars(work.spend_cap)} a purchase. Nothing was filled.")
        if work.budget:
            cash = quests.money(work)
            if amount > cash["left"]:
                raise Refused(f"{quests.dollars(amount)} is more than is left of “{work.title}”'s "
                              f"budget ({quests.dollars(cash['left'])}). Nothing was filled.")
    return amount


async def fill_card(who, desk, chat: str, args: dict, *, work_id=None,
                    phone=None, public_url: str = "") -> str:
    """Fill the checkout page open in the live browser with the vault's card.

    Checked against every cap first, written down before the fill, and told to the owner
    after it. What comes back says the brand, the last four, the merchant and the
    amount, never the card itself.
    """
    from . import untrusted

    purchase = desk.purchase_here(who) if desk is not None else None
    reason = " ".join(str(args.get("reason") or "").split())[:400] or (
        purchase.what if purchase is not None else "")
    if not reason:
        return untrusted.ours("Say why: the step of the work's plan this purchase is for.")
    currency = (str(args.get("currency") or (purchase.currency if purchase else "USD"))
                .strip().upper() or "USD")[:8]
    if purchase is not None and currency != purchase.currency:
        return untrusted.ours(f"The purchase ‹owner› authorized here is in {purchase.currency}, "
                              f"not {currency}. Fill the card in {purchase.currency}.")
    said_work = args.get("quest") or args.get("work")
    task = task_ref(args.get("task"))
    try:
        work, task = await _card_fill_work(who, said_work, task, work_id)
        own, chosen, entity, amount = await _checked_card_fill(who, purchase, args, work, chat)
    except Refused as exc:
        return untrusted.ours(str(exc))
    except ValueError as exc:
        return untrusted.ours(str(exc))
    where = desk.where(who)[0] if desk is not None else ""
    merchant = " ".join(str(args.get("merchant") or "").split())[:120] or (
        urlsplit(where).hostname or "")
    if desk is None or not where:
        return untrusted.ours("The live browser is not open on a checkout page. Open the page "
                              "first, then fill the card.")
    charge, was = await _record_card_fill(
        who, own, work, chosen, entity, amount, currency, merchant, reason, task)

    if work is not None and own is None:
        await asyncio.to_thread(
            quests.ledger_add, who, work.id, direction="out", amount=amount, currency=currency,
            what=f"Card at {charge.merchant}: {reason}"[:300], by="card", ref=f"card-{charge.id}")
    try:
        card = await asyncio.to_thread(_open_card, chosen, entity)
        filled = await desk.fill_card(who, chat, card)
    except Exception as exc:  # noqa: BLE001 - never says the card, only what went wrong
        log.warning("the card could not be filled for user %s: %s", who.user_id,
                    type(exc).__name__)
        await _undo_card_fill(who, charge, was)
        return untrusted.ours("The card could not be filled on that page"
                              + (f": {exc}" if isinstance(exc, Refused) else ".")
                              + (" The order is still submitted and waits to be paid."
                                 if was == "submitted" else
                                 " Nothing was recorded against the caps."))
    finally:
        card = None
    if not filled:
        await _undo_card_fill(who, charge, was)
        return _card_fill_without_fields(purchase, was)
    return await _card_fill_finished(
        who, desk, purchase, chosen, entity, charge, was, filled, amount, currency,
        work, reason, phone, public_url)


async def _card_fill_work(who, said_work, task: str, work_id):
    """Resolve the quest and task before choosing a card or inspecting a charge."""
    work = None
    if said_work not in (None, "") or work_id is not None:
        work = await asyncio.to_thread(
            (lambda: quests.find(who, said_work)) if said_work not in (None, "")
            else (lambda: quests.get(who, work_id)))
        if work is None and work_id is None:
            # Not a quest: a workspace task's number, such as 122, said where a quest's
            # goes. It is kept with the purchase as the task it is for, not refused
            # (the BerryBase checkout, 17 October 2026).
            task = task or task_ref(said_work)
        elif work is None:
            raise Refused("There is no such quest. Name it by its number.")
        else:
            why_not = quests.running(work)
            if why_not and work_id is not None:
                raise Refused(f"“{work.title}”: {why_not}")
    return work, task


async def _checked_card_fill(who, purchase, args: dict, work, chat: str):
    """Reuse the purchase's card when present, then check its billing and caps."""
    # A purchase the owner asked for has one charge, whatever happens: an order submitted at
    # a shop that takes the card afterwards, or an earlier fill on this checkout, is
    # filled into again rather than written down a second time.
    own = (await asyncio.to_thread(
        lambda: _models().CardCharge.objects.filter(
            **_whose(who), id=purchase.charge_id, placed_at__isnull=True,
            state__in=COUNTED).first())
        if purchase is not None and purchase.charge_id is not None else None)
    if own is not None and own.state not in UNPRESSED:
        raise Refused("The payment for this order was already pressed and is "
                      + ("waiting for ‹owner›'s bank approval" if own.state == "bank" else
                         "awaiting the page's confirmation") + f" (charge #{own.id}). "
                      "Nothing was filled: a second payment could pay it twice.")
    if own is not None:
        if _digits(args.get("card")) and _digits(args.get("card"))[-4:] != own.last4:
            raise Refused(f"This order was submitted to be paid with the card ending "
                          f"{own.last4}, so that card is the one filled.")
        chosen = await asyncio.to_thread(
            lambda: _models().PaymentCard.objects.filter(**_whose(who), id=own.card_id).first())
        if chosen is None:
            raise Refused("The card this order was submitted with is no longer in the "
                          "vault. Nothing was filled.")
    else:
        in_silos = ([] if _digits(args.get("card")) else
                    await asyncio.to_thread(silos_for, who, work=work, chat=chat))
        chosen = await asyncio.to_thread(card_in_use, who, args.get("card"), in_silos)
    entity = await asyncio.to_thread(entity_for, who, chosen)
    if own is not None:
        amount = quests.money_of(args.get("amount"), "amount", least="0.01")
        await asyncio.to_thread(check_card_caps, who, chosen, amount, besides=own.id)
    else:
        amount = await asyncio.to_thread(check_purchase, who, amount=args.get("amount"),
                                         work=work, card=chosen)
    return own, chosen, entity, amount


async def _record_card_fill(who, own, work, chosen, entity, amount, currency: str,
                            merchant: str, reason: str, task: str):
    """Write the charge before the ledger and browser, keeping submitted totals."""
    if own is not None:
        charge, was = own, own.state
        await asyncio.to_thread(
            lambda: _models().CardCharge.objects.filter(id=own.id).update(
                state="filled",
                # A submitted order keeps the shop's total until it is paid.
                **({} if was == "submitted" else {"amount": amount}),
                **({"task_ref": task} if task and not own.task_ref else {})))
    else:
        was = ""
        charge = await asyncio.to_thread(
            lambda: _models().CardCharge.objects.create(
                **_whose(who), work_id=work.id if work else None,
                merchant=merchant or "a checkout", amount=amount, currency=currency,
                reason=reason, brand=chosen.brand, last4=chosen.last4, state="filled",
                at=time.time(), billed_to=billed_to(entity), card_id=chosen.id, task_ref=task,
                billing_address=address_line(entity)[:400] if entity is not None else ""))
    return charge, was


async def _undo_card_fill(who, charge, was: str) -> None:
    """Nothing filled: the charge as it was before, or off the caps if it is new."""
    if was:
        await asyncio.to_thread(
            lambda: _models().CardCharge.objects.filter(id=charge.id).update(state=was))
    else:
        await asyncio.to_thread(void_charge, who, charge.id)


def _card_fill_without_fields(purchase, was: str) -> str:
    """Explain the next checkout step for the order's existing state."""
    from . import untrusted

    if was == "submitted":
        return untrusted.ours(
            f"No card fields were found on this page, so nothing was filled. The order is "
            f"submitted at {purchase.site} and waits to be paid by card: go on to the "
            "payment page the shop sends you to (press its button to go on to the "
            "payment if it shows one) and fill the card there.")
    if purchase is not None:
        return untrusted.ours(
            "No card fields were found on that page, so nothing was filled and nothing was "
            "recorded. If this is the shop's last page, with the total, the delivery "
            "address, a card picked as the way to pay and the order button, and the shop "
            "takes the card on its payment page after the order, press the order button "
            "with place_order now; otherwise open the checkout's payment step first.")
    return untrusted.ours("No card fields were found on that page, so nothing was filled "
                          "and nothing was recorded. Open the checkout's payment step first.")


async def _card_fill_finished(who, desk, purchase, chosen, entity, charge, was: str,
                              filled, amount, currency: str, work, reason: str,
                              phone, public_url: str) -> str:
    """Describe the fill, retaining one notice per owner-authorized purchase."""
    from . import untrusted

    log.info("card ending %s filled at %s for %s %s (charge %s, work %s)", chosen.last4,
             charge.merchant, amount, currency, charge.id, work.id if work else "-")
    named = await asyncio.to_thread(card_said, who, chosen)
    note = desk.bill_note(who)
    apart = (f" It {note}, so the order is billed to the card's billing address and not to "
             "where it is delivered." if note else "")
    if entity is None or not entity.line1:
        apart += f" The {named} " + NO_BILLING
    if purchase is not None:
        # A purchase the owner asked for: one notice for it, when the order is placed
        # (`place_order`), not one for the card and another for the order.
        purchase.charge_id, purchase.last4 = charge.id, chosen.last4
        if was == "submitted":
            return untrusted.ours(
                f"Filled the {named} into {', '.join(filled)} on the payment page of the order "
                f"submitted at {purchase.site}, for {amount} {currency}; it is charge "
                f"#{charge.id}, the same one, for the purchase ‹owner› asked for "
                f"({purchase.said()}). Now press this page's Pay button with place_order and its "
                "ref. Do not click it.")
        return untrusted.ours(
            f"Filled the {named} into {', '.join(filled)} at {charge.merchant}, for {amount} "
            f"{currency}; recorded as charge #{charge.id} for the purchase ‹owner› asked for "
            f"({purchase.said()})." + apart + billing_said(entity)
            + " Now tick the shop's own required terms, privacy and withdrawal boxes (never a "
              "newsletter, marketing or account box), go on to the page that shows the order "
              "total and the delivery address, and press the order button with place_order "
              "and its ref. Do not click it.")
    await tell(phone, f"\U0001f4b3 Rouh filled your {named} at "
                      f"{charge.merchant} for {amount} {currency}"
                      + (f", for “{work.title}”" if work else "")
                      + (f", billed to {charge.billed_to}" if charge.billed_to else "")
                      + f".\nWhy: {reason}"
                      + (f"\n\n{public_url}/settings/payments" if public_url else ""))
    return untrusted.ours(
        f"Filled the {named} into {', '.join(filled)} at "
        f"{charge.merchant}, for {amount} {currency}; recorded as charge #{charge.id}"
        + (f" against “{work.title}”" if work else "") + ", and ‹owner› was told." + apart
        + billing_said(entity) + " The last button is still to press, and no purchase "
        "‹owner› asked for covers this site, so it is ‹his›: hand the browser over (in a beat, "
        "queue it with heartbeat_ask). If ‹he› asked for this purchase in ‹his› own words, "
        "authorize_purchase with them first, and place_order presses it after its checks.")


async def place_order(who, desk, chat: str, args: dict, *, phone=None,
                      public_url: str = "") -> str:
    """Press the order button of the purchase the owner authorized on the page open in the live
    browser, once everything `rouh/purchases.py` asks is true; then write it down and tell them.

    Checked here, against what the page shows when the button is about to be pressed
    (`browsing.Desk.place_order`): the card was filled from the vault for this purchase; the
    order total read off the page is inside the card's own caps and within 10% of what was
    expected for the basket; the delivery address shown is one of the owner's shipping
    options; and the billing address shown is the card's billing entity's, never the
    delivery address in its place (`billing_wrong`, fr_cd4ba48083df). Any of them not true
    is a refusal that says which, and nothing is pressed.

    At a shop that takes the card only on its payment provider's page, after its own order
    button, the first press is that button, before any card: the page must show a card
    picked as the way to pay and no card fields, and the caps are those of the card that
    will pay (`_submit`). The second is the provider's Pay, after fill_card there, with the
    same total and cap checks; the address was the shop's page's to show.
    """
    from . import browsing, purchases, shipping, silos, untrusted

    def stop(why: str) -> str:
        return untrusted.ours(f"{browsing.STOPPED} The next step, to place the order, is "
                              f"refused: {why}")

    if desk is None or not desk.where(who)[0]:
        return untrusted.ours("The live browser is not open on a checkout page.")
    purchase = desk.purchase_here(who)
    if purchase is None:
        return stop("no purchase ‹owner› asked for ‹himself› covers this site. If ‹he› asked for it in "
                    "‹his› own words, call authorize_purchase with them; if not, hand the browser "
                    "over, since the order button is ‹his›.")
    m = _models()
    options = await asyncio.to_thread(
        lambda: [shipping.view(r) for r in shipping.option_rows(who, silos.limit_now())])
    said_total = purchases.number(re.sub(r"[^\d.,\s']", "", str(args.get("total") or "")))
    if purchase.charge_id is None:
        return await _submit(who, desk, chat, args, purchase, options, said_total, stop,
                             public_url=public_url)
    charge = await asyncio.to_thread(
        lambda: m.CardCharge.objects.filter(**_whose(who), id=purchase.charge_id).first())
    if charge is not None and charge.state in PRESSED + ("unconfirmed",):
        return stop(f"its payment was already pressed (charge #{charge.id}) and is "
                    + ("waiting for ‹owner›'s bank approval" if charge.state == "bank" else
                       "awaiting the page's confirmation" if charge.state == "confirming" else
                       "not confirmed either way")
                    + ". Pressing again could pay it twice. Never say it is paid until the "
                      "page confirms it.")
    if charge is None or charge.state not in UNPRESSED or getattr(charge, "placed_at", None):
        return stop("the card fill for it was voided or has already been used for an order. "
                    "Fill the card again with fill_card.")
    if charge.state == "submitted":
        return stop(f"the order was already submitted at {purchase.site} and waits to be paid, "
                    "and the card is not in yet. Fill it with fill_card on the payment page the "
                    "shop sent the browser to, then press that page's Pay button with "
                    "place_order.")
    card = await asyncio.to_thread(
        lambda: m.PaymentCard.objects.filter(**_whose(who), id=charge.card_id).first())
    if card is None:
        return stop("the card it was filled with is no longer in the vault.")
    work = await asyncio.to_thread(
        lambda: m.LongWork.objects.filter(**_whose(who), id=charge.work_id).first()
        if charge.work_id else None)
    entity = await asyncio.to_thread(entity_for, who, card)
    named = await asyncio.to_thread(card_said, who, card)
    seen: dict = {}

    async def check(text: str, pay: dict) -> str:
        total, lines = purchases.total_of(text, charge.currency)
        if total is None:
            return stop(f"the order total in {charge.currency} could not be read off this page. "
                        + ("Read the payment page again; if it shows no amount to pay, hand the "
                           "browser over." if purchase.submitted_at else
                           "Go on to the page that shows the order's total and delivery address, "
                           "the last one before the order button, or hand the browser over."))
        where = "; ".join(f"\u201c{w[:80]}\u201d" for w in lines)
        if said_total is not None and abs(said_total - total) > Decimal("0.01"):
            return stop(f"the page's total reads {total} {charge.currency} ({where}), not "
                        f"{said_total}. Read the page again.")
        try:
            await asyncio.to_thread(check_card_caps, who, card, total, besides=charge.id)
        except Refused as exc:
            return stop(str(exc).replace("Nothing was filled.", "Nothing was pressed.")
                        + " Hand the browser over.")
        if work is not None and total > Decimal(work.spend_cap):
            return stop(f"{total} {charge.currency} is over “{work.title}”'s own cap of "
                        f"{quests.dollars(work.spend_cap)} a purchase.")
        if not purchases.close_enough(total, purchase.amount):
            return stop(f"the page's total, {total} {charge.currency} ({where}), is more than "
                        f"{int(purchases.CLOSE * 100)}% away from the {purchase.amount} "
                        f"{purchase.currency} expected for this basket. Check the basket; if "
                        "the price really changed, tell ‹owner› and ask, or hand the browser over.")
        if purchase.submitted_at:
            # The shop's own page showed both addresses when the order was submitted; a
            # payment provider's page shows only what is paid.
            seen.update(total=total, where=where, label=purchase.delivered_to)
            return ""
        option = purchases.address_shown(text, options)
        if option is None:
            return stop("the delivery address on this page is not one of ‹owner›'s shipping "
                        "options. Fill it with fill_shipping, or hand the browser over.")
        wrong = billing_wrong(entity, text, pay, f"the {named}")
        if wrong:
            return stop(wrong)
        seen.update(total=total, where=where, label=option.get("label") or "",
                    delivered=shipping.place_line(option))
        return ""

    try:
        got = await desk.place_order(who, chat, args.get("ref"), check)
    except browsing.CannotBrowse as exc:
        return untrusted.ours(f"Nothing was pressed: {exc}.")
    if not got.get("pressed"):
        said = str(got.get("said") or "Nothing was pressed.")
        if purchase.awaiting:
            said += (f" The order is submitted at {purchase.site} and still unpaid: if it cannot "
                     "be paid, tell ‹owner› plainly that an unpaid order exists there, and hand "
                     "the browser over.")
        return untrusted.ours(said)
    total, now = seen["total"], time.time()
    billing = address_line(entity) if entity is not None else ""
    delivered = seen.get("delivered") or charge.delivered_to or ""
    if purchase.submitted_at:
        billing = charge.billing_address or billing
    # Pressed, and not paid: paid is what the page confirms (`settle`), never the press.
    await asyncio.to_thread(
        lambda: m.CardCharge.objects.filter(id=charge.id).update(
            state="confirming", pressed_at=now, amount=total, bought=purchase.what[:400],
            words=purchase.words[:1000], billing_address=billing[:400],
            delivered_to=(delivered or seen.get("label") or "")[:400]))
    if work is not None:
        await asyncio.to_thread(
            lambda: m.LongWorkLedger.objects.filter(**_whose(who), ref=f"card-{charge.id}")
            .update(amount=total))
    purchase.pressed_at, purchase.outcome = now, ""
    log.info("the payment was pressed at %s for %s %s with the card ending %s (charge %s), on "
             "the person's words; awaiting the page's confirmation", charge.merchant, total,
             charge.currency, card.last4, charge.id)
    outcome, words = got.get("outcome") or "", got.get("words") or ""
    if outcome:
        await settle(who, purchase, outcome, words)
    if purchase.confirming:
        desk.watch(who, purchase)
        # The first answer, if the page gives one soon: most do within seconds.
        waited = time.time() + purchases.CONFIRM_WAIT
        while purchase.confirming and purchase.outcome == "" and time.time() < waited:
            await asyncio.sleep(0.5)
    page = got.get("page") or ""
    if not isinstance(page, untrusted.Ours):
        # The page as it is now, in its own box: only the sentences before it are Rouh's.
        page = untrusted.wrap(page, untrusted.SOURCES["browser"])
    head = (f"Pressed {got.get('name')} for {purchase.what} at {charge.merchant}, {total} "
            f"{charge.currency} (the page's total, {seen['where']}), with the {named}; charge "
            f"#{charge.id}. ")
    if purchase.placed_at is not None:
        billed = (charge.billed_to or "") + (f", {billing}" if billing else "")
        said = (head + "The page confirmed it: it is paid, recorded with ‹his› words, and ‹owner› "
                "was told in one notice. Say it in the chat in one short line: what was "
                "ordered, where, for how much, on which card, who it was billed to"
                + (f" ({billed})" if billed else "") + " and where it goes"
                + f" ({delivered or seen.get('label') or '‹his› shipping option'}).")
    elif purchase.outcome == "failed":
        said = (head + "The page says the payment did not go through: \u201c"
                + purchase.said_words.rstrip(". ") + "\u201d. It is recorded as failed, off the caps, and ‹owner› was told at once. Tell "
                "‹him› in one line exactly what the page says; do not press again unless ‹he› asks"
                + (f", and that the order is still at {purchase.site}, unpaid"
                   if purchase.submitted_at else "") + ".")
    elif purchase.outcome == "bank":
        said = (head + "Nothing is paid yet: the page now asks for ‹owner›'s bank approval "
                "(3-D Secure, ‹his› bank's app or a code), and ‹he› was sent it on Telegram with the "
                "amount and the link. Hand the browser over now with hand_over, saying so, and "
                "never type the code. Do not say it is paid: the browser keeps watching the "
                "page, and only its confirmation makes it paid; ‹he› gets one notice then.")
    else:
        said = (head + "It is pressed and awaiting confirmation: nothing is paid until the "
                "page confirms it. The browser keeps watching the page; ‹owner› gets one notice "
                "once it is confirmed, and is told at once if ‹his› bank asks for ‹him› or it "
                "fails. Say it is pressed and awaiting confirmation, never that it is paid; if "
                "the page asks for anything only ‹he› can do, hand the browser over.")
    return untrusted.ours(said + "\n\n" + page)


async def settle(who, purchase, outcome: str, words: str = "") -> bool:
    """What became of a purchase whose Pay was pressed, written down and told, once each
    (`rouh/purchases.py`, "Paid means confirmed"):

    - "paid": the page confirmed it. The charge "paid" with `placed_at`, and the owner's one
      notice for the order.
    - "failed": the page says it was declined. The charge "failed" with the page's words,
      off the caps and out of its quest's ledger, and the owner told at once.
    - "bank": the page asks for their bank's approval, a code or a captcha. The charge
      "bank", and the owner sent it on Telegram at once with the amount, the shop and the link.
    - "remind": their bank still waits after `purchases.REMIND_MINUTES`: one reminder.
    - "unconfirmed": nothing was seen either way before the browser closed or the
      authorization ran out. The charge "unconfirmed", and the owner told at once to check.

    True when it changed something."""
    from . import notices, purchases

    m = _models()
    if purchase.charge_id is None:
        return False
    cid, now = purchase.charge_id, time.time()
    words = " ".join(str(words or "").split())[:300]
    charge = await asyncio.to_thread(
        lambda: m.CardCharge.objects.filter(**_whose(who), id=cid).first())
    if charge is None:
        return False
    total, currency = charge.amount, charge.currency
    base = str(notices.hooks.public_url or "").rstrip("/")
    if outcome == "paid":
        done = await asyncio.to_thread(
            lambda: m.CardCharge.objects.filter(**_whose(who), id=cid, state__in=PRESSED,
                                                placed_at__isnull=True)
            .update(state="paid", placed_at=now, outcome=words))
        purchase.placed_at, purchase.outcome = now, "paid"
        if not done:
            return False
        card = await asyncio.to_thread(
            lambda: m.PaymentCard.objects.filter(**_whose(who), id=charge.card_id).first())
        named = (await asyncio.to_thread(card_said, who, card) if card is not None else
                 f"{charge.brand} ending {charge.last4}")
        billed = (charge.billed_to or "") + (f", {charge.billing_address}"
                                             if charge.billing_address else "")
        log.info("the payment at %s for %s %s was confirmed by the page (charge %s)",
                 charge.merchant, total, currency, cid)
        await tell(None, f"\U0001f6d2 Rouh ordered {purchase.what} at {charge.merchant} for "
                         f"{total} {currency} on your {named}, and the page confirmed it is paid"
                         + (f".\nBilled to {billed}" if billed else "")
                         + f".\nDelivered to {charge.delivered_to or 'your address'}."
                         + f"\nYou asked: \u201c{purchase.words[:300]}\u201d"
                         + (f"\n\n{base}/settings/payments" if base else ""), who=who)
        return True
    if outcome == "failed":
        done = await asyncio.to_thread(
            lambda: m.CardCharge.objects.filter(**_whose(who), id=cid, state__in=PRESSED)
            .update(state="failed", outcome=words))
        purchase.outcome, purchase.said_words = "failed", words
        purchase.told_unpaid = True
        purchase.expires_at = min(purchase.expires_at, now)
        if not done:
            return False
        await asyncio.to_thread(
            lambda: m.LongWorkLedger.objects.filter(**_whose(who), ref=f"card-{cid}").delete())
        log.warning("the payment at %s for %s %s failed (charge %s): %s", charge.merchant,
                    total, currency, cid, words)
        await tell(None, f"\u274c The payment at {charge.merchant} did not go through: {total} "
                         f"{currency}\nThe page says \u201c{words.rstrip('. ')}\u201d. "
                         "Nothing was paid"
                         + (f", and {purchase.site} still has the order, unpaid: pay it from "
                            "your account there, or ask them to cancel it."
                            if purchase.submitted_at else ".")
                         + (f"\n\n{base}/settings/payments" if base else ""),
                   who=who, at_once=True)
        return True
    if outcome == "bank":
        done = await asyncio.to_thread(
            lambda: m.CardCharge.objects.filter(**_whose(who), id=cid, state="confirming")
            .update(state="bank", outcome=words))
        purchase.outcome, purchase.said_words = "bank", words
        purchase.bank_at = purchase.bank_at or now
        if not done:
            return False
        log.info("the payment at %s for %s %s waits for the person's bank approval (charge %s)",
                 charge.merchant, total, currency, cid)
        await tell(None, purchases.bank_said(purchase, total, currency, words,
                                             f"{base}/browser" if base else ""),
                   who=who, link="/browser", at_once=True, key=f"bank:{cid}")
        return True
    if outcome == "remind":
        if purchase.outcome != "bank" or purchase.placed_at is not None:
            return False
        await tell(None, purchases.remind_said(purchase, total, currency,
                                               f"{base}/browser" if base else ""),
                   who=who, link="/browser", at_once=True, key=f"bank-remind:{cid}")
        return True
    if outcome == "unconfirmed":
        done = await asyncio.to_thread(
            lambda: m.CardCharge.objects.filter(**_whose(who), id=cid, state="confirming")
            .update(state="unconfirmed", outcome=words))
        purchase.outcome = "unconfirmed"
        if not done:
            return False
        log.warning("the payment at %s for %s %s was never confirmed (charge %s): %s",
                    charge.merchant, total, currency, cid, words)
        await tell(None, unconfirmed_said(charge, words), who=who, link="/settings/payments",
                   at_once=True)
        return True
    return False


def unconfirmed_said(charge, why: str) -> str:
    return (f"\u26a0\ufe0f Payment not confirmed at {charge.merchant}: {charge.amount} "
            f"{charge.currency}\nRouh pressed Pay for {charge.bought or charge.reason}, but "
            f"{why} before the page said whether it went through. Check the shop's order or "
            "your bank, and mark it on the Payments page.")


async def _submit(who, desk, chat: str, args: dict, purchase, options: list, said_total,
                  stop, *, public_url: str = "") -> str:
    """The order button of a shop that takes the card on its payment provider's page after
    it, pressed before any card is filled (`rouh/purchases.py`, "Shops that take the card
    after the order button").

    Only when the page shows a card picked as the way to pay and no card fields: a page with
    card fields is fill_card's first. The card that will pay is picked now, as fill_card
    picks it, and the page's total is checked against its caps and the basket, the delivery
    address against the owner's options and the billing address against the card's billing
    entity (`billing_wrong`), exactly as for any order. Its one charge is written before the
    press, as "submitted", with both addresses, and filled into on the payment page afterwards.
    """
    from . import browsing, purchases, shipping, untrusted

    m = _models()
    try:
        in_silos = ([] if _digits(args.get("card")) else
                    await asyncio.to_thread(silos_for, who, chat=chat))
        chosen = await asyncio.to_thread(card_in_use, who, args.get("card"), in_silos)
        entity = await asyncio.to_thread(entity_for, who, chosen)
        named = await asyncio.to_thread(card_said, who, chosen)
    except Refused as exc:
        return stop(f"{exc} Nothing was pressed.")
    currency = purchase.currency
    seen: dict = {}

    async def check(text: str, pay: dict) -> str:
        if pay.get("card_fields"):
            return stop("the card was not filled for this purchase, and this page has card "
                        "fields. Fill them with fill_card first, then press the order button "
                        "with place_order.")
        card, method = purchases.card_method(pay.get("picked") or [], text)
        if not card:
            return stop("the card was not filled for this purchase, and this page does not show "
                        "a card picked as the way to pay"
                        + (f" (it shows {method!r})" if method else "")
                        + ". Pick the shop's credit or debit card payment and come back to this "
                          "page, or, where the page has card fields, fill them with fill_card. "
                          "Any other way to pay is ‹owner›'s: hand the browser over.")
        total, lines = purchases.total_of(text, currency)
        if total is None:
            return stop(f"the order total in {currency} could not be read off this page. Go on "
                        "to the page that shows the order's total and delivery address, the "
                        "last one before the order button, or hand the browser over.")
        where = "; ".join(f"\u201c{w[:80]}\u201d" for w in lines)
        if said_total is not None and abs(said_total - total) > Decimal("0.01"):
            return stop(f"the page's total reads {total} {currency} ({where}), not "
                        f"{said_total}. Read the page again.")
        try:
            await asyncio.to_thread(check_card_caps, who, chosen, total)
        except Refused as exc:
            return stop(str(exc).replace("Nothing was filled.", "Nothing was pressed.")
                        + " Hand the browser over.")
        if not purchases.close_enough(total, purchase.amount):
            return stop(f"the page's total, {total} {currency} ({where}), is more than "
                        f"{int(purchases.CLOSE * 100)}% away from the {purchase.amount} "
                        f"{purchase.currency} expected for this basket. Check the basket; if "
                        "the price really changed, tell ‹owner› and ask, or hand the browser over.")
        option = purchases.address_shown(text, options)
        if option is None:
            return stop("the delivery address on this page is not one of ‹owner›'s shipping "
                        "options. Fill it with fill_shipping, or hand the browser over.")
        wrong = billing_wrong(entity, text, pay, f"the {named}")
        if wrong:
            return stop(wrong)
        merchant = (" ".join(str(args.get("merchant") or "").split())[:120]
                    or urlsplit(desk.where(who)[0]).hostname or purchase.site)
        now = time.time()
        # Written before the press, so the caps count it whatever the shop does next.
        seen["charge"] = await asyncio.to_thread(
            lambda: m.CardCharge.objects.create(
                **_whose(who), merchant=merchant, amount=total, currency=currency,
                reason=purchase.what[:400], brand=chosen.brand, last4=chosen.last4,
                state="submitted", at=now, billed_to=billed_to(entity), card_id=chosen.id,
                submitted_at=now, bought=purchase.what[:400], words=purchase.words[:1000],
                task_ref=task_ref(args.get("task")),
                billing_address=address_line(entity)[:400] if entity is not None else "",
                delivered_to=shipping.place_line(option)[:400]))
        seen.update(total=total, where=where, option=option, method=method)
        return ""

    try:
        got = await desk.place_order(who, chat, args.get("ref"), check)
    except browsing.CannotBrowse as exc:
        got = {"pressed": False, "said": f"Nothing was pressed: {exc}."}
    charge = seen.get("charge")
    if not got.get("pressed"):
        if charge is not None:
            await asyncio.to_thread(void_charge, who, charge.id)
        said = str(got.get("said") or "Nothing was pressed.")
        return said if isinstance(said, untrusted.Ours) else untrusted.ours(said)
    total, option = seen["total"], seen["option"]
    purchase.submitted_at, purchase.submitted_total = charge.submitted_at, total
    purchase.charge_id, purchase.last4 = charge.id, chosen.last4
    purchase.delivered_to = option.get("label") or ""
    purchase.touched_at = time.time()
    log.info("an order was submitted at %s for %s %s, to be paid with the card ending %s on "
             "its payment page (charge %s), on the person's words", charge.merchant, total,
             currency, chosen.last4, charge.id)
    page = got.get("page") or ""
    if not isinstance(page, untrusted.Ours):
        page = untrusted.wrap(page, untrusted.SOURCES["browser"])
    site = got.get("site") or ""
    if got.get("bank"):
        nxt = (" The page now asks for the bank's approval, 3-D Secure or a code: that step is "
               "‹owner›'s. Hand the browser over now with hand_over, saying so, and that the order "
               "is submitted and not paid yet.")
    elif site and site != purchase.site and purchase.covers(site):
        nxt = (f" The shop sent the browser on to its payment page, on {site}. Fill the card "
               f"there with fill_card (amount {total}, currency {currency}), then press its Pay "
               "button with place_order and its ref.")
    else:
        nxt = (f" The page is still on {purchase.site}. If it shows a button that goes on to "
               "the payment, press it with click; on the payment page, fill the card with "
               f"fill_card (amount {total}, currency {currency}) and press its Pay button with "
               "place_order.")
    return untrusted.ours(
        f"Pressed {got.get('name')}: the order for {purchase.what} is submitted at "
        f"{charge.merchant} for {total} {currency} (the page's total, {seen['where']}), paid by "
        f"{seen['method'] or 'card'}, "
        + (f"billed to {billed_to(entity)}, {address_line(entity)}, " if entity is not None else "")
        + f"delivered to {shipping.place_line(option)}. "
        f"It is in the payments ledger once, as charge #{charge.id}, submitted and awaiting "
        f"payment with the {await asyncio.to_thread(card_said, who, chosen)}." + nxt
        + " Do not tell ‹owner› yet: ‹he› gets one notice once it is paid. If it cannot be paid, "
          f"tell ‹him› plainly that an unpaid order exists at {purchase.site}, and hand the "
          "browser over.\n\n" + page)


async def left_unpaid(who, purchase, why: str) -> bool:
    """An order submitted at a shop and then not paid: its charge "unpaid", off the caps,
    and the owner told plainly that the shop has an unpaid order. Once: a charge already paid,
    voided or told is left alone."""
    from . import purchases

    m = _models()
    if purchase.charge_id is None:
        return False
    done = await asyncio.to_thread(
        lambda: m.CardCharge.objects.filter(
            **_whose(who), id=purchase.charge_id, placed_at__isnull=True,
            submitted_at__isnull=False, state__in=UNPRESSED).update(state="unpaid"))
    if not done:
        return False
    log.warning("an order submitted at %s was left unpaid (charge %s): %s", purchase.site,
                purchase.charge_id, why)
    await tell(None, "\u26a0\ufe0f " + purchases.unpaid_said(purchase)
               + f" ({why[:1].upper() + why[1:]}.)"
               + (" If you paid it yourself while you had the browser, there is nothing to do."
                  if purchase.handed else ""), who=who, link="/settings/payments", at_once=True)
    return True


def unpaid_after_restart() -> list:
    """Orders submitted at a shop and not paid when Rouh last stopped: the purchase that
    would have paid them was in the browser's memory, which a restart empties. Each is
    "unpaid" now, and comes back for its owner to be told about (`tell_unpaid_after_restart`)."""
    m = _models()
    rows = list(m.CardCharge.objects.filter(submitted_at__isnull=False, placed_at__isnull=True,
                                            state__in=UNPRESSED))
    left = []
    for row in rows:
        if m.CardCharge.objects.filter(id=row.id, state__in=UNPRESSED).update(state="unpaid"):
            left.append(row)
    return left


def unconfirmed_after_restart() -> list:
    """Payments pressed and still awaiting the page's confirmation when Rouh last stopped:
    the watch on their pages went with it. Each is "unconfirmed" now. One waiting for
    the owner's bank stays "bank": they were told, and settle it on the Payments page."""
    m = _models()
    left = []
    for row in m.CardCharge.objects.filter(state="confirming"):
        if m.CardCharge.objects.filter(id=row.id, state="confirming").update(
                state="unconfirmed", outcome="Rouh restarted"):
            left.append(row)
    return left


async def tell_unpaid_after_restart() -> int:
    """Every order a restart left unpaid, and every payment it left unconfirmed, told to its
    owner plainly, once."""
    from types import SimpleNamespace

    for row in await asyncio.to_thread(unconfirmed_after_restart):
        log.warning("the payment at %s was left unconfirmed by a restart (charge %s)",
                    row.merchant, row.id)
        await tell(None, unconfirmed_said(row, "Rouh restarted"),
                   who=SimpleNamespace(org_id=row.org_id, user_id=row.user_id),
                   link="/settings/payments", at_once=True)
    left = await asyncio.to_thread(unpaid_after_restart)
    for row in left:
        log.warning("an order submitted at %s was left unpaid by a restart (charge %s)",
                    row.merchant, row.id)
        await tell(None, f"\u26a0\ufe0f Unpaid order at {row.merchant}\nRouh placed the order "
                         f"for {row.bought or row.reason} ({row.amount} {row.currency}), but it "
                         "was not paid, because Rouh restarted before paying. The shop has the "
                         "order and is waiting for the money: pay it from your account there, "
                         "or ask them to cancel it.",
                   who=SimpleNamespace(org_id=row.org_id, user_id=row.user_id),
                   link="/settings/payments", at_once=True)
    return len(left)


def spent_by_run(who, run_id: str) -> Decimal:
    """What a run of the one program has had filled in with the card, voided purchases aside."""
    from django.db.models import Sum

    if not run_id:
        return Decimal(0)
    found = _models().CardCharge.objects.filter(
        **_whose(who), run_id=str(run_id), state="filled").aggregate(n=Sum("amount"))["n"]
    return Decimal(found or 0)


async def fill_card_in_run(who, *, run_id: str, port: int, amount, currency: str = "USD",
                           merchant: str, reason: str, address: str = "", press: str = "",
                           phone=None, public_url: str = "", why_for: str = "") -> dict:
    """Fill the vault's card into the checkout open in a run's own browser, and press.

    For the nightly feature run (`rouh/nightly_feature.py`), which has checked its own cap
    a run and its two services before this. Here are the vault's caps, checked first; the
    purchase written down against the run before the card is opened; the card filled and
    the run's button pressed (`browsing.fill_card_over_cdp`); the owner told on Telegram. A
    fill that found no card fields voids the purchase again. Answers {"ok", "said",
    "charge"}; what is said names the brand and the last four, never the card.
    """
    from . import browsing

    reason = " ".join(str(reason or "").split())[:400]
    merchant = " ".join(str(merchant or "").split())[:120]
    currency = (str(currency or "USD").strip().upper() or "USD")[:8]
    press = " ".join(str(press or "").split())[:120]
    if not reason or not merchant:
        return {"ok": False, "said": "Say the merchant and why: the service and what it is for."}
    if not press:
        return {"ok": False, "said": "Say press: the words on the button that pays, such as "
                                     "Subscribe or Pay now. The card is filled in and that "
                                     "button pressed in one step, so the card is never left on "
                                     "the page for you to read."}
    try:
        try:
            in_silos = await asyncio.to_thread(silos_for, who, run_id=str(run_id))
            chosen = await asyncio.to_thread(card_in_use, who, None, in_silos)
            entity = await asyncio.to_thread(entity_for, who, chosen)
        except Refused:
            raise Refused(NO_CARD + " Write the service down as waiting for a card, and carry "
                          "on: a sign-up that needs no card does not wait for one.") from None
        value = await asyncio.to_thread(check_purchase, who, amount=amount, work=None,
                                        card=chosen)
    except (Refused, ValueError) as exc:
        return {"ok": False, "said": str(exc)}
    charge = await asyncio.to_thread(
        lambda: _models().CardCharge.objects.create(
            **_whose(who), work_id=None, merchant=merchant, amount=value, currency=currency,
            reason=reason, brand=chosen.brand, last4=chosen.last4, state="filled",
            at=time.time(), run_id=str(run_id), billed_to=billed_to(entity), card_id=chosen.id))
    try:
        card = await asyncio.to_thread(_open_card, chosen, entity)
        got = await browsing.fill_card_over_cdp(port, card, address=address, press=press)
    except Exception as exc:  # noqa: BLE001 - never says the card, only what went wrong
        log.warning("the card could not be filled into run %s's browser: %s", run_id,
                    type(exc).__name__)
        await asyncio.to_thread(void_charge, who, charge.id)
        return {"ok": False, "said": "The card could not be filled in"
                + (f": {exc}" if isinstance(exc, (Refused, browsing.CannotBrowse)) else
                   f" ({type(exc).__name__}).")
                + " Nothing was recorded against the caps."}
    finally:
        card = None
    if not got["filled"]:
        await asyncio.to_thread(void_charge, who, charge.id)
        return {"ok": False, "said": "No card fields were found on that page, so nothing was "
                                     "filled and nothing was recorded. Open the checkout's "
                                     "payment step first."}
    if not got["pressed"]:
        await asyncio.to_thread(void_charge, who, charge.id)
        return {"ok": False, "said": f"No button or link saying “{press}” was found on that page, "
                                     "so nothing was pressed, the card's fields were emptied "
                                     "again and nothing was recorded. Say the button's words "
                                     "exactly as the page shows them."}
    log.info("card ending %s filled into run %s's browser at %s for %s %s (charge %s)",
             chosen.last4, run_id, merchant, value, currency, charge.id)
    named = await asyncio.to_thread(card_said, who, chosen)
    await tell(phone, f"\U0001f4b3 Rouh filled your {named} at "
                      f"{merchant} for {value} {currency}, for {why_for or 'run ' + run_id}"
                      + (f", billed to {charge.billed_to}" if charge.billed_to else "") + "."
                      f"\nWhy: {reason}"
                      + (f"\n\n{public_url}/anatomy/money/payments" if public_url else ""))
    said = (f"Filled the {named} into "
            f"{', '.join(got['filled'])} at {merchant}, for {value} {currency}, and pressed "
            f"“{press}”; recorded as charge #{charge.id}, and ‹owner› was told."
            + billing_said(entity) + " ")
    if got["cleared"]:
        said += ("The card's fields were still on the page afterwards, so they were emptied: "
                 "read the page for whether it went through. If it did not, void the charge "
                 "with nightly_pay, action void, so it is off the caps. ")
    said += f"The page is now {got['url']}" + (f" ({got['title']})" if got["title"] else "") + "."
    return {"ok": True, "said": said, "charge": charge.id}


def paid_charge(who, charge_id) -> bool:
    """A payment the owner says went through, which the page never confirmed to Rouh: one
    waiting for their bank, or pressed and never confirmed either way."""
    done = _models().CardCharge.objects.filter(
        **_whose(who), id=charge_id, state__in=PRESSED + ("unconfirmed",)).update(
        state="paid", placed_at=time.time(), outcome=owner.say("Marked as paid by ‹owner›", who))
    return bool(done)


def void_charge(who, charge_id) -> bool:
    """A purchase that never went through: off the caps and out of its work's ledger."""
    m = _models()
    done = m.CardCharge.objects.filter(**_whose(who), id=charge_id,
                                       state__in=COUNTED).update(state="void")
    if done:
        m.LongWorkLedger.objects.filter(**_whose(who), ref=f"card-{charge_id}").delete()
    return bool(done)


async def tell(phone, text: str, *, who=None, link: str = "", at_once: bool = False,
               key: str = "") -> None:
    """The owner told: on their screen first, and on Telegram if it is left there
    (`rouh/notices.py`), or on Telegram at once too for what cannot wait (`at_once`: their
    bank's approval, a payment that failed or was left unpaid). Never a card's digits."""
    from . import notices

    if await notices.phone(text[:3500], kind="payment", who=who, link=link, key=key,
                           at_once=at_once) is None:
        log.warning("a payments message could not be given")


# --- Stripe ---------------------------------------------------------------------------------


def _hint(key: str) -> str:
    head = "rk_live_" if key.startswith("rk_live_") else "rk_test_" if key.startswith("rk_test_") \
        else key[:8]
    return f"{head}…{key[-4:]}"


def save_stripe_key(who, key: str) -> dict:
    key = str(key or "").strip()
    if not re.fullmatch(r"(rk|sk)_(test|live)_[A-Za-z0-9]{10,200}", key):
        raise Refused(fields={"key": "That is not a Stripe key. A restricted key starts rk_test_ "
                                     "or rk_live_."})
    if key.startswith("sk_"):
        raise Refused(fields={"key": "That is a secret key, which can do everything. Make a "
                                     "restricted key with only the permissions listed here, and "
                                     "give that instead."})
    row = settings_of(who)
    _save(row, stripe_sealed=_box().seal(key), stripe_hint=_hint(key),
          stripe_mode="live" if "_live_" in key else "test", stripe_saved_at=time.time())
    log.info("a Stripe key was saved for user %s (%s)", who.user_id, row.stripe_mode)
    return public(who)


def delete_stripe_key(who) -> dict:
    row = settings_of(who)
    _save(row, stripe_sealed="", stripe_hint="", stripe_mode="", stripe_saved_at=0,
          hook_id="", hook_url="", hook_sealed="", hook_saved_at=0)
    return public(who)


class Stripe:
    """Stripe's API with one person's restricted key, which never leaves this object."""

    def __init__(self, key: str) -> None:
        self._key = key

    async def call(self, method: str, path: str, data: dict | None = None) -> dict:
        import httpx

        flat = _form(data or {})
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                r = await client.request(
                    method, f"{STRIPE_API}/v1/{path.lstrip('/')}", auth=(self._key, ""),
                    data=flat if method == "POST" else None,
                    params=flat if method == "GET" else None)
        except httpx.HTTPError as exc:
            raise Refused(f"Stripe could not be reached: {type(exc).__name__}.") from None
        try:
            body = r.json()
        except ValueError:
            body = {}
        if r.status_code >= 400:
            err = (body.get("error") or {}) if isinstance(body, dict) else {}
            said = str(err.get("message") or f"it answered {r.status_code}")
            raise Refused("Stripe said: " + said.replace(self._key, "[key]")[:400])
        return body if isinstance(body, dict) else {}


def _form(data: dict, prefix: str = "") -> dict:
    """Stripe's form encoding: metadata[work]=3, line_items[0][price]=..."""
    out = {}
    for key, value in data.items():
        name = f"{prefix}[{key}]" if prefix else str(key)
        if isinstance(value, dict):
            out.update(_form(value, name))
        elif isinstance(value, list):
            for i, item in enumerate(value):
                if isinstance(item, dict):
                    out.update(_form(item, f"{name}[{i}]"))
                else:
                    out[f"{name}[{i}]"] = str(item)
        elif isinstance(value, bool):
            out[name] = "true" if value else "false"
        elif value is not None:
            out[name] = str(value)
    return out


def stripe_for(who) -> Stripe:
    row = settings_of(who)
    if not row.stripe_sealed:
        raise Refused(NO_KEY)
    return Stripe(_box().open_(row.stripe_sealed))


def _link(who, work, kind: str, stripe_id: str, name: str = "", url: str = "") -> None:
    _models().StripeLink.objects.create(**_whose(who), work_id=work.id if work else None,
                                        kind=kind, stripe_id=stripe_id, name=name[:200],
                                        url=url[:500], at=time.time())


def _cents(amount, currency: str) -> int:
    """The amount in the currency's smallest unit, as Stripe counts it."""
    value = quests.money_of(amount, "amount", least="0.01")
    if currency.lower() in ZERO_DECIMAL:
        return int(value.to_integral_value())
    return int((value * 100).to_integral_value())


#: Currencies Stripe counts in whole units.
ZERO_DECIMAL = frozenset({"bif", "clp", "djf", "gnf", "jpy", "kmf", "krw", "mga", "pyg", "rwf",
                          "ugx", "vnd", "vuv", "xaf", "xof", "xpf"})


async def stripe_act(who, args: dict, *, work_id=None, approved: bool = False,
                     queue=None) -> str:
    """One `stripe` tool call: status, list, create_product, create_price,
    create_payment_link, payments, balance, refund."""
    action = str(args.get("action") or "status").strip().lower()
    try:
        if action == "status":
            return await asyncio.to_thread(status_line, who)
        said_work = args.get("quest") or args.get("work")
        if said_work not in (None, ""):
            work = await asyncio.to_thread(quests.find, who, said_work)
        else:
            work = (await asyncio.to_thread(quests.get, who, work_id)
                    if work_id is not None else None)
        if (said_work not in (None, "") or work_id is not None) and work is None:
            raise Refused("There is no such quest. Name it by its number.")
        if action == "list":
            return await asyncio.to_thread(_list_links, who, work)
        stripe = await asyncio.to_thread(stripe_for, who)
        meta = {"rouh_work": str(work.id)} if work else {}
        if action == "create_product":
            name = " ".join(str(args.get("name") or "").split())[:200]
            if not name:
                raise Refused("Give the product a name.")
            got = await stripe.call("POST", "products", {
                "name": name, "description": str(args.get("description") or "")[:1000] or None,
                "metadata": meta})
            await asyncio.to_thread(_link, who, work, "product", got.get("id", ""), name)
            return (f"Made the product “{name}”, {got.get('id')}"
                    + (f", for “{work.title}”" if work else "") + ".")
        if action == "create_price":
            product = str(args.get("product") or "").strip()
            if not product.startswith("prod_"):
                raise Refused("product is the product's id, prod_...")
            currency = (str(args.get("currency") or "usd").strip().lower() or "usd")[:3]
            data = {"product": product, "currency": currency,
                    "unit_amount": _cents(args.get("amount"), currency), "metadata": meta}
            if args.get("recurring") in ("month", "year", "week", "day"):
                data["recurring"] = {"interval": args["recurring"]}
            got = await stripe.call("POST", "prices", data)
            await asyncio.to_thread(_link, who, work, "price", got.get("id", ""))
            return (f"Made the price {got.get('id')}: {args.get('amount')} "
                    f"{currency.upper()} for {product}.")
        if action == "create_payment_link":
            price = str(args.get("price") or "").strip()
            if not price.startswith("price_"):
                raise Refused("price is the price's id, price_...")
            quantity = max(1, min(100, int(args.get("quantity") or 1)))
            got = await stripe.call("POST", "payment_links", {
                "line_items": [{"price": price, "quantity": quantity}], "metadata": meta})
            await asyncio.to_thread(_link, who, work, "payment_link", got.get("id", ""),
                                    url=str(got.get("url") or ""))
            return (f"Made the payment link {got.get('url')} ({got.get('id')})"
                    + (f", for “{work.title}”: what is paid through it goes in its ledger"
                       if work else "") + ".")
        if action == "balance":
            got = await stripe.call("GET", "balance")
            parts = [f"{b.get('amount', 0) / 100:.2f} {str(b.get('currency', '')).upper()}"
                     for b in got.get("available") or []]
            pend = [f"{b.get('amount', 0) / 100:.2f} {str(b.get('currency', '')).upper()}"
                    for b in got.get("pending") or []]
            return ("Stripe balance: available " + (", ".join(parts) or "nothing")
                    + "; pending " + (", ".join(pend) or "nothing") + ".")
        if action == "payments":
            got = await stripe.call("GET", "payment_intents", {"limit": 20})
            lines = []
            for p in got.get("data") or []:
                lines.append(f"{p.get('id')}: {p.get('amount', 0) / 100:.2f} "
                             f"{str(p.get('currency', '')).upper()}, {p.get('status')}, "
                             f"{clock.clock(p.get('created'))}")
            return "Recent payments:\n" + ("\n".join(lines) or "none yet.")
        if action == "refund":
            target = str(args.get("payment") or "").strip()
            if not target.startswith(("pi_", "ch_")):
                raise Refused("payment is the payment's id, pi_... or ch_...")
            if not approved:
                return await queue_refund(who, args, target, work, queue)
            data = {"payment_intent" if target.startswith("pi_") else "charge": target}
            if args.get("amount") not in (None, ""):
                data["amount"] = _cents(args.get("amount"), "usd")
            got = await stripe.call("POST", "refunds", data)
            return f"Refunded: {got.get('id')}, {got.get('status')}."
        if action in ("payout", "payouts", "transfer", "account"):
            raise Refused("Payouts, transfers and account changes are ‹owner›'s, in Stripe "
                          "itself; the key has no access to them.")
        return ("action is status, list, create_product, create_price, create_payment_link, "
                "payments, balance or refund.")
    except Refused as exc:
        return str(exc)


async def queue_refund(who, args: dict, target: str, work, queue) -> str:
    """A refund goes to the approval queue and runs only on the owner's yes."""
    if queue is None:
        return "A refund waits for ‹owner›'s yes, and there is no approval queue here."
    ident = await queue(
        tool="stripe", args={**args, "action": "refund"},
        what=f"Refund Stripe payment {target}"
             + (f" ({args.get('amount')})" if args.get("amount") else " in full"),
        to_whom="the customer who paid", why=str(args.get("why") or args.get("reason") or "")[:500]
        or "Asked for in conversation.", cost="the refunded amount", work=work)
    return (f"A refund is never made without ‹owner›'s yes: it is queued as #{ident} on the "
            "Heartbeat page, and runs exactly as asked when ‹he› says yes.")


def _list_links(who, work) -> str:
    rows = _models().StripeLink.objects.filter(**_whose(who))
    if work is not None:
        rows = rows.filter(work_id=work.id)
    rows = list(rows.order_by("-at")[:40])
    if not rows:
        return "Rouh has made nothing in Stripe yet."
    return "\n".join(f"{r.kind} {r.stripe_id}" + (f" “{r.name}”" if r.name else "")
                     + (f" {r.url}" if r.url else "") + (f" (work #{r.work_id})" if r.work_id else "")
                     for r in rows)


# --- the webhook ------------------------------------------------------------------------------


async def make_webhook(who, public_url: str) -> dict:
    """Rouh's own webhook endpoint in Stripe, at the address Rouh is served on, its signing
    secret sealed. Made again when it is pressed again."""
    if not public_url.startswith(("https://", "http://")):
        raise Refused("Rouh does not know the address it is served on, so Stripe has nowhere "
                      "to send its events.")
    row = await asyncio.to_thread(settings_of, who)
    stripe = await asyncio.to_thread(stripe_for, who)
    token = row.hook_token or secrets.token_urlsafe(24)
    url = public_url.rstrip("/") + HOOK_ROUTE + token
    if row.hook_id:
        try:
            await stripe.call("DELETE", f"webhook_endpoints/{row.hook_id}")
        except Refused:
            pass
    got = await stripe.call("POST", "webhook_endpoints", {
        "url": url, "enabled_events": list(HOOK_EVENTS),
        "description": "Rouh: payments for its quests"})
    secret = str(got.get("secret") or "")
    if not secret.startswith("whsec_"):
        raise Refused("Stripe made the endpoint but gave no signing secret.")
    await asyncio.to_thread(_save, row, hook_token=token, hook_id=str(got.get("id") or ""),
                            hook_url=url, hook_sealed=_box().seal(secret),
                            hook_saved_at=time.time())
    log.info("a Stripe webhook was made for user %s: %s", who.user_id, got.get("id"))
    return await asyncio.to_thread(public, who)


def verify(secret: str, payload: bytes, header: str, now: float | None = None) -> bool:
    """Whether the Stripe-Signature header is Stripe's own for this payload, and fresh."""
    now = time.time() if now is None else now
    parts: dict[str, list[str]] = {}
    for piece in str(header or "").split(","):
        if "=" in piece:
            k, v = piece.split("=", 1)
            parts.setdefault(k.strip(), []).append(v.strip())
    try:
        stamp = int(parts.get("t", [""])[0])
    except ValueError:
        return False
    if abs(now - stamp) > HOOK_TOLERANCE:
        return False
    signed = f"{stamp}.".encode() + payload
    want = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(want, sig) for sig in parts.get("v1", []))


def hook_owner(token: str):
    """Whose webhook this address is, or None."""
    if not token or len(token) > 100:
        return None
    return _models().PaymentSettings.objects.filter(hook_token=token).exclude(hook_sealed="").first()


def take_event(row, payload: bytes, header: str) -> tuple[int, dict | None]:
    """A webhook's event: (status for Stripe, the payment written down or None)."""
    try:
        secret = _box().open_(row.hook_sealed)
    except Exception:  # noqa: BLE001 - a secret that will not open is no secret
        return 400, None
    if not verify(secret, payload, header):
        log.warning("a Stripe event with a bad signature was refused (user %s)", row.user_id)
        return 400, None
    try:
        event = json.loads(payload.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return 400, None
    kind = str(event.get("type") or "")
    obj = (event.get("data") or {}).get("object") or {}
    if kind == "checkout.session.completed":
        if obj.get("payment_status") not in ("paid", "no_payment_required"):
            return 200, None
        return 200, _money_in(row, ref=str(obj.get("payment_intent") or obj.get("id") or ""),
                              amount=obj.get("amount_total"), currency=obj.get("currency"),
                              meta=obj.get("metadata") or {},
                              link=str(obj.get("payment_link") or ""),
                              who_paid=(obj.get("customer_details") or {}).get("email") or "")
    if kind == "payment_intent.succeeded":
        return 200, _money_in(row, ref=str(obj.get("id") or ""), amount=obj.get("amount_received")
                              or obj.get("amount"), currency=obj.get("currency"),
                              meta=obj.get("metadata") or {}, link="", who_paid="")
    return 200, None


def _money_in(row, *, ref: str, amount, currency, meta: dict, link: str, who_paid: str):
    """One payment written as money in, against the work whose product or link it came from."""
    from django.db import IntegrityError

    if not ref:
        return None
    m = _models()
    if m.LongWorkLedger.objects.filter(user_id=row.user_id, org_id=row.org_id, ref=ref).exists():
        return None
    work_id = None
    if str(meta.get("rouh_work") or "").isdigit():
        work_id = int(meta["rouh_work"])
    elif link:
        work_id = (m.StripeLink.objects.filter(user_id=row.user_id, org_id=row.org_id,
                                               stripe_id=link).values_list("work_id", flat=True)
                   .first())
    if work_id is not None and not m.LongWork.objects.filter(
            user_id=row.user_id, org_id=row.org_id, id=work_id).exists():
        work_id = None
    try:
        value = (Decimal(int(amount or 0)) / 100).quantize(Decimal("0.01"))
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    currency = str(currency or "usd").upper()[:8]
    what = "Stripe payment" + (f" via {link}" if link else "") + (f" from {who_paid}" if who_paid else "")
    try:
        entry = m.LongWorkLedger.objects.create(
            user_id=row.user_id, org_id=row.org_id, work_id=work_id, direction="in",
            amount=value, currency=currency, what=what[:300], by="stripe", ref=ref,
            at=time.time())
    except IntegrityError:
        return None
    log.info("a Stripe payment came in for user %s: %s %s (work %s)", row.user_id, value,
             currency, work_id or "-")
    return entry


# --- what is shown and said -----------------------------------------------------------------


def _day(ts: float) -> str:
    return clock.moment(ts).strftime("%-d %b %Y, %H:%M")


def _expiry(card) -> str:
    return f"{card.exp_month:02d}/{card.exp_year % 100:02d}" if card.exp_month else ""


def _caps_public(who, card) -> dict:
    """A card's own caps as the Payments page draws them: each "100.00" or None, and what
    is spent against the day's and the month's so far."""
    out = {key: (f"{Decimal(getattr(card, key)):.2f}" if getattr(card, key) is not None else None)
           for key, _what, _said in CAPS}
    if card.per_day is not None:
        out["spent_day"] = f"{card_spent(who, card, 'day'):,.2f}"
    if card.per_month is not None:
        out["spent_month"] = f"{card_spent(who, card, 'month'):,.2f}"
    return out


def public(who) -> dict:
    """Everything the Payments page shows: the billing entities, each card's brand, last
    four, name, expiry, silo, entity and caps, never its number or code; and the account's silos
    to pick from."""
    from . import silos

    m = _models()
    row = settings_of(who)
    carry_over(who)
    entities = entities_of(who)
    cards = cards_of(who)
    known = {e.id for e in entities}
    every_silo = silos.of(who.user_id, who.org_id)
    have = {s.key: s for s in every_silo}
    default = _pick(cards, have) if cards else None
    now = time.time()
    charges = list(m.CardCharge.objects.filter(**_whose(who)).order_by("-at")[:60])
    money_in = list(m.LongWorkLedger.objects.filter(**_whose(who), by="stripe").order_by("-at")[:60])
    every = quests.all_of(who)
    titles = {w.id: f"Quest {w.task_number} {w.title}" for w in every}
    hrefs = {w.id: quests.address(w) for w in every}
    return {
        "cards": [{"id": c.id, "brand": c.brand, "last4": c.last4, "name": c.name,
                   "expiry": _expiry(c), "saved": _day(c.saved_at) if c.saved_at else "",
                   "silo": have[_silo_of(c, have)].chip() if _silo_of(c, have) else None,
                   "default": c is default,
                   "caps": _caps_public(who, c),
                   "entity": c.entity_id if c.entity_id in known else None} for c in cards],
        "new_caps": {"per_purchase": f"{DEFAULT_PER_PURCHASE:.2f}",
                     "per_day": f"{DEFAULT_PER_DAY:.2f}", "per_month": None},
        "entities": [{"id": e.id, "label": e.label, "company": e.company, "vat": e.vat,
                      "reg_number": e.reg_number, "email": e.email,
                      "address": {k: getattr(e, k) for k in ADDRESS},
                      "lines": invoice_lines(e),
                      "cards": sum(1 for c in cards if c.entity_id == e.id)} for e in entities],
        "silos": [s.chip() for s in every_silo],
        "stripe": ({"hint": row.stripe_hint, "mode": row.stripe_mode,
                    "saved": _day(row.stripe_saved_at) if row.stripe_saved_at else ""}
                   if row.stripe_sealed else None),
        "webhook": ({"url": row.hook_url, "id": row.hook_id,
                     "saved": _day(row.hook_saved_at) if row.hook_saved_at else ""}
                    if row.hook_sealed else None),
        "permissions": STRIPE_PERMISSIONS,
        "charges": [{"id": c.id, "merchant": c.merchant, "amount": f"{c.amount:,.2f}",
                     "currency": c.currency, "reason": c.reason, "state": c.state,
                     "work": titles.get(c.work_id, "") if c.work_id else "",
                     "work_href": hrefs.get(c.work_id, "") if c.work_id else "",
                     "card": f"{c.brand} ····{c.last4}", "billed_to": c.billed_to,
                     "placed": bool(c.placed_at), "bought": c.bought, "words": c.words,
                     "submitted": bool(c.submitted_at), "task": c.task_ref,
                     "pressed": bool(c.pressed_at), "outcome": c.outcome,
                     "billing_address": c.billing_address, "delivered_to": c.delivered_to,
                     "when": quests._when(c.at, now)}
                    for c in charges],
        "money_in": [{"id": e.id, "amount": f"{e.amount:,.2f}", "currency": e.currency,
                      "what": e.what, "work": titles.get(e.work_id, "") if e.work_id else "",
                      "when": quests._when(e.at, now)} for e in money_in],
    }


def status_line(who) -> str:
    """The payments status a tool may read: the brand, the last four and the caps, only."""
    p = public(who)
    labels = {e["id"]: e["label"] for e in p["entities"]}
    cards = [f"{c['brand']} ending {c['last4']}" + (f" ({c['silo']['name']})" if c["silo"] else "")
             + (f", billed to {labels[c['entity']]}" if c["entity"] in labels else "")
             + _caps_line(c["caps"]) for c in p["cards"]]
    default = next((cards[i] for i, c in enumerate(p["cards"]) if c["default"]), "")
    card = (f"Card: {cards[0]}." if len(cards) == 1
            else f"Cards: {'; '.join(cards)}. Unless another is named, a purchase in a silo fills "
                 f"that silo's card, and otherwise the {default}."
            if cards else "Card: none in the vault.")
    entities = " ".join(f"{e['label']}: " + "; ".join(e["lines"]) + "."
                        for e in p["entities"])
    stripe = (f"Stripe: a {p['stripe']['mode']} restricted key is set"
              + (", and its webhook is made." if p["webhook"] else ", with no webhook yet.")
              if p["stripe"] else "Stripe: no key is set.")
    return (f"{card} " + (f"Billing entities, whose details a checkout is filled with for "
                          f"their cards: {entities} " if entities else "")
            + f"A purchase over one of its card's caps is refused. {stripe}")


def _caps_line(caps: dict) -> str:
    """A card's caps as the payments tool says them, from `_caps_public`."""
    said = []
    for key, _what, per in CAPS:
        if caps.get(key) is None:
            continue
        spent = caps.get({"per_day": "spent_day", "per_month": "spent_month"}.get(key, ""))
        when = "today" if key == "per_day" else "this month"
        said.append(f"${caps[key]} {per}" + (f" (${spent} spent {when})" if spent else ""))
    if not said:
        return ", no caps of its own: nothing limits what it is charged"
    return ", its caps at most " + (said[0] if len(said) == 1
                                    else ", ".join(said[:-1]) + " and " + said[-1])
