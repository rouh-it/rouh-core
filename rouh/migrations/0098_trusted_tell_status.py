"""Whether a trusted contact may be told where their own requests stand (`trusted.STATUS_OPTION`).

Petar, 6 October 2026: a per-contact option, off by default, so that a trusted
contact who asks whether something of theirs is waiting for the owner, stopped,
approved or done is answered at once, from the real state of their own cases
and approvals (`mail_cases.status_answer`).

On the installation it was written for, the owner asked for it to be on for one
contact, found by exactly that name, without moving that contact's revision.
That choice lives only in that installation's database; the option is off for
everybody else, so the seed does nothing.
"""
from django.db import migrations, models


def seed(apps, schema_editor):
    """Nothing to do: the option is the owner's to turn on, per contact."""


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0097_task_status_in_the_database'),
    ]

    operations = [
        migrations.AddField(
            model_name='trustedcontact',
            name='tell_status',
            field=models.BooleanField(default=False, db_default=False),
        ),
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
