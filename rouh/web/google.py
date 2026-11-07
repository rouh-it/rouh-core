"""Settings and the Google round trip: the organisation's OAuth client, and
each person connecting their own Google account.

    GET  /api/settings/google              what Settings draws
    POST /api/settings/google/client       an administrator enters the client
    POST /api/settings/google/client/remove
    GET  /api/settings/google/calendars    the calendars this person's connection can see
    POST /api/settings/google/calendars/add   put a calendar shared with it on its list
    POST /api/settings/google/calendars/remove   take one off that list again
    GET  /auth/google/start                off to the consent screen
    GET  /auth/google/callback             back from it
    POST /auth/google/disconnect

Who is asking is `Tenancy.current`, through `common.who`, and nothing here
reads an organisation or a user out of the request. What an ordinary member is
told, and what only an administrator is, is unchanged from when these were
FastAPI routes (`rouh/google_web.py` until 23 September 2026). Google is a
source of data here and never a way to sign in (4 November 2026: signing in
with Google, `sso.py`, was taken out).
"""
from __future__ import annotations

import logging
import time
import urllib.parse
from collections import defaultdict, deque

from asgiref.sync import sync_to_async
from django.http import HttpRequest, HttpResponseRedirect

from rouh.config import config
from rouh.google_oauth import (CALENDAR_SCOPE, GOOGLE_APIS, NOT_REGISTERED, SCOPES,
                               ConsentFailed, NeedsReconnect, NotConnected,
                               capabilities_of, redirect_accepted,
                               missing_scopes, why_reconnect)
from rouh.google_store import NotSetUp
from rouh.redaction import scrub

from .common import answer, body_of, only, public_base, refuse, who
from .gate import sign_in_first

log = logging.getLogger("rouh.google")

#: How often one signed-in person may ask for a consent URL, finish one, or
#: disconnect. Generous for a person pressing a button, useless to anything
#: trying combinations. `config.google_rate_limit` is this number and is a
#: setting only so the browser environment does not meet the rate limit every
#: time it tries something else.
LIMIT_PER_MINUTE = 12
LIMIT_WINDOW_SECONDS = 60.0


class Meter:
    """A plain per-caller rate limit, in this process's memory."""

    def __init__(self, allowed: int = LIMIT_PER_MINUTE,
                 window: float = LIMIT_WINDOW_SECONDS) -> None:
        self._allowed = allowed
        self._window = window
        self._seen: dict[str, deque[float]] = defaultdict(deque)

    def too_many(self, key: str) -> bool:
        now = time.monotonic()
        seen = self._seen[key]
        while seen and now - seen[0] > self._window:
            seen.popleft()
        if len(seen) >= self._allowed:
            return True
        seen.append(now)
        return False


meter = Meter(int(getattr(config, "google_rate_limit", 0) or LIMIT_PER_MINUTE))

TOO_MANY = "That is too many attempts. Wait a minute."
NOT_ADMIN = "Only an administrator of your organisation can change this."


def _parts():
    """The store and the round trip, or None where credentials cannot be kept.

    If the encryption library is missing there is nowhere safe to keep a
    credential, so the whole of Google stays off (`runtime.py`), and every
    address here says so rather than failing.
    """
    from rouh import runtime

    if runtime.google_store is None or runtime.google_auth is None:
        return None
    return runtime.google_store, runtime.google_auth, runtime.tenancy


def _off():
    return refuse("Google is switched off on this server: credentials cannot be "
                  "encrypted here.", 503)


def page(where: str) -> str:
    """Back to Rouh's own page, with Settings open on Google."""
    return "/?settings=google" + where


def _q(text: str) -> str:
    return urllib.parse.quote((text or "")[:600], safe="")


def _session_of(request: HttpRequest) -> str:
    """The browser a consent is bound to: its Django session.

    A state minted in one browser cannot be finished in another. Only a hash
    of this is ever stored (`google_oauth._fingerprint`).
    """
    return request.session.session_key or ""


