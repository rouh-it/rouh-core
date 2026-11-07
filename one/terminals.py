"""The program's side of every run's terminal.

A run's terminal is held by its own holder process (``holder.py``), so it
survives the program restarting. This file is the other end: it starts a
holder, connects to it, keeps a copy of the screen, passes what the terminal
prints to whoever is watching, and types into it.

The copy of the screen is kept by pyte, a terminal emulator written in Python.
It is what lets the program:

* show a person who attaches the screen as it is now, not a replay of an
  hour of output (:meth:`Terminal.screen_ansi`);
* hand an agent "what the screen showed" as text when a person hands a run
  back (:meth:`Terminal.screen_text`);
* rebuild the screen after a restart from the end of the run's ``tty.log``.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
import signal
import subprocess
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

import pyte

from .holder import HEADER, frame

log = logging.getLogger("one.terminals")

#: How much of the end of tty.log is replayed to rebuild a screen after a
#: restart. A terminal program redraws its whole screen often, so the end of
#: the log is enough, and a whole hour of output would take seconds to replay.
REBUILD_TAIL = 256 * 1024
#: How much of the end of tty.log a page is given when it opens a run, so it
#: has the run's recent output to scroll back through, not only its screen (D50).
HISTORY_TAIL = 256 * 1024
#: The modes a program in the terminal turns on that change what a terminal
#: does for it, in the order another terminal needs them: its full screen
#: (1049), how the arrow keys are sent (1), the markers around a paste (2004),
#: and being told of the mouse (1000, 1002, 1003, in the form 1006). A page
#: opening a run is given them with its screen (D51): Claude Code 2.1.263
#: draws on the full screen, asks for the mouse, and scrolls back through the
#: whole run when told of the wheel.
CARRIED_MODES = (1049, 1, 2004, 1000, 1002, 1003, 1006)
_PRIVATE_MODE = re.compile(rb"\x1b\[\?([\d;]+)([hl])")
#: The most lines one message of the wheel scrolls.
WHEEL_MOST = 100
#: What a terminal reports of the mouse, and nothing else (D51).
MOUSE_REPORTS = re.compile(rb"(?:\x1b\[<\d{1,3};\d{1,4};\d{1,4}[Mm]|\x1b\[M[\x20-\xff]{3})+")

Watcher = Callable[[bytes], Any]


class Terminal:
    """One run's terminal, as the program sees it."""

    def __init__(self, run_id: str, folder: Path, *, cols: int = 120, rows: int = 40) -> None:
        self.run_id = run_id
        self.folder = Path(folder)
        self.cols, self.rows = cols, rows
        self.screen = pyte.Screen(cols, rows)
        self.stream = pyte.ByteStream(self.screen)
        #: Bytes of tty.log already fed to the screen.
        self.offset = 0
        self.watchers: dict[str, Watcher] = {}
        self.reader: asyncio.StreamReader | None = None
        self.writer: asyncio.StreamWriter | None = None
        self.exit: dict[str, Any] | None = None
        self.child_pid: int | None = None
        self.holder_pid: int | None = None
        self.on_exit: Callable[["Terminal", dict], Awaitable[None] | None] | None = None
        self.last_output = 0.0
        self._task: asyncio.Task | None = None
        self._connected = asyncio.Event()
        #: Set when the program lets go on purpose. Letting go is not the run ending.
        self._closing = False

    # -- connecting ----------------------------------------------------------

    @property
    def sock_path(self) -> Path:
        return self.folder / "ctl.sock"

    @property
    def log_path(self) -> Path:
        return self.folder / "tty.log"

    @property
    def connected(self) -> bool:
        return self.writer is not None and not self.writer.is_closing()

    async def connect(self, *, rebuild: bool = False) -> bool:
        """Connect to the holder. False when there is none to connect to."""
        try:
            reader, writer = await asyncio.open_unix_connection(str(self.sock_path))
        except (FileNotFoundError, ConnectionRefusedError, OSError):
            return False
        self.reader, self.writer = reader, writer
        try:
            kind, payload = await self._read_frame()
        except (asyncio.IncompleteReadError, ConnectionResetError, OSError):
            # The holder took the connection and then went, because its command
            # had already ended: a run of `sh -c "exit 4"` is over before the
            # program can say hello. There is no terminal to connect to, which
            # is what False means; the caller finds exit.json on its next pass.
            writer.close()
            self.reader = self.writer = None
            return False
        if kind != b"h":
            writer.close()
            self.reader = self.writer = None
            return False
        hello = json.loads(payload)
        self.child_pid = hello.get("child")
        self.holder_pid = hello.get("pid")
        self.cols, self.rows = int(hello.get("cols") or self.cols), int(hello.get("rows") or self.rows)
        if self.screen.columns != self.cols or self.screen.lines != self.rows:
            self.screen.resize(self.rows, self.cols)
        logged = int(hello.get("log") or 0)
        if rebuild and self.offset == 0:
            self.offset = max(0, logged - REBUILD_TAIL)
            if self.offset:
                self._carry_modes(self.offset)
        if logged > self.offset:
            self._catch_up(logged)
        self._task = asyncio.create_task(self._pump(), name=f"terminal-{self.run_id}")
        self._connected.set()
        return True

    def _catch_up(self, upto: int) -> None:
        """Feed the screen what was printed while nobody was connected."""
        try:
            with self.log_path.open("rb") as fh:
                fh.seek(self.offset)
                missed = fh.read(max(0, upto - self.offset))
        except OSError:
            return
        if missed:
            self.stream.feed(missed)
            self.offset += len(missed)

    def _carry_modes(self, upto: int) -> None:
        """Turn on the carried modes the program turned on before ``upto``.

        After a restart the screen is rebuilt from the end of tty.log only,
        and Claude Code turns on its full screen and the mouse once, as it
        starts. Without them a page opening the run after a deploy would get
        a screen the wheel does not scroll (D51).
        """
        state: dict[int, bool] = {}
        carry = b""
        try:
            with self.log_path.open("rb") as fh:
                left = upto
                while left > 0:
                    chunk = fh.read(min(1 << 20, left))
                    if not chunk:
                        break
                    left -= len(chunk)
                    data = carry + chunk
                    for match in _PRIVATE_MODE.finditer(data):
                        for code in match.group(1).split(b";"):
                            if code.isdigit() and int(code) in CARRIED_MODES:
                                state[int(code)] = match.group(2) == b"h"
                    # A sequence cut in two by the chunk is found whole next time.
                    carry = data[-64:]
        except OSError:
            return
        if state:
            self.stream.feed("".join(f"\x1b[?{m}{'h' if on else 'l'}"
                                     for m, on in state.items()).encode())

    async def _read_frame(self) -> tuple[bytes, bytes]:
        head = await self.reader.readexactly(HEADER.size)
        kind, size = HEADER.unpack(head)
        payload = await self.reader.readexactly(size) if size else b""
        return kind, payload

    async def _pump(self) -> None:
        try:
            while True:
                kind, payload = await self._read_frame()
                if kind == b"o":
                    self.stream.feed(payload)
                    self.offset += len(payload)
                    self.last_output = time.time()
                    for key, watcher in list(self.watchers.items()):
                        try:
                            result = watcher(payload)
                            if asyncio.iscoroutine(result):
                                await result
                        except Exception:
                            log.exception("a watcher of %s failed; dropping it", self.run_id)
                            self.watchers.pop(key, None)
                elif kind == b"x":
                    self.exit = json.loads(payload)
        except (asyncio.IncompleteReadError, ConnectionResetError, OSError):
            pass
        finally:
            self.writer = None
        if self._closing:
            return
        if self.exit is None:
            self.exit = read_exit(self.folder)
        if self.exit is None and holder_alive(self.folder):
            # The holder let go of us, most likely because we fell behind. The
            # run is fine: connect again and read what we missed from its log.
            for _ in range(20):
                await asyncio.sleep(0.25)
                if await self.connect():
                    return
            self.exit = read_exit(self.folder)
        if self.on_exit is not None:
            result = self.on_exit(self, self.exit or {})
            if asyncio.iscoroutine(result):
                await result

    # -- doing ---------------------------------------------------------------

    async def _send(self, kind: bytes, payload: bytes = b"") -> bool:
        if not self.connected:
            return False
        self.writer.write(frame(kind, payload))
        with contextlib.suppress(ConnectionResetError, BrokenPipeError):
            await self.writer.drain()
        return True

    async def type(self, data: bytes | str) -> bool:
        if isinstance(data, str):
            data = data.encode("utf-8")
        return await self._send(b"d", data)

    async def paste(self, text: str, *, submit: bool = True) -> bool:
        """Put text in as one paste, then press Enter, the way a person pastes.

        Bracketed paste keeps a multi-line message in one piece: without it
        every newline would be an Enter and send half a message.
        """
        ok = await self.type(b"\x1b[200~" + text.encode("utf-8") + b"\x1b[201~")
        if ok and submit:
            await asyncio.sleep(0.15)
            ok = await self.type(b"\r")
        return ok

    async def resize(self, cols: int, rows: int) -> None:
        cols = max(20, min(int(cols), 1000))
        rows = max(5, min(int(rows), 500))
        if (cols, rows) == (self.cols, self.rows):
            return
        self.cols, self.rows = cols, rows
        self.screen.resize(rows, cols)
        await self._send(b"w", json.dumps({"cols": cols, "rows": rows}).encode())

    async def nudge_redraw(self) -> None:
        """Make the program in the terminal draw its whole screen again.

        A terminal program redraws everything when its window changes size, so
        the window is made one column narrower and put back.
        """
        cols, rows = self.cols, self.rows
        await self._send(b"w", json.dumps({"cols": max(20, cols - 1), "rows": rows}).encode())
        await asyncio.sleep(0.05)
        await self._send(b"w", json.dumps({"cols": cols, "rows": rows}).encode())

    async def signal(self, sig: int = signal.SIGTERM) -> bool:
        return await self._send(b"k", json.dumps({"signal": int(sig)}).encode())

    async def closed(self, timeout: float | None = None) -> bool:
        if self._task is None:
            return True
        try:
            await asyncio.wait_for(asyncio.shield(self._task), timeout)
            return True
        except asyncio.TimeoutError:
            return False

    async def close(self) -> None:
        """Let go of the holder without stopping the run: the program is going away."""
        self._closing = True
        if self.writer is not None:
            self.writer.close()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task

    # -- the screen ------------------------------------------------------------

    def screen_text(self, *, last: int | None = None) -> str:
        lines = [line.rstrip() for line in self.screen.display]
        while lines and not lines[-1]:
            lines.pop()
        if last is not None:
            lines = lines[-last:]
        return "\n".join(lines)

    def screen_ansi(self) -> bytes:
        """The screen as it is now, after the modes its program has on (D51)."""
        return self.modes_ansi() + render_ansi(self.screen)

    def modes(self) -> list[int]:
        """The carried modes the program in the terminal has on now (D51).

        pyte keeps a private mode m as m << 5, so it is not mistaken for a
        public one of the same number.
        """
        return [m for m in CARRIED_MODES if (m << 5) in self.screen.mode]

    def modes_ansi(self) -> bytes:
        return "".join(f"\x1b[?{m}h" for m in self.modes()).encode()

    @property
    def full_screen(self) -> bool:
        """Whether its program draws on the terminal's full screen, which keeps no history."""
        return (1049 << 5) in self.screen.mode

    @property
    def wants_mouse(self) -> bool:
        """Whether its program asked to be told of the mouse."""
        return any((m << 5) in self.screen.mode for m in (1000, 1002, 1003))

    @staticmethod
    def is_mouse(data: bytes) -> bool:
        """Whether ``data`` is what a terminal reports of the mouse, and nothing else."""
        return bool(MOUSE_REPORTS.fullmatch(data))

    def wheel(self, lines: int, col: int, row: int) -> bytes | None:
        """The mouse wheel turned ``lines`` lines, up when below zero, over a
        cell, the way the program in the terminal asked to be told of the
        mouse. None when it did not ask: then nothing is sent, and never
        arrow keys (D50, D51)."""
        if not self.wants_mouse:
            return None
        mode = self.screen.mode
        button = 64 if lines < 0 else 65
        col = max(1, min(int(col), self.cols))
        row = max(1, min(int(row), self.rows))
        if (1006 << 5) in mode:
            one = f"\x1b[<{button};{col};{row}M".encode()
        else:  # the old form: each number in one byte, counted from 32
            one = b"\x1b[M" + bytes([32 + button, 32 + min(col, 223), 32 + min(row, 223)])
        return one * min(abs(int(lines)), WHEEL_MOST)

    def history(self, limit: int = HISTORY_TAIL) -> bytes:
        """The end of what the terminal printed, up to what the screen shows now.

        Written into an empty terminal of the same size, it draws the screen as
        it is and leaves the lines above it to scroll back to (D50). It starts
        at the beginning of a line, so it does not open inside a colour, and
        everything after it reaches a watcher added at the same moment.

        A program on the full screen keeps no history there, and what it
        printed is a stream of changes to one screen: its screen is given
        instead (D51). Either way the modes its program has on come first.
        """
        if self.full_screen:
            return self.screen_ansi()
        upto = self.offset
        start = max(0, upto - limit)
        try:
            with self.log_path.open("rb") as fh:
                fh.seek(start)
                data = fh.read(upto - start)
        except OSError:
            return self.screen_ansi()
        if start:
            cut = data.find(b"\n")
            data = data[cut + 1:] if cut >= 0 else data
        return (self.modes_ansi() + data) if data else self.screen_ansi()


