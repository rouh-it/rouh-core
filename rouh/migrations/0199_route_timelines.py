"""route_timelines: how the model that answered each turn was decided, drawn as the "Model decision" line
under the answer (`rouh/modelrouter.py`; Petar, 21 October 2026)."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0198_no_delegations_table'),
    ]

    operations = [
        migrations.CreateModel(
            name='RouteTimeline',
            fields=[
                ('call', models.TextField(primary_key=True, serialize=False)),
                ('session_id', models.TextField()),
                ('root', models.BigIntegerField(blank=True, null=True)),
                ('ts', models.FloatField()),
                ('data', models.JSONField(default=dict)),
            ],
            options={
                'db_table': 'route_timelines',
                'indexes': [models.Index(fields=['session_id', 'root'], name='route_timelines_chat')],
            },
        ),
    ]
