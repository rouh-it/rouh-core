"""Which commit of the one program is serving, and which one is waiting for it.

This is the **one** mark in the top bar, the right of the two. The other one is
Rouh's own (`rouh_version.py`), and the reading they share is in
`versions.py`.

On 16 September Rouh was deployed at f4eb8a4, which is the commit that taught
the one program to put a run out of the way. The one program's own checkout,
``/srv/one/app``, was still at 5d1d755 and knew nothing about it. Two programs,
two checkouts, two deploys, and nothing on any screen said they had come apart.
The only sign was an error, in the browser, when somebody archived a run: the
button was there because Rouh had shipped it, and the program behind it had
never heard of it.

This is what answers that before the button is pressed. Two commits:

* **running** - the commit the program serving right now says it was built from,
  asked down its own socket every time a page connects. Not read from a file, not
  compiled into the page: the point is to catch a program that is not the code
  beside it, and only the program can say. A program too old to report its commit
  has its own checkout read instead, so both sides of the comparison show a real
  commit rather than the word unknown for one of them.
* **available** - the commit ``origin/main`` is at in **the one program's own
  checkout**, ``/srv/one/app``. That is the clone a deploy of the one program
  fetches into and fast-forwards, so it is what the next deploy would serve.

Both halves therefore come out of the same clone of the repository. They used to
not: available was read out of Rouh's checkout, ``/var/www/rouh/app``, which
is a different service's copy that a deploy of Rouh moves. The running commit
of one program and the newest commit of another are not two versions of one
thing, so they could never agree, and a Rouh deploy made this mark announce an
update for a program that had not changed at all.

``state`` is the one word the page acts on, and `versions.compare` says what each
of ``update``, ``same``, ``off`` and ``unknown`` means. A program whose checkout
is ahead of it only under ``workspace/`` is ``same``: a deploy of that moves the
files and restarts nothing, so there is nothing for the button to do.

A Rouh that has never been paired with the program gets ``None`` and shows no
mark at all: there is no program here to be behind.
"""
from __future__ import annotations

import asyncio
import logging

from . import versions
from .config import config
from .one_client import OneClient, OneRefused, OneUnavailable

log = logging.getLogger("rouh.one_version")

#: The budget for the whole answer, shared with Rouh's own mark.
SECONDS = versions.SECONDS


def repo() -> str:
    """The checkout to read the available commit out of.

    The one program's own, ``config.one_app_dir`` (``/srv/one/app``): it is the
    clone its service is started from and the clone a deploy of it fetches into,
    so what ``origin/main`` is at there is exactly what the next deploy would
    serve. Reading Rouh's checkout instead, which is what this used to do,
    compares one service's running commit against another service's copy of the
    repository.

    ``ROUH_ONE_REPO`` points it somewhere else, which is what a machine that
    keeps the program's code somewhere unusual needs.
    """
    return config.one_repo or config.one_app_dir


def available(where: str | None = None) -> dict[str, str]:
    """The commit waiting in the one program's own checkout."""
    return versions.available(where or repo())


def running_commit(where: str | None = None) -> str:
    """The commit the one program's own checkout is standing on.

    This is the fallback for a program too old to say. Until 16 September the
    hello carried no commit at all, so every program that has not yet been
    deployed once since then answers "who are you" with a version and nothing
    else, and the panel said "commit unknown" for the one side of the comparison
    a person most wants to look at.

    The checkout is where that program's service is started from, so the commit
    it is standing on is the commit the process was started from, unless somebody
    has moved the checkout without restarting - which is exactly what a deploy
    does, for the few seconds between the two. That is a better answer than no
    answer, and the program's own word is still preferred whenever it has one.
    """
    return versions.head_commit(where or config.one_app_dir or "")


async def running(client: OneClient) -> dict[str, str] | None:
    """What the program serving right now says it is, or None if it did not say.

    One connection, one hello, closed again. The hello is the program's own
    answer to "who are you", so this needs no new message. The version it reports
    is carried along for the log and for `Hub.on_hello`, and the commit is what
    the mark compares.
    """
    try:
        hello = await client.identify()
    except (OneUnavailable, OneRefused) as exc:
        log.debug("the one program did not say which version it is: %s", exc)
        return None
    except Exception:
        log.exception("asking the one program which version it is failed")
        return None
    commit = versions.short(str(hello.get("commit") or ""))
    if not commit:
        commit = await asyncio.to_thread(running_commit)
    return {"version": str(hello.get("version") or ""), "commit": commit}


async def snapshot(client: OneClient) -> dict | None:
    """Everything the mark needs, or None when there is no program to report on.

    Never raises and never takes longer than `SECONDS`: this is called while a
    page is connecting, and a page that will not open because git was slow is a
    worse outcome than a page with no mark on it. Rouh's own mark is read at
    the same time rather than after this one, so neither holds up the other.
    """
    if not client.configured():
        return None
    try:
        return await asyncio.wait_for(_snapshot(client), SECONDS)
    except asyncio.TimeoutError:
        log.warning("the one program's version took longer than %ss to work out", SECONDS)
        return {"service": "one", "state": "off", "running": None,
                "available": {"commit": "", "ref": ""}}
    except Exception:
        log.exception("working out the one program's version failed")
        return None


async def _snapshot(client: OneClient) -> dict:
    now, ready = await asyncio.gather(running(client),
                                      asyncio.to_thread(available))
    # Off the loop, because telling whether only content is newer asks git,
    # and inside the same budget as the rest of this answer.
    return await asyncio.to_thread(versions.compare, now, ready, "one", repo())
