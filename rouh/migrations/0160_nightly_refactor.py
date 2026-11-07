"""The nightly code refactoring run's nights (`rouh/nightly_refactor.py`).

Petar, 15 October 2026: a refactoring run every night at 03:00, after the feature run, which
keeps a list of what else to refactor and a list of what was refactored, and lands its
refactors on main without asking him. A night is a row from the moment its time comes, so a
night waiting for the feature run to land outlives the restart that landing's deploy makes.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0159_ask_serves'),
    ]

    operations = [
        migrations.CreateModel(
            name='NightlyRefactorNight',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('user_id', models.TextField()),
                ('org_id', models.TextField()),
                ('number', models.IntegerField()),
                ('run_id', models.TextField(blank=True, default='')),
                ('state', models.TextField(default='waiting')),
                ('why', models.TextField(blank=True, default='')),
                ('started_at', models.FloatField()),
                ('began_at', models.FloatField(blank=True, null=True)),
                ('outcome', models.TextField(blank=True, default='')),
                ('summary', models.TextField(blank=True, default='')),
                ('items', models.JSONField(blank=True, default=list)),
                ('commits', models.JSONField(blank=True, default=list)),
                ('left', models.IntegerField(default=0)),
                ('reported_at', models.FloatField(blank=True, null=True)),
                ('undo_run_id', models.TextField(blank=True, default='')),
                ('undone_at', models.FloatField(blank=True, null=True)),
            ],
            options={
                'db_table': 'nightly_refactor_nights',
                'constraints': [models.UniqueConstraint(fields=('org_id', 'user_id', 'number'), name='nightly_refactor_night_number')],
            },
        ),
    ]
