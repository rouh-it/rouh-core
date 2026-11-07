"""Before you meet: a note on the people at each outside meeting, before it starts.

Built by the nightly feature run, night 3, 7 October 2026 (task 94, idea I-001),
from task 66's "A brief before each outside meeting" and task 47's "Notes two
hours before a meeting". Before a meeting with somebody outside his own company,
Petar looked up who is coming, what they last wrote and what was said, or asked
Rouh "who is this and what did we say"; on 6 October 2026 he asked it by hand,
"I want to prepare for the Northwind meeting". So Rouh gathers it for him:

- **Who is coming.** Every guest who is not Petar, not a room and not at one of
  his own company's addresses, with what his contacts say about them: their
  name, their organisation, his relationship to them in his own words, and the
  start of Rouh's research on them (`rouh/people.py`).
- **What was said last.** The newest emails with each of them, to or from or
  copied, from his own inboxes (read only, `rouh/inboxes.py`) and from Rouh's,
  newest first, each with its subject, who sent it, when, and its first words.

Nothing is asked of a model: it is what his calendar, his contacts and his mail
already hold, put in one place.

**Where it is.**

1. In the morning brief: an event opened on its calendar shows "Before you
   meet" under its description (`GET /api/brief/event/prep`, `briefpage.js`).
2. On his phone: an hour before each such meeting, one Telegram message says
   who is coming, their organisation and the last email with each, and links to
   the brief with that event open (`Notes`, the loop below). Each event is
   noted once, kept in `user_settings` as `meeting_prep_sent`, so a restart or
   a deploy never sends it twice.

**Its switch** is `meeting_prep` (`rouh/switches.py`): off, the brief shows no
note and nothing goes to the phone.

**Whose.** Everything is read as the person whose calendar it is, with both
their ids, and only the person the bot's phone belongs to gets the Telegram line.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from datetime import datetime, timedelta

from . import clock

log = logging.getLogger("rouh.meeting_prep")

#: The feature's switch (`rouh/switches.py`).
SWITCH = "meeting_prep"
TITLE = "Before you meet: a note on who is coming to each outside meeting, in the brief and an hour before on Telegram"

#: How long before a meeting its note goes to the phone, in seconds.
LEAD = 60 * 60
#: How many guests a note is about, and how many emails it shows each.
MOST_PEOPLE = 6
MOST_MAILS = 3
#: How many of each guest's addresses are searched: the invitation's, then their card's.
MOST_ADDRESSES = 5
#: How long one note may take to gather, in seconds, before it says so.
SECONDS = 15.0
#: The setting that remembers which events have been noted on the phone.
SENT = "meeting_prep_sent"
#: How long a noted event is remembered, in seconds: well past its day.
KEEP_SENT = 3 * 24 * 3600

#: Mail services anybody can have an address at: sharing one with Petar does
#: not make a guest his colleague.
PUBLIC_MAIL = {
    "gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "live.com", "yahoo.com",
    "icloud.com", "me.com", "mac.com", "proton.me", "protonmail.com", "aol.com",
    "abv.bg", "mail.bg", "gmx.com", "gmx.net", "yandex.com", "zoho.com",
}
#: Addresses that are a calendar or a room, not a person.
NOT_A_PERSON = re.compile(r"@(?:group|resource|import)\.calendar\.google\.com$|"
                          r"@group\.v\.calendar\.google\.com$", re.I)


def on(who) -> bool:
    from . import switches

    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def _addr(value) -> str:
    return str(value or "").strip().lower()


def _domain(address: str) -> str:
    return address.rsplit("@", 1)[-1] if "@" in address else ""


def own_addresses(who) -> set[str]:
    """Every address that is the person's or Rouh's: never a guest to note."""
    from . import inboxes, my_card

    out = set(my_card.own_addresses(str(who.user_id), who.org_id))
    for one in (inboxes.account_address(who), inboxes.rouh_address(who)):
        if one:
            out.add(one)
    try:
        out.update(_addr(one.email) for one in inboxes.theirs(who) if one.email)
    except Exception:  # noqa: BLE001 - an inbox that cannot be listed is not a guest
        log.exception("the person's inboxes could not be listed")
    return {one for one in out if "@" in one}


def own_domains(addresses: set[str]) -> set[str]:
    """The person's own company's domains: their addresses' own, but no public mail service."""
    return {_domain(one) for one in addresses} - PUBLIC_MAIL - {""}


