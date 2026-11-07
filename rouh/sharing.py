"""Pages of the workspace, made public.

A page built in the workspace is an explainer: one self-contained `index.html`
under the step that produced it, usually with the Ask AI drawer on it. Until
this module every one of them was behind Rouh's sign-in, so the only way to
show one to anybody was a screenshot. This is the other door: the owner of a
page turns it public, gets a link, and anybody who has that link opens the page
with no account, no sign-in and no password.

What is shared, and what is not
-------------------------------

**One page, as it is on disk.** Not the task it belongs to, not the step's
notes, not the workspace around it, and nothing the reader could climb to from
it. A share names one path and the public route serves that path and no other:
a link inside the page to another page of the workspace is a link to an address
that answers "Not found" to somebody who is not signed in, exactly as it did
before any of this existed.

**Or one task, or one subtask** (since 12 October 2026, fr_80eaca4ddcbf): the
same row, link and panel, naming the task's folder rather than a page, and
served as the task and what sits under it (`rouh/taskshare.py` says exactly
what that is, and what it never is). Its link is read only. Shared with one
person it is read or changed as the owner said, as a page is (since 13
October 2026: `role_for`).

**No Ask AI, unless the owner says a visitor may change the page.** A link is
read-only by default (`VIEW`), and a read-only link serves the page and stops,
for the two reasons that held on 23 September 2026 and still hold for it: a
drawer's questions can only leave a framed page through a page around it
(``pages.ask_script``), and ``POST /api/askai/ask`` is a model call on this
install's key.

Petar, 24 September 2026 (fr_edecde0ad6e6): "in rare cases, we would like
shared and public pages to have the ability to edit that HTML... I'll take the
risk for now." So a link can be made changeable (`EDIT`, `role` on the row), and
then everything those two reasons asked for is there: a page of Rouh's own
around the shared one that carries the drawer's questions, routes scoped to the
token, a ceiling on questions a day, and the owner's key paying for them, as he
said it should (``rouh/web/guests.py``). Every change a visitor makes can be put
back and is saved like any other (``askai.py``, "Changing the page").

**Or with one person, by their email address** (`Guests`, at the end of this
module): a letter, an account made from it, and the page with Ask AI on it for
that account alone.

**Never a listing.** There is no index of public pages at the public end. The
person who owns them has one, behind the sign-in (`mine`), which is what
"See all public pages" opens.

The token is the whole of the credential
----------------------------------------

`find` and `opened` are the methods here that take no identity, and that is
the point: a visitor has none. The token is 32 url-safe characters from `secrets`, so it is
a secret in its own right, and the page it names is what the person deliberately
made public. Every other method takes the identity it is asking about and puts
both ids in the WHERE clause, even where the token alone is unique: a caller
holding the wrong person is the bug worth turning into "no such page" rather
than into one person taking another person's page down - or, far worse,
publishing it.

One link per page, and it never changes
---------------------------------------

Petar, 7 October 2026 (fr_d687af2e4fd1): "now that I have shared this with
someone or made it public, the copy link button should be working. in google
drive I think the public link stays the same, here also we should keep the
public link stable and just manage permissions."

So a page has one link, `/p/<token>`, made the first time anybody asks for it
(`link`) and kept for as long as the page is: the row is never deleted to take
a page down. Who the link lets in is the permissions, read when it is opened
(`rouh/web/views.py`, `public_page`):

- **Public** (`public` on the row): anybody, signed in or not.
- **Not public**: the owner, who lands on the page in their own Rouh, and the
  people it is shared with by email, who land on their own reader's page
  (`/shared/<token>`). Somebody not signed in is asked to sign in first, and
  anybody else signed in is told it is not shared with them. Nobody else is
  shown a word of it.

Turning it off
--------------

`stop` turns `public` off. The token is kept, so turning it on again brings
back the very link that was sent, as Drive does, but from that moment a
stranger opening it is refused: nothing is kept for a grace period and nothing
is cached in front of it, because the header on every public answer is
`no-store` (`pages.HEADERS`). What a link cannot take back is a copy somebody
already saved, which is what the panel says on screen in as many words.

Two doors onto the same rows
----------------------------

**Share** in the top bar is one; the assistant's own `publish_task` and
`check_task_sharing` (`rouh/tools.py`) are the other, so "make task 56 public"
said out loud does exactly what pressing the button on each of its pages would.
Same rows, same tokens, same route, and the same rule for what may go out
(`shareable`): the tools add nothing here but a way to name a whole task, and
`sensitive`, which is what makes the assistant ask about money, health and
contact details before it publishes anything that has them.
"""
from __future__ import annotations

