"""What a connection's service said when it refused Rouh, kept at that moment, and when to believe it.

Petar, 19 November 2026. iCloud contacts were marked `needs_new_password` after one 401, while
the app-specific password was still valid in his Apple account, and nothing could say why
afterwards: the chat could not read the core's log, a job could not reach the core at all, and
the one line the log had said only that iCloud "stopped accepting" the password. So:

**The evidence, kept as it happened** (`record`). Each refusal of a connection's credentials is a
row of `connection_incidents` and a line in the log: when, which connection, which part of Rouh
asked (sync, save, discover, photo fetch, test), the method, the host and the path (never a
query string, which is where a key would be), the status, the headers that say why (the
`WANTED` ones: WWW-Authenticate, Retry-After and Apple's own x-apple-*), and the first `BODY`
characters of what came back, scrubbed. The last `KEEP` of each connection are kept. Never a
credential: nothing here is handed one, and everything is put through `rouh_log.redact` besides.

**One refusal is not a verdict** (`failed`, `ok`). A connection's run of refusals is one row of
`connection_trouble`, gone at its first success. A sync marks a connection dead only once its
credentials have been refused at least `PERSIST` (15 minutes) after the first refusal, which is
two sync cycles apart; until then it is only suspected, and said as "refused us at 14:05,
retrying".

Every query names the person and the organisation (AGENTS.md, "Whose data is it").
"""
from __future__ import annotations

import json
import logging
import time
import urllib.parse
from dataclasses import dataclass, field

log = logging.getLogger("rouh.connections")

#: How long refusals have to go on before a connection is believed dead: two sync cycles apart.
PERSIST = 15 * 60
#: How many incidents of one connection are kept.
KEEP = 50
#: How much of the body is kept.
BODY = 500
#: The headers kept, besides any that start with x-apple-.
WANTED = ("www-authenticate", "retry-after")
WANTED_PREFIXES = ("x-apple-",)

#: The parts of Rouh that make requests, as an incident names them.
SYNC, SAVE, DELETE, DISCOVER, PHOTO, TEST, CALL, REFRESH = (
    "sync", "save", "delete", "discover", "photo fetch", "test", "call", "token refresh")


@dataclass
class Evidence:
    """One request and what came back, with nothing secret in it."""

    method: str = ""
    host: str = ""
    path: str = ""
    status: int = 0
    headers: dict = field(default_factory=dict)
    body: str = ""

    def as_dict(self) -> dict:
        return {"method": self.method, "host": self.host, "path": self.path,
                "status": self.status, "headers": dict(self.headers), "body": self.body}


def kept_headers(headers) -> dict:
    """Only the headers that say why, each scrubbed."""
    from .rouh_log import redact

    out = {}
    for name, value in (dict(headers or {})).items():
        low = str(name).lower()
        if low in WANTED or low.startswith(WANTED_PREFIXES):
            out[low] = redact(str(value))[:500]
    return out


def evidence(method: str, url: str, status: int = 0, headers=None, body: str = "") -> Evidence:
    """The evidence of one request: the host and the path, never the query."""
    from .rouh_log import redact

    parts = urllib.parse.urlsplit(str(url or ""))
    return Evidence(method=str(method or "").upper(), host=(parts.hostname or "").lower(),
                    path=parts.path or "/", status=int(status or 0),
                    headers=kept_headers(headers), body=redact(str(body or ""))[:BODY])


def of_response(response) -> Evidence:
    """The evidence of an httpx (or requests) response."""
    request = getattr(response, "request", None)
    try:
        text = response.text
    except Exception:  # noqa: BLE001 - a body that cannot be read as text
        text = ""
    return evidence(getattr(request, "method", "") or "", str(getattr(request, "url", "") or ""),
                    getattr(response, "status_code", 0), getattr(response, "headers", {}), text)


def said_at(at: float) -> str:
    """'14:05 on 19 November', on the person's clock."""
    from . import clock

    moment = clock.moment(at)
    if moment is None:
        return "an unknown time"
    return f"{moment.strftime('%H:%M')} on {moment.day} {moment.strftime('%B')}"


def request_said(row: dict | None) -> str:
    """'PROPFIND p52-contacts.icloud.com/123/carddavhome/ answered 401'."""
    if not row:
        return ""
    where = f"{row.get('host') or ''}{row.get('path') or ''}"
    out = f"{row.get('method') or 'a request'} {where}".strip()
    if row.get("status"):
        out += f" answered {row['status']}"
    headers = row.get("headers") or {}
    if headers:
        out += " (" + "; ".join(f"{k}: {v}" for k, v in headers.items()) + ")"
    return out


# --- the incidents ------------------------------------------------------------------------------


def record(connection: str, user_id: str, org_id: str, *, part: str, what: Evidence | dict | None,
           outcome: str = "", note: str = "", at: float | None = None) -> dict:
    """Keep one refusal, in the table and in the log, and hand it back as kept. Never raises: the
    evidence is never what stops the work it is about."""
    from .rouh_log import redact

    if isinstance(what, Evidence):
        what = what.as_dict()
    what = dict(what or {})
    row = {"connection": str(connection), "at": float(at or time.time()), "part": str(part or ""),
           "method": str(what.get("method") or ""), "host": str(what.get("host") or ""),
           "path": str(what.get("path") or ""), "status": int(what.get("status") or 0),
           "headers": kept_headers(what.get("headers") or {}),
           "body": redact(str(what.get("body") or ""))[:BODY],
           "outcome": str(outcome or ""), "note": redact(str(note or ""))[:500]}
    try:
        log.warning("connection incident: user %s, %s", user_id,
                    json.dumps(row, ensure_ascii=False, sort_keys=True))
    except Exception:  # noqa: BLE001
        pass
    if not user_id or not org_id:
        return row
    try:
        from .models import ConnectionIncident

        made = ConnectionIncident.objects.create(user_id=str(user_id), org_id=str(org_id), **row)
        row["id"] = made.id
        old = list(ConnectionIncident.objects.filter(user_id=str(user_id), org_id=str(org_id),
                                                     connection=str(connection))
                   .order_by("-at", "-id").values_list("id", flat=True)[KEEP:])
        if old:
            ConnectionIncident.objects.filter(user_id=str(user_id), org_id=str(org_id),
                                              id__in=old).delete()
    except Exception:  # noqa: BLE001 - kept in the log line above, whatever the table did
        log.exception("connection incident for %s could not be kept in the table", connection)
    return row


