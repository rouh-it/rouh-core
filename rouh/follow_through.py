"""Followed through: when a job Rouh started finishes, Rouh does what it said it would do next.

Built by the nightly feature run, night 20, 23 October 2026 (task 94, idea I-117). On 22 October
2026 ‹he› asked Rouh to share a Drive folder with a colleague, put its link on a task's page, and
email her where it was. Rouh shared the folder, started a job for the page, and said "Once it's
done I'll email her the page link". The job finished; the note Rouh was handed about it ended, as
every finished job's does, "Do not start anything", and nothing reminded Rouh of what it had said.
The email never went until ‹he› asked "How come I asked you to send her an email and you didn't?"
The same shape ran through the fortnight before it: "Once it's done and I've checked the images
exist, I'll give you the one command", "I'll check it when it finishes". And the other half of it,
the same day: ‹he› added two documents to a running job, and its report said nothing about them;
Rouh told ‹him› to check the card for whether they made it in.

So, while its switch is on, the note a finished job hands Rouh (`assistant_job.Lander._say`, for
jobs of the workspace and of the one program alike) carries two more things, read by code from the
conversation the job was started in, with no model call:

* **What Rouh said it would do once the job was done**: the sentences of its own reply, in the turn
  that started the job, that promise a step of its own after the job ("once it's done I'll email
  her"), leaving out the ones that only promise to tell ‹him› the result, which the report does. The
  note then says to do that step now, as it was said, which is the one exception to "Do not start
  anything", or to say why it no longer makes sense.
* **What was added to the job while it ran**: every message Rouh sent on to it for ‹him›
  (`one_say`, `reply_to_task`), in the words sent. The note says to check the report against each,
  and to ask the job for one it left out rather than tell ‹him› to look.

Nothing else changes: a job with neither is reported exactly as before.

**Whose.** Only the conversation the job reports in, read by its own id: the same chat the note is
said in.

**Its switch** is `follow_through` (`rouh/switches.py`): off, the note is as it was.
"""
from __future__ import annotations

import json
import logging
import re

log = logging.getLogger("rouh.follow_through")

SWITCH = "follow_through"

#: Tools that hand a running job more of what the person wants.
ADDED_BY = {"one_say": "text", "reply_to_task": "answer"}

#: How much of each is carried: enough to recognise it, never a whole document.
SAID_MAX = 600
ADDED_MAX = 700
ADDED_COUNT = 6

#: A promise of one's own: "I'll" or "I will", and the verb that follows it.
_MINE = re.compile(r"\bI(?:'|’)ll\s+(\w+)|\bI will\s+(\w+)", re.I)
#: That the step waits on the job: once it is done, when it finishes, after it lands.
_AFTER = re.compile(r"\b(once|when|after|as soon as|then)\b", re.I)
#: Verbs that only promise to tell the person what came of it: the report does that.
_TELLING = {"tell", "let", "say", "report", "hear", "know", "update", "come", "be", "keep",
            "show", "ping", "text", "notify", "flag", "see", "get"}


def on(org_id=None) -> bool:
    from . import switches

    return switches.on(SWITCH, org_id or None)


def _rows(sql: str, args=()) -> list[dict]:
    from django.db import connection

    with connection.cursor() as cur:
        cur.execute(sql, args)
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def _blocks(content: str) -> list:
    try:
        said = json.loads(content)
    except (TypeError, ValueError):
        return [{"type": "text", "text": str(content or "")}]
    if isinstance(said, str):
        return [{"type": "text", "text": said}]
    return said if isinstance(said, list) else []


def _only_results(blocks: list) -> bool:
    """A user row that is only tool results, or a note from Rouh's own software, is not the person."""
    if not blocks:
        return True
    for b in blocks:
        if not isinstance(b, dict):
            return False
        if b.get("type") == "tool_result":
            continue
        return False
    return True


def promises(text: str) -> list[str]:
    """The sentences of a reply that promise a step of Rouh's own once the job is done."""
    found = []
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", str(text or "")):
        sentence = sentence.strip()
        if not sentence or not _AFTER.search(sentence):
            continue
        verbs = [(a or b).lower() for a, b in _MINE.findall(sentence)]
        if any(v not in _TELLING for v in verbs):
            found.append(sentence[:SAID_MAX])
    return found


def gather(chat: str, job: str) -> dict:
    """What Rouh said it would do once `job` finished, and what was added to it, in `chat`."""
    job = str(job or "").strip()
    if not chat or not job or not re.fullmatch(r"[\w-]{4,64}", job):
        return {"promised": [], "added": []}
    rows = _rows("SELECT id, role, content FROM messages WHERE session_id = %s AND content LIKE %s "
                 "ORDER BY id LIMIT 1", (chat, f"%{job}%"))
    if not rows:
        return {"promised": [], "added": []}
    start = rows[0]["id"]
    later = _rows("SELECT id, role, content FROM messages WHERE session_id = %s AND id >= %s "
                  "ORDER BY id LIMIT 400", (chat, start))
    promised: list[str] = []
    added: list[str] = []
    in_turn = True
    for r in later:
        blocks = _blocks(r["content"])
        if r["role"] == "user":
            if r["id"] != start and not _only_results(blocks):
                in_turn = False
            continue
        for b in blocks:
            if not isinstance(b, dict):
                continue
            if in_turn and b.get("type") == "text":
                promised += promises(b.get("text") or "")
            elif b.get("type") == "tool_use" and b.get("name") in ADDED_BY:
                given = b.get("input") or {}
                if str(given.get("run") or given.get("id") or "") == job:
                    words = str(given.get(ADDED_BY[b["name"]]) or "").strip()
                    if words:
                        added.append(words[:ADDED_MAX])
    seen = set()
    promised = [p for p in promised if not (p in seen or seen.add(p))]
    return {"promised": promised[:4], "added": added[-ADDED_COUNT:]}


def extend(note: str, *, chat: str, job: str, who=None) -> str:
    """A finished job's note, with what Rouh promised and what was added to the job. Never raises."""
    try:
        text = str(note or "")
        if not job or not chat or "finished" not in text[:200] or not on():
            return note
        got = gather(chat, job)
        extra = []
        if got["promised"]:
            said = " ".join(f"«{p}»" for p in got["promised"])
            extra.append(
                " When you started this job you told the person what you would do once it was "
                f"done: {said} Do that step now, exactly as you said, in this turn; it is the one "
                "thing \"Do not start anything\" does not cover. If the job's result makes it "
                "pointless or impossible, say so and why instead.")
        if got["added"]:
            asks = " ".join(f"«{a}»" for a in got["added"])
            extra.append(
                " While it ran, these were added to the job for the person, in the words sent: "
                f"{asks} Check its report against each. If the report says nothing about one, do "
                "not tell the person to look at the card: ask the job for it with reply_to_task, "
                "and say that you did.")
        if not extra:
            return note
        from . import evolution

        if got["promised"]:
            evolution.used(SWITCH, "kept_word", who=who,
                           detail=f"{len(got['promised'])} promised step(s) after job {job}")
        if got["added"]:
            evolution.used(SWITCH, "added_checked", who=who,
                           detail=f"{len(got['added'])} added message(s) to job {job}")
        body = text.rstrip()
        if body.endswith("]"):
            return body[:-1].rstrip() + "".join(extra) + "]"
        return body + "".join(extra)
    except Exception:
        log.exception("following through on job %s could not be read; the note is as it was", job)
        return note
