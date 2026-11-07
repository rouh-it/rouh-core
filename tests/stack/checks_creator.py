"""CONTAINERS.md: what only the Creator Rouh does, through its protected core (task 161).

The stack test's settings make this stack a Creator Rouh: ROUH_GUARD_UPSTREAM names "rouh-core",
a git server among the stand-ins seeded with the code under test (compose.test.yml), reached
through the key proxy like everything else. Until the guard's key is made the stack behaves as
any Rouh instance, so these come last, after Rouh's own change (self.improve), and make the key
first, as the Creator's owner does once.

    creator.push-main     a checked change, healthy for a while, is pushed to rouh-core's main
    creator.merge-runs    a run's work is fitted onto a main that moved, by land.sh, then proposed
    nightly.base-patch    the 00:40 base level is checked and pushed as base-patch/<level>, and
                          its result read back from the refs the guard fetches
"""
from __future__ import annotations

import json
import time

import smoke
from smoke import Failed, Stack, check, expect

UPSTREAM = "git://standins/rouh-core.git"
CODE = "git -c safe.directory='*' -C /code"
BARE = "git --git-dir=/tmp/git/rouh-core.git"
_DONE: dict = {}


def _once(name: str, fn, s: Stack) -> None:
    if name in _DONE:
        if _DONE[name]:
            raise Failed(_DONE[name])
        return
    try:
        fn(s)
        _DONE[name] = ""
    except Exception as e:  # noqa: BLE001 - whatever stopped it, the next check that needs it is told, not run again
        _DONE[name] = str(e) if isinstance(e, Failed) else f"{type(e).__name__}: {e}"[:900]
        raise


def _upstream_main(s: Stack) -> str:
    r = s.run("core", f"git ls-remote {UPSTREAM} refs/heads/main")
    return r.stdout.split()[0] if r.stdout.strip() else ""


def _head(s: Stack) -> str:
    return s.run("core", f"{CODE} rev-parse HEAD").stdout.strip()


def _until_pushed(s: Stack, want: str, limit: float, why: str) -> None:
    end = time.time() + limit
    got = ""
    while time.time() < end:
        got = _upstream_main(s)
        if want and got == want:
            return
        time.sleep(5)
    status = s.run("guard", "python -I /opt/rouh-guard/bin/rouh-guard status").stdout
    raise Failed(f"{why}: rouh-core's main is {got[:12]}, not {want[:12]}; the guard says "
                 f"{json.dumps((json.loads(status or '{}').get('upstream') or {}))[-900:]}")


def _push_main(s: Stack) -> None:
    from checks_workspace import self_improve

    self_improve(s)
    got = s.run("guard", "python -I /opt/rouh-guard/bin/rouh-guard upstream-key")
    key = (json.loads(got.stdout or "{}") or {}).get("key") or ""
    expect(key.startswith("ssh-ed25519 "), f"the guard made no key for rouh-core: {(got.stdout + got.stderr)[-400:]}")
    # The key stays with the protected core: neither the Rouh nor a run can reach it.
    for who in ("core", "worker"):
        r = s.run(who, "ls /guard/upstream/key 2>/dev/null; echo end")
        expect(r.stdout.strip() == "end", f"the {who} can see the guard's key: {r.stdout}")
    here = _head(s)
    r = s.run("core", f"{CODE} log -1 --format=%s")
    expect("stack test's change" in r.stdout, f"the code that runs is not Rouh's checked change: {r.stdout}")
    _until_pushed(s, here, 300, "the checked change never reached rouh-core's main")


@check("creator.push-main")
def creator_push_main(s: Stack) -> None:
    """Rouh's change of its own code, checked by the protected core and live as an undo point,
    is pushed to rouh-core's main once Rouh has answered on it for a while; never forced."""
    _once("push-main", _push_main, s)


def _merge_runs(s: Stack) -> None:
    _once("push-main", _push_main, s)
    before = _head(s)
    # Another run's work lands on rouh-core's main while this run works (in the Creator Rouh's
    # old way, a second land.sh; here, a push from elsewhere).
    s.run("standins", "set -e; rm -rf /tmp/other; git clone -q /tmp/git/rouh-core.git /tmp/other; cd /tmp/other; "
                      "echo 'Written by the other run.' > tests/stack/merge-other-run.txt; git add -A; "
                      "git -c user.name=Other -c user.email=other@example.com commit -q -m 'The other run'; "
                      "git push -q origin HEAD:main")
    other = s.run("standins", f"{BARE} rev-parse main").stdout.strip()
    end = time.time() + 120
    while time.time() < end and s.run("core", f"{CODE} rev-parse refs/upstream/heads/main").stdout.strip() != other:
        time.sleep(5)
    # This run, made from the code that ran before the other landed. Its landing runs on its own,
    # into a log, so a slow one says where it is.
    r = s.run("worker", f"set -e; rm -rf ~/fit-a /tmp/fit-a.log /tmp/fit-a.out; git clone -q /code ~/fit-a; cd ~/fit-a; "
                        f"git checkout -q {before}; git checkout -q -B main; git config user.name 'Stack run'; "
                        "git config user.email run@example.com; echo 'Written by this run.' > tests/stack/merge-this-run.txt; "
                        "git add -A; git commit -q -m 'The stack test run, fitted onto the other'; "
                        "nohup python3 /code/bin/rouh-land --path ~/fit-a --run stack-merge --title 'The stack test run' "
                        "> /tmp/fit-a.out 2> /tmp/fit-a.log < /dev/null & echo started")
    expect("started" in r.stdout, f"the run's landing did not start: {r.stdout}{r.stderr}")
    end = time.time() + 1500
    out = ""
    while time.time() < end:
        out = s.run("worker", "cat /tmp/fit-a.out 2>/dev/null").stdout.strip()
        if out:
            break
        time.sleep(10)
    log = s.run("worker", "cat /tmp/fit-a.log 2>/dev/null; ls -la /run/one/proposals 2>/dev/null | tail -5").stdout
    try:
        answer = json.loads((out.splitlines() or ["{}"])[-1])
    except ValueError:
        answer = {}
    expect(answer.get("landed"), f"the run's work did not land ({'no answer in 25 minutes' if not out else out[-300:]}); "
                                 f"its landing said: {log[-900:]}")
    now = _head(s)
    r = s.run("core", f"{CODE} log --format=%s -4; ls /code/tests/stack/merge-other-run.txt /code/tests/stack/merge-this-run.txt")
    expect("merge-other-run.txt" in r.stdout and "merge-this-run.txt" in r.stdout,
           f"the code that runs does not hold both runs' work: {r.stdout}{r.stderr}")
    r = s.run("core", f"{CODE} merge-base --is-ancestor {other} HEAD && echo on-top")
    expect("on-top" in r.stdout, "this run's work was not fitted on top of the other's")
    _until_pushed(s, now, 300, "the fitted work never reached rouh-core's main")


