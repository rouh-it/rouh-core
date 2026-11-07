"""The Incubator's tables (`rouh/incubator.py`): one list of ideas for Rouh's new genes and mutations.

Petar, 3 November 2026: "I think it needs to be a feature separately put in navigation with its own
page and database + tooling for LLM to manage." Every row carries `org_id` and `user_id`, and every
query names both.
"""
from django.db import models


class IncubatorIdea(models.Model):
    """One idea, kept with the words it was first written in, never shortened or reworded."""

    id = models.BigAutoField(primary_key=True)
    org_id = models.TextField()
    user_id = models.TextField()
    #: Its number in this person's Incubator, shown as INC-<number> (`incubator.PREFIX`).
    number = models.IntegerField()
    title = models.TextField()
    #: "gene" (a new gene), "mutation" (a change to a gene there is), or "" (not known yet).
    kind = models.TextField(blank=True, default="")
    #: For a mutation, the gene it changes, as a gene key or in words, when it is known.
    gene = models.TextField(blank=True, default="")
    #: One of `incubator.CATEGORIES`, and any further topics.
    category = models.TextField(blank=True, default="")
    tags = models.JSONField(default=list, blank=True)
    #: One of `incubator.STATUSES`.
    status = models.TextField(default="new")
    #: Where it came from first (`incubator.SOURCES`), and every source it is known from.
    source = models.TextField(default="person")
    sources = models.JSONField(default=list, blank=True)
    #: Its own name in that source: I-028 in the nightly list, N-019 in the nursery, 70-01 for a step.
    ref = models.TextField(blank=True, default="")
    #: The status word it had in its source, as written there ("looked at", "already-built").
    source_status = models.TextField(blank=True, default="")
    #: What the import keys it by, so importing again changes nothing: "ws:<object id>",
    #: "nightly:I-028", "nursery:N-019". "" for an idea added by hand or in a chat.
    source_key = models.TextField(blank=True, default="")
    #: The full original text, exactly as written.
    original = models.TextField(blank=True, default="")
    #: The same text in its parts, for reading in sections: [{"title", "path", "text"}].
    sections = models.JSONField(default=list, blank=True)
    #: Triage notes added later, by the person or Rouh; the original above is never changed.
    notes = models.TextField(blank=True, default="")
    #: Where it lives and what goes with it: [{"kind", "label", "href", "path"}], kinds task, step,
    #: chat, page, file, idea, request, gene and link.
    links = models.JSONField(default=list, blank=True)
    #: The idea this one was merged into, when it is "merged".
    merged_into = models.BigIntegerField(null=True, blank=True)
    #: The Gene therapy feedback and feature request Go made of it (`incubator.go`).
    feedback_id = models.TextField(blank=True, default="")
    request_id = models.TextField(blank=True, default="")
    #: What it became, once built: a gene key, a mutation or a feature request, in words.
    built_as = models.TextField(blank=True, default="")
    #: When the original was written, when its source says, epoch seconds.
    source_at = models.FloatField(null=True, blank=True)
    #: Its score's parts (`rouh/incubator_score.py`), never the score itself, which is worked out from them:
    #: {"impact"|"confidence"|"frequency"|"pain"|"clarity"|"risk": {"rouh", "why", "mine"?, "by"?, "at"?},
    #: "stars": {"why"}}. "rouh" is the scorer's value and "why" its one-line reason; "mine" is a value
    #: set by hand, which a re-score never touches.
    score_parts = models.JSONField(default=dict, blank=True)
    #: The stars, 1 to 3: the ones Rouh suggests, and the person's own, which win when set.
    stars_suggested = models.IntegerField(null=True, blank=True)
    stars_mine = models.IntegerField(null=True, blank=True)
    #: When Rouh last scored it, and with which model.
    scored_at = models.FloatField(null=True, blank=True)
    scored_model = models.TextField(blank=True, default="")
    created_at = models.FloatField()
    updated_at = models.FloatField()

    class Meta:
        db_table = "incubator_ideas"
        constraints = [models.UniqueConstraint(fields=["org_id", "user_id", "number"],
                                               name="incubator_number_once")]
        indexes = [models.Index(fields=["org_id", "user_id", "status"], name="incubator_whose_status"),
                   models.Index(fields=["org_id", "user_id", "source_key"], name="incubator_source_key")]


class IncubatorEvent(models.Model):
    """One change to one idea: who, when, what it was and what it is now."""

    id = models.BigAutoField(primary_key=True)
    org_id = models.TextField()
    user_id = models.TextField()
    idea_id = models.BigIntegerField()
    at = models.FloatField()
    #: Who changed it, in words: "you", "Rouh, in the Incubator's chat", "run 2e72efa9", "the import".
    by = models.TextField(blank=True, default="")
    #: added, imported, edited, status, category, merged, linked, go, request, built; and for its score
    #: scored (Rouh scored it), stars, part (a part set by hand) and proposed_again (the nightly run
    #: proposed it again, which counts as demand).
    what = models.TextField()
    before = models.JSONField(default=dict, blank=True)
    after = models.JSONField(default=dict, blank=True)
    note = models.TextField(blank=True, default="")

    class Meta:
        db_table = "incubator_events"
        indexes = [models.Index(fields=["org_id", "user_id", "idea_id", "at"], name="incubator_event_idea")]
