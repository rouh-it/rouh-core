"""When a share ends by itself (`rouh/share_ends.py`, night 29, 1 November 2026).

One row a person a page or task shared with them by hand, for a share given an end in the
Share panel: the owner's ``org_id`` and ``user_id``, the share's ``token`` (`PageGuest`),
its ``rel`` and address, and ``ends_at``. When it has passed, the share is taken away the
way Remove takes it away, and the row goes with it.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0222_synapse_bg_again'),
    ]

    operations = [
        migrations.CreateModel(
            name='ShareEnd',
            fields=[
                ('token', models.TextField(primary_key=True, serialize=False)),
                ('org_id', models.TextField()),
                ('user_id', models.TextField()),
                ('rel', models.TextField()),
                ('email', models.TextField()),
                ('ends_at', models.FloatField()),
                ('set_at', models.FloatField()),
            ],
            options={
                'db_table': 'share_ends',
                'indexes': [models.Index(fields=['ends_at'], name='share_ends_when')],
            },
        ),
    ]
