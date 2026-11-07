"""Trusted contacts, and each trusted contact's email as a case Petar can decide on.

    GET  /api/settings/trusted             who Rouh may deal with by email, by exact
                                           address, and for what: the Trusted contacts
                                           section of Anatomy, Behaviour, at
                                           /anatomy/behaviour/trusted-contacts
    POST /api/settings/trusted             one change, from that group; answers the
                                           whole group again
    GET  /api/settings/trusted/find?q=     contacts a few words find, to trust one
    GET  /api/settings/grants              every grant Petar can give a trusted contact, as a
                                           tree, with who holds each (`rouh/grants.py`):
                                           the Grants panel of Trusted contacts, at
                                           /anatomy/behaviour/trusted-contacts/grants
    POST /api/settings/grants              make, change, put a version back, merge, or
                                           list a grant's versions; answers the tree again
    GET  /api/mail/approvals               every case waiting for a decision, in its
                                           group's queue, and the latest after them:
                                           the Approvals page under Now, at
                                           /mail/approvals, drawn by approvalspage.js
    GET  /mail/case/<key>                  the case's one address: Rouh's page, with the
                                           case in the Approvals layer, in a frame
                                           (`approvalspage.js`)
    GET  /mail/case/<key>?framed=1         what that frame shows: the case's page, every
                                           ask with its decision and grant card
                                           (`mailcasepage.js`), then every step with
                                           what went in and came out, the routing rule
                                           by rule, the logs, tests and fixes
                                           (`rouh/case_trace.py`); opened on its own,
                                           it goes back to the address above
    GET  /mail/case/<key>/trace            the address the case's page had from 15
                                           October 2026 until it was one page again
                                           the same evening: goes to the case
    GET  /api/mail/case/<key>              that case's asks in two groups, each with
                                           its status and Petar's controls
    POST /api/mail/case/<key>              a press there: a choice on an ask, Test, or
                                           Redo (JSON, with the asks drawn again)
    POST /mail/case/<key>                  from the case's page: redo the whole email as
                                           a fresh attempt, test it, or mark a false
                                           alarm
    GET  /mail/case/<key>/request/<id>     one model request of the case, whole as
                                           sent, with its answer (JSON)
    POST /mail/case/<key>/ask              a question about the case, answered with
                                           its whole trace in front of the model
    GET  /mail/case/<key>/file/<id>        one file the case's reply carries, by the
                                           first 16 of its sha256, inline (?download=1
                                           to save it); only while it still hashes the
                                           same, so what opens is what is approved
    GET  /mail/case/<key>/file/<id>/page/<n>  that PDF's page n, drawn as a picture
    GET  /mail/case/<key>/attachment/<part>   one file the email brought, fetched from
                                           Rouh's Gmail as it is opened, inline under
                                           its own name; anything but a PDF is
                                           sandboxed, so nothing in it runs as Rouh
    GET  /mail/case/<key>/fixes            the runs fixing the checks behind steps
                                           marked false alarms, drawn again for the
                                           page while one goes (`rouh/case_fixes.py`)
    POST /mail/case/<key>/fix/<id>/stop    stop that fix's run, and only that run
    POST /mail/case/<key>/fix/<id>/undo    revert the fix's commit and redeploy
    GET  /mail/case/<key>/state            a short stamp of what the page draws, and
                                           whether anything still goes: the page asks
                                           it every few seconds and draws again only
                                           the parts that changed, never reloading

All of them are behind the sign-in (`gate.py`), and every one answers only the
person the rows belong to: a case another person's key names is "not there"
(`AGENTS.md`, "Whose data is it"). The cases are pages of their own, drawn by
the server, and every form carries Django's CSRF token. The approvals were one
too until 15 October 2026, when Petar asked for them inside Rouh, with the orb,
under Now: "It is not a setting page, it is content page" (fr_37cea76c6db3).
Trusted contacts were one too until 2 October 2026, when Petar asked for them
as a section of Settings with a list of people, each opened to be changed
(fr_ce3a4480d9b4); the page is drawn by `app.js` from the API above. A case was a page of
its own too until 15 October 2026, when Petar asked for it inside Rouh with his orb and
stripped to what he needs to decide (fr_7d4948ef128b); what it was is its trace now, with
no decisions of its own, so the case is the one approval page (fr_bfda0e144e7c), and it
works with no script; its script only adds the prompts on demand, the Ask box, copying
and the explanations on tap. The key in
a case's address is random, so the link on Petar's phone names nothing about
the email; the page it opens shows everything only to him.
"""
from __future__ import annotations

import contextlib
import json
import logging
from urllib.parse import quote, urlencode

from asgiref.sync import sync_to_async
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import render

from rouh import addressing, genes

from .common import answer, body_of, only, refuse, who

log = logging.getLogger("rouh.trusted")

#: Behaviour, Trusted contacts, from its manifest (Connections' until 4 November 2026, and under
#: /settings before that).
ROUTE = genes.BY_ID["trusted-contacts"]["route"]
APPROVALS = addressing.MAIL_APPROVALS


def _desk():
    from rouh import runtime

    alerts = runtime.mail_alerts
    return alerts.cases if alerts is not None else None


def _people():
    from rouh import runtime

    if runtime.contacts is not None:
        return runtime.contacts.people
    from rouh.people import People

    return People()


def _page(response: HttpResponse) -> HttpResponse:
    response["Cache-Control"] = "no-store, must-revalidate"
    return response


def _back(path: str, **said) -> HttpResponseRedirect:
    said = {k: v for k, v in said.items() if v}
    return HttpResponseRedirect(path + ("?" + urlencode(said) if said else ""))


def _login(path: str) -> HttpResponseRedirect:
    return HttpResponseRedirect("/login?next=" + quote(path))


# --- trusted contacts ------------------------------------------------------------------


def _object_store():
    from rouh import objects

    return objects.shared_store(even_when_off=True)


def _sees_now(me, sees) -> list[str]:
    """The silos a contact sees now (`rouh/silos.py`): theirs, or the ones shown to others."""
    from rouh import silos

    return silos.ordered(me.user_id, me.org_id, silos.others(me.user_id, me.org_id) if sees is None else sees)


def _person(one, people, me) -> dict:
    """One trusted contact as the page draws it, in the list and opened."""
    card = None
    if one.contact_id:
        try:
            card = people.person(me.user_id, me.org_id, one.contact_id)
        except Exception:  # noqa: BLE001 - the card is only a help here
            card = None
    return {"id": one.id, "name": one.name, "contact_id": one.contact_id,
            "trusted": one.trusted, "levels": list(one.levels),
            "addresses": list(one.addresses),
            "others": [a for a in (card.emails if card is not None else [])
                       if a not in one.addresses],
            "organisation": card.organisation if card is not None else "",
            "grants": list(one.grants),
            "inbox_scope": one.inbox_scope, "inbox_from": list(one.inbox_from),
            "beyond": one.beyond, "zone": one.zone, "sees": one.sees,
            "sees_now": _sees_now(me, one.sees),
            "inbox_reads": _reads(me, one.id),
            "telegram": _telegram_state(me, one.id),
            "group_id": one.group_id, "group_name": one.group_name, "note": one.note,
            "task_levels": _task_levels(me, one),
            "extra_grants": _extra(me, one),
            "cap_grants": _cap_grants(me, one),
            "grant_calendars": _grant_calendars(me, one),
            "authority": _authority(me, one)}


def _task_levels(me, one) -> dict:
    """What they may do on each row of the tree, by id: read, edit or decide, where it came
    from, and their own record's level (`task_access.page_levels`)."""
    from rouh import task_access

    try:
        return task_access.page_levels(me, one)
    except Exception:  # noqa: BLE001 - the page shows the rest
        log.exception("the task levels of trusted contact %s could not be read", one.id)
        return {}


def _cap_grants(me, one) -> list[dict]:
    """Their grants of their own, as data (CAPABILITIES.md): each in its one sentence, with its
    state, uses, the message it came from and its history, newest first, the ones in force first."""
    from rouh import capability_grants
    from rouh.mail_cases import case_path

    try:
        rows = capability_grants.page_view(me, one)
    except Exception:  # noqa: BLE001 - the page shows the rest
        log.exception("the grants of trusted contact %s could not be read", one.id)
        return []
    keep = ("id", "capability", "name", "wording", "state", "state_now", "state_said", "lifetime",
            "until", "scope", "limits", "version", "version_now", "effects", "about", "uses_done",
            "uses_today", "suspended_reason", "reason", "approved_at", "ended_at", "events")
    return [{**{k: r.get(k) for k in keep},
             "case_href": case_path(r["case_key"]) if r.get("case_key") else ""} for r in rows]


