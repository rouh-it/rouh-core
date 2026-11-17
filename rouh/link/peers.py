"""Connecting two Rouhs, and how far each trusts the other.

Three ways in, each ending in a connection with a trust level on each side, chosen by that side's
person:

1. **A link or a QR code.** One person makes a connect link (`invite`): ``<address>/link/join/<secret>``,
   good once, for 14 days, optionally for one Rouh only (``for_label``). The other person brings it
   to their own Rouh (`accept`), which fetches the first Rouh's card, checks it, and says ``hello``
   with the secret; the first Rouh checks the secret and the card and connects. The QR code is the
   same link.
2. **A contact.** A contact's "their Rouh" line names their Rouh's address. Saying ``hello`` to it
   with no secret asks to connect; the other side connects at once if its person put this Rouh on
   that person's contact too, and otherwise asks its person (a request on the Connections page).
3. **A stranger's Rouh** (phase 4), only while the owner's strangers switch is on.

Lowering a level or cutting a connection is one press (`set_trust`, `cut`), takes effect at once
here (every message is checked against the row as it is now), and the other side is told.
"""
from __future__ import annotations

import hashlib
import secrets
import time
from urllib.parse import urlsplit

from . import card as _card
from . import forms, limits, log, trust, wire

INVITE_DAYS = 14


class Problem(ValueError):
    """Something the person can fix, said in plain words."""


def _now() -> float:
    return time.time()


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def dialable(address: str) -> str:
    """The address to post to, or "" when this Rouh must never dial it and reaches that Rouh through
    the mailbox only. Only https to a public name is dialled: never a private, loopback or link-local
    address, so a card cannot point this Rouh at its own machine or its network. Loopback is allowed
    only to a Rouh that is itself on loopback (a test world on this machine)."""
    import ipaddress
    import socket

    from . import me as _me

    p = urlsplit(str(address or ""))
    host = (p.hostname or "").lower()
    if not host:
        return ""
    mine = urlsplit(_me.own_address()).hostname or ""
    if mine in ("127.0.0.1", "localhost") and host in ("127.0.0.1", "localhost") and p.scheme in ("http", "https"):
        return f"{p.scheme}://{p.netloc}"
    if p.scheme != "https" or p.username or p.password:
        return ""
    try:
        ip = ipaddress.ip_address(host)
        infos = [ip]
    except ValueError:
        if "." not in host or host.endswith((".local", ".internal", ".localhost")):
            return ""
        try:
            infos = {ipaddress.ip_address(i[4][0]) for i in socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)}
        except OSError:
            return f"https://{p.netloc}"   # not resolvable now: tried later, refused then if private
    if any(not i.is_global for i in infos):
        return ""
    return f"https://{p.netloc}"


def peer_row(org: str, label: str):
    from rouh.models import LinkPeer

    return LinkPeer.objects.filter(org_id=org, label=label).first()


def shown(row) -> dict:
    return {"label": row.label, "name": row.name, "address": row.address, "trust": row.trust,
            "trust_word": trust.WORDS.get(row.trust, row.trust), "silo": row.silo, "state": row.state,
            "via": row.via, "contact_id": row.contact_id, "note": row.note,
            "since": row.created_at, "last_seen": row.last_seen_at}


def listing(org: str) -> list[dict]:
    from rouh.models import LinkPeer

    return [shown(r) for r in LinkPeer.objects.filter(org_id=org).order_by("-updated_at")]


# --- connect links --------------------------------------------------------------------------------


def invite(org: str, *, trust_level: str = "known", silo: str = "", for_label: str = "", note: str = "",
           days: int = INVITE_DAYS) -> dict:
    """A new connect link. The secret is in the link only; its hash is kept."""
    from rouh.models import LinkInvite

    from . import me as _me

    me = _me.me(org)
    if not me.address:
        raise Problem("This Rouh has no address other Rouhs can reach yet (Settings, Connections, Phone).")
    token = secrets.token_urlsafe(24)
    now = _now()
    row = LinkInvite.objects.create(org_id=org, token_hash=_hash(token), trust=trust.valid(trust_level),
                                    silo=silo[:40], for_label=for_label[:80], note=note[:200],
                                    created_at=now, expires_at=now + days * 86400)
    link = f"{me.address}/link/join/{token}"
    words = f"Made a connect link at {trust.WORDS[row.trust]}"
    words += f", for {for_label} only" if for_label else ""
    log.write(org, "invite", words + f", good until {time.strftime('%d %B %Y', time.gmtime(row.expires_at))}.",
              peer=for_label)
    return {"id": row.id, "link": link, "trust": row.trust, "for_label": row.for_label,
            "expires_at": row.expires_at, "qr": qr_svg(link)}


