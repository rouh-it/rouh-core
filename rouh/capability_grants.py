"""Grants as data, kept: what the owner gave a trusted contact of a capability, and every use of it.

The rules are `rouh/capabilities.py`'s and CAPABILITIES.md's; this is where they meet the
database. A grant is a `models.CapabilityGrant` row: one contact, one capability at one contract
version, an exact scope, typed limits and a lifetime, its words made by code from those fields,
and the digest of what the owner approved. Nothing here is a model's: a row is written only by the
owner's press (`approve`, `once`, `decline`, `revoke`) or by code that keeps a contract honest
(`suspend_incompatible`).

**Two places hold what a contact may have done, and one reader reads both.** What the contact page
gave - levels, the inbox reach, Clockwork, Memory, Shared task, Your calendar with its ticked
calendars - stays where it is kept and is read as standing grants of the capabilities that name
it (`capabilities.Capability.legacy_grant`, `held_keys`); grants of their own, with scope, limits
and a lifetime, are rows here (`rows_of`). `capabilities.authorize` reads both, and nothing else
decides.

**Uses are claimed before a call runs** (`claim`): in one transaction, under a lock on the grant's
row, with a key made of the case, the tool and its arguments. A retry of the same call finds its
claim done and is told what it did instead of doing it again; a grant allowed once is claimed by
one ask alone, so two calls racing for it get one claim and one refusal; a grant with a limit a day
counts what it did in the last 24 hours.

Every query names the organisation and the owner (`AGENTS.md`, "Whose data is it").
"""
from __future__ import annotations

import logging
import time

from . import capabilities as caps

log = logging.getLogger("rouh.capability_grants")

DAY = 86400.0


def _first(name: str) -> str:
    return (str(name or "").split() or ["them"])[0]


def _view(row) -> dict:
    return {"id": row.id, "contact": row.contact_id, "capability": row.capability,
            "version": row.version, "scope": list(row.scope or []),
            "limits": dict(row.limits or {}), "lifetime": row.lifetime, "until": row.until,
            "expires_at": row.expires_at, "max_uses": row.max_uses, "used": row.used,
            "state": row.state, "digest": row.digest, "wording": row.wording,
            "case_key": row.case_key, "ask_ident": row.ask_ident,
            "approved_by": row.approved_by, "approved_at": row.approved_at,
            "ended_by": row.ended_by, "ended_at": row.ended_at, "reason": row.reason,
            "suspended_reason": row.suspended_reason, "proposed_by": row.proposed_by,
            "replaces": row.replaces_id, "created_at": row.created_at,
            "updated_at": row.updated_at}


def _q(user_id: str, org_id: str):
    from .models import CapabilityGrant

    return CapabilityGrant.objects.filter(user_id=user_id, org_id=org_id)


def rows_of(user_id: str, org_id: str, contact_id, *, every: bool = False) -> list[dict]:
    """A contact's grants of their own, as `capabilities.authorize` reads them: the active ones,
    or with `every` all of them, newest first."""
    if not contact_id:
        return []
    q = _q(user_id, org_id).filter(contact_id=int(contact_id))
    if not every:
        q = q.filter(state__in=(caps.ACTIVE, caps.SUSPENDED))
    return [_view(r) for r in q.order_by("-id")]


def one(user_id: str, org_id: str, grant_id) -> dict | None:
    try:
        row = _q(user_id, org_id).filter(id=int(grant_id)).first()
    except (TypeError, ValueError):
        return None
    return _view(row) if row is not None else None


def used_today(user_id: str, org_id: str, grant_ids, *, now: float | None = None) -> dict:
    """{grant id: calls it covered in the last 24 hours, claimed or done}."""
    from django.db.models import Count

    from .models import CapabilityUse

    ids = [int(i) for i in grant_ids or () if i]
    if not ids:
        return {}
    since = (now or time.time()) - DAY
    got = (CapabilityUse.objects.filter(user_id=user_id, org_id=org_id, grant_id__in=ids,
                                        at__gte=since, state__in=("claimed", "done"))
           .values("grant_id").annotate(n=Count("id")))
    return {g["grant_id"]: g["n"] for g in got}


