"""Comments on Rouh's pages, for Rouh and its agents: read them, add one, change one, take one away.

Petar, 3 November 2026 (fr_a713abaff0d5), after a job said of the explainer with his brother's
comments: "so they're probably comments left on the page in Rouh, which I have no tool to read."
And: "build the tools to read and edit and delete and create comments on the html visual
explainer pages for rouh and its agents."

The comments are the ones people pin to a page in the browser (`rouh/comments.py`, drawn by
`rouh/static/askai/comments.js`), and this reads and writes those very rows, never a copy: what
Rouh adds is on the page at the next load, and what it takes away is gone from it. One tool,
`page_comments`, does every action; a chat turn has it, and every background job has it through
Rouh's gateway (`rouh/job_gateway.py`), where `list` only reads, adding, answering, changing and
resolving write only on the owner's own page, and deleting waits for the owner's word unless they
asked for it (`rouh/job_policy.py`).

**Which page.** A page in the workspace by its path (`work/x/148.y/148-03.z/index.html`), a step's
or task's folder or number (`148-03`, whose `index.html` is meant), or one of Rouh's own addresses
for it (`/task/...`, `/workspace/...`, with or without `?doc=`). The comments are the owner's, as
on their canvas: the speaker's `user_id` and `org_id` and the page's path (`comments.Place`).

**What a comment is on.** Each thread is pinned to one element of the page, and its anchor keeps
the element's tag, its place and its words; reading says them, and whether that element is still in
the page's file. A new thread is pinned to the element that holds a passage Rouh quotes (`on`), or
to one by its `#id`, found by reading the page's file the way a browser builds it (`_Tree`), and
described the way the page describes an element it is pressed on (`describe` in comments.js): the
same place, the same words and the same fingerprint of them (`hash_of`), so the page finds it
exactly as it finds a person's pin. The quote is kept too, and the page looks for it when nothing
else finds the element (`byQuote` in comments.js), so a page whose scripts change what the file
says still draws the pin where the words are.

**Who did it.** What Rouh writes is under its own author, `comments.AGENT_ID`, which no account
can be: the page draws it with the sparkle and the name Rouh, or "Rouh's agent" when no person was
watching (a background job, a beat), so nobody takes it for a person's. Rouh acts for the page's
owner, so it may resolve, reopen and take away any comment, as the owner may; it may change only
what it wrote itself, because on a page nobody but its author changes a message (`comments.edit`).
It never tags anybody: a tag is a letter to that person, and sending is not this tool's.

No model is asked here: it is the page's own rows and file, read and written by code.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from . import comments

log = logging.getLogger("rouh.page_comments")

TOOL_NAME = "page_comments"
ACTIONS = ("list", "add", "reply", "edit", "delete", "resolve", "reopen")
#: The actions that write: everything but `list`.
WRITES = tuple(a for a in ACTIONS if a != "list")

DESCRIPTION = (
    "Read and write the comments people pin to one of Rouh's HTML pages in the browser (a visual "
    "explainer, a step's or task's page), the same comments they see and leave there. "
    "action 'list' gives every thread on the page, oldest first: its number, open or resolved, "
    "what it is pinned to (the element and its words, and whether that is still on the page), and "
    "each message with its number, author, time and words; give `person` to keep to one person's "
    "threads ('Nikola'). 'add' starts a new thread with `body`, pinned to the element that holds "
    "`on`, a short passage quoted exactly from the page (or '#some-id'); leave `on` out to comment "
    "on the page as a whole. 'reply' adds `body` at the end of thread `thread`. 'edit' changes the "
    "words of message `message` to `body`: only Rouh's own messages can be changed. 'delete' takes "
    "away message `message` (the first message of a thread takes the whole thread), or the whole "
    "thread `thread`. 'resolve' and 'reopen' mark thread `thread` done or open again. What Rouh "
    "writes shows on the page as Rouh's, never as a person's, and nobody is tagged or emailed. "
    "`page` is the page's path in the workspace, a step's or task's number or folder (its "
    "index.html), or Rouh's own address for it.")

SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": list(ACTIONS),
                   "description": "What to do. 'list' when left out."},
        "page": {"type": "string",
                 "description": "The page: its workspace path, a step or task number such as "
                                "'148-03', its folder, or Rouh's address for it."},
        "on": {"type": "string",
               "description": "For 'add': a passage quoted exactly from the page, or '#id' of an "
                              "element, to pin the comment to. Leave out for the whole page."},
        "body": {"type": "string", "description": "For 'add', 'reply' and 'edit': the words."},
        "thread": {"type": "integer", "description": "The thread's number, from 'list'."},
        "message": {"type": "integer", "description": "The message's number, from 'list'."},
        "person": {"type": "string",
                   "description": "For 'list': only threads this person wrote in (a name)."},
        "resolved": {"type": "boolean",
                     "description": "For 'list': include resolved threads. True when left out."},
    },
    "required": ["page"],
}


class Refused(ValueError):
    """What could not be done, in a sentence for the model."""


# --- which page ------------------------------------------------------------------------------


def _index_of(root: Path, folder: str) -> str:
    folder = folder.strip("/")
    if (root / folder).is_dir():
        return f"{folder}/index.html" if folder else "index.html"
    return folder


def _from_address(path: str, query: dict) -> str:
    """The workspace path one of Rouh's own addresses for a page names, or ''."""
    from . import addressing, objectindex, pages

    doc = unquote((query.get("doc") or [""])[0]).strip("/")
    path = unquote(path)
    if path.startswith(pages.ROUTE):
        rest = path[len(pages.ROUTE):].strip("/")
        prefix = objectindex.TASK_PREFIX.strip("/")
        if rest.startswith(prefix):
            folder = rest[len(prefix):].strip("/")
            return f"{folder}/{doc}" if doc else folder
        return rest
    for kind in ("task", "project"):
        if not path.startswith(f"/{kind}/"):
            continue
        name = path[len(kind) + 2:].strip("/")
        row = addressing.at(kind, name)
        if row is not None:
            folder = (getattr(row, "folder", "") or "").strip("/")
            return f"{folder}/{doc}" if doc else folder
        inside = addressing.inside(kind, name)
        if inside is not None:
            _each, row, rest = inside
            folder = (getattr(row, "folder", "") or "").strip("/")
            return f"{folder}/{rest}".strip("/")
    return ""


