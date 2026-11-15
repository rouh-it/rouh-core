import django.db.models
from django.db import migrations, models


class Migration(migrations.Migration):
    """What this Rouh keeps and runs (task 185): its preset, its own choices over the preset, and
    the limits confirmed for deleting old records (`rouh/lean.py`). A Rouh with no rows behaves as
    its preset, and a Rouh with no preset row as Installed (or Creator, on the Rouh that makes
    releases)."""

    dependencies = [("rouh", "0250_dream_plan")]
    operations = [
        migrations.CreateModel(
            name="LeanState",
            fields=[
                ("org_id", models.TextField(primary_key=True, serialize=False)),
                ("preset", models.TextField()),
                ("changed_by", models.TextField(blank=True, default="")),
                ("updated_at", models.FloatField(default=0)),
                ("swept_at", models.FloatField(default=0)),
            ],
            options={"db_table": "lean_state"},
        ),
        migrations.CreateModel(
            name="LeanChoice",
            fields=[
                ("pk", django.db.models.CompositePrimaryKey("org_id", "item", blank=True, editable=False,
                                                            primary_key=True, serialize=False)),
                ("org_id", models.TextField()),
                ("item", models.TextField()),
                ("mode", models.TextField()),
                ("days", models.IntegerField(blank=True, null=True)),
                ("by", models.TextField(blank=True, default="")),
                ("updated_at", models.FloatField(default=0)),
            ],
            options={"db_table": "lean_choice"},
        ),
        migrations.CreateModel(
            name="LeanApplied",
            fields=[
                ("pk", django.db.models.CompositePrimaryKey("org_id", "item", blank=True, editable=False,
                                                            primary_key=True, serialize=False)),
                ("org_id", models.TextField()),
                ("item", models.TextField()),
                ("mode", models.TextField()),
                ("days", models.IntegerField(blank=True, null=True)),
                ("done_before", models.FloatField(default=0)),
                ("by", models.TextField(blank=True, default="")),
                ("updated_at", models.FloatField(default=0)),
            ],
            options={"db_table": "lean_applied"},
        ),
    ]
