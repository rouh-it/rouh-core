"""The person's own mailboxes, connected to be read and never written to.

Task 71, 30 September 2026: "Waiting on others" in the morning brief has to
work with the person's real email, and Rouh has to be able to read more than one
mailbox. Rouh's Google connection (`google_oauth.py`, GOOGLE.md) is not that:
it is Rouh's own mailbox (`ROUH_OWN_MAILBOXES`, `inbox.own`), granted
everything an assistant acts with - sending, drafting, labelling, Drive,
Calendar. A person's own mailbox is only ever read, so it is connected on its
own, as many as they like, each with the least Google grants that can read
mail and nothing else:

    openid, userinfo.email     which account it is, so the page can name it
    gmail.readonly             read messages and threads, search, and nothing more

`gmail.readonly` cannot send, draft, archive, delete, label or mark anything
read: Google refuses every write made with it. This file does not ask it to
either. `ReadOnlyGmail` makes GET requests and has no other kind to make, and
a grant that comes back from Google carrying anything wider than `READ_SCOPES`
is not kept at all (`MailboxAuth.finish`).

**Whose.** A mailbox is one person's, like every Google connection: each row
carries `user_id` and `org_id` and every query names both, and a mailbox is
always asked for by its id *and* its owner, so an id that belongs to somebody
else is "not found". Each mailbox has its own tokens, sealed with the same box
as every other credential (`encryption.SecretBox`); nothing that builds a
response ever reads them.

**The consent round trip** is the Google connection's own, through the same
organisation OAuth client and the same callback address, so nothing new has
to be registered in Google Cloud. The state carries the purpose `mailbox`
(`google_store.GoogleStore.remember_state`), and the callback hands a state of
that purpose here (`web/mailboxes.py`), so a state minted to connect a mailbox
can never be finished as the Google connection, or the other way round. It
asks `prompt=select_account consent`, so the person picks which of their
accounts to connect every time, and it leaves out `include_granted_scopes`,
so a Google account that also granted Rouh wider access through the same
client is not handed that access again here.

**Forwarding, when the person allows it.** Petar, 4 October 2026, asking Rouh
to forward a whole conversation from his own inbox to a contact. Forwarding is
sending, and `gmail.readonly` cannot send, so a mailbox can be given exactly
one more grant, on its own and only when the person presses Allow forwarding
beside it in Settings: `gmail.send`, which sends a message and can read,
change or delete nothing. Nothing else is ever asked for - no modify, no
compose, no labels - so the mailbox is still read for everything else.

- The consent asks for `FORWARD_SCOPES` with the mailbox's own address as the
  `login_hint`, its state carries `forward:<id>` (`FORWARDING`), and a grant
  for any other account than that mailbox's is not kept (`MailboxAuth.finish`).
- What it allows is narrower than the scope. Only one request can ever carry
  it: `ForwardingGmail.send`, which `inboxes.ForwardClients` hands nothing but
  a forward's `POST /messages/send`, and only `forward_mail` and
  `forward_thread` open one (`inboxes.open_to_forward`). Every other write is
  refused exactly as before, the brief's nudge from a mailbox included.
- Taking it away is Disconnect, which withdraws the whole grant at Google, and
  then connecting the mailbox again, read-only.

**Disconnecting** forgets the tokens here, and asks Google to withdraw the
grant only when nothing else on this install holds the same Google account
through the same client. Google withdraws a grant for the account and the
client together, not for one token, so revoking a read-only mailbox that
is also Rouh's own would otherwise cut Rouh's own connection off too.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import os
import time
import urllib.parse
from dataclasses import dataclass, field

import httpx

from .encryption import CannotOpen, SecretBox
from .redaction import scrub
from .tenancy import Identity

log = logging.getLogger("rouh.mailboxes")

#: The consent state's purpose (`google_store.GoogleStore.remember_state`).
PURPOSE = "mailbox"

READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"

#: Everything a mailbox is asked for. The least that reads mail and names the account.
READ_SCOPES: tuple[str, ...] = (
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    READONLY_SCOPE,
)

SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"

#: What a mailbox is asked for when the person allows forwarding from it: the
#: same, and sending, which reads, changes and deletes nothing.
FORWARD_SCOPES: tuple[str, ...] = READ_SCOPES + (SEND_SCOPE,)

#: How a consent state says it is allowing forwarding, and for which mailbox:
#: `forward:<id>`, in the state's `next_path`.
FORWARDING = "forward:"

#: What Google may say back for the same grant. `email` and `profile` are the
#: short names Google sometimes answers `userinfo.*` with.
GRANTS_KEPT = frozenset(READ_SCOPES) | {
    "email", "profile", "https://www.googleapis.com/auth/userinfo.profile"}

#: How many mailboxes one person may connect. Generous; a list read every morning.
MOST = 8

REFRESH_MARGIN_SECONDS = 120
TIMEOUT_SECONDS = 20.0
READ_SECONDS = 30.0
ATTEMPTS = 3


class Refused(RuntimeError):
    """Something the person has to be told, in words that can be shown as they are."""


class NotConnected(Refused):
    """That mailbox is not connected for this person (or never was theirs)."""


class NeedsReconnect(Refused):
    """Google no longer accepts the mailbox's grant; Connect it again."""


