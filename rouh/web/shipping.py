"""The Shipping page, at /settings/shipping (`rouh/shipping.py`).

    GET  /api/shipping                    the options in the main order, the situations with
                                          their lists (Default first), the recipient, and the
                                          couriers and kinds of place the page suggests
    POST /api/shipping/option             {id?, label, company, kind, place_code?, place_name?,
                                          address{line1, city, postal_code, country, floor,
                                          apartment, entrance, door_code}, recipient_name?,
                                          recipient_phone?, notes?}: added at the end, or changed
    POST /api/shipping/option/delete      {id}: out of every list
    POST /api/shipping/option/active      {id, active}: switched on or off
    POST /api/shipping/order              {situation, order: [ids]}: a list put in this order
                                          ("default" is the main order)
    POST /api/shipping/move               {situation, id, by: -1 or 1}: one moved up or down
    POST /api/shipping/situation          {id?, name, options?}: a situation added, or renamed
    POST /api/shipping/situation/delete   {id}
    POST /api/shipping/recipient          {name, phone}: who a parcel is for by default

A refusal is ``{"error": ...}``, with ``"fields": {name: what is wrong}`` when it is in
fields of the form sent, so the page says each under its own field. Every query names the
signed-in person's user and organisation.
"""
from __future__ import annotations

import asyncio
import logging

from django.http import HttpRequest

from .clock import _signed_in, their_clock
from .common import answer, body_of, only, refuse

log = logging.getLogger("rouh.web.shipping")
NO_STORE = {"Cache-Control": "no-store"}


async def _page(me) -> dict:
    from rouh import shipping

    return await asyncio.to_thread(shipping.public, me)


async def _do(request, work):
    from rouh import shipping

    me = await asyncio.to_thread(_signed_in, request)
    if me is None:
        return refuse("Sign in first.", 401)
    try:
        said = await asyncio.to_thread(work, me, body_of(request))
    except shipping.Refused as exc:
        more = {"fields": exc.fields} if exc.fields else {}
        return refuse(str(exc), 400, **more, **(await _page(me)))
    except Exception:  # noqa: BLE001
        log.exception("a shipping change failed")
        return refuse("That could not be saved. Try again.", 500, **(await _page(me)))
    return answer({"ok": True, "said": said, **(await _page(me))}, headers=NO_STORE)


@only("GET")
@their_clock
async def page(request: HttpRequest):
    me = await asyncio.to_thread(_signed_in, request)
    if me is None:
        return refuse("Sign in first.", 401)
    return answer(await _page(me), headers=NO_STORE)


def _option(me, body):
    from rouh import shipping

    changed = body.get("id") not in (None, "")
    got = shipping.save_option(me, body)
    return f"{'Saved' if changed else 'Added'}: {got.label}."


def _option_delete(me, body):
    from rouh import shipping

    gone = shipping.delete_option(me, body.get("id"))
    if gone is None:
        raise shipping.Refused("That shipping option is not one of yours.")
    return f"Deleted {gone.label}."


def _option_active(me, body):
    from rouh import shipping

    got = shipping.set_active(me, body.get("id"), bool(body.get("active")))
    if got is None:
        raise shipping.Refused("That shipping option is not one of yours.")
    return f"{got.label} is {'on' if got.active else 'off: Rouh skips it'}."


def _order(me, body):
    from rouh import shipping

    name = shipping.reorder(me, body.get("situation"), body.get("order") or [])
    return f"{name} is in its new order."


def _move(me, body):
    from rouh import shipping

    name = shipping.move(me, body.get("situation"), body.get("id"), int(body.get("by") or 0))
    return f"{name} is in its new order."


def _situation(me, body):
    from rouh import shipping

    changed = body.get("id") not in (None, "")
    got = shipping.save_situation(me, body)
    return f"{'Renamed to' if changed else 'Added'} {got.name}."


def _situation_delete(me, body):
    from rouh import shipping

    gone = shipping.delete_situation(me, body.get("id"))
    if gone is None:
        raise shipping.Refused("That situation is not one of yours.")
    return f"Deleted the situation {gone.name}."


def _recipient(me, body):
    from rouh import shipping

    got = shipping.set_recipient(me, body.get("name"), body.get("phone"))
    return f"Parcels are for {got['name'] or 'you'}" + (f", {got['phone']}" if got["phone"] else "") + "."


def _view(work):
    @only("POST")
    @their_clock
    async def view(request: HttpRequest):
        return await _do(request, work)
    return view


option = _view(_option)
option_delete = _view(_option_delete)
option_active = _view(_option_active)
order = _view(_order)
move = _view(_move)
situation = _view(_situation)
situation_delete = _view(_situation_delete)
recipient = _view(_recipient)
