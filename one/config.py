"""Every setting the program reads, in one place, with the reason next to it.

All of them come from the environment, so the same code runs on the laptop for
tests and on the server for real. The server's values are in the service file,
``one/deploy/one.service``. No secret is read here: the phone's Telegram key
is read from its own file by ``phone.py`` when a message is sent.
"""
from __future__ import annotations

import contextlib
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def this_machine() -> str:
    """The address another machine reaches this one at.

    Asked of the routing table, by opening a UDP socket towards a public
    address and reading back which of this machine's addresses it would leave
    from. Nothing is sent: a UDP socket that is connected has still spoken to
    nobody.
    """
    import socket
    with contextlib.suppress(OSError):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("198.51.100.1", 9))  # TEST-NET-2: routed, never answered
            return probe.getsockname()[0]
    with contextlib.suppress(OSError):
        return socket.gethostbyname(socket.gethostname())
    return "127.0.0.1"


def _access() -> str:
    # An unknown word is taken as the careful one, never the open one.
    raw = _env("ONE_ACCESS", "full").lower()
    return raw if raw in ("full", "guarded") else "guarded"


def _num(name: str, default: float) -> float:
    raw = _env(name)
    try:
        return float(raw) if raw else default
    except ValueError:
        return default


def _size(name: str, default: int) -> int:
    """A number of bytes, written plainly or with K, M or G after it: 4294967296 or 4G."""
    raw = _env(name).strip().upper().removesuffix("B")
    scale = {"K": 1 << 10, "M": 1 << 20, "G": 1 << 30}.get(raw[-1:], 1)
    try:
        return int(float(raw[:-1] if scale > 1 else raw) * scale) if raw else default
    except ValueError:
        return default


@dataclass(frozen=True)
class Space:
    """Where a run works: the assistant, one repository, or a folder of its own (D42)."""

    name: str
    #: The Linux user it works as. Blank means the program's own user, which
    #: is only right on the laptop, for tests.
    user: str
    #: The repository its checkout is made from; None means a folder of its own.
    repo: str | None
    #: Where its checkout or folder is made.
    folders: str
    #: The folder every path it is given must be inside, owned by its user.
    runs: str
    #: The branch its checkout starts from and its work is saved to. "auto" is
    #: worked out from the repository when the checkout is made: its
    #: development branch if it has one, otherwise its main branch.
    target: str
    #: Whether `repo` itself is brought up to main after a landing: only the
    #: assistant's copy, which everything on the server reads.
    follow: bool
    #: Whether changes left uncommitted are committed when its work lands:
    #: only the assistant's notes. In a code repository a change whose tests
    #: failed is left uncommitted on purpose, and must not reach main.
    leftovers: bool
    #: A folder already on the server, added as it is: a run works in it
    #: directly, like a terminal, and nothing is saved for it (D43).
    in_place: bool = False


#: What a run started under another name was working in, and the space that is
#: now. "workspace" and "server" are from before D42; "jarvis" is from before
#: 22 September 2026, when `/srv/spaces/jarvis` became `/srv/spaces/rouh` with
#: the rest of the rename. Every one of them is still on runs in the list and
#: in the events of runs that have finished, so every one of them still
#: resolves. RENAME.md says which other names moved.
OLD_NAMES = {"workspace": "assistant", "server": "assistant", "jarvis": "rouh"}


