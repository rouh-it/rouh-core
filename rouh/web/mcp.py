"""Anatomy, Connections, MCP servers, at /anatomy/connections/mcp (`rouh/mcp_servers.py`).

    GET  /api/settings/mcp              this person's servers and the installation's own (read-only,
                                        "from settings"): each connected or failing and why, its tools,
                                        Ask first, and the last four of each secret; and the presets
    POST /api/settings/mcp/test         {name, kind, url, headers | command, args, env, id?}: open it,
                                        list its tools, close it; nothing is kept
    POST /api/settings/mcp/save         the same: tested, then kept, its secrets sealed, and opened in
                                        the running Rouh, so its tools are Rouh's with no restart
    POST /api/settings/mcp/check        {id}: open a saved server again now
    POST /api/settings/mcp/enabled      {id, on}: turn it on or off
    POST /api/settings/mcp/ask-first    {id, on}: whether its tools ask before they run
    POST /api/settings/mcp/remove       {id}: take its tools out of the list and forget it

A token typed here goes straight to the server and never through a chat or a model, and is never
sent back. A command runs a program on this machine, so only an administrator of the organisation
may connect one.
"""
from __future__ import annotations

import asyncio
import logging

from django.http import HttpRequest

from .clock import _signed_in, their_clock
from .common import answer, body_of, only, refuse
from .google import Meter

log = logging.getLogger("rouh.web.mcp")
NO_STORE = {"Cache-Control": "no-store"}
meter = Meter(12, 60.0)
TOO_MANY = "That is too many tries. Wait a minute."


def _registry():
    from rouh import runtime

    return runtime.tools


async def _me(request):
    return await asyncio.to_thread(_signed_in, request)


async def _page(me) -> dict:
    from rouh import mcp_servers

    return await asyncio.to_thread(mcp_servers.public, me, _registry())


@only("GET")
@their_clock
async def page(request: HttpRequest):
    me = await _me(request)
    if me is None:
        return refuse("Sign in first.", 401)
    out = await _page(me)
    out["can_run_commands"] = bool(getattr(me, "is_admin", False))
    return answer(out, headers=NO_STORE)


async def _do(request, work, *, with_page: bool = True, metered: bool = False):
    from rouh import mcp_servers
    from rouh.encryption import NotEncryptable

    me = await _me(request)
    if me is None:
        return refuse("Sign in first.", 401)
    body = body_of(request)
    try:
        if metered and meter.too_many("mcp:" + str(me.user_id)):
            raise mcp_servers.Refused(TOO_MANY)
        if str(body.get("kind") or "") == "stdio" and not getattr(me, "is_admin", False):
            raise mcp_servers.Refused("A command runs a program on this machine, so only an "
                                      "administrator can connect one. Use an address instead.")
        said = await work(me, body, _registry())
    except mcp_servers.Refused as exc:
        return refuse(str(exc), 400, **(await _page(me)))
    except NotEncryptable:
        return refuse("Secrets cannot be kept safely on this machine yet, so nothing was kept.", 500,
                      **(await _page(me)))
    except Exception:  # noqa: BLE001 - never says what was typed
        log.exception("an MCP server change failed")
        return refuse("That did not work. Try again.", 500, **(await _page(me)))
    finally:
        body.clear()
    out = {"ok": True, **said}
    if with_page:
        out.update(await _page(me))
        out["can_run_commands"] = bool(getattr(me, "is_admin", False))
    return answer(out, headers=NO_STORE)


@only("POST")
@their_clock
async def test(request: HttpRequest):
    from rouh import mcp_servers

    return await _do(request, mcp_servers.test, with_page=False, metered=True)


@only("POST")
@their_clock
async def save(request: HttpRequest):
    from rouh import mcp_servers

    return await _do(request, mcp_servers.save, metered=True)


@only("POST")
@their_clock
async def check(request: HttpRequest):
    from rouh import mcp_servers

    return await _do(request, mcp_servers.check, metered=True)


@only("POST")
@their_clock
async def enabled(request: HttpRequest):
    from rouh import mcp_servers

    return await _do(request, mcp_servers.set_enabled)


@only("POST")
@their_clock
async def ask_first(request: HttpRequest):
    from rouh import mcp_servers

    return await _do(request, mcp_servers.set_ask_first)


@only("POST")
@their_clock
async def remove(request: HttpRequest):
    from rouh import mcp_servers

    return await _do(request, mcp_servers.remove)
