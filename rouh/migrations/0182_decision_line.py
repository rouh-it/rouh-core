"""A decision's line: what a yes does and what waiting costs (`rouh/decisions.py`, `line_of`).

Petar, 18 October 2026: the Decisions page becomes a short list of lines, each a link to the
item's own page, and each saying only what he needs to tell whether it needs him now: what it
is, what a yes would do, what waiting costs, a few tags, and Rouh's recommendation with its
handle. `line` keeps what the source said of the second and third: {"yes", "wait", "blocks",
"tags", "advice"}. A decision made before this has an empty one until its source is read again.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0181_decision_gate'),
    ]

    operations = [
        migrations.AddField(
            model_name='decision',
            name='line',
            field=models.JSONField(default=dict, db_default={}),
        ),
    ]
