"""Every use of a model its own pick, beside the two defaults.

Petar, 5 October 2026 (fr_74d5e6383c34): "extend this page to include every
single model use we have. I would like to be able to have full control on what
action/service uses what model." One JSON object per organisation, a use's id
to the model picked for it (`rouh/modeldefaults.py`, `USES`). Empty is every
use on the model it used before there was a pick, so nothing moves until
somebody picks something.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0092_heartbeat_split"),
    ]

    operations = [
        migrations.AddField(
            model_name="modeldefaults",
            name="uses",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
