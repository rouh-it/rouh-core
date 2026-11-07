"""Calendar: calendars and their events, read and written in the person's own
time zone.
"""
from __future__ import annotations

import asyncio
import re
import urllib.parse
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING

from ..google_oauth import (CALENDAR_NEEDED, CALENDAR_SCOPE, NeedsMoreAccess, NeedsReconnect,
                            NotConnected)
from ..tenancy import Identity
from .common import CannotDoThat, GoogleSaidNo, SeveralOfThose, _text_of_html

if TYPE_CHECKING:
    from .clients import GoogleClients


#: How many events a listing gives back when it is not told, and the most it
#: ever does. Fifty is a fortnight of a busy working calendar; two hundred and
#: fifty is Google's own default page and more than anybody listens to.
EVENTS_LISTED = 50
MAX_EVENTS_LISTED = 250

#: How far a listing looks when it is given no times: the next week, from the
#: start of today. A search with words and no times looks a year either way,
#: because "when is the dentist" may be last month or next.
LOOK_AHEAD_DAYS = 7
SEARCH_REACH_DAYS = 366

#: The most calendars one account's list is read to. A person sees perhaps a
#: dozen; this is only a ceiling on a list somebody filled with subscriptions.
MAX_CALENDARS = 100

#: How long an event is when it is given a start and nothing else.
DEFAULT_MINUTES = 60

#: What each of Google's four access roles lets this account do, said the way
#: a person would say it. `freeBusyReader` is the one worth reading twice: a
#: calendar shared that way shows when its owner is busy and nothing else, so
#: its events are never listed, only its busy times.
ACCESS_WORDS = {
    "owner": "can change everything, including who it is shared with",
    "writer": "can add, change and delete events",
    "reader": "can see every event, and change nothing",
    "freeBusyReader": "can see only when it is busy",
}

#: The roles an event may be written with.
WRITABLE = ("owner", "writer")

#: The order calendars are listed in after the person's own and the account's
#: own: the ones Rouh may change first, then the ones it may only read.
ACCESS_ORDER = {"owner": 0, "writer": 1, "reader": 2, "freeBusyReader": 3}

#: An invitation's answer, as Google names it and as a person says it.
RESPONSES = {
    "accepted": "accepted",
    "declined": "declined",
    "tentative": "said maybe",
    "needsAction": "has not answered",
}


#: The time zone a calendar Rouh makes keeps when it is not told one: blank,
#: which is where the person lives now, their own clock (`zone_of_person`), as
#: Petar asked on 12 October 2026. It was a place written here until
#: 20 October 2026; it is nobody's now. A calendar's zone is only where its new
#: events start on Google's screen; every time Rouh writes carries its own
#: zone anyway.
NEW_CALENDAR_ZONE = ""

#: What a person hears when making a calendar, or changing who one is shared
#: with, finds the grant without the whole Calendar scope. Unlike
#: `CALENDAR_NEEDED` it names the scope, because a narrower calendar grant
#: reads and writes events perfectly well and still cannot do this, and what
#: has to be fixed is that one permission on Google's consent screen.
MAKING_CALENDARS_NEEDS = (
    f"Making a calendar, and changing who a calendar is shared with, need the whole "
    f"Google Calendar permission, {CALENDAR_SCOPE}, and this Google connection was "
    f"not given it: a narrower calendar permission is not enough. The connected "
    f"account has to consent again: open Settings, press Grant the new access (or "
    f"Connect Google), allow Google Calendar on Google's screen, and ask me again. "
    f"Nothing was made or shared.")

#: The four roles a calendar can be shared with somebody at, widest last, and
#: what each lets that person do, said the way a person would say it.
SHARE_ROLES = {
    "freeBusyReader": "see only when it is busy",
    "reader": "see every event",
    "writer": "add, change and delete events",
    "owner": "change everything, including who it is shared with, and delete it",
}

#: Every secondary calendar's id ends with this. A person's own calendar's id
#: is their address, and a calendar Rouh may change the sharing of is never
#: one of those (`Calendar.owned`).
SECONDARY_CALENDAR = "@group.calendar.google.com"

#: Something that is one email address and nothing else.
_ONE_ADDRESS = re.compile(r"[^@\s,;<>\"']+@[^@\s,;<>\"']+\.[^@\s,;<>\"']+")


class NotOnThisAccount(RuntimeError):
    """A calendar name this account has nothing called, with what it does have.

    Like `SeveralOfThose`, not a refusal from Google: the list was read and
    the name is not on it. The message is every calendar that is, so the
    person hears what to say instead, and it is shown as it is.
    """


def zone_of_person():
    """Where the person is, which is the clock every calendar time is read on.

    `clock.zone()`, because that is the clock the model is told "now" is on: a
    time it gives with no offset means the same wall clock as the one in its
    own prompt, and every time it is given back is on it too.
    """
    from ..clock import zone

    return zone()


def when_given(value, zone=None) -> date | datetime | None:
    """A time a tool was given, read the way the person meant it.

    "2026-09-25" is a whole day. "2026-09-25T15:00" is three in the afternoon
    on the person's clock. A time with its own offset, or a Z, keeps it and is
    then said back on the person's clock. Nothing gives None.
    """
    text = str(value or "").strip()
    if not text:
        return None
    zone = zone or zone_of_person()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        try:
            return date.fromisoformat(text)
        except ValueError:
            raise CannotDoThat(f"{text!r} is not a day on the calendar.") from None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{1,2}:\d{2}(:\d{2})?", text):
        text = text.replace(" ", "T", 1)
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        raise CannotDoThat(
            f"{text!r} is not a time I can read. Give a whole day as 2026-09-25 and a "
            f"time as 2026-09-25T15:00, on the person's own clock.") from None
    if moment.tzinfo is None:
        return moment.replace(tzinfo=zone)
    return moment.astimezone(zone)


def _from_google(part: dict, zone) -> date | datetime | None:
    """One end of an event as Google holds it: a moment, or a whole day."""
    part = part or {}
    if part.get("dateTime"):
        try:
            return datetime.fromisoformat(
                str(part["dateTime"]).replace("Z", "+00:00")).astimezone(zone)
        except ValueError:
            return None
    if part.get("date"):
        try:
            return date.fromisoformat(str(part["date"]))
        except ValueError:
            return None
    return None


def _to_google(value: date | datetime, zone_name: str, *, clearing: bool = False) -> dict:
    """One end of an event the way Google takes it.

    A moment carries its offset and the zone it belongs to, which a repeating
    event must have. `clearing` is for a change from a timed event to a whole
    day or back: a PATCH merges objects, so the half that is no longer true
    has to be said to be empty or Google keeps both.
    """
    if isinstance(value, datetime):
        out = {"dateTime": value.isoformat(timespec="seconds"), "timeZone": zone_name}
        if clearing:
            out["date"] = None
        return out
    out = {"date": value.isoformat()}
    if clearing:
        out["dateTime"] = None
    return out


