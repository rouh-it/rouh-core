"""One scheduler: what may start, and when.

Step 07, section 6: "What it decides, in order: may it start, what may it
touch, what does it cost, what if it dies, who is watching it." What a run may
touch is ``rules.py``; what happens when it dies is ``runs.py``. This file is
whether it may start now, and, when memory runs short, closing the run left
unwatched the longest.

**The processor.** On 14 September Rouh's live site stopped answering for
about 11 minutes while ten threads each held a whole processor, and nothing
refused the work that caused it. The program runs under a processor limit set
on its own service (``CPUQuota`` in ``one.service``), which the kernel
enforces for every run it starts; the scheduler also reads how much of that
limit is in use and makes new runs wait while it is nearly all used, so the
limit is met by waiting rather than by everything slowing down.

**Waiting is visible.** A run that cannot start yet is in the list as
``run.queued`` with the reason, and that reason is what every screen shows
next to the word "queued": "6 runs are already working; it starts when one
finishes", not "waiting to start" on its own.

**How many at once.** Thirty runs of Claude Code may work at the same time.
That number is set in one place only, ``ONE_MAX_RUNS`` in the stack's
settings file (the machine's ``.env``, ``deploy/stack/settings.env.example``),
which ``deploy/stack/compose.yml`` hands to the worker, 30 when the settings
file says nothing; before the containers (31 October 2026) it was the systemd
drop-in ``one.service.d/limits.conf``. The 4 in ``config.py`` is the fallback
for a machine with neither and is not tuned by hand. A run sitting at its
prompt costs almost nothing, so the count is no longer what protects the
machine: the processor share (``ONE_CPU_BUDGET``) and the memory share below
are, read from the worker container's own limits (``ROUH_WORKER_MEMORY``).

**Memory.** Every run stays open until the person closes it, their decision of
15 September (D49): a run that has finished its turn waits at its prompt, with
its terminal, however long nobody looks. Each holds about 300 MB, and the
service may use a fixed amount in all (``MemoryMax`` in ``one.service``). When
the program's processes use more than ``MEMORY_ROOM`` of it, the run left
unwatched the longest is closed, and the list says so (``closed-for-room``);
a run somebody is watching or typing into is never closed for room. New runs
wait while memory is that full.

**What "used" means.** Not ``memory.current``. That is everything the cgroup
is charged for, and most of it is page cache: file pages the kernel keeps
because it has the room and drops the instant anything wants it back. On 20
September 2026 the service read 18.8 GB of its 20 GB cap and queued a run for
want of memory while the machine had 22.8 GB free; 15.4 GB of that 18.8 was
file cache and the program and its runs were holding 2.6 GB between them. What
is counted instead is what the kernel cannot take back on its own, out of
``memory.stat``: ``anon``, ``shmem`` and ``swap``, plus the small kernel
allocations (``kernel_stack``, ``slab``, ``sock``, ``percpu``). Both gates read
the same number, so a run is neither made to wait nor closed for room because
the program once read a large file.

``shmem`` is shared memory: a page of a tmpfs, which is a filesystem that
lives in memory and nowhere else. On the server ``/tmp`` is one of those, 16 GB of
it, and the 3.1 GB of working files the runs have left in there is charged to
this service as 3.26 GB of ``shmem``. It looks like page cache and is nothing
like it. The kernel charges a tmpfs page to ``file``, because a filesystem is
what it belongs to, and then keeps it on the anonymous list, because there is
no disk behind it to write it back to: dropping the page would lose the file.
So none of it is reclaimable, and counting it is not the same mistake as
counting page cache. The reclaimable part of ``file`` is exactly the two file
lists, ``inactive_file`` and ``active_file``; whatever is left of ``file``
after those two is ``shmem``, to within a few kilobytes of the reading not
being taken all at once. Leaving it out understated the service by 3.26 GB on
20 September, 15% of the 20 GB cap read as free. What it costs to be wrong this
way round is worse than the other: the cgroup had already been pushed against
its ceiling 1,748 times and had written nothing to swap, so the kernel was
holding the line by dropping page cache, and once there is no page cache left
to drop it kills a process instead of making anybody wait.

One thing follows from this and is not handled here: memory held as files in
``/tmp`` is not given back by closing a run, and the sentence a queued run
carries says a run being closed is what ends the wait. A tmpfs that is filling
up is emptied by deleting files, not by closing runs.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING

from rouh import browser_handoff

from .listfile import epoch
from .reaper import Reaper
from .runs import hours
from .views import ENDED, REAPED

if TYPE_CHECKING:  # pragma: no cover
    from .program import Program

log = logging.getLogger("one.scheduler")

#: States in which a run of Claude Code is doing work, as opposed to sitting at its prompt.
BUSY = frozenset({"starting", "working", "asking", "saving"})
ALIVE = BUSY | {"idle"}
#: Above this share of the memory the service may use, the run left unwatched
#: the longest is closed to make room, and new runs wait (D49).
MEMORY_ROOM = 0.85
#: Seconds after closing a run for room before another is closed, so the first
#: has time to give its memory back.
ROOM_PAUSE = 10.0
#: Where cgroup v2 is mounted. Named once so the walk up in ``_memory_dir``
#: and the derivation in ``_own_cgroup`` cannot drift apart.
CGROUP_ROOT = Path("/sys/fs/cgroup")
#: The lines of ``memory.stat`` that are memory really in use: pages the kernel
#: cannot take back on its own. ``anon`` is the program's and its runs' own
#: heaps and stacks, ``shmem`` is their shared memory, and between them they
#: are nearly all of it; the rest are small and are added when the kernel
#: reports them. Everything left out is reclaimable, which is the whole point;
#: the paragraph on what "used" means, at the top of this file, says why. The
#: half of ``slab`` that is reclaimable is counted here too, which overstates
#: by about 2% of the cap on the server; that is noise beside the 77% ``file``
#: was adding, and not worth a second reading of the same file to take out.
#: ``pagetables`` is left out and is the only thing that keeps this sum from
#: agreeing exactly with ``memory.current`` less the two file lists: 17 MB of
#: the 21 GB cap on the server, which is noise of the same kind.
IN_USE_FIELDS = ("anon", "shmem", "swap", "kernel_stack", "slab", "sock", "percpu")
#: Where a kernel or a cgroup version calls the same field something else.
#: cgroup v2 says ``shmem``; ``shm`` is read as the same thing rather than
#: silently as nothing, because reading shared memory as zero is the fault
#: being fixed here.
FIELD_ALIASES = {"shmem": "shm"}


class CpuMeter:
    """How much of the processor the program's service uses, as a share of its limit."""

    def __init__(self, cgroup: Path | None = None, *, named: str = "") -> None:
        self.dir = cgroup if cgroup is not None else _own_cgroup(named)
        self._last: tuple[float, int] | None = None
        self.value: float | None = None

    def limit(self) -> float:
        """How many processors' worth the service may use."""
        try:
            quota, period = (self.dir / "cpu.max").read_text().split()
            if quota != "max":
                return int(quota) / int(period)
        except (OSError, ValueError, AttributeError):
            pass
        return float(os.cpu_count() or 1)

    def sample(self) -> float | None:
        if self.dir is None:
            return None
        try:
            stat = (self.dir / "cpu.stat").read_text()
            usage = int(next(line.split()[1] for line in stat.splitlines()
                             if line.startswith("usage_usec")))
        except (OSError, StopIteration, ValueError, IndexError):
            return None
        now = time.monotonic()
        if self._last is not None and now > self._last[0]:
            used = (usage - self._last[1]) / 1e6 / (now - self._last[0])
            self.value = used / self.limit()
        self._last = (now, usage)
        return self.value


