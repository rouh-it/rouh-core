"""Background-task delegation for Rouh: hand a real job to Claude Code in tmux.

The voice assistant says "on it", calls :meth:`CrewManager.spawn`, and gets back a
``Crewmate``: one Claude Code session, running in its own tmux window, in its own git
worktree. The assistant does not watch it. Claude Code calls back over HTTP when the
job lands, and :meth:`CrewManager.handle_event` turns that call into a status change.

Everything is recorded in Rouh's database, so the server can restart and pick up
exactly where it was. tmux is the source of truth about who is still alive;
:meth:`CrewManager.reconcile` compares the two and never leaves a dead crewmate
sitting at ``running``.

The record is three tables - ``crewmates``, ``crew_events`` and
``crew_tree_events``, which are `rouh.models.Crewmate`, `CrewEvent` and
`CrewTreeEvent` - in PostgreSQL since 23 September 2026. Until then they were
SQLite tables this module made for itself, by default in a ``crew.sqlite3`` of
the workspace's own when nobody named a file; there is one database now and
every crew manager, on the server or in a check of somebody's own, writes to
whichever one Django is pointed at.


Verification notes (this matters, so it is written down)
--------------------------------------------------------

Everything below was checked on this machine on 2026-09-08 against Claude Code
**2.1.263** (native build, commit 37ae3f38d765) and **tmux 3.7c**. Nothing here is
recalled or guessed.

**The hooks JSON shape is verified.** Three independent sources agree:

1. The shipped ``claude`` binary carries the settings schema. Its own text names the
   five hook types (``command``, ``prompt``, ``agent``, ``http``, ``mcp_tool``) and,
   for the HTTP one, describes ``url`` as "URL to POST the hook input JSON to" and
   ``timeout`` as "Timeout in seconds for this specific request".
2. ``claude doctor`` validates settings files found in the current directory and
   names the file and the offending key. Feeding it a bad event name printed the
   full list of 33 valid hook events; feeding it a bad type printed the five valid
   types. The exact config this module writes passes it with no complaint. That
   check is available at runtime as :meth:`CrewManager.verify_hooks`, and the test
   suite runs it, so a future Claude Code release that changes the schema fails a
   test instead of silently never firing.
3. The user's own working ``~/.claude/settings.json`` uses the same shape for
   ``Stop`` and ``Notification`` and demonstrably fires.

The shape is::

    {"hooks": {"<EventName>": [{"matcher": "...", "hooks": [<entry>, ...]}]}}

``matcher`` is optional and is left out here. For ``Stop`` it is ignored; for
``Notification`` it would filter on the notification subtype (``permission_prompt``,
``idle_prompt``, ``agent_needs_input`` and eleven others), and we want all of them.

**The callback uses the ``http`` hook type, not curl.** Claude Code POSTs the hook
input JSON itself. No shell, no quoting, no dependency on curl being installed. The
crewmate id travels in the query string, which this module controls end to end, so
the POST body can stay exactly what Claude Code sends. Set ``hook_transport="command"``
to fall back to curl (also argv-only, no shell) for an older Claude Code.

This was watched working, not merely validated. A settings file of exactly this shape
was written into a directory, a throwaway HTTP server was put on a local port, and
Claude Code POSTed to it, with the query string intact::

    POST /internal/crew-event?crew=probe123&kind=session_end
    {"session_id": "...", "transcript_path": "...", "cwd": "...",
     "prompt_id": "...", "hook_event_name": "SessionEnd", "reason": "..."}

So the body carries ``hook_event_name``, ``session_id``, ``cwd``, ``prompt_id`` and
``transcript_path``, and the id and kind arrive from the URL. That is the merge
:meth:`CrewManager.handle_event` expects.

**The one thing that would make a crewmate hang for ever: workspace trust.** A
brand-new git worktree is a directory Claude Code has never seen. Interactive Claude
Code stops dead in a new directory and asks::

    Accessing workspace: /private/tmp/...
    Quick safety check: Is this a project you created or one you trust?
      > No, exit
        Yes, I trust this folder

Nobody is watching a crewmate, so that dialog is a deadlock: no work, no hooks, no
callback, for ever. This was reproduced by launching interactive Claude Code in a
fresh directory in tmux and reading the pane. Separately, Claude Code's own error
message says untrusted workspaces also get their hooks thrown away:

    Ignoring N hooks entries from .claude/ settings: this workspace has not been
    trusted. Run Claude Code interactively here once and accept the trust dialog, or
    set projects[<path>].hasTrustDialogAccepted: true in ~/.claude.json.

So this module writes that key for each new worktree before it launches anything
(``seed_trust=True``, on by default), and for the repository the worktree was made
from, which is where Claude Code 2.1.274 files it (``_claude_project_root``). That is the same thing Claude Code's own cloud
runner does. With it, the same directory went straight to the prompt. Turn it off and
crewmates hang on the dialog, which is why it is on.

(Note for anyone testing this: ``claude -p`` skips the trust dialog, so hooks fire in
an untrusted directory in print mode. That is not the case that matters here.
Crewmates run interactive Claude Code on a real terminal, which is the gated one.)

**Mode flags are verified.** ``claude --permission-mode`` accepts, per its own error
message, ``acceptEdits``, ``auto``, ``bypassPermissions``, ``manual``, ``dontAsk``,
``plan``. Inside the binary, ``manual`` is an alias: ``e === "manual" ? "default" : e``.
The in-product help describes the modes as:

* ``default`` (reached by ``manual``) - ask before every edit
* ``acceptEdits`` - edit freely, ask for commands
* ``plan`` - research and propose, never touch files
* ``auto`` - Claude decides what is safe
* ``bypassPermissions`` - skip everything

**The model and the effort are asked for, not assumed.** ``claude --model`` and
``claude --effort <level>`` are which model a crewmate is and how hard it thinks, and
since 27 September 2026 both are the organisation's default pair, asked for at every
start (`rouh/modeldefaults.py`, the ``defaults`` the manager is handed). Before 19
September 2026
nothing passed it and every worker took Claude Code's own default, which is why every
node in the work tree read ``effort high`` however the deployment was configured. Like
``--name`` it is only passed to a build whose ``--help`` mentions it: an older binary
handed a flag it does not know prints one line, exits 1, and the job looks like a
worker that failed with no output.

**Deny rules live in the settings file, not on the command line.** ``--disallowed-tools``
is documented as "comma or space-separated", and every useful rule contains a space
(``Bash(git push:*)``), so passing it there risks being split into nonsense. The
``permissions.deny`` array in the settings file cannot be split. It is passed on the
command line as well, purely as a second line of defence.

**Honesty about what a mode guarantees.** ``local-only`` and ``direct-pr`` are a
permission mode, a set of deny rules and an instruction block. A determined model
could reach a shell another way. The hard boundary is the one that does not depend on
the model behaving: the crewmate works in its own git worktree on its own branch, so
it cannot touch your checkout or the default branch by accident.


tmux facts this module depends on, all measured
-----------------------------------------------

* ``tmux new-window`` with several arguments executes them directly, with no shell.
  A window launched with the argument ``hi there; rm -rf /`` printed that text.
* Window ids (``@4``) are unique while the server lives, but restart at ``@0`` when
  the server dies. So the crewmate id goes in the **window name**, and the name is
  what reconciliation matches on. The id is only a fast path.
* By default a window vanishes when its command exits. ``remain-on-exit on`` keeps it
  with ``pane_dead=1`` and the exit code in ``pane_dead_status``, so the final screen
  can still be read. It is set right after the window is created; if that loses a
  race against an instant crash, the window is simply gone and reconciliation calls
  it ``lost``, which is the right answer anyway.
* ``send-keys -l`` submits on every newline. Multi-line input goes through
  ``load-buffer`` on stdin then ``paste-buffer -p``, which wraps it in bracketed-paste
  markers, so the text arrives as one paste and Enter is sent separately.
"""

from __future__ import annotations

# Run as ``python -m rouh.crew``, this is a command of its own and nothing has
# set Django up yet: the crew's rows are Django's, so it is set up here, before
# anything below can reach for them. Imported by the server, or by anything
# else, this line is not reached, and it never is inside the server, where
# Django is already set up.
#
# The crew's coroutines read and write their rows inline, under a lock, the way
# they always did: the rows are tiny and the database is on this machine. The
# server allows that for the whole process, and so does this command, which
# runs the same coroutines.
if __name__ == "__main__":  # pragma: no cover - the hand check at the bottom
    import os as _os

    _os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    from rouh.project import setup as _setup_django

    _setup_django()

import asyncio
import contextlib
import json
import logging
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import sys
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from . import attachments, browser_handoff, clock
from . import owner as _owner

__all__ = [
    "CrewManager",
    "Crewmate",
    "CrewError",
    "UnknownCrewmate",
    "YoloRefused",
    "TmuxError",
    "MODES",
    "ModeSpec",
    "WorkerProfile",
    "STATUSES",
    "TERMINAL_STATUSES",
    "DEFAULT_CALLBACK_URL",
    "TELEMETRY_KINDS",
    "TREE_KINDS",
    "normalise_kind",
    "is_late_news",
]

LOG = logging.getLogger("rouh.crew")

DEFAULT_CALLBACK_URL = "http://127.0.0.1:8021/internal/crew-event"
DEFAULT_SESSION = "rouh"
DEFAULT_WORKSPACE = Path(os.environ.get("ROUH_CREW_HOME", "~/.rouh/crew")).expanduser()
KEEPALIVE_WINDOW = "rouh-keepalive"

#: The MCP servers every agent on this machine gets, wherever it runs. One
#: file, committed at the top of this repository, read by this module and by
#: one/asuser.py, which are the two places that start an agent. Adding a server
#: for every run means editing that file and nothing else. See AGENTS.md,
#: "The MCP servers every run gets".
MACHINE_MCP_SERVERS = Path(__file__).resolve().parent.parent / "mcp-servers.json"


def _read_mcp_servers(path: Path) -> dict[str, Any]:
    """The ``mcpServers`` table in one of these files, or nothing at all.

    Never raises. A missing file is the ordinary case for a checkout with no
    .mcp.json of its own, and a machine still serving a deploy from before
    mcp-servers.json existed reads nothing here rather than failing to start a
    job.
    """
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        servers = data.get("mcpServers")
        return dict(servers) if isinstance(servers, dict) else {}
    except (OSError, ValueError, AttributeError, TypeError):
        return {}


def _machine_mcp_servers() -> dict[str, Any]:
    """This machine's own servers, from MACHINE_MCP_SERVERS, with ``{repo}`` filled in.

    ``{repo}`` is the folder that file is in: this deployment's own checkout,
    which no job can change. It is how a server that is a file of this
    repository - `rouh/worker_mcp.py` - is named, whatever checkout the job
    works in, or none. one/asuser.py fills it in the same way from its own copy.
    """
    here = str(MACHINE_MCP_SERVERS.parent)

    def fill(value: Any) -> Any:
        if isinstance(value, str):
            return value.replace("{repo}", here)
        if isinstance(value, list):
            return [fill(v) for v in value]
        if isinstance(value, dict):
            return {k: fill(v) for k, v in value.items()}
        return value

    return {name: fill(spec) for name, spec in _read_mcp_servers(MACHINE_MCP_SERVERS).items()}


def _claude_project_root(folder: Path) -> Path | None:
    """The folder Claude Code files ``folder``'s trust under, or None outside git.

    Claude Code keys its per-project config, which holds the answer to the
    trust dialog and the MCP servers approved with it, on the repository a
    folder belongs to rather than on the folder: the git root above it, and
    for a git worktree the repository the worktree was made from. So a
    crewmate's worktree at ``crew/worktrees/<id>`` is filed under the checkout
    it came from, ``/var/www/rouh/app`` on the server.

    This reads the worktree's ``.git`` file the way the binary does, and
    checks the same things it checks, so a folder it would not follow to a
    repository is answered with its own git root, as the binary answers it.
    Read out of Claude Code 2.1.274 on 24 September 2026.
    """
    root = None
    for here in (folder, *folder.parents):
        if (here / ".git").exists() or (here / ".git").is_symlink():
            root = here
            break
    if root is None or (root / ".git").is_symlink():
        return None
    try:
        line = (root / ".git").read_text(encoding="utf-8").strip()
    except OSError:
        # A directory: an ordinary checkout, filed under its own root.
        return root
    if not line.startswith("gitdir:"):
        return root
    try:
        gitdir = Path(os.path.normpath(root / line[len("gitdir:"):].strip()))
        common = Path(os.path.normpath(
            gitdir / (gitdir / "commondir").read_text(encoding="utf-8").strip()))
        back = Path(os.path.normpath(
            gitdir / (gitdir / "gitdir").read_text(encoding="utf-8").strip()))
    except OSError:
        return root
    if gitdir.parent != common / "worktrees":
        return root
    if os.path.realpath(back) != os.path.realpath(root / ".git"):
        return root
    return common.parent if common.name == ".git" else common


