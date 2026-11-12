"""CONTAINERS.md, "Every other gene and page": each of Rouh's genes, and each page it serves, that
no other row covers, checked on the running stack as the person uses it.

Each check opens the page's own address, signed in as the owner the first run made, and asks the
page's own API for what the page draws, and where the page does something (a goal set, a thought
kept, a rule added, a page shared), does it and reads it back. Where a gene has no page of its own,
its tool is called through the stand-in model, as the model would call it. Where a gene only
changes what a turn or a run is told, its own words are asked for in the core, from its own module,
with words that should bring it on and words that should not.
"""
from __future__ import annotations

import json
import shlex
import time
import urllib.parse
import urllib.request

from smoke import Failed, Stack, check, expect


# --- the page's own HTTP ---------------------------------------------------------------------------

def _csrf(s: Stack) -> str:
    for part in s.cookie.split(";"):
        name, _, value = part.strip().partition("=")
        if name == "rouh_csrftoken":
            return value
    return ""


def _send(s: Stack, path: str, body: dict | None = None, *, method: str = "POST",
          cookie: bool = True) -> tuple[int, dict]:
    """A request as the page sends it, with its CSRF header; the status and the JSON it answered."""
    headers = {"Content-Type": "application/json", "Origin": s.url, "Referer": s.url + "/"}
    if cookie:
        headers |= {"Cookie": s.cookie, "X-CSRFToken": _csrf(s)}
    req = urllib.request.Request(s.url + path, data=json.dumps(body or {}).encode(), method=method,
                                 headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            code, raw = r.status, r.read()
    except urllib.error.HTTPError as e:
        code, raw = e.code, e.read()
    try:
        return code, json.loads(raw or b"{}")
    except ValueError:
        return code, {"_text": raw.decode("utf-8", "replace")[:600]}


def post(s: Stack, path: str, body: dict | None = None) -> dict:
    code, got = _send(s, path, body)
    expect(code == 200, f"POST {path} answered {code}: {json.dumps(got)[:400]}")
    return got


def api(s: Stack, path: str, *keys: str) -> dict:
    """GET one of the page's own addresses: 200, JSON, with every key named."""
    code, body, _ = s.get(path)
    expect(code == 200, f"{path} answered {code}: {body[:300]}")
    try:
        got = json.loads(body)
    except ValueError:
        raise Failed(f"{path} did not answer JSON: {body[:300]}")
    missing = [k for k in keys if k not in got]
    expect(not missing, f"{path} has no {', '.join(missing)}: {body[:400]}")
    return got


def page(s: Stack, path: str, has: str = "") -> str:
    """The page's own address answers with Rouh's page (or its own), signed in."""
    code, body, _ = s.get(path)
    expect(code == 200 and "<html" in body.lower(), f"{path} answered {code}: {body[:200]}")
    expect("/login" not in body[:600], f"{path} sent the owner to the sign-in page")
    if has:
        expect(has.lower() in body.lower(), f"{path} does not say {has!r}: {body[:300]}")
    return body


def opens(path: str, api_path: str, *keys: str):
    """A page that is its address and what its API hands it."""
    def fn(s: Stack) -> None:
        page(s, path)
        api(s, api_path, *keys)
    return fn


def core_py(s: Stack, code: str, timeout: float = 120) -> str:
    """Python in the core with Rouh's Django set up; what it printed."""
    return s.manage(code, timeout=timeout)


def task_folder(s: Stack, title: str) -> str:
    """A task of the owner's, made through Rouh's own tool, and its folder in the workspace, once
    Rouh has filed it into the project it belongs to (a new task starts in unfiled/)."""
    s.chat = ""
    s.tool("make_a_task", {"title": title})
    found, end = "", time.time() + 90
    while time.time() < end:
        tasks = api(s, "/api/workspace/index", "tasks")["tasks"]
        mine = [t["rel"] for t in tasks if (t.get("name") or "").strip().lower() == title.lower()]
        if mine:
            found = mine[0]
            if not found.startswith("unfiled/"):
                return found
        time.sleep(3)
    expect(found, f"the task {title!r} never reached the task list")
    return found


# --- the heartbeat, its beats, quests, goals, decisions --------------------------------------------

@check("page.heartbeat")
def heartbeat_page(s: Stack) -> None:
    """Anatomy, Behaviour, Heartbeat: its state, and a beat now, as Beat now does."""
    page(s, "/anatomy/behaviour/heartbeat")
    api(s, "/api/heartbeat", "state", "config", "beats")
    got = post(s, "/api/heartbeat/act", {"act": "now"})
    expect(got.get("ok"), f"Beat now: {json.dumps(got)[:400]}")


@check("page.beats")
def beats_page(s: Stack) -> None:
    page(s, "/anatomy/behaviour/beats")
    api(s, "/api/heartbeat/beats", "beats", "total", "limits")


check("page.quests")(opens("/quests", "/api/quests", "quests"))


@check("page.goals")
def goals_page(s: Stack) -> None:
    """The Goals page: a goal set there is on the page."""
    page(s, "/goals")
    post(s, "/api/goals/save", {"name": "Stack test goal", "about": "A goal the stack test set"})
    listed = json.dumps(api(s, "/api/goals", "goals")["goals"])
    expect("stack test goal" in listed.lower(), f"the goal is not on the page: {listed[:300]}")


check("page.decisions")(opens("/decisions", "/api/decisions", "open", "history", "counts"))


# --- the morning brief, receipts, the control room -------------------------------------------------

@check("page.brief")
def brief_page(s: Stack) -> None:
    """The morning brief, made now as Make it now makes it, and its settings."""
    page(s, "/brief")
    got = post(s, "/api/brief/make", {})
    expect(got.get("ok") and got.get("brief"), f"Make the brief: {json.dumps(got)[:400]}")
    api(s, "/api/brief", "brief", "schedule")
    api(s, "/api/brief/past", "briefs")
    page(s, "/anatomy/behaviour/brief")
    api(s, "/api/settings/brief", "on", "time")


check("page.receipts")(opens("/receipts", "/api/receipts", "month", "rows", "totals"))
check("page.control")(opens("/control", "/api/control", "clusters"))


# --- thoughts, boxes, rules, agent instructions ----------------------------------------------------

@check("page.thoughts")
def thoughts_page(s: Stack) -> None:
    page(s, "/thoughts")
    post(s, "/api/thoughts/new", {"words": "A thought the stack test had about plain words"})
    listed = json.dumps(api(s, "/api/thoughts", "thoughts")["thoughts"])
    expect("stack test had" in listed, f"the thought is not on the page: {listed[:300]}")


@check("page.box")
def box_page(s: Stack) -> None:
    """A sealed box made on the Boxes page opens again with what was put in it."""
    page(s, "/box")
    made = post(s, "/api/box/new", {"label": "Stack test box", "content": "the stack test's secret 4471"})
    ident = (made.get("box") or {}).get("id")
    expect(ident, f"the box was not made: {json.dumps(made)[:300]}")
    opened = api(s, f"/api/box/{ident}", "box")
    expect("4471" in json.dumps(opened), f"the box did not open with what was put in: {json.dumps(opened)[:300]}")


@check("page.rules")
def rules_page(s: Stack) -> None:
    """The Rules page: the defaults every Rouh starts with are on it and none is locked, every rule says when
    it is told, a rule added there is listed with its Conditions line, with its Agent switch on it is in what an
    agent starts with, and deleted it is gone from both. Since 30 October 2026 (94d047d5) there are no built-in
    rules: every rule is the person's, and the agent instructions are rules with their Agent switch on."""
    page(s, "/rules")
    rows = api(s, "/api/rules", "rows", "groups", "sections")["rows"]
    defaults = [r for r in rows if r.get("kind") == "rule" and r.get("defaults")]
    expect(defaults, "the page has none of the defaults every Rouh starts with")
    expect(all(str(r.get("conditions") or "").strip() for r in rows if r.get("kind") == "rule"),
           "a rule on the page has no Conditions line")
    one = defaults[0]["ref"]
    post(s, "/api/rules/enable", {"ref": one, "on": False})
    off = next((r for r in api(s, "/api/rules", "rows")["rows"] if r["ref"] == one), None)
    expect(off is not None and not off.get("on"), f"a default rule could not be turned off: {json.dumps(off)[:300]}")
    post(s, "/api/rules/enable", {"ref": one, "on": True})
    got = post(s, "/api/rules/add", {"text": "The stack test asks for short answers, word basalt-9"})
    rows = api(s, "/api/rules", "rows")["rows"]
    mine = [r for r in rows if "basalt-9" in json.dumps(r)]
    expect(mine, f"the rule is not on the page: {json.dumps(got)[:300]}")
    expect(str(mine[0].get("conditions") or "").strip(), f"the rule has no Conditions line: {json.dumps(mine[0])[:300]}")
    expect(str(mine[0].get("ref") or "").startswith("r:"),
           f"the new rule is not an ordinary rule: {mine[0].get('ref')}")
    post(s, "/api/rules/switch", {"ref": mine[0]["ref"], "which": "agent", "on": True})
    text = api(s, "/api/agent-instructions/preview", "text")["text"]
    expect("basalt-9" in text, f"the rule with its Agent switch on is not in what an agent starts with: {text[:300]}")
    post(s, "/api/rules/delete", {"ref": mine[0]["ref"]})
    left = [r for r in api(s, "/api/rules", "rows")["rows"] if "basalt-9" in json.dumps(r)]
    expect(not left, "the rule was not deleted")
    expect("basalt-9" not in api(s, "/api/agent-instructions/preview", "text")["text"],
           "the deleted rule is still in what an agent starts with")


@check("page.agent-instructions")
def agent_instructions_page(s: Stack) -> None:
    """The Agent instructions page: one added there is in what a run is handed."""
    page(s, "/agent-instructions")
    groups = api(s, "/api/agent-instructions", "groups")["groups"]
    expect(groups, "the page has no groups")
    post(s, "/api/agent-instructions/add", {"title": "Stack test instruction", "group_id": groups[0].get("id"),
                                             "text": "Say the word quartz-7 when you start."})
    text = api(s, "/api/agent-instructions/preview", "text")["text"]
    expect("quartz-7" in text, f"the new instruction is not in what a run is handed: {text[:300]}")


# --- Anatomy: the person, the money, the machine ---------------------------------------------------

@check("page.anatomy")
def anatomy_page(s: Stack) -> None:
    """Anatomy, its six groups' pages, each drawn from the genes."""
    page(s, "/anatomy")
    groups = api(s, "/api/anatomy", "groups")["groups"]
    expect(len(groups) == 6, f"Anatomy has {len(groups)} groups, not six")
    for g in ("you", "your-rouh", "connections", "behaviour", "money", "meta"):
        page(s, f"/anatomy/{g}")
    # What moved on 4 November 2026 left nothing behind: its old addresses are not found, and
    # rouh.land's own return address answers only a return with a code (`addressing.ROUH_LAND_RETURN`).
    for old in ("/anatomy/meta/birthday", "/anatomy/rouh-land/models", "/anatomy/meta/genes", "/anatomy/meta/offline",
                "/anatomy/rouh-land/your-profile", "/anatomy/rouh-land/rouh-profile", "/anatomy/connections/phone",
                "/anatomy/rouh-land/gene-pool", "/login/recover",
                "/anatomy/connections/trusted-contacts", "/settings/models", "/settings/birthday", "/settings/genes",
                "/settings/trusted-contacts", "/settings/offline", "/anatomy/you/profile", "/settings/profile"):
        code, body, _ = s.get(old, follow=False)
        expect(code == 404, f"{old} answered {code}, not 404: {body[:200]}")
    code, _, headers = s.get("/anatomy/meta/birthday?birth=abc", follow=False)
    where = {k.lower(): v for k, v in headers.items()}.get("location", "")
    expect(code in (301, 302) and where.startswith("/anatomy/your-rouh?birth=abc"),
           f"rouh.land's return answered {code} {where}")


@check("page.profile")
def profile_page(s: Stack) -> None:
    """You, About You (Profile until 4 November 2026): a nickname is kept, and who you are and your
    company are kept on your own contact card."""
    page(s, "/anatomy/you/about-you")
    post(s, "/api/settings/profile", {"nickname": "Lex"})
    got = api(s, "/api/settings/profile", "first_name", "nickname", "card_about", "card_company")
    expect(got["nickname"] == "Lex", f"the nickname was not kept: {got['nickname']!r}")
    post(s, "/api/settings/profile", {"card_company": "Example Studio", "card_about": "Runs a small studio."})
    got = api(s, "/api/settings/profile", "card_about", "card_company")
    expect(got["card_company"] == "Example Studio" and got["card_about"] == "Runs a small studio.",
           f"the contact card did not keep them: {json.dumps(got)[:300]}")


@check("page.account")
def account_page(s: Stack) -> None:
    """You, Account: who is signed in; and with no sign-in, Rouh's page is the sign-in page."""
    page(s, "/anatomy/you/account")
    expect(api(s, "/api/settings/profile", "username")["username"] == "alex@example.com", "the wrong owner is signed in")
    code, body, headers = s.get("/", cookie=False, follow=False)
    where = {k.lower(): v for k, v in headers.items()}.get("location", "")
    expect(code in (301, 302, 303, 401) and "/login" in where + body[:300],
           f"with no sign-in, / answered {code} {where} {body[:200]}")


@check("page.location")
def location_page(s: Stack) -> None:
    """Location and time: a point the page reports is kept, and its clock with it."""
    page(s, "/anatomy/you/location")
    post(s, "/api/settings/location", {"lat": 38.7223, "lon": -9.1393, "accuracy": 30, "asked": True})
    got = api(s, "/api/settings/location", "location", "zone")
    expect((got.get("location") or {}).get("lat") == 38.7223, f"the location was not kept: {json.dumps(got)[:300]}")


@check("page.silos")
def silos_page(s: Stack) -> None:
    """Silos: one added is on the page, and taken out is gone."""
    page(s, "/anatomy/you/silos")
    post(s, "/api/settings/silos/add", {"name": "Stack test silo"})
    silos = api(s, "/api/settings/silos", "silos", "rules")["silos"]
    mine = [x for x in silos if x.get("name") == "Stack test silo"]
    expect(mine, f"the silo is not on the page: {[x.get('name') for x in silos]}")
    post(s, "/api/settings/silos/remove", {"key": mine[0].get("key")})
    silos = api(s, "/api/settings/silos", "silos")["silos"]
    expect(not [x for x in silos if x.get("name") == "Stack test silo"], "the silo was not taken out")


@check("page.models")
def models_page(s: Stack) -> None:
    """Anatomy, Behaviour, Models: the mode, the tiers and every use, as the page draws them."""
    page(s, "/anatomy/behaviour/models")
    got = api(s, "/api/settings/models", "mode", "modes")
    expect(got["mode"] in [m.get("id") for m in got["modes"]], f"the mode is not one of the modes: {got['mode']}")


@check("page.services")
def services_page(s: Stack) -> None:
    """Money, Services: a service added is in the list, with what it costs."""
    page(s, "/anatomy/money/services")
    post(s, "/api/settings/services", {"name": "Stack test service", "amount": 5, "currency": "EUR",
                                       "period": "month"})
    listed = json.dumps(api(s, "/api/settings/services", "services")["services"])
    expect("Stack test service" in listed, f"the service is not in the list: {listed[:300]}")


@check("page.payments")
def payments_page(s: Stack) -> None:
    """Money, Payments: a billing entity added is on the page."""
    page(s, "/anatomy/money/payments")
    post(s, "/api/payments/entity", {"label": "Stack Test Ltd", "address": {
        "line1": "1 Test Street", "city": "Lisbon", "postal_code": "1000-001", "country": "PT"}})
    listed = json.dumps(api(s, "/api/payments", "cards", "entities", "permissions")["entities"])
    expect("Stack Test Ltd" in listed, f"the entity is not on the page: {listed[:300]}")


@check("page.shipping")
def shipping_page(s: Stack) -> None:
    """Money, Shipping: who receives a parcel is kept."""
    page(s, "/anatomy/money/shipping")
    post(s, "/api/shipping/recipient", {"name": "Alex Morgan", "phone": "+351 210 000 000"})
    got = api(s, "/api/shipping", "options", "situations", "recipient")
    expect(got["recipient"].get("phone") == "+351 210 000 000", f"the recipient was not kept: {got['recipient']}")


@check("page.signups")
def signups_page(s: Stack) -> None:
    """Money, Sign-ups: the hours a sign-up is allowed for and the grants given."""
    page(s, "/anatomy/money/signups")
    api(s, "/api/settings/signups", "hours", "grants")


@check("page.stats")
def stats_page(s: Stack) -> None:
    page(s, "/anatomy/meta/stats")
    page(s, "/anatomy/meta/stats/events")
    api(s, "/api/settings/stats", "navigation", "flow")


@check("gene.event-log")
def event_log(s: Stack) -> None:
    """What the page sends of what the person did is taken into the event log, and Stats counts it."""
    import uuid

    before = api(s, "/api/settings/stats/events", "totals", "per_day")["totals"]
    code, got = _send(s, "/api/events", {"session": "stack-test", "events": [
        {"id": str(uuid.uuid4()), "name": "ui.open", "at": time.time(), "props": {"path": "/tasks"}}]})
    expect(code == 202 and got.get("taken") == 1, f"the event log did not take the page's event: {code} {got}")
    end = time.time() + 30
    while time.time() < end:
        now = api(s, "/api/settings/stats/events", "totals")["totals"]
        if now != before:
            return
        time.sleep(2)
    raise Failed(f"Stats' event log did not count it: {before} then {now}")


@check("page.birthday")
def birthday_page(s: Stack) -> None:
    """Your Rouh (Rouh profile until 7 November 2026). The stack's first run picks On its own, so this is a free
    Rouh (4 November 2026): no birth, no name, no keys, a nickname that is kept, and one line."""
    page(s, "/anatomy/your-rouh")
    got = api(s, "/api/birth", "born", "standing")
    expect(got["born"] is False and got["standing"]["kind"] == "free",
           f"a Rouh set up on its own is not a free Rouh: {json.dumps(got)[:300]}")
    expect("rouh" not in got, f"a free Rouh is handed a birth: {json.dumps(got)[:300]}")
    post(s, "/api/birth/nickname", {"first": "", "last": "", "nickname": "Pip"})
    expect(api(s, "/api/birth", "nickname")["nickname"] == "Pip", "a free Rouh's nickname was not kept")


@check("page.genes")
def genes_page(s: Stack) -> None:
    """Meta, Gene registry: the shared genes installed, those there are, and the registry."""
    page(s, "/anatomy/meta/gene-pool")
    got = api(s, "/api/settings/genes", "registry", "installed", "available", "route")
    expect(got["route"] == "/anatomy/meta/gene-pool", f"a shared gene's page is under {got['route']}")


@check("page.rouh-land-account")
def rouh_land_account_page(s: Stack) -> None:
    """Your rouh.land account (You, Your account; on Your Rouh, its connection): whether you have a
    rouh.land account and whether this Rouh is connected to it, and no key or id of the Rouh's."""
    page(s, "/anatomy/you/account")
    got = api(s, "/api/rouh-land/account", "born", "connected", "has_account", "email", "role", "door",
              "account_url", "problem")
    expect(got["born"] is False, f"Your profile says a free Rouh is born: {json.dumps(got)[:300]}")
    expect(got["connected"] is False and got["problem"] is None,
           f"an independent Rouh is said to be connected, or in trouble: {json.dumps(got)[:300]}")
    for rouh_own in ("name", "registry_id", "registry_url", "connected_words", "checked_words"):
        expect(rouh_own not in got, f"Your profile carries the Rouh's own {rouh_own}")


@check("page.build")
def build_page(s: Stack) -> None:
    """Meta, This build: the session, the version and commit, and the day it was committed."""
    code, body, _ = s.get("/anatomy/meta/build")
    expect(code == 200 and 'id="verRev"' in body and 'id="sessId"' in body, f"This build answered {code}")


@check("page.home")
def home_page(s: Stack) -> None:
    page(s, "/home")
    got = api(s, "/api/home/lights", "connected")
    expect(got.get("said") or got.get("connected") is not None, json.dumps(got)[:300])
    api(s, "/api/home/vacuum", "connected")


@check("page.metabolism")
def metabolism_page(s: Stack) -> None:
    """Metabolism: the runs and the work there has been, and what it cost."""
    page(s, "/metabolism")
    api(s, "/api/job-requests", "total", "asks")
    api(s, "/api/spend", "today", "all_time")


@check("page.gaps")
def gaps_page(s: Stack) -> None:
    page(s, "/gaps", has="agent loop gaps")
    got = api(s, "/api/gaps", "gaps", "summary")
    expect(got["gaps"], "the gaps page lists nothing")


@check("gene.llm-request-log")
def llm_request_log(s: Stack) -> None:
    """Every request made of a model is written down with its cost: a turn's request is in the
    day's usage, and in the turn records' export."""
    s.say("Hello for the request log")
    days = api(s, "/api/usage/daily", "days")["days"]
    expect(days and days[0].get("requests", 0) >= 1, f"the day's usage counts no request: {json.dumps(days)[:300]}")
    code, body, _ = s.get("/api/turns/export")
    expect(code == 200 and "turn_id" in body, f"the turn records' export: {code} {body[:200]}")


@check("page.demo")
def demo_page(s: Stack) -> None:
    """Demo mode: turned on it is on, and turned off again."""
    post(s, "/api/demo", {"on": True})
    expect(api(s, "/api/demo", "on")["on"] is True, "demo mode did not turn on")
    post(s, "/api/demo", {"on": False})
    expect(api(s, "/api/demo", "on")["on"] is False, "demo mode did not turn off")


@check("page.offline")
def offline_page(s: Stack) -> None:
    """Offline: the page's service worker, the offline page, and every part of the sealed copy."""
    page(s, "/offline")
    page(s, "/anatomy/behaviour/offline")
    code, body, headers = s.get("/sw.js")
    kind = {k.lower(): v for k, v in headers.items()}.get("content-type", "")
    expect(code == 200 and "javascript" in kind, f"/sw.js answered {code}, {kind}")
    for part in ("calendar", "decisions", "tasks", "chats", "mail", "contacts"):
        code, body, _ = s.get(f"/api/offline/pack/{part}")
        expect(code == 200, f"the offline copy's {part} answered {code}: {body[:200]}")
    api(s, "/api/offline/outbox", "results")


# --- Evolution: parameters, mutations, the gene log, the Gene Pool ----------------------------------

@check("page.evolution-parameters")
def evolution_parameters(s: Stack) -> None:
    """Evolution, Parameters: the night's numbers, saved as they are, are kept as the person's."""
    page(s, "/evolution/parameters")
    got = api(s, "/api/evolution/parameters", "parameters", "schedule", "defaults")["parameters"]
    keep = {k: got[k] for k in ("total", "invisible", "shows_up", "ask_for", "changes_work") if k in got}
    post(s, "/api/evolution/parameters", keep)
    now = api(s, "/api/evolution/parameters", "parameters")["parameters"]
    expect(now.get("updated_at"), f"the parameters were not saved: {now}")


@check("page.mutations")
def mutations_page(s: Stack) -> None:
    """Evolution, Mutations: its views, the month and the gene log it reads every change into."""
    page(s, "/evolution/mutations")
    page(s, "/evolution/mutations/month")
    api(s, "/api/evolution/mutations", "views", "requests", "counts")
    api(s, "/api/evolution/month", "days", "genes")
    api(s, "/api/genes/log", "genes", "commits", "statuses")


@check("page.gene-pool")
def gene_pool_page(s: Stack) -> None:
    """Evolution, the Gene Pool: what this Rouh has joined, shares and is offered."""
    page(s, "/evolution/pool")
    page(s, "/evolution/pool/outgoing")
    api(s, "/api/genes/pool", "joined", "mode", "families")
    api(s, "/api/genes/pool/out", "rows", "mode")


@check("page.incubator")
def incubator_page(s: Stack) -> None:
    """Evolution, the Incubator: an idea added on its page is listed, opens whole, and takes a new category."""
    page(s, "/evolution/incubator")
    made = post(s, "/api/incubator/new", {"title": "Stack test idea", "text": "The stack test's own words, kept whole."})
    expect(made.get("ok"), f"the Incubator could not keep an idea: {made}")
    number = made["idea"]["number"]
    got = api(s, "/api/incubator", "ideas", "counts", "facts", "prefs")
    expect(any(v["number"] == number for v in got["ideas"]), "the idea added is not listed")
    one = api(s, f"/api/incubator/{number}", "idea")["idea"]
    expect(one["original"] == "The stack test's own words, kept whole.", f"its words came back changed: {one['original']!r}")
    moved = post(s, f"/api/incubator/{number}", {"category": "speed"})
    expect(moved["idea"]["category"] == "speed", f"its category did not change: {moved}")


@check("page.nightly-run")
def nightly_run_page(s: Stack) -> None:
    """Evolution, the nightly run's own page: its caps, its nights and its schedule, or that it has none."""
    page(s, "/evolution/nightly")
    got = api(s, "/api/evolution/nightly", "caps", "nights", "schedule", "ideas")
    expect(got["caps"].get("dollars") == 100 and got["caps"].get("services") == 2, f"its caps: {got['caps']}")


@check("page.trials")
def trials_page(s: Stack) -> None:
    """Evolution, Trials: its pages, a trial started from a run, a step it cannot take without a tester said
    plainly, and the list of problems with the owner's own confusion on it."""
    page(s, "/evolution/trials")
    page(s, "/evolution/trials/problems")
    got = api(s, "/api/trials", "trials", "counts", "personas", "default")
    expect({p["id"] for p in got["personas"]} >= {"vesela", "boris"} and got["default"] == "vesela",
           f"its personas: {got['personas']}, default {got['default']}")
    out = core_py(s, "import asyncio\nfrom rouh import trials\nfrom rouh.tenancy import Tenancy\n"
                     "me = Tenancy().only_person()\n"
                     "t = trials.start(me, goal='You want to see the list of tries.', subject='the Trials page', by='stack')\n"
                     "try:\n    asyncio.run(trials.step(me, t['number'], {'url': '/evolution/trials', 'text': 'Trials'}))\n"
                     "except Exception as exc:\n    print('STEP', type(exc).__name__)\n"
                     "print('BROKEN', trials.broken(me, t['number'], 'no tester in the stack test')['state'])\n"
                     "print('OWNER', trials.owner_said(me, 'this is so confusing'))\n")
    expect("BROKEN broken" in out and "OWNER [" in out and "OWNER []" not in out, f"a trial in the core: {out[-400:]}")
    got = api(s, "/api/trials/problems?source=owner", "problems", "counts", "screens")
    expect(any(p["source"] == "owner" for p in got["problems"]), f"the owner's confusion is not listed: {got}")
    one = api(s, f"/api/trials/{api(s, '/api/trials', 'trials')['trials'][0]['number']}", "trial")
    expect(one["trial"]["state"] == "broken", f"the trial: {one['trial']}")


# --- trusted contacts, approvals, sources ---------------------------------------------------------

@check("page.trusted-contacts")
def trusted_contacts_page(s: Stack) -> None:
    """Behaviour, Trusted contacts: the contacts, their levels and every grant they can be given."""
    page(s, "/anatomy/behaviour/trusted-contacts")
    page(s, "/anatomy/behaviour/trusted-contacts/grants")
    api(s, "/api/settings/trusted", "rows", "levels", "never")
    got = api(s, "/api/settings/grants", "grants", "limits")
    expect(got["grants"], "there are no grants to give")


@check("page.mail-approvals")
def mail_approvals_page(s: Stack) -> None:
    page(s, "/mail/approvals")
    api(s, "/api/mail/approvals", "queues", "waiting", "recent")


@check("gene.mail-replay")
def mail_replay(s: Stack) -> None:
    """Every kept case of a trusted contact's mail comes out as it must, judged in the core by the
    code a run of a case uses, and nothing but the outbox can send to a contact."""
    r = s.run("core", "cd /code && python -m rouh.mail_replay", timeout=300)
    expect(r.returncode == 0, f"the mail replay in the core: {(r.stdout + r.stderr)[-800:]}")


@check("page.sources")
def sources_page(s: Stack) -> None:
    page(s, "/sources")
    api(s, "/api/sources", "pages")


# --- the page in a real browser, and the files it loads ----------------------------------------------

def _asset(s: Stack, name: str) -> tuple[int, str, int]:
    """One of the page's own files, by the address the page loads it from (`/a/<stamp>/<name>`):
    its status, its type and its size."""
    import re

    _, body, _ = s.get("/")
    stamp = re.search(r'/a/([0-9a-f]+)/app\.js', body)
    expect(stamp, "Rouh's page names no app.js")
    req = urllib.request.Request(f"{s.url}/a/{stamp.group(1)}/{name}", headers={"Cookie": s.cookie})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.headers.get("Content-Type", ""), len(r.read())
    except urllib.error.HTTPError as e:
        return e.code, "", 0


def assets(*want: tuple[str, str]):
    """Files the page loads, each served with the type a browser will run it as."""
    def fn(s: Stack) -> None:
        for name, kind in want:
            code, got, size = _asset(s, name)
            expect(code == 200 and size > 0, f"{name} answered {code}")
            expect(kind in got, f"{name} is served as {got!r}, and a browser runs it only as {kind}")
    return fn


check("gene.voice-detection")(assets(("vad.js", "javascript"), ("ort.min.mjs", "javascript"),
                                     ("ort-wasm-simd-threaded.mjs", "javascript"),
                                     ("ort-wasm-simd-threaded.wasm", "application/wasm"),
                                     ("silero-vad.onnx", "")))
check("gene.orb-sound")(assets(("app/orb_sound.js", "javascript"), ("app/orb.js", "javascript")))
check("gene.falling-stars")(assets(("app/stars.js", "javascript")))


@check("page.in-browser")
def in_browser(s: Stack) -> None:
    """Rouh's page in a real Chromium, signed in: every file it loads answers, no script fails,
    and it goes live on its socket."""
    from playwright.sync_api import sync_playwright

    failed, errors = [], []
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context()
        host = urllib.parse.urlparse(s.url).hostname
        ctx.add_cookies([{"name": n.strip(), "value": v, "domain": host, "path": "/"}
                         for n, _, v in (c.partition("=") for c in s.cookie.split(";")) if n.strip()])
        pg = ctx.new_page()
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.on("response", lambda r: failed.append(f"{r.status} {r.url}")
              if r.url.startswith(s.url) and r.status >= 400 else None)
        pg.on("requestfailed", lambda r: failed.append(f"failed {r.url}") if r.url.startswith(s.url) else None)
        pg.goto(s.url + "/")
        pg.wait_for_selector("#conn[data-state=live]", state="attached", timeout=90000)
        pg.wait_for_timeout(3000)
        pg.screenshot(path=str(s.out / "in-browser.png"))
        b.close()
    expect(not failed, f"the page's own requests failed: {failed[:8]}")
    expect(not errors, f"the page's scripts failed: {errors[:5]}")


# --- the page's socket, fresh for each check ---------------------------------------------------------

def fresh(s: Stack):
    """The page's socket, opened afresh in the stack test's own chat (`Stack.socket`)."""
    return s.socket()


def say(s: Stack, text: str, limit: float = 120) -> tuple[str, list[dict]]:
    return s.say(text, limit)


def tool(s: Stack, name: str, args: dict | None = None, limit: float = 120) -> str:
    return s.tool(name, args, limit)


def ws_ask(s: Stack, message: dict, want, limit: float = 60) -> dict:
    """One message to the page's socket, and the first answer `want` takes."""
    fresh(s)
    s.ws.send(json.dumps(message))
    return s.wait_for(want, limit)


# --- a page of the owner's, in a task of the owner's -------------------------------------------------

PAGE_HTML = """<!doctype html><html><head><meta charset="utf-8"><title>Stack test page</title></head><body>
<section id="hero"><h1>Stack test page</h1><p>Scale does not make this easier.</p></section>
<section id="plans"><h2>Pricing plans</h2><p>The process has four boxes.</p></section>
<section id="team"><h2>Our team</h2><p>The process is run by two people, Dana and Sam.</p></section>
</body></html>
"""

_PAGE: dict = {}


def the_page(s: Stack) -> str:
    """The task the page checks share, with a page in it, written into the workspace Rouh serves;
    its address there."""
    if _PAGE:
        if _PAGE.get("error"):
            raise Failed(_PAGE["error"])
        return _PAGE["doc"]
    try:
        rel = task_folder(s, "Stack test pages")
        out = core_py(s, "from pathlib import Path\nfrom rouh.config import config\n"
                         f"p = Path(config.assistant_repo) / {rel!r} / 'index.html'\n"
                         f"p.write_text({PAGE_HTML!r}, encoding='utf-8')\nprint('wrote', p.is_file())")
        expect("wrote True" in out, f"the page could not be written into the workspace: {out[-300:]}")
        _PAGE.update(task=rel, doc=rel + "/index.html")
    except Failed as e:
        _PAGE["error"] = f"the page the page checks share: {e}"
        raise
    return _PAGE["doc"]


def q(doc: str) -> str:
    return urllib.parse.quote(doc, safe="")


def ask_ai(s: Stack, doc: str, question: str, path: str = "/api/askai/ask") -> list[dict]:
    """One Ask AI question on a page, as the page's Ask box sends it; every event it streamed."""
    req = urllib.request.Request(s.url + path, data=json.dumps({"doc": doc, "question": question}).encode(),
                                 method="POST", headers={"Cookie": s.cookie, "X-CSRFToken": _csrf(s), "Origin": s.url,
                                                         "Referer": s.url + "/", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            raw = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        raise Failed(f"Ask AI answered {e.code}: {e.read()[:300]!r}")
    events = []
    for line in raw.splitlines():
        if line.startswith("data: "):
            try:
                events.append(json.loads(line[6:]))
            except ValueError:
                pass
    expect(events, f"Ask AI streamed nothing: {raw[:300]}")
    return events


_EDIT: dict = {}


def the_edit(s: Stack) -> int:
    """Ask AI asked, once, to change the page's second heading, with copy to keep word for word."""
    if _EDIT:
        if _EDIT.get("error"):
            raise Failed(_EDIT["error"])
        return _EDIT["edit"]
    doc = the_page(s)
    try:
        events = ask_ai(s, doc, "Headline: Pricing that grows with you\nTOOL edit_page " + json.dumps(
            {"edits": [{"find": "<h2>Pricing plans</h2>", "replace": "<h2>Pricing that grows</h2>"}],
             "summary": "A new headline for the plans"}))
        edited = [e for e in events if e.get("type") == "edited"]
        expect(edited, f"Ask AI changed nothing: {json.dumps(events)[-600:]}")
        _EDIT.update(edit=edited[0].get("edit"), events=events)
    except Failed as e:
        _EDIT["error"] = f"Ask AI's change of the page: {e}"
        raise
    return _EDIT["edit"]


@check("gene.ask-ai-edit")
def ask_ai_edit(s: Stack) -> None:
    """Ask AI changes the page when asked, and the page on disk has the change."""
    the_edit(s)
    code, body, _ = s.get("/workspace/" + the_page(s))
    expect(code == 200 and "Pricing that grows" in body, f"the page Rouh serves has not changed: {code} {body[:300]}")


@check("gene.page-history")
def page_history(s: Stack) -> None:
    """The page's history names the change and who made it, and the change kept as an option
    gives the page its two versions to switch between."""
    edit = the_edit(s)
    doc = the_page(s)
    got = api(s, f"/api/askai/history?doc={q(doc)}")
    expect("A new headline for the plans" in json.dumps(got), f"the history has no such change: {json.dumps(got)[:400]}")
    kept = post(s, f"/api/askai/keep?doc={q(doc)}", {"edit": edit, "keep": "option"})
    expect("As it was" in json.dumps(kept), f"the change was not kept as an option: {json.dumps(kept)[:400]}")


@check("gene.askai-show")
def askai_show(s: Stack) -> None:
    """Show me where, beside a change Ask AI made: the part of the page it is in."""
    got = post(s, "/api/askai/where", {"doc": the_page(s), "edit": the_edit(s)})
    expect("Pricing that grows" in json.dumps(got), f"Show me where: {json.dumps(got)[:300]}")


@check("gene.copy-exact")
def copy_exact(s: Stack) -> None:
    """Copy given to Ask AI that is not on the page word for word after its change is said to the reader."""
    the_edit(s)
    said = json.dumps(_EDIT["events"])
    expect("word for word" in said and "Pricing that grows with you" in said,
           f"the reader was not told the copy is not on the page word for word: {said[-600:]}")


@check("gene.page-facts")
def page_facts(s: Stack) -> None:
    """A fact told to Ask AI on a page in a task is kept in the task's notes."""
    doc = the_page(s)
    events = ask_ai(s, doc, "TOOL keep_fact " + json.dumps({"fact": "Our scanner folder is backed up nightly."}))
    expect("Kept for the task" in json.dumps(events), f"Ask AI did not keep the fact: {json.dumps(events)[-400:]}")
    out = core_py(s, "from pathlib import Path\nfrom rouh.config import config\n"
                     f"print(open(Path(config.assistant_repo) / {_PAGE['task']!r} / 'AGENTS.md').read())")
    expect("backed up nightly" in out, f"the task's notes do not have the fact: {out[-400:]}")


@check("page.shared-public")
def shared_public(s: Stack) -> None:
    """A page made public opens by its link with no sign-in, and taken down again it does not."""
    doc = the_page(s)
    got = post(s, "/api/share", {"rel": doc, "public": True})
    link = got.get("path") or ""
    expect(link.startswith("/p/"), f"the page was not made public: {json.dumps(got)[:300]}")
    code, body, _ = s.get(link, cookie=False)
    expect(code == 200 and "Stack test page" in body, f"the public link answered {code} with no sign-in: {body[:200]}")
    post(s, "/api/share", {"rel": doc, "public": False})
    code, _, _ = s.get(link, cookie=False, follow=False)
    expect(code != 200, f"the page still opens with no sign-in after it was taken down ({code})")


#: A stand-in registration on rouh.land and relay address, for the checks that share with a person
#: (step 176-26): only a Connected Rouh shares privately, since the person signs in with rouh.land
#: (`rouh/landshare.py`). Only the relay's name is set, never "on", so no frpc starts.
STACK_RELAY = "stack-heron.rouh.page"
CONNECT = ("import time\nfrom rouh.models import RouhBirth\nfrom rouh import relay\nnow = time.time()\n"
           "RouhBirth.objects.get_or_create(org_id='org-default', state='born', defaults=dict(name='Stack Heron', "
           "tag='test', born_at=now, birth_key='stack', daily_public='stack', daily_private='', daily_since=now, "
           "recovery_public='stack', updated_at=now, registry_id='stack-test', registry_url='https://rouh.land/registry/birth/'))\n"
           f"relay._change(hostname={STACK_RELAY!r})\nprint('connected')\n")
ON_ITS_OWN = ("from rouh.models import RouhBirth\nfrom rouh import relay\n"
              "RouhBirth.objects.filter(registry_id='stack-test').delete()\nrelay._change(hostname=None)\n"
              "print('on its own')\n")


def connected(s: Stack, fn) -> None:
    """Run `fn` with this Rouh registered on rouh.land and given a relay address, and take both
    away after, so no other check sees a Rouh it is not."""
    def fixture(code):
        # relay's private state is 0600. Docker exec defaults to root; a root-written
        # fixture cannot be read by the real app, which runs as rouh (10001).
        r = s.py("core", "from rouh.project import setup\nsetup()\n" + code, user="10001:10001")
        expect(r.returncode == 0, "the sharing fixture could not be set: " + (r.stderr or r.stdout)[-600:])
        return r.stdout

    expect("connected" in fixture(CONNECT), "the stand-in registration could not be made")
    try:
        fn()
    finally:
        fixture(ON_ITS_OWN)


@check("page.shared-guests")
def shared_guests(s: Stack) -> None:
    """A page shared with a person by email, on a Connected Rouh: they are listed with when they
    last opened it, and opening it signed out sends them to sign in with rouh.land, on the relay
    address. On its own, the Rouh refuses to share privately and makes no account."""
    doc = the_page(s)
    code, got = _send(s, "/api/share/invite", {"rel": doc, "email": "sam@example.test", "notify": False,
                                                "role": "view"})
    expect(code == 400 and "On its own" in json.dumps(got), f"an On its own Rouh shared privately: {code} {got}")

    def shared() -> None:
        post(s, "/api/share/invite", {"rel": doc, "email": "sam@example.test", "notify": False, "role": "view"})
        people = api(s, f"/api/share?rel={q(doc)}", "people")["people"]
        sam = [p for p in people if p.get("email") == "sam@example.test"]
        expect(sam and "opened" in sam[0], f"the person shared with is not listed: {json.dumps(people)[:300]}")
        code, body, _ = s.get("/shared")
        expect(code == 200, f"/shared answered {code}")
        shared_link = "/shared/" + sam[0]["token"]
        code, _, _ = s.get(shared_link, cookie=False, follow=False)
        expect(code == 401, f"a signed-out script was not refused: {code}")
        navigation = {"Accept": "text/html", "Sec-Fetch-Mode": "navigate"}
        code, _, heads = s.get(shared_link, cookie=False, follow=False, headers=navigation)
        expect(code == 303 and next((v for k, v in heads.items() if k.lower() == "location"), "").startswith("/shared/in?"),
               f"opened signed out, it did not go to rouh.land's sign-in: {code} {next((v for k, v in heads.items() if k.lower() == 'location'), None)}")
        code, _, heads = s.get(next(v for k, v in heads.items() if k.lower() == "location"), cookie=False, follow=False, headers=navigation)
        expect(code == 303 and next((v for k, v in heads.items() if k.lower() == "location"), "").startswith(f"https://{STACK_RELAY}/shared/in?"),
               f"it did not go on to the relay address: {code} {next((v for k, v in heads.items() if k.lower() == 'location'), None)}")
        post(s, "/api/share/uninvite", {"rel": doc, "token": sam[0].get("token")})

    connected(s, shared)


@check("gene.page-comments")
def page_comments(s: Stack) -> None:
    doc = the_page(s)
    got = post(s, f"/api/comments?doc={q(doc)}", {"do": "start", "anchor": {"tag": "h1", "text": "Stack test page",
                                                                            "fx": 0.5, "fy": 0.5},
                                                   "body": "A comment from the stack test"})
    expect((got.get("thread") or {}).get("id"), f"the comment was not left: {json.dumps(got)[:300]}")
    listed = json.dumps(api(s, f"/api/comments?doc={q(doc)}"))
    expect("A comment from the stack test" in listed, f"the comment is not on the page: {listed[:300]}")


@check("gene.page-highlights")
def page_highlights(s: Stack) -> None:
    doc = the_page(s)
    got = post(s, f"/api/highlights?doc={q(doc)}", {"do": "add", "colour": "green",
                                                     "anchor": {"text": "four boxes", "start": 0}})
    expect((got.get("highlight") or {}).get("id"), f"the highlight was not kept: {json.dumps(got)[:300]}")
    expect("four boxes" in json.dumps(api(s, f"/api/highlights?doc={q(doc)}")), "the highlight is not listed")


@check("gene.page-definitions")
def page_definitions(s: Stack) -> None:
    """Define, beside Ask: the model explains a passage in the light of the page."""
    doc = the_page(s)
    got = post(s, f"/api/definitions?doc={q(doc)}", {"do": "define", "anchor": {"text": "four boxes", "start": 0}})
    expect("four boxes" in json.dumps(got).lower() and "error" not in got, f"Define: {json.dumps(got)[:300]}")
    expect("four boxes" in json.dumps(api(s, f"/api/definitions?doc={q(doc)}")), "the definition is not listed")


@check("gene.x-ray")
def x_ray(s: Stack) -> None:
    """A report's X-ray beside it is laid over the page as it opens on the canvas."""
    doc = the_page(s)
    layer = {"xray": 1, "answer": {"claim": "The process has four boxes."},
             "points": [{"claim": "It has four boxes.", "quote": "The process has four boxes."}]}
    core_py(s, "from pathlib import Path\nfrom rouh.config import config\n"
               f"(Path(config.assistant_repo) / {doc!r}).with_suffix('.xray.json').write_text({json.dumps(layer)!r})")
    code, body, _ = s.get(f"/workspace/{doc}?framed=1&hosted=1")
    expect(code == 200 and "ROUH_XRAY" in body, f"the page opened on the canvas has no X-ray: {code} {body[:200]}")


@check("gene.self-link")
def self_link(s: Stack) -> None:
    """A link to Rouh's own page is read inside Rouh, as the person, never over the web."""
    got = tool(s, "read_rouh_link", {"url": f"{s.url}/workspace/{the_page(s)}"})
    expect("Read inside Rouh" in got and "four boxes" in got, f"read_rouh_link: {got[:400]}")


@check("gene.since-read")
def since_read(s: Stack) -> None:
    got = api(s, f"/api/since-read?doc={q(the_page(s))}", "on", "changed")
    expect(got["on"] is True, f"Since you last read it is off: {got}")


@check("gene.page-pdf")
def page_pdf(s: Stack) -> None:
    """A page laid out as a PDF for paper and kept in its task."""
    doc = the_page(s)
    at = doc.rsplit("/", 1)[0]
    api(s, f"/api/page-pdf?at={q(at)}", "on", "made")
    code, got = _send(s, "/api/page-pdf", {"at": at, "paper": "a4"})
    expect(code in (200, 202) and got.get("started"), f"the PDF was not started: {code} {got}")
    end = time.time() + 120
    while time.time() < end:
        made = api(s, f"/api/page-pdf?at={q(at)}", "made")["made"]
        if made:
            return
        time.sleep(4)
    raise Failed("no PDF was made in two minutes")


@check("gene.page-listen")
def page_listen(s: Stack) -> None:
    """Listen to this page: the model writes the narration and the voice reads its first part."""
    doc = the_page(s)
    path = f"/api/page-listen?doc={q(doc)}"
    got = post(s, path, {"do": "narrate", "title": "Stack test page",
                         "outline": [{"n": 0, "kind": "h1", "text": "Stack test page"},
                                     {"n": 1, "kind": "p", "text": "The process has four boxes."}]})
    key = got.get("key")
    expect(key, f"no narration was started: {got}")
    end = time.time() + 90
    while not got.get("done") and time.time() < end:
        time.sleep(2)
        got = post(s, path, {"do": "ready", "key": key})
    expect(got.get("parts"), f"the narration has no parts: {got}")
    spoken = post(s, path, {"do": "say", "key": key, "i": 0})
    expect(spoken.get("pcm"), f"the voice did not read it: {json.dumps(spoken)[:200]}")


# --- the conversation: forks, recall, addresses, search, notices, plain words -------------------------

def _new_chat(s: Stack) -> str:
    """A new chat of the stack test's own, as New chat opens one."""
    s.chat = ""
    s.socket()
    return s.chat


@check("gene.forks")
def forks(s: Stack) -> None:
    """A side conversation forked off a chat answers, and knows which chat it came from."""
    chat = _new_chat(s)
    s.say("A message to fork from")
    seen: list[dict] = []
    s.socket()
    s.ws.send(json.dumps({"type": "fork", "from": chat, "text": "A side question in a fork"}))
    done = s.wait_for(lambda m: m.get("type") in ("assistant_done", "fork_refused"), 120, seen)
    expect(done.get("type") == "assistant_done", f"the fork was refused: {done}")
    new = [m.get("chat") for m in seen if m.get("type") == "chat_switched"] + [done.get("chat")]
    new = [c.get("id") if isinstance(c, dict) else c for c in new]
    new = [c for c in new if c and c != chat]
    expect(new, f"no new chat was made for the fork: {[m.get('type') for m in seen]}")
    out = core_py(s, f"from rouh import forks\nprint('parent', forks.parent_of({new[0]!r}))")
    expect(f"parent {chat}" in out, f"the fork does not know its parent: {out[-200:]}")


@check("gene.memory-recall")
def memory_recall(s: Stack) -> None:
    """Before Rouh answers, what the message names is looked up, and the page is shown the reading."""
    _, seen = say(s, "What did we decide about the printer feeder last week?")
    expect([m for m in seen if m.get("type") == "recall"], f"no recall was read: {sorted({m.get('type') for m in seen})}")


@check("gene.addresses")
def addresses(s: Stack) -> None:
    """Every chat and task has its own address: it opens Rouh's page, and the page's socket opens
    that chat."""
    chat = _new_chat(s)
    s.say("A message in a chat with its own address")
    page(s, f"/chat/{chat}")
    page(s, f"/task/{the_page(s).rsplit('/', 1)[0]}")
    from websockets.sync.client import connect

    ws = connect(s.url.replace("http", "ws", 1) + "/ws", additional_headers={"Cookie": s.cookie}, open_timeout=30)
    try:
        ws.send(json.dumps({"type": "hello", "client": "stack-test/1", "chat": chat}))
        end = time.time() + 30
        while time.time() < end:
            m = json.loads(ws.recv(timeout=30))
            if m.get("type") == "ready":
                expect(m.get("session_id") == chat, f"the address opened {m.get('session_id')}, not {chat}")
                return
    finally:
        ws.close()
    raise Failed("the page's socket was never ready")


@check("gene.search")
def search(s: Stack) -> None:
    """Search over chats, tasks, pages and runs finds the page by its words."""
    the_page(s)
    got = ws_ask(s, {"type": "search", "q": "Stack test pages", "kind": "all", "gen": 7},
                 lambda m: m.get("type") == "search_results" and m.get("gen") == 7, 60)
    expect(sum((got.get("counts") or {}).values()) > 0 if isinstance(got.get("counts"), dict) else got.get("results"),
           f"search found nothing: {json.dumps(got)[:400]}")


@check("gene.notifications")
def notifications(s: Stack) -> None:
    """A notice for the person is under the bell as the page opens, and read there it is read."""
    s.socket()
    out = core_py(s, "from rouh import notices\nfrom rouh.tenancy import Tenancy\n"
                     "n = notices.post(Tenancy().only_person(), title='Stack test notice', link='/tasks', "
                     f"key='stack-test-notice-{time.time()}')\nprint('id', n['id'])")
    ident = int(out.split("id", 1)[1].split()[0])

    def holds(state: str):
        return lambda m: m.get("type") == "notices" and any(
            n.get("id") == ident and (not state or n.get("state") == state) for n in m.get("items") or [])

    s.socket()
    s.wait_for(holds(""), 60)
    s.ws.send(json.dumps({"type": "notice", "act": "read", "ids": [ident]}))
    s.wait_for(holds("read"), 30)


@check("gene.plain-words")
def plain_words(s: Stack) -> None:
    """A term the person asks the meaning of is explained every time after, in turns and runs."""
    say(s, "what is WIPO?")
    out = core_py(s, "from rouh import plain_words\nfrom rouh.tenancy import Tenancy\nwho = Tenancy().only_person()\n"
                     "print('block', 'WIPO' in plain_words.block(who))\n"
                     "print('runs', '## Plain words' in plain_words.for_runs(who.org_id))")
    expect("block True" in out and "runs True" in out, f"the term is not explained after: {out[-300:]}")


@check("gene.offline-outbox")
def offline_outbox(s: Stack) -> None:
    """What was done on a device with no connection is carried out when it comes back."""
    got = post(s, "/api/offline/outbox", {"device": {"id": "stack-test-device", "name": "Stack test", "kind": "phone"},
                                          "actions": [{"id": "stack-test-note-1", "kind": "note",
                                                       "payload": {"text": "A note written offline in the stack test"},
                                                       "made_at": time.time()}]})
    expect("done" in json.dumps(got), f"the offline note was not carried out: {json.dumps(got)[:300]}")


# --- trusted contacts' mail cases, the feedback board -----------------------------------------------

@check("page.mail-case")
def mail_case(s: Stack) -> None:
    """A trusted contact's email as a case: its page, and what the page draws of it."""
    core_py(s, "import time\nfrom rouh.tenancy import Tenancy\nfrom rouh.models.trust import MailCase\n"
               "who = Tenancy().only_person()\n"
               "MailCase.objects.get_or_create(key='stacktestcase1', defaults=dict(user_id=str(who.user_id), "
               "org_id=str(who.org_id), message_id='stack-test-case-msg-1', sender='maria@client.example', "
               "sender_name='Maria Client', subject='Can we move Friday?', stage='needs_petar', "
               "email={'from': 'Maria Client <maria@client.example>', 'subject': 'Can we move Friday?', "
               "'body': 'Can we move Friday to Monday?', 'date': time.time()}, proposed_reply='Monday works.'))")
    page(s, "/mail/case/stacktestcase1")
    got = api(s, "/api/mail/case/stacktestcase1", "case")
    expect(got["case"].get("name") == "Maria Client", f"the case: {json.dumps(got)[:300]}")
    code, _, _ = s.get("/api/mail/case/no-such-case")
    expect(code == 404, f"a case that is not there answered {code}")


@check("gene.feedback-board")
def feedback_board(s: Stack) -> None:
    """Feedback given on a page becomes a feature request on the board (Gene therapy)."""
    before = api(s, "/api/gene-therapy")
    auto = (before.get("settings") or {}).get("autobuild")
    post(s, "/api/gene-therapy/settings", {"autobuild": False})
    try:
        post(s, "/api/gene-therapy", {"body": "The search box should find pages by their title.", "page": "/tasks"})
        got = api(s, "/api/gene-therapy", "counts")
        expect("find pages by their title" in json.dumps(got), f"the feedback is not on the board: {json.dumps(got)[:400]}")
        expect(got["counts"].get("requests"), f"no feature request was written from it: {got['counts']}")
    finally:
        if auto is not None:
            post(s, "/api/gene-therapy/settings", {"autobuild": auto})


# --- tasks and steps renamed and moved in words -------------------------------------------------------

def task_with_a_step(s: Stack, title: str) -> dict:
    """A task made from a new chat that has drawn one card, so the card is its first step; its row
    in the task list."""
    s.chat = ""
    s.tool("show_on_screen", {"title": f"{title} card", "blocks": [{"block": "text", "text": "A step to move."}]})
    s.tool("make_a_task", {"title": title})
    end = time.time() + 60
    while time.time() < end:
        mine = [t for t in api(s, "/api/workspace/index", "tasks")["tasks"]
                if (t.get("name") or "").strip().lower() == title.lower()]
        if mine and mine[0].get("steps"):
            return mine[0]
        time.sleep(3)
    raise Failed(f"the task {title!r} with its step never reached the task list")


@check("gene.task-rename")
def task_rename(s: Stack) -> None:
    """Asked in words, Rouh renames the task the chat is in."""
    t = task_with_a_step(s, "Stack test to rename")
    got = s.tool("rename_task", {"name": "Stack test renamed"})
    expect("Stack test renamed" in got, f"rename_task: {got[:300]}")
    names = [x.get("name") for x in api(s, "/api/workspace/index", "tasks")["tasks"] if x.get("number") == t["number"]]
    expect(names == ["Stack test renamed"], f"the task list says {names}")


@check("gene.step-move")
def step_move(s: Stack) -> None:
    """Asked in words, Rouh moves a step out of its task as a task of its own."""
    t = task_with_a_step(s, "Stack test step to move")
    got = s.tool("move_step", {"what": f"{t['number']}-01", "to": "own task"})
    expect("is now" in got, f"move_step: {got[:300]}")
    left = [x.get("steps") for x in api(s, "/api/workspace/index", "tasks")["tasks"] if x.get("number") == t["number"]]
    expect(left == [0], f"the step is still in its task: {left}")


# --- what a turn, an Ask AI answer or a run is told, asked of each gene in the core --------------------

WHO = "from rouh.tenancy import Tenancy\nwho = Tenancy().only_person()\n"


def in_core(*want: str, code: str, before=None):
    """A gene that changes what a turn, Ask AI or a run is told: its own module, in the core,
    given words that bring it on and words that do not; each line it must print."""
    def fn(s: Stack) -> None:
        if before:
            before(s)
        out = core_py(s, WHO + code, timeout=180)
        missing = [w for w in want if w not in out]
        expect(not missing, f"it did not say {missing}: {out[-700:]}")
    return fn


check("gene.short-answers")(in_core("short True", "long True", code="""
from rouh import short_answers as sa
print('short', 'how_to_answer' in sa.note(who, 'what is SMB? shortly'))
print('long', sa.note(who, 'explain SMB in detail, step by step') == '')
"""))

check("gene.askai-words")(in_core("found True", "none True", code="""
from rouh import askai_words as aw
src = '<h2>Pricing plans</h2><p>The process has four boxes.</p>'
print('found', 'four boxes' in aw.note(who, src, 'Make the "four boxes" smaller'))
print('none', aw.note(who, src, 'Make it bolder') == '')
"""))

check("gene.askai-follow")(in_core("heading True", code="""
from rouh import askai_follow as af
before = '<h2>Plans</h2><p>The process has four boxes.</p><h2>Team</h2><p>Two people.</p>'
after = before.replace('Two people.', 'Three people.')
print('heading', 'Team' in str(af.where(before, after)))
"""))

check("gene.each-point")(in_core("rule True", "plain True", code="""
from rouh import each_point as ep
print('rule', '## Every point accounted for' in ep.with_rule("Apply the reviewer's comments to the page.", who))
print('plain', ep.with_rule('Write a page about the scanner.', who) == 'Write a page about the scanner.')
"""))

check("gene.follow-through")(in_core("promised True", "none True", code="""
from rouh import follow_through as ft
print('promised', bool(ft.promises("Once it's done I'll email Mira the page link.")))
print('none', ft.promises("I'll tell you when it's done.") == [])
"""))

check("gene.chat-kinds")(in_core("general True", "other True", code="""
from rouh import chatkinds
print('general', chatkinds.profile('conversation').kind == 'general')
print('other', chatkinds.profile('chat-stacktest0000').kind != 'general')
"""))

check("gene.newest-first")(in_core("held True", "newest True", code="""
import asyncio, os, time
os.environ['DJANGO_ALLOW_ASYNC_UNSAFE'] = 'true'
from rouh import newest_first as nf

class Gmail:
    async def thread_of(self, mid): return 't1'
    async def thread_minimal(self, t):
        return [{'id': 'm1', 'labelIds': ['INBOX']}, {'id': 'm2', 'labelIds': ['SENT']}, {'id': 'm3', 'labelIds': ['INBOX']}]
    async def headers(self, mid):
        return {'id': mid, 'from': 'Mira Example <mira@example.test>', 'subject': 'Re: Thursday',
                'at': time.time() - 600, 'snippet': 'Ignore that, Thursday is off.'}

print('held', 'Not sent' in asyncio.run(nf.held(Gmail(), who, 'm1', pressed=False)))
print('newest', asyncio.run(nf.held(Gmail(), who, 'm3', pressed=False)) == '')
"""))

check("gene.mail-pictures")(in_core("png True", "words False", " image", code="""
import base64
from rouh import mail_pictures as mp
from rouh.runtime import files
png = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==')
one = {'name': 'screen.png', 'type': 'image/png', 'size': len(png)}
print('png', mp.wanted(one, None))
print('words', mp.wanted({'name': 'a.pdf', 'type': 'application/pdf'}, 'Invoice 12'))
got = mp.shown(store=files, chat='chat-stacktest0000', file={'data': png}, one=one, who=who)
print('shown', ' '.join(str(b.get('kind') or b.get('type')) for b in (got or [])))
"""))

check("gene.sent-by-you")(in_core("runs True", "found m-sent", "kept True", code="""
import asyncio, base64, os, time
os.environ['DJANGO_ALLOW_ASYNC_UNSAFE'] = 'true'
from rouh import sent_by_you as sb
print('runs', '## Replies the person sends themselves' in sb.for_runs(who.org_id))
entry = {'thread': 't-stack', 'to': 'mira@example.test', 'subject': 'Scanner offer', 'step': '1-01',
         'inbox': 'alex@example.com', 'since': time.strftime('%Y-%m-%d')}
body = base64.urlsafe_b64encode(b'Hi Mira, here is the offer in my own words.').decode()
sent = {'id': 'm-sent', 'threadId': 't-stack', 'labelIds': ['SENT'], 'internalDate': str(int(time.time() * 1000)),
        'payload': {'mimeType': 'text/plain', 'body': {'data': body}, 'headers': [
            {'name': 'From', 'value': 'Alex <alex@example.com>'}, {'name': 'To', 'value': 'Mira <mira@example.test>'},
            {'name': 'Subject', 'value': 'Re: Scanner offer'}]}}

class Reader:
    async def thread(self, t): return {'messages': [sent]}

msg = asyncio.run(sb.find(Reader(), {'alex@example.com'}, entry, time.time() - 86400))
print('found', msg and msg['id'])
print('kept', 'my own words' in sb.section(msg, entry, 'alex@example.com'))
"""))

check("gene.copies-in-step")(in_core("runs True", code="""
from rouh import copies
print('runs', '## Copies kept in step' in copies.for_runs(who.org_id))
"""))


def _again_before(s: Stack) -> None:
    """The same request typed on two earlier days: typed twice now, and moved back a week and two."""
    s.chat = ""
    for _ in range(2):
        s.say("Check the shipping status of the oak flooring samples")
    core_py(s, "from django.db import connection\nwith connection.cursor() as c:\n"
               "    c.execute(\"SELECT id FROM messages WHERE role='user' AND content LIKE %s ORDER BY id DESC LIMIT 2\", "
               "['%oak flooring samples%'])\n"
               "    for n, (i,) in enumerate(c.fetchall()):\n"
               "        c.execute('UPDATE messages SET ts = ts - %s WHERE id = %s', [86400 * 7 * (n + 1), i])")


@check("gene.asked-again")
def asked_again(s: Stack) -> None:
    """A request typed by hand on different days is offered, once, as scheduled work."""
    _again_before(s)
    text, _ = s.say("Check the shipping status of the oak flooring samples")
    expect("asked me for this before" in text or "Clockwork" in text,
           f"the request asked again was not offered as scheduled work: {text[-400:]}")


@check("gene.answered-in-chat")
def answered_in_chat(s: Stack) -> None:
    """A decision waiting on the person that they already answered in a chat shows their words."""
    out = core_py(s, WHO + "import time\nfrom rouh.models import Decision\n"
                  "d = Decision.objects.create(user_id=str(who.user_id), org_id=str(who.org_id), source='stacktest', "
                  "source_id='stack-test-aic', key='stack-test-aic', title='Pick the printer vendor', "
                  "question='Which printer vendor should we order from, Brother or Canon?', "
                  "options=[{'id': 'brother', 'label': 'Brother'}, {'id': 'canon', 'label': 'Canon'}], status='open', "
                  "created_at=time.time() - 60, updated_at=time.time() - 60)\nprint('decision', d.id)")
    ident = int(out.split("decision", 1)[1].split()[0])
    s.chat = ""
    s.say("About the printer vendor order: let's go with Brother printers.")
    core_py(s, WHO + "import asyncio, os\nos.environ['DJANGO_ALLOW_ASYNC_UNSAFE'] = 'true'\n"
               "from rouh import answered_in_chat as a\nprint(asyncio.run(a.Reader(owner=lambda: who).beat()))",
            timeout=240)
    got = api(s, f"/api/decisions/{ident}")
    expect("brother" in json.dumps(got.get("said") or got.get("decision", {}).get("said") or {}).lower(),
           f"the decision does not show the answer given in the chat: {json.dumps(got)[:500]}")


# --- meetings: before, what to raise, after, the guests ----------------------------------------------

MEETING = WHO + """
import asyncio, json, os, time
from datetime import datetime, timedelta, timezone
os.environ['DJANGO_ALLOW_ASYNC_UNSAFE'] = 'true'
now = datetime.now(timezone.utc)
event = {'id': 'stacktest1', 'calendar_id': 'primary', 'title': 'Stack test with Example Ltd',
         'start': (now + timedelta(hours=2)).isoformat(), 'end': (now + timedelta(hours=3)).isoformat(),
         'guests': [{'email': 'alex@example.com', 'me': True}, {'email': 'dana@client.example', 'name': 'Dana Client'},
                    {'email': 'room-1@resource.calendar.google.com', 'resource': True}]}
people = [{'name': 'Dana Client', 'email': 'dana@client.example'}]
"""

check("gene.meeting-prep")(in_core("guests dana@client.example", "on True", code=MEETING + """
from rouh import meeting_prep as mp
own = mp.own_addresses(who)
print('on', mp.on(who))
print('guests', ' '.join(g.get('email', '') for g in mp.worth_noting(event, own, mp.own_domains(own))))
"""))

check("gene.what-to-raise")(in_core("standing True", "no mail True", code=MEETING + """
from rouh import meeting_brief as mb
print('no mail', 'no email' in json.dumps(asyncio.run(mb.make(who, event, slack=False))).lower())
mails = [{'subject': 'Pricing sheet', 'from': 'Dana Client <dana@client.example>', 'at': time.time() - 86400,
          'text': 'Could you send the pricing sheet before we meet?', 'link': '', 'inbox': 'alex@example.com'}]
q = mb.question(event, people, mails, now, mb.remembered_for(who, event, people))
got = asyncio.run(mb.ask(who, q, remembering=False))
got = got[0] if isinstance(got, tuple) else got
print('standing', bool((got or {}).get('standing')), json.dumps(got)[:300])
"""))

check("gene.what-to-raise-remembers")(in_core("remembered True", code=MEETING + """
from rouh import meeting_brief as mb
mb.keep_fact(who, 'Dana moved to the risk team in October.', people, 'Stack test')
print('remembered', 'risk team' in json.dumps(mb.remembered_for(who, event, people)))
"""))

check("gene.after-meeting")(in_core("work Send the pricing sheet", code=MEETING + """
from rouh import meeting_next as mn
meeting = {'id': 'stack-test-meeting-1', 'version': 1, 'title': 'Stack test meeting', 'page': '', 'dataset': '',
           'body': 'Summary: we agreed on pricing.\\nAction items:\\n- Send the pricing sheet to Dana (Alex, due 2026-11-02)',
           'end': time.time() - 3600}
got = asyncio.run(mn.read(who, meeting))
print('work', ' '.join(w.get('do', '') for w in got.get('work') or []), json.dumps(got)[:300])
"""))

check("gene.meeting-guests")(in_core('"email": "dana@client.example"', code=MEETING + """
from rouh import meeting_people as mp, meeting_prep
got = mp.guests_of(event, meeting_prep.own_addresses(who))
print('look', json.dumps(got))
"""))

check("gene.meeting-contacts")(in_core("skip True", "switch", code=MEETING + """
import subprocess, sys
from rouh import meeting_contacts as mc
print('skip', mc.meeting_skip(event, set())[0] == '')
print(subprocess.run([sys.executable, 'manage.py', 'meeting_contacts', 'status'], capture_output=True, text=True).stdout)
"""))


# --- the morning brief's own lines ------------------------------------------------------------------

#: A meeting the meeting library kept, in Synapse Master, with an action an outside guest owes and
#: a next meeting agreed and not booked.
SEED_MEETING = WHO + """
from datetime import datetime, timedelta
from psycopg.types.json import Json
from rouh.synapse import db, master, datasets
from rouh.synapse.sources import meetings as library
ds = master.of(str(who.org_id), str(who.user_id))
body = '''Stack test with Example Ltd
Took part: Alex <alex@example.com>; Ana Petrova <ana@example.test> (outside)
Summary:
We agreed the quote and the next steps.
Next meeting: 2026-11-12 10:00
Action items:
- Send the signed quote (Ana Petrova (outside), due 2026-10-25, open)
'''
if not db.row("SELECT id FROM synapse.item WHERE dataset_id=%s AND source=%s AND source_key=%s",
              (ds["id"], library.SOURCE, "meeting:stack-test-1")):
    db.row("INSERT INTO synapse.item (dataset_id, kind, source, source_key, title, raw, body, said_at, tier, "
           "tier_why, tier_by, sensitivity, sensitivity_why, owner, meta, status) VALUES (%s,'meeting',%s,%s,%s,%s,%s,%s,1,"
           "'stack test','code','normal',%s::jsonb,%s,%s::jsonb,'stored') RETURNING id",
           (ds["id"], library.SOURCE, "meeting:stack-test-1", "Stack test with Example Ltd", body, body,
            datetime.now().astimezone() - timedelta(days=5), Json({}), datasets.me(ds), Json({"meeting": {"page": ""}})))
"""

check("gene.owed-to-you")(in_core("owed Ana", code=SEED_MEETING + """
from rouh import owed_to_you
print('owed', ' '.join(l.get('who', '') for l in owed_to_you.lines(who)))
"""))

check("gene.next-meeting")(in_core("agreed 2026-", code=SEED_MEETING + """
from rouh import next_meeting
print('agreed', ' '.join(l.get('day', '') for l in next_meeting.lines(who)))
"""))


@check("gene.others-changed")
def others_changed(s: Stack) -> None:
    """A page of the owner's that somebody else changed since the owner last opened it."""
    doc = the_page(s)
    out = core_py(s, WHO + "import json, time\nfrom rouh.models import AskEdit\nfrom rouh import others_changed\n"
                  "from rouh.config import config\n"
                  f"AskEdit.objects.create(user_id='999999', org_id='guest', doc={doc!r}, "
                  "summary='A guest changed the heading', before='<h1>a</h1>', after='<h1>b</h1>', "
                  "created_at=time.time(), page_org_id=str(who.org_id))\n"
                  "print('changed', json.dumps(others_changed.changed(who, config.assistant_repo)))")
    expect("Stack test page" in out or doc in out, f"the page changed by somebody else is not listed: {out[-400:]}")
    got = post(s, "/api/brief/others_changed", {"key": doc, "act": "seen", "newest": 1})
    expect(got.get("ok"), f"Seen on the brief's line: {got}")


@check("gene.not-opened")
def not_opened(s: Stack) -> None:
    """A page shared by hand that is not opened days after the invitation: the brief's line, and
    Remind them beside the person in the Share panel."""
    doc = the_page(s)
    connected(s, lambda: post(s, "/api/share/invite", {"rel": doc, "email": "ana@example.test", "notify": False,
                                                       "role": "view"}))
    out = core_py(s, WHO + "import json, time\nfrom rouh.models import PageGuest\nfrom rouh import not_opened\n"
                  f"PageGuest.objects.filter(user_id=who.user_id, email='ana@example.test', rel={doc!r})"
                  ".update(created_at=time.time() - 3 * 86400, mailed_at=time.time() - 3 * 86400)\n"
                  "print('found', json.dumps(not_opened.found(who)))")
    expect("ana@example.test" in out, f"the brief does not say the share was not opened: {out[-400:]}")
    people = api(s, f"/api/share?rel={q(doc)}", "people")["people"]
    ana = [p for p in people if p.get("email") == "ana@example.test"]
    expect(ana and "mail.google.com" in str(ana[0].get("remind")), f"Remind them is not offered: {json.dumps(ana)[:300]}")
    post(s, "/api/share/uninvite", {"rel": doc, "token": ana[0].get("token")})


@check("page.draft-edits")
def draft_edits(s: Stack) -> None:
    """Behaviour, Draft edits: what the person changed in an email Rouh drafted, before sending."""
    page(s, "/anatomy/behaviour/draft-edits")
    core_py(s, WHO + "from rouh import draft_edits\n"
               "was = {'fields': [{'name': 'to', 'value': 'ana@example.test'}], 'body': 'Hi Ana,\\nThe report is ready.'}\n"
               "sent = {'fields': [{'name': 'to', 'value': 'ana@example.test'}], 'body': 'Dear Ana,\\nThe report is ready.'}\n"
               "draft_edits.keep(str(who.user_id), str(who.org_id), 'send_mail', was, sent, card='stack-test')")
    got = api(s, "/api/settings/draft-edits", "on", "total", "edits")
    expect("Dear Ana" in json.dumps(got["edits"]), f"the change is not listed: {json.dumps(got)[:300]}")


@check("gene.to-send")
def to_send(s: Stack) -> None:
    """A reply a task drafted for the person waits on the task's page with Write it in Gmail."""
    rel = the_page(s).rsplit("/", 1)[0]
    core_py(s, "from rouh.config import config\nfrom rouh import taskmeta, sent_by_you\n"
               "def how(data):\n    data = data or {}\n    held = sent_by_you._entries(data)\n"
               "    held.append({'subject': 'Stack test reply', 'to': 'ana@example.test', 'since': '2026-10-28', "
               "'body': 'Hello Ana.'})\n    data[sent_by_you.KEY] = held\n    return data\n"
               f"taskmeta.change({rel!r}, how, config.assistant_repo, by='stack test')")
    code, body, _ = s.get(f"/workspace/_task/{rel}?framed=1")
    expect(code == 200 and "tkToSend" in body, f"the task's page has no reply to send: {code} {body[:200]}")
    got = post(s, "/api/to-send", {"folder": rel, "n": 0, "do": "opened", "subject": "Stack test reply"})
    expect(got.get("ok"), f"Write it in Gmail: {got}")


# --- Google: the documents genes, through the stand-in for Google -----------------------------------

GOOGLE = 9015
#: The stand-in's short document, so all it says fits in what the stand-in model says back.
DOC = "file-2"
DOC_LINK = "https://docs.google.com/document/d/file-2/edit"
TOM = {"displayName": "Tom Carter", "emailAddress": "tom@exampleco.test"}
_G: dict = {}


def standin_post(s: Stack, port: int, path: str, body: dict) -> object:
    r = s.run("core", "python -c " + shlex.quote(
        "import json, sys, urllib.request\n"
        f"req = urllib.request.Request('http://standins:{port}{path}', data=sys.argv[1].encode(), "
        "headers={'content-type': 'application/json'})\n"
        "print(urllib.request.urlopen(req, timeout=20).read().decode())") + " " + shlex.quote(json.dumps(body)))
    expect(r.returncode == 0, f"the stand-in on {port} did not take {path}: {r.stderr[-300:]}")
    return r.stdout


def google(s: Stack) -> None:
    """Google connected, as the owner connects it: the organisation's client saved in Settings,
    Connect pressed, Allow pressed on the stand-in's consent page; and the document the genes
    read given a history, comments, and who last changed it."""
    if _G:
        if _G.get("error"):
            raise Failed(_G["error"])
        return
    try:
        held = api(s, "/api/settings/google", "connection")["connection"]
        # Connected and then refused means something before broke the connection, which is a fault
        # of its own to find, not one to connect over.
        expect(not held.get("needs_reconnect"), f"the owner's Google was refused before these checks: {held.get('trouble')}")
        if not held.get("connected"):
            import html
            import re
            from pathlib import Path

            made = re.search(r'fake_google\.build\([^,]+,\s*"([^"]+)",\s*"([^"]+)"',
                             (Path(__file__).parent / "standins.py").read_text())
            expect(made, "the stand-in's Google client is not in standins.py")
            post(s, "/api/settings/google/client", {"client_id": made.group(1), "client_secret": made.group(2)})
            url = api(s, "/auth/google/start?show=url", "url")["url"]
            consent = urllib.parse.urlparse(url)
            with urllib.request.urlopen(url, timeout=30) as r:
                page_html = r.read().decode()
            allow = re.search(r'id="allow" href="([^"]+)"', page_html)
            expect(allow, f"the consent page has no Allow: {page_html[:300]}")
            code, _, headers = _get_raw(f"{consent.scheme}://{consent.netloc}{html.unescape(allow.group(1))}")
            back = {k.lower(): v for k, v in headers.items()}.get("location", "")
            expect(back.startswith(s.url), f"Allow did not send the browser back to Rouh: {code} {back}")
            _get_raw(back, cookie=s.cookie)
            got = api(s, "/api/settings/google", "connection")["connection"]
            expect(got.get("connected"), f"Google is not connected: {got}")
        an_hour_ago = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 3600))
        standin_post(s, GOOGLE, "/_doc_history", {"file": DOC, "revisions": [
            {"id": "1", "modifiedTime": "2026-10-01T10:00:00Z", "lastModifyingUser": TOM,
             "text": "Risks\n\nThe timeline is long."},
            {"id": "2", "modifiedTime": "2026-10-20T10:00:00Z", "lastModifyingUser": TOM,
             "text": "Risks\n\nThe timeline is tight."}],
            "comments": [{"id": "c1", "author": TOM, "content": "Can we shorten the intro?",
                          "createdTime": an_hour_ago, "modifiedTime": an_hour_ago,
                          "resolved": False, "replies": [], "quotedFileContent": {"value": "The timeline is tight."}}]})
        standin_post(s, GOOGLE, "/_file_meta", {"file": DOC, "modifiedTime": "2026-10-20T10:00:00Z",
                                                "lastModifyingUser": TOM})
        _G["ok"] = True
    except Exception as e:  # noqa: BLE001 - every check that needs Google says the same
        _G["error"] = f"connecting Google: {e}"
        raise Failed(_G["error"]) from None


def _get_raw(url: str, cookie: str = "") -> tuple[int, str, dict]:
    from smoke import _NoRedirect

    req = urllib.request.Request(url, headers={"Cookie": cookie} if cookie else {})
    try:
        with urllib.request.build_opener(_NoRedirect()).open(req, timeout=30) as r:
            return r.status, r.read().decode("utf-8", "replace"), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace"), dict(e.headers)


def g_tool(s: Stack, name: str, args: dict, has: str) -> str:
    google(s)
    got = s.tool(name, args)
    expect("not set up" not in got and "not connected" not in got and has.lower() in got.lower(),
           f"{name} did not say {has!r}: {got[:500]}")
    return got


@check("gene.doc-changes")
def doc_changes(s: Stack) -> None:
    """What changed in a Google Doc since a day: the paragraph added, and who added it."""
    got = g_tool(s, "doc_changes", {"document": DOC_LINK, "since": "2026-10-10"}, "by Tom Carter")
    expect("The timeline is long." in got, f"doc_changes did not say what was taken out: {got[:500]}")


@check("gene.doc-comments")
def doc_comments(s: Stack) -> None:
    """A Google Doc read through read_doc comes with its open comments."""
    g_tool(s, "read_doc", {"document": DOC_LINK}, "shorten the intro")


@check("gene.doc-last-changed")
def doc_last_changed(s: Stack) -> None:
    """A Google Doc read through read_doc comes with who last changed it and when."""
    g_tool(s, "read_doc", {"document": DOC_LINK}, "Tom Carter")


@check("gene.doc-comment")
def doc_comment(s: Stack) -> None:
    """Asked to comment on a Google Doc, Rouh writes the comment in it, on the passage named."""
    g_tool(s, "comment_on_doc", {"document": DOC_LINK, "words": "A comment from the stack test",
                                 "passage": "The timeline is tight."}, "")
    seen = s.standin(GOOGLE, "/_seen")
    expect("A comment from the stack test" in json.dumps(seen.get("comments_made")),
           f"the comment did not reach the stand-in's Drive: {json.dumps(seen.get('comments_made'))[:300]}")


@check("gene.doc-reply")
def doc_reply(s: Stack) -> None:
    """Asked to answer a comment in a Google Doc, Rouh writes the answer under it."""
    g_tool(s, "reply_to_doc_comment", {"document": DOC_LINK, "comment_id": "c1", "words": "Shortened it."}, "")
    seen = s.standin(GOOGLE, "/_seen")
    expect("Shortened it." in json.dumps(seen.get("replies")),
           f"the answer did not reach the stand-in's Drive: {json.dumps(seen.get('replies'))[:300]}")


def _task_doc(s: Stack) -> str:
    """The page checks' task, with the stand-in's document linked in its notes (Add a document)."""
    google(s)
    rel = the_page(s).rsplit("/", 1)[0]
    if not _G.get("linked"):
        code, got = _send(s, "/api/task-docs/add", {"folder": rel, "link": DOC_LINK})
        expect(code == 200 and got.get("ok") or "already link" in json.dumps(got), f"Add a document: {code} {got}")
        _G["linked"] = True
    return rel


@check("gene.task-docs")
def task_docs(s: Stack) -> None:
    """The task's documents: a Doc added to the task is on its page, with What changed."""
    rel = _task_doc(s)
    code, body, _ = s.get(f"/workspace/_task/{rel}?framed=1")
    expect(code == 200 and f'data-doc="{DOC}"' in body, f"the task's page does not list the document: {code}")
    got = post(s, "/api/task-docs/changes", {"folder": rel, "doc": DOC})
    expect("not connected" not in json.dumps(got).lower(), f"What changed: {json.dumps(got)[:300]}")
    expect(post(s, "/api/task-docs/names", {"folder": rel}).get("ok"), "the documents' names were not read")


@check("gene.doc-add")
def doc_add(s: Stack) -> None:
    """Add a document: a pasted link is kept in the task's notes, and the same link again is refused."""
    rel = _task_doc(s)
    code, got = _send(s, "/api/task-docs/add", {"folder": rel, "link": DOC_LINK})
    expect(code == 400 and "already" in json.dumps(got), f"the same link again: {code} {got}")


@check("gene.doc-on-page")
def doc_on_page(s: Stack) -> None:
    """On the page?: which paragraphs of the task's Doc are already on its pages."""
    rel = _task_doc(s)
    code, got = _send(s, "/api/task-docs/on-page", {"folder": rel, "doc": DOC})
    expect(code == 200 and "error" not in got, f"On the page?: {code} {json.dumps(got)[:300]}")


@check("gene.task-comments")
def task_comments(s: Stack) -> None:
    """The open comments on the task's documents, with a run to apply them."""
    rel = _task_doc(s)
    got = post(s, "/api/task-docs/comments", {"folder": rel})
    expect("shorten the intro" in json.dumps(got), f"the task's documents' comments: {json.dumps(got)[:400]}")


@check("gene.comments-by")
def comments_by(s: Stack) -> None:
    """Asked for one person's comments, Rouh finds them on the documents the tasks link."""
    _task_doc(s)
    g_tool(s, "comments_by", {"person": "Tom Carter"}, "shorten the intro")


@check("gene.new-comments")
def new_comments(s: Stack) -> None:
    """The brief's line of new comments on the documents the tasks link, as the brief is made."""
    _task_doc(s)
    got = post(s, "/api/brief/make", {})
    said = json.dumps((got.get("brief") or {}).get("new_comments"))
    expect("shorten the intro" in said, f"the brief's new comments: {said[:400]}")


# --- Google Slides decks (night 27, rouh/decks.py) ------------------------------------------------

def _decks(s: Stack) -> list[str]:
    """Two decks in the stand-in's Drive, named with today's and tomorrow's date on the clock
    here, so whichever day the core's clock is on, one of them is the deck for a talk."""
    google(s)
    if not _G.get("decks"):
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)
        for i, day in enumerate((now, now + timedelta(days=1))):
            deck = f"stack-deck-{i}"
            standin_post(s, GOOGLE, "/_deck", {"id": deck, "name": f"{day.date().isoformat()} Stack talk", "slides": [
                {"id": f"s{i}a", "title": "Why it is hard", "text": "Ten problems", "notes": "Open with the gap."},
                {"id": f"s{i}b", "title": "Robots", "text": "Humanoid robots benchmark", "notes": "Show the video."},
                {"id": f"s{i}c", "title": "Shadow AI", "text": "43% of incidents", "notes": ""}]})
            standin_post(s, GOOGLE, "/_doc_history", {"file": deck, "revisions": [], "comments": [
                {"id": "d1", "author": TOM, "content": "Say which year the 43% is for.", "resolved": False,
                 "createdTime": "2026-10-29T10:00:00Z", "replies": [],
                 "quotedFileContent": {"value": "43% of incidents"}}]})
        _G["decks"] = ["stack-deck-0", "stack-deck-1"]
    return _G["decks"]


