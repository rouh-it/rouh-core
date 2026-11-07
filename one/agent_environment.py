"""Privileged agent and shell environment setup, using only the standard library.

The command module supplies helper and system lookups so its established import
paths and monkeypatch boundaries also work when it runs directly under python -I.
Trust and MCP configuration remain with their own helpers.
"""
from __future__ import annotations

import os


SAFE_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
#: The worker's own settings a run is given as they are (`_clean_env`).
PASSED_ON = ("HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY", "https_proxy", "http_proxy", "no_proxy",
             "ROUH_WORKER_KEY_FILE", "ROUH_LAND_THROUGH")
#: The protected core's commands, in the containers (guard/README.md).
GUARD_BIN = "/opt/rouh-guard/bin"
#: `bin/` of the repository this file is in: Rouh's commands for a workspace.
OWN_BIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin")


#: The one variable a run of Codex billed to the API key reads its key from
#: (one/billing.py). Set for that run's Codex alone; `_clean_env` never
#: carries it anywhere else.
API_KEY_VAR = "OPENAI_API_KEY"


def _home(command) -> str:
    # For the tests on the laptop only, which must never touch the real
    # ~/.claude.json. On the server this runs under sudo, which empties the
    # environment, so a caller cannot use it to point anywhere else.
    return command.os.environ.get("ONE_ASUSER_HOME") or command.pwd.getpwuid(command.os.getuid()).pw_dir


def _clean_env(extra: dict | None, command) -> dict:
    env = {
        "HOME": command._home(),
        "USER": command.pwd.getpwuid(command.os.getuid()).pw_name,
        "LOGNAME": command.pwd.getpwuid(command.os.getuid()).pw_name,
        "PATH": command.SAFE_PATH,
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
    }
    git = command.shutil.which("git")
    if git and command.os.path.dirname(git) not in env["PATH"].split(":"):
        env["PATH"] = command.os.path.dirname(git) + ":" + env["PATH"]
    # Rouh's commands for a workspace - `rouh-task`, `rouh` - from this
    # program's own deployed copy of the repository, which no run can change.
    # A run in a checkout of the workspace has no code of its own to run them
    # from (21 October 2026).
    if command.os.path.isdir(command.OWN_BIN):
        env["PATH"] = command.OWN_BIN + ":" + env["PATH"]
    # In the containers (deploy/stack/compose.yml) a run's only way out is the key proxy, and
    # its only way to Rouh the key Rouh made for the worker; both are the worker's own settings,
    # which a run needs as they are. On the server this runs under sudo, whose environment has
    # none of them, so nothing changes there. And `rouh-propose`, how a run in the containers
    # hands a change of Rouh's own code to its protected core, from that core's own files.
    for name in command.PASSED_ON:
        if command.os.environ.get(name):
            env[name] = command.os.environ[name]
    if command.os.path.isdir(command.GUARD_BIN):
        env["PATH"] = env["PATH"] + ":" + command.GUARD_BIN
    env.update(extra or {})
    return env


