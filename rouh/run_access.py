"""What the switch opens for each run: the five rouh-open items, per run, and the tripwire.

Petar, 20 November 2026 (task 191): "okay. so the switch should cover all 5 items in the
rouh-open. Build the entire thing now." rouh-open, from his Mac, opens five things for some hours,
for every run in the worker at once: the internet (any public server, any port), GitHub as him,
rouh.land's login, the relay's login and the host's own login. Now the switch on the Permissions
page (`rouh/unrestricted.py`) hands all five to his own runs, and only to them, for as long as it
is Unrestricted.

**How a run is told apart from another** (all runs are one Linux user in the worker):

- the one program knows which run each process belongs to from the kernel's process tree, and
  gives every run a proxy password and a token that only it holds in memory (`one/rundoor.py`,
  `one/peers.py`). A run's requests leave through the program's run door, which adds that run's
  password; a run's calls to Rouh's tools carry its token (`rouh/worker_mcp.py`), which Rouh
  checks with the program (`verify`), so a run cannot name another run (191-01 weak spot 2);
- every few seconds Rouh asks the program for the live runs' password hashes (never the
  passwords), decides for each from its origin (`job_gateway.scope_of`) and the owner's mode
  (`unrestricted.for_job`) whether it is free, and writes that into the keys volume as
  `keyproxy_runs.json`, which the key proxy reads (`guard/rouh_guard/keyproxy.py`). An entry lasts
  `TTL` seconds unless written again, so if Rouh stops, every run falls back to Restricted;
- what a free run gets past the proxy's standing rules: any public server on any port; GitHub as
  the owner, from a standing token in the keys volume; and the ssh of the owner's servers whose
  login is standing (rouh.land, the relay, the host), from `standing_access.json`, which the host's
  `rouh-grant standing` writes. The servers themselves take the jobs' standing key only from the
  office's own addresses, so the proxy is the one way to them, and it lets only free runs through.

**Who never gets any of the five**: a run a contact's mail started, a run doing a trusted
contact's work, a heartbeat beat, a run one of Rouh's processes started, a run with no words of
the owner's behind it, an ended run, a process that left its run, and anything with no password.
The owner's rouh-open grants, while open, still reach the owner's own runs, Restricted or not, and
nothing else's.

**The tripwire** (`trip`): the mode drops to Restricted, and the owner is told once, when

- the mode row says Unrestricted without the seal only the owner's press writes (`seal_ok`), so
  something other than the press wrote it;
- a run shows Rouh a token that is another run's, or none of the program's;
- the key proxy saw a planted credential used (the canary below), or a run that is not the
  owner's try one of the owner's servers;
- the run door saw a run try the program's own control (a device's token from a file).

A trip only ever goes to Restricted, and is written as a flip "by the tripwire" with the reason.
It never turns anything on.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import secrets
import time

log = logging.getLogger("rouh.run_access")

#: The five rouh-open items, in rouh-open's own order.
ITEMS = ("internet", "github", "rouh-land", "relay", "host")
NAMES = {"internet": "Internet", "github": "GitHub", "rouh-land": "rouh.land", "relay": "The relay",
         "host": "The host"}
SAID = {
    "internet": ("Ports 80 and 443 to public servers only, unless a timed grant is open.",
                 "Any public server, on any port. The office network stays closed."),
    "github": ("Public repositories only, unless a timed GitHub grant is open.",
               "GitHub as you, from your standing token, added on the way out; no run sees it."),
    "rouh-land": ("Its login refuses the jobs' key, unless a timed login for it is open.",
                  "rouh.land's ssh, as the jobs' standing key, from the office's addresses only."),
    "relay": ("Its login refuses the jobs' key, unless a timed login for it is open.",
              "The relay's ssh, as the jobs' standing key, from the office's addresses only."),
    "host": ("Its login refuses the jobs' key, unless a timed login for it is open.",
             "The host's ssh as your admin account, with its sudo: root on the machine Rouh runs on."),
}

RUNS_FILE = "keyproxy_runs.json"
STANDING_FILE = "standing_access.json"
GITHUB_STANDING_FILE = "github_standing.json"
#: How long an entry lasts if Rouh stops writing: then every run is Restricted again.
TTL = 90.0
#: How often Rouh writes it, and looks at the trips.
EVERY = 15.0
#: The group the key proxy reads the keys volume as (deploy/stack/compose.yml).
KEYS_GROUP = 10002
#: The decoy Rouh leaves where a run could read it, and whose hash the proxy watches for.
CANARY_FILE = "standing-github.json"


def _keys_dir() -> str:
    return os.environ.get("ROUH_KEYS_DIR", "/keys")


def _read(name: str):
    try:
        with open(os.path.join(_keys_dir(), name), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


# --- what the page shows ----------------------------------------------------------------------


def standing() -> dict:
    """What standing access the host has installed: {"github": login or "", "servers": {item}}."""
    data = _read(STANDING_FILE) or {}
    gh = data.get("github") if isinstance(data.get("github"), dict) else None
    has_token = os.path.exists(os.path.join(_keys_dir(), GITHUB_STANDING_FILE))
    items = {}
    for e in data.get("servers") or []:
        if isinstance(e, dict) and e.get("name") and not e.get("off"):
            items[str(e.get("item") or e["name"])] = e
    return {"github": (gh.get("login") or "yes") if gh and has_token else "", "servers": items}


def items(who) -> list[dict]:
    """[{key, name, restricted, unrestricted, ready, why, until}] for the Permissions page: what
    each of the five does now under each mode, and whether its standing access is installed."""
    from . import unrestricted

    have = standing()
    timed = {g["what"].split(" ", 1)[0].lower(): g["until"] for g in unrestricted.grants_open()}
    logins = {}
    for e in (_read("server_logins.json") or {}).get("logins") or []:
        if isinstance(e, dict) and float(e.get("until") or 0) > time.time():
            logins[str(e.get("name"))] = float(e["until"])
    proxy = proxy_state()
    out = []
    for key in ITEMS:
        # Where each is set up, so a new Rouh says how to make it ready, never "run rouh-open":
        # GitHub on the Keys page, the host by Rouh's own setup on a Linux server, and rouh.land
        # and the relay only on the Rouh that has them among its servers (applies False elsewhere).
        ready, why, fix, applies = True, "", None, True
        if key in ("rouh-land", "relay") and key not in have["servers"]:
            ready, applies, why = False, False, "Not one of this Rouh's servers."
        elif not proxy.get("per_run"):
            ready, why = False, ("The key proxy here does not hand access to one run yet. It comes with the "
                                 "next update of Rouh's protected core, by itself.")
        elif key == "github" and not have["github"]:
            ready, why = False, "Give a GitHub token once, on Keys, under GitHub for your runs."
            fix = {"label": "Add it on Keys", "href": "/anatomy/connections/keys#github_runs"}
        elif key == "host" and key not in have["servers"]:
            ready, why = False, ("This machine's own login is put in by Rouh's setup on a Linux server "
                                 "(rouh update does it). A Mac does not use it.")
        elif key in ("rouh-land", "relay", "host") and key not in have["servers"]:
            ready, why = False, f"{NAMES[key]}'s standing login is not installed yet."
        until = None
        if key == "internet":
            until = timed.get("internet")
        elif key == "github":
            until = timed.get("github")
        else:
            server = have["servers"].get(key) or {}
            until = logins.get(str(server.get("name") or key))
        restricted, free = SAID[key]
        if key == "github" and have["github"] and have["github"] != "yes":
            free = f"GitHub as {have['github']}, from your standing token, added on the way out; no run sees it."
        out.append({"key": key, "name": NAMES[key], "restricted": restricted, "unrestricted": free,
                    "ready": ready, "why": why, "until": until, "applies": applies, "fix": fix})
    return out


_proxy_state: dict = {"at": 0.0, "state": {}}


def proxy_state() -> dict:
    """Whether the running key proxy hands access per run (it answers /trips), cached a minute."""
    if time.time() - _proxy_state["at"] < 60:
        return _proxy_state["state"]
    state = {"per_run": False}
    try:
        import urllib.request

        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(_proxy_url() + "/trips", timeout=3) as r:
            got = json.loads(r.read() or b"{}")
        state = {"per_run": int(got.get("format") or 0) >= 1, "strict": bool(got.get("strict"))}
    except Exception:  # noqa: BLE001 - an old proxy, or none here
        pass
    _proxy_state.update(at=time.time(), state=state)
    return state


def _proxy_url() -> str:
    return (os.environ.get("ROUH_KEYPROXY_URL") or "http://keyproxy:8080").rstrip("/")


# --- a run's token ----------------------------------------------------------------------------

_checked: dict[str, tuple[str, float]] = {}


#: How long after the one program first handed out tokens a run started before it may still
#: call Rouh's tools without one: the runs already going when this was deployed (a run lasts at
#: most six hours, ONE_RUN_LIFETIME).
GRACE = 6 * 3600.0


async def _door_started(client) -> float:
    if _state.get("door_started"):
        return float(_state["door_started"])
    got = await asyncio.wait_for(client.ask("run_doors"), 5)
    _state["door_started"] = float(got.get("started_at") or 0)
    return _state["door_started"]


def _run_started(job: str) -> float:
    from .models import Run

    got = Run.objects.filter(id=job).values_list("started_at", flat=True).first()
    return float(got or 0)


async def verify(job: str, token: str) -> str:
    """Whether a job is the run it names, by its own run token:

    "ok"        the token is this job's own, the one program says
    "other"     it is another run's, or none of the program's: refused, and the tripwire
    "none"      no token, from a run the program could have given one: refused
    "legacy"    no token, from a run started before the program handed out tokens, within
                `GRACE`: served, never Unrestricted
    "noprogram" no one program here at all (a test world, the server): served as before, never
                Unrestricted
    "unchecked" the program could not be asked: refused, said plainly
    """
    from .one_client import OneClient

    token = str(token or "").strip()
    client = OneClient()
    if not client.configured:
        return "noprogram"
    if not token:
        try:
            started = await _door_started(client)
        except Exception:  # noqa: BLE001
            return "unchecked"
        if not started:
            return "legacy"            # a program that hands out no tokens yet
        begun = await asyncio.to_thread(_run_started, job)
        if begun and begun < started and time.time() < started + GRACE:
            return "legacy"
        return "none"
    cached = _checked.get(token)
    if cached and time.time() - cached[1] < 300:
        run = cached[0]
    else:
        try:
            got = await asyncio.wait_for(client.ask("run_token_check", token=token), 5)
        except Exception:  # noqa: BLE001
            log.exception("a run's token could not be checked")
            return "unchecked"
        run = str(got.get("run") or "")
        if run:
            _checked[token] = (run, time.time())
            if len(_checked) > 500:
                _checked.pop(next(iter(_checked)))
    if not run:
        return "other"
    return "ok" if run == str(job or "").strip() else "other"


# --- the runs file ----------------------------------------------------------------------------

_state = {"ack": 0.0, "seen_trip": 0.0, "seen_attempt": 0.0, "canary": "", "task": None,
          "last": {}}


def _canary() -> str:
    """The decoy token, made once and left where a run could find it (`/run/one`)."""
    if _state["canary"]:
        return _state["canary"]
    folder = os.environ.get("ROUH_CANARY_DIR") or os.path.dirname(
        os.environ.get("ROUH_WORKER_KEY_FILE", "") or "/run/one/x")
    path = os.path.join(folder, CANARY_FILE)
    token = ""
    try:
        with open(path, encoding="utf-8") as fh:
            token = str(json.load(fh).get("token") or "")
    except (OSError, ValueError, AttributeError):
        token = ""
    if not token.startswith("ghp_"):
        token = "ghp_" + secrets.token_hex(18)
        try:
            os.makedirs(folder, exist_ok=True)
            tmp = path + ".new"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump({"token": token, "login": "standing", "note": "GitHub as the owner"}, fh)
            os.chmod(tmp, 0o600)
            os.replace(tmp, path)
        except OSError:
            log.warning("the decoy could not be written in %s", folder)
            return ""
    _state["canary"] = token
    return token


def _kind_of(scope) -> str:
    return str(getattr(scope, "kind", "") or "unknown")


async def entries(doors: list[dict]) -> dict:
    """{password hash: entry} for the key proxy, from the program's live runs."""
    from . import job_gateway, unrestricted

    out = {}
    owner_mode = await asyncio.to_thread(unrestricted.owner_mode)
    for d in doors:
        h = str(d.get("hash") or "")
        if not h:
            continue
        if d.get("who") == "program":
            out[h] = {"run": "", "kind": "program", "free": False}
            continue
        run = str(d.get("run") or "")
        scope, _why = await asyncio.to_thread(job_gateway.scope_of, run)
        kind = _kind_of(scope) if scope is not None else "unknown"
        free = False
        if scope is not None and kind == "owner":
            # The door knows the run by the kernel's process tree: as good as its token.
            scope.verified = True
            free = (await unrestricted.for_job(scope)) == ""
        entry = {"run": run, "kind": kind, "free": free}
        if free:
            entry["gets"] = list(ITEMS)
            if owner_mode.until:
                entry["until"] = float(owner_mode.until)
        out[h] = entry
    return out