@check("gene.deck-slides")
def deck_slides(s: Stack) -> None:
    """A Google Slides deck read through read_doc comes slide by slide, with its notes and comments."""
    deck = _decks(s)[0]
    got = g_tool(s, "read_doc", {"document": f"https://docs.google.com/presentation/d/{deck}/edit"},
                 "=== Slide 3 of 3")
    expect("Speaker notes: Show the video." in got and "which year the 43%" in got,
           f"read_doc did not give the deck's notes and comments: {got[:600]}")


@check("gene.find-slides")
def find_slides(s: Stack) -> None:
    """Asked for a slide by its words, Rouh finds the slide itself, with a link to it."""
    _decks(s)
    got = g_tool(s, "find_slides", {"words": "humanoid robots"}, "Slide 2: Robots")
    expect("#slide=id.s0b" in got or "#slide=id.s1b" in got, f"find_slides gave no link to the slide: {got[:500]}")


@check("gene.talk-deck")
def talk_deck(s: Stack) -> None:
    """The brief's line for a deck named with today's or tomorrow's date: the slide with no notes
    and the comment nobody answered."""
    _decks(s)
    got = post(s, "/api/brief/make", {})
    said = json.dumps((got.get("brief") or {}).get("talk_deck"))
    expect("Stack talk" in said and "which year the 43%" in said and '"no_notes": [3]' in said,
           f"the brief's deck for a talk: {said[:500]}")


