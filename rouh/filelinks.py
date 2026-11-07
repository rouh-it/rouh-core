"""Download links for a task's working files, pressed inside the task frame.

Petar, 29 September 2026, on a bank's PDF under task 18-03: "I have no way to
download it. Make a download button". Then, once it worked from Rouh's top
bar: "I like the old place of the button", which was under the file's name,
and a button on the file's own line on the task's page as well.

Both of those are inside the frame, and the frame is sandboxed with an origin
of its own, so the browser sends no sign-in with a request the frame makes
(`pages.follow_script`). Handing the press up and starting the download from
Rouh's page by script was tried first, and Petar's browser did nothing with
it, though the server sent the file every time. A browser saves what the
person pressed a link for, so the link has to work from inside the frame.

So the link carries its own credential: a token Django signs with the
server's secret, naming the account it was drawn for, its organisation, the
object's folder and the file inside it, good for `LASTS` seconds. It is drawn
only into a page a signed-in person asked for, and it is checked again when it
is used: the account must still be a whole, active one of the same
organisation, and the file must pass every rule the reading view opens it by
(`objectindex.doc_download`). The task frame is given `allow-downloads` and
nothing else new (`canvasLoad` in app.js).
"""
from __future__ import annotations

from pathlib import PurePosixPath
from urllib.parse import quote

from django.core import signing

#: Where a download link is answered (`rouh/web/views.py`, `file_link`). Open
#: at the gate, because the token is the credential (`rouh/web/gate.py`).
ROUTE = "/files/"

#: How long a link drawn into a page works. A task's page is read again every
#: time it is opened, so a link is never older than the page it is on; half a
#: day covers a page left open all day.
LASTS = 12 * 3600

_SALT = "rouh.filelinks"


class Refused(Exception):
    """A link that is not one Rouh drew, or one that has run out."""


def link(who, rel: str, doc: str) -> str:
    """The address that downloads ``doc`` of the object at ``rel``, for ``who``.

    The file's name is on the end so the address reads as the file; the token
    decides everything and the name is never read back.
    """
    token = signing.dumps({"u": str(who.user_id), "o": str(who.org_id),
                           "r": str(rel), "d": str(doc)}, salt=_SALT, compress=True)
    return ROUTE + token + "/" + quote(PurePosixPath(str(doc)).name, safe="")


def read(token: str) -> dict:
    """What a link says: its account ``u``, organisation ``o``, folder ``r``
    and file ``d``. Refused when it was not signed here or has run out."""
    try:
        said = signing.loads(str(token or ""), salt=_SALT, max_age=LASTS)
    except signing.SignatureExpired:
        raise Refused("That download link has run out. Open the file again.") from None
    except signing.BadSignature:
        raise Refused("That is not a download link Rouh made.") from None
    if not isinstance(said, dict) or not all(isinstance(said.get(k), str) and said.get(k)
                                             for k in ("u", "o", "r", "d")):
        raise Refused("That is not a download link Rouh made.")
    return said
