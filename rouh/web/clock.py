"""Clockwork (the Reminders page until 8 October 2026) and the Goals page: read, add and change.

    GET  /api/reminders           everything scheduled, with the words to draw it
    POST /api/reminders/save      {id?, kind, title, what, date, time, repeat, days,
                                  silos?, about_rouh?}: `title` the one line, `what`
                                  the description, `about_rouh` whether it is about
                                  Rouh itself (left out of the morning brief when it
                                  repeats; from the chat it was made in when left out)
    POST /api/reminders/act       {id, act: pause | resume | delete | try | rouh |
                                  not_rouh}: the last two mark it about Rouh or not,
                                  Rouh's own server jobs too
    POST /api/reminders/read      {words}: a sentence read into when, a title and a
                                  description
                                  by Luna (`reminder_words.read`), saved nowhere
    GET  /api/goals               every goal, with its plan
    POST /api/goals/save          {name, about}: a new goal, and Rouh asking
                                  about it in its own chat
    POST /api/goals/step          {goal, step, act: now | at | after | clear |
                                   status | reword, date?, time?, after?,
                                   status?, wording?}: with wording, the
                                   person's own words for the step are kept
                                   first, and what is started is what they say.
                                   From a step's own page, {folder, act: now |
                                   status | note | tick, status?, note?, choice?}
                                   instead: the step whose folder that is, in
                                   the goal above it; note and choice are what
                                   the person wrote and picked on its How to
                                   do it page, kept on the step. And tick
                                   {index, text, done}: one of the person's
                                   own steps on that page ticked or unticked
                                   (`goals.YOUR_STEPS`), refused 409 when
                                   the list changed under the page.
                                   again {step, feedback}: Rouh does the step
                                   again, told what the person did not like.
                                   From the goal's own page, where its
                                   streams are, {folder, step?, act, ...}: the
                                   goal whose folder that is; act deadline
                                   {deadline}, arrange {streams: [{id, name,
                                   steps}]}, split (Rouh splits the plan into
                                   streams) and go {stream?} (Rouh carries on
                                   by itself) need no step
    POST /api/goals/revise        {goal | folder, step, wording, ask}: the step
                                  rewritten by Rouh the way the person asked,
                                  saved nowhere until they save or start it

Petar, 26 September 2026: "please implement 1 and 4. think carefully about the
interface that should be visible and easy and friendly". Everything here goes
through `runtime.timekeeper`, the very object the model's `schedule` and goal
tools use, so a reminder typed on the page and one said out loud are the same
row and every open tab of the person's hears about either.

A goal is a task tagged Goal since 27 September 2026, with its plan as its
steps (`rouh/goals.py`): what is saved here is a name and everything the person
knows about it, and what a step can be asked for is Rouh doing it now, at a
time, or after another step.

Every request is on the person's own clock: the page sends the time zone its
device is on as `X-Time-Zone`, which is kept as theirs (`clock.remember`), and
the whole request runs inside `clock.person`, so "tomorrow at nine" is nine
where they are.

Every answer is the whole list again, drawn from the database, so the page
shows what is there rather than what it guessed a press did. Every reminder is
the signed-in person's own: each query names their user and organisation. A
goal is a task in the workspace, whose it is like every other task there.
"""
from __future__ import annotations

import asyncio
import functools
from datetime import datetime

from django.http import HttpRequest

from .. import protected
from .common import answer, body_of, only, refuse, who

NO_STORE = {"Cache-Control": "no-store"}


def _keeper():
    from rouh import runtime

    return runtime.timekeeper


async def _reminders(me) -> dict:
    from rouh import reminders

    def listed():
        from rouh import nightly_feature

        # The nightly feature run is a feature of its own since 3 November 2026: its row is on its
        # page in Evolution (`rouh/web/nightly_run.py`), and the same row still starts it.
        views = [reminders.view(r) for r in reminders.rows(me) if (r.job or "") != nightly_feature.JOB]
        live = sorted((v for v in views if v["state"] != "done"),
                      key=lambda v: (v["state"] != "on", v["next_at"] or 9e18))
        done = sorted((v for v in views if v["state"] == "done"),
                      key=lambda v: -(v["last_at"] or 0))[:10]
        return live + done

    def every_silo():
        from rouh import silos

        return [s.chip() for s in silos.of(me.user_id, me.org_id)]

    keeper = _keeper()
    return {"reminders": await asyncio.to_thread(listed),
            "silos": await asyncio.to_thread(every_silo),
            "telegram": bool(keeper.telegram and keeper.telegram.configured())}