@dataclass
class Settings:
    # --- Where things are ----------------------------------------------------
    #: The list, the runs' own folders and the views' saved position.
    data: Path = field(default_factory=lambda: Path(_env("ONE_DATA", "/var/lib/one")))
    #: The socket the terminal, Rouh and the program's own tools talk to.
    socket: str = field(default_factory=lambda: _env("ONE_SOCKET", "/run/one/one.sock"))
    #: The browser, the phone's answer links and the runs' hooks come in here.
    #: Only on this machine: nginx is what faces the internet.
    http_host: str = field(default_factory=lambda: _env("ONE_HTTP_HOST", "127.0.0.1"))
    http_port: int = field(default_factory=lambda: int(_num("ONE_HTTP_PORT", 8031)))
    #: The path the program is served under, behind nginx.
    base_path: str = field(default_factory=lambda: _env("ONE_BASE_PATH", "/one").rstrip("/"))
    #: The address a phone opens, for the links in its messages, such as
    #: https://rouh.example.com/one. The installation's own, set per machine;
    #: blank writes links without a host.
    public_url: str = field(
        default_factory=lambda: _env("ONE_PUBLIC_URL").rstrip("/"))
    #: Every name the program is opened under from outside, comma separated
    #: (two side by side since 4 October 2026, task 86). The public URL above
    #: is the one links are written with. The installation's own, set per
    #: machine; blank allows only the public URL's own name.
    public_hosts: str = field(
        default_factory=lambda: _env("ONE_PUBLIC_HOSTS"))
    #: Who another machine's ssh reaches this one as, for the command a page
    #: offers for taking a run over in a real terminal. Blank works it out
    #: from the route this machine takes to the internet, as root, which is
    #: one of the two accounts that may open the socket. The name the page is
    #: served under is no use here: it is usually a proxy's address (Cloudflare's),
    #: not this machine's.
    ssh_target: str = field(default_factory=lambda: _env("ONE_SSH_TARGET"))
    #: Rouh on this machine, which every run's agent instructions are read
    #: from as it starts (`agents.fetch_instructions`, Rouh's
    #: `/internal/agent-instructions`). Only this machine may ask that
    #: address. Blank asks nothing, and a run starts without them: a world
    #: with no Rouh in it.
    rouh_url: str = field(
        default_factory=lambda: _env("ONE_ROUH_URL", "http://127.0.0.1:8021").rstrip("/"))

    # --- Who a run works as, and where ----------------------------------------
    #: The Linux user every run works as. Blank means the program's own user,
    #: which is only right on the laptop, for tests.
    run_as: str = field(default_factory=lambda: _env("ONE_RUN_AS", "assistant"))
    sudo: str = field(default_factory=lambda: _env("ONE_SUDO", "/usr/bin/sudo"))
    #: The Python that runs asuser.py as that user. The system's own, not the
    #: program's environment, so the sudo rule names a program root owns.
    asuser_python: str = field(default_factory=lambda: _env("ONE_ASUSER_PYTHON", "/usr/bin/python3"))
    #: The person's workspace that a run works in when it names no space: a
    #: checkout of the workspace's own repository, which runs are worktrees of.
    #:
    #: It was a repository of its own, `/srv/assistant`, until 21 September
    #: 2026, then `workspace/` inside the `rouh` checkout until 21 October
    #: 2026, when it became a repository of its own again, so that Rouh's code
    #: holds none of the person's life. A run lands it through `land.sh` like
    #: any other repository; `land.sh` sees the workspace's map at the top and
    #: moves the live workspace instead of deploying. A checkout that still
    #: holds the workspace as `workspace/` works as it did, and the run's
    #: brief says which of the two it is in (`agents.workspace_layout`).
    workspace: str = field(
        default_factory=lambda: _env("ONE_WORKSPACE")
        or str(Path(_env("ONE_SPACES_DIR", "/srv/spaces")) / "workspace"))
    #: Where each run's own checkout is made. Owned by the run's user.
    runs_dir: str = field(default_factory=lambda: _env("ONE_RUNS_DIR", "/srv/one-runs"))
    #: Where the program's own scratch runs work, when a run is not in a repository.
    scratch_dir: str = field(default_factory=lambda: _env("ONE_SCRATCH_DIR", "/srv/one-runs/scratch"))
    claude: str = field(default_factory=lambda: _env("ONE_CLAUDE", "/usr/bin/claude"))
    #: Where `land.sh` keeps its lock and writes its conflict records. Blank is
    #: land.sh's own, the server's /srv/rouh-land. Passed to it on every landing,
    #: because a landing runs under sudo with a clean environment: a test world
    #: that only set ROUH_LAND_DIR for itself used to land into the server's
    #: directory anyway, and on 18 October 2026 six of its records reached Petar
    #: as real decisions.
    land_dir: str = field(
        default_factory=lambda: _env("ROUH_LAND_DIR") or _env("JARVIS_LAND_DIR"))
    #: The same model a page asked for in the terminal is made with.
    #:
    #: Opus 5.5 since 23 September 2026, asked for by Petar by voice: "make
    #: sure all new claude code sessions start with default model opus 5.5".
    #: The terminal's own default is the `model` line in each account's
    #: `~/.claude/settings.json`, and a run names the model on the command
    #: line rather than inheriting it, so the two are only ever the same model
    #: because this line says so. It moves when that one does.
    model: str = field(default_factory=lambda: _env("ONE_MODEL", "claude-opus-5-5"))
    #: How hard a run thinks, as `claude --effort`. A run is a background
    #: worker: nobody is sitting with their mouth open waiting for it, so it is
    #: worth the thinking. Rouh's own jobs - delegate_task, assistant jobs
    #: and improve_myself - are runs of this program since D42, so this is
    #: where their effort is decided. Blank leaves the flag off and Claude Code
    #: picks, which is what happened until 19 September 2026.
    #:
    #: Only for a run whose request did not say. Since 27 September 2026 Rouh
    #: says, for every run it starts: the model and the level are its
    #: organisation's defaults in Settings (`rouh/modeldefaults.py`). So this
    #: and `model` above are what a run started from a terminal or from this
    #: program's own page gets: Opus 5.5 at medium, what Petar asked for "for
    #: all runs" that day, and xhigh until then.
    effort: str = field(default_factory=lambda: _env("ONE_EFFORT", "medium"))
    #: Codex, OpenAI's command-line agent, for a run the person asks for by
    #: name. Claude Code stays what a run is unless Codex is asked for.
    #: Install it with `npm install -g @openai/codex`; a run of it fails,
    #: saying so, on a machine where it is not there.
    codex: str = field(default_factory=lambda: _env("ONE_CODEX", "/usr/bin/codex"))
    #: Which model a Codex run uses. Empty means Codex's own default, which is
    #: the right answer until the person says otherwise: a model name guessed
    #: here would be wrong the week OpenAI renames one.
    codex_model: str = field(default_factory=lambda: _env("ONE_CODEX_MODEL"))
    #: How hard a Codex run thinks. The same decision as `effort` above, one
    #: agent along: a run is a background worker, so it is given the thinking
    #: rather than the speed. Codex has no flag for it, so it travels as the
    #: config override `-c model_reasoning_effort=`; `agents.codex_args` says
    #: what that survives. Blank leaves it off and Codex picks, which is what
    #: happened until 19 September 2026, when every Codex run - including
    #: Rouh's own delegate_task and assistant jobs asked for with
    #: `agent="codex"` - took Codex's own default while the Claude Code runs
    #: beside them thought at xhigh.
    codex_effort: str = field(default_factory=lambda: _env("ONE_CODEX_EFFORT", "xhigh"))
    #: How long a Codex run has to prove its hooks are live, by sending
    #: SessionStart, before the program stops it. Codex runs with its hooks
    #: silently off when it has not been told to trust them, and a run with no
    #: hooks is a run with none of the program's rules, so it is not left
    #: going. Claude Code needs none of this: its hooks cannot be switched off
    #: by anything but the settings file the program writes itself.
    codex_handshake: float = field(default_factory=lambda: _num("ONE_CODEX_HANDSHAKE", 60))
    #: Where the OpenAI API is, for a run of Codex billed to the API key
    #: (`billing.py`). Only a test world changes it, to a stand-in that spends
    #: nothing. The key itself is not a setting and is not read here.
    codex_api_base_url: str = field(
        default_factory=lambda: _env("ONE_CODEX_API_BASE_URL", "https://api.openai.com/v1"))
    #: Which branch a run's work lands on.
    target: str = field(default_factory=lambda: _env("ONE_TARGET", "main"))
    #: Have each run of Claude Code write its own debug log, in its checkout's
    #: .one folder, which git never sees. For finding out why a run did
    #: something; off unless asked for.
    claude_debug: bool = field(
        default_factory=lambda: _env("ONE_CLAUDE_DEBUG").lower() in ("1", "true", "yes", "on"))

    # --- Spaces (D42) ------------------------------------------------------------------
    #: Every repository a run can work in besides the assistant's own workspace,
    #: one clone each, named by its folder, owned by the run's user. Added with
    #: `one space add`; Rouh's own code is the space "rouh".
    spaces_dir: str = field(default_factory=lambda: _env("ONE_SPACES_DIR", "/srv/spaces"))
    #: Where a folder added by its project's name is made, if it is not there
    #: yet (D44). On a server it is set with ONE_FOLDERS_DIR, no longer the same path
    #: as the person's projects on their Mac.
    folders_dir: str = field(default_factory=lambda: _env("ONE_FOLDERS_DIR", "/srv/folders"))

    # --- What a run may do -----------------------------------------------------------
    #: "full": a run may do anything its user can, and nobody is asked. The
    #: person's decision on 14 September (D8). Every call is still written
    #: down, marked with what the guarded rules would have done.
    #: "guarded": the rules in rules.py refuse some calls and ask about others.
    access: str = field(default_factory=_access)

    # --- The scheduler ------------------------------------------------------------
    #: Runs of Claude Code at once. More wait, visibly, until one ends.
    #: The live number is set by ONE_MAX_RUNS in the service's drop-in,
    #: /etc/systemd/system/one.service.d/limits.conf, which is the one place
    #: it is decided. This 4 is only the fallback for a machine with no
    #: drop-in; do not tune it by hand.
    max_runs: int = field(default_factory=lambda: int(_num("ONE_MAX_RUNS", 4)))
    #: New runs wait while the program's processes use more than this share of
    #: the processor they are allowed (the service's CPUQuota).
    cpu_budget: float = field(default_factory=lambda: _num("ONE_CPU_BUDGET", 0.9))
    #: Where the processor and memory gates read what the service is using.
    #: Blank works it out from this process's own cgroup, which is right on the
    #: server. A folder with no cpu.stat in it - anything at all, which is what
    #: a throwaway world in a test gives - is no cgroup, and both gates are
    #: off: a test program's two runs are not what the whole machine's limits
    #: are about, and reading them made every test that starts a run depend on
    #: how busy the machine happened to be. In a container, blank is the
    #: container's own cgroup, read-only there: both gates then keep to the
    #: worker's own limits (mem_limit and cpus in the stack file).
    cgroup: str = field(default_factory=lambda: _env("ONE_CGROUP"))
    #: A run of Claude Code that finished its work and sits at its prompt with
    #: nobody attached is closed after this long; 0 is never. Never since the
    #: person's decision of 15 September (D49): every run stays open until they
    #: close it, and only memory running short closes one (Scheduler.make_room).
    idle_close: float = field(default_factory=lambda: _num("ONE_IDLE_CLOSE", 0))
    #: A run that dies badly is started again this many times, then a person is told.
    restarts: int = field(default_factory=lambda: int(_num("ONE_RESTARTS", 2)))
    #: A run whose process went down with the program - a deploy restarts the
    #: worker container, and every run in it - is carried on this many times.
    #: Not the run's fault, so not one of its ``restarts``; the limit is only
    #: there so that nothing can start one again for ever.
    carry_ons: int = field(default_factory=lambda: int(_num("ONE_CARRY_ONS", 30)))
    #: How often, in seconds, the server's copy of the workspace is brought up
    #: to main when no run has landed; 0 switches that off.
    follow_every: float = field(default_factory=lambda: _num("ONE_FOLLOW_EVERY", 60))

    # --- Garbage collection for runs (scheduler.py) -------------------------------
    #: How long a run may go with nothing happening in it, in seconds, before
    #: it is cleaned up. Counted from the last thing that happened in the run
    #: (``last_at``: a tool call opened or closed, its own or a sub-agent's, a
    #: turn ended or woken, a message to it), never from when it started, so a
    #: run that is working is never stopped however long it works. Past it the
    #: run is stopped, which empties its cgroup and with it every process and
    #: browser it started, and it ends ``reaped``: "Cleaned up" on every
    #: screen, not a success and not a crash. 0 is never. Six hours, at
    #: Petar's word on 5 October 2026 (fr_61710d502d1c), counted from the last
    #: activity since his word on 30 October 2026: "the 6h limit should be
    #: after the run has completed and has not been moving ... not 6h after
    #: the run has started".
    run_lifetime: float = field(default_factory=lambda: _num("ONE_RUN_LIFETIME", 6 * 3600))
    #: How long a run may sit paused - its turn over, waiting on a sub-agent,
    #: a background command, a monitor or a wake-up it scheduled - with
    #: nothing at all in the list, before the program calls that turn over
    #: and saves and reports it (`Runs.end_stale_pause`). Seventy-five
    #: minutes: past the hour a ScheduleWakeup can be set for, and long
    #: enough for a sub-agent, whose own tool calls count as something. 0 is
    #: never, which leaves only ``run_lifetime``.
    pause_silence: float = field(default_factory=lambda: _num("ONE_PAUSE_SILENCE", 75 * 60))
    #: How long a run that has finished its turn well stays open at its prompt
    #: before it is closed and archived, in seconds, so a follow-up said right
    #: after its report still reaches the live session. A run that has ended
    #: done is archived at once. A negative number switches archiving off.
    archive_after: float = field(default_factory=lambda: _num("ONE_ARCHIVE_AFTER", 600))

    # --- The reaper ---------------------------------------------------------------
    #: How often, in seconds, what runs leave behind is swept up (reaper.py);
    #: 0 switches the sweeping off and leaves the picture readable.
    reap_every: float = field(default_factory=lambda: _num("ONE_REAP_EVERY", 300))
    #: How long a process may be orphaned and outside every run's box before it
    #: is stopped. Nothing a live run owns is ever both of those, however long
    #: the run lasts: everything a run starts is born inside that run's cgroup,
    #: and a process is handed to init only once whoever started it has gone.
    #: So this is not a limit on how long work may take, and no amount of
    #: sitting at a prompt brings a run near it.
    #:
    #: Four hours, at Petar's word on 22 September 2026, raised from the one
    #: hour it shipped with that morning. The only thing a longer ceiling costs
    #: is memory held by something already dead for that much longer; what a
    #: shorter one risks is a process that is somebody's being taken for
    #: nobody's, and that is the expensive way to be wrong.
    stray_after: float = field(default_factory=lambda: _num("ONE_STRAY_AFTER", 4 * 3600))
    #: How long a leftover world may sit in the scratch filesystem with nothing
    #: holding it open before it is deleted.
    scratch_after: float = field(default_factory=lambda: _num("ONE_SCRATCH_AFTER", 6 * 3600))
    #: Where the harness and the tools a run proves its work with put their
    #: temporary worlds. On this server it is a tmpfs, so what is left there is
    #: memory and not disk, which is why it is swept at all.
    scratch_tmp: str = field(default_factory=lambda: _env("ONE_SCRATCH_TMP", "/tmp"))
    #: The most memory one run may hold, in bytes (or 4G), written onto its own
    #: cgroup so the kernel enforces it. 0 is no limit. A run that goes past it
    #: is pushed back by reclaim first and killed inside its own box if it will
    #: not come down, which is the whole point: the run that leaks dies, and
    #: not the program, nor the run next to it. Where no box can be made - the
    #: containers - its holder reads what the run holds and ends it over this
    #: instead (holder.Holder._watch).
    run_memory_max: int = field(default_factory=lambda: _size("ONE_RUN_MEMORY_MAX", 4 << 30))

    # --- Questions and the phone ------------------------------------------------
    #: Claude Code waits at most ten minutes for a hook. A question is closed
    #: as "no" a minute before that, so the answer always reaches the run.
    question_timeout: float = field(default_factory=lambda: _num("ONE_QUESTION_TIMEOUT", 540))
    hook_timeout: int = field(default_factory=lambda: int(_num("ONE_HOOK_TIMEOUT", 600)))
    #: How long a question waits before the phone is told, when nobody is watching.
    phone_after: float = field(default_factory=lambda: _num("ONE_PHONE_AFTER", 20))
    telegram: str = field(default_factory=lambda: _env("ONE_TELEGRAM", "/etc/one/telegram.json"))

    # --- Terminals --------------------------------------------------------------
    cols: int = field(default_factory=lambda: int(_num("ONE_COLS", 120)))
    rows: int = field(default_factory=lambda: int(_num("ONE_ROWS", 40)))
    #: The Python that runs the holders: the program's own.
    python: str = field(default_factory=lambda: _env("ONE_PYTHON", sys.executable))

    def space(self, name: str | None) -> Space:
        """Where a run in that space works; the assistant when none is named.

        Every run works as the same user, which may use sudo (D42): the
        assistant and Rouh are one assistant, and a repository is only
        where a run's work is saved.
        """
        name = OLD_NAMES.get(name or "", name or "assistant")
        if name == "assistant":
            return Space("assistant", self.run_as, self.workspace, self.runs_dir, self.runs_dir,
                         self.target, follow=True, leftovers=True)
        if name == "scratch":
            return Space("scratch", self.run_as, None, self.scratch_dir, self.runs_dir,
                         self.target, follow=False, leftovers=False)
        path = Path(self.spaces_dir) / name
        if path.is_symlink():
            # A folder added as it is (D43): the spaces folder holds a link to it.
            return Space(name, self.run_as, None, os.path.realpath(path), self.runs_dir,
                         self.target, follow=False, leftovers=False, in_place=True)
        return Space(name, self.run_as, str(path), self.runs_dir,
                     self.runs_dir, "auto", follow=False, leftovers=False)

    @property
    def list_dir(self) -> Path:
        return self.data / "list"

    @property
    def runs_state(self) -> Path:
        """Each run's own folder: its terminal log, its hooks' settings, how it ended."""
        return self.data / "runs"

    @property
    def snapshot_path(self) -> Path:
        return self.data / "views.json"

    @property
    def asuser_path(self) -> Path:
        return Path(__file__).resolve().parent / "asuser.py"

    @property
    def codexhook_path(self) -> Path:
        """What every Codex hook runs: it posts the hook here and prints the answer."""
        return Path(__file__).resolve().parent / "codexhook.py"

    def agent_binary(self, engine: str) -> str:
        return self.codex if engine == "codex" else self.claude

    def agent_model(self, engine: str) -> str:
        return self.codex_model if engine == "codex" else self.model

    def agent_effort(self, engine: str) -> str:
        """How hard a run of this agent thinks when its request did not say."""
        return self.codex_effort if engine == "codex" else self.effort

    @property
    def hook_url(self) -> str:
        # A program listening on every address (the containers, where Rouh's core passes its
        # pages on, rouh/onebridge.py) is still reached by its own runs on loopback, which is
        # the only place its hook answers.
        host = "127.0.0.1" if self.http_host in ("0.0.0.0", "::", "") else self.http_host
        return f"http://{host}:{self.http_port}{self.base_path}/hook"


def load() -> Settings:
    return Settings()