def _grant_calendars(me, one) -> dict:
    """Which calendars each calendar grant given them reaches, by key: a list of ids, or None
    for every calendar, a grant from before there was a choice (`grants.calendars_of`)."""
    from rouh import grants

    return grants.calendars_of(me.user_id, me.org_id, one.id)


def _extra(me, one) -> list[str]:
    """The grants given them as rows, as the tree names them now (a merged one as where it went)."""
    from rouh import grants

    found = grants.tree(me.org_id)
    return sorted({found.resolve(k) for k in one.extra_grants or ()} - {""})


def _more_grants(me) -> list[dict]:
    """Every grant given as a row (Clockwork, Memory, Shared task and any made since), in the
    tree's order, with what sits above each, for the More grants group of a contact's page."""
    from rouh import grants

    found = grants.tree(me.org_id)
    out = []
    for node in found.live():
        if node.holding != grants.GRANT:
            continue
        above = found.above(node.key)
        out.append({"key": node.key, "name": node.name, "description": node.description,
                    "above": above,
                    "above_names": {k: found.name(k) for k in above},
                    "above_levels": [k for k in above if found.nodes[k].holding == grants.LEVEL],
                    # Given calendar by calendar, each ticked on its own (`grants.calendars_of`).
                    "by_calendar": grants.reaches_calendars(found, node.key),
                    "depth": sum(1 for k in above if found.nodes[k].holding == grants.GRANT)})
    return out


def _authority(me, one) -> dict:
    """What they did lately where they decide for you (`rouh/delegation.py`), each with its
    Undo. What they may do is the tree's (`_task_levels`), never listed again here."""
    from rouh import delegation

    try:
        return {"acts": delegation.acts(me.user_id, me.org_id, contact_id=one.id, most=30,
                                        theirs=False)}
    except Exception:  # noqa: BLE001 - the page shows the rest
        log.exception("the acts of trusted contact %s could not be read", one.id)
        return {"acts": []}


def _telegram_state(me, trusted_id) -> dict:
    from rouh import telegram_guests

    try:
        return telegram_guests.Links().state(me.user_id, me.org_id, trusted_id)
    except Exception:  # noqa: BLE001 - the page shows the rest
        log.exception("the Telegram link of trusted contact %s could not be read", trusted_id)
        return {}


def _bot_owner(me) -> str:
    """Why this person cannot link anybody's Telegram, or "" when they can.

    The bot on this machine is its owner's (`telegram.phone_owner`), and so is
    every case it opens, so only the owner links an account to one of their
    contacts.
    """
    from rouh import runtime, telegram

    if not runtime.tools.telegram.configured():
        return "Telegram is not set up on this server."
    owner = telegram.phone_owner(runtime.tenancy)
    if owner is None or owner.user_id != me.user_id or owner.org_id != me.org_id:
        return "The Telegram bot on this server is somebody else's."
    return ""


def _reads(me, trusted_id) -> list[dict]:
    from rouh import inbox_grants

    try:
        return inbox_grants.latest(me.user_id, me.org_id, trusted_id)
    except Exception:  # noqa: BLE001 - the page shows the rest
        log.exception("the inbox reads of trusted contact %s could not be read", trusted_id)
        return []


def _contacts_view(me) -> dict:
    from rouh import delegation, inbox_grants, mail_cases, silos, trusted as trust

    store = trust.TrustStore()
    objs = _object_store()
    people = _people()
    rows = store.all(me.user_id, me.org_id)
    return {
        "approvals": APPROVALS,
        "rows": [_person(one, people, me) for one in rows],
        "groups": store.groups(me.user_id, me.org_id),
        "levels": [{"key": k, "name": v[0], "said": v[1]} for k, v in trust.LEVELS.items()],
        "inbox_scopes": [{"key": k, "name": trust.INBOX_SCOPES[k][0],
                          "said": trust.INBOX_SCOPES[k][1]} for k in trust.INBOX_STANDING],
        "inbox_writable": inbox_grants.writable(me),
        "inbox_note": "" if inbox_grants.writable(me) else inbox_grants.READ_ONLY_NOTE,
        "beyonds": [{"key": k, "name": v[0], "said": v[1]} for k, v in trust.BEYOND.items()],
        "silos": [s.chip() for s in silos.of(me.user_id, me.org_id)],
        "silos_others": silos.others(me.user_id, me.org_id),
        "tree": _tree(me),
        "never": list(delegation.NEVER.values()),
        "trusted_count": sum(1 for r in rows if r.trusted),
        "telegram_off": _bot_owner(me),
        "timing": mail_cases.timing_of(me.user_id, me.org_id),
        "more_grants": _more_grants(me),
    }


def _tree(me) -> list[dict]:
    """The one tree on a contact's page (`task_access.page_tree`)."""
    from rouh import task_access

    try:
        return task_access.page_tree(me)
    except Exception:  # noqa: BLE001 - the page shows the rest
        log.exception("the tree of the trusted contacts page could not be read")
        return []


def _find(me, query: str) -> list[dict]:
    from rouh import trusted as trust

    have = {r.contact_id for r in trust.TrustStore().all(me.user_id, me.org_id)
            if r.contact_id}
    return [f for f in trust.find_contacts(_people(), me.user_id, me.org_id, query)
            if f["id"] not in have]


@only("GET", "POST")
async def trusted_contacts(request: HttpRequest):
    """The Trusted contacts group of Settings: everybody, and one change at a time."""
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("Not signed in.", 401)
    if request.method == "POST":
        return await _change(body_of(request), me)
    return answer(await sync_to_async(_contacts_view)(me))


@only("GET")
async def find(request: HttpRequest):
    """Contacts a few words find, not already listed, to pick one to trust."""
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("Not signed in.", 401)
    query = (request.GET.get("q") or "").strip()[:100]
    return answer({"query": query,
                   "found": await sync_to_async(_find)(me, query) if query else []})


def _list(value) -> list:
    return [str(v) for v in value] if isinstance(value, list) else []


def _inbox_from(value) -> list:
    """The senders and labels typed for "A sender or label": a list, or one box of them."""
    if isinstance(value, list):
        return [str(v) for v in value]
    return [str(value or "")]


