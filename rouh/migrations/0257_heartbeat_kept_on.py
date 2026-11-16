import time

from django.db import migrations

#: Whose a heartbeat row with no organisation is (`rouh.models.accounts.DEFAULT_ORG_ID`).
DEFAULT_ORG_ID = "org-default"
BY = "kept on by the update: it was there before the heartbeat became a setting"


def keep_on(apps, schema_editor):
    """The heartbeat became a setting of what Rouh keeps and runs (task 185, step 185-05), Off on
    every new install. A Rouh that already has a heartbeat keeps it On, as its own choice, so nobody's
    heartbeat stops silently with the update; a paused one stays paused. The Creator Rouh's preset
    has it On already, so nothing is written there and nothing on its page changes. A fresh install
    has no heartbeat yet when this runs, and starts Off."""
    Heart = apps.get_model("rouh", "HeartbeatState")
    State = apps.get_model("rouh", "LeanState")
    Choice = apps.get_model("rouh", "LeanChoice")
    now = time.time()
    for org in sorted({str(o or "") or DEFAULT_ORG_ID for o in Heart.objects.values_list("org_id", flat=True)}):
        if State.objects.filter(org_id=org, preset="creator").exists():
            continue
        Choice.objects.get_or_create(org_id=org, item="heartbeat",
                                     defaults={"mode": "on", "days": None, "by": BY, "updated_at": now})


class Migration(migrations.Migration):
    """An existing Rouh's heartbeat kept On when the heartbeat became Off by default (`rouh/lean.py`)."""

    dependencies = [("rouh", "0256_forget_saved_chat_options")]
    operations = [migrations.RunPython(keep_on, migrations.RunPython.noop)]
