"""The views behind the Gene therapy drawer and the board.

Gene therapy was called Feedback until 12 October 2026, when Petar renamed it:
"Can we also change the name of the feedback function to be called gene
therapy with a gene emoji and rename all the code files". The records it keeps
are still a feedback and a feature request, in the same tables
(`rouh/gene_therapy.py`), and every address below still answers under its old
name, `/api/feedback/...`, for a page loaded before the rename.

    GET    /api/gene-therapy                       the whole board, both columns
    POST   /api/gene-therapy                       what the drawer sends, and
                                                   what is then taken up by itself
    POST   /api/gene-therapy/settings              the board's own switches:
                                                   whether it builds by itself
    POST   /api/gene-therapy/requests              a feature request on its own
    GET    /api/gene-therapy/requests/<id>         one, with its files and its run
    POST   /api/gene-therapy/requests/<id>         change its title, type or status
    POST   /api/gene-therapy/requests/<id>/run     start a run to build it
    DELETE /api/gene-therapy/requests/<id>
    GET    /api/gene-therapy/<id>                  one feedback, with what came of it
    POST   /api/gene-therapy/<id>                  change its status
    POST   /api/gene-therapy/<id>/promote          turn it into a feature request
    DELETE /api/gene-therapy/<id>

**The order of the addresses matters** (`rouh/project/urls.py`): the
`requests/...` ones and `settings` are declared before `<id>`, or the literal
word would be read as a feedback's id and the route would answer "not found".

Every one of them starts with the same question - who is signed in, and which
organisation are they in - through `Tenancy.current`, and nothing here reads an
organisation or a user out of the request body. The board is the
organisation's: what it lists is `org_id`'s rows and nobody else's.

Files never touch this module's storage. The drawer uploads them through
`POST /attachments/<session>` while the person is still typing, exactly as the
composer does, and sends the ids it got back. Here they are resolved against
that session by `attachments.Attachments.resolve`, so an id that was never
uploaded, or that belongs to a different folder, is simply not found and the
rest of the submission goes through.

These were FastAPI routes in `rouh/feedback_web.py` until 23 September 2026,
and `rouh/web/feedback.py` until 12 October 2026; what they answer is unchanged.
"""
from __future__ import annotations

import logging
from typing import Any

from asgiref.sync import sync_to_async

from rouh import gene_therapy as gt
from rouh import objects, runs, starting, triage

from .common import answer, body_of, methods, only, refuse, who

log = logging.getLogger("rouh.gene_therapy")

#: The most files one submission may carry. A person attaching more than this
#: to one piece of feedback has a folder, not an attachment.
MAX_FILES = 20

NO_STORE = {"Cache-Control": "no-store"}


def _rt():
    from rouh import runtime

    return runtime


def _run_state(run_id: str) -> dict | None:
    """What the register says about the run building a request, or None.

    None covers both "no run yet" and "a run this machine has forgotten", and
    the card says which: an id with no row is a run that has been deleted, and
    that is a fact worth showing rather than hiding.
    """
    if not run_id:
        return None
    try:
        row = runs.row_for(run_id)
    except Exception:                                        # pragma: no cover
        log.exception("the run behind a feature request could not be read")
        return None
    if row is None:
        return {"id": run_id, "gone": True}
    return {"id": row["id"], "title": row["title"], "status": row["status"],
            "detail": row.get("detail") or "", "mode": row.get("mode") or "",
            "exit_code": row.get("exit_code"), "gone": False}


def _card(row: gt.FeatureRequest, files=()) -> dict:
    """One feature request as the board draws it: the row, its run, and
    whether it is waiting for the sweep to start one (`triage.queued`)."""
    return dict(row.as_json(files), run=_run_state(row.run_id), queued=triage.queued(row))


