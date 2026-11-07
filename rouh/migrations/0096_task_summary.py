"""A task's summary: what it is, where it stands and what is open, in 50 to 90 words.

Petar, 6 October 2026, by voice, on `workspace/_tasks.md` becoming a view generated from
this database rather than a file written by hand: "yes I would like that. shouldn't we do
it this way?" The paragraph each task had in that file is this column now. It is written
in a file in the task's own folder, as `summary`, and taken in here on every reconcile the way
the status is (`conversations.reconcile`); `rouh/tasklist.py` writes the file out of it.
Empty until the first reconcile after the deploy reads it off the disk.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0095_decisions"),
    ]

    operations = [
        migrations.AddField(
            model_name="task",
            name="summary",
            field=models.TextField(blank=True, default=""),
        ),
    ]
