"""Passkeys: the WebAuthn checks a sign-in with one needs, and nothing more (`rouh/signin.py`).

A passkey is an extra a person adds in Anatomy, You, Account, after signing in by email. Petar,
4 November 2026: "passkey/face/touch should be extra, not default". It never replaces the email:
removing every passkey leaves the account exactly as reachable as before.

What is checked, the way the WebAuthn specification asks a relying party to:

- **Adding one** (`registration`): the browser's client data says ``webauthn.create``, carries the
  challenge this server gave and this page's own origin; the authenticator data is for this host
  (its SHA-256), says a person was present, and carries the new credential, whose public key is
  kept as the COSE map it came in. Attestation is not asked for ("none"), so nothing about the
  device is kept or judged.
- **Signing in with one** (`assertion`): ``webauthn.get``, the same challenge and origin checks, a
  person present, the signature over the authenticator data and the hash of the client data, made
  by the key kept for that credential, and a signature counter that moved forward when the device
  keeps one.

Written on the `cryptography` library Rouh already ships with, so a passkey adds no library to
the containers. Three algorithms, the ones every platform authenticator uses: ES256 (-7), EdDSA
(-8) and RS256 (-257).
"""
from __future__ import annotations

import base64
import hashlib
import json
import struct

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, padding, rsa

#: The algorithms offered when a passkey is made, in order of preference.
ALGORITHMS = (-7, -8, -257)


class Wrong(ValueError):
    """What the browser sent does not hold; the text says why, for the log."""


def b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def unb64url(text: str) -> bytes:
    text = str(text or "")
    try:
        return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except (ValueError, TypeError) as exc:
        raise Wrong("not base64url") from exc


# --- CBOR, as much of it as WebAuthn uses ------------------------------------------------------


def _cbor(data: bytes, at: int = 0):
    """One CBOR item from `data` at `at`: (value, where the next item starts)."""
    if at >= len(data):
        raise Wrong("CBOR ended early")
    head = data[at]
    major, info = head >> 5, head & 31
    at += 1
    if info < 24:
        n = info
    elif info in (24, 25, 26, 27):
        size = 1 << (info - 24)
        if at + size > len(data):
            raise Wrong("CBOR ended early")
        n = int.from_bytes(data[at:at + size], "big")
        at += size
    else:
        raise Wrong("CBOR of a length this does not read")
    if major == 0:
        return n, at
    if major == 1:
        return -1 - n, at
    if major in (2, 3):
        if at + n > len(data):
            raise Wrong("CBOR ended early")
        raw = data[at:at + n]
        return (raw if major == 2 else raw.decode("utf-8", "strict")), at + n
    if major == 4:
        out = []
        for _ in range(n):
            item, at = _cbor(data, at)
            out.append(item)
        return out, at
    if major == 5:
        out = {}
        for _ in range(n):
            key, at = _cbor(data, at)
            value, at = _cbor(data, at)
            out[key] = value
        return out, at
    if major == 7:
        return {20: False, 21: True, 22: None}.get(info), at
    raise Wrong("CBOR of a kind this does not read")


def cbor(data: bytes):
    return _cbor(bytes(data))[0]


# --- the parts -------------------------------------------------------------------------------


def _client_data(raw: bytes, kind: str, challenge: bytes, origin: str) -> bytes:
    try:
        said = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise Wrong("client data is not JSON") from exc
    if said.get("type") != kind:
        raise Wrong(f"client data is {said.get('type')!r}, not {kind}")
    if unb64url(said.get("challenge", "")) != challenge:
        raise Wrong("the challenge is not the one given")
    if said.get("origin") != origin:
        raise Wrong(f"the origin {said.get('origin')!r} is not {origin}")
    return hashlib.sha256(raw).digest()


def _auth_data(raw: bytes, rp_id: str) -> tuple[int, int]:
    if len(raw) < 37:
        raise Wrong("authenticator data is too short")
    if raw[:32] != hashlib.sha256(rp_id.encode()).digest():
        raise Wrong("authenticator data is for another site")
    flags = raw[32]
    if not flags & 0x01:
        raise Wrong("no person was present")
    return flags, struct.unpack(">I", raw[33:37])[0]


def public_key(cose: bytes):
    """The key a COSE map holds, and its algorithm."""
    key = cbor(cose)
    if not isinstance(key, dict):
        raise Wrong("the public key is not a COSE map")
    alg, kty = key.get(3), key.get(1)
    if alg == -7 and kty == 2 and key.get(-1) == 1:
        x, y = key.get(-2), key.get(-3)
        return alg, ec.EllipticCurvePublicNumbers(int.from_bytes(x, "big"), int.from_bytes(y, "big"),
                                                  ec.SECP256R1()).public_key()
    if alg == -8 and kty == 1 and key.get(-1) == 6:
        return alg, ed25519.Ed25519PublicKey.from_public_bytes(key.get(-2))
    if alg == -257 and kty == 3:
        n, e = key.get(-1), key.get(-2)
        return alg, rsa.RSAPublicNumbers(int.from_bytes(e, "big"), int.from_bytes(n, "big")).public_key()
    raise Wrong(f"a key of algorithm {alg} is not one this takes")


def registration(*, client_data: bytes, attestation: bytes, challenge: bytes, origin: str,
                 rp_id: str) -> dict:
    """A new passkey, checked: {credential_id, public_key (COSE bytes), sign_count}."""
    _client_data(client_data, "webauthn.create", challenge, origin)
    att = cbor(attestation)
    if not isinstance(att, dict) or not isinstance(att.get("authData"), bytes):
        raise Wrong("the attestation has no authenticator data")
    auth = att["authData"]
    flags, count = _auth_data(auth, rp_id)
    if not flags & 0x40:
        raise Wrong("no credential in the authenticator data")
    at = 37 + 16
    if len(auth) < at + 2:
        raise Wrong("authenticator data is too short")
    length = struct.unpack(">H", auth[at:at + 2])[0]
    at += 2
    cred_id = auth[at:at + length]
    if len(cred_id) != length or not length:
        raise Wrong("the credential id is cut short")
    at += length
    _key, end = _cbor(auth, at)
    cose = auth[at:end]
    public_key(cose)   # one this can check later, or refused now
    return {"credential_id": bytes(cred_id), "public_key": bytes(cose), "sign_count": count}


def assertion(*, client_data: bytes, auth_data: bytes, signature: bytes, cose: bytes, challenge: bytes,
              origin: str, rp_id: str, sign_count: int) -> int:
    """A sign-in with a passkey, checked; gives back the new signature count."""
    digest = _client_data(client_data, "webauthn.get", challenge, origin)
    _flags, count = _auth_data(auth_data, rp_id)
    alg, key = public_key(cose)
    signed = bytes(auth_data) + digest
    try:
        if alg == -7:
            key.verify(signature, signed, ec.ECDSA(hashes.SHA256()))
        elif alg == -8:
            key.verify(signature, signed)
        else:
            key.verify(signature, signed, padding.PKCS1v15(), hashes.SHA256())
    except InvalidSignature as exc:
        raise Wrong("the signature does not hold") from exc
    if count and sign_count and count <= sign_count:
        raise Wrong("the signature counter went backwards: the passkey may have been copied")
    return count
