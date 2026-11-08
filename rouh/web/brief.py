"""The morning brief's routes (`rouh/morning_brief.py`).

    GET  /api/brief                the newest brief kept, today's or, before it is made,
                                   the last one; `brief` is null when there has never
                                   been one. Never makes one.
    POST /api/brief/make           Update: make today's from the sources as they are now,
                                   doing a model's work again only for what is new
    GET  /api/brief/calendar       today's calendar read again from Google, and kept
    GET  /api/brief/past           every brief kept, newest first, each by its day
    GET  /api/brief/day/<day>      one day's brief exactly as it was kept (YYYY-MM-DD)
    GET  /api/brief/history/topics the topics Today in history can be picked for, the ones
                                   picked, the person's own and examples of them
    POST /api/brief/history/topics keep them: {topics, custom, day}; that day's Today in
                                   history is picked again for them and handed back
    GET  /api/settings/brief       the Settings card: on or off, the time, the YouTube
                                   channels, and the place the weather is for (the
                                   person's location, which is changed under Location)
    POST /api/settings/brief       save them: {on, time, channels}
    GET  /api/brief/one-thing      today's one thing, and what the picker offers
    POST /api/brief/one-thing      choose it: {category, task, sub}, or {clear: true}
    GET  /api/brief/event          one event of its calendar, whole: ?calendar=&event=
    POST /api/brief/event/answer   answer its invitation: {calendar, event, response}
    GET  /api/brief/event/prep     Before you meet: who from outside is coming, and the
                                   last emails with each (`rouh/meeting_prep.py`):
                                   ?calendar=&event=
    GET  /api/brief/event/raise    What to raise: where things stand with the guests from
                                   outside and what to raise, read from the mail by the
                                   model (`rouh/meeting_brief.py`): ?calendar=&event=;
                                   kept in today's brief, which makes it as it is made
    POST /api/brief/event/raise/correct
                                   What to raise made again with what the person says
                                   is wrong in it: {calendar, event, correction}; it
                                   replaces the one kept in today's brief
    GET  /api/brief/contacts       the contacts a birthday can be linked to: ?q=
    POST /api/brief/birthday/link  link a calendar birthday to a contact:
                                   {calendar, event, contact}, or {calendar, event, unlink: true}
    POST /api/brief/slack/dismiss  put a line of Needs you in Slack away, or bring it back:
                                   {key, at, undo}; it stays out of every brief after
                                   until its place has something newer (`slack_brief.dismiss`)
    POST /api/brief/owed           a line of Owed to you: {key, act: context|draft|send|came|dismiss|undo, text}
                                   (`rouh/owed_to_you.py`)
    POST /api/brief/no_notes       Meetings with no notes: {key, act: not_recorded|undo|library}
                                   (`rouh/notes_missing.py`)
    POST /api/brief/next_meeting   Agreed, not booked: {key, act: book|not_needed|undo}
                                   (`rouh/next_meeting.py`)
    POST /api/brief/others_changed Changed by others: {key, act: open|seen|undo, newest}
                                   (`rouh/others_changed.py`)
    POST /api/brief/shared_with_you Shared with you: {key, act: add|open|seen|undo, task}
                                   (`rouh/shared_with_you.py`)
    POST /api/brief/not_opened     Not opened yet: {key, act: write|opened|seen|undo}
                                   (`rouh/not_opened.py`)
    POST /api/brief/new_comments   New comments on your documents: {key, act: opened|task|seen|undo}
                                   (`rouh/new_comments.py`)
    POST /api/brief/talk_deck      The deck for your talk: {key, act: opened|slide|comment|seen|undo}
                                   (`rouh/talk_deck.py`)
    POST /api/brief/not_handed     Made, not handed over: {key, act: task|handed|undo}
                                   (`rouh/not_handed.py`)
    POST /api/brief/my_word        Your word, by mail: {key, act: open|context|done|undo} (`rouh/my_word.py`)
    POST /api/brief/answer_waiting Waiting on your answer: {key, act: open|put_away|undo} (`rouh/answer_waiting.py`)
    POST /api/brief/task_dates     Dates your tasks wait on: {key, act: task|context|done|undo}
                                   (`rouh/task_dates.py`)
    POST /api/brief/raise_attached What to raise reads what is attached: {act: opened|doc}, the use
                                   (`rouh/raise_attached.py`)
    POST /api/brief/host_admits    Who lets the note-taker in: {key, act: asked|put|undo|guests}
                                   (`rouh/host_admits.py`)
    POST /api/brief/refactoring/<n>/undo
                                   Undo under last night's refactoring in the Report: a
                                   run reverts that night's commits (`rouh/nightly_refactor.py`)

Each person's own, like the signatures: anybody signed in reads and changes
their own and nobody else's.
"""
from __future__ import annotations

import asyncio
import logging

from asgiref.sync import sync_to_async
from django.http import HttpRequest

from rouh import (answer_waiting, birthdays, flight_open, gone_quiet, my_word, host_admits, invite_missing, no_place, not_answered, not_said_yes, raise_attached, location, meeting_brief, meeting_prep, morning_brief, new_comments,
                  next_meeting, not_handed, not_opened, task_dates, notes_missing, one_thing, others_changed, owed_to_you,
                  shared_with_you, slack_brief, talk_deck)

