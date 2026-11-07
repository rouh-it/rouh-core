"""The first thing a worker's window runs, so that a worker that dies at once still says why.

A worker is Claude Code in a tmux window (`crew.py`), and tmux is told two
things about that window once it exists: keep it when its program exits
(`remain-on-exit`), and copy everything it prints into the job's log
(`pipe-pane`). Both used to be said a moment *after* the program had started.
A program that died in that moment - a worker user that does not exist, a flag
the binary refuses, a binary that is not there - was gone before either was
said: its window vanished with whatever it printed, no log was written, and
the job was found "lost" with nothing to say about it.

That is how b0e4656f, "Kept notes missing from the Kvadrat project", died on
24 September 2026, in the second it was started, with no `session.log` and
nothing in the journal. `runuser` had been asked for the user `jarvis`, which
had been renamed `rouh` two days before, and said so on a terminal nobody was
reading any more.

So this stands in front of the worker and closes that gap from both ends:

1. It waits until Rouh has said both things. Rouh writes the file named by
   `--ready` once it has, so everything the worker prints, from its first
   byte, is in the log and on the window's last screen.
2. It runs the worker exactly as it was given, on the same terminal, and
   waits for it. Nothing about the worker's terminal changes: its input,
   output and errors are the window's own, which Claude Code needs.
3. When the worker ends it writes down how, in the file named by `--record`:
   its exit code and how long it lived. Rouh reads that back when it finds the
   job dead (`CrewManager.death_of`). A worker that could not be started at
   all is written down the same way, with what went wrong, and says so on the
   terminal too.

The standard library only, and run by path with `python -I`, because a
worker's window is in the job's own checkout, which may be any repository at
all, and nothing there may be imported by accident.
"""
from __future__ import annotations

import contextlib
import json
import os
import signal
import subprocess
import sys
import time

#: How long to wait for Rouh to say the window is being kept and logged. It is
#: said a few milliseconds after the window opens; this is only the ceiling for
#: a Rouh that died in between, after which the worker starts anyway, because a
#: job that runs unlogged is better than one that never runs.
WAIT_FOR_READY = 15.0


def _parse(argv: list[str]) -> tuple[str, str, list[str]]:
    """``--ready FILE --record FILE -- command...``, in any order before the ``--``."""
    ready = record = ""
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--":
            return ready, record, argv[i + 1:]
        if arg in ("--ready", "--record") and i + 1 < len(argv):
            if arg == "--ready":
                ready = argv[i + 1]
            else:
                record = argv[i + 1]
            i += 2
            continue
        raise SystemExit(f"crew_launch: unexpected argument {arg!r}")
    return ready, record, []


def _wait_for(path: str, limit: float) -> None:
    if not path:
        return
    deadline = time.monotonic() + limit
    while not os.path.exists(path) and time.monotonic() < deadline:
        time.sleep(0.02)


def _write(path: str, data: dict) -> None:
    """Written whole or not at all, so a reader never sees half of it."""
    if not path:
        return
    tmp = f"{path}.tmp"
    with contextlib.suppress(OSError):
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        os.replace(tmp, path)


def main(argv: list[str] | None = None) -> int:
    ready, record, command = _parse(list(sys.argv[1:] if argv is None else argv))
    if not command:
        print("crew_launch: there is no command to run", file=sys.stderr)
        return 2
    _wait_for(ready, WAIT_FOR_READY)

    # A key pressed in the window is the worker's, and the terminal sends it to
    # both of us. These are handlers rather than SIG_IGN on purpose: a handler
    # goes back to the default in the worker when it starts, and an ignored
    # signal would be ignored in the worker too.
    for name in ("SIGINT", "SIGQUIT", "SIGTSTP"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), lambda *_: None)

    started = time.time()
    try:
        child = subprocess.Popen(command)
    except OSError as exc:
        said = f"{command[0]}: {exc.strerror or exc}"
        print(f"The worker could not be started. {said}", file=sys.stderr, flush=True)
        code = 127 if isinstance(exc, FileNotFoundError) else 126
        _write(record, {"started": started, "ended": time.time(), "exit_code": code,
                        "said": said})
        return code
    _write(record, {"started": started, "pid": child.pid})

    # Closing the window hangs the terminal up and stopping a job sends TERM.
    # Either is passed on and then waited for, so what is written down is how
    # the worker ended rather than how this did.
    def forward(signum, _frame):
        with contextlib.suppress(OSError):
            child.send_signal(signum)

    for name in ("SIGHUP", "SIGTERM"):
        signal.signal(getattr(signal, name), forward)

    code = child.wait()
    if code < 0:
        # Killed by a signal: said the way a shell says it.
        code = 128 - code
    _write(record, {"started": started, "ended": time.time(), "exit_code": code,
                    "pid": child.pid})
    return code


if __name__ == "__main__":
    sys.exit(main())
