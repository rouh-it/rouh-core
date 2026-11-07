"""Billing entities: who a card's purchases are billed to (`rouh/payments.py`).

Petar, 14 October 2026 (fr_7c47d56e9a95): "You added billing address but we also need
company details for the invoices- company, vat, and if anything else is filled. We
actually need to have multiple entities saved. I have two business entities and one
personal set of cards".

Each `billing_entities` row is a label, an optional company, VAT number, registration
number and invoice email, and the billing address. Each card belongs to one
(`payment_cards.entity_id`), and each purchase keeps who it was billed to as it was then
(`card_charges.billed_to`). A card saved before this keeps its billing address inside its
seal, which a migration cannot open, so the address is carried over into an entity the
first time the vault is read (`payments.carry_over`), with nothing lost.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0145_payment_card_silo'),
    ]

    operations = [
        migrations.CreateModel(
            name='BillingEntity',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('user_id', models.TextField()),
                ('org_id', models.TextField()),
                ('label', models.TextField()),
                ('company', models.TextField(blank=True, default='')),
                ('vat', models.TextField(blank=True, default='')),
                ('reg_number', models.TextField(blank=True, default='')),
                ('email', models.TextField(blank=True, default='')),
                ('line1', models.TextField(blank=True, default='')),
                ('line2', models.TextField(blank=True, default='')),
                ('city', models.TextField(blank=True, default='')),
                ('postal_code', models.TextField(blank=True, default='')),
                ('state', models.TextField(blank=True, default='')),
                ('country', models.TextField(blank=True, default='')),
                ('created_at', models.FloatField()),
                ('updated_at', models.FloatField(default=0)),
            ],
            options={
                'db_table': 'billing_entities',
                'indexes': [models.Index(fields=['org_id', 'user_id', 'created_at'], name='billing_entities_whose')],
            },
        ),
        migrations.AddField(
            model_name='paymentcard',
            name='entity_id',
            field=models.BigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='cardcharge',
            name='billed_to',
            field=models.TextField(blank=True, default=''),
        ),
    ]
