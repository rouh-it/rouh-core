"""Services: what Rouh and the person pay for again and again, kept to be tracked and stopped.

Petar, 15 October 2026: "Services should have nothing to do with nightly gene creation.
Services are things we purchase and we need to track and maybe unsubscribe. We currently have
none of those and the services item should be in payments of anatomy."

So a service is a `PaidService` row, typed in on Anatomy, Money, Services (`servicespage.js`,
`rouh/web/services.py`), beside Payments: its name, what it is for, what one period costs
(a month, a year or a week), when it renews, when a trial ends, what pays for it, the account it
is under and how to cancel it, and whether it is active, a trial or cancelled. Cancelling is
marked here once it is done; the page never cancels anything by itself. A renewal date that has
passed is rolled on by its period for showing (`next_renewal`), so a monthly plan typed once
keeps saying when it renews next. Anatomy's board says a renewal or a trial's end in the next
week (`attention`).

It is not the nightly feature run's register: that run keeps its own sign-ups in its task's
services.md, and a gene's Card in Mutations names those (`evolution.services_of`).

**Whose.** Every row carries `user_id` and `org_id`, and every query names both. Nothing
secret is kept: the account it is under is a name or an address, never a password.
"""
from __future__ import annotations

import datetime as dt
import re
import time
from decimal import Decimal, InvalidOperation

from . import clock

#: What one amount pays for, as the page names it.
PERIODS = {"month": "a month", "year": "a year", "week": "a week"}
#: What a service can be, as the page names it.
STATES = {"active": "Active", "trial": "Trial", "cancelled": "Cancelled"}
#: How long each text may be.
LONGEST = {"name": 120, "what_for": 300, "paid_with": 120, "account": 200, "cancel_how": 600}
#: How soon a renewal or a trial's end is worth saying on Anatomy's board.
SOON_DAYS = 7


class Refused(ValueError):
    """A service that could not be saved, with what is wrong with each field when it is one's."""

    def __init__(self, message: str = "", fields: dict | None = None):
        self.fields = dict(fields or {})
        super().__init__(message or " ".join(self.fields.values()))


def _model():
    from .models import PaidService

    return PaidService


def _whose(who) -> dict:
    return {"user_id": str(who.user_id), "org_id": str(who.org_id)}


def _today() -> dt.date:
    return clock.now().date()


def _text(value, most: int) -> str:
    # Never an em dash in what Rouh shows (AGENTS.md).
    return " ".join(str(value or "").replace("\u2014", "-").split())[:most]


def _date(value, name: str, wrong: dict) -> dt.date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return dt.date.fromisoformat(text)
    except ValueError:
        wrong[name] = "That is not a date."
        return None


def _amount(value, wrong: dict) -> Decimal | None:
    text = str(value if value is not None else "").strip().replace(",", ".").lstrip("$€£")
    if not text:
        return None
    try:
        got = Decimal(text)
    except InvalidOperation:
        wrong["amount"] = "That is not an amount: type it as 12 or 12.50."
        return None
    if got < 0 or got >= Decimal("1e9"):
        wrong["amount"] = "That amount cannot be right."
        return None
    return got.quantize(Decimal("0.01"))


