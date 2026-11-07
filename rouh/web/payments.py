"""The Payments page, at /settings/payments, and Stripe's webhook (`rouh/payments.py`).

    GET  /api/payments                 the billing entities, each card's brand, last four,
                                       name, expiry, silo, entity and caps, the masked Stripe
                                       key, the webhook, the purchases and the money in
    POST /api/payments/entity          {id?, label, company?, vat?, reg_number?, email?,
                                       address{...}}: a billing entity added, or changed
    POST /api/payments/entity/delete   {id}: an entity with no cards under it taken out
    POST /api/payments/card            {number, expiry, cvc, name, silo?, entity,
                                       per_purchase?, per_day?, per_month?}: a card added to
                                       the vault under that entity with its caps, typed by
                                       Petar and sealed at once; never echoed
    POST /api/payments/card/delete     {id}: that card out of the vault
    POST /api/payments/card/silo       {id, silo}: that card made a silo's (a silo's key), or
                                       no silo's ("")
    POST /api/payments/card/entity     {id, entity}: that card moved under another entity
    POST /api/payments/card/caps       {id, per_purchase, per_day, per_month}: that card's
                                       own caps in dollars, each "" for none
    POST /api/payments/charge/void     {id}: a purchase that never went through
    POST /api/payments/charge/paid     {id}: a payment Petar says went through, which the
                                       page never confirmed (his bank's, or unconfirmed)
    POST /api/payments/stripe          {key}: a restricted key, sealed; shown masked
    POST /api/payments/stripe/delete   the key and the webhook out
    POST /api/payments/webhook         make Rouh's webhook endpoint in Stripe
    POST /hooks/stripe/<token>         Stripe's events, open to Stripe: nothing is read
                                       from one before its signature is checked

A refusal is ``{"error": ...}``, and ``"fields": {name: what is wrong}`` as well when what
is wrong is in fields of the form sent, every one of them at once, so the page says each
under its own field.

A card's number, expiry and code arrive in one request and go straight into the vault:
they are in no answer, no log line and no error message, which name the field that is
wrong and never what was typed. Every query names the signed-in person's user and
organisation.
"""
from __future__ import annotations

import asyncio
import logging

from django.http import HttpRequest, HttpResponse
from django.views.decorators.csrf import csrf_exempt

from .clock import _signed_in, their_clock
from .common import answer, body_of, only, public_base, refuse

log = logging.getLogger("rouh.web.payments")
NO_STORE = {"Cache-Control": "no-store"}


def _phone():
    from rouh import runtime

    return runtime.tools.telegram


async def _me(request):
    return await asyncio.to_thread(_signed_in, request)


async def _page(me) -> dict:
    from rouh import payments

    return await asyncio.to_thread(payments.public, me)


async def _do(request, work):
    from rouh import payments

    me = await _me(request)
    if me is None:
        return refuse("Sign in first.", 401)
    try:
        said = await work(me, body_of(request))
    except payments.Refused as exc:
        # What is wrong with each field, when it is a field's, said under that field.
        more = {"fields": exc.fields} if exc.fields else {}
        return refuse(str(exc), 400, **more, **(await _page(me)))
    except ValueError as exc:
        return refuse(str(exc), 400, **(await _page(me)))
    except Exception:  # noqa: BLE001 - never says what was typed
        log.exception("a payments change failed")
        return refuse("That could not be saved. Try again.", 500, **(await _page(me)))
    return answer({"ok": True, "said": said, **(await _page(me))}, headers=NO_STORE)


@only("GET")
@their_clock
async def page(request: HttpRequest):
    me = await _me(request)
    if me is None:
        return refuse("Sign in first.", 401)
    return answer(await _page(me), headers=NO_STORE)


@only("POST")
@their_clock
async def card(request: HttpRequest):
    from rouh import payments

    async def go(me, body):
        got = await asyncio.to_thread(payments.save_card, me, body)
        return f"Saved: {got.brand} ending {got.last4}."
    return await _do(request, go)


@only("POST")
@their_clock
async def card_delete(request: HttpRequest):
    from rouh import payments

    async def go(me, body):
        gone = await asyncio.to_thread(payments.delete_card, me, body.get("id"))
        if gone is None:
            raise payments.Refused("That card is not in the vault.")
        return f"Deleted the {gone.brand} ending {gone.last4} from the vault."
    return await _do(request, go)


@only("POST")
@their_clock
async def card_silo(request: HttpRequest):
    from rouh import payments, silos

    async def go(me, body):
        got = await asyncio.to_thread(payments.set_card_silo, me, body.get("id"), body.get("silo"))
        if got is None:
            raise payments.Refused("That card is not in the vault.")
        info = (await asyncio.to_thread(silos.by_key, me.user_id, me.org_id)).get(got.silo)
        if info is None:
            return f"The {got.brand} ending {got.last4} is for no silo."
        return f"The {got.brand} ending {got.last4} is now {info.name}\u2019s card."
    return await _do(request, go)


