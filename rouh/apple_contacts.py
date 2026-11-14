"""Apple Contacts: a person's iCloud address book, kept in Rouh's own database
and written back to iCloud when the person asks.

Petar, 24 September 2026: "a live, two-way Apple Contacts integration into
Rouh, over iCloud's CardDAV, so the assistant can look people up and add or
update them." APPLE.md is the long version; this is what each piece does.

**The connection.** Each person enters their Apple ID and an app-specific
password in Settings. It is theirs, not their organisation's: keyed by user and
organisation and queried with both, like a Google connection. The password is
sealed with `encryption.SecretBox`, exactly as a Google refresh token is, and
it is never logged, never put in a card and never sent back to a page. It is
checked before it is kept - a real CardDAV discovery against iCloud - so a
password that does not work is never saved, and one that stops working later
(revoked, or every app-specific password revoked by an Apple ID password
change) marks the connection `needs_new_password` and Settings says so.

**The sync.** `ContactDesk.sync` finds the address book once, then asks iCloud
what changed since last time with the sync-collection REPORT and the token it
was given, fetches only the cards whose ETag moved, and keeps each one as a row
(`models.AppleContact`): the name, every number and address with its label, the
organisation, the birthday, the note, and the card itself. A token iCloud no
longer honours, or a server without sync-collection, is a whole listing
compared ETag by ETag instead. It runs as soon as a password is saved, from the
Sync now button, when the assistant is asked to refresh first, and on its own
every `apple_sync_minutes` (15). Each run records when it finished and how
many cards it changed.

**A sync only ever reads.** It never writes to iCloud and never deletes
anything anywhere: a card iCloud says has gone is marked `gone_at` in Rouh's
copy and left out of searches, and that is all. Writing is only ever one of the
three calls below, made because the person asked.

**Writing.** `save` PUTs the card back with If-Match on the ETag Rouh last
read, and a new one with If-None-Match. When iCloud says the card changed
somewhere else in the meantime (412), the new version is read, and:

- if the other change touched none of the fields this one sets, this change is
  made on top of it and written again, and nothing of either is lost;
- if both changed the same field, both are kept: the other device's version
  stays as it is, and this one is saved as a second card with the same name
  and a line in its note saying why. The answer says so, with both ids.

`delete` is the only way a card leaves iCloud, and it is a call of its own,
also with If-Match, so a card changed on the phone a moment ago is not deleted
out from under it.

**Seeing it.** Every save is two calls, and the first writes nothing: `look`
makes the change on a copy of the card in memory and hands back the contact as
it would be, for the screen, while the details are read back out loud; `save`
writes it once the person has said yes and hands back the contact as iCloud
kept it, which the screen draws over the look. Both are `contact_card`: every
field, each marked added, changed or removed by this change.

**Searching** is Rouh's own database, never iCloud, so it is one query and
fast enough for the middle of a spoken turn. Words match the name, the
organisation, the email addresses and the note, with accents off and Cyrillic
also written out in Latin ("Ivan" finds "Иван"); a number matches on its last
nine digits, so "+44 7700 900 123" and "07700 900 123" are the same phone.

Every write is a line in `{log_dir}/contacts-writes.log`, the same way every
Google write is in `google-writes.log` (`google_audit.WriteLog`).
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import time
import urllib.parse
import uuid
from dataclasses import dataclass, field

from . import carddav, clock, vcard
from .carddav import (CardDAV, CardDAVError, Changed, Found, Gone, NotAccepted, Place,
                      Refused, TokenExpired, Unreachable)
from .encryption import CannotOpen, SecretBox
from .tenancy import Identity

log = logging.getLogger("rouh.contacts")

#: What an app-specific password looks like: sixteen lower-case letters, which
#: Apple shows in four groups of four. Anything else is not one, and the most
#: likely thing it is instead is the person's real Apple ID password, which
#: must never be kept - so it is refused before it is sent anywhere.
PASSWORD_SHAPE = re.compile(r"^[a-z]{4}-?[a-z]{4}-?[a-z]{4}-?[a-z]{4}$")

#: How long the first scheduled sync waits after Rouh starts, in seconds, so a
#: restart is not also a burst of requests to iCloud.
FIRST_BEAT = 45.0

#: How long a search waits for a sync it was asked to run first.
REFRESH_WAIT = 25.0

#: How many people one search hands back at most.
MOST = 25

NOT_ACCEPTED = (
    "iCloud did not accept that Apple ID and app-specific password. Check that the "
    "Apple ID is the one you sign in to iCloud with and that the password was copied "
    "exactly. If it was revoked, or you are not sure, make a new one at "
    "account.apple.com. Nothing was saved.")

REVOKED = (
    "iCloud stopped accepting the app-specific password. It was probably revoked at "
    "account.apple.com, or the Apple ID's own password was changed, which revokes every "
    "app-specific password. Make a new one there and enter it in Settings, under Apple "
    "Contacts.")

UNREADABLE = (
    "The stored app-specific password cannot be opened with this server's encryption "
    "key, so it has to be entered again in Settings, under Apple Contacts.")

#: The field names of `vcard.Person`, said the way a person says them.
FIELD_WORDS = {"name": "name", "organisation": "organisation", "birthday": "birthday",
               "note": "note", "title": "job title"}


def _count(user_id: str, org_id: str) -> int:
    from .synapse import contacts

    return contacts.count(user_id, org_id)


def check_password(text: str) -> str:
    """An app-specific password, tidied to abcd-efgh-ijkl-mnop, or ValueError."""
    squeezed = re.sub(r"\s+", "", text or "").lower()
    if not squeezed:
        raise ValueError("Enter the app-specific password Apple made for Rouh.")
    if not PASSWORD_SHAPE.match(squeezed):
        raise ValueError(
            "That is not an app-specific password. Apple writes them as four groups of "
            "four letters, like abcd-efgh-ijkl-mnop. Your normal Apple ID password does "
            "not work here, and it was not sent to Apple or kept.")
    letters = squeezed.replace("-", "")
    return "-".join(letters[i:i + 4] for i in range(0, 16, 4))


def check_apple_id(text: str) -> str:
    value = (text or "").strip()
    if not value:
        raise ValueError("Enter the Apple ID: the email address you sign in to iCloud with.")
    if " " in value or len(value) > 200 or not (
            re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value)
            or re.fullmatch(r"\+?[\d\s\-()]{7,20}", value)):
        raise ValueError("That does not look like an Apple ID. It is the email address "
                         "(or phone number) you sign in to iCloud with.")
    return value


@dataclass(frozen=True)
class Held:
    """One person's connection, opened. Never leaves this process."""

    user_id: str
    org_id: str
    apple_id: str
    password: str = field(repr=False)
    place: Place | None = None
    sync_token: str = ""
    needs_new_password: bool = False

    def __str__(self) -> str:             # so an f-string cannot print the password
        return f"<Held {self.user_id} {self.apple_id}>"


@dataclass
class Outcome:
    """What one sync did."""

    changed: int = 0
    total: int = 0
    error: str = ""
    skipped: bool = False


@dataclass
class Said:
    """What `look` and `save` answer: the words for the model, and the contact
    as the screen should show it, when there is one to show.

    `key` says which contact the card is about - its id for a change, its name
    for somebody new - so the look before a save and the save itself are one
    card on the screen, revised, and never two.
    """

    text: str
    card: dict | None = None
    key: str = ""


# --- the two tables -----------------------------------------------------------------


