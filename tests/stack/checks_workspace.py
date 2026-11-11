"""CONTAINERS.md: one workspace for Rouh and its runs, its copy in the owner's repository, and
Rouh changing its own code through the protected core.

The workspace's main is the bare repository in the workspace volume, written by the core alone
(rouh/workspace_follow.py); the stack test's settings name a git server among the stand-ins as
the owner's repository (ROUH_WORKSPACE_REMOTE=git://standins/workspace.git).
"""
from __future__ import annotations

import time

import smoke
from smoke import Failed, Stack, check, expect

MAIN = "git -c safe.directory='*' --git-dir=/workspace-origin/workspace.git"


def _until(s: Stack, service: str, script: str, want: str, limit: float, why: str) -> str:
    end = time.time() + limit
    out = ""
    while time.time() < end:
        r = s.run(service, script)
        out = r.stdout + r.stderr
        if want in r.stdout:
            return r.stdout
        time.sleep(5)
    raise Failed(f"{why}: {out[-500:]}")


@check("workspace.one")
def workspace_one(s: Stack) -> None:
    """A task Rouh makes reaches the runs' workspace, and a run's committed work reaches Rouh's."""
    s.chat = ""  # a chat of its own: a chat already filed into a task files into that one
    got = s.tool("make_a_task", {"title": "Shared workspace task"})
    expect("Traceback" not in got, got[:300])
    _until(s, "worker", f"{MAIN} ls-tree -r --name-only main | grep -i shared-workspace-task | head -1",
           "shared-workspace-task", 180, "Rouh's new task never reached the workspace's main")
    _until(s, "worker", "ls -d /home/rouh/workspace/*/*shared-workspace-task* /home/rouh/workspace/*/*/*shared-workspace-task* 2>/dev/null",
           "shared-workspace-task", 180, "the runs' workspace did not follow main")
    smoke.the_run(s)
    _until(s, "core", "cat /data/workspace/stack-test/run-note.md 2>/dev/null",
           "A note the stack test's run wrote", 240, "the run's committed note never reached Rouh's workspace")


@check("workspace.github")
def workspace_github(s: Stack) -> None:
    """Main is saved to the owner's repository, and what is pushed there comes back."""
    ours = s.run("core", f"{MAIN} rev-parse main").stdout.strip()
    expect(ours, "the workspace has no main")
    _until(s, "core", "git ls-remote git://standins/workspace.git refs/heads/main", ours[:12], 120,
           "main was not saved to the owner's repository")
    s.run("standins", "set -e; rm -rf /tmp/laptop; git clone -q /tmp/git/workspace.git /tmp/laptop; cd /tmp/laptop; "
                      "echo 'Written on the laptop.' > from-the-laptop.md; git add -A; "
                      "git -c user.name=Laptop -c user.email=laptop@example.com commit -q -m 'From the laptop'; "
                      "git push -q origin HEAD:main")
    _until(s, "core", "cat /data/workspace/from-the-laptop.md 2>/dev/null", "Written on the laptop", 150,
           "what was pushed to the owner's repository never reached Rouh's workspace")


_IMPROVED: dict = {}


@check("self.improve", "guard.change-step", "self.deploy")
def self_improve(s: Stack) -> None:
    if _IMPROVED:
        if _IMPROVED.get("error"):
            raise Failed(_IMPROVED["error"])
        return
    try:
        _improve(s)
        _IMPROVED["ok"] = True
    except Failed as e:
        _IMPROVED["error"] = str(e)
        raise


