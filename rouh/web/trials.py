"""Trials' pages in Evolution, at /evolution/trials, and `rouh-trial`'s door (`rouh/trials/`).

    GET  /api/trials                          the jobs (who tried each is not said here), the counts, the testers,
                                              and the newest tries (`trials`, for a run reading the old shape)
    GET  /api/trials/jobs/<n>                 one job: its goal, what it covers, its tries newest first with who did them
    POST /api/trials/jobs/<n>                 {"name"?, "goal"?, "covers"?}: the job changed
    POST /api/trials/jobs/<n>/run             {"persona"?}: a new try of it, in a run of its own
    GET  /api/trials/<n>                      one try whole: its walk-through, step by step, its problems and ending
    GET  /api/trials/<n>/shot/<step>          one step's screenshot
    POST /api/trials/<n>/again                the same try again, by a new tester, in a run of its own (a review)
    POST /api/trials/<n>/fix                  a review's Fix the ones I chose: one run fixes what the owner decided
    POST /api/trials/new                      {"page", "goal", "persona"?, "subject"?}: a try by hand
    GET  /api/trials/problems                 the list: ?status=open|decided|fixed|set_aside|all&source=persona|owner
                                              &persona=vesela&job=3&screen=/x, open first, the worst first
    GET  /api/trials/problems/<n>             one problem, with every sighting and its discussion
    POST /api/trials/problems/<n>/say         {"text"}: the owner writes in its thread, and Rouh answers there
    POST /api/trials/problems/<n>/verdict     {"verdict", "decision"?, "feedback"?}: not a problem, won't fix,
                                              decided (fix it like this), sent as feedback, or "" to take it back
    GET  /api/trials/problems/<n>/report      the problem as a report for Gene therapy
    GET  /api/trials/testers                  every tester (?archived=1 with the removed ones)
    GET  /api/trials/testers/<key>            one tester whole: their profile in sections, and their tries
    POST /api/trials/testers/new              a new tester from the form
    POST /api/trials/testers/draft            {"sentence"}: a whole tester written by Rouh, to change before saving
    POST /api/trials/testers/<key>            a tester changed
    POST /api/trials/testers/<key>/remove     a tester taken off the list (kept, so old tries say who did them)
    POST /api/trials/testers/<key>/default    the tester who tries every change
    POST /api/trials/testers/<key>/pause      {"on": true|false}: pause or resume one tester, at once
    POST /api/trials/pause                    {"on": true|false}: the switch that pauses every tester

    POST /internal/trials                     the same from a run on this machine or in the worker
                                              (`bin/rouh-trial`)

Only the signed-in person's own, asked for by their organisation and account together.
"""
from __future__ import annotations

import asyncio
import logging

from django.http import FileResponse, HttpRequest
from django.views.decorators.csrf import csrf_exempt

from .common import answer, body_of, from_this_machine, only, refuse, who

log = logging.getLogger(__name__)
NO_STORE = {"Cache-Control": "no-store"}


async def _me(request):
    return await asyncio.to_thread(who, request)


def _owner_name(me) -> str:
    try:
        from rouh import owner

        o = owner.resolve(me)
        return (o.name if o else "") or "You"
    except Exception:  # noqa: BLE001 - a name on the page is never worth the page
        return "You"


def _everything(me, g=None) -> dict:
    from rouh import trials

    g = g or {}
    return {"ok": True, "jobs": trials.jobs(me, tester=g.get("persona", ""), result=g.get("result", "")),
            # Forty of the newest tries: enough for the Atlas's latest row, its week of bars and each job's
            # newest try against its one before (`trialspage.js`, the Page atlas design, 7 November 2026).
            "trials": trials.listing(me, limit=40), "counts": trials.counts(me), "personas": trials.personas(me),
            "testers": trials.testers(me), "paused_all": trials.paused_all(me) is not None,
            "default": trials.default_persona(me), "owner": _owner_name(me),
            "rounds": trials.ROUNDS, "verdicts": trials.VERDICTS}


