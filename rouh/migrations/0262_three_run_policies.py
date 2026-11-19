"""The job modes nobody used are taken out: a run works under "one", "auto" or "self".

Petar, 19 November 2026: "Delete the ones we don't use." Of the seven policies a run
could carry, three were in use: "one" (a run of the one program, which every server
job had become), "auto" (`assistant_job`) and "self" (`improve_myself`). "safe",
"local-only", "direct-pr" and "yolo" go.

A run row that carried one of the four keeps showing, under what it became
(`objects.RETIRED_POLICIES`): "yolo" was a server job, and a server job is a run of
the one program, so "one"; the other three were workers that did not push, which is
"auto". Then the CHECK on the column is narrowed to the three, and the column's
default, which was "safe", is "auto".

The crew's own rows (`crewmates`) are left as they were: they are the crew's history
and have no CHECK, and a worker started again from one runs under the mode its old
one became (`crew.mode_now`).
"""
from django.db import migrations, models

#: As `objects.RETIRED_POLICIES` says it on the day, written out so this
#: migration means the same thing whatever that list becomes.
RETIRED = {"yolo": "one", "safe": "auto", "local-only": "auto", "direct-pr": "auto"}
KEPT = ("one", "auto", "self")


def map_retired(apps, schema_editor):
    Run = apps.get_model("rouh", "Run")
    for old, new in RETIRED.items():
        Run.objects.filter(policy=old).update(policy=new)


class Migration(migrations.Migration):

    dependencies = [("rouh", "0261_heartbeat_beats_are_jobs")]

    operations = [
        migrations.RunPython(map_retired, migrations.RunPython.noop),
        migrations.RemoveConstraint(model_name="run", name="run_policy_known"),
        migrations.AddConstraint(
            model_name="run",
            constraint=models.CheckConstraint(condition=models.Q(("policy__in", KEPT)),
                                              name="run_policy_known")),
        migrations.AlterField(model_name="run", name="policy",
                              field=models.TextField(default="auto")),
    ]
