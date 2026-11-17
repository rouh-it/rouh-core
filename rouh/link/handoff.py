"""Hand-offs between Rouhs that do not know each other well (phase 4), in fixed forms only.

A client's Rouh hands a business's Rouh a **brief** (what is needed, by when, a budget band, how to
answer); the business's person reads it and their Rouh sends back a **quote** (an amount, a
currency, until when, a few words). Every field is a fixed form (`forms.FORMS`): no free order
travels, and what arrives is kept for a person to read, never handed to a model that can act.

**Money only ever as a proposal.** A Rouh may send a ``money.proposal`` (an amount and what for).
It is shown to the person on its own page with no AI on it (`/link/money/<id>`), and only the
person's own press says "I agree"; the agreement is signed into this Rouh's log, which the other
side's person can read (`log.ask`).
No Rouh pays, signs or books anything by itself, and nothing here moves money: paying, if the person
wants to, is theirs to do, outside Rouh Link.

All of this is reached by strangers only while the owner's strangers switch is on, which stays held
off for every Rouh until rouh.land's terms cover the relay and Rouhs talking (`me.held`).
"""
from __future__ import annotations

import time
import uuid

from . import limits, log, wire


def _now() -> float:
    return time.time()


def _keep(org: str, peer_label: str, kind: str, key: str, form: dict, state: str = "new") -> None:
    from rouh.models import LinkMessage

    LinkMessage.objects.update_or_create(org_id=org, msg_id=f"{kind}:{key}", direction="handoff", defaults=dict(
        peer_label=peer_label, kind=kind, envelope={"form": {k: str(v) if isinstance(v, str) else v for k, v in form.items()}},
        state=state, created_at=_now()))


def listing(org: str) -> list[dict]:
    from rouh.models import LinkMessage

    out = []
    for r in LinkMessage.objects.filter(org_id=org, direction="handoff").order_by("-created_at")[:100]:
        out.append({"id": r.msg_id, "peer": r.peer_label, "kind": r.kind, "form": (r.envelope or {}).get("form") or {},
                    "state": r.state, "at": r.created_at, "said": r.said})
    return out


def one(org: str, hid: str):
    from rouh.models import LinkMessage

    return LinkMessage.objects.filter(org_id=org, direction="handoff", msg_id=hid).first()


@wire.handles("handoff.brief")
def _brief(ctx, form) -> dict:
    _keep(ctx.org, ctx.peer.label, "handoff.brief", form["brief_id"], form)
    log.write(ctx.org, "brief", f"{ctx.peer.name} handed over a brief ({len(str(form['need']))} characters) for a person to read.",
              peer=ctx.peer.label)
    from . import spaces

    spaces.push_owner(ctx.org, {"type": "link_notice", "said": f"{ctx.peer.name} handed you a brief."})
    return {"kept": True}


@wire.handles("handoff.quote")
def _quote(ctx, form) -> dict:
    _keep(ctx.org, ctx.peer.label, "handoff.quote", form["brief_id"], form)
    log.write(ctx.org, "quote", f"{ctx.peer.name} sent a quote: {form['amount']} {form['currency']}, for a person to read.",
              peer=ctx.peer.label)
    return {"kept": True}


@wire.handles("money.proposal")
def _money(ctx, form) -> dict:
    _keep(ctx.org, ctx.peer.label, "money.proposal", form["proposal_id"], form)
    log.write(ctx.org, "money", f"{ctx.peer.name} proposed {form['amount']} {form['currency']}; only this Rouh's person "
              f"can agree, on its own page. Nothing is paid.", peer=ctx.peer.label)
    from . import spaces

    spaces.push_owner(ctx.org, {"type": "link_notice",
                                "said": f"{ctx.peer.name} proposes {form['amount']} {form['currency']}. Nothing is paid."})
    return {"kept": True}


def send_brief(org: str, label: str, need: str, by_when: str = "", budget_band: str = "ask") -> dict:
    from . import forms, peers

    peer = peers.peer_row(org, label)
    if peer is None or peer.state != "connected":
        raise peers.Problem("Connect to that Rouh first.")
    body = {"brief_id": uuid.uuid4().hex[:16], "need": need[:1200], "budget_band": budget_band,
            "reply_way": "this-link", **({"by_when": by_when} if by_when else {})}
    forms.read_message("handoff.brief", body)
    wire.queue(org, peer, "handoff.brief", body)
    log.write(org, "brief", f"Handed {peer.name} a brief.", peer=label)
    return {"brief_id": body["brief_id"]}


def send_quote(org: str, brief_id: str, amount: float, currency: str, words: str = "", valid_until: str = "") -> dict:
    from rouh.models import LinkMessage

    from . import forms, peers

    row = one(org, f"handoff.brief:{brief_id}")
    if row is None:
        raise peers.Problem("There is no such brief.")
    peer = peers.peer_row(org, row.peer_label)
    if peer is None or peer.state != "connected":
        raise peers.Problem("That Rouh is not connected now.")
    body = {"brief_id": brief_id, "amount": float(amount), "currency": currency, **({"words": words[:1200]} if words else {}),
            **({"valid_until": valid_until} if valid_until else {})}
    forms.read_message("handoff.quote", body)
    wire.queue(org, peer, "handoff.quote", body)
    LinkMessage.objects.filter(id=row.id).update(state="answered", said=f"quoted {amount} {currency}")
    log.write(org, "quote", f"Sent {peer.name} a quote of {amount} {currency}; a person decides on it there.", peer=peer.label)
    return {"ok": True}


def send_money(org: str, label: str, amount: float, currency: str, what_for: str) -> dict:
    """A proposal of money to another Rouh's person: words and a number, nothing more. Nothing moves."""
    from . import forms, peers

    peer = peers.peer_row(org, label)
    if peer is None or peer.state != "connected":
        raise peers.Problem("Connect to that Rouh first.")
    body = {"proposal_id": uuid.uuid4().hex[:16], "amount": float(amount), "currency": currency, "for": what_for[:300]}
    forms.read_message("money.proposal", body)
    wire.queue(org, peer, "money.proposal", body)
    log.write(org, "money", f"Proposed {amount} {currency} to {peer.name}; only its person can agree. Nothing is paid.",
              peer=label)
    return {"proposal_id": body["proposal_id"]}


def agree_money(org: str, hid: str, who_said: str) -> dict:
    """The person's own press on the page with no AI: agreed, signed into the log, told to the
    other side. Nothing is paid."""
    from rouh.models import LinkMessage

    from . import peers

    row = one(org, hid)
    if row is None or row.kind != "money.proposal":
        raise peers.Problem("There is no such proposal.")
    if row.state == "agreed":
        return {"state": "agreed"}
    f = (row.envelope or {}).get("form") or {}
    LinkMessage.objects.filter(id=row.id).update(state="agreed", said=f"agreed by {who_said}", done_at=_now())
    log.write(org, "money", f"This Rouh's person agreed {f.get('amount')} {f.get('currency')} for “{str(f.get('for'))[:80]}”, "
              f"on the page with no AI. Nothing was paid.", peer=row.peer_label)
    return {"state": "agreed"}


def decline(org: str, hid: str) -> dict:
    from rouh.models import LinkMessage

    LinkMessage.objects.filter(org_id=org, direction="handoff", msg_id=hid).update(state="declined", done_at=_now())
    return {"state": "declined"}


del limits
