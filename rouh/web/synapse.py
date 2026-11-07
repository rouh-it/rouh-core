"""Synapse's lab, over HTTP: everything its debugger reads and does (`rouh/synapse/`).

One address, `/api/synapse/...`, dispatched here. Every dataset address checks
that the dataset is the asking person's, in their organisation, before
anything else (`datasets.mine`); a dataset that is not theirs is simply not
found. Long work (storing an item's model part, a question, an evaluation) is
started and answered at once with the id the page then reads as it fills in.
"""
from __future__ import annotations

import asyncio
import logging
import threading

from django.http import HttpRequest
from django.views.decorators.csrf import csrf_exempt

from .common import answer, body_of, refuse, who

log = logging.getLogger("rouh.web.synapse")

NO_STORE = {"Cache-Control": "no-store"}

#: What this first version does not do yet, said on the homepage itself.
NOT_BUILT = [
    {"what": "A local decision model on this machine (D68)",
     "why": "Nothing to run it with yet: no JevK5 or Laya is installed, and this machine has no NVIDIA card (Q18). "
            "Sensitivity suggestions, which the spec keeps local, use the generative backend here, as D67 allows."},
    {"what": "Voyage's rerank-2.5 (D39)",
     "why": "Embeddings are Voyage's voyage-4 since 3 October 2026 (D37); the cross-encoder candidate for the "
            "seed slot is not in the comparison yet."},
    {"what": "The Decisions API itself",
     "why": "It is in limited preview and refuses this key (403, checked every hour). Every decision is answered "
            "by the generative backend with log probabilities meanwhile, and says so."},
    {"what": "Asking the tier call again when an item's signals change, and code's old rules in shadow (D80)",
     "why": "The tier call runs when an item is stored and again whenever it is edited. A later "
            "reply, star or task link does not ask it again by itself yet, and D58's old rules are not computed beside it."},
    {"what": "Its own worker service, rouh-memory-worker (D61)",
     "why": "The queue, its table and SKIP LOCKED are the spec's, but the loop runs inside Rouh's process."},
    {"what": "Real sources: calendar, Drive, chats",
     "why": "Only Synapse Master is hooked to Rouh: every task and what is inside it, the contacts, kept two ways "
            "with iCloud (4 October 2026), and since 5 October 2026 every email of Rouh's own Gmail, kept in step "
            "(the Gmail card). The other datasets are the lab's own. A person Synapse met in an item "
            "(origin synapse) is never synced to iCloud or the phone."},
    {"what": "Importers for events and places",
     "why": "Both kinds are registered with their requirements (rouh/synapse/kinds.py) so the pattern is there; "
            "nothing fills them yet."},
    {"what": "Nightly jobs: the weekly link re-check of 1,000 links (D33) and the nightly deletion check (D60)",
     "why": "Both run on demand here: the phrase check runs with every delete, and Explore has a topic merge (D34)."},
    {"what": "Groups as readers (D60)",
     "why": "Readers are people and 'everyone'; a group of people is not a principal yet."},
    {"what": "Per-section X-rays as passages of their own (D8)",
     "why": "Long documents get section X-rays and a document X-ray, stored on the item; only the document X-ray "
            "is a search passage."},
    {"what": "Partitioning, replicas and cold vectors (D62)",
     "why": "Not built. Recent first (Tune > Search, off) uses a time-led index on the passages instead of "
            "partitions, and `manage.py synapse_bench` measures search and link candidates at 100,000 items "
            "without either (migration 0071, 4 October 2026)."},
    {"what": "A worker of its own for backfill",
     "why": "An import's model parts run on the queue's backfill lane, on slots of their own in Rouh's process "
            "(SYNAPSE_BACKFILL_WORKERS, 4) plus the import's own (`batch.store_many`); never on a live slot."},
    {"what": "Backups reaching deleted items (Q9)",
     "why": "Deletion reaches every table and the logged prompts; backups keep an item until they expire."},
]


def _need_ready():
    from rouh.synapse import db

    return db.ready()


def _start(fn, *args, **kwargs) -> None:
    """Run work on a thread of its own, closing its database connection after."""
    def go():
        from django.db import connection
        try:
            fn(*args, **kwargs)
        except Exception:  # noqa: BLE001
            log.exception("Synapse work failed")
        finally:
            connection.close()
    threading.Thread(target=go, daemon=True).start()


async def api(request: HttpRequest, rest: str = ""):
    if not await asyncio.to_thread(_need_ready):
        return refuse("Synapse's tables are not in this database yet (migration 0062).", 503)
    person = who(request)
    if person is None:
        return refuse("Sign in first.", 401)
    parts = [p for p in rest.strip("/").split("/") if p]
    try:
        if not parts or parts == ["home"]:
            return answer(await asyncio.to_thread(_home, person), headers=NO_STORE)
        if parts == ["datasets"] and request.method == "POST":
            got = body_of(request)
            from rouh.synapse import datasets
            ds = await asyncio.to_thread(datasets.create, person, got.get("name") or "", got.get("about") or "")
            return answer({"ok": True, "dataset": ds["id"]})
        if parts == ["chat"] and request.method == "POST":
            # The one Synapse chat, told which dataset is on the screen, and
            # whether the chat open beside the lab is already one of its own.
            got = body_of(request)
            return answer(await asyncio.to_thread(_chat, person, str(got.get("dataset") or ""),
                                                  str(got.get("active") or "")))
        if parts == ["examples"] and request.method == "POST":
            from rouh.synapse import seeds, worker
            worker.start()
            got = await asyncio.to_thread(seeds.create, person, body_of(request).get("key") or "")
            return answer(got, status=200 if got.get("ok") else 400)
        if parts == ["explain"] and request.method == "POST":
            from rouh.synapse import explain
            got = body_of(request)
            return answer(await asyncio.to_thread(explain.explain, person, got.get("label") or "",
                                                  got.get("place") or "", got.get("hint") or "",
                                                  got.get("before") or [], got.get("asks") or [],
                                                  got.get("question") or ""))
        if parts[:1] == ["mail"] and len(parts) == 2 and parts[1] in ("read", "reconcile") \
                and request.method == "POST":
            got = await asyncio.to_thread(_mail_now, person, parts[1], str(body_of(request).get("inbox") or ""))
            return answer(got, status=200 if got.get("ok") else 400)
        if parts[:1] == ["improvements"] and len(parts) <= 2:
            got = await asyncio.to_thread(_improvements, person, parts[1] if len(parts) == 2 else "")
            return answer(got, status=200 if got.get("ok") else 404, headers=NO_STORE)
        if parts == ["decisions", "probe"] and request.method == "POST":
            from rouh.synapse import ai
            got = await asyncio.to_thread(ai.probe_decisions, str(person.org_id),
                                          {"user_id": str(person.user_id), "org_id": str(person.org_id)})
            return answer(got)
        if parts[0] == "ds" and len(parts) >= 2:
            from rouh.synapse import datasets
            ds = await asyncio.to_thread(datasets.mine, parts[1], person)
            if ds is None:
                return refuse("There is no such dataset.", 404)
            return await _dataset(request, ds, parts[2:])
    except Exception as exc:  # noqa: BLE001
        log.exception("Synapse's API failed on %s", rest)
        return refuse(f"That did not work: {type(exc).__name__}: {exc}", 500)
    return refuse("There is nothing at that address.", 404)


def _chat(person, dataset: str, active: str) -> dict:
    """The person's Synapse chat with the screen's dataset noted on it, and
    whether `active` is that chat or a fork off it, which the page then keeps
    rather than switching (`rouh/synapse/chat.py`)."""
    from rouh import forks
    from rouh.synapse import chat, datasets

    ds = datasets.mine(dataset, person) if dataset else None
    got = chat.general(person, ds["id"] if ds else None)
    keep = bool(active) and (active == got or forks.root_of(active) == got)
    return {"ok": True, "chat": got, "keep": keep}


def _schedule(person) -> dict | None:
    """The nightly run's row on the Reminders page, as the Improvements page says it."""
    from rouh import clock, reminders
    from rouh.synapse import nightly

    row = reminders.server_row(person, nightly.JOB)
    if row is None:
        return None
    with clock.person(person):
        v = reminders.view(row)
    return {"id": row.id, "state": v["state"], "when": v["when"], "repeats": v["repeats"],
            "last_said": v["last_said"], "last_day": v["last_day"], "last_time": v["last_time"]}


def _improvements(person, number: str) -> dict:
    """The attempts to make Synapse better, newest first, or one of them whole (`synapse/improvements.py`)."""
    from rouh.synapse import improvements, nightly

    if not improvements.ready():
        return {"ok": False, "error": "The attempts table is not in this database yet (migration 0087)."}
    org, user = str(person.org_id), str(person.user_id)
    improvements.settle(org, user, run_state=nightly.run_state)
    if number:
        row = improvements.one(org, user, number)
        if row is None:
            return {"ok": False, "error": f"There is no attempt {number}."}
        return {"ok": True, "attempt": improvements.view(row)}
    rows = improvements.listing(org, user)
    return {"ok": True, "schedule": _schedule(person), "measures": improvements.MEASURES,
            "attempts": [{**{k: v for k, v in improvements.view(r).items() if k not in ("before", "after", "ideas")},
                          "headline": [m for m in improvements.view(r)["measures"]
                                       if m["key"] in improvements.HEADLINE]} for r in rows]}


