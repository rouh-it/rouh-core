"""Every edit edit_doc can make to a Google Doc, found by its words and sent as one change.

edit_doc began with three edits (`Docs.append`, `Docs.replace`, `Docs.insert_at_heading`),
and on 16 November 2026 it could not add one row to the SAFE table of a cap table, because
none of the three can touch a table. This is the rest of what the Docs API's batchUpdate
does: text put in before or after words, taken out, or replaced only where it is meant;
rows, columns and cells of a table; bold, links, headings, alignment and lists; tables,
page breaks and pictures put in; the header and the footer; and any one tab.

How it stays right, because a document's positions move with every edit:

- **Everything is found in one fresh reading.** Each edit names what it works on by its
  words, a heading, or a table and a row and a column (`Anchors`), never by a position,
  and all of them are found in the same reading before anything is sent.
- **Nothing found, or more than one found where one was meant, changes nothing.** The
  answer says what was there instead, and the edit is refused before any request goes.
- **One batch, all or nothing.** Every edit becomes a few requests (`Unit`), and the units
  are sent in one batchUpdate, from the end of the document backwards, so an edit near the
  start never moves the place an edit further down was found at. Google applies a batch
  whole or not at all, and the reading's revision goes with it (`requiredRevisionId`), so
  a document somebody changed in the meantime is read again rather than edited blind.
- **Two edits on the same words in one call are refused**, naming both, rather than
  guessed at: the second is made in a call of its own, on the document as the first left it.

The one thing done in two steps is a header or a footer a document does not have yet:
Google gives the new one's id only once it is made, so it is made, then written in.

There is no horizontal line here: the Docs API has no request that puts one in.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .common import CannotDoThat, GoogleSaidNo


def u16(text: str) -> int:
    """How many positions some text takes in a document: Google counts UTF-16 units."""
    return len((text or "").encode("utf-16-le")) // 2


def _norm(text: str) -> str:
    return " ".join((text or "").split()).lower()


def _short(text: str, most: int = 60) -> str:
    text = " ".join((text or "").replace("\n", " / ").split())
    return text if len(text) <= most else text[:most - 3].rstrip() + "..."


#: Every edit edit_doc takes, in the words its schema uses.
OPS = ("append", "replace", "insert_at_heading", "insert", "delete", "style",
       "insert_row", "delete_row", "insert_column", "delete_column", "write_cell",
       "clear_cell", "merge_cells", "unmerge_cells", "insert_table", "delete_table",
       "page_break", "image", "header", "footer")

#: What a model may write for a paragraph's style, and the Docs API's own name for it.
PARAGRAPH_STYLES = {
    "normal": "NORMAL_TEXT", "normal text": "NORMAL_TEXT", "text": "NORMAL_TEXT",
    "title": "TITLE", "subtitle": "SUBTITLE",
    **{f"heading {n}": f"HEADING_{n}" for n in range(1, 7)},
    **{f"heading{n}": f"HEADING_{n}" for n in range(1, 7)},
    **{f"h{n}": f"HEADING_{n}" for n in range(1, 7)},
    **{str(n): f"HEADING_{n}" for n in range(1, 7)},
}

ALIGNMENTS = {"left": "START", "start": "START", "center": "CENTER", "centre": "CENTER",
              "middle": "CENTER", "right": "END", "end": "END", "justify": "JUSTIFIED",
              "justified": "JUSTIFIED"}

LISTS = {"bullet": "BULLET_DISC_CIRCLE_SQUARE", "bullets": "BULLET_DISC_CIRCLE_SQUARE",
         "bulleted": "BULLET_DISC_CIRCLE_SQUARE",
         "numbered": "NUMBERED_DECIMAL_ALPHA_ROMAN", "numbers": "NUMBERED_DECIMAL_ALPHA_ROMAN",
         "number": "NUMBERED_DECIMAL_ALPHA_ROMAN",
         "checkbox": "BULLET_CHECKBOX", "checklist": "BULLET_CHECKBOX", "checkboxes": "BULLET_CHECKBOX"}
NO_LIST = ("none", "off", "no", "remove", "plain")

COLOURS = {"black": "000000", "white": "ffffff", "red": "d93025", "green": "188038",
           "blue": "1a73e8", "yellow": "fbbc04", "orange": "fa7b17", "purple": "9334e6",
           "gray": "5f6368", "grey": "5f6368"}

TEXT_STYLE_KEYS = ("bold", "italic", "underline", "strikethrough", "font_size", "font",
                   "color", "highlight", "link")
PARAGRAPH_KEYS = ("paragraph_style", "align", "list")


# --- The document, as positions -------------------------------------------------------


@dataclass
class Para:
    """One paragraph: where it is, its words with each one's position, and what it is."""

    start: int
    end: int
    text: str
    starts: list[int]
    sizes: list[int]
    style: str
    #: The cell it is in, (table number, row, column), counted from 1, or None.
    cell: tuple | None
    #: Whether it is the last paragraph of the body or of its cell, whose newline
    #: cannot be written after or taken out.
    last: bool = False
    bullet: bool = False

    @property
    def words(self) -> str:
        return self.text.rstrip("\n")


@dataclass
class Cell:
    start: int
    end: int
    content_start: int
    content_end: int
    row: int
    column: int
    paras: list[Para] = field(default_factory=list)
    row_span: int = 1
    column_span: int = 1

    @property
    def text(self) -> str:
        return " / ".join(p.words.replace("￼", "").strip() for p in self.paras
                          if p.words.strip()) or ""

    @property
    def empty(self) -> bool:
        return self.content_end - self.content_start <= 1


@dataclass
class Row:
    start: int
    end: int
    number: int
    cells: list[Cell] = field(default_factory=list)

    @property
    def text(self) -> str:
        return " | ".join(c.text for c in self.cells)


@dataclass
class Table:
    number: int
    start: int
    end: int
    rows: list[Row] = field(default_factory=list)
    columns: int = 0
    in_cell: bool = False

    @property
    def named(self) -> str:
        head = self.rows[0].text if self.rows else ""
        return f'table {self.number} ("{_short(head, 70)}")' if head.strip(" |") else \
            f"table {self.number}"

    @property
    def merged(self) -> bool:
        return any(c.row_span > 1 or c.column_span > 1 for r in self.rows for c in r.cells)


