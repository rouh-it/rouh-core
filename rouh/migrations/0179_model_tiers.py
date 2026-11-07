"""Three tiers and a tier for every use, in place of two model pairs and a model per use
and per chat (`rouh/modeldefaults.py`, `rouh/modelstandard.py`).

Petar, 18 October 2026: "map each current per-use model to the nearest tier if it is one
of the three tier models, otherwise to the use's recommended tier." So, for each
organisation's row:

- the old default pair is the use "chats" and the old General pair the use "general";
- every model picked for a use, and those two, becomes the tier whose model it is when it
  is one of the three tier models (Cheaper GPT-6 Luna, Recommended Opus 5.5, Best GPT-6
  Astra), and otherwise the use's recommended tier;
- a use that followed the default, or is on its recommended tier, is written down as
  nothing at all, so it goes on following the standard: only a real difference is kept;
- the wake-up check that was off stays off.

The levels that came with the old pairs are dropped: a model thinks at the level that comes
with it now. So is the model picked per chat in the box beside the composer, which is gone.
The tiers and the recommended tiers are copied here as they were in the standard of this
day (`model_standard.json`, revision 2026-10-18.1), so this migration means the same thing
whatever the standard says later.
"""

from django.db import migrations, models

TIER_OF_MODEL = {"gpt-6-luna": "cheaper", "claude-opus-5-5": "recommended", "claude-opus-5": "recommended",
                 "gpt-6-astra": "best"}

RECOMMENDED = {
    "general": "recommended", "chats": "recommended", "chat_title": "cheaper", "filing": "cheaper",
    "reminder_title": "cheaper", "reminder_words": "cheaper", "heartbeat_check": "off",
    "heartbeat_decide": "recommended", "code_runs": "recommended", "merge_pass": "recommended",
    "codex_runs": "recommended", "nightly_feature_run": "recommended",
    "nightly_refactor_run": "recommended", "workers": "recommended", "triage": "recommended",
    "run_summary": "cheaper", "subagent": "recommended", "askai": "recommended",
    "comment_pass": "recommended", "source_check": "recommended", "gene_question": "recommended",
    "gene_writer": "cheaper", "gene_eval": "recommended", "gene_match": "recommended",
    "case_fix_run": "recommended", "case_ask": "recommended", "slack_promises": "cheaper",
    "slack_decisions": "recommended", "goal_split": "recommended", "goal_revise": "recommended",
    "morning_brief": "recommended", "meeting_brief": "recommended",
    "meeting_pick_words": "cheaper", "meeting_next": "recommended",
    "answered_in_chat": "cheaper", "control_room": "recommended",
}


def tier_for(use: str, value: str) -> str:
    """The tier an old pick becomes, or "" for following the standard."""
    value = str(value or "").strip()
    if not value or value == "default":
        return ""
    if value == "off":
        tier = "off" if use == "heartbeat_check" else ""
    else:
        tier = TIER_OF_MODEL.get(value) or RECOMMENDED.get(use, "recommended")
    return "" if tier == RECOMMENDED.get(use, "recommended") else tier


def to_tiers(apps, schema_editor):
    ModelDefaults = apps.get_model("rouh", "ModelDefaults")
    for row in ModelDefaults.objects.all():
        old = dict(row.uses or {})
        old["chats"] = row.default_model
        old["general"] = row.general_model
        new = {}
        for use, value in old.items():
            if use not in RECOMMENDED:
                continue
            tier = tier_for(use, value)
            if tier:
                new[use] = tier
        row.uses = new
        row.tiers = {}
        row.save(update_fields=["uses", "tiers"])


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0178_reminder_about_rouh"),
    ]

    operations = [
        migrations.AddField(
            model_name="modeldefaults",
            name="tiers",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="modeldefaults",
            name="share_outcomes",
            field=models.BooleanField(default=True),
        ),
        migrations.RunPython(to_tiers, migrations.RunPython.noop),
        migrations.RemoveField(model_name="modeldefaults", name="default_model"),
        migrations.RemoveField(model_name="modeldefaults", name="default_effort"),
        migrations.RemoveField(model_name="modeldefaults", name="general_model"),
        migrations.RemoveField(model_name="modeldefaults", name="general_effort"),
        migrations.RemoveField(model_name="chat", name="model"),
        migrations.CreateModel(
            name="ModelOutcome",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("org_id", models.TextField()),
                ("user_id", models.TextField(blank=True, default="")),
                ("call", models.TextField(unique=True)),
                ("session_id", models.TextField(blank=True, default="")),
                ("use", models.TextField()),
                ("tier", models.TextField(blank=True, default="")),
                ("model", models.TextField()),
                ("effort", models.TextField(blank=True, default="")),
                ("outcome", models.TextField(default="pending")),
                ("signal", models.TextField(blank=True, default="")),
                ("requests", models.IntegerField(default=0)),
                ("cost_usd", models.FloatField(blank=True, null=True)),
                ("latency_ms", models.IntegerField(blank=True, null=True)),
                ("started_at", models.FloatField()),
                ("ended_at", models.FloatField(blank=True, null=True)),
                ("settled_at", models.FloatField(blank=True, null=True)),
                ("counted_on", models.TextField(blank=True, default="")),
            ],
            options={
                "db_table": "model_outcome",
                "indexes": [
                    models.Index(fields=["org_id", "outcome"], name="model_outcome_open"),
                    models.Index(fields=["session_id", "-started_at"], name="model_outcome_chat"),
                ],
            },
        ),
    ]