import html
import logging
import re
import secrets
import threading
import time
from pathlib import Path

log = logging.getLogger("rouh.sharing")

#: Where a public page is served. Short on purpose: this is the part of the
#: address a person pastes into a message.
ROUTE = "/p/"

#: How many bytes of randomness a token carries. 24 bytes is 32 url-safe
#: characters, which is far past guessing and still short enough to read out.
TOKEN_BYTES = 24

#: The longest token accepted from an address at all. A token is fixed-length,
#: so this only exists to keep a nonsense address from reaching the database
#: as a very long string.
TOKEN_MAX = 128

#: The most public pages listed at once. A person with more than this has a
#: different problem than this screen.
LIST_MAX = 500

#: The rows are `rouh.models.PublicPage`, in the `public_pages` table. One
#: link per page per person is a unique constraint on (user_id, rel), so
#: pressing "make it public" twice, or taking it down and making it public
#: again, hands back the link that is already out there rather than minting a
#: second one that takes the first one's place.


def path_for(token: str) -> str:
    """The address a public page is served at, as the browser needs it."""
    return ROUTE + str(token or "")


def link_for(public_url: str, token: str) -> str:
    """The whole link, for somebody who is not looking at Rouh at all.

    The panel builds its link from the address the browser is at. The
    assistant has no browser to ask, and the link it hands over is going into
    a message to somebody else, so it is built from the address this Rouh is
    reached at from outside (`config.public_url`).
    """
    return str(public_url or "").rstrip("/") + path_for(token)


#: The kind of file that may be made public. A share is a page, not a folder
#: and not one of the files beside one: a picture or a script handed its own
#: public address would be a second way in that nobody asked for. Everything a
#: page needs is already inside it by the time it is served
#: (`pages.with_files`).
SUFFIX = ".html"


def shareable(root, rel: str) -> tuple[str, str]:
    """The page `rel` names and its title, or `pages.Refused` saying why not.

    Exactly `pages.py`'s own rules, through `pages.check`, so a path that could
    never have been served signed in can never be made public either. The
    suffix is checked as the address was written as well as after the links in
    it were followed, which is the same pairing `pages.read` does. The one
    rule, for the Share panel and the assistant's tools alike.
    """
    from . import pages, taskshare

    rel = str(rel or "")
    if taskshare.is_task(rel):
        # A task or a subtask, since 12 October 2026 (`rouh/taskshare.py`).
        return taskshare.shareable(root, rel)
    if not rel.lower().endswith(SUFFIX):
        raise pages.Refused("Only a page can be made public.")
    target = pages.check(root, rel, rel)
    return rel, pages.title_of(target)


# --- what is never published without its own yes ---------------------------
#
# "A task whose AGENTS.md or pages contain money, runway, burn, revenue,
# personal health detail or anybody's private contact details is not published
# without saying so explicitly first and getting a yes to that specific
# point." That is the person's rule, and it is a rule the assistant cannot
# keep from memory: it has usually not read the task it is asked to publish.
# So the text is looked at here, and `publish_task` refuses until the person
# has said yes to each kind that was found.
#
# It is found by looking for words and shapes, not by understanding the page,
# so it can miss something and it can find something harmless - a ticket price
# is money. It is there so the question gets asked; the person answers it.

#: The kinds, in the words the assistant says out loud and passes back.
MONEY, HEALTH, CONTACT = "money", "health", "contact details"
KINDS = (MONEY, HEALTH, CONTACT)

_MONEY_WORDS = (r"runway|burn(?:\s+rate)?|revenues?|turnover|salar(?:y|ies)|payroll|"
                r"valuation|invoices?|invoiced|budgets?|cash\s*flow|profits?|ebitda|"
                r"p&l|bank\s+balance|fundrais(?:e|ing)|funding\s+round|"
                r"euros?|dollars?|leva|stotinki")
