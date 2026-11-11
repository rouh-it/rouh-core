"""Whether each of Rouh's own scheduled jobs really ran last night, and really worked.

Petar, 5 November 2026, after the move to containers: "I keep discovering more and more issues
since we moved to containers." From 1 to 5 November every nightly Synapse attempt (#47 to #51)
ended with nothing done, because its worker could not reach the database from the worker
container, and every nightly refactoring run (nights 17 to 21) was stopped a minute after it
started, because Codex was not signed in there. Each of them was still "scheduled", and the run
list said each one had ended; nothing said that none of them had worked. So this looks, every
morning, at what each job left behind, not at whether it is on Clockwork:

- **Clockwork's own row** for each of Rouh's server jobs (`reminders.SERVER`): it must have been
  started at its last due time, and what it said then (`last_said`) must not be that it could not
  start.
- **The job's own record**, where it keeps one: the Synapse attempt (`improvements.latest`), the
  refactoring night (`nightly_refactor.latest`), the feature run's night (its Clockwork line).
- **The backups**: a nightly copy of the database from the last day, and an off-site copy sent in
  the last eight days, where one is set up (`rouh/offsite.py`).
- **Rouh's shared rules** (task 140, step 140-17): the daily fetch of https://rouh.land/rules/defaults.json
  (`rouh/ruledefaults.py`) must have worked in the last two days. From 30 October to 11 November 2026 it
  answered 404 and nothing said so, and every Rouh born then started without the rules that send work to a job.

`check(who)` says it all, one entry a job, and `human` is it in a sentence or two. The core runs
it every half hour (`runtime._job_watch_loop`), keeps the newest answer in the data directory for
server_health, and in the morning on the owner's clock says the failures as one notice that goes on
to the phone (`alarm_due`): the morning after a job starts failing, and the same failures again only a
week on. A morning where everything ran says nothing, and a job held back on purpose (the Synapse night
waiting on Decision 422) is said on server_health and never alarmed about.

    python manage.py job_watch          the same, in words, from a shell in the core
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import time
from typing import Any

log = logging.getLogger("rouh.job_watch")

#: How late a daily job may be started before it counts as not having run.
GRACE_S = 45 * 60
#: A nightly copy of the database older than this is not last night's.
NIGHTLY_HOURS = 30
#: An off-site copy older than this means a weekly one was missed.
OFFSITE_DAYS = 8
#: The morning hour, on the owner's clock, at which failures are said.
ALARM_HOUR = 7
#: What a Clockwork line says when its job did not start (`timekeeper._server_job_line`).
NOT_STARTED = ("could not", "not started", "tried now, could not", "tried now, not started")
#: Words in a job's own line that mean it ran and failed.
FAILED_WORDS = ("could not", "failed", "short because", "without saying what it did", "not started")


def _plain(text: str) -> str:
    """One line: a traceback's last line, never its frames."""
    text = str(text or "")
    if "Traceback" in text or "\n  File " in text:
        last = [ln.strip() for ln in text.splitlines() if ln.strip()]
        head = text.split(":", 1)[0] if ":" in text.splitlines()[0] else ""
        text = (head + ": " if head and head not in last[-1] else "") + (last[-1] if last else "")
    return " ".join(text.split())


def _entry(job: str, title: str, ok: bool | None, why: str = "", *, last_at: float | None = None,
           said: str = "") -> dict:
    why, said = _plain(why), _plain(said)
    return {"job": job, "title": title, "ok": ok, "why": why[:500], "said": said[:400],
            "last_at": _stamp(last_at) if last_at else ""}


