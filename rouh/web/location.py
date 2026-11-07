"""Settings for where the person is: the Location card at the top of Settings.

    GET  /api/settings/location           what the card draws
    POST /api/settings/location           keep a point: {"lat", "lon", "accuracy", "source",
                                          "asked"}; "asked" is the person pressing Share
    POST /api/settings/location/place     a place typed by hand: {"place": "Frankfurt"},
                                          for when the device cannot say where it is
    POST /api/settings/location/forget    forget it; the device's zone is the clock again
    POST /api/settings/location/second    the second time zone: {"zone": "Europe/Lisbon"},
                                          or {"zone": ""} for none

Every request carries the zone the page's device is on as `X-Time-Zone`, which
is kept as the device's (`clock.remember`) and stands in for the location's
zone when that cannot be worked out. The point may come from a browser today
and from a phone app later, which posts the same thing with `source` "phone".
`rouh/location.py` holds what it means and where it is kept; this file is only
the route. The person's own, so anybody signed in reads and changes their own.
"""
from __future__ import annotations

from asgiref.sync import sync_to_async
from django.http import HttpRequest

from rouh import clock, location

from .common import answer, body_of, only, refuse, who


def _me(request):
    me = who(request)
    zone = request.headers.get("X-Time-Zone", "")
    if me is not None and zone:
        clock.remember(me, zone)
    return me


def _card(me, device: str) -> dict:
    """The section's state, with where the installation's own clock is (`clock.DEFAULT`),
    which the page names while nothing better is known: "Until then Rouh keeps Lisbon time"."""
    out = location.card(me, device)
    out["default_place"] = clock.place(clock.DEFAULT)
    return out


@only("GET", "POST")
async def settings_location(request: HttpRequest):
    me = await sync_to_async(_me)(request)
    if me is None:
        return refuse("sign in", 401)
    device = request.headers.get("X-Time-Zone", "")
    if request.method == "POST":
        sent = body_of(request)
        kept = await sync_to_async(location.keep)(
            me, sent.get("lat"), sent.get("lon"), sent.get("accuracy"),
            source=str(sent.get("source") or "browser"), device_zone=device,
            asked=bool(sent.get("asked")))
        if kept is None:
            return refuse("That is not a place on Earth.", 400)
    return answer(await sync_to_async(_card)(me, device))


@only("POST")
async def typed_place(request: HttpRequest):
    me = await sync_to_async(_me)(request)
    if me is None:
        return refuse("sign in", 401)
    text = str(body_of(request).get("place") or "").strip()
    if not text:
        return refuse("Type a town, an airport or an address.", 400)
    try:
        found = await sync_to_async(location.find)(text)
    except LookupError:
        return refuse("The map service did not answer, so the place could not be looked up. "
                      "Try again in a moment.", 502)
    if found is None:
        return refuse(f"No place called “{text[:80]}” was found. Try a town and its country.", 422)
    lat, lon, place = found
    device = request.headers.get("X-Time-Zone", "")
    await sync_to_async(location.keep)(me, lat, lon, None, source="typed",
                                       device_zone=device, asked=True, place=place)
    return answer(await sync_to_async(_card)(me, device))


@only("POST")
async def forget(request: HttpRequest):
    me = await sync_to_async(_me)(request)
    if me is None:
        return refuse("sign in", 401)
    await sync_to_async(location.forget)(me)
    return answer(await sync_to_async(_card)(me, request.headers.get("X-Time-Zone", "")))


@only("POST")
async def second_zone(request: HttpRequest):
    me = await sync_to_async(_me)(request)
    if me is None:
        return refuse("sign in", 401)
    if not await sync_to_async(location.keep_second_zone)(me, body_of(request).get("zone")):
        return refuse("That is not a time zone Rouh knows.", 400)
    return answer(await sync_to_async(_card)(me, request.headers.get("X-Time-Zone", "")))
