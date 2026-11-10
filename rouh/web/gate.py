"""The gate: every address answers only to a signed-in person, with a short
list of exceptions that is written down here and nowhere else.

This process can read mail-shaped things, spend money on tokens and start jobs
on a server; it does not get to be open to anyone who finds the hostname. So
one thing decides for every address this server answers on, and it is this
middleware. A view that forgets to check is not a hole, because a view never
checks - it is already past the gate by the time it runs, and `request.user`
says who it is. The websocket has the same gate in front of it
(`rouh/web/consumers.py`), reading the same Django session.

What it replaced (until 23 September 2026) was an ASGI class in front of
FastAPI that read Rouh's own cookie; the addresses it lets through, and what
it answers everybody else, are unchanged.
"""
from __future__ import annotations

import logging
import time
from urllib.parse import quote

from asgiref.sync import iscoroutinefunction, markcoroutinefunction, sync_to_async
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect

from rouh import accounts, dbwork, filelinks, pages, picturelinks, sharing

from .common import answer, client_ip

log = logging.getLogger("rouh.gate")

#: Addresses that answer without a sign-in, and nothing else does.
#:
#: - the sign-in page and the form it posts to, or nobody could ever get in,
#:   and the start of signing in with Google, for the same reason;
#: - asking for a new password, and the link that answers it with the form it
#:   leads to (`/login/reset/<uid>/...`), because they are for somebody who
#:   cannot sign in. The link is the credential there, a signed token that
#:   works once, within the hour, for one account (`rouh/password_reset.py`);
#: - Google coming back from a consent screen. The view itself decides: a
#:   sign-in with Google has nobody signed in yet, and connecting a Google
#:   account is refused there unless somebody is (`rouh/web/google.py`);
#: - signing out, which is about ending a cookie and cannot need a live one;
#: - the health check, which systemd, the deploy and the rollback all read
#:   before anybody has signed in to anything;
#: - the front-end files. They are the same bytes for everyone and carry
#:   nothing of the person's; the page they belong to is behind the gate.
#: - a page the person deliberately made public, and only such a page. This is
#:   the one prefix here that carries something of theirs, and it is the whole
#:   reason the token in the address is 32 random characters rather than a
#:   number: the token **is** the credential (`sharing.py`). One route lives
#:   under it, it serves one page per token, and there is no listing at this
#:   end - nothing under `/p/` can be walked, guessed or enumerated.
#: - the address Google's Pub/Sub posts a note to when a watched inbox
#:   changes (`/hooks/gmail/<token>`). Google has no sign-in to give, so the
#:   token in the address is the credential, the way a public page's is, and
#:   the most a note can do is make Rouh look at that inbox for new mail
#:   (`rouh/mail_alerts.py`).
#: - the address Stripe posts its events to (`/hooks/stripe/<token>`). The
#:   token picks whose webhook it is, and nothing in an event is read until
#:   its signature is checked against that webhook's own signing secret
#:   (`payments.verify`): an event nobody signed is refused.
#: - the address the meeting library posts "a meeting changed" to
#:   (`/api/hooks/meeting-library`). The library has no sign-in to give: the
#:   HMAC of the raw body with the library's webhook secret is the credential,
#:   checked with a timestamp and a list of signatures already taken, and a
#:   message that fails any of them is refused with 401. All one that passes
#:   can do is make Rouh read that meeting again from the library itself
#:   (`rouh/synapse/meetings.py`).
#:
#: - an invitation to a page shared by email (`/join/<token>`), which is for
#:   somebody who has no account yet: the token in the address is the
#:   credential, and all it can do is make an account for the one address it
#:   was sent to (`rouh/web/guests.py`).
#: - a download link beside one of a task's files (`/files/<token>/<name>`),
#:   because it is pressed inside the task frame, which sends no sign-in. The
#:   token in the address is the credential: signed by this server, for one
#:   account and one file, for half a day, and checked again against the
#:   account and the file when it is used (`rouh/filelinks.py`).
#: - a picture of a page on the canvas (`/pictures/<token>/<path>`), fetched by
#:   the sandboxed frame, which sends no sign-in. The token is the credential:
#:   signed by this server, for one account and one task's pictures, for the
#:   day, and checked again against the account and the file when it is used
#:   (`rouh/picturelinks.py`).
#: - Django's list of common passwords (`/login/common-passwords`), which the
#:   invitation's form and the new-password form tick a rule off against as a
#:   password is typed. It is the same for everybody and public already.
#:
#: - Let's Encrypt's HTTP-01 check (`/.well-known/acme-challenge/<token>`), which comes
#:   through the relay's port 80 with no sign-in to give; it answers only the token a
#:   certificate order of this Rouh's is waiting on, and 404 to anything else
#:   (`rouh/relay.py`).
#: - the link in the QR code that signs the owner in on their phone (`/phone/in`): the
#:   code in it is the credential, made for one account by its owner signed in on the
#:   computer, good once and for ten minutes (`relay.signin_link`).
#:
#: A request that came in through the relay never reaches the first-run pages and their
#: setup code, or the internal addresses, whatever else it carries: they answer it 404
#: (`relay.local_only`), the setup page stays on the computer it runs on.
#:
#: `/internal/` is not on this list because it is not open: its endpoints are
#: for Claude Code's hooks and for the notes a job queues for the person
#: (`rouh/outbox.py`), all from this machine, and are held to
#: `from_this_machine`, which is stricter than a sign-in, not looser.
#: An address that answers to a key rather than a sign-in, and checks the key itself:
#: `/api/task`, where `workspace/bin/task` on Petar's laptop changes a task's status or
#: summary (`rouh/web/taskapi.py`). A request there with no live key is refused by the view.
TOKEN_PATHS = frozenset({"/api/task"})

