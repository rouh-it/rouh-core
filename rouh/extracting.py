"""The words in an uploaded file, as Markdown.

This is the reading half of making the person's uploads searchable
(`rouh/uploads.py` is the rest). It is handed one file and writes the words in
it to standard output as Markdown, and that is all it does: it writes nowhere,
keeps nothing, and imports nothing from Django.

**It runs in a process of its own**, `python -m rouh.extracting <file> <kind>`,
started by `uploads.py` for each file, and never inside Rouh. Rouh is one
long-lived process that every one of the person's files goes through, and each
of these would otherwise be its problem:

- **Time.** A PDF can be made so that reading it never ends. The process is
  killed after `uploads.EXTRACT_SECONDS`, and the file is simply found by its
  name rather than by its words.
- **Memory.** A sixty megabyte spreadsheet can unzip to gigabytes of XML. This
  process gives itself a ceiling (`MEMORY`) before it opens anything, so a file
  that needs more fails here, and whatever it did use is handed back to the
  machine when it exits, which memory used inside Rouh would never be.
- **A parser that falls over** takes this process with it, not the server.

What is read
------------

Decided by the file's extension first, because that is what the upload was
stored under, and then by the kind `attachments.classify` gave it, so a PDF or
a text file with a name that says nothing is still read.

- **PDF**, page by page, with `pypdf`. A PDF that is only pictures of pages - a
  scan - has no words in it to read, and there is no OCR on this machine.
- **Word, Excel and PowerPoint** (.docx, .xlsx, .pptx and their macro-enabled
  twins), and **OpenDocument** (.odt, .ods, .odp): each is a zip of XML, read
  as a stream, so the size of a file is never the size of what is held.
  Headings stay headings, lists stay lists, and a table or a sheet becomes a
  Markdown table, one row per line.
- **HTML and SVG**: the words, without the markup or the scripts.
- **RTF**: the words, without the control codes.
- **Everything else that is text** - notes, Markdown, CSV, JSON, source - is
  its own Markdown, as it is.

Nothing else is read. A picture, a recording and the older binary Office
formats (.doc, .xls, .ppt) are still found by their names. A forwarded email
(.eml) and a zip archive are read while Files inside files read is on
(`rouh/inside_files.py`), each file inside them read as its own section.

**No word is added that the file does not have.** Pages and slides are divided
by a Markdown rule (`---`) rather than by a heading saying "Page 2", because
every word here is a word a search can match, and a heading on every page
would make "page" find every PDF there is.
"""
from __future__ import annotations

import html.parser
import logging
import os
import posixpath
import re
import sys
import zipfile
from xml.etree import ElementTree

#: The most Markdown one file is turned into, in characters. Two million is a
#: book of well over a thousand pages; past that the rest of the file is not
#: what a search is for, and the file is still found by everything before it.
TEXT_MAX = 2_000_000

#: The address space this process allows itself, in bytes. A gigabyte holds a
#: sixty-four megabyte PDF open in `pypdf` with room to spare, and is a limit
#: the machine can afford to lose to one file at a time.
MEMORY = 1024 * 1024 * 1024

#: The most columns one row of a table is drawn with. A cell somewhere out at
#: column XFD is still read; it is just not padded out to sixteen thousand
#: empty cells first.
COLUMNS_MAX = 200

#: How the pages of a PDF and the slides of a deck are divided.
RULE = "---"


class _Full(Exception):
    """The Markdown has reached `TEXT_MAX`, so reading stops here."""


class _Out:
    """The Markdown being written, which refuses to grow past `TEXT_MAX`.

    Blocks are paragraphs, headings and list items, each followed by a blank
    line; table rows are lines of their own, with a blank line after the last.
    """

    def __init__(self, limit: int = TEXT_MAX) -> None:
        self.parts: list[str] = []
        self.size = 0
        self.limit = limit
        self.header: int | None = None   # the width of the table being written

    def _add(self, text: str) -> None:
        room = self.limit - self.size
        if len(text) > room:
            self.parts.append(text[:room])
            self.size = self.limit
            raise _Full
        self.parts.append(text)
        self.size += len(text)

    def block(self, text: str, prefix: str = "") -> None:
        text = text.strip()
        if not text:
            return
        self.end_table()
        self._add(prefix + text + "\n\n")

    def row(self, cells: list[str]) -> None:
        """One row of a table; the first row of each table is its header."""
        cells = [_cell(c) for c in cells]
        while cells and not cells[-1]:
            cells.pop()
        if not any(cells):
            return
        self._add("| " + " | ".join(cells) + " |\n")
        if self.header is None:
            self.header = len(cells)
            self._add("|" + " --- |" * len(cells) + "\n")

    def end_table(self) -> None:
        if self.header is not None:
            self.header = None
            self._add("\n")

    def rule(self) -> None:
        """A division between two pages or two slides, never two in a row."""
        self.end_table()
        if self.parts and self.parts[-1] != RULE + "\n\n":
            self._add(RULE + "\n\n")

    def text(self) -> str:
        return "".join(self.parts)