def _prepare_trust_document(config: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Prepare the in-memory projects and onboarding fields before settings are seeded."""
    projects = config.setdefault("projects", {})
    changed = False

    # The trust dialog is not the only blocking first-run prompt, and the
    # others are worse because they appear only on a machine where nobody
    # has ever run Claude Code interactively - which is exactly what a
    # server is. Two were found by watching a worker sit for ever:
    #
    #   "Choose the text style that looks best with your terminal"
    #   "Do you want to use this API key?"
    #
    # Neither prints an error. The window stays open, the job never
    # starts, and the only symptom is a task that is running and doing
    # nothing. Answer them in the config before launching anything.
    if not config.get("hasCompletedOnboarding"):
        config["hasCompletedOnboarding"] = True
        changed = True
    return projects, changed


def _update_trust_theme(config: dict[str, Any]) -> bool:
    """Set the in-memory theme after the dangerous-mode settings have been seeded."""
    changed = False
    if not config.get("theme"):
        config["theme"] = "dark"
        changed = True
    return changed


def _update_trust_access(config: dict[str, Any], projects: dict[str, Any],
                         paths: set[str], offered: Sequence[str], key: str,
                         uses_key: bool) -> bool:
    """Merge key approval and project trust into the in-memory document."""
    changed = False
    if key and uses_key:
        # Claude Code records the decision against the last 20 characters
        # of the key, never the whole thing.
        tail = key[-20:]
        responses = config.setdefault("customApiKeyResponses", {})
        approved = responses.setdefault("approved", [])
        responses.setdefault("rejected", [])
        if tail not in approved:
            approved.append(tail)
            changed = True
    for path in paths:
        entry = projects.get(path)
        base = entry if isinstance(entry, dict) else {}
        # A path already trusted used to be skipped outright here, and
        # that quietly cost every job its browser. The servers are
        # approved further down this loop, so a checkout that was
        # trusted before it had an .mcp.json - or before this seeded
        # one - never got them, and no later run could fix it because
        # the path stayed trusted. Measured on this server on 21
        # September 2026: of 251 project paths in one user's
        # ~/.claude.json, 22 had a server approved, and the rouh
        # user's 59 had none at all. So the entry is brought up to
        # date every time, and only written back if something changed.
        already = (base.get("hasTrustDialogAccepted") is True)
        projects[path] = {
            "allowedTools": [],
            "mcpContextUris": [],
            "mcpServers": {},
            "enabledMcpjsonServers": [],
            "disabledMcpjsonServers": [],
            "hasClaudeMdExternalIncludesApproved": False,
            "hasClaudeMdExternalIncludesWarningShown": False,
            **base,
            "hasTrustDialogAccepted": True,
        }
        if offered:
            # A server committed to the repository is the repository
            # asking for it, so it is allowed rather than refused, and
            # taken off any refused list a older seeding left behind.
            before = (sorted(base.get("enabledMcpjsonServers") or []),
                      sorted(base.get("disabledMcpjsonServers") or []))
            projects[path]["enabledMcpjsonServers"] = sorted(
                set(projects[path].get("enabledMcpjsonServers") or []) | set(offered)
            )
            projects[path]["disabledMcpjsonServers"] = sorted(
                set(projects[path].get("disabledMcpjsonServers") or []) - set(offered)
            )
            after = (projects[path]["enabledMcpjsonServers"],
                     projects[path]["disabledMcpjsonServers"])
            if before != after:
                already = False
        if not already:
            changed = True
    return changed


#: The machine's server whose one tool queues an email to the person
#: (`rouh/worker_mcp.py`), which is told here which job it belongs to.
OUTBOX_SERVER = "rouh"

#: What every worker is told about email, because it cannot send any and used
#: to spend its time finding that out (`rouh/outbox.py`). The one program tells
#: its runs the same thing (`one/agents.py`, MAIL_RULE).
MAIL_INSTRUCTION = (
    "You cannot send email: this server has no mail and you have no account to send "
    "from, so never try with a command or look for credentials. If you are asked to "
    "email or message the person, call the notify_owner tool with a subject and the "
    "text. It queues them for Rouh, which says who it goes to, asks the person, and "
    "sends it from their own account after you finish. Say in your last message that "
    "you queued it. Anything that needs the person's or Rouh's accounts - mail and its "
    "files (mail_find, mail_file), calendar, Drive and Docs, contacts, Slack, meetings, "
    "memory - you do with the rouh server's tools: Rouh runs them with its own logins, so "
    "never say a job cannot get it, and never look for a login. A call that sends, shares, "
    "pays or deletes comes back pending, as a decision for the person: carry on. For "
    "anything no tool gives, call request_from_rouh with what you need, why and what you do "
    "meanwhile, and carry on with the rest of the work rather than stopping.")

#: What every worker is told about its browser (`rouh/browser_handoff.py`): the
#: headless one it has is for work nobody watches, and a step that is the
#: person's is stopped at and handed to Rouh's live browser. The one program
#: tells its runs the same thing (`one/agents.py`, BROWSER_RULE).
BROWSER_INSTRUCTION = browser_handoff.WORKER_RULE[2:]

#: What every worker is told about a file it is handed: open it and look, and
#: if it will not open, ask rather than guess (`rouh/attachments.py`). The one
#: program tells its runs the same thing (`one/agents.py`, FILES_RULE).
FILES_INSTRUCTION = attachments.WORKER_RULE[2:]

# Passing the prompt as an argv element is the cleanest route (tmux hands argv to
# execvp untouched), but Linux caps a single argument at 128 KiB. Above this, the
# crewmate is pointed at the prompt file instead.
MAX_INLINE_PROMPT_BYTES = 32 * 1024

#: What every worker's window runs first, in front of the worker itself: it
#: waits until the window is kept and logged, and writes down how the worker
#: ended (`crew_launch.py`).
LAUNCHER = Path(__file__).resolve().with_name("crew_launch.py")

#: A job that dies this soon after it was started, having never begun work,
#: died at launch rather than while working.
LAUNCH_SECONDS = 60.0

#: The most of what a dead job printed that is kept as its reason.
SAID_MOST = 200


# --------------------------------------------------------------------------------------
# Status vocabulary
# --------------------------------------------------------------------------------------

#: Every status a crewmate can hold.
#:
#: ``starting``  the window exists and the prompt has been handed over
#: ``running``   Claude Code is working
#: ``waiting``   Claude Code raised a notification: it wants a human
#: ``done``      Claude Code finished a turn (the ``Stop`` hook fired); still alive
#: ``lost``      the tmux window is gone and we never saw it finish
#: ``killed``    we stopped it on purpose
#: ``failed``    it reported a failure
STATUSES = ("starting", "running", "waiting", "done", "lost", "killed", "failed")

#: Statuses reconciliation will not overwrite.
TERMINAL_STATUSES = frozenset({"done", "lost", "killed", "failed"})


# --------------------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------------------


class CrewError(RuntimeError):
    """Anything this module refuses to do, or cannot do."""


class UnknownCrewmate(CrewError):
    """No crewmate with that id is on record."""


class YoloRefused(CrewError):
    """A caller asked for yolo mode without saying ``allow_yolo=True``.

    Deliberately loud. ``yolo`` runs Claude Code with ``--dangerously-skip-permissions``,
    which means nothing at all stands between the model and the machine. Silently
    downgrading to a safer mode would be worse than refusing, because the caller would
    believe permissions were off when they were not.
    """


class TmuxError(CrewError):
    """A tmux command failed. Carries the command, exit code and stderr."""

    def __init__(self, argv: Sequence[str], returncode: int, stderr: str) -> None:
        self.argv = list(argv)
        self.returncode = returncode
        self.stderr = stderr.strip()
        super().__init__(
            f"tmux failed ({returncode}): {shlex.join(self.argv)}\n{self.stderr}"
        )


# --------------------------------------------------------------------------------------
# Modes
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ModeSpec:
    """One named way of running a crewmate.

    ``permission_mode``   value for ``claude --permission-mode``
    ``extra_flags``       further flags, each already split into argv elements
    ``deny``              ``permissions.deny`` rules written into the settings file
    ``instructions``      appended to the prompt so the model knows its own limits
    ``requires_opt_in``   the caller must pass ``allow_yolo=True``
    """

    name: str
    summary: str
    permission_mode: str | None
    extra_flags: tuple[str, ...] = ()
    deny: tuple[str, ...] = ()
    instructions: str = ""
    requires_opt_in: bool = False

    def claude_flags(self) -> list[str]:
        flags: list[str] = []
        if self.permission_mode:
            flags += ["--permission-mode", self.permission_mode]
        flags += list(self.extra_flags)
        return flags


_PUSH_DENY = (
    "Bash(git push:*)",
    "Bash(git push)",
    "Bash(git remote:*)",
)
_PR_DENY = (
    "Bash(gh:*)",
    "Bash(gh pr:*)",
    "Bash(glab:*)",
)
#: Pushing, for the one mode whose work goes to main. Since cards 488 and 489
#: `land.sh` is the only thing allowed to push there, and a rule the model is
#: merely told is a rule a model can talk itself round, so this is the rule it
#: cannot: the script's own push happens inside the script, which Claude Code
#: sees as one `Bash(./land.sh)` call. It is not on the other modes, because a
#: job whose work is a pull request somewhere else has a push to make.
_MAIN_PUSH_DENY = (
    "Bash(git push:*)",
    "Bash(git push)",
)
_MAIN_BRANCH_DENY = (
    "Bash(git checkout main:*)",
    "Bash(git checkout master:*)",
    "Bash(git switch main:*)",
    "Bash(git switch master:*)",
    "Bash(git push:* --force:*)",
    "Bash(git push:* -f:*)",
)

MODES: dict[str, ModeSpec] = {
    "safe": ModeSpec(
        name="safe",
        summary="Claude Code asks a human before every edit and every command.",
        # "manual" is the documented CLI spelling; inside Claude Code it resolves to
        # "default", described in-product as "ask before every edit".
        permission_mode="manual",
        deny=_PUSH_DENY + _PR_DENY,
        instructions=(
            "You are running with permission prompts on. Every edit and every command "
            "needs a person to approve it, and nobody may be watching. Prefer reading, "
            "searching and explaining over acting. If the job cannot be finished "
            "without approvals, do the reading, write down exactly what you would "
            "change, and stop."
        ),
    ),
    "local-only": ModeSpec(
        name="local-only",
        summary="May edit files in its own worktree. Never pushes, never opens a pull request.",
        permission_mode="acceptEdits",
        deny=_PUSH_DENY + _PR_DENY,
        instructions=(
            "You may create, edit and delete files inside this worktree, and you may "
            "commit. You must not push to any remote and you must not open a pull "
            "request. When you are finished, leave the work committed on this branch "
            "and say what you changed. Rouh lands it for you through `land.sh`, "
            "which is the only thing here allowed to push to main; if your work "
            "collides with something that landed while you worked, you will be sent "
            "both sides and asked to reconcile them yourself."
        ),
    ),
    "auto": ModeSpec(
        name="auto",
        summary=(
            "Runs unattended. Claude Code decides what is safe to do on its own, "
            "so it does not stop to ask. Still cannot push or open a pull request."
        ),
        permission_mode="auto",
        deny=_PUSH_DENY + _PR_DENY,
        instructions=(
            "Nobody is watching and nothing will stop to ask you. Work to the end of "
            "the task. You may read, write and run commands inside this workspace. "
            "You must not push to any remote and you must not open a pull request. "
            "If you hit something you genuinely cannot decide, stop and write down "
            "what the choice is and what you would need to make it."
        ),
    ),
    "self": ModeSpec(
        name="self",
        summary=(
            "Rouh working on its own repository. No prompts, and its work does "
            "reach main, because a change that cannot land is a change that "
            "cannot be deployed. It lands through land.sh, never by pushing."
        ),
        permission_mode="bypassPermissions",
        deny=_MAIN_PUSH_DENY,
        instructions=(
            "You are changing Rouh itself, the assistant that started you. Nobody "
            "is watching and nothing will stop to ask.\n"
            "\n"
            "Work in this order and do not skip a step:\n"
            "1. Read the code around what you are changing before changing it.\n"
            "2. Make the change.\n"
            "3. Prove it yourself. There are no committed tests in this repository "
            "and no suite to run: drive the running app in a real browser over "
            "Playwright MCP, and write and run whatever Python check the logic "
            "needs. AGENTS.md there says how.\n"
            "4. Leave what you wrote to prove it out of the commit. No test file "
            "goes back into this repository.\n"
            "5. Commit with a message that says what changed and why.\n"
            "6. End with `./land.sh`, which is the only thing allowed to push to "
            "main. Never `git push` yourself. It replays your work over whatever "
            "landed on main while you worked, one job at a time, pushes it, and "
            "then deploys it and waits for the machine to be serving the commit "
            "it pushed. Read its last line: landing includes deploying, and a "
            "change that is on main and not live is not done. "
            "If it says your work collides with something, it hands you both "
            "sides and what to do: read that, reconcile the intent rather than "
            "the text, prove it in the browser again, and run `./land.sh` "
            "again.\n"
            "\n"
            "Then stop and say what you changed, in plain language, in one or two "
            "sentences. Somebody will read that out loud.\n"
            "\n"
            "If you cannot get the change right, do not push. Say what is wrong and "
            "what you would need. A broken push takes the assistant down, and the "
            "assistant is how anyone would ask you to fix it."
        ),
    ),
    "direct-pr": ModeSpec(
        name="direct-pr",
        summary="May commit, push its own branch and open a pull request. Never touches the default branch.",
        permission_mode="acceptEdits",
        deny=_MAIN_BRANCH_DENY,
        instructions=(
            "You may edit files, commit, push this branch and open a pull request. "
            "You must not commit to, push to, or force-push the default branch "
            "(main or master), and you must not merge your own pull request. Work only "
            "on the branch this worktree is already on. Finish by opening a pull "
            "request and giving its URL."
        ),
    ),
    "yolo": ModeSpec(
        name="yolo",
        summary="All permission checks skipped. Refused unless the caller passes allow_yolo=True.",
        permission_mode=None,
        extra_flags=("--dangerously-skip-permissions",),
        deny=(),
        instructions=(
            "Permission checks are off. Nothing will stop you, so stop yourself: stay "
            "inside this worktree, do not touch anything outside it, and do not act on "
            "the default branch."
        ),
        requires_opt_in=True,
    ),
}


@dataclass(frozen=True)
class WorkerProfile:
    """Who a job runs as, and where, when that is not the manager's default.

    The default worker is the ``rouh`` user, in a worktree under the crew
    workspace, on Rouh's own API key. A job in the person's assistant
    workspace differs on every one of those: it runs as the
    ``assistant`` user, in that user's repository, on the person's Claude
    subscription. A profile names those differences once, and a spawn that asks
    for it by name gets all of them together.

    ``run_as`` / ``run_home``  the Linux user the job runs as, and its home
    ``worktrees_dir``         where the job's own checkout is made
    ``git_user``              run git as this user. The repository is theirs, so
                              git refuses root ("dubious ownership"), and a push
                              needs their key
    ``unset_env``             taken out of what the job can see. The API key has
                              to go: Claude Code prefers a key to the
                              subscription whenever both are present
    ``extra_flags``           appended to the claude command line
    ``base``                  what a new branch starts from, fetched first
    ``instructions``          appended to the job's brief
    ``given_repo`` / ``own_checkout``  a job given ``given_repo`` makes its
                              worktree from ``own_checkout``, ``git_user``'s own
                              checkout of the same repository. The person's
                              workspace Rouh serves is root's, and git run as
                              ``git_user`` refuses it ("dubious ownership") and
                              could not write a worktree into it if it did not
    """

    name: str
    run_as: str | None = None
    run_home: str | None = None
    worktrees_dir: Path | None = None
    git_user: str | None = None
    unset_env: tuple[str, ...] = ()
    extra_flags: tuple[str, ...] = ()
    base: str | None = None
    instructions: str = ""
    given_repo: str | None = None
    own_checkout: str | None = None


def _worktree_admin(workdir: Path) -> Path | None:
    """A worktree's own directory inside the repository it belongs to.

    `<repo>/.git/worktrees/<id>`, which is where git writes that worktree's
    HEAD, its index and the lock it takes to commit. It is named by the one
    line of the `.git` file in the worktree itself, so this follows what git
    wrote rather than guessing at a layout.
    """
    marker = Path(workdir) / ".git"
    try:
        said = marker.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not said.startswith("gitdir:"):
        return None
    where = Path(said.split(":", 1)[1].strip())
    return where if where.is_dir() else None


def _same_dir(a: str, b: str) -> bool:
    try:
        return Path(a).expanduser().resolve() == Path(b).expanduser().resolve()
    except OSError:
        return False


def _give_dir(path: Path, user: str) -> None:
    """Make ``path`` if it is missing and hand it to ``user``, when it is not theirs."""
    import pwd

    path.mkdir(parents=True, exist_ok=True)
    who = pwd.getpwnam(user)
    if path.stat().st_uid != who.pw_uid:
        os.chown(path, who.pw_uid, who.pw_gid)


def _running_as_root() -> bool:
    return hasattr(os, "geteuid") and os.geteuid() == 0


def _user_exists(name: str) -> bool:
    try:
        import pwd

        pwd.getpwnam(name)
        return True
    except (KeyError, ImportError):
        return False


def _cannot_run_as(user: str | None) -> str | None:
    """Why a worker cannot be started as this user, or None when it can.

    Asked before anything is made, because the launch itself cannot say it:
    `runuser` prints one line and exits, and the window goes with it. From
    22 September 2026, when the machine's `jarvis` user was renamed `rouh`,
    every worker was started as a user that no longer existed and died in the
    same second, with nothing written anywhere a person would look. Refusing
    here turns that into a sentence the person is told.
    """
    if not user:
        return None
    if not _user_exists(user):
        return (f"A worker cannot be started as the user {user!r}: there is no such user "
                "on this machine, so nothing was started. ROUH_CREW_USER names the user "
                "workers run as.")
    if not _running_as_root():
        return (f"A worker cannot be started as the user {user!r} from here: switching "
                "to another user needs root, and Rouh is not running as root, so nothing "
                "was started. Leave ROUH_CREW_USER blank to run workers as Rouh's own "
                "user.")
    return None


def _skips_permissions(spec: ModeSpec) -> bool:
    """True for a mode that runs with Claude Code's permission checks off."""
    return (spec.permission_mode == "bypassPermissions"
            or "--dangerously-skip-permissions" in spec.extra_flags)


def _flag_value(argv: Sequence[str], flag: str) -> str:
    """What a command line gives a flag, as "--flag value" or "--flag=value";
    the last one wins, as it does for Claude Code, and "" when it is not there."""
    found = ""
    for i, part in enumerate(argv):
        if part == flag and i + 1 < len(argv):
            found = argv[i + 1]
        elif part.startswith(flag + "="):
            found = part[len(flag) + 1:]
    return found


# --------------------------------------------------------------------------------------
# The record
# --------------------------------------------------------------------------------------


@dataclass
class Crewmate:
    """One delegated job. Mirrors a row of the ``crewmates`` table."""

    id: str
    title: str
    task: str
    mode: str
    status: str
    session: str
    window_name: str
    workdir: str
    repo: str | None = None
    branch: str | None = None
    is_worktree: bool = False
    window_id: str | None = None
    pane_id: str | None = None
    created_at: str = ""
    updated_at: str = ""
    started_at: str | None = None
    finished_at: str | None = None
    exit_code: int | None = None
    last_event: str | None = None
    #: Put out of the person's way in the lists, and brought back. Archiving
    #: stops the job too: see ``CrewManager.archive``. Its checkout is left
    #: alone either way.
    archived: bool = False
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def alive(self) -> bool:
        """True while the job has not ended, by its status alone.

        Not whether its process is running: a "done" job is not alive here and
        usually still sits at its prompt in its window (see ``archive``).
        """
        return self.status not in TERMINAL_STATUSES

    @property
    def workdir_path(self) -> Path:
        return Path(self.workdir)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    # The web layer reads a result as if it were a JSON object, so a crewmate answers
    # to both `mate.status` and `mate.get("status")`. Fields it does not have, such as
    # "detail", come back as the default rather than raising.
    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def __getitem__(self, key: str) -> Any:
        try:
            return getattr(self, key)
        except AttributeError:
            raise KeyError(key) from None

    def keys(self) -> Iterable[str]:
        return self.as_dict().keys()

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "Crewmate":
        """One crewmate from a ``crewmates`` row, as a mapping of its columns."""
        data = dict(row)
        data["is_worktree"] = bool(data["is_worktree"])
        data["archived"] = bool(data.get("archived"))
        data["meta"] = json.loads(data["meta"] or "{}")
        return cls(**data)


# --------------------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------------------


def _new_id() -> str:
    return uuid.uuid4().hex[:8]


_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def slugify(text: str, *, words: int = 4, max_len: int = 32) -> str:
    """Turn a task sentence into something safe for a branch and a tmux window name.

    Only lowercase letters, digits and single dashes survive, so the result can never
    carry a tmux target character (``:`` or ``.``) or a git refname character.
    """
    cleaned = _SLUG_STRIP.sub(" ", text.lower()).split()
    slug = "-".join(cleaned[:words])[:max_len].strip("-")
    return slug or "task"


def _expects(given: Any) -> set[str]:
    """The files a job declared, as plain relative paths inside its checkout."""
    if isinstance(given, str):
        given = given.replace(",", " ").split()
    if not given:
        return set()
    out = set()
    for item in given:
        path = str(item or "").strip().strip("/")
        if path and ".." not in path.split("/"):
            out.add(path)
    return set(sorted(out)[:40])


def _tail(text: str, lines: int) -> str:
    parts = text.rstrip("\n").split("\n")
    return "\n".join(parts[-lines:]) if lines > 0 else ""


async def _run(
    argv: Sequence[str],
    *,
    cwd: str | os.PathLike[str] | None = None,
    stdin_data: bytes | None = None,
    timeout: float = 30.0,
) -> tuple[int, str, str]:
    """Run a command as an argument list. Never a shell, never an interpolated string.

    Output is captured to temporary files rather than pipes, and that is not a
    style choice.

    `tmux new-session` starts a long-lived server process that inherits whatever
    file descriptors it was handed. Given a pipe, the server holds the write end
    open for as long as it lives, which is for ever. Reading that pipe until
    end-of-file therefore never returns, so the command appears to hang even
    though the session was created within milliseconds. Measured inside the
    running app: 0.01s to run `tmux -V`, 12s and a timeout to run
    `tmux new-session`, and 0.02s for the identical call writing to a file.

    It only shows up in a long-lived process, which is why it survived every
    test from a shell and only appeared once the assistant tried to start a job.
    A file needs no end-of-file, so waiting on the process alone is enough.
    """
    with tempfile.TemporaryFile() as out_fh, tempfile.TemporaryFile() as err_fh:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=str(cwd) if cwd is not None else None,
            stdin=asyncio.subprocess.PIPE if stdin_data is not None else asyncio.subprocess.DEVNULL,
            stdout=out_fh,
            stderr=err_fh,
        )
        try:
            if stdin_data is not None and proc.stdin is not None:
                proc.stdin.write(stdin_data)
                with contextlib.suppress(Exception):
                    await proc.stdin.drain()
                proc.stdin.close()
            await asyncio.wait_for(proc.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            await proc.wait()
            raise CrewError(f"timed out after {timeout}s: {shlex.join(list(argv))}") from None
        out_fh.seek(0)
        err_fh.seek(0)
        return (
            proc.returncode or 0,
            out_fh.read().decode("utf-8", "replace"),
            err_fh.read().decode("utf-8", "replace"),
        )


# --------------------------------------------------------------------------------------
# tmux
# --------------------------------------------------------------------------------------



def _last_prompt_line(screen: str) -> str:
    """The text sitting on the input line, if there is one.

    Claude Code draws it after a caret. Anything else on screen is output and
    changes on its own, which would make a comparison meaningless.
    """
    for line in reversed((screen or "").splitlines()):
        stripped = line.strip()
        for caret in ("\u276f", ">"):
            if stripped.startswith(caret):
                return stripped[len(caret):].strip()
    return ""


class Tmux:
    """A thin async wrapper around the tmux command line.

    ``socket`` maps to ``tmux -L``. Leaving it unset uses the default server, which is
    what a human wants: they can just ``tmux attach -t rouh``. Tests set it so a
    broken test can never reach a real session.
    """

    def __init__(self, socket: str | None = None, binary: str = "tmux") -> None:
        self.socket = socket
        self.binary = binary

    def argv(self, *args: str) -> list[str]:
        base = [self.binary]
        if self.socket:
            base += ["-L", self.socket]
        return base + list(args)

    async def run(self, *args: str, check: bool = True, timeout: float = 15.0,
                  stdin_data: bytes | None = None) -> tuple[int, str, str]:
        argv = self.argv(*args)
        rc, out, err = await _run(argv, stdin_data=stdin_data, timeout=timeout)
        if check and rc != 0:
            raise TmuxError(argv, rc, err)
        return rc, out, err

    async def available(self) -> bool:
        try:
            rc, _, _ = await self.run("-V", check=False, timeout=10.0)
        except (FileNotFoundError, CrewError):
            return False
        return rc == 0

    async def has_session(self, session: str) -> bool:
        rc, _, _ = await self.run("has-session", "-t", f"={session}", check=False)
        return rc == 0

    async def list_windows(self, session: str | None = None) -> list[dict[str, Any]]:
        """Raw tmux truth. One dict per window, across every session unless narrowed."""
        fmt = "#{session_name}\t#{window_id}\t#{window_index}\t#{window_name}\t#{pane_id}\t#{pane_dead}\t#{pane_dead_status}\t#{pane_pid}\t#{pane_current_path}"
        args = ["list-windows", "-F", fmt]
        if session is None:
            args.append("-a")
        else:
            args += ["-t", f"={session}"]
        rc, out, err = await self.run(*args, check=False)
        if rc != 0:
            # No server running at all, or the session is gone. Both mean "no windows".
            lowered = err.lower()
            if "no server running" in lowered or "can't find session" in lowered or "no such file" in lowered:
                return []
            raise TmuxError(self.argv(*args), rc, err)
        windows: list[dict[str, Any]] = []
        for line in out.splitlines():
            if not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) < 9:
                parts += [""] * (9 - len(parts))
            dead_status = parts[6].strip()
            windows.append(
                {
                    "session": parts[0],
                    "window_id": parts[1],
                    "window_index": parts[2],
                    "window_name": parts[3],
                    "pane_id": parts[4],
                    "dead": parts[5] == "1",
                    "exit_code": int(dead_status) if dead_status.lstrip("-").isdigit() else None,
                    "pane_pid": parts[7],
                    "path": parts[8],
                }
            )
        return windows

    async def new_session(self, session: str, *, cwd: str, window_name: str,
                          command: Sequence[str]) -> None:
        await self.run(
            "new-session", "-d", "-s", session, "-n", window_name, "-c", cwd, *command
        )

    async def new_window(self, session: str, *, name: str, cwd: str,
                         command: Sequence[str]) -> tuple[str, str]:
        _, out, _ = await self.run(
            "new-window", "-d", "-t", f"={session}:", "-n", name, "-c", cwd,
            "-P", "-F", "#{window_id}\t#{pane_id}", *command,
        )
        window_id, _, pane_id = out.strip().partition("\t")
        return window_id, pane_id

    async def set_window_option(self, target: str, option: str, value: str) -> bool:
        rc, _, _ = await self.run("set-option", "-w", "-t", target, option, value, check=False)
        return rc == 0

    async def capture(self, target: str, lines: int) -> str:
        rc, out, err = await self.run(
            "capture-pane", "-p", "-J", "-t", target, "-S", f"-{max(lines, 1)}", check=False
        )
        if rc != 0:
            raise TmuxError(self.argv("capture-pane", "-t", target), rc, err)
        return out

    async def paste(self, target: str, text: str, *, buffer_name: str) -> None:
        """Deliver text as a bracketed paste, so newlines do not submit early."""
        await self.run("load-buffer", "-b", buffer_name, "-", stdin_data=text.encode("utf-8"))
        await self.run("paste-buffer", "-p", "-d", "-b", buffer_name, "-t", target)

    # Enter, twice over, because which one works depends on a mode the program
    # on the other end chose and nothing announces it.
    #
    # Claude Code turns on the kitty keyboard protocol. In it Enter arrives as
    # ESC [ 13 u, and the plain carriage return that `send-keys Enter` produces
    # is ignored outright. The effect was silent and total: every message Rouh
    # sent a worker was typed into its prompt and left sitting there. "deploy
    # it" sat unsent for four hours, which is what made self-updating look
    # impossible.
    #
    # The plain one is tried FIRST and the escape sequence only if the line did
    # not clear. That order matters: a program not using the protocol treats
    # ESC [ 13 u as five characters and types them into the command, so leading
    # with it would corrupt whatever was about to run.
    KITTY_ENTER = ("1b", "5b", "31", "33", "75")   # ESC [ 1 3 u

    async def send_enter(self, target: str) -> bool:
        """Submit whatever is on the prompt. True if the line actually cleared."""
        pending = _last_prompt_line(await self.capture(target, 40))
        if not pending:
            await self.run("send-keys", "-t", target, "Enter", check=False)
            return True

        async def cleared() -> bool:
            await asyncio.sleep(0.5)
            now = _last_prompt_line(await self.capture(target, 40))
            # Gone, or at least no longer holding what we were waiting to send.
            return not now or now != pending

        await self.run("send-keys", "-t", target, "Enter", check=False)
        if await cleared():
            return True

        await self.run("send-keys", "-t", target, "-H", *self.KITTY_ENTER, check=False)
        return await cleared()

    async def kill_window(self, target: str) -> bool:
        rc, _, _ = await self.run("kill-window", "-t", target, check=False)
        return rc == 0