async def _goals(me) -> dict:
    from rouh import goals

    keeper = _keeper()
    return {"goals": await asyncio.to_thread(goals.listing, me),
            "telegram": bool(keeper.telegram and keeper.telegram.configured())}


def _signed_in(request):
    """Who is asking; a query, so it is asked on a thread."""
    if hasattr(request, "rouh_me"):
        return request.rouh_me
    return who(request)


def _theirs(request):
    """Who is asking, with the time zone their page sent kept as theirs."""
    from rouh import clock

    me = who(request)
    zone = request.headers.get("X-Time-Zone", "")
    if me is not None and zone:
        clock.remember(me, zone)
    return me


def their_clock(view):
    """The view, run on the clock of whoever is asking (`clock.person`)."""
    @functools.wraps(view)
    async def wrapped(request, *args, **kwargs):
        from rouh import clock

        me = await asyncio.to_thread(_theirs, request)
        request.rouh_me = me
        with clock.person(me):
            return await view(request, *args, **kwargs)
    return wrapped


@only("GET")
@their_clock
async def reminders_list(request: HttpRequest):
    me = await asyncio.to_thread(_signed_in, request)
    if me is None:
        return refuse("Sign in first.", 401)
    return answer(await _reminders(me), headers=NO_STORE)


def _first(body: dict):
    """The first time a form gave, as a moment on the person's clock."""
    from rouh import clock, reminders

    day = str(body.get("date") or "").strip()
    at = str(body.get("time") or "").strip()
    if not at:
        raise ValueError("What time? It was empty.")
    if not day:
        return reminders.moment_of(at)
    try:
        found = datetime.fromisoformat(f"{day}T{at}")
    except ValueError:
        raise ValueError("That is not a date and a time.") from None
    return found.replace(tzinfo=clock.zone())


def _about_rouh(body: dict):
    """The form's About Rouh, True or False, or None when it did not say."""
    got = body.get("about_rouh")
    return got if isinstance(got, bool) else None


@only("POST")
@their_clock
async def reminders_save(request: HttpRequest):
    from rouh import reminders

    me = await asyncio.to_thread(_signed_in, request)
    if me is None:
        return refuse("Sign in first.", 401)
    body = body_of(request)
    keeper = _keeper()
    kind = str(body.get("kind") or "remind")
    if kind not in ("remind", "do"):
        return refuse("That kind is not one Clockwork has.", 400)
    try:
        first = _first(body)
        if body.get("id"):
            row = await asyncio.to_thread(reminders.one, me, body.get("id"))
            if row is None:
                return refuse("That is not in Clockwork any more.", 404,
                              **(await _reminders(me)))
            fields = {"what": body.get("what") or "", "title": body.get("title") or "",
                      "repeat": body.get("repeat") or "once",
                      "days": body.get("days") or (), "kind": kind,
                      "silos": [str(k) for k in body["silos"]] if isinstance(body.get("silos"), list) else None,
                      "about_rouh": _about_rouh(body)}
            # What the person typed is their own words, kept with what asked for it before.
            changed = await asyncio.to_thread(reminders.change, me, row.id, first=first,
                                              asked=[fields["title"], fields["what"]], **fields)
            keeper.clock.poke()
            await keeper.tell(me)
            saved = changed.id
        else:
            made = await asyncio.to_thread(
                reminders.add, me, what=body.get("what") or "", title=body.get("title") or "",
                kind=kind,
                chat_id="", first=first, repeat=body.get("repeat") or "once",
                days=body.get("days") or (),
                # Typed on the page by the person: their own words (`reminders.asked_of`).
                asked=[body.get("title") or "", body.get("what") or ""],
                silos=[str(k) for k in body["silos"]] if isinstance(body.get("silos"), list) else None,
                about_rouh=_about_rouh(body))
            keeper.clock.poke()
            await keeper.tell(me)
            saved = made.id
    except ValueError as exc:
        return refuse(str(exc), 400)
    return answer({"ok": True, "saved": saved, **(await _reminders(me))}, headers=NO_STORE)


