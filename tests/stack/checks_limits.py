"""CONTAINERS.md: how many runs at once, each run's memory limit, and a stop that ends everything.

In the worker there is no cgroup a run can be given (an unprivileged container, /sys/fs/cgroup
read-only), so each run's holder keeps its box by hand (one/runprocs.py). These checks drive
what the person drives - runs started and stopped through Rouh's own tools, and through the one
program's own socket in the worker as its CLI does - and look at the worker's processes from
outside. The stack test's settings (tests/stack/settings.env) give two runs at once and 256 MB
a run.
"""
from __future__ import annotations

import json
import time

from smoke import LAST, LIMIT, Failed, Stack, check, expect

# Each of these waits on runs starting, working and ending, past the five minutes a check gets.
LIMIT.update({"one.many-runs": 480, "install.max-runs": 480, "one.run-memory": 480, "one.run-stop": 600})


def _one(s: Stack, body: str, timeout: float = 120) -> object:
    """Ask the one program in the worker, over its own socket, as `one` (one/cli.py) does.

    ``body`` is the inside of an async function with ``c`` connected; what it returns is printed
    as JSON and handed back.
    """
    code = ("import asyncio, json\nfrom one.cli import Connection\n"
            "async def main():\n    c = Connection()\n    await c.open()\n    await c.hello()\n"
            "    try:\n" + "".join(f"        {line}\n" for line in body.strip().splitlines())
            + "    finally:\n        await c.close()\n"
            "print('ONE ' + json.dumps(asyncio.run(main())))")
    r = s.py("worker", code, timeout=timeout)
    for line in r.stdout.splitlines():
        if line.startswith("ONE "):
            return json.loads(line[4:])
    raise Failed(f"the one program in the worker did not answer: {(r.stdout + r.stderr)[-500:]}")


def _runs(s: Stack) -> list[dict]:
    return _one(s, 'return (await c.ask("runs", limit=200))["runs"]')


def _run_titled(s: Stack, title: str, limit: float = 90) -> dict:
    end = time.time() + limit
    while time.time() < end:
        found = [r for r in _runs(s) if r.get("title") == title]
        if found:
            return found[0]
        time.sleep(3)
    raise Failed(f"no run called {title!r} reached the one program")


def _wait_run(s: Stack, run_id: str, want, why: str, limit: float = 120) -> dict:
    end = time.time() + limit
    run: dict = {}
    while time.time() < end:
        run = next((r for r in _runs(s) if r["id"] == run_id), {})
        if run and want(run):
            return run
        time.sleep(3)
    raise Failed(f"{why}; the run is {json.dumps({k: run.get(k) for k in ('state', 'how', 'ended_why', 'queued_because')})}")


def _quiet(s: Stack, gap: float = 8, limit: float = 120, waiting_for: str = "") -> None:
    """Let whatever Rouh is saying by itself on the page's socket finish first.

    A run that finishes its turn is reported as a turn of its own ("A job has finished: ..."),
    and a tool asked for while that turn is answering reads that turn's answer as its own. So
    the socket is read until it has said nothing for ``gap`` seconds, and first, with
    ``waiting_for``, until it has said those words; then it is closed, as ``Stack.say`` leaves it.
    """
    s.socket()
    end = time.time() + limit
    try:
        while time.time() < end:
            try:
                raw = s.ws.recv(timeout=gap)
            except TimeoutError:
                if not waiting_for:
                    return
                continue
            if waiting_for and isinstance(raw, str) and waiting_for in raw:
                waiting_for = ""
    finally:
        try:
            s.ws.close()
        except Exception:  # noqa: BLE001 - a socket already gone is closed enough
            pass
        s.ws = None


def _tool(s: Stack, name: str, args: dict) -> str:
    _quiet(s)
    return s.tool(name, args)


def _alive(s: Stack, word: str) -> list[str]:
    r = s.run("worker", f"pgrep -f '{word}' || true")
    return r.stdout.split()


_MANY: dict = {}


