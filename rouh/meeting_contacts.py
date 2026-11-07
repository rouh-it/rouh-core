"""Everybody he meets, in his contacts: the guests of his calendar meetings added to his iCloud.

Petar, by voice, 22 October 2026: "add everyone under 20 people in meeting. no family, ignore
things not people." That sentence is the standing permission for this pass, and for nothing
else: every other write to iCloud is still `save_contact`, shown first and saved on his word.

So a pass runs over his own calendar, by itself, and adds each guest he has met to his iCloud
contacts, through the very write `save_contact` makes (`ContactDesk.save`):

1. **The meetings.** Only his own calendar - the one whose id is his account's address (or the
   setting `ROUH_MEETING_CONTACTS_CALENDARS`) - read from Google, each occurrence of a repeating
   meeting on its own. A shared family calendar, an old company one and a free-and-busy one are
   never read. A cancelled meeting, or one he declined, is passed over, and so is a meeting of
   `LARGE` people or more, counted as `meeting_people.headcount` counts them (him included,
   rooms left out, a list with no size given taken as large).
2. **People only.** Not him and not Rouh (`meeting_prep.own_addresses`, and an address's
   +tag is taken off first), no room or resource, no group, list or shared mailbox
   (`meeting_people.skip_why`, and `NOT_PEOPLE` for notifications), no note taker or bot
   (`BOTS`), and nobody his family: a guest whose relationship in Rouh says so (`FAMILY`).
3. **Never twice.** Somebody who already has a card in iCloud, by any of its addresses, is
   left as they are, and nothing on an existing card is ever changed. Somebody whose card he
   deleted from the phone is not put back, and neither is somebody this pass added before
   (the setting `meeting_contacts`, `added`).
4. **The card.** The guest's name as the invitation gives it, else as Rouh knows them (LinkedIn
   research, their Synapse person), else out of their address (tomasz.wisniewski becomes Tomasz
   Wisniewski); their organisation from the research, else from their address's domain (not a
   public mail service); the address labelled work; and the note "Added by Rouh from the
   calendar: <meeting>, <date>", so that every card this made can be found and removed together.
   The card iCloud keeps lands on the guest's person in Synapse Master (`contacts.keep`), so
   Rouh's person and the phone's card are one.

5. **Who they are.** Everybody it adds is then looked up on LinkedIn, a queue drained slowly in
   the background by the meeting guests' own lookup (`drain`, under "who they are, from LinkedIn"
   below), and kept on Rouh's contact alone, never on the iCloud card.

**When.** Once, over the last `BACKFILL_DAYS` days (`backfill`); then by itself every `BEAT`
and `SOON` after the calendar sync stored a change (`poke`, from `calsync`), over the meetings
from `BEHIND_DAYS` ago to `AHEAD_DAYS` ahead, so a guest is added as soon as the invitation is
on the calendar.

**What is said.** Nothing, when it works (Petar's principle N1). Each pass that added somebody
or failed is kept in the setting's `log`, who was added from which meeting, and each card in
`contacts-writes.log` beside every other write to iCloud. `manage.py meeting_contacts status`
reads both.

**Its switch** is `meeting_contacts` (`rouh/switches.py`): off, the pass does nothing.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from . import meeting_people as mp

log = logging.getLogger("rouh.meeting_contacts")

#: The feature's switch (`rouh/switches.py`).
SWITCH = "meeting_contacts"
TITLE = "Everybody from his meetings of fewer than twenty people, added to his iCloud contacts"

#: A meeting with this many people invited or more is not one to add the people of. Petar,
#: 22 October 2026: "everyone under 20 people in meeting". The same count as the LinkedIn pass.
LARGE = int(os.environ.get("ROUH_MEETING_CONTACTS_LARGE") or 20)
#: How far back the one backfill reads, and the window every later pass reads, in days.
BACKFILL_DAYS = 365
BEHIND_DAYS = 7
AHEAD_DAYS = 90
#: How often the pass runs by itself, and how soon after the calendar changed, in seconds.
BEAT = 60 * 60
SOON = 150
#: How many days of calendar one listing asks for (Google lists at most 250 at a time).
CHUNK_DAYS = 30
#: The setting this keeps, per person (`user_settings`), and how many passes its log keeps.
SETTING = "meeting_contacts"
LOG_KEPT = 200
#: The first words of every note this writes: how the cards it made are found again.
NOTE_HEAD = "Added by Rouh from the calendar"

#: An address that is a notification, not a person, by its part before the @ (the rest of the
#: shared mailboxes and lists are `meeting_people`'s own).
NOT_PEOPLE = re.compile(
    r"^(?:calendar[-_.]?notifications?|notifications?|notify|alerts?|mailer[-_.]?daemon|postmaster|"
    r"newsletters?|updates|bounces?|reply|do[-_.]?not[-_.]?reply|no[-_.]?reply.*|noreply.*|career|"
    r"recruit\w*|hiring|talent|cohort\w*|founders|investors|office|reception|front[-_.]?desk|"
    r"meetings?|bookings?|scheduling|schedule|webinars?|community|hi|hey)$", re.I)
#: An address a calendar writes for somebody, not one that reaches them: Apple's invitation relay,
#: and the stand-in Microsoft gives an account with no mailbox.
RELAY = re.compile(r"@imip\.me\.com$|@calendar\.icloud\.com$|^outlook_[0-9a-f]{12,}@outlook\.com$", re.I)
#: A note taker, a recorder or another bot that joins meetings, by its address or its name.
BOT_DOMAINS = re.compile(
    r"@(?:[a-z0-9-]+\.)?(?:fireflies\.ai|otter\.ai|read\.ai|fathom\.video|fathom\.ai|tldv\.io|tl-dv\.io|"
    r"meetgeek\.ai|avoma\.com|recall\.ai|supernormal\.com|tactiq\.io|krisp\.ai|grain\.com|grain\.co|"
    r"airgram\.io|notta\.ai|sembly\.ai|jamie\.ai|bluedothq\.com|vowel\.com|claap\.io|"
    r"rewatch\.com|fellow\.app|modjo\.ai|gong\.io|chorus\.ai|bot\.[a-z.]+)$", re.I)
BOT_LOCAL = re.compile(
    r"(?:^|[._+-])(?:bot|notetaker|note[-_.]?taker|recorder|transcriber|assistant|fireflies|"
    r"otter|fathom|tldv|meetgeek|recall)(?:$|[._+-])", re.I)
BOT_NAME = re.compile(
    r"\b(?:bot|notetaker|note\s*taker|recorder|transcri(?:ber|ption)|fireflies|otter(?:\.ai)?|"
    r"read\.ai|fathom|tl;?dv|meetgeek|avoma|recall\.ai|supernormal|tactiq|krisp|zoom\s+(?:ai|bot)|"
    r"teams\s+(?:bot|recorder)|meet\s+(?:bot|recorder)|ai\s+(?:assistant|companion))\b", re.I)
#: What a relationship says when the person is his family.
FAMILY = re.compile(
    r"\b(?:family|wife|husband|spouse|partner in life|girlfriend|boyfriend|fianc[eé]e?|son|"
    r"daughter|father|mother|dad|daddy|mum|mom|papi|mameto|brother|sister|sibling|"
    r"grand(?:father|mother|son|daughter|ma|pa|parents?)|granny|uncle|aunt|auntie|cousin|"
    r"niece|nephew|in-law|stepson|stepdaughter|stepfather|stepmother)\b", re.I)


# --- small things ------------------------------------------------------------------------------


def on(who) -> bool:
    from . import switches

    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def _bare(address: str) -> str:
    """An address without its +tag: rouh+invoices@ is rouh@."""
    address = mp._addr(address)
    if "@" not in address:
        return address
    local, domain = address.split("@", 1)
    return f"{local.split('+', 1)[0]}@{domain}"


def calendar_ids(who) -> list[str]:
    """His own calendar, and only it: the setting's ids, else the address on his account."""
    from . import inboxes

    said = [one.strip() for one in (os.environ.get("ROUH_MEETING_CONTACTS_CALENDARS") or "").split(",")
            if one.strip()]
    if said:
        return said
    own = inboxes.account_address(who)
    return [own] if own else []


