"""PostgreSQL, for a process that lives for weeks, through a pool of its own.

Django's own backend, with four things changed.

**A broken connection is opened again.** When the database restarts underneath
a long-lived process, a connection it held is dead, and plain Django would fail
every query on it. So a query that failed with a database error marks the
connection, and the next query on it asks first whether it is still usable, and
opens a new one if it is not. One query fails - the one that found out - and the
one after it works. Nothing is retried behind anybody's back.

**Every connection comes from one bounded pool** (`OPTIONS["pool"]` in
`rouh/project/settings.py`), so this process can never hold more of PostgreSQL
than the pool's ``max_size``, however many threads it runs. Until 21 October
2026 every thread kept a connection of its own for ever (``CONN_MAX_AGE=None``),
and every web request ran on a thread of its own that asgiref throws away, so a
connection was left behind per request until Python's garbage collector found
it; the server filled PostgreSQL's 97 slots several times an hour
(`workspace/rouh/assistant/137.rouh-runs-out-of-database-connections`). Now a
connection is taken for a unit of work and given back after it: by Django at
the end of each request, by `rouh.dbwork` after each call handed to a thread,
by the loops that close after each beat, and - whatever else happens - when the
thread that held it ends (`_Held`). A pooled connection that is never given
back is gone for good, which is why the last of those exists.

**Background work can never take the last connections.** A thread whose name
says it is background work (`BACKGROUND`) takes a background share first, and
the share is ``max_size`` less `INTERACTIVE_RESERVE`, so a burst of imports,
backfills or dreaming waits for its own share while a request, the websocket
and the conversation still find a connection at once.

**A connection comes back clean.** A borrower that ran something that outlives
its statement on the session - a ``SET``, a session advisory lock, a temporary
table, ``set_config`` (`_LEAVES_STATE`) - marks the connection, and before it is
lent again its session settings are reset and any lock let go (`_reset`), so
nothing one borrower set travels to the next. A connection nobody marked is
lent again as it is, which keeps giving back as cheap as keeping.

**A connection is checked as it is lent without asking the server**
(`_check`): an idle connection the server has said nothing on is alive, and one
it has (it was restarted, or it ended the session) is asked properly and
replaced. A database restart costs no failed query, and a healthy connection no
round trip.

When the pool is empty a borrower waits, at most `WAIT` seconds (`LOOP_WAIT` on
the event loop's own thread, which must never stall), and then gets an error
that the page answers with 503 and "try again" (`rouh.dbwork.busy`), never a
PostgreSQL refusal for every service on the machine.
"""
from __future__ import annotations

import logging
import select
import threading

from django.core.exceptions import ImproperlyConfigured
from django.db.backends.base.base import NO_DB_ALIAS
from django.db.backends.postgresql import base
from django.db.utils import OperationalError

log = logging.getLogger("rouh.db")

#: Connections the pool keeps for work that somebody is waiting on. Background
#: work shares the rest.
INTERACTIVE_RESERVE = 12

#: Threads whose work is background work, by the start of their name: Synapse's
#: workers, imports, backfills, syncs and dreaming, Slack's backfill, the silos'
#: refill and the start-up content index.
BACKGROUND = ("synapse-", "slack-backfill", "silos-refill", "content-index")

#: Seconds a borrower waits for a connection before it is told the database is
#: busy; on the event loop's own thread, shorter, because the whole process
#: waits with it.
WAIT = 10.0
LOOP_WAIT = 2.0

#: Seconds background work waits for its share before the unit fails and is
#: tried again by its own loop or queue.
BACKGROUND_WAIT = 120.0


class Busy(OperationalError):
    """No connection could be had in time: the pool, or background's share of it, is in use."""


_share_lock = threading.Lock()
_share: threading.BoundedSemaphore | None = None
_share_size = 0


class _Token:
    """One connection's place in background's share, given back exactly once, on whichever
    path comes first: the wrapper closing, its thread ending, or the pool taking the
    connection back (`_reset`)."""

    __slots__ = ("_share", "_lock")

    def __init__(self, share: threading.BoundedSemaphore):
        self._share = share
        self._lock = threading.Lock()

    def give_back(self) -> None:
        with self._lock:
            share, self._share = self._share, None
        if share is not None:
            share.release()


#: Who holds a pooled connection now: id(wrapper) -> (thread, wrapper), for the health page.
_holding: dict[int, tuple[threading.Thread, object]] = {}
_holding_lock = threading.Lock()


def _hold(wrapper) -> None:
    with _holding_lock:
        _holding[id(wrapper)] = (threading.current_thread(), wrapper)


def _unhold(wrapper) -> None:
    with _holding_lock:
        _holding.pop(id(wrapper), None)


