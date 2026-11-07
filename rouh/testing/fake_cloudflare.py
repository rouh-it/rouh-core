"""A stand-in for Cloudflare's API, so Settings, Cloudflare can be driven with nothing real.

The same idea as `fake_stripe.py`: a real HTTP server in front of the real client
(`rouh/cloudflare.py`), so what a check proves is what went over the wire. It speaks
enough of Cloudflare's v4 API, in its shapes, for what Rouh asks of a token:

- writing (task 165): ``POST /zones/<id>/dns_records``, ``PUT /zones/<id>/dns_records/<record>``
  (refused beside a CNAME of the same name, as Cloudflare does), ``GET /zones/<id>``, any
  ``GET /zones/<id>/settings/<key>``, ``PATCH /zones/<id>/settings/<key>`` and ``POST /certificates``;
- ``GET /user/tokens/verify``, ``GET /zones`` (and ``?name=``), and per zone
  ``GET /zones/<id>/dns_records``, ``GET /zones/<id>/settings/ssl``,
  ``GET /certificates?zone_id=<id>`` (the certificates made here for its names) and ``POST /zones/<id>/purge_cache``, each
  refused with Cloudflare's own ``10000 Authentication error`` when the token was not
  made with that permission.

Zone Settings comes as two permissions here, as at Cloudflare: ``settings`` (Read) lets a
token read a setting, and ``settings_edit`` (Edit, which includes Read) also lets it PATCH one;
a PATCH from a token with Read only is refused with ``9109 Unauthorized to access requested
resource``, HTTP 403, as Cloudflare refuses it. The values are kept per zone in `SETTINGS`, so
a PATCH really changes them, and its body is in ``GET /_calls``.

Its two zones are the two an installation's organisation starts with
(`cloudflare.STARTING`), so a token the world carries over finds its own zone here, or
example.com and example.org where the installation starts with none. The tokens it
knows are `TOKENS`: one for the first zone with everything, one for the second without
Cache Purge, one for the second without SSL and Certificates, one for the second with Zone
Settings Read only (as rouh.land's was on 2 November 2026), and one that sees both. Any other is refused with ``1000 Invalid API Token``, as Cloudflare does.

Two more are account tokens, made under Manage Account, API Tokens, as Petar made rouh.page's on
27 October 2026: Cloudflare answers ``/user/tokens/verify`` for one with ``1000 Invalid API Token``
and verifies it only at ``GET /accounts/<account id>/tokens/verify``. One has every permission on
the second zone; the other has all but Zone - Read, so it cannot find its zone by name and is
only found active with the account's id given. A third has no Zone Settings permission at
all, as rouh.page's first account token had: reading the SSL setting is refused.
Email Routing (2 November 2026): ``GET``/``POST /zones/<id>/email/routing/dns`` (the records it
needs, and turning it on for the zone's apex with no ``name``, as Cloudflare refuses the apex's own
name there with ``2007``; refused too while a foreign MX or an SPF without Cloudflare's include is in
the way), ``GET /zones/<id>/email/routing``, its rules and catch-all, ``DELETE`` of a DNS record,
and the account's destination addresses, each refused without Email Routing Rules (zone) or
Addresses (account) Edit. The first zone starts with a registrar's five forwarding MX records,
an SPF with a newsletter sender's include and that sender's DKIM, code and DMARC records, and
``POST /_verify/<email>`` stands for a destination's owner clicking Cloudflare's link. One token,
the first zone's without either Email Routing permission, is for refusals.
``GET /_calls`` lists every call, oldest first, with the token's last four only, and
``POST /_grant/<last four>/<permission>`` gives a token a permission it lacked, as fixing it at
Cloudflare would.

Point ``ROUH_CLOUDFLARE_API`` at it.

    python -m rouh.testing.fake_cloudflare --port 8098
"""
from __future__ import annotations

import argparse

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

ACCOUNT = "0f1e2d3c4b5a69788796a5b4c3d2e1f0"


def _starting() -> list[dict]:
    """The zones the installation's organisation starts with (`rouh/cloudflare.py`), then two
    examples, so there are always two to stand in for."""
    try:
        from ..cloudflare import STARTING
        said = [dict(z) for z in STARTING if str(z.get("zone") or "").strip()]
    except Exception:                               # noqa: BLE001 - examples are enough
        said = []
    for name in ("example.com", "example.org"):
        if all(z["zone"] != name for z in said):
            said.append({"zone": name, "zone_id": ""})
    return said[:2]