def _numbered(root: Path, said: str) -> str:
    """The folder of task `148`, or of its step `148-03`: the task by its number, as the
    workspace knows it, and the step as the folder inside it named after that number."""
    from . import objects

    task, _, step = said.partition("-")
    store = objects.shared_store(even_when_off=True)
    row = None
    try:
        row = store.numbered_task(int(task)) if store is not None else None
    except Exception:  # noqa: BLE001 - said as not found
        log.exception("could not look up task %s", task)
    folder = (getattr(row, "folder", "") or "").strip("/") if row is not None else ""
    if not folder or not (root / folder).is_dir():
        raise Refused(f"There is no task {task} in the workspace.")
    if not step:
        return folder
    want = f"{task}-{step}"
    for name in sorted(os.listdir(root / folder)):
        if (name == want or name.startswith(want + ".")) and (root / folder / name).is_dir():
            return f"{folder}/{name}"
    raise Refused(f"Task {task} has no step {want}.")


def page_of(root, said: str) -> str:
    """The workspace path of the HTML page `said` names, checked as the drawer checks one."""
    from . import addressing, askai

    root = Path(root or "")
    said = " ".join(str(said or "").split())
    if not said or not str(root) or not root.is_dir():
        raise Refused("Say which page: its path in the workspace, a step's number, or its address.")
    rel = ""
    if "://" in said or said.startswith("/"):
        parts = urlsplit(said if "://" in said else "http://x" + said)
        rel = _from_address(parts.path, parse_qs(parts.query))
        if not rel and not said.startswith("/"):
            raise Refused(f"{said} is not an address of one of Rouh's pages.")
        if not rel:
            rel = said.strip("/")
    elif re.fullmatch(r"\d{1,5}(?:-\d{1,3})?", said):
        rel = _numbered(root, said)
    else:
        rel = said
        if not (root / rel.strip("/")).exists():
            row = addressing.at("task", rel.strip("/"))
            if row is not None and getattr(row, "folder", ""):
                rel = row.folder
    rel = _index_of(root, rel.strip("/"))
    try:
        askai.resolve(root, rel)
    except askai.Unavailable as exc:
        raise Refused(f"{rel}: {exc}") from None
    return rel


