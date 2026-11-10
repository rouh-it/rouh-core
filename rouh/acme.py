"""A certificate from Let's Encrypt for one name, by its HTTP-01 check (RFC 8555).

The phone address of a Rouh (`rouh/relay.py`) is locked with a certificate the Rouh holds
itself, so the relay in between passes the locked bytes on by name and never sees what is in
them. This is the smallest ACME client that gets one: an account key, an order for one name,
the HTTP-01 check answered from Rouh's own web server through the relay's port 80
(`/.well-known/acme-challenge/<token>`), the order finalised with a new key's signing request,
and the chain handed back. Nothing else of ACME is here: no wildcard, no DNS check, no revoke.

``ROUH_ACME_DIRECTORY`` names the service (Let's Encrypt's own unless an installation names
another), and ``ROUH_ACME_CA_BUNDLE`` the certificate a test service's own address is signed with
(Pebble's); real Let's Encrypt needs neither.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import time
from collections.abc import Callable

log = logging.getLogger("rouh.acme")

LETS_ENCRYPT = "https://acme-v02.api.letsencrypt.org/directory"
TIMEOUT = 30.0
#: How long the check and the signing may take before the order is given up for now.
PATIENCE = 180.0


class AcmeError(RuntimeError):
    """The certificate service said no, or did not answer, with what it said in words."""


def directory_url() -> str:
    return os.environ.get("ROUH_ACME_DIRECTORY", "").strip() or LETS_ENCRYPT


def _verify():
    bundle = os.environ.get("ROUH_ACME_CA_BUNDLE", "").strip()
    return bundle or True


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def new_key_pem() -> str:
    """A new P-256 private key, as PEM text."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    key = ec.generate_private_key(ec.SECP256R1())
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption()).decode()


def _load(pem: str):
    from cryptography.hazmat.primitives import serialization

    return serialization.load_pem_private_key(pem.encode(), password=None)


def _jwk(key) -> dict:
    nums = key.public_key().public_numbers()
    return {"crv": "P-256", "kty": "EC", "x": _b64(nums.x.to_bytes(32, "big")), "y": _b64(nums.y.to_bytes(32, "big"))}


def thumbprint(key) -> str:
    jwk = _jwk(key)
    return _b64(hashlib.sha256(json.dumps(jwk, sort_keys=True, separators=(",", ":")).encode()).digest())


def _sign(key, data: bytes) -> bytes:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

    r, s = decode_dss_signature(key.sign(data, ec.ECDSA(hashes.SHA256())))
    return r.to_bytes(32, "big") + s.to_bytes(32, "big")


def _names(name) -> list[str]:
    """One name, or several (a born address and the owner's chosen one, task 140, step 140-13)."""
    names = [name] if isinstance(name, str) else list(name)
    return [n for i, n in enumerate(names) if n and n not in names[:i]]


def csr_der(key_pem: str, name) -> bytes:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.x509.oid import NameOID

    key = _load(key_pem)
    names = _names(name)
    csr = (x509.CertificateSigningRequestBuilder()
           .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, names[0])]))
           .add_extension(x509.SubjectAlternativeName([x509.DNSName(n) for n in names]), critical=False)
           .sign(key, hashes.SHA256()))
    return csr.public_bytes(serialization.Encoding.DER)


def not_after(cert_pem: str) -> float:
    """When the first certificate in this chain stops being good, as a Unix time."""
    from cryptography import x509

    cert = x509.load_pem_x509_certificate(cert_pem.encode())
    when = getattr(cert, "not_valid_after_utc", None) or cert.not_valid_after
    return when.timestamp()


def not_before(cert_pem: str) -> float:
    from cryptography import x509

    cert = x509.load_pem_x509_certificate(cert_pem.encode())
    when = getattr(cert, "not_valid_before_utc", None) or cert.not_valid_before
    return when.timestamp()


