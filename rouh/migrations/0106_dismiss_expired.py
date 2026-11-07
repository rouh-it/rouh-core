"""Every approval and decision that ran out of time is dismissed, not opened again.

Petar, 8 October 2026: "No need to reopen expired - set them dismissed as I don't want to
deal with old stuff." Nothing runs out of time any more (0105). What already had is closed
as dismissed: nothing is done and nothing is sent, it is off the Decisions list and the
morning report, and it stays in its history as dismissed.

- A mail or Telegram case's approval, "expired" -> "dismissed". Its case stays blocked,
  so Redo is still on its page; its history says it was dismissed.
- A decision, `decisions.status` "expired" -> "dismissed", with a line in its history.

`dismiss` is a plain function, so a check can call it on a test database. It returns the
counts by source, which the deploy's log prints.
"""
import time

from django.db import migrations

APPROVAL_WHY = ("Closed on 8 October 2026 without a decision: it had run out of time under "
                "the old 48-hour limit. Nothing was done on it.")
CASE_SAID = ("Its decision, which had run out of time under the old 48-hour limit, was "
             "dismissed: nothing was done and nothing was sent. Redo starts it again if you "
             "want it.")
CASE_BLOCKER = ("Your decision was dismissed: it had run out of time under the old 48-hour "
                "limit. Nothing was done and nothing was sent.")
DECISION_SAID = ("Dismissed on 8 October 2026: it had run out of time, and old questions are "
                 "not brought back. Nothing was done on it.")


def dismiss(MailCase, MailApproval, MailCaseEvent, Decision, DecisionEvent) -> dict:
    """Dismiss every expired approval and decision. Returns {source: how many}."""
    now = time.time()
    counts: dict[str, int] = {}
    for approval in MailApproval.objects.filter(status="expired").order_by("id"):
        if not MailApproval.objects.filter(id=approval.id, status="expired").update(
                status="dismissed", why_invalid=APPROVAL_WHY):
            continue
        case = MailCase.objects.filter(id=approval.case_id, user_id=approval.user_id,
                                       org_id=approval.org_id).first()
        telegram = case is not None and str(case.message_id or "").startswith("tg:")
        key = "telegram case approvals" if telegram else "mail case approvals"
        counts[key] = counts.get(key, 0) + 1
        if case is None or (approval.attempt_no or 1) != (case.attempt_no or 1):
            continue                     # an earlier attempt, frozen by Redo: history only
        MailCaseEvent.objects.create(user_id=case.user_id, org_id=case.org_id, case_id=case.id,
                                     at=now, stage=case.stage, said=CASE_SAID)
        if case.stage == "blocked" and (case.blocker or "").startswith(
                "The approval expired after"):
            MailCase.objects.filter(id=case.id).update(blocker=CASE_BLOCKER, updated_at=now)
    for row in Decision.objects.filter(status="expired").order_by("id"):
        if not Decision.objects.filter(id=row.id, status="expired").update(
                status="dismissed", updated_at=now,
                result=((row.result + " " if row.result else "") + DECISION_SAID)[:2000]):
            continue
        DecisionEvent.objects.create(decision_id=row.id, user_id=row.user_id, org_id=row.org_id,
                                     kind="dismissed", by="rouh", detail=DECISION_SAID, at=now)
        key = f"decisions: {row.source}"
        counts[key] = counts.get(key, 0) + 1
    return counts


def forwards(apps, schema_editor):
    counts = dismiss(*(apps.get_model("rouh", name) for name in (
        "MailCase", "MailApproval", "MailCaseEvent", "Decision", "DecisionEvent")))
    said = ", ".join(f"{k} {v}" for k, v in sorted(counts.items())) or "none"
    print(f"\n  expired approvals and decisions dismissed: {sum(counts.values())} ({said})")


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0105_approvals_never_expire'),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