def _as_dict(row) -> dict:
    return {"id": row.id, "connection": row.connection, "at": row.at, "part": row.part,
            "method": row.method, "host": row.host, "path": row.path, "status": row.status,
            "headers": row.headers or {}, "body": row.body, "outcome": row.outcome,
            "note": row.note}


def recent(connection: str, user_id: str, org_id: str, limit: int = 5) -> list[dict]:
    """This connection's newest incidents, newest first."""
    from .models import ConnectionIncident

    if not user_id or not org_id:
        return []
    rows = (ConnectionIncident.objects.filter(user_id=str(user_id), org_id=str(org_id),
                                              connection=str(connection))
            .order_by("-at", "-id")[:max(1, min(int(limit or 5), KEEP))])
    return [_as_dict(r) for r in rows]


def first_since(connection: str, user_id: str, org_id: str, since: float,
                parts: tuple = ()) -> dict | None:
    """The oldest incident of this connection at or after `since`, of one of `parts` if given."""
    from .models import ConnectionIncident

    if not user_id or not org_id:
        return None
    rows = ConnectionIncident.objects.filter(user_id=str(user_id), org_id=str(org_id),
                                             connection=str(connection), at__gte=float(since))
    if parts:
        rows = rows.filter(part__in=list(parts))
    row = rows.order_by("at", "id").first()
    return _as_dict(row) if row is not None else None


def latest(connection: str, user_id: str, org_id: str) -> dict | None:
    found = recent(connection, user_id, org_id, 1)
    return found[0] if found else None


# --- one refusal is not a verdict ---------------------------------------------------------------


@dataclass
class Trouble:
    """A connection's run of refusals so far."""

    first_at: float
    last_at: float
    failures: int
    first_part: str = ""
    last_part: str = ""

    @property
    def persistent(self) -> bool:
        """Refused again at least `PERSIST` after the first refusal: two sync cycles apart."""
        return self.failures >= 2 and self.last_at - self.first_at >= PERSIST

    def as_dict(self) -> dict:
        return {"first_at": self.first_at, "last_at": self.last_at, "failures": self.failures,
                "first_part": self.first_part, "last_part": self.last_part,
                "persistent": self.persistent}


#: A run of refusals with nothing for this long is over: the next refusal starts a new one. For a
#: connection whose every success is not written down (Google's calls, `troubled`).
STALE = 2 * 3600

#: The connections this process has seen refused and not yet seen work, so a success clears them
#: without a query for every call that works.
_TROUBLED: set = set()


def troubled(connection: str, user_id: str, org_id: str) -> bool:
    return (str(connection), str(user_id), str(org_id)) in _TROUBLED


def failed(connection: str, user_id: str, org_id: str, part: str = "",
           at: float | None = None) -> Trouble:
    """One more refusal of this connection, counted: the run of them so far."""
    from django.db import transaction

    from .models import ConnectionTrouble

    now = float(at or time.time())
    _TROUBLED.add((str(connection), str(user_id), str(org_id)))
    with transaction.atomic():
        row = (ConnectionTrouble.objects.select_for_update()
               .filter(user_id=str(user_id), org_id=str(org_id), connection=str(connection))
               .first())
        if row is not None and now - row.last_at > STALE:
            row.delete()
            row = None
        if row is None:
            row = ConnectionTrouble.objects.create(
                user_id=str(user_id), org_id=str(org_id), connection=str(connection),
                first_at=now, last_at=now, failures=1, first_part=part, last_part=part)
        else:
            row.last_at, row.failures, row.last_part = now, row.failures + 1, part
            row.save(update_fields=["last_at", "failures", "last_part"])
    return Trouble(row.first_at, row.last_at, row.failures, row.first_part, row.last_part)


def ok(connection: str, user_id: str, org_id: str) -> None:
    """The connection worked: whatever run of refusals it had is over."""
    from .models import ConnectionTrouble

    _TROUBLED.discard((str(connection), str(user_id), str(org_id)))
    if user_id and org_id:
        ConnectionTrouble.objects.filter(user_id=str(user_id), org_id=str(org_id),
                                         connection=str(connection)).delete()


def trouble(connection: str, user_id: str, org_id: str) -> Trouble | None:
    from .models import ConnectionTrouble

    if not user_id or not org_id:
        return None
    row = ConnectionTrouble.objects.filter(user_id=str(user_id), org_id=str(org_id),
                                           connection=str(connection)).first()
    if row is None:
        return None
    return Trouble(row.first_at, row.last_at, row.failures, row.first_part, row.last_part)


__all__ = ["DELETE", "DISCOVER", "Evidence", "KEEP", "PERSIST", "PHOTO", "SAVE", "SYNC", "TEST",
           "Trouble", "evidence", "failed", "first_since", "latest", "troubled", "of_response", "ok", "recent", "record",
           "request_said", "said_at", "trouble"]
