"""The few things every view here needs, said once.

A view in this package asks who is signed in, reads a JSON body, answers in
JSON, and sometimes has to know whether a caller is this machine itself. Each
of those is one function below, so no view answers any of them its own way.
"""
from __future__ import annotations

import json
import logging
from functools import wraps

from django.http import HttpRequest, HttpResponse, HttpResponseNotAllowed

log = logging.getLogger("rouh.web")


def answer(data, status: int = 200, headers: dict | None = None) -> HttpResponse:
    """JSON, the way every endpoint here has always answered.

    Not Django's JsonResponse: that one refuses anything but a dict unless
    told otherwise and writes non-ASCII as escapes. A list is a perfectly good
    answer (the Ask AI threads are one), and a name with an accent in it should
    reach the page as that name.
    """
    body = json.dumps(data, ensure_ascii=False, default=str, separators=(",", ":"))
    response = HttpResponse(body, status=status, content_type="application/json")
    for name, value in (headers or {}).items():
        response[name] = value
    return response


def refuse(message: str, status: int, **more) -> HttpResponse:
    """The error shape the page reads: ``{"error": "..."}`` and a status."""
    return answer({"error": message, **more}, status=status)


def body_of(request: HttpRequest) -> dict:
    """The JSON object a request carried, or an empty one.

    Anything that is not a JSON object is treated as nothing sent, never as an
    error: every endpoint that takes a body already says what it needs when a
    field is missing.
    """
    try:
        got = json.loads(request.body or b"null")
    except (ValueError, UnicodeDecodeError):
        return {}
    return got if isinstance(got, dict) else {}


def _text(body, key: str, most: int = 4000) -> str:
    value = body.get(key)
    return str(value)[:most] if isinstance(value, (str, int, float)) else ""


def who(request: HttpRequest):
    """Who is asking, with their organisation. `Tenancy.current` answers it.

    The gate has already let the person in and Django has already said who
    they are (`request.user`); this maps that account onto its organisation,
    and it is the only place in the web layer that does.
    """
    from rouh import runtime

    return runtime.tenancy.current(getattr(request, "user", None))


def client_ip(request: HttpRequest) -> str:
    """The address the request really came from.

    nginx is the only way in from outside and it sets X-Real-IP on everything
    it forwards, so that is the address to rate-limit by. A request that did
    not come through it is on this machine, and then the socket's own address
    is the truth.
    """
    forwarded = request.headers.get("x-real-ip") or ""
    if forwarded:
        return forwarded.strip()[:64]
    return (request.META.get("REMOTE_ADDR") or "")[:64]


#: Headers nginx adds to every request it forwards (X-Real-IP, X-Forwarded-For),
#: and the standard one. A request carrying any of them came through a proxy.
PROXIED = ("x-forwarded-for", "x-real-ip", "forwarded")


def public_base(request: HttpRequest) -> str:
    """The address this request came in on, when it is one of Rouh's own names.

    Every one of the installation's public names is Rouh (`config.public_hosts`), and a
    sign-in lives on the name it was made on, so anything that has to come
    back to this browser - Google's way back above all - is sent to the name
    the person is on. The host is Django's, which has already refused any name
    not in ALLOWED_HOSTS, and only a configured public name is used, so a
    caller cannot choose where Google delivers a code. Anything else (this
    machine, a test world on 127.0.0.1) gets the configured public URL.
    """
    from rouh.config import config

    try:
        host = request.get_host()
    except Exception:  # DisallowedHost: never reached past the middleware
        return config.public_url.rstrip("/")
    name = host.rsplit(":", 1)[0] if not host.endswith("]") else host
    if name.lower() in config.public_host_list():
        return f"{request.scheme}://{host.lower()}"
    return config.public_url.rstrip("/")


def from_this_machine(request: HttpRequest) -> bool:
    """True only for a caller on this machine that did not come through a proxy.

    The address has to be there and be loopback: a request that carries no
    client address at all is refused, not waved through. And it must carry none
    of the headers nginx adds to everything it forwards, so even if the proxy
    were one day set up to hide the real address, a request from outside would
    still be refused.

    In the containers the runs are in the worker, another container, and it shows the key Rouh
    made for it instead (`rouh/workerkey.py`), on the same terms: never through a proxy.
    """
    from rouh import workerkey

    local = request.META.get("REMOTE_ADDR") in ("127.0.0.1", "::1") or workerkey.shown(request)
    return local and not any(name in request.headers for name in PROXIED)


def methods(**handlers):
    """One address, a view per method: ``methods(GET=read, POST=write)``.

    Django routes by address and leaves the method to the view; the addresses
    here have always been declared per method, so this keeps them that way. A
    HEAD is answered as a GET would be, and anything not named is a 405.
    """
    if "GET" in handlers and "HEAD" not in handlers:
        handlers["HEAD"] = handlers["GET"]

    async def view(request, *args, **kwargs):
        handler = handlers.get(request.method)
        if handler is None:
            return HttpResponseNotAllowed(sorted(handlers))
        return await handler(request, *args, **kwargs)

    first = next(iter(handlers.values()))
    view.__name__ = getattr(first, "__name__", "view")
    view.__doc__ = getattr(first, "__doc__", None)
    return view


def only(*allowed: str):
    """A single-method view: ``@only("POST")``. HEAD rides along with GET."""
    wanted = set(allowed) | ({"HEAD"} if "GET" in allowed else set())

    def wrap(handler):
        @wraps(handler)
        async def view(request, *args, **kwargs):
            if request.method not in wanted:
                return HttpResponseNotAllowed(sorted(wanted))
            return await handler(request, *args, **kwargs)
        return view
    return wrap


def file_response(path: str, content_type: str, *, chunk: int = 1 << 20):
    """A file off disk, streamed without holding the event loop or all of it.

    Django's own FileResponse reads with a plain file iterator, which under
    ASGI it can only serve by reading the whole file into memory first; a
    speech model or a large attachment is megabytes. This reads it a chunk at
    a time, each read on a thread.
    """
    import asyncio
    import os

    from django.http import StreamingHttpResponse

    async def chunks():
        handle = await asyncio.to_thread(open, path, "rb")
        try:
            while True:
                part = await asyncio.to_thread(handle.read, chunk)
                if not part:
                    break
                yield part
        finally:
            await asyncio.to_thread(handle.close)

    response = StreamingHttpResponse(chunks(), content_type=content_type)
    response["Content-Length"] = str(os.path.getsize(path))
    return response
