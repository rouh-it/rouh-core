"""How a shop's checkout is filled: the card from the vault, where it is billed and where it is
delivered, into the fields a checkout page has for them.

The field patterns for each (`CARD_FIELDS`, `BILL_FIELDS`, `SHIP_FIELDS`, `SHIP_LABELS`), the helpers
that find and fill them in every frame of a page, the boxes that open a separate delivery address
or a billing address of its own, `fill_card_over_cdp` for a run's own browser, and `scrub_card`,
which takes the card back out of an outline.

The live browser's `Desk` (`rouh/browsing.py`) calls them from `fill_card`, `fill_shipping`,
`fill_billing` and `place_order`; `browsing` re-exports the names its callers use.
"""
from __future__ import annotations

import asyncio
import contextlib
import re
import time

# --- the card, filled from the vault (`payments.fill_card`) --------------------------------

#: Set on a field Rouh filled with one of the two addresses, "billing" or "shipping", so
#: filling the other never writes over it on the same page.
FILLED_AS = "data-rouh-filled"
#: Never a field marked as the delivery address's, nor one Rouh filled with it.
_NOT_SHIPPING = (':not([autocomplete~="shipping"]):not([name*="shipping" i]):not([id*="shipping" i])'
                 ':not([name*="delivery" i]):not([id*="delivery" i])'
                 f':not([{FILLED_AS}="shipping"])')


def _billed(*selectors: str) -> tuple:
    return tuple(sel + _NOT_SHIPPING for sel in selectors)


#: The card's fields on a checkout page: (which value, what it is called, where it may be).
#: The `autocomplete` names first, which every well-made checkout and Stripe's own fields
#: carry, then the names and ids checkouts commonly use. Its billing address is never put
#: into a field of the delivery address (`_NOT_SHIPPING`).
CARD_FIELDS = (
    ("number", "the card number", (
        'input[autocomplete~="cc-number"]', 'input[name="cardnumber"]',
        'input[name*="card_number" i]', 'input[name*="card-number" i]',
        'input[name*="cardNumber" i]', 'input[id*="cardnumber" i]',
        'input[id*="card-number" i]', 'input[id*="card_number" i]')),
    ("exp", "the expiry", (
        'input[autocomplete~="cc-exp"]', 'input[name="exp-date"]', 'input[name*="expiry" i]',
        'input[id*="expiry" i]', 'input[name*="exp_date" i]', 'input[placeholder*="MM / YY" i]',
        'input[placeholder*="MM/YY" i]')),
    ("exp_month", "the expiry month", (
        'input[autocomplete~="cc-exp-month"]', 'select[autocomplete~="cc-exp-month"]',
        'select[name*="exp_month" i]', 'select[name*="expmonth" i]', 'input[name*="exp_month" i]')),
    ("exp_year", "the expiry year", (
        'input[autocomplete~="cc-exp-year"]', 'select[autocomplete~="cc-exp-year"]',
        'select[name*="exp_year" i]', 'select[name*="expyear" i]', 'input[name*="exp_year" i]')),
    ("cvc", "the security code", (
        'input[autocomplete~="cc-csc"]', 'input[name="cvc"]', 'input[name*="cvc" i]',
        'input[name*="cvv" i]', 'input[id*="cvc" i]', 'input[id*="cvv" i]',
        'input[name*="security_code" i]')),
    ("name", "the name on the card", (
        'input[autocomplete~="cc-name"]', 'input[name*="cardholder" i]',
        'input[name*="nameoncard" i]', 'input[id*="cardholder" i]', 'input[name="billingName"]')),
    ("line1", "the billing street", _billed(
        'input[autocomplete~="address-line1"]', 'input[name*="address_line1" i]',
        'input[name="billingAddressLine1"]')),
    ("line2", "the billing street's second line", _billed(
        'input[autocomplete~="address-line2"]', 'input[name*="address_line2" i]',
        'input[name="billingAddressLine2"]')),
    ("city", "the billing city", _billed(
        'input[autocomplete~="address-level2"]', 'input[name*="city" i]',
        'input[name="billingLocality"]')),
    ("state", "the billing region", _billed(
        'input[autocomplete~="address-level1"]', 'select[autocomplete~="address-level1"]',
        'input[name="billingAdministrativeArea"]')),
    ("postal_code", "the billing postcode", _billed(
        'input[autocomplete~="postal-code"]', 'input[name*="postal" i]', 'input[name*="zip" i]',
        'input[name="billingPostalCode"]')),
    ("country", "the billing country", _billed(
        'select[autocomplete~="country"]', 'select[autocomplete~="country-name"]',
        'input[autocomplete~="country"]', 'select[name*="country" i]',
        'select[name="billingCountry"]')),
    # The card's billing entity's company details (`payments.BillingEntity`), filled only
    # when the entity has them, so a personal one leaves a checkout's company fields empty.
    ("company", "the company name", _billed(
        'input[autocomplete~="organization"]', 'input[name="company" i]',
        'input[name*="company_name" i]', 'input[name*="companyName" i]',
        'input[name*="company-name" i]', 'input[id="company" i]', 'input[id*="company_name" i]',
        'input[id*="companyName" i]', 'input[name*="business_name" i]',
        'input[name*="businessName" i]', 'input[id*="businessName" i]',
        'input[name="organization" i]', 'input[name="organisation" i]')),
    ("vat", "the VAT number", (
        'input[name="vat" i]', 'input[name*="vat_number" i]', 'input[name*="vatNumber" i]',
        'input[name*="vat-number" i]', 'input[name*="vat_id" i]', 'input[name*="vatId" i]',
        'input[id="vat" i]', 'input[id*="vat_number" i]', 'input[id*="vatNumber" i]',
        'input[id*="vat-number" i]', 'input[name*="tax_id" i]', 'input[name*="taxId" i]',
        'input[name*="tax-id" i]', 'input[id*="taxId" i]', 'input[id*="tax_id" i]')),
    ("reg_number", "the company registration number", (
        'input[name*="registration_number" i]', 'input[name*="registrationNumber" i]',
        'input[name*="registration-number" i]', 'input[name*="company_number" i]',
        'input[name*="companyNumber" i]', 'input[name*="company-number" i]',
        'input[id*="registration_number" i]', 'input[id*="registrationNumber" i]',
        'input[id*="company_number" i]', 'input[id*="companyNumber" i]',
        'input[name="eik" i]', 'input[name="bulstat" i]', 'input[name="uic" i]')),
    ("email", "the email for invoices", (
        'input[name*="invoice_email" i]', 'input[name*="invoiceEmail" i]',
        'input[name*="billing_email" i]', 'input[name*="billingEmail" i]',
        'input[id*="invoice_email" i]', 'input[id*="invoiceEmail" i]',
        'input[id*="billing_email" i]', 'input[id*="billingEmail" i]')),
)

