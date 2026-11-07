"""Each card in the vault may have a limit of its own (`rouh/payments.py`).

Petar, 14 October 2026, on the Payments page (fr_c29d7ddcee31): "Each card needs to have a
limit". A card keeps its limit in dollars, or none, which is every card there is today, and
what it counts over, a month unless he picks a purchase or a day; and each purchase keeps
the card it was filled from, so that card's spending can be added up.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0146_billing_entities'),
    ]

    operations = [
        migrations.AddField(
            model_name='paymentcard',
            name='spend_limit',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True),
        ),
        migrations.AddField(
            model_name='paymentcard',
            name='limit_period',
            field=models.TextField(blank=True, default='month'),
        ),
        migrations.AddField(
            model_name='cardcharge',
            name='card_id',
            field=models.BigIntegerField(blank=True, null=True),
        ),
    ]
