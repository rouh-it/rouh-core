"""Organisations, and which one the signed-in person belongs to.

Rouh is becoming a service that several organisations use, so there are two
levels of ownership and everything that belongs to anybody belongs to one of
them:

- an **organisation** owns the settings its people share. The Google OAuth
  client - the client id and the encrypted client secret its administrator
  types in once - is the first of those.
- a **user** owns their own connections. Their Google account, their access
  token, their refresh token, their mail and their files are theirs and reach
  nobody else, not even another user of the same organisation.

The rule that comes out of that, and it is not negotiable anywhere in this
repository: **every row that belongs to an organisation carries `org_id`, every
row that belongs to a person carries `user_id`, and every query names the one
it is asking about.** There is no "the settings", no "the connection", no
global anything. A query that forgets is a query that hands one customer
another customer's credentials.

Where the people come from
--------------------------

The people are Django's accounts (`rouh.models.User`). This file does not
keep a second list of people beside them - that is how two lists of users end
up disagreeing. It owns the two things the account model adds for it,
`org` and `is_org_admin`, and the organisations themselves.

An account with no organisation yet is adopted into the default organisation
the first time it is seen, and the first member of an organisation is its
administrator, so the person who has been using this install is an
administrator of it on their next sign-in without anybody running anything.

Who is asking
-------------

`Tenancy.current` is the one place that answers it, and it takes what the
session already worked out: the Django user the sign-in gate found for the
cookie, which is `request.user` on a request and `scope["user"]` on the
websocket. Nothing else in this repository decides who is asking.

Inside a spoken turn there is no request to read, so the identity is carried in
a `ContextVar` that the websocket sets for the life of the connection. A tool
called from that turn reads it without anything having to be threaded through
the model loop. When neither is available - a background job, a command - and
this install has exactly one account, that one is meant; with more than one,
the answer is "I do not know whose", which is the only safe answer when the
next step would read somebody's mail.
"""
from __future__ import annotations

import contextlib
import contextvars
import time
import uuid
from dataclasses import dataclass

from .models.accounts import DEFAULT_ORG_ID, DEFAULT_ORG_NAME

__all__ = ["DEFAULT_ORG_ID", "DEFAULT_ORG_NAME", "GUEST_ORG", "Identity", "SPEAKER", "Tenancy",
           "ensure_organisation", "set_speaker", "speaker", "speaking"]


@dataclass(frozen=True)
class Identity:
    """Who is asking, and what they are allowed to see.

    `user_id` is the account's id as text. Text, because every table that keys
    a row by a person stores it as text, and one type everywhere is one fewer
    thing to get wrong in a WHERE clause.

    `is_admin` is administrator **of their own organisation**. It never means
    anything across organisations: there is no route in Rouh that reads
    another organisation's rows, for anybody.
    """

    user_id: str
    org_id: str
    is_admin: bool = False
    email: str = ""
    name: str = ""


#: The organisation a guest's own rows are kept under. Not a row of
#: `organisations`: a guest belongs to none, and this names nothing anybody
#: else's rows are under, so a query scoped to it finds only guests' own.
GUEST_ORG = "guests"


#: Who is talking, for the length of one websocket connection. Set by the
#: socket, read by the assistant's tools. A ContextVar rather than an argument
#: threaded through the model loop: every task a turn starts inherits it, and
#: nothing between the socket and the tool has to know it exists.
SPEAKER: contextvars.ContextVar[Identity | None] = contextvars.ContextVar(
    "rouh_speaker", default=None)


@contextlib.contextmanager
def speaking(who: Identity | None):
    """Say who this context belongs to."""
    token = SPEAKER.set(who)
    try:
        yield who
    finally:
        SPEAKER.reset(token)


def set_speaker(who: Identity | None) -> None:
    """Say who this context belongs to, for as long as it lasts.

    Called once per websocket connection. Each connection is its own task, so
    what is set here is that connection's alone and every task its turns start
    inherits it; nothing leaks between two tabs or two people.
    """
    SPEAKER.set(who)


def speaker() -> Identity | None:
    return SPEAKER.get()


def ensure_organisation(org_id: str, name: str = "") -> None:
    """Make the organisation if there is none by that id yet."""
    from .models import Organisation

    Organisation.objects.get_or_create(
        id=org_id or DEFAULT_ORG_ID,
        defaults={"name": name or (DEFAULT_ORG_NAME if org_id in ("", DEFAULT_ORG_ID)
                                   else "An organisation"),
                  "created_at": time.time()})