from .common import answer, body_of, only, refuse, who

log = logging.getLogger("rouh.web.brief")

NO_STORE = {"Cache-Control": "no-store"}


def _telegram() -> bool:
    from rouh import runtime

    telegram = getattr(runtime.tools, "telegram", None)
    return bool(telegram and telegram.configured())


def _phone_is_mine(me) -> bool:
    from rouh import runtime, telegram

    owner = telegram.phone_owner(runtime.tenancy)
    return bool(owner and owner.user_id == me.user_id and owner.org_id == me.org_id)


async def _make(me, zone) -> dict:
    from rouh import runtime

    return await morning_brief.make(me, google=runtime.brief_google, zone=zone)


def _page_zone(request, me):
    """The clock of the page asking (`morning_brief.zone_for_page`), or None."""
    return morning_brief.zone_for_page(me, request.headers.get("X-Time-Zone", ""))


@only("GET")
async def brief_today(request: HttpRequest):
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("sign in", 401)
    zone = await sync_to_async(_page_zone)(request, me)
    day = await sync_to_async(morning_brief.today_of)(me, zone)
    settings = await sync_to_async(morning_brief.settings_of)(me)
    made = {"today": day, "schedule": {"on": settings["on"], "time": settings["time"]}}
    brief = await sync_to_async(morning_brief.kept)(me, day)
    # Opening the page never makes a brief (fr_e7c51081dc50, 9 October 2026:
    # "morning routine gets generated at 7 and anytime I visit that page I see
    # the last generated routine"). Before today's is made, the last one is
    # shown exactly as it was kept, and the page says whose day it is; when
    # there has never been one, it says so, and Update makes one.
    if brief is None or brief.get("shape") != morning_brief.SHAPE:
        last = await sync_to_async(morning_brief.latest)(me)
        if last is None:
            return answer({"ok": True, "brief": None, **made}, headers=NO_STORE)
        morning_brief.drop_stale_raises(last)
        return answer({"ok": True, "brief": await _with_one_thing(me, last), **made},
                      headers=NO_STORE)
    # What is kept is what is shown, never made again by opening it
    # (fr_5fb00def9d2d). One made on another clock than this page's has only
    # its calendar read on this one, so its times are the ones the calendar
    # shows here (`clock_moved`).
    if zone is not None and brief.get("zone") != zone.key:
        await morning_brief.clock_moved(me, google=_google(), zone=zone, brief=brief)
    if morning_brief.weather_moved(brief, settings):
        # Kept for a place the person has since left, by their location:
        # only the weather is read again.
        await morning_brief.weather_again(me, zone=zone, brief=brief)
    if "birthdays" not in brief:
        # Kept before the brief had birthdays: only they are read, not the rest.
        await morning_brief.birthdays_again(me, google=_google(), zone=zone, brief=brief)
    # Rouh's own rows, read again every time: one set since seven is there too.
    await morning_brief.reminders_again(me, zone=zone, brief=brief)
    # And the Report: last night's Synapse attempt may have finished after the brief was made.
    await morning_brief.report_again(me, zone=zone, brief=brief)
    # And Slack: a line he has answered or reacted to since goes (`slack_brief.again`).
    await slack_brief.again(me, brief)
    # And What to raise whose Slack lines were chosen under an older rule, or that read
    # nothing, is asked for again.
    morning_brief.drop_stale_raises(brief)
    return answer({"ok": True, "brief": await _with_one_thing(me, brief), **made},
                  headers=NO_STORE)