def holders() -> dict:
    """How many pooled connections are out, by the kind of thread holding them (its name
    without the number), and how many of those threads have ended: the second should be 0."""
    import re

    with _holding_lock:
        items = list(_holding.values())
    out: dict[str, int] = {}
    ended = 0
    for thread, wrapper in items:
        if getattr(wrapper, "connection", None) is None:
            continue
        name = re.sub(r"[-_]\d+(_\d+)?$", "", thread.name or "?")
        out[name] = out.get(name, 0) + 1
        if not thread.is_alive():
            ended += 1
    return {"by_thread": dict(sorted(out.items(), key=lambda kv: -kv[1])), "threads_ended": ended}


def _background_share(max_size: int) -> threading.BoundedSemaphore:
    global _share, _share_size
    with _share_lock:
        if _share is None:
            _share_size = max(1, int(max_size) - INTERACTIVE_RESERVE)
            _share = threading.BoundedSemaphore(_share_size)
        return _share


def share_in_use() -> tuple[int, int]:
    """How much of background's share is taken, and how big it is."""
    if _share is None:
        return 0, 0
    return _share_size - _share._value, _share_size  # noqa: SLF001 - a reading, never a change


def is_background(thread: threading.Thread | None = None) -> bool:
    name = (thread or threading.current_thread()).name or ""
    return name.startswith(BACKGROUND)


#: The start of a statement whose effect outlives it on the session.
_LEAVES_STATE = ("SET ", "SET\t", "SET\n", "RESET", "CREATE TEMP", "CREATE LOCAL TEMP", "DECLARE",
                 "LISTEN", "PREPARE", "LOAD")


def _leaves_state(sql) -> bool:
    if not isinstance(sql, str):
        sql = str(sql)
    head = sql.lstrip()[:20].upper()
    return (head.startswith(_LEAVES_STATE) or "advisory_lock" in sql or "set_config" in sql
            or "SET SESSION" in head)


def _watch(execute, sql, params, many, context):
    """Every statement this process runs passes here: one that leaves something on the session
    marks the connection to be reset before it is lent again."""
    if _leaves_state(sql):
        context["connection"]._rouh_dirty = True
    return execute(sql, params, many, context)


def _reset(conn) -> None:
    """What a marked connection goes through on its way back into the pool, on one of the pool's
    own threads: its session settings back to the server's, any session advisory lock it still
    holds let go, and the time zone Django expects set again. One round trip, and only when a
    borrower left something behind."""
    token = getattr(conn, "_rouh_token", None)
    if token is not None:
        conn._rouh_token = None
        token.give_back()
    if not getattr(conn, "_rouh_dirty", False):
        return
    from django.conf import settings
    from psycopg import sql

    zone = sql.Literal(settings.TIME_ZONE if settings.USE_TZ else "UTC").as_string(conn)
    conn.execute(f"RESET ALL; SELECT pg_advisory_unlock_all(); SET TIME ZONE {zone}")
    conn._rouh_dirty = False


def _check(conn) -> None:
    """Whether a connection is fit to lend, without a round trip when it plainly is: nothing
    should ever arrive on an idle connection, so one with something waiting on it - the
    server's goodbye when it restarts or ends the session, or the socket closing - is asked
    properly, which raises if it is gone and the pool replaces it."""
    from psycopg_pool import ConnectionPool

    try:
        waiting, _, _ = select.select([conn.fileno()], [], [], 0)
    except (OSError, ValueError):
        waiting = True
    if waiting:
        ConnectionPool.check_connection(conn)


class _Held:
    """The connections one thread holds, given back when that thread ends.

    A thread's Django connection is only freed by the garbage collector (the
    wrapper holds itself in a cycle), so a thread that ended holding one would
    keep a pooled connection out for minutes, or for good. One of these is kept
    in the thread's own slot of `_threads` and nothing else refers to it, so it
    goes the moment the thread does, and gives back whatever is still out."""

    def __init__(self):
        self.wrappers: list[DatabaseWrapper] = []

    def __del__(self):
        for wrapper in self.wrappers:
            try:
                wrapper._give_back()
            except Exception:  # noqa: BLE001 - a thread's end is no place to fail
                pass


_threads = threading.local()


def _held() -> _Held:
    held = getattr(_threads, "held", None)
    if held is None:
        held = _threads.held = _Held()
    return held


