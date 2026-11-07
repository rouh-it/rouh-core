"""Settings for the models: the mode, the router's bar, two tiers, the choice of every
use, locks, and the Auto toggle and Sync of each box.

    GET  /api/settings/models            what the Models page draws
    POST /api/settings/models            one change:
         {"which": "mode", "mode"}         best, balanced or saver
         {"which": "bar", "bar"}           the router's bar set by hand (0.5 to 1), or
                                           null to follow the service's
         {"which": "<tier>", "models"}     a tier's whole ordered list of models
         {"which": "<tier>", "model"}      one model moved to the front of a tier's list
         {"which": "<tier>", "main"}       a provider's first model moved to the front
         {"which": "<use>", "tier"}        a use on a tier, or "off"
         {"which": "<use>", "models"}      a use on models of its own (Custom), in order
         {"which": "share", "on"}          the anonymous daily totals shared or not
         {"which": "compare", "on", "per_day"}  the blind comparisons on or off
         {"which": "<item>", "lock"}       a tier or a use locked (true) or not (false)
         {"which": "auto", "on", "box"}    Auto on in a box, "tiers" or "uses" (the service;
                                           while either is on, the day's counts and double
                                           calls) or off (the manual settings)
         {"which": "sync", "box"}          Sync: the box's manual settings made the
                                           service's, once; "changed" says how many
         {"which": "undo_sync"}            what the last Sync or Reset changed, put back
         {"which": "reset", "box"}         the box's manual settings not locked back to the
                                           defaults
    GET  /api/settings/models/share      what would be sent today, exactly, and what double
                                         calls cost this month
    GET  /api/settings/models/sent       exactly what was last sent, or kept as what would
                                         have been sent, for "See exactly what was sent"
    POST /api/settings/models/keys       {"provider": "google" or "xai", "key"}: an
                                         organisation's own key kept sealed, or removed
                                         with an empty one; never given back
    POST /api/models/vote                {"token", "vote"}: a blind comparison's vote
                                         (`rouh/modelvotes.py`)

They are the organisation's, like its Google app, and only its administrators
may change them: which model answers decides what everybody in it is answered
with and what that costs. Anybody in it may read them. `rouh/modeldefaults.py`
holds what they mean and where they are kept, and `rouh/modeloutcomes.py` what
is shared; this file is only the routes.
"""
from __future__ import annotations

import logging

from asgiref.sync import sync_to_async
from django.http import HttpRequest

from rouh import modeldefaults, modeloutcomes
from rouh.config import config

from .common import answer, body_of, only, refuse, who

log = logging.getLogger("rouh.modeldefaults")

NOT_ADMIN = "Only an administrator of your organisation can change these."


@only("GET", "POST")
async def settings_models(request: HttpRequest):
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("sign in", 401)

    def now():
        return modeldefaults.shown(me.org_id, config, who=me)

    if request.method == "GET":
        return answer(await sync_to_async(now)())
    if not modeldefaults.may_change(me):
        return refuse(NOT_ADMIN, 403, **(await sync_to_async(now)()))
    sent = body_of(request)
    by = me.name or me.email or me.user_id
    try:
        changed = await sync_to_async(modeldefaults.put)(
            me.org_id, str(sent.get("which") or ""),
            model=str(sent.get("model") or "") or None,
            tier=str(sent.get("tier") or "") or None,
            main=str(sent.get("main") or "") or None,
            lock=bool(sent["lock"]) if "lock" in sent else None,
            on=bool(sent["on"]) if sent.get("on") is not None else None,
            box=str(sent.get("box") or "") or None, mode=str(sent.get("mode") or "") or None,
            bar=sent.get("bar") if "bar" in sent else None,
            models=[str(m) for m in sent["models"]] if isinstance(sent.get("models"), list) else None,
            per_day=sent.get("per_day") if "per_day" in sent else None, by=by, cfg=config)
    except modeldefaults.Refused as exc:
        return refuse(str(exc), 400, **(await sync_to_async(now)()))
    from rouh import runtime

    await runtime.announce_model_defaults()
    return answer({"ok": True, "changed": changed, **(await sync_to_async(now)())})


@only("GET")
async def settings_models_share(request: HttpRequest):
    """Exactly what Auto sends rouh.land today, and what double calls cost this month, for
    the (i) beside each Auto toggle."""
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("sign in", 401)
    return answer(await sync_to_async(modeloutcomes.preview)(me.org_id, config))


@only("GET")
async def settings_models_sent(request: HttpRequest):
    """Exactly what this organisation last sent rouh.land, or kept as what would have been
    sent while sending is a dry run: the payload itself, as JSON, with nothing added to it."""
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("sign in", 401)
    import json

    from django.http import HttpResponse

    said = await sync_to_async(modeloutcomes.last_sent)(me.org_id)
    response = HttpResponse(json.dumps(said, indent=2, ensure_ascii=False) + "\n",
                            content_type="application/json; charset=utf-8")
    response["Cache-Control"] = "no-store"
    return response


@only("POST")
async def settings_models_keys(request: HttpRequest):
    """An organisation's own Google or xAI key, kept sealed (`rouh/providerkeys.py`), or
    removed. Only its administrators; the answer is the Models page again, which says only
    whether a key is set and its last four characters."""
    from rouh import providerkeys

    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("sign in", 401)

    def now():
        return modeldefaults.shown(me.org_id, config, who=me)

    if not modeldefaults.may_change(me):
        return refuse(NOT_ADMIN, 403, **(await sync_to_async(now)()))
    sent = body_of(request)
    try:
        await sync_to_async(providerkeys.save)(me.org_id, str(sent.get("provider") or ""),
                                               str(sent.get("key") or ""),
                                               by=me.name or me.email or me.user_id)
    except providerkeys.Refused as exc:
        return refuse(str(exc), 400, **(await sync_to_async(now)()))
    from rouh import runtime

    await runtime.announce_model_defaults()
    return answer({"ok": True, **(await sync_to_async(now)())})


@only("POST")
async def models_vote(request: HttpRequest):
    """A blind comparison's vote: A, B, Tie, Neither or Skip, by its one-time token."""
    from rouh import modelvotes

    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("sign in", 401)
    sent = body_of(request)
    try:
        await sync_to_async(modelvotes.vote)(me, str(sent.get("token") or ""), str(sent.get("vote") or ""))
    except modelvotes.Refused as exc:
        return refuse(str(exc), 400)
    return answer({"ok": True})