async def _with_one_thing(me, brief: dict) -> dict:
    # Read as the page asks, not kept in the brief, which is made at seven
    # before anything is chosen and made again by Update. So is the second
    # time zone, which Settings changes without the brief being made again.
    second = await sync_to_async(location.second_zone)(me)
    # So is what is owed to him from his meetings past its date (`rouh/owed_to_you.py`).
    brief = dict(brief)
    await owed_to_you.again(me, brief)
    # And what he promised somebody by email, by a day that has come (`rouh/my_word.py`).
    await my_word.again(me, brief)
    # And emails from people that asked him something and wait on his answer (`rouh/answer_waiting.py`).
    await answer_waiting.again(me, brief)
    # And his meetings with people from outside that the meeting library sent no notes for (`rouh/notes_missing.py`).
    await notes_missing.again(me, brief)
    # And a next meeting agreed in one of them that is not in his calendar (`rouh/next_meeting.py`).
    await next_meeting.again(me, brief)
    # And his pages somebody else changed since he last opened them (`rouh/others_changed.py`).
    from rouh.config import config

    await others_changed.again(me, brief, config.assistant_repo)
    # And a Google document shared with him in his own inboxes that no task links yet
    # (`rouh/shared_with_you.py`).
    from rouh import runtime

    await shared_with_you.again(me, brief, config.assistant_repo,
                                getattr(runtime, "brief_google", None))
    # And a page he shared for somebody to read that they have not opened (`rouh/not_opened.py`).
    await not_opened.again(me, brief)
    # And comments left on the Google documents his tasks link to, not answered yet
    # (`rouh/new_comments.py`).
    await new_comments.again(me, brief, config.assistant_repo, getattr(runtime, "brief_google", None))
    # And what is still open in the deck for today's or tomorrow's talk (`rouh/talk_deck.py`).
    await talk_deck.again(me, brief, getattr(runtime, "brief_google", None))
    # And work a task made for somebody that was never handed to them (`rouh/not_handed.py`).
    await not_handed.again(me, brief, config.assistant_repo)
    # And a date an open task's notes say something is due by, passed or close (`rouh/task_dates.py`).
    await task_dates.again(me, brief, config.assistant_repo)
    # And today's and tomorrow's calls somebody outside hosts, whose host lets the note-taker in
    # (`rouh/host_admits.py`).
    await host_admits.again(me, brief)
    # And a flight in the next two weeks his main calendar shows him free during (`rouh/flight_open.py`).
    await flight_open.again(me, brief, getattr(runtime, "brief_google", None))
    # And an invitation in his own mail whose meeting is on none of his calendars (`rouh/invite_missing.py`).
    await invite_missing.again(me, brief, getattr(runtime, "brief_google", None))
    # And a meeting of his with guests and nowhere to meet: no place, no call link (`rouh/no_place.py`).
    await no_place.again(me, brief, getattr(runtime, "brief_google", None))
    # And a meeting of his today or tomorrow nobody has accepted, or somebody declined
    # (`rouh/not_said_yes.py`).
    await not_said_yes.again(me, brief, getattr(runtime, "brief_google", None))
    # And an invitation of somebody else's today or tomorrow he never answered
    # (`rouh/not_answered.py`).
    await not_answered.again(me, brief, getattr(runtime, "brief_google", None))
    # And the companies he met regularly who have stopped, with nothing booked (`rouh/gone_quiet.py`).
    await gone_quiet.again(me, brief, getattr(runtime, "brief_google", None))
    return {**brief, "one_thing": await sync_to_async(one_thing.chosen)(me),
            "second_zone": second.key if second else ""}


@only("POST")
async def brief_make(request: HttpRequest):
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("sign in", 401)
    zone = await sync_to_async(_page_zone)(request, me)
    try:
        brief = await _make(me, zone)
    except Exception:
        log.exception("the morning brief could not be made")
        return refuse("The brief could not be made just now. Try again in a moment.", 500)
    settings = await sync_to_async(morning_brief.settings_of)(me)
    return answer({"ok": True, "brief": await _with_one_thing(me, brief), "today": brief["day"],
                   "schedule": {"on": settings["on"], "time": settings["time"]}},
                  headers=NO_STORE)


@only("GET", "POST")
async def brief_one_thing(request: HttpRequest):
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("sign in", 401)
    if request.method == "POST":
        sent = body_of(request)
        try:
            if sent.get("clear") is True:
                await sync_to_async(one_thing.clear)(me)
            else:
                await sync_to_async(one_thing.choose)(me, sent)
        except one_thing.Refused as exc:
            return refuse(str(exc), 400)
        return answer({"ok": True, "one_thing": await sync_to_async(one_thing.chosen)(me)},
                      headers=NO_STORE)
    try:
        offered = await asyncio.to_thread(one_thing.options)
    except Exception:
        log.exception("the one thing's picker could not read the projects")
        offered = {"ok": True, "categories": [], "tasks": [],
                   "note": "Your projects could not be read just now, so type your own."}
    return answer({**offered, "one_thing": await sync_to_async(one_thing.chosen)(me)},
                  headers=NO_STORE)


@only("POST")
async def brief_refactor_undo(request: HttpRequest, number: int):
    """Undo, under last night's refactoring in the Report: a run that reverts exactly the commits
    that night named (`nightly_refactor.undo`). Only the signed-in person's own nights."""
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("sign in", 401)
    from rouh import nightly_refactor

    try:
        said = await nightly_refactor.undo(me, number)
    except nightly_refactor.Refused as exc:
        return refuse(str(exc), 400)
    except Exception:
        log.exception("the refactoring night's undo could not be started")
        return refuse("The undo could not be started just now. Try again in a minute.", 500)
    return answer({"ok": True, "said": said}, headers=NO_STORE)


def _google():
    from rouh import runtime

    return runtime.brief_google


@only("GET")
async def brief_calendar(request: HttpRequest):
    """The calendar alone, read again, which the page asks for every time it opens."""
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("sign in", 401)
    zone = await sync_to_async(_page_zone)(request, me)
    part = await morning_brief.calendar_again(me, google=_google(), zone=zone)
    return answer({"ok": True, "calendar": part, "zone": (zone.key if zone else "")},
                  headers=NO_STORE)


@only("GET")
async def brief_event(request: HttpRequest):
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("sign in", 401)
    zone = await sync_to_async(_page_zone)(request, me)
    try:
        event = await morning_brief.event_whole(
            me, google=_google(), zone=zone, calendar_id=request.GET.get("calendar"),
            event_id=request.GET.get("event"))
    except morning_brief.Refused as exc:
        return refuse(str(exc), 400)
    except Exception as exc:
        log.warning("an event on the brief could not be read: %s", exc)
        return refuse(morning_brief._google_trouble(exc, "event"), 502)
    return answer({"ok": True, "event": event}, headers=NO_STORE)


