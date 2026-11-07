"""The rules a new password is held to, said on the form that asks for one.

Petar, 24 September 2026 (fr_a5aa0123f5d1):

    "Make the requirements for the password to be 10 symbols, not 12, as a
    minimum. List the requirements for the password, whatever they are. I
    don't know what they are. As the person types, change the color of the
    requirements that are satisfied so the person knows the password would be
    good."

The rules are Django's validators, as `AUTH_PASSWORD_VALIDATORS` in
`rouh/project/settings.py` sets them, and the server checks a password with
them and with nothing else (`validate_password`). This module turns that same
list into the lines under the password box, with what the page needs to tick
each one off as the person types (`rouh/static/password-rules.js`), so the page
can never promise a rule the server does not hold, or leave out one it does.

One line is the form's rather than Django's: the same password typed in both
boxes. Without it every line could be green and the form still say no.

The one rule a page cannot work out alone is "not a commonly used password",
because that is Django's list of twenty thousand. The page fetches the list
itself, once (`common_passwords`), rather than sending what the person is
typing anywhere as they type it.
"""
from __future__ import annotations

import functools
import gzip

from django.contrib.auth.password_validation import (CommonPasswordValidator,
                                                     MinimumLengthValidator,
                                                     UserAttributeSimilarityValidator,
                                                     get_default_password_validators)

#: The form's own line, after the validators' (`password-rules.js` knows it).
SAME = {"kind": "same", "text": "The same in both boxes"}

#: Where the page fetches the common-password list (`rouh/web/reset.py`).
COMMON_ROUTE = "/login/common-passwords"


def min_length() -> int:
    """The shortest password the validators allow, for the box's minlength."""
    return max([one.min_length for one in get_default_password_validators()
                if isinstance(one, MinimumLengthValidator)] or [1])


def rules(*, username_is_email: bool) -> list[dict]:
    """One line per validator the server checks, in the order it checks them,
    each with what the page needs to judge it; then the form's own.

    ``username_is_email`` is true for a guest, whose username is their address,
    so the similarity line need not name both.
    """
    out: list[dict] = []
    for one in get_default_password_validators():
        if isinstance(one, MinimumLengthValidator):
            out.append({"kind": "length", "min": one.min_length,
                        "text": f"At least {one.min_length} characters"})
        elif isinstance(one, UserAttributeSimilarityValidator):
            named = ("your name or email address" if username_is_email
                     else "your name, username or email address")
            out.append({"kind": "similar", "attributes": list(one.user_attributes),
                        "max": one.max_similarity, "text": f"Not too like {named}"})
        elif isinstance(one, CommonPasswordValidator):
            out.append({"kind": "common", "text": "Not a commonly used password"})
        else:
            # A rule this page cannot judge as it is typed is still listed, in
            # Django's own words, and left to the server.
            out.append({"kind": "other", "text": str(one.get_help_text()).rstrip(".")})
    return out + [SAME]


def for_page(person: dict, *, username_is_email: bool) -> dict:
    """What `password_rules.html` and its script are handed.

    ``person`` is what the similarity rule compares with: the account's
    username, email and names, as far as they are known. A name typed on the
    same form is read off the form as it is typed.
    """
    return {"rules": rules(username_is_email=username_is_email), "common": COMMON_ROUTE,
            "person": {k: str(v or "") for k, v in person.items()}}


@functools.cache
def common_passwords() -> bytes:
    """The common-password list the server refuses, one to a line, gzipped.

    Read off the validator the settings configure, so a list of our own set
    there later is the list the page gets too. Empty when none is configured.
    """
    found = next((one for one in get_default_password_validators()
                  if isinstance(one, CommonPasswordValidator)), None)
    words = sorted(found.passwords) if found is not None else []
    return gzip.compress("\n".join(words).encode("utf-8"), mtime=0)