#: Not "diagnostics", "symptom" or a program's `doctor` command: this is a
#: workspace full of debugging, and those are its words far more often than a
#: body's. Measured over the whole workspace on 23 September 2026 they were
#: most of what this found in tasks that have nothing to do with health.
_HEALTH_WORDS = (r"diagnos[ie]s|diagnosed|medications?|medicines?|prescri\w+|dosage|"
                 r"(?<!claude )(?<!brew )(?<!flutter )(?<!npm )doctors?|physio\w*|"
                 r"surgery|surgeon|injur(?:y|ies|ed)|pain(?!\s+points?)|painful|mri|"
                 r"x-rays?|blood\s+tests?|therap(?:y|ies|ist)|allerg\w*|illness|"
                 r"disease|hospital|clinic|mental\s+health|pregnan\w*|rehab\w*|"
                 r"tendon\w*|fractur\w*|inflammation|chronic")

#: What each kind looks like. Every pattern is searched on the text a reader
#: sees - tags, scripts and styles taken out - so a CSS `margin` or a
#: picture's `@2x` is not money or an address.
_LOOKS = {
    MONEY: [
        # A dollar sign after a number is a shell prompt far more often than a
        # price, so only the euro and the pound are read that way round.
        re.compile(r"[€$£]\s?\d[\d.,]*|\d[\d.,]*\s?(?:[€£]|лв\.?|bgn\b|eur\b|usd\b|gbp\b)",
                   re.I),
        re.compile(r"\b(?:MRR|ARR)\b"),
        re.compile(rf"\b(?:{_MONEY_WORDS})\b", re.I),
    ],
    HEALTH: [re.compile(rf"\b(?:{_HEALTH_WORDS})\b", re.I)],
    CONTACT: [
        # Not `git@github.com`, which is how a repository is addressed, and
        # not a no-reply address, which reaches nobody.
        re.compile(r"(?<![\w.%+-])(?!git@|no-?reply@)[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+"
                   r"(?:\.[A-Za-z0-9-]+)*"
                   r"\.(?!(?:png|jpe?g|gif|svg|webp|css|js|html?)\b)[A-Za-z]{2,}"),
        re.compile(r"(?<![\w+])\+\d{1,3}[\s.-]?\(?\d{1,4}\)?(?:[\s.-]?\d{2,4}){2,4}(?!\w)"),
        re.compile(r"\b(?:tel|phone|mobile|cell|gsm|телефон|тел)\b\.?:?\s*\+?\d[\d\s().-]{6,}\d",
                   re.I),
    ],
}

#: How many examples of one kind are handed back. Enough to say what it is;
#: the point is the question, not an inventory.
EXAMPLES = 3

#: How much of one file is looked at. A page is served whole, so it is read
#: whole, up to far past the size of any page in the workspace.
SCAN_MAX = 5_000_000

_DROP = re.compile(r"<(script|style|svg|template|noscript)\b[^>]*>.*?</\1\s*>", re.I | re.S)
_TAG = re.compile(r"<[^>]+>")
_LINKED = re.compile(r"""href\s*=\s*["']?(?:mailto|tel):([^"'\s>?]+)""", re.I)


def readable_text(raw: str, is_html: bool) -> str:
    """What a reader of the file actually sees, on one line.

    A `mailto:` or `tel:` link is kept even though it is inside a tag, because
    the address it holds is published along with the page whether or not the
    page shows it.
    """
    if not is_html:
        return " ".join(str(raw or "").split())
    linked = " ".join(_LINKED.findall(raw))
    text = _TAG.sub(" ", _DROP.sub(" ", raw))
    return " ".join((html.unescape(text) + " " + linked).split())


#: The other words a kind arrives as, from a model that paraphrased it.
_SAID = {"finance": MONEY, "financial": MONEY, "finances": MONEY, "prices": MONEY,
         "price": MONEY, "medical": HEALTH, "contact": CONTACT, "contacts": CONTACT,
         "contact detail": CONTACT, "email": CONTACT, "emails": CONTACT,
         "phone": CONTACT, "phones": CONTACT}


