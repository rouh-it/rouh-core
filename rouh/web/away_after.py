"""Away, after Rouh wrote, over the web (`rouh/away_after.py`, night 38's gene `away_after`).

``GET /mail/away-after/<key>`` is where Open on an away reply's notice goes: it says the gene was used,
and sends the person on to the chat the email was sent from, or its conversation in Gmail. The key is
the notice's own, so no message id travels in the address.
"""
from __future__ import annotations

from asgiref.sync import sync_to_async
from django.http import HttpRequest, HttpResponseRedirect

from rouh import away_after, evolution

from .common import only, refuse, who


@only("GET")
async def open_it(request: HttpRequest, key: str):
    me = await sync_to_async(who)(request)
    if me is None:
        return HttpResponseRedirect("/login?next=" + request.path)
    if not key.startswith("aa-") or len(key) > 40:
        return refuse("That is not an automatic reply Rouh told you about.", 404)
    if not await sync_to_async(away_after.on)(me):
        return refuse("Away, after Rouh wrote is switched off.", 404)
    if await sync_to_async(away_after.opens)(me, key) is None:
        return refuse("That is not an automatic reply Rouh told you about.", 404)
    await sync_to_async(evolution.used)(away_after.SWITCH, "opened", who=me, detail=key)
    return HttpResponseRedirect(await sync_to_async(away_after.where_to)(me, key))


__all__ = ["open_it"]
