"""The signature checks on a shared gene: part of the protected core since 24 October 2026.

Task 98, step 98-23: "Accept a shared gene whose signature does not check out" is one of the
things a Rouh can no longer do, so the checks that decide it left the Rouh's own code
(``rouh/genelab.py``) for the protected core, which a Rouh uses and cannot edit. They are the same
functions as before, moved: the registry's Ed25519 key read from its PEM, a signed list checked
against it, the address a gene may be fetched from, the fetch itself, the Sigstore signature
checked against the publisher's build identity, and the gene's files unpacked in memory with
links, devices and paths that climb out refused.

A Rouh in a container asks for them over the guard's socket (``gene`` in ``rouh_guard.server``);
a Rouh with no protected core beside it (the server Rouh runs on, a test world) imports them from
its repository's ``guard/`` (``rouh/guardface.py``). Either way the Rouh gets back plain values:
a key is its PEM, bytes are bytes.
"""
from __future__ import annotations

import base64
import contextlib
import hashlib
import io
import ipaddress
import json
import re
import tarfile
import zipfile
from urllib.parse import urlsplit

MOST_LIST = 5 * 1024 * 1024
MOST_UNPACKED = 40 * 1024 * 1024
MOST_FILES = 400
TIMEOUT = 20.0
GITHUB_ISSUER = "https://token.actions.githubusercontent.com"


class Refused(ValueError):
    """What is not taken, with the reason as a sentence."""


def canonical(payload) -> bytes:
    """The bytes a registry signs: the payload as JSON, keys sorted, no spaces."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _text(value, most: int = 4000) -> str:
    return str(value).strip()[:most] if isinstance(value, (str, int, float)) else ""


def load_key(pem: str):
    """The registry's Ed25519 public key from its PEM, or Refused saying what is wrong."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    text = str(pem or "").strip()
    if not text:
        raise Refused("Paste the registry's public key: the PEM that starts with -----BEGIN PUBLIC KEY-----.")
    try:
        key = serialization.load_pem_public_key(text.encode())
    except Exception:
        raise Refused("That is not a public key in PEM form: it starts with -----BEGIN PUBLIC KEY-----.") from None
    if not isinstance(key, Ed25519PublicKey):
        raise Refused("That key is not an Ed25519 key, which is what a gene registry signs with.")
    return key


def key_id(key) -> str:
    """The registry's own name for its key: the first 16 hex of the SHA-256 of its raw bytes."""
    from cryptography.hazmat.primitives import serialization

    raw = key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return hashlib.sha256(raw).hexdigest()[:16]


def verify(document, key, kind: str) -> dict:
    """A fetched list's payload, if it is signed by the pinned key and is the kind expected.
    Raises Refused saying which of those failed."""
    from cryptography.exceptions import InvalidSignature

    if not isinstance(document, dict) or not isinstance(document.get("payload"), dict):
        raise Refused("it is not a signed list: there is no payload in it")
    if document.get("key_id") != key_id(key):
        raise Refused(f"it is signed by another key ({str(document.get('key_id'))[:20]!r}, "
                      f"not the pinned {key_id(key)})")
    try:
        key.verify(base64.b64decode(str(document.get("signature") or ""), validate=True),
                   canonical(document["payload"]))
    except (InvalidSignature, ValueError):
        raise Refused("its signature does not hold against the pinned key, so it was changed "
                      "or not made by that registry") from None
    payload = document["payload"]
    if payload.get("kind") != kind:
        raise Refused(f"it says it is {str(payload.get('kind'))[:40]!r}, not {kind!r}")
    return payload



def _loopback(host: str) -> bool:
    if host in ("localhost",):
        return True
    with contextlib.suppress(ValueError):
        return ipaddress.ip_address(host).is_loopback
    return False


def url_ok(url: str) -> str:
    """An address Rouh may fetch a gene from: https, or http on this machine for a local
    copy of a registry. Anything else is Refused."""
    url = str(url or "").strip()
    try:
        parts = urlsplit(url)
    except ValueError:
        raise Refused(f"{url[:80]!r} is not an address.") from None
    if parts.scheme == "https" and parts.hostname:
        return url
    if parts.scheme == "http" and parts.hostname and _loopback(parts.hostname):
        return url
    raise Refused("A registry and its genes are fetched over https only (or over http from this "
                  f"machine itself, for a local copy): {url[:80]!r} is neither.")


def fetch(url: str, most: int) -> bytes:
    import httpx

    url_ok(url)
    with httpx.Client(timeout=TIMEOUT, follow_redirects=True, max_redirects=5,
                      headers={"User-Agent": "Rouh gene lab (protected core)", "Accept": "*/*"}) as client:
        with client.stream("GET", url) as r:
            url_ok(str(r.url))
            if r.status_code != 200:
                raise Refused(f"{urlsplit(url).hostname} answered {r.status_code}")
            got = bytearray()
            for chunk in r.iter_bytes():
                got.extend(chunk)
                if len(got) > most:
                    raise Refused(f"it is larger than {most // (1024 * 1024)} MB")
            return bytes(got)



