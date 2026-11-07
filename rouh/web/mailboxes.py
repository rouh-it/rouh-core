"""Read-only mailboxes in Settings, and the ghost list the brief draws from them.

    GET  /api/settings/mailboxes               the person's mailboxes, and whether one can be added
    GET  /auth/mailbox/start                   off to Google's account chooser, read-only;
                                               ?hint=<address> offers that account first;
                                               ?forward=<id> allows forwarding from that
                                               one mailbox instead (`gmail.send` as well)
    (GET /auth/google/callback)                back from it: `google.callback` hands a
                                               state of the purpose "mailbox" to `finish`
    POST /api/settings/mailboxes/disconnect    {"id": ...}
    GET  /api/brief/ghosts                     what is waiting on others, per mailbox;
                                               ?fresh=1 looks at the mailboxes again
    POST /api/brief/ghosts/mark                {mailbox, thread, message, action, until}
    POST /api/brief/ghosts/send                {mailbox, thread, message, text} the nudge,
                                               sent from Rouh's own connection
    GET  /api/brief/mail/message               ?mailbox=&message= one email on the brief,
                                               whole, to read without leaving it

Each person's own, like the brief (`rouh/mailboxes.py`, `rouh/ghosts.py`).
"""
from __future__ import annotations

import logging
import urllib.parse

from asgiref.sync import sync_to_async
from django.http import HttpRequest, HttpResponseRedirect

from rouh import ghosts, mailboxes
from rouh.config import config
from rouh.google_oauth import NOT_REGISTERED, ConsentFailed, redirect_accepted
from rouh.google_store import NotSetUp
from rouh.redaction import scrub

from .common import answer, body_of, only, public_base, refuse, who
from .google import TOO_MANY, _session_of, _wants_the_url, meter

log = logging.getLogger("rouh.mailboxes")

NO_STORE = {"Cache-Control": "no-store"}

#: What each grant is, in the words Google's own screen uses, for the card.
GRANT_WORDS = ["See which Google account it is",
               "View your email messages and settings (read-only)"]

#: And the one more a mailbox is asked for when the person allows forwarding.
FORWARD_WORDS = "Send email on your behalf (only ever a forward you ask Rouh for)"


def _auth():
    from rouh import runtime

    return getattr(runtime, "mailbox_auth", None)


def _off():
    return refuse("Google is switched off on this server: credentials cannot be "
                  "encrypted here.", 503)


def page(where: str) -> str:
    return "/?settings=mailboxes" + where


def _q(text: str) -> str:
    return urllib.parse.quote((text or "")[:600], safe="")


@only("GET")
async def settings_mailboxes(request: HttpRequest):
    auth = _auth()
    if auth is None:
        return _off()
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("sign in", 401)

    def read():
        rows = auth.store.rows(me)
        return {"ok": True, "can_connect": auth.google_store.client_summary(me.org_id)["configured"],
                "is_admin": me.is_admin, "most": mailboxes.MOST,
                "grants": GRANT_WORDS, "forward_grant": FORWARD_WORDS,
                "mailboxes": [mailboxes.summary(row) for row in rows]}

    return answer(await sync_to_async(read)(), headers=NO_STORE)


@only("GET")
async def start(request: HttpRequest):
    """Off to Google's account chooser for one more mailbox, read-only; ?show=url for the address.

    `?forward=<id>` is the person allowing forwarding from one mailbox of
    theirs, asked for by its id and its owner like every mailbox, so an id that
    is not theirs is "not connected".
    """
    auth = _auth()
    if auth is None:
        return _off()
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("sign in", 401)
    if meter.too_many("mailbox-start:" + me.user_id):
        return refuse(TOO_MANY, 429)
    forwarding = None
    if request.GET.get("forward"):
        forwarding = await sync_to_async(auth.store.mailbox)(me, request.GET.get("forward"))
        if forwarding is None:
            said = "That mailbox is not connected, so forwarding cannot be allowed from it."
            if _wants_the_url(request):
                return refuse(said, 404)
            return HttpResponseRedirect(page("&mailbox=error&say=" + _q(said)), status=303)
    try:
        client = await sync_to_async(auth.google_store.client_for)(me.org_id)
        back_to = auth.redirect_uri(public_base(request))
        if await redirect_accepted(config.google_auth_url, client.client_id, back_to) is False:
            said = NOT_REGISTERED.format(redirect=back_to)
            if _wants_the_url(request):
                return refuse(said, 409)
            return HttpResponseRedirect(page("&mailbox=error&say=" + _q(said)), status=303)
        state = await sync_to_async(auth.mint_state)(
            me, _session_of(request), forwarding=forwarding.id if forwarding else 0)
        hint = str(request.GET.get("hint") or "").strip()[:320]
        url = await sync_to_async(auth.consent_url)(me, state, base=public_base(request),
                                                    forwarding=forwarding,
                                                    hint=hint if "@" in hint else "")
    except NotSetUp:
        said = ("Google is not set up for your organisation yet. An administrator has to "
                "enter the organisation's Google app in Settings, under Google, first.")
        if _wants_the_url(request):
            return refuse(said, 409)
        return HttpResponseRedirect(page("&mailbox=error&say=" + _q(said)), status=303)
    if _wants_the_url(request):
        if forwarding is not None:
            return answer({"url": url, "scopes": list(mailboxes.FORWARD_SCOPES),
                           "say": f"Open this to allow forwarding from {forwarding.email}."})
        return answer({"url": url, "scopes": list(mailboxes.READ_SCOPES),
                       "say": "Open this to connect a mailbox, read-only."})
    return HttpResponseRedirect(url, status=303)


