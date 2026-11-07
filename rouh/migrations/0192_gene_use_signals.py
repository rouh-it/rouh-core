"""How a gene says it was used is one contract (`rouh/genes/signals.py`, GENES.md "How a gene says it
was used").

Petar, 19 October 2026: Sources checked's trial offered "Its own code saying you used it", ticked,
though its code never said anything, so the box could never count, and its one real use, opening
its Sources page at 03:46 that night, was not counted because that box was unticked. Since then a
gene's trial counts only the use signals it declares in its code, each in its own words, and a new
trial starts with all of them ticked.

So, once:

* every use or run a gene's code reported before its points had names gets the name its gene now
  declares for that point (Printable PDF's three by where they came from, and every other gene's
  one), and Facts told on a page's, which is the person telling it something, is a use;
* every trial still running counts every signal its gene declares, and an ended trial keeps what it
  counted in the new names, with "its own code saying you used it" and "it running by itself"
  dropped where the gene has no such point; each running trial whose list changed gets a line in
  its history saying so;
* the gene's own list of what counts (`use`) and Parameters' kinds of use (`trial_counts`) are
  taken out: what counts is in the code now.
"""
import time

from django.db import migrations

#: (switch, kind it was reported as) -> the event it is now, and the kind that event is.
NAMED = {
    ("calendar_clash", "ran"): ("clash_named", "ran"),
    ("plain_words", "ran"): ("term_kept", "ran"),
    ("draft_edits", "ran"): ("edits_learned", "ran"),
    ("copies_in_step", "ran"): ("copies_named", "ran"),
    ("short_answers", "ran"): ("kept_short", "ran"),
    ("asked_again", "ran"): ("offered_again", "ran"),
    ("page_facts", "ran"): ("fact_kept", "used"),
}


def _pdf_event(detail: str) -> str:
    if "from its menu" in detail:
        return "chat_pdf"
    if "from the button" in detail:
        return "page_pdf"
    return "asked_for_pdf"


def _keys(g, sig: dict) -> list[str]:
    out = [f"nav:{k}" for k in sig.get("nav", {})] + [f"route:{k}" for k in sig.get("routes", {})]
    out += [f"tool:{k}" for k in sig.get("tools", {})]
    out += [f"event:{k}" for k in sig.get("events", {})] + [f"event:{k}" for k in sig.get("runs", {})]
    if g.kind == "ask_for" and g.moment:
        out.append("taken")
    return out


def forward(apps, schema_editor):
    from rouh.genes import signals

    Gene = apps.get_model("rouh", "MutationsGene")
    Event = apps.get_model("rouh", "MutationsGeneEvent")
    switch_of = dict(Gene.objects.values_list("id", "switch"))
    for e in Event.objects.filter(kind__in=("used", "ran")):
        if (e.data or {}).get("event"):
            continue
        switch = switch_of.get(e.gene_id) or ""
        if switch == "page_pdf" and e.kind == "used":
            name, kind = _pdf_event(e.detail or ""), "used"
        elif (switch, e.kind) in NAMED:
            name, kind = NAMED[(switch, e.kind)]
        else:
            continue
        Event.objects.filter(id=e.id).update(kind=kind, data={**(e.data or {}), "event": name})
    now = time.time()
    for g in Gene.objects.all():
        t = dict(g.trial or {})
        if "counts" not in t:
            continue
        sig = signals.of_switch(g.switch)
        keys = _keys(g, sig)
        before = list(t["counts"])
        if g.state == "trial":
            after = keys
        else:
            wanted = set(before)
            if "used" in wanted:
                wanted |= {f"event:{k}" for k in sig.get("events", {})}
            if "ran" in wanted:
                wanted |= {f"event:{k}" for k in sig.get("runs", {})}
            after = [k for k in keys if k in wanted]
        if after == before:
            continue
        Gene.objects.filter(id=g.id).update(trial={**t, "counts": after})
        if g.state == "trial":
            words = {**{f"nav:{k}": v for k, v in sig.get("nav", {}).items()},
                     **{f"route:{k}": v for k, v in sig.get("routes", {}).items()},
                     **{f"tool:{k}": v for k, v in sig.get("tools", {}).items()},
                     **{f"event:{k}": v for k, v in sig.get("events", {}).items()},
                     **{f"event:{k}": v for k, v in sig.get("runs", {}).items()},
                     "taken": "You took it when Rouh offered it"}
            Event.objects.create(
                org_id=g.org_id, user_id=g.user_id, gene_id=g.id, kind="trial_changed", by="rouh",
                at=now, data={"before": {"counts": before}, "after": {"counts": after}},
                detail="What counts as using it is now everything it declares: "
                       + "; ".join(words.get(k, k) for k in after) + ".")


class Migration(migrations.Migration):

    dependencies = [("rouh", "0191_gene_reviewed")]

    operations = [
        migrations.RunPython(forward, migrations.RunPython.noop),
        migrations.RemoveField(model_name="mutationsgene", name="use"),
        migrations.RemoveField(model_name="evolutionsetting", name="trial_counts"),
    ]