def agreed(said) -> set[str]:
    """The kinds the person has said yes to, out of what the tool was given."""
    if isinstance(said, str):
        said = [said]
    if not isinstance(said, (list, tuple)):
        return set()
    out = set()
    for one in said:
        word = " ".join(str(one or "").strip().lower().replace("_", " ").split())
        if word in KINDS:
            out.add(word)
        elif word in _SAID:
            out.add(_SAID[word])
    return out


def sensitive(root, files: list[tuple[str, str]]) -> dict[str, dict]:
    """What in these files needs its own yes before it is published.

    `files` is `(path in the workspace, where to say it is)` pairs: the task's
    own notes and every page about to go out. The answer has one entry per
    kind found, `{"where": [...], "found": [...]}`: every place it turned up,
    and up to `EXAMPLES` of what matched, which is the words themselves - a
    price, "runway", an address - and never the sentence around them. A
    sentence of a page is somebody's writing and could say anything to the
    model reading it; what these patterns match cannot. A kind that is not
    found is not in the answer, so an empty one means nothing was found, not
    that nothing is there.
    """
    base = Path(root)
    out: dict[str, dict] = {}
    for rel, where in files:
        try:
            with open(base / rel, encoding="utf-8", errors="replace") as fh:
                raw = fh.read(SCAN_MAX)
        except OSError:
            continue
        text = readable_text(raw, rel.lower().endswith(SUFFIX))
        for kind in KINDS:
            matched = [m.group(0).strip() for pattern in _LOOKS[kind]
                       for m in pattern.finditer(text)]
            if not matched:
                continue
            have = out.setdefault(kind, {"where": [], "found": []})
            if where not in have["where"]:
                have["where"].append(where)
            for word in matched:
                if len(have["found"]) >= EXAMPLES:
                    break
                if word.lower() not in (w.lower() for w in have["found"]):
                    have["found"].append(word)
    return out


def clean_token(raw: str) -> str:
    """A token as it arrived, or empty if it could never be one of ours.

    Checked before the database is asked at all: a token is url-safe base64 and
    nothing else, so anything with a slash, a dot or a percent sign in it is
    refused here rather than turned into a query.
    """
    token = str(raw or "")
    if not token or len(token) > TOKEN_MAX:
        return ""
    ok = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")
    return token if set(token) <= ok else ""


#: What a reader may do with what is shared with them, lowest first: read it; read it and
#: change it with Ask AI; and, for a task, a goal, a quest or a step shared with one of the
#: owner's trusted contacts, decide for the owner there too (`rouh/task_access.py`, the one
#: permission every check reads, DELEGATION.md). Each includes the ones before it. A link has
#: only the first two.
VIEW, EDIT, DECIDE = "view", "edit", "decide"
ROLES = (VIEW, EDIT, DECIDE)
RANK = {VIEW: 1, EDIT: 2, DECIDE: 3}


def role_of(raw) -> str:
    """One of `ROLES` out of whatever was sent: anything not one of them is "view"."""
    said = str(raw or "").strip().lower()
    return said if said in ROLES else VIEW


def can_edit(role) -> bool:
    """Whether a role lets its reader change what is shared: edit, or decide, which includes it."""
    return RANK.get(role_of(role), 0) >= RANK[EDIT]


def role_for(rel: str, raw, person: bool = False) -> str:
    """What a reader of this path may do: `role_of`, except that a task's link
    is only ever read, and only a person may decide, and only over a task.

    A link to a task is anybody who has it, and a whole task changed by
    anybody is more than any link was meant to carry. A task shared with one
    `person` is somebody the owner chose, so it takes the role they asked for,
    exactly as a page does: Petar, 13 October 2026, "sharing can mean read or
    edit depending on my ask" (`rouh/taskshare.py`). A page has no decisions, so
    deciding on one is editing it.
    """
    from . import taskshare

    if taskshare.is_task(rel) and not person:
        return VIEW
    role = role_of(raw)
    if role == DECIDE and not (person and taskshare.is_task(rel)):
        return EDIT
    return role