def _own_cgroup(named: str = "") -> Path | None:
    """The cgroup the processor and memory gates read, or None for neither.

    ``named`` is the ``cgroup`` setting: a folder said by hand, for a program
    in a throwaway world that must not be told what the whole machine is
    doing. A folder with no ``cpu.stat`` in it is no cgroup, and both gates
    are off.
    """
    if named:
        path = Path(named)
        return path if (path / "cpu.stat").exists() else None
    try:
        for line in Path("/proc/self/cgroup").read_text().splitlines():
            if line.startswith("0::"):
                path = CGROUP_ROOT / line[3:].lstrip("/")
                if (path / "cpu.stat").exists():
                    return path
    except OSError:
        pass
    return None


def _memory_dir(cgroup: Path) -> Path:
    """The nearest cgroup from here upwards that says anything about memory.

    The service has ``Delegate=yes`` and the holders make a ``run-<id>``
    cgroup under it for every run (``holder.Holder._make_box``). Those
    children get no memory controller of their own unless somebody turns one
    on, so a process sitting in one has no memory files beside it, while the
    service's - one level up, and hierarchical, so they cover every run at
    once - say exactly what is wanted. Walking up finds them either way.

    The walk stops at ``/sys/fs/cgroup``, and a folder said by hand that is
    not under it at all is left where it is: a throwaway world in a test must
    never end up reading the real service.
    """
    here = cgroup
    while not (here / "memory.stat").exists() and not (here / "memory.current").exists():
        if here == CGROUP_ROOT or CGROUP_ROOT not in here.parents:
            return cgroup
        here = here.parent
    return here