# --- the page's elements, as a browser builds them -----------------------------------------------

#: What JavaScript's \s is, so words are cut where the page cuts them (`words` in comments.js).
_JS_SPACE = re.compile("[\t\n\v\f\r    -     　﻿]+")
_VOID = frozenset("area base br col embed hr img input link meta param source track wbr".split())
#: Tags whose start closes an open <p>, as a browser's parser does.
_CLOSES_P = frozenset(
    "address article aside blockquote details dialog div dl fieldset figcaption figure footer "
    "form h1 h2 h3 h4 h5 h6 header hgroup hr main menu nav ol p pre section table ul".split())
#: Tags whose start closes an open one of the same family.
_SIBLINGS = {"li": {"li"}, "dt": {"dt", "dd"}, "dd": {"dt", "dd"}, "tr": {"tr", "td", "th"},
             "td": {"td", "th"}, "th": {"td", "th"}, "option": {"option"}}
_HEAD = frozenset("head title meta link base style script noscript template".split())
#: Elements nobody pins a comment to, and whose words are not what a reader sees.
_UNSEEN = frozenset("script style template noscript head title".split())


def words(text) -> str:
    return _JS_SPACE.sub(" ", str(text or "")).strip()


def hash_of(text: str) -> str:
    """The page's fingerprint of some words (`hashOf` in comments.js): djb2 with xor, over the
    words' UTF-16 code units, as an unsigned 32-bit number in base 36."""
    h = 5381
    data = str(text or "").encode("utf-16-le", "surrogatepass")
    for i in range(0, len(data), 2):
        h = ((h * 33) & 0xFFFFFFFF) ^ (data[i] | (data[i + 1] << 8))
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    out = ""
    while True:
        h, r = divmod(h, 36)
        out = digits[r] + out
        if not h:
            return out


class _El:
    __slots__ = ("tag", "attrs", "kids", "parent", "bits")

    def __init__(self, tag: str, attrs: dict, parent):
        self.tag, self.attrs, self.kids, self.parent, self.bits = tag, attrs, [], parent, []

    def text(self) -> str:
        """`textContent`: every word under it, scripts and styles too, as a browser has it."""
        out: list[str] = []

        def walk(el):
            for bit in el.bits:
                out.append(bit if isinstance(bit, str) else "")
                if not isinstance(bit, str):
                    walk(bit)

        walk(self)
        return "".join(out)