OPEN_PATHS = frozenset({"/login", "/setup", "/setup/connect", "/setup/you", "/phone/in", "/login/forgot",
                        "/login/help", "/login/passkey/options", "/login/passkey/verify", "/logout", "/healthz",
                        "/favicon.ico", "/auth/google/callback", "/login/common-passwords",
                        "/api/hooks/meeting-library",
                        # The service worker: the same script for everybody, holding nothing of
                        # anybody's, checked by the browser for an update signed in or not.
                        "/sw.js"})
OPEN_PREFIXES = ("/a/", "/static/", "/internal/", "/login/reset/", "/login/link/", "/hooks/gmail/", "/.well-known/acme-challenge/",
                 "/hooks/stripe/",
                 # A run's one question, opened on the phone by its own unguessable address, where
                 # Rouh passes the one program's pages on (`rouh/onebridge.py`, which lets nothing
                 # else of the program's through without a sign-in).
                 "/one/q/",
                 # Rouh for Mac's native first run (`rouh/web/setup_api.py`): every call there
                 # checks the setup code itself, and the relay never lets one through.
                 "/setup/api/",
                 sharing.ROUTE, "/join/", filelinks.ROUTE, picturelinks.ROUTE)

#: Where a guest may go, past the addresses open to everybody. A guest is an
#: account made from an invitation to one shared page, and what it may reach
#: is the pages shared with that address and signing out (`rouh/web/guests.py`):
#: not Rouh, not the socket, not a setting, not anybody's workspace.
GUEST_PATHS = frozenset({"/shared", "/logout"})
GUEST_PREFIXES = ("/shared/",)


def _plain_through_relay(request: HttpRequest) -> str:
    """The https address to send a plain http request through the relay's port 80 to, or "":
    that port is only for Let's Encrypt's check."""
    from rouh import relay

    if request.is_secure() or request.path.startswith(relay.CHALLENGE_PATH) or not relay.through(request):
        return ""
    asked = (request.headers.get("host") or "").split(":")[0].strip().lower()
    held = relay.read()
    base = relay.address(held)
    if base and asked in relay.hostnames(held) and asked != held.get("hostname"):
        # The owner's own name (step 140-13): sent on to https on the same name.
        base = base.replace(f"//{held.get('hostname')}", f"//{asked}", 1)
    return base + request.get_full_path() if base else ""


def _local_only_from_outside(request: HttpRequest) -> bool:
    from rouh import relay

    return relay.local_only(request.path) and relay.through(request)


def a_guest_may(path: str) -> bool:
    return path in GUEST_PATHS or path.startswith(GUEST_PREFIXES)


def open_to_everyone(path: str) -> bool:
    return path in OPEN_PATHS or path.startswith(OPEN_PREFIXES)


