"""The ask a raised one serves (`MailAsk.serves`).

Petar, 15 October 2026 (fr_1dd66d24e1f6), on a trusted contact's case: what the work needs was shown in
the work's own long sentence, three times, and never in the contact's words. The start already says which
ask each need serves (`case_report` needs[].ask); it was dropped when the need was raised. It is
kept now, and filled in here for the needs raised before, from the start's reports the case and
its earlier attempts kept: a need's quote is "Needed by <who>: <what>", so the report's entry
whose words end it is the one.
"""
from django.db import migrations, models


def _norm(text) -> str:
    return " ".join(str(text or "").split())


def backfill(apps, schema_editor):
    MailAsk = apps.get_model("rouh", "MailAsk")
    MailCase = apps.get_model("rouh", "MailCase")
    MailCaseAttempt = apps.get_model("rouh", "MailCaseAttempt")
    raised = MailAsk.objects.filter(source="work", serves="")
    for case_id in sorted(set(raised.values_list("case_id", flat=True))):
        case = MailCase.objects.filter(id=case_id).first()
        if case is None:
            continue
        reports = [case.work_report or {}]
        for row in MailCaseAttempt.objects.filter(case_id=case_id).order_by("number"):
            reports.append(((row.snapshot or {}).get("work_report")) or {})
        needs = [n for r in reports if isinstance(r, dict)
                 for n in (r.get("needs") or []) if isinstance(n, dict) and n.get("ask")]
        idents = set(MailAsk.objects.filter(case_id=case_id).values_list("ident", flat=True))
        for a in raised.filter(case_id=case_id):
            quote = _norm(a.quote)
            hit = next((n for n in needs if _norm(n.get("what"))
                        and quote.endswith(_norm(n.get("what"))[:600])
                        and str(n["ask"]).strip("[] ") in idents), None)
            if hit is not None:
                a.serves = str(hit["ask"]).strip("[] ")
                a.save(update_fields=["serves"])


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0158_task_origin'),
    ]

    operations = [
        migrations.AddField(
            model_name='mailask',
            name='serves',
            field=models.TextField(blank=True, db_default='', default=''),
        ),
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
