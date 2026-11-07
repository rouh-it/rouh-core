"""Rouh offline: the copy each device keeps, and the one outbox on the server.

Petar, 12 October 2026, on card 1457 ("Rouh offline, on laptop and phone", version 2), "Do it":
he is sometimes on his laptop and sometimes on his phone, and wants Rouh to keep working with
him when there is no internet. This is phase one of that plan, the part Rouh recommended first:

- **The offline pack.** While a device is online it keeps a copy of what he would need, made
  here in parts (`PARTS`) and fetched one part at a time, so a part that fails costs that part
  and nothing else. Petar said what it holds, 12 October 2026, and it is the same on the laptop
  and the phone: the calendar a month either side of today, thirty days of both inboxes, every
  chat of the last two weeks whole with all its forks, every task the Control Room ranks above
  its quiet edge whole (and every pinned one), the decisions, and the contacts. A device short
  of room leaves out the last kinds first, in his order (app/offline.js). What is in it is read
  through the code that already reads it for the page and the tools: the task rows and their
  notes (`steps`), the Control Room's own score (`controlroom.room`), the decisions
  (`decisions.listing`), the calendar and both inboxes (`google_api` over Rouh's own connection
  and the person's read-only mailboxes, `inboxes`), the contacts (`synapse.contacts`) and the
  chats with their cards (`artifacts`). Clockwork, the goals and the quests are kept as their
  own pages read them, by the device itself.

- **The one outbox.** What he does offline on either device - answers a decision, writes a
  reply or a new email, edits a task's notes, makes a reminder or a task, records a note for
  Rouh, changes something on Clockwork, a goal or a quest, sends feedback - is kept on the device
  with an id of its own, the device it came from, when, and the version of what it acted on, and
  is sent here when the device reconnects (`take`). Each is a row of `OfflineAction` under that
  id, so it is carried out exactly once, whichever device sends it first and however many times.
  Every rule that holds online holds here, because each is carried out through the path that
  does it online: a decision through the decisions' answer path with his exact words
  (`decision_desk.Desk.act`), a reminder through Clockwork's, a task through `owning.new_task`,
  a note as his own message in General, a change on Clockwork, a goal or a quest through the
  very view the page posts to (`CLOCK_ROUTES`), and feedback through the board's own store, with
  the time it was written.

- **What moved meanwhile becomes a decision.** An action whose subject changed since he acted
  on it - a newer email in the thread, a decision already answered or asked differently, a
  page edited by a job - is not carried out over the newer version. It becomes a decision of
  the source `offline` (`decision_sources.OfflineSource`) showing both versions, and is carried
  out, or not, the way he answers it. A page edited on both sides is merged first
  (`offline_merge`), and only where the two edits really meet does it come to him.

- **Nothing irreversible goes without its confirmation.** A reply becomes a draft in Rouh's
  own mailbox (the person's mailboxes are read only). It is sent only when he pressed Send
  and confirmed it on the device, the same press and confirmation the compose card asks for
  online, and only when the current rules allow that send: not a trusted contact's open case
  (`mail_cases.holds_reply`), and nothing newer in the thread. Anything else stays a draft,
  with a decision to send it that asks the confirmation a send needs. A decision whose answer
  spends money, sends, publishes or cannot be undone needs the same `confirm` it needs online,
  or it is held as a decision asking for it.

Every result is pushed to every open tab of the person (`offline_results` on the socket), so
something approved on the phone shows as done on the laptop, and each device reads the results
of both when it reconnects (`results`).

Later phases - models on the device, handing off between devices over Bluetooth or Wi-Fi,
satellite and messaging-only channels, the Gmail-to-Synapse mirror - plug in here: an action
is a kind and a payload, whoever carries it, and the pack is parts, wherever they come from.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import contextvars
import hashlib
import json
import logging
import os
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from django.db import IntegrityError, transaction

from . import fileutil

log = logging.getLogger("rouh.offline")

#: What a device may have done offline, each carried out by its own function below. `clock`
#: is a change on Clockwork, a goal or a quest, sent through the very view that makes it online
#: (`CLOCK_ROUTES`); `feedback` is the Gene therapy drawer's Send (the kind kept its old name, because it is stored).
KINDS = ("decision", "reply", "draft", "page", "reminder", "task", "note", "clock", "feedback")
#: What became of one: received and running on the way, then done, clash (a decision now),
#: held (waiting on a confirmation, as a decision), failed (said why), or dropped (he said so).
STATUSES = ("received", "running", "done", "clash", "held", "failed", "dropped")
#: Waiting on him, as a decision of the source `offline`.
ASKING = ("clash", "held")
#: The parts of the pack this server makes, each fetched on its own. Clockwork, the goals and
#: the quests are not among them: the device keeps what their own pages read
#: (`/api/reminders`, `/api/goals`, `/api/quests`), through the service worker, so the copy is
#: the page's own answer and nothing here can drift from it (app/offline.js, `KINDS`).
PARTS = ("calendar", "decisions", "tasks", "chats", "mail", "contacts")

#: How long an action id may be, and how much one device may send at once.
MAX_ID = 80
MAX_BATCH = 50
#: A voice note's sound, as base64 of a WAV: about three minutes of 16 kHz speech.
MAX_AUDIO_B64 = 8 * 1024 * 1024
#: A page's text, either side.
MAX_PAGE = 600_000
#: Notes the pack carries whole; a longer one is cut, and says so.
MAX_NOTE = 120_000

# What the copy holds. Petar, 12 October 2026: "Calendar - 30 days back and forward. Emails - 30
# days. Chats - Rouh - 2 weeks back and all its forks. Tasks - all tasks in control room that have
# been selected above status 'quiet'. Full content of - clockwork, quests, and goals, task browser
# mechanics with the airplane." The same on the laptop and the phone; a device short of room
# leaves out the last of them first, in the order app/offline.js keeps (`KINDS` there).

#: The calendar, this many days either side of today, every calendar Rouh shows.
CALENDAR_DAYS = 30
#: How many days one read of the calendar asks for, so Google's page of 250 is never the edge.
CALENDAR_STEP = 5
#: Mail, this many days back, both inboxes, headers and bodies.
MAIL_DAYS = 30
#: How many days of mail one request of the pack carries: six requests for the thirty days, so
#: none of them runs into the proxy's minute.
MAIL_PAGE_DAYS = 5
#: The most of one inbox one page carries, and the most of one body.
MAIL_PAGE_MOST = 1500
MAIL_BODY_MOST = 200_000
#: Chats with something said in them this many days back, whole, with all their forks.
CHAT_DAYS = 14
#: How many chats one request of the pack carries, and the most chats it looks through, newest
#: first, for the ones of the last two weeks.
CHATS_PAGE = 25
CHATS_LISTED = 5000
#: The most of one chat, of one message and of one chat's cards: far past any real one, a
#: guard against a runaway rather than a cut.
CHAT_MESSAGES_MOST = 20_000
CHAT_TEXT_MOST = 100_000
CHAT_CARDS_MOST = 2_000
#: A page step's words, for reading and searching on the Offline page.
PAGE_WORDS_MOST = 30_000


def version_of(text: str) -> str:
    """The version of a note: its text, hashed, as Ask AI names a page's (`askai.page_version`)."""
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]


def _root() -> Path:
    from .config import config

    return Path(config.assistant_repo).resolve()


# --- the pack ------------------------------------------------------------------------------


def pack_tasks(who) -> dict:
    """Every task's row; the whole of every task the Control Room ranks above quiet.

    Every task is listed with its name, its status and its project, so the task browser and
    the Offline page can say what is there with no connection. The ones the device keeps whole
    are the tasks of every cluster the Control Room draws larger than its quiet edge
    (`controlroom.room`, its own score, read afresh every time the copy is made), and every
    pinned task whatever its cluster. Whole is the task's notes (its AGENTS.md first), every
    step with its own notes and its page's words, and what the device reads to open each of
    them on the canvas (`pages`, the built pages of the task and its steps), whose pictures and
    styles come inside each page (`pages.with_files`).

    A note carries the version it was read at, which is what an edit made offline names as
    what it started from.
    """
    from . import pinning, steps

    root = _root()
    rows = steps.index_rows(root)
    pinned_numbers = {str(p.get("number") or "") for p in pinning.listing()}
    active, why = _ranked(who)
    projects = _project_names()
    tasks = []
    for row in rows:
        number = row.get("number")
        rel = row["rel"]
        is_pinned = str(number) in pinned_numbers
        ranked = active.get(rel)
        one = {"rel": rel, "number": number, "name": row.get("name") or "",
               "status": row.get("status") or "", "said": row.get("said") or "",
               "steps": row.get("steps") or 0, "changed": row.get("changed"),
               "project": _project_of(rel, projects),
               "pinned": is_pinned, "whole": False,
               "cluster": (ranked or {}).get("cluster", ""), "size": (ranked or {}).get("size", "")}
        if ranked or is_pinned:
            try:
                one.update(_task_whole(root, rel))
                one["whole"] = True
            except Exception:  # noqa: BLE001 - one unreadable task is that task, not the copy
                log.exception("offline: task %s could not be read whole", rel)
        tasks.append(one)
    return {"tasks": tasks, "pinned": sorted(n for n in pinned_numbers if n),
            "whole": sum(1 for t in tasks if t["whole"]), "why": why}