@check("one.many-runs", "install.max-runs")
def many_runs(s: Stack) -> None:
    """ONE_MAX_RUNS from the settings file reaches the one program, and it starts that many runs
    at once and no more: one more waits, saying why, until one of them finishes."""
    if _MANY:
        if _MANY.get("error"):
            raise Failed(_MANY["error"])
        return
    try:
        _many_runs(s)
        _MANY["ok"] = True
    except Failed as e:
        _MANY["error"] = str(e)
        raise


def _many_runs(s: Stack) -> None:
    r = s.py("worker", """
import os
for pid in os.listdir("/proc"):
    try:
        argv = open(f"/proc/{pid}/cmdline", "rb").read().split(b"\\0")
        if b"one.program" in argv:
            env = dict(l.split(b"=", 1) for l in open(f"/proc/{pid}/environ", "rb").read().split(b"\\0") if b"=" in l)
            print("MAX", env.get(b"ONE_MAX_RUNS", b"").decode())
    except OSError:
        pass
""")
    said = [line.split(" ", 1)[1] for line in r.stdout.splitlines() if line.startswith("MAX ")]
    expect(said and said[0].strip().isdigit(), f"the one program has no ONE_MAX_RUNS: {(r.stdout + r.stderr)[-300:]}")
    most = int(said[0])
    expect(most == 2, f"the settings file says 2 runs at once and the one program was given {most}")
    titles = [f"Stack test at once {i}" for i in range(most + 1)]
    brief = "Stack test at once\nWAIT: 150\nSAY: Waited."
    for title in titles:
        _one(s, f'return await c.ask("start", brief={brief!r}, title={title!r})')
    mine: list[dict] = []
    try:
        end = time.time() + 120
        busy_most = 0
        while time.time() < end:
            runs = _runs(s)
            mine = [r for r in runs if r.get("title") in titles]
            busy = [r for r in runs if r.get("kind") == "agent" and r["state"] in ("starting", "working", "asking", "saving")]
            busy_most = max(busy_most, len(busy))
            expect(len(busy) <= most, f"{len(busy)} runs work at once with ONE_MAX_RUNS={most}")
            waiting = [r for r in mine if r["state"] == "queued" and "already working" in (r.get("queued_because") or "")]
            if len(busy) == most and waiting:
                break
            time.sleep(3)
        else:
            raise Failed(f"never {most} runs working and one waiting (at most {busy_most} worked at once): "
                         + json.dumps([{k: r.get(k) for k in ('title', 'state', 'queued_because')} for r in mine]))
    finally:
        for r in mine:
            if r["state"] not in ("done", "failed", "unfinished", "lost", "refused", "reaped"):
                _one(s, f'return await c.ask("stop", run={r["id"]!r})')


@check("one.run-memory")
def run_memory(s: Stack) -> None:
    """A run that holds more memory than one run may (ONE_RUN_MEMORY_MAX) is ended, with what it
    started, and the program says why."""
    title = "Stack test memory"
    got = _tool(s, "one_start", {"title": title, "brief": f"{title}\n"
                               "RUN: python3 -c \"import time; b = b'x' * (400 << 20); time.sleep(9473)\"\n"
                               "SAY: It should not get here."})
    run = _run_titled(s, title)
    run = _wait_run(s, run["id"], lambda r: r["state"] in ("failed", "done", "unfinished", "lost"),
                    f"the run holding 400 MB was not ended (one_start said: {got[:200]})", 180)
    expect(run["state"] == "failed" and run.get("how") == "over-memory",
           f"the run ended {run['state']} ({run.get('how')}), not for its memory")
    expect("memory" in (run.get("ended_why") or ""), f"the program did not say why: {run.get('ended_why')!r}")
    expect(not _alive(s, "^python3 -c .*9473"), "the process holding the memory is still there")
    shown = _one(s, f'return (await c.ask("run", run={run["id"]!r}, entries=0))["run"].get("ended_why")')
    expect("over the" in (shown or ""), f"the run's own page does not say why: {shown!r}")


