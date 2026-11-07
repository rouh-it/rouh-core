"""The heartbeat split in three: the heartbeat, Payments, and the long-running work it carries.

After 0091, which put the experiment's card vault, Stripe and a settings page onto the
heartbeat itself; Petar stopped that run, and this undoes the mixing without losing
anything of it: its settings go into the heartbeat's `config`, its caps into
`payment_settings`, and its vault's card and Stripe key there too, moved as they are,
still sealed and never opened.

Petar, 5 October 2026: "Heartbeat is the functionality you have to have in general. It has
nothing to do with the money project/experiment. ... Split those two." So the experiment's
brief, dates, budget, ledger and the spend so far move out of `heartbeat_state` into the
first `long_work` row, keeping its title, and the heartbeat keeps only its own settings.

- `heartbeat_state` gains `config`, `sent` and `held`, and loses the experiment's eight
  columns and 0091's settings columns once they are copied.
- `heartbeat_beats` and `heartbeat_approvals` say what raised them (`work_id`, `duties`,
  `duty`); every beat and approval so far was the experiment's, and says so.
- `long_work` and `long_work_ledger` are new; `heartbeat_ledger`'s rows are copied into the
  second and the table goes.
- `payment_settings`, `card_charges` and `stripe_links` are new (`rouh/payments.py`), and
  `heartbeat_vault` goes once it is copied.

The Heartbeat chat's history stays where it is: the experiment's row names it as where its
earlier beats ran (`earlier_chat_id`), and its model spend there since the experiment began is
carried as `spent_before`, so its budget counts it.
"""
import time
from decimal import Decimal

from django.db import migrations, models
from django.db.models import Q, Sum

MOVED = ("title", "goal", "rules", "plan", "notebook", "started_at", "ends_at", "budget")
#: 0091's settings columns, carried into `config` and `payment_settings` and then dropped.
SETTINGS_0091 = ("run_from", "run_until", "quiet_from", "quiet_until", "tg_per_hour",
                 "tg_per_day", "msg_quiet_from", "msg_quiet_until", "tell_when", "tg_sent",
                 "tg_held", "card_per_purchase", "card_per_day")
#: 0091's names for what is worth a message, and this heartbeat's.
WORTH = {"needs_yes": "needs_yes", "needs_human": "needs_human", "earned": "earned",
         "broken": "broken", "daily_summary": "summary"}


def _config_from_0091(row) -> dict:
    """0091's settings as `heartbeat.config_of` reads them; only what was set is carried."""
    config = {"hours": {}, "messages": {}}
    if row.run_from and row.run_until:
        config["hours"].update(work_from=row.run_from, work_to=row.run_until)
    if row.quiet_from and row.quiet_until:
        config["hours"].update(quiet_on=True, quiet_from=row.quiet_from, quiet_to=row.quiet_until)
    config["messages"].update(per_hour=int(row.tg_per_hour or 0), per_day=int(row.tg_per_day or 0))
    if row.msg_quiet_from and row.msg_quiet_until:
        config["messages"].update(quiet_on=True, quiet_from=row.msg_quiet_from,
                                  quiet_to=row.msg_quiet_until)
    flags = row.tell_when or {}
    config["messages"]["worth"] = {mine: bool(flags.get(theirs, True))
                                   for theirs, mine in WORTH.items()}
    return {k: v for k, v in config.items() if v}


def payments_from_0091(apps, schema_editor):
    """0091's caps and vault into `payment_settings`, still sealed."""
    State = apps.get_model("rouh", "HeartbeatState")
    Vault = apps.get_model("rouh", "HeartbeatVault")
    Settings = apps.get_model("rouh", "PaymentSettings")
    now = time.time()
    for row in State.objects.all():
        Settings.objects.get_or_create(
            user_id=row.user_id, org_id=row.org_id,
            defaults={"per_purchase": row.card_per_purchase or Decimal(50),
                      "per_day": row.card_per_day or Decimal(50), "updated_at": now})
        State.objects.filter(id=row.id).update(
            config=_config_from_0091(row), sent=list(row.tg_sent or []),
            held=list(row.tg_held or []))
    for v in Vault.objects.all():
        target, _made = Settings.objects.get_or_create(
            user_id=v.user_id, org_id=v.org_id, defaults={"updated_at": now})
        fields = {}
        # Moved as they are, still sealed, and never opened here: `payments` reads 0091's
        # shape of a card as well as its own.
        if v.card_sealed:
            fields.update(card_sealed=v.card_sealed, card_brand="Card",
                          card_last4=v.card_last4 or "", card_saved_at=v.card_saved_at or now)
        if v.stripe_sealed:
            fields.update(stripe_sealed=v.stripe_sealed,
                          stripe_hint=f"rk_…{v.stripe_last4}" if v.stripe_last4 else "rk_…",
                          stripe_saved_at=v.stripe_saved_at or now)
        if fields:
            Settings.objects.filter(id=target.id).update(**fields)


