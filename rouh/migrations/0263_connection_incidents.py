"""Every refusal of a connection's credentials, kept as it happened, and a connection's run of them.

Petar, 19 November 2026: iCloud contacts were marked as needing a new password after one 401,
and nothing could say why afterwards. `connection_incidents` keeps the evidence of each refusal
(`rouh/connection_incidents.py`); `connection_trouble` is one row while refusals go on, so a
connection is marked dead only once they persist across two sync cycles.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("rouh", "0262_three_run_policies")]

    operations = [
        migrations.CreateModel(
            name="ConnectionIncident",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("user_id", models.TextField()),
                ("org_id", models.TextField()),
                ("connection", models.TextField()),
                ("at", models.FloatField()),
                ("part", models.TextField(blank=True, default="")),
                ("method", models.TextField(blank=True, default="")),
                ("host", models.TextField(blank=True, default="")),
                ("path", models.TextField(blank=True, default="")),
                ("status", models.IntegerField(default=0)),
                ("headers", models.JSONField(blank=True, default=dict)),
                ("body", models.TextField(blank=True, default="")),
                ("outcome", models.TextField(blank=True, default="")),
                ("note", models.TextField(blank=True, default="")),
            ],
            options={
                "db_table": "connection_incidents",
                "indexes": [models.Index(fields=["user_id", "org_id", "connection", "-at"],
                                         name="connection_incidents_whose")],
            },
        ),
        migrations.CreateModel(
            name="ConnectionTrouble",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("user_id", models.TextField()),
                ("org_id", models.TextField()),
                ("connection", models.TextField()),
                ("first_at", models.FloatField()),
                ("last_at", models.FloatField()),
                ("failures", models.IntegerField(default=1)),
                ("first_part", models.TextField(blank=True, default="")),
                ("last_part", models.TextField(blank=True, default="")),
            ],
            options={
                "db_table": "connection_trouble",
                "constraints": [models.UniqueConstraint(fields=["user_id", "org_id", "connection"],
                                                        name="connection_trouble_one")],
            },
        ),
    ]
