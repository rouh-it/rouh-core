"""A calendar link read: a calendar somebody published as a link (an .ics or webcal:// address),
read whole, on ‹his› clock, with its repeating events worked out.

Built by the nightly feature run, night 33 (second run), 5 November 2026 (task 94). People share
calendars as links more than any other way outside one company: a conference's programme, a
school's or a club's dates, a partner's "my availability" calendar, a supplier's delivery days, a
colleague at another company who publishes their busy times. Google Calendar's "Secret address in
iCal format" and Outlook's "Publish a calendar" both give one. Asked "what is on this calendar next
week?", Rouh could only fetch the address as a web page: a webcal:// address does not open at all,
and an .ics file is hundreds of lines of raw iCalendar in which a weekly meeting is one entry with a
rule (RRULE), taken out dates (EXDATE) and moved occurrences (RECURRENCE-ID) elsewhere in the file,
in the sender's time zone. A model reading that guesses, and guesses wrong.

So, while its switch is on, the tool `read_calendar_link` (asked for in words: "what is on this
calendar this week", "when is Dana busy on Thursday, here is her calendar", with the link):

- fetches the address once (webcal:// as https://), only from the public internet, at most
  `MOST_BYTES`, with no login, and reads it with `rouh/invites.py`, which already reads Outlook's
  Windows zone names and a file's own VTIMEZONE;
- works out every occurrence in the days asked (14 from today unless said, at most `MOST_DAYS`),
  repeats included, dates taken out left out, moved occurrences at their new time, cancelled ones
  gone;
- says them day by day on ‹his› clock, each with its time, title and place, or only the ones whose
  words match `words`, and the calendar's own name.

No model is asked. Nothing is kept: the address and what it said are read for the answer and gone.

**Whose.** Nobody's account: a public address the person gave.

**Its switch** is `calendar_link` (`rouh/switches.py`): off, the tool says so and reads nothing.
"""
from __future__ import annotations

import asyncio
import logging
import re
import socket
import urllib.parse
from datetime import date, datetime, time, timedelta, timezone

from . import invites

log = logging.getLogger("rouh.calendar_link")

SWITCH = "calendar_link"
TITLE = "A calendar link read: a published calendar (an .ics or webcal link) read on your clock, repeats included"
TOOL_NAME = "read_calendar_link"

#: The most a calendar is read, the most events taken out of it, the most days asked about, the
#: most occurrences said, and how long the fetch may take.
MOST_BYTES = 6_000_000
MOST_EVENTS = 5000
MOST_DAYS = 92
MOST_SAID = 80
TIMEOUT = 20
REDIRECTS = 3
USER_AGENT = "Rouh calendar reader (+https://rouh.it)"

DESCRIPTION = (
    "Reads a calendar somebody published or shared as a link - an .ics address, a webcal:// "
    "address, Google Calendar's 'secret address in iCal format', Outlook's published calendar, a "
    "conference's or a school's calendar feed - and says what is on it, day by day, on the "
    "person's own clock, with repeating events worked out (weekly meetings, dates taken out, "
    "moved occurrences). Use it whenever the person gives such a link and asks what is on it, when "
    "somebody is busy or free by it, or when something on it happens; web fetch cannot read these "
    "properly. Give days (from today, 14 unless said) or from and to, and words to keep only the "
    "events that mention them.")

SCHEMA = {
    "type": "object",
    "properties": {
        "url": {"type": "string",
                "description": "The calendar's link: https://..., http://... or webcal://..."},
        "days": {"type": "integer",
                 "description": "How many days from today (or from 'from') to read. 14 unless said."},
        "from": {"type": "string", "description": "The first day, as YYYY-MM-DD. Today unless said."},
        "to": {"type": "string", "description": "The last day, as YYYY-MM-DD, instead of days."},
        "words": {"type": "string",
                  "description": "Only the events whose title, place or description has these words."},
    },
    "required": ["url"],
}


class Refused(ValueError):
    """Why a link cannot be read, in a sentence."""


def on(who) -> bool:
    from . import switches

    if who is None:
        return False
    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


# --- Fetching ---------------------------------------------------------------------------------

