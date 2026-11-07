"""Every run, from being asked for to ending: the part of the program that acts.

What it does, in the order a run meets it:

* :meth:`Runs.request` writes ``run.requested`` and wakes the scheduler.
* :meth:`Runs.launch`, called by the scheduler, makes the run's checkout,
  writes its hook settings and brief into it, and starts its terminal.
* :meth:`Runs.on_hook` takes every hook Claude Code sends. A tool call is
  decided (``rules.decide``), asked about if it must be, and answered. The end
  of a turn lands the run's work on main, and can hand Claude a follow-up.
* :meth:`Runs.take`, :meth:`Runs.type_in` and :meth:`Runs.give` are taking over
  a run and handing it back, step 07's six steps.
* :meth:`Runs.stop` ends a run; :meth:`Runs._on_exit` hears it end, by itself
  or not, and decides whether it is started again.
* :meth:`Runs.adopt_all` reconnects to every run after the program restarts.

Nothing here keeps the truth. What happened goes into the list, and what a
run's state is comes back from the views.

**Every tool call is decided, three ways over.** On the server on 14
September, twice, a run's first tool call never reached the program through
the PreToolUse hook, and the cause was not found. So a call is decided by the
program on its first chance, PreToolUse; if that never arrives, on its second,
PermissionRequest, which Claude Code sends whenever it is about to ask on its
own screen; and the deny rules in the run's settings bind even when neither is
heard. A call that still finishes without the program having decided it is
written down as ``hook.missed``, so it is never silent.
"""
from __future__ import annotations

import asyncio
import contextlib
import fcntl
import json
import logging
import os
import pwd
import secrets
import shutil
import signal
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import agents, billing, codex_signin, codexhome, drops, rules, sealed
from .documents import DocumentsError
from .hookbodies import CLOSING_TEXT
from .terminals import read_exit, session_alive
from .views import ENDED, OVER_MEMORY, delivered, ended_state, work_left

if TYPE_CHECKING:  # pragma: no cover
    from .program import Program

log = logging.getLogger("one.runs")

#: Claude Code's own questions on its screen that only a terminal can answer.
TERMINAL_QUESTIONS = frozenset({"permission_prompt", "elicitation_dialog", "agent_needs_input"})

#: The pause between clearing Claude Code's box and pasting a message into it.
#: Sent in the same burst, Claude Code reads the two keys that clear the box as
#: part of the paste: it takes them out again as "2 invisible characters",
#: leaves the message in its box to be reviewed, and ignores the Enter. Measured
#: against Claude Code 2.1.280 on 30 September 2026 (fr_8ced13df88e4): every
#: message between about 100 and 1,000 characters was left unsent that way, and
#: with this pause every one of them was sent.
CLEAR_PAUSE = 0.3
#: What a restart reads out of the list for each run it adopts: the calls
#: already decided, and what became of its messages (Runs.messages_left).
ADOPT_KINDS = frozenset({
    "tool.opened", "permission.decided", "message.sent", "message.queued", "message.failed",
    "agent.prompted", "agent.stopped", "run.restarted", "run.ended"})


#: The list's entries for the program itself starting and stopping.
PROGRAM_KINDS = frozenset({"program.started", "program.stopping"})


def why_program_went(last: list[dict[str, Any]], *,
                     contained: bool | None = None) -> str:
    """What took the last program down, in words, for a run that went down with it.

    ``last`` is the list's last few ``PROGRAM_KINDS`` entries, oldest first.
    The last is the program that has just started; the one before it is the
    program before, which either wrote ``program.stopping`` (it was asked to
    stop: a deploy, which in the containers restarts the worker container with
    every run in it) or did not (it went down without stopping: a crash, or
    the container or the machine stopped under it). The ``program.started``
    before that says which commit it ran, so a deploy can be named as one.
    ``contained`` is whether the program runs in a container, where stopping
    it restarts the container and so ends every run in it; on a server of its
    own the runs' holders outlive it, and losing one there is something else.
    """
    if contained is None:
        contained = os.path.exists("/.dockerenv")
    if not last or last[-1].get("kind") != "program.started":
        return "the program went down while it was away"
    onto = (last[-1].get("body") or {}).get("commit")
    before = last[-2] if len(last) >= 2 else None
    if before is None or before.get("kind") != "program.stopping":
        return "the program went down without stopping (a crash, or its container or machine stopped)"
    at = str(before.get("at") or "")[11:16]
    said = f"the program was stopped at {at} UTC" if at else "the program was stopped"
    was = (last[-3].get("body") or {}).get("commit") if len(last) >= 3 else None
    if onto and was and onto != was:
        said += f" for the deploy of {onto}"
    return said + (", which restarts the worker container" if contained else "")


#: How long Claude Code is given to say it took a typed message, through its
#: UserPromptSubmit hook, before Enter is pressed once more, and then again
#: before the message is called not delivered. Twice this and the pauses around
#: the paste stay inside the ten seconds Rouh waits for an answer.
TAKE_WAIT = 4.0


