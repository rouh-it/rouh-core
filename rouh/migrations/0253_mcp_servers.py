from django.db import migrations, models


class Migration(migrations.Migration):
    """The MCP servers a person connects on Anatomy, Connections, MCP servers (`rouh/mcp_servers.py`),
    each keyed by its organisation and person, its secrets sealed."""

    dependencies = [("rouh", "0252_every_chat_belongs")]
    operations = [
        migrations.CreateModel(
            name="McpServer",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("org_id", models.TextField()),
                ("user_id", models.TextField()),
                ("name", models.TextField()),
                ("kind", models.TextField(default="http")),
                ("url", models.TextField(blank=True, default="")),
                ("command", models.JSONField(blank=True, default=list)),
                ("headers_sealed", models.TextField(blank=True, default="")),
                ("env_sealed", models.TextField(blank=True, default="")),
                ("hints", models.JSONField(blank=True, default=dict)),
                ("preset", models.TextField(blank=True, default="")),
                ("enabled", models.BooleanField(default=True)),
                ("ask_first", models.BooleanField(default=True)),
                ("tools", models.JSONField(blank=True, default=list)),
                ("checked_at", models.FloatField(default=0)),
                ("last_error", models.TextField(blank=True, default="")),
                ("made_at", models.FloatField(default=0)),
                ("updated_at", models.FloatField(default=0)),
            ],
            options={"db_table": "mcp_servers"},
        ),
        migrations.AddConstraint(
            model_name="mcpserver",
            constraint=models.UniqueConstraint(fields=("org_id", "user_id", "name"), name="mcp_servers_one_name"),
        ),
    ]
