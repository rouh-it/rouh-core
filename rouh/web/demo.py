"""Demo mode on the web (`rouh/demo.py`): its switch, its approvals, and the layer every answer
passes on its way out while it is on.

    GET  /api/demo                     whether this account is in demo mode, and what is shown
    POST /api/demo                     {"on": true|false}: turn it on or off, for every device
    POST /api/demo/dots                {"dots": true|false}: the purple dots while it is on
    POST /api/demo/preview             {"on": true|false}: this browser only, written down nowhere
    GET  /api/demo/approvals           everything approved, and what changed since
    POST /api/demo/approve             {"kind", "ref", "on"?}: approve one thing, or take it back
    POST /api/demo/copy                {"task"}: a demo copy of a task
    GET  /api/demo/history             every time it was turned on or off, and from where

`DemoLens` is the middleware: the cookie the page's first script reads, kept in step with the
switch, and outside demo mode every demo copy taken out of the lists. The blurring itself is the
browser's, from the style every page carries in its head (`rouh/demo_style.py`).
"""
from __future__ import annotations

import asyncio
import logging
from urllib.parse import quote

from asgiref.sync import iscoroutinefunction, markcoroutinefunction
from django.http import HttpRequest, HttpResponse

from .common import answer, body_of, only, refuse, who

log = logging.getLogger("rouh.web")

NO_STORE = {"Cache-Control": "no-store"}

#: Addresses whose answers hold nothing of anybody's, or are this feature's own.
_PASS = ("/a/", "/static/", "/sw.js", "/healthz", "/api/demo", "/login", "/logout", "/setup",
         "/internal/", "/hooks/", "/.well-known/", "/favicon")
#: And addresses whose answers belong to somebody the page was shared with, never the owner.
_GUESTS = ("/p/", "/shared/", "/join/")


def _preview(request) -> bool:
    from rouh import demo

    return request.COOKIES.get(demo.PREVIEW_COOKIE) == "1"


def _agent(request) -> str:
    return request.headers.get("User-Agent", "")


# --------------------------------------------------------------------------
# The endpoints
# --------------------------------------------------------------------------

async def _me(request):
    return await asyncio.to_thread(who, request)


async def state(request: HttpRequest):
    """GET says it; POST {"on"} turns it."""
    from rouh import demo

    me = await _me(request)
    if me is None:
        return refuse("Sign in first.", 401)
    if request.method == "POST":
        body = body_of(request)
        if not isinstance(body.get("on"), bool):
            return refuse("Say on, true or false.", 400)
        await asyncio.to_thread(demo.turn, me, body["on"], agent=_agent(request),
                                address=str(body.get("address") or "")[:300])
        await demo.broadcast(me)
    elif request.method not in ("GET", "HEAD"):
        return refuse("GET or POST.", 405)
    said = await asyncio.to_thread(demo.page_state, me, _preview(request))
    response = answer(said, headers=NO_STORE)
    _cookie(response, said["on"])
    return response


@only("POST")
async def dots(request: HttpRequest):
    from rouh import demo

    me = await _me(request)
    if me is None:
        return refuse("Sign in first.", 401)
    body = body_of(request)
    await asyncio.to_thread(demo.set_dots, me, bool(body.get("dots")))
    await demo.broadcast(me)
    return answer(await asyncio.to_thread(demo.page_state, me, _preview(request)), headers=NO_STORE)


@only("POST")
async def preview(request: HttpRequest):
    """The preview, for this browser alone: a cookie, and nothing written down."""
    from rouh import demo

    me = await _me(request)
    if me is None:
        return refuse("Sign in first.", 401)
    on = bool(body_of(request).get("on"))
    said = await asyncio.to_thread(demo.page_state, me, on)
    response = answer(said, headers=NO_STORE)
    if on:
        response.set_cookie(demo.PREVIEW_COOKIE, "1", samesite="Lax", httponly=False)
    else:
        response.delete_cookie(demo.PREVIEW_COOKIE, samesite="Lax")
    return response


@only("GET")
async def approvals(request: HttpRequest):
    from rouh import demo

    me = await _me(request)
    if me is None:
        return refuse("Sign in first.", 401)
    return answer(await asyncio.to_thread(demo.approvals, me), headers=NO_STORE)


