"""Written delegate grants between Rouhs (phase 3): what another Rouh may decide for this one's person.

A person writes a grant to a connection they trust as Delegate ("Ilina's Rouh may agree meetings
for me: up to an hour, weekdays, 9 to 18, at most five a week"). It is:

- **written**: kept here with its limits and its words, signed by this Rouh, and its id;
- **shown to both people**: the other Rouh is sent the same grant (``grant.shown``) and its person
  sees it on their Connections page, exactly as written;
- **checked in code**: when the delegate's person says yes on this person's behalf
  (``grant.decide``), this Rouh's own code checks the grant is in force, of this kind, and that
  the time fits every limit, before it records the yes, as this person's yes "by grant"; nothing
  outside the grant is ever decided, and no model is asked;
- **withdrawn at once**: one press here; from that moment every ``grant.decide`` is refused, and
  the other side is told (``grant.withdrawn``).

Money is never in a grant (its limit is fixed at 0), in any phase.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime, timedelta

from . import limits, log, seal, trust, wire

WHAT = {"meetings": "agree meetings for me"}
DEFAULT_LIMITS = {"most_minutes": 60, "days": [0, 1, 2, 3, 4], "from_hour": 9, "to_hour": 18, "most_a_week": 5, "money": 0}
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _now() -> float:
    return time.time()


def words_of(what: str, lim: dict, other_name: str) -> str:
    days = ", ".join(DAYS[d] for d in lim.get("days", []))
    return (f"{other_name} may {WHAT.get(what, what)}: up to {lim.get('most_minutes', 60)} minutes, on {days or 'no day'}, "
            f"between {lim.get('from_hour', 9)}:00 and {lim.get('to_hour', 18)}:00, at most {lim.get('most_a_week', 5)} a week. "
            "Never money.")


def shown(row) -> dict:
    return {"grant_id": row.grant_id, "direction": row.direction, "peer": row.peer_label, "what": row.what,
            "limits": row.limits, "words": row.words, "created_at": row.created_at, "ends_at": row.ends_at,
            "withdrawn_at": row.withdrawn_at, "active": active(row)}


def active(row) -> bool:
    return row.withdrawn_at is None and (row.ends_at is None or row.ends_at > _now())


def listing(org: str) -> list[dict]:
    from rouh.models import LinkGrant

    return [shown(r) for r in LinkGrant.objects.filter(org_id=org).order_by("-created_at")[:100]]


def _clean_limits(given: dict | None) -> dict:
    lim = dict(DEFAULT_LIMITS)
    given = given or {}
    try:
        lim["most_minutes"] = max(15, min(480, int(given.get("most_minutes", lim["most_minutes"]))))
        lim["days"] = sorted({int(d) for d in given.get("days", lim["days"]) if 0 <= int(d) <= 6})
        lim["from_hour"] = max(0, min(23, int(given.get("from_hour", lim["from_hour"]))))
        lim["to_hour"] = max(lim["from_hour"] + 1, min(24, int(given.get("to_hour", lim["to_hour"]))))
        lim["most_a_week"] = max(0, min(50, int(given.get("most_a_week", lim["most_a_week"]))))
    except (TypeError, ValueError):
        pass
    lim["money"] = 0
    return lim


def give(org: str, label: str, *, what: str = "meetings", given_limits: dict | None = None, days: int = 90) -> dict:
    """This Rouh's person writes a grant to a connection trusted as Delegate."""
    from rouh.models import LinkGrant

    from . import me as _me
    from . import peers

    peer = peers.peer_row(org, label)
    if peer is None or peer.state != "connected":
        raise peers.Problem("Connect to that Rouh first.")
    if peer.trust != "delegate":
        raise peers.Problem(f"Trust {peer.name} as Delegate first; a grant is only for a delegate.")
    if what not in WHAT:
        raise peers.Problem("A grant is for meetings, for now.")
    me = _me.me(org)
    lim = _clean_limits(given_limits)
    gid = uuid.uuid4().hex[:16]
    words = words_of(what, lim, peer.name.split(" ·")[0] + "'s Rouh")
    ends = _now() + max(1, min(365, int(days))) * 86400
    body = {"grant_id": gid, "from": me.label, "to": label, "what": what, "limits": lim, "words": words, "ends_at": ends}
    sig = seal.sign(me.seed, body)
    LinkGrant.objects.create(org_id=org, grant_id=gid, direction="out", peer_label=label, what=what, limits=lim,
                             words=words, created_at=_now(), ends_at=ends, signature=sig)
    wire.queue(org, peer, "grant.shown", {"grant_id": gid, "what": what, "limits": lim, "words": words, "ends_at": ends,
                                          "sig": sig})
    log.write(org, "grant", f"Wrote a grant to {peer.name}: {words}", peer=label)
    return shown(LinkGrant.objects.get(org_id=org, grant_id=gid, direction="out"))


