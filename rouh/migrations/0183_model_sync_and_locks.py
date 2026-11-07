"""Two models a tier, Daily for Recommended, Custom, locks, and sync with the standard
(`rouh/modeldefaults.py`), Petar, the evening of 18 October 2026.

- `sync`, `manual` and `locked` are new: every organisation starts synced, with no manual
  set and nothing locked, which is what it had.
- The middle tier is called Daily now. A tier kept as "recommended", and a use kept on
  "recommended", are renamed "daily", and so is the tier written down on every call
  (`model_outcome.tier`), so the router's "last tier" and the shared counts read the same.
- A tier kept as one model becomes that model as its company's pick and the main one;
  the other company's pick is the one the standard of this day gave the tier
  (`model_standard.json`, revision 2026-10-18.2), copied here so that this migration means
  the same thing whatever the standard says later.
"""

from django.db import migrations, models

STAND_INS = {
    "cheaper": {"openai": "gpt-6-luna", "anthropic": "claude-haiku-4-5"},
    "daily": {"openai": "gpt-6.1-sol", "anthropic": "claude-opus-5-5"},
    "best": {"openai": "gpt-6-astra", "anthropic": "claude-fable-5-1"},
}


def _company(model: str) -> str:
    return "openai" if str(model).startswith(("gpt-", "o1", "o3", "o4", "chatgpt-")) else "anthropic"


def forward(apps, schema_editor):
    ModelDefaults = apps.get_model("rouh", "ModelDefaults")
    for row in ModelDefaults.objects.all():
        tiers = {}
        for tier, value in dict(row.tiers or {}).items():
            tier = "daily" if tier == "recommended" else tier
            if tier not in STAND_INS:
                continue
            if isinstance(value, str) and value:
                c = _company(value)
                tiers[tier] = {**STAND_INS[tier], c: value, "main": c}
            elif isinstance(value, dict):
                tiers[tier] = value
        uses = {u: ("daily" if t == "recommended" else t) for u, t in dict(row.uses or {}).items()}
        row.tiers, row.uses = tiers, uses
        row.save(update_fields=["tiers", "uses"])
    Outcome = apps.get_model("rouh", "ModelOutcome")
    Outcome.objects.filter(tier="recommended").update(tier="daily")


def backward(apps, schema_editor):
    ModelDefaults = apps.get_model("rouh", "ModelDefaults")
    for row in ModelDefaults.objects.all():
        tiers = {}
        for tier, value in dict(row.tiers or {}).items():
            tier = "recommended" if tier == "daily" else tier
            tiers[tier] = value.get(value.get("main") or "anthropic") if isinstance(value, dict) else value
        uses = {u: ("recommended" if t == "daily" else t) for u, t in dict(row.uses or {}).items()}
        row.tiers, row.uses = tiers, uses
        row.save(update_fields=["tiers", "uses"])
    Outcome = apps.get_model("rouh", "ModelOutcome")
    Outcome.objects.filter(tier="daily").update(tier="recommended")


class Migration(migrations.Migration):

    dependencies = [("rouh", "0182_decision_line")]

    operations = [
        migrations.AddField("modeldefaults", "sync", models.BooleanField(default=True)),
        migrations.AddField("modeldefaults", "manual", models.JSONField(blank=True, default=dict)),
        migrations.AddField("modeldefaults", "locked", models.JSONField(blank=True, default=list)),
        migrations.RunPython(forward, backward),
    ]