def write_runs(runs: dict, *, ack: float, canaries: list[str], now: float | None = None) -> str:
    """keyproxy_runs.json, whole or not at all, readable by the key proxy's group only."""
    moment = time.time() if now is None else now
    data = {"format": 1, "written": moment, "until": moment + TTL, "ack": ack,
            "canaries": canaries, "runs": runs}
    path = os.path.join(_keys_dir(), RUNS_FILE)
    tmp = f"{path}.{os.getpid()}.new"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    try:
        os.chown(tmp, -1, KEYS_GROUP)
    except OSError:
        pass
    os.chmod(tmp, 0o640)
    os.replace(tmp, path)
    return path


async def sync_once() -> dict:
    """Ask the program for its runs, write the runs file, read the trips. Never raises."""
    from .one_client import OneClient

    said = {"runs": 0, "free": 0, "trips": 0}
    try:
        client = OneClient()
        doors = []
        attempts = []
        if client.configured:
            got = await asyncio.wait_for(client.ask("run_doors"), 10)
            doors = got.get("doors") or []
            _state["door_started"] = float(got.get("started_at") or 0)
            with_attempts = await asyncio.wait_for(
                client.ask("door_attempts", since=_state["seen_attempt"]), 10)
            attempts = with_attempts.get("attempts") or []
        runs = await entries(doors)
        trips = await asyncio.to_thread(_proxy_trips)
        for t in trips:
            if float(t.get("at") or 0) > _state["seen_trip"]:
                _state["seen_trip"] = float(t["at"])
                said["trips"] += 1
                await asyncio.to_thread(trip, f"the key proxy: {t.get('what')}"
                                        + (f" ({t.get('target')})" if t.get("target") else ""),
                                        by="the key proxy", run=str(t.get("run") or ""))
        for a in attempts:
            _state["seen_attempt"] = max(_state["seen_attempt"], float(a.get("at") or 0))
            run = str(a.get("run") or "")
            kind = "unknown"
            if run:
                from . import job_gateway

                scope, _w = await asyncio.to_thread(job_gateway.scope_of, run)
                kind = _kind_of(scope) if scope else "unknown"
            if kind != "owner":
                said["trips"] += 1
                await asyncio.to_thread(trip, f"the one program: {a.get('what')}", by="the run door",
                                        run=run)
        if trips:
            _state["ack"] = max(_state["ack"], max(float(t.get("at") or 0) for t in trips))
        # Every trip seen is acked only after the mode is Restricted, so nothing is free between.
        if said["trips"]:
            runs = await entries(doors)
        canary = _canary()
        await asyncio.to_thread(write_runs, runs, ack=_state["ack"],
                                canaries=[_hash(canary)] if canary else [])
        said["runs"] = len(runs)
        said["free"] = sum(1 for e in runs.values() if e.get("free"))
        _state["last"] = {"at": time.time(), **said}
    except Exception:  # noqa: BLE001 - written next time; until then entries run out
        log.exception("the runs' access could not be written")
    return said


