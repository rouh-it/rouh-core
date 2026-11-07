"""A purchase Rouh placed itself, on Petar's own words (`rouh/purchases.py`).

Petar, 17 October 2026, during an online shop's checkout: "Don't leave pay
button for me, you need to learn to do it autonomously." So a card charge says when Rouh
pressed the order button, what was ordered and which of his words authorized it.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0172_dreame_mi"),
    ]

    operations = [
        migrations.AddField(
            model_name="cardcharge",
            name="placed_at",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="cardcharge",
            name="bought",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="cardcharge",
            name="words",
            field=models.TextField(blank=True, default=""),
        ),
    ]
