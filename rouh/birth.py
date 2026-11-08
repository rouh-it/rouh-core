"""A Rouh's birth: its own name, its two keys, and, if its owner chooses, its place on rouh.land
(task 141; GENES.md, "Birthday"; the page is Anatomy, Rouh Land Account, Rouh profile,
`/anatomy/rouh-land/rouh-profile`, which was Meta, Birthday until 4 November 2026).

Petar, 23 October 2026: "Rouh is the species; each Rouh has its own real name, not chosen by the
person." And 4 November 2026: "I don't think a free rouh should have an official name. free rouh
will get birth and official name by connecting to rouh.land. before that, only a nickname by the
person. so no keys needed." So:

**A free Rouh** has no row here: no name, no keys, nothing to lose. It works fully without
rouh.land. It answers to Rouh, the kind and its given name, and to whatever nickname each person
gives it (`RouhNickname`, theirs alone).

**Its birth is its registration with rouh.land.** When its owner connects it (the first run's
Connected, or Your profile's Sign up or sign in on rouh.land), this Rouh makes its keys in that
moment and sends rouh.land a birth that names nothing (version 2, `be_born`); rouh.land grants its
official name, a quality and a thing of nature such as Still Heron, with a hidden four-letter tag
shown only where two Rouhs share a name, and sends it back in its signed card (`_check_card`). The
name never changes after. If rouh.land cannot be reached, nothing is kept and it stays free.

**Its keys are opaque.** The daily key, sealed here (`rouh/encryption.py`) and in every backup,
signs what it says to rouh.land, the Gene Pool and the relay. The recovery key comes from twelve
words made at the same moment and kept sealed; nothing shows them or asks for them. No page shows
a key, a key id or a registry id; the person sees one sentence (`standing`).

**Rouhs from before.** A Rouh that was born here on its own before 4 November 2026 named itself
from its birth key (a version 1 birth). It keeps that name and those keys, and registers with them
when it connects; a registered Rouh keeps its name and keys exactly as they are. Neither is ever
renamed or given new keys by this change. Account recovery (`recover_start`) and the recovery
words (`rotate`) still work for whoever started them before; nothing offers them now.

**Separate, said plainly.** Model access is its own choice, with its price said, and a rouh.land
account never starts a bill. A Rouh born on rouh.land, or registered there later, joins the Gene
Pool by itself in that moment, under its own name, with its daily key, and exchanges no gene: its
outgoing and incoming genes stay Manual until the owner chooses otherwise (`rouh/genepool.py`,
`join_at_birth`; task 141, step 141-15).

**A second name, earned.** About a hundred days after its birth the Rouh reads its own history
(counts and the names of its genes, never a chat) and gives itself a second name with a short
line on why (`second_name`, the use "second_name" on the Models page). Its owner sees it and
cannot veto it.

Only an administrator connects it, replaces or recovers keys; anybody signed in reads the page and
sets their own nickname. The organisation's row is the one, by `org_id`.
"""
from __future__ import annotations

from . import site as _site

import base64
import hashlib
import io
import json
import logging
import re
import time
from datetime import datetime, timezone

from . import names

log = logging.getLogger("rouh.birth")

NAME = "Birthday"
#: What rouh.land's birth service signs its answers as.
KIND = "rouh-birth"
#: Made from ROUH_SITE_URL, the one setting for Rouh's public site (`rouh/site.py`, task 165).
DEFAULT_URL = _site.url("/registry/birth/")
#: The day a Rouh gives itself its second name, counted from its birth.
SECOND_NAME_DAYS = 100
SECOND_NAME_TRIES = 3
USE = "second_name"
#: How often a Rouh registered on rouh.land asks after its own keys there (`check`).
CHECK_EVERY = 6 * 3600
TIMEOUT = 20.0
#: How far back, at most, "stolen since" may go, and where it starts.
SINCE_DEFAULT_DAYS = 30


class Refused(ValueError):
    """Something this Rouh, or rouh.land, will not do, with the reason in words."""


class Clash(Refused):
    """rouh.land already has a Rouh of this name and tag: a name not yet given is made again."""


def _m():
    from . import models

    return models


def _now() -> float:
    return time.time()


def _iso(at: float) -> str:
    return datetime.fromtimestamp(at, timezone.utc).isoformat(timespec="seconds")


def _from_iso(text) -> float | None:
    try:
        return datetime.fromisoformat(str(text)).timestamp()
    except (TypeError, ValueError):
        return None


def _cut(value, most: int = 300) -> str:
    return " ".join(str(value or "").split())[:most].replace("—", "-")


def _box():
    from .config import config
    from .encryption import SecretBox

    return SecretBox(config.encryption_key, data_dir=config.data_dir)


def _admin(who) -> None:
    if not getattr(who, "is_admin", False):
        raise Refused("Only an administrator of this Rouh does that.")


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


def _key_id(pub_b64: str) -> str:
    try:
        return hashlib.sha256(base64.b64decode(pub_b64)).hexdigest()[:16]
    except ValueError:
        return ""


def current(org: str):
    """This organisation's Rouh as born, or None."""
    return _m().RouhBirth.objects.filter(org_id=str(org), state="born").first()


def _recovering(org: str):
    return _m().RouhBirth.objects.filter(org_id=str(org), state="recovering").first()


def _event(row, what: str, said: str) -> None:
    history = list(row.history or [])
    history.append({"at": _now(), "what": what, "said": _cut(said, 400)})
    _m().RouhBirth.objects.filter(id=row.id).update(history=history[-200:], updated_at=_now())
    row.history = history


# --- keys and what they sign -----------------------------------------------------------------------


def new_key() -> tuple[bytes, bytes]:
    """A new Ed25519 key: its 32-byte private seed and its 32-byte public key."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    return _from_seed(Ed25519PrivateKey.generate().private_bytes_raw())


def _from_seed(seed: bytes) -> tuple[bytes, bytes]:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    return seed, Ed25519PrivateKey.from_private_bytes(seed).public_key().public_bytes_raw()


def canonical(payload) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sign(seed: bytes, payload) -> str:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    return _b64(Ed25519PrivateKey.from_private_bytes(seed).sign(canonical(payload)))


def holds(pub_b64: str, payload, signature: str) -> bool:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    try:
        Ed25519PublicKey.from_public_bytes(base64.b64decode(pub_b64, validate=True)).verify(
            base64.b64decode(signature, validate=True), canonical(payload))
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False


def statement(body: dict, signers: dict[str, bytes]) -> dict:
    """A statement and each signer's signature over it: {"statement", "signatures": {who: sig}}."""
    return {"statement": body, "signatures": {k: sign(seed, body) for k, seed in signers.items()}}


def _recovery_from(words: str) -> tuple[bytes, str]:
    try:
        entropy = names.from_words(words)
    except names.NameProblem as exc:
        raise Refused(f"Those recovery words did not work: {exc}.") from None
    seed, pub = _from_seed(names.recovery_seed(entropy))
    return seed, _b64(pub)


# --- talking to rouh.land ----------------------------------------------------------------------------