def _improvements_home(person) -> dict:
    """The homepage's card: how many attempts, the newest one, and when the next night is."""
    from rouh.synapse import improvements

    if not improvements.ready():
        return {}
    rows = improvements.listing(str(person.org_id), str(person.user_id), 1)
    count = improvements.db.value("SELECT count(*) FROM synapse.attempt WHERE org_id = %s AND user_id = %s",
                                  (str(person.org_id), str(person.user_id))) or 0
    return {"count": int(count), "latest": improvements.summary_line(rows[0]) if rows else "",
            "schedule": _schedule(person)}


def _home(person) -> dict:
    from rouh import modeldefaults
    from rouh.config import model_name
    from rouh.synapse import ai, datasets, kinds, numbers, seeds, worker

    worker.start()
    seeds.seed_on_first_visit(person)
    status = ai.decisions_status(str(person.org_id))
    return {
        "datasets": datasets.listing(person),
        "people": _people_home(person),
        "mail": _mail_home(person),
        "calendar": _calendar_home(person),
        "meetings": _meetings_home(person),
        "improvements": _improvements_home(person),
        "kinds": kinds.catalogue(),
        "examples": seeds.examples(),
        "settings": numbers.catalogue({}),
        "backends": {
            "openai_key": ai.have_key(),
            "voyage_key": ai.have_voyage(),
            "decisions": status,
            "embeddings": numbers.BY_KEY["embed_model"].value,
            # The Models page's, now (`synapse/numbers.MODEL_USES`), by name.
            **{k: model_name(modeldefaults.use_model(u, str(person.org_id) or None))
               for k, u in (("helper", "synapse_helper"), ("answer", "synapse_answer"),
                            ("decision_generative", "synapse_decision"), ("judge", "synapse_judge"))},
            "store": "PostgreSQL with pgvector (halfvec, HNSW) and full text (English, Bulgarian Hunspell, simple), "
                     "in the synapse schema of Rouh's own database",
        },
        "not_built": NOT_BUILT,
    }


@csrf_exempt
async def meeting_library_hook(request: HttpRequest):
    """`POST /api/hooks/meeting-library`: the meeting library says a meeting changed (`synapse/meetings.py`).

    Open without a sign-in, because the library has none to give: the signature over the raw body, with
    the library's webhook secret, is the credential, and a message with a timestamp more than five minutes
    off or a signature already taken is refused with 401. What it can do is queue the meeting to be read
    again from the library itself; nothing in the message is stored."""
    from rouh.synapse import meetings

    if request.method != "POST":
        return refuse("POST only", 405)
    status, said = await asyncio.to_thread(meetings.receive, request.body, request.headers)
    return answer(said, status=status, headers=NO_STORE)


