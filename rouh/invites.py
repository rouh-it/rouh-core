"""Calendar invitations as they travel in email: the iCalendar file, read into plain facts.

The part shared by two genes of the nightly feature run, night 33, 4 November 2026 (task 94):
Invitations read on your clock (`rouh/mail_invites.py`) and Invitations not in your calendar
(`rouh/invite_missing.py`). It asks no model and reaches nothing: it only reads.

An invitation sent by email is a `text/calendar` part (RFC 5545, the iCalendar format, carried by
RFC 6047, iMIP), most often with no file name, beside the words the sender's program wrote. Google's
own invitations put the time in those words; Outlook's and Teams' often do not, or say it in the
sender's own time zone ("Pacific Standard Time"), and the zone is written in the calendar part only
by a Windows name and a VTIMEZONE block. So the time on the person's own clock is only known by
reading the calendar part, which nothing in Rouh read before: `gmail._message_bodies` keeps the
plain and the HTML parts and drops it.

`parse(text)` turns one calendar file into `Invite`s: what kind it is (an invitation, a change, a
cancellation, an answer), its title, its start and end as aware datetimes, where, the call link,
who sent it, who is invited and how they answered, whether it repeats, and its UID and SEQUENCE,
which is what a calendar knows it by.

Time zones are read three ways, in this order: an IANA name (`Europe/Sofia`), a Windows name from
`WINDOWS` (`FLE Standard Time`), and otherwise the file's own VTIMEZONE, worked out for the year of
the event from its STANDARD and DAYLIGHT rules. A time with no zone at all is floating, which the
person's own clock is taken for, and said so.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

#: The most a file is read, and the most events taken out of one.
MOST_BYTES = 400_000
MOST_EVENTS = 6

#: Windows' names for the zones people send invitations from, as Outlook and Exchange write them
#: in TZID, mapped the way Unicode's CLDR maps them (windowsZones.xml, territory 001).
WINDOWS = {
    "Dateline Standard Time": "Etc/GMT+12", "UTC-11": "Etc/GMT+11",
    "Hawaiian Standard Time": "Pacific/Honolulu", "Alaskan Standard Time": "America/Anchorage",
    "Pacific Standard Time": "America/Los_Angeles", "US Mountain Standard Time": "America/Phoenix",
    "Mountain Standard Time": "America/Denver", "Central Standard Time": "America/Chicago",
    "Central America Standard Time": "America/Guatemala",
    "Central Standard Time (Mexico)": "America/Mexico_City",
    "Eastern Standard Time": "America/New_York", "US Eastern Standard Time": "America/Indianapolis",
    "SA Pacific Standard Time": "America/Bogota", "Atlantic Standard Time": "America/Halifax",
    "Canada Central Standard Time": "America/Regina", "Venezuela Standard Time": "America/Caracas",
    "SA Western Standard Time": "America/La_Paz", "Pacific SA Standard Time": "America/Santiago",
    "Newfoundland Standard Time": "America/St_Johns", "E. South America Standard Time": "America/Sao_Paulo",
    "Argentina Standard Time": "America/Buenos_Aires", "SA Eastern Standard Time": "America/Cayenne",
    "Greenland Standard Time": "America/Godthab", "UTC-02": "Etc/GMT+2",
    "Azores Standard Time": "Atlantic/Azores", "Cape Verde Standard Time": "Atlantic/Cape_Verde",
    "UTC": "Etc/UTC", "Coordinated Universal Time": "Etc/UTC",
    "GMT Standard Time": "Europe/London", "Greenwich Standard Time": "Atlantic/Reykjavik",
    "Morocco Standard Time": "Africa/Casablanca",
    "W. Europe Standard Time": "Europe/Berlin", "Central Europe Standard Time": "Europe/Budapest",
    "Romance Standard Time": "Europe/Paris", "Central European Standard Time": "Europe/Warsaw",
    "W. Central Africa Standard Time": "Africa/Lagos",
    "GTB Standard Time": "Europe/Bucharest", "FLE Standard Time": "Europe/Kiev",
    "E. Europe Standard Time": "Europe/Chisinau", "Middle East Standard Time": "Asia/Beirut",
    "Egypt Standard Time": "Africa/Cairo", "South Africa Standard Time": "Africa/Johannesburg",
    "Israel Standard Time": "Asia/Jerusalem", "Turkey Standard Time": "Europe/Istanbul",
    "Jordan Standard Time": "Asia/Amman", "Kaliningrad Standard Time": "Europe/Kaliningrad",
    "Arabic Standard Time": "Asia/Baghdad", "Arab Standard Time": "Asia/Riyadh",
    "Belarus Standard Time": "Europe/Minsk", "Russian Standard Time": "Europe/Moscow",
    "E. Africa Standard Time": "Africa/Nairobi", "Iran Standard Time": "Asia/Tehran",
    "Arabian Standard Time": "Asia/Dubai", "Azerbaijan Standard Time": "Asia/Baku",
    "Georgian Standard Time": "Asia/Tbilisi", "Caucasus Standard Time": "Asia/Yerevan",
    "Afghanistan Standard Time": "Asia/Kabul", "West Asia Standard Time": "Asia/Tashkent",
    "Pakistan Standard Time": "Asia/Karachi", "India Standard Time": "Asia/Calcutta",
    "Sri Lanka Standard Time": "Asia/Colombo", "Nepal Standard Time": "Asia/Katmandu",
    "Central Asia Standard Time": "Asia/Almaty", "Bangladesh Standard Time": "Asia/Dhaka",
    "Myanmar Standard Time": "Asia/Rangoon", "SE Asia Standard Time": "Asia/Bangkok",
    "China Standard Time": "Asia/Shanghai", "Singapore Standard Time": "Asia/Singapore",
    "Taipei Standard Time": "Asia/Taipei", "W. Australia Standard Time": "Australia/Perth",
    "Tokyo Standard Time": "Asia/Tokyo", "Korea Standard Time": "Asia/Seoul",
    "Cen. Australia Standard Time": "Australia/Adelaide", "AUS Central Standard Time": "Australia/Darwin",
    "E. Australia Standard Time": "Australia/Brisbane", "AUS Eastern Standard Time": "Australia/Sydney",
    "Tasmania Standard Time": "Australia/Hobart", "New Zealand Standard Time": "Pacific/Auckland",
    "Fiji Standard Time": "Pacific/Fiji", "Tonga Standard Time": "Pacific/Tongatapu",
}

#: What a METHOD says the email is, in words.
METHODS = {
    "REQUEST": "an invitation",
    "CANCEL": "a cancellation",
    "REPLY": "an answer to an invitation",
    "PUBLISH": "a calendar entry to add",
    "COUNTER": "a proposal of another time",
    "DECLINECOUNTER": "a refusal of a proposed time",
    "REFRESH": "a request for the latest version",
    "ADD": "more dates for an invitation",
}

#: How a guest answered, in words.
ANSWERS = {"ACCEPTED": "accepted", "DECLINED": "declined", "TENTATIVE": "said maybe",
           "NEEDS-ACTION": "has not answered", "DELEGATED": "passed it on"}

#: Where a call link is kept, by Teams, Zoom, Webex and Google, beside LOCATION and URL.
_CALL_PROPS = ("X-MICROSOFT-SKYPETEAMSMEETINGURL", "X-MICROSOFT-ONLINEMEETINGCONFLINK",
               "X-GOOGLE-CONFERENCE", "X-ZOOM-MEETING-URL", "CONFERENCE")
_CALL = re.compile(r"https://(?:[\w.-]*\.)?(?:teams\.microsoft\.com|teams\.live\.com|zoom\.us|"
                   r"meet\.google\.com|webex\.com|whereby\.com|gotomeeting\.com|"
                   r"meet\.jit\.si|chime\.aws)/[^\s<>\"'\\)]+", re.I)
_DAYS = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}


@dataclass
class Guest:
    email: str
    name: str = ""
    answer: str = ""
    role: str = ""


@dataclass
class Invite:
    method: str = ""
    uid: str = ""
    sequence: int = 0
    title: str = ""
    start: datetime | date | None = None
    end: datetime | date | None = None
    all_day: bool = False
    floating: bool = False
    zone_said: str = ""
    where: str = ""
    call: str = ""
    organiser: Guest | None = None
    guests: list[Guest] = field(default_factory=list)
    repeats: str = ""
    status: str = ""
    recurrence_id: str = ""
    description: str = ""
    #: The occurrences of a repeating event taken out of it (EXDATE), and the moment of the one
    #: occurrence this event replaces (RECURRENCE-ID): read for a whole calendar
    #: (A calendar link read, `rouh/calendar_link.py`).
    exdates: list = field(default_factory=list)
    recurrence_at: datetime | date | None = None

    @property
    def cancelled(self) -> bool:
        return self.method == "CANCEL" or self.status == "CANCELLED"

    @property
    def kind(self) -> str:
        if self.method == "REQUEST" and self.sequence > 0:
            return "a changed invitation"
        if self.status == "CANCELLED" and self.method != "CANCEL":
            return "a cancellation"
        return METHODS.get(self.method, "a calendar entry")


# --- Reading the file -------------------------------------------------------------------------

def _unfold(text: str) -> list[str]:
    """The file's logical lines: a line that starts with a space or a tab continues the last."""
    out: list[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and out:
            out[-1] += raw[1:]
        elif raw.strip():
            out.append(raw)
    return out


def _split(line: str) -> tuple[str, dict[str, str], str]:
    """NAME;PARAM=V;PARAM="V":value, with quoted values kept whole."""
    head, value, quoted, i = "", "", False, 0
    for i, ch in enumerate(line):
        if ch == '"':
            quoted = not quoted
        elif ch == ":" and not quoted:
            head, value = line[:i], line[i + 1:]
            break
    else:
        return line.upper(), {}, ""
    bits, cur, quoted = [], "", False
    for ch in head:
        if ch == '"':
            quoted = not quoted
            continue
        if ch == ";" and not quoted:
            bits.append(cur)
            cur = ""
        else:
            cur += ch
    bits.append(cur)
    params = {}
    for one in bits[1:]:
        k, _, v = one.partition("=")
        params[k.strip().upper()] = v.strip()
    return bits[0].strip().upper(), params, value


def _text(value: str) -> str:
    return (value.replace("\\n", "\n").replace("\\N", "\n").replace("\\,", ",")
            .replace("\\;", ";").replace("\\\\", "\\")).strip()


def _blocks(lines: list[str]) -> list[tuple[str, list]]:
    """Nested BEGIN/END blocks, as (name, [(name, params, value) or block])."""
    root: list = []
    stack: list[tuple[str, list]] = [("", root)]
    for line in lines:
        name, params, value = _split(line)
        if name == "BEGIN":
            block = (value.strip().upper(), [])
            stack[-1][1].append(block)
            stack.append(block)
        elif name == "END":
            if len(stack) > 1:
                stack.pop()
        else:
            stack[-1][1].append((name, params, value))
    return root


def _props(block) -> list[tuple[str, dict, str]]:
    return [one for one in block[1] if len(one) == 3]


def _children(block, name: str) -> list:
    return [one for one in block[1] if len(one) == 2 and one[0] == name]


def _first(block, name: str):
    return next(((n, p, v) for n, p, v in _props(block) if n == name), None)


# --- Time zones -------------------------------------------------------------------------------

def _offset(value: str) -> timedelta:
    m = re.fullmatch(r"([+-])(\d{2})(\d{2})(\d{2})?", value.strip())
    if not m:
        return timedelta(0)
    sign = -1 if m.group(1) == "-" else 1
    return sign * timedelta(hours=int(m.group(2)), minutes=int(m.group(3)), seconds=int(m.group(4) or 0))


def _naive(value: str) -> datetime | None:
    value = value.strip().rstrip("Z")
    for fmt in ("%Y%m%dT%H%M%S", "%Y%m%dT%H%M"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def _rule_day(year: int, rule: str, at: datetime) -> datetime | None:
    """The day a yearly RRULE (BYMONTH and BYDAY, such as -1SU or 2SU) falls on in `year`."""
    parts = dict(one.split("=", 1) for one in rule.split(";") if "=" in one)
    try:
        month = int(parts.get("BYMONTH") or at.month)
    except ValueError:
        return None
    m = re.fullmatch(r"([+-]?\d)?(MO|TU|WE|TH|FR|SA|SU)", (parts.get("BYDAY") or "").strip())
    if not m:
        return at.replace(year=year)
    nth, weekday = int(m.group(1) or 1), _DAYS[m.group(2)]
    if nth > 0:
        first = date(year, month, 1)
        day = first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (nth - 1))
    else:
        last = (date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1))
        day = last - timedelta(days=(last.weekday() - weekday) % 7 + 7 * (-nth - 1))
    return datetime(day.year, day.month, day.day, at.hour, at.minute, at.second)


