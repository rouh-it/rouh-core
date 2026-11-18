"""Files they can open, over the web (`rouh/their_files.py`, night 47's gene `their_files`).

``GET /api/contact-files/<contact>`` is what Files they can open on a contact card fetches: the person's
own Drive files that one of the contact's addresses can open, read at the press. ``POST
/api/contact-files/<contact>/take-off`` with ``{"file": <id>}`` is Take off beside one of them: that
contact's own access to that file alone is taken away. Another person's contact is not found.
"""
from __future__ import annotations

import json
import logging

from asgiref.sync import sync_to_async
from django.http import HttpRequest, JsonResponse

from rouh import their_files

from .common import only, refuse, who

log = logging.getLogger("rouh.web.their_files")


async def _ready(request: HttpRequest, contact: str):
    me = await sync_to_async(who)(request)
    if me is None:
        return None, None, refuse("Sign in first.", 401)
    if not await sync_to_async(their_files.on)(me):
        return None, None, refuse("Files they can open is switched off.", 404)
    if len(contact) > 60:
        return None, None, refuse("That is not one of your contacts.", 404)
    from rouh import runtime

    google = getattr(runtime, "brief_google", None)
    return me, (google(me) if google else None), None


@only("GET")
async def listing(request: HttpRequest, contact: str):
    me, services, refused = await _ready(request, contact)
    if refused is not None:
        return refused
    try:
        got = await their_files.files_of(me, contact, services)
    except Exception as exc:  # noqa: BLE001 - said on the card
        log.warning("the files a contact can open could not be read: %r", exc)
        got = {"error": "Google would not list your files: " + str(exc)[:200]}
    return JsonResponse(got, status=200 if "error" not in got else 409)


@only("POST")
async def take_off(request: HttpRequest, contact: str):
    me, services, refused = await _ready(request, contact)
    if refused is not None:
        return refused
    try:
        body = json.loads(request.body or b"{}")
    except ValueError:
        body = {}
    file_id = str((body or {}).get("file") or "").strip()
    if not file_id or len(file_id) > 200:
        return refuse("Say which file.", 400)
    try:
        got = await their_files.take_off(me, contact, file_id, services)
    except Exception as exc:  # noqa: BLE001 - said on the card
        log.warning("a contact could not be taken off a file: %r", exc)
        got = {"error": "Google would not take them off: " + str(exc)[:200]}
    return JsonResponse(got, status=200 if "error" not in got else 409)


__all__ = ["listing", "take_off"]
