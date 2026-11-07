"""A row for every request Rouh makes of a model, and each piece of what was asked, once.

Petar, 26 September 2026 (fr_c2ebaf6fa3e0): "full log of every single LLM
request we do, including cost, reasoning etc." `rouh/llmlog.py` writes it and
says what each column is for; an earlier project's `LLMInteraction` is where it started.
Two empty tables: nothing is moved into them and nothing reads them yet.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0029_chat_model"),
    ]

    operations = [
        migrations.CreateModel(
            name="LLMPiece",
            fields=[
                ("hash", models.CharField(max_length=64, primary_key=True, serialize=False)),
                ("kind", models.TextField()),
                ("body", models.TextField()),
                ("size", models.IntegerField(default=0)),
                ("created_at", models.FloatField()),
            ],
            options={
                "db_table": "llm_pieces",
            },
        ),
        migrations.CreateModel(
            name="LLMRequest",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("started_at", models.FloatField()),
                ("finished_at", models.FloatField(blank=True, null=True)),
                ("org_id", models.TextField(blank=True, default="")),
                ("user_id", models.TextField(blank=True, default="")),
                ("session_id", models.TextField(blank=True, default="")),
                ("turn_id", models.TextField(blank=True, default="")),
                ("purpose", models.TextField(blank=True, default="")),
                ("subject", models.TextField(blank=True, default="")),
                ("caller", models.TextField(blank=True, default="")),
                ("provider", models.TextField(default="anthropic")),
                ("endpoint", models.TextField(blank=True, default="")),
                ("model", models.TextField(blank=True, default="")),
                ("stream", models.BooleanField(default=False)),
                ("max_tokens", models.IntegerField(blank=True, null=True)),
                ("effort", models.TextField(blank=True, default="")),
                ("thinking", models.TextField(blank=True, default="")),
                ("settings", models.JSONField(default=dict)),
                ("system_piece", models.CharField(blank=True, default="", max_length=64)),
                ("tools_piece", models.CharField(blank=True, default="", max_length=64)),
                ("message_pieces", models.JSONField(default=list)),
                ("request_hash", models.CharField(blank=True, default="", max_length=64)),
                ("request_bytes", models.IntegerField(default=0)),
                ("attempt", models.IntegerField(default=1)),
                ("status", models.TextField(default="sent")),
                ("http_status", models.IntegerField(blank=True, null=True)),
                ("request_id", models.TextField(blank=True, default="")),
                ("message_id", models.TextField(blank=True, default="")),
                ("served_model", models.TextField(blank=True, default="")),
                ("stop_reason", models.TextField(blank=True, default="")),
                ("error_type", models.TextField(blank=True, default="")),
                ("error", models.TextField(blank=True, default="")),
                ("text", models.TextField(blank=True, default="")),
                ("reasoning", models.TextField(blank=True, default="")),
                ("response", models.JSONField(blank=True, null=True)),
                ("input_tokens", models.BigIntegerField(default=0)),
                ("output_tokens", models.BigIntegerField(default=0)),
                ("cache_read_tokens", models.BigIntegerField(default=0)),
                ("cache_write_tokens", models.BigIntegerField(default=0)),
                ("web_searches", models.IntegerField(default=0)),
                ("usage", models.JSONField(default=dict)),
                ("cost_usd", models.DecimalField(blank=True, decimal_places=6, max_digits=12,
                                                 null=True)),
                ("first_token_ms", models.IntegerField(blank=True, null=True)),
                ("duration_ms", models.IntegerField(blank=True, null=True)),
            ],
            options={
                "db_table": "llm_requests",
                "indexes": [
                    models.Index(fields=["-started_at"], name="llm_requests_recent"),
                    models.Index(fields=["user_id", "org_id", "-started_at"],
                                 name="llm_requests_mine"),
                    models.Index(fields=["session_id", "id"], name="llm_requests_chat"),
                    models.Index(fields=["turn_id"], name="llm_requests_turn"),
                    models.Index(fields=["purpose", "-started_at"], name="llm_requests_purpose"),
                    models.Index(fields=["request_hash"], name="llm_requests_same"),
                ],
            },
        ),
    ]