def next_page(value: str | None) -> str:
    """Where to go once signed in: a plain path on this site, or the start.

    Anything that could leave this site is thrown away rather than repaired, so
    a sign-in link cannot be made to land the person on somebody else's page.
    """
    value = (value or "").strip()
    if (len(value) > 200 or not value.startswith("/") or value.startswith("//")
            or not all(c.isalnum() or c in "/_.-?=&" for c in value)):
        return "/"
    return value


def wants_json(request: HttpRequest) -> bool:
    """Would a refusal here be read by a script rather than shown to a person?

    A page the person typed the address of, or clicked a link to, should end up
    looking at the sign-in form. Everything else - the canvas asking for its
    cards, the paperclip uploading a file, a picture in the transcript - is a
    fetch whose caller wants to be told in JSON what went wrong, not handed a
    page of HTML it will try to parse as an answer.
    """
    if request.method != "GET":
        return True
    if request.path.startswith("/api/"):
        return True
    if request.headers.get("sec-fetch-mode") not in (None, "navigate"):
        return True
    return "text/html" not in (request.headers.get("accept") or "")


def sign_in_first(request: HttpRequest) -> HttpResponse:
    """What an unsigned-in caller gets back."""
    if request.path.startswith(pages.ROUTE):
        # A workspace page is not answered with Rouh's sign-in form, because
        # what asked for it is almost always a sandboxed frame that took itself
        # somewhere, and it carries no sign-in by design. `pages.signed_out_page`
        # hands its own address back to Rouh's page, which is signed in,
        # fetches it and puts it back, so the frame still lands where it meant
        # to. Anything that is not a browser gets the four words.
        if "text/html" in (request.headers.get("accept") or ""):
            response = HttpResponse(pages.signed_out_page(), status=401,
                                    content_type=pages.TYPES[".html"])
        else:
            response = HttpResponse(pages.SIGNED_OUT, status=401, content_type="text/plain")
        for name, value in pages.HEADERS.items():
            response[name] = value
        return response
    if wants_json(request):
        return answer({"error": "Sign in to Rouh first.", "sign_in": "/login"}, status=401)
    where = request.get_full_path()
    back = next_page(where)
    # The whole address, query and all, escaped so that its own "?" and "="
    # cannot be read as more of /login's query string and quietly drop the part
    # of the address that says which page the person asked for.
    return HttpResponseRedirect(
        "/login" + (f"?next={quote(back, safe='/')}" if back != "/" else ""), status=303)


def guest_refused(request: HttpRequest) -> HttpResponse:
    """What a guest gets anywhere but the pages shared with them.

    A page they typed the address of is the list of what was shared with them,
    which is the whole of what their account is for. Anything a script asked
    for is a refusal in words.
    """
    if wants_json(request):
        return answer({"error": "This account can open the pages shared with it, and "
                                "nothing else."}, status=403)
    return HttpResponseRedirect("/shared", status=303)


def database_busy(request: HttpRequest, exc: BaseException) -> HttpResponse:
    """What a request gets when no database connection was free in time: 503 and when to try
    again, which the page's own readers wait for, instead of a 500 (`rouh/dbwork.py`)."""
    log.warning("%s %s: the database is busy (%s)", request.method, request.path, exc)
    if request.path.startswith("/api/"):
        response = answer({"error": "Rouh is busy for a moment. Try again."}, status=503)
    else:
        response = HttpResponse("Rouh is busy for a moment. Try again.", status=503,
                                content_type="text/plain; charset=utf-8")
    response["Retry-After"] = "2"
    return response


