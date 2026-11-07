"""The Gene Pool's incoming setting (`rouh/genepool.py`; task 141, step 141-15): whether the Pool's genes
may come into this Rouh, beside 141-09's outgoing one.

Petar, 25 October 2026: "control outgoing genes and control incoming genes ... By default both of those
will be manual or in other words not exchanging, but a person can choose something else." Manual is
where every Rouh starts.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0214_job_requests'),
    ]

    operations = [
        migrations.AddField(model_name='poolmembership', name='incoming_mode',
                            field=models.TextField(blank=True, default='manual')),
        migrations.AddField(model_name='poolmembership', name='incoming_mode_by',
                            field=models.TextField(blank=True, default='')),
        migrations.AddField(model_name='poolmembership', name='incoming_mode_at',
                            field=models.FloatField(blank=True, null=True)),
    ]
