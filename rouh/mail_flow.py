"""A job started from the owner's own email, followed until its report is back.

Petar, 30 September 2026, in the chat where a contact's email had been handled:
"You did start a run to investigate, but ultimately you didn't help [her],
didn't answer her and didn't notify me that you helped her." A job that has
started is work in progress and nothing more, so the email it was started for
is not finished until the job's report comes back and Rouh answers with it.

The same day this module carried every email's stages - triage, the work, the
outcome, the answer and the note - on its row in `mail_alert_seen`. That
evening everybody's email but the owner's own became a case (`rouh/mail_cases.py`,
which has all of those stages and more, with the reply sent by the code), so
what is left here is the one thing the owner's own mail still needs: a job started
from his email (`delegate_task`, `assistant_job`) is written against it
(`work_started`), the email stays **working** until the job reports
(`work_reported` in `mail_alerts`), and then Rouh is handed it back in the
same conversation to answer him with the result (`resume_note`). A report
that never arrives - Rouh restarting as it came, a job that died - is chased
by the case sweep (`mail_alerts.MailAlerts.chores`).

The stage columns on `mail_alert_seen` (`triage`, `outcome`, `reply_owed` and
the rest) stay in the table for the rows written while they were used; nothing
writes them now.
"""
from __future__ import annotations

import logging
import time

log = logging.getLogger("rouh.mail_flow")

#: The state of one piece of work in `MailAlertSeen.work`.
RUNNING, FINISHED = "running", "finished"

#: How long a job may have been finished with its report never reaching the
#: email before the sweep hands the email back on its own (`MailAlerts.chores`).
REPORT_GRACE_SECONDS = 10 * 60


def _rows(user_id: str, org_id: str, message_id: str):
    from .models import MailAlertSeen

    return MailAlertSeen.objects.filter(user_id=user_id, org_id=org_id,
                                        message_id=message_id)


def row_of(user_id: str, org_id: str, message_id: str) -> dict | None:
    return _rows(user_id, org_id, message_id).values().first() if message_id else None


# --- the work ---------------------------------------------------------------------------


def _open_work(row: dict) -> list[dict]:
    return [w for w in (row.get("work") or []) if w.get("state") == RUNNING]


def _finished_unseen(row: dict) -> list[dict]:
    return [w for w in (row.get("work") or []) if w.get("state") == FINISHED
            and not w.get("seen")]


def work_started(turn, run_id: str, title: str) -> None:
    """A job was started for this email: in progress, and nothing more."""
    from django.db import transaction

    from .models import MailAlertSeen

    if not run_id:
        return
    with transaction.atomic():
        row = (MailAlertSeen.objects.select_for_update()
               .filter(user_id=turn.user_id, org_id=turn.org_id, message_id=turn.message_id)
               .first())
        if row is None:
            return
        work = [w for w in (row.work or []) if w.get("run") != run_id]
        work.append({"run": run_id, "title": (title or "")[:200], "state": RUNNING,
                     "at": time.time()})
        row.work = work
        row.save(update_fields=["work"])
    log.info("mail %s: job %s started for it; it is in progress until the job reports",
             turn.message_id, run_id)


def email_of_run(run_id: str) -> dict | None:
    """The email a job was started for, if it was started for one."""
    from .models import MailAlertSeen

    if not run_id:
        return None
    for row in (MailAlertSeen.objects.filter(work__contains=[{"run": str(run_id)}])
                .order_by("-id").values()[:1]):
        return row
    return None


def work_finished(row: dict, run_id: str, report: str) -> bool:
    """Write down that a job for this email has finished, and what it said.

    True when this is news: the job was still running on the record. A report
    said twice is taken once.
    """
    from django.db import transaction

    from .models import MailAlertSeen

    with transaction.atomic():
        got = MailAlertSeen.objects.select_for_update().filter(id=row["id"]).first()
        if got is None:
            return False
        news = False
        work = []
        for one in got.work or []:
            if one.get("run") == run_id and one.get("state") == RUNNING:
                one = {**one, "state": FINISHED, "said": (report or "")[:8000],
                       "ended": time.time()}
                news = True
            work.append(one)
        if news:
            got.work = work
            got.save(update_fields=["work"])
    return news


def seen_reports(row: dict) -> None:
    """The finished jobs' reports have been put in front of Rouh."""
    from .models import MailAlertSeen

    work = [{**w, "seen": True} if w.get("state") == FINISHED else w
            for w in (row.get("work") or [])]
    MailAlertSeen.objects.filter(id=row["id"]).update(work=work)


# --- what Rouh is told -------------------------------------------------------------------


def done_so_far(row: dict | None) -> list[str]:
    """What is already on the record for this email, one line each."""
    if not row:
        return []
    out = []
    for w in row.get("work") or []:
        state = "still running" if w.get("state") == RUNNING else "finished"
        out.append(f"Job {w.get('run')} ({w.get('title') or 'no title'}): {state}.")
    if row.get("replied") or row.get("reply_id"):
        out.append("It has been answered already.")
    return out


def resume_note(row: dict, reports: list[dict], *, owner: str) -> str:
    """What Rouh is told when the owner's email, whose job has reported, comes back to it."""
    from .turnmarks import NOTE
    from .untrusted import wrap

    out = [f"{NOTE} The email at the head of this conversation, message id "
           f"{row['message_id']}, is back with you to finish. Nothing already done is done "
           "again.]", ""]
    done = done_so_far(row)
    if done:
        out += ["Already on the record:"] + [f"- {line}" for line in done] + [""]
    for one in reports:
        out.append(f"The job {one.get('run')} ({one.get('title') or 'no title'}) has "
                   "finished. What it reported:")
        out.append(wrap(one.get("said") or "(it said nothing that could be read)",
                        "a background job's report of what it did and saw"))
        out.append("")
    out += [f"It is {owner}'s own email. Answer it again in its own thread with send_mail "
            f"and reply_to_message_id {row['message_id']}, with what the job did and "
            "found, in full.", "", "Then say here, in one or two sentences, what you did."]
    return "\n".join(out)


def said_for_log(row: dict) -> str:
    """What became of it, one sentence, for Settings and the log."""
    if _open_work(row):
        return "Working on it: " + ", ".join(
            (w.get("title") or w.get("run") or "a job") for w in _open_work(row)) + "."
    return ""


# --- a job's report, back to its email ---------------------------------------------------

#: What takes a job's report back to the email it was started for, given the
#: job's id and its report, answering whether the job was an email's at all
#: (`MailAlerts.work_reported`). None where no mail is handled.
on_report = None


async def reported(run_id: str, report: str) -> bool:
    """Whether a finished job's report belongs to an email, which then takes it.

    The job reporters (`assistant_job.Lander._say`, `job_report.JobReporter`)
    ask this before they say a job's result in a conversation. Never raises:
    a report that could not be taken back is said like any other.
    """
    if on_report is None or not run_id:
        return False
    try:
        return bool(await on_report(str(run_id), report or ""))
    except Exception:  # noqa: BLE001 - the report is still said the ordinary way
        log.exception("the report of job %s could not be taken back to its email", run_id)
        return False
