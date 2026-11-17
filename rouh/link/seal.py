"""Locking a message from one Rouh to another, end to end, from their keys.

An envelope is what crosses the relay and waits in the mailbox. Outside, it says only who it is
from and to (relay labels), when, and its id; everything else is in ``box``:

    {"v": 1, "id": "<uuid>", "from": "<label>", "from_key": "<sender's daily key>",
     "to": "<label>", "to_key": "<receiver's daily key>", "at": <unix seconds>, "eph": "<X25519 public, base64>",
     "nonce": "<12 bytes, base64>", "box": "<ChaCha20-Poly1305, base64>", "sig": "<Ed25519>"}

``to_key`` is what the mailbox files it under: only the holder of that key's private half can take
it out (`rouh/link/mailbox.py`). The key is HKDF-SHA256 over X25519(eph, the receiver's link key), bound to the id and both labels,
so a box cannot be moved to another envelope; the header outside the box is its associated data.
``sig`` is the sender's daily key over everything else, so the receiver knows who spoke before it
opens anything, and a mailbox that changed a byte is caught. A fresh ephemeral key for every
message means no two boxes share a key.
"""
from __future__ import annotations

import base64
import json
import os
import time
import uuid

#: An envelope older than this, or this far in the future, is refused (a mailbox holds 30 days).
MAX_AGE = 31 * 86400
SKEW = 600
#: The most a box may hold.
MAX_BYTES = 2_000_000


class Refused(ValueError):
    """An envelope that does not hold: wrong form, wrong key, changed, or not for us."""


def b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


def unb64(text: str) -> bytes:
    try:
        return base64.b64decode(str(text), validate=True)
    except (ValueError, TypeError):
        raise Refused("not base64") from None


def canonical(payload) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _key(shared: bytes, mid: str, sender: str, to: str) -> bytes:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None,
                info=f"rouh-link v1|{mid}|{sender}|{to}".encode()).derive(shared)


def sign(seed: bytes, payload) -> str:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    return b64(Ed25519PrivateKey.from_private_bytes(seed).sign(canonical(payload)))


def holds(pub_b64: str, payload, signature: str) -> bool:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    try:
        Ed25519PublicKey.from_public_bytes(unb64(pub_b64)).verify(unb64(signature), canonical(payload))
        return True
    except (InvalidSignature, Refused, ValueError, TypeError):
        return False


def lock(*, sender: str, sender_seed: bytes, sender_key: str, to: str, to_link_key: str, inner: dict,
         to_key: str = "", mid: str = "", at: float | None = None) -> dict:
    """The envelope for ``inner``, locked to ``to_link_key`` and signed by the sender."""
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
    from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

    mid = mid or str(uuid.uuid4())
    eph = X25519PrivateKey.generate()
    shared = eph.exchange(X25519PublicKey.from_public_bytes(unb64(to_link_key)))
    nonce = os.urandom(12)
    head = {"v": 1, "id": mid, "from": sender, "from_key": sender_key, "to": to, "to_key": to_key,
            "at": round(at if at is not None else time.time(), 3),
            "eph": b64(eph.public_key().public_bytes_raw()), "nonce": b64(nonce)}
    raw = canonical(inner)
    if len(raw) > MAX_BYTES:
        raise Refused("too big to send")
    box = ChaCha20Poly1305(_key(shared, mid, sender, to)).encrypt(nonce, raw, canonical(head))
    env = {**head, "box": b64(box)}
    env["sig"] = sign(sender_seed, env)
    return env


def outside(env) -> dict:
    """What anyone may read of an envelope: checked for its form only."""
    if not isinstance(env, dict) or env.get("v") != 1:
        raise Refused("not a Rouh Link envelope")
    for k in ("id", "from", "from_key", "to", "eph", "nonce", "box", "sig"):
        if not isinstance(env.get(k), str) or not env.get(k):
            raise Refused(f"the envelope has no {k}")
    if not isinstance(env.get("at"), (int, float)):
        raise Refused("the envelope has no time")
    if len(env["id"]) > 64 or len(env["from"]) > 80 or len(env["to"]) > 80:
        raise Refused("the envelope's names are too long")
    if len(env["box"]) > MAX_BYTES * 4 // 3 + 64:
        raise Refused("too big")
    if not isinstance(env.get("to_key", ""), str):
        raise Refused("the envelope's receiver key is not a key")
    return {k: env.get(k, "") for k in ("id", "from", "from_key", "to", "to_key", "at")}


def signed_by(env: dict) -> bool:
    body = {k: v for k, v in env.items() if k != "sig"}
    return holds(env["from_key"], body, env["sig"])


def unlock(env: dict, *, me: str, link_private: bytes, now: float | None = None) -> tuple[dict, dict]:
    """(outside, inner) of an envelope for ``me``, or Refused. The signature is checked against the
    key the envelope names; whether that key is the sender's is the caller's to check."""
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
    from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

    head = outside(env)
    if head["to"] != me:
        raise Refused("this envelope is for another Rouh")
    t = time.time() if now is None else now
    if head["at"] > t + SKEW or head["at"] < t - MAX_AGE:
        raise Refused("this envelope is too old, or from the future")
    if not signed_by(env):
        raise Refused("the signature does not hold")
    shared = X25519PrivateKey.from_private_bytes(link_private).exchange(
        X25519PublicKey.from_public_bytes(unb64(env["eph"])))
    aad = canonical({k: env.get(k, "") for k in ("v", "id", "from", "from_key", "to", "to_key", "at", "eph", "nonce")})
    try:
        raw = ChaCha20Poly1305(_key(shared, env["id"], env["from"], env["to"])).decrypt(
            unb64(env["nonce"]), unb64(env["box"]), aad)
    except InvalidTag:
        raise Refused("the box does not open with this Rouh's key") from None
    try:
        inner = json.loads(raw)
    except ValueError:
        raise Refused("the box held no JSON") from None
    if not isinstance(inner, dict):
        raise Refused("the box held no object")
    return head, inner


# --- a group's key, for three or more (phase 2) -------------------------------------------------


def group_lock(epoch_key: bytes, epoch: int, space_id: str, sender: str, sender_seed: bytes,
               sender_key: str, inner: dict) -> dict:
    """One box for a whole group, under its epoch key (`rouh/link/groups.py`), signed by the sender."""
    from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

    nonce = os.urandom(12)
    head = {"v": 1, "group": space_id, "epoch": int(epoch), "from": sender, "from_key": sender_key,
            "at": round(time.time(), 3), "nonce": b64(nonce), "id": str(uuid.uuid4())}
    box = ChaCha20Poly1305(epoch_key).encrypt(nonce, canonical(inner), canonical(head))
    env = {**head, "box": b64(box)}
    env["sig"] = sign(sender_seed, env)
    return env


def group_unlock(env: dict, epoch_key: bytes) -> dict:
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

    body = {k: v for k, v in env.items() if k != "sig"}
    if not holds(str(env.get("from_key") or ""), body, str(env.get("sig") or "")):
        raise Refused("the signature does not hold")
    head = {k: env[k] for k in ("v", "group", "epoch", "from", "from_key", "at", "nonce", "id")}
    try:
        raw = ChaCha20Poly1305(epoch_key).decrypt(unb64(env["nonce"]), unb64(env["box"]), canonical(head))
    except InvalidTag:
        raise Refused("the box does not open with this epoch's key") from None
    return json.loads(raw)
