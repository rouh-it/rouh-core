"""Comments pinned to a page that is shared with people, the way Figma has them.

Petar, 24 September 2026 (fr_5879c0745f99):

    "On the collaborative page, where I have shared it with other people and
    they can use the Ask AI feature, I'd like to be able to ... add comments in
    the style of Figma. The person would press C or a comment button somewhere,
    probably next to the Ask AI icon, which should also be floating. ... you
    can click on the screen at one of the HTML elements and write a comment.
    The comment will be threaded, so people can answer each other. I'd like
    people to be able to tag each other and get an email notification about
    it. ... a resolve button that gets rid of the thread. That also means we
    need to be able to access all comments, even the ones that are resolved.
    ... if a comment is tied to a specific HTML element and we remove that
    element, what happens to the comment? One option is to keep the comment in
    roughly the same place ... The other option, and maybe those two can be
    combined, is that the deleted element can be saved to the comment."

The page draws all of it (`rouh/static/askai/comments.js`): the pins, the
thread beside one, the box to write in, the people to tag. This module is
what is kept and who may do what with it.

Whose comments they are
-----------------------

A page's comments belong to the page as its owner shared it: the owner's
``user_id`` and ``org_id`` and the page's path, the same three a share is kept
under (`sharing.Guests`). Everybody it is shared with reads and writes that
one set - that is what makes it a conversation - and every query here names
all three. What each message records besides is who wrote it.

Who may comment is **everybody who can open the page as themselves**: its
owner, on Rouh's canvas, and every person it is shared with by email, whether
they may change the page or only read it. Figma lets a viewer comment too,
and a comment changes nothing on the page. A visitor to a public link is
nobody - there is no name to put on a pin and nobody to tag - so a link shows
no comments at all, and nobody's name or address reaches it.

Tagging somebody
----------------

The people who can be tagged are exactly the people who can open the page
(`people`), and the page is only ever told their names and addresses, never
the tokens their links are made of. A tag is checked here against that list
and against the words of the message, so nobody can be emailed who is not on
the page, and nobody who is not named in what they are sent. Each tagged
person gets one letter from Rouh's own address (`rouh/mailer.py`) with the
words of the comment and a link that opens the page with that thread open:
their own link to it, or the invitation still waiting for them.

Ask AI in the threads
---------------------

Since fr_662a64715b9f Ask AI can go through every open thread and add to it
(`rouh/commentpass.py`). What it writes is a message like anybody's, under an
author no account can be (`AI_ID`), so the page draws it with the sparkle
rather than initials, nobody can edit it, and the owner can take it away like
any message. It never writes into a thread whose last word is already its
own (`reply_as_ai`), which is the rule Petar gave it: "If it already wrote in
that thread and nobody else said anything more, it should not add the second
message."

The element a comment was on
----------------------------

Each comment keeps two things about it: where it was (``anchor``: the
element's place in the page, its words, and the point clicked, both as a
share of the element and as a place on the page) and what it looked like
(``snapshot``: the element as markup with its styles written in, taken as the
comment was made). The pin is drawn at its share of the element, found again
on the page as it is now, so it moves with the element; the place on the page
is only for when the element is gone. Then the pin stays where it was, drawn
differently, and shows the snapshot, and anybody can put it onto another
element (`move`), which describes it and pictures it afresh. The snapshot is somebody else's markup,
so the page never puts it in as markup: it rebuilds it element by element out
of a short list of tags and attributes (``safeSnapshot`` in comments.js).
"""
from __future__ import annotations

import html
import logging
import math
import re
import threading
import time
from dataclasses import dataclass
from urllib.parse import quote, urlencode

log = logging.getLogger("rouh.comments")

#: The longest message kept. A comment is a few sentences, not a document.
BODY_MAX = 5000

#: The largest snapshot of an element kept. The page makes it smaller than
#: this itself, dropping pictures and then detail, before it sends it.
SNAPSHOT_MAX = 200_000

#: The most threads on one page, and messages in one thread.
THREADS_MAX = 500
MESSAGES_MAX = 300

