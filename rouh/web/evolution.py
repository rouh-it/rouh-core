"""Evolution over the web: Parameters and Mutations (`rouh/evolution.py`, `evolutionpage.js`).

Every route answers the signed-in person about their own rows only: Mutations' genes, events,
mutation requests and questions are looked up by id together with their organisation and account,
so an id of anybody else's is "not found".

    GET  /api/evolution/parameters              Parameters, and when the next night reads them
    POST /api/evolution/parameters              {total, invisible, shows_up, ask_for, changes_work},
                                                or {trial: {days?, needed?, counts?}}: a new trial's defaults,
                                                or {guide: "..."}: the guiding prompt, saved at once, and
                                                the Incubator scored again with it when it changed
    GET  /api/evolution/mutations               every gene in its view, the questions
    GET  /api/evolution/month                   the month view: the last thirty days
    GET  /api/evolution/genes/<id>              one gene, all five tabs
    POST /api/evolution/genes/<id>/answer       {answer, at?, reason?}: reject also takes its code out
    POST /api/evolution/genes/<id>/trial        {days?, needed?, counts?}: its trial, saved at once
    POST /api/evolution/genes/<id>/mutate       {words}: kept, and its run started at once
    POST /api/evolution/mutations/<id>          {words}, {withdraw: true} or {start: true}
    POST /api/evolution/genes/<id>/ask          {question, topic?}
    POST /api/evolution/genes/<id>/question     {day, pick}: the day-2 or day-7 question
    POST /api/evolution/switches                {name, on}: one of Other switches, which no gene
                                                has, on or off
"""
from __future__ import annotations

import logging

from asgiref.sync import sync_to_async
from django.http import HttpRequest, HttpResponseNotAllowed

from rouh import evolution, gene_questions, genepool
from rouh.config import config

from .comments import NO_STORE
from .common import answer, body_of, refuse, who

log = logging.getLogger("rouh.web.evolution")


async def _me(request: HttpRequest):
    return await sync_to_async(who)(request)


def _said_by(me) -> str:
    return (getattr(me, "name", "") or getattr(me, "email", "") or "you") + ", in Parameters"


async def parameters(request: HttpRequest):
    me = await _me(request)
    if me is None:
        return refuse("Sign in to Rouh first.", 401)
    rescored = None
    if request.method == "POST":
        body = body_of(request)
        try:
            if isinstance(body, dict) and "trial" in body:
                await sync_to_async(evolution.put_trial_defaults)(me, body["trial"])
            elif isinstance(body, dict) and "guide" in body:
                before = await sync_to_async(evolution.guide_text)(me)
                await sync_to_async(evolution.put_guide)(me, body["guide"], by=_said_by(me))
                if (await sync_to_async(evolution.guide_text)(me)) != before:
                    rescored = await _rescore(me)
            else:
                await sync_to_async(evolution.put_parameters)(me, body, by=_said_by(me))
        except evolution.Refused as exc:
            return refuse(str(exc), 400)
    elif request.method not in ("GET", "HEAD"):
        return HttpResponseNotAllowed(["GET", "POST"])
    got = await sync_to_async(evolution.parameters)(me)
    when = await sync_to_async(evolution.schedule)(me)
    from rouh import genedraft
    drafts = {"value": await sync_to_async(genedraft.propose)(me), "choices": genedraft.PROPOSE,
              "on": await sync_to_async(genedraft.on)(str(me.org_id))}
    return answer({"parameters": got, "schedule": when, "most": evolution.MOST, "drafts": drafts,
                   "defaults": evolution.DEFAULTS,
                   "guide": await sync_to_async(evolution.guide)(me), "guide_start": evolution.GUIDE_START,
                   "guide_most": evolution.GUIDE_MOST, "rescored": rescored,
                   "trial": await sync_to_async(evolution.trial_defaults)(me),
                   "trial_defaults": evolution.TRIAL_DEFAULTS,
                   "trial_most_days": evolution.TRIAL_MOST_DAYS, "needed_most": evolution.NEEDED_MOST,
                   "kinds": [{"id": k, "name": evolution.KIND_NAMES[k], "said": evolution.KIND_SAID[k]}
                             for k in evolution.KINDS]}, headers=NO_STORE)