class Tenancy:
    """The organisations, and which one each account is in.

    It holds nothing: every answer is a query, so two processes, or a command
    run beside the server, can never disagree about who is in what.
    """

    def __init__(self, *_ignored) -> None:
        # It used to be handed the SQLite file. There is nothing to open now;
        # the argument is accepted so a caller written before the move still
        # works while it is changed.
        pass

    # --- reading ------------------------------------------------------------

    @staticmethod
    def _user(user_id: str):
        from .models import User

        try:
            return User.objects.filter(pk=int(str(user_id))).first()
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _identity(user) -> Identity:
        if getattr(user, "is_guest", False):
            # A guest is in no organisation and manages nothing. What they
            # own is their own questions about the pages shared with them,
            # and those are keyed by their own id under `GUEST_ORG`.
            return Identity(user_id=str(user.pk), org_id=GUEST_ORG, is_admin=False,
                            email=user.email or "", name=user.first_name or user.username or "")
        return Identity(
            user_id=str(user.pk),
            org_id=user.org_id or DEFAULT_ORG_ID,
            is_admin=bool(user.is_org_admin),
            email=user.email or "",
            name=user.username or "",
        )

    def identity_of(self, user_id: str) -> Identity | None:
        """One person, by account id, adopted into an organisation if need be.

        Never a guest: a guest belongs to no organisation, and adopting one
        into the default organisation would hand them everything in it.
        """
        user = self._user(user_id)
        if user is None or not user.is_active:
            return None
        if not user.org_id and not getattr(user, "is_guest", False):
            self.adopt(str(user.pk))
            user = self._user(user_id)
            if user is None:                      # deleted while we looked
                return None
        return self._identity(user)

    def organisation_name(self, org_id: str) -> str:
        from .models import Organisation

        row = Organisation.objects.filter(id=org_id).values_list("name", flat=True).first()
        return row or ""

    def members(self, org_id: str) -> list[Identity]:
        """Everyone in **one** organisation. The argument is not optional."""
        from .models import User

        if not org_id:
            return []
        return [self._identity(u)
                for u in User.objects.filter(org_id=org_id, is_active=True,
                                             is_guest=False).order_by("id")]

    def only_person(self) -> Identity | None:
        """The one account, when there is exactly one. Otherwise None.

        For the places with no session to read: a background job, a command, a
        turn that began somewhere other than a browser. On an install with one
        account, this is the person; as soon as there are two, "I do not know
        whose" is the only safe answer, because the next step reads somebody's
        mail.
        """
        from .models import User

        # Not a guest: somebody a page was shared with is not the person
        # this install belongs to, and an install with one person and a guest
        # is still one person's.
        users = list(User.objects.filter(is_active=True, is_guest=False).order_by("id")[:2])
        if len(users) != 1:
            return None
        return self.identity_of(str(users[0].pk))

    # --- writing ------------------------------------------------------------

    def adopt(self, user_id: str, org_id: str = DEFAULT_ORG_ID) -> Identity | None:
        """Put an account in an organisation, and make the first one its admin.

        An organisation with nobody to manage its Google app cannot be set up
        at all, so its first member manages it.
        """
        from django.db import transaction

        from .models import User

        ensure_organisation(org_id)
        with transaction.atomic():
            user = self._user(user_id)
            if user is None:
                return None
            if getattr(user, "is_guest", False):
                return self._identity(user)
            if not user.org_id:
                User.objects.filter(pk=user.pk).update(org_id=org_id)
            org = user.org_id or org_id
            if not User.objects.filter(org_id=org, is_org_admin=True).exists():
                first = User.objects.filter(org_id=org).order_by("id").first()
                if first is not None:
                    User.objects.filter(pk=first.pk).update(is_org_admin=True)
        user = self._user(user_id)
        return self._identity(user) if user is not None else None

    def add_organisation(self, name: str, org_id: str = "", *, sso_domain: str = "") -> str:
        from .models import Organisation

        org_id = org_id or "org-" + uuid.uuid4().hex[:12]
        Organisation.objects.create(id=org_id, name=name or "An organisation",
                                    created_at=time.time(),
                                    sso_domain=(sso_domain or "").strip().lower())
        return org_id

    def put_in(self, user_id: str, org_id: str, *, is_admin: bool | None = None) -> None:
        """Move an account to an organisation, and say whether it manages it."""
        from .models import User

        if not org_id:
            raise ValueError("a user belongs to an organisation; org_id is required")
        ensure_organisation(org_id)
        fields = {"org_id": org_id}
        if is_admin is not None:
            fields["is_org_admin"] = bool(is_admin)
        User.objects.filter(pk=int(user_id)).update(**fields)

    def set_admin(self, user_id: str, is_admin: bool) -> None:
        from .models import User

        User.objects.filter(pk=int(user_id)).update(is_org_admin=bool(is_admin))

    # --- who is asking ------------------------------------------------------

    def current(self, signed_in) -> Identity | None:
        """The one helper every route goes through.

        `signed_in` is what the sign-in gate found: the Django user, or an
        anonymous one, or None. A dict with an ``id`` or a bare id are taken
        too, for the callers that only ever had the id. Returns None when
        nobody is signed in, and a route that gets None answers 401. It never
        falls back to an identity for an unsigned request: "no session" and
        "somebody" are different answers and only one of them may reach a
        credential.
        """
        if not signed_in:
            return None
        if getattr(signed_in, "is_authenticated", None) is False:
            return None
        if isinstance(signed_in, dict):
            user_id = signed_in.get("id")
        else:
            user_id = getattr(signed_in, "pk", signed_in)
        if user_id in (None, ""):
            return None
        return self.identity_of(str(user_id))

    def close(self) -> None:
        pass
