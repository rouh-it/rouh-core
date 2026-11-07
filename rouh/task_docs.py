"""The task's documents: the Google Docs a task's notes link to, on its page, each with What
changed, read in place.

Built by the nightly feature run, night 20, 23 October 2026 (task 94, idea I-120). A client's
documents live in Google Docs, and ‹his› work tasks keep their links in their notes: one task of
‹his› links fifteen. Before a meeting with that client on 22 October 2026 ‹he› pasted three of
those documents into a chat to be checked for changes, two of them links the task's notes had held
for days. The task knew its documents; its page never showed them, so finding them and asking
about them was ‹his› to do, link by link.

So, while its switch is on, a task's page (and a step's) has a section **Documents**, last, after
the work (lesson L14): every Google Doc, Sheet or Slides deck linked in the `.md` files of its
folder, named as the notes name it, each linked to the document. **What changed** on a line reads
the document's saved versions and comments in Drive (`rouh/doc_changes.py`) since ‹he› last opened
this page, or over the last week, and shows the answer right under the line, in place. Nothing is
read from Drive until it is pressed.

**Whose.** The task's own files, and the documents the connected Google account can open; only a
document linked in this task's notes is read for its page.

**Its switch** is `task_docs` (`rouh/switches.py`): off, the section is not there.
"""
from __future__ import annotations

import html
import logging
import re
import threading
import time
from pathlib import Path

log = logging.getLogger("rouh.task_docs")

SWITCH = "task_docs"
#: The most documents listed, and the most notes files read to find them.
MOST = 20
MOST_FILES = 300
MOST_BYTES = 2_000_000

_LINK = re.compile(r"https://docs\.google\.com/(document|spreadsheets|presentation)/d/"
                   r"([A-Za-z0-9_-]{5,})[^\s)\]>\"']*")
_MD_LINK = re.compile(r"\[([^\]\n]{2,160})\]\((https://docs\.google\.com/[^)\s]+)\)")
#: A document named in quotes in the notes near its link: Google Doc "Northwind Launch Prioritization".
_QUOTED = re.compile(r"[\"\u201c]([^\"\u201c\u201d\n]{3,120})[\"\u201d]")
#: The person's own setting: the documents' names as Drive gives them, by id.
NAMES = "task_docs_names"
KINDS = {"document": "Google Doc", "spreadsheets": "Google Sheet", "presentation": "Google Slides"}


def on(org_id=None) -> bool:
    from . import switches

    return switches.on(SWITCH, org_id or None)


def _name(words: str) -> str:
    words = re.sub(r"[*_`]+", "", " ".join(str(words or "").split())).strip()
    if words.lower().startswith("http") or len(words) < 2:
        return ""
    return words


def linked(root, rel: str) -> list[dict]:
    """The Google documents linked in the .md files under a task's folder, newest mention first."""
    base = Path(root) / rel
    if not rel or not base.is_dir():
        return []
    files = []
    for path in base.rglob("*.md"):
        if any(p.startswith(".") or p in ("temp", "node_modules") for p in path.relative_to(base).parts):
            continue
        try:
            files.append((path.stat().st_mtime, path))
        except OSError:
            continue
        if len(files) >= MOST_FILES:
            break
    files.sort(reverse=True)
    found: dict[str, dict] = {}
    for when, path in files:
        try:
            if path.stat().st_size > MOST_BYTES:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        named = {}
        for words, url in _MD_LINK.findall(text):
            got = _LINK.match(url)
            if got:
                named.setdefault(got.group(2), _name(words))
        for got in _LINK.finditer(text):
            kind, doc = got.group(1), got.group(2)
            if not named.get(doc):
                # Named in quotes on its own line or the two before it.
                near = _QUOTED.findall("\n".join(text[:got.start()].split("\n")[-3:]))
                if near:
                    named[doc] = _name(near[-1])
            one = found.get(doc)
            if one is None:
                found[doc] = {"id": doc, "kind": KINDS[kind], "url": got.group(0).rstrip(".,;:"),
                              "title": named.get(doc, ""), "at": when}
            elif not one["title"] and named.get(doc):
                one["title"] = named[doc]
    out = sorted(found.values(), key=lambda one: one["at"], reverse=True)[:MOST]
    return out


