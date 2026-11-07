"""A task's Markdown files, read on its own page rather than hidden.

Petar, 23 September 2026: "I feel like I'm not seeing any MD files." A task's
folder holds its notes as Markdown - the `AGENTS.md` that says where the work
stands, a step Rouh filed as a `step.md`, whatever else was written down - and
nothing on the screen showed any of it. The pages a task built were shown; the
words beside them were not.

So a task's page lists them, each by its file name, beside everything else
directly in it (`objectindex._level`), and opens one here, drawn into the same page at
`/workspace/_task/<folder>/?doc=<name>`. It is a reading view and nothing
more: it writes nothing, and it is drawn fresh from the file every time.

Why here and not by `pages.py`. That module serves a workspace file as it is,
and refuses every `.md` on purpose: what it serves is what Share can hand to
anybody with the link, and a task's notes are its internal record. This is not
that route. It answers only under `/workspace/_task/`, behind the sign-in, and
Share cannot reach it (`pages.check` refuses `_task/` like any other folder
outside `pages.TOPS`), so what a signed-in person could already open in the
workspace is what they can now read, and nothing more leaves it.

Two shapes of file:

- **Any `.md`**: plain Markdown, drawn by `markdown_html`. Everything is escaped
  first and only then given its shape, so a note can never put markup of its
  own into the page. The rules are the conversation's own (`renderMarkdown` in
  app.js) with the three a document needs and a chat message does not: fenced
  code, a quote and a rule. Lines of one paragraph are joined, because the
  house rule for a long Markdown file is one sentence per line and that is not
  a line break.
- **`step.md`**: Rouh's own format for a step (`rouh/steps.py`), prose with
  blocks fenced by colons. It is read with that module's own parser, so a stat,
  a table or a list reads as one here and not as the fence that wrote it.
"""
from __future__ import annotations

import html
import re

#: What a step written by Rouh is called in its folder (`steps.STEP_FILE`).
STEP_FILE = "step.md"

#: A line that opens or closes a fenced code block, and its language.
_FENCE = re.compile(r"^\s*(```+|~~~+)\s*([\w+-]*)\s*$")
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_BULLET = re.compile(r"^(\s*)[-*+]\s+(.*)$")
_NUMBERED = re.compile(r"^(\s*)\d{1,9}[.)]\s+(.*)$")
_RULE_LINE = re.compile(r"^\s*([-*_])(\s*\1){2,}\s*$")
_TABLE_RULE = re.compile(r"^:?-+:?$")
_QUOTE = re.compile(r"^\s*>\s?(.*)$")


def _inline(text: str) -> str:
    """One run of text: escaped, then code, bold, italic and links.

    Code spans are taken out before anything else and put back last, so an
    asterisk inside backticks stays an asterisk. A link keeps only an address
    that leaves the workspace - http, https or mailto - because a relative one
    in a note means a path on disk, and there is no address for that here.
    """
    kept: list[str] = []

    def keep(found: re.Match) -> str:
        kept.append(f"<code>{found.group(1)}</code>")
        return f"\x00{len(kept) - 1}\x00"

    out = html.escape(text.replace("\x00", ""), quote=True)
    out = re.sub(r"`([^`]+)`", keep, out)
    out = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(r"__([^_]+)__", r"<strong>\1</strong>", out)
    out = re.sub(r"(^|[^*\w])\*([^*\n]+)\*(?!\w)", r"\1<em>\2</em>", out)
    out = re.sub(r"(^|[^\w])_([^_\n]+)_(?!\w)", r"\1<em>\2</em>", out)
    out = re.sub(
        r"\[([^\]]+)\]\(((?:https?:|mailto:)[^\s)]+)\)",
        r'<a href="\2" target="_blank" rel="noopener noreferrer">\1</a>', out)
    return re.sub(r"\x00(\d+)\x00",
                  lambda m: kept[int(m.group(1))] if int(m.group(1)) < len(kept) else "", out)


def _cells(row: str) -> list[str]:
    return [c.strip() for c in row.strip().strip("|").split("|")]


