"""The gene log, its use, its marks and evaluations, and this Rouh's place in the Gene Pool
(`rouh/genelog.py`, `rouh/geneuse.py`, `rouh/genepool.py`, GENES.md "The gene log").

Task 98, step 98-16, Petar, 13 October 2026: "Everything that remains in my Rouh needs to be
formulated as a gene in a list. There will be a log of implemented genes. This log should be
automatically populated by anything I build". A gene in the log is a node of a family tree: a
root, the sub-genes grown from it here whenever a change altered its contract, and the forks a
"make it different" install made of a gene from the Pool.

What a gene is and does is this Rouh's own, so the log is keyed by `org_id`; how much a person
uses a gene, and what they think of it, is theirs, so use, marks and evaluations carry `user_id`
too. Every query names both where both are there.
"""
from __future__ import annotations

from django.db import models


class GeneLogGene(models.Model):
    """One node of the gene log: a gene, or a sub-gene of one, or a fork from the Pool."""

    id = models.BigAutoField(primary_key=True)
    org_id = models.TextField()
    #: Stable within the organisation: a manifest's id ("decisions"), a nightly gene's key in Mutations
    #: ("night-10"), a sub-gene's "<root>.<n>", a draft's "draft-<slug>", an install's "pool-<node>".
    key = models.TextField()
    name = models.TextField()
    #: One sentence: what it does for the person.
    sentence = models.TextField(blank=True, default="")
    #: The gene contract, in GENES.md's shape: {"what", "where", "touches": {"permissions",
    #: "accounts", "tables", "jobs"}, "remove"}. Informational, never a permission.
    contract = models.JSONField(default=dict, blank=True)
    contract_sha = models.TextField(blank=True, default="")
    #: What counts as using it: {"nav", "routes", "tools", "jobs", "purposes", "places", "settings"}.
    uses = models.JSONField(default=dict, blank=True)
    #: Where it came from (`genelog.ORIGINS`) and where it stands (`genelog.STATUSES`).
    origin = models.TextField(default="request")
    status = models.TextField(default="kept")
    #: The family: its parent node and how it came off it ("sub" grown here, "fork" made different
    #: on install), and the family's root. A root's `tip_id` is the node new work lands on.
    parent_id = models.BigIntegerField(null=True, blank=True)
    root_id = models.BigIntegerField(null=True, blank=True)
    relation = models.TextField(blank=True, default="")
    tip_id = models.BigIntegerField(null=True, blank=True)
    #: What it is in Rouh: its manifest, its key in Mutations, its feature switch.
    manifest = models.TextField(blank=True, default="")
    mutations_key = models.TextField(blank=True, default="")
    switch = models.TextField(blank=True, default="")
    #: How much it was built on: revisions of this node, and the first and last commit.
    revisions = models.IntegerField(default=0)
    first_commit = models.TextField(blank=True, default="")
    last_commit = models.TextField(blank=True, default="")
    #: When it came into this Rouh, and when it last changed (the list's recency).
    made_at = models.FloatField()
    changed_at = models.FloatField()
    #: Who asked for it (a user id), and in words where it was made: "commit 1a2b3c4", "night 10".
    requested_by = models.TextField(blank=True, default="")
    made_by = models.TextField(blank=True, default="")
    #: Sharing, a family's (its root's): "" not chosen, "proposed" put on the review list by the
    #: sharing mode, waiting for a person, "selected" approved by a person and kept in sync with the
    #: Pool, "declined" a person said no (never proposed again), "stopped" taken out of the Pool again.
    share = models.TextField(blank=True, default="")
    share_by = models.TextField(blank=True, default="")
    share_at = models.FloatField(null=True, blank=True)
    #: Its node in the Pool once sent, the contract hash last sent, when, and what went wrong.
    pool_node = models.TextField(blank=True, default="")
    synced_sha = models.TextField(blank=True, default="")
    synced_at = models.FloatField(null=True, blank=True)
    sync_error = models.TextField(blank=True, default="")
    #: The review gate (task 141, step 141-09): the hash of the exact body a person approved to send
    #: for this node (`genepool.body_sha`), who approved it and when; and their edits to what is sent,
    #: {"name", "sentence", "brief"}, each in place of the log's own. A body that differs from the one
    #: approved is not sent until it is approved again.
    approved_sha = models.TextField(blank=True, default="")
    approved_by = models.TextField(blank=True, default="")
    approved_at = models.FloatField(null=True, blank=True)
    pool_edit = models.JSONField(default=dict, blank=True)
    #: For a gene installed from the Pool: {"node", "family", "donor", "how", "words", "receipt"}.
    pool_origin = models.JSONField(default=dict, blank=True)
    #: Taking it out, as its contract says: {"state", "run", "said", "at"}.
    removal = models.JSONField(default=dict, blank=True)
    #: A gene drafted on the fly: {"versions": [{"at", "contract", "said"}], "chat", "idea", "run"}.
    draft = models.JSONField(default=dict, blank=True)
    created_at = models.FloatField()
    updated_at = models.FloatField()

    class Meta:
        db_table = "gene_log"
        constraints = [models.UniqueConstraint(fields=["org_id", "key"], name="gene_log_one")]
        indexes = [models.Index(fields=["org_id", "root_id"], name="gene_log_family"),
                   models.Index(fields=["org_id", "changed_at"], name="gene_log_recent")]


