"""Asked to open a file, over the web (`rouh/access_asked.py`, night 46's gene `access_asked`).

``GET /mail/access-asked/<key>?role=reader|commenter|writer`` is where Let them in and View only on the
notice go: it shares the file with whoever asked, says so in a notice of its own, and sends the person
back to Rouh, where that notice is. The key is the notice's own, so nothing about the file or the person
travels in the link, and pressing it a second time shares nothing twice.
"""
from __future__ import annotations

import logging

from asgiref.sync import sync_to_async
from django.http import HttpRequest, HttpResponseRedirect

from rouh import access_asked, notices

from .common import only, refuse, who

log = logging.getLogger("rouh.web.access_asked")


@only("GET")
async def let_in(request: HttpRequest, key: str):
    me = await sync_to_async(who)(request)
    if me is None:
        return HttpResponseRedirect("/login?next=" + request.get_full_path())
    if not key.startswith("aa-") or len(key) > 40:
        return refuse("That is not a request Rouh told you about.", 404)
    if not await sync_to_async(access_asked.on)(me):
        return refuse("Asked to open a file is switched off.", 404)
    from rouh import runtime

    google = getattr(runtime, "brief_google", None)
    role = str(request.GET.get("role") or "")
    try:
        done, said = await access_asked.let_in(me, key, role, google(me) if google else None)
    except Exception as exc:  # noqa: BLE001 - said, and nothing kept
        log.warning("a request for access could not be answered: %r", exc)
        done, said = False, "Google would not share the file: " + str(exc)[:200]
    if not done:
        await notices.notify(title="Nobody was let in", body=said, kind="mail", who=me)
    return HttpResponseRedirect("/")


__all__ = ["let_in"]
