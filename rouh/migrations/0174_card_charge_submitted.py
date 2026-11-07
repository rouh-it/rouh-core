"""An order Rouh submitted at a shop that takes the card only afterwards (`rouh/purchases.py`).

The first real order Rouh placed, on 17 October 2026, stuck where the shop has no card
fields until its order button is pressed and sends the browser to its payment provider. So a
card charge can say when that order button was pressed, before the card went in.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0173_card_charge_placed"),
    ]

    operations = [
        migrations.AddField(
            model_name="cardcharge",
            name="submitted_at",
            field=models.FloatField(blank=True, null=True),
        ),
    ]
