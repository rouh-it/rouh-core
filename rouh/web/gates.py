"""Anatomy, Behaviour, Permission gates, at /anatomy/behaviour/gates (`rouh/gates.py`).

    GET  /api/anatomy/gates      every tool Rouh has, by area, each with whether it asks first, whether
                                 the server locks it on (ROUH_CONFIRM_TOOLS), and whether a mistake with
                                 it is expensive or cannot be undone (a candidate)
    POST /api/anatomy/gates      {tool, on}: one tool's "ask me first" switched; the page as it is after

Reading needs a sign-in; changing needs the organisation's administrator, since a gate is a safety
setting of the whole Rouh. A tool the server gates cannot be switched off here. A change is read by
the next tool call (`gates.live`), with no restart.
"""
from __future__ import annotations

import asyncio
import logging

from django.http import HttpRequest

from .clock import _signed_in, their_clock
from .common import answer, body_of, only, refuse

log = logging.getLogger("rouh.web.gates")
NO_STORE = {"Cache-Control": "no-store"}


def _entries() -> list:
    from rouh import runtime

    return runtime.tools.all_entries()


def _page(org: str) -> dict:
    from rouh import gates, runtime

    return gates.page(org, runtime.config, _entries())


@only("GET", "POST")
@their_clock
async def page(request: HttpRequest):
    from rouh import gates, runtime

    me = await asyncio.to_thread(_signed_in, request)
    if me is None:
        return refuse("Sign in first.", 401)
    org = str(me.org_id)
    if request.method == "GET":
        got = await asyncio.to_thread(_page, org)
        return answer({**got, "can_change": bool(getattr(me, "is_admin", False))}, headers=NO_STORE)
    if not getattr(me, "is_admin", False):
        return refuse("Only this Rouh's administrator can change its permission gates.", 403)
    body = body_of(request)
    tool = str(body.get("tool") or "").strip()
    on = bool(body.get("on"))
    known = {t.name for t in _entries()} | await asyncio.to_thread(gates.chosen, org)
    if tool not in known:
        return refuse("There is no tool with that name.", 400)
    if not on and tool in gates.from_server(runtime.config):
        return refuse("The server gates this tool (ROUH_CONFIRM_TOOLS), so it can only be turned "
                      "off in the server's settings.", 400, **(await asyncio.to_thread(_page, org)))
    try:
        await asyncio.to_thread(gates.put, org, tool, on, "the owner on Anatomy")
    except Exception:  # noqa: BLE001 - said plainly, and the log has why
        log.exception("a permission gate could not be saved")
        return refuse("That could not be saved. Try again.", 500)
    got = await asyncio.to_thread(_page, org)
    return answer({"ok": True, "tool": tool, "on": on, **got, "can_change": True}, headers=NO_STORE)