def _wants_the_url(request: HttpRequest) -> bool:
    """Whether this caller asked to be shown the address rather than sent to it."""
    return (request.GET.get("show") or "").strip().lower() == "url"


# --- what Settings draws -------------------------------------------------------


@only("GET")
async def settings_google(request: HttpRequest):
    parts = _parts()
    if parts is None:
        return _off()
    store, auth, tenancy = parts
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("sign in", 401)

    def read():
        # An ordinary member is told whether their organisation is set up,
        # because that is why their Connect button is on or off. They are not
        # told the client id and never the secret: it is their administrator's
        # to hold, and a page that never receives it cannot leak it.
        summary = store.client_summary(me.org_id)
        setup = {
            "configured": summary["configured"],
            "may_edit": me.is_admin,
            "redirect_uri": auth.redirect_uri(public_base(request)),
            "apis": list(GOOGLE_APIS),
        }
        if me.is_admin:
            setup["client_id"] = summary["client_id"]
            setup["secret_set"] = summary["secret_set"]
            setup["secret_changed_at"] = summary["secret_changed_at"]

        held = store.connection(me.user_id, me.org_id)
        connection = {"connected": False, "email": "", "connected_at": 0,
                      "capabilities": [], "needs_reconnect": False, "trouble": "",
                      "needs_more_access": False}
        if held is not None:
            # A grant older than what Rouh now asks for is not a broken
            # connection, and the page has to be able to tell the person which
            # of the two it is: one of them is their Google account saying no,
            # the other is one press of Connect.
            lacking = missing_scopes(held.scopes)
            connection = {
                "connected": True,
                "email": held.google_email,
                "connected_at": held.connected_at,
                "capabilities": capabilities_of(held.scopes),
                "needs_reconnect": held.needs_reconnect and not lacking,
                "needs_more_access": bool(lacking),
                # Google's own words about why, scrubbed again on the way out.
                "trouble": (why_reconnect(lacking, say_where=False) if lacking
                            else scrub(held.trouble)),
            }
        return {
            "organisation": {"id": me.org_id, "name": tenancy.organisation_name(me.org_id)},
            "you": {"user_id": me.user_id, "is_admin": me.is_admin,
                    "name": me.name, "email": me.email},
            "setup": setup,
            "connection": connection,
            "can_connect": summary["configured"],
        }

    return answer(await sync_to_async(read)())


# --- the organisation's own OAuth client --------------------------------------------


@only("POST")
async def save_client(request: HttpRequest):
    parts = _parts()
    if parts is None:
        return _off()
    store, _auth, _tenancy = parts
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("sign in", 401)
    if not me.is_admin:
        return refuse(NOT_ADMIN, 403)
    if meter.too_many("save:" + me.user_id):
        return refuse(TOO_MANY, 429)
    body = body_of(request)
    try:
        await sync_to_async(store.save_client)(
            me.org_id, str(body.get("client_id") or ""), str(body.get("client_secret") or ""),
            by_user_id=me.user_id)
    except ValueError as exc:
        return refuse(str(exc), 400)
    log.info("google oauth client saved for org %s by user %s", me.org_id, me.user_id)
    # What comes back is the summary, never the secret that was just sent.
    return answer({"ok": True, **(await sync_to_async(store.client_summary)(me.org_id))})


@only("POST")
async def remove_client(request: HttpRequest):
    parts = _parts()
    if parts is None:
        return _off()
    store, _auth, _tenancy = parts
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("sign in", 401)
    if not me.is_admin:
        return refuse(NOT_ADMIN, 403)
    gone = await sync_to_async(store.remove_client)(me.org_id)
    log.info("google oauth client removed for org %s by user %s", me.org_id, me.user_id)
    return answer({"ok": True, "removed": gone})


# --- the calendars this person's connection can see ------------------------------------

