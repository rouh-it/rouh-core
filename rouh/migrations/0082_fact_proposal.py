"""Where each old fact is proposed to go, now that the memory is rules, words and notes (`rouh/rules.py`)."""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("rouh", "0081_synapse_mail_sync")]

    operations = [
        migrations.AddField(model_name="fact", name="proposal",
                            field=models.JSONField(blank=True, default=None, null=True)),
    ]