_FIRST, _SECOND = _starting()
#: The two zones' names: the first is the one whose token a world carries over
#: (`cloudflare.CARRIED`, `rouh/testing/browser.py`).
FIRST, SECOND = _FIRST["zone"], _SECOND["zone"]
ZONES = {
    FIRST: {"id": _FIRST.get("zone_id") or "5b1c0e2f7a9d4e3c8b6a1f0e9d8c7b6a", "name": FIRST,
            "status": "active", "account": {"id": ACCOUNT, "name": "Rouh"}},
    SECOND: {"id": _SECOND.get("zone_id") or "a920b4895520d0de824ac3746f88c4d3", "name": SECOND,
             "status": "pending", "account": {"id": ACCOUNT, "name": "Rouh"}},
}
EVERYTHING = {"dns", "zone", "settings", "settings_edit", "ssl", "purge", "email_rules", "email_addresses"}
#: Email Routing's two permissions: Zone - Email Routing Rules - Edit and Account - Email Routing
#: Addresses - Edit. Neither is needed, so a token made before them still passes.
EMAIL = {"email_rules", "email_addresses"}
#: Every token the stand-in accepts: the zones it sees and what it may do there.
TOKENS = {
    "cfstand-first-zone-everything-0000000000000aaaa": {"zones": [FIRST], "perms": EVERYTHING},
    "cfstand-second-zone-no-purge-00000000000000bbbb": {"zones": [SECOND],
                                                        "perms": EVERYTHING - {"purge"}},
    "cfstand-second-zone-no-ssl-0000000000000000cccc": {"zones": [SECOND],
                                                        "perms": EVERYTHING - {"ssl", "purge"}},
    "cfstand-second-zone-settings-read-only-0000hhhh": {"zones": [SECOND],
                                                        "perms": EVERYTHING - {"settings_edit"}},
    "cfstand-first-zone-no-email-routing-0000000iiii": {"zones": [FIRST], "perms": EVERYTHING - EMAIL},
    "cfstand-both-zones-00000000000000000000000dddd": {"zones": [FIRST, SECOND],
                                                       "perms": EVERYTHING},
    "cfstand-account-second-zone-0000000000000000eeee": {"zones": [SECOND], "perms": EVERYTHING,
                                                         "account": ACCOUNT},
    "cfstand-account-second-no-zone-read-00000000ffff": {"zones": [SECOND],
                                                         "perms": EVERYTHING - {"zone"},
                                                         "account": ACCOUNT},
    "cfstand-account-second-no-settings-000000000gggg": {"zones": [SECOND],
                                                         "perms": EVERYTHING - {"settings", "settings_edit"},
                                                         "account": ACCOUNT},
}
RECORDS = {
    FIRST: [{"id": "r1", "type": "A", "name": FIRST, "content": "203.0.113.10", "proxied": True,
             "ttl": 1, "comment": ""},
            # Mail as a registrar's forwarding and a newsletter sender leave a zone: five MX
            # records of the registrar's, its SPF with the sender's include, and the sender's
            # DKIM, code and DMARC records, which Email Routing must leave alone.
            *[{"id": f"mx{i}", "type": "MX", "name": FIRST, "content": f"eforward{i}.registrar-servers.example",
               "priority": 10 if i < 4 else 15 if i == 4 else 20, "ttl": 1, "comment": ""} for i in range(1, 6)],
            {"id": "spf", "type": "TXT", "name": FIRST, "ttl": 1, "comment": "",
             "content": '"v=spf1 include:spf.efwd.registrar-servers.example include:spf.sender.example ~all"'},
            {"id": "dkim1", "type": "CNAME", "name": f"sender1._domainkey.{FIRST}", "ttl": 1, "comment": "",
             "content": "b1.example-com.dkim.sender.example", "proxied": False},
            {"id": "code", "type": "TXT", "name": FIRST, "ttl": 1, "comment": "",
             "content": '"sender-code:0123456789abcdef"'},
            {"id": "dmarc", "type": "TXT", "name": f"_dmarc.{FIRST}", "ttl": 1, "comment": "",
             "content": '"v=DMARC1; p=none; rua=mailto:dmarc@example.com"'}],
    SECOND: [],
}