#: Said under Calendars when the connection was made before Rouh asked for
#: calendars. The button it names is the one right above it.
CALENDAR_NOT_GRANTED = ("Not part of this connection yet. Press Grant the new access "
                        "above and allow Google Calendar on Google's screen.")


def _calendar_row(one: dict) -> dict:
    """What the page is told about one calendar: nothing it does not draw."""
    return {"id": one["id"], "name": one["name"], "access": one["access"], "can": one["can"],
            "primary": one["primary"], "theirs": one.get("theirs", False),
            "zone": one["zone"]}


def _calendar_of(me):
    from rouh import runtime
    from rouh.google_api import GoogleClients

    return GoogleClients(runtime.google_auth, config).for_user(me).calendar


@only("GET")
async def calendars(request: HttpRequest):
    """Which calendars Rouh can see through this person's connection, and what it
    may do on each: the answer to "is my calendar linked".

    Asked of Google when the card is drawn rather than kept here, because the
    list is changed from Google's side - a calendar shared with the account
    arrives there, not here - and a copy would be wrong the moment it was.
    """
    parts = _parts()
    if parts is None:
        return _off()
    store, _auth, _tenancy = parts
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("sign in", 401)
    held = await sync_to_async(store.connection)(me.user_id, me.org_id)
    if held is None:
        return answer({"connected": False, "granted": False, "calendars": []})
    base = {"connected": True, "account": held.google_email}
    if held.scopes and CALENDAR_SCOPE not in held.scopes:
        return answer({**base, "granted": False, "calendars": [],
                       "say": CALENDAR_NOT_GRANTED})
    if meter.too_many("calendars:" + me.user_id):
        return refuse(TOO_MANY, 429)
    try:
        found = await _calendar_of(me).calendars()
    except (NotConnected, NeedsReconnect) as exc:
        return answer({**base, "granted": True, "calendars": [], "say": scrub(str(exc))})
    except Exception as exc:
        log.warning("google calendars could not be listed for user %s: %s",
                    me.user_id, type(exc).__name__)
        return answer({**base, "granted": True, "calendars": [],
                       "say": "Google did not list the calendars: " + scrub(str(exc))})
    return answer({**base, "granted": True, "calendars": [_calendar_row(one) for one in found]})


@only("POST")
async def add_calendar(request: HttpRequest):
    """Put a calendar somebody shared with this person's Google account on its list.

    The same thing as the assistant's `add_shared_calendar`, and recorded in
    the same trail: it changes the account's list, never anybody's events.
    """
    from rouh import runtime
    from rouh.google_api import GoogleSaidNo

    parts = _parts()
    if parts is None:
        return _off()
    store, _auth, _tenancy = parts
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("sign in", 401)
    if meter.too_many("calendar-add:" + me.user_id):
        return refuse(TOO_MANY, 429)
    wanted = str(body_of(request).get("calendar") or "").strip()
    if not wanted or len(wanted) > 300 or any(c.isspace() for c in wanted):
        return refuse("Give the calendar's id: for a person's own calendar, their email "
                      "address.", 400)
    held = await sync_to_async(store.connection)(me.user_id, me.org_id)
    if held is None:
        return refuse("Connect a Google account first.", 409)
    try:
        added = await _calendar_of(me).add(wanted)
    except GoogleSaidNo as exc:
        return refuse(
            f"Google would not add {wanted}: {scrub(str(exc)).rstrip('.')}. Its owner has to "
            f"share it with {held.google_email or 'this Google account'} first.", 409)
    except Exception as exc:
        return refuse(scrub(str(exc)), 409)
    said = (f"Added the calendar {added['name']} ({added['id']}) to "
            f"{held.google_email or 'the connected account'}'s calendars, from Settings.")
    runtime.google_audit.wrote("add_shared_calendar", added["id"], said,
                               user_id=me.user_id, org_id=me.org_id,
                               account=held.google_email)
    log.info("user %s added the calendar %s to their connected Google account",
             me.user_id, added["id"])
    return answer({"ok": True, "calendar": _calendar_row(added)})


