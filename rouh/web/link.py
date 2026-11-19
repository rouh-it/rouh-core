"""Rouh Link's addresses (`rouh/link/`, task 189).

Open to everybody, because other Rouhs and other agents are not signed in here; each checks what it
is handed itself:

    GET  /.well-known/agent-card.json   the Rouh card (A2A agent card), signed
    GET  /.well-known/agent.json        the same, at A2A's older address
    POST /link/in                       another Rouh's locked envelope; answered with one
    GET  /link/join/<secret>            a connect link opened in a browser: says what it is
    POST /link/a2a                      another maker's A2A agent (phase 5; off by a setting)

Signed in, the person's own:

    GET  /link                          Connections: Rouhs, links, requests, live spaces
    GET  /link/accept?link=...          bring someone's connect link to your own Rouh
    GET  /link/space/<id>               a live shared space
    /api/link/...                       what those pages ask
"""
from __future__ import annotations

import asyncio
import json
import logging
import time

from asgiref.sync import sync_to_async
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt

from .common import answer, body_of, only, refuse, who

log = logging.getLogger("rouh.link")
NO_STORE = {"Cache-Control": "no-store"}


def _org_for_request(request: HttpRequest) -> str | None:
    from rouh.link import me as _me

    host = (request.headers.get("host") or "").split(":")[0].lower()
    label = host.split(".")[0] if host.count(".") >= 2 else ""
    if label:
        org = _me.org_for_label(label)
        if org:
            return org
    return _me.only_org()


# --- open to everybody --------------------------------------------------------------------------------


@only("GET")
async def agent_card(request: HttpRequest):
    from rouh.link import card

    org = await sync_to_async(_org_for_request)(request)
    if org is None:
        return refuse("There is no born Rouh here.", 404)
    try:
        doc = await sync_to_async(card.build)(org)
    except Exception as exc:  # noqa: BLE001
        log.info("no card: %s", exc)
        return refuse("There is no born Rouh here.", 404)
    return answer(doc, headers={"Cache-Control": "max-age=60", "Access-Control-Allow-Origin": "*"})


@csrf_exempt
@only("POST")
async def inbox(request: HttpRequest):
    """Another Rouh's envelope. Its words never reach a model; see `rouh/link/wire.py`."""
    from rouh.link import limits, seal, wire

    if len(request.body or b"") > seal.MAX_BYTES * 2:
        return refuse("Too big.", 413)
    try:
        env = json.loads(request.body or b"null")
    except ValueError:
        return refuse("Not a Rouh Link envelope.", 400)
    try:
        got = await wire.receive(env)
    except limits.No as exc:
        return refuse(str(exc), 403)
    except seal.Refused as exc:
        return refuse(str(exc), 400)
    except LookupError as exc:
        return refuse(str(exc), 404)
    except Exception as exc:  # noqa: BLE001 - said plainly, never the trace
        from rouh.link import forms

        if isinstance(exc, forms.Refused):
            return refuse(f"That did not fit its form: {exc}", 400)
        log.exception("the link inbox failed")
        return refuse("This Rouh could not take that in.", 500)
    return answer(got, headers=NO_STORE)


