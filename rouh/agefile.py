"""Files encrypted in age's format (age-encryption.org/v1), with nothing but `cryptography`.

The weekly copy off the machine (`rouh/offsite.py`) is encrypted before it leaves, and the
containers a Rouh runs in have no gpg and no age to do it with: the base is Python and its
libraries, and nothing new is installed on the machine for it. So this writes age's own
format, which is small and fully specified (https://age-encryption.org/v1), from the
primitives `cryptography` already has: X25519, HKDF-SHA-256, HMAC-SHA-256, scrypt and
ChaCha20-Poly1305. What it writes the stock `age` opens (`age -d -i key.txt copy.age`), on any
machine, and what `age` writes this opens; the stack test proves the first with the real `age`.

Two kinds of recipient, as age has:

- a public key, ``age1...`` (``age-keygen`` makes one, with its private half ``AGE-SECRET-KEY-1...``),
  so the machine that makes the copies cannot open them, and only whoever keeps the private
  half off it can. The better of the two;
- a passphrase (age's scrypt recipient), when nothing but a long word is kept off the machine.

    python -m rouh.agefile encrypt --recipient age1... < plain > sealed.age
    python -m rouh.agefile decrypt --identity key.txt < sealed.age > plain
    ROUH_AGE_PASSPHRASE=... python -m rouh.agefile decrypt < sealed.age > plain

Nothing here prints or logs a key, a passphrase or anything it opened.
"""
from __future__ import annotations

import base64
import hmac
import io
import os
import sys
from typing import BinaryIO, Iterable

MAGIC = b"age-encryption.org/v1"
CHUNK = 64 * 1024
TAG = 16
#: age's own work factor for a passphrase (2**18): about a second, and 256 MB, to try one.
SCRYPT_LOG_N = 18


class AgeError(ValueError):
    """Not an age file this can open: the wrong key or passphrase, or a file changed or cut short."""


# --- the primitives -------------------------------------------------------------------------

def _hkdf(ikm: bytes, salt: bytes | None, info: bytes) -> bytes:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    return HKDF(algorithm=hashes.SHA256(), length=32, salt=salt or None, info=info).derive(ikm)


def _aead(key: bytes):
    from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

    return ChaCha20Poly1305(key)


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    if "=" in text or "\n" in text or "\r" in text:
        raise AgeError("the header is not canonical base64")
    try:
        data = base64.b64decode(text + "=" * (-len(text) % 4), validate=True)
    except Exception as exc:
        raise AgeError("the header is not base64") from exc
    if _b64(data) != text:
        raise AgeError("the header is not canonical base64")
    return data


def _wrap(data: bytes) -> bytes:
    """A stanza's body: base64 at 64 columns, the last line always shorter than 64 (so maybe empty)."""
    text = _b64(data)
    lines = [text[i:i + 64] for i in range(0, len(text), 64)]
    if not lines or len(lines[-1]) == 64:
        lines.append("")
    return "".join(line + "\n" for line in lines).encode()


# --- Bech32, for age's keys ---------------------------------------------------------------------

_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"


def _polymod(values: Iterable[int]) -> int:
    gen = (0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3)
    chk = 1
    for v in values:
        top = chk >> 25
        chk = (chk & 0x1FFFFFF) << 5 ^ v
        for i in range(5):
            chk ^= gen[i] if (top >> i) & 1 else 0
    return chk


def _hrp_expand(hrp: str) -> list[int]:
    return [ord(c) >> 5 for c in hrp] + [0] + [ord(c) & 31 for c in hrp]


def _convert(data: Iterable[int], frm: int, to: int, pad: bool) -> list[int]:
    acc = bits = 0
    out = []
    for v in data:
        acc = (acc << frm) | v
        bits += frm
        while bits >= to:
            bits -= to
            out.append((acc >> bits) & ((1 << to) - 1))
    if pad and bits:
        out.append((acc << (to - bits)) & ((1 << to) - 1))
    elif not pad and (bits >= frm or (acc << (to - bits)) & ((1 << to) - 1)):
        raise AgeError("not a key: its padding is wrong")
    return out


def bech32_encode(hrp: str, data: bytes) -> str:
    words = _convert(data, 8, 5, True)
    chk = _polymod(_hrp_expand(hrp) + words + [0] * 6) ^ 1
    words += [(chk >> 5 * (5 - i)) & 31 for i in range(6)]
    return hrp + "1" + "".join(_CHARSET[w] for w in words)


def bech32_decode(text: str, hrp: str) -> bytes:
    if text.lower() != text and text.upper() != text:
        raise AgeError("not a key: mixed case")
    text = text.lower()
    sep = text.rfind("1")
    if text[:sep] != hrp or sep < 1 or len(text) - sep < 7:
        raise AgeError(f"not a key of the kind {hrp!r}")
    try:
        words = [_CHARSET.index(c) for c in text[sep + 1:]]
    except ValueError as exc:
        raise AgeError("not a key: a letter that Bech32 has not") from exc
    if _polymod(_hrp_expand(hrp) + words) != 1:
        raise AgeError("not a key: its checksum is wrong (a letter mistyped?)")
    return bytes(_convert(words[:-6], 5, 8, False))


