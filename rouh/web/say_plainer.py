"""Say it more simply, over the web (`rouh/say_plainer.py`, night 50's gene `say_plainer`).

``POST /api/say-plainer``: the button under an answer was pressed. It says the gene was used, and
nothing else; the message itself went the way every message goes.
"""
from __future__ import annotations

from asgiref.sync import sync_to_async
from django.http import HttpRequest

from rouh import say_plainer

from .common import answer, only, refuse, who


@only("POST")
async def pressed(request: HttpRequest):
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("sign in", 401)
    if not await sync_to_async(say_plainer.on)(me):
        return refuse("Say it more simply is switched off.", 404)
    await sync_to_async(say_plainer.pressed)(me)
    return answer({"ok": True})


__all__ = ["pressed"]