@only("GET")
async def join_page(request: HttpRequest, token: str):
    from rouh.link import me as _me

    org = await sync_to_async(_org_for_request)(request)
    name = ""
    if org is not None:
        try:
            mine = await sync_to_async(_me.me)(org)
            name = mine.tagged
        except Exception:  # noqa: BLE001
            name = ""
    # Never moved to another name (Petar, 19 November 2026): the page answers on whichever of this
    # Rouh's names it was opened on, a link sent on a chosen name keeps opening while that name is
    # answered, and the link it hands on to the visitor's own Rouh is always the born-name one.
    from rouh.link import peers

    here = request.build_absolute_uri("/").rstrip("/")
    link = (await sync_to_async(peers.join_base)(here)) + request.path
    names, where_owner = await sync_to_async(_names_and_owner_home)(request)
    if not name:
        return render(request, "rouh/link_join.html", {"name": "", "link": link}, status=404)
    own = await _own_link(request, org, token)
    if own is not None:
        # Its own person, signed in here: never a box asking for their own address, and never a way
        # to connect this Rouh to itself. What the link is, and what they can do with it.
        response = render(request, "rouh/link_join.html", {"name": name, "link": link, "own": own})
        response["Cache-Control"] = "no-store, private"
        return response
    from urllib.parse import urlencode

    from rouh import birth

    # Somebody else's browser. rouh.land knows which Rouh is theirs when they are signed in there, and
    # sends them on to it (rouh-land `birth/connect.py`); it tells this page nothing about them.
    land = birth.defaults()[0].rstrip("/") + "/connect/?" + urlencode({"link": link})
    domain = await sync_to_async(_relay_domain)()
    return render(request, "rouh/link_join.html", {
        "name": name, "link": link, "land": land, "domain": domain, "owner_home": where_owner,
        "js": {"domain": domain, "own": names, "link": link}})


def _relay_domain() -> str:
    """The relay's domain, which a bare Rouh name typed on the page is put on: rouh.page, or the one
    this Rouh's own born name is on."""
    from rouh import relay

    try:
        born = relay.hostname().lower()
    except Exception:  # noqa: BLE001
        born = ""
    return born.split(".", 1)[1] if born.count(".") >= 2 else "rouh.page"


def urlsplit_host(url: str) -> str:
    from urllib.parse import urlsplit

    return (urlsplit(url).hostname or "").lower()


def _names_and_owner_home(request: HttpRequest) -> tuple[list[str], str]:
    """Every name this Rouh answers on (born, chosen, and the one this page came in on), and, when its
    person signs in on another name than this one, this page there: their session lives on the name
    they sign in on, so their own-link view is one press away, and nobody else is moved."""
    from rouh import relay

    asked = request.get_host().lower()
    try:
        names = [n.lower() for n in relay.hostnames()]
        preferred = relay.preferred_address()
    except Exception:  # noqa: BLE001 - no relay state: only the name it came in on
        names, preferred = [], ""
    names = list(dict.fromkeys(names + [asked, asked.split(":")[0]]))
    home = ""
    if preferred and urlsplit_host(preferred) != asked.split(":")[0]:
        home = preferred.rstrip("/") + request.path
    return names, home


async def _own_link(request: HttpRequest, org: str | None, token: str) -> dict | None:
    """The connect link as this Rouh's own person sees it, when they are the one signed in here;
    None for anybody else (nobody signed in, a guest, or somebody of another organisation)."""
    from rouh.link import peers

    if org is None:
        return None
    try:
        user = await request.auser()
    except Exception:  # noqa: BLE001 - no session to read: not its person
        return None
    if getattr(user, "is_guest", False):
        return None
    me = await sync_to_async(who)(request)
    if me is None or str(me.org_id) != str(org):
        return None
    found = await sync_to_async(peers.invite_for_token)(str(org), token)
    if found is None:
        return {"state": "unknown"}
    day = lambda t: time.strftime("%-d %B %Y", time.gmtime(t)) if t else ""  # noqa: E731
    found.update(expires_day=day(found["expires_at"]), used_day=day(found["used_at"]),
                 withdrawn_day=day(found["withdrawn_at"]),
                 days=max(1, round((found["expires_at"] - found["created_at"]) / 86400)))
    return found


@csrf_exempt
@only("POST")
async def a2a(request: HttpRequest):
    from rouh.link import open_network

    return await open_network.a2a_endpoint(request)


# --- the person's pages ------------------------------------------------------------------------------


async def _me_or_none(request):
    return await sync_to_async(who)(request)


@only("GET")
async def connections_page(request: HttpRequest):
    me = await _me_or_none(request)
    if me is None:
        return HttpResponse(status=401)
    return render(request, "rouh/link_connections.html", {})