def _held(who) -> dict:
    return mp._setting(who, SETTING)


def _put(who, value: dict) -> None:
    mp._put(who, SETTING, value)


def _day_of(event: dict) -> str:
    start = event.get("start")
    if isinstance(start, datetime):
        from . import clock

        with contextlib.suppress(Exception):
            start = start.astimezone(clock.zone())
    return f"{start.day} {start:%B %Y}" if start is not None and hasattr(start, "day") else ""


def note_for(event: dict) -> str:
    title = " ".join(str(event.get("title") or "a meeting with no title").split())
    day = _day_of(event)
    return f"{NOTE_HEAD}: {title}{', ' + day if day else ''}"


# --- who is not added ---------------------------------------------------------------------------


def not_a_person(guest: dict, own: set[str]) -> str:
    """Why a guest is not somebody to add, from the invitation alone, or "" for one who is."""
    address = mp._addr(guest.get("email"))
    name = " ".join(str(guest.get("name") or "").split())
    if not address or "@" not in address:
        return "no address"
    local = _bare(address).split("@", 1)[0]
    if (address in own or _bare(address) in own or guest.get("this_calendar") or guest.get("me")
            or (local in ("rouh", "rou") and any(_bare(address).endswith("@" + mp._domain(o)) for o in own))
            or _own_elsewhere(_bare(address), own)):
        return "his own or Rouh's"
    if guest.get("resource") or mp.NOT_A_PERSON.search(address) or mp.ROOM.search(name):
        return "a room or resource"
    if RELAY.search(address):
        return "a calendar's relay address"
    if BOT_DOMAINS.search(address) or BOT_LOCAL.search(local) or BOT_NAME.search(name):
        return "a note taker or bot"
    if NOT_PEOPLE.search(local) or mp.MAILBOX_LOCAL.search(local) or mp.is_group(address, name):
        return "a group, list or shared mailbox"
    return ""


def _own_elsewhere(address: str, own: set[str]) -> bool:
    """One of his own addresses at his company's other domain: p@example.com beside p@example.ai."""
    local, domain = address.split("@", 1)
    word = domain.split(".")[0]
    return any(o.split("@", 1)[0] == local and mp._domain(o).split(".")[0] == word
               and mp._domain(o) not in mp.PUBLIC_MAIL for o in own if "@" in o)


def meeting_skip(event: dict, calendars: set[str]) -> tuple[str, int]:
    """Why nobody of a meeting is added, or "", and how many people it has."""
    if calendars and str(event.get("calendar_id") or "").lower() not in calendars:
        return "not on his own calendar", 0
    if event.get("status") == "cancelled":
        return "cancelled", 0
    if event.get("my_response") == "declined":
        return "he declined it", 0
    count, why = mp.headcount(event)
    if count >= LARGE:
        return f"{LARGE} people or more ({count})", count
    if why:
        return f"too large: {why}", count
    return "", count


def is_family(person) -> bool:
    return bool(FAMILY.search(str(getattr(person, "relationship", "") or "")))


# --- the card ---------------------------------------------------------------------------------


def _a_name(said: str) -> str:
    """A name as an invitation writes it, made a name: "Rivera, Sam" is Sam Rivera, and what is in
    brackets or after a bar ("Sam Rivera | Example Fund", "(Example Bank)") is left out."""
    said = re.sub(r"\([^)]*\)|\[[^\]]*\]|<[^>]*>", " ", str(said or ""))
    said = re.split(r"\s+[|/•·]\s+", said)[0]
    said = " ".join(said.split()).strip(" ,;-|'\"")
    if "@" in said:
        return ""
    if said.count(",") == 1:
        last, first = (part.strip() for part in said.split(","))
        if first and last and not mp.NOT_NAME.match(first):
            said = f"{first} {last}"
    return said