#: The kinds of `CARD_FIELDS` that are the card's billing address and company, not the card.
_CARD_BILLING_KINDS = ("line1", "line2", "city", "state", "postal_code", "country", "company",
                       "vat", "reg_number", "email")


# --- where it is billed (`payments.billing_values`) ------------------------------------------

#: A checkout's billing address form, the one a shop asks for before the card: Shopware's main
#: form (billingAddress[...], BerryBase), WooCommerce's billing_*, and any field marked billing.
#: Filled from the billing entity of the card that will pay, never with where it is delivered:
#: the BerryBase order of 17 October 2026 (fr_cd4ba48083df) was billed to the office
#: it was delivered to, because the one address form Shopware shows is its billing address and
#: the delivery address went into it.
BILL_FIELDS = (
    ("given_name", "the billing first name", _billed(
        'input[name="billingAddress[firstName]"]', 'input[name="billing_first_name"]',
        'input[autocomplete~="billing"][autocomplete~="given-name"]', 'input[name="firstName"]')),
    ("family_name", "the billing last name", _billed(
        'input[name="billingAddress[lastName]"]', 'input[name="billing_last_name"]',
        'input[autocomplete~="billing"][autocomplete~="family-name"]', 'input[name="lastName"]')),
    ("company", "the company name", _billed(
        'input[name="billingAddress[company]"]', 'input[name="billing_company"]',
        'input[autocomplete~="billing"][autocomplete~="organization"]')),
    ("vat", "the VAT number", _billed(
        'input[name="vatIds[]"]', 'input[name="billingAddress[vatId]"]',
        'input[name*="billing" i][name*="vat" i]')),
    ("phone", "the billing phone", _billed(
        'input[name="billingAddress[phoneNumber]"]', 'input[name="billing_phone"]',
        'input[autocomplete~="billing"][autocomplete~="tel"]')),
    ("line1", "the billing street", _billed(
        'input[name="billingAddress[street]"]', 'input[name="billing_address_1"]',
        'input[autocomplete~="billing"][autocomplete~="address-line1"]',
        'input[autocomplete~="billing"][autocomplete~="street-address"]',
        'textarea[autocomplete~="billing"][autocomplete~="street-address"]',
        'input[name="billingAddressLine1"]', 'input[name*="billing" i][name*="street" i]',
        'input[name*="billing" i][name*="address1" i]', 'input[name*="billing" i][name*="address_1" i]')),
    ("line2", "the billing street's second line", _billed(
        'input[name="billingAddress[additionalAddressLine1]"]', 'input[name="billing_address_2"]',
        'input[autocomplete~="billing"][autocomplete~="address-line2"]',
        'input[name="billingAddressLine2"]')),
    ("city", "the billing city", _billed(
        'input[name="billingAddress[city]"]', 'input[name="billing_city"]',
        'input[autocomplete~="billing"][autocomplete~="address-level2"]',
        'input[name="billingLocality"]', 'input[name*="billing" i][name*="city" i]')),
    ("state", "the billing region", _billed(
        'input[name="billing_state"]', 'select[name="billing_state"]',
        'input[autocomplete~="billing"][autocomplete~="address-level1"]',
        'select[autocomplete~="billing"][autocomplete~="address-level1"]')),
    ("postal_code", "the billing postcode", _billed(
        'input[name="billingAddress[zipcode]"]', 'input[name="billing_postcode"]',
        'input[autocomplete~="billing"][autocomplete~="postal-code"]',
        'input[name="billingPostalCode"]', 'input[name*="billing" i][name*="zip" i]',
        'input[name*="billing" i][name*="postal" i]', 'input[name*="billing" i][name*="postcode" i]')),
    ("country", "the billing country", _billed(
        'select[name="billingAddress[countryId]"]', 'select[name="billing_country"]',
        'select[autocomplete~="billing"][autocomplete~="country"]', 'select[name="billingCountry"]',
        'select[name*="billing" i][name*="country" i]')),
)

