"""What background jobs ask Rouh's gateway for (`rouh/job_gateway.py`, Petar, 25 October 2026)."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0213_model_providers_and_votes'),
    ]

    operations = [
        migrations.CreateModel(
            name='JobRequest',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('user_id', models.TextField()),
                ('org_id', models.TextField()),
                ('job_id', models.TextField()),
                ('job_title', models.TextField(blank=True, default='')),
                ('scope', models.TextField()),
                ('kind', models.TextField()),
                ('tool', models.TextField(blank=True, default='')),
                ('need', models.TextField(blank=True, default='')),
                ('why', models.TextField(blank=True, default='')),
                ('meanwhile', models.TextField(blank=True, default='')),
                ('gap', models.TextField(blank=True, default='')),
                ('outcome', models.TextField(default='asking')),
                ('answer', models.TextField(blank=True, default='')),
                ('approval_id', models.BigIntegerField(blank=True, null=True)),
                ('model', models.TextField(blank=True, default='')),
                ('cost_usd', models.FloatField(blank=True, null=True)),
                ('created_at', models.FloatField()),
                ('settled_at', models.FloatField(blank=True, null=True)),
            ],
            options={
                'db_table': 'job_requests',
                'indexes': [models.Index(fields=['org_id', 'user_id', '-created_at'], name='job_requests_whose'),
                            models.Index(fields=['job_id'], name='job_requests_job'),
                            models.Index(fields=['approval_id'], name='job_requests_approval')],
            },
        ),
    ]