@dataclass(frozen=True)
class Mailbox:
    """One mailbox, opened. The tokens never leave this process."""

    id: int
    user_id: str
    org_id: str
    email: str
    google_account: str
    access_token: str = field(repr=False, default="")
    refresh_token: str = field(repr=False, default="")
    expires_at: float = 0.0
    scopes: tuple[str, ...] = ()
    connected_at: float = 0.0
    needs_reconnect: bool = False
    trouble: str = ""

    def __str__(self) -> str:
        return f"<Mailbox {self.id} {self.email}>"


def can_forward(scopes) -> bool:
    """Whether a mailbox's grant lets Rouh forward from it, when the person asks."""
    held = set(scopes.split() if isinstance(scopes, str) else scopes or ())
    return SEND_SCOPE in held and READONLY_SCOPE in held


def summary(row) -> dict:
    """What a page may be told about a mailbox: never a token.

    `read_only` is whether nothing in it can be changed: a mailbox that may
    also forward is still that, because a forward only adds what it sent to
    its Sent, and nothing that was there is changed.
    """
    held = set((row.scopes or "").split())
    return {"id": row.id, "email": row.email, "connected_at": row.connected_at,
            "needs_reconnect": bool(row.needs_reconnect), "trouble": scrub(row.trouble or ""),
            "read_only": held <= GRANTS_KEPT | {SEND_SCOPE},
            "can_forward": can_forward(held)}


