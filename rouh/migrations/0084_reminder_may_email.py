"""Email a scheduled item may send without asking, approved in advance (`reminders.Permit`).

Petar, 5 October 2026: "Please set it up so you send the email, no approval
from me." A scheduled item can carry the addresses its unattended turn may
email from Rouh's own inbox, how many sends that covers, and the words that
granted it. Every column has a default the database keeps, so a Rouh rolled
back past this still writes rows the table takes.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("rouh", "0083_synapse_calendar_sync")]

    operations = [
        migrations.AddField(model_name="reminder", name="may_email",
                            field=models.TextField(blank=True, db_default="", default="")),
        migrations.AddField(model_name="reminder", name="may_email_times",
                            field=models.IntegerField(db_default=0, default=0)),
        migrations.AddField(model_name="reminder", name="may_email_sent",
                            field=models.IntegerField(db_default=0, default=0)),
        migrations.AddField(model_name="reminder", name="may_email_words",
                            field=models.TextField(blank=True, db_default="", default="")),
        migrations.AddField(model_name="reminder", name="may_email_at",
                            field=models.FloatField(blank=True, null=True)),
    ]
