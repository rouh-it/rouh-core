"""A box handed to a run as a file: put in, read back for redacting, and shredded.

Petar, 2 November 2026: "things don't need to go in chat, you can simply use that info and pass it
around in files as you do work". Rouh hands a run the boxes the person named (`rouh/boxes.py`,
"Handing a box to a job"); the program collects what is in them from Rouh once, as the run starts,
and ``asuser.py secrets-put`` writes each one as the run's own user at ``<cwd>/.secrets/box-<n>``:
the folder 0700, the file 0600, beside a ``.gitignore`` of ``*``. The brief names the path only.

When the run ends, ``asuser.py secrets-shred`` reads them one last time to scrub the run's own
transcript of anything they held, then overwrites each with random bytes and deletes it. While the
run lives, ``asuser.py transcript --secrets`` redacts them from every line the program reads.

Standard library only: ``asuser.py`` loads this file by path under ``python3 -I``.
"""
from __future__ import annotations

import contextlib
import json
import os
import re
import shutil

#: The folder, inside the folder a run starts in, and each box's file in it.
DIR = ".secrets"
FILE = re.compile(r"box-(\d{1,6})")
#: What contents become wherever they turn up; the same words as Rouh's (`boxes.REDACTED`).
REDACTED = "[box {n}, redacted]"
#: Contents shorter than this are never looked for.
LEAST = 4


def folder(cwd: str) -> str:
    return os.path.join(cwd, DIR)


def put(cwd: str, boxes: list[dict]) -> list[str]:
    """Write each ``{"number", "content"}`` into ``<cwd>/.secrets``. Returns the paths written."""
    where = folder(cwd)
    if os.path.islink(where):
        raise OSError(f"{where} is a link, so nothing was written there")
    os.makedirs(where, mode=0o700, exist_ok=True)
    os.chmod(where, 0o700)
    with open(os.path.join(where, ".gitignore"), "w") as fh:
        fh.write("*\n")
    written = []
    for one in boxes:
        number = int(one["number"])
        path = os.path.join(where, f"box-{number}")
        with contextlib.suppress(FileNotFoundError):
            os.unlink(path)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(str(one.get("content") or ""))
        written.append(path)
    return written


def read(where: str) -> list[tuple[int, str]]:
    """What each box file in the folder ``where`` holds, for redacting. Never printed."""
    out: list[tuple[int, str]] = []
    if not where or os.path.basename(os.path.normpath(where)) != DIR or os.path.islink(where):
        return out
    try:
        names = os.listdir(where)
    except OSError:
        return out
    for name in names:
        m = FILE.fullmatch(name)
        if not m:
            continue
        path = os.path.join(where, name)
        if os.path.islink(path):
            continue
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                out.append((int(m.group(1)), fh.read()))
        except OSError:
            continue
    return out


def _forms(content: str) -> set[str]:
    return {f for f in (content, content.strip(), json.dumps(content)[1:-1],
                        json.dumps(content, ensure_ascii=False)[1:-1]) if f and len(f) >= LEAST}


def redact(text: str, pairs: list[tuple[int, str]]) -> str:
    """``text`` with every box's exact contents replaced, as it is and as JSON writes it."""
    if not text or not pairs:
        return text
    for number, content in sorted(pairs, key=lambda p: -len(p[1] or "")):
        if not content or len(content) < LEAST:
            continue
        mark = REDACTED.format(n=number)
        for form in _forms(content):
            if form in text:
                text = text.replace(form, mark)
    return text


def redact_bytes(data: bytes, pairs: list[tuple[int, str]]) -> bytes:
    if not data or not pairs:
        return data
    text = data.decode("utf-8", "surrogateescape")
    clean = redact(text, pairs)
    return data if clean == text else clean.encode("utf-8", "surrogateescape")


def scrub(path: str, pairs: list[tuple[int, str]]) -> bool:
    """Rewrite one file with every box's contents redacted, in place. True when it changed."""
    if not pairs or os.path.islink(path) or not os.path.isfile(path):
        return False
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError:
        return False
    clean = redact_bytes(data, pairs)
    if clean == data:
        return False
    tmp = path + ".scrub"
    try:
        with open(tmp, "wb") as fh:
            fh.write(clean)
        os.chmod(tmp, os.stat(path).st_mode & 0o777)
        os.replace(tmp, path)
    except OSError:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        return False
    return True


def _overwrite(path: str) -> None:
    try:
        if os.path.islink(path):
            return
        size = os.path.getsize(path)
        with open(path, "r+b", buffering=0) as fh:
            for _ in range(2):
                fh.seek(0)
                fh.write(os.urandom(max(size, 1)))
                os.fsync(fh.fileno())
    except OSError:
        pass


def shred(cwd: str, scrub_too: list[str] = ()) -> dict:
    """Scrub ``scrub_too`` of what the boxes held, then overwrite and delete them and their folder."""
    where = folder(cwd)
    if os.path.islink(where):
        with contextlib.suppress(OSError):
            os.unlink(where)
        return {"shredded": 0, "scrubbed": 0}
    if not os.path.isdir(where):
        return {"shredded": 0, "scrubbed": 0}
    pairs = read(where)
    scrubbed = sum(1 for path in scrub_too if scrub(path, pairs))
    count = 0
    for name in os.listdir(where):
        path = os.path.join(where, name)
        _overwrite(path)
        with contextlib.suppress(OSError):
            os.unlink(path)
        count += bool(FILE.fullmatch(name))
    shutil.rmtree(where, ignore_errors=True)
    return {"shredded": count, "scrubbed": scrubbed}
