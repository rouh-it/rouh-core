"""Cloudflare: one API token per zone, typed into Settings and kept sealed.

Petar, 12 October 2026: "create an input field where I can save the token in settings, so
it doesn't pass through the LLM. Remember I have one cloudflare token for [the first Rouh's
domain] and now we are doing another one for Rouh.it".

**Where a token comes in.** Settings, Cloudflare (/settings/cloudflare), one row per zone: a
password field and Save. The token leaves the page in one request, straight to
`web/cloudflare.py`, and is checked here with Cloudflare's own API before anything is kept.
It never goes through a chat, a model, a tool result, a log line, an error message, a page's
answer or Synapse: what is shown and said afterwards is that one is set, its last four
characters, when it was saved and when it was last checked.

**The check** is the one a task first wrote to check a token, made general, for any
zone: the token finds the zone by its name (`GET /zones?name=`, Zone - Read), which gives the
zone's id and its account's, so nobody looks either up; Cloudflare says the token is active,
at `GET /user/tokens/verify` for a user token or `GET /accounts/<id>/tokens/verify` for an
account token (27 October 2026: rouh.page's was one, and the first endpoint alone refused it
as invalid), the account being the zone's or the one given when the zone was added or the
token saved, as Cloudflare's own token page shows it; the zones it can list are exactly this
one, and when the zone's id or account is already known, it is that one. Nobody types a zone
id ("zone id seems not required", Petar, 27 October 2026); DNS and SSL and Certificates each
answer it, read with GET as 86-02 did; and it may change the zone's settings (Zone Settings,
Edit), proved by reading one setting and writing back exactly the value read, so nothing in
the zone changes (Petar, 2 November 2026: "check for zone settings write", after a token with
only Read passed here and could not then change rouh.land's settings). Cache Purge is
optional, and is tried by purging one address under the zone that does not exist. A token
that fails any of it is not kept, and the page says which, with one exception: a token
Cloudflare accepts as active, that finds this zone and no other, and lacks only DNS, Zone
Settings Edit or SSL and Certificates, is
kept sealed and marked as failing (Petar, 28 October 2026, `only_permissions_missing`), so the
permission is added at Cloudflare and Check again pressed, with nothing pasted again. It is
never put in place of a kept token that passed.

**Where it is kept.** Sealed with `encryption.SecretBox`, as the Stripe key and the card are
(`rouh/payments.py`), in `cloudflare_zones`, keyed by organisation: a zone is shared by the
people of the organisation that owns it, and only its administrators change its token.

**A token from before.** Until 20 October 2026 the first installation's organisation started
with two zones written in here, and a token a task had installed in the server's environment
was sealed into its zone's row the first time the zones were read (`_carry_over`). Those rows
are kept as they are; a new organisation starts with no zone and nothing is carried.

**Using a token.** Rouh's own code asks by zone name, `cloudflare_token("example.com")`, or
better `zone_api("example.com")`, which calls Cloudflare with it; a tool takes a zone name and
never a token, and the model never sees one.

**Email Routing** (2 November 2026): a zone's mail forwarding is set up through the API, as
everything with one is, not clicked through the dashboard: `ZoneAPI.email_status`,
`email_enable`, `email_destination` and `email_rule`. Turning it on never removes or replaces a
DNS record silently: the MX records and the SPF record in the way are named, and only a second
call with `replace_mx` removes those MX records and adds Cloudflare's include to that SPF record;
nothing else is touched. Its two permissions, Email Routing Rules Edit (zone) and Email Routing
Addresses Edit (account), are optional in the check, and a call refused for want of one names it.

`ROUH_CLOUDFLARE_API` points it all at a stand-in (`rouh/testing/fake_cloudflare.py`).
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from .encryption import box as _box

log = logging.getLogger("rouh.cloudflare")

#: Cloudflare's API, or a stand-in's in a test world.
API = os.environ.get("ROUH_CLOUDFLARE_API", "https://api.cloudflare.com/client/v4").rstrip("/")
PAGE = "/settings/cloudflare"
TIMEOUT = 15

#: The zones an organisation starts with: none. Every zone is added in Settings,
#: Cloudflare, by the organisation's administrator (20 October 2026: an installation starts
#: with nobody's zones). The two this module once wrote in for the first installation's own
#: organisation are rows of `cloudflare_zones` there, kept as they are, `starting` and all.
STARTING: tuple[dict, ...] = ()
#: A token already in Rouh's environment, by zone, carried into the zone's row once: none
#: now. The first installation's was carried on 12 October 2026 and its row says so.
CARRIED: dict[str, str] = {}
CARRIED_SAID = "the server's settings, where task 86-02 installed it on 3 October 2026"

#: What a token is made with, in Cloudflare's own words, as the page lists them. Zone
#: Settings is Edit, which includes Read: Rouh changes a zone's settings (task 165 sets
#: always_use_https and min_tls_version on rouh.land), and on 2 November 2026 a token with
#: only Read passed here and then could not. Edit is proved by reading a setting and writing
#: the same value back (`_settings_edit`), so the check itself changes nothing.
ZONE_READ, DNS, SETTINGS, SSL = ("Zone - Zone - Read", "Zone - DNS - Edit",
                                 "Zone - Zone Settings - Edit", "Zone - SSL and Certificates - Edit")
NEEDED = (ZONE_READ, DNS, SETTINGS, SSL)
#: Email Routing (2 November 2026: mail forwarding for a zone set up through the API, not the
#: dashboard): rules are the zone's, destination addresses the account's. Both are optional,
#: so a token made before them still passes; a call refused for want of one names it.
EMAIL_RULES = "Zone - Email Routing Rules - Edit"
EMAIL_ADDRESSES = "Account - Email Routing Addresses - Edit"
#: Purge is tried, by purging an address under the zone that does not exist; Email Routing
#: Rules Edit by writing the catch-all back exactly as read; Email Routing Addresses by
#: listing them (adding one would send it an email, so Edit is shown the first time one is).
OPTIONAL = ("Zone - Cache Purge - Purge", EMAIL_RULES, EMAIL_ADDRESSES)
#: The settings Edit is proved on, in order: harmless ones every plan may change. The first
#: that reads and says it is editable is written back exactly as read.
SETTINGS_PROBE = ("always_use_https", "ssl")
#: What Cloudflare says to a token that may not do what it asked: 9109 "Unauthorized to
#: access requested resource" and 10000 "Authentication error", with HTTP 403.
DENIED_CODES = {9109, 10000}

_DOMAIN = re.compile(r"^(?=.{3,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
_TOKEN = re.compile(r"^[A-Za-z0-9_\-]{20,200}$")
#: A zone's or an account's id: 32 hexadecimal characters.
_ID = re.compile(r"^[0-9a-f]{32}$")


class Refused(ValueError):
    """Said to the person as it is. Never holds a token or any part of one but its last four.
    `tried` is what a refused token's check found, for the page to show."""

    def __init__(self, said: str, tried: dict | None = None) -> None:
        super().__init__(said)
        self.tried = tried


class NoToken(LookupError):
    """No token is kept for that zone: what to do about it, in a sentence."""


class CFError(Exception):
    """Cloudflare said no, or could not be reached; its words, never the token. `codes` are
    Cloudflare's error codes and `status` the HTTP status, when it answered at all."""

    def __init__(self, said: str, codes=(), status: int = 0) -> None:
        super().__init__(said)
        self.codes = {int(c) for c in codes if str(c).isdigit()}
        self.status = int(status or 0)

    @property
    def denied(self) -> bool:
        """Cloudflare refused it for want of a permission."""
        return self.status == 403 or bool(self.codes & DENIED_CODES)