def section(person, root, rel: str) -> str:
    """The Documents section of a task's page; "" when off, nobody is signed in, or none is linked.

    What changed is drawn hidden and shown by `taskpage.js` where Rouh is around the page to hand
    the press to. While this gene is off and Attach to a meeting is on (`rouh/meeting_attach.py`),
    the section is still drawn, its lines with only the document and Attach to a meeting, because
    that is the one place a task's documents are listed."""
    from . import doc_on_page, meeting_attach, rehearse

    if person is None or not rel:
        return ""
    try:
        org = getattr(person, "org_id", None)
        listing = on(org)
        if not listing and not meeting_attach.on(org):
            return ""
        docs = linked(root, rel)
        known = kept_names(person)
    except Exception:  # noqa: BLE001 - the page is drawn without it
        log.exception("the documents linked under %s could not be read", rel)
        return ""
    adding = listing and doc_add_on(person) and not _is_step(rel)
    if not docs and not adding:
        return ""
    rows = []
    for one in docs:
        drive = known.get(one["id"], "")
        title = drive or one["title"] or one["kind"]
        rows.append(
            f'<div class="odoc" data-doc="{html.escape(one["id"], quote=True)}"'
            f'{"" if drive else " data-unnamed"}>'
            f'<p class="odoc-line"><a class="odoc-name" href="{html.escape(one["url"], quote=True)}" '
            f'target="_blank" rel="noopener">{html.escape(title)}</a>'
            f'<span class="odoc-kind">{html.escape(one["kind"])}</span>'
            + ('<button type="button" class="obtn odoc-what" hidden>What changed</button>'
               + doc_on_page.button(person, one) + rehearse.button(person, one) if listing else '')
            + f'{meeting_attach.button(person, one)}</p>'
            f'<div class="odoc-said" hidden></div></div>')
    many = len(docs)
    # Add a document (night 23, switch `doc_add`): a link pasted here is kept in the task's notes.
    # Not a <form>: the page is drawn in a sandboxed frame, which may not submit one.
    form = ('<div class="odoc-add" hidden><input class="odoc-add-link" type="url" '
            'inputmode="url" autocomplete="off" aria-label="A Google Doc, Sheet or Slides link" '
            'placeholder="Paste a Google Doc, Sheet or Slides link">'
            '<button type="button" class="obtn odoc-add-go">Add</button>'
            '<p class="odoc-add-said" role="status" hidden></p></div>') if adding else ""
    count = f'<span class="c">{many}</span>' if many else ""
    return (f'<section class="oset odocs" id="tkDocs" aria-label="Documents"><h2 class="divider">'
            f'Documents{count}</h2><div class="rows">{"".join(rows)}</div>{form}'
            f'</section>')


# --- A link kept in the task's notes -------------------------------------------------------
# Used by Add a document under the section (switch `doc_add`, `rouh/web/task_docs.py`) and by
# Shared with you in the morning brief (switch `shared_with_you`, `rouh/shared_with_you.py`).

#: The heading the links go under, at the end of the task's AGENTS.md.
ADDED_HEADING = "## Documents added"
DOC_ADD = "doc_add"
_write_lock = threading.Lock()


def doc_add_on(who) -> bool:
    from . import switches

    return who is not None and switches.on(DOC_ADD, getattr(who, "org_id", None) or None)


def _is_step(rel: str) -> bool:
    from . import steps

    return steps.is_step(rel)


def link_of(text: str) -> dict | None:
    """The first Google Doc, Sheet or Slides link in what was pasted: {id, kind, url}, or None."""
    got = _LINK.search(str(text or ""))
    if not got:
        return None
    return {"id": got.group(2), "kind": KINDS[got.group(1)],
            "url": f"https://docs.google.com/{got.group(1)}/d/{got.group(2)}/edit"}


def notes_of(root, rel: str) -> Path | None:
    """The AGENTS.md of the task a folder is, or None when it is not a task with notes."""
    from . import steps

    task = steps.task_part(rel)
    parts = [p for p in task.split("/") if p]
    if not parts or not steps._TASK_NAME.match(parts[-1]):
        return None
    path = Path(root) / task / "AGENTS.md"
    return path if path.is_file() else None


def holding(root, doc_id: str, rels) -> str:
    """Which of these task folders already link or name this document, the first one, or ""."""
    for rel in rels:
        base = Path(root) / rel
        if not base.is_dir():
            continue
        for path in base.rglob("*.md"):
            try:
                if path.stat().st_size <= MOST_BYTES and doc_id in path.read_text(
                        encoding="utf-8", errors="replace"):
                    return rel
            except OSError:
                continue
    return ""


def _one_line(text, most: int = 200) -> str:
    text = " ".join(str(text or "").split()).replace("[", "(").replace("]", ")")
    # A task's AGENTS.md is read for its open question by these words (`rouh/waiting.py`).
    text = re.sub(r"(?i)\bwaiting on\b", "waiting for", text)
    return text if len(text) <= most else text[:most - 1].rstrip() + "…"


