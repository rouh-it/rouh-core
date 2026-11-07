"""A Dreame robot vacuum through the Dreamehome cloud (`rouh/dreame.py`, `rouh/models/dreame.py`).

Petar, 17 October 2026: "I have robot for cleaning, can we connect that too?" One new table: each
person's Dreamehome connection, its password and tokens sealed.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0169_hue"),
    ]

    operations = [
        migrations.CreateModel(
            name="DreameConnection",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("org_id", models.TextField()),
                ("user_id", models.TextField()),
                ("email", models.TextField(blank=True, default="")),
                ("password_sealed", models.TextField(blank=True, default="")),
                ("region", models.TextField(blank=True, default="")),
                ("access_sealed", models.TextField(blank=True, default="")),
                ("access_expires_at", models.FloatField(default=0)),
                ("refresh_sealed", models.TextField(blank=True, default="")),
                ("tenant_id", models.TextField(blank=True, default="")),
                ("did", models.TextField(blank=True, default="")),
                ("model", models.TextField(blank=True, default="")),
                ("robot_name", models.TextField(blank=True, default="")),
                ("bind_domain", models.TextField(blank=True, default="")),
                ("master_uid", models.TextField(blank=True, default="")),
                ("rooms_json", models.TextField(blank=True, default="")),
                ("rooms_at", models.FloatField(default=0)),
                ("connected_at", models.FloatField(default=0)),
                ("reached_at", models.FloatField(default=0)),
                ("lapsed_at", models.FloatField(default=0)),
                ("lapsed_said", models.TextField(blank=True, default="")),
                ("made_at", models.FloatField(default=0)),
                ("updated_at", models.FloatField(default=0)),
            ],
            options={"db_table": "dreame_connections"},
        ),
        migrations.AddConstraint(
            model_name="dreameconnection",
            constraint=models.UniqueConstraint(fields=["org_id", "user_id"], name="dreame_connections_one"),
        ),
    ]
