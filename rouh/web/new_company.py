"""A new company for a contact, over the web (`rouh/new_company.py`, night 41's gene `new_company`).

``GET /mail/new-company/<key>`` is where Change it on their contact on the notice goes: it writes the
company to the contact in iCloud, says so in a notice of its own, and sends the person back to Rouh,
where that notice is. The key is the notice's own, so no contact id or company travels in the address,
and pressing it a second time changes nothing twice.
"""
from __future__ import annotations

from asgiref.sync import sync_to_async
from django.http import HttpRequest, HttpResponseRedirect

from rouh import new_company, notices

from .common import only, refuse, who


@only("GET")
async def change_it(request: HttpRequest, key: str):
    me = await sync_to_async(who)(request)
    if me is None:
        return HttpResponseRedirect("/login?next=" + request.path)
    if not key.startswith("nc-") or len(key) > 40:
        return refuse("That is not a company Rouh told you about.", 404)
    if not await sync_to_async(new_company.on)(me):
        return refuse("A new company in their signature is switched off.", 404)
    from rouh import runtime

    done, said = await new_company.change(me, key, getattr(runtime, "contacts", None))
    if not done:
        await notices.notify(title="The company was not changed", body=said, kind="mail", who=me)
    return HttpResponseRedirect("/")


__all__ = ["change_it"]