def _cell(text: str) -> str:
    """One cell of a Markdown table: one line, and no pipe that would split it."""
    return " ".join(str(text or "").split()).replace("|", "\\|")


def _tidy(text: str) -> str:
    """Line endings made one, control characters out, runs of blank lines cut.

    A PDF's text is full of form feeds and the odd NUL, and none of them is a
    word or something a Markdown reader wants.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    while text.endswith(RULE):
        text = text[:-len(RULE)].rstrip()
    return text + "\n" if text else ""


def _local(tag) -> str:
    """An XML tag without its namespace: `{...}p` is `p`."""
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _attr(elem, name: str) -> str:
    """An attribute by its name without the namespace, whichever that is."""
    for key, value in elem.attrib.items():
        if _local(key) == name:
            return value
    return ""


def _stream(zf: zipfile.ZipFile, part: str):
    """(event, tag without namespace, element) for one XML part of a zip, as read.

    A stream rather than a tree, so a sheet of a million rows is never held
    whole. Python's own parser resolves no external entity and refuses the
    entity expansion a "billion laughs" file is built on.
    """
    with zf.open(part) as fh:
        for event, elem in ElementTree.iterparse(fh, events=("start", "end")):
            yield event, _local(elem.tag), elem


def _rel_id(elem) -> str:
    """The relationship an element points through: its `r:id`.

    Namespaced on purpose. A slide's entry in a deck has a plain `id` as well,
    which is a number and points at nothing.
    """
    for key, value in elem.attrib.items():
        if key.startswith("{") and _local(key) == "id":
            return value
    return ""


def _rels(zf: zipfile.ZipFile, part: str) -> dict[str, str]:
    """Relationship id -> the part it points at, for one part of an Office file."""
    folder, _, base = part.rpartition("/")
    rels = f"{folder}/_rels/{base}.rels" if folder else f"_rels/{base}.rels"
    out: dict[str, str] = {}
    if rels not in zf.namelist():
        return out
    for event, name, elem in _stream(zf, rels):
        if event != "end" or name != "Relationship":
            continue
        if elem.get("TargetMode") == "External":
            continue
        target = elem.get("Target") or ""
        if target.startswith("/"):
            target = target.lstrip("/")
        else:
            target = posixpath.normpath(posixpath.join(folder, target))
        out[elem.get("Id") or ""] = target
    return out


# ---------------------------------------------------------------------------
# The readers, one per format. Each is handed the path and the Markdown to
# write into, and stops when the Markdown says it is full.
# ---------------------------------------------------------------------------


def _plain(path: str, out: _Out) -> None:
    """A text file, which is its own Markdown."""
    with open(path, "rb") as fh:
        raw = fh.read(TEXT_MAX * 4)
    out._add(_decoded(raw))


def _decoded(raw: bytes) -> str:
    """Text, whichever of the encodings people actually save it in.

    UTF-8 first, with or without its mark; UTF-16 when the file says so, which
    is what Windows calls "Unicode"; and Windows-1252 for the rest, which
    cannot fail and is what an old file with an accent in it usually is.
    """
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16", "replace")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("cp1252", "replace")


class _Html(html.parser.HTMLParser):
    """The words of an HTML page, with its headings and list items marked."""

    SKIP = {"script", "style", "noscript", "template", "head", "iframe", "object"}
    BLOCKS = {"p", "div", "section", "article", "header", "footer", "main", "aside",
              "nav", "ul", "ol", "table", "tr", "blockquote", "pre", "figure",
              "figcaption", "dl", "dt", "dd", "hr", "address", "form", "fieldset",
              "details", "summary", "title", "text", "desc"}

    def __init__(self, out: _Out) -> None:
        super().__init__(convert_charrefs=True)
        self.out = out
        self.skipping = 0
        self.words: list[str] = []
        self.prefix = ""

    def flush(self) -> None:
        text = " ".join("".join(self.words).split())
        self.words = []
        self.out.block(text, self.prefix)
        self.prefix = ""

    def handle_starttag(self, tag, attrs):
        if tag == "body":
            # A page may leave `</head>` out, which HTML allows; the body
            # starting is the head over, whatever was said.
            self.skipping = 0
            self.flush()
        elif tag in self.SKIP:
            self.skipping += 1
        elif re.fullmatch(r"h[1-6]", tag):
            self.flush()
            self.prefix = "#" * int(tag[1]) + " "
        elif tag == "li":
            self.flush()
            self.prefix = "- "
        elif tag in self.BLOCKS or tag == "br":
            self.flush()
        elif tag in ("td", "th"):
            self.words.append(" ")

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self.skipping = max(0, self.skipping - 1)
        elif re.fullmatch(r"h[1-6]", tag) or tag == "li" or tag in self.BLOCKS:
            self.flush()

    def handle_data(self, data):
        if not self.skipping:
            self.words.append(data)


def _html(path: str, out: _Out) -> None:
    with open(path, "rb") as fh:
        raw = fh.read(TEXT_MAX * 4)
    page = _Html(out)
    page.feed(_decoded(raw))
    page.close()
    page.flush()


#: The groups of an RTF file that hold no words of the document: its tables of
#: fonts, colours and styles, its pictures, and what the program that saved it
#: wanted to remember about itself.
_RTF_SKIP = frozenset({
    "fonttbl", "colortbl", "stylesheet", "info", "pict", "object", "themedata",
    "colorschememapping", "latentstyles", "datastore", "xmlnstbl", "listtable",
    "listoverridetable", "revtbl", "rsidtbl", "generator", "filetbl", "header",
    "footer", "headerl", "headerr", "footerl", "footerr", "fldinst",
})
_RTF_TOKEN = re.compile(
    r"\\([a-z]{1,32})(-?\d{1,10})? ?|\\'([0-9a-f]{2})|\\([^a-z])|([{}])|[\r\n]+|([^\\{}\r\n]+)",
    re.I)


def _rtf(path: str, out: _Out) -> None:
    """The words of an RTF file, which is text wrapped in control codes."""
    with open(path, "rb") as fh:
        raw = fh.read(TEXT_MAX * 8).decode("latin-1")
    words: list[str] = []
    stack: list[tuple[bool, int]] = []
    skip, unicode_skip, owed = False, 1, 0
    for word, number, hexcode, symbol, brace, text in (
            m.groups() for m in _RTF_TOKEN.finditer(raw)):
        if brace == "{":
            stack.append((skip, unicode_skip))
        elif brace == "}":
            skip, unicode_skip = stack.pop() if stack else (False, 1)
        elif symbol:
            if symbol == "*":
                skip = True
            elif not skip and symbol in "\\{}":
                words.append(symbol)
            elif not skip and symbol == "~":
                words.append(" ")
        elif word:
            word = word.lower()
            if word in _RTF_SKIP:
                skip = True
            elif word == "uc":
                unicode_skip = int(number or 1)
            elif skip:
                pass
            elif word in ("par", "line", "sect", "page", "row"):
                words.append("\n")
            elif word in ("tab", "cell"):
                words.append("\t")
            elif word == "u" and number:
                words.append(chr(int(number) % 65536))
                owed = unicode_skip
        elif hexcode:
            if owed:
                owed -= 1
            elif not skip:
                words.append(bytes([int(hexcode, 16)]).decode("cp1252", "replace"))
        elif text and not skip:
            if owed:
                cut = min(owed, len(text))
                text, owed = text[cut:], owed - cut
            words.append(text)
    for paragraph in "".join(words).split("\n"):
        out.block(paragraph)


def _pdf(path: str, out: _Out) -> None:
    """A PDF, page by page. A page that will not read is left out, not the file."""
    from pypdf import PdfReader

    # pypdf says what it thinks of every odd PDF on the logger, and a file the
    # person saved from somewhere is an odd PDF more often than not.
    logging.getLogger("pypdf").setLevel(logging.CRITICAL)
    reader = PdfReader(path)
    if reader.is_encrypted:
        # Many PDFs are "encrypted" with an empty password only to stop them
        # being edited; those open. One that needs a real password does not,
        # and is found by its name.
        try:
            if not reader.decrypt(""):
                return
        except Exception:
            return
    for page in reader.pages:
        try:
            text = page.extract_text() or ""
        except (_Full, MemoryError):
            raise
        except Exception:
            continue
        if text.strip():
            out.rule()
            out.block(text)


#: A Word paragraph style that is a heading, and which level: `Heading1`,
#: `heading 2`, and the `Title` style at the top.
_HEADING = re.compile(r"(?i)^(?:heading\s*([1-6])|(title))$")


def _docx(path: str, out: _Out) -> None:
    """A Word document: its body, then its footnotes and endnotes."""
    with zipfile.ZipFile(path) as zf:
        names = set(zf.namelist())
        for part in ("word/document.xml", "word/footnotes.xml", "word/endnotes.xml"):
            if part in names:
                _docx_part(zf, part, out)


def _docx_part(zf: zipfile.ZipFile, part: str, out: _Out) -> None:
    #: The paragraph being read, and the ones it is inside: a text box is a
    #: paragraph within a paragraph, and the words either side of it belong to
    #: the outer one.
    para: dict = {"words": [], "style": "", "listed": False}
    outer: list[dict] = []
    in_props = 0
    #: Word keeps every text box twice, once for itself and once as a picture
    #: for programs too old to draw one (`mc:Fallback`). The second is skipped.
    fallback = 0
    #: The tables being read, innermost last: each is its rows and the cell
    #: being filled. A table inside a cell is read into that cell as words.
    tables: list[dict] = []
    for event, name, elem in _stream(zf, part):
        if name == "Fallback":
            fallback += 1 if event == "start" else -1
            continue
        if fallback:
            continue
        if event == "start":
            if name == "tbl":
                tables.append({"rows": [], "row": [], "cell": []})
            elif name == "tr" and tables:
                tables[-1]["row"] = []
            elif name == "tc" and tables:
                tables[-1]["cell"] = []
            elif name == "p":
                outer.append(para)
                para = {"words": [], "style": "", "listed": False}
            elif name == "pPr":
                in_props += 1
            continue
        if name == "pPr":
            in_props = max(0, in_props - 1)
        elif name == "pStyle":
            para["style"] = _attr(elem, "val")
        elif name == "numPr":
            para["listed"] = True
        elif name == "t":
            para["words"].append(elem.text or "")
        elif name == "tab" and not in_props:
            para["words"].append("\t")
        elif name in ("br", "cr"):
            para["words"].append("\n")
        elif name == "p":
            text = "".join(para["words"]).strip()
            if tables:
                if text:
                    tables[-1]["cell"].append(text)
            else:
                heading = _HEADING.match(para["style"] or "")
                level = int(heading.group(1) or 1) if heading else 0
                prefix = ("#" * level + " " if level
                          else "- " if para["listed"] else "")
                for i, line in enumerate(text.split("\n")):
                    out.block(line, prefix if i == 0 else "")
            para = outer.pop() if outer else {"words": [], "style": "", "listed": False}
            if not outer:
                elem.clear()
        elif name == "tc" and tables:
            tables[-1]["row"].append(" ".join(tables[-1]["cell"]))
        elif name == "tr" and tables:
            tables[-1]["rows"].append(tables[-1]["row"])
            elem.clear()
        elif name == "tbl" and tables:
            done = tables.pop()
            if tables:
                tables[-1]["cell"].append(
                    " ".join(" ".join(cells) for cells in done["rows"]))
            else:
                for cells in done["rows"]:
                    out.row(cells[:COLUMNS_MAX])
                out.end_table()
            elem.clear()


def _column(ref: str) -> int:
    """The column of a cell reference, from nought: `A1` is 0, `AB12` is 27."""
    n = 0
    for ch in ref:
        if not ch.isalpha():
            break
        n = n * 26 + (ord(ch.upper()) - 64)
    return n - 1


def _xlsx(path: str, out: _Out) -> None:
    """An Excel workbook: each sheet under its own name, as a table."""
    with zipfile.ZipFile(path) as zf:
        names = set(zf.namelist())
        shared = _shared_strings(zf) if "xl/sharedStrings.xml" in names else []
        for title, part in _sheets(zf, names):
            if part not in names:
                continue
            out.block(title, "## ")
            _sheet(zf, part, shared, out)
            out.end_table()


def _shared_strings(zf: zipfile.ZipFile) -> list[str]:
    """The strings a workbook keeps once and points at from its cells.

    The pronunciation guide Excel keeps for Japanese (`rPh`) is not the text
    of the cell, so it is left out.
    """
    strings: list[str] = []
    bits: list[str] = []
    guide = 0
    for event, name, elem in _stream(zf, "xl/sharedStrings.xml"):
        if name == "rPh":
            guide += 1 if event == "start" else -1
        elif event == "end" and name == "t" and not guide:
            bits.append(elem.text or "")
        elif event == "end" and name == "si":
            strings.append("".join(bits))
            bits = []
            elem.clear()
    return strings


def _sheets(zf: zipfile.ZipFile, names: set[str]) -> list[tuple[str, str]]:
    """(sheet name, part) for each sheet, in the order the workbook has them."""
    found: list[tuple[str, str]] = []
    if "xl/workbook.xml" in names:
        rels = _rels(zf, "xl/workbook.xml")
        for event, name, elem in _stream(zf, "xl/workbook.xml"):
            if event == "end" and name == "sheet":
                part = rels.get(_rel_id(elem), "")
                if part:
                    found.append((elem.get("name") or "", part))
    if not found:
        parts = [n for n in names if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n)]
        parts.sort(key=lambda n: int(re.sub(r"\D", "", n) or 0))
        found = [("", part) for part in parts]
    return found


def _sheet(zf: zipfile.ZipFile, part: str, shared: list[str], out: _Out) -> None:
    row: dict[int, str] = {}
    value, inline = None, []
    for event, name, elem in _stream(zf, part):
        if event != "end":
            continue
        if name == "v":
            value = elem.text
        elif name == "t":
            inline.append(elem.text or "")
        elif name == "c":
            kind = elem.get("t") or ""
            if kind == "s":
                try:
                    text = shared[int(value or "")]
                except (ValueError, IndexError):
                    text = ""
            elif kind == "inlineStr":
                text = "".join(inline)
            elif kind == "b":
                text = "TRUE" if value == "1" else "FALSE"
            else:
                text = value or ""
            if text:
                col = _column(elem.get("r") or "")
                row[col if col >= 0 else len(row)] = text
            value, inline = None, []
            elem.clear()
        elif name == "row":
            if row:
                widest = max(row)
                if widest < COLUMNS_MAX:
                    out.row([row.get(i, "") for i in range(widest + 1)])
                else:
                    out.row([row[i] for i in sorted(row)][:COLUMNS_MAX])
            row = {}
            elem.clear()


def _pptx(path: str, out: _Out) -> None:
    """A PowerPoint deck, slide by slide, in the order the deck shows them."""
    with zipfile.ZipFile(path) as zf:
        names = set(zf.namelist())
        slides: list[str] = []
        if "ppt/presentation.xml" in names:
            rels = _rels(zf, "ppt/presentation.xml")
            for event, name, elem in _stream(zf, "ppt/presentation.xml"):
                if event == "end" and name == "sldId":
                    part = rels.get(_rel_id(elem), "")
                    if part in names:
                        slides.append(part)
        if not slides:
            slides = [n for n in names if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)]
            slides.sort(key=lambda n: int(re.sub(r"\D", "", n) or 0))
        for part in slides:
            out.rule()
            para: list[str] = []
            for event, name, elem in _stream(zf, part):
                if event != "end":
                    continue
                if name == "t":
                    para.append(elem.text or "")
                elif name == "br":
                    para.append("\n")
                elif name == "p":
                    for line in "".join(para).split("\n"):
                        out.block(line)
                    para = []
                    elem.clear()


def _odf_text(elem) -> str:
    """The words of one OpenDocument paragraph, with its spaces and tabs.

    A paragraph inside this one - in a text box, or a footnote's body - has
    already been written as a paragraph of its own, so it is not read again.
    """
    out = [elem.text or ""]
    for child in elem:
        name = _local(child.tag)
        if name == "s":
            try:
                out.append(" " * max(1, min(int(_attr(child, "c") or 1), 100)))
            except ValueError:
                out.append(" ")
        elif name == "tab":
            out.append("\t")
        elif name == "line-break":
            out.append("\n")
        elif name not in ("p", "h", "note-citation", "annotation"):
            out.append(_odf_text(child))
        out.append(child.tail or "")
    return "".join(out)


def _odf(path: str, out: _Out) -> None:
    """An OpenDocument text, spreadsheet or presentation."""
    with zipfile.ZipFile(path) as zf:
        if "content.xml" not in zf.namelist():
            return
        try:
            spreadsheet = b"spreadsheet" in zf.read("mimetype")
        except KeyError:
            spreadsheet = path.lower().endswith(".ods")
        depth = 0            # how many paragraphs deep, so only the outermost is cleared
        cells = 0            # how many table cells deep
        cell: list[str] = []
        row: list[str] = []
        listed = 0
        for event, name, elem in _stream(zf, "content.xml"):
            if event == "start":
                if name in ("p", "h"):
                    depth += 1
                elif name == "table-cell":
                    cells += 1
                    cell = []
                elif name == "table-row":
                    row = []
                elif name == "list-item":
                    listed += 1
                elif name == "table" and spreadsheet:
                    out.block(_attr(elem, "name"), "## ")
                elif name == "page":
                    out.rule()
                continue
            if name in ("p", "h"):
                depth -= 1
                text = _odf_text(elem).strip()
                if cells:
                    if text:
                        cell.append(text)
                elif text:
                    level = 0
                    if name == "h":
                        try:
                            level = max(1, min(int(_attr(elem, "outline-level") or 1), 6))
                        except ValueError:
                            level = 1
                    prefix = "#" * level + " " if level else ("- " if listed else "")
                    for i, line in enumerate(text.split("\n")):
                        out.block(line, prefix if i == 0 else "")
                if depth == 0 and not cells:
                    elem.clear()
            elif name == "table-cell":
                cells = max(0, cells - 1)
                try:
                    repeat = max(1, min(int(_attr(elem, "number-columns-repeated") or 1),
                                        COLUMNS_MAX))
                except ValueError:
                    repeat = 1
                if cells == 0:
                    row.extend([" ".join(cell)] * repeat)
            elif name == "table-row":
                if not cells:
                    out.row(row[:COLUMNS_MAX])
                    elem.clear()
            elif name == "table":
                if not cells:
                    out.end_table()
            elif name == "list-item":
                listed = max(0, listed - 1)


#: Which reader a file's extension asks for.
READERS = {
    ".pdf": _pdf,
    ".docx": _docx, ".docm": _docx, ".dotx": _docx,
    ".xlsx": _xlsx, ".xlsm": _xlsx,
    ".pptx": _pptx, ".pptm": _pptx, ".ppsx": _pptx,
    ".odt": _odf, ".ods": _odf, ".odp": _odf,
    ".html": _html, ".htm": _html, ".xhtml": _html, ".svg": _html,
    ".rtf": _rtf,
}

#: Which reader a file's kind asks for, when its extension says nothing.
BY_KIND = {"pdf": _pdf, "text": _plain}


def _inside(ending: str):
    """The reader for a forwarded email or a zip archive, while Files inside files read is on
    (`rouh/inside_files.py`), or None."""
    from . import inside_files

    if ending not in inside_files.ENDINGS or not inside_files.allowed():
        return None
    return {".eml": inside_files.read_eml, ".zip": inside_files.read_zip}[ending]


def reader_for(name: str, kind: str = ""):
    """The reader for a file, or None when nothing here can read it."""
    ending = os.path.splitext(name)[1].lower()
    return READERS.get(ending) or _inside(ending) or BY_KIND.get(kind or "")


def can_read(name: str, kind: str = "") -> bool:
    """Whether there is any point starting a process for this file."""
    return reader_for(name, kind) is not None


def markdown_of(path: str, kind: str = "") -> str:
    """The words in one file, as Markdown, or "" when there are none to read.

    Stops at `TEXT_MAX`, and at the memory ceiling, with what it has so far:
    most of a very long file is worth more to a search than none of it.
    """
    read = reader_for(path, kind)
    if read is None:
        return ""
    out = _Out()
    try:
        read(path, out)
    except (_Full, MemoryError):
        pass
    return _tidy(out.text())


def _hold_back() -> None:
    """The ceiling on memory, and the back of the queue for the processor.

    Set by this process on itself before anything is opened. Setting a limit
    from the parent, between fork and exec, is not safe in a program with
    threads, and Rouh is one.
    """
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (MEMORY, MEMORY))
    except (ImportError, ValueError, OSError):
        pass
    try:
        os.nice(10)
    except OSError:
        pass


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not args:
        print("usage: python -m rouh.extracting <file> [kind]", file=sys.stderr)
        return 2
    _hold_back()
    try:
        text = markdown_of(args[0], args[1] if len(args) > 1 else "")
    except Exception as exc:
        # One line, for Rouh's log: a .docx that is really an old .doc, a zip
        # cut short, a PDF that is not one. The file is still found by name.
        print(f"{type(exc).__name__}: {exc}"[:300], file=sys.stderr)
        return 1
    sys.stdout.buffer.write(text.encode("utf-8", "replace"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
