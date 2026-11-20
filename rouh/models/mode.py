"""The owner's mode switch, Restricted or Unrestricted, and what was done under it
(`rouh/unrestricted.py`, Anatomy, Behaviour, Permissions).

`PermissionMode` is one row per person: the mode now and how long it lasts. No row is Restricted.
`PermissionModeFlip` is every flip, written in the same transaction as the row, never changed.
`UnrestrictedAction` is one row for each call that ran because the mode was Unrestricted - what
would otherwise have waited for a yes - with how to undo it where the service allows one: the
"What Rouh did" feed. Every row is the person's own (AGENTS.md, "Whose data is it")."""
from django.db import models


class PermissionMode(models.Model):
    pk = models.CompositePrimaryKey("org_id", "user_id")
    org_id = models.TextField()
    user_id = models.TextField()
    #: "restricted" or "unrestricted".
    mode = models.TextField(default="restricted")
    #: "hours", "until_back" (until switched back) or "permanent".
    how = models.TextField(blank=True, default="")
    #: When an Unrestricted of some hours ends; None for the other two and for Restricted.
    until = models.FloatField(null=True, blank=True)
    set_at = models.FloatField(default=0)
    #: Who pressed it, in words: "the owner on the Permissions page".
    set_by = models.TextField(blank=True, default="")
    #: The row sealed with this Rouh's own key by the press that wrote it (`run_access.seal`): an
    #: Unrestricted row whose seal does not open to itself was written some other way, and trips
    #: the tripwire back to Restricted.
    seal = models.TextField(blank=True, default="")

    class Meta:
        db_table = "permission_mode"


class PermissionModeFlip(models.Model):
    id = models.BigAutoField(primary_key=True)
    org_id = models.TextField()
    user_id = models.TextField()
    was = models.TextField()
    now = models.TextField()
    how = models.TextField(blank=True, default="")
    until = models.FloatField(null=True, blank=True)
    at = models.FloatField()
    by = models.TextField(blank=True, default="")
    #: The browser the press came from, cut short, for whoever reads the log.
    agent = models.TextField(blank=True, default="")

    class Meta:
        db_table = "permission_mode_flip"
        indexes = [models.Index(fields=["org_id", "user_id", "-at"], name="mode_flip_whose")]


class UnrestrictedAction(models.Model):
    id = models.BigAutoField(primary_key=True)
    org_id = models.TextField()
    user_id = models.TextField()
    #: "job" (a run's call through the gateway) or "chat" (a tool in the owner's own chat).
    via = models.TextField()
    #: The run's id, or the chat's.
    where = models.TextField(blank=True, default="")
    title = models.TextField(blank=True, default="")
    tool = models.TextField()
    #: The call's arguments, as JSON text, secrets masked.
    args = models.TextField(blank=True, default="")
    what = models.TextField(blank=True, default="")
    why = models.TextField(blank=True, default="")
    result = models.TextField(blank=True, default="")
    ok = models.BooleanField(default=True)
    #: How to undo it: {"kind": "cloudflare", "zone": ..., "ops": [...]} where the service
    #: allows one, else {} and `undo_said` says why not.
    undo = models.JSONField(default=dict, blank=True)
    undo_said = models.TextField(blank=True, default="")
    undone_at = models.FloatField(null=True, blank=True)
    undone_said = models.TextField(blank=True, default="")
    at = models.FloatField()

    class Meta:
        db_table = "unrestricted_action"
        indexes = [models.Index(fields=["org_id", "user_id", "-at"], name="unres_action_whose")]
