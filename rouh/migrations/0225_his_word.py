"""The owner's own words behind a run, and what ran on them (`rouh/his_word.py`; 2 November 2026).

`run_words` keeps, for each run, the words of the owner's that started it or were said to it
later, exactly as said. `job_requests` gains `words`, `judged` and `undo`: for a job's call that ran
because those words already asked for it ("Done on your word" on the Metabolism page), the words
that covered it, the judge's reason, and how to undo it.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0224_box_handovers'),
    ]

    operations = [
        migrations.AddField(
            model_name='jobrequest',
            name='judged',
            field=models.TextField(blank=True, db_default='', default=''),
        ),
        migrations.AddField(
            model_name='jobrequest',
            name='undo',
            field=models.TextField(blank=True, db_default='', default=''),
        ),
        migrations.AddField(
            model_name='jobrequest',
            name='words',
            field=models.TextField(blank=True, db_default='', default=''),
        ),
        migrations.CreateModel(
            name='RunWords',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('user_id', models.TextField()),
                ('org_id', models.TextField()),
                ('run_id', models.TextField()),
                ('how', models.TextField(default='started')),
                ('words', models.TextField()),
                ('from_run', models.TextField(blank=True, default='')),
                ('at', models.FloatField()),
            ],
            options={
                'db_table': 'run_words',
                'indexes': [models.Index(fields=['run_id', 'at'], name='run_words_run')],
            },
        ),
    ]
