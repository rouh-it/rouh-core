"""recall_timelines: what Synapse Master's look-ups did for each of the person's messages, drawn under it
in the chat (`rouh/recalling.py`; Petar, 10 October 2026)."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0112_notices'),
    ]

    operations = [
        migrations.CreateModel(
            name='RecallTimeline',
            fields=[
                ('message_id', models.BigIntegerField(primary_key=True, serialize=False)),
                ('session_id', models.TextField()),
                ('ts', models.FloatField()),
                ('data', models.JSONField(default=dict)),
            ],
            options={
                'db_table': 'recall_timelines',
                'indexes': [models.Index(fields=['session_id', 'message_id'], name='recall_timelines_chat')],
            },
        ),
    ]
