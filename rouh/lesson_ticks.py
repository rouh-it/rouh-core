"""Lessons ticked as you do them: the Guide sees the lessons you have already done in a chat.

Built by the nightly feature run, night 50 of the ledger (21 November 2026, task 94), for the
person's guidance that half of what is built makes Rouh easier for somebody using it for the
first time, technical or not.

The Guide (`rouh/handholding.py`) ticks a lesson by itself only where the database shows it
done: a connection, a task, a reminder, a rule. Most of its lessons are done by asking Rouh in
words ("go through my inbox", "what is on my calendar", "look this up"), and those stayed open
until the person found the lesson and ticked it by hand. Somebody new who already did half the
path by talking was told they had done none of it, and sent to do it again.

So, while its switch is on, a lesson in `TOOLS` counts as done, marked Detected with the words
"Rouh saw you do it in a chat", once Rouh's model has called one of its tools for this person:
read from the event log's daily counts (`analytics.object_daily`, `tool.called`, which
`brain.py` writes for every call), by `org_id` and `user_id`. One query, no model, nothing
written. Opening the Guide with such a lesson ticked is its use.

**Its switch** is `lesson_ticks` (`rouh/switches.py`): off, those lessons wait for a tick by hand
as before.
"""
from __future__ import annotations

import logging

log = logging.getLogger("rouh.lesson_ticks")

SWITCH = "lesson_ticks"
TITLE = "Lessons ticked as you do them: the Guide sees what you already did in a chat"
WHY = "Rouh saw you do it in a chat."

#: Handholding's lesson id, and the tools whose call shows it done (`rouh/handholding.json`).
TOOLS: dict[str, tuple[str, ...]] = {
    "inbox": ("show_inbox", "read_recent_mail"),
    "reply": ("send_mail", "draft_mail"),
    "calendar": ("list_calendar_events", "create_calendar_event", "upcoming"),
    "contacts": ("search_contacts", "show_contact"),
    "lookup": ("web_search", "web_fetch"),
    "browser": ("browser",),
    "share": ("publish_task", "share_with_person"),
    "running": ("what_is_running", "job_status", "one_runs"),
    "quest": ("quest",),
    "models": ("model_defaults",),
    "gene-therapy": ("improve_myself",),
    "incubator": ("incubator_add",),
    "drive-open": ("open_files",),
    "heartbeat": ("heartbeat",),
}


def on(who) -> bool:
    from . import switches

    if who is None:
        return False
    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def done(who) -> dict:
    """{lesson id: WHY} for every lesson in `TOOLS` this person has done by asking Rouh."""
    if who is None or not on(who):
        return {}
    from django.db import connection

    from . import events

    names = sorted({t for tools in TOOLS.values() for t in tools})
    try:
        events.rollup()
    except Exception:  # noqa: BLE001 - what is rolled up already still counts
        log.warning("lesson_ticks: the event rollups could not be brought up to date", exc_info=True)
    with connection.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT object_id FROM analytics.object_daily "
            "WHERE org_id = %s AND user_id = %s AND name = 'tool.called' "
            "AND object_type = 'tool' AND object_id = ANY(%s)",
            [str(who.org_id or ""), str(who.user_id), names])
        used = {r[0] for r in cur.fetchall()}
    return {lesson: WHY for lesson, tools in TOOLS.items() if used.intersection(tools)}


def seen(who, ticked: dict) -> None:
    """The Guide was opened with a lesson this gene ticked: its use."""
    from . import evolution

    mine = sorted(k for k, v in (ticked or {}).items() if v == WHY)
    if mine:
        evolution.used("lesson_ticks", "seen", who=who, detail=", ".join(mine)[:60])
