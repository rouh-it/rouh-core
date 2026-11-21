"""Things to try that fit what you have, over the web (`rouh/try_fit.py`, night 50's gene `try_fit`).

``POST /api/try-fit`` ``{kind}``: one of the person's own things to try on an empty conversation
was pressed. It says the gene was used, and nothing else.
"""
from __future__ import annotations

from asgiref.sync import sync_to_async
from django.http import HttpRequest

from rouh import try_fit

from .common import answer, body_of, only, refuse, who

KINDS = ("calendar", "mail")


@only("POST")
async def pressed(request: HttpRequest):
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("sign in", 401)
    kind = str(body_of(request).get("kind") or "")
    if kind not in KINDS:
        return refuse("That is not one of your own things to try.", 400)
    if not await sync_to_async(try_fit.on)(me):
        return refuse("Things to try that fit what you have is switched off.", 404)
    await sync_to_async(try_fit.pressed)(me, kind)
    return answer({"ok": True})


__all__ = ["pressed"]
