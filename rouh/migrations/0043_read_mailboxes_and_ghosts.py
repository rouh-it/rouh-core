"""Read-only mailboxes and the ghost list's marks (`rouh/mailboxes.py`, `rouh/ghosts.py`).

Task 71, 30 September 2026: "Waiting on others" in the morning brief, read
from the person's own mailboxes, each connected read-only. Both tables start
empty, so a Rouh rolled back past this migration loses nothing it had before.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0042_morning_briefs"),
    ]

    operations = [
        migrations.CreateModel(
            name="ReadMailbox",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("user_id", models.TextField()),
                ("org_id", models.TextField()),
                ("email", models.TextField(blank=True, default="")),
                ("google_account", models.TextField()),
                ("access_sealed", models.TextField(blank=True, default="")),
                ("refresh_sealed", models.TextField(blank=True, default="")),
                ("expires_at", models.FloatField(default=0)),
                ("scopes", models.TextField(blank=True, default="")),
                ("connected_at", models.FloatField(default=0)),
                ("needs_reconnect", models.BooleanField(default=False)),
                ("trouble", models.TextField(blank=True, default="")),
                ("scan", models.TextField(blank=True, default="")),
                ("scanned_at", models.FloatField(default=0)),
            ],
            options={
                "db_table": "read_mailboxes",
                "constraints": [models.UniqueConstraint(
                    fields=("org_id", "user_id", "google_account"),
                    name="read_mailboxes_once_each")],
                "indexes": [models.Index(fields=["org_id", "user_id"],
                                         name="read_mailboxes_whose")],
            },
        ),
        migrations.CreateModel(
            name="GhostMark",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("user_id", models.TextField()),
                ("org_id", models.TextField()),
                ("mailbox_id", models.BigIntegerField()),
                ("thread_id", models.TextField()),
                ("message_id", models.TextField()),
                ("state", models.TextField()),
                ("until", models.FloatField(default=0)),
                ("at", models.FloatField()),
            ],
            options={
                "db_table": "ghost_marks",
                "constraints": [models.UniqueConstraint(
                    fields=("org_id", "user_id", "mailbox_id", "thread_id"),
                    name="ghost_marks_one")],
            },
        ),
    ]
