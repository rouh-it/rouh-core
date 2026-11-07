"""A turn Rouh's own software wrote is marked as such, and never drawn as the person's.

Everything Rouh is told to say unprompted - a job's report, a run waiting for
an answer, a conflict to decide, a press on a card - is handed to the model as
a `user` message, because that is the only way to hand it anything. It was
stored exactly like the person's own words, so reading a chat back drew it
under their name. Petar, 24 September 2026 (feedback fr_2f27e92125ba): "There
is a message under my name that I never wrote - instructions to the robot. If
a client saw my screen they would think I write like that."

From here on such a row carries `note` (`memory.Memory.add_message`), and the
page is never sent one. This marks the ones already stored, by the openings
those notes have had, every one of them a bracket around Rouh's own words and
nothing a person says. On the live database that day: 226 rows, every one of
them ending in "]". A sound the transcriber heard is left
alone - "[background noise]", "[clicking]" - because that is the person's
microphone, however little it says.

The same notes had been copied into each chat's own record of what was said
(`conversations.add_turn`), which is what search reads a chat's words from and
what names a chat. The copy of a marked row is taken out of it, matched by
chat and by its exact words, and nothing else is touched. What the model reads
is not changed at all: the rows stay, marked.

There is nothing to put back on the way down. The record's copies were copies
of rows that are still here.
"""
import json
import re

from django.db import migrations, models

#: How a note of Rouh's own began, in every shape it has had.
OPENINGS = re.compile(
    r"^\[(A job|The job|The change to your own code|A run in the one program"
    r"|the person interacted with the screen|A note from Rouh's own software)\b")


def _words(content: str) -> str | None:
    """The plain words of a stored user row, or None for a tool's answer."""
    try:
        blocks = json.loads(content)
    except (TypeError, ValueError):
        return None
    if isinstance(blocks, str):
        return blocks
    if not isinstance(blocks, list):
        return None
    if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in blocks):
        return None
    return " ".join(b.get("text") or "" for b in blocks
                    if isinstance(b, dict) and b.get("type") == "text").strip()


def is_note(content: str) -> bool:
    said = (_words(content) or "").strip()
    return bool(OPENINGS.match(said)) and said.endswith("]")


def forward(apps, schema_editor):
    TranscriptMessage = apps.get_model("rouh", "TranscriptMessage")
    ChatMessage = apps.get_model("rouh", "ChatMessage")

    marked: list[int] = []
    copies: set[tuple[str, str]] = set()
    rows = (TranscriptMessage.objects.filter(role="user", content__contains="[")
            .values_list("id", "session_id", "content"))
    for ident, chat, content in rows.iterator():
        if is_note(content):
            marked.append(ident)
            copies.add((chat, " ".join((_words(content) or "").split())))
    for at in range(0, len(marked), 500):
        TranscriptMessage.objects.filter(id__in=marked[at:at + 500]).update(note=True)

    gone: list[str] = []
    chats = sorted({chat for chat, _ in copies})
    for at in range(0, len(chats), 200):
        for ident, chat, body in (ChatMessage.objects
                                  .filter(chat_id__in=chats[at:at + 200], role="user")
                                  .values_list("id", "chat_id", "body")):
            if (chat, body) in copies:
                gone.append(ident)
    for at in range(0, len(gone), 500):
        ChatMessage.objects.filter(id__in=gone[at:at + 500]).delete()
    if marked or gone:
        print(f"software notes: {len(marked)} marked in the transcript, "
              f"{len(gone)} taken out of the chats' own records")


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0009_worker_outbox"),
    ]

    operations = [
        migrations.AddField(
            model_name="transcriptmessage",
            name="note",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="openturn",
            name="note",
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(forward, migrations.RunPython.noop),
    ]
