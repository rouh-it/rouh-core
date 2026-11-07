"""The Gene Pool's review gate (`rouh/genepool.py`; task 141, step 141-09): what a person approved to
send for each node of the gene log, their edits to it, and how genes reach the review list.

Petar, 22 October 2026: "I would like to see those genes before they go to the pool ... options for
automatically uploading everything or preselecting items." Manual is where every Rouh starts.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0208_synapse_person_change'),
    ]

    operations = [
        migrations.AddField(model_name='geneloggene', name='approved_sha',
                            field=models.TextField(blank=True, default='')),
        migrations.AddField(model_name='geneloggene', name='approved_by',
                            field=models.TextField(blank=True, default='')),
        migrations.AddField(model_name='geneloggene', name='approved_at',
                            field=models.FloatField(blank=True, null=True)),
        migrations.AddField(model_name='geneloggene', name='pool_edit',
                            field=models.JSONField(blank=True, default=dict)),
        migrations.AddField(model_name='poolmembership', name='share_mode',
                            field=models.TextField(blank=True, default='manual')),
        migrations.AddField(model_name='poolmembership', name='share_mode_by',
                            field=models.TextField(blank=True, default='')),
        migrations.AddField(model_name='poolmembership', name='share_mode_at',
                            field=models.FloatField(blank=True, null=True)),
    ]
