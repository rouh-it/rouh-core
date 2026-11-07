"""Times as the person reads them: their own clock, with its offset written
on it, and ages already worked out.

The server keeps Berlin time, the person lived in Athens an hour ahead of it,
and the job records are written in UTC. Handing the model all three and leaving
it to subtract is how a job three minutes old was called "about two hours" old:
the prompt said 10:28 "in Athens", which was Berlin's clock, the job said 08:25,
which was UTC, and the model took the difference.

So every time the model is given goes through here: a clock time where the
person is, with its offset, and an age computed from the real clock at the
moment of asking.

**Where the person is.** Until 27 September 2026 that was one city, written into
this file. Petar, that day, on the Reminders page: "consider where I am and the
timezone ... decide what time it is right now where I am, which is different
than server". So it is the person's own time zone now, the one their browser
is on, which a phone or a laptop sets from where it is. Every page sends it
when its socket opens (`hello`, `tz`) and with every reminder it saves, and it
is kept as a setting of that person's own (`UserSetting`, name `zone`), so a
reminder due at three in the night is said on their clock and not the
server's. It needs no permission.

**Where the person says they are.** Petar, 30 September 2026: "location should
give you timezone". Once the person shares a location (the Location card at
the top of Settings, `rouh/location.py`), the zone at that point is theirs
(`locate`), above the one their device reports, until they forget it. Either
way it is a zone's name and never an offset, so summer and winter time follow
by themselves.

`zone()` is the one answer to "whose clock", read for whoever the turn or the
request is for (`tenancy.speaker`, or `person(who)` around a request). With
nobody known it is the one person there is, and with nobody at all, the
installation's own default (`ROUH_DEFAULT_ZONE`, UTC unless it says).
"""
from __future__ import annotations

import contextlib
import contextvars
import json
import logging
import threading
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

log = logging.getLogger("rouh.clock")

def _default() -> ZoneInfo:
    """Where a person is when nothing has said otherwise: the installation's own
    setting (`ROUH_DEFAULT_ZONE`, SETUP.md), UTC when it names none or names
    something that is not a zone. Never a place written here: it was the first
    owner's own city, until 20 October 2026."""
    from .config import config

    try:
        return ZoneInfo(str(config.default_zone or "UTC").strip() or "UTC")
    except (ZoneInfoNotFoundError, ValueError, OSError):
        log.warning("ROUH_DEFAULT_ZONE %r is not a time zone; UTC instead", config.default_zone)
        return ZoneInfo("UTC")


#: Where the person is when nothing has said otherwise.
DEFAULT = _default()

#: The name a person's time zone is kept under, in `user_settings`.
SETTING = "zone"

#: Each person's time zone, by user id: read from the database once when Rouh
#: starts (`load`) and written through whenever a page says it changed
#: (`remember`), so asking for the time never waits on a query.
_ZONES: dict[str, ZoneInfo] = {}
_LOCK = threading.Lock()

#: The zone at each person's shared location, by user id (`rouh/location.py`),
#: which outranks the one their device reports.
_LOCATED: dict[str, ZoneInfo] = {}

#: Set around a request or a job that knows whose clock it is on (`person`).
_HERE: contextvars.ContextVar[ZoneInfo | None] = contextvars.ContextVar(
    "rouh_zone", default=None)


def zone_named(name) -> ZoneInfo | None:
    """The time zone a browser named ("Europe/Lisbon"), or None if it is not one."""
    text = str(name or "").strip()
    if not text or len(text) > 64 or ".." in text or text.startswith("/"):
        return None
    try:
        return ZoneInfo(text)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return None


def zone_of(who) -> ZoneInfo:
    """This person's time zone, as last reported by one of their pages."""
    user = getattr(who, "user_id", None)
    if not user:
        return DEFAULT
    user = str(user)
    return _LOCATED.get(user) or _ZONES.get(user, DEFAULT)


def reported(who) -> bool:
    """Whether a page of this person's has ever said what zone it is on."""
    return str(getattr(who, "user_id", "") or "") in _ZONES


def locate(who, name) -> ZoneInfo | None:
    """The zone at this person's shared location is their clock; None puts the device's back."""
    user = str(getattr(who, "user_id", "") or "")
    if not user:
        return None
    z = zone_named(name) if name else None
    with _LOCK:
        if z is None:
            _LOCATED.pop(user, None)
        else:
            _LOCATED[user] = z
    return z


def located(zones: dict) -> None:
    """Every person's location zone at once, as `location.load` reads them."""
    found = {str(user): z for user, name in zones.items() if (z := zone_named(name))}
    with _LOCK:
        _LOCATED.update(found)


def zone() -> ZoneInfo:
    """The clock of whoever this is for."""
    here = _HERE.get()
    if here is not None:
        return here
    try:
        from .tenancy import speaker

        who = speaker()
    except Exception:
        who = None
    if who is not None:
        return zone_of(who)
    # A job or a loop with nobody named: on an install with one person on it,
    # that person's clock, as `Tenancy.only_person` answers whose it is.
    people = set(_ZONES) | set(_LOCATED)
    if len(people) == 1:
        only = next(iter(people))
        return _LOCATED.get(only) or _ZONES[only]
    return DEFAULT


