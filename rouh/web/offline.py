"""Rouh offline, over HTTP (`rouh/offline.py`).

    GET  /api/offline/pack/<part>   one part of this device's offline copy: calendar, decisions,
                                    tasks, chats, mail or contacts, the same on every device.
                                    ?page=N for mail (five days a page, the newest first) and
                                    chats (25 chats a page); the answer says how many `pages`
    POST /api/offline/outbox        what one device did offline:
                                    {device: {id, name, kind}, actions: [{id, kind, payload,
                                    base, made_at}]}; each is carried out once, and the answer
                                    is what became of every one
    GET  /api/offline/outbox        what became of his actions, from both devices: ?since=
    GET  /sw.js                     the service worker that keeps the page and its copy

Everything but the service worker is the signed-in person's own and nobody else's. The
service worker is the same script for everybody, holds nothing of anybody's, and is open
like the page's other files, so the browser can check it for an update whoever is signed in.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging

from django.http import HttpRequest, HttpResponse

from .clock import _signed_in, their_clock
from .common import answer, body_of, only, refuse

log = logging.getLogger("rouh.web.offline")

NO_STORE = {"Cache-Control": "no-store"}


def owner_of(me) -> str:
    """What the page and the service worker call this person: never their id itself.

    The offline copy is kept under it and opened only by it, and a page served to anybody
    else carries another one, which is what makes the service worker clear the copy rather
    than hand it to them."""
    if me is None:
        return ""
    return hashlib.sha256(f"rouh-offline:{me.org_id}:{me.user_id}".encode()).hexdigest()[:20]


@only("GET")
@their_clock
async def pack(request: HttpRequest, part: str):
    from rouh import offline

    me = await asyncio.to_thread(_signed_in, request)
    if me is None:
        return refuse("Sign in first.", 401)
    if part not in offline.PARTS:
        return refuse("There is no such part of the offline copy.", 404)
    try:
        page = int(request.GET.get("page") or 0)
    except ValueError:
        page = 0
    try:
        got = await offline.pack_part(me, part, page)
    except Exception as exc:  # noqa: BLE001 - one part failing is said, and the others still come
        log.exception("the offline %s part could not be made", part)
        return refuse(f"The {part} could not be read just now: {exc}", 502)
    return answer(got, headers=NO_STORE)


@their_clock
async def outbox(request: HttpRequest):
    from rouh import offline

    me = await asyncio.to_thread(_signed_in, request)
    if me is None:
        return refuse("Sign in first.", 401)
    if request.method == "GET":
        try:
            since = float(request.GET.get("since") or 0)
        except ValueError:
            since = 0.0
        return answer({"results": await asyncio.to_thread(offline.results, me, since)},
                      headers=NO_STORE)
    if request.method != "POST":
        return HttpResponse(status=405, headers={"Allow": "GET, POST"})
    body = body_of(request)
    device = body.get("device") if isinstance(body.get("device"), dict) else {}
    actions = body.get("actions") if isinstance(body.get("actions"), list) else []
    if not actions:
        return answer({"results": []}, headers=NO_STORE)
    # The account it came with, for what is carried out through its own view (`offline._clock`).
    got = await offline.take(me, device, actions, user=getattr(request, "user", None))
    return answer({"results": got}, headers=NO_STORE)


@only("GET")
async def service_worker(request: HttpRequest):
    """The service worker, at the top of the site so that it may look after all of it.

    Its text names the build, so every deploy is a new worker the browser installs by
    itself, and the page's files at their hashed addresses, which it keeps for the page to
    open with no connection."""
    from . import assets

    text = assets.body("sw.js").decode("utf-8")
    text = text.replace('"__ROUH_BUILD__"', json.dumps(assets.ASSETS))
    text = text.replace('"__ROUH_SHELL__"', json.dumps(shell_files()))
    return HttpResponse(text, content_type="application/javascript; charset=utf-8",
                        headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"})


#: The page's files the service worker keeps ahead of time. Not the speech model and its
#: runtime, which are megabytes and only hear the microphone, nor the service worker itself.
_SKIPPED = ("ort", "silero", "sw.js")


def shell_files() -> list[str]:
    from . import assets

    names = [n for n in assets.ASSET_NAMES
             if n.endswith((".js", ".css", ".png", ".svg", ".webmanifest"))
             and not n.startswith(_SKIPPED)]
    out = [assets.address(n) for n in names] + assets.module_addresses()
    return sorted(set(out))
