"""The person's answer to a waiting task, and what became of it.

Petar, 24 September 2026 (fr_2050f48023a7), about the yellow box on task 61:
"it has to be clear what happens afterwards. would the chat continue? the task
will continue? I don't feel we have a clear idea what stopped and how it will
continue forward."

A task that waits on the person asks at the top of its own page
(`objectindex._waiting_panel`), with the answers it offers and a box for his
own. An answer sent from there goes into the chat the task already has, and
into a new one only when it has none (`conversations.answer_for_task`), where
Rouh hands it to a job that writes it into the task and carries the task on
(`brain.WAITING`). That job changes the task itself - its notes, and its
status off `waiting` - and what it changes lands minutes later. Until then the
task still says Waiting, and its page asked the same question again as if
nothing had happened, and "Waiting on you" still listed it.

So the answer is written down here the moment it is sent, against the task
and the question as the page showed it (`record`), and read back wherever the
task says what it waits on (`answer_to`, `answers_to`): its page says it was
answered, when, in which chat and which job has it, and the lists stop saying
it waits on him. An answer is to one question: a job that asks something new
asks it in new words, and the page asks that one afresh.

Dismissed
---------

Petar, the same day: "i also need the option to dismiss it". A question can
be closed without an answer: a row here with `dismissed` set and nothing in
it, and nothing sent anywhere - no chat, no job, and the task itself left
exactly as it is. The newest row on a question decides: dismissed, the page
keeps one line saying so with the way back to the question, and the lists
stop counting it as waiting on him; answered after all, it is answered. An
answer that is dismissed stays the answer, and its job goes on.

Everything here is the workspace's, like the tasks and chats it points at, and
never read by anybody who could not read the task.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from . import waiting

log = logging.getLogger("rouh.answering")

#: The longest answer kept, and the longest question. The page cuts its own
#: before it sends them (`taskpage.js`); these stop anything else growing a row.
ANSWER_MOST = 4000
ASKED_MOST = waiting.ASK_MOST + waiting.LINE_MOST

#: How long before an answer a job may have started and still be the one
#: carrying it: none, give or take the clocks of two processes.
SLACK = 5.0


@dataclass(frozen=True)
class Answered:
    """The newest word on a question: an answer, a dismissal, or both, and
    the job started from the answer's chat since."""

    #: What they answered, or "" when they only dismissed it.
    answer: str
    #: When they answered, or when they dismissed it if they never answered.
    at: float
    chat_id: str
    #: The newest run started from the answer's chat since, or None.
    run: object | None = None
    #: The box was closed, after the answer or instead of one.
    dismissed: bool = False
    #: When it was closed, when it was.
    dismissed_at: float = 0.0


def asked_of(root, folder: str, names=()):
    """What a waiting task asks, in the three shapes its callers need.

    The question's shape from its meta (or None), the passage from its
    notes (or None), and the one line an answer is recorded against: the
    question as its meta puts it, else the notes' own line, else "". Every
    place that says what a task waits on asks here, so the line on the rail
    and the question on the page are always the same words.
    """
    question = waiting.question_of(root, folder)
    notes = waiting.ask_of(root, folder, names)
    line = (question.ask if question and question.ask
            else notes.line if notes else "")
    return question, notes, line


def _cut(text, most: int) -> str:
    return str(text or "").strip()[:most]


def record(folder: str, asked: str, answer: str, chat_id: str, *,
           dismissed: bool = False) -> str:
    """Write down an answer sent from a task's page, or the question
    dismissed there. The task's id, or "".

    `folder` is the task's, as Rouh's own page read it off the canvas, never
    as the framed page said it (`taskChat` in app.js). Nothing is written for
    a folder no task has, or an answer with nothing in it. A dismissal has no
    answer and no chat, because nothing was sent."""
    from . import conversations
    from .models import TaskAnswer

    answer = "" if dismissed else _cut(answer, ANSWER_MOST)
    if not folder or not (answer or dismissed):
        return ""
    task = conversations.task_by_folder(str(folder).strip().strip("/"))
    if task is None:
        log.warning("an answer came for %s, where there is no task", folder)
        return ""
    TaskAnswer.objects.create(task_id=task.id, asked=_cut(asked, ASKED_MOST),
                              answer=answer, chat_id="" if dismissed else _cut(chat_id, 200),
                              dismissed=dismissed, created_at=time.time())
    if dismissed:
        log.info("task %s: its question dismissed", task.number)
    else:
        log.info("task %s answered in chat %s", task.number, chat_id)
    return task.id


def answers_to(asked: dict[str, str]) -> dict[str, Answered]:
    """The newest word on each task's question as it is asked now: its
    answer, whether it was dismissed, or both (`_read`).

    `asked` is task id -> the line the question is asked in (`asked_of`). A
    task whose newest row was about other words has had nothing said about
    this question, and is left out. One query for the whole list, since the
    rail asks for every waiting task at once."""
    from .models import TaskAnswer

    if not asked:
        return {}
    newest: dict[str, list[dict]] = {}
    rows = (TaskAnswer.objects.filter(task_id__in=list(asked))
            .order_by("task_id", "-created_at", "-id")
            .values("task_id", "asked", "answer", "chat_id", "dismissed", "created_at"))
    for row in rows:
        newest.setdefault(row["task_id"], []).append(row)
    out: dict[str, Answered] = {}
    for task_id, said in newest.items():
        got = _read(said, _cut(asked[task_id], ASKED_MOST))
        if got is not None:
            out[task_id] = got
    return out


def _read(said: list[dict], line: str) -> Answered | None:
    """One task's rows, newest first, read as the word on this question.

    Only the rows since the task last asked something else count: an older
    answer to the same words, from before another question came in between,
    is not this answer. The newest of them says whether it is dismissed; the
    newest that is not a dismissal is the answer."""
    now: list[dict] = []
    for row in said:
        if row["asked"] != line:
            break
        now.append(row)
    if not now:
        return None
    dismissed = bool(now[0]["dismissed"])
    answered = next((row for row in now if not row["dismissed"]), None)
    if answered is None:
        return Answered(answer="", at=now[0]["created_at"], chat_id="",
                        dismissed=True, dismissed_at=now[0]["created_at"])
    return Answered(answer=answered["answer"], at=answered["created_at"],
                    chat_id=answered["chat_id"], dismissed=dismissed,
                    dismissed_at=now[0]["created_at"] if dismissed else 0.0)


def answer_to(task_id: str, asked: str) -> Answered | None:
    """The word on this task's question as it is asked now, with the job
    started from the answer's chat since, or None when nothing has been said
    about it."""
    from .models import Link, Run

    got = answers_to({task_id: asked}).get(task_id) if task_id else None
    if got is None or not got.chat_id:
        return got
    started = list(Link.objects.filter(rel="from", src_type="run", dst_type="chat",
                                       dst_id=got.chat_id).values_list("src_id", flat=True))
    run = (Run.objects.filter(id__in=started, started_at__gte=got.at - SLACK)
           .order_by("-started_at").first()) if started else None
    return Answered(answer=got.answer, at=got.at, chat_id=got.chat_id, run=run,
                    dismissed=got.dismissed, dismissed_at=got.dismissed_at)
