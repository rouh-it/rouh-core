"""The run door: each run's own way out, with its own identity, which no other run can borrow.

Task 191 (Petar, 20 November 2026): "the switch should cover all 5 items in the rouh-open". The
key proxy (guard/rouh_guard/keyproxy.py) is every run's only way out, but it sits in another
container and sees every run arrive from the same address, so on its own it cannot give the
owner's Unrestricted run the internet, GitHub and his servers while a run a stranger's mail
started gets none of it. This door is what tells them apart.

**What it holds, in this process's memory and nowhere else.** For every run the program has a
terminal for, a proxy password (32 random bytes) and a run token (an HMAC of the run's id under a
key made when the program starts). Neither is ever in a run's environment, a file or an argument,
because every run is the same Linux user and could read those of another run; this process's
memory is the one place no run can read (``ptrace`` is limited to descendants). The key proxy is
told only the passwords' hashes, by Rouh's core, which asks the program for them
(``hashes``) and decides from the owner's mode and the run's origin which of them get what
(`rouh/run_access.py`). A program that starts again makes new ones; the core picks them up within
seconds.

**The door itself.** A forward proxy on ``127.0.0.1`` (``ONE_DOOR_PORT``, 8078) and on a unix
socket in the worker's home (the one ``bin/rouh-github`` gives gh), which every run's
``HTTPS_PROXY`` and ``HTTP_PROXY`` point at. For each connection it asks the kernel which process
opened it (`one/peers.py`) and which run that process descends from, takes off any
Proxy-Authorization the caller sent, puts that run's own on, and hands the connection to the key
proxy as it is. A connection from no run (a process that cut itself loose, or anything the
program did not start) goes on with nothing added, which is Restricted.

**The token.** ``bin`` tools and ``rouh/worker_mcp.py`` ask the control socket for their run's
token (``run_token``); the socket answers only with the token of the run the asking process
descends from. Rouh's core checks a token with ``run_token_check`` before it believes a job is
the run it says, so a run naming another run is refused (191-01 weak spot 2).

Standard library only.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import hmac
import logging
import os
import secrets
import time
from typing import Any, Callable
from urllib.parse import urlsplit

from . import peers

log = logging.getLogger("one.rundoor")

#: The header the key proxy reads a run's password from, and what the door always takes off.
AUTH = "proxy-authorization"
HEAD_LIMIT = 64 * 1024


def _port() -> int:
    try:
        return int(os.environ.get("ONE_DOOR_PORT", "") or 8078)
    except ValueError:
        return 8078


def gh_socket() -> str:
    """The unix socket gh talks over (bin/rouh-github keeps the same path); ``ONE_DOOR_GH_SOCKET``
    names another (a test world's own, so it never takes the worker's), and "off" none."""
    said = os.environ.get("ONE_DOOR_GH_SOCKET", "").strip()
    if said:
        return "" if said == "off" else said
    home = os.environ.get("HOME") or "/home/rouh"
    path = os.path.join(home, ".cache", "rouh-github", "gh.sock")
    if len(path) > 100:
        path = f"/tmp/rouh-github-{os.getuid()}/gh.sock"
    return path


def upstream() -> tuple[str, int] | None:
    """The key proxy, from the program's own settings as the worker was started with them."""
    raw = os.environ.get("ONE_DOOR_UPSTREAM") or os.environ.get("ROUH_MODEL_PROXY") or ""
    if not raw:
        for name in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
            value = os.environ.get(name) or ""
            if value and "127.0.0.1" not in value and "localhost" not in value:
                raw = value
                break
    if not raw:
        return None
    url = urlsplit(raw if "://" in raw else "http://" + raw)
    return (url.hostname or "keyproxy", url.port or 8080) if url.hostname else None