#: Email Routing per zone, as Cloudflare keeps it; a POST to .../email/routing/dns turns it on.
ROUTING = {name: {"enabled": False, "rules": [],
                  "catch_all": {"id": "catchall0", "tag": "catchall0", "name": "", "enabled": False,
                                "matchers": [{"type": "all"}], "actions": [{"type": "drop"}]}}
           for name in ZONES}
#: The destination addresses of the one account; `POST /_verify/<email>` stands for its owner
#: clicking the link Cloudflare sent it.
ADDRESSES: list[dict] = []


def _routing_records(zone: str) -> list[dict]:
    """What Email Routing needs in a zone, in the shape Cloudflare lists it."""
    return ([{"type": "MX", "name": zone, "content": f"route{i}.mx.cloudflare.net", "priority": p, "ttl": 1}
             for i, p in ((1, 13), (2, 86), (3, 24))]
            + [{"type": "TXT", "name": zone, "content": "v=spf1 include:_spf.mx.cloudflare.net ~all", "ttl": 1},
               {"type": "TXT", "name": f"cf2024-1._domainkey.{zone}", "ttl": 1,
                "content": "v=DKIM1; h=sha256; k=rsa; p=MIIBstandin"}])

#: Each zone's settings, as Cloudflare holds them; a PATCH changes them.
SETTINGS = {name: {"ssl": "strict", "always_use_https": "on", "min_tls_version": "1.2", "tls_1_3": "on",
                   "automatic_https_rewrites": "on"} for name in ZONES}

app = FastAPI()
CALLS: list[dict] = []
#: The Origin CA certificates made here (``POST /certificates``), listed back per zone by name
#: (``GET /certificates?zone_id=``), as Cloudflare lists them.
CERTIFICATES: list[dict] = []


def _ok(result, **more):
    return JSONResponse({"success": True, "errors": [], "messages": [], "result": result, **more})


def _no(code: int, message: str, status: int):
    return JSONResponse({"success": False, "errors": [{"code": code, "message": message}],
                         "messages": [], "result": None}, status_code=status)


def _token(request: Request, body=None):
    auth = request.headers.get("authorization", "")
    token = auth[7:] if auth.startswith("Bearer ") else ""
    CALLS.append({"method": request.method, "path": request.url.path, "query": str(request.url.query),
                  "token": "…" + token[-4:] if token else "", **({"body": body} if body is not None else {})})
    return TOKENS.get(token)


def _zone(grant, zone_id: str):
    for name in grant["zones"]:
        if ZONES[name]["id"] == zone_id:
            return name
    return None


def _denied():
    return _no(10000, "Authentication error", 403)


@app.get("/_calls")
async def calls():
    return CALLS


@app.post("/_grant/{last4}/{perm}")
async def grant(last4: str, perm: str):
    """Give the token ending `last4` one more permission, as its maker would at Cloudflare."""
    for token, given in TOKENS.items():
        if token.endswith(last4):
            given["perms"] = set(given["perms"]) | {perm}
            return {"ok": True}
    return JSONResponse({"ok": False}, status_code=404)


@app.get("/user/tokens/verify")
async def verify(request: Request):
    grant = _token(request)
    if grant is None or grant.get("account"):
        return _no(1000, "Invalid API Token", 401)
    return _ok({"id": "tok0001", "status": "active"})


@app.get("/accounts/{account_id}/tokens/verify")
async def verify_account(request: Request, account_id: str):
    grant = _token(request)
    if grant is None or grant.get("account") != account_id:
        return _no(1000, "Invalid API Token", 401)
    return _ok({"id": "tok0002", "status": "active"})


@app.get("/zones")
async def zones(request: Request, name: str = "", per_page: int = 20):
    grant = _token(request)
    if grant is None:
        return _no(1000, "Invalid API Token", 401)
    if "zone" not in grant["perms"]:
        return _ok([])
    seen = [ZONES[z] for z in grant["zones"] if not name or z == name]
    return _ok(seen[:per_page])


@app.get("/zones/{zone_id}/dns_records")
async def dns_records(request: Request, zone_id: str):
    grant = _token(request)
    if grant is None:
        return _no(1000, "Invalid API Token", 401)
    name = _zone(grant, zone_id)
    if name is None or "dns" not in grant["perms"]:
        return _denied()
    return _ok(RECORDS.get(name, []))


