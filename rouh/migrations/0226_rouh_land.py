"""The public site moved from rouh.it to rouh.land (task 165, `rouh/site.py`): the addresses a
Rouh keeps in its own database are moved with it, once, as it takes this code in.

A direct move (Petar, 2 November 2026): rouh.it sends nobody on and is retired, so a Rouh that
kept https://rouh.it/... would go on calling an address that stops answering. What is rewritten,
and only where it starts with exactly https://rouh.it or https://www.rouh.it:

- `rouh_birth.registry_url`, where this Rouh is registered for its birth, and the address a
  waiting account recovery is asked for at, `rouh_birth.pending["url"]`;
- `pool_membership.url`, where the Gene Pool is;
- `gene_registries.url`, the gene registry an organisation fetches shared genes from;
- `app_state`, a top-level "url" of what was last fetched or sent (the model standard, the rule
  defaults, the daily totals), which the pages show.

Nothing signed is touched: a card, a birth statement, an index or a gene's artifact is as the
registry signed it. Running it again changes nothing; each row it changes is logged, and how many
were changed is logged and said in the migrate command's own output.
"""
import json
import logging

from django.db import migrations

log = logging.getLogger("rouh.migrations")

OLD = ("https://rouh.it", "https://www.rouh.it")
NEW = "https://rouh.land"


def moved(address):
    """`address` on rouh.land when it is exactly on an old origin, else None (as `site.rewrite`,
    written out here so this migration never changes with that module)."""
    if not isinstance(address, str):
        return None
    text = address.strip()
    low = text.lower()
    for old in OLD:
        if low == old or (low.startswith(old) and low[len(old)] in "/?#"):
            return NEW + text[len(old):]
    return None


def forward(apps, schema_editor):
    changed = 0
    Birth = apps.get_model("rouh", "RouhBirth")
    for row in Birth.objects.all():
        fields = []
        new = moved(row.registry_url)
        if new:
            log.info("rouh.land: rouh_birth %s registry_url %s -> %s", row.id, row.registry_url, new)
            row.registry_url = new
            fields.append("registry_url")
        pending = row.pending if isinstance(row.pending, dict) else {}
        new = moved(pending.get("url"))
        if new:
            log.info("rouh.land: rouh_birth %s pending url %s -> %s", row.id, pending.get("url"), new)
            row.pending = {**pending, "url": new}
            fields.append("pending")
        if fields:
            row.save(update_fields=fields)
            changed += 1
    for model in ("PoolMembership", "GeneRegistry"):
        for row in apps.get_model("rouh", model).objects.all():
            new = moved(row.url)
            if new:
                log.info("rouh.land: %s %s url %s -> %s", model, row.id, row.url, new)
                row.url = new
                row.save(update_fields=["url"])
                changed += 1
    AppState = apps.get_model("rouh", "AppState")
    for row in AppState.objects.all():
        try:
            value = json.loads(row.value)
        except (TypeError, ValueError):
            continue
        new = moved(value.get("url")) if isinstance(value, dict) else None
        if new:
            log.info("rouh.land: app_state %s url %s -> %s", row.key, value["url"], new)
            value["url"] = new
            row.value = json.dumps(value)
            row.save(update_fields=["value"])
            changed += 1
    said = f"rouh.land: {changed} stored address{'' if changed == 1 else 'es'} moved from rouh.it"
    log.warning(said)
    print(f"\n  {said}", end="")


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0225_his_word'),
    ]

    operations = [
        migrations.RunPython(forward, migrations.RunPython.noop),
    ]
