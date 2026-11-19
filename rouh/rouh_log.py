"""Rouh's own log, read by Rouh: in the core process, by words, time and level, with secrets masked.

Petar, 19 November 2026. When iCloud contacts stopped working, nothing could say why: `run_command`
runs in the worker container, which cannot see the core's log, a job's "ssh mozart" was refused,
and its attempt to read the log became a decision that led nowhere. So the core reads its own log
itself, for the chat (`read_rouh_log`) and for any job of the owner's or of Rouh's own through the
job gateway (`job_policy.READS`), with the same masking for both.

**What is read.** In the containers the core's output goes to Docker's log, which nothing inside
the machine can read, so the core also writes every line it logs to `core.log` in its own logs
folder (`install`, from `runtime.py`): rotated at `FILE_BYTES`, `FILE_COUNT` kept, and masked on
the way in by the same filter as every other handler (`redaction.Scrubbing`). On a server where
systemd appends the output to `rouh.log`, that is read too. `files` says which there are.

**What comes back** is the newest `limit` entries that have every one of the words, at the level
asked or above, between `since` and `until`, oldest first; an entry is its line with any
traceback under it. Every entry is put through `redact` before it leaves: everything
`redaction.scrub` masks, and passwords, tokens, Authorization headers, cookies, API keys and
credentials in an address besides.
"""
from __future__ import annotations

import logging
import logging.handlers
import os
import re
import time
from dataclasses import dataclass

from . import redaction

log = logging.getLogger("rouh.rouh_log")

FILE_NAME = "core.log"
FILE_BYTES = 10 * 1024 * 1024
FILE_COUNT = 5
#: Where a server's systemd unit appends the core's output.
SERVER_LOGS = ("/var/www/rouh/logs/rouh.log",)
#: The most entries one read hands back, and the longest one entry may be.
MOST = 300
ENTRY_CHARS = 2000
#: The most bytes one read goes through, newest first, across every file.
SCAN_BYTES = 80 * 1024 * 1024

LEVELS = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "WARN": 30, "ERROR": 40, "CRITICAL": 50}

LINE = re.compile(r"^(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}:\d{2})(?:[,.]\d+)?\s+"
                  r"(DEBUG|INFO|WARNING|ERROR|CRITICAL)\s+(\S+)\s?(.*)$")

#: Besides `redaction.PATTERNS`: credentials of every other shape a line can carry.
MASK = redaction.MASK
_KEEP_NAME = (
    # A header or field that is all secret: its whole value, to the end of the line or the quote.
    re.compile(r"(?i)((?<![A-Za-z0-9_-])(?:proxy-)?authorization['\"]?\s*[:=]\s*['\"]?)"
               r"(?!\[redacted\])((?:[A-Za-z-]+\s+)?[^\s,'\";]+)"),
    re.compile(r"(?i)((?<![A-Za-z0-9_-])(?:set-)?cookie['\"]?\s*[:=]\s*['\"]?)"
               r"(?!\[redacted\])((?:[^\s;,'\"=]+=[^\s;,'\"]*;?\s?)+)"),
    # A named field carrying a secret, quoted any way.
    re.compile(r"(?i)((?<![A-Za-z0-9_])(?:[a-z0-9_-]*(?:api[_-]?key|secret|passw(?:or)?d|passwd|"
               r"token|session(?:_?id)?|csrf[a-z_]*|private[_-]?key|auth[_-]?key|"
               r"hue-application-key|x-api-key))['\"]?\s*[:=]\s*['\"]?)"
               r"(?!\[redacted\])([^\s,&'\"}\];]{4,})"),
    # Credentials in an address: https://user:password@host.
    re.compile(r"(?i)(\b[a-z][a-z0-9+.-]*://[^/\s:@]+:)(?!\[redacted\])([^/\s@]+)(?=@)"),
)
_WHOLE = (
    re.compile(r"(?i)\bbearer\s+(?!\[redacted\])[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"sk-ant-[A-Za-z0-9_-]{10,}"),
    re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}"),
    re.compile(r"\b(?:sk|rk|pk)_(?:live|test)_[A-Za-z0-9]{10,}"),
    re.compile(r"\bwhsec_[A-Za-z0-9]{10,}"),
    re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}"),
    re.compile(r"\bxapp-[A-Za-z0-9-]{10,}"),
    re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{4,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)"),
)


