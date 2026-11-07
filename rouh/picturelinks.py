"""The pictures of a page on the canvas, fetched by the frame as they come into view.

Petar, 7 November 2026, on step 169-05's page: "it loaded, but I had to wait like
30 seconds or more". The page is 144 KB, and it shows 211 screenshots. Until then
every picture a framed page names was put into it as a ``data:`` address
(`pages.with_files`), because the frame is sandboxed and its own requests carry no
sign-in, so a plain reference to a picture could never load. That made the page
16.9 MB of text, sent whole, through the office line and Cloudflare, before the
frame could draw a thing. Rouh built it in 0.2 seconds; the wait was the sending.

So a page Rouh frames for a signed-in person names its pictures by an address of
their own, and the browser fetches each one by itself, in parallel, the ones on
the screen first (``loading="lazy"``), and keeps it for the day.

The address carries its own credential, as a download link beside a task's file
does (`rouh/filelinks.py`): a token signed with the server's secret, naming the
account it was drawn for, its organisation, the task folder the page is in, and
the day it was drawn. One token for all of a page's pictures, and the same one
all day, so a page opened again is drawn from the browser's own copy. It reads
only pictures (`pages.PICTURES`), only inside that one task, by the same rules a
file asked for by its own address is read (`pages.check`), and it is checked
again when it is used: the account must still be a whole, active one of the same
organisation (`views.picture_link`).

The copy a device keeps for offline is still the whole page, its pictures put in
(`X-Rouh-Later`, `offline.js`), and the service worker never lets a page that only
names its pictures replace one (`sw.js`).
"""
from __future__ import annotations

import time
from urllib.parse import quote

from django.core import signing

#: Where a picture is answered (`rouh/web/views.py`, `picture_link`). Open at
#: the gate, because the token is the credential (`rouh/web/gate.py`).
ROUTE = "/pictures/"

#: How many days a token works after the day it was drawn. A page left open
#: overnight still draws a picture scrolled to in the morning.
DAYS = 1

#: How long the browser keeps a picture. A token is the same all day, so a page
#: opened again that day is drawn from the browser's copy.
KEEP_SECONDS = 24 * 3600

#: Sent with every picture. `sandbox` and `default-src 'none'` because an SVG is
#: a document too: opened straight at its address it would otherwise run on
#: Rouh's own origin. `private` so Cloudflare never keeps one.
HEADERS = {
    "Content-Security-Policy": "sandbox; default-src 'none'; img-src data:; style-src 'unsafe-inline'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": f"private, max-age={KEEP_SECONDS}",
}

_SALT = "rouh.picturelinks"


class Refused(Exception):
    """A token that is not one Rouh drew, one that has run out, or a picture outside it."""


def _today() -> int:
    return int(time.time() // 86400)


def token(user_id, org_id, task: str, day: int | None = None) -> str:
    """The credential for every picture inside ``task``, for one account, today."""
    return signing.Signer(salt=_SALT).sign_object(
        {"u": str(user_id), "o": str(org_id), "t": str(task).strip("/"),
         "d": _today() if day is None else int(day)}, compress=True)


def read(raw: str) -> dict:
    """What a token says: its account ``u``, organisation ``o`` and task ``t``."""
    try:
        said = signing.Signer(salt=_SALT).unsign_object(str(raw or ""))
    except signing.BadSignature:
        raise Refused("That is not a picture address Rouh made.") from None
    if not isinstance(said, dict) or not all(isinstance(said.get(k), str) and said.get(k)
                                             for k in ("u", "o", "t")):
        raise Refused("That is not a picture address Rouh made.")
    day = said.get("d")
    if not isinstance(day, int) or not 0 <= _today() - day <= DAYS:
        raise Refused("That picture address has run out. Open the page again.")
    return said


def inside(said: dict, rel: str) -> bool:
    """Whether ``rel``, a path in the workspace, is inside the token's task."""
    return str(rel).startswith(said["t"] + "/")


def linker(who, page: str):
    """For `pages.read`: the address of each picture the page at ``page`` names,
    for ``who``, or None for one outside the page's own task."""
    from .steps import task_part

    folder = str(page).strip("/").rsplit("/", 1)[0] if "/" in str(page).strip("/") else ""
    task = task_part(folder)
    if not task:
        return None
    signed = token(who.user_id, who.org_id, task)

    def address(rel: str) -> str | None:
        if not str(rel).startswith(task + "/"):
            return None
        return ROUTE + signed + "/" + quote(str(rel), safe="/")

    return address