def withdraw(org: str, grant_id: str) -> dict:
    """One press: from now every decision under it is refused; the other side is told."""
    from rouh.models import LinkGrant

    from . import peers

    row = LinkGrant.objects.filter(org_id=org, grant_id=grant_id, direction="out").first()
    if row is None:
        raise peers.Problem("No such grant of yours.")
    LinkGrant.objects.filter(id=row.id).update(withdrawn_at=_now())
    log.write(org, "grant", f"Withdrew the grant to {row.peer_label}.", peer=row.peer_label)
    peer = peers.peer_row(org, row.peer_label)
    if peer is not None and peer.state == "connected":
        wire.queue(org, peer, "grant.withdrawn", {"grant_id": grant_id})
    return shown(LinkGrant.objects.get(id=row.id))


@wire.handles("grant.shown")
def _shown(ctx, form) -> dict:
    """The other side's person wrote a grant to this Rouh: kept, to show this person."""
    from rouh.models import LinkGrant

    body = {"grant_id": form["grant_id"], "from": ctx.peer.label, "to": ctx.me.label, "what": form["what"],
            "limits": form["limits"], "words": str(form["words"]), "ends_at": form.get("ends_at")}
    if not seal.holds(ctx.peer.daily_key, body, form["sig"]):
        raise limits.No("That grant's signature does not hold.")
    LinkGrant.objects.update_or_create(org_id=ctx.org, grant_id=form["grant_id"], direction="in", defaults=dict(
        peer_label=ctx.peer.label, what=form["what"], limits=form["limits"], words=str(form["words"]),
        created_at=_now(), ends_at=form.get("ends_at"), signature=form["sig"]))
    log.write(ctx.org, "grant", f"{ctx.peer.name} wrote this Rouh a grant: {form['words']}", peer=ctx.peer.label)
    from . import spaces

    spaces.push_owner(ctx.org, {"type": "link_notice", "said": f"{ctx.peer.name} gave your Rouh a grant: {form['words']}"})
    return {}


@wire.handles("grant.withdrawn")
def _withdrawn(ctx, form) -> dict:
    from rouh.models import LinkGrant

    LinkGrant.objects.filter(org_id=ctx.org, grant_id=form["grant_id"], direction="in",
                             peer_label=ctx.peer.label).update(withdrawn_at=_now())
    log.write(ctx.org, "grant", f"{ctx.peer.name} withdrew its grant.", peer=ctx.peer.label)
    return {}


def fits(lim: dict, start: datetime, end: datetime, used_this_week: int) -> str:
    """'' when a meeting at this time fits every limit, else why not, in words."""
    minutes = (end - start).total_seconds() / 60
    if minutes > lim.get("most_minutes", 60):
        return f"longer than the grant's {lim.get('most_minutes')} minutes"
    if start.weekday() not in lim.get("days", []):
        return "not on a day the grant allows"
    if start.hour < lim.get("from_hour", 9) or (end.hour + end.minute / 60) > lim.get("to_hour", 18):
        return "outside the grant's hours"
    if used_this_week >= lim.get("most_a_week", 5):
        return "the grant's meetings for this week are used up"
    if lim.get("money"):
        return "a grant never covers money"
    return ""


