"""Rouh Link: Rouhs working together, live (`rouh/link/`, task 189).

Every row is one organisation's (AGENTS.md, "Whose data is it"): a Rouh's own view of the other
Rouhs it knows, the live shared spaces it holds or is in, the changes made in them, and its signed
log. Two Rouhs in the same space each keep their own copy, in their own database.
"""
from django.db import models


class LinkSelf(models.Model):
    """This Rouh's own part of the link: its link key (X25519, for locking messages to it), sealed,
    and the switches that are the owner's (strangers, the open network, being found by email)."""

    org_id = models.TextField(primary_key=True)
    link_public = models.TextField()
    #: The private half, sealed with `encryption.SecretBox`.
    link_private = models.TextField()
    settings = models.JSONField(default=dict, blank=True)
    created_at = models.FloatField(default=0)
    updated_at = models.FloatField(default=0)

    class Meta:
        db_table = "link_self"


class LinkPeer(models.Model):
    """Another Rouh this one is connected to, by its relay label, and how far it is trusted."""

    id = models.BigAutoField(primary_key=True)
    org_id = models.TextField()
    label = models.TextField()
    name = models.TextField(blank=True, default="")
    #: Where it is reached: https://<label>.rouh.page, or what its signed card says.
    address = models.TextField(blank=True, default="")
    card = models.JSONField(default=dict, blank=True)
    daily_key = models.TextField(blank=True, default="")
    link_key = models.TextField(blank=True, default="")
    #: stranger, known, colleague, family or delegate (`rouh/link/trust.py`).
    trust = models.TextField(default="known")
    #: work or personal: the side of this Rouh it belongs to (`rouh/silos.py`).
    silo = models.TextField(blank=True, default="")
    #: asked, connected, cut or blocked.
    state = models.TextField(default="connected")
    #: link, qr, contact, email, a2a: how it came.
    via = models.TextField(blank=True, default="")
    contact_id = models.TextField(blank=True, default="")
    note = models.TextField(blank=True, default="")
    created_at = models.FloatField(default=0)
    updated_at = models.FloatField(default=0)
    last_seen_at = models.FloatField(null=True, blank=True)

    class Meta:
        db_table = "link_peers"
        constraints = [models.UniqueConstraint(fields=["org_id", "label"], name="link_peers_org_label")]


class LinkInvite(models.Model):
    """A connect link or QR code this Rouh made: whoever brings its secret back may connect, once."""

    id = models.BigAutoField(primary_key=True)
    org_id = models.TextField()
    #: sha256 of the secret in the link; the secret itself is never kept.
    token_hash = models.TextField()
    trust = models.TextField(default="known")
    silo = models.TextField(blank=True, default="")
    #: The label it is meant for, when made for one Rouh (a contact's, or Maria's): only it may use it.
    for_label = models.TextField(blank=True, default="")
    note = models.TextField(blank=True, default="")
    created_at = models.FloatField(default=0)
    expires_at = models.FloatField(default=0)
    used_at = models.FloatField(null=True, blank=True)
    used_by = models.TextField(blank=True, default="")
    withdrawn_at = models.FloatField(null=True, blank=True)

    class Meta:
        db_table = "link_invites"


class LinkMessage(models.Model):
    """One message to or from another Rouh, by its id, so delivering it twice does no harm; also
    the outbox, for a message still to be delivered (straight, or by the mailbox)."""

    id = models.BigAutoField(primary_key=True)
    org_id = models.TextField()
    msg_id = models.TextField()
    peer_label = models.TextField()
    #: in or out
    direction = models.TextField()
    kind = models.TextField()
    #: The sealed envelope, for an outgoing one still to be delivered; {} once done.
    envelope = models.JSONField(default=dict, blank=True)
    #: queued, sent, mailbox, done, refused
    state = models.TextField(default="queued")
    tries = models.IntegerField(default=0)
    next_at = models.FloatField(default=0)
    said = models.TextField(blank=True, default="")
    created_at = models.FloatField(default=0)
    done_at = models.FloatField(null=True, blank=True)

    class Meta:
        db_table = "link_messages"
        constraints = [models.UniqueConstraint(fields=["org_id", "msg_id", "direction"],
                                               name="link_messages_once")]
        indexes = [models.Index(fields=["org_id", "state", "next_at"], name="link_messages_due")]