class MailboxStore:
    """The `read_mailboxes` rows, sealed and opened, always asked for by owner."""

    def __init__(self, box: SecretBox) -> None:
        self._box = box

    def _open(self, sealed: str) -> str:
        if not sealed:
            return ""
        try:
            return self._box.open_(sealed)
        except CannotOpen:
            return ""

    def _opened(self, row) -> Mailbox:
        return Mailbox(id=row.id, user_id=row.user_id, org_id=row.org_id, email=row.email,
                       google_account=row.google_account,
                       access_token=self._open(row.access_sealed),
                       refresh_token=self._open(row.refresh_sealed),
                       expires_at=row.expires_at or 0.0,
                       scopes=tuple((row.scopes or "").split()),
                       connected_at=row.connected_at or 0.0,
                       needs_reconnect=bool(row.needs_reconnect), trouble=row.trouble or "")

    @staticmethod
    def rows(who: Identity) -> list:
        from .models import ReadMailbox

        if not who or not who.user_id or not who.org_id:
            return []
        return list(ReadMailbox.objects.filter(user_id=who.user_id, org_id=who.org_id)
                    .order_by("connected_at", "id"))

    @staticmethod
    def row(who: Identity, mailbox_id) -> object | None:
        from .models import ReadMailbox

        try:
            ident = int(mailbox_id)
        except (TypeError, ValueError):
            return None
        if not who or not who.user_id or not who.org_id:
            return None
        return ReadMailbox.objects.filter(id=ident, user_id=who.user_id,
                                          org_id=who.org_id).first()

    def mailbox(self, who: Identity, mailbox_id) -> Mailbox | None:
        found = self.row(who, mailbox_id)
        return self._opened(found) if found is not None else None

    def save(self, who: Identity, *, email: str, google_account: str, access_token: str,
             refresh_token: str, expires_at: float, scopes) -> int:
        """Keep a mailbox that was just granted, or its new tokens if it was already here.

        A consent without a refresh token keeps the one already held, as the
        Google connection does (`GoogleStore.save_connection`).
        """
        from django.db import transaction

        from .models import ReadMailbox

        if not who.user_id or not who.org_id or not google_account:
            raise ValueError("a mailbox belongs to a user in an organisation, and to an account")
        with transaction.atomic():
            held = (ReadMailbox.objects.select_for_update()
                    .filter(user_id=who.user_id, org_id=who.org_id,
                            google_account=google_account).first())
            if held is None and ReadMailbox.objects.filter(
                    user_id=who.user_id, org_id=who.org_id).count() >= MOST:
                raise Refused(f"You can connect {MOST} mailboxes at most. Disconnect one first.")
            refresh = self._box.seal(refresh_token) if refresh_token else (
                held.refresh_sealed if held is not None else "")
            values = dict(email=email, access_sealed=self._box.seal(access_token),
                          refresh_sealed=refresh, expires_at=float(expires_at),
                          scopes=" ".join(scopes or ()), connected_at=time.time(),
                          needs_reconnect=False, trouble="")
            if held is None:
                held = ReadMailbox.objects.create(user_id=who.user_id, org_id=who.org_id,
                                                  google_account=google_account, **values)
            else:
                for key, value in values.items():
                    setattr(held, key, value)
                held.save()
            return held.id

    def store_access(self, mailbox: Mailbox, access_token: str, expires_at: float) -> None:
        from .models import ReadMailbox

        ReadMailbox.objects.filter(id=mailbox.id, user_id=mailbox.user_id,
                                   org_id=mailbox.org_id).update(
            access_sealed=self._box.seal(access_token), expires_at=float(expires_at),
            needs_reconnect=False, trouble="")

    @staticmethod
    def needs_reconnect(mailbox: Mailbox, why: str) -> None:
        from .models import ReadMailbox

        ReadMailbox.objects.filter(id=mailbox.id, user_id=mailbox.user_id,
                                   org_id=mailbox.org_id).update(
            needs_reconnect=True, trouble=why[:300], access_sealed="", expires_at=0)

    @staticmethod
    def forget(who: Identity, mailbox_id) -> bool:
        from .models import GhostMark, ReadMailbox

        found = MailboxStore.row(who, mailbox_id)
        if found is None:
            return False
        GhostMark.objects.filter(user_id=who.user_id, org_id=who.org_id,
                                 mailbox_id=found.id).delete()
        ReadMailbox.objects.filter(id=found.id, user_id=who.user_id,
                                   org_id=who.org_id).delete()
        return True

    @staticmethod
    def held_elsewhere(mailbox: Mailbox) -> bool:
        """Whether anything else here holds the same Google account through this org's client."""
        from .models import GoogleConnection, ReadMailbox

        if (GoogleConnection.objects.filter(org_id=mailbox.org_id,
                                            google_account=mailbox.google_account).exists()):
            return True
        return (ReadMailbox.objects.filter(org_id=mailbox.org_id,
                                           google_account=mailbox.google_account)
                .exclude(id=mailbox.id).exists())


