"""The guard service: ``rouh-guard serve`` (guard/README.md).

It runs in a container of its own on the base image, with the protected core's files read-only
at /opt/rouh-guard (the guard-bin volume), and it is the only part of a Rouh that the Rouh's own
code cannot change. It answers the changes contract on the socket in the guard-run volume
(``server.py``), which only the core mounts.

Settings, all from the stack file:

    ROUH_GUARD_SOCKET   the socket, /run/guard/guard.sock
    ROUH_GUARD_STATE    the guard's own volume, /guard: undo points and their history
    ROUH_GUARD_SIGNAL   what the start scripts read, /run/guard-signal (state.json)
    ROUH_APP_DIR        the Rouh's code, /code
    ROUH_GUARD_UPSTREAM the Creator Rouh only: where a checked change is pushed (upstream.py);
                        blank in every Rouh instance, and then nothing is pushed anywhere
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys

from . import VERSION
from .server import Server


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s guard %(message)s", stream=sys.stdout)
    log = logging.getLogger("rouh-guard")
    sock = os.environ.get("ROUH_GUARD_SOCKET", "/run/guard/guard.sock")
    changes = doctor = upstream = None
    try:
        from . import changes as changes_mod
        from . import doctor as doctor_mod
        from . import upstream as upstream_mod
    except ImportError:
        changes_mod = doctor_mod = upstream_mod = None
    if changes_mod is not None:
        changes = changes_mod.Changes.from_environment()
        doctor = doctor_mod.Doctor(changes)
        upstream = upstream_mod.Upstream(changes, doctor)
    server = Server(sock, changes=changes, doctor=doctor, upstream=upstream)
    log.info("the protected core %s starts", VERSION)

    async def run() -> None:
        loop = asyncio.get_running_loop()
        stop = asyncio.Event()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, stop.set)
        tasks = [asyncio.create_task(server.serve())]
        if changes is not None:
            await changes.start()
        if doctor is not None:
            tasks.append(asyncio.create_task(doctor.watch()))
        if upstream is not None and upstream.on:
            log.info("this is the Creator Rouh: a checked change is pushed to %s once it has run healthy", upstream.url)
            tasks.append(asyncio.create_task(upstream.watch()))
        await stop.wait()
        for t in tasks:
            t.cancel()

    asyncio.run(run())
    return 0