# ---------------------------------------------------------------------------
# Starting holders
# ---------------------------------------------------------------------------


class Terminals:
    """Every run's terminal the program holds, by run id."""

    def __init__(self, root: Path, *, python: str, app_root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.python = python
        self.app_root = Path(app_root)
        self.by_run: dict[str, Terminal] = {}

    def folder(self, run_id: str) -> Path:
        return self.root / run_id

    async def start(self, run_id: str, argv: list[str], *, cols: int, rows: int,
                    env: dict[str, str] | None = None, cwd: str | None = None,
                    wait: float = 15.0) -> Terminal:
        folder = self.folder(run_id)
        folder.mkdir(parents=True, exist_ok=True)
        for name in ("exit.json", "ctl.sock"):
            with contextlib.suppress(FileNotFoundError):
                (folder / name).unlink()
        command = [self.python, "-m", "one.holder", "--dir", str(folder), "--cols", str(cols),
                   "--rows", str(rows)]
        if cwd:
            command += ["--cwd", cwd]
        command += ["--", *argv]
        holder_log = open(folder / "holder.log", "ab")
        try:
            subprocess.Popen(command, cwd=str(self.app_root), env=env or dict(os.environ),
                             stdin=subprocess.DEVNULL, stdout=holder_log, stderr=subprocess.STDOUT,
                             start_new_session=True, close_fds=True)
        finally:
            holder_log.close()
        terminal = Terminal(run_id, folder, cols=cols, rows=rows)
        self.by_run[run_id] = terminal
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            if (folder / "ctl.sock").exists() and await terminal.connect():
                return terminal
            if (folder / "exit.json").exists():
                # It ended before it could be reached. What it printed is in the log.
                terminal.exit = read_exit(folder)
                terminal._catch_up(terminal.log_path.stat().st_size
                                   if terminal.log_path.exists() else 0)
                return terminal
            await asyncio.sleep(0.03)
        raise RuntimeError(f"the holder for {run_id} did not start within {wait:.0f} seconds; "
                           f"see {folder / 'holder.log'}")

    async def adopt(self, run_id: str) -> Terminal | None:
        """Connect to a run's holder after a restart. None when it is not there."""
        folder = self.folder(run_id)
        terminal = Terminal(run_id, folder)
        if (folder / "ctl.sock").exists() and await terminal.connect(rebuild=True):
            self.by_run[run_id] = terminal
            return terminal
        return None

    def get(self, run_id: str) -> Terminal | None:
        return self.by_run.get(run_id)

    def alive(self, run_id: str) -> bool:
        """Whether this run's terminal session is there now, asked of the system.

        Not worked out from the run's state: a run that has finished its turn
        still has its terminal, and one whose holder died has none whatever the
        list last said. The program's own connection answers when it has one,
        and the holder's process answers when it does not - after a restart,
        say, before the run has been adopted.
        """
        terminal = self.by_run.get(run_id)
        if terminal is not None and terminal.exit is None and terminal.connected:
            return True
        return session_alive(self.folder(run_id))

    def forget(self, run_id: str) -> None:
        self.by_run.pop(run_id, None)

    async def close(self) -> None:
        for terminal in list(self.by_run.values()):
            await terminal.close()


def read_exit(folder: Path) -> dict[str, Any] | None:
    try:
        return json.loads((Path(folder) / "exit.json").read_text())
    except (OSError, ValueError):
        return None


def session_alive(folder: Path) -> bool:
    """Whether the terminal session in this folder is still open.

    ``exit.json`` is written by the holder on its way out and removed when a
    new one starts, so it is the plain answer; a holder that was killed
    outright writes nothing, and then its process says.
    """
    if (Path(folder) / "exit.json").exists():
        return False
    return holder_alive(folder)


def holder_alive(folder: Path) -> bool:
    try:
        pid = int(json.loads((Path(folder) / "holder.json").read_text())["pid"])
    except (OSError, ValueError, KeyError, TypeError):
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


# ---------------------------------------------------------------------------
# Drawing a screen for a terminal that attaches
# ---------------------------------------------------------------------------

_BASIC = {"black": 0, "red": 1, "green": 2, "brown": 3, "yellow": 3, "blue": 4,
          "magenta": 5, "cyan": 6, "white": 7}
_BRIGHT = {"brightblack": 0, "brightred": 1, "brightgreen": 2, "brightbrown": 3,
           "brightyellow": 3, "brightblue": 4, "brightmagenta": 5, "brightcyan": 6,
           "brightwhite": 7}


def _colour(value: str, fg: bool) -> list[str]:
    if not value or value == "default":
        return []
    if value in _BASIC:
        return [str((30 if fg else 40) + _BASIC[value])]
    if value in _BRIGHT:
        return [str((90 if fg else 100) + _BRIGHT[value])]
    if len(value) == 6:
        try:
            r, g, b = int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)
        except ValueError:
            return []
        return ["38" if fg else "48", "2", str(r), str(g), str(b)]
    return []