@check("one.run-stop")
def run_stop(s: Stack) -> None:
    """Stopping a run with Rouh's one_stop ends everything it started, a detached
    `setsid sleep` included."""
    title = "Stack test stop"
    _tool(s, "one_start", {"title": title, "brief": f"{title}\n"
                         "RUN: setsid -f sleep 7311 </dev/null >/dev/null 2>&1\n"
                         "SAY: A sleep is running by itself."})
    run = _run_titled(s, title)
    end = time.time() + 180
    while time.time() < end and not _alive(s, "^sleep 7311"):
        time.sleep(3)
    expect(_alive(s, "^sleep 7311"), "the run never started its detached sleep")
    r = s.run("worker", "ps -o pid,ppid,sid,args -C sleep")
    expect("7311" in r.stdout, f"no detached sleep to look at: {r.stdout}")
    _wait_run(s, run["id"], lambda r: r["state"] == "idle", "the run did not finish its turn", 120)
    _quiet(s, waiting_for="A sleep is running by itself", limit=60)
    said = _tool(s, "one_stop", {"run": run["id"]})
    expect("Traceback" not in said, f"one_stop: {said[:300]}")
    _wait_run(s, run["id"], lambda r: r["state"] in ("done", "failed", "unfinished", "lost", "reaped"),
              f"the run did not end when stopped (one_stop said: {said[:200]})", 120)
    end = time.time() + 30
    while time.time() < end and _alive(s, "^sleep 7311"):
        time.sleep(2)
    expect(not _alive(s, "^sleep 7311"), "the run was stopped and its detached sleep is still running: "
           + s.run("worker", "ps -o pid,ppid,sid,args -C sleep").stdout)


@check("one.deploy-keeps-runs")
def deploy_keeps_runs(s: Stack) -> None:
    """A deploy that changes the one program starts it again in the worker without taking the
    runs with it: the protected core's signal for the worker moves, as it does when a change to
    the program goes live (guard/rouh_guard/changes.py), `rouh-guard-run` starts the program again
    in place, and a run that was working carries on in the very same process, neither lost nor
    started again. Until 3 November 2026 the worker's container restarted instead, and every
    deploy killed every run in it."""
    title = "Stack test deploy"
    brief = f"{title}\nWAIT: 240\nSAY: Waited."
    _one(s, f'return await c.ask("start", brief={brief!r}, title={title!r})')
    run = _run_titled(s, title)
    run = _wait_run(s, run["id"], lambda r: r["state"] == "working", "the run did not start working", 300)
    # Anchored, so the shell that runs pgrep, whose own command line holds the words, is not found.
    held = f"^[^ ]*python[^ ]* -m one.holder --dir [^ ]*{run['id']} "
    holder = _alive(s, held)
    program = _alive(s, "^python -m one.program")
    expect(holder and program, f"no holder ({holder}) or program ({program}) to watch")
    r = s.run("guard", """python3 - <<'PY'
import json, os
p = os.path.join(os.environ.get("ROUH_GUARD_SIGNAL", "/run/guard-signal"), "state.json")
d = json.load(open(p))
d.setdefault("restart", {})["worker"] = int(d["restart"].get("worker") or 0) + 1
open(p + ".t", "w").write(json.dumps(d))
os.chmod(p + ".t", 0o644)
os.replace(p + ".t", p)
print("bumped", d["restart"])
PY""")
    expect("bumped" in r.stdout, f"the worker's signal could not be moved: {(r.stdout + r.stderr)[-300:]}")
    end = time.time() + 120
    now: list[str] = []
    while time.time() < end:
        now = _alive(s, "^python -m one.program")
        if now and now != program:
            break
        time.sleep(3)
    expect(now and now != program, f"the one program was not started again: {program} then {now}; "
           f"the worker's log: {s.logs('worker', 40)[-800:]}")
    while time.time() < end + 60:
        try:
            _runs(s)  # its socket answers again
            break
        except Failed:
            time.sleep(3)
    after = _wait_run(s, run["id"], lambda r: r["state"] in ("working", "idle", "done", "lost", "failed"),
                      "the program that came back does not know the run", 120)
    expect(after["state"] in ("working", "idle", "done"),
           f"the run did not survive the restart: {after['state']} ({after.get('ended_why')})")
    expect(not int(after.get("restarts") or 0) and not int(after.get("carried") or 0),
           f"the run was started again rather than kept: restarts {after.get('restarts')}, "
           f"carried {after.get('carried')}")
    expect(_alive(s, held) == holder,
           "the run's holder is not the one it had before the restart")
    if after["state"] == "working":
        _one(s, f'return await c.ask("stop", run={run["id"]!r})')


