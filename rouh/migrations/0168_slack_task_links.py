"""A Slack channel linked to a task (`rouh/slack_tasks.py`, `rouh/models/slack.py`).

Petar, 16 October 2026, the fifth of five Slack ideas: "link #pricing to 19". While a channel is
linked, a decision made in it is written into the task's notes as it happens. Two new tables: the
links, and the decisions written, each with the line written so it can be taken out again.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0167_slack_promises"),
    ]

    operations = [
        migrations.CreateModel(
            name="SlackTaskLink",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("org_id", models.TextField()),
                ("user_id", models.TextField()),
                ("team_id", models.TextField()),
                ("channel_id", models.TextField()),
                ("task_id", models.TextField()),
                ("linked_at", models.FloatField(default=0)),
                ("read_to", models.FloatField(default=0)),
                ("made_at", models.FloatField(default=0)),
                ("updated_at", models.FloatField(default=0)),
            ],
            options={"db_table": "slack_task_links"},
        ),
        migrations.AddConstraint(
            model_name="slacktasklink",
            constraint=models.UniqueConstraint(fields=("org_id", "team_id", "channel_id"),
                                               name="slack_task_links_one"),
        ),
        migrations.AddIndex(
            model_name="slacktasklink",
            index=models.Index(fields=["org_id", "task_id"], name="slack_task_links_task"),
        ),
        migrations.CreateModel(
            name="SlackTaskDecision",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("org_id", models.TextField()),
                ("user_id", models.TextField()),
                ("team_id", models.TextField()),
                ("channel_id", models.TextField()),
                ("task_id", models.TextField()),
                ("ts", models.TextField()),
                ("thread_ts", models.TextField(blank=True, default="")),
                ("key", models.TextField()),
                ("who", models.TextField(blank=True, default="")),
                ("decision", models.TextField()),
                ("quote", models.TextField(blank=True, default="")),
                ("link", models.TextField(blank=True, default="")),
                ("said_at", models.FloatField(default=0)),
                ("line", models.TextField(blank=True, default="")),
                ("notes", models.TextField(blank=True, default="")),
                ("written_at", models.FloatField(default=0)),
                ("removed_at", models.FloatField(default=0)),
            ],
            options={"db_table": "slack_task_decisions"},
        ),
        migrations.AddConstraint(
            model_name="slacktaskdecision",
            constraint=models.UniqueConstraint(fields=("org_id", "key"), name="slack_task_decisions_one"),
        ),
        migrations.AddIndex(
            model_name="slacktaskdecision",
            index=models.Index(fields=["org_id", "task_id"], name="slack_task_decisions_task"),
        ),
    ]
