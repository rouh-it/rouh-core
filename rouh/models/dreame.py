"""A Dreame robot vacuum through the Dreamehome or Xiaomi cloud: each person's own account (`rouh/dreame.py`).

Petar, 17 October 2026: "I have robot for cleaning, can we connect that too?" A robot is a Dreame
paired in the Dreamehome app.

There is no developer app to register with Dreame, so there is nothing at the organisation's
level: the Dreamehome account, its password and its tokens are the one person's who typed them,
and every row names the organisation and the person (`AGENTS.md`, "Whose data is it").
"""
from django.db import models


class DreameConnection(models.Model):
    """One person's Dreamehome account and the robot Rouh drives with it. Secrets are sealed."""

    id = models.BigAutoField(primary_key=True)
    org_id = models.TextField()
    user_id = models.TextField()
    #: Which app the robot is paired in, and so which cloud: "dreamehome", or "mi" for a Xiaomi
    #: account in Mi Home.
    account = models.TextField(blank=True, default="dreamehome")
    #: The Dreamehome account: the email it signs in with, and its password, sealed, so a sign-in
    #: that can no longer be renewed is made again without asking.
    email = models.TextField(blank=True, default="")
    password_sealed = models.TextField(blank=True, default="")
    #: The cloud the account lives in: eu, ru, us, sg, kr or cn for Dreamehome; de, us, ru, sg,
    #: in, tw or cn for Mi Home.
    region = models.TextField(blank=True, default="")
    #: The tokens, sealed, and when the access token stops working. For Mi Home the access token
    #: is Xiaomi's serviceToken and the refresh token its passToken, and the password is not kept.
    access_sealed = models.TextField(blank=True, default="")
    access_expires_at = models.FloatField(default=0)
    refresh_sealed = models.TextField(blank=True, default="")
    tenant_id = models.TextField(blank=True, default="")
    #: Mi Home only, sealed JSON: the key the calls are signed with (ssecurity), the Xiaomi user
    #: id, and the device id Rouh signs in as, kept so Xiaomi sees the same device each time.
    session_sealed = models.TextField(blank=True, default="")
    #: The robot: its id in the cloud, its model (dreame.vacuum.r2338a), the name the app gives
    #: it, the server it is bound to, and the account that owns it.
    did = models.TextField(blank=True, default="")
    model = models.TextField(blank=True, default="")
    robot_name = models.TextField(blank=True, default="")
    bind_domain = models.TextField(blank=True, default="")
    master_uid = models.TextField(blank=True, default="")
    #: The rooms read from the robot's map, as JSON [{id, name}], and when they were read.
    rooms_json = models.TextField(blank=True, default="")
    rooms_at = models.FloatField(default=0)
    connected_at = models.FloatField(default=0)
    #: When the cloud last answered a call made with this connection.
    reached_at = models.FloatField(default=0)
    #: Set when neither the refresh token nor the kept password signs in any more: when, and why
    #: in a sentence. Connecting again clears it.
    lapsed_at = models.FloatField(default=0)
    lapsed_said = models.TextField(blank=True, default="")
    made_at = models.FloatField(default=0)
    updated_at = models.FloatField(default=0)

    class Meta:
        db_table = "dreame_connections"
        constraints = [models.UniqueConstraint(fields=["org_id", "user_id"], name="dreame_connections_one")]
