"""Google and xAI keys per organisation, the totals toggle and the blind comparisons apart from
Auto, the votes, and a call's errors (`rouh/providerkeys.py`, `rouh/modelvotes.py`; Petar, 24
October 2026). Each organisation's totals go on being shared exactly when they were: while
either box was on Auto."""

from django.db import migrations, models


def carry_over(apps, schema_editor):
    rows = apps.get_model("rouh", "ModelDefaults")
    for row in rows.objects.all():
        row.share_totals = bool(row.auto_tiers or row.auto_uses)
        row.save(update_fields=["share_totals"])


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0212_turn_records'),
    ]

    operations = [
        migrations.CreateModel(
            name='ModelProviderKey',
            fields=[
                ('pk', models.CompositePrimaryKey('org_id', 'provider', blank=True, editable=False, primary_key=True, serialize=False)),
                ('org_id', models.TextField()),
                ('provider', models.TextField()),
                ('key_sealed', models.TextField()),
                ('last4', models.TextField(blank=True, default='')),
                ('saved_by', models.TextField(blank=True, default='')),
                ('saved_at', models.FloatField(default=0)),
            ],
            options={
                'db_table': 'model_provider_key',
            },
        ),
        migrations.AddField(
            model_name='modeldefaults',
            name='compare',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='modeldefaults',
            name='compare_per_day',
            field=models.IntegerField(default=1),
        ),
        migrations.AddField(
            model_name='modeldefaults',
            name='share_totals',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='modeloutcome',
            name='errors',
            field=models.IntegerField(default=0),
        ),
        migrations.CreateModel(
            name='ModelVote',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('org_id', models.TextField()),
                ('use', models.TextField()),
                ('model_a', models.TextField()),
                ('model_b', models.TextField()),
                ('first', models.TextField()),
                ('vote', models.TextField(blank=True, default='')),
                ('day', models.TextField()),
                ('counted_on', models.TextField(blank=True, default='')),
                ('token', models.TextField(blank=True, default='')),
            ],
            options={
                'db_table': 'model_vote',
                'indexes': [models.Index(fields=['org_id', 'day'], name='model_vote_org_day')],
            },
        ),
        migrations.RunPython(carry_over, migrations.RunPython.noop),
    ]
