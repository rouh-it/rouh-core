"""What anyone can look at, worked out from the list and never stored as the truth.

Step 07: "the list, and the documents" are true by themselves; everything else
is worked out from the list. Here that is: the runs and their states, the open
questions, the paired devices, and the work tree the orb draws.

:class:`Views` takes entries one at a time with :meth:`Views.apply`. Given the
same entries in the same order it always ends up the same, and the tests check
that applying the whole list at once and applying it in pieces across a saved
position agree. The saved position (:meth:`snapshot`, :meth:`restore`) exists
only so a restart does not have to read a year of list; delete it and the
program rebuilds everything from the list.

The work tree is built by Rouh's own ``rouh.tree.build_tree``, fed the
list's entries in the shape that function reads. One definition of the tree,
so the orb can draw the program's runs exactly as it draws Rouh's jobs.
"""
from __future__ import annotations

from typing import Any, Iterable

from rouh import tree as jtree

from . import agents, billing
from .listfile import epoch

#: Every state a run can be in, in the order it usually goes through them.
#: ``saving`` is between Claude finishing a turn and its work being on main:
#: a run is not "finished its turn" to anyone looking while that is going on.
#: ``reaped`` is a run the program shut down because nothing had happened in
#: it for longer than a run may sit still (``Settings.run_lifetime``, six
#: hours, counted from its last activity and not from its start, at Petar's
#: word on 30 October 2026): neither a success nor a crash, and every screen
#: says which it was.
STATES = ("queued", "starting", "working", "asking", "saving", "idle", "done", "unfinished",
          "failed", "lost", "refused", "reaped")
OPEN = frozenset({"queued", "starting", "working", "asking", "saving", "idle"})
ENDED = frozenset({"done", "unfinished", "failed", "lost", "refused", "reaped"})

#: The ``how`` of a stop the program made because nothing had happened in the
#: run for too long. A run stopped that way ends ``reaped``.
REAPED = "reaped"
#: The ``how`` of a run its holder ended for holding more memory than one run
#: may (``holder.Holder._watch``). It ends ``failed``, with the reason on it.
OVER_MEMORY = "over-memory"

#: **The signals that mean something stopped this run**, as against the run
#: breaking. A hangup is what a machine going down sends to whatever is in a
#: terminal it is tearing down; an interrupt is Ctrl-C; a quit and a terminate
#: are a person, systemd or this program asking it to go; a kill is the same
#: ask with no time left. Not one of them is the run's own doing.
#:
#: What is deliberately **not** here is the faults - SIGSEGV, SIGABRT, SIGBUS,
#: SIGILL, SIGFPE - which are the process coming apart inside itself. Those
#: are a failure however far along the work was, and they are the reason this
#: is a list rather than "any signal at all".
#:
#: Claude Code does not die on any of these: it answers them by closing its
#: session properly and exiting 128 plus the number, so SIGTERM leaves 143 and
#: a hangup leaves 129. `signalled` below reads both shapes.
STOPPING = frozenset({1, 2, 3, 9, 15})


def signalled(signal: int | None, code: int | None) -> int | None:
    """Which signal ended this process, however it reached us.

    Two shapes mean the same thing and both turn up. A process that dies on a
    signal is reported with `signal` set and no code. One that **answers** the
    signal and leaves tidily - which is what Claude Code does - is reported as
    having exited with 128 plus the signal's number and no signal at all. Run
    76a0d438 ended `exited` with code 129 and signal None on 22 September 2026,
    hung up by a reboot, and was read as a plain non-zero exit because only the
    first shape was being looked for.
    """
    if signal is not None:
        return signal
    return code - 128 if code is not None and 128 < code < 160 else None


def stopped(signal: int | None, code: int | None) -> bool:
    """Whether what ended this process was something stopping it, not a fault."""
    return signalled(signal, code) in STOPPING


#: The ways a run can end that nobody asked for. Every other ``how`` comes
#: from :meth:`one.runs.Runs.stop`, which only ever runs because the program
#: or a person asked the run to end.
BY_ITSELF = frozenset({"exited", "lost", "failed-to-start"})


def delivered(run: dict[str, Any]) -> bool:
    """The run finished a turn and was not in the middle of another one."""
    return int(run.get("turns") or 0) > 0 and run.get("state") in ("idle", "saving")


def work_left(body: dict[str, Any]) -> str:
    """What a run left behind that never reached its target branch, in words.

    ``dirty`` and ``unsaved`` are read off the run's own checkout as it ends
    (``one.runs.Runs.what_is_left``), and are in the ``run.ended`` entry. An
    entry written before 17 September 2026 has neither, so it says nothing and
    the run is judged the way it was judged then.

    On 17 September run 8109f4b5 wrote the whole of a fix to Rouh, ended its
    turn saying "Waiting on the rouh/ suite" without having committed any of
    it, was closed three minutes later to make room, and was called **Done**
    with exit code 0. Nothing about the way it ended said otherwise, because
    nothing about the way it ended looked at the work.
    """
    if body.get("dirty"):
        return "it left changes that were never committed"
    unsaved = int(body.get("unsaved") or 0)
    if unsaved:
        where = str(body.get("target") or "main")
        return (f"it left {unsaved} commit{'s' if unsaved != 1 else ''} "
                f"that never reached {where}")
    return ""