async def _change(form: dict, me) -> HttpResponse:
    """One press in the section. Every one of them is Petar's own, and nothing else writes trust.

    The answer is the whole section again, with what was said about the press
    and, for a save, which contact it was, so the page draws what is true now.
    """
    from rouh import trusted as trust

    store = trust.TrustStore()
    act = str(form.get("act") or "")
    said, saved_id = "", None
    try:
        if act == "save":
            addresses = _list(form.get("addresses")) + [
                a for a in str(form.get("more") or "").replace(",", " ").split() if a]
            # Beside each task its level, as changed on the page: {task id: edit, view or ""}.
            levels_now = {str(k): str(v or "") for k, v in form["task_levels"].items()} \
                if isinstance(form.get("task_levels"), dict) else {}
            saved = await sync_to_async(store.save)(
                me.user_id, me.org_id, name=str(form.get("name") or ""),
                contact_id=str(form.get("contact_id") or "").strip()[:40],
                addresses=addresses, levels=_list(form.get("levels")),
                grants=await sync_to_async(_tidy)(await sync_to_async(_ticks_kept)(
                    me, form.get("id"), _list(form.get("grants")), levels_now))
                if "grants" in form else await sync_to_async(_ticks_now)(me, form.get("id")),
                trusted=form.get("trusted") is True, group_id=form.get("group") or None,
                note=str(form.get("note") or ""), trusted_id=form.get("id") or None,
                inbox_scope=str(form.get("inbox_scope") or "") or None
                if "inbox_scope" in form else None,
                inbox_from=_inbox_from(form.get("inbox_from"))
                if "inbox_from" in form else None,
                beyond=str(form.get("beyond") or "") or None if "beyond" in form else None,
                zone=str(form.get("zone") or "") if "zone" in form else None)
            if isinstance(form.get("sees"), list):
                # The silos they see (`rouh/silos.py`): left to the default while the ticks are the default.
                ticked = [str(k) for k in form["sees"]]
                now = await sync_to_async(_sees_now)(me, saved.sees)
                if sorted(ticked) != sorted(now):
                    saved = await sync_to_async(store.set_sees)(me.user_id, me.org_id, saved.id, ticked)
            given = []
            if isinstance(form.get("more_grants"), list):
                from rouh import grants

                given = await sync_to_async(grants.set_given)(
                    me.user_id, me.org_id, saved.id, _list(form.get("more_grants")),
                    by=str(me.user_id),
                    calendars={str(k): _list(v) for k, v in form["grant_calendars"].items()}
                    if isinstance(form.get("grant_calendars"), dict) else None)
            if levels_now or "grants" in form:
                given += await sync_to_async(_tasks_moved)(me, saved.id, levels_now)
            log.info("user %s saved trusted contact %s (trusted %s, %d addresses)",
                     me.user_id, saved.id, saved.trusted, len(saved.addresses))
            said = (f"{saved.name} is trusted for {len(saved.addresses)} exact "
                    f"address{'es' if len(saved.addresses) != 1 else ''}." if saved.trusted
                    else f"{saved.name} is saved, and not trusted.") + \
                "".join(" " + one for one in given)
            saved_id = saved.id
        elif act in ("trust", "untrust"):
            saved = await sync_to_async(store.set_trusted)(me.user_id, me.org_id,
                                                           form.get("id"), act == "trust")
            log.info("user %s %s trusted contact %s", me.user_id,
                     "switched on" if saved.trusted else "switched off", saved.id)
            said = (f"{saved.name} is trusted again." if saved.trusted else
                    f"{saved.name} is no longer trusted. Nothing from them "
                    "is handled by Rouh without you now.")
            saved_id = saved.id
        elif act == "remove":
            gone = await sync_to_async(store.remove)(me.user_id, me.org_id, form.get("id"))
            if not gone:
                return refuse("That contact was not there.", 404)
            log.info("user %s removed trusted contact %s", me.user_id, form.get("id"))
            said = "Removed."
        elif act in ("tg_code", "tg_confirm", "tg_refuse", "tg_unlink"):
            said, extra = await _telegram_press(act, form, me)
            saved_id = form.get("id")
            view = await sync_to_async(_contacts_view)(me)
            view.update(said=said, saved=saved_id, **extra)
            return answer(view)
        elif act in ("task_level", "tick", "authority_undo"):
            # One press in the tree, or an Undo under it: answered with what changed alone, so
            # the page changes those rows in place and nothing else moves (B1).
            said = await _row_press(act, form, me)
            return answer(await sync_to_async(_rows_now)(me, form.get("id"), said))
        elif act == "cap_revoke":
            # A grant of their own taken back, at once: a call checked after this finds it gone
            # (CAPABILITIES.md). Only one of this contact's, of this owner's.
            from rouh import capability_grants

            got = await sync_to_async(capability_grants.one)(me.user_id, me.org_id,
                                                             form.get("grant"))
            if got is None or str(got["contact"]) != str(form.get("id")):
                return refuse("That grant is not theirs.", 404)
            done = await sync_to_async(capability_grants.revoke)(
                me, got["id"], by=str(me.user_id), reason=str(form.get("reason") or "")[:2000])
            log.info("user %s took back grant %s of trusted contact %s", me.user_id, got["id"],
                     form.get("id"))
            said, saved_id = done["said"], form.get("id")
        elif act == "timing":
            from rouh import mail_cases

            kept = await sync_to_async(mail_cases.put_timing)(
                me.user_id, me.org_id, remind_hours=form.get("remind_hours"))
            log.info("user %s set the case timing to %s", me.user_id, kept)
            said = ("Reminders: " + (f"after {mail_cases.hours_said(kept['remind_hours'])}"
                                     if kept["remind_hours"] else "never") + ".")
        elif act == "add_group":
            made = await sync_to_async(store.add_group)(me.user_id, me.org_id,
                                                        str(form.get("group_name") or ""))
            said = (f"The queue {made['name']} is there. Put contacts in it from their "
                    "page; it only sorts their approvals.")
        elif act == "remove_group":
            gone = await sync_to_async(store.remove_group)(me.user_id, me.org_id,
                                                           form.get("group"))
            said = "The queue is gone; its contacts are in no queue now." if gone else ""
        else:
            return refuse("That press was not understood.", 400)
    except ValueError as exc:
        return refuse(str(exc), 400)
    view = await sync_to_async(_contacts_view)(me)
    view.update(said=said, saved=saved_id)
    return answer(view)


def _ticks_now(me, contact_id) -> list[str]:
    from rouh import trusted as trust

    was = trust.TrustStore().get(me.user_id, me.org_id, contact_id) if contact_id else None
    return list(was.grants) if was is not None else []


async def _row_press(act: str, form: dict, me) -> str:
    """A level set on one row of a contact's tree, a column or project ticked or not, or one
    thing they did put back. Petar's own, like every press here."""
    from rouh import delegation, task_access
    from rouh import trusted as trust

    try:
        if act == "task_level":
            said = await sync_to_async(delegation.set_on)(
                me, form.get("id"), str(form.get("task") or ""), str(form.get("level") or ""))
            log.info("user %s set trusted contact %s to %s on %s", me.user_id, form.get("id"),
                     form.get("level") or "none", form.get("task"))
            return said
        if act == "tick":
            node = str(form.get("node") or "")
            objs = _object_store()
            rows = trust.Tree(objs).rows if objs is not None else {}
            if (rows.get(node) or {}).get("type") != "project":
                raise ValueError("Only a column or a project is ticked; a task has its level.")
            now = [g for g in await sync_to_async(_ticks_now)(me, form.get("id"))
                   if (rows.get(g) or {}).get("type") == "project"]
            want = now + [node] if form.get("on") is True else [g for g in now if g != node]
            saved = await sync_to_async(trust.TrustStore().set_ticks)(
                me.user_id, me.org_id, form.get("id"), await sync_to_async(_tidy)(want))
            try:
                await sync_to_async(task_access.keep_ticks)(me)
            except Exception:  # noqa: BLE001 - the next pass of `requester_share.keep` does it
                log.exception("the ticked tasks of trusted contact %s could not be shared",
                              saved.id)
            title = (rows.get(node) or {}).get("title") or "It"
            return (f"{saved.name} may read everything in {title}, now and later."
                    if form.get("on") is True else
                    f"{title} is not ticked for {saved.name} any more.")
        said = await delegation.undo(me, form.get("act_id"))
        log.info("user %s undid delegate action %s", me.user_id, form.get("act_id"))
        return "Undone. " + said
    except delegation.Refused as exc:
        raise ValueError(str(exc)) from None


def _rows_now(me, contact_id, said: str) -> dict:
    """What one press in the tree answers: the contact's levels on every row, what is ticked,
    and their acts, and nothing else of the page."""
    from rouh import trusted as trust

    one = trust.TrustStore().get(me.user_id, me.org_id, contact_id)
    if one is None:
        return {"said": said, "rows": True}
    return {"said": said, "rows": True, "id": one.id, "task_levels": _task_levels(me, one),
            "grants": list(one.grants), "levels": list(one.levels),
            "authority": _authority(me, one)}


def _ticks_kept(me, contact_id, ticked: list, levels_now: dict) -> list[str]:
    """What is ticked on their page, as kept: the columns and projects ticked, and every task
    they had ticked before that was not taken away beside it. A task ticked on the page now is
    a share of it (`_tasks_moved`), not a tick, so the tick list holds what reaches later tasks."""
    from rouh import trusted as trust

    objs = _object_store()
    rows = trust.Tree(objs).rows if objs is not None else {}
    was = trust.TrustStore().get(me.user_id, me.org_id, contact_id) if contact_id else None
    kept = [g for g in ticked if (rows.get(g) or {}).get("type") != "task"]
    kept += [g for g in (was.grants if was is not None else ())
             if (rows.get(g) or {}).get("type") == "task" and levels_now.get(g, "x") != ""]
    return list(dict.fromkeys(kept))


def _tasks_moved(me, contact_id, levels_now: dict) -> list[str]:
    """Each task's level changed on their page, carried out, and what is ticked shared to read
    with them in Rouh too (`rouh/task_access.py`). What happened, a sentence each."""
    from rouh import task_access
    from rouh import trusted as trust

    now = trust.TrustStore().get(me.user_id, me.org_id, contact_id)
    if now is None:
        return []
    said = task_access.set_from_page(me, now, levels_now)
    try:
        task_access.keep_ticks(me)
    except Exception:  # noqa: BLE001 - the next pass of `requester_share.keep` does it
        log.exception("the ticked tasks of trusted contact %s could not be shared", contact_id)
    return said