class _Tree(HTMLParser):
    """The page's <body>, built as a browser would build it from the file, closely enough to
    name an element the way comments.js names it."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.body = _El("body", {}, None)
        self.head = _El("head", {}, None)
        self.stack: list[_El] = []
        self.in_head = False
        self.seen_body = False

    def _top(self) -> _El:
        return self.stack[-1] if self.stack else (self.head if self.in_head else self.body)

    def _close_to(self, tag: str) -> None:
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return

    def _open(self, family: set, stop: set) -> bool:
        for el in reversed(self.stack):
            if el.tag in family:
                return True
            if el.tag in stop:
                return False
        return False

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag == "html":
            return
        if tag == "head":
            self.in_head = True
            return
        if tag == "body":
            self.in_head, self.seen_body, self.stack = False, True, []
            for k, v in attrs:
                self.body.attrs.setdefault(k, v or "")
            return
        if self.in_head and tag not in _HEAD:
            self.in_head, self.stack = False, []
        if tag in _CLOSES_P and self._open({"p"}, {"div", "section", "article", "td", "th", "li",
                                                    "blockquote", "table"}):
            self._close_to("p")
        if tag in _SIBLINGS:
            stop = {"ul", "ol", "dl", "table", "tbody", "thead", "tfoot", "select"} - {tag}
            for el in reversed(self.stack):
                if el.tag in stop:
                    break
                if el.tag in _SIBLINGS[tag]:
                    self._close_to(el.tag)
                    break
        if tag == "tr" and self._top().tag == "table":
            self._push("tbody", {})
        self._push(tag, dict((k, v or "") for k, v in attrs))
        if tag in _VOID:
            self.stack.pop()

    def _push(self, tag, attrs):
        parent = self._top()
        el = _El(tag, attrs, parent)
        parent.kids.append(el)
        parent.bits.append(el)
        self.stack.append(el)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag.lower() not in _VOID and self.stack and self.stack[-1].tag == tag.lower():
            self.stack.pop()

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "head":
            self.in_head, self.stack = False, []
            return
        if tag in ("body", "html"):
            return
        self._close_to(tag)

    def handle_data(self, data):
        if not self.stack and not self.in_head and not data.strip() and not self.seen_body:
            return
        self._top().bits.append(data)


def _ours(el: _El) -> bool:
    if el.attrs.get("id", "").startswith("askai-"):
        return True
    cls = el.attrs.get("class", "").split()
    return "askai-hl" in cls or "askai-mk" in cls


def _path(el: _El) -> str:
    parts = []
    while el.parent is not None:
        same = [k for k in el.parent.kids if k.tag == el.tag and not _ours(k)]
        parts.insert(0, f"{el.tag}:{same.index(el) + 1 if el in same else 1}")
        el = el.parent
    return "/".join(parts)


def _elements(el: _El):
    for kid in el.kids:
        if kid.tag in _UNSEEN:
            continue
        yield kid
        yield from _elements(kid)


def read_page(root, rel: str) -> _El:
    """The page's <body> as a tree of elements."""
    tree = _Tree()
    tree.feed((Path(root) / rel).read_text("utf-8", "replace"))
    tree.close()
    return tree.body


def _cls(el: _El) -> str:
    return " ".join(c for c in words(el.attrs.get("class", "")).split(" ")
                    if c and not c.startswith("askai-"))


def _sig(el: _El) -> str:
    a = el.attrs
    return hash_of(f"{el.tag}|{_cls(el)}|{a.get('src', '')[:4000]}|{a.get('alt', '')}|"
                   f"{a.get('href', '')}")


def describe(el: _El, quote: str = "") -> dict:
    """An element as the page describes the one a comment is pinned to (`describe` in
    comments.js), but for where a press landed, which nobody made: the top right of it."""
    text = words(el.text())
    label = text or el.attrs.get("alt", "") or el.attrs.get("aria-label", "") or \
        el.attrs.get("title", "")
    label = label if len(label) <= 120 else label[:119] + "…"
    return {"path": _path(el) if el.parent is not None else "", "tag": el.tag,
            "id": el.attrs.get("id", ""), "cls": _cls(el)[:200], "text": text[:300],
            "hash": hash_of(text), "sig": _sig(el), "label": label,
            "fx": 0.98, "fy": 0.0, "x": 0, "y": 0, "w": 1, "pfx": -1, "pfy": -1,
            "quote": quote}