def _rfc3339(value: date | datetime, zone) -> str:
    """A bound for a listing, which Google takes only as a moment with an offset."""
    if not isinstance(value, datetime):
        value = datetime(value.year, value.month, value.day, tzinfo=zone)
    return value.isoformat(timespec="seconds")


def _moment(value: date | datetime | None, zone) -> datetime:
    """Something to sort by: a whole day counts from its midnight."""
    if value is None:
        return datetime.max.replace(tzinfo=timezone.utc)
    if isinstance(value, datetime):
        return value
    return datetime(value.year, value.month, value.day, tzinfo=zone)


def event_span(start, end, minutes=None) -> tuple[date | datetime, date | datetime]:
    """Where an event begins and ends, from what a person said.

    A whole-day event's end is the last day it covers, the way a person says
    "Monday to Wednesday"; `_to_google` is given the day after, which is what
    Google means by an end. A timed event with no end lasts `minutes`, or an
    hour.
    """
    if start is None:
        raise CannotDoThat("Say when it starts.")
    if isinstance(start, datetime):
        if end is None:
            end = start + timedelta(minutes=int(minutes or DEFAULT_MINUTES))
        elif not isinstance(end, datetime):
            raise CannotDoThat("It starts at a time, so give its end as a time too, "
                          "like 2026-09-25T16:00.")
        if end <= start:
            raise CannotDoThat("It has to end after it starts.")
        return start, end
    if end is None:
        end = start
    elif isinstance(end, datetime):
        raise CannotDoThat("A whole-day event ends on a day, not at a time: give its "
                      "last day, like 2026-09-26.")
    if end < start:
        raise CannotDoThat("Its last day cannot be before its first.")
    return start, end


def listing_window(start, end, *, searching: bool = False,
                   zone=None) -> tuple[datetime, datetime]:
    """The two moments a listing runs between, from what the tool was given.

    A day alone is the whole of that day, so "what do I have tomorrow" is
    tomorrow's date and nothing else, and a day given as the end includes it.
    A time is that moment. Nothing at all is the next `LOOK_AHEAD_DAYS` from
    the start of today, or, when there are words to search for, a year either
    side of today.
    """
    zone = zone or zone_of_person()
    today = datetime.now(zone).date()

    def midnight(day: date) -> datetime:
        return datetime(day.year, day.month, day.day, tzinfo=zone)

    if start is None and end is None:
        if searching:
            return (midnight(today - timedelta(days=SEARCH_REACH_DAYS)),
                    midnight(today + timedelta(days=SEARCH_REACH_DAYS + 1)))
        return midnight(today), midnight(today + timedelta(days=LOOK_AHEAD_DAYS))
    if start is None:
        start = today
    begin = start if isinstance(start, datetime) else midnight(start)
    if end is None:
        finish = (begin + timedelta(days=LOOK_AHEAD_DAYS) if isinstance(start, datetime)
                  else midnight(start + timedelta(days=1)))
    else:
        finish = end if isinstance(end, datetime) else midnight(end + timedelta(days=1))
    if finish <= begin:
        raise CannotDoThat("The end of that span is before its start.")
    return begin, finish


def said_day(value: date | datetime) -> str:
    """'Thursday 25 September 2026'."""
    return f"{value:%A} {value.day} {value:%B %Y}"


def said_span(start, end, all_day: bool) -> str:
    """When an event is, the way it would be read out.

    'Thursday 25 September 2026, 15:00-16:00', 'Thursday 25 September 2026,
    all day', and an event that runs past midnight says both days.
    """
    if start is None:
        return "at a time Google did not say"
    if all_day or not isinstance(start, datetime):
        if end is None or end == start:
            return f"{said_day(start)}, all day"
        return f"{said_day(start)} to {said_day(end)}, all day"
    if end is None:
        return f"{said_day(start)}, {start:%H:%M}"
    if end.date() == start.date():
        return f"{said_day(start)}, {start:%H:%M}-{end:%H:%M}"
    return f"{said_day(start)}, {start:%H:%M} to {said_day(end)}, {end:%H:%M}"


def _a_calendar(raw: dict) -> dict:
    """One calendar on the account's list, keyed the way a person names things."""
    own_name = raw.get("summaryOverride") or raw.get("summary") or raw.get("id") or ""
    access = raw.get("accessRole") or "reader"
    return {
        "id": raw.get("id") or "",
        "name": own_name,
        "real_name": raw.get("summary") or "",
        "primary": bool(raw.get("primary")),
        "access": access,
        "can": ACCESS_WORDS.get(access, access),
        "writable": access in WRITABLE,
        "zone": raw.get("timeZone") or "",
        "about": (raw.get("description") or "").strip(),
        "hidden": bool(raw.get("hidden")),
        # The account that made it, which Google says only of a secondary
        # calendar: what `Calendar.owned` checks before any sharing changes.
        "made_by": raw.get("dataOwner") or "",
    }


def _a_guest(raw: dict) -> dict:
    return {
        "email": raw.get("email") or "",
        "name": raw.get("displayName") or "",
        "response": raw.get("responseStatus") or "needsAction",
        "optional": bool(raw.get("optional")),
        "organiser": bool(raw.get("organizer")),
        "this_calendar": bool(raw.get("self")),
        "resource": bool(raw.get("resource")),
        # People they may bring, or the members of a group Google expanded the count of.
        "additional": int(raw.get("additionalGuests") or 0),
    }


