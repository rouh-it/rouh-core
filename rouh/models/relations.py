"""Relationships between contacts (`rouh/relationships.py`).

The person, 17 November 2026 (INC-553): "also we should build relationships types between contacts. pet of,
wife of, ex bf, brother, friends, coworkers, tennis buddies, strangers, unknown.... maybe a bunch of popular
ones and then custom ones possible too." Every row carries `user_id` and `org_id` and is always asked for
with both (`AGENTS.md`, "Whose data is it").
"""
from django.db import models


class ContactRelation(models.Model):
    """One link between two of the person's contacts, or between a contact and the person themselves.

    `a` and `b` are each a contact's id in the person's Synapse Master, or "me" for the person. `a_is` is
    what `a` is to `b` as its card says it ("Wife of"), and `b_is` what `b` is to `a` ("Husband of"): the
    same words on both sides when the link reads the same both ways ("Friend of").
    """

    id = models.BigAutoField(primary_key=True)
    user_id = models.TextField()
    org_id = models.TextField()
    a = models.TextField()
    b = models.TextField()
    a_is = models.TextField()
    b_is = models.TextField()
    #: Where it was said: "card" (pressed on a contact card) or "chat" (said to Rouh).
    by = models.TextField(blank=True, default="")
    created_at = models.FloatField(default=0)
    updated_at = models.FloatField(default=0)

    class Meta:
        db_table = "contact_relation"
        indexes = [models.Index(fields=["org_id", "user_id", "a"], name="contact_relation_a"),
                   models.Index(fields=["org_id", "user_id", "b"], name="contact_relation_b")]


class RelationType(models.Model):
    """A relationship type the person made up, kept for reuse once used, with its other side's words."""

    id = models.BigAutoField(primary_key=True)
    user_id = models.TextField()
    org_id = models.TextField()
    label = models.TextField()
    #: The words for the other side ("" when they read the same both ways).
    inverse = models.TextField(blank=True, default="")
    used_at = models.FloatField(default=0)

    class Meta:
        db_table = "contact_relation_type"
        constraints = [models.UniqueConstraint(fields=["org_id", "user_id", "label"],
                                               name="contact_relation_type_one")]
