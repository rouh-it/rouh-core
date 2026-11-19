"""Starting a live page (Rouh Link, kind `html`, task 189): a real page made into a space.

Petar, 19 November 2026: a fully custom HTML page that several Rouhs and their people work on
live. A space of that kind starts from one of four things, and this is where each is read:

- **a page in the workspace**, a `.html` or `.htm` file inside a task's or a step's folder. The
  small files it names in its own folder (pictures, style sheets, scripts, fonts, each at most
  400 KB) are put into it, because the live page is drawn in a frame that can fetch nothing
  (LIVE-PAGE interface, section 3): a picture as a data: address, a style sheet as a `<style>`,
  a script as the text of its `<script>`. A remote address is left exactly as it is; the frame
  blocks it, and bringing the page back gives the file its words, not a copy of the internet.
  Its side is the side of the task's place in the tree, Work or Personal (`silos.COLUMNS`).
- **a card's drawn page** (`card:<number>`), the first `html` block of the card.
- **pasted HTML**, as it is.
- **a blank page**, a small starter with a heading and a paragraph.

Then every element is given its stable id (`htmldoc.stamp`) and the space is made
(`spaces.create(..., kind="html", html=...)`). A page past 2 MB once its files are in is refused
in plain words rather than cut.

Nothing here changes the workspace: the page on disk is only read. Bringing the live version back
is `pageout.py`, and only on the owner's press.
"""

from __future__ import annotations

import html as _html
import logging
import os
import re
from pathlib import Path

from rouh import pages
from rouh.config import config

log = logging.getLogger("rouh.link.pagein")

#: The most of one file put into a page. Past it the reference is left as the page wrote it.
ASSET_MOST = 400_000
#: The most a live page holds (`htmldoc.MOST`), said here too so the refusal needs no room.
PAGE_MOST = 2_000_000
#: A page's own kinds.
SUFFIXES = (".html", ".htm")
#: What a folder of a task or a step carries (`objecttree`).
SIDECAR = ".object.json"

TOO_BIG = ("A live page holds at most 2 MB, and this page is bigger than that once its pictures, "
           "styles and scripts are put into it. Make it smaller, or start from a blank page.")

#: The blank page: a heading and a paragraph, in a quiet, readable style that follows Rouh's own
#: loosely (system type, a narrow column, light and dark).
BLANK = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  :root {{ color-scheme: light dark; --ink: #1d1d1f; --soft: #5f6368; --paper: #fbfaf7; --line: #e4e1da; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --ink: #ecebe8; --soft: #a3a19c; --paper: #17171a; --line: #2d2d31; }}
  }}
  body {{ margin: 0; background: var(--paper); color: var(--ink);
         font: 16px/1.6 -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif; }}
  main {{ max-width: 680px; margin: 0 auto; padding: 48px 20px 64px; }}
  h1 {{ font-size: 28px; line-height: 1.25; margin: 0 0 12px; letter-spacing: -0.01em; }}
  p {{ margin: 0 0 14px; color: var(--soft); }}