def held_keys(contact, tree) -> set[str]:
    """What the contact page gives them, as the grant keys capabilities name (`legacy_grant`):
    their levels, inbox, rows of More grants, and "lift:time" when a grant they hold lifts
    committing the owner's time (Your calendar). Exactly what they held before grants were data."""
    if contact is None:
        return set()
    held = set(tree.held(contact))
    if any(tree.lifts(k) & {"time"} for k in held):
        held.add("lift:time")
    return held


def holds_key(contact, key: str, tree, *, rows: list | None = None, lock: dict | None = None,
              found=None) -> bool:
    """Whether the contact holds what a grant key on their page names, there or as an active
    grant of its own of a capability that key gives: what a Clockwork item's work needs."""
    resolved = tree.resolve(key) or key
    if resolved in held_keys(contact, tree):
        return True
    found = found or caps.catalogue()
    lock = lock if lock is not None else caps.read_lock()
    wanted = {c.id for c in found.by_legacy(resolved)}
    for row in rows if rows is not None else (getattr(contact, "cap_grants", None) or []):
        if row.get("capability") in wanted and not caps.row_problem(
                row, found.caps[row["capability"]], lock):
            return True
    return False


# --- the owner's presses ----------------------------------------------------------------------


def _event(row, kind: str, *, by: str, detail: dict | None = None) -> None:
    from .models import CapabilityGrantEvent

    CapabilityGrantEvent.objects.create(user_id=row.user_id, org_id=row.org_id, grant=row,
                                        at=time.time(), by=str(by or ""), kind=kind,
                                        digest=row.digest, detail=detail or {})


def prepared(proposal: dict, contact, *, labels: dict | None = None,
             found=None) -> tuple[dict, list[str]]:
    """A proposal as the owner is shown it: validated, with its words and digest, or what is
    wrong with it. Pure but for the catalogue."""
    found = found or caps.catalogue()
    cap = found.caps.get(str(proposal.get("capability") or ""))
    p = caps.canonical({**proposal, "contact": getattr(contact, "id", 0)})
    wrong = caps.validate(p, cap)
    if wrong:
        return p, wrong
    return {**p, "wording": caps.wording(p, cap, _first(getattr(contact, "name", "")),
                                         labels=labels),
            "digest": caps.digest(p), "name": cap.name, "effects": caps.effects_said(cap),
            "about": cap.about, "reserved": cap.reserved}, []


def _make(who, contact, p: dict, *, state: str, by: str, case_key: str = "",
          ask_ident: str = "", raw: dict | None = None, proposed_by: str = "",
          reason: str = "", replaces=None, labels: dict | None = None):
    from .models import CapabilityGrant

    found = caps.catalogue()
    cap = found.caps[p["capability"]]
    now = time.time()
    once = p["lifetime"] == caps.ONCE
    row = CapabilityGrant.objects.create(
        user_id=who.user_id, org_id=who.org_id, contact_id=int(contact.id),
        capability=cap.id, version=int(p["version"]), scope=list(p["scope"]),
        limits=dict(p["limits"]), lifetime=p["lifetime"], until=p["until"],
        expires_at=caps.ends_at(p["until"]) if p["lifetime"] == caps.UNTIL else None,
        max_uses=1 if once else None, used=0, state=state, digest=caps.digest(p),
        wording=caps.wording(p, cap, _first(contact.name), labels=labels),
        proposal=dict(raw or {}), proposed_by=proposed_by, case_key=case_key,
        ask_ident=ask_ident,
        approved_by=by if state == caps.ACTIVE else "",
        approved_at=now if state == caps.ACTIVE else None,
        ended_by=by if state == caps.REJECTED else "",
        ended_at=now if state == caps.REJECTED else None, reason=reason[:2000],
        replaces=replaces, created_at=now, updated_at=now)
    return row


