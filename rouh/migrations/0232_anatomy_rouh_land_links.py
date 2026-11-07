"""Anatomy's sixth group, Rouh Land Account (4 November 2026): the notices a Rouh keeps still
pointing at a section that moved are pointed at where it is now, once.

Petar: "when I say move, don't leave backup forwarding links". So a moved section's old address is
not found (`genes.MOVED`), and nothing Rouh itself keeps may still lead there. A notice - a shared
gene blocked or with an update, a contact to look at - holds its address in `link` and in the
`href` of each of `links`. What is rewritten, only where an address starts with exactly one of
these (and is followed by nothing, `/`, `?` or `#`):

- `/settings/genes`, `/anatomy/meta/genes`              -> `/anatomy/rouh-land/gene-pool`
- `/settings/birthday`, `/anatomy/meta/birthday`        -> `/anatomy/rouh-land/rouh-profile`
- `/settings/models`, `/anatomy/behaviour/models`       -> `/anatomy/rouh-land/models`
- `/settings/trusted-contacts`, `/anatomy/connections/trusted-contacts`
                                                        -> `/anatomy/behaviour/trusted-contacts`
- `/settings/offline`, `/anatomy/meta/offline`          -> `/anatomy/behaviour/offline`

The addresses are written out here, so this migration never changes with the manifests. Running
it again changes nothing.
"""
import logging

from django.db import migrations

log = logging.getLogger("rouh.migrations")

MOVES = (
    (("/settings/genes", "/anatomy/meta/genes"), "/anatomy/rouh-land/gene-pool"),
    (("/settings/birthday", "/anatomy/meta/birthday"), "/anatomy/rouh-land/rouh-profile"),
    (("/settings/models", "/anatomy/behaviour/models"), "/anatomy/rouh-land/models"),
    (("/settings/trusted-contacts", "/anatomy/connections/trusted-contacts"), "/anatomy/behaviour/trusted-contacts"),
    (("/settings/offline", "/anatomy/meta/offline"), "/anatomy/behaviour/offline"),
)


def moved(address):
    """`address` where its section is now, or None when it names no moved section."""
    if not isinstance(address, str):
        return None
    for olds, new in MOVES:
        for old in olds:
            if address == old or (address.startswith(old) and address[len(old)] in "/?#"):
                return new + address[len(old):]
    return None


def forward(apps, schema_editor):
    Notice = apps.get_model("rouh", "Notice")
    changed = 0
    for row in Notice.objects.all().only("id", "link", "links").iterator():
        fields = []
        new = moved(row.link)
        if new:
            row.link = new
            fields.append("link")
        if isinstance(row.links, list):
            links, touched = [], False
            for one in row.links:
                href = one.get("href") if isinstance(one, dict) else None
                to = moved(href)
                if to:
                    one = {**one, "href": to}
                    touched = True
                links.append(one)
            if touched:
                row.links = links
                fields.append("links")
        if fields:
            row.save(update_fields=fields)
            changed += 1
    if changed:
        log.info("Anatomy, Rouh Land Account: %s notices pointed at where their section is now", changed)


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0231_message_branches"),
    ]

    operations = [
        migrations.RunPython(forward, migrations.RunPython.noop),
    ]
