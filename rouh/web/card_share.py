"""Send their contact card, over the web (`rouh/card_share.py`, night 44's gene `card_share`).

``GET /api/contact-card/<id>`` is what Send their card on a contact card fetches: the contact's vCard
from Rouh's own copy of the person's own card, the picture left out, as a `.vcf` file the page hands to
the phone's share sheet or downloads. Another person's contact, or one that is not a card, is not found.
"""
from __future__ import annotations

from urllib.parse import quote

from asgiref.sync import sync_to_async
from django.http import HttpRequest, HttpResponse

from rouh import card_share

from .common import only, refuse, who


@only("GET")
async def vcard(request: HttpRequest, contact: str):
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("Sign in first.", 401)
    if not await sync_to_async(card_share.on)(me):
        return refuse("Send their contact card is switched off.", 404)
    if len(contact) > 60:
        return refuse("That is not one of your contacts.", 404)
    got = await sync_to_async(card_share.card_for)(me, contact)
    if got is None:
        return refuse("That is not one of your contacts.", 404)
    text, name = got
    response = HttpResponse(text.encode("utf-8"), content_type="text/vcard; charset=utf-8")
    response["Content-Disposition"] = f"attachment; filename*=UTF-8''{quote(name)}"
    response["Cache-Control"] = "no-store"
    return response


__all__ = ["vcard"]
