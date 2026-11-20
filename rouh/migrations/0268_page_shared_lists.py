"""One list a page shares among everybody who may change it (`rouh/sharedlist.py`): Petar, 20
November 2026, task 149, "my brother sees his words, I see mine. this needs to share a common db".
A new table only; `page_states` is not touched, so each person's own list stays as it was."""
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("rouh", "0267_permission_mode_seal")]

    operations = [
        migrations.CreateModel(
            name="PageSharedList",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("org_id", models.TextField()),
                ("rel", models.TextField()),
                ("key", models.TextField()),
                ("items", models.JSONField(default=list)),
                ("answers", models.JSONField(default=dict)),
                ("removed", models.JSONField(default=list)),
                ("log", models.JSONField(default=list)),
                ("version", models.BigIntegerField(default=0)),
                ("updated_at", models.FloatField()),
            ],
            options={
                "db_table": "page_shared_lists",
                "constraints": [models.UniqueConstraint(fields=("org_id", "rel", "key"),
                                                        name="page_shared_lists_one")],
            },
        ),
    ]
