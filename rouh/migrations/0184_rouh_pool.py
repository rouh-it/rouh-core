"""The Rouh pool: sync and share are one switch, and double calls are kept as conclusions
(`rouh/modeldefaults.py`, `rouh/llm.py`), Petar, the evening of 18 October 2026: "sync and
share should be one toggle."

An organisation that had switched sharing off is out of the pool, as it had asked for
nothing to be sent; one that had both on is in it. Then `share_outcomes` goes.
"""

from django.db import migrations, models


def forward(apps, schema_editor):
    ModelDefaults = apps.get_model("rouh", "ModelDefaults")
    ModelDefaults.objects.filter(share_outcomes=False).update(sync=False)


def backward(apps, schema_editor):
    ModelDefaults = apps.get_model("rouh", "ModelDefaults")
    ModelDefaults.objects.filter(sync=False).update(share_outcomes=False)


class Migration(migrations.Migration):

    dependencies = [("rouh", "0183_model_sync_and_locks")]

    operations = [
        migrations.RunPython(forward, backward),
        migrations.RemoveField("modeldefaults", "share_outcomes"),
        migrations.CreateModel(
            name="ModelDouble",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("org_id", models.TextField()),
                ("use", models.TextField()),
                ("first_model", models.TextField()),
                ("first_effort", models.TextField(blank=True, default="")),
                ("second_model", models.TextField()),
                ("second_effort", models.TextField(blank=True, default="")),
                ("winner", models.TextField()),
                ("first_cost_usd", models.FloatField(blank=True, null=True)),
                ("second_cost_usd", models.FloatField(blank=True, null=True)),
                ("judge_cost_usd", models.FloatField(blank=True, null=True)),
                ("first_ms", models.IntegerField(blank=True, null=True)),
                ("second_ms", models.IntegerField(blank=True, null=True)),
                ("at", models.FloatField()),
                ("counted_on", models.TextField(blank=True, default="")),
            ],
            options={"db_table": "model_double",
                     "indexes": [models.Index(fields=["org_id", "at"], name="model_double_org_at")]},
        ),
    ]