def _swapped(cgroup: Path) -> int:
    """What the cgroup has pushed out to swap, in bytes, or 0 if it cannot say.

    cgroup v1 put a ``swap`` line in ``memory.stat``; v2 keeps the number in a
    file of its own, and a machine built without swap at all - which the server is
    - has neither. Nothing to read means nothing swapped.
    """
    try:
        return int((cgroup / "memory.swap.current").read_text())
    except (OSError, ValueError):
        return 0


def memory_in_use(cgroup: Path) -> int | None:
    """Bytes the cgroup really holds, from ``memory.stat``, or None if it cannot say.

    ``memory.current`` is the wrong number to gate on: it is everything the
    cgroup is charged for, page cache included, and page cache is reclaimable -
    the kernel drops those file pages the moment anything needs the room. On
    20 September 2026 that read 88% of the service's 20 GB cap and queued run
    52295e1b, "Fetch Telegram chat id", on a machine with 22.8 GB free; 15.4
    of the 18.8 GB was file cache and the program's own memory was 2.6 GB. So
    what is summed here is what the kernel cannot take back on its own.

    Shared memory is part of that, and was left out until 20 September: a
    tmpfs page is charged to ``file`` and so looked like page cache, while the
    kernel keeps it on the anonymous list and reclaims none of it. On the server
    that was 3.26 GB the gate could not see, 15% of the cap, and it is the
    runs' own working files in ``/tmp``, which is a filesystem in memory. What
    ``file`` holds beyond the two file lists, ``inactive_file`` and
    ``active_file``, is exactly this.

    None is the honest answer when ``memory.stat`` is missing or says nothing
    about ``anon``; the caller falls back to ``memory.current`` rather than
    guess, because overstating makes runs wait and waiting is the safe way to
    be wrong.
    """
    try:
        text = (cgroup / "memory.stat").read_text()
    except OSError:
        return None
    fields: dict[str, str] = {}
    for line in text.splitlines():
        name, _, value = line.partition(" ")
        fields[name] = value
    for name, other in FIELD_ALIASES.items():
        if name not in fields and other in fields:
            fields[name] = fields[other]
    if "anon" not in fields:
        return None
    total = 0
    try:
        for name in IN_USE_FIELDS:
            if name in fields:
                total += int(fields[name])
    except ValueError:
        return None
    return total if "swap" in fields else total + _swapped(cgroup)


def _paths(given) -> set[str]:
    """One run's declared files as a set of plain relative paths."""
    return {str(p).strip().strip("/") for p in (given or []) if str(p).strip()}


