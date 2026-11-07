"""Philips Hue through its cloud (`rouh/hue.py`, `rouh/models/hue.py`).

Petar, 16 October 2026: "can you build the cloud integration". Two new tables: the organisation's
Remote Hue API app, its secret sealed, and each person's Hue connection, its tokens and the
bridge's application key sealed.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0168_slack_task_links"),
    ]

    operations = [
        migrations.CreateModel(
            name="HueApp",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("org_id", models.TextField()),
                ("client_id", models.TextField(blank=True, default="")),
                ("secret_sealed", models.TextField(blank=True, default="")),
                ("secret_last4", models.TextField(blank=True, default="")),
                ("app_id", models.TextField(blank=True, default="")),
                ("saved_by", models.TextField(blank=True, default="")),
                ("saved_at", models.FloatField(default=0)),
            ],
            options={"db_table": "hue_apps"},
        ),
        migrations.AddConstraint(
            model_name="hueapp",
            constraint=models.UniqueConstraint(fields=["org_id"], name="hue_apps_one"),
        ),
        migrations.CreateModel(
            name="HueConnection",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("org_id", models.TextField()),
                ("user_id", models.TextField()),
                ("access_sealed", models.TextField(blank=True, default="")),
                ("access_expires_at", models.FloatField(default=0)),
                ("refresh_sealed", models.TextField(blank=True, default="")),
                ("refresh_expires_at", models.FloatField(default=0)),
                ("key_sealed", models.TextField(blank=True, default="")),
                ("bridge_id", models.TextField(blank=True, default="")),
                ("bridge_name", models.TextField(blank=True, default="")),
                ("connected_at", models.FloatField(default=0)),
                ("refreshed_at", models.FloatField(default=0)),
                ("reached_at", models.FloatField(default=0)),
                ("lapsed_at", models.FloatField(default=0)),
                ("lapsed_said", models.TextField(blank=True, default="")),
                ("made_at", models.FloatField(default=0)),
                ("updated_at", models.FloatField(default=0)),
            ],
            options={"db_table": "hue_connections"},
        ),
        migrations.AddConstraint(
            model_name="hueconnection",
            constraint=models.UniqueConstraint(fields=["org_id", "user_id"], name="hue_connections_one"),
        ),
    ]
