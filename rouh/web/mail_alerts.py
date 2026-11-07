"""New mail in Settings, and the address Google's Pub/Sub posts new mail to.

    GET  /api/settings/mail-alerts            what the card draws
    POST /api/settings/mail-alerts/on         watch the inbox, and hand new mail to Rouh
    POST /api/settings/mail-alerts/off        stop
    POST /api/settings/mail-alerts/topic      an administrator: the organisation's topic,
                                              or {"remove": true}
    POST /hooks/gmail/<token>                 Pub/Sub, with a note that the inbox changed
    GET  /settings/mail-alerts/log            the log: every message read, what Rouh did
                                              about it, and the way to its conversation

`/guidance`, what the person said was worth a note to the small model that
judged each message, went with that model on 25 September 2026
(fr_b657bd8f6100): Rouh itself handles every message now.

Two levels, like Google's own card. The topic and the address Google posts to
are the organisation's, and only an administrator sees or changes them; turning
alerts on is each person's own, for their own connected mailbox. Who is asking
is `Tenancy.current`, through `common.who`.

The last address is the only one here without a sign-in, and it is on the
gate's list for that reason (`gate.py`): Google posts to it. What lets a
caller through is the token in the address, and all a note that gets through
can do is make Rouh look at the inbox (`rouh/mail_alerts.py`).
"""
from __future__ import annotations

import logging

from asgiref.sync import sync_to_async
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt

from rouh.config import config

from .common import answer, body_of, only, refuse, who
from .google import Meter

log = logging.getLogger("rouh.mail_alerts")

#: How often one person may press on or off. Each press is a call to Gmail.
meter = Meter(12, 60.0)

#: How many notes one organisation's address takes in a minute. Gmail sends
#: one per change to an inbox, which is a handful a minute on a busy day; past
#: this Pub/Sub is told to come back later, which it does by itself.
pushes = Meter(240, 60.0)

TOO_MANY = "That is too many attempts. Wait a minute."
NOT_ADMIN = "Only an administrator of your organisation can change this."


def _desk():
    from rouh import runtime

    return runtime.mail_alerts


def _off():
    return refuse("Mail alerts are switched off on this server: credentials cannot be "
                  "encrypted here.", 503)


async def _state(desk, me) -> dict:
    return await sync_to_async(desk.state)(me, config.public_url)


async def _me(request: HttpRequest):
    return await sync_to_async(who)(request)


@only("GET")
async def settings_alerts(request: HttpRequest):
    desk = _desk()
    if desk is None:
        return _off()
    me = await _me(request)
    if me is None:
        return refuse("sign in", 401)
    return answer(await _state(desk, me))


@only("GET")
async def decision_log(request: HttpRequest):
    """Every new message read for the person asking, and what Rouh did about it.

    A page of its own, linked from the Mail alerts card, because it is long
    and is read beside a mail app while a test is sent. `show` is sent, quiet
    or all; `before` is the id the previous page ended at. Only ever the
    asker's own rows (`AlertStore.decisions`). No-store, because the point of
    it is what is true now; the page asks again by itself while it is open.
    """
    from rouh.mail_alerts import LOG_ROUTE

    me = await _me(request)
    if me is None:
        return HttpResponseRedirect("/login?next=" + LOG_ROUTE)
    desk = _desk()
    try:
        before = max(0, int(request.GET.get("before") or 0))
    except ValueError:
        before = 0
    context = {"off": True, "route": LOG_ROUTE}
    if desk is not None:
        context = {"off": False, "route": LOG_ROUTE, **await sync_to_async(desk.log_view)(
            me, show=request.GET.get("show") or "all", before=before)}
    response = await sync_to_async(render)(request, "rouh/mail_log.html", context)
    response["Cache-Control"] = "no-store, must-revalidate"
    return response


@only("POST")
async def turn_on(request: HttpRequest):
    desk = _desk()
    if desk is None:
        return _off()
    me = await _me(request)
    if me is None:
        return refuse("sign in", 401)
    if meter.too_many("switch:" + me.user_id):
        return refuse(TOO_MANY, 429)
    try:
        said = await desk.turn_on(me)
    except ValueError as exc:
        return refuse(str(exc), 409, **(await _state(desk, me)))
    return answer({"ok": True, "said": said, **(await _state(desk, me))})


@only("POST")
async def turn_off(request: HttpRequest):
    desk = _desk()
    if desk is None:
        return _off()
    me = await _me(request)
    if me is None:
        return refuse("sign in", 401)
    if meter.too_many("switch:" + me.user_id):
        return refuse(TOO_MANY, 429)
    said = await desk.turn_off(me)
    return answer({"ok": True, "said": said, **(await _state(desk, me))})


@only("POST")
async def topic(request: HttpRequest):
    from rouh.mail_alerts import check_topic

    desk = _desk()
    if desk is None:
        return _off()
    me = await _me(request)
    if me is None:
        return refuse("sign in", 401)
    if not me.is_admin:
        return refuse(NOT_ADMIN, 403)
    body = body_of(request)
    try:
        named = "" if body.get("remove") is True else check_topic(str(body.get("topic") or ""))
    except ValueError as exc:
        return refuse(str(exc), 400)
    if not named and body.get("remove") is not True:
        return refuse("Enter the topic's full name, like "
                      "projects/your-project-id/topics/gmail-alerts.", 400)
    await sync_to_async(desk.store.set_topic)(me.org_id, named, by_user_id=me.user_id)
    log.info("the gmail push topic for org %s was %s by user %s", me.org_id,
             "set" if named else "removed", me.user_id)
    if named:
        # Everybody already watching carries on, on the topic that is there now.
        desk.renew_organisation(me.org_id)
    said = ("Saved. Each person can now turn alerts on for their own inbox." if named
            else "Removed. Nobody's watch is renewed until a topic is entered again.")
    return answer({"ok": True, "said": said, **(await _state(desk, me))})


@csrf_exempt
@only("POST")
async def gmail_push(request: HttpRequest, token: str):
    """Google's Pub/Sub, saying that a watched inbox changed.

    Answered at once and looked at afterwards: Pub/Sub waits ten seconds for a
    reply before it tries again, and reading a message and handing it to Rouh
    takes longer than that. Any 2xx tells Pub/Sub the note arrived. A token nobody
    holds is a 404, which a stale subscription goes on getting until somebody
    deletes it; a note that cannot be read is taken and dropped, because
    sending it again would not make it readable.
    """
    from rouh.mail_alerts import read_push

    desk = _desk()
    if desk is None:
        return HttpResponse(status=404)
    org_id = await sync_to_async(desk.store.org_for_token)(token)
    if not org_id:
        log.info("a gmail push to an address nobody holds")
        return HttpResponse(status=404)
    if pushes.too_many(org_id):
        return HttpResponse(status=429)
    note = read_push(body_of(request))
    if note is None:
        log.info("a gmail push for org %s that said nothing readable", org_id)
        return HttpResponse(status=204)
    address, _history = note
    count = await desk.pushed(org_id, address)
    # Synapse Master's copy of the same inbox reads its history now too (`synapse/gmailsync.py`).
    try:
        from rouh.synapse import gmailsync

        await sync_to_async(gmailsync.pushed)(org_id, address)
    except Exception:  # noqa: BLE001 - the copy reads Gmail every minute anyway
        log.exception("could not tell Synapse's Gmail sync about a push")
    log.info("a gmail push for org %s: %d watching", org_id, count)
    return HttpResponse(status=204)