def _follow(force: bool = True) -> None:
    """Point every share at where its page is now, before one is looked up by path.

    A page whose folder has moved is the same page (`rouh/pageplaces.py`), so
    the owner asking about it at its new path is asking about the shares it
    already has, not about a page nobody has shared yet.
    """
    from . import pageplaces, taskshare

    pageplaces.follow(force=force)
    if force:
        taskshare.follow(pageplaces.ROOT)


def _read_at(share: dict | None) -> dict | None:
    """A share found by its token, naming where its page is now.

    None when its path now holds a different page than the one that was
    shared, which is never served in its place (`pageplaces.where`).
    """
    from . import pageplaces, taskshare

    if share is None:
        return None
    if taskshare.is_task(share["rel"]):
        return {**share, "rel": taskshare.reading(share["rel"], pageplaces.ROOT)}
    rel = pageplaces.reading(share["rel"])
    if rel is None:
        log.warning("share %s... names %s, which is another page now; not served",
                    share["token"][:6], share["rel"])
        return None
    return {**share, "rel": rel}


def _row(row) -> dict:
    """One share, as every caller has always been handed it."""
    return {
        "token": row.token,
        "rel": row.rel,
        "title": row.title or "",
        "path": path_for(row.token),
        "created_at": row.created_at,
        "role": role_of(getattr(row, "role", VIEW)),
        "public": bool(getattr(row, "public", True)),
        "owner_id": str(row.user_id),
        "org_id": str(row.org_id),
    }


