"""Trusted contacts get three levels and a picker of tasks, in place of categories.

Petar, 30 September 2026: communication, then access to his tasks (picked by
column, project and task), then using Rouh for themselves (`rouh/trusted.py`).
The four categories this replaces were live for an evening with nobody trusted
yet, so there is nothing to carry over.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0050_trusted_contacts_and_mail_cases"),
    ]

    operations = [
        migrations.RemoveField(model_name="trustedcontact", name="categories"),
        migrations.AddField(model_name="trustedcontact", name="levels",
                            field=models.JSONField(default=list)),
        migrations.AddField(model_name="trustedcontact", name="grants",
                            field=models.JSONField(default=list)),
    ]
