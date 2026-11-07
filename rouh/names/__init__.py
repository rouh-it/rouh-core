"""A Rouh's own name, worked out from its birth key, and the recovery words of its recovery key.

Petar, 23 October 2026 (task 141): "Rouh is the species; each Rouh has its own real name, not
chosen by the person": a quality and a thing of nature, two words, such as Quiet Ember, Still
Heron or Brave Oak. The name comes from the Rouh's birth public key and nothing else, once, at
birth: the same key always gives the same name, so nobody, rouh.land included, can choose it or
ask for another, and a Rouh with no rouh.land account works out its own the same way, offline.
A short tag from the same key, such as "k7q2", tells two Rouhs of the same name apart; it is
shown only when names clash (`Name.tagged`).

How (version 1, frozen):

* `h = SHA-256("rouh-name-v1" 0x00 <the 32 bytes of the Ed25519 public key>)`.
* The quality is word `int(h[0:8]) mod len(qualities)`, the nature word `int(h[8:16]) mod
  len(natures)`, both big-endian. A pair that may not be (`acceptable`) is passed over for the
  pair from `SHA-256(h || n)`, n = 1, 2, ..., until one may.
* The tag is the first 20 bits of `h[16:19]` in the base32 letters below: 4 characters.

The word lists beside this file are part of the name: a changed list would rename every Rouh.
So each is pinned by its SHA-256 (`PINNED`) and refused if it differs; new lists would be a
version 2 beside these, and a name keeps the version it was made with. rouh.land holds a copy of
this file and its lists (its `birth` app), held to the same hashes, so both work out the same
name from the same key.

The recovery words are BIP-39's English list and its encoding: 128 bits of randomness, 12 words,
the last carrying a 4-bit check, so a mistyped word is caught. The recovery key is the Ed25519
key whose 32-byte seed is HMAC-SHA-256("rouh recovery key v1", BIP-39 seed of the words, no
passphrase): the words are the key, and nothing else needs keeping.

Standard library only: rouh.land, the page's check and a person with Python can all run it.

    python3 -m rouh.names <base64 public key>      the name and tag that key gives
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

HERE = Path(__file__).resolve().parent
VERSION = 1
FILES = ("qualities.txt", "natures.txt", "banned.txt", "recovery_words.txt")
#: Each list's SHA-256, by version. Version 1 is every Rouh named since 23 October 2026.
PINNED = {1: {
    "qualities.txt": "501b858d1cd8efbe8d4c96ae0169c7502f8e4bc774b941b944328118d35ccc08",
    "natures.txt": "793caa9993579225a7b2e68921473af45467a584064c2cea090381be840b12fa",
    "banned.txt": "09e81a1720e8c1ce7e5b38f64ff2afd293e57eacca538e166ba16f90b53ec9a1",
    "recovery_words.txt": "2f5eed53a4727b4bf8880d8f3f199efc90e58503646d9ff8eff3a2ed3b24dbda",
}}
#: The tag's letters: Crockford's base32, lower case, with no letters people misread.
TAG_LETTERS = "0123456789abcdefghjkmnpqrstvwxyz"
#: A quality of rank or might beside one of these animals or skies is never a name, so that a
#: name never reads as an imitation of any people's names (task 141, step 141-10).
STEREOTYPE_QUALITIES = frozenset("brave proud noble fierce mighty".split())
STEREOTYPE_NATURES = frozenset("eagle wolf bear hawk bison buffalo elk crow raven horse stallion "
                               "thunder cloud moon sky coyote cougar falcon".split())


class NameProblem(ValueError):
    """The lists are not the ones this version was made with, or a key is not a key."""


@dataclass(frozen=True)
class Name:
    quality: str
    nature: str
    tag: str
    version: int = VERSION

    @property
    def words(self) -> str:
        return f"{self.quality.capitalize()} {self.nature.capitalize()}"

    @property
    def tagged(self) -> str:
        return f"{self.words} ·{self.tag}"

    def __str__(self) -> str:
        return self.words


def _read(name: str, version: int) -> list[str]:
    raw = (HERE / name).read_bytes()
    want = PINNED[version][name]
    got = hashlib.sha256(raw).hexdigest()
    if want and got != want:
        raise NameProblem(f"{name} is not the list version {version} names were made with "
                         f"(sha256 {got[:12]}, pinned {want[:12]}): a changed list would rename every Rouh")
    lines = raw.decode().splitlines()
    return [x.strip() for x in lines if x.strip() and not x.lstrip().startswith("#")]


@lru_cache(maxsize=4)
def lists(version: int = VERSION) -> tuple[tuple[str, ...], tuple[str, ...], frozenset]:
    if version not in PINNED:
        raise NameProblem(f"there is no version {version} of the name lists")
    q = tuple(_read("qualities.txt", version))
    n = tuple(_read("natures.txt", version))
    banned = frozenset(tuple(line.split()) for line in _read("banned.txt", version))
    return q, n, banned


@lru_cache(maxsize=2)
def recovery_words(version: int = VERSION) -> tuple[str, ...]:
    words = tuple(_read("recovery_words.txt", version))
    if len(words) != 2048:
        raise NameProblem("the recovery word list has to be 2048 words")
    return words


def acceptable(quality: str, nature: str, version: int = VERSION) -> bool:
    """Whether this pair may be a Rouh's name: not banned, not one word twice or one word
    inside the other (Snowy Snowflake), and not a quality of rank or might beside one of
    the animals and skies in STEREOTYPE_NATURES."""
    _, _, banned = lists(version)
    if (quality, nature) in banned:
        return False
    if quality[:4] == nature[:4] or quality in nature or nature in quality:
        return False
    if quality in STEREOTYPE_QUALITIES and nature in STEREOTYPE_NATURES:
        return False
    return True


def _raw(public) -> bytes:
    if isinstance(public, str):
        try:
            public = base64.b64decode(public, validate=True)
        except ValueError:
            raise NameProblem("that is not a base64 public key") from None
    if not isinstance(public, (bytes, bytearray)) or len(public) != 32:
        raise NameProblem("an Ed25519 public key is 32 bytes")
    return bytes(public)


def tag_of(public, version: int = VERSION) -> str:
    h = hashlib.sha256(b"rouh-name-v1\x00" + _raw(public)).digest()
    bits = int.from_bytes(h[16:19], "big") >> 4
    return "".join(TAG_LETTERS[(bits >> s) & 31] for s in (15, 10, 5, 0))


def derive(public, version: int = VERSION) -> Name:
    """The one name this public key gives (bytes, or base64 text)."""
    raw = _raw(public)
    q, n, _ = lists(version)
    h = hashlib.sha256(b"rouh-name-v1\x00" + raw).digest()
    d, step = h, 0
    while True:
        quality = q[int.from_bytes(d[0:8], "big") % len(q)]
        nature = n[int.from_bytes(d[8:16], "big") % len(n)]
        if acceptable(quality, nature, version):
            return Name(quality, nature, tag_of(raw, version), version)
        step += 1
        d = hashlib.sha256(h + step.to_bytes(4, "big")).digest()


def same_name(a: str, b: str) -> bool:
    return " ".join(str(a or "").lower().split()) == " ".join(str(b or "").lower().split())


# --- recovery words ---------------------------------------------------------------------------


def new_entropy() -> bytes:
    return secrets.token_bytes(16)


def to_words(entropy: bytes) -> list[str]:
    """BIP-39: 16 bytes and a 4-bit check, as 12 words."""
    if len(entropy) != 16:
        raise NameProblem("recovery words carry 16 bytes")
    words = recovery_words()
    check = hashlib.sha256(entropy).digest()[0] >> 4
    bits = (int.from_bytes(entropy, "big") << 4) | check
    return [words[(bits >> (11 * (11 - i))) & 2047] for i in range(12)]


def from_words(text: str) -> bytes:
    """The 16 bytes back out of the 12 words, or NameProblem saying what is wrong, in words."""
    got = [w for w in re.split(r"[\s,.;]+", str(text or "").strip().lower()) if w]
    got = [re.sub(r"^\d+[).:-]?", "", w) or w for w in got]
    got = [w for w in got if w]
    if len(got) != 12:
        raise NameProblem(f"there are 12 recovery words, and {len(got)} were given")
    words = recovery_words()
    index = {w: i for i, w in enumerate(words)}
    # BIP-39's words are told apart by their first four letters.
    by4 = {w[:4]: i for i, w in enumerate(words)}
    bits = 0
    for pos, w in enumerate(got, 1):
        i = index.get(w, by4.get(w[:4]) if len(w) >= 4 else None)
        if i is None:
            raise NameProblem(f"word {pos}, “{w}”, is not one of the recovery words")
        bits = (bits << 11) | i
    entropy, check = (bits >> 4).to_bytes(16, "big"), bits & 15
    if hashlib.sha256(entropy).digest()[0] >> 4 != check:
        raise NameProblem("the words are not in the right order, or one of them is wrong")
    return entropy


def recovery_seed(entropy: bytes) -> bytes:
    """The recovery key's 32-byte Ed25519 seed, from its 16 bytes of randomness."""
    phrase = " ".join(to_words(entropy)).encode()
    seed = hashlib.pbkdf2_hmac("sha512", phrase, b"mnemonic", 2048)
    return hmac.new(b"rouh recovery key v1", seed, hashlib.sha256).digest()


def main(argv) -> int:
    if len(argv) != 2:
        print(__doc__.rsplit("\n\n", 1)[-1].strip())
        return 2
    name = derive(argv[1].strip())
    print(f"{name.words}\n{name.tagged}")
    return 0
