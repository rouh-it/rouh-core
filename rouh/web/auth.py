"""Signing in and signing out: one email box, and Rouh decides what follows (`rouh/signin.py`).

    GET  /login                    the email box and Continue
    POST /login  step=email        Continue: "Check your email" (a link and a code went, if the
                                   address signs anybody in), or a password box when this Rouh
                                   cannot send mail. The same answer for every address.
    POST /login  step=code         the six-digit code from the letter
    POST /login  step=password     the password: the way in when this Rouh cannot send mail, and
                                   the quiet fallback under "Can't get the email?" when it can
    GET/POST /login/link/<token>   the letter's link: in at once in the browser that asked, after
                                   one press anywhere else (so a mail scanner never uses it up)
    POST /login/passkey/options    a challenge for a passkey this device holds
    POST /login/passkey/verify     the passkey's answer
    POST /logout                   sign out

Google is never a way in here (Petar, 4 November 2026: "google will never be a login"): it is
connected as mail, calendar and Drive, and nothing more.

A refused attempt is written down, by address and by the name that was tried, and the next one
from that address or against that account waits longer; after eight in a quarter of an hour none
is checked for a quarter of an hour (`rouh/accounts.py`).
"""
from __future__ import annotations

import asyncio
import json
import logging
import secrets

from django.contrib import messages
from django.contrib.auth import aauthenticate, alogin, alogout
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import render

from rouh import accounts, signin

from . import firstrun
from .common import client_ip, public_base
from .gate import next_page
from .reset import SIGN_IN_AS

log = logging.getLogger("rouh.auth")

#: What a refused password says. One sentence for an address nobody has and a wrong password.
REFUSED = "That email and password do not match an account here."
#: What a wrong or used-up code says.
CODE_REFUSED = "That code is not right, or it has been used or has expired. Check the newest email, or ask for a new one."

#: The cookie a sign-in lived in until 22 September 2026, when the app was Jarvis.
OLD_COOKIE = "jarvis_session"

#: The asking browser's own token, so its letter's link signs it in without a second press.
BROWSER = "signin_browser"
#: The passkey challenge this browser was given.
CHALLENGE = "signin_passkey_challenge"
#: The address typed, kept for the page that follows Continue.
TYPED = "signin_email"
#: The backend a sign-in here names: the one that checks passwords, and keeps the session.
BACKEND = "rouh.accounts.CaseInsensitiveBackend"


def _through_relay(request: HttpRequest) -> bool:
    from rouh import relay

    try:
        return relay.through(request)
    except Exception:  # noqa: BLE001 - the sign-in page always draws
        return False


def _page(request: HttpRequest, template: str = "rouh/login.html", *, status: int = 200, **more) -> HttpResponse:
    context = {
        "next_to": next_page(more.pop("next_to", "")),
        "minutes": signin.LINK_MINUTES,
        # In the containers the owner can also be let in from this machine (`firstrun.py`), or, on the
        # phone address, with the QR code that machine shows (`rouh/relay.py`).
        "owner_way": firstrun.owner_way_in(),
        "phone_way": _through_relay(request),
        **more,
    }
    response = render(request, template, context, status=status)
    response["Cache-Control"] = "no-store"
    response["Referrer-Policy"] = "same-origin"
    return response


async def _said(request) -> tuple[str, bool]:
    said = await asyncio.to_thread(lambda: list(messages.get_messages(request)))
    note = " ".join(str(m) for m in said)
    return note, bool(said) and all(m.level < messages.WARNING for m in said)


async def login(request: HttpRequest) -> HttpResponse:
    """The email box, and what it posts to. Somebody already signed in is sent on."""
    if request.method == "POST":
        step = request.POST.get("step") or ("password" if request.POST.get("password") else "email")
        if step == "code":
            return await _by_code(request)
        if step == "password":
            return await _by_password(request)
        return await _continue(request)
    if request.method not in ("GET", "HEAD"):
        return HttpResponse(status=405, headers={"Allow": "GET, HEAD, POST"})
    user = await request.auser()
    if user.is_authenticated:
        return HttpResponseRedirect(next_page(request.GET.get("next")), status=303)
    if await asyncio.to_thread(firstrun.open_now):
        return HttpResponseRedirect(firstrun.PATH, status=303)
    note, good = await _said(request)
    email = await request.session.apop(SIGN_IN_AS, "") or request.GET.get("email", "")
    return await asyncio.to_thread(_page, request, note=note, note_good=good, email=signin.normal(email),
                                   next_to=request.GET.get("next", ""))


def _browser(request) -> str:
    nonce = request.session.get(BROWSER)
    if not nonce:
        nonce = secrets.token_urlsafe(18)
        request.session[BROWSER] = nonce
    return nonce


def _link_base(request) -> str:
    """Where a letter's link points: the name this browser is on when it is one of Rouh's own,
    else the installation's public address, else, on this machine only, the address asked on."""
    base = public_base(request)
    if base:
        return base
    host = request.get_host()
    name = host.rsplit(":", 1)[0].strip("[]").lower()
    if name in ("localhost", "127.0.0.1", "::1"):
        return f"{request.scheme}://{host}"
    return ""