def render_ansi(screen: pyte.Screen) -> bytes:
    """The screen as a terminal would draw it: clear, then every cell, then the cursor."""
    out: list[str] = ["\x1b[0m\x1b[2J\x1b[H"]
    last: tuple | None = None
    for y in range(screen.lines):
        row = screen.buffer[y]
        out.append(f"\x1b[{y + 1};1H")
        line: list[str] = []
        x = 0
        while x < screen.columns:
            char = row[x]
            style = (char.fg, char.bg, char.bold, char.italics, char.underscore,
                     char.reverse, char.strikethrough)
            if style != last:
                codes = ["0"]
                if char.bold:
                    codes.append("1")
                if char.italics:
                    codes.append("3")
                if char.underscore:
                    codes.append("4")
                if char.reverse:
                    codes.append("7")
                if char.strikethrough:
                    codes.append("9")
                codes += _colour(char.fg, True)
                codes += _colour(char.bg, False)
                line.append("\x1b[" + ";".join(codes) + "m")
                last = style
            data = char.data or " "
            line.append(data)
            # A wide character takes two cells; pyte leaves the second empty.
            x += 2 if len(data) == 1 and _wide(data) else 1
        out.append("".join(line).rstrip(" ") if last == (
            "default", "default", False, False, False, False, False) else "".join(line))
    out.append("\x1b[0m")
    out.append(f"\x1b[{screen.cursor.y + 1};{screen.cursor.x + 1}H")
    if screen.cursor.hidden:
        out.append("\x1b[?25l")
    else:
        out.append("\x1b[?25h")
    return "".join(out).encode("utf-8")


def _wide(ch: str) -> bool:
    try:
        from wcwidth import wcwidth
    except ImportError:  # pragma: no cover - pyte depends on wcwidth
        return False
    return wcwidth(ch) == 2
