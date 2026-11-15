import django.db.models
from django.db import migrations, models


class Migration(migrations.Migration):
    """Permission gates (`rouh/gates.py`): the tools switched to "ask me first" on Anatomy,
    Behaviour, Permission gates. Empty by default: no tool is gated."""

    dependencies = [("rouh", "0254_chat_reading")]
    operations = [
        migrations.CreateModel(
            name="PermissionGate",
            fields=[
                ("pk", django.db.models.CompositePrimaryKey("org_id", "tool", blank=True, editable=False,
                                                            primary_key=True, serialize=False)),
                ("org_id", models.TextField()),
                ("tool", models.TextField()),
                ("by", models.TextField(blank=True, default="")),
                ("updated_at", models.FloatField(default=0)),
            ],
            options={"db_table": "permission_gates"},
        ),
    ]