class AppleStore:
    """The connections and the cards. Every method takes both ids it is asking about."""

    def __init__(self, box: SecretBox) -> None:
        self._box = box

    # --- the connection ---------------------------------------------------------

    def save(self, user_id: str, org_id: str, apple_id: str, password: str,
             place: Place) -> None:
        """Keep a connection that iCloud has just accepted.

        A different Apple ID, or a different address book, is somebody else's
        cards: Rouh's copy of the old ones is dropped (nothing in iCloud is
        touched) and the next sync starts from nothing. The same Apple ID with
        a new password keeps everything, including the sync token.
        """
        from django.db import transaction

        from .models import AppleConnection

        if not user_id or not org_id:
            raise ValueError("an Apple connection belongs to a user in an organisation")
        sealed = self._box.seal(password)
        with transaction.atomic():
            old = (AppleConnection.objects.select_for_update()
                   .filter(user_id=user_id, org_id=org_id).first())
            same = (old is not None and old.apple_id.lower() == apple_id.lower()
                    and old.book_url == place.book)
            if not same:
                # Somebody else's cards: their people stay in Synapse, no longer contacts.
                from .synapse import contacts

                contacts.forget(user_id, org_id)
            AppleConnection.objects.update_or_create(
                user_id=user_id,
                defaults={
                    "org_id": org_id, "apple_id": apple_id, "password_sealed": sealed,
                    "connected_at": time.time(), "principal_url": place.principal,
                    "home_url": place.home, "book_url": place.book,
                    "sync_token": old.sync_token if same else "",
                    "last_sync_at": old.last_sync_at if same else 0,
                    "last_sync_changed": old.last_sync_changed if same else 0,
                    "last_error": "", "needs_new_password": False})

    def held(self, user_id: str, org_id: str) -> Held | None:
        from .models import AppleConnection

        if not user_id or not org_id:
            return None
        row = AppleConnection.objects.filter(user_id=user_id, org_id=org_id).first()
        if row is None:
            return None
        try:
            password = self._box.open_(row.password_sealed)
        except CannotOpen:
            # Sealed under another key: as good as no password at all, and
            # said as that rather than skipped in silence.
            if not row.needs_new_password:
                AppleConnection.objects.filter(user_id=user_id, org_id=org_id).update(
                    needs_new_password=True, last_attempt_at=time.time(),
                    last_error=UNREADABLE)
            return Held(user_id, org_id, row.apple_id, "", None, "", True)
        place = (Place(row.principal_url, row.home_url, row.book_url)
                 if row.book_url else None)
        return Held(user_id, org_id, row.apple_id, password, place, row.sync_token or "",
                    bool(row.needs_new_password))

    def place_found(self, user_id: str, org_id: str, place: Place) -> None:
        from .models import AppleConnection

        AppleConnection.objects.filter(user_id=user_id, org_id=org_id).update(
            principal_url=place.principal, home_url=place.home, book_url=place.book,
            sync_token="")

    def summary(self, user_id: str, org_id: str) -> dict:
        """What Settings is shown: everything except the password."""
        from .models import AppleConnection

        row = (AppleConnection.objects.filter(user_id=user_id, org_id=org_id).first()
               if user_id and org_id else None)
        if row is None:
            return {"connected": False, "apple_id": "", "connected_at": 0,
                    "needs_new_password": False, "last_sync_at": 0, "last_sync_changed": 0,
                    "last_attempt_at": 0, "last_error": "", "unreadable": False,
                    "contacts": 0}
        return {
            "connected": True,
            "apple_id": row.apple_id,
            "connected_at": row.connected_at,
            "needs_new_password": bool(row.needs_new_password),
            "last_sync_at": row.last_sync_at,
            "last_sync_changed": row.last_sync_changed,
            "last_attempt_at": row.last_attempt_at,
            "last_error": row.last_error or "",
            # Not revoked: sealed under a key this server does not have.
            "unreadable": bool(row.needs_new_password) and row.last_error == UNREADABLE,
            "contacts": _count(user_id, org_id),
        }

    def rejected(self, user_id: str, org_id: str) -> None:
        from .models import AppleConnection

        AppleConnection.objects.filter(user_id=user_id, org_id=org_id).update(
            needs_new_password=True, last_attempt_at=time.time(), last_error=REVOKED)

    def attempted(self, user_id: str, org_id: str, error: str) -> None:
        from .models import AppleConnection

        AppleConnection.objects.filter(user_id=user_id, org_id=org_id).update(
            last_attempt_at=time.time(), last_error=(error or "")[:500])

    def synced(self, user_id: str, org_id: str, token: str, changed: int) -> None:
        from .models import AppleConnection

        now = time.time()
        AppleConnection.objects.filter(user_id=user_id, org_id=org_id).update(
            sync_token=token or "", last_sync_at=now, last_sync_changed=int(changed),
            last_attempt_at=now, last_error="", needs_new_password=False)

    def forget(self, user_id: str, org_id: str) -> bool:
        """The connection; the people its cards were stay in Synapse, no longer contacts. Nothing in iCloud."""
        from .models import AppleConnection
        from .synapse import contacts

        if not user_id or not org_id:
            return False
        contacts.forget(user_id, org_id)
        gone, _ = AppleConnection.objects.filter(user_id=user_id, org_id=org_id).delete()
        return gone > 0

    def connected_people(self) -> list[tuple[str, str]]:
        """Everybody whose contacts the beat should sync: for the beat only."""
        from .models import AppleConnection

        return list(AppleConnection.objects.filter(needs_new_password=False)
                    .values_list("user_id", "org_id"))

    # --- the cards: people of Synapse Master since 4 October 2026 (`synapse/contacts.py`) ---------

    def etags(self, user_id: str, org_id: str) -> dict[str, str]:
        from .synapse import contacts

        return contacts.etags(user_id, org_id)

    def keep(self, user_id: str, org_id: str, found: list[Found]) -> int:
        """Cards as iCloud holds them, onto their people in Synapse Master. How many were new or changed."""
        from .synapse import contacts

        return contacts.keep(user_id, org_id, found)

    def gone(self, user_id: str, org_id: str, hrefs: list[str]) -> int:
        """iCloud says these went: their people stay in Synapse, no longer contacts."""
        from .synapse import contacts

        return contacts.gone(user_id, org_id, hrefs)

    def one(self, user_id: str, org_id: str, contact_id) -> dict | None:
        from .synapse import contacts

        return contacts.one(user_id, org_id, contact_id)

    def by_href(self, user_id: str, org_id: str, href: str) -> dict | None:
        from .synapse import contacts

        return contacts.by_href(user_id, org_id, href)

    def search(self, user_id: str, org_id: str, query: str, limit: int = 8) -> list[dict]:
        """The people a few words or a number find, best first."""
        from .synapse import contacts

        return contacts.search(user_id, org_id, query, limit, most=MOST)


# --- the desk the tools and Settings use ----------------------------------------------------