def _take_files(owner_kind: str, owner_id: str, sent: Any) -> list:
    """Bind the files already uploaded to the row now being written.

    The session is on each entry, because the drawer uploads into a folder of
    its own before there is a row to hang them on. Anything that does not
    resolve is left out and said so in the log: a screenshot that never
    arrived must not throw away the sentence it came with.
    """
    rt = _rt()
    wanted: dict[str, list[str]] = {}
    for entry in (sent or [])[:MAX_FILES]:
        if isinstance(entry, dict):
            session, att_id = str(entry.get("session") or ""), str(entry.get("id") or "")
        else:
            session, att_id = "", str(entry or "")
        if not session or not att_id:
            continue
        wanted.setdefault(session, []).append(att_id)
    records: list[dict] = []
    for session, ids in wanted.items():
        found, missing = rt.files.resolve(session, ids)
        if missing:
            log.info("%s file(s) on a feedback submission were not found", len(missing))
        records.extend(found)
    if not records:
        return []
    return rt.gene_therapy.add_files(owner_kind, owner_id, records)


def _automatic() -> bool:
    convert = _rt().converter
    return convert is not None and convert.enabled


# --- the whole board --------------------------------------------------------------


async def _board(request):
    """Both columns, their counts, and what a run may be started with.

    One request rather than one per column: the two lists are read together,
    they are drawn together, and a board that asked twice could show a
    feature request whose feedback is not on the screen beside it.
    """
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("sign in", 401)
    rt = _rt()

    def read():
        store = rt.gene_therapy
        # Before either column is read, not after: a request whose run has
        # ended since the last look says so on this draw rather than on the
        # next one.
        triage.settle_quietly(store, me.org_id)
        said = store.list_feedback(me.org_id)
        asked = store.list_requests(me.org_id)
        said_files = store.files_by_owner(gt.FEEDBACK, [f.id for f in said])
        asked_files = store.files_by_owner(gt.REQUEST, [r.id for r in asked])
        return {
            "you": {"user_id": me.user_id, "name": me.name},
            "organisation": {"id": me.org_id},
            "feedback": [f.as_json(said_files.get(f.id, ())) for f in said],
            "requests": [_card(r, asked_files.get(r.id, ())) for r in asked],
            "counts": store.counts(me.org_id),
            # Whether anything left here is picked up by itself. "Nothing has
            # happened to my feedback yet" and "nobody is ever going to look
            # at my feedback" are two very different things to be reading.
            "automatic": _automatic(),
            # And the board's own switches: whether what is picked up is also
            # given a run by itself, and who last moved it.
            "settings": store.board_settings(me.org_id),
            "statuses": {"feedback": list(gt.FEEDBACK_STATUSES),
                         "requests": list(gt.REQUEST_STATUSES)},
            "kinds": list(gt.REQUEST_KINDS),
            # What the Start-a-run box on a card offers: the same two lists
            # the sidebar's own Start box uses.
            "run_options": {
                "workspaces": starting.workspaces(),
                "policies": list(objects.POLICIES),
                "one_program": bool(rt.one is not None and rt.one.configured()),
            },
        }

    return answer(await sync_to_async(read)(), headers=NO_STORE)


async def _leave_feedback(request):
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("sign in", 401)
    rt = _rt()
    sent = body_of(request)
    try:
        row = await sync_to_async(rt.gene_therapy.add_feedback)(
            org_id=me.org_id, user_id=me.user_id, author=me.name,
            body=str(sent.get("body") or ""), page=str(sent.get("page") or ""))
    except gt.Refused as exc:
        return refuse(str(exc), 400)
    files = await sync_to_async(_take_files)(gt.FEEDBACK, row.id, sent.get("files"))
    # Taken up at once, in the background: read, turned into a feature request
    # and given a run, while the person is still reading Thank you. The answer
    # does not wait for any of it (`triage.Converter.take_later`). The run only
    # when this board builds by itself, and Thank you says which.
    automatic = _automatic()
    if automatic:
        rt.converter.take_later(me.org_id, row)
    builds = automatic and await sync_to_async(rt.gene_therapy.autobuild)(me.org_id)
    return answer({"ok": True, "automatic": automatic, "autobuild": builds,
                   "feedback": row.as_json(files)})


board = methods(GET=_board, POST=_leave_feedback)


