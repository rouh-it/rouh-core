from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("rouh", "0246_greeting_in_the_conversation")]
    operations = [
        migrations.AddField(model_name="run", name=name,
                            field=models.TextField(blank=True, default="", db_default=""))
        for name in ("model", "actual_model")
    ]