@only("GET")
async def listing(request: HttpRequest):
    me = await _me(request)
    if me is None:
        return refuse("Sign in first.", 401)
    try:
        got = await asyncio.to_thread(_everything, me, dict(request.GET.items()))
    except trials_refused() as exc:
        return refuse(str(exc), 400)
    return answer(got, headers=NO_STORE)


@only("GET")
async def trial(request: HttpRequest, number: int):
    from rouh import trials

    me = await _me(request)
    if me is None:
        return refuse("Sign in first.", 401)
    try:
        got = await asyncio.to_thread(trials.one, me, number)
    except trials.NotFound as exc:
        return refuse(str(exc), 404)
    return answer({"ok": True, "trial": got, "owner": _owner_name(me), "rounds": trials.ROUNDS,
                   "personas": await asyncio.to_thread(trials.personas, me), "names": trials.HOW_BAD_NAMES},
                  headers=NO_STORE)


@only("GET")
async def shot(request: HttpRequest, number: int, step: int):
    from rouh import trials

    me = await _me(request)
    if me is None:
        return refuse("Sign in first.", 401)
    try:
        path = await asyncio.to_thread(trials.shot_path, me, number, step)
    except trials.NotFound as exc:
        return refuse(str(exc), 404)
    if path is None:
        return refuse("That step has no picture.", 404)
    out = FileResponse(open(path, "rb"), content_type="image/jpeg")
    out["Cache-Control"] = "private, max-age=86400"
    return out


@only("POST")
async def again(request: HttpRequest, number: int):
    from rouh import trials

    me = await _me(request)
    if me is None:
        return refuse("Sign in first.", 401)
    b = body_of(request)
    try:
        got = await trials.run_by_hand(me, again=number, persona_id=str(b.get("persona") or ""))
    except trials.Refused as exc:
        return refuse(str(exc), 404 if isinstance(exc, trials.NotFound) else 400)
    return answer({"ok": True, "trial": got, "said": got.get("said", "")}, headers=NO_STORE)


@only("POST")
async def new(request: HttpRequest):
    from rouh import trials

    me = await _me(request)
    if me is None:
        return refuse("Sign in first.", 401)
    b = body_of(request)
    try:
        got = await trials.run_by_hand(me, persona_id=str(b.get("persona") or ""), goal=str(b.get("goal") or ""),
                                       page=str(b.get("page") or ""), subject=str(b.get("subject") or ""))
    except trials.Refused as exc:
        return refuse(str(exc), 400)
    return answer({"ok": True, "trial": got, "said": got.get("said", "")}, headers=NO_STORE)


@only("GET")
async def problems(request: HttpRequest):
    from rouh import trials

    me = await _me(request)
    if me is None:
        return refuse("Sign in first.", 401)
    g = request.GET
    try:
        got = await asyncio.to_thread(lambda: {
            "ok": True, "problems": trials.problems(me, status=g.get("status", ""), source=g.get("source", ""),
                                                    persona_id=g.get("persona", ""), screen=g.get("screen", ""),
                                                    job=g.get("job") or None),
            "counts": trials.counts(me), "screens": trials.screens(me), "personas": trials.personas(me),
            "testers": trials.testers(me, archived=True), "jobs": [{"number": j["number"], "name": j["name"]}
                                                                    for j in trials.jobs(me)],
            "owner": _owner_name(me), "names": trials.HOW_BAD_NAMES, "verdicts": trials.VERDICTS})
    except trials.Refused as exc:
        return refuse(str(exc), 400)
    return answer(got, headers=NO_STORE)


def trials_refused():
    from rouh import trials

    return trials.Refused


async def _do(request, fn, *, status_for_missing: int = 404):
    """Sign-in, then `fn(me, body)` in a thread, and its answer or its refusal said plainly."""
    from rouh import trials

    me = await _me(request)
    if me is None:
        return refuse("Sign in first.", 401)
    b = body_of(request) if request.method == "POST" else dict(request.GET.items())
    try:
        got = await fn(me, b)
    except trials.Refused as exc:
        return refuse(str(exc), status_for_missing if isinstance(exc, trials.NotFound) else 400)
    return answer({"ok": True, **got}, headers=NO_STORE)


def _sync(fn):
    """A blocking function, run in a thread when `_do` awaits it."""
    async def run(me, b):
        return await asyncio.to_thread(fn, me, b)
    return run