def name_for(guest: dict, row: dict | None) -> str:
    """The invitation's name, else Rouh's (LinkedIn's, then the person's), else the address's."""
    meta = (row or {}).get("meta") or {}
    li = meta.get("linkedin") or {}
    shown = _a_name(guest.get("name"))
    if len(shown.split()) >= 2:
        return shown
    for said in ((li.get("name") if li.get("status") == mp.MATCHED else ""), meta.get("name"),
                 (row or {}).get("title")):
        said = _a_name(said)
        if len(said.split()) >= 2:
            return said
    first, last = mp.name_from_address(guest.get("email") or "")
    if last:
        return f"{first} {last}"
    if shown:
        return shown
    local = re.sub(r"[^a-z]+", " ", (guest.get("email") or "").split("@", 1)[0].split("+", 1)[0].lower())
    return " ".join(w.title() for w in local.split()) or (guest.get("email") or "")


def organisation_for(who, ds: dict, guest: dict, row: dict | None, own_domains: set[str]) -> str:
    """The research's company, else the person's own, else what the address's domain is called."""
    meta = (row or {}).get("meta") or {}
    li = meta.get("linkedin") or {}
    if li.get("status") == mp.MATCHED and li.get("company"):
        return str(li["company"])
    if meta.get("organisation"):
        return str(meta["organisation"])
    domain = mp._domain(mp._addr(guest.get("email")))
    if not domain or domain in mp.PUBLIC_MAIL:
        return ""
    held = dict(mp._setting(who, mp.DOMAINS).get(domain) or {})
    for one in list(held.get("learned") or []) + mp._contact_orgs(ds, domain) + [held.get("site") or ""]:
        if one and one.strip():
            return one.strip()
    label = domain.split(".")[-2] if domain.count(".") >= 1 else domain
    if label in ("co", "com", "org", "net", "ac", "gov") and domain.count(".") >= 2:
        label = domain.split(".")[-3]
    if len(label) < 2:
        return ""
    return label.upper() if len(label) <= 3 else label[:1].upper() + label[1:]


def _name_key(name: str) -> str:
    """A whole name, for telling whether two are the same person: two words or more, folded."""
    words = mp._fold(name).split()
    return " ".join(words) if len(words) >= 2 else ""


def _card_names(who) -> set[str]:
    """Every whole name on his iCloud cards."""
    from .synapse import contacts

    return {k for k in (_name_key(c.get("name") or "") for c in contacts.all_cards(str(who.user_id),
                                                                                    str(who.org_id))) if k}


# --- one pass ---------------------------------------------------------------------------------


@dataclass
class Report:
    """What one pass did, for the log and the command."""

    meetings: int = 0
    added: list = field(default_factory=list)
    would_add: list = field(default_factory=list)
    #: Meetings passed over, by why: {why: count}, and a few of each by title.
    meetings_skipped: dict = field(default_factory=dict)
    meetings_skipped_titles: dict = field(default_factory=dict)
    #: Guests passed over, by why: {why: count}, and a few of each by address.
    guests_skipped: dict = field(default_factory=dict)
    guests_skipped_who: dict = field(default_factory=dict)
    failed: list = field(default_factory=list)
    trouble: str = ""
    _seen: set = field(default_factory=set, repr=False)

    def skip_meeting(self, why: str, title: str) -> None:
        key = why.split(" (")[0] if why.startswith(str(LARGE)) else why.split(":")[0]
        self.meetings_skipped[key] = self.meetings_skipped.get(key, 0) + 1
        titles = self.meetings_skipped_titles.setdefault(key, [])
        if len(titles) < 12 and title not in titles:
            titles.append(title)

    def skip_guest(self, why: str, who: str) -> None:
        """One guest passed over, each address once however many meetings they were at."""
        address = who.rsplit("<", 1)[-1].rstrip(">")
        if address in self._seen:
            return
        self._seen.add(address)
        self.guests_skipped[why] = self.guests_skipped.get(why, 0) + 1
        people = self.guests_skipped_who.setdefault(why, [])
        if len(people) < 15 and who not in people:
            people.append(who)

    def said(self) -> str:
        if self.trouble:
            return self.trouble
        bits = [f"{self.meetings} meeting{'s' if self.meetings != 1 else ''} read"]
        if self.added:
            bits.append(f"{len(self.added)} added to the iCloud contacts")
        if self.would_add:
            bits.append(f"{len(self.would_add)} would be added")
        if self.failed:
            bits.append(f"{len(self.failed)} could not be added")
        if self.meetings_skipped:
            bits.append("meetings passed over: " + ", ".join(
                f"{n} {why}" for why, n in sorted(self.meetings_skipped.items())))
        if self.guests_skipped:
            bits.append("guests passed over: " + ", ".join(
                f"{n} {why}" for why, n in sorted(self.guests_skipped.items())))
        return "; ".join(bits) + "."


async def read_events(calendar, start: datetime, end: datetime, ids: list[str]) -> list[dict]:
    """Every occurrence between two moments on the calendars named, a month at a time, each
    listing split again while Google says it cut it short."""
    out: list[dict] = []

    async def window(a: datetime, b: datetime) -> None:
        got = await calendar.events(a, b, calendar_ids=ids, limit=mp_max())
        if got.get("cut") and b - a > timedelta(days=1):
            middle = a + (b - a) / 2
            await window(a, middle)
            await window(middle, b)
            return
        for line in got.get("trouble") or []:
            log.info("meeting contacts: %s", line)
        out.extend(got.get("events") or [])

    at = start
    while at < end:
        nxt = min(end, at + timedelta(days=CHUNK_DAYS))
        await window(at, nxt)
        at = nxt
    seen, events = set(), []
    for event in sorted(out, key=lambda e: mp._start_of(e) or datetime.max.replace(tzinfo=timezone.utc)):
        key = (event.get("calendar_id"), mp.event_key(event))
        if key not in seen:
            seen.add(key)
            events.append(event)
    return events


