"""A case hands on what its contact's levels cannot do, and keeps the reply that went.

Petar, 1 October 2026: a case whose work leaves a step the contact's levels
cannot reach - a database write, a server-side repair - hands that step to a
server job (or to him, when it is a decision) and waits for it, rather than
stopping as blocked (`mail_cases.CaseDesk._hand_off`). And the reply says only
what was proven: when the rest cannot be finished, a reply that states only
what was verified goes instead of none (`CaseDesk._honest`). So a case keeps
the step it handed on and the job doing it, the honest reply, and the reply
exactly as it was sent.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0052_page_opened"),
    ]

    operations = [
        migrations.AddField(model_name="mailcase", name="follow_up",
                            field=models.JSONField(default=dict)),
        migrations.AddField(model_name="mailcase", name="partial_reply",
                            field=models.TextField(blank=True, default="")),
        migrations.AddField(model_name="mailcase", name="still_open",
                            field=models.TextField(blank=True, default="")),
        migrations.AddField(model_name="mailcase", name="reply_kind",
                            field=models.TextField(blank=True, default="")),
        migrations.AddField(model_name="mailcase", name="sent_reply",
                            field=models.TextField(blank=True, default="")),
    ]
