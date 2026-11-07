"""Auto per box of the Models page, and Undo for a Sync (`rouh/modeldefaults.py`).

Petar, the evening of 18 October 2026: an Auto toggle right of the title in each model
box, the tiers' and Each use's, each independent. So the one `auto` becomes
`auto_tiers` and `auto_uses`, both what it was, and `undo` keeps what the last Sync or
Reset replaced until the next change. A use still on "auto" in the manual set is Daily.
"""

from django.db import migrations, models


def forward(apps, schema_editor):
    ModelDefaults = apps.get_model("rouh", "ModelDefaults")
    for row in ModelDefaults.objects.all():
        row.auto_tiers = row.auto_uses = bool(row.auto)
        manual = dict(row.manual or {})
        if manual.get("uses"):
            manual["uses"] = {u: ("daily" if v == "auto" else v) for u, v in manual["uses"].items()}
        row.manual = manual
        row.save(update_fields=["auto_tiers", "auto_uses", "manual"])


class Migration(migrations.Migration):

    dependencies = [("rouh", "0185_models_auto")]

    operations = [
        migrations.AddField("modeldefaults", "auto_tiers", models.BooleanField(default=True)),
        migrations.AddField("modeldefaults", "auto_uses", models.BooleanField(default=True)),
        migrations.AddField("modeldefaults", "undo", models.JSONField(blank=True, default=dict)),
        migrations.RunPython(forward, migrations.RunPython.noop),
        migrations.RemoveField("modeldefaults", "auto"),
    ]