def _own_zone(block) -> "callable | None":
    """A VTIMEZONE's offset for a local time, from its STANDARD and DAYLIGHT parts."""
    parts = []
    for name in ("STANDARD", "DAYLIGHT"):
        for one in _children(block, name):
            start = _first(one, "DTSTART")
            to = _first(one, "TZOFFSETTO")
            if not to:
                continue
            rule = _first(one, "RRULE")
            parts.append((name, _naive(start[2]) if start else None, _offset(to[2]),
                          rule[2] if rule else ""))
    if not parts:
        return None

    def offset_at(local: datetime) -> timedelta:
        changes = []
        for _name, start, off, rule in parts:
            if start is None:
                changes.append((datetime.min, off))
                continue
            if rule:
                for year in (local.year - 1, local.year):
                    when = _rule_day(year, rule, start)
                    if when is not None and when >= start:
                        changes.append((when, off))
            changes.append((start, off))
        before = [c for c in changes if c[0] <= local]
        if before:
            return max(before, key=lambda c: c[0])[1]
        return min(changes, key=lambda c: c[0])[1]

    return offset_at


def _zone_named(name: str):
    name = name.strip().strip('"')
    if not name:
        return None
    # An IANA name, a Windows name, or an IANA name at the end of a path, as Thunderbird writes
    # "/mozilla.org/20050126_1/Europe/Sofia".
    tail = "/".join(name.strip("/").split("/")[-2:]) if "/" in name else ""
    for one in (name, WINDOWS.get(name, ""), tail):
        if not one:
            continue
        try:
            return ZoneInfo(one)
        except (ZoneInfoNotFoundError, ValueError):
            continue
    return None


