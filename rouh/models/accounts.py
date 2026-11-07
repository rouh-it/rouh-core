"""People, the organisations they belong to, and how they got in.

Until 23 September 2026 this was three hand-written SQLite tables in
`rouh/accounts.py` and one in `rouh/tenancy.py`. It is Django's own account
model now, extended by the two things Rouh needs on top of it: which
organisation a person is in, and whether they manage that organisation.

**Two kinds of administrator, and they are not the same thing.**

- ``is_org_admin`` is administrator *of their own organisation*: the person
  who may enter that organisation's Google client. It never means anything
  across organisations (`rouh/tenancy.py`).
- ``is_staff`` / ``is_superuser`` are Django's, and say who may open the
  Django admin at ``/admin/`` to manage accounts on this install.

**The rule about whose data is whose is unchanged.** Every row that belongs to
an organisation carries ``org_id``, every row that belongs to a person carries
``user_id``, and every query names the one it is asking about. The ids are
kept as text in those rows, exactly as they were, so a query written against
the old tables reads the same against these.
"""
from __future__ import annotations

from django.contrib.auth.models import AbstractUser, UserManager
from django.db import models
from django.db.models.functions import Lower

#: The organisation this install already had before there were organisations.
#: Named rather than generated so a migration onto an existing database is
#: repeatable, and so a check of your own can say which one it means.
DEFAULT_ORG_ID = "org-default"
DEFAULT_ORG_NAME = "My organisation"


class Organisation(models.Model):
    """One organisation: the level that owns what its people share.

    Its Google Cloud OAuth client is the first of those (`GoogleClient`), and
    signing in with Google is the second (`rouh/web/sso.py`):

    - ``sso_domain`` is the email domain whose people may sign in with that
      client, checked against the address Google vouches for. Blank means
      nobody signs in with Google here.
    - ``sso_auto_create`` says whether somebody from that domain who has no
      account yet is given one the first time they sign in. Off unless an
      administrator turns it on: until the conversations and the workspace are
      kept per person, a new account sees what everybody else in the
      organisation sees, and that is a decision for a person, not a default.
      With it off, an administrator makes the account (`manage.py account add
      alice --email alice@example.com`, or the Django admin) and the person
      then signs in with Google as that account.
    """

    id = models.TextField(primary_key=True)
    name = models.TextField()
    created_at = models.FloatField()
    sso_domain = models.TextField(blank=True, default="")
    sso_auto_create = models.BooleanField(default=False)

    class Meta:
        db_table = "organisations"

    def __str__(self) -> str:
        return f"{self.name} ({self.id})"


class RouhUserManager(UserManager):
    """Usernames are matched without regard to case, as they always were."""

    def get_by_natural_key(self, username):
        return self.get(username__iexact=username)


class User(AbstractUser):
    """One person who may use Rouh.

    Django's user, so the password is kept by Django's hashers (scrypt first,
    `rouh/project/settings.py`), a sign-in is a Django session, and the admin
    can manage accounts. What Rouh adds is the organisation and whether they
    manage it.

    The id is an integer, as it always was: user 1 on the old tables is user 1
    here, and every row that names a person by ``user_id = '1'`` still names
    the same person.
    """

    org = models.ForeignKey(Organisation, on_delete=models.PROTECT, null=True, blank=True,
                            db_column="org_id", related_name="members")
    is_org_admin = models.BooleanField(
        default=False,
        help_text="Manages their own organisation: may enter its Google client.")
    #: Somebody a page was shared with by email, who made this account from
    #: the invitation (`rouh/web/guests.py`). A guest belongs to no
    #: organisation and reaches the pages shared with them and nothing else:
    #: the gate turns every other address away (`rouh/web/gate.py`), and the
    #: socket the voice rides on is closed to them.
    is_guest = models.BooleanField(
        default=False,
        help_text="Made from an invitation to a shared page: sees what was shared "
                  "with them and nothing else.")

    objects = RouhUserManager()

    class Meta:
        db_table = "users"
        constraints = [
            # One account per name, whatever the case it is typed in. The old
            # table said COLLATE NOCASE; this says the same thing to PostgreSQL.
            models.UniqueConstraint(Lower("username"), name="users_username_ci"),
        ]


class SignInFailure(models.Model):
    """One refused sign-in, by address and by the name that was tried.

    They decide how long the next attempt has to wait and when an account or
    an address is shut out for a while (`rouh/accounts.py`). Nothing else is
    kept about an attempt: never the password.
    """

    ts = models.FloatField(db_index=True)
    ip = models.TextField(blank=True, default="")
    username = models.TextField(blank=True, default="")

    class Meta:
        db_table = "auth_failures"


class Handover(models.Model):
    """A password that was sent to its owner, and where it was sent.

    One row per account per handover. It is written only once the message
    has really gone (`rouh/handover.py`): a password nobody was told is a
    locked door, which is what happened the last time an account was made for
    the owner, and this row is how the cutover proves it did not happen again.
    The password itself is never kept here, only that it was delivered.
    """

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="handovers")
    sent_at = models.FloatField()
    #: Where it went, in words: "telegram", "email to alex@example.com".
    channels = models.TextField()
    reason = models.TextField(blank=True, default="")

    class Meta:
        db_table = "account_handover"