def mp_max() -> int:
    from .google_api.calendar import MAX_EVENTS_LISTED

    return MAX_EVENTS_LISTED


_running = threading.Lock()


async def run(who, *, calendar, desk, start: datetime | None = None, end: datetime | None = None,
              events: list[dict] | None = None, dry: bool = False, kind: str = "pass",
              most: int | None = None, wait: bool = False) -> Report:
    """One pass over his meetings between `start` and `end` (or `events`): each guest who is a
    person, not his family and not in his contacts yet, added to iCloud. With `dry`, nothing is
    written anywhere and `would_add` says who would be. One pass at a time."""
    from . import meeting_prep
    from .people import People

    report = Report()
    deadline = time.monotonic() + (600 if wait else 0)
    while not _running.acquire(blocking=False):
        if time.monotonic() >= deadline:
            report.trouble = "A pass over the meetings' guests is already running."
            return report
        await asyncio.sleep(1)
    try:
        ids = calendar_ids(who)
        if not ids:
            report.trouble = "There is no calendar of his own to read: his account has no address."
            return report
        if not dry:
            blocked = await asyncio.to_thread(desk.not_ready_because, who) if desk is not None \
                else "Apple Contacts are not set up on this machine."
            if blocked:
                report.trouble = blocked
                return report
        if events is None:
            now = datetime.now(timezone.utc)
            start = start or now - timedelta(days=BEHIND_DAYS)
            end = end or now + timedelta(days=AHEAD_DAYS)
            events = await read_events(calendar, start, end, ids)
        own = await asyncio.to_thread(meeting_prep.own_addresses, who)
        own = own | {_bare(one) for one in own}
        domains = meeting_prep.own_domains(own)
        ds = await asyncio.to_thread(mp._ds, who)
        held = await asyncio.to_thread(_held, who)
        added_before = dict(held.get("added") or {})
        people = People()
        chosen: dict[str, tuple[dict, dict, dict | None]] = {}
        calendars = {one.lower() for one in ids}
        for event in events:
            title = " ".join(str(event.get("title") or "").split()) or "(no title)"
            why, _ = meeting_skip(event, calendars)
            if why:
                report.skip_meeting(why, title)
                continue
            report.meetings += 1
            for guest in event.get("guests") or []:
                address = mp._addr(guest.get("email"))
                if address in chosen:
                    continue
                said = f"{guest.get('name') or ''} <{address}>".strip()
                why = not_a_person(guest, own)
                if why:
                    report.skip_guest(why, said)
                    continue
                if address in added_before:
                    report.skip_guest("added by this pass before", said)
                    continue
                found = await asyncio.to_thread(people.by_address, str(who.user_id), str(who.org_id), address)
                if any(p.is_me for p in found):
                    report.skip_guest("his own or Rouh's", said)
                    continue
                if any(is_family(p) for p in found):
                    report.skip_guest("family", said)
                    continue
                if any(p.card is not None for p in found):
                    report.skip_guest("already in his contacts", said)
                    continue
                rows = [await asyncio.to_thread(mp._row, ds, p.id) for p in found if p.id]
                rows = [r for r in rows if r is not None]
                if any((r.get("meta") or {}).get("icloud_gone") for r in rows):
                    report.skip_guest("deleted from his contacts before", said)
                    continue
                chosen[address] = (guest, event, rows[0] if rows else None)
        names_held = await asyncio.to_thread(_card_names, who)
        plans: list[dict] = []
        by_name: dict[str, dict] = {}
        for address, (guest, event, row) in chosen.items():
            name = name_for(guest, row)
            said = f"{name} <{address}>"
            key = _name_key(name)
            if key and key in names_held:
                # Somebody of that whole name is in his contacts already: the same person at
                # another address, most likely, and an existing card is never changed.
                report.skip_guest("a contact of that name is there already", said)
                continue
            if key and key in by_name:
                # One person at two addresses in his meetings: one card with both.
                by_name[key]["also"].append(address)
                continue
            plan = {"email": address, "also": [], "name": name,
                    "organisation": await asyncio.to_thread(organisation_for, who, ds, guest, row, domains),
                    "meeting": " ".join(str(event.get("title") or "").split()), "date": _day_of(event),
                    "note": note_for(event), "pid": str(row["id"]) if row else "",
                    "about": " ".join(str(event.get(k) or "") for k in ("description", "where"))[:2000]}
            if key:
                by_name[key] = plan
            plans.append(plan)
        if most is not None:
            plans = plans[:max(0, int(most))]
        if dry:
            report.would_add = plans
            return report
        if plans:
            # The duplicates are judged on the cards as iCloud has them now.
            outcome = await desk.sync(who)
            if getattr(outcome, "error", ""):
                report.trouble = f"iCloud could not be read first: {outcome.error}"
                return report
        for plan in plans:
            found = await asyncio.to_thread(people.by_address, str(who.user_id), str(who.org_id), plan["email"])
            if any(p.card is not None for p in found):
                report.skip_guest("already in his contacts", f"{plan['name']} <{plan['email']}>")
                continue
            args = {"name": plan["name"],
                    "add_emails": [{"address": one, "label": "work"} for one in [plan["email"], *plan["also"]]],
                    "note": plan["note"], "confirmed": True}
            if plan["organisation"]:
                args["organisation"] = plan["organisation"]
            try:
                said = await desk.save(args, who=who)
            except Exception as exc:  # noqa: BLE001 - one card never stops the others
                log.exception("meeting contacts: %s could not be added", plan["email"])
                report.failed.append({**plan, "why": f"{type(exc).__name__}: {exc}"})
                continue
            found = await asyncio.to_thread(people.by_address, str(who.user_id), str(who.org_id), plan["email"])
            card = next((p for p in found if p.card is not None), None)
            if card is None:
                report.failed.append({**plan, "why": " ".join(str(said.text or "").split())[:300]})
                continue
            done = {**plan, "pid": card.id, "at": round(time.time(), 1)}
            report.added.append(done)
            await asyncio.to_thread(_mark_added, who, done)
        if report.added:
            from . import evolution

            await asyncio.to_thread(evolution.used, SWITCH, "added", who=who,
                                    detail=f"{len(report.added)} added from the calendar")
        return report
    finally:
        with contextlib.suppress(Exception):
            if not dry and (report.added or report.failed or kind == "backfill"):
                await asyncio.to_thread(_keep_log, who, report, kind)
        if report.added or report.failed or report.trouble or kind == "backfill":
            log.info("meeting contacts (%s%s): %s", kind, ", dry run" if dry else "", report.said())
        _running.release()