def approve(who, contact, proposal: dict, *, shown_digest: str, by: str, case_key: str = "",
            ask_ident: str = "", raw: dict | None = None, proposed_by: str = "",
            labels: dict | None = None) -> dict:
    """The owner gives a grant exactly as he was shown it. ValueError when it is not one that can
    be given, when it is not for this contact, or when what he approved is not what it is now:
    the digest he was shown must be the digest of these very fields."""
    from django.db import transaction

    if contact is None or getattr(contact, "implicit", False) or not getattr(contact, "trusted",
                                                                           False):
        raise ValueError("Only somebody on your Trusted contacts, switched on, can be given a "
                         "grant.")
    p, wrong = prepared(proposal, contact, labels=labels)
    if wrong:
        raise ValueError(" ".join(wrong))
    if not shown_digest or shown_digest != p["digest"]:
        raise ValueError("What it would give changed since it was shown to you: look at it again "
                         "and give it as it is now.")
    with transaction.atomic():
        same = _q(who.user_id, who.org_id).select_for_update().filter(
            contact_id=int(contact.id), digest=p["digest"], state=caps.ACTIVE).first()
        if same is not None:
            return {**_view(same), "said": f"{contact.name} has this already: {same.wording}"}
        row = _make(who, contact, p, state=caps.ACTIVE, by=by, case_key=case_key,
                    ask_ident=ask_ident, raw=raw, proposed_by=proposed_by, labels=labels)
        _event(row, "approved", by=by, detail={"case": case_key, "ask": ask_ident,
                                               "wording": row.wording})
    log.info("grant %s of %s given to contact %s by %s", row.id, row.capability, contact.id, by)
    return {**_view(row), "said": f"Given: {row.wording}"}


def once(who, contact, proposal: dict, *, by: str, case_key: str, ask_ident: str,
         raw: dict | None = None, proposed_by: str = "") -> dict:
    """The owner allows one ask once: a grant of the ask's own capability, scope and values,
    lasting once, bound to this case and this ask, so no other message and no other ask can use
    it, and its use is claimed once."""
    from django.db import transaction

    p = caps.canonical({**proposal, "contact": contact.id, "lifetime": caps.ONCE, "until": ""})
    found = caps.catalogue()
    cap = found.caps.get(p["capability"])
    if cap is None:
        raise ValueError("It is not a capability Rouh has.")
    with transaction.atomic():
        same = _q(who.user_id, who.org_id).select_for_update().filter(
            contact_id=int(contact.id), case_key=case_key, ask_ident=ask_ident,
            lifetime=caps.ONCE, state__in=(caps.ACTIVE, caps.SPENT)).first()
        if same is not None:
            return _view(same)
        row = _make(who, contact, p, state=caps.ACTIVE, by=by, case_key=case_key,
                    ask_ident=ask_ident, raw=raw, proposed_by=proposed_by)
        _event(row, "allowed_once", by=by, detail={"case": case_key, "ask": ask_ident})
    return _view(row)


def decline(who, contact, proposal: dict, *, by: str, reason: str = "", case_key: str = "",
            ask_ident: str = "", raw: dict | None = None, proposed_by: str = "") -> dict | None:
    """The owner declines a proposed grant, with his reason when he gave one: kept, so the next
    time the same is proposed his answer and reason are shown beside it (`declined_before`)."""
    if contact is None or not getattr(contact, "id", 0):
        return None
    p, wrong = prepared(proposal, contact)
    if wrong:
        return None
    row = _make(who, contact, p, state=caps.REJECTED, by=by, case_key=case_key,
                ask_ident=ask_ident, raw=raw, proposed_by=proposed_by, reason=reason)
    _event(row, "declined", by=by, detail={"reason": reason[:2000], "case": case_key})
    return _view(row)


def declined_before(user_id: str, org_id: str, contact_id, capability: str) -> dict | None:
    """The last time the owner declined this capability for this contact, with his reason."""
    if not contact_id:
        return None
    row = (_q(user_id, org_id).filter(contact_id=int(contact_id), capability=capability,
                                      state=caps.REJECTED).order_by("-id").first())
    return _view(row) if row is not None else None


def revoke(who, grant_id, *, by: str, reason: str = "") -> dict:
    """Take a grant back, at once: a call checked after this finds it gone."""
    from django.db import transaction

    with transaction.atomic():
        row = _q(who.user_id, who.org_id).select_for_update().filter(id=int(grant_id)).first()
        if row is None:
            raise ValueError("That grant is not there.")
        if row.state not in (caps.ACTIVE, caps.SUSPENDED):
            return {**_view(row), "said": "It was not in force."}
        row.state, row.ended_by, row.ended_at = caps.REVOKED, str(by), time.time()
        row.reason = (reason or "")[:2000]
        row.updated_at = time.time()
        row.save()
        _event(row, "revoked", by=by, detail={"reason": reason[:2000]})
    return {**_view(row), "said": f"Taken back: {row.wording}"}


