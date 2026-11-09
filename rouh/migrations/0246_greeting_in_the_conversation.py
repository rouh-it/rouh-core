"""Rouh's first words in General become part of the conversation the model is sent (Petar, 9 November 2026).

"the very first message that is sent doesn't get attached to the conversation. when I answered how, it said it
didn't know what I was talking about. fix." From 8 November 2026 the first run wrote its greeting into General
as a notice (`Memory.add_notice`), which the page draws as Rouh's and the model is never sent, so "how do I do
that?" right under it was answered as the start of a conversation.

The greeting is now an answer like any other: a note from Rouh's own software, which the model reads and the
page never draws, and Rouh's words as the assistant's reply to it, in the same exchange
(`rouh/web/firstrun.py`, `_greet`). A conversation the model is sent has to start with the person's side
(`memory.repair_history`), which is what the note is for.

So, once, every greeting already written as a notice is made that exchange: its row becomes the note, keeping
its id, time and place in the chat, and the greeting's words go into a new assistant row answering it. Only
rows with the greeting's own words are touched; any other notice stays the page's alone.
"""
import json

from django.db import migrations

#: Words only the first run's greeting has (`firstrun.GREETING` as it was on 8 November 2026).
GREETING_WORDS = "I will be your Rouh, we will continuously co-evolve"
#: `turnmarks.NOTE`, as it is today; a migration keeps its own copy.
NOTE = "[A note from Rouh's own software, not the person:"
GREETED = ("{note} the person has just finished setting up this Rouh and opened General for the first "
           "time. Your first message to them is the one below.]")


def _text(content: str) -> str:
    try:
        blocks = json.loads(content)
    except ValueError:
        return ""
    if isinstance(blocks, str):
        return blocks
    if isinstance(blocks, list):
        return " ".join(str(b.get("text") or "") for b in blocks if isinstance(b, dict))
    return ""


def forward(apps, schema_editor):
    Message = apps.get_model("rouh", "TranscriptMessage")
    for row in Message.objects.filter(notice=True, role="assistant", content__contains=GREETING_WORDS):
        if GREETING_WORDS not in _text(row.content):
            continue
        words = row.content
        Message.objects.filter(id=row.id).update(
            role="user", note=True, notice=False, root=row.id,
            content=json.dumps(GREETED.format(note=NOTE)))
        Message.objects.create(
            session_id=row.session_id, ts=row.ts + 0.001, role="assistant", content=words,
            spoken=False, root=row.id, version=row.version, live=row.live, follows=None,
            picked=row.picked, note=False, notice=False)


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0245_chat_model_choice"),
    ]

    operations = [
        migrations.RunPython(forward, migrations.RunPython.noop),
    ]