@only("POST")
async def settings(request):
    """Move one of the board's own switches. Only `autobuild`, so far.

    The organisation's, not the person's: the board is one list for everybody
    in it, so whether it builds by itself is one answer for all of them, and
    anybody who can press Start on a card can press this. Every open board is
    told, so a second tab does not go on showing a switch that has moved.
    """
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("sign in", 401)
    sent = body_of(request)
    if not isinstance(sent.get("autobuild"), bool):
        return refuse("Say autobuild: true or false.", 400)
    rt = _rt()
    now = await sync_to_async(rt.gene_therapy.set_autobuild)(
        me.org_id, sent["autobuild"], by=me.name)
    await rt.announce_gene_therapy()
    return answer({"ok": True, "settings": now})


# --- feature requests ------------------------------------------------------------------


@only("POST")
async def new_request(request):
    """A feature request nobody complained about first. That is allowed."""
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("sign in", 401)
    rt = _rt()
    sent = body_of(request)
    try:
        row = await sync_to_async(rt.gene_therapy.add_request)(
            org_id=me.org_id, user_id=me.user_id, author=me.name,
            title=str(sent.get("title") or ""), body=str(sent.get("body") or ""),
            kind=str(sent.get("kind") or "feature"))
    except gt.Refused as exc:
        return refuse(str(exc), 400)
    files = await sync_to_async(_take_files)(gt.REQUEST, row.id, sent.get("files"))
    return answer({"ok": True, "request": _card(row, files)})


async def _one_request(request, request_id: str):
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("sign in", 401)
    store = _rt().gene_therapy

    def read():
        # The same settling the board does, because a card read in full is
        # read on its own and must not be the one place still saying Building.
        triage.settle_quietly(store, me.org_id)
        row = store.get_request(me.org_id, request_id)
        if row is None:
            return None
        files = store.files_for(gt.REQUEST, row.id)
        out: dict[str, Any] = {"request": _card(row, files)}
        if row.from_feedback:
            came_from = store.get_feedback(me.org_id, row.from_feedback)
            if came_from is not None:
                out["source"] = came_from.as_json(store.files_for(gt.FEEDBACK, came_from.id))
        return out

    out = await sync_to_async(read)()
    if out is None:
        return refuse("not found", 404)
    return answer(out, headers=NO_STORE)


async def _change_request(request, request_id: str):
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("sign in", 401)
    store = _rt().gene_therapy
    sent = body_of(request)
    try:
        row = await sync_to_async(store.update_request)(
            me.org_id, request_id,
            title=sent["title"] if "title" in sent else None,
            body=sent["body"] if "body" in sent else None,
            kind=sent["kind"] if "kind" in sent else None,
            status=sent["status"] if "status" in sent else None)
    except gt.Refused as exc:
        return refuse(str(exc), 400)
    if row is None:
        return refuse("not found", 404)
    await sync_to_async(_take_files)(gt.REQUEST, row.id, sent.get("files"))
    files = await sync_to_async(store.files_for)(gt.REQUEST, row.id)
    return answer({"ok": True, "request": _card(row, files)})


async def _drop_request(request, request_id: str):
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("sign in", 401)
    if not await sync_to_async(_rt().gene_therapy.delete_request)(me.org_id, request_id):
        return refuse("not found", 404)
    return answer({"ok": True})


one_request = methods(GET=_one_request, POST=_change_request, DELETE=_drop_request)