def _moment(prop, zones: dict, fallback) -> tuple[datetime | date | None, bool, bool, str]:
    """(value, all day, floating, the zone's name as sent) for DTSTART or DTEND."""
    if prop is None:
        return None, False, False, ""
    _name, params, value = prop
    value = value.strip()
    if params.get("VALUE", "").upper() == "DATE" or re.fullmatch(r"\d{8}", value):
        try:
            return datetime.strptime(value[:8], "%Y%m%d").date(), True, False, ""
        except ValueError:
            return None, False, False, ""
    local = _naive(value)
    if local is None:
        return None, False, False, ""
    if value.endswith("Z"):
        return local.replace(tzinfo=timezone.utc), False, False, "UTC"
    tzid = params.get("TZID", "")
    if tzid:
        zone = _zone_named(tzid)
        if zone is not None:
            return local.replace(tzinfo=zone), False, False, tzid
        own = zones.get(tzid)
        if own is not None:
            return local.replace(tzinfo=timezone(own(local))), False, False, tzid
    return local.replace(tzinfo=fallback), False, True, tzid


def _duration(value: str) -> timedelta | None:
    m = re.fullmatch(r"([+-])?P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?",
                     value.strip())
    if not m:
        return None
    weeks, days, hours, minutes, seconds = (int(g or 0) for g in m.groups()[1:])
    return timedelta(weeks=weeks, days=days, hours=hours, minutes=minutes, seconds=seconds)


