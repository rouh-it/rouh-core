"""Where what Rouh wrote came from: a number after each thing, and the list.

Petar, 24 September 2026 (fr_999dc7d6c2b2): "After web search and research as
a whole, every source needs to be listed in a sources section. Ideally
different items should have footnote numbers so we know specifically which
thing was found at which url."

The model already says which page each thing came from, in a form nobody could
see. When it writes out of a web search, or out of a page it read with
web_fetch, Anthropic's API splits the answer into text blocks and hangs the
page each block came from on that block as a citation: the address and the
title for a search result, and the document it read for a fetched page. Rouh
streamed the words and dropped the rest, so an answer about today's prices
said where they came from out loud, once, and nowhere on the screen.

So the footnotes are worked out here, from those citations, and never asked of
the model. A number goes after every block that cites a page, the pages are
numbered in the order they are first cited, and the answer ends with the list
the numbers point at. The model cannot leave a page out, cannot number one
wrong, and never has to write an address or a "[1]" into words that are then
read aloud. Only the pages it cited are listed: a result that came back from a
search and was not used for anything is not a source of anything.

Both halves are plain Markdown, `[1]` after the words and a "Sources" line over
a numbered list of links, because that is what the page draws them from
(`footnotes` in app.js), what copying an answer carries away with it, and what
a chat's own record keeps.

One numbering per response from the API, which is one stored message. The
live stream (`brain.py`) and a conversation read back later (`memory.py`) walk
the same blocks through the same `Numbering`, so an answer carries the same
numbers after a reload as it did while it was being written.
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit

#: The line over the list. The page finds the list by it, so it is one word
#: and never changes.
HEADING = "Sources"

#: What a title may not carry into `[title](address)`: the brackets would end
#: the link early, and the marks would turn half of it bold or into code.
_UNSAFE_TITLE = re.compile(r"[\[\]*`_]")


def _get(thing, name: str):
    """A field of a block, whether the SDK's object or the stored dict."""
    if isinstance(thing, dict):
        return thing.get(name)
    return getattr(thing, name, None)


def _web(url) -> bool:
    return isinstance(url, str) and url.startswith(("https://", "http://"))


def address(url: str) -> str:
    """A URL as a Markdown link can hold it: no space and no bracket inside."""
    return (url.strip().replace(" ", "%20").replace("(", "%28").replace(")", "%29"))


def where(url: str) -> str:
    """The site and the path, short: what a link is called when it has no title."""
    parts = urlsplit(url)
    said = (parts.netloc.removeprefix("www.") + parts.path).rstrip("/")
    return said[:80] or url[:80]


#: The longest a page's name is shown. Some pages call themselves a paragraph.
LONGEST_TITLE = 140


def title_of(title, url: str) -> str:
    """A page's name as a link can carry it: one line, no marks, not too long."""
    said = " ".join(_UNSAFE_TITLE.sub(" ", str(title or "")).split())
    if len(said) > LONGEST_TITLE:
        said = said[:LONGEST_TITLE].rsplit(" ", 1)[0].rstrip(" ,;:-|") + "…"
    return said or where(url)


class Numbering:
    """The pages one response cites, numbered in the order they are first cited."""

    def __init__(self) -> None:
        #: (address, title), in the order of their numbers.
        self.pages: list[tuple[str, str]] = []
        self._numbers: dict[str, int] = {}
        #: (title, address) of every page web_fetch read in this response. A
        #: fetched page's citations name it by its document title, not by its
        #: address, and this is where the address is.
        self._read: list[tuple[str, str]] = []

    def read(self, block) -> None:
        """Note a page web_fetch brought back, from its `web_fetch_tool_result`."""
        got = _get(block, "content")
        if _get(got, "type") != "web_fetch_result":
            return
        url = _get(got, "url")
        if _web(url):
            self._read.append((str(_get(_get(got, "content"), "title") or ""), url))

    def cite(self, block) -> str:
        """The marker for one text block: "[1]", "[1][3]", or "" if it cites no page."""
        numbers: list[int] = []
        for citation in _get(block, "citations") or []:
            page = self._page(citation)
            if page is None:
                continue
            url, title = page
            n = self._numbers.get(url)
            if n is None:
                self.pages.append((url, title))
                n = self._numbers[url] = len(self.pages)
            elif title and not self.pages[n - 1][1]:
                self.pages[n - 1] = (url, title)
            if n not in numbers:
                numbers.append(n)
        return "".join(f"[{n}]" for n in numbers)

    def _page(self, citation) -> tuple[str, str] | None:
        kind = _get(citation, "type")
        if kind in ("web_search_result_location", LUNA_CITATION):
            # A search result Claude wrote from, or a page Luna searched or
            # opened: both name the page by its address and its title.
            url = _get(citation, "url")
            return (url, str(_get(citation, "title") or "")) if _web(url) else None
        if kind == "char_location":
            # A page read with web_fetch. Nothing else here is ever cited this
            # way: a file the person attaches goes to the model without
            # citations turned on, so a document citation is a fetched page.
            title = str(_get(citation, "document_title") or "")
            for read_title, url in self._read:
                if title and read_title == title:
                    return url, read_title
            if len(self._read) == 1:
                return self._read[0][1], self._read[0][0] or title
        return None

    def listing(self) -> str:
        """The Sources list, as Markdown under a blank line, or "" if nothing was cited."""
        if not self.pages:
            return ""
        rows = [f"{n}. [{title_of(title, url)}]({address(url)})"
                for n, (url, title) in enumerate(self.pages, 1)]
        return "\n\n" + HEADING + "\n" + "\n".join(rows)