@check("gene.rehearse")
def rehearse(s: Stack) -> None:
    """Rehearse: a deck the task links read slide by slide for it, and a picture of one slide."""
    deck = _decks(s)[0]
    rel = the_page(s).rsplit("/", 1)[0]
    code, got = _send(s, "/api/task-docs/add", {"folder": rel, "link": f"https://docs.google.com/presentation/d/{deck}/edit"})
    expect(code == 200 or "already" in json.dumps(got), f"adding the deck to the task: {code} {got}")
    code, body, _ = s.get(f"/workspace/_task/{rel}?framed=1")
    expect(code == 200 and "odoc-rehearse" in body, f"the task's page has no Rehearse on the deck: {code}")
    got = post(s, "/api/task-docs/rehearse", {"folder": rel, "doc": deck})
    slides = (got.get("deck") or {}).get("slides") or []
    expect(len(slides) == 3 and slides[0].get("notes") == "Open with the gap.", f"the deck to rehearse: {json.dumps(got)[:400]}")
    pic = post(s, "/api/task-docs/slide-picture", {"folder": rel, "doc": deck, "slide": slides[1]["id"]})
    expect(str(pic.get("url") or "").endswith(".svg"), f"no picture of the slide: {pic}")


@check("gene.askai-docs")
def askai_docs(s: Stack) -> None:
    """A Google Doc linked in a question to Ask AI is read before it answers."""
    google(s)
    events = ask_ai(s, the_page(s), f"What does this say? {DOC_LINK}")
    expect("Reading the linked document" in json.dumps(events), f"Ask AI did not read the linked Doc: {json.dumps(events)[:400]}")


