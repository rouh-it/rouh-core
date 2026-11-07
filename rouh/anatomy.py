"""Anatomy's status board, at `/anatomy`: one line for each of its groups (`genes.ANATOMY`),
and on it only what needs the person's attention now.

Petar, 14 October 2026 (card 1554): Anatomy is one place in five groups, You, Connections,
Behaviour, Money and Meta, with Rouh Land Account the sixth since 4 November 2026, and its front is a status board rather than a list of tiles: a
connection that has to be made again, a card near its cap or about to expire, the heartbeat
paused. A group with nothing to say is "all fine", which the page says; nothing here says it.

Every fact is read, never written: a cheap query of this person's own rows, each named by both
its user and its organisation (AGENTS.md, "Whose data is it"). A section that cannot be read says
nothing rather than stopping the others, and the log says why. What only the device knows -
whether it is offline, and what waits in its outbox - the page adds itself (`app/runs.js`).
"""
from __future__ import annotations

import datetime as dt
import logging
import re
import time
from decimal import Decimal

from . import clock, genes

log = logging.getLogger("rouh.anatomy")

#: A card's cap counts as near once this much of it is spent.
NEAR_CAP = Decimal("0.8")
#: How soon an expiry, a renewal or a trial's end is worth saying.
CARD_DAYS = 31
TOKEN_DAYS = 14


def _whose(me) -> dict:
    return {"user_id": str(me.user_id), "org_id": str(me.org_id)}


def _today() -> dt.date:
    return clock.now().date()


def _days(day: dt.date) -> int:
    return (day - _today()).days


def _day_said(day: dt.date) -> str:
    return f"{day.day} {day.strftime('%B')}"


# --- You ------------------------------------------------------------------------------------

def _location(me) -> list[tuple[str, str]]:
    from . import location

    return [] if location.get(me) else [("location", "No location kept")]


# --- Rouh Land Account ---------------------------------------------------------------------

def _your_profile(me) -> list[tuple[str, str]]:
    """Not connected to a rouh.land account, or something wrong between this Rouh and rouh.land."""
    from . import landaccount

    return [("your-profile", said) for said in landaccount.attention(me)]


# --- Connections ----------------------------------------------------------------------------

def _email(me) -> list[tuple[str, str]]:
    from .google_oauth import missing_scopes
    from .models import GoogleConnection, ReadMailbox

    out = []
    row = GoogleConnection.objects.filter(**_whose(me)).first()
    if row is not None:
        if missing_scopes(row.scopes.split()):
            out.append(("email", "Google needs more access"))
        elif row.needs_reconnect:
            out.append(("email", "Google needs connecting again"))
    for box in ReadMailbox.objects.filter(**_whose(me), needs_reconnect=True).order_by("id"):
        out.append(("email", f"{box.email or 'A mailbox'} needs connecting again"))
    return out


def _telegram(me) -> list[tuple[str, str]]:
    from .models import TelegramAccount

    row = TelegramAccount.objects.filter(**_whose(me)).first()
    if row is None or not row.state:
        return []
    if row.state in ("code", "password"):
        return [("telegram", "Telegram sign-in not finished")]
    if row.last_error:
        return [("telegram", "Telegram needs signing in again")]
    return []


def _apple(me) -> list[tuple[str, str]]:
    from .models import AppleConnection

    row = AppleConnection.objects.filter(**_whose(me)).first()
    if row is None:
        return []
    if row.needs_new_password:
        return [("apple", "Apple Contacts needs a new app password")]
    if row.last_error and (row.last_attempt_at or 0) > (row.last_sync_at or 0):
        return [("apple", "Apple Contacts could not sync")]
    return []


_UNTIL = re.compile(r"until (\d{4}-\d{2}-\d{2})")


def _cloudflare(me) -> list[tuple[str, str]]:
    from .models import CloudflareZone

    out = []
    for z in CloudflareZone.objects.filter(org_id=str(me.org_id)).exclude(token_sealed="").order_by("zone"):
        if z.check_ok is False:
            out.append(("cloudflare", f"Cloudflare token for {z.zone} failed its check"))
            continue
        for check in z.checks or []:
            found = _UNTIL.search(str((check or {}).get("said") or ""))
            if not found:
                continue
            try:
                day = dt.date.fromisoformat(found.group(1))
            except ValueError:
                continue
            if _days(day) < 0:
                out.append(("cloudflare", f"Cloudflare token for {z.zone} has expired"))
            elif _days(day) <= TOKEN_DAYS:
                out.append(("cloudflare", f"Cloudflare token for {z.zone} expires {_day_said(day)}"))
    return out