#: A billing address form is on the page: one of its street, postcode or city fields shows.
_BILL_FORM = tuple(sel for kind, _w, sels in BILL_FIELDS if kind in ("line1", "postal_code", "city")
                   for sel in sels)

#: Where `fill_billing`, asked for on a page with no field marked billing (an address editor the
#: shop opened for its billing address), may still put it: the card's own address fields.
_BILL_LOOSE = tuple((kind, words, sels) for kind, words, sels in CARD_FIELDS
                    if kind in _CARD_BILLING_KINDS)

#: A box that opens a separate delivery address, below the billing one: Shopware's
#: "Shipping and billing address do not match", WooCommerce's "Ship to a different address?".
_APART = ('input[type=checkbox][name="differentShippingAddress"]',
          'input[type=checkbox]#ship-to-different-address-checkbox',
          'input[type=checkbox][name="ship_to_different_address"]',
          'input[type=checkbox][name*="different_shipping" i]',
          'input[type=checkbox][name*="differentShipping" i]',
          'input[type=checkbox][name*="different_delivery" i]',
          'input[type=checkbox][name*="differentDelivery" i]')
_APART_LABEL = (r"shipping and billing address(?:es)? (?:do not|don't) match|ship to a different address|"
                r"(?:different|separate|another) (?:shipping|delivery) address|deliver to (?:a )?different|"
                r"abweichende (?:liefer|versand)adresse|lieferadresse weicht|andere lieferadresse|"
                r"(?:друг|различен) адрес за доставка")
#: A box that makes the billing address the delivery address, ticked by many checkouts at the
#: payment step (Magento's "My billing and shipping address are the same", Stripe's, Shopify's
#: "Same as shipping address"), and the choice beside it for a billing address of its own.
_SAME = ('input[type=checkbox][name*="same_as_shipping" i]', 'input[type=checkbox][id*="same_as_shipping" i]',
         'input[type=checkbox][name*="sameAsShipping" i]', 'input[type=checkbox][id*="sameAsShipping" i]',
         'input[type=checkbox][id*="same-as-shipping" i]', 'input[type=checkbox][name*="same-as-shipping" i]',
         'input[type=checkbox][name*="billingSameAsShipping" i]')
_SAME_LABEL = (r"same as (?:the |my )?(?:shipping|delivery)|billing and (?:shipping|delivery) address(?:es)? "
               r"are the same|use (?:the |my )?(?:shipping|delivery) address (?:as|for) (?:the |my )?billing|"
               r"rechnungsadresse (?:entspricht|ist identisch mit|gleich) (?:der )?lieferadresse|"
               r"gleiche adresse wie lieferadresse|същ\w* като адреса за доставка")
_OWN_BILLING_LABEL = (r"(?:use a |a )?different billing address|another billing address|"
                      r"(?:andere|abweichende) rechnungsadresse|друг адрес за фактур")


# --- where it is delivered (`shipping.fill_values`) ------------------------------------------

#: Never a billing field, nor one Rouh filled with the billing address: those are the card's
#: billing entity's (`CARD_FIELDS`, `BILL_FIELDS`).
_NOT_BILLING = (':not([autocomplete~="billing"]):not([name*="billing" i]):not([id*="billing" i])'
                f':not([{FILLED_AS}="billing"])')