@check("gene.page-gdoc")
def page_gdoc(s: Stack) -> None:
    """A Google Doc of this page: the page made into a Doc in the owner's Drive."""
    google(s)
    at = the_page(s).rsplit("/", 1)[0]
    code, got = _send(s, "/api/page-gdoc", {"at": at})
    expect(code == 200 and got.get("made"), f"the Google Doc was not made: {code} {json.dumps(got)[:300]}")


@check("gene.shared-with-you")
def shared_with_you(s: Stack) -> None:
    """The brief's line of Docs shared with the person that no task links yet, and Seen on it."""
    google(s)
    for act in ("seen", "undo"):
        got = post(s, "/api/brief/shared_with_you", {"key": "file-2", "act": act})
        expect(got.get("ok"), f"{act} on the brief's line: {got}")


@check("gene.notes-missing")
def notes_missing(s: Stack) -> None:
    """The brief's line of meetings the meeting library sent no notes for, and its answers."""
    for body in ({"act": "library"}, {"key": "n-stack-test", "act": "not_recorded"}, {"key": "n-stack-test", "act": "undo"}):
        got = post(s, "/api/brief/no_notes", body)
        expect(got.get("ok"), f"{body}: {got}")


@check("core.commands-open-credentials")
def commands_open_credentials(s: Stack) -> None:
    """A command run in the core beside Rouh (`docker compose exec core python manage.py ...`)
    opens what Rouh sealed with its key, and leaves the owner's Google working."""
    google(s)
    out = core_py(s, "from rouh.encryption import box\nfrom rouh.models import GoogleConnection\n"
                     "print('key from', box().key_source)\n"
                     "box().open_(GoogleConnection.objects.first().refresh_sealed)\nprint('opens yes')")
    expect("key from environment" in out and "opens yes" in out, f"a command in the core: {out[-300:]}")
    got = api(s, "/api/settings/google", "connection")["connection"]
    expect(got.get("connected") and not got.get("needs_reconnect"), f"Google after a command in the core: {got}")


