"""The email a scheduled item could send approved in advance, gone again (5 October 2026).

Petar changed course the same day: a turn nobody is watching started by time
may now do anything but three groups of things (`rouh/protected.py`), so no
item needs an approval of its own. The columns 0084 added are kept in the
table, out of the model, with the defaults the database fills in, so a Rouh
rolled back to 0084's code still reads and writes rows.
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [("rouh", "0084_reminder_may_email")]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveField(model_name="reminder", name=name)
                for name in ("may_email", "may_email_times", "may_email_sent",
                             "may_email_words", "may_email_at")
            ],
            database_operations=[],
        ),
    ]
