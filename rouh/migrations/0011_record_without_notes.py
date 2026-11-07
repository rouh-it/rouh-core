"""The notes 0010 could not match, taken out of the chats' own records.

0010 took a note of Rouh's own out of a chat's record (`conversations.add_turn`)
only where the same chat's transcript held the row it was copied from, matched
by chat and by words. On the live database that left 51: copies filed under
another chat than the transcript row they came from, because the record and
the transcript have not always agreed about which chat a turn belongs to. The
record is what search reads a chat's words from and what it shows under a chat
that matched, so a job's report still turned up there as something said in the
chat (feedback fr_2f27e92125ba).

They are recognised by their words alone, as 0010 recognised the transcript's:
a `user` row that opens the way one of those notes has always opened and ends
with the bracket that closes it. On the live database that day every such row
was one of those 51, and the only other bracketed rows were sounds the
transcriber heard - "[background noise]", "[clicking]" - which stay.

Nothing is put back on the way down: every one of them was a copy of a note,
and no copy of a note belongs in a record.
"""
import re

from django.db import migrations

#: How a note of Rouh's own began, in every shape it has had (0010's list).
OPENINGS = re.compile(
    r"^\[(A job|The job|The change to your own code|A run in the one program"
    r"|the person interacted with the screen|A note from Rouh's own software)\b")


def forward(apps, schema_editor):
    ChatMessage = apps.get_model("rouh", "ChatMessage")
    gone = [ident for ident, body in (ChatMessage.objects
                                      .filter(role="user", body__startswith="[")
                                      .values_list("id", "body"))
            if OPENINGS.match(body or "") and (body or "").rstrip().endswith("]")]
    for at in range(0, len(gone), 500):
        ChatMessage.objects.filter(id__in=gone[at:at + 500]).delete()
    if gone:
        print(f"software notes: {len(gone)} more taken out of the chats' own records")


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0010_software_notes"),
    ]

    operations = [
        migrations.RunPython(forward, migrations.RunPython.noop),
    ]
