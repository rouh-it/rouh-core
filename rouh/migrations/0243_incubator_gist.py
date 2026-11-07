"""The Incubator's summaries (`rouh/incubator_gist.py`, 7 November 2026): each idea keeps what Rouh wrote
to get a reader up to speed - one plain line, the problem, who it helps, what it looks like in use, its
vision, its size and the ideas it looks like - written once and kept, never on every view.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0242_trial_tester_paused'),
    ]

    operations = [
        migrations.AddField(model_name='incubatoridea', name='gist',
                            field=models.JSONField(blank=True, default=dict)),
    ]
