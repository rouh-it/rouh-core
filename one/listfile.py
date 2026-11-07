"""The list: everything that happens, one line each, added to and never changed.

This is step 07's data model. There is one writer, this process, and the list is
plain text, one file per day (UTC):

    <root>/2026-09-14.jsonl

Every line is one entry with the same six fields:

    {"n": 1042, "at": "2026-09-14T10:31:07.412Z", "run": "6aa9acb0",
     "kind": "tool.closed", "by": "run", "body": {"call": "uvs9NBFYcB", ...}}

``n``     the entry's number, one more than the entry before it, across files.
          A client that reconnects says where it got to with it.
``at``    when, in UTC, to the millisecond.
``run``   the run the entry is about, or null.
``kind``  what happened. KINDS.md lists every kind and its body. A shape, once
          written, is never changed: a changed shape gets a new kind.
``by``    who caused it: a device id, ``program``, or ``run`` for the run itself.
``body``  the details.

Step 07 names four fields: at, run, kind and body. ``n`` is there so views and
clients can say where they are, and ``by`` is step 07's "one field on every
event saying which device".

Why plain files and not a database: the list has to be readable in ten years
with this program long dead, by ``cat`` and ``grep``. A database file is one
program's idea of a file.

Durability, measured against what can actually go wrong:

* The program crashing loses nothing. Every entry is written and flushed to the
  operating system before :meth:`ListFile.append` returns.
* The whole machine losing power can lose at most the entries of the last fifth
  of a second, because the files are synced to disk in the background at that
  interval rather than once per entry. A busy run fires tens of hooks a second,
  and a disk sync per hook would put a pause of milliseconds in every tool call.
* A line cut off half-way by a power cut is found when the file is next opened
  and trimmed off, and an entry saying so is added. Nobody was ever told about
  the half-written entry, so dropping it loses nothing anyone relied on.
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

#: Biggest body kept, in bytes of JSON. A body over this has its longest text
#: fields cut until it fits, and says so in ``_cut``. The list is for what
#: happened, not for whole files; a run's full terminal output is in its own
#: tty.log, and a transcript is in Claude Code's own file.
BODY_LIMIT = 16_000

#: How often the files are synced to disk, in seconds.
SYNC_EVERY = 0.2

Listener = Callable[[dict[str, Any]], None]


def iso(at: float) -> str:
    """Seconds since 1970 as the list writes them: UTC, milliseconds, a Z."""
    return datetime.fromtimestamp(at, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def epoch(at: str) -> float:
    """The list's time back to seconds since 1970."""
    return datetime.fromisoformat(at.replace("Z", "+00:00")).timestamp()


def _day(at: float) -> str:
    return datetime.fromtimestamp(at, timezone.utc).strftime("%Y-%m-%d")


def fit(body: dict[str, Any], limit: int = BODY_LIMIT,
        whole: tuple[str, ...] = ()) -> dict[str, Any]:
    """The body, with its longest strings shortened until it is under ``limit``.

    Shortened, never dropped: what is left of a long command or answer is still
    worth more than a hole, and ``_cut`` lists the fields that were shortened.

    The top-level fields named in ``whole`` are never shortened, so a body that
    needs them is kept over ``limit`` rather than cut: a run's brief is what the
    run is told to do, read back from this list when it starts, and a brief cut
    to fit lost its last part without anybody being told (night 14 of the
    nightly feature run, 17 October 2026, was given its brief without what
    Parameters asked of it).
    """
    text = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
    if len(text.encode("utf-8")) <= limit:
        return body
    body = json.loads(text)  # a copy we are free to change
    # The fields kept whole do not count against the limit: the rest is fitted to it on its
    # own. Counting them left a brief over the limit nothing for the rest, so every other
    # field was halved again and again, and run db78bd19 was started with the model
    # "claude [cut]" and the title "Auto c [cut]" (17 October 2026).
    kept = {name: body.pop(name) for name in whole if name in body}
    cut: list[str] = []
    for _ in range(64):
        path, value = _longest_string(body)
        if path is None:
            break
        size = len(json.dumps(body, ensure_ascii=False).encode("utf-8"))
        if size <= limit:
            break
        keep = max(200, len(value) - (size - limit) - 64)
        if keep >= len(value):
            keep = len(value) // 2
        _set(body, path, value[:keep] + " [cut]")
        name = ".".join(str(p) for p in path)
        if name not in cut:
            cut.append(name)
    body.update(kept)
    if cut:
        body["_cut"] = cut
    return body