@check("creator.merge-runs")
def creator_merge_runs(s: Stack) -> None:
    """Two runs' work fitted together before proposing: rouh-core's main moved while a run
    worked, and its landing replays its work onto it with land.sh's own steps, the protected core
    checks the result, and it is pushed on top of the other run's."""
    _once("merge-runs", _merge_runs, s)


_LEVEL = r'''
from pathlib import Path
from rouh import base_patches as b
print("RELEASES", b.makes_releases())
repo = b._state()
_git = b._git
level = "{level}"
_git("checkout", "-q", "-B", f"base-patch/{{level}}", "origin/main", cwd=repo)
(repo / "{path}").parent.mkdir(parents=True, exist_ok=True)
(repo / "{path}").write_text("The stack test's base level.\n")
_git("add", "-A", cwd=repo)
_git("-c", "user.name=Rouh", "-c", "user.email=rouh@localhost", "commit", "-q", "-m", f"base {{level}}: stack test", cwd=repo)
print("SHA", _git("rev-parse", "HEAD", cwd=repo).stdout.strip())
print("WHY", repr(b.push_level(repo, f"base-patch/{{level}}")))
'''


def _as_rouh(s: Stack, code: str, timeout: float = 300) -> str:
    """Python in the core with Rouh's Django, as Rouh's own user, which the code and its folders are."""
    r = s.py("core", "from rouh.project import setup\nsetup()\n" + code, user="10001", timeout=timeout)
    if r.returncode:
        raise Failed(f"Python in the core failed: {(r.stderr or r.stdout)[-600:]}")
    return r.stdout


def _base_patch(s: Stack) -> None:
    _once("merge-runs", _merge_runs, s)
    out = _as_rouh(s, _LEVEL.format(level="9.9.1", path="deploy/container/base/stack-test-level.txt"), timeout=1700)
    expect("RELEASES True" in out, f"the Creator Rouh in the containers does not make releases: {out[-400:]}")
    sha = next((ln.split()[1] for ln in out.splitlines() if ln.startswith("SHA ")), "")
    expect("WHY ''" in out, f"the base level was not pushed: {out[-600:]}")
    r = s.run("core", f"git ls-remote {UPSTREAM} refs/heads/base-patch/9.9.1")
    expect(sha and r.stdout.startswith(sha), f"rouh-core has no base-patch/9.9.1 at {sha[:12]}: {r.stdout}{r.stderr}")
    # A level that changes more than the version list is never pushed.
    out = _as_rouh(s, _LEVEL.format(level="9.9.2", path="rouh/stack_test_not_a_version.py"), timeout=300)
    expect("nothing else" in out, f"a level changing Rouh's code was not refused: {out[-600:]}")
    r = s.run("core", f"git ls-remote {UPSTREAM} refs/heads/base-patch/9.9.2")
    expect(not r.stdout.strip(), f"a refused level reached rouh-core: {r.stdout}")
    # GitHub's answer, read back from what the guard fetches: published, and failed.
    s.run("standins", f"set -e; {BARE} tag base-9.9.1 {sha}; "
                      f"t=$({BARE} mktag <<EOF\nobject {sha}\ntype commit\ntag base-failed-9.9.3\n"
                      "tagger Actions <a@example.com> 0 +0000\n\nWhat failed: the build on Arm\n"
                      f"The run: https://example.com/run/1\nEOF\n); {BARE} update-ref refs/base-failed/9.9.3 $t")
    out = _as_rouh(s, "from rouh import base_patches as b, guardface\n"
                   "guardface.ask('upstream', fetch=True, timeout=300)\n"
                   "print('ONE', b._result(None, '9.9.1'))\nprint('THREE', b._result(None, '9.9.3'))")
    expect("ONE {'level': '9.9.1', 'ok': True" in out, f"the published level was not read back: {out[-500:]}")
    expect("the build on Arm" in out, f"the failed level was not read back: {out[-500:]}")


@check("nightly.base-patch")
def nightly_base_patch(s: Stack) -> None:
    """The 00:40 base level: made on top of rouh-core's main as the guard fetches it, checked by
    the protected core and pushed as base-patch/<level> only if it changes the version list alone;
    published and failed levels read back from the refs the guard keeps in /code."""
    _once("base-patch", _base_patch, s)


smoke.LAST.update({"creator.push-main", "creator.merge-runs", "nightly.base-patch"})
smoke.LIMIT.update({"creator.push-main": 1800, "creator.merge-runs": 2400, "nightly.base-patch": 2400})