class GeneLogEvent(models.Model):
    """Something that happened to a gene in the log: made, a revision, a sub-gene, kept, shared."""

    id = models.BigAutoField(primary_key=True)
    org_id = models.TextField()
    gene_id = models.BigIntegerField()
    root_id = models.BigIntegerField()
    kind = models.TextField()
    commit = models.TextField(blank=True, default="")
    #: "rouh", "person", "night", "commit", "gene writer", "pool".
    by = models.TextField(blank=True, default="")
    detail = models.TextField(blank=True, default="")
    data = models.JSONField(default=dict, blank=True)
    at = models.FloatField()

    class Meta:
        db_table = "gene_log_events"
        indexes = [models.Index(fields=["org_id", "root_id", "at"], name="gene_log_event_family")]


class GeneLogCommit(models.Model):
    """One landed change to Rouh's code, read once, and the gene it was put to."""

    id = models.BigAutoField(primary_key=True)
    org_id = models.TextField()
    sha = models.TextField()
    at = models.FloatField()
    subject = models.TextField(blank=True, default="")
    #: The node it went to, None while it waits for the gene writer or when it is no gene's.
    gene_id = models.BigIntegerField(null=True, blank=True)
    #: How: "trailer", "manifest", "night", "subject", "gene writer", "none"; "" while waiting.
    how = models.TextField(blank=True, default="")
    #: What it did to the gene: "made", "revision", "sub_gene", "" for none.
    did = models.TextField(blank=True, default="")
    said = models.TextField(blank=True, default="")
    tries = models.IntegerField(default=0)

    class Meta:
        db_table = "gene_log_commits"
        constraints = [models.UniqueConstraint(fields=["org_id", "sha"], name="gene_log_commit_one")]
        indexes = [models.Index(fields=["org_id", "how"], name="gene_log_commit_how")]


class GeneUseDaily(models.Model):
    """How many times a person used a gene on a day of theirs, and by which way."""

    id = models.BigAutoField(primary_key=True)
    org_id = models.TextField()
    user_id = models.TextField()
    #: The family's root key: a gene's use is its whole family's.
    gene_key = models.TextField()
    day = models.DateField()
    uses = models.IntegerField(default=0)
    #: {"press": n, "open": n, "tool": n, "job": n, "model": n, "own": n}
    parts = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "gene_use_daily"
        constraints = [models.UniqueConstraint(fields=["org_id", "user_id", "gene_key", "day"],
                                               name="gene_use_daily_one")]
        indexes = [models.Index(fields=["org_id", "user_id", "day"], name="gene_use_daily_when")]


