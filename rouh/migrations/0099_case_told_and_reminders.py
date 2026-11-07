"""What a case's own code told the sender, newer messages kept as context, and reminders.

Petar, 6 October 2026, after a trusted contact heard nothing for twenty hours
about a research request: an acknowledgement once a request is accepted and
handed to a job, a status update after a quiet spell for a contact who may be
told where their requests stand, a newer message in the same conversation kept
on the open case instead of lapsing its approval, and one reminder to him of a
decision left waiting (`rouh/mail_cases.py`).

None of it reaches back: every case already open is marked as told nothing
(`told` {"before": true}), so no acknowledgement or status update goes for it,
and every approval already waiting is marked as reminded, so no reminder goes
for it. He asked that nothing go to that contact as part of this work.
"""
import time

from django.db import migrations, models

CLOSED = ("done", "blocked", "junk_spam", "junk_not_moved")


def quiet_for_what_is_open(apps, schema_editor):
    MailCase = apps.get_model("rouh", "MailCase")
    MailApproval = apps.get_model("rouh", "MailApproval")
    MailCase.objects.exclude(stage__in=CLOSED).update(told={"before": True})
    MailApproval.objects.filter(status="pending").update(reminded_at=time.time())


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0098_trusted_tell_status'),
    ]

    operations = [
        migrations.AddField(
            model_name='mailcase',
            name='told',
            field=models.JSONField(default=dict, db_default={}),
        ),
        migrations.AddField(
            model_name='mailcase',
            name='later',
            field=models.JSONField(default=list, db_default=[]),
        ),
        migrations.AddField(
            model_name='mailapproval',
            name='reminded_at',
            field=models.FloatField(default=0, db_default=0),
        ),
        migrations.RunPython(quiet_for_what_is_open, migrations.RunPython.noop),
    ]
