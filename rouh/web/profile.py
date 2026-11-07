"""The person's own profile, You, About You, opened by Edit behind their name.

    GET  /api/settings/profile            the profile, the card's name brought across first, and
                                          who they are and their company from their own contact
    POST /api/settings/profile            change any of {"first_name", "last_name", "nickname",
                                          "email", "follow_card", "pronouns", "card_about",
                                          "card_company"}: the last two are kept on their own
                                          contact card (`profile.py`)
    POST /api/settings/profile/password   {"current", "new", "again"}

What a profile is and what each field does is `rouh/profile.py`; the contact
card itself is picked and forgotten at `/api/settings/my-card`
(`rouh/web/mycard.py`), the same card the mail reads. This file is only the
routes.
"""
from __future__ import annotations

from asgiref.sync import sync_to_async
from django.http import HttpRequest

from rouh import profile

from .common import answer, body_of, only, refuse, who
from .google import Meter

#: Wrong passwords, a few a minute: the current one is checked here as at sign-in.
meter = Meter(5, 60.0)


@only("GET", "POST")
async def settings_profile(request: HttpRequest):
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("sign in", 401)
    if request.method == "GET":
        return answer(await sync_to_async(profile.state)(me.user_id, me.org_id))
    try:
        said = await sync_to_async(profile.save)(me.user_id, me.org_id, body_of(request))
    except ValueError as exc:
        return refuse(str(exc), 400, **(await sync_to_async(profile.state)(me.user_id, me.org_id)))
    return answer({"ok": True, "said": said, **(await sync_to_async(profile.state)(me.user_id, me.org_id))})


def _change_now(request: HttpRequest, user_id: str, body: dict) -> str:
    from django.contrib.auth import update_session_auth_hash

    from rouh.models import User

    user = User.objects.get(pk=user_id)
    said = profile.change_password(user, str(body.get("current") or ""), str(body.get("new") or ""),
                                   str(body.get("again") or ""))
    # This sign-in stays; every other one is asked for the new password.
    update_session_auth_hash(request, user)
    return said


@only("POST")
async def password(request: HttpRequest):
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("sign in", 401)
    if meter.too_many("password:" + me.user_id):
        return refuse("That is too many tries. Wait a minute.", 429)
    try:
        said = await sync_to_async(_change_now)(request, me.user_id, body_of(request))
    except ValueError as exc:
        return refuse(str(exc), 400)
    return answer({"ok": True, "said": said})