def _continue_sync(request, email: str, back: str):
    """What follows Continue. Returns (template, context, status)."""
    if email and "@" not in email:
        # A username: an account made with no email (`manage.py account add`) still signs in with
        # its password, so no account is ever left without a way in.
        return "rouh/login_password.html", {"email": email}, 200
    if not signin.looks_right(email):
        return "rouh/login.html", {"email": email, "note": "Type your whole email address, such as you@example.com."}, 400
    request.session[TYPED] = email
    if not signin.can_send():
        return "rouh/login_password.html", {"email": email}, 200
    try:
        made = signin.make(email, ip=client_ip(request), browser=_browser(request), next_to=back)
    except signin.Limited as exc:
        return "rouh/login.html", {"email": email, "note": str(exc)}, 429
    if made.get("token"):
        base = _link_base(request)
        made["link"] = base + signin.LINK_PATH + made["token"] if base else ""
    return "rouh/login_check.html", {"email": email, "_made": made}, 200


async def _continue(request: HttpRequest) -> HttpResponse:
    back = next_page(request.POST.get("next", ""))
    email = signin.normal(request.POST.get("email") or request.POST.get("username"))
    template, context, status = await asyncio.to_thread(_continue_sync, request, email, back)
    made = context.pop("_made", None) or {}
    if made.get("token"):
        # Sent after the page has answered: the time it takes says nothing about the address.
        signin.start_sending("", email, made["token"], made["link"], made["code"])
    if template == "rouh/login_check.html" and status == 200:
        log.info("a sign-in email was asked for from %s", client_ip(request))
    return await asyncio.to_thread(_page, request, template, status=status, next_to=back, **context)