def _delivery(*selectors: str) -> tuple:
    return tuple(sel + _NOT_BILLING for sel in selectors)


def _shopware(field: str, tag: str = "input") -> tuple:
    """Shopware's own name for one field of its separate shipping address, shippingAddress[...],
    which opens when "Shipping and billing address do not match" is ticked. Its main form,
    billingAddress[...], is the billing address (`BILL_FIELDS`), and is never a delivery field."""
    return (f'{tag}[name="shippingAddress[{field}]"]',)


def _ship(field: str, generic: tuple, tag: str = "input", extra: tuple = ()) -> tuple:
    own = _shopware(field, tag) if field else ()
    return _delivery(*own, *generic) + extra


#: A checkout's delivery fields: (which value, what it is called, where it may be), the ones a page
#: marks as the shipping address's first, then the `autocomplete` names, then common names and ids.
#: A field none of them finds is looked for by its label (`SHIP_LABELS`).
SHIP_FIELDS = (
    ("name", "the recipient's name", _ship("", (
        'input[autocomplete~="shipping"][autocomplete~="name"]', 'input[autocomplete="name"]',
        'input[name="name" i]', 'input[name*="full_name" i]', 'input[name*="fullName" i]',
        'input[name*="recipient_name" i]', 'input[name*="recipientName" i]', 'input[id*="fullname" i]'))),
    ("given_name", "the first name", _ship("firstName", (
        'input[autocomplete~="shipping"][autocomplete~="given-name"]', 'input[autocomplete~="given-name"]',
        'input[name*="first_name" i]', 'input[name*="firstName" i]', 'input[name*="firstname" i]',
        'input[id*="firstname" i]'))),
    ("family_name", "the last name", _ship("lastName", (
        'input[autocomplete~="shipping"][autocomplete~="family-name"]', 'input[autocomplete~="family-name"]',
        'input[name*="last_name" i]', 'input[name*="lastName" i]', 'input[name*="lastname" i]',
        'input[id*="lastname" i]'))),
    ("phone", "the phone", _ship("phoneNumber", (
        'input[autocomplete~="shipping"][autocomplete~="tel"]', 'input[autocomplete~="tel"]',
        'input[type="tel"]', 'input[name*="phone" i]', 'input[name*="mobile" i]', 'input[id*="phone" i]'))),
    ("entrance", "the entrance", _delivery(
        'input[name*="entrance" i]', 'input[id*="entrance" i]', 'input[name*="vhod" i]')),
    ("floor", "the floor", _delivery(
        'input[name*="floor" i]', 'input[id*="floor" i]', 'input[name*="etaj" i]')),
    ("apartment", "the apartment", _delivery(
        'input[name*="apartment" i]', 'input[id*="apartment" i]', 'input[name="apt" i]',
        'input[name*="flat" i]')),
    ("line1", "the street", _ship("street", (
        'input[autocomplete~="shipping"][autocomplete~="address-line1"]',
        'input[autocomplete~="shipping"][autocomplete~="street-address"]',
        'input[autocomplete~="address-line1"]', 'input[autocomplete~="street-address"]',
        'textarea[autocomplete~="street-address"]', 'input[name*="street" i]', 'input[name*="address1" i]',
        'input[name*="address_1" i]', 'input[name*="address_line1" i]', 'input[name="address" i]',
        'input[id="address" i]'))),
    ("line2", "the second address line", _ship("additionalAddressLine1", (
        'input[autocomplete~="shipping"][autocomplete~="address-line2"]', 'input[autocomplete~="address-line2"]',
        'input[name*="address2" i]', 'input[name*="address_2" i]', 'input[name*="address_line2" i]',
        'input[name*="additionalAddressLine1" i]'))),
    ("city", "the city", _ship("city", (
        'input[autocomplete~="shipping"][autocomplete~="address-level2"]', 'input[autocomplete~="address-level2"]',
        'input[name*="city" i]', 'input[id*="city" i]', 'input[name*="town" i]'))),
    ("postal_code", "the postcode", _ship("zipcode", (
        'input[autocomplete~="shipping"][autocomplete~="postal-code"]', 'input[autocomplete~="postal-code"]',
        'input[name*="postal" i]', 'input[name*="postcode" i]', 'input[name*="zip" i]'))),
    ("country", "the country", _ship("countryId", (
        'select[autocomplete~="shipping"][autocomplete~="country"]', 'select[autocomplete~="country"]',
        'select[autocomplete~="country-name"]', 'input[autocomplete~="country"]', 'select[name*="country" i]'),
        tag="select")),
    ("notes", "the notes for the courier", _delivery(
        'textarea[name*="note" i]', 'textarea[id*="note" i]', 'textarea[name*="comment" i]',
        'textarea[name*="instruction" i]', 'input[name*="instruction" i]', 'input[name*="courier_note" i]',
        'input[name*="delivery_note" i]')),
)

