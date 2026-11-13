"""Call from their contact card, counted (`rouh/card_call.py`, night 42's gene `card_call`).

``POST /api/card-call`` with ``{"how": "call"}`` or ``{"how": "text"}`` is what the page sends when
Call or Text is pressed on a contact card: the phone rings or texts by the link itself, and this only
counts the use. No number is sent.
"""
from __future__ import annotations

from asgiref.sync import sync_to_async
from django.http import HttpRequest

from rouh import card_call

from .common import answer, body_of, only, refuse, who


@only("POST")
async def pressed(request: HttpRequest):
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("Sign in first.", 401)
    how = str(body_of(request).get("how") or "")
    if how not in card_call.HOW:
        return refuse("Say call or text.", 400)
    if not await sync_to_async(card_call.pressed)(me, how):
        return refuse("Call from their contact card is switched off.", 404)
    return answer({"ok": True})


__all__ = ["pressed"]
