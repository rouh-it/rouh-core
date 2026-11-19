"""Bringing a live page back into the workspace (Rouh Link, kind `html`, task 189).

A live page made from a page in a task's folder (`pagein.py`) is worked on in the space, and the
file it came from is left alone the whole time. Only the owner's press brings it back, never
anything automatic:

- **Bring back** (`bring_back`) writes the page as it stands in the space into the file it came
  from. What the file held before is kept in **the page's own history** (`AskEdit`, the record
  Ask AI and Rename already keep of every change to a page, `rouh/pagehistory.py`), as one line,
  "Brought back from the live page “…”", under the owner's name. That is chosen over a copy
  beside the file because it is where the person already looks for an earlier version of a page
  (History, with its Undo), it lives in the database and so survives any move of the workspace,
  and it adds no second page to the task's folder for its page, the task browser and the saves
  to show. ``backup`` is that line's version id, `b<id>`: the page before the change
  (`pagehistory.version_source`).
- The file is saved the way every page Rouh changes in place is: written whole
  (`askai._write_source`) and handed to Rouh's save (`saving.touched`, `saving.poke`), which
  commits it to the workspace's main with Rouh's own landing.
- One line goes into the task's notes (the nearest `AGENTS.md` above the page, else a new one
  in the page's folder): the day, the file, the space and the Rouhs' people it was worked on with.
- ``meta["brought"] = {"at", "path", "backup", "seq"}`` on the space, and a line in the signed log.
- **Put back** (`put_back`) writes the version from before the last bring back again, marks that
  line of the page's history put back (as its Undo would), adds a line to the notes and clears
  ``meta["brought"]``. As Undo does, it refuses when the file has changed since it was brought
  back, so nobody's later change is thrown away; the history still has every version.
- An ended space may still be brought back: the owner may want its last version.

And a member's Rouh may ask the owner to keep the version as it is (`ask_keep`): a
`space.keep_ask` to the holder, kept in ``meta["keep_asks"]`` (the newest 20) and said to the
owner. It changes nothing; the owner decides.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime
from pathlib import Path

from rouh.config import config

from . import log as _log
from . import pagein, wire

log = logging.getLogger("rouh.link.pageout")

#: The most asks to keep a version a space holds, newest last.
KEEP_ASKS_MOST = 20
NOTES = "AGENTS.md"


def _now() -> float:
    return time.time()


def _plain(words: str) -> Exception:
    from .peers import Problem

    return Problem(words)


def _day(at: float | None = None) -> str:
    d = datetime.fromtimestamp(at or _now())
    return f"{d.day} {d:%B %Y}"


def _and(names: list[str]) -> str:
    names = [n for n in names if n]
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def _owned(org: str, sid: str, who):
    """The space's row, when it is held here and the person pressing is this Rouh's own."""
    from . import spaces

    row = spaces._row(org, sid)
    if row is None:
        raise LookupError("There is no such live space.")
    if not row.mine or who is None or str(getattr(who, "org_id", "")) != str(org):
        raise _plain("Only the owner of the page can bring it back or put it back.")
    if row.kind != "html":
        raise _plain("Only a live page can be brought back into the workspace.")
    source = str(row.source or "")
    if not source or source.startswith("card:"):
        raise _plain("This live page did not start from a page in your workspace, so there is no file "
                     "to bring it back into.")
    return row


def _others(row) -> list[str]:
    """The people of the other Rouhs that were in the space, by name."""
    from . import spaces

    out = []
    for m in spaces.members_of(row):
        if m.get("label") == row.holder_label or not m.get("joined_at"):
            continue
        name = str(m.get("name") or m.get("label") or "").strip()
        if name and name not in out:
            out.append(name)
    return out


# --- the file and its notes -------------------------------------------------------------------------


def notes_file(root, rel: str) -> tuple[str, Path]:
    """The task's notes for a page: the nearest `AGENTS.md` at or above its folder, short of the
    top of the tree, else one in the page's own folder."""
    base = Path(root).resolve()
    parts = rel.split("/")[:-1]
    for n in range(len(parts), 1, -1):
        here = "/".join(parts[:n]) + "/" + NOTES
        if (base / here).is_file():
            return here, base / here
    here = "/".join(parts) + "/" + NOTES
    return here, base / here