class ContactDesk:
    """Whose contacts, the sync, and every sentence the assistant says about them.

    Like `GoogleDesk`: a tool runs inside a spoken turn, so the person is the
    speaker the websocket set (`tenancy.speaker`), or the one account this
    install has; with several and nobody named, nobody.
    """

    def __init__(self, tenancy, store: AppleStore, cfg, audit=None, *,
                 transport=None) -> None:
        self._tenancy = tenancy
        self.store = store
        self.url = getattr(cfg, "carddav_url", "") or carddav.ICLOUD
        self.minutes = float(getattr(cfg, "apple_sync_minutes", 15) or 15)
        self.audit = audit
        #: For a check of one's own: httpx's MockTransport in place of iCloud.
        self._transport = transport
        #: What Rouh knows about each contact beyond the card: who they are to
        #: the person, and the research (`rouh/people.py`).
        from .people import People

        self.people = People()
        self._locks: dict[str, asyncio.Lock] = {}
        self._running: dict[str, asyncio.Task] = {}
        self.task: asyncio.Task | None = None

    def person(self) -> Identity | None:
        from .tenancy import speaker

        return speaker() or self._tenancy.only_person()

    def _lock(self, user_id: str) -> asyncio.Lock:
        if user_id not in self._locks:
            self._locks[user_id] = asyncio.Lock()
        return self._locks[user_id]

    def _dav(self, held: Held) -> CardDAV:
        return CardDAV(self.url, held.apple_id, held.password, transport=self._transport)

    async def _db(self, fn, *args, **kwargs):
        return await asyncio.to_thread(fn, *args, **kwargs)

    # --- connecting ---------------------------------------------------------------

    async def connect(self, who: Identity, apple_id: str, password: str) -> str:
        """Check the pair against iCloud and keep it only if iCloud accepts it.

        Raises ValueError with the sentence to show for anything that was not
        kept. On success the first sync is already running when this returns.
        """
        apple_id = check_apple_id(apple_id)
        password = check_password(password)
        try:
            async with CardDAV(self.url, apple_id, password, transport=self._transport) as dav:
                place = await dav.discover()
        except NotAccepted as exc:
            log.info("icloud did not accept the app-specific password for user %s",
                     who.user_id)
            raise ValueError(NOT_ACCEPTED) from exc
        except Unreachable as exc:
            raise ValueError(f"{exc} Nothing was saved; try again in a moment.") from exc
        except CardDAVError as exc:
            raise ValueError(f"{exc} Nothing was saved.") from exc
        await self._db(self.store.save, who.user_id, who.org_id, apple_id, password, place)
        log.info("apple contacts connected for user %s in org %s", who.user_id, who.org_id)
        self.sync_soon(who)
        return (f"iCloud accepted {apple_id}. Rouh is fetching the contacts now; "
                "this page shows how many when it has finished.")

    async def disconnect(self, who: Identity) -> bool:
        async with self._lock(who.user_id):
            gone = await self._db(self.store.forget, who.user_id, who.org_id)
        log.info("apple contacts disconnected for user %s in org %s", who.user_id, who.org_id)
        return gone

    # --- syncing ------------------------------------------------------------------------

    def syncing(self, who: Identity) -> bool:
        task = self._running.get(who.user_id)
        return task is not None and not task.done()

    async def finished(self, who: Identity) -> None:
        """Wait for the sync already running for this person, if there is one.

        For a caller with nothing else to do meanwhile: `manage.py apple
        connect`, which reports the first sync's result before it exits.
        """
        task = self._running.get(who.user_id)
        if task is not None:
            await task

    def sync_soon(self, who: Identity) -> None:
        """Start a sync in the background, unless one is already running."""
        if self.syncing(who):
            return
        task = asyncio.get_running_loop().create_task(self.sync(who))
        self._running[who.user_id] = task
        task.add_done_callback(lambda _t, uid=who.user_id: self._running.pop(uid, None))

    async def sync(self, who: Identity) -> Outcome:
        async with self._lock(who.user_id):
            return await self._sync(who)

    async def _sync(self, who: Identity) -> Outcome:
        held = await self._db(self.store.held, who.user_id, who.org_id)
        if held is None or held.needs_new_password:
            return Outcome(skipped=True)
        try:
            async with self._dav(held) as dav:
                place = held.place
                if place is None:
                    place = await dav.discover()
                    await self._db(self.store.place_found, who.user_id, who.org_id, place)
                    held = Held(held.user_id, held.org_id, held.apple_id, held.password,
                                place, "", False)
                try:
                    token, changed = await self._pull(dav, held, place)
                except Refused as exc:
                    if exc.status not in (403, 404):
                        raise
                    # The address book moved. Find it again, once.
                    place = await dav.discover()
                    await self._db(self.store.place_found, who.user_id, who.org_id, place)
                    held = Held(held.user_id, held.org_id, held.apple_id, held.password,
                                place, "", False)
                    token, changed = await self._pull(dav, held, place)
                # Each contact's picture, kept here while the sign-in is open (`contact_photos`).
                from . import contact_photos

                await contact_photos.keep_faces(dav, who)
        except NotAccepted:
            await self._db(self.store.rejected, who.user_id, who.org_id)
            log.warning("icloud stopped accepting the app-specific password of user %s",
                        who.user_id)
            return Outcome(error=REVOKED)
        except CardDAVError as exc:
            await self._db(self.store.attempted, who.user_id, who.org_id, str(exc))
            log.warning("apple contacts sync for user %s did not finish: %s", who.user_id, exc)
            return Outcome(error=str(exc))
        await self._db(self.store.synced, who.user_id, who.org_id, token, changed)
        total = (await self._db(self.store.summary, who.user_id, who.org_id))["contacts"]
        log.info("apple contacts synced for user %s: %d card(s) changed, %d contact(s)",
                 who.user_id, changed, total)
        return Outcome(changed=changed, total=total)

    async def _pull(self, dav: CardDAV, held: Held, place: Place) -> tuple[str, int]:
        """Read what changed into the table. Nothing is written to iCloud here."""
        local = await self._db(self.store.etags, held.user_id, held.org_id)
        changes = None
        if held.sync_token:
            with contextlib.suppress(TokenExpired, Refused):
                changes = await dav.changes(place.book, held.sync_token)
        whole = changes is None
        if changes is None:
            try:
                changes = await dav.changes(place.book, "")
            except (TokenExpired, Refused) as exc:
                # A server without sync-collection: every card and its ETag,
                # compared with what Rouh holds.
                if isinstance(exc, Refused) and exc.status in (404,):
                    raise
                listing = await dav.listing(place.book)
                changes = carddav.Changes(changed=list(listing.items()), token="")
        if whole:
            there = {href for href, _etag in changes.changed}
            changes.removed = [href for href in local if href not in there]
        wanted = [href for href, etag in changes.changed if local.get(href) != etag]
        found = await dav.fetch(place.book, wanted) if wanted else []
        kept = await self._db(self.store.keep, held.user_id, held.org_id, found)
        dropped = await self._db(self.store.gone, held.user_id, held.org_id,
                                 [h for h in changes.removed if h in local])
        return changes.token, kept + dropped

    # --- the beat ---------------------------------------------------------------------------

    def start(self) -> None:
        #: The loop the desk runs on, so a change made in Synapse, on a worker thread, is written to
        #: iCloud here with the same lock as every other write (`synapse/contacts.run_job`).
        self.loop = asyncio.get_running_loop()
        if self.task is None or self.task.done():
            self.task = self.loop.create_task(self._beat())

    async def stop(self) -> None:
        for task in [self.task, *self._running.values()]:
            if task is not None and not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
        self.task = None

    async def _beat(self) -> None:
        await asyncio.sleep(FIRST_BEAT)
        while True:
            try:
                for user_id, org_id in await self._db(self.store.connected_people):
                    await self.sync(Identity(user_id=user_id, org_id=org_id))
            except asyncio.CancelledError:
                raise
            except Exception:  # a sync must never kill the app
                log.exception("the contacts beat stumbled; carrying on")
            await asyncio.sleep(self.minutes * 60)

    # --- what the assistant is told ------------------------------------------------------------

    def not_ready_because(self, who: Identity | None) -> str:
        from .untrusted import ours

        if who is None:
            return ours("I cannot tell whose contacts to use from here. Ask me from a "
                        "conversation you are signed in to.")
        summary = self.store.summary(who.user_id, who.org_id)
        if not summary["connected"]:
            return ours("Apple Contacts are not connected yet. Open Settings, find Apple "
                        "Contacts, and enter the Apple ID with an app-specific password "
                        "made at account.apple.com.")
        if summary["needs_new_password"]:
            return ours((UNREADABLE if summary["unreadable"] else REVOKED)
                        + " Until then the contacts cannot be read or changed.")
        return ""

    async def search(self, query: str, limit: int = 8, refresh_first: bool = False) -> str:
        from .untrusted import ours

        who = self.person()
        if who is None:
            return await self._db(self.not_ready_because, who)
        query = (query or "").strip()
        limit = max(1, min(int(limit or 8), MOST))
        summary = await self._db(self.store.summary, who.user_id, who.org_id)
        # A revoked password stops the sync and every write, and not the
        # looking up: Rouh's copy is still there, and "what is Ana's number"
        # deserves the number, with a word that it may be out of date.
        stale = ""
        if summary["connected"] and summary["needs_new_password"]:
            stale = ("iCloud stopped accepting the app-specific password, so this is Rouh's "
                     "copy from the last sync and may be out of date. Enter a new password "
                     "in Settings, under Apple Contacts.\n\n")
        else:
            blocked = await self._db(self.not_ready_because, who)
            if blocked:
                # iCloud is not there, and the contacts Rouh keeps of its own
                # still are: somebody who wrote in, and the person themselves.
                own = [one for one in (await self._db(self.people.search, who.user_id, who.org_id, query)
                                       if query else []) if _on_their_side(one)]
                if not own:
                    return blocked
                return (f"{blocked}\n\nPeople with no iCloud card that match \"{query}\":\n\n"
                        + "\n\n".join(_known_said(one) for one in own[:limit]))
        if refresh_first and not stale:
            with contextlib.suppress(TimeoutError):
                outcome = await asyncio.wait_for(asyncio.shield(self.sync(who)), REFRESH_WAIT)
                if outcome.error == REVOKED:
                    stale = ("iCloud stopped accepting the app-specific password just now, "
                             "so this is Rouh's copy from the last sync.\n\n")
            summary = await self._db(self.store.summary, who.user_id, who.org_id)
        if not summary["last_sync_at"]:
            if self.syncing(who):
                return ours("The first sync from iCloud is still running. Ask me again in "
                            "a moment.")
            return ours("The contacts have not been synced from iCloud yet"
                        + (f": {summary['last_error']}" if summary["last_error"] else ".")
                        + " Settings has a Sync now button.")
        if not query:
            return ours("Say who to look for: a name, a number, an email address or an "
                        "organisation.")
        found = await self._db(self._found, who, query, limit)
        when = clock.ago(summary["last_sync_at"])
        if not found:
            return (f"{stale}Nobody in the iCloud contacts, or among Rouh's own, matches "
                    f"\"{query}\" ({summary['contacts']} contacts, synced {when}).")
        head = (f"{_many(len(found), 'person')} "
                f"{'match' if len(found) != 1 else 'matches'} \"{query}\" (the iCloud "
                f"contacts synced {when}, with who each is to the person and the online "
                "research, which are Rouh's own):")
        return stale + head + "\n\n" + "\n\n".join(_known_said(one) for one in found)

    def _found(self, who: Identity, query: str, limit: int) -> list:
        """The cards a query finds, each with its profile, then Rouh's own matches."""
        rows = self.store.search(who.user_id, who.org_id, query, limit)
        # A contact's job title (night 42, `rouh/job_title.py`): words in somebody's job title find
        # them too, after the matches by name, number, address or company.
        from . import job_title

        rows = rows + job_title.found(who, query, {str(r.get("id")) for r in rows}, limit - len(rows))
        # A contact's postal address (night 43, `rouh/postal_address.py`): a city or a street finds them too.
        from . import postal_address

        rows = rows + postal_address.found(who, query, {str(r.get("id")) for r in rows}, limit - len(rows))
        found = self.people.attach(who.user_id, who.org_id, rows)
        more = self.people.search(who.user_id, who.org_id, query,
                                  skip={one.id for one in found})
        return [one for one in found + more if _on_their_side(one)][:limit]

    # --- what Rouh knows about a person ------------------------------------------------------

    async def show(self, args: dict) -> Said:
        """One contact, whole: the card, who they are to the person, and the research."""
        from .untrusted import ours

        who = self.person()
        if who is None:
            return Said(await self._db(self.not_ready_because, who))
        contact_id = str(args.get("contact_id") or "").strip()
        address = str(args.get("email") or "").strip().lower()
        query = str(args.get("query") or "").strip()
        if contact_id:
            person = await self._db(self.people.person, who.user_id, who.org_id, contact_id)
            if person is None or not _on_their_side(person):
                return Said(ours(f"There is no contact with the id {contact_id}. Search for "
                                 "the person first and use the id that comes back."))
        elif address:
            found = [one for one in await self._db(self.people.by_address, who.user_id, who.org_id, address)
                     if _on_their_side(one)]
            if not found:
                return Said(ours(f"Nobody with {address} is in the contacts, and Rouh has no "
                                 "contact of its own for them."))
            person = found[0]
        elif query:
            found = await self._db(self._found, who, query, 8)
            if not found:
                return Said(ours(f"Nobody in the contacts matches \"{query}\"."))
            if len(found) > 1:
                return Said(ours(
                    f"{_many(len(found), 'person')} match \"{query}\", so nothing was shown. "
                    "Ask which, or show one by its id: "
                    + "; ".join(f"{one.id} {one.name or '(no name)'}"
                                + (f" ({one.organisation})" if one.organisation else "")
                                for one in found) + "."))
            person = found[0]
        else:
            return Said(ours("Say whose contact to show: contact_id, email, or a name as "
                             "query."))
        return Said(_known_said(person, whole=True)
                    + "\n\nOn the screen now, with both of Rouh's own fields, which the "
                      "person can change on the card.",
                    profile_card(person), f"profile:{person.id}")

    async def note(self, args: dict, *, turn=None) -> Said:
        """Change who a contact is to the person, or the research about them.

        `turn` is the email this turn is about (`mail_turn.MailTurn`) when it
        is somebody else's: then only the research, and only about whoever
        wrote it, may be written. Who somebody is to the person is only ever
        the person's to say, and a stranger's email must not be able to make
        itself somebody's friend, or add an address to somebody's card.
        """
        from .untrusted import ours

        who = self.person()
        if who is None:
            return Said(await self._db(self.not_ready_because, who))
        contact_id = str(args.get("contact_id") or "").strip()
        address = str(args.get("email") or "").strip().lower()
        name = args.get("name")
        relationship = args.get("relationship")
        research = args.get("research")
        confirmed = args.get("research_confirmed")
        if isinstance(confirmed, str):
            confirmed = confirmed.strip().lower() == "true"
        add = [str(x) for x in args.get("add_emails") or [] if str(x or "").strip()]
        remove = [str(x) for x in args.get("remove_emails") or [] if str(x or "").strip()]
        silos = args.get("silos")
        silos = None if silos is None else silos
        guarded = turn is not None and not turn.from_owner
        if guarded and relationship is not None:
            return Said(ours("Only ‹owner› says who somebody is to ‹him›, so nothing was kept. "
                             "Ask ‹him› in your note, and keep it when ‹he› answers."))
        if guarded and silos is not None:
            return Said(ours("Only ‹owner› says which of ‹his› silos somebody is in, so nothing was kept."))
        if guarded and (add or remove):
            return Said(ours("An email cannot change which addresses belong to whom, so "
                             "nothing was kept."))
        if contact_id:
            person = await self._db(self.people.person, who.user_id, who.org_id, contact_id)
            if person is None and contact_id.lower() == "me" and not guarded:
                # Their own contact, made the first time they say something
                # about themselves - the addresses they write from, above all.
                person = await self._db(self.people.ensure_me, who.user_id, who.org_id)
            if person is None:
                return Said(ours(f"There is no contact with the id {contact_id}. Search for "
                                 "the person first and use the id that comes back."))
        elif address:
            found = await self._db(self.people.by_address, who.user_id, who.org_id, address)
            person = found[0] if found else None
        else:
            return Said(ours("Say which contact: contact_id, or their email address for "
                             "somebody new."))
        if guarded:
            theirs = (person.id == turn.sender_contact if person is not None
                      else address == turn.sender)
            if not theirs or (person is not None and person.is_me):
                return Said(ours("While handling an email, only what is known about whoever "
                                 "wrote it may be kept, so nothing was kept."))
        if (relationship is None and research is None and confirmed is None and not add
                and not remove and name is None and silos is None):
            return Said(ours("Nothing to keep was given."))
        try:
            person = await self._db(
                self.people.write, who.user_id, who.org_id, person,
                name=None if name is None else str(name), address=address,
                relationship=None if relationship is None else str(relationship),
                research=None if research is None else str(research),
                confirmed=None if confirmed is None else bool(confirmed),
                add_emails=add, remove_emails=remove, silos=silos)
        except ValueError as exc:
            return Said(ours(str(exc)))
        if guarded and not turn.sender_contact:
            turn.sender_contact = person.id
        kept = [what for what, given in (("who they are to the person", relationship),
                                         ("the online research", research))
                if given is not None]
        if confirmed is not None and research is None:
            kept.append("whether the research is confirmed")
        if add or remove:
            kept.append("the addresses")
        if silos is not None:
            kept.append("which silos they are in")
        text = (f"Kept {' and '.join(kept) or 'the name'} for {person.name or person.id} "
                f"(contact {person.id}), on the person in Synapse Master; nothing was written to "
                "iCloud. " + person.research_said() + " " + person.silos_said() + " The contact is on the screen.")
        return Said(ours(text), profile_card(person), f"profile:{person.id}")

    # --- writing ---------------------------------------------------------------------------------

    async def look(self, args: dict) -> Said:
        """The contact as `save` would leave it, for the screen, and nothing written.

        The first of the two calls every save is made in. The change is made
        on a copy of the card Rouh holds, in memory, so the person sees exactly
        what they are being asked to agree to while it is read back to them,
        and iCloud is not asked anything. Petar, 24 September 2026, on the
        read-back before a contact is saved: "That is how I want it to behave
        with anything that goes outside. I would like to see the new contact,
        though."
        """
        from .untrusted import ours

        who = self.person()
        blocked = await self._db(self.not_ready_because, who)
        if blocked:
            return Said(blocked)
        contact_id = str(args.get("contact_id") or "").strip()
        try:
            changes = _changes_from(args)
            if not contact_id:
                card, _ = vcard.new_card("LOOK", changes)
                after = _fields(vcard.read(card.text()))
                shown = contact_card(after, None, UNSAVED)
                details = "; ".join(f"{row['label']} {' '.join(row['value'].split())}"
                                    for row in shown["blocks"][0]["rows"]).rstrip(".")
                return Said(
                    ours(f"Nothing is saved yet. On the screen now, marked not saved: "
                         f"{after['name']} as they would be added"
                         f"{': ' + details if details else ''}. {ASK_FIRST}"),
                    shown, key_for(args))
            row = await self._db(self.store.one, who.user_id, who.org_id, contact_id)
            if row is None:
                return Said(ours(f"There is no contact with the id {contact_id}. Search for "
                                 "the person first and use the id that comes back."))
            if row["kind"] != "individual":
                return Said(ours("That is a contact group, not a person, and groups are not "
                                 "changed from here."))
            if changes.empty():
                return Said(ours("Nothing to change was given."))
            mine = vcard.Card.parse(row["vcard"])
            said = vcard.apply(mine, changes)
        except vcard.BadField as exc:
            return Said(ours(str(exc)))
        if not said:
            return Said(ours(f"{row['name']} already reads that way, so there is nothing "
                             "to save."))
        after = _fields(vcard.read(mine.text()))
        return Said(
            ours(f"Nothing is changed yet. On the screen now, marked not saved, with each "
                 f"change marked: {row['name']}, {'; '.join(said)}. {ASK_FIRST}"),
            contact_card(after, row, UNSAVED), key_for(args))

    async def save(self, args: dict, who: Identity | None = None) -> Said:
        """Write the contact to iCloud, and the contact as iCloud kept it for the screen.

        `who` is given when the change was made in Synapse rather than in a conversation."""
        from .untrusted import ours

        who = who or self.person()
        blocked = await self._db(self.not_ready_because, who)
        if blocked:
            return Said(blocked)
        try:
            changes = _changes_from(args)
        except vcard.BadField as exc:
            return Said(ours(str(exc)))
        contact_id = str(args.get("contact_id") or "").strip()
        try:
            async with self._lock(who.user_id):
                held = await self._db(self.store.held, who.user_id, who.org_id)
                if held is None or held.needs_new_password:
                    return Said(await self._db(self.not_ready_because, who))
                async with self._dav(held) as dav:
                    place = await self._place(dav, held)
                    if not contact_id:
                        done = await self._create(dav, held, place, changes)
                        done.key = key_for(args)
                        return done
                    row = await self._db(self.store.one, who.user_id, who.org_id, contact_id)
                    if row is None:
                        return Said(ours(f"There is no contact with the id {contact_id}. "
                                         "Search for the person first and use the id that "
                                         "comes back."))
                    if row["kind"] != "individual":
                        return Said(ours("That is a contact group, not a person, and groups "
                                         "are not changed from here."))
                    done = await self._update(dav, held, place, row, changes)
                    done.key = key_for(args)
                    return done
        except vcard.BadField as exc:
            return Said(ours(str(exc)))
        except NotAccepted:
            await self._db(self.store.rejected, who.user_id, who.org_id)
            return Said(ours(REVOKED + " Nothing was changed."))
        except CardDAVError as exc:
            return Said(ours(f"{exc} Nothing was changed."))

    async def delete(self, args: dict) -> str:
        from .untrusted import ours

        who = self.person()
        blocked = await self._db(self.not_ready_because, who)
        if blocked:
            return blocked
        contact_id = str(args.get("contact_id") or "").strip()
        try:
            async with self._lock(who.user_id):
                row = await self._db(self.store.one, who.user_id, who.org_id, contact_id)
                if row is None:
                    return ours(f"There is no contact with the id {contact_id}. Search for "
                                "the person first and use the id that comes back.")
                held = await self._db(self.store.held, who.user_id, who.org_id)
                if held is None or held.needs_new_password:
                    return await self._db(self.not_ready_because, who)
                async with self._dav(held) as dav:
                    place = await self._place(dav, held)
                    try:
                        await dav.delete(row["href"], row["etag"])
                    except Gone:
                        await self._db(self.store.gone, who.user_id, who.org_id, [row["href"]])
                        return ours(f"{row['name']} was already gone from iCloud, so there "
                                    "was nothing to delete.")
                    except Changed:
                        fresh = await dav.fetch(place.book, [row["href"]])
                        await self._db(self.store.keep, who.user_id, who.org_id, fresh)
                        return ours(f"{row['name']} was changed on another device since I "
                                    "last read it, so I did not delete it. Ask again if it "
                                    "should still go.")
                await self._db(self.store.gone, who.user_id, who.org_id, [row["href"]])
        except NotAccepted:
            await self._db(self.store.rejected, who.user_id, who.org_id)
            return ours(REVOKED + " Nothing was deleted.")
        except CardDAVError as exc:
            return ours(f"{exc} Nothing was deleted.")
        said = f"Deleted {row['name']} from the iCloud contacts."
        self._wrote("delete_contact", row["name"], f"{said} (id {row['id']})", held)
        return ours(said + " It leaves the phone when the phone next syncs with iCloud.")

    async def remove_card(self, who: Identity, *, href: str, etag: str, name: str) -> str:
        """A card deleted from iCloud because its person was deleted in Synapse: by its address and ETag,
        since the person is gone from Synapse already. Changed on another device meanwhile, it is kept."""
        from .untrusted import ours

        if not href:
            return ours("That person had no card in iCloud, so nothing was deleted.")
        try:
            async with self._lock(who.user_id):
                held = await self._db(self.store.held, who.user_id, who.org_id)
                if held is None or held.needs_new_password:
                    return ours("iCloud is not connected, so nothing was deleted.")
                async with self._dav(held) as dav:
                    await self._place(dav, held)
                    try:
                        await dav.delete(href, etag)
                    except Gone:
                        return ours(f"{name} was already gone from iCloud.")
                    except Changed:
                        return ours(f"{name} was changed on another device since, so the card was kept in "
                                    "iCloud.")
        except NotAccepted:
            await self._db(self.store.rejected, who.user_id, who.org_id)
            return ours(REVOKED + " Nothing was deleted.")
        except CardDAVError as exc:
            return ours(f"{exc} Nothing was deleted.")
        self._wrote("delete_contact", name, f"Deleted {name} from the iCloud contacts, deleted in Synapse", held)
        return ours(f"Deleted {name} from the iCloud contacts, as it was deleted in Synapse.")

    async def _place(self, dav: CardDAV, held: Held) -> Place:
        if held.place is not None:
            return held.place
        place = await dav.discover()
        await self._db(self.store.place_found, held.user_id, held.org_id, place)
        return place

    async def _write_new(self, dav: CardDAV, held: Held, place: Place,
                         card: vcard.Card) -> dict:
        """PUT a card that is not in iCloud yet, and read back what iCloud kept."""
        uid = card.value("UID")
        href = urllib.parse.urljoin(place.book.rstrip("/") + "/",
                                    urllib.parse.quote(uid) + ".vcf")
        await dav.put(href, card.text())
        return await self._read_back(dav, held, place, href)

    async def _read_back(self, dav: CardDAV, held: Held, place: Place, href: str) -> dict:
        """What iCloud holds now, which is not always what was sent (RFC 6352 5.3.4)."""
        fresh = await dav.fetch(place.book, [href])
        await self._db(self.store.keep, held.user_id, held.org_id, fresh)
        row = await self._db(self.store.by_href, held.user_id, held.org_id, href)
        if row is None:
            raise Refused("iCloud said the card was saved but does not hand it back.")
        return row

    async def _create(self, dav: CardDAV, held: Held, place: Place,
                      changes: vcard.Changes) -> Said:
        from .untrusted import ours

        card, said = vcard.new_card(str(uuid.uuid4()).upper(), changes)
        row = await self._write_new(dav, held, place, card)
        details = f": {', '.join(said)}" if said else ""
        text = f"Added {row['name']} to the iCloud contacts{details}. Id {row['id']}."
        self._wrote("save_contact", row["name"], text, held)
        return Said(ours(text + " It reaches the phone when the phone next syncs with "
                         "iCloud. " + SHOWN_SAVED),
                    contact_card(row, None, SAVED, person=await self._person_of(held, row)))

    async def _update(self, dav: CardDAV, held: Held, place: Place, row: dict,
                      changes: vcard.Changes) -> Said:
        from .untrusted import ours

        if changes.empty():
            return Said(ours("Nothing to change was given."))
        name = row["name"]
        mine = vcard.Card.parse(row["vcard"])
        said = vcard.apply(mine, changes)
        if not said:
            return Said(ours(f"{name} already reads that way, so nothing was changed."))
        try:
            await dav.put(row["href"], mine.text(), etag=row["etag"])
        except Changed:
            return await self._both(dav, held, place, row, changes, mine)
        fresh = await self._read_back(dav, held, place, row["href"])
        text = f"Changed {fresh['name']} in the iCloud contacts: {'; '.join(said)}. Id {row['id']}."
        self._wrote("save_contact", fresh["name"], text, held)
        return Said(ours(f"{text} {SHOWN_SAVED}"), contact_card(
            fresh, row, SAVED, person=await self._person_of(held, fresh)))

    async def _both(self, dav: CardDAV, held: Held, place: Place, row: dict,
                    changes: vcard.Changes, mine: vcard.Card) -> Said:
        """The card changed somewhere else while this was being written.

        Merged when the two changes touch different fields; both kept, as two
        cards, when they touch the same one. Never one silently over the other.
        The screen shows whichever card holds this change, and says which.
        """
        from .untrusted import ours

        name = row["name"]
        fresh = await dav.fetch(place.book, [row["href"]])
        if not fresh:
            await self._db(self.store.gone, held.user_id, held.org_id, [row["href"]])
            again = vcard.with_uid(mine, str(uuid.uuid4()).upper())
            kept = await self._write_new(dav, held, place, again)
            text = (f"{name} was deleted on another device while I was changing it. So "
                    f"that nothing is lost, I saved my version as a new card (id "
                    f"{kept['id']}); delete it if the deletion was meant.")
            self._wrote("save_contact", name, text, held)
            return Said(ours(f"{text} {SHOWN_SAVED}"), contact_card(
                kept, row, SAVED, person=await self._person_of(held, kept),
                remark=("It had been deleted on another device while this was being "
                        "saved, so this was saved as a new contact. Delete it if the "
                        "deletion was meant.")))
        await self._db(self.store.keep, held.user_id, held.org_id, fresh)
        was, theirs = vcard.read(row["vcard"]), vcard.read(fresh[0].data)
        ours_now = vcard.read(mine.text())
        clash = [key for key in changes.scalars()
                 if getattr(theirs, key) != getattr(was, key)
                 and getattr(theirs, key) != getattr(ours_now, key)]
        if not clash:
            merged = vcard.Card.parse(fresh[0].data)
            said = vcard.apply(merged, changes)
            try:
                if said:
                    await dav.put(row["href"], merged.text(), etag=fresh[0].etag)
            except Changed:
                clash = ["whole card"]
            else:
                now = await self._read_back(dav, held, place, row["href"])
                text = (f"{name} had also been changed on another device since I last read "
                        f"it. That change is kept, and mine is made on top of it: "
                        f"{'; '.join(said) or 'nothing more was needed'}. Id {now['id']}.")
                self._wrote("save_contact", now["name"], text, held)
                # Marked against the other device's version, so what is
                # marked is this change and not theirs.
                return Said(ours(f"{text} {SHOWN_SAVED}"), contact_card(
                    now, _fields(theirs), SAVED, person=await self._person_of(held, now),
                    remark=("It had also been changed on another device. That change is "
                            "kept, and this one is made on top of it.")))
        second = vcard.Card.parse(mine.text())
        note = second.value("NOTE").strip()
        today = clock.now()
        marker = (f"Kept by Rouh on {today.day} {today:%B %Y}: this contact was changed "
                  "on another device while Rouh was changing it, so both versions were "
                  "kept. This card is Rouh's; the other card with this name is the other "
                  "device's.")
        second.set("NOTE", vcard.escape((note + "\n\n" if note else "") + marker))
        second = vcard.with_uid(second, str(uuid.uuid4()).upper())
        kept = await self._write_new(dav, held, place, second)
        fields = " and ".join(FIELD_WORDS.get(key, key) for key in clash)
        text = (f"{name} was changed on another device at the same time, in the {fields}, "
                f"so I kept both: the card as it is now on the phone (id {row['id']}), and "
                f"my version as a second card with the same name (id {kept['id']}), with a "
                "line in its note saying why. Nothing was overwritten; merge the two on the "
                "phone when you have a moment.")
        self._wrote("save_contact", name, text, held)
        return Said(ours(f"{text} {SHOWN_SAVED}"), contact_card(
            kept, row, SAVED, person=await self._person_of(held, kept),
            remark=(f"It was changed on another device at the same time, in the {fields}, "
                    "so both were kept: this is the second card with this name, and the "
                    "other device's is the first. Merge the two on the phone.")))

    async def _person_of(self, held: Held, row: dict):
        """A card just written, as Rouh knows it: with its relationship and research."""
        found = await self._db(self.people.attach, held.user_id, held.org_id, [row])
        return found[0] if found else None

    def _wrote(self, tool: str, target: str, summary: str, held: Held) -> None:
        """One line in contacts-writes.log, once iCloud has said it worked."""
        if self.audit is not None:
            self.audit.wrote(tool, target, summary, user_id=held.user_id,
                             org_id=held.org_id, account=held.apple_id)