@only("POST")
async def run_for_request(request, request_id: str):
    """Start a real run to build it, briefed with the card and its files.

    The same `starting.start` every other way of starting work goes through,
    so this is a run of exactly the same kind as one started from the sidebar.
    What it is given is `gene_therapy.compose_brief` - the title, how the solution
    should work, the feedback it came out of, and every attached file by its
    path on disk, which is how a file reaches something that can open it.
    """
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("sign in", 401)
    rt = _rt()
    store = rt.gene_therapy
    row = await sync_to_async(store.get_request)(me.org_id, request_id)
    if row is None:
        return refuse("not found", 404)
    sent = body_of(request)

    def brief_of():
        source = (store.get_feedback(me.org_id, row.from_feedback)
                  if row.from_feedback else None)
        return gt.compose_brief(
            row,
            files=store.files_for(gt.REQUEST, row.id),
            source=source,
            source_files=(store.files_for(gt.FEEDBACK, source.id)
                          if source is not None else ()),
        )

    brief = await sync_to_async(brief_of)()
    try:
        started = await rt.start_run_for(
            brief=brief, title=row.title,
            workspace=str(sent.get("workspace") or ""),
            policy=str(sent.get("policy") or ""), org_id=me.org_id)
    except starting.CannotStart as exc:
        return refuse(str(exc), 503)
    except Exception as exc:                                 # pragma: no cover
        log.exception("a run for feature request %s could not be started", row.id)
        return refuse(f"It could not be started: {exc}", 500)
    after = await sync_to_async(store.set_run)(me.org_id, row.id, str(started.get("id") or ""))
    files = await sync_to_async(store.files_for)(gt.REQUEST, row.id)
    return answer({
        "ok": True,
        "started": started,
        "request": _card(after or row, files),
    })


# --- one feedback ---------------------------------------------------------------------


async def _one_feedback(request, feedback_id: str):
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("sign in", 401)
    store = _rt().gene_therapy

    def read():
        row = store.get_feedback(me.org_id, feedback_id)
        if row is None:
            return None
        made = store.list_requests(me.org_id, from_feedback=row.id)
        made_files = store.files_by_owner(gt.REQUEST, [r.id for r in made])
        return {
            "feedback": row.as_json(store.files_for(gt.FEEDBACK, row.id)),
            # What has already come out of it, so nobody writes the same
            # feature request twice.
            "requests": [_card(r, made_files.get(r.id, ())) for r in made],
        }

    out = await sync_to_async(read)()
    if out is None:
        return refuse("not found", 404)
    return answer(out, headers=NO_STORE)


async def _change_feedback(request, feedback_id: str):
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("sign in", 401)
    store = _rt().gene_therapy
    sent = body_of(request)
    try:
        row = await sync_to_async(store.set_feedback_status)(
            me.org_id, feedback_id, str(sent.get("status") or ""))
    except gt.Refused as exc:
        return refuse(str(exc), 400)
    if row is None:
        return refuse("not found", 404)
    files = await sync_to_async(store.files_for)(gt.FEEDBACK, row.id)
    return answer({"ok": True, "feedback": row.as_json(files)})


async def _drop_feedback(request, feedback_id: str):
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("sign in", 401)
    if not await sync_to_async(_rt().gene_therapy.delete_feedback)(me.org_id, feedback_id):
        return refuse("not found", 404)
    return answer({"ok": True})


one_feedback = methods(GET=_one_feedback, POST=_change_feedback, DELETE=_drop_feedback)


@only("POST")
async def promote(request, feedback_id: str):
    """Turn what somebody said into what is going to be done about it.

    The feedback itself is not touched beyond its status: it stays exactly as
    it was written. What is made is a second row that remembers it.
    """
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("sign in", 401)
    store = _rt().gene_therapy
    source = await sync_to_async(store.get_feedback)(me.org_id, feedback_id)
    if source is None:
        return refuse("not found", 404)
    sent = body_of(request)
    try:
        row = await sync_to_async(store.add_request)(
            org_id=me.org_id, user_id=me.user_id, author=me.name,
            title=str(sent.get("title") or "") or source.body.splitlines()[0][:200],
            body=str(sent.get("body") or ""),
            kind=str(sent.get("kind") or "feature"),
            from_feedback=source.id)
    except gt.Refused as exc:
        return refuse(str(exc), 400)
    files = await sync_to_async(_take_files)(gt.REQUEST, row.id, sent.get("files"))
    # Picked up, and the left column says so without anybody reading the right
    # one against it. A feedback somebody has already marked done or declined
    # is left where it is: that was a decision, and this is not the place to
    # undo it.
    if source.status in ("new", "triaged"):
        await sync_to_async(store.set_feedback_status)(me.org_id, source.id, "planned")
    return answer({"ok": True, "request": _card(row, files)})
