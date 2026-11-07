"""Mail alerts: new mail in the person's Gmail inbox, judged, and sent to Telegram.

Petar, 24 September 2026 (fr_2c8ef5688989): Rouh should learn about new mail
the moment it arrives, read it, decide whether it is worth his time, and send a
short Telegram note only when it is. Gmail tells Rouh through Google Cloud
Pub/Sub, which posts to an address on this server (`rouh/mail_alerts.py`).

Three tables. `gmail_push` is an organisation's: the Pub/Sub topic in its own
Google Cloud project and the token in the address Google posts to, sealed.
`mail_alerts` is a person's: on or off, the Gmail watch, and the history id
reading has got to. `mail_alert_seen` is every new message read for them and
what was made of it, which is what keeps one message from being judged or sent
twice and what Settings shows under Lately.

Nothing is in any of them until somebody turns alerts on, so a Rouh rolled back
past this migration loses nothing it had before.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0011_record_without_notes"),
    ]

    operations = [
        migrations.CreateModel(
            name="GmailPush",
            fields=[
                ("org_id", models.TextField(primary_key=True, serialize=False)),
                ("topic", models.TextField(blank=True, default="")),
                ("token_hash", models.TextField(unique=True)),
                ("token_sealed", models.TextField()),
                ("updated_at", models.FloatField(default=0)),
                ("updated_by", models.TextField(blank=True, default="")),
                ("last_push_at", models.FloatField(default=0)),
            ],
            options={
                "db_table": "gmail_push",
            },
        ),
        migrations.CreateModel(
            name="MailAlert",
            fields=[
                ("user_id", models.TextField(primary_key=True, serialize=False)),
                ("org_id", models.TextField()),
                ("enabled", models.BooleanField(default=False)),
                ("mailbox", models.TextField(blank=True, default="")),
                ("history_id", models.TextField(blank=True, default="")),
                ("watch_topic", models.TextField(blank=True, default="")),
                ("watch_expires_at", models.FloatField(default=0)),
                ("watch_renewed_at", models.FloatField(default=0)),
                ("trouble", models.TextField(blank=True, default="")),
                ("last_push_at", models.FloatField(default=0)),
                ("last_checked_at", models.FloatField(default=0)),
                ("guidance", models.TextField(blank=True, default="")),
                ("updated_at", models.FloatField(default=0)),
            ],
            options={
                "db_table": "mail_alerts",
                "indexes": [models.Index(fields=["org_id", "enabled"], name="mail_alerts_org")],
            },
        ),
        migrations.CreateModel(
            name="MailAlertSeen",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("user_id", models.TextField()),
                ("org_id", models.TextField()),
                ("message_id", models.TextField()),
                ("at", models.FloatField()),
                ("sender", models.TextField(blank=True, default="")),
                ("subject", models.TextField(blank=True, default="")),
                ("worth", models.BooleanField(default=False)),
                ("why", models.TextField(blank=True, default="")),
                ("sent", models.BooleanField(default=False)),
                ("error", models.TextField(blank=True, default="")),
            ],
            options={
                "db_table": "mail_alert_seen",
                "indexes": [models.Index(fields=["user_id", "org_id", "at"],
                                         name="mail_alert_seen_mine")],
                "constraints": [
                    models.UniqueConstraint(fields=("user_id", "message_id"),
                                            name="mail_alert_seen_once"),
                ],
            },
        ),
    ]