# --- how things are said ------------------------------------------------------------------------


def _changes_from(args: dict) -> vcard.Changes:
    def maybe(key: str) -> str | None:
        return None if args.get(key) is None else str(args.get(key))

    def pairs(key: str, what: str) -> list[dict]:
        out = []
        for item in args.get(key) or []:
            if isinstance(item, str):
                item = {what: item}
            if isinstance(item, dict) and str(item.get(what) or "").strip():
                out.append({what: str(item[what]).strip(),
                            "label": str(item.get("label") or "").strip()})
        return out

    def plain(key: str) -> list[str]:
        return [str(v).strip() for v in (args.get(key) or []) if str(v or "").strip()]

    changes = vcard.Changes(
        name=maybe("name"), organisation=maybe("organisation"),
        birthday=maybe("birthday"), note=maybe("note"), title=maybe("title"),
        add_phones=pairs("add_phones", "number"), remove_phones=plain("remove_phones"),
        add_emails=pairs("add_emails", "address"), remove_emails=plain("remove_emails"))
    # A contact's postal address (night 43, `rouh/postal_address.py`); taken out of the arguments while off.
    from . import postal_address

    changes.add_addresses, changes.remove_addresses = postal_address.to_changes(args)
    if changes.birthday:
        vcard.check_birthday(changes.birthday)            # said before anything is sent
    for phone in changes.add_phones:
        if not vcard.digits_of(phone["number"]):
            raise vcard.BadField(f"\"{phone['number']}\" is not a phone number.")
    return changes


