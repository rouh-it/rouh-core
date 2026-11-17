"""Rouh Link (task 189): the link key and switches, connections, connect links, messages, the
signed log, live spaces, their changes, and delegate grants (`rouh/models/link.py`)."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0258_contact_relations'),
    ]

    operations = [
        migrations.CreateModel(
            name='LinkInvite',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('org_id', models.TextField()),
                ('token_hash', models.TextField()),
                ('trust', models.TextField(default='known')),
                ('silo', models.TextField(blank=True, default='')),
                ('for_label', models.TextField(blank=True, default='')),
                ('note', models.TextField(blank=True, default='')),
                ('created_at', models.FloatField(default=0)),
                ('expires_at', models.FloatField(default=0)),
                ('used_at', models.FloatField(blank=True, null=True)),
                ('used_by', models.TextField(blank=True, default='')),
                ('withdrawn_at', models.FloatField(blank=True, null=True)),
            ],
            options={
                'db_table': 'link_invites',
            },
        ),
        migrations.CreateModel(
            name='LinkSelf',
            fields=[
                ('org_id', models.TextField(primary_key=True, serialize=False)),
                ('link_public', models.TextField()),
                ('link_private', models.TextField()),
                ('settings', models.JSONField(blank=True, default=dict)),
                ('created_at', models.FloatField(default=0)),
                ('updated_at', models.FloatField(default=0)),
            ],
            options={
                'db_table': 'link_self',
            },
        ),
        migrations.CreateModel(
            name='LinkGrant',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('org_id', models.TextField()),
                ('grant_id', models.TextField()),
                ('direction', models.TextField()),
                ('peer_label', models.TextField()),
                ('what', models.TextField()),
                ('limits', models.JSONField(blank=True, default=dict)),
                ('words', models.TextField(blank=True, default='')),
                ('created_at', models.FloatField(default=0)),
                ('ends_at', models.FloatField(blank=True, null=True)),
                ('withdrawn_at', models.FloatField(blank=True, null=True)),
                ('signature', models.TextField(blank=True, default='')),
            ],
            options={
                'db_table': 'link_grants',
                'constraints': [models.UniqueConstraint(fields=('org_id', 'grant_id', 'direction'), name='link_grants_once')],
            },
        ),
        migrations.CreateModel(
            name='LinkLog',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('org_id', models.TextField()),
                ('seq', models.IntegerField()),
                ('at', models.FloatField()),
                ('peer_label', models.TextField(blank=True, default='')),
                ('space_id', models.TextField(blank=True, default='')),
                ('kind', models.TextField()),
                ('plain', models.TextField()),
                ('entry', models.JSONField(blank=True, default=dict)),
                ('prev', models.TextField(blank=True, default='')),
                ('hash', models.TextField()),
                ('sig', models.TextField(blank=True, default='')),
            ],
            options={
                'db_table': 'link_log',
                'constraints': [models.UniqueConstraint(fields=('org_id', 'seq'), name='link_log_seq')],
            },
        ),
        migrations.CreateModel(
            name='LinkMessage',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('org_id', models.TextField()),
                ('msg_id', models.TextField()),
                ('peer_label', models.TextField()),
                ('direction', models.TextField()),
                ('kind', models.TextField()),
                ('envelope', models.JSONField(blank=True, default=dict)),
                ('state', models.TextField(default='queued')),
                ('tries', models.IntegerField(default=0)),
                ('next_at', models.FloatField(default=0)),
                ('said', models.TextField(blank=True, default='')),
                ('created_at', models.FloatField(default=0)),
                ('done_at', models.FloatField(blank=True, null=True)),
            ],
            options={
                'db_table': 'link_messages',
                'indexes': [models.Index(fields=['org_id', 'state', 'next_at'], name='link_messages_due')],
                'constraints': [models.UniqueConstraint(fields=('org_id', 'msg_id', 'direction'), name='link_messages_once')],
            },
        ),
        migrations.CreateModel(
            name='LinkOp',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('org_id', models.TextField()),
                ('space_id', models.TextField()),
                ('seq', models.IntegerField(default=0)),
                ('op_id', models.TextField()),
                ('actor', models.TextField()),
                ('kind', models.TextField()),
                ('data', models.JSONField(blank=True, default=dict)),
                ('at', models.FloatField(default=0)),
                ('pending', models.BooleanField(default=False)),
                ('undone', models.BooleanField(default=False)),
            ],
            options={
                'db_table': 'link_ops',
                'indexes': [models.Index(fields=['org_id', 'space_id', 'seq'], name='link_ops_order')],
                'constraints': [models.UniqueConstraint(fields=('org_id', 'space_id', 'op_id'), name='link_ops_once')],
            },
        ),
        migrations.CreateModel(
            name='LinkPeer',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('org_id', models.TextField()),
                ('label', models.TextField()),
                ('name', models.TextField(blank=True, default='')),
                ('address', models.TextField(blank=True, default='')),
                ('card', models.JSONField(blank=True, default=dict)),
                ('daily_key', models.TextField(blank=True, default='')),
                ('link_key', models.TextField(blank=True, default='')),
                ('trust', models.TextField(default='known')),
                ('silo', models.TextField(blank=True, default='')),
                ('state', models.TextField(default='connected')),
                ('via', models.TextField(blank=True, default='')),
                ('contact_id', models.TextField(blank=True, default='')),
                ('note', models.TextField(blank=True, default='')),
                ('created_at', models.FloatField(default=0)),
                ('updated_at', models.FloatField(default=0)),
                ('last_seen_at', models.FloatField(blank=True, null=True)),
            ],
            options={
                'db_table': 'link_peers',
                'constraints': [models.UniqueConstraint(fields=('org_id', 'label'), name='link_peers_org_label')],
            },
        ),
        migrations.CreateModel(
            name='LinkSpace',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('org_id', models.TextField()),
                ('space_id', models.TextField()),
                ('kind', models.TextField(default='task')),
                ('title', models.TextField(blank=True, default='')),
                ('holder_label', models.TextField()),
                ('holder_address', models.TextField(blank=True, default='')),
                ('holder_key', models.TextField(blank=True, default='')),
                ('mine', models.BooleanField(default=False)),
                ('silo', models.TextField(blank=True, default='')),
                ('seq', models.IntegerField(default=0)),
                ('doc', models.JSONField(blank=True, default=dict)),
                ('meta', models.JSONField(blank=True, default=dict)),
                ('source', models.TextField(blank=True, default='')),
                ('state', models.TextField(default='live')),
                ('created_at', models.FloatField(default=0)),
                ('updated_at', models.FloatField(default=0)),
            ],
            options={
                'db_table': 'link_spaces',
                'constraints': [models.UniqueConstraint(fields=('org_id', 'space_id'), name='link_spaces_once')],
            },
        ),
    ]