@only("GET", "POST")
async def one_job(request: HttpRequest, number: int):
    from rouh import trials

    if request.method == "POST":
        return await _do(request, _sync(lambda me, b: {"job": trials.edit_job(
            me, number, name=b.get("name"), goal=b.get("goal"), covers=b.get("covers"))}))
    return await _do(request, _sync(lambda me, b: {"job": trials.job(me, number), "personas": trials.personas(me),
                                                   "default": trials.default_persona(me)}))


@only("POST")
async def run_job(request: HttpRequest, number: int):
    from rouh import trials

    async def go(me, b):
        got = await trials.run_by_hand(me, persona_id=str(b.get("persona") or ""), job_no=number)
        return {"trial": got, "said": got.get("said", "")}
    return await _do(request, go)


@only("POST")
async def fix(request: HttpRequest, number: int):
    """A review's Fix the ones I chose: one run that fixes the problems the owner decided, their way."""
    from rouh import trials

    async def go(me, b):
        return await trials.fix_chosen(me, number)
    return await _do(request, go)


@only("GET")
async def one_problem(request: HttpRequest, number: int):
    from rouh import trials

    return await _do(request, _sync(lambda me, b: {"problem": trials.problem(me, number), "owner": _owner_name(me),
                                                   "names": trials.HOW_BAD_NAMES, "verdicts": trials.VERDICTS}))


@only("POST")
async def problem_say(request: HttpRequest, number: int):
    from rouh import trials

    async def go(me, b):
        return {"problem": await trials.say(me, number, str(b.get("text") or ""))}
    return await _do(request, go)


@only("POST")
async def problem_verdict(request: HttpRequest, number: int):
    from rouh import trials

    return await _do(request, _sync(lambda me, b: {"problem": trials.set_verdict(
        me, number, str(b.get("verdict") or ""), decision=str(b.get("decision") or ""),
        feedback_id=str(b.get("feedback") or ""))}))


@only("GET")
async def problem_report(request: HttpRequest, number: int):
    from rouh import trials

    def go(me, b):
        p = trials.problem(me, number)
        s = next((x for x in p.get("sightings") or [] if x.get("trial") and x.get("shot")), None)
        return {"body": trials.feedback_text(me, number),
                "shots": [f"/api/trials/{s['trial']}/shot/{s['step']}"] if s else []}
    return await _do(request, _sync(go))


@only("GET")
async def testers(request: HttpRequest):
    from rouh import trials

    return await _do(request, _sync(lambda me, b: {"testers": trials.testers(me, archived=bool(b.get("archived"))),
                                                   "default": trials.default_persona(me),
                                                   "paused_all": trials.paused_all(me) is not None,
                                                   "sections": list(trials.SECTIONS)}))


@only("GET", "POST")
async def one_tester(request: HttpRequest, key: str):
    from rouh import trials

    if request.method == "POST":
        return await _do(request, _sync(lambda me, b: {"tester": trials.edit_tester(me, key, b)}))
    return await _do(request, _sync(lambda me, b: {"tester": trials.tester_read(me, key),
                                                   "sections": list(trials.SECTIONS)}))


@only("POST")
async def new_tester(request: HttpRequest):
    from rouh import trials

    return await _do(request, _sync(lambda me, b: {"tester": trials.add_tester(
        me, b, made_by="rouh" if b.get("written_by_rouh") else "owner")}))


@only("POST")
async def draft_tester(request: HttpRequest):
    from rouh import trials

    async def go(me, b):
        return {"draft": await trials.draft_tester(me, str(b.get("sentence") or ""))}
    return await _do(request, go)


@only("POST")
async def remove_tester(request: HttpRequest, key: str):
    from rouh import trials

    return await _do(request, _sync(lambda me, b: {"tester": trials.remove_tester(me, key)}))


@only("POST")
async def default_tester(request: HttpRequest, key: str):
    from rouh import trials

    return await _do(request, _sync(lambda me, b: {"default": trials.set_default_persona(me, key)}))


def _on(b) -> bool:
    v = b.get("on", True)
    return v if isinstance(v, bool) else str(v).strip().lower() not in ("0", "false", "off", "no", "")