# --- Night 28: pictures in docs, what was asked on pages, open items, made not handed over -------

#: A picture one pixel square, the smallest PNG there is.
PNG_1PX = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


@check("gene.doc-pictures")
def doc_pictures(s: Stack) -> None:
    """A Google Doc with a picture read through read_doc: the picture marked where it stands."""
    google(s)
    standin_post(s, GOOGLE, "/_doc", {"id": "stack-pictures", "name": "Stack pictures", "parts": [
        "Above the flow.", {"picture": PNG_1PX, "title": "The flow"}, "Below the flow."]})
    g_tool(s, "read_doc", {"document": "https://docs.google.com/document/d/stack-pictures/edit"},
           "[picture 1: The flow]")


@check("gene.page-asks")
def page_asks(s: Stack) -> None:
    """Asked what somebody asked Ask AI on the owner's pages: their request, in their own words."""
    doc = the_page(s)
    core_py(s, "import time\nfrom rouh.tenancy import Tenancy\nfrom rouh.models import AskThread, AskMessage, AskEdit\n"
               "who = Tenancy().only_person()\nnow = time.time()\n"
               f"t = AskThread.objects.create(user_id=str(who.user_id), org_id=who.org_id, doc={doc!r}, created_at=now)\n"
               "AskMessage.objects.create(thread=t, user_id=str(who.user_id), role='user', "
               "content='Make the stack headline green', created_at=now)\n"
               f"AskEdit.objects.create(user_id=str(who.user_id), org_id=who.org_id, page_org_id=who.org_id, doc={doc!r}, "
               "thread_id=t.id, summary='Made the headline green.', before='a', after='b', created_at=now + 1)\n")
    got = s.tool("page_asks", {"person": "me", "days": 2})
    expect("Make the stack headline green" in got and "Made the headline green." in got,
           f"page_asks did not list the request: {got[:500]}")


_NOTES = ("# Stack test pages\n\n## Where this stands\n\nThe spec is written.\n\nOpen:\n"
          "- **Hand the spec to Dana.** Send her the link.\n- Agree the price with Owen.\n\n## What it is\n\nPages.\n")


def _notes(s: Stack, rel: str = "") -> str:
    """A task given notes with two open items, one to hand to somebody, written three days ago:
    the pages' task, or the one named."""
    rel = rel or the_page(s).rsplit("/", 1)[0]
    out = core_py(s, "import os, time\nfrom pathlib import Path\nfrom rouh.config import config\n"
                     f"p = Path(config.assistant_repo) / {rel!r} / 'AGENTS.md'\n"
                     "old = p.read_text(encoding='utf-8') if p.is_file() else ''\n"
                     f"if 'Where this stands' not in old:\n    p.write_text({_NOTES!r} + old, encoding='utf-8')\n"
                     "then = time.time() - 3 * 86400\nos.utime(p, (then, then))\nprint('wrote', p.is_file())")
    expect("wrote True" in out, f"the task's notes could not be written: {out[-300:]}")
    return rel


_HAND: dict = {}


@check("gene.not-handed")
def not_handed(s: Stack) -> None:
    """The brief's line for work a task's notes say to hand to somebody, never shared with them.
    A task of its own: the pages' task is shared by other checks, and a share since the line was
    written counts as handed over.

    The line must have stood two days in the notes, by `git blame`. In the stack, Rouh's save
    commits a change to a task's notes within a minute ("the change made to .../AGENTS.md"), so
    no file time can make it look older, and this failed whenever the save came first (Tests on
    main, 2 November 2026). So the line is asked for with the clock three days on, through the
    function the brief calls (`not_handed.found`), and Handed over and Undo go through the brief's
    own API."""
    if not _HAND:
        _HAND["rel"] = task_folder(s, "Stack hand over")
    rel = _notes(s, _HAND["rel"])
    out = core_py(s, WHO + "import json, time\nfrom rouh import not_handed\nfrom rouh.config import config\n"
                     "print('FOUND' + json.dumps(not_handed.found(who, config.assistant_repo, now=time.time() + 3 * 86400)))")
    said = out.rsplit("FOUND", 1)[-1].strip()
    expect('"person": "Dana"' in said and "Hand the spec to Dana" in said, f"the brief's not handed over: {said[:500]}")
    mine = [i for i in (json.loads(said) or {}).get("items", []) if str(i.get("key", "")).startswith(rel + ":")]
    expect(mine, f"no line for {rel}: {said[:500]}")
    key = mine[0]["key"]
    expect(post(s, "/api/brief/not_handed", {"key": key, "act": "handed"}).get("ok"), "Handed over was refused")
    expect(post(s, "/api/brief/not_handed", {"key": key, "act": "undo"}).get("ok"), "its Undo was refused")


@check("gene.open-items")
def open_items(s: Stack) -> None:
    """The task's open items on its page, and Done marking one done in its notes, and Undo."""
    rel = _notes(s)
    code, body, _ = s.get(f"/workspace/_task/{rel}?framed=1")
    expect(code == 200 and "tkOpen" in body and "Agree the price with Owen." in body,
           f"the task's page has no open items: {code} {body[:200]}")
    import re

    keys = re.findall(r'class="oopen" data-key="([0-9a-f]+)"', body)
    expect(len(keys) == 2, f"two open items, not {keys}")
    expect(post(s, "/api/open-items", {"folder": rel, "key": keys[1], "do": "done"}).get("ok"), "Done was refused")
    out = core_py(s, "from pathlib import Path\nfrom rouh.config import config\n"
                     f"print((Path(config.assistant_repo) / {rel!r} / 'AGENTS.md').read_text())")
    expect("~~Agree the price with Owen.~~ **Done (" in out, f"the item is not marked done in the notes: {out[-400:]}")
    expect(post(s, "/api/open-items", {"folder": rel, "key": keys[1], "do": "undo"}).get("ok"), "Undo was refused")


# --- Night 29: sheets read tab by tab and written, shares that end, dates the tasks wait on -----

SHEET = "stack-sheet"
SHEET_LINK = f"https://docs.google.com/spreadsheets/d/{SHEET}/edit"


def _sheet(s: Stack) -> None:
    google(s)
    standin_post(s, GOOGLE, "/_sheet", {"id": SHEET, "name": "Stack price model", "tabs": [
        {"title": "Summary", "rows": [["Product", "Price"], ["Platform", "49"]]},
        {"title": "Discounts", "rows": [["Bundle", "Discount"], ["Both", "25%"]]}]})


@check("gene.sheet-tabs")
def sheet_tabs(s: Stack) -> None:
    """A Google Sheet read through read_doc: every tab by its name, not only the first."""
    _sheet(s)
    got = g_tool(s, "read_doc", {"document": SHEET_LINK}, "Tab 2 of 2: Discounts")
    expect("2: Both | 25%" in got, f"read_doc did not give the second tab's rows: {got[:500]}")


@check("gene.sheet-write")
def sheet_write(s: Stack) -> None:
    """edit_sheet writes a cell and adds a row, and says what the cell held before."""
    _sheet(s)
    got = g_tool(s, "edit_sheet", {"sheet": SHEET_LINK, "tab": "Discounts",
                                   "cells": [{"at": "B2", "value": "20%"}], "append": [["Partner", "15%"]]},
                 "B2: «25%» → «20%»")
    expect("added 1 row" in got, f"edit_sheet did not add the row: {got[:400]}")


@check("gene.share-ends")
def share_ends(s: Stack) -> None:
    """A share given an end in the Share panel, and taken away by itself once the end has passed."""
    doc = the_page(s)
    connected(s, lambda: post(s, "/api/share/invite", {"rel": doc, "email": "una@example.test", "notify": False,
                                                       "role": "view"}))
    people = api(s, f"/api/share?rel={q(doc)}", "people")["people"]
    una = [p for p in people if p.get("email") == "una@example.test"]
    expect(una and "ends" in una[0], f"the Share panel has no Until: {json.dumps(una)[:300]}")
    got = post(s, "/api/share/ends", {"rel": doc, "token": una[0]["token"], "days": 7})
    expect(float(got.get("ends") or 0) > time.time(), f"the end was not set: {json.dumps(got)[:300]}")
    out = core_py(s, "import time\nfrom rouh.models import ShareEnd, PageGuest\nfrom rouh import share_ends\n"
                     f"ShareEnd.objects.filter(token={una[0]['token']!r}).update(ends_at=time.time() - 60)\n"
                     "share_ends.sweep()\n"
                     f"print('left', PageGuest.objects.filter(token={una[0]['token']!r}).count())")
    expect("left 0" in out, f"the ended share was not taken away: {out[-300:]}")


@check("gene.task-dates")
def task_dates(s: Stack) -> None:
    """The brief's line for a date an open task's notes say something is due by, and Done and Undo."""
    rel = task_folder(s, "Stack dates")
    from datetime import date, timedelta

    d = date.today() - timedelta(days=5)
    notes = (f"# Stack dates\n\n## Where this stands\n\nOpen:\n- The stack policy is due by "
             f"{d.day} {d.strftime('%B')} {d.year}.\n\n## What it is\n\nDates.\n")
    mine, said = [], {}
    # Twice at most: a task the filing model put in no project is filed a little later, and notes
    # written into its old folder are then in no task (seen on amd64 on 5 November 2026).
    for _ in range(2):
        out = core_py(s, "from pathlib import Path\nfrom rouh.config import config\n"
                         f"p = Path(config.assistant_repo) / {rel!r} / 'AGENTS.md'\n"
                         f"p.write_text({notes!r}, encoding='utf-8')\nprint('wrote', p.is_file())")
        expect("wrote True" in out, f"the task's notes could not be written: {out[-300:]}")
        got = post(s, "/api/brief/make", {})
        said = (got.get("brief") or {}).get("task_dates") or {}
        mine = [i for i in said.get("items") or [] if "stack policy" in i.get("words", "")]
        if mine:
            break
        time.sleep(10)
        tasks = api(s, "/api/workspace/index", "tasks")["tasks"]
        rel = next((t["rel"] for t in tasks if (t.get("name") or "").strip().lower() == "stack dates"), rel)
    expect(mine and -6 <= mine[0].get("days", 0) <= -4, f"the brief's dates: {json.dumps(said)[:500]}")
    expect(post(s, "/api/brief/task_dates", {"key": mine[0]["key"], "act": "done"}).get("ok"), "Done was refused")
    expect(post(s, "/api/brief/task_dates", {"key": mine[0]["key"], "act": "undo"}).get("ok"), "its Undo was refused")


# --- Night 30: suggested edits read, a deck written, who lets the note-taker in, a meeting's guests --

@check("gene.doc-suggestions")
def doc_suggestions(s: Stack) -> None:
    """A Google Doc with suggested edits read through read_doc: each marked where it stands."""
    google(s)
    standin_post(s, GOOGLE, "/_doc", {"id": "stack-suggestions", "name": "Stack suggestions", "parts": [
        {"runs": [{"text": "Nine seats at "}, {"text": "€49", "delete": "s.1"}, {"text": "€39", "insert": "s.2"},
                  {"text": " a seat."}]}]})
    got = g_tool(s, "read_doc", {"document": "https://docs.google.com/document/d/stack-suggestions/edit"},
                 "[suggested deletion: «€49»][suggested insertion: «€39»]")
    expect("1 suggested insertion and 1 suggested deletion" in got, f"read_doc did not count them: {got[:500]}")