_setting_lock = threading.Lock()


def _mark_added(who, done: dict) -> None:
    """One card added, kept at once, so a pass cut short never adds them again."""
    with _setting_lock:
        held = _held(who)
        added = dict(held.get("added") or {})
        for address in [done["email"], *done.get("also", [])]:
            added[address] = {"name": done["name"], "pid": done["pid"], "meeting": done["meeting"],
                              "date": done["date"], "at": done["at"]}
        held["added"] = added
        _put(who, held)
    # And looked up on LinkedIn, in the queue's turn.
    enqueue(who, [done])


def _keep_log(who, report: Report, kind: str) -> None:
    with _setting_lock:
        held = _held(who)
        entry = {"at": round(time.time(), 1), "kind": kind, "said": report.said(),
                 "added": [{k: a.get(k) for k in ("name", "email", "also", "organisation", "meeting", "date", "pid")}
                           for a in report.added],
                 "failed": [{k: f.get(k, "") for k in ("name", "email", "meeting", "why")} for f in report.failed],
                 "meetings_skipped": report.meetings_skipped, "guests_skipped": report.guests_skipped}
        held["log"] = (list(held.get("log") or []) + [entry])[-LOG_KEPT:]
        if kind == "backfill" and not report.trouble:
            held["backfilled_at"] = entry["at"]
        _put(who, held)


async def backfill(who, *, calendar, desk, dry: bool = False, most: int | None = None) -> Report:
    """The once-only pass over the last `BACKFILL_DAYS` days, and the window ahead with it."""
    now = datetime.now(timezone.utc)
    return await run(who, calendar=calendar, desk=desk, start=now - timedelta(days=BACKFILL_DAYS),
                     end=now + timedelta(days=AHEAD_DAYS), dry=dry, kind="backfill", most=most, wait=True)


# --- who they are, from LinkedIn -----------------------------------------------------------
#
# Petar, by voice, 22 October 2026: "Did you make sure those contacts get researched in LinkedIn?
# If not please do it." So everybody this pass adds is looked up on LinkedIn by the very lookup
# the meeting guests' pass makes (`meeting_people.research`): their name with the organisation
# behind their address, kept on Rouh's own contact only when the name and the company agree,
# and otherwise left with the candidates on their contact for his pick. Nothing of it is written
# to iCloud: `meeting_people.save_match` writes Synapse alone (`contacts.write`).
#
# They are a queue (the setting `RESEARCH`): the backfill's 273 and every guest an hourly pass
# adds after them, one person at a time with `RESEARCH_GAP` between, within an allowance of
# HarvestAPI runs a day of its own (`RESEARCH_DAILY_CALLS`), so it never takes the next week's
# guests' lookups from them. Whoever drains it holds a lease on it (`RESEARCH_LEASE`), so Rouh
# and a command run beside it never look the same person up twice, and a restart carries on
# where it stopped, because each person leaves the queue only once their answer is kept.

#: The queue, what became of each person, and the lease (`user_settings`).
RESEARCH = "meeting_contacts_research"
#: Where its HarvestAPI runs are counted, apart from the meeting guests' pass (`meeting_people.Budget`).
RESEARCH_CALLS = "meeting_contacts_research_calls"
#: The most HarvestAPI runs the queue spends in a UTC day: a person is three to seven.
RESEARCH_DAILY_CALLS = int(os.environ.get("ROUH_MEETING_CONTACTS_RESEARCH_CALLS") or 1500)
#: Seconds between one person and the next, so HarvestAPI is never asked in a burst.
RESEARCH_GAP = float(os.environ.get("ROUH_MEETING_CONTACTS_RESEARCH_GAP") or 30)
#: How long a lease on the queue holds without being renewed, in seconds.
RESEARCH_LEASE = 15 * 60
#: How many times somebody LinkedIn failed for is tried, `meeting_people.FAILED_AGAIN` apart.
RESEARCH_TRIES = 3
#: After this many failures one after another, the queue rests for `RESEARCH_REST` seconds.
RESEARCH_FAILS_IN_A_ROW, RESEARCH_REST = 3, 3600
#: What one person costs, about, in dollars: a search of three runs, a second one of three when
#: the first found nobody, and a profile (`meeting_people.PRICE`).
RESEARCH_EACH = 0.028
#: The most the backfill spends by itself, in dollars (Petar, 22 October 2026): above it, only the
#: people of the last `RECENT_DAYS` days are queued, and the rest are held with what they would cost.
RESEARCH_SPEND_MOST = 50.0
RECENT_DAYS = 90
#: How many contacts waiting for his pick make it worth one question for them all.
MANY_WAITING = 5


def _research_held(who) -> dict:
    return mp._setting(who, RESEARCH)


