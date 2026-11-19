"""What went wrong with a connection, kept at the moment it went wrong (`rouh/connection_incidents.py`).

Petar, 19 November 2026: iCloud contacts were marked as needing a new password after one 401, and
nothing on the machine could say why afterwards - not the chat, not a job. So every refusal of a
connection's credentials is kept as it happened: the request, the answer's status and the headers
that say why, the first of its body, and which part of Rouh asked. Never a credential.

Every row names its person and organisation (AGENTS.md, "Whose data is it").
"""
from django.db import models


class ConnectionIncident(models.Model):
    """One refusal of a connection's credentials: the evidence, as it was at that moment.

    `connection` is the connection's key (`apple_contacts`, `google`, `hue`, `dreame`, ...).
    `headers` holds only the headers that say why (WWW-Authenticate, Retry-After, x-apple-*),
    and `path` never a query string. The last 50 of each connection are kept.
    """

    id = models.BigAutoField(primary_key=True)
    user_id = models.TextField()
    org_id = models.TextField()
    connection = models.TextField()
    at = models.FloatField()
    #: Which part of Rouh made the request: sync, save, delete, discover, photo fetch, test.
    part = models.TextField(blank=True, default="")
    method = models.TextField(blank=True, default="")
    host = models.TextField(blank=True, default="")
    path = models.TextField(blank=True, default="")
    status = models.IntegerField(default=0)
    headers = models.JSONField(default=dict, blank=True)
    body = models.TextField(blank=True, default="")
    #: What Rouh made of it: "retrying", "marked dead", "not counted" and the like.
    outcome = models.TextField(blank=True, default="")
    note = models.TextField(blank=True, default="")

    class Meta:
        db_table = "connection_incidents"
        indexes = [models.Index(fields=["user_id", "org_id", "connection", "-at"],
                                name="connection_incidents_whose")]


class ConnectionTrouble(models.Model):
    """A connection whose credentials are refused and not yet believed dead.

    One row while the refusals go on; gone at the first success. A connection is marked dead only
    once a refusal comes at least `connection_incidents.PERSIST` after the first one, which is two
    sync cycles apart.
    """

    id = models.BigAutoField(primary_key=True)
    user_id = models.TextField()
    org_id = models.TextField()
    connection = models.TextField()
    first_at = models.FloatField()
    last_at = models.FloatField()
    failures = models.IntegerField(default=1)
    #: The part of Rouh whose request was refused first, and last.
    first_part = models.TextField(blank=True, default="")
    last_part = models.TextField(blank=True, default="")

    class Meta:
        db_table = "connection_trouble"
        constraints = [models.UniqueConstraint(fields=["user_id", "org_id", "connection"],
                                               name="connection_trouble_one")]