@only("POST")
@their_clock
async def reminders_read(request: HttpRequest):
    """A sentence read into a reminder's parts by Luna, for the form to fill in."""
    from rouh import reminder_words

    me = await asyncio.to_thread(_signed_in, request)
    if me is None:
        return refuse("Sign in first.", 401)
    words = str(body_of(request).get("words") or "")[:2000]
    try:
        found = await reminder_words.read(words, me)
    except reminder_words.CannotRead as exc:
        return refuse(str(exc), 503)
    return answer({"ok": True, **found.view()}, headers=NO_STORE)


@only("POST")
@their_clock
async def reminders_act(request: HttpRequest):
    from rouh import reminders

    me = await asyncio.to_thread(_signed_in, request)
    if me is None:
        return refuse("Sign in first.", 401)
    body = body_of(request)
    act = str(body.get("act") or "")
    keeper = _keeper()
    row = await asyncio.to_thread(reminders.one, me, body.get("id"))
    if row is None:
        return refuse("That is not in Clockwork any more.", 404, **(await _reminders(me)))
    try:
        if act == "delete":
            await keeper.drop(me, row.id)
        elif act in ("pause", "resume"):
            await keeper.change(me, row.id, state="paused" if act == "pause" else "on")
        elif act == "try":
            await keeper.try_now(me, row.id)
        elif act in ("rouh", "not_rouh"):
            await keeper.change(me, row.id, about_rouh=act == "rouh")
        else:
            return refuse("That is not something Clockwork can do.", 400)
    except ValueError as exc:
        return refuse(str(exc), 400, **(await _reminders(me)))
    return answer({"ok": True, **(await _reminders(me))}, headers=NO_STORE)


@only("GET")
@their_clock
async def goals_list(request: HttpRequest):
    me = await asyncio.to_thread(_signed_in, request)
    if me is None:
        return refuse("Sign in first.", 401)
    return answer(await _goals(me), headers=NO_STORE)


@only("POST")
@their_clock
async def goals_save(request: HttpRequest):
    from rouh import goals

    me = await asyncio.to_thread(_signed_in, request)
    if me is None:
        return refuse("Sign in first.", 401)
    body = body_of(request)
    try:
        made = await _keeper().set_goal(me, name=str(body.get("name") or ""),
                                        about=str(body.get("about") or ""))
    except goals.Refused as exc:
        return refuse(str(exc), 400)
    return answer({"ok": True, "saved": made["goal"].id, "chat": made["chat"],
                   **(await _goals(me))}, headers=NO_STORE)


#: What Rouh is told of a stream started because the plan was rearranged.
_STREAMS_GO = ("The plan's streams were rearranged, and every stream goes on at once. "
               + protected.WORDS)


