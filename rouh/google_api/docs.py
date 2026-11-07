"""Docs: reading a document tab by tab, making one, and changing one.
"""
from __future__ import annotations

import logging
import re
import urllib.parse
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..tenancy import Identity
from .common import CannotDoThat, GoogleSaidNo
from .drive import DOC_TYPE, FOLDER_TYPE, MAX_FILE_CHARS

if TYPE_CHECKING:
    from .clients import GoogleClients

log = logging.getLogger("rouh.google")


class Docs:
    """Google Docs: reading a document, making one, and changing one."""

    def __init__(self, clients: GoogleClients, who: Identity) -> None:
        self._clients = clients
        self._who = who

    def _url(self, path: str) -> str:
        return self._clients.base("docs") + "/v1/documents" + path

    async def document(self, document_id: str) -> dict:
        return await self._clients.call(
            self._who, "GET", self._url("/" + urllib.parse.quote(document_id)))

    async def read(self, document_id: str, tab: str = "", pictures: bool = False,
                   suggestions: bool = False) -> dict:
        """The document as a person would read it: every tab, with its links.

        `includeTabsContent` is what makes Google send every tab. Without it
        Google sends the first tab's body and nothing else, which is how Rouh
        read a contact's homepage copy on 24 September 2026 and never saw its second
        tab. `document()` above still asks without it on purpose: the edits it
        serves are made to the first tab and count positions in it.
        """
        body = await self._clients.call(
            self._who, "GET", self._url("/" + urllib.parse.quote(document_id)),
            params={"includeTabsContent": "true"})
        return reading_of(body, document_id=body.get("documentId") or document_id, tab=tab,
                          pictures=pictures, suggestions=suggestions)

    async def picture(self, address: str) -> bytes:
        """One picture of a document, from the address its reading gave (`reading_of`)."""
        return await self._clients.call(self._who, "GET", address, want_bytes=True)

    async def create(self, title: str, body: str = "") -> dict:
        """A new document, with its first words already in it if there are any."""
        made = await self._clients.call(
            self._who, "POST", self._url(""), json_body={"title": title or "Untitled"})
        document_id = made.get("documentId") or ""
        if body and document_id:
            # Index 1 is the first position a document has: index 0 is the
            # start of the body itself, which nothing may be written at.
            await self.batch_update(
                document_id, [{"insertText": {"location": {"index": 1}, "text": body}}])
        return {"id": document_id, "title": made.get("title") or title,
                "link": f"https://docs.google.com/document/d/{document_id}/edit"
                        if document_id else ""}

    async def batch_update(self, document_id: str, requests: list[dict]) -> dict:
        """The one way a document is changed. Every edit below becomes one of these."""
        if not requests:
            return {}
        return await self._clients.call(
            self._who, "POST",
            self._url("/" + urllib.parse.quote(document_id) + ":batchUpdate"),
            json_body={"requests": requests})

    async def append(self, document_id: str, text: str) -> str:
        """Add text to the end of the document, on a new line of its own.

        The end of a document is the position just before the newline its last
        paragraph ends with, because that newline cannot be written after. So
        what is appended goes in front of it, and needs a newline of its own
        first or it runs on from the last sentence that is already there.
        """
        body = await self.document(document_id)
        at = _end_index(body)
        lead = "" if at <= 1 else "\n"
        await self.batch_update(document_id, [
            {"insertText": {"location": {"index": at}, "text": lead + (text or "")}}])
        return f"added {_count_words(text)} to the end"

    async def replace(self, document_id: str, find: str, put: str) -> str:
        """Swap every occurrence of one string for another, throughout."""
        if not find:
            raise GoogleSaidNo("Say what text to replace.")
        answer = await self.batch_update(document_id, [
            {"replaceAllText": {
                "containsText": {"text": find, "matchCase": True},
                "replaceText": put or ""}}])
        changed = 0
        for one in answer.get("replies") or []:
            changed += int((one.get("replaceAllText") or {}).get("occurrencesChanged") or 0)
        if not changed:
            raise GoogleSaidNo(f"{find!r} is not in that document, so nothing was changed.")
        return f"replaced {changed} occurrence" + ("s" if changed != 1 else "") + f" of {find!r}"

    async def insert_at_heading(self, document_id: str, heading: str, text: str) -> str:
        """Put text into the section under a heading, as its first paragraph.

        Under the heading, not before it: a person who says "add this under
        Risks" means inside that section, and inserting at the heading's own
        start index would push the words above the heading instead.
        """
        body = await self.document(document_id)
        at = _after_heading(body, heading)
        if at is None:
            raise GoogleSaidNo(
                f"There is no heading called {heading!r} in that document.")
        await self.batch_update(document_id, [
            {"insertText": {"location": {"index": at}, "text": (text or "").rstrip("\n") + "\n"}}])
        return f"added {_count_words(text)} under {heading!r}"


