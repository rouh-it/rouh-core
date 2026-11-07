"""Two tiers and three modes (`rouh/modeldefaults.py`; Petar, 23 October 2026, card 1842).

The Models page had three tiers, Cheaper, Daily and Best; it has two now, Cheaper and Smart,
and a mode on top of them, Best, Balanced or Saver. Every organisation's own settings move
with it: its Daily tier becomes Smart and its Best tier goes, every use on Daily or Best is
on Smart, the router of 18 October (use "router") is gone, and what is locked stays locked,
under its new name. A use on a model of its own (Custom) is left exactly as it was. What the
last Sync replaced is dropped, since it named tiers that are no more. The mode starts empty,
which is the service's default, Balanced.
"""
from django.db import migrations, models

OLD = {"daily": "smart", "recommended": "smart", "best": "smart"}


def two_tiers(apps, schema_editor):
    ModelDefaults = apps.get_model("rouh", "ModelDefaults")
    for row in ModelDefaults.objects.all():
        manual = row.manual if isinstance(row.manual, dict) else {}
        tiers = dict(manual.get("tiers") or {})
        smart = tiers.get("smart") or tiers.get("daily") or tiers.get("recommended")
        out_t = {}
        if tiers.get("cheaper"):
            out_t["cheaper"] = tiers["cheaper"]
        if smart:
            out_t["smart"] = smart
        uses = {}
        for use, choice in dict(manual.get("uses") or {}).items():
            if use == "router":
                continue
            choice = str(choice or "")
            uses[use] = OLD.get(choice, choice)
        new = dict(manual)
        if tiers or "tiers" in manual:
            new["tiers"] = out_t
        if uses or "uses" in manual:
            new["uses"] = uses
        locked = []
        for item in row.locked or []:
            item = OLD.get(str(item), str(item))
            if item != "router" and item not in locked:
                locked.append(item)
        row.manual, row.locked, row.undo = new, locked, {}
        row.save(update_fields=["manual", "locked", "undo"])


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0209_gene_pool_review'),
    ]

    operations = [
        migrations.AddField(model_name='modeldefaults', name='mode',
                            field=models.TextField(blank=True, default='')),
        migrations.RunPython(two_tiers, migrations.RunPython.noop),
    ]
