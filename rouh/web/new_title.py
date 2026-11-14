"""A new job title for a contact, over the web (`rouh/new_title.py`, night 43's gene `new_title`).

``GET /mail/new-title/<key>`` is where Change it on their contact on the notice goes: it writes the
job title to the contact in iCloud, says so in a notice of its own, and sends the person back to Rouh,
where that notice is. The key is the notice's own, so no contact id or title travels in the address,
and pressing it a second time changes nothing twice.
"""
from __future__ import annotations

from asgiref.sync import sync_to_async
from django.http import HttpRequest, HttpResponseRedirect

from rouh import new_title, notices

from .common import only, refuse, who


@only("GET")
async def change_it(request: HttpRequest, key: str):
    me = await sync_to_async(who)(request)
    if me is None:
        return HttpResponseRedirect("/login?next=" + request.path)
    if not key.startswith("nt-") or len(key) > 40:
        return refuse("That is not a job title Rouh told you about.", 404)
    if not await sync_to_async(new_title.on)(me):
        return refuse("A new job title in their signature is switched off.", 404)
    from rouh import runtime

    done, said = await new_title.change(me, key, getattr(runtime, "contacts", None))
    if not done:
        await notices.notify(title="The job title was not changed", body=said, kind="mail", who=me)
    return HttpResponseRedirect("/")


__all__ = ["change_it"]
