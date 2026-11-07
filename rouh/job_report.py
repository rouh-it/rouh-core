"""Tell the person what a server job found when it finishes.

Assistant jobs (task 36) already come back on their own: ``Lander`` in
``assistant_job.py`` puts the result on the canvas and has Rouh say it.
Rouh's own server jobs, started with ``delegate_task`` or ``improve_myself``,
did not. Asked on 13 September to count the files in /tmp, Rouh said only
"Started it, the id is 92af5611" and never came back with the count.

This does for them the three things Lander does, in the same order: a card with
the job's own closing words, a note on the job of what was reported, so the same
answer is never given twice, and a short note handed to Rouh to say.

It never talks over the person. The card goes up at once. The spoken report
waits until nobody is speaking, dictating or being answered, and then for a
moment of quiet; a job that finishes while the person is mid-sentence is told
after they are done.
"""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

from . import artifacts, browser_handoff, mail_flow, outbox, run_report, runs
from .crew import CrewManager
from .memory import ANSWERING, answering_in

log = logging.getLogger("rouh.jobs")

#: Assistant jobs are reported by ``assistant_job.Lander``, not here.
ASSISTANT_PROFILE = "assistant"
#: Seconds of quiet - nobody speaking, dictating or being answered - before the
#: report is said.
SETTLE = 2.0
#: After this long without a quiet moment the report is not said at all; its card
#: is on the screen either way.
GIVE_UP = 600.0
POLL = 0.25


def fingerprint(text: str) -> str:
    """A short fixed name for what a job said, so it is reported only once."""
    return hashlib.sha256((text or "").strip().encode("utf-8")).hexdigest()[:16]


def is_test_job(title: str) -> bool:
    """A throwaway job a check started, which is never reported.

    The same marker, matched the same way, as the one ``forget_test_jobs()``
    wipes by. The live orb checks start such jobs, and each one would otherwise
    put a card on the person's canvas, speak into their open tab, and then have
    its record wiped from under the card.
    """
    return (title or "").strip().lower().endswith(CrewManager.TEST_JOB_SUFFIX)


def final_message(payload: dict) -> str:
    """The job's closing message: from the Stop hook, else from its transcript."""
    said = (payload.get("last_assistant_message") or "").strip()
    return said or _last_assistant_text(payload.get("transcript_path"))