@only("POST")
async def brief_event_answer(request: HttpRequest):
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("sign in", 401)
    zone = await sync_to_async(_page_zone)(request, me)
    sent = body_of(request)
    try:
        event = await morning_brief.answer_event(
            me, google=_google(), zone=zone, calendar_id=sent.get("calendar"),
            event_id=sent.get("event"), response=str(sent.get("response") or ""))
    except morning_brief.Refused as exc:
        return refuse(str(exc), 400)
    except Exception as exc:
        log.warning("an invitation on the brief could not be answered: %s", exc)
        return refuse(morning_brief._google_trouble(exc, "event"), 502)
    return answer({"ok": True, "event": event}, headers=NO_STORE)


@only("GET")
async def brief_event_prep(request: HttpRequest):
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("sign in", 401)
    zone = await sync_to_async(_page_zone)(request, me)
    try:
        made = await meeting_prep.note_for_event(
            me, google=_google(), zone=zone, calendar_id=request.GET.get("calendar"),
            event_id=request.GET.get("event"))
    except morning_brief.Refused as exc:
        return refuse(str(exc), 400)
    except Exception as exc:
        log.warning("the note before a meeting could not be made: %s", exc)
        return refuse(morning_brief._google_trouble(exc, "event"), 502)
    return answer(made, headers=NO_STORE)


@only("GET")
async def brief_event_raise(request: HttpRequest):
    """What to raise at a meeting today's brief was made without one for.

    The brief makes it for every meeting as it is made and the page draws
    that (fr_5fb00def9d2d); this is for one added to the calendar since, or one
    the model could not be asked about then. Made once, and kept on the
    meeting in today's brief, so the next open is the same and instant.
    """
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("sign in", 401)
    zone = await sync_to_async(_page_zone)(request, me)
    calendar_id = str(request.GET.get("calendar") or "")
    event_id = str(request.GET.get("event") or "")
    day = await sync_to_async(morning_brief.today_of)(me, zone)
    kept = await sync_to_async(morning_brief.raise_kept)(me, day, calendar_id, event_id)
    if kept is not None:
        return answer(kept, headers=NO_STORE)
    try:
        made = await meeting_brief.for_event(
            me, google=_google(), zone=zone, calendar_id=calendar_id, event_id=event_id)
    except morning_brief.Refused as exc:
        return refuse(str(exc), 400)
    except Exception as exc:
        log.warning("what to raise at a meeting could not be made: %s", exc)
        return refuse(morning_brief._google_trouble(exc, "event"), 502)
    if meeting_brief.settled(made):
        await sync_to_async(morning_brief.keep_raise)(me, day, calendar_id, event_id, made)
    return answer(made, headers=NO_STORE)


@only("POST")
async def brief_event_raise_correct(request: HttpRequest):
    """What to raise at a meeting, made again with what he says is wrong in it.

    Fr_792353f69079, 9 October 2026: he describes what is wrong in his own
    words and the reading is made again with it (`meeting_brief.correct`),
    replacing the one kept on the meeting in today's brief. When it cannot be
    made, the kept one stays as it was and the page says why.
    """
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("sign in", 401)
    zone = await sync_to_async(_page_zone)(request, me)
    sent = body_of(request)
    calendar_id = str(sent.get("calendar") or "")
    event_id = str(sent.get("event") or "")
    day = await sync_to_async(morning_brief.today_of)(me, zone)
    before = await sync_to_async(morning_brief.raise_kept)(me, day, calendar_id, event_id)
    if before is None:
        return refuse("Today's brief has no What to raise for that meeting to correct.", 404)
    try:
        made = await meeting_brief.correct_for_event(
            me, google=_google(), zone=zone, calendar_id=calendar_id, event_id=event_id,
            before=before, said=str(sent.get("correction") or ""))
    except (morning_brief.Refused, meeting_brief.NotCorrected) as exc:
        return refuse(str(exc), 400)
    except Exception as exc:
        log.warning("what to raise could not be made again with a correction: %s", exc)
        return refuse(morning_brief._google_trouble(exc, "event"), 502)
    await sync_to_async(morning_brief.replace_raise)(me, day, calendar_id, event_id, before, made)
    return answer(made, headers=NO_STORE)


@only("GET")
async def brief_past(request: HttpRequest):
    """Every brief this person has, newest first, each by its day (fr_5fb00def9d2d)."""
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("sign in", 401)
    zone = await sync_to_async(_page_zone)(request, me)
    today = await sync_to_async(morning_brief.today_of)(me, zone)
    briefs = await sync_to_async(morning_brief.past)(me, today)
    return answer({"ok": True, "today": today, "briefs": briefs}, headers=NO_STORE)


@only("GET")
async def brief_day(request: HttpRequest, day: str):
    """One day's brief exactly as it was kept: nothing in it is read again or made again,
    but for a What to raise that read nothing, which the page asks for (`redo_raise`)."""
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("sign in", 401)
    try:
        brief = await sync_to_async(morning_brief.kept_day)(me, day)
    except morning_brief.Refused as exc:
        return refuse(str(exc), 400)
    if brief is None:
        return refuse("There is no brief kept for that day.", 404)
    morning_brief.drop_stale_raises(brief)
    second = await sync_to_async(location.second_zone)(me)
    return answer({"ok": True, "brief": {**brief, "second_zone": second.key if second else ""}},
                  headers=NO_STORE)


