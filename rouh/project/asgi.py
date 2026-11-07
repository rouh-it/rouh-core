"""The ASGI application uvicorn serves: Django for HTTP, Channels for the
websocket, and the process's own start and stop around both.

`rouh/server.py` hands this to uvicorn as ``rouh.server:app``, which is the
name systemd's `run-server.sh` has always started, so the service, the unit
and the deploy did not have to change for Rouh to become a Django project.

Three things happen here that are worth saying out loud.

**The lifespan.** Rouh is not a web server that answers and forgets: it holds
the voice, the task list's feeds, the background workers and the one program's
socket open for as long as it runs. `rouh.runtime.startup` opens them and
`rouh.runtime.shutdown` closes them, and neither Django nor Channels has a
place for that, so the ASGI lifespan messages are answered here. A start that
fails says so to uvicorn, which exits; systemd starts it again, and a deploy
that never comes up healthy is rolled back (`deploy/rouh.sh`). Nothing is
imported from `rouh.runtime` until then, so importing this module - which is
what the deploy's import check does - needs neither the database nor anything
else running.

**The database from the event loop.** Rouh's stores are called straight from
async code, as they always were when they were SQLite: each call is one short
query on this machine, none awaits anything in the middle of a transaction,
and the slow ones are handed to a thread. Django refuses that by default, to
protect code that would hold a transaction open across an await. None here
does, so it is allowed for this process with ``DJANGO_ALLOW_ASYNC_UNSAFE``.

**Who may open the socket.** The same session cookie as the page, read by
Channels' own `AuthMiddlewareStack`, and never from a page on another site:
a browser always says which page opened a socket (the Origin header), and one
that names anything but this site's own names is refused (`_SameSiteOnly`),
so another site cannot open a socket to Rouh in a visitor's browser. A
client that is not a browser sends no Origin at all - the scripted
conversations in `rouh/testing/session.py`, `verify.py` - and still has to
carry a signed-in session cookie to get anywhere.
"""
from __future__ import annotations

import contextlib
import logging
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "rouh.project.settings")
os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")

import django  # noqa: E402

django.setup()

# A reset link's token never reaches the log, which other users on the machine
# can read (`rouh/password_reset.py`): not uvicorn's line for every request,
# and not Django's for one that went wrong.
from rouh.mail_alerts import HidePushTokens  # noqa: E402
from rouh.password_reset import HideResetTokens  # noqa: E402

# And neither does the token in the address Google posts new mail to
# (`rouh/mail_alerts.py`), which is the only thing that opens it.
for _name in ("uvicorn.access", "django.request"):
    logging.getLogger(_name).addFilter(HideResetTokens())
    logging.getLogger(_name).addFilter(HidePushTokens())

# Settings are read now and never again, so the name is taken back out of this
# process's environment: every job Rouh starts inherits it, and a worker
# running some other Django project would otherwise quietly load Rouh's
# settings instead of its own. (DJANGO_ALLOW_ASYNC_UNSAFE has to stay: Django
# reads it on every call it guards.)
if os.environ.get("DJANGO_SETTINGS_MODULE") == "rouh.project.settings":
    del os.environ["DJANGO_SETTINGS_MODULE"]

from channels.auth import AuthMiddlewareStack  # noqa: E402
from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402
from channels.security.websocket import OriginValidator  # noqa: E402
from django.conf import settings  # noqa: E402
from django.core.asgi import get_asgi_application  # noqa: E402
from django.urls import path, re_path  # noqa: E402

from rouh import onebridge  # noqa: E402
from rouh.onebridge import Socket as OneSocket  # noqa: E402
from rouh.web.consumers import NoSuchSocket, RouhSocket  # noqa: E402

log = logging.getLogger("rouh")


class _SameSiteOnly(OriginValidator):
    """Refuse a socket a page on another site opened; allow one with no page."""

    def valid_origin(self, parsed_origin):
        if parsed_origin is None:
            return True
        return super().valid_origin(parsed_origin)


_routes = ProtocolTypeRouter({
    "http": get_asgi_application(),
    "websocket": _SameSiteOnly(AuthMiddlewareStack(URLRouter([
        path("ws", RouhSocket.as_asgi()),
        # The one program's socket, through Rouh where no nginx sends it there (`rouh/onebridge.py`).
        path("one/ws", OneSocket.as_asgi()) if onebridge.on() else path("one/ws", NoSuchSocket.as_asgi()),
        re_path(r"", NoSuchSocket.as_asgi()),
    ])), settings.ALLOWED_HOSTS),
})


async def _lifespan(receive, send) -> None:
    """Start Rouh before the first request, and stop it after the last."""
    while True:
        message = await receive()
        if message["type"] == "lifespan.startup":
            try:
                from rouh import restarts, runtime

                # Whether the Rouh before this one went on purpose, before any
                # page can connect and ask (`rouh/restarts.py`).
                restarts.begin()
                await runtime.startup()
                # Synapse's lab picks up its queue where a restart left it.
                try:
                    from rouh.synapse import worker as synapse_worker

                    synapse_worker.start()
                except Exception:  # noqa: BLE001 - the lab is never worth a start
                    log.exception("Synapse's worker did not start")
            except BaseException as exc:
                log.exception("Rouh could not start")
                await send({"type": "lifespan.startup.failed",
                            "message": f"{type(exc).__name__}: {exc}"})
                return
            await send({"type": "lifespan.startup.complete"})
        elif message["type"] == "lifespan.shutdown":
            # Going on purpose, said first, so the pages that come back to the
            # next Rouh say Evolving rather than Reconnecting (`rouh/restarts.py`).
            from rouh import restarts

            restarts.stopping()
            # And nothing a deploy held back is let go by a Rouh on its way out (`rouh/answers_now.py`).
            with contextlib.suppress(Exception):
                from rouh import answers_now

                answers_now.stopping()
            try:
                from rouh import runtime

                await runtime.shutdown()
            except Exception:
                log.exception("Rouh did not stop cleanly")
            await send({"type": "lifespan.shutdown.complete"})
            return


async def application(scope, receive, send):
    if scope["type"] == "lifespan":
        return await _lifespan(receive, send)
    # A request the page marks as one nobody is waiting on - the offline copy
    # filling itself, a count for the navigation - does its work in the lane
    # kept for that, so it never holds a thread the conversation needs
    # (`rouh.dbwork.later`).
    if scope["type"] == "http" and _later(scope):
        from rouh import dbwork

        with dbwork.later():
            return await _routes(scope, receive, send)
    return await _routes(scope, receive, send)


def _later(scope) -> bool:
    for name, value in scope.get("headers") or ():
        if name == b"x-rouh-later":
            return value == b"1"
    return False
