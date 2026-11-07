"""The runs' checkouts, and putting a run's work where it belongs.

A run works in a space (``config.Space``, D42): the assistant, whose
repository is the person's workspace; any other repository added as a space,
Rouh's own code among them; a folder already on the server, added as it is
(D43); or a folder of its own. A run in a repository works in its own git
checkout of it, on a branch of its own, so it never touches anyone else's work
while it runs. When it finishes a turn, what it committed is saved
(:meth:`Documents.land`): put on top of the latest main and pushed, or, in a
repository with a development branch, pushed on its own branch for a pull
request. The workspace copy on the server takes the assistant's work in at
once (``runs.py``); no other copy is kept in step. A run in a folder
added as it is works in that folder directly, like a terminal, and nothing is
saved for it.

A checkout is a whole copy of its repository, so it does not outlive its run
for long: once the run has ended with nothing left unsaved, it is removed
(``runs.py``), and carrying the run on later makes a fresh one.

Everything here happens as the run's user, ``assistant``, through
``asuser.py`` under sudo. That user owns the workspace copy, every space's
clone and the server's GitHub key, and may itself use sudo (D42). The program
holds no key to GitHub.

Step 07: "anything a person reads is a file". The documents stay plain files
in folders, and git stays the way back.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import secrets
from datetime import date
from pathlib import Path
from typing import Any

from .config import Settings, Space
from .rules import SPACE_NAME

log = logging.getLogger("one.documents")

_SLUG = re.compile(r"[^a-z0-9]+")
#: A repository named the way GitHub shows it: owner/name.
_GITHUB_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9._-]+$")
_ORIGIN = re.compile(r'\[remote "origin"\][^\[]*?\burl\s*=\s*(\S+)', re.S)
#: A project's name, as the folder it is made in under folders_dir (D44):
#: one folder, or a path of them, never going up.
_PROJECT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*(/[A-Za-z0-9][A-Za-z0-9._-]*)*$")


def slugify(text: str, words: int = 4, limit: int = 32) -> str:
    parts = [p for p in _SLUG.sub(" ", (text or "").lower()).split() if p][:words]
    return ("-".join(parts) or "run")[:limit].strip("-") or "run"


def github_name(url: str) -> str:
    """owner/name for a GitHub address, or the address as it is."""
    found = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?/?$", url or "")
    return found.group(1) if found else (url or "")


class DocumentsError(RuntimeError):
    pass


class Documents:
    def __init__(self, settings: Settings) -> None:
        self.s = settings

    def _sp(self, space: str | None) -> Space:
        return self.s.space(space)

    # -- spaces ------------------------------------------------------------------

    def has_space(self, name: str) -> bool:
        sp = self._sp(name)
        return sp.repo is None or os.path.isdir(os.path.join(sp.repo, ".git"))

    def spaces(self) -> list[dict[str, Any]]:
        """Every space a run can work in: the assistant first, then each one added."""
        out = [{"name": "assistant", "repo": github_name(self._origin(self.s.workspace)),
                "kind": "repository", "default": True}]
        root = Path(self.s.spaces_dir)
        try:
            entries = sorted(root.iterdir(), key=lambda p: p.name)
        except OSError:
            entries = []
        for entry in entries:
            if entry.is_symlink():
                out.append({"name": entry.name, "folder": os.readlink(entry), "kind": "folder"})
            elif (entry / ".git").is_dir():
                out.append({"name": entry.name, "repo": github_name(self._origin(str(entry))),
                            "kind": "repository"})
        return out

    @staticmethod
    def _origin(repo: str) -> str:
        """The repository's own address, read from its git config as a plain file."""
        try:
            text = (Path(repo) / ".git" / "config").read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
        found = _ORIGIN.search(text)
        return found.group(1) if found else ""

    @staticmethod
    def _space_name(name: str | None, given: str) -> str:
        """The space's name: the one asked for, or the repository's or folder's own."""
        base = re.sub(r"\.git$", "", given.rstrip("/").rsplit("/", 1)[-1])
        name = re.sub(r"[^a-z0-9._-]+", "-", (name or base).lower()).strip("-.")
        if not SPACE_NAME.match(name) or name in ("assistant", "scratch"):
            raise DocumentsError(f"{name!r} cannot be a space's name")
        return name

    async def add_space(self, repo: str = "", name: str | None = None, *,
                        folder: str = "") -> dict[str, Any]:
        """Add a space: a repository by its GitHub name, or a folder, by its project's name.

        A folder is made under folders_dir if it is not there yet (D44), or
        given by its whole path, and added as it is: runs work in it directly
        (D43). A repository is cloned. A bare repository on this machine,
        given by its path, is cloned like one on GitHub.
        """
        folder = (folder or "").strip()
        if folder:
            if folder.startswith("/"):
                path = folder
            elif _PROJECT.match(folder):
                path = str(Path(self.s.folders_dir) / folder)
            else:
                raise DocumentsError(f"{folder!r} cannot be a project's name: use letters, "
                                     "digits, dots, dashes and underscores")
            name = self._space_name(name, path)
            got = await self.call("link", "--path", path, "--name", name, "--create",
                                  "--root", self.s.spaces_dir, "--runs", self.s.runs_dir,
                                  user=self.s.run_as)
            if not got.get("ok"):
                raise DocumentsError(f"could not add {path}: {got.get('reason')}")
            return {"name": name, "folder": got.get("path"), "kind": "folder",
                    "flow": "in place", "made": bool(got.get("made"))}
        repo = (repo or "").strip()
        if repo.startswith("/"):
            what = await self.call("inspect", "--path", repo, user=self.s.run_as)
            if not what.get("bare"):
                raise DocumentsError(f"{repo} is not a repository: add a folder as a folder")
            url = repo
        elif _GITHUB_NAME.match(repo):
            url = f"git@github.com:{repo}.git"
        elif repo.startswith(("git@", "ssh://", "https://", "file://")):
            url = repo
        else:
            raise DocumentsError(f"{repo!r} is not a repository's GitHub name, owner/name")
        name = self._space_name(name, repo)
        got = await self.call("clone", "--url", url, "--path", str(Path(self.s.spaces_dir) / name),
                              "--root", self.s.spaces_dir, user=self.s.run_as, timeout=1900.0)
        if not got.get("ok"):
            raise DocumentsError(f"could not add {repo}: {got.get('reason')}")
        return {"name": name, "repo": github_name(url), "kind": "repository",
                "target": got.get("target"), "flow": got.get("flow")}

    # -- running asuser.py -------------------------------------------------------

    def asuser_argv(self, *args: str, user: str = "") -> list[str]:
        base = [self.s.asuser_python, "-I", str(self.s.asuser_path), *args]
        if user:
            return [self.s.sudo, "-n", "-u", user, *base]
        return base

    async def call(self, *args: str, user: str = "", stdin: bytes | None = None,
                   timeout: float = 180.0) -> dict:
        argv = self.asuser_argv(*args, user=user)
        proc = await asyncio.create_subprocess_exec(
            *argv, stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            out, err = await asyncio.wait_for(proc.communicate(stdin), timeout)
        except asyncio.TimeoutError:
            proc.kill()
            raise DocumentsError(f"{args[0]} took longer than {timeout:.0f} seconds")
        lines = [line for line in out.decode("utf-8", "replace").splitlines() if line.strip()]
        if not lines:
            raise DocumentsError(f"{args[0]} said nothing (exit {proc.returncode}): "
                                 f"{err.decode('utf-8', 'replace').strip()[:400]}")
        try:
            return json.loads(lines[-1])
        except ValueError:
            raise DocumentsError(f"{args[0]} said something that is not JSON: {lines[-1][:200]}")

    # -- checkouts ---------------------------------------------------------------

    def branch_for(self, run_id: str, title: str) -> str:
        return f"one/{date.today().isoformat()}-{slugify(title)}-{run_id}"

    async def make_checkout(self, run_id: str, title: str, space: str, *,
                            again: dict[str, Any] | None = None) -> dict[str, Any]:
        """A folder for the run to work in: its own checkout, or a folder.

        ``own`` is where the run's own files go, its brief and its hooks' key:
        inside its checkout, or, in a folder added as it is, in a folder of the
        run's own beside it, so the person's folder never holds them.

        `again` is the run itself when it is carried on after its checkout was
        removed. Work pushed on its own branch is not on the development
        branch, so the fresh checkout starts from that branch instead.
        """
        sp = self._sp(space)
        if sp.in_place:
            mine = str(Path(sp.runs) / run_id)
            await self._hide_own_files(sp, mine)
            return {"cwd": sp.folders, "branch": None, "repo": None, "target": None,
                    "flow": "in place", "own": f"{mine}/.one"}
        path = str(Path(sp.folders) / run_id)
        if not sp.repo:
            await self._hide_own_files(sp, path)
            return {"cwd": path, "branch": None, "repo": None, "target": None, "flow": None,
                    "own": f"{path}/.one"}
        resume = bool(again and again.get("flow") == "branch" and again.get("pushed"))
        branch = str(again["pushed"]) if resume else self.branch_for(run_id, title)
        base = f"origin/{branch}" if resume else None
        got = await self._worktree(sp, path, branch, base)
        if not got.get("ok") and "already exists" in str(got.get("reason")):
            # A run carried on after its checkout was removed: its old folder,
            # or its branch, may still be taken. A fresh one.
            extra = secrets.token_hex(2)
            path = f"{path}-{extra}"
            if not resume:
                branch = f"{branch}-{extra}"
            got = await self._worktree(sp, path, branch, base)
        if not got.get("ok"):
            raise DocumentsError(f"could not make the run's checkout: {got.get('reason')}")
        await self._hide_own_files(sp, path)
        if resume:
            target, flow = again.get("target"), "branch"
        else:
            target, flow = got.get("target") or sp.target, got.get("flow") or "main"
        return {"cwd": path, "branch": branch, "repo": sp.repo, "base_sha": got.get("base_sha"),
                "target": target, "flow": flow, "own": f"{path}/.one"}

    async def _worktree(self, sp: Space, path: str, branch: str, base: str | None) -> dict:
        if base is None:
            base = "auto" if sp.target == "auto" else f"origin/{sp.target}"
        return await self.call("worktree-add", "--repo", sp.repo or "", "--path", path,
                               "--branch", branch, "--base", base, "--runs", sp.runs, "--fetch",
                               user=sp.user)

    async def _hide_own_files(self, sp: Space, path: str) -> None:
        """Keep the run's brief and hook settings out of git, whatever the run commits.

        A ``.gitignore`` of ``*`` inside ``.one/`` makes git ignore everything
        in that folder, itself included, so ``git add -A`` in the run picks up
        none of it and the repository's own files are not changed. Found by
        the end-to-end test on 14 September: without it the brief and the
        hook key went to main with the run's first commit.
        """
        got = await self.call("write", "--path", f"{path}/.one/.gitignore", "--runs", sp.runs,
                              "--mode", "644", stdin=b"*\n", user=sp.user)
        if not got.get("ok"):
            raise DocumentsError(f"could not make the run's folder: {got.get('reason')}")

    async def write(self, path: str, data: bytes | str, *, space: str, mode: str = "600") -> None:
        if isinstance(data, str):
            data = data.encode("utf-8")
        sp = self._sp(space)
        got = await self.call("write", "--path", path, "--runs", sp.runs, "--mode", mode,
                              stdin=data, user=sp.user)
        if not got.get("ok"):
            raise DocumentsError(f"could not write {path}: {got.get('reason')}")

    async def put_secrets(self, cwd: str, boxes: list[dict], *, space: str) -> int:
        """Put the boxes handed to a run in its ``.secrets`` folder, as its own user (``sealed.py``).

        What is in them goes on stdin, never on a command line, and nothing of it is said back.
        """
        sp = self._sp(space)
        got = await self.call("secrets-put", "--cwd", cwd, "--runs", sp.runs,
                              stdin=json.dumps({"boxes": boxes}).encode("utf-8"), user=sp.user)
        if not got.get("ok"):
            raise DocumentsError(f"the boxes could not be put in the run's folder: {got.get('reason')}")
        return int(got.get("written") or 0)

    async def read_secrets(self, cwd: str, *, space: str) -> list[tuple[int, str]]:
        """What a run's boxes hold, for scrubbing the program's own records of it. Never said."""
        sp = self._sp(space)
        try:
            got = await self.call("secrets-read", "--cwd", cwd, "--runs", sp.runs, user=sp.user)
        except DocumentsError:
            raise DocumentsError("the run's boxes could not be read to scrub its terminal") from None
        return [(int(b["number"]), str(b.get("content") or "")) for b in got.get("boxes") or []]

    async def shred_secrets(self, cwd: str, *, space: str, scrub: list[str] = ()) -> dict:
        """Scrub the run's transcript of what its boxes held, then shred them."""
        sp = self._sp(space)
        extra = [x for path in scrub if path for x in ("--scrub", path)]
        return await self.call("secrets-shred", "--cwd", cwd, "--runs", sp.runs, *extra,
                               user=sp.user)

    async def drop(self, folder: str, name: str, data: bytes, *, space: str,
                   mode: str = "600") -> str:
        """Put a file dropped on a run's terminal in its own folder (D52).

        Nothing is overwritten: the path that comes back is the name the file
        was given, which is ``name`` unless something of that name was there.
        """
        sp = self._sp(space)
        got = await self.call("drop", "--path", f"{folder}/{name}", "--runs", sp.runs,
                              "--mode", mode, stdin=data, user=sp.user)
        if not got.get("ok"):
            raise DocumentsError(f"could not put {name} in {folder}: {got.get('reason')}")
        return str(got["path"])

    async def follow(self) -> dict:
        """Bring the server's own copy of the workspace up to main: a fast-forward only."""
        sp = self._sp("assistant")
        return await self.call("follow", "--repo", sp.repo or "", "--target", sp.target,
                               user=sp.user)

    async def land_kept(self, branch: str) -> dict:
        """Land commits ``follow`` found made on the copy's own main and kept on ``branch``."""
        sp = self._sp("assistant")
        extra = ["--land-dir", self.s.land_dir] if self.s.land_dir else []
        if self.s.claude:
            extra += ["--claude", self.s.claude]
        return await self.call("land-kept", "--repo", sp.repo or "", "--branch", branch,
                               "--runs", sp.runs, "--target", sp.target, *extra,
                               user=sp.user, timeout=1900.0)

    async def seed_trust(self, path: str, *, space: str, bypass: bool = False,
                         engine: str = "claude") -> str:
        """Answer the agent's first-run questions, and give the checkout its MCP servers.

        Returns the file to hand the run with ``--mcp-config``, or "" when
        there is nothing to add: either the checkout already defines every
        server this machine would have given it, or this is Codex, whose
        servers went into its own config instead.
        """
        got = await self.call("seed-trust", "--path", path, "--engine", engine,
                              *(["--bypass"] if bypass else []),
                              user=self._sp(space).user)
        if not got.get("ok"):
            raise DocumentsError(f"could not mark {path} trusted: {got.get('reason')}")
        return got.get("mcp_config") or ""

    def _target(self, sp: Space, target: str | None) -> str:
        return target or (sp.target if sp.target != "auto" else "main")

    async def land(self, path: str, *, run_id: str, space: str, target: str | None = None,
                   flow: str | None = None, branch: str | None = None,
                   title: str = "", base: str = "") -> dict[str, Any]:
        """Save a run's work, through ``land.sh``, which is the only thing that pushes.

        ``title`` and ``base`` are the run's own, and both are for the ladder in
        ``land.sh``: the title is what the conflict record and the card call the
        job, and the base is the commit the run's branch was made from, which is
        the difference between a run that committed nothing and a run whose
        commits are already on main. Without the base the second reads as the
        first, and a change that is live is reported as a run that saved nothing.
        """
        sp = self._sp(space)
        # Only the assistant's notes are committed for the run; in a code
        # repository a change whose tests failed is left uncommitted on purpose.
        extra = [] if sp.leftovers else ["--leave-uncommitted"]
        if flow == "branch" and branch:
            extra += ["--push-branch", branch]
        if title:
            extra += ["--title", title[:120]]
        if base:
            extra += ["--base", base]
        if self.s.land_dir:
            extra += ["--land-dir", self.s.land_dir]
        if self.s.claude:
            # The Claude Code Rouh's merge pass runs, when a collision reaches
            # it in land.sh: the program's own, the one its runs are.
            extra += ["--claude", self.s.claude]
        # The landing takes a lock and a run may have to wait behind another,
        # so it is given longer than the fifteen minutes the lock waits.
        return await self.call("land", "--path", path, "--runs", sp.runs,
                               "--target", self._target(sp, target), "--run", run_id,
                               "--leftover-message", f"Run {run_id}: work left uncommitted when it stopped",
                               *extra, user=sp.user, timeout=1900.0)

    async def status(self, path: str, *, space: str, target: str | None = None,
                     branch: str | None = None, flow: str | None = None,
                     landed_head: str | None = None) -> dict[str, Any]:
        """Whether a checkout still holds anything that is not saved.

        ``landed_head`` is the run's commit its last landing took (``work.landed``):
        only what came after it can be unsaved.
        """
        sp = self._sp(space)
        also = ["--also", branch] if flow == "branch" and branch else []
        if landed_head:
            also += ["--landed-head", landed_head]
        return await self.call("status", "--path", path, "--target", self._target(sp, target),
                               *also, user=sp.user)

    async def remove(self, path: str, branch: str | None, *, space: str) -> dict[str, Any]:
        """Take a run's checkout, and its branch, away."""
        sp = self._sp(space)
        return await self.call("worktree-remove", "--repo", sp.repo or "", "--path", path,
                               "--branch", branch or "", "--runs", sp.runs, user=sp.user)

    async def remove_folder(self, path: str, *, space: str) -> dict[str, Any]:
        """Take a run's own folder away, when it is not a checkout; never anyone else's."""
        sp = self._sp(space)
        return await self.call("rmtree", "--path", path, "--runs", sp.runs, user=sp.user)

    # -- starting things -----------------------------------------------------------

    def agent_argv(self, run_id: str, cwd: str, agent_args: list[str], *, space: str,
                   engine: str = "claude", hook_key: str = "",
                   api_key_file: str = "", browser_port: int = 0) -> list[str]:
        """The command that becomes the run's agent, as the run's own user.

        The hook key is passed on only for a Codex run: Claude Code's hooks
        carry it in the settings file the program writes, mode 600, and putting
        it in the environment as well would spread it for nothing.

        It goes as ``--hook-key=<key>``, in one argument, and that is not a
        matter of taste. A key is ``secrets.token_urlsafe``, whose alphabet has
        a dash in it, so about one key in sixty-four begins with one, and
        ``--hook-key -Xy...`` reads to argparse as a flag with nothing after
        it: ``asuser.py agent: error: argument --hook-key: expected one
        argument``, exit 2, before Codex is started at all. Watched here on 19
        September 2026, in a run that died in the same second it began, was
        restarted twice and ended failed. ``--opt=value`` is the one form whose
        value cannot be mistaken for a flag.

        ``api_key_file`` is only for a run of Codex billed to the OpenAI API
        key (``billing.py``), and it names the file the key was written to,
        never the key: the key is on no command line.
        """
        key = [] if engine != "codex" else [f"--hook-key={hook_key}"]
        if engine == "codex" and api_key_file:
            key.append(f"--api-key-file={api_key_file}")
        if browser_port:
            key.append(f"--browser-port={int(browser_port)}")
        return self.asuser_argv("agent", "--cwd", cwd, "--run", run_id,
                                "--engine", engine, "--binary", self.s.agent_binary(engine),
                                *key, "--", *agent_args, user=self._sp(space).user)

    def shell_argv(self, run_id: str, cwd: str, *, space: str) -> list[str]:
        return self.asuser_argv("shell", "--cwd", cwd, "--run", run_id, user=self._sp(space).user)