@only("POST")
async def pause_tester(request: HttpRequest, key: str):
    """Pause or resume one tester, at once, with no question first (Petar, 5 November 2026)."""
    from rouh import trials

    return await _do(request, _sync(lambda me, b: {"tester": trials.set_paused(me, key, _on(b))}))


@only("POST")
async def pause_all(request: HttpRequest):
    """The switch that pauses every tester at once, or lets them go again."""
    from rouh import trials

    return await _do(request, _sync(lambda me, b: {"pause": trials.set_paused(me, "", _on(b))}))


# --- rouh-trial, from a run ---------------------------------------------------------------------


def _owner():
    from rouh.tenancy import Tenancy

    return Tenancy().only_person()


@csrf_exempt
@only("GET", "POST")
async def internal(request: HttpRequest):
    """`bin/rouh-trial`: start a trial, send each step and hand back what to do, finish it, or say it broke;
    and list, read, problems, problem, record, sighting, reopen, personas, persona, default and queue, as Rouh's `trials` tool does."""
    from rouh import trials

    if not from_this_machine(request):
        return answer({"ok": False, "error": "Only this machine may use this address."}, status=403)
    me = await asyncio.to_thread(_owner)
    if me is None:
        return answer({"ok": False, "error": "This Rouh has no one person to keep trials for."}, status=400)
    b = body_of(request) if request.method == "POST" else dict(request.GET.items())
    action = str(b.get("action") or "list")
    by = " ".join(str(b.get("by") or "").split())[:120] or "a job on this machine"
    try:
        return await _internal(me, b, action, by)
    except trials.Paused as exc:
        # Not a failure: a paused tester starts nothing, and the run that asked skips its trial and carries on.
        return answer({"ok": True, "skipped": True, "result": trials.SKIPPED, "said": str(exc),
                       "tester": exc.tester, "everyone": exc.everyone})
    except trials.Refused as exc:
        return answer({"ok": False, "error": str(exc)}, status=404 if isinstance(exc, trials.NotFound) else 400)
    except Exception as exc:  # noqa: BLE001 - the run is told what went wrong, in a sentence
        log.exception("trials: %s failed", action)
        return answer({"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:300]}"}, status=500)


