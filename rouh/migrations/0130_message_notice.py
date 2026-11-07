"""A message that is a notice's words, kept in the chat the notice leads to.

Petar, 12 October 2026 (fr_c8fb46a5a132): "when a run completes and the notification pops,
the is a link go to chat. And I go there but there is no message. That same content in the
notification needs to be posted in the chat for permanence." So a finished run's notice is
written into its chat as well, as one of Rouh's messages (`assistant_job.Lander._keep`). The
page draws it; the model is never sent it, because the job's words reached it already in
the note its report turn answered (`memory.Memory._window`). False on every row before.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0129_cloudflare_zones"),
    ]

    operations = [
        migrations.AddField(
            model_name="transcriptmessage",
            name="notice",
            field=models.BooleanField(default=False),
        ),
    ]
