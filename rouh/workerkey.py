"""The key a worker in another container shows Rouh, in place of being on the same machine.

Rouh's internal addresses (`/internal/...`: a job's note to the owner, the tools a run uses, its
agent instructions, a task's status) answer only a caller on this machine (`web/common.py`,
`from_this_machine`). On the server that is every run. In the containers every Rouh instance runs
(deploy/stack/compose.yml), the runs are in the worker, another container, so until 29 October
2026 none of them could reach Rouh at all (CONTAINERS.md, `callbacks.*`).

So Rouh makes one key at its start and writes it, with the address the worker reaches it at,
into the volume the two share (`ROUH_WORKER_KEY_FILE`, /run/one/rouh-worker.json in the stack,
readable by the worker's user only). A caller that shows it in `X-Rouh-Worker-Key` is let in as
one on this machine would be, and nothing more: it still may not have come through a proxy, and
the relay still answers 404 to every internal address (`rouh/relay.py`). The key is not a model
key or anybody's login: it opens exactly what being on the same machine opens on the server.

    {"url": "http://core:8021", "token": "..."}

The callers (`rouh/worker_mcp.py`, `bin/rouh-task`, `bin/rouh`, `one/agents.py`) are standard
library only and read the same file the same way, by the same name.
"""
from __future__ import annotations

import hmac
import json
import logging
import os
import secrets

log = logging.getLogger(__name__)

HEADER = "X-Rouh-Worker-Key"
#: Where the key is kept, or "" where there is no worker in another container (the server).
PATH = os.environ.get("ROUH_WORKER_KEY_FILE", "").strip()

_cache: dict = {"mtime": None, "token": ""}


def ensure(path: str = "") -> bool:
    """Make the key once, at Rouh's start, when there is a worker to hand it to. Kept across
    restarts, so a run already going keeps reaching Rouh; made again only when it is missing."""
    path = path or PATH
    if not path or not os.path.isdir(os.path.dirname(path) or "."):
        return False
    url = os.environ.get("ROUH_INTERNAL_URL", "").strip() or f"http://127.0.0.1:{os.environ.get('ROUH_PORT', '8021')}"
    try:
        with open(path, encoding="utf-8") as fh:
            said = json.load(fh)
        if said.get("token") and said.get("url") == url:
            return True
    except (OSError, ValueError):
        pass
    tmp = f"{path}.new.{os.getpid()}"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump({"url": url, "token": secrets.token_urlsafe(32)}, fh)
    os.replace(tmp, path)
    log.info("made the key the worker shows Rouh, in %s", path)
    return True


def token(path: str = "") -> str:
    path = path or PATH
    if not path:
        return ""
    try:
        mtime = os.stat(path).st_mtime
    except OSError:
        return ""
    if _cache["mtime"] != mtime:
        try:
            with open(path, encoding="utf-8") as fh:
                _cache["token"] = str(json.load(fh).get("token") or "")
        except (OSError, ValueError):
            _cache["token"] = ""
        _cache["mtime"] = mtime
    return _cache["token"]


def shown(request) -> bool:
    """Whether this request carries the worker's key."""
    got = request.headers.get(HEADER, "")
    want = token()
    return bool(got and want) and hmac.compare_digest(got.encode(), want.encode())
