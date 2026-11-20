"""Bank details that changed, over the web (`rouh/bank_changed.py`, night 49's gene `bank_changed`).

``GET /mail/bank-changed/<key>`` is where Open the email on its notice goes: it says the gene was
used, and sends the person on to the email in Gmail. The key is the notice's own, so no message id
travels in the address.
"""
from __future__ import annotations

from asgiref.sync import sync_to_async
from django.http import HttpRequest, HttpResponseRedirect

from rouh import bank_changed, evolution

from .common import only, refuse, who


@only("GET")
async def open_it(request: HttpRequest, key: str):
    me = await sync_to_async(who)(request)
    if me is None:
        return HttpResponseRedirect("/login?next=" + request.path)
    if not key.startswith("bc-") or len(key) > 40:
        return refuse("That is not a bank account that changed Rouh told you about.", 404)
    if not await sync_to_async(bank_changed.on)(me):
        return refuse("Bank details that changed is switched off.", 404)
    held = await sync_to_async(bank_changed.opens)(me, key)
    if held is None:
        return refuse("That is not a bank account that changed Rouh told you about.", 404)
    await sync_to_async(evolution.used)(bank_changed.SWITCH, "opened", who=me,
                                        detail=str(held.get("sender") or key)[:200])
    return HttpResponseRedirect(await sync_to_async(bank_changed.where_to)(me, key))


__all__ = ["open_it"]
