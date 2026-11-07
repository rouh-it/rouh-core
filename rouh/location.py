"""Where the person is: a place, kept as theirs, and the time zone it gives.

Petar, 30 September 2026 (fr_ed03633d613c): "I would like to have you know my
location. Now through browser permission and later when this is an app through
phone location. I want to see my location. In settings on the very top. And
location should give you timezone (also consider summertime winter savings)".

So a location is a point (latitude, longitude, how sure) that something the
person carries reported, with `source` saying what: "browser" today, from the
Location card at the top of Settings, and a phone app later posting the same
thing to the same route (`rouh/web/location.py`). Nothing here knows how the
point was measured, which is what lets the source be swapped.

From the point two things are worked out, each by asking a public service with
no key:

- **The time zone**, as an IANA name ("Europe/Lisbon"), from Open-Meteo's
  forecast API with `timezone=auto`, the service the morning brief's weather
  already comes from. A name and never an offset: the offset is read from the
  zone at the moment it is wanted (`clock.offset`), so summer and winter time
  come and go by themselves. That zone is then the person's clock everywhere
  (`clock.locate`), above the one their device reports, until they forget
  the location. If the service cannot be reached, the zone the device is on
  stands in, and the card says so.
- **The place**, as a person says it ("Lisbon, Portugal"), from OpenStreetMap's
  Nominatim at the level of a town. If that cannot be read, the card shows the
  coordinates rather than nothing.

Both are asked again only when the point has moved more than `MOVED` metres or
the one kept is older than `STALE` seconds, so a page that reports on every
visit costs nobody anything.

Kept in `user_settings` under `NAME`, like the time zone and the signatures,
with both ids in every query as `tenancy.py` requires. It is the person's own
and nobody else's.
"""
from __future__ import annotations

import json
import logging
import math
import os
import threading
import time
from datetime import datetime, timedelta, timezone

import httpx

from . import clock

log = logging.getLogger("rouh.location")

#: Where it is kept, in `user_settings`.
NAME = "location"

#: What may say where the person is. A phone app is the next one; "typed" is
#: a place the person typed on the card because their device could not say
#: (fr_89af9a2376cf, below under `find`).
SOURCES = ("browser", "phone", "typed")

#: Moved this far (metres), and the place and zone are worked out again.
MOVED = 1000.0

#: Kept this long (seconds), and they are worked out again even without moving.
STALE = 24 * 3600

ZONE_URL = os.environ.get("ROUH_LOCATION_ZONE_URL", "https://api.open-meteo.com/v1/forecast")
PLACE_URL = os.environ.get("ROUH_LOCATION_PLACE_URL",
                           "https://nominatim.openstreetmap.org/reverse")
SEARCH_URL = os.environ.get("ROUH_LOCATION_SEARCH_URL",
                            "https://nominatim.openstreetmap.org/search")
#: Nominatim's policy asks every caller to say who it is.
AGENT = "Rouh/1.0 (personal assistant; location for its own user)"

#: Each person's kept location, by user id, read when Rouh starts (`load`) and
#: written through by `keep` and `forget`, so the prompt never waits on a query.
_HELD: dict[str, dict] = {}
_LOCK = threading.Lock()


def _point(lat, lon, accuracy):
    try:
        lat, lon = float(lat), float(lon)
        accuracy = float(accuracy) if accuracy not in (None, "") else None
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(lat) and math.isfinite(lon)) or abs(lat) > 90 or abs(lon) > 180:
        return None
    if accuracy is not None and (not math.isfinite(accuracy) or accuracy < 0):
        accuracy = None
    return lat, lon, accuracy


def distance(a: tuple, b: tuple) -> float:
    """Metres between two (lat, lon) points, along the ground."""
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = (math.sin((la2 - la1) / 2) ** 2
         + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2)
    return 2 * 6371000.0 * math.asin(min(1.0, math.sqrt(h)))


