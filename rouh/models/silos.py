"""Silos: the parts of a person's life everything Rouh keeps is labelled with (`rouh/silos.py`).

Petar, 12 October 2026: "Make a silo setting in settings. This will control how many silos you have
and what they are called. Maybe a person has more than two. And then everything will get labeled -
data, emails, calendars etc". Every row carries `user_id` and `org_id` and is always asked for with
both (`AGENTS.md`, "Whose data is it").
"""
from django.db import models


class Silo(models.Model):
    """One silo of one account: Work, Personal, Family, a company of its own.

    `key` is the silo's stable id, which every label and every reader set holds (a Synapse item's
    `silos`, a trusted contact's `sees`, a rule's `silo`), so renaming, recolouring and moving it
    change nothing underneath. The two every account starts with keep the keys the fixed labels had,
    `work` and `personal`; any other is `s` and eight hex digits.
    """

    id = models.BigAutoField(primary_key=True)
    user_id = models.TextField()
    org_id = models.TextField()
    key = models.TextField()
    name = models.TextField()
    #: One of the page's colours by name (`silos.COLOURS`) or "#rrggbb".
    colour = models.TextField(default="slate")
    #: Its place in the list, smallest first.
    position = models.IntegerField(default=0)
    #: Words that place a contact here by what the person said they are to them (a relationship),
    #: and that tell the X-ray what the silo covers: "colleague, client, investor".
    words = models.TextField(blank=True, default="")
    #: Unattended runs on Rouh itself may see it.
    runs = models.BooleanField(default=False)
    #: Somebody using Rouh on the person's behalf sees it until the person sets what they see:
    #: a sender who is not a trusted contact, and a trusted contact whose `sees` is not set.
    others = models.BooleanField(default=False)
    created_at = models.FloatField(default=0)
    updated_at = models.FloatField(default=0)

    class Meta:
        db_table = "silo"
        constraints = [models.UniqueConstraint(fields=["org_id", "user_id", "key"], name="silo_one_key")]


class SiloRule(models.Model):
    """Where something comes from, and the silo that decides for it (`silos.RULE_KINDS`).

    `kind` is what is matched: a workspace project (`match` its folder, everything inside it
    following), a calendar (its id), an email domain, a sender's address, an inbox (its address), a
    Drive shared drive or folder (its id), or the meetings with no calendar event (`match` "").
    """

    id = models.BigAutoField(primary_key=True)
    user_id = models.TextField()
    org_id = models.TextField()
    kind = models.TextField()
    match = models.TextField()
    #: How the page names what is matched, when the match itself is an id ("Alex's calendar").
    label = models.TextField(blank=True, default="")
    silo = models.TextField()
    created_at = models.FloatField(default=0)

    class Meta:
        db_table = "silo_rule"
        constraints = [models.UniqueConstraint(fields=["org_id", "user_id", "kind", "match"],
                                               name="silo_rule_one_match")]
