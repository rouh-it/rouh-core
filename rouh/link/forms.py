"""The keyless reader: what another Rouh sends, turned into a fixed form by code, or refused.

Safety rule 2 of the concept (task 164's split of reader and doer): whatever another Rouh writes is
data, never an order. So nothing it sends is read by a model that holds a tool or a key. This
module reads every message body against the one form its kind allows: known fields only, each of
its type and length, enums from their lists, nothing else carried along. What comes out is a plain
dict the code acts on by its fields; the free text in it (a comment, a line of a shared page, a
brief) is kept as `Outside`, words to show a person and never words to obey.

A field not in the form is dropped; a field of the wrong type refuses the whole message. The reader
holds no key, reads no database and calls no model: it is a function of its input.
"""
from __future__ import annotations

import re
from datetime import datetime


class Refused(ValueError):
    """A message that does not fit its form."""


class Outside(str):
    """Words another Rouh wrote: shown to people, never given to a model that can act."""

    outside = True


ID = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")
LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,78}[a-z0-9])?$")
B64 = re.compile(r"^[A-Za-z0-9+/=_-]*$")
ISO = re.compile(r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})?)?$")


def _clean_text(value: str, most: int) -> str:
    text = "".join(c for c in str(value) if c in "\n\t" or (ord(c) >= 32 and ord(c) != 127))
    return text[:most]


def read_value(value, rule, where: str):
    kind = rule[0]
    if kind == "str":
        if not isinstance(value, str) or len(value) > rule[1]:
            raise Refused(f"{where}: not a short text")
        return _clean_text(value, rule[1])
    if kind == "text":
        if not isinstance(value, str):
            raise Refused(f"{where}: not text")
        return Outside(_clean_text(value, rule[1]))
    if kind == "id":
        if not isinstance(value, str) or not ID.match(value):
            raise Refused(f"{where}: not an id")
        return value
    if kind == "label":
        if not isinstance(value, str) or not LABEL.match(value):
            raise Refused(f"{where}: not a Rouh's label")
        return value
    if kind == "actor":
        if not isinstance(value, str) or not re.match(r"^(person|rouh):[a-z0-9-]{1,80}$", value):
            raise Refused(f"{where}: not a person or a Rouh")
        return value
    if kind == "url":
        if not isinstance(value, str) or len(value) > 300 or not re.match(r"^https?://[A-Za-z0-9.:\[\]-]+(/[^\s]*)?$", value):
            raise Refused(f"{where}: not an address")
        return value
    if kind == "b64":
        if not isinstance(value, str) or len(value) > rule[1] or not B64.match(value):
            raise Refused(f"{where}: not a key")
        return value
    if kind == "int":
        if isinstance(value, bool) or not isinstance(value, int) or not (rule[1] <= value <= rule[2]):
            raise Refused(f"{where}: not a whole number in range")
        return value
    if kind == "num":
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not (rule[1] <= value <= rule[2]):
            raise Refused(f"{where}: not a number in range")
        return value
    if kind == "bool":
        if not isinstance(value, bool):
            raise Refused(f"{where}: not yes or no")
        return value
    if kind == "enum":
        if value not in rule[1]:
            raise Refused(f"{where}: not one of {', '.join(map(str, rule[1]))}")
        return value
    if kind == "iso":
        if not isinstance(value, str) or not ISO.match(value):
            raise Refused(f"{where}: not a time")
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise Refused(f"{where}: not a time") from None
        return value
    if kind == "list":
        if not isinstance(value, list) or len(value) > rule[1]:
            raise Refused(f"{where}: not a list, or too long")
        return [read_value(v, rule[2], f"{where}[{i}]") for i, v in enumerate(value)]
    if kind == "pair":
        if not isinstance(value, list) or len(value) != 2:
            raise Refused(f"{where}: not a pair")
        return [read_value(value[0], rule[1], where), read_value(value[1], rule[1], where)]
    if kind == "obj":
        return read(value, rule[1], where)
    if kind == "json":
        # A small JSON value whose meaning is checked by its own reader (the card, a doc's value).
        import json

        if len(json.dumps(value, default=str)) > rule[1]:
            raise Refused(f"{where}: too big")
        return value
    if kind == "op":
        from . import doc

        return doc.read_op(value, where)
    if kind == "maybe":
        return None if value is None else read_value(value, rule[1], where)
    raise Refused(f"{where}: unknown rule")


def read(body, spec: dict, where: str = "") -> dict:
    if not isinstance(body, dict):
        raise Refused(f"{where or 'the message'}: not an object")
    out = {}
    for key, rule in spec.items():
        name, optional = (key[:-1], True) if key.endswith("?") else (key, False)
        if name not in body or body[name] is None and optional:
            if not optional:
                raise Refused(f"{where + '.' if where else ''}{name}: missing")
            continue
        out[name] = read_value(body[name], rule, f"{where + '.' if where else ''}{name}")
    return out


# --- the forms, one per kind ----------------------------------------------------------------------