def suspend_incompatible(org_id: str, *, by: str = "code") -> list[dict]:
    """Every grant in force whose capability changed incompatibly since it was given, or is
    gone, suspended with the reason; and one suspended for a version that is compatible again,
    restored. What changed only its words changes nothing."""
    from django.db import transaction

    from .models import CapabilityGrant

    found, lock = caps.catalogue(), caps.read_lock()
    out = []
    for row in CapabilityGrant.objects.filter(org_id=org_id,
                                              state__in=(caps.ACTIVE, caps.SUSPENDED)):
        cap = found.caps.get(row.capability)
        state, why = caps.version_state(cap, row.version, lock)
        bad = state in ("suspended", "unknown")
        if bad == (row.state == caps.SUSPENDED) and (not bad or row.suspended_reason == why):
            continue
        with transaction.atomic():
            row = CapabilityGrant.objects.select_for_update().get(id=row.id)
            row.state = caps.SUSPENDED if bad else caps.ACTIVE
            row.suspended_reason = why if bad else ""
            row.updated_at = time.time()
            row.save()
            _event(row, "suspended" if bad else "resumed", by=by, detail={"why": why})
        out.append({"id": row.id, "state": row.state, "why": why})
    return out


# --- uses -------------------------------------------------------------------------------------


def claim(who, *, grant_ref: str, grant_id: int = 0, call_key: str, use_key: str = "",
          case_key: str = "", ask_ident: str = "", tool: str = "", capability: str = "",
          contact=None, scope=(), values: dict | None = None) -> tuple[str, str, int]:
    """Claim one call before it runs: ("go", "", use id), ("done", what it did, id) for a call
    already made, ("busy", why, 0) while the same call runs elsewhere, or ("refused", why, 0).

    For a grant of its own the row is locked and checked again now - taken back, ended, used up,
    suspended, its scope and limits, and how many it did today - so nothing given or taken while
    the turn ran is missed, and two racing calls of a grant allowed once get one claim."""
    from django.db import IntegrityError, transaction

    from .models import CapabilityGrant, CapabilityUse

    now = time.time()
    with transaction.atomic():
        row = None
        if grant_id:
            row = (CapabilityGrant.objects.select_for_update()
                   .filter(user_id=who.user_id, org_id=who.org_id, id=int(grant_id)).first())
            if row is None:
                return "refused", "the grant it rested on is not there", 0
        kept = (CapabilityUse.objects.select_for_update()
                .filter(org_id=who.org_id, grant_ref=grant_ref, call_key=call_key).first())
        if kept is not None and kept.state == "done":
            return "done", kept.result, kept.id
        if kept is not None and kept.state == "claimed" and now - kept.at < 900:
            return "busy", "the same call is running already", 0
        if row is not None:
            found, lock = caps.catalogue(), caps.read_lock()
            cap = found.caps.get(row.capability)
            if cap is None:
                return "refused", "its capability is not one Rouh has now", 0
            today = used_today(who.user_id, who.org_id, [row.id], now=now).get(row.id, 0)
            view = _view(row)
            if row.lifetime == caps.ONCE and row.state == caps.SPENT and use_key and \
                    CapabilityUse.objects.filter(grant=row, use_key=use_key,
                                                 state__in=("claimed", "done")).exists():
                # The one ask it was allowed for, making another call of its own work.
                view = {**view, "state": caps.ACTIVE, "used": 0}
            said = caps.row_problem(view, cap, lock, scope=scope, values=values, now=now,
                                    case_key=case_key, ask=ask_ident, used_today=today)
            if said:
                return "refused", f"grant {row.id}: {said}", 0
            if row.lifetime == caps.ONCE:
                others = (CapabilityUse.objects.filter(grant=row, state__in=("claimed", "done"))
                          .exclude(use_key=use_key).exists())
                if others:
                    return "refused", f"grant {row.id}: it was used already", 0
        if kept is not None:
            kept.state, kept.at, kept.use_key = "claimed", now, use_key
            kept.save(update_fields=["state", "at", "use_key"])
            use = kept
        else:
            try:
                with transaction.atomic():
                    use = CapabilityUse.objects.create(
                        user_id=who.user_id, org_id=who.org_id, grant=row, grant_ref=grant_ref,
                        call_key=call_key, use_key=use_key, case_key=case_key,
                        ask_ident=ask_ident, tool=tool, capability=capability,
                        state="claimed", at=now)
            except IntegrityError:
                return "busy", "the same call is running already", 0
        if row is not None and row.lifetime == caps.ONCE:
            row.used = 1
            row.state = caps.SPENT
            row.updated_at = now
            row.save(update_fields=["used", "state", "updated_at"])
            _event(row, "used", by="code", detail={"case": case_key, "tool": tool})
        elif row is not None:
            row.used = (row.used or 0) + 1
            row.updated_at = now
            row.save(update_fields=["used", "updated_at"])
    return "go", "", use.id


