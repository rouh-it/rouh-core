"""The lines tool calls draw in a chat are kept with it (`models.ToolLine`).

30 September 2026, fr_3f1814427840: "I would like in chat when I see the tool
usage to also be saved in chat history. Currently after refresh we no longer
see old tool usage." A table of its own, so rolling back past this loses only
the lines, and the chats read back as they did before: words only.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0044_ghost_list_reads_the_connection"),
    ]

    operations = [
        migrations.CreateModel(
            name="ToolLine",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("session_id", models.TextField()),
                ("call_id", models.TextField()),
                ("after_message_id", models.BigIntegerField(blank=True, null=True)),
                ("ts", models.FloatField()),
                ("name", models.TextField(blank=True, default="")),
                ("input", models.TextField(blank=True, default="")),
                ("done", models.BooleanField(default=False)),
                ("ok", models.BooleanField(default=True)),
                ("summary", models.TextField(blank=True, default="")),
                ("results", models.JSONField(blank=True, default=list)),
                ("output", models.TextField(blank=True, null=True)),
            ],
            options={
                "db_table": "tool_lines",
                "indexes": [
                    models.Index(fields=["session_id", "call_id"], name="tool_lines_call"),
                    models.Index(fields=["session_id", "after_message_id"],
                                 name="tool_lines_after"),
                ],
            },
        ),
    ]
