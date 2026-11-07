"""The program's two doors: its socket on the server, and its web address.

**The socket** (``/run/one/one.sock``) takes one JSON message per line. Only
root and the program's own user can open it, so whoever does has logged in to
the machine: it is a real keyboard, and what it sends needs no token. Rouh
and the laptop's ``one`` command, through ssh, come in here.

**The web address** is only on this machine; nginx is what faces the
internet, at the installation's public address (``ONE_PUBLIC_URL``). It serves:

``/one/``         the page, to a paired browser
``/one/pair``     where a browser is paired, with a code from a terminal
``/one/ws``       the same messages as the socket, for a paired browser
``/one/drop``     a file dropped on a run's terminal by a paired browser
``/one/q/<t>``    the phone's page for one question: shows it, answers on a button
``/one/hook``     where every run's Claude Code sends its hooks; this machine only
``/one/healthz``  whether the program is up

The web address is a Django application since 23 September 2026 - the same
framework as Rouh beside it - built inside the program's own process
(`make_app`), with Channels for the socket, served by the uvicorn the program
already ran. It has no database, no sessions and no middleware, because it
never had any: a browser is known by the device token in its cookie, a phone
by the token in the question's address, and a hook by coming from this
machine. Each address answers exactly what it answered as a FastAPI route.
"""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import html
import json
import logging
import os
import re
import urllib.parse
from pathlib import Path
from typing import TYPE_CHECKING

import secrets

from . import version
from .devices import hash_token, new_device_id, new_token
from .documents import DocumentsError
from .drops import MOST_BYTES, MOST_FILES, DropRefused
from .protocol import Client
from .runs import RunError

if TYPE_CHECKING:  # pragma: no cover
    from django.http import HttpRequest as Request

if TYPE_CHECKING:  # pragma: no cover
    from .program import Program

log = logging.getLogger("one.web")

STATIC = Path(__file__).resolve().parent / "static"
COOKIE = "one_device"
YEAR = 365 * 24 * 3600

#: Headers every request nginx forwards carries. A hook that has one came from outside.
_PROXIED = ("x-forwarded-for", "x-real-ip", "forwarded")


def _headers(request: Request | None = None) -> dict[str, str]:
    host = request.headers.get("host", "") if request is not None else ""
    connect = "'self'" + (f" wss://{host} ws://{host}" if host else "")
    return {
        "Cache-Control": "no-store",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
        # Scripts only from the program itself. Styles may also be inline,
        # because xterm.js draws a terminal's colours with style elements of
        # its own; a style cannot run anything.
        "Content-Security-Policy": (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            f"img-src 'self' data:; connect-src {connect}; frame-ancestors 'none'; "
            "base-uri 'none'; form-action 'self'"),
    }


_ASSET = re.compile(r'(static/[\w./-]+\.(?:js|css))"')


def came_from(request) -> str:
    """The address a request came from, before nginx and Cloudflare.

    The page asks the program for the command that takes a run over in a real
    terminal, and the answer is different for a browser on this machine and a
    browser anywhere else (D52). `request` is a Django request, or the scope of
    a socket.
    """
    headers = _header_map(request)
    forwarded = headers.get("x-forwarded-for") or headers.get("x-real-ip") or ""
    if forwarded:
        return forwarded.split(",")[0].strip()
    if isinstance(request, dict):
        client = request.get("client") or ("", 0)
        return str(client[0] or "")
    return request.META.get("REMOTE_ADDR", "") or ""


def _header_map(request) -> dict[str, str]:
    """A request's headers, lower-cased, whether it is a request or a socket."""
    if isinstance(request, dict):
        return {k.decode("latin-1").lower(): v.decode("latin-1")
                for k, v in request.get("headers") or []}
    return {k.lower(): v for k, v in request.headers.items()}


def _versioned_index() -> str:
    """The page, with each of its files named by what is in it.

    Cloudflare tells browsers to keep the page's files for four hours,
    whatever the program says. On 15 September a browser kept the day
    before's app.js beside a new page, so the list of spaces never filled.
    Now a file's address changes whenever the file does.
    """
    page = (STATIC / "index.html").read_text(encoding="utf-8")

    def stamp(found: re.Match) -> str:
        try:
            data = (STATIC / found.group(1)[len("static/"):]).read_bytes()
        except OSError:
            return found.group(0)
        return f'{found.group(1)}?v={hashlib.sha256(data).hexdigest()[:10]}"'

    return _ASSET.sub(stamp, page)