@only("GET")
async def accept_page(request: HttpRequest):
    me = await _me_or_none(request)
    if me is None:
        return HttpResponse(status=401)
    return render(request, "rouh/link_connections.html", {"accept_link": str(request.GET.get("link") or "")[:400]})


@only("GET")
async def space_page(request: HttpRequest, sid: str):
    me = await _me_or_none(request)
    if me is None:
        return HttpResponse(status=401)
    from rouh.link import spaces

    row = await sync_to_async(spaces._row)(str(me.org_id), sid[:40])
    if row is not None and row.kind == "html":
        # A Live page (step 189-08): the page drawn live in a sealed frame, beside its source.
        return render(request, "rouh/link_livepage.html", {"space_id": sid[:40]})
    return render(request, "rouh/link_space.html", {"space_id": sid[:40]})


# --- the person's API ---------------------------------------------------------------------------------


def _problem(exc) -> HttpResponse:
    from rouh.link import forms, limits, me as _me, peers, wire

    if isinstance(exc, (peers.Problem, limits.No, forms.Refused, _me.NotBorn)):
        return refuse(str(exc), 400)
    if isinstance(exc, wire.Refusal):
        return refuse(f"The other Rouh said: {exc.said}", 400)
    if isinstance(exc, wire.Unreachable):
        return refuse("The other Rouh did not answer; it may be off. Try again later.", 503)
    if isinstance(exc, LookupError):
        return refuse(str(exc), 404)
    log.exception("a link request failed")
    return refuse("That did not work. It is written down.", 500)


async def _guard(request, fn):
    me = await _me_or_none(request)
    if me is None:
        return refuse("sign in", 401)
    try:
        got = await fn(me, body_of(request) if request.method == "POST" else {})
    except Exception as exc:  # noqa: BLE001
        return _problem(exc)
    return answer(got, headers=NO_STORE)


async def _state(me) -> dict:
    from rouh.link import card as _card
    from rouh.link import me as _me
    from rouh.link import grants as _grants
    from rouh.link import handoff as _handoff
    from rouh.link import peers, spaces, trust

    org = str(me.org_id)
    born = await sync_to_async(_me.born)(org)
    out = {"born": born, "levels": [{"id": k, "word": trust.WORDS[k], "says": trust.SAYS[k]} for k in trust.LEVELS]}
    if not born:
        return out
    who_ = await sync_to_async(_me.me)(org)
    out.update({
        "me": {"name": who_.tagged, "label": who_.label, "address": who_.address,
               "card": who_.address + _card.WELL_KNOWN if who_.address else ""},
        "settings": await sync_to_async(_me.settings)(org),
        "peers": await sync_to_async(peers.listing)(org),
        "invites": await sync_to_async(peers.invites)(org),
        "spaces": await sync_to_async(spaces.listing)(org),
        "grants": await sync_to_async(_grants.listing)(org),
        "handoffs": await sync_to_async(_handoff.listing)(org),
    })
    return out


@only("GET")
async def api_state(request):
    return await _guard(request, lambda me, b: _state(me))


@only("POST")
async def api_invite(request):
    from rouh.link import peers

    async def go(me, b):
        return await sync_to_async(peers.invite)(str(me.org_id), trust_level=str(b.get("trust") or "known"),
                                                 silo=str(b.get("silo") or ""), for_label=str(b.get("for_label") or ""),
                                                 note=str(b.get("note") or ""))
    return await _guard(request, go)


@only("POST")
async def api_invite_withdraw(request):
    from rouh.link import peers

    async def go(me, b):
        await sync_to_async(peers.withdraw_invite)(str(me.org_id), int(b.get("id") or 0))
        return {"ok": True}
    return await _guard(request, go)


@only("POST")
async def api_accept(request):
    from rouh.link import peers

    async def go(me, b):
        return await peers.accept(str(me.org_id), str(b.get("link") or ""), trust_level=str(b.get("trust") or "known"),
                                  silo=str(b.get("silo") or ""), contact_id=str(b.get("contact_id") or ""))
    return await _guard(request, go)