def _overlap(mine: set[str], theirs: set[str]) -> set[str]:
    """What two declarations have in common, a folder counting as everything in it.

    A job that says it will touch `rouh/static/` and a job that says it will
    touch `rouh/static/app.js` are working on the same thing, and the point of
    declaring is to catch exactly that. Matching on the string alone would miss
    it and then both would start.
    """
    shared: set[str] = set()
    for a in mine:
        for b in theirs:
            if a == b or a.startswith(b + "/") or b.startswith(a + "/"):
                shared.add(a if len(a) >= len(b) else b)
    return shared


def _rounded(share: float) -> str:
    """A share as a percentage in steps of five: "90%", "95%".

    A run is told its reason again whenever the reason changes, and every run
    still waiting is told. Written to the nearest whole percent, a measurement
    that wobbles by a fraction would rewrite every waiting run's reason several
    times a minute and say nothing new; in steps of five it changes when the
    situation does.
    """
    return f"{round(share * 20) / 20:.0%}"


class Scheduler:
    def __init__(self, program: "Program", *, meter: CpuMeter | None = None) -> None:
        self.p = program
        self.s = program.settings
        self.meter = meter or CpuMeter(named=self.s.cgroup)
        self._room_at = 0.0  # when a run was last closed to make room
        self._memory_from = ""  # which file memory was last read from, for the log
        #: What owns whatever a run leaves behind. The scheduler is where it
        #: lives because this is the one loop that is already running when
        #: nothing else is, and sweeping is exactly a thing to do between runs.
        self.reaper = Reaper(program)
        self._wake = asyncio.Event()
        self._task: asyncio.Task | None = None

    def wake(self) -> None:
        self._wake.set()

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop(), name="scheduler")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()

    #: How often ended runs' checkouts are looked at, in seconds.
    TIDY_EVERY = 600.0

    async def _loop(self) -> None:
        tidied = 0.0  # so the first pass, just after a start, tidies too
        reaped = 0.0  # and sweeps, which is when the last run's leavings are oldest
        # The server's copy of the workspace is brought up to main every so
        # often, so it follows main when no run lands too (Runs.follow_check).
        followed = time.monotonic()
        while True:
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                pass
            self._wake.clear()
            try:
                self.meter.sample()
                await self.make_room()
                await self.admit()
                await self.close_idle()
                await self.archive_succeeded()
                await self.forget_due()
                await self.close_overdue()
                await self.end_stale_pauses()
                if time.monotonic() - tidied > self.TIDY_EVERY or not tidied:
                    tidied = time.monotonic()
                    await self.p.runs.tidy_sweep()
                # In a thread: a sweep reads every /proc entry on the machine
                # and walks a filesystem, and the loop that admits runs must
                # never be the thing waiting on either.
                if self.s.reap_every and (time.monotonic() - reaped > self.s.reap_every
                                          or not reaped):
                    reaped = time.monotonic()
                    await asyncio.to_thread(self.reaper.sweep)
                if self.s.follow_every and time.monotonic() - followed > self.s.follow_every:
                    followed = time.monotonic()
                    await self.p.runs.follow_check()
            except Exception:  # the scheduler must never stop
                log.exception("the scheduler hit a problem; carrying on")

    async def admit(self) -> None:
        """Start queued runs, oldest first, while there is room.

        Every run that cannot start is told why, not only the first one. Until
        16 September 2026 this stopped at the first run it could not start, so
        the second and the third waited with no reason on them at all and the
        page said "waiting to start" about them, which reads as stuck.
        """
        views = self.p.views
        queued = sorted((r for r in views.runs.values()
                         if r["state"] == "queued" and not self.p.runs.launching(r["id"])),
                        key=lambda r: r["requested_at"])
        blocked: str | None = None
        for run in queued:
            # A shell run is not a run of Claude Code and holds nothing back,
            # so it starts whatever the runs ahead of it are waiting for.
            if run["kind"] == "shell":
                asyncio.create_task(self.p.runs.launch(run["id"]))
                continue
            # Once one run cannot start, none behind it can either, and they
            # are all waiting for the same thing. Each of them says so.
            why = blocked or self.why_wait()
            if why:
                blocked = why
                self._queue(run, why)
                continue
            # And the one reason that is this run's own rather than the
            # machine's: it says it will touch files a run already working says
            # it will touch. That does not hold anything else back, because the
            # next run along may be nowhere near them.
            clash = self.would_collide(run)
            if clash:
                self._queue(run, clash)
                continue
            asyncio.create_task(self.p.runs.launch(run["id"]))

    def why_wait(self) -> str | None:
        """Why a run cannot start this instant, in the person's words, or None.

        One sentence that says what is in the way and what ends the wait, so a
        queued run on any screen reads as waiting for something nameable.
        """
        agents = [r for r in self.p.views.runs.values() if r["kind"] == "agent"]
        busy = sum(1 for r in agents if r["state"] in BUSY) + sum(
            1 for r in agents if r["state"] == "queued" and self.p.runs.launching(r["id"]))
        if busy >= self.s.max_runs:
            if busy == 1:
                return "1 run is already working; it starts when that one finishes"
            return f"{busy} runs are already working; it starts when one finishes"
        # Runs at their prompts no longer hold new ones back (D49): memory does.
        full = self.memory_share()
        if full is not None and full > MEMORY_ROOM:
            return (f"the program is using {_rounded(full)} of its memory; it starts "
                    "when a run is closed")
        share = self.meter.value
        if share is not None and share > self.s.cpu_budget:
            return (f"the program is using {_rounded(share)} of the processor it is "
                    "allowed; it starts when that drops")
        return None

    def would_collide(self, run: dict) -> str | None:
        """Why this run must wait for another one working on the same files, or None.

        The cheap prevention off card 488. A job declares up front the files it
        expects to touch, and a job whose declaration overlaps one already
        working waits for it rather than both starting and one of them finding
        out at the end that its work will not go onto main. Resolving a
        collision costs a whole extra turn of a model, or a person; waiting
        costs the minutes the run ahead was going to take anyway.

        Only ever a delay, never a refusal, and only between runs in the same
        space: two repositories cannot collide with each other. A run that
        declares nothing is not held back and holds nothing back, so this is
        worth nothing to a job that says nothing and free to everything else.
        """
        mine = _paths(run.get("expects"))
        if not mine:
            return None
        for other in self.p.views.runs.values():
            if other["id"] == run["id"] or other["kind"] != "agent":
                continue
            if other["state"] not in BUSY and not self.p.runs.launching(other["id"]):
                continue
            if (other.get("space") or "assistant") != (run.get("space") or "assistant"):
                continue
            shared = _overlap(mine, _paths(other.get("expects")))
            if not shared:
                continue
            what = ", ".join(sorted(shared)[:3])
            more = len(shared) - 3
            return (f"another run is already working on {what}"
                    + (f" and {more} more" if more > 0 else "")
                    + f' ("{str(other.get("title") or other["id"])[:40]}"); '
                    "it starts when that one finishes")
        return None

    def _queue(self, run: dict, why: str) -> None:
        """Write the reason onto the run, once, and again whenever it changes.

        A run changes nothing by waiting for the same thing twice, so only a
        new reason is written down; a run with no reason on it yet always gets
        one, because ``queued_because`` starts as None and None is never a
        reason.
        """
        if run.get("queued_because") != why:
            self.p.list.append("run.queued", run=run["id"], body={"why": why})

    async def close_idle(self) -> None:
        """Close runs of Claude Code that finished and have sat unwatched for a while.

        Off by default since D49: every run stays open until the person closes
        it. ``ONE_IDLE_CLOSE`` still sets a time, for a machine with less memory.
        """
        if self.s.idle_close <= 0:
            return
        now = time.time()
        for run in list(self.p.views.runs.values()):
            if run["kind"] != "agent" or run["state"] != "idle":
                continue
            if run.get("watchers") or run.get("driver") or self.p.runs.pending.get(run["id"]):
                continue
            if now - epoch(run["last_at"]) < self.s.idle_close:
                continue
            holding = await self.p.runs.holds_work(run)
            if holding:
                # Closing it would throw that work away. Said out loud, so that
                # a run which is never closed is as easy to explain as one that is.
                log.info("not closing idle run %s: %s", run["id"], holding)
                continue
            log.info("closing run %s: idle and unwatched, and it holds nothing "
                     "that is not on %s", run["id"], run.get("target") or "main")
            try:
                await self.p.runs.stop(run["id"], by="program", how="closed-idle")
            except Exception:
                log.exception("could not close idle run %s", run["id"])

    # -- garbage collection (fr_61710d502d1c) -----------------------------------------
    #
    # Petar, 5 October 2026: "Every run that was successful should have a green
    # status and be archived. The Claude code and all its sub-processes and
    # browsers should be closed after 6 hours." Two sweeps, on this loop
    # because it is the one already running when nothing else is.
    #
    # Stopping a run is what closes everything it started: its holder empties
    # the run's own cgroup (``holder.py``), which no process in it can escape,
    # however it detached, so a Playwright MCP and every Chromium behind it go
    # with the Claude Code that started them. What escaped the box altogether
    # is the reaper's (``reaper.py``).

    #: The most runs archived in one pass, so the first pass after this landed,
    #: with every run that ever ended done to put away, is a trickle of list
    #: entries rather than a flood to every screen at once.
    ARCHIVE_BATCH = 20

    async def close_overdue(self) -> None:
        """Stop every run that nothing has happened in for longer than a run may sit.

        Petar, 30 October 2026: "the 6h limit should be after the run has
        completed and has not been moving ... not 6h after the run has
        started". So the limit is counted from the run's last activity
        (``last_at``): every tool call opened or closed, a sub-agent's as much
        as its own, a turn ended or woken, a background command or monitor
        reporting back, a message said to it. A run that is working is never
        stopped by this, however long it has been going; only one that has
        been still for the whole of ``run_lifetime`` is. It ends ``reaped``
        (``views.ended_state``), which every screen calls Cleaned up: not a
        success and not a crash. Its checkout is kept if it holds anything,
        and the run is not archived, so it stays in view to be looked at.

        Two waits, both short. A run saving its work is landing it on main this
        instant, and a run a person has taken over is in their hands; either is
        stopped the moment that is over.
        """
        limit = self.s.run_lifetime
        if limit <= 0:
            return
        now = time.time()
        runs = self.p.runs
        for run in list(self.p.views.runs.values()):
            if run["kind"] != "agent" or run["state"] in ENDED or run["state"] in ("queued", "saving"):
                continue
            if self.p.terminals.get(run["id"]) is None or runs.launching(run["id"]):
                continue  # no process to be alive, or one being started this instant
            if run["id"] in runs.stopping or run["id"] in runs.takeovers:
                continue
            if self.s.archive_after >= 0 and self.succeeded(run, now, batch=False):
                # A success past the limit is put away as a success, green,
                # by ``archive_succeeded``, never cleaned up as if it were
                # stuck. On the day this shipped every run that had finished
                # well and sat at its prompt for more than six hours was both.
                continue
            since = (run.get("last_at") or run.get("launched_at") or run.get("started_at")
                     or run["requested_at"])
            if now - epoch(since) < limit:
                continue
            log.info("cleaning up run %s: nothing has happened in it for %s",
                     run["id"], hours(now - epoch(since)))
            try:
                await runs.stop(run["id"], by="program", how=REAPED)
            except Exception:
                log.exception("could not clean up run %s", run["id"])

    async def end_stale_pauses(self) -> None:
        """End the turn of every paused run that nothing has woken for too long.

        A run that ended a turn waiting on what it started is working, and is
        left alone while anything at all happens in it. One silent for
        ``pause_silence`` is not going to be woken, so its turn is saved and
        reported as it stands (``Runs.end_stale_pause``), rather than reading
        as working until six silent hours clean it up (``close_overdue``).
        """
        limit = self.s.pause_silence
        if limit <= 0:
            return
        now = time.time()
        for run in list(self.p.views.runs.values()):
            if run["kind"] != "agent" or run["state"] in ENDED or not run.get("waiting_on"):
                continue
            if run["id"] in self.p.runs.stopping or run["id"] in self.p.runs.takeovers:
                continue
            silent = now - epoch(run["last_at"])
            if silent < limit:
                continue
            log.info("run %s has waited %s on %s with nothing happening; ending its turn",
                     run["id"], hours(silent), ", ".join(run["waiting_on"]))
            try:
                await self.p.runs.end_stale_pause(run["id"], silent_for=silent)
            except Exception:
                log.exception("could not end the pause of run %s", run["id"])

    def succeeded(self, run: dict, now: float, *, batch: bool = True) -> bool:
        """Whether this run is a success the program should put away now.

        A run that ended **done** is one: its work is on main, or it had none,
        and nothing of it was left behind (``views.ended_state``). So is a run
        of Claude Code at its prompt whose last turn ended well
        (``succeeded_at``: landed and live, or nothing to save and nothing
        left) once ``archive_after`` has passed with nothing happening, nobody
        at its terminal and nothing waiting for it. The person's own session is
        theirs to close and is never put away open.

        ``batch`` False asks only whether it is a success at all, whatever the
        wait: ``close_overdue`` leaves those to this rather than reaping them.
        """
        if run.get("archived") or run.get("archive_settled"):
            return False
        if run["state"] == "done":
            return True
        if (run["state"] != "idle" or run["kind"] != "agent" or run.get("interactive")
                or not run.get("succeeded_at")):
            return False
        if batch and now - epoch(run["succeeded_at"]) < self.s.archive_after:
            return False
        if (run.get("question") or run.get("conflict") or run.get("watchers")
                or run.get("driver") or self.p.runs.pending.get(run["id"])
                or run["id"] in self.p.runs.takeovers):
            return False
        # Finished its turn by handing a step to the live browser: it is
        # waiting on the person, not done (rouh/browser_handoff.py).
        return browser_handoff.find(run.get("last_message")) is None

    async def archive_succeeded(self) -> None:
        """Put away every run that succeeded: closed, green, and archived.

        A run open at its prompt is closed down the archive's own path, so it
        ends done, which is the green on every screen, and its checkout goes
        once nothing in it is unsaved. Archived is out of the way and not gone:
        "Archived too" in the program's list and "Show archived" in Rouh's
        bring it back, and a message to it carries it on and brings it back by
        itself (``Runs._unarchive``). A run somebody brought back is never put
        away again until it is started again (``archive_settled``).
        """
        if self.s.archive_after < 0:
            return
        now = time.time()
        done = 0
        for run in sorted(self.p.views.runs.values(), key=lambda r: r["requested_at"]):
            if done >= self.ARCHIVE_BATCH:
                return
            if not self.succeeded(run, now):
                continue
            done += 1
            if run["state"] != "done":
                log.info("archiving run %s: its last turn ended well", run["id"])
            try:
                await self.p.runs.archive(run["id"], by="program", how="succeeded")
            except Exception:
                log.exception("could not archive run %s", run["id"])

    async def forget_due(self) -> None:
        """Forget every ended run whose person asked for it once it ended (`one forget
        --when-ended`), as soon as its wait after the end is over."""
        now = time.time()
        for run in list(self.p.views.runs.values()):
            after = run.get("forget_after")
            if after is None or run["state"] not in ENDED or not run.get("ended_at"):
                continue
            if now - epoch(run["ended_at"]) < after:
                continue
            try:
                await self.p.runs.forget(run["id"], by="program")
            except Exception:
                log.exception("could not forget run %s", run["id"])

    # -- memory (D49) ------------------------------------------------------------------

    def memory(self) -> tuple[int | None, int | None]:
        """What the service's processes really use, and what they may, in bytes.

        Both the gate on starting a run (``why_wait``) and the one that closes
        the run left unwatched the longest (``make_room``) read this, so the
        two can never disagree about how full the program is.
        """
        cgroup = self.meter.dir
        if cgroup is None:
            return None, None
        cgroup = _memory_dir(cgroup)
        try:
            limit = (cgroup / "memory.max").read_text().strip()
            cap = None if limit == "max" else int(limit)
        except (OSError, ValueError):
            return None, None
        used = memory_in_use(cgroup)
        if used is not None:
            self._measured_by("memory.stat",
                              "anon, shared memory and swap, not reclaimable page cache")
            return used, cap
        # Neither blind nor broken: the old number, which overstates, so the
        # program waits rather than starting runs it has no room for.
        try:
            used = int((cgroup / "memory.current").read_text())
        except (OSError, ValueError):
            return None, None
        self._measured_by("memory.current",
                          "memory.stat could not be read, so page cache is counted too")
        return used, cap

    def _measured_by(self, how: str, why: str) -> None:
        """Say which of the two ways memory was read, at the first and at any change.

        Once, not every five seconds: which file is being read changes almost
        never, and a line a log has already got says nothing.
        """
        if self._memory_from != how:
            self._memory_from = how
            log.info("the memory gates read %s: %s", how, why)

    def memory_share(self) -> float | None:
        used, limit = self.memory()
        return used / limit if used is not None and limit else None

    async def make_room(self) -> None:
        """Close the run left unwatched the longest while memory is nearly all used.

        "Nearly all used" is the same true figure the starting gate uses, so a
        run is no more evicted for page cache than another is made to wait for
        it (``memory``).
        """
        share = self.memory_share()
        if share is None or share <= MEMORY_ROOM or time.monotonic() - self._room_at < ROOM_PAUSE:
            return
        idle = [r for r in self.p.views.runs.values()
                if r["kind"] == "agent" and r["state"] == "idle" and not r.get("watchers")
                and not r.get("driver") and not self.p.runs.pending.get(r["id"])]
        if not idle:
            return
        # The one closed is the one that has nothing left to lose. On 17
        # September this took the oldest of them, which was 8109f4b5: it held
        # the whole of a fix to Rouh, uncommitted, and closing it left that
        # fix in a checkout nobody was going to look at. Memory is worth less
        # than a morning's work, so a run still holding work is passed over,
        # and if every one of them is, nothing is closed and the person is told.
        self._room_at = time.monotonic()
        for run in sorted(idle, key=lambda r: epoch(r["last_at"])):
            holding = await self.p.runs.holds_work(run)
            if holding:
                log.info("not closing run %s to make room: %s", run["id"], holding)
                continue
            # What was judged, and not only what was done about it. Working out
            # why f9c548c7 was closed on 19 September took reading the log, the
            # journal, the run's own list entries and its checkout, and the
            # answer was still a deduction: the line said a run had been closed
            # and never said what had been asked about it first.
            log.info("closing run %s to make room: the program uses %.0f%% of its memory, "
                     "and it holds nothing that is not on %s",
                     run["id"], share * 100, run.get("target") or "main")
            try:
                await self.p.runs.stop(run["id"], by="program", how="closed-for-room")
            except Exception:
                log.exception("could not close run %s to make room", run["id"])
            return
        log.warning("the program uses %.0f%% of its memory and every finished run still holds "
                    "work that is not on main, so none was closed", share * 100)
        self.p.tell(None, f"The program is using {share * 100:.0f}% of its memory and every "
                          f"finished run still holds work that is not saved to main, so none "
                          f"was closed. Look at them before starting anything else.",
                    reason="no-room")
