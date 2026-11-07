"""How far Rouh may read Petar's own inbox for a trusted contact, and the log of it.

Petar, 2 October 2026: a trusted contact held every level and topic, and every
request of theirs that needed his inbox still failed, because nothing could grant
it. So each trusted contact has "Your inbox - how far" (`inbox_scope`, with the
senders and labels of "A sender or label" in `inbox_from`) and "When a request
goes beyond all this" (`beyond`), every contact starting at None and Ask me;
nothing is seeded. A case keeps what he allowed for that one email
(`mail_cases.inbox_grant`), and every read of his inbox done for a contact is a
row of `trusted_inbox_reads`, shown on their page (`rouh/inbox_grants.py`).
"""
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0057_case_attempts'),
    ]

    operations = [
        migrations.AddField(
            model_name='trustedcontact',
            name='inbox_scope',
            field=models.TextField(default='none', db_default='none'),
        ),
        migrations.AddField(
            model_name='trustedcontact',
            name='inbox_from',
            field=models.JSONField(default=list, db_default=[]),
        ),
        migrations.AddField(
            model_name='trustedcontact',
            name='beyond',
            field=models.TextField(default='ask', db_default='ask'),
        ),
        migrations.AddField(
            model_name='mailcase',
            name='inbox_grant',
            field=models.JSONField(default=dict, db_default={}),
        ),
        migrations.CreateModel(
            name='InboxRead',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('user_id', models.TextField()),
                ('org_id', models.TextField()),
                ('case_id', models.BigIntegerField(default=0)),
                ('case_key', models.TextField(blank=True, default='')),
                ('at', models.FloatField(default=0)),
                ('kind', models.TextField(default='read')),
                ('inbox', models.TextField(blank=True, default='')),
                ('query', models.TextField(blank=True, default='')),
                ('message_id', models.TextField(blank=True, default='')),
                ('subject', models.TextField(blank=True, default='')),
                ('sender', models.TextField(blank=True, default='')),
                ('found', models.IntegerField(default=0)),
                ('scope', models.TextField(blank=True, default='')),
                ('source', models.TextField(blank=True, default='')),
                ('contact', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                              related_name='+', to='rouh.trustedcontact')),
            ],
            options={
                'db_table': 'trusted_inbox_reads',
                'indexes': [models.Index(fields=['org_id', 'user_id', 'contact', 'at'],
                                         name='trusted_inbox_reads_latest')],
            },
        ),
    ]
