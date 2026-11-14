"""Directions from their contact card, counted (`rouh/card_directions.py`, night 43's gene).

``POST /api/card-directions`` is what the page sends when an address or Directions is pressed on a
contact card: Maps opens by the link itself, and this only counts the use. No address is sent.
"""
from __future__ import annotations

from asgiref.sync import sync_to_async
from django.http import HttpRequest

from rouh import card_directions

from .common import answer, only, refuse, who


@only("POST")
async def pressed(request: HttpRequest):
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("Sign in first.", 401)
    if not await sync_to_async(card_directions.pressed)(me):
        return refuse("Directions from their contact card is switched off.", 404)
    return answer({"ok": True})


__all__ = ["pressed"]
