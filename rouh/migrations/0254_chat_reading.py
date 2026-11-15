from django.db import migrations, models


class Migration(migrations.Migration):
    """What Rouh reads in a chat, set by the person in "What I'm reading" (`rouh/reading.py`), and whether the
    chat is incognito (`rouh/incognito.py`). Petar, 15 November 2026 (Chat Change Planning, points 4, 5, 7)."""

    dependencies = [("rouh", "0253_mcp_servers")]
    operations = [
        migrations.AddField(model_name="chat", name="reading",
                            field=models.JSONField(blank=True, default=dict, db_default={})),
        migrations.AddField(model_name="chat", name="incognito",
                            field=models.BooleanField(default=False, db_default=False)),
    ]
