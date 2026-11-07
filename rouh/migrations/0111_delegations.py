"""delegations and delegate_acts: what a trusted contact may decide for Petar, and every
action they took, tried or had held for him (`rouh/delegation.py`, `DELEGATION.md`;
Petar, 9 October 2026)."""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0110_synapse_meetings'),
    ]

    operations = [
        migrations.CreateModel(
            name='Delegation',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('user_id', models.TextField()),
                ('org_id', models.TextField()),
                ('kind', models.TextField()),
                ('target', models.TextField()),
                ('number', models.IntegerField(default=0)),
                ('title', models.TextField(blank=True, default='')),
                ('power', models.TextField(default='decide')),
                ('pending', models.TextField(blank=True, default='')),
                ('state', models.TextField(default='active')),
                ('granted_by', models.TextField(default='petar')),
                ('created_at', models.FloatField(default=0)),
                ('updated_at', models.FloatField(default=0)),
                ('revoked_at', models.FloatField(default=0)),
                ('contact', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='+', to='rouh.trustedcontact')),
            ],
            options={
                'db_table': 'delegations',
                'indexes': [models.Index(fields=['org_id', 'user_id', 'contact'], name='delegations_contact')],
                'constraints': [models.UniqueConstraint(condition=models.Q(('state', 'active')), fields=('org_id', 'user_id', 'contact', 'kind', 'target'), name='delegations_one_active')],
            },
        ),
        migrations.CreateModel(
            name='DelegateAct',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('user_id', models.TextField()),
                ('org_id', models.TextField()),
                ('contact_name', models.TextField(blank=True, default='')),
                ('act', models.TextField()),
                ('target_kind', models.TextField(blank=True, default='')),
                ('target', models.TextField(blank=True, default='')),
                ('number', models.IntegerField(default=0)),
                ('title', models.TextField(blank=True, default='')),
                ('words', models.TextField(blank=True, default='')),
                ('said', models.TextField(blank=True, default='')),
                ('asked', models.JSONField(default=dict)),
                ('outcome', models.TextField(default='done')),
                ('why', models.TextField(blank=True, default='')),
                ('decision_id', models.BigIntegerField(blank=True, null=True)),
                ('handle', models.TextField(blank=True, default='')),
                ('case_id', models.BigIntegerField(blank=True, null=True)),
                ('channel', models.TextField(blank=True, default='')),
                ('undo', models.JSONField(default=dict)),
                ('key', models.TextField(blank=True, default='')),
                ('at', models.FloatField(default=0)),
                ('undone_at', models.FloatField(default=0)),
                ('undone_said', models.TextField(blank=True, default='')),
                ('contact', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='rouh.trustedcontact')),
                ('delegation', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='rouh.delegation')),
            ],
            options={
                'db_table': 'delegate_acts',
                'indexes': [models.Index(fields=['org_id', 'user_id', 'at'], name='delegate_acts_when'), models.Index(fields=['org_id', 'user_id', 'contact'], name='delegate_acts_contact'), models.Index(fields=['org_id', 'user_id', 'decision_id'], name='delegate_acts_decision'), models.Index(fields=['org_id', 'user_id', 'key'], name='delegate_acts_key')],
            },
        ),
    ]
