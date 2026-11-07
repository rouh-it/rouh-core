"""The box: what the person keeps from the model, sealed (`rouh/boxes.py`).

Petar, 13 October 2026 (fr_e7f2ebe1c141). One row a box, keyed by organisation and account.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0137_page_source_checks"),
    ]

    operations = [
        migrations.CreateModel(
            name="Box",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("org_id", models.TextField()),
                ("user_id", models.TextField()),
                ("label", models.TextField(blank=True, default="")),
                ("kind", models.TextField(default="secret")),
                ("sealed", models.TextField()),
                ("size", models.IntegerField(default=0)),
                ("made_at", models.FloatField()),
                ("updated_at", models.FloatField()),
            ],
            options={
                "db_table": "boxes",
                "indexes": [models.Index(fields=["org_id", "user_id", "made_at"], name="boxes_whose")],
            },
        ),
    ]
