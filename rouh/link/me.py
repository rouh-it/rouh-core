"""This Rouh, as the link sees it: its name, its relay label and address, its keys, its switches.

A Rouh takes part in Rouh Link only once it is born (`rouh/birth.py`): its name is worked out from
its birth key, and its daily key (the birth key, or a successor the recovery key signed for)
signs everything it says. The link adds one key of its own, an X25519 key other Rouhs lock
messages to; its public half is in the Rouh card, signed by the daily key, and its private half
is sealed in `link_self` like every other credential.
"""
from __future__ import annotations

import base64
import os
import time
from dataclasses import dataclass
from urllib.parse import urlsplit


class NotBorn(Exception):
    """This Rouh has no birth yet, so it has no name and no key to speak with."""


#: The owner's switches, with what they are until changed. Strangers and the open network stay
#: off until rouh.land's terms cover the relay and Rouhs talking (task 131, step 131-10).
DEFAULTS = {
    "strangers": False,
    "open_network": False,
    "findable_by_email": False,
    "most_members": 5,
    "pace": True,
    # Where an agreed meeting goes, one calendar id per side (`meeting.book_calendar`): "" is the
    # usual calendar for Work, and for Personal the one personal calendar the silo rules name, else
    # nowhere until one is chosen on Connections. Never the work calendar for a Personal meeting.
    "book_calendar_work": "",
    "book_calendar_personal": "",
}


@dataclass
class Me:
    org_id: str
    name: str
    tag: str
    label: str
    address: str
    daily_public: str
    seed: bytes
    birth_key: str
    birth_statement: dict
    key_changes: list
    registry_card: dict
    link_public: str
    link_private: bytes
    dead: bool

    @property
    def tagged(self) -> str:
        return f"{self.name} ·{self.tag}" if self.tag else self.name


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


def _now() -> float:
    return time.time()


def label_of(name: str, tag: str) -> str:
    from rouh import relay

    base = relay.label_for(name)
    return f"{base}-{tag.lower()}" if tag else base


def own_address() -> str:
    """Where other Rouhs reach this one: its relay address, else its public URL (a test world)."""
    from rouh import relay
    from rouh.config import config

    try:
        found = relay.preferred_address() or relay.address()
    except Exception:  # noqa: BLE001 - no relay state is no relay address
        found = ""
    if found:
        return found.rstrip("/")
    return (os.environ.get("ROUH_LINK_ADDRESS") or config.public_url or "").rstrip("/")


def own_label(name: str, tag: str) -> str:
    from rouh import relay

    try:
        host = relay.hostname()
    except Exception:  # noqa: BLE001
        host = ""
    if host:
        return host.split(".")[0]
    return label_of(name, tag)


def _link_key(org: str) -> tuple[str, bytes]:
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

    from rouh.encryption import box
    from rouh.models import LinkSelf

    row = LinkSelf.objects.filter(org_id=org).first()
    if row is None:
        key = X25519PrivateKey.generate()
        priv = key.private_bytes_raw()
        pub = key.public_key().public_bytes_raw()
        now = _now()
        LinkSelf.objects.get_or_create(org_id=org, defaults=dict(
            link_public=_b64(pub), link_private=box().seal(_b64(priv)), settings={},
            created_at=now, updated_at=now))
        row = LinkSelf.objects.get(org_id=org)
    return row.link_public, base64.b64decode(box().open_(row.link_private))


def me(org: str) -> Me:
    """This organisation's Rouh for the link, or NotBorn."""
    from rouh import birth

    row = birth.current(str(org))
    if row is None:
        raise NotBorn("This Rouh is not born yet, so it has no name to work with other Rouhs.")
    link_pub, link_priv = _link_key(str(org))
    card = (row.card or {}).get("payload") if isinstance(row.card, dict) else {}
    return Me(org_id=str(org), name=row.name, tag=row.tag, label=own_label(row.name, row.tag),
              address=own_address(), daily_public=row.daily_public, seed=birth._seed_of(row),
              birth_key=row.birth_key, birth_statement=row.birth_statement or {},
              key_changes=list(row.key_changes or []), registry_card=card or {},
              link_public=link_pub, link_private=link_priv, dead=bool(row.key_dead_at))


def born(org: str) -> bool:
    from rouh import birth

    return birth.current(str(org)) is not None


#: Reaching strangers and the open network are held off for every Rouh until rouh.land's terms cover
#: the relay and Rouhs talking (task 131, step 131-10; Petar's default, 17 November 2026). An
#: installation lifts the hold with ROUH_LINK_OPEN=1, and then its owner may turn them on.
HELD = ("strangers", "open_network", "findable_by_email")
HELD_WHY = ("Off for every Rouh until rouh.land's terms of use cover the relay and Rouhs talking to "
            "each other. Then you can turn each on here.")


def held() -> bool:
    return os.environ.get("ROUH_LINK_OPEN", "").strip() != "1"


def settings(org: str) -> dict:
    from rouh.models import LinkSelf

    row = LinkSelf.objects.filter(org_id=str(org)).first()
    got = dict(DEFAULTS)
    if row is not None and isinstance(row.settings, dict):
        got.update({k: v for k, v in row.settings.items() if k in DEFAULTS})
    if held():
        for k in HELD:
            got[k] = False
    got["held"] = held()
    got["held_why"] = HELD_WHY if held() else ""
    return got


def set_settings(org: str, **changes) -> dict:
    from rouh.models import LinkSelf

    if born(org):
        _link_key(str(org))
    row = LinkSelf.objects.filter(org_id=str(org)).first()
    if row is None:
        raise NotBorn("This Rouh is not born yet.")
    kept = dict(row.settings or {})
    for k, v in changes.items():
        if k in HELD and held() and v:
            raise ValueError(HELD_WHY)
        if k in DEFAULTS:
            kept[k] = type(DEFAULTS[k])(v)
    LinkSelf.objects.filter(org_id=str(org)).update(settings=kept, updated_at=_now())
    return settings(org)


def host_of(address: str) -> str:
    return (urlsplit(address).hostname or "").lower()


def org_for_label(label: str) -> str | None:
    """Which organisation here answers to this label (one Rouh per organisation)."""
    from rouh import birth
    from rouh.models import RouhBirth

    for row in RouhBirth.objects.filter(state="born"):
        if own_label(row.name, row.tag) == label or label_of(row.name, row.tag) == label:
            return str(row.org_id)
    del birth
    return None


def only_org() -> str | None:
    """The organisation of the one Rouh born here, for an address that names no one."""
    from rouh.models import RouhBirth

    rows = list(RouhBirth.objects.filter(state="born").values_list("org_id", flat=True)[:2])
    return str(rows[0]) if len(rows) == 1 else None