#: The most other files listed under a document it links to. A page of links
#: is something to crawl; a thousand is a directory, and the first hundred of
#: those say what it is.
MAX_LINKED_LISTED = 100

#: The least of a tab worth giving when the rest of it does not fit. Less than
#: this is a stump, and the tab is better named as left out, so it is read
#: whole with the tab parameter rather than taken as all there is.
SHORTEST_PART = 2_000

#: What a Google address points at, by the word in its path: what it is called
#: out loud, and Drive's own type for it. A plain Drive file's address does not
#: say what the file is, so its type is left for Drive to say.
LINKED_KINDS = {
    "document": ("Google Doc", DOC_TYPE),
    "spreadsheets": ("Google Sheet", "application/vnd.google-apps.spreadsheet"),
    "presentation": ("Google Slides", "application/vnd.google-apps.presentation"),
    "forms": ("Google Form", "application/vnd.google-apps.form"),
    "drawings": ("Google Drawing", "application/vnd.google-apps.drawing"),
    "folders": ("Drive folder", FOLDER_TYPE),
    "file": ("Drive file", ""),
}


def linked_file(address: str) -> dict | None:
    """The Drive file a Google address points at, or None for any other address.

    Gives its id, what kind of thing it is, in words and as Drive's own type,
    and the tab the address names, if it names one.

    Every shape a person pastes or a document holds: `docs.google.com/document/
    d/ID/edit`, the same with `/u/1/` or `/a/example.com/` for which account
    was signed in, `drive.google.com/file/d/ID/view`, `drive.google.com/drive/
    folders/ID`, and `drive.google.com/open?id=ID`. A published copy,
    `/document/d/e/2PACX.../pub`, is not a file anybody can open by an id, so
    it is not one.
    """
    try:
        parts = urllib.parse.urlsplit((address or "").strip())
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or (parts.hostname or "") not in (
            "docs.google.com", "drive.google.com"):
        return None
    path = [one for one in parts.path.split("/") if one]
    query = urllib.parse.parse_qs(parts.query)
    kind = next((one for one in path if one in LINKED_KINDS), "file")
    if "d" in path:
        after = path[path.index("d") + 1:]
        file_id = after[0] if after and after[0] != "e" else ""
    elif kind == "folders":
        after = path[path.index("folders") + 1:]
        file_id = after[0] if after else ""
    else:
        file_id = (query.get("id") or [""])[0]
    if not re.fullmatch(r"[A-Za-z0-9_-]+", file_id):
        return None
    words, mime = LINKED_KINDS[kind]
    return {"id": file_id, "kind": words, "mime_type": mime,
            "tab": (query.get("tab") or [""])[0]}


@dataclass
class DocTab:
    """One tab of a document: its id, its title, where it sits, and its body."""

    id: str
    title: str
    #: Its title after its parents' titles, "v1 / Call notes", so a tab nested
    #: under another is never mistaken for one at the top.
    path: str
    body: dict
    #: The pictures placed in this tab, by their object id, as Google sends them.
    pictures: dict = field(default_factory=dict)

    @property
    def named(self) -> str:
        """How a tab is said in a sentence: its place and its id."""
        return f'"{self.path}" ({self.id})' if self.id else f'"{self.path}"'


