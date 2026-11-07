"""Philips Hue: the organisation's Hue developer app, and each person's own Hue account (`rouh/hue.py`).

Petar, 16 October 2026: "can you build the cloud integration", for his home lights through the
Philips Hue cloud (the Remote Hue API) rather than the bridge on his own network.

The developer app - its client id, client secret and app id from developers.meethue.com - is the
organisation's, entered by its administrator, with the secret sealed. The Hue account it signs in
to, its tokens and the application key on that account's bridge are the one person's: every row
names the organisation, and the connection names the person too (`AGENTS.md`, "Whose data is it").
"""
from django.db import models


class HueApp(models.Model):
    """One organisation's Remote Hue API app. The secret is sealed with `encryption.SecretBox`."""

    id = models.BigAutoField(primary_key=True)
    org_id = models.TextField()
    client_id = models.TextField(blank=True, default="")
    secret_sealed = models.TextField(blank=True, default="")
    secret_last4 = models.TextField(blank=True, default="")
    app_id = models.TextField(blank=True, default="")
    saved_by = models.TextField(blank=True, default="")
    saved_at = models.FloatField(default=0)

    class Meta:
        db_table = "hue_apps"
        constraints = [models.UniqueConstraint(fields=["org_id"], name="hue_apps_one")]


class HueConnection(models.Model):
    """One person's Hue account, signed in through the cloud, and the bridge Rouh is linked to."""

    id = models.BigAutoField(primary_key=True)
    org_id = models.TextField()
    user_id = models.TextField()
    #: The OAuth tokens, sealed, and when each stops working (0 when Hue did not say).
    access_sealed = models.TextField(blank=True, default="")
    access_expires_at = models.FloatField(default=0)
    refresh_sealed = models.TextField(blank=True, default="")
    refresh_expires_at = models.FloatField(default=0)
    #: The application key ("username") the bridge gave Rouh once its link button was pressed
    #: through the cloud, sealed: the `hue-application-key` header of every CLIP v2 call.
    key_sealed = models.TextField(blank=True, default="")
    bridge_id = models.TextField(blank=True, default="")
    bridge_name = models.TextField(blank=True, default="")
    connected_at = models.FloatField(default=0)
    refreshed_at = models.FloatField(default=0)
    #: When Hue last answered a call made with this connection.
    reached_at = models.FloatField(default=0)
    #: Set when the sign-in can no longer be renewed, or the bridge no longer takes Rouh's key:
    #: when, and why in a sentence. Connecting again clears it.
    lapsed_at = models.FloatField(default=0)
    lapsed_said = models.TextField(blank=True, default="")
    made_at = models.FloatField(default=0)
    updated_at = models.FloatField(default=0)

    class Meta:
        db_table = "hue_connections"
        constraints = [models.UniqueConstraint(fields=["org_id", "user_id"], name="hue_connections_one")]