# --- the box and the rows ---------------------------------------------------------------

def _model():
    from .models import CloudflareZone

    return CloudflareZone


def domain_of(text) -> str:
    """A zone's name as somebody might type it, made plain: "https://Example.COM/" is example.com."""
    name = str(text or "").strip().lower()
    name = re.sub(r"^[a-z]+://", "", name).split("/")[0].split(":")[0].strip(".")
    if name.startswith("www."):
        name = name[4:]
    return name


def _org(org_id: str | None) -> str:
    """Whose zones: the one given, the speaker's, the only person's, or the only
    organisation anybody belongs to. Never a guess between two."""
    if org_id:
        return str(org_id)
    from .tenancy import Tenancy, speaker

    who = speaker() or Tenancy().only_person()
    if who is not None:
        return who.org_id
    from .models import User

    orgs = set(User.objects.filter(is_active=True, is_guest=False).values_list("org_id", flat=True))
    if len(orgs) == 1:
        return str(orgs.pop())
    raise NoToken("Whose Cloudflare? More than one organisation is on this install; name it.")


def zones_of(org_id: str) -> list:
    """The organisation's zones, oldest first: the ones added in Settings (`STARTING` is empty)."""
    from .tenancy import DEFAULT_ORG_ID

    m = _model()
    if str(org_id) == DEFAULT_ORG_ID:
        for i, z in enumerate(STARTING):
            m.objects.get_or_create(org_id=str(org_id), zone=z["zone"],
                                    defaults={"zone_id": z["zone_id"], "account_id": z["account_id"],
                                              "starting": True, "made_at": time.time() + i / 1000})
        _carry_over(str(org_id))
    return list(m.objects.filter(org_id=str(org_id)).order_by("made_at", "id"))


def _carry_over(org_id: str) -> None:
    """The token already in Rouh's environment into its zone's row, sealed, once."""
    m = _model()
    for zone, name in CARRIED.items():
        token = (os.environ.get(name) or "").strip()
        if not token:
            continue
        done = m.objects.filter(org_id=org_id, zone=zone, carried=False, token_sealed="").update(
            token_sealed=_box().seal(token), last4=token[-4:], saved_at=time.time(),
            saved_by="", source="server", carried=True, checked_at=0, check_ok=None, checks=[])
        if done:
            log.info("the %s Cloudflare token in Rouh's environment was sealed into Settings", zone)


def _row(org_id: str, zone: str):
    zone = domain_of(zone)
    for row in zones_of(org_id):
        if row.zone == zone:
            return row
    return None


# --- talking to Cloudflare ----------------------------------------------------------------


def _scrub(text: str, token: str) -> str:
    return text.replace(token, "…") if token and len(token) >= 8 else text


