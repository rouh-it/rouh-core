"""The program: one process that holds every run and keeps one list.

This file puts the parts together and runs them. Step 07, section 4:

* the writer   - ``listfile.ListFile``, the only thing that adds to the list
* the terminals - ``terminals.Terminals``, one holder per run
* the scheduler - ``scheduler.Scheduler`` and ``rules``
* the documents - ``documents.Documents``, checkouts and landing
* the model     - Claude Code, in each run; Rouh's voice attaches from outside
* the protocol  - ``protocol.Client``, over the socket and over the web

Every entry the list takes is applied to the views and heard by every
connection, in the order it was written. Nothing is sent to a screen that is
not in the list first.

**The watchdog.** The service is started with ``WatchdogSec``: this process
has to tell systemd it is alive every few seconds, from the same loop that
does everything else. If that loop ever stops for half a minute, as Rouh's
did for 11 minutes on 14 September, systemd restarts the program, and the
runs carry on in their holders.

Run it with ``python -m one.program``.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import signal
import socket
import time
from pathlib import Path
from typing import Any

from . import billing, version
from .claude_signin import SignIn
from .codex_signin import CodexSignIn
from .config import Settings, load
from .devices import Pairing
from .documents import Documents
from .listfile import ListFile, epoch
from .phone import Phone
from .questions import Questions
from .runs import Runs
from .scheduler import CpuMeter, Scheduler
from .terminals import Terminals
from .transcripts import Transcripts
from .views import TREE_KINDS, Views

log = logging.getLogger("one")

APP_ROOT = Path(__file__).resolve().parent.parent

#: How often the views' saved position is written, in entries and seconds.
SNAPSHOT_EVERY = 2000
SNAPSHOT_SECONDS = 60.0
#: A notice about the same run for the same reason goes to the phone at most this often.
TELL_EVERY = 300.0


def sd_notify(state: str) -> None:
    """Tell systemd something, if systemd is listening. Does nothing on the laptop."""
    address = os.environ.get("NOTIFY_SOCKET")
    if not address:
        return
    if address.startswith("@"):
        address = "\0" + address[1:]
    with contextlib.suppress(OSError):
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
            sock.connect(address)
            sock.sendall(state.encode())


class Program:
    def __init__(self, settings: Settings, *, phone: Any = None, meter: CpuMeter | None = None) -> None:
        self.settings = settings
        settings.data.mkdir(parents=True, exist_ok=True)
        self.list = ListFile(settings.list_dir)
        self.views = self._load_views()
        self.list.listen(self._on_entry)
        self.terminals = Terminals(settings.runs_state, python=settings.python, app_root=APP_ROOT)
        self.documents = Documents(settings)
        self.questions = Questions(self.list, self.views, timeout=settings.question_timeout)
        #: The OpenAI API key, for runs of Codex billed to it, in memory only.
        self.api_key = billing.Key()
        #: Claude Code's sign-in, for Rouh's page, in the containers only.
        self.claude_signin = SignIn()
        #: Codex's sign-in with a ChatGPT plan, for Rouh's page, in the containers only. A lost
        #: sign-in is told to the phone once, not for every run it stops.
        self.codex_signin = CodexSignIn(settings, tell=lambda text: self.tell(None, text, reason="codex-signin"))
        self.pairing = Pairing()
        self.phone = phone if phone is not None else Phone(settings.telegram)
        self.runs = Runs(self)
        self.scheduler = Scheduler(self, meter=meter)
        self.transcripts = Transcripts(self)
        self.clients: set[Any] = set()
        self.started_at = time.time()
        self._tree_dirty = True
        self._tree_sent: str | None = None
        self._since_snapshot = 0
        self._snapshot_at = time.monotonic()
        self._told: dict[tuple[str, str], float] = {}
        self._tasks: list[asyncio.Task] = []
        self._sends: set[asyncio.Task] = set()

    # -- the list and the views ----------------------------------------------------

    def _load_views(self) -> Views:
        views = Views()
        with contextlib.suppress(OSError, ValueError):
            views = Views.restore(json.loads(self.settings.snapshot_path.read_text()))
        if views.n > self.list.last_n:
            views = Views()  # a saved position from a different list: start again
        views.apply_all(self.list.read(since=views.n))
        return views

    def _on_entry(self, entry: dict[str, Any]) -> None:
        self.views.apply(entry)
        kind = entry["kind"]
        if kind in TREE_KINDS or kind.startswith(("run.", "question.")):
            self._tree_dirty = True
        for client in list(self.clients):
            client.hear(entry)
        self.transcripts.hear(entry)
        self._since_snapshot += 1

    def save_snapshot(self) -> None:
        path = self.settings.snapshot_path
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.views.snapshot()))
        os.replace(tmp, path)
        self._since_snapshot = 0
        self._snapshot_at = time.monotonic()

    def tree(self) -> dict[str, Any]:
        return self.views.tree(time.time())

    def device_name(self, device_id: str | None) -> str:
        if not device_id:
            return "someone"
        if device_id == "console":
            return "the server's own terminal"
        return (self.views.devices.get(device_id) or {}).get("name") or device_id

    # -- starting and stopping ---------------------------------------------------------

    async def start(self) -> None:
        self.list.append("program.started",
                         body={**version.describe(), "pid": os.getpid()})
        await self.runs.adopt_all()
        self.scheduler.start()
        self._tasks = [asyncio.create_task(self._beat(), name="beat"),
                       asyncio.create_task(self._phone_questions(), name="phone")]
        sd_notify("READY=1")

    async def stop(self) -> None:
        sd_notify("STOPPING=1")
        for task in self._tasks:
            task.cancel()
        await self.scheduler.stop()
        with contextlib.suppress(Exception):
            self.list.append("program.stopping", body={"pid": os.getpid()})
        for client in list(self.clients):
            with contextlib.suppress(Exception):
                await client.close()
        with contextlib.suppress(Exception):
            await self.transcripts.close()
        with contextlib.suppress(Exception):
            # A device sign-in waiting for its approval ends with the program, never after it.
            await self.codex_signin.close()
        await self.runs.close()
        # The runs go on in their holders. Only the program's hold on them ends.
        await self.terminals.close()
        with contextlib.suppress(Exception):
            self.save_snapshot()
        self.list.close()

    # -- the beat ---------------------------------------------------------------------

    async def _beat(self) -> None:
        """A quarter-second heartbeat: the tree, typed keys, the saved position, systemd."""
        ticks = 0
        while True:
            await asyncio.sleep(0.25)
            ticks += 1
            try:
                if self._tree_dirty or ticks % 8 == 0:
                    self._push_tree()
                if ticks % 4 == 0:
                    self.runs.flush_keys()
                    sd_notify("WATCHDOG=1")
                    await self.runs.hand_back_quiet()
                if (self._since_snapshot >= SNAPSHOT_EVERY
                        or (self._since_snapshot and time.monotonic() - self._snapshot_at > SNAPSHOT_SECONDS)):
                    await asyncio.to_thread(self.save_snapshot)
            except Exception:
                log.exception("the beat hit a problem; carrying on")

    def _push_tree(self) -> None:
        self._tree_dirty = False
        watching = [c for c in self.clients if "tree" in c.subs]
        if not watching:
            return
        tree = self.tree()
        text = json.dumps(tree, sort_keys=True, default=str)
        if text == self._tree_sent:
            return
        self._tree_sent = text
        message = {"t": "tree", "tree": tree, "now": time.time()}
        for client in watching:
            client.push(message)

    # -- the phone ----------------------------------------------------------------------

    async def _phone_questions(self) -> None:
        """Send the phone every question nobody has answered for a while."""
        while True:
            await asyncio.sleep(1.0)
            now = time.time()
            for q in self.views.open_questions():
                if q.get("phoned") or now - epoch(q["asked_at"]) < self.settings.phone_after:
                    continue
                token = self.questions.phone_token(q["id"])
                url = f"{self.settings.public_url}/q/{token}"
                run = self.views.runs.get(q.get("run") or "") or {}
                text = f"{run.get('title') or 'A run'} is waiting for you.\n\n{q['text']}"
                ok = await self._send_phone(text, [("Allow", url + "?a=yes"), ("Deny", url + "?a=no")])
                self.list.append("phone.sent", run=q.get("run"), body={
                    "question": q["id"], "kind": "question", "ok": ok})

    def tell(self, run_id: str | None, text: str, *, reason: str) -> None:
        """A notice for the phone, about a run, at most once every five minutes per reason."""
        key = (run_id or "", reason)
        now = time.monotonic()
        if now - self._told.get(key, -TELL_EVERY) < TELL_EVERY:
            return
        self._told[key] = now

        async def send() -> None:
            link = f"{self.settings.public_url}/#run={run_id}" if run_id else self.settings.public_url
            ok = await self._send_phone(text, [("Open", link)])
            self.list.append("phone.sent", run=run_id, body={"kind": "notice", "reason": reason,
                                                             "ok": ok})

        task = asyncio.create_task(send())
        self._sends.add(task)
        task.add_done_callback(self._sends.discard)

    async def _send_phone(self, text: str, buttons: list[tuple[str, str]]) -> bool:
        try:
            return bool(await self.phone.send(text, buttons=buttons))
        except Exception:
            log.exception("the phone message failed")
            return False


# ---------------------------------------------------------------------------
# Running it
# ---------------------------------------------------------------------------


async def serve(settings: Settings, *, phone: Any = None, meter: CpuMeter | None = None,
                ready: asyncio.Event | None = None, stop: asyncio.Event | None = None) -> None:
    import uvicorn

    from .web import make_app, serve_socket

    program = Program(settings, phone=phone, meter=meter)
    await program.start()
    if os.environ.get("ONE_SHELL_FOR_ROUH") == "1":
        # The box Rouh's shell runs its commands in, looked at once and written down for the
        # core's server_health (one/shell.py).
        from . import shell

        state = await asyncio.to_thread(shell.write_state, settings.socket)
        (log.info if state["on"] else log.warning)("rouh's shell: %s", state["said"])
    socket_server = await serve_socket(program, settings.socket)
    app = make_app(program)
    # wsproto rather than uvicorn's websockets implementation, which is built
    # on an interface the websockets package has deprecated.
    config = uvicorn.Config(app, host=settings.http_host, port=settings.http_port,
                            log_level="warning", ws="wsproto", ws_ping_interval=20,
                            ws_ping_timeout=20, proxy_headers=False, lifespan="off",
                            access_log=False,
                            # Longer than any client waits to reuse an idle
                            # connection, so the server is never the one that
                            # closes it as a request arrives (see web.py's hook).
                            timeout_keep_alive=75)
    server = uvicorn.Server(config)
    # uvicorn catches SIGTERM itself and raises it again once it has stopped
    # serving. A handler of our own is what it raises it into, so the program
    # gets to close its list and save its position instead of dying mid-write.
    signal.signal(signal.SIGTERM, lambda *_: None)
    web = asyncio.create_task(server.serve(), name="web")
    if ready is not None:
        while not server.started and not web.done():
            await asyncio.sleep(0.02)
        ready.set()
    try:
        if stop is not None:
            done, _ = await asyncio.wait({web, asyncio.create_task(stop.wait())},
                                         return_when=asyncio.FIRST_COMPLETED)
            server.should_exit = True
            await web
        else:
            await web
    finally:
        socket_server.close()
        await socket_server.wait_closed()
        with contextlib.suppress(FileNotFoundError):
            os.unlink(settings.socket)
        await program.stop()


#: Libraries that log every request's address at INFO. Telegram puts the bot's
#: key in the address, so on 14 September 2026 the first phone message wrote the
#: key into the program's log. They only ever say something above INFO now.
QUIET = ("httpx", "httpcore")


def quiet_libraries() -> None:
    for name in QUIET:
        logging.getLogger(name).setLevel(logging.WARNING)


def main() -> None:
    logging.basicConfig(level=os.environ.get("ONE_LOG", "INFO"),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    quiet_libraries()
    asyncio.run(serve(load()))


if __name__ == "__main__":
    main()
