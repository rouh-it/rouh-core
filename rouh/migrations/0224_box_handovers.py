"""A box handed to a job as a file (`rouh/boxes.py`, "Handing a box to a job"; 2 November 2026).

One row for each box handed to a job: whose, which box, the sha256 of the one-time key the
program collects it with, the job, and when it was asked for, written and shredded. Never
what was in the box.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0223_share_ends'),
    ]

    operations = [
        migrations.CreateModel(
            name='BoxHandover',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('org_id', models.TextField()),
                ('user_id', models.TextField()),
                ('box_id', models.BigIntegerField()),
                ('number', models.IntegerField(default=0)),
                ('label', models.TextField(blank=True, default='')),
                ('grant', models.TextField(db_index=True)),
                ('run_id', models.TextField(blank=True, db_index=True, default='')),
                ('via', models.TextField(blank=True, default='')),
                ('chat', models.TextField(blank=True, default='')),
                ('made_at', models.FloatField()),
                ('handed_at', models.FloatField(blank=True, null=True)),
                ('ended_at', models.FloatField(blank=True, null=True)),
                ('ended', models.TextField(blank=True, default='')),
            ],
            options={
                'db_table': 'box_handovers',
                'indexes': [models.Index(fields=['org_id', 'user_id', 'box_id', 'made_at'],
                                         name='box_handovers_whose')],
            },
        ),
    ]
