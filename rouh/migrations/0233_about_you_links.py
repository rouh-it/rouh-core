"""You, Profile is About You (4 November 2026): the notices a Rouh keeps still pointing at its old
address are pointed at the new one, once.

Petar: "You -> Profile should be renamed to About You", and a move leaves no forwarding links, so
`/anatomy/you/profile` and `/settings/profile` are not found (`genes.MOVED`). A notice holds its
address in `link` and in the `href` of each of `links`; one that starts with exactly one of those
two (followed by nothing, `/`, `?` or `#`) is rewritten to `/anatomy/you/about-you`. The addresses
are written out here, so this migration never changes with the manifests. Running it again
changes nothing.
"""
import logging

from django.db import migrations

log = logging.getLogger("rouh.migrations")

OLD = ("/anatomy/you/profile", "/settings/profile")
NEW = "/anatomy/you/about-you"


def moved(address):
    """`address` at About You, or None when it does not name the old Profile."""
    if not isinstance(address, str):
        return None
    for old in OLD:
        if address == old or (address.startswith(old) and address[len(old)] in "/?#"):
            return NEW + address[len(old):]
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
        log.info("About You: %s notices pointed at its new address", changed)


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0232_anatomy_rouh_land_links"),
    ]

    operations = [
        migrations.RunPython(forward, migrations.RunPython.noop),
    ]
