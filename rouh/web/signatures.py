"""Settings for the signatures under the email Rouh sends: each person's own.

    GET  /api/settings/signatures   what the Email signatures card draws
    POST /api/settings/signatures   save both: {"new", "reply"}

Unlike the models, these are the person's and nobody else's, so anybody signed
in may read and change their own and no one else's. `rouh/signatures.py`
holds what they mean and where they are kept; this file is only the route.
"""
from __future__ import annotations

from asgiref.sync import sync_to_async
from django.http import HttpRequest

from rouh import signatures

from .common import answer, body_of, only, refuse, who


@only("GET", "POST")
async def settings_signatures(request: HttpRequest):
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("sign in", 401)
    if request.method == "GET":
        return answer({**(await sync_to_async(signatures.get)(me)), "most": signatures.MOST})
    sent = body_of(request)
    for key in (signatures.NEW, signatures.ANSWER):
        if not isinstance(sent.get(key, ""), str):
            return refuse("A signature is text.", 400)
        if len(sent.get(key) or "") > signatures.MOST:
            return refuse(f"A signature is at most {signatures.MOST} characters.", 400)
    kept = await sync_to_async(signatures.put)(
        me, sent.get(signatures.NEW, ""), sent.get(signatures.ANSWER, ""))
    return answer({"ok": True, **kept, "most": signatures.MOST})
