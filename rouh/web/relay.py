"""Settings, Connections, Phone, at /anatomy/connections/phone, and the relay's two open addresses
(`rouh/relay.py`).

    GET  /api/settings/phone            the address, the real state, the certificate, this month's
                                        traffic beside the fair limit when the relay says it
    POST /api/settings/phone/on         "Reach me from my phone": frpc starts, the address opens
    POST /api/settings/phone/off        the address closes; it stays this Rouh's
    POST /api/settings/phone/claim      ask the relay for the address again (when the claim at
                                        birth did not get through)
    POST /api/settings/phone/signin     a one-time sign-in link for the phone, with its QR code

    GET  /.well-known/acme-challenge/<token>   Let's Encrypt's HTTP-01 check, open to everybody
    GET  /phone/in?code=...                    the QR code's link: signs the owner in, once

Only an administrator turns the address on or off or makes a sign-in link; everybody signed in
reads the state.
"""
from __future__ import annotations

import asyncio
import logging

from django.contrib.auth import alogin
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import render

from .clock import _signed_in
from .common import answer, client_ip, only, refuse

log = logging.getLogger("rouh.web.relay")
NO_STORE = {"Cache-Control": "no-store"}


async def _me(request):
    return await asyncio.to_thread(_signed_in, request)


@only("GET")
async def page(request: HttpRequest) -> HttpResponse:
    from rouh import relay

    me = await _me(request)
    if me is None:
        return refuse("Sign in first.", 401)
    got = await asyncio.to_thread(relay.status)
    got["admin"] = bool(getattr(me, "is_admin", False))
    return answer(got, headers=NO_STORE)


async def _admin_do(request, work):
    from rouh import relay

    me = await _me(request)
    if me is None:
        return refuse("Sign in first.", 401)
    if not getattr(me, "is_admin", False):
        return refuse("Only an administrator of this Rouh does that.", 403)
    try:
        got = await work(me)
    except relay.Refused as exc:
        return refuse(str(exc), 400, **(await asyncio.to_thread(relay.status)), admin=True)
    # The page draws what comes back, and only an administrator got here: without this its
    # buttons went until the next look.
    if isinstance(got, dict) and "state" in got:
        got["admin"] = True
    return answer(got, headers=NO_STORE)


@only("POST")
async def turn_on(request: HttpRequest) -> HttpResponse:
    from rouh import relay

    return await _admin_do(request, lambda me: relay.turn_on())


@only("POST")
async def turn_off(request: HttpRequest) -> HttpResponse:
    from rouh import relay

    return await _admin_do(request, lambda me: relay.turn_off())


@only("POST")
async def claim(request: HttpRequest) -> HttpResponse:
    from rouh import relay

    async def work(me):
        # A Rouh born before its first run asked, already linked to its owner's rouh.land account:
        # that link is the choice of Connected, so its address is asked for now.
        if await asyncio.to_thread(relay.chose_connected) is None and await asyncio.to_thread(relay.in_account):
            await asyncio.to_thread(lambda: relay.linked_later(claim=False))
        await asyncio.to_thread(relay.claim)
        return await asyncio.to_thread(relay.status)

    return await _admin_do(request, work)



@only("POST")
async def signin(request: HttpRequest) -> HttpResponse:
    from rouh import relay
    from rouh.models import User

    async def work(me):
        user = await asyncio.to_thread(User.objects.get, pk=me.user_id)
        return await asyncio.to_thread(relay.signin_link, user)

    return await _admin_do(request, work)


@only("GET")
async def challenge(request: HttpRequest, token: str) -> HttpResponse:
    from rouh import relay

    said = relay.challenge_answer(token)
    if not said:
        raise Http404
    return HttpResponse(said, content_type="text/plain", headers=NO_STORE)


@only("GET")
async def phone_in(request: HttpRequest) -> HttpResponse:
    """The QR code's link. The code is taken out of the address at once, whatever it is."""
    from rouh import relay
    from rouh.models import User

    code = request.GET.get("code", "")
    uid = relay.take_signin(code) if code else ""
    if not uid:
        if code:
            log.warning("phone sign-in: a used, wrong or old code from %s", client_ip(request))
        response = render(request, "rouh/phone_in.html", {}, status=403 if code else 200)
        response["Cache-Control"] = "no-store"
        response["Referrer-Policy"] = "same-origin"
        return response
    user = await asyncio.to_thread(lambda: User.objects.filter(pk=uid, is_active=True).first())
    if user is None:
        return HttpResponseRedirect("/login", status=303)
    await alogin(request, user, backend="rouh.accounts.CaseInsensitiveBackend")
    log.info("phone sign-in: %s signed in on a phone from %s", user.username, client_ip(request))
    return HttpResponseRedirect("/", status=303)