@only("GET")
async def brief_contacts(request: HttpRequest):
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("sign in", 401)
    query = (request.GET.get("q") or "")[:200]
    found = await sync_to_async(birthdays.find_contacts)(me, query)
    connected = await sync_to_async(birthdays._connected)(me)
    return answer({"ok": True, "contacts": found, "connected": connected}, headers=NO_STORE)


@only("POST")
async def brief_birthday_link(request: HttpRequest):
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("sign in", 401)
    zone = await sync_to_async(_page_zone)(request, me)
    sent = body_of(request)
    try:
        if sent.get("unlink") is True:
            await sync_to_async(birthdays.unlink)(
                me, calendar_id=sent.get("calendar"), event_key=sent.get("event"))
        else:
            await sync_to_async(birthdays.link)(
                me, calendar_id=sent.get("calendar"), event_key=sent.get("event"),
                contact_id=sent.get("contact"), title=str(sent.get("title") or ""))
    except birthdays.Refused as exc:
        return refuse(str(exc), 400)
    part = await morning_brief.birthdays_again(me, google=_google(), zone=zone)
    return answer({"ok": True, "birthdays": part}, headers=NO_STORE)


@only("POST")
async def brief_slack_dismiss(request: HttpRequest):
    """The x on a line of Needs you in Slack, and its Undo (fr_6d5b2ccbf194)."""
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("sign in", 401)
    sent = body_of(request)
    key = str(sent.get("key") or "")[:300]
    try:
        at = float(sent.get("at"))
    except (TypeError, ValueError):
        at = 0.0
    if not key or at <= 0:
        return refuse("Which line, and the time of its newest message.", 400)
    await sync_to_async(slack_brief.dismiss)(me, key, at, undo=bool(sent.get("undo")))
    return answer({"ok": True}, headers=NO_STORE)


@only("POST")
async def brief_owed(request: HttpRequest):
    """A line of Owed to you: What was this about, Draft a follow-up, Send it, It came, Dismiss, or
    Undo (`rouh/owed_to_you.py`)."""
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("sign in", 401)
    sent = body_of(request)
    key, act = str(sent.get("key") or "")[:40], str(sent.get("act") or "")
    if not key or act not in ("context", "draft", "send", "came", "dismiss", "undo"):
        return refuse("Which line, and what to do with it.", 400)
    if act in ("context", "draft"):
        try:
            if act == "draft":
                return answer({"ok": True, "text": await sync_to_async(owed_to_you.draft)(me, key)},
                              headers=NO_STORE)
            return answer({"ok": True, **await sync_to_async(owed_to_you.context)(me, key)}, headers=NO_STORE)
        except owed_to_you.Refused as exc:
            return refuse(str(exc), 400)
    if act == "send":
        try:
            done = await owed_to_you.chase(me, _google(), key, str(sent.get("text") or ""))
        except owed_to_you.Refused as exc:
            return refuse(str(exc), 400)
        return answer({"ok": True, **done}, headers=NO_STORE)
    await sync_to_async(owed_to_you.mark)(
        me, key, {"came": "came", "dismiss": "dismissed"}.get(act, ""))
    return answer({"ok": True}, headers=NO_STORE)


@only("POST")
async def brief_no_notes(request: HttpRequest):
    """Meetings with no notes: Not recorded, Undo, or Open the meeting library (`rouh/notes_missing.py`)."""
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("sign in", 401)
    sent = body_of(request)
    key, act = str(sent.get("key") or "")[:40], str(sent.get("act") or "")
    if act not in ("not_recorded", "undo", "library") or (act != "library" and not key):
        return refuse("Which meeting, and what to do with it.", 400)
    if not await sync_to_async(notes_missing.on)(me):
        return refuse("Meetings with no notes is switched off.", 400)
    await sync_to_async(notes_missing.act)(me, key, act)
    return answer({"ok": True}, headers=NO_STORE)


@only("POST")
async def brief_next_meeting(request: HttpRequest):
    """Agreed, not booked: Book it, Not needed, or Undo (`rouh/next_meeting.py`)."""
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("sign in", 401)
    sent = body_of(request)
    key, act = str(sent.get("key") or "")[:40], str(sent.get("act") or "")
    if act not in ("book", "not_needed", "undo") or not key:
        return refuse("Which meeting, and what to do with it.", 400)
    if not await sync_to_async(next_meeting.on)(me):
        return refuse("Agreed, not booked is switched off.", 400)
    if act == "book":
        try:
            done = await next_meeting.book(me, _google(), key)
        except next_meeting.Refused as exc:
            return refuse(str(exc), 400)
        return answer({"ok": True, **done}, headers=NO_STORE)
    await sync_to_async(next_meeting.mark)(me, key, "not_needed" if act == "not_needed" else "")
    return answer({"ok": True}, headers=NO_STORE)


