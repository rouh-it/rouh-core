"""The owner's mode switch, Restricted or Unrestricted, its log of flips, and the "What Rouh did"
feed of what ran under Unrestricted (`rouh/unrestricted.py`, 20 November 2026, task 191). Three new
tables; nothing existing is changed.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("rouh", "0265_evolution_guide")]

    operations = [
        migrations.CreateModel(
            name="PermissionMode",
            fields=[
                ("pk", models.CompositePrimaryKey("org_id", "user_id", blank=True, editable=False,
                                                  primary_key=True, serialize=False)),
                ("org_id", models.TextField()),
                ("user_id", models.TextField()),
                ("mode", models.TextField(default="restricted")),
                ("how", models.TextField(blank=True, default="")),
                ("until", models.FloatField(blank=True, null=True)),
                ("set_at", models.FloatField(default=0)),
                ("set_by", models.TextField(blank=True, default="")),
            ],
            options={"db_table": "permission_mode"},
        ),
        migrations.CreateModel(
            name="PermissionModeFlip",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("org_id", models.TextField()),
                ("user_id", models.TextField()),
                ("was", models.TextField()),
                ("now", models.TextField()),
                ("how", models.TextField(blank=True, default="")),
                ("until", models.FloatField(blank=True, null=True)),
                ("at", models.FloatField()),
                ("by", models.TextField(blank=True, default="")),
                ("agent", models.TextField(blank=True, default="")),
            ],
            options={"db_table": "permission_mode_flip",
                     "indexes": [models.Index(fields=["org_id", "user_id", "-at"],
                                              name="mode_flip_whose")]},
        ),
        migrations.CreateModel(
            name="UnrestrictedAction",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("org_id", models.TextField()),
                ("user_id", models.TextField()),
                ("via", models.TextField()),
                ("where", models.TextField(blank=True, default="")),
                ("title", models.TextField(blank=True, default="")),
                ("tool", models.TextField()),
                ("args", models.TextField(blank=True, default="")),
                ("what", models.TextField(blank=True, default="")),
                ("why", models.TextField(blank=True, default="")),
                ("result", models.TextField(blank=True, default="")),
                ("ok", models.BooleanField(default=True)),
                ("undo", models.JSONField(blank=True, default=dict)),
                ("undo_said", models.TextField(blank=True, default="")),
                ("undone_at", models.FloatField(blank=True, null=True)),
                ("undone_said", models.TextField(blank=True, default="")),
                ("at", models.FloatField()),
            ],
            options={"db_table": "unrestricted_action",
                     "indexes": [models.Index(fields=["org_id", "user_id", "-at"],
                                              name="unres_action_whose")]},
        ),
    ]
