"""A contact's face and addresses, for the contact card, the meeting card and the profile.

    GET  /api/people/<person id>/photo              the picture, or 404 when they have none
    GET  /api/people/<person id>/addresses          every address of theirs, as one list
    POST /api/people/<person id>/addresses/silo     {"address", "silo"}: that address's silo

The picture on their iCloud card when it carries one, else the LinkedIn photo Rouh kept for
them before a meeting (`rouh/meeting_people.py`, `photo_of`). Only ever the signed-in person's
own contact: the person is looked up in their own Synapse Master, by both their ids, so an id
from somebody else's Master is simply not found.
"""
from __future__ import annotations

import asyncio
import re

from django.http import HttpRequest, HttpResponse

from .common import answer, body_of, only, refuse, who

#: A person's id in Synapse.
_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


@only("GET")
async def photo(request: HttpRequest, person_id: str):
    from rouh import meeting_people

    me = await asyncio.to_thread(who, request)
    if me is None:
        return refuse("Sign in first.", 401)
    if not _ID.match(person_id or ""):
        return refuse("not found", 404)
    got = await asyncio.to_thread(meeting_people.photo_of, me, person_id)
    if got is None:
        return refuse("not found", 404)
    body, kind = got
    response = HttpResponse(body, content_type=kind if kind.startswith("image/") else "image/jpeg")
    # Private: the person's own contact, behind their sign-in. The address changes with the
    # picture (`photo_url`), so it can be kept a day.
    response["Cache-Control"] = "private, max-age=86400"
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = "sandbox; default-src 'none'"
    return response


def _addresses_now(me, person_id: str) -> dict | None:
    from rouh import person_addresses
    from rouh.people import People

    person = People().person(str(me.user_id), str(me.org_id), person_id)
    if person is None:
        return None
    return person_addresses.view(str(me.user_id), str(me.org_id), person)


@only("GET")
async def addresses(request: HttpRequest, person_id: str):
    """GET /api/people/<person id>/addresses: every address of the person as one list
    (`rouh/person_addresses.py`), the same rows the contact card and the profile draw."""
    me = await asyncio.to_thread(who, request)
    if me is None:
        return refuse("Sign in first.", 401)
    if not _ID.match(person_id or ""):
        return refuse("not found", 404)
    got = await asyncio.to_thread(_addresses_now, me, person_id)
    if got is None:
        return refuse("That contact is not there.", 404)
    return answer({"ok": True, **got}, headers={"Cache-Control": "no-store"})


@only("POST")
async def address_silo(request: HttpRequest, person_id: str):
    """POST /api/people/<person id>/addresses/silo {"address", "silo"}: one of the person's addresses put in
    a silo, or ("" for silo) taken out of it. Answers the list as it now reads."""
    from rouh import person_addresses, silos

    me = await asyncio.to_thread(who, request)
    if me is None:
        return refuse("Sign in first.", 401)
    if not _ID.match(person_id or ""):
        return refuse("not found", 404)
    body = body_of(request)
    address = str(body.get("address") or "").strip().lower()[:320]
    now = await asyncio.to_thread(_addresses_now, me, person_id)
    if now is None:
        return refuse("That contact is not there.", 404)
    if address not in {r["address"].lower() for r in now["rows"]}:
        return refuse("That address is not one of theirs.", 400)
    try:
        await asyncio.to_thread(person_addresses.set_silo, str(me.user_id), str(me.org_id), address,
                                str(body.get("silo") or "") or None)
    except silos.Refused as exc:
        return refuse(str(exc), 400)
    got = await asyncio.to_thread(_addresses_now, me, person_id)
    return answer({"ok": True, **(got or {})})
