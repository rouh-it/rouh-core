"""The Incubator's scores (`rouh/incubator_score.py`, 4 November 2026): each idea keeps the parts of its
score, Rouh's suggested stars and the person's own, and when it was scored. The score itself is worked
out from the parts and never stored.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0229_quiet_undo_points'),
    ]

    operations = [
        migrations.AddField(model_name='incubatoridea', name='score_parts',
                            field=models.JSONField(blank=True, default=dict)),
        migrations.AddField(model_name='incubatoridea', name='stars_suggested',
                            field=models.IntegerField(blank=True, null=True)),
        migrations.AddField(model_name='incubatoridea', name='stars_mine',
                            field=models.IntegerField(blank=True, null=True)),
        migrations.AddField(model_name='incubatoridea', name='scored_at',
                            field=models.FloatField(blank=True, null=True)),
        migrations.AddField(model_name='incubatoridea', name='scored_model',
                            field=models.TextField(blank=True, default='')),
    ]
