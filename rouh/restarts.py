"""Whether Rouh went away on purpose, said to the page that comes back.

Petar, 27 October 2026 (fr_4ba66bbb733a): "make sure all upgrades and changes
we do go through evolving, not reconnecting". The page says Evolving when the
socket closes with 1012, which is uvicorn going down on a deploy, but a page
that never saw that close - a phone asleep through the deploy, a tab in the
background, a page opened while Rouh was down - said Reconnecting, and after
it Alive, as if the person's own connection had been the trouble.

So every Rouh says two things about itself, on the handshake and on
`/healthz`, and the page that comes back judges the gap from them
(`bootChanged` in app/socket.js):

- ``started``: when this process started, which is different after every
  restart and the same for every connection to one process.
- ``planned``: whether the process before it stopped on purpose. A stop that
  runs the lifespan's shutdown (systemd's restart on a deploy, Rouh updating
  itself, a package upgrade restarting the service) leaves a mark in the data
  folder as it goes; a crash or a kill leaves none. The next start reads the
  mark and takes it away.
"""
from __future__ import annotations

import json
import logging
import os
import time

log = logging.getLogger(__name__)

#: When this process started, in milliseconds, as the page compares it.
STARTED = int(time.time() * 1000)

#: Whether the process before this one stopped on purpose. Read once, at start.
PLANNED = False

_NAME = "stopped-on-purpose.json"


def _mark_path() -> str:
    from rouh.config import config

    return os.path.join(config.data_dir, _NAME)


def begin() -> None:
    """Read, and take away, the mark the process before this one left as it stopped."""
    global PLANNED
    path = _mark_path()
    try:
        with open(path, encoding="utf-8") as f:
            said = json.load(f)
    except FileNotFoundError:
        PLANNED = False
        return
    except (OSError, ValueError):
        said = {}
    PLANNED = True
    log.info("the Rouh before this one stopped on purpose (%s)", said.get("at", "at a time it did not say"))
    try:
        os.remove(path)
    except OSError:
        log.warning("could not take away %s", path)


def stopping() -> None:
    """Leave the mark that says this process is going on purpose. First, before anything can hang."""
    try:
        path = _mark_path()
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "pid": os.getpid(),
                       "started": STARTED}, f)
        os.replace(tmp, path)
    except OSError:
        log.warning("could not leave the mark that Rouh stopped on purpose", exc_info=True)


def said() -> dict:
    """The two words for the handshake and `/healthz`."""
    return {"started": STARTED, "planned": PLANNED}
