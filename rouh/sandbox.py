"""Putting run_command inside a box the kernel holds shut.

`run_command` has been read-only by rule since it existed: a list of allowed
commands, a refusal for redirection and chaining, and a check on the flags of
the few commands that can write with the right ones. That is a regular
expression believing a promise. It has held, and it will hold right up until
somebody finds the spelling nobody thought of.

This is the same promise made by the kernel instead. Every stage of a pipeline
runs inside bubblewrap with the whole filesystem bound read-only and the
network taken away, so a command that tries to write gets EROFS from the
kernel and a command that tries to reach the internet finds no route. The
pattern rules stay exactly where they are: they are what makes a refusal say
something useful, and two locks on one door is the point.

What is deliberately not taken away
-----------------------------------

The process table, because `ps` is one of the allowed commands and a sandbox
that makes it print nothing has broken the tool to protect it. The mounts,
for `df`. /proc, for everything that reads it. This box is about writing and
about the network; it is not a jail, and nothing here pretends it is one
against a hostile program that already got in.

/dev is replaced with bubblewrap's own small one rather than bound read-only,
because a great many programs write to /dev/null on their way past.

Where bubblewrap cannot run: Landlock
-------------------------------------

Bubblewrap needs unprivileged user namespaces, and a container started with
Docker's own syscall filter is refused them (`unshare` and a `clone` that asks
for a namespace are kept for CAP_SYS_ADMIN), which is how every Rouh instance
runs: in the worker of deploy/stack/compose.yml, with no capability at all and
a stack check that refuses any other filter. Proved on 30 October 2026 (task
139, step 139-14): bubblewrap in that worker says "No permissions to create a
new namespace", and Landlock, asked for in the same worker, answers.

Landlock is the kernel's own unprivileged lock (Linux 5.13 for files, 6.7 for
TCP), allowed by Docker's filter and needing no capability, and it holds the
same two things: a process that restricted itself, and everything it starts,
may write no file but /dev/null and may open no TCP connection, refused by the
kernel with EACCES. So where bubblewrap would not run, each stage starts
through this very file (`python -I sandbox.py --landlock -- argv`), which locks
itself and then becomes the command. A kernel too old to close TCP does not
count as a box: the network is half of the promise.

When there is neither
---------------------

It says so, loudly, once, at start-up, and carries on with the rules alone.
The alternative is a machine where run_command stops working because a package
is missing, which is a worse failure than the one it is protecting against.
`ROUH_SANDBOX=required` turns that round for anybody who would rather have
the refusal.
"""
from __future__ import annotations

import ctypes
import logging
import os
import shutil
import subprocess
import sys

log = logging.getLogger("rouh.sandbox")

#: The program that does it. Not a library: a setuid-less, dependency-free
#: binary that every distribution has, and the one the request named.
BWRAP = "bwrap"

#: What `ROUH_SANDBOX` may say.
#:
#: auto      use it when it is here, say so when it is not, carry on either way
#: required  use it, and refuse to run anything at all when it is not here
#: off       do not use it; the pattern rules are the whole of the check
MODES = ("auto", "required", "off")

#: What a command is told when the sandbox is required and is not there.
NO_SANDBOX = ("Refused. This machine is set to run commands inside a sandbox "
              "(ROUH_SANDBOX=required) and neither bubblewrap nor the kernel's "
              "Landlock will hold one here, so nothing was run.")

# Landlock, from <linux/landlock.h>. The three calls have the same numbers on
# every architecture Rouh runs on (x86_64 and arm64 alike).
_LL_CREATE, _LL_ADD_RULE, _LL_RESTRICT = 444, 445, 446
_LL_VERSION = 1 << 0                 # landlock_create_ruleset(NULL, 0, this): the ABI
_LL_RULE_PATH_BENEATH = 1
_PR_SET_NO_NEW_PRIVS = 38
_FS_WRITE_FILE = 1 << 1
#: Everything that changes the filesystem, by the ABI that added it. Reading
#: and running are not handled, so they stay allowed everywhere.
_FS_CHANGES = {1: (1 << 1) | (1 << 4) | (1 << 5) | (1 << 6) | (1 << 7) | (1 << 8)
                  | (1 << 9) | (1 << 10) | (1 << 11) | (1 << 12),
               2: 1 << 13,   # refer: linking or renaming across directories
               3: 1 << 14}   # truncate
_FS_TRUNCATE = 1 << 14
_NET_BIND_TCP, _NET_CONNECT_TCP = 1 << 0, 1 << 1
#: Since ABI 6: no abstract unix socket outside the box, and no signal to a
#: process outside it, so a command cannot reach or stop the program that ran it.
_SCOPE_ABSTRACT_UNIX, _SCOPE_SIGNAL = 1 << 0, 1 << 1
#: The first ABI that can close TCP.
LANDLOCK_NET_ABI = 4
#: What the launcher exits with when it could not lock itself. It never runs
#: the command unlocked.
LANDLOCK_FAILED = 126


def mode_of(cfg) -> str:
    raw = str(getattr(cfg, "sandbox", "auto") or "auto").strip().lower()
    return raw if raw in MODES else "auto"


