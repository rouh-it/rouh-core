"""Each step of an email case kept whole, and Petar's tuning notes on it.

Petar, 1 October 2026: the case page is for debugging and tuning the pipeline,
so every turn's brief, tools and levels, every report and the routing of it
rule by rule are kept (`mail_case_traces`), and what he says about a case - a
false alarm and why, a re-run and its note, a question and its answer - too
(`mail_case_notes`). `step_note` carries a re-run's note to that turn's brief.
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0053_case_follow_ups'),
    ]

    operations = [
        migrations.AddField(
            model_name='mailcase',
            name='step_note',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.CreateModel(
            name='MailCaseNote',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('user_id', models.TextField()),
                ('org_id', models.TextField()),
                ('at', models.FloatField()),
                ('kind', models.TextField()),
                ('step', models.TextField(blank=True, default='')),
                ('text', models.TextField(blank=True, default='')),
                ('answer', models.TextField(blank=True, default='')),
                ('data', models.JSONField(default=dict)),
                ('case', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='notes', to='rouh.mailcase')),
            ],
            options={
                'db_table': 'mail_case_notes',
                'indexes': [models.Index(fields=['org_id', 'user_id', 'kind', 'at'], name='mail_case_notes_kind')],
            },
        ),
        migrations.CreateModel(
            name='MailCaseTrace',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('user_id', models.TextField()),
                ('org_id', models.TextField()),
                ('at', models.FloatField()),
                ('kind', models.TextField()),
                ('mode', models.TextField(blank=True, default='')),
                ('attempt', models.IntegerField(default=0)),
                ('data', models.JSONField(default=dict)),
                ('case', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='traces', to='rouh.mailcase')),
            ],
            options={
                'db_table': 'mail_case_traces',
                'indexes': [models.Index(fields=['org_id', 'user_id', 'case', 'at'], name='mail_case_traces_case')],
            },
        ),
    ]