def add_note(root, rel: str, line: str) -> str:
    """One line at the end of the task's notes. Its path in the workspace."""
    here, target = notes_file(root, rel)
    try:
        was = target.read_text(encoding="utf-8")
    except FileNotFoundError:
        was = ""
    text = was if not was or was.endswith("\n") else was + "\n"
    text += ("\n" if text and not text.endswith("\n\n") else "") + line.replace("\u2014", "-") + "\n"
    spare = target.with_name(f".{target.name}.{os.getpid()}.rouh-edit")
    try:
        spare.write_text(text, encoding="utf-8")
        if was:
            st = target.stat()
            os.chmod(spare, st.st_mode & 0o7777)
            try:
                os.chown(spare, st.st_uid, st.st_gid)
            except OSError:
                pass
        os.replace(spare, target)
    finally:
        if spare.exists():
            spare.unlink()
    return here


def _save(*paths: str) -> None:
    """Hand the changed files to Rouh's save, which commits them to the workspace's main."""
    try:
        from rouh import saving

        saving.touched(*paths)
        saving.poke()
    except Exception:  # noqa: BLE001 - the file is written; the next save pass finds it anyway
        log.exception("pageout: the save could not be told about %s", paths)


def write_page(root, rel: str, new: str, *, who, summary: str):
    """The page written whole, with what it held kept as a line of its history.
    ``(before, row id or None)``; None when the page already said exactly this."""
    from rouh import askai
    from rouh.models import AskEdit

    _rel, target = pagein.workspace_page(root, rel)
    with askai._EDIT_LOCK:
        before = pagein.read_text(target)
        if before == new:
            return before, None
        askai._write_source(target, new)
        row = AskEdit.objects.create(
            user_id=str(who.user_id), org_id=str(who.org_id), page_org_id=str(who.org_id), doc=rel,
            summary=summary[:300], before=before, after=new, created_at=_now())
    return before, row.id


# --- the two presses --------------------------------------------------------------------------------


def bring_back(org: str, sid: str, *, who) -> dict:
    """The live page as it stands, into the file it came from. Owner only, on the press."""
    from rouh.models import LinkSpace

    from . import htmldoc, spaces

    row = _owned(org, sid, who)
    root = config.assistant_repo or ""
    rel = str(row.source)
    # The element ids are the space's own (markers, claims, pins); the person's file never needed them.
    new = htmldoc.unstamp(htmldoc.text(row.doc or {}))
    if not new.strip():
        raise _plain("The live page is empty, so there is nothing to bring back.")
    title = row.title or "Live page"
    _before, edit = write_page(root, rel, new, who=who,
                               summary=f"Brought back from the live page “{title}”")
    name = rel.rsplit("/", 1)[-1]
    if edit is None:
        said = f"{name} already says exactly what the live page says."
        return {"ok": True, "path": rel, "backup": "", "said": said, "changed": False}
    others = _others(row)
    line = (f"{_day()}: `{name}` brought back from the live page space “{title}”"
            + (f" worked on with {_and(others)}." if others else "."))
    notes = add_note(root, rel, line)
    _save(rel, notes)
    brought = {"at": round(_now(), 3), "path": rel, "backup": f"b{edit}", "seq": int(row.seq or 0)}
    fresh = spaces._row(org, sid)
    LinkSpace.objects.filter(id=row.id).update(meta=dict((fresh or row).meta or {}, brought=brought),
                                               updated_at=_now())
    _log.write(org, "bring_back", f"Brought “{title[:80]}” back into {rel}.", space=sid)
    spaces._wake(org, sid)
    said = (f"{name} now says what the live page says. What it said before is in the page's history, "
            "and Put back brings it back.")
    return {"ok": True, "path": rel, "backup": brought["backup"], "said": said, "changed": True}


