"""The Incubator (`rouh/incubator.py`, 3 November 2026): one list of ideas for Rouh's new genes and
mutations, with the history of every change, in place of task 166's Gene Nursery file.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0226_rouh_land'),
    ]

    operations = [
        migrations.CreateModel(
            name='IncubatorEvent',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('org_id', models.TextField()),
                ('user_id', models.TextField()),
                ('idea_id', models.BigIntegerField()),
                ('at', models.FloatField()),
                ('by', models.TextField(blank=True, default='')),
                ('what', models.TextField()),
                ('before', models.JSONField(blank=True, default=dict)),
                ('after', models.JSONField(blank=True, default=dict)),
                ('note', models.TextField(blank=True, default='')),
            ],
            options={
                'db_table': 'incubator_events',
                'indexes': [models.Index(fields=['org_id', 'user_id', 'idea_id', 'at'], name='incubator_event_idea')],
            },
        ),
        migrations.CreateModel(
            name='IncubatorIdea',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('org_id', models.TextField()),
                ('user_id', models.TextField()),
                ('number', models.IntegerField()),
                ('title', models.TextField()),
                ('kind', models.TextField(blank=True, default='')),
                ('gene', models.TextField(blank=True, default='')),
                ('category', models.TextField(blank=True, default='')),
                ('tags', models.JSONField(blank=True, default=list)),
                ('status', models.TextField(default='new')),
                ('source', models.TextField(default='person')),
                ('sources', models.JSONField(blank=True, default=list)),
                ('ref', models.TextField(blank=True, default='')),
                ('source_status', models.TextField(blank=True, default='')),
                ('source_key', models.TextField(blank=True, default='')),
                ('original', models.TextField(blank=True, default='')),
                ('sections', models.JSONField(blank=True, default=list)),
                ('notes', models.TextField(blank=True, default='')),
                ('links', models.JSONField(blank=True, default=list)),
                ('merged_into', models.BigIntegerField(blank=True, null=True)),
                ('feedback_id', models.TextField(blank=True, default='')),
                ('request_id', models.TextField(blank=True, default='')),
                ('built_as', models.TextField(blank=True, default='')),
                ('source_at', models.FloatField(blank=True, null=True)),
                ('created_at', models.FloatField()),
                ('updated_at', models.FloatField()),
            ],
            options={
                'db_table': 'incubator_ideas',
                'indexes': [models.Index(fields=['org_id', 'user_id', 'status'], name='incubator_whose_status'), models.Index(fields=['org_id', 'user_id', 'source_key'], name='incubator_source_key')],
                'constraints': [models.UniqueConstraint(fields=('org_id', 'user_id', 'number'), name='incubator_number_once')],
            },
        ),
    ]
