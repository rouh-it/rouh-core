from django.db import migrations, models


class Migration(migrations.Migration):
    """A guest is a rouh.land account (`rouh/landshare.py`, task 176, step 176-26)."""

    dependencies = [("rouh", "0247_run_model")]
    operations = [
        migrations.AddField(model_name="user", name="land_id",
                            field=models.CharField(blank=True, default="", db_default="", max_length=64)),
    ]
