"""A Google Doc of this page: a page of a task made into a Google Doc, from the share icon's menu.

Built by the nightly feature run, night 21, 24 October 2026 (task 94, idea I-128). ‹His› work is
written on Rouh's pages, and the people ‹he› works with outside Rouh read and comment in Google
Docs. On 13 October 2026 ‹he› had a job make a Google Doc of a task's findings to send on; the
sharing rule ‹he› gave Rouh speaks of "a Google Doc copy" of a task; and a task's copies are kept
in step by hand (night 14's Copies kept in step). Rouh could make a Google Doc only of plain text
(`docs.create`), so a page went across without its headings, lists, tables or links, or a job
wrote it out again.

So, while its switch is on, the menu under the share icon of a page open on the canvas has a
section **Google Doc**: **Make a Google Doc of this page** turns the page into a Google Doc in the
connected Google account's Drive, keeping its headings, paragraphs, lists, tables, bold and
links, and leaving out what is only there on the screen (its menu, buttons, scripts, pictures
drawn by code). Drive does the converting, from the page's own HTML (`clean`), so no model is
asked. The person is given edit access when the account is not their own. The document is kept
for the page: the next press, **Update the Google Doc**, puts the page as it is now into the same
document, so its link stays the same, and **Open the Google Doc** opens it. A notice says when it
is ready, with the link.

**Whose.** A page of ‹his› workspace, found the way the PDF of a page is (`page_pdf.locate`); the
document is made with the Google account Rouh has for the person, and which document belongs to
which page is ‹his› own setting (`user_settings`, `page_gdoc`), by `org_id` and `user_id`.

**Its switch** is `page_gdoc` (`rouh/switches.py`): off, the section is not in the menu.
"""
from __future__ import annotations

import html
import html.parser
import json
import logging
import re
import time

log = logging.getLogger("rouh.page_gdoc")

SWITCH = "page_gdoc"
#: The person's own setting: {page path: {id, link, at, title}}.
KEPT = "page_gdoc"
#: The largest page made into a document.
MOST_BYTES = 4_000_000

#: The elements kept as they are, without their attributes.
_KEEP = {"h1", "h2", "h3", "h4", "h5", "h6", "p", "ul", "ol", "li", "table", "thead", "tbody",
         "tfoot", "tr", "td", "th", "b", "strong", "i", "em", "u", "s", "blockquote", "pre",
         "code", "sup", "sub", "br", "hr", "caption", "dl", "dt", "dd", "mark", "small"}
#: Blocks of the screen kept as a paragraph each.
_AS_P = {"figcaption", "summary", "address"}
#: The elements never carried across, with everything inside them.
_DROP = {"script", "style", "nav", "button", "svg", "noscript", "template", "select", "option",
         "textarea", "input", "head", "title", "form", "dialog", "iframe", "canvas", "video",
         "audio", "picture", "img", "object", "embed", "menu"}
#: An element whose id or class says it is the page's own machinery, not its content.
_DROP_MARK = re.compile(r"(^|[\s_-])(menu|hamburger|burger|navbar|sidebar|toc|xray|toolbar|"
                        r"skip-link|nav-toggle|drawer|toast)($|[\s_-])", re.I)
_VOID = {"br", "hr", "img", "meta", "link", "input", "source", "wbr", "col", "area", "base"}
#: The kept elements that hold a paragraph's words, and the inline ones that go inside one.
_BLOCKS = {"h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "td", "th", "pre", "blockquote", "dt",
           "dd", "caption"}
_INLINE = {"b", "strong", "i", "em", "u", "s", "code", "sup", "sub", "a", "mark", "small", "span",
           "abbr", "cite", "q", "time", "label"}


def on(who) -> bool:
    from . import switches

    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


