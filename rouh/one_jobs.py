"""Rouh's jobs in the one program, and what happens when one finishes (stage 5).

Rouh's jobs used to be its own crew's tmux windows. Since stage 5 they are
runs of the one program, and since D42 the assistant and Rouh are one: the
person's jobs and Rouh's jobs on the server are runs of the assistant, and a
change to Rouh's own code is a run in the space "rouh". The program holds
the terminal, saves the work after every turn and sends a clash back to be
fixed, all by itself. What is left for Rouh is what it always did at the
end: put the result in front of the person, a page, the files changed, an
answer, or "Needs you", and say it once nobody is talking.

So this is the crew's ``Lander`` without the landing. It listens to the
program's list, and when a run Rouh started has had its turn's work saved,
or found nothing new to save, or could not be saved, it shows that the way
``Lander`` shows a crew job's. Runs anyone else started are theirs to watch.

**A change to Rouh's own code that reached main is deployed with nobody
asked, and this reports what became of it.** It used to be deployed by asking
the model to say so and then call ``deploy_myself``, which is a step that can
be skipped, forgotten or talked out of - and a change that is on main and not
deployed is not done. The person's standing policy, said again on 19 September
2026, is that work which passes its tests is committed, merged to main and
deployed, with no approval anywhere in it.

Since 21 September 2026 the deploy is ``land.sh``'s own last step, so by the
time a landing is reported the commit is either being served or it is not, and
the entry says which. ``_deployed`` takes that answer when it is there, because
it was checked against the two health pages rather than against a script's exit
code, and deploys itself only for a landing that did not: an older ``land.sh``,
a machine where the deploy is off, or a run whose answer never came back
because the deploy restarted the program mid-sentence. ``_show_change`` then
puts what was pushed and whether it is live on the card and in what Rouh
says, and a change that is on main and not live is never said as done.

The deploy is the one thing here that happens whoever started the run. Every
other report is only for runs Rouh started, because a run started from a
terminal or a browser has a person watching its own screen and does not want
Rouh narrating it. Going live is not narration: a change that is on main is
on main whoever put it there.

It is also both services, whatever the change touched. Two of them come out of
this one repository, and ``deploy_onto_a_landed_change`` in `rouh/runtime.py`
runs the one script that moves them together (``update-all.sh``). It used to
deploy the one program only when a file under ``one/`` had changed, which is
how Rouh came to be serving 7596716 with that program four commits behind it.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Awaitable, Callable

from . import browser_handoff, conflicts, modeldefaults, outbox, rules, run_report, runs, task_origin
from .assistant_job import (FILES_SHOWN, Lander, WorkspaceCopy, answer_from, fingerprint,
                            pick_page, saved_files, summary_from)
from .memory import answering_in

log = logging.getLogger("rouh.one_jobs")

#: What is said when a change reached main and there was no way to deploy it.
#: Never silence: a change on main that nothing restarted onto is the failure
#: this whole path exists to stop, so it is said out loud like any other.
NOT_DEPLOYED = "nothing here could deploy it, so it is on main and not live yet"

#: The entries that end a turn: one of the three savings, for a run in a
#: repository, or the turn's end itself, for a run with nothing to save.
#:
#: ``run.ended`` is not a turn ending, it is the run itself ending, and it is
#: here for one case only: a run that ended with work that never reached main.
#: Until 17 September 2026 Rouh was never told a run had ended at all, so run
#: 8109f4b5 could be closed to make room with the whole of a fix to Rouh
#: uncommitted in its checkout, and nothing anywhere said so.
#:
#: ``agent.pause-ended`` is a paused turn the program called over because
#: nothing woke it (`one/runs.py`, ``Runs.end_stale_pause``): reported itself
#: for a run with nothing to save, and through its saving for any other.
DONE_KINDS = ("work.landed", "work.nothing-new", "work.not-landed", "agent.stopped",
              "agent.pause-ended", "run.ended")


def _left_behind(body: dict) -> str:
    """What a run's ``run.ended`` says it left behind unsaved, in words, or "".

    The same sentence the program puts on the run (``work_left`` in
    one/views.py), worked out here rather than imported, because Rouh reads
    the program over a socket and holds none of its code.
    """
    if body.get("dirty"):
        return "it left changes that were never committed"
    unsaved = int(body.get("unsaved") or 0)
    if unsaved:
        where = str(body.get("target") or "main")
        return f"it left {unsaved} commit{'s' if unsaved != 1 else ''} that never reached {where}"
    return ""


def _saving(entry: dict) -> bool:
    """A turn's end whose saving comes next, and says how the turn ended."""
    return (entry.get("kind") in ("agent.stopped", "agent.pause-ended")
            and bool((entry.get("body") or {}).get("saving")))


