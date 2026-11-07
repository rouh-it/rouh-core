"""Two tasks that were in two places, taken back to one, once.

Petar, 24 September 2026: "dedup the other tasks too". Three task numbers were
in two folders on the installation it was written for, all for one reason:
Rouh writes a task's folder into this machine's checkout and never commits it,
so a job working from main cannot see it and writes its own. This was two of
the three. The third, task 51, is two different pieces of work under one
number, and one of them is given a number of its own in `0007`.

On that installation, for two named tasks, it removed the empty copy of each
(a folder holding only its id file and an empty list of steps), pointed
the task's row at the copy with the work in it, and gave whatever the stray row
owned to the step it always was - each only when everything was exactly as it
was found on 24 September 2026. Nothing with work in it was removed.

Those tasks are that owner's own, and live only in that installation's
database and workspace; anywhere else there was never anything for it to
find, so it does nothing.
"""
from django.db import migrations


def forward(apps, schema_editor):
    """Nothing to do: the two tasks it tidied belong to the installation they were on."""


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0005_remove_task_58_ready_card"),
    ]

    operations = [
        migrations.RunPython(forward, migrations.RunPython.noop),
    ]