@check("gene.slide-write")
def slide_write(s: Stack) -> None:
    """edit_slides replaces words on a slide and writes its speaker notes, saying what they said."""
    google(s)
    standin_post(s, GOOGLE, "/_deck", {"id": "stack-write-deck", "name": "Stack write deck", "slides": [
        {"id": "w1", "title": "The price", "text": "Nine seats at €49", "notes": "Say it once."}]})
    got = g_tool(s, "edit_slides", {"deck": "https://docs.google.com/presentation/d/stack-write-deck/edit",
                                    "replace": [{"find": "€49", "put": "€39"}],
                                    "notes": [{"slide": 1, "text": "Then stop."}]},
                 "«€49» → «€39» on slide 1")
    expect("they said «Say it once.»" in got, f"edit_slides did not say what the notes held: {got[:400]}")


_CALLS = """
import json, os
from datetime import datetime, timedelta, timezone
from rouh.models import User
from rouh.tenancy import Identity
from rouh.synapse import ingest, master
from rouh.synapse.sources import calsync
u = User.objects.filter(is_superuser=False).order_by('id').first() or User.objects.order_by('id').first()
org = str(getattr(u, 'org_id', '') or '')
if not org:
    from rouh.models import Organisation
    org = str(Organisation.objects.first().pk)
who = Identity(user_id=str(u.pk), org_id=org, email=u.email or '')
ds = master.make(org, str(u.pk))['dataset']
now = datetime.now(timezone.utc)
soon = now + timedelta(hours=2)
me = (u.email or 'owner@example.test').lower()
def g(e, n, st='accepted', mine=False):
    return {'email': e, 'displayName': n, 'responseStatus': st, **({'self': True} if mine else {})}
cal = {'calendar_id': me, 'name': 'Stack'}
for raw in [
    {'id': 'st1', 'summary': 'Stack catch-up with Eleven', 'iCalUID': 'st1@test', 'updated': now.isoformat(),
     'start': {'dateTime': soon.isoformat()}, 'end': {'dateTime': (soon + timedelta(minutes=30)).isoformat()},
     'organizer': {'email': 'viktor@elevenvc.test', 'displayName': 'Viktor Ivanov'},
     'attendees': [g(me, 'Owner', mine=True), g('viktor@elevenvc.test', 'Viktor Ivanov')],
     'hangoutLink': 'https://meet.google.com/aaa-bbbb-ccc'},
    {'id': 'st2', 'summary': 'Stack pages review call', 'iCalUID': 'st2@test', 'updated': now.isoformat(),
     'start': {'dateTime': (now + timedelta(days=1)).isoformat()},
     'end': {'dateTime': (now + timedelta(days=1, hours=1)).isoformat()},
     'organizer': {'email': me, 'self': True},
     'attendees': [g(me, 'Owner', mine=True), g('owen@northwind.test', 'Owen Marsh')],
     'hangoutLink': 'https://meet.google.com/ddd-eeee-fff'}]:
    calsync.apply(ds, raw, cal, lane='live', by='stack', out={}, owner_email=me)
"""


@check("gene.share-meeting")
def share_meeting(s: Stack) -> None:
    """The Share panel offers a meeting about the page, and Share with them shares with its guests."""
    core_py(s, _CALLS + "print('seeded')")
    doc = the_page(s)
    title_words = doc.rsplit("/", 1)[-1]
    got = api(s, f"/api/share/meetings?rel={q(doc)}", "meetings")["meetings"]
    mine = [m for m in got if m.get("title") == "Stack pages review call"]
    expect(mine and "owen@northwind.test" in mine[0]["guests"],
           f"no meeting offered for {title_words}: {json.dumps(got)[:400]}")
    done: dict = {}
    connected(s, lambda: done.update(post(s, "/api/share/meetings", {"rel": doc, "key": mine[0]["key"],
                                                                     "notify": False, "role": "view"})))
    expect("owen@northwind.test" in (done.get("shared") or []), f"not shared with the guests: {json.dumps(done)[:400]}")


# --- Night 31: files in Drive read, what is attached read, a copy made, attached to a meeting --

#: A one-page PDF with words in it, the smallest a reader takes: its catalogue, its page, its words.
def _a_pdf(lines: list[str]) -> str:
    import base64
    import io

    content = "BT /F1 14 Tf 72 720 Td 18 TL " + " ".join(f"({x}) Tj T*" for x in lines) + " ET"
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
            "/Resources << /Font << /F1 5 0 R >> >> >>",
            f"<< /Length {len(content)} >>\nstream\n{content}\nendstream",
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offs = io.BytesIO(), []
    out.write(b"%PDF-1.4\n")
    for i, o in enumerate(objs, 1):
        offs.append(out.tell())
        out.write(f"{i} 0 obj\n{o}\nendobj\n".encode())
    x = out.tell()
    out.write(f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode())
    for o in offs:
        out.write(f"{o:010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{x}\n%%EOF\n".encode())
    return base64.b64encode(out.getvalue()).decode()


@check("gene.drive-files")
def drive_files(s: Stack) -> None:
    """A PDF in Drive read through read_doc: its words, and the line that says what it was."""
    google(s)
    standin_post(s, GOOGLE, "/_file", {"id": "stack-msa", "name": "Stack MSA.pdf", "mimeType": "application/pdf",
                                       "base64": _a_pdf(["Stack master services agreement", "Term: 24 months."])})
    got = g_tool(s, "read_doc", {"document": "stack-msa"}, "A PDF in Drive")
    expect("Term: 24 months." in got, f"read_doc did not read the PDF's words: {got[:500]}")


@check("gene.drive-copy")
def drive_copy(s: Stack) -> None:
    """copy_drive_file makes a copy of a Doc, fills in its words, and leaves the original as it was."""
    google(s)
    standin_post(s, GOOGLE, "/_doc", {"id": "stack-template", "name": "Stack template",
                                      "parts": ["Statement of work for {{client}}."]})
    got = g_tool(s, "copy_drive_file", {"file": "stack-template", "name": "Stack copy",
                                        "fill": [{"find": "{{client}}", "put": "Acme"}]}, "Filled in")
    made = got.split("file id ", 1)[1].split(",", 1)[0].split(" ", 1)[0].strip(".")
    expect("for Acme" in s.tool("read_doc", {"document": made}), f"the copy was not filled in: {got[:400]}")
    expect("{{client}}" in s.tool("read_doc", {"document": "stack-template"}), "the original was changed")


@check("gene.raise-attached")
def raise_attached(s: Stack) -> None:
    """What to raise's reading of a meeting gives the model the document attached to its invitation."""
    google(s)
    standin_post(s, GOOGLE, "/_doc", {"id": "stack-agenda", "name": "Stack agenda",
                                      "parts": ["Agenda: the start date and who signs."]})
    # asyncio.run in a Django shell: Django refuses the database from it unless told (the server
    # itself reads it from threads), and the read swallowed that and returned nothing.
    out = core_py(s, """
import asyncio, json, os
os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"
from rouh.models import User
from rouh.tenancy import Identity
from rouh import raise_attached, runtime
u = User.objects.filter(is_superuser=False).order_by('id').first() or User.objects.order_by('id').first()
who = Identity(user_id=str(u.pk), org_id=str(u.org_id), email=u.email or '')
event = {'title': 'Stack call', 'attachments': [{'title': 'Stack agenda', 'link': 'https://docs.google.com/document/d/stack-agenda/edit',
                                                 'file_id': 'stack-agenda', 'mime_type': ''}]}
got = asyncio.run(raise_attached.read(who, event, runtime.brief_google(who) if runtime.brief_google else None))
print(json.dumps(raise_attached.question_lines(got))[:600])
""")
    expect("Agenda: the start date" in out, f"the attached document was not read: {out[-500:]}")


@check("gene.meeting-attach")
def meeting_attach(s: Stack) -> None:
    """A task's Google Doc is offered the meeting about it the owner organises, and Attach puts it on
    the invitation."""
    google(s)
    folder = task_folder(s, "Stack pages review")
    core_py(s, f"""
from pathlib import Path
from rouh.config import config
p = Path(config.assistant_repo) / {folder!r} / 'AGENTS.md'
p.write_text(p.read_text() + '\\n[Stack proposal](https://docs.google.com/document/d/stack-template/edit)\\n')
""" + _CALLS + "print('seeded')")
    got = post(s, "/api/task-docs/attach", {"folder": folder, "doc": "stack-template"})
    expect(got.get("ok") and any(m.get("title") == "Stack pages review call" for m in got.get("meetings") or []),
           f"no meeting offered: {json.dumps(got)[:400]}")


# --- Night 32: files inside files read, away and focus time, flights left open, time before its date --

@check("gene.inside-files")
def inside_files(s: Stack) -> None:
    """A zip archive and a forwarded email are read by the reader every attachment goes through."""
    out = core_py(s, """
import io, os, tempfile, zipfile
from email.message import EmailMessage
from rouh import uploads
m = EmailMessage()
m['From'] = 'Owen <owen@northwind.test>'
m['Subject'] = 'Stack discount policy'
m.set_content('Partners get 12 percent.')
pack = io.BytesIO()
with zipfile.ZipFile(pack, 'w') as z:
    z.writestr('pack/readme.txt', 'Answers due by 20 November.')
    z.writestr('pack/fwd.eml', bytes(m))
d = tempfile.mkdtemp()
p = os.path.join(d, 'pack.zip')
open(p, 'wb').write(pack.getvalue())
print(uploads.words_in(p, '', 'pack.zip'))
""")
    expect("Answers due by 20 November." in out and "Partners get 12 percent." in out,
           f"the zip and the email inside it were not read: {out[-500:]}")


@check("gene.calendar-away")
def calendar_away(s: Stack) -> None:
    """block_my_time puts Google's own out-of-office on the calendar, with its message."""
    from datetime import date, timedelta

    day = (date.today() + timedelta(days=10)).isoformat()
    got = g_tool(s, "block_my_time", {"kind": "away", "start": day, "end": day,
                                      "message": "Away for the stack."}, "Out of office")
    expect("Away for the stack." in got and "decline" in got, f"no out-of-office said: {got[:400]}")


@check("gene.flight-open")
def flight_open(s: Stack) -> None:
    """A flight on another calendar, with the main calendar free then, is found for the brief."""
    from datetime import datetime, timedelta, timezone

    google(s)
    start = (datetime.now(timezone.utc) + timedelta(days=3)).replace(hour=7, minute=0, second=0, microsecond=0)
    standin_post(s, GOOGLE, "/_calendar", {"id": "stack-family@group.calendar.google.com", "summary": "Family"})
    standin_post(s, GOOGLE, "/_calendar_event", {"calendar": "stack-family@group.calendar.google.com", "event": {
        "id": "stack-flight", "summary": "Flight LH 1427 SOF → FRA",
        "start": {"dateTime": start.isoformat()}, "end": {"dateTime": (start + timedelta(hours=2)).isoformat()}}})
    out = core_py(s, """
import asyncio, json, os
os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"
from rouh.models import User
from rouh.tenancy import Identity
from rouh import flight_open, runtime
u = User.objects.filter(is_superuser=False).order_by('id').first() or User.objects.order_by('id').first()
who = Identity(user_id=str(u.pk), org_id=str(u.org_id), email=u.email or '')
print(json.dumps(asyncio.run(flight_open.found(who, runtime.brief_google)))[:800])
""")
    expect("Flight LH 1427" in out, f"the flight was not found: {out[-500:]}")


@check("gene.task-time")
def task_time(s: Stack) -> None:
    """A task due soon has its section, and Find time says the free hours before its date."""
    from datetime import date, timedelta

    google(s)
    folder = task_folder(s, "Stack time before its date")
    due = date.today() + timedelta(days=6)
    core_py(s, f"""
from pathlib import Path
from rouh.config import config
p = Path(config.assistant_repo) / {folder!r} / 'AGENTS.md'
p.write_text('# Stack\\n\\n## Where this stands\\n\\nThe report is due by {due.day} {due:%B} {due.year}.\\n')
print('seeded')
""")
    got = post(s, "/api/task-time", {"folder": folder, "act": "find"})
    expect(got.get("ok") and "hours" in got and isinstance(got.get("gaps"), list),
           f"Find time did not answer: {json.dumps(got)[:400]}")


# --- Night 33: invitations read on your clock, invitations not in your calendar, when others are free,
# --- not booked over someone busy

def _invite_raw(uid: str, title: str, start: str, end: str) -> str:
    """An Outlook-style invitation, Pacific time with a Windows zone name, as raw mail in base64."""
    import base64
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    cal = "\r\n".join([
        "BEGIN:VCALENDAR", "METHOD:REQUEST", "BEGIN:VEVENT", f"UID:{uid}",
        "ORGANIZER;CN=Paola Ricci:mailto:paola@packin.test",
        "ATTENDEE;PARTSTAT=NEEDS-ACTION;CN=Alex:mailto:alex.morgan@example.com",
        f"SUMMARY:{title}", f"DTSTART;TZID=Pacific Standard Time:{start}",
        f"DTEND;TZID=Pacific Standard Time:{end}", "END:VEVENT", "END:VCALENDAR"]) + "\r\n"
    m = MIMEMultipart("alternative")
    m["From"], m["To"], m["Subject"] = "Paola Ricci <paola@packin.test>", "alex.morgan@example.com", title
    m.attach(MIMEText("Microsoft Teams meeting", "plain"))
    part = MIMEText(cal, "calendar")
    part.set_param("method", "REQUEST")
    m.attach(part)
    return base64.b64encode(m.as_bytes()).decode()


@check("gene.mail-invites")
def mail_invites(s: Stack) -> None:
    """read_mail reads an email's calendar invitation, its time said on the person's clock."""
    google(s)
    sent = json.loads(standin_post(s, GOOGLE, "/_deliver", {
        "raw": _invite_raw("stack-invite-1", "Stack DPA review", "20270310T090000", "20270310T100000")}))
    got = g_tool(s, "read_mail", {"message_id": sent["id"]}, "read from its calendar file")
    expect("Stack DPA review" in got and "Los Angeles time" in got, f"the invitation was not read: {got[:600]}")


@check("gene.invite-missing")
def invite_missing(s: Stack) -> None:
    """An invitation on none of the calendars is found for the brief; one already there is not."""
    google(s)
    out = core_py(s, """
import asyncio, json, os, time
os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"
from zoneinfo import ZoneInfo
from rouh.models import User
from rouh.tenancy import Identity
from rouh import clock, invite_missing, invites, runtime
u = User.objects.filter(is_superuser=False).order_by('id').first() or User.objects.order_by('id').first()
who = Identity(user_id=str(u.pk), org_id=str(u.org_id), email=u.email or '')
text = ("BEGIN:VCALENDAR\\nMETHOD:REQUEST\\nBEGIN:VEVENT\\nUID:stack-missing-1\\n"
        "ORGANIZER;CN=Nadia:mailto:nadia@lumen.test\\nSUMMARY:Stack kick-off\\n"
        "DTSTART:20990310T110000Z\\nDTEND:20990310T120000Z\\nEND:VEVENT\\nEND:VCALENDAR\\n")
one = invites.parse(text, clock.zone_of(who))[0]
invite_missing.AHEAD = 365 * 100
invite_missing._found[str(who.user_id)] = (time.time(), [{"invite": one, "message": {"id": "m-stack", "subject": "x"},
                                                          "inbox": "a@example.com", "at": time.time()}])
print(json.dumps(asyncio.run(invite_missing.found(who, runtime.brief_google)))[:800])
""")
    expect("Stack kick-off" in out, f"the invitation missing from the calendar was not found: {out[-500:]}")


@check("gene.when-free")
def when_free(s: Stack) -> None:
    """when_free reads a colleague's busy times through Google's free/busy, and says common free times."""
    google(s)
    standin_post(s, GOOGLE, "/_calendar_event", {"calendar": "todor@example.com", "event": {
        "id": "stack-busy", "summary": "(private)", "start": {"dateTime": "2027-03-10T09:00:00+00:00"},
        "end": {"dateTime": "2027-03-10T17:00:00+00:00"}}})
    got = g_tool(s, "when_free", {"people": ["todor@example.com", "nobody@outside.test"],
                                  "start": "2027-03-10", "end": "2027-03-11"}, "todor@example.com is busy")
    expect("nobody@outside.test: not read" in got and "Times when" in got, f"when_free: {got[:600]}")


@check("gene.busy-guard")
def busy_guard(s: Stack) -> None:
    """A meeting with a guest who is busy then is not booked, and other times are offered."""
    google(s)
    standin_post(s, GOOGLE, "/_calendar_event", {"calendar": "ivo@example.com", "event": {
        "id": "stack-ivo-busy", "summary": "(private)", "start": {"dateTime": "2027-03-11T00:00:00+00:00"},
        "end": {"dateTime": "2027-03-11T23:00:00+00:00"}}})
    got = g_tool(s, "create_calendar_event", {"title": "Stack held meeting", "start": "2027-03-11T14:00",
                                              "minutes": 30, "guests": ["ivo@example.com"]}, "Not booked")
    expect("ivo@example.com is busy" in got, f"the busy guest was not named: {got[:500]}")


# --- Night 33, second run: booked with a call link, meetings with nowhere to meet, a calendar link
# --- read, a mistyped address caught

@check("gene.meet-link")
def meet_link(s: Stack) -> None:
    """A meeting booked with a guest and no place goes out with a Google Meet link, and says so."""
    got = g_tool(s, "create_calendar_event", {"title": "Stack call with a link", "start": "2027-03-12T10:00",
                                              "minutes": 30, "guests": ["kim@packin.test"]}, "video call")
    expect("Booked with a call link" in got, f"the Meet link was not said: {got[:500]}")


@check("gene.no-place")
def no_place(s: Stack) -> None:
    """A meeting of the owner's with a guest and no place is found for the brief; Add a Meet link gives it one."""
    google(s)
    out = core_py(s, """
import asyncio, json, os
os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"
from datetime import datetime, timedelta, timezone
from rouh.models import User
from rouh.tenancy import Identity
from rouh import no_place, runtime
u = User.objects.filter(is_superuser=False).order_by('id').first() or User.objects.order_by('id').first()
who = Identity(user_id=str(u.pk), org_id=str(u.org_id), email=u.email or '')
async def go():
    cal = runtime.brief_google(who).calendar
    made = await cal.create("primary", title="Stack meeting with nowhere", guests=["kim@packin.test"],
                            start=datetime.now(timezone.utc) + timedelta(hours=20), minutes=30, notify=False)
    got = await no_place.found(who, runtime.brief_google)
    line = next(i for i in got["items"] if i["title"] == "Stack meeting with nowhere")
    done = await no_place.act(who, runtime.brief_google, line["key"], "add",
                              calendar_id=line["calendar_id"], event_id=line["event_id"])
    return {"found": line["title"], "video": done.get("video")}
print(json.dumps(asyncio.run(go())))
""")
    expect("Stack meeting with nowhere" in out and "meet.google.com" in out,
           f"the meeting with nowhere to meet was not found or given a link: {out[-500:]}")


@check("gene.calendar-link")
def calendar_link(s: Stack) -> None:
    """A published calendar is read on the person's clock: a weekly repeat, a date taken out, a moved one."""
    out = core_py(s, """
import asyncio, httpx
from datetime import datetime
from zoneinfo import ZoneInfo
from rouh import calendar_link
ICS = "\\r\\n".join(["BEGIN:VCALENDAR", "X-WR-CALNAME:Stack feed",
    "BEGIN:VEVENT", "UID:w", "SUMMARY:Stack weekly", "DTSTART;TZID=W. Europe Standard Time:20270104T100000",
    "DTEND;TZID=W. Europe Standard Time:20270104T110000", "RRULE:FREQ=WEEKLY;BYDAY=MO",
    "EXDATE;TZID=W. Europe Standard Time:20270111T100000", "END:VEVENT",
    "BEGIN:VEVENT", "UID:w", "SUMMARY:Stack weekly (moved)", "RECURRENCE-ID;TZID=W. Europe Standard Time:20270118T100000",
    "DTSTART;TZID=W. Europe Standard Time:20270119T150000", "DTEND;TZID=W. Europe Standard Time:20270119T160000",
    "END:VEVENT", "END:VCALENDAR", ""])
calendar_link._allowed = lambda: {"feed.test:443"}
mock = httpx.MockTransport(lambda request: httpx.Response(200, text=ICS))
said, found = asyncio.run(calendar_link.answer({"url": "webcal://feed.test/stack.ics", "from": "2027-01-04", "days": 21},
                                               ZoneInfo("Europe/Sofia"), now=datetime(2027, 1, 1, tzinfo=ZoneInfo("UTC")),
                                               transport=mock))
print(said)
""")
    expect("Monday 4 January" in out and "11:00-12:00: Stack weekly" in out and "Monday 11 January" not in out
           and "Tuesday 19 January" in out and "16:00-17:00: Stack weekly (moved)" in out,
           f"the calendar was not read as it says: {out[-800:]}")


