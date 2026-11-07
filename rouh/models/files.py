"""One home for every file: the list of files, which is the only authority on where a file is.

Petar, 4 November 2026 (task "One home for every file"): a zip he attached in a chat was saved
where Rouh could read it and no job could, because in the containers the jobs run in another box
with no view of Rouh's data. So every file Rouh is handed - a chat upload, an email attachment, a
Telegram photo, a Slack file, a job's output, a Gene therapy file - has one row here, and its one
home on disk is a folder every part of Rouh sees at the same path, read and write
(`rouh/filestore.py`). Every path Rouh puts in front of a model or a job comes from this row.

`File` is the file: what it is, its fingerprint, where it is, where it came from and who may see
it. `FileOwner` is what it belongs to, a chat, a task (a step is a task too) or a project, and a
file may have several: the same bytes given twice are kept once with two owners.
`FileVersion` is each earlier state of a file a job or a person changed, kept so nothing is lost.

Every row carries `org_id` and `user_id` and is asked for with both wherever a person is asking
(AGENTS.md, "Whose data is it").
"""
from django.db import models
from django.db.models import Q

#: Where a file came from.
FILE_SOURCES = ("chat", "email", "telegram", "slack", "job", "gene_therapy", "task_page",
                "project_page", "made", "migrated")

#: Where its bytes are kept: on this machine's disk only, committed to the workspace's git, or on
#: disk with a copy in R2 (Cloudflare's object store), which is the backup and shared copy.
FILE_STORAGE = ("disk", "git", "disk+r2")

#: What a file can belong to. A step is a task row too.
FILE_OWNER_KINDS = ("chat", "task", "project")


class File(models.Model):
    id = models.TextField(primary_key=True)
    org_id = models.TextField(blank=True, default="")
    user_id = models.TextField(blank=True, default="")
    name = models.TextField()
    media_type = models.TextField(blank=True, default="")
    kind = models.TextField(default="file")
    size = models.BigIntegerField(default=0)
    sha256 = models.TextField(blank=True, default="")
    #: The absolute path of the file now, the same in Rouh and in every job.
    path = models.TextField()
    #: The key it was given under in the attachment store (a chat id, `task-<id>`,
    #: `project-<id>`), which the addresses the page opens it by are made of.
    session = models.TextField(blank=True, default="")
    storage = models.TextField(default="disk")
    source = models.TextField(default="chat")
    #: Which message, mail, Telegram update, Slack file or run it came from.
    source_ref = models.JSONField(default=dict, blank=True)
    #: The silos it is labelled with (`rouh/silos.py`); empty is its owner's.
    silos = models.JSONField(default=list, blank=True)
    #: Who may read or edit it, when it is not simply its owner's:
    #: {"read": [...], "edit": [...]}. Empty means inherited from what it belongs to.
    permissions = models.JSONField(default=dict, blank=True)
    #: The rest of what the attachment store says about it (converted_from, unseen, made).
    meta = models.JSONField(default=dict, blank=True)
    #: Its key in R2 once a copy is there.
    r2_key = models.TextField(blank=True, default="")
    created_at = models.FloatField()
    updated_at = models.FloatField()
    #: Put in the bin, and where it is kept there until the bin is emptied.
    deleted_at = models.FloatField(null=True, blank=True)
    deleted_by = models.TextField(blank=True, default="")

    class Meta:
        db_table = "file"
        indexes = [
            models.Index(fields=["sha256"], name="file_sha256"),
            models.Index(fields=["session"], name="file_session"),
            models.Index(fields=["deleted_at"], name="file_deleted"),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(storage__in=FILE_STORAGE), name="file_storage_known"),
        ]


class FileOwner(models.Model):
    id = models.BigAutoField(primary_key=True)
    file = models.ForeignKey(File, on_delete=models.CASCADE, related_name="owners",
                             db_column="file_id")
    kind = models.TextField()
    owner_id = models.TextField()
    created_at = models.FloatField()

    class Meta:
        db_table = "file_owner"
        indexes = [models.Index(fields=["kind", "owner_id"], name="file_owner_of")]
        constraints = [
            models.UniqueConstraint(fields=["file", "kind", "owner_id"], name="file_owner_once"),
            models.CheckConstraint(condition=Q(kind__in=FILE_OWNER_KINDS), name="file_owner_known"),
        ]


class FileVersion(models.Model):
    """One earlier state of a file: its fingerprint, size and where that copy is kept."""

    id = models.BigAutoField(primary_key=True)
    file = models.ForeignKey(File, on_delete=models.CASCADE, related_name="versions",
                             db_column="file_id")
    number = models.IntegerField()
    sha256 = models.TextField()
    size = models.BigIntegerField(default=0)
    #: Where this version's bytes are: a path in the store's version folder, a git commit, or an
    #: R2 key.
    kept_at = models.TextField(blank=True, default="")
    r2_key = models.TextField(blank=True, default="")
    made_at = models.FloatField()
    by = models.TextField(blank=True, default="")

    class Meta:
        db_table = "file_version"
        constraints = [
            models.UniqueConstraint(fields=["file", "number"], name="file_version_once"),
        ]
