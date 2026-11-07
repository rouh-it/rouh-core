"""Slides: reading a Google Slides deck slide by slide, with its speaker notes.

Drive's own export of a deck is one run of text with no slide numbers, the speaker notes run into
the slides' words, which is all Rouh could read of a deck until night 27 (30 October 2026, task 94):
"what does slide 40 say" had no answer. The Slides API sends each slide on its own, with the id
that opens it in Google Slides and its notes page, and this reads that into plain parts.
"""
from __future__ import annotations

import logging
import urllib.parse
from typing import TYPE_CHECKING

from ..tenancy import Identity

if TYPE_CHECKING:
    from .clients import GoogleClients

log = logging.getLogger("rouh.google")

PRESENTATION_TYPE = "application/vnd.google-apps.presentation"
#: The placeholders a slide's title is in.
TITLES = ("TITLE", "CENTERED_TITLE")
#: Only what reading a deck needs: the slides, their elements and their notes pages, never the
#: masters and layouts, which are most of a big deck's size.
FIELDS = ("presentationId,title,revisionId,slides(objectId,pageElements,"
          "slideProperties(notesPage(notesProperties,pageElements)))")


class Slides:
    """Google Slides: a deck read whole, and one slide's picture."""

    def __init__(self, clients: GoogleClients, who: Identity) -> None:
        self._clients = clients
        self._who = who

    def _url(self, path: str) -> str:
        return self._clients.base("slides") + "/v1/presentations" + path

    async def deck(self, presentation_id: str) -> dict:
        """The deck as `deck_of` reads it: {id, title, revision, slides: [{n, id, title, text, notes}]}."""
        body = await self._clients.call(
            self._who, "GET", self._url("/" + urllib.parse.quote(presentation_id)),
            params={"fields": FIELDS})
        return deck_of(body, presentation_id)

    async def batch_update(self, presentation_id: str, requests: list[dict]) -> dict:
        """Changes made to a deck, in one batch (Written into a deck, `rouh/slide_write.py`)."""
        return await self._clients.call(
            self._who, "POST", self._url("/" + urllib.parse.quote(presentation_id) + ":batchUpdate"),
            json_body={"requests": requests})

    async def thumbnail(self, presentation_id: str, page_id: str) -> str:
        """The address of a picture of one slide, which Google keeps for about half an hour."""
        body = await self._clients.call(
            self._who, "GET",
            self._url("/" + urllib.parse.quote(presentation_id) + "/pages/"
                      + urllib.parse.quote(page_id) + "/thumbnail"),
            params={"thumbnailProperties.thumbnailSize": "MEDIUM"})
        return str(body.get("contentUrl") or "")


def _runs(text: dict | None) -> str:
    return "".join(((e.get("textRun") or {}).get("content") or "")
                   for e in (text or {}).get("textElements") or [])


def _words(element: dict) -> list[tuple[str, str]]:
    """(placeholder type, words) for one element and everything grouped in it, in order."""
    out: list[tuple[str, str]] = []
    shape = element.get("shape")
    if shape:
        said = _runs(shape.get("text")).strip()
        if said:
            out.append((str((shape.get("placeholder") or {}).get("type") or ""), said))
    table = element.get("table")
    if table:
        for row in table.get("tableRows") or []:
            cells = [_runs(c.get("text")).strip() for c in row.get("tableCells") or []]
            if any(cells):
                out.append(("TABLE", " | ".join(cells)))
    for child in (element.get("elementGroup") or {}).get("children") or []:
        out.extend(_words(child))
    return out


def _notes(slide: dict) -> str:
    page = (slide.get("slideProperties") or {}).get("notesPage") or {}
    wanted = (page.get("notesProperties") or {}).get("speakerNotesObjectId") or ""
    for element in page.get("pageElements") or []:
        if wanted and element.get("objectId") == wanted:
            return _runs((element.get("shape") or {}).get("text")).strip()
    for element in page.get("pageElements") or []:
        shape = element.get("shape") or {}
        if (shape.get("placeholder") or {}).get("type") == "BODY":
            return _runs(shape.get("text")).strip()
    return ""


def _notes_id(slide: dict) -> str:
    """The id of the shape a slide's speaker notes are written in, or ""."""
    page = (slide.get("slideProperties") or {}).get("notesPage") or {}
    return str((page.get("notesProperties") or {}).get("speakerNotesObjectId") or "")


def deck_of(body: dict, presentation_id: str = "") -> dict:
    """A deck as Slides sends it, read into numbered slides with their words and notes."""
    deck_id = body.get("presentationId") or presentation_id
    slides = []
    for n, slide in enumerate(body.get("slides") or [], start=1):
        parts: list[tuple[str, str]] = []
        for element in slide.get("pageElements") or []:
            parts.extend(_words(element))
        title = next((w for kind, w in parts if kind in TITLES), "")
        rest = [w for kind, w in parts if not (kind in TITLES and w == title)]
        if not title and rest:
            title = rest[0].splitlines()[0]
        slides.append({"n": n, "id": slide.get("objectId") or "", "title": " ".join(title.split()),
                        "text": "\n".join(rest).strip(), "notes": _notes(slide),
                        "notes_id": _notes_id(slide)})
    return {"id": deck_id, "title": body.get("title") or "", "revision": body.get("revisionId") or "",
            "slides": slides}


def slide_link(deck_id: str, slide_id: str = "") -> str:
    """The address that opens the deck in Google Slides, on one slide when its id is given."""
    link = f"https://docs.google.com/presentation/d/{deck_id}/edit"
    return link + (f"#slide=id.{slide_id}" if slide_id else "")


__all__ = ["FIELDS", "PRESENTATION_TYPE", "Slides", "TITLES", "deck_of", "slide_link"]