def finish(who, use_id: int, *, ok: bool, result: str = "") -> None:
    """A claimed call's outcome. A failed one frees a grant allowed once for its ask again."""
    from django.db import transaction

    from .models import CapabilityGrant, CapabilityUse

    if not use_id:
        return
    with transaction.atomic():
        use = CapabilityUse.objects.select_for_update().filter(org_id=who.org_id,
                                                               id=int(use_id)).first()
        if use is None:
            return
        use.state = "done" if ok else "failed"
        use.result = str(result or "")[:4000]
        use.done_at = time.time()
        use.save(update_fields=["state", "result", "done_at"])
        if not ok and use.grant_id:
            row = CapabilityGrant.objects.select_for_update().get(id=use.grant_id)
            if row.lifetime == caps.ONCE and row.state == caps.SPENT and not \
                    CapabilityUse.objects.filter(grant=row, state="done").exists():
                row.state, row.used = caps.ACTIVE, 0
                row.updated_at = time.time()
                row.save(update_fields=["state", "used", "updated_at"])
                _event(row, "freed", by="code", detail={"why": "the call it was used for "
                                                                "made nothing"})
            elif row.lifetime != caps.ONCE and row.used:
                row.used -= 1
                row.updated_at = time.time()
                row.save(update_fields=["used", "updated_at"])


# --- a turn's work: what it may do, and each call checked again ------------------------------


def _cap_of(found, a):
    """The capability an ask is, by what the reading named or the grant it needs."""
    cap = found.get(a.capability) if a.capability and a.capability != "unsupported" else None
    if cap is None and a.grant and a.grant != "none":
        named = found.by_legacy(a.grant)
        cap = next((c for c in named if c.action == a.action), named[0] if named else None)
    return cap