class Body:
    """One body or header of one tab, read into paragraphs, tables and positions.

    Positions are Google's own: UTF-16 units from the start of the segment. Each
    character of the text is kept with the position it starts at, so a passage found
    in the words is a range in the document, wherever runs, chips and pictures fall.
    """

    def __init__(self, content: list | None) -> None:
        self.paras: list[Para] = []
        self.tables: list[Table] = []
        content = content or []
        self.end = int((content[-1].get("endIndex") if content else 1) or 1)
        self._walk(content, cell=None)
        if self.paras:
            # The very last paragraph of the body: its newline is the body's own end.
            self._mark_last(content)
        self.flat = "".join(p.text for p in self.paras)
        self.starts: list[int] = [s for p in self.paras for s in p.starts]
        self.sizes: list[int] = [s for p in self.paras for s in p.sizes]

    def _mark_last(self, content: list) -> None:
        for element in reversed(content):
            if element.get("paragraph") is not None:
                at = int(element.get("startIndex") or 0)
                for one in self.paras:
                    if one.start == at and one.cell is None:
                        one.last = True
                return

    def _walk(self, content: list, cell: tuple | None) -> list[Para]:
        made: list[Para] = []
        for element in content or ():
            paragraph = element.get("paragraph")
            if paragraph is not None:
                para = self._paragraph(element, paragraph, cell)
                self.paras.append(para)
                made.append(para)
            table = element.get("table")
            if table is not None:
                self._table(element, table, inside=cell is not None)
        return made

    def _paragraph(self, element: dict, paragraph: dict, cell: tuple | None) -> Para:
        start = int(element.get("startIndex") or 0)
        text: list[str] = []
        starts: list[int] = []
        sizes: list[int] = []
        for piece in paragraph.get("elements") or ():
            at = int(piece.get("startIndex") or 0)
            run = piece.get("textRun")
            if run is not None:
                for ch in run.get("content") or "":
                    size = 2 if ord(ch) > 0xFFFF else 1
                    text.append(ch)
                    starts.append(at)
                    sizes.append(size)
                    at += size
            else:
                # A chip, a picture, a page break: one mark standing for it.
                text.append("￼")
                starts.append(at)
                sizes.append(max(1, int(piece.get("endIndex") or at + 1) - at))
        style = (paragraph.get("paragraphStyle") or {}).get("namedStyleType") or "NORMAL_TEXT"
        return Para(start=start, end=int(element.get("endIndex") or start + len(text)),
                    text="".join(text), starts=starts, sizes=sizes, style=style, cell=cell,
                    bullet=bool(paragraph.get("bullet")))

    def _table(self, element: dict, table: dict, inside: bool) -> None:
        made = Table(number=len(self.tables) + 1, start=int(element.get("startIndex") or 0),
                     end=int(element.get("endIndex") or 0), columns=int(table.get("columns") or 0),
                     in_cell=inside)
        self.tables.append(made)
        for r, row in enumerate(table.get("tableRows") or (), start=1):
            got = Row(start=int(row.get("startIndex") or 0), end=int(row.get("endIndex") or 0),
                      number=r)
            made.rows.append(got)
            for c, cell in enumerate(row.get("tableCells") or (), start=1):
                content = cell.get("content") or []
                style = cell.get("tableCellStyle") or {}
                one = Cell(start=int(cell.get("startIndex") or 0),
                           end=int(cell.get("endIndex") or 0),
                           content_start=int((content[0] if content else cell).get("startIndex") or 0),
                           content_end=int((content[-1] if content else cell).get("endIndex") or 0),
                           row=r, column=c, row_span=int(style.get("rowSpan") or 1),
                           column_span=int(style.get("columnSpan") or 1))
                got.cells.append(one)
                one.paras = self._walk(content, (made.number, r, c))
                for element_ in reversed(content):
                    if element_.get("paragraph") is not None:
                        at = int(element_.get("startIndex") or 0)
                        for p in one.paras:
                            if p.start == at:
                                p.last = True
                        break
        if not made.columns and made.rows:
            made.columns = max(len(r.cells) for r in made.rows)

    # --- finding ---------------------------------------------------------------

    def matches(self, needle: str, *, match_case: bool = True, lo: int | None = None,
                hi: int | None = None) -> list[tuple[int, int]]:
        """Every place some words are, as (start, end) positions, inside lo..hi if given."""
        if not needle:
            return []
        flags = 0 if match_case else re.IGNORECASE
        found = [(m.start(), m.end()) for m in re.finditer(re.escape(needle), self.flat, flags)]
        if not found and needle.split():
            # The same words with their spacing written differently, a common slip.
            loose = r"\s+".join(re.escape(w) for w in needle.split())
            found = [(m.start(), m.end()) for m in re.finditer(loose, self.flat, flags)]
        out = []
        for a, b in found:
            if b <= a:
                continue
            start, end = self.starts[a], self.starts[b - 1] + self.sizes[b - 1]
            if lo is not None and start < lo:
                continue
            if hi is not None and end > hi:
                continue
            out.append((start, end))
        return out

    def context(self, start: int, end: int) -> str:
        """Some words either side of a range, to tell one match from another."""
        a = next((i for i, s in enumerate(self.starts) if s >= start), len(self.flat))
        b = next((i for i, s in enumerate(self.starts) if s >= end), len(self.flat))
        def plain(text: str) -> str:
            return text.replace("\n", " / ")

        return ("..." + plain(self.flat[max(0, a - 30):a]) + "[" + plain(self.flat[a:b]) + "]"
                + plain(self.flat[b:b + 30]) + "...")

    def para_at(self, index: int) -> Para | None:
        for one in self.paras:
            if one.start <= index < one.end:
                return one
        return None

    def where(self, index: int) -> str:
        """Where a position is, in words: a table's cell, or the heading it is under."""
        para = self.para_at(index)
        if para and para.cell:
            t, r, c = para.cell
            return f"in table {t}, row {r}, column {c}"
        heading = ""
        for one in self.paras:
            if one.start > index:
                break
            if one.cell is None and _is_heading(one.style):
                heading = one.words
        return f'under "{_short(heading, 40)}"' if heading else "at the top"

    def first_para(self) -> Para:
        for one in self.paras:
            if one.cell is None:
                return one
        raise CannotDoThat("That document has no paragraph to write in.")


def _is_heading(style: str) -> bool:
    return style.startswith("HEADING_") or style in ("TITLE", "SUBTITLE")


def _level(style: str) -> int:
    if style == "TITLE":
        return 0
    if style == "SUBTITLE":
        return 1
    if style.startswith("HEADING_"):
        return int(style.split("_")[1])
    return 99


# --- One edit, as requests --------------------------------------------------------------


@dataclass
class Unit:
    """One edit's requests, with what it touches, so a batch can be ordered and checked.

    `key` is where it is: units go from the highest key down. An edit that moves what
    comes after it (`shifts`) is keyed by where it starts; one that only styles is keyed
    by where it ends, so it is sent before anything inside its range moves. `lo` and
    `hi` are what a shifting unit reads and writes, for the check that no two edits in
    one call touch the same words. A `stable` unit names its table only by where the
    table starts and by row and column numbers, which nothing inside the table moves.
    """

    key: int
    lo: int
    hi: int
    shifts: bool
    requests: list
    said: str
    order: int = 0
    stable: bool = False
    tie: tuple = ()
    segment: str = ""
    edit_no: int = 0
    #: For a header or footer that has to be made first: (kind, text, styles).
    later: tuple | None = None