def split(apps, schema_editor):
    State = apps.get_model("rouh", "HeartbeatState")
    Work = apps.get_model("rouh", "LongWork")
    OldLedger = apps.get_model("rouh", "HeartbeatLedger")
    Ledger = apps.get_model("rouh", "LongWorkLedger")
    Beat = apps.get_model("rouh", "HeartbeatBeat")
    Approval = apps.get_model("rouh", "HeartbeatApproval")
    Request = apps.get_model("rouh", "LLMRequest")
    for row in State.objects.all():
        if not (row.title or row.goal or row.plan or row.notebook):
            continue
        spent = Decimal("0")
        if row.chat_id:
            spent = Decimal(Request.objects.filter(
                session_id=row.chat_id, user_id=row.user_id,
                started_at__gte=row.started_at or 0).aggregate(n=Sum("cost_usd"))["n"] or 0)
        own = dict(row.own or {})
        work = Work.objects.create(
            user_id=row.user_id, org_id=row.org_id, title=row.title or "Long-running work",
            goal=row.goal, rules=row.rules, plan=row.plan, notebook=row.notebook,
            state="on", carried=True, chat_id="", earlier_chat_id=row.chat_id or "",
            started_at=row.started_at or 0, ends_at=row.ends_at or 0,
            budget=row.budget or 0, spend_cap=Decimal("50"), spent_before=spent,
            # Everything waiting for a beat was the experiment's: it is told at its next one.
            pending=list(row.pending or []),
            own={k: own.get(k, []) for k in ("runs", "threads", "files") if own.get(k)},
            due_at=row.due_at or 0, due_what=row.due_what or "",
            last_beat_at=row.last_beat_at or 0, last_full_at=row.last_full_at or 0,
            created_at=row.created_at or 0, updated_at=row.updated_at or 0)
        for e in OldLedger.objects.filter(user_id=row.user_id, org_id=row.org_id):
            Ledger.objects.create(user_id=e.user_id, org_id=e.org_id, work_id=work.id,
                                  direction=e.direction, amount=e.amount, currency=e.currency,
                                  what=e.what, by=e.by, ref=e.ref or "", at=e.at)
        Beat.objects.filter(user_id=row.user_id, org_id=row.org_id).update(work_id=work.id)
        Approval.objects.filter(user_id=row.user_id, org_id=row.org_id).update(work_id=work.id)
        # The runs, threads and files were the experiment's; its own next beat is too.
        State.objects.filter(id=row.id).update(own={}, pending=[], due_at=0, due_what="")


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0091_heartbeat_settings_and_vault'),
    ]

    operations = [
        migrations.CreateModel(
            name='LongWork',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('user_id', models.TextField()),
                ('org_id', models.TextField()),
                ('title', models.TextField()),
                ('goal', models.TextField(blank=True, default='')),
                ('rules', models.TextField(blank=True, default='')),
                ('plan', models.TextField(blank=True, default='')),
                ('notebook', models.TextField(blank=True, default='')),
                ('state', models.TextField(default='on')),
                ('carried', models.BooleanField(default=True)),
                ('chat_id', models.TextField(blank=True, default='')),
                ('earlier_chat_id', models.TextField(blank=True, default='')),
                ('started_at', models.FloatField(default=0)),
                ('ends_at', models.FloatField(default=0)),
                ('budget', models.DecimalField(decimal_places=2, default=0, max_digits=10)),
                ('spend_cap', models.DecimalField(decimal_places=2, default=50, max_digits=10)),
                ('spent_before', models.DecimalField(decimal_places=6, default=0, max_digits=12)),
                ('pending', models.JSONField(default=list)),
                ('own', models.JSONField(default=dict)),
                ('due_at', models.FloatField(default=0)),
                ('due_what', models.TextField(blank=True, default='')),
                ('last_beat_at', models.FloatField(default=0)),
                ('last_full_at', models.FloatField(default=0)),
                ('created_at', models.FloatField(default=0)),
                ('updated_at', models.FloatField(default=0)),
            ],
            options={
                'db_table': 'long_work',
                'indexes': [models.Index(fields=['org_id', 'user_id'], name='long_work_whose')],
            },
        ),
        migrations.CreateModel(
            name='LongWorkLedger',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('user_id', models.TextField()),
                ('org_id', models.TextField()),
                ('work_id', models.BigIntegerField(blank=True, null=True)),
                ('direction', models.TextField()),
                ('amount', models.DecimalField(decimal_places=2, max_digits=12)),
                ('currency', models.TextField(default='USD')),
                ('what', models.TextField()),
                ('by', models.TextField()),
                ('ref', models.TextField(blank=True, default='')),
                ('at', models.FloatField()),
            ],
            options={
                'db_table': 'long_work_ledger',
                'indexes': [models.Index(fields=['org_id', 'user_id', 'work_id', 'at'],
                                         name='long_work_ledger_whose')],
                'constraints': [models.UniqueConstraint(
                    condition=~Q(ref=''), fields=('org_id', 'user_id', 'ref'),
                    name='long_work_ledger_ref_once')],
            },
        ),
        migrations.CreateModel(
            name='PaymentSettings',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('user_id', models.TextField()),
                ('org_id', models.TextField()),
                ('card_sealed', models.TextField(blank=True, default='')),
                ('card_brand', models.TextField(blank=True, default='')),
                ('card_last4', models.TextField(blank=True, default='')),
                ('card_saved_at', models.FloatField(default=0)),
                ('per_purchase', models.DecimalField(decimal_places=2, default=50, max_digits=10)),
                ('per_day', models.DecimalField(decimal_places=2, default=50, max_digits=10)),
                ('stripe_sealed', models.TextField(blank=True, default='')),
                ('stripe_hint', models.TextField(blank=True, default='')),
                ('stripe_mode', models.TextField(blank=True, default='')),
                ('stripe_saved_at', models.FloatField(default=0)),
                ('hook_token', models.TextField(blank=True, default='')),
                ('hook_id', models.TextField(blank=True, default='')),
                ('hook_url', models.TextField(blank=True, default='')),
                ('hook_sealed', models.TextField(blank=True, default='')),
                ('hook_saved_at', models.FloatField(default=0)),
                ('updated_at', models.FloatField(default=0)),
            ],
            options={
                'db_table': 'payment_settings',
                'constraints': [models.UniqueConstraint(fields=('org_id', 'user_id'),
                                                        name='payment_settings_one')],
            },
        ),
        migrations.CreateModel(
            name='CardCharge',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('user_id', models.TextField()),
                ('org_id', models.TextField()),
                ('work_id', models.BigIntegerField(blank=True, null=True)),
                ('merchant', models.TextField()),
                ('amount', models.DecimalField(decimal_places=2, max_digits=12)),
                ('currency', models.TextField(default='USD')),
                ('reason', models.TextField()),
                ('brand', models.TextField(blank=True, default='')),
                ('last4', models.TextField(blank=True, default='')),
                ('state', models.TextField(default='filled')),
                ('at', models.FloatField()),
            ],
            options={
                'db_table': 'card_charges',
                'indexes': [models.Index(fields=['org_id', 'user_id', 'at'], name='card_charges_whose')],
            },
        ),
        migrations.CreateModel(
            name='StripeLink',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('user_id', models.TextField()),
                ('org_id', models.TextField()),
                ('work_id', models.BigIntegerField(blank=True, null=True)),
                ('kind', models.TextField()),
                ('stripe_id', models.TextField()),
                ('name', models.TextField(blank=True, default='')),
                ('url', models.TextField(blank=True, default='')),
                ('at', models.FloatField()),
            ],
            options={
                'db_table': 'stripe_links',
                'indexes': [models.Index(fields=['org_id', 'user_id', 'stripe_id'],
                                         name='stripe_links_whose')],
            },
        ),
        migrations.AddField(model_name='heartbeatstate', name='config',
                            field=models.JSONField(default=dict)),
        migrations.AddField(model_name='heartbeatstate', name='sent',
                            field=models.JSONField(default=list)),
        migrations.AddField(model_name='heartbeatstate', name='held',
                            field=models.JSONField(default=list)),
        migrations.AddField(model_name='heartbeatbeat', name='work_id',
                            field=models.BigIntegerField(blank=True, null=True)),
        migrations.AddField(model_name='heartbeatbeat', name='duties',
                            field=models.JSONField(default=list)),
        migrations.AddField(model_name='heartbeatapproval', name='work_id',
                            field=models.BigIntegerField(blank=True, null=True)),
        migrations.AddField(model_name='heartbeatapproval', name='duty',
                            field=models.TextField(blank=True, default='')),
        migrations.RunPython(split, migrations.RunPython.noop),
        migrations.RunPython(payments_from_0091, migrations.RunPython.noop),
        *[migrations.RemoveField(model_name='heartbeatstate', name=name)
          for name in MOVED + SETTINGS_0091],
        migrations.DeleteModel(name='HeartbeatLedger'),
        migrations.DeleteModel(name='HeartbeatVault'),
    ]
