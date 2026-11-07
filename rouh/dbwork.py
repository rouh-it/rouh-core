"""Work handed to a thread gives its database connection back when it is done.

Rouh's async code hands its database work to threads: about 1,750
`asyncio.to_thread` calls, a few `run_in_executor(None, ...)`, and its own
pools (`rouh/synapse/autorecall.py`, `rouh/owner.py`, `rouh/recalling.py`).
Django gives each thread a connection of its own and only lets it go at the end
of a web request, which a thread like these never sees, so each of them used to
keep one for as long as the process ran. With the connections now lent by one
bounded pool (`rouh/project/db/base.py`), a connection kept like that is one the
rest of Rouh cannot have.

`Executor` is a thread pool whose threads give their connection back to the
pool as soon as they have nothing to do: a thread that is handed one call after
another keeps its connection between them, and one that waits `IDLE` seconds
with nothing to run gives it back. So steady work pays nothing for the pool, and
an idle thread holds nothing. `install` makes it the event loop's default
executor, so every `asyncio.to_thread` goes through it without changing a line
of the calls.

A call that is cancelled from the async side still runs to its end on its
thread (Python cannot stop a thread), and gives its connection back then;
PostgreSQL's own time limits bound how long that can be.

`busy` says whether an error means "no connection could be had in time", which
the gate and the views answer with 503 and a Retry-After instead of a 500.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import contextlib
import contextvars
import logging
import os
import queue
import threading

#: Seconds a pool thread waits with nothing to run before it gives its connection back.
IDLE = 0.05

log = logging.getLogger("rouh.dbwork")


def release() -> None:
    """Give back every database connection this thread holds, unless it is inside a transaction
    (then whoever opened the transaction gives it back when it ends)."""
    from django.db import connections

    for conn in connections.all(initialized_only=True):
        if conn.connection is not None and not conn.in_atomic_block:
            try:
                conn.close()
            except Exception:  # noqa: BLE001 - the next use opens a fresh one
                log.warning("a database connection could not be given back", exc_info=True)


def _run_and_release(fn, args, kwargs):
    try:
        return fn(*args, **kwargs)
    finally:
        release()


class _GiveBackWhenIdle(queue.SimpleQueue):
    """The work queue of an `Executor`. Its threads wait here for their next call; one that
    waits `IDLE` with nothing coming gives its connection back, on its own thread, then waits on."""

    def get(self, block=True, timeout=None):
        if block and timeout is None:
            try:
                return super().get(timeout=IDLE)
            except queue.Empty:
                release()
        return super().get(block, timeout)


#: Whether the work being handed to a thread now is work nobody is waiting on (`later`): "" for
#: no, "quiet" for the lane after the person's own work (`foreground`), "now" for the lane at once.
_LATER: contextvars.ContextVar[str] = contextvars.ContextVar("rouh_later", default="")

#: How many threads the work nobody is waiting on shares.
LATER_THREADS = 2


@contextlib.contextmanager
def later(wait: bool = True):
    """Everything handed to the loop's threads inside this goes to the lane of `LATER_THREADS`
    threads kept for work nobody is waiting on, rather than to the threads everything else shares.

    The offline copy fills itself with a few hundred requests for whole task
    pages, decisions and goals, four at a time from every open tab, and each
    is a third of a second of Python or more. On 23 October 2026 they held
    every one of the sixteen threads, and a page being opened waited in line
    behind them: seventeen seconds for its conversation, and two more for its
    canvas, whose own request takes ten milliseconds. In their own lane they
    wait for each other instead, and Python's one lock is shared between
    their two threads and everything else, rather than everything else
    waiting for a thread at all. The page says which of its requests are
    these, with the header `X-Rouh-Later: 1` (`rouh/project/asgi.py`).

    `wait` False is for work a page being opened does want, only not first (the lists after
    its handshake): it goes to the lane without waiting for the person's own work to finish
    (`foreground`).
    """
    token = _LATER.set("quiet" if wait else "now")
    try:
        yield
    finally:
        _LATER.reset(token)


#: How long work in the lane waits for the person's own work to finish before it starts anyway,
#: so that a turn that never ends can never hold it back for good.
QUIET_LONGEST = 30.0

_foreground = 0
_foreground_lock = threading.Lock()
_quiet = threading.Event()
_quiet.set()


@contextlib.contextmanager
def foreground():
    """The person is waiting on what runs inside this: a turn being answered, a page's
    handshake. Work in the lane that has not started yet waits until there is none, at most
    `QUIET_LONGEST` seconds (`_after_quiet`).

    The lane alone was not enough (23 October 2026): two of its threads building whole task
    pages for the offline copy still took two thirds of Python's one lock, and a "hi" sent
    just after the page opened took thirteen seconds where it takes two. Work already
    running in the lane runs on to its end; nothing new starts while the person waits."""
    global _foreground
    with _foreground_lock:
        _foreground += 1
        _quiet.clear()
    try:
        yield
    finally:
        with _foreground_lock:
            _foreground -= 1
            if _foreground <= 0:
                _foreground = 0
                _quiet.set()


def _after_quiet(fn, args, kwargs):
    _quiet.wait(QUIET_LONGEST)
    return fn(*args, **kwargs)


_lane: "Executor | None" = None
_lane_lock = threading.Lock()


def _later_lane() -> "Executor":
    global _lane
    with _lane_lock:
        if _lane is None:
            _lane = Executor(max_workers=LATER_THREADS, thread_name_prefix="rouh-later")
        return _lane


class Executor(concurrent.futures.ThreadPoolExecutor):
    """A thread pool whose threads give their database connection back when they have nothing to do."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        #: Only the loop's default hands work to the lane (`install`, `later`); a pool of its
        #: own keeps what it is given.
        self.lends = False
        # Python's ThreadPoolExecutor keeps its waiting work in `_work_queue`, a SimpleQueue its
        # threads `get` from; if a later Python ever stops doing so, every call gives its
        # connection back as it ends instead, which is as safe and a little slower.
        self._lazy = isinstance(getattr(self, "_work_queue", None), queue.SimpleQueue)
        if self._lazy:
            self._work_queue = _GiveBackWhenIdle()

    def submit(self, fn, /, *args, **kwargs):
        # Never from one of the lane's own threads: work it hands on and waits for
        # must not wait behind itself.
        lane = _LATER.get() if self.lends else ""
        if lane and not threading.current_thread().name.startswith("rouh-later"):
            if lane == "now":
                return _later_lane().submit(fn, *args, **kwargs)
            return _later_lane().submit(_after_quiet, fn, args, kwargs)
        if self._lazy:
            return super().submit(fn, *args, **kwargs)
        return super().submit(_run_and_release, fn, args, kwargs)


