"""A Rouh's birth: its own name, its keys and where it is registered (`rouh/birth.py`).

One row a birth, for the organisation the Rouh belongs to. A Rouh is born once; the row of a
birth whose identity ended (both keys lost, `state` "ended") is kept beside the new one, so
what it was is never forgotten.
"""
from django.db import models


class RouhBirth(models.Model):
    """This organisation's Rouh: its name, from its birth key, and the keys that speak for it.

    The daily key's private half is sealed (`rouh/encryption.py`) and so is in every backup of
    the database, as sealed as every other credential: restoring a backup, with the
    installation's encryption key, restores the Rouh with its identity. The recovery key's
    private half is never kept: its twelve words are sealed here only until they are shown once,
    and emptied the moment they are."""

    id = models.BigAutoField(primary_key=True)
    org_id = models.TextField()
    #: "born", or "ended" when its identity ended and a new Rouh was born in its place.
    state = models.TextField(default="born")
    name = models.TextField()
    tag = models.TextField()
    names_version = models.IntegerField(default=1)
    born_at = models.FloatField()
    #: When this Rouh's life began, for a Rouh born after it was already running (`retro`): its
    #: first chat, task or gene, so its history is its own from before its birth too.
    life_began_at = models.FloatField(null=True, blank=True)
    retro = models.BooleanField(default=False)
    #: The public key the name was worked out from, base64; never changes, whatever key follows.
    birth_key = models.TextField()
    #: The birth, as signed at the moment of it by the birth key and the recovery key.
    birth_statement = models.JSONField(default=dict, blank=True)
    daily_public = models.TextField()
    daily_private = models.TextField()
    daily_since = models.FloatField()
    recovery_public = models.TextField()
    #: The recovery words, sealed, until they are shown once; "" from then on.
    recovery_words = models.TextField(blank=True, default="")
    recovery_shown_at = models.FloatField(null=True, blank=True)
    #: The last time the person typed the words back and they were right.
    recovery_checked_at = models.FloatField(null=True, blank=True)
    #: Every key change signed by the recovery key, oldest first, so a registry that meets this
    #: Rouh later can follow its keys from its birth key to today's.
    key_changes = models.JSONField(default=list, blank=True)
    #: Where it is registered: rouh.land's birth service, its pinned key and this Rouh's id there.
    registry_url = models.TextField(blank=True, default="")
    registry_key = models.TextField(blank=True, default="")
    registry_id = models.TextField(blank=True, default="")
    connected_at = models.FloatField(null=True, blank=True)
    #: What the registry last said about this Rouh, signed (its card), and when.
    card = models.JSONField(default=dict, blank=True)
    checked_at = models.FloatField(null=True, blank=True)
    #: The moment the registry said today's key is dead (revoked there), if it did.
    key_dead_at = models.FloatField(null=True, blank=True)
    #: A new key waiting for the registry's seven days (account recovery): its public half, its
    #: private half sealed, a new recovery key's sealed words, the request's id and its day.
    pending = models.JSONField(default=dict, blank=True)
    #: What happened, newest last: [{at, what, said}].
    history = models.JSONField(default=list, blank=True)
    #: The second name, given by the Rouh itself after about a hundred days (`birth.second_name`).
    second_name = models.TextField(blank=True, default="")
    second_name_why = models.TextField(blank=True, default="")
    second_name_at = models.FloatField(null=True, blank=True)
    second_name_model = models.TextField(blank=True, default="")
    second_name_tries = models.JSONField(default=list, blank=True)
    error = models.TextField(blank=True, default="")
    updated_at = models.FloatField()

    class Meta:
        db_table = "rouh_birth"
        constraints = [models.UniqueConstraint(fields=["org_id"], condition=models.Q(state="born"),
                                               name="rouh_birth_one_alive")]


class RouhNickname(models.Model):
    """What one person calls their Rouh, its human names: shown to them only, never sent anywhere."""

    id = models.BigAutoField(primary_key=True)
    org_id = models.TextField()
    user_id = models.TextField()
    nickname = models.TextField()
    #: The human names beside it (`birth.set_human_names`), each "" when none.
    first_name = models.TextField(default="")
    last_name = models.TextField(default="")
    updated_at = models.FloatField()

    class Meta:
        db_table = "rouh_nickname"
        constraints = [models.UniqueConstraint(fields=["org_id", "user_id"], name="rouh_nickname_one")]
