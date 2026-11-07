"""Demo mode: one switch that blurs the person's content everywhere (`rouh/demo.py`).

Petar, 28 October 2026 (task 155): "with one toggle we can safely blur everything - no risk.
Then we manually go through tasks and settings and designate what can be unblurred." The
switch is the account's, so every device and every tab follows it; every change of it is
written down with when and from where; and what he lets the audience see is kept as an
approval of the thing as it was at that moment. Every row carries `org_id` and `user_id` and
is always asked for with both (`AGENTS.md`, "Whose data is it").
"""
from django.db import models


class DemoState(models.Model):
    """Whether one account is in demo mode now, and since when."""

    id = models.BigAutoField(primary_key=True)
    org_id = models.TextField()
    user_id = models.TextField()
    on = models.BooleanField(default=False)
    #: When it was last turned on (unix seconds); what was made after it was made on stage.
    since = models.FloatField(default=0)
    #: The device that last turned it on or off, in words ("iPhone, Safari").
    device = models.TextField(blank=True, default="")
    #: Whether the purple dots are drawn while it is on.
    dots = models.BooleanField(default=True)
    updated_at = models.FloatField(default=0)

    class Meta:
        db_table = "demo_state"
        constraints = [models.UniqueConstraint(fields=["org_id", "user_id"], name="demo_state_one")]


class DemoEvent(models.Model):
    """Every time demo mode was turned on or off, and from where. Never changed, never deleted."""

    id = models.BigAutoField(primary_key=True)
    org_id = models.TextField()
    user_id = models.TextField()
    on = models.BooleanField()
    at = models.FloatField()
    device = models.TextField(blank=True, default="")
    #: The browser's own words for itself, cut short.
    agent = models.TextField(blank=True, default="")
    address = models.TextField(blank=True, default="")

    class Meta:
        db_table = "demo_event"
        indexes = [models.Index(fields=["org_id", "user_id", "at"], name="demo_event_whose")]


class DemoApproval(models.Model):
    """One thing the person let the audience see, as it was when they did.

    `kind` is task (with all its steps), step, chat, card or setting; `ref` is the task's or
    step's folder, the chat's id, the card's id or the settings section's name. A demo
    copy is a task too (`kind` copy, `ref` the copy's folder, `source` its original's).
    `fingerprint` is what the thing was when approved: anything changed since is blurred again
    until it is approved again (`demo.fingerprint`).
    """

    id = models.BigAutoField(primary_key=True)
    org_id = models.TextField()
    user_id = models.TextField()
    kind = models.TextField()
    ref = models.TextField()
    fingerprint = models.TextField(blank=True, default="")
    source = models.TextField(blank=True, default="")
    approved_at = models.FloatField(default=0)

    class Meta:
        db_table = "demo_approval"
        constraints = [models.UniqueConstraint(fields=["org_id", "user_id", "kind", "ref"],
                                               name="demo_approval_one")]