@only("POST")
async def api_connect(request):
    from rouh.link import peers

    async def go(me, b):
        return await peers.connect_address(str(me.org_id), str(b.get("address") or ""),
                                           trust_level=str(b.get("trust") or "known"), silo=str(b.get("silo") or ""),
                                           contact_id=str(b.get("contact_id") or ""))
    return await _guard(request, go)


@only("POST")
async def api_peer(request, label: str):
    """One press on a connection: trust, side, cut, block, unblock, say yes to a request."""
    from rouh.link import peers

    async def go(me, b):
        org, act = str(me.org_id), str(b.get("act") or "")
        if act == "trust":
            return await sync_to_async(peers.set_trust)(org, label, str(b.get("level") or "known"))
        if act == "silo":
            return await sync_to_async(peers.set_silo)(org, label, str(b.get("silo") or ""))
        if act == "cut":
            return await sync_to_async(peers.cut)(org, label)
        if act == "block":
            return await sync_to_async(peers.cut)(org, label, block=True)
        if act == "unblock":
            return await sync_to_async(peers.unblock)(org, label)
        if act == "yes":
            return await sync_to_async(peers.accept_request)(org, label, str(b.get("level") or "known"),
                                                             str(b.get("silo") or ""))
        if act == "contact":
            return await sync_to_async(peers.link_contact)(org, label, str(b.get("contact_id") or ""))
        raise peers.Problem("What should happen to that connection?")
    return await _guard(request, go)


@only("GET")
async def api_peer_log(request, label: str):
    from rouh.link import log as _log
    from rouh.link import peers

    async def go(me, b):
        org = str(me.org_id)
        mine = await sync_to_async(_log.entries)(org, peer=label, most=200)
        try:
            theirs = await peers.their_log(org, label)
            said = ""
        except Exception as exc:  # noqa: BLE001
            theirs, said = [], f"Their side could not be read now ({type(exc).__name__})."
        return {"mine": mine, "theirs": theirs, "theirs_said": said}
    return await _guard(request, go)


@only("POST")
async def api_grant(request):
    """Write a grant to a delegate, or withdraw one: {"act": "give"|"withdraw", ...}."""
    from rouh.link import grants

    async def go(me, b):
        org = str(me.org_id)
        if b.get("act") == "withdraw":
            return await sync_to_async(grants.withdraw)(org, str(b.get("grant_id") or ""))
        return await sync_to_async(grants.give)(org, str(b.get("label") or ""), what=str(b.get("what") or "meetings"),
                                                given_limits=b.get("limits") if isinstance(b.get("limits"), dict) else None,
                                                days=int(b.get("days") or 90))
    return await _guard(request, go)


@only("POST")
async def api_handoff(request):
    """A brief to a connection, a quote back on a brief, or no: {"act": "brief"|"quote"|"decline", ...}."""
    from rouh.link import handoff

    async def go(me, b):
        org, act = str(me.org_id), str(b.get("act") or "")
        if act == "brief":
            return await sync_to_async(handoff.send_brief)(org, str(b.get("label") or ""), str(b.get("need") or ""),
                                                           str(b.get("by_when") or ""), str(b.get("budget_band") or "ask"))
        if act == "quote":
            return await sync_to_async(handoff.send_quote)(org, str(b.get("brief_id") or ""), float(b.get("amount") or 0),
                                                           str(b.get("currency") or "EUR"), str(b.get("words") or ""))
        if act == "decline":
            return await sync_to_async(handoff.decline)(org, str(b.get("id") or ""))
        if act == "money":
            return await sync_to_async(handoff.send_money)(org, str(b.get("label") or ""), float(b.get("amount") or 0),
                                                           str(b.get("currency") or "EUR"), str(b.get("for") or ""))
        from rouh.link import peers

        raise peers.Problem("What should happen to that hand-off?")
    return await _guard(request, go)