#: The words a delivery field is labelled with, for a field none of `SHIP_FIELDS` finds: read
#: from the start of its label, in English, German and Bulgarian. "Additional Address Info /
#: Post Number" is BerryBase's second line.
SHIP_LABELS = {
    "given_name": r"^\s*(first ?name|given name|vorname|име)\b",
    "family_name": r"^\s*(last ?name|surname|family name|nachname|фамилия)\b",
    "phone": r"^\s*(phone|telephone|mobile|telefon|handy|телефон)",
    "line1": r"^\s*(street|address line 1|straße|strasse|улица|адрес\b)",
    "line2": r"^\s*(additional address|address line 2|adresszusatz|address supplement|"
             r"apartment, suite)",
    "city": r"^\s*(city|town|ort|stadt|град|населено място)\b",
    "postal_code": r"^\s*(postal ?code|post ?code|zip|plz|postleitzahl|пощенски код)",
    "country": r"^\s*(country|land|държава)\b",
}

#: Which of the two addresses a field is, as the page marks it or as Rouh filled it: "billing"
#: (named or marked billing, Shopware's billingAddress[...] included), "shipping", or "".
_SIDE_SCRIPT = r"""(e) => {
  const filled = e.getAttribute('%s') || '';
  if (filled) return filled;
  const named = ((e.getAttribute('name') || '') + ' ' + (e.id || '')).toLowerCase();
  const auto = (e.getAttribute('autocomplete') || '').toLowerCase();
  if (/(^|\s)billing(\s|$)/.test(auto) || named.includes('billing')) return 'billing';
  if (/(^|\s)shipping(\s|$)/.test(auto) || named.includes('shipping') || named.includes('delivery')) return 'shipping';
  return '';
}""" % FILLED_AS


async def _fill_label(frame, pattern: str, value: str, side: str = "shipping") -> bool:
    """Fill the first visible, editable field whose label starts with these words, unless it
    is the other address's: a delivery field is never one marked or filled as billing, and a
    billing field never one marked or filled as shipping. The field is marked as `side`."""
    other = "billing" if side == "shipping" else "shipping"
    try:
        found = frame.get_by_label(re.compile(pattern, re.IGNORECASE))
        count = await found.count()
    except Exception:
        return False
    for i in range(min(count, 4)):
        target = found.nth(i)
        try:
            if not await target.is_visible() or not await target.is_editable():
                continue
            if await target.evaluate(_SIDE_SCRIPT, timeout=3000) == other:
                continue
            tag = await target.evaluate("e => e.tagName.toLowerCase()", timeout=3000)
            if tag == "select":
                if not await _pick(target, value):
                    continue
            elif tag in ("input", "textarea"):
                await target.fill(value, timeout=6000)
            else:
                continue
            await _mark(target, side)
            return True
        except Exception:
            continue
    return False


async def _mark(target, side: str) -> None:
    if side:
        with contextlib.suppress(Exception):
            await target.evaluate("(e, v) => e.setAttribute('%s', v)" % FILLED_AS, side,
                                  timeout=3000)


async def _showing(frames, selectors: tuple) -> bool:
    """Whether any frame shows a field any of these finds."""
    for frame in frames:
        for selector in selectors:
            with contextlib.suppress(Exception):
                found = frame.locator(selector)
                for i in range(min(await found.count(), 4)):
                    if await found.nth(i).is_visible():
                        return True
    return False


#: A field of a separate delivery address form, marked as the shipping address's.
_SHIP_FORM = ('input[name^="shippingAddress["]', 'select[name^="shippingAddress["]',
              'input[name^="shipping_address" i]', 'input[name^="shipping_"]:not([type=radio])'
              ':not([type=checkbox]):not([type=hidden])', 'input[autocomplete~="shipping"]',
              'select[autocomplete~="shipping"]')


async def _box(frames, selectors: tuple, label: str, kinds=("checkbox",)):
    """The first tick box (or radio, when `kinds` says) any of these finds, or whose label
    reads so, in any frame; with its type. (None, "") when there is none."""
    for frame in frames:
        for selector in selectors:
            with contextlib.suppress(Exception):
                found = frame.locator(selector)
                if await found.count():
                    return found.first, "checkbox"
        with contextlib.suppress(Exception):
            found = frame.get_by_label(re.compile(label, re.IGNORECASE))
            for i in range(min(await found.count(), 4)):
                target = found.nth(i)
                kind = await target.evaluate(
                    "e => (e.tagName.toLowerCase() === 'input' && (e.getAttribute('type') || '')"
                    ".toLowerCase()) || ''", timeout=3000)
                if kind in kinds:
                    return target, kind
    return None, ""


