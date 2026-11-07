"""The heartbeat: a turn nobody asked for, so Rouh can keep a long experiment going (`rouh/heartbeat.py`).

Four new tables: each person's heartbeat and its standing brief, every beat, the approval queue,
and the experiment's ledger. New tables only, so a Rouh rolled back past this never reads them.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0089_synapse_dreams'),
    ]

    operations = [
        migrations.CreateModel(
            name='HeartbeatApproval',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('user_id', models.TextField()),
                ('org_id', models.TextField()),
                ('beat_id', models.BigIntegerField(blank=True, null=True)),
                ('tool', models.TextField(blank=True, default='')),
                ('args', models.JSONField(default=dict)),
                ('what', models.TextField()),
                ('to_whom', models.TextField(blank=True, default='')),
                ('why', models.TextField(blank=True, default='')),
                ('cost', models.TextField(blank=True, default='')),
                ('blocking', models.BooleanField(default=False)),
                ('state', models.TextField(default='waiting')),
                ('answered_on', models.TextField(blank=True, default='')),
                ('result', models.TextField(blank=True, default='')),
                ('asked_at', models.FloatField()),
                ('answered_at', models.FloatField(blank=True, null=True)),
            ],
            options={
                'db_table': 'heartbeat_approvals',
                'indexes': [models.Index(fields=['org_id', 'user_id', 'state'], name='heartbeat_approvals_whose')],
            },
        ),
        migrations.CreateModel(
            name='HeartbeatBeat',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('user_id', models.TextField()),
                ('org_id', models.TextField()),
                ('trigger', models.TextField()),
                ('events', models.JSONField(default=list)),
                ('status', models.TextField(default='running')),
                ('reason', models.TextField(blank=True, default='')),
                ('outcome', models.TextField(blank=True, default='')),
                ('said', models.TextField(blank=True, default='')),
                ('tools', models.JSONField(default=list)),
                ('cost', models.DecimalField(blank=True, decimal_places=6, max_digits=12, null=True)),
                ('started_at', models.FloatField()),
                ('finished_at', models.FloatField(blank=True, null=True)),
            ],
            options={
                'db_table': 'heartbeat_beats',
                'indexes': [models.Index(fields=['org_id', 'user_id', 'started_at'], name='heartbeat_beats_whose')],
            },
        ),
        migrations.CreateModel(
            name='HeartbeatLedger',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('user_id', models.TextField()),
                ('org_id', models.TextField()),
                ('direction', models.TextField()),
                ('amount', models.DecimalField(decimal_places=2, max_digits=12)),
                ('currency', models.TextField(default='USD')),
                ('what', models.TextField()),
                ('by', models.TextField()),
                ('at', models.FloatField()),
            ],
            options={
                'db_table': 'heartbeat_ledger',
                'indexes': [models.Index(fields=['org_id', 'user_id', 'at'], name='heartbeat_ledger_whose')],
            },
        ),
        migrations.CreateModel(
            name='HeartbeatState',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('user_id', models.TextField()),
                ('org_id', models.TextField()),
                ('state', models.TextField(default='on')),
                ('interval_minutes', models.IntegerField(default=30)),
                ('daily_cap', models.DecimalField(decimal_places=2, default=3, max_digits=10)),
                ('chat_id', models.TextField(blank=True, default='')),
                ('title', models.TextField(blank=True, default='')),
                ('goal', models.TextField(blank=True, default='')),
                ('rules', models.TextField(blank=True, default='')),
                ('plan', models.TextField(blank=True, default='')),
                ('notebook', models.TextField(blank=True, default='')),
                ('started_at', models.FloatField(default=0)),
                ('ends_at', models.FloatField(default=0)),
                ('budget', models.DecimalField(decimal_places=2, default=100, max_digits=10)),
                ('pending', models.JSONField(default=list)),
                ('own', models.JSONField(default=dict)),
                ('notes', models.JSONField(default=list)),
                ('due_at', models.FloatField(default=0)),
                ('due_what', models.TextField(blank=True, default='')),
                ('last_beat_at', models.FloatField(default=0)),
                ('last_full_at', models.FloatField(default=0)),
                ('last_telegram_at', models.FloatField(default=0)),
                ('wakes', models.JSONField(default=list)),
                ('created_at', models.FloatField(default=0)),
                ('updated_at', models.FloatField(default=0)),
            ],
            options={
                'db_table': 'heartbeat_state',
                'constraints': [models.UniqueConstraint(fields=('org_id', 'user_id'), name='heartbeat_state_one')],
            },
        ),
    ]