def _add_months(day: dt.date, months: int) -> dt.date:
    month = day.month - 1 + months
    year = day.year + month // 12
    month = month % 12 + 1
    last = (dt.date(year + month // 12, month % 12 + 1, 1) - dt.timedelta(days=1)).day
    return dt.date(year, month, min(day.day, last))


def next_renewal(row, today: dt.date | None = None) -> dt.date | None:
    """When it renews next: its date, rolled on by its period while that date has passed."""
    day = row.renews_on
    if day is None or row.state == "cancelled":
        return day
    today = today or _today()
    if day >= today:
        return day
    if row.period == "week":
        return day + dt.timedelta(days=7 * -(-(today - day).days // 7))
    # Counted from the first date, never step by step, so the 31st stays the 31st after a
    # February (the 28th there) rather than drifting to the 28th for good.
    step = 12 if row.period == "year" else 1
    months = (today.year - day.year) * 12 + today.month - day.month
    k = max(1, months // step)
    while _add_months(day, k * step) < today:
        k += 1
    return _add_months(day, k * step)


def monthly(row) -> Decimal:
    """What it costs in an average month."""
    if row.amount is None:
        return Decimal(0)
    amount = Decimal(row.amount)
    if row.period == "year":
        return amount / 12
    if row.period == "week":
        return amount * 52 / 12
    return amount


def view(row, today: dt.date | None = None) -> dict:
    today = today or _today()
    renews = next_renewal(row, today)
    return {
        "id": row.id, "name": row.name, "what_for": row.what_for,
        "amount": f"{Decimal(row.amount):.2f}" if row.amount is not None else "",
        "currency": row.currency, "period": row.period, "period_said": PERIODS.get(row.period, ""),
        "renews_on": row.renews_on.isoformat() if row.renews_on else "",
        "renews_next": renews.isoformat() if renews else "",
        "renews_in": (renews - today).days if renews else None,
        "trial_ends": row.trial_ends.isoformat() if row.trial_ends else "",
        "trial_in": (row.trial_ends - today).days if row.trial_ends else None,
        "paid_with": row.paid_with, "account": row.account, "cancel_how": row.cancel_how,
        "state": row.state, "state_said": STATES.get(row.state, row.state),
        "cancelled_at": row.cancelled_at,
    }


def _cards(who) -> list[str]:
    """The vault's cards as a person names them, to pick what pays for a service."""
    try:
        from . import payments

        return [f"{c.brand} ending {c.last4}" for c in payments.cards_of(who)]
    except Exception:  # noqa: BLE001 - only suggestions; the field takes any words
        return []


def listing(who) -> dict:
    """Everything the Services page shows: every service, active ones first, and what the
    active ones cost a month in all, by currency."""
    today = _today()
    rows = list(_model().objects.filter(**_whose(who)).order_by("name", "id"))
    order = {"trial": 0, "active": 1, "cancelled": 2}
    rows.sort(key=lambda r: (order.get(r.state, 3), r.name.lower(), r.id))
    totals: dict[str, Decimal] = {}
    for r in rows:
        if r.state == "active" and r.amount is not None:
            totals[r.currency] = totals.get(r.currency, Decimal(0)) + monthly(r)
    return {
        "services": [view(r, today) for r in rows],
        "monthly": [{"currency": c, "amount": f"{a.quantize(Decimal('0.01')):.2f}"}
                    for c, a in sorted(totals.items())],
        "periods": [{"id": k, "name": v} for k, v in PERIODS.items()],
        "states": [{"id": k, "name": v} for k, v in STATES.items()],
        "cards": _cards(who),
    }


def _one(who, ident):
    try:
        ident = int(ident)
    except (TypeError, ValueError):
        return None
    return _model().objects.filter(**_whose(who), id=ident).first()


def save(who, body: dict):
    """A service added, or one of theirs changed. Every field that is wrong is said at once."""
    body = body if isinstance(body, dict) else {}
    wrong: dict = {}
    fields = {k: _text(body.get(k), n) for k, n in LONGEST.items()}
    if not fields["name"]:
        wrong["name"] = "Name the service, such as Figma or Google Workspace."
    amount = _amount(body.get("amount"), wrong)
    currency = _text(body.get("currency"), 3).upper() or "USD"
    if not re.fullmatch(r"[A-Z]{3}", currency):
        wrong["currency"] = "Three letters, such as USD, EUR or BGN."
    period = str(body.get("period") or "month")
    if period not in PERIODS:
        wrong["period"] = "A month, a year or a week."
    state = str(body.get("state") or "active")
    if state not in STATES:
        wrong["state"] = "Active, Trial or Cancelled."
    renews_on = _date(body.get("renews_on"), "renews_on", wrong)
    trial_ends = _date(body.get("trial_ends"), "trial_ends", wrong)
    row = None
    if body.get("id") not in (None, ""):
        row = _one(who, body.get("id"))
        if row is None:
            raise Refused("That service is not in the list.")
    if wrong:
        raise Refused(fields=wrong)
    now = time.time()
    values = dict(fields, amount=amount, currency=currency, period=period, state=state,
                  renews_on=renews_on, trial_ends=trial_ends, updated_at=now)
    if row is None:
        return _model().objects.create(**_whose(who), created_at=now,
                                       cancelled_at=now if state == "cancelled" else None, **values)
    if state == "cancelled" and row.state != "cancelled":
        values["cancelled_at"] = now
    elif state != "cancelled":
        values["cancelled_at"] = None
    _model().objects.filter(**_whose(who), id=row.id).update(**values)
    return _one(who, row.id)


def set_state(who, ident, state: str):
    """A service marked cancelled, once it has been, or active again."""
    if state not in STATES:
        raise Refused("A service is active, a trial or cancelled.")
    row = _one(who, ident)
    if row is None:
        raise Refused("That service is not in the list.")
    now = time.time()
    _model().objects.filter(**_whose(who), id=row.id).update(
        state=state, updated_at=now, cancelled_at=now if state == "cancelled" else None)
    return _one(who, row.id)


def delete(who, ident):
    """A service taken out of the list altogether, as if it had never been typed in."""
    row = _one(who, ident)
    if row is None:
        raise Refused("That service is not in the list.")
    _model().objects.filter(**_whose(who), id=row.id).delete()
    return row


def _day_said(day: dt.date) -> str:
    return f"{day.day} {day.strftime('%B')}"


def attention(who) -> list[str]:
    """What Anatomy's board says: a trial ending or a service renewing in the next week."""
    today = _today()
    out = []
    for r in _model().objects.filter(**_whose(who)).exclude(state="cancelled").order_by("name"):
        if r.state == "trial" and r.trial_ends and 0 <= (r.trial_ends - today).days <= SOON_DAYS:
            out.append(f"{r.name}'s trial ends {_day_said(r.trial_ends)}")
        renews = next_renewal(r, today)
        if renews and 0 <= (renews - today).days <= SOON_DAYS:
            out.append(f"{r.name} renews {_day_said(renews)}")
    return out
