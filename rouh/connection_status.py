"""Every connection of one person, as it stands, and a test of one: what `connection_status` says.

Petar, 19 November 2026: when one of Rouh's own connections stops working, Rouh should be able to
say why from its own chat turn, without the person's help. So this reads, in the core, each of the
person's connections - iCloud contacts, Google and the mailboxes read with it, Slack, Hue, the Dreame
robot, Telegram, Cloudflare - and says its state, when it was last tried and last worked, its last
error, when it last failed and what the service said then (`connection_incidents`), and where it was
found (the CardDAV addresses iCloud gave). Never a credential: every field is picked here by name,
and a sealed value is never opened, only whether there is one.

`test` asks the service once with what is kept (`ContactDesk.test`, for iCloud a PROPFIND on the
principal) and says what came back. It changes nothing, except that with `reconnect` and an answer
that accepts, a connection marked as needing a new password is cleared.

Every query names the person, and the organisation (AGENTS.md, "Whose data is it").
"""
from __future__ import annotations

import logging

from . import connection_incidents as incidents

log = logging.getLogger("rouh.connections")

#: The connections a test can be run on now, by key.
TESTABLE = ("apple_contacts",)


def _when(at) -> str:
    from . import clock

    return clock.stamp(at) if at else ""


def _incidents(key: str, who, many: int) -> dict:
    found = incidents.recent(key, who.user_id, who.org_id, many) if many else []
    newest = found[0] if found else incidents.latest(key, who.user_id, who.org_id)
    out = {"last_failure_at": _when(newest["at"]) if newest else "",
           "last_failure": ({k: newest[k] for k in ("part", "method", "host", "path", "status",
                                                    "headers", "body", "outcome")}
                            if newest else None)}
    if many:
        out["incidents"] = [{**{k: r[k] for k in ("part", "method", "host", "path", "status",
                                                  "headers", "outcome", "note")},
                             "at": _when(r["at"])} for r in found]
    trouble = incidents.trouble(key, who.user_id, who.org_id)
    if trouble is not None:
        out["refusals_running"] = {"since": _when(trouble.first_at), "last": _when(trouble.last_at),
                                   "count": trouble.failures}
    return out


def _apple(who, many: int) -> list[dict]:
    from .models import AppleConnection

    row = AppleConnection.objects.filter(user_id=str(who.user_id), org_id=str(who.org_id)).first()
    if row is None:
        return []
    trouble = incidents.trouble("apple_contacts", who.user_id, who.org_id)
    state = ("needs_new_password" if row.needs_new_password
             else "suspected: refused, retrying" if trouble is not None
             else "connected")
    return [{
        "connection": "apple_contacts", "name": "iCloud contacts (CardDAV)", "state": state,
        "connected": True, "account": row.apple_id,
        "needs_new_password": bool(row.needs_new_password),
        "connected_at": _when(row.connected_at), "last_attempt_at": _when(row.last_attempt_at),
        "last_synced": _when(row.last_sync_at), "last_sync_changed": row.last_sync_changed,
        "last_error": row.last_error or "",
        "discovered": {"principal": row.principal_url, "home": row.home_url, "book": row.book_url},
        "testable": True,
        **_incidents("apple_contacts", who, many),
    }]


def _google(who, many: int) -> list[dict]:
    from .models import GoogleConnection, ReadMailbox

    out = []
    row = GoogleConnection.objects.filter(user_id=str(who.user_id), org_id=str(who.org_id)).first()
    if row is not None:
        out.append({
            "connection": "google", "name": "Google (Gmail, Calendar, Drive)",
            "state": "needs_reconnect" if row.needs_reconnect else "connected",
            "connected": True, "account": row.google_email,
            "needs_reconnect": bool(row.needs_reconnect), "last_error": row.trouble or "",
            "connected_at": _when(row.connected_at),
            "access_token_expires_at": _when(row.expires_at),
            "scopes": len((row.scopes or "").split()),
            **_incidents("google", who, many),
        })
    for box in ReadMailbox.objects.filter(user_id=str(who.user_id), org_id=str(who.org_id)).order_by("id"):
        out.append({
            "connection": f"mailbox:{box.email}", "name": f"Mailbox {box.email}",
            "state": "needs_reconnect" if box.needs_reconnect else "connected", "connected": True,
            "account": box.email, "needs_reconnect": bool(box.needs_reconnect),
            "last_error": box.trouble or "", "connected_at": _when(box.connected_at),
            "last_scanned": _when(box.scanned_at),
            **_incidents(f"mailbox:{box.email}", who, many),
        })
    return out


def _slack(who, many: int) -> list[dict]:
    from .models import SlackConnection

    row = SlackConnection.objects.filter(org_id=str(who.org_id)).first()
    if row is None or not (row.bot_sealed or row.app_sealed or row.user_sealed):
        return []
    missing = [n for n, v in (("bot token", row.bot_sealed), ("app-level token", row.app_sealed)) if not v]
    return [{
        "connection": "slack", "name": f"Slack {row.team_name or ''}".strip(),
        "state": ("missing " + " and ".join(missing)) if missing else (row.listening or "connected"),
        "connected": True, "account": row.team_name or row.team_id,
        "listening": row.listening, "last_error": row.listening_said or "",
        "connected_at": _when(row.connected_at), "last_checked": _when(row.checked_at),
        "last_heard": _when(row.heard_at),
        **_incidents("slack", who, many),
    }]