def add_link(root, rel: str, link: dict, title: str, note: str) -> dict:
    """Keep a document's link in the task's notes, under `ADDED_HEADING`.

    ``{"ok", "added", "line", "task"}``; `added` is False when the task already links or names it.
    Raises ValueError with a sentence when the folder is not a task with notes."""
    from datetime import datetime

    from . import clock, saving, steps

    path = notes_of(root, rel)
    if path is None:
        raise ValueError("That is not a task with notes, so there is nowhere to keep the link.")
    task = steps.task_part(rel)
    if holding(root, link["id"], [task]):
        return {"ok": True, "added": False, "line": "", "task": task}
    try:
        zone = clock.zone()
    except Exception:  # noqa: BLE001 - the server's own zone is a fair second
        zone = None
    at = datetime.fromtimestamp(time.time(), zone)
    name = _one_line(title, 160) or link["kind"]
    line = f"- [{name}]({link['url']}): {_one_line(note, 240)}; kept here on {at.day} {at:%B %Y}."
    with _write_lock:
        text = path.read_text(encoding="utf-8")
        if ADDED_HEADING in text:
            at_ = text.index(ADDED_HEADING) + len(ADDED_HEADING)
            rest = text[at_:]
            nxt = re.search(r"\n## ", rest)
            end = at_ + (nxt.start() if nxt else len(rest.rstrip("\n")))
            after = text[end:].lstrip("\n")
            text = text[:end].rstrip("\n") + "\n" + line + "\n" + ("\n" + after if after else "")
        else:
            text = (text.rstrip("\n") + "\n\n" + ADDED_HEADING + "\n\n"
                    "Google documents kept for this task by Rouh, as the owner asked, newest last."
                    "\n\n" + line + "\n")
        _write(path, text)
    saving.poke()
    return {"ok": True, "added": True, "line": line, "task": task}


def take_link(root, rel: str, line: str) -> bool:
    """Undo: the very line `add_link` wrote taken out of the task's notes again."""
    from . import saving

    path = notes_of(root, rel)
    if path is None or not line:
        return False
    with _write_lock:
        text = path.read_text(encoding="utf-8")
        if line + "\n" not in text:
            return False
        text = text.replace(line + "\n", "", 1)
        empty = ADDED_HEADING + "\n\nGoogle documents kept for this task by Rouh, as the owner asked, newest last.\n\n"
        if text.rstrip("\n").endswith(empty.rstrip("\n")):
            text = text.rstrip("\n")[: -len(empty.rstrip("\n"))].rstrip("\n") + "\n"
        _write(path, text)
    saving.poke()
    return True