def _writable(request: Request, zone_id: str):
    grant = _token(request)
    if grant is None:
        return None, _no(1000, "Invalid API Token", 401)
    name = _zone(grant, zone_id)
    if name is None or "dns" not in grant["perms"]:
        return None, _denied()
    return name, None


def _clash(name: str, body: dict, but: str = ""):
    """Cloudflare's own refusal of a record beside a CNAME of the same name."""
    others = [r for r in RECORDS.setdefault(name, []) if r["name"] == body.get("name") and r["id"] != but]
    if body.get("type") == "CNAME" and others or any(r["type"] == "CNAME" for r in others):
        return _no(81053, "An A, AAAA, or CNAME record with that host already exists.", 400)
    return None


@app.post("/zones/{zone_id}/dns_records")
async def dns_add(request: Request, zone_id: str):
    """Writing records (task 165): POST adds one, PUT replaces one by its id, as Cloudflare does."""
    name, refused = _writable(request, zone_id)
    if refused:
        return refused
    body = await request.json()
    if _clash(name, body):
        return _clash(name, body)
    rec = {"id": f"r{len(CALLS)}x{len(RECORDS[name])}", "comment": "", **body}
    RECORDS[name].append(rec)
    return _ok(rec)


@app.put("/zones/{zone_id}/dns_records/{rec_id}")
async def dns_put(request: Request, zone_id: str, rec_id: str):
    name, refused = _writable(request, zone_id)
    if refused:
        return refused
    body = await request.json()
    for i, r in enumerate(RECORDS.setdefault(name, [])):
        if r["id"] == rec_id:
            if _clash(name, body, but=rec_id):
                return _clash(name, body, but=rec_id)
            RECORDS[name][i] = {"id": rec_id, "comment": "", **body}
            return _ok(RECORDS[name][i])
    return _no(81044, "Record does not exist.", 404)


@app.get("/zones/{zone_id}")
async def zone_details(request: Request, zone_id: str):
    grant = _token(request)
    if grant is None:
        return _no(1000, "Invalid API Token", 401)
    name = _zone(grant, zone_id)
    if name is None or "zone" not in grant["perms"]:
        return _denied()
    return _ok({**ZONES[name], "name_servers": ["ada.ns.cloudflare.com", "bob.ns.cloudflare.com"]})


@app.post("/certificates")
async def certificate_make(request: Request):
    """An Origin CA certificate (task 165): refused without SSL and Certificates, as Cloudflare does."""
    grant = _token(request)
    if grant is None:
        return _no(1000, "Invalid API Token", 401)
    if "ssl" not in grant["perms"]:
        return _denied()
    body = await request.json()
    if "BEGIN CERTIFICATE REQUEST" not in str(body.get("csr")):
        return _no(1010, "Invalid CSR", 400)
    made = {"id": str(328578533902268680212849205732770752308931942346 + len(CERTIFICATES)),
            "hostnames": body.get("hostnames"),
            "certificate": "-----BEGIN CERTIFICATE-----\nstand-in\n-----END CERTIFICATE-----\n",
            "expires_on": "2041-11-01 00:00:00 +0000 UTC",
            "request_type": body.get("request_type"), "requested_validity": body.get("requested_validity")}
    CERTIFICATES.append(made)
    return _ok(made)


@app.get("/zones/{zone_id}/settings/{key}")
async def setting(request: Request, zone_id: str, key: str):
    grant = _token(request)
    if grant is None:
        return _no(1000, "Invalid API Token", 401)
    name = _zone(grant, zone_id)
    if name is None or not {"settings", "settings_edit"} & set(grant["perms"]):
        return _denied()
    return _ok({"id": key, "value": SETTINGS[name].get(key, "off"), "editable": True})


@app.patch("/zones/{zone_id}/settings/{key}")
async def setting_change(request: Request, zone_id: str, key: str):
    """Change one setting: Zone Settings Edit only, as at Cloudflare."""
    try:
        body = await request.json()
    except Exception:                               # noqa: BLE001 - Cloudflare's own refusal
        body = {}
    grant = _token(request, body)
    if grant is None:
        return _no(1000, "Invalid API Token", 401)
    name = _zone(grant, zone_id)
    if name is None:
        return _denied()
    if "settings_edit" not in grant["perms"]:
        return _no(9109, "Unauthorized to access requested resource", 403)
    if not isinstance(body, dict) or "value" not in body:
        return _no(1007, "Invalid value for zone setting " + key, 400)
    SETTINGS[name][key] = body["value"]
    return _ok({"id": key, "value": body["value"], "editable": True})