def ended_state(run: dict[str, Any], how: str, code: int | None, signal: int | None,
                left: str = "") -> str:
    """What to call a run that has ended: ``done``, ``unfinished``, ``failed`` or ``lost``.

    A run somebody asked to end is done, whatever number its process gave on
    the way out. The program ends a run of Claude Code by pressing Ctrl-C
    twice and, if it will not go, with SIGTERM; Claude Code answers SIGTERM by
    closing its session and exiting 143. That 143 is the stop showing through,
    not a failure. Until 16 September 2026 six runs that had delivered their
    work and saved it to main were called failed for exactly that reason, and
    the person was told they had "stopped with an error".

    A run nobody asked to end is judged by how it went: exit 0, or no exit
    code at all, is done. **So is being stopped by any of the signals that
    mean stopping** (`STOPPING`) once its last turn was delivered, which is
    the same deliberate stop arriving through another door. A fault - SIGSEGV,
    SIGABRT, a non-zero exit with no signal behind it and no work delivered -
    is a failure, and the code and the signal stay in the list either way.

    That "any of them" was "SIGTERM, and only SIGTERM" until 22 September 2026,
    and it named a number where it meant a kind. At 15:23 that day run 582125d8
    rebooted this machine on purpose, to measure the boot. Seven runs went down
    with it and not one of them had a line of uncommitted work. Five were sent
    SIGTERM, exited 143 and were called done. Two were sent SIGHUP, exited 129
    and were called **failed** - 76a0d438, whose feature was on main and
    deployed an hour earlier, and 4b715c5e, in the same position. One event,
    one state, two colours, decided by which signal happened to reach which
    process first as the machine went down.

    `delivered` is what keeps this honest, and it is doing more work than the
    signal list is. A run that was **working** when the machine stopped it has
    not delivered, so it is still a failure and the program still resumes it;
    only a run that had finished its turn and was sitting there is forgiven.

    ``left`` is what the run's checkout still held as it ended, in words
    (:func:`work_left`), and it is the last word over all of that. A run that
    would otherwise be called done, but whose work never reached its target
    branch, is **unfinished**: the exit code says the process ended tidily, and
    only the checkout says the work did not. Done here means committed and on
    main, and nothing weaker is allowed to say it.
    """
    if how == "lost":
        return "lost"
    if how == REAPED:
        # Shut down by the program's own clock, which is neither the run
        # finishing nor the run breaking. What it left behind is still on the
        # run (``left``), and every screen says it beside the word.
        return "reaped"
    if how in ("failed-to-start", OVER_MEMORY):
        return "failed"
    state = "failed"
    if how not in BY_ITSELF:
        state = "done"
    elif signal is None and code in (0, None):
        state = "done"
    elif stopped(signal, code) and delivered(run):
        state = "done"
    return "unfinished" if state == "done" and left else state

#: Tool calls and the like kept per run for the tree. The tree shows now, and a
#: finished call leaves it within seconds, so an old call is never drawn.
TREE_KEEP = 1500
#: How long an ended run stays in the tree, in seconds. As long as the orb's
#: grey trace of finished work, then gone.
TREE_AFTER_END = 30.0

#: List kinds that build the tree, and the hook each stands for.
TREE_KINDS = {
    "tool.opened": "pre_tool_use",
    "tool.closed": "post_tool_use",
    "subagent.opened": "subagent_start",
    "subagent.closed": "subagent_stop",
    "agent.stopped": "stop",
    "agent.notified": "notification",
    "agent.ended": "session_end",
}

#: Which way of working the views out a saved position was made with. Raise it
#: whenever what an entry does to the views changes: a saved position from
#: another way is thrown away, and everything is worked out again from the
#: list. Found on 14 September, when a fix to how a question clears did not
#: reach a run whose state had been saved before the fix.
#: 6: a run that ended is called done or failed by :func:`ended_state`, so the
#: runs already saved as failed on a 143 are worked out again and come back done.
#: 7: a run that ended with work never committed, or with commits that never
#: reached main, is called unfinished rather than done (:func:`work_left`).
#: 8: a delivered run stopped by any stopping signal is done, not only one
#: stopped by SIGTERM, so the runs a reboot hung up and left saved as failed
#: on a 129 are worked out again and come back done (:func:`stopped`).
#: 9: a run carries when its process was last started (``launched_at``), when
#: its last turn ended well (``succeeded_at``) and whether the program may still
#: archive it (``archive_settled``), for the garbage collection in scheduler.py.
#: 10: a run started again because its process went down with the program
#: (``with_program``, a deploy restarting the worker container) counts in
#: ``carried``, not in the ``restarts`` a crash gets.
LOGIC = 10

#: What the person's own session is called until its first prompt names it.
SESSION_TITLE = "Your own session"

#: How a run's state reads as a worker in Rouh's tree.
_WORKER_STATUS = {
    "queued": "running", "starting": "running", "working": "running", "asking": "waiting",
    "saving": "running", "idle": "done", "done": "done", "unfinished": "failed",
    "failed": "failed", "lost": "lost", "refused": "lost", "reaped": "done",
}


def _t(at: str | None) -> float | None:
    return epoch(at) if at else None


