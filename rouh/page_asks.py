"""What they asked on your pages: asked in words, Rouh lists what each person asked Ask AI to do on
‹his› pages, when, and what it did.

Built by the nightly feature run, night 28, 31 October 2026 (task 94, idea I-168). ‹He› shares
Work pages for others to change with Ask AI: a site's copy page with the marketing lead who writes
it, who made 133 changes there by 27 October 2026, most of them in long requests with whole
sections of new copy. Before a meeting with him, ‹he› wanted to know where the site stood and what
had been changed, and a job had to count the changes out of the workspace's git history (task 61,
step 61-05: "96 Ask AI edits ... from 25 September to 1 October"). Asked in a chat, Rouh had no way
to see who asked Ask AI for what: each page's History panel lists its own changes in one line each,
one page at a time, and nothing else reads them.

So, while its switch is on, the tool `page_asks` gives, newest first, every change Ask AI made on
the owner's pages (one task's, or all of them) in the days asked, by one person or by everybody:
when, who, on which page, what they asked in their own words (the request it answered), what Ask
AI said it did, and whether it was undone; with a count by person and by page first. Rouh reads it
and says what matters; nothing is changed.

**Whose.** The changes on the owner's own pages, as the History panel reads them: `askai_edits`
rows whose `page_org_id` is the owner's organisation, and the requests in the same Ask AI thread
(`askai_messages`). A guest's own requests on pages that are not the owner's are never read.

**Its switch** is `page_asks` (`rouh/switches.py`): off, the tool says it is switched off.
"""
from __future__ import annotations

import logging
import re
import time

log = logging.getLogger("rouh.page_asks")

SWITCH = "page_asks"
TITLE = ("What they asked on your pages: asked in words, Rouh lists what each person asked Ask AI "
         "to do on your pages, when, and what it did")
TOOL_NAME = "page_asks"
#: The days looked back when none are said, and the most.
DAYS, MOST_DAYS = 14, 180
#: The most changes said, and how much of a request is quoted.
SHOWN, ASKED = 60, 700
DESCRIPTION = (
    "List what people asked Ask AI to do on the person's own pages, and what it changed, because "
    "the person asked: 'what did Tom change on the site this week?', 'who has been editing task "
    "61's pages?', 'what did Maria ask on the plan?'. Each change Ask AI made on their pages "
    "(History in the page's menu keeps them one page at a time) comes with when, who asked, the "
    "page and its task, the request in the asker's own words, what Ask AI said it did, and "
    "whether it was undone, newest first, after a count by person and by page. Give `person` as "
    "a name as they said it ('Tom'), or leave it out for everybody; `task` as a number to keep "
    "to one task. Read it and say what matters: what changed, what is still asked for, what was "
    "put back. It changes nothing.")
SCHEMA = {
    "type": "object",
    "properties": {
        "person": {"type": "string",
                   "description": "Whose requests: a name, or part of one; 'me' for the owner's own."},
        "task": {"type": "string", "description": "Only one task's pages: its number (61)."},
        "days": {"type": "integer", "description": f"How many days back. {DAYS} when left out."},
    },
    "required": [],
}


def on(who) -> bool:
    from . import switches

    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def _task_of(doc: str) -> str:
    """The task number a page's path is under ("work/northwind/61.launch-plan/..." is 61), or ""."""
    for part in str(doc or "").split("/"):
        found = re.match(r"^(\d+)\.", part)
        if found:
            return found.group(1)
    return ""


def _clip(text: str, most: int) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= most else text[:most - 1].rstrip() + "…"


