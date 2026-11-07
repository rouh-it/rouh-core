"""One organisation's default model and reasoning, and General's.

Petar, 27 September 2026: "Put a default model and default reasoning somewhere
in settings (and I should have a list to choose from) and then whatever is set
there will be default in db for chats, feedback etc. ... another such setting
also is needed for the general chat separately." `rouh/modeldefaults.py` reads
and writes it; no row is this install's own defaults, so nothing moves until
somebody picks something.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0034_telegram_fork_topics"),
    ]

    operations = [
        migrations.CreateModel(
            name="ModelDefaults",
            fields=[
                ("org_id", models.TextField(primary_key=True, serialize=False)),
                ("default_model", models.TextField(blank=True, default="")),
                ("default_effort", models.TextField(blank=True, default="")),
                ("general_model", models.TextField(blank=True, default="")),
                ("general_effort", models.TextField(blank=True, default="")),
                ("changed_by", models.TextField(blank=True, default="")),
                ("changed_at", models.FloatField(blank=True, null=True)),
            ],
            options={"db_table": "model_defaults"},
        ),
    ]
