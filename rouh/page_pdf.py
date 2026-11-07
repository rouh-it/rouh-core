"""A page as a printable PDF: any page in a task, laid out again for paper, on request.

Built by the nightly feature run, night 11, 14 October 2026 (task 94, idea I-088). On 10 October
2026 Petar wrote in task 101: "As I expected this page is unprintable. Please take all the
content and build a nice well organized letter size pdf", and a run spent its time doing it by
hand. The pages runs make are built for a screen - a side list, a fixed bar, slides that snap,
panels that open on a press - and a browser's own Print gives the screen, cut where it falls.

So when he asks for one ("make this page a PDF", "I need to print this"), the `print_page` tool
opens the page in a headless Chromium on Rouh's own server, takes its content out of the layout
(headings, paragraphs, lists, tables, figures, drawings and pictures, quotes, code, and its
sources, in the order they come; never its menus, bars, buttons or anything hidden), lays it out
again for letter or A4 paper with page numbers, a title and where it came from, and keeps the
PDF in the task's own folder beside the page (Petar's lesson L8: what is about a task lives in
the task). It answers with a link that downloads it, the same kind of link a task's files have
(`rouh/filelinks.py`).

**No model call.** The layout is code and Chromium's own print.

**What it may reach.** The page's own folder on disk, which Rouh hands the browser itself
(`FOLDER`), and the https addresses the page itself loads (its fonts, its scripts); nothing on a
private address and nothing over plain http. In the containers the browser is the browser
container's (`browsing.chromium`), and its way out is the key proxy.

**Its switch** is `page_pdf` (`rouh/switches.py`), off until Petar keeps it in Mutations: off,
the tool makes nothing and says so.
"""
from __future__ import annotations

import asyncio
import ipaddress
import logging
import re
import time
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

log = logging.getLogger("rouh.page_pdf")

#: The gene's switch (`rouh/switches.py`).
SWITCH = "page_pdf"
TITLE = "A page as a printable PDF: any task's page laid out again for letter or A4 paper, on request"
#: The papers it lays out for, by the word the person uses.
PAPERS = {"letter": "Letter", "a4": "A4"}
#: How long a page has to draw itself before its content is taken, in seconds.
SETTLE_SECONDS = 2.5
#: How long the whole making may take, in seconds.
MOST_SECONDS = 90.0
#: Less text than this taken out of the layout means it found nothing, and the page is printed as it is.
LEAST_TEXT = 200
#: What can be made a PDF: a page, and a Markdown file, drawn first as a task's page reads it
#: (`docview`). Petar, 15 October 2026 (fr_4c075039223f): "What if I have Md files in that
#: folder? Maybe I want those pdf-ed or not."
PRINTABLE = (".html", ".htm", ".md")


class Refused(ValueError):
    """A page that cannot be made into a PDF, with the reason in words."""


def on(org_id=None) -> bool:
    from . import switches

    return switches.on(SWITCH, org_id or None)


def locate(root, page: str) -> tuple[str, Path]:
    """(the object's folder relative to the workspace, the page file) for what the person named:
    a task's folder, its address in Rouh (/task/...), or a page or a Markdown file inside it.
    Refused when it is not one of those inside the workspace.

    A folder means its `index.html`, which is what the `print_page` tool is asked for when he
    names a task. The menus on the screen never send a folder: they name the item
    (`for_item`)."""
    if not root:
        raise Refused("There is no workspace on this machine to find the page in.")
    base = Path(root).resolve()
    text = str(page or "").strip()
    text = re.sub(r"^https?://[^/]+", "", text)
    text = text.split("?")[0].split("#")[0]
    for lead in ("/task/", "task/", "/workspace/", "workspace/"):
        if text.startswith(lead):
            text = text[len(lead):]
            break
    parts = [p for p in text.strip("/").split("/") if p]
    if not parts or any(p.startswith(".") or "\\" in p or "\x00" in p for p in parts):
        raise Refused(f"{page!r} does not name a page in the workspace.")
    path = (base / "/".join(parts)).resolve()
    if base not in path.parents and path != base:
        raise Refused(f"{page!r} is outside the workspace.")
    if path.is_dir():
        path = path / "index.html"
    if path.suffix.lower() not in PRINTABLE or not path.is_file():
        raise Refused(f"There is no page at {page!r}: name the task, or the page's file in it.")
    return str(path.parent.relative_to(base)), path


def pdf_name(page: Path) -> str:
    """What the PDF is called: the task's folder name for its index page (and for the `step.md`
    Rouh wrote for it), else the page's or the Markdown file's own."""
    stem = page.parent.name if page.stem in ("index", "step") else page.stem
    stem = re.sub(r"^\d+(?:-\d+)?\.", "", stem) or stem
    return f"{stem}.pdf"


