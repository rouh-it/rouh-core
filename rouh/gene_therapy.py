"""What the person says about Rouh, and what is going to be done about it.

Two things, not one, and the whole design is in that sentence.

**A feedback is what somebody said.** A sentence, a screenshot, a file, the
moment they had it. It is never edited into something else and never turns into
a task by being rewritten: what a person said stays what they said.

**A feature request is what we decided to do about it.** It has a type -
feature, bug, improvement, question - a title, and a description of how the
solution should work, with its own files as extra guidance. One is made *from*
a feedback and remembers which one (`from_feedback`), and one can also be made
on its own, because not everything worth building came out of somebody
complaining.

They are two tables because they have two lifetimes and two status sets, and
folding them into one row with a flag on it is the mistake that makes "which of
these did the person actually say" unanswerable six months later.

    feedback         new -> triaged -> planned -> done, or declined
    feature_request  proposed -> building -> shipped or failed, or declined

**Neither of those two steps waits for a person any more.** A feedback is read
the moment it lands, a feature request is written from it, and a run is started
to build it, all without anybody pressing anything: `rouh/triage.py` is that,
and it is the reason `automatic`, `run_note` and `run_tries` are columns here.
Everything below is unchanged by it - a person may still promote a feedback by
hand and still start a run by hand, and a request they wrote themselves is
never started for them.

**The second step has a switch.** Each organisation's board can turn off the
run being started by itself (`autobuild`, in `feedback_board`), and then only
the run is held back: the feedback is still read and the request still
written, and it waits on the board, `proposed` with no run, until somebody
presses Start or turns the switch back on. Petar, 23 September 2026 - "keep
converting feedback to features, but if the toggle is off, don't build them -
immediately on submit and on a cronjob."

**Nor does the end of it.** The run that builds a request finishes, and
`triage.settle` writes that ending here - `shipped` or `failed` - and marks the
feedback it came from done. Until 23 September 2026 nothing did, so a card
whose work had been built and landed hours before still read `building` with
"run done" printed underneath it: the board could see the run had finished and
the status never moved.

A feature request carries `run_id`: the run started to build it. That is a
plain column and not a link in `objects.py`, because a run is one of the five
objects and a feature request is not one of them: the reference points out of
this module into the register, never the other way round, and a run deleted
from the register leaves the id behind harmlessly (`runs.row_for` answers None
and the card says the run is gone).

**Files.** Both kinds take attachments, and neither stores a byte of them.
`rouh/attachments.py` owns everything about a file on disk - where it goes,
what it may be, what it is served as - and this keeps the record it hands back,
keyed by the attachment's own id and the folder it was uploaded into. A drawer
that is still being typed into uploads straight away, into a folder of its own
(`fb-<something>`), so the wait for a screenshot happens while the person is
still writing; submitting is what binds those ids to the row.

**Whose it is.** Every row carries `org_id` and `user_id`, and every read is
scoped by the organisation, because the board is the organisation's - the point
of it is that the people in one place see one list. Who wrote each one is on
the row and on the screen. There is no query here that does not name an
organisation, and no route that takes one from the caller.
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, Iterable

log = logging.getLogger("rouh.gene_therapy")

#: What a feedback can be. `new` is what everything arrives as; `planned` is
#: what it becomes the moment a feature request is made from it, so the left
#: column never has to be read against the right one to see what has been
#: picked up.
FEEDBACK_STATUSES: tuple[str, ...] = ("new", "triaged", "planned", "done", "declined")

#: And a feature request. `building` is set by starting a run for it and taken
#: off again by that run ending (`triage.settle`), so the column says what is
#: happening without anybody remembering to move a card.
#:
#: `failed` is the fourth because a run that ends badly is a fact worth saying.
#: Without it the only honest place to leave such a card was `building`, and a
#: card that says it is being built by a run that died months ago is a spinner
#: nobody can stop.
REQUEST_STATUSES: tuple[str, ...] = ("proposed", "building", "shipped", "failed",
                                     "declined")

#: The "feature/bug/etc" of the person's own words. A type rather than four
#: tables: they differ in what they are called and in nothing else.
REQUEST_KINDS: tuple[str, ...] = ("feature", "bug", "improvement", "question")

#: All three are CHECK constraints in the database too, and `rouh/models/rest.py`
#: takes them from here, so the rule in the table and the rule in this file are
#: one list written once.

#: The most text one of these may carry. Long enough for anything a person
#: types into a drawer, short enough that a paste of a whole log file is cut
#: rather than stored whole.
MAX_BODY = 20_000
MAX_TITLE = 200

#: The two owners a file can have here, as the column says them.
FEEDBACK, REQUEST = "feedback", "request"


@dataclass(frozen=True)
class Attachment:
    """One file on one feedback or one request."""

    att_id: str
    session: str
    name: str
    media_type: str
    kind: str
    size: int
    path: str
    created_at: float

    def as_json(self, *, with_path: bool = False) -> dict:
        """What the page is told. The path on disk is deliberately left out.

        The browser has no use for the server's layout and every reason not to
        know it; what it needs is the address to fetch the file from, which is
        the same route the transcript's own thumbnails use. `with_path` is for
        the brief a run is given, which is the one place a path belongs.
        """
        out = {
            "id": self.att_id,
            "session": self.session,
            "name": self.name,
            "media_type": self.media_type,
            "kind": self.kind,
            "size": self.size,
            "url": f"/attachments/{self.session}/{self.att_id}",
        }
        if with_path:
            out["path"] = self.path
        return out


@dataclass(frozen=True)
class Feedback:
    id: str
    org_id: str
    user_id: str
    author: str
    body: str
    page: str
    status: str
    created_at: float
    updated_at: float | None

    def as_json(self, files: Iterable[Attachment] = ()) -> dict:
        return {
            "id": self.id,
            "author": self.author,
            "user_id": self.user_id,
            "body": self.body,
            "page": self.page,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "files": [f.as_json() for f in files],
        }


@dataclass(frozen=True)
class FeatureRequest:
    id: str
    org_id: str
    user_id: str
    author: str
    from_feedback: str
    kind: str
    title: str
    body: str
    status: str
    run_id: str
    run_started_at: float | None
    created_at: float
    updated_at: float | None
    automatic: bool = False
    run_note: str = ""
    run_tries: int = 0

    def as_json(self, files: Iterable[Attachment] = ()) -> dict:
        return {
            "id": self.id,
            "author": self.author,
            "user_id": self.user_id,
            "from_feedback": self.from_feedback,
            "kind": self.kind,
            "title": self.title,
            "body": self.body,
            "status": self.status,
            "run_id": self.run_id,
            "run_started_at": self.run_started_at,
            "automatic": bool(self.automatic),
            "run_note": self.run_note,
            "run_tries": self.run_tries,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "files": [f.as_json() for f in files],
        }


def _text(raw: Any, limit: int) -> str:
    return str(raw or "").strip()[:limit]


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _feedback(row) -> Feedback:
    """A row of `rouh.models.Feedback`, as the frozen value callers are handed."""
    return Feedback(
        id=row.id, org_id=row.org_id, user_id=row.user_id,
        author=row.author, body=row.body, page=row.page,
        status=row.status, created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _request(row) -> FeatureRequest:
    """A row of `rouh.models.FeatureRequest`, the same way."""
    return FeatureRequest(
        id=row.id, org_id=row.org_id, user_id=row.user_id,
        author=row.author, from_feedback=row.from_feedback,
        kind=row.kind, title=row.title, body=row.body,
        status=row.status, run_id=row.run_id,
        run_started_at=row.run_started_at,
        created_at=row.created_at, updated_at=row.updated_at,
        automatic=bool(row.automatic), run_note=row.run_note,
        run_tries=int(row.run_tries or 0),
    )


def _file(row) -> Attachment:
    """A row of `rouh.models.FeedbackFile`, the same way."""
    return Attachment(
        att_id=row.att_id, session=row.session, name=row.name,
        media_type=row.media_type, kind=row.kind, size=row.size,
        path=_where_now(row.att_id, row.path), created_at=row.created_at,
    )


def _where_now(att_id: str, was: str) -> str:
    """Where the file is now, by the list of files (`rouh/filestore.py`), which moves files
    when their chat becomes a task's; the path noted here when it was given, failing that."""
    from . import filestore

    got = filestore.row(att_id)
    return got.path if got is not None else was


