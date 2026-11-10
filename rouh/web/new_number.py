"""A new number in their signature, over the web (`rouh/new_number.py`, night 39's gene `new_number`).

``GET /mail/new-number/<key>`` is where Add it to their contact on the notice goes: it adds the number
to the contact in iCloud, says so in a notice of its own, and sends the person back to Rouh, where
that notice is. The key is the notice's own, so no contact id or number travels in the address, and
pressing it a second time adds nothing twice.
"""
from __future__ import annotations

from asgiref.sync import sync_to_async
from django.http import HttpRequest, HttpResponseRedirect

from rouh import new_number, notices

from .common import only, refuse, who


@only("GET")
async def add_it(request: HttpRequest, key: str):
    me = await sync_to_async(who)(request)
    if me is None:
        return HttpResponseRedirect("/login?next=" + request.path)
    if not key.startswith("nn-") or len(key) > 40:
        return refuse("That is not a number Rouh told you about.", 404)
    if not await sync_to_async(new_number.on)(me):
        return refuse("A new number in their signature is switched off.", 404)
    from rouh import runtime

    done, said = await new_number.add(me, key, getattr(runtime, "contacts", None))
    if not done:
        await notices.notify(title="The number was not added", body=said, kind="mail", who=me)
    return HttpResponseRedirect("/")


__all__ = ["add_it"]