LAST.add("one.deploy-keeps-runs")
LIMIT.update({"one.deploy-keeps-runs": 480})


def _bump_core(s: Stack) -> None:
    r = s.run("guard", """python3 - <<'PY'
import json, os
p = os.path.join(os.environ.get("ROUH_GUARD_SIGNAL", "/run/guard-signal"), "state.json")
d = json.load(open(p))
d.setdefault("restart", {})["core"] = int(d["restart"].get("core") or 0) + 1
open(p + ".t", "w").write(json.dumps(d))
os.chmod(p + ".t", 0o644)
os.replace(p + ".t", p)
print("bumped", d["restart"])
PY""")
    expect("bumped" in r.stdout, f"the core's signal could not be moved: {(r.stdout + r.stderr)[-300:]}")


def _started(s: Stack) -> float:
    try:
        code, body, _ = s.get("/healthz", cookie=False)
    except OSError:
        return 0.0
    if code != 200 or '"ok":true' not in body.replace(" ", ""):
        return 0.0
    return float(json.loads(body).get("started") or 0)


def _back_after(s: Stack, before: float, limit: float = 400) -> None:
    end = time.time() + limit
    while time.time() < end:
        now = _started(s)
        if now and now != before:
            return
        time.sleep(3)
    raise Failed(f"Rouh did not come back after its restart; the core's log: {s.logs('core', 30)[-800:]}")


def _last_wait(s: Stack) -> dict:
    r = s.run("core", "tail -n 1 /data/rouh/deploy-wait/waits.log")
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        raise Failed(f"no wait was written down: {(r.stdout + r.stderr)[-300:]}")


@check("core.deploy-waits-for-answers")
def deploy_waits_for_answers(s: Stack) -> None:
    """No deploy cuts a chat answer (Petar, 3 November 2026): the protected core's signal for the
    core moves while Rouh is in the middle of a slow answer, as it does when a change goes live,
    and `rouh-guard-run` waits (guard/rouh_guard/deploywait.py, rouh/answers_now.py): the answer
    arrives whole, and only then does Rouh start again. A second move, with nothing being
    answered, goes at once."""
    import threading

    # The last sentence of the stand-in model's slow answer (rouh/testing/fake_model.py, SLOW_ANSWER).
    whole = "tell you about each one as I reach it"
    before = _started(s)
    expect(before, "Rouh is not answering its health page before the check")
    got: dict = {}

    def ask() -> None:
        try:
            got["text"], _ = s.say("SLOWLY, the whole list please", 240)
        except Exception as exc:  # noqa: BLE001 - said below
            got["error"] = exc

    talk = threading.Thread(target=ask, daemon=True)
    talk.start()
    end = time.time() + 60
    while time.time() < end:
        r = s.run("core", "cat /data/rouh/deploy-wait/state.json")
        try:
            if json.loads(r.stdout).get("answers"):
                break
        except ValueError:
            pass
        time.sleep(0.5)
    else:
        raise Failed(f"Rouh never counted the answer in progress: {(r.stdout + r.stderr)[-300:]}")
    _bump_core(s)
    talk.join(240)
    expect("error" not in got, f"the answer did not arrive: {got.get('error')}")
    expect(whole in (got.get("text") or ""), f"the answer was cut: {(got.get('text') or '')[-200:]}")
    _back_after(s, before)
    waited = _last_wait(s)
    expect(waited.get("outcome") == "ready" and float(waited.get("waited") or 0) >= 2
           and any(a.get("kind") == "chat" for a in waited.get("answers") or []),
           f"the deploy did not wait for the answer: {waited}")
    # And with nothing in progress, at once.
    before = _started(s)
    began = time.time()
    _bump_core(s)
    _back_after(s, before)
    waited = _last_wait(s)
    expect(waited.get("outcome") == "idle" and float(waited.get("waited") or 99) < 5,
           f"a deploy with nothing in progress waited: {waited}")
    expect(time.time() - began < 300, "Rouh took too long to start again")


LAST.add("core.deploy-waits-for-answers")
LIMIT.update({"core.deploy-waits-for-answers": 900})