def redact(text: str) -> str:
    """The text with every credential-shaped thing in it masked: `redaction.scrub`, and more."""
    if not text:
        return text or ""
    out = redaction.scrub(str(text))
    for pattern in _KEEP_NAME:
        out = pattern.sub(lambda m: m.group(1) + MASK, out)
    for pattern in _WHOLE:
        out = pattern.sub(MASK, out)
    return out


class _Redacting(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.msg = redact(record.getMessage())
            record.args = ()
        except Exception:  # noqa: BLE001 - a record that cannot be formatted is not ours to fix
            pass
        return True


_FOLDER = ""


def install(folder: str) -> str:
    """Write every line the core logs into `folder`/core.log too, masked. Once; the path, or "".

    Never raises: a core that cannot write its own copy of its log still starts, and says so.
    """
    global _FOLDER
    if not folder:
        return ""
    path = os.path.join(folder, FILE_NAME)
    root = logging.getLogger()
    for handler in root.handlers:
        if isinstance(handler, logging.handlers.RotatingFileHandler) and \
                os.path.realpath(getattr(handler, "baseFilename", "")) == os.path.realpath(path):
            _FOLDER = folder
            return path
    try:
        os.makedirs(folder, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(path, maxBytes=FILE_BYTES,
                                                       backupCount=FILE_COUNT, encoding="utf-8",
                                                       delay=True)
    except OSError as exc:
        log.warning("the core's own log cannot be written to %s: %s", path, exc)
        return ""
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    handler.addFilter(redaction.Scrubbing())
    handler.addFilter(_Redacting())
    root.addHandler(handler)
    _FOLDER = folder
    return path


def files(folder: str | None = None) -> list[str]:
    """Every log file there is to read, newest first: core.log and its rotations, then rouh.log."""
    folder = folder if folder is not None else _FOLDER
    if not folder:
        try:
            from .config import config

            folder = config.logs_path
        except Exception:  # noqa: BLE001
            folder = ""
    out, seen = [], set()
    names = []
    if folder:
        names += [os.path.join(folder, FILE_NAME)]
        names += [os.path.join(folder, f"{FILE_NAME}.{n}") for n in range(1, FILE_COUNT + 1)]
        names += [os.path.join(folder, "rouh.log"), os.path.join(folder, "rouh.log.1")]
    names += list(SERVER_LOGS) + [p + ".1" for p in SERVER_LOGS]
    for name in names:
        try:
            real = os.path.realpath(name)
            if real in seen or not os.path.isfile(real):
                continue
        except OSError:
            continue
        seen.add(real)
        out.append(name)
    return out


@dataclass
class Entry:
    at: float
    level: str
    logger: str
    text: str
    source: str

    def said(self) -> str:
        stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.at))
        return f"{stamp} {self.level} {self.logger} {self.text}"


def _lines_backwards(path: str, budget: list[int]):
    """The file's lines, last first, reading at most what the shared budget has left."""
    try:
        fh = open(path, "rb")
    except OSError:
        return
    with fh:
        fh.seek(0, os.SEEK_END)
        pos = fh.tell()
        rest = b""
        while pos > 0 and budget[0] > 0:
            step = min(65536, pos)
            pos -= step
            fh.seek(pos)
            chunk = fh.read(step)
            budget[0] -= step
            parts = (chunk + rest).split(b"\n")
            rest = parts[0]
            for raw in reversed(parts[1:]):
                yield raw.decode("utf-8", "replace").rstrip("\r")
        if rest and (pos == 0):
            yield rest.decode("utf-8", "replace").rstrip("\r")


def _entries_backwards(path: str, budget: list[int]):
    """The file's entries, newest first, each with the lines under it (a traceback)."""
    under: list[str] = []
    for line in _lines_backwards(path, budget):
        found = LINE.match(line)
        if not found:
            if line.strip():
                under.append(line)
            continue
        day, clock_, level, name, message = found.groups()
        try:
            at = time.mktime(time.strptime(f"{day} {clock_}", "%Y-%m-%d %H:%M:%S"))
        except (ValueError, OverflowError):
            at = 0.0
        text = message + ("\n" + "\n".join(reversed(under)) if under else "")
        under = []
        yield Entry(at, level, name, text, os.path.basename(path))


_SPAN = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(s|sec|secs|seconds?|m|min|mins|minutes?|h|hr|hrs|hours?|"
                   r"d|days?|w|weeks?)\s*(?:ago)?\s*$", re.I)