def hours(seconds: float) -> str:
    """A run's lifetime in words: "6 hours", "90 minutes"."""
    if seconds >= 3600 and seconds % 3600 == 0:
        n = int(seconds // 3600)
        return f"{n} hour{'s' if n != 1 else ''}"
    n = max(1, round(seconds / 60))
    return f"{n} minute{'s' if n != 1 else ''}"


class RunError(ValueError):
    """Something asked of a run that cannot be done, said in words a person can act on."""


class Takeover:
    """A person holding a run's keyboard.

    ``direct`` is typing onto the run's own screen, from a browser page (D46):
    Claude saw every key as it came, so no note about them follows.
    """

    def __init__(self, device: str, asked_by: str, *, direct: bool = False) -> None:
        self.device = device
        self.asked_by = asked_by
        self.direct = direct
        self.started = time.time()
        self.last_key = self.started
        self.keys = bytearray()
        self.unrecorded = bytearray()
        self.prompts: list[str] = []


class _RunInteraction:
    """Messages and keyboard ownership for a run, including restart recovery.

    Runs supplies the program, mutable state and lifecycle operations. Keeping
    these methods on the same instance preserves its queues, delivery events
    and takeover records across hooks, terminal exits and cancellation.
    """

    # -- messages ------------------------------------------------------------------------

    async def say(self, run_id: str, text: str, *, by: str,
                  files: list[tuple[str, str, bytes]] | None = None) -> str:
        """Give a run of Claude Code a message. Returns sent, queued or carried on.

        ``files`` go with it, as (name, type, bytes): a picture the person
        dropped into a chat with Rouh and asked to be handed to this run.
        Rouh's own copy is in a folder no run can read, so a path to it was a
        picture that never arrived (fr_40ca307722f1, 29 September 2026). They
        are put where a file dropped on the run's terminal goes, its own
        ``drops`` folder (``keep_drops``), and their paths end the message.
        """
        run = self._run(run_id)
        text = (text or "").strip()
        if run["kind"] != "agent":
            raise RunError("only a run of Claude Code takes messages")
        if not text:
            raise RunError("the message is empty")
        if files:
            kept = await self._keep_files(run, files, by=by)
            text = f"{text}\n\n{drops.typed([k['path'] for k in kept]).strip()}"
        if run["state"] in ENDED:
            if not run.get("session_id") or not run.get("cwd"):
                raise RunError("that run cannot be carried on: it never got as far as a conversation")
            self._can_resume(run)
            self._unarchive(run_id, by=by, why="it was carried on with a message")
            self.list.append("run.restarted", run=run_id, by=by, body={"why": "carried on"})
            self.list.append("message.sent", run=run_id, by=by, body={
                "text": agents.plain(text, 4000), "via": "carried on"})
            self._spawn(self.launch(run_id, resume=True, prompt=text))
            return "carried on"
        if run_id in self.takeovers or run["state"] != "idle" or run_id in self._typing:
            self.pending.setdefault(run_id, []).append(text)
            self.list.append("message.queued", run=run_id, by=by, body={"text": agents.plain(text, 4000)})
            self._unarchive(run_id, by=by, why="it was given a message to work on")
            return "queued"
        terminal = self.p.terminals.get(run_id)
        if terminal is None:
            raise RunError("that run has no terminal right now")
        why = await self._type_message(run_id, terminal, text, by=by, via="typed")
        if why:
            raise RunError(f"{why} Nothing was sent to it: send it again.")
        self._unarchive(run_id, by=by, why="it was given a message to work on")
        return "sent"

    def _unarchive(self, run_id: str, *, by: str, why: str) -> None:
        """Bring a run back into the list, because it is about to work again.

        Archiving is the person saying they are done with a run, and it stops
        the run. A message afterwards says the opposite, so the run comes back
        rather than working where nobody looks. On 27 September 2026 Jarvis
        carried on run 5567e3f6, archived the evening before, with a follow-up;
        it did the work, finished its turn and then sat at its prompt, hidden,
        for a week: the list left it out because it was archived, and nothing
        archived it again because it already was, so nothing ever stopped it.
        Back in the list it is an ordinary open run, closed the ordinary way.
        """
        if self.views.runs.get(run_id, {}).get("archived"):
            self.list.append("run.archived", run=run_id, by=by, body={"on": False, "why": why})

    async def carry_on(self, run_id: str, *, by: str) -> None:
        """Start the person's own session again after it ended, in the same conversation."""
        run = self._run(run_id)
        if not run.get("interactive"):
            raise RunError("a run is carried on by sending it a message: one say")
        if run["state"] not in ENDED:
            return
        if not run.get("cwd"):
            raise RunError("that session never got as far as its checkout, so there is nothing "
                           "to carry on")
        self._can_resume(run)
        self._unarchive(run_id, by=by, why="it was carried on")
        self.list.append("run.restarted", run=run_id, by=by, body={"why": "carried on"})
        self._spawn(self.launch(run_id, resume=True))

    @staticmethod
    def _codex_conversation(run: dict[str, Any]) -> str | None:
        """The Codex conversation a run had, which ``codex resume`` carries on.

        Only the one Codex itself named in its SessionStart hook: the id a run
        of Codex is started with is the program's own and Codex never sees it,
        so until that hook arrives (and gives the run its transcript) there is
        no conversation of Codex's to go back to.
        """
        if agents.engine_of(run.get("engine")) != "codex" or not run.get("transcript"):
            return None
        return str(run.get("session_id") or "") or None

    def _can_resume(self, run: dict[str, Any]) -> None:
        """Refuse, saying why, to carry on a run of Codex that has no conversation to go back to.

        Never a fresh Codex in its place: it would know nothing of what the
        run had done, and answer a question about it as if it were new
        (fr_21b395a23dcf, 27 October 2026).
        """
        if agents.engine_of(run.get("engine")) == "codex" and not self._codex_conversation(run):
            raise RunError("that run of Codex cannot be carried on: Codex never said which "
                           "conversation it was, so there is none to go back to. Start a new run "
                           "instead.")

    async def _paste(self, terminal, text: str) -> None:
        # Whatever half-typed line is in Claude Code's box goes first, or the
        # message would be glued onto the end of it. On its own, and a moment
        # before the paste, or it is read as part of the paste (CLEAR_PAUSE).
        await terminal.type(b"\x05\x15")
        await asyncio.sleep(CLEAR_PAUSE)
        await terminal.paste(text)

    async def _type_message(self, run_id: str, terminal, text: str, *, by: str, via: str,
                            sent: bool = True) -> str | None:
        """Type a message at a run's prompt, and see Claude Code take it.

        None when it did, and then ``message.sent`` says so (unless ``sent`` is
        False, for a follow-up whose entry was written already). Otherwise the
        reason, written down as ``message.failed``, and the message is not left
        in its box. A message typed and never taken used to be written down as
        sent all the same: the run was shown as working on it for good, it sat
        unsent in Claude Code's box, and whatever was queued behind it waited
        for a turn that never ended (fr_8ced13df88e4, 30 September 2026).

        Taken means Claude Code's UserPromptSubmit hook arrived. When it has
        not, Enter is pressed once more, which is also what sends a message
        Claude Code is holding for review.
        """
        taken = self._typing[run_id] = asyncio.Event()
        try:
            await self._paste(terminal, text)
            for again in (True, False):
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(taken.wait(), TAKE_WAIT)
                if taken.is_set() or not again or self.p.terminals.get(run_id) is not terminal:
                    break
                await terminal.type(b"\r")
        finally:
            if self._typing.get(run_id) is taken:
                del self._typing[run_id]
        if taken.is_set():
            if sent:
                self.list.append("message.sent", run=run_id, by=by, body={
                    "text": agents.plain(text, 4000), "via": via, "taken": True})
            return None
        if self.p.terminals.get(run_id) is not terminal:
            why = "The run's terminal went away before it took the message."
        else:
            why = "It did not take the message: it never started a turn on it."
            if await self._clear_box(terminal, text):
                why += " It was taken out of its box again."
        self.list.append("message.failed", run=run_id, by=by, body={
            "text": agents.plain(text, 4000), "via": via, "why": why})
        return why

    @staticmethod
    def in_box(screen: str, text: str) -> bool:
        """Whether Claude Code's box on ``screen`` holds some of ``text``.

        The box is the lines after the last one that starts with its prompt
        mark, up to the rule under it. A long message is scrolled inside it, so
        what shows can be any stretch of the message, wrapped anywhere.
        """
        lines = screen.splitlines()
        starts = [i for i, line in enumerate(lines) if line.startswith("\u276f")]
        if not starts:
            return False
        box: list[str] = []
        for line in lines[starts[-1]:]:
            if box and line.lstrip().startswith("\u2500"):
                break
            box.append(line.lstrip("\u276f").strip())
        shown = " ".join(" ".join(box).split())
        whole = " ".join(text.split())
        if len(shown) < 12:
            return False
        # A wrapped word may be cut at the edge, so a stretch from the middle.
        middle = shown[len(shown) // 4: len(shown) // 4 + 40] if len(shown) > 60 else shown[:40]
        return middle in whole

    async def _clear_box(self, terminal, text: str) -> bool:
        """Take a message that was never sent out of Claude Code's box.

        Only when the box can be seen to hold it: Escape twice clears the whole
        box, where the keys that clear a line leave every line but the last of
        a message with several, but on an empty box it opens the list of
        earlier prompts instead. Whether it worked is read back off the screen.
        """
        if not self.in_box(terminal.screen_text(), text):
            return False
        for _ in range(2):
            await terminal.type(b"\x1b")
            await asyncio.sleep(CLEAR_PAUSE)
        await asyncio.sleep(0.5)
        return not self.in_box(terminal.screen_text(), text)

    # -- taking over and handing back --------------------------------------------------------

    def take(self, run_id: str, device: str, *, asked_by: str, direct: bool = False) -> None:
        run = self._run(run_id)
        if run["state"] in ENDED or run["state"] == "queued":
            raise RunError("only a run that is going can be taken over")
        current = self.takeovers.get(run_id)
        if current is not None:
            if current.device == device:
                return
            raise RunError(f"{self.p.device_name(current.device)} is already driving it")
        self.takeovers[run_id] = Takeover(device, asked_by, direct=direct)
        self.list.append("run.taken-over", run=run_id, by=asked_by, body={"device": device})

    def driver(self, run_id: str) -> str | None:
        current = self.takeovers.get(run_id)
        return current.device if current else None

    async def type_in(self, run_id: str, device: str, data: bytes, *,
                      paste: bool = False) -> None:
        """Keys into a run's terminal. ``paste`` puts them in as one paste.

        The difference is not cosmetic. Claude Code only turns a file's path
        into an attachment when the path arrives as a paste: measured against
        Claude Code 2.1.263 on 16 September, the same path sent key by key
        stays a path on its screen and the picture never reaches the model,
        while pasted it becomes [Image #1] (D52). Nothing is submitted either
        way: the person presses Enter.
        """
        current = self.takeovers.get(run_id)
        if current is None or current.device != device:
            raise RunError("you are not driving this run: take it first")
        terminal = self.p.terminals.get(run_id)
        if terminal is None:
            raise RunError("that run has no terminal right now")
        current.last_key = time.time()
        # What is written down is what was put in, never the markers around it.
        current.keys += data
        current.unrecorded += data
        if paste:
            await terminal.paste(data.decode("utf-8", "replace"), submit=False)
        else:
            await terminal.type(data)
        if len(current.unrecorded) >= 200 or b"\r" in data:
            self._record_keys(run_id, current)

    async def scroll(self, run_id: str, device: str, lines: int, col: int, row: int) -> None:
        """The mouse wheel over a run's terminal (D51)."""
        terminal = self._under_the_mouse(run_id, device)
        data = terminal.wheel(lines, col, row)
        if data is None:
            raise RunError("what runs in this terminal does not scroll with the mouse")
        if data:
            await terminal.type(data)

    async def mouse(self, run_id: str, device: str, data: bytes) -> None:
        """What the mouse did over a run's terminal, as a page's terminal
        reported it (D51): in Claude Code's fullscreen renderer a click moves
        the cursor or opens a result, and a drag selects and copies."""
        terminal = self._under_the_mouse(run_id, device)
        if len(data) > 8192 or not terminal.is_mouse(data):
            raise RunError("only what the mouse did is sent this way")
        if not terminal.wants_mouse:
            raise RunError("what runs in this terminal does not use the mouse")
        await terminal.type(data)

    def _under_the_mouse(self, run_id: str, device: str):
        """The run's terminal, for the mouse. The mouse is not typing: it needs
        nobody's keyboard and nothing of it is written down. While somebody
        else has the keyboard the screen is theirs, and it is refused."""
        current = self.takeovers.get(run_id)
        if current is not None and current.device != device:
            raise RunError(f"{self.p.device_name(current.device)} has its keyboard")
        terminal = self.p.terminals.get(run_id)
        if terminal is None:
            raise RunError("that run has no terminal right now")
        return terminal

    def flush_keys(self) -> None:
        """Write down keys typed but not yet recorded. Called on a beat by the program."""
        for run_id, current in list(self.takeovers.items()):
            self._record_keys(run_id, current)

    #: A browser holding a run's keyboard with no key for this long gives it
    #: back (D46): messages for the run and a terminal's take wait while it is
    #: held, and a browser tab can sleep. The next key takes it again.
    QUIET = 120.0

    async def hand_back_quiet(self) -> None:
        """Give back every run a browser has held with no key for QUIET seconds."""
        now = time.time()
        for run_id, current in list(self.takeovers.items()):
            if current.direct and now - current.last_key > self.QUIET:
                await self.give(run_id, by="program")

    def _record_keys(self, run_id: str, current: Takeover) -> None:
        if current.unrecorded:
            text = agents.typed_text(bytes(current.unrecorded), 2000)
            current.unrecorded.clear()
            # Only what a person can read: keys that were all mouse reports or
            # a terminal's answers about itself leave nothing to write down.
            if text:
                self.list.append("input.typed", run=run_id, by=current.device, body={"text": text})

    async def give(self, run_id: str, *, by: str) -> None:
        current = self.takeovers.pop(run_id, None)
        if current is None:
            return
        self._record_keys(run_id, current)
        terminal = self.p.terminals.get(run_id)
        screen = terminal.screen_text(last=40) if terminal else ""
        typed = agents.typed_text(bytes(current.keys))
        minutes = (time.time() - current.started) / 60
        self.list.append("run.handed-back", run=run_id, by=by, body={
            "device": current.device, "typed": typed[-3000:], "prompts": current.prompts[-10:],
            "screen": agents.plain(screen, 6000), "minutes": round(minutes, 2)})
        run = self.views.runs.get(run_id)
        if not run or run["kind"] != "agent" or run["state"] in ENDED:
            return
        messages = list(self.pending.pop(run_id, []))
        # In the person's own session the typing was the session itself, and
        # typed onto the run's own screen from a browser Claude saw every key
        # (D46), so there is nothing to tell Claude about it.
        if (typed or current.prompts) and not run.get("interactive") and not current.direct:
            messages.insert(0, agents.hand_back_message(
                device=self.p.device_name(current.device), minutes=minutes, typed=typed,
                prompts=current.prompts, screen=screen))
        if not messages:
            return
        text = "\n\n".join(messages)
        if run["state"] == "idle" and terminal is not None:
            await self._type_message(run_id, terminal, text, by="program", via="handed back")
        else:
            self.pending.setdefault(run_id, []).append(text)

    def _not_handed_over(self, run_id: str, why: str) -> None:
        """Write down the messages queued for a run that will now never get them."""
        left = self.pending.pop(run_id, None)
        if left:
            self.list.append("message.failed", run=run_id, by="program", body={
                "text": agents.plain("\n\n".join(left), 4000), "via": "queued",
                "why": f"It was queued for the end of the run's turn, and {why}."})

    @staticmethod
    def messages_left(entries: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, list[str]]:
        """What a run's messages were left as, out of its entries in the list.

        The message typed at its prompt that Claude Code never took, if the
        last one was, and the messages still queued for the end of its turn.
        The queue is held in memory only, so a restart of the program lost it
        without a word, and a message typed and never taken was written down as
        sent until 30 September 2026 (fr_8ced13df88e4).
        """
        untaken: dict[str, Any] | None = None
        queued: list[str] = []
        for entry in entries:
            kind, body = entry.get("kind"), entry.get("body") or {}
            if kind == "message.sent":
                if body.get("via") in ("typed", "handed back") and not body.get("taken"):
                    untaken = entry
                if body.get("via") in ("end of turn", "handed back"):
                    queued = []
            elif kind == "message.queued":
                queued.append(str(body.get("text") or ""))
            elif kind == "message.failed":
                if body.get("via") == "queued":
                    queued = []
                if body.get("left"):
                    untaken = None
            elif kind in ("agent.prompted", "tool.opened", "agent.stopped", "run.restarted",
                          "run.ended"):
                untaken = None
                if kind == "run.ended":
                    queued = []
        return untaken, [q for q in queued if q]

    def _messages_left(self, run: dict[str, Any], terminal,
                       entries: list[dict[str, Any]]) -> None:
        """Put right the messages a run held when the program came back.

        A message it never took is taken out of its box and written down as
        not delivered, and the run, shown as working on it, is at its prompt
        again. Messages queued for the end of a turn still going are queued
        again; queued behind a message it never took, or for a run already at
        its prompt, no turn is coming to hand them over, and they are written
        down as not delivered rather than sent hours late.
        """
        if run["kind"] != "agent":
            return
        untaken, queued = self.messages_left(entries)
        stuck = untaken is not None and run["state"] == "working"
        if queued and run["state"] != "idle" and not stuck:
            self.pending[run["id"]] = queued
        elif queued:
            self.pending[run["id"]] = queued
            self._not_handed_over(run["id"], "no turn was coming to end, so it never was")
        if stuck:
            self._spawn(self._left_in_box(run["id"], terminal, str(untaken["body"].get("text") or "")))

    async def _left_in_box(self, run_id: str, terminal, text: str) -> None:
        # The screen is drawn again from the end of its log as it is adopted.
        await asyncio.sleep(1.0)
        why = "It never took this message: it was left unsent in its box"
        why += (", and has been taken out of it now." if await self._clear_box(terminal, text)
                else ".")
        self.list.append("message.failed", run=run_id, by="program", body={
            "text": agents.plain(text, 4000), "via": "typed", "why": why, "left": True})


class Runs(_RunInteraction):
    def __init__(self, program: "Program") -> None:
        self.p = program
        self.s = program.settings
        self.docs = program.documents
        #: Each run's hook key. A hook that does not carry its run's key is not
        #: that run's, and is ignored.
        self.keys: dict[str, str] = {}
        #: Messages for a run of Claude Code, handed over at the end of its turn.
        self.pending: dict[str, list[str]] = {}
        #: Runs a message is being typed into, each with what is set when
        #: Claude Code says it took it (its UserPromptSubmit hook).
        self._typing: dict[str, asyncio.Event] = {}
        self.fix_tries: dict[str, int] = {}
        #: Runs already asked once to finish what they left uncommitted, so a
        #: run that means it when it says the tests will not pass is asked once
        #: and then believed.
        self.finish_asks: dict[str, int] = {}
        #: Runs being stopped on purpose, and how.
        self.stopping: dict[str, str] = {}
        #: The one task asking each run to leave, while it is still asking.
        #: Not one of ``_tasks``: the program waits for these as it stops, so
        #: a deploy does not cut a stop short (``_finish_closing``).
        self.closing: dict[str, asyncio.Task] = {}
        #: Runs that would not leave when asked, and what it took in the end.
        #: Kept until the run ends, so the list says so.
        self.forced: dict[str, str] = {}
        self.takeovers: dict[str, Takeover] = {}
        #: The tool calls the program decided, by run, so one that finishes
        #: without having been decided can be told apart.
        self._decided: dict[str, set[str]] = {}
        #: Calls decided at the second chance, which carries no call id: known
        #: by their tool and input until they finish, each with the id the
        #: program gave it so its opening and closing entries pair up.
        self._caught: dict[str, list[tuple[int, str]]] = {}
        self._session_seen: set[str] = set()
        #: Runs of Codex started as ``codex resume``, until their SessionStart
        #: hook says the conversation was found: one that exits before that
        #: could not be carried on, and is not started again in a loop.
        self._codex_resuming: set[str] = set()
        #: Runs whose checkout is being tidied this instant (``_tidy``).
        self._tidying: set[str] = set()
        #: What a Codex run is told about how it works, until its SessionStart
        #: hook arrives to carry it: Codex has no way to be given it up front.
        self._context: dict[str, str] = {}
        #: The agent instructions the last run was given, for a run that starts
        #: while Rouh is not answering (`_instructions`). In memory only.
        self._last_instructions = ""
        self._tasks: set[asyncio.Task] = set()
        self._launching: set[str] = set()
        #: Each open run of Codex's session file, read for turns that failed
        #: (billing.Watcher): Codex sends no hook when one does.
        self.watchers: dict[str, billing.Watcher] = {}
        #: Runs being asked to leave so they can start again on the API key,
        #: and how they start again once they have gone.
        self.switching: dict[str, dict[str, Any]] = {}
        #: The one-time key each run that was handed boxes collects them with, until it starts.
        #: In memory only, never in the list: a program started again before the run starts
        #: has none, and the run fails to start saying so (``_hand_boxes``).
        self._box_keys: dict[str, str] = {}
        program.questions.handle(billing.ASK_API, self._answered_api)
        program.questions.handle(billing.ASK_FRESH, self._answered_fresh)

    def _home(self, run: dict[str, Any]) -> str:
        """The home folder of the user the run works as."""
        return _home_of(self.s.space(run.get("space")).user)

    @property
    def list(self):
        return self.p.list

    @property
    def views(self):
        return self.p.views

    def _spawn(self, coro) -> asyncio.Task:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._finished)
        return task

    def _finished(self, task: asyncio.Task) -> None:
        self._tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            log.error("a run task failed", exc_info=task.exception())

    def _run(self, run_id: str) -> dict[str, Any]:
        run = self.views.runs.get(run_id or "")
        if run is None:
            raise RunError(f"there is no run {run_id!r}")
        return run

    # -- asking for a run ------------------------------------------------------------

    def request(self, opts: dict[str, Any], *, by: str, surface: str) -> str:
        run_id = secrets.token_hex(4)
        opts = dict(opts)
        box_key = opts.pop("box_key", None)
        if box_key and opts.get("boxes"):
            self._box_keys[run_id] = str(box_key)
        # The brief is kept whole: it is read back from this entry when the run starts.
        self.list.append("run.requested", run=run_id, by=by, body={**opts, "surface": surface},
                         whole=("brief",))
        self.p.scheduler.wake()
        return run_id

    # -- starting ----------------------------------------------------------------------

    def launching(self, run_id: str) -> bool:
        return run_id in self._launching

    async def launch(self, run_id: str, *, resume: bool = False, prompt: str | None = None,
                     codex_session: str | None = None, fresh: bool = False) -> None:
        """Start a run the scheduler let through. Failing to start ends it, saying why.

        ``codex_session`` carries a run of Codex on in that conversation
        (``codex resume``) rather than in a new one. Started again with
        ``resume`` and none given, a run of Codex goes back to the
        conversation it had, as Claude Code's ``--resume`` does; ``fresh``
        is the one case that starts a new one, because the person said so.
        """
        # A new process says who it is again when it is up, and its state follows.
        self._session_seen.discard(run_id)
        self._launching.add(run_id)
        try:
            run = self._run(run_id)
            if run["kind"] == "shell":
                await self._launch_shell(run)
            else:
                await self._launch_agent(run, resume=resume, prompt=prompt,
                                         codex_session=codex_session, fresh=fresh)
        except Exception as exc:
            log.exception("run %s could not start", run_id)
            self.list.append("run.ended", run=run_id, body={
                "how": "failed-to-start", "code": None, "why": f"{type(exc).__name__}: {exc}"[:600]})
            run = self.views.runs.get(run_id)
            if run is not None:
                await self._shred_boxes(run)
            self.p.scheduler.wake()
        finally:
            self._launching.discard(run_id)

    async def _checkout(self, run: dict[str, Any]) -> dict[str, Any]:
        """The run's folder: the one it has, or a fresh one in its space."""
        cwd = run.get("cwd")
        own = run.get("own") or (f"{cwd}/.one" if cwd else None)
        if cwd and os.path.isdir(cwd) and own and os.path.isdir(os.path.dirname(own)):
            return {"cwd": cwd, "branch": run.get("branch"), "repo": run.get("repo"),
                    "target": run.get("target"), "flow": run.get("flow"), "own": own,
                    "base_sha": run.get("base_sha")}
        got = await self.docs.make_checkout(run["id"], run["title"], run["space"], again=run)
        where = {name: got.get(name)
                 for name in ("cwd", "branch", "repo", "target", "flow", "own", "base_sha")}
        if cwd:
            # Its checkout was removed once its work was saved. The
            # conversation is Claude Code's own and carries on; the files
            # start again from where its work was saved.
            self.list.append("run.checkout", run=run["id"], body=where)
        return where

    async def _launch_agent(self, run: dict[str, Any], *, resume: bool, prompt: str | None,
                            codex_session: str | None = None, fresh: bool = False) -> None:
        run_id, space = run["id"], run["space"]
        engine = agents.engine_of(run.get("engine"))
        if engine == "codex" and resume and not codex_session and not fresh:
            # Until 27 October 2026 this was a new Codex, told only that it
            # had been started again: a run closed and then asked what it had
            # done opened a blank terminal that knew nothing (fr_21b395a23dcf).
            codex_session = self._codex_conversation(run)
            if not codex_session:
                raise RunError("Codex never said which conversation it was, so it could not "
                               "be carried on, and no new one was started in its place")
        if codex_session:
            self._codex_resuming.add(run_id)
        pays = billing.billing_of(engine, run.get("billing"))
        if pays == billing.API and not self.p.api_key.available():
            # Never the subscription instead: the person asked for the key.
            raise RunError("it is to be billed to the OpenAI API key, and no key has reached "
                           "the program, so it was not started and nothing was billed")
        if engine == "codex" and pays == billing.SUBSCRIPTION and _codex_signed_in(self._home(run)) is False:
            # Without its login Codex opens on its "Sign in with ChatGPT" screen and waits there, sends
            # no hook, and was stopped a minute later as "ungoverned": every nightly refactoring run in
            # the containers from 1 to 5 November 2026 ended that way, saying nothing of the reason.
            # Since 6 November 2026 it says one line, with where the button is, and the phone is
            # told once until Codex is signed in again (codex_signin.py), not once a run.
            self.p.codex_signin.tell_lost()
            raise RunError(codex_signin.needs_line(self.s.public_url))
        where = await self._checkout(run)
        cwd, branch = where["cwd"], where["branch"]
        if not resume:
            await self._hand_boxes(run, cwd)
        key = self._key_for(run_id)
        settings_path = f"{where['own']}/settings.json"
        if engine == "claude":
            await self.docs.write(settings_path, json.dumps(
                agents.hook_settings(run_id, key, self.s.hook_url,
                                     long_timeout=self.s.hook_timeout,
                                     access=self.s.access),
                indent=2), mode="600", space=space)
        # What the brief says about who the run works as and where its work
        # is saved.
        told = {"access": self.s.access,
                "user": self.s.space(space).user or pwd.getpwuid(os.getuid()).pw_name,
                "target": where["target"], "flow": where["flow"], "engine": engine}
        # The agent instructions first, before anything else the run is told:
        # read from Rouh's database as it starts (`_instructions`).
        append = await self._instructions(run) or None
        if run.get("interactive"):
            # The person's own session: they type every prompt, so how the run
            # works is added to Claude Code's own instructions instead.
            told_how = agents.session_brief(space=space, run_id=run_id, cwd=cwd,
                                            branch=branch,
                                            code_repo=str(Path(self.s.spaces_dir) / "rouh"),
                                            **told)
            append = f"{append}\n\n---\n\n{told_how}" if append else told_how
            if resume and run.get("session_id"):
                session, resume_id = None, run["session_id"]
            else:
                session, resume_id = str(uuid.uuid4()), None
            first = prompt
        elif resume:
            session, resume_id = None, run.get("session_id")
            first = prompt or agents.RESTARTED
        else:
            brief = agents.compose_brief(run["brief"], space=space,
                                         surface=run.get("surface"), run_id=run_id, cwd=cwd,
                                         branch=branch, signups=bool(run.get("signups")),
                                         code_repo=str(Path(self.s.spaces_dir) / "rouh"),
                                         **told)
            brief_path = f"{where['own']}/brief.md"
            await self.docs.write(brief_path, brief, mode="600", space=space)
            session, resume_id = str(uuid.uuid4()), None
            first = agents.first_prompt(brief, brief_path)
        mcp_config = await self.docs.seed_trust(cwd, bypass=self.s.access == "full",
                                                space=space, engine=engine)
        if engine == "codex":
            # Codex has no flag for extra instructions and no setting for a
            # file of them, so how this run works is given to it as the answer
            # to its SessionStart hook, which puts it in front of the model as
            # a developer message. It is kept here until that hook arrives.
            self._context[run_id] = append or ""
            args = agents.codex_args(
                model=run.get("model") or self.s.codex_model, run_id=run_id,
                hook_url=self.s.hook_url, poster=str(self.s.codexhook_path),
                python=self.s.asuser_python, prompt=first,
                long_timeout=self.s.hook_timeout, access=self.s.access,
                effort=run.get("effort") or self.s.agent_effort(engine), billing=pays,
                api_base_url=self.s.codex_api_base_url, resume_session=codex_session,
                browser_port=int(run.get("browser_port") or 0))
        else:
            args = agents.claude_args(
                model=run.get("model") or self.s.model, settings_path=settings_path,
                session_id=session, resume=resume_id, run_id=run_id, prompt=first,
                debug_file=f"{where['own']}/claude-debug.log" if self.s.claude_debug else None,
                access=self.s.access, effort=run.get("effort") or self.s.agent_effort(engine),
                mcp_config=mcp_config, append_system_prompt=append)
        key_file = ""
        if engine == "codex" and pays == billing.API:
            # The key goes to the run through a file of its own user's, mode
            # 600, which asuser.py reads and deletes before Codex starts: it is
            # never an argument, and never an entry in the list.
            key_file = f"{where['own']}/{billing.KEY_FILE}"
            await self.docs.write(key_file, self.p.api_key.get(), mode="600", space=space)
        if not resume:
            self.list.append("run.started", run=run_id,
                             body={**where, "session_id": session, "engine": engine,
                                   "billing": pays})
        await self._hold(run_id, self.docs.agent_argv(run_id, cwd, args, space=space,
                                                      engine=engine, hook_key=key,
                                                      api_key_file=key_file,
                                                      browser_port=int(run.get("browser_port") or 0)))
        if engine == "codex":
            self._spawn(self._prove_governed(run_id))

    async def _hand_boxes(self, run: dict[str, Any], cwd: str) -> None:
        """Put the boxes the person handed this run in its folder, before the agent starts.

        Collected from Rouh once, with the key the run was started with (``agents.collect_boxes``),
        and written as the run's own user at ``.secrets/box-<n>`` (``sealed.py``). What is in them
        is held here only for as long as that takes, and never written to the list or a log. A run
        that cannot have its boxes is not started: it would go on without what it was told it has.
        """
        run_id, boxes = run["id"], run.get("boxes") or []
        if not boxes or run.get("boxes_handed"):
            return
        key = self._box_keys.pop(run_id, "")
        if not key:
            raise RunError("it was handed boxes, and the key to collect them was lost when the "
                           "program started again before the run did; ask for it again")
        got = await asyncio.to_thread(agents.collect_boxes, self.s.rouh_url, key=key, run_id=run_id)
        try:
            written = await self.docs.put_secrets(cwd, got, space=run["space"])
        finally:
            got.clear()
        self.list.append("run.boxes", run=run_id, body={
            "what": "handed", "written": written,
            "numbers": [int(b.get("number") or 0) for b in boxes]})

    async def _shred_boxes(self, run: dict[str, Any]) -> None:
        """Shred the boxes handed to a run that has ended, and tell Rouh. Never raises."""
        run_id = run["id"]
        self._box_keys.pop(run_id, None)
        if not run.get("boxes") or run.get("boxes_shredded"):
            return
        cwd = run.get("cwd")
        got: dict[str, Any] = {"shredded": 0, "scrubbed": 0}
        try:
            if cwd and os.path.isdir(os.path.dirname(cwd.rstrip("/")) or "/"):
                # The program's own record of the run's terminal first: only the program can
                # write it, and only the run's user can read the boxes (`sealed.py`).
                held = await self.docs.read_secrets(cwd, space=run["space"])
                try:
                    if held:
                        tty = self.p.terminals.folder(run_id) / "tty.log"
                        await asyncio.to_thread(sealed.scrub, str(tty), held)
                finally:
                    held.clear()
                got = await self.docs.shred_secrets(cwd, space=run["space"],
                                                    scrub=[str(run.get("transcript") or "")])
                if not got.get("ok", True):
                    log.warning("run %s: its boxes could not be shredded: %s", run_id,
                                got.get("reason"))
                    return
        except Exception:  # noqa: BLE001 - tried again by the sweep
            log.exception("run %s: its boxes could not be shredded", run_id)
            return
        self.list.append("run.boxes-shredded", run=run_id, body={
            "shredded": int(got.get("shredded") or 0), "scrubbed": int(got.get("scrubbed") or 0)})
        try:
            await asyncio.to_thread(agents.boxes_ended, self.s.rouh_url, run_id=run_id)
        except Exception as exc:  # noqa: BLE001 - the files are gone either way
            log.warning("run %s: Rouh could not be told its boxes were shredded (%s)", run_id, exc)

    async def boxes_sweep(self) -> None:
        """Every ended run whose boxes were never shredded: after a restart, and now and then."""
        for run in list(self.views.runs.values()):
            if run["state"] in ENDED and run.get("boxes") and not run.get("boxes_shredded"):
                await self._shred_boxes(run)

    async def _instructions(self, run: dict[str, Any]) -> str:
        """The agent instructions this run starts with, from Rouh, and where they came from.

        Asked of Rouh each time a run is started or started again, so a change
        on its Agent instructions page reaches the very next run. When Rouh
        does not answer, the copy the last run was given, said so in the list;
        with none, the run starts without them, said so too. Never a reason
        not to start a run.
        """
        run_id = run["id"]
        try:
            text = await asyncio.to_thread(agents.fetch_instructions, self.s.rouh_url,
                                           run_id=run_id, task=str(run.get("task") or ""))
            source = "rouh"
            self._last_instructions = text
        except Exception as exc:  # noqa: BLE001 - said in the list, and the run still starts
            text, source = self._last_instructions, ("the last copy" if self._last_instructions
                                                     else "none")
            log.warning("run %s: the agent instructions could not be read from Rouh (%s); %s",
                        run_id, exc, "it is given the last copy" if text else "it starts without them")
            self.list.append("run.instructions", run=run_id, body={
                "what": ("started with the last agent instructions Rouh gave"
                         if text else "started without agent instructions"),
                "why": str(exc)[:300], "from": source, "chars": len(text)})
            return text
        self.list.append("run.instructions", run=run_id, body={
            "what": f"started with Rouh's agent instructions, {len(text):,} characters",
            "from": source, "chars": len(text)})
        return text

    async def _prove_governed(self, run_id: str) -> None:
        """Stop a Codex run that has not shown its hooks are live.

        Codex will not run a hook a person has not told it to trust, and it
        says nothing when it skips one: on this server on 17 September 2026 a
        Codex run started with the program's hooks and without
        ``--dangerously-bypass-hook-trust`` ran its command, wrote its file and
        reported success, having asked the program nothing. The program passes
        that flag, and this is what stops the flag from being the only thing in
        the way: SessionStart is the first hook Codex sends, so a run that has
        not sent one by now is a run whose hooks are not running, and a run
        whose hooks are not running has none of the program's rules. It is
        stopped rather than left going.

        Claude Code needs none of this. Its hooks are in the settings file the
        program writes and hands it on its own command line, and nothing can
        switch them off.
        """
        await asyncio.sleep(self.s.codex_handshake)
        run = self.views.runs.get(run_id)
        if run is None or run["state"] in ENDED or run_id in self._session_seen:
            return
        if self.p.terminals.get(run_id) is None:
            return  # it has gone already, and its going was dealt with then
        self.list.append("run.ungoverned", run=run_id, body={
            "engine": "codex", "waited": self.s.codex_handshake,
            "why": ("Codex did not send its SessionStart hook, so the program cannot tell "
                    "whether its rules are running. A run the program cannot decide for is "
                    "not left going.")})
        await self.stop(run_id, by="the program")

    async def _launch_shell(self, run: dict[str, Any]) -> None:
        run_id = run["id"]
        where = await self._checkout(run)
        self.list.append("run.started", run=run_id, body=where)
        await self._hold(run_id, self.docs.shell_argv(run_id, where["cwd"], space=run["space"]))

    async def _hold(self, run_id: str, argv: list[str]) -> None:
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": os.environ.get("HOME", "/"),
               "LANG": "C.UTF-8", "TERM": "xterm-256color",
               # What the holder writes onto this run's own cgroup, so that a
               # run that leaks is the thing that dies for it and not the
               # program nor the run beside it (holder.Holder._ceiling).
               "ONE_RUN_MEMORY_MAX": str(self.s.run_memory_max)}
        # A world a test stands up gives its agents a home of its own
        # (tests/dev_server.py), and the agent has to be given it too. Until
        # 24 September 2026 only the program's own calls of asuser.py were,
        # so every stand-in agent in every world wrote into the real home,
        # and the Read tab, which reads the transcript where the world's home
        # says it is, found none. On the server this is never set: sudo gives
        # asuser.py the run's user's own home.
        if os.environ.get("ONE_ASUSER_HOME"):
            env["ONE_ASUSER_HOME"] = os.environ["ONE_ASUSER_HOME"]
        # In the containers a run's only way out is the key proxy, and its only way to Rouh the key
        # Rouh made for the worker (one/asuser.py, PASSED_ON). On the server sudo, between here and
        # the run, takes them off again, and the program's own environment has none of them anyway.
        from .asuser import PASSED_ON

        env.update({name: os.environ[name] for name in PASSED_ON if os.environ.get(name)})
        terminal = await self.p.terminals.start(run_id, argv, cols=self.s.cols, rows=self.s.rows,
                                                env=env)
        terminal.on_exit = self._on_exit
        if terminal.exit is not None and not terminal.connected:
            await self._on_exit(terminal, terminal.exit)
        elif run_id in self.stopping or self._run(run_id).get("close_wanted"):
            # Asked to end while it was starting, when there was no terminal
            # to ask yet. It is asked now, or it would go on for good.
            self.stopping.setdefault(run_id, self._run(run_id).get("close_wanted") or "stopped")
            self._close(run_id, terminal)

    def _key_for(self, run_id: str) -> str:
        key = self.keys.get(run_id)
        if not key:
            key = secrets.token_urlsafe(18)
            self.keys[run_id] = key
            path = self.p.terminals.folder(run_id) / "hook.key"
            path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as fh:
                fh.write(key)
        return key

    # -- the hooks -----------------------------------------------------------------------

    async def on_hook(self, run_id: str, key: str, kind: str, payload: dict[str, Any]) -> dict:
        """Take one hook from a run and give Claude Code its answer."""
        expected = self.keys.get(run_id or "", "")
        if not expected or not secrets.compare_digest(expected, key or ""):
            log.warning("a hook for run %r without its key was ignored", run_id)
            return {}
        run = self.views.runs.get(run_id)
        if run is None or run["state"] in ENDED:
            return {}
        if run_id not in self._session_seen and payload.get("transcript_path"):
            self._session_seen.add(run_id)
            self._codex_resuming.discard(run_id)
            self.list.append("agent.session", run=run_id, by="run", body={
                "session_id": payload.get("session_id"),
                "transcript": payload.get("transcript_path")})
            if agents.engine_of(run.get("engine")) == "codex":
                self._watch_codex(run_id)
        if kind == "session_start":
            # A Codex run is told how it works here, because there is nowhere
            # earlier to tell it. A Claude Code run was told on its command
            # line and has nothing waiting.
            context = self._context.pop(run_id, "")
            if context:
                return agents.session_context(context)
            return {}
        if kind == "pre_tool_use":
            return await self._pre_tool(run, payload)
        if kind == "permission_request":
            return await self._permission_request(run, payload)
        if kind == "stop":
            return await self._turn_ended(run, payload)
        if kind == "post_tool_use":
            given = self._note_if_missed(run_id, payload)
            if given:
                payload = {**payload, "tool_use_id": given}
        if (kind == "notification" and payload.get("notification_type") == "idle_prompt"
                and run["kind"] == "agent" and run["state"] in ("working", "saving")
                and not run.get("waiting_on")):
            # (A paused run sits at its prompt on purpose, waiting on what it
            # started, and its Stop hook was heard: that is not a lost one.)
            # Claude Code says it is waiting at its prompt, but the program never
            # heard its turn end: the Stop hook was lost, as one was on 14
            # September to a connection being closed. The turn is ended here
            # instead, a minute late, so its work still lands.
            self.list.append("hook.missed", run=run_id, body={
                "hook": "Stop", "tool": "", "what": "the end of a turn", "caught": "Notification"})
            follow_up = await self._turn_ended(run, {"last_assistant_message": "",
                                                     "stop_hook_active": False})
            terminal = self.p.terminals.get(run_id)
            if (follow_up or {}).get("reason") and terminal is not None:
                # Not waited for here: Claude Code is waiting on this hook, and
                # takes nothing typed until it has its answer.
                self._spawn(self._type_message(run_id, terminal, follow_up["reason"],
                                               by="program", via="end of turn", sent=False))
            return {}
        found = agents.simple_entry(kind, payload)
        if found is None:
            return {}
        entry_kind, body = found
        self.list.append(entry_kind, run=run_id, by="run", body=body)
        if kind == "prompt" and run_id in self._typing:
            self._typing[run_id].set()
        if kind == "prompt" and run_id in self.takeovers:
            self.takeovers[run_id].prompts.append(body["text"][:500])
        if kind == "notification" and body.get("type") in TERMINAL_QUESTIONS:
            self.p.tell(run_id, f"{run['title']} is waiting for you in its terminal: "
                                f"{body.get('message') or 'it has a question'}",
                        reason="terminal-question")
        return {}

    async def _pre_tool(self, run: dict[str, Any], payload: dict[str, Any]) -> dict:
        run_id = run["id"]
        tool = str(payload.get("tool_name") or "tool")
        tool_input = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
        decision = rules.decide(tool, tool_input, cwd=run.get("cwd") or payload.get("cwd") or "/",
                                scratch=payload.get("scratchpad_dir"), home=self._home(run))
        body = agents.tool_body(payload)
        if self.s.access == "full":
            # Full access, the person's decision (D8): nothing is refused and
            # nobody is asked. The call is still written down, marked with
            # what the guarded rules would have done, so those stand out.
            if decision.rule != "ordinary":
                body["rule"] = decision.rule
            if decision.decision != "allow":
                body["guarded"] = decision.decision
            self._mark_decided(run_id, body.get("call"))
            self.list.append("tool.opened", run=run_id, by="run", body=body)
            return _pre_tool_answer("allow", "Allowed: this run has full access.")
        if decision.decision == "ask":
            # The reason is the question; the call itself goes beside it,
            # whole, so it can be read before it is allowed.
            answer = await self.p.questions.ask(
                run_id, text=f"{decision.why} Allow it?", tool=tool, what=body["what"],
                detail=_call_in_full(tool, tool_input), why=decision.why)
            if answer == "yes":
                decision = rules.Decision("allow", "person-said-yes", "The person allowed it.")
            elif answer == "no":
                decision = rules.Decision("deny", "person-said-no", (
                    "The person said no to this. Do not try it another way: carry on without it, "
                    "or stop and say what you needed."))
            else:
                decision = rules.Decision("deny", "nobody-answered", (
                    "Nobody answered in time, so it was not allowed. Carry on without it, or stop "
                    "and say what you needed."))
        self._mark_decided(run_id, body.get("call"))
        if decision.decision == "deny":
            self.list.append("permission.decided", run=run_id, body={
                "call": body.get("call"), "tool": tool, "decision": "deny", "rule": decision.rule,
                "why": decision.why, "what": body["what"]})
            return _pre_tool_answer("deny", decision.why)
        if decision.rule != "ordinary":
            body["rule"] = decision.rule
        self.list.append("tool.opened", run=run_id, by="run", body=body)
        return _pre_tool_answer("allow", "Allowed by the one program's rules.")

    async def _permission_request(self, run: dict[str, Any], payload: dict[str, Any]) -> dict:
        """The second chance: Claude Code is about to ask on its own screen.

        That only happens when the program did not decide the call first, so
        it is written down as missed, then decided exactly as PreToolUse
        would have been. Watched on the server on 14 September: this hook
        carries the tool's name and its whole input but no call id, and an
        "allow" answer skips the dialog.

        With no input to judge the call by, the program does not guess: it
        steps aside, Claude Code asks on its own screen, and its notification
        tells the person.
        """
        run_id = run["id"]
        tool = str(payload.get("tool_name") or "tool")
        tool_input = payload.get("tool_input")
        if not isinstance(tool_input, dict) or not tool_input:
            self.list.append("hook.missed", run=run_id, body={
                "hook": "PreToolUse", "tool": tool, "what": tool, "caught": None,
                "why": "the second chance did not say what the call would do"})
            return {}
        given = "caught-" + secrets.token_hex(6)
        payload = {**payload, "tool_use_id": given}
        self.list.append("hook.missed", run=run_id, body={
            "hook": "PreToolUse", "tool": tool, "call": given,
            "what": agents.tool_body(payload)["what"], "caught": "PermissionRequest"})
        answer = (await self._pre_tool(run, payload)).get("hookSpecificOutput") or {}
        if answer.get("permissionDecision") == "allow":
            self._caught.setdefault(run_id, []).append((_fingerprint(tool, tool_input), given))
            return {"hookSpecificOutput": {"hookEventName": "PermissionRequest",
                                           "decision": {"behavior": "allow"}}}
        return {"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": {
            "behavior": "deny",
            "message": answer.get("permissionDecisionReason") or "Refused by the one program's rules."}}}

    def _mark_decided(self, run_id: str, call: Any) -> None:
        if call:
            self._decided.setdefault(run_id, set()).add(str(call))

    def _note_if_missed(self, run_id: str, payload: dict[str, Any]) -> str | None:
        """A call finished that the program never decided: say so in the list.

        A call decided at the second chance is recognised by its tool and
        input, because that hook carries no call id; the id the program gave
        it then is returned, so the call closes under the id it opened with.
        Anything else ran without the program being asked, which Claude Code
        does by itself with a read-only command such as ``ls``; it is written
        down, never silent.
        """
        call = str(payload.get("tool_use_id") or "")
        if not call or call in self._decided.get(run_id, set()):
            return None
        tool = str(payload.get("tool_name") or "tool")
        tool_input = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
        mark = _fingerprint(tool, tool_input)
        caught = self._caught.get(run_id) or []
        for i, (seen, given) in enumerate(caught):
            if seen == mark:
                del caught[i]
                self._mark_decided(run_id, call)
                return given
        self._mark_decided(run_id, call)
        self.list.append("hook.missed", run=run_id, body={
            "hook": "PreToolUse", "tool": tool, "call": call,
            "what": agents.tool_body(payload)["what"], "caught": None})
        return None

    async def _turn_ended(self, run: dict[str, Any], payload: dict[str, Any]) -> dict:
        run_id = run["id"]
        # A run in a repository, the workspace or Rouh's own code, saves its
        # work to main at the end of every turn.
        saving = bool(self.s.space(run["space"]).repo and run.get("repo") and run.get("cwd"))
        # What the run started that will wake it again: a sub-agent, a
        # background command, a monitor, a scheduled wake-up. Claude Code names
        # them in the Stop hook (`agents.paused_on`), and while any is live the
        # turn's end is a pause, not the end of the work: the session is
        # prompted again by itself the moment one of them reports.
        #
        # So nothing is landed, nobody is told and the run is not sent back:
        # it stays working, waiting on what it named, until its next turn ends
        # with nothing left in flight, or until it has been silent for
        # ``pause_silence`` (`end_stale_pauses`), or its process goes. Until
        # 18 October 2026 a turn like that was landed and reported like any
        # other, so run 9854c2fa, whose helper was still converting files, was
        # sent back once, stopped again, and was announced to the person as a
        # change that had stopped unsaved while it carried on working.
        waiting = agents.paused_on(payload)
        # In the person's own session they always hold the keyboard, and a
        # clash still goes back to Claude, with them watching it being fixed.
        driving = run_id in self.takeovers and not run.get("interactive")
        if waiting:
            self.list.append("agent.stopped", run=run_id, by="run", body={
                "message": agents.plain(payload.get("last_assistant_message"), CLOSING_TEXT),
                "again": bool(payload.get("stop_hook_active")), "saving": False,
                "paused": True, "background": waiting}, whole=("message",))
            follow_up = None
            if self.pending.get(run_id) and not driving:
                follow_up = "\n\n".join(self.pending.pop(run_id))
                self.list.append("message.sent", run=run_id, body={
                    "text": agents.plain(follow_up, 4000), "via": "end of turn"})
            self.p.scheduler.wake()
            return {"decision": "block", "reason": follow_up} if follow_up else {}
        self.list.append("agent.stopped", run=run_id, by="run", body={
            "message": agents.plain(payload.get("last_assistant_message"), CLOSING_TEXT),
            "again": bool(payload.get("stop_hook_active")), "saving": saving},
            whole=("message",))
        follow_up = await self._end_turn(run, driving=driving)
        if follow_up is None and self.pending.get(run_id) and not driving:
            follow_up = "\n\n".join(self.pending.pop(run_id))
            self.list.append("message.sent", run=run_id, body={
                "text": agents.plain(follow_up, 4000), "via": "end of turn"})
        self.p.scheduler.wake()
        if follow_up:
            return {"decision": "block", "reason": follow_up}
        return {}

    async def _end_turn(self, run: dict[str, Any], *, driving: bool,
                        at_turn_end: bool = True) -> str | None:
        """Save a turn that is really over: land its work, or say what it left."""
        if not (self.s.space(run["space"]).repo and run.get("repo") and run.get("cwd")):
            return None
        return await self._land(run, driving=driving, at_turn_end=at_turn_end)

    async def end_stale_pause(self, run_id: str, *, silent_for: float) -> None:
        """A paused run that nothing has woken for too long: its turn is over after all.

        What it was waiting on has had ``pause_silence`` to report, with no
        prompt, no tool call and no sub-agent in the list for all of it, so it
        is not coming: a sub-agent that died without a word, a command whose
        notice was lost, a wake-up scheduled too far off to be this run's
        work. Left alone, the run would read as working until the six-hour
        limit cleaned it up, and its work would sit unreported.

        So the turn is ended the ordinary way, without it: its commits are
        landed and reported, or what it left uncommitted is said, and the
        reason goes in the list first. Nothing is sent back to it, because
        there is no turn to send back into; if what it waited on does report
        later, the run simply carries on, and its next turn reports again.
        """
        run = self.views.runs.get(run_id)
        if run is None or run["state"] in ENDED or not run.get("waiting_on"):
            return
        waited = ", ".join(run.get("waiting_on") or [])
        minutes = max(1, int(silent_for // 60))
        self.list.append("agent.pause-ended", run=run_id, body={
            "why": (f"nothing came back from {waited} in {minutes} "
                    f"minute{'s' if minutes != 1 else ''}")[:400],
            "background": list(run.get("waiting_on") or []),
            "saving": bool(self.s.space(run["space"]).repo and run.get("repo")
                           and run.get("cwd"))})
        run = self.views.runs.get(run_id) or run
        if run.get("state") == "saving":
            await self._end_turn(run, driving=False, at_turn_end=False)
        self.p.scheduler.wake()

    def _ask_once(self, run_id: str) -> bool:
        """Whether this run may be sent back to finish, and marks that it was.

        Once for the whole run, not once for each reason: a run that comes back
        saying the tests will not pass is telling the truth as often as not, and
        being asked twice would make a loop of a plain answer.
        """
        if self.finish_asks.get(run_id, 0) >= 1:
            return False
        self.finish_asks[run_id] = self.finish_asks.get(run_id, 0) + 1
        return True

    async def _land(self, run: dict[str, Any], *, driving: bool,
                    at_turn_end: bool = False) -> str | None:
        """Put the run's commits on main. A follow-up for Claude if it must fix a clash.

        ``at_turn_end`` is the Stop hook rather than the run's exit, and is the
        only moment a follow-up can be handed back at all. A turn that ended
        with work still in flight never gets here: it is a pause (`_turn_ended`).
        """
        run_id = run["id"]
        try:
            result = await self.docs.land(run["cwd"], run_id=run_id, space=run["space"],
                                          target=run.get("target"), flow=run.get("flow"),
                                          branch=run.get("branch"),
                                          title=run.get("title") or "",
                                          base=run.get("base_sha") or "")
        except Exception as exc:
            result = {"landed": False, "reason": f"{type(exc).__name__}: {exc}"}
        if result.get("landed") and result.get("sha") and result.get("sha") == run.get("landed"):
            # The same commit this run's last turn was already reported as
            # landing. A run whose work is on main is recognised as landed
            # every time it is asked (`asuser.land`), so a later turn that
            # changed nothing would otherwise report the same change twice.
            result = {"landed": False, "reason": "nothing new to land"}
        if result.get("landed"):
            self.fix_tries.pop(run_id, None)
            if self.s.space(run["space"]).follow:
                await self._follow()
            body = {"sha": result.get("sha"), "files": result.get("files") or [],
                    "commits": result.get("commits")}
            if result.get("landed_head"):
                # Which of the run's own commits this landing took: everything
                # up to it is on the target, whatever ids the replay gave it.
                body["landed_head"] = result["landed_head"]
            if result.get("deploy_reason"):
                # What land.sh's own last step made of it. Landing includes
                # deploying since 21 September 2026, so by the time this entry
                # is written the commit is either being served or it is not,
                # and whoever reports the turn says which rather than guessing.
                body["deployed"] = bool(result.get("deployed"))
                body["deploy"] = result.get("deploy") or ""
                body["deploy_reason"] = result.get("deploy_reason")
            if result.get("already"):
                # It was on main before this landing ran: an earlier attempt of
                # the same work got there, and land.sh compared by patch rather
                # than by text and said so instead of calling it a collision.
                # 5f932c8's case, and the one that needs nobody at all.
                body["already"] = True
                body["dropped"] = result.get("dropped")
            if result.get("pushed_itself"):
                # On main because the run pushed it with `./land.sh` in its
                # own turn: not an earlier attempt of the same change, just
                # this one, landed a few seconds before this was asked.
                body["pushed_itself"] = True
            if result.get("branch"):
                # Pushed on its own branch, for a pull request (D42).
                body.update(branch=result["branch"], compare=result.get("compare"),
                            target=run.get("target"))
            self.list.append("work.landed", run=run_id, body=body)
            return None
        reason = str(result.get("reason") or "it did not say why")
        if reason == "nothing new to land":
            # Nothing was committed. Whether that is a run with nothing to
            # commit or a run that walked away from its own work is the
            # difference between an answer and a loss, and only the checkout
            # knows, so it is asked and the answer goes in the list.
            left = await self.what_is_left(run)
            # Decided before the entry is written, because Rouh reports a
            # turn that saved nothing off it: a turn about to carry on must not
            # be announced as one that finished with nothing to show.
            send_back = (at_turn_end and not driving and bool(left.get("dirty"))
                         and self._ask_once(run_id))
            self.list.append("work.nothing-new", run=run_id,
                             body={**left, **({"sent_back": True} if send_back else {})})
            if send_back:
                why = work_left({**left, "target": run.get("target")})
                self.list.append("work.unfinished", run=run_id, body={
                    "why": why[:400], "sent_back": True})
                return agents.finish_the_work(target=run.get("target"))
            return None
        files = result.get("files") or []
        # What land.sh decided about this collision, carried on the entry so that
        # every screen, Rouh and the person see the same one thing: which
        # record holds both sides, the question in one line, which attempt this
        # was, and whose move it is now.
        about = {name: result[name]
                 for name in ("conflict", "question", "pre_branch", "attempt",
                              "both_rewrote", "needs_person")
                 if result.get(name) not in (None, "")}
        # Rung four: the conflict goes back to the worker that wrote the code,
        # with both sides and the brief land.sh wrote for it. The run does not
        # end and nothing is said to anybody: its next stop lands it the normal
        # way. Rung six - twice failed, or both sides rewrote the same thing -
        # arrives as ``needs_person`` and is never sent back, because only the
        # person can answer it.
        handback = str(result.get("handback") or "")
        if (result.get("clash") and handback and not result.get("needs_person")
                and self.fix_tries.get(run_id, 0) < 1 and not driving):
            self.fix_tries[run_id] = self.fix_tries.get(run_id, 0) + 1
            self.list.append("work.not-landed", run=run_id, body={
                "reason": reason, "files": files, "sent_back": True, **about})
            return handback
        self.list.append("work.not-landed", run=run_id, body={
            "reason": reason, "files": files, "sent_back": False, **about})
        if not result.get("needs_person"):
            # A conflict the person has to decide reaches them through the
            # conflict card, out loud and on their phone (rouh/conflicts.py),
            # which carries both sides and the four choices. A second, plainer
            # line saying the same thing would be the same question twice.
            self.p.tell(run_id, f"{run['title']}: its work could not be saved to main. {reason}",
                        reason="not-landed")
        return None

    async def what_is_left(self, run: dict[str, Any]) -> dict[str, Any]:
        """What this run's checkout still holds that has not reached its branch.

        ``{"dirty": bool, "unsaved": int}``, or ``{}`` when there is nothing to
        ask: a run with no repository, a checkout already taken away, or a git
        that would not answer. An empty answer never turns a run into an
        unfinished one, because not knowing is not the same as knowing it lost
        something, and a wrong "unfinished" would be its own kind of lie.
        """
        cwd = run.get("cwd")
        if not run.get("repo") or not cwd or not os.path.isdir(cwd):
            return {}
        try:
            got = await self.docs.status(cwd, space=run["space"], target=run.get("target"),
                                         branch=run.get("branch"), flow=run.get("flow"),
                                         landed_head=run.get("landed_head"))
        except Exception:
            log.exception("could not read what run %s left in %s", run["id"], cwd)
            return {}
        if not got.get("ok") or not got.get("exists", True):
            return {}
        return {"dirty": bool(got.get("dirty")), "unsaved": int(got.get("unsaved") or 0)}

    async def holds_work(self, run: dict[str, Any]) -> str:
        """Why this run must not be closed yet, in words, or "".

        The scheduler asks before it closes a run to make room or because it has
        sat unwatched: a run whose work is all on main can go, and a run still
        holding work cannot, because closing it is what threw away 8109f4b5's.

        A checkout that is there and will not answer counts as holding work.
        ``what_is_left`` says ``{}`` both for "there is nothing to ask about"
        and for "the asking failed", and until 19 September 2026 this read the
        second as the first: an empty answer became an empty `work_left`, which
        the scheduler read as nothing to lose. Nothing was logged, because
        nothing had gone wrong as far as any one line of it could tell.

        Run f9c548c7 went that way on 19 September 2026, holding the only copy
        of a fix to Rouh. Which failure it was is not recoverable now, and
        that is half the point: the closing was logged, the reason it was
        thought safe was not. The likeliest is the timing, because its landing
        had begun seven seconds earlier and a `git status` in a checkout
        another git is working in comes back non-zero - which would mean the
        check failed exactly because the run was busy saving its work, and
        failing meant "safe to throw away".

        So the question is asked the other way round here: a checkout that is
        still on disk has to say it is empty before it is believed.
        """
        cwd = run.get("cwd")
        if not run.get("repo") or not cwd or not os.path.isdir(cwd):
            return ""                   # a scratch run, or a checkout already gone
        left = await self.what_is_left(run)
        if not left:
            return "what it still holds could not be read"
        return work_left({**left, "target": run.get("target")})

    #: How long the server's copy may fail to follow main before the person is told.
    FOLLOW_TELL_AFTER = 300.0

    async def _follow(self) -> bool:
        """Bring the server's own copy of the workspace up to main at once.

        Stage 4: that copy is the one everything on the server reads, Rouh
        and pa.lcl included, so it takes a run's work in as soon as it lands
        rather than waiting for anything else to bring it. Never fatal. On 14
        September it could not follow for 15 minutes and only the log knew, so
        once it has failed for FOLLOW_TELL_AFTER seconds the person is told,
        with git's own words.

        Told once for each problem, not every few minutes while it lasts
        (Petar's N1). On 27 October 2026 the copy was stuck for eleven hours
        and he heard the same sentence every half hour, with an age counted
        from the program's last restart rather than from when it stuck. So
        when it started failing and what was said are kept on disk
        (``follow.json``), across restarts, until it follows again.

        Commits somebody made on the copy's own main no longer stop it: they
        are kept on a branch, the copy follows main, and the branch is landed
        like any run's work (``asuser._keep_aside``, ``_land_kept``).
        """
        try:
            got = await self.docs.follow()
            if got.get("ok") and got.get("skipped"):
                # Another follow held the lock, or git was busy: this says
                # nothing either way, so the clock is left alone. On 14
                # September every check landed on a run of the workspace's own
                # `bin/sync`, each one reset the clock, and a copy stuck for
                # minutes was never reported. That script is gone; the reason
                # for leaving the clock alone on a skip is not.
                return True
            if got.get("ok"):
                if got.get("kept"):
                    self._spawn(self._land_kept(got["kept"]))
                self._follow_state(None)
                return True
            why = str(got.get("reason") or "it did not say why")
        except Exception as exc:
            log.exception("could not bring the workspace copy up to main")
            why = f"{type(exc).__name__}: {exc}"
        log.warning("the workspace copy did not follow main: %s", why)
        state = self._follow_state()
        now = time.time()
        since = float(state.get("since") or now)
        told = state.get("told")
        if now - since >= self.FOLLOW_TELL_AFTER and told != why:
            told = why
            self.p.tell(None, f"The server's copy of the workspace has not taken in main since "
                              f"{time.strftime('%H:%M', time.localtime(since))}, so pa.lcl and Rouh "
                              f"show older pages. What git said: {why[:300]}", reason="copy-stuck")
        self._follow_state({"since": since, "told": told})
        return False

    def _follow_state(self, state: dict | None | bool = False) -> dict:
        """What ``_follow`` keeps across restarts: ``{"since", "told"}``, or {} while it follows.

        Called with nothing it reads; with a dict it writes; with None it clears.
        """
        path = self.s.data / "follow.json"
        if state is False:
            try:
                got = json.loads(path.read_text())
                return got if isinstance(got, dict) else {}
            except (OSError, ValueError):
                return {}
        try:
            if state is None:
                path.unlink(missing_ok=True)
            else:
                path.write_text(json.dumps(state))
        except OSError:
            log.exception("could not keep the copy's follow state in %s", path)
        return state or {}

    async def _land_kept(self, kept: dict) -> None:
        """Land the commits ``follow`` found on the copy's own main, and say so once."""
        branch, commits = kept["branch"], kept.get("commits") or []
        self.list.append("copy.kept", body=kept)
        try:
            got = await self.docs.land_kept(branch)
        except Exception as exc:
            log.exception("could not land %s", branch)
            got = {"landed": False, "reason": f"{type(exc).__name__}: {exc}"}
        self.list.append("copy.kept-landed" if got.get("landed") else "copy.kept-not-landed",
                         body={"branch": branch, **{k: got.get(k) for k in
                                                    ("sha", "reason", "deploy_reason", "conflict")}})
        what = f"{len(commits)} commit{'s' if len(commits) != 1 else ''} made straight on the " \
               f"server's copy of the workspace ({'; '.join(commits)[:200]})"
        if got.get("landed"):
            self.p.tell(None, f"{what} were saved to main as {str(got.get('sha') or '')[:8]}.",
                        reason=f"copy-kept-{branch}")
        else:
            self.p.tell(None, f"{what} could not be saved to main, and are kept on the branch "
                              f"{branch}. {str(got.get('reason') or '')[:300]}",
                        reason=f"copy-kept-{branch}")

    async def follow_check(self) -> None:
        """Called now and then by the scheduler, so the copy follows main when no run lands too."""
        await self._follow()

    # -- stopping ------------------------------------------------------------------------

    async def stop(self, run_id: str, *, by: str, how: str = "stopped") -> None:
        run = self._run(run_id)
        if run["state"] in ENDED:
            raise RunError("that run has already ended")
        # Durable: it stands until the run is started again, so a stop this
        # program does not live to finish is finished by the next one.
        self.list.append("run.stop-requested", run=run_id, by=by,
                         body={"how": how, "durable": True})
        if run["state"] == "queued" and not self.launching(run_id):
            self.list.append("run.ended", run=run_id, by=by, body={"how": how, "code": None})
            self.p.scheduler.wake()
            return
        self.stopping[run_id] = how
        self.switching.pop(run_id, None)
        self.p.questions.withdraw_run(run_id, "the run is being stopped")
        terminal = self.p.terminals.get(run_id)
        if terminal is None:
            if not self.launching(run_id) and run["state"] == "asking":
                # Paused with no process behind it (a conversation that would
                # not carry over to the key): there is nothing to ask to
                # leave, so it ends here.
                self.stopping.pop(run_id, None)
                await self._end(run, how=how, code=None, sig=None, forced=None)
            return
        self._close(run_id, terminal)

    def _close(self, run_id: str, terminal) -> asyncio.Task:
        """Ask this run's terminal to end, once, however many times it is asked for.

        A second ask while the first is still asking gets the first, so a stop
        and an archive, or a restart finding a stop still wanted, never press
        the keys twice over each other.
        """
        task = self.closing.get(run_id)
        if task is not None and not task.done():
            return task
        run = self.views.runs.get(run_id) or {}
        if run.get("kind") == "agent":
            coro = self._see_claude_out(run_id, terminal)
        else:
            coro = self._hang_up(run_id, terminal)
        task = asyncio.create_task(coro, name=f"close-{run_id}")
        self.closing[run_id] = task

        def done(t: asyncio.Task, run_id: str = run_id) -> None:
            if self.closing.get(run_id) is t:
                self.closing.pop(run_id, None)
            if not t.cancelled() and t.exception() is not None:
                log.error("asking run %s to end failed", run_id, exc_info=t.exception())

        task.add_done_callback(done)
        return task

    async def _hang_up(self, run_id: str, terminal) -> None:
        await terminal.signal(signal.SIGHUP)
        await self._make_sure_it_ends(run_id, terminal)

    #: Claude Code leaves on two Ctrl-C close together. One press on its own
    #: only arms "Press Ctrl-C again to exit", and that arming times out after
    #: a couple of seconds, so two presses far apart never end it.
    CTRL_C_GAP = 0.4
    #: How long to give it to go after a pair of presses, before asking again.
    CTRL_C_WAIT = 5.0
    #: How many times to ask before taking the terminal away from it.
    CTRL_C_ROUNDS = 3

    async def _see_claude_out(self, run_id: str, terminal) -> None:
        """Ask Claude Code to leave, and keep asking until it does.

        A press while it is still working interrupts the work instead of
        arming the exit, so the first pair can be swallowed: the program
        closes a run the moment its turn ends, and on 16 September six runs
        that had already saved their work sat at "Press Ctrl-C again to exit"
        until SIGTERM took the terminal away from them, which is where their
        exit code 143 came from. Asking again costs a few seconds and ends
        the session the way Claude Code ends it by itself, exit code 0.
        """
        for _ in range(self.CTRL_C_ROUNDS):
            await terminal.type(b"\x03")
            await asyncio.sleep(self.CTRL_C_GAP)
            await terminal.type(b"\x03")
            if await terminal.closed(timeout=self.CTRL_C_WAIT):
                return
        await self._make_sure_it_ends(run_id, terminal)

    async def _make_sure_it_ends(self, run_id: str, terminal) -> None:
        """It would not leave when asked. Take the terminal away from it, and say so."""
        self.forced[run_id] = "SIGTERM"
        await terminal.signal(signal.SIGTERM)  # the holder kills it ten seconds later
        if await terminal.closed(timeout=15):
            return
        self.forced[run_id] = "SIGKILL"
        await terminal.signal(signal.SIGKILL)
        await terminal.closed(timeout=5)

    # -- forgetting a run ------------------------------------------------------------------

    async def forget(self, run_id: str, *, by: str) -> int:
        """Forget an ended run for good: off every list, its entries out of the
        list's files, its own folder (terminal log, hooks, how it ended) deleted.

        For a run the person wants gone, not put away: ``archive`` keeps
        everything and only hides it. Only a run that has ended, so nothing is
        pulled from under work in progress. Its checkout and Claude Code's own
        transcript are not this program's and are not touched here. The number
        of list entries that went is returned.
        """
        run = self._run(run_id)
        if run["state"] not in ENDED:
            raise RunError(f"run {run_id} has not ended; stop it first")
        self.list.append("run.forgotten", run=run_id, by=by, body={})
        dropped = await asyncio.to_thread(self.list.scrub, run_id)
        self.p.terminals.forget(run_id)
        folder = self.p.terminals.folder(run_id)
        await asyncio.to_thread(shutil.rmtree, folder, True)
        log.info("run %s forgotten by %s: %d list entries and its folder deleted", run_id, by, dropped)
        return dropped

    def retitle(self, run_id: str, title: str, *, by: str, brief: str | None = None) -> None:
        """Give a run another title, and another brief when one is given (`run.retitled`)."""
        self._run(run_id)
        body: dict[str, Any] = {"title": str(title or "").strip()[:120]}
        if brief is not None:
            body["brief"] = str(brief)
        self.list.append("run.retitled", run=run_id, by=by, body=body)

    def forget_later(self, run_id: str, *, by: str, after: float) -> None:
        """Forget a run `after` seconds once it has ended, whether or not it has ended yet:
        the way a run is forgotten that is still working, its own included, so its report
        is delivered first (`Scheduler.forget_due`)."""
        self._run(run_id)
        self.list.append("run.forget-requested", run=run_id, by=by, body={"after": float(after)})

    # -- putting a run out of the way ----------------------------------------------------

    async def archive(self, run_id: str, *, by: str, on: bool = True,
                      how: str = "stopped") -> dict[str, Any]:
        """Put a run out of the list's way, or bring it back. Archiving stops it.

        The flag used to be all there was, and a run put away carried on working
        in a terminal nobody was watching. The person asked on 16 September 2026
        for putting a run away to mean they are done with it, so a run that has
        not ended is stopped first, down the same path ``stop`` takes when they
        ask for it by name, and then the flag goes on the list.

        A run that has already ended has nothing to stop, unless its terminal
        is somehow still there, and then that is closed. Bringing one back is
        the flag alone: it does not start anything again. The checkout is left
        where it is either way, and the flag survives a restart because the list
        does.

        The flag and the stop are written down before anything is waited on,
        and the stop stands until the run is started again. On 3 October 2026
        the stop itself lived only in this program, so a deploy that restarted
        it a moment after an archive cancelled the stop, and the program that
        came back adopted the session as if nothing had been asked: archived,
        and still running for good. Now the program that comes back finishes
        it (``adopt_all``), and the one going away waits for it first.

        ``how`` is what the stop is called, which the program's own garbage
        collection sets to ``succeeded`` (``Scheduler.archive_succeeded``).
        """
        run = self._run(run_id)
        if bool(run.get("archived")) != bool(on):
            self.list.append("run.archived", run=run_id, by=by, body={"on": bool(on)})
        if on and run["state"] not in ENDED:
            try:
                await self.stop(run_id, by=by, how=how)
            except Exception as exc:
                # The run goes off the list whatever its terminal did. A run
                # that ended between reading it and stopping it, or a terminal
                # that will not answer, must not leave the person with an error
                # and the run still in front of them.
                log.warning("could not stop %s while archiving it: %s", run_id, exc)
        elif on and session_alive(self.p.terminals.folder(run_id)):
            self.list.append("run.stop-requested", run=run_id, by=by, body={
                "how": "stopped", "durable": True,
                "why": "it was archived after it ended, and its terminal was still there"})
            await self._close_left_over(run_id)
        return self._run(run_id)

    async def _close_left_over(self, run_id: str) -> bool:
        """Close the terminal of a run that has ended but whose holder is still there.

        Reached only through the run's own folder: its holder's own socket,
        which answers only for that holder. Nothing is matched by name or
        pattern and no process id is signalled, so nothing but this run's own
        terminal can be touched. False when there is no holder to reach.
        """
        terminal = self.p.terminals.get(run_id) or await self.p.terminals.adopt(run_id)
        if terminal is None:
            return False
        terminal.on_exit = self._on_exit
        self.list.append("run.close-resumed", run=run_id, body={
            "holder": terminal.holder_pid,
            "why": "the run had ended and was asked to stay ended, and its terminal was still open"})
        self._close(run_id, terminal)
        return True

    # -- who pays for a run of Codex (billing.py) ------------------------------------------

    def _watch_codex(self, run_id: str) -> None:
        """Read this run of Codex's session file for turns that failed, from now on.

        Once per file: a run carried on in the same conversation has the same
        file, and its watcher simply goes on reading it.
        """
        run = self.views.runs.get(run_id)
        path = str((run or {}).get("transcript") or "")
        if run is None or not path or run["state"] in ENDED:
            return
        watcher = self.watchers.get(run_id)
        if watcher is not None and watcher.path == path and not watcher.task.done():
            return
        if watcher is not None:
            self._spawn(watcher.stop())
        self.watchers[run_id] = billing.Watcher(
            self.docs, run_id, path, self.s.space(run.get("space")).user, self._codex_turn_failed)

    def _unwatch_codex(self, run_id: str) -> None:
        watcher = self.watchers.pop(run_id, None)
        if watcher is not None:
            self._spawn(watcher.stop())

    async def _codex_turn_failed(self, run_id: str, failed: dict[str, Any]) -> None:
        """Codex ended a turn with an error. Say so, and ask when only a person can decide.

        A subscription that ran out, or whose login stopped working, pauses the
        run with the choice of carrying it on on the API key; nothing is
        switched and nothing is billed until somebody answers yes. A turn that
        fails on the first go of a conversation carried over to the key is
        that conversation not being taken, and the person is asked about a
        fresh one. Anything else is only written down, so the run is seen to
        have stopped rather than looking busy for ever.
        """
        run = self.views.runs.get(run_id)
        if run is None or run["state"] in ENDED:
            return
        turn = failed.get("turn") or ""
        if turn and turn in (run.get("failed_turns") or []):
            return  # already seen, before a restart or a resume
        pays = billing.billing_of(run.get("engine"), run.get("billing"))
        resuming = bool(run.get("billing_resuming"))
        self.list.append("codex.turn-failed", run=run_id, body={
            "turn": turn, "info": failed.get("info") or "",
            "message": agents.plain(failed.get("message"), 600), "billing": pays})
        if pays == billing.SUBSCRIPTION and failed.get("info") == "unauthorized":
            # A lost sign-in is the same for every run, so it is one line, said once
            # (codex_signin.tell_lost), never a question for each run: the run stops, its checkout
            # kept, and it can be started again once Codex is signed in.
            self.list.append("codex.needs-signin", run=run_id, body={
                "said": codex_signin.needs_line(self.s.public_url)})
            self.p.codex_signin.tell_lost()
            with contextlib.suppress(RunError):
                await self.stop(run_id, by="codex-signin")
        elif pays == billing.SUBSCRIPTION and failed.get("info") in billing.STOPS:
            self._offer_api(run_id, failed)
        elif pays == billing.API and resuming:
            self._offer_fresh(run_id, failed.get("message") or failed.get("info") or "an error")
        else:
            self.p.tell(run_id, f"{run['title']}: Codex stopped: {failed.get('message')}",
                        reason="codex-stopped")

    def _offer_api(self, run_id: str, failed: dict[str, Any]) -> None:
        run = self._run(run_id)
        why = billing.STOPS.get(str(failed.get("info") or ""), "stopped it")
        if billing.saver(self.s.land_dir):
            # Saver never offers per-token billing: the run waits for its subscription.
            self.p.tell(run_id, billing.SAVER_WAITS.format(title=run["title"], why=why),
                        reason="codex-subscription")
            return
        if not self.p.api_key.available():
            self.p.tell(run_id, f"{run['title']} is paused: the ChatGPT subscription it runs on "
                                f"{why}, and there is no OpenAI API key here to carry it on with.",
                        reason="codex-subscription")
            return
        self.p.questions.pose(
            run_id, kind=billing.ASK_API, choices=billing.CHOICES[billing.ASK_API],
            text=(f"Codex paused this run: the ChatGPT subscription it runs on {why}. "
                  "Continue it on the OpenAI API key? That is billed per token to the API "
                  "account, and nothing is billed unless you say yes. It carries on in the same "
                  "conversation and the same checkout."),
            detail=agents.plain(failed.get("message"), 600) or None,
            why=f"subscription: {failed.get('info')}")

    def _offer_fresh(self, run_id: str, failure: str) -> None:
        run = self._run(run_id)
        self.p.questions.pose(
            run_id, kind=billing.ASK_FRESH, choices=billing.CHOICES[billing.ASK_FRESH],
            text=("Codex could not carry this run's conversation over to the OpenAI API key. "
                  "Start a fresh Codex session on the key, in the same checkout? Every file is "
                  "kept, and it is told where the old conversation is so it can read it. It is "
                  "billed per token to the API account."),
            detail=agents.plain(failure, 600) or None,
            why="the conversation was not carried over")
        self.p.tell(run_id, f"{run['title']}: its conversation did not carry over to the API "
                            "key. It is waiting for you to say whether to start it fresh.",
                    reason="codex-resume-failed")

    async def _answered_api(self, question: dict[str, Any], answer: str, by: str) -> None:
        """The person's answer to carrying a run on on the key. Only a yes does anything."""
        run_id = str(question.get("run") or "")
        run = self.views.runs.get(run_id)
        if answer != "yes" or run is None or run["state"] in ENDED:
            return
        why = billing.STOPS.get(str(question.get("why") or "").rpartition(" ")[2], "stopped it")
        session = str(run.get("session_id") or "")
        if not self.p.api_key.available() or not session:
            what = ("no OpenAI API key has reached the program" if session
                    else "the program never learned which conversation it was")
            self.list.append("codex.not-switched", run=run_id, body={"why": what})
            self.p.tell(run_id, f"{run['title']} was not moved onto the API key: {what}. "
                                "It is still paused, and nothing was billed.",
                        reason="codex-subscription")
            return
        self.list.append("run.billing", run=run_id, by=by, body={
            "billing": billing.API, "was": billing.SUBSCRIPTION, "resume": session,
            "stop": why, "why": f"the ChatGPT subscription {why}, and the person said to "
                                "carry on on the OpenAI API key"})
        self._start_again(run_id, by=by, codex_session=session,
                          prompt=billing.CONTINUED.format(why=why),
                          why="carried on in the same conversation on the OpenAI API key")

    async def _answered_fresh(self, question: dict[str, Any], answer: str, by: str) -> None:
        """A fresh session on the key, or the run left as it is."""
        run_id = str(question.get("run") or "")
        run = self.views.runs.get(run_id)
        if run is None or run["state"] in ENDED:
            return
        if answer != "yes":
            if self.p.terminals.get(run_id) is None:
                # Its Codex had already gone: nothing is left to pause, so it
                # ends here, and its checkout is kept or saved the way any
                # run's is.
                await self._end(run, how="stopped", code=None, sig=None, forced=None)
            return
        failure = str(question.get("detail") or "the API refused it")
        brief = str(run.get("brief") or run.get("last_prompt") or "(the task is in the old "
                                                                  "conversation)")
        self.list.append("run.billing", run=run_id, by=by, body={
            "billing": billing.API, "was": run.get("billing_was") or billing.SUBSCRIPTION,
            "fresh": True, "why": "the conversation did not carry over, and the person said "
                                  "to start a fresh one on the key"})
        why = run.get("billing_stop") or "stopped it"
        self._start_again(run_id, by=by, codex_session=None,
                          prompt=billing.FRESH.format(
                              why=why, failure=failure, brief=brief,
                              transcript=run.get("transcript") or "its session file"),
                          why="a fresh Codex session on the OpenAI API key, in the same checkout")

    def _start_again(self, run_id: str, *, by: str, codex_session: str | None, prompt: str,
                     why: str) -> None:
        """Ask Codex to leave at its prompt, then start it again as it now is.

        Never mid-request: the run is paused on a question, at its prompt,
        because the turn it was on has already ended.
        """
        how = {"codex_session": codex_session, "prompt": prompt, "why": why, "by": by}
        terminal = self.p.terminals.get(run_id)
        if terminal is None:
            self._relaunch(run_id, how)
            return
        self.switching[run_id] = how
        self._spawn(self._see_claude_out(run_id, terminal))

    def _relaunch(self, run_id: str, how: dict[str, Any]) -> None:
        self.list.append("run.restarted", run=run_id, by=how.get("by") or "program",
                         body={"why": how["why"], "billing": True})
        self._spawn(self.launch(run_id, resume=True, prompt=how["prompt"],
                                codex_session=how.get("codex_session"),
                                fresh=not how.get("codex_session")))

    # -- files dropped on its terminal (D52) --------------------------------------------------

    async def keep_drops(self, run_id: str, files: list[tuple[str, str, bytes]],
                         *, by: str) -> dict[str, Any]:
        """Files dropped on a run's terminal, put where the run can read them.

        Claude Code turns a pasted path into an attachment, so the file
        itself never travels down the terminal: it is written into the run's
        own folder (``drops.py``) and what comes back is the line to put at
        its prompt, which the page sends as one paste after taking the run's
        keyboard (D46). A paste and not keystrokes, because only a paste is
        attached. No Enter: the person adds their words and sends it.
        """
        run = self._run(run_id)
        if run["state"] in ENDED:
            raise RunError("that run has ended, so there is nothing to attach a file to")
        kept = await self._keep_files(run, files, by=by)
        return {"files": kept, "typed": drops.typed([k["path"] for k in kept])}

    async def _keep_files(self, run: dict[str, Any], files: list[tuple[str, str, bytes]],
                          *, by: str) -> list[dict[str, Any]]:
        """Files written into the run's own ``drops`` folder, each checked first."""
        drops.too_many(len(files))
        folder = drops.folder_for(run)
        checked = [(drops.safe_name(name, drops.check(name, content_type, len(data))), data)
                   for name, content_type, data in files]
        kept: list[dict[str, Any]] = []
        for name, data in checked:
            try:
                path = await self.docs.drop(folder, name, data, space=run["space"])
            except DocumentsError as exc:
                raise RunError(str(exc)) from None
            kept.append({"name": os.path.basename(path), "path": path, "bytes": len(data)})
            self.list.append("file.dropped", run=run["id"], by=by, body=kept[-1])
        return kept

    # -- the end ----------------------------------------------------------------------------

    async def _on_exit(self, terminal, info: dict) -> None:
        run_id = terminal.run_id
        self.p.terminals.forget(run_id)
        run = self.views.runs.get(run_id)
        if run is None or run["state"] in ENDED:
            self._not_handed_over(run_id, "the run ended before its turn did")
            self.stopping.pop(run_id, None)
            self.forced.pop(run_id, None)
            self.switching.pop(run_id, None)
            self._unwatch_codex(run_id)
            return
        self.takeovers.pop(run_id, None)
        self._context.pop(run_id, None)
        self.p.questions.withdraw_run(run_id, "the run ended")
        code, sig = (info or {}).get("code"), (info or {}).get("signal")
        # Asked to end, by this program or by the one before it: never a crash
        # to start again from.
        how = self.stopping.pop(run_id, None) or run.get("close_wanted")
        forced = self.forced.pop(run_id, None)
        switching = self.switching.pop(run_id, None)
        if switching is not None and how is None:
            # It left because it was asked to, so it can start again the way
            # the person chose: on the API key (billing.py).
            self._relaunch(run_id, switching)
            return
        over = (info or {}).get("over_memory")
        if over and how is None:
            # Its holder ended it for holding more memory than a run may
            # (holder.Holder._watch, where there is no cgroup to hold it to).
            # Never started again: it would only grow to the same place.
            await self._end(run, how=OVER_MEMORY, code=code, sig=sig, forced=forced, why=over)
            return
        # The one rule for what an ended run is called, so the list, every
        # screen and what the person is told all say the same thing. A run
        # that was asked to end is done whatever number it gave on the way
        # out; the number itself is kept below either way.
        died_badly = ended_state(run, how or "exited", code, sig) == "failed"
        what = f"signal {sig}" if sig is not None else f"exit code {code}"
        resuming = run_id in self._codex_resuming
        self._codex_resuming.discard(run_id)
        if (died_badly and run.get("billing_resuming")
                and agents.engine_of(run.get("engine")) == "codex"):
            # `codex resume` on the key would not even start. Starting it again
            # the way a crash is would start a new conversation with nobody
            # having said so, so the person is asked instead, and the run
            # waits with its checkout exactly as it was.
            self.list.append("codex.resume-failed", run=run_id, body={
                "why": f"codex resume ended with {what}", "code": code, "signal": sig})
            self._offer_fresh(run_id, f"codex resume ended with {what} before its first turn")
            return
        if died_badly and resuming:
            # Its conversation could not be opened again. Starting it again
            # the way a crash is would only fail the same way, and a fresh
            # Codex would not know what the run did, so it ends, saying so.
            self.list.append("codex.resume-failed", run=run_id, body={
                "why": f"Codex would not open its earlier conversation (codex resume ended "
                       f"with {what}), so no new one was started in its place",
                "code": code, "signal": sig})
            await self._end(run, how=how, code=code, sig=sig, forced=forced,
                            why=f"could not be carried on: Codex would not open its earlier "
                                f"conversation (codex resume ended with {what}), and no new "
                                f"one was started in its place")
            return
        if (died_badly and run["kind"] == "agent" and run.get("session_id")
                and int(run.get("restarts") or 0) < self.s.restarts):
            self.list.append("run.restarted", run=run_id, body={
                "why": f"it stopped by itself with {what}", "code": code, "signal": sig})
            self._spawn(self.launch(run_id, resume=True))
            return
        await self._end(run, how=how, code=code, sig=sig, forced=forced)

    def _sweeps(self, run: dict[str, Any], died_badly: bool) -> bool:
        """Whether a run's end lands what it left: an agent's, in a repository, between turns."""
        return (run["kind"] == "agent" and not died_badly and bool(run.get("repo"))
                and bool(self.s.space(run["space"]).repo) and delivered(run))

    async def _end(self, run: dict[str, Any], *, how: str | None, code: Any, sig: Any,
                   forced: str | None, why: str | None = None) -> None:
        """Call a run whose process has gone ended, saying what it left behind."""
        run_id = run["id"]
        self._unwatch_codex(run_id)
        # Its boxes go first, done, failed or stopped, before anything else is read or said.
        await self._shred_boxes(run)
        self._not_handed_over(run_id, "the run ended before its turn did")
        died_badly = ended_state(run, how or "exited", code, sig) == "failed"
        if run["kind"] == "shell" and self.s.space(run["space"]).repo and run.get("repo"):
            await self._land(run, driving=False)
        # What the run leaves behind is read here, before it is called anything,
        # because that is the whole question: "done" means committed and on
        # main, and a checkout that still holds work says it was not.
        leaves = await self.what_is_left(run)
        if (leaves.get("unsaved") or leaves.get("dirty")) and self._sweeps(run, died_badly):
            # Committed after its last landing, or left in its tree, by a run that
            # had finished its turn: that is its work, and it is landed now, by the
            # same landing, rather than reported as lost (docs/landing-architecture.md,
            # step 3). A run that broke in the middle of a turn is never swept: half
            # a change does not go to main unasked.
            self.list.append("work.swept", run=run_id, body={
                "dirty": bool(leaves.get("dirty")), "unsaved": leaves.get("unsaved")})
            await self._land(run, driving=False)
            leaves = await self.what_is_left(run)
        left = work_left({**leaves, "target": run.get("target")})
        state = ended_state(run, how or "exited", code, sig, left)
        self.list.append("run.ended", run=run_id, body={
            # A run the clock cleaned up with all its work on main is over and
            # not a failure (5cf20ca4, 0b4e1d37 on 2 November 2026).
            "how": how or "exited", "code": code, "signal": sig,
            "ok": state == "done" or (state == "reaped" and not left),
            # Whether any of its work is really on main, and what is still not.
            "saved": bool(run.get("landed")), "target": run.get("target"), **leaves,
            **({"forced": forced} if forced else {}), **({"why": why} if why else {})})
        if state == "reaped" and left:
            # Cleaned up on the clock with its work not on main: that work is
            # in its checkout, which is kept, and somebody has to know.
            self.p.tell(run_id, f"{run['title']} was stopped after "
                                f"{hours(self.s.run_lifetime)} with nothing happening, "
                                f"and {left}.", reason="reaped")
        elif state == "unfinished":
            self.p.tell(run_id, f"{run['title']} ended unfinished: {left}.", reason="unfinished")
        elif state == "lost":
            # Never silent: it says what killed it, and what of its work is left.
            self.p.tell(run_id, f"{run['title']} was lost"
                                + (f": {why}" if why else "") + (f", and {left}." if left else "."),
                        reason="lost")
        elif died_badly and why:
            self.p.tell(run_id, f"{run['title']} {why}.", reason="failed")
        elif died_badly:
            self.p.tell(run_id, f"{run['title']} stopped with an error "
                                f"({'signal ' + str(sig) if sig is not None else 'exit ' + str(code)}).",
                        reason="failed")
        self._spawn(self._tidy(run_id))
        self.p.scheduler.wake()

    # -- tidying away checkouts ---------------------------------------------------------------

    #: A scratch run's folder is kept this long after the run ends, for looking at.
    SCRATCH_KEEP = 7 * 24 * 3600.0

    async def _tidy(self, run_id: str) -> None:
        """``_tidy_once``, never twice at the same time for one run.

        A run's own end tidies it and so does the scheduler's sweep, and when
        the two overlap - a run lost as the program comes back, with the sweep
        starting beside it - both found the checkout there and both wrote it
        down as removed.
        """
        if run_id in self._tidying:
            return
        self._tidying.add(run_id)
        try:
            await self._tidy_once(run_id)
        finally:
            self._tidying.discard(run_id)

    async def _tidy_once(self, run_id: str) -> None:
        """Take an ended run's checkout away once nothing in it is unsaved.

        A workspace run's checkout is a whole copy of the workspace, so it goes
        as soon as the run has ended with everything on main; carrying the run
        on later makes a fresh one. One that still holds commits not on main,
        or changes never committed, is kept, and the list says why, so a
        person can decide what becomes of them. Nothing is ever landed here:
        a run stopped half-way does not put half its work on main. A scratch
        run's folder is kept a week, for looking at. A run in a folder added
        as it is leaves only its own files beside it, and they go as it ends.
        """
        from .listfile import epoch

        run = self.views.runs.get(run_id)
        if not run or run["state"] not in ENDED or run.get("checkout") in ("removed", "kept"):
            return
        cwd = run.get("cwd")
        if not cwd:
            return
        try:
            if run.get("repo"):
                if not os.path.isdir(cwd):
                    return
                status = await self.docs.status(cwd, space=run["space"], target=run.get("target"),
                                                branch=run.get("branch"), flow=run.get("flow"),
                                                landed_head=run.get("landed_head"))
                if not status.get("ok") or not status.get("exists", True):
                    return
                if status.get("dirty") or status.get("unsaved"):
                    why = ("it has changes that were never committed" if status.get("dirty")
                           else f"it has {status['unsaved']} commit(s) that are not on main")
                    self.list.append("checkout.kept", run=run_id, body={"cwd": cwd, "why": why})
                    return
                self._keep_debug_log(run_id, run.get("own") or f"{cwd}/.one")
                got = await self.docs.remove(cwd, run.get("branch"), space=run["space"])
                gone = cwd
            else:
                # The run's own folder goes. In a folder added as it is, that
                # is the one beside it: the person's folder itself never goes
                # (D43), and may be gone already, which left the run's own
                # folder behind for good on 15 September (D44).
                own = run.get("own") or f"{cwd}/.one"
                gone = os.path.dirname(own)
                if not os.path.isdir(gone):
                    return
                ended = epoch(run["ended_at"]) if run.get("ended_at") else time.time()
                if run.get("flow") != "in place" and time.time() - ended < self.SCRATCH_KEEP:
                    return
                self._keep_debug_log(run_id, own)
                got = await self.docs.remove_folder(gone, space=run["space"])
            if got.get("ok"):
                self.list.append("checkout.removed", run=run_id, body={"cwd": gone})
        except Exception:
            log.exception("could not tidy away run %s's checkout", run_id)

    def _keep_debug_log(self, run_id: str, own: str) -> None:
        """Claude Code's own debug log, when there is one, outlives the checkout.

        It is the only record of what Claude Code did with its hooks, and on
        14 September the one that would have explained a missed hook went
        with its checkout.
        """
        source = Path(own) / "claude-debug.log"
        if not source.is_file():
            return
        try:
            shutil.copyfile(source, self.p.terminals.folder(run_id) / "claude-debug.log")
        except OSError as exc:
            log.warning("could not keep run %s's debug log: %s", run_id, exc)

    async def tidy_sweep(self) -> None:
        """Every ended run whose checkout is still there. The scheduler calls this now and then."""
        await self.boxes_sweep()
        for run in list(self.views.runs.values()):
            if (run["state"] in ENDED and run.get("left") and run.get("checkout") == "kept"
                    and run.get("cwd")):
                await self._settle(run)
            if (run["state"] in ENDED and run.get("cwd")
                    and run.get("checkout") not in ("removed", "kept")):
                await self._tidy(run["id"])

    async def _settle(self, run: dict[str, Any]) -> None:
        """A run called unfinished whose work is on its target after all: say so, quietly.

        The record only, never the phone: the person was told once already, and
        what they were told turned out not to be so. Runs 5979a8ce, 9cac1ec6,
        f2f3d5ad and f18345b8 were kept as "never reached main" with every byte
        of their work on main (docs/landing-architecture.md); this is what puts
        them right once the reading of what is left is exact, and what puts
        right any run whose work reaches main some other way later.
        """
        leaves = await self.what_is_left(run)
        if not leaves or leaves.get("dirty") or leaves.get("unsaved"):
            return
        self.list.append("run.settled", run=run["id"], body={
            "why": "everything it committed is on its target", **leaves})
        await self._tidy(run["id"])

    # -- after a restart ----------------------------------------------------------------------

    async def adopt_all(self) -> None:
        """Reconnect to every run that was going when the program stopped."""
        opened = list(self.views.open_runs())
        # The list is read once for all of them. It is read before the program
        # tells systemd it is up, and once for each run it came to over a
        # minute with 35 runs open on 30 September 2026, against systemd's 90
        # seconds to start: one more pass each and the deploy failed.
        wanted = {run["id"] for run in opened}
        entries: dict[str, list[dict[str, Any]]] = {run_id: [] for run_id in wanted}
        went: list[dict[str, Any]] = []
        for entry in self.list.read(kinds=ADOPT_KINDS | PROGRAM_KINDS):
            if entry.get("kind") in PROGRAM_KINDS:
                went = (went + [entry])[-3:]
            elif entry.get("run") in wanted:
                entries[entry["run"]].append(entry)
        cause = why_program_went(went)
        for run in opened:
            run_id = run["id"]
            if run["state"] == "queued":
                continue
            with contextlib.suppress(OSError):
                self.keys[run_id] = (self.p.terminals.folder(run_id) / "hook.key").read_text().strip()
            if run.get("session_id"):
                self._session_seen.add(run_id)
            # What was decided before the restart, so a call that opened then
            # and closes now is not taken for one the program never saw.
            for entry in entries[run_id]:
                if entry.get("kind") in ("tool.opened", "permission.decided"):
                    self._mark_decided(run_id, (entry.get("body") or {}).get("call"))
            terminal = await self.p.terminals.adopt(run_id)
            wanted = run.get("close_wanted")
            if terminal is not None:
                terminal.on_exit = self._on_exit
                self.list.append("run.adopted", run=run_id, body={"holder": terminal.holder_pid})
                if wanted:
                    # Asked to end before the restart, and it had not yet: the
                    # stop the last program did not live to finish, finished.
                    self.stopping[run_id] = wanted
                    self.p.questions.withdraw_run(run_id, "the run is being stopped")
                    self.list.append("run.close-resumed", run=run_id, body={
                        "holder": terminal.holder_pid, "how": wanted,
                        "why": "it was asked to end before the program restarted"})
                    self._close(run_id, terminal)
                    if run["state"] == "saving":
                        self._spawn(self._land_again(run_id))
                    continue
                self._messages_left(run, terminal, entries[run_id])
                if agents.engine_of(run.get("engine")) == "codex":
                    self._watch_codex(run_id)
                if run["state"] == "saving":
                    self._spawn(self._land_again(run_id))
                continue
            asked = self.views.questions.get(run.get("question") or "") or {}
            if asked.get("open") and asked.get("kind") == billing.ASK_FRESH:
                # Paused on whether to start fresh on the key, with no Codex
                # left to adopt: that is how it was left, and still is.
                continue
            info = read_exit(self.p.terminals.folder(run_id))
            if info is not None:
                self.list.append("run.ended", run=run_id, body={
                    "how": wanted or "exited", "code": info.get("code"),
                    "signal": info.get("signal"), "while": "the program was away"})
            elif wanted:
                # Asked to end, and its terminal is gone: ended, as asked. Never
                # started again, which is what a terminal lost by itself gets.
                self.list.append("run.ended", run=run_id, body={
                    "how": wanted, "code": None, "signal": None,
                    "while": "the program was away",
                    "why": "it was asked to end, and its terminal was gone when the program came back"})
            elif (run["kind"] == "agent" and run.get("session_id")
                    and int(run.get("carried") or 0) < self.s.carry_ons):
                # Its terminal's holder went while the program was away and
                # left no exit.json, so it was killed from outside rather than
                # ending by itself: on the server once (14 September), and in
                # the containers every time a deploy restarts the worker
                # container, which takes every holder and run with it. Its
                # conversation and its checkout are still there, so it is
                # carried on from them, and it is not counted against the
                # restarts a crash gets: until 3 November 2026 it was, so three
                # deploys inside four minutes that morning left four runs
                # "lost", with no word anywhere of what had killed them.
                self.list.append("run.restarted", run=run_id, body={
                    "why": f"its process went down with the program ({cause}), and it was carried on",
                    "with_program": True, "cause": cause})
                self._spawn(self.launch(run_id, resume=True,
                                        prompt=agents.CARRIED_ON.format(why=cause)))
            else:
                # Lost, and said why, through the same end as every other run,
                # so what it left is read and the person is told.
                if run["kind"] != "agent" or not run.get("session_id"):
                    why = (f"it went down with the program before it had a conversation "
                           f"to carry on; {cause}")
                else:
                    times = int(run.get("carried") or 0) + 1
                    why = (f"it went down with the program "
                           f"{'once' if times == 1 else f'{times} times'} and was not started "
                           f"again; the last time, {cause}")
                self._spawn(self._end(run, how="lost", code=None, sig=None, forced=None, why=why))
        # Runs that ended but were asked to stay ended, whose terminal is
        # still there: closed the same way, through their own holder's socket.
        for run in list(self.views.runs.values()):
            if (run["state"] in ENDED and run.get("close_wanted")
                    and session_alive(self.p.terminals.folder(run["id"]))):
                await self._close_left_over(run["id"])
        self.p.questions.withdraw_stale("the program restarted, and the run asked again if it still needed to")

    async def _land_again(self, run_id: str) -> None:
        """Finish a landing the program's own restart cut short.

        A run is "saving" from the end of its turn until ``_land`` writes what
        became of its work, and ``_land`` runs inside this program. Landing a
        change to this repository deploys it, and the deploy restarts this
        program, so the landing that pushed the change is the one thing sure
        to be killed before it can say so. Every such run then sat in "saving
        its work" for good: a finished run shown as working, counted as busy
        by the scheduler, and never reported. On 29 September 2026 six of them
        had sat there for up to twelve hours with their work live on main.

        Landing again is safe because land.sh is: work already on the target
        and live is recognised by patch, reported as landed and not deployed a
        second time, and work that never got there lands the ordinary way.
        """
        # Not while that deploy is still going. It restarts this program first
        # and Rouh after, so until it lets go of its lock Rouh is not serving
        # the commit yet, and land.sh would take work that is on its way to
        # being live for work to deploy, and deploy it a second time.
        await deploy_settled()
        run = self.views.runs.get(run_id)
        if not run or run["state"] != "saving" or not run.get("cwd"):
            return
        log.info("run %s was saving when the program stopped; landing it again", run_id)
        follow_up = await self._land(run, driving=False)
        terminal = self.p.terminals.get(run_id)
        if follow_up and terminal is not None:
            # A clash handed back to the run to reconcile, as at a turn's end.
            await self._paste(terminal, follow_up)

    #: How long the program, going away, waits for the runs it is stopping to
    #: be gone. Inside the 20 seconds systemd gives it (TimeoutStopSec).
    SHUTDOWN_GRACE = 10.0

    async def _finish_closing(self) -> None:
        """Wait for every run being asked to end to be gone, before the program goes.

        A deploy restarts the program, and a stop still asking when it does
        was cancelled with everything else, leaving the run going with nobody
        asking any more. So the program waits for each one to end, for as long
        as it has. One that has not ended by then is handed to its holder with
        SIGTERM, which the holder follows with SIGKILL ten seconds later by
        itself, with or without a program. Either way the stop stands on the
        list, and the program that comes back finishes whatever is left.
        """
        pending = {run_id: t for run_id, t in self.closing.items() if not t.done()}
        if not pending:
            return
        log.info("waiting for %d run(s) being stopped to end", len(pending))
        await asyncio.wait(pending.values(), timeout=self.SHUTDOWN_GRACE)
        for run_id, task in pending.items():
            if task.done():
                continue
            terminal = self.p.terminals.get(run_id)
            if terminal is not None:
                log.warning("run %s had not ended as the program stopped; its holder ends it",
                            run_id)
                self.forced[run_id] = "SIGTERM"
                with contextlib.suppress(Exception):
                    await terminal.signal(signal.SIGTERM)
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task

    async def close(self) -> None:
        await self._finish_closing()
        for watcher in list(self.watchers.values()):
            await watcher.stop()
        self.watchers.clear()
        for task in list(self._tasks):
            task.cancel()
        for task in list(self._tasks):
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task


#: The lock ``update-all.sh`` holds for the whole of a deploy, named the way it
#: names it. Readable by every user that lands work, which is all flock needs.
DEPLOY_LOCK = os.environ.get("ROUH_DEPLOY_LOCK") or os.path.join(
    os.environ.get("ROUH_LAND_DIR") or "/srv/rouh-land", "deploy.lock")


async def deploy_settled(*, most: float = 900.0, every: float = 2.0,
                         lock: str | None = None) -> bool:
    """Wait until no deploy holds the deploy lock, for at most ``most`` seconds.

    True once it is free, or when there is no lock here to wait on at all, which
    is a machine with nothing to deploy; False when it was still held at the end.
    """
    path = lock or DEPLOY_LOCK
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return True
    try:
        until = time.monotonic() + most
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
            except BlockingIOError:
                if time.monotonic() >= until:
                    log.warning("a deploy still held %s after %ss", path, int(most))
                    return False
                await asyncio.sleep(every)
                continue
            except OSError:
                return True
            fcntl.flock(fd, fcntl.LOCK_UN)
            return True
    finally:
        os.close(fd)


def _fingerprint(tool: str, tool_input: dict[str, Any]) -> int:
    """A call known by its tool and input, within this process only."""
    return hash((tool, json.dumps(tool_input or {}, sort_keys=True, default=str)))


def _call_in_full(tool: str, tool_input: dict[str, Any]) -> str:
    """A tool call as a person would want to read it before allowing it, secrets hidden."""
    if tool == "Bash":
        text = "$ " + str(tool_input.get("command") or "")
    else:
        shown = {k: v for k, v in tool_input.items()
                 if isinstance(v, (str, int, float, bool)) and k not in ("content", "new_string",
                                                                          "old_string")}
        text = f"{tool} " + json.dumps(shown, ensure_ascii=False)
    return agents.plain(text, 1200)


def _pre_tool_answer(decision: str, why: str) -> dict:
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": decision,
                                   "permissionDecisionReason": why}}


def _codex_signed_in(home: str) -> bool | None:
    """Whether Codex has its ChatGPT login for the user whose home this is: True, False, or None
    when this process may not look (another user's folder, on the server)."""
    folder = codexhome.folder(home)
    try:
        os.stat(os.path.join(folder, "auth.json"))
        return True
    except FileNotFoundError:
        try:
            os.stat(home)
        except OSError:
            return None
        return False
    except OSError:
        return None


def _home_of(user: str | None) -> str:
    if user:
        with contextlib.suppress(KeyError):
            return pwd.getpwnam(user).pw_dir
    return str(Path.home())