async def _telegram_press(act: str, form: dict, me) -> tuple[str, dict]:
    """One press about a contact's own Telegram account (`rouh/telegram_guests.py`).

    A code is made here and shown once; the account that uses it is only
    linked when Petar confirms it here, bound to the account he was shown.
    Nothing here ever links an account by itself.
    """
    from rouh import runtime, telegram_guests as tgg, trusted as trust

    links = tgg.Links()
    found = await sync_to_async(trust.TrustStore().get)(me.user_id, me.org_id, form.get("id"))
    if found is None:
        raise ValueError("That contact is not one of yours.")
    if act == "tg_code":
        why = await sync_to_async(_bot_owner)(me)
        if why:
            raise ValueError(why + " Nobody can be linked.")
        code, until = await sync_to_async(links.make_code)(me.user_id, me.org_id, found.id)
        link = await runtime.telegram_guests.bot_link(code)
        log.info("user %s made a Telegram link code for trusted contact %s", me.user_id,
                 found.id)
        return (f"A link code for {found.name} is ready. Send it to them; it works once.",
                {"tg_code": {"id": found.id, "code": code, "link": link,
                             "command": f"/start {code}", "until": until}})
    if act == "tg_confirm":
        state = await sync_to_async(links.confirm)(me.user_id, me.org_id, found.id,
                                                   str(form.get("tg_user_id") or ""))
        log.info("user %s confirmed Telegram account %s for trusted contact %s", me.user_id,
                 state.get("tg_user_id"), found.id)
        await runtime.telegram_guests.tell(state.get("tg_user_id"), tgg.LINKED_SAID.format(
            owner=tgg.Guests._owner_name(me)))
        said = f"{found.name}'s Telegram account is linked: {state.get('account')}."
        if not found.trusted:
            said += (" They are not trusted now, so everything they send there waits for "
                     "you.")
        return said, {}
    was = await sync_to_async(links.drop)(me.user_id, me.org_id, found.id)
    if was.get("state") == tgg.LINKED:
        await runtime.telegram_guests.tell(was.get("tg_user_id"), tgg.UNLINKED_SAID)
    log.info("user %s %s the Telegram link of trusted contact %s (was %s)", me.user_id,
             "refused" if act == "tg_refuse" else "undid", found.id, was.get("state") or "none")
    if act == "tg_refuse":
        return (f"Refused. That Telegram account is not linked to {found.name}, and the code "
                "is spent. Make a new code to try again." if was else "Nothing was waiting."), {}
    return ((f"{found.name}'s Telegram account is unlinked. Nothing from it reaches Rouh now."
             if was.get("state") == tgg.LINKED else "The link code is withdrawn.")
            ), {}


# --- grants: what can be given, as rows (`rouh/grants.py`) ----------------------------------


def _grants_view(me, *, versions_of: str = "") -> dict:
    """The organisation's grants as the panel draws them: the tree, who holds each, and one
    grant's versions when asked."""
    from rouh import grants, trusted as trust

    found = grants.tree(me.org_id)
    contacts = trust.TrustStore().all(me.user_id, me.org_id)
    rows = []
    for row in found.as_list():
        holding = [c for c in contacts if found.holds(c, row["key"])]
        given = [c for c in holding if row["key"] in found.given(c)]
        row.update(holders=[c.name for c in holding], held=len(holding),
                   given=[c.name for c in given],
                   parent_name=found.name(row["parent"]) if row["parent"] else "",
                   movable=row["holding"] == grants.GRANT,
                   parents=[n.key for n in found.live() if n.holding != grants.INBOX
                            and n.key != row["key"] and n.key not in found.under(row["key"])])
        rows.append(row)
    # What each lets Rouh do: the capabilities the code declares for it (CAPABILITIES.md). One
    # made from words with none behind it is kept for review and allows nothing.
    from rouh import capabilities

    catalogue = capabilities.catalogue()
    for row in rows:
        named = catalogue.by_legacy(row["key"]) + (
            catalogue.by_legacy("lift:time") if "time" in found.lifts(row["key"]) else [])
        row["allows"] = [{"id": c.id, "name": c.name, "effects": capabilities.effects_said(c)}
                         for c in named]
        row["for_review"] = not named
    view = {"grants": rows, "limits": list(grants.HARD_LIMITS.values())}
    if versions_of:
        key = found.resolve(versions_of) or versions_of
        listed = grants.versions(me.org_id, key)
        for v in listed:
            v["by_said"] = ("as first set up" if v["by"] == "seed" else
                            "by you" if v["by"] == str(me.user_id) else
                            f"by {v['by']}" if v["by"] else "")
        view["versions"] = {"key": key, "list": listed}
    return view


@only("GET", "POST")
async def grants_panel(request: HttpRequest):
    """The grants Petar can give: read them, or one change, every one a version of its own."""
    from rouh import grants

    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("Not signed in.", 401)
    if request.method == "GET":
        return answer(await sync_to_async(_grants_view)(
            me, versions_of=(request.GET.get("versions") or "").strip()[:80]))
    form = body_of(request)
    act = str(form.get("act") or "")
    key = str(form.get("key") or "").strip()[:80]
    by = str(me.user_id)
    said, show = "", key
    try:
        if act in ("create", "merge"):
            # A grant made or widened from words allows nothing since 21 October 2026: what a
            # grant lets Rouh do is what the code declares (CAPABILITIES.md).
            return refuse("Grants are no longer made or merged from words: what Rouh may do for "
                          "a contact is what its code declares, given as a grant from a case or "
                          "on their page.", 400)
        if act == "save":
            parent = form.get("parent")
            node = await sync_to_async(grants.edit)(
                me.org_id, key, name=form.get("name"), title=form.get("title"),
                description=form.get("description"),
                prompt=form.get("prompt"),
                parent_key=str(parent or "").strip() if parent is not None else None, by=by,
                why="Changed on the Grants page.")
            said = f"{node.name} is saved, as version {node.revision}."
            log.info("user %s changed grant %s to version %s", me.user_id, key, node.revision)
        elif act == "undo":
            to = form.get("revision")
            node = await sync_to_async(grants.undo)(
                me.org_id, key, by=by, to_revision=int(to) if to not in (None, "") else None)
            said = (f"{node.name} is back as it was; that is version {node.revision}."
                   )
            log.info("user %s put grant %s back (now version %s)", me.user_id, key, node.revision)
        elif act != "versions":
            return refuse("That press was not understood.", 400)
    except (ValueError, TypeError) as exc:
        return refuse(str(exc), 400)
    view = await sync_to_async(_grants_view)(me, versions_of=show)
    view.update(said=said, shown=show)
    return answer(view)


def _tidy(grants) -> list[str]:
    from rouh import trusted as trust

    objs = _object_store()
    return trust.tidy_grants(objs, grants) if objs is not None else []


# --- the approvals and the cases ---------------------------------------------------------


@only("GET")
async def approvals(request: HttpRequest):
    """The Approvals page's rows: the queues, how many wait, and the latest after them."""
    from rouh import genes

    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("Sign in first.", 401)
    # Where the queues are set up, which the page links to.
    contacts = genes.BY_ID["trusted-contacts"]["route"]
    desk = _desk()
    if desk is None:
        return _page(answer({"off": True, "queues": [], "waiting": 0, "recent": [], "contacts": contacts}))
    got = await sync_to_async(desk.queue)(me)
    return _page(answer({"off": False, "contacts": contacts, **got}))


#: The query that asks a case's address for the case's own page, which Rouh shows in a frame
#: inside the Approvals layer (`approvalspage.js`); without it the address is Rouh's page.
FRAMED = "framed"


def _framed(path: str, **said) -> HttpResponseRedirect:
    """Back to the case's page in its frame, with what a press said."""
    return _back(path, **{FRAMED: "1", **said})


@only("GET", "POST")
async def case(request: HttpRequest, key: str):
    """A case's one address (Petar, 15 October 2026, fr_65ed87c8685b: "The new approvals page
    should be merged into the old one, and there should be 1 url").

    Read in the browser's address bar, it is Rouh's page, which opens the Approvals layer with
    the orb beside it (fr_7d4948ef128b) and shows the case there in a frame. The frame asks the
    same address with `?framed=1`, and that is the case's page drawn by the server: the old
    page, every step, log, test and fix, with what was the new page in it - every ask with its
    decision and grant card (`mailcasepage.js`). Opened on its own, with nothing around it,
    `?framed=1` goes back to the plain address, so the case is never shown without Rouh. The
    page's forms post here."""
    from rouh.mail_cases import case_path

    if request.method == "POST":
        return await _case_page(request, key)
    if not request.GET.get(FRAMED):
        from . import views

        return await views.index(request)
    if request.headers.get("Sec-Fetch-Dest") == "document":
        return HttpResponseRedirect(case_path(key))
    return await _case_page(request, key)


@only("GET", "POST")
async def case_trace(request: HttpRequest, key: str):
    """The case's trace, `/mail/case/<key>/trace`, from 15 October 2026 until the trace and the
    case were one page again the same evening (fr_65ed87c8685b): goes to the case, so a link
    or a bookmark to it still opens it."""
    from rouh.mail_cases import case_path

    if request.method == "POST":
        return await _case_page(request, key)
    return HttpResponseRedirect(case_path(key))


