"""Promises in Slack go to Clockwork, or wait until they are late (`rouh/slack_promises.py`).

Petar, 16 October 2026, asking why Slack promises went to the decisions list, and then "Do it": a
promise is not a decision until it is overdue and he must choose what to do; before that it is a
deadline, and deadlines belong on Clockwork. So one of his own keeps the Clockwork reminder made for
it, and one made to him keeps how often he said Wait and until when.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0170_dreame"),
    ]

    operations = [
        migrations.AddField(
            model_name="slackpromise",
            name="clockwork_id",
            field=models.BigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="slackpromise",
            name="clockwork_at",
            field=models.FloatField(default=0),
        ),
        migrations.AddField(
            model_name="slackpromise",
            name="waits",
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name="slackpromise",
            name="wait_until",
            field=models.FloatField(default=0),
        ),
    ]