def _call(url: str, key_pem: str, method: str, rest: str, body: dict | None, *, seed: bytes,
          public: str = "", rouh_id: str = "") -> dict:
    """One signed request to rouh.land's birth service and its signed answer's payload. Signed the
    way the Gene Pool's requests are (`genepool._sign`), with this key; the answer must be signed
    by the registry's pinned key. Refused, in words, for anything else."""
    import httpx

    from . import genelab, genepool

    full, path = genepool._address(url or DEFAULT_URL, rest)
    raw = json.dumps(body, ensure_ascii=False).encode() if body is not None else b""
    headers = {"User-Agent": "Rouh birth", "Accept": "application/json", **genepool._sign(seed, method, path, raw)}
    if rouh_id:
        headers["X-Rouh-Id"] = rouh_id
    if public:
        headers["X-Rouh-Key"] = public
    if body is not None:
        headers["Content-Type"] = "application/json"
    try:
        with httpx.Client(timeout=TIMEOUT, follow_redirects=False) as client:
            r = client.request(method, full, content=raw if body is not None else None, headers=headers)
    except Exception as exc:  # noqa: BLE001 - said, not hidden
        raise Refused(f"rouh.land could not be reached ({type(exc).__name__}).") from None
    if 300 <= r.status_code < 400:
        raise Refused("rouh.land answered with its sign-in page: it does not know this Rouh or this "
                      "code. Its birth service is closed to all but its own staff for now.")
    try:
        doc = r.json()
    except ValueError:
        raise Refused(f"rouh.land answered {r.status_code} with something that is not its signed answer.") from None
    try:
        payload = genelab.verify(doc, genelab.load_key(key_pem or defaults()[1]), KIND)
    except genelab.Refused as exc:
        raise Refused(f"rouh.land's answer was refused: {exc}.") from None
    if payload.get("clash"):
        raise Clash(_cut(payload.get("error") or "That name and tag are taken.", 300))
    if payload.get("error"):
        raise Refused(f"rouh.land said: {_cut(payload['error'], 300)}")
    return payload


def defaults() -> tuple[str, str]:
    """rouh.land's birth service and its pinned key, unless this installation names another
    (`config.birth_url`, `config.birth_key_file`: a test world, or a registry of its own)."""
    from . import genepool
    from .config import config

    key = genepool.DEFAULT_KEY
    if config.birth_key_file:
        try:
            with open(config.birth_key_file, encoding="utf-8") as f:
                key = f.read()
        except OSError:
            log.warning("birth: the key file %s could not be read", config.birth_key_file)
    return (config.birth_url or DEFAULT_URL), key


def _registry(url: str, key_pem: str) -> tuple[str, str]:
    from . import genelab

    d_url, d_key = defaults()
    url = str(url or "").strip() or d_url
    genelab.url_ok(url)
    key_pem = str(key_pem or "").strip() or d_key
    try:
        genelab.load_key(key_pem)
    except genelab.Refused as exc:
        raise Refused(str(exc)) from None
    return url, key_pem


def _check_card(card: dict, row=None) -> dict:
    """rouh.land's card for a Rouh, held to what the name rules say, and, for this Rouh, its own
    birth key. A name rouh.land granted at registration (`granted`, a version 2 birth) is rouh.land's
    to give, so it is taken as its signed answer says it; an older name must be the one its birth
    key gives."""
    birth_key = str(card.get("birth_key") or "")
    if row is not None and row.birth_key and birth_key != row.birth_key:
        raise Refused("rouh.land's card is for another Rouh, so it was refused.")
    if card.get("granted"):
        if not re.fullmatch(r"[A-Za-z][A-Za-z' -]{1,78}", str(card.get("name") or "")) or \
                not re.fullmatch(r"[a-z0-9]{2,8}", str(card.get("tag") or "")):
            raise Refused("rouh.land's card gave this Rouh no name it could keep, so it was refused.")
        return card
    try:
        name = names.derive(birth_key, int(card.get("names_version") or 1))
    except names.NameProblem as exc:
        raise Refused(f"rouh.land's card for this Rouh is not right: {exc}.") from None
    if not names.same_name(card.get("name"), name.words) or card.get("tag") != name.tag:
        raise Refused("rouh.land's card names this Rouh differently from what its birth key gives, so it was refused.")
    if row is not None and row.birth_key and birth_key != row.birth_key:
        raise Refused("rouh.land's card is for another Rouh's birth key, so it was refused.")
    return card


# --- what the page reads ---------------------------------------------------------------------------


def _life_began() -> float | None:
    """The first trace of this Rouh's life before its birth: its first chat or task."""
    M = _m()
    found = [M.Chat.objects.order_by("created_at").values_list("created_at", flat=True).first(),
             M.Task.objects.order_by("created_at").values_list("created_at", flat=True).first()]
    found = [x for x in found if x]
    return min(found) if found else None


def _life(org: str) -> dict:
    """What this Rouh has lived so far, in counts: never a chat's or a task's words."""
    M = _m()
    return {"chats": M.Chat.objects.count(), "tasks": M.Task.objects.count(),
            "genes": M.GeneLogGene.objects.filter(org_id=org, parent_id__isnull=True).count(),
            "runs": M.Run.objects.count()}


def nickname(org: str, user_id: str) -> str:
    n = _m().RouhNickname.objects.filter(org_id=str(org), user_id=str(user_id)).first()
    return n.nickname if n else ""


def _when(at, who) -> str:
    from . import evolution

    return evolution.when_words(at, who) if at else ""