def put_back(org: str, sid: str, *, who) -> dict:
    """The file as it was before the last bring back, again. Owner only, on the press."""
    from rouh import askai
    from rouh.models import AskEdit, LinkSpace

    from . import spaces

    row = _owned(org, sid, who)
    brought = (row.meta or {}).get("brought") or {}
    backup = str(brought.get("backup") or "")
    rel = str(brought.get("path") or row.source)
    if not backup.startswith("b") or not backup[1:].isdigit():
        raise _plain("This live page has not been brought back, so there is nothing to put back.")
    root = config.assistant_repo or ""
    edit = AskEdit.objects.filter(id=int(backup[1:]), page_org_id=str(org), doc=rel).first()
    if edit is None or edit.undone_at:
        raise _plain("The version from before it was brought back is no longer there to put back.")
    _rel, target = pagein.workspace_page(root, rel)
    with askai._EDIT_LOCK:
        if pagein.read_text(target) != edit.after:
            raise _plain("The page has changed since it was brought back, so putting it back would throw "
                         "that change away. Its history still has the version from before.")
        askai._write_source(target, edit.before)
        AskEdit.objects.filter(id=edit.id).update(undone_at=_now())
    try:
        from rouh import pagehistory

        pagehistory.undone(str(org), rel, edit)
    except Exception:  # noqa: BLE001 - the page is put back; its options are carried at the next look
        log.exception("pageout: the options of %s could not be carried back", rel)
    title = row.title or "Live page"
    name = rel.rsplit("/", 1)[-1]
    notes = add_note(root, rel, f"{_day()}: `{name}` put back as it was before it was brought back from "
                                f"the live page space “{title}”.")
    _save(rel, notes)
    fresh = spaces._row(org, sid)
    meta = dict((fresh or row).meta or {})
    meta.pop("brought", None)
    LinkSpace.objects.filter(id=row.id).update(meta=meta, updated_at=_now())
    _log.write(org, "put_back", f"Put {rel} back as it was before “{title[:80]}” was brought back.", space=sid)
    spaces._wake(org, sid)
    return {"ok": True, "path": rel, "backup": backup,
            "said": f"{name} is back as it was before the live page was brought back.", "changed": True}


# --- a member asks the owner to keep this version ---------------------------------------------------------


def ask_keep(org: str, sid: str, words: str = "") -> dict:
    """This Rouh's person, a member, asks the holder's owner to keep the page as it is now."""
    from . import peers, spaces

    row = spaces._row(org, sid)
    if row is None:
        raise LookupError("There is no such live space.")
    if row.kind != "html":
        raise _plain("Only a live page can be asked to be kept.")
    if row.mine:
        raise _plain("This is your own page: bring it back yourself when it is right.")
    holder = peers.peer_row(org, row.holder_label)
    if holder is None or holder.state != "connected":
        raise _plain("The Rouh holding this page is not connected now, so it cannot be asked.")
    form = {"space_id": sid, "seq": int(row.seq or 0)}
    words = " ".join(str(words or "").split())[:300]
    if words:
        form["words"] = words
    wire.queue(org, holder, "space.keep_ask", form)
    _log.write(org, "keep_ask", f"Asked to keep this version of “{(row.title or '')[:80]}”.",
               peer=row.holder_label, space=sid)
    return {"ok": True, "said": "Asked. The owner decides whether to bring this version back."}


@wire.handles("space.keep_ask")
def _space_keep_ask(ctx, form) -> dict:
    from rouh.models import LinkSpace

    from . import spaces

    row = spaces._row(ctx.org, form["space_id"])
    if row is None or not row.mine or row.kind != "html":
        return {}
    label = ctx.peer.label
    if not any(m.get("label") == label and m.get("state") == "joined" for m in spaces.members_of(row)):
        return {}
    name = str(getattr(ctx.peer, "name", "") or label)
    ask = {"from": label, "name": name, "seq": int(form.get("seq") or 0),
           "words": " ".join(str(form.get("words") or "").split())[:300], "at": round(_now(), 3)}
    meta = dict(row.meta or {})
    meta["keep_asks"] = (list(meta.get("keep_asks") or []) + [ask])[-KEEP_ASKS_MOST:]
    LinkSpace.objects.filter(id=row.id).update(meta=meta, updated_at=_now())
    title = (row.title or "")[:80]
    _log.write(ctx.org, "keep_ask", f"{name} asked to keep this version of “{title}”.", peer=label,
               space=row.space_id)
    spaces._wake(ctx.org, row.space_id)
    spaces.push_owner(ctx.org, {"type": "link_notice",
                                "said": f"{name} asks you to keep this version of “{title[:60]}”."})
    return {}