def install(loop: asyncio.AbstractEventLoop | None = None) -> Executor:
    """`Executor` as the loop's default, the size Python's own default would have been."""
    loop = loop or asyncio.get_running_loop()
    executor = Executor(max_workers=min(32, (os.cpu_count() or 1) + 4), thread_name_prefix="rouh-thread")
    executor.lends = True
    loop.set_default_executor(executor)
    return executor


def busy(exc: BaseException | None) -> bool:
    """Whether this error, or one it came from, means the database had no connection free in
    time: Rouh's own pool, background's share of it, or PostgreSQL out of slots."""
    from rouh.project.db.base import Busy

    seen = 0
    while exc is not None and seen < 8:
        if isinstance(exc, Busy):
            return True
        if type(exc).__name__ in ("PoolTimeout", "TooManyRequests"):
            return True
        # 53300 too_many_connections: PostgreSQL out of slots, or a role at its own limit.
        if getattr(exc, "sqlstate", None) == "53300":
            return True
        text = str(exc)
        if "remaining connection slots are reserved" in text or "too many clients already" in text \
                or "too many connections for role" in text:
            return True
        exc = exc.__cause__ or exc.__context__
        seen += 1
    return False


def pool_state() -> dict:
    """The pool's numbers, for the health page: never anything but counts."""
    from django.db import connections

    from rouh.project.db.base import holders, share_in_use

    try:
        pool = connections["default"].pool
    except Exception:  # noqa: BLE001
        pool = None
    if pool is None:
        return {"pooled": False}
    stats = pool.get_stats()
    taken, share = share_in_use()
    return {
        "pooled": True,
        "max": pool.max_size,
        "open": stats.get("pool_size", 0),
        "free": stats.get("pool_available", 0),
        "waiting": stats.get("requests_waiting", 0),
        "background_in_use": taken,
        "background_share": share,
        "timeouts": stats.get("requests_errors", 0),
        "held": holders(),
    }
