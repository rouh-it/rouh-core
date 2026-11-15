"""A new address in their signature, over the web (`rouh/sig_address.py`, night 44's gene `sig_address`).

``GET /mail/new-address-sig/<key>`` is where Add it to their contact on the notice goes, and
``?replace=1`` is Add it, take the old one off: it changes the contact in iCloud, says so in a notice of
its own, and sends the person back to Rouh, where that notice is. The key is the notice's own, so no
contact id or address travels in the link, and pressing it a second time changes nothing twice.
"""
from __future__ import annotations

from asgiref.sync import sync_to_async
from django.http import HttpRequest, HttpResponseRedirect

from rouh import notices, sig_address

from .common import only, refuse, who


@only("GET")
async def add_it(request: HttpRequest, key: str):
    me = await sync_to_async(who)(request)
    if me is None:
        return HttpResponseRedirect("/login?next=" + request.path)
    if not key.startswith("sa-") or len(key) > 40:
        return refuse("That is not an address Rouh told you about.", 404)
    if not await sync_to_async(sig_address.on)(me):
        return refuse("A new address in their signature is switched off.", 404)
    from rouh import runtime

    replace = request.GET.get("replace") == "1"
    done, said = await sig_address.add(me, key, getattr(runtime, "contacts", None), replace=replace)
    if not done:
        await notices.notify(title="The address was not added", body=said, kind="mail", who=me)
    return HttpResponseRedirect("/")


__all__ = ["add_it"]
