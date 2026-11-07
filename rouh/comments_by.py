"""Their comments: asked in words, Rouh finds every comment one person left on the Google
documents it can read.

Built by the nightly feature run, night 26, 29 October 2026 (task 94). On 28 October 2026 ‹he›
asked for an explainer to be updated "as per all comments of my brother nikola". Rouh said it
could not find anything from him, not in its inbox, not in Slack, not in the task, and went on a
guess; the job it started found three of his comments, made six days before, on a colleague's
Google Doc that another task's notes link to. Rouh could read the comments of one document it was
pointed at (`read_doc`, `doc_changes`), and had no way to ask "what did this person comment".

So, while its switch is on, the tool `comments_by` reads the comments on every Google Doc, Sheet
and Slides deck linked in the tasks' notes (or one task's), and on the ones changed lately in
Drive, and gives each comment and answer that person wrote in the days asked: the document, the
tasks that link it, the words it is on, what it says, when, whether it is open, resolved or
answered, and a link that opens that comment. No model call: Drive's own comments, matched by
name (`rouh/comments_in_docs.py`).

**Whose.** The documents the connected Google account can open, by `org_id` and `user_id`
(`rouh/tenancy.py`), read only.

**Its switch** is `comments_by` (`rouh/switches.py`): off, the tool says so and reads nothing.
"""
from __future__ import annotations

import logging
import re
import time

log = logging.getLogger("rouh.comments_by")

SWITCH = "comments_by"
TITLE = ("Their comments: asked in words, Rouh finds every comment one person left on the Google "
         "documents it can read")
TOOL_NAME = "comments_by"
#: The days looked back when none are said, and the most.
DAYS, MOST_DAYS = 30, 180
#: The most documents changed lately in Drive read besides the linked ones.
RECENT = 25
#: The most comments said.
SHOWN = 60
DESCRIPTION = (
    "Find the comments one person left on Google Docs, Sheets and Slides decks, because the "
    "person asked: 'what did Nikola comment?', 'apply all of Nikola's comments', 'has Tom said "
    "anything on the copy docs this week?'. It reads the comments on every Google document "
    "linked in the tasks' notes (or only one task's, with `task`) and on the documents changed "
    "lately in Drive, and gives each comment and answer by that person: the document, the task "
    "that links it, the words it is on, what it says, when, whether it is open, resolved or "
    "answered, and a link that opens it. Use it before saying you cannot find somebody's "
    "comments, and before a job applies them: hand the job what it found, word for word. Give "
    "`person` as a name as they said it ('Nikola', 'Tom Ward').")
SCHEMA = {
    "type": "object",
    "properties": {
        "person": {"type": "string", "description": "Whose comments: a name, or part of one."},
        "task": {"type": "string",
                 "description": "Only the documents one task's notes link to: its number (148)."},
        "days": {"type": "integer", "description": f"How many days back. {DAYS} when left out."},
        "open_only": {"type": "boolean",
                      "description": "Only comments not resolved yet. False when left out."},
    },
    "required": ["person"],
}
_TYPES = {"application/vnd.google-apps.document": "Google Doc",
          "application/vnd.google-apps.spreadsheet": "Google Sheet",
          "application/vnd.google-apps.presentation": "Google Slides"}


def on(who) -> bool:
    from . import switches

    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def matches(person: str, name: str) -> bool:
    """Whether a comment's author is the person asked for: every word asked starts a word of the
    author's name or address ("nikola" is Nikola Petrov)."""
    asked = [w for w in re.split(r"[\s,]+", str(person or "").lower()) if w]
    held = [w for w in re.split(r"[\s.@_\-]+", str(name or "").lower()) if w]
    return bool(asked) and all(any(h.startswith(w) for h in held) for w in asked)


def _in_task(doc: dict, task: str) -> bool:
    task = str(task or "").strip().split("-", 1)[0].strip()
    return not task or any(t["number"] == task for t in doc.get("tasks") or [])


async def _recent(drive) -> list[dict]:
    """Google documents changed lately in Drive, newest first, as `linked_docs` gives them."""
    try:
        files = await drive.search("", RECENT)
    except Exception as exc:  # noqa: BLE001 - the linked ones are read all the same
        log.info("Drive's recent files could not be listed: %r", exc)
        return []
    out = []
    for f in files:
        kind = _TYPES.get(f.get("mime_type") or "")
        if kind and f.get("id"):
            out.append({"id": f["id"], "kind": kind, "url": f.get("link") or "",
                        "title": f.get("name") or "", "at": 0.0, "tasks": []})
    return out