def one_connection_per_thread() -> None:
    """Django's connections, kept one per thread whatever runs in it.

    Django keeps its connections in an asgiref ``Local``, which in a thread that is
    running an event loop gives every asyncio task a connection of its own, and
    nothing ever closes those: the loop's own thread, and every thread that wraps a
    Google call in ``asyncio.run`` (`synapse/sources/calsync.py`,
    `synapse/sources/gmailsync.py`), took a fresh one each time and kept it. On 21
    October 2026 the calendar's thread alone held eleven within two minutes.
    Rouh's async code calls the stores straight from the loop and never awaits
    inside a transaction (`rouh/project/asgi.py`), so one connection per thread is
    what it was written for: the loop's thread has one, and a thread that runs a
    loop now and then uses its own, which its beat gives back. Called once, from
    `rouh.apps`, before anything has opened a connection."""
    from django.db import connections

    if not isinstance(connections._connections, threading.local):
        connections._connections = threading.local()


class DatabaseWrapper(base.DatabaseWrapper):
    _rouh_token: _Token | None = None
    _rouh_dirty = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.execute_wrappers.append(_watch)

    @property
    def pool(self):
        """Django's own pool, made the same way (Django 5.2's `pool`), with Rouh's check and reset."""
        pool_options = self.settings_dict["OPTIONS"].get("pool")
        if self.alias == NO_DB_ALIAS or not pool_options:
            return None
        if self.alias not in self._connection_pools:
            if self.settings_dict.get("CONN_MAX_AGE", 0) != 0:
                raise ImproperlyConfigured("Pooling doesn't support persistent connections.")
            pool_options = {} if pool_options is True else dict(pool_options)
            try:
                from psycopg_pool import ConnectionPool
            except ImportError as err:
                raise ImproperlyConfigured(
                    "Error loading psycopg_pool module.\nDid you install psycopg[pool]?") from err
            connect_kwargs = self.get_connection_params()
            connect_kwargs["autocommit"] = True
            pool_options.setdefault("reset", _reset)
            pool = ConnectionPool(
                kwargs=connect_kwargs,
                open=False,
                configure=self._configure_connection,
                check=_check if self.settings_dict["CONN_HEALTH_CHECKS"] else None,
                **pool_options,
            )
            self._connection_pools.setdefault(self.alias, pool)
        return self._connection_pools[self.alias]

    def close_if_health_check_failed(self):
        if (self.connection is not None and self.errors_occurred
                and not self.in_atomic_block):
            if not self.is_usable():
                self.close()
            self.errors_occurred = False
        return super().close_if_health_check_failed()

    def get_new_connection(self, conn_params):
        pool = self.pool
        if pool is None:
            return super().get_new_connection(conn_params)
        self._release_share()                       # never two places for one wrapper
        token = None
        if is_background():
            share = _background_share(pool.max_size)
            if not share.acquire(timeout=BACKGROUND_WAIT):
                raise Busy(f"background work has all {share_in_use()[1]} of its database connections in use")
            token = _Token(share)
        try:
            if "isolation_level" in self.settings_dict["OPTIONS"]:
                connection = super().get_new_connection(conn_params)
            else:
                connection = self._from_pool(pool)
        except BaseException:
            if token is not None:
                token.give_back()
            raise
        self._rouh_token = token
        connection._rouh_token = token
        _hold(self)
        held = _held()
        if self not in held.wrappers:
            held.wrappers.append(self)
        return connection

    def _from_pool(self, pool):
        """Django's own `get_new_connection` for a pool, with a wait that depends on who waits."""
        self.isolation_level = base.IsolationLevel.READ_COMMITTED
        pool.open()
        on_loop = threading.current_thread() is threading.main_thread()
        try:
            connection = pool.getconn(timeout=LOOP_WAIT if on_loop else WAIT)
        except Exception as exc:
            from psycopg_pool import PoolTimeout, TooManyRequests

            if isinstance(exc, (PoolTimeout, TooManyRequests)):
                stats = pool.get_stats()
                log.warning("database pool busy: %s (%s of %s out, %s waiting)", exc,
                            stats.get("pool_size", 0) - stats.get("pool_available", 0),
                            pool.max_size, stats.get("requests_waiting", 0))
                raise Busy(f"no database connection free in {exc}") from exc
            raise
        return connection

    def _close(self):
        self._mark()
        try:
            return super()._close()
        finally:
            self._release_share()

    def _mark(self):
        """The borrower left something on the session: the pool resets it before lending it again."""
        if self._rouh_dirty and self.connection is not None:
            self.connection._rouh_dirty = True
        self._rouh_dirty = False

    def _release_share(self):
        _unhold(self)
        token, self._rouh_token = self._rouh_token, None
        if token is not None:
            token.give_back()

    def _give_back(self):
        """The connection back to its pool, from a thread that has ended: nobody uses this
        wrapper again, so only the connection and the share are dealt with."""
        self._mark()
        connection, self.connection = self.connection, None
        try:
            if connection is not None:
                pool = getattr(connection, "_pool", None)
                if pool is not None:
                    pool.putconn(connection)
                else:
                    connection.close()
        finally:
            self._release_share()
