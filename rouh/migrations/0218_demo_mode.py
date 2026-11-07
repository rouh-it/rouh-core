"""Demo mode (`rouh/demo.py`): the account's switch, every time it was turned, and what was
approved for the audience, each as it was when approved."""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0217_rouh_human_names'),
    ]

    operations = [
        migrations.CreateModel(
            name='DemoState',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('org_id', models.TextField()),
                ('user_id', models.TextField()),
                ('on', models.BooleanField(default=False)),
                ('since', models.FloatField(default=0)),
                ('device', models.TextField(blank=True, default='')),
                ('dots', models.BooleanField(default=True)),
                ('updated_at', models.FloatField(default=0)),
            ],
            options={'db_table': 'demo_state'},
        ),
        migrations.AddConstraint(
            model_name='demostate',
            constraint=models.UniqueConstraint(fields=('org_id', 'user_id'), name='demo_state_one'),
        ),
        migrations.CreateModel(
            name='DemoEvent',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('org_id', models.TextField()),
                ('user_id', models.TextField()),
                ('on', models.BooleanField()),
                ('at', models.FloatField()),
                ('device', models.TextField(blank=True, default='')),
                ('agent', models.TextField(blank=True, default='')),
                ('address', models.TextField(blank=True, default='')),
            ],
            options={'db_table': 'demo_event'},
        ),
        migrations.AddIndex(
            model_name='demoevent',
            index=models.Index(fields=['org_id', 'user_id', 'at'], name='demo_event_whose'),
        ),
        migrations.CreateModel(
            name='DemoApproval',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('org_id', models.TextField()),
                ('user_id', models.TextField()),
                ('kind', models.TextField()),
                ('ref', models.TextField()),
                ('fingerprint', models.TextField(blank=True, default='')),
                ('source', models.TextField(blank=True, default='')),
                ('approved_at', models.FloatField(default=0)),
            ],
            options={'db_table': 'demo_approval'},
        ),
        migrations.AddConstraint(
            model_name='demoapproval',
            constraint=models.UniqueConstraint(fields=('org_id', 'user_id', 'kind', 'ref'),
                                               name='demo_approval_one'),
        ),
    ]