def outsiders(guests, own: set[str], domains: set[str]) -> list[dict]:
    """The guests from outside: not the person, not a room, not their company. In order, each once."""
    out, seen = [], set()
    for guest in guests or []:
        address = _addr(guest.get("email"))
        if (not address or "@" not in address or address in seen or guest.get("resource")
                or guest.get("this_calendar") or guest.get("me") or address in own
                or _domain(address) in domains or NOT_A_PERSON.search(address)):
            continue
        seen.add(address)
        out.append({"email": address, "name": str(guest.get("name") or "").strip(),
                    "response": guest.get("response") or "needsAction"})
    return out


def worth_noting(event: dict, own: set[str], domains: set[str]) -> list[dict]:
    """The outside guests of an event that gets a note, or [] for one that does not:
    all day, declined, cancelled, or only his own people."""
    if event.get("all_day") or event.get("status") == "cancelled":
        return []
    if event.get("my_response") == "declined" or event.get("response") == "declined":
        return []
    return outsiders(event.get("guests"), own, domains)


# --- what is known about each guest -----------------------------------------


def _who_they_are(who, guest: dict) -> dict:
    """The guest as his contacts know them."""
    from .people import People

    found = []
    try:
        found = People().by_address(str(who.user_id), who.org_id, guest["email"])
    except Exception:  # noqa: BLE001 - a guest Rouh knows nothing of is still a guest
        log.exception("the contacts could not be looked in for a guest")
    person = next((one for one in found if not one.is_me), None)
    # Synapse makes a person of everybody it meets in an item, often by a first
    # name alone ("Sam"): the invitation's own fuller name ("Sam Rivera") wins then.
    said = str(guest.get("name") or "").strip()
    name = (person.name if person else "") or said or guest["email"]
    if said and len(said) > len(name) and said.lower().startswith(name.lower()):
        name = said
    # Known is somebody on his phone's contacts, or somebody he or Rouh wrote
    # something down about; a person Synapse only met in an item is not.
    known = person is not None and (person.card is not None or bool(person.relationship)
                                    or bool(person.research))
    # Every address they are known by, the invitation's first: a contact's card often has
    # one for each company (fr_a69ec60fb722, a guest invited at his own company's,
    # written to and met at a client's), and the mail and meetings at each are theirs.
    own = own_addresses(who)
    emails = [guest["email"]] + [one for one in (person.emails if person else [])
                                 if one != guest["email"] and one not in own][:MOST_ADDRESSES - 1]
    return {"email": guest["email"], "emails": emails, "name": name,
            "response": guest.get("response") or "needsAction",
            "known": known, "contact_id": person.id if person else "",
            "organisation": person.organisation if person else "",
            "relationship": person.relationship[:400] if person else "",
            "research": person.gist() if person else ""}


def _mailboxes(who) -> list[tuple[str, object]]:
    """Every inbox the note looks in, by the address it is shown under, and its reader."""
    from . import inboxes

    out = []
    if inboxes.ready():
        for one in inboxes.theirs(who):
            if one.needs_reconnect:
                continue
            try:
                out.append((one.email, inboxes.open_one(who, one).gmail))
            except Exception as exc:  # noqa: BLE001
                log.info("inbox %s could not be opened for a meeting note: %s", one.email, exc)
    return out


def _gmail_link(inbox: str, thread: str) -> str:
    if not thread:
        return ""
    return ("https://mail.google.com/mail/?authuser=" + inbox + "#all/" + thread) if inbox \
        else "https://mail.google.com/mail/#all/" + thread


async def _mails_with(addresses, readers: list[tuple[str, object]]) -> list[dict]:
    """The newest emails with any of `addresses` (one, or every address a guest is known by),
    across every inbox, newest first, one a thread."""
    addresses = [addresses] if isinstance(addresses, str) else list(addresses)

    async def one_inbox(inbox: str, gmail, address: str) -> list[dict]:
        found = await gmail.recent(MOST_MAILS, address)
        return [{**one, "inbox": inbox} for one in found]

    asked = [(inbox, gmail, address) for address in addresses for inbox, gmail in readers]
    answers = await asyncio.gather(*(one_inbox(*one) for one in asked), return_exceptions=True)
    got: list[dict] = []
    for (inbox, _, _), answer in zip(asked, answers):
        if isinstance(answer, BaseException):
            log.info("inbox %s could not be searched for a meeting note: %s", inbox, answer)
            continue
        got.extend(answer)
    got.sort(key=lambda one: -(one.get("at") or 0))
    out, threads = [], set()
    for one in got:
        thread = one.get("thread_id") or one.get("id")
        if thread in threads:
            continue
        threads.add(thread)
        out.append({"subject": (one.get("subject") or "(no subject)")[:200],
                    "from": _sender(one.get("from")), "at": one.get("at") or 0,
                    "snippet": " ".join(str(one.get("snippet") or "").split())[:240],
                    "inbox": one.get("inbox") or "",
                    "link": _gmail_link(one.get("inbox") or "", thread or "")})
        if len(out) >= MOST_MAILS:
            break
    return out


