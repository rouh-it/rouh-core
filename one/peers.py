"""Which run a connection to the program comes from, asked of the kernel, never of the caller.

Every run in the worker works as the one Linux user the program does, so nothing a run can read
- its environment, a file, a socket's path - can tell one run from another: any run can read
another's environment in ``/proc``, and any run can set ``ONE_RUN`` to whatever it likes. What a
run cannot change is its place in the process tree. A process's parent is set by the kernel when
it is born and only ever changes to init when its parent dies, so a process that descends from a
run's holder is that run's, and nothing a run does can make one of its processes descend from
another run's holder. ``ptrace`` is limited to a process's own descendants here
(``kernel.yama.ptrace_scope`` 1), so no run can reach into another run's memory, or the
program's, either.

So for every connection that reaches the program from inside the worker - the control socket
(``SO_PEERCRED`` gives the pid), the program's web port and the run door (``/proc/net/tcp`` gives
the socket, and the processes' open files give its owner) - the program walks the caller's
parents up to the first holder it started, and that is the run. A connection from another
container (Rouh's core, a browser through Rouh) has no process in this namespace at all: a unix
socket says pid 0 for it, and no local socket matches a TCP one. That is "outside".

A process that cut itself loose (``setsid`` and a double fork, ``nohup``) is handed to init and
belongs to no run any more: it is "unknown", and gets nothing that is a run's.

Only the standard library.
"""
from __future__ import annotations

import ipaddress
import os
import socket
import struct

#: What `whose` answers besides a run's id: another container; the program and what it started
#: outside any run; the worker's own start (the program's parents and what they started); a
#: command typed into the container from the machine (``docker exec``, whose top parent is 0);
#: and a process that left its run, or anything else.
OUTSIDE, PROGRAM, SYSTEM, ADMIN, UNKNOWN = "outside", "program", "system", "admin", "unknown"
#: The answers that are not a run.
NOT_RUNS = frozenset({OUTSIDE, PROGRAM, SYSTEM, ADMIN, UNKNOWN})


def _stat(pid: int) -> tuple[int, int] | None:
    """(parent, start time) of one process, or None when it is gone."""
    try:
        with open(f"/proc/{pid}/stat", "rb") as fh:
            rest = fh.read().rpartition(b")")[2].split()
        return int(rest[1]), int(rest[19])
    except (OSError, ValueError, IndexError):
        return None


def started(pid: int) -> int:
    """A process's start time in clock ticks, 0 when it is gone: with the pid, its identity."""
    got = _stat(pid)
    return got[1] if got else 0


def lineage(pid: int, most: int = 64) -> list[int]:
    """The process and each of its parents in turn, up to init (not included)."""
    return _climb(pid, most)[0]


def _climb(pid: int, most: int = 64) -> tuple[list[int], int]:
    """(the lineage, the parent the climb stopped at: 1 for init, 0 for outside this namespace,
    -1 when a process went away on the way)."""
    out = []
    while pid > 1 and len(out) < most:
        out.append(pid)
        got = _stat(pid)
        if got is None:
            return out, -1
        pid = got[0]
    return out, pid


def whose_pid(pid: int, holders: dict[int, tuple[str, int]], program: int | None = None) -> str:
    """The run a process is part of, by its parents: a run's id, `PROGRAM` for the program itself
    and what it started outside any run, or `UNKNOWN`.

    ``holders`` is {holder pid: (run id, the holder's start time)}, from the program's own
    terminals; the start time is checked so a pid used again by another process is not taken for
    the holder that had it.
    """
    program = os.getpid() if program is None else program
    if pid <= 0:
        return OUTSIDE
    chain, top = _climb(pid)
    for p in chain:
        held = holders.get(p)
        if held is not None and (not held[1] or started(p) == held[1]):
            return held[0]
        if p == program:
            return PROGRAM
    if top == 0:
        return ADMIN
    if top == 1 and chain and set(chain) & set(lineage(program)[1:]):
        return SYSTEM
    return UNKNOWN


# --- unix sockets ---------------------------------------------------------------------------

def peer_pid(sock: socket.socket | None) -> int:
    """The pid at the other end of a unix socket, as this namespace sees it: 0 when the peer is in
    another container (or the socket is not a unix one), -1 when it cannot be read."""
    if sock is None or getattr(sock, "family", None) != socket.AF_UNIX:
        return 0
    try:
        raw = sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
    except OSError:
        return -1
    pid, _uid, _gid = struct.unpack("3i", raw)
    return pid


# --- TCP --------------------------------------------------------------------------------------

def _hex_address(text: str) -> tuple[str, int]:
    addr, _, port = text.partition(":")
    raw = bytes.fromhex(addr)
    if len(raw) == 4:
        ip = socket.inet_ntop(socket.AF_INET, raw[::-1])
    else:
        ip = socket.inet_ntop(socket.AF_INET6, b"".join(raw[i:i + 4][::-1] for i in range(0, 16, 4)))
    return ip, int(port, 16)


def _same(a: str, b: str) -> bool:
    try:
        x, y = ipaddress.ip_address(a), ipaddress.ip_address(b)
    except ValueError:
        return a == b
    if getattr(x, "ipv4_mapped", None):
        x = x.ipv4_mapped
    if getattr(y, "ipv4_mapped", None):
        y = y.ipv4_mapped
    return x == y


def tcp_inode(peer: tuple, here: tuple) -> int:
    """The inode of the local socket whose own end is `peer` and whose far end is `here`: the
    caller's side of a connection we accepted, when the caller is in this namespace. 0 if none."""
    peer_ip, peer_port = peer[0], int(peer[1])
    here_ip, here_port = here[0], int(here[1])
    for table in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            with open(table, encoding="ascii") as fh:
                next(fh, None)
                for line in fh:
                    f = line.split()
                    if len(f) < 10:
                        continue
                    try:
                        lip, lport = _hex_address(f[1])
                        rip, rport = _hex_address(f[2])
                    except ValueError:
                        continue
                    if lport == peer_port and rport == here_port and _same(lip, peer_ip) \
                            and _same(rip, here_ip):
                        return int(f[9])
        except OSError:
            continue
    return 0


def pid_of_inode(inode: int, skip: int | None = None) -> int:
    """The first process holding the socket with this inode open, or 0."""
    if not inode:
        return 0
    want = f"socket:[{inode}]"
    skip = os.getpid() if skip is None else skip
    try:
        pids = [int(n) for n in os.listdir("/proc") if n.isdigit()]
    except OSError:
        return 0
    for pid in sorted(pids, reverse=True):     # the newest first: a run's tools are young
        if pid == skip:
            continue
        try:
            with os.scandir(f"/proc/{pid}/fd") as fds:
                for fd in fds:
                    try:
                        if os.readlink(fd.path) == want:
                            return pid
                    except OSError:
                        continue
        except OSError:
            continue
    return 0


def tcp_peer_pid(peer: tuple | None, here: tuple | None) -> int:
    """The pid that opened a TCP connection we accepted, when it is in this namespace, else 0."""
    if not peer or not here:
        return 0
    return pid_of_inode(tcp_inode(peer, here))


__all__ = ["ADMIN", "NOT_RUNS", "OUTSIDE", "PROGRAM", "SYSTEM", "UNKNOWN", "lineage", "peer_pid", "pid_of_inode", "started",
           "tcp_inode", "tcp_peer_pid", "whose_pid"]
