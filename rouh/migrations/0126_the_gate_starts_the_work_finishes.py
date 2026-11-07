"""The case is an entry gate only (Petar, 11 October 2026, `MAIL.md`, D18).

"I don't think approval should be involved in the work, once I approve and it passes by me and
my rules. It is responsible for letting tasks start, not monitoring their responses and status
and completion." An ask the gate lets through is started as ordinary work and marked started,
with its handle (`MailAsk.work`); what that work sends back for the contact waits on the case a
few minutes, so results that finish together go together (`MailCase.results`).

Open cases move onto this without anything being sent or run: a case caught between its work
and the old check, or waiting on a job its work or the check started, has the asks that work
was doing marked started, with the jobs it knows of as their handles, and rests where its
ledger says. Its old decision is made again by the sweep (D8), and nothing reaches the contact.
"""
import time

from django.db import migrations, models

#: The old steps after the work had started: the work's job, the check, the jobs fixing it.
OLD_STEPS = ("waiting_on_job", "verifying", "following_up")


def forwards(apps, schema_editor):
    MailCase = apps.get_model("rouh", "MailCase")
    MailAsk = apps.get_model("rouh", "MailAsk")
    MailCaseEvent = apps.get_model("rouh", "MailCaseEvent")
    now = time.time()
    for case in MailCase.objects.filter(stage__in=OLD_STEPS):
        follow = case.follow_up or {}
        jobs = [case.job_id, str(follow.get("job_id") or "")]
        jobs += [str(j.get("id") or "") for j in follow.get("jobs") or [] if isinstance(j, dict)]
        jobs = list(dict.fromkeys(j for j in jobs if j))
        handles = [{"kind": "job", "ref": j, "title": f"Job {j}", "at": now} for j in jobs] or \
            [{"kind": "note", "ref": "", "title": "Started by the case's own work before 12 "
                                                   "October 2026", "at": now}]
        asks = list(MailAsk.objects.filter(case_id=case.id, gone=False))
        moved = []
        for a in asks:
            if a.status not in ("allowed", "approved"):
                continue
            only_answer = a.grant == "none" and not a.hard_limit
            a.status = "done" if only_answer else "started"
            a.why = ("Answered before the gate model." if only_answer else
                     "Started before the gate model; its work has it.")
            if not only_answer:
                a.work = handles
            a.updated_at = now
            a.save(update_fields=["status", "why", "work", "updated_at"])
            moved.append(a)
        live = [a for a in asks if not a.gone]
        if any(a.status in ("waiting_for_petar", "failed", "approved", "allowed") for a in live):
            stage = "awaiting_approval"
        elif live and all(a.status == "declined" for a in live):
            stage = "blocked"
        else:
            stage = "done"
        MailCase.objects.filter(id=case.id).update(stage=stage, turn_started_at=0, updated_at=now)
        started = sum(1 for a in moved if a.status == "started")
        answered = len(moved) - started
        MailCaseEvent.objects.create(
            user_id=case.user_id, org_id=case.org_id, case_id=case.id, stage=stage, at=now,
            said=(f"Moved onto the gate model (D18): {started} ask"
                  f"{'s' if started != 1 else ''} the work was doing marked started, and its "
                  "work has them now"
                  + (f"; {answered} answer{'s' if answered != 1 else ''} marked done"
                     if answered else "") + ". Nothing ran and nothing was sent."))


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0125_clockwork_follows_grants"),
    ]

    operations = [
        migrations.AddField(
            model_name="mailask",
            name="work",
            field=models.JSONField(blank=True, db_default=[], default=list),
        ),
        migrations.AddField(
            model_name="mailcase",
            name="results",
            field=models.JSONField(blank=True, db_default=[], default=list),
        ),
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
