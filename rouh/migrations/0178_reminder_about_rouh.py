"""Whether a Clockwork item is about Rouh itself (`Reminder.about_rouh`).

Petar, 18 October 2026 (fr_5db528986cf6): "The morning routine gets too busy with those nightly
runs of new genes and refactoring. I want to see only the stuff that is not Rouh and not regular."
So every item says whether it is about Rouh, and the morning brief leaves out those that are and
repeat (`morning_brief._reminders`). Rouh's own server jobs - the nightly feature, refactoring,
Synapse and dreaming runs, the Control Room's names - are about Rouh by what they are, so the rows
already there are marked so.
"""

from django.db import migrations, models


def server_jobs_are_rouh(apps, schema_editor):
    Reminder = apps.get_model("rouh", "Reminder")
    Reminder.objects.filter(kind="server").update(about_rouh=True)


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0177_card_charge_pressed"),
    ]

    operations = [
        migrations.AddField(
            model_name="reminder",
            name="about_rouh",
            field=models.BooleanField(db_default=False, default=False),
        ),
        migrations.RunPython(server_jobs_are_rouh, migrations.RunPython.noop),
    ]