async def _case_page(request: HttpRequest, key: str):
    """The case's page (`mail_case.html`): every ask with its decision (`mailcasepage.js`, from
    `case_api`), and every step of the case, for seeing and tuning it (`rouh/case_trace.py`);
    and its presses, Redo, Test and a step marked, which come back to it in its frame."""
    from rouh.mail_cases import case_path

    path = case_path(key)
    framed = f"{path}?{FRAMED}=1"
    me = await sync_to_async(who)(request)
    if me is None:
        return _login(path)
    desk = _desk()
    if desk is None:
        return HttpResponse("New mail is not handled on this server.", status=404,
                            content_type="text/plain; charset=utf-8")
    if request.method == "POST":
        form = request.POST
        choice = form.get("choice") or ""
        try:
            if choice == "redo":
                try:
                    attempt = int(form.get("attempt") or 0)
                except ValueError:
                    attempt = 0
                said = await desk.redo(me, key, attempt=attempt,
                                       instruction=form.get("instruction") or "")
            elif choice == "test":
                from rouh import case_dry_run

                run_id = await case_dry_run.run(desk, me, key)
                said = (f"Test {run_id} started: what a run would do now, with the grants as "
                        "they are, and nothing sent or changed. Its steps show under Tests as "
                        "they come in.")
            elif choice in desk.VERDICTS:
                said = await desk.remark(me, key, choice, form.get("step") or "",
                                         form.get("reason") or "")
            else:
                raise ValueError("That press was not understood.")
        except LookupError:
            return await _case_missing(request)
        except ValueError as exc:
            return _framed(path, bad=str(exc))
        log.info("user %s on case %s: %s", me.user_id, key[:6], choice)
        anchor = "followUp" if choice == "false_alarm" else form.get("back") or ""
        return HttpResponseRedirect(_framed(path, said=said).url
                                    + (f"#{anchor}" if anchor.replace("-", "").replace(
                                        "_", "").isalnum() else ""))
    # Taken before the page is drawn, so a change while it is drawn is never missed by the
    # page's own asking after it (`case_state`).
    stamp = await sync_to_async(desk.page_stamp)(me, key)
    try:
        view = await sync_to_async(_case_view)(desk, me, key)
    except Exception:
        log.exception("case %s could not be drawn for user %s", key[:6], me.user_id)
        return await _case_missing(request, drawn=False)
    if view is None:
        return await _case_missing(request)
    view["stamp"] = (stamp or {}).get("stamp") or ""
    said = request.GET.get("said") or ""
    view.update(route=ROUTE, approvals=APPROVALS, path=path, framed=framed,
                said=said[:600], bad=(request.GET.get("bad") or "")[:300])
    return _page(await sync_to_async(render)(request, "rouh/mail_case.html", view))


async def _case_missing(request: HttpRequest, *, drawn: bool = True) -> HttpResponse:
    """A case link that cannot show its case, in plain words with a way back, never a bare
    error (Petar, 13 October 2026, fr_e71feba5b161). `drawn` is False when the case is there
    but its page failed to draw: the log has why."""
    if drawn:
        title, said, status = ("There is no such case",
                               ("Nothing under this link belongs to your account. The case may "
                                "have been removed, or the link may be cut short."), 404)
    else:
        title, said, status = ("This case cannot be shown right now",
                               ("The case is there, but its page could not be drawn. Rouh's "
                                "log says why; nothing about the case itself was changed."), 500)
    return _page(await sync_to_async(render)(
        request, "rouh/mail_case_missing.html",
        {"title": title, "said": said, "approvals": APPROVALS, "dark_only": True},
        status=status))


async def _held_press(desk, me, key: str, form) -> tuple[str, str]:
    """One choice on one box of what waits for Petar, from the case page, saved at once (Petar,
    11 October 2026): "grant:" sets its grant up - independent, sub_grant_of or merge_into, with
    the target from the page - once for every ask in the box; "contact:" decides what the
    contact gets for all of them - grant (Give permanently), once, decline or mine; "test:grants"
    judges the ledger again with the grants and the choices as they stand, at once, with no
    model (`CaseDesk.test_grants`). A choice is saved and nothing else happens: only Petar's
    Redo runs the case (D6). Answers what was done, and what follows from it."""
    from rouh import decisions
    from rouh import mail_ledger as ledger

    part, _, act = str(form.get("act") or "").partition(":")
    if part == "test":
        got = await sync_to_async(desk.test_grants)(me, key)
        return got["said"], ""
    idents = [str(i) for i in form.getlist("ask") if str(i)]
    if not idents:
        raise ValueError("Those asks are no longer waiting.")
    case = await sync_to_async(_case_of)(desk, me, key)
    if case is None:
        raise LookupError(key)
    pending = await sync_to_async(desk.store.decision)(me.user_id, me.org_id, case.id)
    if pending is not None:
        found = await sync_to_async(decisions.for_source)(me, "mail", str(pending.id)) or {}
        if found.get("status") in ("answered", "applying"):
            raise ValueError("You answered these on the Decisions page a moment ago, and that "
                             "answer goes in a few seconds. The page shows it then.")
    if part == "contact":
        if act not in ledger.CHOICES:
            raise ValueError("Pick what to give them.")
        raw = {"choice": act}
        if form.get("proposal"):
            try:
                raw["proposal"] = json.loads(form.get("proposal"))
            except ValueError:
                raise ValueError("That grant could not be read.") from None
        if form.get("digest"):
            raw["digest"] = form.get("digest")
        if form.get("reason"):
            raw["reason"] = form.get("reason")
        if act == ledger.GRANT and form.get("grant"):
            # A grant there is, picked to give them for an ask no grant covered (Petar, 18
            # October 2026, fr_aa3ca23c06f7).
            raw.update(how="give", grant=str(form.get("grant")))
        if form.get("calendars_given"):
            raw["calendars"] = form.getlist("calendar")
        said = await desk.decide_asks(me, key, choices={i: dict(raw) for i in idents},
                                      run=False)
    else:
        raise ValueError("Pick a choice.")
    with contextlib.suppress(Exception):
        await sync_to_async(decisions.sync)(me, ["mail"])
    return said, ""


@only("GET")
async def case_state(request: HttpRequest, key: str):
    """The case page's question every few seconds: has anything it draws changed, and is
    anything still going (`CaseDesk.page_stamp`)."""
    me = await sync_to_async(who)(request)
    desk = _desk()
    if me is None or desk is None:
        return JsonResponse({"error": "Not signed in."}, status=403)
    got = await sync_to_async(desk.page_stamp)(me, key)
    if got is None:
        return JsonResponse({"error": "There is no such case."}, status=404)
    return _page(JsonResponse(got))


# --- what they asked, and the decision on each, at the top of the case's page ----------


#: Where an ask came from, as the case's groups put it (`mail_ledger.Ask.source`): what the
#: sender asked for, or what the work found it needs (D18, "Needs you ..." raised by a run).
NEEDED = "work"


def _first_clause(text: str) -> str:
    """The first clause of a long sentence the work wrote: what it is, before why."""
    import re

    text = " ".join(str(text or "").split())
    return re.split(r"(?<=[a-z])[.;:]\s|\s(?:so|so that|because)\s", text, maxsplit=1)[0]


def _wants(first: str, label: str) -> str:
    """What they asked, as what they want: "Sam wants to add the flights to the trip". A label
    is a few words in the imperative ("Add the flights to the trip"); one that does not start
    with a plain word, such as a name, is kept as it is."""
    label = " ".join(str(label or "").split()).rstrip(".")
    head = label.split(" ", 1)[0]
    if not first or not head[:1].isupper() or not head[1:].islower() or not head.isalpha():
        return label
    return f"{first} wants to {head.lower()}{label[len(head):]}"


def _case_item(a: dict, every: dict, first: str = "") -> dict:
    """One ask as a row of the case: what it is in a few words, the sender's own words asking
    it, where it stands, and what is only about it (the long explanation, why, what shows it
    done), said once. Its decision, when it waits on Petar, is its box's (`_case_box`).

    Petar, 15 October 2026 (fr_1dd66d24e1f6): what the work needs was its own long sentence,
    three times over, where he wanted "Sam wants to edit a task" and their quote. So an ask the
    work raised is named by the ask it serves (`MailAsk.serves`), with that ask's quote, and its
    own sentence is under Details; with none named, by the sentence's first clause. `every` is
    the case's ledger by id, `first` the sender's first name."""
    named = " ".join(a["named"].split())
    quote = a["quote"] if " ".join(a["quote"].split()) not in named else ""
    # What stopped its work, in the work's words, said once under Details (D29).
    about = " ".join(str(a.get("blocker") or "").split())
    if a.get("source") == NEEDED:
        about = " ".join((a.get("do") or a["named"]).split())
        served = every.get(a.get("serves") or "")
        if served is not None:
            named, quote = _wants(first, served["named"]), served["quote"]
        else:
            named, quote = _first_clause(about), ""
    why = a["why"]
    if why.startswith("No grant covers it"):
        # Said by the box under it, which proposes the grant or offers once or a grant.
        why = ""
    return {"id": a["ident"], "n": a["n"], "what": named, "quote": quote, "about": about,
            "status": a["status"], "words": a["words"], "tone": a["tone"],
            "why": why, "possible": a.get("possible") or "",
            "needs": a["lift_said"] or (f"Hard limit: {a['limit_said']}" if a["hard_limit"]
                                        else a["grant_said"]),
            "choice": a["choice"], "choice_said": a["choice_said"],
            "evidence": [" ".join(str(e.get("said") or "").split())
                         for e in a.get("evidence_said") or [] if e.get("said")],
            "work": [{k: w.get(k, "") for k in ("title", "href", "now", "tone")}
                     for w in a.get("work_now") or []],
            "box": ""}


