"""One way of running git against a checkout, for every module that asks git a question.

Each caller wants something different back - the words, None when it did not
work, the bytes, the whole `CompletedProcess`, or an exception - so that part
stays with the caller. What is the same everywhere is how git is started, and
that is here: `git -c safe.directory=<where> -C <where> ...`, with what it says
captured and nothing raised for a non-zero exit.

``safe.directory`` is set because Rouh runs as root out of a checkout owned by
another user, and git refuses to answer at all unless it is told that this path
is expected. A caller that never set it passes ``safe_directory=False`` rather
than gaining it, because adding it changes what git does with a repository
owned by somebody else.

Standard library only: `land.sh` runs `python -m rouh.numbering` with whatever
Python it finds, which may not be the one with Rouh's requirements in it.
"""
from __future__ import annotations

import subprocess
from pathlib import Path


def run(where: str | Path, *args: str, timeout: float, text: bool = True,
        feed: bytes | str | None = None,
        safe_directory: bool = True) -> subprocess.CompletedProcess:
    """Run one git command in `where` and hand back what it did.

    A non-zero exit is the caller's to read. A git that cannot be started, or
    that runs past `timeout`, raises exactly as `subprocess.run` does.
    """
    argv = ["git"]
    if safe_directory:
        argv += ["-c", f"safe.directory={where}"]
    argv += ["-C", str(where), *args]
    return subprocess.run(argv, input=feed, capture_output=True, text=text,
                          timeout=timeout, check=False)
