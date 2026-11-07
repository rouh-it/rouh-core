"""Apple Contacts: each person's iCloud connection, and their cards.

Petar, 24 September 2026: a live, two-way Apple Contacts integration over
iCloud's CardDAV, so the assistant can look people up and add or update them.
Two tables, one row per person and one row per card, both keyed by person and
organisation and queried scoped (`CLAUDE.md`, "Whose data is it"). The
app-specific password is sealed in ``password_sealed`` exactly as a Google
refresh token is. `rouh/apple_contacts.py` owns what the rows mean.

Nothing is in either table until somebody enters an Apple ID in Settings, so a
Rouh rolled back past this migration loses nothing it had before.

It was written as 0006 and renumbered the same night: two other migrations,
0006 and 0007, landed on main while it was being built, and two leaves in one
app is a graph Django refuses to migrate, which is how the first deploy of it
failed and was rolled back.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0007_renumber_task_51_to_59"),
    ]

    operations = [
        migrations.CreateModel(
            name="AppleConnection",
            fields=[
                ("user_id", models.TextField(primary_key=True, serialize=False)),
                ("org_id", models.TextField()),
                ("apple_id", models.TextField()),
                ("password_sealed", models.TextField()),
                ("connected_at", models.FloatField(default=0)),
                ("principal_url", models.TextField(blank=True, default="")),
                ("home_url", models.TextField(blank=True, default="")),
                ("book_url", models.TextField(blank=True, default="")),
                ("sync_token", models.TextField(blank=True, default="")),
                ("last_sync_at", models.FloatField(default=0)),
                ("last_sync_changed", models.IntegerField(default=0)),
                ("last_attempt_at", models.FloatField(default=0)),
                ("last_error", models.TextField(blank=True, default="")),
                ("needs_new_password", models.BooleanField(default=False)),
            ],
            options={
                "db_table": "apple_connections",
                "indexes": [models.Index(fields=["org_id"], name="apple_connections_org")],
            },
        ),
        migrations.CreateModel(
            name="AppleContact",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("user_id", models.TextField()),
                ("org_id", models.TextField()),
                ("href", models.TextField()),
                ("uid", models.TextField(blank=True, default="")),
                ("etag", models.TextField(blank=True, default="")),
                ("kind", models.TextField(default="individual")),
                ("name", models.TextField(blank=True, default="")),
                ("phones", models.JSONField(default=list)),
                ("emails", models.JSONField(default=list)),
                ("organisation", models.TextField(blank=True, default="")),
                ("birthday", models.TextField(blank=True, default="")),
                ("note", models.TextField(blank=True, default="")),
                ("vcard", models.TextField()),
                ("search_text", models.TextField(blank=True, default="")),
                ("digits", models.TextField(blank=True, default="")),
                ("changed_at", models.FloatField()),
                ("gone_at", models.FloatField(blank=True, null=True)),
            ],
            options={
                "db_table": "apple_contacts",
                "indexes": [models.Index(fields=["user_id", "org_id", "name"],
                                         name="apple_contacts_mine")],
                "constraints": [models.UniqueConstraint(fields=["user_id", "href"],
                                                        name="apple_contacts_one")],
            },
        ),
    ]