async def _dataset(request: HttpRequest, ds: dict, parts: list[str]):
    from rouh.synapse import (datasets, db, evaluate, ingest, learning, mapping, numbers, people, recall, worker)

    worker.start()
    method = request.method
    head = parts[0] if parts else ""
    if not parts:
        return answer(await asyncio.to_thread(_summary, ds), headers=NO_STORE)
    if head == "rename" and method == "POST":
        got = body_of(request)
        row = await asyncio.to_thread(datasets.rename, ds, got.get("name") or "", got.get("about"))
        return answer({"ok": True, "name": row["name"]})
    if head == "delete" and method == "POST":
        counts = await asyncio.to_thread(datasets.remove, ds)
        if counts.get("refused"):
            return refuse(counts["refused"], 409)
        return answer({"ok": True, "deleted": counts})
    if head == "people" and method == "GET":
        # The picker for readers: people already in the owner's people set, never a typed name.
        got = await asyncio.to_thread(people.search, ds, request.GET.get("q", ""))
        return answer({"people": got}, headers=NO_STORE)
    if head == "items" and method == "GET":
        q = request.GET.get("q", "")
        kind = request.GET.get("kind", "")
        origin = request.GET.get("origin", "")
        return answer(await asyncio.to_thread(_items, ds, q, kind, origin), headers=NO_STORE)
    if head == "items" and method == "POST":
        got = body_of(request)
        items = got.get("items") or ([got] if got.get("text") or got.get("raw") else [])
        if not items:
            return refuse("Give the item some text.", 400)
        out = []
        for it in items[:200]:
            # A thread is never typed by a person: only code fills it, from the source (an .eml's headers).
            it = {k: v for k, v in it.items() if k != "thread"} if isinstance(it, dict) else it
            out.append(await asyncio.to_thread(ingest.store, ds, it, by="page"))
        return answer({"ok": True, "stored": out})
    if head == "upload" and method == "POST":
        files = await asyncio.to_thread(lambda: request.FILES)
        units = []
        for f in files.getlist("files")[:50]:
            data = await asyncio.to_thread(f.read)
            units.append(_parse_file(f.name, data))
        if len(units) == 1:
            out = [await asyncio.to_thread(ingest.store, ds, payload, by="page") for payload in units[0]]
            return answer({"ok": True, "stored": out})
        # Several files are a batch: stored many at once, each file's items in order (an email before
        # its attachments), and their model parts on the queue's backfill lane (`batch`).
        from rouh.synapse import batch
        got = await asyncio.to_thread(batch.store_many, ds, units, by="page", wait=False)
        return answer({"ok": True, "stored": got["rows"], "backfill": True, "failed": got["failed"],
                       "store_s": got["store_s"], "concurrency": got["concurrency"]})
    if head == "item" and len(parts) >= 2:
        item_id = parts[1]
        if len(parts) == 2 and method == "GET":
            got = await asyncio.to_thread(_item_page, ds, item_id)
            return answer(got, status=200 if got else 404, headers=NO_STORE)
        action = parts[2] if len(parts) > 2 else ""
        if action == "edit" and method == "POST":
            changes = {k: v for k, v in body_of(request).items() if k != "thread"}
            where = await asyncio.to_thread(_where, ds, item_id)
            got = await asyncio.to_thread(ingest.edit, where, item_id, changes, by="page")
            return answer(got, status=200 if got.get("ok") else 400)
        if action == "silos" and method == "POST":
            # Its silos, as the person set them on the item's page (`rouh/silos.py`): a label, no new version.
            from rouh import silos
            where = await asyncio.to_thread(_where, ds, item_id)
            given = body_of(request).get("silos")
            got = await asyncio.to_thread(silos.set_item, where, item_id, given if isinstance(given, list) else [])
            return answer(got, status=200 if got.get("ok") else 400)
        if action == "delete" and method == "POST":
            where = await asyncio.to_thread(_where, ds, item_id)
            got = await asyncio.to_thread(ingest.delete, where, item_id, by="page")
            return answer(got, status=200 if got.get("ok") else 400)
        if action == "passage" and len(parts) == 4 and method == "GET":
            got = await asyncio.to_thread(_passage, ds, item_id, parts[3])
            return answer(got, status=200 if got else 404, headers=NO_STORE)
        if action == "rerun" and method == "POST":
            # One item's X-ray made again, as the worker reprocesses it: the way to fill in the people
            # mentioned for an item X-rayed before 4 October 2026, which is never done by itself.
            where = await asyncio.to_thread(_where, ds, item_id)
            got = await asyncio.to_thread(_rerun, where, item_id)
            return answer(got, status=200 if got.get("ok") else 400)
        if action == "gold" and method == "POST":
            where = await asyncio.to_thread(_where, ds, item_id)
            gold = await asyncio.to_thread(ingest.set_mentions_gold, where["id"], item_id, body_of(request).get("gold"))
            return answer({"ok": True, "gold": gold})
        if action == "rule" and method == "POST":
            got = await asyncio.to_thread(_confirm_rule, ds, item_id, body_of(request))
            return answer(got)
        if action in ("same", "not_same") and method == "POST":
            # His pick between two people flagged as likely the same, kept with Undo (`aka.link`, `aka.apart`).
            other = str(body_of(request).get("other") or "")
            if action == "same":
                return await _aka(ds, item_id, "link", {"pick": {"kind": "person", "id": other}, "by": "Synapse"})
            return await _aka(ds, item_id, "apart", {"other": other, "by": "Synapse"})
        if action == "aka" and len(parts) <= 4:
            # Also known as (`rouh/synapse/aka.py`): the person's identifiers, a search to link one, and
            # every link and unlink with its Undo, for the contact card and the person card alike.
            sub = parts[3] if len(parts) == 4 else ""
            if sub == "" and method == "GET":
                return await _aka(ds, item_id, "view", {})
            if sub == "find" and method == "GET":
                return await _aka(ds, item_id, "find", {"q": request.GET.get("q", "")[:200]})
            if sub in ("link", "unlink", "apart", "undo") and method == "POST":
                return await _aka(ds, item_id, sub, body_of(request))
    if head == "activity":
        return answer(await asyncio.to_thread(_activity, ds, request.GET.get("since", "")), headers=NO_STORE)
    if head == "trace" and len(parts) == 2:
        got = await asyncio.to_thread(_trace, ds, parts[1])
        return answer(got, status=200 if got else 404, headers=NO_STORE)
    if head == "query" and method == "POST" and len(parts) == 1:
        got = body_of(request)
        question = str(got.get("question") or "").strip()
        if not question:
            return refuse("Ask something.", 400)
        qid = await asyncio.to_thread(
            db.value, "INSERT INTO synapse.query (dataset_id, question, context_item, asker, mode, by, label, settings) "
                      "VALUES (%s, %s, %s, %s, %s, 'page', %s, %s::jsonb) RETURNING id",
            (ds["id"], question[:2000], got.get("context") or None,
             people.asker_id(ds, got.get("asker")),
             "background" if got.get("mode") == "background" else "live", str(got.get("label") or "")[:80],
             db.Json(got.get("override") or {})))
        _start(recall.run, ds, question, asker=got.get("asker") or None, context_item_id=got.get("context") or None,
               mode=got.get("mode") or "live", override=got.get("override") or None, by="page",
               label=str(got.get("label") or ""), query_id=qid)
        return answer({"ok": True, "query": qid})
    if head == "query" and len(parts) == 2:
        got = await asyncio.to_thread(_query, ds, parts[1])
        return answer(got, status=200 if got else 404, headers=NO_STORE)
    if head == "queries":
        return answer(await asyncio.to_thread(_queries, ds), headers=NO_STORE)
    if head == "why" and method == "POST":
        got = body_of(request)
        return answer(await asyncio.to_thread(recall.why_item, ds, got.get("query"), got.get("item")))
    if head == "graph":
        return answer(await asyncio.to_thread(_graph, ds), headers=NO_STORE)
    if head == "search":
        q = request.GET.get("q", "")
        asker = request.GET.get("asker") or datasets.me(ds)
        return answer(await asyncio.to_thread(_search, ds, q, asker), headers=NO_STORE)
    if head == "map":
        sub = parts[1] if len(parts) > 1 else ""
        if sub == "rebuild" and method == "POST":
            viewer = body_of(request).get("viewer") or datasets.me(ds)
            _start(mapping.build, ds, people.asker_id(ds, viewer), by="page", why="rebuilt on request")
            return answer({"ok": True})
        if sub == "pin" and method == "POST":
            got = body_of(request)
            await asyncio.to_thread(mapping.pin, ds, got.get("section") or "words", got.get("key") or got.get("text", "")[:40],
                                    got.get("text") or "")
            return answer({"ok": True})
        if sub == "unpin" and method == "POST":
            got = body_of(request)
            await asyncio.to_thread(mapping.unpin, ds, got.get("section") or "words", got.get("key") or "")
            return answer({"ok": True})
        return answer(await asyncio.to_thread(_map, ds, request.GET.get("viewer") or datasets.me(ds)), headers=NO_STORE)
    if head == "settings":
        if method == "POST":
            got = body_of(request)
            ds2, problems = await asyncio.to_thread(datasets.tune, ds, got.get("changes") or {})
            await asyncio.to_thread(_note_tune, ds2, got.get("changes") or {}, problems)
            return answer({"ok": not problems, "problems": problems,
                           "settings": numbers.catalogue(ds2.get("tuning") or {})})
        return answer({"settings": numbers.catalogue(ds.get("tuning") or {})}, headers=NO_STORE)
    if head == "eval":
        sub = parts[1] if len(parts) > 1 else ""
        if sub == "question" and method == "POST":
            got = body_of(request)
            if got.get("delete"):
                await asyncio.to_thread(evaluate.delete_question, ds, got["delete"])
                return answer({"ok": True})
            if got.get("id"):
                return answer(await asyncio.to_thread(evaluate.update_question, ds, got["id"], got))
            return answer(await asyncio.to_thread(
                evaluate.add_question, ds, str(got.get("question") or ""), gold=got.get("gold") or [],
                facts=got.get("facts") or [], asker=got.get("asker") or "", context=got.get("context") or "",
                forbidden=bool(got.get("forbidden")), group=got.get("group") or ""))
        if sub == "run" and method == "POST":
            got = body_of(request)
            return answer(await asyncio.to_thread(evaluate.start, ds, got.get("presets") or ["without", "with"],
                                                  by="page", only=got.get("only") or None))
        if sub == "run" and len(parts) == 3:
            return answer(await asyncio.to_thread(db.row, "SELECT * FROM synapse.eval_run WHERE dataset_id = %s AND id = %s",
                                                  (ds["id"], parts[2])) or {}, headers=NO_STORE)
        return answer(await asyncio.to_thread(_eval, ds), headers=NO_STORE)
    if head == "vectors":
        from rouh.synapse import vectors
        sub = parts[1] if len(parts) > 1 else ""
        if sub == "move" and method == "POST":
            to = str(body_of(request).get("to") or "voyage-4")
            got = await asyncio.to_thread(vectors.start, ds, to, by="page")
            return answer(got, status=200 if got.get("ok") else 400)
        if sub == "put_back" and method == "POST":
            got = await asyncio.to_thread(vectors.put_back, ds, by="page")
            return answer(got, status=200 if got.get("ok") else 400)
        return answer(await asyncio.to_thread(vectors.status, ds), headers=NO_STORE)
    if head == "dreams":
        return await _dreams(request, ds, parts[1:])
    if head == "learn" and method == "POST":
        return answer(await asyncio.to_thread(learning.apply, ds, by="page"))
    if head == "topics" and len(parts) > 1 and parts[1] == "merge" and method == "POST":
        return answer(await asyncio.to_thread(_merge_topics, ds))
    if head == "copy" and method == "POST":
        got = body_of(request)
        return answer(await asyncio.to_thread(_copy, ds, request, got))
    return refuse("There is nothing at that address.", 404)


def datasets_me(ds: dict) -> str:
    from rouh.synapse import datasets

    return datasets.me(ds)


def _dream_numbers(request: HttpRequest, got: dict) -> None:
    """Each change still waiting carries the number of the one decision that holds it: since
    8 October 2026 a night's changes of one kind are one decision, "Synapse, night 1: 32 link
    changes" (`decision_sources.DreamSource`), and its number is how the person names them to
    Rouh (`rouh/decision_numbers.py`)."""
    from rouh import decisions

    changes = got.get("changes") or []
    me = who(request)
    if not changes or me is None:
        return

    def group(c) -> str:
        return f"{c.get('night') or got.get('number')}:{c.get('kind')}"

    try:
        numbers = decisions.numbers_of_sources(
            me, "dream", sorted({group(c) for c in changes if c.get("state") == "waiting"}),
            take_in=False)
    except Exception:
        log.exception("the dream changes' decision numbers could not be read")
        return
    for c in changes:
        if c.get("state") == "waiting" and numbers.get(group(c)):
            c["decision_number"] = numbers[group(c)]


async def _dreams(request: HttpRequest, ds: dict, parts: list[str]):
    """The Dreams page (`rouh/synapse/dreaming.py`): the nights, one night, what waits, and the buttons. Every
    change is read and decided as the dataset's own person, who sees only what they can read in full."""
    from rouh.synapse import dreaming, search

    if not await asyncio.to_thread(dreaming.ready):
        return refuse("Dreaming's tables are not in this database yet (migration 0089).", 503)
    viewer = search.readers_for(await asyncio.to_thread(datasets_me, ds))
    method = request.method
    sub = parts[0] if parts else ""
    if not parts and method == "GET":
        got = await asyncio.to_thread(dreaming.listing, ds, viewer)
        if ds.get("master"):
            got["schedule"] = await asyncio.to_thread(dreaming.schedule, who(request))
        got["example"] = ds.get("example") or ""
        if got["example"]:
            from rouh.synapse import seeds
            got["examples_missing"] = await asyncio.to_thread(seeds.dream_examples_missing, ds)
        return answer(got, headers=NO_STORE)
    if sub == "run" and method == "POST":
        got = await asyncio.to_thread(dreaming.queue, ds, by="page")
        return answer(got, status=200 if got.get("ok") else 409)
    if sub == "waiting" and method == "GET":
        got = await asyncio.to_thread(dreaming.waiting, ds, viewer)
        await asyncio.to_thread(_dream_numbers, request, got)
        return answer(got, headers=NO_STORE)
    if sub == "night" and len(parts) == 2 and method == "GET":
        got = await asyncio.to_thread(dreaming.night, ds, parts[1], viewer)
        if got:
            await asyncio.to_thread(_dream_numbers, request, got)
        return answer(got or {"error": "There is no such night."}, status=200 if got else 404, headers=NO_STORE)
    if sub == "night" and len(parts) == 3 and parts[2] == "undo" and method == "POST":
        got = await asyncio.to_thread(dreaming.undo_night, ds, parts[1], viewer)
        return answer(got, status=200 if got.get("ok") else 400)
    if sub == "change" and len(parts) == 3 and method == "POST" and parts[2] in ("approve", "reject", "undo"):
        got = await asyncio.to_thread(dreaming.decide, ds, parts[1], parts[2], viewer)
        return answer(got, status=200 if got.get("ok") else 400)
    if sub == "group" and method == "POST":
        got = body_of(request)
        verdict = str(got.get("verdict") or "")
        if verdict not in ("approve", "reject"):
            return refuse("Approve or reject.", 400)
        night_id = None
        if got.get("night"):
            from rouh.synapse import db
            night_id = await asyncio.to_thread(db.value, "SELECT id FROM synapse.dream WHERE dataset_id = %s AND number = %s",
                                               (ds["id"], int(got["night"])))
            if not night_id:
                return refuse("There is no such night.", 404)
        out = await asyncio.to_thread(dreaming.decide_group, ds, night_id, str(got.get("kind") or ""), verdict, viewer)
        return answer(out)
    if sub == "examples" and method == "POST":
        from rouh.synapse import seeds
        got = await asyncio.to_thread(seeds.add_dream_examples, ds)
        return answer(got, status=200 if got.get("ok") else 400)
    return refuse("There is nothing at that address.", 404)