#: Letters one person may cause in a day by tagging people. Rouh sends them
#: from its own address and pays nothing per letter, but a guest tagging the
#: same person in a loop should not be able to fill their inbox.
LETTERS_A_DAY = 100

#: The largest id taken from a page. One past what the column holds is "no
#: such comment", not a database error.
_ID_MAX = 2 ** 63 - 1

_LOCK = threading.Lock()

#: Ask AI, as the author of what it writes in a thread. No account has this
#: id: accounts are numbered.
AI_ID = "ai"
AI_NAME = "Ask AI"

#: Rouh, or one of its agents, as the author of what it writes through its
#: `page_comments` tool (`rouh/page_comments.py`). No account has this id
#: either. The name is kept on each message: Rouh in a chat, and its agent
#: when nobody was watching (a background job, a beat).
AGENT_ID = "rouh"
AGENT_NAME = "Rouh"
AGENT_JOB_NAME = "Rouh's agent"


class Refused(ValueError):
    """Something that was not done, the sentence saying why, and its status."""

    def __init__(self, words: str, status: int = 400) -> None:
        super().__init__(words)
        self.status = status


@dataclass(frozen=True)
class Place:
    """One page, as its owner shared it: whose comments these are."""

    org_id: str
    owner_id: str
    rel: str
    title: str = ""


@dataclass(frozen=True)
class Person:
    """Who is commenting: the account signed in, and whether it owns the page."""

    key: str
    user_id: str
    name: str
    email: str
    is_owner: bool = False


def clean_email(raw) -> str:
    from .sharing import clean_email as clean

    return clean(raw)


def key_for(email: str, user_id: str) -> str:
    """How a person is told apart on a page: their address, which is what a
    page is shared with, or their account when they have no address."""
    return clean_email(email) or f"u:{user_id}"


def name_of(user) -> str:
    """What a person is called on a pin and in a letter."""
    if user is None:
        return "Somebody"
    full = ""
    try:
        full = user.get_full_name()
    except AttributeError:
        pass
    return (full or getattr(user, "username", "") or "Somebody").strip()[:120]


def person_of(user, *, owner: bool) -> Person | None:
    """The account signed in, as a commenter, or None when it is nobody."""
    if user is None or not getattr(user, "is_authenticated", False):
        return None
    email = clean_email(getattr(user, "email", ""))
    return Person(key=key_for(email, str(user.pk)), user_id=str(user.pk), name=name_of(user),
                  email=email, is_owner=owner)


def ai_person() -> Person:
    """Ask AI, as a commenter."""
    return Person(key=AI_ID, user_id=AI_ID, name=AI_NAME, email="")


def agent_person(name: str = AGENT_NAME) -> Person:
    """Rouh or one of its agents, as a commenter. It acts for the page's
    owner, so it may take away what the owner may; it changes only what it
    wrote itself, as everybody does (`edit`)."""
    return Person(key=AGENT_ID, user_id=AGENT_ID, name=name or AGENT_NAME, email="",
                  is_owner=True)


def page_config(me: Person, open_thread: int = 0, ai_pass: bool = False) -> dict:
    """What the page is told before anything is fetched: who is looking, and
    which thread to open, from the link in a letter (`drawer_head`).
    ``ai_pass`` is whether this reader may have Ask AI answer the comments
    (`rouh/commentpass.py`): somebody who may change the page."""
    return {"me": {"key": me.key, "name": me.name, "owner": me.is_owner},
            "open": max(0, int(open_thread or 0)), "ai_pass": bool(ai_pass)}


# --- who can open the page ------------------------------------------------------------------


