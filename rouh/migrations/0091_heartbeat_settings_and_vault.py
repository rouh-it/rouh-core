"""The heartbeat's settings, its card vault and Stripe key, and the owner's change to its brief.

Petar, 5 October 2026: a settings page (the hours it beats, its quiet hours, what it may
message about and how often, its caps), a card the heartbeat may spend from within caps,
and a Stripe restricted key. All new columns have defaults and the vault is a new table,
so a Rouh rolled back past this reads none of it.

And the brief: on the installation it was written for, the one heartbeat experiment that
was running had its seeded rules (if still as seeded) and the first two lines of its plan
(if still there) changed to the owner's new brief, and its next beat was told. That brief
was the owner's own, and it now lives only in that installation's database; a fresh
install has no heartbeat running when it migrates, so that step does nothing.
"""
from django.db import migrations, models


def brief_changed(apps, schema_editor):
    """Nothing to do: the brief it changed was one owner's own, kept in their database."""


def nothing(apps, schema_editor):
    return None



class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0090_heartbeat'),
    ]

    operations = [
        migrations.CreateModel(
            name='HeartbeatVault',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('user_id', models.TextField()),
                ('org_id', models.TextField()),
                ('card_sealed', models.TextField(blank=True, default='')),
                ('card_last4', models.TextField(blank=True, default='')),
                ('card_saved_at', models.FloatField(default=0)),
                ('stripe_sealed', models.TextField(blank=True, default='')),
                ('stripe_last4', models.TextField(blank=True, default='')),
                ('stripe_saved_at', models.FloatField(default=0)),
                ('webhook_id', models.TextField(blank=True, default='')),
                ('webhook_url', models.TextField(blank=True, default='')),
                ('webhook_secret_sealed', models.TextField(blank=True, default='')),
                ('webhook_token_hash', models.TextField(blank=True, default='')),
                ('updated_at', models.FloatField(default=0)),
            ],
            options={
                'db_table': 'heartbeat_vault',
            },
        ),
        migrations.AddField(
            model_name='heartbeatledger',
            name='ref',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='heartbeatstate',
            name='card_per_day',
            field=models.DecimalField(decimal_places=2, default=50, max_digits=10),
        ),
        migrations.AddField(
            model_name='heartbeatstate',
            name='card_per_purchase',
            field=models.DecimalField(decimal_places=2, default=50, max_digits=10),
        ),
        migrations.AddField(
            model_name='heartbeatstate',
            name='msg_quiet_from',
            field=models.TextField(blank=True, default='22:00'),
        ),
        migrations.AddField(
            model_name='heartbeatstate',
            name='msg_quiet_until',
            field=models.TextField(blank=True, default='08:00'),
        ),
        migrations.AddField(
            model_name='heartbeatstate',
            name='quiet_from',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='heartbeatstate',
            name='quiet_until',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='heartbeatstate',
            name='run_from',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='heartbeatstate',
            name='run_until',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='heartbeatstate',
            name='summary_day',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='heartbeatstate',
            name='tell_when',
            field=models.JSONField(default=dict),
        ),
        migrations.AddField(
            model_name='heartbeatstate',
            name='tg_held',
            field=models.JSONField(default=list),
        ),
        migrations.AddField(
            model_name='heartbeatstate',
            name='tg_per_day',
            field=models.IntegerField(default=6),
        ),
        migrations.AddField(
            model_name='heartbeatstate',
            name='tg_per_hour',
            field=models.IntegerField(default=1),
        ),
        migrations.AddField(
            model_name='heartbeatstate',
            name='tg_sent',
            field=models.JSONField(default=list),
        ),
        migrations.AddConstraint(
            model_name='heartbeatledger',
            constraint=models.UniqueConstraint(condition=models.Q(('ref', ''), _negated=True), fields=('org_id', 'user_id', 'ref'), name='heartbeat_ledger_once'),
        ),
        migrations.AddConstraint(
            model_name='heartbeatvault',
            constraint=models.UniqueConstraint(fields=('org_id', 'user_id'), name='heartbeat_vault_one'),
        ),
        migrations.RunPython(brief_changed, nothing),
    ]
