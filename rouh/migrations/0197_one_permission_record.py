"""One permission record: a trusted contact's authority to decide moves into the share rows.

Petar, 21 October 2026: delegate grants (`delegations`) and task and page shares
(`page_guests`) become one record, read < edit < decide, that every check reads
(`rouh/task_access.py`, DELEGATION.md). Every active grant becomes a row of `page_guests` on
its work's folder ("_task/<folder>", a quest by its task's), for the contact's first ticked
address: a row that is already there is raised to the grant's level and made the person's own
(no longer a tick's), and keeps its link. Nothing is emailed. Each delegate action keeps the
record it was done under, by the row's token. Revoked grants were history only; their
revokes stay in `delegate_acts`.

The counts are printed: grants found, rows made, rows raised, and grants that could not be
moved (with why); a grant that cannot be moved stops the migration rather than being lost.
"""

import secrets
import time

from django.db import migrations, models

RANK = {"view": 1, "edit": 2, "decide": 3}


def _folder(apps, d):
    Task = apps.get_model("rouh", "Task")
    LongWork = apps.get_model("rouh", "LongWork")
    task_id = d.target
    if d.kind == "quest":
        q = LongWork.objects.filter(id=int(d.target)).first() if str(d.target).isdigit() else None
        task_id = q.task_id if q is not None else ""
    if not task_id:
        return ""
    return Task.objects.filter(id=task_id).values_list("folder", flat=True).first() or ""


def forwards(apps, schema_editor):
    Delegation = apps.get_model("rouh", "Delegation")
    DelegateAct = apps.get_model("rouh", "DelegateAct")
    PageGuest = apps.get_model("rouh", "PageGuest")
    TrustedAddress = apps.get_model("rouh", "TrustedAddress")
    User = apps.get_model("rouh", "User")
    found = made = raised = same = 0
    lost = []
    tokens = {}
    for d in Delegation.objects.filter(state="active").order_by("id"):
        found += 1
        address = (TrustedAddress.objects.filter(contact_id=d.contact_id)
                   .order_by("id").values_list("address", flat=True).first() or "")
        address = str(address or "").strip().lower()
        folder = _folder(apps, d)
        if not address or not folder:
            lost.append(f"grant {d.id} ({d.kind} {d.number}): "
                        + ("its contact has no address" if not address else
                           "its work has no folder"))
            continue
        rel = "_task/" + folder
        role = "decide" if d.power == "decide" else "view"
        by = "rouh" if d.granted_by == "rouh" else "owner"
        row = PageGuest.objects.filter(user_id=d.user_id, org_id=d.org_id, rel=rel,
                                       email=address).first()
        if row is None:
            account = User.objects.filter(email__iexact=address, is_active=True).first()
            row = PageGuest.objects.create(
                token=secrets.token_urlsafe(24), user_id=d.user_id, org_id=d.org_id, rel=rel,
                title=(d.title or "")[:200], email=address, role=role,
                guest_id=str(account.pk) if account is not None else "",
                created_at=d.created_at or time.time(), via="", pending=d.pending or "",
                granted_by=by)
            made += 1
        else:
            want = role if RANK.get(role, 0) > RANK.get(row.role, 0) else row.role
            if want != row.role or row.via:
                raised += 1
            else:
                same += 1
            PageGuest.objects.filter(token=row.token).update(
                role=want, via="", pending=d.pending or row.pending or "", granted_by=by)
        tokens[d.id] = row.token
    if lost:
        raise RuntimeError("These grants could not be moved into the one permission record, "
                           "so nothing was changed: " + "; ".join(lost))
    for a in DelegateAct.objects.exclude(delegation_id=None).only("id", "delegation_id"):
        token = tokens.get(a.delegation_id, "")
        if token:
            DelegateAct.objects.filter(id=a.id).update(grant=token)
    print(f"\n  one permission record: {found} active grant(s); {made} row(s) made, "
          f"{raised} raised or made the person's own, {same} already at that level")


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0196_page_definitions"),
    ]

    operations = [
        migrations.AddField(
            model_name="pageguest",
            name="pending",
            field=models.TextField(blank=True, db_default="", default=""),
        ),
        migrations.AddField(
            model_name="pageguest",
            name="granted_by",
            field=models.TextField(blank=True, db_default="", default=""),
        ),
        migrations.AddField(
            model_name="delegateact",
            name="grant",
            field=models.TextField(blank=True, db_default="", default=""),
        ),
        migrations.AddField(
            model_name="mailask",
            name="task_needs",
            field=models.TextField(blank=True, db_default="", default=""),
        ),
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