# --------------------------------------------------------------------------------------
# The manager
# --------------------------------------------------------------------------------------

# The three tables are `rouh.models.Crewmate`, `CrewEvent` and `CrewTreeEvent`
# (`rouh/models/rest.py`). `crew_tree_events` is every telemetry hook, raw,
# exactly as Claude Code sent it: the source of truth, with the work tree
# derived from it on every read and never accumulated in memory. That is what
# makes a close that never arrived a bug someone can fix and replay, rather than
# a structure on screen that nothing will ever correct. Its `at` is unix
# seconds as a float because tool calls last milliseconds and the crewmates
# table's ISO strings only go to the second.


# --------------------------------------------------------------------------------------
# Reading a worker's screen
#
# A crewmate that stops and asks a question is the normal case, not an error. Claude
# Code draws the question as a numbered list and then waits for ever. Nothing upstream
# could see that: the status said "waiting" and the reason lived only in a terminal
# nobody was looking at. These read it back out.
# --------------------------------------------------------------------------------------

# " 1. Yes", "❯ 2. Yes, allow reading from ...", "  3. No"
_OPTION = re.compile(r"^\s*[>❯]?\s*(\d{1,2})[.)]\s+(.{1,120}?)\s*$")
_ASKING = re.compile(
    r"(do you want to|would you like to|allow this|may i |shall i |"
    r"press enter to continue|\(y/n\)|continue\?|proceed\?)",
    re.I,
)
# Lines that prove a prompt is on screen but are not the question itself.
_NAVIGATION = re.compile(
    r"(esc to cancel|tab to amend|press enter|enter to confirm|to confirm|"
    r"use arrow|↑|↓|shift\+tab)", re.I
)
# The cursor Claude Code draws beside the option it has selected. Its presence on
# a numbered line is the single most reliable sign that something is waiting for
# a keypress, whatever the wording above it happens to be.
_CURSOR = re.compile(r"^\s*[>❯]\s*\d{1,2}[.)]\s")


_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07|\r")


def _strip_ansi(text: str) -> str:
    """A piped pane is full of cursor moves and colour codes. Nobody reads those."""
    return _ANSI.sub("", text or "")


# Claude Code's own furniture at the foot of its screen, which is how a finished
# job's screen ends: the mode line under the input box ("\u23f5\u23f5 auto mode on
# (shift+tab to cycle) \u00b7 install gh for PR status \u00b7 \u2190 for agents"), the
# rules above and below the input, the input itself, often holding a suggested
# next prompt ("\u276f show me the 10 largest entries with sizes"), the "\u273b
# Cooked for 21s \u00b7 done 2:07 PM" summary, and its own notices ("\u2718
# Auto-update failed ... Run claude doctor", "new task? /clear to save 305.6k
# tokens"). None of it says what the job did, and the mode line was shown under
# every finished job's title as though it did.
_CHROME = re.compile(
    r"shift\+tab to cycle|esc to interrupt|for shortcuts|\u2190 for agents|"
    r"bypass permissions on|auto mode on|accept edits on|plan mode on|"
    r"install gh for pr status|/clear to save|claude doctor|auto-update failed",
    re.I,
)
# "\u273b Cooked for 21s \u00b7 done 2:07 PM", "\u25cf Worked for 9m 53s", "\u2733 Baked for 7s".
_DONE_FOR = re.compile(
    r"^[\u273b\u2733\u2736\u2722\u273d\u273a\u2734\u25cf*\u00b7]\s+\w+ for \d+(?:\.\d+)?[smh]\b"
)
# A rule or box edge, the input prompt, and the mode line's arrows.
_FURNITURE = "\u2500\u2501\u2550\u256d\u256e\u2570\u256f\u2502\u2503\u250c\u2510\u2514\u2518\u23f5\u276f"


def _is_chrome(line: str) -> bool:
    """True for a line Claude Code draws around its prompt, not one the job wrote."""
    s = (line or "").strip()
    if not s:
        return True
    if s[0] in _FURNITURE:
        return True
    return bool(_DONE_FOR.match(s) or _CHROME.search(s))


def closing_line(text: str, limit: int = 160) -> str:
    """A job's closing message as one short line: what goes under its title.

    The message a job ends with says what it did, in its own words. The PAGE line
    an assistant job puts first is a path, not a description, so it is left out.
    """
    kept = [ln.strip() for ln in (text or "").splitlines()]
    kept = [ln for ln in kept if ln and not ln.upper().startswith("PAGE:")]
    one = re.sub(r"\s+", " ", " ".join(kept)).replace("**", "").replace("`", "").strip()
    if len(one) > limit:
        one = one[: limit - 3].rsplit(" ", 1)[0] + "..."
    return one


#: A line that says what went wrong, rather than one that happens to be last.
_REASON = re.compile(
    r"(error|not found|no such|does not exist|denied|refus|cannot|can't|could not|"
    r"failed|invalid|unknown option|not allowed|may not|killed|panic|exception)",
    re.IGNORECASE)


#: A cursor sent to another row, which to somebody reading the log afterwards
#: is a new line.
_ROW_MOVE = re.compile(r"\x1b\[[0-9;]*[HfBEd]")
#: Every other escape a terminal program writes: the rest of CSI, including
#: the private ones Claude Code uses for its keyboard (`ESC [>5u`), OSC, the
#: character sets, and the two-character ones such as saving the cursor
#: (`ESC 7`). `_ANSI` is the short list the screen readers here need; a raw
#: log needs all of them.
_ESCAPE = re.compile(
    r"\x1b\[[0-9;?<>=!]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"
    r"|\x1b[()*+][0-9A-Za-z]|\x1b[0-9=>A-Z\\^_`a-z]|[\x00-\x08\x0b-\x1f\x7f]")


def _terminal_lines(raw: str) -> list[str]:
    """A piped terminal, as the lines a person would have read on it."""
    text = _ROW_MOVE.sub("\n", raw.replace("\r\n", "\n").replace("\r", "\n"))
    return [re.sub(r"[ \t]+", " ", ln).strip() for ln in _ESCAPE.sub("", text).split("\n")]


def _without_tmux(screen: str) -> list[str]:
    """A captured window as lines, without the one tmux adds under a window
    kept after its program exited - "Pane is dead (status 1, ...)" - which the
    job never said."""
    return [ln.rstrip() for ln in _strip_ansi(screen or "").splitlines()
            if not ln.startswith("Pane is dead")]


def _read_end(path: Path, most: int = 16384) -> str:
    """The last `most` bytes of a file, as text. Raises OSError when it is not there."""
    with open(path, "rb") as fh:
        fh.seek(0, os.SEEK_END)
        size = fh.tell()
        fh.seek(max(0, size - most))
        return fh.read().decode("utf-8", errors="replace")


def last_words(text: str) -> str:
    """What a dead job last printed that reads as a reason, as one short line.

    The last line that sounds like an error wins over the last line of all,
    because a program that fails usually says why and then something after
    it: a usage hint, a stack frame, a blank prompt. Claude Code's own
    furniture is never a reason (`_is_chrome`). Empty when there is nothing.
    """
    lines = [ln for ln in _terminal_lines(text or "") if ln and not _is_chrome(ln)]
    if not lines:
        return ""
    reasons = [ln for ln in lines if _REASON.search(ln)]
    said = (reasons or lines)[-1]
    if len(said) > SAID_MOST:
        said = said[: SAID_MOST - 3].rstrip() + "..."
    return said


def read_screen(text: str) -> dict:
    """Turn a captured pane into something a caller can act on.

    Returns the last lines, whether it looks like a question is on screen, the
    numbered choices if there are any, and the question itself.
    """
    lines = [ln.rstrip() for ln in (text or "").splitlines()]
    visible = [ln for ln in lines if ln.strip()]
    tail = visible[-40:]

    options: list[dict] = []
    for ln in tail:
        m = _OPTION.match(ln)
        if m:
            label = m.group(2).strip()
            # A diff or a file listing also starts with a number. A real choice
            # has words in it and is not mostly punctuation.
            # A diff line or a file listing also starts with a number. A real
            # choice reads as words. "No" is two letters, so the floor is two.
            if sum(c.isalpha() for c in label) >= 2 and not label.startswith("|"):
                options.append({"number": m.group(1), "label": label})

    near = tail[-25:]
    selected = any(_CURSOR.match(ln) for ln in near)
    asking = bool(options) and (
        selected
        or any(_ASKING.search(ln) for ln in near)
        or any(_NAVIGATION.search(ln) for ln in near)
    )
    if not asking:
        # Some prompts carry no numbered list, e.g. a bare "continue?".
        asking = any(_ASKING.search(ln) for ln in tail[-8:])

    question = ""
    if asking:
        # The question, not the keyboard hint underneath it. Prefer a real
        # question mark; fall back to the last line that reads like an ask.
        for ln in reversed(near):
            if _NAVIGATION.search(ln) or _OPTION.match(ln):
                continue
            if ln.strip().endswith("?"):
                question = ln.strip()
                break
        if not question:
            for ln in reversed(near):
                if _ASKING.search(ln) and not _OPTION.match(ln) and not _NAVIGATION.search(ln):
                    question = ln.strip()
                    break
        if not question and options:
            # No question mark anywhere. The prompt is whatever was said last
            # before the list of choices started.
            first_option = None
            for idx, ln in enumerate(near):
                if _OPTION.match(ln):
                    first_option = idx
                    break
            if first_option:
                for ln in reversed(near[:first_option]):
                    if ln.strip() and not _NAVIGATION.search(ln):
                        question = ln.strip()
                        break
        if not question and options:
            question = "A choice is on screen and nobody has answered it."

    return {
        "asking": asking,
        "question": question,
        "options": options[:8],
        "tail": "\n".join(tail),
        # The last thing the job wrote, not Claude Code's furniture below it.
        "last_line": next((ln.strip() for ln in reversed(tail) if not _is_chrome(ln)), ""),
    }


