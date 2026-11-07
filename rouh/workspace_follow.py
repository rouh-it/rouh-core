"""One workspace for Rouh and its runs in the containers, and its copy on GitHub.

On the server the workspace is the person's own repository on GitHub, and two checkouts follow
it: Rouh's live one, which `land.sh` moves onto every landing (`update-all.sh --workspace`), and
the one program's, which follows main every minute. In the containers every Rouh instance runs
(deploy/stack/compose.yml) there was no GitHub and no deploy: the core's workspace (/data/
workspace) and the runs' (in the worker) were two repositories that never met, and what a run
made never reached Rouh's page (CONTAINERS.md, `workspace.one`).

So in the stack the workspace's main is a bare repository in a volume the core and the worker
both mount (`ROUH_WORKSPACE_ORIGIN`, /workspace-origin/workspace.git). The core's start makes it
from the core's workspace on the first start (guard/bin/rouh-core-entrypoint), Rouh's saves land
there (`rouh/saving.py`, `ROUH_SAVE_WORKSPACE`), the runs land there (one/asuser.py), and this
keeps Rouh's live checkout on it, the way `update-all.sh --workspace` does on the server: after
Rouh's own pending saves have gone, a main that moved is checked out over it, and files nobody
has saved yet are left where they are.

And when the owner names a repository for it (`ROUH_WORKSPACE_REMOTE`, an https address with
`ROUH_WORKSPACE_REMOTE_TOKEN`, or any address git reaches), main is kept level with it: new work
here is pushed there, and new work there (the person's laptop, say) is taken when it is a
fast-forward. When the two have each moved, neither is changed, and Rouh says so once.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from urllib.parse import quote, urlsplit, urlunsplit

from . import gitutil
from .config import config

log = logging.getLogger("rouh.workspace_follow")

EVERY = float(os.environ.get("ROUH_WORKSPACE_FOLLOW_EVERY", "30"))
REMOTE = os.environ.get("ROUH_WORKSPACE_REMOTE", "").strip()
TOKEN = os.environ.get("ROUH_WORKSPACE_REMOTE_TOKEN", "").strip()
#: Or, for an ssh address, a key that may write to that one repository (a deploy key), kept in the
#: core's data volume. The Creator Rouh's (task 161): GitHub's API makes a deploy key, and nobody
#: has to make a token by hand.
KEY_FILE = os.environ.get("ROUH_WORKSPACE_REMOTE_KEY_FILE", "").strip()

_thread: threading.Thread | None = None
_wake = threading.Event()
#: What the last pass found, for the stack test and anyone who asks: {"at", "head", "remote"}.
state: dict = {}


def enabled() -> bool:
    return os.environ.get("ROUH_WORKSPACE_FOLLOW", "") == "1" and bool(config.assistant_repo)


def _git(*args: str, where: str | None = None, timeout: float = 120):
    return gitutil.run(where or config.assistant_repo, *args, timeout=timeout)


def _remote_url() -> str:
    """The owner's repository, with the token in it for https; never logged."""
    if not REMOTE:
        return ""
    if TOKEN and REMOTE.startswith("https://"):
        parts = urlsplit(REMOTE)
        return urlunsplit(parts._replace(netloc=f"x-access-token:{quote(TOKEN, safe='')}@{parts.hostname}"
                                         + (f":{parts.port}" if parts.port else "")))
    return REMOTE


def _ssh() -> tuple[str, ...]:
    """git's settings for the owner's repository over ssh with its own key, when one is set."""
    if not KEY_FILE:
        return ()
    known = os.path.join(os.path.dirname(KEY_FILE), "known_hosts")
    return ("-c", f"core.sshCommand=ssh -i {KEY_FILE} -o IdentitiesOnly=yes -o BatchMode=yes "
                  f"-o StrictHostKeyChecking=accept-new -o UserKnownHostsFile={known}")


def follow_once() -> str:
    """One pass: Rouh's saves first, then the owner's repository, then Rouh's live checkout.
    Returns what it did, in a few words."""
    from . import saving

    saving.poke()
    saving.wait(90)
    did = take_landings()
    url = _remote_url()
    origin = _git("remote", "get-url", "origin").stdout.strip()
    if url and origin:
        did.append(_level_with_remote(origin, url))
    got = _git("fetch", "--quiet", "origin")
    if got.returncode:
        return "could not fetch the workspace's main: " + (got.stderr or got.stdout).strip()[:200]
    want = _git("rev-parse", "--verify", "-q", "origin/main").stdout.strip()
    head = _git("rev-parse", "--verify", "-q", "HEAD").stdout.strip()
    if want and want != head:
        moved = _git("checkout", "--quiet", "--force", "-B", "main", want)
        if moved.returncode:
            did.append("could not move onto main: " + (moved.stderr or moved.stdout).strip()[:200])
        else:
            _git("branch", "--quiet", "--set-upstream-to=origin/main", "main")
            did.append(f"moved onto main at {want[:7]}")
            _changed()
    state.update(at=time.time(), head=want or head)
    return "; ".join(d for d in did if d) or "level"