def _address(url: str) -> str:
    """The address to fetch: webcal(s) as https, refused when it is no web address at all."""
    url = (url or "").strip().strip("<>").strip()
    parts = urllib.parse.urlsplit(url)
    scheme = parts.scheme.lower()
    if scheme in ("webcal", "webcals"):
        parts = parts._replace(scheme="https")
    elif scheme not in ("http", "https"):
        raise Refused("That is not a calendar's web address: give one that starts with https://, "
                      "http:// or webcal://.")
    if not parts.hostname:
        raise Refused("That address has no site in it.")
    if parts.username or parts.password:
        raise Refused("That address carries a login in it, and Rouh does not read those.")
    return urllib.parse.urlunsplit(parts)


async def _vetted(url: str, allow: set[str]) -> None:
    """Refused unless every address the site's name has is on the public internet (or the test
    world's own, `ROUH_BROWSER_ALLOW`)."""
    from .browsing import is_public

    parts = urllib.parse.urlsplit(url)
    host = (parts.hostname or "").lower().rstrip(".")
    port = parts.port or (443 if parts.scheme == "https" else 80)
    if f"{host}:{port}" in allow:
        return
    loop = asyncio.get_running_loop()
    try:
        found = await asyncio.wait_for(loop.getaddrinfo(host, port, type=socket.SOCK_STREAM), 10)
    except (OSError, asyncio.TimeoutError):
        if _behind_proxy() and not _is_ip(host) and host != "localhost":
            # In the containers names are looked up by the way out, the key proxy, which itself
            # refuses this machine and private networks (guard/rouh_guard/keyproxy.py).
            return
        raise Refused(f"{host} could not be found.") from None
    addresses = [info[4][0] for info in found]
    if not addresses or host == "localhost" or host.endswith(".localhost") \
            or not all(is_public(a) for a in addresses):
        raise Refused(f"{host} is not on the public internet, and Rouh reads calendars only from there.")


def _behind_proxy() -> bool:
    import os

    return bool(os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy"))


def _is_ip(host: str) -> bool:
    import ipaddress

    try:
        ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return False
    return True


def _allowed() -> set[str]:
    from .browsing import _allowed_list
    from .config import config

    return _allowed_list(getattr(config, "browser_allow", "") or "")


async def fetch(url: str, *, transport=None) -> str:
    """The calendar's text. Refused, with why, when it cannot be read. A webcal:// address is
    tried over https first and, when nothing answers there, over plain http, as calendar apps do."""
    said = (url or "").strip().strip("<>").strip()
    if urllib.parse.urlsplit(said).scheme.lower() == "webcal":
        try:
            return await _fetch(said, transport=transport)
        except Refused as exc:
            if not getattr(exc, "unreached", False):
                raise
            return await _fetch("http" + said[len("webcal"):], transport=transport)
    return await _fetch(said, transport=transport)


async def _fetch(url: str, *, transport=None) -> str:
    import httpx

    url = _address(url)
    allow = _allowed()
    async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False, transport=transport,
                                 headers={"User-Agent": USER_AGENT,
                                          "Accept": "text/calendar, text/plain;q=0.8, */*;q=0.5"}) as client:
        for _ in range(REDIRECTS + 1):
            await _vetted(url, allow)
            try:
                async with client.stream("GET", url) as got:
                    if got.status_code in (301, 302, 303, 307, 308) and got.headers.get("location"):
                        url = _address(urllib.parse.urljoin(url, got.headers["location"]))
                        continue
                    if got.status_code in (401, 403):
                        raise Refused("The site would not show that calendar without a login: it may "
                                      "be private, or the link may have been reset.")
                    if got.status_code == 404:
                        raise Refused("There is no calendar at that address any more.")
                    if got.status_code >= 400:
                        raise Refused(f"The site answered {got.status_code} and no calendar.")
                    body = bytearray()
                    async for chunk in got.aiter_bytes():
                        body += chunk
                        if len(body) > MOST_BYTES:
                            break
                    encoding = got.encoding or "utf-8"
            except httpx.HTTPError as exc:
                refused = Refused("The calendar's site did not answer, or would not let Rouh in "
                                  f"({type(exc).__name__}).")
                refused.unreached = isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout))
                raise refused from None
            text = bytes(body[:MOST_BYTES]).decode(encoding if encoding else "utf-8", errors="replace")
            if "BEGIN:VCALENDAR" not in text.upper():
                raise Refused("That address is a web page, not a calendar file: ask for its iCal "
                              "or .ics address (in Google Calendar, Settings, the calendar, "
                              "Integrate calendar; in Outlook, Publish a calendar, ICS).")
            return text
    raise Refused("That address sent Rouh on too many times.")