def _stamp(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _previous_due(row, now: float) -> float | None:
    """When a repeating row was last due, from its next time: a day (or a week) before it."""
    nxt = getattr(row, "next_at", None)
    if not nxt:
        return None
    step = {"daily": 86400, "weekdays": 86400, "weekly": 7 * 86400}.get(str(row.repeat or ""), 0)
    if not step:
        return None
    due = float(nxt) - step
    while due > now:
        due -= step
    return due


def _clockwork(row, now: float) -> dict:
    """One server job's Clockwork row: did it start at its last time, and what did it say."""
    title = str(row.title or row.job or "a job")
    said = str(row.last_said or "")
    if str(row.state or "on") != "on":
        return _entry(row.job, title, None, "paused on Clockwork", last_at=row.last_at, said=said)
    due = _previous_due(row, now)
    if due is not None and due > float(row.created_at or 0) + 60:
        if not row.last_at or float(row.last_at) < due - GRACE_S:
            return _entry(row.job, title, False,
                          f"it was due {_stamp(due)} and did not start"
                          + (f"; the last time it started was {_stamp(float(row.last_at))}" if row.last_at else ""),
                          last_at=row.last_at, said=said)
    if said.lower().startswith(NOT_STARTED):
        return _entry(row.job, title, False, said, last_at=row.last_at, said=said)
    if not row.last_at:
        return _entry(row.job, title, None, "it has not had its first night yet", said=said)
    return _entry(row.job, title, True, "", last_at=row.last_at, said=said)


def _synapse(who, entry: dict) -> dict:
    from .synapse.lab import improvements, nightly

    # A night whose worker has ended is closed first, with its reason, as the morning brief and the next
    # night do (`improvements.settle`): until then it reads as still running, and so as fine.
    improvements.settle(str(who.org_id), str(who.user_id), run_state=nightly.run_state)
    got = improvements.latest(str(who.org_id), str(who.user_id))
    if not got:
        return entry
    if got.get("outcome") == "failed":
        why = str(got.get("conclusion") or got.get("report") or "no reason was written on it")

        if why.startswith(nightly.IN_CONTAINERS[:60]):
            # Held back on purpose until the owner answers Decision 422: said, never alarmed about.
            return {**entry, "ok": None, "why": f"attempt {got.get('number')} held back: {why}"[:500]}
        return {**entry, "ok": False, "why": f"attempt {got.get('number')} failed: {why}"[:500]}
    if got.get("outcome") in ("", None, "running"):
        return entry
    return {**entry, "why": f"attempt {got.get('number')}: {got.get('outcome')}"}


def _refactor(who, entry: dict) -> dict:
    from . import nightly_refactor

    nightly_refactor.settle(who)
    row = nightly_refactor.latest(who)
    if row is None:
        return entry
    line = nightly_refactor.line_of(row)
    ended = str(row.state or "") == "ended" or (
        bool(row.run_id) and nightly_refactor.run_state(row.run_id) in nightly_refactor.ENDED)
    if not row.outcome and ended:
        # How its run ended, with the run's own reason (`nightly_refactor.settle`, `run_ended`).
        return {**entry, "ok": False, "why": line}
    if row.outcome == "failed":
        return {**entry, "ok": False, "why": line}
    return {**entry, "why": line} if entry["ok"] else entry


def _said_failed(entry: dict) -> dict:
    """A job whose own Clockwork line says it ran and failed."""
    if entry["ok"] and any(w in entry["said"].lower() for w in FAILED_WORDS):
        return {**entry, "ok": False, "why": entry["said"]}
    return entry


#: The job's own record, read after its Clockwork row, where it keeps one.
OWN_RECORD = {"synapse_nightly": _synapse, "nightly_refactor": _refactor}


def _backups(now: float) -> list[dict]:
    from . import offsite

    out = []
    n = offsite.nightly()
    if n.get("on"):
        fresh = bool(offsite.newest_nightly(NIGHTLY_HOURS))
        out.append(_entry("backup.nightly", "Nightly copy of the database", fresh,
                          "" if fresh else n.get("human", "no nightly copy from the last day"), said=n.get("human", "")))
    if offsite.set_up():
        last = offsite.status()
        good = (last.get("last_good") or {}).get("ts") or 0
        ok = bool(good) and now - float(good) < OFFSITE_DAYS * 86400
        why = "" if ok else (offsite.describe().get("human") or "no off-site copy in the last eight days")
        out.append(_entry("backup.offsite", "Weekly off-site copy", ok, why,
                          last_at=float(good) if good else None, said=offsite.describe().get("human", "")))
    return out


#: How long the shared rules may go unfetched before it is said as a failure: two daily fetches missed.
RULES_DAYS = 2


def _rule_defaults(now: float) -> dict:
    """Whether this Rouh fetched the shared rules from rouh.land lately (`ruledefaults.fetch`), as a job of
    its own. Not fetched since it started is said, not alarmed about: the first fetch comes soon after."""
    from . import ruledefaults
    from .config import config

    title = "Rouh's shared rules from rouh.land"
    url = getattr(config, "rule_defaults_url", "") or ""
    if not url:
        return _entry("rules.defaults", title, None, "no address is set (ROUH_RULE_DEFAULTS_URL is empty)")
    said = ruledefaults.fetched_said()
    if not said:
        return _entry("rules.defaults", title, None, "not fetched yet since Rouh started")
    ok_at = float(said.get("ok_at") or 0)
    if said.get("ok"):
        return _entry("rules.defaults", title, True, last_at=ok_at,
                      said=f"revision {said.get('revision')}, {said.get('rules')} rules")
    if ok_at and now - ok_at < RULES_DAYS * 86400:
        return _entry("rules.defaults", title, True, last_at=ok_at,
                      said=f"the last try failed ({said.get('error')}); the one before worked")
    since = f"since {_stamp(ok_at)}" if ok_at else "ever"
    return _entry("rules.defaults", title, False,
                  f"{url} has not given them {since}: {said.get('error') or 'no answer'}. A Rouh keeps the rules "
                  "it has; new ones and changes reach nobody until it answers again",
                  last_at=ok_at or None, said=str(said.get("error") or ""))


def _where(path: str, env: str) -> str:
    """Where a secret comes from: its file, the settings file's environment, or nowhere."""
    if path and os.path.exists(path):
        return f"the file {path}"
    if (os.environ.get(env) or "").strip():
        return f"the settings file ({env})"
    return ""


def secrets() -> list[dict]:
    """Whether the secrets the scheduled jobs need reach this Rouh, and from where: the bot that says
    the morning's alarm, the mail key and the encryption key. Never a value. One that is not set is said
    (ok None) and never alarmed about: an installation may simply not have set it up."""
    from . import mailer, telegram
    from .config import config

    out = []
    tg = telegram.Telegram(config.telegram_file, api_base=config.telegram_api_base).configured()
    src = _where(config.telegram_file, "ROUH_TELEGRAM_BOT_TOKEN")
    out.append(_entry("secret.telegram", "Rouh's Telegram bot", True if tg else None,
                      f"from {src}" if tg else "no bot and chat are set (ROUH_TELEGRAM_BOT_TOKEN and ROUH_TELEGRAM_CHAT_ID, "
                      "or the file), so nothing reaches the phone"))
    mail = mailer.ready(config)
    src = _where(config.brevo_file, "ROUH_BREVO_API_KEY")
    out.append(_entry("secret.mail", "Rouh's own mail (Brevo)", True if mail else None,
                      f"from {src}" if mail else "no sender address (ROUH_MAIL_FROM) or no key (ROUH_BREVO_API_KEY, "
                      "or the file), so Rouh's own letters are not sent"))
    key = bool(os.environ.get("ROUH_ENCRYPTION_KEY") or getattr(config, "encryption_key", ""))
    out.append(_entry("secret.encryption", "The key credentials are sealed with", True if key else None,
                      "from the environment" if key else "ROUH_ENCRYPTION_KEY is not set: a key beside the data is used"))
    return out


def check(who, now: float | None = None) -> dict:
    """Every scheduled job of this person's Rouh: whether it ran at its last time and worked."""
    from . import reminders

    now = now or time.time()
    jobs: list[dict] = []
    rows = reminders._model().objects.filter(user_id=who.user_id, org_id=who.org_id,
                                             kind=reminders.SERVER).order_by("id")
    for row in rows:
        try:
            entry = _clockwork(row, now)
            own = OWN_RECORD.get(str(row.job or ""))
            if entry["ok"] is False and own is not None and not entry["why"].startswith("it was due"):
                # Started at its time: the job's own record says how it went, not the words of its line.
                entry = {**entry, "ok": True, "why": ""}
            if entry["ok"] and own is None:
                entry = _said_failed(entry)
            if own is not None and entry["ok"] is not False:
                entry = own(who, entry)
            elif own is not None and entry["ok"] is False:
                extra = own(who, {**entry, "ok": True, "why": ""})
                if extra.get("why"):
                    entry = {**entry, "why": f"{entry['why']}; {extra['why']}"[:500]}
        except Exception as exc:  # noqa: BLE001 - one job that cannot be read is said, not hidden
            log.exception("a scheduled job could not be checked")
            entry = _entry(str(row.job or ""), str(row.title or ""), False,
                           f"it could not be checked: {type(exc).__name__}: {exc}")
        jobs.append(entry)
    try:
        jobs += _backups(now)
    except Exception as exc:  # noqa: BLE001
        jobs.append(_entry("backup", "Backups", False, f"they could not be checked: {type(exc).__name__}: {exc}"))
    try:
        jobs.append(_rule_defaults(now))
    except Exception as exc:  # noqa: BLE001
        jobs.append(_entry("rules.defaults", "Rouh's shared rules from rouh.land", False,
                           f"it could not be checked: {type(exc).__name__}: {exc}"))
    try:
        jobs += secrets()
    except Exception as exc:  # noqa: BLE001
        jobs.append(_entry("secret", "Secrets", False, f"they could not be checked: {type(exc).__name__}: {exc}"))
    failed = [j for j in jobs if j["ok"] is False]
    if failed:
        human = (f"{len(failed)} of Rouh's {len(jobs)} scheduled jobs and the things they need did not work last time: "
                 + "; ".join(f"{j['title']} ({j['why']})" for j in failed))
    else:
        human = f"All of Rouh's scheduled jobs ran and worked last time, and what they need is there ({len(jobs)} checked)."
    return {"at": _stamp(now), "ts": now, "jobs": jobs, "failed": len(failed), "human": human}


# --- kept, and said once a morning ----------------------------------------------------------------

def _path() -> str:
    from .config import config

    return os.path.join(config.data_dir, "job-watch.json")


def kept() -> dict:
    try:
        with open(_path(), encoding="utf-8") as fh:
            got = json.load(fh)
        return got if isinstance(got, dict) else {}
    except (OSError, ValueError):
        return {}


def keep(result: dict, **extra: Any) -> None:
    path = _path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({**kept(), **result, **extra}, fh)
    os.replace(tmp, path)


#: The same failures are said again only this many days after they were last said.
SAME_AGAIN_DAYS = 7


def failing(result: dict) -> list[str]:
    return sorted(j["job"] for j in result.get("jobs") or [] if j.get("ok") is False)


def alarm_due(result: dict, local: dt.datetime, last: dict) -> bool:
    """At most once a day, from the morning hour on the owner's clock, and only when something failed:
    at once when a job fails that was not failing when it was last said, and the same failures again
    only a week on, so a job that stays broken is not a notice every morning."""
    now_failing = failing(result)
    if not now_failing or local.hour < ALARM_HOUR or last.get("alarmed_on") == local.date().isoformat():
        return False
    if set(now_failing) - set(last.get("alarmed_jobs") or []):
        return True
    try:
        said = dt.date.fromisoformat(str(last.get("alarmed_on")))
    except ValueError:
        return True
    return (local.date() - said).days >= SAME_AGAIN_DAYS


def alarm_title(result: dict) -> str:
    n = len(failing(result))
    return f"{n} of Rouh's night jobs did not work" if n != 1 else "One of Rouh's night jobs did not work"


def alarm_text(result: dict) -> str:
    """The failures first, each with why, then the jobs that did work, by name, so the notice alone says
    how the whole night went."""
    bad = [f"{j['title']}: {j['why']}" for j in result["jobs"] if j["ok"] is False]
    good = [j["title"] for j in result["jobs"] if j["ok"] is True and not str(j.get("job", "")).startswith("secret.")]
    text = (f"Rouh's scheduled jobs: {len(bad)} did not work last time.\n"
            + "\n".join(f"- Did not work: {line}" for line in bad))
    if good:
        text += "\n- Worked: " + ", ".join(good) + "."
    return text


async def tick(who) -> dict:
    """The check, kept, and the morning's alarm when one is due."""
    import asyncio

    from . import clock, notices

    result = await asyncio.to_thread(check, who)
    last = await asyncio.to_thread(kept)
    with clock.person(who):
        local = clock.now()
    if alarm_due(result, local, last):
        await notices.phone(alarm_text(result), kind="alarm", key=f"job-watch:{local.date().isoformat()}",
                            who=who, title=alarm_title(result), link="/clockwork",
                            at_once=False)
        await asyncio.to_thread(keep, result, alarmed_on=local.date().isoformat(), alarmed_jobs=failing(result))
    else:
        await asyncio.to_thread(keep, result)
    return result


def describe() -> dict:
    """What server_health says: the newest check, as kept."""
    got = kept()
    if not got:
        return {"human": "Rouh has not checked its scheduled jobs yet since it started.", "failed": None, "jobs": []}
    return {"at": got.get("at"), "failed": got.get("failed"), "jobs": got.get("jobs") or [],
            "human": got.get("human", "")}


def failed_why(job: str) -> str:
    """Why this scheduled job did not work last time, as the newest check found, or "" when it did (or
    nothing has checked yet). Clockwork's card says it after its last line (`reminders.view`)."""
    if not job:
        return ""
    try:
        for j in kept().get("jobs") or []:
            if j.get("job") == job and j.get("ok") is False:
                return str(j.get("why") or "")
    except Exception:  # noqa: BLE001 - a card is drawn whatever the check's file holds
        return ""
    return ""