def _an_event(raw: dict, calendar: dict, zone) -> dict:
    """One event, keyed the way a person names things, on the person's clock.

    `this_calendar` on a guest, and `mine` on the event, are about the calendar
    this copy of the event was read from, which is what Google's own `self`
    means. On a calendar somebody shared with this account that is the sharer,
    not the account, and that is the person a reply from here speaks for.
    """
    start = _from_google(raw.get("start"), zone)
    end = _from_google(raw.get("end"), zone)
    all_day = start is not None and not isinstance(start, datetime)
    if all_day and end is not None and not isinstance(end, datetime):
        # Google's end is the day after the last one; a person's is the last.
        end = max(start, end - timedelta(days=1))
    guests = [_a_guest(one) for one in raw.get("attendees") or []]
    me = next((one for one in guests if one["this_calendar"]), None)
    organiser = raw.get("organizer") or {}
    video = raw.get("hangoutLink") or ""
    if not video:
        for point in (raw.get("conferenceData") or {}).get("entryPoints") or []:
            if point.get("entryPointType") == "video" and point.get("uri"):
                video = point["uri"]
                break
    description = raw.get("description") or ""
    if "<" in description and ">" in description:
        description = _text_of_html(description)
    return {
        "id": raw.get("id") or "",
        "calendar_id": calendar.get("id") or "",
        "calendar": calendar.get("name") or calendar.get("id") or "",
        "title": (raw.get("summary") or "").strip() or "(no title)",
        "start": start,
        "end": end,
        "all_day": all_day,
        "zone": (raw.get("start") or {}).get("timeZone") or "",
        "where": (raw.get("location") or "").strip(),
        "description": description.strip(),
        "organiser": organiser.get("email") or "",
        "organiser_name": organiser.get("displayName") or "",
        "mine": bool(organiser.get("self")),
        "guests": guests,
        # Google left part of a long guest list out of this copy of the event.
        "guests_omitted": bool(raw.get("attendeesOmitted")),
        "my_response": me["response"] if me else "",
        "video": video,
        "link": raw.get("htmlLink") or "",
        "series": raw.get("recurringEventId") or "",
        "repeats": [str(one) for one in raw.get("recurrence") or []],
        "status": raw.get("status") or "confirmed",
        "busy": raw.get("transparency") != "transparent",
        "kind": raw.get("eventType") or "default",
        # The iCloud contact a birthday Rouh put on the calendar is for
        # (`rouh/birthdays.py`), which Rouh writes into the event's own
        # private properties as it adds it.
        "contact_uid": str(((raw.get("extendedProperties") or {}).get("private") or {})
                           .get("rouhContactUid") or ""),
        # The files attached to the invitation, each a Drive file: read by What to raise
        # (`rouh/raise_attached.py`) and added to by Attach to a meeting (`rouh/meeting_attach.py`).
        "attachments": attachments_of(raw),
        # What a calendar knows the meeting by, the UID of the invitation it came in
        # (Invitations not in your calendar, `rouh/invite_missing.py`).
        "ical_uid": str(raw.get("iCalUID") or ""),
    }


def attachments_of(raw: dict) -> list[dict]:
    """The files attached to one event as Google gives them: [{title, link, file_id, mime_type}]."""
    out = []
    for one in raw.get("attachments") or []:
        if not isinstance(one, dict) or not one.get("fileUrl"):
            continue
        out.append({"title": str(one.get("title") or "").strip() or "an attached file",
                    "link": str(one.get("fileUrl") or ""), "file_id": str(one.get("fileId") or ""),
                    "mime_type": str(one.get("mimeType") or "")})
    return out


#: What an event is, field by field, for saying whether restoring it kept it:
#: everything but its status and Google's own bookkeeping (etag, updated,
#: sequence), which a restore changes by being one.
_RESTORE_KEEPS = ("summary", "description", "location", "start", "end", "recurrence",
                  "recurringEventId", "originalStartTime", "organizer", "hangoutLink",
                  "transparency", "visibility", "colorId", "eventType")


def restore_changed(before: dict, after: dict) -> list[str]:
    """Which of an event's details differ between two reads of it, by Google's name.

    Guests are compared by address and answer, and the call by its links,
    because Google rewrites the rest of both (display names, entry point
    labels) as it pleases.
    """
    changed = [name for name in _RESTORE_KEEPS if before.get(name) != after.get(name)]

    def guests(raw):
        return sorted((str(one.get("email") or "").lower(), one.get("responseStatus") or "",
                       bool(one.get("optional"))) for one in raw.get("attendees") or [])

    def call(raw):
        return sorted(str(one.get("uri") or "")
                      for one in (raw.get("conferenceData") or {}).get("entryPoints") or [])

    if guests(before) != guests(after):
        changed.append("attendees")
    if call(before) != call(after):
        changed.append("conferenceData")
    return changed


def must_be_one_address(value: str) -> str:
    """One email address, as it was given, or `CannotDoThat`.

    A calendar is only ever shared with one person at a time, by their
    address: never a list of them, never a domain, and never "anyone" or
    "default", which is how Google spells the public.
    """
    text = str(value or "").strip()
    if text.lower().startswith("mailto:"):
        text = text[len("mailto:"):]
    if not _ONE_ADDRESS.fullmatch(text):
        raise CannotDoThat(
            f"{text or 'Nothing'!r} is not one email address. A calendar is shared with "
            f"one person at a time, by their address, and never with the public or a "
            f"whole domain.")
    return text