class CrewManager:
    """Spawn Claude Code crewmates in tmux, and know what became of them.

    Every public method is a coroutine, because the caller is FastAPI. Subprocess work
    (tmux, git, claude) runs through ``asyncio.create_subprocess_exec`` and never
    blocks the event loop. Database work is done inline under a lock: the rows are
    tiny, the database is on this machine, and the writes take a fraction of a
    millisecond.

    Nothing here polls a terminal. Claude Code POSTs to ``callback_url`` when it stops
    or wants a human, and the web layer passes that straight to :meth:`handle_event`.
    :meth:`start_reconciler` adds a slow sweep as a backstop, for the cases a callback
    cannot cover: the process was killed, the machine rebooted, tmux was restarted.
    """

    def __init__(
        self,
        *,
        workspace: str | os.PathLike[str] | None = None,
        db_path: str | os.PathLike[str] | None = None,
        session: str = DEFAULT_SESSION,
        socket: str | None = None,
        callback_url: str | None = None,
        launcher: Sequence[str] | Callable[..., Sequence[str]] | None = None,
        hook_transport: str = "http",
        hook_timeout: int = 10,
        allow_yolo: bool = False,
        default_env: Mapping[str, str] | None = None,
        effort: str | None = None,
        defaults: Callable[[], Any] | None = None,
        instructions: Callable[[str, str], str] | None = None,
        run_as: str | None = None,
        run_home: str | None = None,
        seed_trust: bool = True,
        claude_config_path: str | os.PathLike[str] | None = None,
        tmux_binary: str = "tmux",
        git_binary: str = "git",
        land_dir: str | None = None,
        land_script: str | None = None,
        configure_logging: bool = True,
    ) -> None:
        if hook_transport not in ("http", "command"):
            raise ValueError("hook_transport must be 'http' or 'command'")

        self.workspace = Path(workspace).expanduser() if workspace else DEFAULT_WORKSPACE
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.worktrees_dir = self.workspace / "worktrees"
        self.scratch_dir = self.workspace / "scratch"
        self.worktrees_dir.mkdir(exist_ok=True)
        self.scratch_dir.mkdir(exist_ok=True)
        #: One directory per crewmate, holding the tmux server that crewmate
        #: starts if it ever runs tmux itself. See `worker_tmux_dir`.
        self.tmux_dirs = self.workspace / "tmux"
        self.tmux_dirs.mkdir(exist_ok=True)

        self.session = session
        self.callback_url = (
            callback_url
            or os.environ.get("ROUH_CREW_CALLBACK")
            or DEFAULT_CALLBACK_URL
        )
        self.hook_transport = hook_transport
        self.hook_timeout = hook_timeout
        # A deployment-wide standing permission for yolo mode, so the whole process can
        # be opted in once instead of every call saying so. A single spawn can still opt
        # in on its own with allow_yolo=True. Either one is enough; neither is a veto.
        self.allow_yolo = allow_yolo
        self.default_env = dict(default_env or {})
        #: How hard every crewmate thinks, passed as `claude --effort`, when
        #: nothing hands the manager `defaults`. Blank leaves the flag off and
        #: Claude Code picks, which is what happened before 19 September 2026.
        self.effort = (effort or "").strip() or None
        #: Which model a crewmate is and how hard it thinks, asked for at every
        #: start: the organisation's default pair, something with `model` and
        #: `effort` (`rouh/modeldefaults.py`). None names no model and thinks
        #: at `effort`.
        self.defaults = defaults
        #: The agent instructions a worker starts with, asked for at every start
        #: with the job's id and the task in play (`rouh/agent_instructions.py`).
        #: None gives none, which is what every worker had before 15 October 2026.
        self.instructions = instructions
        self.run_as = (run_as or "").strip() or None
        self.run_home = (run_home or "").strip() or None
        self._flags_cache: set[str] | None = None
        self.seed_trust = seed_trust
        #: Whether the caller named the config file, rather than it being the
        #: worker user's own, in `run_home`.
        self._claude_config_given = bool(claude_config_path)
        self.claude_config_path = (
            Path(claude_config_path).expanduser()
            if claude_config_path
            # Trust and the answered first-run questions have to be written
            # where the process that reads them will look, which is the worker
            # user's home, not this one's.
            else (Path(self.run_home) / ".claude.json") if self.run_home
            else Path("~/.claude.json").expanduser()
        )
        self.git_binary = git_binary
        #: Where ``land.sh`` keeps its lock and its conflict records, and which
        #: copy of the script to run. Both blank on a real server, where the
        #: defaults are right: the directory two users share and the copy beside
        #: this package. A test points them somewhere of its own.
        self.land_dir = (land_dir or "").strip()
        self.land_script = (land_script or "").strip()
        self.tmux = Tmux(socket=socket, binary=tmux_binary)
        self._launcher = launcher or ("claude",)

        if configure_logging:
            _ensure_stdout_logging()

        # The rows are Django's, in whichever database it is pointed at, and
        # the schema is its migrations'. `db_path` named a SQLite file until
        # 23 September 2026; it is still accepted, so a caller written before
        # then needs no change, and it is not used.
        del db_path
        self._db_lock = threading.Lock()

        self._reconciler: asyncio.Task[None] | None = None
        self._listeners: list[Callable[[Crewmate, str, Mapping[str, Any]], Any]] = []
        #: Called with no arguments whenever something the work tree is built
        #: from changes: a crewmate row written, or a telemetry hook stored.
        self._tree_listeners: list[Callable[[], Any]] = []
        self._tree_pruned_at = 0.0
        self.profiles: dict[str, WorkerProfile] = {}
        #: What each new worktree was made from, kept from the moment it is made
        #: until the row is written. ``land.sh`` needs it to tell a job that
        #: committed nothing from a job whose commits are already on main, and
        #: those two used to be reported as the same thing.
        self._base_shas: dict[str, str] = {}
        #: Per worker, the agent that made each `Agent` tool call not yet
        #: claimed by a sub-agent announcing itself, oldest first. Blank means
        #: the worker itself made it. See `_register_subagent`.
        self._pending_agents: dict[str, list[str]] = {}

        LOG.info(
            "crew manager ready: workspace=%s session=%s callback=%s transport=%s",
            self.workspace, self.session, self.callback_url, self.hook_transport,
        )

    # -- lifecycle ---------------------------------------------------------------

    async def start(self, interval: float = 30.0) -> list["Crewmate"]:
        """Come up: reconcile once against tmux, then run the backstop sweep.

        Call this from the web layer's startup. The first reconcile is what makes a
        restart safe: crewmates recorded as running whose windows died while this
        process was down are marked lost immediately, rather than at the first sweep.
        """
        corrected = await self.reconcile()
        if corrected:
            LOG.info("startup found %d crewmate(s) that had died while we were away",
                     len(corrected))
        # A box handed to a job that ended while Rouh was away is still in its folder.
        for mate in self._select_all():
            if not mate.alive and (mate.meta or {}).get("boxes"):
                await asyncio.to_thread(self._shred_boxes, mate)
        await self.start_reconciler(interval)
        return corrected

    async def stop(self) -> None:
        """Shut down cleanly. The crewmates keep running in tmux; only we go away."""
        await self.aclose()

    async def start_reconciler(self, interval: float = 30.0) -> None:
        """Start the backstop sweep. Not the primary mechanism, just the safety net."""
        if self._reconciler and not self._reconciler.done():
            return
        self._reconciler = asyncio.create_task(self._reconcile_loop(interval))
        LOG.info("reconciliation sweep every %.0fs", interval)

    async def aclose(self) -> None:
        if self._reconciler:
            self._reconciler.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reconciler
            self._reconciler = None
        # Nothing to close: the database connection is Django's, one per
        # thread, and outlives any one crew manager.

    async def _reconcile_loop(self, interval: float) -> None:
        while True:
            try:
                await asyncio.sleep(interval)
                changed = await self.reconcile()
                if changed:
                    LOG.info("sweep corrected %d crewmate(s)", len(changed))
            except asyncio.CancelledError:
                raise
            except Exception:  # pragma: no cover - a sweep must never kill the app
                LOG.exception("reconciliation sweep failed; continuing")

    def on_change(self, callback: Callable[[Crewmate, str, Mapping[str, Any]], Any]) -> None:
        """Register something to call when a crewmate changes status.

        The voice layer uses this to say "that landed" without asking. Called as
        ``callback(crewmate, kind, payload)``; a coroutine is scheduled, a plain
        function is called inline. Failures are logged, never raised.
        """
        self._listeners.append(callback)

    def on_tree_change(self, callback: Callable[[], Any]) -> None:
        """Register something to call, with no arguments, when the work tree changes.

        Every write the tree is built from calls it: a crewmate created, its status
        or anything else about it updated, a telemetry hook stored. The web layer
        uses it to push the tree to the page at once, so a job started, stopped,
        finished or found dead shows on the orb in the time it takes to send a
        message. Called inline, so it must be cheap; failures are logged, never
        raised.
        """
        self._tree_listeners.append(callback)

    def _tree_changed(self) -> None:
        for listener in list(self._tree_listeners):
            try:
                listener()
            except Exception:  # pragma: no cover - a listener must not break a write
                LOG.exception("work tree listener failed")

    # -- spawning ----------------------------------------------------------------

    def add_profile(self, profile: WorkerProfile) -> None:
        """Make a named profile available to ``spawn(profile=...)``."""
        self.profiles[profile.name] = profile
        if profile.worktrees_dir is not None:
            Path(profile.worktrees_dir).mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _home_of(user: str) -> str:
        try:
            import pwd

            return pwd.getpwnam(user).pw_dir
        except Exception:
            return f"/home/{user}"

    def _git_argv(self, user: str | None, *args: str) -> list[str]:
        """git, run as ``user`` when this process is root and a user is named.

        HOME is stated because runuser keeps root's, and git reads its identity
        and settings from $HOME. ssh finds the user's own key without it, since
        it looks the home up itself; git does not.
        """
        argv = [self.git_binary, *args]
        if user and _running_as_root():
            argv = ["runuser", "-u", user, "--", "env", f"HOME={self._home_of(user)}", *argv]
        return argv

    async def spawn(
        self,
        task: str,
        repo: str | None = None,
        mode: str = "safe",
        title: str | None = None,
        *,
        allow_yolo: bool = False,
        base: str = "HEAD",
        env: Mapping[str, str] | None = None,
        profile: str | None = None,
        expects: Sequence[str] | None = None,
        in_play: str | None = None,
        secrets: Sequence[Mapping[str, Any]] | None = None,
    ) -> Crewmate:
        """Hand a job to a new Claude Code crewmate and return immediately.

        ``repo``  a git repository to work in. A fresh worktree on a fresh branch is
                  created for it, and when none can be, nothing is started and
                  ``CrewError`` says why. Only a job given no repo (None) gets a
                  scratch directory under the workspace.
        ``mode``  one of ``safe``, ``local-only``, ``direct-pr``, ``yolo``.
        ``base``  what the new branch starts from. Defaults to the repo's current HEAD.
        ``expects``  the files this job says it will touch. Kept on the row, and
                  compared against the jobs already running: see
                  :meth:`already_working_on`. It is never a refusal here, because
                  the crew has no queue to put a job in, but it is on the row and
                  in the log, so a collision has a name before it happens.
        ``in_play``  the task this job is for, when it is one task's work: its own
                  record is put after the agent instructions it starts with.
        ``secrets``  the boxes the person handed this job, ``{"number", "content"}``
                  each (`rouh/boxes.py`): written to ``.secrets/box-<n>`` in its
                  folder before it starts, and shredded when it ends (`_shred_boxes`).
        """
        if not task or not task.strip():
            raise ValueError("task must not be empty")

        prof: WorkerProfile | None = None
        if profile:
            prof = self.profiles.get(profile)
            if prof is None:
                raise ValueError(
                    f"unknown worker profile {profile!r}; known: "
                    f"{', '.join(self.profiles) or 'none'}"
                )

        spec = MODES.get(mode)
        if spec is None:
            raise ValueError(f"unknown mode {mode!r}; expected one of {', '.join(MODES)}")
        if spec.requires_opt_in and not (allow_yolo or self.allow_yolo):
            raise YoloRefused(
                "Refusing to spawn in yolo mode. yolo runs Claude Code with "
                "--dangerously-skip-permissions, so nothing stands between the model and "
                "this machine. Pass allow_yolo=True to say you meant it, or set "
                "allow_yolo=True on the manager to opt the whole process in. Nothing was "
                "spawned and no worktree was created."
            )

        if not await self.tmux.available():
            raise CrewError(
                f"tmux is not usable (tried {self.tmux.binary!r}). A crewmate needs a "
                "tmux window to live in."
            )
        if (problem := _cannot_run_as((prof.run_as if prof else None) or self.run_as)):
            raise CrewError(problem)

        # The cheap prevention on card 488: a job says up front what it expects
        # to touch, and a job whose files are already being worked on is worth
        # knowing about before it starts rather than when its work will not go
        # onto main. The one program queues such a run; the crew has no queue,
        # so here it is said in the log and kept on the row.
        if (clash := self.already_working_on(expects)):
            LOG.warning("a new job expects to touch %s, which %s is already working on",
                        ", ".join(sorted(clash[1])[:3]), clash[0])

        crew_id = _new_id()
        slug = slugify(task)
        title = (title or task.strip().splitlines()[0])[:120]
        window_name = f"jv-{crew_id}-{slug}"[:60]

        workdir, repo_root, branch, is_worktree = await self._prepare_workdir(
            crew_id, repo, slug, base, prof
        )

        if secrets:
            from . import boxes

            boxes.write_folder(str(workdir), list(secrets))
        prompt = self._compose_prompt(task=task, spec=spec, crew_id=crew_id,
                                      workdir=workdir, branch=branch, repo=repo_root,
                                      prof=prof)
        prompt_path = self._write_prompt(workdir, prompt)
        self._write_settings(workdir, crew_id, spec)
        if self.seed_trust:
            self._seed_workspace_trust(workdir, prof, bypass=_skips_permissions(spec))

        now = clock.utc_iso(timespec="seconds")
        mate = Crewmate(
            id=crew_id,
            title=title,
            task=task,
            mode=spec.name,
            status="starting",
            session=self.session,
            window_name=window_name,
            workdir=str(workdir),
            repo=str(repo_root) if repo_root else None,
            branch=branch,
            is_worktree=is_worktree,
            created_at=now,
            updated_at=now,
            started_at=now,
            meta={
                "prompt_path": str(prompt_path),
                "slug": slug,
                **({"expects": list(declared)} if (declared := _expects(expects)) else {}),
                **({"in_play": str(in_play)} if in_play else {}),
                **({"boxes": sorted(int(b["number"]) for b in secrets)} if secrets else {}),
                **({"base_sha": base_sha} if (base_sha := self._base_shas.pop(crew_id, "")) else {}),
                **({"profile": prof.name, "git_user": prof.git_user, "run_as": prof.run_as}
                   if prof else {}),
            },
        )

        self._hand_over(workdir, prof.run_as if prof else None)
        # And the worktree's own administrative directory, which is not inside
        # it: it is `<repo>/.git/worktrees/<id>`, and `git worktree add` leaves
        # it owned by whoever ran the command, which is root whenever the
        # profile names no git user. A worker that cannot write there cannot
        # commit - "Unable to create ... index.lock: Permission denied" - and
        # so ends with everything it did still in its checkout, which is the
        # one failure this whole repository's rules exist to stop. Found on
        # 24 September 2026 by job be7dec58, at the moment it tried to commit.
        if is_worktree:
            admin = _worktree_admin(workdir)
            if admin is not None:
                self._hand_over(admin, prof.run_as if prof else None)
        # Before the command is built: the command names this directory, and
        # tmux quietly goes back to a shared socket in /tmp if it is not there.
        self.prepare_tmux_dir(crew_id, (prof.run_as if prof else None) or self.run_as)
        command = self._behind_the_launcher(
            mate, self._build_command(mate, spec, prompt, prompt_path, prof))
        mate.meta["command"] = list(command)

        await self._ensure_session()

        # The environment has to be set on the session BEFORE the window is
        # created. tmux copies it into a pane at creation time, so setting it
        # afterwards reaches nothing, and the worker starts with no credentials
        # and dies about ten seconds later with exit code 1 and no output.
        merged_env = {**(self.default_env or {}), **(dict(env) if env else {})}
        for key, value in merged_env.items():
            await self.tmux.run(
                "set-environment", "-t", f"={self.session}", str(key), str(value), check=False
            )

        try:
            window_id, pane_id = await self.tmux.new_window(
                self.session, name=window_name, cwd=str(workdir), command=command
            )
        except TmuxError:
            LOG.exception("could not open a tmux window for %s; cleaning up", crew_id)
            if is_worktree and repo_root:
                await self._remove_worktree(repo_root, workdir, branch)
            raise

        mate.window_id = window_id
        mate.pane_id = pane_id

        # Keep the window after the process exits so the final screen can still be read
        # and the exit code recovered. If this loses a race against an instant crash the
        # window is simply gone, and reconciliation calls that "lost", which is correct.
        target = window_id or f"={self.session}:{window_name}"
        await self.tmux.set_window_option(target, "remain-on-exit", "on")
        await self.tmux.set_window_option(target, "automatic-rename", "off")

        # Everything the window prints also goes to a file, from now until it
        # dies. tmux only keeps what fits in the pane, so an hour-long job has
        # scrolled most of its life away by the time anyone asks what happened.
        # `-o` means "only if not already piping", so a reconnect cannot double it.
        log_path = self._log_path(mate)
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            await self.tmux.run(
                "pipe-pane", "-o", "-t", target,
                f"cat >> {shlex.quote(str(log_path))}",
                check=False,
            )
        except Exception as exc:
            LOG.warning("could not start a log for %s: %s", crew_id, exc)

        # And only now is the worker itself started. The launcher in front of
        # it has been waiting for this file, so everything the worker prints,
        # from its first byte, is in the log above and on a window that is
        # kept when it exits - which is what a worker that dies at once has
        # left to say why (`crew_launch.py`).
        self._let_go(mate)

        self._insert(mate)
        self._log_event(crew_id, "spawned", "starting", {
            "mode": spec.name, "workdir": str(workdir), "branch": branch,
            "window": window_name, "window_id": window_id,
        })
        LOG.info(
            "spawned %s (%s) mode=%s window=%s workdir=%s branch=%s",
            crew_id, title, spec.name, window_name, workdir, branch or "-",
        )
        return mate

    def already_working_on(self, expects: Sequence[str] | None
                           ) -> tuple[str, set[str]] | None:
        """A job still running whose declared files overlap these, and what they share.

        A folder counts as everything in it, so a job that says
        ``rouh/static/`` and a job that says ``rouh/static/app.js`` are
        working on the same thing. Matching the strings alone would miss exactly
        the case worth catching.
        """
        mine = _expects(expects)
        if not mine:
            return None
        for mate in self._select_all():
            if mate.status in TERMINAL_STATUSES:
                continue
            theirs = _expects((mate.meta or {}).get("expects"))
            shared = {a if len(a) >= len(b) else b
                      for a in mine for b in theirs
                      if a == b or a.startswith(b + "/") or b.startswith(a + "/")}
            if shared:
                return mate.id, shared
        return None

    async def _prepare_workdir(
        self, crew_id: str, repo: str | None, slug: str, base: str,
        prof: WorkerProfile | None = None,
    ) -> tuple[Path, Path | None, str | None, bool]:
        """Return ``(workdir, repo_root, branch, is_worktree)``.

        A scratch directory is only ever for a job given no repository. A job
        given one gets a worktree of it or is refused here, before any worker
        exists: on 27 October 2026 job 55a6f8a1 was given the person's
        workspace, git run as the ``assistant`` user refused the root-owned
        checkout, the job was started in an empty scratch directory instead,
        changed nothing, and only said "no repository to land in" at the end.
        """
        user = prof.git_user if prof else None
        if not repo:
            workdir = self.scratch_dir / crew_id
            workdir.mkdir(parents=True, exist_ok=True)
            return workdir, None, None, False

        given = repo
        if prof and prof.given_repo and prof.own_checkout and _same_dir(repo, prof.given_repo):
            repo = prof.own_checkout
            LOG.info("%s: %s is made from %s, %s's own checkout of it",
                     crew_id, given, repo, user or "this user")
        repo_root, why = await self._git_root(repo, user)
        if repo_root is None:
            raise CrewError(
                f"{given} could not be opened as a git repository"
                + (f" ({repo})" if repo != given else "")
                + (f" by the user {user}" if user else "")
                + f": {why}. Nothing was started.")

        # A repository with no commits yet cannot have a worktree added to it.
        rc, _, _ = await _run(self._git_argv(user, "rev-parse", "--verify", "HEAD"), cwd=repo_root)
        if rc != 0:
            raise CrewError(
                f"{repo_root} has no commits yet, so no checkout of it can be made for "
                f"the job. Nothing was started.")

        if prof and prof.base:
            # Start from what is on the remote now, not from whenever this
            # checkout last pulled: another job may have landed since.
            rc, _, err = await _run(self._git_argv(user, "fetch", "-q", "origin"),
                                    cwd=repo_root, timeout=120.0)
            if rc != 0:
                LOG.warning("%s: could not fetch before starting: %s", crew_id, err.strip())
            base = prof.base

        branch = f"rouh/{date.today().isoformat()}-{slug}-{crew_id}"
        worktrees_dir = (Path(prof.worktrees_dir) if prof and prof.worktrees_dir
                         else self.worktrees_dir)
        workdir = worktrees_dir / crew_id
        if user and _running_as_root():
            # git makes the worktree as ``user``, so the folder it goes in has
            # to be theirs: /srv/assistant-jobs was made by root and stayed root's.
            _give_dir(worktrees_dir, user)
        rc, out, err = await _run(
            self._git_argv(user, "worktree", "add", "-b", branch, str(workdir), base),
            cwd=repo_root,
            timeout=120.0,
        )
        if rc != 0:
            raise CrewError(
                f"could not create a git worktree for {repo_root} at {workdir}: {err.strip()}"
            )
        LOG.info("%s: worktree %s on branch %s", crew_id, workdir, branch)
        rc, sha, _ = await _run(self._git_argv(user, "-C", str(workdir), "rev-parse", "HEAD"))
        self._base_shas[crew_id] = sha.strip() if rc == 0 else ""
        return workdir, repo_root, branch, True

    async def _git_root(self, repo: str, user: str | None = None) -> tuple[Path | None, str]:
        """The repository's top, asked of git as ``user``; else None and git's own reason."""
        path = Path(repo).expanduser()
        if not path.is_dir():
            return None, "there is no such folder"
        rc, out, err = await _run(self._git_argv(user, "rev-parse", "--show-toplevel"), cwd=path)
        if rc != 0 or not out.strip():
            said = " ".join((err or "").strip().splitlines()[:1]) or f"git exited {rc}"
            return None, said
        return Path(out.strip()), ""

    async def _ensure_session(self) -> None:
        if await self.tmux.has_session(self.session):
            return
        # The keepalive window means the session survives every crewmate finishing.
        await self.tmux.new_session(
            self.session,
            cwd=str(self.workspace),
            window_name=KEEPALIVE_WINDOW,
            command=["sh", "-c", "while :; do sleep 3600; done"],
        )
        LOG.info("created tmux session %r", self.session)

    def _supported_flags(self) -> set[str]:
        """The long options this build of Claude Code accepts, read from --help."""
        if self._flags_cache is not None:
            return self._flags_cache
        flags: set[str] = set()
        try:
            program = self._launcher[0] if not callable(self._launcher) else "claude"
            out = subprocess.run(
                [str(program), "--help"], capture_output=True, text=True, timeout=20
            )
            said = (out.stdout or "") + (out.stderr or "")
            flags = set(re.findall(r"--[a-z][a-z0-9-]*", said))
            # 2.1.280 lists the file form only as "--append-system-prompt[-file]".
            if "--append-system-prompt[-file]" in said:
                flags.add("--append-system-prompt-file")
        except Exception:
            LOG.warning("could not read the flags this claude supports; using the safe subset")
        self._flags_cache = flags
        return flags

    def _build_command(
        self, mate: Crewmate, spec: ModeSpec, prompt: str, prompt_path: Path,
        prof: WorkerProfile | None = None,
    ) -> list[str]:
        """Build the argv tmux will exec. Never a shell string.

        A callable ``launcher`` gets full control and is what tests use, so the suite
        never spends a token. A sequence is treated as the program plus its leading
        arguments, with the mode flags and the prompt appended.

        Either way the result is wrapped in this crewmate's own tmux world, so
        even a launcher that decides everything else cannot decide that.
        """
        if callable(self._launcher):
            built = self._launcher(mate=mate, spec=spec, prompt=prompt, prompt_path=prompt_path)
            return [*self._own_tmux_env(mate), *[str(part) for part in built]]

        argv = [str(part) for part in self._launcher]
        argv += spec.claude_flags()
        if prof:
            argv += list(prof.extra_flags)

        # Claude Code's flags differ between versions, and the machine this was
        # written on is not the machine it runs on. 2.1.2 has no --name at all
        # and spells the deny flag --disallowed, while later builds use
        # --disallowed-tools. An unknown flag is not a warning: the process
        # prints one line and exits, the pane dies with status 1, and the only
        # symptom upstream is a job that "failed" with no output. So ask the
        # binary what it accepts rather than assuming.
        supported = self._supported_flags()
        # This machine's own MCP servers, which a brand new worktree has no
        # other way of getting. Asked of the binary first, like every other
        # flag here: a build without --mcp-config would print one line, exit 1,
        # and look exactly like a job that failed with no output.
        if "--mcp-config" in supported:
            mcp = self._merged_mcp_config(Path(mate.workdir), job_id=mate.id,
                                          outbox_url=self.outbox_url)
            if mcp:
                argv += ["--mcp-config", str(mcp)]
        if "--name" in supported:
            argv += ["--name", f"rouh-{mate.id}"]
        # Which model the worker is and how hard it thinks: the default pair,
        # asked for now, so a change in Settings reaches the next worker. A
        # launcher or a profile that names its own model or effort keeps it.
        # The effort only when this build takes the flag, for the same reason
        # --name is: a build that does not know --effort prints one line,
        # exits 1, and the job looks like it failed with no output.
        model, effort = "", self.effort
        if self.defaults is not None:
            try:
                work = self.defaults()
                model, effort = work.model, work.effort
            except Exception:
                LOG.exception("the default model could not be read; the worker is "
                              "started without one")
        if model and not _flag_value(argv, "--model"):
            argv += ["--model", model]
        if effort and "--effort" in supported and "--effort" not in argv:
            argv += ["--effort", effort]
        # The agent instructions, read from the database now, before anything
        # else the worker is told: Claude Code puts them in its system prompt.
        # As a file beside the prompt, never on the command line: tmux refuses
        # a command of more than about 16 KB ("command too long", tmux 3.6),
        # and the instructions alone are 13 KB. The file is this worker's copy
        # of what it was given, made from the rows a moment ago; nothing reads
        # it but this worker. Never a reason not to start the worker.
        if self.instructions is not None and "--append-system-prompt-file" in supported:
            told = ""
            try:
                told = self.instructions(mate.id, str((mate.meta or {}).get("in_play") or ""))
            except Exception:
                LOG.exception("the agent instructions could not be read; the worker is "
                              "started without them")
            if told:
                given = prompt_path.with_name("instructions.md")
                given.write_text(_owner.say(told), encoding="utf-8")
                with contextlib.suppress(Exception):
                    if (who := (prof.run_as if prof else None) or self.run_as):
                        shutil.chown(given, user=who, group=who)
                argv += ["--append-system-prompt-file", str(given)]
        # The deny rules are NOT passed on the command line, and that is
        # deliberate. Both spellings of the flag take "<rules...>", which
        # commander treats as variadic: it keeps eating arguments until the next
        # option. The prompt is the last argument, so the final --disallowed
        # swallowed the entire task as if it were one more rule. Claude Code
        # then started with no instruction at all and sat at an empty prompt
        # for ever, looking exactly like a worker that had hung.
        #
        # permissions.deny in the settings file is the mechanism that actually
        # binds anyway, so nothing is lost by leaving the flag off.

        run_as = (prof.run_as if prof else None) or self.run_as
        run_home = (prof.run_home if prof else None) or self.run_home
        unset = list(prof.unset_env) if prof else []
        # runuser without -l keeps the environment, so the API key set on the
        # tmux session still arrives. Only HOME has to be stated, because
        # Claude Code keeps its config there and root's copy is not readable
        # by this user. A profile can also take variables away, and the one
        # that matters is the key: a job meant to run on the subscription
        # would otherwise quietly run on the key, which Claude Code prefers.
        env_args = self._own_tmux_env(mate, unset=unset,
                                      home=run_home if run_as else None)
        if run_as:
            argv = ["runuser", "-u", run_as, "--", *env_args, *argv]
        else:
            argv = [*env_args, *argv]

        inline = prompt.encode("utf-8")
        if len(inline) <= MAX_INLINE_PROMPT_BYTES:
            argv.append(prompt)
        else:
            # Linux caps one argv element at 128 KiB, so a very long brief is handed
            # over by reference instead. The file is written either way.
            argv.append(
                f"Read the file {prompt_path} and carry out the task it describes. "
                "It is your full brief, including the limits you must work inside."
            )
        return argv

    # -- a tmux world of each crewmate's own -------------------------------------

    def worker_tmux_dir(self, crew_id: str) -> Path:
        """The private ``TMUX_TMPDIR`` for one crewmate.

        Derived from the id alone, so the command a job was started with can be
        rebuilt later without consulting anything.
        """
        return self.tmux_dirs / crew_id

    def _own_tmux_env(self, mate: "Crewmate", *, unset: Sequence[str] = (),
                      home: str | None = None) -> list[str]:
        """The ``env`` prefix that puts a crewmate in a tmux world of its own.

        This is not belt and braces. tmux sets ``TMUX`` in every pane it opens,
        and a tmux client reads ``TMUX`` before it reads ``TMUX_TMPDIR``, so a
        crewmate that runs tmux without naming a socket reaches the very server
        Rouh keeps every job in - which is how one worker's tidy-up stopped
        three siblings and Rouh's own windows in the same second on
        17 September 2026. With ``TMUX`` taken out and ``TMUX_TMPDIR`` pointed
        somewhere private, the worst such a command can reach is a server this
        crewmate started itself.

        The directory has to exist. tmux falls back to ``/tmp`` when it cannot
        make ``$TMUX_TMPDIR/tmux-<uid>``, which would put the crewmate back on a
        shared socket, so `prepare_tmux_dir` runs before the window opens.
        """
        parts = ["env", "-u", "TMUX"]
        for name in unset:
            parts += ["-u", str(name)]
        parts.append(f"TMUX_TMPDIR={self.worker_tmux_dir(mate.id)}")
        if home:
            parts.append(f"HOME={home}")
        # Which job this is and which Rouh it belongs to, for `rouh-task`, which
        # changes a task's status or summary in that Rouh and says it was this job
        # (`rouh/taskrecord.py`). A world a check stands up is its own Rouh, not 8021.
        parts.append(f"ROUH_JOB={mate.id}")
        parts.append(f"ROUH_URL={self.rouh_url}")
        # And the commands themselves, from Rouh's own code: a job works in a
        # checkout of the workspace, which holds no code (21 October 2026).
        own_bin = str(Path(__file__).resolve().parent.parent / "bin")
        if os.path.isdir(own_bin):
            parts.append(f"PATH={own_bin}:{os.environ.get('PATH') or '/usr/local/bin:/usr/bin:/bin'}")
        return parts

    @property
    def rouh_url(self) -> str:
        """This Rouh's own address on this machine, worked out from where its hooks go."""
        from urllib.parse import urlsplit, urlunsplit

        parts = urlsplit(self.callback_url)
        return urlunsplit((parts.scheme, parts.netloc, "", "", ""))

    def prepare_tmux_dir(self, crew_id: str, owner: str | None = None) -> Path:
        """Make the crewmate's private tmux directory, owned by whoever runs it."""
        path = self.worker_tmux_dir(crew_id)
        try:
            path.mkdir(parents=True, exist_ok=True)
            path.chmod(0o700)
            self._hand_over(path, owner)
        except OSError as exc:
            # Not fatal: the job can still run. It is logged loudly because the
            # isolation above quietly stops working if this directory is missing.
            LOG.warning("could not make a private tmux directory at %s: %s", path, exc)
        return path

    async def close_tmux_dir(self, crew_id: str) -> None:
        """Stop any tmux server this crewmate started, then take its directory away.

        Each socket is named explicitly with ``-S``, so this can only ever reach
        a server whose socket file is inside this crewmate's own directory.
        """
        path = self.worker_tmux_dir(crew_id)
        if not path.is_dir():
            return
        for sock in sorted(path.glob("tmux-*/*")):
            if not sock.is_socket():
                continue
            with contextlib.suppress(Exception):
                await _run([self.tmux.binary, "-S", str(sock), "kill-server"], timeout=10.0)
                LOG.info("stopped the private tmux server %s of %s", sock, crew_id)
        shutil.rmtree(path, ignore_errors=True)

    # -- prompt, settings, trust -------------------------------------------------

    def _compose_prompt(self, *, task: str, spec: ModeSpec, crew_id: str,
                        workdir: Path, branch: str | None, repo: Path | None,
                        prof: WorkerProfile | None = None) -> str:
        lines = [task.strip(), "", "---", "", "## How you are running"]
        lines.append(
            f"You are a Rouh crewmate, id `{crew_id}`, running unattended in a tmux "
            f"window in mode `{spec.name}`."
        )
        lines.append(f"Working directory: `{workdir}`.")
        if repo and branch:
            lines.append(
                f"This is a git worktree of `{repo}`, checked out on the new branch "
                f"`{branch}`. That branch is yours. Nothing you do here touches anyone "
                "else's checkout."
            )
        elif repo:
            lines.append(f"Source repository: `{repo}`.")
        else:
            lines.append("This is a scratch directory, not a git repository.")
        if prof and prof.instructions:
            lines += ["", "## What kind of job this is", prof.instructions]
        lines += ["", "## What this mode allows", spec.instructions]
        lines += ["", "## Email", MAIL_INSTRUCTION]
        lines += ["", "## A browser", BROWSER_INSTRUCTION]
        lines += ["", "## Files you are given", FILES_INSTRUCTION]
        lines += [
            "",
            "## Finishing",
            "Nobody is reading the screen. When you stop, write a short plain-language "
            "summary as your last message: what you did, what you changed, anything you "
            "could not do, and anything a person must decide. That summary is what gets "
            "read back out loud, so no jargon and no shorthand.",
        ]
        # A worker's brief leaves Rouh here, past the place model requests have the owner's
        # marks filled in (`rouh/owner.py`), so they are filled in here, for the person this
        # job is for: the one whose turn started it, else the installation's one account.
        return _owner.say("\n".join(lines) + "\n")

    def _write_prompt(self, workdir: Path, prompt: str) -> Path:
        rouh_dir = workdir / ".rouh"
        rouh_dir.mkdir(parents=True, exist_ok=True)
        prompt_path = rouh_dir / "prompt.md"
        prompt_path.write_text(prompt, encoding="utf-8")
        return prompt_path

    def callback_url_for(self, crew_id: str, kind: str) -> str:
        """The URL a hook posts to. The crewmate id rides in the query string.

        Claude Code posts its own hook JSON as the body, and that body has no idea a
        crewmate exists. The id and the kind therefore go in the URL, which this module
        builds itself, so no user text is ever interpolated into it.
        """
        sep = "&" if "?" in self.callback_url else "?"
        return f"{self.callback_url}{sep}crew={crew_id}&kind={kind}"

    def _hook_entry(self, crew_id: str, kind: str) -> dict[str, Any]:
        url = self.callback_url_for(crew_id, kind)
        if self.hook_transport == "http":
            return {"type": "http", "url": url, "timeout": self.hook_timeout}
        # Argument-list curl: no shell anywhere, and the hook JSON arrives on stdin,
        # which "--data-binary @-" forwards untouched.
        return {
            "type": "command",
            "command": "curl",
            "args": [
                "-sS", "-m", str(self.hook_timeout), "-X", "POST",
                "-H", "Content-Type: application/json",
                "--data-binary", "@-", url,
            ],
            "timeout": self.hook_timeout + 5,
        }

    def build_settings(self, crew_id: str, spec: ModeSpec) -> dict[str, Any]:
        """The settings document written into the worktree. Public so tests can read it.

        Three of these hooks say what became of the job. The other four say what
        it is doing while it does it, and they are what the work tree is drawn
        from. All seven are the same shape and the same URL, differing only in
        the ``kind`` in the query string.

        The four telemetry hooks carry no ``matcher``, so they fire for every
        tool rather than a named few. Measured on the server on 8 September 2026
        against Claude Code 2.1.263: ``PreToolUse`` and ``PostToolUse`` both
        carry ``tool_use_id``, so a tool call is one node that opens and closes;
        ``PostToolUse`` adds ``duration_ms``; every event inside a sub-agent
        carries ``agent_id`` and the worker's own events do not, so nothing has
        to be inferred from timing.

        The cost is one curl per tool call, which the tool call waits for. It is
        a request to a port on the same machine, so it is milliseconds, and a
        Rouh that is down refuses the connection immediately rather than
        holding the worker up.
        """
        settings: dict[str, Any] = {
            "hooks": {
                # Claude Code finished a turn. This is the "it landed" signal.
                "Stop": [{"hooks": [self._hook_entry(crew_id, "stop")]}],
                # Claude Code wants a human: a permission prompt, or it has gone idle.
                # No matcher, so every notification subtype arrives.
                "Notification": [{"hooks": [self._hook_entry(crew_id, "notification")]}],
                # The session itself ended. Belt and braces against a missed Stop.
                "SessionEnd": [{"hooks": [self._hook_entry(crew_id, "session_end")]}],
                # A tool is about to run, and has just finished.
                "PreToolUse": [{"hooks": [self._hook_entry(crew_id, "pre_tool_use")]}],
                "PostToolUse": [{"hooks": [self._hook_entry(crew_id, "post_tool_use")]}],
                # A sub-agent opened, and closed. Its own tool calls arrive
                # between these two carrying its agent_id.
                "SubagentStart": [{"hooks": [self._hook_entry(crew_id, "subagent_start")]}],
                "SubagentStop": [{"hooks": [self._hook_entry(crew_id, "subagent_stop")]}],
            }
        }
        if spec.deny:
            settings["permissions"] = {"deny": list(spec.deny)}
        return settings

    def _write_settings(self, workdir: Path, crew_id: str, spec: ModeSpec) -> Path:
        claude_dir = workdir / ".claude"
        claude_dir.mkdir(parents=True, exist_ok=True)
        path = claude_dir / "settings.local.json"
        existing: dict[str, Any] = {}
        if path.exists():
            with contextlib.suppress(json.JSONDecodeError, OSError):
                existing = json.loads(path.read_text(encoding="utf-8"))
        merged = {**existing, **self.build_settings(crew_id, spec)}
        path.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
        return path

    def _seed_workspace_trust(self, workdir: Path, prof: WorkerProfile | None = None,
                              *, bypass: bool = True) -> None:
        """Mark the new worktree trusted, or the hooks are read and thrown away.

        Claude Code refuses to load hooks from a workspace nobody has trusted, and says
        so on stderr where nothing will see it. Its own message names this exact fix,
        and its cloud runner does the same thing. Both the given path and its resolved
        path are seeded, because /tmp is a symlink on macOS.

        A profile with its own home has its own config file, and that file must end
        up belonging to the profile's user, or Claude Code cannot write to it.
        """
        paths = {str(workdir), str(workdir.resolve())}
        # The worktree alone is not enough. Claude Code files trust under the
        # repository a worktree was made from (`_claude_project_root`), and
        # when the checkout's .claude/settings.json pre-approves a tool it
        # asks again, on the same screen, unless that repository is trusted:
        #
        #   This folder pre-approves 1 tool permission in .claude/settings.json:
        #     mcp__playwright
        #   > No, continue without these permissions
        #     Yes, I trust this folder
        #
        # This repository has pre-approved mcp__playwright since 20 September
        # 2026, so a worker in a worktree of it stopped there, and on 24
        # September two had sat on it for an hour. Trusting the repository is
        # what pressing Yes on that screen writes.
        if (repository := _claude_project_root(workdir)) is not None:
            paths |= {str(repository), str(repository.resolve())}
        # A job nobody watches cannot answer "use this MCP server?", which a
        # checkout's own .mcp.json raises before anything else, and the only
        # answer safe to give unseen is no: an .mcp.json can start any program.
        # The first research job sat at exactly that question.
        #
        # Both sources are approved: what the checkout committed, and what this
        # machine gives every run. The machine's own are handed over with
        # --mcp-config and need no approval, but a repository that later commits
        # the same name to its own .mcp.json would raise the question again, and
        # the answer is already known. `if prof` used to guard this, which left
        # the ordinary worker - the one with no profile at all - with no browser.
        offered = sorted(set(self._project_mcp_servers(workdir))
                         | set(_read_mcp_servers(MACHINE_MCP_SERVERS)))
        config_path = (Path(prof.run_home) / ".claude.json"
                       if prof and prof.run_home else self.claude_config_path)
        # Whoever the worker runs as, profile or not. It was the profile's user
        # alone, so the ordinary worker's own config file was rewritten as root
        # on every start and left root's (found on 24 September 2026, with
        # /var/www/rouh/home/.claude.json owned by root). Only when that file is
        # in the worker's own home: with none named it is this process's.
        owner = (prof.run_as if prof
                 else (self.run_as if self.run_home and not self._claude_config_given
                       else None))
        uses_key = not (prof and "ANTHROPIC_API_KEY" in prof.unset_env)
        try:
            config: dict[str, Any] = {}
            if config_path.exists():
                config = json.loads(config_path.read_text(encoding="utf-8"))
            projects, changed = _prepare_trust_document(config)
            # Bypass Permissions mode has its own one-time acceptance screen,
            # separate from the trust dialog and from onboarding. It is the
            # fourth first-run gate, and like the others it waits for ever.
            # It does NOT live in this file: `bypassPermissionsModeAccepted`
            # here is a legacy key the binary migrates away, and the value it
            # actually reads is `skipDangerousModePermissionPrompt` in the
            # user's settings.json. Writing the old key looks like it works and
            # changes nothing, which is how an hour goes missing.
            # Only for a job that will actually run with the checks off. A
            # profile's user is never given the acceptance ahead of time for a
            # mode it is not being started in.
            if prof is None or bypass:
                self._seed_dangerous_mode(config_path, owner)
            if _update_trust_theme(config):
                changed = True
            key = (self.default_env or {}).get("ANTHROPIC_API_KEY") or os.environ.get(
                "ANTHROPIC_API_KEY", ""
            )
            if _update_trust_access(config, projects, paths, offered, key, uses_key):
                changed = True
            if not changed:
                return
            config_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = config_path.with_suffix(".rouh-tmp")
            tmp.write_text(json.dumps(config, indent=2), encoding="utf-8")
            os.replace(tmp, config_path)
            if owner:
                with contextlib.suppress(Exception):
                    shutil.chown(config_path, user=owner, group=owner)
            LOG.info("seeded workspace trust for %s", ", ".join(sorted(paths)))
        except Exception:
            LOG.exception(
                "could not seed workspace trust in %s. Claude Code will ignore the hooks "
                "in this worktree and the crewmate will never call back. Fix by running "
                "claude once in %s and accepting the trust dialog.",
                config_path, workdir,
            )

    async def verify_hooks(self, crew_id_or_dir: str | os.PathLike[str],
                           *, timeout: float = 45.0) -> dict[str, Any]:
        """Ask Claude Code whether it accepts the settings file we wrote. Costs nothing.

        ``claude doctor`` validates the settings files in the current directory and
        names both the file and the offending key. No model is called and no tokens are
        spent, so this is safe to run on every spawn and it is what the test suite uses
        to prove the hooks config is still valid against the installed Claude Code.

        Returns ``{"ok": bool, "checked": bool, "problems": [...], "output": str}``.
        ``checked`` is False when the claude binary is missing or too slow, which is
        an unknown answer, not a pass.
        """
        target = Path(str(crew_id_or_dir))
        if not target.is_dir():
            mate = self.get(str(crew_id_or_dir))
            if mate is None:
                raise UnknownCrewmate(f"no crewmate or directory {crew_id_or_dir!r}")
            target = mate.workdir_path

        launcher = self._launcher if not callable(self._launcher) else ("claude",)
        binary = str(launcher[0]) if launcher else "claude"
        try:
            rc, out, err = await _run([binary, "doctor"], cwd=target, timeout=timeout)
        except (FileNotFoundError, CrewError) as exc:
            return {"ok": False, "checked": False, "problems": [str(exc)], "output": ""}

        blob = f"{out}\n{err}"
        problems = [
            line.strip(" -")
            for line in blob.splitlines()
            if "settings.local.json" in line and ("Unknown" in line or "Invalid" in line
                                                  or "ignored" in line or "expected" in line)
        ]
        return {"ok": rc == 0 and not problems, "checked": True,
                "problems": problems, "output": blob}

    # -- reading state -----------------------------------------------------------

    async def status(self, id: str | None = None) -> Crewmate | list[Crewmate]:
        """One crewmate or all of them, reconciled against what tmux really reports.

        A crewmate whose window has gone is marked ``lost`` here rather than being left
        at ``running`` for ever.
        """
        await self.reconcile()
        if id is None:
            return self._select_all()
        mate = self.get(id)
        if mate is None:
            raise UnknownCrewmate(f"no crewmate with id {id!r}")
        return mate

    def get(self, id: str) -> Crewmate | None:
        """Read one crewmate straight from the database, with no tmux round trip."""
        from .models import Crewmate as Row

        with self._db_lock:
            row = Row.objects.filter(id=str(id)).values().first()
        return Crewmate.from_row(row) if row else None

    def find_by_workdir(self, workdir: str | os.PathLike[str]) -> Crewmate | None:
        """Find a crewmate by the directory it works in.

        Used to recover the crewmate from a hook payload when the query string carrying
        the id did not survive the web layer. Paths are compared resolved, because macOS
        reports /private/tmp where the caller said /tmp.
        """
        from .models import Crewmate as Row

        wanted = str(workdir)
        with self._db_lock:
            row = Row.objects.filter(workdir=wanted).values().first()
        if row:
            return Crewmate.from_row(row)

        try:
            resolved = Path(wanted).resolve()
        except (OSError, ValueError):
            return None
        for mate in self._select_all():
            try:
                if Path(mate.workdir).resolve() == resolved:
                    return mate
            except (OSError, ValueError):
                continue
        return None

    def restarts(self) -> dict[str, str]:
        """Every job that died, by id, with the id it was started again as, or "".

        One query for the whole task list, which asks on every rebuild.
        """
        from .models import Crewmate as Row

        with self._db_lock:
            rows = list(Row.objects.filter(status="lost").values("id", "meta"))
        out: dict[str, str] = {}
        for row in rows:
            try:
                meta = json.loads(row["meta"] or "{}")
            except ValueError:
                meta = {}
            out[str(row["id"])] = str((meta or {}).get("restarted_as") or "")
        return out

    def _select_all(self) -> list[Crewmate]:
        from .models import Crewmate as Row

        with self._db_lock:
            rows = list(Row.objects.order_by("-created_at").values())
        return [Crewmate.from_row(row) for row in rows]

    async def list_windows(self, all_sessions: bool = True) -> list[dict[str, Any]]:
        """Raw tmux truth, used for reconciliation and useful on its own when debugging."""
        return await self.tmux.list_windows(None if all_sessions else self.session)

    def events(self, id: str, limit: int = 50) -> list[dict[str, Any]]:
        """The event log for one crewmate, newest last."""
        from .models import CrewEvent

        with self._db_lock:
            rows = list(CrewEvent.objects.filter(crew_id=str(id)).order_by("-seq")
                        .values()[:int(limit)])
        out = []
        for row in reversed(rows):
            item = dict(row)
            item["payload"] = json.loads(item["payload"] or "{}")
            out.append(item)
        return out

    # -- the work tree -----------------------------------------------------------

    def record_tree_event(self, crew_id: str, kind: str, payload: Mapping[str, Any],
                          *, at: float | None = None) -> None:
        """Store one telemetry hook, raw, with the time it arrived.

        Raw and undigested on purpose. The tree is rebuilt from these rows on
        every read, so a mistake in how it is read is a mistake that can be
        corrected and replayed. Nothing is derived here.
        """
        from .models import CrewTreeEvent

        moment = time.time() if at is None else float(at)
        blob = json.dumps(_trim_for_tree(_scrub(payload)))
        with self._db_lock:
            CrewTreeEvent.objects.create(crew_id=crew_id, kind=kind, at=moment, payload=blob)
        self._maybe_prune_tree_events(moment)
        self._register_subagent(crew_id, kind, payload, moment)
        self._tree_changed()

    def _register_subagent(self, crew_id: str, kind: str, payload: Mapping[str, Any],
                           at: float) -> None:
        """A sub-agent opening or closing, written down as a run of its own.

        A sub-agent is the third kind of running work and it used to be written
        down nowhere: it was a node the tree derived from this stream of events
        and nothing else, so it was on the orb and on no list. Now it is a row
        in `run` with its parent's id on it, which is what makes the orb draw
        it as a branch off its parent rather than as a spike of its own.

        The id is the one `rouh/tree.py` has always drawn it under - the
        first twelve characters of Claude Code's own ``agent_id`` - so the
        twigs of a sub-agent's own tool calls still find it.
        """
        try:
            from . import runs
            from .tree import AGENT_TOOLS

            if kind == "pre_tool_use":
                # Starting a sub-agent is itself a tool call, and the call says
                # which agent made it while the sub-agent's own announcement
                # does not. So the caller is remembered here, oldest first, and
                # the next announcement claims it: that is the only way a
                # sub-agent inside a sub-agent hangs off the right branch.
                if str(payload.get("tool_name") or "") in AGENT_TOOLS:
                    waiting = self._pending_agents.setdefault(crew_id, [])
                    waiting.append(str(payload.get("agent_id") or "")[:12])
                    del waiting[:-20]
                return
            if kind not in ("subagent_start", "subagent_stop"):
                return
            agent_id = str(payload.get("agent_id") or "")[:12]
            if not agent_id:
                return
            if kind == "subagent_stop":
                # Closes only what `sub_run` wrote down. Claude Code sends a
                # stop with no start after every turn, for the next prompt it
                # suggests, and that one closes nothing (`runs.sub_done`).
                runs.sub_done(agent_id, at=at)
                return
            waiting = self._pending_agents.get(crew_id) or []
            parent = (waiting.pop(0) if waiting else "") or crew_id
            runs.sub_run(parent, agent_id,
                         title=str(payload.get("agent_type") or "sub-agent"), at=at,
                         fallback_parent=crew_id)
        except Exception:
            LOG.exception("could not write a sub-agent of %s to the run register", crew_id)

    def _maybe_prune_tree_events(self, now: float, *, keep: float = 6 * 3600.0) -> None:
        """Throw away telemetry nobody can still be looking at.

        A busy worker fires a few events a second, so this table would otherwise
        grow without limit. Six hours is far longer than the minute the tree
        remembers, and short enough that the file stays small.
        """
        if now - self._tree_pruned_at < 60.0:
            return
        from .models import CrewTreeEvent

        self._tree_pruned_at = now
        with self._db_lock:
            CrewTreeEvent.objects.filter(at__lt=now - keep).delete()

    def tree_events(self, *, window: float = 900.0, limit: int = 4000,
                    now: float | None = None) -> list[dict[str, Any]]:
        """Everything the work tree is built from, ready for ``tree.build_tree``.

        Two sources, deliberately. The stored hooks say what is happening inside
        each worker. The ``crewmates`` rows say whether the worker itself is
        still alive, and they are what makes the tree honest after a restart or
        after the reconciliation sweep has marked something lost: the row is
        authoritative and survives any pruning of the events.

        Hook events for a worker that is not in the row set are dropped, or a
        worker that finished an hour ago would come back as a node with no name
        and nothing to close it.
        """
        moment = time.time() if now is None else now
        events: list[dict[str, Any]] = []
        wanted: set[str] = set()
        # Asked of the database rather than filtered in Python, because this
        # runs twice a second for as long as a tab is open and the crewmates
        # table only ever grows. The timestamps are ISO strings always written
        # in UTC by the same function, so comparing them as text is comparing
        # them as times.
        from django.db.models import Q

        from .models import Crewmate as Row
        from .models import CrewTreeEvent

        cutoff = clock.utc_iso(moment - window, timespec="seconds")
        with self._db_lock:
            rows = list(Row.objects.filter(
                ~Q(status__in=sorted(TERMINAL_STATUSES))
                | Q(finished_at__gte=cutoff) | Q(updated_at__gte=cutoff)
            ).order_by("created_at").values())
        for mate in (Crewmate.from_row(row) for row in rows):
            # `finished_at` is when the first Stop arrived, and a worker that
            # launches a sub-agent asynchronously goes on working after that.
            # The later of the two is when it was last heard from, which is
            # what the tree should start forgetting it from.
            finished = clock.epoch(mate.finished_at, zulu=False)
            if finished is not None:
                finished = max(finished, clock.epoch(mate.updated_at, zulu=False) or finished)
            if not mate.alive and (finished is None or moment - finished > window):
                continue
            wanted.add(mate.id)
            events.append({
                "kind": "worker",
                "at": clock.epoch(mate.created_at, zulu=False) or moment,
                "crew_id": mate.id,
                "payload": {
                    "title": mate.title,
                    "mode": mate.mode,
                    "status": mate.status,
                    "closed_at": finished,
                },
            })
        if not wanted:
            return events

        with self._db_lock:
            rows = list(CrewTreeEvent.objects.filter(at__gte=moment - window)
                        .order_by("-seq").values("crew_id", "kind", "at", "payload")
                        [:int(limit)])
        for row in rows:
            if row["crew_id"] not in wanted:
                continue
            try:
                payload = json.loads(row["payload"] or "{}")
            except json.JSONDecodeError:
                payload = {}
            events.append({
                "kind": row["kind"],
                "at": float(row["at"]),
                "crew_id": row["crew_id"],
                "payload": payload,
            })
        return events

    async def reconcile(self) -> list[Crewmate]:
        """Compare the record against tmux and correct it. Returns what changed."""
        live = await self.tmux.list_windows(None)
        by_name = {(w["session"], w["window_name"]): w for w in live}

        changed: list[Crewmate] = []
        for mate in self._select_all():
            if not mate.alive:
                continue
            window = by_name.get((mate.session, mate.window_name))
            if window is None:
                self._set_status(mate, "lost", reason="tmux window is gone")
                self._log_event(mate.id, "reconciled", "lost",
                                {"reason": "window not found", "window": mate.window_name})
                changed.append(mate)
                # Told like any other change, so a job that vanished is reported
                # to the person, not only corrected in the record.
                await self._notify(mate, "lost", {"reason": "its window is gone"})
                continue

            # The window id restarts at @0 when the tmux server restarts, so trust the
            # name and refresh the id from what tmux reports now.
            if window["window_id"] != mate.window_id or window["pane_id"] != mate.pane_id:
                mate.window_id = window["window_id"]
                mate.pane_id = window["pane_id"]
                self._update(mate, window_id=mate.window_id, pane_id=mate.pane_id)

            if window["dead"]:
                exit_code = window["exit_code"]
                # Its last screen, in case the log never got its last words:
                # a dead window is kept precisely so this can still be read.
                screen = ""
                with contextlib.suppress(Exception):
                    screen = await self.tmux.capture(window["window_id"] or window["pane_id"], 80)
                self._set_status(mate, "lost", exit_code=exit_code, screen=screen,
                                 reason="the process exited without reporting")
                self._log_event(mate.id, "reconciled", "lost",
                                {"reason": "pane dead", "exit_code": exit_code})
                changed.append(mate)
                await self._notify(mate, "lost", {"reason": "it exited without reporting",
                                                  "exit_code": exit_code})
        return changed

    # -- acting on a crewmate ----------------------------------------------------

    async def archive(self, id: str, on: bool = True) -> Crewmate:
        """Put a job out of the lists' way, or bring it back. Archiving stops it.

        Archiving used to be bookkeeping alone, and it left the worker running
        in a tmux window nobody was looking at any more. The person asked on
        16 September 2026 for the opposite: putting a job away is how they say
        they are done with it, so the terminal behind it is closed too. A job
        still alive is killed first, down the same path ``stop_task`` takes, and
        only then is the row marked.

        A job whose status says it has finished may still have its terminal
        open: "done" means Claude Code finished a turn and reported, not that
        its process exited, so the worker usually sits at its prompt in its
        window until somebody closes it. Every archive of a finished job used to
        leave that window running for good. So the status is not trusted for
        this: tmux is asked whether this job's own window is still there, and if
        it is, it is closed, down the same narrow path ``kill`` uses, matching
        this job's session and window name and nothing else. The status is left
        as it was, because the job did finish. A window already gone is simply
        nothing to close.

        Bringing one back is bookkeeping in both directions: nothing is started
        again, and a job that was stopped stays stopped.

        Two things archiving still does not touch. The checkout is left where it
        is - this closes the terminal, it does not throw the work away - and
        ``updated_at`` is put back to what it was, because archiving is not the
        job doing something and must not move the row to the top of a list
        sorted by when it last did.
        """
        mate = self.get(id)
        if mate is None:
            raise UnknownCrewmate(f"no crewmate with id {id!r}")
        was = mate.updated_at
        if on and mate.alive:
            try:
                await self.kill(id)
            except Exception as exc:
                # The row goes away whatever the terminal did. A window that has
                # already gone, or a tmux that will not answer, must not leave
                # the person with an error message and the job still on the
                # list: the failure goes in the log and the archiving carries on.
                LOG.exception("could not stop %s while archiving it", id)
                self._log_event(id, "archive_stop_failed", mate.status,
                                {"error": f"{type(exc).__name__}: {exc}"[:300]})
            mate = self.get(id) or mate
        elif on:
            try:
                await self._close_finished(mate)
            except Exception as exc:
                LOG.exception("could not close the window of %s while archiving it", id)
                self._log_event(id, "archive_stop_failed", mate.status,
                                {"error": f"{type(exc).__name__}: {exc}"[:300]})
        if bool(mate.archived) != bool(on):
            self._update(mate, archived=int(bool(on)), updated_at=was)
            mate.archived = bool(on)
            self._log_event(mate.id, "archived", mate.status, {"on": bool(on)})
            LOG.info("%s %s", mate.id, "archived" if on else "unarchived")
        elif mate.updated_at != was:
            # Already archived and still running: it was stopped just now, and
            # the stop must not move the row either.
            self._update(mate, updated_at=was)
        return mate

    async def _close_finished(self, mate: Crewmate) -> bool:
        """Close the window of a job that has finished but may still be running.

        Returns whether there was a window to close. The status is not changed:
        the job finished, and closing its terminal does not make it killed.
        """
        target = await self._resolve_target(mate)
        if target:
            await self.tmux.kill_window(target)
            LOG.info("closed the window %s of the finished job %s", mate.window_name, mate.id)
            self._log_event(mate.id, "closed", mate.status, {"window": mate.window_name})
        await self.close_tmux_dir(mate.id)
        return bool(target)

    async def send(self, id: str, text: str) -> Crewmate:
        """Type more input into a live crewmate and press Enter.

        The text goes through a tmux paste buffer over stdin, so it never reaches a
        shell and a multi-line message arrives as one paste instead of submitting on
        every newline.
        """
        mate = self.get(id)
        if mate is None:
            raise UnknownCrewmate(f"no crewmate with id {id!r}")
        target = await self._require_target(mate)

        await self.tmux.paste(target, text, buffer_name=f"rouh-{mate.id}")
        submitted = await self.tmux.send_enter(target)
        if not submitted:
            LOG.warning(
                "%s: the text was typed but the prompt did not clear; it may be unsent",
                mate.id,
            )

        if mate.status in ("done", "waiting", "starting"):
            self._set_status(mate, "running", clear_finished=True)
        self._log_event(mate.id, "sent", mate.status,
                        {"chars": len(text), "submitted": submitted})
        LOG.info("sent %d chars to %s (submitted=%s)", len(text), mate.id, submitted)
        return mate

    async def capture(self, id: str, lines: int = 200) -> str:
        """The tail of what that window is showing right now."""
        mate = self.get(id)
        if mate is None:
            raise UnknownCrewmate(f"no crewmate with id {id!r}")
        target = await self._resolve_target(mate)
        if target is None:
            raise CrewError(
                f"crewmate {id} has no tmux window any more (status {mate.status}); "
                "there is nothing left to capture"
            )
        return _tail(await self.tmux.capture(target, lines), lines)

    async def describe(self, id: str, lines: int = 120) -> dict:
        """Everything knowable about one crewmate, including what is on its screen.

        This exists because "waiting" on its own is useless. A person asking "what
        is it doing" wants the answer, and the answer is on the terminal.
        """
        mate = self.get(id)
        if mate is None:
            raise UnknownCrewmate(f"no crewmate with id {id!r}")
        await self.reconcile()
        mate = self.get(id) or mate
        # as_dict(), not get(). Crewmate.get(key) is a dictionary-style accessor
        # and calling it with no argument raises, which turned "show me the
        # worker's screen" into a type error the assistant then had to apologise
        # for while it read the log instead.
        out = mate.as_dict()
        out["log_path"] = str(self._log_path(mate))
        try:
            screen = read_screen(await self.capture(id, lines))
            out.update(
                asking=screen["asking"],
                question=screen["question"],
                options=screen["options"],
                screen=screen["tail"],
                last_line=screen["last_line"],
            )
        except Exception as exc:
            out.update(
                asking=False, question="", options=[], screen="",
                screen_error=f"{type(exc).__name__}: {exc}",
            )
        return out

    async def answer(self, id: str, choice: str) -> Crewmate:
        """Answer a question the crewmate is showing.

        A number picks that option. Anything else is typed in as text. Both end
        with Enter, which is what the prompt is waiting for.
        """
        return await self.send(id, str(choice).strip())

    @staticmethod
    def _project_mcp_servers(workdir: Path) -> list[str]:
        """The servers a checkout's own .mcp.json asks to start, which are allowed.

        A worker here drives a real browser over Playwright MCP, so the server
        the repository committed has to be on before it starts, not waiting
        behind a question nobody is there to answer.
        """
        return sorted(_read_mcp_servers(workdir / ".mcp.json"))

    @property
    def outbox_url(self) -> str:
        """Where this Rouh takes a job's queued email: beside where its hooks go.

        Worked out from the hook address rather than configured again, so a
        world a check stands up on a port of its own gets its own jobs' notes
        instead of sending them to the server on 8021.
        """
        from urllib.parse import urlsplit, urlunsplit

        parts = urlsplit(self.callback_url)
        return urlunsplit((parts.scheme, parts.netloc, "/internal/outbox", "", ""))

    @staticmethod
    def _merged_mcp_config(workdir: Path, *, job_id: str = "",
                           outbox_url: str = "") -> Path | None:
        """Write the MCP servers this job gets, and return the file to hand it.

        A job works in a worktree made a minute ago, and a directory Claude
        Code has never seen has no servers at all. That is why `/mcp` in a new
        job said "No MCP servers configured": the browser this repository
        insists every change is proved in was simply not there.

        Two things are merged: MACHINE_MCP_SERVERS, the list at the top of this
        repository that every job on this machine is entitled to, and the
        checkout's own .mcp.json. **The checkout's own entry wins a name
        collision**, which is what the second dict in the merge below does.

        Everything is then handed over with --mcp-config, including the
        checkout's own, and that is not belt and braces. Measured on Claude
        Code 2.1.274 on 21 September 2026: a checkout's .mcp.json is not loaded
        at all unless something enables it, and the thing that enables it is
        `enabledMcpjsonServers` in the checkout's own .claude/settings.json.
        The per-path approval this module also writes into ~/.claude.json is
        not what this build reads. Two worktrees, one of this repository and
        one of the person's workspace, were approved identically in
        ~/.claude.json and both committed a playwright to .mcp.json; the first
        came up "connected" and the second said "No MCP servers configured",
        and the only difference between them was that this repository commits
        a .claude/settings.json that turns it on. A server passed with
        --mcp-config needs no approval anywhere and came up connected in a git
        directory made seconds earlier, so that is the one road everything
        takes.

        The machine's ``rouh`` server is told which job it belongs to, and
        where this Rouh is, in its own environment (``ROUH_JOB``,
        ``ROUH_OUTBOX_URL``): a note a job queues is tagged with the id this
        manager gave it, never one the model wrote (`rouh/worker_mcp.py`).

        Returns the file to pass, or None when there is nothing to pass.
        """
        machine = _machine_mcp_servers()
        outbox = machine.get(OUTBOX_SERVER)
        if isinstance(outbox, dict) and job_id:
            outbox["env"] = {**(outbox.get("env") or {}), "ROUH_JOB": job_id,
                             **({"ROUH_OUTBOX_URL": outbox_url} if outbox_url else {})}
        wanted = {**machine, **_read_mcp_servers(workdir / ".mcp.json")}
        if not wanted:
            return None
        own = workdir / ".rouh"
        try:
            own.mkdir(parents=True, exist_ok=True)
            # .rouh/ is scratch for the job and must never reach the
            # repository. This repository ignores it by name, but a job also
            # works in the person's own workspace, which does not, so the
            # directory carries the rule with it.
            (own / ".gitignore").write_text("*\n", encoding="utf-8")
            path = own / "mcp.json"
            path.write_text(json.dumps({"mcpServers": wanted}, indent=2) + "\n",
                            encoding="utf-8")
            # The job may run as another user than the one that wrote this.
            path.chmod(0o644)
            return path
        except OSError as exc:
            LOG.warning("could not write the MCP servers into %s: %s", own, exc)
            return None

    def _seed_dangerous_mode(self, config_path: Path | None = None,
                             owner: str | None = None) -> None:
        """Answer the Bypass Permissions disclaimer before anything sees it."""
        settings = (config_path or self.claude_config_path).parent / ".claude" / "settings.json"
        try:
            current: dict[str, Any] = {}
            if settings.exists():
                current = json.loads(settings.read_text(encoding="utf-8")) or {}
            if current.get("skipDangerousModePermissionPrompt") is True:
                return
            current["skipDangerousModePermissionPrompt"] = True
            settings.parent.mkdir(parents=True, exist_ok=True)
            settings.write_text(json.dumps(current, indent=1), encoding="utf-8")
            self._hand_over(settings.parent, owner)
            LOG.info("accepted the bypass-permissions disclaimer in %s", settings)
        except Exception as exc:
            LOG.warning("could not pre-accept bypass permissions: %s", exc)

    def _hand_over(self, path: Path, user: str | None = None) -> None:
        """Give a directory to the user the worker runs as.

        Without this the worker cannot write in its own workspace and the job
        fails on the first edit with a permission error that looks like nothing
        else in the logs.
        """
        who = user or self.run_as
        if not who:
            return
        try:
            shutil.chown(path, user=who, group=who)
            for child in path.rglob("*"):
                with contextlib.suppress(Exception):
                    shutil.chown(child, user=who, group=who)
        except Exception as exc:
            LOG.warning("could not hand %s to %s: %s", path, who, exc)

    def _log_path(self, mate: "Crewmate") -> Path:
        return Path(mate.workdir) / ".rouh" / "session.log"

    def _log_paths(self, mate: Crewmate) -> list[Path]:
        """Where a job's log may be: `.rouh/`, or `.jarvis/` for a job from
        before the rename on 22 September 2026."""
        return [self._log_path(mate), Path(mate.workdir) / ".jarvis" / "session.log"]

    async def printed(self, mate: Crewmate, lines: int = 160) -> tuple[str, str]:
        """What a job printed, for a person to read, and where it was read from.

        Its window's own screen while tmux still has the window - running, or
        kept after it exited - because that is the job's terminal exactly as it
        looks. Otherwise its log, which is the same window as tmux piped it:
        mostly Claude Code moving the cursor about and redrawing its frame, so
        that is turned back into lines and the lines a redraw repeats are
        dropped. ``("", "")`` when there is neither.
        """
        with contextlib.suppress(Exception):
            target = await self._resolve_target(mate)
            if target:
                kept = _without_tmux(await self.tmux.capture(target, lines))
                while kept and not kept[-1]:
                    kept.pop()
                if any(kept):
                    return "\n".join(kept[-lines:]), "its window"
        for path in self._log_paths(mate):
            try:
                raw = _read_end(path, 262144)
            except OSError:
                continue
            kept = []
            for ln in _terminal_lines(raw):
                if not ln.strip() or _is_chrome(ln) or ln in kept[-40:]:
                    continue
                kept.append(ln)
            return "\n".join(kept[-lines:]), str(path)
        return "", ""

    # -- the launcher, and what a job that never reported died of ---------------

    @staticmethod
    def _launch_files(workdir: str | os.PathLike[str]) -> tuple[Path, Path]:
        """The two files between Rouh and `crew_launch.py`: the go-ahead it
        waits for, and the record of how the worker ended that it writes."""
        folder = Path(workdir) / ".rouh"
        return folder / "ready", folder / "exit.json"

    def _behind_the_launcher(self, mate: Crewmate, command: Sequence[str]) -> list[str]:
        """The worker's command, started by `crew_launch.py` rather than by tmux.

        So the worker waits until its window is kept and logged, and how it
        ended is written down even when it lived for a millisecond. Run by path
        and isolated, with this process's own Python, because the window is in
        the job's checkout and nothing there is Rouh's to import.
        """
        if not LAUNCHER.is_file():
            LOG.warning("%s is missing, so %s starts without it", LAUNCHER, mate.id)
            return list(command)
        ready, record = self._launch_files(mate.workdir)
        return [sys.executable, "-I", str(LAUNCHER), "--ready", str(ready),
                "--record", str(record), "--", *command]

    def _let_go(self, mate: Crewmate) -> None:
        ready, _ = self._launch_files(mate.workdir)
        try:
            ready.parent.mkdir(parents=True, exist_ok=True)
            ready.write_text(clock.utc_iso(timespec="seconds") + "\n", encoding="utf-8")
        except OSError as exc:
            # The launcher starts the worker anyway after a few seconds; only
            # its first words might miss the log.
            LOG.warning("could not tell %s's launcher to start it: %s", mate.id, exc)

    def death_of(self, mate: Crewmate, *, exit_code: int | None = None,
                 screen: str = "", because: str = "") -> dict[str, Any]:
        """What is known about how a job that never reported ended.

        Read when the job is found dead, and kept on its row as ``death``, so a
        death has a reason for as long as the job is on the list, whatever
        happens to its folder afterwards:

        ``at_launch``  it never started working: no hook ever arrived, and it
                       died within a minute of being started
        ``exit_code``  from tmux, or from the launcher's record
        ``said``       why, in words: what Claude Code's own SessionEnd hook
                       said when it sent one (`because`), otherwise the last
                       thing it printed that reads as a reason - the end of
                       its log first, then its window's last screen
        ``line``       all of that as the one short line its card shows, or ""
                       when nothing at all is known

        Never raises: a death with no reason is still a death.
        """
        _, record_path = self._launch_files(mate.workdir)
        record: dict[str, Any] = {}
        with contextlib.suppress(OSError, ValueError, TypeError):
            got = json.loads(record_path.read_text(encoding="utf-8"))
            record = got if isinstance(got, dict) else {}
        code = exit_code if exit_code is not None else record.get("exit_code")
        code = code if isinstance(code, int) else None

        started = record.get("started") or clock.epoch(mate.created_at, zulu=False)
        ended = record.get("ended") or time.time()
        lived = (float(ended) - float(started)) if started else None
        at_launch = mate.status == "starting" and (lived is None or lived < LAUNCH_SECONDS)

        # Only the very end of the log: a job that dies part way through has
        # a screen full of its own work above that, and an error it was merely
        # reading is not what it died of.
        said = because
        for path in ([] if said else self._log_paths(mate)):
            with contextlib.suppress(OSError):
                said = last_words(_read_end(path, 4096))
            if said:
                break
        said = (said or last_words("\n".join(_without_tmux(screen)))
                or str(record.get("said") or "")[:SAID_MOST])

        head = "Died at launch" if at_launch else "Died while working"
        if said:
            line = f"{head}: {said}"
        elif code is not None:
            line = f"{head}, with exit code {code}"
        else:
            line = ""
        return {"at_launch": at_launch, "exit_code": code, "said": said, "line": line,
                "lived": round(lived, 1) if lived is not None else None}

    async def tail_log(self, id: str, lines: int = 200) -> str:
        """The full history, not just what still fits on the screen.

        tmux only keeps what is in the pane. A job that has been running for an
        hour has scrolled most of its life away, so everything is also piped to
        a file from the moment the window opens.
        """
        mate = self.get(id)
        if mate is None:
            raise UnknownCrewmate(f"no crewmate with id {id!r}")
        path = self._log_path(mate)
        if not path.exists():
            return f"(no log at {path} yet)"
        try:
            data = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return f"(could not read {path}: {exc})"
        return _tail(_strip_ansi(data), lines)

    async def changes(self, id: str) -> dict:
        """What this worker actually did to the files.

        Reading the screen says what it claims to have done and the log says
        what it tried. Neither says what changed, which is the thing you
        actually want before trusting a job or throwing it away.
        """
        mate = self.get(id)
        if mate is None:
            raise UnknownCrewmate(f"no crewmate with id {id!r}")
        workdir = Path(mate.workdir)
        out: dict[str, Any] = {
            "id": mate.id, "title": mate.title, "status": mate.status,
            "workdir": str(workdir), "branch": mate.branch,
            "is_worktree": bool(mate.is_worktree),
        }
        if not workdir.exists():
            out["gone"] = "the working directory has been removed"
            return out

        git_user = (mate.meta or {}).get("git_user")

        async def git(*args: str) -> str:
            rc, stdout, _ = await _run(
                self._git_argv(git_user, "-C", str(workdir), *args), timeout=20
            )
            return stdout.strip() if rc == 0 else ""

        if mate.is_worktree and mate.branch:
            # Compare against where the branch started, not against main, or a
            # worker that started an hour ago reports everyone else's work too.
            base = await git("merge-base", "HEAD", "origin/main") or "HEAD~1"
            out["commits"] = [
                line for line in (await git("log", "--oneline", f"{base}..HEAD")).splitlines()
            ]
            out["diffstat"] = (await git("diff", "--stat", f"{base}..HEAD")).splitlines()[-12:]
            out["uncommitted"] = (await git("status", "--porcelain")).splitlines()[:20]
            remote = await git("ls-remote", "--heads", "origin", mate.branch)
            out["pushed"] = bool(remote)
            merged = await git("branch", "--contains", "HEAD", "-a")
            out["in_main"] = "origin/main" in merged
        else:
            files = []
            for path in sorted(workdir.rglob("*")):
                if path.is_file() and ".rouh" not in path.parts and ".claude" not in path.parts:
                    files.append(f"{path.relative_to(workdir)} ({path.stat().st_size}b)")
            out["files"] = files[:30]
        return out

    def set_meta(self, id: str, **values: Any) -> None:
        """Record something about a job after the fact, such as the page it made."""
        mate = self.get(id)
        if mate is None:
            return
        meta = dict(mate.meta or {}, **values)
        # Recording something about a job is not news of the job itself. The
        # orb reads updated_at as when a job last moved, so a page landing after
        # the job finished must not bring it back on the orb or lengthen its
        # "Took" (found by the session working on the orb, 12 September 2026).
        self._update(mate, meta=json.dumps(meta), updated_at=mate.updated_at)
        mate.meta = meta

    async def land(self, id: str, *, target: str = "main") -> dict:
        """Move a finished job's commits onto the remote's ``target`` branch.

        A job works on its own branch in its own checkout, so it never has to
        know about anyone else's work. Landing is the one moment the two meet:
        anything the job left uncommitted is committed here, so nothing it made
        is lost, and then ``land.sh`` does the rest, because it is the only
        thing anywhere allowed to push to ``main``.

        What that buys, and what this used to do instead (cards 488 and 489):
        work already on the target is recognised by patch rather than by text
        and reported as landed, instead of colliding with itself; one landing
        happens at a time, so the next one replays onto a target that has
        stopped moving; a conflict resolved once is remembered; the work exactly
        as the job wrote it is kept on a branch of its own before anything is
        resolved; and a real collision comes back as ``clash`` with a brief in
        ``handback`` for the job itself to fix, or, twice failed, as
        ``needs_person`` with a record the person is asked from.

        Safe to call twice. Once landed there is nothing new, and it says so.
        """
        mate = self.get(id)
        if mate is None:
            raise UnknownCrewmate(f"no crewmate with id {id!r}")
        out: dict[str, Any] = {"id": mate.id, "title": mate.title, "landed": False}
        if not (mate.is_worktree and mate.repo):
            out["reason"] = "this job has no repository to land in"
            return out
        workdir = Path(mate.workdir)
        if not workdir.exists():
            out["reason"] = "its working directory is gone"
            return out
        user = (mate.meta or {}).get("git_user")
        # The brief and the hook settings Rouh wrote into the checkout are
        # not the job's work and must never reach the repository.
        own_files = (":(exclude).rouh", ":(exclude).claude/settings.local.json")

        async def git(*args: str, timeout: float = 60.0) -> tuple[int, str, str]:
            return await _run(self._git_argv(user, "-C", str(workdir), *args), timeout=timeout)

        rc, status, _ = await git("status", "--porcelain", "--", ".", *own_files)
        if rc == 0 and status.strip():
            await git("add", "-A", "--", ".", *own_files)
            rc, _, _ = await git("commit", "-q", "-m",
                                 f"Job {mate.id}: work left uncommitted when it stopped")
            out["committed_leftovers"] = rc == 0

        got = await self.run_land_script(mate, target=target)
        out.update(got)
        if out.get("landed"):
            self.set_meta(mate.id, landed_sha=out.get("sha"), landed_at=clock.utc_iso(timespec="seconds"))
            self._log_event(mate.id, "landed", mate.status,
                            {"sha": out.get("sha"), "files": (out.get("files") or [])[:40],
                             **({"already": True} if out.get("already") else {})})
        elif out.get("reason") != "nothing new to land":
            self._log_event(mate.id, "land_failed", mate.status,
                            {"reason": out.get("reason"),
                             **({"conflict": out["conflict"]} if out.get("conflict") else {})})
        return out

    #: Where ``land.sh`` is. Beside this package, which is the root of the one
    #: repository both services come out of, so a job in any checkout climbs the
    #: same ladder. ``Config.land_script`` points it elsewhere for a test.
    LAND_SCRIPT = Path(__file__).resolve().parent.parent / "land.sh"

    async def run_land_script(self, mate: "Crewmate", *, target: str = "main",
                             answer: str = "", conflict: str = "") -> dict[str, Any]:
        """Run ``land.sh`` for one job and read the JSON it always prints.

        Run as the job's own git user where it has one, because the repository
        is that user's and git refuses another's ("dubious ownership"), and
        because the key that may push is theirs.

        ``answer`` carries the person's pick back to the same checkout, which is
        the other half of the conflict card: ``1`` replays the job's side over
        the target, ``2`` keeps the target's, ``3`` comes back here as a brief
        for the job to reconcile both, and ``4`` parks it with nothing moved.
        """
        user = (mate.meta or {}).get("git_user")
        script = str(getattr(self, "land_script", "") or self.LAND_SCRIPT)
        argv = ["bash", script, "--path", str(mate.workdir), "--target", target,
                "--run", mate.id, "--title", (mate.title or mate.id)[:120], "--quiet"]
        if (base := (mate.meta or {}).get("base_sha")):
            argv += ["--from", str(base)]
        if (land_dir := getattr(self, "land_dir", "")):
            argv += ["--land-dir", str(land_dir)]
        if answer:
            argv += ["--answer", str(answer)]
        if conflict:
            argv += ["--conflict", str(conflict)]
        if user and _running_as_root():
            # The same shape ``_git_argv`` uses, and for the same two reasons:
            # the repository is that user's, so git refuses another's outright,
            # and HOME has to be stated because runuser keeps root's and git
            # reads its identity and its ssh key out of it.
            argv = ["runuser", "-u", user, "--", "env", f"HOME={self._home_of(user)}", *argv]
        rc, stdout, stderr = await _run(argv, timeout=1900.0)
        said = [line for line in (stdout or "").splitlines() if line.strip()]
        try:
            out = json.loads(said[-1]) if said else {}
        except ValueError:
            out = {}
        if not isinstance(out, dict) or "state" not in out:
            tail = ((stderr or stdout) or "").strip()[-300:]
            LOG.warning("land.sh said nothing readable for %s (exit %s): %s", mate.id, rc, tail)
            return {"landed": False,
                    "reason": f"land.sh said nothing readable (exit {rc}): {tail}"}
        state = str(out.get("state") or "")
        answer_out: dict[str, Any] = {"landed": bool(out.get("landed")),
                                      "reason": str(out.get("reason") or "")}
        for key in ("sha", "files", "commits", "already", "conflict", "pre_branch",
                    "question", "attempt", "both_rewrote", "handback", "dropped",
                    # Landing includes deploying since 21 September 2026: these
                    # say whether what was pushed is what the machine is serving.
                    "deployed", "deploy", "deploy_reason"):
            if out.get(key) not in (None, "", []):
                answer_out[key] = out[key]
        if state in ("handback", "needs-person"):
            answer_out["clash"] = True
            answer_out["needs_person"] = state == "needs-person"
        elif state == "nothing":
            answer_out["reason"] = "nothing new to land"
        elif state == "parked":
            answer_out["parked"] = True
        return answer_out

    async def tidy(self, id: str | None = None, *, delete_branch: bool = False) -> dict:
        """Remove what a finished worker left on disk.

        Never touches one that is still going: a worktree pulled out from under
        a running job takes the job with it. Anything still alive is reported as
        skipped rather than silently ignored.
        """
        mates = [self.get(id)] if id else list(self._select_all())
        mates = [m for m in mates if m is not None]
        removed, skipped, freed = [], [], 0
        for mate in mates:
            if mate.status in ("running", "starting", "waiting"):
                skipped.append({"id": mate.id, "why": f"still {mate.status}"})
                continue
            workdir = Path(mate.workdir)
            size = 0
            if workdir.exists():
                size = sum(f.stat().st_size for f in workdir.rglob("*") if f.is_file())
            try:
                await self.kill(mate.id, remove_worktree=True, delete_branch=delete_branch)
                removed.append({"id": mate.id, "title": mate.title,
                                "freed_mb": round(size / 1048576, 1)})
                freed += size
            except Exception as exc:
                skipped.append({"id": mate.id, "why": f"{type(exc).__name__}: {exc}"})
        return {"removed": removed, "skipped": skipped,
                "freed_mb": round(freed / 1048576, 1)}

    #: What a live check titles every job it starts with. The only jobs
    #: :meth:`forget_test_jobs` will touch.
    TEST_JOB_SUFFIX = "- safe to delete"

    async def forget_test_jobs(self) -> dict:
        """Remove every finished test job as if it had never been started.

        A live check starts a throwaway job to see it on the orb, and each run
        left one to three of them on the person's task list for good. This
        stops such a job's tmux window and then deletes its row, its event log,
        its telemetry and its scratch folder - but only for a job that is
        plainly one of them:

        * titled ``... - safe to delete``;
        * already over. One still going is reported and left alone, never
          stopped, so a check that has not finished loses nothing;
        * working in a scratch folder of its own, not a repository, which is
          never true of the assistant's jobs or of Rouh changing itself;
        * whose folder sits directly in this manager's scratch area and is not
          a link. A folder anywhere else, or reached through a link, is not
          ours to delete, and the job is left whole rather than half removed.

        The window is stopped first, and only for a job that passes every guard
        above. A job that is skipped is never stopped, so a check still running
        loses nothing.

        Jobs without the suffix are not looked at and not reported. Returns
        exactly what was removed and what was skipped, and why.
        """
        import shutil

        removed: list[dict] = []
        skipped: list[dict] = []
        scratch = self.scratch_dir.resolve()
        for mate in self._select_all():
            if not mate.title.strip().lower().endswith(self.TEST_JOB_SUFFIX):
                continue
            folder = mate.workdir_path
            why = None
            if mate.status not in TERMINAL_STATUSES:
                why = f"still {mate.status}"
            elif mate.mode == "auto":
                why = "an assistant job"
            elif mate.repo or mate.is_worktree:
                why = "it works in a repository, not a scratch folder"
            elif folder.is_symlink():
                why = "its folder is a link"
            elif folder.exists():
                try:
                    inside = folder.parent.resolve() == scratch and folder.name == mate.id
                except (OSError, ValueError):
                    inside = False
                if not inside:
                    why = "its folder is outside the scratch area"
            # Stop it before forgetting it. A finished Claude Code is still
            # running: it printed its summary, went back to its prompt and sits
            # there on an open pty for ever. Deleting the row without killing
            # the window orphans that process, because every way of stopping one
            # - reconcile, tidy, kill - starts from the database and a forgotten
            # job is in none of them. Twenty-five were found this way on
            # 16 September 2026, holding 7.4 GB, the oldest five days old.
            if why is None:
                target = await self._resolve_target(mate)
                if target is not None:
                    await self.tmux.kill_window(target)
                    LOG.info("stopped the window of test job %s before forgetting it", mate.id)
                await self.close_tmux_dir(mate.id)
            if why is None and folder.is_dir():
                try:
                    shutil.rmtree(folder)
                except OSError as exc:
                    why = f"its folder could not be removed: {exc}"
            if why:
                skipped.append({"id": mate.id, "title": mate.title, "why": why})
                continue
            self._delete_rows(mate.id)
            # And out of the run register, or a job forgotten here would stay
            # on the task list and on the orb for ever: the register is what
            # both are answered from now (`rouh/runs.py`).
            with contextlib.suppress(Exception):
                from . import runs

                runs.forget(mate.id)
            removed.append({"id": mate.id, "title": mate.title})
            LOG.info("forgot test job %s (%s)", mate.id, mate.title)
        if removed:
            self._tree_changed()
        return {"removed": removed, "skipped": skipped}

    async def forget(self, id: str) -> bool:
        """Stop a job and take it out of the crew's books for good.

        What a person means by deleting a run: the record goes, from this
        database and from the run register, and the terminal behind it goes
        with it. A job still alive is stopped first, down the same path
        ``archive`` and ``stop_task`` take, because deleting the row without
        killing the window orphans the process - every way of stopping one
        starts from the database, and a forgotten job is in none of them. That
        is how twenty-five of them were found holding 7.4 GB on 16 September
        2026.

        **The checkout is left exactly where it is.** Deleting a record is not
        throwing away work: the worktree, its branch and its commits stay, the
        same promise ``archive`` makes. What is on the list goes; what is on
        the disk is the person's.

        False when there was no such job, which is not an error: two tabs
        pressing the same cross is an ordinary thing to happen.
        """
        mate = self.get(id)
        if mate is None:
            return False
        if mate.alive:
            try:
                await self.kill(id)
            except Exception:
                # The row goes whatever the terminal did. A window that has
                # already gone, or a tmux that will not answer, must not leave
                # the person with the job still on the list.
                LOG.exception("could not stop %s while deleting it", id)
        with contextlib.suppress(Exception):
            await self.close_tmux_dir(mate.id)
        self._delete_rows(mate.id)
        LOG.info("deleted the job %s (%s); its checkout is untouched", mate.id, mate.title)
        self._tree_changed()
        return True

    async def kill(self, id: str, *, remove_worktree: bool = False,
                   delete_branch: bool = False) -> Crewmate:
        """Stop the window. Optionally remove the worktree it was working in.

        The worktree is only ever removed when this manager created it, and only from
        under its own workspace, so a mistaken call cannot delete somebody's checkout.
        """
        mate = self.get(id)
        if mate is None:
            raise UnknownCrewmate(f"no crewmate with id {id!r}")

        target = await self._resolve_target(mate)
        if target:
            await self.tmux.kill_window(target)
            LOG.info("killed window %s for %s", mate.window_name, mate.id)

        # Whatever this crewmate started inside its own tmux world goes with it.
        # Without this a worker that ran tmux leaves a server behind for ever:
        # a detached tmux server has nothing to make it exit.
        await self.close_tmux_dir(mate.id)

        if remove_worktree:
            await self._maybe_remove_workdir(mate, delete_branch=delete_branch)

        self._set_status(mate, "killed")
        self._log_event(mate.id, "killed", "killed", {"removed_worktree": remove_worktree})
        return mate

    async def _maybe_remove_workdir(self, mate: Crewmate, *, delete_branch: bool) -> None:
        workdir = mate.workdir_path
        roots = [self.workspace] + [Path(p.worktrees_dir) for p in self.profiles.values()
                                    if p.worktrees_dir]
        inside = False
        for root in roots:
            try:
                if workdir.resolve().is_relative_to(Path(root).resolve()):
                    inside = True
                    break
            except (OSError, ValueError):
                continue
        if not inside:
            LOG.warning(
                "refusing to remove %s for %s: it is not inside the crew workspace %s",
                workdir, mate.id, self.workspace,
            )
            return

        if mate.is_worktree and mate.repo:
            await self._remove_worktree(Path(mate.repo), workdir,
                                        mate.branch if delete_branch else None,
                                        (mate.meta or {}).get("git_user"))
        else:
            import shutil

            shutil.rmtree(workdir, ignore_errors=True)
            LOG.info("removed scratch dir %s", workdir)

    async def _remove_worktree(self, repo_root: Path, workdir: Path, branch: str | None,
                               user: str | None = None) -> None:
        rc, _, err = await _run(
            self._git_argv(user, "worktree", "remove", "--force", str(workdir)),
            cwd=repo_root, timeout=60.0,
        )
        if rc != 0:
            LOG.warning("could not remove worktree %s: %s", workdir, err.strip())
            return
        LOG.info("removed worktree %s", workdir)
        if branch:
            rc, _, err = await _run(
                self._git_argv(user, "branch", "-D", branch), cwd=repo_root, timeout=30.0
            )
            if rc != 0:
                LOG.warning("could not delete branch %s: %s", branch, err.strip())

    async def _resolve_target(self, mate: Crewmate) -> str | None:
        """Find the live tmux target for a crewmate, matching on the window name.

        The name carries the crewmate id and is unique. The window id is not safe on
        its own, because tmux hands out ids from zero again after the server restarts.
        """
        for window in await self.tmux.list_windows(None):
            if window["session"] == mate.session and window["window_name"] == mate.window_name:
                return window["window_id"] or f"={mate.session}:{mate.window_name}"
        return None

    async def _require_target(self, mate: Crewmate) -> str:
        target = await self._resolve_target(mate)
        if target is None:
            self._set_status(mate, "lost", reason="tmux window is gone")
            raise CrewError(
                f"crewmate {mate.id} is no longer running: its tmux window "
                f"{mate.window_name!r} is gone. Marked lost."
            )
        return target

    # -- the callback ------------------------------------------------------------

    async def handle_event(self, payload: Mapping[str, Any]) -> Crewmate | None:
        """Take one callback from a crewmate's hook and move it along.

        The web layer should merge the query string with the POSTed body and pass the
        result straight in::

            @app.post("/internal/crew-event")
            async def crew_event(request: Request):
                body = await request.json()
                merged = {**dict(request.query_params), **body}
                await crew.handle_event(merged)
                return {"ok": True}

        The id is read from ``crew``, ``crew_id`` or ``id``. If the web layer passes only
        the POSTed body and drops the query string, the crewmate is still found, by
        matching Claude Code's own ``cwd`` field against the worktree it was given. So
        the callback works whether or not the query string survives the trip.

        The kind is read from ``kind`` (which this module puts in the URL) or from
        Claude Code's own ``hook_event_name``. Unknown ids are logged and dropped, never
        raised, because this runs on an HTTP endpoint and must not be turned into a 500
        by a stale worktree that still has an old settings file.
        """
        data = dict(payload or {})
        crew_id = str(data.get("crew") or data.get("crew_id") or data.get("id") or "").strip()
        raw_kind = str(
            data.get("kind") or data.get("hook_event_name") or data.get("event") or ""
        ).strip()
        kind = _normalise_kind(raw_kind)

        mate = self.get(crew_id) if crew_id else None
        if mate is None and data.get("cwd"):
            mate = self.find_by_workdir(str(data["cwd"]))
            if mate is not None:
                LOG.debug("recovered crewmate %s from cwd %s", mate.id, data["cwd"])

        if mate is None:
            LOG.warning(
                "crew event ignored: no crewmate for id=%r cwd=%r (kind=%s)",
                crew_id or None, data.get("cwd"), kind,
            )
            return None
        crew_id = mate.id

        if kind in TELEMETRY_KINDS:
            # What the worker is doing, not what became of it. These arrive a
            # few a second from a busy worker, so they go straight to the tree's
            # own table and, but for one moment, touch nothing else: no status
            # change, no entry in the event log a person reads, and no listener
            # woken. The web layer returns immediately without reading anybody's
            # screen.
            self.record_tree_event(crew_id, kind, data)
            # The one moment: the first tool call of a job still "starting".
            # No hook says a job has begun, and one launched with its prompt
            # never goes through send(), so it read "starting" from launch to
            # finish (job 78d4e65c, 13 September 2026: 151 tool hooks in thirty
            # minutes). The change goes the way every status change goes, so
            # the orb and the task list hear of it at once. A job waiting for a
            # person, or already ended, is never moved: see _status_for_event.
            new_status = _status_for_event(kind, mate.status, data)
            if new_status and new_status != mate.status:
                self._log_event(crew_id, kind, new_status, data)
                self._set_status(mate, new_status, last_event=kind)
                LOG.info("crewmate %s -> %s (%s)", crew_id, new_status, kind)
                await self._notify(mate, kind, data)
            return mate

        new_status = _status_for_event(kind, mate.status, data)
        self._log_event(crew_id, kind, new_status or mate.status, data)
        # The three lifecycle hooks shape the tree as well: a notification means
        # a person is being asked, and a stop means nothing under that worker can
        # still be running.
        if kind in TREE_KINDS:
            self.record_tree_event(crew_id, kind, data)

        if new_status and new_status != mate.status:
            self._set_status(mate, new_status, last_event=kind,
                             because=_session_ended(data) if new_status == "lost" else "")
            LOG.info("crewmate %s -> %s (%s)", crew_id, new_status, kind)
        elif new_status is None and not mate.alive:
            # Late news about a job that has already ended, which changes
            # nothing about it: Claude Code's "waiting for your input" about a
            # minute after a job finishes, and its SessionEnd about a second
            # after one is stopped. It is in the event log above and goes no
            # further. Touching the row would move `updated_at`, which the tree
            # reads as the moment the job ended: a finished job's spike came
            # back on the orb a minute later, and its card said it had taken a
            # minute longer than it did.
            pass
        else:
            self._update(mate, last_event=kind, updated_at=clock.utc_iso(timespec="seconds"))
            mate.last_event = kind

        await self._notify(mate, kind, data)
        return mate

    async def _notify(self, mate: Crewmate, kind: str, payload: Mapping[str, Any]) -> None:
        for listener in list(self._listeners):
            try:
                result = listener(mate, kind, payload)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:  # pragma: no cover - a listener must not break the callback
                LOG.exception("crew listener failed for %s (%s)", mate.id, kind)

    # -- persistence -------------------------------------------------------------

    def _insert(self, mate: Crewmate) -> None:
        from .models import Crewmate as Row

        row = mate.as_dict()
        row["is_worktree"] = bool(mate.is_worktree)
        row["archived"] = bool(mate.archived)
        row["meta"] = json.dumps(mate.meta)
        with self._db_lock:
            Row.objects.create(**row)
        self._register(mate)
        self._tree_changed()

    def _update(self, mate: Crewmate, **fields: Any) -> None:
        from .models import Crewmate as Row

        if not fields:
            return
        fields.setdefault("updated_at", clock.utc_iso(timespec="seconds"))
        with self._db_lock:
            Row.objects.filter(id=mate.id).update(**fields)
        for key, value in fields.items():
            if key == "meta" and isinstance(value, str):
                # Written as JSON and read as a dict everywhere else, including
                # by the register right below.
                value = json.loads(value or "{}")
            if hasattr(mate, key):
                setattr(mate, key, value)
        self._register(mate)
        self._tree_changed()

    def register_all(self) -> int:
        """Put every worker on record into the run register. Returns how many.

        Run once at start-up. The register is what the task list, `check_tasks`
        and the orb are answered from now, and it is written when a `crewmates`
        row changes - so without this, the first Rouh to come up with the
        object model on would show an empty list until every job happened to
        change. A job that has been sitting finished for a week never changes
        again, and it would have vanished for good.
        """
        try:
            from . import runs

            mates = self._select_all()
            for mate in mates:
                runs.crew_run(mate)
            return len(mates)
        except Exception:
            LOG.exception("could not put the workers on record into the run register")
            return 0

    def _register(self, mate: Crewmate) -> None:
        """Write this worker into the run register, which is one kind of thing now.

        Both writes of a `crewmates` row come through here, so the register
        cannot fall behind this table: a background worker, a run of the one
        program and a sub-agent inside either are all one row in `run`, and
        that row is what the task list, `check_tasks`, the orb and
        `what_is_running` are answered from (`rouh/runs.py`). With the object
        model turned off this does nothing at all, and nothing else answers
        instead: the second way went in step five.

        Imported here rather than at the top: `runs.py` reads the
        configuration and opens a database, and this module is imported by
        things that want neither.
        """
        try:
            from . import runs

            runs.crew_run(mate)
        except Exception:  # the register must never be the reason a job fails
            LOG.exception("could not write crewmate %s to the run register", mate.id)

    def _set_status(self, mate: Crewmate, status: str, *, exit_code: int | None = None,
                    reason: str | None = None, last_event: str | None = None,
                    clear_finished: bool = False, screen: str = "",
                    because: str = "") -> None:
        if status not in STATUSES:
            raise ValueError(f"unknown status {status!r}")
        fields: dict[str, Any] = {"status": status, "updated_at": clock.utc_iso(timespec="seconds")}
        if status in TERMINAL_STATUSES and not clear_finished:
            fields["finished_at"] = clock.utc_iso(timespec="seconds")
        if clear_finished:
            fields["finished_at"] = None
        if status == "lost" and mate.status != "lost":
            # Why it died, read now, while its log and its record are there to
            # read, and kept on the row: every path that finds a job dead comes
            # through here, so none of them can leave a death without a reason.
            try:
                death = self.death_of(mate, exit_code=exit_code, screen=screen,
                                      because=because)
            except Exception:  # a death with no reason is still a death
                LOG.exception("could not read why %s died", mate.id)
                death = {"at_launch": False, "exit_code": exit_code, "said": "", "line": "",
                         "lived": None}
            fields["meta"] = json.dumps({**(mate.meta or {}), "death": death})
            if exit_code is None:
                exit_code = death["exit_code"]
            LOG.info("crewmate %s died: %s", mate.id, death["line"] or "without a report")
        if exit_code is not None:
            fields["exit_code"] = exit_code
        if last_event is not None:
            fields["last_event"] = last_event
        ending = status in TERMINAL_STATUSES and mate.status not in TERMINAL_STATUSES
        self._update(mate, **fields)
        if status in TERMINAL_STATUSES and (mate.meta or {}).get("boxes"):
            # Done, failed, lost or killed: the boxes it was handed go now.
            self._shred_boxes(mate)
        if reason:
            LOG.info("crewmate %s -> %s (%s)", mate.id, status, reason)
        if ending:
            # How long it ran and how it ended (`rouh/events.py`), once, as it ends.
            from . import events

            began = clock.epoch(mate.created_at, zulu=False)
            events.emit("job.finished", actor=events.started_by(mate.id, "rouh"),
                        source="server", object_type="job", object_id=mate.id, owner=True,
                        duration_ms=(time.time() - began) * 1000 if began else None,
                        props={"outcome": status, "exit_code": exit_code})

    def _shred_boxes(self, mate: Crewmate) -> None:
        """Scrub a job's log of what its boxes held, shred them, and say so. Never raises."""
        from . import boxes

        try:
            folder = mate.workdir or ""
            if folder and os.path.isdir(os.path.join(folder, boxes.SECRETS_DIR)):
                n = boxes.shred_folder(folder, [str(p) for p in self._log_paths(mate)])
                LOG.info("crewmate %s: %d box file(s) shredded", mate.id, n)
            boxes.ended(mate.id)
        except Exception:  # noqa: BLE001 - tried again as Rouh starts
            LOG.exception("crewmate %s: its boxes could not be shredded", mate.id)

    def _log_event(self, crew_id: str, kind: str, status: str | None,
                   payload: Mapping[str, Any]) -> None:
        from .models import CrewEvent

        with self._db_lock:
            CrewEvent.objects.create(crew_id=crew_id, kind=kind, at=clock.utc_iso(timespec="seconds"), status=status,
                                     payload=json.dumps(_scrub(payload)))

    def _delete_rows(self, crew_id: str) -> None:
        """Every row this crew keeps about one job, gone in one transaction."""
        from django.db import transaction

        from .models import Crewmate as Row
        from .models import CrewEvent, CrewTreeEvent

        with self._db_lock, transaction.atomic():
            CrewTreeEvent.objects.filter(crew_id=crew_id).delete()
            CrewEvent.objects.filter(crew_id=crew_id).delete()
            Row.objects.filter(id=crew_id).delete()


