"""Auto is the Models page's one toggle, Sync a one-time press (`rouh/modeldefaults.py`).

Petar, the evening of 18 October 2026: "Auto is a toggle. Sync is a one time button press."
So the switch is `auto`, and an organisation's choices are one manual set: the changes it
kept over the standard while synced (`tiers`, `uses`) go into its manual set where that set
names nothing, and those two fields go. A use that was on "auto" (the chats' own choice for
an evening) is on Daily; routing them is the standard's now, with Auto on. A tier or use
that was "recommended" was renamed "daily" by 0181.
"""

from django.db import migrations


def forward(apps, schema_editor):
    ModelDefaults = apps.get_model("rouh", "ModelDefaults")
    for row in ModelDefaults.objects.all():
        manual = dict(row.manual or {})
        tiers = dict(manual.get("tiers") or {})
        uses = dict(manual.get("uses") or {})
        for t, v in dict(row.tiers or {}).items():
            tiers.setdefault(t, v)
        for u, v in dict(row.uses or {}).items():
            uses.setdefault(u, v)
        uses = {u: ("daily" if v == "auto" else v) for u, v in uses.items()}
        row.manual = {"tiers": tiers, "uses": uses} if (tiers or uses) else {}
        row.save(update_fields=["manual"])


class Migration(migrations.Migration):

    dependencies = [("rouh", "0184_rouh_pool")]

    operations = [
        migrations.RunPython(forward, migrations.RunPython.noop),
        migrations.RemoveField("modeldefaults", "tiers"),
        migrations.RemoveField("modeldefaults", "uses"),
        migrations.RenameField("modeldefaults", "sync", "auto"),
    ]
