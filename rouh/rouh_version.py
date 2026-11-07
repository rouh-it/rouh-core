"""Which commit of Rouh is serving, and which commit its checkout has waiting.

This is the **rouh** mark in the top bar, the left of the two. The other one,
beside it, is the one program's (`one_version.py`), and the reading they share is
in `versions.py`. There are two marks because there are two services:

* Rouh is the systemd unit ``rouh``, deployed from ``/var/www/rouh/app``,
  serving the page the marks are drawn on.
* The one program is the systemd unit ``one``, deployed from ``/srv/one/app``.

Until 16 September the top bar compared one against the other: the one program's
running commit against the newest commit in Rouh's checkout. Two programs, two
checkouts, one comparison, and the two numbers were never numbers of the same
thing. Each mark now reads both of its halves out of the one checkout its own
service is deployed from.

The two commits on this mark:

* **running** - the commit Rouh is answering from. It is the one
  `version.get_version` reports, which is read once at startup out of
  ``/var/www/rouh/app``, so it stays the commit this process was started at
  even after a deploy has moved the checkout underneath it. There is exactly one
  notion of "the running build" in Rouh and this is it: a second reader that
  could disagree with what the assistant says out loud would be worse than no
  mark.
* **available** - the commit ``origin/main`` is at in that same checkout. That is
  what a deploy of Rouh would fast-forward onto and start from. When everything
  newer than the running commit is under ``workspace/``, which a deploy moves
  without restarting anything, the running commit is the newest code there is
  and the mark says Rouh is current (`versions.only_content`).

There is no ``off`` state here. Rouh is the thing serving the page the mark is
drawn on, so it is running by definition; a Rouh that is not running has no
page to say so on.
"""
from __future__ import annotations

import asyncio
import logging

from . import versions
from .config import config
from .version import REVISION, UNKNOWN, get_version

log = logging.getLogger("rouh.rouh_version")


def repo() -> str:
    """The checkout Rouh itself is deployed from."""
    return config.app_dir


def running() -> dict[str, str]:
    """The commit Rouh is answering from.

    `version.get_version` is the same answer `server_health` gives and the same
    one the assistant says when asked which build it is on. It is worked out once
    and kept, so it stays the commit this process started at even after a deploy
    has moved the checkout under it.
    """
    commit = get_version().get("short_sha") or ""
    return {"commit": "" if commit == UNKNOWN else commit}


def _snapshot() -> dict:
    where = repo()
    return versions.compare(running(), versions.available(where), "rouh", where)


async def snapshot() -> dict:
    """Everything the rouh mark needs. Never raises, and never takes longer
    than `versions.SECONDS`.

    This is read while a page is connecting. A page that will not open because
    git was slow is a worse outcome than a page with one mark missing from it,
    and the one program's mark is read at the same time rather than after this
    one, so neither can hold up the other.
    """
    try:
        return await asyncio.wait_for(asyncio.to_thread(_snapshot), versions.SECONDS)
    except asyncio.TimeoutError:
        log.warning("Rouh's own version took longer than %ss to work out",
                    versions.SECONDS)
    except Exception:
        log.exception("working out which build of Rouh is running failed")
    # Git is the half that was slow, so nothing here may touch it again: this
    # says what is running out of what was read at import and leaves the other
    # half empty, which the page shows as a commit it could not compare.
    return versions.compare({"commit": REVISION}, {"commit": "", "ref": ""}, "rouh")
