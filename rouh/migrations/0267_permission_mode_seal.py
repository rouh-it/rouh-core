"""The seal on the owner's mode (task 191, `rouh/run_access.py`): a column, and a seal for every row
there is now, so a mode the owner already switched is not taken for one written behind their back."""
from django.db import migrations, models


def seal_rows(apps, schema_editor):
    from rouh import run_access

    PermissionMode = apps.get_model("rouh", "PermissionMode")
    for row in PermissionMode.objects.all():
        PermissionMode.objects.filter(org_id=row.org_id, user_id=row.user_id).update(
            seal=run_access.seal(row.org_id, row.user_id, row.mode, row.how, row.until, row.set_at))


class Migration(migrations.Migration):
    dependencies = [("rouh", "0266_permission_mode")]

    operations = [
        migrations.AddField(model_name="permissionmode", name="seal",
                            field=models.TextField(blank=True, default="")),
        migrations.RunPython(seal_rows, migrations.RunPython.noop),
    ]