#: How a page Luna wrote from is kept on the text it wrote from it: OpenAI's own
#: name for the annotation, with its address and its title (`rouh/luna.py`).
#: Anthropic's API refuses a citation of any type it did not make, and a
#: citation of a type it did make needs the encrypted index only it can write,
#: so these are kept in a type of their own and taken off before a chat goes
#: back to Claude (`for_anthropic`).
LUNA_CITATION = "url_citation"


def for_anthropic(messages: list) -> list:
    """A window with Luna's citations taken off, for a request to Anthropic.

    Only the citations: the words stay, and so do their footnotes, which are
    worked out again from the stored message whenever it is drawn. The very
    same list comes back when there are none, which is every chat Claude alone
    has answered, so for those this is a walk over the list and nothing else.
    """
    out = None
    for i, message in enumerate(messages):
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, list) or message.get("role") != "assistant":
            continue
        kept = []
        changed = False
        for block in content:
            cites = block.get("citations") if isinstance(block, dict) else None
            if isinstance(cites, list) and any(
                    isinstance(c, dict) and c.get("type") == LUNA_CITATION for c in cites):
                theirs = [c for c in cites
                          if not (isinstance(c, dict) and c.get("type") == LUNA_CITATION)]
                block = {k: v for k, v in block.items() if k != "citations"}
                if theirs:
                    block["citations"] = theirs
                changed = True
            kept.append(block)
        if changed:
            if out is None:
                out = list(messages)
            out[i] = {**message, "content": kept}
    return messages if out is None else out


def footnoted(blocks) -> str:
    """One stored answer's words, with its footnotes and its Sources list.

    What the page is given for an answer read back out of the history, and
    the same text the stream wrote while it was live. Pieces of one run of
    text are joined as they were written, because the API splits a sentence
    wherever a citation starts or ends; text either side of a tool call is two
    paragraphs, because on the live screen it was two.
    """
    if isinstance(blocks, str):
        return blocks.strip()
    numbering = Numbering()
    out: list[str] = []
    apart = False
    for block in blocks or []:
        kind = _get(block, "type")
        if kind == "text":
            words = str(_get(block, "text") or "")
            if apart and out and words.strip():
                out.append("\n\n")
                words = words.lstrip()
            out.append(words + numbering.cite(block))
            apart = False
            continue
        if kind == "web_fetch_tool_result":
            numbering.read(block)
        apart = True
    return ("".join(out).strip() + numbering.listing()).strip()


def footnoted_pieces(blocks, cuts) -> list[str]:
    """`footnoted`, cut at the blocks numbered in `cuts`: one piece before each
    cut and one after the last, `len(cuts) + 1` in all.

    For an answer drawn back with the lines of its tool calls between its
    words (`memory._parts`), each cut being a call that has a line. The pages
    are numbered across the whole answer, as they were live, and the Sources
    list goes under its last words.
    """
    if isinstance(blocks, str):
        blocks = [{"type": "text", "text": blocks}]
    at = set(cuts)
    numbering = Numbering()
    pieces: list[list[str]] = [[]]
    apart = False
    for i, block in enumerate(blocks or []):
        if i in at:
            pieces.append([])
            apart = False
            continue
        kind = _get(block, "type")
        if kind == "text":
            words = str(_get(block, "text") or "")
            out = pieces[-1]
            if apart and out and words.strip():
                out.append("\n\n")
                words = words.lstrip()
            out.append(words + numbering.cite(block))
            apart = False
            continue
        if kind == "web_fetch_tool_result":
            numbering.read(block)
        apart = True
    said = ["".join(piece).strip() for piece in pieces]
    listing = numbering.listing()
    if listing:
        last = max((k for k, words in enumerate(said) if words), default=len(said) - 1)
        said[last] = (said[last] + listing).strip()
    return said


#: Where a Markdown answer's own Sources list starts: a line that says only
#: "Sources", as a heading, in bold or with a colon, and a numbered line under it.
_LISTED = re.compile(r"(?im)^[ \t]*(?:#{1,6}[ \t]*)?(?:\*\*)?sources:?(?:\*\*)?:?[ \t]*\n+(?=[ \t]*\d{1,3}[.)][ \t])")


def split_sources(text: str) -> tuple[str, str]:
    """A Markdown answer, and the Sources list at its end, apart.

    ("the words", "Sources\\n1. [..](..)"), or (text, "") when it has no list.
    For whatever shortens an answer or says it out loud: the list is kept
    whole or left out whole, never cut half way down.
    """
    text = str(text or "")
    found = None
    for found in _LISTED.finditer(text):
        pass
    if found is None:
        return text, ""
    return text[:found.start()].rstrip(), text[found.start():].strip()
