"""Did not arrive, over the web (`rouh/not_arrived.py`, night 34's gene `not_arrived`).

``GET /mail/not-arrived/<key>`` is where Open on a bounce's notice goes: it says the gene was used,
and sends the person on to the chat the email was sent from, or its conversation in Gmail. The key is
the notice's own, so no message id travels in the address.
"""
from __future__ import annotations

from asgiref.sync import sync_to_async
from django.http import HttpRequest, HttpResponseRedirect

from rouh import evolution, not_arrived

from .common import only, refuse, who


@only("GET")
async def open_it(request: HttpRequest, key: str):
    me = await sync_to_async(who)(request)
    if me is None:
        return HttpResponseRedirect("/login?next=" + request.path)
    if not key.startswith("na-") or len(key) > 40:
        return refuse("That is not a bounce Rouh told you about.", 404)
    if not await sync_to_async(not_arrived.on)(me):
        return refuse("Did not arrive is switched off.", 404)
    if await sync_to_async(not_arrived.opens)(me, key) is None:
        return refuse("That is not a bounce Rouh told you about.", 404)
    await sync_to_async(evolution.used)(not_arrived.SWITCH, "opened", who=me, detail=key)
    return HttpResponseRedirect(await sync_to_async(not_arrived.where_to)(me, key))


__all__ = ["open_it"]
