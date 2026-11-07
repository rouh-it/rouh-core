"""A trusted contact's own Telegram account, linked by them and confirmed by Petar.

Petar, 5 October 2026: a trusted contact may use Rouh over Telegram with exactly
the permissions they have by email (`rouh/telegram_guests.py`). A new table, so a
Rouh rolled back past this never reads or writes it.
"""
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("rouh", "0085_reminder_may_email_gone")]

    operations = [
        migrations.CreateModel(
            name="TelegramLink",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("user_id", models.TextField()),
                ("org_id", models.TextField()),
                ("state", models.TextField(default="waiting")),
                ("code_hash", models.TextField(blank=True, default="")),
                ("code_expires_at", models.FloatField(default=0)),
                ("tg_user_id", models.TextField(blank=True, default="")),
                ("tg_name", models.TextField(blank=True, default="")),
                ("tg_username", models.TextField(blank=True, default="")),
                ("made_at", models.FloatField(default=0)),
                ("claimed_at", models.FloatField(default=0)),
                ("linked_at", models.FloatField(default=0)),
                ("updated_at", models.FloatField(default=0)),
                ("contact", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                              related_name="+", to="rouh.trustedcontact")),
            ],
            options={"db_table": "telegram_links"},
        ),
        migrations.AddConstraint(
            model_name="telegramlink",
            constraint=models.UniqueConstraint(fields=("org_id", "user_id", "contact"),
                                               name="telegram_links_one_per_contact"),
        ),
        migrations.AddConstraint(
            model_name="telegramlink",
            constraint=models.UniqueConstraint(condition=models.Q(("tg_user_id", ""),
                                                                  _negated=True),
                                               fields=("org_id", "user_id", "tg_user_id"),
                                               name="telegram_links_one_per_account"),
        ),
    ]