def _identity_policy(sig: dict, provenance: dict):
    """What the signature has to have been made by: what the registry's signed index says,
    never what the signature itself says."""
    from sigstore.verify import policy

    ident = sig.get("identity") if isinstance(sig.get("identity"), dict) else {}
    issuer = _text(ident.get("issuer") or sig.get("issuer"), 300) or GITHUB_ISSUER
    san = _text(ident.get("identity") or ident.get("san") or sig.get("san"), 500)
    if san:
        return policy.Identity(identity=san, issuer=issuer), f"{san}, issued by {issuer}"
    repo = _text(ident.get("repository") or provenance.get("repository"), 300)
    repo = re.sub(r"^https?://github\.com/", "", repo).strip("/")
    if not repo or issuer != GITHUB_ISSUER:
        raise Refused("the registry gave a Sigstore signature without saying whose build made it")
    rules = [policy.OIDCIssuer(issuer), policy.GitHubWorkflowRepository(repo)]
    commit = _text(ident.get("commit") or provenance.get("commit"), 64)
    if re.fullmatch(r"[0-9a-f]{40}", commit):
        rules.append(policy.GitHubWorkflowSHA(commit))
    return policy.AllOf(rules), f"GitHub Actions in {repo}" + (f" at {commit[:12]}" if commit else "")


def sigstore_check(artifact: bytes, sig: dict, provenance: dict) -> dict:
    """The artifact's Sigstore signature checked, where the registry gives one: {state, said}.
    state is "verified", "none" (the registry gave none) or Refused is raised."""
    if not sig:
        return {"state": "none", "said": "The registry gave no Sigstore signature for this version, so "
                                         "Rouh checked its files against the signed index's hash alone."}
    bundle = sig.get("bundle")
    if not bundle and sig.get("bundle_url"):
        try:
            bundle = json.loads(fetch(url_ok(_text(sig["bundle_url"], 2000)), MOST_LIST).decode("utf-8"))
        except Refused as exc:
            raise Refused(f"its Sigstore signature could not be fetched: {exc}") from None
        except Exception:
            raise Refused("its Sigstore signature could not be fetched") from None
    if not isinstance(bundle, (dict, str)) or not bundle:
        raise Refused("the registry named a Sigstore signature and gave none")
    try:
        from sigstore.models import Bundle
        from sigstore.verify import Verifier
    except ImportError:
        raise Refused("the registry gave a Sigstore signature, and Sigstore cannot be checked on "
                      "this machine yet") from None
    rule, whose = _identity_policy(sig, provenance)
    try:
        b = Bundle.from_json(bundle if isinstance(bundle, str) else json.dumps(bundle))
        Verifier.production().verify_artifact(artifact, b, rule)
    except Refused:
        raise
    except Exception as exc:
        raise Refused(f"its Sigstore signature does not hold ({type(exc).__name__}: "
                      f"{str(exc)[:160]})") from None
    return {"state": "verified", "said": f"Its Sigstore signature holds: signed by {whose}.",
            "identity": whose}



def _clean_path(name: str) -> str | None:
    parts = [p for p in str(name).replace("\\", "/").split("/") if p not in ("", ".")]
    if not parts or any(p == ".." for p in parts) or str(name).startswith("/"):
        return None
    return "/".join(parts)[:300]


def unpack(data: bytes, name: str = "") -> dict[str, bytes]:
    """The files in a gene's artifact: a tar (any compression), a zip, or one file as it is.
    Links, devices and paths that climb out are refused, and so is too much."""
    out: dict[str, bytes] = {}
    total = 0

    def keep(path, body):
        nonlocal total
        p = _clean_path(path)
        if p is None:
            raise Refused(f"it has a file whose path climbs out of it: {str(path)[:80]!r}")
        total += len(body)
        if len(out) >= MOST_FILES or total > MOST_UNPACKED:
            raise Refused("it unpacks into more than Rouh keeps for a gene")
        out[p] = body

    buf = io.BytesIO(data)
    if zipfile.is_zipfile(buf):
        with zipfile.ZipFile(buf) as z:
            for info in z.infolist():
                if info.is_dir():
                    continue
                if (info.external_attr >> 16) & 0o170000 == 0o120000:
                    raise Refused("it has a link in it, which a gene's files never need")
                keep(info.filename, z.read(info))
        return out
    try:
        tar = tarfile.open(fileobj=io.BytesIO(data), mode="r:*")
    except tarfile.TarError:
        tar = None
    if tar is not None:
        with tar:
            for m in tar.getmembers():
                if m.isdir():
                    continue
                if not m.isfile():
                    raise Refused("it has a link or a device in it, which a gene's files never need")
                f = tar.extractfile(m)
                keep(m.name, f.read() if f else b"")
        return out
    keep(_clean_path(name) or "gene", data)
    return out


def key_of(pem: str) -> dict:
    """A registry key, checked: {"pem", "id"}."""
    key = load_key(pem)
    return {"pem": str(pem).strip(), "id": key_id(key)}


def verify_pem(document, pem: str, kind: str) -> dict:
    return verify(document, load_key(pem), kind)
