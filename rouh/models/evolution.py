"""Evolution: Parameters and Mutations (`rouh/evolution.py`, EVOLUTION.md).

Petar, 13 October 2026, task 94 step 94-08: the nightly run builds as many genes a night, of as
many of each kind, as Parameters says, and every gene it builds is kept in Mutations with
its card, every answer he gave it, the mutations he asked for, the questions he asked and how it
was used. Every row is one person's, keyed by `org_id` and `user_id`, and every query names both.
"""
from __future__ import annotations

from django.db import models


class EvolutionSetting(models.Model):
    """Parameters: how many genes a night the nightly run builds, and how many of each kind.

    The four kinds always add up to `total`; 0 pauses the building, not the run. No row is
    the proposal's defaults (`evolution.DEFAULTS`)."""

    id = models.BigAutoField(primary_key=True)
    org_id = models.TextField()
    user_id = models.TextField()
    total = models.IntegerField()
    invisible = models.IntegerField()
    shows_up = models.IntegerField()
    ask_for = models.IntegerField()
    changes_work = models.IntegerField()
    updated_at = models.FloatField()
    #: Who changed it last, in words: "the owner, in Parameters".
    by = models.TextField(blank=True, default="")
    #: Every earlier value with its time, newest last: [{"at", "by", "total", ...}].
    history = models.JSONField(default=list, blank=True)
    #: Genes on the fly (task 98, step 98-17): "asked", Rouh drafts a gene only when the person
    #: asks for one, or "offer", Rouh may offer to draft one when it sees something worth one.
    #: Still the owner's to decide, so it starts at "asked".
    propose = models.TextField(default="asked", blank=True)
    #: A new trial's settings (Petar, 18 October 2026): how many days it runs and how many uses
    #: pass it. Each trial takes a copy when it starts, which he can change on the gene; what
    #: counts is the gene's own use signals, all of them (`rouh/genes/signals.py`).
    trial_days = models.IntegerField(default=7)
    trial_needed = models.IntegerField(default=1)

    class Meta:
        db_table = "evolution_settings"
        constraints = [models.UniqueConstraint(fields=["org_id", "user_id"],
                                               name="evolution_setting_one")]


class MutationsGene(models.Model):
    """One gene the nightly run built for this person, one version of it.

    A gene brought in from a night before Mutations (`evolution.bring_in`) has `source`
    "night"; one the run registered with `nightly_gene` has "registered". A mutation of a gene
    is a new row with `parent_id` the version it came from and `version` one more."""

    id = models.BigAutoField(primary_key=True)
    org_id = models.TextField()
    user_id = models.TextField()
    #: Stable within the person: "night-10", or "n11-<slug>" for one the run registered.
    key = models.TextField()
    #: The night that built it (`NightlyFeatureNight.id`), and its number, as shown.
    night_id = models.BigIntegerField(null=True, blank=True)
    night = models.IntegerField(null=True, blank=True)
    source = models.TextField(default="registered")
    name = models.TextField()
    #: One of `evolution.KINDS`, or "" for a gene from before the kinds.
    kind = models.TextField(blank=True, default="")
    #: Who set the kind: "night" (the run that built it) or "brought in" (`bring_in`).
    kind_by = models.TextField(blank=True, default="")
    #: One sentence: what changes for him.
    sentence = models.TextField(blank=True, default="")
    #: The "when" sentence: "When I am about to call someone, I'll say catch me up".
    moment = models.TextField(blank=True, default="")
    #: The words to say, or the press, for a gene he asks for.
    words = models.TextField(blank=True, default="")
    #: Where it changes things: brief, meetings, decisions, mail, chat, pages, ...
    place = models.TextField(blank=True, default="")
    #: What it is an update of, and only what changed, for an update.
    builds_on = models.TextField(blank=True, default="")
    changed = models.TextField(blank=True, default="")
    #: It sends, pays, deletes or touches other people: never bundled, always its own card.
    sensitive = models.BooleanField(default=False)
    #: How often its moment comes: daily, weekly, monthly or seasonal (judged over that).
    rhythm = models.TextField(blank=True, default="weekly")
    switch = models.TextField(blank=True, default="")
    #: The original gene, as written: {"does", "reads": [], "changes": [], "sends": [],
    #: "jobs": [], "accounts": []}; and the mutated version for us, as it ran in its test
    #: install, the same shape with "did". Empty when nothing was observed.
    original = models.JSONField(default=dict, blank=True)
    observed = models.JSONField(default=dict, blank=True)
    #: The mutation check's result (`evolution.mutation_check`).
    checked = models.JSONField(default=dict, blank=True)
    #: See it in use: workspace paths of screenshots from its test install, and the steps.
    screenshots = models.JSONField(default=list, blank=True)
    steps = models.JSONField(default=list, blank=True)
    report = models.TextField(blank=True, default="")
    commits = models.JSONField(default=list, blank=True)
    saves = models.TextField(blank=True, default="")
    #: Lineage.
    version = models.IntegerField(default=1)
    parent_id = models.BigIntegerField(null=True, blank=True)
    mutation_id = models.BigIntegerField(null=True, blank=True)
    #: Where it stands (`evolution.STATES`), and what it stood at before Decide later or a
    #: mutation request, to go back to.
    state = models.TextField(default="candidate")
    before = models.TextField(blank=True, default="")
    #: Why it stands there, in a few words: who turned it off, how it was learned.
    verdict = models.TextField(blank=True, default="")
    #: When it left the shelf for a morning's deck; None while it is on the shelf.
    released_at = models.FloatField(null=True, blank=True)
    trial_started_at = models.FloatField(null=True, blank=True)
    #: When the trial was extended once by its own length, because its moment did not come.
    extended_at = models.FloatField(null=True, blank=True)
    #: This gene's trial (`evolution.trial_of`): {"days", "needed", "counts": [item keys]},
    #: copied from Parameters when it starts and changed on the gene; and once it has ended,
    #: {"outcome", "ended_at", "uses"}. Empty for a trial started before 18 October 2026, which
    #: runs on its rhythm's length with every use signal counting.
    trial = models.JSONField(default=dict, blank=True)
    booked_at = models.FloatField(null=True, blank=True)
    reminder_id = models.BigIntegerField(null=True, blank=True)
    #: The run taking its code out, when he asked for that.
    removal_run = models.TextField(blank=True, default="")
    made_at = models.FloatField()
    updated_at = models.FloatField()
    answered_at = models.FloatField(null=True, blank=True)
    #: When the owner last decided anything about this version, and which decision, as its event's
    #: kind (`evolution.reviewed`): until the first, a gene on trial is in New.
    reviewed_at = models.FloatField(null=True, blank=True)
    reviewed_as = models.TextField(blank=True, default="")

    class Meta:
        db_table = "mutations_genes"
        constraints = [models.UniqueConstraint(fields=["org_id", "user_id", "key", "version"],
                                               name="mutations_gene_one")]
        indexes = [models.Index(fields=["org_id", "user_id", "state"], name="mutations_gene_whose")]


