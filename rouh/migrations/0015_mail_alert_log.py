"""What the mail alerts' decision log shows: what the AI read, and what it said.

Petar, 24 September 2026 (fr_6b8861e231e4), after a second test email never
reached his phone: "i think i need a log of the ai decisions on the emails."
`mail_alert_seen` kept the sender's name, the subject and the model's one
sentence, which was not enough to tell why: not even the address the email
came from. These columns keep the rest of what the decision was made on
(`MailAlerts.decisions`, the page at /settings/mail-alerts/log).

Every column has a default in the database as well as in Django, so a Rouh
rolled back past this migration can still write a row, and the rows it had
read before it are shown as recorded before the log kept details.
"""
from django.db import migrations, models


def _text() -> models.TextField:
    return models.TextField(blank=True, default="", db_default="")


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0014_chat_fork"),
    ]

    operations = [
        migrations.AddField(model_name="mailalertseen", name=name, field=_text())
        for name in ("stage", "address", "labels", "snippet", "own", "model", "answer", "note")
    ]
