"""Owner marks filled in on every page and answer Rouh's own views give.

Text that names the owner says so with a mark (`‹owner›`, `‹his›`, ... in
`rouh/owner.py`), and the mark is filled in where the text leaves Rouh
(SETUP.md). A model's request, the page's socket, a Telegram message and a
letter each fill in their own; this is the last safety net for the rest: an
HTML page, a JSON answer or plain text from one of Rouh's own views that still
carries a mark has it filled in here, for the person signed in, or for the
installation's owner when the reader is a guest or nobody.

It costs nothing on an answer without a mark, which is nearly every one: the
body is looked at for the mark's first character (or its JSON escape) and
handed back untouched when it is not there. Streamed answers - files, a task's
own pages - and compressed ones are left as they are.
"""
from __future__ import annotations

import asyncio
import html

from asgiref.sync import iscoroutinefunction, markcoroutinefunction

from rouh import owner

#: The kinds of answer a mark is filled in on.
KINDS = ("text/html", "application/json", "text/plain")

_OPEN = owner.OPEN.encode("utf-8")
_ESCAPED = b"\\u2039"


def _carries_marks(response) -> bool:
    if getattr(response, "streaming", False) or response.get("Content-Encoding"):
        return False
    kind = str(response.get("Content-Type") or "").lower()
    if not kind.startswith(KINDS):
        return False
    body = response.content
    return _OPEN in body or (kind.startswith("application/json") and _ESCAPED in body)


def _reader(request):
    """Whose words these are: the signed-in person, or None for a guest or nobody."""
    user = getattr(request, "user", None)
    if user is None or not getattr(user, "is_authenticated", False) or getattr(user, "is_guest", False):
        return None
    return str(user.pk)


def fill(request, response):
    """The response with every mark in its body filled in for its reader."""
    kind = str(response.get("Content-Type") or "").lower()
    who = _reader(request)
    body = response.content
    if kind.startswith("application/json"):
        new = owner.say_bytes(body, who)
    else:
        charset = getattr(response, "charset", None) or "utf-8"
        try:
            text = body.decode(charset)
        except (LookupError, UnicodeDecodeError):
            return response
        said = owner.words(owner.resolve(who))
        if kind.startswith("text/html"):
            said = {mark: html.escape(words) for mark, words in said.items()}
        new = owner.say(text, who, said=said).encode(charset)
    if new is not body and new != body:
        response.content = new
        if response.has_header("Content-Length"):
            response["Content-Length"] = str(len(new))
    return response


class OwnerMarks:
    """Every mark left in a page or an answer, filled in for whoever reads it."""

    sync_capable = True
    async_capable = True

    def __init__(self, get_response):
        self.get_response = get_response
        self._async = iscoroutinefunction(self.get_response)
        if self._async:
            markcoroutinefunction(self)

    def __call__(self, request):
        if self._async:
            return self._acall(request)
        response = self.get_response(request)
        return fill(request, response) if _carries_marks(response) else response

    async def _acall(self, request):
        response = await self.get_response(request)
        if not _carries_marks(response):
            return response
        # Reading who the owner is may touch the database: off the event loop.
        return await asyncio.to_thread(fill, request, response)
