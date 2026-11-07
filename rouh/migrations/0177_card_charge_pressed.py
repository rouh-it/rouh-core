"""When Rouh pressed a purchase's Pay or order button, and what the page then said
(`CardCharge.pressed_at`, `CardCharge.outcome`).

On 17 October 2026 an online shop's order (charge 2) was written down as paid the moment Mollie's
"Pay with card" was pressed, and Petar was told it was paid, while his bank was still showing
a 3-D Secure dialog asking for a code from the bank's mobile app. A press is not a payment: the
charge is "confirming" from the press until the page shows the shop's or the payment
provider's confirmation, and only then paid (`payments.settle`).
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0176_card_charge_addresses"),
    ]

    operations = [
        migrations.AddField(
            model_name="cardcharge",
            name="pressed_at",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="cardcharge",
            name="outcome",
            field=models.TextField(blank=True, default=""),
        ),
    ]
