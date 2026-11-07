"""Throwaway git checkouts, for the tests about the two version chips.

Both chips in the top bar answer the same question about two different services:
which commit is this service answering from, and which commit is waiting for it
on ``origin/main`` in that service's own checkout. Testing that honestly needs
real git and not a stand-in, because "the commit ``origin/main`` is at in this
folder" is a question only git can answer, and a fake that answered it would be
the thing under test.

So this makes the smallest world in which the question has a real answer: an
origin with a ``main``, and a clone of it that is a service's checkout. A test
then moves one of them and looks at the chip.
"""
from __future__ import annotations

import subprocess
from pathlib import Path


def git(*args: str, cwd: Path) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                          text=True).stdout.strip()


def head(folder: Path, ref: str = "HEAD") -> str:
    """The short commit a ref is at, as it is shown on a chip."""
    return git("rev-parse", "--short=7", ref, cwd=folder)


def an_origin(folder: Path) -> Path:
    """A repository with one commit on ``main``, standing in for GitHub."""
    folder.mkdir(parents=True, exist_ok=True)
    git("init", "-q", "-b", "main", ".", cwd=folder)
    git("config", "user.name", "Test", cwd=folder)
    git("config", "user.email", "test@example.com", cwd=folder)
    write(folder, "first")
    git("add", "-A", cwd=folder)
    git("commit", "-q", "-m", "first", cwd=folder)
    return folder


def a_checkout(origin: Path, into: Path) -> Path:
    """A clone of that origin, standing in for a service's own checkout.

    This is ``/var/www/rouh/app`` or ``/srv/one/app``: the folder a service is
    started from, and the folder its deploy fetches into.
    """
    git("clone", "-q", "--local", "--branch", "main", str(origin), str(into),
        cwd=origin.parent)
    git("config", "user.name", "Test", cwd=into)
    git("config", "user.email", "test@example.com", cwd=into)
    return into


def a_service(folder: Path, name: str) -> tuple[Path, Path]:
    """An origin and a checkout of it, which is one whole service's world."""
    origin = an_origin(folder / f"{name}-origin")
    return origin, a_checkout(origin, folder / f"{name}-app")


def publish(origin: Path, checkout: Path, message: str = "newer") -> str:
    """Merge a commit into that service's `main`, fetch it, and say its commit.

    This is "somebody merged while the old build carried on serving": the
    checkout stays where it is, standing on the commit the running service was
    started from, and ``origin/main`` moves ahead of it.
    """
    write(origin, message)
    git("add", "-A", cwd=origin)
    git("commit", "-q", "-m", message, cwd=origin)
    git("fetch", "-q", "origin", cwd=checkout)
    return head(checkout, "origin/main")


def write(folder: Path, what: str) -> None:
    (folder / "what-changed.txt").write_text(what + "\n")
