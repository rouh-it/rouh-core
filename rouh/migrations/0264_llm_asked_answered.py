"""What each model call was asked and what came back, short, for the cost page.

The owner, 19 November 2026: the "One call" page of Usage says what a call cost and what its prompt
was made of, but not what it was, so the owner had to ask Rouh. Two nullable columns, so adding them
rewrites nothing and every call before keeps NULL (`rouh/llmlog.py`, `asked_of`, `answered_of`).
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("rouh", "0263_connection_incidents")]

    operations = [
        migrations.AddField(model_name="llmrequest", name="asked",
                            field=models.JSONField(blank=True, null=True)),
        migrations.AddField(model_name="llmrequest", name="answered",
                            field=models.JSONField(blank=True, null=True)),
    ]