async def money_page(request: HttpRequest, hid: str):
    """A money proposal from another Rouh, on a page with no AI on it: the person reads it and, only
    if they want to, presses I agree. Nothing is paid, here or anywhere in Rouh Link."""
    from rouh.link import handoff

    me = await _me_or_none(request)
    if me is None:
        return HttpResponse(status=401)
    row = await sync_to_async(handoff.one)(str(me.org_id), hid[:120])
    if row is None or row.kind != "money.proposal":
        return HttpResponse("There is no such proposal.", status=404, content_type="text/plain")
    said = ""
    if request.method == "POST":
        await sync_to_async(handoff.agree_money)(str(me.org_id), row.msg_id, f"account {me.user_id}")
        row = await sync_to_async(handoff.one)(str(me.org_id), hid[:120])
        said = "You agreed. Nothing was paid: paying, if you want to, is yours to do."
    f = (row.envelope or {}).get("form") or {}
    from rouh.link import peers

    p = await sync_to_async(peers.peer_row)(str(me.org_id), row.peer_label)
    return render(request, "rouh/link_money.html", {"f": f, "row": row, "said": said,
                                                    "peer": p.name if p is not None else row.peer_label})


@only("POST")
async def api_settings(request):
    from rouh.link import me as _me

    async def go(me, b):
        if not getattr(me, "is_admin", False):
            from rouh.link import peers

            raise peers.Problem("Only an administrator of this Rouh changes these.")
        try:
            if "findable_by_email" in b:
                from rouh.link import open_network

                await sync_to_async(open_network.set_findable)(str(me.org_id), bool(b["findable_by_email"]))
            if "most_members" in b:
                b["most_members"] = max(2, min(50, int(b.get("most_members") or 5)))
            chose = [k for k in ("book_calendar_work", "book_calendar_personal") if k in b]
            for k in chose:
                b[k] = str(b.get(k) or "").strip()[:300]
                if b[k]:
                    from rouh.link import meeting

                    got = await meeting.writable_calendars(str(me.org_id))
                    one = next((c for c in got.get("calendars") or [] if c["id"] == b[k]), None)
                    if one is None:
                        raise ValueError("That calendar is not one this Rouh can put meetings in.")
                    side = k.rsplit("_", 1)[1]
                    if one.get("side") and one["side"] not in (side, "*"):
                        raise ValueError(f"{one['name']} is on the {meeting._side_words(one['side'])} side, so "
                                         f"{meeting._side_words(side)} meetings do not go in it.")
            kept = await sync_to_async(_me.set_settings)(str(me.org_id), **{k: v for k, v in b.items() if k in _me.DEFAULTS})
            if chose:
                from rouh.link import meeting

                asyncio.ensure_future(meeting.book_waiting(str(me.org_id)))
            return kept
        except ValueError as exc:
            from rouh.link import peers

            raise peers.Problem(str(exc)) from None
    return await _guard(request, go)


@only("GET")
async def api_calendars(request):
    """The calendars Connections offers for agreed meetings, one choice per side: the owner's
    calendars this Rouh may write to (owner or writer), each with its side by the silo rules."""
    from rouh.link import meeting

    async def go(me, b):
        if not getattr(me, "is_admin", False):
            return {"connected": False, "calendars": [], "fallback": {}, "admin": False}
        return await meeting.writable_calendars(str(me.org_id))
    return await _guard(request, go)


@only("POST")
async def api_contact(request):
    """A contact's "their Rouh" line: note it, and connect when asked."""
    from rouh.link import peers

    async def go(me, b):
        org = str(me.org_id)
        address = str(b.get("address") or "")
        try:
            label = await peers.label_at(peers.normal_address(address))
        except peers.Problem:
            label = ""
        row = await sync_to_async(peers.note_contact)(org, str(b.get("contact_id") or ""), address, label)
        if b.get("connect"):
            return await peers.connect_address(org, row["address"], contact_id=str(b.get("contact_id") or ""))
        return row
    return await _guard(request, go)


@only("POST")
async def api_find(request):
    """Find a Rouh by one exact email through rouh.land (the open network; off unless turned on)."""
    from rouh.link import open_network

    async def go(me, b):
        return await open_network.find(str(me.org_id), str(b.get("email") or ""))
    return await _guard(request, go)


