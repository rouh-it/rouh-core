"""A payment that did not go through, over the web (`rouh/payment_failed.py`, night 48's gene `payment_failed`).

``GET /mail/payment-failed/<key>`` is where Open the email on a failed payment's notice goes: it says the gene was
used, and sends the person on to the email in Gmail. The key is the notice's own, so no message id
travels in the address.
"""
from __future__ import annotations

from asgiref.sync import sync_to_async
from django.http import HttpRequest, HttpResponseRedirect

from rouh import evolution, payment_failed

from .common import only, refuse, who


@only("GET")
async def open_it(request: HttpRequest, key: str):
    me = await sync_to_async(who)(request)
    if me is None:
        return HttpResponseRedirect("/login?next=" + request.path)
    if not key.startswith("pf-") or len(key) > 40:
        return refuse("That is not a failed payment Rouh told you about.", 404)
    if not await sync_to_async(payment_failed.on)(me):
        return refuse("A payment that did not go through is switched off.", 404)
    held = await sync_to_async(payment_failed.opens)(me, key)
    if held is None:
        return refuse("That is not a failed payment Rouh told you about.", 404)
    await sync_to_async(evolution.used)(payment_failed.SWITCH, "opened", who=me,
                                        detail=str(held.get("service") or key)[:200])
    return HttpResponseRedirect(await sync_to_async(payment_failed.where_to)(me, key))


__all__ = ["open_it"]
