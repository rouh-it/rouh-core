"""Rouh's read-only shell, run here in the containers, where the one program holds no key.

On the server Rouh answers "how much disk is left" with a short command it runs itself, read-only,
in a sandbox (`rouh/tools.py`, `run_command`). In the containers every Rouh instance runs, Rouh's
core holds every key, so a command run there could read them; it runs here instead, in the worker,
which holds none (deploy/stack/compose.yml). Rouh still decides what may run: it checks the
command against its own read-only rules first (`plan_pipeline`) and sends only the stages it
allowed, each an argument list, wired together here without a shell. Only Rouh's own connection
may ask (`rules.ALLOWED`, "voice"), and only where the worker says so (`ONE_SHELL_FOR_ROUH=1`).

Each stage runs inside the same box as on the server (`rouh/sandbox.py`): the files read-only and
the network closed by the kernel. In the worker that is Landlock, because Docker's syscall filter
refuses bubblewrap its namespaces; the stack sets `ROUH_SANDBOX=required` there, so with no box
nothing runs. The program looks once, as it starts, and writes what it found beside its socket
(`sandbox.json`), where the core's server_health reads it (task 139, step 139-14).
"""
from __future__ import annotations

import json
import os
import subprocess

from rouh import sandbox

#: Beside the program's socket, in the volume the core and the worker share (/run/one).
STATE_FILE = "sandbox.json"
#: The box this program's stages run in, looked at once (`look`).
_box: sandbox.Sandbox | None = None


def look() -> sandbox.Sandbox:
    """The box, found once from `ROUH_SANDBOX` and `ROUH_SANDBOX_NETWORK`."""
    global _box
    if _box is None:
        mode = (os.environ.get("ROUH_SANDBOX") or "auto").strip().lower()
        network = (os.environ.get("ROUH_SANDBOX_NETWORK") or "").strip().lower() in ("1", "true", "yes", "on")
        _box = sandbox.Sandbox(mode=mode if mode in sandbox.MODES else "auto", network=network).look()
    return _box


def write_state(socket_path: str) -> dict:
    """Look, and write what was found beside the socket for the core to read."""
    state = look().state()
    path = os.path.join(os.path.dirname(socket_path) or ".", STATE_FILE)
    try:
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(state, f)
        os.replace(tmp, path)
    except OSError:
        pass
    return state

#: What a stage may be at most, and the whole of what may be asked.
MOST_STAGES = 6
MOST_ARGS = 64


def run(stages, *, cwd: str, timeout: float = 20, limit: int = 4000) -> str:
    if not isinstance(stages, list) or not stages or len(stages) > MOST_STAGES:
        return "Nothing to run."
    for parts in stages:
        if not isinstance(parts, list) or not parts or len(parts) > MOST_ARGS \
                or not all(isinstance(p, str) for p in parts):
            return "That is not a command this shell runs."
    box = look()
    refused = box.refusal()
    if refused:
        return refused
    env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": os.environ.get("HOME", "/tmp"),
           "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}
    cwd = cwd if os.path.isdir(cwd) else os.environ.get("HOME", "/")
    procs: list[subprocess.Popen] = []
    try:
        for i, parts in enumerate(stages):
            procs.append(subprocess.Popen(box.wrap(parts, cwd=cwd), cwd=cwd, env=env, text=True,
                                          stdin=procs[-1].stdout if procs else subprocess.DEVNULL,
                                          stdout=subprocess.PIPE, stderr=subprocess.PIPE))
            if i:
                procs[-2].stdout.close()
        out, err = procs[-1].communicate(timeout=min(float(timeout), 30))
        for proc in procs[:-1]:
            proc.wait(timeout=1)
    except subprocess.TimeoutExpired:
        for proc in procs:
            proc.kill()
        return f"Timed out after {int(timeout)} seconds."
    except (OSError, ValueError) as exc:
        return f"{type(exc).__name__}: {exc}"
    text = out or err or "(no output)"
    limit = min(int(limit), 8000)
    return text[:limit] + f"\n... cut off at {limit} characters." if len(text) > limit else text