@only("GET")
async def api_contact_line(request, contact_id: str):
    from rouh.link import peers

    async def go(me, b):
        return {"line": await sync_to_async(peers.contact_line)(str(me.org_id), contact_id)}
    return await _guard(request, go)


# --- spaces -------------------------------------------------------------------------------------------


def _task_seed(me, source: str) -> dict:
    """A task's title and steps, to start a live task page from (its folder, as the task page knows it)."""
    import re

    from rouh import taskmeta

    folder = source.strip("/").split("/")[-1]
    m = re.match(r"^(\d+)[.-](.*)$", folder)
    words = (m.group(2) if m else folder).replace("-", " ").strip()
    title = (f"{m.group(1)}. " if m else "") + (words[:1].upper() + words[1:])
    steps = []
    try:
        meta = taskmeta.read(source) or {}
    except Exception:  # noqa: BLE001 - a task with no meta starts with no steps
        meta = {}
    for _k, st in list((meta.get("steps") or {}).items())[:30]:
        if isinstance(st, dict) and st.get("title"):
            steps.append(str(st["title"])[:300])
    return {"title": title[:200], "steps": steps, "notes": ""}


@only("POST")
async def api_space_new(request):
    from rouh.link import spaces

    async def go(me, b):
        org = str(me.org_id)
        title = " ".join(str(b.get("title") or "").split())[:200]
        source = str(b.get("source") or "")[:300]
        if str(b.get("kind") or "") == "html":
            # A Live page: from a page in the workspace, a card's drawn page, pasted HTML or a blank page.
            from rouh.link import pagein

            made = await sync_to_async(pagein.start)(org, me, source=source, html=str(b.get("html") or ""),
                                                     card=str(b.get("card") or "")[:80], title=title,
                                                     silo=str(b.get("silo") or ""))
            for label in (b.get("invite") or [])[:5]:
                await sync_to_async(spaces.invite)(org, made["space_id"], str(label), str(b.get("role") or "editor"))
            return made
        steps = [str(s)[:300] for s in (b.get("steps") or []) if str(s).strip()][:60]
        notes = str(b.get("notes") or "")[:4000]
        if source and not title:
            seed = await sync_to_async(_task_seed)(me, source)
            title, steps, notes = seed["title"], steps or seed["steps"], notes or seed["notes"]
        if not title:
            from rouh.link import peers

            raise peers.Problem("Give the space a title.")
        sid = await sync_to_async(spaces.create)(org, kind=str(b.get("kind") or "task"), title=title, source=source,
                                                 silo=str(b.get("silo") or ""), steps=steps, notes=notes)
        for label in (b.get("invite") or [])[:5]:
            await sync_to_async(spaces.invite)(org, sid, str(label), str(b.get("role") or "editor"))
        return {"space_id": sid, "url": f"/link/space/{sid}"}
    return await _guard(request, go)


def _int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


@only("GET")
async def api_space(request, sid: str):
    from rouh.link import spaces

    async def go(me, b):
        since = int(request.GET.get("since") or -1)
        wait = min(25.0, max(0.0, float(request.GET.get("wait") or 0)))
        return await spaces.page_state(str(me.org_id), sid, since=since, wait=wait,
                                       part=str(request.GET.get("part") or "")[:120],
                                       follow=str(request.GET.get("follow") or "")[:120],
                                       watching=request.GET.get("watching", "1") != "0",
                                       hv=_int(request.GET.get("hv"), -1))
    return await _guard(request, go)