@only("POST")
async def remove_calendar(request: HttpRequest):
    """Take a calendar off this person's Google account's list: Rouh stops reading it and acting on it.

    Petar, 16 October 2026 (fr_6d4c861d976e): "I should be able to disconnect
    delete calendars here". Disconnect only: the calendar and its events stay
    exactly as they are at Google, and the account keeps whatever sharing it
    had, so the calendar can be added again by its id. The connection itself
    and every other calendar are left alone.
    """
    from rouh import runtime
    from rouh.google_api import GoogleSaidNo

    parts = _parts()
    if parts is None:
        return _off()
    store, _auth, _tenancy = parts
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("sign in", 401)
    if meter.too_many("calendar-remove:" + me.user_id):
        return refuse(TOO_MANY, 429)
    wanted = str(body_of(request).get("calendar") or "").strip()
    if not wanted or len(wanted) > 300 or any(c.isspace() for c in wanted):
        return refuse("Say which calendar, by its id.", 400)
    held = await sync_to_async(store.connection)(me.user_id, me.org_id)
    if held is None:
        return refuse("Connect a Google account first.", 409)
    try:
        gone = await _calendar_of(me).remove(wanted)
    except GoogleSaidNo as exc:
        return refuse(f"{scrub(str(exc)).rstrip('.')}.", 409)
    except Exception as exc:
        log.warning("google calendar %s could not be removed for user %s: %s",
                    wanted, me.user_id, type(exc).__name__)
        return refuse(f"{scrub(str(exc)).rstrip('.')}.", 409)
    try:
        from rouh.synapse import calsync

        await sync_to_async(calsync.left_list)(me.user_id, me.org_id, gone["id"])
    except Exception as exc:  # noqa: BLE001 - the hourly discover stops it anyway
        log.warning("synapse calendar row for %s not stopped: %s", gone["id"], type(exc).__name__)
    said = (f"Removed the calendar {gone['name']} ({gone['id']}) from "
            f"{held.google_email or 'the connected account'}'s calendars, from Settings. "
            "The calendar and its events are unchanged at Google.")
    runtime.google_audit.wrote("remove_calendar", gone["id"], said,
                               user_id=me.user_id, org_id=me.org_id,
                               account=held.google_email)
    log.info("user %s removed the calendar %s from their connected Google account",
             me.user_id, gone["id"])
    return answer({"ok": True, "calendar": _calendar_row(gone)})


# --- the consent round trip ------------------------------------------------------------


@only("GET")
async def start(request: HttpRequest):
    """Off to the consent screen - or, with ?show=url, the address itself.

    The redirect is what the Connect button uses. `?show=url` hands the same
    address back as JSON instead of following it, so the person can be given a
    link to press when they are nowhere near Settings: told out loud in a
    spoken turn, read out of a log, pasted into another browser. It is the same
    URL, minted the same way, with this person's own state on it, so it works
    exactly once and only in the browser that asked for it.
    """
    parts = _parts()
    if parts is None:
        return _off()
    store, auth, _tenancy = parts
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("sign in", 401)
    if meter.too_many("start:" + me.user_id):
        return refuse(TOO_MANY, 429)
    try:
        # Asked of Google before the person is sent there: a callback address
        # the client does not have registered is a dead end on Google's page.
        client = await sync_to_async(store.client_for)(me.org_id)
        back_to = auth.redirect_uri(public_base(request))
        if await redirect_accepted(config.google_auth_url, client.client_id, back_to) is False:
            said = NOT_REGISTERED.format(redirect=back_to)
            log.warning("google connect: %s is not a registered redirect URI of %s's client",
                        back_to, me.org_id)
            if _wants_the_url(request):
                return refuse(said, 409)
            return HttpResponseRedirect(page("&google=error&say=" + _q(said)), status=303)
        state = await sync_to_async(auth.mint_state)(me, _session_of(request))
        url = await sync_to_async(auth.consent_url)(me, state, base=public_base(request))
    except NotSetUp:
        if _wants_the_url(request):
            return refuse("Google is not set up for this organisation yet. An administrator "
                          "has to register a Google Cloud OAuth client in Settings first.", 409)
        return HttpResponseRedirect(page("&google=not-set-up"), status=303)
    if _wants_the_url(request):
        held = await sync_to_async(store.connection)(me.user_id, me.org_id)
        lacking = missing_scopes(held.scopes) if held else []
        log.info("google consent url handed to user %s in org %s for %d scopes",
                 me.user_id, me.org_id, len(SCOPES))
        return answer({
            "url": url,
            "scopes": list(SCOPES),
            "missing_scopes": lacking,
            "say": why_reconnect(lacking) if lacking else
                   "Open this to connect the Google account.",
        })
    return HttpResponseRedirect(url, status=303)