def call(token: str, method: str, path: str, body=None) -> dict:
    """One call to Cloudflare's API with a token. Raises CFError with Cloudflare's words."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, data=data, method=method,
                                 headers={"Authorization": f"Bearer {token}",
                                          "Content-Type": "application/json"})
    status = 200
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            out = json.load(r)
    except urllib.error.HTTPError as e:
        status = e.code
        try:
            out = json.load(e)
        except Exception:
            raise CFError(f"HTTP {e.code}", status=e.code) from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        reason = getattr(e, "reason", e)
        raise CFError(_scrub(f"Cloudflare could not be reached ({reason})", token)) from None
    if not isinstance(out, dict) or not out.get("success"):
        errs = (out or {}).get("errors") if isinstance(out, dict) else None
        said = "; ".join(f"{x.get('code')}: {x.get('message')}" for x in (errs or []) if isinstance(x, dict))
        codes = [x.get("code") for x in (errs or []) if isinstance(x, dict)]
        raise CFError(_scrub(said or "no reason given", token), codes=codes, status=status)
    return out


def prove(token: str, zone: str, *, zone_id: str = "", account_id: str = "") -> dict:
    """Every check a token for `zone` must pass, as 86-02's `cf_rouh_is.py prove` did.

    The zone is found by its name first (`GET /zones?name=`), which gives its id and its
    account's, so nobody looks either up. A user token (My Profile, API Tokens) is then
    verified at `/user/tokens/verify`; an account token (Manage Account, API Tokens), which
    Cloudflare refuses there with "1000: Invalid API Token", at
    `/accounts/<account id>/tokens/verify`, with the account the zone is in or the one given.
    That refusal is what turned rouh.page's token away on 27 October 2026.

    Returns {"ok", "checks": [{"name", "ok", "optional", "said"}], "zone_id", "account_id",
    "status", "missing": [names]}. Nothing in it holds the token."""
    checks: list[dict] = []
    found = {"zone_id": "", "account_id": "", "status": ""}

    def mark(name, good, said, optional=False):
        checks.append({"name": name, "ok": bool(good), "optional": optional, "said": said})

    # The zone, by its name: its id and its account's come with it.
    mine, zone_said = None, ""
    try:
        got = call(token, "GET", f"/zones?name={urllib.parse.quote(zone)}")["result"] or []
        mine = next((z for z in got if z.get("name") == zone), None)
    except CFError as e:
        zone_said = str(e)
    if mine is not None:
        found["zone_id"] = str(mine.get("id") or "")
        found["account_id"] = str((mine.get("account") or {}).get("id") or "")
        found["status"] = str(mine.get("status") or "")

    # Active: as a user token, then as an account token of the zone's account or the one typed.
    v, kind, refused = None, "", ""
    try:
        v = call(token, "GET", "/user/tokens/verify")["result"] or {}
        kind = "user"
    except CFError as e:
        refused = str(e)
        for acc in dict.fromkeys(a for a in (found["account_id"], account_id) if a):
            try:
                v = call(token, "GET", f"/accounts/{acc}/tokens/verify")["result"] or {}
                kind = f"account token of account {acc}"
                break
            except CFError:
                continue
    if v is None:
        said = f"Cloudflare does not accept this token (it said {refused})"
        if not found["account_id"] and not account_id:
            said += (". If it was made under Manage Account, API Tokens, it is an account token: paste "
                     "the Account ID that page shows beside the token, and Save again")
        mark("Active", False, said)
        return _proved(checks, found)
    status = v.get("status") or "unknown"
    mark("Active", status == "active",
         f"Cloudflare says it is {status}" + (", an " + kind if kind != "user" else "")
         + (f", until {v['expires_on'][:10]}" if v.get("expires_on") else ", with no expiry"))
    if not checks[-1]["ok"]:
        return _proved(checks, found)

    if mine is None:
        mark("Zone - Zone - Read", False,
             f"this token cannot read {zone}" + (f" (Cloudflare said {zone_said})" if zone_said else "")
             + f": give it {_and(list(NEEDED))} for {zone}")
        for name in DNS, SETTINGS, SSL:
            mark(name, False, f"not tried: it cannot see {zone}")
        return _proved(checks, found)
    mark(ZONE_READ, True, f"it finds {zone}")
    if zone_id and found["zone_id"] != zone_id:
        mark("Zone ID", False, f"the {zone} it sees is zone {found['zone_id']}, not {zone_id}")
    if account_id and found["account_id"] and found["account_id"] != account_id:
        mark("Account", False, f"the {zone} it sees is in account {found['account_id']}, not {account_id}")

    try:
        names = sorted(str(z.get("name") or "") for z in call(token, "GET", "/zones?per_page=50")["result"] or [])
    except CFError:
        names = [zone]
    if names == [zone]:
        mark(f"Only {zone}", True, f"the token sees {zone} and no other zone")
    else:
        mark(f"Only {zone}", False, f"the token sees {_and(names)}; in Cloudflare, set its Zone "
             f"Resources to Include, Specific zone, {zone}")

    zid = found["zone_id"]
    for name, path in ((DNS, f"/zones/{zid}/dns_records?per_page=1"),
                       (SSL, f"/certificates?zone_id={zid}")):
        try:
            call(token, "GET", path)
            mark(name, True, "answers")
        except CFError as e:
            mark(name, False, f"refused (Cloudflare said {e}): give the token {name} for {zone}")
    mark(SETTINGS, *_settings_edit(token, zid, zone))
    try:
        call(token, "POST", f"/zones/{zid}/purge_cache",
             {"files": [f"https://{zone}/.rouh-cache-purge-check"]})
        mark(OPTIONAL[0], True, "answers", optional=True)
    except CFError:
        mark(OPTIONAL[0], False, "not given; optional", optional=True)
    mark(EMAIL_RULES, *_email_rules_edit(token, zid, zone), optional=True)
    acc = found["account_id"] or account_id
    if not acc:
        mark(EMAIL_ADDRESSES, False, "not tried: the zone's account is not known; optional", optional=True)
    else:
        try:
            call(token, "GET", f"/accounts/{acc}/email/routing/addresses?per_page=5")
            mark(EMAIL_ADDRESSES, True, "answers (it lists the account's destination addresses)",
                 optional=True)
        except CFError as e:
            mark(EMAIL_ADDRESSES, False, "not given; optional" if e.denied else
                 f"not given (Cloudflare said {e}); optional", optional=True)
    return _proved(checks, found)


def _email_rules_edit(token: str, zid: str, zone: str) -> tuple[bool, str]:
    """Whether the token may change the zone's Email Routing rules, without changing any: the
    catch-all is read and written back exactly as read, which Cloudflare accepts only with
    Email Routing Rules Edit."""
    try:
        got = call(token, "GET", f"/zones/{zid}/email/routing/rules/catch_all")["result"] or {}
    except CFError as e:
        return False, "not given; optional" if e.denied else f"not given (Cloudflare said {e}); optional"
    try:
        call(token, "PUT", f"/zones/{zid}/email/routing/rules/catch_all", _catch_all_body(got))
    except CFError as e:
        return False, ("it can read the rules but not change them; optional" if e.denied else
                       f"writing the catch-all back unchanged was refused (Cloudflare said {e}); optional")
    return True, f"may change {zone}'s mail forwarding rules (proved by writing the catch-all back as it was)"


def _catch_all_body(rule: dict) -> dict:
    """The catch-all as Cloudflare takes it back: what it is, never its id or dates."""
    return {"actions": rule.get("actions") or [{"type": "drop"}],
            "matchers": rule.get("matchers") or [{"type": "all"}],
            "enabled": bool(rule.get("enabled")), "name": str(rule.get("name") or "")}


def _settings_edit(token: str, zid: str, zone: str) -> tuple[bool, str]:
    """Whether the token may change the zone's settings, without changing any.

    A harmless setting is read, then written back with exactly the value read: Cloudflare
    accepts that write only from a token with Zone Settings Edit, and refuses it from one with
    Read alone (9109 or 10000, HTTP 403). Nothing is written when the read fails, and nothing
    but the value just read is ever sent."""
    refused = None
    for key in SETTINGS_PROBE:
        try:
            got = call(token, "GET", f"/zones/{zid}/settings/{key}")["result"] or {}
        except CFError as e:
            refused = refused or e
            continue
        if "value" not in got or got.get("editable") is False:
            continue
        try:
            call(token, "PATCH", f"/zones/{zid}/settings/{key}", {"value": got["value"]})
        except CFError as e:
            if e.denied:
                return False, (f"it can read {zone}'s settings but not change them (Cloudflare said {e}): "
                               f"Zone Settings Edit is missing; give the token {SETTINGS} for {zone}")
            return False, (f"writing {key} back unchanged was refused (Cloudflare said {e}); "
                           f"the token needs {SETTINGS} for {zone}")
        return True, f"may change {zone}'s settings (proved by writing {key} back as it was)"
    if refused is not None:
        return False, (f"it cannot read {zone}'s settings (Cloudflare said {refused}): "
                       f"Zone Settings Edit is missing; give the token {SETTINGS} for {zone}")
    return False, f"none of {_and(list(SETTINGS_PROBE))} could be changed in {zone}, so Edit is unproved"


def _proved(checks: list[dict], found: dict) -> dict:
    missing = [c["name"] for c in checks if not c["ok"] and not c["optional"]]
    return {"ok": not missing, "checks": checks, "missing": missing, **found}


def _why_not(zone: str, proved: dict) -> str:
    by = {c["name"]: c for c in proved["checks"]}
    if "Active" in by and not by["Active"]["ok"]:
        return f"Not saved: {by['Active']['said']}."
    if ZONE_READ in by and not by[ZONE_READ]["ok"]:
        return f"Not saved: {by[ZONE_READ]['said']}."
    for name in "Zone ID", "Account", f"Only {zone}":
        if name in by and not by[name]["ok"]:
            return f"Not saved: {by[name]['said']}."
    perms = [n for n in proved["missing"] if n.startswith("Zone - ")]
    if perms:
        return (f"Not saved: this token can read {zone} but is missing {_and(perms)}. Add "
                f"{'it' if len(perms) == 1 else 'them'} for {zone} in Cloudflare, or make a new one.")
    return f"Not saved: {_and([by[n]['said'] for n in proved['missing']])}."


def _and(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


# --- what the page does -------------------------------------------------------------------


def _admin(who) -> None:
    if not getattr(who, "is_admin", False):
        raise Refused("Only an administrator of this organisation changes its Cloudflare tokens.")


def _typed_id(text, what: str) -> str:
    """An account id pasted in by hand, as Cloudflare's token page shows it."""
    value = re.sub(r"\s+", "", str(text or "")).lower()
    if value and not _ID.match(value):
        raise Refused(f"That is not an {what}: Cloudflare's are 32 letters and digits, such as "
                      "0f1e2d3c4b5a69788796a5b4c3d2e1f0. Nothing was saved.")
    return value


