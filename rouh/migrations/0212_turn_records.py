"""Every turn's timings and results, kept for good (`rouh/turnrecords.py`, Petar, 23 October 2026)."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0211_rouh_birth'),
    ]

    operations = [
        migrations.CreateModel(
            name='TurnRecord',
            fields=[
                ('turn_id', models.TextField(primary_key=True, serialize=False)),
                ('session_id', models.TextField()),
                ('org_id', models.TextField(blank=True, default='')),
                ('user_id', models.TextField(blank=True, default='')),
                ('message_id', models.BigIntegerField(blank=True, null=True)),
                ('root', models.BigIntegerField(blank=True, null=True)),
                ('version', models.IntegerField(default=1)),
                ('note', models.BooleanField(default=False)),
                ('heard', models.TextField(blank=True, default='')),
                ('started_at', models.FloatField()),
                ('ended_at', models.FloatField(blank=True, null=True)),
                ('total_ms', models.IntegerField(blank=True, null=True)),
                ('first_token_ms', models.IntegerField(blank=True, null=True)),
                ('first_word_ms', models.IntegerField(blank=True, null=True)),
                ('first_spoken_ms', models.IntegerField(blank=True, null=True)),
                ('status', models.TextField(default='running')),
                ('error', models.TextField(blank=True, default='')),
                ('tier', models.TextField(blank=True, default='')),
                ('model', models.TextField(blank=True, default='')),
                ('mode', models.TextField(blank=True, default='')),
                ('reply_ids', models.JSONField(default=list)),
                ('reply_text', models.TextField(blank=True, default='')),
                ('cost_usd', models.DecimalField(blank=True, decimal_places=6, max_digits=12, null=True)),
                ('costs', models.JSONField(default=dict)),
                ('trace', models.JSONField(default=dict)),
                ('synapse', models.JSONField(default=list)),
                ('labels', models.JSONField(default=dict)),
            ],
            options={
                'db_table': 'turn_records',
                'indexes': [
                    models.Index(fields=['session_id', 'root'], name='turn_records_chat'),
                    models.Index(fields=['user_id', 'org_id', '-started_at'], name='turn_records_mine'),
                    models.Index(fields=['message_id'], name='turn_records_message'),
                ],
            },
        ),
    ]