# --- what each address reads ------------------------------------------------------------

def _summary(ds: dict) -> dict:
    from rouh.synapse import ai, datasets, db, kinds, mapping, numbers, people, vectors, worker

    people.ensure_values(ds)
    counts = db.row(
        "SELECT count(*) FILTER (WHERE kind NOT IN ('person','topic','layer','rule') AND deleted_at IS NULL) AS items, "
        "count(*) FILTER (WHERE kind = 'topic' AND deleted_at IS NULL) AS topics, "
        "count(*) FILTER (WHERE kind = 'layer' AND deleted_at IS NULL) AS layers, "
        "count(*) FILTER (WHERE kind = 'rule' AND deleted_at IS NULL) AS rules, "
        "count(*) FILTER (WHERE deleted_at IS NOT NULL) AS tombstones, "
        "count(*) FILTER (WHERE xray IS NOT NULL AND jsonb_array_length(coalesce(xray->'claims', '[]'::jsonb)) > 0 "
        "  AND deleted_at IS NULL) AS xrayed "
        "FROM synapse.item WHERE dataset_id = %s", (ds["id"],)) or {}
    # The people this dataset knows: its own, or the ones of its owner's people set it links to (decision 7).
    counts["people"] = db.value(
        "SELECT count(*) FROM synapse.item i WHERE i.dataset_id = ANY(synapse.scope(%s)) AND i.kind = 'person' "
        "AND i.deleted_at IS NULL AND synapse.reaches(%s, i.dataset_id, i.id)", (ds["id"], ds["id"]))
    counts["links"] = db.value("SELECT count(*) FROM synapse.link WHERE dataset_id = %s", (ds["id"],))
    counts["passages"] = db.value("SELECT count(*) FROM synapse.passage WHERE dataset_id = %s", (ds["id"],))
    counts["vectors"] = db.value("SELECT count(vec) FROM synapse.passage WHERE dataset_id = %s", (ds["id"],))
    counts["cost"] = float(db.value("SELECT coalesce(sum(cost_usd), 0) FROM synapse.trace WHERE dataset_id = %s",
                                    (ds["id"],)) or 0)
    tiers = db.rows("SELECT tier, count(*) AS n FROM synapse.item WHERE dataset_id = %s AND deleted_at IS NULL AND "
                    "kind NOT IN ('person','topic','layer','rule') GROUP BY tier ORDER BY tier", (ds["id"],))
    by_type = db.rows("SELECT type, origin, count(*) AS n, round(avg(strength)::numeric, 2) AS strength FROM synapse.link "
                      "WHERE dataset_id = %s GROUP BY type, origin ORDER BY count(*) DESC", (ds["id"],))
    m = mapping.current(ds)
    home = people.home(ds)
    me = datasets.me(ds)
    return {"dataset": {k: ds.get(k) for k in ("id", "name", "about", "example", "chat_id", "owner_name", "created_at",
                                                "role", "people_id", "master")},
            "me": me, "me_name": people.name_of(me), "counts": counts, "tiers": tiers, "links_by_type": by_type,
            "people": datasets.people(ds), "jobs": worker.waiting(ds["id"]),
            "people_home": {"id": home["id"], "name": home["name"], "own": home["id"] == ds["id"],
                            "origins": _origins(home["id"])},
            "kinds": kinds.catalogue(),
            "map": {"text": m["text"], "version": m["version"], "made_at": m["made_at"], "tokens": m["tokens"]} if m else None,
            "settings": numbers.catalogue(ds.get("tuning") or {}),
            "decisions": ai.decisions_status(ds["org_id"]), "openai_key": ai.have_key(),
            "vectors": vectors.status(ds)}


def _origins(scope: str) -> dict:
    from rouh.synapse import db

    return {r["origin"] or "none": r["n"] for r in db.rows(
        "SELECT meta->>'origin' AS origin, count(*) AS n FROM synapse.item WHERE dataset_id = %s AND kind = 'person' "
        "AND deleted_at IS NULL GROUP BY 1 ORDER BY 1", (scope,))}


def _people_home(person) -> dict:
    """The owner's contacts on the homepage: Synapse Master's people, how many have a card in iCloud, and
    what is on its way to iCloud (`synapse/contacts.py`)."""
    from rouh.synapse import db, master

    ms = master.of(str(person.org_id), str(person.user_id))
    if not ms:
        return {"id": None, "origins": {}, "identities": {}}
    return {"id": ms["id"], "name": ms["name"], "origins": _origins(ms["id"]),
            "identities": {r["type"]: r["n"] for r in db.rows(
                "SELECT type, count(*) AS n FROM synapse.identity WHERE scope_id = %s GROUP BY type", (ms["id"],))},
            "likely_same": db.value("SELECT count(*) FROM synapse.item WHERE dataset_id = %s AND kind = 'person' "
                                    "AND deleted_at IS NULL AND jsonb_array_length(coalesce(meta->'likely_same', "
                                    "'[]'::jsonb)) > 0", (ms["id"],)),
            **(db.row("SELECT count(*) FILTER (WHERE meta ? 'icloud') AS cards FROM synapse.item WHERE dataset_id = %s "
                      "AND kind = 'person' AND deleted_at IS NULL", (ms["id"],)) or {}),
            **(db.row("SELECT count(*) FILTER (WHERE done_at IS NULL) AS to_icloud, "
                      "count(*) FILTER (WHERE done_at IS NOT NULL AND error <> '') AS to_icloud_failed, "
                      "max(done_at) FILTER (WHERE error = '') AS last_to_icloud FROM synapse.job "
                      "WHERE dataset_id = %s AND kind IN ('icloud_push', 'icloud_delete')", (ms["id"],)) or {})}


def _mail_home(person) -> dict:
    """Gmail kept in the person's Synapse Master: each inbox's sync, for the homepage's card
    (`synapse/gmailsync.py`)."""
    from rouh.synapse import gmailsync, master

    ms = master.of(str(person.org_id), str(person.user_id))
    if not ms:
        return {"id": None, "inboxes": []}
    return {"id": ms["id"], "name": ms["name"], "inboxes": gmailsync.health(ms["id"]),
            "stale_minutes": gmailsync.STALE_MINUTES, "poll_seconds": gmailsync.POLL_SECONDS}


def _calendar_home(person) -> dict:
    """Every calendar kept in the person's Synapse Master, for the homepage's card (`synapse/calsync.py`)."""
    from rouh.synapse import calsync, master

    ms = master.of(str(person.org_id), str(person.user_id))
    if not ms:
        return {"id": None, "calendars": []}
    return {"id": ms["id"], "calendars": calsync.health(ms["id"]), "poll_seconds": calsync.POLL_SECONDS,
            "stale_minutes": calsync.STALE_MINUTES}


def _meetings_home(person) -> dict:
    """The meeting library kept in the person's Synapse Master, for the homepage's card (`synapse/meetings.py`)."""
    from rouh.synapse import master, meetings

    ms = master.of(str(person.org_id), str(person.user_id))
    if not ms:
        return {"id": None}
    got = meetings.health(ms["id"])
    return {"id": ms["id"], **got} if got else {"id": None}


