"""Grants as data (CAPABILITIES.md, MAIL.md D35): three new tables, and nothing moved.

`capability_grants` holds a contact's grants of their own - one capability at one contract
version, an exact scope, typed limits and a lifetime, its sentence and the digest of what the owner
approved - and every proposal declined; `capability_grant_events` what happened to each, kept
forever; `capability_uses` every call a grant covered, claimed before it ran, so a retry is never
done twice. `mail_asks` gains the capability an ask was read as, the resources it names and the
values it asks.

Nothing that was there is changed: the levels, the inbox reach, the grants on contacts' pages and
every task's permission are read as they are, as standing grants of the capabilities that name
them (`capability_grants.held_keys`).
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0201_task_ticks_are_records'),
    ]

    operations = [
        migrations.CreateModel(
            name='CapabilityGrant',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('user_id', models.TextField()),
                ('org_id', models.TextField()),
                ('capability', models.TextField()),
                ('version', models.IntegerField()),
                ('scope', models.JSONField(default=list)),
                ('limits', models.JSONField(default=dict)),
                ('lifetime', models.TextField()),
                ('until', models.TextField(blank=True, default='')),
                ('expires_at', models.FloatField(blank=True, default=None, null=True)),
                ('max_uses', models.IntegerField(blank=True, default=None, null=True)),
                ('used', models.IntegerField(default=0)),
                ('state', models.TextField()),
                ('digest', models.TextField()),
                ('wording', models.TextField(blank=True, default='')),
                ('proposal', models.JSONField(default=dict)),
                ('proposed_by', models.TextField(blank=True, default='')),
                ('case_key', models.TextField(blank=True, default='')),
                ('ask_ident', models.TextField(blank=True, default='')),
                ('approved_by', models.TextField(blank=True, default='')),
                ('approved_at', models.FloatField(blank=True, default=None, null=True)),
                ('ended_by', models.TextField(blank=True, default='')),
                ('ended_at', models.FloatField(blank=True, default=None, null=True)),
                ('reason', models.TextField(blank=True, default='')),
                ('suspended_reason', models.TextField(blank=True, default='')),
                ('created_at', models.FloatField(default=0)),
                ('updated_at', models.FloatField(default=0)),
                ('contact', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='+', to='rouh.trustedcontact')),
                ('replaces', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='rouh.capabilitygrant')),
            ],
            options={
                'db_table': 'capability_grants',
            },
        ),
        migrations.CreateModel(
            name='CapabilityGrantEvent',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('user_id', models.TextField()),
                ('org_id', models.TextField()),
                ('at', models.FloatField()),
                ('by', models.TextField(blank=True, default='')),
                ('kind', models.TextField()),
                ('digest', models.TextField(blank=True, default='')),
                ('detail', models.JSONField(default=dict)),
                ('grant', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='events', to='rouh.capabilitygrant')),
            ],
            options={
                'db_table': 'capability_grant_events',
            },
        ),
        migrations.CreateModel(
            name='CapabilityUse',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('user_id', models.TextField()),
                ('org_id', models.TextField()),
                ('grant_ref', models.TextField()),
                ('call_key', models.TextField()),
                ('use_key', models.TextField(blank=True, default='')),
                ('case_key', models.TextField(blank=True, default='')),
                ('ask_ident', models.TextField(blank=True, default='')),
                ('tool', models.TextField(blank=True, default='')),
                ('capability', models.TextField(blank=True, default='')),
                ('state', models.TextField()),
                ('result', models.TextField(blank=True, default='')),
                ('at', models.FloatField()),
                ('done_at', models.FloatField(blank=True, default=None, null=True)),
                ('grant', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='uses', to='rouh.capabilitygrant')),
            ],
            options={
                'db_table': 'capability_uses',
            },
        ),
        migrations.AddIndex(
            model_name='capabilitygrant',
            index=models.Index(fields=['org_id', 'user_id', 'contact', 'state'], name='capability_grants_held'),
        ),
        migrations.AddIndex(
            model_name='capabilitygrant',
            index=models.Index(fields=['org_id', 'user_id', 'case_key'], name='capability_grants_case'),
        ),
        migrations.AddIndex(
            model_name='capabilitygrantevent',
            index=models.Index(fields=['org_id', 'user_id', 'grant'], name='capability_grant_events_of'),
        ),
        migrations.AddIndex(
            model_name='capabilityuse',
            index=models.Index(fields=['org_id', 'grant', 'at'], name='capability_uses_day'),
        ),
        migrations.AddConstraint(
            model_name='capabilityuse',
            constraint=models.UniqueConstraint(fields=('org_id', 'grant_ref', 'call_key'), name='capability_uses_once'),
        ),

        migrations.AddField(
            model_name='mailask',
            name='capability',
            field=models.TextField(blank=True, db_default='', default=''),
        ),
        migrations.AddField(
            model_name='mailask',
            name='scope',
            field=models.JSONField(blank=True, db_default=[], default=list),
        ),
        migrations.AddField(
            model_name='mailask',
            name='values',
            field=models.JSONField(blank=True, db_default={}, default=dict),
        ),
    ]