def save(who, zone: str, token: str, account_id: str = "") -> dict:
    """Check a token with Cloudflare and keep it, sealed, for the zone; or refuse it, saying
    why. The zone's id, and its account's, are found with the token; `account_id`, as
    Cloudflare's token page shows it, is needed only for an account token that cannot read
    the zone. Returns the page, with what the check found as `tried`."""
    _admin(who)
    row = _row(who.org_id, zone)
    if row is None:
        raise Refused("That zone is not one of this organisation's. Add it first.")
    token = str(token or "").strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    if not _TOKEN.match(token):
        raise Refused("That does not look like a Cloudflare API token: one is a single word of "
                      "letters, digits, dashes and underscores. Nothing was saved.")
    account_id = _typed_id(account_id, "Account ID") or row.account_id
    proved = prove(token, row.zone, zone_id=row.zone_id, account_id=account_id)
    tried = {"zone": row.zone, "checks": proved["checks"], "account_id": account_id}
    fixable = not proved["ok"] and only_permissions_missing(proved)
    if fixable and row.token_sealed and row.check_ok is True:
        # Never put a token that fails in place of one that passed.
        log.info("a Cloudflare token for %s was refused in place of one that passed (%s)",
                 row.zone, ", ".join(proved["missing"]))
        raise Refused(_why_not(row.zone, proved) + f" The token ending {row.last4}, which passed, "
                      "is still kept.", tried)
    if not proved["ok"] and not fixable:
        log.info("a Cloudflare token for %s was refused (%s)", row.zone, ", ".join(proved["missing"]))
        raise Refused(_why_not(row.zone, proved), tried)
    now = time.time()
    _model().objects.filter(id=row.id, org_id=who.org_id).update(
        token_sealed=_box().seal(token), last4=token[-4:], saved_at=now, saved_by=str(who.user_id),
        source="settings", carried=True, checked_at=now, check_ok=proved["ok"], checks=proved["checks"],
        zone_id=proved["zone_id"] or row.zone_id, account_id=proved["account_id"] or row.account_id,
        status=proved["status"], updated_at=now)
    if fixable:
        log.info("a Cloudflare token for %s was kept, failing for want of %s, for org %s by user %s",
                 row.zone, ", ".join(proved["missing"]), who.org_id, who.user_id)
    else:
        log.info("a Cloudflare token for %s was checked and saved for org %s by user %s",
                 row.zone, who.org_id, who.user_id)
    token = ""
    return {**public(who), "tried": tried, "kept_failing": fixable,
            "why": _fix_then_check(row.zone, proved) if fixable else ""}


def only_permissions_missing(proved: dict) -> bool:
    """Whether a token failed only for want of a permission, and so is worth keeping.

    Petar, 28 October 2026: "when a token fails only for a missing permission, Rouh could keep
    it encrypted and marked as failing. You would then fix the permission at Cloudflare and
    press Check again, with nothing to paste." So it is kept only when Cloudflare has said it
    is active and it finds this very zone (Zone - Read), in the zone's own id and account,
    seeing no other zone, and what fails is one or more of DNS, Zone Settings Edit (2 November
    2026: a token with Zone Settings Read only is kept, so Edit is added at Cloudflare and
    Check again pressed) and SSL and Certificates. A token Cloudflare does not accept, or one not active, or one that cannot
    see the zone, is never kept: nothing would show it is this zone's token."""
    if proved["ok"]:
        return False
    by = {c["name"]: c for c in proved["checks"]}
    if not (by.get("Active", {}).get("ok") and by.get(ZONE_READ, {}).get("ok")):
        return False
    fixable = {DNS, SETTINGS, SSL}
    return bool(proved["missing"]) and all(name in fixable for name in proved["missing"])


def _fix_then_check(zone: str, proved: dict) -> str:
    perms = proved["missing"]
    return (f"it is missing {_and(perms)}. Add {'it' if len(perms) == 1 else 'them'} to this token "
            f"for {zone} at Cloudflare, then press Check again: there is nothing to paste.")


def check(who, zone: str) -> dict:
    """Check the kept token again. Kept whatever it says: the page says what failed."""
    _admin(who)
    row = _row(who.org_id, zone)
    if row is None or not row.token_sealed:
        raise Refused("There is no token kept for that zone to check.")
    proved = prove(_box().open_(row.token_sealed), row.zone, zone_id=row.zone_id, account_id=row.account_id)
    now = time.time()
    _model().objects.filter(id=row.id, org_id=who.org_id).update(
        checked_at=now, check_ok=proved["ok"], checks=proved["checks"],
        zone_id=row.zone_id or proved["zone_id"], account_id=row.account_id or proved["account_id"],
        status=proved["status"] or row.status, updated_at=now)
    return {**public(who), "tried": {"zone": row.zone, "checks": proved["checks"]},
            "passed": proved["ok"],
            "why": "" if proved["ok"] else ("Not saved: " + _fix_then_check(row.zone, proved)
                                            if only_permissions_missing(proved) else _why_not(row.zone, proved))}


def remove(who, zone: str) -> dict:
    """Forget the zone's token. It is not revoked at Cloudflare."""
    _admin(who)
    row = _row(who.org_id, zone)
    if row is None:
        raise Refused("That zone is not one of this organisation's.")
    _model().objects.filter(id=row.id, org_id=who.org_id).update(
        token_sealed="", last4="", saved_at=0, saved_by="", source="", checked_at=0, check_ok=None,
        checks=[], updated_at=time.time())
    log.info("the Cloudflare token for %s was removed for org %s by user %s", row.zone, who.org_id, who.user_id)
    return public(who)


def add_zone(who, zone: str, account_id: str = "") -> dict:
    """A zone by its domain name, and, if given, the Cloudflare account it is in."""
    _admin(who)
    name = domain_of(zone)
    if not _DOMAIN.match(name):
        raise Refused("Give the zone's domain name, such as example.com.")
    if _row(who.org_id, name) is not None:
        raise Refused(f"{name} is already here.")
    account_id = _typed_id(account_id, "Account ID")
    _model().objects.create(org_id=who.org_id, zone=name, account_id=account_id, made_at=time.time())
    return public(who)


def forget_zone(who, zone: str) -> dict:
    """Take a zone off the list. Only one with no token, and never one it starts with."""
    _admin(who)
    row = _row(who.org_id, zone)
    if row is None:
        raise Refused("That zone is not one of this organisation's.")
    if row.starting:
        raise Refused(f"{row.zone} is one of this installation's own zones and stays on the list.")
    if row.token_sealed:
        raise Refused(f"Remove {row.zone}'s token first.")
    _model().objects.filter(id=row.id, org_id=who.org_id).delete()
    return public(who)


def _when(ts) -> str:
    from . import clock

    return clock.moment(ts).strftime("%-d %b %Y, %H:%M") if ts else ""


def public(who) -> dict:
    """Everything the page shows, for the person's organisation. Never a token: that one is
    set, its last four, when it was saved and when it was last checked."""
    rows = zones_of(who.org_id)
    return {
        "admin": bool(getattr(who, "is_admin", False)),
        "needed": list(NEEDED), "optional": list(OPTIONAL),
        "zones": [{
            "zone": r.zone, "zone_id": r.zone_id, "account_id": r.account_id, "status": r.status,
            "starting": r.starting,
            "token": ({"last4": r.last4, "saved": _when(r.saved_at),
                       "from": CARRIED_SAID if r.source == "server" else "",
                       "checked": _when(r.checked_at), "ok": r.check_ok,
                       "checks": r.checks or [],
                       "missing": [c.get("name") for c in r.checks or []
                                   if not c.get("ok") and not c.get("optional")]
                       } if r.token_sealed else None),
        } for r in rows],
    }


def status_line(who) -> str:
    """What a tool may say: each zone, whether a token is set, and how its check went."""
    out = []
    for z in public(who)["zones"]:
        t = z["token"]
        if not t:
            out.append(f"{z['zone']}: no token.")
            continue
        state = ("passed every check" if t["ok"] else
                 "failed its last check (missing " + _and([c["name"] for c in t["checks"]
                                                           if not c["ok"] and not c["optional"]] or ["?"]) + ")"
                 if t["ok"] is False else "not checked here yet")
        out.append(f"{z['zone']}: a token is set, saved {t['saved']}"
                   + (f" (carried over from {t['from']})" if t["from"] else "")
                   + f"; {state}" + (f", last checked {t['checked']}" if t["checked"] else "") + ".")
    return " ".join(out) + f" Tokens are added, replaced and removed in Settings, Cloudflare ({PAGE})."


