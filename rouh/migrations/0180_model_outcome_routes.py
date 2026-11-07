"""What Auto decided for a turn, kept with its call (`rouh/modelrouter.py`, `rouh/modeloutcomes.py`):
the exchange it answered, whether the router picked the tier or its fallback did, the reason, and
how long the router took and what it cost.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0179_model_tiers'),
    ]

    operations = [
        migrations.AddField(
            model_name='modeloutcome',
            name='auto',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='modeloutcome',
            name='root',
            field=models.BigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='modeloutcome',
            name='route_reason',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='modeloutcome',
            name='router_cost_usd',
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='modeloutcome',
            name='router_ms',
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='modeloutcome',
            name='router_ok',
            field=models.BooleanField(default=False),
        ),
    ]