def agent(args, command) -> int:
    """Become the run's agent - Claude Code or Codex - with nothing of the program's environment.

    The program's own environment never reaches a run: a run gets a home, a
    path, a terminal type, its own id and, for Codex, the key its hooks answer
    with, and that is all. Each agent finds the person's subscription in this
    user's own settings. Claude Code's updater is off: this user cannot write
    where Claude Code is installed, and every run's screen said "Auto-update
    failed" until it was.

    The key goes in the environment and never in the arguments, because the
    arguments are on the process list for every account on this machine to
    read. Claude Code's key is in its settings file, mode 600, for the same
    reason; Codex has no settings file of its own here, so its hooks read the
    key from here.
    """
    binary = command.shutil.which(
        args.binary, path=command.SAFE_PATH + ":" + command.os.path.dirname(args.binary)) \
        if not command.os.path.isabs(args.binary) else args.binary
    if not binary:
        what = "Codex" if args.engine == "codex" else "Claude Code"
        command.sys.stderr.write(
            f"one: {what} is not on this machine: there is no {args.binary}.\r\n")
        if args.engine == "codex":
            command.sys.stderr.write("one: install it with: sudo npm install -g @openai/codex\r\n")
        return 127
    extra = {"TERM": args.term, "COLORTERM": "truecolor", "ONE_RUN": args.run,
             "DISABLE_AUTOUPDATER": "1", "TMPDIR": command._run_tmp(args.cwd)}
    if args.hook_key:
        extra["ONE_HOOK_KEY"] = args.hook_key
    if args.api_key_file:
        key, why = command._take_api_key(args.api_key_file, args.cwd)
        if not key:
            # Never the subscription instead: a run the person asked to have
            # billed to the key either is, or does not start.
            command.sys.stderr.write(f"one: this run is billed to the OpenAI API key, and {why}, "
                                     "so Codex was not started. Nothing was billed.\r\n")
            return 78
        extra[command.API_KEY_VAR] = key
    if args.browser_port:
        extra[command.BROWSER_CONFIG_VAR] = command._browser_config(args.cwd, args.browser_port)
    env = command._clean_env(extra)
    command.os.chdir(args.cwd)
    rest = list(args.rest)
    if rest and rest[0] == "--":
        rest = rest[1:]
    command.os.execve(binary, [binary, *rest], env)
    return 127  # pragma: no cover


def _take_api_key(path: str, cwd: str, command) -> tuple[str, str]:
    """The key the program left in the run's own folder, and the file gone.

    The program writes it there through ``write``, from stdin, a moment before
    it starts the run, because sudo carries no environment across and an
    argument is on every process list. It is read once and deleted at once, so
    it is in the Codex process's environment and nowhere else on disk.
    """
    own = command.os.path.join(cwd, ".one")
    if not command._inside(path, own) or command.os.path.islink(path):
        return "", f"{path} is not in the run's own folder"
    try:
        with open(path, encoding="utf-8") as fh:
            key = fh.read().strip()
    except OSError:
        return "", "the key did not reach it"
    finally:
        with command.contextlib.suppress(OSError):
            command.os.unlink(path)
    if not key or any(c.isspace() for c in key):
        return "", "the key that reached it was empty or not a key"
    return key, ""


def _run_tmp(cwd: str, command) -> str:
    """This run's own folder for temporary files, and why it is not /tmp.

    On this server ``/tmp`` is a tmpfs: a filesystem that lives in memory and
    nowhere else, so a folder left in it is memory left held. Proving a change
    fills it - the harness stands a whole world up under ``tempfile.mkdtemp``
    for every world it serves - and none of it is given back by ending the run,
    because ending a run frees processes and not files. On 22 September 2026
    that was 7.9 GB of this machine's memory, in folders belonging to runs
    whose checkouts had been deleted days before.

    A run's own checkout is on disk, where there are 395 GB rather than 16, and
    it is already thrown away when the run is tidied. So that is where a run's
    temporary files go, and they go with it.

    ``.one/`` rather than the checkout's own top level, because ``.one/`` is
    already the run's scratch folder and already carries a ``.gitignore`` of
    ``*``, so nothing written here can reach a commit. If it cannot be made -
    a checkout that is gone, a folder that is not ours - the answer is the
    machine's own ``/tmp``, which is what every run used before this.
    """
    try:
        folder = command.os.path.join(cwd, ".one", "tmp")
        command.os.makedirs(folder, exist_ok=True)
        return folder
    except OSError:
        return command.os.environ.get("TMPDIR") or "/tmp"


def shell(args, command) -> int:
    env = command._clean_env({"TERM": args.term, "COLORTERM": "truecolor", "ONE_RUN": args.run,
                              "TMPDIR": command._run_tmp(args.cwd)})
    command.os.chdir(args.cwd)
    sh = command.pwd.getpwuid(command.os.getuid()).pw_shell or "/bin/bash"
    if not command.os.path.exists(sh) or sh.endswith("nologin") or sh.endswith("false"):
        sh = "/bin/bash"
    command.os.execve(sh, [sh, "-l"], env)
    return 127  # pragma: no cover