class SignInRequired:
    """The gate, in front of every view.

    Async, because nearly every view here is: a middleware that could only run
    in a thread would hand every request to a thread and back for nothing.
    """

    sync_capable = False
    async_capable = True

    def __init__(self, get_response):
        self.get_response = get_response
        if iscoroutinefunction(self.get_response):
            markcoroutinefunction(self)

    async def __call__(self, request: HttpRequest):
        to_https = _plain_through_relay(request)
        if to_https:
            return HttpResponseRedirect(to_https, status=301)
        if _local_only_from_outside(request):
            log.warning("%s %s through the relay, refused: it is for this computer only", request.method, request.path)
            return HttpResponse("Not found", status=404, content_type="text/plain")
        if open_to_everyone(request.path):
            return await self.get_response(request)
        if request.path in TOKEN_PATHS and (request.headers.get("authorization") or "") \
                .lower().startswith("bearer "):
            return await self.get_response(request)
        try:
            user = await request.auser()
        except Exception as exc:
            if dbwork.busy(exc):
                return database_busy(request, exc)
            raise
        # The sign-in was read on this request's own thread; its connection goes
        # back now rather than when the response ends, which for a stream such as
        # Ask AI's answer is minutes later (`rouh/dbwork.py`).
        await sync_to_async(dbwork.release)()
        if not user.is_authenticated:
            log.info("%s %s without a sign-in", request.method, request.path)
            return sign_in_first(request)
        request.user = user
        self._renew(request)
        if getattr(user, "is_guest", False) and not a_guest_may(request.path):
            return guest_refused(request)
        return await self.get_response(request)

    def process_exception(self, request: HttpRequest, exception: Exception):
        """A view that could not get a database connection in time answers 503, not 500."""
        if dbwork.busy(exception):
            return database_busy(request, exception)
        return None

    @staticmethod
    def _renew(request: HttpRequest) -> None:
        """Push the end of a sign-in back, once a day, while it is being used.

        Somebody who uses Rouh every day is never signed out; a browser left
        somewhere stops working thirty days after it was last used. Once a day
        rather than on every request, because renewing writes the session row
        and sends the cookie again, and a page asks for a great many things.
        """
        session = request.session
        now = time.time()
        last = session.get("renewed_at") or 0
        if now - float(last) >= accounts.RENEW_AFTER:
            session["renewed_at"] = now          # marks it modified: saved, cookie re-sent


class SecureCookiesWhenHttps:
    """Mark every cookie Secure when the browser came over https, and only then.

    The site is https everywhere a browser reaches it, through nginx. What
    reaches Rouh over plain http is this machine: the hooks, the health check,
    a laptop, the browser environment. A cookie marked Secure on plain http is
    a cookie the browser throws away, which is a sign-in that never sticks, so
    the flag follows the request rather than being set for everybody.
    """

    sync_capable = True
    async_capable = True

    def __init__(self, get_response):
        self.get_response = get_response
        self._async = iscoroutinefunction(self.get_response)
        if self._async:
            markcoroutinefunction(self)

    def __call__(self, request):
        if self._async:
            return self._acall(request)
        return self._mark(request, self.get_response(request))

    async def _acall(self, request):
        return self._mark(request, await self.get_response(request))

    @staticmethod
    def _mark(request, response):
        if request.is_secure():
            for morsel in response.cookies.values():
                morsel["secure"] = True
        return response


def unknown_address(request: HttpRequest) -> str:
    """The name a write was posted from when this Rouh was never told it, such as a tunnel's
    (maria.example.test through Cloudflare to 127.0.0.1:8420); "" otherwise. A reload cannot
    help that, so the refusal says what can: ROUH_PUBLIC_HOSTS in the settings file."""
    from urllib.parse import urlsplit

    from django.conf import settings
    from django.utils.http import is_same_domain

    origin = request.headers.get("Origin", "")
    name = (urlsplit(origin).hostname or "").lower() if origin and origin != "null" else ""
    if not name or any(is_same_domain(name, host) for host in settings.ALLOWED_HOSTS):
        return ""
    return name


def csrf_failure(request: HttpRequest, reason: str = "") -> HttpResponse:
    """A write without the page's token. Said in JSON to a script, plainly to a person."""
    log.warning("refused a %s to %s from %s: %s", request.method, request.path,
                client_ip(request), reason)
    name = unknown_address(request)
    said = (f"This Rouh has not been told it is reached at {name}, so it refused that. "
            f"Add ROUH_PUBLIC_HOSTS={name} to its settings file, or open it on its own machine."
            if name else "")
    if request.headers.get("sec-fetch-mode") == "navigate" and not request.path.startswith("/api/"):
        # A form a person sent, such as the first run's: a page, not JSON.
        from django.shortcuts import render

        return render(request, "rouh/refused.html", {
            "said": said or "That did not come from Rouh's own page, so it was refused. "
                            "Go back, reload the page and try again.",
            "back": request.path,
        }, status=403)
    if wants_json(request):
        return answer({"error": said or "That request did not come from Rouh's own page, so it "
                                        "was refused. Reload the page and try again."}, status=403)
    return HttpResponse(said or "That did not come from Rouh's own page, so it was refused. "
                                "Go back, reload the page and try again.",
                        status=403, content_type="text/plain; charset=utf-8")
