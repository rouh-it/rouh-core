"""Settings, Stats, at /settings/stats, and what it counts (`rouh/navtaps.py`,
`rouh/events.py`).

    GET  /api/settings/stats          the Navigation tab: the group boxes and the links
                                      beside each, how often each was pressed in the last
                                      30 days, and the flow from one to the next
    POST /api/nav/tap                 {item, visit}: one press of one row of the navigation,
                                      or of one of its group boxes ("group:<id>"), in the
                                      page load `visit`
    GET  /api/settings/stats/events   the Event log tab, /settings/stats/events: the
                                      signed-in person's own numbers from the event log
    POST /api/events                  {session, events: [...]}: a batch from the page's
                                      tracker (`rouh/static/track.js`), queued, never waited on

Petar, 10 October 2026 (fr_e82bf294e064, and the event log the same evening). Every query
names the signed-in person's user and organisation: the counts are theirs, from every
device they use.
"""
from __future__ import annotations

import asyncio
import json

from django.http import HttpRequest

from .clock import _signed_in
from .common import answer, body_of, only, refuse

NO_STORE = {"Cache-Control": "no-store"}


@only("GET")
async def page(request: HttpRequest):
    from rouh import navtaps

    me = await asyncio.to_thread(_signed_in, request)
    if me is None:
        return refuse("Sign in first.", 401)
    return answer(await asyncio.to_thread(navtaps.page, me), headers=NO_STORE)


@only("POST")
async def tap(request: HttpRequest):
    from rouh import navtaps

    me = await asyncio.to_thread(_signed_in, request)
    if me is None:
        return refuse("Sign in first.", 401)
    try:
        body = body_of(request)
        await asyncio.to_thread(navtaps.record, me, body.get("item"), visit=body.get("visit") or "")
    except navtaps.Refused as exc:
        return refuse(str(exc), 400)
    return answer({"ok": True}, headers=NO_STORE)


#: The most a batch from the page may weigh. The tracker sends far less.
HEAVIEST = 256 * 1024


@only("POST")
async def take(request: HttpRequest):
    from rouh import events

    me = await asyncio.to_thread(_signed_in, request)
    if me is None:
        return refuse("Sign in first.", 401)
    if len(request.body or b"") > HEAVIEST:
        return refuse("That batch is too big.", 413)
    try:
        sent = json.loads(request.body or b"null")
    except (ValueError, UnicodeDecodeError):
        return refuse("Send {session, events}.", 400)
    try:
        # Checked and queued here; written by the event log's own thread, so this
        # answers at once whatever the database is doing.
        got = events.take(me, sent)
    except events.Refused as exc:
        return refuse(str(exc), 400)
    return answer(got, status=202, headers=NO_STORE)


@only("GET")
async def event_log(request: HttpRequest):
    from rouh import clock, events

    me = await asyncio.to_thread(_signed_in, request)
    if me is None:
        return refuse("Sign in first.", 401)
    zone = clock.zone_named(request.headers.get("X-Time-Zone", ""))
    return answer(await asyncio.to_thread(events.stats, me, zone=zone), headers=NO_STORE)