def _zone_at(lat: float, lon: float):
    """The IANA zone at this point, or None if it could not be read."""
    try:
        got = httpx.get(ZONE_URL, params={"latitude": lat, "longitude": lon,
                                          "timezone": "auto", "forecast_days": 1},
                        timeout=8.0)
        got.raise_for_status()
        return clock.zone_named(got.json().get("timezone"))
    except (httpx.HTTPError, ValueError, AttributeError) as exc:
        log.warning("the time zone at a location could not be read: %s", exc)
        return None


def _place_at(lat: float, lon: float) -> str:
    """The town and country at this point, as a person says it, or ""."""
    try:
        got = httpx.get(PLACE_URL, params={"lat": lat, "lon": lon, "format": "jsonv2",
                                           "zoom": 10, "accept-language": "en"},
                        headers={"User-Agent": AGENT}, timeout=8.0)
        got.raise_for_status()
        body = got.json()
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("the place at a location could not be read: %s", exc)
        return ""
    return said_place(body)


def said_place(body) -> str:
    """"Lisbon, Portugal" from a Nominatim answer; "" if it names nothing."""
    if not isinstance(body, dict):
        return ""
    address = body.get("address") if isinstance(body.get("address"), dict) else {}
    town = next((str(address[k]) for k in ("city", "town", "village", "hamlet",
                                             "municipality", "suburb", "county")
                 if address.get(k)), "") or str(body.get("name") or "")
    region = str(address.get("state") or "")
    country = str(address.get("country") or "")
    # The region only where there is no town: "Lisbon, Lisbon District, Portugal"
    # says the same thing twice.
    out = ", ".join(p for p in (town or region, country) if p)
    return out[:120]


def _row(who) -> dict | None:
    from .models import UserSetting

    value = (UserSetting.objects
             .filter(user_id=str(who.user_id), org_id=who.org_id or "", name=NAME)
             .values_list("value", flat=True).first())
    try:
        held = json.loads(value) if value else None
    except (TypeError, ValueError):
        return None
    return held if isinstance(held, dict) else None


def _read(who) -> dict | None:
    held = _row(who)
    return held if held and "lat" in held and "lon" in held else None


def get(who) -> dict | None:
    """This person's kept location, or None."""
    if who is None or not getattr(who, "user_id", None):
        return None
    return _read(who)


def held(who) -> dict | None:
    """The kept location without a query, for the prompt: what `load` and `keep` left."""
    user = getattr(who, "user_id", None)
    return _HELD.get(str(user)) if user else None


def keep(who, lat, lon, accuracy=None, *, source="browser", device_zone="",
         asked: bool = True, now: float | None = None, place: str = "") -> dict | None:
    """Keep where this person is now, and the zone it gives. What is kept, or None.

    `asked` is the person sharing it (Share my location); a page reporting by
    itself is not, and is not kept once they have pressed Forget, because the
    browser's permission outlives the Forget and would bring it straight back.
    A page reporting by itself does not replace a place the person typed
    either: they typed it because the device could not say, or said wrong,
    and only their own press of Update now puts the device's back.
    The place and the zone are asked for only when the point moved or the one
    kept is old; otherwise the new point is kept with the old answers. A
    `place` given is the name the point was found by, and is kept as it is.
    """
    point = _point(lat, lon, accuracy)
    if point is None or who is None or not getattr(who, "user_id", None):
        return None
    lat, lon, accuracy = point
    source = source if source in SOURCES else "browser"
    now = time.time() if now is None else now
    row = _row(who)
    if not asked and row and (row.get("forgotten") or row.get("source") == "typed"):
        return row
    before = row if row and "lat" in row else None
    fresh = (not place and before is not None and before.get("zone") and before.get("place")
             and distance((lat, lon), (before["lat"], before["lon"])) < MOVED
             and now - float(before.get("looked", 0) or 0) < STALE
             and before.get("zone_from") == "location")
    if fresh:
        place, zone_name, zone_from = before.get("place", ""), before["zone"], "location"
        looked = float(before.get("looked", now))
    else:
        found = _zone_at(lat, lon)
        place = place or _place_at(lat, lon)
        if found is not None:
            zone_name, zone_from = found.key, "location"
        else:
            device = clock.zone_named(device_zone)
            zone_name = (device or clock.zone_of(who)).key
            zone_from = "device"
        looked = now
    kept = {"lat": round(lat, 5), "lon": round(lon, 5),
            "accuracy": round(accuracy) if accuracy is not None else None,
            "place": place, "zone": zone_name, "zone_from": zone_from,
            "source": source, "at": now, "looked": looked}
    _write(who, kept)
    with _LOCK:
        _HELD[str(who.user_id)] = kept
    # Only a zone the location gave outranks the device's; one that stood in
    # for it is the device's own anyway.
    clock.locate(who, zone_name if zone_from == "location" else None)
    return kept