@only("POST")
async def brief_others_changed(request: HttpRequest):
    """Changed by others: Open the page, Seen, or Undo (`rouh/others_changed.py`)."""
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("sign in", 401)
    sent = body_of(request)
    key, act = str(sent.get("key") or "")[:400], str(sent.get("act") or "")
    try:
        newest = int(sent.get("newest") or 0)
    except (TypeError, ValueError):
        newest = 0
    if act not in ("open", "seen", "undo") or not key:
        return refuse("Which page, and what to do with it.", 400)
    if not await sync_to_async(others_changed.on)(me):
        return refuse("Changed by others is switched off.", 400)
    await sync_to_async(others_changed.act)(me, key, act, newest)
    return answer({"ok": True}, headers=NO_STORE)


@only("POST")
async def brief_shared_with_you(request: HttpRequest):
    """Shared with you: Add to a task, Open, Got it, or Undo (`rouh/shared_with_you.py`)."""
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("sign in", 401)
    sent = body_of(request)
    key, act = str(sent.get("key") or "")[:200], str(sent.get("act") or "")
    task = str(sent.get("task") or "")[:400]
    if act not in ("add", "open", "seen", "undo") or not key:
        return refuse("Which document, and what to do with it.", 400)
    if not await sync_to_async(shared_with_you.on)(me):
        return refuse("Shared with you is switched off.", 400)
    from rouh.config import config

    try:
        done = await shared_with_you.act(me, config.assistant_repo, key, act, task)
    except shared_with_you.Refused as exc:
        return refuse(str(exc), 400)
    return answer(done, headers=NO_STORE)


@only("POST")
async def brief_not_opened(request: HttpRequest):
    """Not opened yet: Write to them, Open, Let it be, or Undo (`rouh/not_opened.py`)."""
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("sign in", 401)
    sent = body_of(request)
    key, act = str(sent.get("key") or "")[:80], str(sent.get("act") or "")
    if act not in ("write", "opened", "seen", "undo") or not key:
        return refuse("Which page, and what to do with it.", 400)
    if not await sync_to_async(not_opened.on)(me):
        return refuse("Not opened yet is switched off.", 400)
    try:
        done = await sync_to_async(not_opened.act)(me, key, act)
    except not_opened.Refused as exc:
        return refuse(str(exc), 400)
    return answer(done, headers=NO_STORE)


@only("POST")
async def brief_new_comments(request: HttpRequest):
    """New comments on your documents: Open, Open the task, Let it be, or Undo
    (`rouh/new_comments.py`)."""
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("sign in", 401)
    sent = body_of(request)
    key, act = str(sent.get("key") or "")[:200], str(sent.get("act") or "")
    if act not in ("opened", "task", "seen", "undo") or not key:
        return refuse("Which comment, and what to do with it.", 400)
    if not await sync_to_async(new_comments.on)(me):
        return refuse("New comments on your documents is switched off.", 400)
    try:
        done = await sync_to_async(new_comments.act)(me, key, act)
    except new_comments.Refused as exc:
        return refuse(str(exc), 400)
    return answer(done, headers=NO_STORE)


@only("POST")
async def brief_talk_deck(request: HttpRequest):
    """The deck for your talk: Open the deck, a slide or a comment, Let it be, or Undo
    (`rouh/talk_deck.py`)."""
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("sign in", 401)
    sent = body_of(request)
    key, act = str(sent.get("key") or "")[:300], str(sent.get("act") or "")
    if act not in ("opened", "slide", "comment", "seen", "undo") or not key:
        return refuse("Which deck, and what to do with it.", 400)
    if not await sync_to_async(talk_deck.on)(me):
        return refuse("The deck for your talk is switched off.", 400)
    try:
        done = await sync_to_async(talk_deck.act)(me, key, act)
    except talk_deck.Refused as exc:
        return refuse(str(exc), 400)
    return answer(done, headers=NO_STORE)


@only("POST")
async def brief_not_handed(request: HttpRequest):
    """Made, not handed over: Open the task, Handed over, or Undo (`rouh/not_handed.py`)."""
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("sign in", 401)
    sent = body_of(request)
    key, act = str(sent.get("key") or "")[:400], str(sent.get("act") or "")
    if act not in ("task", "handed", "undo") or not key:
        return refuse("Which line, and what to do with it.", 400)
    if not await sync_to_async(not_handed.on)(me):
        return refuse("Made, not handed over is switched off.", 400)
    try:
        done = await sync_to_async(not_handed.act)(me, key, act)
    except not_handed.Refused as exc:
        return refuse(str(exc), 400)
    return answer(done, headers=NO_STORE)


@only("POST")
async def brief_my_word(request: HttpRequest):
    """Your word, by mail: Open the email, What you wrote, Done, or Undo (`rouh/my_word.py`)."""
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("sign in", 401)
    sent = body_of(request)
    key, act = str(sent.get("key") or "")[:100], str(sent.get("act") or "")
    if act not in my_word.ACTS or not key:
        return refuse("Which line, and what to do with it.", 400)
    if not await sync_to_async(my_word.on)(me):
        return refuse("Your word, by mail, is switched off.", 400)
    try:
        done = await sync_to_async(my_word.act)(me, key, act)
    except my_word.Refused as exc:
        return refuse(str(exc), 400)
    return answer(done, headers=NO_STORE)