def _proxy_trips() -> list[dict]:
    try:
        import urllib.request

        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(_proxy_url() + "/trips", timeout=3) as r:
            got = json.loads(r.read() or b"{}")
        return [t for t in got.get("trips") or [] if isinstance(t, dict)]
    except Exception:  # noqa: BLE001 - an old proxy, or none
        return []


async def _loop() -> None:
    while True:
        await sync_once()
        await asyncio.sleep(EVERY)


def start() -> None:
    """Start writing the runs file, in the containers only (where there is a keys volume)."""
    if _state["task"] is not None or not os.path.isdir(_keys_dir()):
        return
    if os.environ.get("ROUH_RUN_ACCESS", "1") == "0":
        return
    _state["task"] = asyncio.get_running_loop().create_task(_loop(), name="run-access")


async def now() -> None:
    """Write it at once (after a flip), so the switch reaches the proxy in a second, not fifteen."""
    if _state["task"] is not None:
        await sync_once()


# --- the seal on the mode, and the tripwire ---------------------------------------------------


def _canonical(org_id: str, user_id: str, mode: str, how: str, until, set_at) -> str:
    return json.dumps([str(org_id), str(user_id), str(mode), str(how or ""),
                       None if until is None else round(float(until), 3), round(float(set_at or 0), 3)])


