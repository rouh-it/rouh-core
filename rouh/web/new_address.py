"""A new address for a contact, over the web (`rouh/new_address.py`, night 40's gene `new_address`).

``GET /mail/new-address/<key>`` is where Add it to their contact on the notice goes: it adds the address
to the contact in iCloud, says so in a notice of its own, and sends the person back to Rouh, where
that notice is. The key is the notice's own, so no contact id or address travels in the address, and
pressing it a second time adds nothing twice.
"""
from __future__ import annotations

from asgiref.sync import sync_to_async
from django.http import HttpRequest, HttpResponseRedirect

from rouh import new_address, notices

from .common import only, refuse, who


@only("GET")
async def add_it(request: HttpRequest, key: str):
    me = await sync_to_async(who)(request)
    if me is None:
        return HttpResponseRedirect("/login?next=" + request.path)
    if not key.startswith("na-") or len(key) > 40:
        return refuse("That is not an address Rouh told you about.", 404)
    if not await sync_to_async(new_address.on)(me):
        return refuse("A new address for a contact is switched off.", 404)
    from rouh import runtime

    done, said = await new_address.add(me, key, getattr(runtime, "contacts", None))
    if not done:
        await notices.notify(title="The address was not added", body=said, kind="mail", who=me)
    return HttpResponseRedirect("/")


__all__ = ["add_it"]
