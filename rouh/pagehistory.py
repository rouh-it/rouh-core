"""A page's history, and the changes kept as options over it.

Petar, 24 September 2026 (fr_b91369ea7ba2): "whenever someone makes a change
on the website, I want a history of every change, including who made it and
when. I want to be able to click on each entry and see how the page looked at
that moment... for every change, I have to decide whether I want to keep it in
the options. That means if I have a red button and make a change to make it
orange, I decide whether this change should stay like this or have an options
pop-up so other people can switch between red and orange... I'd rather have it
as a layer on top so it doesn't distort the original HTML... I think the
default option should be able to be marked by anyone."

The history
-----------

A page changes in two ways, and the history is both of them, newest first:

- **Ask AI changed it** (`askai.apply_edits`), for the owner, for a person the
  page was shared with, or for a visitor to a link that may change it. Every
  such change is kept whole (`AskEdit`), so it says who asked, when, what it
  did, and exactly how the page read afterwards. One change is one `edit_page`
  call: one line in the conversation, with one Undo on it. A change put back
  is a line of its own, at the time it was put back. Somebody picking which of
  a page's options everybody sees is a change too (`choose`), and is listed.
- **A new version was saved in git**: a job built or rebuilt the page, or it
  was changed by hand. Each commit that changed the page is a line, with its
  author and its subject, read out of the workspace's own history. Rouh's own
  commits are left out, because they are Rouh saving the Ask AI changes above
  (`rouh/saving.py`), which are listed already, with the person who asked.

Every line can be opened, and the page is then served as it was at that moment
(`version_source`), in the same frame, read only, with a bar over it that says
which moment it is and a way back to the page as it is now.

The history is the owner's, for now. An old version can show what the owner
took out of the page before sharing it, so a person the page is shared with,
and a visitor to its link, are not given it (`rouh/web/guests.py` never asks).

The options
-----------

A change Ask AI made can be kept as an option: the page on disk keeps the
change, and the version before it is kept beside the page (`PageOption`), not
in it. Nothing is written into the page to mark it: the switch is drawn over
the page by the Ask AI layer (`askai.js`, "The options"), which is handed the
options as the page is sent (`for_layer`). Each option is the elements the
change touched (`parts_of`), whole, in every version; the version on disk is
the default, which is what everybody sees when the page opens.

- **Anybody who can read the page may make another version the default**, and
  the last one to do so is the one that stands (`choose`). That writes the
  page, like any change, so it is saved to main and is a line in the history.
- **Somebody who may change the page may make a version final** (`decide`):
  it becomes the default and the choice is closed, and the page says so to
  everybody who reads it, with who decided and when. The other versions stay,
  to be looked at, and the choice can be opened again (`reopen`). Petar, 29
  September 2026 (fr_a383dc8329c0): "coding an option as final between all
  those other options."
- **Switching without making it the default** is the viewer's alone: the
  layer swaps the element in the page on the screen and nothing is sent.
- **A change to an element that is already an option** carries the option
  with it (`rebase`), and kept as an option itself it becomes another version
  of the same one rather than a second switch over the first (`keep`).
- **Every version says why it exists.** Petar, 24 September 2026
  (fr_662a64715b9f): "each option for how something should look or what we
  should choose needs to have reasoning somewhere around it so that we know
  why somebody picked that specific option to exist." A change Ask AI made
  carries the reason the model gave for it (`askai.EDIT_TOOL`), the version
  before it says what it was before, and anybody who may change the page can
  write or rewrite the reason of any version (`set_reason`).
- **Ask AI may offer one more version.** Its pass over a page's comments
  (`rouh/commentpass.py`), where people are weighing the versions of a part
  in a thread, may add a version of its own with its reason (`propose`): "If
  one person suggested A, another person suggested B, and we comment on it,
  the AI can suggest C." It is offered beside the others and never made the
  default; the page is not written.

What is not known yet, and so is not decided here: whether a person the page
is shared with should see its history, and whether one Ask AI request that made
several changes should be one line or several. It is several today, one per
`edit_page` call, because each has its own Undo.
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
import time
from html import escape as html_escape, unescape as html_unescape
from pathlib import Path

from . import gitutil, pages

log = logging.getLogger("rouh.pagehistory")

#: The largest element a change may touch and still be kept as an option. The
#: element travels whole, in every version, into every page it is served with.
PART_MAX = 100_000

#: Elements too wide to swap: a change they are the smallest holder of reaches
#: across the page rather than changing one part of it.
TOO_WIDE = frozenset({"html", "head", "body"})

#: How many lines the history lists, of each kind.
HISTORY_MAX = 200
GIT_MAX = 80

#: Who a visitor to a public link that may change the page is, in the history.
LINK_NAME = "Someone with the link"

#: What the version before a kept change is called, and why it is there.
AS_IT_WAS = "As it was"
AS_IT_WAS_WHY = "How the page had it before “{change}”."

#: The longest reason a version keeps, and the longest name.
REASON_MAX = 400
LABEL_MAX = 120

#: The most versions one part of a page may have. Past this an option is a
#: list to scroll rather than a choice.
VERSIONS_MAX = 8

#: Who Ask AI is, in a version it offered (`propose`), and what it is called.
AI_BY = "ai"
AI_NAME = "Ask AI"

#: What a version offered by the model may not hold. The version is put into
#: the page on the screen when somebody switches to it, and into the file when
#: somebody makes it the default, so it is held to markup: nothing that runs,
#: loads or frames anything.
_UNSAFE = re.compile(r"<\s*/?\s*(script|iframe|frame|object|embed|link|meta|base|form)\b"
                     r"|\son[a-z]+\s*=|javascript:|vbscript:|data:text/html|srcdoc\s*=",
                     re.I)

#: The author of Rouh's own commits (`saving.Saver.save_once`).
ROUH_AUTHOR = "Rouh"

_SHA = re.compile(r"[0-9a-f]{40}")
_VERSION = re.compile(r"(?P<kind>[ebu])(?P<id>[0-9]{1,18})|g(?P<sha>[0-9a-f]{40})")


class Refused(ValueError):
    """Something asked of the history or the options that was not done, and
    the sentence that says why."""


# --------------------------------------------------------------------------
# What a change touched
# --------------------------------------------------------------------------


def track(hunks: list[tuple[int, int, int]], at: int, find: str, put: str
          ) -> list[tuple[int, int, int]]:
    """Where a page has been changed so far, after one more edit.

    ``hunks`` are (start, end, how much longer) in the page as it is now, in
    order and apart. The edit put ``put`` in place of ``find`` at ``at``. What
    the two begin and end with alike is not a change, so an edit of
    ``<section>`` to ``<section class="x">`` changed the section, not the
    element around it. A hunk the edit touches becomes one with it.
    """
    same = 0
    most = min(len(find), len(put))
    while same < most and find[same] == put[same]:
        same += 1
    tail = 0
    while tail < most - same and find[-1 - tail] == put[-1 - tail]:
        tail += 1
    at += same
    found = len(find) - same - tail
    put = len(put) - same - tail
    grew = put - found
    lo, hi, total = at, at + put, grew
    kept: list[tuple[int, int, int]] = []
    for start, end, longer in hunks:
        if end < at:
            kept.append((start, end, longer))
        elif start > at + found:
            kept.append((start + grew, end + grew, longer))
        else:
            lo = min(lo, start)
            hi = max(hi, end + grew if end > at + found else at + put)
            total += longer
    kept.append((lo, hi, total))
    kept.sort()
    return kept


def _before_at(hunks, where: int) -> int:
    """Where a place in the changed page was before the change."""
    return where - sum(longer for _, end, longer in hunks if end <= where)


def parts_of(before: str, after: str, hunks) -> list[dict]:
    """The elements a change touched, each whole, before and after it.

    The smallest element that holds each changed piece, and the outermost of
    those where one holds another, so a change to a button's colour is the
    button and a change to its colour and its words is still the button. Empty
    when a piece is held by nothing smaller than the page's head or body, or
    by an element too large to carry about: such a change reaches across the
    page, and there is nothing one switch could swap.
    """
    if not hunks:
        return []
    spans = pages.element_spans(after)
    held = []
    for start, end, _ in hunks:
        found = pages.enclosing(spans, start, end)
        if found is None:
            return []
        held.append(found)
    outer: list[tuple[int, int, str]] = []
    for one in sorted(set(held), key=lambda s: (s[0], -s[1])):
        if outer and outer[-1][0] <= one[0] and one[1] <= outer[-1][1]:
            continue
        outer.append(one)
    parts = []
    for start, end, name in outer:
        if name in TOO_WIDE or end - start > PART_MAX:
            return []
        was = before[_before_at(hunks, start):_before_at(hunks, end)]
        now = after[start:end]
        if was != now:
            parts.append({"tag": name, "at": start, "before": was, "after": now})
    return parts


def _load(raw) -> list:
    try:
        got = json.loads(raw or "[]")
    except ValueError:
        return []
    return got if isinstance(got, list) else []


# --------------------------------------------------------------------------
# Options, carried over every change
# --------------------------------------------------------------------------


def _live(org_id: str, doc: str):
    from .models import PageOption

    return list(PageOption.objects.filter(org_id=org_id, doc=doc, removed_at__isnull=True)
                .order_by("id"))


def rebase(org_id: str, doc: str, parts: list[dict], pairs, source: str, *,
           skip: int = 0) -> None:
    """Carry the page's options over a change just written to it.

    An option whose default is still in the page is left alone. One the change
    touched is moved with it: the version on the page becomes what the change
    made of it, and the change's own edits are made to the other versions too
    wherever they fit, so a button's new words reach its old colour as well.
    One the change cut across is left as it was, and is no longer on the page
    (`for_layer` leaves it out; the history says so).
    """
    for row in _live(org_id, doc):
        if row.id == skip:
            continue
        mine = _load(row.parts)
        moved = False
        for part in mine:
            alts = part.get("alts") or []
            if not 0 <= row.chosen < len(alts):
                continue
            now = alts[row.chosen]
            if now in source:
                continue
            for change in parts:
                was, made = change["before"], change["after"]
                if now == was:
                    alts[row.chosen] = made
                    for n, alt in enumerate(alts):
                        if n == row.chosen:
                            continue
                        for find, put in pairs:
                            if find and alt.count(find) == 1:
                                alt = alt.replace(find, put, 1)
                        alts[n] = alt
                elif was and now.count(was) == 1:
                    for n, alt in enumerate(alts):
                        if alt.count(was) == 1:
                            alts[n] = alt.replace(was, made, 1)
                else:
                    continue
                moved = True
                break
        if moved:
            row.parts = json.dumps(mine)
            row.save(update_fields=["parts"])


def _meta(row) -> dict:
    return {"edit": int(row.id), "by": row.user_id, "at": row.created_at,
            "label": row.summary or "This change", "reason": row.reason or ""}


def keep(root, who, org_id: str, doc: str, edit_id, choice: str) -> dict:
    """Keep one change as final, or as an option beside the version before it.

    Kept as an option onto an element that is already one, it is another
    version of that option rather than a second switch over the first.
    """
    from . import askai
    from .models import AskEdit, PageOption

    if choice not in ("option", "final"):
        raise Refused("Keep it as an option, or as final.")
    wanted = _number(edit_id)
    page = askai.resolve(root, doc)
    with askai._EDIT_LOCK:
        row = AskEdit.objects.filter(id=wanted, page_org_id=org_id, doc=doc).first()
        if row is None:
            raise Refused("There is no such change.")
        if row.kind:
            raise Refused("That was somebody picking which option everybody sees, "
                          "not a change to keep.")
        if row.undone_at:
            raise Refused("That change was put back.")
        if row.keep == choice:
            return {"edit": row.id, "keep": row.keep}
        if row.keep == "option":
            raise Refused("That change is an option already. Stop offering it from the "
                          "options on the page.")
        if choice == "final":
            AskEdit.objects.filter(id=row.id).update(keep="final")
            return {"edit": row.id, "keep": "final"}
        parts = _load(row.parts)
        if not parts:
            raise Refused("That change reaches across too much of the page to be kept as "
                          "an option.")
        source = askai.read_source(page)
        if any(part["after"] not in source for part in parts):
            raise Refused("The page has changed there since, so that change can no longer "
                          "be kept as an option.")
        mine = _meta(row)
        into = _chain(org_id, doc, parts)
        if into is not None:
            option, at, earlier = into
            alts = _load(option.alts)
            kept = _load(option.parts)
            for n, part in enumerate(kept):
                part["alts"].insert(option.chosen, earlier if n == at
                                    else part["alts"][option.chosen])
            alts.insert(option.chosen, alts[option.chosen])
            alts[option.chosen + 1] = mine
            option.parts = json.dumps(kept)
            option.alts = json.dumps(alts)
            option.chosen += 1
            # The change is what everybody sees now, so whoever asked for it
            # is who made it the default.
            option.chosen_by = row.user_id
            option.chosen_at = row.created_at
            option.save(update_fields=["parts", "alts", "chosen", "chosen_by", "chosen_at"])
        else:
            PageOption.objects.create(
                org_id=org_id, doc=doc, edit_id=row.id,
                parts=json.dumps([{"tag": p["tag"], "alts": [p["before"], p["after"]]}
                                  for p in parts]),
                alts=json.dumps([{"edit": None, "by": "", "at": row.created_at,
                                  "label": AS_IT_WAS,
                                  "reason": AS_IT_WAS_WHY.format(
                                      change=mine["label"])[:REASON_MAX]}, mine]),
                chosen=1, created_by=who.user_id, created_at=time.time())
        AskEdit.objects.filter(id=row.id).update(keep="option")
    log.info("pagehistory: change %s to %s is kept as an option", row.id, doc)
    return {"edit": row.id, "keep": "option"}


def _chain(org_id: str, doc: str, parts: list[dict]):
    """The option a one-element change was made inside of, if there is one:
    (the option, which of its parts, that part as it was before the change)."""
    if len(parts) != 1:
        return None
    was, made = parts[0]["before"], parts[0]["after"]
    for option in reversed(_live(org_id, doc)):
        for n, part in enumerate(_load(option.parts)):
            alts = part.get("alts") or []
            if not 0 <= option.chosen < len(alts):
                continue
            now = alts[option.chosen]
            if now.count(made) == 1:
                return option, n, now.replace(made, was, 1)
    return None


def undone(org_id: str, doc: str, row) -> None:
    """A change was put back: the option it was kept as goes with it, and every
    other option is carried back over the page as it is again."""
    from .models import PageOption

    now = time.time()
    for option in _live(org_id, doc):
        if option.edit_id == row.id:
            PageOption.objects.filter(id=option.id).update(removed_at=now,
                                                           removed_by="undo")
            continue
        alts = _load(option.alts)
        if option.chosen < len(alts) and (alts[option.chosen] or {}).get("edit") == row.id \
                and option.chosen > 0:
            kept = _load(option.parts)
            for part in kept:
                del part["alts"][option.chosen]
            del alts[option.chosen]
            option.parts = json.dumps(kept)
            option.alts = json.dumps(alts)
            option.chosen -= 1
            # Nobody picked the version the page is back to; it is just there.
            option.chosen_by = ""
            option.chosen_at = None
            option.save(update_fields=["parts", "alts", "chosen", "chosen_by", "chosen_at"])
    back = [{"tag": p["tag"], "before": p["after"], "after": p["before"]}
            for p in _load(row.parts)]
    rebase(org_id, doc, back, [], row.before)


def choose(root, who, org_id: str, doc: str, option_id, index) -> dict:
    """Make one version of an option the one everybody sees.

    It is written into the page, the way any change is, and saved to main, and
    it is a line in the history under the name of whoever picked it.
    """
    from . import askai
    from .models import AskEdit, PageOption

    wanted = _number(option_id)
    pick = _number(index, -1)
    page = askai.resolve(root, doc)
    with askai._EDIT_LOCK:
        option = PageOption.objects.filter(id=wanted, org_id=org_id, doc=doc,
                                           removed_at__isnull=True).first()
        if option is None:
            raise Refused("Those options are not on this page any more.")
        alts = _load(option.alts)
        kept = _load(option.parts)
        if not 0 <= pick < len(alts):
            raise Refused("There is no such version.")
        if pick == option.chosen:
            return {"option": option.id, "chosen": pick, "changed": False}
        if option.final_at:
            raise Refused("That choice was made final. Open it again first to change it.")
        before = askai.read_source(page)
        after = before
        hunks: list[tuple[int, int, int]] = []
        pairs = []
        for part in kept:
            now, put = part["alts"][option.chosen], part["alts"][pick]
            if after.count(now) != 1:
                raise Refused("That part of the page has changed since, so its options "
                              "cannot be switched any more.")
            at = after.find(now)
            after = after[:at] + put + after[at + len(now):]
            hunks = track(hunks, at, now, put)
            pairs.append((now, put))
        askai._write_source(page, after)
        label = str((alts[pick] or {}).get("label") or "another version")
        made = parts_of(before, after, hunks)
        row = AskEdit.objects.create(
            user_id=who.user_id, org_id=who.org_id, page_org_id=org_id, doc=doc,
            kind="default", summary=f"Made “{label}” the default"[:300],
            before=before, after=after, parts=json.dumps(made), created_at=time.time())
        option.chosen = pick
        option.chosen_by = who.user_id
        option.chosen_at = row.created_at
        option.save(update_fields=["chosen", "chosen_by", "chosen_at"])
        rebase(org_id, doc, made, pairs, after, skip=option.id)
    log.info("pagehistory: option %s on %s now shows version %s by default", option.id, doc,
             pick)
    askai._saved_soon()
    return {"option": option.id, "chosen": pick, "changed": True, "edit": row.id}


#: The longest name a page is given by Rename.
TITLE_MAX = 200

_HEAD_OPEN = re.compile(r"<head(?:\s[^>]*)?>", re.IGNORECASE)


def retitle(root, who, doc: str, title: str) -> dict:
    """Give a page another name: the words in its ``<title>``, which is what
    its task's page, the canvas and the window call it (`pages.title_of`).

    Petar, 26 October 2026 (fr_0234d21daa0b), on the three dots of the page on
    a task's page: "Add rename to this context menu". Only the name changes:
    the file keeps its name, so every link to it still works. It is written
    the way any change to a page is, and is a line in its history with an Undo
    under the name of whoever renamed it, so the name before is never lost.
    """
    from . import askai
    from .models import AskEdit

    title = " ".join(str(title or "").split())[:TITLE_MAX]
    if not title:
        raise Refused("A name cannot be empty.")
    try:
        page = askai.resolve(root, doc)
    except askai.Unavailable as exc:
        raise Refused(str(exc)) from None
    put = html_escape(title)
    with askai._EDIT_LOCK:
        try:
            before = askai.read_source(page)
        except askai.EditRefused as exc:
            raise Refused(f"It could not be renamed: {exc}") from None
        found = pages._TITLE.search(before)
        if found:
            if " ".join(html_unescape(found.group(1)).split()) == title:
                return {"ok": True, "title": title, "changed": False}
            after = before[:found.start(1)] + put + before[found.end(1):]
        else:
            head = _HEAD_OPEN.search(before)
            if head is None:
                raise Refused("This page has no head to put a name in.")
            after = before[:head.end()] + f"<title>{put}</title>" + before[head.end():]
        askai._write_source(page, after)
        row = AskEdit.objects.create(
            user_id=who.user_id, org_id=who.org_id, page_org_id=who.org_id, doc=doc,
            summary=f"Renamed it “{title}”"[:300], before=before, after=after,
            created_at=time.time())
    log.info("pagehistory: %s renamed to %r", doc, title)
    askai._saved_soon()
    return {"ok": True, "title": title, "changed": True, "edit": row.id}


def decide(root, who, org_id: str, doc: str, option_id, index) -> dict:
    """Make one version final: the default, and the choice closed.

    Petar, 29 September 2026 (fr_a383dc8329c0): "How do you close open
    items? ... I think he might mean coding an option as final between all
    those other options." For somebody who may change the page. The version is
    made the default the way `choose` does, if it is not already, and the
    option is marked as decided, by whom and when. The other versions are
    kept, so it can be opened again (`reopen`), but nobody can change the
    default and Ask AI offers no more versions while it stands.
    """
    from .models import PageOption

    pick = _number(index, -1)
    done = choose(root, who, org_id, doc, option_id, pick)
    with _lock():
        PageOption.objects.filter(id=_number(option_id), org_id=org_id, doc=doc,
                                  removed_at__isnull=True
                                  ).update(final_at=time.time(), final_by=who.user_id)
    log.info("pagehistory: option %s on %s was made final at version %s", option_id, doc, pick)
    return {**done, "final": True}


def reopen(who, org_id: str, doc: str, option_id) -> dict:
    """Open a choice made final again: its versions can be picked between once more."""
    from .models import PageOption

    done = PageOption.objects.filter(id=_number(option_id), org_id=org_id, doc=doc,
                                     removed_at__isnull=True
                                     ).update(final_at=None, final_by="")
    if not done:
        raise Refused("Those options are not on this page any more.")
    log.info("pagehistory: option %s on %s was opened again by %s", option_id, doc,
             who.user_id)
    return {"option": _number(option_id), "final": False}


def remove(who, org_id: str, doc: str, option_id) -> dict:
    """Stop offering an option. The page keeps whichever version is its default."""
    from .models import PageOption

    done = PageOption.objects.filter(id=_number(option_id), org_id=org_id, doc=doc,
                                     removed_at__isnull=True
                                     ).update(removed_at=time.time(), removed_by=who.user_id)
    if not done:
        raise Refused("Those options are not on this page any more.")
    return {"option": _number(option_id), "removed": True}


def set_reason(who, org_id: str, doc: str, option_id, index, reason) -> dict:
    """Write why one version of an option exists, or change what it says.

    For somebody who may change the page. It is a sentence beside the version,
    not a change to the page, so it is not a line in the history.
    """
    from .models import PageOption

    words = " ".join(str(reason or "").split())[:REASON_MAX]
    pick = _number(index, -1)
    with _lock():
        option = PageOption.objects.filter(id=_number(option_id), org_id=org_id, doc=doc,
                                           removed_at__isnull=True).first()
        if option is None:
            raise Refused("Those options are not on this page any more.")
        alts = _load(option.alts)
        if not 0 <= pick < len(alts):
            raise Refused("There is no such version.")
        alts[pick] = {**(alts[pick] or {}), "reason": words}
        option.alts = json.dumps(alts)
        option.save(update_fields=["alts"])
    log.info("pagehistory: the reason for version %s of option %s on %s was %s", pick,
             option.id, doc, "written" if words else "taken away")
    return {"option": option.id, "version": pick, "reason": words}


def check_version(markup: str, tag: str, others) -> str:
    """One version of a part of the page, offered by the model, as it is kept,
    or Refused saying why it cannot be.

    It has to be exactly one element, of the same kind as the part it is a
    version of, different from every version already there, and markup only
    (`_UNSAFE`).
    """
    text = str(markup or "").strip()
    if not text:
        raise Refused("That version is empty.")
    if len(text) > PART_MAX:
        raise Refused("That version is too large.")
    if _UNSAFE.search(text):
        raise Refused("That version holds something that runs or loads, which a version "
                      "may not.")
    spans = pages.element_spans(text)
    whole = [s for s in spans if s[0] == 0 and s[1] == len(text)]
    if not whole or whole[0][2] != str(tag or "").lower():
        raise Refused(f"That version is not one <{tag}> element.")
    if any(text == str(o or "").strip() for o in others):
        raise Refused("That version is the same as one already there.")
    return text


def propose(org_id: str, doc: str, option_id, versions, label: str, reason: str,
            by: str = AI_BY) -> dict:
    """One more version of an option, offered beside the others.

    ``versions`` is the new version of each part of the option, in order. The
    page is not written and the default does not move: anybody may switch to
    it on their own screen or make it the default, as with any version.
    """
    from .models import PageOption

    name = " ".join(str(label or "").split())[:LABEL_MAX]
    why = " ".join(str(reason or "").split())[:REASON_MAX]
    if not name or not why:
        raise Refused("A version needs a name and a reason.")
    with _lock():
        option = PageOption.objects.filter(id=_number(option_id), org_id=org_id, doc=doc,
                                           removed_at__isnull=True).first()
        if option is None:
            raise Refused("Those options are not on this page any more.")
        if option.final_at:
            raise Refused("That choice was made final, so no more versions are offered.")
        alts = _load(option.alts)
        kept = _load(option.parts)
        if len(alts) >= VERSIONS_MAX:
            raise Refused(f"That part of the page has {VERSIONS_MAX} versions already.")
        if not isinstance(versions, list) or len(versions) != len(kept):
            raise Refused("A version has to give every part of the option.")
        made = [check_version(v, part.get("tag") or "", part.get("alts") or [])
                for v, part in zip(versions, kept)]
        for part, version in zip(kept, made):
            part["alts"].append(version)
        alts.append({"edit": None, "by": by, "at": time.time(), "label": name,
                     "reason": why})
        option.parts = json.dumps(kept)
        option.alts = json.dumps(alts)
        option.save(update_fields=["parts", "alts"])
    log.info("pagehistory: %s offered version %s of option %s on %s", by, len(alts) - 1,
             option.id, doc)
    return {"option": option.id, "version": len(alts) - 1, "label": name, "reason": why}


def _lock():
    """The lock every change to a page and its options is made under."""
    from . import askai

    return askai._EDIT_LOCK


def for_layer(root, org_id: str, doc: str, source: str, files: bool = True) -> list[dict]:
    """The options on the page as it is about to be sent, for the layer that
    draws them (`askai.js`).

    Only those whose default is on the page, each part with where it starts in
    the file, which is the number the page's element carries
    (`pages.with_marks`), and every version with the files it names put in, as
    the page's own are. An option the page has moved away from is left out.
    ``files`` False leaves the versions as they are kept, which is what the
    model is shown (`rouh/commentpass.py`): a picture put in is a long run of
    letters that says nothing.
    """
    rows = _live(org_id, doc)
    if not rows:
        return []
    ids = set()
    for row in rows:
        ids.add(row.chosen_by)
        ids.add(row.final_by)
        ids.update(str((a or {}).get("by") or "") for a in _load(row.alts))
    called = names(ids)
    out = []
    for row in rows:
        alts = _load(row.alts)
        shown = []
        for part in _load(row.parts):
            versions = part.get("alts") or []
            if not 0 <= row.chosen < len(versions) or len(versions) != len(alts):
                shown = []
                break
            at = source.find(versions[row.chosen])
            if at < 0:
                shown = []
                break
            shown.append({"tag": part.get("tag") or "",
                          "at": -1 if part.get("tag") in pages._UNMARKED else at,
                          "alts": [_with_files(root, doc, v) if files else v
                                   for v in versions]})
        if not shown:
            continue
        first = next((a for a in alts if (a or {}).get("edit") == row.edit_id), None)
        out.append({
            "id": row.id,
            "title": str((first or alts[-1] or {}).get("label") or "Options"),
            "chosen": row.chosen,
            "chosen_by": called.get(row.chosen_by, "") if row.chosen_by else "",
            "chosen_at": row.chosen_at or 0,
            "final": bool(row.final_at),
            "final_by": called.get(row.final_by, "") if row.final_by else "",
            "final_at": row.final_at or 0,
            "alts": [{"label": str((a or {}).get("label") or "A version"),
                      "who": called.get(str((a or {}).get("by") or ""), ""),
                      "at": (a or {}).get("at") or 0,
                      "reason": str((a or {}).get("reason") or ""),
                      "ai": (a or {}).get("by") == AI_BY} for a in alts],
            "parts": shown,
        })
    return out


def options_now(root, org_id: str, doc: str) -> list[dict]:
    """`for_layer`, for the page as it is on disk now. Nothing when the page
    cannot be read: a page without its options is still the page."""
    from . import askai

    try:
        source = askai.read_source(askai.resolve(root, doc))
    except (askai.Unavailable, askai.EditRefused):
        return []
    try:
        return for_layer(root, org_id, doc, source)
    except Exception:                               # noqa: BLE001 - the page still draws
        log.exception("pagehistory: the options on %s could not be read", doc)
        return []


def _with_files(root, doc: str, markup: str) -> str:
    try:
        return pages.with_files(root, doc, markup.encode("utf-8", "surrogateescape")
                                ).decode("utf-8", "surrogateescape")
    except Exception:                               # noqa: BLE001 - the words still show
        log.exception("pagehistory: the files in an option on %s could not be put in", doc)
        return markup


# --------------------------------------------------------------------------
# The history, and the page as it was
# --------------------------------------------------------------------------


def names(ids) -> dict[str, str]:
    """What to call each person who changed a page."""
    from .models import User

    ids = {str(i) for i in ids if i}
    out = {i: LINK_NAME for i in ids if i.startswith("link:")}
    if AI_BY in ids:
        out[AI_BY] = AI_NAME
    wanted = [int(i) for i in ids if i.isdigit()]
    for user in User.objects.filter(pk__in=wanted):
        out[str(user.pk)] = (user.get_full_name() or user.username or "Somebody").strip()
    return out


def git_versions(root, doc: str) -> list[dict]:
    """The commits that changed the page, newest first, each with who made it,
    when, what it said, and where the page was in it.

    Rouh's own commits are left out, and so is a commit that left the page as
    the one before it had it, which is what moving its folder looks like.
    Nothing at all where the workspace is not in git.
    """
    where = str(Path(root))
    try:
        done = gitutil.run(where, "log", "--follow", "-n", str(GIT_MAX * 2), "--no-abbrev",
                           "--raw", "--format=%x1e%H%x1f%at%x1f%an%x1f%s", "--", doc,
                           timeout=20)
    except (OSError, subprocess.SubprocessError):
        return []
    if done.returncode != 0:
        return []
    found = []
    for block in done.stdout.split("\x1e")[1:]:
        head, _, rest = block.partition("\n")
        fields = head.split("\x1f", 3)
        if len(fields) != 4 or not _SHA.fullmatch(fields[0]):
            continue
        blob, path = "", ""
        for line in rest.splitlines():
            if not line.startswith(":"):
                continue
            said, _, paths = line.partition("\t")
            parts = said.split()
            if len(parts) < 5:
                continue
            blob = "" if parts[4].startswith("D") else parts[3]
            path = paths.split("\t")[-1]
        try:
            at = float(fields[1])
        except ValueError:
            at = 0.0
        found.append({"sha": fields[0], "at": at, "author": fields[2], "subject": fields[3],
                      "blob": blob, "path": path})
    out = []
    for n, one in enumerate(found):
        older = found[n + 1]["blob"] if n + 1 < len(found) else None
        if not one["blob"] or one["blob"] == older or one["author"] == ROUH_AUTHOR:
            continue
        out.append(one)
        if len(out) >= GIT_MAX:
            break
    return out


def _subject(said: str) -> str:
    return re.sub(r"^workspace:\s*", "", said or "").strip() or "A new version was saved"


def history(root, org_id: str, doc: str, source: str = "") -> list[dict]:
    """Every change to the page, newest first, as the History panel lists it."""
    from .models import AskEdit, PageOption

    rows = list(AskEdit.objects.filter(page_org_id=org_id, doc=doc).order_by("-id")
                .values("id", "user_id", "summary", "created_at", "undone_at", "kind",
                        "keep")[:HISTORY_MAX])
    keepable = set(AskEdit.objects.filter(page_org_id=org_id, doc=doc).exclude(parts="")
                   .values_list("id", flat=True))
    options = {}
    for option in PageOption.objects.filter(org_id=org_id, doc=doc):
        state = "stopped" if option.removed_at else "gone"
        if not option.removed_at and _on_page(option, source):
            state = "on"
        options[option.edit_id] = state
        for alt in _load(option.alts):
            made = (alt or {}).get("edit")
            if made and made not in options:
                options[made] = state
    called = names(r["user_id"] for r in rows)
    out: list[dict] = []
    for row in rows:
        who = called.get(row["user_id"], "Somebody")
        entry = {"id": f"e{row['id']}", "edit": row["id"],
                 "kind": "default" if row["kind"] else "change",
                 "summary": row["summary"] or "Changed the page", "who": who,
                 "at": row["created_at"], "keep": row["keep"],
                 "undone": bool(row["undone_at"])}
        if not row["kind"]:
            entry["keepable"] = (row["id"] in keepable and not row["undone_at"]
                                 and row["keep"] != "option")
            if row["keep"] == "option":
                entry["option"] = options.get(row["id"], "gone")
        out.append(entry)
        if row["undone_at"]:
            out.append({"id": f"u{row['id']}", "kind": "undo",
                        "summary": "Put back: " + (row["summary"] or "a change"),
                        "who": who, "at": row["undone_at"]})
    saved = git_versions(root, doc)
    for one in saved:
        out.append({"id": "g" + one["sha"], "kind": "saved", "summary": _subject(one["subject"]),
                    "who": one["author"] or "Somebody", "at": one["at"]})
    if rows:
        first = rows[-1]
        if not any(one["at"] <= first["created_at"] for one in saved):
            out.append({"id": f"b{first['id']}", "kind": "start",
                        "summary": "The page before the first change here", "who": "",
                        "at": first["created_at"]})
    out.sort(key=lambda e: (e["at"] or 0, 0 if e["kind"] in ("start",) else 1), reverse=True)
    return out


def _on_page(option, source: str) -> bool:
    if not source:
        return False
    for part in _load(option.parts):
        alts = part.get("alts") or []
        if not 0 <= option.chosen < len(alts) or alts[option.chosen] not in source:
            return False
    return True


def version_source(root, org_id: str, doc: str, version: str) -> tuple[str, dict]:
    """The page as it was at one line of its history, and that line."""
    from .models import AskEdit

    found = _VERSION.fullmatch(str(version or ""))
    if not found:
        raise Refused("There is no such version of this page.")
    if found.group("sha"):
        sha = found.group("sha")
        for one in git_versions(root, doc):
            if one["sha"] == sha:
                text = _git_show(root, sha, one["path"])
                if text is None:
                    break
                return text, {"id": "g" + sha, "kind": "saved", "summary": _subject(one["subject"]),
                              "who": one["author"], "at": one["at"]}
        raise Refused("There is no such version of this page.")
    row = AskEdit.objects.filter(id=_number(found.group("id")), page_org_id=org_id,
                                 doc=doc).first()
    if row is None:
        raise Refused("There is no such version of this page.")
    kind = found.group("kind")
    who = names([row.user_id]).get(row.user_id, "Somebody")
    if kind == "e":
        return row.after, {"id": f"e{row.id}", "kind": "default" if row.kind else "change",
                           "summary": row.summary, "who": who, "at": row.created_at}
    if kind == "u":
        if not row.undone_at:
            raise Refused("There is no such version of this page.")
        return row.before, {"id": f"u{row.id}", "kind": "undo",
                            "summary": "Put back: " + (row.summary or "a change"), "who": who,
                            "at": row.undone_at}
    return row.before, {"id": f"b{row.id}", "kind": "start",
                        "summary": "The page before the first change here", "who": "",
                        "at": row.created_at}


def _git_show(root, sha: str, path: str) -> str | None:
    where = str(Path(root))
    try:
        done = gitutil.run(where, "show", f"{sha}:{path}", timeout=20, text=False)
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0 or len(done.stdout) > pages.MAX_BYTES:
        return None
    return done.stdout.decode("utf-8", "surrogateescape")


def _number(raw, otherwise: int = 0) -> int:
    try:
        got = int(raw)
    except (TypeError, ValueError):
        return otherwise
    return got if -1 < got < 2 ** 63 else otherwise
