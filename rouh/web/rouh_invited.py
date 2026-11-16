"""Invited Rouh, not you, over the web (`rouh/rouh_invited.py`, night 45's gene `rouh_invited`).

``GET /mail/rouh-invited/<key>`` is where Put it on my calendar on the notice goes: it puts the meeting on
the person's calendar as the same event, says so in a notice of its own, and sends the person back to
Rouh, where that notice is. The key is the notice's own, so nothing about the meeting travels in the
link, and pressing it a second time puts nothing on twice.
"""
from __future__ import annotations

import logging

from asgiref.sync import sync_to_async
from django.http import HttpRequest, HttpResponseRedirect

from rouh import notices, rouh_invited

from .common import only, refuse, who

log = logging.getLogger("rouh.web.rouh_invited")


@only("GET")
async def put_it_on(request: HttpRequest, key: str):
    me = await sync_to_async(who)(request)
    if me is None:
        return HttpResponseRedirect("/login?next=" + request.path)
    if not key.startswith("ri-") or len(key) > 40:
        return refuse("That is not an invitation Rouh told you about.", 404)
    if not await sync_to_async(rouh_invited.on)(me):
        return refuse("Invited Rouh, not you is switched off.", 404)
    from rouh import runtime

    google = getattr(runtime, "brief_google", None)
    try:
        done, said = await rouh_invited.add(me, key, google(me) if google else None)
    except Exception as exc:  # noqa: BLE001 - said, and nothing kept
        log.warning("an invitation could not be put on the calendar: %r", exc)
        done, said = False, "Google would not put it on the calendar: " + str(exc)[:200]
    if not done:
        await notices.notify(title="It was not put on your calendar", body=said, kind="mail", who=me)
    return HttpResponseRedirect("/")


__all__ = ["put_it_on"]
