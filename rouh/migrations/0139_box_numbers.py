"""Boxes get numbers, and remember when Rouh was asked to open one (`rouh/boxes.py`).

Petar, 13 October 2026: "they should have identification, maybe numbers so that I can tell the
LLM which box to open when needed". Each person's boxes are numbered from 1 in the order they
were made, the boxes already kept included.
"""
from django.db import migrations, models


def number_them(apps, schema_editor):
    Box = apps.get_model("rouh", "Box")
    counts: dict[tuple[str, str], int] = {}
    for b in Box.objects.order_by("made_at", "id"):
        key = (b.org_id, b.user_id)
        counts[key] = counts.get(key, 0) + 1
        b.number = counts[key]
        b.save(update_fields=["number"])


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0138_boxes"),
    ]

    operations = [
        migrations.AddField(model_name="box", name="number", field=models.IntegerField(default=0)),
        migrations.AddField(model_name="box", name="given_at", field=models.FloatField(blank=True, null=True)),
        migrations.AddField(model_name="box", name="given_chat",
                            field=models.TextField(blank=True, default="")),
        migrations.RunPython(number_them, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="box",
            constraint=models.UniqueConstraint(fields=("org_id", "user_id", "number"), name="boxes_number"),
        ),
    ]
