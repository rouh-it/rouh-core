"""The feedback board's own settings, one row per organisation.

The first of them is ``autobuild``: whether a feature request written out of a
feedback is given a run by itself. Petar, 23 September 2026 - "give me a
toggle that turns off automatic build. keep converting feedback to features,
but if the toggle is off, don't build them". An organisation with no row has
never moved it, and is on, which is what every board did before this table.

A table of its own rather than a column on ``organisations``, because it is
the board's (`rouh/feedback.py`), and a Rouh rolled back past this migration
goes on writing organisations exactly as it did.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0002_database_rules"),
    ]

    operations = [
        migrations.CreateModel(
            name="FeedbackBoard",
            fields=[
                ("org_id", models.TextField(primary_key=True, serialize=False)),
                ("autobuild", models.BooleanField(default=True)),
                ("changed_by", models.TextField(blank=True, default="")),
                ("changed_at", models.FloatField(blank=True, null=True)),
            ],
            options={
                "db_table": "feedback_board",
            },
        ),
    ]