async def _set_box(target, want: bool) -> bool:
    """A tick box or radio set to `want`; whether it now is. Shops often hide the input under
    a drawn one, so a press on it by force, then on its label, follow a plain one."""
    for force in (False, True):
        with contextlib.suppress(Exception):
            await target.set_checked(want, force=force, timeout=3000)
            if await target.is_checked() == want:
                return True
    with contextlib.suppress(Exception):
        await target.evaluate("e => { const l = (e.labels && e.labels[0]) || e.closest('label');"
                              " (l || e).click(); }", timeout=3000)
        return await target.is_checked() == want
    return False


async def _open_apart(frames) -> bool:
    """The page's separate delivery address opened, by ticking its box (`_APART`)."""
    target, _kind = await _box(frames, _APART, _APART_LABEL)
    if target is None:
        return False
    with contextlib.suppress(Exception):
        if await target.is_checked():
            return True
    return await _set_box(target, True)


async def _bill_apart(frames) -> str:
    """The billing address made one of its own where the page has it the delivery address's
    by a box (`_SAME`): the box unticked, or the choice beside it picked. Answers what was
    done, in words, or ""."""
    target, kind = await _box(frames, _SAME, _SAME_LABEL, kinds=("checkbox", "radio"))
    if target is None:
        return ""
    with contextlib.suppress(Exception):
        if not await target.is_checked():
            return ""
    if kind == "checkbox":
        return ("unticked the box that made the billing address the delivery address"
                if await _set_box(target, False) else "")
    own, _ = await _box(frames, (), _OWN_BILLING_LABEL, kinds=("radio",))
    if own is not None and await _set_box(own, True):
        return "picked a billing address of its own instead of the delivery address"
    return ""


async def _fill_set(frames, fields: tuple, values: dict, side: str, labels: dict | None = None
                    ) -> list[str]:
    """Each of `fields` that has a value filled in the first frame that has it, by its names,
    else by its label (`labels`); the fields marked as `side`. Answers what was filled."""
    filled: list[str] = []
    for kind, words, selectors in fields:
        value = str(values.get(kind) or "")
        if not value:
            continue
        done = False
        for frame in frames:
            if await _fill_first(frame, selectors, value, side):
                done = True
                break
        if not done and labels and kind in labels:
            for frame in frames:
                if await _fill_label(frame, labels[kind], value, side):
                    done = True
                    break
        if done:
            filled.append(words)
    return filled


#: The parts of a door address that go into the second line when the page has no field for them.
_SHIP_PARTS = (("entrance", "entrance"), ("floor", "floor"), ("apartment", "apartment"))


async def _fill_delivery(frames, values: dict) -> list[str]:
    """One shipping option's values into the page's delivery fields (`SHIP_FIELDS`, then
    `SHIP_LABELS`), each marked as the shipping address's. Answers what was filled."""
    filled: list[str] = []
    done: set[str] = set()
    rest = ""
    for kind, words, selectors in SHIP_FIELDS:
        value = str(values.get(kind) or "")
        if kind == "line2":
            rest = ", ".join(f"{name} {values.get(k)}" for k, name in _SHIP_PARTS
                             if values.get(k) and k not in done)
            value = rest
        if not value:
            continue
        for frame in frames:
            if await _fill_first(frame, selectors, value, "shipping"):
                done.add(kind)
                break
        if kind not in done and kind in SHIP_LABELS:
            for frame in frames:
                if await _fill_label(frame, SHIP_LABELS[kind], value, "shipping"):
                    done.add(kind)
                    break
        if kind in done:
            filled.append(words)
            if kind == "line2":
                rest = ""
    if rest and "line1" in done:
        # No field for them: after the street, where a courier reads them.
        for frame in frames:
            if await _fill_first(frame, dict((k, s) for k, _, s in SHIP_FIELDS)["line1"],
                                 f"{values.get('line1')}, {rest}", "shipping"):
                break
    return filled


#: The values every outline is scrubbed of once they are on a page.
_SCRUBBED = ("number", "exp", "cvc")


def _card_values(card: dict) -> dict:
    month = int(card.get("exp_month") or 0)
    year = int(card.get("exp_year") or 0)
    address = card.get("address") or {}
    invoice = card.get("invoice") or {}
    return {"number": str(card.get("number") or ""),
            "exp": f"{month:02d} / {year % 100:02d}" if month else "",
            "exp_month": f"{month:02d}" if month else "", "exp_year": str(year) if year else "",
            "cvc": str(card.get("cvc") or ""), "name": str(card.get("name") or ""),
            **{k: str(address.get(k) or "") for k in
               ("line1", "line2", "city", "state", "postal_code", "country")},
            **{k: str(invoice.get(k) or "") for k in ("company", "vat", "reg_number", "email")}}


