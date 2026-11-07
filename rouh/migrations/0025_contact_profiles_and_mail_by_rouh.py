"""Contacts gain a relationship and online research, and Rouh itself handles new mail.

Petar, 25 September 2026 (fr_b657bd8f6100), having found an inbox full of
mail he did not know about: "we need to update our contacts. Please add two
fields: 1. Online research (MD content) 2. My relationship to them", and "We
will remove the small haiku model that decides whether I have to be notified.
That entire functionality should be removed. You will be deciding what to
do."

Three things, all additive to the database:

- `contact_profiles`, what Rouh knows about a person beyond their card
  (`rouh/people.py`). A table of its own rather than two columns on
  `apple_contacts`, because that table is a copy of iCloud that a disconnect
  drops and a sync rewrites, and because somebody who writes in need not be
  in the address book at all.
- `mail_alert_seen` learns the Gmail thread, the conversation in Rouh a
  message was handled in, whether it was the person's own instruction, and
  whether Rouh answered it.
- The two columns only the small model used, `mail_alerts.guidance` and
  `mail_alert_seen.own`, leave Django's picture of the tables and stay in the
  database, each with a default there, so a Rouh rolled back past this can
  still read and write both tables.
"""
from django.db import migrations, models


def _text() -> models.TextField:
    return models.TextField(blank=True, default="", db_default="")


def _flag() -> models.BooleanField:
    return models.BooleanField(default=False, db_default=False)


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0024_option_reasons"),
    ]

    operations = [
        migrations.CreateModel(
            name="ContactProfile",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("user_id", models.TextField()),
                ("org_id", models.TextField()),
                ("apple_uid", models.TextField(blank=True, default="")),
                ("name", models.TextField(blank=True, default="")),
                ("emails", models.JSONField(default=list)),
                ("is_me", models.BooleanField(default=False)),
                ("relationship", models.TextField(blank=True, default="")),
                ("relationship_at", models.FloatField(default=0)),
                ("research", models.TextField(blank=True, default="")),
                ("researched_at", models.FloatField(default=0)),
                ("research_confirmed", models.BooleanField(default=False)),
                ("created_at", models.FloatField(default=0)),
                ("updated_at", models.FloatField(default=0)),
            ],
            options={
                "db_table": "contact_profiles",
                "indexes": [models.Index(fields=["user_id", "org_id"],
                                         name="contact_profiles_mine")],
                "constraints": [
                    models.UniqueConstraint(fields=["user_id", "org_id", "apple_uid"],
                                            condition=~models.Q(apple_uid=""),
                                            name="contact_profiles_card"),
                    models.UniqueConstraint(fields=["user_id", "org_id"],
                                            condition=models.Q(is_me=True),
                                            name="contact_profiles_me"),
                ],
            },
        ),
        *[migrations.AddField(model_name="mailalertseen", name=name, field=_text())
          for name in ("thread_id", "chat_id")],
        *[migrations.AddField(model_name="mailalertseen", name=name, field=_flag())
          for name in ("from_petar", "replied")],
        # Gone from the models, kept in the tables. `guidance` never had a
        # default in the database, so it is given one first: without it a row
        # written by this code, which no longer names the column, is refused.
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunSQL(
                'ALTER TABLE "mail_alerts" ALTER COLUMN "guidance" SET DEFAULT \'\';',
                'ALTER TABLE "mail_alerts" ALTER COLUMN "guidance" DROP DEFAULT;')],
            state_operations=[migrations.RemoveField(model_name="mailalert", name="guidance")],
        ),
        migrations.SeparateDatabaseAndState(
            state_operations=[migrations.RemoveField(model_name="mailalertseen", name="own")],
        ),
    ]
