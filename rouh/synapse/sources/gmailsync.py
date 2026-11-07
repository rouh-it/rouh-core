"""Every email of a Gmail inbox, kept in Synapse Master, all the time (card 1163, 5 October 2026).

Petar, by voice: "Build a continuous, reliable sync of ALL mail from Gmail into
Synapse Master ... first for Rouh's own inbox ONLY ... make the
inbox a setting (a list of inboxes, starting with just rouh) and have
my own address added later by config alone, no code change."

**Which inboxes.** One row of `synapse.mail_sync` per Master dataset and inbox
(migration 0081, which put in Rouh's own address on the
server). `manage.py synapse_mail add <address>` adds another and `remove`
stops one. An address is read as Rouh's own Google connection when it is
that connection's, and otherwise as one of the person's own mailboxes,
connected read-only in Settings (`mailboxes.py`): every request here is a GET,
which a read-only mailbox answers the same way.

**New mail.** Gmail's history from the last history id read (`history.list`,
every kind of record: messages added and deleted, labels added and taken off)
is read every minute, and at once when Gmail's push reaches Rouh
(`/hooks/gmail/`, the Pub/Sub topic mail alerts already set up; `pushed`).
What changed becomes jobs on Synapse's own queue (`synapse.job`, kinds
`mail_add`, `mail_delete`, `mail_labels`), and only once they are written
there is the history id moved on, so a restart between the two reads the same
changes again and the queue takes each once. When Gmail no longer keeps history
that far back (its 404), the whole id list is read instead and only what is
missing is queued. The watch Gmail pushes for is mail alerts' own, renewed
daily there; when mail alerts is off, this renews it daily itself (`_watch`).

**Backfill.** Every message in the mailbox, spam and the Bin included, is
listed a page at a time, the page token saved after each page is queued, so a
restart carries on from the page it was on. Its jobs go on the queue's
backfill lane, which never takes a slot live mail needs, oldest first (a Gmail
id carries the time it arrived, `_arrived`). Drafts are left out until sent.

**Once each.** An email's key is `gmail:<inbox>:<Gmail id>`. A job for a key
already waiting is not queued twice, every job holds a lock on its key while it
runs, and a job finds what is already stored before it stores anything. The
email is read with the lab's own parser (`parsing.py`) and stored with its
files (`mailfiles.py`: the same bytes are one item, linked `attached` to each
email they came on) through `batch.store_many`. The owner is its only reader.

**Deletes and labels follow Gmail.** A message Gmail deleted for good
(checked with Gmail before anything is deleted here) is deleted with
everything made from it (`ingest.delete`), and a file no other email holds goes
with it. Labels and the folder (inbox, sent, archived, spam, trash) are kept on
the item as `meta.gmail`, written in place without asking a model again; spam
and the Bin get the junk prior when a question walks to them (`walk.prior`).

**Every night** Gmail's whole id list is compared with Synapse's items of that
inbox: what is missing is queued, what Gmail no longer has is deleted, and
the owner hears on Telegram only if the two still differ after that (`reconcile`).

**Health** is `health`: the last push, the last history read and whether it
worked, the cursor, the backfill, the backlog, failures, the last
reconciliation, what it cost. A sync with no good history read for 15 minutes
is flagged. The lab's homepage shows it for Master, and so does
`manage.py synapse_mail status`.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import threading
import time
from datetime import datetime, timezone

from .. import db
from ..db import Json

log = logging.getLogger("rouh.synapse.gmail")

SOURCE = "gmail"
KINDS = ("mail_add", "mail_delete", "mail_labels")
#: How often each inbox's history is read when no push comes (seconds).
POLL_SECONDS = float(os.environ.get("SYNAPSE_GMAIL_POLL_SECONDS") or 60)
#: A sync with no good history read for this long is flagged.
STALE_MINUTES = 15
#: Backfill pages listed per beat, 500 ids each, so a big mailbox never holds up the history read.
PAGES_PER_BEAT = 4
#: The nightly reconciliation starts after this hour on the machine's own clock,
#: once a day, before the database's own backup at 03:40.
RECONCILE_HOUR = 2
#: How long a reconciliation waits for what it queued before comparing again (seconds).
RECONCILE_WAIT = float(os.environ.get("SYNAPSE_GMAIL_RECONCILE_WAIT") or 1800)
#: A watch made here is made again once it is this old (seconds), as mail alerts does.
WATCH_EVERY = 23 * 3600
#: Priorities on the queue: live mail ahead of the model parts (4). The backfill is level with them,
#: so its emails, each dated by when it arrived, are taken before model parts queued since, and an
#: email is stored (and found by its words) long before its own model part comes round.
LIVE_PRIORITY, BACKFILL_PRIORITY = 3, 4
#: More missing than this after Gmail lost its history, or at night, goes on the backfill lane.
LIVE_AT_MOST = 50


def key_of(inbox: str, message_id: str) -> str:
    return f"gmail:{inbox}:{message_id}"


def prefix_of(inbox: str) -> str:
    return f"gmail:{inbox}:"


def clean_inbox(address: str) -> str:
    return " ".join(str(address or "").split()).lower()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _arrived(message_id: str) -> datetime | None:
    """When a message reached Gmail, from its id alone: a Gmail id is the arrival time in
    milliseconds shifted left by 20 bits. None for an id of another shape (a test's)."""
    try:
        ms = int(message_id, 16) >> 20
    except (TypeError, ValueError):
        return None
    if not 946684800000 < ms < time.time() * 1000 + 86400000:
        return None
    return datetime.fromtimestamp(ms / 1000, timezone.utc)


def folder_of(labels) -> str:
    held = set(labels or ())
    for label, name in (("TRASH", "trash"), ("SPAM", "spam"), ("DRAFT", "draft"), ("INBOX", "inbox"),
                        ("SENT", "sent")):
        if label in held:
            return name
    return "archived"


# ---------------------------------------------------------------------------------------------
# the inboxes, as a setting
# ---------------------------------------------------------------------------------------------

def rows(enabled_only: bool = True) -> list[dict]:
    """Every inbox kept in a Master dataset, with its dataset's owner."""
    if not db.value("SELECT to_regclass('synapse.mail_sync') IS NOT NULL"):
        return []
    return db.rows("SELECT s.*, d.org_id, d.user_id, d.name AS dataset_name FROM synapse.mail_sync s "
                   "JOIN synapse.dataset d ON d.id = s.dataset_id WHERE d.master"
                   + (" AND s.enabled" if enabled_only else "") + " ORDER BY s.added_at, s.inbox")


def row_of(ds_id: str, inbox: str) -> dict | None:
    return db.row("SELECT s.*, d.org_id, d.user_id FROM synapse.mail_sync s JOIN synapse.dataset d ON "
                  "d.id = s.dataset_id WHERE s.dataset_id = %s AND s.inbox = %s", (str(ds_id), clean_inbox(inbox)))


def add(ds: dict, address: str, *, by: str = "command") -> dict:
    """Keep this inbox in this Master: `rouh` (or "") is Rouh's own Google connection. Checked
    against what is connected first, so a typo is said rather than kept."""
    inbox = clean_inbox(address)
    if inbox in ("", "rouh", "rouh's", "own"):
        inbox = rouh_address(ds)
        if not inbox:
            raise ValueError("Rouh's Google account is not connected, so there is no inbox of Rouh's to keep.")
    kind, _ = kind_of(ds, inbox)
    if not kind:
        raise ValueError(f"{inbox} is neither Rouh's Google connection nor one of the person's own mailboxes "
                         "connected in Settings, so it cannot be read.")
    db.run("INSERT INTO synapse.mail_sync (dataset_id, inbox, added_by) VALUES (%s, %s, %s) "
           "ON CONFLICT (dataset_id, inbox) DO UPDATE SET enabled = true, updated_at = now()",
           (str(ds["id"]), inbox, by[:80]))
    wake()
    return {"inbox": inbox, "kind": kind}


def remove(ds: dict, address: str) -> int:
    """Stop keeping an inbox. What is stored stays, and its jobs still waiting are dropped."""
    inbox = clean_inbox(address)
    n = db.run("UPDATE synapse.mail_sync SET enabled = false, updated_at = now() WHERE dataset_id = %s AND inbox = %s",
               (str(ds["id"]), inbox))
    db.run("UPDATE synapse.job SET done_at = now(), error = 'its inbox is no longer kept' WHERE dataset_id = %s "
           "AND done_at IS NULL AND kind = ANY(%s) AND payload->>'inbox' = %s", (str(ds["id"]), list(KINDS), inbox))
    return n


def rouh_address(ds: dict) -> str:
    """The address of Rouh's own Google connection for this dataset's owner, or ""."""
    try:
        return clean_inbox(db.value("SELECT google_email FROM google_connections WHERE user_id = %s AND org_id = %s",
                                    (str(ds["user_id"]), str(ds["org_id"]))) or "")
    except Exception:  # noqa: BLE001 - a database without Google's table
        return ""


def kind_of(ds: dict, inbox: str) -> tuple[str, int | None]:
    """("rouh", None) for Rouh's own connection, ("read-only", mailbox id) for one of the person's,
    ("", None) for neither."""
    if inbox and inbox == rouh_address(ds):
        return "rouh", None
    try:
        got = db.value("SELECT id FROM read_mailboxes WHERE user_id = %s AND org_id = %s AND lower(email) = %s "
                       "ORDER BY id LIMIT 1", (str(ds["user_id"]), str(ds["org_id"]), inbox))
    except Exception:  # noqa: BLE001
        got = None
    return ("read-only", int(got)) if got else ("", None)


# ---------------------------------------------------------------------------------------------
# reaching Gmail, from a thread of Synapse's own
# ---------------------------------------------------------------------------------------------

class NotReadable(RuntimeError):
    """The inbox cannot be read now: not connected, or the connection needs the person."""


def _open(ds: dict, inbox: str):
    """(a `google_api.Gmail` for this inbox, the owner). Made fresh for each use: Google's
    clients keep asyncio locks, which belong to the event loop that made them."""
    from ...config import config
    from ...encryption import SecretBox
    from ...google_api import Gmail, GoogleClients
    from ...google_oauth import GoogleAuth
    from ...google_store import GoogleStore
    from ...tenancy import Identity

    who = Identity(user_id=str(ds["user_id"]), org_id=str(ds["org_id"]))
    kind, mailbox_id = kind_of(ds, inbox)
    if not kind:
        raise NotReadable(f"{inbox} is not connected: neither Rouh's Google account nor a mailbox in Settings.")
    box = SecretBox(config.encryption_key, data_dir=config.data_dir)
    store = GoogleStore(None, box)
    auth = GoogleAuth(store, config)
    if kind == "rouh":
        return Gmail(GoogleClients(auth, config), who), who
    from ...inboxes import ReadOnlyClients
    from ...mailboxes import MailboxAuth, MailboxStore, ReadOnlyGmail

    mailboxes = MailboxStore(box)
    mailbox_auth = MailboxAuth(store, auth, mailboxes, config)
    mailbox = mailboxes.mailbox(who, mailbox_id)
    if mailbox is None:
        raise NotReadable(f"{inbox} is not connected any more.")
    return Gmail(ReadOnlyClients(ReadOnlyGmail(mailbox_auth, mailbox, config)), who), who


def _run(who, coro):
    """One request to Gmail, on an event loop of this thread's own."""
    from ...tenancy import speaking

    with speaking(who):
        return asyncio.run(coro)


def _gone(exc: Exception) -> bool:
    return getattr(exc, "status", 0) == 404


_names: dict[str, tuple[float, dict]] = {}


def _label_names(gmail, who, inbox: str) -> dict:
    """Gmail's label ids and the names a person sees, kept an hour."""
    got = _names.get(inbox)
    if got and time.time() - got[0] < 3600:
        return got[1]
    try:
        names = {one["id"]: one["name"] for one in _run(who, gmail.labels()) if one.get("id")}
    except Exception:  # noqa: BLE001 - names are a kindness; ids are kept anyway
        names = {}
    _names[inbox] = (time.time(), names)
    return names


# ---------------------------------------------------------------------------------------------
# the queue
# ---------------------------------------------------------------------------------------------

def queue(ds_id: str, inbox: str, kind: str, message_ids, *, lane: str = "live",
          priority: int | None = None) -> int:
    """Jobs for these messages, each once: a key already stored (or deleted in Synapse) is not
    queued to be added again, and a job of the same kind still waiting for the same key is that
    job (moved to the live lane when live mail asks for it). Returns how many were made."""
    from .. import worker

    ids = list(dict.fromkeys(str(m) for m in message_ids if m))
    if not ids:
        return 0
    lane = "backfill" if lane == "backfill" else "live"
    priority = priority if priority is not None else (BACKFILL_PRIORITY if lane == "backfill" else LIVE_PRIORITY)
    keys = {key_of(inbox, m): m for m in ids}
    made = 0
    with db.atomic():
        db.run("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"synapse.mail.queue:{ds_id}:{inbox}",))
        if kind == "mail_add":
            have = {r["source_key"] for r in db.rows(
                "SELECT source_key FROM synapse.item WHERE dataset_id = %s AND source = %s AND source_key = ANY(%s)",
                (ds_id, SOURCE, list(keys)))}
        else:
            have = set()
        waiting = {}
        for r in db.rows("SELECT id, payload->>'key' AS key, lane, locked_by FROM synapse.job WHERE dataset_id = %s "
                         "AND kind = %s AND done_at IS NULL AND payload->>'key' = ANY(%s)", (ds_id, kind, list(keys))):
            # A labels or delete job already running may have read Gmail before this change: a new one
            # runs after it. An add running is an add.
            if r["locked_by"] is None or kind == "mail_add":
                waiting[r["key"]] = r
        new = [(k, m) for k, m in keys.items() if k not in have and k not in waiting]
        if new:
            times = [_arrived(m) if lane == "backfill" else None for _, m in new]
            db.run("INSERT INTO synapse.job (dataset_id, kind, payload, priority, not_before, lane) "
                   "SELECT %s, %s, jsonb_build_object('inbox', %s::text, 'id', u.m, 'key', u.k), %s, "
                   "least(now(), coalesce(u.t, now())), %s FROM unnest(%s::text[], %s::text[], %s::timestamptz[]) "
                   "AS u(m, k, t)",
                   (ds_id, kind, inbox, priority, lane, [m for _, m in new], [k for k, _ in new], times))
            made = len(new)
        if lane == "live":
            promote = [r["id"] for r in waiting.values() if r["lane"] == "backfill" and r["locked_by"] is None]
            if promote:
                db.run("UPDATE synapse.job SET lane = 'live', priority = least(priority, %s), not_before = now() "
                       "WHERE id = ANY(%s)", (priority, promote))
    if made:
        worker.poke()
    return made


@contextlib.contextmanager
def _held(key: str):
    """One job at a time per message, in any process: a lock on its key while it runs."""
    db.run("SELECT pg_advisory_lock(hashtext(%s))", ("synapse.mail:" + key,))
    try:
        yield
    finally:
        db.run("SELECT pg_advisory_unlock(hashtext(%s))", ("synapse.mail:" + key,))


def run_job(ds: dict, job: dict) -> str:
    """The worker's side of one message's job. Returns what happened, in words, for the log."""
    p = job.get("payload") or {}
    inbox, mid = clean_inbox(p.get("inbox")), str(p.get("id") or "")
    if not inbox or not mid:
        return "nothing to do: the job names no message"
    key = key_of(inbox, mid)
    with _held(key):
        if job["kind"] == "mail_add":
            said = _add(ds, inbox, mid, key, lane=job.get("lane") or "live")
        elif job["kind"] == "mail_delete":
            said = _delete(ds, inbox, mid, key, job_id=job.get("id"))
        else:
            said = _labels(ds, inbox, mid, key)
    log.info("Synapse mail %s %s: %s", job["kind"], key, said)
    return said


def _item(ds_id: str, key: str) -> dict | None:
    return db.row("SELECT id, status, deleted_at, meta, title FROM synapse.item WHERE dataset_id = %s AND source = %s "
                  "AND source_key = %s ORDER BY stored_at DESC LIMIT 1", (ds_id, SOURCE, key))


def _gmail_meta(inbox: str, mid: str, thread: str, label_ids, names: dict, internal_ms: int = 0) -> dict:
    ids = list(label_ids or [])
    out = {"inbox": inbox, "id": mid, "thread_id": thread, "label_ids": ids,
           "labels": [names.get(x, x) for x in ids], "folder": folder_of(ids), "unread": "UNREAD" in ids,
           "starred": "STARRED" in ids}
    if internal_ms:
        out["arrived_at"] = datetime.fromtimestamp(internal_ms / 1000, timezone.utc).isoformat()
    return out


def _add(ds: dict, inbox: str, mid: str, key: str, *, lane: str) -> str:
    from .. import batch, datasets
    from . import parsing
    from ...google_api import GoogleSaidNo

    ds_id = str(ds["id"])
    item = _item(ds_id, key)
    if item and item.get("deleted_at") is not None:
        return "deleted in Synapse, so kept out (D60)"
    if item and item["status"] == "stored":
        # Its code part was cut off half way (a restart): what was written goes, and it is stored whole.
        db.run("DELETE FROM synapse.item WHERE id = %s AND status = 'stored'", (item["id"],))
        item = None
    gmail, who = _open(ds, inbox)
    try:
        got = _run(who, gmail.raw(mid))
    except GoogleSaidNo as exc:
        if _gone(exc):
            return "gone from Gmail before it was read"
        raise
    if "DRAFT" in got["labels"]:
        return "a draft, left out until it is sent"
    names = _label_names(gmail, who, inbox)
    gm = _gmail_meta(inbox, mid, got["thread_id"], got["labels"], names, got["internal_ms"])
    parts = parsing.parse_file(f"{mid}.eml", got["raw"], mail_key=key, source=SOURCE)
    mail, files = parts[0], parts[1:]
    if item:
        _set_labels(ds, item, gm)
        if (item.get("meta") or {}).get("gmail", {}).get("files_done"):
            return "already stored; labels read again"
        return "already stored; " + _store_files(ds, item["id"], files, lane)
    me = datasets.me(ds)
    cats = [x.split("_", 1)[1].lower() for x in got["labels"] if x.startswith("CATEGORY_")]
    if cats:
        mail.setdefault("headers", {})["category"] = cats[0]
    if "STARRED" in got["labels"]:
        mail["starred"] = True
    if not mail.get("said_at") and got["internal_ms"]:
        mail["said_at"] = gm["arrived_at"]
    mail.update({"source": SOURCE, "source_key": key, "gmail": gm, "readers": [me], "owner": me})
    report = batch.store_many(ds, [[mail, *files]], by="gmail", concurrency=1, wait=False, lane=lane, mind_cap=False)
    first = report["rows"][0] if report["rows"] else {}
    if not first.get("ok"):
        if first.get("error"):
            raise RuntimeError(f"the email could not be stored: {first['error']}")
        return f"not stored: {first.get('why') or 'no reason given'}"
    bad = [r for r in report["rows"][1:] if not r.get("ok") and r.get("error")]
    if bad:
        raise RuntimeError(f"{len(bad)} of its {len(files)} files could not be stored: {bad[0]['error']}")
    _files_done(first["item"])
    return f"stored with {len(files)} file{'s' if len(files) != 1 else ''}"


def _store_files(ds: dict, item_id: str, files: list[dict], lane: str) -> str:
    """The files of an email stored before its files were (a restart between the two)."""
    from .. import batch

    if files:
        report = batch.store_many(ds, [list(files)], by="gmail", concurrency=1, wait=False, lane=lane, mind_cap=False)
        bad = [r for r in report["rows"] if not r.get("ok") and r.get("error")]
        if bad:
            raise RuntimeError(f"{len(bad)} of its {len(files)} files could not be stored: {bad[0]['error']}")
    _files_done(item_id)
    return f"its {len(files)} file{'s' if len(files) != 1 else ''} stored now"


def _files_done(item_id: str) -> None:
    db.run("UPDATE synapse.item SET meta = jsonb_set(meta, '{gmail,files_done}', 'true'::jsonb, true) "
           "WHERE id = %s AND meta ? 'gmail'", (item_id,))


def _set_labels(ds: dict, item: dict, gm: dict) -> bool:
    """The item's Gmail labels and folder as Gmail has them now; written in place, no model asked.
    A change of folder or of a label a person gave is written on the item's history too."""
    from ..trace import Trace

    meta = item.get("meta") or {}
    was = meta.get("gmail") or {}
    now = {**was, **gm, "files_done": bool(was.get("files_done"))}
    if was.get("label_ids") == now.get("label_ids") and was.get("folder") == now.get("folder"):
        return False
    db.run("UPDATE synapse.item SET meta = jsonb_set(meta, '{gmail}', %s::jsonb, true), updated_at = now() "
           "WHERE id = %s", (Json(now), item["id"]))
    seen_only = {"UNREAD"}
    before, after = set(was.get("label_ids") or []), set(now.get("label_ids") or [])
    if was.get("folder") != now.get("folder") or (before ^ after) - seen_only:
        trace = Trace(ds["id"], "edit", f"Gmail labels: {item.get('title') or ''}"[:300], by="gmail",
                      item_id=item["id"])
        named = {**dict(zip(was.get("label_ids") or [], was.get("labels") or [])),
                 **dict(zip(now.get("label_ids") or [], now.get("labels") or []))}
        with trace.step("labels", "Its labels and folder in Gmail, kept on the item (no model asked)") as st:
            st.data.update({"folder": {"before": was.get("folder"), "after": now.get("folder")},
                            "added": sorted(named.get(x, x) for x in after - before),
                            "removed": sorted(named.get(x, x) for x in before - after),
                            "junk_prior": now.get("folder") in ("spam", "trash")})
        trace.finish("done")
    return True


def _delete(ds: dict, inbox: str, mid: str, key: str, *, job_id=None, checked: bool = False) -> str:
    """Gmail deleted it for good: the item goes with everything made from it, and so does each
    of its files no other email holds. Gmail is asked first, unless the caller just did."""
    from .. import ingest
    from ...google_api import GoogleSaidNo

    ds_id = str(ds["id"])
    item = _item(ds_id, key)
    if not item or item.get("deleted_at") is not None:
        _drop_waiting(ds_id, key, job_id)
        return "nothing stored to delete"
    if not checked:
        gmail, who = _open(ds, inbox)
        try:
            labels = _run(who, gmail.labels_now(mid))
        except GoogleSaidNo as exc:
            if not _gone(exc):
                raise
        else:
            _set_labels(ds, item, _gmail_meta(inbox, mid, (item.get("meta") or {}).get("gmail", {}).get("thread_id", ""),
                                              labels, _label_names(gmail, who, inbox)))
            return "Gmail still has it, so it stays; its labels were read again"
    files = db.rows("SELECT id, meta FROM synapse.item WHERE dataset_id = %s AND deleted_at IS NULL AND "
                    "meta->'attached_to' ? %s", (ds_id, key))
    ingest.delete(ds, item["id"], by="gmail")
    gone = kept = 0
    for f in files:
        others = [k for k in (f.get("meta") or {}).get("attached_to") or [] if k != key and ingest.find_by_key(ds_id, k)]
        if others:
            db.run("UPDATE synapse.item SET meta = jsonb_set(meta, '{attached_to}', %s::jsonb), updated_at = now() "
                   "WHERE id = %s", (Json(others), f["id"]))
            kept += 1
            continue
        ingest.delete(ds, f["id"], by="gmail")
        # Its key freed: it went because its email did, so the same file on a new email is stored again.
        db.run("UPDATE synapse.item SET source_key = source_key || '#gone-' || floor(extract(epoch FROM now())) "
               "WHERE id = %s", (f["id"],))
        gone += 1
    _drop_waiting(ds_id, key, job_id)
    return f"deleted, with {gone} file{'s' if gone != 1 else ''}" + (f"; {kept} kept for other emails" if kept else "")


def _drop_waiting(ds_id: str, key: str, but=None) -> None:
    db.run("UPDATE synapse.job SET done_at = now(), error = '' WHERE dataset_id = %s AND done_at IS NULL "
           "AND locked_by IS NULL AND kind = ANY(%s) AND payload->>'key' = %s AND id <> %s",
           (ds_id, ["mail_add", "mail_labels"], key, int(but or 0)))


def _labels(ds: dict, inbox: str, mid: str, key: str) -> str:
    from ...google_api import GoogleSaidNo

    ds_id = str(ds["id"])
    gmail, who = _open(ds, inbox)
    try:
        labels = _run(who, gmail.labels_now(mid))
    except GoogleSaidNo as exc:
        if _gone(exc):
            return _delete(ds, inbox, mid, key, checked=True)
        raise
    if "DRAFT" in labels:
        return "a draft, left out until it is sent"
    item = _item(ds_id, key)
    if item and item.get("deleted_at") is not None:
        return "deleted in Synapse, so kept out (D60)"
    if not item or item["status"] == "stored":
        n = queue(ds_id, inbox, "mail_add", [mid], lane="live")
        return "not stored yet, so queued to be stored" if n else "not stored yet; it is already queued"
    thread = (item.get("meta") or {}).get("gmail", {}).get("thread_id", "")
    changed = _set_labels(ds, item, _gmail_meta(inbox, mid, thread, labels, _label_names(gmail, who, inbox)))
    return f"labels now {', '.join(labels) or 'none'}" if changed else "labels unchanged"


# ---------------------------------------------------------------------------------------------
# reading Gmail's history, and the backfill's listing
# ---------------------------------------------------------------------------------------------

def _set(ds_id: str, inbox: str, **fields) -> None:
    if not fields:
        return
    names = list(fields)
    values = [Json(v) if isinstance(v, (dict, list)) else v for v in fields.values()]
    db.run("UPDATE synapse.mail_sync SET " + ", ".join(f"{n} = %s" for n in names) + ", updated_at = now() "
           "WHERE dataset_id = %s AND inbox = %s", (*values, ds_id, inbox))


def _plan(records: list[dict], plan: dict) -> None:
    """Gmail's history records, in order, as one thing to do per message: add, delete, labels,
    or nothing for a draft. A later record wins, except that an add is never undone by a
    label change, and a delete is final."""
    for rec in records:
        for a in rec.get("messagesAdded") or []:
            m = a.get("message") or {}
            if m.get("id") and plan.get(m["id"]) != "delete":
                plan[m["id"]] = "draft" if "DRAFT" in (m.get("labelIds") or []) else "add"
        for a in rec.get("messagesDeleted") or []:
            m = a.get("message") or {}
            if m.get("id"):
                plan[m["id"]] = "delete"
        for field in ("labelsAdded", "labelsRemoved"):
            for a in rec.get(field) or []:
                m = a.get("message") or {}
                if not m.get("id") or plan.get(m["id"]) in ("add", "delete"):
                    continue
                plan[m["id"]] = "draft" if "DRAFT" in (m.get("labelIds") or []) else "labels"


def read_history(ds: dict, row: dict) -> dict:
    """Everything that changed in one inbox since its history id, queued, and only then the
    history id moved on. Gmail's 404 (history gone) lists the whole mailbox instead."""
    from ...google_api import HistoryGone

    ds_id, inbox = str(ds["id"]), row["inbox"]
    gmail, who = _open(ds, inbox)
    start = str(row.get("history_id") or "")
    if not start:
        # The first look: where the mailbox is now is where new mail starts; the backfill lists the rest.
        now = _run(who, gmail.profile())
        if not now["history_id"]:
            raise RuntimeError("Gmail did not say which history id the mailbox is at")
        _set(ds_id, inbox, history_id=now["history_id"], last_history_at=_now(), last_history_ok_at=_now(),
             history_failures=0, history_error="", backfill_state=row.get("backfill_state") or "listing",
             backfill_started_at=row.get("backfill_started_at") or _now())
        return {"started_at": now["history_id"]}
    plan: dict[str, str] = {}
    latest, token = start, ""
    try:
        while True:
            page = _run(who, gmail.changes(start, page_token=token))
            latest = page["history_id"] or latest
            _plan(page["history"], plan)
            token = page["next"]
            if not token:
                break
    except HistoryGone:
        return relist(ds, row, gmail, who)
    by = {"add": [], "delete": [], "labels": []}
    for mid, what in plan.items():
        if what in by:
            by[what].append(mid)
    made = {"added": queue(ds_id, inbox, "mail_add", by["add"]),
            "deleted": queue(ds_id, inbox, "mail_delete", by["delete"]),
            "labels": queue(ds_id, inbox, "mail_labels", by["labels"]),
            "drafts_left_out": sum(1 for w in plan.values() if w == "draft")}
    # Queued first, then the cursor: a restart between the two reads these changes again, and the
    # queue takes each once.
    _set(ds_id, inbox, history_id=latest, last_history_at=_now(), last_history_ok_at=_now(), history_failures=0,
         history_error="", last_history_counts={**made, "from": start, "to": latest})
    return made


def gmail_ids(gmail, who) -> tuple[set[str], set[str]]:
    """(every message id in the mailbox, spam and the Bin included, drafts left out; the drafts')."""
    ids: set[str] = set()
    token = ""
    while True:
        page, token = _run(who, gmail.listing(page_token=token))
        ids.update(page)
        if not token:
            break
    drafts = _run(who, gmail.draft_message_ids())
    return ids - drafts, drafts


def synapse_ids(ds_id: str, inbox: str) -> tuple[set[str], set[str]]:
    """(the Gmail ids of this inbox's emails stored and not deleted; those deleted in Synapse)."""
    pre = prefix_of(inbox)
    live, dead = set(), set()
    for r in db.rows("SELECT source_key, deleted_at IS NOT NULL AS dead FROM synapse.item WHERE dataset_id = %s "
                     "AND source = %s AND kind = 'mail' AND source_key LIKE %s", (ds_id, SOURCE, pre + "%")):
        (dead if r["dead"] else live).add(r["source_key"][len(pre):])
    return live, dead


def relist(ds: dict, row: dict, gmail, who) -> dict:
    """Gmail no longer has history from where this inbox was read: the whole id list is read and only
    what is missing is queued, and reading history starts again from where the mailbox is now."""
    ds_id, inbox = str(ds["id"]), row["inbox"]
    now = _run(who, gmail.profile())
    ids, _ = gmail_ids(gmail, who)
    live, dead = synapse_ids(ds_id, inbox)
    missing = sorted(ids - live - dead)
    lane = "live" if len(missing) <= LIVE_AT_MOST else "backfill"
    made = queue(ds_id, inbox, "mail_add", missing, lane=lane)
    said = (f"Gmail no longer had this inbox's history from {row.get('history_id')}, so the whole mailbox was "
            f"listed ({len(ids)} messages) and {made} missing were queued; history is read from {now['history_id']} on.")
    _set(ds_id, inbox, history_id=now["history_id"], last_history_at=_now(), last_history_ok_at=_now(),
         history_failures=0, history_error=said,
         last_history_counts={"relisted": len(ids), "added": made, "from": row.get("history_id"), "to": now["history_id"]})
    log.warning("Synapse mail %s: %s", inbox, said)
    return {"relisted": len(ids), "added": made}


def list_backfill(ds: dict, row: dict, pages: int = PAGES_PER_BEAT) -> dict:
    """The next pages of the whole mailbox queued on the backfill lane, the page token saved after
    each page is queued, so a restart carries on from that page."""
    from ...google_api import GoogleSaidNo

    ds_id, inbox = str(ds["id"]), row["inbox"]
    gmail, who = _open(ds, inbox)
    drafts = _run(who, gmail.draft_message_ids())
    token, listed, made = str(row.get("backfill_token") or ""), int(row.get("backfill_listed") or 0), 0
    for _ in range(max(1, pages)):
        try:
            ids, following = _run(who, gmail.listing(page_token=token))
        except GoogleSaidNo as exc:
            if token and getattr(exc, "status", 0) == 400:
                # A page token Gmail no longer takes: listed again from the start; nothing is queued twice.
                _set(ds_id, inbox, backfill_token="", backfill_listed=0)
                return {"restarted": True}
            raise
        made += queue(ds_id, inbox, "mail_add", [m for m in ids if m not in drafts], lane="backfill")
        listed += len(ids)
        token = following
        if not token:
            _set(ds_id, inbox, backfill_token="", backfill_listed=listed, backfill_state="listed",
                 backfill_listed_at=_now())
            return {"listed": listed, "queued": made, "done": True}
        _set(ds_id, inbox, backfill_token=token, backfill_listed=listed)
    return {"listed": listed, "queued": made, "done": False}


# ---------------------------------------------------------------------------------------------
# the watch Gmail pushes for, when mail alerts is not keeping it
# ---------------------------------------------------------------------------------------------

def _watch(ds: dict, row: dict) -> None:
    """Gmail's watch on Rouh's own inbox, made daily. Mail alerts makes the same watch (the INBOX
    label, the organisation's topic) when it is on, and then it is left to it; a read-only mailbox
    cannot be watched (its grant makes GET requests only), so it is read every minute."""
    ds_id, inbox = str(ds["id"]), row["inbox"]
    kind, _ = kind_of(ds, inbox)
    if kind != "rouh":
        if row.get("watch_by") != "none":
            _set(ds_id, inbox, watch_by="none", watch_error="A mailbox connected read-only cannot be watched, so "
                                                          "its history is read every minute.")
        return
    alerts = None
    with contextlib.suppress(Exception):
        alerts = db.row("SELECT enabled, watch_expires_at, watch_renewed_at, mailbox FROM mail_alerts WHERE "
                        "user_id = %s AND org_id = %s", (str(ds["user_id"]), str(ds["org_id"])))
    if alerts and alerts["enabled"] and clean_inbox(alerts["mailbox"]) == inbox and \
            time.time() - float(alerts["watch_renewed_at"] or 0) < WATCH_EVERY + 3 * 3600:
        _set(ds_id, inbox, watch_by="mail alerts", watch_error="",
             watch_expires_at=datetime.fromtimestamp(float(alerts["watch_expires_at"] or 0), timezone.utc),
             watch_renewed_at=datetime.fromtimestamp(float(alerts["watch_renewed_at"] or 0), timezone.utc))
        return
    renewed = row.get("watch_renewed_at")
    if row.get("watch_by") == "sync" and renewed and (_now() - renewed).total_seconds() < WATCH_EVERY:
        return
    if row.get("watch_by") == "no topic" and renewed and (_now() - renewed).total_seconds() < 3600:
        return
    from ...config import config
    from ...encryption import SecretBox
    from ...mail_alerts import AlertStore

    topic = AlertStore(SecretBox(config.encryption_key, data_dir=config.data_dir)).topic(str(ds["org_id"]))
    if not topic:
        _set(ds_id, inbox, watch_by="no topic", watch_renewed_at=_now(),
             watch_error="No Pub/Sub topic is set for this organisation, so history is read every minute.")
        return
    gmail, who = _open(ds, inbox)
    try:
        made = _run(who, gmail.watch(topic, labels=("INBOX",)))
    except Exception as exc:  # noqa: BLE001 - said on the health card; history is read every minute anyway
        _set(ds_id, inbox, watch_error=f"Gmail would not make the watch: {exc}"[:500], watch_renewed_at=_now(),
             watch_by="sync")
        return
    _set(ds_id, inbox, watch_by="sync", watch_error="", watch_renewed_at=_now(),
         watch_expires_at=datetime.fromtimestamp(made["expires_at"] or time.time(), timezone.utc))


# ---------------------------------------------------------------------------------------------
# every night: Gmail's whole list against Synapse's
# ---------------------------------------------------------------------------------------------

def _waiting_for(ds_id: str, keys: list[str]) -> int:
    if not keys:
        return 0
    return int(db.value("SELECT count(*) FROM synapse.job WHERE dataset_id = %s AND done_at IS NULL AND "
                        "kind = ANY(%s) AND payload->>'key' = ANY(%s)", (ds_id, list(KINDS), keys)) or 0)


def reconcile(ds: dict, inbox: str, *, wait: float | None = None, notify: bool = True, by: str = "nightly",
              on_progress=None) -> dict:
    """Gmail's id list against Synapse's emails of this inbox: the missing queued, the extra deleted
    (each checked with Gmail first), and after waiting for those, compared again. The owner hears on
    Telegram only if they still differ then."""
    ds_id, inbox = str(ds["id"]), clean_inbox(inbox)
    wait = RECONCILE_WAIT if wait is None else float(wait)
    began = time.time()
    gmail, who = _open(ds, inbox)
    ids, drafts = gmail_ids(gmail, who)
    live, dead = synapse_ids(ds_id, inbox)
    missing, extra = sorted(ids - live - dead), sorted(live - ids)
    out = {"at": _now().isoformat(), "by": by, "gmail": len(ids), "drafts_left_out": len(drafts),
           "synapse": len(live), "deleted_in_synapse": len(dead & ids), "missing": len(missing), "extra": len(extra),
           "queued": 0, "deleting": 0}
    if missing:
        out["queued"] = queue(ds_id, inbox, "mail_add", missing,
                              lane="live" if len(missing) <= LIVE_AT_MOST else "backfill")
    if extra:
        out["deleting"] = queue(ds_id, inbox, "mail_delete", extra)
    fixed = [key_of(inbox, m) for m in missing + extra]
    while fixed and _waiting_for(ds_id, fixed) and time.time() - began < wait:
        if on_progress:
            on_progress(_waiting_for(ds_id, fixed))
        time.sleep(5)
    out["waited_s"] = round(time.time() - began, 1)
    if fixed:
        ids2, _ = gmail_ids(gmail, who)
        live2, dead2 = synapse_ids(ds_id, inbox)
        # What is still on the queue, and not given up on, is on its way rather than a difference:
        # mail that arrived while waiting, or a queue busy with other work.
        coming = {(r["kind"], r["id"]) for r in db.rows(
            "SELECT kind, payload->>'id' AS id FROM synapse.job WHERE dataset_id = %s AND kind IN ('mail_add', "
            "'mail_delete') AND done_at IS NULL AND tries < 3 AND payload->>'inbox' = %s", (ds_id, inbox))}
        missing2, extra2 = ids2 - live2 - dead2, live2 - ids2
        still_missing = sorted(m for m in missing2 if ("mail_add", m) not in coming)
        still_extra = sorted(m for m in extra2 if ("mail_delete", m) not in coming)
        out.update({"gmail_after": len(ids2), "synapse_after": len(live2),
                    "on_the_way": len(missing2) - len(still_missing) + len(extra2) - len(still_extra)})
    else:
        still_missing, still_extra = [], []
    out.update({"missing_after": len(still_missing), "extra_after": len(still_extra),
                "clean": not still_missing and not still_extra,
                "examples": {"missing": still_missing[:10], "extra": still_extra[:10]}})
    out["told_owner"] = _tell(ds, inbox, out) if notify and not out["clean"] else ""
    _set(ds_id, inbox, last_reconcile_at=_now(), reconcile=out)
    log.info("Synapse mail %s reconciled: %s", inbox, {k: v for k, v in out.items() if k != "examples"})
    return out


def _tell(ds: dict, inbox: str, out: dict) -> str:
    """The Telegram note when a reconciliation could not make the two agree. Only to the phone's
    own person (`telegram.phone_owner`), and only about their own Master."""
    from ... import telegram
    from ...config import config
    from ...tenancy import Tenancy

    try:
        owner = telegram.phone_owner(Tenancy())
        if owner is None or str(owner.user_id) != str(ds["user_id"]) or str(owner.org_id) != str(ds["org_id"]):
            return "not sent: the phone is somebody else's"
        bot = telegram.Telegram(getattr(config, "telegram_file", None), api_base=getattr(config, "telegram_api_base", None))
        if not bot.configured():
            return "not sent: Telegram is not set up"
        which = "tonight's check" if out.get("by") == "nightly" else "a check against it"
        text = (f"Synapse's copy of {inbox} still differs from Gmail after {which}: "
                f"{out['missing_after']} missing and {out['extra_after']} extra, of {out.get('gmail_after', out['gmail'])} "
                "in Gmail. The Synapse page's Gmail card, or manage.py synapse_mail status, has the details.")
        asyncio.run(bot.send(text))
        return "sent"
    except Exception as exc:  # noqa: BLE001 - the result is kept whether or not the note went
        log.exception("Synapse mail %s: the reconciliation note did not go", inbox)
        return f"not sent: {type(exc).__name__}"


def reconcile_due(row: dict, now: float | None = None) -> bool:
    """Once a night, after RECONCILE_HOUR, and only once the backfill is listed and stored: before
    that, everything not stored yet would look missing."""
    now = time.time() if now is None else now
    local = time.localtime(now)
    if local.tm_hour < RECONCILE_HOUR or row.get("backfill_state") != "listed":
        return False
    last = row.get("last_reconcile_at")
    if last is not None and time.localtime(last.timestamp())[:3] == local[:3]:
        return False
    return not db.value("SELECT 1 FROM synapse.job WHERE dataset_id = %s AND kind = 'mail_add' AND lane = 'backfill' "
                        "AND done_at IS NULL AND payload->>'inbox' = %s LIMIT 1", (str(row["dataset_id"]), row["inbox"]))


_reconciling: set[str] = set()


def _reconcile_soon(ds: dict, row: dict) -> None:
    """The nightly reconciliation on a thread of its own: it waits for what it queued, and the
    history must go on being read meanwhile."""
    name = f"{ds['id']}:{row['inbox']}"
    if name in _reconciling:
        return
    _reconciling.add(name)
    # Written down as started, so a restart in the middle does not start another tonight.
    _set(str(ds["id"]), row["inbox"], last_reconcile_at=_now())

    def go():
        from django.db import connection

        try:
            reconcile(ds, row["inbox"])
        except Exception as exc:  # noqa: BLE001
            log.exception("Synapse mail %s: the nightly reconciliation failed", row["inbox"])
            with contextlib.suppress(Exception):
                _set(str(ds["id"]), row["inbox"], reconcile={"at": _now().isoformat(), "by": "nightly",
                                                            "error": f"{type(exc).__name__}: {exc}"[:500]})
        finally:
            _reconciling.discard(name)
            connection.close()

    threading.Thread(target=go, name="synapse-gmail-reconcile", daemon=True).start()


# ---------------------------------------------------------------------------------------------
# the beat
# ---------------------------------------------------------------------------------------------

_wake = threading.Event()
_started = False
_start_lock = threading.Lock()


def wake() -> None:
    _wake.set()


def pushed(org_id: str, address: str) -> int:
    """Gmail's push reached Rouh for this address: noted, and its history read now."""
    if not db.value("SELECT to_regclass('synapse.mail_sync') IS NOT NULL"):
        return 0
    n = db.run("UPDATE synapse.mail_sync s SET last_push_at = now() FROM synapse.dataset d WHERE d.id = s.dataset_id "
               "AND d.org_id = %s AND s.inbox = %s AND s.enabled", (str(org_id), clean_inbox(address)))
    if n:
        wake()
    return n


def beat_one(ds: dict, row: dict) -> dict:
    """One inbox's turn: its history, the next pages of its backfill, its watch, and the night's check.
    Only one process reads an inbox at a time (a lock on it), so a command run beside Rouh waits."""
    from .. import datasets

    ds = datasets.by_id(row["dataset_id"]) if not ds else ds
    name = f"synapse.mail.beat:{row['dataset_id']}:{row['inbox']}"
    if not db.value("SELECT pg_try_advisory_lock(hashtext(%s))", (name,)):
        return {"busy": True}
    out: dict = {}
    try:
        try:
            out["history"] = read_history(ds, row)
        except Exception as exc:  # noqa: BLE001 - said on the card, and tried again next beat
            log.warning("Synapse mail %s: history not read: %s", row["inbox"], exc)
            db.run("UPDATE synapse.mail_sync SET last_history_at = now(), history_failures = history_failures + 1, "
                   "history_error = %s, updated_at = now() WHERE dataset_id = %s AND inbox = %s",
                   (f"{type(exc).__name__}: {exc}"[:500], str(ds["id"]), row["inbox"]))
            out["error"] = str(exc)
            return out
        row = row_of(ds["id"], row["inbox"]) or row
        if row.get("backfill_state") == "listing":
            try:
                out["backfill"] = list_backfill(ds, row)
            except Exception as exc:  # noqa: BLE001
                log.warning("Synapse mail %s: backfill page not listed: %s", row["inbox"], exc)
                _set(str(ds["id"]), row["inbox"], backfill_error=f"{type(exc).__name__}: {exc}"[:500])
        with contextlib.suppress(Exception):
            _watch(ds, row)
        if reconcile_due(row):
            _reconcile_soon(ds, row)
        return out
    finally:
        db.run("SELECT pg_advisory_unlock(hashtext(%s))", (name,))


def beat() -> None:
    from .. import datasets

    for row in rows():
        ds = datasets.by_id(row["dataset_id"])
        if ds:
            beat_one(ds, row)


def _loop() -> None:
    from django.db import connection

    time.sleep(5)
    while True:
        try:
            if db.ready():
                beat()
        except Exception:  # noqa: BLE001 - the loop never dies
            log.exception("the Synapse Gmail sync stumbled")
        finally:
            connection.close()
        _wake.wait(POLL_SECONDS)
        _wake.clear()


def start() -> None:
    """The beat, once per process, on a thread of its own (`worker.start` starts it)."""
    global _started
    with _start_lock:
        if _started or os.environ.get("SYNAPSE_GMAIL_SYNC", "1") == "0":
            return
        _started = True
    threading.Thread(target=_loop, name="synapse-gmail", daemon=True).start()


# ---------------------------------------------------------------------------------------------
# health
# ---------------------------------------------------------------------------------------------

def health(ds_id: str | None = None) -> list[dict]:
    """Where each inbox's sync stands, for the lab's card and `manage.py synapse_mail status`."""
    out = []
    for r in rows(enabled_only=False):
        if ds_id and str(r["dataset_id"]) != str(ds_id):
            continue
        d, inbox = str(r["dataset_id"]), r["inbox"]
        pre = prefix_of(inbox)
        items = db.row(
            "SELECT count(*) FILTER (WHERE kind = 'mail' AND deleted_at IS NULL) AS mail, "
            "count(*) FILTER (WHERE kind = 'mail' AND deleted_at IS NOT NULL) AS deleted, "
            "count(*) FILTER (WHERE kind = 'mail' AND deleted_at IS NULL AND status IN ('ready', 'failed')) AS read_by_model, "
            "count(*) FILTER (WHERE kind = 'mail' AND deleted_at IS NULL AND meta->'gmail'->>'folder' IN ('spam', 'trash')) "
            "AS junk_folder, max(stored_at) FILTER (WHERE kind = 'mail') AS last_stored "
            "FROM synapse.item WHERE dataset_id = %s AND source = %s AND source_key LIKE %s", (d, SOURCE, pre + "%")) or {}
        items["files"] = db.value(
            "SELECT count(*) FROM synapse.item WHERE dataset_id = %s AND source = %s AND deleted_at IS NULL AND "
            "kind IN ('doc', 'file') AND EXISTS (SELECT 1 FROM jsonb_array_elements_text(coalesce(meta->'attached_to', "
            "'[]'::jsonb)) a WHERE a LIKE %s)", (d, SOURCE, pre + "%")) or 0
        folders = {x["folder"] or "none": x["n"] for x in db.rows(
            "SELECT meta->'gmail'->>'folder' AS folder, count(*) AS n FROM synapse.item WHERE dataset_id = %s AND "
            "source = %s AND kind = 'mail' AND deleted_at IS NULL AND source_key LIKE %s GROUP BY 1 ORDER BY 2 DESC",
            (d, SOURCE, pre + "%"))}
        jobs = {f"{x['kind']}:{x['lane']}": x["n"] for x in db.rows(
            "SELECT kind, lane, count(*) AS n FROM synapse.job WHERE dataset_id = %s AND done_at IS NULL AND "
            "kind = ANY(%s) AND payload->>'inbox' = %s GROUP BY 1, 2", (d, list(KINDS), inbox))}
        model_parts = db.value(
            "SELECT count(*) FROM synapse.job j JOIN synapse.item i ON i.id = j.item_id WHERE j.dataset_id = %s AND "
            "j.done_at IS NULL AND j.kind IN ('ingest', 'reingest') AND i.source = %s", (d, SOURCE)) or 0
        failed = db.row(
            "SELECT count(*) AS n, max(done_at) AS last_at, (array_agg(error ORDER BY done_at DESC))[1] AS last FROM "
            "synapse.job WHERE dataset_id = %s AND kind = ANY(%s) AND payload->>'inbox' = %s AND done_at IS NOT NULL "
            "AND error <> '' AND error NOT LIKE 'its inbox%%' AND done_at > now() - interval '7 days'",
            (d, list(KINDS), inbox)) or {}
        retrying = db.value("SELECT count(*) FROM synapse.job WHERE dataset_id = %s AND kind = ANY(%s) AND "
                            "payload->>'inbox' = %s AND done_at IS NULL AND error <> ''", (d, list(KINDS), inbox)) or 0
        cost = db.value(
            "SELECT coalesce(sum(t.cost_usd), 0) FROM synapse.trace t JOIN synapse.item i ON i.id = t.item_id WHERE "
            "t.dataset_id = %s AND i.source = %s AND (i.source_key LIKE %s OR EXISTS (SELECT 1 FROM "
            "jsonb_array_elements_text(coalesce(i.meta->'attached_to', '[]'::jsonb)) a WHERE a LIKE %s))",
            (d, SOURCE, pre + "%", pre + "%")) or 0
        ok_at = r.get("last_history_ok_at")
        stale = bool(r["enabled"]) and (ok_at is None or (_now() - ok_at).total_seconds() > STALE_MINUTES * 60)
        backlog = sum(jobs.values())
        out.append({
            "dataset": d, "inbox": inbox, "enabled": bool(r["enabled"]), "added_at": r["added_at"],
            "history_id": r["history_id"], "last_push_at": r["last_push_at"], "last_history_at": r["last_history_at"],
            "last_history_ok_at": ok_at, "history_error": r["history_error"], "history_failures": r["history_failures"],
            "last_history_counts": r["last_history_counts"],
            "stale": stale, "flag": (f"No good read of Gmail's history in {STALE_MINUTES} minutes" if stale else ""),
            "backfill": {"state": r["backfill_state"] or "not started", "listed": r["backfill_listed"],
                         "started_at": r["backfill_started_at"], "listed_at": r["backfill_listed_at"],
                         "error": r["backfill_error"],
                         "done": r["backfill_state"] == "listed" and not jobs.get("mail_add:backfill")},
            "items": items, "folders": folders, "jobs": jobs, "backlog": backlog, "model_parts_waiting": model_parts,
            "failed_7d": failed.get("n") or 0, "last_failure": failed.get("last") or "",
            "last_failure_at": failed.get("last_at"), "retrying": retrying,
            "watch": {"by": r["watch_by"], "expires_at": r["watch_expires_at"], "renewed_at": r["watch_renewed_at"],
                      "error": r["watch_error"]},
            "last_reconcile_at": r["last_reconcile_at"], "reconcile": r["reconcile"] or {},
            "cost_usd": round(float(cost), 6)})
    return out


__all__ = ["KINDS", "SOURCE", "add", "beat", "beat_one", "folder_of", "gmail_ids", "health", "key_of", "list_backfill",
           "pushed", "queue", "read_history", "reconcile", "relist", "remove", "rows", "run_job", "start",
           "synapse_ids", "wake"]
