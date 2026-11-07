"""The Rules page: every rule Rouh follows - for everything, and for a person, task or project - in groups
in three sections, each with its switch, its group, where it came from, whether it is one of the defaults
every Rouh gets (who it is for: Creator only or Rouh instances), whether it is Useful to others,
and when it is told.

    GET  /api/rules                 everything on the page: {"rows": [...], "groups": [...], ...}
    POST /api/rules/add             {"text", "for": [{type, id, name}], "group"?}: a new rule
    POST /api/rules/edit            {"ref", "text"?, "silos"?, "mode"?, "defaults"?, "useful"?}: reword one;
                                    `mode` keeps it to written replies ("text"), spoken ones ("voice"), or every
                                    reply (""), `defaults` sets who it is for (true: Rouh instances, false:
                                    Creator only), and `useful` its label
    POST /api/rules/useful          {"ref", "on"}: mark a rule for its creator alone as useful to others
    POST /api/rules/standard        {"ref"}: Make standard - a Useful rule becomes one for every Rouh instance
    POST /api/rules/delete          {"ref"}: a rule
    POST /api/rules/enable          {"ref", "on"}: turn one off or on
    POST /api/rules/switch          {"ref", "which": "chat" | "agent", "on"}: one of its two switches, Chat (told in
                                    chats) and Agent (told to every agent Rouh starts); both off is turned off
    POST /api/rules/group           {"ref", "group"}: move one to another group by hand
    POST /api/rules/restore         {"ref", "change"}: the words one had after an entry of its history
    GET  /api/rules/history?ref=    what was done to one, newest first
    POST /api/rules/apply           {"fact", "home", "text", "for", "term", "meaning"}: move one old fact
    GET  /api/rules/targets?q=      people, tasks and projects a rule can be for
    GET  /api/rules/told[?id=][&chat=]     the person's latest conversation requests; with an id, what that
                                    request was told, stretch by stretch, checked against what it sent

A rule is named by its `ref` (`rules._ref`): "r:<id>". The person's words were here as "w:<key>" until 30 October
2026, and are Vocabulary in Synapse Master since (`rouh/vocabulary.py`, `rouh/web/vocabulary.py`). Every rule is
equal since 30 October 2026: until then Rouh's own were "built-in", "b:<key>", kept apart and twenty locked on.

It was the Memory page (`/api/memory`) until 5 October 2026, when the memory became rules, words and
notes in Synapse Master (`rouh/rules.py`). Its card of rules said in a conversation, waiting for the
person, was taken out on 6 October 2026 (`ingest.write_rules`). Until 29 October 2026 it was four cards by
where a rule was kept, each with rows of its own design, and the built-in rules had endpoints of their own
(`/api/rules/builtin/*`). Every write answers with the whole page again, so what is drawn is what is kept.
Whose: the signed-in person's Master (`Tenancy.current`, via `who`).
"""
from __future__ import annotations

import logging
import time

from asgiref.sync import sync_to_async
from django.http import HttpRequest

from .common import answer, body_of, only, refuse, who

log = logging.getLogger(__name__)

NO_STORE = {"Cache-Control": "no-store"}


def _page(me) -> dict:
    from rouh import agent_instructions, rule_groups, ruledefaults, rules, silos, vocabulary

    ds = rules.master(me.user_id, me.org_id)
    # The person's old words, moved by what each does before the page is drawn without them.
    vocabulary.settle(ds)
    # The defaults every Rouh starts with are on the page before the first turn has taken them in.
    ruledefaults.ensure(ds)
    # And the agent instructions, which are rules here since 30 October 2026, before the first agent starts.
    try:
        agent_instructions.move_to_rules(me.org_id)
    except Exception:  # noqa: BLE001 - the page is still drawn; the next run's start moves them
        log.exception("the agent instructions could not be moved to the Rules page")
    # Every rule kept before its group and origin were written down gets them, once.
    rules.settle(ds)
    rows = rules.page_rows(ds, me.org_id)
    # Each group with the sentence its (i) says: when its rules are told to a model (`rules.included_said`).
    groups = [{**g, "included": rules.included_said([r for r in rows if r["group"] == g["key"]])}
              for g in rule_groups.listing()]
    return {"rows": rows, "groups": groups, "sections": rule_groups.sections(), "old": rules.old_facts(),
            "master": ds["name"], "silos": [s.chip() for s in silos.of(me.user_id, me.org_id)]}


async def _me(request):
    return await sync_to_async(who)(request)


async def _answer(me, **extra):
    return answer({**extra, **(await sync_to_async(_page)(me))}, headers=NO_STORE)


@only("GET")
async def page(request: HttpRequest):
    me = await _me(request)
    if me is None:
        return refuse("sign in", 401)
    return await _answer(me)


def _by(request) -> str:
    name = getattr(getattr(request, "user", None), "username", "") or "someone"
    return f"{name} on the Rules page"