def turn_authorized(who, case, contact, tree, asks, *, tasks: dict | None = None) -> list[dict]:
    """What the work of a case's start may do, ask by ask, as code authorises it now: the
    capability, the resources it reaches, the limits and values it is held to, and the authority
    behind it - their task level, a grant on their page, a grant of their own, or the owner's
    once - for every ask the start does (allowed, or approved by the owner) and every grant such an
    ask needs as well. `MailTurn.authorized`, which every call is checked against."""
    from . import mail_ledger as ledger

    if contact is None:
        return []
    found, lock = caps.catalogue(), caps.read_lock()
    keys = held_keys(contact, tree)
    rows = list(getattr(contact, "cap_grants", None) or [])
    out: list[dict] = []

    def add(cap, a, v: caps.Verdict | None, *, ref: str = "", scope=None, values=None,
            once_row: dict | None = None) -> None:
        if cap is None:
            return
        entry = {"capability": cap.id, "version": cap.version, "ask": a.ident, "quote": a.quote,
                 "scope": scope, "values": dict(values if values is not None else a.values),
                 "limits": {}, "ref": ref, "grant_id": 0, "once": False, "reason": ""}
        if v is not None:
            entry.update(limits=dict(v.limits), grant_id=v.grant_id, once=v.once,
                         reason=v.reason, version=v.version or cap.version,
                         ref=v.ref + (f":{contact.id}" if v.via in ("held", "level") else ""))
            if v.via in ("row", "once") and cap.resource in caps.SCOPED:
                entry["scope"] = list(v.scope)
        if once_row is not None:
            entry.update(grant_id=once_row["id"], once=True, ref=f"row:{once_row['id']}",
                         reason=f"You allowed it once (grant {once_row['id']}).")
        out.append(entry)

    for a in ledger.to_do(asks):
        cap = _cap_of(found, a)
        if a.choice == ledger.ONCE:
            # The owner's yes for this ask in this message: its own capability, resources and
            # values, through the grant allowed once for it when there is one.
            row = next((r for r in rows if r.get("lifetime") == caps.ONCE
                        and r.get("case_key") == case.key and r.get("ask_ident") == a.ident
                        and r.get("state") in (caps.ACTIVE, caps.SPENT)), None)
            if cap is None and a.hard_limit:
                cap = found.get({"time": "calendar.write"}.get(a.hard_limit, ""))
            scope = ([a.task] if a.task else []) + [x for x in a.scope if x != a.task]
            add(cap, a, None, ref=f"once:{case.key}:{a.ident}",
                scope=scope if cap is not None and cap.resource in caps.SCOPED and scope
                else None, once_row=row)
        elif cap is not None and cap.authority == "task_level":
            scope = ([a.task] if a.task else []) + [x for x in a.scope if x != a.task]
            v = caps.authorize(cap, contact, scope=scope, tasks=tasks or {}, lock=lock)
            if v.ok:
                add(cap, a, v, scope=scope)
        elif cap is not None:
            v = caps.authorize(cap, contact, scope=a.scope, values=a.values, held=keys,
                               rows=rows, tasks=tasks, lock=lock, case_key=case.key, ask=a.ident)
            if v.ok:
                add(cap, a, v, scope=None if v.via == "held" else a.scope or None)
            elif a.status == ledger.APPROVED and a.choice == ledger.GRANT:
                # Given for good a moment ago: read again from what was just written.
                fresh = rows_of(who.user_id, who.org_id, contact.id)
                v = caps.authorize(cap, contact, scope=a.scope, values=a.values, held=keys,
                                   rows=fresh, tasks=tasks, lock=lock, case_key=case.key,
                                   ask=a.ident)
                if v.ok:
                    add(cap, a, v, scope=a.scope or None)
        if a.task and (cap is None or cap.resource != "task"):
            # Work about one of the owner's tasks reads it: through their level on it.
            reader = found.get("tasks.read")
            v = caps.authorize(reader, contact, scope=[a.task], tasks=tasks or {}, lock=lock)
            if reader is not None and (v.ok or a.choice == ledger.ONCE):
                add(reader, a, v if v.ok else None, scope=[a.task],
                    ref=f"once:{case.key}:{a.ident}")
        for other in a.also:
            key = tree.resolve("communicate" if other == "none" else other) or other
            for c in found.by_legacy(key):
                v = caps.authorize(c, contact, held=keys, rows=rows, lock=lock,
                                   case_key=case.key, ask=a.ident)
                if v.ok:
                    add(c, a, v, values={})
    # A clockwork item's own work adds only to a task they may edit, which the tool checks.
    return out


def clockwork_authorized(contact, tree, uses) -> list[dict]:
    """What a Clockwork item's "do" work may do when it runs: the capabilities of the grants it
    uses, each held now on their page or as a grant of their own, and adding to a task they may
    edit, whose level the tool checks itself."""
    found, lock = caps.catalogue(), caps.read_lock()
    keys = held_keys(contact, tree)
    rows = list(getattr(contact, "cap_grants", None) or [])
    out = []
    for key in uses or ():
        key = tree.resolve(key) or key
        for c in found.by_legacy(key):
            v = caps.authorize(c, contact, held=keys, rows=rows, lock=lock)
            if v.ok:
                out.append({"capability": c.id, "version": c.version, "ask": "", "quote": "",
                            "scope": None, "values": {}, "limits": dict(v.limits),
                            "ref": v.ref + (f":{contact.id}" if v.via == "held" else ""),
                            "grant_id": v.grant_id, "once": v.once, "reason": v.reason})
        if key == "shared_task":
            out.append({"capability": "tasks.change", "version": 1, "ask": "", "quote": "",
                        "scope": None, "values": {}, "limits": {},
                        "ref": f"level:tool:{contact.id}", "grant_id": 0, "once": False,
                        "reason": "adding to a task they may edit, which the tool checks"})
    return out


def _turn_who(turn):
    from .tenancy import Identity

    return Identity(user_id=str(turn.user_id), org_id=str(turn.org_id))


def _note(turn, kind: str, **data) -> None:
    """One line of what code decided about a call, on the case's trace (`MailCaseTrace`)."""
    if not getattr(turn, "case_id", 0):
        return
    try:
        from .mail_cases import CaseStore

        CaseStore().trace(turn.user_id, turn.org_id, turn.case_id, kind, mode=turn.mode, **data)
    except Exception:  # noqa: BLE001 - the trace must never stop a call
        log.exception("the authority trace of case %s could not be kept", turn.case_id)