def tabs_of(document: dict) -> list[DocTab]:
    """Every tab of a document, each one before those nested under it.

    Google sends them only when it is asked with `includeTabsContent`, as a
    tree: a tab's `childTabs` are the tabs under it in the document's own
    sidebar, and they are read in the order the sidebar shows them. A document
    sent without that has one `body` and no tabs, and reads as the one tab it
    then is.
    """
    out: list[DocTab] = []

    def walk(tabs, above: tuple[str, ...]) -> None:
        for one in tabs or ():
            about = one.get("tabProperties") or {}
            title = " ".join((about.get("title") or "").split()) or "Untitled tab"
            out.append(DocTab(id=about.get("tabId") or "", title=title,
                              path=" / ".join((*above, title)),
                              body=(one.get("documentTab") or {}).get("body") or {},
                              pictures=(one.get("documentTab") or {}).get("inlineObjects") or {}))
            walk(one.get("childTabs"), (*above, title))

    walk(document.get("tabs"), ())
    if not out:
        out.append(DocTab(id="", title="", path="", body=document.get("body") or {},
                          pictures=document.get("inlineObjects") or {}))
    return out


def pick_tab(tabs: list[DocTab], wanted: str) -> DocTab:
    """The one tab a person means, by its id or by its title however it is said.

    Its id first, exactly, because that is what read_doc's own headers give.
    Then its title, or its place under another tab, ignoring capitals and
    spaces. Then the same words in any order, because a tab titled "Headline
    Options v2" is "the Headline v2 options tab" once it is said out loud,
    which is how Petar named a contact's on 24 September 2026. Then the one tab whose
    title holds every word given. Two tabs that fit as well as each other, or
    none, is a question back with every tab listed, and never a guess.
    """
    said = " ".join((wanted or "").split()).lower()
    words = _words(said)
    looks = (
        lambda tab: bool(tab.id) and tab.id.lower() == said,
        lambda tab: said in (tab.title.lower(), tab.path.lower()),
        lambda tab: bool(words) and sorted(_words(tab.title)) == sorted(words),
        lambda tab: bool(words) and set(words) <= set(_words(tab.path)),
    )
    for look in looks:
        fits = [tab for tab in tabs if look(tab)]
        if len(fits) == 1:
            return fits[0]
        if fits:
            raise CannotDoThat(
                f"More than one tab in that document fits {wanted!r}: "
                f"{', '.join(tab.named for tab in fits)}. Say which one by its id.")
    listed = ", ".join(tab.named for tab in tabs if tab.id or tab.title)
    raise CannotDoThat(
        f"There is no tab called {wanted!r} in that document. "
        + (f"Its tabs are {listed}." if listed else "It has only the one tab."))


def _words(text: str) -> list[str]:
    return re.findall(r"\w+", (text or "").lower())