#: The grant card's words, as the case page shows them (`mailcasepage.js`).
_GRANT_FIELDS = ("key", "kind", "made", "name", "canonical", "proposed", "title", "description",
                 "prompt", "prompt_kind", "addition", "path", "tools", "tools_from", "lifts",
                 "limit", "holders", "affects", "suggestion", "target", "why_new", "nearest", "inbox",
                 "by_calendar", "calendars_held", "calendars_now", "task", "level",
                 # A grant Rouh's code proposes as data (CAPABILITIES.md).
                 "capability", "version", "resource", "fields", "wording", "digest", "problems",
                 "effects", "about", "constraints", "declined")


def _case_box(box: dict, first: str, listed: bool) -> dict:
    """One decision of the case, as the old page's boxes had it (`CaseDesk.held_view`): the
    grant the asks in it need, set up first when it is new (step 1), and what the contact gets
    (step 2). Each choice says whether it is final: setting a grant up and giving it take
    effect at once; Allow once, Decline and I'll see to it are only saved, and can be changed
    until Redo runs them (Petar, 15 October 2026, fr_bfda0e144e7c)."""
    from rouh import mail_ledger as ledger

    g = box["grant"]
    card = {k: g.get(k) for k in _GRANT_FIELDS}
    name = card["canonical"] or card["name"]
    options = {o["key"]: o for o in box["options"]}
    new = g["state"] == "new" and not g.get("set_up")
    later = " It is saved the moment you press it, and Rouh acts on it when you press Redo."
    task = g["state"] == "task"
    said = {
        ledger.GRANT: (f"{first} gets " + ("the new grant" if new else name)
                       + " from now on, for this and every later ask like it."
                       + (" Rouh creates the grant first, as Grant above proposes it." if new
                          else "")
                       + " It takes effect the moment you press it. Pressing another choice "
                         f"afterwards does not take it back: do that on {first}'s page in "
                         "Trusted contacts."),
        ledger.ONCE: ("Rouh does it this once, and they may not edit the task." if task else
                      "Rouh does it this once, and grants nothing.") + later,
        ledger.DECLINE: "Rouh does not do it, and the reply says you decided not to." + later,
        ledger.MINE: "Rouh does not do it: you see to it yourself." + later,
    }
    if g["state"] == "proposal":
        said[ledger.GRANT] = (f"{first} gets exactly the grant above, as its sentence says, and "
                              "nothing more. It takes effect the moment you press it. Take it "
                              f"back on {first}'s page in Trusted contacts.")
        said[ledger.DECLINE] = ("Rouh does not do it, and the reply says you decided not to. "
                                "Your reason, if you write one, is kept with the proposal and "
                                "shown the next time the same is proposed." + later)
    if g["state"] == "unsupported":
        said[ledger.MINE] = "Nothing Rouh has can do it: you see to it yourself." + later
    if task:
        # Letting them edit the task is no grant (D28): the same share Rouh's own pages read.
        said[ledger.GRANT] = (f"{first} may edit task {g['task']} from now on, in Rouh, by "
                              "email and on Telegram, and this and every later ask like it goes "
                              "ahead. It takes effect the moment you press it. To take it back, "
                              f"untick the task on {first}'s page in Trusted contacts.")
    out = []
    for k in (ledger.GRANT, ledger.ONCE, ledger.DECLINE, ledger.MINE):
        o = options.get(k)
        if o is None:
            if k != ledger.GRANT or g["state"] == "limit":
                continue
            # Not on the Trusted contacts: a grant cannot be given, and the page says why.
            o = {"key": k, "label": ledger.CHOICES[k][0], "off": True, "chosen": False}
            why = "Only somebody on your Trusted contacts can be given a grant."
        else:
            # A new grant is created as proposed when it is given (`CaseDesk._ask_choice`), so
            # all four can be pressed at any time (fr_1dd66d24e1f6).
            o = {**o, "off": False}
            why = ""
        label = (f"Let {first} edit it" if task and k == ledger.GRANT else
                 "Give it" if g["state"] == "proposal" and k == ledger.GRANT else o["label"])
        if task and o["off"] and k == ledger.GRANT:
            why = "Only somebody on your Trusted contacts can be let in to a task."
        out.append({"key": k, "label": label, "said": said[k], "chosen": bool(o["chosen"]),
                    "off": bool(o["off"]), "why_off": why, "final": k == ledger.GRANT})
    return {"key": box["key"], "n": box["n"], "asks": [x["id"] for x in box["asks"]],
            "grant": card, "set_up": bool(g.get("set_up")), "listed": listed,
            "choice": box["choice"],
            "choice_said": ledger.CHOICES.get(box["choice"], ("",))[0] if box["choice"] else "",
            "options": out}


def _case_app(desk, me, key: str) -> dict | None:
    """What the case's page draws at its top (`mailcasepage.js`): every ask of it in two groups
    - what they asked, and what the work needs - each with its status, and each that waits on
    Petar inside its decision box (`_case_box`): the grant it needs and what the contact gets,
    together; then Test and Redo. Explanations of how it works are behind its (i) icons (Petar,
    15 October 2026, fr_7d4948ef128b; the boxes are the old page's, with the asks merged in,
    fr_bfda0e144e7c). Who sent it, the message, what went back and every step are the page's
    own, drawn by the server (`mail_case.html`), since the two were one page again the same
    evening (fr_65ed87c8685b)."""
    from rouh.mail_cases import case_path, first_name

    view = desk.view(me, key)
    if view is None:
        return None
    case = view["case"]
    held = view["held"] or {}
    contact = view["contact"]
    name = case.sender_name or (contact.name if contact is not None else "") or case.sender
    first = first_name(name) or name
    listed = bool(contact is not None and not contact.implicit and contact.trusted)
    every = {a["ident"]: a for a in view["ledger"]}
    items = [_case_item(a, every, first) for a in view["ledger"]]
    source = {a["ident"]: a.get("source") or "" for a in view["ledger"]}
    # Each ask that waits on Petar sits in its decision's box, with the other asks that need
    # the same grant; a box is drawn where its first ask is.
    boxes = {}
    for box in held.get("boxes") or []:
        one = _case_box(box, first, listed)
        boxes[one["key"]] = one
        for i in items:
            if i["id"] in one["asks"]:
                i["box"] = one["key"]
    groups = []
    asked = [i for i in items if source[i["id"]] != NEEDED]
    needed = [i for i in items if source[i["id"]] == NEEDED]
    if asked:
        groups.append({"key": "asked", "name": f"What {first} asked", "items": asked})
    if needed:
        groups.append({"key": "needed", "name": "What the work needs", "items": needed})
    return {
        "key": case.key, "path": case_path(case.key), "first": first, "name": name,
        "noun": view["noun"],
        # Their page in Trusted contacts, where what they are trusted for is changed (Petar,
        # 16 October 2026, fr_c622df46477c): their name on the page leads there.
        "contact_href": (f"{ROUTE}/{contact.id}" if contact is not None and not contact.implicit
                         and contact.id else ""),
        "groups": groups, "boxes": boxes,
        "redo": {k: view["redo"].get(k) for k in ("open", "why_not", "attempt")},
        "answered_elsewhere": bool(held.get("answered_elsewhere")),
        "grants": [{"key": g["key"], "label": g["label"], "holders": g["holders"]}
                   for g in held.get("grants") or []],
        "parents": [{"key": g["key"], "label": g["label"], "holders": g["holders"]}
                    for g in held.get("parents") or []],
    }


def _press(body: dict):
    """The case page's press as the form `_held_press` reads."""
    from django.http import QueryDict

    form = QueryDict(mutable=True)
    form.setlist("ask", [str(i) for i in body.get("asks") or [] if str(i)])
    form["act"] = str(body.get("act") or "")
    form["target_sub"] = form["target_merge"] = str(body.get("target") or "")
    form["grant"] = str(body.get("grant") or "")[:80]
    # A grant's words as Petar edited them before it is created (Petar, 16 October 2026,
    # fr_c622df46477c): "I have create button for a grant but it don't allow me to edit it".
    for f in ("name", "description", "prompt"):
        if body.get(f) is not None:
            form[f] = str(body.get(f) or "")[:4000]
    # A grant Rouh's code proposed, as the owner was shown it, and the digest of what he saw
    # (CAPABILITIES.md); his reason when he declines.
    if isinstance(body.get("proposal"), dict):
        form["proposal"] = json.dumps(body["proposal"])[:20000]
    form["digest"] = str(body.get("digest") or "")[:64]
    form["reason"] = str(body.get("reason") or "")[:2000]
    # The calendars ticked for a calendar grant, given one at a time (Petar, 16 October 2026).
    if isinstance(body.get("calendars"), list):
        form["calendars_given"] = "1"
        form.setlist("calendar", [str(c)[:300] for c in body["calendars"][:200] if str(c)])
    return form