class Shares:
    """Each page's one link, and whether it is public.

    One row per page whose link anybody has asked for. A page that is not
    public either has no row or has one with `public` off, which keeps its
    token so its link never changes (see "One link per page" above).

    The rows are Django's (`rouh.models.PublicPage`) since the move into
    PostgreSQL on 23 September 2026. The path the constructor used to open is
    still accepted, and not used.
    """

    def __init__(self, db_path: str | None = None) -> None:
        self._lock = threading.Lock()

    def close(self) -> None:
        """Nothing to close: the connection is Django's, one per thread."""

    # -- the owner's side, every query scoped to them ----------------------

    def state(self, who, rel: str) -> dict | None:
        """This person's share of this page, or None if it is not public."""
        from .models import PublicPage

        _follow()
        with self._lock:
            row = PublicPage.objects.filter(user_id=who.user_id, org_id=who.org_id,
                                            rel=str(rel or ""), public=True).first()
        return _row(row) if row else None

    def link(self, who, rel: str, title: str = "") -> dict:
        """This page's one link, made now if nobody has asked for it before.

        Making it changes nobody's access: a new one is not public, and lets in
        only the owner and the people the page is shared with. What it is
        handed back with says whether it is public.
        """
        from django.db import IntegrityError

        from . import pageplaces
        from .models import PublicPage

        rel = str(rel or "")
        _follow()
        with self._lock:
            row = PublicPage.objects.filter(user_id=who.user_id, org_id=who.org_id,
                                            rel=rel).first()
            if row is not None:
                return _row(row)
            pageplaces.remember(rel)
            try:
                row = PublicPage.objects.create(
                    token=secrets.token_urlsafe(TOKEN_BYTES), user_id=who.user_id,
                    org_id=who.org_id, rel=rel, title=(title or "")[:200],
                    created_at=time.time(), role=VIEW, public=False)
            except IntegrityError:
                # Another process made it a moment ago: theirs is the link.
                row = PublicPage.objects.get(user_id=who.user_id, org_id=who.org_id, rel=rel)
        return _row(row)

    def share(self, who, rel: str, title: str = "", role: str | None = None) -> dict:
        """Make this page public, and hand back its share.

        Already public is not an error and does not mint a second token, and
        nor does a page that was public once, or whose link was copied before
        it was public: the link the person has already sent somebody is the one
        made public, and only the title - and what a visitor may do, when
        ``role`` is given - is brought up to date. A new link is read-only
        unless it is said otherwise.
        """
        from . import pageplaces
        from .models import PublicPage

        rel = str(rel or "")
        title = (title or "")[:200]
        _follow()
        pageplaces.remember(rel)
        with self._lock:
            row = PublicPage.objects.filter(user_id=who.user_id, org_id=who.org_id,
                                            rel=rel).first()
            if row is not None:
                changes = {} if row.public else {"public": True}
                if title and title != row.title:
                    changes["title"] = title
                if role is not None and role_for(rel, role) != row.role:
                    changes["role"] = role_for(rel, role)
                if changes:
                    PublicPage.objects.filter(token=row.token, user_id=who.user_id,
                                              org_id=who.org_id).update(**changes)
                    row = PublicPage.objects.get(token=row.token)
                return _row(row)
            row = PublicPage.objects.create(
                token=secrets.token_urlsafe(TOKEN_BYTES), user_id=who.user_id,
                org_id=who.org_id, rel=rel, title=title, created_at=time.time(),
                role=role_for(rel, role), public=True)
        return _row(row)

    def stop(self, who, rel: str) -> bool:
        """Take this page down. True if it was public and now is not.

        The row and its token stay, so the link is the same one if the page is
        made public again; until then it lets nobody in who is not the owner or
        a person the page is shared with.
        """
        from .models import PublicPage

        with self._lock:
            done = PublicPage.objects.filter(user_id=who.user_id, org_id=who.org_id,
                                             rel=str(rel or ""), public=True
                                             ).update(public=False)
        return bool(done)

    def stop_token(self, who, token: str) -> bool:
        """The same, named by the token rather than by the path.

        This is what the list of public pages presses, because a row there is a
        share and not a place in the workspace. Both ids are in the WHERE
        clause even though the token alone is unique, so a token belonging to
        somebody else is "no such page" rather than one person taking another
        person's page down.
        """
        from .models import PublicPage

        token = clean_token(token)
        if not token:
            return False
        with self._lock:
            done = PublicPage.objects.filter(token=token, user_id=who.user_id,
                                             org_id=who.org_id, public=True
                                             ).update(public=False)
        return bool(done)

    def mine(self, who, limit: int = LIST_MAX) -> list[dict]:
        """Every page this person has public, newest first."""
        from .models import PublicPage

        _follow(force=False)
        with self._lock:
            rows = list(PublicPage.objects
                        .filter(user_id=who.user_id, org_id=who.org_id, public=True)
                        .order_by("-created_at", "token")
                        [:max(1, min(int(limit or LIST_MAX), LIST_MAX))])
        return [_row(row) for row in rows]

    # -- the visitor's side, which has no identity to scope by --------------

    def find(self, token: str) -> dict | None:
        """The page a token names, for somebody who is not signed in.

        Deliberately unscoped: a visitor is nobody, and the token is the whole
        of the credential. It is the only method here that does not take an
        identity, and every caller of it serves one page and never a listing.
        """
        from .models import PublicPage

        token = clean_token(token)
        if not token:
            return None
        with self._lock:
            row = PublicPage.objects.filter(token=token, public=True).first()
        return _read_at(_row(row)) if row else None

    def opened(self, token: str) -> dict | None:
        """The page a link names, public or not, for deciding who it lets in.

        Unscoped like `find`, and never served on its own: the caller serves a
        page that is not public only to its owner and to the people it is
        shared with, and refuses everybody else.
        """
        from .models import PublicPage

        token = clean_token(token)
        if not token:
            return None
        with self._lock:
            row = PublicPage.objects.filter(token=token).first()
        return _read_at(_row(row)) if row else None


# --- sharing one page with one person ----------------------------------------
#
# Petar, 24 September 2026 (fr_edecde0ad6e6): "The way it would work is that I
# invite a specific person with a specific email. If that person doesn't have
# an account, he receives an email saying he needs to register. They can
# register, and when they go to the website, they would see the thing I have
# shared with them. That would be like the guest account: just a list of the
# things that have been shared with them, and then they can use the Ask AI
# active feature... If they have an account, they're just notified that there
# is a new thing that's been shared with them."
#
# One row per page per address (`rouh.models.PageGuest`). The owner's side is
# scoped to the owner like every other method here. The reader's side is found
# by the token and then held to the person signed in: a row answers only the
# account whose address it names, so a forwarded link is a link to a sign-in
# page and nothing more. What they may do is the row's `role`, the same two
# words a public link has. The letters and the pages are `rouh/web/guests.py`.

#: The longest address taken. RFC 5321's own limit.
EMAIL_MAX = 254