def _secure(program: "Program", request) -> bool:
    return (program.settings.public_url.startswith("https")
            and request.headers.get("x-forwarded-proto", "") == "https")


#: The program whose web address this process serves. Set once, by
#: `make_app`, before Django is asked anything; the views read it.
_PROGRAM: "Program | None" = None


def _program() -> "Program":
    assert _PROGRAM is not None, "make_app has not been called"
    return _PROGRAM


def _allowed_hosts(program: "Program") -> list[str]:
    """The names a request may arrive under: this machine, and the public ones.

    Rouh's names, side by side (`ONE_PUBLIC_HOSTS`: two of them on one machine
    since 4 October 2026), the public URL's own, and any in ONE_ALLOWED_HOSTS.
    """
    public = urllib.parse.urlsplit(program.settings.public_url).hostname or ""
    extra = [h.strip() for h in os.environ.get("ONE_ALLOWED_HOSTS", "").split(",")]
    names = [h.strip() for h in program.settings.public_hosts.split(",")]
    return sorted({h.lower() for h in ("127.0.0.1", "localhost", "[::1]", "::1",
                                       public, *names, *extra) if h})


def _configure_django(program: "Program") -> None:
    """Django, for this process: no database, no sessions, no middleware.

    Nothing is signed with the secret key - there are no sessions and no CSRF
    tokens here - so it is made for the process and never kept. The program
    configures its own logging, so Django is told not to.
    """
    from django.conf import settings

    if settings.configured:
        return
    settings.configure(
        DEBUG=False,
        SECRET_KEY="one-" + secrets.token_urlsafe(40),
        ALLOWED_HOSTS=_allowed_hosts(program),
        ROOT_URLCONF="one.urls",
        MIDDLEWARE=[],
        INSTALLED_APPS=[],
        DATABASES={},
        USE_TZ=True,
        USE_I18N=False,
        LOGGING_CONFIG=None,
        # A drop carries up to ten files of 20 MB; files past a few megabytes
        # are spooled to disk while the form is read.
        DATA_UPLOAD_MAX_NUMBER_FILES=MOST_FILES + 1,
    )
    import django

    django.setup()


def _page_response(body: str, status: int = 200, request: "Request | None" = None):
    from django.http import HttpResponse

    response = HttpResponse(body, status=status, content_type="text/html; charset=utf-8")
    for name, value in _headers(request).items():
        response[name] = value
    return response


def _json(data, status: int = 200, headers: dict | None = None):
    from django.http import HttpResponse

    response = HttpResponse(json.dumps(data, default=str), status=status,
                            content_type="application/json")
    for name, value in (headers or {}).items():
        response[name] = value
    return response


def _browser_device(cookies) -> dict | None:
    token = cookies.get(COOKIE)
    if not token:
        return None
    dev = _program().views.device_for_token_hash(hash_token(token))
    return dev if dev and dev.get("surface") == "browser" else None


def _method(request, *allowed: str):
    """None when the method is one of `allowed`, or the 405 to answer."""
    from django.http import HttpResponseNotAllowed

    wanted = set(allowed) | ({"HEAD"} if "GET" in allowed else set())
    return None if request.method in wanted else HttpResponseNotAllowed(sorted(wanted))


# -- the views --------------------------------------------------------------------------


async def healthz(request):
    if (refused := _method(request, "GET")) is not None:
        return refused
    program = _program()
    # `version` is the number a person reads; `commit` is which build of that
    # number is actually serving. Both, because a version repeated across two
    # commits cannot say which of them answered this request.
    return _json({"ok": True, **version.describe(), "n": program.list.last_n,
                  "open_runs": len(program.views.open_runs()), "up_since": program.started_at})


async def bare(request):
    from django.http import HttpResponseRedirect

    return HttpResponseRedirect(_program().settings.base_path + "/", status=307)


async def index(request):
    """The program's own page: every run, full screen.

    Since D47 nginx sends /one/ itself to Rouh's page, which has the runs, the
    voice and the orb, and back here only when Rouh does not answer; /one/runs
    is always this.
    """
    from django.http import HttpResponseRedirect

    if (refused := _method(request, "GET")) is not None:
        return refused
    base = _program().settings.base_path
    if _browser_device(request.COOKIES) is None:
        # Come back to the page that was asked for. The two addresses are not
        # the same page on the server: /one/ is Rouh's page and /one/runs is
        # this one (D47), so a browser that pairs on the way to /one/runs has
        # to land on /one/runs.
        back = _safe_next(request.path)
        tail = "?next=" + urllib.parse.quote(back, safe="/") if back else ""
        return HttpResponseRedirect(base + "/pair" + tail, status=303)
    return _page_response(_versioned_index(), request=request)