def anchor_for(body: _El, on: str) -> dict:
    """Where a new comment is pinned: the smallest element that holds the passage `on`, or the
    element with that `#id`, or the page as a whole when `on` is empty."""
    said = words(on)
    if not said:
        return describe(body)
    if said.startswith("#") and " " not in said:
        for el in _elements(body):
            if el.attrs.get("id") == said[1:]:
                return describe(el)
        raise Refused(f"Nothing on the page has the id {said[1:]}.")
    best, best_len = None, None
    for exact in (True, False):
        want = said if exact else said.lower()
        for el in _elements(body):
            text = words(el.text())
            if want in (text if exact else text.lower()):
                if best_len is None or len(text) <= best_len:
                    best, best_len = el, len(text)
        if best is not None:
            break
    if best is None:
        raise Refused(f"These words are not on the page: \"{said[:160]}\". Quote a short "
                      "passage exactly as the page has it, or give '#id' of an element.")
    return describe(best, said[:300])


def still_there(body: _El, anchor: dict) -> bool | None:
    """Whether the element a thread is pinned to is still in the page's file, by its words; None
    when that cannot be told (the page as a whole)."""
    if not anchor or (anchor.get("tag") or "body") == "body":
        return None
    want, tag = anchor.get("hash") or "", anchor.get("tag")
    quote = words(anchor.get("quote") or "")
    for el in _elements(body):
        if el.tag != tag:
            continue
        text = words(el.text())
        if (want and hash_of(text) == want) or (quote and quote in text):
            return True
    return False


# --- who, and where -----------------------------------------------------------------------------


def _owner():
    from .tenancy import GUEST_ORG, Tenancy, speaker

    who = speaker() or Tenancy().only_person()
    if who is None or getattr(who, "org_id", "") == GUEST_ORG:
        raise Refused("Only the owner of the pages can work with their comments here.")
    return who


def _place(root, rel: str, who) -> comments.Place:
    from . import pageplaces, pages

    pageplaces.follow()
    return comments.Place(org_id=who.org_id, owner_id=str(who.user_id), rel=rel,
                          title=pages.title_of(Path(root) / rel))


def _rouh() -> comments.Person:
    from . import protected

    unattended = False
    try:
        unattended = bool(protected.UNATTENDED.get())
    except LookupError:
        pass
    return comments.agent_person(comments.AGENT_JOB_NAME if unattended else comments.AGENT_NAME)


# --- saying it ---------------------------------------------------------------------------------


def _when(at) -> str:
    from . import clock

    try:
        return f"{clock.clock(at)}, {clock.ago(at)}"
    except Exception:  # noqa: BLE001 - a time is never worth failing a reading
        return ""


def _on(anchor: dict, there) -> str:
    tag = anchor.get("tag") or "body"
    if tag == "body" and not anchor.get("path"):
        return "the page as a whole"
    said = anchor.get("quote") or anchor.get("label") or anchor.get("text") or ""
    said = said if len(said) <= 200 else said[:199] + "…"
    name = f"<{tag}" + (f" id={anchor['id']}" if anchor.get("id") else "") + ">"
    where = f"{name} \"{said}\"" if said else name
    if there is False:
        where += " (not found in the page as it is now: the element was changed or removed)"
    return where


def said(place: comments.Place, threads: list[dict], body, *, person: str = "",
         resolved: bool = True) -> str:
    """Every thread, as Rouh reads it."""
    from .comments_by import matches

    shown = []
    for t in threads:
        if not resolved and t["resolved"]:
            continue
        if person and not any(matches(person, m["author"]["name"]) for m in t["messages"]):
            continue
        shown.append(t)
    head = f"Comments on {place.title or place.rel} ({place.rel})"
    if not threads:
        return head + ": none. Nobody has commented on this page."
    if not shown:
        return head + f": {len(threads)} threads, none of them " + \
            (f"with a message from {person}." if person else "open.")
    open_n = sum(1 for t in shown if not t["resolved"])
    lines = [head + f": {len(shown)} threads shown, {open_n} open, oldest first."]
    for t in shown:
        state = (f"resolved by {t['resolved_by'] or 'somebody'} {_when(t['resolved_at'])}"
                 if t["resolved"] else "open")
        there = still_there(body, t["anchor"]) if body is not None else None
        lines.append(f"\nThread {t['id']} [{state}] on {_on(t['anchor'], there)}")
        for m in t["messages"]:
            who = m["author"]["name"]
            if m["author"].get("ai") and not m["author"].get("agent"):
                who += " (Ask AI)"
            lines.append(f"  Message {m['id']}, {who}, {_when(m['created_at'])}"
                         + (" (edited)" if m["edited"] else "") + ":")
            lines.extend("    " + line for line in (m["body"] or "").splitlines() or [""])
    return "\n".join(lines)