def _ranked(who) -> tuple[dict[str, dict], str]:
    """The tasks of every Control Room cluster above its quiet edge, by folder.

    Read with `remember=False`: the copy being made is not him looking at the room, so it moves
    neither "since you last looked" nor a card's size."""
    from urllib.parse import unquote

    from . import controlroom

    try:
        got = controlroom.room(who, remember=False)
    except Exception as exc:  # noqa: BLE001 - the pinned tasks still come
        log.exception("offline: the Control Room could not be read")
        return {}, f"The Control Room could not be read, so only pinned tasks are whole: {exc}"
    out: dict[str, dict] = {}
    for cluster in got.get("clusters") or []:
        size = str(cluster.get("size") or "")
        if size in ("", "quiet"):
            continue
        for task in cluster.get("tasks") or []:
            href = str(task.get("href") or "")
            if href.startswith("/task/"):
                out.setdefault(unquote(href[len("/task/"):]).strip("/"),
                               {"cluster": str(cluster.get("name") or ""), "size": size})
    return out, ""


def _project_names() -> dict[str, str]:
    """Every project's name, by its folder."""
    from . import objects

    store = objects.shared_store(even_when_off=True)
    if store is None:
        return {}
    try:
        return {row["folder"]: row.get("title") or "" for row in store.objects()
                if row["type"] == "project" and row.get("folder")}
    except Exception:  # noqa: BLE001 - a task without its project's name is still a task
        log.exception("offline: the projects could not be read")
        return {}


def _project_of(rel: str, names: dict[str, str]) -> str:
    """The project a task is filed in: the nearest folder above it that is a project."""
    parts = rel.split("/")[:-1]
    while parts:
        folder = "/".join(parts)
        if names.get(folder):
            return names[folder]
        parts.pop()
    above = rel.split("/")[:-1]
    return above[-1].replace("-", " ").capitalize() if above else ""


def _task_whole(root: Path, rel: str) -> dict:
    """One task's notes and steps, as the device keeps them, and the pages it opens."""
    from . import steps

    detail = steps.task_detail(root, rel)
    folder = root / detail["rel"]
    notes = [_note_of(root, path) for path in _notes_in(folder)]
    shown = []
    for step in detail.get("steps") or []:
        item = {"rel": step.get("rel"), "title": step.get("title") or step.get("folder") or "",
                "number": step.get("number"), "state": step.get("state") or "",
                "kind": step.get("kind") or ""}
        step_folder = root / (step.get("rel") or "")
        md = step_folder / steps.STEP_FILE
        if md.is_file():
            item["note"] = _note_of(root, md)
        elif step.get("kind") == "page":
            page = step_folder / "index.html"
            if page.is_file():
                item["words"] = _page_words(page.read_text(encoding="utf-8", errors="replace"),
                                            PAGE_WORDS_MOST)
        for extra in _notes_in(step_folder, first=False):
            item.setdefault("notes", []).append(_note_of(root, extra))
        shown.append(item)
    try:
        built = [p["rel"] for p in steps.pages_in(root, detail["rel"]).get("pages") or []]
    except Exception:  # noqa: BLE001 - its notes are still worth keeping
        built = []
    return {"notes": notes, "step_list": shown, "pages": built}


def _notes_in(folder: Path, first: bool = True) -> list[Path]:
    """The `.md` files a task or step folder keeps, AGENTS.md first; never a generated list."""
    if not folder.is_dir():
        return []
    found = sorted(p for p in folder.iterdir()
                   if p.is_file() and p.suffix.lower() == ".md" and not p.name.startswith((".", "_"))
                   and p.name != "step.md")
    found.sort(key=lambda p: (p.name != "AGENTS.md", p.name.lower()))
    return found if first else [p for p in found if p.name != "AGENTS.md"]


def _note_of(root: Path, path: Path) -> dict:
    text = path.read_text(encoding="utf-8", errors="replace")
    cut = len(text) > MAX_NOTE
    from . import saving

    rel = str(path.relative_to(root)).replace(os.sep, "/")
    return {"path": rel, "name": path.name, "text": text[:MAX_NOTE], "version": version_of(text),
            "cut": cut, "editable": not cut and saving._kept_in_place(rel)}


_TAGS = re.compile(r"<(script|style)[^>]*>.*?</\1>|<[^>]+>", re.DOTALL | re.IGNORECASE)
_BLOCK_END = re.compile(r"</(p|div|h[1-6]|li|tr|section|article|br)\s*>|<br\s*/?>", re.IGNORECASE)