def _research_change(who, change):
    """The queue's setting changed under a row lock, so Rouh and a command run beside it never
    write over each other. Answers what `change` answers."""
    from django.db import IntegrityError, transaction

    from .models import UserSetting

    mine = {"user_id": str(who.user_id), "name": RESEARCH}
    with contextlib.suppress(IntegrityError), transaction.atomic():
        UserSetting.objects.get_or_create(**mine, defaults={"org_id": who.org_id or "", "value": "{}",
                                                            "updated_at": time.time()})
    with transaction.atomic():
        value = UserSetting.objects.select_for_update().filter(**mine).values_list("value", flat=True).first()
        try:
            held = json.loads(value) if value else {}
        except (TypeError, ValueError):
            held = {}
        if not isinstance(held, dict):
            held = {}
        out = change(held)
        UserSetting.objects.filter(**mine).update(value=json.dumps(held), org_id=who.org_id or "",
                                                  updated_at=time.time())
    return out


def _met_on(said: str) -> float:
    """The day a card's meeting was, as `_day_of` wrote it ("27 March 2026"), as a moment, or 0."""
    try:
        return datetime.strptime(str(said or ""), "%d %B %Y").replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        return 0.0


def enqueue(who, entries: list[dict]) -> int:
    """People to look up on LinkedIn: {pid, email, name, meeting, date, about}. Somebody queued
    or looked up by the queue before is not queued again. How many were queued."""
    def change(held: dict) -> int:
        queue = dict(held.get("queue") or {})
        done = held.get("done") or {}
        n = 0
        for one in entries:
            pid = str(one.get("pid") or "")
            if not pid or pid in queue or pid in done:
                continue
            queue[pid] = {k: one.get(k) or "" for k in ("email", "name", "meeting", "date")}
            queue[pid]["about"] = str(one.get("about") or "")[:2000]
            queue[pid]["queued_at"] = round(time.time(), 1)
            n += 1
        held["queue"] = queue
        return n

    return _research_change(who, change)


def queue_backfill(who) -> dict:
    """Everybody this pass added before the queue was, queued once: all of them when that costs
    no more than `RESEARCH_SPEND_MOST`, else those met in the last `RECENT_DAYS` days, and the rest
    held, with what they would cost. What it did."""
    if _research_held(who).get("backfill_queued_at"):
        return {"queued": 0, "already": True}
    added = _held(who).get("added") or {}
    by_pid: dict[str, dict] = {}
    for address, one in added.items():
        pid = str(one.get("pid") or "")
        if pid and pid not in by_pid:
            by_pid[pid] = {"pid": pid, "email": address, "name": one.get("name") or "",
                           "meeting": one.get("meeting") or "", "date": one.get("date") or ""}
    entries = list(by_pid.values())
    held_back: list[dict] = []
    estimate = round(len(entries) * RESEARCH_EACH, 2)
    if estimate > RESEARCH_SPEND_MOST:
        since = time.time() - RECENT_DAYS * 86400
        held_back = [e for e in entries if _met_on(e["date"]) < since]
        entries = [e for e in entries if _met_on(e["date"]) >= since]
    n = enqueue(who, entries)

    def mark(held: dict) -> None:
        held["backfill_queued_at"] = round(time.time(), 1)
        held["held_back"] = {e["pid"]: e for e in held_back}
        held["held_back_cost"] = round(len(held_back) * RESEARCH_EACH, 2)

    _research_change(who, mark)
    log.info("meeting contacts: %d contacts queued for LinkedIn (about $%.2f), %d held back", n,
             n * RESEARCH_EACH, len(held_back))
    return {"queued": n, "estimate": estimate, "held_back": len(held_back),
            "held_back_cost": round(len(held_back) * RESEARCH_EACH, 2)}


def why_not_research(meta: dict) -> str:
    """Why a contact is not looked up now, or "": somebody with research of any age is left as
    they are (Petar, 22 October 2026), and so is somebody the lookup answered lately."""
    if str(meta.get("research") or "").strip():
        return "researched already"
    return mp.due(meta)


def _lease(who, token: str, *, let_go: bool = False) -> bool:
    """Take or renew the lease on the queue for `token`, or let it go. Whether it is `token`'s."""
    def change(held: dict) -> bool:
        now = time.time()
        lease = held.get("lease") or {}
        if lease.get("by") and lease.get("by") != token and float(lease.get("until") or 0) > now:
            return False
        if let_go:
            held.pop("lease", None)
        else:
            held["lease"] = {"by": token, "until": round(now + RESEARCH_LEASE, 1)}
        return True

    return _research_change(who, change)


def _next_due(held: dict, now: float) -> tuple[str, dict] | None:
    queue = held.get("queue") or {}
    ready = [(float(one.get("not_before") or 0), float(one.get("queued_at") or 0), pid)
             for pid, one in queue.items() if float(one.get("not_before") or 0) <= now]
    if not ready:
        return None
    _, _, pid = min(ready)
    return pid, dict(queue[pid])


def _settle(who, pid: str, entry: dict, result: dict, cost: float) -> None:
    """One person's answer kept, and them out of the queue, or back in it for later."""
    status = result.get("status") or ""

    def change(held: dict) -> None:
        queue = dict(held.get("queue") or {})
        done = dict(held.get("done") or {})
        held["spent"] = round(float(held.get("spent") or 0) + cost, 4)
        held["looked_up"] = int(held.get("looked_up") or 0) + (1 if cost else 0)
        tries = int(entry.get("tries") or 0) + 1
        if status == "capped" or (status == mp.FAILED and tries < RESEARCH_TRIES):
            queue[pid] = {**entry, "tries": tries if status == mp.FAILED else entry.get("tries", 0),
                          "not_before": round(time.time() + (mp.FAILED_AGAIN if status == mp.FAILED else 0), 1),
                          "why": str(result.get("why") or status)[:300]}
            held["fails_in_a_row"] = int(held.get("fails_in_a_row") or 0) + (status == mp.FAILED)
        else:
            queue.pop(pid, None)
            done[pid] = {"status": status, "name": result.get("name") or entry.get("name") or "",
                         "email": entry.get("email") or "", "at": round(time.time(), 1),
                         "cost": round(cost, 4), "why": str(result.get("why") or "")[:300],
                         "url": result.get("url") or ""}
            held["fails_in_a_row"] = 0
        held["queue"], held["done"] = queue, done

    _research_change(who, change)


