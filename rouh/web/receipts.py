"""The Receipts page, at /receipts: every receipt and invoice in the person's mail, by month
(`rouh/receipts.py`).

    GET  /api/receipts              one month's: ?month=2026-09 (this one when left out),
                                    &again=1 to read the mail again rather than the copy
                                    kept a few minutes
    GET  /api/receipts/zip          the month for the accountant, every file and a
                                    receipts.csv, as a zip: ?month=2026-09
    GET  /api/receipts/file         one file of one receipt: ?inbox=&id=&part=

Only the signed-in person's own inboxes and their own Rouh's are read, and only to read.
A file is read from the inbox it is asked for in, which must be theirs. Its switch is
`receipts`: off, every route says so.
"""
from __future__ import annotations

import asyncio
import logging

from django.http import HttpRequest, HttpResponse
from django.utils.http import content_disposition_header

from .clock import _signed_in, their_clock
from .common import answer, only, refuse

log = logging.getLogger("rouh.web.receipts")

NO_STORE = {"Cache-Control": "no-store"}
#: A file out of somebody else's email is shown as itself and can run nothing.
FILE_HEADERS = {"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
                "Content-Security-Policy": "sandbox; default-src 'none'; img-src data:; "
                                           "style-src 'unsafe-inline'"}
#: What a browser may open in a tab; anything else is downloaded.
SHOWN = ("application/pdf", "image/png", "image/jpeg", "image/gif", "image/webp")


def _services(me):
    """The person's Google services, whose Gmail is Rouh's own inbox, or None."""
    from rouh import runtime

    google = getattr(runtime, "brief_google", None)
    return google(me) if google is not None else None


def _zone(request, me):
    from rouh import clock, morning_brief

    return (morning_brief.zone_for_page(me, request.headers.get("X-Time-Zone", ""))
            or clock.zone_of(me))


@only("GET")
@their_clock
async def listing(request: HttpRequest):
    from rouh import receipts

    me = await asyncio.to_thread(_signed_in, request)
    if me is None:
        return refuse("Sign in first.", 401)
    zone = await asyncio.to_thread(_zone, request, me)
    try:
        made = await receipts.month(me, services=_services(me), zone=zone,
                                    asked=request.GET.get("month", ""),
                                    again=request.GET.get("again") == "1")
    except receipts.Refused as exc:
        return refuse(str(exc), 400)
    return answer(made, headers=NO_STORE)


@only("GET")
@their_clock
async def bundle(request: HttpRequest):
    from rouh import receipts

    me = await asyncio.to_thread(_signed_in, request)
    if me is None:
        return refuse("Sign in first.", 401)
    zone = await asyncio.to_thread(_zone, request, me)
    try:
        name, data = await receipts.bundle(me, services=_services(me), zone=zone,
                                           asked=request.GET.get("month", ""))
    except receipts.Refused as exc:
        return refuse(str(exc), 400)
    except Exception as exc:  # noqa: BLE001
        log.warning("the receipts could not be put in a zip: %s", exc)
        return refuse("The receipts could not be read from the mail just now. Try again in "
                      "a moment.", 502)
    response = HttpResponse(data, content_type="application/zip", headers=dict(NO_STORE))
    response["Content-Disposition"] = content_disposition_header(True, name)
    return response


@only("GET")
@their_clock
async def one_file(request: HttpRequest):
    from rouh import receipts

    me = await asyncio.to_thread(_signed_in, request)
    if me is None:
        return refuse("Sign in first.", 401)
    try:
        got = await receipts.one_file(me, services=_services(me),
                                      inbox=request.GET.get("inbox", ""),
                                      message_id=request.GET.get("id", ""),
                                      part=request.GET.get("part", ""))
    except receipts.Refused as exc:
        return refuse(str(exc), 400)
    except Exception as exc:  # noqa: BLE001
        log.warning("a receipt's file could not be read: %s", exc)
        return refuse("That file could not be read from the mail just now.", 502)
    kind = str(got.get("type") or "application/octet-stream").lower()
    shown = kind in SHOWN
    response = HttpResponse(got["data"], content_type=kind if shown else "application/octet-stream",
                            headers=dict(FILE_HEADERS))
    response["Content-Disposition"] = content_disposition_header(not shown,
                                                                 got.get("name") or "file")
    return response