@check("gene.address-check")
def address_check(s: Stack) -> None:
    """An address a letter off one the owner has is held, with the known one named; a new one is not."""
    out = core_py(s, """
import json
from rouh.models import User
from rouh.tenancy import Identity
from rouh import address_check
u = User.objects.filter(is_superuser=False).order_by('id').first() or User.objects.order_by('id').first()
mine = (u.email or 'alex.morgan@example.com').lower()
who = Identity(user_id=str(u.pk), org_id=str(u.org_id), email=mine)
local, _, domain = mine.partition('@')
typo = local + '@' + domain[0] + domain[2] + domain[1] + domain[3:]
held, found = address_check.check(who, to=typo)
fine, _ = address_check.check(who, to='somebody.new@elsewhere.test')
print(json.dumps({"held": held, "mine": mine, "fine": fine}))
""")
    expect("Not sent" in out and '"fine": ""' in out, f"the mistyped address was not held: {out[-500:]}")


# --- Night 34: away, said their automatic reply; did not arrive; waiting on your answer;
# --- unsubscribe in the inbox card

def _owner_py(body: str) -> str:
    """Python in the core with `who`, the owner, and asyncio, for a gene with no screen of its own."""
    return """
import asyncio, json, os
os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"
from rouh.models import User
from rouh.tenancy import Identity
u = User.objects.filter(is_superuser=False).order_by('id').first() or User.objects.order_by('id').first()
who = Identity(user_id=str(u.pk), org_id=str(u.org_id), email=u.email or '')
""" + body


@check("gene.away-replies")
def away_replies(s: Stack) -> None:
    """A meeting with a guest whose automatic reply says they are away is held, with the reply's words."""
    google(s)
    standin_post(s, GOOGLE, "/_deliver", {
        "from": "Pia Stack <pia@away.test>", "quiet": True, "days_ago": 1,
        "subject": "Automatic reply: Stack plan", "headers": {"Auto-Submitted": "auto-replied"},
        "text": "I am out of the office until 30 November. Please write to Ola at ola@away.test."})
    got = g_tool(s, "create_calendar_event", {"title": "Stack plan", "start": "2027-03-12T10:00", "minutes": 30,
                                              "guests": ["pia@away.test"]}, "Not booked yet")
    expect("out of the office until 30 November" in got, f"the automatic reply was not read: {got[:500]}")


@check("gene.not-arrived")
def not_arrived(s: Stack) -> None:
    """A bounce in Rouh's inbox becomes a notice that says which address failed and why."""
    out = core_py(s, _owner_py("""
from rouh import not_arrived, notices
said = asyncio.run(not_arrived.seen(who, {
    "id": "stack-bounce-1", "thread_id": "t-stack", "from": "Mail Delivery Subsystem <mailer-daemon@googlemail.com>",
    "subject": "Delivery Status Notification (Failure)", "failed_recipients": "nobody@stack-typo.test",
    "body": "The response was: 550 5.1.1 The email account that you tried to reach does not exist."}))
print(said)
print(json.dumps([n["title"] for n in notices.listing(who)["items"]][:5]))
"""))
    expect("nobody@stack-typo.test" in out and "Did not arrive" in out, f"the bounce was not told: {out[-500:]}")


@check("gene.to-answer")
def to_answer(s: Stack) -> None:
    """to_answer lists an email from a person, to the owner, that asked something and was not answered."""
    google(s)
    standin_post(s, GOOGLE, "/_deliver", {
        "from": "Rita Stack <rita@stack-client.test>", "quiet": True, "days_ago": 2,
        "subject": "Stack contract", "text": "Could you send the signed contract by Friday?\n\nRita"})
    got = g_tool(s, "to_answer", {}, "waiting on your answer")
    expect("Could you send the signed contract by Friday?" in got, f"the unanswered ask was not found: {got[:600]}")


@check("gene.inbox-unsubscribe")
def inbox_unsubscribe(s: Stack) -> None:
    """A list's one-click unsubscribe is offered, and never sent to an address on the machine's own network."""
    out = core_py(s, _owner_py("""
from rouh import inbox_unsubscribe as iu
mail = {"from": "Stack News <news@stack-list.test>", "list_unsubscribe": "<https://127.0.0.1/unsub/1>",
        "list_unsubscribe_post": "List-Unsubscribe=One-Click"}
print(json.dumps(iu.offer(mail)))
print(json.dumps(asyncio.run(iu.press(who, mail))))
"""))
    expect('"how": "one-click"' in out and "not on the public internet" in out,
           f"unsubscribe was not offered, or went to a private address: {out[-500:]}")


# --- Night 34, this Rouh's run: a file promised, not attached (with night 35's said attached,
# --- nothing attached); guests who have not said yes; public holidays read from Google; remind
# --- me about this email

@check("gene.attach-promised")
def attach_promised(s: Stack) -> None:
    """An email whose words say a file is attached, sent with no file, is held and not sent."""
    got = g_tool(s, "send_mail", {"to": "dana@stack-client.test", "subject": "Stack proposal",
                                  "body": "Hi Dana,\n\nPlease find attached the proposal.\n"}, "Not sent")
    expect("no file is on it" in got, f"the email with no file was not held: {got[:500]}")
    got = g_tool(s, "send_mail", {"to": "owen@attach-stack.test", "subject": "The proposal",
                                  "body": "Hi Owen, please find the proposal attached."}, "nothing is attached")
    expect("Not sent yet" in got, f"the email was not held: {got[:500]}")


@check("gene.not-said-yes")
def not_said_yes(s: Stack) -> None:
    """A meeting of the owner's tomorrow whose guest has not answered is found for the brief."""
    google(s)
    out = core_py(s, _owner_py("""
from datetime import datetime, timedelta, timezone
from rouh import not_said_yes, runtime, clock
async def go():
    cal = runtime.brief_google(who).calendar
    zone = clock.zone_of(who)
    start = (datetime.now(zone) + timedelta(days=1)).replace(hour=11, minute=0, second=0, microsecond=0)
    await cal.create("primary", title="Stack kickoff nobody accepted", guests=["kim@packin.test"],
                     start=start, minutes=30, notify=False)
    got = await not_said_yes.found(who, runtime.brief_google)
    line = next(i for i in (got or {}).get("items", []) if i["title"] == "Stack kickoff nobody accepted")
    return {"found": line["title"], "nobody": line["nobody"], "write": line["write"][:40]}
print(json.dumps(asyncio.run(go())))
"""))
    expect("Stack kickoff nobody accepted" in out and '"nobody": true' in out,
           f"the meeting nobody accepted was not found: {out[-500:]}")


@check("gene.public-holidays")
def public_holidays(s: Stack) -> None:
    """public_holidays reads a country's holidays from Google's holiday calendar for it."""
    google(s)
    standin_post(s, GOOGLE, "/_calendar_event", {"calendar": "en.pl#holiday@group.v.calendar.google.com", "event": {
        "id": "stack-pl-1111", "summary": "National Independence Day", "description": "Public holiday",
        "start": {"date": "2027-11-11"}, "end": {"date": "2027-11-12"}}})
    got = g_tool(s, "public_holidays", {"country": "Poland", "date": "2027-11-11"}, "public holiday in Poland")
    expect("National Independence Day" in got, f"the holiday was not read: {got[:500]}")


@check("gene.inbox-remind")
def inbox_remind(s: Stack) -> None:
    """Remind me about this email makes one reminder on Clockwork, at the time chosen, naming the email."""
    out = core_py(s, _owner_py("""
from rouh import inbox_remind, reminders
said = inbox_remind.make(who, found={"id": "stack-m1", "from": "Rita Stack <rita@stack-client.test>",
                                     "subject": "Stack contract"}, when="morning", chat="", inbox="", read_only=False)
row = reminders.one(who, said["reminder"])
print(json.dumps({"said": said["said"], "title": row.title, "kind": row.kind}))
"""))
    expect("Back to the email from Rita Stack" in out and "tomorrow morning" in out,
           f"the reminder was not made: {out[-500:]}")


# --- Night 35: on their clock too; renews soon; newsletters you never open (said attached,
# --- nothing attached, is in gene.attach-promised above)

@check("gene.their-clock")
def their_clock(s: Stack) -> None:
    """An email naming a time, to somebody whose own mail is written on another clock, is held with their hour."""
    google(s)
    standin_post(s, GOOGLE, "/_deliver", {
        "from": "Marco Stack <marco@clock-stack.test>", "quiet": True, "days_ago": 2,
        "date": "Tue, 03 Nov 2026 09:12:00 -0500", "subject": "Our call",
        "text": "Happy to talk next week."})
    got = g_tool(s, "send_mail", {"to": "marco@clock-stack.test", "subject": "Our call",
                                  "body": "Can we talk at 15:00 tomorrow?"}, "Not sent yet")
    expect("UTC-05:00" in got and "on theirs" in got, f"their clock was not told: {got[:600]}")


@check("gene.renewal-notice")
def renewal_notice(s: Stack) -> None:
    """An email saying a subscription renews soon becomes a notice with what, when and how much."""
    out = core_py(s, _owner_py("""
import time
from datetime import datetime, timedelta
from rouh import notices, renewal_notice
day = (datetime.now() + timedelta(days=9)).strftime("%-d %B %Y")
said = asyncio.run(renewal_notice.seen(who, {
    "id": "stack-renewal-1", "thread_id": "t-renew", "from": "Stackly Billing <billing@stackly.test>",
    "subject": "Your Stackly Pro plan renews soon", "at": time.time(),
    "body": f"Your Stackly Pro plan will automatically renew on {day} for $48.00."}))
print(said)
print(json.dumps([n["title"] + " | " + (n.get("body") or "") for n in notices.listing(who)["items"]][:5]))
"""))
    expect("Renews soon: Stackly" in out and "$48.00" in out, f"the renewal was not told: {out[-500:]}")


@check("gene.unread-lists")
def unread_lists(s: Stack) -> None:
    """unread_lists finds a newsletter none of whose emails was opened, and leaves out one that is read."""
    google(s)
    for n in range(3):
        for name, read in (("Never Read Weekly", False), ("Always Read Daily", True)):
            slug = name.split()[0].lower()
            standin_post(s, GOOGLE, "/_deliver", {
                "from": f"{name} <news@{slug}-stack.test>", "quiet": True, "days_ago": 3 + n * 7, "read": read,
                "subject": f"{name} number {n}", "text": "This week's news. Unsubscribe at the foot.",
                "headers": {"List-Unsubscribe": f"<https://{slug}-stack.test/u/{n}>",
                            "List-Id": f"{name} <{slug}.stack.test>"}})
    got = g_tool(s, "unread_lists", {}, "Never Read Weekly")
    expect("Always Read Daily" not in got and "none opened" in got, f"the lists were not counted: {got[:600]}")


@check("gene.their-hours")
def their_hours(s: Stack) -> None:
    """A meeting with a guest whose own mail is written on UTC-05:00, at three in their night, is held."""
    google(s)
    standin_post(s, GOOGLE, "/_deliver", {
        "from": "Nora Stack <nora@hours-stack.test>", "quiet": True, "days_ago": 1,
        "date": "Wed, 04 Nov 2026 10:00:00 -0500", "subject": "Hello", "text": "Talk soon."})
    got = s.tool("create_calendar_event", {"title": "Stack hours", "start": "2027-03-12T10:00", "minutes": 30,
                                           "guests": ["nora@hours-stack.test"]})
    expect("Not booked yet" in got and "UTC-05:00" in got, f"the meeting in the guest's night was booked: {got[:500]}")


# --- Night 36: not booked on a guest's public holiday; invitations you have not answered; where your
# --- meeting time went; you meet them soon

@check("gene.holiday-guard")
def holiday_guard(s: Stack) -> None:
    """A meeting with a guest at a .pl address on Poland's public holiday is held, with its name."""
    google(s)
    standin_post(s, GOOGLE, "/_calendar_event", {"calendar": "en.pl#holiday@group.v.calendar.google.com", "event": {
        "id": "stack-pl-0503", "summary": "Constitution Day", "description": "Public holiday",
        "start": {"date": "2027-05-03"}, "end": {"date": "2027-05-04"}}})
    got = s.tool("create_calendar_event", {"title": "Stack holiday", "start": "2027-05-03T11:00", "minutes": 30,
                                           "guests": ["marta@holiday-stack.pl"]})
    expect("Not booked" in got and "Constitution Day" in got, f"the meeting on the guest's holiday was booked: {got[:500]}")


@check("gene.not-answered")
def not_answered(s: Stack) -> None:
    """An invitation of somebody else's tomorrow, not answered, is found for the brief, and Yes answers it."""
    google(s)
    out = core_py(s, _owner_py("""
from datetime import datetime, timedelta, timezone
import urllib.request
from rouh import not_answered, runtime, clock
async def go():
    cal = runtime.brief_google(who).calendar
    me = str((await cal.about("primary")).get("id") or "")
    zone = clock.zone_of(who)
    start = (datetime.now(zone) + timedelta(days=1)).replace(hour=11, minute=0, second=0, microsecond=0)
    raw = {"id": "stack-invite", "summary": "Stack invitation not answered",
           "start": {"dateTime": start.isoformat()}, "end": {"dateTime": (start + timedelta(minutes=30)).isoformat()},
           "organizer": {"email": "olga@answer-stack.test"},
           "attendees": [{"email": me, "self": True, "responseStatus": "needsAction"},
                         {"email": "olga@answer-stack.test", "organizer": True, "responseStatus": "accepted"}]}
    req = urllib.request.Request(GOOGLE_URL + "/_calendar_event", method="POST",
                                 data=json.dumps({"calendar": me, "event": raw}).encode(),
                                 headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req).read()
    got = await not_answered.found(who, runtime.brief_google)
    line = next(i for i in (got or {}).get("items", []) if i["title"] == "Stack invitation not answered")
    done = await not_answered.act(who, runtime.brief_google, line["key"], "accepted",
                                  calendar_id=line["calendar_id"], event_id=line["event_id"])
    return {"found": line["title"], "answer": done.get("my_response")}
print(json.dumps(asyncio.run(go())))
""").replace("GOOGLE_URL", repr(f"http://standins:{GOOGLE}")))
    expect("Stack invitation not answered" in out and '"answer": "accepted"' in out,
           f"the invitation not answered was not found or answered: {out[-500:]}")


@check("gene.meeting-hours")
def meeting_hours(s: Stack) -> None:
    """meeting_hours counts the meetings with one company last week, and leaves out one declined."""
    google(s)
    out = core_py(s, _owner_py("""
from datetime import datetime, timedelta
import urllib.request
from rouh import runtime, clock
async def go():
    cal = runtime.brief_google(who).calendar
    me = str((await cal.about("primary")).get("id") or "")
    zone = clock.zone_of(who)
    day = (datetime.now(zone) - timedelta(days=6)).replace(hour=10, minute=0, second=0, microsecond=0)
    for n, (hours, mine) in enumerate(((1, "accepted"), (2, "accepted"), (3, "declined"))):
        start = day + timedelta(hours=n * 4)
        raw = {"id": f"stack-hours-{n}", "summary": "Stack hours", "start": {"dateTime": start.isoformat()},
               "end": {"dateTime": (start + timedelta(hours=hours)).isoformat()}, "organizer": {"email": me, "self": True},
               "attendees": [{"email": me, "self": True, "responseStatus": mine},
                             {"email": "ivo@hours-co.test", "responseStatus": "accepted"}]}
        req = urllib.request.Request(GOOGLE_URL + "/_calendar_event", method="POST",
                                     data=json.dumps({"calendar": me, "event": raw}).encode(),
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req).read()
print(json.dumps(asyncio.run(go())))
""").replace("GOOGLE_URL", repr(f"http://standins:{GOOGLE}")))
    expect("Traceback" not in out, f"the meetings could not be put on the calendar: {out[-500:]}")
    got = g_tool(s, "meeting_hours", {"company": "hours-co"}, "With hours-co")
    expect("2 meetings, 3 hours" in got, f"the meetings were not counted as two, three hours: {got[:500]}")


@check("gene.meeting-soon")
def meeting_soon(s: Stack) -> None:
    """An opened email whose sender is a guest of a meeting in three days gets the line naming it."""
    google(s)
    out = core_py(s, _owner_py("""
from datetime import datetime, timedelta
from rouh import meeting_soon, runtime, clock
async def go():
    cal = runtime.brief_google(who).calendar
    zone = clock.zone_of(who)
    start = (datetime.now(zone) + timedelta(days=3)).replace(hour=13, minute=0, second=0, microsecond=0)
    await cal.create("primary", title="Stack meeting soon", guests=["dana@soon-stack.test"],
                     start=start, minutes=30, notify=False)
    got = await meeting_soon.shown(who, cal, {"from": "Dana Stack <dana@soon-stack.test>", "to": "", "cc": ""},
                                   own=[])
    return {"said": [m["said"] for m in (got or {}).get("meetings", [])]}
print(json.dumps(asyncio.run(go())))
"""))
    expect("Stack meeting soon" in out and "You meet" in out, f"the meeting soon was not said: {out[-500:]}")


# --- Night 36: in their language; your word, by mail; promised to you by mail; if it does not come

@check("gene.their-language")
def their_language(s: Stack) -> None:
    """An English email to somebody whose own mail is in Bulgarian is held, with their language."""
    google(s)
    standin_post(s, GOOGLE, "/_deliver", {
        "from": "Ivan Stack <ivan@language-stack.test>", "quiet": True, "days_ago": 2, "subject": "Договорът",
        "text": "Здравей,\n\nЩе ти изпратя договора до петък, след като го прегледа и нашият юрист. "
                "Ако имаш въпроси, пиши ми.\n\nИван"})
    got = g_tool(s, "send_mail", {"to": "ivan@language-stack.test", "subject": "The contract",
                                  "body": "Hi Ivan,\n\nThe offer is fine with us, and we are happy to sign once your "
                                          "lawyer has read the contract. Please send it when it is ready.\n\nAlex"},
                 "Not sent yet")
    expect("Bulgarian" in got and "language_checked" in got, f"their language was not told: {got[:600]}")


@check("gene.my-word")
def my_word(s: Stack) -> None:
    """A promise the owner made by email, by a day now passed, with no email to them since, is found for the brief."""
    google(s)
    standin_post(s, GOOGLE, "/_deliver", {
        "sent": True, "to": "Owen Stack <owen@word-stack.test>", "days_ago": 4, "subject": "Order form",
        "text": "Hi Owen,\n\nI'll send you the signed order form by tomorrow.\n\nAlex"})
    out = core_py(s, _owner_py("""
from datetime import datetime
from rouh import clock, my_word
zone = clock.zone_of(who)
got = my_word.lines(asyncio.run(my_word.read_all(who, zone)), {}, zone, datetime.now(zone).date())
print(json.dumps([[one["to"], one["sentence"], one["when"]] for one in got], ensure_ascii=False))
"""))
    expect("signed order form by tomorrow" in out and "days ago" in out,
           f"the promise was not found: {out[-500:]}")


@check("gene.promised-to-you")
def promised_to_you(s: Stack) -> None:
    """promised_to_you finds what somebody promised by email by a day now passed, with nothing from them since."""
    google(s)
    standin_post(s, GOOGLE, "/_deliver", {
        "from": "Dana Stack <dana@promise-stack.test>", "quiet": True, "days_ago": 5, "subject": "Price list",
        "text": "Hi Alex,\n\nI'll have the new price list to you in 2 days.\n\nDana"})
    got = g_tool(s, "promised_to_you", {}, "Late, and nothing from them since")
    expect("I'll have the new price list to you in 2 days." in got, f"the promise was not found: {got[:600]}")