class MailboxAuth:
    """The consent round trip for a mailbox, and keeping its token alive.

    Built on the Google connection's own pieces: the organisation's client
    (`GoogleStore.client_for`), the single-use states (`remember_state`,
    `take_state` with the purpose `mailbox`) and their signature
    (`GoogleAuth._sign`), and the same endpoints.
    """

    def __init__(self, google_store, google_auth, mailboxes: MailboxStore, cfg, *,
                 client_factory=None) -> None:
        self.google_store = google_store
        self.google_auth = google_auth
        self.store = mailboxes
        self._cfg = cfg
        self._client_factory = client_factory or (lambda: httpx.AsyncClient(
            timeout=TIMEOUT_SECONDS))
        self._locks: dict[int, asyncio.Lock] = {}

    def redirect_uri(self, base: str = "") -> str:
        return self.google_auth.redirect_uri(base)

    # --- step one ---------------------------------------------------------------

    def mint_state(self, who: Identity, session: str = "", *, forwarding: int = 0) -> str:
        """A single-use consent state; `forwarding` is the mailbox it allows forwarding from."""
        from .google_oauth import _fingerprint

        nonce = base64.urlsafe_b64encode(os.urandom(18)).decode().rstrip("=")
        self.google_store.remember_state(
            nonce, who.user_id, who.org_id, _fingerprint(session), purpose=PURPOSE,
            next_path=f"{FORWARDING}{int(forwarding)}" if forwarding else "")
        return f"{nonce}.{self.google_auth._sign(nonce)}"

    def consent_url(self, who: Identity, state: str, base: str = "", *,
                    forwarding: Mailbox | None = None, hint: str = "") -> str:
        """Google's consent screen for one more mailbox, read-only, with the account chooser.

        With `forwarding`, the screen for allowing forwarding from that one
        mailbox instead: reading and sending, and nothing else, with its
        address put forward so the right account is the one offered.

        Raises `google_store.NotSetUp` when the organisation has no client.
        """
        client = self.google_store.client_for(who.org_id)
        query = {
            "client_id": client.client_id,
            "redirect_uri": self.redirect_uri(base),
            "response_type": "code",
            "scope": " ".join(FORWARD_SCOPES if forwarding else READ_SCOPES),
            "access_type": "offline",
            # Which account is the person's to choose each time, and the
            # consent is shown so a refresh token is always issued for it.
            "prompt": "select_account consent",
            "state": state,
        }
        if forwarding is not None and forwarding.email:
            query["login_hint"] = forwarding.email
        elif hint:
            # Connect pressed beside one of the person's addresses (`rouh/person_addresses.py`): that
            # account is the one offered first. The chooser still lets them pick another.
            query["login_hint"] = hint
        return self._cfg.google_auth_url + "?" + urllib.parse.urlencode(query)

    # --- step two ----------------------------------------------------------------

    def take_state(self, state: str, session: str = "") -> dict:
        from .google_oauth import ConsentFailed, _fingerprint
        import hmac

        raw = (state or "").strip()
        if "." not in raw:
            raise ConsentFailed("That sign-in did not come back with a valid state, so it was refused.")
        nonce, signature = raw.rsplit(".", 1)
        if not hmac.compare_digest(signature, self.google_auth._sign(nonce)):
            raise ConsentFailed("That sign-in did not come back with a valid state, so it was refused.")
        found = self.google_store.take_state(nonce, PURPOSE)
        if found is None:
            raise ConsentFailed("That sign-in had already been used or had expired. "
                                "Press Connect a mailbox again.")
        if found["session"] and found["session"] != _fingerprint(session):
            raise ConsentFailed("That sign-in was started in a different browser session, "
                                "so it was refused.")
        return found

    async def finish(self, who: Identity, code: str, base: str = "", *,
                     forwarding: int = 0) -> int:
        """Exchange the code, check the grant is read-only, find the account, keep it.

        With `forwarding`, the mailbox being allowed to forward: the grant may
        carry `gmail.send` as well, has to, and has to be that mailbox's own
        account, or nothing is kept. A mailbox that may already forward can be
        connected again read-only and keeps what Google hands back for it.
        """
        from asgiref.sync import sync_to_async

        from .google_oauth import ConsentFailed, _google_said

        client = await sync_to_async(self.google_store.client_for)(who.org_id)
        form = {"code": code, "client_id": client.client_id,
                "client_secret": client.client_secret, "redirect_uri": self.redirect_uri(base),
                "grant_type": "authorization_code"}
        async with self._client_factory() as http:
            answer = await http.post(self._cfg.google_token_url, data=form)
            if answer.status_code >= 400:
                raise ConsentFailed(_google_said(answer, self.redirect_uri(base)))
            payload = answer.json()
            access = payload.get("access_token") or ""
            if not access:
                raise ConsentFailed("Google did not return an access token.")
            granted = tuple((payload.get("scope") or "").split())
            if READONLY_SCOPE not in granted:
                raise ConsentFailed(
                    "Reading mail was not allowed on Google's screen, so nothing was "
                    "connected. Press Connect a mailbox again and leave \"View your email "
                    "messages and settings\" ticked.")
            if forwarding and SEND_SCOPE not in granted:
                raise ConsentFailed(
                    "Sending was not allowed on Google's screen, so forwarding is still off "
                    "and nothing changed. Press Allow forwarding again and leave \"Send "
                    "email on your behalf\" ticked.")
            info = await http.get(self._cfg.google_userinfo_url,
                                  headers={"Authorization": f"Bearer {access}"})
            body = info.json() if info.status_code < 400 else {}
        email, account = str(body.get("email") or ""), str(body.get("sub") or "")
        if not account:
            raise ConsentFailed("Google did not say which account that was, so nothing was "
                                "connected. Try again.")
        if forwarding:
            meant = await sync_to_async(self.store.row)(who, forwarding)
            if meant is None:
                raise ConsentFailed("That mailbox is not connected any more, so forwarding "
                                    "was not turned on. Nothing changed.")
            if meant.google_account != account:
                await self._let_go(who, account, access)
                raise ConsentFailed(
                    f"{email or 'Another account'} was chosen on Google's screen, but "
                    f"forwarding was being allowed for {meant.email}. Rouh kept nothing and "
                    f"nothing changed. Press Allow forwarding again and choose {meant.email}.")
        kept = set(GRANTS_KEPT)
        if forwarding or await sync_to_async(self._forwards)(who, account):
            kept.add(SEND_SCOPE)
        wider = [one for one in granted if one not in kept]
        if wider:
            # Nothing is kept: a token that can write is not a read-only
            # mailbox, whatever this file would do with it.
            log.warning("a mailbox consent for user %s came back with more than read-only "
                        "access (%s); nothing was kept", who.user_id, ", ".join(wider))
            raise ConsentFailed(
                "Google handed back more than read-only access for that account, so "
                "Rouh kept nothing. Nothing was connected.")
        expires_at = time.time() + float(payload.get("expires_in") or 3600)
        ident = await sync_to_async(self.store.save)(
            who, email=email, google_account=account, access_token=access,
            refresh_token=payload.get("refresh_token") or "", expires_at=expires_at,
            scopes=granted)
        log.info("read-only mailbox %s connected for user %s in org %s%s", ident, who.user_id,
                 who.org_id, ", and may forward" if SEND_SCOPE in granted else "")
        return ident

    def _forwards(self, who: Identity, account: str) -> bool:
        """Whether this person's mailbox of that Google account may already forward."""
        from .models import ReadMailbox

        held = (ReadMailbox.objects.filter(user_id=who.user_id, org_id=who.org_id,
                                           google_account=account)
                .values_list("scopes", flat=True).first())
        return can_forward(held or "")

    async def _let_go(self, who: Identity, account: str, token: str) -> None:
        """Hand back a grant that is not being kept, unless something here holds that account."""
        from asgiref.sync import sync_to_async

        from .models import GoogleConnection, ReadMailbox

        def held() -> bool:
            return (GoogleConnection.objects.filter(org_id=who.org_id,
                                                    google_account=account).exists()
                    or ReadMailbox.objects.filter(org_id=who.org_id,
                                                  google_account=account).exists())

        if not token or await sync_to_async(held)():
            return
        try:
            async with self._client_factory() as http:
                await http.post(self._cfg.google_revoke_url, data={"token": token})
        except Exception:
            log.warning("a grant that was not kept could not be handed back to Google")

    # --- keeping it alive --------------------------------------------------------------

    async def access_token(self, mailbox: Mailbox, *, renew: bool = False) -> str:
        from asgiref.sync import sync_to_async

        if mailbox.needs_reconnect and not renew:
            raise NeedsReconnect(mailbox.trouble or "Google no longer accepts this mailbox. "
                                 "Connect it again in Settings.")
        if (not renew and mailbox.access_token
                and mailbox.expires_at - time.time() > REFRESH_MARGIN_SECONDS):
            return mailbox.access_token
        lock = self._locks.setdefault(mailbox.id, asyncio.Lock())
        async with lock:
            held = await sync_to_async(self.store.mailbox)(
                Identity(user_id=mailbox.user_id, org_id=mailbox.org_id), mailbox.id)
            if held is None:
                raise NotConnected("That mailbox is not connected any more.")
            if (not renew and held.access_token
                    and held.expires_at - time.time() > REFRESH_MARGIN_SECONDS):
                return held.access_token
            return await self._refresh(held)

    async def _refresh(self, held: Mailbox) -> str:
        from asgiref.sync import sync_to_async

        from .google_oauth import _google_said

        if not held.refresh_token:
            said = "This mailbox has no refresh token, so it has to be connected again."
            await sync_to_async(self.store.needs_reconnect)(held, said)
            raise NeedsReconnect(said)
        client = await sync_to_async(self.google_store.client_for)(held.org_id)
        async with self._client_factory() as http:
            answer = await http.post(self._cfg.google_token_url, data={
                "client_id": client.client_id, "client_secret": client.client_secret,
                "refresh_token": held.refresh_token, "grant_type": "refresh_token"})
        if answer.status_code >= 400:
            said = _google_said(answer, self.redirect_uri())
            if "invalid_grant" in said or answer.status_code in (400, 401):
                await sync_to_async(self.store.needs_reconnect)(held, said)
                raise NeedsReconnect(f"Google has withdrawn access to {held.email}. Connect it "
                                     "again in Settings.")
            raise Refused(said)
        payload = answer.json()
        access = payload.get("access_token") or ""
        if not access:
            raise Refused("Google did not return a new access token.")
        await sync_to_async(self.store.store_access)(
            held, access, time.time() + float(payload.get("expires_in") or 3600))
        return access

    # --- taking it away ---------------------------------------------------------------

    async def disconnect(self, who: Identity, mailbox_id) -> dict | None:
        """Forget the mailbox here, and withdraw the grant at Google if nothing else holds it."""
        from asgiref.sync import sync_to_async

        held = await sync_to_async(self.store.mailbox)(who, mailbox_id)
        if held is None:
            return None
        shared = await sync_to_async(self.store.held_elsewhere)(held)
        revoked = False
        token = held.refresh_token or held.access_token
        if token and not shared:
            try:
                async with self._client_factory() as http:
                    await http.post(self._cfg.google_revoke_url, data={"token": token})
                revoked = True
            except Exception:
                log.warning("a mailbox's revoke did not go through; forgetting it here anyway")
        await sync_to_async(self.store.forget)(who, held.id)
        log.info("read-only mailbox %s disconnected for user %s", held.id, who.user_id)
        return {"email": held.email, "revoked": revoked, "shared": shared}


