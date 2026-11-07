"""A title for every grant: one line in plain words on what it lets Rouh do for the contact.

Petar, 11 October 2026, on a trusted contact's case (decision x452): a grant has four sets of
words, its canonical name, a title, a description and its prompt, and the case page shows the
title under the name, with the description behind an information icon. The grants every
organisation was seeded with get the titles written for them (`grants.SEED`); any other grant
gets its description's first sentence, which the owner can change on the Grants page. Each grant's
versions are left as they were: the title is new, not a change to them.
"""
from django.db import migrations, models


def titles(apps, schema_editor):
    from rouh.grants import seed_title, title_from

    Grant = apps.get_model("rouh", "Grant")
    for row in Grant.objects.filter(title=""):
        row.title = seed_title(row.key) or title_from(row.description) or row.name
        row.save(update_fields=["title"])


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0118_notice_deployed"),
    ]

    operations = [
        migrations.AddField(
            model_name="grant",
            name="title",
            field=models.TextField(blank=True, db_default="", default=""),
        ),
        migrations.AddField(
            model_name="grantversion",
            name="title",
            field=models.TextField(blank=True, db_default="", default=""),
        ),
        migrations.RunPython(titles, migrations.RunPython.noop),
    ]