async def find(google, who, root, person: str, *, task: str = "", days: int = DAYS,
               open_only: bool = False) -> dict:
    """{ok, items: [{doc, comment, reply}], read, failed, linked, recent} or {ok: False, why}."""
    import asyncio

    from . import comments_in_docs as cid

    days = max(1, min(int(days or DAYS), MOST_DAYS))
    since = time.time() - days * 86400
    drive = google.services().drive
    linked = [d for d in await asyncio.to_thread(cid.linked_docs, root) if _in_task(d, task)]
    recent = [] if task else [d for d in await _recent(drive) if d["id"] not in {x["id"] for x in linked}]
    docs = linked[:cid.MOST_DOCS] + recent
    read, failed = await cid.read_all(drive, docs, most=len(docs))
    items = []
    for doc, comments in read:
        for c in comments:
            if open_only and c.get("resolved"):
                continue
            if matches(person, c.get("who")) and cid.moment(c.get("at")) >= since:
                items.append({"doc": doc, "comment": c, "reply": None})
                continue
            for r in c.get("replies") or []:
                if matches(person, r.get("who")) and cid.moment(r.get("at")) >= since:
                    items.append({"doc": doc, "comment": c, "reply": r})
    items.sort(key=lambda i: cid.moment((i["reply"] or i["comment"]).get("at")), reverse=True)
    return {"ok": True, "items": items, "read": len(read), "failed": failed,
            "linked": len(linked[:cid.MOST_DOCS]), "recent": len(recent), "days": days}


def said(person: str, got: dict, names: dict[str, str]) -> str:
    """What the tool answers, grouped by document, newest first."""
    from . import comments_in_docs as cid

    items = got["items"]
    where = (f"Read {got['read']} Google documents ({got['linked']} linked in tasks' notes"
             + (f", {got['recent']} changed lately in Drive" if got["recent"] else "") + ")"
             + (f"; {got['failed']} could not be opened by Rouh's Google account"
                if got["failed"] else "") + ".")
    if not items:
        return (f"No comment by {person} in the last {got['days']} days on the Google documents "
                f"Rouh can read. {where} A comment on a document Rouh's Google account cannot "
                "open is not among them: ask for it to be shared with Rouh.")
    docs = {}
    for i in items[:SHOWN]:
        docs.setdefault(i["doc"]["id"], []).append(i)
    lines = [f"Comments by {person} in the last {got['days']} days: {len(items)}, on {len(docs)} "
             f"documents. {where}"]
    for doc_id, mine in docs.items():
        doc = mine[0]["doc"]
        name = names.get(doc_id) or doc.get("title") or doc["kind"]
        tasks = "; ".join(f"task {t['number']} {t['title']}" for t in doc.get("tasks") or [])
        lines.append(f"\n{name} ({doc['kind']}" + (f", linked in {tasks}" if tasks else "") + ")")
        for i in mine:
            c, r = i["comment"], i["reply"]
            state = "resolved" if c.get("resolved") else (
                "open, answered" if cid.last_word(c)["answer"] else "open, no answer yet")
            if r is None:
                line = (f"- {cid.day(cid.moment(c.get('at')))}, {c.get('who') or person}, {state}"
                        + (f", on «{cid.clip(c['on'], 200)}»" if c.get("on") else "")
                        + f": «{cid.clip(c.get('words'), 600)}»")
            else:
                line = (f"- {cid.day(cid.moment(r.get('at')))}, {r.get('who') or person} answered "
                        f"{c.get('who') or 'a comment'}'s comment «{cid.clip(c.get('words'), 200)}» "
                        f"({state}): «{cid.clip(r.get('words'), 600)}»")
            lines.append(line + f" Opens at {cid.link_to(doc, c.get('id') or '')}")
    if len(items) > SHOWN:
        lines.append(f"\nAnd {len(items) - SHOWN} older ones; ask for fewer days to see them.")
    return "\n".join(lines)


async def answer(google, who, root, args: dict) -> str:
    """The tool: the person's comments, or why not, in words."""
    import asyncio

    from . import comments_in_docs as cid
    from . import evolution, untrusted

    if who is None or not await asyncio.to_thread(on, who):
        return untrusted.ours("Finding somebody's comments is switched off (Their comments, in "
                              "Evolution, Mutations).")
    person = " ".join(str(args.get("person") or "").split())
    if not person:
        return untrusted.ours("Say whose comments: a name, as they said it.")
    blocked = google.not_ready_because()
    if blocked:
        return blocked
    if not root:
        return untrusted.ours("There is no workspace here to find the tasks' documents in.")
    got = await find(google, who, root, person, task=str(args.get("task") or ""),
                     days=int(args.get("days") or DAYS), open_only=bool(args.get("open_only")))
    docs = {i["doc"]["id"]: i["doc"] for i in got["items"]}
    names = await cid.names(who, google.services().drive, list(docs.values())) if docs else {}
    await asyncio.to_thread(evolution.used, SWITCH, "found", who=who,
                            detail=f"{len(got['items'])} comments by one person on {len(docs)} documents")
    return said(person, got, names)


__all__ = ["DESCRIPTION", "SCHEMA", "SWITCH", "TITLE", "TOOL_NAME", "answer", "find", "matches", "on"]
