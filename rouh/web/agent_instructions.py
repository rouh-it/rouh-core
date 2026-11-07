"""What every agent Rouh starts is told, and the address a starting run reads it from.

    GET  /api/agent-instructions                  the rules every agent is told, under their headings
    POST /api/agent-instructions/add              {"title", "text", "group"}: a rule with its Agent switch on
    GET  /api/agent-instructions/preview          {"text"}: exactly what an agent starts with
    GET  /api/agent-instructions/issued[?id=]     the latest runs and what each was given

    GET  /internal/agent-instructions?run=&via=&task=   this machine only: the text for a run
                                                        that is starting, written down against it

Until 30 October 2026 these were the addresses of a page of their own, Agent instructions, where
the statements were kept. Since then every one is a rule on the Rules page, whose Agent switch says
whether agents are told it (`rouh/agent_instructions.py`, `rouh/rules.py`), and `/agent-instructions`
opens the Rules page on the rules agents are told; what is left here is read by the Rules page
(`/rules/agents`), by the one program and by the stack test.
Whose: the signed-in person's organisation (`Tenancy.current`, via `who`); the internal address,
which has no person, the organisation of the one person this install has (`modeldefaults.org_now`).
"""
from __future__ import annotations

import logging

from asgiref.sync import sync_to_async
from django.http import HttpRequest
from django.views.decorators.csrf import csrf_exempt

from .common import answer, body_of, from_this_machine, only, refuse, who

log = logging.getLogger(__name__)

NO_STORE = {"Cache-Control": "no-store"}


async def _me(request):
    return await sync_to_async(who)(request)


def _page(org: str) -> dict:
    from rouh import agent_instructions as ai

    return ai.page(org)


@only("GET")
async def page(request: HttpRequest):
    me = await _me(request)
    if me is None:
        return refuse("sign in", 401)
    return answer(await sync_to_async(_page)(me.org_id), headers=NO_STORE)


@only("POST")
async def add(request: HttpRequest):
    from rouh import agent_instructions as ai

    me = await _me(request)
    if me is None:
        return refuse("sign in", 401)
    body = body_of(request)
    name = getattr(getattr(request, "user", None), "username", "") or "someone"
    try:
        await sync_to_async(lambda: ai.add(me.org_id, title=body.get("title") or "", text=body.get("text") or "",
                                           group=str(body.get("group") or ""), by=f"{name} through Rouh's API"))()
    except ValueError as exc:
        return refuse(str(exc), 400)
    return answer({"ok": True, **(await sync_to_async(_page)(me.org_id))}, headers=NO_STORE)


@only("GET")
async def preview(request: HttpRequest):
    from rouh import agent_instructions as ai

    me = await _me(request)
    if me is None:
        return refuse("sign in", 401)
    text = await sync_to_async(ai.block)(me.org_id)
    return answer({"text": text, "chars": len(text), "fingerprint": ai.fingerprint(text)}, headers=NO_STORE)


@only("GET")
async def issued(request: HttpRequest):
    from rouh import agent_instructions as ai

    me = await _me(request)
    if me is None:
        return refuse("sign in", 401)
    one = request.GET.get("id")
    if one:
        got = await sync_to_async(ai.issued_text)(me.org_id, one)
        if got is None:
            return refuse("That is not there.", 404)
        return answer(got, headers=NO_STORE)
    return answer({"issued": await sync_to_async(ai.issued)(me.org_id)}, headers=NO_STORE)


def _for_a_run(run: str, via: str, task: str) -> str:
    from rouh import agent_instructions as ai
    from rouh.modeldefaults import org_now

    return ai.issue(org_now(), run_id=run, via=via, task=task)


@csrf_exempt
@only("GET")
async def internal(request: HttpRequest):
    """A run starting on this machine: the text it begins with (`one/runs.py`)."""
    if not from_this_machine(request):
        return answer({"ok": False, "error": "Only this machine may use this address."}, status=403)
    run = str(request.GET.get("run") or "")[:80]
    via = str(request.GET.get("via") or "")[:60]
    task = str(request.GET.get("task") or "")[:200]
    try:
        text = await sync_to_async(_for_a_run)(run, via, task)
    except Exception as exc:  # noqa: BLE001 - said to the program, which starts the run anyway
        log.exception("the agent instructions for run %s could not be made", run)
        return answer({"ok": False, "error": f"The agent instructions could not be read: {exc}"},
                      status=500)
    return answer({"ok": True, "text": text}, headers=NO_STORE)
