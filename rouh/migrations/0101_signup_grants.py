"""Sign-ups the person authorized the live browser to make (`rouh/signups.py`).

Petar, 6 October 2026: a Stripe sign-up he had asked for, "without stopping and asking
me", stopped at its password and its Sign up button. One row per authorization, with the
password he sets for it sealed.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0100_nightly_feature'),
    ]

    operations = [
        migrations.CreateModel(
            name='SignupGrant',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('user_id', models.TextField()),
                ('org_id', models.TextField()),
                ('service', models.TextField()),
                ('site', models.TextField()),
                ('email', models.TextField(blank=True, default='')),
                ('words', models.TextField(blank=True, default='')),
                ('source', models.TextField(default='conversation')),
                ('chat', models.TextField(blank=True, default='')),
                ('granted_at', models.FloatField()),
                ('expires_at', models.FloatField()),
                ('withdrawn_at', models.FloatField(blank=True, null=True)),
                ('password_sealed', models.TextField(blank=True, default='')),
                ('password_set_at', models.FloatField(blank=True, null=True)),
                ('filled_at', models.FloatField(blank=True, null=True)),
                ('submitted_at', models.FloatField(blank=True, null=True)),
            ],
            options={
                'db_table': 'signup_grants',
                'indexes': [models.Index(fields=['org_id', 'user_id', 'expires_at'],
                                         name='signup_grants_whose')],
            },
        ),
    ]
