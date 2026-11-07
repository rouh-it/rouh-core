"""`rouh objecttree` for a job: the command run inside Rouh, against the job's own checkout.

Making, moving and checking the workspace's projects, tasks and steps writes a row first and
the folder after (`rouh/objecttree.py`), so it needs Rouh's database. A job cannot open that
itself, and should not: the password is in a file only Rouh may read, and a job is the
`assistant` user. Until 27 October 2026 `bin/rouh` ran the module in the job's own process,
with whatever `python3` it found, and two runs on task 98 that day could not make a step: one
had no Django, and the other, given Rouh's virtualenv, connected with no password
("fe_sendauth: no password supplied"), which the pool's retries turned into "no database
connection free" two seconds later, and which read like task 137's full database.

So `bin/rouh objecttree ...` posts its words here, with the workspace it was run in, and Rouh
runs `objecttree.main` with them and answers what it printed and its exit code. Rouh runs as
root and hands every file it writes to whoever owns the checkout (`steps.own_as_workspace`), so
the job can edit and commit them as its own.

Only a caller on this machine that did not come through the proxy (`from_this_machine`), and
only for a checkout of the person's workspace (its first commit is the live workspace's) in
one of the places a workspace is kept or checked out: the live one, the one program's space
and its runs' checkouts, assistant jobs' worktrees and the crew's folder. Anything else is
refused before the command is read.
"""
from __future__ import annotations

import asyncio
import io
import logging
import os
import subprocess
from pathlib import Path

from django.http import HttpRequest
from django.views.decorators.csrf import csrf_exempt

from rouh.config import config

from .common import answer, body_of, from_this_machine, only

log = logging.getLogger(__name__)


def _places() -> list[Path]:
    said = (config.assistant_repo, config.workspace_space, config.one_runs,
            config.assistant_jobs, config.crew_workspace)
    return [Path(one).resolve() for one in said if one]


def _first_commit(where: Path) -> str:
    try:
        # As root, in a checkout the person's assistant owns, which git refuses without this.
        done = subprocess.run(["git", "-c", "safe.directory=*", "-C", str(where), "rev-list",
                               "--max-parents=0", "HEAD"], capture_output=True, text=True,
                              timeout=20, check=False)
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout.split()[-1] if done.returncode == 0 and done.stdout.split() else ""


_FIRST: list[str] = []


def _workspace_first_commit() -> str:
    """The live workspace's first commit, kept once it has been read."""
    if not _FIRST and config.assistant_repo:
        first = _first_commit(Path(config.assistant_repo))
        if first:
            _FIRST.append(first)
    return _FIRST[0] if _FIRST else ""


def workspace_of(said: str) -> Path | None:
    """The workspace a caller named, if it is one Rouh may write into, else None."""
    if not said or not os.path.isabs(said):
        return None
    root = Path(said).resolve()
    if not (root / "_migration-map.json").is_file():
        return None
    if not any(root == place or place in root.parents for place in _places()):
        return None
    first = _workspace_first_commit()
    if not first or _first_commit(root) != first:
        return None
    return root


def _run(root: Path, words: list[str]) -> tuple[int, str, str]:
    from rouh import objecttree

    out, err = io.StringIO(), io.StringIO()
    try:
        code = objecttree.main(["--root", str(root), *words], out=out, err=err)
    except SystemExit as exc:                     # argparse, on words it does not take
        code = exc.code if isinstance(exc.code, int) else 2
    return code, out.getvalue(), err.getvalue()


#: The most a carried tree may be, packed (`_carried`).
CARRIED_MOST = 32 * 1024 * 1024
#: The files a tree is made of, which is all a carried tree holds (`bin/rouh`, `carry`).
TREE_FILES = ("_migration-map.json", ".object.json", "AGENTS.md", "step.md")