def _sender(value) -> str:
    value = str(value or "").strip()
    found = re.match(r'^\s*"?([^"<]+?)"?\s*<[^>]+>\s*$', value)
    return (found.group(1) if found else value)[:80]


async def note(who, event: dict, *, services=None) -> dict:
    """The note for one event: {ok, people: [...], inboxes: [...]}, or {ok, off} when switched off.

    `event` is one as `google_api.Calendar` gives it. `services` is the person's
    Google services, whose Gmail is Rouh's own inbox; None leaves Rouh's inbox out.
    """
    from asgiref.sync import sync_to_async

    if not await sync_to_async(on)(who):
        return {"ok": True, "off": True, "people": []}
    own = await sync_to_async(own_addresses)(who)
    guests = worth_noting(event, own, own_domains(own))[:MOST_PEOPLE]
    if not guests:
        return {"ok": True, "people": [], "inboxes": []}
    people = [await sync_to_async(_who_they_are)(who, one) for one in guests]
    readers = await sync_to_async(_mailboxes)(who)
    if services is not None:
        from . import inboxes

        rouh = await sync_to_async(inboxes.rouh_address)(who)
        if rouh not in [inbox for inbox, _ in readers]:
            readers.append((rouh, services.gmail))
    note_said = ""
    try:
        mails = await asyncio.wait_for(
            asyncio.gather(*(_mails_with(one["emails"], readers)
                             for one in people)), SECONDS)
    except asyncio.TimeoutError:
        mails = [[] for _ in people]
        note_said = "The mail could not be searched in time, so the last emails are not here."
    for person, theirs in zip(people, mails):
        person["mails"] = theirs
    return {"ok": True, "people": people, "inboxes": [inbox for inbox, _ in readers],
            "note": note_said}


# --- on the phone, an hour before -------------------------------------------


def _day_said(moment: datetime, now: datetime) -> str:
    gap = (moment.date() - now.date()).days
    return "" if gap == 0 else ("tomorrow " if gap == 1 else moment.strftime("%A "))


def phone_text(event: dict, made: dict, now: datetime, link: str) -> str:
    """The Telegram message: when and what, then a line a person, then the link."""
    start = event["start"]
    minutes = max(1, round((start - now).total_seconds() / 60))
    lines = [f"🤝 In {minutes} min, {_day_said(start, now)}{start:%H:%M}: {event['title']}"]
    for person in made.get("people") or []:
        line = "• " + person["name"]
        if person.get("organisation"):
            line += f", {person['organisation']}"
        if not person.get("known"):
            line += " (not in your contacts)"
        last = (person.get("mails") or [None])[0]
        if last:
            when = clock.moment(last["at"]) if last.get("at") else None
            line += (f". Last email{' ' + f'{when.day} {when:%b}' if when else ''}: "
                     f"“{last['subject'][:90]}”")
        else:
            line += ". No email with them yet."
        lines.append(line)
    if link:
        lines.append("Before you meet: " + link)
    return "\n".join(lines)


def event_link(public_url: str, event: dict) -> str:
    """The brief, with this event open (`briefpage.js` reads `#event=`)."""
    from urllib.parse import quote

    from . import addressing

    if not public_url:
        return ""
    return (public_url.rstrip("/") + addressing.BRIEF + "#event="
            + quote(f"{event['calendar_id']}:{event['id']}", safe=""))


def sent_of(who) -> dict:
    from .models import UserSetting

    value = (UserSetting.objects.filter(user_id=str(who.user_id), org_id=who.org_id or "",
                                        name=SENT).values_list("value", flat=True).first())
    try:
        held = json.loads(value) if value else {}
    except (TypeError, ValueError):
        held = {}
    return held if isinstance(held, dict) else {}