def _person(params: dict, value: str) -> Guest:
    email = re.sub(r"^mailto:", "", value.strip(), flags=re.I).strip()
    return Guest(email=email, name=_text(params.get("CN", "")).strip('"'),
                 answer=params.get("PARTSTAT", "").upper(), role=params.get("ROLE", "").upper())


def parse(text: str, fallback=timezone.utc, *, most: int = MOST_EVENTS,
          most_bytes: int = MOST_BYTES) -> list[Invite]:
    """Every event of one calendar file, as `Invite`s; [] when it is not one. An invitation
    holds a few; a whole published calendar is read with a larger `most` and `most_bytes`."""
    if not text or "BEGIN:VCALENDAR" not in text.upper():
        return []
    lines = _unfold(text[:most_bytes])
    roots = [b for b in _blocks(lines) if b[0] == "VCALENDAR"]
    out: list[Invite] = []
    for cal in roots:
        method = (_first(cal, "METHOD") or ("", {}, ""))[2].strip().upper()
        zones = {}
        for tz in _children(cal, "VTIMEZONE"):
            tzid = _first(tz, "TZID")
            own = _own_zone(tz)
            if tzid and own:
                zones[tzid[2].strip()] = own
        for ev in _children(cal, "VEVENT")[:most]:
            one = Invite(method=method)
            for name, params, value in _props(ev):
                if name == "UID":
                    one.uid = value.strip()
                elif name == "SEQUENCE":
                    one.sequence = int(value) if value.strip().isdigit() else 0
                elif name == "SUMMARY":
                    one.title = _text(value)
                elif name == "LOCATION":
                    one.where = _text(value)
                elif name == "STATUS":
                    one.status = value.strip().upper()
                elif name == "RRULE":
                    one.repeats = value.strip()
                elif name == "RECURRENCE-ID":
                    one.recurrence_id = value.strip()
                    one.recurrence_at = _moment((name, params, value), zones, fallback)[0]
                elif name == "EXDATE":
                    for part in value.split(","):
                        gone = _moment((name, params, part), zones, fallback)[0]
                        if gone is not None:
                            one.exdates.append(gone)
                elif name == "DESCRIPTION":
                    one.description = _text(value)
                elif name == "ORGANIZER":
                    one.organiser = _person(params, value)
                elif name == "ATTENDEE":
                    one.guests.append(_person(params, value))
                elif name in _CALL_PROPS or name == "URL":
                    m = _CALL.search(value)
                    if m and not one.call:
                        one.call = m.group(0)
            one.start, one.all_day, one.floating, one.zone_said = _moment(
                _first(ev, "DTSTART"), zones, fallback)
            end = _moment(_first(ev, "DTEND"), zones, fallback)[0]
            if end is None and one.start is not None:
                lasts = _duration((_first(ev, "DURATION") or ("", {}, ""))[2])
                if lasts is not None:
                    end = one.start + lasts
                elif one.all_day:
                    end = one.start + timedelta(days=1)
            one.end = end
            if not one.call:
                for words in (one.where, one.description):
                    m = _CALL.search(words or "")
                    if m:
                        one.call = m.group(0)
                        break
            out.append(one)
    return out