@only("POST")
async def api_space_ops(request, sid: str):
    """The person's own changes: each made as this Rouh's person, whatever the page said."""
    from rouh.link import doc as _doc
    from rouh.link import me as _me
    from rouh.link import spaces

    async def go(me, b):
        org = str(me.org_id)
        mine = await sync_to_async(_me.me)(org)
        ops = []
        for raw in (b.get("ops") or [])[:200]:
            if not isinstance(raw, dict):
                continue
            raw = dict(raw, actor=f"person:{mine.label}")
            if raw.get("kind") == "ins":
                n = str(raw.get("id0") or "").split("~", 1)[0]
                raw["id0"] = f"{n}~person:{mine.label}"
            ops.append(_doc.read_op(raw))
        got = await spaces.change(org, sid, ops)
        if any(o["kind"] == "yes" and o["id"] in (got.get("accepted") or []) for o in ops):
            from rouh import evolution
            from rouh.link import meeting

            await sync_to_async(evolution.used)(meeting.SWITCH, "said_yes", who=me)
        return got
    return await _guard(request, go)


@only("POST")
async def api_space_cursor(request, sid: str):
    """Live cursors (step 189-09): this person's pointer, caret and selection to their own Rouh, and the
    others' back, after waiting up to ``wait`` seconds for anything new. Kept in memory only, never
    stored. It carries the CSRF token like every write: where a person points is what "this one" means
    to their Rouh, so no other site may say it for them."""
    from rouh.link import cursors

    async def go(me, b):
        return await cursors.from_page(str(me.org_id), sid[:40], b if isinstance(b, dict) else {}, who=me)
    return await _guard(request, go)


@only("GET")
async def api_space_history(request, sid: str):
    from rouh.link import spaces

    async def go(me, b):
        return await spaces.history(str(me.org_id), sid, int(request.GET.get("seq") or 0))
    return await _guard(request, go)


@only("POST")
async def api_space_act(request, sid: str):
    """invite, join, leave, end, rouh (work), skip, stop, meeting."""
    from rouh.link import meeting, pacing, peers, spaces, worker

    async def go(me, b):
        org, act = str(me.org_id), str(b.get("act") or "")
        if act == "invite":
            return await sync_to_async(spaces.invite)(org, sid, str(b.get("label") or ""), str(b.get("role") or "editor"))
        if act == "join":
            return await spaces.join(org, sid)
        if act == "leave":
            await spaces.leave(org, sid)
            return {"ok": True}
        if act == "rouh":
            task = asyncio.ensure_future(worker.work(org, sid, str(b.get("words") or ""), who=me))
            await asyncio.sleep(0.05)
            if task.done() and task.exception() is not None:
                raise task.exception()
            return {"ok": True, "started": True}
        if act == "source":
            # A person's own edit of a live page's source (step 189-08), made as this Rouh's person.
            return await spaces.source_edit(org, sid, str(b.get("html") or ""), _int(b.get("base"), -1))
        if act in ("bring_back", "put_back"):
            # Only the owner, only on their press: the live page into the task's page file, or back.
            from rouh.link import pageout

            fn = pageout.bring_back if act == "bring_back" else pageout.put_back
            return await sync_to_async(fn)(org, sid, who=me)
        if act == "ask_keep":
            from rouh.link import pageout

            return await sync_to_async(pageout.ask_keep)(org, sid, str(b.get("words") or "")[:300])
        if act == "skip":
            return {"ok": pacing.skip(org, sid)}
        if act == "stop":
            return {"ok": pacing.stop(org, sid)}
        if act == "meeting":
            return await meeting.start(org, sid, minutes=int(b.get("minutes") or 30), days=int(b.get("days") or 7))
        if act == "yes_for":
            from rouh.link import grants

            return await grants.decide_for(org, sid, str(b.get("granter") or ""), str(b.get("proposal") or ""),
                                           str(b.get("option") or ""))
        if act == "standin":
            from rouh.link import standin

            return await sync_to_async(standin.choose)(org, sid, str(b.get("label") or ""))
        raise peers.Problem("What should happen in that space?")
    return await _guard(request, go)


@only("GET")
async def api_space_log(request, sid: str):
    from rouh.link import log as _log

    async def go(me, b):
        return {"entries": await sync_to_async(_log.entries)(str(me.org_id), space=sid, most=300)}
    return await _guard(request, go)