def mark_sent(who, key: str) -> None:
    from .models import UserSetting

    now = time.time()
    held = {k: v for k, v in sent_of(who).items()
            if isinstance(v, (int, float)) and now - v < KEEP_SENT}
    held[key] = now
    UserSetting.objects.bulk_create(
        [UserSetting(user_id=str(who.user_id), org_id=who.org_id or "", name=SENT,
                     value=json.dumps(held), updated_at=now)],
        update_conflicts=True, unique_fields=["user_id", "name"],
        update_fields=["org_id", "value", "updated_at"])


def event_key(event: dict) -> str:
    """One meeting, whichever calendar it was read from: its own id and when it starts."""
    start = event.get("start")
    return f"{event.get('id') or ''}@{int(start.timestamp()) if isinstance(start, datetime) else ''}"


class Notes:
    """The loop that sends each outside meeting's note to the phone, an hour before it.

    It wakes once a minute, like the morning brief's (`morning_brief.Mornings`),
    and only for the person the bot's phone belongs to, with the switch on and
    Google connected. An event already noted is never noted again.
    """

    def __init__(self, *, tenancy, telegram, public_url: str, google=None) -> None:
        self.tenancy = tenancy
        self.telegram = telegram
        self.public_url = (public_url or "").rstrip("/")
        self.google = google
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.get_running_loop().create_task(self._run())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None

    async def _run(self) -> None:
        await asyncio.sleep(30)
        while True:
            try:
                await self.beat()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("the meeting notes' beat failed")
            await asyncio.sleep(60)

    def _owner(self):
        from .telegram import phone_owner

        owner = phone_owner(self.tenancy)
        if owner is None or not on(owner):
            return None
        return owner

    async def beat(self) -> list[str]:
        """One look at the next hour. The titles of the meetings noted."""
        from asgiref.sync import sync_to_async

        from . import notices

        if self.google is None or self.telegram is None or not self.telegram.configured():
            return []
        who = await sync_to_async(self._owner)()
        if who is None:
            return []
        zone = clock.zone_of(who)
        now = datetime.now(zone)
        with clock.person(who, zone):
            services = self.google(who)
            try:
                got = await services.calendar.events(now, now + timedelta(seconds=LEAD))
            except Exception as exc:  # noqa: BLE001 - not connected, or Google said no
                log.info("the calendar could not be read for meeting notes: %s", exc)
                return []
            own = await sync_to_async(own_addresses)(who)
            domains = own_domains(own)
            sent = await sync_to_async(sent_of)(who)
            noted, seen = [], set()
            for event in got.get("events") or []:
                start = event.get("start")
                key = event_key(event)
                if (not isinstance(start, datetime) or start <= now or key in sent
                        or key in seen or not worth_noting(event, own, domains)):
                    continue
                seen.add(key)
                made = await note(who, event, services=services)
                if made.get("off") or not made.get("people"):
                    continue
                text = phone_text(event, made, datetime.now(zone),
                                  event_link(self.public_url, event))
                # On his screen first, and on the phone if it is left there
                # (`rouh/notices.py`).
                if await notices.phone(text, kind="meeting", who=who,
                                       key=f"meeting_prep:{key}") is None:
                    log.warning("a meeting note could not be given")
                    continue
                await sync_to_async(mark_sent)(who, key)
                log.info("sent the note before %r to the phone", event["title"])
                noted.append(event["title"])
        return noted


async def note_for_event(who, *, google, zone, calendar_id, event_id) -> dict:
    """The note for one event of the brief, read again from Google."""
    from .morning_brief import Refused, _event_ids, _services

    calendar_id, event_id = _event_ids(calendar_id, event_id)
    zone = zone or clock.zone_of(who)
    with clock.person(who, zone):
        services = _services(who, google)
        from asgiref.sync import sync_to_async

        if not await sync_to_async(on)(who):
            return {"ok": True, "off": True, "people": []}
        try:
            event = await services.calendar.event(calendar_id, event_id)
        except Exception as exc:  # noqa: BLE001
            raise Refused("The event could not be read again from Google just now.") from exc
        made = await note(who, event, services=services)
        if made.get("people"):
            from . import evolution

            await sync_to_async(evolution.used)(SWITCH, "meeting_opened", who=who,
                                                detail=f"{len(made['people'])} from outside at "
                                                       f"{str(event.get('title') or 'a meeting')[:80]}")
        return made


__all__ = ["LEAD", "Notes", "SWITCH", "TITLE", "event_key", "event_link", "note",
           "note_for_event", "outsiders", "own_addresses", "own_domains", "phone_text",
           "worth_noting"]