def _do(me, what, body, by):
    from rouh import rules

    ds = rules.master(me.user_id, me.org_id)
    here = rules.origin_of("manual", f"Added by you on the Rules page, {rules._day(time.time())}.")
    if what == "add":
        return rules.add_rule(ds, body.get("text") or "", body.get("for") or [], by="the Rules page", origin=here,
                              group=str(body.get("group") or ""))
    if what == "apply":
        return rules.apply_fact(int(body.get("fact") or 0), body, user_id=me.user_id, org_id=me.org_id)
    kind, ident = rules._ref(str(body.get("ref") or ""))
    if what == "edit":
        got = rules.edit_rule(ds, ident, body.get("text") or "", by="the Rules page",
                              silos=body.get("silos") if isinstance(body.get("silos"), list) else None,
                              mode=body.get("mode") if isinstance(body.get("mode"), str) else None)
        if got is not None and isinstance(body.get("defaults"), bool) and body["defaults"] != got["defaults"]:
            rules.set_defaults(ds, f"r:{ident}", body["defaults"], by=by)
        if (got is not None and isinstance(body.get("useful"), bool) and not body.get("defaults")
                and body["useful"] != got["useful"]):
            rules.set_useful(ds, f"r:{ident}", body["useful"], by=by)
        # Its group, when Save carried a different one: moved by hand, and kept there.
        group = str(body.get("group") or "")
        if got is not None and group and group != _group_of(ds, me.org_id, f"{kind}:{ident}"):
            rules.set_group(ds, me.org_id, f"{kind}:{ident}", group, by=by)
        return got
    if what == "delete":
        return rules.delete_rule(ds, ident, by="the Rules page")
    if what == "enable":
        return rules.set_on(ds, me.org_id, body["ref"], bool(body.get("on")), by=by)
    if what == "switch":
        return rules.set_switch(ds, body["ref"], str(body.get("which") or ""), bool(body.get("on")), by=by)
    if what == "group":
        return rules.set_group(ds, me.org_id, body["ref"], str(body.get("group") or ""), by=by)
    if what == "useful":
        return rules.set_useful(ds, body["ref"], bool(body.get("on")), by=by)
    if what == "standard":
        return rules.make_standard(ds, body["ref"], by=by)
    if what == "restore":
        return rules.restore(ds, me.org_id, body["ref"], str(body.get("change") or ""), by=by)
    raise ValueError(what)


def _group_of(ds, org_id: str, ref: str) -> str:
    from rouh import rules

    return next((r["group"] for r in rules.page_rows(ds, org_id) if r["ref"] == ref), "")


def _post(what: str):
    @only("POST")
    async def view(request: HttpRequest):
        me = await _me(request)
        if me is None:
            return refuse("sign in", 401)
        try:
            got = await sync_to_async(_do)(me, what, body_of(request), _by(request))
        except (ValueError, LookupError) as exc:
            return refuse(str(exc), 400, **(await sync_to_async(_page)(me)))
        if got is None or got is False:
            return refuse("That is not there any more.", 404, **(await sync_to_async(_page)(me)))
        return await _answer(me, ok=True)
    return view


add = _post("add")
edit = _post("edit")
delete = _post("delete")
enable = _post("enable")
switch = _post("switch")
group = _post("group")
restore = _post("restore")
apply = _post("apply")
useful = _post("useful")
standard = _post("standard")


@only("GET")
async def targets(request: HttpRequest):
    from rouh import rules

    me = await _me(request)
    if me is None:
        return refuse("sign in", 401)
    got = await sync_to_async(rules.targets)(request.GET.get("q", ""), user_id=me.user_id, org_id=me.org_id)
    return answer({"targets": got}, headers=NO_STORE)


@only("GET")
async def history(request: HttpRequest):
    from rouh import rules

    me = await _me(request)
    if me is None:
        return refuse("sign in", 401)

    def got():
        return rules.history(rules.master(me.user_id, me.org_id), me.org_id, request.GET.get("ref", ""))

    try:
        out = await sync_to_async(got)()
    except (ValueError, LookupError) as exc:
        return refuse(str(exc), 404)
    return answer({"history": out}, headers=NO_STORE)


@only("GET")
async def told(request: HttpRequest):
    """The person's own requests only: another person's, or another organisation's, is "not found"."""
    from rouh import prompting

    me = await _me(request)
    if me is None:
        return refuse("sign in", 401)
    ident = request.GET.get("id", "").strip()
    if not ident:
        got = await sync_to_async(prompting.recent)(me.org_id, me.user_id, chat=request.GET.get("chat", ""))
        return answer({"requests": got}, headers=NO_STORE)
    try:
        got = await sync_to_async(prompting.told)(me.org_id, me.user_id, ident)
    except LookupError as exc:
        return refuse(str(exc), 404)
    return answer({"told": got}, headers=NO_STORE)