def reading_of(document: dict, *, document_id: str = "", tab: str = "",
               pictures: bool = False, suggestions: bool = False) -> dict:
    """A document the way read_doc says it: every tab, links kept, cut to size.

    A document with one tab reads as its words and nothing else, the same as
    before tabs were read at all. With more than one, each tab comes under a
    line of its own naming it, "=== Tab: Headline Options v2 (t.bg1a0mdnoeme)
    ===", nested tabs named by their place, "v1 / Call notes", in the order the
    document's sidebar has them. `tab` narrows it to one of them (`pick_tab`).

    The whole of it is held to `MAX_FILE_CHARS`, and a cut is said rather than
    left for the reader to notice: which tab stopped part way, which tabs were
    left out, and that the tab parameter reads any of them whole.

    After the words comes every other file the document links to, with the id
    read_doc takes, because a document that is an index of other documents is
    only half read without them (a contact's site plan, 24 September 2026, which
    links a copy document for each page and read as a list of page names).

    `pictures` marks each picture in its place, "[picture 2: Process map]", and
    lists them under "pictures" with the address Google keeps each at for half
    an hour (Pictures in docs seen, `rouh/doc_pictures.py`); without it a
    picture is no words at all, as it always was.

    `suggestions` marks each suggested edit nobody has accepted or rejected
    yet, "[suggested insertion: «...»]" and "[suggested deletion: «...»]", and
    counts them under "suggestions" (Suggested edits read as suggestions,
    `rouh/doc_suggestions.py`); without it a suggestion reads as if it were
    already in, and the words it would delete as if nobody had touched them.
    """
    tabs = tabs_of(document)
    reading = _Reading(document_id or document.get("documentId") or "", tabs)
    reading.mark_pictures = pictures
    reading.mark_suggestions = suggestions
    chosen = pick_tab(tabs, tab) if (tab or "").strip() else None
    shown = [chosen] if chosen else tabs
    # Every tab shown is read, even one that will not fit, so the links in it
    # are still in the list at the end.
    texts = [reading.text(one) for one in shown]
    if not any(texts):
        text = ""
    elif len(shown) == 1:
        text = texts[0]
        if len(text) > MAX_FILE_CHARS:
            text = (text[:MAX_FILE_CHARS]
                    + f"\n\n[Cut here: this goes on past the {MAX_FILE_CHARS:,} characters "
                      "read_doc gives at once, and the rest of it is not included.]")
    else:
        text = _tab_by_tab(shown, texts)
    listed = reading.linked_list()
    if text and listed:
        text += "\n\n" + listed
    return {"id": reading.document_id, "title": document.get("title") or "", "text": text,
            "tabs": [{"id": one.id, "title": one.title, "path": one.path} for one in tabs],
            "tab": ({"id": chosen.id, "title": chosen.title, "path": chosen.path}
                    if chosen and len(tabs) > 1 else None),
            "pictures": reading.pictures,
            "suggestions": {"insertions": len(reading.inserted), "deletions": len(reading.deleted)}}


def _tab_by_tab(tabs: list[DocTab], texts: list[str]) -> str:
    """Several tabs' words, each under its own line, as many as fit."""
    blocks: list[str] = []
    used = 0
    cut_short: DocTab | None = None
    left_out: list[DocTab] = []
    for one, words in zip(tabs, texts):
        block = f"=== Tab: {one.path} ({one.id}) ===\n" + (words or "(this tab is empty)")
        room = MAX_FILE_CHARS - used
        if cut_short or left_out:
            left_out.append(one)
        elif len(block) <= room:
            blocks.append(block)
            used += len(block) + 2
        elif room >= SHORTEST_PART:
            blocks.append(block[:room])
            cut_short = one
        else:
            left_out.append(one)
    if cut_short or left_out:
        said = [(f"[Cut here: read_doc gives at most {MAX_FILE_CHARS:,} characters at once, "
                 "and this document is longer.")]
        if cut_short:
            said.append(f"The tab {cut_short.named} stops part way through.")
        if left_out:
            said.append("Not included at all: "
                        + ", ".join(one.named for one in left_out) + ".")
        said.append("Read any one tab whole with read_doc, this document, and tab set to "
                    "its id.]")
        blocks.append(" ".join(said))
    return "\n\n".join(blocks)