@only("GET", "POST")
async def case_api(request: HttpRequest, key: str):
    """The case inside Rouh: read it (`_case_app`), or press one of its controls - a choice on
    asks ("choose", saved at once and nothing else, D6), "test" (each ask as a run would take it
    now, with nothing done, D9) or "redo" (Petar's run of it). Answers what was done and the
    case drawn again."""
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("Sign in first.", 401)
    desk = _desk()
    if desk is None:
        return _page(answer({"off": True}))
    ok, said, error, test = True, "", "", None
    if request.method == "POST":
        body = body_of(request)
        do = str(body.get("do") or "")
        try:
            if do == "choose":
                said, _ = await _held_press(desk, me, key, _press(body))
            elif do == "preview":
                # A proposed grant as the owner narrowed it: validated and worded by code, and
                # given the digest Give is then bound to. Nothing is saved (CAPABILITIES.md).
                asks = [str(i) for i in body.get("asks") or [] if str(i)]
                shown = await sync_to_async(desk.preview_grant)(
                    me, key, ask_id=asks[0] if asks else "",
                    fields=body.get("proposal") if isinstance(body.get("proposal"), dict) else {})
                return _page(answer({"ok": True, "preview": shown}))
            elif do == "redo":
                try:
                    attempt = int(body.get("attempt") or 0)
                except (TypeError, ValueError):
                    attempt = 0
                said = await desk.redo(me, key, attempt=attempt)
            else:
                raise ValueError("That press was not understood.")
        except LookupError:
            return refuse("There is no such case.", 404)
        except ValueError as exc:
            ok, error = False, str(exc)
        except Exception:  # the page says it failed, in words
            log.exception("a press on case %s failed", key[:6])
            ok, error = False, ("It could not be done: something went wrong on the server. "
                                "Try again in a moment.")
        log.info("user %s on case %s: %s %s: %s", me.user_id, key[:6], do,
                 str(body.get("act") or ""), "done" if ok else "failed")
    # Taken before the case is drawn, so a change while it is drawn is never missed by the
    # page's own asking after it (`case_state`).
    stamp = await sync_to_async(desk.page_stamp)(me, key)
    try:
        view = await sync_to_async(_case_app)(desk, me, key)
    except Exception:
        log.exception("case %s could not be drawn for user %s", key[:6], me.user_id)
        return refuse("This case cannot be shown right now: the server could not draw it. "
                      "Nothing about the case itself was changed.", 500)
    if view is None:
        return refuse("There is no such case. Nothing under this link belongs to your account.",
                      404)
    view["stamp"] = (stamp or {}).get("stamp") or ""
    view["live"] = bool((stamp or {}).get("live"))
    out = {"ok": ok, "said": said, "error": error, "case": view}
    if test is not None:
        out["test"] = [{"id": r["id"], "goes": r["goes"], "words": r["words"], "why": r["why"]}
                       for r in test["rows"]]
    return _page(answer(out, status=200 if ok else 400))


def _case_view(desk, me, key: str) -> dict | None:
    """What the case page draws: the desk's view of it, and its trace for debugging."""
    from rouh import case_trace

    view = desk.view(me, key)
    if view is None:
        return None
    case = view["case"]
    trace = case_trace.build(case, desk.store, contact_now=view["contact"],
                             working=view["working"], state=view["state"])
    view["files"] = case_trace.files_read(case, trace)
    from rouh.mail_cases import case_path
    for one in view["files"]:
        one["url"] = (f"{case_path(case.key)}/attachment/{quote(one['part'])}"
                      if view["channel"] == "email" and one["part"] else "")
    went = {one["went"] for one in view["files"]}
    view["files_note"] = (case_trace.files_went_said(view["files"]) if len(went) == 1
                          else "")
    view["files_known"] = "attachments" in (case.email or {})
    for a in view["earlier_attempts"]:
        a["end_said"] = case_trace.attempt_end(a)
    view["log_groups"] = case_trace.attempts_on_passes(
        trace["flow"], trace["steps"], view["earlier_attempts"], case.attempt_no, view["events"])
    view["fixes"] = _fix_views(me, case, trace["steps"])
    view.update(_fix_context(view["fixes"]))
    view["follow_pill"] = _follow_pill(view["fixes"], view.get("follow"))
    view["mark_default"] = trace["diagnosis"].get("step") or trace["flow"].get("current") or ""
    view.update(trace=trace, steps=trace["steps"], flow=trace["flow"],
                diagnosis=trace["diagnosis"], notes=trace["notes"],
                glossary=case_trace.GLOSSARY,
                verdicts=desk.VERDICTS, earlier=trace["diagnosis"]["earlier"],
                dark_only=True, questions=[n for n in trace["notes"] if n["kind"] == "question"],
                tuning=[n for n in trace["notes"] if n["kind"] != "question"],
                glossary_json=json.dumps(case_trace.GLOSSARY))
    return view


def _case_of(desk, me, key: str):
    return desk.store.by_key(me.user_id, me.org_id, key)


def _fix_views(me, case, steps: list[dict] | None = None) -> list[dict]:
    """The case's fixes as the page draws them, each also put on the step it is about."""
    from rouh import case_fixes

    fixes = case_fixes.views_for(me, case)
    for step in steps or []:
        ids = {step["id"], *([step["decision_step"]["id"]] if step.get("decision_step") else [])}
        # The newest fix of the step only: the panel at the top keeps the rest.
        step["fixes"] = [f for f in fixes if f["step"] in ids][:1]
    return fixes


def _fix_context(fixes: list[dict]) -> dict:
    """What the page needs besides the fixes: the newest of each step for Fix's own lines,
    whether any is going, and whether one ended in the last day, which opens their section."""
    import time

    lines, seen = [], set()
    for f in fixes:
        if f["step"] not in seen:
            seen.add(f["step"])
            lines.append(f)
    return {"fix_lines": lines, "fixes_live": any(f["live"] for f in fixes),
            "fixes_just": any(time.time() - f["ended_at"] < 86400 for f in fixes)}


def _follow_pill(fixes: list[dict], follow: dict | None) -> dict | None:
    """The pill of Sent back to be fixed: a fix going first, then the work sent back, then
    how the newest fix ended."""
    if any(f["tone"] == "run" and f["pill"] != "Re-running" for f in fixes):
        return {"text": "A run is fixing a check", "tone": "busy"}
    if any(f["live"] for f in fixes):
        return {"text": "Re-running this case", "tone": "busy"}
    if follow:
        return {"text": follow["label"], "tone": follow["pill"]}
    return {"text": fixes[0]["pill"], "tone": fixes[0]["tone"]} if fixes else None


@only("GET")
async def case_fixes(request: HttpRequest, key: str):
    """The case's fixes, drawn again for the page while one is going (`rouh/case_fixes.py`).

    Answers the panel at the top and the line at each step, as HTML the page swaps in, and
    whether anything is still going, so the page knows to keep asking.
    """
    from django.template.loader import render_to_string

    from rouh import case_fixes as fixes_of

    me = await sync_to_async(who)(request)
    desk = _desk()
    if me is None or desk is None:
        return JsonResponse({"error": "Not signed in."}, status=403)
    case = await sync_to_async(_case_of)(desk, me, key)
    if case is None:
        return JsonResponse({"error": "There is no such case."}, status=404)
    rows = await sync_to_async(fixes_of.of_case)(me, case.id)
    for row in rows:
        if fixes_of.live(row):
            await fixes_of.settle_one(row.id, desk)
    case = await sync_to_async(_case_of)(desk, me, key)
    fixes = await sync_to_async(_fix_views)(me, case)
    from rouh.mail_cases import _follow_view, _noun, case_path

    def draw():
        top = render_to_string("rouh/_case_fix.html",
                               {"fixes": fixes, "path": case_path(key), "noun": _noun(case),
                                "follow": _follow_view(case)},
                               request=request)
        by_step: dict[str, list] = {}
        for f in fixes:
            by_step.setdefault(f["step"], [f])
        steps = {sid: render_to_string("rouh/_case_fix_step.html", {"fixes": fs})
                 for sid, fs in by_step.items()}
        lines = render_to_string("rouh/_case_fix_step.html",
                                 {"fixes": _fix_context(fixes)["fix_lines"]})
        return top, steps, lines

    top, steps, lines = await sync_to_async(draw)()
    live = any(f["live"] for f in fixes)
    pill = _follow_pill(fixes, await sync_to_async(_follow_view)(case))
    return _page(JsonResponse({"live": live, "top": top, "steps": steps, "lines": lines,
                               "pill": pill}))


