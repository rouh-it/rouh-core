"""One access level per task per person (`rouh/task_access.py`, MAIL.md D28).

Petar, 16 October 2026 (fr_5825d8e52d0a): "If she is allowed, she should be allowed from
anywhere", and when the work cannot change a task she may not edit, "a grant should not be
offered, permission change should be offered".

- `page_guests.via` says who keeps a share: "" a person chose it, "tick" a ticked column or
  project on the contact's page keeps it.
- `mail_asks.task` is the task an ask adds to or changes, whose edit permission it needs.

The Edit rights grant (`edit_tasks`) goes: it was a second way of saying a contact may change
a task, given with Shared task, and changing a task is the task's own permission now. Nothing
it did is undone: the tasks it shared with somebody to edit stay shared with them to edit.

The Shared task grant's words say what it is now, as a new version with the old one kept: making
a task they and the owner both add to, and never adding to one.

The one ask raised before this that was such a permission and was put to the owner as a new
grant - one case's request for a contact's access to an existing numbered task, still open - is
given its task here, so it is offered as a permission change of that task and not as a grant. An ask is taken only when it waits, was raised by the work,
names no grant, and says it is about access to one numbered task.
"""
import re
import time

from django.db import migrations, models

_ABOUT = re.compile(r"\b(access|permission|shared[- ]task|edit rights?)\b", re.I)
_TASK = re.compile(r"\btask (\d{1,5})\b", re.I)


def tasks_of_raised(apps, schema_editor):
    MailAsk = apps.get_model("rouh", "MailAsk")
    for a in MailAsk.objects.filter(source="work", grant="", gone=False,
                                    status="waiting_for_petar"):
        words = " ".join(str(x or "") for x in (a.do, a.label, a.quote))
        numbers = set(_TASK.findall(words))
        if len(numbers) == 1 and _ABOUT.search(words):
            a.task = numbers.pop()
            a.new_grant = {}
            a.save(update_fields=["task", "new_grant"])


def shared_task_words(apps, schema_editor):
    from rouh import grants

    Grant = apps.get_model("rouh", "Grant")
    GrantVersion = apps.get_model("rouh", "GrantVersion")
    now = time.time()
    new = (grants.SHARED_TASK_TITLE, grants.SHARED_TASK_DESCRIPTION, grants.SHARED_TASK_PROMPT)
    for row in Grant.objects.filter(key="shared_task"):
        if (row.title, row.description, row.prompt) == new:
            continue
        row.title, row.description, row.prompt = new
        row.revision += 1
        row.updated_at = now
        row.save(update_fields=["title", "description", "prompt", "revision", "updated_at"])
        parent = Grant.objects.filter(id=row.parent_id).first() if row.parent_id else None
        GrantVersion.objects.create(
            org_id=row.org_id, grant=row, revision=row.revision, name=row.name, title=row.title,
            description=row.description, prompt=row.prompt,
            parent_key=parent.key if parent is not None else "", at=now, by="migration 0162",
            why="Making a shared task only: adding to a task is that task's own permission "
                "(Petar, 16 October 2026, fr_5825d8e52d0a).", case_key="")


def edit_rights_gone(apps, schema_editor):
    Grant = apps.get_model("rouh", "Grant")
    Grant.objects.filter(key="edit_tasks").delete()


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0161_contact_grant_calendars'),
    ]

    operations = [
        migrations.AddField(
            model_name='pageguest',
            name='via',
            field=models.TextField(blank=True, db_default='', default=''),
        ),
        migrations.AddField(
            model_name='mailask',
            name='task',
            field=models.TextField(blank=True, db_default='', default=''),
        ),
        migrations.RunPython(tasks_of_raised, migrations.RunPython.noop),
        migrations.RunPython(edit_rights_gone, migrations.RunPython.noop),
        migrations.RunPython(shared_task_words, migrations.RunPython.noop),
    ]