# --- Working out the occurrences --------------------------------------------------------------

def _as_moment(value, zone) -> datetime:
    """A start as a moment: a whole day starts at midnight on the person's clock."""
    if isinstance(value, datetime):
        return value
    return datetime.combine(value, time(0), tzinfo=zone)


def _same(a, b) -> bool:
    if isinstance(a, datetime) and isinstance(b, datetime):
        return a == b
    if isinstance(a, datetime) or isinstance(b, datetime):
        da = a.date() if isinstance(a, datetime) else a
        db = b.date() if isinstance(b, datetime) else b
        return da == db
    return a == b


def _starts(one: invites.Invite, begin: datetime, end: datetime, zone) -> list:
    """Every start of one event inside [begin, end), its repeats worked out, as its own kind
    (a date for a whole-day one)."""
    first = one.start
    if first is None:
        return []
    if not one.repeats:
        return [first]
    from dateutil.rrule import rrulestr

    whole = not isinstance(first, datetime)
    anchor = datetime.combine(first, time(0)) if whole else first
    rule_text = re.sub(r"^RRULE:", "", one.repeats.strip(), flags=re.I)
    rule, until = None, None
    for attempt in (rule_text, re.sub(r";?UNTIL=[^;]*", "", rule_text)):
        try:
            rule = rrulestr(attempt, dtstart=anchor)
            break
        except (ValueError, TypeError):
            # An UNTIL dateutil will not take beside this start (a bare date beside a time with a
            # zone): kept as the last day by hand instead.
            m = re.search(r"UNTIL=(\d{8})", rule_text)
            until = datetime.strptime(m.group(1), "%Y%m%d").date() if m else None
            continue
    if rule is None:
        return [first]
    lo, hi = (begin.replace(tzinfo=None), end.replace(tzinfo=None)) if whole else (begin, end)
    if not whole and anchor.tzinfo is None:
        lo, hi = lo.replace(tzinfo=None), hi.replace(tzinfo=None)
    # A start a little before the window can still be going on in it.
    lasting = (one.end - one.start) if isinstance(one.end, type(one.start)) and one.end else timedelta(0)
    out = []
    try:
        for at in rule.xafter(lo - lasting, count=MOST_SAID * 4, inc=True):
            if at >= hi or (until is not None and (at.date() if isinstance(at, datetime) else at) > until):
                break
            out.append(at.date() if whole else at)
    except (ValueError, TypeError, OverflowError):
        return [first]
    return [s for s in out if not any(_same(s, gone) for gone in one.exdates)]


def occurrences(events: list[invites.Invite], begin: datetime, end: datetime, zone,
                words: str = "") -> list[dict]:
    """Every occurrence of every event in [begin, end), on the person's clock, earliest first:
    [{start, end, all_day, title, where, call, floating}]."""
    moved: dict[str, list] = {}
    for one in events:
        if one.recurrence_id and one.uid and one.recurrence_at is not None:
            moved.setdefault(one.uid, []).append(one.recurrence_at)
    wanted = [w for w in re.findall(r"\w+", (words or "").lower()) if len(w) > 1]
    out = []
    for one in events:
        if one.cancelled or one.start is None:
            continue
        if wanted:
            hay = f"{one.title} {one.where} {one.description}".lower()
            if not all(w in hay for w in wanted):
                continue
        lasting = (one.end - one.start) if one.end is not None and type(one.end) is type(one.start) \
            else (timedelta(days=1) if not isinstance(one.start, datetime) else timedelta(0))
        replaced = moved.get(one.uid, []) if not one.recurrence_id else []
        for start in _starts(one, begin, end, zone):
            if replaced and any(_same(start, r) for r in replaced):
                continue  # this occurrence is in the file again, at its new time
            a = _as_moment(start, zone)
            b = _as_moment(start + lasting, zone) if lasting else a
            if b <= begin and a < begin or a >= end:
                continue
            out.append({"start": a, "end": b, "all_day": not isinstance(start, datetime),
                        "title": one.title or "(no title)", "where": one.where or "",
                        "call": one.call or "", "floating": one.floating})
    out.sort(key=lambda o: (o["start"], o["title"]))
    return out


