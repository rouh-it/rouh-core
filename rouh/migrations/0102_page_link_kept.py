"""A page's link is kept when the page stops being public (`rouh/sharing.py`).

Petar, 7 October 2026 (fr_d687af2e4fd1): "in google drive I think the public link
stays the same, here also we should keep the public link stable and just manage
permissions." Until now taking a page down deleted its row, so making it public
again minted a new token and every link already sent stopped working for good.
The row stays now, with `public` saying whether a stranger may read it. Every
row there is today is a public page, so they all start true.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0101_signup_grants'),
    ]

    operations = [
        migrations.AddField(
            model_name='publicpage',
            name='public',
            field=models.BooleanField(default=True, db_default=True),
        ),
    ]