@only("POST")
@their_clock
async def goals_step(request: HttpRequest):
    """One step of a goal: Rouh does it now, at a time, after another, or its status."""
    from rouh import goals

    me = await asyncio.to_thread(_signed_in, request)
    if me is None:
        return refuse("Sign in first.", 401)
    body = body_of(request)
    act = str(body.get("act") or "")
    step = str(body.get("step") or "")
    keeper = _keeper()
    folder = str(body.get("folder") or "")
    mapped = await asyncio.to_thread(_goal_by_folder, folder) if folder else None
    if mapped is not None:
        # The goal's own page, with its roadmap: the goal is where it is, and
        # the step is the one pressed on it.
        goal = mapped
    elif folder:
        # A step's own page knows where it is, not which goal it is in.
        if act not in ("now", "status", "note", "tick"):
            return refuse("That is not something a step's page can do.", 400)
        goal, step = await asyncio.to_thread(_step_by_folder, folder)
    else:
        goal = await asyncio.to_thread(_goal_by_id, str(body.get("goal") or ""))
    if goal is None:
        return refuse("That goal is not there any more.", 404, **(await _goals(me)))
    if act == "arrange":
        # The steps moved between streams or within one, on the goal's page.
        try:
            await asyncio.to_thread(goals.arrange, goal, body.get("streams"))
        except goals.Refused as exc:
            return refuse(str(exc), 400, **(await _goals(me)))
        # A stream the move made, or a step moved to the front of one, goes
        # on at once alongside the others (fr_a25fe6a202a3).
        await keeper.start_streams_quietly(me, goal, _STREAMS_GO)
        await keeper.tell(me)
        return answer({"ok": True, "goal": goal.id, **(await _goals(me))}, headers=NO_STORE)
    if act == "check":
        # Check now on a step that is the goal's quest's (`rouh/questcheck.py`): one beat
        # on the quest, the same as on the quest's own page. Never a goal run.
        from rouh import questcheck, quests, runtime

        row = next((w for w in await asyncio.to_thread(quests.all_of, me)
                    if w.task_id == goal.id), None)
        if row is None:
            return refuse("This goal is no quest's, so there is nothing to check.", 404,
                          **(await _goals(me)))
        try:
            said = await runtime.pulse.work_now(me, row.id,
                                                while_paused=body.get("while_paused") is True,
                                                where="goal")
        except questcheck.Refused as exc:
            return refuse(str(exc), 409, **(await _goals(me)))
        await keeper.tell(me)
        return answer({"ok": True, "goal": goal.id, "said": said, **(await _goals(me))},
                      headers=NO_STORE)
    if act in ("pause", "resume", "redirect"):
        # The person holding or steering the goal from its own page (`goals.PAUSED`,
        # `goals.DIRECTION`).
        try:
            if act == "pause":
                await keeper.pause(me, goal)
            elif act == "resume":
                await keeper.resume(me, goal)
            elif str(body.get("direction") or "").strip():
                await keeper.redirect(me, goal, str(body.get("direction")))
            else:
                await asyncio.to_thread(goals.set_direction, goal, "")
                await keeper.tell(me)
        except ValueError as exc:
            return refuse(str(exc), 400, **(await _goals(me)))
        return answer({"ok": True, "goal": goal.id, **(await _goals(me))}, headers=NO_STORE)
    if act == "go":
        try:
            started = await keeper.let_go(me, goal, str(body.get("stream") or ""))
        except ValueError as exc:
            return refuse(str(exc), 400, **(await _goals(me)))
        return answer({"ok": True, "goal": goal.id, "started": [s["id"] for s in started],
                       **(await _goals(me))}, headers=NO_STORE)
    if act == "tick" and mapped is None and folder:
        # One of his steps ticked on the step's How to do it page
        # (`goals.YOUR_STEPS`): kept at once, and nothing else changes.
        try:
            row = await asyncio.to_thread(goals.find_step, goal, step)
            if row[0] is None:
                raise goals.Refused("That step is not part of this goal any more.")
            index = int(body.get("index"))
        except (TypeError, ValueError) as exc:
            return refuse(str(exc) if isinstance(exc, goals.Refused)
                          else "Which step was ticked is not clear.", 400)
        try:
            items = await asyncio.to_thread(goals.tick_your_step, row[0], index,
                                            str(body.get("text") or ""),
                                            bool(body.get("done")))
        except goals.Refused as exc:
            return refuse(str(exc), 409)
        await keeper.tell(me)
        return answer({"ok": True, "goal": goal.id,
                       "ticked": sum(1 for x in items if x["done"]), "of": len(items)},
                      headers=NO_STORE)
    if act == "deadline":
        try:
            await asyncio.to_thread(goals.set_deadline, goal, body.get("deadline"))
        except goals.Refused as exc:
            return refuse(str(exc), 400, **(await _goals(me)))
        await keeper.tell(me)
        return answer({"ok": True, "goal": goal.id, **(await _goals(me))}, headers=NO_STORE)
    try:
        wording = body.get("wording")
        if wording is not None:
            row = await asyncio.to_thread(goals.find_step, goal, step)
            if row[0] is None:
                raise goals.Refused("That step is not part of this goal any more.")
            await asyncio.to_thread(goals.reword, row[0], wording)
        if mapped is None and folder and ("note" in body or "choice" in body):
            # What he wrote and picked on the step's How to do it page, kept
            # before it is marked complete, so the two go together.
            row = await asyncio.to_thread(goals.find_step, goal, step)
            if row[0] is None:
                raise goals.Refused("That step is not part of this goal any more.")
            await asyncio.to_thread(
                goals.change_step, row[0],
                note=str(body["note"]) if "note" in body else None,
                choice=str(body["choice"]) if "choice" in body else None)
        if act == "reword":
            if wording is None:
                return refuse("There is nothing to keep.", 400)
            await keeper.tell(me)
        elif act == "note":
            await keeper.tell(me)
        elif act == "again":
            # Do it again, from the goal's page: what he did not like goes
            # first in what the run is told (fr_6acc50075110).
            feedback = str(body.get("feedback") or "").strip()
            if not feedback:
                return refuse("Say what you did not like first.", 400)
            await keeper.do_step(me, goal, step, unattended=False,
                                 why=goals.again_why(feedback))
        elif act == "now":
            await keeper.do_step(me, goal, step, unattended=False,
                                 why="The person asked for this step to be started now.")
        elif act == "at":
            await keeper.schedule_step(me, goal, step, first=_first(body))
        elif act == "after":
            await keeper.step_after(me, goal, step, str(body.get("after") or ""))
        elif act == "clear":
            await keeper.clear_step_run(me, goal, step)
        elif act == "status":
            # The person on the page: their Mark complete is the only one that is.
            await keeper.step_status(me, goal, step, str(body.get("status") or ""),
                                     by_person=True)
        else:
            return refuse("That is not something a step can do.", 400)
    except ValueError as exc:
        return refuse(str(exc), 400, **(await _goals(me)))
    return answer({"ok": True, "goal": goal.id, **(await _goals(me))}, headers=NO_STORE)


