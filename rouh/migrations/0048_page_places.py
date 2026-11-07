"""Which page each shared path is, by the object it sits in (`rouh/pageplaces.py`).

A trusted contact's three shared logo pages stopped opening on 29 September 2026 because
their folders moved and every row naming them kept the old path. One row per
path any share, comment or Ask AI row names: the id of the object the page is
in and where inside it. Rouh fills it in by itself as it starts. A Rouh rolled
back past this migration loses only the table.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0047_birthday_links"),
    ]

    operations = [
        migrations.CreateModel(
            name="PagePlace",
            fields=[
                ("rel", models.TextField(primary_key=True, serialize=False)),
                ("object_id", models.TextField()),
                ("sub", models.TextField()),
                ("seen_at", models.FloatField()),
            ],
            options={
                "db_table": "page_places",
                "indexes": [models.Index(fields=["object_id"], name="page_places_object")],
            },
        ),
    ]
