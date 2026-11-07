"""One run's terminal, held by a process of its own.

The program starts one holder per run. The holder opens a pseudo-terminal,
starts the run's command on it, and from then on:

- writes everything the terminal prints to ``tty.log`` in the run's folder, so
  a person can read the whole of it afterwards and the program can rebuild the
  screen after it restarts;
- relays the terminal to one controller at a time, the program, over
  ``ctl.sock`` in the same folder;
- when the command ends, writes ``exit.json`` and goes.

It is a separate process so that a run outlives the program. When the program
restarts - a deploy, a crash, the watchdog - the holders carry on, and the new
program connects to each one again. That is step 07's "reads the list and
adopts every run whose process is still alive", and it is why this file uses
only the standard library and changes rarely: a holder runs the code it
started with for as long as its run lasts.

Frames on ``ctl.sock``, in both directions: one byte of type, four bytes of
length (big-endian), then the payload.

    from the program   d  bytes to type into the terminal
                       w  resize, JSON {"cols": c, "rows": r}
                       k  signal the command, JSON {"signal": 15}
    from the holder    h  hello, JSON {pid, child, cols, rows, started, log}
                       o  bytes the terminal printed
                       x  the command ended, JSON {code, signal, at}

``log`` in the hello is how many bytes ``tty.log`` held when the controller
connected. Every ``o`` frame after it is the next bytes of that file, so a
controller that was away can read what it missed from the file.
"""
from __future__ import annotations

import argparse
import errno
import fcntl
import json
import os
import selectors
import signal
import socket
import struct
import sys
import termios
import time
import traceback

from . import runprocs

HEADER = struct.Struct(">cI")
#: Largest frame the program may send. Anything bigger is a broken controller.
MAX_FRAME = 4 * 1024 * 1024
#: Bytes queued for a controller that is not reading, before it is dropped.
#: The terminal must never wait on the program: a dropped controller comes
#: back and reads what it missed from tty.log.
MAX_BACKLOG = 8 * 1024 * 1024
#: After the command exits, how long to keep reading what it printed last.
DRAIN_FOR = 0.5
#: After a polite stop, how long before the command is killed.
KILL_AFTER = 10.0

# -- the box a run's processes live in ---------------------------------------
#
# Everything a run starts has to end with it, and following "who started whom"
# is not enough to make that true. A process can call setsid() and cut itself
# loose from its parent, which is not an accident or a trick: it is what every
# backgrounded command does on purpose, so that it survives the shell that
# launched it. Signalling the child, or even the child's whole process group,
# never reaches those.
#
# On 19 September 2026 run f9c548c7 was closed to make room while it had six
# processes running behind it: two copies of Rouh and four stand-in servers,
# started to test what Rouh says out loud. Every one had cut itself loose, so
# the shutdown reached none of them, and they were still there hours later
# holding 400 MB and six ports, orphaned to init, with nothing left alive that
# knew they existed.
#
# A cgroup cannot be escaped that way. Every descendant of a process in one is
# in it too, whatever it does about its parent, and one write to `cgroup.kill`
# ends all of them at once with no PID to race against.
#
# It is best effort on purpose. Without `Delegate=yes` on the service there is
# nowhere to make one, and a run that cannot have a box must still run exactly
# as it did before rather than refuse to start.

CGROUP_ROOT = "/sys/fs/cgroup"

#: How long to wait for the kernel to empty a killed cgroup before giving up on
#: taking the directory away. The kill itself is immediate; the directory can
#: only go once the last process in it has been reaped.
BOX_GONE_BY = 1.0

# -- and where there is no box ------------------------------------------------
#
# In the containers every Rouh instance runs there is never one: the worker is
# an unprivileged container with /sys/fs/cgroup read-only, and the stack's
# walls are not taken down to change that (runprocs.py has the whole of why).
# There the holder keeps the box by hand instead: it finds the run's processes
# in /proc, by parentage and by the ONE_RUN mark in their environment, every
# WATCH_EVERY seconds; it ends the run when they hold more than the run's
# memory limit between them; and it ends every one of them, detached ones
# included, when the run ends. The server makes its box and never reaches this.

