"""One home for every file (`rouh/filestore.py`, `rouh/models/files.py`), 4 November 2026: the list
of files, which is the only authority on where a file is, what it belongs to, where it came from and
its earlier versions.
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0240_trial_mode'),
    ]

    operations = [
        migrations.CreateModel(
            name='File',
            fields=[
                ('id', models.TextField(primary_key=True, serialize=False)),
                ('org_id', models.TextField(blank=True, default='')),
                ('user_id', models.TextField(blank=True, default='')),
                ('name', models.TextField()),
                ('media_type', models.TextField(blank=True, default='')),
                ('kind', models.TextField(default='file')),
                ('size', models.BigIntegerField(default=0)),
                ('sha256', models.TextField(blank=True, default='')),
                ('path', models.TextField()),
                ('session', models.TextField(blank=True, default='')),
                ('storage', models.TextField(default='disk')),
                ('source', models.TextField(default='chat')),
                ('source_ref', models.JSONField(blank=True, default=dict)),
                ('silos', models.JSONField(blank=True, default=list)),
                ('permissions', models.JSONField(blank=True, default=dict)),
                ('meta', models.JSONField(blank=True, default=dict)),
                ('r2_key', models.TextField(blank=True, default='')),
                ('created_at', models.FloatField()),
                ('updated_at', models.FloatField()),
                ('deleted_at', models.FloatField(blank=True, null=True)),
                ('deleted_by', models.TextField(blank=True, default='')),
            ],
            options={
                'db_table': 'file',
                'indexes': [models.Index(fields=['sha256'], name='file_sha256'), models.Index(fields=['session'], name='file_session'), models.Index(fields=['deleted_at'], name='file_deleted')],
                'constraints': [models.CheckConstraint(condition=models.Q(('storage__in', ('disk', 'git', 'disk+r2'))), name='file_storage_known')],
            },
        ),
        migrations.CreateModel(
            name='FileOwner',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('kind', models.TextField()),
                ('owner_id', models.TextField()),
                ('created_at', models.FloatField()),
                ('file', models.ForeignKey(db_column='file_id', on_delete=django.db.models.deletion.CASCADE, related_name='owners', to='rouh.file')),
            ],
            options={
                'db_table': 'file_owner',
                'indexes': [models.Index(fields=['kind', 'owner_id'], name='file_owner_of')],
                'constraints': [models.UniqueConstraint(fields=('file', 'kind', 'owner_id'), name='file_owner_once'), models.CheckConstraint(condition=models.Q(('kind__in', ('chat', 'task', 'project'))), name='file_owner_known')],
            },
        ),
        migrations.CreateModel(
            name='FileVersion',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('number', models.IntegerField()),
                ('sha256', models.TextField()),
                ('size', models.BigIntegerField(default=0)),
                ('kept_at', models.TextField(blank=True, default='')),
                ('r2_key', models.TextField(blank=True, default='')),
                ('made_at', models.FloatField()),
                ('by', models.TextField(blank=True, default='')),
                ('file', models.ForeignKey(db_column='file_id', on_delete=django.db.models.deletion.CASCADE, related_name='versions', to='rouh.file')),
            ],
            options={
                'db_table': 'file_version',
                'constraints': [models.UniqueConstraint(fields=('file', 'number'), name='file_version_once')],
            },
        ),
    ]
