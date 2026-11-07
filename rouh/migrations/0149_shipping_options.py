"""Shipping options in the person's favourite order, and the situations that reorder them
(`rouh/shipping.py`).

Petar, 14 October 2026: "I want to be able to define shipping options and addresses with
priority depending on what the vendor allows ... sometimes it is a box, sometimes a speedy
office, sometimes I have to provide address. I have preferences for each situation ... I
need to be able to line up options in favorite order."

Each `shipping_options` row is a courier, a kind of place (locker, office or door address)
and the place itself, with its place in the main order and an on/off switch. Each
`shipping_situations` row is a named situation with its own ordered list of those options;
the Default situation is the main order and has no row. Both are labelled with a silo,
Personal, as private contact detail.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0148_payment_card_caps'),
    ]

    operations = [
        migrations.CreateModel(
            name='ShippingOption',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('user_id', models.TextField()),
                ('org_id', models.TextField()),
                ('label', models.TextField()),
                ('company', models.TextField(blank=True, default='')),
                ('kind', models.TextField()),
                ('place_code', models.TextField(blank=True, default='')),
                ('place_name', models.TextField(blank=True, default='')),
                ('line1', models.TextField(blank=True, default='')),
                ('city', models.TextField(blank=True, default='')),
                ('postal_code', models.TextField(blank=True, default='')),
                ('country', models.TextField(blank=True, default='')),
                ('floor', models.TextField(blank=True, default='')),
                ('apartment', models.TextField(blank=True, default='')),
                ('entrance', models.TextField(blank=True, default='')),
                ('door_code', models.TextField(blank=True, default='')),
                ('recipient_name', models.TextField(blank=True, default='')),
                ('recipient_phone', models.TextField(blank=True, default='')),
                ('notes', models.TextField(blank=True, default='')),
                ('position', models.IntegerField(default=0)),
                ('active', models.BooleanField(default=True)),
                ('silo', models.TextField(blank=True, default='')),
                ('created_at', models.FloatField()),
                ('updated_at', models.FloatField(default=0)),
            ],
            options={
                'db_table': 'shipping_options',
                'indexes': [models.Index(fields=['org_id', 'user_id', 'position'], name='shipping_options_whose')],
            },
        ),
        migrations.CreateModel(
            name='ShippingSituation',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('user_id', models.TextField()),
                ('org_id', models.TextField()),
                ('name', models.TextField()),
                ('options', models.JSONField(blank=True, default=list)),
                ('position', models.IntegerField(default=0)),
                ('silo', models.TextField(blank=True, default='')),
                ('created_at', models.FloatField()),
                ('updated_at', models.FloatField(default=0)),
            ],
            options={
                'db_table': 'shipping_situations',
                'indexes': [models.Index(fields=['org_id', 'user_id', 'position'], name='shipping_situations_whose')],
            },
        ),
    ]