#: Seconds between two looks at a run's processes, where there is no box.
WATCH_EVERY = 2.0


def own_cgroup() -> str | None:
    """The cgroup this process is in, as a path, or None if it cannot be read."""
    try:
        with open("/proc/self/cgroup", "r", encoding="utf-8") as fh:
            for line in fh:
                # cgroup v2 says it in one line, "0::<path>". A machine still on
                # v1 has no cgroup.kill to write to, so it gets no box.
                if line.startswith("0::"):
                    return os.path.join(CGROUP_ROOT, line.strip()[3:].lstrip("/"))
    except OSError:
        pass
    return None


def frame(kind: bytes, payload: bytes = b"") -> bytes:
    return HEADER.pack(kind, len(payload)) + payload


def set_size(fd: int, cols: int, rows: int) -> None:
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


class Holder:
    def __init__(self, folder: str, argv: list[str], *, cols: int = 120, rows: int = 40,
                 cwd: str | None = None) -> None:
        self.folder = folder
        self.argv = argv
        self.cols = max(20, min(int(cols), 1000))
        self.rows = max(5, min(int(rows), 500))
        self.cwd = cwd
        self.child = 0
        self.master = -1
        self.log = None
        self.logged = 0
        self.started = time.time()
        self.sel = selectors.DefaultSelector()
        self.listener: socket.socket | None = None
        self.controller: socket.socket | None = None
        self.inbuf = bytearray()
        self.outbuf = bytearray()
        self.pending_input = bytearray()
        self.exit_status: tuple[int | None, int | None] | None = None
        self.exited_at: float | None = None
        self.term_at: float | None = None
        self.master_open = True
        self.wake_r, self.wake_w = os.pipe()
        #: This run's own cgroup, or None where one could not be made. Only the
        #: command and its descendants go in it; the holder stays where it was,
        #: so emptying the box never reaches the holder itself.
        self.box: str | None = None
        #: Where there is no box, the run's processes kept track of by hand
        #: (runprocs.py), and the memory limit they are held to; 0 is none.
        self.procs: runprocs.Processes | None = None
        self.limit = 0
        self.watched_at = 0.0
        #: Why the holder ended the run itself, in a sentence, for exit.json.
        self.over_memory = ""
        #: When the run's processes, told to go, are killed if still there.
        self.kill_procs_at: float | None = None

    # -- start --------------------------------------------------------------

    def _ceiling(self, box: str) -> None:
        """Write this run's memory limit onto its own box, if the box will take one.

        ``memory.high`` first and ``memory.max`` above it: the kernel answers
        ``high`` by reclaiming hard and making the run itself wait, which a run
        that is merely busy rides out, and only a run that will not come down
        reaches ``max`` and is killed inside its own box. The service, the
        program and the run beside it are then never what dies for it.

        On this server it writes nothing, because there is no memory controller
        on a run's box to write to and there cannot be one while the service's
        own cgroup has to stay startable. ``reaper.py`` has the whole account,
        under "Why there is no per-run memory ceiling", and what it would take.
        This stays because it is right, it costs one failed open per run, and it
        starts working by itself the day a box is accounted.
        """
        ceiling = _memory_limit()
        if not ceiling:
            return
        for name, value in (("memory.high", int(ceiling * 0.9)), ("memory.max", ceiling)):
            try:
                with open(os.path.join(box, name), "w", encoding="utf-8") as fh:
                    fh.write(str(value))
            except OSError:
                return              # no controller here: the service's limit stands

    def _make_box(self) -> None:
        """Make this run's cgroup, if this machine and this service allow one."""
        own = own_cgroup()
        if not own or not os.path.isdir(own):
            return
        if not os.path.exists(os.path.join(own, "cgroup.kill")):
            return                      # too old a kernel to empty a box at all
        box = os.path.join(own, "run-" + os.path.basename(self.folder.rstrip("/")))
        try:
            os.makedirs(box, exist_ok=True)
            # A box that cannot be written to is worse than none: the command
            # would never join it and the kill at the end would find it empty
            # while the real processes carried on somewhere else.
            os.close(os.open(os.path.join(box, "cgroup.procs"), os.O_WRONLY))
        except OSError:
            return
        self._ceiling(box)
        self.box = box

    def _empty_the_box(self) -> None:
        """Kill whatever is still in this run's cgroup, then take it away.

        This is the one shutdown that a process cannot escape by cutting itself
        loose from its parent.
        """
        box, self.box = self.box, None
        if not box:
            return
        try:
            with open(os.path.join(box, "cgroup.kill"), "w", encoding="utf-8") as fh:
                fh.write("1")
        except OSError:
            return
        # The kill lands at once; the directory only goes when the last process
        # in it has been reaped, which is a moment later.
        deadline = time.monotonic() + BOX_GONE_BY
        while True:
            try:
                os.rmdir(box)
                return
            except OSError:
                if time.monotonic() >= deadline:
                    return
                time.sleep(0.02)

    def start(self) -> None:
        os.makedirs(self.folder, exist_ok=True)
        self.log = open(os.path.join(self.folder, "tty.log"), "ab", buffering=0)
        self.logged = self.log.tell()
        self._make_box()
        master, slave = os.openpty()
        set_size(slave, self.cols, self.rows)
        pid = os.fork()
        if pid == 0:  # the command
            try:
                os.setsid()
                # Into the box before anything is executed, so that everything
                # this command goes on to start is born inside it. Joining here
                # rather than from the parent leaves no window in which the
                # command is running and not yet in its box.
                if self.box:
                    fd = os.open(os.path.join(self.box, "cgroup.procs"), os.O_WRONLY)
                    os.write(fd, str(os.getpid()).encode())
                    os.close(fd)
                fcntl.ioctl(slave, termios.TIOCSCTTY, 0)
                for fd in (0, 1, 2):
                    os.dup2(slave, fd)
                os.closerange(3, 1024)
                for sig in (signal.SIGPIPE, signal.SIGINT, signal.SIGTERM, signal.SIGHUP,
                            signal.SIGCHLD, signal.SIGQUIT):
                    signal.signal(sig, signal.SIG_DFL)
                if self.cwd:
                    os.chdir(self.cwd)
                os.execvp(self.argv[0], self.argv)
            except BaseException as exc:  # pragma: no cover - only in the child
                try:
                    os.write(2, f"one holder: could not start {self.argv[0]}: {exc}\r\n".encode())
                finally:
                    os._exit(127)
        os.close(slave)
        self.child = pid
        self.master = master
        if not self.box:
            self.procs = runprocs.Processes(os.path.basename(self.folder.rstrip("/")), pid)
            self.limit = _memory_limit()
        os.set_blocking(master, False)

        sock_path = os.path.join(self.folder, "ctl.sock")
        try:
            os.unlink(sock_path)
        except FileNotFoundError:
            pass
        old = os.umask(0o177)
        try:
            self.listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.listener.bind(sock_path)
        finally:
            os.umask(old)
        self.listener.listen(4)
        self.listener.setblocking(False)

        _write_json(os.path.join(self.folder, "holder.json"), {
            "pid": os.getpid(), "child": pid, "cols": self.cols, "rows": self.rows,
            "started": self.started, "argv0": os.path.basename(self.argv[0]),
        })

        signal.signal(signal.SIGCHLD, lambda *_: None)
        signal.signal(signal.SIGTERM, self._on_term)
        signal.signal(signal.SIGHUP, signal.SIG_IGN)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGPIPE, signal.SIG_IGN)
        os.set_blocking(self.wake_w, False)
        signal.set_wakeup_fd(self.wake_w)

        self.sel.register(self.master, selectors.EVENT_READ, "master")
        self.sel.register(self.listener, selectors.EVENT_READ, "listen")
        self.sel.register(self.wake_r, selectors.EVENT_READ, "wake")

    def _on_term(self, *_: object) -> None:
        # Someone stopped the holder itself. Pass it on and finish properly.
        self._signal_child(signal.SIGTERM)
        self.term_at = time.monotonic()

    # -- the loop -----------------------------------------------------------

    def run(self) -> int:
        while True:
            self._reap()
            if self.exit_status is not None:
                if not self.master_open or time.monotonic() - (self.exited_at or 0) > DRAIN_FOR:
                    break
            if self.term_at and time.monotonic() - self.term_at > KILL_AFTER:
                self._signal_child(signal.SIGKILL)
                self.term_at = None
            self._watch()
            for key, mask in self.sel.select(timeout=0.25):
                try:
                    self._handle(key, mask)
                except Exception:
                    # The holder must outlive its own bugs: if it dies, its
                    # run dies with it. A failure is written to holder.log,
                    # and a controller that caused one is let go; the program
                    # reconnects.
                    traceback.print_exc()
                    if key.data == "ctl":
                        self._drop_controller()
        return self._finish()

    def _handle(self, key: selectors.SelectorKey, mask: int) -> None:
        what = key.data
        if what == "master":
            # Unless this same round hung the terminal up (_refused).
            if self.master_open:
                self._read_master()
        elif what == "listen":
            self._accept()
        elif what == "ctl":
            # One select can report the controller after another event has
            # already let it go: on 14 September the terminal's output hit a
            # closed controller, dropped it, and the same round then read
            # from it, and the holder died with its run. So a report about a
            # controller that is no longer the current one is ignored.
            if key.fileobj is not self.controller:
                return
            if mask & selectors.EVENT_READ:
                self._read_controller()
            if mask & selectors.EVENT_WRITE:
                self._flush_controller()
        elif what == "wake":
            try:
                os.read(self.wake_r, 512)
            except OSError:
                pass
        elif what == "master-write":
            self._flush_input()

    def _reap(self) -> None:
        if self.exit_status is not None or not self.child:
            return
        try:
            pid, status = os.waitpid(self.child, os.WNOHANG)
        except ChildProcessError:
            pid, status = self.child, 0
        if pid == 0:
            return
        code = os.WEXITSTATUS(status) if os.WIFEXITED(status) else None
        sig = os.WTERMSIG(status) if os.WIFSIGNALED(status) else None
        self.exit_status = (code, sig)
        self.exited_at = time.monotonic()

    def _read_master(self) -> None:
        while True:
            try:
                data = os.read(self.master, 65536)
            except BlockingIOError:
                return
            except OSError as exc:
                if exc.errno == errno.EIO:  # every copy of the terminal's other end is closed
                    self._close_master()
                    return
                raise
            if not data:
                self._close_master()
                return
            self.log.write(data)
            self.logged += len(data)
            self._to_controller(b"o", data)

    def _close_master(self) -> None:
        if self.master_open:
            self.master_open = False
            try:
                self.sel.unregister(self.master)
            except (KeyError, ValueError):
                pass

    def _accept(self) -> None:
        try:
            conn, _ = self.listener.accept()
        except BlockingIOError:
            return
        # One controller at a time. A new one is the program after a restart,
        # and the old connection is from the program that died.
        self._drop_controller()
        conn.setblocking(False)
        self.controller = conn
        self.inbuf.clear()
        self.outbuf.clear()
        self.sel.register(conn, selectors.EVENT_READ, "ctl")
        hello = {"pid": os.getpid(), "child": self.child, "cols": self.cols, "rows": self.rows,
                 "started": self.started, "log": self.logged}
        self._to_controller(b"h", json.dumps(hello).encode())
        if self.exit_status is not None:
            self._send_exit()

    def _drop_controller(self) -> None:
        if self.controller is None:
            return
        try:
            self.sel.unregister(self.controller)
        except (KeyError, ValueError):
            pass
        try:
            self.controller.close()
        except OSError:
            pass
        self.controller = None
        self.outbuf.clear()
        self.inbuf.clear()

    def _to_controller(self, kind: bytes, payload: bytes) -> None:
        if self.controller is None:
            return
        self.outbuf += frame(kind, payload)
        if len(self.outbuf) > MAX_BACKLOG:
            self._drop_controller()
            return
        self._flush_controller()

    def _flush_controller(self) -> None:
        if self.controller is None:
            return
        try:
            while self.outbuf:
                sent = self.controller.send(self.outbuf)
                if not sent:
                    break
                del self.outbuf[:sent]
        except BlockingIOError:
            pass
        except OSError:
            self._drop_controller()
            return
        events = selectors.EVENT_READ | (selectors.EVENT_WRITE if self.outbuf else 0)
        try:
            self.sel.modify(self.controller, events, "ctl")
        except (KeyError, ValueError):
            pass

    def _read_controller(self) -> None:
        if self.controller is None:
            return
        try:
            data = self.controller.recv(65536)
        except BlockingIOError:
            return
        except OSError:
            data = b""
        if not data:
            self._drop_controller()
            return
        self.inbuf += data
        while len(self.inbuf) >= HEADER.size:
            kind, size = HEADER.unpack_from(self.inbuf)
            if size > MAX_FRAME:
                self._drop_controller()
                return
            if len(self.inbuf) < HEADER.size + size:
                break
            payload = bytes(self.inbuf[HEADER.size:HEADER.size + size])
            del self.inbuf[:HEADER.size + size]
            self._command(kind, payload)
            if self.controller is None:
                return

    def _command(self, kind: bytes, payload: bytes) -> None:
        if kind == b"d":
            if self.master_open:
                self.pending_input += payload
                self._flush_input()
        elif kind == b"w":
            try:
                size = json.loads(payload)
                self.cols = max(20, min(int(size["cols"]), 1000))
                self.rows = max(5, min(int(size["rows"]), 500))
                if self.master_open:
                    set_size(self.master, self.cols, self.rows)
            except (ValueError, KeyError, TypeError, OSError):
                pass
        elif kind == b"k":
            try:
                sig = int(json.loads(payload).get("signal", signal.SIGTERM))
            except (ValueError, TypeError, AttributeError):
                sig = signal.SIGTERM
            self._signal_child(sig)
            if sig == signal.SIGTERM:
                self.term_at = time.monotonic()

    def _flush_input(self) -> None:
        if not self.master_open:
            self.pending_input.clear()
            return
        try:
            while self.pending_input:
                written = os.write(self.master, self.pending_input)
                del self.pending_input[:written]
        except BlockingIOError:
            pass
        except OSError:
            self.pending_input.clear()
        # Keep asking to write while typing is queued, and stop asking once not.
        try:
            if self.pending_input:
                self.sel.modify(self.master, selectors.EVENT_READ | selectors.EVENT_WRITE, "master")
            else:
                self.sel.modify(self.master, selectors.EVENT_READ, "master")
        except (KeyError, ValueError):
            pass

    def _signal_child(self, sig: int) -> None:
        if self.child and self.exit_status is None:
            try:
                os.kill(self.child, sig)
            except ProcessLookupError:
                pass
            except PermissionError:
                self._refused(sig)

    def _refused(self, sig: int) -> None:
        """The kernel would not let this holder signal its own command.

        The command is a sudo that becomes the run's user, and a signal
        reaches it only while sudo's real user id is still the holder's own,
        which is true of sudo and sudo-rs as this machine has them (measured
        on 3 October 2026: SIGTERM through the holder ended a stand-in agent,
        and SIGKILL ended one that ignored it). A sudo that changed that would
        turn every stop into nothing, and until then this was swallowed in
        silence, so a run asked to end carried on with no word anywhere.

        So it is written to holder.log, and an ask to end is carried out the
        one way that needs no permission: the terminal is hung up. Closing
        the pseudo-terminal's master makes the kernel send SIGHUP to the
        session it controls, which is the command and everything it started
        in the foreground, and Claude Code leaves on a hang-up.
        """
        try:
            name = signal.Signals(sig).name
        except ValueError:
            name = str(sig)
        sys.stderr.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} holder: not allowed to send "
                         f"{name} to the command (pid {self.child})")
        if sig not in (signal.SIGTERM, signal.SIGKILL, signal.SIGHUP) or not self.master_open:
            sys.stderr.write("\n")
            sys.stderr.flush()
            return
        sys.stderr.write("; hanging up its terminal instead\n")
        sys.stderr.flush()
        self._close_master()
        try:
            os.close(self.master)
        except OSError:
            pass
        # Never closed twice: the number may by then belong to something else.
        self.master = -1

    # -- the run's memory, where there is no box -----------------------------

    def _watch(self) -> None:
        """Look at the run's processes now and then, and end the run over its limit.

        What the kernel does at ``memory.max`` on a box, done from outside it:
        the run is told on its own screen, and every process of it is sent
        SIGTERM so that it can go tidily; whatever is still there
        ``runprocs.GRACE`` seconds later is killed. The command is among them,
        so the run ends, and ``exit.json`` says why, for the program to say on.
        """
        procs = self.procs
        if procs is None or self.exit_status is not None:
            return
        now = time.monotonic()
        if self.kill_procs_at is not None and now >= self.kill_procs_at:
            self.kill_procs_at = None
            procs.signal(signal.SIGKILL)
        if not self.limit or self.over_memory or now - self.watched_at < WATCH_EVERY:
            return
        self.watched_at = now
        used = procs.memory()
        if used <= self.limit:
            return
        self.over_memory = (f"was ended for holding {_mb(used)} of memory, over the "
                            f"{_mb(self.limit)} one run may hold (ONE_RUN_MEMORY_MAX)")
        sys.stderr.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} holder: the run "
                         f"{self.over_memory}; ending all of it\n")
        sys.stderr.flush()
        said = f"\r\n[one] This run {self.over_memory}.\r\n".encode()
        self.log.write(said)
        self.logged += len(said)
        self._to_controller(b"o", said)
        procs.signal(signal.SIGTERM)
        self.kill_procs_at = now + runprocs.GRACE

    def _end_the_procs(self) -> None:
        """Where there is no box: end every process the run still has, detached or not."""
        if self.procs is None:
            return
        left = self.procs.end()
        if left:
            sys.stderr.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} holder: ended {left} "
                             f"process(es) the run left behind\n")
            sys.stderr.flush()

    # -- the end ------------------------------------------------------------

    def _exit_info(self) -> dict:
        code, sig = self.exit_status or (None, None)
        info = {"code": code, "signal": sig, "at": time.time()}
        if self.over_memory:
            info["over_memory"] = self.over_memory
        return info

    def _send_exit(self) -> None:
        self._to_controller(b"x", json.dumps(self._exit_info()).encode())

    def _finish(self) -> int:
        # Whatever it printed last is the most useful line of the whole log.
        if self.master_open:
            self._read_master()
        # The command has gone. Anything it left behind goes with it, including
        # what cut itself loose and would otherwise outlive everything that
        # knew it was there.
        self._empty_the_box()
        self._end_the_procs()
        _write_json(os.path.join(self.folder, "exit.json"), self._exit_info())
        self._send_exit()
        if self.controller is not None:
            deadline = time.monotonic() + 2.0
            while self.outbuf and time.monotonic() < deadline:
                self._flush_controller()
                time.sleep(0.02)
        self._drop_controller()
        try:
            os.unlink(os.path.join(self.folder, "ctl.sock"))
        except OSError:
            pass
        if self.log is not None:
            self.log.close()
        try:
            os.close(self.master)
        except OSError:
            pass
        return 0


def _memory_limit() -> int:
    """The most memory one run may hold, in bytes, as the program passed it; 0 is none."""
    try:
        return max(0, int(os.environ.get("ONE_RUN_MEMORY_MAX", "").strip() or 0))
    except ValueError:
        return 0


def _mb(size: int) -> str:
    return f"{size / 1048576:.0f} MB"


def _write_json(path: str, data: dict) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    os.replace(tmp, path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Hold one run's terminal.")
    parser.add_argument("--dir", required=True, help="the run's folder")
    parser.add_argument("--cols", type=int, default=120)
    parser.add_argument("--rows", type=int, default=40)
    parser.add_argument("--cwd", default=None)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        parser.error("no command to run")
    holder = Holder(args.dir, command, cols=args.cols, rows=args.rows, cwd=args.cwd)
    holder.start()
    return holder.run()


if __name__ == "__main__":
    sys.exit(main())