# --- the tool -----------------------------------------------------------------------------------


def _number(args: dict, key: str) -> int:
    try:
        value = int(args.get(key))
    except (TypeError, ValueError):
        raise Refused(f"Give `{key}`, the number 'list' shows for it.") from None
    if value <= 0:
        raise Refused(f"Give `{key}`, the number 'list' shows for it.")
    return value


def act(root, args: dict) -> str:
    """One action on one page's comments, said in words. Raises Refused or comments.Refused."""
    action = str(args.get("action") or "list").strip().lower()
    if action not in ACTIONS:
        raise Refused(f"There is no action {action!r}: it is one of {', '.join(ACTIONS)}.")
    who = _owner()
    rel = page_of(root, str(args.get("page") or ""))
    place = _place(root, rel, who)
    rouh = _rouh()
    if action == "list":
        try:
            body = read_page(root, rel)
        except OSError:
            body = None
        threads = comments.threads(place, rouh)
        return said(place, threads, body, person=" ".join(str(args.get("person") or "").split()),
                    resolved=args.get("resolved") is not False)
    if action == "add":
        anchor = anchor_for(read_page(root, rel), str(args.get("on") or ""))
        thread, _ = comments.start(place, rouh, anchor, "", args.get("body"), [])
        log.info("page_comments: %s started thread %s on %s", rouh.name, thread["id"], rel)
        return (f"Started thread {thread['id']} on {place.rel}, pinned to "
                f"{_on(anchor, True)}, as {rouh.name}. Its message is {thread['messages'][0]['id']}. "
                "It shows on the page at its next load.")
    if action == "reply":
        message, done = comments.reply(place, rouh, _number(args, "thread"), args.get("body"), [])
        return f"Answered thread {done['thread']} as {rouh.name}: message {message['id']}."
    if action == "edit":
        number = _number(args, "message")
        message, done = comments.edit(place, rouh, number, args.get("body"), [])
        return f"Changed message {message['id']} in thread {done['thread']}."
    if action == "delete":
        if args.get("message") not in (None, "", 0):
            gone = comments.remove_message(place, rouh, _number(args, "message"))
        else:
            gone = comments.remove_thread(place, rouh, _number(args, "thread"))
        log.info("page_comments: %s took away a %s on %s", rouh.name, gone["removed"], rel)
        if gone["removed"] == "thread":
            return f"Took away thread {gone['thread']} on {place.rel}, with every message in it."
        return f"Took away message {gone['message']} from thread {gone['thread']}."
    done = comments.resolve(place, rouh, _number(args, "thread"), action == "resolve")
    return (f"Thread {done['thread']} is " + ("resolved" if done["resolved"] else "open again")
            + f", by {rouh.name}.")


async def answer(root, args: dict):
    """The tool's answer. What people wrote is boxed as theirs; what Rouh did is its own words."""
    from . import untrusted

    args = args if isinstance(args, dict) else {}
    try:
        text = await asyncio.to_thread(act, root, args)
    except (Refused, comments.Refused) as exc:
        return untrusted.ours(str(exc))
    if str(args.get("action") or "list").strip().lower() == "list":
        return text
    return untrusted.ours(text)


def workspace_root(cfg) -> str:
    root = getattr(cfg, "assistant_repo", "") or ""
    return root if root and os.path.isdir(root) else ""


__all__ = ["ACTIONS", "DESCRIPTION", "SCHEMA", "TOOL_NAME", "WRITES", "act", "anchor_for",
           "answer", "hash_of", "page_of", "read_page", "said", "still_there"]