@only("POST")
async def brief_answer_waiting(request: HttpRequest):
    """Waiting on your answer: Open the email, Not needed, or Undo (`rouh/answer_waiting.py`)."""
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("sign in", 401)
    sent = body_of(request)
    key, act = str(sent.get("key") or "")[:100], str(sent.get("act") or "")
    if act not in answer_waiting.ACTS or not key:
        return refuse("Which line, and what to do with it.", 400)
    if not await sync_to_async(answer_waiting.on)(me):
        return refuse("Waiting on your answer, in the brief, is switched off.", 400)
    try:
        done = await sync_to_async(answer_waiting.act)(me, key, act)
    except answer_waiting.Refused as exc:
        return refuse(str(exc), 400)
    return answer(done, headers=NO_STORE)


@only("POST")
async def brief_task_dates(request: HttpRequest):
    """Dates your tasks wait on: Open the task, What it says, Done, or Undo (`rouh/task_dates.py`)."""
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("sign in", 401)
    sent = body_of(request)
    key, act = str(sent.get("key") or "")[:400], str(sent.get("act") or "")
    if act not in ("task", "context", "done", "undo") or not key:
        return refuse("Which line, and what to do with it.", 400)
    if not await sync_to_async(task_dates.on)(me):
        return refuse("Dates your tasks wait on is switched off.", 400)
    try:
        done = await sync_to_async(task_dates.act)(me, key, act)
    except task_dates.Refused as exc:
        return refuse(str(exc), 400)
    return answer(done, headers=NO_STORE)


@only("POST")
async def brief_raise_attached(request: HttpRequest):
    """What to raise reads what is attached: the list of the documents it read opened, or one of
    them (`rouh/raise_attached.py`), reported as the gene's use."""
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("sign in", 401)
    sent = body_of(request)
    act = str(sent.get("act") or "")
    if act not in ("opened", "doc"):
        return refuse("Which press.", 400)
    if not await sync_to_async(raise_attached.on)(me):
        return refuse("What to raise reads what is attached is switched off.", 400)
    from rouh import evolution

    what = str(sent.get("what") or "")[:120]
    if act == "opened":
        await sync_to_async(evolution.used)("raise_attached", "opened", who=me, detail=what)
    else:
        await sync_to_async(evolution.used)("raise_attached", "doc", who=me, detail=what)
    return answer({"ok": True}, headers=NO_STORE)


@only("POST")
async def brief_host_admits(request: HttpRequest):
    """Who lets the note-taker in: Ask the host, No notes needed, Undo, or Who is in it (`rouh/host_admits.py`)."""
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("sign in", 401)
    sent = body_of(request)
    key, act = str(sent.get("key") or "")[:40], str(sent.get("act") or "")
    if act not in host_admits.ACTS or not key:
        return refuse("Which meeting, and what to do with it.", 400)
    if not await sync_to_async(host_admits.on)(me):
        return refuse("Who lets the note-taker in is switched off.", 400)
    await sync_to_async(host_admits.act)(me, key, act)
    return answer({"ok": True}, headers=NO_STORE)


@only("POST")
async def brief_flight_open(request: HttpRequest):
    """Flights left open: Block it as out of office, Not needed, or Undo (`rouh/flight_open.py`)."""
    from rouh import runtime

    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("sign in", 401)
    sent = body_of(request)
    key, act = str(sent.get("key") or "")[:40], str(sent.get("act") or "")
    if act not in flight_open.ACTS or not key:
        return refuse("Which flight, and what to do with it.", 400)
    if not await sync_to_async(flight_open.on)(me):
        return refuse("Flights left open is switched off.", 400)
    try:
        done = await flight_open.act(me, getattr(runtime, "brief_google", None), key, act,
                                     calendar_id=str(sent.get("calendar_id") or "")[:300],
                                     event_id=str(sent.get("event_id") or "")[:300])
    except flight_open.Refused as exc:
        return refuse(str(exc), 400)
    except Exception as exc:  # noqa: BLE001 - said, and nothing kept
        log.warning("a flight could not be blocked: %r", exc)
        return refuse("Google would not put the block on the calendar: " + str(exc)[:200], 502)
    return answer(done, headers=NO_STORE)


@only("POST")
async def brief_invite_missing(request: HttpRequest):
    """Invitations not in your calendar: Put it in my calendar, Not needed, or Undo
    (`rouh/invite_missing.py`)."""
    from rouh import runtime

    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("sign in", 401)
    sent = body_of(request)
    key, act = str(sent.get("key") or "")[:40], str(sent.get("act") or "")
    if act not in invite_missing.ACTS or not key:
        return refuse("Which invitation, and what to do with it.", 400)
    if not await sync_to_async(invite_missing.on)(me):
        return refuse("Invitations not in your calendar is switched off.", 400)
    try:
        done = await invite_missing.act(me, getattr(runtime, "brief_google", None), key, act)
    except invite_missing.Refused as exc:
        return refuse(str(exc), 400)
    except Exception as exc:  # noqa: BLE001 - said, and nothing kept
        log.warning("an invitation could not be put in the calendar: %r", exc)
        return refuse("Google would not put it on the calendar: " + str(exc)[:200], 502)
    return answer(done, headers=NO_STORE)