class Door:
    """The run door, its secrets and its two listeners. One per program."""

    def __init__(self, holders: Callable[[], dict[int, tuple[str, int]]],
                 live: Callable[[str], bool] | None = None) -> None:
        #: {holder pid: (run id, start time)} now, from the program's terminals.
        self._holders = holders
        self._live = live or (lambda _run: True)
        self._key = secrets.token_bytes(32)
        self._passwords: dict[str, str] = {}
        self._program_password = secrets.token_urlsafe(32)
        self.started_at = time.time()
        self.port = _port()
        self.servers: list[asyncio.base_events.Server] = []
        self.seen: dict[str, float] = {}
        #: Attempts to use another run's identity, for the core's tripwire (`attempts`).
        self._attempts: list[dict] = []

    # --- identity ------------------------------------------------------------------------------

    def whose(self, pid: int) -> str:
        if pid == 0:
            return peers.OUTSIDE
        if pid < 0:
            return peers.UNKNOWN
        try:
            return peers.whose_pid(pid, self._holders())
        except Exception:  # noqa: BLE001 - nobody known is nobody
            log.exception("whose process %s is could not be read", pid)
            return peers.UNKNOWN

    def password(self, run: str) -> str:
        if run == peers.PROGRAM:
            return self._program_password
        got = self._passwords.get(run)
        if got is None:
            got = self._passwords[run] = secrets.token_urlsafe(32)
        return got

    def token(self, run: str) -> str:
        mac = hmac.new(self._key, f"run:{run}".encode(), hashlib.sha256).hexdigest()
        return f"{run}.{mac}"

    def check(self, token: str) -> str:
        """The run a token was given to, or "" when it is not one of this program's."""
        run, _, mac = str(token or "").rpartition(".")
        if not run or not mac:
            return ""
        if not hmac.compare_digest(self.token(run), f"{run}.{mac}"):
            return ""
        return run

    def note_attempt(self, what: str, **detail: Any) -> None:
        self._attempts.append({"at": time.time(), "what": what, **detail})
        del self._attempts[:-50]
        log.warning("run door: %s %s", what, detail)

    def attempts(self, since: float = 0.0) -> list[dict]:
        return [a for a in self._attempts if a["at"] > since]

    def hashes(self) -> list[dict]:
        """What the core hands the key proxy: each live run's password hash, never the password."""
        out = [{"run": "", "who": peers.PROGRAM, "hash": _hash(self._program_password)}]
        holders = self._holders()
        live = {run for run, _start in holders.values()}
        for run in list(self._passwords):
            if run not in live:
                self._passwords.pop(run, None)
        for run in sorted(live):
            out.append({"run": run, "who": "run", "hash": _hash(self.password(run))})
        return out

    # --- the door ------------------------------------------------------------------------------

    async def start(self) -> None:
        if upstream() is None:
            log.info("run door: no key proxy in this program's settings, so no door")
            return
        try:
            self.servers.append(await asyncio.start_server(self._tcp, "127.0.0.1", self.port,
                                                           limit=HEAD_LIMIT * 2))
        except OSError as exc:
            log.warning("run door: port %s could not be opened (%s)", self.port, exc)
            return
        path = gh_socket()
        if not path:
            log.info("run door open on 127.0.0.1:%s", self.port)
            return
        try:
            os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
            with contextlib.suppress(FileNotFoundError):
                os.unlink(path)
            self.servers.append(await asyncio.start_unix_server(self._unix, path,
                                                                limit=HEAD_LIMIT * 2))
            os.chmod(path, 0o600)
        except OSError as exc:
            log.warning("run door: gh's socket %s could not be opened (%s)", path, exc)
        log.info("run door open on 127.0.0.1:%s and %s", self.port, path)

    def address(self) -> str:
        return f"http://127.0.0.1:{self.port}" if self.servers else ""

    async def close(self) -> None:
        for server in self.servers:
            server.close()
        self.servers.clear()

    async def _tcp(self, reader, writer) -> None:
        peer = writer.get_extra_info("peername")
        here = writer.get_extra_info("sockname")
        pid = await asyncio.to_thread(peers.tcp_peer_pid, peer, here)
        await self._through(reader, writer, self.whose(pid) if pid else peers.UNKNOWN)

    async def _unix(self, reader, writer) -> None:
        sock = writer.get_extra_info("socket")
        pid = peers.peer_pid(sock)
        await self._through(reader, writer, self.whose(pid) if pid > 0 else peers.UNKNOWN)

    async def _through(self, reader, writer, whose: str) -> None:
        up = upstream()
        try:
            try:
                head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 30)
            except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, asyncio.TimeoutError,
                    ConnectionError):
                return
            if up is None or len(head) > HEAD_LIMIT:
                return
            lines = head.decode("latin-1").split("\r\n")
            kept = [lines[0]] + [ln for ln in lines[1:] if ln and
                                 ln.split(":", 1)[0].strip().lower() != AUTH]
            if whose not in peers.NOT_RUNS or whose == peers.PROGRAM:
                name = "program" if whose == peers.PROGRAM else f"run-{whose}"
                pair = base64.b64encode(f"{name}:{self.password(whose)}".encode()).decode()
                kept.append(f"Proxy-Authorization: Basic {pair}")
                self.seen[whose] = time.time()
            try:
                up_reader, up_writer = await asyncio.wait_for(asyncio.open_connection(*up), 20)
            except (OSError, asyncio.TimeoutError):
                writer.write(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n"
                             b"Connection: close\r\n\r\n")
                with contextlib.suppress(Exception):
                    await writer.drain()
                return
            up_writer.write(("\r\n".join(kept) + "\r\n\r\n").encode("latin-1"))
            await up_writer.drain()
            await asyncio.gather(_pipe(reader, up_writer), _pipe(up_reader, writer))
            with contextlib.suppress(Exception):
                up_writer.close()
        except Exception:  # noqa: BLE001
            log.exception("run door: a connection failed")
        finally:
            with contextlib.suppress(Exception):
                writer.close()


def _hash(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


async def _pipe(reader, writer) -> None:
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
    except (ConnectionError, OSError, asyncio.IncompleteReadError):
        pass
    finally:
        with contextlib.suppress(Exception):
            if writer.can_write_eof():
                writer.write_eof()


__all__ = ["Door", "gh_socket", "upstream"]
