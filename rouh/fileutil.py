"""Writing a file whole, so that nobody ever reads half of one.

Every file written here goes to a temporary file in the same folder first and
is then renamed over the real one with `os.replace`, which on one filesystem
is all or nothing: a reader sees the old file or the new one, never a file a
killed process stopped writing half way through.

The places that write this way each did it their own way before there was one
helper, and what they did differently is kept as flags rather than smoothed
over, because a temporary name or a mode is something another program can see:

- `spare` names the temporary file. Without it the file is a unique one made
  by `tempfile.mkstemp` in `folder` (the target's own folder unless given),
  ending in `suffix`, which `mkstemp` makes readable by its owner only.
- `keep_mode` and `keep_owner` give the new file the old one's permissions and
  owner, when there is an old one. An owner that cannot be kept is not an error.
- `tidy` removes the temporary file when anything goes wrong on the way. Off,
  it is left where it was, as some callers always have.

Nothing here calls `fsync`. Standard library only, so that anything can load it.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import IO, Any


def write_atomic(path: str | os.PathLike, data: str, *, spare: str | os.PathLike | None = None,
                 suffix: str = "", folder: str | os.PathLike | None = None,
                 encoding: str = "utf-8", newline: str | None = None,
                 keep_mode: bool = False, keep_owner: bool = False, tidy: bool = True) -> None:
    """Write `data` to `path` whole, through a temporary file and a rename."""
    _write(path, lambda fh: fh.write(data), spare=spare, suffix=suffix, folder=folder,
           encoding=encoding, newline=newline, keep_mode=keep_mode, keep_owner=keep_owner,
           tidy=tidy)


def write_json_atomic(path: str | os.PathLike, obj: Any, *, end: str = "",
                      spare: str | os.PathLike | None = None, suffix: str = "",
                      folder: str | os.PathLike | None = None, encoding: str = "utf-8",
                      newline: str | None = None, keep_mode: bool = False,
                      keep_owner: bool = False, tidy: bool = True, **dump_kw: Any) -> None:
    """Write `obj` as JSON to `path` whole, followed by `end`.

    `dump_kw` goes to `json.dump`, which writes straight into the temporary
    file, so a value that cannot be written stops it part way, as it always has.
    """
    def fill(fh: IO[str]) -> None:
        json.dump(obj, fh, **dump_kw)
        if end:
            fh.write(end)

    _write(path, fill, spare=spare, suffix=suffix, folder=folder, encoding=encoding,
           newline=newline, keep_mode=keep_mode, keep_owner=keep_owner, tidy=tidy)


def _write(path: str | os.PathLike, fill: Callable[[IO[str]], Any], *,
           spare: str | os.PathLike | None, suffix: str, folder: str | os.PathLike | None,
           encoding: str, newline: str | None, keep_mode: bool, keep_owner: bool,
           tidy: bool) -> None:
    target = Path(path)
    try:
        if spare is None:
            handle, spare = tempfile.mkstemp(
                dir=target.parent if folder is None else folder, suffix=suffix)
            fh = os.fdopen(handle, "w", encoding=encoding, newline=newline)
        else:
            fh = open(spare, "w", encoding=encoding, newline=newline)
        with fh:
            fill(fh)
        if (keep_mode or keep_owner) and target.exists():
            was = target.stat()
            if keep_mode:
                os.chmod(spare, was.st_mode & 0o7777)
            if keep_owner:
                with contextlib.suppress(OSError):
                    os.chown(spare, was.st_uid, was.st_gid)
        os.replace(spare, path)
    finally:
        if tidy and spare is not None and Path(spare).exists():
            Path(spare).unlink()
