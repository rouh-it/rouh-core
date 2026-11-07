"""The one place reminders and goals are made, changed and said.

The model's tools (`tools.ToolRegistry`) and the two pages (`rouh/web/clock.py`)
both come through here, so "remind me Friday at nine" said out loud and the
same reminder typed into the Reminders page are one thing done two ways, and
both tell every open tab of that person's in the same words.

What it is handed rather than imports is Rouh's own running pieces, by
runtime.py: the open tabs, the turn starter, the chats and the phone. That is
what keeps this file free of the runtime's import, and lets a check of it stand
up a clock with nothing else running.

A goal is a task (`rouh/goals.py`) with one chat, its own, and what is done
here for one is Rouh reading it and asking in that chat, and working its steps:
each step Rouh takes up is a background run (`start_run`), now, at a time (a
job of kind `do` whose turn starts it), or once another step is complete, and
when the run ends the step says what needs the person and a line says so in the
goal's chat (`run_finished`).

Saying a due row is `deliver`:

1. It is handed to Rouh in its chat, as a turn of Rouh's own started by a
   note (`reminders.note_for`), once that chat is not in the middle of another
   answer. The turn runs with the person's identity, so the tools act for them,
   and marked as unattended, so it may do anything but the two protected
   groups - money and commitments, and permanent deletion; work on Rouh
   itself goes on the person's own words stored with the row (`rouh/protected.py`). What to do is Rouh's to decide: a
   line to the phone with `send_telegram`, a few tools, or a run
   (fr_0d01a6cf1316). What it did is written down as it does it
   (`reminders.HANDLING`), and the person's own words stored with the row
   (`reminders.asked_of`) go with it: on them alone the turn may share and
   give or take a trusted contact's authority, as they asked.
2. A reminder whose turn sent nothing to the phone goes there anyway, as the
   plain line it used to be ("⏰ Call the dentist"), so a turn that failed or
   forgot never loses it. A job's answer goes to the phone when it is done,
   unless it found nothing new or Rouh already sent one itself.
3. What happened is written on the row, for the list to show.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from typing import Awaitable, Callable, Iterable

from . import clock, events, goals, protected, reminders

log = logging.getLogger("rouh.timekeeper")


#: What a step or a stream asked for while its goal is paused is told.
PAUSED_WORDS = ("This goal is paused, so nothing of it starts. The person resumes it on the "
                "goal's own page.")


def _flat_steps(v: dict) -> list[dict]:
    out: list[dict] = []

    def walk(items):
        for s in items:
            out.append(s)
            walk(s.get("parts") or [])
    walk(v.get("steps") or [])
    return out


class Timekeeper:
    def __init__(self, *, memory, telegram, public_url: str,
                 tabs: Callable[[], Iterable],
                 start_turn: Callable[[str, str], Awaitable],
                 busy: Callable[[str], bool],
                 new_chat: Callable[..., Awaitable[str]],
                 identity_of: Callable[[str], object],
                 start_run: Callable[..., Awaitable[str]] | None = None,
                 say: Callable[[str, str], Awaitable] | None = None,
                 server_jobs: dict[str, Callable[..., Awaitable[str]]] | None = None):
        self.memory = memory
        self.telegram = telegram
        self.public_url = (public_url or "").rstrip("/")
        self.tabs = tabs
        self.start_turn = start_turn
        self.busy = busy
        self.new_chat = new_chat
        self.identity_of = identity_of
        #: Starts one background run for a step: (brief, title, goal, chat)
        #: to its run id (`runtime._goal_run`). None where nothing can run one.
        self.start_run = start_run
        #: Writes one line of Rouh's into a chat and every tab standing in it.
        self.say = say
        #: Rouh's own server jobs by name, for rows of kind `server`: each is started with
        #: (who, trying) and answers the line the Reminders page shows after "Last time, ...:".
        self.server_jobs = dict(server_jobs or {})
        self.clock = reminders.Clock(self.deliver)
        #: One per chat, held from looking for the chat to be free until its
        #: turn is on the register. Without it two reminders due in the same
        #: second both found the chat free, and the second turn started
        #: cancelled the first, as if the person had talked over it.
        self.starting: dict[str, asyncio.Lock] = {}
        #: One per goal, held while its streams are looked over and their
        #: next steps marked on it, so two starts at once never start one twice.
        self.streaming: dict[str, asyncio.Lock] = {}

    def start(self) -> None:
        self.clock.start()
        self.mending = asyncio.create_task(self._mend(), name="goal results")

    async def _mend(self) -> None:
        """Steps Rouh marked done before their results were kept get them now (`goals.mend`),
        and the chats streams were worked in leave the chat list (`goals.retire_stream_chats`)."""
        try:
            gone = await asyncio.to_thread(goals.retire_stream_chats)
            if gone:
                log.info("took %d stream chat(s) out of the chat list: %s", len(gone),
                         ", ".join(gone))
        except Exception:
            log.exception("the goals' stream chats could not be taken out of the chat list")
        try:
            wrote = await asyncio.to_thread(goals.mend)
        except Exception:
            log.exception("the goal steps' results could not be mended")
            return
        if wrote:
            log.info("wrote the results of %d goal step(s) into their folders", wrote)
        try:
            # Steps that waited on the person only to look Rouh's work over are
            # complete, and their goals go on (fr_5404edbbea30).
            settled = await asyncio.to_thread(goals.settle)
        except Exception:
            log.exception("the goal steps waiting on a review could not be settled")
            return
        for goal, row in settled:
            await self.carry_on(None, goal, row)

    async def stop(self) -> None:
        await self.clock.stop()

    # --- the person's tabs ---------------------------------------------------

    def summary(self, who) -> dict:
        """What the sidebar's two rows say: the next reminder, and the goals."""
        with clock.person(who):
            return self._summary(who)

    def _summary(self, who) -> dict:
        live = [r for r in reminders.rows(who, include_done=False) if r.state == "on"]
        nxt = min(live, key=lambda r: r.next_at or 9e18) if live else None
        views = goals.listing(who)
        return {
            "reminders": {"count": len(live),
                          "next": reminders.view(nxt) if nxt is not None else None},
            "goals": {"count": len(views),
                      "open": sum(1 for g in views if g["status"] != "done")},
            "telegram": bool(self.telegram and self.telegram.configured()),
        }

    async def tell(self, who, *, shown: dict | None = None) -> None:
        """Every open tab of this person's hears that something changed.

        Only that person's: another account on the same Rouh has reminders of
        its own, and is told nothing about these.
        """
        if who is None:
            return
        said = dict(await asyncio.to_thread(self.summary, who), type="clock")
        for tab in list(self.tabs()):
            me = getattr(tab, "me", None)
            if getattr(tab, "closed", True) or me is None:
                continue
            if (me.user_id, me.org_id) != (who.user_id, who.org_id):
                continue
            with contextlib.suppress(Exception):
                await tab.emit(said)

    # --- reminders ---------------------------------------------------------------

    async def schedule(self, who, *, what: str, title: str = "", kind: str = "remind",
                       chat: str = "", at: str = "", in_minutes=None, repeat: str = "once",
                       days=(), asked=(), owner_contact_id=None, **theirs):
        """A new row. `theirs` is what an item made for a trusted contact says of itself:
        goes_to, uses, message, channel and case_id (`reminders.add`)."""
        first = reminders.moment_of(at, in_minutes)
        row = await asyncio.to_thread(reminders.add, who, what=what, title=title, kind=kind,
                                      chat_id=chat or "", first=first, repeat=repeat,
                                      days=days, asked=asked, owner_contact_id=owner_contact_id,
                                      **theirs)
        self.clock.poke()
        await self.tell(who)
        return row

    async def change(self, who, row_id, **fields):
        first = None
        if fields.get("at") or fields.get("in_minutes") not in (None, ""):
            first = reminders.moment_of(fields.get("at") or "", fields.get("in_minutes"))
        row = await asyncio.to_thread(
            reminders.change, who, row_id, what=fields.get("what"), title=fields.get("title"),
            first=first,
            repeat=fields.get("repeat"), days=fields.get("days"), kind=fields.get("kind"),
            state=fields.get("state"), asked=fields.get("asked"),
            goes_to=fields.get("goes_to"), uses=fields.get("uses"),
            message=fields.get("message"), channel=fields.get("channel"),
            about_rouh=fields.get("about_rouh"))
        if row is not None:
            self.clock.poke()
            await self.tell(who)
        return row

    async def drop(self, who, row_id) -> bool:
        gone = await asyncio.to_thread(reminders.drop, who, row_id)
        if gone:
            self.clock.poke()
            await self.tell(who)
        return gone

    async def try_now(self, who, row_id):
        """Say one row now, to see how it arrives, leaving its time as it was."""
        row = await asyncio.to_thread(reminders.one, who, row_id)
        if row is None:
            return None
        self.clock.run(row, trying=True)
        return row

    # --- goals (`rouh/goals.py`) ---------------------------------------------------

    async def _turn(self, who, chat: str, note: str, *, unattended: bool):
        """A turn of Rouh's own in `chat`, for `who`, once the chat is free.

        Unattended is a turn nobody asked for just now, so the tools that act
        outside Rouh are neither offered nor callable (`reminders.UNATTENDED`).
        """
        from .tenancy import SPEAKER

        async with self.starting.setdefault(chat, asyncio.Lock()):
            waited = 0.0
            while self.busy(chat) and waited < reminders.FREE_WAIT:
                await asyncio.sleep(2.0)
                waited += 2.0
            speaker_was = SPEAKER.set(who)
            away_was = reminders.UNATTENDED.set(bool(unattended))
            try:
                return await self.start_turn(chat, note)
            finally:
                reminders.UNATTENDED.reset(away_was)
                SPEAKER.reset(speaker_was)

    async def set_goal(self, who, *, name: str, about: str) -> dict:
        """A goal: its task, its chat, and Rouh reading it and asking, in that chat.

        The turn is started and not waited for: the page opens the chat and
        watches the answer arrive there.
        """
        made = await asyncio.to_thread(goals.create, name, about)
        task = made["task"]
        # Made, owned by the task and written into it by the runtime, which
        # then files the new task into a project: its folder may move, so it is
        # read again rather than trusted from before.
        chat = await self.new_chat("\U0001f3af " + task.title, task.id)
        task = await asyncio.to_thread(self._task, task.id) or task
        v = await asyncio.to_thread(goals.view, task)
        v["about"] = v["about"] or goals._words(about, goals.MAX_ABOUT)
        await self._turn(who, chat, goals.note_to_understand(v), unattended=False)
        await self.tell(who)
        return {"goal": task, "chat": chat, "view": v}

    async def _goal_and_step(self, goal, step_id: str):
        v = await asyncio.to_thread(goals.view, goal)
        step = goals.step_in(v, step_id)
        if step is None:
            raise goals.Refused("That step is not part of this goal any more.")
        return v, step

    async def do_step(self, who, goal, step_id: str, *, why: str, unattended: bool) -> None:
        """Rouh does one step now, as a background run owned by the goal's task.

        Never in a chat: the goal has one, its own, and a step's work is a run
        like any job, on the orb, side by side with the other streams' runs
        (`goals.brief_for_step`). `unattended` is kept for the callers; a run
        is always told nobody is watching.
        """
        v, step = await self._goal_and_step(goal, step_id)
        if v.get("paused"):
            raise goals.Refused(PAUSED_WORDS)
        if step.get("who") == goals.QUEST:
            # The quest's own beats do it; a run of the goal's would be a
            # second executor beside the quest, round its budget and pause.
            raise goals.Refused(f"\u201c{step['title']}\u201d is the quest's to do, in its "
                                "own beats; the goal does not start it as a run.")
        if self.start_run is None:
            raise goals.Refused("Nothing on this machine can run a step in the background.")
        await self._drop_scheduled(who, step)
        row = await asyncio.to_thread(self._task, step_id)
        # How it stood, put back if no run starts: a step Rouh had done its
        # part of keeps its results rather than reading as under way.
        was = await asyncio.to_thread(goals.step_state, row)
        await asyncio.to_thread(goals.change_step, row, status="in-progress",
                                run={"mode": "now"})
        brief = goals.brief_for_step(v, step, why=why)
        title = f"{v['title']} \u00b7 {step['title']}"[:80]
        try:
            job = await self.start_run(brief, title, goal, v["chat"])
        except Exception as exc:
            await asyncio.to_thread(goals.put_back, row, was)
            await self.tell(who)
            raise goals.Refused(f"The run for \u201c{step['title']}\u201d could not be "
                                f"started: {exc}") from exc
        await asyncio.to_thread(
            goals.change_step, row, run={"mode": "now", "job": job},
            job={"id": job, "by": getattr(who, "user_id", "") or "",
                 "at": int(time.time())})
        log.info("step %s of goal %s is run %s", step_id, goal.id, job)
        await self.tell(who)

    async def run_finished(self, job_id: str, final: str = "", *, ok: bool = True,
                           why: str = "") -> bool:
        """A background run has ended. True when it was a goal step's, and handled.

        Called by whatever reports a finished run (`assistant_job.Lander`,
        `one_jobs.OneLander`) before it draws or says anything: a step's run
        draws no card anywhere. What it made in the step's folder is the
        step's result, on its own page; the step says what now needs the
        person (`goals.run_finished`); and one short line goes into the goal's
        own chat saying what finished and what needs them.
        """
        step, goal = await asyncio.to_thread(goals.step_of_job, job_id)
        if step is None:
            return False
        done = await asyncio.to_thread(goals.run_finished, step, final, ok=ok, why=why)
        v = await asyncio.to_thread(goals.view, goal)
        s = goals.step_in(v, step.id) or {"n": "", "title": step.title}
        head = f"Step {s['n']} \u201c{s['title']}\u201d"
        if done["status"] == "complete":
            line = (f"{head} finished its run after you marked it complete, and it stays "
                    "complete" + (": what it made is on the step's page." if done["result"]
                                  else "."))
        elif done["status"] == "done":
            line = (f"{head} is complete: what Rouh made is on the step's page."
                    if done["result"] else f"{head} is complete.")
        elif done["status"] == "yours":
            line = (f"{head}: Rouh's part is done, and its explainer is on the step's page."
                    if done["result"] else f"{head}: Rouh's part is done.")
            need = (s.get("needs") or {})
            if need.get("words"):
                words = need["words"].rstrip()
                line += (f" {need.get('label') or 'Needs you'}: {words}"
                         + ("" if words.endswith((".", "?", "!")) else "."))
                if s.get("options"):
                    line += " Options: " + "; ".join(s["options"]) + "."
        else:
            line = f"{head} stopped and needs you: {done['needs']}"
        if self.say is not None and v["chat"]:
            try:
                await self.say(v["chat"], line)
            except Exception:
                log.exception("the line about step %s could not go into its goal's chat", step.id)
        meta = await asyncio.to_thread(goals._meta, goals._folder(step))
        by = ((meta.get("goal_step") or {}).get(goals.JOB) or {}).get("by") or ""
        who = await asyncio.to_thread(self.identity_of, by) if by else None
        if done["status"] == "done":
            # Complete without asking him (fr_5404edbbea30): the goal goes on.
            await self.carry_on(who, goal, step)
        await self.tell(who)
        return True

    async def schedule_step(self, who, goal, step_id: str, *, first) -> None:
        """Rouh does one step at a time: a job of kind `do`, in the goal's chat."""
        v, step = await self._goal_and_step(goal, step_id)
        await self._drop_scheduled(who, step)
        # Said on the Reminders page as well as to Rouh, so in words: the turn
        # it starts is in the goal's own chat, which is told the whole plan
        # with every step's id (`goals.block`).
        what = (f"Step {step['n']} of the goal \u201c{v['title']}\u201d: {step['title']}."
                + (f" How: {step['how']}" if step["how"] else ""))[:reminders.MAX_WHAT - 140]
        what += (" Start it now with goal_step and run now, which works it as a background "
                 "run; do not do the step in this chat.")
        title = f"{step['title']} (step {step['n']} of the goal \u201c{v['title']}\u201d)"
        row = await asyncio.to_thread(reminders.add, who, what=what, title=title, kind="do",
                                      chat_id=v["chat"], first=first)
        task = await asyncio.to_thread(self._task, step_id)
        await asyncio.to_thread(goals.change_step, task,
                                run={"mode": "at", "reminder": row.id})
        self.clock.poke()
        await self.tell(who)

    async def step_after(self, who, goal, step_id: str, after_id: str) -> None:
        """Rouh does one step as soon as another one is marked done."""
        v, step = await self._goal_and_step(goal, step_id)
        if after_id == step_id or goals.step_in(v, after_id) is None:
            raise goals.Refused("Pick another step of this goal to wait for.")
        await self._drop_scheduled(who, step)
        task = await asyncio.to_thread(self._task, step_id)
        await asyncio.to_thread(goals.change_step, task,
                                run={"mode": "after", "after": after_id})
        if goals.step_in(v, after_id)["status"] == "done":
            await self.do_step(who, goal, step_id, unattended=False,
                               why="The step it waits for is already done.")
            return
        await self.tell(who)

    async def clear_step_run(self, who, goal, step_id: str) -> None:
        _v, step = await self._goal_and_step(goal, step_id)
        await self._drop_scheduled(who, step)
        task = await asyncio.to_thread(self._task, step_id)
        await asyncio.to_thread(goals.change_step, task, run={})
        await self.tell(who)

    async def step_status(self, who, goal, step_id: str, status: str, *,
                          by_person: bool = False, left=None) -> list:
        """A step's status, and every step waiting on it started once it is complete.

        Done is complete, from the person (`by_person`) or from Rouh; from
        Rouh with `left`, a decision or action of the person's, it is Rouh's
        part done and the step waits on them for that (`goals.ROUH_DONE`).
        What was started is handed back, for the caller to say.
        """
        task = await asyncio.to_thread(self._task, step_id)
        if task is None:
            raise goals.Refused("That step is not there any more.")
        block = await asyncio.to_thread(goals.change_step, task, status=status,
                                        left=left, by_person=by_person)
        started = []
        if block.get("done_by") in goals.DONE_BY:
            started = await self.carry_on(who, goal, task)
        await self.tell(who)
        return started

    async def carry_on(self, who, goal, task) -> list:
        """A step is complete: the steps set to follow it start, and so does the
        next step of every stream Rouh can take up. Returns those set to follow."""
        started = []
        _v, step = await self._goal_and_step(goal, task.id)
        await self._drop_scheduled(who, step)
        for nxt in await asyncio.to_thread(goals.waiting_on, goal, task.id):
            # Nobody pressed anything just now, so it runs the way a
            # scheduled job does: anything but the two protected groups
            # (`rouh/protected.py`).
            # Started in the background: this may itself be inside the
            # turn in that very chat, which the new turn waits to be free.
            asyncio.ensure_future(self._after_done(who, goal, nxt.id, task.title))
            started.append(nxt)
        # The stream goes on: its next step, if Rouh can take it up and it
        # was not set to follow this one already (just above).
        asyncio.ensure_future(self.start_streams_quietly(
            who, goal, f"\u201c{task.title}\u201d is complete, and this step comes next "
                       "in its stream. " + protected.WORDS))
        await self._tell_quest(goal, task)
        return started

    async def _tell_quest(self, goal, task) -> None:
        """A step of the goal's quest made ready by this one: the quest hears it.

        A step that is the quest's is never started as a run (`do_step`), so its next
        beat is told instead: an event on the quest (`heartbeat.Heartbeat.event`), which
        wakes that beat under every rule a beat keeps - quiet hours, a pause, its budget,
        the daily cap and the flood guard - and is handed what was completed and what
        Petar wrote there (`questcheck.step_completed`). Nothing is started here."""
        from . import heartbeat, questcheck

        pulse = heartbeat.LIVE
        if pulse is None:
            return
        try:
            woken = await asyncio.to_thread(questcheck.step_completed, goal, task)
            owner = await pulse._who() if woken else None
        except Exception:
            log.exception("the quest of goal %s could not be told a step is complete", goal.id)
            return
        for work, words, more in woken:
            if owner is None or (str(work.user_id), str(work.org_id)) != (
                    str(owner.user_id), str(owner.org_id)):
                continue
            await pulse.event("goal", words, work_id=work.id, **more)

    async def let_go(self, who, goal, stream_id: str = "") -> list:
        """Rouh goes on by itself with a stream, or with every stream it can.

        Petar, 27 September 2026 (fr_b083c37a634d): "everything that can be
        done without me should be done without me." What a plan does by
        itself (`start_streams`), pressed: it also takes up again a step whose
        turn ended without Rouh's part done. Returns the steps started now.
        """
        if await asyncio.to_thread(goals.is_paused, goal):
            raise goals.Refused(PAUSED_WORDS)
        heads = await self.start_streams(
            who, goal, stream_id=stream_id, again=True, unattended=False,
            why="The person let you carry on with this part of the plan by yourself.")
        if not heads:
            raise goals.Refused("Nothing there is Rouh's to do by itself just now."
                                if stream_id else
                                "No stream has a step Rouh can do by itself just now.")
        return heads

    async def start_streams(self, who, goal, *, why: str, unattended: bool = True,
                            stream_id: str = "", again: bool = False) -> list:
        """Every stream whose next step Rouh can take up, started at once.

        Petar, 27 September 2026 (fr_a25fe6a202a3): "whatever the plan, should
        start executing in parallel all tasks that are in different streams.
        Basically streams are groups that are not blocking each other and can
        work in parallel." So this is called the moment a plan is written or
        rearranged, and when a step is marked complete, and nobody is asked
        first. Each stream's next step (`goals.can_start`) is started as a
        background run of its own (`do_step`), all of them side by side; the steps of Rouh's
        straight after it are set to start once the one before is complete
        (`step_after`), so a stream carries on until it comes to something
        only the person can do or decide. A stream whose next step is theirs
        waits on them. Returns the steps started.
        """
        async with self.streaming.setdefault(goal.id, asyncio.Lock()):
            # Read with the person's reminders: without them a step set for a
            # time reads as set for nothing, and was started at once.
            v = await asyncio.to_thread(self._view_for, who, goal)
            if v["stage"] != "planned" or not v["chat"] or v.get("paused"):
                return []
            heads = []
            for lane in v["streams"]:
                if stream_id and lane["id"] != stream_id:
                    continue
                steps = [goals.step_in(v, ident) for ident in lane["steps"]]
                at = next((i for i, s in enumerate(steps) if s and s["id"] == lane["head"]),
                          None)
                if at is None or not goals.can_start(steps[at], again=again):
                    continue
                before = steps[at]
                for nxt in steps[at + 1:]:
                    if nxt is None or not goals.can_start(nxt):
                        break
                    row = await asyncio.to_thread(self._task, nxt["id"])
                    await asyncio.to_thread(goals.change_step, row,
                                            run={"mode": "after", "after": before["id"]})
                    before = nxt
                heads.append(steps[at])
            # Every one says Rouh is on it before any turn starts, which is
            # also what keeps a second start from taking it up again. How it
            # stood first is kept, to be put back if its run never starts.
            was = {}
            for s in heads:
                row = await asyncio.to_thread(self._task, s["id"])
                was[s["id"]] = await asyncio.to_thread(goals.step_state, row)
                await asyncio.to_thread(goals.change_step, row, status="in-progress",
                                        run={"mode": "now"})
        if not heads:
            return []
        await self.tell(who)
        started = await asyncio.gather(
            *(self.do_step(who, goal, s["id"], why=why, unattended=unattended) for s in heads),
            return_exceptions=True)
        for s, went in zip(heads, started):
            if isinstance(went, BaseException):
                log.error("step %s of goal %s could not be started: %s", s["id"], goal.id, went)
                # Not left saying Rouh is on it: it stands as it did, so the
                # page never counts a step as under way that nothing is running.
                row = await asyncio.to_thread(self._task, s["id"])
                if row is not None:
                    await asyncio.to_thread(goals.put_back, row, was[s["id"]])
        return [s for s, went in zip(heads, started) if not isinstance(went, BaseException)]

    async def start_streams_quietly(self, who, goal, why: str) -> None:
        """`start_streams` in the background, for a caller that must not wait on it."""
        try:
            await self.start_streams(who, goal, why=why)
        except Exception:
            log.exception("the streams of goal %s could not be started", goal.id)

    async def _after_done(self, who, goal, step_id: str, done_title: str) -> None:
        if await asyncio.to_thread(goals.is_paused, goal):
            # Left set to follow; resuming the goal starts it (`resume`).
            return
        try:
            await self.do_step(who, goal, step_id, unattended=True,
                               why=f"\u201c{done_title}\u201d is done, and this step was "
                                   "set to start after it. " + protected.WORDS)
        except Exception:
            log.exception("a goal step set to follow another could not be started")

    # --- the person holding and steering a goal ---------------------------------

    async def pause(self, who, goal) -> bool:
        """The person holds the goal: nothing of it starts until they resume it.

        Every stream (`start_streams`), step set to follow another
        (`_after_done`) and step pressed or asked for (`do_step`) is refused
        while it is paused, and a step set for a time has its reminder paused
        too, so its turn never comes round to be refused. A run already under
        way is left to finish, as a dot's delegated tasks are when it is
        paused; it reports in the goal's chat as always. Returns whether it changed.
        """
        changed = await asyncio.to_thread(goals.set_paused, goal, True)
        if not changed:
            return False
        for reminder in await asyncio.to_thread(goals.scheduled_reminders, goal):
            await self._hold(who, reminder, "paused")
        v = await asyncio.to_thread(goals.view, goal)
        await self._line(v, "You paused this goal. Nothing new starts until you resume it"
                            + (", and the runs already under way finish and report here."
                               if any((s.get("run") or {}).get("mode") == "now"
                                      for s in _flat_steps(v)) else "."))
        await self.tell(who)
        return True

    async def resume(self, who, goal) -> list:
        """The goal goes on: its held reminders come back on, a step whose
        step-to-follow was completed meanwhile starts, and so does every
        stream Rouh can take up. Returns the steps started."""
        changed = await asyncio.to_thread(goals.set_paused, goal, False)
        if not changed:
            return []
        for reminder in await asyncio.to_thread(goals.scheduled_reminders, goal):
            await self._hold(who, reminder, "on")
        v = await asyncio.to_thread(goals.view, goal)
        started = []
        why = "The person resumed this goal from its page. " + protected.WORDS
        for s in _flat_steps(v):
            run = s.get("run") or {}
            if run.get("mode") == "after":
                after = goals.step_in(v, run.get("after") or "")
                if after is not None and after["status"] == "done" and not after["hollow"]:
                    try:
                        await self.do_step(who, goal, s["id"], why=why, unattended=True)
                        started.append(s)
                    except goals.Refused as exc:
                        log.warning("step %s could not be started on resume: %s", s["id"], exc)
        started += await self.start_streams(who, goal, why=why)
        await self._line(v, "You resumed this goal"
                            + (": Rouh took up " + ", ".join(
                                f"step {x['n']} \u201c{x['title']}\u201d" for x in started)
                               + "." if started else "."))
        await self.tell(who)
        return started

    async def redirect(self, who, goal, said: str) -> str:
        """The person steers the goal: their words are kept on it (`goals.DIRECTION`),
        every run started from now on is told them first, and Rouh looks over the
        plan against them in the goal's chat, in a turn nobody is watching, so it
        may do anything but the three protected groups (`rouh/protected.py`)."""
        kept = await asyncio.to_thread(goals.set_direction, goal, said)
        if not kept:
            raise goals.Refused("Say how the goal should change first.")
        v = await asyncio.to_thread(goals.view, goal)
        await self.tell(who)
        if v["chat"]:
            asyncio.ensure_future(self._redirect_turn(who, v, kept))
        return kept

    async def _redirect_turn(self, who, v: dict, said: str) -> None:
        handling = reminders.Handling()
        handling_was = reminders.HANDLING.set(handling)
        try:
            turn = await self._turn(who, v["chat"], goals.note_to_redirect(v, said),
                                    unattended=True)
        except Exception:
            log.exception("Rouh could not look over goal %s after it was redirected", v["id"])
            return
        finally:
            reminders.HANDLING.reset(handling_was)
        if turn is not None and getattr(turn, "task", None) is not None:
            await asyncio.wait({turn.task}, timeout=reminders.TURN_LIMIT)
        await self._say_outward(v["chat"], handling, f"\U0001f3af {v['title'][:80]}")

    async def _said_quietly(self, chat: str, line: str) -> None:
        try:
            await self.say(chat, line)
        except Exception:
            log.exception("what an unattended turn did could not be said in its chat")

    async def _say_outward(self, chat: str, handling, head: str) -> bool:
        """Everything a turn nobody watched did outside Rouh, in its chat and as a notice.

        Said by the code, not left to the model's answer, so nothing it sent,
        changed, shared or published goes unsaid. True when the phone had it.
        """
        report = reminders.outward_report(handling)
        if not report:
            return False
        if self.say is not None and chat:
            with contextlib.suppress(Exception):
                await self.say(chat, report)
        link = f"\n\n{self.public_url}/chat/{chat}" if self.public_url and chat else ""
        return await self.phone(f"{head}\n\n{report}{link}")

    async def _hold(self, who, reminder: str, state: str) -> None:
        """A step's reminder paused or back on; one already said or gone is left be."""
        try:
            row = await asyncio.to_thread(reminders.one, who, reminder)
            if row is not None and row.state in ("on", "paused") and row.state != state:
                await self.change(who, reminder, state=state)
        except ValueError as exc:
            log.warning("the reminder %s of a goal step could not be set %s: %s",
                        reminder, state, exc)

    async def _line(self, v: dict, line: str) -> None:
        """One line into the goal's chat, not waited for: `say` waits for the chat
        to be free, and Rouh pausing a goal from that very chat is its turn."""
        if self.say is None or not v.get("chat"):
            return

        async def said() -> None:
            try:
                await self.say(v["chat"], line)
            except Exception:
                log.exception("a line could not go into the chat of goal %s", v["id"])
        asyncio.ensure_future(said())

    async def _drop_scheduled(self, who, step: dict) -> None:
        run = step.get("run") or {}
        if run.get("mode") == "at" and run.get("reminder"):
            await asyncio.to_thread(reminders.drop, who, run["reminder"])
            self.clock.poke()

    @staticmethod
    def _view_for(who, goal) -> dict:
        by_id = ({r.id: r for r in reminders.rows(who, include_done=False)}
                 if who is not None else {})
        return goals.view(goal, reminders_by_id=by_id)

    @staticmethod
    def _task(task_id: str):
        st = goals._store()
        return st.get_task(task_id) if st is not None else None

    # --- saying a due row ------------------------------------------------------

    def _chat_or_general(self, chat: str) -> str:
        if chat and self.memory.chat(chat) is not None:
            return chat
        return self.memory.ensure_general()

    def _chat_named(self, chat: str) -> str:
        row = self.memory.chat(chat) or {}
        if row.get("id") == self.memory.ensure_general() or chat == self.memory.ensure_general():
            return "General"
        return row.get("title") or "its chat"

    async def phone(self, text: str) -> bool:
        """A reminder for the person: on their screen first, and on their phone if it is left
        there (`rouh/notices.py`)."""
        from . import notices

        return await notices.phone(text, kind="reminder") is not None

    async def _server_job(self, row, who, *, trying: bool) -> None:
        """One of Rouh's own server jobs, started by code at its time: no chat turn, nothing said in a chat.

        What it did is written on the row, for the Reminders page, and the job keeps its own record (the
        nightly Synapse run: the attempts table and the morning brief's Report)."""
        job = self.server_jobs.get(getattr(row, "job", "") or "")
        began = time.monotonic()
        line = (await _server_job_line(job, who, trying) if job is not None
                else f"not started: no job called {getattr(row, 'job', '') or '(none)'} on this server")
        events.emit("schedule.ran", who=who, actor="system", source="scheduler",
                    object_type="work", object_id=getattr(row, "job", "") or "",
                    duration_ms=(time.monotonic() - began) * 1000,
                    props={"outcome": "failed" if line.startswith(("could not", "not started"))
                           else "done", "tried_now": bool(trying)})
        if trying:
            line = "tried now, " + line
        await asyncio.to_thread(reminders.said, row.id, line)
        await self.tell(who)

    async def deliver(self, row, *, due_at: float | None = None, trying: bool = False) -> None:
        who = await asyncio.to_thread(self.identity_of, row.user_id)
        if who is None or getattr(who, "org_id", "") != row.org_id:
            await asyncio.to_thread(reminders.said, row.id, "not said: its person is gone")
            return
        events.emit("reminder.fired", who=who, actor="system", source="scheduler",
                    object_type="reminder", object_id=row.id,
                    props={"kind": str(row.kind or "")[:20], "tried_now": bool(trying)})
        if row.kind == reminders.SERVER:
            await self._server_job(row, who, trying=trying)
            return
        # A trusted contact's item: checked against what they hold now, and what goes to them
        # goes through the one outbox (Petar, 12 October 2026, `rouh/clockwork_grants.py`).
        theirs = None
        if getattr(row, "owner_contact_id", None):
            theirs = await self._theirs(row, who, due_at=due_at, trying=trying)
            if theirs is None:
                return
        chat = await asyncio.to_thread(self._chat_or_general, row.chat_id)
        where = await asyncio.to_thread(self._chat_named, chat)

        # Handed to Rouh, in the chat, once it is free (`_turn`): starting a
        # turn in a chat that is being answered would stop that answer. What
        # the turn does is written into `handling` as it does it; the turn's
        # task takes a copy of this context, and the record is the same object.
        phone_ready = bool(self.telegram and self.telegram.configured())
        # The person's own words stored with it, the only ones on which its turn may give
        # or take a contact's authority (`tools.ToolRegistry._delegate`).
        handling = reminders.Handling(asked=reminders.asked_of(row))
        handling_was = reminders.HANDLING.set(handling)
        # The reminder's own title and words are the person's, so automatic recall looks up what they name,
        # as it does for a message of theirs (Petar, 10 October 2026: "I think Clockwork should also use the
        # synapse"); the note around them is Rouh's and is not looked up (`autorecall.WORDS`).
        from .synapse import autorecall

        words_was = autorecall.WORDS.set(
            " ".join(w for w in (reminders.title_of(row), reminders.details_of(row)) if w))
        # A contact's "do" item works with the tools of the grants it uses and nothing else, held
        # like a case's work, so no hard limit is in reach (`clockwork_grants.turn_for`).
        from . import mail_turn

        held_was = mail_turn.CURRENT.set(theirs["turn"]) if theirs and theirs.get("turn") \
            else None
        # What the turn makes - a task, a run and what the run brings in - is Clockwork's
        # scheduled work, out of his own task list (`rouh/task_origin.py`).
        from . import task_origin

        making = task_origin.making("clockwork", f"Clockwork's item {row.id}")
        making.__enter__()
        try:
            turn = await self._turn(who, chat, reminders.note_for(
                row, due_at=due_at, trying=trying, phone=phone_ready), unattended=True)
        finally:
            making.__exit__(None, None, None)
            if held_was is not None:
                mail_turn.CURRENT.reset(held_was)
            autorecall.WORDS.reset(words_was)
            reminders.HANDLING.reset(handling_was)
        answer = ""
        if turn is not None and getattr(turn, "task", None) is not None:
            # Waited for without taking on how it ended: a turn cut short (the
            # person talking in that chat) must still end in a line on the row
            # and the phone, never in this raising and the reminder being lost.
            await asyncio.wait({turn.task}, timeout=reminders.TURN_LIMIT)
            answer = "".join(getattr(turn, "said", []) or []).strip()

        link = f"\n\n{self.public_url}/chat/{chat}" if self.public_url else ""
        # Everything it did outside Rouh, said by the code in the chat and on
        # the phone, whatever the answer said or left out (`protected.OUTWARD`).
        report = reminders.outward_report(handling)
        extra = f"\n\n{report}" if report else ""
        if report and self.say is not None:
            asyncio.ensure_future(self._said_quietly(chat, report))
        phoned = False
        title, details = reminders.title_of(row), reminders.details_of(row)
        if row.kind == "do":
            quiet = not answer or answer.startswith(reminders.NOTHING_NEW.rstrip("."))
            if report:
                quiet = False
            if answer and not quiet and not handling.told:
                phoned = await self.phone(f"🔁 {title}\n\n{answer[:1500]}{extra}{link}")
            elif report:
                phoned = await self.phone(f"🔁 {title}{extra}{link}")
            if quiet and answer and not (handling.started or handling.told):
                line = "nothing new, so nothing was sent"
            else:
                line = reminders.handled_line(where, handling, answer)
                if phoned:
                    line += " and sent you a notification of it"
        else:
            # Rouh decided, and a reminder still reaches the phone whatever it
            # decided: the line it always was, when the turn sent nothing there.
            if not handling.told:
                phoned = await self.phone(f"⏰ {title}" + (f"\n{details}" if details else "")
                                          + (f"\n\n{answer[:1500]}" if answer else "")
                                          + extra + link)
            elif report:
                phoned = await self.phone(f"⏰ {title}{extra}{link}")
            line = reminders.handled_line(where, handling, answer)
            if phoned:
                line += ", and it went to your notifications"
        if theirs is not None and theirs.get("to_them") and row.kind == "do":
            quiet = not answer or answer.startswith(reminders.NOTHING_NEW.rstrip("."))
            if not quiet:
                theirs["line"] = await self._to_them(row, who, theirs, answer, due_at=due_at,
                                                     trying=trying)
        if theirs is not None and theirs.get("line"):
            line += "; " + theirs["line"]
        if trying:
            line = "tried now, " + line
        await asyncio.to_thread(reminders.said, row.id, line)
        await self.tell(who)

    async def _theirs(self, row, who, *, due_at, trying: bool) -> dict | None:
        """A trusted contact's item, due: may it still run, and what goes to them.

        None when it is done with here: stopped because a grant it needs was taken away (or they
        were removed), or a message to them alone, sent. Otherwise what the rest of `deliver`
        needs: the turn to hold a "do" item's work to, whether its answer goes to them, and a
        line to add to what the row says.
        """
        from . import clockwork_grants as cw
        from . import grants
        from . import trusted as trust

        owner = await asyncio.to_thread(reminders.owner_name, row)
        contact = await asyncio.to_thread(trust.TrustStore().get, row.user_id, row.org_id,
                                          row.owner_contact_id)
        tree = await asyncio.to_thread(grants.tree, row.org_id)
        why = cw.refusal(contact, tree, cw.needs(row), now=True, owner=owner)
        if why:
            if trying:
                await asyncio.to_thread(reminders.said, row.id, f"tried now, it would not run: {why}")
            else:
                await asyncio.to_thread(reminders.stop, row, why)
                log.info("Clockwork item %s of contact %s stopped: %s", row.id,
                         row.owner_contact_id, why)
            await self.tell(who)
            return None
        out = {"to_them": cw.to_them(row), "line": "", "contact": contact,
               "turn": cw.turn_for(row, contact, tree, who) if row.kind == "do" else None}
        if row.kind == "remind" and cw.to_them(row):
            words = getattr(row, "message", "") or "\n".join(
                w for w in (reminders.title_of(row), reminders.details_of(row)) if w)
            out["line"] = await self._to_them(row, who, out, words, due_at=due_at,
                                              trying=trying)
            if not cw.to_owner(row):
                await asyncio.to_thread(reminders.said, row.id,
                                        ("tried now, " if trying else "") + out["line"])
                await self.tell(who)
                return None
        return out

    async def _to_them(self, row, who, theirs: dict, words: str, *, due_at,
                       trying: bool) -> str:
        """What a contact's item says to them, through the one outbox (D5), as a line for the row.
        Try it now shows what would go and sends nothing: only its time sends to them."""
        from . import mail_outbox as outbox
        from .decision_sources import hooks
        from .models import MailCase

        contact = theirs["contact"]
        first = (contact.name.split() or [contact.name])[0]
        case = await asyncio.to_thread(lambda: MailCase.objects.filter(
            user_id=row.user_id, org_id=row.org_id, id=getattr(row, "case_id", None) or 0)
            .first())
        if case is None:
            return f"nothing went to {first}: the message it was made from is not there any more"
        try:
            ch = outbox.item_channel(row, case, contact)
        except ValueError as exc:
            return f"nothing went to {first}: {exc}"
        where = "by email" if ch["channel"] == "email" else "on Telegram"
        if trying:
            return f"would send {first} {where}: \u201c{' '.join(words.split())[:300]}\u201d"
        desk = hooks.mail_desk() if hooks.mail_desk is not None else None
        if desk is None:
            return f"nothing went to {first}: new mail is not handled on this server"
        sent = await outbox.send_item(desk, who, case, row, contact, text=words,
                                      due_at=due_at or time.time())
        if sent.before:
            return f"it had gone to {first} {where} already"
        if sent.state == "sent":
            return f"sent to {first} {where}"
        return f"not sent to {first}: {sent.error}"


async def _server_job_line(job, who, trying: bool) -> str:
    try:
        return str(await job(who, trying) or "done")
    except Exception as exc:  # noqa: BLE001 - the row says what stopped it
        log.exception("a server job could not be started")
        return f"could not start: {type(exc).__name__}: {exc}"[:300]


def when_said(row) -> str:
    """When a row is next due, for a sentence: "Friday 2 October at 09:00"."""
    return reminders.spoken(clock.moment(row.next_at)) if row.next_at else "never again"
