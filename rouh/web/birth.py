"""A Rouh's birth over the web (`rouh/birth.py`, `birthpage.js`): Anatomy, Rouh Land Account,
Rouh profile (Meta, Birthday until 4 November 2026).

    GET  /api/birth                     what the page draws: its name, keys, rouh.land, second name
    POST /api/birth/born                {code?, url?, key?}: born on rouh.land, which gives it its name
    POST /api/birth/nickname            {nickname, first?, last?}: what this person calls it, its
                                        human names, for them only
    POST /api/birth/connect             {code, url?, key?}: registered on rouh.land; a free Rouh's birth
    POST /api/birth/check               ask rouh.land now how its keys stand
    POST /api/birth/rotate              {words, stolen?, since?}: a new daily key, signed for by the
                                        recovery key; stolen marks the old one dead
    POST /api/birth/recover             {url?, key?}: account recovery, a new key to ask for on rouh.land
    POST /api/birth/recover/started     {request}: rouh.land sent the person back with their request
    POST /api/birth/end                 {name}: both keys lost, this identity ends
    POST /api/birth/disconnect          stop being connected to rouh.land; the owner keeps their email

Reading and the nickname are anybody's signed in; everything else is an administrator's. Nothing
here answers with a key or the recovery words (Petar, 4 November 2026: the keys are opaque).
"""
from __future__ import annotations

from asgiref.sync import sync_to_async
from django.http import HttpRequest, HttpResponseNotAllowed

from rouh import addressing, birth, genelab

from .comments import NO_STORE
from .common import _text, answer, body_of, refuse, who

REFUSED = (birth.Refused, genelab.Refused)


async def _me(request: HttpRequest):
    return await sync_to_async(who)(request)


async def page(request: HttpRequest):
    me = await _me(request)
    if me is None:
        return refuse("Sign in to Rouh first.", 401)
    if request.method not in ("GET", "HEAD"):
        return HttpResponseNotAllowed(["GET"])
    return answer(await sync_to_async(birth.page)(me), headers=NO_STORE)


async def _post(request: HttpRequest, act):
    me = await _me(request)
    if me is None:
        return refuse("Sign in to Rouh first.", 401)
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    try:
        got = await act(me, body_of(request))
    except REFUSED as exc:
        return refuse(str(exc), 400)
    out = await sync_to_async(birth.page)(me)
    out.update(got or {})
    return answer(out, headers=NO_STORE)


def _registry(body) -> dict:
    return {"url": _text(body, "url", 500), "key_pem": _text(body, "key", 2000)}


async def born(request: HttpRequest):
    async def act(me, body):
        got = await sync_to_async(birth.be_born)(me, code=_text(body, "code", 200), **_registry(body))
        # Born on rouh.land is Connected: its phone address is asked for too.
        from rouh import relay

        await sync_to_async(relay.linked_later)()
        return got
    return await _post(request, act)


async def nickname(request: HttpRequest):
    async def act(me, body):
        if "first" in body or "last" in body:
            return await sync_to_async(birth.set_human_names)(
                me, first=_text(body, "first", 80), last=_text(body, "last", 80),
                nickname=_text(body, "nickname", 80))
        return await sync_to_async(birth.set_nickname)(me, _text(body, "nickname", 80))
    return await _post(request, act)


async def connect(request: HttpRequest):
    async def act(me, body):
        code = _text(body, "code", 200)
        was_free = await sync_to_async(birth.current)(str(me.org_id)) is None
        got = await sync_to_async(birth.connect)(me, code=code, **_registry(body))
        if code or was_free:
            # Linked to the owner's rouh.land account after birth: Connected, so its phone address too.
            from rouh import relay

            await sync_to_async(relay.linked_later)()
        return got
    return await _post(request, act)


async def check(request: HttpRequest):
    async def act(me, body):
        if not getattr(me, "is_admin", False):
            raise birth.Refused("Only an administrator of this Rouh does that.")
        got = await sync_to_async(birth.check)(str(me.org_id), force=True)
        if got.get("error"):
            raise birth.Refused(got["error"])
        said = birth.standing(birth.current(str(me.org_id)))["said"]
        rec = await sync_to_async(birth.recover_check)(str(me.org_id))
        return {"ok": True, "said": rec.get("said") or said}
    return await _post(request, act)


async def rotate(request: HttpRequest):
    async def act(me, body):
        return await sync_to_async(birth.rotate)(me, _text(body, "words", 600), stolen=bool(body.get("stolen")),
                                                 since=_text(body, "since", 40))
    return await _post(request, act)


async def recover(request: HttpRequest):
    async def act(me, body):
        # rouh.land accepts only its own return address (`addressing.ROUH_LAND_RETURN`), which
        # sends the person on to Rouh profile with the request's id.
        back = request.build_absolute_uri(addressing.ROUH_LAND_RETURN)
        return await sync_to_async(birth.recover_start)(me, back=back, **_registry(body))
    return await _post(request, act)


async def recover_started(request: HttpRequest):
    async def act(me, body):
        return await sync_to_async(birth.recover_started)(me, _text(body, "request", 60))
    return await _post(request, act)


async def end(request: HttpRequest):
    async def act(me, body):
        return await sync_to_async(birth.end)(me, _text(body, "name", 80))
    return await _post(request, act)


async def disconnect(request: HttpRequest):
    """Stop being connected to rouh.land (`birth.disconnect`): the owner keeps their email here."""
    async def act(me, body):
        return await sync_to_async(birth.disconnect)(me)
    return await _post(request, act)
