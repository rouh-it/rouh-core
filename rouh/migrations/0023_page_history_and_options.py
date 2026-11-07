"""A page's history of changes, and the changes kept as options.

Petar, 24 September 2026 (fr_b91369ea7ba2): "whenever someone makes a change on
the website, I want a history of every change, including who made it and
when... for every change, I have to decide whether I want to keep it in the
options."

- `askai_edits.page_org_id`: whose page a change was made to. A guest's own
  rows are kept under `guests`, so without it the owner's history of a page
  could not find the changes a guest made to it. Filled in here for every row
  already there: the owner's own organisation for their changes and a link
  visitor's, and the sharing owner's for a guest's.
- `askai_edits.kind`, `keep` and `parts`: whether a change was Ask AI's or a
  default being picked, whether the owner kept it as an option, and the
  elements it changed. Every row already there is an Ask AI change nobody has
  been asked about yet, with no parts, so none of them can become an option.
- `page_options`: the changes kept as options (`rouh/pagehistory.py`).

On the way down the table and the four columns simply go.

It was written as 0022 and renumbered before it landed: comments pinned to a
page reached main as 0022 while it was being built, and two leaves in one app
is a graph Django refuses to migrate.
"""
from django.db import migrations, models


def fill_page_org(apps, schema_editor):
    AskEdit = apps.get_model("rouh", "AskEdit")
    PageGuest = apps.get_model("rouh", "PageGuest")
    for row in AskEdit.objects.filter(page_org_id="").only("id", "org_id", "user_id", "doc"):
        org = row.org_id
        if org == "guests":
            share = (PageGuest.objects.filter(guest_id=row.user_id, rel=row.doc)
                     .values("org_id").first())
            org = share["org_id"] if share else ""
        if org:
            AskEdit.objects.filter(id=row.id).update(page_org_id=org)


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0022_page_comments"),
    ]

    operations = [
        migrations.AddField(
            model_name="askedit",
            name="page_org_id",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="askedit",
            name="kind",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="askedit",
            name="keep",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="askedit",
            name="parts",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddIndex(
            model_name="askedit",
            index=models.Index(fields=["page_org_id", "doc", "-id"], name="askai_edits_history"),
        ),
        migrations.RunPython(fill_page_org, migrations.RunPython.noop),
        migrations.CreateModel(
            name="PageOption",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("org_id", models.TextField()),
                ("doc", models.TextField()),
                ("edit_id", models.BigIntegerField()),
                ("parts", models.TextField()),
                ("alts", models.TextField()),
                ("chosen", models.IntegerField(default=0)),
                ("chosen_by", models.TextField(blank=True, default="")),
                ("chosen_at", models.FloatField(blank=True, null=True)),
                ("created_by", models.TextField()),
                ("created_at", models.FloatField()),
                ("removed_by", models.TextField(blank=True, default="")),
                ("removed_at", models.FloatField(blank=True, null=True)),
            ],
            options={
                "db_table": "page_options",
                "indexes": [models.Index(fields=["org_id", "doc", "id"],
                                         name="page_options_page")],
            },
        ),
    ]