def available() -> str:
    """Where bubblewrap is, or an empty string."""
    return shutil.which(BWRAP) or ""


def works(timeout: float = 10.0, *, network: bool = False) -> bool:
    """Whether a box really holds here, bubblewrap's or Landlock's, rather
    than merely being installed."""
    return bwrap_works(timeout) or landlock_works(timeout, network=network)


def bwrap_works(timeout: float = 10.0) -> bool:
    """Whether bubblewrap really runs here, rather than merely being installed.

    Bubblewrap needs unprivileged user namespaces, and there are machines
    where it is on the disk and refused by the kernel. Asking it to echo is
    cheaper than finding out from a person's first question.
    """
    where = available()
    if not where:
        return False
    try:
        done = subprocess.run(argv_for(["/bin/true"], cwd="/"),
                              capture_output=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


def _libc():
    libc = ctypes.CDLL(None, use_errno=True)
    libc.syscall.restype = ctypes.c_long
    return libc


def landlock_abi() -> int:
    """The Landlock ABI this kernel offers, or 0 when it offers none (or is not Linux)."""
    if not sys.platform.startswith("linux"):
        return 0
    try:
        abi = _libc().syscall(_LL_CREATE, None, ctypes.c_size_t(0), ctypes.c_uint32(_LL_VERSION))
    except (OSError, AttributeError):
        return 0
    return int(abi) if abi > 0 else 0


def landlock_works(timeout: float = 10.0, *, network: bool = False) -> bool:
    """Whether a stage started through the launcher really runs here, locked.

    Only on a kernel that can close TCP too, unless the network is allowed:
    a box that keeps the files and leaves the network open is half of one.
    """
    abi = landlock_abi()
    if abi < 1 or (not network and abi < LANDLOCK_NET_ABI):
        return False
    try:
        done = subprocess.run(landlock_argv(["/bin/true"], network=network),
                              capture_output=True, timeout=timeout, cwd="/")
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


def landlock_argv(argv: list[str], *, network: bool = False) -> list[str]:
    """`argv`, started through this file, which locks itself and becomes it."""
    return [sys.executable, "-I", os.path.abspath(__file__), "--landlock",
            *(["--network"] if network else []), "--", *argv]


def landlock_self(*, network: bool = False) -> int:
    """Lock this process, and all it starts, out of every change to the files
    but writing /dev/null, and out of TCP unless `network`. Returns the ABI it
    used; raises OSError when the kernel would not take it."""
    abi = landlock_abi()
    if abi < 1:
        raise OSError("this kernel has no Landlock")
    if not network and abi < LANDLOCK_NET_ABI:
        raise OSError(f"this kernel's Landlock (ABI {abi}) cannot close the network")
    libc = _libc()
    fs = sum(bits for since, bits in _FS_CHANGES.items() if abi >= since)
    net = (_NET_BIND_TCP | _NET_CONNECT_TCP) if (abi >= LANDLOCK_NET_ABI and not network) else 0
    scoped = (_SCOPE_ABSTRACT_UNIX | _SCOPE_SIGNAL) if abi >= 6 else 0
    fields = [fs] + ([net] if abi >= LANDLOCK_NET_ABI else []) + ([scoped] if abi >= 6 else [])
    attr = (ctypes.c_uint64 * len(fields))(*fields)

    def call(*args):
        got = libc.syscall(*args)
        if got < 0:
            err = ctypes.get_errno()
            raise OSError(err, os.strerror(err))
        return got

    ruleset = call(_LL_CREATE, ctypes.byref(attr), ctypes.c_size_t(ctypes.sizeof(attr)),
                   ctypes.c_uint32(0))
    try:
        # /dev/null stays writable: a great many programs write to it on their way past.
        null = os.open("/dev/null", os.O_PATH | os.O_CLOEXEC)
        try:
            # struct landlock_path_beneath_attr is packed: a u64 and an s32, twelve bytes.
            rule = (ctypes.c_uint64(_FS_WRITE_FILE | (_FS_TRUNCATE if abi >= 3 else 0)).value
                    .to_bytes(8, sys.byteorder) + null.to_bytes(4, sys.byteorder, signed=True))
            buf = ctypes.create_string_buffer(rule, len(rule))
            call(_LL_ADD_RULE, ctypes.c_int(ruleset), ctypes.c_int(_LL_RULE_PATH_BENEATH),
                 buf, ctypes.c_uint32(0))
        finally:
            os.close(null)
        if libc.prctl(_PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0:
            raise OSError(ctypes.get_errno(), "no_new_privs was refused")
        call(_LL_RESTRICT, ctypes.c_int(ruleset), ctypes.c_uint32(0))
    finally:
        os.close(ruleset)
    return abi


def _launch(args: list[str]) -> None:
    """`sandbox.py --landlock [--network] -- argv`: lock, then become argv."""
    network = "--network" in args[:args.index("--")] if "--" in args else False
    argv = args[args.index("--") + 1:] if "--" in args else []
    if not argv:
        sys.stderr.write("sandbox: nothing to run\n")
        raise SystemExit(LANDLOCK_FAILED)
    try:
        landlock_self(network=network)
    except OSError as exc:
        sys.stderr.write(f"Refused. The sandbox could not be closed, so nothing was run: {exc}\n")
        raise SystemExit(LANDLOCK_FAILED)
    try:
        os.execvp(argv[0], argv)
    except OSError as exc:
        sys.stderr.write(f"{argv[0]}: {exc.strerror}\n")
        raise SystemExit(127)


def argv_for(argv: list[str], *, cwd: str = "/", network: bool = False) -> list[str]:
    """`argv`, wrapped so it can read everything and change nothing.

    The whole filesystem read-only, a fresh small /dev, no network unless it is
    asked for, no controlling terminal, and the sandbox dying with this process
    so a command that outlives its turn cannot outlive Rouh.
    """
    box = [
        BWRAP,
        # Everything readable, nothing writable. This is the whole feature.
        "--ro-bind", "/", "/",
        # bubblewrap's own /dev rather than the host's bound read-only: a great
        # many programs write to /dev/null on their way past, and a read-only
        # one turns that into a failure with no explanation.
        "--dev", "/dev",
        # No terminal to talk to, so nothing can push characters back into the
        # one Rouh is running in.
        "--new-session",
        # If this process goes, the sandbox goes. A command cannot outlive the
        # turn that started it.
        "--die-with-parent",
    ]
    if not network:
        box += ["--unshare-net"]
    if cwd:
        box += ["--chdir", cwd]
    return box + ["--", *argv]


class Sandbox:
    """What this machine can do, worked out once and said once.

    Checked at start-up rather than on each call: `works()` runs a program, and
    running one on every pipeline stage would be the slowest part of a spoken
    turn.
    """

    def __init__(self, cfg=None, *, mode: str = "", network: bool = False):
        self.mode = mode or (mode_of(cfg) if cfg is not None else "auto")
        self.network = bool(network if cfg is None
                            else getattr(cfg, "sandbox_network", False))
        self.where = ""
        #: "bwrap" or "landlock" once one is found to hold here, else "".
        self.kind = ""
        self.usable = False
        self.why = "not looked yet"

    def look(self) -> "Sandbox":
        """Find out, and say what was found. Safe to call more than once."""
        if self.mode == "off":
            self.usable, self.why = False, "turned off (ROUH_SANDBOX=off)"
            return self
        self.kind, self.usable = "", False
        self.where = available()
        if self.where and bwrap_works():
            self.kind, self.usable = "bwrap", True
            self.why = f"{self.where}, filesystem read-only" + (
                ", network allowed" if self.network else ", no network")
            return self
        bwrap_said = (f"{BWRAP} is installed at {self.where} but would not run here, "
                      "which usually means unprivileged user namespaces are refused"
                      if self.where else f"{BWRAP} is not installed")
        abi = landlock_abi()
        if landlock_works(network=self.network):
            self.kind, self.usable = "landlock", True
            self.where = f"Landlock ABI {abi}"
            self.why = f"the kernel's Landlock (ABI {abi}), filesystem read-only" + (
                ", network allowed" if self.network else ", no network")
            return self
        landlock_said = ("this kernel has no Landlock" if abi < 1 else
                         f"this kernel's Landlock (ABI {abi}) cannot close the network"
                         if abi < LANDLOCK_NET_ABI and not self.network else
                         f"Landlock (ABI {abi}) would not start here")
        self.why = f"{bwrap_said}, and {landlock_said}"
        return self

    def said(self) -> str:
        """One line for the start-up log."""
        if self.usable:
            return f"commands run sandboxed: {self.why}"
        if self.mode == "required":
            return (f"commands WILL NOT RUN: the sandbox is required and {self.why}")
        return (f"commands are not sandboxed: {self.why}. They are still held to "
                "the read-only command rules, which is what it was before this "
                "existed. Install bubblewrap, or run on Linux 6.7 or later for Landlock, "
                "to have the kernel hold them too")

    def refusal(self) -> str:
        """What to say instead of running anything, or nothing if it may run."""
        return NO_SANDBOX if (self.mode == "required" and not self.usable) else ""

    def wrap(self, argv: list[str], *, cwd: str = "/") -> list[str]:
        if not self.usable:
            return list(argv)
        if self.kind == "landlock":
            return landlock_argv(argv, network=self.network)
        return argv_for(argv, cwd=cwd, network=self.network)

    def state(self) -> dict:
        """What server_health says about it, and what the worker writes down for the core."""
        return {"on": self.usable, "mode": self.mode, "kind": self.kind, "said": self.said()}


#: The one this process uses. Filled in at start-up by `runtime.py`; until then
#: it is a sandbox that has not looked, which wraps nothing.
current = Sandbox(mode="off")


def use(sandbox: "Sandbox") -> "Sandbox":
    global current
    current = sandbox
    return current


if __name__ == "__main__" and sys.argv[1:2] == ["--landlock"]:
    _launch(sys.argv[2:])