class _Clean(html.parser.HTMLParser):
    """The page's content as plain HTML Drive turns into a document."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self._stack: list[tuple[str, bool, str]] = []  # (tag, dropping from here, what it wrote)
        # Words of the screen outside any paragraph (a label in a div) get one of their own.
        self._loose = False

    def _in_block(self) -> bool:
        return any(w in _BLOCKS for _t, _d, w in self._stack)

    def _end_loose(self) -> None:
        if self._loose:
            self.out.append("</p>")
            self._loose = False

    def _start_loose(self) -> None:
        if not self._loose and not self._in_block():
            self.out.append("<p>")
            self._loose = True

    def _dropping(self) -> bool:
        return any(drop for _t, drop, _w in self._stack)

    def handle_starttag(self, tag, attrs):
        marks = dict(attrs)
        if tag in _VOID:
            if not self._dropping() and tag in ("br", "hr"):
                self.out.append(f"<{tag}>")
            return
        # Not the hidden attribute: a page of several pages hides all but the one shown.
        drop = (tag in _DROP or marks.get("aria-hidden") == "true"
                or bool(_DROP_MARK.search(f"{marks.get('id') or ''} {marks.get('class') or ''}")))
        wrote = ""
        if not drop and not self._dropping():
            if tag in _INLINE:
                self._start_loose()
            elif tag not in _KEEP or tag in _BLOCKS or tag in ("ul", "ol", "table", "dl", "hr"):
                self._end_loose()
            if tag not in _KEEP and tag not in ("a",):
                # A span or a box of the screen: a word boundary where the screen had one.
                self.out.append(" ")
            if tag in _KEEP:
                wrote = tag
                span = ""
                if tag in ("td", "th"):
                    for name in ("colspan", "rowspan"):
                        if str(marks.get(name) or "").isdigit():
                            span += f' {name}="{marks[name]}"'
                self.out.append(f"<{tag}{span}>")
            elif tag in _AS_P:
                wrote = "p"
                self.out.append("<p>")
            elif tag == "a":
                href = str(marks.get("href") or "")
                if re.match(r"^(https?:|mailto:)", href, re.I):
                    wrote = "a"
                    self.out.append(f'<a href="{html.escape(href, quote=True)}">')
        self._stack.append((tag, drop, wrote))

    def handle_endtag(self, tag):
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i][0] == tag:
                closed = self._stack[i:]
                del self._stack[i:]
                if not self._dropping():
                    if tag not in _INLINE:
                        self._end_loose()
                    for _t, drop, wrote in reversed(closed):
                        if wrote and not drop:
                            self.out.append(f"</{wrote}>")
                    if tag not in _KEEP and tag != "a":
                        self.out.append(" ")
                return

    def handle_data(self, data):
        if not self._dropping() and data:
            if data.strip():
                self._start_loose()
            self.out.append(html.escape(data, quote=False))

    def close(self):
        super().close()
        self._end_loose()


def clean(markup: str, title: str) -> str:
    """The page as a plain HTML document for Drive to convert: its content and nothing else."""
    body = re.search(r"<body[^>]*>(.*)</body>", markup, re.S | re.I)
    reader = _Clean()
    reader.feed(body.group(1) if body else markup)
    reader.close()
    inner = "".join(reader.out)
    # Empty blocks the screen's own layout left behind.
    inner = re.sub(r"<(p|li|h[1-6])>\s*</\1>", "", inner)
    return ("<!DOCTYPE html><html><head><meta charset=\"utf-8\">"
            f"<title>{html.escape(title)}</title></head><body>{inner}</body></html>")


def kept(who) -> dict[str, dict]:
    from .models import UserSetting

    value = (UserSetting.objects.filter(user_id=str(who.user_id), org_id=who.org_id or "", name=KEPT)
             .values_list("value", flat=True).first())
    try:
        held = json.loads(value) if value else {}
    except (TypeError, ValueError):
        held = {}
    return {str(k): v for k, v in held.items() if isinstance(v, dict) and v.get("id")} \
        if isinstance(held, dict) else {}


def _keep(who, page: str, made: dict) -> None:
    from .models import UserSetting

    held = kept(who)
    held[page] = made
    UserSetting.objects.bulk_create(
        [UserSetting(user_id=str(who.user_id), org_id=who.org_id or "", name=KEPT,
                     value=json.dumps(held), updated_at=time.time())],
        update_conflicts=True, unique_fields=["user_id", "name"],
        update_fields=["org_id", "value", "updated_at"])


def _page(root, at: str):
    from . import page_pdf

    rel, page_file = page_pdf.locate(root, page_pdf.target(at))
    return f"{rel}/{page_file.name}", page_file


def state(who, root, at: str) -> dict:
    """Whether the menu offers Google Doc for this page, and the document made of it, if any."""
    from . import page_pdf

    if not on(who):
        return {"on": False}
    try:
        page, _file = _page(root, at)
    except page_pdf.Refused:
        return {"on": True, "page": False}
    return {"on": True, "page": True, "made": kept(who).get(page)}


def _own_address(who) -> str:
    from django.contrib.auth import get_user_model

    user = get_user_model().objects.filter(pk=int(who.user_id)).first() \
        if str(who.user_id).isdigit() else None
    return str(getattr(user, "email", "") or "").strip().lower()


async def make(who, google, root, at: str) -> dict:
    """The page made into its Google Doc, or put into the one made of it before. {ok, made, ...}."""
    import asyncio

    from asgiref.sync import sync_to_async

    from . import evolution, page_pdf, pages

    if not await sync_to_async(on)(who):
        return {"ok": False, "error": "Google Doc is switched off: the gene page_gdoc is off in Evolution, Mutations."}
    try:
        page, page_file = await asyncio.to_thread(_page, root, at)
    except page_pdf.Refused as exc:
        return {"ok": False, "error": str(exc)}
    if google is None:
        return {"ok": False, "error": "Google is not set up here, so no Google Doc can be made."}
    try:
        if page_file.stat().st_size > MOST_BYTES:
            return {"ok": False, "error": "This page is too large to make into a Google Doc."}
        markup = await asyncio.to_thread(page_file.read_text, "utf-8", "replace")
    except OSError:
        return {"ok": False, "error": "The page could not be read."}
    title = pages.title_of(page_file) or page_file.parent.name
    document = clean(markup, title)
    try:
        services = google(who)
        drive = services.drive
    except Exception as exc:  # noqa: BLE001 - not connected
        log.info("no Drive to make a Google Doc with: %r", exc)
        return {"ok": False, "error": "Google is not connected. Connect it in Settings first."}
    before = (await sync_to_async(kept)(who)).get(page)
    from .google_oauth import NotConnected

    try:
        done = await drive.import_html(title, document, file_id=before["id"] if before else "")
    except NotConnected as exc:
        # The services are made before anything asks Google, so a person with no Google
        # account is only found out here, at the first call.
        log.info("no Drive to make a Google Doc with: %r", exc)
        return {"ok": False, "error": "Google is not connected. Connect it in Settings first."}
    except Exception as exc:  # noqa: BLE001 - said on the screen
        log.info("the Google Doc of %s could not be %s: %r", page, "updated" if before else "made", exc)
        if before:
            # Gone from Drive, or no longer the account's: a new one is made.
            try:
                done = await drive.import_html(title, document)
                before = None
            except Exception as again:  # noqa: BLE001
                log.info("a new Google Doc of %s could not be made either: %r", page, again)
                return {"ok": False, "error": "Google Drive did not take it. Try again in a moment."}
        else:
            return {"ok": False, "error": "Google Drive did not take it. Try again in a moment."}
    link = done.get("link") or f"https://docs.google.com/document/d/{done['id']}/edit"
    shared = ""
    mine = await sync_to_async(_own_address)(who)
    account = ""
    with_address = getattr(services, "address", None)
    if callable(with_address):
        try:
            account = str(with_address() or "").lower()
        except Exception:  # noqa: BLE001
            account = ""
    if mine and mine != account and not before:
        try:
            await drive.share_with_person(done["id"], mine, "writer", notify=False)
            shared = mine
        except Exception as exc:  # noqa: BLE001 - the document is made; said in the answer
            log.info("the Google Doc of %s could not be shared with its owner: %r", page, exc)
    made = {"id": done["id"], "link": link, "at": time.time(), "title": title}
    await sync_to_async(_keep)(who, page, made)
    if before:
        await sync_to_async(evolution.used)("page_gdoc", "updated", who=who,
                                            detail=f"updated the Google Doc of {page}")
    else:
        await sync_to_async(evolution.used)("page_gdoc", "made", who=who,
                                            detail=f"made the Google Doc of {page}")
    return {"ok": True, "made": made, "updated": bool(before), "shared": shared, "page": page}


def opened(who, root, at: str) -> None:
    """Open the Google Doc was pressed: counted as a use."""
    from . import evolution, page_pdf

    if not on(who):
        raise page_pdf.Refused("Google Doc is switched off: the gene page_gdoc is off in Evolution, Mutations.")
    page, _file = _page(root, at)
    evolution.used(SWITCH, "opened", who=who, detail=f"opened the Google Doc of {page}")


__all__ = ["KEPT", "SWITCH", "clean", "kept", "make", "on", "opened", "state"]