class LinkLog(models.Model):
    """The signed log: every message and change, in plain words, each entry chained to the one
    before and signed with this Rouh's daily key (`rouh/link/log.py`)."""

    id = models.BigAutoField(primary_key=True)
    org_id = models.TextField()
    seq = models.IntegerField()
    at = models.FloatField()
    peer_label = models.TextField(blank=True, default="")
    space_id = models.TextField(blank=True, default="")
    kind = models.TextField()
    plain = models.TextField()
    entry = models.JSONField(default=dict, blank=True)
    prev = models.TextField(blank=True, default="")
    hash = models.TextField()
    sig = models.TextField(blank=True, default="")

    class Meta:
        db_table = "link_log"
        constraints = [models.UniqueConstraint(fields=["org_id", "seq"], name="link_log_seq")]


class LinkSpace(models.Model):
    """A live shared space, as this Rouh keeps it: held here (its room), or a member's copy."""

    id = models.BigAutoField(primary_key=True)
    org_id = models.TextField()
    space_id = models.TextField()
    #: task, page, doc, trip, research, calendar, list (`rouh/link/kinds.py`)
    kind = models.TextField(default="task")
    title = models.TextField(blank=True, default="")
    #: The label of the Rouh that holds the room, its address and its daily key.
    holder_label = models.TextField()
    holder_address = models.TextField(blank=True, default="")
    holder_key = models.TextField(blank=True, default="")
    mine = models.BooleanField(default=False)
    silo = models.TextField(blank=True, default="")
    #: The last change applied to this copy, by the room's order.
    seq = models.IntegerField(default=0)
    #: The space as it stands, worked out from its changes (`rouh/link/doc.py`).
    doc = models.JSONField(default=dict, blank=True)
    #: Members, roles, the stand-in, the group's epoch: {"members": [...], ...}
    meta = models.JSONField(default=dict, blank=True)
    #: The task this space was made from, for one held here.
    source = models.TextField(blank=True, default="")
    #: live, left, ended
    state = models.TextField(default="live")
    created_at = models.FloatField(default=0)
    updated_at = models.FloatField(default=0)

    class Meta:
        db_table = "link_spaces"
        constraints = [models.UniqueConstraint(fields=["org_id", "space_id"], name="link_spaces_once")]


class LinkOp(models.Model):
    """One change in a live shared space, in the room's order (seq), or one of this member's own
    still on its way to the room (seq 0, pending)."""

    id = models.BigAutoField(primary_key=True)
    org_id = models.TextField()
    space_id = models.TextField()
    seq = models.IntegerField(default=0)
    op_id = models.TextField()
    #: person:<label> or rouh:<label>
    actor = models.TextField()
    kind = models.TextField()
    data = models.JSONField(default=dict, blank=True)
    at = models.FloatField(default=0)
    pending = models.BooleanField(default=False)
    undone = models.BooleanField(default=False)

    class Meta:
        db_table = "link_ops"
        constraints = [models.UniqueConstraint(fields=["org_id", "space_id", "op_id"], name="link_ops_once")]
        indexes = [models.Index(fields=["org_id", "space_id", "seq"], name="link_ops_order")]


class LinkGrant(models.Model):
    """A written delegate grant: what another Rouh may decide for this Rouh's person, with limits,
    checked in code (`rouh/link/grants.py`), shown to both people, withdrawn in one press."""

    id = models.BigAutoField(primary_key=True)
    org_id = models.TextField()
    grant_id = models.TextField()
    #: out: given by this Rouh's person to the peer; in: given to this Rouh by the peer's person.
    direction = models.TextField()
    peer_label = models.TextField()
    what = models.TextField()
    limits = models.JSONField(default=dict, blank=True)
    words = models.TextField(blank=True, default="")
    created_at = models.FloatField(default=0)
    ends_at = models.FloatField(null=True, blank=True)
    withdrawn_at = models.FloatField(null=True, blank=True)
    signature = models.TextField(blank=True, default="")

    class Meta:
        db_table = "link_grants"
        constraints = [models.UniqueConstraint(fields=["org_id", "grant_id", "direction"], name="link_grants_once")]