def when(value, *, now: float | None = None) -> float | None:
    """A moment from what a model says: '2h', '30 minutes', an ISO time (the person's clock when it
    has no offset), or epoch seconds. None for nothing; ValueError for what is not a moment."""
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    now = time.time() if now is None else now
    span = _SPAN.match(text)
    if span:
        n, unit = float(span.group(1)), span.group(2).lower()[0]
        return now - n * {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}[unit]
    if re.fullmatch(r"\d{9,11}(?:\.\d+)?", text):
        return float(text)
    from . import clock

    import datetime as dt

    try:
        moment = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"{text!r} is not a time. Say it like 2h, 30m, 1d or "
                         "2026-11-19T14:00.") from None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=clock.zone())
    return moment.timestamp()


@dataclass
class Read:
    entries: list
    files: list
    scanned_back_to: float
    more: bool


def read(words=None, since=None, until=None, level: str = "", limit: int = 40, logger: str = "",
         folder: str | None = None) -> Read:
    """The newest `limit` entries with every word, at `level` or above, from `logger` (a prefix),
    between `since` and `until`, oldest first, each masked."""
    if isinstance(words, str):
        words = words.split()
    wanted = [str(w).lower() for w in (words or []) if str(w).strip()]
    floor = LEVELS.get(str(level or "").strip().upper(), 0)
    if level and not floor:
        raise ValueError("level is one of DEBUG, INFO, WARNING, ERROR or CRITICAL.")
    start, end = when(since), when(until)
    limit = max(1, min(int(limit or 40), MOST))
    prefix = str(logger or "").strip()
    found: list[Entry] = []
    budget = [SCAN_BYTES]
    oldest = 0.0
    more = False
    paths = files(folder)
    # Each stream - core.log and its rotations, a server's rouh.log - read newest first on its own.
    streams: dict[str, list[str]] = {}
    for path in paths:
        streams.setdefault(os.path.basename(path).split(".log")[0], []).append(path)
    for stream in streams.values():
        mine: list[Entry] = []
        stop = False
        for path in stream:
            for entry in _entries_backwards(path, budget):
                if entry.at:
                    oldest = entry.at if not oldest else min(oldest, entry.at)
                if end is not None and entry.at and entry.at > end:
                    continue
                if start is not None and entry.at and entry.at < start:
                    stop = True
                    break
                if LEVELS.get(entry.level, 0) < floor:
                    continue
                if prefix and not entry.logger.startswith(prefix):
                    continue
                # Words are matched on the masked text, so a secret is never found by guessing it.
                entry.text = redact(entry.text)
                low = (entry.logger + " " + entry.text).lower()
                if any(w not in low for w in wanted):
                    continue
                if len(mine) >= limit:
                    more = True
                    stop = True
                    break
                if len(entry.text) > ENTRY_CHARS:
                    entry.text = entry.text[:ENTRY_CHARS] + " [... cut]"
                mine.append(entry)
            if budget[0] <= 0:
                more = True
            if stop or budget[0] <= 0:
                break
        # Read newest first: turned round, so entries of the same second stay in the file's order.
        found += mine[::-1]
    found.sort(key=lambda e: e.at)
    if len(found) > limit:
        more = True
        found = found[-limit:]
    return Read(found, paths, oldest, more)


def said(got: Read, *, words=None) -> str:
    """What the tool answers: the entries, and where they came from."""
    if not got.files:
        return ("There is no log file to read here yet: the core writes core.log in its logs folder "
                "from its next start.")
    head = (f"{len(got.entries)} entr{'y' if len(got.entries) == 1 else 'ies'} of Rouh's own log"
            + (f" with {' '.join(words) if isinstance(words, list) else words}" if words else "")
            + f", oldest first, from {', '.join(os.path.basename(p) for p in got.files)}"
            + (f" (the files go back to {time.strftime('%Y-%m-%d %H:%M', time.localtime(got.scanned_back_to))},"
               f" server time {time.strftime('%z')})" if got.scanned_back_to else "")
            + ". Secrets are masked as [redacted].")
    if got.more:
        head += " There are more: narrow it with words, since or level, or raise the limit."
    if not got.entries:
        return head + "\n\nNothing matched."
    return head + "\n\n" + "\n".join(e.said() for e in got.entries)


__all__ = ["Entry", "Read", "files", "install", "read", "redact", "said", "when"]