async def _fill_first(frame, selectors: tuple, value: str, side: str = "") -> bool:
    """Fill the first visible, editable field any of these finds in this frame, and mark it as
    the `side` of the two addresses it is, when it is one."""
    for selector in selectors:
        try:
            found = frame.locator(selector)
            count = await found.count()
        except Exception:
            continue
        for i in range(min(count, 4)):
            target = found.nth(i)
            try:
                if not await target.is_visible() or not await target.is_editable():
                    continue
                tag = await target.evaluate("e => e.tagName.toLowerCase()", timeout=3000)
                if tag == "select":
                    if not await _pick(target, value):
                        continue
                else:
                    await target.fill(value, timeout=6000)
                await _mark(target, side)
                return True
            except Exception:
                continue
    return False


async def _pick(target, value: str) -> bool:
    """A drop-down set to this value, by its value or its words, ignoring case."""
    with contextlib.suppress(Exception):
        await target.select_option(value=value, timeout=3000)
        return True
    with contextlib.suppress(Exception):
        await target.select_option(label=value, timeout=3000)
        return True
    with contextlib.suppress(Exception):
        options = await target.evaluate(
            "e => Array.from(e.options).map(o => [o.value, o.textContent.trim()])", timeout=3000)
        low = value.strip().lower()
        names = {low}
        if len(low) == 2 and low.isalpha():
            # A country's two letters, in a list that names countries in words and keeps an
            # id of its own as the value (Shopware's countryId): the country's name in the
            # page's language, English, German and Bulgarian, from the browser itself.
            with contextlib.suppress(Exception):
                said = await target.evaluate(
                    """(e, code) => { const out = [];
                      const langs = [document.documentElement.lang || 'en', 'en', 'de', 'bg'];
                      for (const l of langs) { try {
                        out.push(new Intl.DisplayNames([l], {type: 'region'}).of(code.toUpperCase()));
                      } catch (x) {} }
                      return out; }""", low, timeout=3000)
                names |= {str(n).strip().lower() for n in said or [] if n}
        for v, words in options or []:
            if (str(v).lower() in names or str(words).lower() in names
                    or str(words).strip().lower().rstrip("*").strip() in names):
                await target.select_option(value=v, timeout=3000)
                return True
    return False


#: The card's own fields, cleared again after a press in a run's browser, so a checkout that
#: is still on the screen does not show the card to the run's next look at it.
_CLEARED = ("number", "exp", "exp_month", "exp_year", "cvc")


async def fill_card_over_cdp(port: int, card: dict, *, address: str = "", press: str = "",
                             wait: float = 20.0) -> dict:
    """Fill the vault's card into the checkout a run has open in its own browser, and press.

    For `payments.fill_card_in_run` alone, which has checked every cap and written the
    purchase down first. The run is the nightly feature run (`rouh/nightly_feature.py`),
    whose headless browser listens for DevTools on loopback on `port`, a port Rouh chose
    for it (`one/asuser.py`, ``_browser_config``). Connecting does not take the browser
    over: the run's own Playwright goes on driving it, and closing the connection here
    leaves it as it was.

    The page is the one at `address` when one is, else the newest that has card fields.
    The card goes into every frame's card fields, as in the live browser (`CARD_FIELDS`),
    and then the button or link whose words are `press` is pressed. Whatever the press led
    to, any card field still on the page is emptied again, so the run's next look at the
    page does not carry the card. Answers what was filled, in words, whether it pressed,
    and where the page is now; never a value.
    """
    from playwright.async_api import async_playwright

    from .browsing import CannotBrowse, _masked, _page_url, _settle

    values = _card_values(card)
    out = {"filled": [], "pressed": False, "cleared": False, "url": "", "title": ""}
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.connect_over_cdp(f"http://127.0.0.1:{int(port)}",
                                                         timeout=15000)
            try:
                page = await _checkout_page(browser, address)
                if page is None:
                    raise CannotBrowse("no page with card fields is open in the run's browser"
                                       + (f" at {address}" if address else ""))
                for frame in list(page.frames):
                    for kind, words, selectors in CARD_FIELDS:
                        value = values.get(kind)
                        if not value or words in out["filled"]:
                            continue
                        if await _fill_first(frame, selectors, value):
                            out["filled"].append(words)
                if out["filled"] and press:
                    out["pressed"] = await _press_named(page, press)
                    if out["pressed"]:
                        deadline = time.monotonic() + max(2.0, wait)
                        await _settle(page)
                        while time.monotonic() < deadline and await _card_showing(page):
                            await asyncio.sleep(1.0)
                if await _card_showing(page):
                    for frame in list(page.frames):
                        for kind, _words, selectors in CARD_FIELDS:
                            if kind in _CLEARED:
                                with contextlib.suppress(Exception):
                                    await _fill_first(frame, selectors, "")
                    out["cleared"] = True
                out["url"] = _masked(_page_url(page))
                with contextlib.suppress(Exception):
                    out["title"] = (await page.title())[:200]
            finally:
                with contextlib.suppress(Exception):
                    await browser.close()
    finally:
        values.clear()
    return out


