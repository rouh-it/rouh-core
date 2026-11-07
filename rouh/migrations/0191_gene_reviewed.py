"""Mutations has New: the genes Petar has not decided anything about yet (`rouh/evolution.py`).

Petar, 19 October 2026: "Items I have never seen that I need to decide if I want them for trial
or if they should continue trial, and items I have decided I want trial for them. Currently those
two mix and I keep reading again and again the same items." So a gene version keeps when he first
decided about it and what. A version that already has a decision of his in its history counts as
reviewed, at the time and with the kind of his latest one; every other is in New if it is on
trial. No gene is changed otherwise, and no event is added or rewritten.
"""
from django.db import migrations, models

#: His decisions, as the history records them (`by` "person"). `tried` was Try it now, which
#: decides nothing.
DECIDED = ("kept", "kept_mutation", "kept_original", "turned_off", "rejected", "turned_on",
           "later", "mutation_requested", "booked", "keep_anyway", "trial_started",
           "trial_changed", "seen", "kept_in_trial")


def reviewed(apps, schema_editor):
    Gene = apps.get_model("rouh", "MutationsGene")
    Event = apps.get_model("rouh", "MutationsGeneEvent")
    for g in Gene.objects.all():
        e = (Event.objects.filter(org_id=g.org_id, user_id=g.user_id, gene_id=g.id, by="person",
                                  kind__in=DECIDED).order_by("-at", "-id").first())
        if e is not None:
            Gene.objects.filter(id=g.id).update(reviewed_at=e.at, reviewed_as=e.kind)


class Migration(migrations.Migration):

    dependencies = [("rouh", "0190_gene_try_it_removed")]

    operations = [
        migrations.AddField(model_name="mutationsgene", name="reviewed_at",
                            field=models.FloatField(blank=True, null=True)),
        migrations.AddField(model_name="mutationsgene", name="reviewed_as",
                            field=models.TextField(blank=True, default="")),
        migrations.RunPython(reviewed, migrations.RunPython.noop),
    ]