# --- for Rouh's own code -------------------------------------------------------------------


def cloudflare_token(zone: str, org_id: str | None = None) -> str:
    """The token kept for a zone, for Rouh's own server code to call Cloudflare with.

    Never to be put in a prompt, a tool result, a log line or a message: hand it straight
    to the call. `zone_api` does that for you, and is what a tool should use."""
    org = _org(org_id)
    row = _row(org, zone)
    if row is None or not row.token_sealed:
        from . import owner

        raise NoToken(owner.say(f"No Cloudflare token is kept for {domain_of(zone)}. ‹owner› adds one in "
                                f"Settings, Cloudflare ({PAGE})."))
    return _box().open_(row.token_sealed)


class ZoneAPI:
    """Cloudflare for one zone, by name: its id, and calls made with its kept token."""

    def __init__(self, zone: str, zone_id: str, token: str, account_id: str = "") -> None:
        self.zone = zone
        self.zone_id = zone_id
        self.account_id = account_id
        self._token = token

    def __repr__(self) -> str:
        return f"ZoneAPI({self.zone!r}, {self.zone_id!r})"

    def call(self, method: str, path: str, body=None) -> dict:
        """A call under /zones/<this zone's id>, or any path that starts with /."""
        if not path.startswith(("/zones/", "/user", "/certificates", "/accounts/")):
            path = f"/zones/{self.zone_id}{path if path.startswith('/') else '/' + path}"
        return call(self._token, method, path, body)

    def dns_records(self) -> list[dict]:
        got = self.call("GET", "/dns_records?per_page=100")["result"] or []
        return [{k: r.get(k) for k in ("type", "name", "content", "proxied", "ttl", "comment")} for r in got]

    # Writing (task 165, 1 November 2026: rouh.land set up beside rouh.it "through Cloudflare's
    # API"). Narrow on purpose: records are made or changed in place, and a call that would
    # change more than it names is refused before anything is written. The one deletion is
    # `dns_delete`, one record a call, named by type, name and content (2 November 2026: a
    # stray AAAA added to rouh.land by mistake).

    def dns_set(self, wanted: list[dict]) -> list[str]:
        """Make the zone hold each record in `wanted`, and say what was done to each.

        A record is {type, name, content, proxied?, ttl?, comment?, replaces?}. `name` is the
        full name or "@" for the zone itself. It is matched to what the zone has already:
        - the same type, name and content: changed only where proxied, ttl or comment differ;
        - A, AAAA and CNAME: the one record of that type and name is changed in place, and
          a CNAME standing where an A or AAAA is wanted (or the other way round) is changed
          into it, since Cloudflare allows no other record beside a CNAME;
        - any other type (TXT, MX ...): added beside what is there, unless `replaces` gives the
          start of the content of the one record it takes the place of (such as "v=DMARC1").
        Two records that could be meant is a refusal, never a guess. Every record is checked
        before the first is written."""
        have = self.call("GET", "/dns_records?per_page=500")["result"] or []
        plan, claimed = [], set()
        for w in wanted:
            kind = str(w.get("type") or "").upper().strip()
            name = self._full(w.get("name"))
            content = str(w.get("content") or "").strip()
            if not kind or not name or not content:
                raise CFError("each record needs a type, a name and its content")
            body = {"type": kind, "name": name, "content": content,
                    "ttl": int(w.get("ttl") or 1)}
            if kind in ("A", "AAAA", "CNAME"):
                body["proxied"] = bool(w.get("proxied", False))
            if w.get("comment"):
                body["comment"] = str(w["comment"])[:100]
            if kind == "MX":
                body["priority"] = int(w.get("priority") or 10)
            same = [r for r in have if r.get("type") == kind and r.get("name") == name
                    and str(r.get("content")).rstrip(".") == content.rstrip(".")]
            if same:
                plan.append(("same", same[0], body))
                continue
            if kind in ("A", "AAAA", "CNAME"):
                kinds = ("CNAME",) if kind != "CNAME" else ("A", "AAAA", "CNAME")
                kinds = tuple(sorted(set(kinds) | {kind}))
                old = [r for r in have if r.get("name") == name and r.get("type") in kinds]
                if kind != "CNAME":
                    # Another A (or AAAA) at the name is the one replaced; a CNAME there too.
                    old = [r for r in old if r.get("type") in (kind, "CNAME")]
            elif w.get("replaces"):
                start = str(w["replaces"])
                old = [r for r in have if r.get("type") == kind and r.get("name") == name
                       and str(r.get("content") or "").strip('"').startswith(start)]
                if not old:
                    plan.append(("add", None, body))
                    continue
            else:
                plan.append(("add", None, body))
                continue
            old = [r for r in old if r.get("id") not in claimed]
            if len(old) > 1:
                raise CFError(f"{name} has {len(old)} records this {kind} could replace "
                              f"({', '.join(r['type'] + ' ' + str(r['content']) for r in old)}); nothing was written")
            if old:
                claimed.add(old[0].get("id"))
            plan.append(("change", old[0], body) if old else ("add", None, body))
        said = []
        for how, old, body in plan:
            label = f"{body['type']} {body['name']} -> {body['content']}" + (
                " proxied" if body.get("proxied") else "")
            if how == "same":
                if all(old.get(k) == body[k] for k in ("proxied", "ttl", "comment") if k in body):
                    said.append(f"{label}: already so")
                    continue
                self.call("PUT", f"/dns_records/{old['id']}", body)
                said.append(f"{label}: settings changed")
            elif how == "change":
                self.call("PUT", f"/dns_records/{old['id']}", body)
                said.append(f"{label}: was {old['type']} {old['content']}")
            else:
                self.call("POST", "/dns_records", body)
                said.append(f"{label}: added")
        return said

    def _full(self, name) -> str:
        name = str(name or "").strip().rstrip(".").lower()
        if name in ("", "@"):
            return self.zone if name == "@" else ""
        return name if name == self.zone or name.endswith("." + self.zone) else f"{name}.{self.zone}"

    def settings(self) -> dict:
        """The zone's encryption settings as Cloudflare has them (Zone Settings, which the
        check asks to be Edit, so they can be changed too)."""
        out = {}
        for key in ("ssl", "always_use_https", "min_tls_version", "tls_1_3", "automatic_https_rewrites"):
            try:
                out[key] = self.call("GET", f"/settings/{key}")["result"].get("value")
            except CFError as exc:
                out[key] = f"unreadable ({exc})"
        try:
            got = self.call("GET", f"/zones/{self.zone_id}")["result"] or {}
            out["status"] = got.get("status")
            out["name_servers"] = got.get("name_servers") or []
        except CFError as exc:
            out["status"] = f"unreadable ({exc})"
        return out

    #: The encryption settings `settings_set` may change, and the values each may take (task
    #: 165, 2 November 2026: rouh.land goes to Full (strict) once its server has a Cloudflare
    #: Origin CA certificate, as rouh.it is). Nothing else of a zone is changed this way.
    SETTABLE = {"ssl": ("off", "flexible", "full", "strict"),
                "always_use_https": ("on", "off"),
                "min_tls_version": ("1.0", "1.1", "1.2", "1.3")}

    def settings_set(self, wanted: dict) -> list[str]:
        """Set some of the zone's encryption settings, and say what each was and is now.

        Only the keys in SETTABLE, each to one of its values; every key and value is checked
        before the first is written, and a setting already so is left alone."""
        if not isinstance(wanted, dict) or not wanted:
            raise CFError("give the settings to set, such as {\"ssl\": \"strict\"}")
        plan = []
        for key, value in wanted.items():
            key, value = str(key).strip().lower(), str(value).strip().lower()
            if key not in self.SETTABLE:
                raise CFError(f"{key} is not one this can set ({', '.join(self.SETTABLE)}); nothing was written")
            if value not in self.SETTABLE[key]:
                raise CFError(f"{key} is one of {', '.join(self.SETTABLE[key])}, not {value}; nothing was written")
            plan.append((key, value))
        said = []
        for key, value in plan:
            was = self.call("GET", f"/settings/{key}")["result"].get("value")
            if str(was) == value:
                said.append(f"{key}: already {value}")
                continue
            now = self.call("PATCH", f"/settings/{key}", {"value": value})["result"].get("value")
            said.append(f"{key}: was {was}, now {now}")
        return said

    def origin_certificate(self, csr: str, hostnames: list[str], days: int = 5475,
                           key_type: str = "rsa") -> dict:
        """A Cloudflare Origin CA certificate for this zone's names, from a certificate
        request made on the server, whose key never leaves it (SSL and Certificates, Edit).
        The certificate is public; it is what the server shows Cloudflare."""
        csr = str(csr or "").strip()
        if "BEGIN CERTIFICATE REQUEST" not in csr:
            raise CFError("give the certificate request (CSR) in PEM, made on the server")
        names = [self._full(h) if not str(h).startswith("*.") else "*." + self._full(str(h)[2:])
                 for h in hostnames or []]
        if not names or any(not n for n in names):
            raise CFError("give the names the certificate is for, such as the zone and *.zone")
        if days not in (7, 30, 90, 365, 730, 1095, 5475):
            raise CFError("days is one of 7, 30, 90, 365, 730, 1095 or 5475")
        got = self.call("POST", "/certificates", {
            "csr": csr, "hostnames": names, "requested_validity": days,
            "request_type": "origin-ecc" if key_type == "ecc" else "origin-rsa"})["result"] or {}
        return {"id": got.get("id"), "certificate": got.get("certificate"),
                "expires_on": got.get("expires_on"), "hostnames": got.get("hostnames") or names}

    def origin_certificates(self) -> list[dict]:
        """The zone's Cloudflare Origin CA certificates, as Cloudflare lists them (SSL and
        Certificates): each one's id, names, expiry and public PEM. Reads only, and no
        private key is ever involved: Cloudflare never had one (task 165, 2 November 2026:
        a certificate made earlier could not be read back to be installed)."""
        got = self.call("GET", f"/certificates?zone_id={urllib.parse.quote(self.zone_id)}")["result"] or []
        return [{"id": c.get("id"), "hostnames": list(c.get("hostnames") or []),
                 "expires_on": c.get("expires_on"), "certificate": c.get("certificate") or ""}
                for c in got if isinstance(c, dict)]

    @staticmethod
    def _same_content(kind: str, a, b) -> bool:
        """Whether two contents of a record of `kind` are the same: a trailing dot never counts,
        nor the quotes round a TXT; an address is compared as an address, a host name in any case."""
        a, b = str(a or "").strip(), str(b or "").strip()
        if kind == "TXT":
            a, b = a.strip('"'), b.strip('"')
        a, b = a.rstrip("."), b.rstrip(".")
        if kind in ("A", "AAAA"):
            import ipaddress
            try:
                return ipaddress.ip_address(a) == ipaddress.ip_address(b)
            except ValueError:
                return a == b
        if kind in ("CNAME", "MX", "NS", "PTR"):
            return a.lower() == b.lower()
        return a == b

    def dns_delete(self, record) -> dict:
        """Delete exactly one DNS record of the zone, named by its type, full name and content,
        and give it back as it was, so it can be made again with dns_set.

        One record a call, always: a list, a missing field, a wildcard (`*` anywhere), or a
        record that matches none or more than one of the zone's is refused before anything is
        deleted. Never by type alone, never by name alone."""
        if not isinstance(record, dict):
            raise CFError("give one record, {type, name, content}; one record is deleted a call, never a list, so nothing was deleted")
        kind = str(record.get("type") or "").upper().strip()
        raw_name = str(record.get("name") or "").strip()
        content = str(record.get("content") or "").strip()
        if not kind or not raw_name or not content:
            raise CFError("the record needs its type, its full name and its content, all three; nothing was deleted")
        if "*" in kind or "*" in raw_name or "*" in content:
            raise CFError("no wildcards: name the one record exactly; nothing was deleted")
        name = self._full(raw_name)
        if not name:
            raise CFError("the record needs its full name; nothing was deleted")
        have = self.call("GET", "/dns_records?per_page=500")["result"] or []
        found = [r for r in have if str(r.get("type") or "").upper() == kind
                 and str(r.get("name") or "").rstrip(".").lower() == name
                 and self._same_content(kind, r.get("content"), content)]
        if not found:
            raise CFError(f"{self.zone} has no {kind} {name} -> {content}; nothing was deleted")
        if len(found) > 1:
            raise CFError(f"{len(found)} records of {self.zone} match {kind} {name} -> {content}; "
                          f"one is deleted a call, so nothing was deleted")
        r = found[0]
        self.call("DELETE", f"/dns_records/{r['id']}")
        was = {k: r.get(k) for k in ("type", "name", "content", "proxied", "ttl", "priority", "comment")
               if r.get(k) not in (None, "")}
        log.info("cloudflare: deleted %s %s -> %s from %s", r.get("type"), r.get("name"), r.get("content"), self.zone)
        return {"id": r.get("id"), "deleted": was}

    # --- Email Routing (2 November 2026: mail forwarding for a zone, set up through the API
    # rather than clicked through the dashboard, as ‹owner›'s standing rule has it). Rules and
    # the switch are the zone's (Email Routing Rules Edit); destination addresses are the
    # account's (Email Routing Addresses Edit). No DNS record is removed or replaced unless the
    # call says replace_mx, and only the MX records and the SPF record Email Routing needs are
    # ever touched: DKIM, DMARC and every other record are left as they are.

    def _need(self, permission: str, method: str, path: str, body=None) -> dict:
        """A call that, refused for want of a permission, says which one, in Cloudflare's name."""
        try:
            return self.call(method, path, body)
        except CFError as e:
            if e.denied:
                raise CFError(f"Cloudflare refused it ({e}): the token kept for {self.zone} needs "
                              f"{permission}. Add it to that token at Cloudflare (API Tokens, Edit), then "
                              f"run check again; there is nothing to paste", codes=e.codes, status=e.status) from None
            raise

    def _account(self) -> str:
        if not self.account_id:
            got = self.call("GET", f"/zones/{self.zone_id}")["result"] or {}
            self.account_id = str((got.get("account") or {}).get("id") or "")
            if not self.account_id:
                raise CFError(f"Cloudflare did not say which account {self.zone} is in")
        return self.account_id

    def email_required(self) -> list[dict]:
        """The DNS records Email Routing needs in this zone, as Cloudflare lists them."""
        got = self._need(EMAIL_RULES, "GET", "/email/routing/dns")["result"]
        if isinstance(got, dict):                   # the newer shape: {"record": [...], "errors": [...]}
            got = got.get("record") or got.get("records") or []
        return [{"type": str(r.get("type") or "").upper(), "name": str(r.get("name") or self.zone).rstrip(".").lower(),
                 "content": str(r.get("content") or ""), "priority": r.get("priority")}
                for r in got or [] if isinstance(r, dict)]

    def email_plan(self) -> dict:
        """What Email Routing needs against what the zone holds: {"present", "missing",
        "conflicts"}. A conflict is an MX record at the zone's own name that is not Cloudflare's
        (removed, with replace_mx) or an SPF record there without what Email Routing needs
        (changed in place, everything it already allows kept, with replace_mx)."""
        need = self.email_required()
        have = self.call("GET", "/dns_records?per_page=500")["result"] or []
        mx_wanted = {_host(r["content"]) for r in need if r["type"] == "MX"}
        spf_wanted = next((r for r in need if r["type"] == "TXT" and _is_spf(r["content"])), None)
        apex = [r for r in have if str(r.get("name") or "").rstrip(".").lower() == self.zone]
        spfs = [r for r in apex if r.get("type") == "TXT" and _is_spf(r.get("content"))]
        if spf_wanted and len(spfs) > 1:
            raise CFError(f"{self.zone} has {len(spfs)} SPF records ({'; '.join(str(r.get('content')) for r in spfs)}), "
                          f"which is invalid and cannot be merged safely; make it one first. Nothing was changed")
        conflicts = [{"id": r.get("id"), "type": "MX", "name": self.zone, "content": str(r.get("content")),
                      "priority": r.get("priority"), "do": "remove"}
                     for r in apex if r.get("type") == "MX" and _host(r.get("content")) not in mx_wanted]
        if spf_wanted and spfs:
            merged = _spf_merge(str(spfs[0].get("content") or ""), spf_wanted["content"])
            if merged != str(spfs[0].get("content") or ""):
                conflicts.append({"id": spfs[0].get("id"), "type": "TXT", "name": self.zone,
                                  "content": str(spfs[0].get("content")), "do": "change", "to": merged,
                                  "ttl": spfs[0].get("ttl") or 1})
        present, missing = [], []
        for r in need:
            if r["type"] == "MX":
                ok = any(h.get("type") == "MX" and _host(h.get("content")) == _host(r["content"])
                         and str(h.get("name") or "").rstrip(".").lower() == r["name"] for h in have)
            elif r is spf_wanted:
                ok = bool(spfs) and _spf_merge(str(spfs[0].get("content") or ""), r["content"]) == str(spfs[0].get("content") or "")
            else:
                ok = any(h.get("type") == r["type"] and str(h.get("name") or "").rstrip(".").lower() == r["name"]
                         and str(h.get("content") or "").strip('"') == r["content"].strip('"') for h in have)
            (present if ok else missing).append(r)
        return {"present": present, "missing": missing, "conflicts": conflicts}

    def email_addresses(self) -> list[dict]:
        acc = self._account()
        got = self._need(EMAIL_ADDRESSES, "GET", f"/accounts/{acc}/email/routing/addresses?per_page=50")["result"]
        return [a for a in got or [] if isinstance(a, dict)]

    def email_status(self) -> list[str]:
        """Whether Email Routing is on and its records right, the destination addresses and
        whether each is verified, the rules and the catch-all. Reads only; each part refused
        for want of a permission says which, and the rest is still said."""
        said = []
        try:
            got = self._need(EMAIL_RULES, "GET", "/email/routing")["result"] or {}
            said.append(f"Email Routing is {'on' if got.get('enabled') else 'off'}"
                        + (f" (Cloudflare says {got.get('status')})" if got.get("status") else ""))
        except CFError as e:
            said.append(f"whether Email Routing is on: unreadable ({e})")
        try:
            plan = self.email_plan()
            said.append("DNS records it needs: " + ("all present" if not plan["missing"] else
                        f"{len(plan['present'])} present, missing {_and([_rec(r) for r in plan['missing']])}"))
            for c in plan["conflicts"]:
                said.append("in the way: " + _conflict(c))
        except CFError as e:
            said.append(f"its DNS records: unreadable ({e})")
        try:
            addrs = self.email_addresses()
            said.append("destination addresses: " + (_and([
                f"{a.get('email')} ({'verified' if a.get('verified') else 'NOT verified yet'})" for a in addrs])
                if addrs else "none"))
        except CFError as e:
            said.append(f"destination addresses: unreadable ({e})")
        try:
            rules = self._need(EMAIL_RULES, "GET", "/email/routing/rules?per_page=50")["result"] or []
            rules = [r for r in rules if not any(m.get("type") == "all" for m in r.get("matchers") or [])]
            said.append("rules: " + (_and([_rule(r) for r in rules]) if rules else "none"))
            catch = self._need(EMAIL_RULES, "GET", "/email/routing/rules/catch_all")["result"] or {}
            said.append("catch-all: " + (_does(catch) if catch.get("enabled") else "off"))
        except CFError as e:
            said.append(f"rules: unreadable ({e})")
        return said

    def email_enable(self, replace_mx: bool = False) -> list[str]:
        """Turn Email Routing on. When an MX record that is not Cloudflare's, or an SPF record
        without Email Routing's include, is in the way, nothing is changed and each record is
        named, unless `replace_mx`: then those MX records are removed and the SPF record is
        changed in place to add what Email Routing needs, keeping everything it already allowed.
        No other record is touched."""
        plan = self.email_plan()
        said = []
        if plan["conflicts"] and not replace_mx:
            return ([f"Nothing was changed. Turning Email Routing on for {self.zone} would replace "
                     f"{len(plan['conflicts'])} record{'s' if len(plan['conflicts']) != 1 else ''}:"]
                    + ["- " + _conflict(c) for c in plan["conflicts"]]
                    + ["Mail sent to those MX hosts stops arriving once they go. Call email_routing_enable "
                       "again with replace_mx true to do exactly this; no other record is touched."])
        for c in plan["conflicts"]:
            if c["do"] == "remove":
                self.call("DELETE", f"/dns_records/{c['id']}")
                said.append(f"removed MX {c['content']}" + (f" (priority {c['priority']})" if c.get("priority") is not None else ""))
            else:
                self.call("PUT", f"/dns_records/{c['id']}", {"type": "TXT", "name": self.zone,
                                                              "content": c["to"], "ttl": int(c.get("ttl") or 1)})
                said.append(f"SPF changed from {c['content']} to {c['to']}")
        # The zone's apex is enabled by sending no name at all: `name` is only for a subdomain,
        # and Cloudflare refuses the zone's own name there ("2007: Invalid Input: must be a
        # subdomains of <zone>"), which is what stopped rouh.land's enable on 2 November 2026.
        try:
            self._need(EMAIL_RULES, "POST", "/email/routing/dns", {})
        except CFError as e:
            if e.status not in (404, 405):
                raise CFError("; ".join(said + [f"turning Email Routing on was refused: {e}"]) if said else str(e),
                              codes=e.codes, status=e.status) from None
            self._need(EMAIL_RULES, "POST", "/email/routing/enable", {})
        got = self._need(EMAIL_RULES, "GET", "/email/routing")["result"] or {}
        said.append(f"Email Routing is {'on' if got.get('enabled') else 'still off'}"
                    + (f" (Cloudflare says {got.get('status')})" if got.get("status") else ""))
        after = self.email_plan()
        said.append("its DNS records: " + ("all present" if not after["missing"] else
                    "still missing " + _and([_rec(r) for r in after["missing"]])))
        said.append("no other record was touched")
        return said

    def email_destination(self, email: str) -> list[str]:
        """Add a destination address to the zone's account. Cloudflare emails it a link, and
        rules deliver to it only once that link is clicked; one already there is not sent again."""
        email = str(email or "").strip().lower()
        if not _EMAIL.match(email):
            raise CFError("give the destination as an email address, such as someone@example.com")
        for a in self.email_addresses():
            if str(a.get("email") or "").lower() == email:
                return [f"{email} is already a destination address"
                        + (", verified: rules may forward to it." if a.get("verified") else
                           ", NOT verified yet: Cloudflare emailed it a verification link when it was added, "
                           "and its owner must click it before any rule delivers there. Nothing was sent again.")]
        acc = self._account()
        got = self._need(EMAIL_ADDRESSES, "POST", f"/accounts/{acc}/email/routing/addresses", {"email": email})["result"] or {}
        if got.get("verified"):
            return [f"{email} is now a destination address, already verified: rules may forward to it."]
        return [f"{email} is now a destination address, NOT verified yet. Cloudflare has emailed it a "
                "verification link, which its owner must click; until then no rule delivers there, and "
                "email_routing_rule refuses to point at it."]

    def email_rule(self, address: str, to: str, catch_all: bool = False) -> list[str]:
        """Forward one address of the zone, or the catch-all, to a verified destination,
        making the rule or changing the one already there for that address."""
        to = str(to or "").strip().lower()
        if not _EMAIL.match(to):
            raise CFError("give the destination ('to') as an email address")
        found = next((a for a in self.email_addresses() if str(a.get("email") or "").lower() == to), None)
        if found is None:
            raise CFError(f"{to} is not a destination address yet: add it with email_routing_destination, "
                          f"have its owner click the link Cloudflare emails it, then make the rule. Nothing was changed")
        if not found.get("verified"):
            raise CFError(f"{to} is not verified yet: its owner must click the link Cloudflare emailed it, "
                          f"and only then can a rule forward to it. Nothing was changed")
        action = [{"type": "forward", "value": [to]}]
        if catch_all:
            was = self._need(EMAIL_RULES, "GET", "/email/routing/rules/catch_all")["result"] or {}
            if was.get("enabled") and _forwards(was) == [to]:
                said = [f"catch-all: already forwards to {to}"]
            else:
                self._need(EMAIL_RULES, "PUT", "/email/routing/rules/catch_all", {
                    "actions": action, "matchers": [{"type": "all"}], "enabled": True,
                    "name": f"Everything else to {to}"})
                said = [f"catch-all: now forwards to {to}; until now: {_does(was) if was.get('enabled') else 'off'}"]
        else:
            address = str(address or "").strip().lower()
            if address and "@" not in address:
                address = f"{address}@{self.zone}"
            domain = address.rpartition("@")[2]
            if not _EMAIL.match(address) or not (domain == self.zone or domain.endswith("." + self.zone)):
                raise CFError(f"give the address mail is sent to ('from') in {self.zone}, such as noreply@{self.zone}, "
                              "or catch_all true")
            rules = self._need(EMAIL_RULES, "GET", "/email/routing/rules?per_page=50")["result"] or []
            mine = next((r for r in rules if any(m.get("type") == "literal" and m.get("field") == "to"
                                                 and str(m.get("value") or "").lower() == address
                                                 for m in r.get("matchers") or [])), None)
            body = {"actions": action, "matchers": [{"type": "literal", "field": "to", "value": address}],
                    "enabled": True, "name": f"{address} to {to}"}
            if mine is None:
                self._need(EMAIL_RULES, "POST", "/email/routing/rules", body)
                said = [f"{address}: now forwards to {to} (a new rule)"]
            elif mine.get("enabled") and _forwards(mine) == [to]:
                said = [f"{address}: already forwards to {to}"]
            else:
                rid = mine.get("id") or mine.get("tag")
                self._need(EMAIL_RULES, "PUT", f"/email/routing/rules/{rid}",
                           {**body, "name": mine.get("name") or body["name"],
                            **({"priority": mine["priority"]} if mine.get("priority") is not None else {})})
                said = [f"{address}: now forwards to {to}; until now: {_does(mine) if mine.get('enabled') else 'off'}"]
        try:
            if not (self.call("GET", "/email/routing")["result"] or {}).get("enabled"):
                said.append("Email Routing is off for this zone, so nothing is delivered until email_routing_enable turns it on")
        except CFError:
            pass
        return said


