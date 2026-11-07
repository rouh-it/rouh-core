"""The websocket: the voice, the transcript and the task list, one per tab.

A Channels consumer since 23 September 2026, when it stopped being a FastAPI
route. What happens on the socket is unchanged and is all `runtime.Session`:
this class only puts a tab's socket in front of one, and takes it away again.

The same Django session that lets a person see the page lets them open this
(`AuthMiddlewareStack` in `rouh/project/asgi.py` reads the ``rouh_session``
cookie off the upgrade). A socket with no sign-in behind it is accepted and
closed at once with code 4401, rather than refused at the handshake: a refused
handshake reaches the page as a plain failed connection, and the page would
sit there reconnecting forever. 4401 is what the page reads as "go and sign
in again". Nothing is read from or written to the socket in between.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time

from channels.generic.websocket import AsyncWebsocketConsumer

log = logging.getLogger("rouh")

#: Seconds a message from a tab may take before the log says so (`receive`).
SLOW_MESSAGE = 2.0


def _kind(text: str) -> str:
    """The `type` of a message from the page, for the log, and nothing else of it."""
    try:
        got = json.loads(text)
    except (ValueError, TypeError):
        return "?"
    return str(got.get("type") or "?")[:40] if isinstance(got, dict) else "?"

#: The messages that carry lists a demo copy could be in, and are looked through for one
#: outside demo mode (`demo.hide_copies`).
_LISTS = ('"type": "objects"', '"type": "workspace"', '"type": "search_results"', '"type": "tree"',
          '"type": "task_refs"', '"type": "chats"', '"type": "ready"', '"type": "tasks"')

#: The close code the page reads as "sign in again".
SIGN_IN_AGAIN = 4401


class _Wire:
    """What `runtime.Session` writes to: text or bytes, down this tab's socket.

    Every message the page is sent passes `send_text`, so it is where any owner
    mark still in one (`rouh/owner.py`) is filled in for the person on this
    socket, as the last safety net (SETUP.md). A message without a mark - nearly
    every one - is sent as it was, without a second look. `json.dumps` writes the
    mark as ``\\u2039``, which is looked for too.
    """

    def __init__(self, consumer: AsyncWebsocketConsumer) -> None:
        self._consumer = consumer
        #: The person on this socket (an Identity), set once the socket is theirs.
        self.who = None
        #: This browser is in demo mode's preview (`rouh/demo.py`).
        self.preview = False

    async def send_text(self, text: str) -> None:
        if "\u2039" in text or "\\u2039" in text:
            from rouh import owner

            text = (await asyncio.to_thread(owner.say_bytes, text.encode("utf-8"), self.who)).decode("utf-8")
        text = await self._demo(text)
        if text is None:
            return
        await self._consumer.send(text_data=text)

    async def _demo(self, text: str) -> str | None:
        """Outside demo mode, every demo copy taken out of the lists it would be in
        (`demo.hide_copies`). In demo mode nothing is changed: the browser blurs
        (`rouh/demo_style.py`)."""
        from rouh import demo

        if self.who is None or '"type": "demo"' in text or not any(kind in text for kind in _LISTS):
            return text
        try:
            if self.preview or demo.state(self.who)["on"]:
                return text
        except Exception:
            return text
        if not await asyncio.to_thread(demo.copies):
            return text
        try:
            return json.dumps(demo.hide_copies(json.loads(text)))
        except (ValueError, TypeError):
            return text

    async def send_bytes(self, data: bytes) -> None:
        await self._consumer.send(bytes_data=data)


class RouhSocket(AsyncWebsocketConsumer):
    """One browser tab."""

    session = None

    async def connect(self) -> None:
        user = self.scope.get("user")
        if user is None or not getattr(user, "is_authenticated", False):
            await self.accept()
            await self.close(code=SIGN_IN_AGAIN)
            log.info("websocket refused: no sign-in")
            return
        if getattr(user, "is_guest", False):
            # Somebody a page was shared with. The socket is Rouh itself - the
            # voice, the chats, every tool - and a guest has the pages shared
            # with them and nothing else (`rouh/web/gate.py`).
            await self.accept()
            await self.close(code=SIGN_IN_AGAIN)
            log.info("websocket refused: a guest account")
            return
        from rouh import runtime
        from rouh.tenancy import set_speaker

        await self.accept()
        # Who is on this socket, for everything the socket goes on to start.
        # It is left in this connection's context, so a tool called inside a
        # spoken turn knows whose mail it may read without anything having to
        # be threaded through the model loop (tenancy.py). Each connection is
        # its own task, so nothing leaks between two tabs or two people.
        me = runtime.tenancy.current(user)
        set_speaker(me)
        wire = _Wire(self)
        wire.who = me
        # Demo mode's preview is this browser's alone (`rouh/demo.py`).
        from rouh import demo

        wire.preview = (self.scope.get("cookies") or {}).get(demo.PREVIEW_COOKIE) == "1"
        session = runtime.Session(wire)
        session.me = me
        session.demo_preview = wire.preview
        self.session = session
        runtime.Hub.sockets.add(session)
        log.info("tab connected as %s (%d open)", me.name if me else "nobody",
                 len(runtime.Hub.sockets))

    async def receive(self, text_data=None, bytes_data=None) -> None:
        if self.session is None:
            return
        # A tab's messages are handled one at a time, so one that is slow
        # holds up every one behind it - the search box's question too, which
        # then sits unanswered with nothing said (fr_7356fafcdd76). Which one
        # it was is written down, so the next time is a line in the log.
        began = time.monotonic()
        try:
            if text_data is not None:
                if _kind(text_data) == "hello":
                    # A page opening: work nobody waits on holds back until its
                    # conversation is on its way (`dbwork.foreground`).
                    from rouh import dbwork

                    with dbwork.foreground():
                        await self.session.handle_text(text_data)
                else:
                    await self.session.handle_text(text_data)
                took = time.monotonic() - began
                if took > SLOW_MESSAGE:
                    log.warning("socket message %s took %.1fs; the tab's messages behind it waited",
                                _kind(text_data), took)
            elif bytes_data is not None:
                await self.session.handle_bytes(bytes_data)
        except Exception:
            log.exception("socket died")
            await self.close()

    async def disconnect(self, code) -> None:
        session, self.session = self.session, None
        if session is None:
            return
        from rouh import runtime

        # The tab is gone; the turn it asked for is not. A reload closes this
        # socket in the middle of an answer, and the turn belongs to its thread
        # and carries on there, silently from here on; the page picks it up
        # again on `hello` (`Turn`).
        session.closed = True
        session.stop_waiting()
        if session.live is not None:
            with contextlib.suppress(Exception):
                await session.live.close()
            session.live = None
        runtime.Hub.sockets.discard(session)
        log.info("tab gone (%d open)", len(runtime.Hub.sockets))


class NoSuchSocket(AsyncWebsocketConsumer):
    """Any other socket address: refused at the handshake.

    The page also opens the one program's socket, `/one/ws`, which nginx sends
    to the program and never here. Where there is no nginx in front - a laptop,
    the browser environment - it arrives here, and it is refused plainly
    rather than failing with a server error on every retry.
    """

    async def connect(self) -> None:
        await self.close()