#: How many people one page is shared with, at most.
PEOPLE_MAX = 200

_EMAIL = re.compile(r"[^@\s<>\"',;]+@[^@\s<>\"',;]+\.[^@\s<>\"',;.]{2,}")


def clean_email(raw) -> str:
    """An address as it is kept - trimmed, lower case - or empty if it is not one."""
    said = str(raw or "").strip().lower()
    if not said or len(said) > EMAIL_MAX or not _EMAIL.fullmatch(said):
        return ""
    return said


def _person(row) -> dict:
    return {
        "token": row.token,
        "rel": row.rel,
        "title": row.title or "",
        "email": row.email,
        "role": role_of(row.role),
        "joined": bool(row.guest_id),
        "mailed": bool(row.mailed_at),
        "mail_error": row.mail_error or "",
        "via": getattr(row, "via", "") or "",
        "pending": getattr(row, "pending", "") or "",
        "granted_by": getattr(row, "granted_by", "") or "",
        "created_at": row.created_at,
        "owner_id": row.user_id,
        "org_id": row.org_id,
        "path": "/shared/" + row.token,
    }


def decider_refusal(who, email: str) -> str:
    """Why this address may not decide for the owner, or "": only one of their trusted
    contacts, switched on, ever decides (DELEGATION.md)."""
    from . import trusted

    found = trusted.TrustStore().trusted_for(str(who.user_id), str(who.org_id),
                                             clean_email(email))
    if found is None or getattr(found, "implicit", False) or not found.trusted:
        return ("Only somebody on your Trusted contacts, switched on, can decide for you. "
                f"{clean_email(email) or 'That address'} can be let in to read or edit it.")
    return ""