#: Run in the page: its content, taken out of the layout, as plain markup.
EXTRACT = r"""
() => {
  for (const d of document.querySelectorAll('details')) d.open = true;
  // Every part of the page, not only the one on show: tabs, slides and the pages of an explainer.
  const PARTS = 'section,article,[role=tabpanel],[hidden],[data-title],.page,.slide,.panel,.tab-panel';
  for (const p of document.querySelectorAll(PARTS)) {
    if (p.closest('nav,header,footer,aside,dialog,[role=dialog],[role=menu]')) continue;
    if (p.hidden || getComputedStyle(p).display === 'none' || getComputedStyle(p).visibility === 'hidden') {
      if ((p.textContent || '').trim().length < 40 && !p.querySelector('img,svg,table')) continue;
      p.hidden = false; p.style.display = 'block'; p.style.visibility = 'visible';
    }
  }
  for (const c of document.querySelectorAll('canvas')) {
    try { const img = document.createElement('img'); img.src = c.toDataURL('image/png');
          img.width = c.clientWidth; c.replaceWith(img); } catch (e) {}
  }
  const SKIP = new Set(['script','style','noscript','nav','header','footer','aside','button','form',
    'input','select','textarea','template','dialog','iframe','link','meta','label','video','audio']);
  const BLOCK = new Set(['h1','h2','h3','h4','h5','h6','p','ul','ol','table','figure','img','svg',
    'blockquote','pre','dl','hr']);
  const INLINE = new Set(['a','b','strong','i','em','u','s','code','span','small','sub','sup','mark',
    'abbr','time','br','cite','q','kbd','var','del','ins']);
  const ROLES = new Set(['navigation','banner','toolbar','tablist','menu','menubar','dialog','search']);
  const skip = el => {
    const tag = el.tagName.toLowerCase();
    if (SKIP.has(tag)) return true;
    if (el.getAttribute('aria-hidden') === 'true' && tag !== 'svg') return true;
    if (ROLES.has(el.getAttribute('role') || '')) return true;
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden') return true;
    if (cs.position === 'fixed' || cs.position === 'sticky') return true;
    return false;
  };
  const plain = el => {
    const copy = el.cloneNode(true);
    const scrub = n => {
      if (n.nodeType !== 1) return;
      const tag = n.tagName.toLowerCase();
      if (tag === 'svg') return;
      if (SKIP.has(tag)) { n.remove(); return; }
      for (const a of [...n.attributes]) {
        const keep = ['href','src','alt','colspan','rowspan','start','id'].includes(a.name);
        if (!keep) n.removeAttribute(a.name);
      }
      if (tag === 'a' && (n.getAttribute('href') || '').startsWith('javascript:')) n.removeAttribute('href');
      for (const c of [...n.children]) scrub(c);
    };
    // A drawing keeps how it looked: its page's stylesheet goes, so what it computed is written on it.
    const PROPS = ['fill','stroke','stroke-width','stroke-dasharray','stroke-linecap','fill-opacity',
      'stroke-opacity','font-size','font-family','font-weight','text-anchor','dominant-baseline','color'];
    const isSvg = e => e.tagName.toLowerCase() === 'svg';
    const orig = isSvg(el) ? [el] : [...el.querySelectorAll('svg')];
    const made = isSvg(copy) ? [copy] : [...copy.querySelectorAll('svg')];
    orig.forEach((o, i) => {
      const c = made[i]; if (!c) return;
      const os = [o, ...o.querySelectorAll('*')], cs = [c, ...c.querySelectorAll('*')];
      os.forEach((oe, j) => {
        const ce = cs[j]; if (!ce || j === 0) return;
        const s = getComputedStyle(oe);
        ce.setAttribute('style', PROPS.map(p => `${p}:${s.getPropertyValue(p)}`).join(';')
          + (s.opacity !== '1' ? `;opacity:${s.opacity}` : ''));
      });
      const r = o.getBoundingClientRect();
      if (!c.getAttribute('viewBox') && r.width && r.height) c.setAttribute('viewBox', `0 0 ${r.width} ${r.height}`);
      c.removeAttribute('width'); c.removeAttribute('height');
      c.setAttribute('style', `width:${Math.round(r.width) || 24}px;max-width:100%;height:auto;`
        + `color:${getComputedStyle(o).color}`);
    });
    // A picture keeps its whole address, worked out before anything around it is taken away.
    const isImg = e => e.tagName.toLowerCase() === 'img';
    const pics = isImg(el) ? [el] : [...el.querySelectorAll('img')];
    const copies = isImg(copy) ? [copy] : [...copy.querySelectorAll('img')];
    pics.forEach((o, i) => { if (copies[i]) copies[i].setAttribute('src', o.currentSrc || o.src); });
    scrub(copy);
    return copy.outerHTML;
  };
  const inlineOnly = el => [...el.children].every(c => INLINE.has(c.tagName.toLowerCase()));
  const hasText = el => [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim());
  const out = [];
  const walk = el => {
    for (const c of el.children) {
      if (skip(c)) continue;
      const tag = c.tagName.toLowerCase();
      if (BLOCK.has(tag)) { out.push(plain(c)); continue; }
      if (tag === 'li' || tag === 'dt' || tag === 'dd') { out.push('<p>' + plain(c).replace(/^<[^>]+>|<\/[^>]+>$/g, '') + '</p>'); continue; }
      if (c.children.length === 0 || inlineOnly(c)) {
        if (c.textContent.trim()) {
          const inner = plain(c).replace(/^<[^>]+>/, '').replace(/<\/[^>]+>$/, '');
          out.push('<p>' + inner + '</p>');
        }
        continue;
      }
      if (hasText(c)) {
        const bits = [];
        for (const n of c.childNodes) {
          if (n.nodeType === 3 && n.textContent.trim()) bits.push(n.textContent.trim());
        }
        out.push('<p>' + bits.join(' ').replace(/[<>&]/g, s => ({'<':'&lt;','>':'&gt;','&':'&amp;'}[s])) + '</p>');
      }
      walk(c);
    }
  };
  const root = document.querySelector('main') || document.querySelector('article') || document.body;
  walk(root);
  const h1 = document.querySelector('h1');
  return {title: (document.title || (h1 && h1.textContent) || '').trim(), html: out.join('\n'),
          text: out.join(' ').replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim().length};
}
"""