class GmailReads:
    """What the ghost list reads from a mailbox, over a `get` that only ever reads.

    Shared by a read-only mailbox (`ReadOnlyGmail`) and by Rouh's own Google
    connection read the same way (`ghosts.ConnectionGmail`), so both are looked
    at with the same few requests. `mailbox` has the `id` and `email` the
    ghost list shows it under.
    """

    mailbox = None

    async def get(self, path: str, params=None) -> dict:
        raise NotImplementedError

    async def addresses(self) -> set[str]:
        """Every address this mailbox sends as: its own and its aliases, lower case."""
        own = {self.mailbox.email.lower()} if self.mailbox.email else set()
        try:
            profile = await self.get("/profile")
            if profile.get("emailAddress"):
                own.add(str(profile["emailAddress"]).lower())
        except Exception as exc:
            log.info("mailbox %s: the profile could not be read: %s", self.mailbox.id, exc)
        try:
            listed = await self.get("/settings/sendAs")
            for one in listed.get("sendAs") or []:
                if one.get("sendAsEmail"):
                    own.add(str(one["sendAsEmail"]).lower())
        except Exception as exc:
            log.info("mailbox %s: the send-as addresses could not be read: %s",
                     self.mailbox.id, exc)
        return own

    async def search(self, query: str, most: int) -> list[dict]:
        found = await self.get("/messages", {"q": query, "maxResults": most})
        return [one for one in found.get("messages") or [] if one.get("id")]

    async def thread(self, thread_id: str) -> dict:
        return await self.get(f"/threads/{urllib.parse.quote(thread_id, safe='')}",
                              {"format": "full"})

    async def headers(self, message_id: str) -> dict:
        return await self.get(f"/messages/{urllib.parse.quote(message_id, safe='')}", {
            "format": "metadata",
            "metadataHeaders": ["From", "Subject", "Auto-Submitted", "X-Autoreply",
                                "X-Autorespond", "Precedence"]})

    async def summary(self, message_id: str) -> dict:
        """What an unread email's line on the brief needs: who, what, when, and its own id."""
        return await self.get(f"/messages/{urllib.parse.quote(message_id, safe='')}", {
            "format": "metadata", "metadataHeaders": ["From", "Subject", "Date", "Message-ID"]})

    async def message(self, message_id: str) -> dict:
        """One whole email, as Gmail's `format=full` has it, to be read on the brief."""
        return await self.get(f"/messages/{urllib.parse.quote(message_id, safe='')}",
                              {"format": "full"})