def qr_svg(link: str) -> str:
    try:
        import io

        import segno

        out = io.BytesIO()
        segno.make(link, error="m").save(out, kind="svg", scale=4, border=2, dark="#111", light="#fff")
        return out.getvalue().decode()
    except Exception:  # noqa: BLE001 - the link alone still works
        return ""


def invites(org: str) -> list[dict]:
    from rouh.models import LinkInvite

    now = _now()
    return [{"id": r.id, "trust": r.trust, "for_label": r.for_label, "note": r.note, "created_at": r.created_at,
             "expires_at": r.expires_at, "used_at": r.used_at, "used_by": r.used_by,
             "open": r.used_at is None and r.withdrawn_at is None and r.expires_at > now}
            for r in LinkInvite.objects.filter(org_id=org).order_by("-created_at")[:50]]


def withdraw_invite(org: str, invite_id: int) -> None:
    from rouh.models import LinkInvite

    LinkInvite.objects.filter(org_id=org, id=invite_id, used_at__isnull=True).update(withdrawn_at=_now())


def parse_link(link: str) -> tuple[str, str]:
    """(address, secret) of a connect link, or Problem."""
    link = str(link or "").strip()
    parts = urlsplit(link)
    if parts.scheme not in ("https", "http") or not parts.netloc or "/link/join/" not in parts.path:
        raise Problem("That is not a Rouh connect link: it looks like https://<name>.rouh.page/link/join/...")
    token = parts.path.split("/link/join/", 1)[1].strip("/")
    if not token or len(token) > 120:
        raise Problem("That connect link has no secret in it.")
    if parts.scheme == "http" and parts.hostname not in ("127.0.0.1", "localhost"):
        raise Problem("A connect link must be https.")
    return f"{parts.scheme}://{parts.netloc}", token


async def accept(org: str, link: str, *, trust_level: str = "known", silo: str = "", contact_id: str = "") -> dict:
    """Bring another Rouh's connect link here: connect to it."""
    import asyncio

    from . import me as _me

    address, token = parse_link(link)
    if not dialable(address):
        raise Problem("That link does not point at a Rouh's public address.")
    return await _say_hello(org, address, token=token, trust_level=trust_level, silo=silo,
                            contact_id=contact_id, via="link", me_mod=_me, asyncio=asyncio)


async def connect_address(org: str, address: str, *, trust_level: str = "known", silo: str = "",
                          contact_id: str = "", via: str = "contact") -> dict:
    """Ask the Rouh at this address to connect, with no link: from a contact's "their Rouh" line."""
    import asyncio

    from . import me as _me

    address = normal_address(address)
    if not dialable(address):
        raise Problem("That is not a Rouh's public address.")
    return await _say_hello(org, address, token="", trust_level=trust_level, silo=silo,
                            contact_id=contact_id, via=via, me_mod=_me, asyncio=asyncio)


def normal_address(text: str) -> str:
    """https://still-heron.rouh.page from "still-heron.rouh.page", "Still Heron", or a link."""
    from rouh import relay

    t = str(text or "").strip().rstrip("/")
    if not t:
        raise Problem("Which Rouh? Its address looks like still-heron.rouh.page.")
    if "://" not in t:
        if "." not in t:
            t = relay.label_for(t.split("·")[0]) + (("-" + t.split("·")[1].strip().lower()) if "·" in t else "")
            t = f"{t}.{relay.domain()}"
        t = "https://" + t
    p = urlsplit(t)
    if not p.hostname:
        raise Problem("That is not a Rouh's address.")
    return f"{p.scheme}://{p.netloc}"


