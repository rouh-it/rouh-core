"""The consent round trip, and keeping an access token alive afterwards.

Real OAuth 2.0 against Google, using **the asking user's own organisation's**
client. There is no Rouh-wide client anywhere in this file, and there is no
fallback to one: `google_store.GoogleStore.client_for` raises `NotSetUp` and
the caller says so to the person.

The three things that make the round trip safe:

- **Offline access.** ``access_type=offline`` so a refresh token is issued, and
  ``prompt=consent`` when this user has no refresh token yet, because Google
  only issues one on a consent the person actually saw.
- **Incremental authorisation.** ``include_granted_scopes=true``, so a later
  stage can ask for one more capability without throwing away what is already
  granted.
- **A state parameter that cannot be guessed or reused.** It is a random nonce
  with an HMAC of that nonce beside it, so a forged one is thrown out before
  the database is touched; the nonce is then a row that is deleted as it is
  read, so a real one works exactly once; and the row carries the session it
  was issued to, so a state minted in one browser cannot be finished in
  another.

The refresh is serialised per user. Two tool calls that both want mail at the
same moment must not both post a refresh: Google would issue two tokens, one of
them would be stored, and the other would be handed to a caller who then gets a
401 nobody can explain.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import logging
import os
import time
import urllib.parse

import httpx

from .google_store import Connection, GoogleStore
from .redaction import scrub
from .tenancy import Identity

log = logging.getLogger("rouh.google")

#: The one Drive scope, named because more than one thing checks for it.
#: It is the whole of Drive: reading a file, writing one, and changing who a
#: file is shared with. The narrower grants Google offers - `drive.file`,
#: `drive.readonly` - cannot touch the permissions of a file at all, so
#: sharing works with exactly this one and with nothing less.
DRIVE_SCOPE = "https://www.googleapis.com/auth/drive"

#: The narrower read-only grant Google also offers. Rouh never asks for it -
#: it cannot write a file or change who can open one - but a connection made
#: before this install, or by another tool, may hold it, and it is enough for
#: everything the listing tools do. Named so the shared drive check can accept
#: it rather than insisting on the wide one for a read.
DRIVE_READONLY_SCOPE = "https://www.googleapis.com/auth/drive.readonly"

#: Either of these can see a shared drive. The third grant Google offers,
#: `drive.file`, cannot: it only ever shows the app its own files, so a shared
#: drive full of the organisation's documents is invisible to it and
#: `drives.list` refuses it outright. That is the whole reason this tuple
#: exists rather than a single scope name.
SHARED_DRIVE_SCOPES: tuple[str, ...] = (DRIVE_SCOPE, DRIVE_READONLY_SCOPE)

#: What a person hears when the connection cannot reach a shared drive. It
#: names the button rather than the scope, because the person hearing it is
#: deciding whether to press something, not debugging OAuth.
SHARED_DRIVES_NEED = (
    "Shared drives need this Google account connected with full Drive access, "
    "and this connection was not given it. Open Settings and press Connect "
    "Google to grant it again, then ask me for the shared drives once more.")

#: The whole of Google Calendar, and the broadest calendar grant Google has:
#: every calendar the account can see - its own, and every one somebody has
#: shared with it - read, written and deleted from, events and calendars both.
#: Every narrower calendar scope (`calendar.events`, `calendar.readonly`,
#: `calendar.calendarlist`, `calendar.freebusy` and the rest) is a part of this
#: one, so nothing a calendar tool will ever want is outside it.
CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar"

#: What a person hears when a calendar call finds the grant without it. The
#: button, not the URL, for the same reason as `SHARED_DRIVES_NEED`.
CALENDAR_NEEDED = (
    "Google Calendar is not part of this Google connection yet: it was made "
    "before Rouh asked for calendars. Open Settings and press Grant the new "
    "access, allow Google Calendar on Google's screen, and ask me again.")

#: What Rouh asks for. Read and write, both, because it is an assistant and
#: not a reader: mail it can read, label, archive and trash (gmail.modify),
#: mail it can send (gmail.send), drafts it can write (gmail.compose), Drive it
#: can read, write and share (drive), documents it can read and edit
#: (documents), every calendar the account can see (calendar), and who the
#: person is, so Settings can name the account.
#:
#: Adding one to this list is not free. A person who granted the old set keeps
#: working until the moment something needs the new capability, so the mismatch
#: is found up front instead - see `missing_scopes` - and the answer is to
#: press Connect again, not an error in the middle of sending.
SCOPES: tuple[str, ...] = (
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.compose",
    DRIVE_SCOPE,
    "https://www.googleapis.com/auth/documents",
    CALENDAR_SCOPE,
)

#: The scopes every call that needs one asks for itself, with `needs_scope`,
#: rather than the whole connection being stopped when a grant lacks them.
#:
#: Everything before Calendar was checked the other way: a grant missing any
#: of them stopped every call, mail included, until Connect was pressed again.
#: That is right for a scope the older calls use without saying so, and wrong
#: for one only new calls use. Calendar came on 24 September 2026, when every
#: connection already sent mail, read Drive and edited documents perfectly
#: well, and one of them - the forgotten-password email - goes out through the
#: connection with nobody signed in to press anything. Stopping all of that
#: for want of a calendar would take away what a person has for the sake of
#: what they have not granted yet. So a grant without it keeps everything it
#: does have, every calendar call is refused up front with `CALENDAR_NEEDED`,
#: and Settings still says what is missing and still asks for it again.
CHECKED_PER_CALL: frozenset[str] = frozenset({CALENDAR_SCOPE})

#: Which granted scopes add up to a capability a person recognises. Settings
#: says "Mail, Drive, Docs, Calendar", not eight URLs.
CAPABILITIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Mail", ("https://www.googleapis.com/auth/gmail.modify",
              "https://www.googleapis.com/auth/gmail.send",
              "https://www.googleapis.com/auth/gmail.compose")),
    ("Drive", (DRIVE_SCOPE,)),
    ("Docs", ("https://www.googleapis.com/auth/documents",)),
    ("Calendar", (CALENDAR_SCOPE,)),
)

#: What each scope lets Rouh do, said the way a person would say it. Used in
#: the sentence that asks somebody to connect again, so that sentence names the
#: capability that is missing rather than a URL.
SCOPE_WORDS: dict[str, str] = {
    "https://www.googleapis.com/auth/gmail.modify": "read, label and archive mail",
    "https://www.googleapis.com/auth/gmail.send": "send mail",
    "https://www.googleapis.com/auth/gmail.compose": "write drafts",
    DRIVE_SCOPE: "read, write and share files in Drive",
    "https://www.googleapis.com/auth/documents": "read and edit Google Docs",
    CALENDAR_SCOPE: "read and change every calendar it can see",
    "https://www.googleapis.com/auth/userinfo.email": "see which account it is",
    "openid": "see which account it is",
}

#: The Google APIs an administrator has to switch on in their project, in the
#: words the Cloud console uses for them.
GOOGLE_APIS: tuple[str, ...] = ("Gmail API", "Google Drive API", "Google Docs API",
                                "Google Calendar API")

#: How long before an access token expires it is treated as expired. A token
#: that is valid for four more seconds is not worth starting a request with.
REFRESH_MARGIN_SECONDS = 120

#: A token exchange is one small request to one endpoint. If it has not
#: answered in this long it is not going to.
TIMEOUT_SECONDS = 20.0


def path_of(url: str) -> str:
    return urllib.parse.urlsplit(url).path or "/"


def redirect_uri(public_url: str) -> str:
    """The address Google is allowed to come back to, on one of Rouh's names.

    Built from a configured public name and nothing else: the configured
    public URL, or `rouh.web.common.public_base`, which picks the name the
    request came in on only when it is one of `config.public_hosts`. It is
    never taken raw from a Host or X-Forwarded-Host header: those come from
    the caller, and an attacker who can set one could otherwise have Google
    deliver an authorisation code to a site they own.
    """
    return (public_url or "").rstrip("/") + "/auth/google/callback"


#: What a person is told when Google will not come back to this address. The
#: fix is one line in the organisation's Google Cloud console, and only an
#: administrator of that project can make it, so the sentence says exactly
#: which line and where.
NOT_REGISTERED = (
    "Google will not send anybody back to {redirect} yet: that address is not "
    "one of the Authorized redirect URIs on this organisation's Google OAuth "
    "client. An administrator adds it in the Google Cloud console (APIs & "
    "Services, Credentials, the OAuth client, Authorized redirect URIs), and "
    "then this works.")


async def redirect_accepted(auth_url: str, client_id: str, redirect: str, *,
                            timeout: float = 4.0) -> bool | None:
    """Whether Google will send a person back to `redirect` for this client.

    Asked of Google itself, before a person is sent there: the authorisation
    endpoint checks the redirect address against the client's registered ones
    before anybody signs in, and answers a mismatch straight away. Without this
    a Rouh whose address had changed (22 September 2026) sent
    people to Google's own error page, which shows the browser's default
    account, offers no way to choose another and no way back - which is what
    Petar met the first time he pressed Sign in with Google.

    True when Google took it, False when it said redirect_uri_mismatch, and
    None when it could not tell - Google unreachable, or an answer in a shape
    this does not know - in which case the caller goes ahead as before.
    """
    query = {"client_id": client_id, "redirect_uri": redirect,
             "response_type": "code", "scope": "openid email"}
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as http:
            got = await http.get(auth_url + "?" + urllib.parse.urlencode(query))
    except httpx.HTTPError:
        return None
    where = got.headers.get("location") or ""
    said = got.text if got.status_code >= 400 else ""
    if "redirect_uri_mismatch" in said:
        return False
    if "authError" in where:
        # Google's error page carries the reason as a base64 message in the
        # address; the code is in it as plain text.
        raw = urllib.parse.parse_qs(urllib.parse.urlsplit(where).query).get("authError", [""])[0]
        try:
            decoded = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
        except (ValueError, TypeError):
            return None
        return False if b"redirect_uri_mismatch" in decoded else None
    if got.status_code in (200, 302, 303) and "error" not in where:
        return True
    return None


def capabilities_of(scopes) -> list[str]:
    """Which of Mail, Drive, Docs and Calendar these granted scopes add up to."""
    held = set(scopes or ())
    return [name for name, needed in CAPABILITIES if held.intersection(needed)]


def missing_scopes(scopes) -> list[str]:
    """Which configured scopes this grant does not carry, in `SCOPES` order.

    This is the whole of the scope check, and it is deliberately a plain subset
    test rather than a table of which scope implies which. Every scope in
    `SCOPES` is the broad one of its family, so nothing Google can grant
    satisfies one of them without being it.

    A connection with no scopes recorded at all is one this build has never
    seen the grant of. Treating that as "everything is missing" would tell a
    working connection to reconnect for no reason, so it is left alone and the
    call itself decides.
    """
    held = set(scopes or ())
    if not held:
        return []
    return [one for one in SCOPES if one not in held]


def missing_for_every_call(scopes) -> list[str]:
    """What this grant lacks that stops every call, not only the ones needing it.

    `missing_scopes` without `CHECKED_PER_CALL`: the scopes older calls rely on
    without naming them. What is left out is still missing, and Settings still
    says so and asks for it again; it is checked by the calls that need it.
    """
    return [one for one in missing_scopes(scopes) if one not in CHECKED_PER_CALL]


def why_reconnect(lacking, *, say_where: bool = True) -> str:
    """The sentence shown when the grant is older than what Rouh now asks for.

    It names the capabilities rather than the URLs, because the person reading
    it is deciding whether to press a button, not debugging OAuth.

    `say_where` adds where the button is. It belongs in a spoken answer and in
    the log, where the person is nowhere near the page. On the Google card in
    Settings it does not: they are already in Settings and the button is the
    next thing under the sentence, so telling them to go and find it is telling
    them to do what they have already done.
    """
    words = []
    for one in lacking or ():
        said = SCOPE_WORDS.get(one, one)
        if said not in words:
            words.append(said)
    what = ", ".join(words[:-1]) + " and " + words[-1] if len(words) > 1 else (
        words[0] if words else "more access")
    said = (f"Rouh now needs permission to {what}, which this connection was "
            f"not given.")
    if say_where:
        said += " Open Settings and press Connect Google to grant it."
    return said


def why_missing(scope: str) -> str:
    """The sentence for one capability a call needs and this grant lacks.

    `why_reconnect` is the one a person reads on the page, so it names
    capabilities and never a URL. This one is raised in the middle of a call,
    where the thing that has to be fixed is a named scope in a consent screen,
    so it says the scope itself as well as what it is for. Nothing is sent,
    because nothing is started: the check happens before the request.
    """
    does = SCOPE_WORDS.get(scope, "do that")
    return (f"This Google connection was never granted {scope}, so it cannot "
            f"{does}. Open Settings and press Connect Google to grant it, or ask "
            f"me for the consent link.")


class ConsentFailed(RuntimeError):
    """Google refused, or the person said no. The message is shown as it is."""


class NotConnected(RuntimeError):
    """This person has not connected a Google account."""


class NeedsReconnect(RuntimeError):
    """Google has withdrawn the grant and the person has to consent again."""


class NeedsMoreAccess(NeedsReconnect):
    """The grant is live but older than what Rouh now asks for.

    A subclass of `NeedsReconnect` because everything that already handles a
    withdrawn grant handles this the same way - stop, and say to press Connect
    again. It is its own class so that Settings and the assistant can say the
    true thing, which is that nothing is broken and one button fixes it.
    """

    def __init__(self, message: str, lacking=()) -> None:
        super().__init__(message)
        self.lacking = tuple(lacking)


class GoogleAuth:
    """Builds consent URLs, finishes them, and keeps tokens alive."""

    def __init__(self, store: GoogleStore, cfg, *, client_factory=None) -> None:
        #: The two tables. Public, because `google_api/clients.py` has to mark a
        #: connection as needing reconnection when Google refuses its token.
        self.store = store
        self._cfg = cfg
        self._client_factory = client_factory or self._default_client
        #: One lock per user, so two callers refreshing the same connection at
        #: the same moment do it once. Guarded by `_locks_lock` because it is
        #: built lazily from several tasks.
        self._locks: dict[str, asyncio.Lock] = {}
        self._locks_lock = asyncio.Lock()

    # --- the addresses ------------------------------------------------------

    @property
    def auth_endpoint(self) -> str:
        return self._cfg.google_auth_url

    @property
    def token_endpoint(self) -> str:
        return self._cfg.google_token_url

    @property
    def revoke_endpoint(self) -> str:
        return self._cfg.google_revoke_url

    @property
    def userinfo_endpoint(self) -> str:
        return self._cfg.google_userinfo_url

    def redirect_uri(self, base: str = "") -> str:
        """Google's way back, on `base` (the name the person is on) or the public URL."""
        return redirect_uri(base or self._cfg.public_url)

    def _default_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=TIMEOUT_SECONDS)

    # --- the state parameter ------------------------------------------------

    def _sign(self, nonce: str) -> str:
        """The signature beside the nonce, so a made-up state is thrown out cheaply.

        This is a filter, not the security: what makes a state safe is that the
        nonce is 18 random bytes, is a row in the database, and is deleted as it
        is read. The key is the instance's own signing secret, Django's
        SECRET_KEY, since the sign-in moved to Django on 23 September 2026;
        before that it was a passphrase this process no longer has.
        """
        from django.utils.crypto import salted_hmac

        return salted_hmac("rouh.google_oauth.state", nonce,
                           algorithm="sha256").hexdigest()[:32]

    def mint_state(self, who: Identity, session: str = "") -> str:
        """A state nobody can forge, that works once, for this session only."""
        nonce = base64.urlsafe_b64encode(os.urandom(18)).decode().rstrip("=")
        self.store.remember_state(nonce, who.user_id, who.org_id,
                                  _fingerprint(session))
        return f"{nonce}.{self._sign(nonce)}"

    def take_state(self, state: str, session: str = "") -> dict:
        """Check a state and spend it, or raise with a sentence to show."""
        raw = (state or "").strip()
        if "." not in raw:
            raise ConsentFailed("That sign-in did not come back with a valid state, so it was refused.")
        nonce, signature = raw.rsplit(".", 1)
        if not hmac.compare_digest(signature, self._sign(nonce)):
            raise ConsentFailed("That sign-in did not come back with a valid state, so it was refused.")
        found = self.store.take_state(nonce)
        if found is None:
            raise ConsentFailed(
                "That sign-in had already been used or had expired. Press Connect Google again."
            )
        if found["session"] and found["session"] != _fingerprint(session):
            raise ConsentFailed(
                "That sign-in was started in a different browser session, so it was refused."
            )
        return found

    # --- step one: send them to Google --------------------------------------

    def consent_url(self, who: Identity, state: str, *, force_consent: bool | None = None,
                    base: str = "") -> str:
        """Where to send this person, built with **their** organisation's client.

        Raises `NotSetUp` when their organisation has not registered one.
        """
        client = self.store.client_for(who.org_id)
        lacking: list[str] = []
        if force_consent is None:
            held = self.store.connection(who.user_id, who.org_id)
            lacking = missing_scopes(held.scopes) if held else []
            # Ask again, on a screen the person answers, when there is no
            # refresh token to renew with, and when the grant that is held is
            # older than what Rouh now asks for. The second one is what makes
            # a widened scope set land: Google reissues a refresh token for the
            # whole new set only on a consent that was actually shown, and
            # without it the connection keeps the narrower grant for ever.
            force_consent = not (held and held.refresh_token) or bool(lacking)
        query = {
            "client_id": client.client_id,
            "redirect_uri": self.redirect_uri(base),
            "response_type": "code",
            "scope": " ".join(SCOPES),
            # Offline, so a refresh token is issued and Rouh can act on a
            # schedule rather than only while the person is watching.
            "access_type": "offline",
            # Incremental: a later stage can ask for one more capability and
            # keep everything already granted.
            "include_granted_scopes": "true",
            "state": state,
        }
        if force_consent:
            # Google issues a refresh token only on a consent screen the person
            # actually answered. Without this, a second connect returns an
            # access token and nothing to renew it with.
            query["prompt"] = "consent"
        url = self.auth_endpoint + "?" + urllib.parse.urlencode(query)
        if lacking:
            # Said out loud in the log as well as on the page, because the
            # person whose connection this is may hear about it in a spoken
            # turn and never open Settings at all.
            log.info(
                "google consent for user %s in org %s is being asked for again: the "
                "grant it holds is missing %s. Send them to /auth/google/start",
                who.user_id, who.org_id, ", ".join(lacking))
        return url

    # --- step two: what Google sent back -------------------------------------

    async def finish(self, who: Identity, code: str, base: str = "") -> Connection:
        """Exchange the code, find out whose account it is, and store it."""
        client = self.store.client_for(who.org_id)
        form = {
            "code": code,
            "client_id": client.client_id,
            "client_secret": client.client_secret,
            "redirect_uri": self.redirect_uri(base),
            "grant_type": "authorization_code",
        }
        async with self._client_factory() as http:
            answer = await http.post(self.token_endpoint, data=form)
            if answer.status_code >= 400:
                raise ConsentFailed(_google_said(answer, self.redirect_uri(base)))
            payload = answer.json()
            access = payload.get("access_token") or ""
            if not access:
                raise ConsentFailed("Google did not return an access token.")
            granted = tuple((payload.get("scope") or "").split()) or SCOPES
            expires_at = time.time() + float(payload.get("expires_in") or 3600)
            email, account = await self._whose_account(http, access)

        self.store.save_connection(
            who.user_id, who.org_id, google_email=email, google_account=account,
            access_token=access, refresh_token=payload.get("refresh_token") or "",
            expires_at=expires_at, scopes=granted,
        )
        held = self.store.connection(who.user_id, who.org_id)
        assert held is not None
        log.info("google connected for user %s in org %s as %s",
                 who.user_id, who.org_id, email)
        return held

    async def _whose_account(self, http: httpx.AsyncClient, access: str) -> tuple[str, str]:
        try:
            answer = await http.get(
                self.userinfo_endpoint,
                headers={"Authorization": f"Bearer {access}"},
            )
            if answer.status_code >= 400:
                return "", ""
            body = answer.json()
            return (body.get("email") or ""), (body.get("sub") or "")
        except Exception:
            # Not knowing the address is a worse Settings page, not a failure
            # to connect. Everything else about the connection is fine.
            log.warning("google connected but its account could not be read")
            return "", ""

    # --- keeping it alive ----------------------------------------------------

    async def _lock_for(self, user_id: str) -> asyncio.Lock:
        async with self._locks_lock:
            lock = self._locks.get(user_id)
            if lock is None:
                lock = asyncio.Lock()
                self._locks[user_id] = lock
            return lock

    async def access_token(self, who: Identity) -> str:
        """A token that is good right now, refreshing if it is about to expire.

        Every call that reaches Google goes through here. Concurrent callers
        for the same person wait on one lock and only one of them refreshes.
        """
        held = self.store.connection(who.user_id, who.org_id)
        if held is None:
            raise NotConnected("This Google account is not connected.")
        self._check_scopes(who, held)
        if held.needs_reconnect:
            raise NeedsReconnect(held.trouble or
                                 "Google has withdrawn this connection. Connect it again.")
        if held.access_token and held.expires_at - time.time() > REFRESH_MARGIN_SECONDS:
            return held.access_token

        lock = await self._lock_for(who.user_id)
        async with lock:
            # Somebody else may have refreshed while this call was waiting.
            # Reading again inside the lock is what makes "only once" true.
            held = self.store.connection(who.user_id, who.org_id)
            if held is None:
                raise NotConnected("This Google account is not connected.")
            if held.needs_reconnect:
                raise NeedsReconnect(held.trouble or
                                     "Google has withdrawn this connection. Connect it again.")
            if held.access_token and held.expires_at - time.time() > REFRESH_MARGIN_SECONDS:
                return held.access_token
            return await self._refresh(who, held)

    def _check_scopes(self, who: Identity, held: Connection) -> None:
        """Stop before the call when the grant is older than what Rouh asks for.

        This is the whole point of checking here rather than reading the error
        Gmail sends back. Every request goes through `access_token`, so one
        check covers every tool; and it happens before anything has been done,
        so the answer is "press Connect again" rather than half a message sent.

        The stored access token is dropped as part of saying so, so nothing can
        carry on using the narrower grant it stands for. It comes back whole on
        the next consent.
        """
        lacking = missing_for_every_call(held.scopes)
        if not lacking:
            return
        said = why_reconnect(lacking)
        if not held.needs_reconnect or held.trouble != said:
            self.store.needs_reconnect(who.user_id, who.org_id, said)
            log.warning(
                "google connection for user %s in org %s was granted before Rouh "
                "asked for %s, so it has to be connected again at /auth/google/start",
                who.user_id, who.org_id, ", ".join(lacking))
        raise NeedsMoreAccess(said, lacking)

    async def _refresh(self, who: Identity, held: Connection) -> str:
        if not held.refresh_token:
            self.store.needs_reconnect(
                who.user_id, who.org_id,
                "There is no refresh token for this connection, so it cannot be renewed.")
            raise NeedsReconnect(
                "This Google connection has no refresh token, so it has to be connected again.")
        client = self.store.client_for(who.org_id)
        form = {
            "client_id": client.client_id,
            "client_secret": client.client_secret,
            "refresh_token": held.refresh_token,
            "grant_type": "refresh_token",
        }
        async with self._client_factory() as http:
            answer = await http.post(self.token_endpoint, data=form)
        if answer.status_code >= 400:
            said = _google_said(answer, self.redirect_uri())
            # invalid_grant is Google saying the grant is gone: the person
            # removed Rouh from their account, or the refresh token expired
            # because the app is still in Testing. Either way it is a
            # reconnect, not a retry.
            if "invalid_grant" in said or answer.status_code in (400, 401):
                self.store.needs_reconnect(who.user_id, who.org_id, said)
                raise NeedsReconnect(
                    "Google has withdrawn this connection. Open Settings and connect it again.")
            raise ConsentFailed(said)
        payload = answer.json()
        access = payload.get("access_token") or ""
        if not access:
            raise ConsentFailed("Google did not return a new access token.")
        expires_at = time.time() + float(payload.get("expires_in") or 3600)
        self.store.store_access_token(who.user_id, who.org_id, access, expires_at)
        log.info("google access token renewed for user %s", who.user_id)
        return access

    # --- taking it away -------------------------------------------------------

    async def disconnect(self, who: Identity) -> bool:
        """Tell Google to forget the grant, then forget it here either way.

        The local tokens go whatever Google says. A revoke that fails must not
        leave a person still connected in a page that has just told them they
        are not.
        """
        held = self.store.connection(who.user_id, who.org_id)
        if held is not None:
            token = held.refresh_token or held.access_token
            if token:
                try:
                    async with self._client_factory() as http:
                        await http.post(self.revoke_endpoint, data={"token": token})
                except Exception:
                    log.warning("google revoke did not go through; removing the local tokens anyway")
        return self.store.forget_connection(who.user_id, who.org_id)


def _fingerprint(session: str) -> str:
    """A short hash of the session cookie, so the cookie itself is not stored."""
    if not session:
        return ""
    return hashlib.sha256(session.encode()).hexdigest()[:32]


def _google_said(answer: httpx.Response, redirect: str) -> str:
    """Google's own error, made readable, with the secrets taken out.

    An OAuth failure is nearly always one of two things and saying which saves
    an hour: the pair is wrong, or the redirect URI in the Cloud console is not
    the one this instance uses.
    """
    detail = ""
    try:
        body = answer.json()
        detail = (body.get("error_description") or body.get("error") or "").strip()
        code = (body.get("error") or "").strip()
    except Exception:
        detail = (answer.text or "").strip()[:400]
        code = ""
    said = scrub(detail) or f"Google answered {answer.status_code}."
    if code == "redirect_uri_mismatch" or "redirect_uri" in said:
        said += (f" The redirect URI registered in the Google Cloud console has to be "
                 f"exactly {redirect}")
    elif code in ("invalid_client", "unauthorized_client"):
        said += (" That usually means the client id or the client secret is not the pair "
                 "from this project. Enter them again in Settings.")
    return said
