"""The files the person uploads, indexed by the words in them.

Petar, 24 September 2026: "the files I give it are not searchable. The uploads
that is." Every file sent in a chat or added to a project has its words read
out of it as Markdown, kept beside it, and indexed here, so the search box finds
the file by what it says and opens the file itself (`rouh/uploads.py`).

Derived: the table starts empty, and Rouh fills it on its first start from the
files already on disk, so a Rouh rolled back past this migration loses nothing
it had before.
"""
import django.contrib.postgres.indexes
import django.contrib.postgres.search
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0012_mail_alerts"),
    ]

    operations = [
        migrations.CreateModel(
            name="UploadedFile",
            fields=[
                ("pk", models.CompositePrimaryKey("session", "att_id", blank=True, editable=False,
                                                  primary_key=True, serialize=False)),
                ("session", models.TextField()),
                ("att_id", models.TextField()),
                ("owner_type", models.TextField()),
                ("owner_id", models.TextField()),
                ("name", models.TextField()),
                ("media_type", models.TextField(blank=True, default="")),
                ("kind", models.TextField(default="file")),
                ("size", models.BigIntegerField(default=0)),
                ("uploaded_at", models.FloatField()),
                ("body", models.TextField(blank=True, default="")),
                ("indexed_at", models.FloatField()),
                ("search", models.GeneratedField(
                    db_persist=True,
                    expression=django.contrib.postgres.search.SearchVector(
                        models.Func(models.F("body"), models.Value("[^[:alnum:]]+"),
                                    models.Value(" "), models.Value("g"),
                                    function="regexp_replace",
                                    output_field=models.TextField()),
                        config="simple"),
                    output_field=django.contrib.postgres.search.SearchVectorField())),
            ],
            options={
                "db_table": "uploaded_file",
                "indexes": [
                    models.Index(fields=["owner_type", "owner_id"], name="uploaded_file_owner"),
                    django.contrib.postgres.indexes.GinIndex(fields=["search"],
                                                             name="uploaded_file_search"),
                ],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("owner_type__in", ("chat", "project"))),
                        name="uploaded_file_owner_known"),
                ],
            },
        ),
    ]