S = lambda n=80: ("str", n)  # noqa: E731
T = lambda n=400: ("text", n)  # noqa: E731

PRESENCE = ("obj", {"actor": ("actor",), "kind": ("enum", ("person", "rouh")), "name?": S(80),
                    "part?": S(120), "doing?": T(200), "follow?": S(120), "busy?": ("bool",)})
SPACE_ID = ("id",)
ROLE = ("enum", ("viewer", "commenter", "editor", "owner"))
KIND = ("enum", ("task", "page", "doc", "trip", "research", "calendar", "list"))
LOG_ENTRY = ("obj", {"seq": ("int", 0, 10**9), "at": ("num", 0, 10**11), "kind": S(40), "plain": T(600),
                     "space_id?": S(80), "hash": S(80), "prev?": S(80), "sig": S(200)})
MEMBER = ("obj", {"label": ("label",), "name?": S(120), "role": ROLE, "address?": ("url",),
                  "key?": ("b64", 64), "link_key?": ("b64", 64)})

FORMS: dict[str, dict] = {
    "hello": {"invite?": S(120), "card": ("json", 20000), "note?": T(300), "trust_offered?": S(20)},
    "ping": {},
    "card": {},
    "bye": {"why?": T(200)},
    "cut": {"why?": T(200)},
    "trust.told": {"level": ("enum", ("stranger", "known", "colleague", "family", "delegate"))},
    "log.ask": {"since?": ("int", 0, 10**9), "space_id?": SPACE_ID},
    "log.share": {"entries": ("list", 500, LOG_ENTRY), "key": ("b64", 64)},
    "meeting.ask": {"ask_id": ("id",), "space_id?": SPACE_ID, "minutes": ("int", 10, 480),
                    "from": ("iso",), "until": ("iso",)},
    "meeting.busy": {"ask_id": ("id",), "busy": ("list", 400, ("pair", ("iso",))), "trouble?": T(200)},
    "space.invite": {"space_id": SPACE_ID, "kind": KIND, "title": T(200), "role": ROLE,
                     "holder": ("label",), "address": ("url",), "holder_key": ("b64", 64),
                     "silo?": S(40), "members?": ("list", 200, MEMBER), "standin?": S(80)},
    "space.join": {"space_id": SPACE_ID},
    "space.left": {"space_id": SPACE_ID},
    "space.ended": {"space_id": SPACE_ID},
    "room.ops": {"space_id": SPACE_ID, "ops": ("list", 300, ("op",)), "via_standin?": ("bool",)},
    "room.poll": {"space_id": SPACE_ID, "since": ("int", 0, 10**9), "wait?": ("num", 0, 25),
                  "presence?": ("list", 6, PRESENCE)},
    "room.presence": {"space_id": SPACE_ID, "presence": ("list", 6, PRESENCE)},
    "group.welcome": {"space_id": SPACE_ID, "epoch": ("int", 0, 10**6), "secret": ("b64", 64),
                      "members": ("list", 200, MEMBER)},
    "standin.hold": {"space_id": SPACE_ID, "until?": ("num", 0, 10**11)},
    "standin.handback": {"space_id": SPACE_ID, "ops": ("list", 2000, ("op",))},
    "grant.shown": {"grant_id": ("id",), "what": ("enum", ("meetings",)), "limits": ("obj", {
                        "most_minutes?": ("int", 0, 480), "days?": ("list", 7, ("int", 0, 6)),
                        "from_hour?": ("int", 0, 23), "to_hour?": ("int", 1, 24),
                        "most_a_week?": ("int", 0, 50), "money?": ("int", 0, 0)}),
                    "words": T(400), "ends_at?": ("maybe", ("num", 0, 10**11)), "sig": S(200)},
    "grant.withdrawn": {"grant_id": ("id",)},
    "grant.decide": {"grant_id": ("id",), "space_id": SPACE_ID, "proposal": ("id",), "option": ("id",)},
    "handoff.brief": {"brief_id": ("id",), "need": T(1200), "by_when?": ("iso",),
                      "budget_band?": ("enum", ("none", "small", "medium", "large", "ask")),
                      "reply_way?": ("enum", ("this-link", "email-after-yes"))},
    "handoff.quote": {"brief_id": ("id",), "amount": ("num", 0, 10**9), "currency": ("enum", ("EUR", "USD", "GBP", "BGN")),
                      "valid_until?": ("iso",), "words?": T(1200)},
    "money.proposal": {"proposal_id": ("id",), "amount": ("num", 0, 10**9),
                       "currency": ("enum", ("EUR", "USD", "GBP", "BGN")), "for": T(300)},
    "a2a.note": {"text": T(2000), "from_agent?": S(200)},
}


def read_message(kind: str, body) -> dict:
    """The fixed form of a message of this kind, or Refused."""
    spec = FORMS.get(kind)
    if spec is None:
        raise Refused(f"there is no form for {kind!r}")
    return read(body if body is not None else {}, spec, kind)


def is_outside(value) -> bool:
    return isinstance(value, Outside)
