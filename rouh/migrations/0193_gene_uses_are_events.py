"""A gene is used only when its own code says so (`rouh/genes/signals.py`, GENES.md "How a gene says
it was used").

Petar, 19 October 2026, the evening after 0192: opening a page, pressing a link or Rouh calling a
tool is not using a gene, and neither is being taken when offered or running by itself as a box of
its own. The only use that counts is one of the events the gene declares, reported by its code. A
gene that is about a page reports opening it from that page's code. So, once:

* a reported use or run is given the kind its gene now declares it as (Plain words keeping a term
  he asked about is a use now, and so are the others he does something for);
* Sources checked's openings of a task's Sources, which the event log kept before its page
  reported them, become the uses its page now reports, `sources_opened`, from when the gene came,
  a burst within ten minutes being one, so its opening at 03:46 on 19 October counts;
* every running trial counts exactly the events its gene declares, with a line in its history
  saying so, and an ended trial keeps only those of them it counted.
"""
import time

from django.db import connection, migrations

SAME_USE = 600


def _gene_of(Gene, switch, org_id, user_id):
    return (Gene.objects.filter(org_id=org_id, user_id=user_id, switch=switch)
            .exclude(state__in=("removed", "replaced")).order_by("-version").first())


def forward(apps, schema_editor):
    from rouh.genes import signals

    Gene = apps.get_model("rouh", "MutationsGene")
    Event = apps.get_model("rouh", "MutationsGeneEvent")
    switch_of = dict(Gene.objects.values_list("id", "switch"))
    for e in Event.objects.filter(kind__in=("used", "ran")):
        name = (e.data or {}).get("event")
        kind = signals.code_kind(switch_of.get(e.gene_id) or "", name) if name else ""
        if kind and kind != e.kind:
            Event.objects.filter(id=e.id).update(kind=kind)

    for org_id, user_id in set(Gene.objects.filter(switch="source_check").values_list("org_id", "user_id")):
        g = _gene_of(Gene, "source_check", org_id, user_id)
        if g is None:
            continue
        with connection.cursor() as cur:
            cur.execute("SELECT to_regclass('analytics.event') IS NOT NULL")
            if not cur.fetchone()[0]:
                break
            cur.execute(
                "SELECT extract(epoch from occurred_at), props->>'path' FROM analytics.event "
                "WHERE org_id = %s AND user_id = %s AND name = 'ui.open' AND object_type = 'place' "
                "AND object_id = 'sources' AND props->>'path' LIKE '/sources/%%' "
                "AND occurred_at >= to_timestamp(%s) ORDER BY occurred_at",
                [org_id, user_id, g.made_at or 0])
            opened = [(float(at), path) for at, path in cur.fetchall()]
        have = list(Event.objects.filter(gene_id=g.id, kind="used", data__event="sources_opened")
                    .values_list("at", flat=True))
        last = None
        for at, path in opened:
            if last is not None and at - last <= SAME_USE:
                continue
            last = at
            if any(abs(at - h) <= SAME_USE for h in have):
                continue
            Event.objects.create(org_id=org_id, user_id=user_id, gene_id=g.id, kind="used", by="evidence",
                                 at=at, detail=f"opened {path[len('/sources/'):][:200]} (from the event log)",
                                 data={"event": "sources_opened"})

    now = time.time()
    for g in Gene.objects.all():
        t = dict(g.trial or {})
        if "counts" not in t:
            continue
        events = signals.of_switch(g.switch).get("events", {})
        keys = [f"event:{k}" for k in events]
        before = list(t["counts"])
        after = keys if g.state == "trial" else [k for k in keys if k in before or "used" in before]
        if after == before:
            continue
        Gene.objects.filter(id=g.id).update(trial={**t, "counts": after})
        if g.state == "trial":
            Event.objects.create(
                org_id=g.org_id, user_id=g.user_id, gene_id=g.id, kind="trial_changed", by="rouh",
                at=now, data={"before": {"counts": before}, "after": {"counts": after}},
                detail="A use counts only when its own code reports one; it counts: "
                       + ("; ".join(events[k] for k in events) or "nothing it declares") + ".")


class Migration(migrations.Migration):

    dependencies = [("rouh", "0192_gene_use_signals")]

    operations = [migrations.RunPython(forward, migrations.RunPython.noop)]