async def _locked(request, name: str):
    locked = await asyncio.to_thread(accounts.locked_for, client_ip(request), name)
    if locked > 0:
        minutes = max(1, int(locked // 60) + 1)
        return f"Too many attempts. Try again in {minutes} minute{'s' if minutes != 1 else ''}."
    return ""


async def _refused(request, name: str) -> None:
    ip = client_ip(request)
    await asyncio.sleep(await asyncio.to_thread(accounts.delay_for, ip, name))
    await asyncio.to_thread(accounts.record_failure, ip, name)


async def _in(request, user, back: str, how: str, email: str = "") -> HttpResponse:
    await asyncio.to_thread(accounts.forget_failures, client_ip(request), user.username)
    await alogin(request, user, backend=BACKEND)
    if email:
        await asyncio.to_thread(signin.retire_others, user, email)
    log.info("account %s signed in by %s from %s", user.pk, how, client_ip(request))
    return HttpResponseRedirect(back, status=303)


async def _by_code(request: HttpRequest) -> HttpResponse:
    back = next_page(request.POST.get("next", ""))
    email = signin.normal(request.POST.get("email") or request.session.get(TYPED, ""))
    locked = await _locked(request, email)
    if locked:
        return await asyncio.to_thread(_page, request, "rouh/login_check.html", status=429, next_to=back,
                                       email=email, note=locked)
    user = await asyncio.to_thread(signin.by_code, email, request.POST.get("code", ""))
    if user is None:
        await _refused(request, email)
        return await asyncio.to_thread(_page, request, "rouh/login_check.html", status=401, next_to=back,
                                       email=email, note=CODE_REFUSED)
    return await _in(request, user, back, "a code from a sign-in email", email)


def _account_by_password(name: str):
    """An address that signs somebody in, or a username, to the account to check the password of."""
    user = signin.user_for(name) if "@" in name else None
    return user.username if user is not None else name


async def _by_password(request: HttpRequest) -> HttpResponse:
    back = next_page(request.POST.get("next", ""))
    name = (request.POST.get("email") or request.POST.get("username") or "").strip()
    template = request.POST.get("from") == "check" and "rouh/login_check.html" or "rouh/login_password.html"
    locked = await _locked(request, name)
    if locked:
        log.warning("sign-in locked out from %s", client_ip(request))
        return await asyncio.to_thread(_page, request, template, status=429, next_to=back, email=name,
                                       note=locked, open_fallback=True)
    username = await asyncio.to_thread(_account_by_password, name)
    person = await aauthenticate(request, username=username, password=request.POST.get("password") or "")
    if person is None:
        await _refused(request, name)
        log.warning("a password sign-in was refused from %s", client_ip(request))
        return await asyncio.to_thread(_page, request, template, status=401, next_to=back, email=name,
                                       note=REFUSED, open_fallback=True)
    return await _in(request, person, back, "password", signin.normal(name) if "@" in name else "")


async def link(request: HttpRequest, token: str) -> HttpResponse:
    """A letter's link. In the browser that asked, it signs in at once; anywhere else, one press
    first, so a mail service that opens links before anybody reads them does not use it up."""
    if request.method not in ("GET", "HEAD", "POST"):
        return HttpResponse(status=405, headers={"Allow": "GET, HEAD, POST"})
    row = await asyncio.to_thread(signin.peek, token)
    bad = await asyncio.to_thread(signin.why_not, row)
    if bad:
        return await asyncio.to_thread(_page, request, "rouh/login_link.html", status=410, bad=bad)
    same = signin.same_browser(row, request.session.get(BROWSER, ""))
    if request.method != "POST" and not same:
        return await asyncio.to_thread(_page, request, "rouh/login_link.html", email=row.email, token=token)
    user = await asyncio.to_thread(signin.take, row)
    if user is None:
        return await asyncio.to_thread(_page, request, "rouh/login_link.html", status=410,
                                       bad="This link was used already. Each link works once.")
    await alogin(request, user, backend=BACKEND)
    log.info("account %s signed in by a sign-in link from %s", user.pk, client_ip(request))
    back = "/anatomy/you/account" if row.next == signin.CONFIRM else next_page(row.next)
    return HttpResponseRedirect(back, status=303)


#: The way in an administrator on the machine makes, as the help page says it.
COMMAND = "python manage.py signin_link you@example.com"
COMMAND_DOCKER = "docker compose exec core python manage.py signin_link you@example.com"


async def help_page(request: HttpRequest) -> HttpResponse:
    """Other ways in, for the owner, when no email arrives."""
    command = COMMAND_DOCKER if firstrun.code_file() else COMMAND
    return await asyncio.to_thread(_page, request, "rouh/login_help.html", command=command,
                                   next_to=request.GET.get("next", ""))


# --- passkeys ----------------------------------------------------------------------------------------


def _rp(request) -> tuple[str, str]:
    """This site as WebAuthn names it: its host, and its origin."""
    host = request.get_host()
    name = host.rsplit(":", 1)[0].strip("[]").lower() if not host.endswith("]") else host.strip("[]")
    return name, f"{request.scheme}://{host.lower()}"


def _json(request) -> dict:
    try:
        got = json.loads(request.body or b"{}")
    except ValueError:
        return {}
    return got if isinstance(got, dict) else {}


async def passkey_options(request: HttpRequest) -> HttpResponse:
    """A challenge for signing in with a passkey. Asks nothing of the address typed: any passkey
    this site knows may answer, so nothing here says whether an account exists."""
    if request.method != "POST":
        return HttpResponse(status=405)
    from rouh import passkeys

    challenge = secrets.token_bytes(32)
    await request.session.aset(CHALLENGE, passkeys.b64url(challenge))
    rp_id, _origin = _rp(request)
    return JsonResponse({"challenge": passkeys.b64url(challenge), "rpId": rp_id, "timeout": 120000,
                         "userVerification": "preferred"}, headers={"Cache-Control": "no-store"})


def _passkey_in(request, got: dict):
    from rouh import passkeys
    from rouh.models import Passkey

    challenge = request.session.pop(CHALLENGE, "")
    if not challenge:
        return None
    try:
        cred = passkeys.unb64url(got.get("id", ""))
        row = Passkey.objects.select_related("user").filter(credential_id=cred).first()
        if row is None or not row.user.is_active:
            return None
        rp_id, origin = _rp(request)
        count = passkeys.assertion(
            client_data=passkeys.unb64url(got.get("clientDataJSON", "")),
            auth_data=passkeys.unb64url(got.get("authenticatorData", "")),
            signature=passkeys.unb64url(got.get("signature", "")), cose=bytes(row.public_key),
            challenge=passkeys.unb64url(challenge), origin=origin, rp_id=rp_id, sign_count=row.sign_count)
    except passkeys.Wrong as exc:
        log.warning("a passkey sign-in was refused: %s", exc)
        return None
    import time

    Passkey.objects.filter(pk=row.pk).update(sign_count=count, last_used_at=time.time())
    return row.user


async def passkey_verify(request: HttpRequest) -> HttpResponse:
    if request.method != "POST":
        return HttpResponse(status=405)
    back = next_page(request.GET.get("next", ""))
    locked = await _locked(request, "passkey")
    if locked:
        return JsonResponse({"error": locked}, status=429)
    user = await asyncio.to_thread(_passkey_in, request, _json(request))
    if user is None:
        await _refused(request, "passkey")
        return JsonResponse({"error": "That passkey did not sign anybody in here. Send yourself a link instead."},
                            status=401)
    await asyncio.to_thread(accounts.forget_failures, client_ip(request), user.username)
    await alogin(request, user, backend=BACKEND)
    log.info("account %s signed in with a passkey from %s", user.pk, client_ip(request))
    return JsonResponse({"ok": True, "next": back})


async def logout(request: HttpRequest) -> HttpResponse:
    """Sign out. The session row goes first, so the cookie is dead whether or not the browser does
    as it is told with the one below."""
    user = await request.auser()
    if user.is_authenticated:
        log.info("%s signed out from %s", user.username, client_ip(request))
    await alogout(request)
    response = HttpResponseRedirect("/login", status=303)
    response.delete_cookie(OLD_COOKIE, path="/")
    return response
