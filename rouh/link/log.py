"""The signed log: every message and every change, in plain words, that both people can read.

Each entry is chained to the one before (``prev`` is its hash) and signed with this Rouh's daily
key, so a log handed to the other side (`share`) can be checked whole: nothing left out of the
middle, nothing changed. Each Rouh keeps its own; the page shows both side by side for a
connection, and the other side's is fetched from it and checked before it is shown.
"""
from __future__ import annotations

import hashlib
import json
import time

from . import seal


def _now() -> float:
    return time.time()


def _hash(entry: dict) -> str:
    return hashlib.sha256(seal.canonical(entry)).hexdigest()


def write(org: str, kind: str, plain: str, *, peer: str = "", space: str = "", entry: dict | None = None) -> None:
    """One entry, signed. Never raises: the log must not stop the thing it records."""
    from django.db import IntegrityError, transaction

    from rouh.models import LinkLog

    from . import me as _me

    try:
        who = _me.me(org)
    except Exception:  # noqa: BLE001 - an unborn Rouh writes nothing
        return
    plain = " ".join(str(plain).split())[:600].replace("—", "-")
    for _ in range(5):
        try:
            with transaction.atomic():
                last = LinkLog.objects.select_for_update().filter(org_id=org).order_by("-seq").first()
                seq = (last.seq + 1) if last else 1
                prev = last.hash if last else ""
                at = round(_now(), 3)
                body = {"seq": seq, "at": at, "kind": kind[:40], "plain": plain, "space_id": space[:80],
                        "peer": peer[:80], "prev": prev}
                h = _hash(body)
                LinkLog.objects.create(org_id=org, seq=seq, at=at, peer_label=peer[:80], space_id=space[:80],
                                       kind=kind[:40], plain=plain, entry=entry or {}, prev=prev, hash=h,
                                       sig=seal.sign(who.seed, {"hash": h}))
            return
        except IntegrityError:
            continue
        except Exception:  # noqa: BLE001
            import logging

            logging.getLogger("rouh.link").exception("the link log could not be written")
            return


def entries(org: str, *, peer: str = "", space: str = "", since: int = 0, most: int = 200) -> list[dict]:
    from rouh.models import LinkLog

    q = LinkLog.objects.filter(org_id=org, seq__gt=since)
    if peer:
        q = q.filter(peer_label=peer)
    if space:
        q = q.filter(space_id=space)
    rows = list(q.order_by("-seq")[:most])
    rows.reverse()
    return [{"seq": r.seq, "at": r.at, "kind": r.kind, "plain": r.plain, "space_id": r.space_id,
             "peer": r.peer_label, "hash": r.hash, "prev": r.prev, "sig": r.sig} for r in rows]


def check_shared(entries_: list[dict], key: str, peer_of_them: str) -> list[dict]:
    """The other side's entries that hold: each hash its body's, each signed by their key. An entry
    that does not hold is marked, never quietly dropped."""
    out = []
    for e in entries_:
        body = {"seq": e.get("seq"), "at": e.get("at"), "kind": e.get("kind"), "plain": str(e.get("plain") or ""),
                "space_id": e.get("space_id") or "", "peer": peer_of_them, "prev": e.get("prev") or ""}
        ok = _hash(body) == e.get("hash") and seal.holds(key, {"hash": e.get("hash")}, str(e.get("sig") or ""))
        out.append({**e, "holds": ok})
    return out


def verify_chain(org: str) -> dict:
    """Whether this Rouh's own log holds end to end."""
    from rouh.models import LinkLog

    prev, n, bad = "", 0, []
    for r in LinkLog.objects.filter(org_id=org).order_by("seq").iterator():
        body = {"seq": r.seq, "at": r.at, "kind": r.kind, "plain": r.plain, "space_id": r.space_id,
                "peer": r.peer_label, "prev": r.prev}
        if r.prev != prev or _hash(body) != r.hash:
            bad.append(r.seq)
        prev, n = r.hash, n + 1
    return {"entries": n, "broken_at": bad[:10], "holds": not bad}


def dumps(x) -> str:
    return json.dumps(x, ensure_ascii=False)
