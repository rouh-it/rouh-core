"""Ask AI changes a page, and a page is shared with people by email.

Petar, 24 September 2026 (fr_edecde0ad6e6): "Now I want Ask AI to also be
able to edit that content... in rare cases, we would like shared and public
pages to have the ability to edit that HTML... I invite a specific person with
a specific email. If that person doesn't have an account, he receives an email
saying he needs to register."

- `public_pages.role`: what a visitor with the link may do. Every link out
  there before this could only be read, which is what the default says.
- `users.is_guest`: an account made from an invitation, which sees what was
  shared with it and nothing else (`rouh/web/gate.py`). Nobody is a guest yet.
- `page_guests`: one page shared with one address (`rouh/sharing.py`).
- `askai_edits`: every change Ask AI makes to a page, whole, so it can be put
  back (`rouh/askai.py`).

Nothing is copied or rewritten on the way up, and on the way down the two
tables and the two columns simply go.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0019_remove_runs_made_from_a_lone_stop'),
    ]

    operations = [
        migrations.AddField(
            model_name='publicpage',
            name='role',
            field=models.TextField(db_default='view', default='view'),
        ),
        migrations.AddField(
            model_name='user',
            name='is_guest',
            field=models.BooleanField(default=False, help_text='Made from an invitation to a shared page: sees what was shared with them and nothing else.'),
        ),
        migrations.CreateModel(
            name='AskEdit',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('user_id', models.TextField()),
                ('org_id', models.TextField()),
                ('doc', models.TextField()),
                ('thread_id', models.BigIntegerField(blank=True, null=True)),
                ('summary', models.TextField(blank=True, default='')),
                ('before', models.TextField()),
                ('after', models.TextField()),
                ('created_at', models.FloatField()),
                ('undone_at', models.FloatField(blank=True, null=True)),
            ],
            options={
                'db_table': 'askai_edits',
                'indexes': [models.Index(fields=['user_id', 'org_id', 'doc', '-id'], name='askai_edits_page')],
            },
        ),
        migrations.CreateModel(
            name='PageGuest',
            fields=[
                ('token', models.TextField(primary_key=True, serialize=False)),
                ('user_id', models.TextField()),
                ('org_id', models.TextField()),
                ('rel', models.TextField()),
                ('title', models.TextField(blank=True, default='')),
                ('email', models.TextField()),
                ('role', models.TextField(default='edit')),
                ('guest_id', models.TextField(blank=True, default='')),
                ('created_at', models.FloatField()),
                ('mailed_at', models.FloatField(blank=True, null=True)),
                ('mail_error', models.TextField(blank=True, default='')),
            ],
            options={
                'db_table': 'page_guests',
                'indexes': [models.Index(fields=['user_id', 'org_id', 'rel'], name='page_guests_page'), models.Index(fields=['email'], name='page_guests_email')],
                'constraints': [models.UniqueConstraint(fields=('user_id', 'rel', 'email'), name='page_guests_one')],
            },
        ),
    ]