async def _internal(me, b, action: str, by: str):
    from rouh import trials

    if action == "start":
        got = await asyncio.to_thread(lambda: trials.start(
            me, persona_id=str(b.get("persona") or ""), goal=str(b.get("goal") or ""),
            subject=str(b.get("subject") or ""), gene=str(b.get("gene") or ""), page=str(b.get("page") or ""),
            round_no=int(b.get("round") or 1), first=b.get("first") or None, number=b.get("trial") or None,
            by=by, run_id=str(b.get("run") or ""), job_no=b.get("job_no") or None,
            job_name=str(b.get("job") or ""), mode="review" if b.get("mode") == "review" else "auto"))
        return answer({"ok": True, "trial": got, "most_steps": trials.MOST_STEPS,
                       "persona": trials.persona(me, got["persona"])})
    if action == "step":
        got = await trials.step(me, b.get("trial"), b.get("observation") or {})
        return answer(got)
    if action == "finish":
        got = await trials.finish(me, b.get("trial"), ending=b.get("ending") or None,
                                  gave_up=bool(b.get("gave_up")), why=str(b.get("why") or ""))
        return answer({"ok": True, "trial": got})
    if action == "broken":
        got = await asyncio.to_thread(trials.broken, me, b.get("trial"), str(b.get("why") or ""))
        return answer({"ok": True, "trial": got})
    if action == "list":
        got = await asyncio.to_thread(trials.listing, me, persona_id=str(b.get("persona") or ""))
        return answer({"ok": True, "trials": got, "lines": [trials.line_for_model(t) for t in got]})
    if action == "read":
        return answer({"ok": True, "trial": await asyncio.to_thread(trials.one, me, b.get("trial"))})
    if action == "problems":
        got = await asyncio.to_thread(lambda: trials.problems(
            me, status=str(b.get("status") or ""), source=str(b.get("source") or ""),
            persona_id=str(b.get("persona") or ""), screen=trials.screen_key(b["screen"]) if b.get("screen") else "",
            job=b.get("job") or None))
        return answer({"ok": True, "problems": got, "lines": [trials.problem_line(p) for p in got]})
    if action == "problem":
        return answer({"ok": True, "problem": await asyncio.to_thread(trials.problem, me, b.get("problem"))})
    if action == "record":
        got = await asyncio.to_thread(lambda: trials.record(
            me, what=str(b.get("what") or ""), quote=str(b.get("quote") or ""), screen=str(b.get("screen") or ""),
            screen_name=str(b.get("screen_name") or ""), how_bad=str(b.get("how_bad") or ""),
            source=str(b.get("source") or "owner"), persona_id=str(b.get("persona") or ""),
            gene=str(b.get("gene") or "")))
        return answer({"ok": True, "problem": got, "line": trials.problem_line(got)})
    if action == "sighting":
        got = await asyncio.to_thread(lambda: trials.sighting(
            me, b.get("problem"), quote=str(b.get("quote") or ""), how_bad=str(b.get("how_bad") or ""),
            source=str(b.get("source") or "owner"), persona_id=str(b.get("persona") or ""),
            trial=b.get("trial") or None, step=b.get("step")))
        return answer({"ok": True, "problem": got, "line": trials.problem_line(got)})
    if action == "reopen":
        got = await asyncio.to_thread(trials.reopen, me, b.get("problem"), note=str(b.get("note") or ""))
        return answer({"ok": True, "problem": got, "line": trials.problem_line(got)})
    if action == "personas":
        return answer({"ok": True, "personas": await asyncio.to_thread(trials.testers, me),
                       "default": await asyncio.to_thread(trials.default_persona, me),
                       "paused_all": (await asyncio.to_thread(trials.paused_all, me)) is not None})
    if action == "persona":
        return answer({"ok": True, "persona": await asyncio.to_thread(trials.tester_read, me,
                                                                      str(b.get("persona") or ""))})
    if action == "jobs":
        got = await asyncio.to_thread(trials.jobs, me, tester=str(b.get("persona") or ""))
        return answer({"ok": True, "jobs": got, "lines": [trials.job_line(j) for j in got]})
    if action == "job":
        return answer({"ok": True, "job": await asyncio.to_thread(trials.job, me, b.get("job"))})
    if action in ("tester_add", "tester_edit"):
        fields = {k: b.get(k) for k in ("name", "age", "job", "city", "short", "them", "device", "profile")
                  if b.get(k) not in (None, "")}
        got = await asyncio.to_thread(
            (lambda: trials.add_tester(me, fields, made_by="rouh")) if action == "tester_add"
            else (lambda: trials.edit_tester(me, str(b.get("persona") or ""), fields)))
        return answer({"ok": True, "tester": got})
    if action == "job_edit":
        got = await asyncio.to_thread(lambda: trials.edit_job(
            me, b.get("job"), name=b.get("name") or None, goal=b.get("goal") or None,
            covers=b.get("covers") if b.get("covers") is not None else None))
        return answer({"ok": True, "job": got})
    if action == "tester_remove":
        got = await asyncio.to_thread(trials.remove_tester, me, str(b.get("persona") or ""))
        return answer({"ok": True, "tester": got})
    if action == "default":
        got = await asyncio.to_thread(trials.set_default_persona, me, str(b.get("persona") or ""))
        return answer({"ok": True, "default": got})
    if action == "queue":
        got = await trials.run_by_hand(me, persona_id=str(b.get("persona") or ""), goal=str(b.get("goal") or ""),
                                       page=str(b.get("page") or ""), subject=str(b.get("job") or b.get("subject") or ""),
                                       gene=str(b.get("gene") or ""), job_no=b.get("job_no") or None)
        return answer({"ok": True, "trial": got, "said": got.get("said", "")})
    return answer({"ok": False, "error": "action is start, step, finish, broken, list, read, problems, problem, "
                                         "record, sighting, reopen, personas, persona, default, queue, jobs, job, "
                                         "job_edit, tester_add, tester_edit or tester_remove."}, status=400)