@only("POST")
async def approve(request: HttpRequest):
    from rouh import demo

    me = await _me(request)
    if me is None:
        return refuse("Sign in first.", 401)
    body = body_of(request)
    kind = str(body.get("kind") or "")
    ref = str(body.get("ref") or "")
    try:
        if body.get("on") is False:
            await asyncio.to_thread(demo.unapprove, me, kind, ref)
            said = {"ok": True, "on": False}
        else:
            got = await asyncio.to_thread(demo.approve, me, kind, ref)
            said = {"ok": True, "on": True, "approved": {"kind": got["kind"]}}
    except ValueError as exc:
        return refuse(str(exc), 400)
    await demo.broadcast(me)
    return answer(said, headers=NO_STORE)


@only("POST")
async def copy(request: HttpRequest):
    from rouh import demo

    me = await _me(request)
    if me is None:
        return refuse("Sign in first.", 401)
    task = str(body_of(request).get("task") or "")
    try:
        made = await asyncio.to_thread(demo.make_copy, me, task)
    except ValueError as exc:
        return refuse(str(exc), 400)
    except Exception as exc:
        log.exception("demo: a copy could not be made of %s", task)
        return refuse(f"The copy could not be made: {exc}", 500)
    await demo.broadcast(me)
    return answer({"ok": True, "number": made["number"],
                   "address": "/task/" + quote(made["folder"], safe="/")}, headers=NO_STORE)


@only("GET")
async def history(request: HttpRequest):
    from rouh import demo

    me = await _me(request)
    if me is None:
        return refuse("Sign in first.", 401)
    return answer({"events": await asyncio.to_thread(demo.history, me)}, headers=NO_STORE)


def _cookie(response: HttpResponse, on: bool) -> None:
    from rouh import demo

    if on:
        response.set_cookie(demo.COOKIE, "1", samesite="Lax", httponly=False, max_age=86400 * 30)
    else:
        response.delete_cookie(demo.COOKIE, samesite="Lax")


# --------------------------------------------------------------------------
# The layer every answer passes
# --------------------------------------------------------------------------

def _owner(request):
    user = getattr(request, "user", None)
    if user is None or not getattr(user, "is_authenticated", False) or getattr(user, "is_guest", False):
        return None
    return who(request)


class DemoLens:
    """The server's half of demo mode, on every answer: the `rouh_demo` cookie kept in step with
    the switch, so a page opened anywhere starts blurred before it asks anything; what is
    being looked at said to the view (`request.rouh_demo`), so a workspace page in a frame is
    handed over in demo mode (`views.workspace_page`); and outside demo mode, no demo copy in
    any list (`demo.hide_copies`). It changes nothing anybody wrote: the blurring is the
    browser's (`rouh/demo_style.py`)."""

    sync_capable = False
    async_capable = True

    def __init__(self, get_response):
        self.get_response = get_response
        if iscoroutinefunction(self.get_response):
            markcoroutinefunction(self)

    async def __call__(self, request):
        from rouh import demo

        path = request.path
        if path.startswith(_PASS) or path.startswith(_GUESTS):
            return await self.get_response(request)
        me = await asyncio.to_thread(_owner, request)
        lens = None
        if me is not None:
            try:
                lens = await asyncio.to_thread(demo.lens_for, me, _preview(request))
            except Exception:
                log.exception("demo: whether demo mode is on could not be read; taking it as on")
                lens = demo.Lens(on=True)
        request.rouh_demo = lens
        response = await self.get_response(request)
        if me is not None:
            on = lens is not None and not lens.preview
            if on != (request.COOKIES.get(demo.COOKIE) == "1"):
                _cookie(response, on)
        if lens is not None:
            # Nothing handed over in demo mode is kept and handed back after it, or before.
            response["X-Rouh-Demo"] = "on"
            response["Cache-Control"] = "no-store"
            return response
        if not response.has_header("Cache-Control") or "no-store" not in response["Cache-Control"]:
            response["Vary"] = ", ".join(filter(None, [response.get("Vary"), "Cookie"]))
        return await self._without_copies(response)

    @staticmethod
    async def _without_copies(response):
        """Outside demo mode a demo copy is in no list."""
        import json as _json

        from rouh import demo

        kind = str(response.get("Content-Type") or "").lower()
        if getattr(response, "streaming", False) or not kind.startswith("application/json"):
            return response
        folders = await asyncio.to_thread(demo.copies)
        if not folders:
            return response
        try:
            data = _json.loads(response.content)
        except ValueError:
            return response
        response.content = _json.dumps(demo.hide_copies(data), ensure_ascii=False).encode()
        if response.has_header("Content-Length"):
            response["Content-Length"] = str(len(response.content))
        return response