def _slack(me) -> list[tuple[str, str]]:
    """Slack connected and not listening, or missing a token it needs (`rouh/slack.py`)."""
    from .models import SlackConnection

    row = SlackConnection.objects.filter(org_id=str(me.org_id)).first()
    if row is None or not (row.bot_sealed or row.app_sealed or row.user_sealed):
        return []
    if not row.bot_sealed or not row.app_sealed:
        return [("slack", "Slack needs its " + ("bot token" if not row.bot_sealed else "app-level token"))]
    if row.listening == "waiting":
        return [("slack", "Slack is not listening")]
    return []


def _hue(me) -> list[tuple[str, str]]:
    """The Hue sign-in lapsed, or the bridge no longer takes Rouh's key, or signed in and still
    waiting for the bridge's own button (`rouh/hue.py`)."""
    from .models import HueConnection

    row = HueConnection.objects.filter(**_whose(me)).first()
    if row is None:
        return []
    if row.lapsed_at:
        return [("hue", "Philips Hue needs signing in again")]
    if row.access_sealed and not row.key_sealed:
        return [("hue", "Philips Hue needs the bridge's button pressed")]
    return []


def _dreame(me) -> list[tuple[str, str]]:
    """The Dreamehome sign-in lapsed: neither its refresh token nor its password works (`rouh/dreame.py`)."""
    from .models import DreameConnection

    row = DreameConnection.objects.filter(**_whose(me)).first()
    if row is None or not row.lapsed_at:
        return []
    return [("dreame", "The Dreame robot needs signing in again")]


# --- Rouh Land Account, Models ---------------------------------------------------------------

def _models(me) -> list[tuple[str, str]]:
    """A tier none of whose models can be asked here: no provider on its list has a key."""
    from . import modeldefaults
    from .config import config

    now = modeldefaults.Now(str(me.org_id), config)
    return [("models", f"{modeldefaults.TIER_NAMES[t]} has no model with a key here")
            for t in modeldefaults.TIERS if not any(now.can_ask(m) for m in now.tier(t))]


# --- Behaviour ------------------------------------------------------------------------------

def _heartbeat(me) -> list[tuple[str, str]]:
    from . import heartbeat

    out = []
    row = heartbeat.state_of(me)
    if row is not None and row.state == "paused":
        out.append(("heartbeat", "Heartbeat paused"))
    elif row is not None and row.daily_cap and heartbeat.spend(row, heartbeat._midnight()) >= row.daily_cap:
        out.append(("heartbeat", "Heartbeat at its daily cap"))
    asks = len(heartbeat.waiting(me))
    if asks:
        out.append(("heartbeat", f"{asks} heartbeat {'approval' if asks == 1 else 'approvals'} waiting"))
    return out


# --- Money ----------------------------------------------------------------------------------