def _labelled(value: str, label: str) -> str:
    return f"{label} {value}" if label else value


# --- the contact on the screen ------------------------------------------------------------------

#: Where the contact on the screen is: looked at and not written yet, written
#: and read back from iCloud, or turned down with the card's own button.
UNSAVED, SAVED, DECLINED = "unsaved", "saved", "declined"

#: What the model is told after a look. The read-back out loud is the part
#: Petar asked to keep exactly as it was; the card is beside it.
ASK_FIRST = (
    "Read the details back out loud as well, the way you always do - the card is beside "
    "what you say, never instead of it - and ask whether to save it. Only when they say "
    "yes, call save_contact again with the same fields and confirmed true. If they change "
    "anything, call it again without confirmed and the card is drawn again. The card also "
    "has a Save button: if they press it instead, you are told, and it is saved without "
    "you calling anything.")

#: And after a save.
SHOWN_SAVED = "The card on the screen now shows it as iCloud kept it, marked saved."


def new_key(name) -> str:
    """Which new contact a card is about: the name it is being added under."""
    return "new:" + vcard.normalise(str(name or ""))


def key_for(args: dict) -> str:
    """Which contact a save is about: its id for a change, its name for somebody new.

    From the call itself, so a spoken yes and a press on the card's button,
    which arrive by different roads, name the same contact the same way.
    """
    said = str(args.get("contact_id") or "").strip().lower()
    if said[:1] in ("c", "p") and said[1:].isdigit():     # an id from before Synapse Master: c685
        said = said[1:]
    return f"c{said}" if said else new_key(args.get("name"))