#: How the content is laid out on paper.
PRINT_CSS = """
@page { margin: 0.8in 0.75in 0.85in; }
html { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
body { font-family: "Charter", "Georgia", "Times New Roman", serif; font-size: 10.6pt;
       line-height: 1.5; color: #1d1d1f; margin: 0; }
.doc-head { border-bottom: 1.5pt solid #1d1d1f; padding-bottom: 8pt; margin-bottom: 16pt; }
.doc-head h1 { font-size: 21pt; line-height: 1.2; margin: 0 0 4pt; }
.doc-head .from { font-family: "Helvetica Neue", Arial, sans-serif; font-size: 8.5pt; color: #6e6e73; }
h1, h2, h3, h4, h5, h6 { font-family: "Helvetica Neue", Arial, sans-serif; color: #111;
       break-after: avoid; page-break-after: avoid; line-height: 1.25; }
h1 { font-size: 17pt; margin: 18pt 0 6pt; }
h2 { font-size: 14pt; margin: 18pt 0 6pt; padding-bottom: 3pt; border-bottom: 0.6pt solid #c7c7cc; }
h3 { font-size: 12pt; margin: 14pt 0 4pt; }
h4, h5, h6 { font-size: 10.6pt; margin: 12pt 0 4pt; }
p { margin: 0 0 7pt; orphans: 3; widows: 3; }
ul, ol { margin: 0 0 8pt; padding-left: 18pt; }
li { margin: 0 0 3pt; }
a { color: #1d4ed8; text-decoration: none; }
table { width: 100%; border-collapse: collapse; margin: 6pt 0 12pt; font-size: 9pt;
        break-inside: auto; }
tr { break-inside: avoid; page-break-inside: avoid; }
thead { display: table-header-group; }
th, td { border: 0.5pt solid #c7c7cc; padding: 4pt 6pt; text-align: left; vertical-align: top; }
th { background: #f2f2f5; font-family: "Helvetica Neue", Arial, sans-serif; }
img, svg { max-width: 100%; height: auto; break-inside: avoid; page-break-inside: avoid; }
figure { margin: 8pt 0 12pt; break-inside: avoid; page-break-inside: avoid; }
figcaption { font-size: 8.5pt; color: #6e6e73; margin-top: 3pt; }
blockquote { margin: 8pt 0; padding: 2pt 0 2pt 12pt; border-left: 2pt solid #c7c7cc; color: #3a3a3c; }
pre, code { font-family: "SF Mono", Menlo, Consolas, monospace; font-size: 8.5pt; }
pre { white-space: pre-wrap; background: #f5f5f7; padding: 6pt 8pt; border-radius: 3pt; }
hr { border: 0; border-top: 0.6pt solid #c7c7cc; margin: 12pt 0; }
del, s, strike { color: #b42318; }
ins { color: #067647; }
mark { background: #fff3b0; }
"""

FOOTER = ('<div style="font-family: Helvetica, Arial, sans-serif; font-size: 7.5pt; color: #8e8e93; '
          'width: 100%; padding: 0 0.75in; display: flex; justify-content: space-between;">'
          '<span>{title}</span><span><span class="pageNumber"></span> of '
          '<span class="totalPages"></span></span></div>')


