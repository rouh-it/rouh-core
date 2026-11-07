"""The program on the laptop, in a throwaway world, for looking at it in a browser.

    python -m one.tests.dev_server /tmp/one-dev 18031

Makes a git remote, a workspace copy of it, two more repositories added as the
spaces ``code`` and ``rouh``, and a stand-in for each agent - Claude Code and
Codex - in the folder, then runs the program there until stopped. Nothing it
does leaves the folder: it has its own home for the agents' config, its own
socket and its own port.

The ``code`` space is a repository like Rouh's own: nothing a run leaves
uncommitted in it is ever committed for the run, which is the whole difference
between the assistant's notes and a change to code whose tests failed. It is
here so that looking at the program by hand, and the browser tests, can both
see what a run in a code repository does.

``rouh`` is the same kind of repository under the name the real machine uses
for Rouh's own code. A run there is the one that is pushed to main and then
deployed without anybody being asked, so a browser test of that path needs the
space to exist here under exactly that name.
"""
from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
from pathlib import Path

from one.config import Settings
from one.phone import FakePhone
from one.program import serve

FAKE = Path(__file__).resolve().parent / "fake_claude.py"
FAKE_CODEX = Path(__file__).resolve().parent / "fake_codex.py"


def git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def a_repository(folder: Path, name: str) -> Path:
    """A bare remote with one commit on main, and a clone of it to work from."""
    origin, seed = folder / f"{name}.git", folder / f"{name}-seed"
    git("init", "-q", "--bare", "-b", "main", str(origin), cwd=folder)
    git("clone", "-q", str(origin), str(seed), cwd=folder)
    git("config", "user.name", "Dev", cwd=seed)
    git("config", "user.email", "dev@example.com", cwd=seed)
    (seed / "README.md").write_text(f"The {name} repository.\n")
    git("add", "-A", cwd=seed)
    git("commit", "-q", "-m", "start", cwd=seed)
    git("push", "-q", "origin", "HEAD:main", cwd=seed)
    return origin


def world(folder: Path, port: int) -> Settings:
    folder.mkdir(parents=True, exist_ok=True)
    origin, ws, home = folder / "origin.git", folder / "ws", folder / "home"
    spaces = folder / "spaces"
    if not origin.exists():
        git("init", "-q", "--bare", "-b", "main", str(origin), cwd=folder)
        git("clone", "-q", str(origin), str(ws), cwd=folder)
        git("config", "user.name", "Dev", cwd=ws)
        git("config", "user.email", "dev@example.com", cwd=ws)
        (ws / "README.md").write_text("A throwaway workspace.\n")
        git("add", "-A", cwd=ws)
        git("commit", "-q", "-m", "start", cwd=ws)
        git("push", "-q", "origin", "HEAD:main", cwd=ws)
    if not spaces.exists():
        # Repositories added as spaces, the way `add_space` leaves one: a clone
        # under the spaces folder, named after it. "rouh" is Rouh's own code
        # on the real machine, and the name matters: it is what decides that a
        # run's landed work is deployed.
        spaces.mkdir(parents=True)
        for name in ("code", "rouh"):
            git("clone", "-q", str(a_repository(folder, name)), str(spaces / name), cwd=folder)
    home.mkdir(exist_ok=True)
    (home / ".gitconfig").write_text("[user]\n\tname = Dev\n\temail = dev@example.com\n")
    wrapper = folder / "claude"
    wrapper.write_text(f"#!/bin/sh\nexec {sys.executable} {FAKE} \"$@\"\n")
    wrapper.chmod(0o755)
    codex = folder / "codex"
    codex.write_text(f"#!/bin/sh\nexec {sys.executable} {FAKE_CODEX} \"$@\"\n")
    codex.chmod(0o755)
    os.environ["ONE_ASUSER_HOME"] = str(home)
    s = Settings()
    s.data, s.socket = folder / "data", str(folder / "s.sock")
    s.http_host, s.http_port, s.base_path = "127.0.0.1", port, "/one"
    s.public_url = f"http://127.0.0.1:{port}/one"
    s.run_as, s.asuser_python = "", sys.executable
    s.workspace, s.runs_dir, s.scratch_dir = str(ws), str(folder / "runs"), str(folder / "runs/scratch")
    s.spaces_dir, s.folders_dir = str(spaces), str(folder / "www")
    s.claude, s.model = str(wrapper), "fake"
    # Its own landing, never the server's /srv/rouh-land, where a conflict
    # record is a question read out to the owner.
    s.land_dir = str(folder / "land")
    s.codex, s.codex_model = str(codex), "fake-codex"
    if os.environ.get("ONE_TEST_CODEX"):
        # The real Codex, for its sign-in alone (`codex_signin_world`): its device sign-in
        # reaches OpenAI for a real code, and is never approved by anybody but a person.
        s.codex, s.codex_model = os.environ["ONE_TEST_CODEX"], ""
    # A stand-in answers its SessionStart at once, so a real handshake's minute
    # is a minute of a test waiting for nothing.
    s.codex_handshake = 20
    # Not the machine's processor and memory: this program's two runs have
    # nothing to do with what the rest of the machine is busy with, and
    # reading them made a run wait for a reason that had nothing to do with
    # the test looking at it.
    s.cgroup = str(folder)
    # Rouh, for the agent instructions every run starts with: none in a world
    # unless one is named, never the machine's own on port 8021.
    s.rouh_url = os.environ.get("ONE_ROUH_URL", "").rstrip("/")
    s.phone_after = 5
    return s


def main() -> None:
    folder = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/one-dev")
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 18031
    logging.basicConfig(level="INFO", format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(serve(world(folder, port), phone=FakePhone()))


if __name__ == "__main__":
    main()
