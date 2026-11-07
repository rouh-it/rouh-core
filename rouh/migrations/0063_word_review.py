"""The word review's settings, one row per organisation (`rouh/word_review.py`).

Petar, 3 October 2026: the flags the plain word check raises on an email case
go to one model call before he is asked, and he tunes that call - its model,
its reasoning and its instructions - from the case page, saved here for every
review after it.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0062_synapse_lab'),
    ]

    operations = [
        migrations.CreateModel(
            name='MailWordReview',
            fields=[
                ('org_id', models.TextField(primary_key=True, serialize=False)),
                ('model', models.TextField(blank=True, default='')),
                ('effort', models.TextField(blank=True, default='')),
                ('prompt', models.TextField(blank=True, default='')),
                ('changed_by', models.TextField(blank=True, default='')),
                ('changed_at', models.FloatField(blank=True, null=True)),
            ],
            options={
                'db_table': 'mail_word_review',
            },
        ),
    ]
