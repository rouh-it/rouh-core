"""Decisions: one record of everything waiting on the person, whatever asked it (`rouh/decisions.py`).

Petar, 5 October 2026: "I feel like questions/answers should be a system unified thing. we have
it with tasks, we have it with quests, but somehow it is hooked to beats also. I think it should
be one model, one design, one place to look at them and make decisions."

Two new tables: the decisions, one row per question a source asked, and each one's history. New
tables only, so a Rouh rolled back past this never reads them. What is open today is taken in
from its sources the first time Rouh looks (`decisions.sync`), so nothing waiting is lost.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0094_quests'),
    ]

    operations = [
        migrations.CreateModel(
            name='Decision',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('user_id', models.TextField()),
                ('org_id', models.TextField()),
                ('source', models.TextField()),
                ('source_id', models.TextField()),
                ('key', models.TextField()),
                ('link', models.TextField(blank=True, default='')),
                ('context', models.TextField(blank=True, default='')),
                ('project', models.TextField(blank=True, default='')),
                ('batch', models.TextField(blank=True, default='')),
                ('title', models.TextField()),
                ('question', models.TextField()),
                ('why', models.TextField(blank=True, default='')),
                ('then', models.TextField(blank=True, default='')),
                ('prepared', models.JSONField(default=list)),
                ('options', models.JSONField(default=list)),
                ('recommended', models.TextField(blank=True, default='')),
                ('recommended_why', models.TextField(blank=True, default='')),
                ('allow_other', models.BooleanField(default=True)),
                ('answer_type', models.TextField(default='choice')),
                ('urgency', models.TextField(default='soon')),
                ('due_at', models.FloatField(blank=True, null=True)),
                ('risk', models.TextField(default='reversible')),
                ('risk_note', models.TextField(blank=True, default='')),
                ('status', models.TextField(default='open')),
                ('snoozed_until', models.FloatField(blank=True, null=True)),
                ('answer', models.JSONField(default=dict)),
                ('answered_by', models.TextField(blank=True, default='')),
                ('channel', models.TextField(blank=True, default='')),
                ('result', models.TextField(blank=True, default='')),
                ('apply_at', models.FloatField(blank=True, null=True)),
                ('telegram_message', models.BigIntegerField(blank=True, null=True)),
                ('created_at', models.FloatField()),
                ('updated_at', models.FloatField()),
                ('answered_at', models.FloatField(blank=True, null=True)),
                ('resolved_at', models.FloatField(blank=True, null=True)),
            ],
            options={
                'db_table': 'decisions',
                'indexes': [models.Index(fields=['org_id', 'user_id', 'status'], name='decisions_whose'), models.Index(fields=['status', 'apply_at'], name='decisions_due')],
                'constraints': [models.UniqueConstraint(fields=('org_id', 'user_id', 'source', 'key'), name='decisions_one_per_question')],
            },
        ),
        migrations.CreateModel(
            name='DecisionEvent',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('decision_id', models.BigIntegerField()),
                ('user_id', models.TextField()),
                ('org_id', models.TextField()),
                ('kind', models.TextField()),
                ('by', models.TextField(blank=True, default='')),
                ('channel', models.TextField(blank=True, default='')),
                ('detail', models.TextField(blank=True, default='')),
                ('at', models.FloatField()),
            ],
            options={
                'db_table': 'decision_events',
                'indexes': [models.Index(fields=['decision_id', 'at'], name='decision_events_of')],
            },
        ),
    ]
