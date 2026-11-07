"""A stand-in for systemctl, for the tests that deploy the one program.

`one/deploy/update.sh` ends by restarting the service and waiting for the
program to answer again. A test cannot restart the real `one.service` on the
machine it is running on, and a test that never restarts anything cannot prove
the thing that matters: that the version on the mark changes, by itself, to the
version the program is now serving.

So the service in these tests is a one program the fixtures started themselves,
and this is what "restart" means for it: stop that process, start it again from
the same checkout with the same environment, and write down the new one's id so
the next restart and the end of the test can find it. Everything else systemd
would be asked is answered with a shrug, because the script only ever asks for
a restart.

The plan - what to start, where, with what, and where to write its output - is
one JSON file, written by the fixture that started the program in the first
place, so the process that comes back is the same process in every way the
tests can see.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time


def stop(pidfile: str) -> None:
    try:
        pid = int(open(pidfile).read().strip())
    except (OSError, ValueError):
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    for _ in range(100):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.1)
    # A program that will not go quietly.
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def start(plan: dict) -> int:
    log = open(plan["log"], "a")
    process = subprocess.Popen(
        plan["argv"], cwd=plan["cwd"], env=plan["env"],
        stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
    )
    with open(plan["pidfile"], "w") as fh:
        fh.write(str(process.pid))
    return process.pid


def main() -> int:
    plan = json.load(open(sys.argv[1]))
    verb = sys.argv[2] if len(sys.argv) > 2 else ""
    if verb != "restart":
        return 0
    stop(plan["pidfile"])
    start(plan)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
