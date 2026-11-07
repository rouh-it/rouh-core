"""A trusted contact's guide, made before the owner is asked, if that one case is still waiting.

Petar, 2 October 2026: one trusted contact's case had been waiting since that
morning on an approval of a reply saying a guide PDF was attached, before any
guide existed. If that one case (found by its page's key) was still waiting
when this landed, its open approval was withdrawn - nothing was done or sent
on it - and the email was read again, so that under the new flow the PDF is
made first and shown under the reply before approval
(`mail_cases.CaseDesk._prepare`). Nothing was sent.

That case lives only in the database of the installation it was on, and was
decided long ago; anywhere else there is no such case, so this does nothing.
"""
from django.db import migrations


def reprepare(apps, schema_editor):
    """Nothing to do: the one case it was for belongs to the installation it was on."""


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0059_case_reply_files'),
    ]

    operations = [
        migrations.RunPython(reprepare, migrations.RunPython.noop),
    ]
