"""The tools task 191 added for the "I can't" cases, checked (191-02 stage 4.1, 20 November 2026).

One check each, calling Rouh's own code the way a job's call reaches it and looking only at what
comes back: each new tool or action runs, and has its class in `rouh/job_policy.py`. Every person,
address and zone here is made up, on .example domains, and nothing reaches a service: Cloudflare's
and Google's stand-ins (`rouh/testing/`) answer in this process, and Reddit is a mock transport.
"""
from __future__ import annotations

import asyncio
import importlib.util
import os
import tempfile
import time
from pathlib import Path

from . import check, expect

CODE = Path(__file__).resolve().parent.parent.parent


def _cloudflare_stand_in():
    """`cloudflare.call` answered by the Cloudflare stand-in in this process, as over the wire."""
    from fastapi.testclient import TestClient

    from rouh import cloudflare
    from rouh.testing import fake_cloudflare as fc

    client = TestClient(fc.app)

    def call(token, method, path, body=None):
        r = client.request(method, path, json=body, headers={"Authorization": f"Bearer {token}"})
        out = r.json()
        if not out.get("success"):
            errs = out.get("errors") or []
            raise cloudflare.CFError("; ".join(f"{e.get('code')}: {e.get('message')}" for e in errs),
                                     codes=[e.get("code") for e in errs], status=r.status_code)
        return out

    return fc, call


@check("tools_191", "Cloudflare reads all settings and lists, deletes and puts back a mail rule",
       "zone_settings and email_routing_rules read and are reads; email_routing_rule_delete deletes one "
       "rule, keeps it for the undo, and is risky")
def cloudflare_rules() -> None:
    from rouh import cloudflare, job_policy as policy, unrestricted

    fc, call = _cloudflare_stand_in()
    before = cloudflare.call
    cloudflare.call = call
    try:
        api = cloudflare.ZoneAPI(fc.FIRST, fc.ZONES[fc.FIRST]["id"], "cfstand-first-zone-everything-0000000000000aaaa",
                                 fc.ACCOUNT)
        expect(any(line.startswith("http3:") for line in api.all_settings()), "zone_settings did not list every setting")
        if not any(a["email"] == "check@mail.example" for a in fc.ADDRESSES):
            fc.ADDRESSES.append({"id": "chk", "email": "check@mail.example", "verified": "2026-11-20"})
        api.email_rule("hello-check", "check@mail.example")
        expect(any("hello-check@" in line for line in api.email_rules()), "the rule made is not listed")
        undo: list = []
        unrestricted.UNDO.set(undo)
        api.email_rule_delete(address="hello-check")
        expect(not any("hello-check@" in line for line in api.email_rules()), "the rule was not deleted")
        api.put_back(undo[0]["ops"])
        expect(any("hello-check@" in line for line in api.email_rules()), "the undo did not make the rule again")
    finally:
        cloudflare.call = before
        unrestricted.UNDO.set(None)
    for action, klass in (("zone_settings", policy.READ), ("email_routing_rules", policy.READ),
                          ("email_routing_rule_delete", policy.RISKY)):
        expect(policy.classify("cloudflare", {"action": action}) == klass, f"cloudflare {action} is not {klass}")


@check("tools_191", "an account-wide Cloudflare token is kept for the other zones it passes for",
       "a token that sees two zones of the list is kept for both, a zone not on the list is left alone, "
       "and a zone whose own token passed keeps it", needs_db=True)
def cloudflare_one_token() -> None:
    from rouh import cloudflare
    from rouh.models import CloudflareZone

    from .unrestricted import _owner

    fc, call = _cloudflare_stand_in()
    who = _owner()
    before = cloudflare.call
    cloudflare.call = call
    try:
        CloudflareZone.objects.filter(org_id=str(who.org_id)).delete()
        for z in (fc.FIRST, fc.SECOND, "not-seen.rouh-check.example"):
            cloudflare.add_zone(who, z)
        got = cloudflare.save(who, fc.FIRST, "cfstand-both-zones-00000000000000000000000dddd")
        expect(got["also"] == [fc.SECOND], f"it was kept for {got['also']}, not for {fc.SECOND} alone")
        cloudflare.remove(who, fc.FIRST)
        cloudflare.remove(who, fc.SECOND)
        cloudflare.save(who, fc.SECOND, "cfstand-second-zone-no-purge-00000000000000bbbb")
        got = cloudflare.save(who, fc.FIRST, "cfstand-both-zones-00000000000000000000000dddd")
        last4 = {z["zone"]: (z["token"] or {}).get("last4") for z in got["zones"]}
        expect(got["also"] == [] and last4[fc.SECOND] == "bbbb", "a zone's own passing token was replaced")
    finally:
        cloudflare.call = before
        CloudflareZone.objects.filter(org_id=str(who.org_id)).delete()