class Views:
    def __init__(self) -> None:
        #: The number of the last entry applied.
        self.n = 0
        self.runs: dict[str, dict[str, Any]] = {}
        self.questions: dict[str, dict[str, Any]] = {}
        self.devices: dict[str, dict[str, Any]] = {}
        self._tree: dict[str, list[dict[str, Any]]] = {}

    # -- applying ------------------------------------------------------------

    def apply_all(self, entries: Iterable[dict[str, Any]]) -> "Views":
        for entry in entries:
            self.apply(entry)
        return self

    def apply(self, entry: dict[str, Any]) -> None:
        n = int(entry.get("n") or 0)
        if n and n <= self.n:
            return  # already in: a saved position and the list overlap by design
        if n:
            self.n = n
        kind = str(entry.get("kind") or "")
        body = entry.get("body") or {}
        handler = getattr(self, "_on_" + kind.replace(".", "_").replace("-", "_"), None)
        if handler is not None:
            handler(entry, body)
            run = self.runs.get(entry.get("run") or "")
            if run and run.get("succeeded_at") and run["state"] not in ("idle", "done"):
                # A turn that ended well is only the run's last word while
                # nothing has happened since: working again, asking, saving
                # another turn or ending any other way, and it is not.
                run["succeeded_at"] = None
        if kind in TREE_KINDS and entry.get("run") in self.runs:
            self._keep_for_tree(entry)

    def _run(self, entry: dict[str, Any]) -> dict[str, Any] | None:
        return self.runs.get(entry.get("run") or "")

    # -- runs ------------------------------------------------------------------

    #: What a run called where it worked, and the space that is now. The first
    #: three are from before D42; "jarvis" is from before 22 September 2026,
    #: when the space was renamed with everything else (RENAME.md). Runs from
    #: then are still in the list, so their space still has to have a name.
    OLD_PROFILES = {"workspace": "assistant", "server": "assistant", "scratch": "scratch",
                    "jarvis": "rouh"}

    @classmethod
    def _space_of(cls, body: dict[str, Any]) -> str:
        """Which space a run works in, under the name that space has now.

        The name is mapped either way it arrives. A run started today names its
        space; a run from before D42 named a profile instead; and a run from
        before 22 September 2026 named `jarvis`, which is `rouh` now. Mapping
        both is what keeps a run from last week saying where it really is
        rather than naming a folder nobody has any more.
        """
        if body.get("space"):
            return cls.OLD_PROFILES.get(str(body["space"]), str(body["space"]))
        return cls.OLD_PROFILES.get(str(body.get("profile") or ""), "assistant")

    def _on_run_requested(self, e, b) -> None:
        brief = str(b.get("brief") or "")
        interactive = bool(b.get("interactive"))
        given = str(b.get("title") or "").strip()
        default = SESSION_TITLE if interactive else "A run"
        title = given or (brief.strip().splitlines() or [default])[0]
        self.runs[e["run"]] = {
            "id": e["run"], "kind": b.get("kind") or "agent", "title": title[:120],
            "interactive": interactive, "titled": bool(given or brief.strip()),
            "brief": brief, "space": self._space_of(b),
            "by": e.get("by"), "surface": b.get("surface"), "model": b.get("model"),
            # How hard it was asked to think, when whoever asked said, which
            # Rouh always does (`rules.start_options`). Kept, so a run started
            # again after a restart thinks at the level it was started at.
            "effort": b.get("effort"),
            # Which agent it is. Every run before 17 September 2026 was Claude
            # Code and said nothing about it, so nothing there reads as claude.
            "engine": agents.engine_of(b.get("engine")),
            # Who pays for it (billing.py): the subscription unless the key was
            # asked for, and only a run of Codex can be. A run from before 27
            # September 2026 says nothing and was on the subscription.
            "billing": billing.billing_of(agents.engine_of(b.get("engine")), b.get("billing")),
            # When it changed and who changed it, and whether the run is on the
            # first turn of a conversation carried over to the key.
            "billing_was": None, "billing_by": None, "billing_at": None,
            # The nightly feature run's two (`rules.start_options`): it may sign up
            # and pay through Rouh's tools, and its browser listens for Rouh on a
            # port of its own. Kept, so a run started again keeps both.
            "signups": b.get("signups") is True,
            "browser_port": int(b.get("browser_port") or 0),
            # The boxes the person handed it (`rouh/boxes.py`), by number and name, whether
            # they were put in its folder and whether they have been shredded (`sealed.py`).
            "boxes": [{"number": int(x.get("number") or 0), "name": str(x.get("name") or "")}
                      for x in (b.get("boxes") or []) if isinstance(x, dict)],
            "boxes_handed": False, "boxes_shredded": False,
            "billing_resuming": False,
            # The turns Codex ended with an error, by id, so none is taken twice.
            "failed_turns": [],
            "state": "queued", "requested_at": e["at"], "started_at": None, "ended_at": None,
            "exit_code": None, "signal": None, "how": None, "ended_why": None,
            "cwd": None, "branch": None,
            "repo": None, "target": None, "flow": None, "compare": None, "pushed": None,
            "own": None,
            "session_id": None, "transcript": None, "driver": None,
            "watchers": [], "last_message": "", "last_prompt": "", "turns": 0, "tools": 0,
            "doing": "", "question": None, "waiting_on_terminal": None, "landed": None,
            "landed_head": None,
            # What its last turn ended waiting on - sub-agents, background
            # commands, monitors, a scheduled wake-up - while that pause stands
            # (`agents.paused_on`). A paused run is working, not finished.
            "waiting_on": [], "paused_at": None,
            # Why a pause was called over with nothing having woken it, until
            # the run is prompted again (`Runs.end_stale_pause`).
            "stalled": "",
            "land_reason": None, "files": [], "restarts": 0, "carried": 0, "queued_because": None,
            # What its branch was made from, which land.sh needs to tell a run
            # that committed nothing from one whose commits are already on main.
            "base_sha": None,
            # The merge conflict its work is stuck on, when there is one
            # (land.sh, rouh/conflicts.py): the record's id, the question in
            # one line, and whether it is the person's to answer. A run waiting
            # on that is red on every screen, not amber, because only a person
            # can move it.
            "conflict": None, "conflict_question": None, "conflict_needs_person": False,
            # The files the job said up front it expects to touch, so the
            # scheduler can queue a job that would collide with one already
            # running instead of starting both.
            "expects": [str(f) for f in (b.get("expects") or []) if str(f).strip()][:40],
            "task": b.get("task"), "step": None, "last_at": e["at"],
            # Set when it ends: what its checkout still held that never reached
            # main, in words, and whether anything of its work ever got there.
            "left": "", "saved": False,
            # Put out of the list's way, by a person or by the program once the
            # run succeeded (scheduler.py, ``Scheduler.archive_succeeded``).
            "archived": False,
            # Whether archiving has been decided about since the run last
            # started: set by any archive or unarchive, so the program never
            # puts away again a run a person brought back.
            "archive_settled": False,
            # When its Claude Code was last started, first launch or a carry
            # on. The six-hour limit counted from this until 30 October 2026;
            # it counts from ``last_at`` now (``Scheduler.close_overdue``).
            "launched_at": None,
            # When its last turn ended well: on main and live, or with nothing
            # to save and nothing left behind. None while anything has
            # happened since (``apply``).
            "succeeded_at": None,
            # How it was asked to end, while that still stands: from the stop
            # being asked for until it is started again. Kept on the list, so
            # a stop the program's own restart cut short is finished by the
            # program that comes back (Runs.adopt_all).
            "close_wanted": None,
        }

    def _on_run_queued(self, e, b) -> None:
        run = self._run(e)
        if run:
            run["queued_because"] = b.get("why")
            run["state"] = "queued"

    def _on_run_archived(self, e, b) -> None:
        """A person, or the program once the run succeeded, put the run out of the
        list's way, or brought it back.

        A flag and nothing else. The run is not stopped, its terminal is not
        closed and its checkout is not touched; ``last_at`` does not move,
        because nothing happened to the run itself.
        """
        run = self._run(e)
        if run:
            run["archived"] = bool(b.get("on", True))
            run["archive_settled"] = True

    def _on_run_retitled(self, e, b) -> None:
        """The person gave the run another title, and with it, when given, another brief:
        every list and every report says the new one from here on (`one retitle`)."""
        run = self._run(e)
        if run is None:
            return
        if str(b.get("title") or "").strip():
            run["title"], run["titled"] = str(b["title"]).strip()[:120], True
        if "brief" in b:
            run["brief"] = str(b.get("brief") or "")

    def _on_run_forget_requested(self, e, b) -> None:
        """The person asked for the run to be forgotten once it has ended and `after` more
        seconds have gone, so its report is still delivered first (`Scheduler.forget_due`)."""
        run = self._run(e)
        if run is not None:
            run["forget_after"] = float(b.get("after") or 0)

    def _on_run_forgotten(self, e, b) -> None:
        """The person asked for an ended run to be forgotten: it is in no view at
        all from here on, nor its questions, nor its part of the work tree. The
        list keeps only this entry about it (``ListFile.scrub``)."""
        run_id = e.get("run") or ""
        self.runs.pop(run_id, None)
        self._tree.pop(run_id, None)
        for qid in [q for q, v in self.questions.items() if v.get("run") == run_id]:
            self.questions.pop(qid, None)

    def _on_run_stop_requested(self, e, b) -> None:
        """Somebody asked the run to end, and it is to stay ended.

        Only an entry that says it is ``durable`` sets it, which is every one
        written since 3 October 2026. The ones written before were acted on by
        the program that wrote them, and a restart does not go back over them.
        It is not cleared by the run ending: an ended run whose terminal is
        somehow still there is still a run somebody asked to end.
        """
        run = self._run(e)
        if run and b.get("durable"):
            run["close_wanted"] = b.get("how") or "stopped"

    def _on_run_refused(self, e, b) -> None:
        run = self._run(e)
        if run:
            run.update(state="refused", how=b.get("why") or "refused", ended_at=e["at"])

    def _on_run_boxes(self, e, b) -> None:
        run = self._run(e)
        if run:
            run["boxes_handed"] = True

    def _on_run_boxes_shredded(self, e, b) -> None:
        run = self._run(e)
        if run:
            run["boxes_shredded"] = True

    def _on_run_started(self, e, b) -> None:
        run = self._run(e)
        if not run:
            return
        run.update(state="starting", started_at=run["started_at"] or e["at"], launched_at=e["at"],
                   cwd=b.get("cwd"), branch=b.get("branch"), repo=b.get("repo"),
                   target=b.get("target"), flow=b.get("flow"), own=b.get("own"),
                   base_sha=b.get("base_sha") or run.get("base_sha"),
                   session_id=b.get("session_id") or run.get("session_id"),
                   queued_because=None, last_at=e["at"])

    def _on_run_restarted(self, e, b) -> None:
        run = self._run(e)
        if run:
            # Started again because a person moved it onto the API key is not
            # a crash, and does not use up one of the restarts a crash gets.
            # Nor is going down with the program: a deploy restarts the worker
            # container in the containers, and every run in it with it
            # (``Runs.adopt_all``). Those are counted on their own, as
            # ``carried``, so a morning of deploys cannot use up a run's
            # restarts and leave it lost, as it left four on 3 November 2026.
            if b.get("with_program"):
                run["carried"] = int(run.get("carried") or 0) + 1
            elif not b.get("billing"):
                run["restarts"] = int(run.get("restarts") or 0) + 1
            # Going again, its checkout is live again, whatever was decided about it.
            run.update(state="starting", ended_at=None, exit_code=None, signal=None, how=None,
                       ended_why=None,
                       checkout=None, checkout_why=None, left="", last_at=e["at"],
                       # Whatever its last process was waiting on went with it.
                       waiting_on=[], paused_at=None, stalled="",
                       # A new process, so a new six hours, and whatever it
                       # does now is the program's to archive again.
                       launched_at=e["at"], archive_settled=False,
                       # Somebody wants it going again, so an earlier stop no longer stands.
                       close_wanted=None)

    def _on_agent_session(self, e, b) -> None:
        run = self._run(e)
        if run:
            run["session_id"] = b.get("session_id") or run.get("session_id")
            run["transcript"] = b.get("transcript") or run.get("transcript")
            if run["state"] == "starting":
                # Up and running. The person's own session now waits for them.
                run["state"] = "idle" if run.get("interactive") else "working"

    def _on_agent_prompted(self, e, b) -> None:
        run = self._run(e)
        if run and run["state"] not in ENDED:
            run["last_prompt"] = str(b.get("text") or "")[:500]
            if run.get("interactive") and not run.get("titled"):
                # The person's own session is named by the first thing asked of it.
                first = next((line.strip() for line in str(b.get("text") or "").splitlines()
                              if line.strip()), "")
                if first:
                    run["title"], run["titled"] = first[:120], True
            if run["state"] != "asking":
                run["state"] = "working"
            run["waiting_on_terminal"] = None
            # Woken: what it waited on reported, or somebody said something.
            run["waiting_on"], run["paused_at"], run["stalled"] = [], None, ""
            run["last_at"] = e["at"]

    def _moved_on(self, run: dict[str, Any]) -> None:
        """The run did something, so a question on its own screen was answered.

        A question the program asked stays until it is answered through the
        program; one Claude Code showed on its own screen is over as soon as
        the run carries on, however it was answered there.
        """
        if run.get("waiting_on_terminal"):
            run["waiting_on_terminal"] = None
            if run["state"] == "asking" and not run.get("question"):
                run["state"] = "working"

    def _on_tool_opened(self, e, b) -> None:
        run = self._run(e)
        if not run or run["state"] in ENDED:
            return
        self._moved_on(run)
        run["tools"] = int(run.get("tools") or 0) + 1
        if b.get("what"):
            run["doing"] = str(b["what"])
        if b.get("step"):
            run["step"] = b["step"]
        if run["state"] in ("starting", "idle"):
            run["state"] = "working"
        run["last_at"] = e["at"]

    def _on_tool_closed(self, e, b) -> None:
        run = self._run(e)
        if run and run["state"] not in ENDED:
            self._moved_on(run)
            # A call finishing is the run moving, so a long command's end
            # counts as much as its start (``Scheduler.close_overdue``).
            run["last_at"] = e["at"]

    def _on_hook_missed(self, e, b) -> None:
        """A tool call the program was not asked about in time. Counted, so it shows."""
        run = self._run(e)
        if run:
            run["missed"] = int(run.get("missed") or 0) + 1
            if not b.get("caught"):
                run["unchecked"] = int(run.get("unchecked") or 0) + 1

    def _on_agent_stopped(self, e, b) -> None:
        run = self._run(e)
        if not run or run["state"] in ENDED:
            return
        self._moved_on(run)
        # A turn ended well, so a conversation carried over to the key was taken.
        run["billing_resuming"] = False
        run["turns"] = int(run.get("turns") or 0) + 1
        if b.get("message"):
            run["last_message"] = str(b["message"])
        if b.get("paused"):
            # The turn ended and the work did not: what it started will wake
            # it again. It is working, it says what on, and nothing is saved
            # or reported until a turn ends with nothing left in flight.
            run["waiting_on"] = [str(n) for n in (b.get("background") or [])][:10]
            run["paused_at"] = e["at"]
            if run["state"] not in ("asking",):
                run["state"] = "working"
            run["doing"] = "Waiting for " + ", ".join(run["waiting_on"])[:200]
            run["last_at"] = e["at"]
            return
        run["waiting_on"], run["paused_at"] = [], None
        if not run.get("question"):
            run["state"] = "saving" if b.get("saving") else "idle"
            if run["state"] == "idle" and not b.get("sent_back") and not b.get("background"):
                # A run with nothing to save: the turn ending is its result.
                run["succeeded_at"] = e["at"]
        run["doing"] = ""
        run["last_at"] = e["at"]

    def _on_agent_pause_ended(self, e, b) -> None:
        """A pause nothing woke for too long is called the end of its turn after all."""
        run = self._run(e)
        if not run or run["state"] in ENDED:
            return
        run["waiting_on"], run["paused_at"] = [], None
        run["stalled"] = str(b.get("why") or "nothing woke it")
        if not run.get("question"):
            run["state"] = "saving" if b.get("saving") else "idle"
        run["doing"] = ""
        run["last_at"] = e["at"]

    def _saved(self, e, *, carry_on: bool = False) -> None:
        run = self._run(e)
        if run and run["state"] == "saving":
            run["state"] = "working" if carry_on else "idle"
            run["last_at"] = e["at"]

    def _on_work_nothing_new(self, e, b) -> None:
        self._saved(e)
        run = self._run(e)
        if run and run["state"] == "idle" and not b.get("sent_back") and not work_left(b):
            run["succeeded_at"] = e["at"]

    def _on_agent_notified(self, e, b) -> None:
        run = self._run(e)
        if not run or run["state"] in ENDED:
            return
        # Claude Code itself is showing a question on its screen that only a
        # terminal can answer. The program's own questions come through the
        # PreToolUse hook and never get here.
        if b.get("type") in ("permission_prompt", "elicitation_dialog", "agent_needs_input"):
            run["waiting_on_terminal"] = str(b.get("message") or "It is waiting for you")
            run["state"] = "asking"

    def _on_run_billing(self, e, b) -> None:
        """Who pays for the run changed, because a person said yes to it."""
        run = self._run(e)
        if run:
            run.update(billing=billing.billing_of(run.get("engine"), b.get("billing")),
                       billing_was=b.get("was"), billing_by=e.get("by"), billing_at=e["at"],
                       billing_resuming=bool(b.get("resume")), last_at=e["at"])
            if b.get("stop"):
                # What the subscription did, kept for a fresh session's brief.
                run["billing_stop"] = b["stop"]

    def _on_codex_turn_failed(self, e, b) -> None:
        """Codex ended a turn with an error, and sent no hook to say so.

        The run is at its prompt again, whatever its last hook made it look
        like, and what stopped it is its last word until it says another.
        """
        run = self._run(e)
        if not run or run["state"] in ENDED:
            return
        turns = list(run.get("failed_turns") or [])
        if b.get("turn") and b["turn"] not in turns:
            turns = (turns + [b["turn"]])[-50:]
        run["failed_turns"] = turns
        run["billing_resuming"] = False
        run["last_message"] = "Codex stopped: " + str(b.get("message") or b.get("info") or "")
        run["doing"] = ""
        if run["state"] in ("working", "starting", "saving") and not run.get("question"):
            run["state"] = "idle"
        run["succeeded_at"] = None
        run["last_at"] = e["at"]

    def _on_message_sent(self, e, b) -> None:
        run = self._run(e)
        if run and run["state"] in ("idle", "starting", "saving"):
            run["state"] = "working"
            run["waiting_on_terminal"] = None

    def _on_message_failed(self, e, b) -> None:
        """A message never reached the run. One found left in its box after a
        restart had been written down as sent, and the run has been shown as
        working on it ever since: it is at its prompt (fr_8ced13df88e4)."""
        run = self._run(e)
        if run and b.get("left") and run["state"] == "working" and not run.get("question"):
            run["state"] = "idle"
            run["doing"] = ""
            run["last_at"] = e["at"]

    def _on_run_attached(self, e, b) -> None:
        run = self._run(e)
        if run and e.get("by") and e["by"] not in run["watchers"]:
            run["watchers"].append(e["by"])

    def _on_run_detached(self, e, b) -> None:
        run = self._run(e)
        if run and e.get("by") in run["watchers"]:
            run["watchers"].remove(e["by"])
        if run and run.get("driver") == e.get("by"):
            run["driver"] = None

    def _on_run_taken_over(self, e, b) -> None:
        run = self._run(e)
        if run:
            run["driver"] = b.get("device") or e.get("by")

    def _on_run_handed_back(self, e, b) -> None:
        run = self._run(e)
        if run:
            run["driver"] = None

    def _on_run_ended(self, e, b) -> None:
        run = self._run(e)
        if not run:
            return
        how = b.get("how") or "exited"
        code, signal = b.get("code"), b.get("signal")
        left = work_left({**b, "target": b.get("target") or run.get("target")})
        state = ended_state(run, how, code, signal, left)
        run.update(state=state, how=how, exit_code=code, signal=signal,
                   ended_at=e["at"], driver=None, watchers=[], question=None,
                   waiting_on_terminal=None, doing="", last_at=e["at"],
                   waiting_on=[], paused_at=None,
                   # What it left behind, so every screen can say why it is
                   # unfinished without working it out again.
                   left=left, saved=bool(b.get("saved")),
                   # Why it ended, when something ended it that the person
                   # would not guess from the state alone (OVER_MEMORY).
                   ended_why=b.get("why"))

    def _on_run_settled(self, e, b) -> None:
        """An ended run found to have nothing left after all (``Runs._settle``)."""
        run = self._run(e)
        if run:
            run.update(state="done" if run.get("state") == "unfinished" else run.get("state"),
                       left="", saved=True, checkout=None, checkout_why=None)

    def _on_run_checkout(self, e, b) -> None:
        """A run carried on after its checkout was removed, in a fresh one."""
        run = self._run(e)
        if run:
            run.update(cwd=b.get("cwd"), branch=b.get("branch"), repo=b.get("repo"),
                       target=b.get("target") or run.get("target"),
                       flow=b.get("flow") or run.get("flow"), own=b.get("own") or run.get("own"),
                       checkout=None, checkout_why=None)

    def _on_checkout_removed(self, e, b) -> None:
        run = self._run(e)
        if run:
            run.update(checkout="removed", checkout_why=None)

    def _on_checkout_kept(self, e, b) -> None:
        run = self._run(e)
        if run:
            run.update(checkout="kept", checkout_why=b.get("why"))

    def _on_work_landed(self, e, b) -> None:
        run = self._run(e)
        if run:
            run.update(landed=b.get("sha"), land_reason=None,
                       # The run's own commit the landing took (`asuser._with_head`):
                       # what is left is what it committed after this.
                       landed_head=b.get("landed_head") or run.get("landed_head"),
                       files=list(b.get("files") or [])[:200],
                       # Its work is on main, so whatever it was stuck on is over.
                       conflict=None, conflict_question=None,
                       conflict_needs_person=False)
            if b.get("branch"):
                # Pushed on its own branch, for a pull request (D42).
                run.update(pushed=b["branch"], compare=b.get("compare"))
        self._saved(e)
        # On main is a success only once it is live too, where landing
        # deploys: on main and not served is not done (AGENTS.md). "none" is
        # land.sh saying there is nothing here to deploy - another repository,
        # a branch this machine does not serve - which is not a deploy that
        # failed, and is the whole of what landing can do for that work.
        failed_to_go_live = ("deploy_reason" in b and not b.get("deployed")
                             and b.get("deploy") != "none")
        if run and run["state"] == "idle" and not failed_to_go_live:
            run["succeeded_at"] = e["at"]

    def _on_work_not_landed(self, e, b) -> None:
        run = self._run(e)
        if run:
            run["land_reason"] = b.get("reason")
            if b.get("files"):
                run["files"] = list(b["files"])[:200]
            # The conflict land.sh wrote down, when it wrote one. A run handed
            # its own conflict back carries it too, because the record is what
            # the work is recoverable from either way; only ``needs_person``
            # says whose move it is.
            run["conflict"] = b.get("conflict")
            run["conflict_question"] = b.get("question")
            run["conflict_needs_person"] = bool(b.get("needs_person"))
        # Sent back to fix a clash, it carries on working in the same turn.
        self._saved(e, carry_on=bool(b.get("sent_back")))

    def _on_program_started(self, e, b) -> None:
        # Every connection died with the program that had them, so nobody is
        # watching or driving anything until they come back.
        for run in self.runs.values():
            run["watchers"] = []
            run["driver"] = None

    # -- questions -------------------------------------------------------------

    def _on_question_asked(self, e, b) -> None:
        qid = b.get("id")
        if not qid:
            return
        self.questions[qid] = {
            "id": qid, "run": e.get("run"), "text": b.get("text") or "",
            "tool": b.get("tool"), "what": b.get("what"), "detail": b.get("detail"),
            "why": b.get("why"), "asked_at": e["at"], "expires_at": b.get("expires_at"),
            "open": True, "answer": None, "answered_by": None, "phoned": False,
            # A posed question (questions.pose): what kind of choice it is,
            # what its two buttons say, and that it lasts until answered.
            "kind": b.get("kind"), "choices": b.get("choices"),
            "lasting": bool(b.get("lasting")),
        }
        run = self._run(e)
        if run and run["state"] not in ENDED:
            run["question"] = qid
            run["state"] = "asking"

    def _close_question(self, e, b, answer: str | None) -> None:
        q = self.questions.get(b.get("id") or "")
        if not q or not q["open"]:
            return
        q.update(open=False, answer=answer, answered_by=e.get("by"), closed_at=e["at"])
        run = self.runs.get(q.get("run") or "")
        if run and run.get("question") == q["id"]:
            run["question"] = None
            if run["state"] == "asking":
                # A posed choice paused a run that was at its prompt: a yes
                # starts it again, anything else leaves it where it was.
                if q.get("kind"):
                    run["state"] = "starting" if answer == "yes" else "idle"
                else:
                    run["state"] = "working"

    def _on_question_answered(self, e, b) -> None:
        self._close_question(e, b, b.get("answer"))

    def _on_question_expired(self, e, b) -> None:
        self._close_question(e, b, "expired")

    def _on_question_withdrawn(self, e, b) -> None:
        self._close_question(e, b, "withdrawn")

    def _on_phone_sent(self, e, b) -> None:
        q = self.questions.get(b.get("question") or "")
        if q:
            q["phoned"] = True

    def open_questions(self) -> list[dict[str, Any]]:
        return sorted((q for q in self.questions.values() if q["open"]),
                      key=lambda q: q["asked_at"])

    # -- devices ---------------------------------------------------------------

    def _on_device_paired(self, e, b) -> None:
        self.devices[b["device"]] = {
            "id": b["device"], "name": b.get("name") or b["device"],
            "surface": b.get("surface"), "token_hash": b.get("token_hash"),
            "paired_at": e["at"], "paired_by": e.get("by"), "revoked_at": None,
        }

    def _on_device_revoked(self, e, b) -> None:
        dev = self.devices.get(b.get("device") or "")
        if dev:
            dev["revoked_at"] = e["at"]

    def device_for_token_hash(self, token_hash: str) -> dict[str, Any] | None:
        for dev in self.devices.values():
            if dev["token_hash"] == token_hash and not dev["revoked_at"]:
                return dev
        return None

    # -- lists to show ---------------------------------------------------------

    def run_list(self, *, limit: int = 200, open_only: bool = False) -> list[dict[str, Any]]:
        """Every run, the one that started most recently first.

        Ordered by when a run was asked for and by nothing else, so a list
        someone is reading never rearranges itself because a run spoke, changed
        state or ended. The id breaks a tie between two runs asked for in the
        same millisecond, so that pair keeps one order for ever too.
        """
        runs = [r for r in self.runs.values() if not open_only or r["state"] in OPEN]
        runs.sort(key=lambda r: (r["requested_at"], r["id"]), reverse=True)
        return [dict(r) for r in runs[:limit]]

    def open_runs(self) -> list[dict[str, Any]]:
        return [r for r in self.runs.values() if r["state"] in OPEN]

    # -- the tree ----------------------------------------------------------------

    def _keep_for_tree(self, entry: dict[str, Any]) -> None:
        events = self._tree.setdefault(entry["run"], [])
        events.append(_as_hook(entry))
        if len(events) > TREE_KEEP:
            del events[: len(events) - TREE_KEEP]

    def tree(self, now: float) -> dict[str, Any]:
        """The work tree, now: every run that is open or ended moments ago."""
        events: list[dict[str, Any]] = []
        for rid, run in self.runs.items():
            ended = _t(run.get("ended_at"))
            if run["state"] in ENDED and (ended is None or now - ended > TREE_AFTER_END):
                self._tree.pop(rid, None)
                continue
            if run["state"] == "refused":
                continue
            opened = _t(run.get("started_at") or run.get("requested_at")) or now
            events.append({"crew_id": rid, "kind": "worker", "at": opened, "payload": {
                "title": run["title"], "mode": "one",
                "status": _WORKER_STATUS.get(run["state"], "running"),
                "closed_at": ended,
            }})
            events.extend(self._tree.get(rid, ()))
        built = jtree.build_tree(events, now=now)
        for node in built.get("children", []):
            run = self.runs.get(node.get("id"))
            if not run:
                continue
            node["owner"] = "one"
            node["space"] = run.get("space")
            if run["state"] == "queued":
                node["queued"] = True
            if run.get("driver"):
                node["driver"] = run["driver"]
            if run.get("step") and not node.get("step"):
                node["step"] = run["step"]
        return built

    # -- the saved position ------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        live = {rid: list(ev) for rid, ev in self._tree.items()
                if self.runs.get(rid, {}).get("state") in OPEN}
        return {"format": 1, "logic": LOGIC, "n": self.n, "runs": self.runs,
                "questions": self.questions, "devices": self.devices, "tree": live}

    @classmethod
    def restore(cls, data: dict[str, Any]) -> "Views":
        """Views from a saved position, or empty ones to be worked out from the whole list."""
        views = cls()
        if data.get("format") != 1 or data.get("logic") != LOGIC:
            return views
        views.n = int(data.get("n") or 0)
        views.runs = data.get("runs") or {}
        views.questions = data.get("questions") or {}
        views.devices = data.get("devices") or {}
        views._tree = data.get("tree") or {}
        return views


def _as_hook(entry: dict[str, Any]) -> dict[str, Any]:
    """One list entry in the shape ``rouh.tree.build_tree`` reads: the hook's own."""
    b = entry.get("body") or {}
    kind = TREE_KINDS[entry["kind"]]
    payload: dict[str, Any] = {}
    if b.get("call"):
        payload["tool_use_id"] = b["call"]
    if b.get("tool"):
        payload["tool_name"] = b["tool"]
    if b.get("agent"):
        payload["agent_id"] = b["agent"]
    if b.get("agent_type"):
        payload["agent_type"] = b["agent_type"]
    if b.get("effort"):
        payload["effort"] = {"level": b["effort"]}
    if isinstance(b.get("input"), dict):
        payload["tool_input"] = b["input"]
    if kind == "post_tool_use":
        if b.get("ms") is not None:
            payload["duration_ms"] = b["ms"]
        response: dict[str, Any] = {}
        if b.get("ok") is False:
            response["is_error"] = True
        if b.get("status"):
            response["status"] = b["status"]
        if b.get("spawned"):
            response["agentId"] = b["spawned"]
        payload["tool_response"] = response
    return {"crew_id": entry["run"], "kind": kind, "at": epoch(entry["at"]), "payload": payload}