class Calendar:
    """Google Calendar: every calendar the account can see, and the events on them.

    Its own calendars and every calendar somebody has shared with it, read and
    written alike. Every request names `CALENDAR_SCOPE`, so a connection made
    before Rouh asked for calendars is told so before anything goes out, and
    nothing else it can do is stopped for it (`google_oauth.CHECKED_PER_CALL`).

    Every time in and out is on the person's clock (`zone_of_person`).
    """

    def __init__(self, clients: GoogleClients, who: Identity) -> None:
        self._clients = clients
        self._who = who
        self.zone = zone_of_person()
        #: The account's calendar list, read once per tool call at most. A
        #: Calendar is made for one call (`GoogleDesk.services`), so this is
        #: never older than the sentence it is used in.
        self._list: list[dict] | None = None

    def _url(self, path: str) -> str:
        return self._clients.base("calendar") + "/calendar/v3" + path

    @staticmethod
    def _id(value: str) -> str:
        # A calendar id is often an email address and a holiday calendar's has
        # a '#' in it, so nothing in either is left for the URL to read.
        return urllib.parse.quote(str(value or ""), safe="")

    def _event_path(self, calendar_id: str, event_id: str = "") -> str:
        path = f"/calendars/{self._id(calendar_id)}/events"
        return path + (f"/{self._id(event_id)}" if event_id else "")

    async def _call(self, method: str, path: str, **kw):
        kw.setdefault("without_it", CALENDAR_NEEDED)
        return await self._clients.call(
            self._who, method, self._url(path), needs_scope=CALENDAR_SCOPE, **kw)

    def _may_make_calendars(self) -> None:
        """Refuse up front, naming the scope, when the grant cannot make or share one.

        `calendars.insert` and every `acl` call need the whole Calendar scope;
        the narrower ones Google offers (`calendar.events`, `calendar.readonly`
        and the rest) do not reach them. Checked before anything is read, so
        what the person hears is this sentence and not the general one about
        calendars.
        """
        self._clients._must_hold(self._who, CALENDAR_SCOPE, MAKING_CALENDARS_NEEDS)

    # --- which calendars -----------------------------------------------------

    async def calendars(self) -> list[dict]:
        """Every calendar on the account's list: its own first, then shared ones.

        A calendar somebody shared with the account is on this list once it
        has been added to it, which Google does by itself for some shares and
        which `add` does for the rest.
        """
        if self._list is not None:
            return self._list
        found: list[dict] = []
        page = ""
        while len(found) < MAX_CALENDARS:
            params = {"maxResults": 250}
            if page:
                params["pageToken"] = page
            got = await self._call("GET", "/users/me/calendarList", params=params)
            found.extend(_a_calendar(one) for one in got.get("items") or [])
            page = got.get("nextPageToken") or ""
            if not page:
                break
        # Whose each one is. The account's own main calendar is `primary`; the
        # person's own is the one whose id is their address, which is how a
        # calendar they shared with a Google account of Rouh's own arrives.
        mine = (self._who.email or "").strip().lower()
        for one in found:
            one["theirs"] = bool(mine) and one["id"].lower() == mine
        found.sort(key=lambda one: (not one["theirs"], not one["primary"],
                                    ACCESS_ORDER.get(one["access"], len(ACCESS_ORDER)),
                                    one["name"].lower()))
        self._list = found[:MAX_CALENDARS]
        return self._list

    async def usual(self) -> str:
        """The calendar a person means by "my calendar", when they name none.

        Their own, when it is on the list and this account may write to it:
        Rouh may be connected to a Google account of its own that the person
        shared their calendar with, and then "put it in my calendar" means
        theirs, not the account's. Otherwise the account's own main calendar.
        """
        for one in await self.calendars():
            if one["theirs"] and one["writable"]:
                return one["id"]
        return "primary"

    async def find_event(self, event_id: str, calendar: str = "") -> str:
        """Which calendar an event is on, when it was not said.

        The usual calendar first, then every other on the list, and the first
        that holds it is the answer. A listing always says which calendar each
        event is on, so this is only the net under a call that left it out.
        """
        if calendar:
            return await self.calendar_id(calendar)
        first = await self.usual()
        tried = [first] + [one["id"] for one in await self.calendars()
                           if one["id"] != first and one["access"] != "freeBusyReader"]
        refused: Exception | None = None
        for calendar_id in tried:
            try:
                await self._raw(calendar_id, event_id)
                return calendar_id
            except GoogleSaidNo as exc:
                refused = refused or exc
        raise refused or GoogleSaidNo(f"There is no event {event_id} on any calendar here.")

    async def about(self, calendar_id: str) -> dict:
        """One calendar from the list, or as much as is known of one that is not on it."""
        wanted = (calendar_id or "").strip()
        for one in await self.calendars():
            if one["id"] == wanted or (wanted == "primary" and one["primary"]):
                return one
        return {"id": wanted, "name": wanted, "real_name": "", "primary": False,
                "access": "", "can": "", "writable": True, "zone": "", "about": "",
                "hidden": False, "made_by": "", "theirs": False}

    async def calendar_id(self, name_or_id: str) -> str:
        """The calendar a person means, by its name on the list or by its id.

        Left out, it is `usual`; "primary" is the account's own. Otherwise an id first,
        then a name exactly, then a name containing the words - and a name that
        fits two calendars is said back with both rather than chosen between,
        for the same reason `Drive.folder_id` does. An address that is on no
        calendar here is taken at its word, because a calendar shared with the
        account can be read before it is on the list.
        """
        wanted = (name_or_id or "").strip()
        if not wanted:
            return await self.usual()
        if wanted.lower() == "primary":
            return "primary"
        calendars = await self.calendars()
        lowered = wanted.lower()
        for one in calendars:
            if one["id"].lower() == lowered:
                return one["id"]
        exact = [one for one in calendars
                 if lowered in (one["name"].lower(), one["real_name"].lower())]
        if len(exact) == 1:
            return exact[0]["id"]
        near = exact or [one for one in calendars
                         if lowered in one["name"].lower() or lowered in one["real_name"].lower()]
        if len(near) == 1:
            return near[0]["id"]
        if near:
            lines = [f"{one['name']!r} - id {one['id']}" for one in near]
            raise SeveralOfThose(
                f"There is more than one calendar called {wanted!r} on this account, "
                f"so I have not guessed. Say which one by its id:\n" + "\n".join(lines))
        if "@" in wanted:
            return wanted
        names = ", ".join(repr(one["name"]) for one in calendars) or "none at all"
        raise NotOnThisAccount(
            f"There is no calendar called {wanted!r} on this account. The calendars it "
            f"can see are {names}.")

    async def add(self, calendar_id: str) -> dict:
        """Put a calendar somebody shared with this account onto its list.

        It changes nothing but the list: nobody's events, and nobody's sharing.
        Google refuses it unless the calendar's owner has shared it with this
        account, or made it public.
        """
        got = await self._call("POST", "/users/me/calendarList",
                               json_body={"id": (calendar_id or "").strip()})
        self._list = None
        return _a_calendar(got)

    async def remove(self, calendar_id: str) -> dict:
        """Take a calendar off the account's list, so Rouh no longer reads it or acts on it.

        It is `add` the other way round (`calendarList.delete`): nobody's events
        and nobody's sharing change, and the calendar itself is not deleted, so
        it can be added again by its id. The account's own main calendar cannot
        leave its list; disconnecting the account is how that one goes.
        """
        wanted = (calendar_id or "").strip()
        calendar = await self.about(wanted)
        if calendar["primary"] or wanted.lower() == "primary":
            raise GoogleSaidNo("It is this account's own calendar, which cannot leave its "
                               "list. Disconnect the account to stop Rouh reading it.")
        await self._call("DELETE", "/users/me/calendarList/" + self._id(wanted))
        self._list = None
        return calendar

    # --- making a calendar, and who it is shared with --------------------------

    async def create_calendar(self, name: str, *, account: str, description: str = "",
                              zone: str = NEW_CALENDAR_ZONE) -> dict:
        """Make a new secondary calendar on this account, and see it is on its list.

        `account` is the connected Google account's address. A calendar that
        account already made under the same name is handed back rather than
        made twice, with `made` false, because "make us a calendar" said twice
        is one calendar. Google puts a calendar on its maker's list by itself;
        if it ever has not, it is added, so the next list_calendars has it.
        """
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        self._may_make_calendars()
        name = (name or "").strip()
        if not name:
            raise CannotDoThat("Say what to call the calendar.")
        zone = (zone or "").strip() or NEW_CALENDAR_ZONE or getattr(self.zone, "key", "") or "UTC"
        try:
            ZoneInfo(zone)
        except (ZoneInfoNotFoundError, ValueError):
            raise CannotDoThat(
                f"{zone!r} is not a time zone I know. Give one like Europe/Lisbon, "
                f"Asia/Tokyo or America/Los_Angeles.") from None
        maker = (account or "").strip().lower()
        for one in await self._listing_to_make():
            if (maker and one["made_by"].lower() == maker
                    and name.lower() in (one["real_name"].lower(), one["name"].lower())):
                return dict(one, made=False)
        body = {"summary": name, "timeZone": zone}
        if (description or "").strip():
            body["description"] = description.strip()
        made = await self._call("POST", "/calendars", json_body=body,
                                without_it=MAKING_CALENDARS_NEEDS)
        calendar_id = made.get("id") or ""
        self._list = None
        try:
            entry = await self._call(
                "GET", f"/users/me/calendarList/{self._id(calendar_id)}")
        except GoogleSaidNo:
            entry = await self._call("POST", "/users/me/calendarList",
                                     json_body={"id": calendar_id})
        return dict(_a_calendar({**made, **entry}), made=True)

    async def owned(self, name_or_id: str, *, account: str) -> dict:
        """The calendar a person means, when it is one this account made itself.

        Who a calendar is shared with is only ever changed on a calendar Rouh's
        own Google account made: never the person's own calendar, never the
        account's main one, and never one somebody else shared with it, even
        when they gave it the right to change who sees it. So the calendar has
        to be a secondary one, and Google itself has to say this account made
        it (`dataOwner`), read fresh from Google rather than from the list.
        Anything else is refused before anything is changed.
        """
        self._may_make_calendars()
        wanted = (name_or_id or "").strip()
        if not wanted:
            raise CannotDoThat("Say which calendar, by its name or its id.")
        maker = (account or "").strip().lower()
        if not maker:
            raise CannotDoThat(
                "I cannot tell which Google account is connected, so I cannot tell "
                "whether it made that calendar. Nothing was changed.")
        await self._listing_to_make()
        calendar_id = await self.calendar_id(wanted)
        about = await self.about(calendar_id)
        said = about["name"] if about["name"] != calendar_id else calendar_id
        person = (self._who.email or "").strip().lower()
        if (calendar_id.lower() in ("primary", maker, person)
                or not calendar_id.lower().endswith(SECONDARY_CALENDAR)):
            raise CannotDoThat(
                f"{said!r} is not a calendar {account} made, and I only ever change who "
                f"can see a calendar Rouh made itself with create_calendar - never a "
                f"person's own calendar, and never this account's main one. Nothing was "
                f"changed.")
        raw = await self._call("GET", f"/calendars/{self._id(calendar_id)}")
        made_by = str(raw.get("dataOwner") or "").strip().lower()
        if made_by != maker:
            raise CannotDoThat(
                f"{said!r} was not made by {account}"
                + (f" but by {made_by}" if made_by else "")
                + ", so who can see it is not Rouh's to change: only its owner can "
                  "share it, in Google Calendar. Nothing was changed.")
        return {"id": calendar_id, "name": raw.get("summary") or said}

    async def _listing_to_make(self) -> list[dict]:
        """The calendar list, read first by making and sharing, and said so if refused.

        It is the first request either sends, so a token Google refuses for want
        of the Calendar scope is refused here, and what is said is the sentence
        that names the scope rather than the general one about calendars.
        """
        try:
            return await self.calendars()
        except NeedsMoreAccess:
            raise NeedsMoreAccess(MAKING_CALENDARS_NEEDS) from None

    def _acl_path(self, calendar_id: str, rule_id: str = "") -> str:
        path = f"/calendars/{self._id(calendar_id)}/acl"
        return path + (f"/{self._id(rule_id)}" if rule_id else "")

    async def sharing(self, calendar_id: str) -> list[dict]:
        """Everybody who has access to a calendar, and at which role.

        Each is `who` (an address, a domain, or "" for the public), `kind`
        (Google's scope type: user, group, domain or default) and `role`. The
        calendar's own entry for itself, which Google lists as an owner of it,
        is left out: it is not a person, and nothing could take it away.
        """
        found: list[dict] = []
        page = ""
        while True:
            params = {"maxResults": 250}
            if page:
                params["pageToken"] = page
            got = await self._call("GET", self._acl_path(calendar_id), params=params,
                                   without_it=MAKING_CALENDARS_NEEDS)
            for rule in got.get("items") or []:
                scope = rule.get("scope") or {}
                who = str(scope.get("value") or "")
                if who.lower() == calendar_id.lower():
                    continue
                found.append({"rule": rule.get("id") or "", "kind": scope.get("type") or "",
                              "who": who, "role": rule.get("role") or ""})
            page = got.get("nextPageToken") or ""
            if not page:
                return found

    @staticmethod
    def _rule_for(rules: list[dict], email: str) -> dict | None:
        return next((one for one in rules
                     if one["kind"] == "user" and one["who"].lower() == email.lower()), None)

    async def share(self, calendar_id: str, email: str, role: str, *,
                    notify: bool = True) -> tuple[str, str]:
        """Give one person access to a calendar at a role, or change theirs.

        Only ever to one email address: the scope is always a user, never a
        domain and never the public, whatever is asked. Gives back what it did,
        "added", "changed" or "unchanged", and the role they had before ("" for
        somebody who had none). Google emails them about it unless `notify` is
        false.
        """
        email = must_be_one_address(email)
        if role not in SHARE_ROLES:
            raise CannotDoThat("A calendar is shared as " + ", ".join(SHARE_ROLES) + ".")
        had = self._rule_for(await self.sharing(calendar_id), email)
        sends = {"sendNotifications": "true" if notify else "false"}
        if had is None:
            await self._call("POST", self._acl_path(calendar_id), params=sends,
                             json_body={"role": role,
                                        "scope": {"type": "user", "value": email}},
                             without_it=MAKING_CALENDARS_NEEDS)
            return "added", ""
        if had["role"] == role:
            return "unchanged", role
        await self._call("PATCH", self._acl_path(calendar_id, had["rule"]), params=sends,
                         json_body={"role": role}, without_it=MAKING_CALENDARS_NEEDS)
        return "changed", had["role"]

    async def unshare(self, calendar_id: str, email: str) -> str:
        """Take one person's access to a calendar away. Gives back the role they had,
        or "" when they had none and nothing was asked of Google."""
        email = must_be_one_address(email)
        had = self._rule_for(await self.sharing(calendar_id), email)
        if had is None:
            return ""
        await self._call("DELETE", self._acl_path(calendar_id, had["rule"]),
                         without_it=MAKING_CALENDARS_NEEDS)
        return had["role"]

    # --- reading events ------------------------------------------------------

    async def events(self, start, end, *, calendar_ids=(), text: str = "",
                     limit: int = EVENTS_LISTED) -> dict:
        """Every event between two moments, on every calendar or the ones named.

        Each calendar is asked at the same moment rather than one after
        another, so ten calendars cost one round trip's wait. Repeating events
        come back as the occurrences that fall inside the window
        (`singleEvents`), which is what "what do I have on Thursday" means.

        A calendar that cannot be read does not lose the others: it is named
        in `trouble` and the rest are answered. A calendar shared as free and
        busy only has no events to list, so its busy times are asked for
        instead and come back in `busy`.

        Returns `{"events", "busy", "trouble", "calendars", "cut"}`.
        """
        want = max(1, min(int(limit or EVENTS_LISTED), MAX_EVENTS_LISTED))
        listed = await self.calendars()
        if calendar_ids:
            chosen = [await self.about(one) for one in calendar_ids]
        else:
            chosen = [one for one in listed if not one["hidden"]]
        readable = [one for one in chosen if one["access"] != "freeBusyReader"]
        busy_only = [one for one in chosen if one["access"] == "freeBusyReader"]
        bounds = {"timeMin": _rfc3339(start, self.zone), "timeMax": _rfc3339(end, self.zone)}

        async def one_calendar(calendar: dict) -> list[dict]:
            params = {**bounds, "singleEvents": "true", "orderBy": "startTime",
                      "maxResults": want, "timeZone": self.zone.key}
            if text:
                params["q"] = text
            got = await self._call("GET", self._event_path(calendar["id"]), params=params)
            return [_an_event(raw, calendar, self.zone) for raw in got.get("items") or []
                    if raw.get("status") != "cancelled"]

        answers = await asyncio.gather(*(one_calendar(one) for one in readable),
                                       return_exceptions=True)
        found: list[dict] = []
        trouble: list[str] = []
        for calendar, answer in zip(readable, answers):
            if isinstance(answer, (NotConnected, NeedsReconnect)):
                # The connection itself, not this calendar: every other
                # calendar would say the same, so it is said once, as itself.
                raise answer
            if isinstance(answer, BaseException):
                trouble.append(f"{calendar['name']} could not be read: {answer}")
                continue
            found.extend(answer)
        busy: list[dict] = []
        if busy_only and not text:
            busy, more = await self._busy(busy_only, bounds)
            trouble.extend(more)
        found.sort(key=lambda one: (_moment(one["start"], self.zone), one["title"].lower()))
        # Which calendars were really asked: a search has no words to match on
        # a free-and-busy calendar, so it is not said to have looked there.
        asked = readable + (busy_only if not text else [])
        return {"events": found[:want], "busy": busy, "trouble": trouble,
                "calendars": asked, "cut": max(0, len(found) - want)}

    async def holiday_events(self, calendar_id: str, start: date, end: date) -> list[dict]:
        """The raw events of a public calendar between two days, read without adding it to the
        account's list: Google's holiday calendars (Public holidays read from Google, night 34,
        `rouh/public_holidays.py`). Raises as every call does when Google has no such calendar."""
        params = {"timeMin": f"{start.isoformat()}T00:00:00Z", "timeMax": f"{end.isoformat()}T00:00:00Z",
                  "singleEvents": "true", "orderBy": "startTime", "maxResults": 250}
        got = await self._call("GET", self._event_path(calendar_id), params=params)
        return list(got.get("items") or [])

    async def _busy(self, calendars: list[dict], bounds: dict) -> tuple[list[dict], list[str]]:
        """When each free-and-busy-only calendar is busy, and nothing else about it."""
        got = await self._call("POST", "/freeBusy", json_body={
            **bounds, "timeZone": self.zone.key,
            "items": [{"id": one["id"]} for one in calendars]})
        out, trouble = [], []
        answered = got.get("calendars") or {}
        for calendar in calendars:
            entry = answered.get(calendar["id"]) or {}
            for error in entry.get("errors") or []:
                trouble.append(f"{calendar['name']} would not say when it is busy: "
                               f"{error.get('reason') or 'no reason given'}")
            for block in entry.get("busy") or []:
                out.append({"calendar": calendar["name"], "calendar_id": calendar["id"],
                            "start": _from_google({"dateTime": block.get("start")}, self.zone),
                            "end": _from_google({"dateTime": block.get("end")}, self.zone)})
        out.sort(key=lambda one: _moment(one["start"], self.zone))
        return out, trouble

    async def free_busy(self, ids, start: datetime, end: datetime) -> dict[str, dict]:
        """When each calendar is busy between two moments, by Google's free/busy query: a
        colleague's main calendar is named by their address, and in one Google Workspace their
        busy times are shown to the others unless they hid them (When others are free,
        `rouh/free_busy.py`). {id: {"busy": [(start, end)], "trouble": "" or Google's reason}},
        each time on the person's clock; nothing else about any event is told."""
        ids = [str(one).strip() for one in ids if str(one or "").strip()][:50]
        if not ids:
            return {}
        got = await self._call("POST", "/freeBusy", json_body={
            "timeMin": _rfc3339(start, self.zone), "timeMax": _rfc3339(end, self.zone),
            "timeZone": self.zone.key, "items": [{"id": one} for one in ids]})
        answered = got.get("calendars") or {}
        out: dict[str, dict] = {}
        for one in ids:
            entry = answered.get(one) or {}
            reasons = [str(e.get("reason") or "") for e in entry.get("errors") or []]
            spans = []
            for block in entry.get("busy") or []:
                a = _from_google({"dateTime": block.get("start")}, self.zone)
                b = _from_google({"dateTime": block.get("end")}, self.zone)
                if isinstance(a, datetime) and isinstance(b, datetime):
                    spans.append((a, b))
            out[one] = {"busy": sorted(spans), "trouble": ", ".join(r for r in reasons if r)
                        or ("" if one in answered else "notFound")}
        return out

    async def import_invite(self, *, uid: str, title: str, start, end, where: str = "",
                            description: str = "", organiser: str = "", organiser_name: str = "",
                            guests=(), sequence: int = 0) -> dict:
        """An invitation that came by email put on the account's main calendar as the same event,
        by its iCalendar UID, the way Gmail adds one itself (Google's events.import): a later
        change or cancellation of it from the sender then finds it, and nobody is emailed
        (Invitations not in your calendar, `rouh/invite_missing.py`)."""
        zone_name = self.zone.key
        body: dict = {
            "iCalUID": uid, "summary": title, "sequence": int(sequence or 0),
            "start": _to_google(start, zone_name),
            "end": _to_google(end if isinstance(end, datetime) else end, zone_name),
            "organizer": {"email": organiser, **({"displayName": organiser_name} if organiser_name else {})},
            "attendees": [{"email": g["email"], **({"displayName": g["name"]} if g.get("name") else {}),
                           "responseStatus": g.get("response") or "needsAction"} for g in guests],
        }
        if where:
            body["location"] = where
        if description:
            body["description"] = description
        made = await self._call("POST", self._event_path("primary") + "/import", json_body=body)
        return _an_event(made, await self.about("primary"), self.zone)

    async def _raw(self, calendar_id: str, event_id: str) -> dict:
        return await self._call("GET", self._event_path(calendar_id, event_id))

    async def add_video(self, calendar_id: str, event_id: str, *, notify: bool = True) -> dict:
        """A Google Meet link added to an event that has none, as the Add Google Meet button
        does (Meetings with nowhere to meet, `rouh/no_place.py`); the event as it is after.
        Google tells the guests of the change when `notify`."""
        params = {**self._send(notify), "conferenceDataVersion": 1}
        body = {"conferenceData": {"createRequest": {
            "requestId": uuid.uuid4().hex, "conferenceSolutionKey": {"type": "hangoutsMeet"}}}}
        made = await self._call("PATCH", self._event_path(calendar_id, event_id), params=params,
                                json_body=body)
        return _an_event(made, await self.about(calendar_id), self.zone)

    async def event(self, calendar_id: str, event_id: str) -> dict:
        """One event, whole: its guests and their answers, its call, its words."""
        raw = await self._raw(calendar_id, event_id)
        return _an_event(raw, await self.about(calendar_id), self.zone)

    # --- writing events ------------------------------------------------------

    async def attach(self, calendar_id: str, event_id: str, *, file_id: str, title: str,
                     link: str, mime_type: str = "") -> dict:
        """One Drive file attached to an event's invitation, beside what it has already
        (Attach to a meeting, `rouh/meeting_attach.py`). Nobody is sent an email: the guests
        find it in the invitation. {already: True} when it was attached before."""
        raw = await self._raw(calendar_id, event_id)
        had = [dict(one) for one in raw.get("attachments") or [] if isinstance(one, dict)]
        if any(str(one.get("fileId") or "") == file_id for one in had):
            return {"already": True, "event": _an_event(raw, await self.about(calendar_id), self.zone)}
        new = {"fileUrl": link, "title": title, "fileId": file_id}
        if mime_type:
            new["mimeType"] = mime_type
        changed = await self._call(
            "PATCH", self._event_path(calendar_id, event_id),
            params={"supportsAttachments": "true", **self._send(False)},
            json_body={"attachments": had + [new]})
        return {"already": False, "event": _an_event(changed, await self.about(calendar_id), self.zone)}

    def _send(self, notify: bool) -> dict:
        # Google's own default is to tell nobody. An invitation nobody is told
        # about is not one, so the tools pass what the person wants.
        return {"sendUpdates": "all" if notify else "none"}

    async def create(self, calendar_id: str, *, title: str, start, end=None, minutes=None,
                     where: str = "", description: str = "", guests=(), repeats=(),
                     video: bool = False, notify: bool = True) -> dict:
        """A new event, with its guests invited by Google if there are any."""
        start, end = event_span(start, end, minutes)
        zone_name = self.zone.key
        body: dict = {
            "summary": title,
            "start": _to_google(start, zone_name),
            "end": _to_google(end if isinstance(end, datetime) else end + timedelta(days=1),
                              zone_name),
        }
        if where:
            body["location"] = where
        if description:
            body["description"] = description
        if guests:
            body["attendees"] = [{"email": one} for one in guests]
        if repeats:
            body["recurrence"] = [one if one.upper().startswith(("RRULE:", "EXDATE:", "RDATE:"))
                                  else "RRULE:" + one for one in repeats]
        params = self._send(notify)
        if video:
            # A Google Meet link, made by Google as the event is: the request
            # id only has to be unique, and conferenceDataVersion=1 is what
            # tells the API this client knows what conferenceData is.
            body["conferenceData"] = {"createRequest": {
                "requestId": uuid.uuid4().hex,
                "conferenceSolutionKey": {"type": "hangoutsMeet"}}}
            params["conferenceDataVersion"] = 1
        made = await self._call("POST", self._event_path(calendar_id), params=params,
                                json_body=body)
        return _an_event(made, await self.about(calendar_id), self.zone)

    async def block(self, *, kind: str, start: datetime, end: datetime, title: str,
                    message: str = "", decline: str = "new") -> dict:
        """Google's own out-of-office or focus-time block on the account's own calendar (Away and
        focus time, `rouh/calendar_away.py`). Unlike an ordinary event, Google itself declines the
        invitations that fall inside it, as `decline` says: "new" (only invitations that come
        after), "all" (those already there too) or "none". Only the primary calendar of a Google
        Workspace account can hold one; Google says so plainly otherwise."""
        modes = {"new": "declineOnlyNewConflictingInvitations",
                 "all": "declineAllConflictingInvitations", "none": "declineNone"}
        properties = {"autoDeclineMode": modes.get(decline, modes["new"])}
        if message and decline != "none":
            properties["declineMessage"] = message
        body: dict = {"summary": title, "start": _to_google(start, self.zone.key),
                      "end": _to_google(end, self.zone.key), "transparency": "opaque"}
        if kind == "focus":
            body["eventType"] = "focusTime"
            body["focusTimeProperties"] = dict(properties, chatStatus="doNotDisturb")
        else:
            body["eventType"] = "outOfOffice"
            body["outOfOfficeProperties"] = properties
        made = await self._call("POST", self._event_path("primary"), json_body=body)
        return _an_event(made, await self.about("primary"), self.zone)

    async def change(self, calendar_id: str, event_id: str, *, title=None, where=None,
                     description=None, start=None, end=None, add=(), remove=(),
                     response: str = "", whole_series: bool = False,
                     notify: bool = True) -> tuple[dict, dict, list[str]]:
        """Change one event, and say what changed.

        Returns what it was, what it is now, and the changes in words. Nothing
        is sent when nothing would change.

        Moving the start keeps the length, so "move my 3pm to Thursday" is a
        start and nothing else. With `whole_series`, one occurrence of a
        repeating event stands for the series: the series is moved by exactly
        as much as that occurrence was, so "every Monday at 9" becomes "every
        Monday at 10" rather than starting again on the day that was named.
        """
        calendar = await self.about(calendar_id)
        raw = await self._raw(calendar_id, event_id)
        before = _an_event(raw, calendar, self.zone)
        target, series_raw = event_id, None
        if whole_series and raw.get("recurringEventId"):
            series_raw = await self._raw(calendar_id, raw["recurringEventId"])
            target = series_raw.get("id") or raw["recurringEventId"]
        patch: dict = {}
        changes: list[str] = []

        if title is not None and title.strip() and title.strip() != before["title"]:
            patch["summary"] = title.strip()
            changes.append(f"the title to {title.strip()!r}")
        if where is not None and where.strip() != before["where"]:
            patch["location"] = where.strip()
            changes.append(f"the place to {where.strip()!r}" if where.strip()
                           else "the place taken off")
        if description is not None and description.strip() != before["description"]:
            patch["description"] = description.strip()
            changes.append("the description")

        if start is not None or end is not None:
            new_start, new_end = self._moved(before, start, end)
            if (new_start, new_end) != (before["start"], before["end"]):
                zone_name = (raw.get("start") or {}).get("timeZone") or self.zone.key
                switching = isinstance(new_start, datetime) != isinstance(before["start"], datetime)
                if series_raw is not None:
                    series_start = _from_google(series_raw.get("start"), self.zone)
                    series_end = _from_google(series_raw.get("end"), self.zone)
                    if switching or series_start is None or series_end is None:
                        raise CannotDoThat("A whole series can be moved to another time, but "
                                      "not between a time and a whole day. Change the one "
                                      "occurrence, or make the series again.")
                    shift = new_start - before["start"]
                    length = new_end - new_start
                    moved_start = series_start + shift
                    moved_end = (moved_start + length) if isinstance(moved_start, datetime) \
                        else series_end + shift
                    patch["start"] = _to_google(moved_start, zone_name)
                    patch["end"] = _to_google(moved_end, zone_name)
                else:
                    patch["start"] = _to_google(new_start, zone_name, clearing=switching)
                    patch["end"] = _to_google(
                        new_end if isinstance(new_end, datetime) else new_end + timedelta(days=1),
                        zone_name, clearing=switching)
                all_day = not isinstance(new_start, datetime)
                changes.append("the time to " + said_span(new_start, new_end, all_day)
                               + (" for every occurrence" if series_raw is not None else ""))

        guests = [dict(one) for one in ((series_raw or raw).get("attendees") or [])]
        if add or remove or response:
            known = {str(one.get("email") or "").lower() for one in guests}
            added = []
            for address in add or ():
                address = str(address or "").strip()
                if address and address.lower() not in known:
                    guests.append({"email": address})
                    known.add(address.lower())
                    added.append(address)
            gone = {str(one or "").strip().lower() for one in remove or () if str(one or "").strip()}
            removed = [one.get("email") for one in guests
                       if str(one.get("email") or "").lower() in gone]
            guests = [one for one in guests if str(one.get("email") or "").lower() not in gone]
            if response:
                me = next((one for one in guests if one.get("self")), None)
                if me is None:
                    raise CannotDoThat(
                        "This calendar is not on that event's guest list, so there is no "
                        "invitation of its own to answer.")
                if me.get("responseStatus") != response:
                    me["responseStatus"] = response
                    changes.append(f"the answer to {RESPONSES.get(response, response)}")
            if added:
                changes.append("invited " + ", ".join(added))
            if removed:
                changes.append("took off " + ", ".join(removed))
            if added or removed or any(c.startswith("the answer") for c in changes):
                patch["attendees"] = guests

        if not patch:
            return before, before, []
        changed = await self._call("PATCH", self._event_path(calendar_id, target),
                                   params=self._send(notify), json_body=patch)
        if series_raw is not None:
            # The series was changed; what the person pointed at was one
            # occurrence of it, and that is what is said back.
            changed = await self._raw(calendar_id, event_id)
        return before, _an_event(changed, calendar, self.zone), changes

    def _moved(self, before: dict, start, end):
        """Where an event goes, keeping its length when only the start is given."""
        old_start, old_end = before["start"], before["end"]
        if start is None:
            start = old_start
        same_kind = isinstance(start, datetime) == isinstance(old_start, datetime)
        if end is None and same_kind and old_start is not None and old_end is not None:
            end = start + (old_end - old_start)
        return event_span(start, end)

    async def move_to(self, calendar_id: str, event_id: str, destination: str, *,
                      notify: bool = True) -> dict:
        """Take an event off one calendar and put it on another, as it is."""
        moved = await self._call(
            "POST", self._event_path(calendar_id, event_id) + "/move",
            params={"destination": destination, **self._send(notify)})
        return _an_event(moved, await self.about(destination), self.zone)

    async def delete(self, calendar_id: str, event_id: str, *, whole_series: bool = False,
                     notify: bool = True) -> dict:
        """Delete one event, or the whole series one occurrence belongs to.

        What was deleted is read first and handed back, so what is said is
        what Google held rather than what anybody remembered.
        """
        calendar = await self.about(calendar_id)
        raw = await self._raw(calendar_id, event_id)
        target = event_id
        if whole_series and raw.get("recurringEventId"):
            target = raw["recurringEventId"]
        await self._call("DELETE", self._event_path(calendar_id, target),
                         params=self._send(notify))
        return _an_event(raw, calendar, self.zone)

    async def restore(self, calendar_id: str, event_id: str, *,
                      notify: bool = False) -> dict:
        """Bring a deleted (cancelled) event back, as the very same event.

        Google keeps a deleted event on its organiser's calendar with its
        status set to cancelled, "so that they can be restored (undeleted)",
        and setting that one field back to confirmed is the restoring
        (https://developers.google.com/workspace/calendar/api/v3/reference/events,
        `status`). So this reads the event first, patches its status and
        nothing else - never a new event, never its guests, time, call, words
        or rules - reads it again, and checks that it came back whole and that
        an ordinary listing of its time now shows it.

        An event that is not cancelled is left alone and said to be so, which
        is what makes a second call harmless. One Google no longer holds, or
        holds only the id of, is said plainly and nothing is made in its
        place. Nobody is emailed unless `notify`.

        Returns `{"before", "after", "restored", "changed", "listed"}`:
        `restored` is False for the call that found nothing to do, `changed`
        names any detail that differs after (which should be none), and
        `listed` is whether the listing shows it.
        """
        calendar = await self.about(calendar_id)
        try:
            raw = await self._raw(calendar_id, event_id)
        except GoogleSaidNo as exc:
            if exc.status in (404, 410):
                raise CannotDoThat(
                    f"Google no longer holds event {event_id} on {calendar['name']}: it has "
                    f"been purged, or it was never on that calendar. Nothing was restored "
                    f"and nothing was made in its place.") from exc
            raise
        before = _an_event(raw, calendar, self.zone)
        if raw.get("status") != "cancelled":
            return {"before": before, "after": before, "restored": False,
                    "changed": [], "listed": None}
        if not raw.get("start"):
            # "Deleted events are only guaranteed to have the id field
            # populated": confirming one of those would bring back an empty
            # event, which is not the event the person meant.
            raise CannotDoThat(
                f"Google keeps only the id of event {event_id} now, not its title or its "
                f"time, so restoring it would bring back an empty event. Nothing was "
                f"restored and nothing was made in its place.")
        if not calendar["writable"] and calendar["access"]:
            raise CannotDoThat(
                f"This account may only read {calendar['name']}, so it cannot restore an "
                f"event on it. Nothing was changed.")
        if raw.get("recurringEventId"):
            series = await self._raw(calendar_id, raw["recurringEventId"])
            if series.get("status") == "cancelled":
                raise CannotDoThat(
                    f"This is one occurrence of a repeating event whose whole series was "
                    f"deleted. Restoring it means restoring the series, by its own event "
                    f"id {raw['recurringEventId']}, which brings every occurrence back. "
                    f"Nothing was changed.")
        await self._call("PATCH", self._event_path(calendar_id, event_id),
                         params=self._send(notify), json_body={"status": "confirmed"})
        # Read again rather than trust the answer to the patch.
        now = await self._raw(calendar_id, event_id)
        after = _an_event(now, calendar, self.zone)
        if now.get("status") == "cancelled":
            raise CannotDoThat(
                f"Google took the request but {before['title']!r} is still cancelled. Only "
                f"the organiser's calendar ({before['organiser'] or 'not said'}) can bring "
                f"a deleted event back. Nothing was made in its place.")
        listed = False
        start, end = _from_google(now.get("start"), self.zone), _from_google(now.get("end"),
                                                                             self.zone)
        if start is not None and end is not None:
            shown = await self.events(start, end, calendar_ids=[calendar_id],
                                      limit=MAX_EVENTS_LISTED)
            listed = any(one["id"] == event_id or one["series"] == event_id
                         for one in shown["events"])
        return {"before": before, "after": after, "restored": True,
                "changed": restore_changed(raw, now), "listed": listed}