def _is_table_rule(line: str, wide: int) -> bool:
    """The row of dashes under a table's headings, one cell per heading."""
    if "-" not in line:
        return False
    cells = _cells(line)
    return len(cells) == wide and all(_TABLE_RULE.match(c) for c in cells)


def markdown_html(text: str, *, drop_title: bool = False) -> str:
    """A Markdown document as the HTML the task page draws it with.

    ``drop_title`` leaves out a heading that is the very first thing in the
    document, because the page has already drawn it as the document's title
    (`first_heading`) and a note opening with its own name twice reads as a
    mistake.
    """
    lines = str(text or "").replace("\r", "").split("\n")
    out: list[str] = []
    para: list[str] = []
    items: list[str] = []
    list_tag = ""
    quote: list[str] = []

    def flush_para() -> None:
        if para:
            out.append(f"<p>{_inline(' '.join(para))}</p>")
            para.clear()

    def flush_list() -> None:
        nonlocal list_tag
        if items:
            out.append(f"<{list_tag}>" + "".join(f"<li>{_inline(i)}</li>" for i in items)
                       + f"</{list_tag}>")
            items.clear()
        list_tag = ""

    def flush_quote() -> None:
        if quote:
            out.append(f"<blockquote>{markdown_html(chr(10).join(quote))}</blockquote>")
            quote.clear()

    def flush_all() -> None:
        flush_para()
        flush_list()
        flush_quote()

    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        fence = _FENCE.match(line)
        if fence:
            flush_all()
            mark, body = fence.group(1), []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith(mark):
                body.append(lines[i])
                i += 1
            i += 1
            lang = fence.group(2)
            label = f' data-lang="{html.escape(lang, quote=True)}"' if lang else ""
            out.append(f"<pre{label}><code>{html.escape(chr(10).join(body))}</code></pre>")
            continue
        if not line.strip():
            flush_all()
            i += 1
            continue
        said = _QUOTE.match(line)
        if said:
            flush_para()
            flush_list()
            quote.append(said.group(1))
            i += 1
            continue
        flush_quote()
        heading = _HEADING.match(line)
        if heading and drop_title and not (out or para or items or quote):
            drop_title = False
            i += 1
            continue
        drop_title = False
        if heading:
            flush_all()
            # The page's own title is the one <h1>, so a document's headings
            # start a level below it.
            level = min(6, len(heading.group(1)) + 1)
            out.append(f"<h{level}>{_inline(heading.group(2))}</h{level}>")
            i += 1
            continue
        if _RULE_LINE.match(line) and not para:
            flush_all()
            out.append("<hr>")
            i += 1
            continue
        head = _cells(line) if "|" in line else None
        if head and i + 1 < len(lines) and _is_table_rule(lines[i + 1], len(head)):
            flush_all()
            rows = []
            i += 2
            while i < len(lines) and lines[i].strip() and "|" in lines[i]:
                rows.append(_cells(lines[i]))
                i += 1
            out.append(
                '<div class="dtable"><table><thead><tr>'
                + "".join(f"<th>{_inline(c)}</th>" for c in head)
                + "</tr></thead><tbody>"
                + "".join("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in row) + "</tr>"
                          for row in rows)
                + "</tbody></table></div>")
            continue
        bullet = _BULLET.match(line)
        numbered = None if bullet else _NUMBERED.match(line)
        if bullet or numbered:
            flush_para()
            tag = "ul" if bullet else "ol"
            if list_tag and list_tag != tag:
                flush_list()
            list_tag = tag
            items.append((bullet or numbered).group(2))
            i += 1
            continue
        if items and line.startswith(("  ", "\t")):
            # A wrapped list item, carried on under the item it belongs to.
            items[-1] += " " + line.strip()
            i += 1
            continue
        flush_list()
        para.append(line.strip())
        i += 1
    flush_all()
    return "".join(out)


