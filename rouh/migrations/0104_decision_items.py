"""A decision may hold many small ones, answered together or one by one (`rouh/decisions.py`).

Petar, 8 October 2026, by voice: "Decisions is overflowing, needs a fix." 142 of the 157
questions waiting on him were one night of Synapse's dreaming, each change its own decision.
Since then a night's changes of one kind are one decision, and the changes are its `items`:
[{"id", "label", "text", "href", "detail", "why", "sides"}], each answered with the
decision's own options, all at once or item by item.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0103_decision_handles'),
    ]

    operations = [
        migrations.AddField(
            model_name='decision',
            name='items',
            field=models.JSONField(default=list, db_default=[]),
        ),
    ]