_EMAIL = re.compile(r"^[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
_SPF_ALL = re.compile(r"^[~+?-]?all$")


def _host(content) -> str:
    return str(content or "").strip().rstrip(".").lower()


def _is_spf(content) -> bool:
    return str(content or "").strip().strip('"').lower().startswith("v=spf1")


def _spf_merge(have: str, wanted: str) -> str:
    """`have` with every mechanism of `wanted` it lacks put in before its `all`, so what it
    already allows (Brevo's include, say) still is. Quoted as it was."""
    quoted = have.strip().startswith('"')
    terms = have.strip().strip('"').split()
    lower = [t.lower() for t in terms]
    add = [t for t in wanted.strip().strip('"').split()[1:]
           if not _SPF_ALL.match(t.lower()) and t.lower() not in lower]
    if not add:
        return have
    at = next((i for i, t in enumerate(lower) if _SPF_ALL.match(t)), len(terms))
    merged = " ".join(terms[:at] + add + terms[at:])
    return f'"{merged}"' if quoted else merged


def _rec(r: dict) -> str:
    return f"{r['type']} {r['name']} {r['content']}" + (f" (priority {r['priority']})" if r.get("priority") is not None else "")


def _conflict(c: dict) -> str:
    if c["do"] == "remove":
        return f"MX {c['name']} {c['content']}" + (f" (priority {c['priority']})" if c.get("priority") is not None else "") + " would be removed"
    return f"SPF TXT {c['name']} would change from {c['content']} to {c['to']}"


def _forwards(rule: dict) -> list[str]:
    return [str(v).lower() for a in rule.get("actions") or [] if a.get("type") == "forward" for v in a.get("value") or []]


def _does(rule: dict) -> str:
    acts = rule.get("actions") or []
    if any(a.get("type") == "forward" for a in acts):
        return "forwards to " + _and(_forwards(rule) or ["?"])
    if any(a.get("type") == "worker" for a in acts):
        return "goes to a Worker"
    return "drops the mail"


def _rule(rule: dict) -> str:
    to = [str(m.get("value")) for m in rule.get("matchers") or [] if m.get("type") == "literal"]
    return f"{_and(to or ['?'])} {_does(rule)}" + ("" if rule.get("enabled", True) else " (off)")


def zone_api(zone: str, org_id: str | None = None) -> ZoneAPI:
    org = _org(org_id)
    row = _row(org, zone)
    token = cloudflare_token(zone, org)
    zid, acc = row.zone_id, row.account_id
    if not zid:
        found = [z for z in (call(token, "GET", f"/zones?name={urllib.parse.quote(row.zone)}")["result"] or [])
                 if z.get("name") == row.zone]
        if not found:
            raise CFError(f"the token kept for {row.zone} cannot see it")
        zid = str(found[0]["id"])
        acc = acc or str((found[0].get("account") or {}).get("id") or "")
        _model().objects.filter(id=row.id, org_id=org).update(zone_id=zid, **({"account_id": acc} if acc else {}))
    return ZoneAPI(row.zone, zid, token, acc)
