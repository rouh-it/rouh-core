"""A run's processes, found and ended where no cgroup can be had for it.

On the server every run's command is born in a cgroup of its own
(``holder.Holder._make_box``): nothing it starts can leave the box, one write
to ``cgroup.kill`` ends all of it, and a memory limit can be written on it.
In the containers every Rouh instance runs, none of that is there. The worker
is an unprivileged container, ``/sys/fs/cgroup`` is mounted read-only in it,
and nothing in the stack's walls (guard/policy) will ever hand it a writable
cgroup tree: that takes a privileged container, the host's cgroup namespace or
a capability the stack check refuses, and each of those is a wall taken down.

So the holder keeps the box by hand, from ``/proc``, with this file:

- **Which processes are the run's.** Every descendant of its command, found by
  parentage, and every process whose environment carries the run's mark,
  ``ONE_RUN=<id>``, which ``asuser.py`` gives the agent and which everything it
  starts inherits. Parentage is lost the moment a process cuts itself loose
  (``setsid``, a double fork, ``nohup ... &``) and is handed to init, which is
  exactly what a backgrounded server does; the environment is not, because
  ``/proc/<pid>/environ`` is what the process was started with and changing
  its own variables later does not change it. A process that was seen as a
  descendant is remembered too, by its pid and its start time, so one started
  with ``env -i`` is still the run's once it detaches.
- **What they hold.** Each one's own share of the anonymous memory it maps
  (``Pss_Anon`` and ``SwapPss`` in ``smaps_rollup``), which is what the kernel
  cannot take back without killing something. A shared page is split between
  the processes that share it, so eight Chromium processes forked from one are
  not counted eight times over. Page cache is not counted, as the scheduler
  does not count it (``scheduler.memory_in_use`` says why), and neither are
  files in a tmpfs, which belong to no process: the worker's own memory limit
  bounds those.
- **Ending them.** SIGTERM to every one, a moment, then SIGKILL to whatever is
  still there. Everything a run starts in the worker is the worker's one user,
  so a signal reaches all of it.

What this cannot do that a cgroup does: a process that both cuts itself loose
and clears its environment before the holder has seen it once (the holder
looks every two seconds) is not found; and memory is read, not refused, so a
run can be over its limit for up to two seconds before it is ended, where the
kernel would stop it at the page. Neither is something a run does by
accident, and the worker's own limit (``mem_limit`` in the stack file) is the
kernel's ceiling over all of it.

Only the standard library, because the holder imports it.
"""
from __future__ import annotations

import os
import signal
import time

#: The variable every run's environment carries, set to the run's id (asuser.py).
MARK = "ONE_RUN"
#: Seconds between the polite signal and the one that cannot be refused.
GRACE = 3.0


def _stat(pid: str) -> tuple[int, int]:
    """(parent, start time in clock ticks) for one process, out of /proc/<pid>/stat.

    The command name is field 2 and may itself hold spaces and brackets, so the
    line is cut after its last ``)`` before it is split.
    """
    with open(f"/proc/{pid}/stat", "rb") as fh:
        rest = fh.read().rpartition(b")")[2].split()
    return int(rest[1]), int(rest[19])


def mark_of(pid: int | str) -> str:
    """The run this process was started for, by its environment, or "" for none."""
    try:
        with open(f"/proc/{pid}/environ", "rb") as fh:
            raw = fh.read()
    except OSError:
        return ""                   # gone, or not this user's to read
    want = MARK.encode() + b"="
    for item in raw.split(b"\0"):
        if item.startswith(want):
            return item[len(want):].decode("utf-8", "replace")
    return ""


