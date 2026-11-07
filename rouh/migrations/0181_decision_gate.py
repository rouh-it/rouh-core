"""The gate in front of the decisions (`rouh/decision_gate.py`, `models.DecisionGate`).

Petar, 18 October 2026: his decisions list was flooded with questions nobody needed, and even
dismissing them cost him energy. So every question a source asks is judged once before it may
reach him, and this table is what the gate said of each: let through, kept from him, or still
to be judged. It is the log of what was refused, for debugging, and is never drawn for him.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0180_model_outcome_routes"),
    ]

    operations = [
        migrations.CreateModel(
            name="DecisionGate",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("user_id", models.TextField()),
                ("org_id", models.TextField()),
                ("source", models.TextField()),
                ("source_id", models.TextField(blank=True, default="")),
                ("key", models.TextField()),
                ("verdict", models.TextField(default="pending")),
                ("by", models.TextField(blank=True, default="")),
                ("reason", models.TextField(blank=True, default="")),
                ("recommendation", models.TextField(blank=True, default="")),
                ("work", models.TextField(blank=True, default="")),
                ("title", models.TextField(blank=True, default="")),
                ("question", models.TextField(blank=True, default="")),
                ("facts", models.JSONField(default=dict)),
                ("model", models.TextField(blank=True, default="")),
                ("tries", models.IntegerField(default=0)),
                ("retry_at", models.FloatField(blank=True, null=True)),
                ("created_at", models.FloatField()),
                ("judged_at", models.FloatField(blank=True, null=True)),
            ],
            options={
                "db_table": "decision_gate",
                "indexes": [models.Index(fields=["org_id", "user_id", "verdict"],
                                         name="decision_gate_whose")],
                "constraints": [models.UniqueConstraint(
                    fields=("org_id", "user_id", "source", "key"),
                    name="decision_gate_one_per_question")],
            },
        ),
    ]