async def _say_hello(org, address, *, token, trust_level, silo, contact_id, via, me_mod, asyncio) -> dict:
    from rouh.models import LinkPeer

    me = await asyncio.to_thread(me_mod.me, org)
    try:
        theirs, part = await _card.fetch(address)
    except _card.Bad as exc:
        raise Problem(f"That Rouh's card does not hold: {exc}.") from None
    except wire.Unreachable:
        raise Problem("That Rouh did not answer. It may be off; try again later.") from None
    if part["label"] == me.label:
        raise Problem("That is this Rouh's own link.")
    now = _now()
    existing = await asyncio.to_thread(peer_row, org, part["label"])
    if existing is not None and existing.state == "blocked":
        raise Problem("You blocked that Rouh. Unblock it on its connection first.")

    def keep():
        LinkPeer.objects.update_or_create(org_id=org, label=part["label"], defaults=dict(
            name=f"{part['name']} ·{part['tag']}", address=dialable(part["address"] or address), card=part,
            daily_key=part["daily_key"], link_key=part["link_key"], trust=trust.valid(trust_level),
            silo=silo, state="waiting" if not token else "connected", via=via,
            contact_id=contact_id or (existing.contact_id if existing else ""),
            created_at=existing.created_at if existing else now, updated_at=now))
        return peer_row(org, part["label"])

    row = await asyncio.to_thread(keep)
    my_card = await asyncio.to_thread(_card.build, org)
    try:
        got = await wire.ask(org, row, "hello", {"invite": token, "card": my_card,
                                                 "trust_offered": row.trust})
    except wire.Refusal as exc:
        await asyncio.to_thread(lambda: LinkPeer.objects.filter(id=row.id).update(state="refused", note=str(exc.said)[:200]))
        raise Problem(f"{row.name} said no: {exc.said}") from None
    except wire.Unreachable:
        raise Problem("That Rouh did not answer. It may be off; try again later.") from None
    state = "connected" if got.get("state") == "connected" else "waiting"
    await asyncio.to_thread(lambda: LinkPeer.objects.filter(id=row.id).update(state=state, updated_at=_now()))
    await asyncio.to_thread(log.write, org, "connect",
                            (f"Connected to {row.name} at {trust.WORDS[row.trust]}, by {via}." if state == "connected"
                             else f"Asked {row.name} to connect; waiting for its person."), peer=row.label)
    return shown(await asyncio.to_thread(peer_row, org, row.label))


def note_contact(org: str, contact_id: str, address: str) -> dict:
    """A contact's "their Rouh" line: this contact's Rouh is at that address. Kept as a connection
    that is only noted until one side says hello; a hello from it then connects at once (both people
    said so: one by noting it here, the other by asking from their contact)."""
    from rouh.models import LinkPeer

    address = normal_address(address)
    host = urlsplit(address).hostname or ""
    label = host.split(".")[0]
    if not forms.LABEL.match(label):
        raise Problem("That is not a Rouh's address.")
    now = _now()
    row = peer_row(org, label)
    if row is None:
        LinkPeer.objects.create(org_id=org, label=label, name=label, address=address, state="noted",
                                trust="known", via="contact", contact_id=str(contact_id)[:80],
                                created_at=now, updated_at=now)
    else:
        LinkPeer.objects.filter(id=row.id).update(contact_id=str(contact_id)[:80], updated_at=now)
    log.write(org, "contact", f"Noted {label} as a contact's Rouh.", peer=label)
    return shown(peer_row(org, label))


def contact_line(org: str, contact_id: str) -> dict | None:
    """What a contact card shows on its "Their Rouh" line."""
    row = for_contact(org, contact_id)
    return shown(row) if row is not None else None


