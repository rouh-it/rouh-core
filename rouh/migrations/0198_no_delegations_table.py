"""The separate grants table goes, once 0197 moved every grant into the one permission record.

Its own migration, so the rows 0197 wrote are committed before the table they pointed at is
dropped (PostgreSQL will not alter a table with deferred checks still pending).
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0197_one_permission_record"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="delegateact",
            name="delegation",
        ),
        migrations.DeleteModel(
            name="Delegation",
        ),
    ]
