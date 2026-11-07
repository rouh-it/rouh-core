"""A tmux server a test can start, use and destroy without reaching anyone else's.

Several tests in this repository start real tmux servers, and one of them starts
a whole Rouh that opens real windows. On 17 September 2026 that stopped being
a detail: a
worker running the suite in a tmux window took the tmux server Rouh itself
lives in down with it, and three sibling jobs died in the same second with
nothing committed.

The two things that made that possible are both fixed here.

* ``TMUX_TMPDIR`` is not enough. A tmux client reads ``TMUX`` first, and tmux
  sets ``TMUX`` in every pane it opens, so a command run from inside a pane -
  which is where the suite runs on the server - ignores ``TMUX_TMPDIR``
  completely and talks to the server that pane belongs to. `env` below takes
  ``TMUX`` out.
* A socket has to be named. Every command this hands out carries ``-L <label>``
  with a label unique to the test, so there is no such thing as "the" server to
  reach by accident.

Use it like this::

    with tmux_sandbox() as tmux:
        tmux.cli("new-session", "-d", "-s", "mine", "sleep", "60")
        assert "mine" in tmux.cli("list-sessions").stdout
        # ... and on the way out, only this server is stopped.

`env` is what to hand any process the test starts that might touch tmux itself.
"""
from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Mapping


@dataclass
class TmuxSandbox:
    """One throwaway tmux server: its socket label, and where its socket lives."""

    #: The label for ``tmux -L``. Unique per sandbox, never "default".
    label: str
    #: The private ``TMUX_TMPDIR``. tmux puts the socket in ``<dir>/tmux-<uid>``.
    tmpdir: Path
    binary: str = field(default="tmux")

    @property
    def socket_path(self) -> Path:
        """Where tmux puts this server's socket file."""
        return self.tmpdir / f"tmux-{os.getuid()}" / self.label

    def env(self, base: Mapping[str, str] | None = None) -> dict[str, str]:
        """``base`` (or this process's environment) with tmux pointed here.

        ``TMUX`` and ``TMUX_PANE`` are removed, not overwritten: their presence
        is what tells a tmux client it is inside a session, and a client that
        believes that ignores ``TMUX_TMPDIR``.
        """
        env = dict(os.environ if base is None else base)
        env.pop("TMUX", None)
        env.pop("TMUX_PANE", None)
        env["TMUX_TMPDIR"] = str(self.tmpdir)
        return env

    def argv(self, *args: str) -> list[str]:
        """A tmux command line for this server, and never for any other."""
        return [self.binary, "-L", self.label, *args]

    def cli(self, *args: str, timeout: float = 20.0) -> subprocess.CompletedProcess[str]:
        return subprocess.run(self.argv(*args), capture_output=True, text=True,
                              timeout=timeout, env=self.env())

    def windows(self, session: str) -> list[str]:
        """The window names in one session of this server, or nothing if it is gone."""
        out = self.cli("list-windows", "-t", f"={session}", "-F", "#{window_name}")
        return out.stdout.splitlines() if out.returncode == 0 else []

    def close(self) -> None:
        """Stop this server and take its directory away. Never touches another.

        The socket is named on the very line that does the killing, rather than
        left to `argv` to add, so this can only ever reach the throwaway server
        this object started.
        """
        with contextlib.suppress(Exception):
            subprocess.run([self.binary, "-L", self.label, "kill-server"],
                           capture_output=True, text=True, timeout=20, env=self.env())
        # tmux leaves the socket file behind, and the directory is ours, so it
        # goes whole rather than file by file.
        shutil.rmtree(self.tmpdir, ignore_errors=True)


def make_tmux_sandbox(prefix: str = "jv") -> TmuxSandbox:
    """A sandbox, ready to use. The caller closes it.

    The directory is made by hand under /tmp and kept short on purpose: a unix
    socket path is capped at 108 characters by the kernel, and pytest's own
    temporary directory is most of that on some machines. tmux also refuses a
    directory anyone else can write to, hence the mode.
    """
    tmpdir = Path(tempfile.mkdtemp(prefix=f"{prefix}-tmux-", dir="/tmp"))
    tmpdir.chmod(0o700)
    return TmuxSandbox(label=f"{prefix}-{os.getpid()}-{uuid.uuid4().hex[:6]}", tmpdir=tmpdir)


@contextlib.contextmanager
def tmux_sandbox(prefix: str = "jv") -> Iterator[TmuxSandbox]:
    box = make_tmux_sandbox(prefix)
    try:
        yield box
    finally:
        box.close()