def _payments(me) -> list[tuple[str, str]]:
    from . import payments
    from .models import PaymentSettings

    out = []
    today = _today()
    for card in payments.cards_of(me):
        name = f"{card.brand or 'Card'} {card.last4}".strip()
        if card.exp_month and card.exp_year:
            year = card.exp_year if card.exp_year > 99 else 2000 + card.exp_year
            last = dt.date(year + card.exp_month // 12, card.exp_month % 12 + 1, 1) - dt.timedelta(days=1)
            if last < today:
                out.append(("payments", f"{name} has expired"))
            elif (last - today).days <= CARD_DAYS:
                out.append(("payments", f"{name} expires {card.exp_month:02d}/{year % 100:02d}"))
        for period, cap in (("day", card.per_day), ("month", card.per_month)):
            if cap is None or Decimal(cap) <= 0:
                continue
            spent = payments.card_spent(me, card, period)
            if spent >= Decimal(cap) * NEAR_CAP:
                part = int(spent * 100 / Decimal(cap))
                out.append(("payments", f"{name} at {part}% of its {'daily' if period == 'day' else 'monthly'} cap"))
    held = PaymentSettings.objects.filter(**_whose(me)).first()
    if held is not None and held.stripe_sealed and not held.hook_sealed:
        out.append(("payments", "Stripe has no webhook"))
    return out


def _signups(me) -> list[tuple[str, str]]:
    from .models import SignupGrant

    now = time.time()
    live = SignupGrant.objects.filter(**_whose(me), withdrawn_at__isnull=True, submitted_at__isnull=True,
                                      expires_at__gt=now).order_by("expires_at")
    return [("signups", f"Sign-up for {g.service} allowed, until "
             + clock.moment(g.expires_at).strftime("%H:%M")) for g in live]


def _services(me) -> list[tuple[str, str]]:
    from . import services

    return [("services", said) for said in services.attention(me)]


# --- Rouh Land Account, Gene Pool -------------------------------------------------------------

def _genes(me) -> list[tuple[str, str]]:
    from .models import GeneRegistry, SharedGene

    out = []
    reg = GeneRegistry.objects.filter(org_id=str(me.org_id)).first()
    if reg is not None and reg.url and reg.error:
        out.append(("gene-pool", "The gene registry could not be read"))
    for g in SharedGene.objects.filter(org_id=str(me.org_id)).order_by("name"):
        if g.blocked or g.state == "blocked":
            out.append(("gene-pool", f"{g.name} was blocked by its registry"))
        elif g.update:
            out.append(("gene-pool", f"{g.name} has an update"))
    return out


# --- Meta -----------------------------------------------------------------------------------

def _changes(me) -> list[tuple[str, str]]:
    """What the protected core has to say: the doctor put the code back, or a change waits."""
    from . import guardface

    if not guardface.here():
        return []
    try:
        status = guardface.ask("status", timeout=3.0)
    except (guardface.Unavailable, guardface.Refused):
        return [("changes", "The protected core does not answer")]
    out = []
    notice, cur = status.get("notice"), ((status.get("code") or {}).get("point") or {})
    if notice and cur.get("n") == notice.get("point"):
        out.append(("changes", "The doctor put Rouh's code back after a change"))
    if status.get("pending"):
        out.append(("changes", "A change waits for a Rouh update"))
    return out


def _birthday(me) -> list[tuple[str, str]]:
    """Rouh profile's line on the board: only when something is wrong or waits, in plain words.
    A free Rouh is fine as it is (4 November 2026), and no key is ever named."""
    from . import birth

    row = birth.current(str(me.org_id))
    if row is None:
        return []
    kind = birth.standing(row)["kind"]
    if kind == "stopped":
        return [("rouh-profile", "rouh.land doesn't recognise this Rouh any more")]
    if kind == "waiting" or (row.pending or {}).get("request"):
        return [("rouh-profile", "Something waits on rouh.land")]
    return []


#: What each section can have to say, by its name in an address. A section with nothing that
#: can need attention (About You, Account, Silos, Voice detection, Morning brief, Heartbeat beats,
#: Shipping, Stats, Trusted contacts, This build) is not here. Offline is the device's, said by
#: the page under Behaviour (`app/runs.js`).
CHECKS = {
    "location": _location,
    "your-profile": _your_profile,
    "email": _email,
    "telegram": _telegram,
    "apple": _apple,
    "cloudflare": _cloudflare,
    "slack": _slack,
    "hue": _hue,
    "dreame": _dreame,
    "models": _models,
    "heartbeat": _heartbeat,
    "payments": _payments,
    "signups": _signups,
    "gene-pool": _genes,
    "changes": _changes,
    "services": _services,
    "rouh-profile": _birthday,
}


def board(me, switch_on=None) -> dict:
    """The groups in order, each with what needs attention in its sections, in theirs."""
    groups = []
    for group in genes.anatomy(switch_on or genes._always):
        facts = []
        for section in group["sections"]:
            check = CHECKS.get(section["id"])
            if check is None:
                continue
            try:
                facts += [{"section": sid, "text": text} for sid, text in check(me)]
            except Exception:
                log.exception("Anatomy could not read %s for %s", section["id"], me.user_id)
        groups.append({"id": group["id"], "name": group["name"], "route": group["route"], "facts": facts})
    return {"groups": groups}
