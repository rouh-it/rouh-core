"""The one program's pages and socket, through Rouh, where no nginx stands in front of the two.

On the server nginx sends `/one/...` and `/one/ws` to the one program on port 8031 (deploy/
nginx-rouh.conf.example), and the person pairs each browser with it once, with a code. In the
containers every Rouh instance runs (deploy/stack/compose.yml) there is no nginx: the page is
the core's, published on one port, and the one program is in the worker, which nothing outside
reaches. So until 29 October 2026 the run screen, the run terminals and a run's question on the
phone could not be opened there at all (CONTAINERS.md, `one.run-screen`, `one.terminal`,
`one.phone-question`).

Here the core passes them on itself, to `ROUH_ONE_HTTP` (http://worker:8031 in the stack):

- only for somebody signed in to Rouh who is not a guest (the gate, `web/gate.py`, keeps guests
  out of everything but their pages), except `/one/q/<token>`, a run's one question, which its
  own unguessable address opens on the phone, as nginx lets it;
- with the browser device the worker paired for Rouh's page at its start (`ROUH_ONE_BROWSER`,
  /run/one/browser.json): the person's own cookies never go to the worker, which is where other
  people's code runs, and the one program's own cookie never comes back to the browser, so the
  person is not asked to pair: their sign-in to Rouh is what lets them in;
- never `/one/hook`, which is the runs' own, on the worker's loopback (nginx refuses it too).

Where `ROUH_ONE_HTTP` is not set (the server, behind nginx) none of this is reached: nginx
answers those addresses before Rouh sees them, and Rouh answers 404 as before.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os

from django.http import HttpResponse, StreamingHttpResponse

log = logging.getLogger(__name__)

ONE_HTTP = os.environ.get("ROUH_ONE_HTTP", "").strip().rstrip("/")
BROWSER_FILE = os.environ.get("ROUH_ONE_BROWSER", "/run/one/browser.json")
COOKIE = "one_device"
#: Headers that belong to one hop, or to the person's own sign-in to Rouh, never passed on.
HOP = {"connection", "keep-alive", "proxy-connection", "proxy-authorization", "te", "trailer",
       "transfer-encoding", "upgrade", "cookie", "host", "content-length", "x-forwarded-for",
       "x-forwarded-proto", "x-real-ip", "forwarded"}
BACK_HOP = {"connection", "keep-alive", "transfer-encoding", "set-cookie", "content-length", "server", "date"}
#: Paths of the one program a phone opens with nothing but its own address.
OPEN = ("/one/q/",)


def on() -> bool:
    return bool(ONE_HTTP)


def device_token() -> str:
    try:
        with open(BROWSER_FILE, encoding="utf-8") as fh:
            return str(json.load(fh).get("token") or "")
    except (OSError, ValueError, AttributeError):
        return ""


def allowed(path: str, user) -> bool:
    if path == "/one/hook" or not path.startswith("/one/"):
        return False
    if path.startswith(OPEN):
        return True
    return bool(getattr(user, "is_authenticated", False)) and not getattr(user, "is_guest", False)


def _forwarded(host: str, scheme: str, client: str, path: str) -> dict:
    headers = {"Host": host, "X-Forwarded-Proto": scheme, "X-Forwarded-For": client or "unknown"}
    token = device_token()
    if token and not path.startswith(OPEN):
        headers["Cookie"] = f"{COOKIE}={token}"
    return headers


async def http(request, rest: str = ""):
    """`/one/...`, passed to the one program and its answer streamed back."""
    import httpx

    path = request.path
    if not on() or not allowed(path, request.user):
        return HttpResponse(status=404)
    headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP}
    headers.update(_forwarded(request.get_host(), request.scheme, request.META.get("REMOTE_ADDR", ""), path))
    url = ONE_HTTP + path + (f"?{request.META['QUERY_STRING']}" if request.META.get("QUERY_STRING") else "")
    body = await asyncio.to_thread(request.read) if request.method in ("POST", "PUT", "PATCH") else None
    client = httpx.AsyncClient(timeout=httpx.Timeout(3600, connect=10), follow_redirects=False, trust_env=False)
    try:
        upstream = await client.send(client.build_request(request.method, url, headers=headers, content=body), stream=True)
    except httpx.HTTPError as exc:
        await client.aclose()
        log.warning("the one program did not answer %s: %s", path, exc)
        return HttpResponse("The one program is not answering yet.", status=502, content_type="text/plain")

    async def chunks():
        try:
            async for piece in upstream.aiter_raw():
                yield piece
        finally:
            await upstream.aclose()
            await client.aclose()

    response = StreamingHttpResponse(chunks(), status=upstream.status_code)
    for name, value in upstream.headers.multi_items():
        if name.lower() not in BACK_HOP:
            response[name] = value
    return response


class Socket:
    """`/one/ws`, relayed both ways, frame for frame, with the close code passed back (4401 is
    the program saying it does not know this browser). A raw ASGI app, inside the socket's
    origin check and sign-in (`project/asgi.py`)."""

    def __init__(self, scope):
        self.scope = scope

    @classmethod
    def as_asgi(cls):
        async def app(scope, receive, send):
            return await cls(scope).run(receive, send)
        return app

    async def run(self, receive, send):
        import websockets

        first = await receive()
        if first.get("type") != "websocket.connect":
            return
        path = self.scope.get("path", "")
        if not on() or not allowed(path, self.scope.get("user")):
            await send({"type": "websocket.close", "code": 4403})
            return
        headers = dict((k.decode("latin-1").lower(), v.decode("latin-1")) for k, v in self.scope.get("headers") or [])
        client = (self.scope.get("client") or ["", 0])[0]
        scheme = "https" if headers.get("x-forwarded-proto") == "https" or self.scope.get("scheme") == "wss" else "http"
        # The Host websockets writes is the worker's own (ONE_ALLOWED_HOSTS lets it in); the rest
        # say who is at the other end, as nginx does.
        extra = {k: v for k, v in _forwarded(headers.get("host", ""), scheme, client, path).items() if k != "Host"}
        url = ONE_HTTP.replace("http", "ws", 1) + path + (
            "?" + self.scope["query_string"].decode() if self.scope.get("query_string") else "")
        try:
            # The core has no proxy in its environment, so this goes straight to the worker.
            upstream = await websockets.connect(url, additional_headers=extra, open_timeout=15,
                                                max_size=32 * 1024 * 1024)
        except Exception as exc:  # noqa: BLE001 - the program down is one plain close
            log.warning("the one program's socket did not open: %s: %s", type(exc).__name__, exc)
            await send({"type": "websocket.close", "code": 1011})
            return
        await send({"type": "websocket.accept"})

        async def down():
            try:
                async for frame in upstream:
                    if isinstance(frame, bytes):
                        await send({"type": "websocket.send", "bytes": frame})
                    else:
                        await send({"type": "websocket.send", "text": frame})
            except websockets.ConnectionClosed:
                pass
            code = upstream.close_code or 1000
            with contextlib.suppress(Exception):
                await send({"type": "websocket.close", "code": code if code != 1005 else 1000})

        task = asyncio.create_task(down())
        try:
            while True:
                m = await receive()
                if m["type"] == "websocket.receive":
                    if m.get("text") is not None:
                        await upstream.send(m["text"])
                    elif m.get("bytes") is not None:
                        await upstream.send(m["bytes"])
                elif m["type"] == "websocket.disconnect":
                    break
        except websockets.ConnectionClosed:
            pass
        finally:
            with contextlib.suppress(Exception):
                await upstream.close()
            task.cancel()