async def static(request, name: str):
    from django.http import HttpResponse

    if (refused := _method(request, "GET")) is not None:
        return refused
    path = (STATIC / name).resolve()
    if not str(path).startswith(str(STATIC) + os.sep) or not path.is_file():
        return HttpResponse("Not found.", status=404, content_type="text/plain")
    kind = {".js": "application/javascript; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".html": "text/html; charset=utf-8",
            ".svg": "image/svg+xml", ".png": "image/png",
            ".json": "application/json"}.get(path.suffix, "application/octet-stream")
    response = HttpResponse(await asyncio.to_thread(path.read_bytes), content_type=kind)
    for header, value in {**_headers(request), "Cache-Control": "no-cache"}.items():
        response[header] = value
    return response


# -- pairing a browser --------------------------------------------------------------------


async def pair(request):
    """The pairing page, and the code typed into it."""
    from django.http import HttpResponseRedirect

    if (refused := _method(request, "GET", "POST")) is not None:
        return refused
    program = _program()
    base = program.settings.base_path
    if request.method != "POST":
        back = _safe_next(request.GET.get("next", ""))
        return _page_response(_pair_html(base, back=back), request=request)
    form = request.POST
    back = _safe_next(str(form.get("next") or ""))
    code = program.pairing.redeem(str(form.get("code") or "").strip())
    if code is None:
        why = ("Ten wrong codes were tried. Pairing opens again within ten minutes."
               if program.pairing.closed() else "That code is wrong or has expired.")
        return _page_response(_pair_html(base, error=why, back=back), status=400,
                              request=request)
    name = str(form.get("name") or "").strip()[:40] or code.name
    token = new_token()
    device_id = new_device_id(name)
    program.list.append("device.paired", by=code.by, body={
        "device": device_id, "name": name, "surface": "browser", "token_hash": hash_token(token)})
    response = HttpResponseRedirect(back or base + "/", status=303)
    response.set_cookie(COOKIE, token, max_age=YEAR, path=base + "/", httponly=True,
                        secure=_secure(program, request), samesite="Strict")
    return response


# -- a file dropped on a run's terminal (D52) ----------------------------------------------

# The page posts the file here rather than sending its bytes down the run's own
# terminal: the file is written where the run can read it, and the page is told
# the line to type at the run's prompt, which Claude Code turns into an
# attachment.


async def drop(request):
    if (refused := _method(request, "POST")) is not None:
        return refused
    program = _program()
    no_store = {"Cache-Control": "no-store"}
    dev = _browser_device(request.COOKIES)
    if dev is None:
        return _json({"ok": False, "why": "this browser is not paired with the program"},
                     status=401, headers=no_store)
    # Refused on what it says it is, before it is read onto the disk. A drop
    # of ten 20 MB files, plus what multipart adds around them.
    try:
        size = int(request.headers.get("content-length") or 0)
    except ValueError:
        size = 0
    if size > MOST_FILES * MOST_BYTES + (1 << 20):
        return _json({"ok": False, "why": f"that drop is {size / 1_000_000:.0f} MB, "
                                          "which is more than a drop may carry"},
                     status=413, headers=no_store)
    try:
        files = await asyncio.to_thread(lambda: request.FILES.getlist("file"))
        run_id = str(request.POST.get("run") or "")
        carried = [(str(f.name or ""), str(f.content_type or ""),
                    await asyncio.to_thread(f.read)) for f in files]
        got = await program.runs.keep_drops(run_id, carried, by=dev["id"])
    except (DropRefused, RunError, DocumentsError, ValueError) as exc:
        return _json({"ok": False, "why": str(exc)}, status=400, headers=no_store)
    finally:
        with contextlib.suppress(Exception):
            for f in request.FILES.getlist("file"):
                f.close()
    return _json({"ok": True, **got}, headers=no_store)


# -- the phone's page for one question -------------------------------------------------------


async def question(request, token: str):
    if (refused := _method(request, "GET", "POST")) is not None:
        return refused
    program = _program()
    base = program.settings.base_path
    if request.method != "POST":
        q = program.questions.for_phone(token)
        return _page_response(_question_html(base, token, q, suggested=request.GET.get("a", "")),
                              request=request)
    answer = str(request.POST.get("answer") or "")
    ok = program.questions.answer_by_phone(token, answer)
    return _page_response(_answered_html(base, answer if ok else None),
                          status=200 if ok else 409, request=request)


