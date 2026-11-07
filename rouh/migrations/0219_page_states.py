"""A page's own settings (`rouh/pagestate.py`): what a person chose on a workspace page, kept on
the server so it lasts past a reload and follows them to every device.

Petar, 29 October 2026, about 158-05's hide and show buttons: "everything should be persistent
storage ... for this page".
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0218_demo_mode'),
    ]

    operations = [
        migrations.CreateModel(
            name='PageState',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('org_id', models.TextField()),
                ('user_id', models.TextField()),
                ('rel', models.TextField()),
                ('settings', models.JSONField(default=dict)),
                ('updated_at', models.FloatField()),
            ],
            options={
                'db_table': 'page_states',
                'constraints': [models.UniqueConstraint(fields=('org_id', 'user_id', 'rel'),
                                                        name='page_states_one')],
            },
        ),
    ]