def _write(path: Path, text: str) -> None:
    import os

    was = path.stat()
    spare = path.with_name(f".{path.name}.{os.getpid()}.rouh-doc")
    try:
        with open(spare, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        os.chmod(spare, was.st_mode & 0o7777)
        try:
            os.chown(spare, was.st_uid, was.st_gid)
        except OSError:
            pass
        os.replace(spare, path)
    finally:
        if spare.exists():
            spare.unlink()


async def add(who, google, root, folder: str, pasted: str) -> dict:
    """Add a document: the link pasted under a task's Documents, kept in its notes, named by Drive."""
    from asgiref.sync import sync_to_async

    from . import evolution

    if not await sync_to_async(on)(getattr(who, "org_id", None)) or not await sync_to_async(doc_add_on)(who):
        return {"ok": False, "error": "Adding documents here is switched off."}
    if _is_step(folder):
        return {"ok": False, "error": "Documents are added on the task's own page."}
    link = link_of(pasted)
    if link is None:
        return {"ok": False, "error": "That is not a link to a Google Doc, Sheet or Slides deck."}
    title, readable = "", False
    if google is not None:
        try:
            title = str((await google(who).drive.metadata(link["id"])).get("name") or "")
            readable = True
        except Exception as exc:  # noqa: BLE001 - kept all the same, and said
            log.info("the document %s could not be opened to be named: %r", link["id"], exc)
    note = "added on the task's page" + ("" if readable else
                                         ", not yet open to Rouh's Google account")
    try:
        done = await sync_to_async(add_link)(root, folder, link, title, note)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    if not done["added"]:
        return {"ok": False, "error": "This task's notes already link that document."}
    # The documents the tasks link, and the new comments on them, are each kept a quarter of an
    # hour; the one just added is read the next time, not after that.
    from . import comments_in_docs, new_comments

    comments_in_docs.forget()
    new_comments.forget()
    if title:
        await sync_to_async(_keep_names)(who, {link["id"]: title})
    await sync_to_async(evolution.used)(DOC_ADD, "added", who=who,
                                        detail=f"added a {link['kind']} on a task's page")
    return {"ok": True, "doc": {**link, "title": title or link["kind"]}, "readable": readable}


def kept_names(who) -> dict[str, str]:
    """The documents' names as Drive last gave them, kept for the person."""
    import json

    from .models import UserSetting

    value = (UserSetting.objects.filter(user_id=str(who.user_id), org_id=who.org_id or "", name=NAMES)
             .values_list("value", flat=True).first())
    try:
        held = json.loads(value) if value else {}
    except (TypeError, ValueError):
        held = {}
    return {str(k): str(v) for k, v in held.items()} if isinstance(held, dict) else {}


def _keep_names(who, got: dict[str, str]) -> None:
    import json

    from .models import UserSetting

    held = kept_names(who)
    held.update(got)
    UserSetting.objects.bulk_create(
        [UserSetting(user_id=str(who.user_id), org_id=who.org_id or "", name=NAMES,
                     value=json.dumps(held), updated_at=time.time())],
        update_conflicts=True, unique_fields=["user_id", "name"],
        update_fields=["org_id", "value", "updated_at"])


async def names(who, google, root, folder: str) -> dict:
    """Every linked document's own name, from Drive, kept for the next time the page is drawn."""
    import asyncio

    from asgiref.sync import sync_to_async

    if not await sync_to_async(on)(getattr(who, "org_id", None)):
        return {"ok": False, "error": "The task's documents are switched off."}
    if google is None:
        return {"ok": False, "error": "Google is not set up here."}
    docs = await sync_to_async(linked)(root, folder)
    try:
        drive = google(who).drive
    except Exception as exc:  # noqa: BLE001 - not connected: the notes' names stay
        log.info("no Drive to name a task's documents with: %r", exc)
        return {"ok": False, "error": "Google is not connected."}

    async def one(doc: dict) -> tuple[str, str]:
        try:
            return doc["id"], str((await drive.metadata(doc["id"])).get("name") or "")
        except Exception as exc:  # noqa: BLE001 - one it cannot open keeps the notes' name
            log.info("the name of %s could not be read: %r", doc["id"], exc)
            return doc["id"], ""

    got = {k: v for k, v in await asyncio.gather(*(one(d) for d in docs)) if v}
    if got:
        await sync_to_async(_keep_names)(who, got)
    return {"ok": True, "names": got}


def _since(who, folder: str) -> str:
    """When the person last opened this page before now, as a moment, or "" for the last week."""
    from datetime import datetime, timezone

    try:
        from . import since_read

        now = time.time()
        last = since_read.last_read(since_read.opens(who, folder, now=now), now)
    except Exception:  # noqa: BLE001 - a week is the answer without it
        log.exception("when %s was last opened could not be read", folder)
        last = None
    return datetime.fromtimestamp(last, timezone.utc).isoformat() if last else ""


async def changes(who, google, root, folder: str, doc: str) -> dict:
    """What changed in one document this task links to, since the person last opened the page."""
    from asgiref.sync import sync_to_async

    from . import doc_changes, evolution

    if not await sync_to_async(on)(getattr(who, "org_id", None)):
        return {"ok": False, "error": "The task's documents are switched off."}
    docs = await sync_to_async(linked)(root, folder)
    one = next((d for d in docs if d["id"] == doc), None)
    if one is None:
        return {"ok": False, "error": "That document is not linked in this task's notes."}
    if google is None:
        return {"ok": False, "error": "Google is not set up here, so nothing can be read."}
    since = await sync_to_async(_since)(who, folder)
    try:
        said = await doc_changes.read(google(who), one["url"], since)
    except Exception as exc:  # noqa: BLE001 - said on the page
        log.info("what changed in %s could not be read: %r", doc, exc)
        return {"ok": False, "error": "It could not be read from Drive. Try again."}
    await sync_to_async(evolution.used)(SWITCH, "what_changed", who=who,
                                        detail=f"what changed in a {one['kind']} on a task's page")
    return {"ok": True, "text": said, "since": since}


__all__ = ["ADDED_HEADING", "DOC_ADD", "SWITCH", "add", "add_link", "changes", "doc_add_on", "holding",
           "kept_names", "link_of", "linked", "names", "notes_of", "on", "section", "take_link"]