def declined(card: dict) -> dict:
    """A contact card whose Don't save was pressed: the same contact, marked not saved."""
    blocks = []
    for b in card.get("blocks") or []:
        if isinstance(b, dict) and b.get("block") == "contact":
            b = dict(b, state=DECLINED, status="Not saved",
                     foot="You chose not to save this. Nothing was written to iCloud.")
        blocks.append(b)
    title = str(card.get("title") or "")
    for was, now in (("Contact to add: ", "Contact not added: "),
                     ("Contact to change: ", "Contact not changed: ")):
        if title.startswith(was):
            title = now + title[len(was):]
    description = str(card.get("description") or "").replace(", shown before saving",
                                                              ", and not saved")
    return dict(card, title=title, description=description, blocks=blocks)


def _fields(person) -> dict:
    """A `vcard.Person` or a row of the table, as the fields a card shows."""
    def get(key: str):
        return person.get(key) if isinstance(person, dict) else getattr(person, key, None)

    from . import job_title, postal_address

    return {"name": str(get("name") or ""), "organisation": str(get("organisation") or ""),
            "phones": list(get("phones") or []), "emails": list(get("emails") or []),
            "birthday": str(get("birthday") or ""), "note": str(get("note") or ""),
            "title": job_title.of(person),
            # On the card an address says so, beside a work number and a work email: "work address".
            "addresses": [dict(a, label=a["label"] if "address" in a["label"].lower() else f"{a['label']} address")
                          for a in postal_address.of(person)]}


