"""A shared page stays shared when its folder moves.

On 29 September 2026 two moves of the workspace - the columns becoming
folders, then task 69 taking the logo rounds out of task 62 - left a contact's
three shared logo pages answering "This page is not there any more": a share
named its page by its path (`public_pages.rel`, `page_guests.rel`), so did the
page's comments (`page_comments.rel`), Ask AI's threads, its history and its
options (`doc` in `askai_threads`, `askai_edits`, `page_options`), and nothing
changed any of them when a folder moved (workspace task 69 has the
note).

A path is only where a page is now. What a page *is* is the object it sits in:
the nearest folder above it with a `.object.json`, whose id a move carries
along, whether Rouh moved it (`objecttree.move`), a job did it with `git mv`,
or a migration of the whole tree did. So every path any of those rows names is
written down once with that id and where the page is inside the object's
folder (`models.PagePlace`), and a path that has stopped being that page is
found again at the object's new place.

Two ways it is put right, and both keep everything but the path:

- **As it moves.** `objecttree.move` knows exactly where every folder went, and
  hands that here (`moved`), so every row under the old folder names the new
  one before the move has even answered.
- **When it is next asked about.** A move nobody told Rouh about - a job's
  `git mv`, a deploy - is found by `where`, which a share's reader asks before
  it serves anything, and by `follow`, which the owner's Share panel, the
  comments, Rouh's start and every move ask. The rows are then moved over
  together (`_repoint`, one transaction).
- **Out of git, when the object cannot say.** A page in a subtask folder with
  no `.object.json` of its own is known by its task's id and the subtask's
  folder name, and when a job's `git mv` takes that subtask to another task
  the id has nothing to find. The workspace's own history does: every move is
  a rename in a commit, so a path that is gone is followed along git's renames
  to where the file is now (`_trail`). On 1 October 2026 that was nine pages'
  Ask AI threads and edits, left naming folders that moved before any of this
  existed, or that moved without an id (62-19 into task 75).

A move Rouh makes writes down what each page is at its new path afresh
(`identity`), never a copy of what the old path said: a subtask with no
`.object.json` is known by the task it is in, and that changes when it moves.
Until 1 October 2026 the copy was kept, so the next look at the page found
it "a different page" and refused its shares, and the people it was shared
with lost the page and its comments.

**Moving never widens anything.** Only the path changes: the token, the person
a share is for, what they may do and whose it is stay exactly as they were. A
path that now holds a *different* page - its folder moved away and another
object took its place - is never served for the old share (`where` answers
None), and a page whose object is in two places at once is left alone rather
than guessed at.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path

log = logging.getLogger("rouh.pageplaces")

#: The workspace this install serves pages from (`config.assistant_repo`),
#: set once by the runtime (`use`). Every function also takes it outright.
ROOT = ""

#: How often `follow` looks over every path when nobody forces it.
FOLLOW_EVERY = 30.0

_lock = threading.Lock()
_last_follow = 0.0

#: git's renames in each workspace, by the commit they were read at (`_trail`).
_trails: dict[str, tuple[str, dict[str, str]]] = {}


def use(root) -> None:
    """Say which workspace pages are served from."""
    global ROOT
    ROOT = str(root or "")


def _root(root=None) -> Path | None:
    got = str(root or ROOT or "")
    return Path(got) if got and os.path.isdir(got) else None


def _clean(rel: str) -> str:
    parts = [p for p in str(rel or "").split("/") if p and p != "."]
    return "" if ".." in parts else "/".join(parts)


def identity(root, rel: str) -> tuple[str, str] | None:
    """(object id, the page's path inside that object's folder) for a page on disk.

    None when the page is not there, or no folder above it is an object.
    """
    from . import objecttree

    base = _root(root)
    rel = _clean(rel)
    if base is None or not rel or not (base / rel).is_file():
        return None
    parts = rel.split("/")
    for cut in range(len(parts) - 1, 0, -1):
        folder = base.joinpath(*parts[:cut])
        try:
            side = objecttree.read_sidecar(folder, base)
        except (objecttree.Refused, OSError):
            side = None
        if side and side.get("id"):
            return str(side["id"]), "/".join(parts[cut:])
    return None


def remember(rel: str, root=None) -> bool:
    """Write down which page this path is, if it is one and was not written already.

    Never written over: a path that already names one object keeps naming it,
    so a page that moved away is still looked for at its object's new place
    even once something else is at the old path.
    """
    from .models import PagePlace

    rel = _clean(rel)
    found = identity(root, rel)
    if found is None:
        return False
    _, made = PagePlace.objects.get_or_create(
        rel=rel, defaults={"object_id": found[0], "sub": found[1], "seen_at": time.time()})
    return made


def opened(rel: str, root=None) -> None:
    """Its owner has this page open on the canvas now. Never raises.

    What lets the Control Room say "You haven't opened it yet" about a page
    Rouh made, and offer Read for it, only when that is so
    (`controlroom._results`). A path that is not a page inside an object's
    folder is not written down, like everywhere else here.
    """
    from .models import PagePlace

    rel = _clean(rel)
    try:
        remember(rel, root)
        PagePlace.objects.filter(rel=rel).update(opened_at=time.time())
    except Exception:  # noqa: BLE001 - the page is served either way
        log.exception("could not write down that %s was opened", rel)


def _folders(base: Path) -> dict[str, list[str]]:
    """Where every object is now: its id and the folders that carry it."""
    from . import objecttree

    out: dict[str, list[str]] = {}
    try:
        for node in objecttree.read_tree(base):
            out.setdefault(str(node.id), []).append(node.rel)
    except (objecttree.Refused, OSError):
        log.exception("the workspace's objects could not be read to find a moved page")
    return out


def _trail(base: Path) -> dict[str, str]:
    """Every rename git has recorded in the workspace, oldest first: old path -> new.

    Paths are the workspace's own (`--relative`), whether the workspace is a
    repository of its own or a folder inside one, as it is on the server. {}
    when it is not in git or git will not answer.
    """
    import subprocess

    try:
        head = subprocess.run(["git", "-C", str(base), "rev-parse", "HEAD"],
                              capture_output=True, text=True, timeout=30).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return {}
    if not head:
        return {}
    known = _trails.get(str(base))
    if known is not None and known[0] == head:
        return known[1]
    try:
        done = subprocess.run(
            ["git", "-C", str(base), "log", "--reverse", "--relative", "--format=",
             "--name-status", "-M", "--diff-filter=R", "-z", "--", "."],
            capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return {}
    if done.returncode != 0:
        return {}
    out: dict[str, str] = {}
    words = [w.strip("\n") for w in done.stdout.decode("utf-8", "replace").split("\0")]
    at = 0
    while at < len(words):
        if words[at].startswith("R") and at + 2 < len(words):
            out[_clean(words[at + 1])] = _clean(words[at + 2])
            at += 3
        else:
            at += 1
    _trails[str(base)] = (head, out)
    return out


def renamed_to(rel: str, root=None, *, trail: dict | None = None) -> str | None:
    """Where git says the file at `rel` went, when it is not at `rel` any more.

    Followed rename by rename to the last one, and only an answer when a file
    is there now. None when the page is still where it was, git never moved it,
    or wherever it went is gone too.
    """
    base = _root(root)
    rel = _clean(rel)
    if base is None or not rel or (base / rel).exists():
        return None
    trail = trail if trail is not None else _trail(base)
    now, seen = rel, {rel}
    while now in trail and trail[now] not in seen:
        now = trail[now]
        seen.add(now)
    return now if now != rel and (base / now).is_file() else None


def where(rel: str, root=None, *, tree: dict | None = None,
          trail: dict | None = None) -> str | None:
    """Where the page this path named is now.

    - the same path, when the page is still there, or nothing is known about it;
    - its new path, when its object has moved and the page is in it;
    - where git's renames took it, when it is gone and its object cannot say
      (`renamed_to`): a subtask with no `.object.json` moved by a job, or a
      page moved before its path was ever written down;
    - the same path, when it is gone and cannot be found (the caller's "not
      there any more");
    - None when the path now holds a different page than the one it named,
      which must never be served in its place.
    """
    from .models import PagePlace

    base = _root(root)
    rel = _clean(rel)
    if base is None or not rel:
        return rel
    place = PagePlace.objects.filter(rel=rel).values("object_id", "sub").first()
    here = identity(base, rel)
    if place is None:
        if here is not None:
            remember(rel, base)
            return rel
        return renamed_to(rel, base, trail=trail) or rel
    known = (place["object_id"], place["sub"])
    if here == known:
        return rel
    tree = tree if tree is not None else _folders(base)
    folders = tree.get(place["object_id"]) or []
    if len(folders) == 1:
        now = f"{folders[0]}/{place['sub']}"
        if identity(base, now) == known:
            return now
    elif len(folders) > 1:
        log.warning("%s is in %d folders at once, so %s is not followed", place["object_id"],
                    len(folders), rel)
    if here is None:
        return renamed_to(rel, base, trail=trail) or rel
    return None


def _referenced() -> set[str]:
    """Every path a share, a comment or a page's Ask AI rows name."""
    from .models import (AskEdit, AskThread, PageComment, PageDefinition, PageGuest,
                         PageHighlight, PageOption, PagePlace, PageState, PublicPage)

    rels: set[str] = set()
    for model, field in ((PublicPage, "rel"), (PageGuest, "rel"), (PageComment, "rel"),
                         (PageHighlight, "rel"), (PageDefinition, "rel"), (PageState, "rel"),
                         (AskThread, "doc"),
                         (AskEdit, "doc"), (PageOption, "doc")):
        rels.update(model.objects.values_list(field, flat=True).distinct())
    # A page its owner has opened, so the time they opened it follows the
    # page when its folder moves, like a share does (`opened`).
    rels.update(PagePlace.objects.filter(opened_at__isnull=False)
                .values_list("rel", flat=True))
    # A shared task names its folder and not a page, and follows its own
    # moves (`rouh/taskshare.py`).
    return {r for r in rels if r and not r.startswith("_task/")}


def _names(rel: str) -> bool:
    """Whether any share, comment or Ask AI row names this path."""
    from .models import (AskEdit, AskThread, PageComment, PageDefinition, PageGuest,
                         PageHighlight, PageOption, PageState, PublicPage)

    return any(model.objects.filter(**{field: rel}).exists()
               for model, field in ((PublicPage, "rel"), (PageGuest, "rel"),
                                    (PageComment, "rel"), (PageHighlight, "rel"),
                                    (PageDefinition, "rel"), (PageState, "rel"),
                                    (AskThread, "doc"),
                                    (AskEdit, "doc"), (PageOption, "doc")))


def _repoint(old: str, new: str, root=None) -> dict:
    """Every row that names `old` names `new` instead, in one transaction.

    Only the path. A share whose owner already has one at the new path (the
    same page shared again after it moved, before this ran) is left as it is:
    its reader still finds the page through `where`, and two rows are never
    squashed into one, which could change what somebody may do.

    What the new path is gets written down from what is there now
    (`identity`), not copied from what the old path said. A subtask with no
    `.object.json` is known by the task it is in and its own folder's name,
    and a move changes both, so a copy would say the page at the new path is
    some other page, and its shares would be refused from the next look on.
    """
    from django.db import transaction

    from .models import (AskEdit, AskThread, PageComment, PageDefinition, PageGuest,
                         PageHighlight, PageOption, PagePlace, PageState, PublicPage)

    found = identity(root, new)
    counts: dict[str, int] = {}
    kept = 0
    with transaction.atomic():
        # Asked before anything moves: rows of some other page already at the
        # new path are why its place is not written over.
        named_already = _names(new)
        for row in PublicPage.objects.select_for_update().filter(rel=old):
            if PublicPage.objects.filter(user_id=row.user_id, rel=new).exists():
                kept += 1
                continue
            PublicPage.objects.filter(token=row.token).update(rel=new)
            counts["public_pages"] = counts.get("public_pages", 0) + 1
        for row in PageGuest.objects.select_for_update().filter(rel=old):
            if PageGuest.objects.filter(user_id=row.user_id, rel=new, email=row.email).exists():
                kept += 1
                continue
            PageGuest.objects.filter(token=row.token).update(rel=new)
            counts["page_guests"] = counts.get("page_guests", 0) + 1
        counts["page_comments"] = PageComment.objects.filter(rel=old).update(rel=new)
        counts["page_highlights"] = PageHighlight.objects.filter(rel=old).update(rel=new)
        counts["page_definitions"] = PageDefinition.objects.filter(rel=old).update(rel=new)
        # A person's settings on the page, unless they already have some at the new path.
        counts["page_states"] = PageState.objects.filter(rel=old).exclude(
            user_id__in=PageState.objects.filter(rel=new).values("user_id")).update(rel=new)
        counts["askai_threads"] = AskThread.objects.filter(doc=old).update(doc=new)
        counts["askai_edits"] = AskEdit.objects.filter(doc=old).update(doc=new)
        counts["page_options"] = PageOption.objects.filter(doc=old).update(doc=new)
        place = PagePlace.objects.select_for_update().filter(rel=old).first()
        if place is not None or found is not None:
            obj, sub = found if found is not None else (place.object_id, place.sub)
            opened_at = place.opened_at if place is not None else None
            have = PagePlace.objects.select_for_update().filter(rel=new).first()
            if have is None:
                PagePlace.objects.create(rel=new, object_id=obj, sub=sub, seen_at=time.time(),
                                         opened_at=opened_at)
            elif (have.object_id, have.sub) != (obj, sub):
                if named_already:
                    log.warning("%s already names %s/%s, which rows still name, so the "
                                "page moved there from %s is not written over it", new,
                                have.object_id, have.sub, old)
                else:
                    have.object_id, have.sub, have.seen_at = obj, sub, time.time()
                    if opened_at and (have.opened_at or 0) < opened_at:
                        have.opened_at = opened_at
                    have.save()
            elif opened_at and (have.opened_at or 0) < opened_at:
                have.opened_at = opened_at
                have.save(update_fields=["opened_at"])
            if place is not None and not kept:
                place.delete()
    counts = {k: v for k, v in counts.items() if v}
    if counts or kept:
        log.info("the page at %s moved to %s: moved %s%s", old, new, counts or "nothing",
                 f", and left {kept} share(s) already made again there" if kept else "")
    return counts


def follow(root=None, *, force: bool = False) -> list[tuple[str, str]]:
    """Find every named page that has moved, and point its rows at where it is now.

    Paths still where they were are written down on the way (`remember`), so a
    page shared before any of this existed is followed from its next move on.
    At most every `FOLLOW_EVERY` seconds unless forced. Never raises.
    """
    global _last_follow
    base = _root(root)
    if base is None:
        return []
    now = time.time()
    if not force and now - _last_follow < FOLLOW_EVERY:
        return []
    moved: list[tuple[str, str]] = []
    with _lock:
        _last_follow = now
        try:
            tree: dict | None = None
            trail: dict | None = None
            for rel in sorted(_referenced()):
                if (base / rel).is_file() and remember_or_same(rel, base):
                    continue
                if tree is None:
                    tree = _folders(base)
                if trail is None and not (base / rel).exists():
                    trail = _trail(base)
                new = where(rel, base, tree=tree, trail=trail)
                if new and new != rel:
                    _repoint(rel, new, base)
                    moved.append((rel, new))
        except Exception:  # noqa: BLE001 - a page that cannot be followed is only a 404
            log.exception("following moved pages stumbled")
    return moved


def remember_or_same(rel: str, base: Path) -> bool:
    """True when the page at `rel` is the one the path has always named."""
    from .models import PagePlace

    place = PagePlace.objects.filter(rel=rel).values("object_id", "sub").first()
    if place is None:
        remember(rel, base)
        return True
    return identity(base, rel) == (place["object_id"], place["sub"])


def moved(root, was: str, now_of) -> None:
    """A folder was moved by Rouh: every row under it follows, and everything else is checked.

    `now_of` maps a path under `was` to where it is now, which `objecttree.move`
    knows exactly, renumbered steps and all.
    """
    from django.db import transaction

    from .models import PagePlace

    base = _root(root)
    if base is None:
        return
    was = _clean(was)
    try:
        # Every path written down under it, not only those a row names: a
        # place left at the old path would send a new page made there to this
        # one's object, wherever it went.
        under = set(PagePlace.objects.filter(rel__startswith=was + "/")
                    .values_list("rel", flat=True))
        with transaction.atomic():
            for rel in sorted(_referenced() | under):
                if rel.startswith(was + "/"):
                    new = _clean(now_of(rel))
                    if new and new != rel and (base / new).is_file():
                        _repoint(rel, new, base)
    except Exception:  # noqa: BLE001 - the move itself has happened either way
        # Nothing half done: the rows are all where they were, and `follow`
        # below, and every look after it, finds them by the object or by git.
        log.exception("the pages under %s could not be followed to their new place", was)
    follow(base, force=True)


def reading(rel: str, root=None) -> str | None:
    """The path to serve for a share that names `rel`, its rows moved over if it moved.

    What every reader of a share asks before it serves a page: the same path,
    the page's new one, or None when the path now holds somebody else's page.
    """
    try:
        new = where(rel, root)
    except Exception:  # noqa: BLE001 - the path as it was is still the best answer
        log.exception("could not tell where %s is now", rel)
        return rel
    if new and new != rel:
        try:
            _repoint(_clean(rel), new, root)
        except Exception:  # noqa: BLE001 - served from where it is either way
            log.exception("could not move the rows of %s over to %s", rel, new)
    return new