def _mail_now(person, what: str, inbox: str) -> dict:
    """Read an inbox's Gmail history now, or start its check against Gmail's whole list now."""
    from rouh.synapse import gmailsync, master

    ms = master.of(str(person.org_id), str(person.user_id))
    row = gmailsync.row_of(ms["id"], inbox) if ms and inbox else None
    if row is None or not row["enabled"]:
        return {"ok": False, "error": "That inbox is not kept in your Synapse Master."}
    if what == "read":
        got = gmailsync.beat_one(ms, row)
        if got.get("busy"):
            return {"ok": True, "said": "It is being read right now."}
        if got.get("error"):
            return {"ok": False, "error": f"Gmail could not be read: {got['error']}"}
        h = got.get("history") or {}
        return {"ok": True, "said": f"Read: {h.get('added', 0)} new, {h.get('deleted', 0)} deleted, "
                                    f"{h.get('labels', 0)} with changed labels queued."}
    _start(gmailsync.reconcile, ms, row["inbox"], by="by hand")
    return {"ok": True, "said": "Checking against Gmail's whole list now; the card shows the result when it is done."}


async def _aka(ds: dict, item_id: str, what: str, sent: dict):
    """One call of `aka` for the person `item_id`, answered as {ok, ...} or {ok: False, why} with 400."""
    from rouh.synapse import aka

    by = {"Synapse": "Synapse", "contact card": "contact card"}.get(str(sent.get("by") or ""), "Synapse")

    def run():
        where = _where(ds, item_id)
        if what == "view":
            return aka.view(where, item_id)
        if what == "find":
            return aka.find(where, item_id, sent.get("q") or "")
        if what == "link":
            pick = sent.get("pick") if isinstance(sent.get("pick"), dict) else {}
            return aka.link(where, item_id, pick, by=by)
        if what == "unlink":
            return aka.unlink(where, item_id, str(sent.get("type") or ""), str(sent.get("value") or ""), by=by)
        if what == "apart":
            return aka.apart(where, item_id, str(sent.get("other") or ""), by=by)
        return aka.undo(where, sent.get("change"), by=by)

    try:
        got = await asyncio.to_thread(run)
    except aka.Refused as exc:
        return answer({"ok": False, "why": str(exc)}, status=400)
    return answer(got, headers=NO_STORE)


def _where(ds: dict, item_id: str) -> dict:
    """The dataset an item lives in: this one, or, for a person, the owner's people set."""
    from rouh.synapse import ingest, people

    got = ingest.get_in_scope(ds, item_id)
    if got and str(got["dataset_id"]) != str(ds["id"]):
        return people.home(ds)
    return ds


def _named(ids) -> list[dict]:
    from rouh.synapse import people

    names = people.names(ids or [])
    return [{"id": i, "name": names.get(i, people.name_of(i))} for i in ids or []]


def _items(ds: dict, q: str, kind: str, origin: str = "") -> dict:
    from rouh.synapse import db, people

    if kind == "contact":
        kind = "person"
    rows = db.rows(
        "SELECT i.id, i.kind, i.title, i.said_at, i.tier, i.tier_by, i.sensitivity, i.silos, i.status, i.source_key, i.owner, i.version, "
        "i.meta->>'from' AS sender, i.meta->>'thread' AS thread, i.meta->>'area' AS area, i.meta->>'layer' AS layer, "
        "i.meta->>'title_by' AS title_by, i.meta->>'area_proposed' AS area_proposed, "
        "i.meta->>'origin' AS origin, (i.meta->>'value')::float AS value, "
        "(SELECT string_agg(o->>'contact_id', ' ') FROM jsonb_array_elements(coalesce(i.meta->'old', '[]'::jsonb)) o) AS old_ids, "
        "jsonb_array_length(coalesce(i.meta->'likely_same', '[]'::jsonb)) AS likely_same, "
        "(i.dataset_id <> %s) AS from_people_set, "
        "CASE WHEN i.meta->>'area_by' IN ('owner', 'model') THEN i.meta->>'area_by' "
        "WHEN coalesce(i.meta->>'area', '') <> '' THEN 'owner' END AS area_by, "
        "jsonb_array_length(coalesce(i.xray->'claims', '[]'::jsonb)) AS claims, "
        # A person's links come from every dataset of their owner; anything else's from its own.
        "(SELECT count(*) FROM synapse.link l WHERE (l.dataset_id = i.dataset_id AND l.src = i.id) OR (l.dst = i.id "
        " AND (i.kind = 'person' OR l.dataset_id = i.dataset_id))) AS links, "
        "(SELECT array_agg(principal ORDER BY principal) FROM synapse.reader r WHERE r.dataset_id = i.dataset_id "
        " AND r.item_id = i.id) AS readers "
        "FROM synapse.item i WHERE i.dataset_id = ANY(synapse.scope(%s)) AND synapse.reaches(%s, i.dataset_id, i.id) "
        "AND i.deleted_at IS NULL "
        "AND (%s = '' OR i.kind = %s) AND (%s = '' OR i.meta->>'origin' = %s) "
        "AND (%s = '' OR i.title ILIKE %s OR i.body ILIKE %s OR EXISTS (SELECT 1 FROM synapse.identity x "
        " WHERE x.scope_id = i.dataset_id AND x.item_id = i.id AND x.value ILIKE %s)) "
        "ORDER BY CASE WHEN %s = 'person' THEN coalesce((i.meta->>'value')::float, 0) END DESC NULLS LAST, "
        "i.said_at DESC NULLS LAST, i.stored_at DESC LIMIT 500",
        (ds["id"], ds["id"], ds["id"], kind, kind, origin, origin, q, f"%{q}%", f"%{q}%", f"%{q.lower()}%", kind))
    names = people.names({r for row in rows for r in row.get("readers") or []} | {row["owner"] for row in rows})
    from rouh import silos

    for row in rows:
        row["silo_chips"] = silos.chips(ds["user_id"], ds["org_id"], row.get("silos") or [])
        row["reader_names"] = [names.get(r, people.name_of(r)) for r in row.get("readers") or []]
        row["owner_name"] = names.get(row["owner"], people.name_of(row["owner"]))
    total = db.value("SELECT count(*) FROM synapse.item i WHERE i.dataset_id = ANY(synapse.scope(%s)) AND "
                     "synapse.reaches(%s, i.dataset_id, i.id) AND i.deleted_at IS NULL AND (%s = '' OR i.kind = %s) "
                     "AND (%s = '' OR i.meta->>'origin' = %s)", (ds["id"], ds["id"], kind, kind, origin, origin))
    return {"items": rows, "total": total}


def _item_page(ds: dict, item_id: str) -> dict | None:
    from rouh.synapse import db, ingest, people, text as tx

    item = ingest.get_in_scope(ds, item_id)
    if item is None:
        return None
    # A person of the owner's people set lives there; everything of theirs is read from it.
    home = str(item["dataset_id"])
    links = ingest.link_rows(ds["id"], item_id)
    passages = db.rows("SELECT id, seq, text, from_xray, embed_model, (vec IS NOT NULL) AS embedded, "
                       "substr(vec::text, 1, 120) AS vec_head, vector_dims(vec) AS vec_dims, "
                       "length(words::text) AS words_len, "
                       "substr(words::text, 1, 400) AS words FROM synapse.passage "
                       "WHERE dataset_id = %s AND item_id = %s ORDER BY from_xray, seq", (home, item_id))
    versions = db.rows("SELECT version, title, raw, xray, made_at, why, keep_until FROM synapse.item_version "
                       "WHERE dataset_id = %s AND item_id = %s ORDER BY version DESC", (home, item_id))
    traces = _item_traces(home, item_id)
    # The newest 60 calls, each with the run it belongs to, grouped by run: newest run first,
    # in call order inside each run.
    calls = db.rows("SELECT c.kind, c.purpose, c.backend, c.model, c.version, c.ms, c.tokens_in, c.tokens_out, "
                    "c.cost_usd, c.ok, c.at, c.trace_id, t.kind AS trace_kind, t.by AS trace_by, "
                    "t.started_at AS trace_at FROM (SELECT * FROM synapse.call WHERE dataset_id = %s AND "
                    "%s::uuid = ANY(items) ORDER BY at DESC LIMIT 60) c LEFT JOIN synapse.trace t ON t.id = c.trace_id "
                    "ORDER BY coalesce(t.started_at, c.at) DESC, c.trace_id, c.at, c.id", (home, item_id))
    derived = db.rows("SELECT d.child_table, d.child_id, i.title, i.kind FROM synapse.derived d LEFT JOIN synapse.item i "
                      "ON i.dataset_id = d.dataset_id AND i.id::text = d.child_id WHERE d.dataset_id = %s AND d.item_id = %s",
                      (home, item_id))
    # The main two are exactly the rows learning counts: questions a person asked (D57). The rest are
    # split by their query: an evaluation run (by 'eval'), or a background pack or any other question.
    uses = db.row(
        "SELECT count(*) FILTER (WHERE u.engaged) AS shown, count(*) FILTER (WHERE u.engaged AND u.cited) AS cited, "
        "count(*) FILTER (WHERE NOT u.engaged AND q.by = 'eval') AS eval_shown, "
        "count(*) FILTER (WHERE NOT u.engaged AND q.by = 'eval' AND u.cited) AS eval_cited, "
        "count(*) FILTER (WHERE NOT u.engaged AND q.by IS DISTINCT FROM 'eval') AS other_shown, "
        "count(*) FILTER (WHERE NOT u.engaged AND q.by IS DISTINCT FROM 'eval' AND u.cited) AS other_cited "
        "FROM synapse.use u LEFT JOIN synapse.query q ON q.id = u.query_id "
        "WHERE u.dataset_id = %s AND u.item_id = %s", (ds["id"], item_id))
    item["readers"] = ingest.readers_of(home, item_id)
    item["reader_names"] = _named(item["readers"])
    item["owner_name"] = people.name_of(item.get("owner"))
    item["compact"] = tx.compact(1, item)
    item["lives_in"] = None if home == str(ds["id"]) else {"id": home, "name": people.home(ds)["name"]}
    from rouh import silos

    item.update(silos.item_view(ds["user_id"], ds["org_id"], item))
    for l in links:
        if l.get("dst_kind") == "person":
            l["dst_origin"] = (db.value("SELECT meta->>'origin' FROM synapse.item WHERE id = %s", (l["dst"],)) or "")
    from rouh.synapse import dreaming, search

    out = {"item": item, "links": links, "passages": passages, "versions": versions, "traces": traces,
           "calls": calls, "derived": derived, "use": uses, "topics": _item_topics(ds, item, links),
           "dreams": dreaming.for_item(ds, item_id, search.readers_for(datasets_me(ds)))}
    if item.get("mentions_gold") and item.get("mentions") is not None:
        from rouh.synapse import mentions
        out["mentions_score"] = mentions.score_item(item["mentions_gold"], item["mentions"])
    if item["kind"] == "person":
        out["person"] = _person(ds, item)
    return out