@check("tools_191", "edit_slides adds, copies, moves and deletes slides",
       "one batch made from the deck as read puts a new slide, a copy, a move and a deletion where "
       "they were asked for, and a call that would leave no slide is refused")
def slides_shape() -> None:
    from fastapi.testclient import TestClient

    from rouh import slide_write
    from rouh.google_api.slides import deck_of
    from rouh.testing import fake_google

    c = TestClient(fake_google.build("http://check.example/cb", "cid", "secret"))
    c.post("/_deck", json={"id": "CHK", "name": "Check", "slides": [
        {"id": f"s{i}", "title": f"T{i}", "text": f"w{i}"} for i in range(1, 6)]})
    read = deck_of(c.get("/v1/presentations/CHK").json(), "CHK")
    requests, _lines, why = slide_write.plan(read, {
        "add_slides": [{"after": 2, "title": "New", "text": "words"}, {"copy_of": 5, "after": 0}],
        "move_slides": [{"slides": [4, 1], "after": 5}], "delete_slides": [3]})
    expect(not why, f"refused: {why}")
    r = c.post("/v1/presentations/CHK:batchUpdate", json={"requests": requests})
    expect(r.status_code == 200, f"the stand-in refused the batch: {r.text[:200]}")
    titles = [s["title"] for s in deck_of(c.get("/v1/presentations/CHK").json(), "CHK")["slides"]]
    expect(titles == ["T5", "T2", "New", "T5", "T1", "T4"], f"the deck came out as {titles}")
    _r, _l, why = slide_write.plan(read, {"delete_slides": [1, 2, 3, 4, 5]})
    expect("no slide" in why, "deleting every slide was not refused")


def _worker_mcp():
    spec = importlib.util.spec_from_file_location("rouh_worker_mcp_check", CODE / "rouh" / "worker_mcp.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@check("tools_191", "upload_drive_file reads a job's own file",
       "a path in a job's own folder is put in Rouh's one store for Rouh to read, a secret is never "
       "copied, and Rouh finds the staged copy and takes it away once read")
def upload_from_a_job() -> None:
    from rouh import tools
    from rouh.config import config

    wm = _worker_mcp()
    with tempfile.TemporaryDirectory() as base:
        store, job = os.path.join(base, "files"), os.path.join(base, "job")
        os.makedirs(store)
        os.makedirs(os.path.join(job, "out"))
        Path(job, "out", "deck.pdf").write_bytes(b"%PDF-1.4 check")
        Path(job, "out", ".env").write_text("A=1")
        was_env, was_dir, was_cwd = os.environ.get("ROUH_FILES_DIR"), config.files_dir, os.getcwd()
        os.environ["ROUH_FILES_DIR"] = store
        config.files_dir = store
        os.chdir(job)
        try:
            args, why = wm._stage({"path": "out/deck.pdf"})
            expect(not why and args["path"].startswith(os.path.realpath(store)), f"not staged: {why or args}")
            expect(Path(args["path"]).read_bytes() == b"%PDF-1.4 check", "the staged copy is not the file")
            expect(args["staged_from"].endswith("out/deck.pdf"), "where it came from is not said")
            _a, why = wm._stage({"path": "out/.env"})
            expect("secrets" in why, "a secret's name was staged")
            folder = tools._staged(args["path"])
            expect(folder and os.path.isdir(folder), "Rouh does not see the staged copy as one")
            tools._unstage(folder)
            expect(not os.path.exists(folder), "the staged copy was not taken away")
        finally:
            os.chdir(was_cwd)
            config.files_dir = was_dir
            if was_env is None:
                os.environ.pop("ROUH_FILES_DIR", None)
            else:
                os.environ["ROUH_FILES_DIR"] = was_env


@check("tools_191", "reddit_search reads Reddit's API, and its posts are boxed",
       "the public JSON is read, a refusal is said with how to give Rouh a Reddit app, an app's token "
       "is used when Reddit refuses, the posts are somebody else's words, and it is a read")
