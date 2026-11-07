"""Promises in Slack (`rouh/slack_promises.py`, `rouh/models/slack.py`).

Petar, 16 October 2026, of five Slack ideas: "do all of those". The second: a commitment with a
deadline, made by him or to him in a Slack message Rouh keeps, is kept as a promise and waits in
Decisions, never as a task. One new table, and one column on the kept messages saying when each
was read for promises; every message kept before this waits to be read (0).
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0166_slack"),
    ]

    operations = [
        migrations.AddField(
            model_name="slackmessage",
            name="promises_read",
            field=models.FloatField(default=0),
        ),
        migrations.AddIndex(
            model_name="slackmessage",
            index=models.Index(fields=["org_id", "promises_read"], name="slack_messages_promises"),
        ),
        migrations.CreateModel(
            name="SlackPromise",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("org_id", models.TextField()),
                ("user_id", models.TextField()),
                ("team_id", models.TextField()),
                ("channel_id", models.TextField()),
                ("ts", models.TextField()),
                ("thread_ts", models.TextField(blank=True, default="")),
                ("key", models.TextField()),
                ("by_petar", models.BooleanField(default=False)),
                ("by_id", models.TextField(blank=True, default="")),
                ("by_name", models.TextField(blank=True, default="")),
                ("to_name", models.TextField(blank=True, default="")),
                ("what", models.TextField()),
                ("quote", models.TextField(blank=True, default="")),
                ("due_at", models.FloatField(default=0)),
                ("due_day", models.TextField(blank=True, default="")),
                ("due_said", models.TextField(blank=True, default="")),
                ("nudge", models.TextField(blank=True, default="")),
                ("status", models.TextField(default="open")),
                ("closed_by", models.TextField(blank=True, default="")),
                ("closed_at", models.FloatField(default=0)),
                ("kept_ts", models.TextField(blank=True, default="")),
                ("kept_said", models.TextField(blank=True, default="")),
                ("kept_by", models.TextField(blank=True, default="")),
                ("kept_why", models.TextField(blank=True, default="")),
                ("not_kept", models.JSONField(blank=True, default=list)),
                ("reopened", models.IntegerField(default=0)),
                ("reminders", models.IntegerField(default=0)),
                ("reminded_at", models.FloatField(default=0)),
                ("reminder_ts", models.TextField(blank=True, default="")),
                ("reminder_text", models.TextField(blank=True, default="")),
                ("note", models.TextField(blank=True, default="")),
                ("private", models.BooleanField(default=False)),
                ("read_back", models.BooleanField(default=False)),
                ("made_at", models.FloatField(default=0)),
                ("updated_at", models.FloatField(default=0)),
            ],
            options={"db_table": "slack_promises"},
        ),
        migrations.AddConstraint(
            model_name="slackpromise",
            constraint=models.UniqueConstraint(fields=("org_id", "key"), name="slack_promises_one"),
        ),
        migrations.AddIndex(
            model_name="slackpromise",
            index=models.Index(fields=["org_id", "user_id", "status"], name="slack_promises_open"),
        ),
        migrations.AddIndex(
            model_name="slackpromise",
            index=models.Index(fields=["org_id", "channel_id", "status"], name="slack_promises_where"),
        ),
    ]