class _Reading:
    """One document's words, tab by tab, with every link in them kept.

    Made once for the whole document, because a link inside it is said in the
    document's own terms wherever it points: a link to another tab by that
    tab's title, and a link to a heading by the heading's own words.
    """

    def __init__(self, document_id: str, tabs: list[DocTab]) -> None:
        self.document_id = document_id
        self.tabs = {one.id: one for one in tabs if one.id}
        self.one_tab = len(tabs) == 1
        #: Each heading's words, by its tab and its id, and by its id alone for
        #: the older links that do not say which tab.
        self.headings: dict[tuple[str, str], str] = {}
        self.any_heading: dict[str, str] = {}
        for one in tabs:
            self._find_headings(one.id, (one.body or {}).get("content"))
        #: Every other file linked to, by its id, in the order first met.
        self.linked: dict[str, dict] = {}
        #: Whether pictures are marked in their place, and each one met, in order.
        self.mark_pictures = False
        self.pictures: list[dict] = []
        #: Whether suggested edits are marked, and the ids of each kind met.
        self.mark_suggestions = False
        self.inserted: set[str] = set()
        self.deleted: set[str] = set()
        self._tab: DocTab | None = None

    def _find_headings(self, tab_id: str, elements) -> None:
        for element in elements or ():
            paragraph = element.get("paragraph")
            heading = ((paragraph or {}).get("paragraphStyle") or {}).get("headingId")
            if heading:
                words = " ".join("".join(
                    (piece.get("textRun") or {}).get("content") or ""
                    for piece in paragraph.get("elements") or ()).split())
                self.headings[(tab_id, heading)] = words
                self.any_heading.setdefault(heading, words)
            for row in (element.get("table") or {}).get("tableRows") or ():
                for cell in row.get("tableCells") or ():
                    self._find_headings(tab_id, cell.get("content"))

    def text(self, tab: DocTab) -> str:
        """Every word of one tab, in order, as plain text with its links in it.

        A tab's body is a list of structural elements: paragraphs, tables and
        section breaks. A paragraph is a list of elements, and a text run
        inside one is where most of the characters are; a smart chip is an
        element of its own beside them. Tables are walked too, because a table
        is often where the numbers somebody is asking about live.
        """
        out: list[str] = []
        self._tab = tab

        def walk(elements, contents: bool) -> None:
            for element in elements or ():
                paragraph = element.get("paragraph")
                if paragraph:
                    out.append(self._paragraph(paragraph.get("elements"), contents))
                table = element.get("table")
                if table:
                    for row in table.get("tableRows") or ():
                        for cell in row.get("tableCells") or ():
                            walk(cell.get("content"), contents)
                section = element.get("tableOfContents")
                if section:
                    walk(section.get("content"), True)

        walk((tab.body or {}).get("content"), False)
        return "".join(out).strip()

    def _paragraph(self, elements, contents: bool) -> str:
        """One paragraph's words, with a link's runs gathered back into one link.

        Google splits a link into several runs wherever its style changes, a
        bold word in the middle of it, so a run is not a link of its own: the
        runs that share a link are said together, with the link once after
        them.
        """
        out: list[str] = []
        held: list[str] = []
        held_link: dict | None = None
        held_suggestion: tuple[str, str] | None = None

        def let_go() -> None:
            if held:
                out.append(self._suggested(self._linked("".join(held), held_link),
                                           held_suggestion))
                held.clear()

        for piece in elements or ():
            run = piece.get("textRun")
            if run is None:
                let_go()
                held_link = None
                held_suggestion = None
                out.append(self._chip(piece))
                continue
            link = (run.get("textStyle") or {}).get("link") or None
            if contents and link and not link.get("url"):
                # A table of contents is a link to every heading, each worded
                # as the heading it points at. Saying so on every line of it
                # says nothing.
                link = None
            suggestion = self._suggestion_of(run)
            if link != held_link or suggestion != held_suggestion:
                let_go()
                held_link = link
                held_suggestion = suggestion
            held.append(run.get("content") or "")
        let_go()
        return "".join(out)

    def _suggestion_of(self, run: dict) -> tuple[str, str] | None:
        """("insertion" or "deletion", its id) for a run somebody only suggested, or None.

        A run Google sends with `suggestedInsertionIds` is not in the
        document until the suggestion is accepted, and one with
        `suggestedDeletionIds` is still in it until then. Only marked while
        Suggested edits read as suggestions is on (`rouh/doc_suggestions.py`).
        """
        if not self.mark_suggestions:
            return None
        inserted = [str(one) for one in run.get("suggestedInsertionIds") or () if one]
        if inserted:
            self.inserted.add(inserted[0])
            return ("insertion", inserted[0])
        deleted = [str(one) for one in run.get("suggestedDeletionIds") or () if one]
        if deleted:
            self.deleted.add(deleted[0])
            return ("deletion", deleted[0])
        return None

    @staticmethod
    def _suggested(words: str, suggestion: tuple[str, str] | None) -> str:
        """Words, marked as a suggested insertion or deletion, the paragraph's newline kept out."""
        if not suggestion:
            return words
        shown = words.rstrip("\n")
        if not shown.strip():
            return words
        return f"[suggested {suggestion[0]}: «{shown}»]" + words[len(shown):]

    def _linked(self, words: str, link: dict | None) -> str:
        """Words, with where they link to after them: "text [link: address]"."""
        if not link:
            return words
        shown = words.rstrip()
        # The paragraph's own newline, when a link runs to the end of one,
        # stays after the mark rather than splitting it from its words.
        after = words[len(shown):]
        if not shown.strip():
            return words
        address = (link.get("url") or "").strip()
        if address:
            self._note(address, shown)
            if _same_address(shown, address):
                # A pasted address is its own link; saying it twice is noise.
                return words
            return f"{shown} [link: {address}]{after}"
        target = self._inside(link)
        return f"{shown} [link: {target}]{after}" if target else words

    def _inside(self, link: dict) -> str:
        """Where a link to somewhere in this same document goes, in its own words.

        Google says it three ways: `tabId` for a whole tab, and `heading` or
        `bookmark` with the tab each is in. A document read without tabs says
        the last two as bare `headingId` and `bookmarkId` instead.
        """
        heading = link.get("heading") or (
            {"id": link["headingId"]} if link.get("headingId") else None)
        if heading:
            tab_id = heading.get("tabId") or ""
            words = (self.headings.get((tab_id, heading.get("id") or ""))
                     or self.any_heading.get(heading.get("id") or ""))
            said = f'heading "{words}"' if words else f"heading {heading.get('id') or ''}"
            return said.strip() + self._in_tab(tab_id)
        bookmark = link.get("bookmark") or (
            {"id": link["bookmarkId"]} if link.get("bookmarkId") else None)
        if bookmark:
            return (f"bookmark {bookmark.get('id') or ''}".strip()
                    + self._in_tab(bookmark.get("tabId") or ""))
        if link.get("tabId"):
            return "tab " + self._tab_named(link["tabId"])
        return ""

    def _in_tab(self, tab_id: str) -> str:
        if self.one_tab or not tab_id:
            return ""
        return " in tab " + self._tab_named(tab_id)

    def _tab_named(self, tab_id: str) -> str:
        one = self.tabs.get(tab_id)
        return one.named if one else tab_id

    def _chip(self, piece: dict) -> str:
        """A smart chip, which is not a run of text and so used to be no words at all."""
        rich = piece.get("richLink")
        if rich:
            about = rich.get("richLinkProperties") or {}
            title = " ".join((about.get("title") or "").split())
            address = (about.get("uri") or "").strip()
            if not address:
                return title
            self._note(address, title)
            return f"{title} [link: {address}]" if title else f"[link: {address}]"
        person = piece.get("person")
        if person:
            about = person.get("personProperties") or {}
            said = ", ".join(one for one in (about.get("name"), about.get("email")) if one)
            return f"[person: {said}]" if said else ""
        date = piece.get("dateElement")
        if date:
            return (date.get("dateElementProperties") or {}).get("displayText") or ""
        placed = piece.get("inlineObjectElement")
        if placed and self.mark_pictures:
            return self._picture(str(placed.get("inlineObjectId") or ""))
        return ""

    def _picture(self, object_id: str) -> str:
        """A picture in its place, "[picture 2: Process map]", kept to be shown."""
        held = ((self._tab.pictures if self._tab else {}) or {}).get(object_id) or {}
        embedded = (held.get("inlineObjectProperties") or {}).get("embeddedObject") or {}
        address = str((embedded.get("imageProperties") or {}).get("contentUri") or "")
        if not address:
            # A drawing or a chart with no picture Google will hand over.
            return "[a drawing that cannot be read here]"
        about = " ".join(" ".join(one for one in (embedded.get("title"), embedded.get("description"))
                                  if one).split())
        n = len(self.pictures) + 1
        self.pictures.append({"n": n, "id": object_id, "uri": address, "about": about,
                              "tab": self._tab.path if self._tab and not self.one_tab else ""})
        return f"[picture {n}: {about}]" if about else f"[picture {n}]"

    def _note(self, address: str, words: str) -> None:
        """Keep a link to another file, for the list at the end."""
        found = linked_file(address)
        if found is None or found["id"] == self.document_id:
            return
        kept = self.linked.setdefault(found["id"], {**found, "said": [], "tabs": []})
        if found["mime_type"] and not kept["mime_type"]:
            # Met first as a plain Drive address, then as what it really is.
            kept.update(kind=found["kind"], mime_type=found["mime_type"])
        words = " ".join((words or "").split())
        if words and not _same_address(words, address) and words not in kept["said"]:
            kept["said"].append(words)
        if found["tab"] and found["tab"] not in kept["tabs"]:
            kept["tabs"].append(found["tab"])

    def linked_list(self) -> str:
        """Every other file this document links to, each with the id read_doc takes."""
        if not self.linked:
            return ""
        count = len(self.linked)
        lines = [(f"Linked documents: {count} other file{'' if count == 1 else 's'} this "
                  "document links to. read_doc reads any of them by its id.")]
        for one in list(self.linked.values())[:MAX_LINKED_LISTED]:
            line = f"- {one['kind']} {one['id']}"
            if one["tabs"]:
                line += ", tab " + " and ".join(one["tabs"])
            if one["said"]:
                line += ", linked as " + " and ".join(
                    f'"{_shortened(words)}"' for words in one["said"][:3])
            if one["mime_type"] == FOLDER_TYPE:
                line += " - a folder, which list_drive_folder lists"
            lines.append(line)
        if count > MAX_LINKED_LISTED:
            lines.append(f"- and {count - MAX_LINKED_LISTED} more")
        return "\n".join(lines)