class Client:
    """One account on one ACME service. Synchronous: it runs in a thread of its own."""

    def __init__(self, account_pem: str, *, directory: str = "", kid: str = "", contact: str = ""):
        import httpx

        self.key = _load(account_pem)
        self.directory_url = directory or directory_url()
        self.kid = kid
        self.contact = contact
        self.http = httpx.Client(timeout=TIMEOUT, verify=_verify(),
                                 headers={"User-Agent": "Rouh acme"})
        self.dir: dict = {}
        self.nonce = ""

    def close(self) -> None:
        self.http.close()

    def _directory(self) -> dict:
        if not self.dir:
            got = self.http.get(self.directory_url)
            if got.status_code != 200:
                raise AcmeError(f"the certificate service's directory answered {got.status_code}")
            self.dir = got.json()
        return self.dir

    def _new_nonce(self) -> str:
        got = self.http.head(self._directory()["newNonce"])
        nonce = got.headers.get("Replay-Nonce", "")
        if not nonce:
            raise AcmeError("the certificate service gave no nonce")
        return nonce

    def _post(self, url: str, payload, *, tries: int = 3):
        """A signed POST (payload None is POST-as-GET), again with a fresh nonce on badNonce."""
        for attempt in range(tries):
            nonce = self.nonce or self._new_nonce()
            self.nonce = ""
            protected = {"alg": "ES256", "nonce": nonce, "url": url}
            if self.kid:
                protected["kid"] = self.kid
            else:
                protected["jwk"] = _jwk(self.key)
            p64 = _b64(json.dumps(protected).encode())
            b64 = "" if payload is None else _b64(json.dumps(payload).encode())
            sig = _b64(_sign(self.key, f"{p64}.{b64}".encode()))
            got = self.http.post(url, content=json.dumps({"protected": p64, "payload": b64, "signature": sig}),
                                 headers={"Content-Type": "application/jose+json"})
            self.nonce = got.headers.get("Replay-Nonce", "")
            if got.status_code < 400:
                return got
            try:
                problem = got.json()
            except ValueError:
                problem = {}
            if problem.get("type", "").endswith(":badNonce") and attempt + 1 < tries:
                continue
            raise AcmeError(f"{problem.get('detail') or 'the certificate service refused'} "
                            f"({got.status_code}, {problem.get('type', '').rsplit(':', 1)[-1] or 'no type'})")
        raise AcmeError("the certificate service kept refusing the nonce")

    def account(self) -> str:
        """This key's account, made if it is new; its address (the kid) is given back."""
        if self.kid:
            return self.kid
        body: dict = {"termsOfServiceAgreed": True}
        if self.contact:
            body["contact"] = [f"mailto:{self.contact}"]
        got = self._post(self._directory()["newAccount"], body)
        self.kid = got.headers.get("Location", "")
        if not self.kid:
            raise AcmeError("the certificate service made no account address")
        return self.kid

    def _wait(self, url: str, done: set[str], what: str) -> dict:
        until = time.monotonic() + PATIENCE
        while True:
            got = self._post(url, None).json()
            status = got.get("status")
            if status in done:
                return got
            if status == "invalid":
                why = ""
                for ch in got.get("challenges") or []:
                    if ch.get("error"):
                        why = ch["error"].get("detail") or ""
                why = why or (got.get("error") or {}).get("detail") or ""
                raise AcmeError(f"the {what} failed: {why or 'no reason given'}")
            if time.monotonic() > until:
                raise AcmeError(f"the {what} took too long (still {status})")
            time.sleep(2)

    def certificate(self, name, key_pem: str, publish: Callable[[str, str], None],
                    unpublish: Callable[[str], None]) -> str:
        """A certificate chain for ``name`` (or a list of names, all on one certificate), signed for
        ``key_pem``. ``publish(token, answer)`` puts the check's answer where
        ``/.well-known/acme-challenge/<token>`` serves it."""
        self.account()
        got = self._post(self._directory()["newOrder"],
                         {"identifiers": [{"type": "dns", "value": n} for n in _names(name)]})
        order_url = got.headers.get("Location", "")
        order = got.json()
        tokens = []
        try:
            for authz_url in order.get("authorizations") or []:
                authz = self._post(authz_url, None).json()
                if authz.get("status") == "valid":
                    continue
                http01 = next((c for c in authz.get("challenges") or [] if c.get("type") == "http-01"), None)
                if http01 is None:
                    raise AcmeError("the certificate service offered no HTTP-01 check")
                token = http01["token"]
                publish(token, f"{token}.{thumbprint(self.key)}")
                tokens.append(token)
                self._post(http01["url"], {})
                self._wait(authz_url, {"valid"}, "check that this Rouh answers on its address")
            order = self._wait(order_url, {"ready", "valid"}, "order") if order.get("status") != "ready" else order
            if order.get("status") == "ready":
                self._post(order["finalize"], {"csr": _b64(csr_der(key_pem, name))})
                order = self._wait(order_url, {"valid"}, "signing")
            chain = self._post(order["certificate"], None).text
        finally:
            for token in tokens:
                unpublish(token)
        if "BEGIN CERTIFICATE" not in chain:
            raise AcmeError("the certificate service gave back no certificate")
        return chain
