"""A page web_fetch could not read, read in a browser instead.

Petar, 26 September 2026 (fr_16fd2dee6b59), from a chat about a shop in a
video game, where web_fetch could not reach the one wiki page the answer
was on ("url_not_accessible") and the answer was pieced together from search
results instead: "Can you design the system so that if we get an error on we
fetch you try play right browser instead".

How it goes
-----------

web_fetch is Anthropic's, and it runs on Anthropic's side in the middle of the
model's reply: the call, what came back and whatever the model does next are
one streamed response. So the second try cannot wait for the reply to end, by
which time the model has gone on without the page. It is made in the middle:

1. The reply is read as it streams (`brain.py`, `subagent.py`). When a
   web_fetch result closes with an error worth another try, and none of
   Anthropic's own calls in the reply is still waiting for its answer, the
   stream is closed right there, which stops the model too.
2. The reply as far as it got is kept, and a call of Rouh's own is added to
   the end of it: `browser_fetch`, with the address web_fetch was given.
3. That call is answered here, by reading the same address once in a headless
   browser (`browsing.Desk.read`), and the model is asked again with the page
   as the call's result. It carries on from the page as it would have from
   the fetch.

Checked against the real API on 26 September 2026, on Opus 5.5 with thinking,
with the very page from that chat: a reply cut after the failed fetch, with a
call added to its end, is taken, and the model answers out of what the call
returned. It is taken whether or not `browser_fetch` is a declared tool, and
it is not declared: the model is never offered a browser to read with, it is
handed what the browser read.

On the screen the failed fetch keeps its red line and the second try gets a
line of its own under it, with the page it read, or with both reasons when it
failed too. The model is told the same and says it in a few words, so the
answer says it as well, read back later as much as live, and nothing fails
quietly.

What never gets a second try
----------------------------

Only a page that could not be got gets another try: the site turned the
fetcher away or did not answer (`url_not_accessible`), the fetcher was busy
(`too_many_requests`) or broken (`unavailable`), or the page was a kind it
does not read (`unsupported_content_type`). Every other error is web_fetch
refusing on purpose, and a browser is not a way round a refusal:

- `url_not_allowed` is a private address, a page its robots.txt keeps out, or
  an address that looks as if it carries a password or a key;
- `url_not_in_prior_context` is the rule that the model reads only an address
  somebody gave it, which is what stops a page from talking it into sending
  the conversation off inside an address of its own making;
- `max_uses_exceeded` is the limit the reply was given;
- `invalid_tool_input` and `url_too_long` are an address no browser would do
  better with.

An error this file has never heard of is left alone for the same reason. So is
a fetch made by code running on Anthropic's side rather than by the model
(a `caller` other than direct): the code waits for its answer in Anthropic's
sandbox, and cutting the reply there would leave it waiting.

Each address is tried once a turn, and at most `MOST` pages a turn, so a model
reaching for page after page that will not load cannot keep a turn going.

Rouh's own pages are never read from outside
---------------------------------------------

An address on one of Rouh's own names (the installation's public
hosts, `rouhlinks.own`) is not a page of the web, and from outside it is only a
sign-in page. Petar pasted a mail case's address into a chat on 6 October
2026 and this file read it in the headless browser three times over, which
read "Sign in to Rouh" every time. So a web_fetch of one of those addresses,
refused or not (Anthropic refuses them at once, since they are web_fetch's
`blocked_domains`), is cut the same way, and the call added is
`read_rouh_link`, answered by reading the page inside Rouh as the person
(`rouhlinks.read`). It never reaches the browser, whatever happens: with
nothing here to read it inside Rouh, it is left alone.

Why the page is plain text
--------------------------

Handed back as a `search_result` block, the page would be cited the way a
fetched page is, with its number after the words and its link under the
answer. That was tried against the real API the same day and taken out again:
once General's window trims that old result to a placeholder
(`rouh/context_editing.py`), every later request in the chat is refused with
"Invalid search result index in citation", and the chat never answers again.
So the page is text, in the same box as every other page Rouh reads
(`untrusted.py`), the model names the site in the sentence as it does for any
page, and the page's title and address are on its line on the screen.
"""
from __future__ import annotations

import asyncio
import json
import logging
import secrets
from dataclasses import dataclass, field

from . import rouhlinks, untrusted, worklabel
from .browsing import Reading

log = logging.getLogger("rouh.fetchfallback")

#: The call Rouh adds to the end of a reply it cut, and answers itself.
TOOL = "browser_fetch"

#: What web_fetch says when it could not get a page, as against refusing to.
TRY_AGAIN = frozenset({"url_not_accessible", "too_many_requests", "unavailable",
                       "unsupported_content_type"})

#: What each of those is, said to the person, the way the failed fetch's own
#: line says it (`brain._WEB_FAILED`).
FAILED = {
    "url_not_accessible": "the page could not be reached",
    "too_many_requests": "too many at once, so it was turned away",
    "unavailable": "the service was not available",
    "unsupported_content_type": "the page is not something it can read",
}

