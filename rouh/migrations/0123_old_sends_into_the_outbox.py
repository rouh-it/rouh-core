"""What Rouh sent to a contact before the outbox (11 October 2026), kept in the outbox as history.

The outbox decides what may go by what already went on the case (`rouh/mail_outbox.py`, D5):
at most one acknowledgement, never the same words twice, and no acknowledgement once an answer
went. Before this, a case's sends were only trace rows (`mail_case_traces`, kind "sent"), so a
case opened before the ledger could have been acknowledged again on the owner's Redo. Every one of
them that went is copied here as it was, under the case it now belongs to (a merged case's sends
under the case it was merged into). The first acknowledgement on a channel takes the key a new
one would, so the unique key itself refuses another. A case answered before traces were kept
(only `replied_at`) gets one reply row with the answer it had. Nothing is sent and nothing else
is changed.
"""

from django.db import migrations

#: Old trace modes, as the outbox's kinds.
KINDS = {"ack": "ack", "waiting": "ack", "reply": "reply", "status": "status",
         "follow_up": "follow_up"}
#: How a case that came on Telegram is keyed (`telegram_guests.CASE_PREFIX`), as it was.
TELEGRAM = "tg:"


def forwards(apps, schema_editor):
    MailCase = apps.get_model("rouh", "MailCase")
    MailCaseTrace = apps.get_model("rouh", "MailCaseTrace")
    MailOutbox = apps.get_model("rouh", "MailOutbox")

    cases = {c.id: c for c in MailCase.objects.all()}
    home = {c.id: (c.merged_into_id or c.id) for c in cases.values()}
    taken = set(MailOutbox.objects.values_list("org_id", "user_id", "key"))
    replied = set()
    for t in MailCaseTrace.objects.filter(kind="sent").order_by("at", "id"):
        data = t.data or {}
        if not data.get("ok") or t.case_id not in home:
            continue
        kind = KINDS.get(t.mode or "", "follow_up")
        case_id = home[t.case_id]
        channel = str(data.get("channel") or "email")
        key = f"{case_id}:ack:{channel}" if kind == "ack" else ""
        if not key or (t.org_id, t.user_id, key) in taken:
            key = f"{case_id}:old:{t.id}"
        if (t.org_id, t.user_id, key) in taken:
            continue
        taken.add((t.org_id, t.user_id, key))
        if kind in ("reply", "status", "follow_up"):
            replied.add(case_id)
        MailOutbox.objects.create(
            user_id=t.user_id, org_id=t.org_id, case_id=case_id, key=key,
            attempt=t.attempt or 0, kind=kind, channel=channel,
            to=str(data.get("to") or ""), text=str(data.get("text") or ""), files=[],
            ledger=[], state="sent", message_id=str(data.get("message_id") or ""),
            error="", thread_before=[], claimed_at=t.at, sent_at=t.at)
    for case in cases.values():
        if case.merged_into_id or not case.replied_at or case.id in replied:
            continue
        key = f"{case.id}:old:replied"
        if (case.org_id, case.user_id, key) in taken:
            continue
        taken.add((case.org_id, case.user_id, key))
        MailOutbox.objects.create(
            user_id=case.user_id, org_id=case.org_id, case_id=case.id, key=key,
            attempt=case.attempt_no or 1, kind="reply",
            channel="telegram" if str(case.message_id or "").startswith(TELEGRAM) else "email",
            to=case.sender or "", text=case.approved_reply or "", files=[], ledger=[],
            state="sent", message_id="", error="", thread_before=[],
            claimed_at=case.replied_at, sent_at=case.replied_at)


def backwards(apps, schema_editor):
    MailOutbox = apps.get_model("rouh", "MailOutbox")
    MailOutbox.objects.filter(key__contains=":old:").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0122_old_case_routing_gone"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