def _page_words(html: str, most: int = 30_000) -> str:
    """A page's words, for reading with no connection: tags out, paragraphs kept."""
    import html as html_lib

    text = _BLOCK_END.sub("\n", html)
    text = _TAGS.sub(" ", text)
    text = html_lib.unescape(text)
    text = re.sub(r"[ \t ]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
    return text[:most]


def pack_decisions(who) -> dict:
    """Everything waiting on him, as the Decisions page has it, without the history."""
    from . import decisions

    got = decisions.listing(who, history=False)
    return {k: got.get(k) for k in ("open", "snoozed", "going", "arranged", "counts", "sources")}


async def pack_calendar(who) -> dict:
    """Every event from 30 days before today to 30 days after, on every calendar he shows.

    Read a few days at a time, each read asking every calendar at once (`Calendar.events`), so
    a busy calendar is never cut at Google's page of 250. An event he declined is kept and
    says so: it is on his calendar, and the copy is the calendar as it is."""
    from . import clock, runtime
    from .google_api import MAX_EVENTS_LISTED
    from .tenancy import speaking

    if runtime.brief_google is None:
        return {"events": [], "why": "Google is not connected on this Rouh."}
    with speaking(who), clock.person(who):
        zone = clock.zone()
        today = datetime.now(zone).replace(hour=0, minute=0, second=0, microsecond=0)
        start = today - timedelta(days=CALENDAR_DAYS)
        end = today + timedelta(days=CALENDAR_DAYS + 1)
        services = await asyncio.to_thread(runtime.brief_google, who)
        if services is None:
            return {"events": [], "why": "Google is not connected for this account yet."}
        windows = []
        at = start
        while at < end:
            windows.append((at, min(end, at + timedelta(days=CALENDAR_STEP))))
            at += timedelta(days=CALENDAR_STEP)
        gate = asyncio.Semaphore(3)

        async def window(a, b):
            async with gate:
                return await services.calendar.events(a, b, limit=MAX_EVENTS_LISTED)

        answers = await asyncio.gather(*(window(a, b) for a, b in windows), return_exceptions=True)
    events: list[dict] = []
    seen: set[tuple] = set()
    trouble: list[str] = []
    for answer in answers:
        if isinstance(answer, BaseException):
            trouble.append(str(answer))
            continue
        trouble.extend(str(t) for t in answer.get("trouble") or [])
        if answer.get("cut"):
            trouble.append(f"{answer['cut']} events of a very busy few days were left out.")
        for e in answer.get("events") or []:
            one = _event(e)
            key = (one["calendar_id"], one["id"], one["start"])
            if key in seen:
                continue
            seen.add(key)
            events.append(one)
    events.sort(key=lambda e: (e["starts_at"], e["title"].lower()))
    return {"events": events, "zone": str(zone), "days": CALENDAR_DAYS,
            "from": start.timestamp(), "to": end.timestamp(),
            "trouble": list(dict.fromkeys(trouble))[:8]}


def _moment(value) -> tuple[str, float]:
    """An event's start or end as text the device reads and as epoch seconds."""
    if isinstance(value, datetime):
        return value.isoformat(), value.timestamp()
    if isinstance(value, date):
        return value.isoformat(), datetime(value.year, value.month, value.day).timestamp()
    return str(value or ""), 0.0


def _event(e: dict) -> dict:
    """One event, whole: everything its own card on the brief would say."""
    start, starts_at = _moment(e.get("start"))
    end, ends_at = _moment(e.get("end"))
    return {"id": e.get("id") or "", "calendar": e.get("calendar") or "",
            "calendar_id": e.get("calendar_id") or "", "title": e.get("title") or "",
            "start": start, "end": end, "starts_at": starts_at, "ends_at": ends_at,
            "all_day": bool(e.get("all_day")), "zone": e.get("zone") or "",
            "where": e.get("where") or "", "description": (e.get("description") or "")[:20_000],
            "organiser": e.get("organiser") or "", "organiser_name": e.get("organiser_name") or "",
            "mine": bool(e.get("mine")),
            "guests": [{"email": g.get("email") or "", "name": g.get("name") or "",
                        "response": g.get("response") or "", "organiser": bool(g.get("organiser")),
                        "optional": bool(g.get("optional"))}
                       for g in (e.get("guests") or [])[:200] if not g.get("resource")],
            "guests_omitted": bool(e.get("guests_omitted")),
            "my_response": e.get("my_response") or "",
            "declined": e.get("my_response") == "declined",
            "video": e.get("video") or "", "link": e.get("link") or "",
            "series": bool(e.get("series")), "status": e.get("status") or "",
            "busy": e.get("busy") is not False, "kind": e.get("kind") or ""}


def pack_contacts(who) -> dict:
    """Every contact of his, for writing to somebody with no connection."""
    from .synapse import contacts

    cards = contacts.all_cards(str(who.user_id), who.org_id)
    out = []
    for card in cards:
        out.append({"id": card.get("id"), "name": card.get("name") or "",
                    "organisation": card.get("organisation") or "",
                    "emails": [e.get("address") for e in card.get("emails") or [] if e.get("address")],
                    "phones": [p.get("number") for p in card.get("phones") or [] if p.get("number")],
                    "note": (card.get("note") or "")[:600]})
    return {"contacts": out}


def mail_pages() -> int:
    return -(-MAIL_DAYS // MAIL_PAGE_DAYS)


async def pack_mail(who, page: int = 0) -> dict:
    """Five of the last thirty days of both inboxes, Rouh's own and his: headers and bodies.

    `page` 0 is the newest five days, and `mail_pages()` of them make the thirty. Every email of
    those days is read whole (`Gmail.message`), with the same readers the mail tools use, so his
    own mailboxes are read and never written. The files on an email are named, as they always
    were. The same email held in two of the mailboxes is kept once.
    """
    from . import inboxes, meeting_prep, runtime

    now = time.time()
    newest = now - page * MAIL_PAGE_DAYS * 86400
    oldest = max(now - MAIL_DAYS * 86400, newest - MAIL_PAGE_DAYS * 86400)
    query = f"after:{int(oldest)}" + (f" before:{int(newest)}" if page else "")
    readers: list[tuple[str, str, object]] = []
    with contextlib.suppress(Exception):
        for address, gmail in await asyncio.to_thread(meeting_prep._mailboxes, who):
            readers.append((address, inboxes.PERSON, gmail))
    rouh_address = ""
    if runtime.brief_google is not None:
        services = await asyncio.to_thread(runtime.brief_google, who)
        if services is not None:
            rouh_address = await asyncio.to_thread(inboxes.rouh_address, who) or "Rouh"
            readers.append((rouh_address, inboxes.ROUH, services.gmail))
    base = {"page": page, "pages": mail_pages(), "days": MAIL_DAYS, "from": oldest, "to": newest,
            "rouh": rouh_address, "inboxes": [a for a, _, _ in readers]}
    if not readers:
        return {**base, "messages": [], "why": "No mailbox is connected yet."}
    gate = asyncio.Semaphore(8)

    async def whole(gmail, ident: str) -> dict | None:
        async with gate:
            try:
                return await gmail.message(ident)
            except Exception:  # noqa: BLE001 - one unreadable email is not the pack's failure
                return None

    messages: list[dict] = []
    seen: set[tuple] = set()
    trouble = []
    for address, whose, gmail in readers:
        ids: list[str] = []
        token = ""
        try:
            while len(ids) < MAIL_PAGE_MOST:
                got, token = await gmail.listing(query=query, page_token=token,
                                                 spam_and_trash=False, size=500)
                ids.extend(got)
                if not token:
                    break
        except Exception as exc:  # noqa: BLE001
            trouble.append(f"{address}: {exc}")
            continue
        if len(ids) > MAIL_PAGE_MOST:
            trouble.append(f"{address}: only the newest {MAIL_PAGE_MOST} of {len(ids)} emails of these days.")
            ids = ids[:MAIL_PAGE_MOST]
        fulls = await asyncio.gather(*(whole(gmail, one) for one in ids))
        for ident, full in zip(ids, fulls):
            if not full:
                continue
            labels = full.get("labels") or []
            if "DRAFT" in labels:
                continue
            same = (str(full.get("subject") or "").strip().lower(), int((full.get("at") or 0) // 60),
                    str(full.get("from") or "").lower())
            if same in seen:
                continue
            seen.add(same)
            body = str(full.get("body") or "")
            messages.append({
                "id": full.get("id") or ident, "thread_id": full.get("thread_id") or "",
                "inbox": address, "whose": whose, "from": full.get("from") or "",
                "to": full.get("to") or "", "cc": full.get("cc") or "",
                "reply_to": full.get("reply_to") or "",
                "subject": full.get("subject") or "", "date": full.get("date") or "",
                "at": full.get("at") or 0, "snippet": re.sub(r"\s+", " ", body[:400]).strip()[:200],
                "unread": bool(full.get("unread")), "sent": "SENT" in labels,
                "body": body[:MAIL_BODY_MOST], "cut": len(body) > MAIL_BODY_MOST,
                "files": [a.get("name") or a.get("filename") or "" for a in full.get("attachments") or []],
                "can_reply": whose == inboxes.ROUH,
            })
    messages.sort(key=lambda m: -(m.get("at") or 0))
    return {**base, "messages": messages, "trouble": trouble[:5]}


def _chat_ids(now: float) -> list[tuple[str, dict]]:
    """Every chat with something said in it in the last two weeks, each followed by every fork
    off it, however deep and however old, as (id, what the list says of it)."""
    from . import conversations
    from .models.objects import ChatFork

    since = now - CHAT_DAYS * 86400
    roots = [row for row in conversations.all_chats(limit=CHATS_LISTED)
             if float(row.get("updated_at") or 0) >= since]
    forks = list(ChatFork.objects.values("chat_id", "parent_id", "at", "created_at"))
    under: dict[str, list[dict]] = {}
    for f in sorted(forks, key=lambda f: float(f.get("created_at") or 0)):
        under.setdefault(f["parent_id"], []).append(f)
    out: list[tuple[str, dict]] = []
    seen: set[str] = set()

    def walk(chat_id: str, row: dict, depth: int) -> None:
        if chat_id in seen or depth > 32:
            return
        seen.add(chat_id)
        out.append((chat_id, row))
        for f in under.get(chat_id, []):
            walk(f["chat_id"], {"fork_of": chat_id, "fork_at": f.get("at"), "depth": depth + 1},
                 depth + 1)

    for row in roots:
        walk(row["id"], dict(row, depth=0), 0)
    return out


def pack_chats(who, page: int = 0) -> dict:
    """One page of the chats used in the last two weeks: each whole, with its cards, and its forks.

    A fork is kept whatever its age, under the chat it came off, with the message of that chat
    it came off after (`fork_at`), which is how the Offline page shows what it carried."""
    from . import artifacts, conversations, runtime

    from .memory import CONVERSATION as general

    now = time.time()
    every = _chat_ids(now)
    parents = {row.get("fork_of") for _c, row in every if row.get("fork_of")}
    pages = max(1, -(-len(every) // CHATS_PAGE))
    out = []
    for chat_id, listed in every[page * CHATS_PAGE:(page + 1) * CHATS_PAGE]:
        row = listed if listed.get("title") else (conversations.chat(chat_id) or {})
        said = []
        with contextlib.suppress(Exception):
            for msg in runtime.memory.transcript(chat_id, CHAT_MESSAGES_MOST):
                text = str(msg.get("text") or "")
                files = [str(a.get("name") or "") for a in msg.get("attachments") or []
                         if isinstance(a, dict)]
                tools = [str(t.get("name") or "") for part in msg.get("parts") or []
                         if isinstance(part, dict) for t in part.get("tools") or [] if isinstance(t, dict)]
                if not text and not files and not tools:
                    continue
                said.append({"id": msg.get("id"), "ts": msg.get("ts"), "role": msg.get("role"),
                             "text": text[:CHAT_TEXT_MOST], "files": files, "tools": tools[:40]})
        cards = []
        with contextlib.suppress(Exception):
            task_rel = runtime.memory.task_of(chat_id)
            for card in artifacts.history(chat_id, task_rel, None, CHAT_CARDS_MOST):
                cards.append({k: card.get(k) for k in ("card_id", "title", "description", "blocks",
                                                       "at", "after_message_id")})
        # A chat with nothing in it, and nothing hanging off it, is not worth a line.
        if not said and not cards and not listed.get("fork_of") and chat_id not in parents:
            continue
        title = row.get("title") or ""
        if chat_id == general:
            # The thread that is always there is General, whatever its own title says.
            title = "General" + (f" · {title}" if row.get("titled") else "")
        out.append({"id": chat_id, "title": title, "task": row.get("task") or "",
                    "number": row.get("number"), "updated": row.get("updated_at") or 0,
                    "fork_of": listed.get("fork_of") or "", "fork_at": listed.get("fork_at"),
                    "depth": listed.get("depth") or 0, "messages": said, "cards": cards})
    return {"chats": out, "page": page, "pages": pages, "count": len(every), "days": CHAT_DAYS,
            "from": now - CHAT_DAYS * 86400, "to": now}


async def pack_part(who, part: str, page: int = 0) -> dict:
    """One part of the pack (one page of it, for mail and chats), and when it was made."""
    if part == "tasks":
        got = await asyncio.to_thread(pack_tasks, who)
    elif part == "decisions":
        got = await asyncio.to_thread(pack_decisions, who)
    elif part == "calendar":
        got = await pack_calendar(who)
    elif part == "contacts":
        got = await asyncio.to_thread(pack_contacts, who)
    elif part == "mail":
        got = await pack_mail(who, max(0, min(int(page or 0), mail_pages() - 1)))
    elif part == "chats":
        got = await asyncio.to_thread(pack_chats, who, max(0, int(page or 0)))
    else:
        raise ValueError(f"No part of the pack is called {part}.")
    return {"part": part, "made_at": time.time(), **got}


# --- the one outbox -------------------------------------------------------------------------


class Refused(Exception):
    """An action that is not one, said in a sentence the device shows."""


def _whose(who) -> dict:
    return {"user_id": str(who.user_id), "org_id": str(who.org_id)}


def as_dict(row) -> dict:
    """One action as the devices read it."""
    return {"id": row.action_id, "kind": row.kind, "status": row.status, "result": row.result,
            "device": row.device_name, "device_kind": row.device_kind, "made_at": row.made_at,
            "received_at": row.received_at, "done_at": row.done_at, "updated_at": row.updated_at,
            "outcome": {k: v for k, v in (row.outcome or {}).items()
                        if k in ("decision", "draft_id", "thread_id", "task", "reminder", "chat",
                                 "merged", "sent", "path", "version", "feedback", "route")},
            "label": label_of(row.kind, row.payload or {})}


def label_of(kind: str, payload: dict) -> str:
    """What one action was, in a few words."""
    if kind == "decision":
        return f"Answer: {payload.get('said') or payload.get('question') or 'a decision'}"[:140]
    if kind == "reply":
        return f"Reply: {payload.get('subject') or ''}"[:140]
    if kind == "draft":
        return f"New email: {payload.get('subject') or ''}"[:140]
    if kind == "page":
        return f"Edit: {payload.get('where') or payload.get('path') or ''}"[:140]
    if kind == "reminder":
        return f"Reminder: {payload.get('title') or payload.get('what') or ''}"[:140]
    if kind == "task":
        return f"New task: {payload.get('title') or ''}"[:140]
    if kind == "note":
        return "Voice note" if payload.get("audio") else f"Note: {payload.get('text') or ''}"[:140]
    if kind == "clock":
        return str(payload.get("label") or "A change on Clockwork, a goal or a quest")[:140]
    if kind == "feedback":
        return f"Gene therapy: {payload.get('body') or ''}"[:140]
    return kind


def results(who, since: float = 0.0, limit: int = 200) -> list[dict]:
    """Every action of his that moved since `since`, from both devices, newest first."""
    from .models import OfflineAction

    rows = (OfflineAction.objects.filter(**_whose(who), updated_at__gt=float(since or 0))
            .order_by("-updated_at")[:limit])
    return [as_dict(r) for r in rows]


def _check(action: dict) -> tuple[str, str, dict, dict, float]:
    ident = str(action.get("id") or "").strip()
    if not ident or len(ident) > MAX_ID or not re.fullmatch(r"[A-Za-z0-9_.:-]+", ident):
        raise Refused("An action came with no usable id.")
    kind = str(action.get("kind") or "")
    if kind not in KINDS:
        raise Refused(f"{kind or 'That'} is not something that can be done offline.")
    payload = action.get("payload") if isinstance(action.get("payload"), dict) else {}
    base = action.get("base") if isinstance(action.get("base"), dict) else {}
    try:
        made = float(action.get("made_at") or 0) / (1000.0 if float(action.get("made_at") or 0) > 1e11 else 1.0)
    except (TypeError, ValueError):
        made = 0.0
    return ident, kind, payload, base, made or time.time()


def _claim(who, device: dict, ident: str, kind: str, payload: dict, base: dict, made: float):
    """The row for this action, and whether this call is the one that carries it out."""
    from .models import OfflineAction

    now = time.time()
    try:
        with transaction.atomic():
            row = OfflineAction.objects.create(
                **_whose(who), action_id=ident, kind=kind, payload=payload, base=base,
                device_id=str(device.get("id") or "")[:80], device_name=str(device.get("name") or "")[:120],
                device_kind=str(device.get("kind") or "")[:20], made_at=made, received_at=now,
                status="running", updated_at=now)
        return row, True
    except IntegrityError:
        return OfflineAction.objects.get(**_whose(who), action_id=ident), False


def _finish(row, status: str, result: str, **outcome) -> None:
    now = time.time()
    row.status = status
    row.result = result
    row.outcome = {**(row.outcome or {}), **outcome}
    row.updated_at = now
    if status in ("done", "dropped", "failed"):
        row.done_at = now
    row.save(update_fields=["status", "result", "outcome", "updated_at", "done_at"])


#: The signed-in account an outbox call came with, for the kinds carried out through a view
#: (`_clock`), which asks who is signed in as every view does.
SIGNED_IN: contextvars.ContextVar = contextvars.ContextVar("rouh_offline_signed_in", default=None)


async def take(who, device: dict, actions: list, user=None) -> list[dict]:
    """Carry out what one device did offline, each once, in the order it was done.

    `user` is the account the outbox call was signed in with, which a change carried out through
    its own view is made as (`_clock`)."""
    token = SIGNED_IN.set(user)
    try:
        return await _take(who, device, actions)
    finally:
        SIGNED_IN.reset(token)


async def _take(who, device: dict, actions: list) -> list[dict]:
    out = []
    asked = False
    actions = sorted((a for a in actions[:MAX_BATCH] if isinstance(a, dict)),
                     key=lambda a: float(a.get("made_at") or 0))
    for action in actions:
        try:
            ident, kind, payload, base, made = _check(action)
        except Refused as exc:
            out.append({"id": str(action.get("id") or ""), "status": "failed", "result": str(exc)})
            continue
        row, mine = await asyncio.to_thread(_claim, who, device, ident, kind, payload, base, made)
        if mine:
            try:
                await CARRY[kind](who, row)
            except Refused as exc:
                await asyncio.to_thread(_finish, row, "failed", str(exc))
            except Exception as exc:  # noqa: BLE001 - one action failing says so; the rest go on
                log.exception("offline action %s (%s) failed", ident, kind)
                await asyncio.to_thread(_finish, row, "failed", f"It could not be carried out: {exc}")
            asked = asked or row.status in ASKING
        out.append(as_dict(row))
    if asked:
        await _ask_again(who)
    await push(who, out)
    return out


async def push(who, rows: list[dict]) -> None:
    """Tell every open tab of his what became of these, the other device's included."""
    if not rows:
        return
    from . import runtime

    with contextlib.suppress(Exception):
        await runtime._decisions_push(who, {"type": "offline_results", "results": rows})


async def _ask_again(who) -> None:
    """Bring the clashes onto the decisions list now, rather than at the next sync."""
    from . import runtime

    with contextlib.suppress(Exception):
        await runtime.desk.sync(who, kinds={"offline"})


# --- carrying each kind out ----------------------------------------------------------------


async def _decision(who, row) -> None:
    """An answer to a decision, through the answer path, with his exact words.

    Carried out only if the decision is still the one he answered: still waiting, with the
    same question and the same answers to choose from. Answered meanwhile the same way, it
    is done; answered differently, or asked differently, it is a clash and becomes a decision.
    """
    from . import decisions, runtime

    p = row.payload or {}
    base = row.base or {}
    ident = int(p.get("decision") or 0)
    now = await asyncio.to_thread(decisions.get, who, ident)
    if now is None:
        raise Refused("That decision is not there any more.")
    choice = [str(c) for c in p.get("choice") or [] if c]
    text = str(p.get("text") or "")
    if now["status"] in (decisions.ANSWERED, decisions.APPLYING, decisions.APPLIED):
        had = now.get("answer") or {}
        if list(had.get("choice") or []) == choice and str(had.get("text") or "") == text:
            await asyncio.to_thread(_finish, row, "done", "Answered the same way already.",
                                    decision=ident)
            return
        await asyncio.to_thread(
            _finish, row, "clash",
            f"It was answered meanwhile{_by(now)}: {str(had.get('said') or 'answered').rstrip('.')}.",
            decision=ident, reason="answered", theirs=str(had.get("said") or ""),
            mine=str(p.get("said") or text or ", ".join(choice)), question=now.get("question") or "")
        return
    if now["status"] not in decisions.ANSWERABLE:
        await asyncio.to_thread(
            _finish, row, "clash", f"It is {now['status']} now, so your answer was not given.",
            decision=ident, reason=now["status"], mine=str(p.get("said") or text or ", ".join(choice)),
            theirs="", question=now.get("question") or "")
        return
    ids_now = [o.get("id") for o in now.get("options") or []]
    asked_then = str(base.get("question") or "")
    ids_then = list(base.get("options") or [])
    if (asked_then and asked_then != now.get("question")) or (ids_then and ids_then != ids_now):
        await asyncio.to_thread(
            _finish, row, "clash", "It was asked differently by the time you answered.",
            decision=ident, reason="changed", mine=str(p.get("said") or text or ", ".join(choice)),
            theirs=str(now.get("question") or ""), question_then=asked_then,
            question=now.get("question") or "")
        return
    body = {"choice": choice, "text": text}
    if p.get("items"):
        body["items"] = p["items"]
    if p.get("confirm"):
        body["confirm"] = str(p["confirm"])
    try:
        got = await runtime.desk.act(who, ident, "answer", body, channel="offline")
    except decisions.NeedsConfirm as exc:
        await asyncio.to_thread(_finish, row, "held",
                                f"{exc.note or exc} This needs your confirmation before it goes.",
                                decision=ident, reason="confirm", risk=exc.risk,
                                mine=str(p.get("said") or text or ", ".join(choice)),
                                question=now.get("question") or "")
        return
    except decisions.Refused as exc:
        raise Refused(str(exc)) from None
    await asyncio.to_thread(_finish, row, "done", _answered(got), decision=ident)


def _answered(got: dict) -> str:
    """What became of an answer from the outbox, without the undo the page offers: it was
    given offline, and there is nothing on the device to undo it with."""
    said = str(((got.get("decision") or {}).get("answer") or {}).get("said") or "").strip().rstrip(".")
    return f"Answered: {said}." if said else "Answered."


def _by(d: dict) -> str:
    where = d.get("channel") or ""
    return f" on {where}" if where and where not in ("screen", "offline") else ""


async def _reader(who, whose: str, inbox: str):
    """The Gmail an action reads its thread through, and whether it may write there."""
    from . import inboxes, meeting_prep, runtime

    if whose == inboxes.PERSON:
        for address, gmail in await asyncio.to_thread(meeting_prep._mailboxes, who):
            if address.lower() == (inbox or "").lower():
                return gmail, False
        return None, False
    if runtime.brief_google is None:
        return None, True
    services = await asyncio.to_thread(runtime.brief_google, who)
    return (services.gmail if services is not None else None), True


async def _thread_last(gmail, thread_id: str) -> dict | None:
    """The newest email in a thread that is not a draft, read as the stand-ins and Gmail answer."""
    if not thread_id or gmail is None:
        return None
    whole = await gmail._clients.call(gmail._who, "GET", gmail._url(f"/threads/{thread_id}"),
                                      params={"format": "minimal"})
    found = [m for m in (whole or {}).get("messages") or [] if "DRAFT" not in (m.get("labelIds") or [])]
    if not found:
        return None
    last = found[-1]
    with contextlib.suppress(Exception):
        return {**await gmail.headers(last["id"]), "id": last["id"]}
    return {"id": last.get("id")}


async def _rouh_gmail(who):
    from . import runtime

    if runtime.brief_google is None:
        raise Refused("Rouh's own mailbox is not connected, so nothing could be drafted.")
    services = await asyncio.to_thread(runtime.brief_google, who)
    if services is None:
        raise Refused("Rouh's own mailbox is not connected for this account.")
    return services.gmail


async def _reply(who, row) -> None:
    """A reply written offline: a draft in Rouh's mailbox, sent only as the rules allow.

    A newer email in the thread since he wrote it makes it a clash, shown with both. A reply
    to an email in one of his own mailboxes cannot go in that thread, which is read only, so
    it is drafted from Rouh's mailbox as a new email to the sender, and says so.
    """
    from . import inboxes, mail_cases

    p = row.payload or {}
    base = row.base or {}
    whose = str(p.get("whose") or inboxes.ROUH)
    reader, writable = await _reader(who, whose, str(p.get("inbox") or ""))
    newer = None
    with contextlib.suppress(Exception):
        last = await _thread_last(reader, str(p.get("thread_id") or ""))
        if last and base.get("last_id") and last.get("id") != base.get("last_id"):
            newer = last
    if newer is not None:
        await asyncio.to_thread(
            _finish, row, "clash",
            f"A newer email came in the thread from {newer.get('from') or 'somebody'} after you wrote this.",
            reason="newer_mail", mine=str(p.get("body") or ""),
            theirs=f"From {newer.get('from') or ''} - {newer.get('subject') or ''}\n\n"
                   f"{newer.get('snippet') or ''}",
            thread_id=str(p.get("thread_id") or ""))
        return
    gmail = await _rouh_gmail(who)
    to = str(p.get("to") or "")
    subject = str(p.get("subject") or "")
    reply_to = str(p.get("message_id") or "") if writable else ""
    made = await gmail.draft(to, subject, str(p.get("body") or ""), cc=str(p.get("cc") or ""),
                             reply_to_message_id=reply_to)
    draft_id = made.get("draft_id") or made.get("id") or ""
    where = ("in the thread" if reply_to else
             "as a new email from Rouh's mailbox, because your own mailbox here is read only")
    held = ""
    if p.get("send") and p.get("confirmed"):
        held = await asyncio.to_thread(mail_cases.holds_reply, str(who.user_id), str(who.org_id),
                                       str(p.get("message_id") or ""))
        if not held:
            await _send(who, gmail, row, made, draft_id, reply_to)
            return
    if p.get("send"):
        why = (held or "a send waits for its confirmation") if p.get("confirmed") or held \
            else "you did not confirm the send on the device"
        await asyncio.to_thread(
            _finish, row, "held", f"Saved as a draft {where}. Not sent: {why}.",
            reason="send", draft_id=draft_id, thread_id=made.get("thread_id") or "",
            to=made.get("to") or to, subject=made.get("subject") or subject,
            mine=str(p.get("body") or ""), refused=bool(held))
        return
    await asyncio.to_thread(_finish, row, "done", f"Saved as a draft {where}, to {made.get('to') or to}.",
                            draft_id=draft_id, thread_id=made.get("thread_id") or "")


async def _send(who, gmail, row, made: dict, draft_id: str, reply_to: str) -> None:
    from . import runtime
    from .tenancy import speaking

    p = row.payload or {}
    sent = await gmail.send_draft(draft_id, made.get("to") or str(p.get("to") or ""),
                                  made.get("subject") or str(p.get("subject") or ""),
                                  str(p.get("body") or ""), cc=str(p.get("cc") or ""),
                                  reply_to_message_id=reply_to)
    desk = getattr(runtime, "google_desk", None)
    if desk is not None:
        with speaking(who), contextlib.suppress(Exception):
            desk.wrote("send_mail", sent.get("to") or "", f"sent from the offline outbox: {sent.get('subject') or ''}")
    await asyncio.to_thread(_finish, row, "done", f"Sent to {sent.get('to') or ''}, as you asked offline.",
                            sent=True, thread_id=sent.get("thread_id") or "", draft_id=draft_id)


async def _draft(who, row) -> None:
    """A new email written offline: a draft in Rouh's mailbox, or sent as the rules allow."""
    p = row.payload or {}
    if not str(p.get("to") or "").strip():
        raise Refused("A new email needs somebody to go to.")
    gmail = await _rouh_gmail(who)
    made = await gmail.draft(str(p.get("to") or ""), str(p.get("subject") or ""), str(p.get("body") or ""),
                             cc=str(p.get("cc") or ""))
    draft_id = made.get("draft_id") or made.get("id") or ""
    if p.get("send") and p.get("confirmed"):
        await _send(who, gmail, row, made, draft_id, "")
        return
    if p.get("send"):
        await asyncio.to_thread(_finish, row, "held",
                                "Saved as a draft. Not sent: you did not confirm the send on the device.",
                                reason="send", draft_id=draft_id, to=made.get("to") or "",
                                subject=made.get("subject") or "", mine=str(p.get("body") or ""))
        return
    await asyncio.to_thread(_finish, row, "done", f"Saved as a draft to {made.get('to') or ''}.",
                            draft_id=draft_id, thread_id=made.get("thread_id") or "")


def _note_path(path: str) -> Path:
    """A task's note that may be written from the outbox: one that is there already, and that
    the workspace's saver keeps when it is changed in place (`saving._kept_in_place`), so the
    edit reaches main and outlives the next deploy."""
    from . import saving, workspace

    asked = str(path or "").strip()
    if not asked.lower().endswith(".md") or not saving._kept_in_place(asked):
        raise Refused("Only a task's own notes can be edited offline.")
    try:
        found = workspace.resolve(_root(), asked)
    except workspace.Refused as exc:
        raise Refused(str(exc)) from None
    if not found.is_file():
        raise Refused(f"{asked} is not there any more.")
    return found


def write_note(path: Path, text: str) -> None:
    """Write a note whole, with its owner kept, and have it saved to main (`rouh/saving.py`)."""
    from . import saving, steps

    fileutil.write_atomic(path, text, spare=path.with_name(f".{path.name}.{os.getpid()}.rouh-offline"),
                          newline="", keep_mode=True, keep_owner=True)
    with contextlib.suppress(Exception):
        steps.own_as_workspace(path, _root())
    saving.poke()


def _page(who, row) -> None:
    """A task's note edited offline, merged with what changed here meanwhile.

    Unchanged since the device read it: written. Changed, by a job or the other device: the
    two edits are merged line by line (`offline_merge`), and written if they do not meet.
    Where they meet it is a clash, with both versions, and nothing is written until he says.
    """
    from .offline_merge import merge

    p = row.payload or {}
    base = row.base or {}
    path = _note_path(str(p.get("path") or ""))
    mine = str(p.get("text") or "")
    if len(mine) > MAX_PAGE:
        raise Refused("That page is too long to send from the outbox.")
    now = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    if version_of(now) == str(base.get("version") or "") or now == mine:
        if now != mine:
            write_note(path, mine)
        _finish(row, "done", "Saved.", path=str(p.get("path")), version=version_of(mine))
        return
    got = merge(str(base.get("text") or ""), mine, now)
    if got.ok:
        write_note(path, got.text)
        _finish(row, "done", "Saved, merged with the changes made here since you went offline.",
                path=str(p.get("path")), version=version_of(got.text), merged=True)
        return
    _finish(row, "clash",
            f"It was changed here while you were offline, in the same place you changed it "
            f"({len(got.clashes)} place{'s' if len(got.clashes) != 1 else ''}).",
            reason="page", path=str(p.get("path")), mine=mine, theirs=now,
            theirs_version=version_of(now), clashes=got.clashes[:10])


async def _page_async(who, row) -> None:
    await asyncio.to_thread(_page, who, row)


async def _reminder(who, row) -> None:
    """A reminder made offline, made the way Clockwork's form makes one, on his clock."""
    from . import clock, reminders, runtime

    p = row.payload or {}
    zone = str(p.get("zone") or "")
    if zone:
        with contextlib.suppress(Exception):
            await asyncio.to_thread(clock.remember, who, zone)
    with clock.person(who):
        at = str(p.get("time") or "").strip()
        day = str(p.get("date") or "").strip()
        if not at:
            raise Refused("A reminder needs a time.")
        try:
            first = (datetime.fromisoformat(f"{day}T{at}").replace(tzinfo=clock.zone()) if day
                     else reminders.moment_of(at))
        except ValueError:
            raise Refused("That is not a date and a time.") from None
        made = await asyncio.to_thread(
            reminders.add, who, what=str(p.get("what") or ""), title=str(p.get("title") or ""),
            kind="remind", chat_id="", first=first, repeat=str(p.get("repeat") or "once"), days=(),
            asked=[str(p.get("title") or ""), str(p.get("what") or "")])
    keeper = runtime.timekeeper
    keeper.clock.poke()
    with contextlib.suppress(Exception):
        await keeper.tell(who)
    await asyncio.to_thread(_finish, row, "done",
                            f"In Clockwork for {first.strftime('%a %d %b, %H:%M')}.", reminder=made.id)


async def _task(who, row) -> None:
    """A task made offline, made as the New task button makes one, and filed the same way."""
    from . import owning, runtime

    p = row.payload or {}
    title = str(p.get("title") or "").strip()
    if not title:
        raise Refused("A new task needs a name.")
    made = await asyncio.to_thread(owning.new_task, title)
    if made is None:
        raise Refused("A task could not be made.")
    note = str(p.get("note") or "").strip()
    if note:
        with contextlib.suppress(Exception):
            folder = _root() / (made.folder or "")
            agents = folder / "AGENTS.md"
            if agents.parent.is_dir():
                had = agents.read_text(encoding="utf-8") if agents.exists() else ""
                await asyncio.to_thread(write_note, agents,
                                        had.rstrip() + "\n\n## Written offline\n\n" + note + "\n")
    with contextlib.suppress(Exception):
        await runtime.announce_objects()
        await runtime._announce_workspace()
        runtime.NewTasks.maybe_file(made.id)
    await asyncio.to_thread(_finish, row, "done", f"Task {made.number or ''} made: {made.title}.".replace("  ", " "),
                            task=made.number)


async def _note(who, row) -> None:
    """A note recorded offline, given to Rouh as his own message in General.

    A voice note is written out first, by the same ears that hear him on Telegram; if they
    cannot, the sound is attached and the message says it could not be heard.
    """
    from . import attachments, runtime, uploads
    from .tenancy import SPEAKER

    p = row.payload or {}
    text = str(p.get("text") or "").strip()
    records = []
    heard = ""
    audio = str(p.get("audio") or "")
    if audio:
        if len(audio) > MAX_AUDIO_B64:
            raise Refused("That voice note is too long to send.")
        try:
            sound = base64.b64decode(audio, validate=False)
        except ValueError:
            raise Refused("That voice note could not be read.") from None
        if runtime.ears.ready:
            with contextlib.suppress(Exception):
                heard = (await runtime.ears.transcribe_file(sound, "voice-note.wav", "audio/wav")).strip()
        general = await asyncio.to_thread(runtime.memory.ensure_general)
        with contextlib.suppress(Exception):
            records = [await asyncio.to_thread(runtime.files.save, general, "voice-note.wav", sound,
                                               content_type="audio/wav")]
    when = _when(who, row.made_at)
    where = row.device_name or row.device_kind or "a device"
    kind = "Voice note" if audio else "Note"
    words = heard or text
    if audio and not heard:
        words = "(It could not be written out here; the recording is attached.)"
    message = f"{kind} I made offline on {where}, {when}:\n\n{words}"
    if text and heard:
        message += f"\n\n{text}"
    chat = await asyncio.to_thread(runtime.memory.ensure_general)
    content = attachments.stored_content(records, message) if records else message
    if records:
        with contextlib.suppress(Exception):
            uploads.take_in(records, ("chat", chat))
    with contextlib.suppress(Exception):
        await runtime.Hub.mirror(None, "user", message, attachments.markers_in(content) if records else None,
                                 chat=chat)
    token = SPEAKER.set(who)
    try:
        await runtime.Turns.start(chat, content, asked_by=None, speak=False, answer_now=True,
                                  heard="typed")
    finally:
        SPEAKER.reset(token)
    await asyncio.to_thread(_finish, row, "done", "Given to Rouh in General.", chat=chat)


# Clockwork, the goals and the quests: a change made on their pages offline, carried out through
# the very view the page posts it to online, as the person, on their clock. Only what a person
# does to what is already there is taken: a run started from a page waits for a connection,
# because "do it now" said yesterday on a plane is not "do it now" today.

#: The views a change may be carried out through, and the acts each takes from the outbox.
#: None is every body the view takes.
CLOCK_ROUTES = {
    "reminders_act": ("pause", "resume", "delete"),
    "reminders_save": None,
    "goals_step": ("tick", "status", "note", "reword", "pause", "resume", "redirect", "deadline",
                   "at", "after", "clear"),
    "quest_act": ("pause", "resume", "set", "brief"),
    "quest_ledger": None,
}

#: What a reminder is, for the question whether it changed while he was offline.
_REMINDER_FIELDS = ("state", "title", "what", "repeat", "days", "at_time", "kind")


def _clock_route(path: str, body: dict):
    """Which of `CLOCK_ROUTES` a change goes through: (name, view, its arguments)."""
    from django.urls import Resolver404, resolve

    from .web import clock as clock_views
    from .web import quests as quest_views

    views = {"reminders_act": clock_views.reminders_act, "reminders_save": clock_views.reminders_save,
             "goals_step": clock_views.goals_step, "quest_act": quest_views.act,
             "quest_ledger": quest_views.ledger}
    try:
        found = resolve(str(path or "").split("?")[0])
    except Resolver404:
        found = None
    name = next((n for n, view in views.items() if found is not None and found.func is view), "")
    if not name:
        raise Refused("That cannot be changed offline.")
    acts = CLOCK_ROUTES[name]
    if acts is not None and str(body.get("act") or "") not in acts:
        raise Refused("That needs a connection: it starts work now, and now was when you pressed it.")
    return name, views[name], found.kwargs


def _account(who):
    """The account to make a change as: the one the outbox call came with, else his own."""
    user = SIGNED_IN.get()
    if user is not None:
        return user
    from django.contrib.auth import get_user_model

    found = get_user_model().objects.filter(pk=who.user_id).first()
    if found is not None:
        return found

    class Signed:
        pk = who.user_id
        is_authenticated = True

    return Signed()


async def _through_view(who, view, kwargs: dict, path: str, body: dict, zone: str) -> tuple[int, dict]:
    """The view, called as the page calls it, as him: its status and what it answered."""
    from django.http import HttpRequest

    req = HttpRequest()
    req.method = "POST"
    req.path = req.path_info = path
    req.META = {"CONTENT_TYPE": "application/json", "REQUEST_METHOD": "POST",
                "SERVER_NAME": "rouh", "SERVER_PORT": "443"}
    if zone:
        req.META["HTTP_X_TIME_ZONE"] = zone
    req._body = json.dumps(body).encode("utf-8")
    req.user = await asyncio.to_thread(_account, who)
    got = view(req, **kwargs)
    if asyncio.iscoroutine(got):
        got = await got
    try:
        said = json.loads(got.content or b"{}")
    except ValueError:
        said = {}
    return got.status_code, said if isinstance(said, dict) else {}


def _reminder_now(who, ident) -> dict | None:
    """One row of his Clockwork as its page draws it now, on his clock."""
    from . import clock, reminders

    with clock.person(who):
        row = reminders.one(who, ident)
        return reminders.view(row) if row is not None else None


def _goal_step_now(who, folder: str) -> dict | None:
    """A step of a goal as the Goals page has it now, found by its folder."""
    from . import goals

    def flat(steps):
        for s in steps or []:
            yield s
            yield from flat(s.get("parts"))

    for goal in goals.listing(who):
        for step in flat(goal.get("steps")):
            if step.get("folder") == folder:
                return step
    return None


def _quest_now(who, number) -> dict | None:
    from . import quests

    row = quests.by_number(who, int(number))
    return None if row is None else {"paused": getattr(row, "state", "") == "paused"}


def _clock_moved(who, name: str, kwargs: dict, body: dict, base: dict) -> tuple[str, str, str]:
    """Whether what a change acted on moved since the device read it: ("" when not), else
    ("done" or "clash", what happened, how it is now)."""
    act = str(body.get("act") or "")
    if name in ("reminders_act", "reminders_save") and body.get("id"):
        now = _reminder_now(who, body.get("id"))
        if now is None:
            raise Refused("That is not in Clockwork any more.")
        if act in ("pause", "resume") and now.get("state") == ("paused" if act == "pause" else "on"):
            return "done", f"It was already {'paused' if act == 'pause' else 'on'}.", ""
        had = {k: base.get(k) for k in _REMINDER_FIELDS if k in base}
        moved = [k for k, v in had.items() if (now.get(k) or "") != (v or "")]
        if moved:
            return ("clash", "It was changed here while you were offline.",
                    f"{now.get('title') or now.get('what') or ''}: {now.get('repeats') or ''}, "
                    f"next {now.get('when') or 'never'}, {now.get('state') or ''}.")
        return "", "", ""
    if name == "goals_step" and body.get("folder") and act in ("status", "tick", "note"):
        now = _goal_step_now(who, str(body.get("folder")))
        if now is None:
            return "", "", ""
        want = str(body.get("status") or "")
        if act == "status" and now.get("status") == want:
            return "done", f"It was already {want.replace('-', ' ')}.", ""
        if base.get("status") and now.get("status") != base.get("status"):
            return ("clash", "The step moved here while you were offline.",
                    f"{now.get('title') or ''}: {str(now.get('status') or '').replace('-', ' ')}.")
        return "", "", ""
    if name == "quest_act" and act in ("pause", "resume") and kwargs.get("number"):
        now = _quest_now(who, kwargs["number"])
        if now is None:
            raise Refused("That quest is not there any more.")
        # Paused or going on is all there is to it, so the only thing that can have moved is
        # that it is already as he left it.
        if now["paused"] == (act == "pause"):
            return "done", f"It was already {'paused' if act == 'pause' else 'going on'}.", ""
    return "", "", ""


async def _clock(who, row, *, over: bool = False) -> None:
    """A change on Clockwork, a goal or a quest, carried out through the view that makes it.

    Unless what it acted on moved meanwhile: then it is a decision showing both, as every
    other kind's clash is, and `over` is his answer to carry it out anyway."""
    p = row.payload or {}
    body = p.get("body") if isinstance(p.get("body"), dict) else {}
    path = str(p.get("path") or "")
    name, view, kwargs = _clock_route(path, body)
    if not over:
        how, said, theirs = await asyncio.to_thread(_clock_moved, who, name, kwargs, body, row.base or {})
        if how == "done":
            await asyncio.to_thread(_finish, row, "done", said, route=name)
            return
        if how == "clash":
            await asyncio.to_thread(_finish, row, "clash", said, reason="clock", route=name,
                                    mine=label_of("clock", p), theirs=theirs)
            return
    status, said = await _through_view(who, view, kwargs, path, body, str(p.get("zone") or ""))
    if status == 409:
        await asyncio.to_thread(_finish, row, "clash", str(said.get("error") or "It changed meanwhile."),
                                reason="clock", route=name, mine=label_of("clock", p),
                                theirs=str(said.get("error") or ""))
        return
    if status >= 400:
        raise Refused(str(said.get("error") or f"It was refused ({status})."))
    await asyncio.to_thread(_finish, row, "done",
                            str(said.get("said") or "").strip() or "Done, as you did it offline.",
                            route=name)


async def _gene_therapy(who, row) -> None:
    """Feedback written offline: on the board as if Send had been pressed when it was written.

    Through the board's own store, under his organisation, dated when he wrote it rather than
    when the device came back, and taken up by itself as the drawer's Send is."""
    from . import runtime

    p = row.payload or {}
    body = str(p.get("body") or "").strip()
    if not body:
        raise Refused("There was nothing written, so nothing was sent.")
    store = getattr(runtime, "gene_therapy", None)
    if store is None:
        raise Refused("Gene therapy is not kept on this Rouh.")
    from . import gene_therapy as gt

    try:
        made = await asyncio.to_thread(store.add_feedback, org_id=who.org_id, user_id=who.user_id,
                                       author=getattr(who, "name", "") or "", body=body,
                                       page=str(p.get("page") or ""), created_at=row.made_at)
    except gt.Refused as exc:
        raise Refused(str(exc)) from None
    convert = getattr(runtime, "converter", None)
    if convert is not None and convert.enabled:
        with contextlib.suppress(Exception):
            convert.take_later(who.org_id, made)
    await asyncio.to_thread(_finish, row, "done",
                            f"On the Gene therapy board, as written {_when(who, row.made_at)}.",
                            feedback=made.id)


CARRY = {"decision": _decision, "reply": _reply, "draft": _draft, "page": _page_async,
         "reminder": _reminder, "task": _task, "note": _note, "clock": _clock,
         "feedback": _gene_therapy}


# --- clashes and holds, answered as decisions (`decision_sources.OfflineSource`) -------------


def asking(who) -> list:
    """Every action of his waiting on him, oldest first."""
    from .models import OfflineAction

    return list(OfflineAction.objects.filter(**_whose(who), status__in=ASKING).order_by("received_at"))


def one(who, action_id: str):
    from .models import OfflineAction

    return OfflineAction.objects.filter(**_whose(who), action_id=action_id).first()


async def resolve(who, action_id: str, pick: str, text: str = "") -> tuple[bool, str]:
    """Carry out his answer to a clash or a hold: (done, what happened)."""
    row = await asyncio.to_thread(one, who, action_id)
    if row is None or row.status not in ASKING:
        return True, "It had already been settled."
    o = row.outcome or {}
    reason = o.get("reason")
    if pick == "drop":
        if row.kind in ("reply", "draft") and reason == "send":
            await asyncio.to_thread(_finish, row, "done", "Kept as a draft; it was not sent.")
            await push(who, [as_dict(row)])
            return True, "Kept as a draft. Nothing was sent."
        await asyncio.to_thread(_finish, row, "dropped", "Dropped, as you said.")
        await push(who, [as_dict(row)])
        return True, "Dropped. Nothing was done with it."
    try:
        if row.kind == "page":
            said = await asyncio.to_thread(_settle_page, row, pick)
        elif row.kind == "decision":
            said = await _settle_decision(who, row, pick)
        elif row.kind in ("reply", "draft"):
            said = await _settle_mail(who, row, pick)
        elif row.kind == "clock":
            if pick != "send":
                raise Refused("That is not one of the answers.")
            await _clock(who, row, over=True)
            said = row.result or "Done."
        else:
            said = "Nothing more to do."
            await asyncio.to_thread(_finish, row, "done", said)
    except Refused as exc:
        return False, str(exc)
    await push(who, [as_dict(row)])
    log.info("offline action %s (%s, %s) settled: %s", action_id, row.kind, reason, pick)
    return True, said


def _settle_page(row, pick: str) -> str:
    o = row.outcome or {}
    path = _note_path(str(o.get("path") or (row.payload or {}).get("path") or ""))
    mine = str((row.payload or {}).get("text") or "")
    now = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    if pick == "theirs":
        _finish(row, "dropped", "Kept the page as it is here; your offline edit was set aside.")
        return "Kept the page as it is."
    if pick == "both":
        joined = now.rstrip() + "\n\n<!-- Written offline on " + (row.device_name or "a device") + " -->\n\n" + mine
        write_note(path, joined)
        _finish(row, "done", "Kept both: your offline version is under the page as it was.",
                version=version_of(joined))
        return "Kept both versions, yours below."
    if pick == "mine":
        if version_of(now) != o.get("theirs_version"):
            raise Refused("The page changed again since this was asked. Open it and look before choosing.")
        write_note(path, mine)
        _finish(row, "done", "Your offline version is the page now.", version=version_of(mine))
        return "Your version is the page now."
    raise Refused("That is not one of the answers.")


async def _settle_decision(who, row, pick: str) -> str:
    """Send the answer after all (with its confirmation where the decision needs one)."""
    from . import decisions, runtime

    p = row.payload or {}
    o = row.outcome or {}
    if pick not in ("send", "confirm"):
        await asyncio.to_thread(_finish, row, "dropped", "Left as it was.")
        return "Left as it was."
    body = {"choice": [str(c) for c in p.get("choice") or []], "text": str(p.get("text") or "")}
    if p.get("items"):
        body["items"] = p["items"]
    if pick == "confirm" or p.get("confirm"):
        body["confirm"] = str(o.get("risk") or p.get("confirm") or "")
    try:
        got = await runtime.desk.act(who, int(o.get("decision") or p.get("decision") or 0), "answer", body,
                                     channel="offline")
    except decisions.NeedsConfirm as exc:
        raise Refused(f"It still needs its confirmation: {exc.note or exc}") from None
    except decisions.Refused as exc:
        raise Refused(str(exc)) from None
    await asyncio.to_thread(_finish, row, "done", _answered(got))
    return _answered(got)


async def _settle_mail(who, row, pick: str) -> str:
    """A reply that met a newer email, or a send that waited for its confirmation."""
    from . import mail_cases

    p = row.payload or {}
    o = row.outcome or {}
    gmail = await _rouh_gmail(who)
    if o.get("reason") == "newer_mail":
        if pick != "draft":
            raise Refused("That is not one of the answers.")
        reply_to = str(p.get("message_id") or "") if p.get("whose", "rouh") == "rouh" else ""
        made = await gmail.draft(str(p.get("to") or ""), str(p.get("subject") or ""), str(p.get("body") or ""),
                                 cc=str(p.get("cc") or ""), reply_to_message_id=reply_to)
        await asyncio.to_thread(_finish, row, "done", "Saved as a draft, after the newer email.",
                                draft_id=made.get("draft_id") or made.get("id") or "")
        return "Saved as a draft. Read the newer email before you send it."
    if pick != "send":
        raise Refused("That is not one of the answers.")
    held = await asyncio.to_thread(mail_cases.holds_reply, str(who.user_id), str(who.org_id),
                                   str(p.get("message_id") or ""))
    if held:
        raise Refused(held)
    draft_id = str(o.get("draft_id") or "")
    reply_to = str(p.get("message_id") or "") if p.get("whose", "rouh") == "rouh" and row.kind == "reply" else ""
    await _send(who, gmail, row, {"to": o.get("to"), "subject": o.get("subject")}, draft_id, reply_to)
    return f"Sent to {o.get('to') or p.get('to') or ''}."


def _when(who, at: float) -> str:
    """A moment as the person's own clock says it (`clock.zone_of`), not the server's."""
    from . import clock

    try:
        zone = clock.zone_of(who) if who is not None else None
    except Exception:  # noqa: BLE001 - the server's clock is still a clock
        zone = None
    return datetime.fromtimestamp(at, zone).strftime("%a %d %b, %H:%M")


def question_of(row, who=None) -> dict:
    """What the decision for one waiting action asks: its words, both versions, its answers."""
    o = row.outcome or {}
    p = row.payload or {}
    reason = o.get("reason") or ""
    when = _when(who, row.made_at)
    on = f"on {row.device_name or row.device_kind or 'a device'}, {when}"
    mine = str(o.get("mine") or "")
    theirs = str(o.get("theirs") or "")
    # His words, once in quotation marks: the device may have put them in already.
    said = mine.strip().strip("\u201c\u201d\"")
    out = {"risk": "reversible", "risk_note": "", "allow_other": False, "recommended": "",
           "recommended_why": "", "urgency": "today"}
    if row.kind == "page":
        out.update(
            title=f"Offline edit clashed: {os.path.basename(str(o.get('path') or ''))}",
            question=f"You edited {o.get('path')} offline {on}, and it was changed here meanwhile in the "
                     "same place. Which should it be?",
            why="Two edits met in the same lines, so neither was written over the other.",
            prepared=[{"label": "Your offline version", "text": mine[:20_000]},
                      {"label": "The page as it is now", "text": theirs[:20_000]}]
            + [{"label": f"Where they meet, line {c.get('line')}",
                "text": f"Yours:\n{c.get('mine')}\nNow:\n{c.get('theirs')}"} for c in (o.get("clashes") or [])[:3]],
            options=[{"id": "mine", "label": "Keep mine", "detail": "Your offline version becomes the page."},
                     {"id": "theirs", "label": "Keep the page as it is", "detail": "Your edit is set aside."},
                     {"id": "both", "label": "Keep both", "detail": "Yours goes under the page as it is."}],
            recommended="both", recommended_why="Nothing is lost, and you can tidy it afterwards.")
    elif row.kind == "decision" and reason == "confirm":
        out.update(
            title=f"Confirm your offline answer: {o.get('question') or ''}"[:200],
            question=f"You answered “{said}” offline {on}. {row.result}",
            why="Anything that spends money, sends, publishes or cannot be undone waits for this.",
            prepared=[{"label": "Your offline answer", "text": mine}],
            options=[{"id": "confirm", "label": "Yes, go ahead", "detail": "Your answer is given now.",
                      "go": True},
                     {"id": "drop", "label": "Drop my answer", "detail": "The decision stays open."}],
            risk=str(o.get("risk") or "irreversible"), risk_note=str(row.result or ""), urgency="now")
    elif row.kind == "decision":
        out.update(
            title=f"Offline answer clashed: {o.get('question') or ''}"[:200],
            question=f"You answered “{said}” offline {on}. {row.result}",
            why="Your answer was not given over a newer one.",
            prepared=[{"label": "Your offline answer", "text": mine},
                      {"label": "What happened here", "text": theirs or row.result}],
            options=([{"id": "send", "label": "Give my answer now",
                       "detail": "Only if the decision can still take it."}] if reason == "changed" else [])
            + [{"id": "drop", "label": "Leave it as it is", "detail": "Your offline answer is set aside."}],
            recommended="drop", recommended_why="It was settled while you were away.")
    elif row.kind == "clock":
        out.update(
            title=f"Offline change clashed: {mine}"[:200],
            question=f"You did this offline {on}: {mine}. {row.result} Do it anyway?",
            why="What you changed is not what it was when you changed it, so nothing was done over it.",
            prepared=[{"label": "What you did offline", "text": mine},
                      {"label": "As it is now", "text": theirs or row.result}],
            options=[{"id": "send", "label": "Do it anyway", "detail": "Your offline change is made now."},
                     {"id": "drop", "label": "Leave it as it is", "detail": "Your offline change is set aside."}],
            recommended="drop", recommended_why="It moved while you were away; look at it first.")
    elif row.kind in ("reply", "draft") and reason == "newer_mail":
        out.update(
            title=f"Offline reply met a newer email: {p.get('subject') or ''}"[:200],
            question=f"You wrote a reply offline {on}. {row.result} Keep yours as a draft?",
            why="It would answer an email that is no longer the latest in the thread.",
            prepared=[{"label": "Your offline reply", "text": mine[:20_000]},
                      {"label": "The newer email", "text": theirs[:20_000]}],
            options=[{"id": "draft", "label": "Keep it as a draft", "detail": "Nothing is sent."},
                     {"id": "drop", "label": "Drop my reply", "detail": "It is thrown away."}],
            recommended="draft", recommended_why="You can change it after reading the newer one.")
    else:
        to = o.get("to") or p.get("to") or ""
        out.update(
            title=f"Send your offline email to {to}?"[:200],
            question=f"You wrote this offline {on} and asked for it to be sent. {row.result}",
            why="Sending cannot be undone, so it waits for your yes.",
            prepared=[{"label": f"To {to} - {o.get('subject') or p.get('subject') or ''}", "text": mine[:20_000]}],
            options=([{"id": "send", "label": "Send it", "detail": f"Goes to {to} now.", "go": True}]
                     if not o.get("refused") else [])
            + [{"id": "drop", "label": "Keep it as a draft only", "detail": "It stays in Drafts."}],
            risk="sending", risk_note=f"Sends an email to {to}.", urgency="today")
    return out