async def is_a_mailbox(request: HttpRequest) -> bool:
    """Whether this callback is finishing a mailbox's consent (its state's purpose)."""
    from rouh import runtime

    state = (request.GET.get("state") or "").strip()
    if "." not in state or runtime.google_store is None:
        return False
    nonce = state.rsplit(".", 1)[0]
    return await sync_to_async(runtime.google_store.state_purpose)(nonce) == mailboxes.PURPOSE


async def finish(request: HttpRequest):
    """Back from Google with a mailbox: spend the state, check it is theirs, keep the grant."""
    auth = _auth()
    if auth is None:
        return _off()
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("sign in", 401)
    if meter.too_many("mailbox-callback:" + me.user_id):
        return refuse(TOO_MANY, 429)
    try:
        issued = await sync_to_async(auth.take_state)(request.GET.get("state") or "",
                                                     _session_of(request))
    except ConsentFailed as exc:
        return HttpResponseRedirect(page("&mailbox=error&say=" + _q(str(exc))), status=303)
    if issued["user_id"] != me.user_id or issued["org_id"] != me.org_id:
        return HttpResponseRedirect(page("&mailbox=error&say=" + _q(
            "That sign-in was started by somebody else, so it was refused.")), status=303)
    forwarding = 0
    held = str(issued.get("next_path") or "")
    if held.startswith(mailboxes.FORWARDING):
        try:
            forwarding = int(held[len(mailboxes.FORWARDING):])
        except ValueError:
            forwarding = 0
    refused = request.GET.get("error") or ""
    if refused:
        said = ("You did not give Rouh permission, so "
                + ("forwarding is still off and nothing changed." if forwarding
                   else "no mailbox was connected.")
                if refused == "access_denied" else f"Google refused: {scrub(refused)}")
        return HttpResponseRedirect(page("&mailbox=denied&say=" + _q(said)), status=303)
    code = request.GET.get("code") or ""
    if not code:
        return HttpResponseRedirect(page("&mailbox=error&say=" + _q(
            "Google came back without an authorisation code.")), status=303)
    try:
        ident = await auth.finish(me, code, base=public_base(request), forwarding=forwarding)
    except NotSetUp:
        return HttpResponseRedirect(page("&mailbox=error&say=" + _q(
            "Google is not set up for your organisation.")), status=303)
    except (ConsentFailed, mailboxes.Refused) as exc:
        return HttpResponseRedirect(page("&mailbox=error&say=" + _q(str(exc))), status=303)
    except Exception:
        log.exception("a mailbox's token exchange failed")
        return HttpResponseRedirect(page("&mailbox=error&say=" + _q(
            "The exchange with Google did not finish. Try Connect a mailbox again.")), status=303)
    row = await sync_to_async(auth.store.row)(me, ident)
    outcome = "forwarding" if forwarding else "connected"
    return HttpResponseRedirect(page(f"&mailbox={outcome}&as=" + _q(row.email if row else "")),
                                status=303)


@only("POST")
async def disconnect(request: HttpRequest):
    auth = _auth()
    if auth is None:
        return _off()
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("sign in", 401)
    if meter.too_many("mailbox-disconnect:" + me.user_id):
        return refuse(TOO_MANY, 429)
    gone = await auth.disconnect(me, body_of(request).get("id"))
    if gone is None:
        return refuse("That mailbox is not connected.", 404)
    return answer({"ok": True, **gone})


@only("GET")
async def brief_ghosts(request: HttpRequest):
    auth = _auth()
    if auth is None:
        return answer({"ok": True, "mailboxes": [], "can_connect": False,
                       "note": "Google is switched off on this server."}, headers=NO_STORE)
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("sign in", 401)
    fresh = request.GET.get("fresh") == "1"
    if fresh and meter.too_many("ghosts:" + me.user_id):
        fresh = False
    got = await ghosts.listing(me, auth, config, fresh=fresh)
    got["can_connect"] = await sync_to_async(
        lambda: auth.google_store.client_summary(me.org_id)["configured"])()
    return answer(got, headers=NO_STORE)


@only("POST")
async def brief_ghosts_mark(request: HttpRequest):
    if _auth() is None:
        return _off()
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("sign in", 401)
    try:
        done = await sync_to_async(ghosts.mark)(me, body_of(request))
    except ghosts.Refused as exc:
        return refuse(str(exc), 400)
    return answer({"ok": True, **done}, headers=NO_STORE)


@only("POST")
async def brief_ghosts_send(request: HttpRequest):
    auth = _auth()
    if auth is None:
        return _off()
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("sign in", 401)
    if meter.too_many("ghost-send:" + me.user_id):
        return refuse(TOO_MANY, 429)
    try:
        done = await ghosts.send_nudge(me, auth, config, body_of(request))
    except ghosts.Refused as exc:
        return refuse(str(exc), 400)
    return answer({"ok": True, **done}, headers=NO_STORE)


@only("GET")
async def brief_mail_message(request: HttpRequest):
    auth = _auth()
    if auth is None:
        return _off()
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("sign in", 401)
    if meter.too_many("mail-message:" + me.user_id):
        return refuse(TOO_MANY, 429)
    try:
        got = await ghosts.message(me, auth, config, request.GET.get("mailbox"),
                                   str(request.GET.get("message") or ""))
    except ghosts.Refused as exc:
        return refuse(str(exc), 400)
    return answer({"ok": True, "message": got}, headers=NO_STORE)