@only("POST")
@their_clock
async def card_entity(request: HttpRequest):
    from rouh import payments

    async def go(me, body):
        got = await asyncio.to_thread(payments.set_card_entity, me, body.get("id"),
                                      body.get("entity"))
        if got is None:
            raise payments.Refused("That card is not in the vault.")
        entity = await asyncio.to_thread(payments.entity_of, me, got.entity_id)
        return f"The {got.brand} ending {got.last4} is now billed to {entity.label}."
    return await _do(request, go)


@only("POST")
@their_clock
async def card_caps(request: HttpRequest):
    from rouh import payments

    async def go(me, body):
        got = await asyncio.to_thread(payments.set_card_caps, me, body.get("id"), body)
        if got is None:
            raise payments.Refused("That card is not in the vault.")
        said = payments.caps_said(got)
        if not said:
            return f"The {got.brand} ending {got.last4} has no caps now: nothing limits it."
        return f"The {got.brand} ending {got.last4} is capped {said}."
    return await _do(request, go)


@only("POST")
@their_clock
async def entity(request: HttpRequest):
    from rouh import payments

    async def go(me, body):
        changed = body.get("id") not in (None, "")
        got = await asyncio.to_thread(payments.save_entity, me, body)
        return f"{'Saved' if changed else 'Added'}: {got.label}."
    return await _do(request, go)


@only("POST")
@their_clock
async def entity_delete(request: HttpRequest):
    from rouh import payments

    async def go(me, body):
        gone = await asyncio.to_thread(payments.delete_entity, me, body.get("id"))
        if gone is None:
            raise payments.Refused("That billing entity is not one of yours.")
        return f"Removed {gone.label}."
    return await _do(request, go)


@only("POST")
@their_clock
async def charge_void(request: HttpRequest):
    from rouh import payments

    async def go(me, body):
        done = await asyncio.to_thread(payments.void_charge, me, body.get("id"))
        if not done:
            raise payments.Refused("That purchase is not one that can be taken back.")
        return "Marked as never gone through: it no longer counts against the caps."
    return await _do(request, go)


@only("POST")
@their_clock
async def charge_paid(request: HttpRequest):
    from rouh import payments

    async def go(me, body):
        done = await asyncio.to_thread(payments.paid_charge, me, body.get("id"))
        if not done:
            raise payments.Refused("That purchase is not one waiting to be confirmed.")
        return "Marked as paid."
    return await _do(request, go)


@only("POST")
@their_clock
async def stripe_key(request: HttpRequest):
    from rouh import payments

    async def go(me, body):
        got = await asyncio.to_thread(payments.save_stripe_key, me, body.get("key"))
        return f"Saved the {got['stripe']['mode']} key {got['stripe']['hint']}."
    return await _do(request, go)


@only("POST")
@their_clock
async def stripe_delete(request: HttpRequest):
    from rouh import payments

    async def go(me, body):
        await asyncio.to_thread(payments.delete_stripe_key, me)
        return "The Stripe key is deleted."
    return await _do(request, go)


@only("POST")
@their_clock
async def webhook(request: HttpRequest):
    from rouh import payments

    async def go(me, body):
        got = await payments.make_webhook(me, public_base(request))
        return f"Made the webhook: Stripe sends its events to {got['webhook']['url']}."
    return await _do(request, go)


@csrf_exempt
@only("POST")
async def stripe_event(request: HttpRequest, token: str):
    """One event from Stripe. Its signature is checked against the secret kept for this
    address before anything in it is read; a payment is written as money in and Petar is told."""
    from rouh import payments, quests

    row = await asyncio.to_thread(payments.hook_owner, token)
    if row is None:
        return HttpResponse(status=404)
    status, entry = await asyncio.to_thread(
        payments.take_event, row, request.body, request.headers.get("Stripe-Signature", ""))
    if entry is not None:
        from rouh import runtime

        title, work = "", None
        if entry.work_id is not None:
            work = await asyncio.to_thread(quests.by_id, row.user_id, row.org_id, entry.work_id)
            title = f"quest {work.task_number} {work.title}" if work else ""
        from rouh.config import config

        await payments.tell(_phone(), f"\U0001f4b0 Money came in: {entry.amount} {entry.currency}"
                                      + (f" for “{title}”" if title else "") + f".\n{entry.what}"
                                      + (f"\n\n{config.public_url.rstrip('/')}"
                                         f"{quests.address(work)}"
                                         if title and config.public_url else ""))
        if entry.work_id is not None:
            await runtime.pulse.event("money", f"Money came in: {entry.amount} {entry.currency}, "
                                               f"{entry.what}.", work_id=entry.work_id)
        else:
            await runtime.pulse._changed()
    return HttpResponse(status=status)