def find(who, *, person: str = "", task: str = "", days: int = DAYS,
         now: float | None = None) -> dict:
    """{items, people, pages, days} of the changes on the owner's pages, newest first."""
    from . import comments_by, pagehistory
    from .models import AskEdit, AskMessage

    now = now or time.time()
    days = max(1, min(int(days or DAYS), MOST_DAYS))
    task = str(task or "").strip().split("-", 1)[0].strip()
    rows = list(AskEdit.objects.filter(page_org_id=who.org_id or "", kind="",
                                       created_at__gte=now - days * 86400)
                .order_by("-id").values("id", "user_id", "doc", "thread_id", "summary",
                                         "created_at", "undone_at"))
    if task:
        rows = [r for r in rows if _task_of(r["doc"]) == task]
    called = pagehistory.names(r["user_id"] for r in rows)
    me = str(who.user_id)
    asked = " ".join(str(person or "").split())
    if asked.lower() in ("me", "myself", "i", "you"):
        rows = [r for r in rows if r["user_id"] == me]
    elif asked:
        rows = [r for r in rows if comments_by.matches(asked, called.get(r["user_id"], ""))]
    threads = {r["thread_id"] for r in rows if r["thread_id"]}
    requests: dict[int, list[tuple[float, str]]] = {}
    for m in (AskMessage.objects.filter(thread_id__in=threads, role="user")
              .order_by("id").values("thread_id", "content", "created_at")):
        requests.setdefault(m["thread_id"], []).append((m["created_at"], m["content"]))
    items = []
    for r in rows:
        before = [c for at, c in requests.get(r["thread_id"] or 0, []) if at <= r["created_at"] + 1]
        items.append({"at": r["created_at"], "doc": r["doc"], "task": _task_of(r["doc"]),
                      "who": "you" if r["user_id"] == me else called.get(r["user_id"], "Somebody"),
                      "asked": before[-1] if before else "", "did": r["summary"] or "",
                      "undone": bool(r["undone_at"])})
    people: dict[str, int] = {}
    pages: dict[str, int] = {}
    for i in items:
        people[i["who"]] = people.get(i["who"], 0) + 1
        pages[i["doc"]] = pages.get(i["doc"], 0) + 1
    return {"items": items, "people": people, "pages": pages, "days": days}


def _day(at: float, who) -> str:
    from datetime import datetime

    from . import clock

    return datetime.fromtimestamp(at, clock.zone_of(who)).strftime("%a %d %b %H:%M")


def said(got: dict, who, person: str, task: str) -> str:
    items = got["items"]
    scope = (f" on task {task}'s pages" if task else " on your pages") + f" in the last {got['days']} days"
    by = f" asked by {person}" if person else ""
    if not items:
        return (f"No change Ask AI made{by}{scope}. Only changes Ask AI made are kept here; a page "
                "edited by hand or by a job is in its task's history instead.")
    lines = [f"{len(items)} changes Ask AI made{by}{scope}."]
    lines.append("By person: " + "; ".join(f"{k} {v}" for k, v in
                                           sorted(got["people"].items(), key=lambda kv: -kv[1])) + ".")
    lines.append("By page: " + "; ".join(f"{k} {v}" for k, v in
                                         sorted(got["pages"].items(), key=lambda kv: -kv[1])[:12]) + ".")
    for i in items[:SHOWN]:
        line = f"\n- {_day(i['at'], who)}, {i['who']}, {i['doc']}"
        if i["undone"]:
            line += " (undone since)"
        if i["asked"]:
            line += f"\n  Asked: «{_clip(i['asked'], ASKED)}»"
        if i["did"]:
            line += f"\n  Ask AI did: {_clip(i['did'], 300)}"
        lines.append(line)
    if len(items) > SHOWN:
        lines.append(f"\nAnd {len(items) - SHOWN} older ones; ask for fewer days to see them.")
    return "\n".join(lines)


async def answer(who, args: dict) -> str:
    """The tool: the changes asked for on the owner's pages, or why not, in words."""
    import asyncio

    from . import evolution, untrusted

    if who is None or not await asyncio.to_thread(on, who):
        return untrusted.ours("Listing what was asked on your pages is switched off (What they "
                              "asked on your pages, in Evolution, Mutations).")
    person = " ".join(str(args.get("person") or "").split())
    task = str(args.get("task") or "").strip()
    got = await asyncio.to_thread(find, who, person=person, task=task,
                                  days=int(args.get("days") or DAYS))
    await asyncio.to_thread(evolution.used, SWITCH, "listed", who=who,
                            detail=f"{len(got['items'])} Ask AI changes on the owner's pages")
    return said(got, who, person, task)


__all__ = ["SWITCH", "TITLE", "TOOL_NAME", "answer", "find", "on"]