@check("gene.promise-watch")
def promise_watch(s: Stack) -> None:
    """If it does not come makes one reminder the morning after the promised day, naming the sender."""
    out = core_py(s, _owner_py("""
import time
from rouh import promise_watch, reminders
said = promise_watch.make(who, found={"id": "stack-w1", "from": "Rita Stack <rita@stack-client.test>",
                                      "subject": "Stack contract", "at": time.time(),
                                      "body": "Hi,\\n\\nI'll send you the signed contract in 3 days.\\n\\nRita"},
                          chat="", inbox="", read_only=False)
row = reminders.one(who, said["reminder"])
print(json.dumps({"said": said["said"], "title": row.title}))
"""))
    expect("Has it come? Rita Stack" in out and "09:00" in out, f"the look was not made: {out[-500:]}")


# --- Night 36 (8 November): got it on Telegram; gone quiet; reply times; also waiting on you

@check("gene.got-it")
def got_it(s: Stack) -> None:
    """A message written to the bot on the phone is marked 👀 on the phone."""
    tg, chat = 9014, 4242
    s.run("core", f"""python -c "import json,urllib.request; urllib.request.urlopen(urllib.request.Request(
'http://standins:{tg}/_send', data=json.dumps({{'chat_id': {chat}, 'text': 'Got it in the stack test'}}).encode(),
headers={{'content-type': 'application/json'}}), timeout=10)" """)
    end = time.time() + 120
    while time.time() < end:
        got = s.standin(tg, f"/_chat?chat={chat}")
        for m in (got.get("messages", []) if isinstance(got, dict) else []):
            if m.get("text") == "Got it in the stack test" and m.get("reactions"):
                expect("\U0001F440" in m["reactions"], f"the message was marked otherwise: {m['reactions']}")
                return
        time.sleep(3)
    raise Failed("the message written on the phone was not marked as taken")


@check("gene.gone-quiet")
def gone_quiet(s: Stack) -> None:
    """A company met every week until seven weeks ago, with nothing booked, is named for the brief."""
    google(s)
    out = core_py(s, _owner_py("""
from datetime import datetime, timedelta
from rouh import gone_quiet, runtime, clock
async def go():
    cal = runtime.brief_google(who).calendar
    zone = clock.zone_of(who)
    last = (datetime.now(zone) - timedelta(days=49)).replace(hour=10, minute=0, second=0, microsecond=0)
    for n in range(5):
        await cal.create("primary", title="Stack weekly", guests=["kai@quiet-stack.test"],
                         start=last - timedelta(days=7 * n), minutes=30, notify=False)
    got = await gone_quiet.found(who, runtime.brief_google)
    return {"said": [i["company"] + ": " + i["said"] for i in (got or {}).get("items", [])]}
print(json.dumps(asyncio.run(go())))
"""))
    expect("quiet-stack.test: You met every week" in out, f"the company gone quiet was not named: {out[-500:]}")


@check("gene.reply-times")
def reply_times(s: Stack) -> None:
    """reply_times counts a company's conversation and says it is still waiting on the owner."""
    google(s)
    standin_post(s, GOOGLE, "/_deliver", {
        "from": "Lea Stack <lea@reply-stack.test>", "quiet": True, "days_ago": 3,
        "subject": "Stack reply times", "text": "Could you look at the stack numbers?\n\nLea"})
    got = g_tool(s, "reply_times", {"who": "reply-stack.test"}, "Reply times with reply-stack.test")
    expect("Still waiting on you" in got and "Stack reply times" in got, f"the conversation was not counted: {got[:600]}")


@check("gene.waiting-too")
def waiting_too(s: Stack) -> None:
    """An opened email names the same sender's other email still waiting on the owner."""
    google(s)
    for subject in ("Stack waiting one", "Stack waiting two"):
        standin_post(s, GOOGLE, "/_deliver", {
            "from": "Ben Stack <ben@waiting-stack.test>", "quiet": True, "days_ago": 2,
            "subject": subject, "text": "Could you answer this one?\n\nBen"})
    out = core_py(s, _owner_py("""
from rouh import waiting_too
async def go():
    got = await waiting_too.shown(who, {"from": "Ben Stack <ben@waiting-stack.test>", "thread_id": "none",
                                        "subject": "Stack waiting one"}, own=[])
    return {"said": [o["said"] for o in (got or {}).get("others", [])]}
print(json.dumps(asyncio.run(go())))
"""))
    expect("is also waiting on you" in out and "Stack waiting two" in out and "Stack waiting one" not in out,
           f"the sender's other email was not named: {out[-500:]}")


# --- Night 37: their other questions; waiting on your answer, in the brief; between you and
# them; if I have not answered it, remind me

@check("gene.their-questions")
def their_questions(s: Stack) -> None:
    """An email to somebody whose other email asking the owner something is unanswered is held, with it."""
    google(s)
    standin_post(s, GOOGLE, "/_deliver", {
        "from": "Rosa Stack <rosa@questions-stack.test>", "quiet": True, "days_ago": 2, "subject": "Invoice",
        "text": "Hi Alex,\n\nCould you tell me which address to put on the invoice?\n\nRosa"})
    got = g_tool(s, "send_mail", {"to": "rosa@questions-stack.test", "subject": "Thursday",
                                  "body": "Hi Rosa,\n\nThursday at ten is fine for the call.\n\nAlex"},
                 "Not sent yet")
    expect("which address to put on the invoice" in got and "asks_checked" in got,
           f"their other question was not told: {got[:600]}")


@check("gene.answer-waiting")
def answer_waiting(s: Stack) -> None:
    """An email from a person asking the owner something, two days old and unanswered, is found for the brief."""
    google(s)
    standin_post(s, GOOGLE, "/_deliver", {
        "from": "Paula Stack <paula@answer-stack.test>", "quiet": True, "days_ago": 2, "subject": "The venue",
        "text": "Hi Alex,\n\nCould you confirm the venue for the workshop by Friday?\n\nPaula"})
    out = core_py(s, _owner_py("""
from rouh import answer_waiting, clock
got = answer_waiting.lines(asyncio.run(answer_waiting.read_all(who)), {}, clock.zone_of(who))
print(json.dumps([[one["name"], one["ask"], one["waited"]] for one in got], ensure_ascii=False))
"""))
    expect("Could you confirm the venue" in out, f"the email waiting on an answer was not found: {out[-500:]}")


@check("gene.between-us")
def between_us(s: Stack) -> None:
    """between_us says what one person asked, unanswered, and what they promised, from their own email."""
    google(s)
    standin_post(s, GOOGLE, "/_deliver", {
        "from": "Viktor Stack <viktor@between-stack.test>", "quiet": True, "days_ago": 3, "subject": "Draft plan",
        "text": "Hi Alex,\n\nI'll send you the draft plan in 2 days. Can you check the budget line?\n\nViktor"})
    got = g_tool(s, "between_us", {"person": "viktor@between-stack.test"}, "They promised the person")
    expect("check the budget line" in got and "draft plan" in got, f"what is open was not said: {got[:600]}")


@check("gene.answer-watch")
def answer_watch(s: Stack) -> None:
    """If I have not answered it, remind me makes one reminder at 09:00 on the next working morning."""
    out = core_py(s, _owner_py("""
import time
from rouh import answer_watch, reminders
said = answer_watch.make(who, found={"id": "stack-a1", "from": "Lena Stack <lena@stack-client.test>",
                                     "to": "alex@example.test", "subject": "Stack offer", "at": time.time(),
                                     "body": "Hi,\\n\\nCould you send me your comments on the offer?\\n\\nLena"},
                         own=["alex@example.test"], chat="", inbox="", read_only=False)
row = reminders.one(who, said["reminder"])
print(json.dumps({"said": said["said"], "title": row.title}))
"""))
    expect("Answered? Lena Stack" in out and "09:00" in out, f"the look was not made: {out[-500:]}")


# --- Night 38 (9 November): not put on twice; away, after Rouh wrote; contacts with no company;
# how you know them

@check("gene.not-twice")
def not_twice(s: Stack) -> None:
    """The same event asked for twice is booked once: the second time says where it already is."""
    google(s)
    args = {"title": "Stack pricing call", "start": "2030-03-05T10:00", "minutes": 30}
    first = g_tool(s, "create_calendar_event", args, "Put 'Stack pricing call'")
    expect("already on the calendar" not in first, f"the first booking was held: {first[:400]}")
    g_tool(s, "create_calendar_event", dict(args, title="Pricing call (stack)", start="2030-03-05T10:15"),
           "already on the calendar")


@check("gene.away-after")
def away_after(s: Stack) -> None:
    """An out-of-office reply to Rouh's email is told in a notice: until when, and whom to write to."""
    out = core_py(s, _owner_py("""
from rouh import away_after
async def go():
    return await away_after.seen(who, {
        "id": "stack-away-1", "thread_id": "stack-away-t", "from": "Ana Stack <ana@away-stack.test>",
        "subject": "Automatic reply: Stack plan", "auto_submitted": "auto-replied",
        "body": "I am out of the office until Monday 16 November. For anything urgent please contact "
                "Ivo Stack (ivo@away-stack.test)."}, mailbox="rouh@example.test")
print(json.dumps({"said": asyncio.run(go())}))
"""))
    expect("Ana Stack is away" in out and "until Monday 16 November" in out and "notice" in out,
           f"the away reply was not told: {out[-500:]}")


@check("gene.no-company")
def no_company(s: Stack) -> None:
    """no_company reads every contact and says how many have no company, or that there are none to read."""
    got = s.tool("no_company", {})
    expect(("have no company" in got or "has a company" in got or "no contacts to read" in got)
           and "switched off" not in got, f"no_company did not read the contacts: {got[:500]}")


@check("gene.know-them")
def know_them(s: Stack) -> None:
    """An email from somebody last written with eight months ago says when, and their first email."""
    google(s)
    for days, subject in ((400, "Stack first hello"), (240, "Stack last word")):
        standin_post(s, GOOGLE, "/_deliver", {
            "from": "Mo Stack <mo@know-stack.test>", "quiet": True, "read": True, "days_ago": days,
            "subject": subject, "text": "Hello Alex,\n\nMo"})
    out = core_py(s, _owner_py("""
from rouh import know_them
async def go():
    got = await know_them.shown(who, {"from": "Mo Stack <mo@know-stack.test>", "thread_id": "none"}, own=[])
    return {"said": (got or {}).get("said", "")}
print(json.dumps(asyncio.run(go())))
"""))
    expect("last wrote with you" in out and "Stack last word" in out and "Stack first hello" in out,
           f"how you know them was not said: {out[-500:]}")


# --- Night 39 (10 November): not sent twice; a new number in their signature; contacts kept twice;
# save them as a contact

@check("gene.sent-twice")
def sent_twice(s: Stack) -> None:
    """The same email sent twice to the same person goes once: the second time says it already went."""
    google(s)
    args = {"to": "Pat Stack <pat@twice-stack.test>", "subject": "Stack seat numbers",
            "body": "Hi Pat,\n\nNine seats from 1 December.\n\nAlex"}
    first = g_tool(s, "send_mail", args, "Sent to")
    expect("already went" not in first, f"the first email was held: {first[:400]}")
    g_tool(s, "send_mail", args, "already went")


@check("gene.new-number")
def new_number(s: Stack) -> None:
    """A signature's mobile that the contact lacks is found; a number on the contact is not."""
    out = core_py(s, _owner_py("""
from rouh import new_number
card = {"id": "c1", "phones": [{"number": "+44 20 7946 0000"}], "emails": [{"address": "nina@sig-stack.test"}]}
body = "Hi,\\n\\nSee you.\\n\\nNina Stack\\nM: +359 89 555 0101\\nT: +44 20 7946 0000\\nVAT: BG204411223"
print(json.dumps({"missing": new_number.missing(card, body)}))
"""))
    expect("+359 89 555 0101" in out and "7946" not in out and "204411223" not in out,
           f"the signature's new number was not found alone: {out[-500:]}")


@check("gene.same-contact")
def same_contact(s: Stack) -> None:
    """same_contact reads every contact and says who is there twice, or that nobody is."""
    got = s.tool("same_contact", {})
    expect(("more than once" in got or "No one is in the contacts twice" in got or "no contacts to read" in got)
           and "switched off" not in got, f"same_contact did not read the contacts: {got[:500]}")


@check("gene.save-sender")
def save_sender(s: Stack) -> None:
    """A sender on no contact gets the card that would be saved, with the company and the signature's number."""
    out = core_py(s, _owner_py("""
from rouh import save_sender
cards = [{"id": "c1", "name": "Dana Stack", "organisation": "Northwind", "emails": [{"address": "dana@northwind-stack.test"}]}]
found = {"from": "Kai Stack <kai@northwind-stack.test>", "subject": "Hello",
         "body": "Hi,\\n\\nKai Stack\\nMobile: +386 41 555 222"}
print(json.dumps(save_sender.card_for(found, cards, [])))
"""))
    expect("Kai Stack" in out and "Northwind" in out and "+386 41 555 222" in out,
           f"the card to save was not made: {out[-500:]}")



# --- Night 40 (11 November): not drafted twice; a new address for a contact; their card to pass on;
# a contact card in an email

@check("gene.draft-twice")
def draft_twice(s: Stack) -> None:
    """The same draft asked for twice is made once: the second time gives the draft already there."""
    google(s)
    args = {"to": "Pat Stack <pat@draft-stack.test>", "subject": "Stack rollout dates",
            "body": "Hi Pat,\n\nThe rollout starts on 1 December.\n\nAlex"}
    first = g_tool(s, "draft_mail", args, "Drafted to")
    expect("Not drafted again" not in first, f"the first draft was held: {first[:400]}")
    g_tool(s, "draft_mail", args, "Not drafted again")


@check("gene.new-address")
def new_address(s: Stack) -> None:
    """A contact's name at an address on none of their cards is matched to that one card; a known address,
    a one-word name and a name on two cards are not."""
    out = core_py(s, _owner_py("""
from rouh import new_address
cards = [{"id": "c1", "name": "Dana Stack", "emails": [{"address": "dana@old-stack.test"}]},
         {"id": "c2", "name": "Chris Twin", "emails": []}, {"id": "c3", "name": "Twin Chris", "emails": []}]
print(json.dumps({"new": (new_address.match(cards, "Stack, Dana", "dana@new-stack.test") or {}).get("id"),
                  "known": new_address.match(cards, "Dana Stack", "dana@old-stack.test"),
                  "one_word": new_address.match(cards, "Dana", "dana@new-stack.test"),
                  "two": new_address.match(cards, "Chris Twin", "chris@twin-stack.test")}))
"""))
    expect('"new": "c1"' in out and '"known": null' in out and '"one_word": null' in out and '"two": null' in out,
           f"the contact at a new address was not matched alone: {out[-500:]}")


@check("gene.contact-card")
def contact_card(s: Stack) -> None:
    """A contact's card file keeps the name, numbers and addresses, and leaves the notes and birthday out."""
    out = core_py(s, _owner_py("""
from rouh import contact_card
v = "\\r\\n".join(["BEGIN:VCARD", "VERSION:3.0", "FN:Dana Stack", "TEL;type=CELL:+44 7700 900 123",
                   "EMAIL:dana@card-stack.test", "NOTE:private 8001011234", "BDAY:1980-01-01", "END:VCARD", ""])
text, left = contact_card.card_text({"id": "c1", "name": "Dana Stack", "vcard": v})
print(json.dumps({"text": text, "left": left}))
"""))
    expect("+44 7700 900 123" in out and "dana@card-stack.test" in out and "8001011234" not in out
           and "BDAY" not in out and "the notes" in out, f"the card file was not made as it should be: {out[-500:]}")


@check("gene.card-in-mail")
def card_in_mail(s: Stack) -> None:
    """A card file on an email is read, and somebody new is offered as a new contact, somebody known as the
    numbers their contact lacks."""
    out = core_py(s, _owner_py("""
from rouh import card_in_mail
v = "\\r\\n".join(["BEGIN:VCARD", "VERSION:3.0", "FN:Sam Stack", "ORG:Lumen;", "TEL;type=CELL:+386 41 555 333",
                   "EMAIL:sam@card-stack.test", "END:VCARD", ""]).encode()
person = card_in_mail.person_of(v)
known = [{"id": "c1", "name": "Sam Stack", "phones": [], "emails": [{"address": "sam@card-stack.test"}]}]
print(json.dumps({"new": card_in_mail.line([], person), "known": card_in_mail.line(known, person)}))
"""))
    expect("Save Sam Stack to contacts" in out and "Add to Sam Stack's contact" in out and "+386 41 555 333" in out,
           f"the card on the email was not read: {out[-500:]}")


# --- Night 41 (12 November): not forwarded twice; a new company in their signature; what changed on a
# contact; call them from their email

@check("gene.forward-twice")
def forward_twice(s: Stack) -> None:
    """A sent forward of the same email to the same people is found; another person, another subject or a
    plain email is not."""
    out = core_py(s, _owner_py("""
from rouh import forward_twice
original = {"from": "Nina Stack <nina@fwd-stack.test>", "subject": "Seat plan"}
sent = {"to": "pat@fwd-stack.test", "subject": "Fwd: Seat plan",
        "body": "---------- Forwarded message ---------\\nFrom: Nina Stack <nina@fwd-stack.test>\\nSubject: Seat plan"}
print(json.dumps({"same": forward_twice.same_forward(sent, to={"pat@fwd-stack.test"}, original=original),
                  "other": forward_twice.same_forward(sent, to={"lee@fwd-stack.test"}, original=original),
                  "plain": forward_twice.same_forward(dict(sent, body="Seat plan attached"),
                                                      to={"pat@fwd-stack.test"}, original=original)}))
"""))
    expect('"same": true' in out and '"other": false' in out and '"plain": false' in out,
           f"the same forward was not found as it should be: {out[-500:]}")


@check("gene.new-company")
def new_company(s: Stack) -> None:
    """The company under a sender's name in a signature is read, and the same company written another way
    is the same."""
    out = core_py(s, _owner_py("""
from rouh import new_company
body = "Thanks,\\n\\nNina Stack\\nHead of Operations, Northwind Ltd\\nM: +44 7700 900123\\n"
print(json.dumps({"got": new_company.company_in(body, "Nina Stack"),
                  "same": new_company.same_company("Northwind Ltd", "Northwind"),
                  "other": new_company.same_company("Brightline", "Northwind")}))
"""))
    expect('"Head of Operations", "Northwind Ltd"' in out and '"same": true' in out and '"other": false' in out,
           f"the signature's company was not read: {out[-500:]}")


@check("gene.contact-changes")
def contact_changes(s: Stack) -> None:
    """Two versions of a contact are told apart: a number taken off and another added, a company changed."""
    out = core_py(s, _owner_py("""
from rouh import contact_changes
a = contact_changes.state_of({"name": "Dana Stack", "organisation": "Brightline",
                              "icloud": {"phones": [{"number": "+44 20 7946 0000"}], "emails": []}})
b = contact_changes.state_of({"name": "Dana Stack", "organisation": "Northwind",
                              "icloud": {"phones": [{"number": "+359 88 765 4321", "label": "mobile"}], "emails": []}})
print(json.dumps(contact_changes.differences(a, b), ensure_ascii=False))
"""))
    expect("company Brightline → Northwind" in out and "+359 88 765 4321 (mobile) added" in out
           and "+44 20 7946 0000 taken off" in out, f"the change was not said: {out[-500:]}")


@check("gene.call-sender")
def call_sender(s: Stack) -> None:
    """A contact's numbers are offered mobile first, each as a tel: link."""
    out = core_py(s, _owner_py("""
from rouh import call_sender
card = {"phones": [{"number": "+44 20 7946 0000", "label": "work"}, {"number": "+359 88 765 4321", "label": "mobile"}]}
print(json.dumps(call_sender.numbers_of(card)))
"""))
    expect(out.find("+359887654321") != -1 and out.find("mobile") < out.find("work"),
           f"the numbers were not offered mobile first: {out[-500:]}")