def _same_address(words: str, address: str) -> bool:
    """Whether some words are only the address they link to, written out."""
    def bare(text: str) -> str:
        return re.sub(r"^https?://(www\.)?", "", (text or "").strip()).rstrip("/")
    return bare(words) == bare(address)


def _shortened(words: str, most: int = 80) -> str:
    return words if len(words) <= most else words[:most - 3].rstrip() + "..."


def _end_index(document: dict) -> int:
    """Where the end of the document is, as an index text may be written at.

    A document's last structural element ends one past the last character, and
    that last position is the newline the body itself always ends with. Writing
    at it is refused, so everything is written just before it.
    """
    content = (document.get("body") or {}).get("content") or []
    if not content:
        return 1
    return max(1, int(content[-1].get("endIndex") or 2) - 1)


def _after_heading(document: dict, heading: str) -> int | None:
    """The index just after the heading paragraph with this text, or None."""
    wanted = " ".join((heading or "").split()).lower()
    if not wanted:
        return None
    for element in (document.get("body") or {}).get("content") or ():
        paragraph = element.get("paragraph")
        if not paragraph:
            continue
        style = (paragraph.get("paragraphStyle") or {}).get("namedStyleType") or ""
        said = "".join((piece.get("textRun") or {}).get("content") or ""
                       for piece in paragraph.get("elements") or ())
        if " ".join(said.split()).lower() != wanted:
            continue
        # Matched on the words, not on the style. A document written with bold
        # lines instead of heading styles is common, and a person pointing at
        # "Risks" means that line whichever way it was made to look like one.
        log.debug("insert under %r, which is a %s", heading, style or "plain paragraph")
        return int(element.get("endIndex") or 1)
    return None


def _count_words(text: str) -> str:
    words = len((text or "").split())
    return f"{words} word" + ("s" if words != 1 else "")
