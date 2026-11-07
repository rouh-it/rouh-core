"""Who made a task: the person, somebody else, or one of Rouh's processes (`rouh/task_origin.py`).

Petar, 16 October 2026: "Whatever any process is doing should be created without me being the
gate. I just don't want to see it by default in the task browser." So the origin every task
already keeps beside its status (migration 0158) says which of three made it, in `made`:
"person", "other" or "process:<name>". The marks made before this say it too: one made for
somebody else is "other", and one Petar said is his own is "person". Nothing else is changed:
a task nothing is said about is still his.

A run keeps the process that started it (`run.made_by`, "" for one started from his own
words), so the steps its checkout brings in when it lands are that process's.
"""
from django.db import migrations, models


def _said(apps, schema_editor):
    Task = apps.get_model("rouh", "Task")
    for row in Task.objects.exclude(origin={}).only("id", "origin"):
        origin = dict(row.origin or {})
        if origin.get("made"):
            continue
        if origin.get("mine"):
            origin["made"] = "person"
        elif origin.get("for"):
            origin["made"] = "other"
        else:
            continue
        Task.objects.filter(id=row.id).update(origin=origin)


def _unsaid(apps, schema_editor):
    Task = apps.get_model("rouh", "Task")
    for row in Task.objects.exclude(origin={}).only("id", "origin"):
        origin = dict(row.origin or {})
        if str(origin.get("made") or "").startswith("process:"):
            Task.objects.filter(id=row.id).update(origin={})
        elif "made" in origin:
            origin.pop("made")
            Task.objects.filter(id=row.id).update(origin=origin)


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0163_ask_blocker'),
    ]

    operations = [
        migrations.AddField(
            model_name='run',
            name='made_by',
            field=models.TextField(blank=True, db_default='', default=''),
        ),
        migrations.RunPython(_said, _unsaid),
    ]