def _people(place: Place) -> list[dict]:
    """Everybody who can open this page, the owner first, with what a letter
    to each of them needs: their address and their own way in."""
    from .models import PageGuest, User

    out: list[dict] = []
    seen: set[str] = set()
    owner = User.objects.filter(pk=int(place.owner_id)).first() \
        if str(place.owner_id).isdigit() else None
    if owner is not None:
        email = clean_email(owner.email)
        key = key_for(email, str(owner.pk))
        seen.add(key)
        out.append({"key": key, "name": name_of(owner), "email": email, "owner": True,
                    "joined": True, "user_id": str(owner.pk), "token": ""})
    rows = list(PageGuest.objects.filter(user_id=place.owner_id, org_id=place.org_id,
                                         rel=place.rel).order_by("created_at", "token")[:200])
    # And everybody a task this page is in was shared with to change, who
    # opens it in their reader's page through the task's own link (`?at=`,
    # `rouh/taskshare.py`, `page_at`).
    tasks = _tasks_over(place.rel)
    rows += list(PageGuest.objects.filter(user_id=place.owner_id, org_id=place.org_id,
                                          rel__in=list(tasks), role="edit")
                 .order_by("created_at", "token")[:200])
    accounts = {str(u.pk): u for u in User.objects.filter(
        pk__in=[int(r.guest_id) for r in rows if str(r.guest_id).isdigit()])}
    for row in rows:
        email = clean_email(row.email)
        if not email or email in seen:
            continue
        seen.add(email)
        account = accounts.get(str(row.guest_id))
        out.append({"key": email, "name": name_of(account) if account else email,
                    "email": email, "owner": False, "joined": account is not None,
                    "user_id": str(account.pk) if account else "", "token": row.token,
                    "at": tasks.get(row.rel, "")})
    return out


def _tasks_over(rel: str) -> dict[str, str]:
    """Each task share's path this page could be inside, with where the page
    is from there: every folder above it, as `taskshare.PREFIX` names one."""
    from . import taskshare

    parts = [p for p in str(rel or "").split("/") if p]
    return {taskshare.PREFIX + "/".join(parts[:n]): "/".join(parts[n:])
            for n in range(1, len(parts))}


def _public(people: list[dict]) -> list[dict]:
    """The people as the page is told of them: never the token of anybody's link."""
    return [{"key": p["key"], "name": p["name"], "email": p["email"], "owner": p["owner"],
             "joined": p["joined"]} for p in people]


# --- what a page may send ----------------------------------------------------------------------

_PATH = re.compile(r"(?:[a-z][a-z0-9-]{0,40}:\d{1,5})(?:/[a-z][a-z0-9-]{0,40}:\d{1,5}){0,80}")
_TAG = re.compile(r"[a-z][a-z0-9-]{0,40}")
_SHORT = re.compile(r"[0-9a-z]{1,16}")


def _number(raw, low: float, high: float) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return low
    if math.isnan(value) or math.isinf(value):
        return low
    return min(max(value, low), high)


def _words(raw, most: int) -> str:
    return " ".join(str(raw or "").split())[:most]


def _short(raw) -> str:
    """A short fingerprint the page made of an element's words or look."""
    said = str(raw or "")
    return said if _SHORT.fullmatch(said) else ""


def clean_anchor(raw) -> dict:
    """Where a comment is pinned, as the page described it, kept to what the
    page reads back and to sizes a page could really have."""
    if not isinstance(raw, dict):
        raise Refused("There is nothing on the page to pin that to.")
    path = str(raw.get("path") or "")
    if path and not _PATH.fullmatch(path):
        raise Refused("That is not a place on the page.")
    tag = str(raw.get("tag") or "body").lower()
    if not _TAG.fullmatch(tag):
        raise Refused("That is not an element of the page.")
    return {
        "path": path,
        "tag": tag,
        "id": str(raw.get("id") or "")[:200],
        "cls": _words(raw.get("cls"), 200),
        "text": _words(raw.get("text"), 300),
        "hash": _short(raw.get("hash")),
        "sig": _short(raw.get("sig")),
        "label": _words(raw.get("label"), 120),
        "fx": _number(raw.get("fx"), 0.0, 1.0),
        "fy": _number(raw.get("fy"), 0.0, 1.0),
        "x": _number(raw.get("x"), 0.0, 1_000_000.0),
        "y": _number(raw.get("y"), 0.0, 10_000_000.0),
        "w": _number(raw.get("w"), 1.0, 100_000.0),
        # The point as a share of the element around it; -1 when there was none.
        "pfx": _number(raw.get("pfx"), -1.0, 1.0),
        "pfy": _number(raw.get("pfy"), -1.0, 1.0),
        # The passage Rouh pinned it by, when Rouh made it (`rouh/page_comments.py`):
        # what the page looks for when nothing else finds the element.
        "quote": _words(raw.get("quote"), 300),
    }