class Plan:
    """Every edit of one call, found in one reading of one tab."""

    def __init__(self, document: dict, tab: str = "") -> None:
        from .docs import pick_tab, tabs_of

        self.document = document
        self.revision = document.get("revisionId") or ""
        tabs = tabs_of(document)
        self.all_tabs = tabs
        self.tab = pick_tab(tabs, tab) if (tab or "").strip() else tabs[0]
        self.tab_id = self.tab.id
        self.raw_tab = _raw_tab(document, self.tab_id)
        self.body = Body((self.tab.body or {}).get("content"))
        self.units: list[Unit] = []

    # --- positions with the tab -----------------------------------------------

    def loc(self, index: int, segment: str = "") -> dict:
        out: dict = {"index": index}
        if segment:
            out["segmentId"] = segment
        if self.tab_id:
            out["tabId"] = self.tab_id
        return out

    def rng(self, start: int, end: int, segment: str = "") -> dict:
        out: dict = {"startIndex": start, "endIndex": end}
        if segment:
            out["segmentId"] = segment
        if self.tab_id:
            out["tabId"] = self.tab_id
        return out

    # --- the anchors ----------------------------------------------------------

    def one_match(self, edit: dict, needle: str, *, lo=None, hi=None, what: str = "find",
                  allow_all: bool = False) -> list[tuple[int, int]]:
        """The place, or with occurrence all every place, the words of an edit are."""
        if not needle:
            raise CannotDoThat(f"Say the words to {what}.")
        match_case = edit.get("match_case")
        match_case = True if match_case is None else bool(match_case)
        if lo is None and hi is None:
            lo, hi = self.scope(edit)
        found = self.body.matches(needle, match_case=match_case, lo=lo, hi=hi)
        scope = self.scope_named(edit)
        if not found:
            hint = ""
            if match_case and self.body.matches(needle, match_case=False, lo=lo, hi=hi):
                hint = " It is there with different capitals: give match_case false."
            elif scope and self.body.matches(needle, match_case=match_case):
                hint = " It is elsewhere in the document, outside that part."
            else:
                elsewhere = self._other_tabs_with(needle)
                if elsewhere:
                    hint = (f" It is in the tab {elsewhere}: give tab to edit that tab.")
            raise CannotDoThat(f"«{_short(needle, 120)}» is not in the document"
                               + (f" {scope}" if scope else "") + "." + hint)
        wanted = edit.get("occurrence")
        if wanted is None or str(wanted).strip() == "":
            if len(found) == 1:
                return found
            if allow_all:
                return found
            listed = "; ".join(f"{n}. {self.body.context(a, b)} ({self.body.where(a)})"
                               for n, (a, b) in enumerate(found[:12], start=1))
            raise CannotDoThat(
                f"«{_short(needle, 80)}» is in the document {len(found)} times"
                + (f" {scope}" if scope else "") + f": {listed}"
                + ("; ..." if len(found) > 12 else "")
                + f". Say which with occurrence (1 to {len(found)}, last, or all).")
        said = str(wanted).strip().lower()
        if said == "all":
            return found
        if said in ("last", "-1"):
            return [found[-1]]
        if said in ("first",):
            return [found[0]]
        try:
            n = int(said)
        except ValueError:
            raise CannotDoThat(f"occurrence is a number, last or all, not {wanted!r}.") from None
        if not 1 <= n <= len(found):
            raise CannotDoThat(f"«{_short(needle, 80)}» is in the document only {len(found)} "
                               f"time{'s' if len(found) != 1 else ''}"
                               + (f" {scope}" if scope else "") + f", so there is no number {n}.")
        return [found[n - 1]]

    def _other_tabs_with(self, needle: str) -> str:
        if len(self.all_tabs) < 2:
            return ""
        for one in self.all_tabs:
            if one is self.tab:
                continue
            body = Body((one.body or {}).get("content"))
            if body.matches(needle, match_case=False):
                return one.named
        return ""

    def scope(self, edit: dict) -> tuple[int | None, int | None]:
        within = edit.get("within")
        if not within:
            return None, None
        if isinstance(within, str):
            within = {"heading": within}
        if not isinstance(within, dict):
            raise CannotDoThat("within is a heading's words, or a table with a row and a column.")
        if within.get("heading"):
            return self.section(within["heading"])
        if within.get("table") is not None or within.get("row") is not None:
            table = self.table(within.get("table"))
            if within.get("row") is not None and within.get("column") is not None:
                cell = self.cell(table, within.get("row"), within.get("column"))
                return cell.content_start, cell.content_end
            if within.get("row") is not None:
                row = self.row(table, within.get("row"))
                return row.start, row.end
            return table.start, table.end
        raise CannotDoThat("within is a heading's words, or a table with a row and a column.")

    def scope_named(self, edit: dict) -> str:
        within = edit.get("within")
        if not within:
            return ""
        if isinstance(within, str):
            return f'under the heading "{within}"'
        if isinstance(within, dict) and within.get("heading"):
            return f'under the heading "{within["heading"]}"'
        if isinstance(within, dict):
            parts = [f"{k} {within[k]}" for k in ("table", "row", "column")
                     if within.get(k) is not None]
            return "in " + ", ".join(parts)
        return ""

    def heading_para(self, heading: str) -> Para:
        wanted = _norm(heading)
        if not wanted:
            raise CannotDoThat("Say which heading.")
        fits = [p for p in self.body.paras if p.cell is None and _norm(p.words) == wanted]
        if len(fits) > 1:
            styled = [p for p in fits if _is_heading(p.style)]
            fits = styled or fits
        if not fits:
            near = [p.words for p in self.body.paras if p.cell is None and _is_heading(p.style)]
            raise CannotDoThat(f"There is no heading called {heading!r} in that document."
                               + (" Its headings are: " + "; ".join(
                                   f'"{_short(w, 50)}"' for w in near[:20]) + "." if near else ""))
        return fits[0]

    def section(self, heading: str) -> tuple[int, int]:
        """From just after a heading to the next heading as big or bigger."""
        para = self.heading_para(heading)
        level = _level(para.style)
        end = self.body.end
        seen = False
        for one in self.body.paras:
            if one is para:
                seen = True
                continue
            if seen and one.cell is None and _is_heading(one.style) and _level(one.style) <= level:
                end = one.start
                break
        return para.end, end

    # --- tables ---------------------------------------------------------------

    def table(self, ref) -> Table:
        tables = self.body.tables
        if not tables:
            raise CannotDoThat("That document has no table" + (
                f" in the tab {self.tab.named}" if len(self.all_tabs) > 1 else "") + ".")
        listed = "; ".join(t.named for t in tables[:20])
        if ref is None or str(ref).strip() == "":
            if len(tables) == 1:
                return tables[0]
            raise CannotDoThat(f"Say which table: there are {len(tables)}: {listed}.")
        said = str(ref).strip()
        if said.lower() == "last":
            return tables[-1]
        if said.lower() == "first":
            return tables[0]
        if re.fullmatch(r"-?\d+", said):
            n = int(said)
            if n < 0:
                n = len(tables) + 1 + n
            if 1 <= n <= len(tables):
                return tables[n - 1]
            raise CannotDoThat(f"There is no table {said}: there are {len(tables)}: {listed}.")
        wanted = _norm(said)
        fits = [t for t in tables if any(wanted in _norm(c.text) for r in t.rows for c in r.cells)]
        if len(fits) > 1:
            head = [t for t in fits if t.rows and any(wanted in _norm(c.text) for c in t.rows[0].cells)]
            fits = head if len(head) == 1 else fits
        if len(fits) == 1:
            return fits[0]
        if not fits:
            raise CannotDoThat(f"No table has «{said}» in it. The tables are: {listed}.")
        raise CannotDoThat(f"More than one table has «{said}» in it: "
                           + "; ".join(t.named for t in fits) + ". Say which by its number.")

    def row(self, table: Table, ref, *, default_last: bool = False) -> Row:
        rows = table.rows
        if ref is None or str(ref).strip() == "":
            if default_last:
                return rows[-1]
            raise CannotDoThat(f"Say which row of {table.named}: a number from 1 to "
                               f"{len(rows)}, or words in it.")
        said = str(ref).strip()
        if said.lower() == "last":
            return rows[-1]
        if said.lower() in ("first", "header"):
            return rows[0]
        if re.fullmatch(r"-?\d+", said):
            n = int(said)
            if n < 0:
                n = len(rows) + 1 + n
            if 1 <= n <= len(rows):
                return rows[n - 1]
            raise CannotDoThat(f"{table.named} has {len(rows)} rows, so there is no row {said}.")
        wanted = _norm(said)
        exact = [r for r in rows if any(_norm(c.text) == wanted for c in r.cells)]
        fits = exact or [r for r in rows if any(wanted in _norm(c.text) for c in r.cells)]
        if len(fits) == 1:
            return fits[0]
        if not fits:
            raise CannotDoThat(f"No row of {table.named} has «{said}» in it. Its rows are: "
                               + "; ".join(f"{r.number}. {_short(r.text, 60)}" for r in rows[:30])
                               + ".")
        raise CannotDoThat(f"More than one row of {table.named} has «{said}» in it: "
                           + "; ".join(f"row {r.number}: {_short(r.text, 60)}" for r in fits)
                           + ". Say which by its number.")

    def column(self, table: Table, ref, *, default_last: bool = False) -> int:
        """A column's number, counted from 1, by number or by the words in its header."""
        count = table.columns
        if ref is None or str(ref).strip() == "":
            if default_last:
                return count
            raise CannotDoThat(f"Say which column of {table.named}: a number from 1 to {count}, "
                               "or the words at its top.")
        said = str(ref).strip()
        if said.lower() == "last":
            return count
        if said.lower() == "first":
            return 1
        if re.fullmatch(r"-?\d+", said):
            n = int(said)
            if n < 0:
                n = count + 1 + n
            if 1 <= n <= count:
                return n
            raise CannotDoThat(f"{table.named} has {count} columns, so there is no column {said}.")
        wanted = _norm(said)
        head = table.rows[0].cells if table.rows else []
        exact = [c.column for c in head if _norm(c.text) == wanted]
        fits = exact or [c.column for c in head if wanted in _norm(c.text)]
        if len(fits) == 1:
            return fits[0]
        heads = "; ".join(f"{c.column}. {_short(c.text, 30)}" for c in head)
        if not fits:
            raise CannotDoThat(f"No column of {table.named} has «{said}» at its top. Its "
                               f"columns are: {heads}.")
        raise CannotDoThat(f"More than one column of {table.named} has «{said}» at its top: "
                           f"{heads}. Say which by its number.")

    def cell(self, table: Table, row_ref, column_ref) -> Cell:
        row = self.row(table, row_ref)
        column = self.column(table, column_ref)
        if column > len(row.cells):
            raise CannotDoThat(f"Row {row.number} of {table.named} has only {len(row.cells)} cells.")
        return row.cells[column - 1]

    def table_start(self, table: Table) -> dict:
        return {"tableStartLocation": self.loc(table.start)}

    # --- where something goes -------------------------------------------------

    def spot(self, edit: dict, *, own_paragraph: bool | None = None,
             for_table: bool = False) -> tuple[int, str, str, str]:
        """Where an edit puts something: (position, text before, text after, in words).

        The text before and after are the newlines that make it a paragraph of its own
        when it is meant to be one.
        """
        new_para = edit.get("new_paragraph")
        new_para = own_paragraph if new_para is None else bool(new_para)
        if edit.get("before") or edit.get("after"):
            after = bool(edit.get("after"))
            needle = edit.get("after") if after else edit.get("before")
            (a, b), = self.one_match(edit, needle, what="put it " + ("after" if after else "before"))
            where = f'{"after" if after else "before"} «{_short(needle, 50)}»'
            if for_table:
                para = self.body.para_at(b - 1 if after else a)
                if after:
                    return para.end - 1, "", "", where
                return para.start, "", "", where
            if not new_para:
                return (b if after else a), "", "", where
            para = self.body.para_at(b - 1 if after else a)
            if not after:
                return para.start, "", "\n", where
            return self._after_para(para) + (where,)
        if edit.get("heading"):
            para = self.heading_para(edit["heading"])
            where = f'under the heading "{_short(para.words, 50)}"'
            if for_table:
                return para.end - 1, "", "", where
            return self._after_para(para) + (where,)
        if edit.get("table") is not None and edit.get("row") is not None \
                and edit.get("column") is not None:
            table = self.table(edit.get("table"))
            cell = self.cell(table, edit.get("row"), edit.get("column"))
            where = f"in {table.named}, row {cell.row}, column {cell.column}"
            lead = "\n" if (new_para and not cell.empty) else ""
            return cell.content_end - 1, lead, "", where
        at = str(edit.get("at") or "end").strip().lower()
        if at in ("start", "top", "beginning"):
            first = self.body.first_para()
            if for_table:
                return first.start, "", "", "at the start"
            empty = len(self.body.paras) == 1 and not first.words
            if new_para is False or empty:
                return first.start, "", "", "at the start"
            return first.start, "", "\n", "at the start"
        if at in ("end", "bottom"):
            at_index = max(1, self.body.end - 1)
            if for_table:
                return at_index, "", "", "at the end"
            lead = "" if (at_index <= 1 or new_para is False) else "\n"
            last = self.body.paras[-1] if self.body.paras else None
            if last is not None and not last.words and last.cell is None and new_para is not False:
                lead = ""  # an empty last line is written in rather than left above it
            return at_index, lead, "", "at the end"
        raise CannotDoThat("Say where: before or after some words, under a heading, in a table "
                           "cell, or at the start or the end.")

    def _after_para(self, para: Para) -> tuple[int, str, str]:
        if para.last:
            return para.end - 1, "\n", ""
        return para.end, "", "\n"

    # --- styles ---------------------------------------------------------------

    def text_style(self, edit: dict) -> tuple[dict, list[str]]:
        style: dict = {}
        fields: list[str] = []
        for key, name in (("bold", "bold"), ("italic", "italic"), ("underline", "underline"),
                          ("strikethrough", "strikethrough")):
            if edit.get(key) is not None:
                style[name] = bool(edit[key])
                fields.append(name)
        if edit.get("font_size") is not None:
            try:
                size = float(edit["font_size"])
            except (TypeError, ValueError):
                raise CannotDoThat(f"font_size is a number of points, not {edit['font_size']!r}.") from None
            style["fontSize"] = {"magnitude": size, "unit": "PT"}
            fields.append("fontSize")
        if edit.get("font"):
            style["weightedFontFamily"] = {"fontFamily": str(edit["font"])}
            fields.append("weightedFontFamily")
        for key, name in (("color", "foregroundColor"), ("highlight", "backgroundColor")):
            if key in edit and edit[key] is not None:
                rgb = _rgb(edit[key])
                if rgb is not None:
                    style[name] = {"color": {"rgbColor": rgb}}
                fields.append(name)
        if "link" in edit and edit["link"] is not None:
            address = str(edit["link"]).strip()
            if address:
                if not re.match(r"^(https?://|mailto:|#)", address):
                    address = "https://" + address
                style["link"] = {"url": address}
            fields.append("link")
        return style, fields

    def style_requests(self, edit: dict, start: int, end: int, segment: str = "") -> tuple[list, list]:
        """The requests that style a range, and what they did, in words."""
        out: list = []
        said: list[str] = []
        if end <= start:
            return out, said
        style, fields = self.text_style(edit)
        if fields:
            out.append({"updateTextStyle": {"range": self.rng(start, end, segment),
                                            "textStyle": style, "fields": ",".join(fields)}})
            said.extend(_style_words(edit))
        paragraph: dict = {}
        pfields: list[str] = []
        if edit.get("paragraph_style"):
            name = PARAGRAPH_STYLES.get(_norm(str(edit["paragraph_style"])))
            if not name:
                raise CannotDoThat(f"paragraph_style is normal, title, subtitle or heading 1 to "
                                   f"heading 6, not {edit['paragraph_style']!r}.")
            paragraph["namedStyleType"] = name
            pfields.append("namedStyleType")
            said.append("made " + name.lower().replace("_", " ").replace("normal text", "normal text"))
        if edit.get("align"):
            name = ALIGNMENTS.get(_norm(str(edit["align"])))
            if not name:
                raise CannotDoThat(f"align is left, center, right or justify, not {edit['align']!r}.")
            paragraph["alignment"] = name
            pfields.append("alignment")
            said.append(f"aligned {str(edit['align']).lower()}")
        if pfields:
            out.append({"updateParagraphStyle": {"range": self.rng(start, end, segment),
                                                 "paragraphStyle": paragraph,
                                                 "fields": ",".join(pfields)}})
        if edit.get("list"):
            kind = _norm(str(edit["list"]))
            if kind in NO_LIST:
                out.append({"deleteParagraphBullets": {"range": self.rng(start, end, segment)}})
                said.append("taken out of its list")
            elif kind in LISTS:
                out.append({"createParagraphBullets": {"range": self.rng(start, end, segment),
                                                       "bulletPreset": LISTS[kind]}})
                said.append(f"made a {kind.rstrip('s') if kind != 'bullets' else 'bullet'} list"
                            .replace("bulleted list", "bullet list"))
            else:
                raise CannotDoThat(f"list is bullet, numbered, checkbox or none, not {edit['list']!r}.")
        return out, said

    # --- the edits ------------------------------------------------------------

    def add(self, edit: dict, order: int) -> None:
        op = str(edit.get("op") or "").strip().lower()
        if op in ("horizontal_rule", "horizontal_line", "rule", "line"):
            raise CannotDoThat("The Google Docs API has no way to put in a horizontal line, so "
                               "that cannot be done from here. A page_break, or a line of "
                               "underscores, are the nearest.")
        handler = getattr(self, "_op_" + op, None)
        if handler is None or op not in OPS:
            raise CannotDoThat(f"{op!r} is not something I can do to a document. It is one of: "
                               + ", ".join(OPS) + ".")
        before = len(self.units)
        handler(edit, order)
        for unit in self.units[before:]:
            unit.order = order
            unit.edit_no = order

    def _push(self, **kwargs) -> Unit:
        unit = Unit(**kwargs)
        self.units.append(unit)
        return unit

    def _insert_unit(self, edit: dict, index: int, lead: str, trail: str, text: str,
                     where: str, segment: str = "") -> None:
        if not text and not lead and not trail:
            raise CannotDoThat("Say the words to put in.")
        reqs = [{"insertText": {"location": self.loc(index, segment), "text": lead + text + trail}}]
        start = index + u16(lead)
        styled, words = self.style_requests(edit, start, start + u16(text), segment)
        reqs.extend(styled)
        said = f"put «{_short(text, 80)}» {where}"
        if words:
            said += ", " + " and ".join(words)
        self._push(key=index, lo=index, hi=index, shifts=True, requests=reqs, said=said,
                   segment=segment)

    def _op_append(self, edit: dict, order: int) -> None:
        index, lead, trail, where = self.spot({"at": "end"})
        self._insert_unit(edit, index, lead, trail, edit.get("text") or "", "at the end")

    def _op_insert_at_heading(self, edit: dict, order: int) -> None:
        para = self.heading_para(edit.get("heading") or "")
        index, lead, trail = self._after_para(para)
        self._insert_unit(edit, index, lead, trail, (edit.get("text") or "").rstrip("\n"),
                          f'under the heading "{_short(para.words, 50)}"')

    def _op_insert(self, edit: dict, order: int) -> None:
        index, lead, trail, where = self.spot(edit)
        text = edit.get("text") or ""
        if trail == "\n":
            text = text.rstrip("\n")
        self._insert_unit(edit, index, lead, trail, text, where)

    def _op_replace(self, edit: dict, order: int) -> None:
        needle = edit.get("find") or ""
        put = edit.get("text") or ""
        found = self.one_match(edit, needle, what="replace", allow_all=edit.get("occurrence") is None)
        for a, b in sorted(found, reverse=True):
            reqs = [{"deleteContentRange": {"range": self.rng(a, b)}}]
            if put:
                reqs.append({"insertText": {"location": self.loc(a), "text": put}})
                styled, _ = self.style_requests(edit, a, a + u16(put))
                reqs.extend(styled)
            self._push(key=a, lo=a, hi=b, shifts=True, requests=reqs,
                       said="", tie=(a,))
        count = len(found)
        which = ""
        occurrence = edit.get("occurrence")
        if occurrence is not None and str(occurrence).lower() != "all":
            which = f" (number {occurrence} of them)" if str(occurrence).isdigit() else f" ({occurrence})"
        where = f" {self.body.where(found[0][0])}" if count == 1 else ""
        self.units[-1].said = (f"replaced {count} occurrence{'s' if count != 1 else ''} of "
                               f"«{_short(needle, 60)}»{which}{where} with «{_short(put, 60)}»")

    def _op_delete(self, edit: dict, order: int) -> None:
        needle = edit.get("find") or ""
        found = self.one_match(edit, needle, what="take out",
                               allow_all=str(edit.get("occurrence") or "").lower() == "all")
        through = edit.get("through")
        ranges = []
        for a, b in found:
            if through:
                ends = [r for r in self.body.matches(through, match_case=edit.get("match_case")
                                                     is not False) if r[0] >= a]
                if not ends:
                    raise CannotDoThat(f"«{_short(through, 80)}» is not after «{_short(needle, 60)}» "
                                       "in the document, so there is nothing to take out up to it.")
                b = ends[0][1]
            if edit.get("whole_paragraphs"):
                first, last = self.body.para_at(a), self.body.para_at(b - 1)
                a, b = first.start, last.end
            ranges.append(self._deletable(a, b))
        for a, b in sorted(ranges, reverse=True):
            self._push(key=a, lo=a, hi=b, shifts=True,
                       requests=[{"deleteContentRange": {"range": self.rng(a, b)}}], said="")
        what = f"«{_short(needle, 60)}»" + (f" through «{_short(through, 60)}»" if through else "")
        self.units[-1].said = (f"took out {what}"
                               + (" (whole paragraphs)" if edit.get("whole_paragraphs") else "")
                               + (f", {len(ranges)} times" if len(ranges) > 1 else
                                  f" {self.body.where(ranges[0][0])}"))

    def _deletable(self, a: int, b: int) -> tuple[int, int]:
        """A range the Docs API will take out: never across a table's edge, never the last newline."""
        first, last = self.body.para_at(a), self.body.para_at(max(a, b - 1))
        if first is None or last is None or first.cell != last.cell:
            raise CannotDoThat("That passage runs into or out of a table. Take out a table with "
                               "delete_table, or its rows with delete_row.")
        if first.cell is None:
            for table in self.body.tables:
                if a < table.start < b:
                    raise CannotDoThat(f"That passage has {table.named} inside it. Take the table "
                                       "out with delete_table, then the words around it.")
        if last.last and b >= last.end:
            # The last newline of the body or of a cell cannot go. When the whole of the last
            # paragraph goes, the newline before it goes instead, so no empty line is left.
            b = last.end - 1
            if a == first.start:
                before = [p for p in self.body.paras if p.end == a and p.cell == first.cell]
                if before:
                    a -= 1
        if b <= a:
            raise CannotDoThat("There is nothing there that can be taken out: a cell or a document "
                               "always keeps its last line.")
        return a, b

    def _op_style(self, edit: dict, order: int) -> None:
        targets: list[tuple[int, int]] = []
        if edit.get("find"):
            found = self.one_match(edit, edit["find"], what="style",
                                   allow_all=str(edit.get("occurrence") or "").lower() == "all")
            for a, b in found:
                if edit.get("through"):
                    ends = [r for r in self.body.matches(edit["through"]) if r[0] >= a]
                    if not ends:
                        raise CannotDoThat(f"«{_short(edit['through'], 80)}» is not after "
                                           f"«{_short(edit['find'], 60)}» in the document.")
                    b = ends[0][1]
                targets.append((a, b))
            what = f"«{_short(edit['find'], 60)}»" + (
                f" through «{_short(edit['through'], 60)}»" if edit.get("through") else "")
        elif edit.get("heading"):
            para = self.heading_para(edit["heading"])
            targets.append((para.start, para.end - 1 if para.end - 1 > para.start else para.end))
            what = f'the heading "{_short(para.words, 50)}"'
        elif edit.get("table") is not None:
            table = self.table(edit.get("table"))
            if edit.get("row") is not None and edit.get("column") is not None:
                cell = self.cell(table, edit.get("row"), edit.get("column"))
                targets.append((cell.content_start, max(cell.content_start + 1, cell.content_end - 1)))
                what = f"row {cell.row}, column {cell.column} of {table.named}"
            elif edit.get("row") is not None:
                row = self.row(table, edit.get("row"))
                targets.extend((c.content_start, max(c.content_start + 1, c.content_end - 1))
                               for c in row.cells)
                what = f"row {row.number} of {table.named}"
            elif edit.get("column") is not None:
                col = self.column(table, edit.get("column"))
                targets.extend((r.cells[col - 1].content_start,
                                max(r.cells[col - 1].content_start + 1, r.cells[col - 1].content_end - 1))
                               for r in table.rows if len(r.cells) >= col)
                what = f"column {col} of {table.named}"
            else:
                targets.extend((c.content_start, max(c.content_start + 1, c.content_end - 1))
                               for r in table.rows for c in r.cells)
                what = table.named
        else:
            raise CannotDoThat("Say what to style: words with find, a heading, or a table's row, "
                               "column or cell.")
        words: list[str] = []
        for a, b in targets:
            reqs, words = self.style_requests(edit, a, b)
            if not reqs:
                raise CannotDoThat("Say how to style it: bold, italic, underline, strikethrough, "
                                   "font_size, font, color, highlight, link, paragraph_style, "
                                   "align or list.")
            self._push(key=b, lo=a, hi=b, shifts=False, requests=reqs, said="")
        self.units[-1].said = f"{what}: " + ", ".join(words) + (
            f" ({len(targets)} places)" if len(targets) > 1 and edit.get("find") else "")

    # --- tables ---------------------------------------------------------------

    def _op_insert_row(self, edit: dict, order: int) -> None:
        table = self.table(edit.get("table"))
        side = _norm(str(edit.get("side") or ("above" if edit.get("above") else "below")))
        above = side in ("above", "before", "up")
        row = self.row(table, edit.get("row"), default_last=True)
        cells = list(edit.get("cells") or [])
        if len(cells) > len(row.cells):
            raise CannotDoThat(f"{table.named} has {len(row.cells)} cells in a row, and "
                               f"{len(cells)} were given.")
        reqs: list = [{"insertTableRow": {"tableCellLocation": {
            **self.table_start(table), "rowIndex": row.number - 1, "columnIndex": 0},
            "insertBelow": not above}}]
        new_start = row.start if above else row.end
        if cells and any(str(c or "") for c in cells):
            if table.merged:
                raise CannotDoThat(f"{table.named} has merged cells, so a new row cannot be filled "
                                   "in the same call. Add the row empty, then write its cells "
                                   "with write_cell in a second call.")
            first = row.cells[0]
            lead_row = first.start - row.start
            lead_cell = first.content_start - first.start
            at = new_start + lead_row + lead_cell
            step = lead_cell + 1
            for j in range(len(cells) - 1, -1, -1):
                text = str(cells[j] if cells[j] is not None else "")
                if text:
                    here = at + j * step
                    reqs.append({"insertText": {"location": self.loc(here), "text": text}})
                    styled, _ = self.style_requests(edit, here, here + u16(text))
                    reqs.extend(styled)
        filled = " | ".join(str(c or "") for c in cells)
        said = (f"added a row {'above' if above else 'below'} row {row.number} "
                f"(«{_short(row.text, 50)}») in {table.named}"
                + (f": {filled}" if filled.strip(" |") else ", empty"))
        self._push(key=new_start, lo=new_start, hi=new_start, shifts=True, requests=reqs, said=said)

    def _op_delete_row(self, edit: dict, order: int) -> None:
        table = self.table(edit.get("table"))
        row = self.row(table, edit.get("row"))
        if len(table.rows) == 1:
            raise CannotDoThat(f"{table.named} has only that one row: take the table out with "
                               "delete_table instead.")
        self._push(key=row.start, lo=row.start, hi=row.end, shifts=True, requests=[
            {"deleteTableRow": {"tableCellLocation": {
                **self.table_start(table), "rowIndex": row.number - 1, "columnIndex": 0}}}],
            said=f"took out row {row.number} of {table.named} («{_short(row.text, 70)}»)")

    def _op_insert_column(self, edit: dict, order: int) -> None:
        table = self.table(edit.get("table"))
        side = _norm(str(edit.get("side") or ("left" if edit.get("left") else "right")))
        left = side in ("left", "before")
        col = self.column(table, edit.get("column"), default_last=True)
        cells = list(edit.get("cells") or [])
        if len(cells) > len(table.rows):
            raise CannotDoThat(f"{table.named} has {len(table.rows)} rows, and {len(cells)} cells "
                               "were given for the new column.")
        reqs: list = [{"insertTableColumn": {"tableCellLocation": {
            **self.table_start(table), "rowIndex": 0, "columnIndex": col - 1},
            "insertRight": not left}}]
        filled = any(str(c or "") for c in cells)
        if filled:
            if table.merged:
                raise CannotDoThat(f"{table.named} has merged cells, so a new column cannot be "
                                   "filled in the same call. Add it empty, then write its cells "
                                   "with write_cell in a second call.")
            spots = []
            for k, row in enumerate(table.rows):
                ref = row.cells[col - 1]
                lead_cell = ref.content_start - ref.start
                point = ref.start if left else ref.end
                spots.append(point + k * (lead_cell + 1) + lead_cell)
            for k in range(len(cells) - 1, -1, -1):
                text = str(cells[k] if cells[k] is not None else "")
                if text:
                    reqs.append({"insertText": {"location": self.loc(spots[k]), "text": text}})
                    styled, _ = self.style_requests(edit, spots[k], spots[k] + u16(text))
                    reqs.extend(styled)
        head = table.rows[0].cells[col - 1].text if table.rows else ""
        said = (f"added a column {'left' if left else 'right'} of column {col} "
                f"(«{_short(head, 40)}») in {table.named}"
                + (": " + " | ".join(str(c or "") for c in cells) if filled else ", empty"))
        if filled:
            self._push(key=table.start, lo=table.start, hi=table.end, shifts=True,
                       requests=reqs, said=said)
        else:
            self._push(key=table.start, lo=table.start, hi=table.start, shifts=True,
                       requests=reqs, said=said, stable=True,
                       tie=(-(col + (0 if left else 1)),))

    def _op_delete_column(self, edit: dict, order: int) -> None:
        table = self.table(edit.get("table"))
        col = self.column(table, edit.get("column"))
        if table.columns == 1:
            raise CannotDoThat(f"{table.named} has only that one column: take the table out with "
                               "delete_table instead.")
        head = table.rows[0].cells[col - 1].text if table.rows else ""
        self._push(key=table.start, lo=table.start, hi=table.start, shifts=True, stable=True,
                   tie=(-col,), requests=[{"deleteTableColumn": {"tableCellLocation": {
                       **self.table_start(table), "rowIndex": 0, "columnIndex": col - 1}}}],
                   said=f"took out column {col} («{_short(head, 40)}») of {table.named}")

    def _op_write_cell(self, edit: dict, order: int, *, clear: bool = False) -> None:
        table = self.table(edit.get("table"))
        cell = self.cell(table, edit.get("row"), edit.get("column"))
        text = "" if clear else str(edit.get("text") or "")
        a, b = cell.content_start, cell.content_end - 1
        reqs: list = []
        if b > a:
            reqs.append({"deleteContentRange": {"range": self.rng(a, b)}})
        if text:
            reqs.append({"insertText": {"location": self.loc(a), "text": text}})
            styled, _ = self.style_requests(edit, a, a + u16(text))
            reqs.extend(styled)
        if not reqs:
            raise CannotDoThat(f"Row {cell.row}, column {cell.column} of {table.named} is already "
                               "empty." if clear else "Say the words to write in the cell.")
        was = cell.text
        said = (f"cleared row {cell.row}, column {cell.column} of {table.named} (was «{_short(was, 50)}»)"
                if clear else
                f"wrote «{_short(text, 60)}» in row {cell.row}, column {cell.column} of {table.named}"
                + (f" (was «{_short(was, 50)}»)" if was else ""))
        self._push(key=a, lo=a, hi=max(a, b), shifts=True, requests=reqs, said=said)

    def _op_clear_cell(self, edit: dict, order: int) -> None:
        self._op_write_cell(edit, order, clear=True)

    def _merge(self, edit: dict, merge: bool) -> None:
        table = self.table(edit.get("table"))
        first = self.cell(table, edit.get("row"), edit.get("column"))
        last_row = self.row(table, edit.get("to_row")) if edit.get("to_row") is not None else \
            table.rows[first.row - 1]
        last_col = self.column(table, edit.get("to_column")) if edit.get("to_column") is not None \
            else first.column
        rows = last_row.number - first.row + 1
        cols = last_col - first.column + 1
        if rows < 1 or cols < 1:
            raise CannotDoThat("to_row and to_column are the last row and column, below and right "
                               "of the first.")
        if merge and rows * cols < 2:
            raise CannotDoThat("Merging needs more than one cell: give to_row or to_column.")
        name = "mergeTableCells" if merge else "unmergeTableCells"
        span_end = last_row.end
        self._push(key=table.rows[first.row - 1].start, lo=table.rows[first.row - 1].start,
                   hi=span_end, shifts=True, requests=[{name: {"tableRange": {
                       "tableCellLocation": {**self.table_start(table), "rowIndex": first.row - 1,
                                             "columnIndex": first.column - 1},
                       "rowSpan": rows, "columnSpan": cols}}}],
                   said=(f"{'merged' if merge else 'unmerged'} rows {first.row} to {last_row.number}, "
                         f"columns {first.column} to {last_col} of {table.named}"))

    def _op_merge_cells(self, edit: dict, order: int) -> None:
        self._merge(edit, True)

    def _op_unmerge_cells(self, edit: dict, order: int) -> None:
        self._merge(edit, False)

    def _op_insert_table(self, edit: dict, order: int) -> None:
        rows = edit.get("rows")
        if not isinstance(rows, list) or not rows or not all(isinstance(r, list) for r in rows):
            raise CannotDoThat("rows is the table's rows, each a list of its cells' words, the "
                               "top row first: [[\"Name\", \"Amount\"], [\"Acme\", \"100\"]].")
        columns = max(len(r) for r in rows)
        if not columns:
            raise CannotDoThat("Each row needs at least one cell.")
        index, _, _, where = self.spot(edit, for_table=True)
        reqs: list = [{"insertTable": {"rows": len(rows), "columns": columns,
                                       "location": self.loc(index)}}]
        # The table starts one past where it is put, after the newline Google adds before it;
        # then a row's mark, a cell's mark, and the cell's own empty line.
        first = index + 4
        fill = []
        for r, row in enumerate(rows):
            for c in range(columns):
                text = str(row[c]) if c < len(row) and row[c] is not None else ""
                if text:
                    fill.append((first + r * (2 * columns + 1) + 2 * c, text))
        for at, text in sorted(fill, reverse=True):
            reqs.append({"insertText": {"location": self.loc(at), "text": text}})
        self._push(key=index, lo=index, hi=index, shifts=True, requests=reqs,
                   said=(f"put in a table of {len(rows)} row{'s' if len(rows) != 1 else ''} and "
                         f"{columns} column{'s' if columns != 1 else ''} {where}, top row: "
                         + " | ".join(str(c or "") for c in rows[0])))

    def _op_delete_table(self, edit: dict, order: int) -> None:
        table = self.table(edit.get("table"))
        self._push(key=table.start, lo=table.start, hi=table.end, shifts=True, requests=[
            {"deleteContentRange": {"range": self.rng(table.start, table.end)}}],
            said=f"took out {table.named}, {len(table.rows)} rows")

    # --- structure -------------------------------------------------------------

    def _op_page_break(self, edit: dict, order: int) -> None:
        index, _, _, where = self.spot(edit, own_paragraph=False)
        para = self.body.para_at(index) or self.body.para_at(index - 1)
        if para is not None and para.cell:
            raise CannotDoThat("A page break cannot go inside a table.")
        self._push(key=index, lo=index, hi=index, shifts=True,
                   requests=[{"insertPageBreak": {"location": self.loc(index)}}],
                   said=f"put in a page break {where}")

    def _op_image(self, edit: dict, order: int) -> None:
        address = str(edit.get("url") or "").strip()
        if not address.startswith("https://"):
            raise CannotDoThat("An image is put in from its https:// address, which Google must "
                               "be able to fetch without signing in (PNG, JPEG or GIF).")
        index, _, _, where = self.spot(edit, own_paragraph=False)
        request: dict = {"uri": address, "location": self.loc(index)}
        size: dict = {}
        for key, name in (("width", "width"), ("height", "height")):
            if edit.get(key) is not None:
                try:
                    size[name] = {"magnitude": float(edit[key]), "unit": "PT"}
                except (TypeError, ValueError):
                    raise CannotDoThat(f"{key} is a number of points.") from None
        if size:
            request["objectSize"] = size
        self._push(key=index, lo=index, hi=index, shifts=True,
                   requests=[{"insertInlineImage": request}],
                   said=f"put in the image {_short(address, 80)} {where}")

    def _op_header(self, edit: dict, order: int, kind: str = "header") -> None:
        text = str(edit.get("text") or "")
        doc_tab = self.raw_tab
        style = doc_tab.get("documentStyle") or {}
        existing_id = style.get("defaultHeaderId" if kind == "header" else "defaultFooterId")
        segments = doc_tab.get("headers" if kind == "header" else "footers") or {}
        if existing_id and existing_id in segments:
            content = segments[existing_id].get("content") or []
            seg = Body(content)
            a = int((content[0] if content else {}).get("startIndex") or 0)
            b = max(a, seg.end - 1)
            reqs: list = []
            if b > a:
                reqs.append({"deleteContentRange": {"range": self.rng(a, b, existing_id)}})
            if text:
                reqs.append({"insertText": {"location": self.loc(a, existing_id), "text": text}})
                styled, _ = self.style_requests(edit, a, a + u16(text), existing_id)
                reqs.extend(styled)
            was = seg.flat.strip()
            self._push(key=10 ** 9, lo=0, hi=0, shifts=True, segment=existing_id, requests=reqs,
                       said=(f"set the {kind} to «{_short(text, 60)}»" if text else
                             f"cleared the {kind}") + (f" (was «{_short(was, 50)}»)" if was else ""))
            return
        if not text:
            raise CannotDoThat(f"That document has no {kind}, so there is nothing to clear.")
        self._push(key=10 ** 9, lo=0, hi=0, shifts=True, segment="new", requests=[],
                   said=f"made a {kind}: «{_short(text, 60)}»", later=(kind, text, edit))

    def _op_footer(self, edit: dict, order: int) -> None:
        self._op_header(edit, order, kind="footer")

    # --- the batch -------------------------------------------------------------

    def ordered(self) -> list[Unit]:
        """The units, from the end of the document backwards, checked for any two on the same words."""
        body = [u for u in self.units if not u.segment]
        movers = [u for u in body if u.shifts and not u.stable]
        for i, one in enumerate(movers):
            for two in movers[i + 1:]:
                if one.edit_no == two.edit_no:
                    continue
                if _overlap(one, two):
                    raise CannotDoThat(
                        f"Edits {one.edit_no + 1} and {two.edit_no + 1} work on the same part of the "
                        f"document ({one.said or 'one'}; {two.said or 'the other'}), so they cannot "
                        "go in one call: make the second in a call of its own, after this one. "
                        "Nothing was changed.")

        def sort_key(u: Unit):
            return (-u.key, 1 if u.shifts else 0, u.tie, -u.order if u.shifts else u.order)

        return sorted(self.units, key=sort_key)

    def requests(self) -> list:
        out: list = []
        for unit in self.ordered():
            out.extend(unit.requests)
        return out


