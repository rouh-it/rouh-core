"""Redo on a case's page: every earlier attempt at an email kept, frozen (`CaseDesk.redo`).

Petar, 2 October 2026: a case that is blocked, or whose decision expired, can
be started again as a fresh attempt from the top of its page, and the old
attempt and its decisions stay as audit history, marked superseded. So a case
counts its attempts (`mail_cases.attempt_no`), remembers what earlier ones
already did outside (`done_before`), each approval says which attempt asked it,
and every superseded attempt is one row of `mail_case_attempts`, once per
number, which is also what stops two presses making two attempts.
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0056_trusted_contact_topics'),
    ]

    operations = [
        migrations.AddField(
            model_name='mailcase',
            name='attempt_no',
            field=models.IntegerField(default=1, db_default=1),
        ),
        migrations.AddField(
            model_name='mailcase',
            name='done_before',
            field=models.JSONField(default=list, db_default=[]),
        ),
        migrations.AddField(
            model_name='mailapproval',
            name='attempt_no',
            field=models.IntegerField(default=1, db_default=1),
        ),
        migrations.CreateModel(
            name='MailCaseAttempt',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('user_id', models.TextField()),
                ('org_id', models.TextField()),
                ('number', models.IntegerField()),
                ('started_at', models.FloatField(default=0)),
                ('ended_at', models.FloatField(default=0)),
                ('status', models.TextField(default='superseded')),
                ('superseded_by', models.IntegerField(default=0)),
                ('redone_by', models.TextField(blank=True, default='')),
                ('redo_instruction', models.TextField(blank=True, default='')),
                ('end_stage', models.TextField(blank=True, default='')),
                ('snapshot', models.JSONField(default=dict)),
                ('effects', models.JSONField(default=list)),
                ('case', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                           related_name='earlier', to='rouh.mailcase')),
            ],
            options={
                'db_table': 'mail_case_attempts',
                'constraints': [models.UniqueConstraint(fields=('case', 'number'),
                                                        name='mail_case_attempts_once')],
            },
        ),
    ]
