"""The morning brief, one row per person per day (`rouh/morning_brief.py`).

Petar, 29 September 2026 (fr_c01a16e51a05): "Make a morning brief please."
The table starts empty, so a Rouh rolled back past this migration loses
nothing it had before.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0041_subtask_note"),
    ]

    operations = [
        migrations.CreateModel(
            name="MorningBrief",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("user_id", models.TextField()),
                ("org_id", models.TextField()),
                ("day", models.TextField()),
                ("made_at", models.FloatField()),
                ("data", models.TextField()),
                ("sent_at", models.FloatField(blank=True, null=True)),
            ],
            options={
                "db_table": "morning_briefs",
                "constraints": [models.UniqueConstraint(fields=("org_id", "user_id", "day"),
                                                        name="morning_briefs_one_a_day")],
            },
        ),
    ]