class ReadOnlyGmail(GmailReads):
    """One connected mailbox, read. GET is the only request it can make.

    Built on `google_api`'s pieces for what Google answers - its retry pauses,
    its wording of a refusal - so a mailbox fails in the same sentences as the
    Google connection does.
    """

    def __init__(self, auth: MailboxAuth, mailbox: Mailbox, cfg, *, client_factory=None) -> None:
        self._auth = auth
        self.mailbox = mailbox
        self._cfg = cfg
        self._client_factory = client_factory or (lambda: httpx.AsyncClient(
            timeout=httpx.Timeout(READ_SECONDS, connect=10.0)))

    def _url(self, path: str) -> str:
        from .google_api import REAL_BASES

        base = (getattr(self._cfg, "google_api_base", "") or "").strip() or REAL_BASES["gmail"]
        return base.rstrip("/") + "/gmail/v1/users/me" + path

    async def get(self, path: str, params=None) -> dict:
        from asgiref.sync import sync_to_async

        from .google_api import GoogleSaidNo, _pause, _said

        token = await self._auth.access_token(self.mailbox)
        wait, last = 0.5, ""
        async with self._client_factory() as http:
            for attempt in range(1, ATTEMPTS + 1):
                answer = await http.request("GET", self._url(path), params=params, headers={
                    "Authorization": f"Bearer {token}", "Accept": "application/json"})
                if answer.status_code < 400:
                    try:
                        return answer.json() if answer.content else {}
                    except ValueError:
                        return {}
                if answer.status_code == 401:
                    if attempt == 1:
                        token = await self._auth.access_token(self.mailbox, renew=True)
                        continue
                    said = "Google refused this mailbox's token."
                    await sync_to_async(self._auth.store.needs_reconnect)(self.mailbox, said)
                    raise NeedsReconnect(f"Google no longer accepts {self.mailbox.email}. "
                                         "Connect it again in Settings.")
                if answer.status_code == 429 or answer.status_code >= 500:
                    last = _said(answer)
                    if attempt == ATTEMPTS:
                        break
                    await asyncio.sleep(_pause(answer, wait))
                    wait *= 2
                    continue
                raise GoogleSaidNo(_said(answer), status=answer.status_code)
        raise GoogleSaidNo(last or "Google is not answering right now.")