class GeneMark(models.Model):
    """A person's own mark on a gene: Essential, Useful or Not for me. It wins over the model's."""

    id = models.BigAutoField(primary_key=True)
    org_id = models.TextField()
    user_id = models.TextField()
    gene_key = models.TextField()
    mark = models.TextField()
    at = models.FloatField()

    class Meta:
        db_table = "gene_marks"
        constraints = [models.UniqueConstraint(fields=["org_id", "user_id", "gene_key"],
                                               name="gene_mark_one")]


class GeneEval(models.Model):
    """The model's monthly evaluation of how useful a gene is to a person (`gene_eval`)."""

    id = models.BigAutoField(primary_key=True)
    org_id = models.TextField()
    user_id = models.TextField()
    gene_key = models.TextField()
    #: "2026-10"
    month = models.TextField()
    #: 1 to 5.
    score = models.IntegerField(null=True, blank=True)
    #: What it replaced, by hand or elsewhere, and about how many minutes a month it saves.
    replaced = models.TextField(blank=True, default="")
    minutes = models.IntegerField(null=True, blank=True)
    reason = models.TextField(blank=True, default="")
    model = models.TextField(blank=True, default="")
    at = models.FloatField()

    class Meta:
        db_table = "gene_evals"
        constraints = [models.UniqueConstraint(fields=["org_id", "user_id", "gene_key", "month"],
                                               name="gene_eval_one")]


class PoolMembership(models.Model):
    """This organisation's Rouh in the Gene Pool: where the Pool is, its pinned key, this Rouh's own
    key (the private half sealed by `rouh/encryption.py`), and what the Pool last said."""

    id = models.BigAutoField(primary_key=True)
    org_id = models.TextField()
    url = models.TextField(blank=True, default="")
    pool_key = models.TextField(blank=True, default="")
    pool_key_id = models.TextField(blank=True, default="")
    #: "" not joined, "member", "left" (by an identity that ended, or by Leave before 141-15).
    status = models.TextField(blank=True, default="")
    rouh_id = models.TextField(blank=True, default="")
    name = models.TextField(blank=True, default="")
    public_key = models.TextField(blank=True, default="")
    private_key = models.TextField(blank=True, default="")
    joined_by = models.TextField(blank=True, default="")
    joined_at = models.FloatField(null=True, blank=True)
    #: The Pool's catalogue as last fetched, and the AI's matches for each person, by user id.
    catalogue = models.JSONField(default=dict, blank=True)
    catalogue_at = models.FloatField(null=True, blank=True)
    matches = models.JSONField(default=dict, blank=True)
    #: The last month whose relative use was sent, and what went wrong last.
    usage_month = models.TextField(blank=True, default="")
    #: How genes reach the review list and the Pool (`genepool.MODES`): "manual" (the default: only
    #: what a person approves), "preselect" (Rouh proposes what passes the checks; a person still
    #: approves each), "auto" (what passes every check is approved by itself; chosen only by an
    #: administrator who confirmed it). Kept on this row before joining too.
    share_mode = models.TextField(blank=True, default="manual")
    share_mode_by = models.TextField(blank=True, default="")
    share_mode_at = models.FloatField(null=True, blank=True)
    #: How the Pool's genes come in (`genepool.INCOMING`, task 141, step 141-15): "manual" (the
    #: default: seen, and installed or updated only when a person presses it) or "off" (nothing comes
    #: in). Kept on this row before joining too.
    incoming_mode = models.TextField(blank=True, default="manual")
    incoming_mode_by = models.TextField(blank=True, default="")
    incoming_mode_at = models.FloatField(null=True, blank=True)
    error = models.TextField(blank=True, default="")
    error_at = models.FloatField(null=True, blank=True)
    updated_at = models.FloatField()

    class Meta:
        db_table = "pool_membership"
        constraints = [models.UniqueConstraint(fields=["org_id"], name="pool_membership_one")]