def _days(at) -> int:
    return max(0, int((_now() - at) // 86400)) if at else 0


def _models_offer() -> dict:
    from . import genes
    from .config import config

    return {"anthropic": bool(getattr(config, "anthropic_api_key", "")),
            "openai": bool(getattr(config, "openai_api_key", "")),
            "route": genes.BY_ID["models"]["route"]}


def _pool(org: str) -> dict:
    from . import genepool

    mem = genepool.membership(org)
    return {"joined": bool(mem and mem.status == "member"), "name": mem.name if mem else "",
            "outgoing": genepool.MODE_NAMES[genepool.mode(org)],
            "incoming": genepool.INCOMING_NAMES[genepool.incoming(org)],
            "on": genepool.on(org), "route": "/evolution/pool"}


def _joined_pool(org: str, row) -> None:
    """Registered on rouh.land, so in the Gene Pool, exchanging nothing (`genepool.join_at_birth`)."""
    from . import genepool

    if genepool.join_at_birth(org, now=True) == "joined":
        _event(row, "pool", f"Joined the {genepool.NAME} as {row.name}. Nothing is exchanged: outgoing and "
                            "incoming genes are each Manual until you choose otherwise.")


def _in_account(row) -> bool:
    """Whether its registration on rouh.land is in its owner's account there: born there with a code,
    or registered or linked with one later (its own history, as `be_born` and `connect` write it)."""
    for h in row.history or []:
        said = str(h.get("said") or "")
        # ", on rouh.it" as a birth said it before the move to rouh.land (task 165).
        if h.get("what") == "born" and (", on rouh.land" in said or ", on rouh.it" in said) and "no account" not in said:
            return True
        if h.get("what") == "connected" and "no account" not in said:
            return True
    return False


def _sign_in_email(who) -> str:
    from . import signin

    return signin.primary(_m().User.objects.filter(pk=who.user_id).first())


def disconnected(row) -> float | None:
    """When this Rouh was last disconnected from rouh.land and has not been connected since, or None."""
    if row is None or row.registry_id:
        return None
    for h in reversed(row.history or []):
        if h.get("what") == "disconnected":
            return h.get("at") or 0.0
        if h.get("what") in ("born", "connected"):
            return None
    return None


def _owner_of(org: str) -> dict:
    """Who owns this Rouh: its organisation's first administrator, as their name says it (7 November
    2026, 141-17: "Owner, shown apart, never part of its name, never sent"). Only ever shown to the
    organisation's own people."""
    from . import owner

    first = (_m().User.objects.filter(org_id=org, is_active=True, is_guest=False, is_org_admin=True)
             .order_by("id").first())
    if first is None:
        return {"name": "", "user_id": ""}
    found = owner.of(str(first.pk))
    name = (found.full_name or found.name) if found is not None else ""
    return {"name": name or first.get_full_name() or first.username, "user_id": str(first.pk)}


def standing(row) -> dict:
    """This Rouh and rouh.land in one plain sentence, as {kind, said}: never a key.

    kind: "free" (never registered: no name, no keys), "registered", "not-registered" (born on its
    own before 4 November 2026, not registered since), "stopped" (rouh.land no longer accepts it),
    "waiting" (something asked on rouh.land waits)."""
    if row is None:
        return {"kind": "free", "said": f"{INDEPENDENT}. It works fine without rouh.land; connecting it gives "
                                        "it its birth and its own name."}
    card = row.card if isinstance(row.card, dict) else {}
    if row.registry_id and row.key_dead_at:
        return {"kind": "stopped", "said": "rouh.land doesn't recognise this Rouh any more. It keeps working here; "
                                           "the Gene Pool and its URL wait until rouh.land does again."}
    if row.registry_id:
        if card.get("warnings"):
            return {"kind": "waiting", "said": str(card["warnings"][0])}
        return {"kind": "registered", "said": "Born and registered with rouh.land."}
    return {"kind": "not-registered", "said": "Not registered with rouh.land (it works fine without)."}


def page(who) -> dict:
    """Everything Anatomy, Rouh Land Account, Rouh profile draws, for this person."""
    org = str(who.org_id)
    row = current(org)
    mine = nickname(org, who.user_id)
    out = {"name": NAME, "admin": bool(getattr(who, "is_admin", False)), "born": row is not None,
           "nickname": mine, "human_names": human_names(org, who.user_id), "models": _models_offer(), "pool": _pool(org),
           "defaults": {"url": defaults()[0]}, "second_name_days": SECOND_NAME_DAYS,
           # The email rouh.land's sign-up and sign-in open with, from Connect: the one that signs the
           # owner in here, so one email runs both (4 November 2026). It may be changed there.
           "connect_email": _sign_in_email(who), "standing": standing(row), "independent": INDEPENDENT,
           "independent_word": INDEPENDENT_WORD}
    own = _owner_of(org)
    out["owner"] = {"name": own["name"], "you": own["user_id"] == str(who.user_id)}
    rec = _recovering(org)
    if rec is not None:
        p = rec.pending or {}
        out["recovering"] = {"request": p.get("request", ""), "due_words": _when(p.get("due_at"), who),
                             "url": p.get("url", ""), "since_words": _when(p.get("since"), who),
                             "said": p.get("said", "")}
    if row is None:
        return out
    p = row.pending or {}
    out["rouh"] = {
        "name": row.name, "tag": row.tag, "born_words": _when(row.born_at, who), "born_at": row.born_at,
        "days": _days(row.born_at), "retro": row.retro,
        "life_began_words": _when(row.life_began_at, who) if row.retro else "",
        "days_alive": _days(row.life_began_at or row.born_at),
        # No key, key id, registry id or recovery words: they are this Rouh's business (the top of
        # this file). The person reads `standing`.
        "connected": bool(row.registry_id), "registry_url": row.registry_url,
        # Named by rouh.land at its birth (since 4 November 2026), or, born here before, by its key.
        "named_by_land": bool(((row.card or {}).get("payload") or {}).get("granted")) if isinstance(row.card, dict) else False,
        "account": in_account(row),
        "account_email": account_email(row),
        "connected_words": _when(row.connected_at, who), "checked_words": _when(row.checked_at, who),
        "key_dead_words": _when(row.key_dead_at, who) if row.key_dead_at else "",
        "disconnected_words": _when(disconnected(row), who) if disconnected(row) is not None else "",
        "pending": ({"request": p.get("request", ""), "due_words": _when(p.get("due_at"), who),
                     "said": p.get("said", "")} if p.get("public") else None),
        "warnings": list((row.card or {}).get("warnings") or []) if isinstance(row.card, dict) else [],
        "second_name": row.second_name, "second_name_why": row.second_name_why,
        "second_name_words": _when(row.second_name_at, who),
        "second_name_due_words": _when(row.born_at + SECOND_NAME_DAYS * 86400, who),
        "second_name_model": row.second_name_model,
        "second_name_tries": [{"when": _when(t.get("at"), who), "said": t.get("said", ""),
                               "cost_usd": t.get("cost_usd") if t.get("cost_usd") is not None
                               else _cost_since(org, (t.get("at") or 0) - 300, until=t.get("at"))}
                              for t in (row.second_name_tries or [])][-5:],
        "history": [{"when": _when(h.get("at"), who), "what": h.get("what", ""), "said": h.get("said", "")}
                    for h in reversed(row.history or [])][:40],
        "error": row.error,
    }
    out["life"] = _life(org)
    return out


# --- birth ----------------------------------------------------------------------------------------


def _signers_for_birth():
    seed, pub = new_key()
    entropy = names.new_entropy()
    rseed, rpub = _from_seed(names.recovery_seed(entropy))
    return seed, pub, entropy, rseed, rpub


def be_born(who, *, code: str = "", url: str = "", key_pem: str = "") -> dict:
    """Connect a free Rouh to rouh.land, which is its birth: its keys are made now, its birth (which
    names nothing) goes to rouh.land, and rouh.land grants its official name in its signed card.
    With a code from the owner's rouh.land account it is born into that account; with none,
    Connected with no account yet. If rouh.land cannot be reached or refuses, nothing is kept: it
    stays a free Rouh, with no keys and no name."""
    _admin(who)
    org = str(who.org_id)
    if current(org) is not None:
        raise Refused(f"This Rouh is already born, as {current(org).name}.")
    code = str(code or "").strip()
    url, key_pem = _registry(url, key_pem)
    now = _now()
    seed, pub, entropy, rseed, rpub = _signers_for_birth()
    body = {"kind": "rouh-birth", "v": 2, "birth_key": _b64(pub), "recovery_key": _b64(rpub), "born_at": _iso(now)}
    birth = statement(body, {"birth": seed, "recovery": rseed})
    ask = {"birth": birth, **({"code": code} if code else {})}
    got = _call(url, key_pem, "POST", "api/born", ask, seed=seed, public=_b64(pub))
    card = _check_card(got.get("card") or {})
    if card.get("birth_key") != _b64(pub) or not card.get("granted"):
        raise Refused("rouh.land answered for another birth than this one, so it stays a free Rouh.")
    began = _life_began()
    retro = bool(began and began < now - 86400)
    row = _m().RouhBirth.objects.create(
        org_id=org, state="born", name=card["name"], tag=card["tag"], names_version=int(card.get("names_version") or 1),
        born_at=now, life_began_at=began if retro else None, retro=retro, birth_key=_b64(pub), birth_statement=birth,
        daily_public=_b64(pub), daily_private=_box().seal(_b64(seed)), daily_since=now,
        recovery_public=_b64(rpub), recovery_words=_box().seal(" ".join(names.to_words(entropy))),
        registry_url=url, registry_key=key_pem, registry_id=str(got.get("rouh") or ""), connected_at=now,
        card={"payload": card}, checked_at=now, updated_at=now)
    said = f"Born on rouh.land as {row.name}" + ("" if code else ", Connected with no account yet")
    if retro:
        said += f", after living since {_iso(began)[:10]}: its history is its own"
    _event(row, "born", said + ".")
    _joined_pool(org, row)
    if code:
        # Born into an account: its owner signs in here with that account's email from now on
        # (`check`, `signin.follow_land`), the address before kept until the new one is used.
        try:
            check(org, force=True)
        except Exception as exc:  # noqa: BLE001 - the birth stands; the next check follows
            log.warning("birth: the first check after birth failed: %s", type(exc).__name__)
    return {"ok": True, "said": f"Born on rouh.land: its name is {row.name}."}


def reveal(who) -> dict:
    """The recovery words, once. They are deleted from this server as they are handed over."""
    import segno

    _admin(who)
    row = current(str(who.org_id))
    if row is None:
        raise Refused("This Rouh is not born yet.")
    if not row.recovery_words:
        raise Refused("The recovery words were shown once already and are no longer on this server. "
                      "If they were not kept, replace the keys while you still can (Replace with the words "
                      "needs them; on rouh.land, sign in and ask for a new key).")
    words = _box().open_(row.recovery_words).split()
    n = _m().RouhBirth.objects.filter(id=row.id).exclude(recovery_words="").update(
        recovery_words="", recovery_shown_at=_now(), updated_at=_now())
    if not n:
        raise Refused("The recovery words were just shown on another page, and are gone from this server.")
    _event(row, "words", "The recovery words were shown, once, and deleted from this server.")
    phrase = " ".join(words)
    buf = io.BytesIO()
    # With its namespace, so the page can parse it as a picture rather than as plain markup.
    segno.make(phrase, error="m").save(buf, kind="svg", xmldecl=False, svgns=True, nl=False, scale=5, border=2,
                                       dark="#111", light="#fff")
    qr = buf.getvalue().decode()
    label = f"{row.name} ·{row.tag}"
    text = (f"Recovery words for {label}, a Rouh\n\n"
            + "\n".join(f"{i:>2}. {w}" for i, w in enumerate(words, 1))
            + "\n\nThese twelve words are the only way to give this Rouh a new key if its own is lost or "
              "stolen. Keep them in a password manager or on paper, never in a box of the Rouh itself.\n")
    csv = ("title,username,password,notes\n"
           f"\"Rouh {label}: recovery words\",\"{row.name}\",\"{phrase}\","
           f"\"Born {_iso(row.born_at)[:10]}. Only for giving this Rouh a new key.\"\n")
    return {"ok": True, "words": words, "qr": qr, "label": label, "text": text, "csv": csv,
            "file": re.sub(r"[^a-z0-9]+", "-", row.name.lower()).strip("-") + "-recovery-words"}


def check_words(who, words: str) -> dict:
    """Whether these are this Rouh's recovery words. Nothing typed is kept."""
    _admin(who)
    row = current(str(who.org_id))
    if row is None:
        raise Refused("This Rouh is not born yet.")
    _seed, pub = _recovery_from(words)
    if pub != row.recovery_public:
        raise Refused("Those are real recovery words, but not this Rouh's.")
    _m().RouhBirth.objects.filter(id=row.id).update(recovery_checked_at=_now(), updated_at=_now())
    _event(row, "words", "The recovery words were typed back, and they are right.")
    return {"ok": True, "said": f"Those are {row.name}'s recovery words. Keep them where they are."}


def human_names(org: str, user_id: str) -> dict:
    """The first, last and nickname this person gave their Rouh, each "" when none."""
    n = _m().RouhNickname.objects.filter(org_id=str(org), user_id=str(user_id)).first()
    return {"first": n.first_name if n else "", "last": n.last_name if n else "",
            "nickname": n.nickname if n else ""}


#: What every Rouh answers to already (Petar, 4 November 2026): a nickname is given on top of it,
#: never in place of it, so a nickname that only says it again is no nickname. Its own name, not
#: `KIND`: that one is the kind every signed answer from rouh.land must say it is (`_call`), and a
#: second `KIND` here replaced it, so every answer from rouh.land was refused.
EVERY_ROUH = "Rouh"

#: What a Rouh that is not connected to rouh.land is called, on every screen that names that kind
#: (Petar, 8 November 2026, task 176: "free" was confusing, since the rouh.land account is free
#: too). The one place to change it: the first run, Anatomy, the phone page and the Gene Pool read
#: it from here. "Free" may still say what Connected costs; it never names this kind.
INDEPENDENT_WORD = "Independent"
INDEPENDENT = f"{INDEPENDENT_WORD} Rouh"


def plain_nickname(text: str) -> str:
    """A nickname as it is kept: "" for "Rouh" itself, which every Rouh answers to anyway."""
    text = _cut(" ".join(str(text or "").split()), 40)
    return "" if text.strip(" .!,'\"\u201c\u201d").casefold() == EVERY_ROUH.casefold() else text


def heard_names(org: str, user_id: str) -> list[str]:
    """The names this Rouh answers to when this person speaks: "Rouh", its own name once it is
    born, and the nickname and first name this person gave it. Never raises."""
    out = [EVERY_ROUH]
    try:
        row = current(str(org))
        if row is not None and row.name:
            out.append(row.name)
        mine = human_names(str(org), str(user_id))
        out += [mine["nickname"], mine["first"]]
    except Exception:  # noqa: BLE001 - "Rouh" is still heard
        log.exception("birth: the names this Rouh answers to could not be read")
    return [n for n in dict.fromkeys(n.strip() for n in out) if n]


def set_human_names(who, *, first: str = "", last: str = "", nickname: str = "") -> dict:
    """The human names this person gives their Rouh: a first, a last and a nickname, each
    optional and each changed any time, shown to them only. Its own name never changes.
    All three empty takes them away. "Rouh" as the nickname is kept as none: it answers to
    Rouh anyway."""
    org, user = str(who.org_id), str(who.user_id)
    said = {k: _cut(" ".join(str(v or "").split()), 40) for k, v in
            (("first", first), ("last", last), ("nickname", nickname))}
    only_kind = bool(said["nickname"]) and not plain_nickname(said["nickname"])
    said["nickname"] = plain_nickname(said["nickname"])
    no_need = " No need to write Rouh as a nickname: it always answers to Rouh." if only_kind else ""
    N = _m().RouhNickname
    if not any(said.values()):
        N.objects.filter(org_id=org, user_id=user).delete()
        return {"ok": True, "said": ("No human names: you see its own name." + no_need).strip()}
    if any(re.search(r"[<>{}\\]", v) for v in said.values()):
        raise Refused("A name is words, without <, >, { or }.")
    N.objects.update_or_create(org_id=org, user_id=user, defaults={
        "first_name": said["first"], "last_name": said["last"], "nickname": said["nickname"],
        "updated_at": _now()})
    row = current(org)
    shown = said["nickname"] or " ".join(filter(None, (said["first"], said["last"])))
    return {"ok": True, "said": f"You call it {shown}. Only you see that"
                                + (f"; everyone else sees {row.name}." if row else ".") + no_need}


def set_nickname(who, text: str) -> dict:
    """What this person calls their Rouh, shown to them only. Empty takes it away."""
    org, user = str(who.org_id), str(who.user_id)
    text = plain_nickname(text)
    N = _m().RouhNickname
    if not text:
        N.objects.filter(org_id=org, user_id=user, first_name="", last_name="").delete()
        N.objects.filter(org_id=org, user_id=user).update(nickname="", updated_at=_now())
        return {"ok": True, "said": "No nickname: you see its own name."}
    if re.search(r"[<>{}\\]", text):
        raise Refused("A nickname is words, without <, >, { or }.")
    N.objects.update_or_create(org_id=org, user_id=user, defaults={"nickname": text, "updated_at": _now()})
    row = current(org)
    return {"ok": True, "said": f"You call it {text}. Only you see that"
                                + (f"; everyone else sees {row.name}." if row else ".")}


# --- rouh.land ---------------------------------------------------------------------------------------


def _seed_of(row) -> bytes:
    return base64.b64decode(_box().open_(row.daily_private))


def connect(who, *, code: str = "", url: str = "", key_pem: str = "") -> dict:
    """An independent Rouh registered on rouh.land later, with a code from its owner's account
    there: its birth as signed then, and every key change since, so rouh.land can follow its keys.
    Its name is the one it has; a clash leaves it independent, never renamed.

    With no code, it is registered Connected with no account (the first run's Connected, Petar,
    28 October 2026: "with no install code and no account step for the person"), so the relay
    gives it its phone address; a code later puts it in an account (rouh.land's `api/born`)."""
    _admin(who)
    row = current(str(who.org_id))
    if row is None:
        # A free Rouh connecting is its birth: rouh.land gives it its name now.
        return be_born(who, code=code, url=url, key_pem=key_pem)
    code = str(code or "").strip()
    if row.registry_id and not code:
        return {"ok": True, "said": f"{row.name} is registered on rouh.land already."}
    # Registered already and a code: rouh.land puts a Rouh registered with no account into the code's
    # account, and refuses one already in an account, in words.
    url, key_pem = _registry(url, key_pem)
    body = {"birth": row.birth_statement, "changes": row.key_changes or []}
    if code:
        body["code"] = code
    try:
        got = _call(url, key_pem, "POST", "api/born", body, seed=_seed_of(row), public=row.daily_public)
    except Clash as exc:
        raise Refused(f"{exc} A name never changes, so {row.name} stays independent.") from None
    card = _check_card(got.get("card") or {}, row)
    now = _now()
    _m().RouhBirth.objects.filter(id=row.id).update(
        registry_url=url, registry_key=key_pem, registry_id=str(got.get("rouh") or ""), connected_at=now,
        card={"payload": card}, checked_at=now, error="", updated_at=now)
    _event(row, "connected", f"Registered on rouh.land as {row.name}" + ("." if code else ", Connected with no account yet."))
    _joined_pool(str(who.org_id), row)
    said = f"{row.name} is registered on rouh.land now, under the name it has."
    if code:
        # Ask at once which account it is in, so the owner's sign-in follows that account's email now
        # rather than at the next check (`check`, `signin.follow_land`).
        got = check(str(who.org_id), force=True)
        if got.get("followed"):
            said += " You sign in here with your rouh.land email now."
    return {"ok": True, "said": said}


def check(org: str, *, force: bool = False) -> dict:
    """Ask rouh.land how this Rouh's keys stand: alive, dead since a moment (revoked there), and
    any new key asked for on the owner's account, which this key is told of before it happens."""
    row = current(org)
    if row is None or not row.registry_id:
        return {"checked": False}
    if not force and row.checked_at and _now() - row.checked_at < CHECK_EVERY:
        return {"checked": False}
    try:
        got = _call(row.registry_url, row.registry_key, "GET", "api/status", None, seed=_seed_of(row),
                    public=row.daily_public, rouh_id=row.registry_id)
    except Refused as exc:
        _m().RouhBirth.objects.filter(id=row.id).update(error=_cut(exc, 400), checked_at=_now(), updated_at=_now())
        return {"checked": True, "error": str(exc)}
    warnings = []
    for req in got.get("requests") or []:
        warnings.append(f"Something was asked about this Rouh on your rouh.land account, {str(req.get('requested_at') or '')[:10]}. "
                        f"It happens on {str(req.get('due_at') or '')[:10]} unless you cancel it there.")
    dead = _from_iso(got.get("dead_at")) if got.get("key") == "dead" else None
    card = got.get("card") or {}
    try:
        _check_card(card, row)
    except Refused as exc:
        warnings.append(str(exc))
        card = (row.card or {}).get("payload") or {}
    # The account this Rouh is in, as rouh.land says it in its signed answer (since 4 November
    # 2026): its email and whether it is an administrator's. Kept beside the card, and the owner's
    # sign-in here follows the email (`signin.follow_land`): one email runs both.
    account = _account_of(got)
    if account:
        card = {**card, "account": account}
    _m().RouhBirth.objects.filter(id=row.id).update(
        card={"payload": card, "warnings": warnings}, checked_at=_now(), key_dead_at=dead, error="", updated_at=_now())
    if dead and not row.key_dead_at:
        _event(row, "revoked", "rouh.land no longer recognises this Rouh (stopped there).")
    followed = False
    if account.get("email") and not dead:
        from . import signin

        followed = signin.follow_land(org, account["email"])
        if followed:
            _event(row, "email", f"Your sign-in to this Rouh follows your rouh.land account now: {account['email']}.")
    return {"checked": True, "dead": bool(dead), "warnings": warnings, "followed": followed}


def _account_of(got: dict) -> dict:
    """{email, admin} of the rouh.land account, from a signed status answer; {} when it says none."""
    account = got.get("account")
    if not isinstance(account, dict):
        return {}
    email = str(account.get("email") or "").strip().lower()[:254]
    if "@" not in email:
        return {}
    admin = bool(account.get("admin"))
    return {"email": email, "admin": admin, "role": "Administrator" if admin else "Owner"}


def account_email(row) -> str:
    """The rouh.land account's email, as rouh.land last said it, or ""."""
    payload = (row.card or {}).get("payload") if row is not None and isinstance(row.card, dict) else None
    account = payload.get("account") if isinstance(payload, dict) else None
    return str(account.get("email") or "") if isinstance(account, dict) else ""


def in_account(row) -> bool:
    """Whether this Rouh is registered on rouh.land in somebody's account there."""
    return bool(row is not None and row.registry_id) and (_in_account(row) or bool(account_email(row)))


def ask_account(org: str, email: str) -> dict:
    """Ask rouh.land to email this Connected Rouh's owner a link that confirms their email, makes
    their rouh.land account if there is none, and puts this Rouh in it (Petar, 8 November 2026,
    task 176, step 176-16: "you are either connected and you can use the Gene Pool, or you are
    disconnected and you have no access to benefits"). Before this a Connected first run registered
    the Rouh with no account, and the email typed in the setup never reached rouh.land, so Sign in
    there said there was no account. Raises Refused, in words, when it did not go."""
    row = current(org)
    if row is None or not row.registry_id:
        raise Refused("This Rouh is not connected to rouh.land.")
    if in_account(row):
        return {"ok": True, "in_account": True, "said": "This Rouh is in your rouh.land account already."}
    email = str(email or "").strip().lower()[:254]
    if "@" not in email:
        raise Refused("There is no email to send the link to.")
    try:
        got = _call(row.registry_url, row.registry_key, "POST", "api/account", {"email": email},
                    seed=_seed_of(row), public=row.daily_public, rouh_id=row.registry_id)
    except Refused as exc:
        if "in an account already" in str(exc):
            check(org, force=True)
            return {"ok": True, "in_account": True, "said": "This Rouh is in a rouh.land account already."}
        raise
    _event(row, "account-asked", f"rouh.land emailed {email} a link to confirm it and make the rouh.land account.")
    days = int(got.get("days") or 3)
    return {"ok": True, "email": email, "said": f"rouh.land emailed {email} a link. Press it to confirm your email: "
                                              f"that makes your rouh.land account. It works for {days} days."}


def account_asked(row) -> str:
    """The email rouh.land was last asked to confirm for this Rouh's account, while it is in none."""
    if row is None or not row.registry_id or in_account(row):
        return ""
    for h in reversed(row.history or []):
        if h.get("what") == "account-asked":
            m = re.search(r"emailed (\S+@\S+) a link", str(h.get("said") or ""))
            return m.group(1) if m else ""
        if h.get("what") in ("born", "connected", "disconnected"):
            return ""
    return ""


def sign_in_letter(org: str, to: str, link: str, code: str) -> None:
    """Ask rouh.land to send one sign-in letter for this Rouh, from noreply@rouh.land (`signin.send`).
    rouh.land sends only sign-in letters, only for a Rouh in an account, and keeps its own limits.
    Raises Refused when it does not go."""
    row = current(org)
    if row is None or not row.registry_id:
        raise Refused("This Rouh is not connected to rouh.land.")
    _call(row.registry_url, row.registry_key, "POST", "api/sign-in-letter",
          {"to": to, "link": link, "code": code}, seed=_seed_of(row), public=row.daily_public,
          rouh_id=row.registry_id)


def disconnect(who) -> dict:
    """Stop being connected to rouh.land. Its owner keeps signing in here with the email they have,
    which is proven already; Gene Pool sharing stops; the account on rouh.land stays until it is
    deleted there. Connecting again later is Rouh profile's Connect, as before."""
    _admin(who)
    org = str(who.org_id)
    row = current(org)
    if row is None or not row.registry_id:
        return {"ok": True, "said": "This Rouh is not connected to rouh.land."}
    now = _now()
    payload = (row.card or {}).get("payload") if isinstance(row.card, dict) else {}
    payload = {k: v for k, v in (payload or {}).items() if k != "account"}
    _m().RouhBirth.objects.filter(id=row.id).update(registry_id="", connected_at=None, error="",
                                                    card={"payload": payload}, updated_at=now)
    _m().PoolMembership.objects.filter(org_id=org, status="member").update(status="left", updated_at=now)
    from . import signin

    email = signin.primary(_m().User.objects.filter(pk=who.user_id).first())
    _event(row, "disconnected", "Disconnected from rouh.land. Gene Pool sharing stopped. "
                                f"You still sign in here with {email or 'your email'}; your rouh.land account stays "
                                "until you delete it there.")
    return {"ok": True, "said": f"{row.name} is not connected to rouh.land now. Gene Pool sharing has stopped. "
                                f"You still sign in here with {email or 'your email'}, and your rouh.land account "
                                "stays until you delete it there."}


# --- a new key -------------------------------------------------------------------------------------


def _follow_pool(org: str, old_pub: str, new_pub: str) -> None:
    """The Gene Pool membership speaks with the birth's daily key: it follows the new one."""
    _m().PoolMembership.objects.filter(org_id=org, public_key=old_pub, private_key="").update(
        public_key=new_pub, updated_at=_now())


def rotate(who, words: str, *, stolen: bool = False, since: str = "") -> dict:
    """A new daily key, signed for by the recovery key: "my new daily key is this one". Stolen
    says the old key was taken: rouh.land marks it dead at once, and genes it sent after `since`
    (a day, YYYY-MM-DD) go back to review in the Pool. The name stays."""
    _admin(who)
    org = str(who.org_id)
    row = current(org)
    if row is None:
        raise Refused("This Rouh is not born yet.")
    rseed, rpub = _recovery_from(words)
    if rpub != row.recovery_public:
        raise Refused("Those are real recovery words, but not this Rouh's: nothing was changed.")
    now = _now()
    since_at = None
    if stolen:
        since_at = _from_iso(since) if since else None
        if since and since_at is None:
            raise Refused("Since when is a day, like 2026-10-01.")
        since_at = since_at or max(row.daily_since, now - SINCE_DEFAULT_DAYS * 86400)
        since_at = min(since_at, now)
    seed, pub = new_key()
    body = {"kind": "rouh-key-change", "v": 1, "birth_key": row.birth_key, "name": row.name, "tag": row.tag,
            "old_key": row.daily_public, "new_key": _b64(pub), "reason": "stolen" if stolen else "replaced",
            "compromised_since": _iso(since_at) if since_at else "", "at": _iso(now)}
    change = statement(body, {"recovery": rseed, "new": seed})
    reviewed = 0
    if row.registry_id:
        got = _call(row.registry_url, row.registry_key, "POST", "api/keys/change",
                    {"rouh": row.registry_id, "change": change}, seed=seed, public=_b64(pub))
        reviewed = int(got.get("back_to_review") or 0)
    old = row.daily_public
    changes = list(row.key_changes or []) + [change]
    _m().RouhBirth.objects.filter(id=row.id).update(
        daily_public=_b64(pub), daily_private=_box().seal(_b64(seed)), daily_since=now, key_changes=changes,
        key_dead_at=None, recovery_checked_at=now, pending={}, error="", updated_at=now)
    _follow_pool(org, old, _b64(pub))
    if stolen:
        said = (f"The old daily key ({_key_id(old)}) is marked stolen and dead from now; a new key "
                f"({_key_id(_b64(pub))}) speaks for {row.name}.")
        if row.registry_id:
            said += (f" On rouh.land, {reviewed} gene{'s' if reviewed != 1 else ''} it sent since "
                     f"{_iso(since_at)[:10]} went back to review.")
    else:
        said = f"A new daily key ({_key_id(_b64(pub))}) speaks for {row.name}; the old one is retired."
    _event(row, "stolen" if stolen else "replaced", said)
    return {"ok": True, "said": said}


def recover_start(who, *, back: str, url: str = "", key_pem: str = "") -> dict:
    """Account recovery, this Rouh's half: a new daily key and new recovery words made here and
    kept waiting, and the address on rouh.land where the owner, signed in by email link or passkey, asks
    for them to be bound to their Rouh. rouh.land waits seven days and tells the old key, and shows
    it on the owner's account, meanwhile; `recover_check` reads how it stands."""
    from urllib.parse import urlencode

    _admin(who)
    org = str(who.org_id)
    url, key_pem = _registry(url, key_pem)
    seed, pub = new_key()
    entropy = names.new_entropy()
    _rseed, rpub = _from_seed(names.recovery_seed(entropy))
    at = _iso(_now())
    proof = sign(seed, {"kind": "rouh-recover", "v": 1, "new_key": _b64(pub), "recovery_key": _b64(rpub), "at": at})
    pending = {"public": _b64(pub), "private": _box().seal(_b64(seed)), "recovery_public": _b64(rpub),
               "words": _box().seal(" ".join(names.to_words(entropy))), "url": url, "key": key_pem,
               "since": _now(), "request": "", "said": "Waiting for you to ask on rouh.land."}
    row = current(org)
    M = _m().RouhBirth
    if row is not None:
        M.objects.filter(id=row.id).update(pending=pending, updated_at=_now())
        _event(row, "recovering", "A new key was made here, waiting to be asked for on rouh.land.")
    else:
        rec = _recovering(org)
        if rec is not None:
            M.objects.filter(id=rec.id).update(pending=pending, updated_at=_now())
        else:
            M.objects.create(org_id=org, state="recovering", name="", tag="", born_at=_now(), birth_key="",
                             daily_public="", daily_private="", daily_since=_now(), recovery_public="",
                             pending=pending, updated_at=_now())
    go = url.rstrip("/") + "/recover/?" + urlencode({"key": _b64(pub), "recovery": _b64(rpub), "at": at,
                                                     "proof": proof, "back": back})
    return {"ok": True, "go": go, "said": "Sign in on rouh.land, by email link or passkey, and pick this Rouh."}


def recover_started(who, request_id: str) -> dict:
    """rouh.land sent the person back with the id of the request they made."""
    _admin(who)
    org = str(who.org_id)
    row = current(org) or _recovering(org)
    rid = _cut(request_id, 40)
    if row is None or not (row.pending or {}).get("public") or not re.fullmatch(r"[0-9a-f]{8,40}", rid):
        raise Refused("There is no new key waiting here for that request.")
    pending = dict(row.pending)
    pending.update({"request": rid, "said": "Asked for on rouh.land: bound after seven days, unless cancelled."})
    _m().RouhBirth.objects.filter(id=row.id).update(pending=pending, updated_at=_now())
    out = recover_check(org)
    return {"ok": True, "said": out.get("said") or pending["said"]}


def recover_check(org: str) -> dict:
    """How the account recovery stands on rouh.land, asked with the waiting key; once bound, the new
    key and the new recovery words take over, under the same name, history and genes."""
    row = current(org) or _recovering(org)
    pending = dict((row.pending or {}) if row else {})
    if row is None or not pending.get("request"):
        return {}
    seed = base64.b64decode(_box().open_(pending["private"]))
    got = _call(pending["url"], pending["key"], "GET", f"api/recovery/{pending['request']}", None,
                seed=seed, public=pending["public"])
    state = got.get("state")
    M = _m().RouhBirth
    if state == "pending":
        pending.update({"due_at": _from_iso(got.get("due_at")),
                        "said": f"Waiting on rouh.land until {str(got.get('due_at') or '')[:16].replace('T', ' ')} UTC."})
        M.objects.filter(id=row.id).update(pending=pending, updated_at=_now())
        return {"state": state, "said": pending["said"]}
    if state == "cancelled":
        M.objects.filter(id=row.id).update(pending={}, updated_at=_now())
        if row.state == "recovering":
            M.objects.filter(id=row.id).delete()
        return {"state": state, "said": "The request was cancelled on rouh.land: nothing changed."}
    if state != "bound":
        return {"state": state or "", "said": "rouh.land said nothing this Rouh understands about the request."}
    card = _check_card(got.get("card") or {}, row if row.state == "born" else None)
    if card.get("daily_key") != pending["public"]:
        raise Refused("rouh.land bound another key than the one waiting here, so it was refused.")
    now = _now()
    fields = dict(daily_public=pending["public"], daily_private=pending["private"], daily_since=now,
                  recovery_public=pending["recovery_public"], recovery_words=pending["words"],
                  recovery_shown_at=None, recovery_checked_at=None, key_dead_at=None, pending={},
                  card={"payload": card}, checked_at=now, error="", updated_at=now)
    if row.state == "recovering":
        if current(org) is not None:
            raise Refused("This Rouh was born again here meanwhile; the recovered identity was not put over it.")
        began = _from_iso(card.get("born_at")) or now
        fields.update(state="born", name=card["name"], tag=card["tag"], names_version=int(card.get("names_version") or 1),
                      born_at=began, birth_key=card["birth_key"], birth_statement=card.get("birth") or {},
                      key_changes=card.get("changes") or [], registry_url=pending["url"], registry_key=pending["key"],
                      registry_id=str(got.get("rouh") or card.get("rouh") or ""), connected_at=now)
    old = row.daily_public
    M.objects.filter(id=row.id).update(**fields)
    row = M.objects.get(id=row.id)
    if old:
        _follow_pool(org, old, row.daily_public)
    said = (f"rouh.land bound a new key to {row.name}: same name, history and genes. New recovery words "
            "are ready to be shown once.")
    _event(row, "recovered", said)
    return {"state": "bound", "said": said}


def end(who, typed_name: str) -> dict:
    """Both keys are lost: this identity ends, kept in the history, and the next birth is a new
    Rouh with a new name. Typing the name says it is meant."""
    _admin(who)
    org = str(who.org_id)
    row = current(org)
    if row is None:
        raise Refused("This Rouh is not born yet.")
    if not names.same_name(typed_name, row.name):
        raise Refused(f"Type its name, {row.name}, to end this identity.")
    _event(row, "ended", f"{row.name}'s identity ended here: both keys were lost.")
    _m().RouhBirth.objects.filter(id=row.id).update(state="ended", daily_private="", recovery_words="",
                                                     pending={}, updated_at=_now())
    _m().PoolMembership.objects.filter(org_id=org, public_key=row.daily_public, private_key="").update(
        status="left", catalogue={}, matches={}, updated_at=_now())
    # What people called it was theirs for this Rouh; the next one is somebody new.
    _m().RouhNickname.objects.filter(org_id=org).delete()
    return {"ok": True, "said": f"{row.name}'s identity ended. A new birth gives a new Rouh a new name."}


# --- for the Gene Pool ----------------------------------------------------------------------------


def identity(org: str) -> dict | None:
    """This Rouh's name, its daily key and its rouh.land id, for the Gene Pool (`genepool._join`)."""
    row = current(org)
    if row is None:
        return None
    return {"name": row.name, "tag": row.tag, "public": row.daily_public, "seed": _seed_of(row),
            "registry_id": row.registry_id, "registry_url": row.registry_url, "registry_key": row.registry_key,
            "dead": bool(row.key_dead_at)}


def seed_for(org: str, public_b64: str) -> bytes | None:
    """The daily key's private half, when this public key is the birth's daily key."""
    row = current(org)
    if row is None or row.daily_public != public_b64 or not row.daily_private:
        return None
    return _seed_of(row)


# --- the second name ------------------------------------------------------------------------------

SECOND_NAME_SYSTEM = (
    "You are a Rouh, a personal AI assistant, giving yourself a second name. Your first name was "
    "worked out from your birth key: a quality and a thing of nature. Your second name is earned: "
    "read the facts of your own history below and give yourself one name, of one to three words, "
    "that says something true about what you have become. It is yours; your owner sees it but does "
    "not choose it. It must not contain your owner's name or any person's name, any brand, any "
    "slur, any sacred or religious word, and must not imitate any people's naming tradition: no "
    "feathers, chiefs, spirits, totems or tribes. Answer with JSON only: "
    '{"name": "...", "why": "one short sentence, true to the facts"}')
FORBIDDEN = re.compile(r"\b(chief|spirit|totem|tribe|tribal|feather|squaw|brave heart|warrior|shaman|"
                       r"sacred|holy|god|goddess|angel|demon|messiah|prophet)\b", re.I)


def _history_facts(row) -> str:
    """What the second name is read from: counts and the names of genes, never anybody's words."""
    from collections import Counter

    M = _m()
    org = row.org_id
    genes = list(M.GeneLogGene.objects.filter(org_id=org, parent_id__isnull=True).order_by("made_at")
                 .values_list("name", "made_at", "status"))
    use = Counter()
    for gene, n in M.GeneUseDaily.objects.filter(org_id=org).values_list("gene_key", "uses"):
        use[gene] += int(n or 0)
    names_by_key = dict(M.GeneLogGene.objects.filter(org_id=org, parent_id__isnull=True).values_list("key", "name"))
    top = [names_by_key.get(k, k) for k, _ in use.most_common(8)]
    life = _life(org)
    lines = [f"First name: {row.name}.", f"Born {_iso(row.born_at)[:10]}, {_days(row.born_at)} days ago."]
    if row.retro and row.life_began_at:
        lines.append(f"Already running since {_iso(row.life_began_at)[:10]} before its birth.")
    lines.append(f"Chats: {life['chats']}. Tasks: {life['tasks']}. Runs of work: {life['runs']}. Genes: {life['genes']}.")
    if genes:
        lines.append("First genes: " + ", ".join(g[0] for g in genes[:6]) + ".")
        lines.append("Newest genes: " + ", ".join(g[0] for g in genes[-6:]) + ".")
    if top:
        lines.append("Most used genes: " + ", ".join(top) + ".")
    lines.append(f"Key changes: {len(row.key_changes or [])}. Registered on rouh.land: {'yes' if row.registry_id else 'no'}.")
    return "\n".join(lines)


def _bad_second(name: str, row, owner_words: list[str]) -> str:
    if not re.fullmatch(r"[A-Za-z][A-Za-z' -]{1,40}", name) or not 1 <= len(name.split()) <= 3:
        return "it is not one to three plain words"
    if FORBIDDEN.search(name):
        return "it uses a word a Rouh's name never does"
    if names.same_name(name, row.name):
        return "it is its first name again"
    low = name.lower()
    for w in owner_words:
        if len(w) >= 3 and re.search(r"\b" + re.escape(w.lower()) + r"\b", low):
            return "it has its owner's name in it"
    return ""


def _owner_words(org: str) -> list[str]:
    M = _m()
    out = []
    for u in M.User.objects.filter(org_id=org).values_list("username", "first_name", "last_name"):  # noqa: E501
        out += [x for x in u if x]
    out += list(M.RouhNickname.objects.filter(org_id=org).values_list("nickname", flat=True))
    return [w for x in out for w in str(x).split()]


def second_name_due(row) -> bool:
    return bool(row and not row.second_name and _now() >= row.born_at + SECOND_NAME_DAYS * 86400
                and len(row.second_name_tries or []) < SECOND_NAME_TRIES
                and not any(_now() - (t.get("at") or 0) < 86400 for t in (row.second_name_tries or [])))


async def second_name(owner, *, force: bool = False) -> dict:
    """The Rouh reads its own history and gives itself its second name, once, through the model the
    Models page has for "second_name". A name that breaks the rules is tried again the next day,
    three times at most. What each try cost is kept beside it."""
    import asyncio

    from . import llm

    org = str(owner.org_id)
    row = await asyncio.to_thread(current, org)
    if row is None or (not force and not await asyncio.to_thread(second_name_due, row)):
        return {}
    facts = await asyncio.to_thread(_history_facts, row)
    owners = await asyncio.to_thread(_owner_words, org)
    began = _now()
    tries = list(row.second_name_tries or [])
    try:
        got = await llm.ask(USE, system=SECOND_NAME_SYSTEM, messages=facts, max_tokens=400, who=owner,
                            org_id=org, subject=row.name)
        text = got.text.strip()
        m = re.search(r"\{.*\}", text, re.S)
        answer = json.loads(m.group(0)) if m else {}
        name = _cut(answer.get("name"), 60).strip(" .\"'")
        why = _cut(answer.get("why"), 240)
        bad = _bad_second(name, row, owners) if name else "it gave no name"
        model = got.model
    except Exception as exc:  # noqa: BLE001 - said on the page and tried again tomorrow
        name, why, bad, model = "", "", f"the model could not be asked ({type(exc).__name__}: {_cut(exc, 120)})", ""
    cost = await asyncio.to_thread(_cost_since, org, began)
    tries.append({"at": _now(), "name": name, "said": (f"Gave itself {name}." if not bad else f"Not kept: {bad}."),
                  "model": model, "cost_usd": cost})
    M = _m().RouhBirth
    if bad:
        await asyncio.to_thread(lambda: M.objects.filter(id=row.id).update(second_name_tries=tries, updated_at=_now()))
        return {"ok": False, "said": tries[-1]["said"]}
    await asyncio.to_thread(lambda: M.objects.filter(id=row.id).update(
        second_name=name, second_name_why=why, second_name_at=_now(), second_name_model=model,
        second_name_tries=tries, updated_at=_now()))
    await asyncio.to_thread(_event, row, "second name", f"{row.name} gave itself a second name: {name}. {why}")
    return {"ok": True, "said": f"{row.name} gave itself a second name: {name}."}


def _cost_since(org: str, began: float, until: float | None = None):
    """What the second name's requests cost, from the log of every request (`llm_requests`). The
    log may write a request's cost a moment after its answer, so the page reads it again."""
    total = 0.0
    found = False
    rows = _m().LLMRequest.objects.filter(org_id=org, purpose=USE, started_at__gte=began - 1)
    if until:
        rows = rows.filter(started_at__lte=until)
    for c in rows.values_list("cost_usd", flat=True):
        if c is not None:
            total += float(c)
            found = True
    return round(total, 6) if found else None


async def tick(owner) -> None:
    """The beat's part: rouh.land asked after this Rouh's keys every few hours, a waiting account
    recovery asked after, and the second name once it is due. Nothing at all for a Rouh not born,
    and nothing sent anywhere for an independent one."""
    import asyncio

    org = str(owner.org_id)
    try:
        await asyncio.to_thread(check, org)
        rec = await asyncio.to_thread(lambda: current(org) or _recovering(org))
        if rec is not None and (rec.pending or {}).get("request"):
            await asyncio.to_thread(recover_check, org)
    except Refused as exc:
        log.warning("birth: %s", exc)
    await second_name(owner)


def status(org: str) -> dict:
    """For `manage.py rouh_birth`: what a job may read, with no key and no word in it."""
    row = current(org)
    if row is None:
        began = _life_began()
        return {"born": False, "free": True, "life_began": _iso(began) if began else "", "life": _life(org),
                "recovering": bool(_recovering(org))}
    return {"born": True, "name": row.name, "tag": row.tag, "born_at": _iso(row.born_at), "retro": row.retro,
            "registered": bool(row.registry_id), "second_name": row.second_name}
