"""Signing in by email: the addresses that sign a person in, the one-time links and codes sent to
them, and the passkeys a person may add (`rouh/signin.py`, `rouh/web/auth.py`).

Petar, 4 November 2026: "Google is just a source of data. It never decides who you are", and
"other guests need email so email authentication is needed ... passkey/face/touch should be
extra, not default". So an account is reached by an email address, and these three tables are the
whole of what that needs:

- ``SignInEmail``: each address that signs one account in. One is the account's own (``primary``),
  the one Anatomy shows; any other is a former address kept only until the new one has been used
  to sign in once, so a change of address can never lock anybody out (`signin.retire_others`).
  Kept apart from the account's contact email (`User.email`), which mail and the contact card read
  for other things.
- ``SignInLink``: one letter's link and six-digit code, kept as hashes only. It works once, for
  `signin.LINK_MINUTES`, and only the newest for an address works. A row is written for an address
  with no account too, never sent, so the hourly limits count it the same and the page answers the
  same.
- ``Passkey``: a WebAuthn credential the person added in Anatomy, You, Account, after signing in.
"""
from __future__ import annotations

from django.db import models


class SignInEmail(models.Model):
    email = models.TextField(unique=True)            # always lower case
    user = models.ForeignKey("rouh.User", on_delete=models.CASCADE, related_name="sign_in_emails")
    primary = models.BooleanField(default=True)
    added_at = models.FloatField()
    #: Where the address came from: "account" (the account's own email when this table began),
    #: "rouh.land" (followed from the connected account), "setup", "invitation", "admin".
    source = models.TextField(blank=True, default="")
    last_used_at = models.FloatField(null=True, blank=True)

    class Meta:
        db_table = "sign_in_emails"


class SignInLink(models.Model):
    token_hash = models.CharField(max_length=64, unique=True)
    code_hash = models.CharField(max_length=64, blank=True, default="")
    email = models.TextField(db_index=True)
    user = models.ForeignKey("rouh.User", null=True, blank=True, on_delete=models.CASCADE,
                             related_name="sign_in_links")
    #: A hash of a token kept in the asking browser's session: a press in that browser goes straight in.
    browser = models.CharField(max_length=64, blank=True, default="")
    #: A keyed hash of where it was asked from, for the hourly limits; never the address itself.
    ip_key = models.CharField(max_length=64, db_index=True)
    #: How it went out: "rouh.land", "gmail", "mailer", "command" (the server's emergency link), or
    #: "" for a row that was never sent (no account for the address).
    route = models.TextField(blank=True, default="")
    next = models.TextField(blank=True, default="")
    made_at = models.FloatField(db_index=True)
    expires_at = models.FloatField()
    used_at = models.FloatField(null=True, blank=True)
    cancelled_at = models.FloatField(null=True, blank=True)
    code_tries = models.IntegerField(default=0)

    class Meta:
        db_table = "sign_in_links"


class Passkey(models.Model):
    user = models.ForeignKey("rouh.User", on_delete=models.CASCADE, related_name="passkeys")
    credential_id = models.BinaryField(unique=True)
    #: The credential's public key, as the COSE map the authenticator gave.
    public_key = models.BinaryField()
    sign_count = models.BigIntegerField(default=0)
    name = models.TextField(blank=True, default="")
    created_at = models.FloatField()
    last_used_at = models.FloatField(null=True, blank=True)

    class Meta:
        db_table = "passkeys"