class ForwardingGmail(ReadOnlyGmail):
    """A mailbox the person allowed to forward from: reads, and sends one message.

    `send` is the one request beyond reading that it has, and the only one
    `gmail.send` is ever used for. It is not tried again on a 5xx: a message
    Google may already have sent is not sent twice, and the person is told
    to look in Sent instead.
    """

    async def send(self, body: dict, *, seconds: float = 0.0) -> dict:
        from asgiref.sync import sync_to_async

        from .google_api import GoogleSaidNo, _pause, _reason, _said

        if not can_forward(self.mailbox.scopes):
            raise Refused(f"Forwarding from {self.mailbox.email} has not been allowed.")
        token = await self._auth.access_token(self.mailbox)
        patience = httpx.Timeout(max(READ_SECONDS, seconds or 0.0), connect=10.0)
        async with self._client_factory() as http:
            for attempt in range(1, ATTEMPTS + 1):
                answer = await http.request(
                    "POST", self._url("/messages/send"), json=body, timeout=patience,
                    headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
                if answer.status_code < 400:
                    try:
                        return answer.json() if answer.content else {}
                    except ValueError:
                        return {}
                if answer.status_code == 401 and attempt == 1:
                    token = await self._auth.access_token(self.mailbox, renew=True)
                    continue
                if answer.status_code == 401:
                    said = "Google refused this mailbox's token."
                    await sync_to_async(self._auth.store.needs_reconnect)(self.mailbox, said)
                    raise NeedsReconnect(f"Google no longer accepts {self.mailbox.email}. "
                                         "Connect it again in Settings.")
                if answer.status_code == 429 and attempt < ATTEMPTS:
                    await asyncio.sleep(_pause(answer, 0.5 * attempt))
                    continue
                if answer.status_code >= 500:
                    raise GoogleSaidNo(
                        f"Google did not answer properly while sending from "
                        f"{self.mailbox.email}, so it may or may not have gone. Look in its "
                        "Sent folder before trying again.", status=answer.status_code)
                raise GoogleSaidNo(_said(answer), status=answer.status_code,
                                   reason=_reason(answer)[0])
        raise GoogleSaidNo("Google is not answering right now. Nothing was sent.")