@wire.handles("hello")
def _hello(ctx, form) -> dict:
    """Another Rouh asks to connect, with a connect link's secret or from a contact."""
    from rouh.models import LinkInvite, LinkPeer

    try:
        part = _card.check(form["card"], label=ctx.head["from"])
    except _card.Bad as exc:
        raise limits.No(f"Your card does not hold: {exc}.") from None
    if part["daily_key"] != ctx.head["from_key"]:
        raise limits.No("Your card names another key than the one that signed this.")
    now = _now()
    org = ctx.org
    existing = ctx.peer
    if existing is not None and existing.state == "blocked":
        raise limits.No("This Rouh does not connect to you.")
    token = str(form.get("invite") or "")
    level, silo, via, state = "known", "", "contact", "asked"
    if token:
        inv = LinkInvite.objects.filter(org_id=org, token_hash=_hash(token)).first()
        if inv is None or inv.used_at is not None or inv.withdrawn_at is not None or inv.expires_at < now:
            raise limits.No("That connect link is used, withdrawn or out of date. Ask for a new one.")
        if inv.for_label and inv.for_label != part["label"]:
            raise limits.No("That connect link is for another Rouh.")
        LinkInvite.objects.filter(id=inv.id, used_at__isnull=True).update(used_at=now, used_by=part["label"])
        level, silo, via, state = inv.trust, inv.silo, "link", "connected"
    elif existing is not None and existing.state in ("waiting", "connected"):
        # Our person asked first (we said hello and are waiting), or this is a reconnect.
        level, silo, via, state = existing.trust, existing.silo, existing.via, "connected"
    elif existing is not None and existing.state == "noted":
        level, via, state = "known", "contact", "connected"
    else:
        from . import me as _me

        if not _me.settings(org)["strangers"]:
            raise limits.No("This Rouh connects only by a connect link from its person, or from a contact.")
        level, via = "stranger", "stranger"
    note = ""
    if via == "stranger":
        from . import identity

        note = identity.check(part)["said"][:600]
    LinkPeer.objects.update_or_create(org_id=org, label=part["label"], defaults=dict(
        name=f"{part['name']} ·{part['tag']}", address=dialable(part["address"]), card=part,
        daily_key=part["daily_key"], link_key=part["link_key"],
        trust=existing.trust if existing is not None and existing.state == "connected" else level,
        silo=existing.silo if existing is not None and existing.silo else silo, state=state, via=via,
        **({"note": note} if note else {}),
        created_at=existing.created_at if existing is not None else now, updated_at=now, last_seen_at=now))
    name = f"{part['name']} ·{part['tag']}"
    log.write(org, "hello", f"{name} connected, by a connect link, at {trust.WORDS[level]}." if state == "connected"
              else f"{name} asked to connect.", peer=part["label"])
    _tell_owner(org, f"{name} " + ("is connected now." if state == "connected" else "asks to connect."))
    return {"state": state}


def accept_request(org: str, label: str, trust_level: str = "known", silo: str = "") -> dict:
    """The person says yes to a Rouh that asked to connect: connected, and the other side told."""
    from rouh.models import LinkPeer

    row = peer_row(org, label)
    if row is None or row.state not in ("asked", "waiting"):
        raise Problem("There is no request from that Rouh.")
    LinkPeer.objects.filter(id=row.id).update(state="connected", trust=trust.valid(trust_level),
                                              silo=silo or row.silo, updated_at=_now())
    row = peer_row(org, label)
    wire.queue(org, row, "hello", {"invite": "", "card": _card.build(org), "trust_offered": row.trust})
    log.write(org, "connect", f"Said yes to {row.name}, at {trust.WORDS[row.trust]}.", peer=label)
    return shown(row)


def set_trust(org: str, label: str, level: str, *, by: str = "the person") -> dict:
    from rouh.models import LinkPeer

    row = peer_row(org, label)
    if row is None:
        raise Problem("No such connection.")
    level = trust.valid(level)
    LinkPeer.objects.filter(id=row.id).update(trust=level, updated_at=_now())
    log.write(org, "trust", f"{by.capitalize()} set {row.name} to {trust.WORDS[level]}"
              f" (was {trust.WORDS.get(row.trust, row.trust)}).", peer=label)
    if row.state == "connected":
        wire.queue(org, row, "trust.told", {"level": level})
    from . import spaces

    spaces.connection_changed(org, label)
    return shown(peer_row(org, label))


