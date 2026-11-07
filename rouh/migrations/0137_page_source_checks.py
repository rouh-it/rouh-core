"""Sources checked: every footnoted page's sources, read against what the page says they say.

The nightly feature run, night 10, 13 October 2026 (`rouh/source_check.py`, behind its switch
`source_check`). One row a page and owner, keyed by both ids.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0136_notice_page_label"),
    ]

    operations = [
        migrations.CreateModel(
            name="PageSourceCheck",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("user_id", models.TextField()),
                ("org_id", models.TextField()),
                ("rel", models.TextField()),
                ("title", models.TextField(default="")),
                ("fp", models.TextField(default="")),
                ("state", models.TextField(default="checking")),
                ("total", models.IntegerField(default=0)),
                ("sources", models.JSONField(default=list)),
                ("checked_at", models.FloatField()),
            ],
            options={
                "db_table": "page_source_checks",
                "constraints": [models.UniqueConstraint(fields=("org_id", "user_id", "rel"),
                                                        name="page_source_checks_page")],
            },
        ),
    ]
