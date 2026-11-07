"""nav_taps: one row per press of a row of the sidebar's navigation, for Settings, Stats
(`rouh/navtaps.py`; Petar, 10 October 2026, fr_e82bf294e064)."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0113_recall_timelines'),
    ]

    operations = [
        migrations.CreateModel(
            name='NavTap',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('user_id', models.TextField()),
                ('org_id', models.TextField()),
                ('item', models.TextField()),
                ('at', models.FloatField()),
            ],
            options={
                'db_table': 'nav_taps',
                'indexes': [models.Index(fields=['org_id', 'user_id', 'at'], name='nav_taps_whose')],
            },
        ),
    ]