class MutationsGeneEvent(models.Model):
    """Something that happened to a gene, one row each: its whole history and the evidence
    of its use. `kind` is one of `evolution.EVENTS`."""

    id = models.BigAutoField(primary_key=True)
    org_id = models.TextField()
    user_id = models.TextField()
    gene_id = models.BigIntegerField()
    kind = models.TextField()
    #: "person", "rouh", "night", "chat" or "evidence".
    by = models.TextField(blank=True, default="")
    detail = models.TextField(blank=True, default="")
    data = models.JSONField(default=dict, blank=True)
    at = models.FloatField()

    class Meta:
        db_table = "mutations_gene_events"
        indexes = [models.Index(fields=["org_id", "user_id", "gene_id", "at"],
                                name="mutations_gene_event_whose")]


class GeneMutation(models.Model):
    """A mutation the owner asked for in their own words, and what became of it.

    requested -> building (its own run started the moment he asked, or a night took it) -> built
    (the run registered the new version) -> landed (its commits are in what Rouh runs); or
    withdrawn, or failed with why."""

    id = models.BigAutoField(primary_key=True)
    org_id = models.TextField()
    user_id = models.TextField()
    gene_id = models.BigIntegerField()
    #: The version it was asked of, as it was then.
    from_version = models.IntegerField(default=1)
    words = models.TextField()
    status = models.TextField(default="requested")
    #: The gene's state before the request, given back if it is withdrawn.
    before = models.TextField(blank=True, default="")
    night = models.IntegerField(null=True, blank=True)
    #: The run started for it alone when he asked (`evolution.start_mutation`); "" when a night builds it.
    run_id = models.TextField(blank=True, default="")
    result_gene_id = models.BigIntegerField(null=True, blank=True)
    commits = models.JSONField(default=list, blank=True)
    outcome = models.TextField(blank=True, default="")
    history = models.JSONField(default=list, blank=True)
    made_at = models.FloatField()
    updated_at = models.FloatField()

    class Meta:
        db_table = "gene_mutations"
        indexes = [models.Index(fields=["org_id", "user_id", "status"], name="gene_mutation_whose")]


class GeneQuestion(models.Model):
    """A question the owner asked on a gene's card, and Rouh's answer, in a topic of follow-ups."""

    id = models.BigAutoField(primary_key=True)
    org_id = models.TextField()
    user_id = models.TextField()
    gene_id = models.BigIntegerField()
    topic = models.BigIntegerField()
    question = models.TextField()
    answer = models.TextField(blank=True, default="")
    model = models.TextField(blank=True, default="")
    at = models.FloatField()

    class Meta:
        db_table = "gene_questions"
        indexes = [models.Index(fields=["org_id", "user_id", "gene_id"], name="gene_question_whose")]
