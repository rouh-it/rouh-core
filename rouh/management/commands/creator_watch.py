"""``python manage.py creator_watch``: a day of Rouh against the same day a week before (task 161).

The Creator Rouh's week of watching after its move into the containers (plan step 6): each
evening the day is counted - runs finished, mail answered, reminders fired, night jobs landed -
and kept in ``<data>/creator-watch/history.json``, which moves with the data directory, so days
counted before the move compare with days after it. The seven days ending that evening are
compared with the seven before them, because one day alone swings too much: a sum that fell to
less than half, where the week before had at least ``FLOOR`` of it, is a regression; the day's
verdict is kept beside its counts, and the exit code is 3 when there is one, so the removal of the
old way (remove_old.sh, in rouh-it-site ops/creator since 7 November 2026) reads it and does not go on.

    python manage.py creator_watch            # yesterday, if not counted yet, and today so far
    python manage.py creator_watch --day 2026-11-03
    python manage.py creator_watch --show     # the history, as JSON

Reminders keep only how often each has fired (``fired``), so a day's firings are the change in
their sum since the evening before; the first evening has none to compare.
"""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo

from django.core.management.base import BaseCommand
from django.db import connection

ZONE = ZoneInfo("Europe/Sofia")
#: The least the seven days before must have had of a thing for a fall in it to count.
FLOOR = {"runs_finished": 20, "mail_answered": 5, "reminders_fired": 10, "night_jobs_landed": 3}
#: How many of each seven days must have been counted for the two weeks to be compared.
ENOUGH = 4


def _home() -> Path:
    from rouh.config import config

    data = Path(getattr(config, "data_dir", "") or os.environ.get("ROUH_DATA_DIR") or "/data")
    return data / "creator-watch"


def _one(sql: str, *args) -> int:
    with connection.cursor() as c:
        c.execute(sql, args)
        row = c.fetchone()
    return int(row[0] or 0) if row else 0


def count(day: dt.date) -> dict:
    a = dt.datetime.combine(day, dt.time(), ZONE).timestamp()
    b = a + 86400
    return {
        "runs_finished": _one("SELECT count(*) FROM run WHERE ended_at >= %s AND ended_at < %s", a, b),
        "mail_answered": _one("SELECT count(*) FROM mail_cases WHERE replied_at >= %s AND replied_at < %s", a, b),
        "night_jobs_landed": _one(
            "SELECT (SELECT count(*) FROM nightly_feature_nights WHERE started_at >= %s AND started_at < %s "
            "AND state = 'ended' AND built <> '') + (SELECT count(*) FROM nightly_refactor_nights "
            "WHERE started_at >= %s AND started_at < %s AND outcome = 'refactored')", a, b, a, b),
    }


def week(days: dict, end: dt.date) -> dict:
    """The seven days ending on `end`: each count's sum, and how many days were counted."""
    out, n = {}, 0
    for i in range(7):
        got = days.get((end - dt.timedelta(days=i)).isoformat())
        if not got:
            continue
        n += 1
        for k in FLOOR:
            if got.get(k) is not None:
                out[k] = out.get(k, 0) + got[k]
    out["days"] = n
    return out


def verdict(days: dict, day: dt.date) -> list[str]:
    """What fell below half of the seven days before, over the seven days ending on `day`: one day
    alone swings too much (mail answered goes from 0 to 13) to be compared with one day."""
    now, before = week(days, day), week(days, day - dt.timedelta(days=7))
    if now["days"] < ENOUGH or before["days"] < ENOUGH:
        return []
    out = []
    for k, floor in FLOOR.items():
        was, got = before.get(k), now.get(k)
        if was is None or got is None:
            continue
        if was >= floor and got < was / 2:
            out.append(f"{k.replace('_', ' ')}: {got} in the last seven days, against {was} in the seven before")
    return out


class Command(BaseCommand):
    help = "A day of Rouh against the same day a week before (task 161)."

    def add_arguments(self, p):
        p.add_argument("--day", default="")
        p.add_argument("--show", action="store_true")

    def handle(self, *a, **o):
        home = _home()
        home.mkdir(parents=True, exist_ok=True)
        f = home / "history.json"
        hist = json.loads(f.read_text()) if f.exists() else {"days": {}, "fired": []}
        if o["show"]:
            self.stdout.write(json.dumps(hist, indent=1))
            return
        now = dt.datetime.now(ZONE)
        day = dt.date.fromisoformat(o["day"]) if o["day"] else now.date()
        got = count(day)
        # Reminders: the change in how often they have fired since the last evening counted.
        fired = _one("SELECT coalesce(sum(fired), 0) FROM reminders")
        last = hist["fired"][-1] if hist["fired"] else None
        if not o["day"]:
            if last and last["day"] != day.isoformat():
                got["reminders_fired"] = max(0, fired - last["sum"])
            hist["fired"] = [x for x in hist["fired"] if x["day"] != day.isoformat()][-30:] + [
                {"day": day.isoformat(), "sum": fired, "at": now.isoformat(timespec="minutes")}]
        hist["days"][day.isoformat()] = {**got, "counted_at": now.isoformat(timespec="minutes")}
        bad = verdict(hist["days"], day)
        hist["days"][day.isoformat()]["regressed"] = bad
        compared = week(hist["days"], day - dt.timedelta(days=7))["days"] >= ENOUGH
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(hist, indent=1))
        tmp.replace(f)
        words = ", ".join(f"{k.replace('_', ' ')} {v}" for k, v in got.items())
        self.stdout.write(f"{day}: {words}" + (f"; REGRESSED - {'; '.join(bad)}" if bad
                                               else ("; the last seven days no worse than the seven before" if compared
                                                     else "; not enough days yet to compare two weeks")))
        if bad:
            raise SystemExit(3)
