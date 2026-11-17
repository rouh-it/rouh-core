"""The Rouh card: an A2A agent card at ``/.well-known/agent-card.json``, signed by the Rouh.

A2A (the open Agent2Agent standard, a2a-protocol.org) says how an agent tells others what it is and
how to reach it: a JSON agent card at a well-known address. A Rouh's card is one, with Rouh's own
part in an extension (``capabilities.extensions``, uri ``EXTENSION``):

- its name and tag, its relay label, and how to reach it (``url``, the A2A endpoint, and the link's
  own inbox and room);
- its birth key, the birth as signed then, every key change since, and today's daily key, so any
  Rouh can follow the keys from the name's own key to the one that signs today;
- its link key (X25519), which messages to it are locked to;
- its job genes, as A2A skills ("Book a meeting", "A live shared space", ...).

It never names the owner. It is signed as A2A signs a card (a JWS with a detached payload, EdDSA)
by the daily key; `check` holds a card to all of it.
"""
from __future__ import annotations

import base64
import json

from . import seal

EXTENSION = "https://rouh.land/link/v1"
PROTOCOL_VERSION = "0.3.0"
WELL_KNOWN = "/.well-known/agent-card.json"
#: The older name of the same address (A2A before 0.3), answered too.
WELL_KNOWN_OLD = "/.well-known/agent.json"


def _b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64u(text: str) -> bytes:
    text = str(text)
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _key_id(pub_b64: str) -> str:
    import hashlib

    try:
        return hashlib.sha256(base64.b64decode(pub_b64)).hexdigest()[:16]
    except ValueError:
        return ""


def skills(org: str) -> list[dict]:
    from . import jobs

    return [{"id": j.id, "name": j.name, "description": j.description, "tags": list(j.tags),
             "inputModes": ["application/json"], "outputModes": ["application/json"]}
            for j in jobs.on_for(org)]


def unsigned(me) -> dict:
    from rouh import version as _version

    try:
        ver = _version.git_revision()[:12]
    except Exception:  # noqa: BLE001
        ver = ""
    base = me.address
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "name": me.tagged,
        "description": ("A Rouh: a personal AI assistant that acts for its person. It works with other "
                        "Rouhs in live shared spaces; anything that binds its person is theirs to agree."),
        "url": f"{base}/link/a2a",
        "preferredTransport": "JSONRPC",
        "version": ver or "1",
        "capabilities": {
            "streaming": False,
            "pushNotifications": False,
            "extensions": [{
                "uri": EXTENSION,
                "description": "Rouh Link: keys, locked messages, live shared spaces.",
                "required": False,
                "params": {
                    "v": 1,
                    "name": me.name,
                    "tag": me.tag,
                    "label": me.label,
                    "address": base,
                    "inbox": f"{base}/link/in",
                    "birth_key": me.birth_key,
                    "birth": me.birth_statement,
                    "key_changes": me.key_changes,
                    "daily_key": me.daily_public,
                    "link_key": me.link_public,
                },
            }],
        },
        "defaultInputModes": ["application/json", "text/plain"],
        "defaultOutputModes": ["application/json", "text/plain"],
        "skills": skills(me.org_id),
    }


def build(org: str) -> dict:
    """This Rouh's card, signed now."""
    from . import me as _me

    who = _me.me(org)
    card = unsigned(who)
    protected = _b64u(json.dumps({"alg": "EdDSA", "typ": "JOSE", "kid": _key_id(who.daily_public)},
                                 separators=(",", ":")).encode())
    payload = _b64u(seal.canonical(card))
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    sig = Ed25519PrivateKey.from_private_bytes(who.seed).sign(f"{protected}.{payload}".encode())
    card["signatures"] = [{"protected": protected, "signature": _b64u(sig)}]
    return card


class Bad(ValueError):
    pass


def rouh_part(card: dict) -> dict:
    for ext in ((card.get("capabilities") or {}).get("extensions") or []):
        if isinstance(ext, dict) and ext.get("uri") == EXTENSION and isinstance(ext.get("params"), dict):
            return ext["params"]
    raise Bad("this agent card is not a Rouh's")


def _chain_holds(part: dict) -> bool:
    """Today's daily key is the birth key, or a key change the recovery key signed for names it."""
    from rouh import birth

    daily, born = part.get("daily_key"), part.get("birth_key")
    stmt = part.get("birth") or {}
    body = stmt.get("statement") if isinstance(stmt, dict) else None
    sigs = stmt.get("signatures") if isinstance(stmt, dict) else None
    if not isinstance(body, dict) or not isinstance(sigs, dict) or body.get("birth_key") != born:
        return False
    if not birth.holds(born, body, str(sigs.get("birth") or "")):
        return False
    recovery = body.get("recovery_key")
    if recovery and not birth.holds(recovery, body, str(sigs.get("recovery") or "")):
        return False
    if daily == born:
        return True
    key = born
    for change in part.get("key_changes") or []:
        cb = (change or {}).get("statement") or {}
        cs = (change or {}).get("signatures") or {}
        if cb.get("birth_key") != born or cb.get("old_key") != key:
            return False
        if not recovery or not birth.holds(recovery, cb, str(cs.get("recovery") or "")):
            return False
        key = cb.get("new_key")
    return key == daily


def check(card: dict, *, label: str = "") -> dict:
    """The Rouh part of a card that holds: signed by its daily key, its name the one its birth key
    gives, its keys chained from birth. Bad otherwise."""
    from rouh import names

    if not isinstance(card, dict):
        raise Bad("no card")
    part = rouh_part(card)
    for k in ("name", "tag", "label", "address", "birth_key", "daily_key", "link_key"):
        if not isinstance(part.get(k), str) or not part.get(k):
            raise Bad(f"the card has no {k}")
    if label and part["label"] != label:
        raise Bad("the card is another Rouh's")
    try:
        if names.tag_of(part["birth_key"]) != part["tag"]:
            raise Bad("the card's name is not the one its birth key gives")
    except names.NameProblem:
        raise Bad("the card's birth key is not a key") from None
    if not _chain_holds(part):
        raise Bad("the card's keys do not follow from its birth")
    sigs = card.get("signatures") or []
    rest = {k: v for k, v in card.items() if k != "signatures"}
    payload = _b64u(seal.canonical(rest))
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    for s in sigs:
        try:
            Ed25519PublicKey.from_public_bytes(base64.b64decode(part["daily_key"])).verify(
                _unb64u(s.get("signature", "")), f"{s.get('protected', '')}.{payload}".encode())
            return part
        except (InvalidSignature, ValueError, TypeError, AttributeError):
            continue
    raise Bad("the card's signature does not hold")


async def fetch(address: str, *, label: str = "") -> tuple[dict, dict]:
    """(card, its Rouh part) from an address, checked."""
    from . import peers, wire

    address = peers.dialable(address)
    if not address:
        raise wire.Unreachable("not a Rouh's public address")
    card = await wire.get_json(address.rstrip("/") + WELL_KNOWN)
    return card, check(card, label=label)