# -- the runs' hooks -------------------------------------------------------------------------


async def hook(request):
    if (refused := _method(request, "POST")) is not None:
        return refused
    local = request.META.get("REMOTE_ADDR") in ("127.0.0.1", "::1")
    if not local or any(name in request.headers for name in _PROXIED):
        return _json({}, status=403)
    try:
        payload = json.loads(request.body or b"null")
    except (ValueError, UnicodeDecodeError):
        payload = {}
    q = request.GET
    answer = await _program().runs.on_hook(q.get("run", ""), q.get("key", ""), q.get("kind", ""),
                                           payload if isinstance(payload, dict) else {})
    # The connection closes with the answer. Claude Code reuses a hook's
    # connection for the next hook, and the web server drops an idle one after
    # a few seconds: on 14 September two hooks sent 5.0 and 5.2 seconds after
    # the one before went to a connection being closed, and were lost ("socket
    # hang up"), one of them the end of a turn.
    return _json(answer or {}, headers={"Connection": "close"})


def urlpatterns_for(base: str) -> list:
    """Every address, under the path the program is served at."""
    from django.urls import path, re_path

    prefix = base.strip("/")
    at = (prefix + "/") if prefix else ""
    patterns = [
        path(at + "healthz", healthz),
        path(at, index),
        path(at + "runs", index),
        re_path(r"^" + re.escape(at) + r"static/(?P<name>.+)$", static),
        path(at + "pair", pair),
        path(at + "drop", drop),
        path(at + "q/<str:token>", question),
        path(at + "hook", hook),
    ]
    if prefix:
        # The bare base, `/one`, sends a browser to `/one/`.
        patterns.insert(0, path(prefix, bare))
    return patterns


class _Socket:
    """The browser's connection: the same messages as the program's socket."""

    @staticmethod
    def consumer():
        from channels.generic.websocket import AsyncWebsocketConsumer
        from django.http.cookie import parse_cookie

        class OneSocket(AsyncWebsocketConsumer):
            client = None

            async def connect(self) -> None:
                program = _program()
                cookies = parse_cookie(_header_map(self.scope).get("cookie", ""))
                dev = _browser_device(cookies)
                if dev is None:
                    # Accepted first, so the browser is told why. Closed before
                    # it is accepted, a socket reaches the browser as a refused
                    # handshake with no reason, and Rouh's page could not tell
                    # "not paired" from "the program is down" (D45).
                    await self.accept()
                    await self.close(code=4401)
                    return
                await self.accept()

                async def send(message: dict) -> None:
                    await self.send(text_data=json.dumps(message, default=str))

                self.client = Client(program, send, local=False, device=dev,
                                     at=came_from(self.scope))
                program.clients.add(self.client)

            async def receive(self, text_data=None, bytes_data=None) -> None:
                if self.client is None or text_data is None:
                    return
                try:
                    message = json.loads(text_data)
                except ValueError:
                    return
                if isinstance(message, dict):
                    await self.client.handle(message)

            async def disconnect(self, code) -> None:
                client, self.client = self.client, None
                if client is not None:
                    await client.close()

        class Elsewhere(AsyncWebsocketConsumer):
            async def connect(self) -> None:
                await self.close()

        return OneSocket, Elsewhere


def make_app(program: "Program"):
    """The program's web address, as a Django application for uvicorn to serve."""
    global _PROGRAM
    _PROGRAM = program
    _configure_django(program)

    from channels.routing import ProtocolTypeRouter, URLRouter
    from django.core.asgi import get_asgi_application
    from django.urls import path, re_path

    from . import urls

    base = program.settings.base_path
    urls.urlpatterns = urlpatterns_for(base)
    prefix = base.strip("/")
    one_socket, elsewhere = _Socket.consumer()
    return ProtocolTypeRouter({
        "http": get_asgi_application(),
        "websocket": URLRouter([
            path((prefix + "/ws") if prefix else "ws", one_socket.as_asgi()),
            re_path(r"", elsewhere.as_asgi()),
        ]),
    })