#: The most pages one turn reads this way.
MOST = 8


def _get(thing, name: str):
    """A field of a block, whether the SDK's object or a plain dict."""
    if isinstance(thing, dict):
        return thing.get(name)
    return getattr(thing, name, None)


@dataclass
class Failure:
    """One web_fetch that failed, waiting for its second try."""

    #: The web_fetch call, as Anthropic numbered it.
    fetch_id: str
    url: str
    code: str
    #: One of Rouh's own addresses, read inside Rouh rather than in a browser
    #: (`rouhlinks.py`).
    own: bool = False
    #: The call Rouh adds for it. An id of the API's shape, new every time,
    #: and new at the end, which is the part the work tree keys a call by.
    call_id: str = field(default_factory=lambda: "toolu_" + secrets.token_hex(12))

    @property
    def tool(self) -> str:
        return rouhlinks.TOOL if self.own else TOOL


class Second:
    """One turn's second tries: the fetches waiting for one, and the
    addresses already read.

    `desk` is the browser desk (`browsing.Desk`), or None where there is no
    browser, in which case every second try says so rather than not happening.
    `links` is the tool registry, which reads an address of Rouh's own inside
    Rouh (`rouhlinks.read`); without it such an address is never tried again.
    """

    def __init__(self, desk, links=None) -> None:
        self.desk = desk
        self.links = links
        self.cfg = getattr(links, "cfg", None) or getattr(desk, "cfg", None)
        self.waiting: list[Failure] = []
        self.tried: set[str] = set()

    def forget(self) -> None:
        """Nothing waiting: a new attempt at a request starts from nothing."""
        self.waiting.clear()

    def note(self, block, content, history=()) -> None:
        """One of Anthropic's results closed in the stream.

        Kept when it is a web_fetch that failed for a reason worth another
        try. `content` is the reply so far and `history` the conversation
        before it, which is where the address is: the result names only the
        call it answers.
        """
        if _get(block, "type") != "web_fetch_tool_result":
            return
        came = _get(block, "content")
        failed = _get(came, "type") == "web_fetch_tool_result_error"
        code = str(_get(came, "error_code") or "") if failed else ""
        fetch_id = str(_get(block, "tool_use_id") or "")
        call = _call(fetch_id, content, history)
        if call is None or not _direct(block) or not _direct(call):
            return
        url = str(_get(_get(call, "input") or {}, "url") or "").strip()
        # One of Rouh's own pages, whatever came back: refused, or a sign-in
        # page read from outside. Read inside Rouh, or not at all, and never
        # in the browser.
        own = bool(url) and rouhlinks.own(url, self.cfg)
        if own and self.links is None:
            return
        if not own and (not failed or code not in TRY_AGAIN):
            return
        if not url or url in self.tried or any(f.url == url for f in self.waiting):
            return
        if len(self.tried) + len(self.waiting) >= MOST:
            log.info("web_fetch could not read %s (%s), and this turn has read %d pages "
                     "in the browser already", url, code, MOST)
            return
        self.waiting.append(Failure(fetch_id, url, code or "read", own=own))
        if own:
            log.info("web_fetch was asked for Rouh's own %s (%s); reading it inside Rouh",
                     url, code or "fetched from outside")
        else:
            log.info("web_fetch could not read %s (%s); reading it in a browser", url, code)

    def due(self, content) -> bool:
        """Whether to stop reading the reply here: a page is waiting for its
        second try, and none of the calls in the reply so far is still waiting
        for its answer. A call to one of Rouh's own tools never is by the time
        a result of Anthropic's arrives, since the API hands those back before
        it runs a fetch asked for beside them; were one ever there, the reply
        is read to its end rather than cut with a call nobody answers."""
        return bool(self.waiting) and not _running(content)

    def calls(self) -> list[dict]:
        """The calls added to the end of the cut reply, one for each page."""
        return [{"type": "tool_use", "id": f.call_id, "name": f.tool, "input": {"url": f.url}}
                for f in self.waiting]

    async def run(self, emit, *, agent_id: str = "") -> list[dict]:
        """Every waiting page read in a browser, all at once, and their results,
        which go back to the model together in one message."""
        waiting, self.waiting = list(self.waiting), []
        self.tried.update(f.url for f in waiting)
        return list(await asyncio.gather(*(self._one(f, emit, agent_id) for f in waiting)))

    async def _one(self, failure: Failure, emit, agent_id: str) -> dict:
        branch = {"agent_id": agent_id} if agent_id else {}
        if failure.own or rouhlinks.own(failure.url, self.cfg):
            return await self._inside(failure, emit, branch)
        said = worklabel.describe_step(TOOL, {"url": failure.url})
        await emit({"type": "tool_start", "id": failure.call_id, "name": TOOL,
                    "input": json.dumps({"url": failure.url}),
                    "what": said["what"], "detail": said["detail"],
                    "where": "rouh", **branch})
        if self.desk is None:
            reading = Reading(url=failure.url, error="there is no browser here")
        else:
            try:
                reading = await self.desk.read(failure.url)
            except Exception as exc:        # a second try must not end the turn
                log.exception("reading %s in the browser failed", failure.url)
                reading = Reading(url=failure.url, error=f"the browser failed ({exc})")
        fetch_said = FAILED.get(failure.code, failure.code)
        if reading.ok:
            log.info("read %s in the browser after web_fetch could not", failure.url)
            summary = "read in a browser instead: " + (reading.title or reading.url)
            results = [{"title": reading.title, "url": reading.url or failure.url}]
            page = (f"Page: {reading.title or '(no title)'}\n"
                    f"Address: {reading.url or failure.url}\n\n{reading.text}")
            content = (
                f"web_fetch could not read {failure.url} ({fetch_said}), so Rouh opened the "
                "same address once in a headless browser, and this is the text that "
                "browser read on the page. Use it the way you would have used the fetch, "
                "and say in a few words, once, that the page was read in a browser because "
                "the usual fetch failed.\n\n"
                + untrusted.wrap(page, untrusted.SOURCES[TOOL]))
        else:
            log.info("the browser could not read %s either: %s", failure.url, reading.error)
            summary = f"both failed: web_fetch said {fetch_said}, and the browser said {reading.error}"
            results = []
            content = (
                f"web_fetch could not read {failure.url} ({fetch_said}), and a second try, "
                "opening the same address in a headless browser, failed too: "
                f"{reading.error}. Tell the person plainly that both tries failed and "
                "what each said, and do not answer as if you had read the page."
                + (" The page is a check for bots, which only a person can pass."
                   if reading.bot_check else ""))
        await emit({"type": "tool_end", "id": failure.call_id, "name": TOOL,
                    "ok": reading.ok, "summary": summary, "results": results,
                    "where": "rouh", **branch})
        return {"type": "tool_result", "tool_use_id": failure.call_id, "content": content,
                **({} if reading.ok else {"is_error": True})}


    async def _inside(self, failure: Failure, emit, branch: dict) -> dict:
        """One of Rouh's own addresses, read inside Rouh as the person (`rouhlinks.read`)."""
        name = rouhlinks.TOOL
        said = worklabel.describe_step(name, {"url": failure.url})
        await emit({"type": "tool_start", "id": failure.call_id, "name": name,
                    "input": json.dumps({"url": failure.url}),
                    "what": said["what"], "detail": said["detail"], "where": "rouh", **branch})
        if self.links is None:
            got = rouhlinks.Got(False, "There is nothing here to read Rouh's own pages with.")
        else:
            got = await rouhlinks.read(self.links, failure.url)
        how = ("Anthropic refused it, as it refuses every address of Rouh's own"
               if failure.code == "url_not_allowed" else
               "from outside it is only a sign-in page")
        content = (
            f"You asked web_fetch for {failure.url}, which is an address of Rouh's own. "
            f"web_fetch never reads those ({how}), and neither does a browser, so Rouh read "
            "it inside itself, as the person, and this is what came back. Use it the way you "
            "would have used the fetch. For a link to Rouh, call read_rouh_link yourself "
            "next time.\n\n" + got.text)
        await emit({"type": "tool_end", "id": failure.call_id, "name": name, "ok": got.ok,
                    "summary": ("read inside Rouh: " + got.title) if got.ok
                    else (got.title or "could not be read"),
                    "results": [{"title": got.title or failure.url, "url": failure.url}]
                    if got.ok else [],
                    "where": "rouh", **branch})
        return {"type": "tool_result", "tool_use_id": failure.call_id, "content": content,
                **({} if got.ok else {"is_error": True})}


def _direct(block) -> bool:
    """Whether a call was the model's own rather than code's on Anthropic's side."""
    caller = _get(block, "caller")
    return caller is None or _get(caller, "type") in (None, "direct")


def _call(fetch_id: str, content, history):
    """The web_fetch call a result answers: in this reply, or, when the fetch
    was asked for beside a call of Rouh's own and ran after it, in the reply
    before."""
    def find(blocks):
        for block in blocks or []:
            if _get(block, "type") == "server_tool_use" and _get(block, "id") == fetch_id:
                return block
        return None

    found = find(content)
    if found is not None:
        return found
    for message in reversed(list(history or [])):
        blocks = message.get("content") if isinstance(message, dict) else None
        if isinstance(blocks, list):
            found = find(blocks)
            if found is not None:
                return found
    return None


def _running(content) -> bool:
    """Whether a call in this reply has no answer in it yet."""
    if any(_get(b, "type") == "tool_use" for b in content or []):
        return True
    asked = {_get(b, "id") for b in content or [] if _get(b, "type") == "server_tool_use"}
    answered = {_get(b, "tool_use_id") for b in content or []
                if str(_get(b, "type") or "").endswith("_tool_result")}
    return bool(asked - answered)