def _used_this_week(org: str, grant_id: str) -> int:
    from rouh.models import LinkLog

    since = _now() - 7 * 86400
    return LinkLog.objects.filter(org_id=org, kind="grant.yes", at__gte=since, entry__grant_id=grant_id).count()


@wire.handles("grant.decide")
async def _decide(ctx, form) -> dict:
    """On the granting person's Rouh: the delegate's person said yes for this person. Code checks the
    written grant and every limit, then records the yes as this person's, by grant."""
    from rouh.models import LinkGrant

    from rouh import clock

    from . import spaces

    row = await asyncio.to_thread(lambda: LinkGrant.objects.filter(
        org_id=ctx.org, grant_id=form["grant_id"], direction="out", peer_label=ctx.peer.label).first())
    if row is None or not active(row):
        raise limits.No("There is no grant in force for that.")
    if trust.valid(ctx.peer.trust) != "delegate":
        raise limits.No("That Rouh is no longer trusted as a delegate.")
    sid = form["space_id"]
    live = await spaces.get(ctx.org, sid)
    prop = live.doc["proposals"].get(form["proposal"])
    if prop is None or prop["state"] != "open" or prop["kind"] != row.what.rstrip("s"):
        raise limits.No("That proposal is not open, or not what the grant covers.")
    opt = next((o for o in prop["options"] if o["id"] == form["option"]), None)
    if opt is None or not opt.get("start") or not opt.get("end"):
        raise limits.No("That is not one of the times.")
    zone = clock.now().tzinfo
    start = datetime.fromisoformat(opt["start"].replace("Z", "+00:00")).astimezone(zone)
    end = datetime.fromisoformat(opt["end"].replace("Z", "+00:00")).astimezone(zone)
    used = await asyncio.to_thread(_used_this_week, ctx.org, row.grant_id)
    why = fits(row.limits or {}, start, end, used)
    if why:
        await asyncio.to_thread(log.write, ctx.org, "grant.no", f"Refused {ctx.peer.name}'s yes under its grant: {why}.",
                                peer=ctx.peer.label, space=sid)
        raise limits.No(f"Outside the grant: {why}.")
    me_label = ctx.me.label
    got = await spaces.change(ctx.org, sid, [spaces.new_op("yes", f"person:{me_label}", pid=form["proposal"],
                                                           option=form["option"], by_grant=row.grant_id)])
    if got.get("refused"):
        raise limits.No(got["refused"][0]["why"])
    await asyncio.to_thread(log.write, ctx.org, "grant.yes",
                            f"Said yes to {opt['label']} for this Rouh's person, because {ctx.peer.name}'s person "
                            f"agreed it under the written grant.", peer=ctx.peer.label, space=sid,
                            entry={"grant_id": row.grant_id})
    spaces.push_owner(ctx.org, {"type": "link_notice",
                                "said": f"{ctx.peer.name} agreed {opt['label']} for you, under your grant."})
    return {"ok": True}


async def decide_for(org: str, sid: str, granter: str, proposal: str, option: str) -> dict:
    """On the delegate's Rouh: its person says yes for the granter, under the grant they hold."""
    from rouh.models import LinkGrant

    from . import peers

    row = await asyncio.to_thread(lambda: LinkGrant.objects.filter(
        org_id=org, direction="in", peer_label=granter, withdrawn_at__isnull=True).order_by("-created_at").first())
    if row is None or not active(row):
        raise peers.Problem("You hold no grant in force from them.")
    peer = await asyncio.to_thread(peers.peer_row, org, granter)
    if peer is None or peer.state != "connected":
        raise peers.Problem("Not connected to them.")
    got = await wire.ask(org, peer, "grant.decide", {"grant_id": row.grant_id, "space_id": sid, "proposal": proposal,
                                                    "option": option})
    await asyncio.to_thread(log.write, org, "grant", f"Said yes for {peer.name}'s person under their grant.",
                            peer=granter, space=sid)
    return got


del timedelta