def _rows(after: dict, before: dict | None) -> list[dict]:
    """Every field of the contact, each saying what this change did to it.

    Nothing is marked on somebody new, because everything on them is. On a
    change, a number or an address taken off is kept in the list as a row of
    its own, marked removed, rather than simply missing: something that has
    quietly gone is exactly what a person would not notice.
    """
    rows: list[dict] = []
    had = before or {}

    def single(kind: str, label: str, now: str, was: str) -> None:
        if before is None or now == was:
            if now:
                rows.append({"kind": kind, "label": label, "value": now})
        elif now and was:
            rows.append({"kind": kind, "label": label, "value": now, "change": "changed",
                         "was": was})
        elif now:
            rows.append({"kind": kind, "label": label, "value": now, "change": "added"})
        else:
            rows.append({"kind": kind, "label": label, "value": was, "change": "removed"})

    def several(kind: str, key: str, now: list[dict], was: list[dict], same) -> None:
        for item in now:
            value, label = str(item.get(key) or ""), str(item.get("label") or "") or kind
            row = {"kind": kind, "label": label, "value": value}
            old = next((o for o in was if same(str(o.get(key) or ""), value)), None)
            if before is not None and old is None:
                row["change"] = "added"
            elif before is not None and (str(old.get("label") or "") or kind) != label:
                row.update(change="changed", was=str(old.get("label") or "") or kind)
            rows.append(row)
        if before is None:
            return
        for old in was:
            value = str(old.get(key) or "")
            if not any(same(str(item.get(key) or ""), value) for item in now):
                rows.append({"kind": kind, "label": str(old.get("label") or "") or kind,
                             "value": value, "change": "removed"})

    single("organisation", "company", after["organisation"], had.get("organisation", ""))
    # A contact's job title (night 42, `rouh/job_title.py`): "" while its switch is off.
    single("title", "job title", after.get("title", ""), had.get("title", ""))
    several("phone", "number", after["phones"], had.get("phones") or [], vcard.same_number)
    several("email", "address", after["emails"], had.get("emails") or [],
            lambda a, b: a.strip().lower() == b.strip().lower())
    # A contact's postal address (night 43, `rouh/postal_address.py`): [] while its switch is off.
    several("postal", "address", after.get("addresses") or [], had.get("addresses") or [], vcard.same_address)
    single("birthday", "birthday", vcard.birthday_words(after["birthday"]),
           vcard.birthday_words(had.get("birthday", "")))
    single("note", "note", after["note"], had.get("note", ""))
    return rows


#: A contact shown as it is, with nothing being changed (`show_contact`).
SHOWN = "shown"


def _on_their_side(person) -> bool:
    """Whether a contact may be looked up in this turn (`rouh/silos.py`): always for the owner; for somebody
    limited to some of their silos, anybody in one of them, and anybody in no silo yet, as it always was, so
    nothing they could look up before is taken away; the owner's family, in Personal, is not looked up for
    anybody limited to Work."""
    from . import silos

    limit = silos.limit_now()
    if limit is None or person is None:
        return True
    return not person.silos or silos.fits(person.silos, limit)

#: What Rouh's own two fields are called on the card, in Petar's words.
RELATIONSHIP_LABEL = "my relationship"
RESEARCH_LABEL = "online research"
SILOS_LABEL = "silos"


def _profile_rows(person) -> list[dict]:
    """The addresses Rouh knows beyond the card, and Rouh's two fields.

    Rows like any other field, so a card filed as a step carries them and the
    task page draws them (`steps.block_text`, `docview`), and the page draws
    the two fields as sections of their own (`contactBlock`).
    """
    rows = [{"kind": "email", "label": "known to Rouh", "value": one}
            for one in person.own_emails]
    if person.relationship:
        rows.append({"kind": "relationship", "label": RELATIONSHIP_LABEL,
                     "value": person.relationship})
    if person.research:
        rows.append({"kind": "research", "label": RESEARCH_LABEL, "value": person.research})
    if person.id and not person.is_me:
        # Its silos (`rouh/silos.py`): Rouh's own, like the two above, and changed on the card. `value` is
        # the words, for a card filed as a step; the page draws the chips and the choices.
        from . import silos

        uid, oid = person.account()
        if uid:
            rows.append({"kind": "silos", "label": SILOS_LABEL, "value": silos.said(uid, oid, person.silos),
                         "keys": silos.ordered(uid, oid, person.silos),
                         "chips": silos.chips(uid, oid, person.silos),
                         "choices": [s.chip() for s in silos.of(uid, oid)],
                         "said": person.silos_said().split(": ", 1)[-1] if person.silos else
                         "In no silo yet: press the ones they belong to."})
    return rows


def _with_profile(block: dict, person) -> dict:
    """A contact block that says which contact it is, and what Rouh knows of them."""
    if person is None or not person.id:
        return block
    block["rows"] = list(block.get("rows") or []) + _profile_rows(person)
    block["contact"] = person.id
    block["research_said"] = person.research_said()
    if person.is_me:
        block["me"] = True
    if person.photo:
        block["photo"] = person.photo
    return block


def _with_addresses(block: dict, person) -> dict:
    """Every address of the contact as one list (`rouh/person_addresses.py`): its label from the card, where
    it comes from, its silo and, for the person's own, whether it is a connected mailbox. The page draws
    it in place of the card's email rows, which stay in `rows` for a card filed as a step."""
    if person is None or not person.id:
        return block
    try:
        from . import person_addresses

        uid, oid = person.account()
        if uid:
            block["addresses"] = person_addresses.view(uid, oid, person)
    except Exception:  # noqa: BLE001 - the card's own rows still say the addresses
        log.exception("contacts: the addresses of %s could not be listed", person.id)
    return block


