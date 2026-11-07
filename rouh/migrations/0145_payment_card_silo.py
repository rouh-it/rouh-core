"""A card in the vault may be for one silo (`rouh/payments.py`, `rouh/silos.py`).

Petar, 14 October 2026, on the Payments page (fr_3c19cfb75db1): "add also silo to the
card. different purposes different cards... work for work". Each card keeps the key of
the silo it is for, or "" for none, which is every card there is today.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0144_payment_cards'),
    ]

    operations = [
        migrations.AddField(
            model_name='paymentcard',
            name='silo',
            field=models.TextField(blank=True, default=''),
        ),
    ]