</style>
</head>
<body>
<main>
<h1>{title}</h1>
<p>Write here, or ask a Rouh in the space to make this page what it should be.</p>
</main>
</body>
</html>
"""


class Problem(ValueError):
    """Said to the person as it is (the API answers it as a 400, `peers.Problem`)."""


def _problem(words: str) -> Exception:
    try:
        from .peers import Problem as Plain

        return Plain(words)
    except Exception:  # noqa: BLE001 - outside Django (a check of the pure parts)
        return Problem(words)


# --- which page ---------------------------------------------------------------------------------


def workspace_page(root, rel: str) -> tuple[str, Path]:
    """``(rel, file)`` for a page in a task's or step's folder, or a plain refusal.

    The rules are `pages.check`'s (under one of `pages.TOPS`, nothing starting with a dot, no link
    out of the workspace, no `..`), with `.htm` allowed too, and one more: the page's folder, or
    one above it short of the top, is a task's or a step's (it holds `.object.json`)."""
    if not root:
        raise _problem("There is no workspace on this machine.")
    rel = str(rel or "").strip()
    if (not rel or rel.startswith("/") or "\\" in rel or "\x00" in rel or "%" in rel
            or any(p in ("", ".", "..") for p in rel.split("/"))):
        raise _problem("That is not a plain path to a page inside the workspace.")
    parts = rel.split("/")
    if os.path.splitext(parts[-1].lower())[1] not in SUFFIXES:
        raise _problem("Only a page (.html or .htm) can be worked on as a live page.")
    try:
        pages._check_parts(parts, rel)
        base = Path(root).resolve()
        target = pages.resolve(base, rel)
        inside = target.relative_to(base).parts
        pages._check_parts(inside, rel)
    except (pages.Refused, ValueError) as exc:
        raise _problem(str(exc)) from None
    if not target.is_file():
        raise _problem(f"There is no page at {rel} in the workspace.")
    if not _in_task(base, target):
        raise _problem("Only a page in a task's or a step's folder can be worked on as a live page.")
    return "/".join(inside), target


def _in_task(base: Path, target: Path) -> bool:
    folder = target.parent
    while folder != base and base in folder.parents:
        if (folder / SIDECAR).is_file():
            return True
        folder = folder.parent
    return False


def side_of(rel: str) -> str:
    """Work or Personal, from the top of the tree the page is in ("" when neither says)."""
    from rouh import silos

    return silos.COLUMNS.get(str(rel or "").split("/", 1)[0], "")


def read_text(target: Path) -> str:
    try:
        raw = target.read_bytes()
    except OSError:
        raise _problem("The page could not be read.") from None
    if len(raw) > PAGE_MOST * 4:
        raise _problem(TOO_BIG)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise _problem("The page is not UTF-8 text, so it cannot be worked on live.") from None
    if "\x00" in text:
        raise _problem("The page holds bytes that are not text.")
    return text


# --- its files put in ------------------------------------------------------------------------------


class _Gather(pages._Inliner):
    """`pages._Inliner`, for a page that will be drawn where nothing can be fetched.

    The frame allows inline style and script only (`style-src 'unsafe-inline'`, `script-src
    'unsafe-inline'`), so a data: style sheet or script would be refused there: a style sheet
    becomes a `<style>` and a script the text of its `<script>`. Pictures and fonts are data:
    addresses, which the frame allows. Each file at most `ASSET_MOST`."""

    def __init__(self, root, page: str) -> None:
        super().__init__(root, page, None)
        self.left: list[str] = []

    def take(self, target: Path, ref: str) -> bytes | None:
        try:
            data = pages._read_upto(target, ASSET_MOST)
        except OSError:
            return None
        if len(data) > ASSET_MOST:
            self.left.append(ref)
            log.info("pagein: %s in %s is left as a reference: it is over %d KB", ref, self.page,
                     ASSET_MOST // 1000)
            return None
        self.total += len(data)
        return data

    @staticmethod
    def _found(attrs: str) -> dict:
        got: dict = {}
        for attr in pages._ATTR.finditer(attrs):
            got.setdefault(attr.group("name").lower(), attr)
        return got

    def sheet(self, attrs: str) -> str | None:
        """A `<style>` for a `<link rel=stylesheet>` naming a file of the page's own, else None."""
        found = self._found(attrs)
        rel = found.get("rel")
        words = _html.unescape(pages._value(rel)).lower().split() if rel is not None else []
        href = found.get("href")
        if "stylesheet" not in words or "alternate" in words or href is None or not href.group("value"):
            return None
        ref = _html.unescape(pages._value(href))
        got = self.find(self.folder, ref, pages.STYLESHEETS)
        if got is None:
            return None
        asked, target, _suffix, _fragment = got
        data = self.take(target, ref)
        if data is None:
            return None
        css = self.css(data.decode("utf-8", "replace"), asked.rsplit("/", 1)[0])
        css = re.sub(r"</(style)", r"<\\/\1", css, flags=re.IGNORECASE)
        media = found.get("media")
        said = (f' media="{_html.escape(_html.unescape(pages._value(media)), quote=True)}"'
                if media is not None and media.group("value") else "")
        return f"<style{said}>{css}</style>"

    def script(self, attrs: str) -> tuple[str, str] | None:
        """``(start tag without its src, the code)`` for a script naming a file of the page's own."""
        found = self._found(attrs)
        src = found.get("src")
        kind = pages._script_type(found)
        if src is None or not src.group("value") or kind not in ("", "text/javascript",
                                                               "application/javascript", "module"):
            return None
        ref = _html.unescape(pages._value(src))
        got = self.find(self.folder, ref, pages.SCRIPTS)
        if got is None:
            return None
        asked, target, _suffix, _fragment = got
        data = self.take(target, ref)
        if data is None:
            return None
        code = data.decode("utf-8", "replace")
        if kind == "module":
            code = self.imports(code, asked.rsplit("/", 1)[0])
        code = re.sub(r"</(script)", r"<\\/\1", code, flags=re.IGNORECASE).replace("<!--", "<\\!--")
        # The src goes, and with it what only a fetched script has.
        drop = [a for k, a in found.items() if k in ("src", "integrity", "crossorigin", "defer", "async")]
        out, pos = [], 0
        for attr in sorted(drop, key=lambda a: a.start()):
            out.append(attrs[pos:attr.start()])
            pos = attr.end()
        out.append(attrs[pos:])
        rest = " ".join("".join(out).split())
        return (f"<script {rest}>" if rest else "<script>"), code

    def walk(self, text: str) -> str:
        out: list[str] = []
        pos = 0
        while True:
            found = pages._TAG.search(text, pos)
            if found is None:
                out.append(text[pos:])
                return "".join(out)
            out.append(text[pos:found.start()])
            pos = found.end()
            name = found.group("name")
            if name is None:
                out.append(found.group(0))
                continue
            name = name.lower()
            attrs = found.group("attrs")
            if name == "link":
                style = self.sheet(attrs)
                if style is not None:
                    out.append(style)
                    continue
            if name == "script":
                close = pages._RAW_END["script"].search(text, pos)
                stop = close.start() if close else len(text)
                put = self.script(attrs)
                if put is not None:
                    out.append(put[0] + put[1])
                    pos = stop
                    continue
            out.append(text[found.start():found.start("attrs")])
            out.append(self.attrs(name, attrs))
            out.append(">")
            if name in pages._RAW_END:
                close = pages._RAW_END[name].search(text, pos)
                stop = close.start() if close else len(text)
                body = text[pos:stop]
                if name == "style":
                    body = self.css(body, self.folder)
                out.append(body)
                pos = stop