def _level_with_remote(origin: str, url: str) -> str:
    """The bare main and the owner's repository's main, made the same where one is ahead."""
    def bare(*args, timeout=120):
        return gitutil.run(origin, *_ssh(), *args, timeout=timeout)

    got = bare("fetch", "--quiet", url, "+refs/heads/main:refs/remotes/github/main", timeout=180)
    if got.returncode:
        theirs = ""
        if "couldn't find remote ref" not in (got.stderr or "") and "not found" not in (got.stderr or "").lower():
            state["remote"] = "could not be reached"
            return "the owner's repository could not be reached"
    else:
        theirs = bare("rev-parse", "-q", "--verify", "refs/remotes/github/main").stdout.strip()
    ours = bare("rev-parse", "-q", "--verify", "refs/heads/main").stdout.strip()
    if not ours or theirs == ours:
        state["remote"] = "level"
        return ""
    if theirs and bare("merge-base", "--is-ancestor", ours, theirs).returncode == 0:
        bare("update-ref", "refs/heads/main", theirs, ours)
        state["remote"] = "taken"
        return f"took the owner's repository's main at {theirs[:7]}"
    if not theirs or bare("merge-base", "--is-ancestor", theirs, ours).returncode == 0:
        pushed = bare("push", "--quiet", url, "refs/heads/main:refs/heads/main", timeout=180)
        if pushed.returncode == 0:
            state["remote"] = "pushed"
            return f"saved main at {ours[:7]} to the owner's repository"
        state["remote"] = "push refused"
        return "the owner's repository refused main"
    if state.get("remote") != "apart":
        log.warning("the workspace's main and the owner's repository have each moved; neither was changed")
    state["remote"] = "apart"
    return "main and the owner's repository have each moved; neither was changed"


def _changed() -> None:
    """Rouh's own idea of the tree brought up to the files that just arrived: the next save
    reads the rows from the disk first (`saving`, `owning.sync`), and the task list and every
    other listener is told the tree changed."""
    from . import objecttree, saving

    saving.poke()
    for hook in list(objecttree.WRITTEN):
        if getattr(hook, "__name__", "") == "poke":
            continue
        try:
            hook()
        except Exception:  # noqa: BLE001 - following main never stops for what comes after it
            log.warning("a listener of the tree failed after main moved", exc_info=True)


LANDINGS = os.environ.get("ROUH_LANDINGS_DIR", "").strip()


def take_landings() -> list[str]:
    """Every run's work the worker handed over (bin/rouh-land), landed onto main with land.sh in
    a checkout of the core's own, and the answer written beside it. Returns what each said."""
    import glob
    import json
    import shutil
    import subprocess
    import tempfile

    if not LANDINGS or not os.path.isdir(LANDINGS):
        return []
    origin = _git("remote", "get-url", "origin").stdout.strip()
    said = []
    for bundle in sorted(glob.glob(os.path.join(LANDINGS, "*.bundle"))):
        name = bundle[: -len(".bundle")]
        result = name + ".result.json"
        if os.path.exists(result):
            continue
        try:
            with open(name + ".json", encoding="utf-8") as fh:
                about = json.load(fh)
        except (OSError, ValueError):
            about = {}
        _write(result, {"state": "landing"})
        work = tempfile.mkdtemp(prefix="landing-", dir=config.data_dir)
        try:
            got = gitutil.run(work, "clone", "-q", origin, ".", timeout=600)
            if got.returncode == 0:
                got = gitutil.run(work, "fetch", "-q", bundle, "+HEAD:refs/heads/landing", timeout=300)
            if got.returncode == 0:
                got = gitutil.run(work, "checkout", "-q", "landing", timeout=120)
            if got.returncode:
                _write(result, {"state": "done", "error": "the run's work could not be read: "
                                + (got.stderr or got.stdout).strip()[:300]})
                continue
            argv = ["bash", os.path.join(config.app_dir or "/code", "land.sh"), "--path", work,
                    "--target", str(about.get("target") or "main"), "--quiet", "--no-deploy"]
            for flag, key in (("--run", "run"), ("--title", "title"), ("--from", "from")):
                if about.get(key):
                    argv += [flag, str(about[key])]
            if about.get("merge"):
                argv.append("--merge")
            proc = subprocess.run(argv, capture_output=True, text=True, timeout=1800,
                                  env=dict(os.environ, GIT_TERMINAL_PROMPT="0"))
            lines = [line for line in proc.stdout.splitlines() if line.strip()]
            try:
                land = json.loads(lines[-1]) if lines else {}
            except ValueError:
                land = {}
            if not isinstance(land, dict) or "state" not in land:
                _write(result, {"state": "done", "error": "land.sh said nothing readable: "
                                + (proc.stderr or proc.stdout).strip()[-300:]})
            else:
                _write(result, {"state": "done", "land": land})
                said.append(f"{os.path.basename(name)}: {land.get('state')}")
        finally:
            shutil.rmtree(work, ignore_errors=True)
    return said


def _write(path: str, data: dict) -> None:
    import json

    tmp = path + ".part"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    os.replace(tmp, path)


def poke() -> None:
    _wake.set()


def _loop() -> None:
    time.sleep(10)
    while True:
        try:
            said = follow_once()
            if said != "level":
                log.info("the workspace: %s", said)
        except Exception:  # noqa: BLE001 - one pass failing is said and the next one runs
            log.warning("following the workspace's main failed", exc_info=True)
        _wake.wait(EVERY)
        _wake.clear()


def start() -> bool:
    global _thread
    if _thread is not None or not enabled():
        return _thread is not None
    _thread = threading.Thread(target=_loop, name="workspace-follow", daemon=True)
    _thread.start()
    log.info("Rouh's workspace follows its main%s", " and the owner's repository" if REMOTE else "")
    return True
