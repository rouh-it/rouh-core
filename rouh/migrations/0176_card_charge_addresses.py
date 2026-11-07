"""Where a card purchase was billed and where it was delivered (`CardCharge.billing_address`,
`CardCharge.delivered_to`).

An online shop's order of 17 October 2026 (fr_cd4ba48083df) was billed to the office it was
delivered to, and nothing Petar could look at said so. Each order Rouh places now keeps both,
and the Payments page shows them.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0175_card_charge_task_ref"),
    ]

    operations = [
        migrations.AddField(
            model_name="cardcharge",
            name="billing_address",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="cardcharge",
            name="delivered_to",
            field=models.TextField(blank=True, default=""),
        ),
    ]