@only("POST")
async def brief_no_place(request: HttpRequest):
    """Meetings with nowhere to meet: Add a Meet link, Not needed, or Undo (`rouh/no_place.py`)."""
    from rouh import runtime

    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("sign in", 401)
    sent = body_of(request)
    key, act = str(sent.get("key") or "")[:40], str(sent.get("act") or "")
    if act not in no_place.ACTS or not key:
        return refuse("Which meeting, and what to do with it.", 400)
    if not await sync_to_async(no_place.on)(me):
        return refuse("Meetings with nowhere to meet is switched off.", 400)
    try:
        done = await no_place.act(me, getattr(runtime, "brief_google", None), key, act,
                                  calendar_id=str(sent.get("calendar_id") or "")[:300],
                                  event_id=str(sent.get("event_id") or "")[:300])
    except no_place.Refused as exc:
        return refuse(str(exc), 400)
    except Exception as exc:  # noqa: BLE001 - said, and nothing kept
        log.warning("a Meet link could not be added: %r", exc)
        return refuse("Google would not add a Meet link: " + str(exc)[:200], 502)
    return answer(done, headers=NO_STORE)


@only("POST")
async def brief_gone_quiet(request: HttpRequest):
    """Gone quiet: Not now, Undo, or Write to them pressed (`rouh/gone_quiet.py`)."""
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("sign in", 401)
    sent = body_of(request)
    key, act = str(sent.get("key") or "")[:120], str(sent.get("act") or "")
    if act not in gone_quiet.ACTS or not key:
        return refuse("Which line, and what to do with it.", 400)
    if not await sync_to_async(gone_quiet.on)(me):
        return refuse("Gone quiet is switched off.", 400)
    try:
        done = await sync_to_async(gone_quiet.act)(me, key, act)
    except gone_quiet.Refused as exc:
        return refuse(str(exc), 400)
    return answer(done, headers=NO_STORE)


@only("POST")
async def brief_not_answered(request: HttpRequest):
    """Invitations you have not answered: Yes, Maybe, No, Not now or Undo (`rouh/not_answered.py`)."""
    from rouh import runtime

    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("sign in", 401)
    sent = body_of(request)
    key, act = str(sent.get("key") or "")[:40], str(sent.get("act") or "")
    if act not in not_answered.ACTS or not key:
        return refuse("Which invitation, and what to do with it.", 400)
    if not await sync_to_async(not_answered.on)(me):
        return refuse("Invitations you have not answered is switched off.", 400)
    try:
        done = await not_answered.act(me, getattr(runtime, "brief_google", None), key, act,
                                      calendar_id=str(sent.get("calendar_id") or "")[:300],
                                      event_id=str(sent.get("event_id") or "")[:300])
    except not_answered.Refused as exc:
        return refuse(str(exc), 400)
    except Exception as exc:  # noqa: BLE001 - said, and nothing kept
        log.warning("an invitation could not be answered: %r", exc)
        return refuse("Google would not take the answer: " + str(exc)[:200], 502)
    return answer(done, headers=NO_STORE)


@only("POST")
async def brief_not_said_yes(request: HttpRequest):
    """Guests who have not said yes: Not needed, Undo, or Write to them pressed
    (`rouh/not_said_yes.py`)."""
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("sign in", 401)
    sent = body_of(request)
    key, act = str(sent.get("key") or "")[:40], str(sent.get("act") or "")
    if act not in not_said_yes.ACTS or not key:
        return refuse("Which meeting, and what to do with it.", 400)
    if not await sync_to_async(not_said_yes.on)(me):
        return refuse("Guests who have not said yes is switched off.", 400)
    return answer(await sync_to_async(not_said_yes.act)(me, key, act), headers=NO_STORE)


@only("GET", "POST")
async def brief_history_topics(request: HttpRequest):
    """The topics Today in history is picked for, from the gear on its heading (fr_a1b47c17f8cf)."""
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("sign in", 401)
    if request.method == "POST":
        sent = body_of(request)
        try:
            kept = await morning_brief.save_topics(me, sent, day=str(sent.get("day") or "")[:10])
        except morning_brief.Refused as exc:
            return refuse(str(exc), 400)
    else:
        kept = await sync_to_async(morning_brief.settings_of)(me)
    return answer({"ok": True, "topics": kept["topics"], "custom": kept["custom"],
                   "history": kept.get("history"),
                   "choices": [{"id": one["id"], "name": one["name"]}
                               for one in morning_brief.HISTORY_TOPICS],
                   "examples": morning_brief.CUSTOM_EXAMPLES,
                   "most_custom": morning_brief.MOST_CUSTOM}, headers=NO_STORE)


@only("GET", "POST")
async def settings_brief(request: HttpRequest):
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("sign in", 401)
    if request.method == "POST":
        try:
            kept = await morning_brief.save_settings(me, body_of(request))
        except morning_brief.Refused as exc:
            return refuse(str(exc), 400)
    else:
        kept = await sync_to_async(morning_brief.settings_of)(me)
    return answer({"ok": True, "on": kept["on"], "time": kept["time"], "place": kept["place"],
                   "channels": morning_brief.channel_lines(kept["channels"]),
                   "channel_names": [one["name"] for one in kept["channels"]],
                   "telegram": await sync_to_async(_telegram)(),
                   "phone_is_mine": await sync_to_async(_phone_is_mine)(me)},
                  headers=NO_STORE)