# A step's data can hold the whole raw text, every call and every signal; the item page
# only needs what each run came to, so these are left in the database.
_STEP_BULK = ["raw", "body", "text", "calls", "signals", "read", "diff", "answer", "sources", "samples", "sample",
              "ops", "gist", "before_why", "why"]


def _item_traces(home: str, item_id: str) -> list[dict]:
    """The runs that stored, edited, reprocessed or deleted an item, newest first, each with
    its step count and the few outcomes that matter, read from its own steps."""
    from rouh.synapse import db

    traces = db.rows("SELECT id, kind, by, title, status, started_at, finished_at, ms, cost_usd, summary "
                     "FROM synapse.trace WHERE dataset_id = %s AND item_id = %s ORDER BY started_at DESC LIMIT 100",
                     (home, item_id))
    if not traces:
        return traces
    steps = db.rows("SELECT trace_id, name, status, data - %s::text[] AS data, data ? 'answer' AS has_answer, "
                    "coalesce(data->>'error', '') AS error FROM synapse.trace_step WHERE trace_id = ANY(%s::uuid[]) "
                    "ORDER BY trace_id, seq", (_STEP_BULK, [str(t["id"]) for t in traces]))
    by_trace: dict = {}
    for st in steps:
        by_trace.setdefault(str(st["trace_id"]), []).append(st)
    for t in traces:
        mine = by_trace.get(str(t["id"]), [])
        t["steps"] = len(mine)
        failed = next((st for st in mine if st["status"] == "failed"), None)
        t["error"] = (failed["error"] or f"the step {failed['name']} failed")[:300] if failed else ""
        t["outcomes"] = _trace_outcomes(t, mine)
        t.pop("summary", None)
    return traces


def _plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


def _trace_outcomes(trace: dict, steps: list[dict]) -> list[str]:
    """What a run came to, most telling first, in a few words each. Only what is really in
    its steps: an empty part says nothing."""
    summary = trace.get("summary") or {}
    named: dict = {}
    for st in steps:
        named.setdefault(st["name"], []).append(st)

    def data(name: str) -> dict:
        return (named.get(name) or [{}])[-1].get("data") or {}

    out: list[str] = []
    if "meeting" in named:
        # A meeting from the meeting library (`synapse/meetings.py`): which revision, and what of its transcript.
        m = data("meeting")
        out.append(f"Meeting {m.get('meeting')}, revision {m.get('revision')}" + (
            ": withdrawn in the library" if trace["kind"] == "delete" else ""))
        tr = data("transcript")
        if tr:
            out.append(f"Transcript: {tr.get('new', 0)} of {tr.get('passages', 0)} passages new, "
                       f"{tr.get('deleted', 0)} gone")
        if "meeting_readers" in named:
            out.append("Readers changed")
    if trace["kind"] == "delete":
        if "tombstone" in named:
            out.append("Out of every search")
        return out
    if trace["kind"] == "layer":
        got = data("apply")
        if "after" in got:
            out.append(_plural(int(got["after"]), "claim"))
        if got.get("added"):
            out.append(f"{len(got['added'])} new")
        if got.get("retired"):
            out.append(f"{len(got['retired']) if isinstance(got['retired'], list) else got['retired']} retired")
        return out
    if "diff" in named:
        d = data("diff")
        if d.get("note"):
            out.append("Nothing changed")
        else:
            if d.get("title"):
                out.append("New title")
            changed = [k for k in (d.get("meta") or {})]
            if changed:
                out.append("Changed: " + ", ".join(changed[:3]))
            if d.get("readers"):
                out.append("Readers changed")
    if "xray" in named:
        x = named["xray"][-1]
        check = data("quote_check")
        if x["status"] == "failed":
            out.append("X-ray failed")
        elif check.get("rejected"):
            out.append("X-ray rejected by the quote check")
        elif x.get("has_answer"):
            n = int(check.get("kept", summary.get("claims") or 0) or 0)
            out.append("X-ray: gist and " + _plural(n, "claim") if n else "X-ray: gist only")
        else:
            out.append("No X-ray")
    before, after = summary.get("tier_before"), summary.get("tier")
    if before is not None and after is not None and before != after:
        out.append(f"Tier {before} to {after}")
    t = data("title")
    if t.get("by") == "model" and t.get("after") and t.get("after") != t.get("before"):
        out.append("New title")
    links = int(data("code_links").get("count") or 0) + len(data("judgement_links").get("made") or []) + \
        len(data("short_links").get("made") or [])
    if links:
        out.append(_plural(links, "link") + " written")
    topics = data("topics")
    for key, said in (("created", "made"), ("linked", "linked"), ("proposed", "proposed")):
        if topics.get(key):
            out.append(_plural(len(topics[key]), "topic") + " " + said)
    area = data("area")
    if area.get("after") and area.get("after") != area.get("before"):
        out.append("Area: " + str(area["after"]))
    passages = int(data("words").get("passages") or 0) + (1 if "xray_passage" in named else 0)
    if passages:
        out.append(_plural(passages, "passage"))
    embedded = int(data("embedding").get("passages") or 0)
    if embedded:
        out.append(_plural(embedded, "embedding"))
    terms = data("terms").get("terms") or []
    if terms:
        out.append(_plural(len(terms), "term") + " for the map")
    # One outcome said once, in the order it first came.
    return list(dict.fromkeys(out))


def _passage(ds: dict, item_id: str, passage_id: str) -> dict | None:
    """One passage whole: its text, its words and its vector, which the item page only begins.
    Asked for when a cell's "See the rest" is pressed, so no page carries every vector."""
    from rouh.synapse import db, ingest

    if not str(passage_id).isdigit():
        return None
    item = ingest.get_in_scope(ds, item_id)
    if item is None:
        return None
    return db.row("SELECT id, seq, text, words::text AS words, vec::text AS vector, vector_dims(vec) AS vec_dims, "
                  "embed_model FROM synapse.passage WHERE dataset_id = %s AND item_id = %s AND id = %s",
                  (str(item["dataset_id"]), item_id, int(passage_id)))


def _person(ds: dict, item: dict) -> dict:
    """What the debugger shows of a person: identifiers, value, where they came from, and every item of
    their owner's that is linked to them, in whichever dataset (decision 11)."""
    from rouh.synapse import db, people

    meta = item.get("meta") or {}
    pid = item["id"]
    linked = db.rows(
        "SELECT l.type, l.strength, l.origin, l.dataset_id, d.name AS dataset, s.id, s.title, s.kind, s.said_at "
        "FROM synapse.link l JOIN synapse.item s ON s.id = l.src JOIN synapse.dataset d ON d.id = l.dataset_id "
        "WHERE l.dst = %s AND s.deleted_at IS NULL AND d.org_id = %s AND d.user_id = %s "
        "ORDER BY s.said_at DESC NULLS LAST LIMIT 300", (pid, ds["org_id"], ds["user_id"]))
    same = meta.get("likely_same") or []
    names = people.names([x.get("id") for x in same])
    return {"origin": meta.get("origin"), "old": meta.get("old") or [],
            # A contact: their card in iCloud, which an edit or a delete here is written to (synapse/contacts.py).
            "card": bool(ds.get("master") and (meta.get("icloud") or {}).get("href")),
            "identities": people.identities(item["dataset_id"], pid),
            "value": meta.get("value"), "value_parts": meta.get("value_parts") or {},
            "likely_same": [dict(x, name=names.get(str(x.get("id")), "(gone)")) for x in same],
            "aka": _aka_view(ds, pid),
            "linked": linked, "embedded": db.value("SELECT count(*) FROM synapse.passage WHERE item_id = %s AND "
                                                   "vec IS NOT NULL", (pid,)),
            "never_synced": meta.get("origin") == "synapse",
            "fields": {k: meta.get(k) for k in ("organisation", "birthday", "relationship", "research",
                                                "research_confirmed", "known", "handle") if meta.get(k) not in (None, "")}}