def _overlap(one: Unit, two: Unit) -> bool:
    if one.lo == one.hi and two.lo == two.hi:
        return False
    if one.lo == one.hi:
        return two.lo < one.lo < two.hi
    if two.lo == two.hi:
        return one.lo < two.lo < one.hi
    return max(one.lo, two.lo) < min(one.hi, two.hi)


def _raw_tab(document: dict, tab_id: str) -> dict:
    """The tab's own documentTab as Google sent it, with its headers and footers."""
    def walk(tabs):
        for one in tabs or ():
            if (one.get("tabProperties") or {}).get("tabId") == tab_id:
                return one.get("documentTab") or {}
            found = walk(one.get("childTabs"))
            if found is not None:
                return found
        return None

    found = walk(document.get("tabs")) if tab_id else None
    if found is None:
        tabs = document.get("tabs") or []
        if tabs and not tab_id:
            return tabs[0].get("documentTab") or {}
        return document
    return found


def _rgb(value) -> dict | None:
    said = str(value or "").strip().lower()
    if said in ("", "none", "no", "off", "clear", "remove"):
        return None
    said = COLOURS.get(said, said).lstrip("#")
    if len(said) == 3:
        said = "".join(ch * 2 for ch in said)
    if not re.fullmatch(r"[0-9a-f]{6}", said):
        raise CannotDoThat(f"A colour is written like #1a73e8 or a plain name (red, blue, green, "
                           f"yellow, orange, purple, gray, black, white), not {value!r}.")
    return {"red": int(said[0:2], 16) / 255, "green": int(said[2:4], 16) / 255,
            "blue": int(said[4:6], 16) / 255}


