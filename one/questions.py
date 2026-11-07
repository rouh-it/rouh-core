"""Questions the program asks a person, and the runs waiting for the answers.

A question starts when a run wants to do something the rules say a person
must allow (``rules.decide`` answered ``ask``). The run's PreToolUse hook is an
HTTP request that stays open while the question is: Claude Code waits up to
ten minutes for a hook, so the run simply waits, and the answer goes back as
the hook's reply.

The question is an entry in the list, so every surface sees it at once: the
terminal, the browser, the orb, Rouh's voice. If nobody answers within
``phone_after`` seconds, the phone is told (``phone.py``). Whoever answers
first answers; the others see it closed. A question nobody answers is closed
as "expired" a minute before Claude Code would give up on the hook, and the
run is told no.

The phone gets a link with a token that answers only that question, only
while it is open, and only once: step 07's "it may only answer a question the
program asked, within minutes, and can never start anything".

A question can also be *posed* (:meth:`Questions.pose`) rather than asked: a
run paused on a choice only a person may make, such as carrying a run of Codex
on on the OpenAI API key once its subscription has stopped it (``billing.py``).
Nothing is held open waiting for it, so it has no time limit, it outlives a
restart of the program, and its two buttons say what they do rather than
"Allow" and "Deny". Its answer goes to whatever registered for its ``kind``.
"""
from __future__ import annotations

import asyncio
import logging
import secrets
import time
from typing import Any, Callable

from .listfile import ListFile, iso
from .views import Views

log = logging.getLogger("one.questions")

ANSWERS = ("yes", "no")


class Questions:
    def __init__(self, lst: ListFile, views: Views, *, timeout: float = 540.0,
                 clock: Callable[[], float] = time.time) -> None:
        self.list = lst
        self.views = views
        self.timeout = timeout
        self._clock = clock
        self._waiting: dict[str, asyncio.Future] = {}
        #: phone token -> question id. In memory only: the token is a secret.
        self._phone: dict[str, str] = {}
        #: kind -> what a posed question of that kind is answered into.
        self._handlers: dict[str, Callable[[dict[str, Any], str, str], Any]] = {}

    def handle(self, kind: str, fn: Callable[[dict[str, Any], str, str], Any]) -> None:
        """Hand every answer to a posed question of ``kind`` to ``fn(question, answer, by)``."""
        self._handlers[kind] = fn

    def pose(self, run_id: str, *, kind: str, text: str, choices: dict[str, str],
             detail: str | None = None, why: str | None = None, by: str = "program") -> str:
        """Put a choice to the person and return at once. The answer goes to ``kind``'s handler.

        One open question of a kind per run: posing it again while it is open
        leaves the one that is there.
        """
        for q in self.views.questions.values():
            if q["open"] and q.get("run") == run_id and q.get("kind") == kind:
                return q["id"]
        qid = secrets.token_hex(4)
        self.list.append("question.asked", run=run_id, by=by, body={
            "id": qid, "text": text, "tool": None, "what": None, "detail": detail, "why": why,
            "expires_at": None, "kind": kind, "lasting": True,
            "choices": {"yes": choices["yes"], "no": choices["no"]},
        })
        return qid

    async def ask(self, run_id: str, *, text: str, tool: str | None = None,
                  what: str | None = None, detail: str | None = None, why: str | None = None,
                  by: str = "program") -> str:
        """Ask, wait, and return the answer: yes, no, expired or withdrawn."""
        qid = secrets.token_hex(4)
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        self._waiting[qid] = future
        self.list.append("question.asked", run=run_id, by=by, body={
            "id": qid, "text": text, "tool": tool, "what": what, "detail": detail, "why": why,
            "expires_at": iso(self._clock() + self.timeout),
        })
        try:
            return await asyncio.wait_for(asyncio.shield(future), self.timeout)
        except asyncio.TimeoutError:
            if self.is_open(qid):
                self.list.append("question.expired", run=run_id, body={"id": qid})
            return "expired"
        finally:
            self._waiting.pop(qid, None)
            for token in [t for t, q in self._phone.items() if q == qid]:
                self._phone.pop(token, None)

    def is_open(self, qid: str) -> bool:
        q = self.views.questions.get(qid)
        return bool(q and q["open"])

    def answer(self, qid: str, answer: str, *, by: str) -> bool:
        """Answer an open question. False if it is not open, or the answer is not yes or no."""
        answer = (answer or "").strip().lower()
        if answer not in ANSWERS or not self.is_open(qid):
            return False
        q = self.views.questions[qid]
        run_id = q.get("run")
        said = (q.get("choices") or {}).get(answer)
        self.list.append("question.answered", run=run_id, by=by, body={
            "id": qid, "answer": answer, **({"said": said} if said else {})})
        future = self._waiting.get(qid)
        if future is not None and not future.done():
            future.set_result(answer)
        handler = self._handlers.get(q.get("kind") or "")
        if handler is not None:
            result = handler(dict(q), answer, by)
            if asyncio.iscoroutine(result):
                task = asyncio.get_running_loop().create_task(result)
                task.add_done_callback(_said_if_failed)
        return True

    def withdraw(self, qid: str, why: str) -> None:
        if not self.is_open(qid):
            return
        run_id = self.views.questions[qid].get("run")
        self.list.append("question.withdrawn", run=run_id, body={"id": qid, "why": why})
        future = self._waiting.get(qid)
        if future is not None and not future.done():
            future.set_result("withdrawn")

    def withdraw_run(self, run_id: str, why: str) -> None:
        for q in list(self.views.questions.values()):
            if q["open"] and q.get("run") == run_id:
                self.withdraw(q["id"], why)

    def withdraw_stale(self, why: str) -> None:
        """Close questions nobody is waiting on: the hook that asked is gone.

        A posed question is not one of them. Nothing was waiting on it in the
        first place, and the run is still paused on it after a restart.
        """
        for q in list(self.views.questions.values()):
            if q["open"] and q["id"] not in self._waiting and not q.get("lasting"):
                self.withdraw(q["id"], why)

    # -- the phone ----------------------------------------------------------

    def phone_token(self, qid: str) -> str:
        token = secrets.token_urlsafe(24)
        self._phone[token] = qid
        return token

    def for_phone(self, token: str) -> dict[str, Any] | None:
        """The open question a phone token answers, or None."""
        qid = self._phone.get(token or "")
        if not qid or not self.is_open(qid):
            return None
        return self.views.questions[qid]

    def answer_by_phone(self, token: str, answer: str) -> bool:
        q = self.for_phone(token)
        if q is None:
            return False
        ok = self.answer(q["id"], answer, by="phone")
        if ok:
            self._phone.pop(token, None)
        return ok


def _said_if_failed(task: asyncio.Task) -> None:
    if not task.cancelled() and task.exception() is not None:
        log.error("an answer was not carried out", exc_info=task.exception())