def place(z: ZoneInfo | None = None) -> str:
    """Where a time zone is, as a person says it: "Sofia", "New York"."""
    key = str(getattr(z or zone(), "key", "") or "")
    city = key.rsplit("/", 1)[-1].replace("_", " ")
    return city or "UTC"


@contextlib.contextmanager
def person(who, zone: ZoneInfo | None = None):
    """Everything inside is on this person's clock, threads it starts too.

    A request that brought its page's time zone keeps it first (`remember`,
    on a thread, because it may write), so the page and the row it saves agree.
    `zone`, when given, is the clock of the very page asking, which wins over
    whichever of the person's devices spoke last.
    """
    token = _HERE.set(zone or zone_of(who))
    try:
        yield
    finally:
        _HERE.reset(token)


def remember(who, name) -> ZoneInfo | None:
    """Keep the time zone a page of this person's is on. None if it is not one.

    Written only when it changed, so a page opening costs no write. A database
    that cannot be written to still leaves it known until Rouh restarts.
    """
    z = zone_named(name)
    user = getattr(who, "user_id", None)
    if z is None or not user:
        return None
    user = str(user)
    with _LOCK:
        if _ZONES.get(user) == z:
            return z
        _ZONES[user] = z
    try:
        from .models import UserSetting

        UserSetting.objects.bulk_create(
            [UserSetting(user_id=user, org_id=getattr(who, "org_id", "") or "",
                         name=SETTING, value=json.dumps({"zone": z.key}),
                         updated_at=time.time())],
            update_conflicts=True, unique_fields=["user_id", "name"],
            update_fields=["org_id", "value", "updated_at"])
        log.info("user %s is on %s time now", user, z.key)
    except Exception:
        log.exception("could not keep the time zone of user %s", user)
    return z


def load() -> int:
    """Read everybody's time zone from the database. How many there were."""
    from .models import UserSetting

    found: dict[str, ZoneInfo] = {}
    for user, value in UserSetting.objects.filter(name=SETTING).values_list("user_id", "value"):
        try:
            z = zone_named(json.loads(value).get("zone"))
        except (TypeError, ValueError, AttributeError):
            z = None
        if z is not None:
            found[str(user)] = z
    with _LOCK:
        _ZONES.update(found)
    return len(found)


def now() -> datetime:
    return datetime.now(zone())


# --- UTC, the way records are written --------------------------------------------------------------


def utcnow() -> datetime:
    """Now, in UTC, with the zone on it."""
    return datetime.now(timezone.utc)


def utc_iso(ts=None, timespec: str = "auto") -> str:
    """'2026-09-12T08:25:03+00:00': seconds since 1970 (now, when None) as an ISO string in UTC."""
    dt = utcnow() if ts is None else datetime.fromtimestamp(ts, timezone.utc)
    return dt.isoformat(timespec=timespec)


def parse_utc(value, zulu: bool = True) -> datetime | None:
    """An ISO string (or anything whose text is one) as a time with its zone on it.

    A time written with no zone is UTC. Nothing, or something unreadable, gives
    None. `zulu` reads a 'Z' anywhere in the text as '+00:00' first, as most
    readers here always have; Python reads a trailing 'Z' by itself, but not
    after a date alone ('2026-10-19Z').
    """
    if not value:
        return None
    text = str(value)
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00") if zulu else text)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def epoch(value, zulu: bool = True) -> float | None:
    """An ISO string as seconds since 1970, by `parse_utc`'s rules. None if unreadable."""
    dt = parse_utc(value, zulu)
    return dt.timestamp() if dt else None


def moment(value) -> datetime | None:
    """A time on the person's clock, from seconds since 1970, an ISO string or a datetime.

    A time written with no zone is UTC, because that is how every record here is
    written. Nothing, or something unreadable, gives None.
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, (int, float)):
        dt = datetime.fromtimestamp(float(value), timezone.utc)
    else:
        try:
            dt = datetime.fromisoformat(str(value))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(zone())


def stamp(value) -> str:
    """'2026-09-12T11:25:03+03:00': the person's time, with the offset on it."""
    dt = moment(value)
    return dt.isoformat(timespec="seconds") if dt else ""


def clock(value) -> str:
    """'11:25', on the person's clock."""
    dt = moment(value)
    return dt.strftime("%H:%M") if dt else ""


def offset(value=None) -> str:
    """'+03:00': the person's distance from UTC at that moment, summer or winter."""
    dt = moment(value) if value is not None else now()
    raw = dt.strftime("%z")
    return f"{raw[:3]}:{raw[3:]}"


def ago(value, at=None) -> str:
    """How long ago, in words: 'just now', '40 seconds ago', '3 minutes ago'."""
    then = moment(value)
    if then is None:
        return ""
    ref = moment(at) if at is not None else now()
    secs = int((ref - then).total_seconds())
    if secs < 10:
        return "just now"                   # a clock slightly ahead lands here too
    if secs < 60:
        return f"{secs} seconds ago"
    mins = secs // 60
    if mins < 60:
        return f"{mins} minute{'s' if mins != 1 else ''} ago"
    hours, mins = divmod(mins, 60)
    if hours < 24:
        text = f"{hours} hour{'s' if hours != 1 else ''}"
        if mins:
            text += f" {mins} minute{'s' if mins != 1 else ''}"
        return text + " ago"
    days = hours // 24
    return f"{days} day{'s' if days != 1 else ''} ago"