# --- keys -------------------------------------------------------------------------------------

def new_identity() -> tuple[str, str]:
    """A new key pair, as age-keygen makes one: (the private AGE-SECRET-KEY-1..., the public age1...)."""
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, PublicFormat

    key = X25519PrivateKey.generate()
    raw = key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    pub = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return bech32_encode("age-secret-key-", raw).upper(), bech32_encode("age", pub)


def recipient_of(identity: str) -> str:
    """The public age1... of a private AGE-SECRET-KEY-1..."""
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    key = X25519PrivateKey.from_private_bytes(bech32_decode(identity.strip(), "age-secret-key-"))
    return bech32_encode("age", key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw))


def identities_in(text: str) -> list[str]:
    """The private keys in a key file as age-keygen writes it: comments and blank lines skipped."""
    return [line.strip() for line in text.splitlines() if line.strip().upper().startswith("AGE-SECRET-KEY-1")]


# --- the header -------------------------------------------------------------------------------

def _x25519_stanza(recipient: str, file_key: bytes) -> bytes:
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    their = bech32_decode(recipient.strip(), "age")
    if len(their) != 32:
        raise AgeError("not an age public key")
    eph = X25519PrivateKey.generate()
    share = eph.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    shared = eph.exchange(X25519PublicKey.from_public_bytes(their))
    key = _hkdf(shared, share + their, b"age-encryption.org/v1/X25519")
    body = _aead(key).encrypt(bytes(12), file_key, None)
    return b"-> X25519 " + _b64(share).encode() + b"\n" + _wrap(body)


def _scrypt_key(passphrase: str, salt: bytes, log_n: int) -> bytes:
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

    return Scrypt(salt=b"age-encryption.org/v1/scrypt" + salt, length=32, n=1 << log_n, r=8, p=1).derive(
        passphrase.encode())


def _scrypt_stanza(passphrase: str, file_key: bytes, log_n: int) -> bytes:
    salt = os.urandom(16)
    body = _aead(_scrypt_key(passphrase, salt, log_n)).encrypt(bytes(12), file_key, None)
    return f"-> scrypt {_b64(salt)} {log_n}\n".encode() + _wrap(body)


def _header(stanzas: list[bytes], file_key: bytes) -> bytes:
    head = MAGIC + b"\n" + b"".join(stanzas) + b"---"
    mac = hmac.new(_hkdf(file_key, None, b"header"), head, "sha256").digest()
    return head + b" " + _b64(mac).encode() + b"\n"


def _read_header(src: BinaryIO) -> tuple[list[tuple[list[str], bytes]], bytes, bytes]:
    """[(the stanza's arguments, its body)], the header up to "---" for its MAC, and the MAC."""
    def line() -> bytes:
        got = src.readline(4096)
        if not got.endswith(b"\n"):
            raise AgeError("this is not an age file, or it is cut short")
        return got

    first = line()
    if first != MAGIC + b"\n":
        raise AgeError("this is not an age file (age-encryption.org/v1)")
    head, stanzas = first, []
    while True:
        got = line()
        if got.startswith(b"--- "):
            return stanzas, head + b"---", _unb64(got[4:-1].decode("ascii", "replace"))
        if not got.startswith(b"-> "):
            raise AgeError("the age header is not well formed")
        head += got
        args = got[3:-1].decode("ascii", "replace").split(" ")
        body = b""
        while True:
            row = line()
            head += row
            text = row[:-1].decode("ascii", "replace")
            if len(text) > 64:
                raise AgeError("the age header is not well formed")
            body += text.encode()
            if len(text) < 64:
                break
        stanzas.append((args, _unb64(body.decode()) if body else b""))


def _file_key(stanzas, identities: list[str], passphrase: str) -> bytes:
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    if any(args[0] == "scrypt" for args, _ in stanzas) and len(stanzas) != 1:
        raise AgeError("a passphrase stanza must be the only one")
    keys = [X25519PrivateKey.from_private_bytes(bech32_decode(i, "age-secret-key-")) for i in identities]
    for args, body in stanzas:
        try:
            if args[0] == "X25519" and keys and len(args) == 2:
                share = _unb64(args[1])
                for key in keys:
                    shared = key.exchange(X25519PublicKey.from_public_bytes(share))
                    if shared == bytes(32):
                        raise AgeError("a broken X25519 stanza")
                    mine = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
                    try:
                        return _aead(_hkdf(shared, share + mine, b"age-encryption.org/v1/X25519")).decrypt(
                            bytes(12), body, None)
                    except InvalidTag:
                        continue
            elif args[0] == "scrypt" and passphrase and len(args) == 3:
                log_n = int(args[2])
                if not 1 <= log_n <= 22:
                    raise AgeError(f"a passphrase work factor of 2**{log_n}, which is refused")
                return _aead(_scrypt_key(passphrase, _unb64(args[1]), log_n)).decrypt(bytes(12), body, None)
        except InvalidTag:
            continue
    raise AgeError("none of the keys or the passphrase given opens this file")


