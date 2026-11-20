"""A document waiting for your signature, over the web (`rouh/sign_request.py`, night 49's gene `sign_request`).

``GET /mail/sign-request/<key>`` is where Open the email on its notice goes: it says the gene was
used, and sends the person on to the email in Gmail. The key is the notice's own, so no message id
travels in the address.
"""
from __future__ import annotations

from asgiref.sync import sync_to_async
from django.http import HttpRequest, HttpResponseRedirect

from rouh import sign_request, evolution

from .common import only, refuse, who


@only("GET")
async def open_it(request: HttpRequest, key: str):
    me = await sync_to_async(who)(request)
    if me is None:
        return HttpResponseRedirect("/login?next=" + request.path)
    if not key.startswith("sr-") or len(key) > 40:
        return refuse("That is not a request to sign Rouh told you about.", 404)
    if not await sync_to_async(sign_request.on)(me):
        return refuse("A document waiting for your signature is switched off.", 404)
    held = await sync_to_async(sign_request.opens)(me, key)
    if held is None:
        return refuse("That is not a request to sign Rouh told you about.", 404)
    await sync_to_async(evolution.used)(sign_request.SWITCH, "opened", who=me,
                                        detail=str(held.get("document") or key)[:200])
    return HttpResponseRedirect(await sync_to_async(sign_request.where_to)(me, key))


__all__ = ["open_it"]