@app.get("/certificates")
async def certificates(request: Request, zone_id: str = ""):
    grant = _token(request)
    if grant is None:
        return _no(1000, "Invalid API Token", 401)
    name = _zone(grant, zone_id)
    if name is None or "ssl" not in grant["perms"]:
        return _denied()
    zone = ZONES[name]["name"]
    return _ok([c for c in CERTIFICATES
                if any(h == zone or str(h).endswith("." + zone) for h in c.get("hostnames") or [])])


@app.post("/zones/{zone_id}/purge_cache")
async def purge(request: Request, zone_id: str):
    grant = _token(request)
    if grant is None:
        return _no(1000, "Invalid API Token", 401)
    if _zone(grant, zone_id) is None or "purge" not in grant["perms"]:
        return _denied()
    return _ok({"id": zone_id})


# --- Email Routing ----------------------------------------------------------------------------

def _routable(request: Request, zone_id: str, body=None):
    grant = _token(request, body)
    if grant is None:
        return None, _no(1000, "Invalid API Token", 401)
    name = _zone(grant, zone_id)
    if name is None or "email_rules" not in grant["perms"]:
        return None, _denied()
    return name, None


async def _json(request: Request):
    try:
        return await request.json()
    except Exception:                               # noqa: BLE001 - no body is an empty one
        return {}


@app.get("/zones/{zone_id}/email/routing")
async def routing(request: Request, zone_id: str):
    name, refused = _routable(request, zone_id)
    if refused:
        return refused
    on = ROUTING[name]["enabled"]
    return _ok({"id": zone_id, "tag": zone_id, "name": name, "enabled": on,
                "status": "ready" if on else "unconfigured", "skip_wizard": True})


@app.get("/zones/{zone_id}/email/routing/dns")
async def routing_dns(request: Request, zone_id: str):
    name, refused = _routable(request, zone_id)
    if refused:
        return refused
    return _ok(_routing_records(name))


@app.post("/zones/{zone_id}/email/routing/dns")
async def routing_enable(request: Request, zone_id: str):
    """Turn it on: refused while a foreign MX record or an SPF without Cloudflare's include is
    at the zone's name, as the dashboard asks for them to go first; else Cloudflare's records
    are added where missing, and nothing is ever removed."""
    body = await _json(request)
    name, refused = _routable(request, zone_id, body)
    if refused:
        return refused
    sub = str((body or {}).get("name") or "").rstrip(".").lower() if isinstance(body, dict) else ""
    if sub and not sub.endswith("." + name):        # `name` is for a subdomain only, as at Cloudflare
        return _no(2007, f"Invalid Input: must be a subdomains of {name}", 400)
    if sub:
        return _no(2008, "the stand-in enables the zone's apex only", 400)
    have = RECORDS.setdefault(name, [])
    need = _routing_records(name)
    hosts = {r["content"] for r in need if r["type"] == "MX"}
    apex = [r for r in have if r["name"] == name]
    spfs = [r for r in apex if r["type"] == "TXT" and r["content"].strip('"').startswith("v=spf1")]
    if any(r["type"] == "MX" and r["content"].rstrip(".") not in hosts for r in apex) or any(
            "include:_spf.mx.cloudflare.net" not in r["content"] for r in spfs):
        return _no(2008, "Conflicting DNS records exist; remove them first", 409)
    for r in need:
        if r["type"] == "TXT" and r["content"].startswith("v=spf1"):
            if spfs:
                continue
        elif any(h["type"] == r["type"] and h["name"] == r["name"] and h["content"].strip('"') == r["content"]
                 for h in have):
            continue
        have.append({"id": f"er{len(have)}", "comment": "Email Routing", "proxied": False, **r})
    ROUTING[name]["enabled"] = True
    return _ok({"id": zone_id, "name": name, "enabled": True, "status": "ready"})


@app.delete("/zones/{zone_id}/dns_records/{rec_id}")
async def dns_delete(request: Request, zone_id: str, rec_id: str):
    name, refused = _writable(request, zone_id)
    if refused:
        return refused
    for i, r in enumerate(RECORDS.setdefault(name, [])):
        if r["id"] == rec_id:
            del RECORDS[name][i]
            return _ok({"id": rec_id})
    return _no(81044, "Record does not exist.", 404)