def inline(root, rel: str, text: str) -> str:
    """The page with the small files of its own put in (see `_Gather`). A page with a `<base>`
    is left as it is, as `pages.with_files` leaves it."""
    if pages._BASE.search(text):
        return text
    return _Gather(root, rel).walk(text)


# --- its name ------------------------------------------------------------------------------------


_HEADING = re.compile(r"<h[1-6]\b[^>]*>(.*?)</h[1-6]\s*>", re.IGNORECASE | re.DOTALL)
_TAGS = re.compile(r"<[^>]*>")


def title_in(text: str) -> str:
    """The page's `<title>`, else its first heading, else ""."""
    for found in (pages._TITLE.search(text), _HEADING.search(text)):
        if found:
            words = " ".join(_html.unescape(_TAGS.sub(" ", found.group(1))).split())
            if words:
                return words[:200]
    return ""


def _whole(text: str, title: str) -> str:
    """A fragment (a card's drawing, a pasted piece) as a whole page; a whole page as it is."""
    if re.search(r"<html\b|<body\b|<!doctype", text[:4000], re.IGNORECASE):
        return text
    return ("<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
            f"<title>{_html.escape(title or 'A live page')}</title>\n</head>\n<body>\n{text}\n</body>\n</html>\n")


def _card_page(card: str) -> tuple[str, str, str]:
    """``(html, title, number)`` of a card's first drawn page."""
    from rouh import artifacts

    number = str(card or "").strip()
    if number.startswith("card:"):
        number = number[5:]
    if not number.isdigit():
        raise _problem("That is not a card's number.")
    got = artifacts.contents(number, root=config.assistant_repo or "")
    spec = (got or {}).get("card") or None
    if not spec:
        raise _problem(f"There is no card {number}.")
    for block in spec.get("blocks") or []:
        if isinstance(block, dict) and block.get("block") == "html":
            markup = str(block.get("html") or block.get("text") or "")
            if markup.strip():
                return markup, str(block.get("title") or spec.get("title") or ""), number
    raise _problem(f"Card {number} has no drawn page on it to work on live.")


# --- the start ------------------------------------------------------------------------------------


def prepare(root, *, source: str = "", html: str = "", card: str = "", title: str = "",
            silo: str = "") -> dict:
    """What the space is made of, before it is made: ``{"text", "title", "source", "silo"}``.
    The whole of the reading, with no room and no database but a card's."""
    title = " ".join(str(title or "").split())[:200]
    if source:
        rel, target = workspace_page(root, source)
        text = inline(root, rel, read_text(target))
        name = os.path.splitext(rel.rsplit("/", 1)[-1])[0]
        made = {"text": text, "title": title or title_in(text) or name, "source": rel,
                "silo": side_of(rel) or silo}
    elif card:
        markup, called, number = _card_page(card)
        called = title or called or title_in(markup) or f"Card {number}"
        made = {"text": _whole(markup, called), "title": called, "source": f"card:{number}", "silo": silo}
    elif str(html or "").strip():
        called = title or title_in(html) or "A pasted page"
        made = {"text": _whole(str(html), called), "title": called, "source": "", "silo": silo}
    else:
        called = title or "A new page"
        made = {"text": BLANK.format(title=_html.escape(called)), "title": called, "source": "",
                "silo": silo}
    if len(made["text"]) > PAGE_MOST:
        raise _problem(TOO_BIG)
    made["silo"] = made["silo"] if made["silo"] in ("work", "personal") else ""
    return made


def start(org: str, me, *, source: str = "", html: str = "", card: str = "", title: str = "",
          silo: str = "") -> dict:
    """A live page made from a workspace page, a card, pasted HTML or nothing:
    ``{"space_id", "url"}``. ``me`` is the person starting it (the API's signed-in person)."""
    from . import htmldoc, spaces

    made = prepare(config.assistant_repo or "", source=source, html=html, card=card, title=title,
                   silo=silo)
    stamped = htmldoc.stamp(made["text"])
    if len(stamped) > min(PAGE_MOST, getattr(htmldoc, "MOST", PAGE_MOST)):
        raise _problem(TOO_BIG)
    sid = spaces.create(org, kind="html", title=made["title"], source=made["source"], silo=made["silo"],
                        html=stamped)
    log.info("pagein: live page %s made from %s", sid, made["source"] or ("pasted" if html else "blank"))
    return {"space_id": sid, "url": f"/link/space/{sid}"}