def _style_words(edit: dict) -> list[str]:
    words = []
    for key in ("bold", "italic", "underline", "strikethrough"):
        if edit.get(key) is not None:
            words.append(key if edit[key] else f"not {key}")
    if edit.get("font_size") is not None:
        words.append(f"{edit['font_size']} pt")
    if edit.get("font"):
        words.append(f"in {edit['font']}")
    if edit.get("color") is not None:
        words.append(f"coloured {edit['color']}" if _rgb_or_none(edit["color"]) else "colour taken off")
    if edit.get("highlight") is not None:
        words.append(f"highlighted {edit['highlight']}" if _rgb_or_none(edit["highlight"])
                     else "highlight taken off")
    if "link" in edit and edit["link"] is not None:
        words.append(f"linked to {edit['link']}" if str(edit["link"]).strip() else "link taken off")
    return words


def _rgb_or_none(value) -> bool:
    try:
        return _rgb(value) is not None
    except CannotDoThat:
        return False


def wants_planner(edits: list, tab: str = "") -> bool:
    """Whether a call needs more than edit_doc's first three edits, done the way they always were."""
    if (tab or "").strip():
        return True
    for edit in edits:
        if not isinstance(edit, dict):
            continue
        op = str(edit.get("op") or "").strip()
        if op not in ("append", "replace", "insert_at_heading"):
            return True
        if op == "replace" and any(edit.get(k) is not None for k in (
                "occurrence", "within", "match_case", *TEXT_STYLE_KEYS)):
            return True
        if any(edit.get(k) is not None for k in (*TEXT_STYLE_KEYS, *PARAGRAPH_KEYS)):
            return True
    return False