# --- the payload ----------------------------------------------------------------------------

def _nonce(counter: int, last: bool) -> bytes:
    return counter.to_bytes(11, "big") + (b"\x01" if last else b"\x00")


def encrypt(src: BinaryIO, dst: BinaryIO, *, recipients: Iterable[str] = (), passphrase: str = "",
            log_n: int = SCRYPT_LOG_N) -> int:
    """src's bytes into dst as an age file for the recipients, or for the passphrase. Bytes read."""
    recipients = [r.strip() for r in recipients if r and r.strip()]
    if bool(recipients) == bool(passphrase):
        raise AgeError("give public keys or a passphrase, one of the two")
    file_key = os.urandom(16)
    stanzas = [_x25519_stanza(r, file_key) for r in recipients] or [_scrypt_stanza(passphrase, file_key, log_n)]
    dst.write(_header(stanzas, file_key))
    nonce = os.urandom(16)
    dst.write(nonce)
    aead = _aead(_hkdf(file_key, nonce, b"payload"))
    total, counter = 0, 0
    block = _read_full(src, CHUNK)
    while True:
        after = _read_full(src, CHUNK) if len(block) == CHUNK else b""
        last = not after
        dst.write(aead.encrypt(_nonce(counter, last), block, None))
        total += len(block)
        if last:
            return total
        block, counter = after, counter + 1


def decrypt(src: BinaryIO, dst: BinaryIO, *, identities: Iterable[str] = (), passphrase: str = "") -> int:
    """An age file from src, opened with one of the private keys or the passphrase, into dst. Bytes written."""
    from cryptography.exceptions import InvalidTag

    stanzas, head, mac = _read_header(src)
    file_key = _file_key(stanzas, [i.strip() for i in identities if i and i.strip()], passphrase)
    if not hmac.compare_digest(hmac.new(_hkdf(file_key, None, b"header"), head, "sha256").digest(), mac):
        raise AgeError("the age header was changed")
    nonce = _read_full(src, 16)
    if len(nonce) != 16:
        raise AgeError("the file is cut short")
    aead = _aead(_hkdf(file_key, nonce, b"payload"))
    total, counter = 0, 0
    block = _read_full(src, CHUNK + TAG)
    while True:
        after = _read_full(src, CHUNK + TAG) if len(block) == CHUNK + TAG else b""
        last = not after
        if len(block) < TAG:
            raise AgeError("the file is cut short")
        try:
            plain = aead.decrypt(_nonce(counter, last), block, None)
        except InvalidTag as exc:
            raise AgeError("the file was changed or cut short") from exc
        if last and not plain and counter:
            raise AgeError("the file ends with an empty piece, which age never writes")
        dst.write(plain)
        total += len(plain)
        if last:
            return total
        block, counter = after, counter + 1


def _read_full(src: BinaryIO, n: int) -> bytes:
    out = b""
    while len(out) < n:
        got = src.read(n - len(out))
        if not got:
            break
        out += got
    return out


def encrypt_bytes(data: bytes, **kw) -> bytes:
    out = io.BytesIO()
    encrypt(io.BytesIO(data), out, **kw)
    return out.getvalue()


def decrypt_bytes(data: bytes, **kw) -> bytes:
    out = io.BytesIO()
    decrypt(io.BytesIO(data), out, **kw)
    return out.getvalue()


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="python -m rouh.agefile", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("encrypt", help="stdin to stdout, for a public key or ROUH_AGE_PASSPHRASE")
    e.add_argument("--recipient", action="append", default=[])
    d = sub.add_parser("decrypt", help="stdin to stdout, with a key file or ROUH_AGE_PASSPHRASE")
    d.add_argument("--identity", help="a key file, as age-keygen writes it")
    a = ap.parse_args(argv)
    phrase = os.environ.get("ROUH_AGE_PASSPHRASE", "")
    try:
        if a.cmd == "encrypt":
            encrypt(sys.stdin.buffer, sys.stdout.buffer, recipients=a.recipient, passphrase="" if a.recipient else phrase)
        else:
            ids = identities_in(open(a.identity, encoding="utf-8").read()) if a.identity else []
            decrypt(sys.stdin.buffer, sys.stdout.buffer, identities=ids, passphrase=phrase)
    except AgeError as exc:
        print(f"agefile: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
