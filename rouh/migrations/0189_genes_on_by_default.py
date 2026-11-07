"""Every gene is on by default, on trial (`rouh/evolution.py`).

Petar, 18 October 2026: "The gene automatic creation and evaluation should run automatically
without my inputs ... Everything that is produced should be ON by default. So there are genes
in trial and genes out of trial." So every gene still waiting on his answer - built and off,
already on and not answered, left for later, booked, or waiting on a change he asked for - is
switched on and starts its trial today, with Parameters' length and uses needed, every use it
has counting, and comes up in the morning deck to look at. A gene kept, turned off or rejected
is left as it is.
"""
import time

from django.db import migrations

WAITING = ("candidate", "review_on", "later", "mutation", "booked")


def on_trial(apps, schema_editor):
    Gene = apps.get_model("rouh", "MutationsGene")
    Event = apps.get_model("rouh", "MutationsGeneEvent")
    Switch = apps.get_model("rouh", "FeatureSwitch")
    Setting = apps.get_model("rouh", "EvolutionSetting")
    now = time.time()
    for g in Gene.objects.filter(state__in=WAITING):
        row = Setting.objects.filter(org_id=g.org_id, user_id=g.user_id).first()
        trial = {"days": (row.trial_days if row else 0) or 7, "needed": (row.trial_needed if row else 0) or 1}
        Gene.objects.filter(id=g.id).update(state="trial", trial_started_at=now, extended_at=None,
                                            trial=trial, verdict="", answered_at=None, before="",
                                            released_at=g.released_at or now, updated_at=now)
        if g.switch:
            Switch.objects.filter(org_id=g.org_id, name=g.switch).update(
                on=True, changed_by="Mutations: on by default, on trial", updated_at=now)
        Event.objects.create(org_id=g.org_id, user_id=g.user_id, gene_id=g.id, kind="trial_started",
                             by="rouh", at=now, data={},
                             detail=f"On by default: switched on, and its trial of {trial['days']} days started.")


class Migration(migrations.Migration):

    dependencies = [("rouh", "0188_gene_trial_settings")]

    operations = [migrations.RunPython(on_trial, migrations.RunPython.noop)]
