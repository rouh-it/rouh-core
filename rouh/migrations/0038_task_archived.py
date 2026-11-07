"""A task archived rather than deleted.

Petar, 29 September 2026 (fr_08e097dbe815): "I think I need an archive on the
task browser." An archived task leaves the live list and is kept, whole, in
the task browser's Archive, where it can be searched and brought back. The
moment it was archived is the mark, and a subtask archived with the task above
it carries the same moment (`rouh/archiving.py`). Every task before this one is
live, which is what NULL says.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0037_petars_mail_signatures"),
    ]

    operations = [
        migrations.AddField(
            model_name="task",
            name="archived_at",
            field=models.FloatField(blank=True, null=True),
        ),
    ]