# --------------------------------------------------------------------------------------
# Event mapping
# --------------------------------------------------------------------------------------

_KIND_ALIASES = {
    "stop": "stop",
    "notification": "notification",
    "sessionend": "session_end",
    "session_end": "session_end",
    "sessionstart": "session_start",
    "session_start": "session_start",
    "subagentstop": "subagent_stop",
    "subagent_stop": "subagent_stop",
    "subagentstart": "subagent_start",
    "subagent_start": "subagent_start",
    "pretooluse": "pre_tool_use",
    "pre_tool_use": "pre_tool_use",
    "posttooluse": "post_tool_use",
    "post_tool_use": "post_tool_use",
    "stopfailure": "failed",
    "failed": "failed",
    "error": "failed",
    "started": "started",
    "running": "started",
}


def _normalise_kind(raw: str) -> str:
    return _KIND_ALIASES.get(raw.strip().lower(), raw.strip().lower() or "unknown")


#: The hooks that describe what a worker is doing rather than what became of it.
#: They arrive several a second from a busy worker and change its status only
#: once: the first tool call of a job still "starting" moves it to "running".
TELEMETRY_KINDS = frozenset({
    "pre_tool_use", "post_tool_use", "subagent_start", "subagent_stop",
})

#: The telemetry hooks that are a tool call opening or closing, the ones that
#: show a job has begun.
TOOL_KINDS = frozenset({"pre_tool_use", "post_tool_use"})