def find(text: str):
    """The place a person typed, as (lat, lon, "Frankfurt am Main, Germany"), or None.

    Petar, 15 October 2026 (fr_89af9a2376cf), on a plane with Wi-Fi: "Location
    should be able to be set by the gps. I see no reason for this to fail".
    His iPad's Safari gave nothing but CoreLocation's "kCLErrorDomain error 0",
    which is the device not knowing where it is: with no GPS fix it places
    itself by the Wi-Fi networks around it, and a plane's are nowhere. So the
    card takes a place typed by hand too, a town, an airport or an address,
    found with OpenStreetMap's Nominatim, the service the place names already
    come from. Raises `LookupError` when Nominatim cannot be reached, so the
    card can tell "no such place" from "try again".
    """
    text = " ".join(str(text or "").split())[:200]
    if not text:
        return None
    try:
        got = httpx.get(SEARCH_URL, params={"q": text, "format": "jsonv2", "limit": 1,
                                            "addressdetails": 1, "accept-language": "en"},
                        headers={"User-Agent": AGENT}, timeout=8.0)
        got.raise_for_status()
        body = got.json()
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("a typed place could not be looked up: %s", exc)
        raise LookupError("the place could not be looked up") from exc
    first = body[0] if isinstance(body, list) and body and isinstance(body[0], dict) else None
    point = _point(first.get("lat"), first.get("lon"), None) if first else None
    if point is None:
        return None
    return point[0], point[1], said_place(first) or text[:120]


def _write(who, kept: dict) -> None:
    from .models import UserSetting

    UserSetting.objects.bulk_create(
        [UserSetting(user_id=str(who.user_id), org_id=who.org_id or "", name=NAME,
                     value=json.dumps(kept, ensure_ascii=False), updated_at=time.time())],
        update_conflicts=True, unique_fields=["user_id", "name"],
        update_fields=["org_id", "value", "updated_at"])


def forget(who) -> None:
    """Forget where this person is. Their device's zone is their clock again.

    What is left is only that they forgot it, so a page does not quietly
    share it again (`keep`); Share my location is how it comes back.
    """
    _write(who, {"forgotten": True, "at": time.time()})
    with _LOCK:
        _HELD.pop(str(who.user_id), None)
    clock.locate(who, None)


def load() -> int:
    """Read everybody's kept location, and give the clock their zones. How many."""
    from .models import UserSetting

    found: dict[str, dict] = {}
    for user, value in UserSetting.objects.filter(name=NAME).values_list("user_id", "value"):
        try:
            held_one = json.loads(value)
        except (TypeError, ValueError):
            continue
        if isinstance(held_one, dict) and "lat" in held_one:
            found[str(user)] = held_one
    with _LOCK:
        _HELD.update(found)
    clock.located({user: one.get("zone") for user, one in found.items()
                   if one.get("zone_from") == "location"})
    return len(found)


def next_change(zone, after: datetime | None = None, days: int = 400):
    """When this zone's clocks next change, and to what offset: (datetime, timedelta) or None.

    Found by stepping a day at a time and then narrowing to the minute, because
    `zoneinfo` does not hand out its transitions. A zone with no summer time
    gives None.
    """
    start = (after or datetime.now(timezone.utc)).astimezone(timezone.utc)
    first = start.astimezone(zone).utcoffset()
    lo = start
    for _ in range(days):
        hi = lo + timedelta(days=1)
        if hi.astimezone(zone).utcoffset() != first:
            while hi - lo > timedelta(minutes=1):
                mid = lo + (hi - lo) / 2
                if mid.astimezone(zone).utcoffset() == first:
                    lo = mid
                else:
                    hi = mid
            when = hi.replace(second=0, microsecond=0).astimezone(zone)
            return when, when.utcoffset()
        lo = hi
    return None


