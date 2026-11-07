"""A task ticked on a trusted contact's page before 16 October 2026 is a record of read now.

Petar, 21 October 2026, on a contact's page: some tasks wore a grey "Can edit" and some a blue one,
"and nothing says what the difference is". The grey ones (63, 14, 10) were tasks ticked one by
one before a task's level was one record (533faf58): the tick was kept in the contact's
`grants`, beside the ticked columns and projects, and read as a floor of read. The one tree on
the contact's page has a level on every task row and keeps ticks for columns and projects
alone, so each task still ticked becomes what it always gave: a record of read on that task
(`page_guests`, role view), the contact's own and no tick's. A task that already has a record of
theirs keeps it as it is. Nothing anybody may do changes.
"""

import secrets
import time

from django.db import migrations


def forward(apps, schema_editor):
    TrustedContact = apps.get_model("rouh", "TrustedContact")
    TrustedAddress = apps.get_model("rouh", "TrustedAddress")
    PageGuest = apps.get_model("rouh", "PageGuest")
    Task = apps.get_model("rouh", "Task")
    for contact in TrustedContact.objects.all():
        grants = [str(g) for g in contact.grants or []]
        tasks = {t.id: t for t in Task.objects.filter(id__in=grants)}
        if not tasks:
            continue
        addresses = list(TrustedAddress.objects.filter(contact_id=contact.id)
                         .order_by("id").values_list("address", flat=True))
        for ident, task in tasks.items():
            if not task.folder or not addresses:
                continue
            rel = "_task/" + task.folder.strip("/")
            mine = PageGuest.objects.filter(user_id=contact.user_id, org_id=contact.org_id,
                                            rel=rel, email__in=addresses)
            if mine.exists():
                mine.filter(via="tick").update(via="")
                continue
            PageGuest.objects.create(token=secrets.token_urlsafe(24), user_id=contact.user_id,
                                     org_id=contact.org_id, rel=rel, title=task.title or "",
                                     email=addresses[0], role="view", created_at=time.time())
        contact.grants = [g for g in grants if g not in tasks]
        contact.save(update_fields=["grants"])


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0200_builtin_rules"),
    ]

    operations = [
        migrations.RunPython(forward, migrations.RunPython.noop),
    ]
