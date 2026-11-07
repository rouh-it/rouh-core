"""Rouh Land Account, Your profile, over the web (`rouh/landaccount.py`, `landaccountpage.js`).

    GET  /api/rouh-land/account         what Your profile draws: whether you have a rouh.land
                                        account this Rouh knows of, whether this Rouh is connected
                                        to it, and what is wrong between them, if anything
    POST /api/rouh-land/account/check   the page's own ask of rouh.land, as it opens (at most once
                                        in five minutes) or `{"retry": true}` beside an error;
                                        answers what GET does. An administrator's.

Reading is anybody's signed in.
"""
from __future__ import annotations

from asgiref.sync import sync_to_async
from django.http import HttpRequest, HttpResponseNotAllowed

from rouh import birth, landaccount

from .comments import NO_STORE
from .common import answer, body_of, refuse, who


async def page(request: HttpRequest):
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("Sign in to Rouh first.", 401)
    if request.method not in ("GET", "HEAD"):
        return HttpResponseNotAllowed(["GET"])
    return answer(await sync_to_async(landaccount.page)(me), headers=NO_STORE)


async def check(request: HttpRequest):
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("Sign in to Rouh first.", 401)
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    try:
        got = await sync_to_async(landaccount.check_now)(me, retry=bool(body_of(request).get("retry")))
    except birth.Refused as exc:
        return refuse(str(exc), 403)
    return answer(got, headers=NO_STORE)