def _offset_words(delta: timedelta) -> str:
    mins = int(delta.total_seconds() // 60)
    sign = "+" if mins >= 0 else "-"
    h, m = divmod(abs(mins), 60)
    return f"UTC{sign}{h:02d}:{m:02d}"


def zone_card(zone, now: datetime | None = None) -> dict:
    """What the card says about a zone right now: its offset, summer or winter, the next change."""
    now = (now or datetime.now(timezone.utc)).astimezone(zone)
    dst = bool(now.dst())
    change = next_change(zone, now)
    out = {"zone": zone.key, "city": clock.place(zone), "offset": _offset_words(now.utcoffset()),
           "abbreviation": now.tzname() or "", "summer": dst,
           "time": now.strftime("%H:%M"), "change": None}
    if change is not None:
        when, to = change
        forward = to > now.utcoffset()
        out["change"] = {
            "at": when.isoformat(timespec="minutes"),
            "day": f"{when.strftime('%A')} {when.day} {when.strftime('%B %Y')}",
            "to": _offset_words(to),
            "words": "clocks go forward an hour" if forward else "clocks go back an hour"}
    return out


#: Where the second time zone is kept, in `user_settings`.
SECOND = "second_zone"


def second_zone(who):
    """The second time zone this person picked, or None.

    Petar, 30 September 2026 (fr_1da7cddc045b): "In the settings, where I have
    Location and Time Zone, add a secondary time zone that I can pick." It is
    a clock to read times on beside the one Rouh keeps, and nothing more: the
    morning brief's calendar shows each time on it too, so a meeting set from
    home reads in home's hours wherever the person is. It never becomes the
    clock Rouh keeps time by.
    """
    from .models import UserSetting

    if who is None or not getattr(who, "user_id", None):
        return None
    value = (UserSetting.objects
             .filter(user_id=str(who.user_id), org_id=who.org_id or "", name=SECOND)
             .values_list("value", flat=True).first())
    try:
        held_one = json.loads(value) if value else None
    except (TypeError, ValueError):
        return None
    return clock.zone_named((held_one or {}).get("zone")) if isinstance(held_one, dict) else None


def keep_second_zone(who, name) -> bool:
    """Keep this person's second time zone, or clear it with an empty name. False if not a zone."""
    from .models import UserSetting

    name = str(name or "").strip()
    zone = clock.zone_named(name) if name else None
    if name and zone is None:
        return False
    UserSetting.objects.bulk_create(
        [UserSetting(user_id=str(who.user_id), org_id=who.org_id or "", name=SECOND,
                     value=json.dumps({"zone": zone.key if zone else ""}),
                     updated_at=time.time())],
        update_conflicts=True, unique_fields=["user_id", "name"],
        update_fields=["org_id", "value", "updated_at"])
    return True


def card(who, device_zone: str = "") -> dict:
    """Everything the Location card draws: the kept location, the zone in use, the second one."""
    kept = get(who)
    device = clock.zone_named(device_zone)
    in_use = clock.zone_of(who)
    second = second_zone(who)
    out = {"location": None, "zone": zone_card(in_use), "zone_from": "device",
           "device_zone": device.key if device else "",
           "second_zone": zone_card(second) if second else None}
    if kept is not None:
        out["location"] = {k: kept.get(k) for k in ("lat", "lon", "accuracy", "place",
                                                    "source", "at")}
        out["zone_from"] = kept.get("zone_from") or "device"
    elif not clock.reported(who):
        out["zone_from"] = "default"
    return out


def prompt_line() -> str:
    """"The person is in Lisbon, Portugal, by their browser's location (2 hours ago)." or "".

    For whoever the turn is for (`tenancy.speaker`), and on an install with one
    person on it, that person, as `clock.zone` does.
    """
    try:
        from .tenancy import speaker

        who = speaker()
    except Exception:
        who = None
    kept = held(who) if who is not None else None
    if kept is None and who is None and len(_HELD) == 1:
        kept = next(iter(_HELD.values()))
    if not kept:
        return ""
    where = kept.get("place") or f"{kept.get('lat')}, {kept.get('lon')}"
    if kept.get("source") == "typed":
        return (f"The person is in {where}, as they typed it in Settings "
                f"{clock.ago(kept.get('at'))}.")
    source = "their phone's" if kept.get("source") == "phone" else "their browser's"
    return (f"The person is in {where}, by {source} location, "
            f"last reported {clock.ago(kept.get('at'))}.")


# --- asked for in a conversation ---------------------------------------------
#
# Petar, 29 September 2026 (fr_a3ff524b15c8): "For location, Rouh should
# request location from the browser so I can give it to it". So when where the
# person is matters to what they asked, the assistant draws a card in the chat
# (`tools._ask_for_location`) with Share my location at its foot, the ask block
# of `rouh/asking.py`. The press is what makes the browser ask its own question,
# never the page loading; the point it gives comes up with the press and is kept
# by `keep` exactly as the Settings card keeps it. The card then says what Rouh
# now knows, or that the browser would not say and why, and the conversation is
# told the same.

#: Why the browser gave nothing, as the page reports it, and how it is said.
FAILED = {
    "denied": ("Your browser is not letting Rouh see your location. To share it, allow "
               "location for this site in the browser's site settings."),
    "unavailable": ("Your device could not work out where it is. Without GPS it places "
                    "itself by the Wi-Fi networks around it, which it cannot do on a plane, "
                    "and an iPad without a SIM card has no GPS at all."),
    "timeout": ("Your device has not found where it is. Without GPS it places itself by "
                "the Wi-Fi networks around it, which it cannot do on a plane, and an iPad "
                "without a SIM card has no GPS at all."),
    "unsupported": "This browser cannot share a location.",
}

#: A location reported this recently (seconds) is where the person is now,
#: and is used rather than asked for again.
RECENT = 15 * 60


def recent(who, now: float | None = None) -> dict | None:
    """This person's kept location, if it was reported in the last `RECENT` seconds."""
    kept = get(who)
    now = time.time() if now is None else now
    if kept and now - float(kept.get("at") or 0) < RECENT:
        return kept
    return None


def said(kept: dict) -> str:
    """"Lisbon, Portugal (38.72230, -9.13930, to within about 30 m)"."""
    where = kept.get("place") or ""
    point = f"{kept.get('lat')}, {kept.get('lon')}"
    acc = kept.get("accuracy")
    if acc:
        point += ", to within about " + (f"{round(acc / 1000, 1)} km" if acc >= 1000
                                         else f"{round(acc)} m")
    return f"{where} ({point})" if where else point


def asking_card(why: str) -> dict:
    """The card that asks for the location, before its ask block is put on it."""
    why = " ".join(str(why or "").split())[:200].rstrip(".")
    text = ("Rouh would like to know where you are" + (f", {why[0].lower() + why[1:]}"
                                                        if why else "")
            + ". Your browser will ask you first, and you can say no.")
    return {"title": "Share your location?",
            "description": "Rouh asking for your location from this browser",
            "blocks": [{"block": "text", "text": text}]}


def shared_card(kept: dict) -> dict:
    """The asking card once the browser gave a point and it was kept."""
    source = "your phone" if kept.get("source") == "phone" else "this browser"
    return {"title": "Location shared: " + (kept.get("place") or "your position"),
            "description": "your location, shared with Rouh from this browser",
            "blocks": [{"block": "text", "text": (
                f"Shared from {source}: {said(kept)}. Rouh uses it in this conversation "
                "and keeps it in Settings under Location, where you can forget it.")}]}


def not_shared_card(words: str) -> dict:
    """The asking card once the browser would not, or could not, say."""
    return {"title": "Location not shared",
            "description": "your location, which the browser did not share with Rouh",
            "blocks": [{"block": "text", "text": words}]}


def declined(card: dict) -> dict:
    """The asking card whose Not now was pressed."""
    return not_shared_card("You chose not to share your location. The browser was not asked.")
