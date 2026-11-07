"""A Rouh's human names (`birth.set_human_names`): a first and a last name beside the nickname,
each what one person calls their Rouh, shown to them only. Its own name never changes.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0216_page_reads'),
    ]

    operations = [
        migrations.AddField(model_name='rouhnickname', name='first_name',
                            field=models.TextField(default='')),
        migrations.AddField(model_name='rouhnickname', name='last_name',
                            field=models.TextField(default='')),
    ]
