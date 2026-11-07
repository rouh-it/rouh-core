"""The services Rouh and the person pay for again and again, kept by hand (`rouh/services.py`).

Petar, 15 October 2026: "Services should have nothing to do with nightly gene creation.
Services are things we purchase and we need to track and maybe unsubscribe. We currently have
none of those and the services item should be in payments of anatomy". So Anatomy, Money,
Services lists these rows, and no longer reads the nightly feature run's services.md.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0154_uploaded_file_task_owner'),
    ]

    operations = [
        migrations.CreateModel(
            name='PaidService',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('user_id', models.TextField()),
                ('org_id', models.TextField()),
                ('name', models.TextField()),
                ('what_for', models.TextField(blank=True, default='')),
                ('amount', models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True)),
                ('currency', models.TextField(default='USD')),
                ('period', models.TextField(default='month')),
                ('renews_on', models.DateField(blank=True, null=True)),
                ('trial_ends', models.DateField(blank=True, null=True)),
                ('paid_with', models.TextField(blank=True, default='')),
                ('account', models.TextField(blank=True, default='')),
                ('cancel_how', models.TextField(blank=True, default='')),
                ('state', models.TextField(default='active')),
                ('created_at', models.FloatField()),
                ('updated_at', models.FloatField()),
                ('cancelled_at', models.FloatField(blank=True, null=True)),
            ],
            options={
                'db_table': 'paid_services',
                'indexes': [models.Index(fields=['org_id', 'user_id', 'state'], name='paid_services_whose')],
            },
        ),
    ]