#: Everything the work tree is built from. The three lifecycle hooks are in here
#: as well because they close nodes: a stop ends every tool call under it.
TREE_KINDS = TELEMETRY_KINDS | {"stop", "session_end", "notification"}


def normalise_kind(raw: str) -> str:
    """The one spelling of an event name. ``PreToolUse`` and ``pre_tool_use`` agree.

    Public because the web layer has to know whether an incoming hook is
    telemetry before it decides how much work to do about it.
    """
    return _normalise_kind(raw)


def is_late_news(kind: str, status: str, payload: Mapping[str, Any] | None = None) -> bool:
    """True for news about a job that has ended which changes nothing about it.

    Claude Code goes on sending hooks after a job ends: "waiting for your input"
    about a minute after it finishes, SessionEnd about a second after it is
    stopped. handle_event leaves such a job's row alone. Public because the web
    layer must leave open pages alone too: telling them read the ended job's
    screen and sent its last line as the job's line.
    """
    return status in TERMINAL_STATUSES and _status_for_event(kind, status, payload) is None


def _is_idle_notification(payload: Mapping[str, Any] | None) -> bool:
    """What a notification says when nobody is actually needed.

    Claude Code fires its notification hook for two unrelated things, and
    reading them as one thing is what put finished jobs under "needs you" for
    ever. A permission prompt genuinely blocks: the worker cannot continue
    until somebody answers. Going idle at the prompt does not block anything -
    it is what every worker does about a minute after it finishes.

    One definition, in `rouh/tree.py`, because the work tree has to tell the
    two apart as well: a worker that is only idle must not be drawn red and
    dashed with NEEDS YOU against it either.
    """
    from .tree import is_idle_notification

    return is_idle_notification(payload)