@only("GET")
async def callback(request: HttpRequest):
    """Back from Google: a person connecting theirs, as a source of data. Google is never a way
    to sign in to Rouh (4 November 2026), so somebody must be signed in already.

    The gate lets this address through unsigned-in only so that it can say "sign in first"
    in its own words.
    """
    from . import mailboxes

    user = await request.auser()
    if not user.is_authenticated:
        return sign_in_first(request)
    # A read-only mailbox comes back to the same address, with a state of its
    # own purpose (`rouh/mailboxes.py`).
    if await mailboxes.is_a_mailbox(request):
        return await mailboxes.finish(request)
    parts = _parts()
    if parts is None:
        return _off()
    _store, auth, _tenancy = parts
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("sign in", 401)
    if meter.too_many("callback:" + me.user_id):
        return refuse(TOO_MANY, 429)
    refused = request.GET.get("error") or ""
    state = request.GET.get("state") or ""
    code = request.GET.get("code") or ""

    # The state is spent whatever happened, including on a refusal, so a
    # cancelled consent cannot be finished later with the same one.
    try:
        issued = await sync_to_async(auth.take_state)(state, _session_of(request))
    except ConsentFailed as exc:
        return HttpResponseRedirect(page("&google=error&say=" + _q(str(exc))), status=303)

    if issued["user_id"] != me.user_id or issued["org_id"] != me.org_id:
        return HttpResponseRedirect(page("&google=error&say=" + _q(
            "That sign-in was started by somebody else, so it was refused.")), status=303)

    if refused:
        # The person pressed Cancel, or Google refused. Nothing is stored.
        said = ("You did not give Rouh permission, so nothing was connected."
                if refused == "access_denied"
                else f"Google refused the connection: {scrub(refused)}")
        log.info("google consent refused for user %s: %s", me.user_id, scrub(refused))
        return HttpResponseRedirect(page("&google=denied&say=" + _q(said)), status=303)

    if not code:
        return HttpResponseRedirect(page("&google=error&say=" + _q(
            "Google came back without an authorisation code.")), status=303)

    try:
        held = await auth.finish(me, code, base=public_base(request))
    except NotSetUp:
        return HttpResponseRedirect(page("&google=not-set-up"), status=303)
    except ConsentFailed as exc:
        return HttpResponseRedirect(page("&google=error&say=" + _q(str(exc))), status=303)
    except Exception:
        log.exception("google token exchange failed")
        return HttpResponseRedirect(page("&google=error&say=" + _q(
            "The exchange with Google did not finish. Try Connect again.")), status=303)
    return HttpResponseRedirect(page("&google=connected&as=" + _q(held.google_email)),
                                status=303)


@only("POST")
async def disconnect(request: HttpRequest):
    parts = _parts()
    if parts is None:
        return _off()
    _store, auth, _tenancy = parts
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("sign in", 401)
    if meter.too_many("disconnect:" + me.user_id):
        return refuse(TOO_MANY, 429)
    gone = await auth.disconnect(me)
    log.info("google disconnected for user %s in org %s", me.user_id, me.org_id)
    return answer({"ok": True, "removed": gone})
