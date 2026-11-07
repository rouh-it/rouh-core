"""What each system prompt was made of (`rouh/prompting.py`).

Every rule is a row of the person's Synapse Master (`rouh/rules.py`) since 30 October 2026; until then Rouh's
own rules were rows of `builtin_rule`, here, which migration 0221 moved into Master and dropped.
"""
from django.db import models


class PromptPart(models.Model):
    """What one part of a system prompt was made of, found by the digest of its exact text.

    A request in `llm_requests` keeps the system prompt it sent; the digest of each of its parts finds the
    row here that says which rule, at which version and why, and which live value, each stretch of it is
    (`prompting.told`). Only the description is kept here, never the words: those are the request's."""

    id = models.BigAutoField(primary_key=True)
    org_id = models.TextField()
    #: sha256 of the part's text exactly as it was sent.
    digest = models.CharField(max_length=64)
    chars = models.IntegerField(default=0)
    #: In order, each {"kind", "key", "title", "version", "why", "chars", "digest"}.
    segments = models.JSONField(default=list)
    created_at = models.FloatField()

    class Meta:
        db_table = "prompt_part"
        constraints = [models.UniqueConstraint(fields=["org_id", "digest"], name="prompt_part_org_digest")]
