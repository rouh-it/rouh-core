import time

from django.db import migrations, models

#: Whose a heartbeat row with no organisation is (`rouh.models.accounts.DEFAULT_ORG_ID`).
DEFAULT_ORG_ID = "org-default"
#: What the Heartbeat page says on a Rouh this update turned the heartbeat off on
#: (`heartbeat.view`, `state.turned_off`).
TURNED_OFF = ("Turned off on 18 November 2026, when beats became background jobs: this Rouh has no "
              "quests, and none of its beats ever left you a note or a Telegram, so it was spending "
              "for nothing. Turn it on here whenever you want it.")
BY = "turned off by the update to beats as jobs: no quests, and no beat ever told the owner anything"


def move_to_jobs(apps, schema_editor):
    """Every Rouh moves to beats that are background jobs (`rouh/heartbeat_jobs.py`).

    What was waiting for the old kind of beat is cut to what still wakes the new one: a run's end
    wakes it only when the heartbeat or a quest started that run (`heartbeat_jobs.run_wakes`), so
    the ends of runs the owner started are dropped from what waits. And a Rouh with no quests
    whose beats never left a note or a Telegram has its heartbeat turned off, with a line on its
    Heartbeat page that says so (Petar, 18 November 2026, task 182)."""
    Heart = apps.get_model("rouh", "HeartbeatState")
    Beat = apps.get_model("rouh", "HeartbeatBeat")
    Work = apps.get_model("rouh", "LongWork")
    State = apps.get_model("rouh", "LeanState")
    Choice = apps.get_model("rouh", "LeanChoice")
    now = time.time()
    for row in Heart.objects.all():
        own = dict(row.own or {})
        mine = set(own.get("runs") or [])
        for w in Work.objects.filter(user_id=row.user_id, org_id=row.org_id):
            mine |= set((w.own or {}).get("runs") or []) if isinstance(w.own, dict) else set()
        kept = [e for e in (row.pending or []) if not isinstance(e, dict) or e.get("kind") != "run"
                or str(e.get("run") or "") in mine]
        fields = {}
        if len(kept) != len(row.pending or []):
            fields["pending"] = kept
        quests = Work.objects.filter(user_id=row.user_id, org_id=row.org_id).exists()
        told = Beat.objects.filter(user_id=row.user_id, org_id=row.org_id,
                                   outcome__in=("note", "telegram")).exists()
        if not quests and not told:
            org = str(row.org_id or "") or DEFAULT_ORG_ID
            choice = Choice.objects.filter(org_id=org, item="heartbeat").first()
            creator = State.objects.filter(org_id=org, preset="creator").exists()
            on = (choice.mode == "on") if choice is not None else creator
            if on:
                if choice is not None:
                    Choice.objects.filter(org_id=org, item="heartbeat").update(
                        mode="off", by=BY, updated_at=now)
                else:
                    Choice.objects.create(org_id=org, item="heartbeat", mode="off", days=None,
                                          by=BY, updated_at=now)
                own["turned_off"] = {"at": now, "said": TURNED_OFF}
                fields["own"] = own
        if fields:
            fields["updated_at"] = now
            Heart.objects.filter(id=row.id).update(**fields)


class Migration(migrations.Migration):
    """Beats become background jobs: a beat's job, what it was about, each subject's own record of
    what the heartbeat did about it, and a $1 daily cap on a new install."""

    dependencies = [("rouh", "0260_synapse_master_owner_only")]
    operations = [
        migrations.AddField("heartbeatbeat", "kind",
                            models.TextField(default="turn", db_default="turn")),
        migrations.AddField("heartbeatbeat", "run_id",
                            models.TextField(blank=True, default="", db_default="")),
        migrations.AddField("heartbeatbeat", "subjects",
                            models.JSONField(default=list, db_default=[])),
        migrations.AlterField("heartbeatstate", "daily_cap",
                              models.DecimalField(max_digits=10, decimal_places=2, default=1)),
        migrations.CreateModel(
            name="HeartbeatSubject",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("user_id", models.TextField()),
                ("org_id", models.TextField()),
                ("kind", models.TextField()),
                ("ref", models.TextField()),
                ("title", models.TextField(blank=True, default="")),
                ("lines", models.JSONField(default=list)),
                ("updated_at", models.FloatField(default=0)),
            ],
            options={"db_table": "heartbeat_subjects"},
        ),
        migrations.AddConstraint(
            model_name="heartbeatsubject",
            constraint=models.UniqueConstraint(fields=["org_id", "user_id", "kind", "ref"],
                                               name="heartbeat_subject_one")),
        migrations.RunPython(move_to_jobs, migrations.RunPython.noop),
    ]
