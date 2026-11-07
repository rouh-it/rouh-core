"""A case's reply can carry the files its work made, and Petar sees them before he approves.

Petar, 2 October 2026, from a trusted contact's case: the reply said a guide was
attached, the approval was asked before any guide existed, and the reply path
could attach nothing. A case keeps the files its work made for the reply
(`reply_files`), the ones that go (`approved_files`), whether its work was done
before he was asked (`prepared`), and every approval the files it was shown
with (`files`), each with its hash (`rouh/case_files.py`).
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0058_trusted_inbox_scope'),
    ]

    operations = [
        migrations.AddField(
            model_name='mailcase',
            name='reply_files',
            field=models.JSONField(default=list, db_default=[]),
        ),
        migrations.AddField(
            model_name='mailcase',
            name='approved_files',
            field=models.JSONField(default=list, db_default=[]),
        ),
        migrations.AddField(
            model_name='mailcase',
            name='prepared',
            field=models.JSONField(default=dict, db_default={}),
        ),
        migrations.AddField(
            model_name='mailapproval',
            name='files',
            field=models.JSONField(default=list, db_default=[]),
        ),
    ]