def _status_for_event(kind: str, current: str,
                      payload: Mapping[str, Any] | None = None) -> str | None:
    """What a callback means for the record. None means "log it, change nothing"."""
    if kind == "stop":
        # Claude Code finished a turn. It is still alive and can be sent more work.
        return "done"
    if kind == "notification":
        if _is_idle_notification(payload):
            # It is sitting at its prompt with nothing to do. If it already said
            # it had finished, it has finished - do not un-finish it. If it never
            # did, then it is idle without having reported anything, and that is
            # worth a person looking at.
            return None if current in TERMINAL_STATUSES else "waiting"
        # A permission prompt. It cannot go on until somebody answers.
        return "waiting"
    if kind == "failed":
        return "failed"
    if kind == "started":
        return "running"
    if kind in TOOL_KINDS:
        # A tool call opening or closing is the first sure sign a job has begun,
        # so it moves a job that is still "starting", and nothing else. A job
        # "waiting" still needs its person: a tool run side by side can report
        # finishing after another stopped to ask. And news about an ended job
        # never touches it: a sub-agent can go on calling tools after the Stop.
        return "running" if current == "starting" else None
    if kind == "session_end":
        # If it already reported finishing, that verdict stands. Otherwise the session
        # ended without ever telling us how it went, which is exactly "lost".
        return None if current in TERMINAL_STATUSES else "lost"
    return None