class Refused(ValueError):
    """A sentence the person can read, for something that cannot be written."""


class GeneTherapyStore:
    """The two tables and the files on them, in Rouh's database.

    The same shape as every other store here - one lock around every write,
    and its own tables, which nothing else reads or writes. Until 23 September
    2026 it opened the SQLite file itself, made its tables, grew them with
    ALTER TABLE and rebuilt one to widen a CHECK; the schema is Django's
    migrations' now, and the path the constructor is still handed is accepted
    and not used.
    """

    def __init__(self, db_path: str | None = None) -> None:
        self._lock = threading.Lock()

    def close(self) -> None:
        """Nothing to let go of: the connection is Django's, one per thread."""

    # --- what somebody said -------------------------------------------------

    def add_feedback(self, *, org_id: str, user_id: str, author: str = "",
                     body: str = "", page: str = "", created_at: float | None = None) -> Feedback:
        """What somebody said, as they said it. `created_at` is when they wrote it, for one
        written with no connection and sent when the device came back (`offline._feedback`)."""
        from .models import Feedback as Row

        body = _text(body, MAX_BODY)
        if not body:
            raise Refused("There was nothing written, so nothing was sent.")
        row = {
            "id": _new_id("fb"), "org_id": str(org_id), "user_id": str(user_id),
            "author": _text(author, 120), "body": body, "page": _text(page, 200),
            "status": "new",
            "created_at": float(created_at) if created_at and created_at <= time.time() else time.time(),
            "updated_at": None,
        }
        with self._lock:
            Row.objects.create(**row)
        log.info("feedback %s written by %s", row["id"], row["author"] or row["user_id"])
        return Feedback(**row)                                   # type: ignore[arg-type]

    def get_feedback(self, org_id: str, feedback_id: str) -> Feedback | None:
        """One feedback, **in one organisation**.

        Both ids in the WHERE clause although the id alone is unique: a caller
        holding the wrong organisation is exactly the bug worth turning into
        "not found" rather than into one customer reading another's.
        """
        from .models import Feedback as Row

        with self._lock:
            row = Row.objects.filter(id=str(feedback_id), org_id=str(org_id)).first()
        return None if row is None else _feedback(row)

    def list_feedback(self, org_id: str, *, status: str = "",
                      limit: int = 500) -> list[Feedback]:
        from .models import Feedback as Row

        rows = Row.objects.filter(org_id=str(org_id))
        if status:
            rows = rows.filter(status=status)
        with self._lock:
            found = list(rows.order_by("-created_at")[:int(limit)])
        return [_feedback(r) for r in found]

    def set_feedback_status(self, org_id: str, feedback_id: str,
                            status: str) -> Feedback | None:
        from .models import Feedback as Row

        if status not in FEEDBACK_STATUSES:
            raise Refused(f"{status!r} is not one of: " + ", ".join(FEEDBACK_STATUSES))
        with self._lock:
            Row.objects.filter(id=str(feedback_id), org_id=str(org_id)).update(
                status=status, updated_at=time.time())
        return self.get_feedback(org_id, feedback_id)

    def feedback_done(self, org_id: str, feedback_id: str) -> bool:
        """The thing they asked for exists now, so their feedback is done.

        Written by the run ending rather than by anybody pressing anything
        (`triage.settle`), which is the other half of `set_feedback_status`
        being called with "planned" when the request was made from it.

        Only from the three that are not somebody's decision. A feedback
        declined in the morning, or already marked done by hand, stays exactly
        where it was put: that was a decision, and a run finishing is not the
        thing that gets to undo it. One guarded statement rather than a read
        and then a write, so two of these cannot race each other.
        """
        from .models import Feedback as Row

        with self._lock:
            moved = Row.objects.filter(
                id=str(feedback_id), org_id=str(org_id),
                status__in=("new", "triaged", "planned"),
            ).update(status="done", updated_at=time.time())
        return bool(moved)

    def delete_feedback(self, org_id: str, feedback_id: str) -> bool:
        """Take it off the board, with its files' records.

        The bytes on disk are left alone: `attachments.py` owns those, a file
        may be referred to from a feature request made out of this feedback,
        and deleting somebody's screenshot because a card was tidied away is
        not a thing this module gets to decide.
        """
        from django.db import transaction

        from .models import Feedback as Row
        from .models import FeedbackFile

        with self._lock, transaction.atomic():
            gone, _ = Row.objects.filter(id=str(feedback_id), org_id=str(org_id)).delete()
            if gone:
                FeedbackFile.objects.filter(owner_kind=FEEDBACK,
                                            owner_id=str(feedback_id)).delete()
        return bool(gone)

    # --- what is going to be done about it ----------------------------------

    def add_request(self, *, org_id: str, user_id: str, author: str = "",
                    title: str = "", body: str = "", kind: str = "feature",
                    from_feedback: str = "",
                    automatic: bool = False) -> FeatureRequest:
        from .models import FeatureRequest as Row

        title = _text(title, MAX_TITLE)
        if not title:
            raise Refused("A feature request needs a title.")
        if kind not in REQUEST_KINDS:
            raise Refused(f"{kind!r} is not one of: " + ", ".join(REQUEST_KINDS))
        row = {
            "id": _new_id("fr"), "org_id": str(org_id), "user_id": str(user_id),
            "author": _text(author, 120), "from_feedback": str(from_feedback or ""),
            "kind": kind, "title": title, "body": _text(body, MAX_BODY),
            "status": "proposed", "run_id": "", "run_started_at": None,
            "automatic": bool(automatic), "run_note": "", "run_tries": 0,
            "created_at": time.time(), "updated_at": None,
        }
        with self._lock:
            Row.objects.create(**row)
        log.info("feature request %s (%s) written from %s%s", row["id"], kind,
                 from_feedback or "nothing", ", by itself" if automatic else "")
        return FeatureRequest(**row)                             # type: ignore[arg-type]

    def get_request(self, org_id: str, request_id: str) -> FeatureRequest | None:
        from .models import FeatureRequest as Row

        with self._lock:
            row = Row.objects.filter(id=str(request_id), org_id=str(org_id)).first()
        return None if row is None else _request(row)

    def list_requests(self, org_id: str, *, status: str = "", kind: str = "",
                      from_feedback: str = "", limit: int = 500) -> list[FeatureRequest]:
        from .models import FeatureRequest as Row

        rows = Row.objects.filter(org_id=str(org_id))
        if status:
            rows = rows.filter(status=status)
        if kind:
            rows = rows.filter(kind=kind)
        if from_feedback:
            rows = rows.filter(from_feedback=str(from_feedback))
        with self._lock:
            found = list(rows.order_by("-created_at")[:int(limit)])
        return [_request(r) for r in found]

    def update_request(self, org_id: str, request_id: str, *, title: str | None = None,
                       body: str | None = None, kind: str | None = None,
                       status: str | None = None) -> FeatureRequest | None:
        from .models import FeatureRequest as Row

        sets: dict[str, Any] = {}
        if title is not None:
            said = _text(title, MAX_TITLE)
            if not said:
                raise Refused("A feature request needs a title.")
            sets["title"] = said
        if body is not None:
            sets["body"] = _text(body, MAX_BODY)
        if kind is not None:
            if kind not in REQUEST_KINDS:
                raise Refused(f"{kind!r} is not one of: " + ", ".join(REQUEST_KINDS))
            sets["kind"] = kind
        if status is not None:
            if status not in REQUEST_STATUSES:
                raise Refused(f"{status!r} is not one of: " + ", ".join(REQUEST_STATUSES))
            sets["status"] = status
        if not sets:
            return self.get_request(org_id, request_id)
        sets["updated_at"] = time.time()
        with self._lock:
            Row.objects.filter(id=str(request_id), org_id=str(org_id)).update(**sets)
        return self.get_request(org_id, request_id)

    def set_run(self, org_id: str, request_id: str, run_id: str) -> FeatureRequest | None:
        """The run that is building it, and the status that goes with it.

        One statement writes both, so a card can never say "proposed" while a
        run started from it is going. The note about why a run could not be
        started goes with it: it was about the try before this one, and this
        one worked.
        """
        from .models import FeatureRequest as Row

        with self._lock:
            Row.objects.filter(id=str(request_id), org_id=str(org_id)).update(
                run_id=str(run_id), run_started_at=time.time(), status="building",
                run_note="", updated_at=time.time())
        return self.get_request(org_id, request_id)

    def run_restarted(self, org_id: str, old_run: str, new_run: str) -> int:
        """A run that died was started again, and what it was building goes with it.

        The request was marked failed when its run died (`triage.settle`), and
        a person pressing Restart on that run is the person deciding it is not
        failed after all, so it is building again, on the new run. A request
        somebody has shipped or declined is left exactly where they put it.
        Returns how many moved.
        """
        from .models import FeatureRequest as Row

        now = time.time()
        with self._lock:
            return (Row.objects.filter(org_id=str(org_id), run_id=str(old_run))
                    .exclude(status__in=("shipped", "declined"))
                    .update(run_id=str(new_run), run_started_at=now, status="building",
                            run_note="", updated_at=now))

    def run_failed(self, org_id: str, request_id: str, why: str) -> FeatureRequest | None:
        """Nothing would start a run for it, and this is the sentence why.

        The count goes up with it, because that is what stops a request nobody
        can run being asked about for ever (`triage.MAX_TRIES`). The status is
        left alone: it is still proposed, and it is still going to be tried
        again on the next sweep. The count is added to in the statement, not
        read and written back, so two sweeps cannot lose one.
        """
        from django.db.models import F

        from .models import FeatureRequest as Row

        with self._lock:
            Row.objects.filter(id=str(request_id), org_id=str(org_id)).update(
                run_note=_text(why, 400), run_tries=F("run_tries") + 1,
                updated_at=time.time())
        return self.get_request(org_id, request_id)

    def building(self, org_id: str, limit: int = 200) -> list[FeatureRequest]:
        """Requests this table still thinks have a run going, oldest first.

        What `triage.settle` walks. Only the ones with a run, because
        `building` without one is not a thing `set_run` can write and there
        would be nothing to ask the register about anyway.
        """
        from .models import FeatureRequest as Row

        with self._lock:
            rows = list(Row.objects.filter(org_id=str(org_id), status="building")
                        .exclude(run_id="").order_by("created_at")[:int(limit)])
        return [_request(r) for r in rows]

    def run_ended(self, org_id: str, request_id: str, status: str) -> bool:
        """The run building it has ended, and this is what it ended as.

        `building` is the only status this moves, and it is in the WHERE
        clause rather than checked first for the same reason `feedback_done`
        guards itself: the sweep and a board being read can both arrive here
        at once, and the second of them must do nothing rather than write
        again. A person who declined the card, or marked it shipped
        themselves, is left alone.
        """
        from .models import FeatureRequest as Row

        if status not in REQUEST_STATUSES:
            raise Refused(f"{status!r} is not one of: " + ", ".join(REQUEST_STATUSES))
        with self._lock:
            moved = Row.objects.filter(id=str(request_id), org_id=str(org_id),
                                       status="building").update(status=status,
                                                                 updated_at=time.time())
        return bool(moved)

    def delete_request(self, org_id: str, request_id: str) -> bool:
        from django.db import transaction

        from .models import FeatureRequest as Row
        from .models import FeedbackFile

        with self._lock, transaction.atomic():
            gone, _ = Row.objects.filter(id=str(request_id), org_id=str(org_id)).delete()
            if gone:
                FeedbackFile.objects.filter(owner_kind=REQUEST,
                                            owner_id=str(request_id)).delete()
        return bool(gone)

    # --- what nobody has picked up yet --------------------------------------
    #
    # The three the sweep in `rouh/triage.py` walks. Oldest first in both
    # lists, because the one that has been waiting longest is the one to do
    # first, and capped, because a sweep is a beat and not a batch job.

    def organisations(self) -> list[str]:
        """Every organisation that has a board, oldest feedback first.

        The one query here that does not name an organisation, and it reads no
        row's content: it answers which boards exist, and everything the sweep
        does afterwards names one of them. Without it a sweep would have to be
        told who its customers are, which is a worse thing to know.
        """
        from django.db.models import Min

        from .models import Feedback as Row

        with self._lock:
            rows = list(Row.objects.values("org_id").annotate(first=Min("created_at"))
                        .order_by("first").values_list("org_id", flat=True))
        return rows

    def unconverted(self, org_id: str, limit: int = 20) -> list[Feedback]:
        """Feedback with nothing made from it yet, and nobody's decision undone.

        `done` and `declined` are somebody's decision about that feedback and
        are never picked up: a feedback declined in the morning must not come
        back as a run in the afternoon.
        """
        from .models import FeatureRequest
        from .models import Feedback as Row

        made_from = (FeatureRequest.objects.filter(org_id=str(org_id))
                     .exclude(from_feedback="").values("from_feedback"))
        with self._lock:
            rows = list(Row.objects.filter(org_id=str(org_id), status__in=("new", "triaged"))
                        .exclude(id__in=made_from).order_by("created_at")[:int(limit)])
        return [_feedback(r) for r in rows]

    def awaiting_run(self, org_id: str, limit: int = 20,
                     max_tries: int = 5) -> list[FeatureRequest]:
        """Requests that came out of a feedback and have no run going.

        Only the ones that came out of a feedback. A feature request somebody
        typed themselves has a Start box under it and a person in front of it,
        and starting a run under somebody who is still writing is interference
        rather than automation.
        """
        from .models import FeatureRequest as Row

        with self._lock:
            rows = list(Row.objects.filter(org_id=str(org_id), run_id="", status="proposed",
                                           run_tries__lt=int(max_tries))
                        .exclude(from_feedback="").order_by("created_at")[:int(limit)])
        return [_request(r) for r in rows]

    # --- the files ----------------------------------------------------------

    def add_files(self, owner_kind: str, owner_id: str,
                  records: Iterable[dict]) -> list[Attachment]:
        """Note which files belong to this row, from `attachments.py`'s records.

        The records are whatever `Attachments.resolve` handed back, so a file
        that is not really on disk never reaches this table. The same file
        noted twice is written over rather than refused, one row at a time, so
        the last of two records with one id is the one kept.
        """
        from django.db import transaction

        from .models import FeedbackFile

        if owner_kind not in (FEEDBACK, REQUEST):
            raise Refused(f"{owner_kind!r} is not something a file can belong to.")
        records = list(records)
        try:
            from .models.files import File

            File.objects.filter(id__in=[str(r.get("id") or "") for r in records],
                                source="chat").update(source="gene_therapy")
        except Exception:  # noqa: BLE001 - where it came from is a label, never a reason to refuse
            log.debug("the files' source could not be said", exc_info=True)
        kept: list[Attachment] = []
        now = time.time()
        with self._lock, transaction.atomic():
            for record in records:
                att = Attachment(
                    att_id=str(record.get("id") or ""),
                    session=str(record.get("session_id") or ""),
                    name=str(record.get("name") or ""),
                    media_type=str(record.get("media_type") or ""),
                    kind=str(record.get("kind") or "file"),
                    size=int(record.get("size") or 0),
                    path=str(record.get("path") or ""),
                    created_at=now,
                )
                if not att.att_id or not att.session:
                    continue
                FeedbackFile.objects.bulk_create(
                    [FeedbackFile(att_id=att.att_id, session=att.session,
                                  owner_kind=owner_kind, owner_id=str(owner_id),
                                  name=att.name, media_type=att.media_type, kind=att.kind,
                                  size=att.size, path=att.path, created_at=att.created_at)],
                    update_conflicts=True,
                    unique_fields=["owner_kind", "owner_id", "att_id"],
                    update_fields=["session", "name", "media_type", "kind", "size", "path",
                                   "created_at"])
                kept.append(att)
        return kept

    def files_for(self, owner_kind: str, owner_id: str) -> list[Attachment]:
        from .models import FeedbackFile

        with self._lock:
            rows = list(FeedbackFile.objects.filter(owner_kind=owner_kind,
                                                    owner_id=str(owner_id))
                        .order_by("created_at", "name"))
        return [_file(r) for r in rows]

    def files_by_owner(self, owner_kind: str,
                       owner_ids: Iterable[str]) -> dict[str, list[Attachment]]:
        """Every file for a list of rows, in one query.

        The board draws a count on each card, and asking per card is how a
        board with forty cards on it becomes forty queries.
        """
        from .models import FeedbackFile

        ids = [str(i) for i in owner_ids]
        out: dict[str, list[Attachment]] = {i: [] for i in ids}
        if not ids:
            return out
        with self._lock:
            rows = list(FeedbackFile.objects.filter(owner_kind=owner_kind, owner_id__in=ids)
                        .order_by("created_at", "name"))
        for row in rows:
            out.setdefault(row.owner_id, []).append(_file(row))
        return out

    # --- how the board is set -----------------------------------------------
    #
    # One row per organisation in `feedback_board`, and no row means nobody
    # has moved anything: every setting is at its default, which is what every
    # board did before there were settings.

    def board_settings(self, org_id: str) -> dict:
        """What this organisation's board is set to, and who last moved it."""
        from .models import FeedbackBoard

        with self._lock:
            row = FeedbackBoard.objects.filter(org_id=str(org_id)).first()
        if row is None:
            return {"autobuild": True, "changed_by": "", "changed_at": None}
        return {"autobuild": bool(row.autobuild), "changed_by": row.changed_by,
                "changed_at": row.changed_at}

    def autobuild(self, org_id: str) -> bool:
        """Whether a request written out of a feedback is given a run by itself.

        Read by `triage.Converter` right before every run it would start, so a
        switch turned off while a feedback is still being read stops that one
        too. Converting is not behind it: the feedback is still read and the
        request still written, and it waits on the board, `proposed` and
        without a run, for somebody to start one or for this to be turned back
        on.
        """
        return self.board_settings(org_id)["autobuild"]

    def set_autobuild(self, org_id: str, on: bool, *, by: str = "") -> dict:
        """Turn it on or off for this organisation. The settings as they now are.

        One statement whichever way it goes, like `Settings.put`: two people
        pressing the switch at once cannot both make the row.
        """
        from .models import FeedbackBoard

        with self._lock:
            FeedbackBoard.objects.bulk_create(
                [FeedbackBoard(org_id=str(org_id), autobuild=bool(on),
                               changed_by=_text(by, 120), changed_at=time.time())],
                update_conflicts=True, unique_fields=["org_id"],
                update_fields=["autobuild", "changed_by", "changed_at"])
        log.info("automatic build is %s for %s, turned so by %s",
                 "on" if on else "off", org_id, by or "somebody")
        return self.board_settings(org_id)

    # --- what the board says at the top -------------------------------------

    def counts(self, org_id: str) -> dict:
        """How many of each status, both sides, for the filters and the heads."""
        from django.db.models import Count

        from .models import FeatureRequest
        from .models import Feedback as Row

        with self._lock:
            said = list(Row.objects.filter(org_id=str(org_id)).values("status")
                        .annotate(n=Count("id")).order_by())
            asked = list(FeatureRequest.objects.filter(org_id=str(org_id)).values("status")
                         .annotate(n=Count("id")).order_by())
        return {
            "feedback": {r["status"]: r["n"] for r in said},
            "requests": {r["status"]: r["n"] for r in asked},
        }