def _last_assistant_text(transcript_path: str | None, tail_bytes: int = 400_000) -> str:
    """The last thing the job wrote, read from the tail of its own transcript.

    Claude Code hands the Stop hook its closing message; where it does not, the
    transcript is where it is. Only the tail is read: a long job's transcript
    runs to megabytes.
    """
    if not transcript_path:
        return ""
    try:
        with Path(transcript_path).open("rb") as fh:
            fh.seek(0, 2)
            fh.seek(max(0, fh.tell() - tail_bytes))
            data = fh.read().decode("utf-8", "replace")
    except OSError:
        return ""
    for line in reversed(data.splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if not isinstance(entry, dict) or entry.get("type") != "assistant":
            continue
        message = entry.get("message")
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if isinstance(content, str):
            text = content
        else:
            text = "\n".join(
                block.get("text", "") for block in content or []
                if isinstance(block, dict) and block.get("type") == "text"
            )
        if text.strip():
            return text.strip()
    return ""


def _card_text(text: str, limit: int = 4000) -> str:
    """The closing message with its line breaks kept, since a card draws markdown."""
    text = re.sub(r"\n{3,}", "\n\n", (text or "").strip())
    if len(text) > limit:
        text = text[: limit - 3].rsplit(" ", 1)[0] + "..."
    return text


def _one_line(text: str, limit: int = 1500) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    if len(text) > limit:
        text = text[: limit - 3].rsplit(" ", 1)[0] + "..."
    return text


class JobReporter:
    """Puts a finished server job's result on the screen and has Rouh say it."""

    def __init__(
        self,
        crew,
        memory,
        broadcast: Callable[[dict], Awaitable[Any]],
        announce: Callable[..., Awaitable[Any]],
        busy: Callable[[], bool],
        *,
        settle: float = SETTLE,
        give_up: float = GIVE_UP,
        poll: float = POLL,
    ) -> None:
        self.crew = crew
        self.memory = memory
        self.broadcast = broadcast
        self.announce = announce
        self.busy = busy
        self.settle = settle
        self.give_up = give_up
        self.poll = poll
        self._locks: dict[str, asyncio.Lock] = {}
        self._tasks: set[asyncio.Task] = set()

    def on_event(self, mate, kind: str, payload) -> None:
        """A crew listener. It returns at once, because the hook that called is waiting."""
        meta = getattr(mate, "meta", None) or {}
        if meta.get("profile") == ASSISTANT_PROFILE:
            return None
        status = getattr(mate, "status", "")
        if kind == "stop" and status == "done":
            what = "done"
        elif status == "lost" and kind in ("lost", "session_end"):
            # Found gone by the sweep, or its session ended without it ever
            # saying it had finished.
            what = "lost"
            if kind == "session_end":
                payload = {"reason": "its session ended before it said it had finished"}
        elif kind == "failed" and status == "failed":
            what = "failed"
        else:
            # Still going, stopped to ask something, or stopped by the person.
            return None
        task = asyncio.create_task(self.report(mate.id, what, dict(payload or {})))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return None

    async def report(self, crew_id: str, what: str, payload: dict) -> dict:
        # Which conversation asked for this job, written down when it started
        # and read back now, because by now the person is somewhere else. Its
        # card is filed there and Rouh says it there. A job no conversation
        # started reports in General, and never in the thread on the screen
        # (`runs.reports_to`) - and its report stays on the job's own run
        # instead of being drawn or said there (`runs.report_stays`). A job
        # asked for in General reports there like in any other chat.
        chat = runs.reports_to(crew_id)
        # The card and the note of what was reported are made one at a time per
        # job, so two stops arriving together cannot both report. Saying it is
        # done outside that, since it can wait minutes for a quiet moment.
        lock = self._locks.setdefault(crew_id, asyncio.Lock())
        async with lock:
            with answering_in(chat), outbox.reporting(crew_id):
                made = await self._show(crew_id, what, payload)
        if made.get("note") is None:
            return made
        # A job started for an email reports to the email (`mail_flow.reported`).
        if await mail_flow.reported(crew_id, made["note"]):
            made.pop("note")
            made["spoken"] = False
            return made
        made["spoken"] = await self._say_when_quiet(made.pop("note"), chat)
        log.info("server job %s: %s, card %s, in chat %s, said aloud: %s",
                 crew_id, what, made.get("card_id"), chat,
                 made["spoken"])
        return made

    async def _show(self, crew_id: str, what: str, payload: dict) -> dict:
        mate = self.crew.get(crew_id)
        if mate is None:
            return {"id": crew_id, "kind": "gone", "note": None}
        title = (getattr(mate, "title", "") or "the job").strip()
        if is_test_job(title):
            return {"id": crew_id, "kind": "test job", "note": None}
        reported = (getattr(mate, "meta", None) or {}).get("reported")

        handoff = None
        if what == "done":
            final = final_message(payload)
            if (getattr(mate, "meta", None) or {}).get("boxes") and final:
                # A job handed boxes: whatever they held is taken out before its words go anywhere.
                from . import boxes

                final = await asyncio.to_thread(boxes.redact_run, crew_id, final)
            said = fingerprint(final)
            # A step it stopped at and handed to the live browser, kept on the
            # job while it sits on it, which is what makes its row wait on the
            # person (`runs.crew_run`); every stop writes it, so the next one
            # without a hand-off takes it off again.
            handoff = browser_handoff.find(final)
            with contextlib.suppress(Exception):
                self.crew.set_meta(crew_id, handoff=handoff.as_dict() if handoff else None)
            if reported is not None and (reported == said or not final):
                return {"id": crew_id, "kind": "silent", "note": None}
        if handoff is not None:
            # Not a result: the job is at its prompt, waiting on the person
            # for a step that is theirs (`browser_handoff`). Drawn and said in
            # General too, as anything a job is stopped on is.
            card_id = await self._card(**browser_handoff.card(handoff, title=title), always=True)
            note = browser_handoff.note(handoff, job=crew_id, title=title)
            log.info("server job %s handed a step to the live browser: %s", crew_id,
                     browser_handoff.statement_json(handoff))
            await browser_handoff.tell_phone(handoff, job=crew_id, title=title)
        elif what == "done":
            card_id = await self._card(
                f"Done: {title}",
                [{"block": "text", "text": _card_text(final) or
                  "It finished, and its closing message could not be read."}],
                foot={"ended": run_report.DONE},
            )
            note = (
                f'[A job on this server has finished: "{title}". Its answer is on the '
                f"screen as card {card_id}. Its answer, in its own words: "
                f"{_one_line(final) or 'it said nothing that could be read.'} Give the "
                "person that answer in one or two short sentences, saying which job it "
                "was. Do not start anything.]"
            )
        elif what == "lost":
            said = "lost"
            if reported == said:
                return {"id": crew_id, "kind": "silent", "note": None}
            # What it died of, when the crew could read that off its log or its
            # launcher's record (`crew.death_of`), and otherwise only that it
            # is gone.
            death = (getattr(mate, "meta", None) or {}).get("death") or {}
            cause = _one_line(str(death.get("line") or ""), 240)
            reason = cause or ("It died without reporting back: "
                               + _one_line(str(payload.get("reason") or "its window is gone"),
                                           200))
            card_id = await self._card(
                f"Died: {title}",
                [{"block": "text", "text": reason.rstrip(".") + ". Its card on the run "
                  "list can start it again."}],
                foot={"ended": run_report.FAILED, "why": "it died without reporting back"},
            )
            note = (
                f'[The job "{title}" on this server died without reporting back. {reason}. '
                f"It is on the screen as card {card_id}, and its card on the Metabolism page has "
                "a Restart button. Tell the person in one short sentence which job it was, "
                "that it died, and why. Do not start anything.]"
            )
        else:
            reason = _one_line(str(payload.get("error") or payload.get("message")
                                   or "it did not say why"), 300)
            said = "failed:" + fingerprint(reason)
            if reported == said:
                return {"id": crew_id, "kind": "silent", "note": None}
            card_id = await self._card(
                f"Failed: {title}",
                [{"block": "text", "text": f"It failed: {reason}"}],
                foot={"ended": run_report.FAILED},
            )
            note = (
                f'[The job "{title}" on this server failed: {reason} It is on the screen '
                f"as card {card_id}. Tell the person in one short sentence which job it "
                "was and that it failed. Do not start anything.]"
            )

        with contextlib.suppress(Exception):
            self.crew.set_meta(crew_id, reported=said)
        # And whatever it queued for the person to be emailed, subject, body
        # and id, so Rouh has it in hand in the turn that reports the job
        # (`rouh/outbox.py`). However the job ended: one that queued a note
        # and then failed still queued it.
        if runs.report_stays(crew_id) and handoff is None:
            # Started from no conversation: the job is on its run and nothing
            # is said about it, bar the notes it queued (`runs.report_stays`,
            # `outbox.on_its_own`).
            note = await asyncio.to_thread(outbox.on_its_own, crew_id) or None
        else:
            note = await asyncio.to_thread(outbox.with_notes, crew_id, note)
        return {"id": crew_id, "kind": "handoff" if handoff is not None else what,
                "card_id": card_id, "note": note}

    async def _card(self, title: str, blocks: list[dict], *, description: str = "",
                    always: bool = False, foot: dict | None = None) -> int | None:
        # A report has no description: the one it had only said its title
        # again (Petar, 26 October 2026, fr_4241e4d596a4). A job no
        # conversation started draws nothing: its report stays on the run. What a job is stopped on is not a report, and is drawn in
        # General too (`always`). `foot` is how it ended, under the same four
        # facts every report carries (`run_report.footer`).
        job = outbox.REPORTING.get()
        if runs.report_stays(job) and not always:
            return None
        if foot is not None and job:
            blocks = list(blocks) + await asyncio.to_thread(run_report.footer, job, **foot)
        spec = {"title": title, "description": description, "blocks": blocks}
        card_id = None
        drawn = dict(spec, at=time.time())
        with contextlib.suppress(Exception):
            # Through the one door every card goes through, so a job's result
            # is kept the same way a card the model drew is and is still there
            # after a reload (`rouh/artifacts.keep`). Which thread it belongs
            # to is on the report already (`memory.ANSWERING`).
            card_id, drawn = await asyncio.to_thread(
                artifacts.keep, self.memory, spec)
        said = {"type": "ui", "spec": drawn}
        # Drawn on the screens standing in that thread and on no other: the
        # page throws away anything naming a conversation it is not looking at
        # (`handleMessage` in app.js).
        if ANSWERING.get():
            said["chat"] = ANSWERING.get()
        with contextlib.suppress(Exception):
            await self.broadcast(said)
        return card_id

    async def _say_when_quiet(self, note: str, chat: str = "") -> bool:
        """Hand Rouh the note once nobody has been speaking or answered for a moment.

        `chat` is the thread it is said in: the one the job was started from.
        Waiting for quiet is about the person and not about the thread, so it
        is still every conversation that has to be quiet before a job talks.
        """
        deadline = time.monotonic() + self.give_up
        quiet_since: float | None = None
        while time.monotonic() < deadline:
            if self._busy():
                quiet_since = None
            else:
                now = time.monotonic()
                if quiet_since is None:
                    quiet_since = now
                if now - quiet_since >= self.settle:
                    spoken = False
                    with contextlib.suppress(Exception):
                        spoken = bool(await self.announce(note, chat))
                    if spoken:
                        return True
                    # No tab to say it in, or one that started answering after
                    # all: keep waiting for the next quiet moment.
                    quiet_since = None
            await asyncio.sleep(self.poll)
        log.info("a server job's result was not said aloud; its card is on the screen")
        return False

    def _busy(self) -> bool:
        try:
            return bool(self.busy())
        except Exception:
            return True