def _improve(s: Stack) -> None:
    """Rouh changes its own code when asked: a run in its own clone commits a change, the
    protected core checks it, and the code that runs is the new commit, as a new undo point."""
    before = s.run("core", "git -c safe.directory='*' -C /code rev-parse HEAD").stdout.strip()
    got = s.tool("improve_myself", {
        "change": "WRITE: tests/stack/marker-from-a-run.txt A change of Rouh's own code, made by a run.\n"
                  "COMMIT: The stack test's change of Rouh's own code\nSAY: Done.",
        "title": "Stack test code change"})
    expect("Traceback" not in got, f"improve_myself: {got[:300]}")
    end = time.time() + 900
    now = before
    while time.time() < end:
        r = s.run("core", "git -c safe.directory='*' -C /code log -1 --format='%H %s'")
        now = r.stdout.strip()
        if now and not now.startswith(before) and "stack test's change" in now:
            break
        time.sleep(10)
    else:
        try:
            runs = s.tool("one_runs", {})
        except Exception as e:  # noqa: BLE001 - only to say more in the failure
            runs = f"(one_runs: {e})"
        raise Failed(f"the change never became the code that runs (still {now[:60]}); "
                     f"the runs: {runs[-500:]}; the guard said: {s.logs('guard', 30)[-300:]}; "
                     f"the worker said: {s.logs('worker', 30)[-300:]}")
    # Rouh starts again on it; wait for it to answer.
    for _ in range(60):
        try:
            code, body, _ = s.get("/healthz", cookie=False)
        except OSError:
            code, body = 0, ""
        if code == 200 and '"ok":true' in body.replace(" ", ""):
            break
        time.sleep(5)
    else:
        raise Failed("Rouh did not come back after the change went live")
    r = s.run("core", "cat /code/tests/stack/marker-from-a-run.txt")
    expect("made by a run" in r.stdout, f"the running code does not have the change: {r.stdout or r.stderr}")


smoke.LAST.update({"self.improve", "guard.change-step", "self.deploy"})
# The three rows share one change of Rouh's own code, made once by whichever of them comes first
# (in CONTAINERS.md's order that is guard.change-step), so each has the change's own limit: under
# the default 300 s the first row was stopped while the change was still on its way, and its
# "took longer than its limit" was remembered as the answer of all three and of everything that
# builds on them (self.gene-log, guard.undo, the Creator's pushes), on 11 November 2026 (dc300500).
smoke.LIMIT.update({"workspace.one": 900, "workspace.github": 420,
                    "self.improve": 1500, "guard.change-step": 1500, "self.deploy": 1500})


@check("self.gene-log")
def gene_log(s: Stack) -> None:
    """The change a run made of Rouh's own code is read into the gene log (Read now, on the page)."""
    from checks_nightly import _post

    self_improve(s)
    got = _post(s, "/api/genes/log/read", {})
    expect(got.get("ok") and "Read 0 new" not in str(got.get("said")), f"the gene log's Read now: {got}")


smoke.LAST.add("self.gene-log")


@check("callbacks.tasks")
def callbacks_tasks(s: Stack) -> None:
    """A run makes a task with `rouh objecttree` and sets its status with `rouh-task`, from the
    worker: Rouh writes the row, the folder appears in the run's own checkout, and once the run
    has landed its work the task is in Rouh's workspace too."""
    run = smoke.the_run(s)
    expect("made-by-a-run" in run["tree"], f"rouh objecttree create in a run: {run['tree'][-400:]}")
    expect("in-progress" in run["task"].lower() or "in progress" in run["task"].lower(),
           f"rouh-task in a run: {run['task'][-400:]}")
    _until(s, "core", "ls -d /data/workspace/*/*made-by-a-run* 2>/dev/null", "made-by-a-run", 240,
           "the task the run made never reached Rouh's workspace")


@check("guard.undo")
def guard_undo(s: Stack) -> None:
    """Meta, Changes, Put back: the undo point before the run's change is put back, the code that
    runs is that point's again, and Rouh comes back on it."""
    import json as _json

    from checks_nightly import _post

    self_improve(s)
    code, body, _ = s.get("/api/settings/changes")
    expect(code == 200, f"/api/settings/changes answered {code}")
    points = _json.loads(body).get("points") or []
    expect(len(points) >= 2, f"there is no earlier undo point to put back: {points}")
    newest = max(points, key=lambda p: p.get("n") or 0)
    before = max((p for p in points if (p.get("n") or 0) < (newest.get("n") or 0)), key=lambda p: p.get("n") or 0)
    got = _post(s, "/api/settings/changes/undo", {"point": before["n"]})
    expect(got.get("ok"), f"Put back: {got}")
    want = str(before.get("commit") or "")
    end = time.time() + 600
    now = ""
    while time.time() < end:
        now = s.run("core", "git -c safe.directory='*' -C /code rev-parse HEAD").stdout.strip()
        try:
            code, body, _ = s.get("/healthz", cookie=False)
        except OSError:
            code, body = 0, ""
        if want and now.startswith(want[:12]) and code == 200:
            return
        time.sleep(10)
    raise Failed(f"the code that runs is {now[:12]}, not the undo point put back ({want[:12]})")


smoke.FINAL.add("guard.undo")
smoke.LIMIT.update({"guard.undo": 1200})