def held(pid: int) -> int:
    """Bytes of anonymous memory this process holds as its own share, or 0 if gone."""
    try:
        with open(f"/proc/{pid}/smaps_rollup", encoding="ascii", errors="replace") as fh:
            fields = dict(line.split(":", 1) for line in fh if ":" in line)
        if "Pss_Anon" in fields:
            return sum(int(fields[name].split()[0]) * 1024
                       for name in ("Pss_Anon", "SwapPss") if name in fields)
    except (OSError, ValueError, IndexError):
        pass
    # A kernel older than 5.9 has no Pss_Anon: what the process maps alone.
    total = 0
    try:
        with open(f"/proc/{pid}/status", encoding="ascii", errors="replace") as fh:
            for line in fh:
                if line.startswith(("RssAnon:", "VmSwap:")):
                    total += int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        return 0
    return total


class Processes:
    """One run's processes, kept track of between looks.

    ``child`` is the run's command, which the holder started. ``run_id`` is the
    mark its environment carries.
    """

    def __init__(self, run_id: str, child: int) -> None:
        self.run_id = run_id
        self.child = child
        #: (pid, start time) of every process seen as the run's, so a pid
        #: reused by something else afterwards is never taken for it.
        self.known: set[tuple[int, int]] = set()
        #: Start times whose mark has been read once: the environment a
        #: process started with never changes, so it is read once per process.
        self._marks: dict[tuple[int, int], str] = {}

    def look(self) -> list[int]:
        """Every process of the run's that is alive now."""
        table: dict[int, tuple[int, int]] = {}
        try:
            names = [n for n in os.listdir("/proc") if n.isdigit()]
        except OSError:
            return []
        for name in names:
            try:
                table[int(name)] = _stat(name)
            except (OSError, ValueError, IndexError):
                continue            # gone between the listing and the read
        children: dict[int, list[int]] = {}
        for pid, (parent, _) in table.items():
            children.setdefault(parent, []).append(pid)
        found: set[int] = set()
        stack = [self.child] if self.child in table else []
        while stack:                # walked, not recursed, each pid once
            pid = stack.pop()
            if pid in found:
                continue
            found.add(pid)
            stack.extend(children.get(pid, ()))
        me = os.getpid()
        for pid, (_, start) in table.items():
            if pid in found or pid == me:
                continue
            key = (pid, start)
            if key in self.known:
                found.add(pid)
                continue
            if key not in self._marks:
                self._marks[key] = mark_of(pid)
            if self._marks[key] == self.run_id:
                found.add(pid)
        alive = {(pid, table[pid][1]) for pid in found}
        self.known = alive
        self._marks = {key: mark for key, mark in self._marks.items() if key[0] in table}
        return sorted(found)

    def memory(self, pids: list[int] | None = None) -> int:
        """Bytes the run holds between all its processes."""
        return sum(held(pid) for pid in (self.look() if pids is None else pids))

    def signal(self, sig: int, pids: list[int] | None = None) -> int:
        """Send one signal to every process of the run's. How many it reached."""
        sent = 0
        for pid in (self.look() if pids is None else pids):
            try:
                os.kill(pid, sig)
                sent += 1
            except (ProcessLookupError, PermissionError):
                continue
        return sent

    def end(self, grace: float = GRACE) -> int:
        """SIGTERM to everything of the run's, then SIGKILL to what is left. How many."""
        pids = self.look()
        if not pids:
            return 0
        self.signal(signal.SIGTERM, pids)
        deadline = time.monotonic() + grace
        while time.monotonic() < deadline:
            if not self.look():
                return len(pids)
            time.sleep(0.1)
        self.signal(signal.SIGKILL)
        return len(pids)


def ended_runs_processes(ended: set[str]) -> dict[str, list[int]]:
    """Processes this user can read whose mark names one of these runs, by run.

    For the reaper, where there is no cgroup to sweep: a run that has ended
    and still has processes marked with its id left them behind, because its
    holder was killed outright and never reached its own ending.
    """
    found: dict[str, list[int]] = {}
    if not ended:
        return found
    try:
        names = [n for n in os.listdir("/proc") if n.isdigit()]
    except OSError:
        return found
    me = os.getpid()
    for name in names:
        if int(name) == me:
            continue
        mark = mark_of(name)
        if mark and mark in ended:
            found.setdefault(mark, []).append(int(name))
    return found
