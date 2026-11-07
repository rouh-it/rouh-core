"""Which answer each message followed, so a question answered again branches the conversation.

Petar, 4 November 2026: "I wanted a second answer by pressing the smart model. but it kept the
message below instead of forking the conversation from that point on." Until this day an exchange
answered again (retry, Smart or Cheaper, an edited question) changed that exchange alone, and
everything said after it stayed under the new answer as though it had followed it.

`follows` is, on the first row of each try of an exchange, the first row of the try of the
exchange before it that it was asked after: the conversation as a tree of tries
(`memory.Memory._relive`). Null on every row before, which reads as the conversation it always
was, one line; a chat's nulls are written in the first time one of its exchanges is answered
again (`_materialize`). `picked` is which try of an exchange the person last chose, kept apart
from `live` because a try can be chosen and still be off the screen when the branch it is on is
not the one being read. It starts as `live`.
"""
from django.db import migrations, models


def picked_is_live(apps, schema_editor):
    TranscriptMessage = apps.get_model("rouh", "TranscriptMessage")
    TranscriptMessage.objects.filter(live=False).update(picked=False)


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0230_incubator_score"),
    ]

    operations = [
        migrations.AddField(
            model_name="transcriptmessage",
            name="follows",
            field=models.BigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="transcriptmessage",
            name="picked",
            field=models.BooleanField(default=True),
        ),
        migrations.RunPython(picked_is_live, migrations.RunPython.noop),
    ]