async def _rescore(me) -> int | None:
    """The Incubator's ideas scored again, in the background, so a new guiding prompt reaches every
    idea's score and not only the next one's. How many are being scored; None when it could not start."""
    from rouh import incubator_score

    try:
        state = await incubator_score.start_all(me, force=True)
        return int(state.get("total") or 0)
    except Exception:  # noqa: BLE001 - the guidance is kept; the scores catch up on the next pass
        log.exception("the Incubator could not be scored again after a new guiding prompt")
        return None


async def mutations(request: HttpRequest):
    me = await _me(request)
    if me is None:
        return refuse("Sign in to Rouh first.", 401)
    if request.method not in ("GET", "HEAD"):
        return HttpResponseNotAllowed(["GET"])
    await sync_to_async(evolution.tick)(me)
    got = await sync_to_async(evolution.mutations)(me)
    got["pool_name"] = genepool.NAME
    words = str(request.GET.get("q") or "").strip()
    if words:
        found = {g.id for g in await sync_to_async(evolution.find_gene)(me, words)}
        got["found"] = sorted(found)
    return answer(got, headers=NO_STORE)


async def month(request: HttpRequest):
    me = await _me(request)
    if me is None:
        return refuse("Sign in to Rouh first.", 401)
    await sync_to_async(evolution.settle)(me)
    return answer(await sync_to_async(evolution.month)(me), headers=NO_STORE)


async def gene(request: HttpRequest, gene_id: int):
    me = await _me(request)
    if me is None:
        return refuse("Sign in to Rouh first.", 401)
    # A trial that is over is judged before it is shown, so the page says how it really stands.
    await sync_to_async(evolution.settle)(me)
    got = await sync_to_async(evolution.gene_page)(me, gene_id)
    if got is None:
        return refuse("There is no such gene in Mutations.", 404)
    # A notice that leads here, such as one saying it was switched off, is read once it is opened (N1).
    from rouh import notices
    await notices.settled(me, kind="rouh", link=f"/evolution/mutations/gene/{gene_id}")
    return answer(got, headers=NO_STORE)


async def _post(request: HttpRequest, act):
    me = await _me(request)
    if me is None:
        return refuse("Sign in to Rouh first.", 401)
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    try:
        return answer(await act(me, body_of(request)), headers=NO_STORE)
    except evolution.Refused as exc:
        return refuse(str(exc), 400)


async def gene_answer(request: HttpRequest, gene_id: int):
    async def act(me, body):
        at = body.get("at")
        try:
            at = float(at) if at not in (None, "") else None
        except (TypeError, ValueError):
            raise evolution.Refused("Pick when to try it.") from None
        what = str(body.get("answer") or "")
        if what == "reject":
            return await evolution.reject(me, gene_id, str(body.get("reason") or ""))
        return await sync_to_async(evolution.answer)(me, gene_id, what, at=at,
                                                     reason=str(body.get("reason") or ""))
    return await _post(request, act)


async def gene_trial(request: HttpRequest, gene_id: int):
    async def act(me, body):
        return await sync_to_async(evolution.put_trial)(me, gene_id, body)
    return await _post(request, act)


async def gene_mutate(request: HttpRequest, gene_id: int):
    async def act(me, body):
        return await evolution.mutate_now(me, gene_id, str(body.get("words") or ""))
    return await _post(request, act)


async def mutation(request: HttpRequest, mutation_id: int):
    async def act(me, body):
        if body.get("start"):
            return await evolution.start_mutation(me, mutation_id)
        return await sync_to_async(evolution.change_mutation)(
            me, mutation_id, words=body.get("words"), withdraw=bool(body.get("withdraw")))
    return await _post(request, act)


async def gene_ask(request: HttpRequest, gene_id: int):
    async def act(me, body):
        topic = body.get("topic")
        try:
            topic = int(topic) if topic else None
        except (TypeError, ValueError):
            topic = None
        try:
            return await gene_questions.ask(config, me, gene_id, str(body.get("question") or ""), topic)
        except evolution.Refused:
            raise
        except Exception as exc:  # noqa: BLE001 - said on the card, in words
            log.exception("a question on gene %s could not be answered", gene_id)
            raise evolution.Refused(f"No answer came back: {type(exc).__name__}. Ask again in a moment.") from None
    return await _post(request, act)


async def switch(request: HttpRequest):
    async def act(me, body):
        return await sync_to_async(evolution.set_switch)(me, body.get("name"), bool(body.get("on")))
    return await _post(request, act)


__all__ = ["gene", "gene_answer", "gene_ask", "gene_mutate", "gene_trial", "month", "mutation",
           "mutations", "parameters", "switch"]
