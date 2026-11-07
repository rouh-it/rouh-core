"""Forgot password: asking for a link, following it, and setting a new one.

    GET  /login/forgot                     the form: username or email
    POST /login/forgot                     answered the same whoever it is
    GET  /login/reset/<uid>/<token>        the link in the email
    GET  /login/reset/<uid>/set-password   the form for the new password
    POST /login/reset/<uid>/set-password
    GET  /login/common-passwords           the list "not a common one" is judged by

All of them are in front of the gate (`gate.py`), because the person they are
for cannot sign in. What a reset is and how its link reaches anybody is
`rouh/password_reset.py`; this is the pages.

The token in the link is moved out of the address as soon as it arrives, into
the browser's own session, and the form is shown at an address without it -
which is what Django's own reset view does, for the same reason: an address
with a live token in it would otherwise sit in the browser's history, and be
sent on as the Referer by anything the page loaded. The request log is kept
free of it too (`password_reset.HideResetTokens`).
"""
from __future__ import annotations

import asyncio
import gzip
import logging

from django.contrib import messages
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import render

from rouh import accounts, password_reset, password_rules

from .common import client_ip

log = logging.getLogger("rouh.reset")

#: Where a followed link's token is kept, in that browser's session only.
SESSION_KEY = "password_reset"
#: The second half of the form's address, where the token was.
SET_PASSWORD = "set-password"
#: The name the sign-in page is filled in with once a password is changed.
SIGN_IN_AS = "sign_in_as"

#: Requests for a link from one address, before it is told to wait. A person
#: asks once or twice; anything asking dozens of times is trying names.
PER_ADDRESS = 6
PER_ADDRESS_SECONDS = 15 * 60
_asked_lately = password_reset.Recent(PER_ADDRESS, PER_ADDRESS_SECONDS)


def _no_store(response: HttpResponse) -> HttpResponse:
    response["Cache-Control"] = "no-store"
    return response


def _forgot_page(request: HttpRequest, *, sent: bool = False, note: str = "", said: str = "",
                 status: int = 200) -> HttpResponse:
    return _no_store(render(request, "rouh/forgot.html",
                            {"sent": sent, "note": note, "said": said}, status=status))


async def forgot(request: HttpRequest) -> HttpResponse:
    """Ask for a link. Whoever it is, the answer is the same page."""
    if request.method == "POST":
        said = (request.POST.get("who") or "").strip()[:254]
        ip = client_ip(request)
        if not said:
            return await asyncio.to_thread(
                _forgot_page, request, note="Type your username or your email address.",
                status=400)
        if _asked_lately.too_many(ip):
            log.warning("password reset asked for too often from %s", ip)
            return await asyncio.to_thread(
                _forgot_page, request, said=said, status=429,
                note="That is a lot of requests from here. Try again in a quarter of an hour.")
        # The looking up and the sending happen after this answer has gone,
        # so it takes as long for a name nobody has as for Petar's.
        password_reset.start(said)
        log.info("password reset asked for from %s", ip)
        return HttpResponseRedirect("/login/forgot?sent=1", status=303)
    if request.method not in ("GET", "HEAD"):
        return HttpResponse(status=405, headers={"Allow": "GET, HEAD, POST"})
    return await asyncio.to_thread(_forgot_page, request, sent=request.GET.get("sent") == "1")


# Both of these answer 200: a link that has run out and a password with
# something wrong with it are pages a person reads, not a request gone wrong
# for the log to warn about.


def _dead(request: HttpRequest) -> HttpResponse:
    return _no_store(render(request, "rouh/reset.html", {"dead": True}))


def _form(request: HttpRequest, user, problems=()) -> HttpResponse:
    person = {"username": user.username, "email": user.email,
              "first_name": user.first_name, "last_name": user.last_name}
    response = render(request, "rouh/reset.html", {
        "username": user.username, "problems": list(problems),
        "min_length": password_rules.min_length(),
        "password_rules": password_rules.for_page(
            person, username_is_email=user.username.lower() == (user.email or "").lower()),
    })
    # No Referrer-Policy of its own: "no-referrer" makes a browser post the form
    # with "Origin: null", which the CSRF check rightly refuses. The token is
    # not in this page's address anyway, and the site's own policy is
    # same-origin.
    return _no_store(response)


def _follow(request: HttpRequest, uid: str, token: str) -> HttpResponse:
    user = password_reset.user_of(uid)
    if token != SET_PASSWORD:
        # The link from the email: check it, keep it out of the address.
        if not password_reset.token_good(user, token):
            log.info("a password reset link was refused")
            return _dead(request)
        request.session[SESSION_KEY] = {"uid": uid, "token": token}
        return HttpResponseRedirect(f"{password_reset.LINK_PATH}{uid}/{SET_PASSWORD}",
                                    status=303)

    kept = request.session.get(SESSION_KEY) or {}
    token = str(kept.get("token") or "") if kept.get("uid") == uid else ""
    if not password_reset.token_good(user, token):
        request.session.pop(SESSION_KEY, None)
        return _dead(request)
    if request.method != "POST":
        return _form(request, user)

    first = request.POST.get("password1") or ""
    second = request.POST.get("password2") or ""
    if first != second:
        return _form(request, user, ["The two passwords are not the same."])
    try:
        validate_password(first, user)
    except ValidationError as exc:
        return _form(request, user, exc.messages)

    # A fresh session for this browser first: whoever it was signed in as, and
    # the token, go with the old one. Then the password, which signs the
    # account out everywhere else (`accounts.set_password`).
    request.session.flush()
    accounts.set_password(user.username, first)
    log.info("%s set a new password from a reset link, from %s", user.username,
             client_ip(request))
    messages.success(request, "Your password has been changed, and every device signed in "
                              "to this account has been signed out. Sign in with the new one.")
    request.session[SIGN_IN_AS] = user.username
    return HttpResponseRedirect("/login", status=303)


async def follow(request: HttpRequest, uid: str, token: str) -> HttpResponse:
    """The link from the email, and the form it leads to."""
    if request.method not in ("GET", "HEAD", "POST"):
        return HttpResponse(status=405, headers={"Allow": "GET, HEAD, POST"})
    return await asyncio.to_thread(_follow, request, uid, token)


async def common_passwords(request: HttpRequest) -> HttpResponse:
    """Django's list of common passwords, for the lines under a new password
    to tick off "not a commonly used password" as it is typed
    (`rouh/password_rules.py`). The same list for everybody and public
    anyway, so it is open, and kept a day."""
    if request.method not in ("GET", "HEAD"):
        return HttpResponse(status=405, headers={"Allow": "GET, HEAD"})
    body = await asyncio.to_thread(password_rules.common_passwords)
    headers = {"Cache-Control": "public, max-age=86400", "Vary": "Accept-Encoding",
               "X-Content-Type-Options": "nosniff"}
    if "gzip" in request.headers.get("Accept-Encoding", ""):
        headers["Content-Encoding"] = "gzip"
    else:
        body = gzip.decompress(body)
    return HttpResponse(body, content_type="text/plain; charset=utf-8", headers=headers)
