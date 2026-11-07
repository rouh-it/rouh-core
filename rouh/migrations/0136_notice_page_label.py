"""A finished run's page button says Page on the notices already sent, as on every new one.

Petar, 13 October 2026 (fr_fab4f066ea28): "For the notifications, now there is a button visual
explainer. Can you name it Page". A notice keeps the words of its buttons (`Notice.links`), so
the new word in `run_report.LABELS` reaches only notices said after it; this gives it to the ones
before, which are those of the day the buttons came in (0135). Where they lead is not touched.
"""
from django.db import migrations

OLD, NEW = "Visual explainer", "Page"
OLD_TITLE, NEW_TITLE = "Open the visual explainer it made", "Open the page it made"


def relabel(apps, schema_editor):
    Notice = apps.get_model("rouh", "Notice")
    for row in Notice.objects.exclude(links=[]).only("id", "links").iterator():
        links = list(row.links or [])
        changed = False
        for link in links:
            if isinstance(link, dict) and link.get("to") == "visual":
                if link.get("label") == OLD:
                    link["label"] = NEW
                    changed = True
                if link.get("title") == OLD_TITLE:
                    link["title"] = NEW_TITLE
                    changed = True
        if changed:
            Notice.objects.filter(pk=row.pk).update(links=links)


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0135_notice_links"),
    ]

    operations = [
        migrations.RunPython(relabel, migrations.RunPython.noop),
    ]
