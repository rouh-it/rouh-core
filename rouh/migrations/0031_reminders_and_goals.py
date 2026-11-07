"""Reminders, repeating jobs and check-ins, and goals with what was done toward them.

Petar, 26 September 2026, answering task 60 again: "Fine - please implement 1
and 4" - idea 1 of the Meta Muse research, a clock (`rouh/reminders.py`), and
idea 4, goals with a plan, a tracker and check-ins (`rouh/goals.py`). Three
empty tables, keyed by person and organisation; nothing is moved into them, so
a Rouh rolled back past this loses nothing it had before.
"""
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0030_llm_requests'),
    ]

    operations = [
        migrations.CreateModel(
            name='Goal',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('user_id', models.TextField()),
                ('org_id', models.TextField()),
                ('title', models.TextField()),
                ('target', models.FloatField(default=1)),
                ('unit', models.TextField(blank=True, default='times')),
                ('per', models.TextField(default='week')),
                ('by_date', models.TextField(blank=True, default='')),
                ('plan', models.TextField(default='[]')),
                ('chat_id', models.TextField(blank=True, default='')),
                ('state', models.TextField(default='on')),
                ('created_at', models.FloatField()),
                ('updated_at', models.FloatField()),
            ],
            options={
                'db_table': 'goals',
                'indexes': [models.Index(fields=['org_id', 'user_id'], name='goals_whose')],
            },
        ),
        migrations.CreateModel(
            name='Reminder',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('user_id', models.TextField()),
                ('org_id', models.TextField()),
                ('kind', models.TextField(default='remind')),
                ('what', models.TextField()),
                ('chat_id', models.TextField(blank=True, default='')),
                ('goal_id', models.BigIntegerField(blank=True, null=True)),
                ('repeat', models.TextField(default='once')),
                ('at_time', models.TextField(blank=True, default='')),
                ('days', models.TextField(blank=True, default='')),
                ('month_day', models.IntegerField(default=0)),
                ('next_at', models.FloatField(blank=True, null=True)),
                ('state', models.TextField(default='on')),
                ('created_at', models.FloatField()),
                ('updated_at', models.FloatField()),
                ('last_at', models.FloatField(blank=True, null=True)),
                ('last_said', models.TextField(blank=True, default='')),
                ('fired', models.IntegerField(default=0)),
            ],
            options={
                'db_table': 'reminders',
                'indexes': [models.Index(fields=['org_id', 'user_id'], name='reminders_whose'), models.Index(fields=['state', 'next_at'], name='reminders_due')],
            },
        ),
        migrations.CreateModel(
            name='GoalEntry',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('user_id', models.TextField()),
                ('org_id', models.TextField()),
                ('day', models.TextField()),
                ('amount', models.FloatField(default=1)),
                ('note', models.TextField(blank=True, default='')),
                ('created_at', models.FloatField()),
                ('goal', models.ForeignKey(db_column='goal_id', on_delete=django.db.models.deletion.CASCADE, related_name='entries', to='rouh.goal')),
            ],
            options={
                'db_table': 'goal_entries',
                'indexes': [models.Index(fields=['goal', 'day'], name='goal_entries_by_day')],
            },
        ),
    ]