def _longest_string(node: Any, path: tuple = ()) -> tuple[tuple | None, str]:
    best: tuple[tuple | None, str] = (None, "")
    if isinstance(node, str):
        return path, node
    items = node.items() if isinstance(node, dict) else enumerate(node) if isinstance(node, list) else ()
    for key, value in items:
        found = _longest_string(value, path + (key,))
        if found[0] is not None and len(found[1]) > len(best[1]):
            best = found
    return best


def _set(node: Any, path: tuple, value: str) -> None:
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value


class ListFile:
    """The one list. Only one process may write it, and that is this object's owner."""

    def __init__(self, root: str | os.PathLike[str], *,
                 clock: Callable[[], float] = time.time,
                 sync_every: float | None = SYNC_EVERY) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._clock = clock
        self._lock = threading.Lock()
        self._listeners: list[Listener] = []
        self._fh = None
        self._fh_day: str | None = None
        self._dirty = False
        #: (first n in the file, file), oldest first, so a read from n can skip
        #: whole days it does not need.
        self._index: list[tuple[int, Path]] = []
        self._last_n = 0
        self._repaired: list[tuple[str, int]] = []
        self._open_existing()
        self._stop = threading.Event()
        self._syncer: threading.Thread | None = None
        if sync_every:
            self._syncer = threading.Thread(target=self._sync_loop, args=(sync_every,),
                                            name="list-sync", daemon=True)
            self._syncer.start()
        for name, dropped in self._repaired:
            self.append("list.repaired", body={"file": name, "dropped_bytes": dropped})

    # -- opening -----------------------------------------------------------

    def files(self) -> list[Path]:
        return sorted(self.root.glob("*.jsonl"))

    def _open_existing(self) -> None:
        for path in self.files():
            self._trim_partial(path)
            first = _first_n(path)
            if first is not None:
                self._index.append((first, path))
        if self._index:
            last = _last_n(self._index[-1][1])
            self._last_n = last or 0

    def _trim_partial(self, path: Path) -> None:
        """Cut a last line that a power cut left without its end."""
        size = path.stat().st_size
        if size == 0:
            return
        with path.open("rb+") as fh:
            fh.seek(-1, os.SEEK_END)
            if fh.read(1) == b"\n":
                return
            # Walk back to the last complete line.
            pos = size
            chunk = 4096
            keep = 0
            while pos > 0:
                start = max(0, pos - chunk)
                fh.seek(start)
                data = fh.read(pos - start)
                at = data.rfind(b"\n")
                if at >= 0:
                    keep = start + at + 1
                    break
                pos = start
            fh.truncate(keep)
            self._repaired.append((path.name, size - keep))

    # -- writing -----------------------------------------------------------

    def append(self, kind: str, *, run: str | None = None, by: str = "program",
               body: dict[str, Any] | None = None,
               whole: tuple[str, ...] = ()) -> dict[str, Any]:
        """Add one entry and return it. Every listener hears it before this returns.

        ``whole`` names the body's fields that are kept whole however long (`fit`)."""
        if not kind or not isinstance(kind, str):
            raise ValueError("an entry needs a kind")
        body = fit(dict(body or {}), whole=whole)
        with self._lock:
            now = self._clock()
            entry = {"n": self._last_n + 1, "at": iso(now), "run": run, "kind": kind,
                     "by": by, "body": body}
            line = json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n"
            fh = self._file_for(now, entry["n"])
            fh.write(line.encode("utf-8"))
            fh.flush()
            self._dirty = True
            self._last_n = entry["n"]
        for listener in list(self._listeners):
            try:
                listener(entry)
            except Exception:  # a listener must never lose an entry for the others
                import logging

                logging.getLogger("one.list").exception("a list listener failed on %s", kind)
        return entry

    def _file_for(self, now: float, n: int):
        day = _day(now)
        if self._fh is None or self._fh_day != day:
            if self._fh is not None:
                self._fh.flush()
                os.fsync(self._fh.fileno())
                self._fh.close()
            path = self.root / f"{day}.jsonl"
            fresh = not path.exists() or path.stat().st_size == 0
            self._fh = path.open("ab")
            self._fh_day = day
            if fresh:
                self._index.append((n, path))
        return self._fh

    def _sync_loop(self, every: float) -> None:
        while not self._stop.wait(every):
            self.sync()

    def sync(self) -> None:
        with self._lock:
            if self._fh is not None and self._dirty:
                os.fsync(self._fh.fileno())
                self._dirty = False

    def close(self) -> None:
        self._stop.set()
        self.sync()
        with self._lock:
            if self._fh is not None:
                self._fh.close()
                self._fh = None

    def scrub(self, run: str, *, keep_kinds: frozenset[str] = frozenset({"run.forgotten"})) -> int:
        """Take every entry about one run out of every file, and say how many went.

        The one exception to "never changed": a run the person asked to be
        forgotten (``run.forgotten``) is forgotten, words and all, and keeping
        its entries would keep every word of it. Only the entries whose ``run``
        is that run go, but those of ``keep_kinds``, which say only that it was
        forgotten; every other entry stays as it was, with its number. Each
        file is written whole beside itself and put in its place in one step,
        under the list's own lock, with the open file closed first so the next
        entry opens it again.
        """
        if not run:
            return 0
        dropped = 0
        with self._lock:
            if self._fh is not None:
                self._fh.flush()
                os.fsync(self._fh.fileno())
                self._fh.close()
                self._fh = None
                self._fh_day = None
            for path in self.files():
                kept: list[bytes] = []
                gone = 0
                with path.open("rb") as fh:
                    for raw in fh:
                        try:
                            entry = json.loads(raw)
                        except ValueError:
                            kept.append(raw)
                            continue
                        if entry.get("run") == run and entry.get("kind") not in keep_kinds:
                            gone += 1
                            continue
                        kept.append(raw)
                if not gone:
                    continue
                tmp = path.with_name(path.name + ".scrub")
                with tmp.open("wb") as out:
                    out.writelines(kept)
                    out.flush()
                    os.fsync(out.fileno())
                os.replace(tmp, path)
                dropped += gone
            self._index = [(first, path) for path in self.files()
                           if (first := _first_n(path)) is not None]
        return dropped

    # -- reading -----------------------------------------------------------

    @property
    def last_n(self) -> int:
        return self._last_n

    def listen(self, listener: Listener) -> Callable[[], None]:
        """Hear every entry as it is added. Returns the function that stops it."""
        self._listeners.append(listener)

        def stop() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return stop

    def read(self, since: int = 0, *, run: str | None = None,
             kinds: set[str] | frozenset[str] | None = None) -> Iterator[dict[str, Any]]:
        """Every entry after number ``since``, oldest first, optionally one run's only."""
        with self._lock:
            index = list(self._index)
            if self._fh is not None:
                self._fh.flush()
        start = 0
        for i, (first, _path) in enumerate(index):
            if first <= since + 1:
                start = i
        for _first, path in index[start:]:
            with path.open("rb") as fh:
                for raw in fh:
                    if not raw.endswith(b"\n"):
                        break  # being written right now; the listener will have it
                    try:
                        entry = json.loads(raw)
                    except ValueError:
                        continue
                    if entry.get("n", 0) <= since:
                        continue
                    if run is not None and entry.get("run") != run:
                        continue
                    if kinds is not None and entry.get("kind") not in kinds:
                        continue
                    yield entry


def _first_n(path: Path) -> int | None:
    with path.open("rb") as fh:
        for raw in fh:
            try:
                return int(json.loads(raw)["n"])
            except (ValueError, KeyError, TypeError):
                continue
    return None


def _last_n(path: Path) -> int | None:
    size = path.stat().st_size
    if size == 0:
        return None
    back = 65536
    with path.open("rb") as fh:
        while True:
            back = min(size, back)
            fh.seek(size - back)
            lines = fh.read().splitlines()
            # The first line read is only whole when the read began at the file's start: a
            # last entry longer than the read (a long brief, kept whole) is read again from
            # further back, never taken for a list with no entries.
            if back < size:
                lines = lines[1:]
            for raw in reversed(lines):
                try:
                    return int(json.loads(raw)["n"])
                except (ValueError, KeyError, TypeError):
                    continue
            if back >= size:
                return None
            back *= 4