def check_turn_call(turn, name: str, args) -> dict:
    """A call of a case's work, checked again on its actual arguments immediately before it runs:
    {"ok", "reason", "use_id", "done", "result"}. Nothing runs that no capability declares (but a
    tool whose hard limit the owner allowed once for an ask of this turn), that names a resource
    outside what was authorised, a value outside the limits, or whose grant was taken back, ended
    or used up since the turn began; a call already made for this case returns what it did and is
    not made again."""
    from . import mail_turn

    if turn is None or not turn.mode or turn.dry or turn.mode == mail_turn.ASSESS:
        return {"ok": True}
    found = caps.catalogue()
    reads = set(mail_turn.MAY_USE) | {mail_turn.OUTCOME_TOOL, mail_turn.TEAM_FIND}
    chk = caps.check_call(found, name, args or {}, list(turn.authorized or []), reads=reads,
                          limit_of_tool=mail_turn.EFFECTS.get(name, ""),
                          limits=turn.owner_limits)
    shown = {k: v for k, v in (args or {}).items() if k in ("action", "task", "calendar", "to",
                                                             "id", "kind", "path")}
    if not chk.ok:
        _note(turn, "authority", tool=name, args=shown, allowed=False, reason=chk.reason,
              capability=chk.capability)
        return {"ok": False, "reason": (f"Not done: {chk.reason.rstrip('.')}. Rouh's code checks every call "
                                        "against what was allowed for this message; say in "
                                        "case_report what it would take.")}
    if not chk.counts or not turn.case_key:
        if chk.counts:
            _note(turn, "authority", tool=name, args=shown, allowed=True, reason=chk.reason,
                  capability=chk.capability, ref=chk.auth.get("ref", ""))
        return {"ok": True}
    auth = chk.auth
    status, said, use_id = claim(
        _turn_who(turn), grant_ref=str(auth.get("ref") or f"turn:{turn.case_key}"),
        grant_id=int(auth.get("grant_id") or 0), call_key=caps.call_key(turn.case_key, name,
                                                                        args or {}),
        use_key=f"{turn.case_key}:{auth.get('ask') or ''}", case_key=turn.case_key,
        ask_ident=str(auth.get("ask") or ""), tool=name, capability=chk.capability,
        scope=[chk.resource] if chk.resource else [], values=chk.values)
    _note(turn, "authority", tool=name, args=shown, allowed=status in ("go", "done"),
          reason=said or chk.reason, capability=chk.capability, ref=auth.get("ref", ""),
          grant=auth.get("grant_id") or 0, version=auth.get("version") or 0,
          ask=auth.get("ask") or "", claim=status)
    if status == "done":
        return {"ok": True, "done": True,
                "result": f"Done already, for this same message, so not done again: {said}"}
    if status != "go":
        return {"ok": False, "reason": f"Not done: {said}."}
    return {"ok": True, "use_id": use_id}


def reading_model(case) -> dict:
    """The model that read the message, from the request log: what the authority trace names as
    the words' extraction."""
    from .models import LLMRequest

    if not getattr(case, "chat_id", ""):
        return {}
    row = (LLMRequest.objects.filter(user_id=case.user_id, org_id=case.org_id,
                                     session_id=case.chat_id).order_by("-id").first())
    if row is None:
        return {}
    return {"model": row.model, "served_model": row.served_model or row.model,
            "purpose": row.purpose, "request": row.id}


# --- what the owner's pages read --------------------------------------------------------------


def events_of(user_id: str, org_id: str, grant_id) -> list[dict]:
    from .models import CapabilityGrantEvent

    return [{"at": e.at, "by": e.by, "kind": e.kind, "detail": e.detail}
            for e in CapabilityGrantEvent.objects.filter(user_id=user_id, org_id=org_id,
                                                         grant_id=int(grant_id)).order_by("id")]


#: How each state is said on the contact's page.
STATE_WORDS = {caps.ACTIVE: "In force", caps.SUSPENDED: "Suspended", caps.REVOKED: "Taken back",
               caps.SPENT: "Used", caps.REJECTED: "Declined", caps.REPLACED: "Replaced",
               caps.PROPOSED: "Proposed"}