def _hue(who, many: int) -> list[dict]:
    from .models import HueConnection

    row = HueConnection.objects.filter(user_id=str(who.user_id), org_id=str(who.org_id)).first()
    if row is None:
        return []
    return [{
        "connection": "hue", "name": "Philips Hue",
        "state": ("lapsed" if row.lapsed_at else "waiting for the bridge's button"
                  if row.access_sealed and not row.key_sealed else "connected"),
        "connected": True, "account": row.bridge_name or row.bridge_id,
        "lapsed_at": _when(row.lapsed_at), "last_error": row.lapsed_said or "",
        "connected_at": _when(row.connected_at), "last_reached": _when(row.reached_at),
        "last_refreshed": _when(row.refreshed_at),
        **_incidents("hue", who, many),
    }]


def _dreame(who, many: int) -> list[dict]:
    from .models import DreameConnection

    row = DreameConnection.objects.filter(user_id=str(who.user_id), org_id=str(who.org_id)).first()
    if row is None:
        return []
    return [{
        "connection": "dreame", "name": "Dreame robot vacuum",
        "state": "lapsed" if row.lapsed_at else "connected", "connected": True,
        "account": row.robot_name or row.model, "lapsed_at": _when(row.lapsed_at),
        "last_error": row.lapsed_said or "", "connected_at": _when(row.connected_at),
        "last_reached": _when(row.reached_at),
        **_incidents("dreame", who, many),
    }]


def _telegram(who, many: int) -> list[dict]:
    from .models import TelegramAccount

    row = TelegramAccount.objects.filter(user_id=str(who.user_id), org_id=str(who.org_id)).first()
    if row is None or not row.state:
        return []
    return [{
        "connection": "telegram", "name": "Telegram (your own account)",
        "state": ("sign-in not finished" if row.state in ("code", "password")
                  else "needs signing in again" if row.last_error else row.state),
        "connected": True, "account": row.name or row.phone_hint,
        "last_error": row.last_error or "", "connected_at": _when(row.connected_at),
        "updated_at": _when(row.updated_at),
        **_incidents("telegram", who, many),
    }]


def _cloudflare(who, many: int) -> list[dict]:
    from .models import CloudflareZone

    out = []
    for z in CloudflareZone.objects.filter(org_id=str(who.org_id)).exclude(token_sealed="").order_by("zone"):
        out.append({
            "connection": f"cloudflare:{z.zone}", "name": f"Cloudflare {z.zone}",
            "state": "failed its check" if z.check_ok is False else "connected", "connected": True,
            "account": z.zone, "last_checked": _when(z.checked_at),
            "last_error": "" if z.check_ok is not False else "the kept token failed its check",
        })
    return out


READERS = (_apple, _google, _slack, _hue, _dreame, _telegram, _cloudflare)


def connections(who, *, incidents_each: int = 0, only: str = "") -> list[dict]:
    """Every connection of this person, each read on its own: one that cannot be read says so."""
    out = []
    for reader in READERS:
        try:
            out += reader(who, max(0, min(int(incidents_each or 0), incidents.KEEP)))
        except Exception as exc:  # noqa: BLE001 - one connection never hides the others
            log.exception("connection_status: %s could not be read", reader.__name__)
            out.append({"connection": reader.__name__.strip("_"), "state": "could not be read",
                        "last_error": type(exc).__name__})
    if only:
        key = only.strip().lower()
        out = [c for c in out if c["connection"] == key or c["connection"].startswith(key + ":")
               or key in (c.get("name") or "").lower()]
    return out


def said(found: list[dict]) -> str:
    import json

    if not found:
        return "No connection matches. Nothing is connected, or the name is not one of them."
    head = "; ".join(f"{c.get('name') or c['connection']}: {c.get('state')}" for c in found)
    return (head + ".\n\n" + json.dumps(found, ensure_ascii=False, indent=1)
            + "\n\nTimes are the person's clock. No credential is ever shown here.")


async def test(who, connection: str, *, reconnect: bool = False, contacts=None) -> dict:
    """One read-only request with the kept credential, and what came back."""
    key = (connection or "").strip().lower()
    if key in ("apple", "icloud", "contacts", "apple_contacts", "icloud contacts"):
        if contacts is None:
            return {"tested": False, "said": "Apple Contacts are switched off on this server."}
        return await contacts.test(who, reconnect=reconnect)
    return {"tested": False, "connection": key,
            "said": f"A test of {key or 'that connection'} is not built yet; only "
                    f"{', '.join(TESTABLE)} can be tested now. Its incidents and read_rouh_log "
                    "say what it last met."}


__all__ = ["TESTABLE", "connections", "said", "test"]