def seal(org_id: str, user_id: str, mode: str, how: str, until, set_at) -> str:
    """What `unrestricted.flip` writes beside the mode: sealed with this Rouh's own key, which no
    tool, run or model holds, so a mode written any other way has no seal that opens."""
    from . import encryption

    return encryption.box().seal(_canonical(org_id, user_id, mode, how, until, set_at))


def seal_ok(row) -> bool:
    """Whether a mode row's seal is the one its own press wrote."""
    from . import encryption

    sealed = str(getattr(row, "seal", "") or "")
    if not sealed:
        return False
    try:
        return encryption.box().open_(sealed) == _canonical(row.org_id, row.user_id, row.mode,
                                                            row.how, row.until, row.set_at)
    except Exception:  # noqa: BLE001 - not ours is not his
        return False


def trip(reason: str, *, by: str, run: str = "", who=None) -> None:
    """The tripwire: the owner's mode to Restricted now, written down, and the owner told once.
    Only ever goes to Restricted. Never raises."""
    try:
        from django.db import transaction

        from . import notices, telegram, unrestricted
        from .models import PermissionMode, PermissionModeFlip
        from .tenancy import Tenancy

        who = who or telegram.phone_owner(Tenancy())
        if who is None:
            return
        whose = {"user_id": str(who.user_id), "org_id": str(getattr(who, "org_id", "") or "")}
        row = PermissionMode.objects.filter(**whose).first()
        log.warning("tripwire: %s (%s%s)", reason, by, f", run {run}" if run else "")
        if row is not None and row.mode != unrestricted.UNRESTRICTED:
            return
        moment = time.time()
        sealed = seal(whose["org_id"], whose["user_id"], unrestricted.RESTRICTED, "", None, moment)
        with transaction.atomic():
            if row is None:
                # No row is the default, Unrestricted, so going back to Restricted writes one.
                PermissionMode.objects.create(
                    **whose, mode=unrestricted.RESTRICTED, how="", until=None, set_at=moment,
                    set_by=f"the tripwire: {reason}"[:500], seal=sealed)
            else:
                PermissionMode.objects.filter(**whose).update(
                    mode=unrestricted.RESTRICTED, how="", until=None, set_at=moment,
                    set_by=f"the tripwire: {reason}"[:500], seal=sealed)
            PermissionModeFlip.objects.create(**whose, was=unrestricted.UNRESTRICTED,
                                              now=unrestricted.RESTRICTED,
                                              how="", until=None, at=moment, by="the tripwire",
                                              agent=str(reason)[:200])
        notices.post(who, title="Rouh switched back to Restricted",
                     body=f"The tripwire went off: {reason}. Nothing else changed. Look at "
                          "Permissions, and switch Unrestricted on again when you are sure.",
                     link="/anatomy/behaviour/permissions", kind="tripwire", key=f"tripwire:{moment:.0f}",
                     phone_text=f"Rouh is back to Restricted: the tripwire went off ({reason}).")
    except Exception:  # noqa: BLE001 - a tripwire that fails says so in the log, never raises
        log.exception("the tripwire could not switch the mode back (%s)", reason)


def last() -> dict:
    """What the last write said, for server_health."""
    return dict(_state["last"])


__all__ = ["ITEMS", "NAMES", "entries", "items", "last", "now", "proxy_state", "seal", "seal_ok",
           "standing", "start", "sync_once", "trip", "verify", "write_runs"]
