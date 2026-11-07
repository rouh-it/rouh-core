"""Which of Petar's calendars a contact's calendar grant reaches (`grants.calendars_of`).

Petar, 16 October 2026 (fr_6c6d23abe250): "This Grant for calendar needs to be able to work with
multiple calendars ... you pick which calendar specifically you approve." A grant that lifts
committing his time (`grants.LIFTS`) keeps the ids of the calendars ticked on the contact's page.
Null is a grant given before there was a choice, or from a case, and reaches every calendar, as
it did; the page shows those all ticked, and saving it keeps exactly what is ticked.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0160_nightly_refactor'),
    ]

    operations = [
        migrations.AddField(
            model_name='contactgrant',
            name='calendars',
            field=models.JSONField(blank=True, default=None, null=True),
        ),
    ]
