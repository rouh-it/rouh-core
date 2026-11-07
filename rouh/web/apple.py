"""Settings for Apple Contacts: each person's own Apple ID and app-specific password.

    GET  /api/settings/apple             what Settings draws
    POST /api/settings/apple             check a pair against iCloud, and keep it if it works
    POST /api/settings/apple/sync        sync now
    POST /api/settings/apple/disconnect  forget the password and Rouh's copy of the cards

There is no organisation half, unlike Google: iCloud needs no app registered
anywhere, so each person's connection is theirs alone, keyed by user and
organisation (`rouh/apple_contacts.py`). Who is asking is `Tenancy.current`,
through `common.who`.

The password goes one way. It arrives in one POST, is checked against iCloud
with a real CardDAV discovery, is sealed if iCloud accepted it, and is never in
any answer, any log line or anything the page is sent afterwards. A password
iCloud refuses is not kept, and the answer says which of the two it was.
"""
from __future__ import annotations

import logging

from asgiref.sync import sync_to_async
from django.http import HttpRequest

from .common import answer, body_of, only, refuse, who
from .google import Meter

log = logging.getLogger("rouh.contacts")

#: How often one person may try a password, or ask for a sync. Each try is a
#: request to Apple, and a stream of wrong ones against an Apple ID is exactly
#: what Apple locks an account for.
meter = Meter(6, 60.0)

TOO_MANY = "That is too many attempts. Wait a minute."


def _desk():
    from rouh import runtime

    return runtime.contacts


def _off():
    return refuse("Apple Contacts are switched off on this server: passwords cannot be "
                  "encrypted here.", 503)


async def _state(desk, me) -> dict:
    # Whether a sync is running is asked before what the last one did, never
    # after. The page announces a sync's result the moment it is told none is
    # running, so "not running" has to mean "finished before the rest of this
    # was read". The other way round, a sync that ended between the two reads
    # was reported as finished with the previous sync's numbers: a password
    # this server could not open came back as "Synced from iCloud".
    syncing = desk.syncing(me)
    summary = await sync_to_async(desk.store.summary)(me.user_id, me.org_id)
    return {
        "connection": summary,
        "syncing": syncing,
        # What to put in the Apple ID box before anybody has typed: the address
        # this account was made with, which for Petar is his Apple ID. Only a
        # suggestion; whatever is typed is what is checked.
        "suggested_apple_id": summary["apple_id"] or me.email or "",
    }


async def _settings_apple(request: HttpRequest):
    desk = _desk()
    if desk is None:
        return _off()
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("sign in", 401)
    return answer(await _state(desk, me))


async def _connect(request: HttpRequest):
    desk = _desk()
    if desk is None:
        return _off()
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("sign in", 401)
    if meter.too_many("connect:" + me.user_id):
        return refuse(TOO_MANY, 429)
    body = body_of(request)
    try:
        said = await desk.connect(me, str(body.get("apple_id") or ""),
                                  str(body.get("app_password") or ""))
    except ValueError as exc:
        return refuse(str(exc), 400, **(await _state(desk, me)))
    return answer({"ok": True, "said": said, **(await _state(desk, me))})


@only("GET", "POST")
async def settings_apple(request: HttpRequest):
    if request.method == "POST":
        return await _connect(request)
    return await _settings_apple(request)


@only("POST")
async def sync_now(request: HttpRequest):
    desk = _desk()
    if desk is None:
        return _off()
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("sign in", 401)
    if meter.too_many("sync:" + me.user_id):
        return refuse(TOO_MANY, 429)
    state = await _state(desk, me)
    if not state["connection"]["connected"]:
        return refuse("Apple Contacts are not connected.", 409, **state)
    if state["connection"]["needs_new_password"]:
        return refuse("iCloud stopped accepting the app-specific password. Enter a new "
                      "one first.", 409, **state)
    desk.sync_soon(me)
    return answer({"ok": True, **(await _state(desk, me))})


@only("POST")
async def disconnect(request: HttpRequest):
    desk = _desk()
    if desk is None:
        return _off()
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("sign in", 401)
    gone = await desk.disconnect(me)
    return answer({"ok": True, "removed": gone, **(await _state(desk, me))})