async def _checkout_page(browser, address: str):
    from .browsing import _bare, _page_url

    pages = [p for context in browser.contexts for p in context.pages]
    want = _bare(address) if address else ""
    if want:
        for page in reversed(pages):
            if _bare(_page_url(page)).startswith(want):
                return page
    for page in reversed(pages):
        for frame in page.frames:
            for _kind, _words, selectors in CARD_FIELDS[:1]:
                for selector in selectors:
                    with contextlib.suppress(Exception):
                        if await frame.locator(selector).count():
                            return page
    return None


async def _press_named(page, words: str) -> bool:
    """Press the first visible button or link on the page, in any frame, that says `words`."""
    words = " ".join(str(words or "").split())[:120]
    for frame in list(page.frames):
        for role in ("button", "link"):
            with contextlib.suppress(Exception):
                found = frame.get_by_role(role, name=words)
                for i in range(min(await found.count(), 4)):
                    target = found.nth(i)
                    if await target.is_visible():
                        await target.click(timeout=8000)
                        return True
        with contextlib.suppress(Exception):
            found = frame.locator("input[type=submit], input[type=button]").filter(
                has_text=words)
            if await found.count() and await found.first.is_visible():
                await found.first.click(timeout=8000)
                return True
    return False


async def _card_showing(page) -> bool:
    """Whether any frame of the page still has a card number field with something in it."""
    for frame in list(page.frames):
        for selector in CARD_FIELDS[0][2]:
            with contextlib.suppress(Exception):
                found = frame.locator(selector)
                for i in range(min(await found.count(), 4)):
                    if (await found.nth(i).input_value(timeout=2000)).strip():
                        return True
    return False


def _number_forms(number: str) -> list[str]:
    """The ways a page may show a card number: plain, in fours, in Amex's 4-6-5, with
    spaces or dashes."""
    if not number:
        return []
    fours = [number[i:i + 4] for i in range(0, len(number), 4)]
    amex = [number[:4], number[4:10], number[10:]]
    out = {number}
    for groups in (fours, amex):
        for sep in (" ", "-", "  "):
            out.add(sep.join(g for g in groups if g))
    return list(out)


#: A line of an outline that is a field, where what was typed into it shows.
_FIELD_LINE = re.compile(r"\b(textbox|spinbutton|combobox|searchbox)\b")

_CARDISH = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")


def scrub_card(text: str, values: list[str], last4: str) -> str:
    """An outline with the card that was filled taken out of it.

    Every form of its number, its expiry and its security code wherever they appear, and
    any other run of digits that is a card number by the Luhn check.
    """
    from .payments import luhn

    mask = "\u2022\u2022\u2022\u2022 " + last4 if last4 else "\u2022\u2022\u2022\u2022"
    out = text or ""
    for value in values:
        if not value:
            continue
        if len(re.sub(r"\D", "", value)) >= 12:
            out = out.replace(value, mask)
        elif "/" in value:
            # The expiry: with its slash it is never a price, so it goes wherever it is.
            out = re.sub(r"(?<!\d)" + re.escape(value) + r"(?!\d)", "\u2022\u2022 / \u2022\u2022", out)
        else:
            # The code is short, so it is scrubbed only where a field shows its value - on
            # the field's own line or on the lines under it - and a price of the same
            # digits elsewhere stays as it is.
            pattern = re.compile(r"(?<![\w/$.,])" + re.escape(value) + r"(?![\w/.,])")
            lines, under = [], -1
            for line in out.split("\n"):
                depth = len(line) - len(line.lstrip())
                if under >= 0 and depth <= under:
                    under = -1
                if _FIELD_LINE.search(line):
                    under = depth
                lines.append(pattern.sub("\u2022\u2022\u2022", line) if under >= 0 else line)
            out = "\n".join(lines)

    def masked(found) -> str:
        digits = re.sub(r"\D", "", found.group(0))
        return mask if 12 <= len(digits) <= 19 and luhn(digits) else found.group(0)

    return _CARDISH.sub(masked, out)
