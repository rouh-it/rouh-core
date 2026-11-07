"""A person may keep several cards in the vault (`rouh/payments.py`, `PaymentCard`).

Petar, 14 October 2026 (fr_392511bf4c9c): "can you make multiple cards adding?" Until
now the vault held one card, on the person's `payment_settings` row. Each card is now a
row of its own in `payment_cards`, and a card already in the vault moves there exactly as
it was sealed, unopened, with its brand, last four and when it was saved. Its name and
expiry were only in the seal, so they stay blank for it until it is saved again. Then the
card's columns leave `payment_settings`. (The live vault was empty when this was written.)
"""
from django.db import migrations, models


def move_cards(apps, schema_editor):
    PaymentSettings = apps.get_model("rouh", "PaymentSettings")
    PaymentCard = apps.get_model("rouh", "PaymentCard")
    for row in PaymentSettings.objects.exclude(card_sealed=""):
        PaymentCard.objects.create(user_id=row.user_id, org_id=row.org_id, sealed=row.card_sealed,
                                   brand=row.card_brand or "Card", last4=row.card_last4,
                                   saved_at=row.card_saved_at or row.updated_at or 0)


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0143_task_107_its_first_chat'),
    ]

    operations = [
        migrations.CreateModel(
            name='PaymentCard',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('user_id', models.TextField()),
                ('org_id', models.TextField()),
                ('sealed', models.TextField()),
                ('brand', models.TextField(blank=True, default='')),
                ('last4', models.TextField(blank=True, default='')),
                ('name', models.TextField(blank=True, default='')),
                ('exp_month', models.IntegerField(default=0)),
                ('exp_year', models.IntegerField(default=0)),
                ('saved_at', models.FloatField()),
            ],
            options={
                'db_table': 'payment_cards',
                'indexes': [models.Index(fields=['org_id', 'user_id', 'saved_at'], name='payment_cards_whose')],
            },
        ),
        migrations.RunPython(move_cards, migrations.RunPython.noop),
        migrations.RemoveField(model_name='paymentsettings', name='card_sealed'),
        migrations.RemoveField(model_name='paymentsettings', name='card_brand'),
        migrations.RemoveField(model_name='paymentsettings', name='card_last4'),
        migrations.RemoveField(model_name='paymentsettings', name='card_saved_at'),
    ]