#: Why Claude Code says a session ended (the `reason` of its SessionEnd hook),
#: as the reason a job that never said it had finished died of.
_SESSION_ENDED = {
    "clear": "its conversation was cleared before it said it had finished",
    "logout": "Claude Code was logged out before it said it had finished",
    "prompt_input_exit": "somebody typed exit at its prompt before it said it had finished",
    "other": "its terminal was closed before it said it had finished",
}


def _session_ended(payload: Mapping[str, Any]) -> str:
    """The words for a SessionEnd that came before any Stop, or "" for none."""
    if _normalise_kind(str(payload.get("kind") or payload.get("hook_event_name") or "")) \
            != "session_end":
        return ""
    reason = str(payload.get("reason") or "").strip()
    return _SESSION_ENDED.get(reason, f"Claude Code ended its session ({reason})"
                              if reason else "Claude Code ended its session")


_SENSITIVE = re.compile(r"(token|secret|password|api[_-]?key|authorization)", re.I)


def _scrub(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Keep obvious credentials out of the event log."""
    out: dict[str, Any] = {}
    for key, value in payload.items():
        if _SENSITIVE.search(str(key)):
            out[key] = "[redacted]"
        elif isinstance(value, str) and len(value) > 4000:
            out[key] = value[:4000] + f"... [{len(value) - 4000} more chars]"
        elif isinstance(value, Mapping):
            out[key] = _scrub(value)
        else:
            out[key] = value
    return out


#: How much of one hook payload is kept. A PostToolUse for a Read of a large
#: file carries the whole file in `tool_response`, and storing that for every
#: tool call would put megabytes a minute on disk for data nothing reads. The
#: fields the tree is built from are tiny and are always kept.
_TREE_PAYLOAD_LIMIT = 4000
_TREE_KEEP_KEYS = (
    "hook_event_name", "tool_name", "tool_use_id", "agent_id", "agent_type",
    "duration_ms", "effort", "permission_mode", "cwd", "session_id", "reason",
)
#: In a trimmed payload, each text in the tool's input is cut to this many
#: characters, and the whole input to about this many.
_TREE_INPUT_TEXT = 300
_TREE_INPUT_BUDGET = 1500


def _small_input(tool_input: Mapping[str, Any]) -> dict[str, Any]:
    """A tool's input with every text cut short, for a payload too big to keep.

    The orb says what a step was from its input - the file a Write wrote, the
    task a helper was given - and a big payload used to lose the input whole,
    so a Write of a long file, or a helper with a long prompt, said nothing.
    """
    out: dict[str, Any] = {}
    used = 0
    for key, value in tool_input.items():
        if isinstance(value, str):
            value = value[:_TREE_INPUT_TEXT]
        elif not (value is None or isinstance(value, (bool, int, float))):
            continue
        used += len(str(key)) + len(str(value))
        if used > _TREE_INPUT_BUDGET:
            break
        out[key] = value
    return out


def _trim_for_tree(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Keep the whole payload when it is small, and its skeleton when it is not."""
    data = dict(payload)
    if len(json.dumps(data, default=str)) <= _TREE_PAYLOAD_LIMIT:
        return data
    kept = {key: data[key] for key in _TREE_KEEP_KEYS if key in data}
    tool_input = data.get("tool_input")
    if isinstance(tool_input, Mapping):
        kept["tool_input"] = _small_input(tool_input)
    response = data.get("tool_response")
    if isinstance(response, Mapping):
        kept["tool_response"] = {
            key: response[key]
            for key in ("status", "is_error", "isError", "interrupted", "agentId",
                        "agentType", "totalDurationMs")
            if key in response
        }
    kept["_trimmed"] = True
    return kept


# --------------------------------------------------------------------------------------
# Logging
# --------------------------------------------------------------------------------------


def _ensure_stdout_logging(level: int = logging.INFO) -> None:
    """Send this module's log to stdout, once, without touching the root logger."""
    if any(getattr(h, "_rouh_crew", False) for h in LOG.handlers):
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-7s rouh.crew %(message)s",
                          datefmt="%H:%M:%S")
    )
    handler._rouh_crew = True  # type: ignore[attr-defined]
    LOG.addHandler(handler)
    LOG.setLevel(level)
    LOG.propagate = False


def describe_modes() -> str:
    """One line per mode, for a help command or a spoken answer."""
    return "\n".join(f"{spec.name}: {spec.summary}" for spec in MODES.values())


if __name__ == "__main__":  # pragma: no cover - a hand check, not part of the suite
    async def _main() -> None:
        manager = CrewManager()
        mates = await manager.status()
        assert isinstance(mates, list)
        print(f"{len(mates)} crewmate(s) on record")
        for mate in mates:
            print(f"  {mate.id}  {mate.status:<8} {mate.mode:<11} {mate.title}")
        print()
        print(describe_modes())
        await manager.aclose()

    asyncio.run(_main())
