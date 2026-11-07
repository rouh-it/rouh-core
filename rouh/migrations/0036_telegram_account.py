"""The owner's own Telegram account, connected to Rouh, so each fork gets a group.

Petar, 27 September 2026: a fork made on Telegram should open in a new group
chat, "check ... how my other project does that". That project does it with its own
account, through Telethon, because a bot cannot make a group; so does Rouh
now (`rouh/telegram_account.py`). One row per person, keyed by user and
organisation, the API hash and the session sealed.

An empty table, so a Rouh rolled back past this loses nothing it had before.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0035_model_defaults"),
    ]

    operations = [
        migrations.CreateModel(
            name="TelegramAccount",
            fields=[
                ("user_id", models.TextField(primary_key=True, serialize=False)),
                ("org_id", models.TextField()),
                ("api_id", models.BigIntegerField(default=0)),
                ("api_hash_sealed", models.TextField(blank=True, default="")),
                ("state", models.TextField(blank=True, default="")),
                ("pending_sealed", models.TextField(blank=True, default="")),
                ("session_sealed", models.TextField(blank=True, default="")),
                ("name", models.TextField(blank=True, default="")),
                ("phone_hint", models.TextField(blank=True, default="")),
                ("connected_at", models.FloatField(default=0)),
                ("updated_at", models.FloatField(default=0)),
                ("last_error", models.TextField(blank=True, default="")),
            ],
            options={
                "db_table": "telegram_accounts",
                "indexes": [models.Index(fields=["org_id"], name="telegram_accounts_org")],
            },
        ),
    ]