@only("POST")
async def case_fix(request: HttpRequest, key: str, fix_id: int, act: str):
    """Stop a fix's run, or undo the fix (`case_fixes.stop`, `case_fixes.undo`)."""
    from rouh import case_fixes as fixes_of
    from rouh.mail_cases import case_path

    path = case_path(key)
    me = await sync_to_async(who)(request)
    if me is None:
        return _login(path)
    desk = _desk()
    case = await sync_to_async(_case_of)(desk, me, key) if desk is not None else None
    row = await sync_to_async(fixes_of.get)(me, fix_id) if case is not None else None
    if row is None or row.case_id != case.id:
        return HttpResponse("There is no such fix.", status=404,
                            content_type="text/plain; charset=utf-8")
    try:
        if act == "stop":
            said = await fixes_of.stop(me, fix_id)
        elif act == "undo":
            said = await fixes_of.undo(me, fix_id)
        else:
            return HttpResponse("Stop or undo.", status=404,
                                content_type="text/plain; charset=utf-8")
    except (fixes_of.Refused, LookupError) as exc:
        return HttpResponseRedirect(_framed(path, bad=str(exc)).url + "#followUp")
    log.info("user %s pressed %s on fix %s of case %s", me.user_id, act, fix_id, key[:6])
    return HttpResponseRedirect(_framed(path, said=said).url + "#followUp")


@only("GET")
async def case_request(request: HttpRequest, key: str, request_id: int):
    """One model request of a case's own chat, whole, for reading its prompts."""
    from rouh import case_trace

    me = await sync_to_async(who)(request)
    desk = _desk()
    if me is None or desk is None:
        return JsonResponse({"error": "Not signed in."}, status=403)
    case = await sync_to_async(_case_of)(desk, me, key)
    got = await sync_to_async(case_trace.request_for)(case, request_id) if case else None
    if got is None:
        return JsonResponse({"error": "There is no such request in this case."}, status=404)
    response = JsonResponse(got, json_dumps_params={"ensure_ascii": False})
    return _page(response)


@only("POST")
async def case_ask(request: HttpRequest, key: str):
    """A question about a case, answered with its whole trace, and kept on the case."""
    from rouh import case_trace, runtime

    me = await sync_to_async(who)(request)
    desk = _desk()
    if me is None or desk is None:
        return JsonResponse({"error": "Not signed in."}, status=403)
    try:
        asked = json.loads(request.body or b"{}")
    except ValueError:
        asked = {}
    question = " ".join(str(asked.get("question") or "").split())[:2000]
    if not question:
        return JsonResponse({"error": "Ask something first."}, status=400)
    case = await sync_to_async(_case_of)(desk, me, key)
    if case is None:
        return JsonResponse({"error": "There is no such case."}, status=404)
    trace = await sync_to_async(lambda: case_trace.build(
        case, desk.store, contact_now=desk.contact_of(me, case)))()
    try:
        said = await case_trace.answer(runtime.config, me, case, trace, question)
    except Exception as exc:  # noqa: BLE001 - said on the page, in words
        log.exception("answering a question on case %s failed", case.id)
        return JsonResponse({"error": f"No answer came back: {exc}"[:400]}, status=502)
    await sync_to_async(desk.store.note)(me.user_id, me.org_id, case.id, "question",
                                         step=str(asked.get("step") or "")[:80],
                                         text=question, answer=said)
    return JsonResponse({"answer": said})


#: What an attachment opened from a case may do in the browser. `sandbox` without
#: allow-same-origin gives it an origin of its own that is nobody's, so whatever is
#: in it never runs as Rouh: it cannot read Rouh's cookies or pages, post a form, or
#: fetch, send or connect anywhere (`default-src 'none'`). Its own script may run in
#: there, because a web page someone made often draws itself with one (a contact's
#: plan, 8 October 2026, shows one of its nine pages without it), and it
#: may draw its pictures, styles and fonts; a link it opens in a new tab leaves the
#: sandbox, as any link to the web would.
ATTACHMENT_CSP = ("sandbox allow-scripts allow-popups allow-popups-to-escape-sandbox; "
                  "default-src 'none'; script-src 'unsafe-inline' 'unsafe-eval' https:; "
                  "style-src 'unsafe-inline' https:; img-src * data: blob:; "
                  "font-src * data:; media-src * data: blob:")


@only("GET")
async def case_attachment(request: HttpRequest, key: str, part: str):
    """One file the email of a case brought, from Gmail, for its own person only.

    Petar, 8 October 2026: each file on the case page opens in a new tab, a
    PDF, a web page, a picture or anything else, and what a browser cannot
    show it saves. Inline under the file's own name, with its type as the email
    said it and never sniffed; a PDF is left to the browser's own viewer, and
    everything else is sandboxed (`ATTACHMENT_CSP`), an HTML file above all.
    """
    from django.utils.http import content_disposition_header

    from rouh import mail_cases

    me = await sync_to_async(who)(request)
    if me is None:
        return _login(f"{mail_cases.case_path(key)}/attachment/{quote(part)}")
    desk = _desk()
    if desk is None:
        return HttpResponse("New mail is not handled on this server.", status=404,
                            content_type="text/plain; charset=utf-8")
    got, why = await desk.attachment(me, key, part)
    if got is None:
        return HttpResponse(why, status=404, content_type="text/plain; charset=utf-8")
    media = str(got.get("type") or "").split(";")[0].strip().lower()
    if not media or "/" not in media or any(c in media for c in " \r\n,\""):
        media = "application/octet-stream"
    response = HttpResponse(got["data"], content_type=media)
    response["Content-Disposition"] = content_disposition_header(
        bool(request.GET.get("download")), got["name"])
    response["X-Content-Type-Options"] = "nosniff"
    response["Referrer-Policy"] = "no-referrer"
    response["Cross-Origin-Resource-Policy"] = "same-origin"
    if media != "application/pdf":
        response["Content-Security-Policy"] = ATTACHMENT_CSP
    response["X-Frame-Options"] = "SAMEORIGIN"
    return _page(response)


def _case_file(desk, me, key: str, file_id: str):
    """(the case, the file) one of its reply files names, or (case, None).

    Looked for among what the reply carries, what Petar was asked about and
    what went, by the first 16 characters of its hash; only a file that still
    hashes the same is served, so the page never shows one thing and approves
    another.
    """
    from rouh import case_files

    case = desk.store.by_key(me.user_id, me.org_id, key)
    if case is None or len(file_id) != 16:
        return case, None
    pools = [case.reply_files or [], case.approved_files or []]
    pools += [a.files or [] for a in desk.store.approvals(me.user_id, me.org_id, case.id)]
    for pool in pools:
        for one in pool:
            if isinstance(one, dict) and str(one.get("sha256") or "")[:16] == file_id:
                state = case_files.now([one])[0]
                if state["missing"] or state["changed"]:
                    continue
                return case, one
    return case, None


@only("GET")
async def case_file(request: HttpRequest, key: str, file_id: str, page: int = 0):
    """One file a case's reply carries, or one drawn page of it, for its own person only."""
    from django.http import FileResponse

    from rouh import case_files, mail_cases

    me = await sync_to_async(who)(request)
    if me is None:
        return _login(mail_cases.case_path(key))
    desk = _desk()
    if desk is None:
        return HttpResponse("New mail is not handled on this server.", status=404,
                            content_type="text/plain; charset=utf-8")
    case, one = await sync_to_async(_case_file)(desk, me, key, file_id)
    if case is None:
        return HttpResponse("There is no such case.", status=404,
                            content_type="text/plain; charset=utf-8")
    if one is None:
        return HttpResponse("That file is not on this case as it was shown: it changed or "
                            "is gone. Open the case again to see it as it is now.", status=410,
                            content_type="text/plain; charset=utf-8")
    if page:
        drawn = await sync_to_async(case_files.page_file)(one, key, page)
        if drawn is None:
            return HttpResponse("There is no such page.", status=404,
                                content_type="text/plain; charset=utf-8")
        response = FileResponse(open(drawn, "rb"), content_type="image/png")
    else:
        response = FileResponse(open(one["path"], "rb"),
                                content_type=one.get("type") or "application/octet-stream",
                                as_attachment=bool(request.GET.get("download")),
                                filename=one.get("name") or "attachment")
    response["X-Content-Type-Options"] = "nosniff"
    if not page and (one.get("kind") not in ("pdf", "image")):
        # Never run as a page of this site, whatever is in it.
        response["Content-Security-Policy"] = "sandbox"
    response["X-Frame-Options"] = "SAMEORIGIN"
    return _page(response)