def _step_block(block: dict) -> str:
    """One block of a `step.md`, the way the canvas would draw it, in HTML."""
    kind = block.get("block")
    if kind == "text":
        return markdown_html(block.get("text") or "")
    if kind == "code":
        return f"<pre><code>{html.escape(str(block.get('text') or ''))}</code></pre>"
    if kind == "stat":
        hint = (f'<span class="dhint">{_inline(str(block["hint"]))}</span>'
                if block.get("hint") else "")
        return (f'<div class="dstat"><span class="dlabel">{_inline(str(block.get("label") or ""))}'
                f'</span><span class="dvalue">{_inline(str(block.get("value") or ""))}</span>'
                f"{hint}</div>")
    if kind == "list":
        return "<ul>" + "".join(f"<li>{_inline(str(i))}</li>"
                                for i in block.get("items") or []) + "</ul>"
    if kind == "table":
        title = (f"<h3>{_inline(str(block['title']))}</h3>" if block.get("title") else "")
        cols = block.get("columns") or []
        head = ("<thead><tr>" + "".join(f"<th>{_inline(str(c))}</th>" for c in cols)
                + "</tr></thead>") if cols else ""
        rows = "".join("<tr>" + "".join(f"<td>{_inline(str(c))}</td>" for c in row) + "</tr>"
                       for row in block.get("rows") or [])
        return f'{title}<div class="dtable"><table>{head}<tbody>{rows}</tbody></table></div>'
    if kind == "chart":
        # The numbers under the chart, which is what a chart is made of. The
        # drawing of it is the canvas's, from the step itself.
        title = (f"<h3>{_inline(str(block['title']))}</h3>" if block.get("title") else "")
        rows = "".join(f"<tr><td>{_inline(str(p.get('label') or ''))}</td>"
                       f"<td>{html.escape(str(p.get('value')))}</td></tr>"
                       for p in block.get("points") or [])
        return f'{title}<div class="dtable"><table><tbody>{rows}</tbody></table></div>'
    if kind == "link":
        href = str(block.get("href") or "")
        text = _inline(str(block.get("text") or href))
        if re.match(r"^(https?:|mailto:)", href):
            return (f'<p><a href="{html.escape(href, quote=True)}" target="_blank" '
                    f'rel="noopener noreferrer">{text}</a></p>')
        return f"<p>{text}</p>"
    if kind == "image":
        caption = block.get("caption") or block.get("alt") or "A picture"
        return f'<p class="dnote">{_inline(str(caption))} (a picture, drawn on the canvas)</p>'
    if kind == "contact":
        # Somebody's contact card, whose every word anybody who sent a vCard
        # could have written: escaped, and never read as markdown.
        def cell(text) -> str:
            return html.escape(str(text or "")).replace("\n", "<br>")

        name = cell(block.get("name") or "A contact")
        if block.get("was_name"):
            name += f' <span class="dhint">(was {cell(block["was_name"])})</span>'
        rows = ""
        for row in block.get("rows") or []:
            if not isinstance(row, dict):
                continue
            said = cell(row.get("value"))
            if row.get("change"):
                was = f", was {cell(row['was'])}" if row.get("was") else ""
                said += f' <span class="dhint">({cell(row["change"])}{was})</span>'
            rows += f"<tr><td>{cell(row.get('label') or row.get('kind'))}</td><td>{said}</td></tr>"
        status = (f'<p class="dnote">{cell(block["status"])}</p>'
                  if block.get("status") else "")
        return (f"<h3>{name}</h3>{status}"
                f'<div class="dtable"><table><tbody>{rows}</tbody></table></div>')
    if kind == "sources":
        return _sources_html(block.get("sources") or [])
    if kind == "html":
        # Markup of its own, which is most of what a step written by Rouh is:
        # drawn whole, in a frame of its own with scripts and nothing else, so
        # it can neither reach this page nor anything behind it. It says how
        # tall it is (`FIT`) and the page sizes the frame to it (`SIZER`).
        markup = str(block.get("html") or block.get("text") or "")
        title = str(block.get("title") or "A block of the step's own markup")
        return (f'<iframe class="dhtml" sandbox="allow-scripts" referrerpolicy="no-referrer" '
                f'title="{html.escape(title, quote=True)}" '
                f'srcdoc="{html.escape(markup + FIT, quote=True)}"></iframe>')
    return ""