class Guests:
    """Which pages are shared with which people, and what each may do."""

    def __init__(self) -> None:
        self._lock = threading.Lock()

    # -- the owner's side, every query scoped to them ----------------------

    def people(self, who, rel: str) -> list[dict]:
        """Everybody this page is shared with, oldest first."""
        from .models import PageGuest

        _follow()
        with self._lock:
            rows = list(PageGuest.objects
                        .filter(user_id=who.user_id, org_id=who.org_id, rel=str(rel or ""))
                        .order_by("created_at", "token")[:PEOPLE_MAX])
        return [_person(row) for row in rows]

    def everyone(self, who, limit: int = LIST_MAX) -> list[dict]:
        """Everything this person has shared with anybody by email, oldest first:
        pages and tasks, each with the address and what they may do."""
        from .models import PageGuest

        _follow(force=False)
        with self._lock:
            rows = list(PageGuest.objects
                        .filter(user_id=who.user_id, org_id=who.org_id)
                        .order_by("created_at", "token")
                        [:max(1, min(int(limit or LIST_MAX), LIST_MAX))])
        return [_person(row) for row in rows]

    def invite(self, who, rel: str, title: str, email: str, role: str,
               guest_id: str = "", via: str = "", *, pending: str | None = None,
               granted_by: str | None = None) -> tuple[dict, bool]:
        """Share this page with this address. Returns the row and whether it is
        new: asking again changes what they may do and keeps their link.

        `via` is who keeps it (`PageGuest.via`): "" when a person chose it, which
        asking again always is, so a share a tick kept becomes the person's own.
        Decide is only ever for one of the owner's trusted contacts, switched on
        (`decider_refusal`): anybody else is refused with the reason, and nothing
        changes. `pending` is a promise the owner approved and `granted_by` who
        gave it ("owner", or "rouh" keeping a promise), left as they are when None."""
        from . import pageplaces
        from .models import PageGuest

        rel = str(rel or "")
        role = role_for(rel, role, person=True)
        if role == DECIDE:
            why = decider_refusal(who, email)
            if why:
                raise ValueError(why)
        extra = {}
        if pending is not None:
            extra["pending"] = " ".join(str(pending or "").split())[:600]
        if granted_by is not None:
            extra["granted_by"] = str(granted_by or "")[:20]
        _follow()
        pageplaces.remember(rel)
        with self._lock:
            row = PageGuest.objects.filter(user_id=who.user_id, org_id=who.org_id, rel=rel,
                                           email=email).first()
            if row is not None:
                PageGuest.objects.filter(token=row.token, user_id=who.user_id,
                                         org_id=who.org_id).update(
                    role=role, title=(title or row.title)[:200],
                    guest_id=row.guest_id or guest_id, via=via, **extra)
                return _person(PageGuest.objects.get(token=row.token)), False
            if PageGuest.objects.filter(user_id=who.user_id, org_id=who.org_id,
                                        rel=rel).count() >= PEOPLE_MAX:
                raise ValueError(f"This page is already shared with {PEOPLE_MAX} people.")
            row = PageGuest.objects.create(
                token=secrets.token_urlsafe(TOKEN_BYTES), user_id=who.user_id,
                org_id=who.org_id, rel=rel, title=(title or "")[:200], email=email,
                role=role, guest_id=guest_id, created_at=time.time(), via=via, **extra)
        return _person(row), True

    def with_addresses(self, who, emails) -> list[dict]:
        """What this person shared with any of these addresses, pages and tasks alike."""
        from .models import PageGuest

        emails = sorted({clean_email(e) for e in emails or ()} - {""})
        if not emails:
            return []
        _follow(force=False)
        with self._lock:
            rows = list(PageGuest.objects
                        .filter(user_id=who.user_id, org_id=who.org_id, email__in=emails)
                        .order_by("created_at", "token")[:LIST_MAX])
        return [_person(row) for row in rows]

    def remove(self, who, token: str) -> bool:
        """Stop sharing one page with one person. Their link stops at once."""
        from .models import PageGuest

        token = clean_token(token)
        if not token:
            return False
        with self._lock:
            done, _ = PageGuest.objects.filter(token=token, user_id=who.user_id,
                                               org_id=who.org_id).delete()
        return bool(done)

    def mailed(self, token: str, error: str = "") -> None:
        """Write down that the letter went, or why it did not."""
        from .models import PageGuest

        PageGuest.objects.filter(token=token).update(
            mailed_at=None if error else time.time(), mail_error=(error or "")[:300])

    # -- the reader's side: found by token, held to the person signed in ---

    def find(self, token: str) -> dict | None:
        """The share a token names, for the invitation and for the reader.

        Not scoped by the owner, because the reader is not the owner. Every
        caller holds the answer to the person signed in (`belongs_to`) before
        it serves anything, and the invitation page shows only the address.
        """
        from .models import PageGuest

        token = clean_token(token)
        if not token:
            return None
        with self._lock:
            row = PageGuest.objects.filter(token=token).first()
        return _read_at(_person(row)) if row else None

    @staticmethod
    def belongs_to(share: dict | None, user) -> bool:
        """Whether this share is for the account signed in."""
        if not share or user is None or not getattr(user, "is_authenticated", False):
            return False
        email = clean_email(getattr(user, "email", ""))
        return bool(email) and email == share.get("email")

    def held_by(self, owner_id: str, org_id: str, rel: str, user) -> dict | None:
        """This owner's share of this page with the account signed in, if any.

        What a page's own link (`/p/<token>`) asks when the page is not public:
        whether the person who opened it is one of the people it is shared
        with, so it can take them to their own reader's page.
        """
        from .models import PageGuest

        email = clean_email(getattr(user, "email", ""))
        if not email or not getattr(user, "is_authenticated", False):
            return None
        with self._lock:
            row = PageGuest.objects.filter(user_id=str(owner_id), org_id=str(org_id),
                                           rel=str(rel or ""), email=email).first()
        return _person(row) if row else None

    def for_person(self, user) -> list[dict]:
        """Every page shared with this account's address, newest first."""
        from .models import PageGuest

        email = clean_email(getattr(user, "email", ""))
        if not email:
            return []
        _follow(force=False)
        with self._lock:
            rows = list(PageGuest.objects.filter(email=email).order_by("-created_at")[:500])
        return [_person(row) for row in rows]

    def claim(self, email: str, guest_id: str) -> int:
        """Say that every page shared with this address has its account now."""
        from .models import PageGuest

        email = clean_email(email)
        if not email:
            return 0
        with self._lock:
            return PageGuest.objects.filter(email=email, guest_id="").update(
                guest_id=str(guest_id))