def reddit_search() -> None:
    import httpx

    from rouh import job_policy as policy, reddit, untrusted

    post = {"data": {"children": [{"data": {"title": "A post", "subreddit": "check", "author": "ana",
                                            "score": 1, "num_comments": 0, "created_utc": 1763500000,
                                            "permalink": "/r/check/comments/x/"}}]}}
    public = {"status": 200}

    def handler(req):
        if req.url.path.endswith(".json"):
            return httpx.Response(public["status"], json=post if public["status"] == 200 else {})
        if req.url.path == "/api/v1/access_token":
            return httpx.Response(200, json={"access_token": "check-token", "expires_in": 60})
        if req.headers.get("authorization") == "Bearer check-token":
            return httpx.Response(200, json=post)
        return httpx.Response(404)

    make = lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))  # noqa: E731
    expect(len(asyncio.run(reddit.search({"query": "rouh"}, client_factory=make))) == 1, "the public search found nothing")
    public["status"] = 403
    was = os.environ.pop(reddit.CLIENT_ID, None), os.environ.pop(reddit.CLIENT_SECRET, None)
    try:
        try:
            asyncio.run(reddit.search({"query": "rouh"}, client_factory=make))
            expect(False, "a refusal with no Reddit app was not said")
        except reddit.Refused as exc:
            expect("reddit.com/prefs/apps" in str(exc), "the refusal does not say how to give Rouh an app")
        os.environ[reddit.CLIENT_ID], os.environ[reddit.CLIENT_SECRET] = "check-app", "check-secret"
        reddit._token.clear()
        got = asyncio.run(reddit.search({"query": "rouh"}, client_factory=make))
        expect(len(got) == 1, "the app's token was not used when Reddit refused")
    finally:
        for name, value in zip((reddit.CLIENT_ID, reddit.CLIENT_SECRET), was):
            os.environ.pop(name, None) if value is None else os.environ.__setitem__(name, value)
        reddit._token.clear()
    expect(untrusted.is_wrapped(untrusted.wrap_for("reddit_search", reddit.render(got, "rouh"))),
           "Reddit's posts are not boxed as somebody else's words")
    expect(policy.classify("reddit_search", {}) == policy.READ, "reddit_search is not a read")


@check("tools_191", "database_read reads, masks credentials, and is the owner's own jobs' only",
       "a SELECT runs read only and is written down; a credential column comes back masked; a write, "
       "a credential named, a whole row made text and a second statement are refused; no other kind "
       "of job is listed it or may call it", needs_db=True)
def database_read() -> None:
    from rouh import db_read, encryption, job_gateway, job_policy as policy
    from rouh.models import CloudflareZone, JobRequest

    from .unrestricted import _owner, _scope

    who = _owner()
    CloudflareZone.objects.update_or_create(org_id=str(who.org_id), zone="db-read.rouh-check.example", defaults={
        "token_sealed": encryption.box().seal("check-token-not-real-0000"), "last4": "0000", "made_at": time.time()})
    scope = _scope(who, "check-db-read")
    try:
        got = asyncio.run(job_gateway.call(scope, policy.DATABASE_READ,
                                           {"sql": "SELECT * FROM cloudflare_zones WHERE zone LIKE 'db-read.%'"}))
        expect(got["ok"] and db_read.MASK in got["text"] and "gAAAAA" not in got["text"],
               f"the sealed token was not masked: {got['text'][:300]}")
        for sql in ("DELETE FROM users", "SELECT token_sealed FROM cloudflare_zones",
                    "SELECT row_to_json(z) FROM cloudflare_zones z", "SELECT 1; SELECT 2",
                    "WITH x AS (DELETE FROM users RETURNING 1) SELECT * FROM x"):
            got = asyncio.run(job_gateway.call(scope, policy.DATABASE_READ, {"sql": sql}))
            expect(not got["ok"], f"{sql!r} was not refused")
        expect(JobRequest.objects.filter(job_id="check-db-read", kind="database").count() >= 6,
               "the queries were not written down")
        for kind in (policy.CONTACT, policy.PROCESS, policy.BEAT):
            expect(policy.decide(kind, policy.DATABASE_READ, {"sql": "SELECT 1"}).verdict == policy.REFUSE,
                   f"a {kind} job may read the database")
            listed = asyncio.run(job_gateway.tools_for(_scope(who, "check-x", kind)))
            expect(policy.DATABASE_READ not in {t["name"] for t in listed}, f"a {kind} job is listed it")
        expect(policy.classify(policy.DATABASE_READ, {}) == policy.READ, "database_read is not a read")
    finally:
        CloudflareZone.objects.filter(zone="db-read.rouh-check.example").delete()
        JobRequest.objects.filter(job_id="check-db-read").delete()


@check("tools_191", "a run is warned before it is ended for its memory",
       "at four fifths of ONE_RUN_MEMORY_MAX the holder types one warning into the run's own terminal, "
       "telling it to commit what it has, and does not type it twice")
def memory_warning() -> None:
    from one import holder as h

    read, write = os.pipe()
    os.set_blocking(read, False)
    try:
        run = h.Holder(tempfile.gettempdir(), ["true"])
        run.master, run.limit = write, 100 * 1048576

        class Procs:
            used = 85 * 1048576

            def memory(self):
                return self.used

            def signal(self, _sig):
                pass

        run.procs = Procs()
        run._watch()
        run.enter_at = time.monotonic() - 1
        run.watched_at = 0.0
        run._watch()
        typed = os.read(read, 65536).decode("utf-8", "replace")
        expect("commit what you have" in typed and typed.endswith("\r"), f"the run was not warned: {typed[:200]!r}")
        expect(not run.over_memory, "a run under its limit was ended")
        run.watched_at = 0.0
        run._watch()
        try:
            again = os.read(read, 65536)
        except BlockingIOError:
            again = b""
        expect(not again, "the warning was typed twice")
    finally:
        os.close(read)
        os.close(write)