def _aka_view(ds: dict, pid) -> dict | None:
    from rouh.synapse import aka

    try:
        return aka.view(_where(ds, str(pid)), str(pid))
    except aka.Refused:
        return None


def _item_topics(ds: dict, item: dict, links: list[dict]) -> dict:
    """The topics an item is linked to, and the ones its X-ray proposed that are not topics yet (D34)."""
    from rouh.synapse import datasets, db, ingest

    item_id = item["id"]
    s = datasets.settings(ds)
    bar, days = int(s.topic_bar_items), int(s.topic_bar_days)
    linked = [{"id": l["dst"], "title": l["dst_title"], "strength": l["strength"]} for l in links
              if str(l["src"]) == str(item_id) and l["type"] == "about" and l["dst_kind"] == "topic"]
    # One row per name the item proposed, its latest; a re-X-ray writes the proposal again.
    proposed = db.rows(
        "SELECT p.name, p.norm, p.strength, p.at, p.at > now() - make_interval(days => %s) AS in_window, "
        " (SELECT count(DISTINCT q.item_id) FROM synapse.topic_proposal q WHERE q.dataset_id = p.dataset_id "
        "  AND q.norm = p.norm AND q.at > now() - make_interval(days => %s)) AS backers "
        "FROM (SELECT DISTINCT ON (norm) * FROM synapse.topic_proposal WHERE dataset_id = %s AND item_id = %s "
        "      ORDER BY norm, at DESC) p "
        # A proposal that has since become a topic is a linked topic above, not a proposal.
        "WHERE NOT EXISTS (SELECT 1 FROM synapse.item t WHERE t.dataset_id = p.dataset_id AND t.kind = 'topic' "
        "  AND t.deleted_at IS NULL AND t.meta->>'norm' = p.norm) "
        "ORDER BY p.at DESC, p.name", (days, days, ds["id"], item_id))
    # Every proposal row counts toward the bar, also one an earlier X-ray of the item made.
    now = {ingest._norm_topic(n) for n in ((item.get("xray") or {}).get("about") or [])}
    for p in proposed:
        p["current"] = p["norm"] in now
    return {"linked": linked, "proposed": proposed, "bar": bar, "days": days}


def _activity(ds: dict, since: str) -> dict:
    from rouh.synapse import db, worker

    rows = db.rows(
        "SELECT t.id, t.kind, t.title, t.by, t.status, t.started_at, t.finished_at, t.ms, t.cost_usd, t.item_id, "
        "(SELECT count(*) FROM synapse.trace_step s WHERE s.trace_id = t.id) AS steps, "
        "(SELECT q.id FROM synapse.query q WHERE q.trace_id = t.id LIMIT 1) AS query_id "
        "FROM synapse.trace t WHERE t.dataset_id = %s ORDER BY t.started_at DESC LIMIT 80", (ds["id"],))
    return {"traces": rows, "jobs": worker.waiting(ds["id"]),
            "latest": rows[0]["started_at"] if rows else None}


def _trace(ds: dict, trace_id: str) -> dict | None:
    from rouh.synapse import db

    try:
        t = db.row("SELECT * FROM synapse.trace WHERE dataset_id = %s AND id = %s::uuid", (ds["id"], trace_id))
    except Exception:  # noqa: BLE001
        return None
    if not t:
        return None
    t["steps"] = db.rows("SELECT id, seq, name, title, status, started_at, ms, cost_usd, data FROM synapse.trace_step "
                         "WHERE trace_id = %s ORDER BY seq", (trace_id,))
    t["calls"] = db.rows("SELECT kind, purpose, backend, model, version, ms, tokens_in, tokens_out, cost_usd, ok, error "
                         "FROM synapse.call WHERE trace_id = %s ORDER BY id", (trace_id,))
    t["query_id"] = db.value("SELECT id FROM synapse.query WHERE trace_id = %s", (trace_id,))
    # The queue's side of it: when each job of this run was queued, on which lane, and when it ran.
    t["jobs"] = db.rows("SELECT id, kind, lane, made_at, not_before, started_at, done_at, tries, error, "
                        "extract(epoch FROM (coalesce(started_at, now()) - made_at)) * 1000 AS waited_ms, "
                        "extract(epoch FROM (done_at - started_at)) * 1000 AS ran_ms "
                        "FROM synapse.job WHERE trace_id = %s ORDER BY id", (trace_id,))
    return t


def _query(ds: dict, query_id: str) -> dict | None:
    from rouh.synapse import db

    try:
        q = db.row("SELECT * FROM synapse.query WHERE dataset_id = %s AND id = %s::uuid", (ds["id"], query_id))
    except Exception:  # noqa: BLE001
        return None
    if not q:
        return None
    from rouh.synapse import people
    q["asker_name"] = people.name_of(q["asker"])
    q["trace"] = _trace(ds, q["trace_id"]) if q.get("trace_id") else None
    return q


def _queries(ds: dict) -> list[dict]:
    from rouh.synapse import db, people

    rows = db.rows("SELECT id, question, asker, mode, by, label, status, ms_pack, ms_total, cost_usd, created_at, "
                   "settings FROM synapse.query WHERE dataset_id = %s AND by <> 'eval' ORDER BY created_at DESC LIMIT 60",
                   (ds["id"],))
    names = people.names([r["asker"] for r in rows])
    for r in rows:
        r["asker_name"] = names.get(r["asker"], people.name_of(r["asker"]))
    return rows


def _graph(ds: dict) -> dict:
    from rouh.synapse import db

    # The dataset's items and the people of its owner's people set it links to (decision 7).
    nodes = db.rows(
        "SELECT i.id, i.kind, i.title, i.tier, i.sensitivity, i.meta->>'layer' AS layer, i.said_at, "
        "(SELECT count(*) FROM synapse.link l WHERE l.dataset_id = %s AND (l.src = i.id OR l.dst = i.id)) AS degree "
        "FROM synapse.item i WHERE i.dataset_id = ANY(synapse.scope(%s)) AND synapse.reaches(%s, i.dataset_id, i.id) "
        "AND i.deleted_at IS NULL ORDER BY degree DESC LIMIT 600", (ds["id"], ds["id"], ds["id"]))
    ids = [n["id"] for n in nodes]
    links = db.rows("SELECT id, src, dst, type, strength, origin FROM synapse.link WHERE dataset_id = %s AND "
                    "src = ANY(%s::uuid[]) AND dst = ANY(%s::uuid[])", (ds["id"], ids or [None], ids or [None])) if ids else []
    return {"nodes": nodes, "links": links}


def _search(ds: dict, q: str, asker: str) -> dict:
    from rouh.synapse import datasets, people, search, vectors
    from rouh.synapse.walk import facts_of

    s = datasets.settings(ds)
    if not q.strip():
        return {"items": []}
    got_q = vectors.query(ds, q, purpose="explore_search", owner=datasets.owner_of(ds))
    qvec = got_q["vec"]
    got = search.hybrid(ds["id"], q, qvec, asker=people.asker_id(ds, asker), settings=s, model=got_q["model"])
    facts = facts_of(ds["id"], [f["item_id"] for f in got["items"][:40]])
    return {"items": [dict(f, title=(facts.get(f["item_id"]) or {}).get("title"),
                           kind=(facts.get(f["item_id"]) or {}).get("kind")) for f in got["items"][:40]],
            "words": got["words"], "meaning": got["meaning"], "ms": got["ms"], "query_words": got["query_words"],
            "meaning_on": qvec is not None, "meaning_model": got_q["model"], "meaning_off_why": got_q["why"]}