@only("POST")
@their_clock
async def goals_revise(request: HttpRequest):
    """A step of a goal rewritten by Rouh the way the person asked, not yet kept."""
    from rouh import goals

    me = await asyncio.to_thread(_signed_in, request)
    if me is None:
        return refuse("Sign in first.", 401)
    body = body_of(request)
    folder = str(body.get("folder") or "")
    goal = await asyncio.to_thread(_goal_by_folder, folder) if folder else \
        await asyncio.to_thread(_goal_by_id, str(body.get("goal") or ""))
    if goal is None:
        return refuse("That goal is not there any more.", 404)
    v = await asyncio.to_thread(goals.view, goal)
    step = goals.step_in(v, str(body.get("step") or ""))
    if step is None:
        return refuse("That step is not part of this goal any more.", 404)
    try:
        wording = await goals.revise(v, step, body.get("wording"), str(body.get("ask") or ""),
                                     who=me)
    except goals.Refused as exc:
        return refuse(str(exc), 400)
    return answer({"ok": True, "wording": wording}, headers=NO_STORE)


def _step_by_folder(folder: str):
    """The goal and the step id for a step's task found by its folder, or
    (None, "") when that folder is not a step of a goal."""
    from rouh import goals

    st = goals._store()
    task = st.by_folder("task", folder) if st is not None else None
    found = goals.of_step(task)
    return (goals.goal_above(task), task.id) if found is not None else (None, "")


def _goal_by_folder(folder: str):
    """The goal whose own folder this is, or None: a step's folder is not."""
    from rouh import goals

    st = goals._store()
    task = st.by_folder("task", folder) if st is not None and folder else None
    return _goal_by_id(task.id) if task is not None else None


def _goal_by_id(ident: str):
    """A goal by its task id, and only a task that is a goal."""
    from rouh import goals

    st = goals._store()
    task = st.get_task(ident) if st is not None and ident else None
    folder = goals._folder(task) if task is not None else None
    return task if folder is not None and goals.is_goal(goals._meta(folder)) else None
