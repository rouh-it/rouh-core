"""A task made for somebody outside, shared with them to edit, once (`rouh/requester_share.py`).

Petar, 14 October 2026: "I want when a task is created by outside person to be automatically
shared with edit rights to them. The entire task, not just the HTML page, the person shouldn't
be requesting it every time."

One row per task per address, written the first time the task is shared with the person who
asked for it, so it is done once: a share Petar stops later is never made again, and no second
letter goes. The tasks made for somebody outside before this are shared at the next start, by
the same code, and each gets its row then.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0152_run_kind'),
    ]

    operations = [
        migrations.CreateModel(
            name='RequesterShare',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('user_id', models.TextField()),
                ('org_id', models.TextField()),
                ('task_id', models.TextField()),
                ('folder', models.TextField(blank=True, default='')),
                ('email', models.TextField()),
                ('outcome', models.TextField()),
                ('token', models.TextField(blank=True, default='')),
                ('mailed', models.BooleanField(default=False)),
                ('mail_error', models.TextField(blank=True, default='')),
                ('at', models.FloatField()),
            ],
            options={
                'db_table': 'requester_shares',
                'constraints': [models.UniqueConstraint(
                    fields=('user_id', 'org_id', 'task_id', 'email'),
                    name='requester_shares_one')],
            },
        ),
    ]
