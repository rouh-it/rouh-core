"""The person's own words on each Clockwork row (`Reminder.asked`).

Petar, 10 October 2026: "Remove that rule. I will be asking you many times in the
future to do a chain of actions that only the last one might be sharing and it may be
the result of clockwork." Scheduled work may now share and give a trusted contact
authority, on the words of his it was made from, so every row keeps them.

Rows made before this are given what he had said in the chat each was asked for in,
up to the moment it was made: his own messages, never a tool's result, a note of
Rouh's software or the page an Ask AI question was about (`memory.his_own_words`
reads them the same way).
"""
import json

from django.db import migrations, models

NOTE = "[A note from Rouh's own software, not the person:"
ASKAI_MARK = "[Asked in Ask AI, the side of the conversation column that answers about the page on the canvas."
ASKAI_PASSAGE = "[The passage they selected on the page:"
#: The note written in place of a question the person stopped (`stopping.STOP_NOTE`).
STOPPED = "[Stopped by the person."
#: How many of his messages a row keeps (`reminders.ASKED_MOST`).
MOST = 12


def _his(content) -> str:
    try:
        blocks = json.loads(content)
    except (TypeError, ValueError):
        blocks = content
    if isinstance(blocks, str):
        text = blocks
    elif isinstance(blocks, list):
        if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in blocks):
            return ""
        texts = [str(b.get("text") or "") for b in blocks
                 if isinstance(b, dict) and b.get("type") == "text"]
        texts = [t for t in texts if not t.lstrip().startswith((NOTE, ASKAI_MARK, ASKAI_PASSAGE, STOPPED))]
        text = " ".join(t for t in texts if t)
    else:
        return ""
    text = text.strip()
    return "" if text.startswith((NOTE, STOPPED)) else text


def backfill(apps, schema_editor):
    Reminder = apps.get_model("rouh", "Reminder")
    Message = apps.get_model("rouh", "TranscriptMessage")
    for row in Reminder.objects.exclude(kind="server").exclude(chat_id=""):
        said = []
        for content in (Message.objects.filter(session_id=row.chat_id, role="user", live=True,
                                               note=False, ts__lte=row.created_at + 5)
                        .order_by("-id").values_list("content", flat=True)[:60]):
            text = _his(content)
            if text:
                said.append(text[:2000])
            if len(said) >= MOST:
                break
        if said:
            Reminder.objects.filter(id=row.id).update(asked=list(reversed(said)))


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0115_event_log"),
    ]

    operations = [
        migrations.AddField(
            model_name="reminder",
            name="asked",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
