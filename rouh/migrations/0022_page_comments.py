"""Comments pinned to a shared page: threads, and the messages in them.

Petar, 24 September 2026 (fr_5879c0745f99): comments on the collaborative
page "in the style of Figma" - pinned to part of the page, threaded, with
people tagged and emailed, resolved and still reachable (`rouh/comments.py`).

Two new tables and nothing else changed, so a Rouh rolled back past this
migration loses only the comments made since.
"""
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0021_browser_logins"),
    ]

    operations = [
        migrations.CreateModel(
            name="PageComment",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("owner_id", models.TextField()),
                ("org_id", models.TextField()),
                ("rel", models.TextField()),
                ("author_id", models.TextField()),
                ("author_name", models.TextField(blank=True, default="")),
                ("author_email", models.TextField(blank=True, default="")),
                ("anchor", models.JSONField(default=dict)),
                ("snapshot", models.TextField(blank=True, default="")),
                ("created_at", models.FloatField()),
                ("resolved_at", models.FloatField(blank=True, null=True)),
                ("resolved_by", models.TextField(blank=True, default="")),
            ],
            options={
                "db_table": "page_comments",
                "indexes": [models.Index(fields=["owner_id", "org_id", "rel", "id"],
                                         name="page_comments_page")],
            },
        ),
        migrations.CreateModel(
            name="PageCommentMessage",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("thread", models.ForeignKey(db_column="thread_id",
                                             on_delete=django.db.models.deletion.CASCADE,
                                             related_name="messages",
                                             to="rouh.pagecomment")),
                ("owner_id", models.TextField()),
                ("org_id", models.TextField()),
                ("author_id", models.TextField()),
                ("author_name", models.TextField(blank=True, default="")),
                ("author_email", models.TextField(blank=True, default="")),
                ("body", models.TextField()),
                ("mentions", models.JSONField(default=list)),
                ("created_at", models.FloatField()),
                ("edited_at", models.FloatField(blank=True, null=True)),
            ],
            options={
                "db_table": "page_comment_messages",
                "indexes": [models.Index(fields=["thread", "id"],
                                         name="page_comment_msgs_thread"),
                            models.Index(fields=["author_id", "created_at"],
                                         name="page_comment_msgs_author")],
            },
        ),
    ]