async def research_one(who, apify, budget, pid: str, entry: dict) -> dict:
    """One contact looked up, through the meeting guests' own lookup, and what became of them."""
    ds = await asyncio.to_thread(mp._ds, who)
    row = await asyncio.to_thread(mp._row, ds, pid)
    if row is None:
        return {"status": "gone", "name": entry.get("name") or ""}
    meta = row.get("meta") or {}
    why = why_not_research(meta)
    if why:
        return {"status": "skipped", "why": why, "name": row.get("title") or ""}
    guest = {"email": entry.get("email") or next(iter(meta.get("emails") or []), ""),
             "name": entry.get("name") or ""}
    event = {"title": entry.get("meeting") or "", "description": entry.get("about") or ""}
    return await mp.research(who, apify, budget, ds=ds, pid=pid, guest=guest, event=event,
                             person_name=row.get("title") or "")


async def drain(who, apify, *, most: int | None = None, gap: float | None = None,
                token: str = "", stop: asyncio.Event | None = None) -> dict:
    """Look up the queue's people one at a time until it is empty, the day's runs are spent,
    `most` people are done, or `stop` is set. What it did."""
    from . import linkedin

    gap = RESEARCH_GAP if gap is None else gap
    token = token or f"{os.uname().nodename}:{os.getpid()}:{id(asyncio.current_task())}"
    out = {"looked_up": 0, "results": [], "cost": 0.0, "stopped": ""}
    if apify is None or not apify.ready():
        out["stopped"] = "LinkedIn research is not set up on this machine: there is no Apify key."
        return out
    if not await asyncio.to_thread(_lease, who, token):
        out["stopped"] = "the queue is being looked up already, elsewhere"
        return out
    try:
        while most is None or out["looked_up"] < most:
            if stop is not None and stop.is_set():
                out["stopped"] = "stopped"
                break
            held = await asyncio.to_thread(_research_held, who)
            if int(held.get("fails_in_a_row") or 0) >= RESEARCH_FAILS_IN_A_ROW and \
                    time.time() - float(held.get("rest_from") or 0) > RESEARCH_REST:
                await asyncio.to_thread(_research_change, who, lambda h: h.update(
                    {"rest_from": round(time.time(), 1), "fails_in_a_row": 0}))
                out["stopped"] = f"LinkedIn failed {RESEARCH_FAILS_IN_A_ROW} times running; resting an hour"
                break
            if time.time() - float(held.get("rest_from") or 0) < RESEARCH_REST:
                out["stopped"] = "resting after LinkedIn failed"
                break
            nxt = _next_due(held, time.time())
            if nxt is None:
                out["stopped"] = "the queue is empty" if not held.get("queue") else "nobody is due yet"
                break
            budget = await asyncio.to_thread(mp.Budget, who, RESEARCH_DAILY_CALLS, RESEARCH_CALLS)
            if not budget.can(linkedin.TRIES):
                out["stopped"] = "the day's HarvestAPI runs for the queue are spent"
                break
            pid, entry = nxt
            try:
                result = await research_one(who, apify, budget, pid, entry)
            except Exception as exc:  # noqa: BLE001 - one person never stops the queue
                log.exception("meeting contacts: %s could not be looked up on LinkedIn", entry.get("email"))
                result = {"status": mp.FAILED, "why": f"{type(exc).__name__}: {exc}"}
            finally:
                await asyncio.to_thread(budget.save)
            await asyncio.to_thread(_settle, who, pid, entry, result, budget.spent_cost)
            await asyncio.to_thread(_lease, who, token)
            out["cost"] = round(out["cost"] + budget.spent_cost, 4)
            out["results"].append({"pid": pid, "name": result.get("name") or entry.get("name"),
                                   "email": entry.get("email"), "status": result.get("status"),
                                   "why": result.get("why") or "", "url": result.get("url") or "",
                                   "headline": result.get("headline") or "",
                                   "confidence": result.get("confidence") or "",
                                   "cost": budget.spent_cost})
            if budget.spent_cost:
                out["looked_up"] += 1
                log.info("meeting contacts: %s on LinkedIn: %s ($%.3f)", entry.get("email"),
                         result.get("status"), budget.spent_cost)
            if result.get("status") == "capped":
                out["stopped"] = "the day's HarvestAPI runs for the queue are spent"
                break
            if budget.spent_cost and gap:
                if stop is not None:
                    with contextlib.suppress(asyncio.TimeoutError):
                        await asyncio.wait_for(stop.wait(), gap)
                else:
                    await asyncio.sleep(gap)
    finally:
        with contextlib.suppress(Exception):
            await asyncio.to_thread(_lease, who, token, let_go=True)
    return out


def waiting_for_pick(who) -> list[dict]:
    """The contacts this pass added who wait for his pick of their LinkedIn profile, as
    `meeting_people.meetings_waiting` gives a meeting's guests: {pid, name, linkedin, email}."""
    from .synapse import db

    pids = sorted({str(one.get("pid")) for one in (_held(who).get("added") or {}).values() if one.get("pid")})
    if not pids:
        return []
    ds = mp._ds(who)
    rows = db.rows("SELECT id, title, meta FROM synapse.item WHERE dataset_id = %s AND id = ANY(%s::uuid[]) "
                   "AND kind = 'person' AND deleted_at IS NULL AND meta->'linkedin'->>'status' = %s "
                   "ORDER BY title", (ds["id"], pids, mp.UNRESOLVED))
    out = []
    for row in rows:
        meta = row.get("meta") or {}
        li = meta.get("linkedin") or {}
        if li.get("candidates") and not str(meta.get("research") or "").strip():
            out.append({"pid": str(row["id"]), "name": row.get("title") or "", "linkedin": li,
                        "email": next(iter(meta.get("emails") or []), "")})
    return out