@app.get("/zones/{zone_id}/email/routing/rules")
async def rules(request: Request, zone_id: str):
    name, refused = _routable(request, zone_id)
    if refused:
        return refused
    return _ok(ROUTING[name]["rules"])


def _rule_bad(body) -> str:
    if not isinstance(body, dict) or not body.get("matchers") or not body.get("actions"):
        return "matchers and actions are required"
    for a in body["actions"]:
        if a.get("type") == "forward":
            for to in a.get("value") or []:
                if not any(x["email"] == to and x["verified"] for x in ADDRESSES):
                    return f"Destination address {to} is not verified"
    return ""


@app.get("/zones/{zone_id}/email/routing/rules/catch_all")
async def catch_all(request: Request, zone_id: str):
    name, refused = _routable(request, zone_id)
    if refused:
        return refused
    return _ok(ROUTING[name]["catch_all"])


@app.put("/zones/{zone_id}/email/routing/rules/catch_all")
async def catch_all_set(request: Request, zone_id: str):
    body = await _json(request)
    name, refused = _routable(request, zone_id, body)
    if refused:
        return refused
    if _rule_bad(body):
        return _no(2020, _rule_bad(body), 400)
    ROUTING[name]["catch_all"] = {**ROUTING[name]["catch_all"], **body}
    return _ok(ROUTING[name]["catch_all"])


@app.post("/zones/{zone_id}/email/routing/rules")
async def rule_add(request: Request, zone_id: str):
    body = await _json(request)
    name, refused = _routable(request, zone_id, body)
    if refused:
        return refused
    if _rule_bad(body):
        return _no(2020, _rule_bad(body), 400)
    rid = f"rule{len(ROUTING[name]['rules']) + 1:04d}"
    rule = {"id": rid, "tag": rid, "priority": 0, "enabled": True, "name": "", **body}
    ROUTING[name]["rules"].append(rule)
    return _ok(rule)


@app.put("/zones/{zone_id}/email/routing/rules/{rule_id}")
async def rule_set(request: Request, zone_id: str, rule_id: str):
    body = await _json(request)
    name, refused = _routable(request, zone_id, body)
    if refused:
        return refused
    if _rule_bad(body):
        return _no(2020, _rule_bad(body), 400)
    for i, r in enumerate(ROUTING[name]["rules"]):
        if r["id"] == rule_id:
            ROUTING[name]["rules"][i] = {**r, **body, "id": rule_id, "tag": rule_id}
            return _ok(ROUTING[name]["rules"][i])
    return _no(2003, "Rule not found", 404)


def _addressable(request: Request, account_id: str, body=None):
    grant = _token(request, body)
    if grant is None:
        return _no(1000, "Invalid API Token", 401)
    mine = grant.get("account") or ZONES[grant["zones"][0]]["account"]["id"]
    if mine != account_id or "email_addresses" not in grant["perms"]:
        return _denied()
    return None


@app.get("/accounts/{account_id}/email/routing/addresses")
async def addresses(request: Request, account_id: str):
    refused = _addressable(request, account_id)
    return refused or _ok(ADDRESSES)


@app.post("/accounts/{account_id}/email/routing/addresses")
async def address_add(request: Request, account_id: str):
    """Add a destination: Cloudflare emails it a link, and it is verified once that is clicked."""
    body = await _json(request)
    refused = _addressable(request, account_id, body)
    if refused:
        return refused
    email = str(body.get("email") or "").lower()
    if "@" not in email:
        return _no(2001, "Invalid email address", 400)
    if any(a["email"] == email for a in ADDRESSES):
        return _no(2032, "Destination address already exists", 409)
    made = {"id": f"addr{len(ADDRESSES) + 1:04d}", "tag": f"addr{len(ADDRESSES) + 1:04d}", "email": email,
            "verified": None, "created": "2026-11-02T10:00:00Z", "modified": "2026-11-02T10:00:00Z"}
    ADDRESSES.append(made)
    return _ok(made)


@app.post("/_verify/{email}")
async def verify_address(email: str):
    """The owner of a destination clicks the link Cloudflare emailed it."""
    for a in ADDRESSES:
        if a["email"] == email.lower():
            a["verified"] = "2026-11-02T10:05:00Z"
            return {"ok": True}
    return JSONResponse({"ok": False}, status_code=404)


def main() -> None:
    import uvicorn

    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8098)
    args = ap.parse_args()
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