def set_silo(org: str, label: str, silo: str) -> dict:
    from rouh.models import LinkPeer

    row = peer_row(org, label)
    if row is None:
        raise Problem("No such connection.")
    LinkPeer.objects.filter(id=row.id).update(silo=silo[:40], updated_at=_now())
    log.write(org, "silo", f"{row.name} is on the {silo or 'no'} side now.", peer=label)
    from . import spaces

    spaces.connection_changed(org, label)
    return shown(peer_row(org, label))


def cut(org: str, label: str, *, block: bool = False) -> dict:
    """One press: the connection is cut (or the Rouh blocked) here at once; the other side told."""
    from rouh.models import LinkPeer

    row = peer_row(org, label)
    if row is None:
        raise Problem("No such connection.")
    LinkPeer.objects.filter(id=row.id).update(state="blocked" if block else "cut", updated_at=_now())
    log.write(org, "block" if block else "cut", f"{'Blocked' if block else 'Cut the connection to'} {row.name}.",
              peer=label)
    if row.state == "connected" and not block:
        try:
            wire.queue(org, row, "cut", {"why": "Its person cut the connection."})
        except Exception:  # noqa: BLE001 - cut here whatever
            pass
    from . import spaces

    spaces.connection_changed(org, label)
    return shown(peer_row(org, label))


def unblock(org: str, label: str) -> dict:
    from rouh.models import LinkPeer

    LinkPeer.objects.filter(org_id=org, label=label, state="blocked").update(state="cut", updated_at=_now())
    log.write(org, "unblock", f"Unblocked {label}; it is not connected until a new link.", peer=label)
    return shown(peer_row(org, label))


def link_contact(org: str, label: str, contact_id: str) -> dict:
    from rouh.models import LinkPeer

    LinkPeer.objects.filter(org_id=org, label=label).update(contact_id=str(contact_id)[:80], updated_at=_now())
    return shown(peer_row(org, label))


def for_contact(org: str, contact_id: str):
    from rouh.models import LinkPeer

    return LinkPeer.objects.filter(org_id=org, contact_id=str(contact_id)).first()


@wire.handles("cut")
def _cut(ctx, form) -> dict:
    from rouh.models import LinkPeer

    LinkPeer.objects.filter(org_id=ctx.org, label=ctx.peer.label).exclude(state="blocked").update(
        state="cut", updated_at=_now())
    log.write(ctx.org, "cut", f"{ctx.peer.name} cut the connection.", peer=ctx.peer.label)
    from . import spaces

    spaces.connection_changed(ctx.org, ctx.peer.label)
    return {}


@wire.handles("trust.told")
def _told(ctx, form) -> dict:
    log.write(ctx.org, "trust", f"{ctx.peer.name} now trusts this Rouh as {trust.WORDS[form['level']]}.",
              peer=ctx.peer.label)
    return {}


@wire.handles("ping")
def _ping(ctx, form) -> dict:
    return {"pong": True}


@wire.handles("bye")
def _bye(ctx, form) -> dict:
    return {}


@wire.handles("log.ask")
def _log_ask(ctx, form) -> dict:
    """The other side's person reads what this Rouh logged about them: entries naming them only."""
    got = log.entries(ctx.org, peer=ctx.peer.label, since=int(form.get("since") or 0), most=300)
    return {"entries": [{k: e[k] for k in ("seq", "at", "kind", "plain", "space_id", "hash", "prev", "sig")}
                        for e in got], "key": ctx.me.daily_public}


async def their_log(org: str, label: str) -> list[dict]:
    """What the other Rouh logged about this one, each entry checked against its key."""
    import asyncio

    row = await asyncio.to_thread(peer_row, org, label)
    if row is None or row.state != "connected":
        return []
    got = await wire.ask(org, row, "log.ask", {"since": 0})
    try:
        form = forms.read_message("log.share", got)
    except forms.Refused:
        return []
    from . import me as _me

    me = await asyncio.to_thread(_me.me, org)
    return log.check_shared(form["entries"], row.daily_key, me.label)


def _tell_owner(org: str, words: str) -> None:
    """A quiet notice on the person's open pages (`spaces.push`)."""
    try:
        from . import spaces

        spaces.push_owner(org, {"type": "link_notice", "said": words})
    except Exception:  # noqa: BLE001
        pass