def _map(ds: dict, viewer: str) -> dict:
    from rouh.synapse import datasets, db, ingest, people

    viewer = people.asker_id(ds, viewer)
    history = db.rows("SELECT version, text, tokens, why, made_at FROM synapse.map WHERE dataset_id = %s AND viewer = %s "
                      "ORDER BY version DESC LIMIT 20", (ds["id"], viewer))
    lines = db.rows("SELECT section, key, text, pinned, by, made_at FROM synapse.map_line WHERE dataset_id = %s "
                    "ORDER BY section, key", (ds["id"],))
    # Every area in the dataset, whoever may read it: this is the owner's debugger, not a viewer's map (D18).
    areas = db.rows(
        "SELECT coalesce(nullif(meta->>'area', ''), 'General') AS area, count(*) AS items, "
        "count(*) FILTER (WHERE coalesce(meta->>'area', '') <> '' AND coalesce(meta->>'area_by', 'owner') = 'owner') AS by_owner, "
        "count(*) FILTER (WHERE meta->>'area_by' = 'model' AND coalesce(meta->>'area', '') <> '') AS by_model "
        f"FROM synapse.item WHERE dataset_id = %s AND deleted_at IS NULL AND kind NOT IN {ingest.AREA_KINDS} "
        "GROUP BY 1 ORDER BY count(*) DESC", (ds["id"],))
    s = datasets.settings(ds)
    return {"viewer": viewer, "viewer_name": people.name_of(viewer), "current": history[0] if history else None, "history": history, "lines": lines,
            "people": datasets.people(ds), "areas": areas, "proposed": ingest.proposals(ds["id"]),
            "area_min_items": int(s.area_min_items)}


def _eval(ds: dict) -> dict:
    from rouh.synapse import db, evaluate, mentions

    runs = db.rows("SELECT id, label, configs, status, by, summary, started_at, finished_at, "
                   "jsonb_array_length(results) AS done FROM synapse.eval_run WHERE dataset_id = %s "
                   "ORDER BY started_at DESC LIMIT 20", (ds["id"],))
    # Gold people (Q21's groundwork): no model call, only the stored people against what was expected.
    gold = db.rows("SELECT id, title, mentions, mentions_gold FROM synapse.item WHERE dataset_id = %s AND "
                   "deleted_at IS NULL AND mentions_gold IS NOT NULL ORDER BY said_at NULLS FIRST, stored_at", (ds["id"],))
    return {"questions": evaluate.questions(ds), "runs": runs, "people": mentions.score(gold),
            "presets": [{"key": k, "label": v["label"], "note": v.get("note", "")} for k, v in evaluate.PRESETS.items()]}


def _note_tune(ds: dict, changes: dict, problems: list) -> None:
    from rouh.synapse.trace import Trace

    t = Trace(ds["id"], "tune", "Numbers changed", by="page")
    with t.step("tune", "Numbers changed") as st:
        st.data.update({"changes": changes, "problems": problems})
    t.finish("done")


def _rerun(ds: dict, item_id: str) -> dict:
    from rouh.synapse import ingest

    item = ingest.get_item(ds["id"], item_id)
    if item is None or item.get("deleted_at") is not None:
        return {"ok": False, "why": "There is no such item."}
    if item["kind"] in ("person", "layer", "topic"):
        return {"ok": False, "why": f"A {item['kind']} has no X-ray to run again."}
    job = ingest.enqueue(ds["id"], "ingest", item_id=item_id, priority=3)
    return {"ok": True, "job": job}


def _confirm_rule(ds: dict, item_id: str, got: dict) -> dict:
    from rouh.synapse import db, ingest

    item = ingest.get_item(ds["id"], item_id)
    if not item:
        return {"ok": False}
    meta = dict(item.get("meta") or {})
    pending = meta.get("pending_rules") or []
    idx = int(got.get("claim", -1))
    match = [p for p in pending if p.get("claim") == idx]
    if not match:
        return {"ok": False, "why": "That claim is not waiting to be a rule."}
    from rouh import rules

    made = ingest.make_rule(ds, match[0]["text"], item, why="confirmed by the owner",
                            origin=rules.origin_of("manual", "Confirmed by you in Synapse's lab, from something it read."))
    meta["pending_rules"] = [p for p in pending if p.get("claim") != idx]
    db.run("UPDATE synapse.item SET meta = %s::jsonb WHERE id = %s", (db.Json(meta), item_id))
    return {"ok": True, "rule": made}


def _merge_topics(ds: dict) -> dict:
    """D34's nightly merge, on request: topics whose vectors are closer than the setting."""
    from rouh.synapse import datasets, db, ingest, search
    from rouh.synapse.trace import Trace

    s = datasets.settings(ds)
    t = Trace(ds["id"], "maintain", "Topic merge (D34)", by="page")
    merged = []
    with t.step("merge", "Topics closer than the merge cosine get a same_as link, and their links move") as st:
        topics = db.rows("SELECT id, title, stored_at FROM synapse.item WHERE dataset_id = %s AND kind = 'topic' "
                         "AND deleted_at IS NULL ORDER BY stored_at", (ds["id"],))
        vecs = search.item_vectors(ds["id"], [x["id"] for x in topics])
        import math

        def cos(a, b):
            if not a or not b:
                return 0.0
            return sum(x * y for x, y in zip(a, b)) / ((math.sqrt(sum(x * x for x in a)) or 1) *
                                                       (math.sqrt(sum(y * y for y in b)) or 1))
        for i, a in enumerate(topics):
            for b in topics[i + 1:]:
                c = cos(vecs.get(a["id"]), vecs.get(b["id"]))
                if c >= float(s.topic_merge_cosine):
                    ingest.add_link(ds["id"], b["id"], a["id"], "same_as", 1.0, origin="code", made_by="topic merge",
                                    why=f"cosine {c:.3f}")
                    moved = db.run("UPDATE synapse.link SET dst = %s WHERE dataset_id = %s AND dst = %s AND type = 'about' "
                                   "AND NOT EXISTS (SELECT 1 FROM synapse.link x WHERE x.dataset_id = synapse.link.dataset_id "
                                   "AND x.src = synapse.link.src AND x.dst = %s AND x.type = 'about')",
                                   (a["id"], ds["id"], b["id"], a["id"]))
                    merged.append({"older": a["title"], "newer": b["title"], "cosine": round(c, 3), "links_moved": moved})
        st.data.update({"topics": len(topics), "merged": merged, "threshold": s.topic_merge_cosine})
    t.finish("done")
    return {"ok": True, "merged": merged, "trace": t.id}


def _copy(ds: dict, request, got: dict) -> dict:
    """A copy of a dataset's raw items and evaluation set, stored again (for D79's ingest-time comparisons)."""
    from rouh.synapse import datasets, db, evaluate, ingest, people

    person = who(request)
    name = got.get("name") or (ds["name"] + (" (decision models off)" if got.get("decision_models_off") else " (copy)"))
    # A copy of a set with its own people (an example) keeps its own people too, so fictional people never
    # reach the owner's real people set; a copy of a real set resolves against the same people set.
    from rouh import owner

    mine = owner.resolve(person)
    new = datasets.create(person, name, ds.get("about") or "",
                          owner_name=ds.get("owner_name") or (mine.name if mine else "") or owner.NOBODY,
                          own_people=not ds.get("people_id"))
    same = people.copy_people(ds, new)
    if got.get("decision_models_off"):
        datasets.tune(new, {"decision_models": False})
    items = db.rows("SELECT * FROM synapse.item WHERE dataset_id = %s AND deleted_at IS NULL AND kind NOT IN "
                    "('person', 'layer') AND source <> 'synapse' ORDER BY said_at NULLS FIRST, stored_at", (ds["id"],))
    topics = db.rows("SELECT * FROM synapse.item WHERE dataset_id = %s AND deleted_at IS NULL AND kind = 'topic' "
                     "AND source <> 'synapse'", (ds["id"],))
    payloads = []
    for it in topics + [i for i in items if i["kind"] != "topic"]:
        p = dict(it.get("meta") or {})
        p.update({"kind": it["kind"], "title": it["title"], "text": it["raw"], "source_key": it["source_key"],
                  "said_at": str(it["said_at"]) if it.get("said_at") else None,
                  "readers": [same.get(r, r) for r in ingest.readers_of(ds["id"], it["id"])],
                  "owner": same.get(it.get("owner"), it.get("owner")),
                  "sensitivity": it["sensitivity"] if it["sensitivity"] in ("private", "special") else None,
                  "gold_people": it.get("mentions_gold")})
        payloads.append(p)
    qs = evaluate.questions(ds)
    keys = {r["id"]: r["source_key"] for r in db.rows("SELECT id, source_key FROM synapse.item WHERE dataset_id = %s",
                                                      (ds["id"],))}

    def fill():
        from django.db import connection
        try:
            for p in payloads:
                ingest.store(new, p, by="copy", wait=True)
            for q in qs:
                evaluate.add_question(new, q["question"], gold=[keys.get(g) for g in q.get("gold") or []],
                                      facts=q.get("facts") or [], asker=same.get(q.get("asker"), q.get("asker")) or "",
                                      context=keys.get(q.get("context_item")) or "", forbidden=q.get("forbidden"),
                                      group=q.get("grp") or "")
        finally:
            connection.close()
    threading.Thread(target=fill, daemon=True).start()
    return {"ok": True, "dataset": new["id"], "items": len(payloads)}


# --- files ---------------------------------------------------------------------------------

def _parse_file(name: str, data: bytes) -> list[dict]:
    """An uploaded file as items (`rouh/synapse/parsing.py`, which the Gmail sync reads mail with too)."""
    from rouh.synapse import parsing

    return parsing.parse_file(name, data)