def page_view(who, contact) -> list[dict]:
    """A contact's grants of their own, as their page lists them: words, state, uses, where it
    came from, what it lets Rouh do, and its history; newest first, the ones in force first."""
    from .models import CapabilityUse

    if contact is None or not getattr(contact, "id", 0):
        return []
    found = caps.catalogue()
    rows = rows_of(who.user_id, who.org_id, contact.id, every=True)
    ids = [r["id"] for r in rows]
    uses: dict[int, int] = {}
    for gid in CapabilityUse.objects.filter(user_id=who.user_id, org_id=who.org_id,
                                            grant_id__in=ids, state="done").values_list(
            "grant_id", flat=True):
        uses[gid] = uses.get(gid, 0) + 1
    today = used_today(who.user_id, who.org_id, ids)
    out = []
    for r in rows:
        if r["state"] == caps.REJECTED:
            continue
        cap = found.caps.get(r["capability"])
        now_state = r["state"]
        if now_state == caps.ACTIVE and r["expires_at"] and r["expires_at"] < time.time():
            now_state = "ended"
        out.append({**r, "state_now": now_state,
                    "state_said": "Ended" if now_state == "ended" else
                    STATE_WORDS.get(now_state, now_state),
                    "name": cap.name if cap else r["capability"],
                    "effects": caps.effects_said(cap) if cap else [],
                    "about": cap.about if cap else "",
                    "version_now": cap.version if cap else 0,
                    "uses_done": uses.get(r["id"], 0), "uses_today": today.get(r["id"], 0),
                    "events": events_of(who.user_id, who.org_id, r["id"])})
    out.sort(key=lambda r: (r["state_now"] not in (caps.ACTIVE, caps.SUSPENDED), -r["id"]))
    return out


def migration_status(user_id: str, org_id: str) -> dict:
    """How the grants that were there before grants were data stand now (CAPABILITIES.md,
    Migration): what the contact page gives that a capability now names, what was free text
    with nothing behind it (kept, allowing nothing), and what is in force as data."""
    from . import grants
    from .models import CapabilityGrant, ContactGrant, PageGuest, TrustedContact

    found = caps.catalogue()
    tree = grants.tree(org_id)
    named = {c.legacy_grant for c in found.caps.values() if c.legacy_grant}
    mapped, review = [], []
    for node in tree.live():
        lifted = bool(tree.lifts(node.key) & {"time"})
        if node.key in named or (lifted and "lift:time" in named):
            mapped.append(node.key)
        else:
            review.append(node.key)
    held_review = list(ContactGrant.objects.filter(user_id=user_id, org_id=org_id,
                                                   grant__key__in=review)
                       .values_list("contact__name", "grant__key"))
    contacts = TrustedContact.objects.filter(user_id=user_id, org_id=org_id)
    return {
        "grant_definitions": len(tree.live()), "definitions_mapped": len(mapped),
        "definitions_for_review": review,
        "contact_grant_rows": ContactGrant.objects.filter(user_id=user_id, org_id=org_id).count(),
        "contact_grant_rows_for_review": [{"contact": c, "grant": g} for c, g in held_review],
        "contacts": contacts.count(),
        "contacts_with_levels": sum(1 for c in contacts if c.levels),
        "contacts_with_inbox": sum(1 for c in contacts if c.inbox_scope not in ("", "none")),
        "task_records_untouched": PageGuest.objects.filter(user_id=user_id, org_id=org_id,
                                                           rel__startswith="_task/").count(),
        "grants_as_data": CapabilityGrant.objects.filter(
            user_id=user_id, org_id=org_id).exclude(state=caps.REJECTED).count(),
        "in_force": CapabilityGrant.objects.filter(user_id=user_id, org_id=org_id,
                                                   state=caps.ACTIVE).count(),
        "suspended": CapabilityGrant.objects.filter(user_id=user_id, org_id=org_id,
                                                    state=caps.SUSPENDED).count(),
    }


__all__ = ["approve", "check_turn_call", "claim", "clockwork_authorized", "decline", "declined_before", "events_of", "finish", "held_keys",
           "holds_key", "migration_status", "once", "one", "page_view", "prepared", "revoke",
           "reading_model", "rows_of", "suspend_incompatible", "turn_authorized", "used_today"]
