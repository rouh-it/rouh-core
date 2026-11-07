"""notices: what drops in at the top of the person's screen, and goes to their phone only if
it is left there (`rouh/notices.py`; Petar, 10 October 2026, fr_8f09d161935f)."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0111_delegations'),
    ]

    operations = [
        migrations.CreateModel(
            name='Notice',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('user_id', models.TextField()),
                ('org_id', models.TextField()),
                ('key', models.TextField(blank=True, default='')),
                ('kind', models.TextField(blank=True, default='')),
                ('title', models.TextField()),
                ('body', models.TextField(blank=True, default='')),
                ('link', models.TextField(blank=True, default='')),
                ('link_label', models.TextField(blank=True, default='')),
                ('decision_id', models.BigIntegerField(blank=True, null=True)),
                ('state', models.TextField(default='new')),
                ('phone_text', models.TextField(blank=True, default='')),
                ('phone', models.TextField(blank=True, default='')),
                ('created_at', models.FloatField()),
                ('seen_at', models.FloatField(blank=True, null=True)),
                ('handled_at', models.FloatField(blank=True, null=True)),
                ('phoned_at', models.FloatField(blank=True, null=True)),
            ],
            options={
                'db_table': 'notices',
                'indexes': [models.Index(fields=['org_id', 'user_id', 'created_at'], name='notices_whose'), models.Index(fields=['phone', 'state'], name='notices_phone_due')],
                'constraints': [models.UniqueConstraint(condition=models.Q(('key', ''), _negated=True), fields=('org_id', 'user_id', 'key'), name='notices_said_once')],
            },
        ),
    ]
