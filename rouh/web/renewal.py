"""Renews soon, over the web (`rouh/renewal_notice.py`, night 35's gene `renewal_notice`).

``GET /mail/renewal/<key>`` is where Open the email on a renewal's notice goes: it says the gene was
used, and sends the person on to the email in Gmail. The key is the notice's own, so no message id
travels in the address.
"""
from __future__ import annotations

from asgiref.sync import sync_to_async
from django.http import HttpRequest, HttpResponseRedirect

from rouh import evolution, renewal_notice

from .common import only, refuse, who


@only("GET")
async def open_it(request: HttpRequest, key: str):
    me = await sync_to_async(who)(request)
    if me is None:
        return HttpResponseRedirect("/login?next=" + request.path)
    if not key.startswith("rn-") or len(key) > 40:
        return refuse("That is not a renewal Rouh told you about.", 404)
    if not await sync_to_async(renewal_notice.on)(me):
        return refuse("Renews soon is switched off.", 404)
    held = await sync_to_async(renewal_notice.opens)(me, key)
    if held is None:
        return refuse("That is not a renewal Rouh told you about.", 404)
    await sync_to_async(evolution.used)(renewal_notice.SWITCH, "opened", who=me,
                                        detail=str(held.get("service") or key)[:200])
    return HttpResponseRedirect(await sync_to_async(renewal_notice.where_to)(me, key))


__all__ = ["open_it"]
