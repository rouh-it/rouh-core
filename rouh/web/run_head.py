"""Three genes on a run's head, over the web (`rouh/run_head.py`, night 50's `run_live`, `run_files`
and `run_carry`).

``POST /api/run-head`` ``{switch, run}``: one of them was used on a run's head. It says so, and
nothing else.
"""
from __future__ import annotations

from asgiref.sync import sync_to_async
from django.http import HttpRequest

from rouh import run_head

from .common import answer, body_of, only, refuse, who


@only("POST")
async def used(request: HttpRequest):
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("sign in", 401)
    body = body_of(request)
    switch = str(body.get("switch") or "")
    if switch not in run_head.GENES:
        return refuse("That is not one of the run's head's genes.", 400)
    if not await sync_to_async(run_head.used)(me, switch, str(body.get("run") or "")):
        return refuse("That is switched off.", 404)
    return answer({"ok": True})


__all__ = ["used"]