# ---------------------------------------------------------------------------
# The brief a run is given
# ---------------------------------------------------------------------------


def compose_brief(request: FeatureRequest, *, files: Iterable[Attachment] = (),
                  source: Feedback | None = None,
                  source_files: Iterable[Attachment] = ()) -> str:
    """Everything the person wrote, in the order somebody would read it.

    The title, how the solution should work, the feedback it came out of, and
    the files - by their path on disk, which is how `attachments.py` names a
    file the model cannot open to something that can open it. A run started
    from a card is therefore briefed with exactly what is on the card and
    nothing invented.
    """
    parts: list[str] = [request.title.strip()]
    body = request.body.strip()
    if body:
        parts.append("## How the solution should work\n\n" + body)
    if source is not None and source.body.strip():
        who = source.author or "somebody"
        parts.append(f"## The feedback this came from\n\n{who} wrote:\n\n"
                     + source.body.strip())

    guidance = _files_section("Files attached as guidance", files)
    if guidance:
        parts.append(guidance)
    shown = _files_section("Files attached to that feedback", source_files)
    if shown:
        parts.append(shown)

    if request.automatic:
        # The one thing a run must not be left to assume. "How the solution
        # should work" above was written by a model reading their sentence
        # (`rouh/triage.py`), and passing that off as the person's own words
        # is how a machine's guess becomes a requirement nobody asked for.
        parts.append(
            f"This is {request.kind} request {request.id} from the Gene therapy board, "
            "and nobody triaged it by hand. The section on how the solution should "
            "work is a reading of what the person wrote; the feedback itself is "
            "their own words. Where the two disagree, their words are the ones to "
            "build to.")
    else:
        parts.append(f"This is {request.kind} request {request.id} from the feedback "
                     "board. Everything above is the person's own words.")
    return "\n\n".join(p for p in parts if p)


def _files_section(heading: str, files: Iterable[Attachment]) -> str:
    lines = [f"- {f.path} ({f.media_type}, {f.size} bytes)"
             for f in files if f.path]
    if not lines:
        return ""
    return f"## {heading}\n\n" + "\n".join(lines)