def _paused(entry: dict) -> bool:
    """A turn's end that is not the end of the work: what it started will wake it.

    The program writes it (`one/runs.py`, ``Runs._turn_ended``) when Claude
    Code's Stop hook names a sub-agent, a background command, a monitor or a
    scheduled wake-up still in flight. Nothing is saved and nothing is to be
    reported until a later turn ends with nothing left in flight.
    """
    return entry.get("kind") == "agent.stopped" and bool((entry.get("body") or {}).get("paused"))


def turn_over(entry: dict) -> bool:
    """Whether this entry is a run's turn really over, and so a thing to report.

    The one test for every listener - the cards and what is said
    (`OneLander`), the heartbeat and the event log (`runtime`) - so they can
    never disagree about whether a run finished. Not a turn whose saving comes
    next, not a turn the program handed straight back, not a pause.
    """
    body = entry.get("body") or {}
    return (entry.get("kind") in DONE_KINDS and bool(entry.get("run")) and not _saving(entry)
            and not _paused(entry) and not body.get("sent_back"))


#: The run states a run is in when its turn has carried on, read back from the
#: program before a turn's end is reported, because the entry is a moment and
#: the run is now.
CARRIED_ON = frozenset({"starting", "working", "asking"})


def _items(files: list[str]) -> list[str]:
    items = list(files[:FILES_SHOWN])
    if len(files) > FILES_SHOWN:
        items.append(f"and {len(files) - FILES_SHOWN} more")
    return items


def forget_run(run_id: str) -> dict:
    """Rouh's side of a run the one program has forgotten (`run.forgotten`): its row on the
    Runs list, the report cards it owns, and every Synapse item made of those cards, each
    deleted the way Synapse deletes (`synapse.ingest.delete`, D60), which takes the words
    out of what was made from them and keeps the key from ever being stored again.

    Without this a forgotten run lived on in Rouh: its report card was in memory, where
    automatic recall found it again, and its title was on the Runs list that every turn
    asking what ran reads. Never raises; says what went.
    """
    out = {"run": run_id, "cards": [], "items": 0}
    try:
        from .conversations import store
        from .synapse import db as sdb, ingest

        st = store()
        if st is None or not st.get_run(run_id):
            return out
        owned = st._owned_tree("run", run_id, None)
        out["cards"] = [oid for kind, oid in owned if kind == "artifact"]
        keys = [f"card:{c}" for c in out["cards"]]
        if keys:
            for row in sdb.rows("SELECT i.id AS forget_item, d.* FROM synapse.item i JOIN synapse.dataset d "
                                "ON d.id = i.dataset_id WHERE i.source_key = ANY(%s) AND i.deleted_at IS NULL",
                                (keys,)):
                ds = {k: v for k, v in row.items() if k != "forget_item"}
                if ingest.delete(ds, str(row["forget_item"]), by="forget").get("ok"):
                    out["items"] += 1
        st.delete("run", run_id)
        log.info("run %s forgotten: its record, %d card(s) and %d memory item(s) deleted",
                 run_id, len(out["cards"]), out["items"])
    except Exception:  # noqa: BLE001 - forgetting one run never stops the rest
        log.exception("could not forget run %s on Rouh's side", run_id)
    return out