def _carried(packed: str, first: str, words: list[str]) -> dict:
    """The command run on a copy of a run's tree it carried here, in the containers.

    There the run's checkout is in the worker, which Rouh's core cannot see, so `bin/rouh` sends
    the files the tree is made of (`TREE_FILES`, packed), and the commit its checkout began from.
    Rouh lays them out in a folder of its own, runs the command there with its database, as it
    would in the checkout, and answers what changed: each file written, with what is in it, each
    removed, and each object folder moved, which `bin/rouh` then does in the checkout itself.
    The files are only ever read as data; nothing in them is run.
    """
    import base64
    import shutil
    import tarfile
    import tempfile

    raw = base64.b64decode(packed or "")
    if len(raw) > CARRIED_MOST:
        return {"ok": False, "error": "The tree sent is larger than Rouh takes."}
    first_live = _workspace_first_commit()
    if not first or not first_live or first != first_live:
        return {"ok": False, "error": "That is not a checkout of this Rouh's workspace."}
    work = Path(tempfile.mkdtemp(prefix="carried-", dir=config.data_dir))
    try:
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:*") as tar:
            members = [m for m in tar.getmembers() if m.isfile() and os.path.basename(m.name) in TREE_FILES]
            tar.extractall(work, members=members, filter="data")
        if not (work / "_migration-map.json").is_file():
            return {"ok": False, "error": "The tree sent has no _migration-map.json at its top."}
        git = ["git", "-c", "safe.directory=*", "-c", "user.name=Rouh", "-c", "user.email=rouh@localhost", "-C", str(work)]
        for step in (["init", "-q"], ["add", "-A"], ["commit", "-q", "-m", "as carried"]):
            subprocess.run([*git, *step], capture_output=True, timeout=60, check=False)
        code, out, err = _run(work, words)
        subprocess.run([*git, "add", "-A"], capture_output=True, timeout=60, check=False)
        said = subprocess.run([*git, "diff", "--cached", "--name-status", "-M", "HEAD"],
                              capture_output=True, text=True, timeout=60, check=False).stdout
        changes, files = [], {}
        for line in said.splitlines():
            bits = line.split("\t")
            kind = bits[0][:1]
            changes.append([kind, *bits[1:]])
            for path in bits[1:] if kind in "AMR" else []:
                if (work / path).is_file():
                    files[path] = base64.b64encode((work / path).read_bytes()).decode()
        return {"ok": True, "code": code, "out": out, "err": err, "changes": changes, "files": files}
    finally:
        shutil.rmtree(work, ignore_errors=True)


@csrf_exempt
@only("POST")
async def internal_objecttree(request: HttpRequest):
    """A job or a run on this machine, making, moving or checking objects in its checkout."""
    if not from_this_machine(request):
        return answer({"ok": False, "error": "Only this machine may use this address."},
                      status=403)
    body = body_of(request)
    words = body.get("args")
    if not isinstance(words, list) or not all(isinstance(w, str) for w in words):
        return answer({"ok": False, "error": "Send the command's words as a list, args."},
                      status=400)
    if body.get("tree"):
        by = " ".join(str(body.get("by") or "").split())[:120] or "the worker"
        got = await asyncio.to_thread(_carried, str(body["tree"]), str(body.get("first") or ""), words)
        log.info("%s: rouh objecttree %s on a carried tree: %s", by, " ".join(words[:1]),
                 f"exit {got.get('code')}" if got.get("ok") else got.get("error"))
        if got.get("ok") and got.get("code") == 0 and words[:1] in (["create"], ["move"]):
            from rouh import runtime

            try:
                await runtime.announce_objects()
            except Exception:
                log.exception("the change on a carried tree could not be announced")
        return answer(got, status=200 if got.get("ok") else 400)
    root = await asyncio.to_thread(workspace_of, str(body.get("root") or ""))
    if root is None:
        return answer({"ok": False, "error": (
            f"{body.get('root') or 'Nothing'} is not a workspace Rouh writes into: it needs "
            "_migration-map.json at its top, and to be the workspace or a git checkout of it "
            "in one of the places runs and jobs keep them.")}, status=400)
    by = " ".join(str(body.get("by") or "").split())[:120] or "this machine"
    code, out, err = await asyncio.to_thread(_run, root, words)
    log.info("%s: rouh objecttree %s in %s: exit %s", by, " ".join(words[:1]), root, code)
    if code == 0 and words[:1] in (["create"], ["move"]):
        from rouh import runtime

        try:
            await runtime.announce_objects()
        except Exception:
            log.exception("the change in %s could not be announced", root)
    return answer({"ok": True, "code": code, "out": out, "err": err})