async def apply(docs, document_id: str, edits: list, tab: str = "") -> dict:
    """Every edit of one call, found in one reading and sent as one batch.

    Gives back the document's title and one sentence for each edit, in the order given.
    Raises CannotDoThat, before anything is sent, for anything that cannot be found or
    done as asked.
    """
    for attempt in (1, 2):
        document = await docs.document_with_tabs(document_id)
        plan = Plan(document, tab=tab)
        for n, edit in enumerate(edits):
            if not isinstance(edit, dict):
                raise CannotDoThat(f"Edit {n + 1} is not an edit: each is an object with an op.")
            try:
                plan.add(edit, n)
            except CannotDoThat as exc:
                prefix = f"Edit {n + 1} ({edit.get('op')})" if len(edits) > 1 else "That edit"
                raise CannotDoThat(f"{prefix}: {exc} Nothing was changed.") from None
        requests = plan.requests()
        try:
            if requests:
                await docs.batch_update(document_id, requests,
                                        revision=plan.revision or None)
        except GoogleSaidNo as exc:
            text = str(exc).lower()
            if attempt == 1 and "revision" in text:
                continue  # somebody changed it as it was read: read it again and redo the plan
            raise
        break
    said_by_edit: dict[int, list[str]] = {}
    for unit in plan.units:
        if unit.later:
            kind, text, edit = unit.later
            made = await docs.batch_update(document_id, [{
                "createHeader" if kind == "header" else "createFooter": {
                    "type": "DEFAULT",
                    **({"sectionBreakLocation": plan.loc(0)} if plan.tab_id else {})}}])
            reply = (made.get("replies") or [{}])[0]
            new_id = (reply.get("createHeader") or reply.get("createFooter") or {}).get(
                "headerId" if kind == "header" else "footerId")
            if not new_id:
                raise GoogleSaidNo(f"Google made no {kind}, so nothing was written in one.")
            reqs = [{"insertText": {"location": plan.loc(0, new_id), "text": text}}]
            styled, _ = plan.style_requests(edit, 0, u16(text), new_id)
            await docs.batch_update(document_id, reqs + styled)
        if unit.said:
            said_by_edit.setdefault(unit.edit_no, []).append(unit.said)
    said = [s for n in sorted(said_by_edit) for s in said_by_edit[n]]
    title = document.get("title") or ""
    where = f" in the tab {plan.tab.named}" if len(plan.all_tabs) > 1 else ""
    return {"title": title, "said": said, "where": where}


__all__ = ["ALIGNMENTS", "Body", "LISTS", "OPS", "PARAGRAPH_STYLES", "Plan", "Unit", "apply",
           "u16", "wants_planner"]