class OneLander(Lander):
    def __init__(self, one, memory, broadcast, announce, review_url: str, *,
                 copy: WorkspaceCopy | None = None,
                 deploy: Callable[[str, list[str]], Awaitable[str]] | None = None) -> None:
        super().__init__(None, memory, broadcast, announce, review_url, copy=copy)
        self.one = one
        #: What deploys a change to Rouh's own code once it is on main, given
        #: the commit and the files. It says in one phrase what it deployed, and
        #: that phrase is the record. None where nothing can deploy, which is
        #: every test that is not about deploying.
        self.deploy = deploy
        #: What was last reported for each run, so the same result is said once.
        self._reported: dict[str, str] = {}
        #: Runs whose work has already been handed to a fresh run to write
        #: again. Once each: a second redo that collided the same way is a sign
        #: the two changes are answers to the same question, which is exactly
        #: what the person is there to decide.
        self._redone: set[str] = set()

    async def _deployed(self, sha: str, files: list[str],
                        body: dict | None = None) -> tuple[bool, str]:
        """What became of the change now it is on main: whether it is live, and why.

        Since 21 September 2026 ``land.sh`` deploys what it lands and does not
        report success until both services answer their health pages with the
        commit it pushed, so the answer is usually already in the entry - and it
        is the better answer, because it was checked against the running build
        rather than taken from a script's exit code. A second deploy over the
        top of it would be a restart for nothing.

        What is left for this is the landing that did not deploy: an older
        ``land.sh``, a machine where the deploy is off, or a run whose answer
        never reached the program because the deploy restarted it mid-sentence.

        Never raises and never waits on a person: a deploy that cannot happen
        is a sentence to put on the card, not a reason to lose the report of a
        change that is already on main.
        """
        said = str((body or {}).get("deploy_reason") or "")
        if said:
            return bool((body or {}).get("deployed")), said
        if self.deploy is None:
            return False, NOT_DEPLOYED
        try:
            return True, await self.deploy(sha, list(files))
        except Exception as exc:
            log.exception("deploying onto %s failed", sha[:7] or "the change")
            return False, f"the deploy would not start: {type(exc).__name__}: {exc}"

    def on_entry(self, entry: dict) -> None:
        """A listener on the program's list. It returns at once."""
        if entry.get("kind") == "run.forgotten" and entry.get("run"):
            # The person asked the program to forget the run for good (`one forget`):
            # Rouh's own record of it goes too, and what memory made of it (`forget_run`).
            task = asyncio.create_task(asyncio.to_thread(forget_run, str(entry["run"])))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
            return
        if not turn_over(entry):
            return
        task = asyncio.create_task(self.report(entry))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def report(self, entry: dict) -> dict | None:
        run_id, kind = str(entry.get("run")), entry.get("kind")
        body = entry.get("body") or {}
        if body.get("sent_back"):
            # The program handed the turn straight back - to fix a clash, to
            # commit what it left, or to wait for a command it started - so the
            # turn is not over and its next one is what there is to report.
            return None
        if kind == "run.ended" and not _left_behind(body):
            return None  # the run ended with its work saved; its turn was reported when it landed
        if _saving(entry) or _paused(entry):
            return None
        lock = self._locks.setdefault(run_id, asyncio.Lock())
        async with lock:
            # And everything this report writes down - the card, and the note
            # handed to Rouh to say - belongs to the conversation the run was
            # started from, not to whichever one the person has open now
            # (`runs.chat_of`, `Lander._card`, `Lander._say`). Petar, 22
            # September 2026: "It should report a run in the chat it was
            # started from."
            #
            # A run no conversation started reports in General, never in the
            # chat on the screen (`runs.reports_to`), and its report draws and
            # says nothing there: it stays on the run (`runs.report_stays`, in
            # `Lander._card` and `Lander._say`). A run asked for in General
            # reports in General like any other chat (Petar, 12 October 2026).
            # The deploy above it happens either way.
            # And which run it is about, so whatever the run queued for the
            # person to be emailed goes inside what Rouh is told (`Lander._say`,
            # `rouh/outbox.py`).
            with answering_in(runs.reports_to(run_id)), outbox.reporting(run_id):
                return await self._report(run_id, kind, body)

    async def _report(self, run_id: str, kind, body: dict) -> dict | None:
        """The report itself, inside the lock and inside its own thread."""
        try:
            run = (await self.one.ask("run", run=run_id, entries=0)).get("run") or {}
        except Exception as exc:
            log.warning("could not read run %s to report it: %s", run_id, exc)
            return None
        if kind in ("agent.stopped", "work.nothing-new") and (
                run.get("waiting_on") or run.get("state") in CARRIED_ON):
            # Read back, the run is not where this entry left it: it is paused
            # on what it started, or it has carried on already - a helper
            # reported, a message was handed to it - and that later turn is
            # what there will be to report. A landing is reported whatever,
            # because a change on main is news; a turn that only ended is not
            # news once the run is working again.
            log.info("not reporting run %s's %s: it is %s", run_id, kind,
                     "paused" if run.get("waiting_on") else run.get("state"))
            return {"kind": "carried_on"}
        space = run.get("space") or "assistant"
        result: dict = {"id": run_id, "sha": body.get("sha"), "reason": body.get("reason"),
                        "files": [f for f in body.get("files") or [] if f],
                        "branch": body.get("branch"), "compare": body.get("compare"),
                        "target": body.get("target"),
                        # Its work was on main before this landing ran: an
                        # earlier attempt of the same change got there, and
                        # land.sh compared by patch rather than by text and
                        # said so instead of calling it a collision.
                        "already": bool(body.get("already")),
                        # Or the run got it there itself, with `./land.sh` in
                        # its own turn, which is the ordinary way a change to
                        # Rouh lands and is no earlier attempt of anything.
                        "pushed_itself": bool(body.get("pushed_itself"))}
        mine = bool(self.one.device_id) and run.get("by") == self.one.device_id
        if kind == "work.landed":
            await self._task_made(run_id, result["files"])
        # The deploy comes before that question, and is the one thing here
        # that does. Whether Rouh or a person at a terminal started the
        # run decides who narrates the result; it does not decide whether a
        # change that is on main goes live, because "done" means deployed
        # for every run of it.
        deployed, live = "", False
        if kind == "work.landed" and space == "rouh":
            live, deployed = await self._deployed(
                str(result["sha"] or "")[:7], result["files"], body)
            result["deployed"], result["live"] = deployed, live
        if not mine:
            # Started from a terminal or a browser: the person is there, and
            # the run's own screen is what they are reading.
            return {"kind": "deployed", "deployed": deployed, "live": live} if deployed else None
        title = (run.get("title") or "the job").strip()
        final = str(run.get("last_message") or "")
        if run.get("boxes") and final:
            # A run handed boxes: whatever they held is taken out before its words go anywhere.
            from . import boxes

            final = await asyncio.to_thread(boxes.redact_run, run_id, final)
        said = fingerprint(final)
        if kind in ("agent.stopped", "work.nothing-new") and run_id in self._reported and (
                self._reported[run_id] == said or not final):
            return {"kind": "silent"}
        # A turn that ended at a step that is the person's, handed to the live
        # browser (`browser_handoff`). The run is open at its prompt waiting
        # for it, so that is what is put in front of them rather than a result;
        # a change to Rouh's own code that landed on the way still has what
        # became of its deploy said first.
        handoff = (browser_handoff.find(final)
                   if kind in ("agent.stopped", "work.nothing-new", "work.landed") else None)
        rouh_landed = kind == "work.landed" and space == "rouh"
        if (handoff is None and kind in ("work.landed", "work.nothing-new", "agent.stopped")
                and await self._goal_step_done(run_id, final, result["files"],
                                               result.get("sha"))):
            # A goal step's run: its step and the goal's chat say it, no card.
            result["kind"] = "goal_step"
            self._reported[run_id] = said
            return result
        if kind in ("run.ended", "work.not-landed") and await self._goal_step_done(
                run_id, final, [], ok=False,
                why=_left_behind(body) or str(result.get("reason") or "")):
            # Its step says it is stuck and why; the report below still goes on.
            pass
        if kind == "run.ended":
            await self._show_left_behind(run_id, title, final, result, run, body)
        elif run.get("stalled") and (kind in ("agent.pause-ended", "work.landed") or (
                kind == "work.nothing-new" and not _left_behind(body))):
            # Its turn was called over for it, so whatever was saved on the
            # way, it is never a "Done": what it was waiting for never came.
            await self._show_stalled(run_id, title, final, result, run,
                                     landed=kind == "work.landed")
        elif handoff is not None and not rouh_landed:
            await self._show_handoff(
                run_id, title, handoff, result,
                saved=saved_files(result["files"]) if kind == "work.landed" else "")
        elif kind == "agent.stopped":
            await self._show_done(run_id, title, final, result)
        elif kind == "work.nothing-new":
            if space == "rouh" or _left_behind(body):
                # Work left uncommitted is unfinished in any space: an
                # "Answer" card with Done on it would hide it.
                await self._show_unsaved(run_id, title, final, result, body, run)
            else:
                await self._show_answer(run_id, title, final, result)
        elif kind == "work.not-landed":
            if body.get("needs_person"):
                # Rung six of the ladder in land.sh. The conflict record is
                # written and the question reaches the person from one place
                # with both sides and the four choices on it (`ConflictFeed`
                # in runtime.py). A "Needs you" card here as well would be
                # the same news twice, and the plainer half of it.
                result.update(kind="conflict", conflict=body.get("conflict"),
                              question=body.get("question"))
                log.warning("run %s needs the person to decide its conflict: %s",
                            run_id, body.get("question") or result.get("reason"))
            elif await self._redo(run_id, title, run, body, result):
                pass
            elif space == "assistant":
                await self._show_needs_you(run_id, title, result)
            else:
                await self._show_code_needs_you(run_id, title, result, space)
        elif space == "rouh":
            await self._show_change(run_id, title, final, result)
        elif space != "assistant":
            await self._show_code(run_id, title, final, result, space)
        else:
            page = pick_page(result["files"], final)
            if page:
                await self._show_page(run_id, title, page, final, result)
            else:
                await self._show_files(run_id, title, result["files"], final, result)
        if handoff is not None and rouh_landed:
            await self._show_handoff(run_id, title, handoff, result,
                                     saved="a change to your own code, reported above")
        if result.get("kind") in ("page", "files", "answer", "change", "handoff", "stalled"):
            self._reported[run_id] = said
        await self._phone(run_id, title, final, result)
        return result

    # --- rung five: the run is gone, so redo rather than untangle ---------------

    async def _redo(self, run_id, title, run, body, result) -> bool:
        """Start a fresh run from the current main to write the change again.

        Rung five of the ladder on card 488. The run that wrote the code is not
        there to reconcile anything, and untangling a stale patch by hand is the
        slower, worse half of the choice: on 20 September 2026 the
        thread-ownership fix was untangled twice and got nowhere, and writing it
        again on top of what was there took one pass. So a fresh run is started
        in the same space with the old commit message, the old diff and what
        landed in the meantime, and told to reimplement.

        False when there is nothing to start from, when this work has already
        been redone once, or when the run that raised it is still going, because
        then rung four is the right one and the program has already taken it.
        """
        record_id = body.get("conflict")
        if not record_id or run.get("state") not in ("idle", "done", "failed", "lost",
                                                     "unfinished", "refused"):
            return False
        if run_id in self._redone:
            log.info("run %s has already been redone once; the person decides this one", run_id)
            return False
        record = next((r for r in conflicts.read_all() if str(r.get("id")) == str(record_id)),
                      None)
        if record is None or record.get("redone_as"):
            return False
        first = str(run.get("brief") or "")
        brief = conflicts.redo_brief(record, brief=first)
        if rules.unruled(first) != first:
            # It was the person's own work, so it is written again under their
            # rules as they are now (`rules.with_rules`), not the copy it had.
            brief = await asyncio.to_thread(rules.with_rules, brief, chat_id=runs.chat_of(run_id))
        # A Claude Code run is redone on the code runs' tier, at its model's
        # level, the way every run Rouh starts is (`starting._ask_the_program`).
        told = {}
        if (run.get("engine") or "claude") == "claude":
            work = await asyncio.to_thread(modeldefaults.use_pair, "code_runs")
            told = {"model": work.model, "effort": work.effort}
        try:
            got = await self.one.ask("start", brief=brief, title=f"Again: {title}"[:120],
                                     space=run.get("space") or "assistant", **told)
        except Exception:
            log.exception("could not start a fresh run to redo %s", run_id)
            return False
        fresh = str((got or {}).get("run") or "")
        if not fresh:
            return False
        # The fresh run is the same request as the one it is rewriting, so it
        # came from the same conversation and reports there too. Its row is
        # written here rather than waited for: a reference needs a run to hang
        # off, and the program's own feed writes the same fields a moment later
        # from the same facts (`runs.one_run`).
        started_in = runs.chat_of(run_id)
        if started_in:
            runs.record(fresh, title=f"Again: {title}"[:120], brief=runs.request_of(brief)[:4000],
                        policy=runs.ONE_POLICY,
                        workspace=str(run.get("space") or "assistant"),
                        state="running", phase="starting", first=True)
            runs.came_from(fresh, started_in)
        # Made by whoever made the first (`rouh/task_origin.py`).
        with contextlib.suppress(Exception):
            task_origin.same_maker(run_id, fresh)
        self._redone.add(run_id)
        with contextlib.suppress(Exception):
            conflicts.set_state(record, conflicts.HANDBACK, redone_as=fresh)
        result.update(kind="redone", redo=fresh)
        log.info("run %s cannot fix its own clash, so %s is writing it again", run_id, fresh)
        await self._say(
            f'[A job finished and its work would not go onto main: "{title}". Something '
            "landed there while it ran and the two collide, and the job itself has stopped, "
            "so a fresh one has been started to write the change again on top of what is "
            "there now. Nothing is lost. Tell the person that in one short sentence. Do not "
            "start anything.]")
        return True

    # --- a turn that saved nothing ----------------------------------------------

    async def _show_answer(self, run_id, title, final, result) -> None:
        """An answer, or work done on the server itself: nothing was saved to a repository."""
        text = answer_from(final) or (
            "It finished without saving anything, and its last message could not be read.")
        card_id = await self._card(f"Answer: {title}", [{"block": "text", "text": text}],
                                   foot={"ended": run_report.DONE})
        result.update(kind="answer", card_id=card_id)
        log.info("one run %s finished and saved nothing", run_id)
        spoken = summary_from(final, limit=1500)
        await self._say(
            f'[A job has finished: "{title}". It saved nothing to the workspace; what it did or '
            f"found is on the screen as card {card_id}. In its own words: "
            f"{spoken or 'it said nothing that could be read'} Give the person that in one or "
            "two short sentences. Do not start anything.]"
        )

    async def _show_done(self, run_id, title, final, result) -> None:
        """A run in a folder of its own, which has nothing to save."""
        text = answer_from(final) or "It finished, and its last message could not be read."
        card_id = await self._card(f"Done: {title}", [{"block": "text", "text": text}],
                                   foot={"ended": run_report.DONE})
        result.update(kind="answer", card_id=card_id)
        log.info("one run %s finished its turn", run_id)
        spoken = summary_from(final, limit=1500)
        await self._say(
            f'[A job has finished: "{title}". What it did or found is on the screen as card '
            f"{card_id}. In its own words: {spoken or 'it said nothing that could be read'} "
            "Tell the person in one or two short sentences. Do not start anything.]"
        )

    # --- work in a repository added as a space ------------------------------------

    async def _show_code(self, run_id, title, final, result, space) -> None:
        summary = summary_from(final)
        blocks: list[dict] = []
        if summary:
            blocks.append({"block": "text", "text": summary})
        items = _items(result["files"])
        if items:
            blocks.append({"block": "list", "items": items})
        if result.get("branch"):
            where = (f"Pushed on the branch {result['branch']}, for a pull request into "
                     f"{result.get('target') or 'its development branch'}.")
            blocks.append({"block": "text", "text": where})
            if result.get("compare"):
                blocks.append({"block": "link", "text": "Open the pull request",
                               "href": result["compare"]})
        else:
            where = f"Saved on {space}'s main branch at {str(result.get('sha') or '')[:7]}."
            blocks.append({"block": "text", "text": where})
        card_id = await self._card(f"Done: {title}", blocks,
                                   foot={"ended": run_report.DONE,
                                         "sha": result.get("sha") or "",
                                         "branch": result.get("branch") or "",
                                         "where": space})
        result.update(kind="files", card_id=card_id)
        log.info("one run %s in %s saved its work: %s", run_id, space, where)
        await self._say(
            f'[A job in the repository {space} has finished: "{title}". {where} Card {card_id} '
            f"lists the files. What it did, in its own words: {summary or 'it did not say'} "
            "Tell the person in one or two short sentences. Do not start anything.]"
        )

    async def _show_code_needs_you(self, run_id, title, result, space) -> None:
        reason = result.get("reason") or "it did not say why"
        where = "your own code" if space == "rouh" else f"the repository {space}"
        card_id = await self._card(f"Needs you: {title}", [{"block": "text", "text": reason}],
                                   foot={"ended": run_report.STOPPED,
                                         "why": "its work could not be saved"})
        result.update(kind="needs_you", card_id=card_id)
        log.warning("one run %s in %s could not be saved: %s", run_id, space, reason)
        await self._say(
            f'[The job "{title}" in {where} stopped, but its work could not be saved: '
            f"{reason} Tell the person in one or two short sentences.]"
        )

    # --- a change to Rouh's own code ------------------------------------------

    async def _show_change(self, run_id, title, final, result) -> None:
        """A change to Rouh's own code: pushed to main, and deployed here.

        The deploy has already been started, in ``report``, so the card says
        what was deployed rather than what somebody meant to deploy. Nobody is
        asked, and no model has to remember to call anything: that step is what
        stood between a change being on main and a change being live.
        """
        summary = summary_from(final)
        sha = str(result.get("sha") or "")[:7]
        # Already done, in `report`, because it happens whoever started the run.
        deployed = result.get("deployed") or NOT_DEPLOYED
        # Whether the commit is what the machine is serving, checked against the
        # health pages rather than assumed. A change on main that nothing is
        # serving is not done, and is never said as though it were.
        live = bool(result.get("live"))
        blocks: list[dict] = []
        if summary:
            blocks.append({"block": "text", "text": summary})
        items = _items(result["files"])
        if items:
            blocks.append({"block": "list", "items": items})
        where = (f"Already on Rouh's main at {sha}, from an earlier attempt of the same "
                 "change, so nothing was pushed twice"
                 if result.get("already") and not result.get("pushed_itself")
                 else f"Pushed to Rouh's main at {sha}")
        blocks.append({"block": "text",
                       "text": f"{where}. {'Deployed' if live else 'NOT LIVE'}: {deployed}."})
        card_id = await self._card(f"Changed: {title}", blocks,
                                   foot={"ended": run_report.DONE if live else run_report.STOPPED,
                                         "why": "" if live else f"on main and NOT live: {deployed}",
                                         "sha": sha, "where": "Rouh",
                                         "touched": result["files"]})
        result.update(kind="change", card_id=card_id, deployed=deployed, live=live)
        log.info("change to Rouh %s pushed to main at %s; live: %s; deploy: %s",
                 run_id, sha, live, deployed)
        if live:
            went = (f"and it is deployed already - {deployed} - with nobody asked, "
                    "which is the standing policy")
            ending = ("Tell the person in one or two short sentences, saying what was pushed "
                      "and what was deployed. Do not call deploy_myself: it has been deployed.")
        else:
            went = (f"and it is NOT live: {deployed}. The work is on main and the machine is "
                    "not serving it, so this change is not done")
            ending = ("Tell the person in one or two short sentences: say plainly that the "
                      "change is on main and is not live, and say why. Do not call it done.")
        await self._say(
            f'[The change to your own code has finished: "{title}". {where}, {went}. '
            f"Card {card_id} lists the files it changed. What it did, in its "
            f"own words: {summary or 'it did not say'} {ending}]"
        )

    # --- a run that ended with work nobody saved ----------------------------------

    async def _show_left_behind(self, run_id, title, final, result, run, body) -> None:
        """The run is over and some of its work never reached main.

        This is the one report that is not about a turn. "Done" everywhere else
        means committed and on main; this says, in the same breath, what is on
        main and what is not, and where the checkout still holding it is, so the
        work can be finished rather than found weeks later.
        """
        left = _left_behind(body)
        saved = bool(body.get("saved"))
        where = (f"Some of its work is on main; {left}." if saved
                 else f"None of its work reached main: {left}.")
        cwd = str(run.get("cwd") or "")
        blocks = [{"block": "text", "text": where}]
        if cwd:
            blocks.append({"block": "text", "text": f"Its checkout is kept at {cwd}."})
        said = answer_from(final)
        if said:
            blocks.append({"block": "text", "text": said})
        card_id = await self._card(f"Unfinished: {title}", blocks,
                                   foot={"ended": run_report.STOPPED,
                                         "why": "it ended with work that is not on main"})
        result.update(kind="unfinished", card_id=card_id, reason=left, saved=saved)
        log.warning("one run %s ended unfinished: %s (checkout %s)", run_id, left, cwd or "gone")
        await self._say(
            f'[The job "{title}" has ended without finishing. {where} Its checkout is still at '
            f"{cwd or 'nowhere it can be found'}, and card {card_id} says so. Tell the person "
            "plainly, in one or two short sentences, that it did not finish and that its work "
            "is not on main. Do not say it is done. Do not start anything.]"
        )

    async def _show_stalled(self, run_id, title, final, result, run, *,
                            landed: bool = False) -> None:
        """A turn that paused for what it started, and nothing ever woke it.

        Not a finish, and never called Done: the run said it would carry on
        when something reported, and nothing did (``run["stalled"]`` says
        what). Its closing words are kept under that, because they are what it
        meant to do next.
        """
        why = str(run.get("stalled") or "nothing woke it")
        blocks = [{"block": "text", "text": f"It stopped waiting: {why}."}]
        saved = ""
        if landed:
            sha = str(result.get("sha") or "")[:7]
            saved = f"What it had done by then is on main at {sha}"
            if result.get("deployed"):
                saved += (f", deployed: {result['deployed']}" if result.get("live")
                          else f", and NOT live: {result['deployed']}")
            saved += "."
            items = _items(result["files"])
            blocks.append({"block": "text", "text": saved})
            if items:
                blocks.append({"block": "list", "items": items})
        elif run.get("landed"):
            saved = f"Its earlier work is on main at {str(run['landed'])[:7]}."
            blocks.append({"block": "text", "text": saved})
        said = answer_from(final)
        if said:
            blocks.append({"block": "text", "text": said})
        card_id = await self._card(f"Stopped: {title}", blocks,
                                   foot={"ended": run_report.STOPPED,
                                         "why": "it did not finish"})
        result.update(kind="stalled", card_id=card_id, reason=why)
        log.warning("one run %s stopped waiting: %s", run_id, why)
        await self._say(
            f'[The job "{title}" was waiting on work it started, and {why}, so its turn was '
            f"called over. {saved} Card {card_id} says so. Tell the person plainly in one or two short "
            "sentences that it did not finish. Do not say it is done. Do not start anything.]"
        )

    async def _show_unsaved(self, run_id, title, final, result, body, run=None) -> None:
        """A turn of a change to Rouh that put nothing new on main.

        Two different things, and the card says which, because the word on it
        is read before anything else on it. A turn that left its changes
        uncommitted has work that is not saved, and is called unfinished, the
        same word the run's own end uses for it. Anything else is a turn with
        nothing to save: an answer, a look round, or a follow-up to a change
        that is on main already from an earlier turn.

        This card used to be called "Not saved" in every case, and a run that
        had pushed its own work with `./land.sh` arrived here too, so a change
        that was on main and deployed was put in front of the person as "NOT
        SAVED: Draggable divider..." (feedback fr_9e9cea243870, 23 September
        2026). That run is reported as landed now (`one/asuser.py`); what is
        left here is only ever a turn that truly put nothing new on main.
        """
        left = _left_behind(body)
        if not left:
            await self._show_done(run_id, title, final, result)
            return
        # An earlier turn's landing is its own news, already reported, and it
        # stays true: said here so this card is not read as though nothing of
        # the run ever reached main, nor as though the later work did.
        earlier = str((run or {}).get("landed") or "")[:7]
        before = (f"Its earlier work is on main at {earlier}, and that is unchanged. "
                  if earlier else "")
        blocks = [{"block": "text",
                   "text": f"{before}Nothing new reached main since: {left}." if earlier
                   else f"Nothing new reached main: {left}."}]
        if (run or {}).get("stalled"):
            blocks.append({"block": "text",
                           "text": f"It stopped waiting: {run['stalled']}."})
        said = answer_from(final)
        if said:
            blocks.append({"block": "text", "text": said})
        what = "change to your own code" if run and run.get("space") == "rouh" else "job"
        card_id = await self._card(f"Unfinished: {title}", blocks,
                                   foot={"ended": run_report.STOPPED,
                                         "why": "nothing new of it reached main"})
        result.update(kind="unfinished", card_id=card_id, reason=left)
        log.info("change to Rouh %s stopped with nothing saved: %s", run_id, left)
        spoken = summary_from(final, limit=1500)
        await self._say(
            f'[The {what} "{title}" has stopped, and nothing new of it '
            f"reached main: {left}. {before}Card {card_id} says so. In its own words: "
            f"{spoken or 'it said nothing that could be read'} Tell the person plainly in one "
            "or two short sentences that this work is not on main. Do not say it is done. "
            "Do not start anything.]"
        )