def _escape(text: str) -> str:
    return (str(text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def _public_https(url: str) -> bool:
    """Whether the page may load this while it is drawn: its own files, data, and https to a
    name that is not a private address."""
    parsed = urlparse(url)
    if parsed.scheme in ("file", "data", "blob", "about"):
        return True
    if parsed.scheme != "https" or not parsed.hostname:
        return False
    host = parsed.hostname
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_global
    except ValueError:
        return host != "localhost" and not host.endswith((".local", ".internal", ".localhost"))


def _markdown_page(md_file: Path) -> str:
    """A Markdown file as a page to lay out: drawn exactly as a task's page reads it
    (`docview`), with its first heading as its title, or its file name where it has none."""
    from . import docview

    try:
        text = md_file.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise Refused(f"{md_file.name} could not be read ({exc}).") from None
    if md_file.name.lower() == docview.STEP_FILE:
        drawn, title = docview.step_html(text)
    else:
        # Its first heading is its title when it opens with one, and is then drawn once.
        title = docview.first_heading(text) if text.lstrip().startswith("#") else ""
        drawn = docview.markdown_html(text, drop_title=bool(title))
    title = title or md_file.name
    return (f'<!doctype html><html><head><meta charset="utf-8"><title>{_escape(title)}</title>'
            f'</head><body><main>{drawn or "<p>This file is empty.</p>"}</main></body></html>')


#: Where the page's own folder is, to the browser that lays it out: an address that is never
#: fetched, because every request to it is answered from the folder on disk (`_from_folder`).
#: So the browser reads the page's own files and nothing else of this machine's disk, and in
#: the containers, where it is another container's (`browsing.chromium`), it reads them at all.
FOLDER = "http://page.rouh.invalid"


async def _from_folder(route, root: Path, page_file: Path):
    """One request to `FOLDER`, answered from the page's folder: a file inside it, the Markdown
    file being printed drawn as a page, or nothing."""
    target = (root / unquote(urlparse(route.request.url).path).lstrip("/")).resolve()
    if (root not in target.parents and target != root) or not target.is_file():
        return await route.fulfill(status=404, body="")
    if target == page_file.resolve() and target.suffix.lower() == ".md":
        return await route.fulfill(status=200, content_type="text/html; charset=utf-8",
                                   body=_markdown_page(page_file))
    return await route.fulfill(path=str(target))


async def render(page_file: Path, paper: str = "Letter", *, made_on: str = "") -> tuple[bytes, dict]:
    """The page laid out again for paper, as PDF bytes, and {title, pages_text, as_is}."""
    from playwright.async_api import async_playwright

    from .browsing import chromium

    root = page_file.parent.resolve()
    async with async_playwright() as pw:
        browser = await chromium(pw, headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        try:
            context = await browser.new_context(viewport={"width": 1100, "height": 1400},
                                                java_script_enabled=True)

            async def gate(route):
                url = route.request.url
                if url == FOLDER or url.startswith(FOLDER + "/"):
                    return await _from_folder(route, root, page_file)
                if url.startswith("file:"):
                    return await route.abort()
                return await (route.continue_() if _public_https(url) else route.abort())

            await context.route("**/*", gate)
            page = await context.new_page()
            await page.goto(f"{FOLDER}/{quote(page_file.name)}", wait_until="load", timeout=30000)
            try:
                await asyncio.wait_for(page.wait_for_load_state("networkidle"), SETTLE_SECONDS * 2)
            except Exception:  # noqa: BLE001 - a page that keeps fetching is drawn as it is
                pass
            await asyncio.sleep(SETTLE_SECONDS / 2)
            taken = await page.evaluate(EXTRACT)
            title = " ".join(str(taken.get("title") or page_file.parent.name).split())[:160]
            # A short note is still laid out as a note: it has no layout of its own to fall back on.
            as_is = (int(taken.get("text") or 0) < LEAST_TEXT
                     and page_file.suffix.lower() != ".md")
            if not as_is:
                head = (f'<header class="doc-head"><h1>{_escape(title)}</h1><div class="from">'
                        f'{_escape(made_on)}</div></header>')
                await page.evaluate(
                    """([css, body]) => {
                        for (const s of document.querySelectorAll('style,link[rel=stylesheet]')) s.remove();
                        for (const s of document.querySelectorAll('script')) s.remove();
                        document.documentElement.removeAttribute('style');
                        document.documentElement.className = '';
                        document.body.removeAttribute('style');
                        document.body.className = '';
                        const st = document.createElement('style'); st.textContent = css;
                        document.head.appendChild(st);
                        document.body.innerHTML = body;
                    }""", [PRINT_CSS, head + "<main>" + str(taken.get("html") or "") + "</main>"])
                try:
                    await page.wait_for_function(
                        "[...document.images].every(i => i.complete)", timeout=10000)
                except Exception:  # noqa: BLE001 - a picture that never came is left out
                    pass
            else:
                await page.emulate_media(media="print")
            pdf = await page.pdf(format=paper, print_background=True, display_header_footer=True,
                                 header_template="<span></span>",
                                 footer_template=FOOTER.replace("{title}", _escape(title)[:90]),
                                 margin={"top": "0.8in", "bottom": "0.85in",
                                         "left": "0.75in", "right": "0.75in"})
            return pdf, {"title": title, "as_is": as_is}
        finally:
            await browser.close()


async def make(who, root, page: str, paper: str = "letter") -> dict:
    """Make the PDF of a page and keep it in its task's folder. {rel, doc, link, title, pages,
    paper, as_is, bytes}. Refused when the page cannot be found or made."""
    from . import filelinks

    if not on(getattr(who, "org_id", None)):
        raise Refused("Printable PDFs are switched off: the gene page_pdf is off until it is kept in "
                      "Mutations. Nothing was made.")
    rel, page_file = await asyncio.to_thread(locate, root, page)
    size = PAPERS.get(str(paper or "letter").strip().lower(), "Letter")
    made_on = f"From Rouh, {time.strftime('%d %B %Y').lstrip('0')}, {rel}/{page_file.name}"
    try:
        pdf, said = await asyncio.wait_for(render(page_file, size, made_on=made_on), MOST_SECONDS)
    except asyncio.TimeoutError:
        raise Refused("The page took too long to lay out for paper; nothing was kept.") from None
    except Exception as exc:  # noqa: BLE001 - said as it is
        log.exception("the page %s could not be made a PDF", page_file)
        raise Refused("The page could not be laid out for paper here ("
                      + (str(exc).splitlines() or ["no reason given"])[0][:160] + ").") from None
    name = pdf_name(page_file)
    target = page_file.parent / name
    await asyncio.to_thread(target.write_bytes, pdf)
    pages = len(re.findall(rb"/Type\s*/Page[^s]", pdf))
    link = filelinks.link(who, rel, name)
    log.info("page pdf: %s/%s made into %s, %d pages on %s", rel, page_file.name, name, pages, size)
    return {"rel": rel, "doc": name, "link": link, "title": said["title"], "pages": pages,
            "paper": size, "as_is": said["as_is"], "bytes": len(pdf)}


# --- From the page itself: the PDF button beside Share, and a notice when it is ready ---------
#
# Version 2, night 12, 15 October 2026: Petar's mutation request on this gene, "I would like to
# also have a button to do that from the task page or from the HTML explainer page. Next to share
# button maybe or in the "..." menu. Maybe e should get a notification that the PDF is ready with
# link to download and go to task or page or whatever else is relevant".
#
# So the canvas bar has a PDF button beside Share wherever Share is (a task's page, a subtask's,
# an HTML page of the workspace), it asks the paper, and the making goes on on the server while
# he does anything else. When it is done he is told in Rouh's own notifications (`notices.py`):
# the PDF's download, the page and its task, each a button; left alone on the screen, it goes
# to his phone the way every notice does.

#: What is being made now, by (organisation, account, page file, paper): a second press while
#: one is under way does not start a second.
_MAKING: dict[tuple, float] = {}


def target(at: str) -> str:
    """The item the menu is about, as `locate` reads it: a page's or a Markdown file's path in
    the workspace, from the Share menu of a page open on the canvas or from an item's own menu
    on a task's page.

    Never a whole task. Share's word for a task or a subtask, `_task/<folder>`, is refused: it
    used to mean the task's `index.html`, which Petar could not see coming (15 October 2026,
    fr_4c075039223f): "With pdf I was at task, I pressed generate pdf and I got a pdf of the
    HTML. That is wrong. What if we had two pdfs? Which one would be prepared?" So a task's PDF
    is made item by item, from each item's own menu on its page, and a page open on its own
    makes that page and nothing else.
    """
    text = str(at or "").strip()
    if text.startswith("_task/"):
        raise Refused("A PDF is made of one item, not a whole task: open the menu on the page "
                      "or the .md you want on the task's page.")
    return text


def addresses(rel: str, page_file: Path) -> dict:
    """Where the notice leads in Rouh: the page, and the task or subtask it is in."""
    task = "/task/" + rel.strip("/")
    return {"page": task + "/" + page_file.name, "task": task}


def _made(who, rel: str, page_file: Path) -> dict | None:
    """The PDF kept beside the page from an earlier making, while it is newer than the page."""
    from . import filelinks

    doc = page_file.parent / pdf_name(page_file)
    try:
        made, drawn = doc.stat().st_mtime, page_file.stat().st_mtime
    except OSError:
        return None
    if made < drawn:
        return None
    return {"doc": doc.name, "link": filelinks.link(who, rel, doc.name), "at": made}


def state(who, root, at: str) -> dict:
    """What the button says for this page: whether it is there at all (the switch, and a page to
    print), a PDF already made and still as new as the page, and whether one is being made."""
    if not on(getattr(who, "org_id", None)):
        return {"on": False}
    try:
        rel, page_file = locate(root, target(at))
    except Refused as exc:
        return {"on": True, "page": False, "why": str(exc)}
    key = (str(who.org_id), str(who.user_id), str(page_file))
    making = [paper for (o, u, f, paper) in _MAKING if (o, u, f) == key]
    return {"on": True, "page": True, "rel": rel, "name": page_file.name,
            "made": _made(who, rel, page_file), "making": making[0] if making else ""}


async def make_and_tell(who, root, at: str, paper: str = "letter") -> dict:
    """Make the PDF in the background and tell him when it is ready. Answers at once with
    {started, paper} or {already}; refused (the switch, no page) before anything starts."""
    if not on(getattr(who, "org_id", None)):
        raise Refused("Printable PDFs are switched off: the gene page_pdf is off until it is kept in "
                      "Mutations. Nothing was made.")
    rel, page_file = await asyncio.to_thread(locate, root, target(at))
    size = PAPERS.get(str(paper or "letter").strip().lower(), "Letter")
    key = (str(who.org_id), str(who.user_id), str(page_file), size)
    if key in _MAKING:
        return {"already": True, "paper": size}
    _MAKING[key] = time.time()
    task = asyncio.get_running_loop().create_task(_make_then_tell(who, root, rel, page_file, size, key))
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)
    return {"started": True, "paper": size}


#: The makings under way, held so the loop does not lose them half way.
_TASKS: set = set()


async def _make_then_tell(who, root, rel: str, page_file: Path, size: str, key: tuple) -> None:
    from . import evolution, notices

    places = addresses(rel, page_file)
    is_index = page_file.name.lower() == "index.html"
    try:
        made = await make(who, root, f"{rel}/{page_file.name}", size)
    except Refused as exc:
        await notices.notify(
            who=who, kind="page_pdf", key=f"page_pdf:{key[2]}:{size}:{time.time():.0f}:no",
            title="The PDF could not be made",
            body=f"{exc}\n\nThe page is {rel}/{page_file.name}.",
            link=places["page"], link_label="Open the page")
        return
    except Exception:  # noqa: BLE001 - said as a notice, never lost
        log.exception("the PDF of %s/%s failed", rel, page_file.name)
        await notices.notify(
            who=who, kind="page_pdf", key=f"page_pdf:{key[2]}:{size}:{time.time():.0f}:fault",
            title="The PDF could not be made",
            body=f"Something went wrong laying out {rel}/{page_file.name} for paper. Nothing was kept.",
            link=places["page"], link_label="Open the page")
        return
    finally:
        _MAKING.pop(key, None)
    await asyncio.to_thread(evolution.used, SWITCH, "page_pdf", who=who,
                            detail=f"{made['rel']}: {made['pages']} pages, from the button")
    pages = f"{made['pages']} page{'s' if made['pages'] != 1 else ''}"
    links = [{"to": "file", "label": "Download the PDF", "href": made["link"],
              "title": f"Save {made['doc']}"}]
    if not is_index:
        links.append({"to": "page", "label": "Open the page", "href": places["page"]})
    links.append({"to": "task", "label": "Open the task", "href": places["task"]})
    base = str(notices.hooks.public_url or "").rstrip("/")
    await notices.notify(
        who=who, kind="page_pdf", key=f"page_pdf:{key[2]}:{size}:{time.time():.0f}",
        title=f"Your PDF is ready: {made['title']}"[:120],
        body=(f"{made['title']}, laid out for {made['paper']} paper: {pages}. Kept in the task "
              f"beside it, as {made['doc']}."
              + ("" if not made["as_is"] else " Its content could not be taken out of its layout, "
                 "so it is printed as it is drawn.")),
        link=places["page"] if not is_index else places["task"],
        links=links,
        phone_text=(f"Your PDF is ready: {made['title']} ({pages}, {made['paper']}).\n"
                    f"{base}{places['task']}" if base else ""))


# --- A chat as a PDF ---------------------------------------------------------------------------
#
# Petar, 15 October 2026 (fr_e8be3507d4d6), on task 108's page: "The chats and the page and finals
# don't have dots, and they should. Chat should be pdf-able as well as pages." So a chat's line on
# a task's page has the same three dots as a page's, and its PDF section makes the conversation:
# who said what and when, in the order it was said, with each card it drew under the message it
# came after, laid out with the same paper, type and footer as a page's PDF. It is kept in the
# task beside the task's other files, and Rouh's notification says when it is ready, with its
# download, the chat and the task, the way a page's does.

#: The most messages one chat's PDF holds: the newest, when a chat is longer still.
CHAT_MOST = 2000
#: The most cards one chat's PDF lays out under its messages.
CHAT_CARDS_MOST = 300


def chat_place(root, chat_id: str, at: str) -> tuple[str, dict]:
    """(the task's folder, the chat's row) for a chat named from a task's page, refused unless
    the chat is that task's, or a fork of one of its chats. The PDF is kept in that folder."""
    from . import conversations, forks

    if not root:
        raise Refused("There is no workspace on this machine to keep the PDF in.")
    chat_id = str(chat_id or "").strip()
    row = conversations.chat(chat_id) if chat_id else None
    if not row:
        raise Refused("There is no such chat.")
    base = Path(root).resolve()
    rel = str(at or "").strip().strip("/")
    folder = (base / rel).resolve() if rel else base
    if not rel or (base not in folder.parents) or not folder.is_dir():
        raise Refused("A chat's PDF is made from its task's page.")
    owners = {conversations.folder_of(chat_id)}
    root_chat = forks.root_of(chat_id)
    if root_chat and root_chat != chat_id:
        owners.add(conversations.folder_of(root_chat))
    if rel not in owners:
        raise Refused("That chat is not one of this task's.")
    return rel, row


def chat_pdf_name(title: str) -> str:
    """What a chat's PDF is called: `chat-` and its name, in plain letters."""
    from .objectindex import _its_emoji

    _mark, words = _its_emoji(title or "")
    slug = re.sub(r"[^a-z0-9]+", "-", words.lower()).strip("-")[:60].strip("-")
    return f"chat-{slug or 'untitled'}.pdf"


def _when(ts) -> str:
    try:
        return time.strftime("%d %b %Y, %H:%M", time.localtime(float(ts))).lstrip("0")
    except (TypeError, ValueError, OverflowError):
        return ""


def _card_html(card: dict) -> str:
    """One card as it reads on paper: its title, what it says it is, and each block that is words,
    a table or a list. What only a screen can draw (a page of its own markup, a form, a button)
    is said to be there rather than left out without a word."""
    from . import docview

    out = [f'<div class="card-name">Card: {_escape(card.get("title") or "Untitled")}</div>']
    if card.get("description"):
        out.append(f'<p class="card-about">{_escape(card["description"])}</p>')
    shown = 0
    for block in card.get("blocks") or []:
        if not isinstance(block, dict):
            continue
        kind = block.get("block")
        label = str(block.get("label") or block.get("title") or "").strip()
        head = f"<h4>{_escape(label)}</h4>" if label and kind not in ("stat", "link") else ""
        if kind == "text":
            out.append(head + docview.markdown_html(str(block.get("text") or "")))
        elif kind == "stat":
            hint = str(block.get("hint") or "").strip()
            out.append(f'<p><strong>{_escape(block.get("value"))}</strong>'
                       + (f" {_escape(label)}" if label else "")
                       + (f' <span class="hint">({_escape(hint)})</span>' if hint else "") + "</p>")
        elif kind == "table":
            cols = "".join(f"<th>{_escape(c)}</th>" for c in block.get("columns") or [])
            rows = "".join("<tr>" + "".join(f"<td>{_escape(c)}</td>" for c in r) + "</tr>"
                           for r in block.get("rows") or [] if isinstance(r, list))
            out.append(head + f"<table><thead><tr>{cols}</tr></thead><tbody>{rows}</tbody></table>")
        elif kind == "list":
            items = "".join(f"<li>{_escape(i)}</li>" for i in block.get("items") or [])
            out.append(head + f"<ul>{items}</ul>")
        elif kind == "code":
            out.append(head + f"<pre>{_escape(block.get('text'))}</pre>")
        elif kind == "chart":
            pairs = "".join(f"<tr><td>{_escape(k)}</td><td>{_escape(v)}</td></tr>"
                            for k, v in zip(block.get("labels") or [], block.get("values") or []))
            out.append(head + f"<table><tbody>{pairs}</tbody></table>")
        elif kind == "link" and block.get("href"):
            out.append(f'<p><a href="{_escape(block["href"])}">{_escape(label or block["href"])}</a></p>')
        elif kind == "image" and str(block.get("src") or "").startswith(("https://", "data:")):
            cap = str(block.get("caption") or block.get("alt") or "").strip()
            out.append(f'<figure><img src="{_escape(block["src"])}" alt="{_escape(cap)}">'
                       + (f"<figcaption>{_escape(cap)}</figcaption>" if cap else "") + "</figure>")
        elif kind == "sources":
            rows = "".join(f'<li><a href="{_escape(s.get("url"))}">{_escape(s.get("title") or s.get("url"))}</a></li>'
                           for s in block.get("sources") or [] if isinstance(s, dict) and s.get("url"))
            if rows:
                out.append(f"<h4>Sources</h4><ol>{rows}</ol>")
        else:
            continue
        shown += 1
    if not shown and not card.get("description"):
        out.append('<p class="hint">This card is drawn on the screen only.</p>')
    return '<div class="card">' + "".join(out) + "</div>"


def _chat_message_html(msg: dict, person: str) -> str:
    """One message on paper, with its speaker, time and attachment names."""
    from . import docview

    text = str(msg.get("text") or "")
    mine = msg.get("role") == "user"
    files = [str(a.get("name") or "") for a in msg.get("attachments") or [] if isinstance(a, dict)]
    body = (f"<p>{_escape(text)}</p>".replace("\n", "<br>") if mine
            else docview.markdown_html(text))
    if files:
        body += f'<p class="hint">Attached: {_escape(", ".join(f for f in files if f))}</p>'
    return (f'<section class="msg {"me" if mine else "rouh"}"><div class="who">'
            f'{_escape(person if mine else "Rouh")}<span class="at">{_escape(_when(msg.get("ts")))}'
            f'</span></div>{body}</section>')


def _chat_document(who, said: list[dict], under: dict, title: str) -> tuple[str, str]:
    """Build paper markup from a loaded transcript and its cards, without reading chat stores."""
    person = str(getattr(who, "name", "") or "").strip() or "You"
    person = person[:1].upper() + person[1:]
    out = []
    for msg in said:
        if msg.get("stopped"):
            out.append('<p class="hint">Stopped here.</p>')
            continue
        out.append(_chat_message_html(msg, person))
        for card in under.get(msg.get("id"), []):
            out.append(_card_html(card))
    from .objectindex import _its_emoji

    named = _its_emoji(title)[1] or "Untitled chat"
    return (f'<!doctype html><html><head><meta charset="utf-8"><title>{_escape(named)}</title>'
            f'<style>{PRINT_CSS}{CHAT_CSS}</style></head><body>'
            f'<header class="doc-head"><h1>{_escape(named)}</h1><div class="from">{{made_on}}</div></header>'
            f'<main>{"".join(out) or "<p>Nothing has been said in this chat yet.</p>"}</main>'
            f'</body></html>'), named


def chat_page(who, chat_id: str, title: str) -> str:
    """The whole conversation as one page to lay out: each message under who said it and when,
    Rouh's in the Markdown it was written in, and each card under the message it came after."""
    from . import artifacts, conversations, docview, runtime

    said = runtime.memory.transcript(chat_id, CHAT_MOST)
    ids = {m.get("id") for m in said}
    under: dict = {}
    try:
        cards = artifacts.history(chat_id, conversations.folder_of(chat_id), None, CHAT_CARDS_MOST)
    except Exception:  # noqa: BLE001 - the words are the chat; its cards are drawn when they can be
        log.exception("the cards of chat %s could not be read for its PDF", chat_id)
        cards = []
    for card in reversed(cards):
        if card.get("after_message_id") in ids:
            under.setdefault(card["after_message_id"], []).append(card)
    return _chat_document(who, said, under, title)


#: How a conversation reads on paper, over `PRINT_CSS`.
CHAT_CSS = """
.msg { margin: 0 0 12pt; break-inside: auto; }
.msg .who { font-family: "Helvetica Neue", Arial, sans-serif; font-size: 8.5pt; font-weight: 700;
       letter-spacing: .03em; text-transform: uppercase; color: #3a3a3c; margin-bottom: 3pt;
       break-after: avoid; page-break-after: avoid; }
.msg .who .at { font-weight: 400; text-transform: none; letter-spacing: 0; color: #8e8e93;
       margin-left: 6pt; }
.msg.me { padding: 6pt 9pt; background: #f2f2f5; border-radius: 4pt; }
.msg.me p:last-child { margin-bottom: 0; }
.card { margin: -4pt 0 12pt; padding: 7pt 10pt; border: 0.6pt solid #c7c7cc; border-radius: 4pt;
       break-inside: avoid; page-break-inside: avoid; }
.card .card-name { font-family: "Helvetica Neue", Arial, sans-serif; font-weight: 700; font-size: 10pt;
       margin-bottom: 3pt; }
.card .card-about { color: #3a3a3c; }
.card h4 { margin: 8pt 0 3pt; }
.hint { color: #8e8e93; font-size: 9pt; }
"""


async def render_html(markup: str, title: str, paper: str = "Letter") -> bytes:
    """Markup already laid out for paper, as PDF bytes, with the same footer as a page's. Nothing
    it holds may reach anything but a public https address."""
    from playwright.async_api import async_playwright

    from .browsing import chromium

    async with async_playwright() as pw:
        browser = await chromium(pw, headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        try:
            context = await browser.new_context(viewport={"width": 1100, "height": 1400},
                                                java_script_enabled=False)

            async def gate(route):
                url = route.request.url
                return await (route.continue_() if _public_https(url) and not url.startswith("file:")
                              else route.abort())

            await context.route("**/*", gate)
            page = await context.new_page()
            await page.set_content(markup, wait_until="load", timeout=30000)
            return await page.pdf(format=paper, print_background=True, display_header_footer=True,
                                  header_template="<span></span>",
                                  footer_template=FOOTER.replace("{title}", _escape(title)[:90]),
                                  margin={"top": "0.8in", "bottom": "0.85in",
                                          "left": "0.75in", "right": "0.75in"})
        finally:
            await browser.close()


async def make_chat(who, root, chat_id: str, at: str, paper: str = "letter") -> dict:
    """Make the PDF of a chat and keep it in its task's folder. {rel, doc, link, title, pages,
    paper, bytes}. Refused when the chat is not that task's, or cannot be made."""
    from . import filelinks

    if not on(getattr(who, "org_id", None)):
        raise Refused("Printable PDFs are switched off: the gene page_pdf is off until it is kept in "
                      "Mutations. Nothing was made.")
    rel, row = await asyncio.to_thread(chat_place, root, chat_id, at)
    size = PAPERS.get(str(paper or "letter").strip().lower(), "Letter")
    markup, named = await asyncio.to_thread(chat_page, who, chat_id, str(row.get("title") or ""))
    markup = markup.replace("{made_on}", _escape(
        f"A chat in Rouh, made {time.strftime('%d %B %Y').lstrip('0')}, from {rel}"), 1)
    try:
        pdf = await asyncio.wait_for(render_html(markup, named, size), MOST_SECONDS)
    except asyncio.TimeoutError:
        raise Refused("The chat took too long to lay out for paper; nothing was kept.") from None
    except Exception as exc:  # noqa: BLE001 - said as it is
        log.exception("the chat %s could not be made a PDF", chat_id)
        raise Refused("The chat could not be laid out for paper here ("
                      + (str(exc).splitlines() or ["no reason given"])[0][:160] + ").") from None
    name = chat_pdf_name(str(row.get("title") or ""))
    await asyncio.to_thread((Path(root).resolve() / rel / name).write_bytes, pdf)
    pages = len(re.findall(rb"/Type\s*/Page[^s]", pdf))
    log.info("chat pdf: %s made into %s/%s, %d pages on %s", chat_id, rel, name, pages, size)
    return {"rel": rel, "doc": name, "link": filelinks.link(who, rel, name), "title": named,
            "pages": pages, "paper": size, "bytes": len(pdf)}


async def make_chat_and_tell(who, root, chat_id: str, at: str, paper: str = "letter") -> dict:
    """A chat's PDF made in the background, and a notification when it is ready, as a page's is
    (`make_and_tell`). Answers at once with {started, paper} or {already}."""
    if not on(getattr(who, "org_id", None)):
        raise Refused("Printable PDFs are switched off: the gene page_pdf is off until it is kept in "
                      "Mutations. Nothing was made.")
    rel, _row = await asyncio.to_thread(chat_place, root, chat_id, at)
    size = PAPERS.get(str(paper or "letter").strip().lower(), "Letter")
    key = (str(who.org_id), str(who.user_id), "chat:" + str(chat_id), size)
    if key in _MAKING:
        return {"already": True, "paper": size}
    _MAKING[key] = time.time()
    task = asyncio.get_running_loop().create_task(_chat_then_tell(who, root, chat_id, rel, size, key))
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)
    return {"started": True, "paper": size}


async def _chat_then_tell(who, root, chat_id: str, rel: str, size: str, key: tuple) -> None:
    from . import addressing, evolution, notices

    chat_at = addressing.url_for("chat", chat_id)
    task_at = "/task/" + rel.strip("/")
    try:
        made = await make_chat(who, root, chat_id, rel, size)
    except Exception as exc:  # noqa: BLE001 - said as a notice, never lost
        if not isinstance(exc, Refused):
            log.exception("the PDF of chat %s failed", chat_id)
        await notices.notify(
            who=who, kind="page_pdf", key=f"page_pdf:{key[2]}:{size}:{time.time():.0f}:no",
            title="The PDF could not be made",
            body=(str(exc) if isinstance(exc, Refused)
                  else "Something went wrong laying out the chat for paper. Nothing was kept."),
            link=chat_at, link_label="Open the chat")
        return
    finally:
        _MAKING.pop(key, None)
    await asyncio.to_thread(evolution.used, SWITCH, "chat_pdf", who=who,
                            detail=f"chat {chat_id}: {made['pages']} pages, from its menu")
    pages = f"{made['pages']} page{'s' if made['pages'] != 1 else ''}"
    base = str(notices.hooks.public_url or "").rstrip("/")
    await notices.notify(
        who=who, kind="page_pdf", key=f"page_pdf:{key[2]}:{size}:{time.time():.0f}",
        title=f"Your PDF is ready: {made['title']}"[:120],
        body=(f"The chat {made['title']}, laid out for {made['paper']} paper: {pages}. Kept in the "
              f"task, as {made['doc']}."),
        link=chat_at,
        links=[{"to": "file", "label": "Download the PDF", "href": made["link"],
                "title": f"Save {made['doc']}"},
               {"to": "chat", "label": "Open the chat", "href": chat_at},
               {"to": "task", "label": "Open the task", "href": task_at}],
        phone_text=(f"Your PDF is ready: {made['title']} ({pages}, {made['paper']}).\n"
                    f"{base}{task_at}" if base else ""))


__all__ = ["PAPERS", "Refused", "SWITCH", "TITLE", "addresses", "chat_page", "chat_pdf_name",
           "chat_place", "locate", "make", "make_and_tell", "make_chat", "make_chat_and_tell", "on",
           "pdf_name", "render", "render_html", "state", "target"]
