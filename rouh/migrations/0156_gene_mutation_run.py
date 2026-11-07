"""A mutation request's own run (`evolution.start_mutation`).

Petar, 15 October 2026 (fr_680c7262913d): "I definitely don't want to wait until next night.
Mutation should start right away". A mutation he asks for starts its own run at once, and the
request keeps that run's id, so the run's tools know which request it builds.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0155_paid_services'),
    ]

    operations = [
        migrations.AddField(
            model_name='genemutation',
            name='run_id',
            field=models.TextField(blank=True, default=''),
        ),
    ]
