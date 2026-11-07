"""The spending caps are each card's own (`rouh/payments.py`).

Petar, 14 October 2026, on the Payments page (fr_c29d7ddcee31): "Each card needs to have a
limit", and then, of the one cap a purchase and a day the whole vault had: "I have a
spending cap but it needs to be per card". Each card gets the most a purchase, a day and a
calendar month of its own, each optional. Every card there is starts with the vault's caps
as they were, so none is left without one; a limit set on a card in the hour before this
(0147) is kept as the cap of its kind, the lower of the two where both say. The vault-wide
caps are then let go.
"""
from decimal import Decimal

from django.db import migrations, models

DEFAULT = Decimal("100")


def per_card(apps, schema_editor):
    Card = apps.get_model("rouh", "PaymentCard")
    Settings = apps.get_model("rouh", "PaymentSettings")
    caps = {(s.org_id, s.user_id): (s.per_purchase, s.per_day) for s in Settings.objects.all()}
    for card in Card.objects.all():
        purchase, day = caps.get((card.org_id, card.user_id), (DEFAULT, DEFAULT))
        month = None
        if card.spend_limit is not None:
            if card.limit_period == "purchase":
                purchase = min(purchase, card.spend_limit)
            elif card.limit_period == "day":
                day = min(day, card.spend_limit)
            else:
                month = card.spend_limit
        Card.objects.filter(id=card.id).update(per_purchase=purchase, per_day=day, per_month=month)


def back(apps, schema_editor):
    Card = apps.get_model("rouh", "PaymentCard")
    for card in Card.objects.exclude(per_month=None):
        Card.objects.filter(id=card.id).update(spend_limit=card.per_month, limit_period="month")


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0147_payment_card_limit'),
    ]

    operations = [
        migrations.AddField(
            model_name='paymentcard',
            name='per_purchase',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True),
        ),
        migrations.AddField(
            model_name='paymentcard',
            name='per_day',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True),
        ),
        migrations.AddField(
            model_name='paymentcard',
            name='per_month',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True),
        ),
        migrations.RunPython(per_card, back),
        migrations.RemoveField(model_name='paymentcard', name='spend_limit'),
        migrations.RemoveField(model_name='paymentcard', name='limit_period'),
        migrations.RemoveField(model_name='paymentsettings', name='per_purchase'),
        migrations.RemoveField(model_name='paymentsettings', name='per_day'),
    ]