#: Put at the end of an html block's markup: tells the page around it how tall
#: the block is, whenever that changes. Its own origin is opaque, so a message
#: is the only thing that can cross, and a number is all this one carries.
FIT = ("<script>(function(){function tell(){try{parent.postMessage({rouhDocHeight:"
       "document.documentElement.scrollHeight},'*')}catch(e){}}"
       "addEventListener('load',tell);if(window.ResizeObserver){new ResizeObserver(tell)"
       ".observe(document.documentElement)}tell()})();</script>")

#: On a page holding html blocks: sizes each frame to the height it says,
#: judged by which frame the message came from and never by what it claims.
SIZER = ("<script>addEventListener('message',function(e){var d=e.data;"
         "if(!d||typeof d.rouhDocHeight!=='number')return;"
         "var f=document.querySelectorAll('iframe.dhtml');"
         "for(var i=0;i<f.length;i++){if(f[i].contentWindow===e.source){"
         "f[i].style.height=Math.min(Math.max(d.rouhDocHeight,80),40000)+'px';}}});</script>")


def _sources_html(pages: list) -> str:
    """A step's sources block: the pages its footnotes point at, numbered.

    Each has an id of its own, `source-N`, which is what a footnote in the
    step links to (`_footnoted`). Only an address that leaves the workspace is
    a link, for the same reason `_inline` keeps only those.
    """
    from . import citing

    rows = []
    for n, page in enumerate(p for p in pages if isinstance(p, dict)):
        url = str(page.get("url") or "").strip()
        name = html.escape(citing.title_of(page.get("title"), url))
        where = html.escape(citing.where(url))
        said = (f'<a href="{html.escape(url, quote=True)}" target="_blank" '
                f'rel="noopener noreferrer">{name}</a>'
                if re.match(r"^https?:", url) else name)
        rows.append(f'<li id="source-{n + 1}">{said} <span class="dwhere">{where}</span></li>')
    if not rows:
        return ""
    return f'<h3>Sources</h3><ol class="dsources">{"".join(rows)}</ol>'


#: A run of footnotes as a card writes them: "[2]", "[1][3]" or "[1, 3]".
_MARK = re.compile(r" ?((?:\[\d{1,3}(?:\s*,\s*\d{1,3})*\])+)(?![^<>]*>)")


def _footnoted(drawn: str, count: int) -> str:
    """Every footnote in one block's HTML, as a link to its page in the list.

    Only numbers the list has: "[2026]" in a sentence is a year in brackets.
    Never inside a tag, which is what the look-ahead keeps it out of.
    """
    def link(found: re.Match) -> str:
        numbers = [int(n) for n in re.findall(r"\d+", found.group(1))]
        if not numbers or any(n < 1 or n > count for n in numbers):
            return found.group(0)
        # One superscript for the run, the numbers apart: "2,3" and not "23".
        return ('<sup class="dcite">'
                + ",".join(f'<a href="#source-{n}">{n}</a>' for n in numbers) + "</sup>")

    return _MARK.sub(link, drawn)


def step_html(text: str) -> tuple[str, str]:
    """A `step.md` as HTML, and its own title from its front matter."""
    from . import steps

    read = steps.parse(str(text or ""))
    blocks = [b for b in read.get("blocks") or [] if isinstance(b, dict)]
    # The list its footnotes point at goes at the end, wherever it was written,
    # and every page in it is one number whichever sources block it came from.
    pages = [p for b in blocks if b.get("block") == "sources"
             for p in (b.get("sources") or [])]
    rest = [b for b in blocks if b.get("block") != "sources"]
    drawn = "".join(
        _footnoted(_step_block(b), len(pages)) if pages and b.get("block") not in ("html", "code")
        else _step_block(b)
        for b in rest)
    if pages:
        drawn += _sources_html(pages)
    if 'class="dhtml"' in drawn:
        drawn += SIZER
    return drawn, str(read.get("title") or "")


def first_heading(text: str) -> str:
    """The first heading of a Markdown document, which is what it is called."""
    in_fence = False
    for line in str(text or "").split("\n"):
        if _FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        found = _HEADING.match(line.strip())
        if found:
            return found.group(2).strip()
    return ""
