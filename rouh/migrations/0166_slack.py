"""Slack: an organisation's own Slack app, its sealed tokens, and every message it can see
(`rouh/slack.py`, `rouh/models/slack.py`).

Petar, 16 October 2026: "I need you to evesdrop on my slack. Full integration. You should be able
to talk to people and be added to channels. Ideally we also want personal messages directly to me
to be readable by you." Four new tables, so nothing that is there changes.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0165_draft_edits"),
    ]

    operations = [
        migrations.CreateModel(
            name="SlackConnection",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("org_id", models.TextField()),
                ("user_id", models.TextField(blank=True, default="")),
                ("team_id", models.TextField(blank=True, default="")),
                ("team_name", models.TextField(blank=True, default="")),
                ("team_url", models.TextField(blank=True, default="")),
                ("bot_user_id", models.TextField(blank=True, default="")),
                ("bot_name", models.TextField(blank=True, default="")),
                ("slack_user_id", models.TextField(blank=True, default="")),
                ("slack_user_name", models.TextField(blank=True, default="")),
                ("bot_sealed", models.TextField(blank=True, default="")),
                ("bot_last4", models.TextField(blank=True, default="")),
                ("user_sealed", models.TextField(blank=True, default="")),
                ("user_last4", models.TextField(blank=True, default="")),
                ("app_sealed", models.TextField(blank=True, default="")),
                ("app_last4", models.TextField(blank=True, default="")),
                ("saved_at", models.FloatField(default=0)),
                ("checked_at", models.FloatField(default=0)),
                ("listening", models.TextField(blank=True, default="")),
                ("listening_said", models.TextField(blank=True, default="")),
                ("connected_at", models.FloatField(default=0)),
                ("heard_at", models.FloatField(default=0)),
                ("backfill", models.JSONField(blank=True, default=dict)),
                ("made_at", models.FloatField(default=0)),
                ("updated_at", models.FloatField(default=0)),
            ],
            options={"db_table": "slack_connections"},
        ),
        migrations.AddConstraint(
            model_name="slackconnection",
            constraint=models.UniqueConstraint(fields=("org_id",), name="slack_connections_one"),
        ),
        migrations.CreateModel(
            name="SlackConversation",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("org_id", models.TextField()),
                ("user_id", models.TextField()),
                ("team_id", models.TextField()),
                ("channel_id", models.TextField()),
                ("kind", models.TextField(default="channel")),
                ("name", models.TextField(blank=True, default="")),
                ("is_member", models.BooleanField(default=False)),
                ("private", models.BooleanField(default=False)),
                ("is_archived", models.BooleanField(default=False)),
                ("topic", models.TextField(blank=True, default="")),
                ("other_id", models.TextField(blank=True, default="")),
                ("backfilled_at", models.FloatField(default=0)),
                ("updated_at", models.FloatField(default=0)),
            ],
            options={"db_table": "slack_conversations"},
        ),
        migrations.AddConstraint(
            model_name="slackconversation",
            constraint=models.UniqueConstraint(fields=("org_id", "team_id", "channel_id"),
                                               name="slack_conversations_one"),
        ),
        migrations.CreateModel(
            name="SlackPerson",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("org_id", models.TextField()),
                ("team_id", models.TextField()),
                ("slack_id", models.TextField()),
                ("name", models.TextField(blank=True, default="")),
                ("real_name", models.TextField(blank=True, default="")),
                ("email", models.TextField(blank=True, default="")),
                ("is_bot", models.BooleanField(default=False)),
                ("deleted", models.BooleanField(default=False)),
                ("contact_id", models.TextField(blank=True, default="")),
                ("contact_name", models.TextField(blank=True, default="")),
                ("updated_at", models.FloatField(default=0)),
            ],
            options={"db_table": "slack_people"},
        ),
        migrations.AddConstraint(
            model_name="slackperson",
            constraint=models.UniqueConstraint(fields=("org_id", "team_id", "slack_id"),
                                               name="slack_people_one"),
        ),
        migrations.CreateModel(
            name="SlackMessage",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("org_id", models.TextField()),
                ("user_id", models.TextField()),
                ("team_id", models.TextField()),
                ("channel_id", models.TextField()),
                ("ts", models.TextField()),
                ("thread_ts", models.TextField(blank=True, default="")),
                ("reply_count", models.IntegerField(default=0)),
                ("author_id", models.TextField(blank=True, default="")),
                ("author_name", models.TextField(blank=True, default="")),
                ("contact_id", models.TextField(blank=True, default="")),
                ("contact_name", models.TextField(blank=True, default="")),
                ("text", models.TextField(blank=True, default="")),
                ("files", models.JSONField(blank=True, default=list)),
                ("subtype", models.TextField(blank=True, default="")),
                ("at", models.FloatField(default=0)),
                ("edited_at", models.FloatField(default=0)),
                ("private", models.BooleanField(default=False)),
                ("by_rouh", models.BooleanField(default=False)),
                ("handed", models.TextField(blank=True, default="")),
                ("made_at", models.FloatField(default=0)),
                ("updated_at", models.FloatField(default=0)),
            ],
            options={"db_table": "slack_messages"},
        ),
        migrations.AddConstraint(
            model_name="slackmessage",
            constraint=models.UniqueConstraint(fields=("org_id", "team_id", "channel_id", "ts"),
                                               name="slack_messages_one"),
        ),
        migrations.AddIndex(
            model_name="slackmessage",
            index=models.Index(fields=["org_id", "channel_id", "at"], name="slack_messages_when"),
        ),
        migrations.AddIndex(
            model_name="slackmessage",
            index=models.Index(fields=["org_id", "author_id"], name="slack_messages_who"),
        ),
    ]