def research_status(who) -> dict:
    """Where the queue stands: how many wait, what became of the rest, what it cost, how long the
    rest will take."""
    held = _research_held(who)
    queue = held.get("queue") or {}
    done = held.get("done") or {}
    counts: dict[str, int] = {}
    for one in done.values():
        counts[one.get("status") or ""] = counts.get(one.get("status") or "", 0) + 1
    looked = int(held.get("looked_up") or 0)
    each = (float(held.get("spent") or 0) / looked) if looked else RESEARCH_EACH
    # A person is about fifteen seconds of lookup and the gap; past a day's runs, the next day.
    per_day = max(1, int(RESEARCH_DAILY_CALLS / 5))
    hours = len(queue) * (RESEARCH_GAP + 15) / 3600 + (len(queue) // per_day) * 24
    return {"queued": len(queue), "done": counts, "spent": round(float(held.get("spent") or 0), 3),
            "looked_up": looked, "cost_each": round(each, 4),
            "rest_costs": round(len(queue) * each, 2),
            "rest_takes_hours": round(hours, 1),
            "held_back": len(held.get("held_back") or {}), "held_back_cost": held.get("held_back_cost") or 0,
            "backfill_queued_at": held.get("backfill_queued_at"), "lease": held.get("lease") or {},
            "waiting_for_pick": len(waiting_for_pick(who)),
            "today": mp._setting(who, RESEARCH_CALLS).get("calls") if
            mp._setting(who, RESEARCH_CALLS).get("day") == mp._today(who) else 0}


# --- the beat ----------------------------------------------------------------------------------


_poke = threading.Event()


def poke() -> None:
    """The calendar changed: run the pass soon rather than at the next hour."""
    _poke.set()


class Adder:
    """The pass, run by itself every `BEAT` and `SOON` after the calendar changed, for the person
    the install belongs to, with the switch on, Google connected and iCloud connected. The first
    time, the backfill."""

    def __init__(self, *, tenancy, google, contacts, apify=None) -> None:
        self.tenancy = tenancy
        self.google = google
        #: The iCloud desk, asked for when it is needed (it is made with the encryption box).
        self.contacts = contacts
        #: HarvestAPI, for looking up on LinkedIn everybody it added (`drain`).
        self.apify = apify
        self._task: asyncio.Task | None = None
        self._lookups: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self.last: Report | None = None

    def start(self) -> None:
        if self._task is None and self.google is not None:
            self._task = asyncio.get_running_loop().create_task(self._run())
        if self._lookups is None and self.apify is not None:
            self._lookups = asyncio.get_running_loop().create_task(self._look_up())

    async def stop(self) -> None:
        self._stop.set()
        for task in (self._task, self._lookups):
            if task is not None:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
        self._task = self._lookups = None

    async def _look_up(self) -> None:
        """The LinkedIn queue, drained a person at a time, looked at again every minute."""
        from . import clock
        from .tenancy import speaking

        await asyncio.sleep(180)
        while not self._stop.is_set():
            try:
                who = await asyncio.to_thread(self._owner)
                if who is not None and self.apify.ready():
                    with speaking(who), clock.person(who, clock.zone_of(who)):
                        await asyncio.to_thread(queue_backfill, who)
                        await drain(who, self.apify, stop=self._stop)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("the meeting contacts' LinkedIn queue failed")
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._stop.wait(), 60)

    async def _run(self) -> None:
        await asyncio.sleep(120)
        last = 0.0
        while True:
            poked = _poke.is_set()
            if time.time() - last >= BEAT or poked:
                if poked:
                    await asyncio.sleep(SOON)
                    _poke.clear()
                last = time.time()
                try:
                    await self.beat()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    log.exception("the meeting contacts' beat failed")
            await asyncio.sleep(30)

    def _owner(self):
        from . import switches
        from .telegram import phone_owner

        owner = phone_owner(self.tenancy)
        if owner is None:
            return None
        with contextlib.suppress(Exception):
            switches.register(SWITCH, TITLE, org_id=str(owner.org_id))
        return owner if on(owner) else None

    async def beat(self) -> Report | None:
        from . import clock
        from .tenancy import speaking

        who = await asyncio.to_thread(self._owner)
        desk = self.contacts() if callable(self.contacts) else self.contacts
        if who is None or desk is None:
            return None
        if await asyncio.to_thread(desk.not_ready_because, who):
            return None
        with speaking(who), clock.person(who, clock.zone_of(who)):
            try:
                calendar = self.google(who).calendar
                if not (await asyncio.to_thread(_held, who)).get("backfilled_at"):
                    self.last = await backfill(who, calendar=calendar, desk=desk)
                else:
                    self.last = await run(who, calendar=calendar, desk=desk)
            except Exception as exc:  # noqa: BLE001 - not connected, or Google said no
                log.info("meeting contacts: the calendar could not be read: %s", exc)
                return None
        return self.last


def status(who) -> dict:
    held = _held(who)
    return {"switch": on(who), "backfilled_at": held.get("backfilled_at"),
            "added": len(held.get("added") or {}), "linkedin": research_status(who),
            "log": list(held.get("log") or [])[-10:]}


__all__ = ["Adder", "LARGE", "MANY_WAITING", "NOTE_HEAD", "Report", "SWITCH", "backfill", "calendar_ids",
           "drain", "enqueue", "is_family", "meeting_skip", "name_for", "not_a_person", "note_for",
           "organisation_for", "poke", "queue_backfill", "research_status", "run", "status",
           "waiting_for_pick", "why_not_research"]