def _name(text: str) -> str:
    m = re.search(r"^X-WR-CALNAME[^:\r\n]*:(.+)$", text[:20000], re.M | re.I)
    return invites._text(m.group(1).strip())[:120] if m else ""


def _day(value: str, zone) -> date | None:
    try:
        return datetime.strptime((value or "").strip()[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def window(args: dict, zone, now: datetime) -> tuple[datetime, datetime]:
    first = _day(str(args.get("from") or ""), zone) or now.astimezone(zone).date()
    last = _day(str(args.get("to") or ""), zone)
    if last is None:
        try:
            days = int(args.get("days") or 14)
        except (TypeError, ValueError):
            days = 14
        last = first + timedelta(days=max(1, min(days, MOST_DAYS)) - 1)
    if last < first:
        first, last = last, first
    last = min(last, first + timedelta(days=MOST_DAYS - 1))
    begin = datetime.combine(first, time(0), tzinfo=zone)
    if first == now.astimezone(zone).date():
        begin = max(begin, now.astimezone(zone) - timedelta(hours=1))
    return begin, datetime.combine(last + timedelta(days=1), time(0), tzinfo=zone)


def said(found: list[dict], begin: datetime, end: datetime, zone, name: str, words: str) -> str:
    span = (f"{begin:%A %-d %B} to {(end - timedelta(seconds=1)):%A %-d %B %Y}")
    head = f"The calendar {name!r}" if name else "The calendar at that link"
    keep = f", the events that mention {words!r}" if words else ""
    if not found:
        return f"{head} has nothing from {span}{keep}."
    lines = [f"{head}, from {span}{keep}, on the person's clock ({zone.key}): "
             f"{len(found)} event{'s' if len(found) != 1 else ''}."]
    shown = found[:MOST_SAID]
    day = None
    for o in shown:
        a, b = o["start"].astimezone(zone), o["end"].astimezone(zone)
        if a.date() != day:
            day = a.date()
            lines.append(f"{a:%A %-d %B}:")
        if o["all_day"]:
            when = "all day" if (b - a) <= timedelta(days=1) else f"all day, to {(b - timedelta(days=1)):%A %-d %B}"
        else:
            when = f"{a:%H:%M}-{b:%H:%M}" if b > a else f"{a:%H:%M}"
            if b.date() != a.date():
                when += f" ({b:%A})"
        extra = []
        if o["where"]:
            extra.append(o["where"][:120])
        if o["call"] and o["call"] not in o["where"]:
            extra.append(o["call"])
        if o["floating"]:
            extra.append("no time zone in the file, so taken as the person's")
        lines.append(f"- {when}: {o['title'][:160]}" + (f" ({'; '.join(extra)})" if extra else ""))
    if len(found) > len(shown):
        lines.append(f"And {len(found) - len(shown)} more; ask for fewer days or with words to see them.")
    return "\n".join(lines)


async def answer(args: dict, zone, *, now: datetime | None = None, transport=None) -> tuple[str, dict]:
    """(what to say, {read, events}) for one call of the tool."""
    url = str(args.get("url") or "").strip()
    if not url:
        return "Give the calendar's link.", {"read": False}
    now = now or datetime.now(timezone.utc)
    try:
        text = await fetch(url, transport=transport)
    except Refused as exc:
        return str(exc), {"read": False}
    events = invites.parse(text, zone, most=MOST_EVENTS, most_bytes=MOST_BYTES)
    if not events:
        return "That calendar has no events in it.", {"read": True, "events": 0}
    begin, end = window(args or {}, zone, now)
    words = str(args.get("words") or "").strip()
    found = occurrences(events, begin, end, zone, words)
    return said(found, begin, end, zone, _name(text), words), {"read": True, "events": len(found)}


__all__ = ["DESCRIPTION", "MOST_DAYS", "Refused", "SCHEMA", "SWITCH", "TITLE", "TOOL_NAME",
           "answer", "fetch", "occurrences", "on", "window"]