def _with_aka(block: dict, person) -> dict:
    """The contact's "Also known as" (`rouh/synapse/aka.py`): every identifier they hold beyond the iCloud
    card - Slack members, names written in mail and notes, the addresses Rouh knows - each with Unlink, and a
    search to link another one in. The addresses that are Rouh's own are drawn there, with their Unlink,
    instead of as rows of the card (`in_aka`); the rows keep them for a card filed as a step."""
    ds_id = str((person.profile or {}).get("dataset_id") or "") if person is not None else ""
    if not ds_id or not person.id:
        return block
    try:
        from .synapse import aka, db

        ds = db.row("SELECT * FROM synapse.dataset WHERE id = %s::uuid", (ds_id,))
        if ds is None:
            return block
        block["aka"] = aka.view(ds, person.id)
        block["people_ds"] = ds_id
        for row in block.get("rows") or []:
            if row.get("kind") == "email" and (person.card is None or row.get("label") == "known to Rouh"):
                row["in_aka"] = True
    except Exception:  # noqa: BLE001 - the card is still the card
        log.exception("contacts: what %s is also known as could not be read", person.id)
    return block


def profile_card(person, *, state: str = SHOWN, status: str = "") -> dict:
    """A contact as it is, with who they are to the person and what is known of them.

    What `show_contact` puts on the screen, and what a change to either field
    redraws: the card if there is one, and Rouh's own contact if there is not.
    """
    fields = _fields(person.card) if person.card is not None else {
        "name": person.name, "organisation": person.organisation, "phones": [], "emails": [
            {"address": one, "label": ""} for one in person.emails],
        "birthday": "", "note": ""}
    name = fields["name"] or "(no name)"
    rows = _rows(fields, None)
    block = {"block": "contact", "state": state, "new": False, "name": name,
             "status": status or ("You" if person.is_me else
                                  "In your iCloud contacts" if person.card is not None
                                  else "Known to Rouh, not in iCloud"),
             "rows": rows,
             "foot": ("Mail from any of these addresses is known to be you, once Gmail "
                      "confirms it came from there. Nothing here goes to iCloud."
                      if person.is_me else
                      "Who they are to you, the research and their silos are Rouh's "
                      "own, and never go to iCloud. Change any of them here, or tell Rouh.")}
    if person.card is None:
        # Rouh's own contact: its addresses are the contact itself, not extra ones.
        block["rows"] = rows + [r for r in _profile_rows(person) if r["kind"] != "email"]
        block["contact"] = person.id
        block["research_said"] = person.research_said()
        if person.is_me:
            block["me"] = True
        if person.photo:
            block["photo"] = person.photo
    else:
        _with_profile(block, person)
    _with_aka(block, person)
    _with_addresses(block, person)
    from . import card_call, card_directions

    card_call.mark(block)
    # Directions from their contact card (night 43, `rouh/card_directions.py`): each address one press from Maps.
    card_directions.mark(block)
    return {"title": f"{'You' if person.is_me else 'Contact'}: {name}",
            "description": (f"the contact {name}, with who they are to you and the online "
                            "research about them"),
            "blocks": [block]}


def contact_card(after, before, state: str, *, remark: str = "", person=None) -> dict:
    """A contact as the screen shows it: a card of one `contact` block.

    `after` is the contact as a save would leave it, or as iCloud kept it;
    `before` is how it read before this change, or None for somebody new.
    `person` is the contact as Rouh knows it (`people.Person`), once it is
    saved, which adds who they are to the person and the research, and makes
    both changeable on the card. The page draws the block (`contactBlock` in
    app.js), and a step it is filed into keeps it whole (`steps.block_text`).
    """
    after = _fields(after)
    before = _fields(before) if before is not None else None
    name = after["name"] or "(no name)"
    new = before is None
    rows = _rows(after, before)
    was_name = before["name"] if before is not None and before["name"] != after["name"] else ""
    marked = sum(1 for row in rows if row.get("change")) + (1 if was_name else 0)
    counted = "" if new else f"{_many(marked, 'change')} marked. "
    if state == SAVED:
        title = f"Contact {'added' if new else 'changed'}: {name}"
        description = (f"the contact {name} as it was {'added to' if new else 'changed in'} "
                       "the iCloud contacts")
        status = "Saved to iCloud"
        foot = (f"{counted}This is what iCloud kept. It reaches the phone when the phone "
                "next syncs with iCloud.")
    else:
        title = f"Contact to {'add' if new else 'change'}: {name}"
        description = (f"the contact {name} as it would be "
                       f"{'added to' if new else 'changed in'} the iCloud contacts, shown "
                       "before saving")
        status = "Not saved yet"
        foot = f"{counted}Nothing is saved until you say yes."
    block = {"block": "contact", "state": state, "new": new, "name": name,
             "status": status, "rows": rows, "foot": foot}
    if was_name:
        block["was_name"] = was_name
    if remark:
        block["remark"] = remark
    if state == SAVED:
        _with_profile(block, person)
        if person is not None:
            _with_aka(block, person)
            _with_addresses(block, person)
    # Call from their contact card (night 42, `rouh/card_call.py`): its numbers one press from ringing.
    from . import card_call, card_directions

    card_call.mark(block)
    # Directions from their contact card (night 43, `rouh/card_directions.py`): each address one press from Maps.
    card_directions.mark(block)
    return {"title": title, "description": description, "blocks": [block]}


def _person_said(row: dict) -> str:
    head = row["name"] or "(no name)"
    if row.get("organisation"):
        head += f" - {row['organisation']}"
    lines = [head]
    from . import job_title

    title = job_title.of(row)
    if title:
        lines.append(f"  job title {title}")
    if row.get("phones"):
        lines.append("  " + "; ".join(_labelled(p["number"], p.get("label", ""))
                                      for p in row["phones"]))
    if row.get("emails"):
        lines.append("  " + "; ".join(e["address"] + (f" ({e['label']})" if e.get("label")
                                                      else "") for e in row["emails"]))
    from . import postal_address

    for one in postal_address.of(row):
        lines.append(f"  address{' (' + one['label'] + ')' if one.get('label') else ''}: {one['address']}")
    if row.get("birthday"):
        lines.append(f"  birthday {vcard.birthday_words(row['birthday'])}")
    if row.get("note"):
        note = " ".join(row["note"].split())
        lines.append("  note: " + (note[:200] + "…" if len(note) > 200 else note))
    lines.append(f"  id {row['id']}")
    return "\n".join(lines)


def _known_said(person, *, whole: bool = False) -> str:
    """A contact as Rouh knows them, for the model: the card, then Rouh's own two fields.

    `whole` gives all of the research, for `show_contact`; a search gives the
    start of it, because one of those is a list of people.
    """
    if person.card is not None:
        said = _person_said(person.card)
        lines = said.split("\n")[:-1]                   # the id goes last, below
    else:
        lines = [f"{person.name or '(no name)'} - Rouh's own contact, not in iCloud"]
        if person.emails:
            lines.append("  " + "; ".join(person.emails))
    if person.card is not None and person.own_emails:
        lines.append("  also known to Rouh: " + "; ".join(person.own_emails))
    if person.is_me:
        lines.append("  this is the person themselves: every address here is theirs")
    lines.append("  my relationship, in the person's own words: "
                 + (person.relationship if person.relationship else "not said yet"))
    if not person.is_me:
        lines.append("  silos: " + person.silos_said().split(": ", 1)[-1].rstrip("."))
    if person.research:
        lines.append(f"  online research ({person.research_said()}):")
        if whole:
            lines += ["    " + line for line in person.research.split("\n")]
        else:
            lines.append("    " + person.gist() + " (show_contact reads all of it)")
    else:
        lines.append("  online research: none yet")
    li = person.linkedin
    if li.get("status") == "unresolved" and li.get("candidates"):
        lines.append(f"  LinkedIn: not sure which profile is theirs ({li.get('why') or 'several people'}); "
                     f"{len(li['candidates'])} candidates wait for the person's pick, drawn with "
                     "show_contact, each with a Research button that keeps the one picked here")
    if person.photo:
        lines.append("  has a picture, drawn on their contact card")
    lines.append(f"  id {person.id}")
    return "\n".join(lines)


def _many(count: int, thing: str) -> str:
    if count == 1:
        return f"1 {thing}"
    return f"{count} {'people' if thing == 'person' else thing + 's'}"



__all__ = ["DECLINED", "NOT_ACCEPTED", "REVOKED", "SAVED", "SHOWN", "UNSAVED", "AppleStore",
           "ContactDesk", "Held", "Outcome", "Said", "check_apple_id", "check_password",
           "contact_card", "declined", "key_for", "new_key", "profile_card"]
