"""The per-person clients: `GoogleClients.for_user(who)`, and the one place a
request to Google is made (`GoogleClients.call`).
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

import httpx

from ..google_oauth import GoogleAuth, NeedsMoreAccess, NeedsReconnect, NotConnected, why_missing
from ..tenancy import Identity
from .common import (ATTEMPTS, BACKOFF_CEILING_SECONDS, BACKOFF_SECONDS, CONNECT_SECONDS,
                     GoogleSaidNo, READ_SECONDS, REAL_BASES, SCOPE_TOO_NARROW, _first_of, _pause,
                     _reason, _said, _too_narrow)
from .gmail import Gmail
from .drive import Drive
from .docs import Docs
from .calendar import Calendar
from .sheets import Sheets
from .slides import Slides

log = logging.getLogger("rouh.google")


@dataclass
class Services:
    """The clients, already acting as one person."""

    gmail: "Gmail"
    drive: "Drive"
    docs: "Docs"
    calendar: "Calendar"
    slides: "Slides | None" = None
    sheets: "Sheets | None" = None


class GoogleClients:
    """Builds the per-person clients, and is the only thing that holds tokens."""

    def __init__(self, auth: GoogleAuth, cfg, *, client_factory=None) -> None:
        self._auth = auth
        self._cfg = cfg
        self._client_factory = client_factory or self._default_client

    def _default_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=httpx.Timeout(READ_SECONDS, connect=CONNECT_SECONDS)
        )

    def base(self, service: str) -> str:
        override = (getattr(self._cfg, "google_api_base", "") or "").strip()
        return (override or REAL_BASES[service]).rstrip("/")

    def for_user(self, who: Identity) -> Services:
        """The four clients for one person. Tokens are fetched per request."""
        return Services(gmail=Gmail(self, who), drive=Drive(self, who), docs=Docs(self, who),
                        calendar=Calendar(self, who), slides=Slides(self, who),
                        sheets=Sheets(self, who))

    # --- the one place a request is made ------------------------------------

    async def call(self, who: Identity, method: str, url: str, *,
                   params: dict | None = None, json_body: dict | None = None,
                   content: bytes | None = None, content_type: str = "",
                   want_text: bool = False, want_location: bool = False,
                   want_bytes: bool = False,
                   more_headers: dict | None = None, seconds: float = 0.0,
                   needs_scope: str | tuple[str, ...] = "", without_it: str = "",
                   forward: bool = False):
        """One request, with a live token, retries, and nothing secret in the log.

        Raises `NotConnected` or `NeedsReconnect` when the person has to act,
        and `GoogleSaidNo` with Google's own wording for everything else.

        `content` is for the one thing Google does not take as JSON: a Drive
        upload, which is a multipart body this builds itself. `want_text` is
        for the other: a file's own bytes coming back, or a document exported
        as plain text. Both go through this method rather than around it, so
        writing a file keeps the same token, timeout, retry and redaction as
        reading a message header.

        `want_location` is the third: starting a resumable upload, where what
        Drive answers with is an empty body and a `Location` header, and that
        header is the address the file's own bytes are then sent to.
        `more_headers` carries the two `X-Upload-Content-*` headers that start
        goes out with, and `seconds` widens the read timeout for the one
        request that carries a whole file, which does not finish inside the
        thirty seconds that is right for reading a message header.

        `needs_scope` is the permission this particular call cannot happen
        without. It is checked against the grant on file before the request is
        made, and it is what Google's own "insufficient authentication scopes"
        is turned into afterwards, so a capability the person never granted
        fails with the scope named rather than with a 403 nobody can read.
        Several scopes mean any one of them will do, which is what a shared
        drive needs: `drive` or `drive.readonly`, and never `drive.file`.
        `without_it` is the sentence said when the grant falls short, for a
        call whose missing capability is better named than its scope is.

        `forward` marks the one send that is a forward (`Gmail.forward`,
        `Gmail.forward_thread`). It changes nothing here; it is what lets the
        same send through the person's own inbox, whose clients send a forward
        and nothing else (`inboxes.ForwardClients`).
        """
        if needs_scope:
            self._must_hold(who, needs_scope, without_it)
        token = await self._auth.access_token(who)
        wait = BACKOFF_SECONDS
        last = ""
        headers = {"Authorization": f"Bearer {token}"}
        headers["Accept"] = "*/*" if want_text or want_bytes else "application/json"
        if content_type:
            headers["Content-Type"] = content_type
        headers.update(more_headers or {})
        patience = httpx.Timeout(seconds or READ_SECONDS, connect=CONNECT_SECONDS)
        async with self._client_factory() as http:
            for attempt in range(1, ATTEMPTS + 1):
                headers["Authorization"] = f"Bearer {token}"
                answer = await http.request(
                    method, url,
                    params=params,
                    json=json_body,
                    content=content,
                    headers=headers,
                    timeout=patience,
                )
                if answer.status_code < 400:
                    if want_location:
                        where = answer.headers.get("Location", "")
                        if not where:
                            raise GoogleSaidNo(
                                "Drive agreed to take the file but did not say where to "
                                "send it, so nothing was uploaded.")
                        return where
                    if want_text:
                        return answer.text
                    if want_bytes:
                        # A picture's own bytes (Pictures in docs seen, `rouh/doc_pictures.py`).
                        return answer.content
                    if not answer.content:
                        return {}
                    try:
                        return answer.json()
                    except ValueError:
                        return {}
                if answer.status_code == 401:
                    # The token went stale early, or the grant is gone. One
                    # forced renewal, then believe it.
                    if attempt == 1:
                        token = await self._renew(who)
                        continue
                    self._auth.store.needs_reconnect(
                        who.user_id, who.org_id,
                        "Google refused this connection's token.")
                    raise NeedsReconnect(
                        "Google no longer accepts this connection. Open Settings and "
                        "connect the account again.")
                if answer.status_code == 429 or answer.status_code >= 500:
                    last = _said(answer)
                    if attempt == ATTEMPTS:
                        break
                    await asyncio.sleep(_pause(answer, wait))
                    wait = min(wait * 2, BACKOFF_CEILING_SECONDS)
                    continue
                if answer.status_code == 403 and _reason(answer)[0] in SCOPE_TOO_NARROW:
                    raise NeedsMoreAccess(
                        without_it or _too_narrow(_first_of(needs_scope), _said(answer)))
                raise GoogleSaidNo(_said(answer), status=answer.status_code,
                                   reason=_reason(answer)[0])
        raise GoogleSaidNo(
            last or "Google is not answering right now. It is worth trying again shortly.")

    def _must_hold(self, who: Identity, scope: str | tuple[str, ...],
                   without_it: str = "") -> None:
        """Refuse before the request when the grant on file lacks the scope.

        Several scopes mean any one of them is enough, so a connection holding
        `drive.readonly` is not sent away from a listing it can perfectly well
        do.

        A connection with no scopes recorded at all is one this build has never
        seen the grant of, and is left to the call itself to judge - the same
        rule `missing_scopes` keeps, for the same reason: telling a working
        connection to reconnect for nothing is worse than a clear 403.
        """
        wanted = (scope,) if isinstance(scope, str) else tuple(scope)
        held = self._auth.store.connection(who.user_id, who.org_id)
        if held is None:
            raise NotConnected("This Google account is not connected.")
        if held.scopes and not any(one in held.scopes for one in wanted):
            log.info("google call refused up front for user %s: the grant does not "
                     "carry %s", who.user_id, " or ".join(wanted))
            raise NeedsMoreAccess(without_it or why_missing(wanted[0]))

    async def _renew(self, who: Identity) -> str:
        held = self._auth.store.connection(who.user_id, who.org_id)
        if held is None:
            raise NotConnected("This Google account is not connected.")
        # Age the stored token out so `access_token` refreshes rather than
        # handing back the one that was just refused.
        self._auth.store.store_access_token(who.user_id, who.org_id,
                                             held.access_token or "", 0.0)
        return await self._auth.access_token(who)
