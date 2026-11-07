"""The nightly feature run (`rouh/nightly_feature.py`), its switches, and the vault's caps at 100.

Petar, 6 October 2026: the nightly feature run may pay up to 100 dollars a run with the
vault's card, and the vault's caps go to 100 dollars a purchase and 100 a day so that the
50-dollar caps do not stop it ("not an extra barrier at 50"). A cap still at the old
default, 50, is raised; a cap somebody set to anything else is left as they set it.
"""
from decimal import Decimal

from django.db import migrations, models


def raise_caps(apps, schema_editor):
    PaymentSettings = apps.get_model("rouh", "PaymentSettings")
    PaymentSettings.objects.filter(per_purchase=Decimal("50")).update(per_purchase=Decimal("100"))
    PaymentSettings.objects.filter(per_day=Decimal("50")).update(per_day=Decimal("100"))


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0099_case_told_and_reminders'),
    ]

    operations = [
        migrations.AddField(
            model_name='cardcharge',
            name='run_id',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AlterField(
            model_name='paymentsettings',
            name='per_day',
            field=models.DecimalField(decimal_places=2, default=100, max_digits=10),
        ),
        migrations.AlterField(
            model_name='paymentsettings',
            name='per_purchase',
            field=models.DecimalField(decimal_places=2, default=100, max_digits=10),
        ),
        migrations.CreateModel(
            name='FeatureSwitch',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('org_id', models.TextField()),
                ('name', models.TextField()),
                ('title', models.TextField(blank=True, default='')),
                ('on', models.BooleanField(default=True)),
                ('night_id', models.BigIntegerField(blank=True, null=True)),
                ('changed_by', models.TextField(blank=True, default='')),
                ('updated_at', models.FloatField()),
            ],
            options={
                'db_table': 'feature_switches',
                'constraints': [models.UniqueConstraint(fields=('org_id', 'name'), name='feature_switch_one')],
            },
        ),
        migrations.CreateModel(
            name='NightlyFeatureNight',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('user_id', models.TextField()),
                ('org_id', models.TextField()),
                ('number', models.IntegerField()),
                ('run_id', models.TextField(blank=True, default='')),
                ('browser_port', models.IntegerField(default=0)),
                ('state', models.TextField(default='running')),
                ('why', models.TextField(blank=True, default='')),
                ('started_at', models.FloatField()),
                ('feature', models.TextField(blank=True, default='')),
                ('switch', models.TextField(blank=True, default='')),
                ('built', models.TextField(blank=True, default='')),
                ('try_it', models.TextField(blank=True, default='')),
                ('saves', models.TextField(blank=True, default='')),
                ('screenshots', models.JSONField(blank=True, default=list)),
                ('report', models.TextField(blank=True, default='')),
                ('asked_at', models.FloatField(blank=True, null=True)),
                ('verdict', models.TextField(blank=True, default='')),
                ('words', models.TextField(blank=True, default='')),
                ('decided_at', models.FloatField(blank=True, null=True)),
                ('undo_run_id', models.TextField(blank=True, default='')),
                ('handed_on', models.FloatField(blank=True, null=True)),
            ],
            options={
                'db_table': 'nightly_feature_nights',
                'constraints': [models.UniqueConstraint(fields=('org_id', 'user_id', 'number'), name='nightly_feature_night_number')],
            },
        ),
        migrations.CreateModel(
            name='NightlyFeatureService',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('user_id', models.TextField()),
                ('org_id', models.TextField()),
                ('night_id', models.BigIntegerField()),
                ('service', models.TextField()),
                ('address', models.TextField()),
                ('why', models.TextField(blank=True, default='')),
                ('login_name', models.TextField(blank=True, default='')),
                ('login_sealed', models.TextField(blank=True, default='')),
                ('at', models.FloatField()),
            ],
            options={
                'db_table': 'nightly_feature_services',
                'indexes': [models.Index(fields=['org_id', 'user_id', 'service'], name='nightly_service_whose')],
            },
        ),
        migrations.RunPython(raise_caps, migrations.RunPython.noop),
    ]
