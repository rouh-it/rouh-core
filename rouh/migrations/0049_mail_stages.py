"""An email's stages, each written down as it happens (`rouh/mail_flow.py`).

A trusted contact's email of 30 September 2026 was taken out of Spam and handed to Rouh,
which started a job and stopped there: she was not helped, not answered and
the owner was not told, and nothing on the record said so. Every column has a
default in the database as well, so a Rouh rolled back past this can still
write a row.
"""
from django.db import migrations, models


def _bool():
    return models.BooleanField(default=False, db_default=False)


def _text():
    return models.TextField(blank=True, default="", db_default="")


def _time():
    return models.FloatField(default=0, db_default=0)


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0048_page_places"),
    ]

    operations = [
        migrations.AddField("mailalertseen", "trusted", _bool()),
        migrations.AddField("mailalertseen", "trust", _text()),
        migrations.AddField("mailalertseen", "known", _bool()),
        migrations.AddField("mailalertseen", "triage", _text()),
        migrations.AddField("mailalertseen", "triage_note", _text()),
        migrations.AddField("mailalertseen", "triaged_at", _time()),
        migrations.AddField("mailalertseen", "help_needed", _bool()),
        migrations.AddField("mailalertseen", "reply_owed", _bool()),
        migrations.AddField("mailalertseen", "work",
                            models.JSONField(default=list, db_default=[])),
        migrations.AddField("mailalertseen", "outcome", _text()),
        migrations.AddField("mailalertseen", "outcome_note", _text()),
        migrations.AddField("mailalertseen", "outcome_at", _time()),
        migrations.AddField("mailalertseen", "reply_id", _text()),
        migrations.AddField("mailalertseen", "reply_claimed_at", _time()),
        migrations.AddField("mailalertseen", "replied_at", _time()),
        migrations.AddField("mailalertseen", "drafted", _bool()),
        migrations.AddField("mailalertseen", "told_at", _time()),
        migrations.AddField("mailalertseen", "replays",
                            models.IntegerField(default=0, db_default=0)),
    ]
