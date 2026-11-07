"""The nightly feature run's own page in Evolution, at /evolution/nightly (`rouh/nightly_feature.py`).

    GET  /api/evolution/nightly        its schedule and switch, its nights and what each did, its settings
    POST /api/evolution/nightly        {"on": bool} switches it on or off; {"at": "HH:MM"} moves its time;
                                       {"start": true} starts tonight's night now

Petar, 3 November 2026: the nightly run was a row on Clockwork, a reminder of Rouh's own; it is a
feature of its own now, beside the Incubator, which is where its ideas are read from and written to.
Its schedule is still kept in that same row (`nightly_feature.ensure`), so its time, its pauses and
its history carry over and the scheduler that has started every night so far starts every night now;
the row is shown here, and no longer on Clockwork (`rouh/web/clock.py`). Its caps and its rules are
the run's own constants and its lessons the task's `feedback.md`, read and never written here.
"""
from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path

from django.http import HttpRequest

from .common import answer, body_of, refuse, who

log = logging.getLogger(__name__)
NO_STORE = {"Cache-Control": "no-store"}


def _night(n) -> dict:
    from rouh import nightly_feature

    return {"number": n.number, "state": n.state, "why": n.why, "run_id": n.run_id,
            "run_state": nightly_feature.run_state(n.run_id) if n.state == "running" else "",
            "started_at": n.started_at, "feature": n.feature, "built": n.built, "report": n.report,
            "verdict": n.verdict, "words": n.words, "target": getattr(n, "target", None) or {}}


def _read(me) -> dict:
    """Everything the page shows, with its times on the person's own clock (`clock.person`)."""
    from rouh import clock

    with clock.person(me):
        return _read_now(me)


def _read_now(me) -> dict:
    from rouh import incubator, nightly_feature, nightly_ideas, reminders
    from rouh.config import config
    from rouh.models import NightlyFeatureNight

    row = nightly_feature.ensure(me)
    folder = nightly_feature.task_folder()
    lessons, lessons_path = "", ""
    if folder and config.assistant_repo:
        path = Path(config.assistant_repo) / folder / "feedback.md"
        if path.is_file():
            lessons, lessons_path = path.read_text(encoding="utf-8", errors="replace"), f"{folder}/feedback.md"
    nights = list(NightlyFeatureNight.objects.filter(org_id=str(me.org_id), user_id=str(me.user_id))
                  .order_by("-number")[:60])
    from_nightly = incubator.listing(me, source="nightly")
    return {
        "ok": True,
        "schedule": reminders.view(row) if row is not None else None,
        "task": folder,
        "caps": {"dollars": int(nightly_feature.NIGHT_CAP), "services": nightly_feature.MOST_SERVICES,
                 "hours": nightly_feature.NIGHT_HOURS, "at": nightly_feature.AT},
        "lessons": lessons, "lessons_path": lessons_path,
        "lesson_count": len(re.findall(r"^#{2,4} ", lessons, re.M)),
        "nights": [_night(n) for n in nights],
        "ideas": {"all": len(from_nightly),
                  "new": sum(1 for v in from_nightly if v["status"] == "new"),
                  "built": sum(1 for v in from_nightly if v["status"] == "built"),
                  # What tonight may pick, by the rule the night is held to (`nightly_ideas`).
                  "pickable": len(nightly_ideas.pickable(me)), "rule": nightly_ideas.RULE},
    }


async def page(request: HttpRequest):
    from rouh import nightly_feature, reminders

    me = await asyncio.to_thread(who, request)
    if me is None:
        return refuse("Sign in first.", 401)
    if request.method == "POST":
        b = body_of(request)
        row = await asyncio.to_thread(nightly_feature.ensure, me)
        if row is None:
            return refuse("The nightly run has no task in this workspace, so there is nothing to schedule.", 400)
        try:
            if "on" in b:
                from rouh import clock

                def switch():
                    with clock.person(me):
                        return reminders.change(me, row.id, state="on" if b.get("on") else "paused")

                await asyncio.to_thread(switch)
            if b.get("at"):
                at = str(b["at"]).strip()
                if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", at):
                    return refuse("A time is HH:MM, such as 04:30.", 400)
                from rouh import clock

                def move():
                    with clock.person(me):
                        return reminders.change(me, row.id, first=reminders.moment_of(at))

                await asyncio.to_thread(move)
            if b.get("start"):
                said = await nightly_feature.start(me, trying=True)
                got = await asyncio.to_thread(_read, me)
                return answer({**got, "said": said}, headers=NO_STORE)
        except ValueError as exc:
            return refuse(str(exc), 400)
    elif request.method != "GET":
        return refuse("GET or POST.", 405)
    return answer(await asyncio.to_thread(_read, me), headers=NO_STORE)