def clean_body(raw) -> str:
    """A message as it is kept: its own line breaks, no trailing space."""
    body = str(raw or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if "\x00" in body:
        body = body.replace("\x00", "")
    if not body:
        raise Refused("Write something first.")
    if len(body) > BODY_MAX:
        raise Refused(f"That is longer than {BODY_MAX} characters.")
    return body


def tagged(raw_keys, body: str, people: list[dict]) -> list[dict]:
    """Who a message tags: people who can open the page, and whose "@name"
    is really in its words. Anything else the page sent is dropped."""
    if not isinstance(raw_keys, list):
        return []
    wanted = [str(k) for k in raw_keys[:50] if isinstance(k, str)]
    out, seen = [], set()
    for person in people:
        if person["key"] in wanted and person["key"] not in seen \
                and ("@" + person["name"]) in body:
            seen.add(person["key"])
            out.append({"key": person["key"], "name": person["name"]})
    return out


def _id(raw) -> int:
    try:
        wanted = int(raw)
    except (TypeError, ValueError):
        raise Refused("There is no such comment.", 404) from None
    if not 0 < wanted <= _ID_MAX:
        raise Refused("There is no such comment.", 404)
    return wanted


# --- reading --------------------------------------------------------------------------------


def _who(key: str, name: str) -> dict:
    return {"key": key, "name": name or "Somebody"}


def _author(row) -> dict:
    if row.author_id == AI_ID:
        return {"key": AI_ID, "name": AI_NAME, "ai": True}
    if row.author_id == AGENT_ID:
        return {"key": AGENT_ID, "name": row.author_name or AGENT_NAME, "ai": True,
                "agent": True}
    return _who(key_for(row.author_email, row.author_id), row.author_name)


def _message(row, me: Person) -> dict:
    mine = row.author_id == me.user_id
    return {
        "id": int(row.id),
        "author": _author(row),
        "body": row.body,
        "mentions": [{"key": str(m.get("key") or ""), "name": str(m.get("name") or "")}
                     for m in (row.mentions or []) if isinstance(m, dict)],
        "created_at": row.created_at,
        "edited": bool(row.edited_at),
        "mine": mine,
        "can_delete": mine or me.is_owner,
    }


def _thread(row, messages: list, me: Person) -> dict:
    mine = row.author_id == me.user_id
    return {
        "id": int(row.id),
        "anchor": row.anchor or {},
        "has_snapshot": bool(row.snapshot),
        "created_at": row.created_at,
        "resolved": bool(row.resolved_at),
        "resolved_at": row.resolved_at,
        "resolved_by": row.resolved_by or "",
        "author": _author(row),
        "mine": mine,
        "can_delete": mine or me.is_owner,
        "messages": [_message(m, me) for m in messages],
    }


def _scoped(place: Place):
    from .models import PageComment

    return PageComment.objects.filter(owner_id=place.owner_id, org_id=place.org_id,
                                      rel=place.rel)


def threads(place: Place, me: Person) -> list[dict]:
    """Every thread on the page, oldest first, each with its messages. The
    snapshots are left out: they are large and only wanted one at a time."""
    from .models import PageCommentMessage

    rows = list(_scoped(place).defer("snapshot").order_by("id")[:THREADS_MAX])
    if not rows:
        return []
    by_thread: dict[int, list] = {int(r.id): [] for r in rows}
    for m in (PageCommentMessage.objects
              .filter(thread_id__in=list(by_thread), owner_id=place.owner_id,
                      org_id=place.org_id)
              .order_by("id")):
        got = by_thread.get(int(m.thread_id))
        if got is not None and len(got) < MESSAGES_MAX:
            got.append(m)
    # `has_snapshot` without reading them: a second small query.
    with_snapshot = set(_scoped(place).filter(id__in=list(by_thread)).exclude(snapshot="")
                        .values_list("id", flat=True))
    out = []
    for row in rows:
        if not by_thread[int(row.id)]:
            continue
        row.snapshot = "x" if int(row.id) in with_snapshot else ""
        out.append(_thread(row, by_thread[int(row.id)], me))
    return out


def listing(place: Place, me: Person) -> dict:
    """What the page draws: the threads, the people who can be tagged, and who
    is looking."""
    people = _people(place)
    return {"threads": threads(place, me), "people": _public(people),
            "me": {"key": me.key, "name": me.name, "owner": me.is_owner}}


def snapshot(place: Place, thread_id) -> str:
    """The element a thread was pinned to, as it looked when it was made."""
    row = _scoped(place).filter(id=_id(thread_id)).values("snapshot").first()
    if row is None:
        raise Refused("There is no such comment.", 404)
    return row["snapshot"] or ""


# --- writing --------------------------------------------------------------------------------


def _one_thread(place: Place, thread_id):
    row = _scoped(place).filter(id=_id(thread_id)).first()
    if row is None:
        raise Refused("That comment is not there any more.", 404)
    return row


def _say(place: Place, me: Person, thread, body: str, mentions: list[dict]):
    from .models import PageCommentMessage

    return PageCommentMessage.objects.create(
        thread=thread, owner_id=place.owner_id, org_id=place.org_id, author_id=me.user_id,
        author_name=me.name, author_email=me.email, body=body, mentions=mentions,
        created_at=time.time())


def start(place: Place, me: Person, anchor, snapshot_html, body, mention_keys) -> tuple[dict, dict]:
    """A new thread with its first message. Returns it as the page draws it,
    and the message it starts with, for the letters."""
    from . import pageplaces
    from .models import PageComment

    where = clean_anchor(anchor)
    words = clean_body(body)
    shot = str(snapshot_html or "")
    if len(shot) > SNAPSHOT_MAX:
        shot = ""
    people = _people(place)
    mentions = tagged(mention_keys, words, people)
    with _LOCK:
        if _scoped(place).count() >= THREADS_MAX:
            raise Refused(f"This page already has {THREADS_MAX} comments.")
        row = PageComment.objects.create(
            owner_id=place.owner_id, org_id=place.org_id, rel=place.rel, author_id=me.user_id,
            author_name=me.name, author_email=me.email, anchor=where, snapshot=shot,
            created_at=time.time())
        first = _say(place, me, row, words, mentions)
    # Which page this is, so the thread follows it when its folder moves.
    pageplaces.remember(place.rel)
    log.info("comments: a thread was started on %s (%d tagged)", place.rel, len(mentions))
    return _thread(row, [first], me), {"message": int(first.id), "thread": int(row.id),
                                       "mentions": mentions, "body": words}


def reply(place: Place, me: Person, thread_id, body, mention_keys) -> tuple[dict, dict]:
    """A reply at the end of a thread."""
    from .models import PageCommentMessage

    row = _one_thread(place, thread_id)
    words = clean_body(body)
    mentions = tagged(mention_keys, words, _people(place))
    with _LOCK:
        if PageCommentMessage.objects.filter(thread=row).count() >= MESSAGES_MAX:
            raise Refused(f"This thread already has {MESSAGES_MAX} messages.")
        said = _say(place, me, row, words, mentions)
    return _message(said, me), {"message": int(said.id), "thread": int(row.id),
                                "mentions": mentions, "body": words}


def reply_as_ai(place: Place, thread_id, body, mention_keys) -> dict | None:
    """Ask AI's reply at the end of a thread, for the letters; or None, and
    nothing written, when the thread has been resolved or taken away since,
    or already ends with Ask AI's own words."""
    from .models import PageCommentMessage

    row = _scoped(place).filter(id=_id(thread_id)).first()
    if row is None or row.resolved_at:
        return None
    words = clean_body(body)
    mentions = tagged(mention_keys, words, _people(place))
    with _LOCK:
        said = list(PageCommentMessage.objects.filter(thread=row).order_by("-id")
                    .values_list("author_id", flat=True)[:MESSAGES_MAX])
        if not said or said[0] == AI_ID or len(said) >= MESSAGES_MAX:
            return None
        made = _say(place, ai_person(), row, words, mentions)
    return {"message": int(made.id), "thread": int(row.id), "mentions": mentions,
            "body": words}


def _one_message(place: Place, message_id):
    from .models import PageCommentMessage

    row = (PageCommentMessage.objects.select_related("thread")
           .filter(id=_id(message_id), owner_id=place.owner_id, org_id=place.org_id,
                   thread__rel=place.rel, thread__owner_id=place.owner_id,
                   thread__org_id=place.org_id)
           .first())
    if row is None:
        raise Refused("That message is not there any more.", 404)
    return row


def edit(place: Place, me: Person, message_id, body, mention_keys) -> tuple[dict, dict]:
    """A message changed by the person who wrote it. Only people it tags now
    and did not before are sent a letter."""
    from .models import PageCommentMessage

    row = _one_message(place, message_id)
    if row.author_id != me.user_id:
        raise Refused("Only the person who wrote that can change it.", 403)
    words = clean_body(body)
    mentions = tagged(mention_keys, words, _people(place))
    before = {str(m.get("key")): m for m in (row.mentions or []) if isinstance(m, dict)}
    kept = [{**before[m["key"]], **m} if m["key"] in before else m for m in mentions]
    PageCommentMessage.objects.filter(id=row.id, owner_id=place.owner_id,
                                      org_id=place.org_id).update(
        body=words, mentions=kept, edited_at=time.time())
    row.body, row.mentions, row.edited_at = words, kept, time.time()
    new = [m for m in mentions if m["key"] not in before]
    return _message(row, me), {"message": int(row.id), "thread": int(row.thread_id),
                               "mentions": new, "body": words}


def remove_message(place: Place, me: Person, message_id) -> dict:
    """A message taken away by who wrote it, or by the page's owner. The
    first message of a thread is the thread, so taking it takes the thread,
    as Figma does."""
    from .models import PageCommentMessage

    row = _one_message(place, message_id)
    if row.author_id != me.user_id and not me.is_owner:
        raise Refused("Only the person who wrote that can remove it.", 403)
    first = (PageCommentMessage.objects.filter(thread_id=row.thread_id)
             .order_by("id").values_list("id", flat=True).first())
    if first == row.id:
        _scoped(place).filter(id=row.thread_id).delete()
        return {"removed": "thread", "thread": int(row.thread_id)}
    PageCommentMessage.objects.filter(id=row.id, owner_id=place.owner_id,
                                      org_id=place.org_id).delete()
    return {"removed": "message", "thread": int(row.thread_id), "message": int(row.id)}


def remove_thread(place: Place, me: Person, thread_id) -> dict:
    """A whole thread taken away, by who started it or by the page's owner."""
    row = _one_thread(place, thread_id)
    if row.author_id != me.user_id and not me.is_owner:
        raise Refused("Only the person who started it, or the page's owner, can remove it.",
                      403)
    _scoped(place).filter(id=row.id).delete()
    return {"removed": "thread", "thread": int(row.id)}


def move(place: Place, me: Person, thread_id, anchor, snapshot_html) -> dict:
    """Put a thread onto another part of the page: where it is pinned, and the
    picture of what it is on, as the page described the element it was
    dropped on. Anybody on the page may, as anybody may resolve it: it changes
    what the comment points at, never what anybody said (fr_a383dc8329c0)."""
    row = _one_thread(place, thread_id)
    where = clean_anchor(anchor)
    shot = str(snapshot_html or "")
    if len(shot) > SNAPSHOT_MAX:
        shot = ""
    _scoped(place).filter(id=row.id).update(anchor=where, snapshot=shot)
    log.info("comments: thread %s on %s was moved onto a <%s>", row.id, place.rel, where["tag"])
    return {"thread": {"id": int(row.id), "anchor": where, "has_snapshot": bool(shot)}}


def resolve(place: Place, me: Person, thread_id, done: bool) -> dict:
    """Resolve a thread, or open it again. Anybody on the page may do either."""
    row = _one_thread(place, thread_id)
    changes = ({"resolved_at": time.time(), "resolved_by": me.name} if done
               else {"resolved_at": None, "resolved_by": ""})
    _scoped(place).filter(id=row.id).update(**changes)
    return {"thread": int(row.id), "resolved": bool(done),
            "resolved_by": changes["resolved_by"], "resolved_at": changes["resolved_at"]}


# --- letters to the people tagged ----------------------------------------------------------


def _letters_today(me: Person) -> int:
    from .models import PageCommentMessage

    rows = PageCommentMessage.objects.filter(
        author_id=me.user_id, created_at__gte=time.time() - 86_400).values_list("mentions",
                                                                                 flat=True)
    return sum(1 for mentions in rows for m in (mentions or [])
               if isinstance(m, dict) and m.get("mailed"))


def link_for(base: str, place: Place, person: dict, thread_id: int) -> str:
    """The address that opens the page with this thread open, for this person:
    Rouh's own address for the page, for its owner; their own link to it, for
    somebody it is shared with; the invitation, for somebody who has not made
    their account yet."""
    base = str(base or "").rstrip("/")
    ask = f"?comment={int(thread_id)}"
    if person.get("at"):
        # A page of a task shared with them: the task's link, at this page.
        ask = "?" + urlencode({"at": person["at"]}) + f"&comment={int(thread_id)}"
    if person["owner"]:
        return f"{base}/task/{quote(place.rel, safe='/')}{ask}"
    if person["joined"]:
        return f"{base}/shared/{person['token']}{ask}"
    return f"{base}/join/{person['token']}{ask}"


def letter(author: str, title: str, body: str, person: dict, link: str):
    """The letter to somebody who was tagged: who, where, the words, the way in."""
    from .mailer import Letter

    title = title or "a page"
    quoted = "\n".join("  " + line for line in body.splitlines())
    joining = not person["owner"] and not person["joined"]
    after = ("To open it, make your account: it takes your name and a password."
             if joining else "")
    text = (f"{author} mentioned you in a comment on {title}:\n\n{quoted}\n\n"
            + (after + "\n\n" if after else "") + f"Open the comment:\n\n  {link}\n")
    e = html.escape
    lines = "<br>".join(e(line) for line in body.splitlines())
    button = "Make your account and open it" if joining else "Open the comment"
    body_html = (
        '<div style="font:15px/1.55 -apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif;'
        'color:#1b1c1e;max-width:520px">'
        f"<p>{e(author)} mentioned you in a comment on "
        f'<span style="font-weight:600">{e(title)}</span>:</p>'
        '<blockquote style="margin:14px 0;padding:10px 14px;border-left:3px solid #4c8dff;'
        f'background:#f3f5f8;border-radius:0 8px 8px 0">{lines}</blockquote>'
        + (f"<p>{e(after)}</p>" if after else "")
        + f'<p style="margin:22px 0"><a href="{e(link, quote=True)}" style="background:#4c8dff;'
        'color:#04070c;padding:11px 18px;border-radius:9px;text-decoration:none;'
        f'font-weight:600">{e(button)}</a></p>'
        f'<p style="color:#5d6674;font-size:13px">Or paste this into your browser:<br>'
        f"{e(link)}</p></div>")
    return Letter(to=person["email"], subject=f"{author} mentioned you on “{title}”",
                  text=text, html=body_html)


def pass_letter(title: str, person: dict, said: list[tuple[str, str, str]]):
    """The one letter somebody gets when Ask AI tagged them during a pass over
    a page's comments, however many threads it tagged them in: for each, what
    the comment was on, what Ask AI said, and the link that opens it."""
    from .mailer import Letter

    title = title or "a page"
    many = len(said) > 1
    head = (f"Ask AI answered the comments on {title}, and tagged you in "
            f"{len(said)} threads:" if many else
            f"Ask AI answered the comments on {title}, and tagged you:")
    text = head + "\n\n" + "\n\n".join(
        (f"On {on}:\n" if on else "") + "\n".join("  " + line for line in body.splitlines())
        + f"\n\n  Open it: {link}" for on, body, link in said) + "\n"
    e = html.escape
    blocks = "".join(
        (f'<p style="margin:18px 0 6px;color:#5d6674;font-size:13px">On {e(on)}</p>'
         if on else "")
        + '<blockquote style="margin:0 0 8px;padding:10px 14px;border-left:3px solid #6d5cf0;'
        'background:#f3f5f8;border-radius:0 8px 8px 0">'
        + "<br>".join(e(line) for line in body.splitlines()) + "</blockquote>"
        + f'<p style="margin:0 0 14px"><a href="{e(link, quote=True)}" style="color:#3d6fe0">'
        "Open this comment</a></p>" for on, body, link in said)
    body_html = (
        '<div style="font:15px/1.55 -apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif;'
        'color:#1b1c1e;max-width:520px">'
        f"<p>{e(head)}</p>{blocks}</div>")
    return Letter(to=person["email"], subject=f"Ask AI tagged you on “{title}”",
                  text=text, html=body_html)


def to_send(place: Place, me: Person, said: dict, base: str) -> list[tuple[dict, object]]:
    """The letters one message causes: one per person it newly tags, never to
    its own author, never past the day's ceiling. Each with who it is for."""
    wanted = {m["key"] for m in said.get("mentions") or []}
    if not wanted:
        return []
    room = LETTERS_A_DAY - _letters_today(me)
    out = []
    for person in _people(place):
        if person["key"] not in wanted or person["key"] == me.key:
            continue
        if not person["email"]:
            out.append((person, None))
            continue
        if room <= 0:
            out.append((person, "limit"))
            continue
        room -= 1
        out.append((person, letter(me.name, place.title, said["body"], person,
                                   link_for(base, place, person, said["thread"]))))
    return out


def record_letters(place: Place, message_id: int, results: list[dict]) -> None:
    """Write down, on the message, whether each letter went."""
    from .models import PageCommentMessage

    row = PageCommentMessage.objects.filter(id=int(message_id), owner_id=place.owner_id,
                                            org_id=place.org_id).first()
    if row is None:
        return
    by_key = {r["key"]: r for r in results}
    mentions = []
    for m in row.mentions or []:
        if isinstance(m, dict) and m.get("key") in by_key:
            got = by_key[m["key"]]
            m = {**m, "mailed": bool(got["sent"]), "why": got.get("why", "")}
        mentions.append(m)
    PageCommentMessage.objects.filter(id=row.id).update(mentions=mentions)


async def send_letters(cfg, place: Place, me: Person, said: dict) -> list[dict]:
    """Send the letters one message causes. Returns, for each person tagged,
    whether their letter went and, when it did not, the sentence why."""
    import asyncio

    from . import mailer

    planned = await asyncio.to_thread(to_send, place, me, said, cfg.public_url)
    if not planned:
        return []
    post = mailer.Mailer(cfg)

    async def one(person, made) -> dict:
        said_to = {"key": person["key"], "name": person["name"], "sent": False, "why": ""}
        if made is None:
            said_to["why"] = "they have no email address"
            return said_to
        if made == "limit":
            said_to["why"] = f"you have sent the {LETTERS_A_DAY} letters a day tags may send"
            return said_to
        try:
            await post.send(made)
        except (mailer.NotSetUp, mailer.NotSent) as exc:
            said_to["why"] = str(exc).rstrip(".")
            return said_to
        said_to["sent"] = True
        return said_to

    results = list(await asyncio.gather(*(one(p, m) for p, m in planned)))
    await asyncio.to_thread(record_letters, place, said["message"], results)
    log.info("comments: %d of %d letters for a tag on %s went", sum(r["sent"] for r in results),
             len(results), place.rel)
    return results
