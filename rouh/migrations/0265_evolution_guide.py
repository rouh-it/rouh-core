"""The guiding prompt in Evolution's Parameters (Petar, 19 November 2026): what the AI picks from the
Incubator or invents for development. Null is never set, read as the starting guidance in
`rouh/evolution.py` (`GUIDE_START`); an empty text is the person clearing it.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("rouh", "0264_llm_asked_answered")]

    operations = [
        migrations.AddField(model_name="evolutionsetting", name="guide",
                            field=models.TextField(blank=True, null=True)),
        migrations.AddField(model_name="evolutionsetting", name="guide_at",
                            field=models.FloatField(blank=True, null=True)),
        migrations.AddField(model_name="evolutionsetting", name="guide_by",
                            field=models.TextField(blank=True, default="")),
    ]
