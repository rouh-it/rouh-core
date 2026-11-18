"""Asked in a comment, over the web (`rouh/comment_asks.py`, night 47's gene `comment_asks`).

``GET /mail/comment-asks/<key>`` is where Say Rouh has seen it on the notice goes: it writes under the
comment from Rouh's own account, says so in a notice of its own, and sends the person back to Rouh.
``?open=1`` is Open the comment: it goes on to the comment in the document. The key is the notice's own,
so nothing about the document travels in the link, and pressing it a second time writes nothing twice.
"""
from __future__ import annotations

import logging

from asgiref.sync import sync_to_async
from django.http import HttpRequest, HttpResponseRedirect

from rouh import comment_asks, notices

from .common import only, refuse, who

log = logging.getLogger("rouh.web.comment_asks")


@only("GET")
async def answer_it(request: HttpRequest, key: str):
    me = await sync_to_async(who)(request)
    if me is None:
        return HttpResponseRedirect("/login?next=" + request.get_full_path())
    if not key.startswith("ca-") or len(key) > 40:
        return refuse("That is not a comment Rouh told you about.", 404)
    if not await sync_to_async(comment_asks.on)(me):
        return refuse("Asked in a comment is switched off.", 404)
    if request.GET.get("open"):
        where = await comment_asks.opened(me, key)
        if not where:
            return refuse("That is not a comment Rouh told you about.", 404)
        return HttpResponseRedirect(where)
    from rouh import runtime

    google = getattr(runtime, "brief_google", None)
    try:
        done, said = await comment_asks.answer(me, key, google(me) if google else None)
    except Exception as exc:  # noqa: BLE001 - said, and nothing kept
        log.warning("a comment asking Rouh could not be answered: %r", exc)
        done, said = False, "Google would not take the answer: " + str(exc)[:200]
    if not done:
        await notices.notify(title="Nothing was written under the comment", body=said, kind="mail", who=me)
    return HttpResponseRedirect("/")


__all__ = ["answer_it"]