# --- Saying it --------------------------------------------------------------------------------

def _clock(value: datetime, zone) -> str:
    local = value.astimezone(zone)
    return local.strftime("%A %-d %B %Y, %H:%M")


def when_words(one: Invite, zone) -> str:
    """When it is, on the person's own clock, with the sender's own time beside it when it differs."""
    if one.start is None:
        return "with no time in it"
    if one.all_day:
        start = one.start
        last = (one.end - timedelta(days=1)) if isinstance(one.end, date) and one.end > start else start
        if last == start:
            return f"all day on {start:%A %-d %B %Y}"
        return f"all day from {start:%A %-d %B} to {last:%A %-d %B %Y}"
    said = _clock(one.start, zone)
    if isinstance(one.end, datetime):
        end = one.end.astimezone(zone)
        said += f" to {end:%H:%M}" if end.date() == one.start.astimezone(zone).date() \
            else f" to {_clock(one.end, zone)}"
        minutes = int((one.end - one.start).total_seconds() // 60)
        if 0 < minutes < 24 * 60:
            said += f" ({minutes // 60} h {minutes % 60:02d} min)" if minutes >= 60 else f" ({minutes} min)"
    said += f", on your clock ({zone.key})"
    theirs = one.start.tzinfo
    if one.floating:
        said += "; the invitation gives no time zone, so it was read as yours"
    elif theirs is not None and their_clock(one) \
            and one.start.utcoffset() != one.start.astimezone(zone).utcoffset():
        said += f"; the sender wrote {their_clock(one)}"
    return said


def their_clock(one: Invite) -> str:
    """The sender's own time of the start, as a person says it: "09:00 Los Angeles time"."""
    if not isinstance(one.start, datetime) or one.floating or one.zone_said == "UTC":
        # A time written in UTC (Google's own invitations) is how it was sent, not the sender's clock.
        return ""
    zone = one.start.tzinfo
    key = getattr(zone, "key", "")
    if key.startswith("Etc/") or key == "UTC" or one.zone_said == "UTC":
        return f"{one.start:%H:%M} UTC" + ("" if not one.start.utcoffset() else _off(one.start))
    if key:
        return f"{one.start:%H:%M} {key.rsplit('/', 1)[-1].replace('_', ' ')} time"
    return f"{one.start:%H:%M} UTC{_off(one.start)}"


def _off(value: datetime) -> str:
    total = int((value.utcoffset() or timedelta(0)).total_seconds() // 60)
    sign = "+" if total >= 0 else "-"
    return f"{sign}{abs(total) // 60:02d}:{abs(total) % 60:02d}"


def _who(one: Guest | None) -> str:
    if one is None:
        return ""
    return f"{one.name} <{one.email}>" if one.name and one.name != one.email else one.email


def described(one: Invite, zone) -> str:
    """One invitation, in a few plain lines."""
    lines = [f"- What it is: {one.kind}" + (f", version {one.sequence}" if one.sequence else "")]
    if one.title:
        lines.append(f"- Title: {one.title}")
    lines.append(f"- When: {when_words(one, zone)}")
    if one.repeats:
        lines.append(f"- It repeats ({one.repeats})" + (", and this is one date of it" if one.recurrence_id else ""))
    elif one.recurrence_id:
        lines.append("- It is one date of a repeating meeting")
    if one.where:
        lines.append(f"- Where: {one.where[:200]}")
    if one.call:
        lines.append(f"- Call link: {one.call}")
    if one.organiser:
        lines.append(f"- Sent by: {_who(one.organiser)}")
    if one.guests:
        if one.method == "REPLY":
            lines.append("- The answer: " + "; ".join(
                f"{_who(g)} {ANSWERS.get(g.answer, g.answer.lower() or 'answered')}" for g in one.guests))
        else:
            shown = one.guests[:12]
            words = "; ".join(_who(g) + (f" ({ANSWERS[g.answer]})" if g.answer in ANSWERS
                                         and g.answer != "NEEDS-ACTION" else "") for g in shown)
            more = f" and {len(one.guests) - len(shown)} more" if len(one.guests) > len(shown) else ""
            lines.append(f"- Invited ({len(one.guests)}): {words}{more}")
    if one.cancelled:
        lines.append("- It is cancelled.")
    if one.uid:
        lines.append(f"- Its calendar id (UID): {one.uid[:120]}")
    return "\n".join(lines)


__all__ = ["ANSWERS", "Guest", "Invite", "METHODS", "WINDOWS", "described", "parse", "their_clock", "when_words"]
