"""Thoughts: the person's own thoughts, kept in their words and listed (`rouh/thoughts.py`).

Petar, 12 October 2026: "If I have random thoughts that come to my mind and I want you to remember
them reliably what feature would you use to handle that?", and then, told there was no list of them,
"But that is exactly what I was interested in getting solved".

On the installation it was written for, this brought back the one thought the owner had given that
night, which Rouh had kept as a note in their Synapse Master, as their first thought, and made that
note its copy in Synapse rather than a second item beside it. That thought now lives only in that
installation's database; anywhere else there was never a note to bring back, so this does nothing.
"""

from django.db import migrations, models


def bring_back(apps, schema_editor):
    """Nothing to do: the one thought it brought back belongs to the installation it was on."""


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0127_offline_actions'),
    ]

    operations = [
        migrations.CreateModel(
            name='Thought',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('org_id', models.TextField()),
                ('user_id', models.TextField()),
                ('words', models.TextField()),
                ('title', models.TextField(blank=True, default='')),
                ('said_at', models.FloatField()),
                ('source', models.TextField(default='typed')),
                ('tags', models.JSONField(default=list)),
                ('status', models.TextField(default='open')),
                ('follows', models.BigIntegerField(blank=True, null=True)),
                ('chat_id', models.TextField(blank=True, default='')),
                ('synapse_item', models.TextField(blank=True, default='')),
                ('synapse_at', models.FloatField(blank=True, null=True)),
                ('made_at', models.FloatField()),
                ('updated_at', models.FloatField()),
                ('archived_at', models.FloatField(blank=True, null=True)),
            ],
            options={
                'db_table': 'thoughts',
                'indexes': [models.Index(fields=['org_id', 'user_id', 'said_at'], name='thoughts_whose'),
                            models.Index(fields=['org_id', 'user_id', 'status'], name='thoughts_state')],
            },
        ),
        migrations.RunPython(bring_back, migrations.RunPython.noop),
    ]
