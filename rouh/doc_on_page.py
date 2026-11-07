"""On the page yet?: which paragraphs of a Google Doc a task links to are not on the task's pages.

Built by the nightly feature run, night 21, 24 October 2026 (task 94, idea I-127). Copy for
‹his› company's site is written in Google Docs by the person ‹he› works with, and put on the
pages of one of ‹his› tasks, by hand and with Ask AI. On 22 October 2026 ‹he› asked a chat "can
you tell me if task 61 has been updated by him and in sync with his word doc", and nothing in
Rouh could say it: a job read the document and the pages and compared them by eye, for twenty
minutes. Whether a page holds a document's words, word for word, is not a question for a model
at all; it is a comparison.

So, while its switch is on, each Google Doc in a task's **Documents** section (`rouh/task_docs.py`)
has **On the page?**. Pressed, Rouh reads the document from Drive once and every page of the task
(its `.html` files) from the workspace, and says, under the document's line, in place: how many
of the document's paragraphs are on the task's pages word for word, on which page most of them
are, and each paragraph that is on none of them. Quotes, dashes and spaces are compared as a
reader sees them (`copy_exact.same`), and a paragraph counts as on a page when its words are there
in that order. No model is asked.

**Whose.** Only a document this task's own notes link to, read with the Google account Rouh has
for the person; only this task's own pages.

**Its switch** is `doc_on_page` (`rouh/switches.py`): off, the button is not there.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

log = logging.getLogger("rouh.doc_on_page")

SWITCH = "doc_on_page"
#: The shortest paragraph that is checked, in words: a heading of two words is everywhere.
FEWEST_WORDS = 4
#: The most pages read, the largest one, and the most paragraphs named back.
MOST_PAGES = 60
MOST_BYTES = 3_000_000
NAMED = 15

_LINK_MARK = re.compile(r"\s*\[link: [^\]]*\]")
#: A person's chip, as the reading writes it: "[person: Tom Carter, tom@example.test]" reads "Tom Carter".
_PERSON = re.compile(r"\[person: ([^,\]]+)[^\]]*\]")
_TAB_LINE = re.compile(r"^=== .* ===$")
_SKIP = ("temp", "node_modules", "source-code", "sqlite")


def on(org_id=None) -> bool:
    from . import switches

    return switches.on(SWITCH, org_id or None)


def button(person, one: dict) -> str:
    """The press on a document's line in Documents, for a Google Doc while the switch is on."""
    try:
        if one.get("kind") != "Google Doc" or not on(getattr(person, "org_id", None)):
            return ""
    except Exception:  # noqa: BLE001 - the line is drawn without it
        log.exception("the switch doc_on_page could not be read")
        return ""
    return '<button type="button" class="obtn odoc-onpage" hidden>On the page?</button>'


def paragraphs(text: str) -> list[str]:
    """The document's paragraphs worth checking, as Drive's reading gives them."""
    out, seen = [], set()
    for line in str(text or "").split("\n"):
        if line.startswith("Linked documents: "):
            break
        if _TAB_LINE.match(line.strip()):
            continue
        words = _PERSON.sub(r"\1", _LINK_MARK.sub("", line)).strip().lstrip("-*\u2022 ").strip()
        if len(words.split()) < FEWEST_WORDS:
            continue
        key = _key(words)
        if key and key not in seen:
            seen.add(key)
            out.append(words)
    return out


def _key(words: str) -> str:
    from .copy_exact import same

    return same(words)


def pages_of(root, folder: str) -> list[tuple[str, str]]:
    """(the page's title or path, its words as a reader sees them) for each page of the task."""
    from . import pages
    from .copy_exact import shown

    base = Path(root) / folder
    out = []
    for path in sorted(base.rglob("*.html")):
        rel = path.relative_to(base)
        if any(p.startswith(".") or p in _SKIP for p in rel.parts):
            continue
        try:
            if path.stat().st_size > MOST_BYTES:
                continue
            words = shown(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        out.append((pages.title_of(path) or rel.as_posix(), words))
        if len(out) >= MOST_PAGES:
            break
    return out


def compare(paras: list[str], held: list[tuple[str, str]]) -> dict:
    """{on, off, most}: how many paragraphs are on a page, which are on none, and the page with most."""
    counts = [0] * len(held)
    off = []
    found = 0
    for words in paras:
        key = _key(words)
        hits = [i for i, (_t, text) in enumerate(held) if key in text]
        if hits:
            found += 1
            for i in hits:
                counts[i] += 1
        else:
            off.append(words)
    most = ""
    if held and max(counts) > 0:
        most = held[counts.index(max(counts))][0]
    return {"on": found, "off": off, "most": most, "pages": len(held)}


def said(name: str, total: int, got: dict) -> str:
    """The answer under the document's line, in plain words."""
    if not total:
        return f"{name} has no paragraphs of {FEWEST_WORDS} words or more to look for."
    if not got["pages"]:
        return "This task has no pages to look on."
    lines = [f"{got['on']} of {total} paragraphs of {name} are on this task's pages word for word"
             + (f", most of them on {got['most']}." if got["most"] else ".")]
    if not got["off"]:
        lines.append("Every paragraph is on a page.")
    else:
        many = len(got["off"])
        lines.append("Not on any page:" if many <= NAMED
                     else f"Not on any page ({many}; the first {NAMED}):")
        for words in got["off"][:NAMED]:
            lines.append("- " + (words if len(words) <= 220 else words[:217].rstrip() + "..."))
    return "\n".join(lines)


async def check(who, google, root, folder: str, doc: str) -> dict:
    """On the page?, for one Google Doc this task's notes link to."""
    from asgiref.sync import sync_to_async

    from . import evolution, task_docs

    if not await sync_to_async(on)(getattr(who, "org_id", None)):
        return {"ok": False, "error": "On the page? is switched off."}
    docs = await sync_to_async(task_docs.linked)(root, folder)
    one = next((d for d in docs if d["id"] == doc), None)
    if one is None or one["kind"] != "Google Doc":
        return {"ok": False, "error": "That Google Doc is not linked in this task's notes."}
    if google is None:
        return {"ok": False, "error": "Google is not set up here, so nothing can be read."}
    from .google_oauth import NotConnected

    try:
        read = await google(who).docs.read(doc)
    except NotConnected:
        return {"ok": False, "error": "Google is not connected. Connect it in Settings first."}
    except Exception as exc:  # noqa: BLE001 - said on the page
        log.info("the document %s could not be read: %r", doc, exc)
        return {"ok": False, "error": "It could not be read from Google Docs. Try again."}
    paras = paragraphs(read.get("text") or "")
    held = await sync_to_async(pages_of)(root, folder)
    got = compare(paras, held)
    name = str(read.get("title") or one.get("title") or "the document")
    await sync_to_async(evolution.used)(
        SWITCH, "checked", who=who,
        detail=f"{got['on']} of {len(paras)} paragraphs on the task's {got['pages']} pages")
    return {"ok": True, "text": said(name, len(paras), got), "on": got["on"], "of": len(paras)}


__all__ = ["SWITCH", "button", "check", "compare", "on", "pages_of", "paragraphs", "said"]