class SocketServer:
    """The socket, and every connection open on it, so all of them can be closed at once.

    Python 3.12's ``wait_closed`` waits for every connection a server is
    still handling, so a program that only closed the server would wait for
    ever on a terminal that is still attached.
    """

    def __init__(self, server: asyncio.AbstractServer, writers: set) -> None:
        self.server = server
        self.writers = writers

    def close(self) -> None:
        self.server.close()
        for writer in list(self.writers):
            with contextlib.suppress(Exception):
                writer.close()

    async def wait_closed(self) -> None:
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(self.server.wait_closed(), 5)


async def serve_socket(program: "Program", path: str) -> SocketServer:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(FileNotFoundError):
        os.unlink(path)
    writers: set = set()

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writers.add(writer)
        async def send(message: dict) -> None:
            writer.write((json.dumps(message, default=str) + "\n").encode("utf-8"))
            await writer.drain()

        client = Client(program, send, local=True)
        program.clients.add(client)
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                try:
                    message = json.loads(line)
                except ValueError:
                    continue
                if isinstance(message, dict):
                    await client.handle(message)
        except (ConnectionResetError, asyncio.IncompleteReadError, BrokenPipeError):
            pass
        finally:
            writers.discard(writer)
            await client.close()
            with contextlib.suppress(Exception):
                writer.close()

    old = os.umask(0o177)
    try:
        server = await asyncio.start_unix_server(handle, path=path, limit=8 * 1024 * 1024)
    finally:
        os.umask(old)
    return SocketServer(server, writers)


# ---------------------------------------------------------------------------
# The three small pages that are not the app
# ---------------------------------------------------------------------------

def _page(title: str, body: str, base: str) -> str:
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<link rel="icon" href="data:,">
<link rel="stylesheet" href="{base}/static/small.css">
</head><body><main class="small">{body}</main></body></html>"""


def _safe_next(value: str) -> str:
    """A page on this same site to go back to once paired, or nothing.

    Rouh's page sends a browser here to be paired and wants it back (D45).
    Only a path on this site is followed, never another site's address,
    however it is written.
    """
    value = (value or "").strip()
    if (not value.startswith("/") or value.startswith("//") or "\\" in value
            or len(value) > 200 or any(ord(c) < 33 for c in value)):
        return ""
    return value


def _pair_html(base: str, error: str = "", back: str = "") -> str:
    err = f'<p class="error" role="alert">{html.escape(error)}</p>' if error else ""
    keep = f'\n  <input type="hidden" name="next" value="{html.escape(back)}">' if back else ""
    return _page("Pair this browser", f"""
<h1>Pair this browser</h1>
<p>On a terminal that is already paired, run <code>one pair browser</code>.
It prints a six-digit code that works once, for ten minutes.</p>
{err}
<form method="post" action="{base}/pair">{keep}
  <label>Code <input name="code" inputmode="numeric" autocomplete="one-time-code"
         pattern="[0-9]{{6}}" maxlength="6" required autofocus></label>
  <label>Name for this browser <input name="name" maxlength="40" placeholder="My phone"></label>
  <button type="submit">Pair</button>
</form>""", base)


def _question_html(base: str, token: str, q: dict | None, *, suggested: str = "") -> str:
    if q is None:
        return _page("Question closed", """
<h1>This question is closed</h1>
<p>It was answered somewhere else, it timed out, or its run ended. Nothing more to do.</p>""", base)
    lead = {"yes": "You tapped Allow. Confirm below.",
            "no": "You tapped Deny. Confirm below."}.get(suggested, "")
    detail = f'<pre class="detail">{html.escape(q.get("detail") or "")}</pre>' if q.get("detail") else ""
    return _page("A run is waiting for you", f"""
<h1>A run is waiting for you</h1>
<p class="question">{html.escape(q["text"])}</p>
{detail}
<p class="hint">{html.escape(lead)}</p>
<form method="post" action="{base}/q/{html.escape(token)}" class="answers">
  <button name="answer" value="yes" class="{'suggested' if suggested == 'yes' else ''}">Allow</button>
  <button name="answer" value="no" class="{'suggested' if suggested == 'no' else ''}">Deny</button>
</form>""", base)


def _answered_html(base: str, answer: str | None) -> str:
    if answer is None:
        return _page("Question closed", """
<h1>This question is closed</h1>
<p>It was answered somewhere else, it timed out, or its run ended. Nothing was changed.</p>""", base)
    said = "Allowed" if answer == "yes" else "Denied"
    return _page(said, f"""
<h1>{said}</h1>
<p>The run has been told. You can close this page.</p>""", base)
