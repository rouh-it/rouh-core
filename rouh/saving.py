"""Rouh saves what it makes in the workspace, so that everything else can see it.

Rouh writes the workspace's shape itself: a task when the person asks for one,
a step when a card is filed, a task moved into a project, a task taken away. It
writes all of it into the checkout the server runs from, and until 24 September
2026 nothing ever saved it. Nothing was meant to: `bin/sync` had kept that
workspace level with GitHub every thirty seconds, and it went with the
workspace's own repository on 21 September. So a task Rouh made lived on this
one machine and nowhere else, and a job Rouh started for the same request,
working in a checkout of main, could not see it and made its own. Task 56 was
two tasks for two days that way, and 51 and 02 were the same bug.

This is the save. Whenever Rouh changes the shape of the workspace
(`objecttree.WRITTEN`), and every few minutes in case something changed it
without saying so, it looks at what the server's checkout holds that main does
not, and lands exactly that through `land.sh`:

- **a new object** - a folder with an `.object.json` that git has never seen -
  is copied into a checkout of main;
- **a move** Rouh made with `git mv` is made again there, so main's copy moves,
  with anything a job added to it, rather than being replaced by this one. So
  is a move git never saw: a task Rouh made a minute ago is saved to main but
  still untracked here, so moving it is a plain rename and the moved folder
  looks new. Main already has that id, at the old path, so it is moved there
  too rather than refused as a second task with the same number - which is
  what happened to task 61 on 24 September 2026, made in `unfiled/`, filed
  into its project a minute later, and left in `unfiled/` on main;
- **a removal** Rouh made with `git rm` is made again there;
- **a page Ask AI changed** (`rouh/askai.py`, since 24 September 2026) is put
  into main's copy of that page. A page is the one thing here that is changed
  in place rather than made, and the deploy that follows resets the server's
  checkout to main, so a change nobody saved would be gone at the next deploy.
  When a job changed the same page on main meanwhile, the two are merged the
  way git merges, and a merge that meets in the same lines is left unsaved and
  said in the log rather than either change being thrown away (`_take_change`);
- **a quest's four files** (`quest-goal.md`, `quest-rules.md`, `quest-plan.md`,
  `quest-notebook.md`, `rouh/quests.py`), changed in place by its page and by every beat
  on it, are put into main's the same way, since 5 October 2026, including the first
  time, when they are new in a task main already has (task 89, which became a quest).
- **the task list, `_tasks.md`**, which since 6 October 2026 is generated out of the
  database (`rouh/tasklist.py`) rather than written by anybody. Each pass first brings
  the rows up to date with the disk (`owning.sync`) and writes the file again out of
  them, and whenever that differs from main's copy main's is replaced with it whole:
  it is never merged, because there is nothing in it of anybody's but the rows'.

Anything main already has is left exactly as main has it. The server's checkout
is behind main between deploys, so it always looks as if it holds things main
does not; this only acts on what Rouh itself left untracked, staged or changed
there, and only while main has not got it. Doing it twice is doing it once.

It lands with `--no-deploy`. The files are already where Rouh serves them from,
because Rouh wrote them there, and a deploy started by the person saying "make a
task" could restart the very service they are talking to. The next ordinary
deploy moves the server's checkout onto main and the saved files become tracked
ones, byte for byte what was already there.

Off unless `ROUH_SAVE_WORKSPACE=1`, and even then only where the workspace is
in a git repository with a remote: a test world, a laptop and a job's checkout
all have a remote too, and it is the real one, so being switched on is a line in
the server's own settings and nowhere else
(`/etc/systemd/system/rouh.service.d/save-workspace.conf`).

**Which repository.** The one that holds the workspace, asked of git
(`rouh/workspace_repo.py`): since 21 October 2026 the workspace's own, a
checkout of the person's private repository beside Rouh's code, where a save is
a commit of nothing but the person's tree and lands with `land.sh` like any
other, as the workspace's own landing. Before that day the workspace was
`workspace/` in Rouh's code repository, and the same code still saves such a
one, with that folder in front of every path.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

from . import filestore, gitutil, workspace_repo
from .config import config

log = logging.getLogger("rouh.saving")


#: How long a save waits after it is told something changed, so a task and the
#: step filed into it a moment later go as one commit, and how new a folder may
#: be before it is left for the next pass because it may still be being written.
SETTLE = 2.0
#: How often it looks anyway, for a change nothing told it about.
EVERY = 300.0
#: How long the first look waits after the server comes up, so it does not
#: compete with the start itself.
FIRST = 15.0
#: What is never copied into a commit, whatever the workspace's .gitignore says.
SKIP = (".git", "node_modules", "__pycache__", ".DS_Store")
SIDECAR = ".object.json"
#: A page, which is what Ask AI changes.
PAGE = ".html"
#: A quest's four files in its task, which its page and its beats change (`rouh/quests.py`).
QUEST_FILES = ("quest-goal.md", "quest-rules.md", "quest-plan.md", "quest-notebook.md")
#: What a task shared with a trusted contact keeps of what was added to it, by them or
#: for Petar (`tools.ToolRegistry._shared_task`, 11 October 2026).
SHARED_NOTES = "shared-notes.md"
#: A task's or a step's own notes, which the person edits offline and the outbox writes when
#: the device comes back (`rouh/offline.py`, 12 October 2026). Until then nothing wrote them
#: in place, and an edit here would have gone with the next deploy.
NOTES = ("AGENTS.md", "step.md")
#: The task list, generated out of the database (`rouh/tasklist.py`).
LISTING = "_tasks.md"


def _git(where: str | Path, *args: str, timeout: int = 120) -> subprocess.CompletedProcess:
    return gitutil.run(where, *args, timeout=timeout)


def _ok(where: str | Path, *args: str, timeout: int = 120) -> str:
    done = _git(where, *args, timeout=timeout)
    if done.returncode != 0:
        raise RuntimeError(f"git {' '.join(args[:2])}: "
                           f"{(done.stderr or done.stdout).strip()[:300]}")
    return done.stdout


class Saver:
    """One checkout of main of Rouh's own, and one thread that lands into it.

    `app` is the top of the repository that holds the workspace the server
    serves, `ws` the workspace's path inside it ("" when the workspace is the
    whole repository), and every path below is a path in that repository.
    """

    def __init__(self, *, workspace: str, into: str, land_script: str, land_dir: str):
        self.live = Path(workspace)
        top, self.ws = workspace_repo.locate(str(workspace))
        self.app = Path(top)
        self.into = Path(into)
        self.land_script = land_script
        self.land_dir = land_dir
        self._cond = threading.Condition()
        self._asked = 0
        self._done = 0
        self._thread: threading.Thread | None = None
        self._stop = False
        self._refused: dict[str, float] = {}
        # What this pass put in from here, kept as the base for the next
        # change only once it has really reached main (`_remember`).
        self._putting: list[tuple[str, str, bytes]] = []
        # The task list main is known to have, so a pass with nothing new in
        # the rows does not check main out to find that out (`_listing`).
        self._listed: bytes | None = None

    # --- asked from anywhere -------------------------------------------------

    def poke(self) -> None:
        """Something in the workspace changed shape: save it soon."""
        with self._cond:
            self._asked += 1
            self._cond.notify_all()

    def wait(self, timeout: float) -> bool:
        """Wait for every change already reported to be saved. True when it was.

        Only for changes somebody already said were made: nothing is looked
        at here, so starting a job when nothing is waiting costs nothing.
        """
        with self._cond:
            target = self._asked
            return self._cond.wait_for(lambda: self._done >= target, timeout=timeout)

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, name="workspace-save",
                                            daemon=True)
            self._thread.start()

    # --- the thread ----------------------------------------------------------

    def _loop(self) -> None:
        time.sleep(FIRST)
        while not self._stop:
            time.sleep(SETTLE)
            with self._cond:
                target = self._asked
            again = False
            try:
                again = self.save_once()
            except Exception:
                log.exception("the workspace could not be saved to main")
            with self._cond:
                if again:
                    # A folder still being written: the pass that saves it is
                    # the one that answers whoever is waiting.
                    continue
                self._done = max(self._done, target)
                self._cond.notify_all()
                self._cond.wait_for(lambda: self._asked > self._done or self._stop,
                                    timeout=EVERY)

    # --- what the server's checkout holds that main does not -----------------

    def changes(self) -> dict:
        """What Rouh left in the server's checkout: new, moved and removed objects,
        pages Ask AI changed (`rouh/askai.py`), and files changed in place
        (`_kept_in_place`)."""
        raw = _ok(self.app, "status", "--porcelain=v1", "-z", "--untracked-files=all",
                  "--", workspace_repo.spec(self.ws))
        parts = raw.split("\0")
        # `edited` is each changed file and the path the deployed copy is at:
        # its own, the one it moved from, or "" for one git has never seen here.
        new_sidecars, renamed, deleted, edited = [], [], [], []
        loose, links = [], []
        i = 0
        while i < len(parts):
            entry = parts[i]
            i += 1
            if len(entry) < 4:
                continue
            x, y, path = entry[0], entry[1], entry[3:]
            if x in "RC":
                was = parts[i]
                i += 1
                if x == "R" and os.path.basename(path) == SIDECAR:
                    renamed.append((os.path.dirname(was), os.path.dirname(path)))
                elif x == "R" and y == "M" and _kept_in_place(path):
                    edited.append((path, was))
                continue
            if "M" in (x, y) and _kept_in_place(path):
                edited.append((path, path))
                continue
            if x == "?" and os.path.basename(path) in (SHARED_NOTES, *QUEST_FILES):
                loose.append(path)
                continue
            if x == "?" and filestore.is_files_link(str(self.app / path)):
                # A task's `files`, the link to its folder in the store (`rouh/filestore.py`).
                links.append(path)
                continue
            if os.path.basename(path) != SIDECAR:
                continue
            if x == "?":
                new_sidecars.append(os.path.dirname(path))
            elif "D" in (x, y):
                deleted.append(os.path.dirname(path))
        # A folder renamed without git knowing - a path git never tracked, or
        # one moved by hand - is a removal and a new folder with the same id.
        ids_new = {self._id_on_disk(f): f for f in new_sidecars}
        moved = list(renamed)
        gone = []
        for folder in deleted:
            ident = self._id_in_head(folder)
            if ident and ident in ids_new:
                moved.append((folder, ids_new.pop(ident)))
            else:
                gone.append(folder)
        # Every new folder, nested ones too: which of them main lacks is only
        # known once main is checked out (`save_once`).
        made = sorted(ids_new.values())
        # A quest's file, new in a task main already has (a task that became a
        # quest), is changed in place like any other; one main lacks goes with
        # its folder.
        edited += [(path, "") for path in loose]
        return {"new": made, "moved": moved, "gone": gone, "edited": edited, "links": links}

    def _id_on_disk(self, folder: str) -> str:
        try:
            node = json.loads((self.app / folder / SIDECAR).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return f"?{folder}"
        return str(node.get("id") or f"?{folder}") if isinstance(node, dict) else f"?{folder}"

    def _id_in_head(self, folder: str) -> str:
        done = _git(self.app, "show", f"HEAD:{folder}/{SIDECAR}")
        if done.returncode != 0:
            return ""
        try:
            node = json.loads(done.stdout)
        except ValueError:
            return ""
        return str(node.get("id") or "") if isinstance(node, dict) else ""

    # --- the save ------------------------------------------------------------

    def _listing(self) -> bytes | None:
        """The task list as the rows say it now, written into the server's
        checkout on the way, or None when it could not be made."""
        from django.db import close_old_connections

        from . import owning, tasklist

        # This thread lives as long as the server, so a connection the
        # database dropped meanwhile is let go of before the rows are read.
        close_old_connections()
        owning.sync()
        tasklist.refresh(self.live)
        try:
            return (self.live / LISTING).read_bytes()
        except OSError:
            return None

    def _put_listing(self, listing: bytes | None) -> bool:
        """The task list put into main's checkout whole. True when main's was different."""
        if listing is None:
            return False
        theirs = self.into / self.ws / LISTING
        try:
            if theirs.read_bytes() == listing:
                self._listed = listing
                return False
        except OSError:
            pass
        theirs.write_bytes(listing)
        _ok(self.into, "add", "--", workspace_repo.path(self.ws, LISTING))
        return True

    def save_once(self) -> bool:
        """Land whatever is unsaved. True when something was left for the next pass."""
        listing = self._listing()
        found = self.changes()
        ready = [f for f in found["new"] if time.time() - _newest(self.app / f) >= SETTLE]
        later = len(ready) < len(found["new"])       # still being written
        # A folder main refused under a number it already has is not offered
        # again until it changes: it would be refused again, every few minutes.
        ready = [f for f in ready if self._refused.get(f) != _newest(self.app / f)]
        # And a page whose change would not merge into main's is not offered
        # again until it changes again, for the same reason.
        edited = [(p, was) for p, was in found["edited"]
                  if self._refused.get(p) != _mtime(self.app / p)]
        listed = listing is not None and listing != self._listed
        links = found.get("links") or []
        if not (ready or found["moved"] or found["gone"] or edited or listed or links):
            return later
        self._fresh_checkout()
        self._putting = []
        made: dict[str, str] = {}
        said: list[str] = []
        # The moves git saw first, so a task goes to where it went before its
        # new steps are looked for there: a step that arrived first would
        # make the task's new folder, and the task would look already moved.
        #
        # Outermost first, and each one inside a folder already moved looked
        # for where that move put it: a task moved by the person renumbers the
        # subtasks inside it (`objecttree.move`), so git says the task went
        # from A to B and its subtask from A/61-01 to B/62-01, and on main the
        # subtask is at B/61-01 by the time it is asked about.
        done_moves: list[tuple[str, str]] = []
        for was, now in sorted(found["moved"], key=lambda pair: pair[0].count("/")):
            for old, new in done_moves:
                if was.startswith(old + "/"):
                    was = new + was[len(old):]
            if self._on_main(now):
                continue
            if self._on_main(was):
                done_moves.append((was, now))
                (self.into / now).parent.mkdir(parents=True, exist_ok=True)
                _ok(self.into, "mv", "--", was, now)
                # The move rewrote the owner in the sidecar; main's copy has the
                # old one, so it follows the server's.
                shutil.copy2(self.app / now / SIDECAR, self.into / now / SIDECAR)
                _ok(self.into, "add", "--", f"{now}/{SIDECAR}")
            else:
                self._copy_in(now)
            said.append(f"the move of {self._short(was)} to {self._short(now)}")
        # Then what changed in place.
        for page, was in edited:
            if not was and not (self.into / page).exists() and not (
                    os.path.basename(page) in QUEST_FILES
                    and (self.into / page).parent.joinpath(SIDECAR).exists()):
                # A task main has not got: it went, or goes, with its folder.
                continue
            if self._take_change(page, was):
                said.append(f"the change Ask AI made to {self._short(page)}"
                            if page.lower().endswith(PAGE)
                            else f"the change made to {self._short(page)}")
        on_main = self._folders_on_main() if ready else {}
        # The outermost of the new folders main lacks: a task and its steps
        # go as one, and a step new inside a task main has goes on its own.
        for folder in _outermost(f for f in ready if not self._on_main(f)):
            was = on_main.get(self._id_on_disk(folder), "")
            if was and was != folder and not os.path.exists(self.app / was):
                self._move_in(was, folder)
                said.append(f"the move of {self._short(was)} to {self._short(folder)}")
                continue
            self._copy_in(folder)
            made[folder] = f"the new {self._short(folder)}"
        for link in links:
            # Only into a task main already has; a new task takes its link with its folder.
            here = self.into / link
            if not self._on_main(os.path.dirname(link)) or os.path.lexists(here):
                continue
            os.symlink(os.readlink(self.app / link), here)
            _ok(self.into, "add", "--", link)
            said.append(f"the link to the files of {self._short(os.path.dirname(link))}")
        for folder in found["gone"]:
            if not self._on_main(folder):
                continue
            ident = self._id_in_head(folder)
            _ok(self.into, "rm", "-r", "-q", "--", folder)
            self._forget_in_map(ident, folder)
            said.append(f"the removal of {self._short(folder)}")
        self._leave_out_doubles(made)
        said = list(made.values()) + said
        # Last, so it is made out of the same rows as everything above it.
        if self._put_listing(listing):
            said.append("the task list, made again out of the database")
        if not said or not _ok(self.into, "diff", "--cached", "--name-only").strip():
            return later
        head = ("workspace: Rouh saves " + said[0] if len(said) == 1
                else f"workspace: Rouh saves {len(said)} changes it made to the tree")
        body = ("Made in Rouh and written into the server's checkout, where a job "
                "working from main could not see it (rouh/saving.py):\n\n"
                + "\n".join(f"- {line}" for line in said))
        _ok(self.into, "-c", "user.name=Rouh", "-c", "user.email=rouh@localhost",
            "commit", "-q", "-m", head, "-m", body)
        if self._land(said):
            for page, at, data in self._putting:
                self._remember(page, at, data)
            if listing is not None:
                self._listed = listing
        self._putting = []
        return later

    def _forget_in_map(self, ident: str, folder: str) -> None:
        """A removed object's line taken out of main's `_migration-map.json` too.

        The server's copy lost it when the object was deleted
        (`objecttree.erase`), and main's must as well: the deploy puts main's
        map back on the server, `ensure_imported` finds an id in it with no
        row, and the deleted task is made again - its row, and then its
        folder, written out from that row. Petar deleted a task for the first
        time from its own page on 27 September 2026 (fr_3273da8d3be9), and a
        delete that comes undone at the next deploy is not a delete.
        """
        from . import objecttree

        base = self.into / self.ws
        rel = self._short(folder)
        if objecttree._forget_in_map(base, {ident} if ident else set(), [rel]):
            _ok(self.into, "add", "--", workspace_repo.path(self.ws, objecttree.MAP_FILE))

    def _short(self, folder: str) -> str:
        """A path in the repository as the person knows it: a path in the workspace."""
        return workspace_repo.inside(self.ws, folder)

    def _take_change(self, page: str, was: str | None = None) -> bool:
        """A page Ask AI changed, or another file changed in place, put into
        main's copy. True when there was something to put in.

        Three versions of it, the way git merges: the one the server's checkout
        was deployed with (its HEAD, at `was` when it moved there since), the
        one on disk there now, which is the change, and main's. A file git has
        never seen here (`was` empty) was deployed as main first had it. Main's the same as the deployed one is the usual
        case, and the change goes in as it is. Main's already the same as the
        change is a change saved before, and nothing is done. Anything else is
        a job that changed the same page on main since the deploy, and the two
        are merged as git would: a merge that meets in the same lines is not
        saved and is said in the log, rather than one of them being thrown
        away. A page main no longer has - moved, or taken away - is left.
        """
        mine = self.app / page
        theirs = self.into / page
        if (os.path.basename(page) in QUEST_FILES and not theirs.exists()
                and theirs.parent.joinpath(SIDECAR).exists() and mine.exists()):
            # A quest's file new in a task main has: put in as it is.
            changed = mine.read_bytes()
            theirs.write_bytes(changed)
            _ok(self.into, "add", "--", page)
            self._putting.append((page, self._head(), changed))
            return True
        try:
            changed = mine.read_bytes()
            on_main = theirs.read_bytes()
        except OSError:
            log.warning("the change made to %s was not saved: main has no such file "
                        "any more", self._short(page))
            self._refused[page] = _mtime(mine)
            return False
        head = self._head()
        if on_main == changed:
            self._remember(page, head, changed)
            return False
        # What main's copy and this one last had in common: what this very
        # saver last put in from here, while the server is still on the same
        # deploy, and otherwise the copy that was deployed.
        base = self._saved_base(page, head)
        if base is None:
            base = self._deployed(page, page if was is None else was)
        if base is None or base == on_main:
            theirs.write_bytes(changed)
        else:
            merged = _merge(on_main, base, changed)
            if merged is None:
                log.error("the change made to %s was not saved: main changed the same "
                          "part of it since the server was deployed", self._short(page))
                self._refused[page] = _mtime(mine)
                return False
            theirs.write_bytes(merged)
        _ok(self.into, "add", "--", page)
        self._putting.append((page, head, changed))
        return True

    # A page saved once is changed again, and the copy main has now is the one
    # saved a minute ago, not the one the server was deployed with. Until 27
    # September 2026 the second change was merged against the deployed copy,
    # so main's copy and the new one both looked changed in the same place,
    # and on a page that is one long line - task 61's whole site is one line
    # of 377 KB - that was every change after the first: 49 of a guest's edits in
    # a row were refused as "main changed the same part", and the next deploy
    # reset the page to the first one (fr_65039fdac5a2). So what was saved
    # from here is kept, with the commit the server was on when it was, and
    # it is the base for as long as the server stays on that commit. It is
    # kept in the saving checkout's own `.git`, which no checkout touches, so
    # a restart that is not a deploy keeps it too.

    def _head(self) -> str:
        done = _git(self.app, "rev-parse", "HEAD")
        return done.stdout.strip() if done.returncode == 0 else ""

    def _base_file(self, page: str) -> Path:
        import hashlib

        name = hashlib.sha256(page.encode("utf-8", "surrogateescape")).hexdigest()[:32]
        return self.into / ".git" / "rouh-saved" / name

    def _remember(self, page: str, head: str, data: bytes) -> None:
        if not head:
            return
        where = self._base_file(page)
        try:
            where.parent.mkdir(parents=True, exist_ok=True)
            spare = where.with_suffix(".new")
            spare.write_bytes(head.encode("ascii") + b"\n" + data)
            os.replace(spare, where)
        except OSError:
            log.warning("could not keep what was saved of %s", self._short(page))

    def _saved_base(self, page: str, head: str) -> bytes | None:
        try:
            raw = self._base_file(page).read_bytes()
        except OSError:
            return None
        at, _, data = raw.partition(b"\n")
        return data if head and at == head.encode("ascii") else None

    def _deployed(self, page: str, was: str) -> bytes | None:
        """The copy of a file the change was made to: the server's HEAD's, or
        for a file git has never seen there, the first copy main had."""
        if was:
            where, spec = self.app, f"HEAD:{was}"
        else:
            first = _git(self.into, "log", "--diff-filter=A", "--format=%H", "-1",
                         "--", page).stdout.strip()
            if not first:
                return None
            where, spec = self.into, f"{first}:{page}"
        shown = gitutil.run(where, "show", spec, timeout=120, text=False)
        return shown.stdout if shown.returncode == 0 else None

    def _leave_out_doubles(self, made: dict[str, str]) -> None:
        """Take out of this save a new folder that would give main a number twice.

        The same question `land.sh` asks before it pushes (`rouh/numbering.py`),
        asked here first of what is staged, so one such folder is left behind on
        its own instead of stopping everything saved beside it. It stays on the
        server and in the log until somebody gives it a number of its own.
        """
        from . import numbering

        staged = _ok(self.into, "write-tree").strip()
        prefix = workspace_repo.path(self.ws, "") if self.ws else ""
        doubled = numbering.doubled(numbering.objects_at(str(self.into), "origin/main", prefix),
                                    numbering.objects_at(str(self.into), staged, prefix))
        for sentence, folders in doubled:
            ours = [f for f in folders if f in made]
            for folder in ours:
                _ok(self.into, "rm", "-r", "-q", "--cached", "--", folder)
                shutil.rmtree(self.into / folder, ignore_errors=True)
                made.pop(folder)
                self._refused[folder] = _newest(self.app / folder)
            if ours:
                log.error("what Rouh made could not be saved to main, because main "
                          "already has it: %s", sentence)

    def _fresh_checkout(self) -> None:
        """Rouh's own checkout of main, made once and put back on main every time.

        Of the repository the workspace is in now: one made of another - Rouh's
        code repository, from before the workspace had a repository of its own -
        is put aside and made again, never pushed from (`_other_origin`)."""
        origin = _ok(self.app, "remote", "get-url", "origin").strip()
        if (self.into / ".git").exists() and self._other_origin(origin):
            aside = self.into.with_name(f"{self.into.name}.before-{int(time.time())}")
            log.info("the saves' checkout was of another repository; it is kept at %s", aside)
            os.replace(self.into, aside)
        if not (self.into / ".git").exists():
            self.into.parent.mkdir(parents=True, exist_ok=True)
            done = subprocess.run(
                ["git", "-c", "safe.directory=*", "clone", "-q", "--no-hardlinks",
                 str(self.app), str(self.into)],
                capture_output=True, text=True, timeout=600, check=False)
            if done.returncode != 0:
                raise RuntimeError(f"could not make {self.into}: {done.stderr.strip()[:300]}")
            _ok(self.into, "remote", "set-url", "origin", origin)
        _ok(self.into, "fetch", "-q", "origin", "main", timeout=300)
        _ok(self.into, "checkout", "-q", "-f", "-B", "rouh-saves", "origin/main")
        _ok(self.into, "clean", "-fdq")

    def _other_origin(self, origin: str) -> bool:
        done = _git(self.into, "remote", "get-url", "origin")
        return done.returncode == 0 and done.stdout.strip() != origin

    def _on_main(self, folder: str) -> bool:
        """Whether main has this object: its sidecar, not merely a folder by
        that name, which a step saved into it may have made."""
        return (self.into / folder / SIDECAR).exists()

    def _folders_on_main(self) -> dict[str, str]:
        """Every object on main, as its id and its folder."""
        from . import numbering

        try:
            prefix = workspace_repo.path(self.ws, "") if self.ws else ""
            return {str(node.get("id") or ""): node["folder"]
                    for node in numbering.objects_at(str(self.into), "HEAD", prefix)
                    if node.get("id") and node.get("folder")}
        except (RuntimeError, OSError, ValueError, KeyError):
            log.exception("could not read which objects main has")
            return {}

    def _move_in(self, was: str, now: str) -> None:
        """Main's copy of an object moved to where the server's copy is now.

        `git mv` of main's folder, so what a job added to it there goes with
        it and its history keeps following. Then the sidecar, whose owner the
        move rewrote, and any object inside the server's copy that main has
        never had - a step filed into the task before it moved - which is new.
        """
        (self.into / now).parent.mkdir(parents=True, exist_ok=True)
        _ok(self.into, "mv", "--", was, now)
        shutil.copy2(self.app / now / SIDECAR, self.into / now / SIDECAR)
        _ok(self.into, "add", "--", f"{now}/{SIDECAR}")
        inside = []
        for dirpath, dirnames, filenames in os.walk(self.app / now):
            dirnames[:] = [d for d in dirnames if d not in SKIP]
            rel = os.path.relpath(dirpath, self.app)
            if rel != now and SIDECAR in filenames and not self._on_main(rel):
                inside.append(rel)
        for folder in _outermost(inside):
            self._copy_in(folder)

    def _copy_in(self, folder: str) -> None:
        src, dst = self.app / folder, self.into / folder
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, dst, symlinks=True, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns(*SKIP))
        _ok(self.into, "add", "-A", "--", folder)

    def _land(self, said: list[str]) -> bool:
        """Land the commit made. True when it reached main."""
        env = dict(os.environ, ROUH_LAND_DIR=self.land_dir)
        done = subprocess.run(
            [self.land_script, "--path", str(self.into), "--no-deploy"],
            capture_output=True, text=True, timeout=900, env=env, check=False)
        lines = [line for line in done.stdout.splitlines() if line.strip()]
        try:
            answer = json.loads(lines[-1]) if lines else {}
        except ValueError:
            answer = {}
        if answer.get("landed"):
            log.info("saved to main at %s: %s", str(answer.get("sha") or "")[:7],
                     "; ".join(said))
            return True
        if answer.get("duplicate"):
            log.error("what Rouh made could not be saved to main, because main already "
                      "has it under the same number: %s", answer.get("reason"))
        else:
            log.warning("what Rouh made could not be saved to main (%s): %s",
                        answer.get("reason") or done.stderr.strip()[-300:],
                        "; ".join(said))
        return False


#: Where a merge that met in one line is tried again, finer: after every tag.
_CUT = b">"
_CUT_MARK = b">\x1e\n"


def _merge(ours: bytes, base: bytes, theirs: bytes) -> bytes | None:
    """``git merge-file`` of three versions of one file, or None where they
    really meet.

    Line by line first, as git would. A page written as one long line meets
    itself in that line whatever changed, so where that fails it is tried
    again with a line break after every tag, taken out afterwards: two
    changes to different parts of one line then merge as two changes to
    different lines. The cut is marked with a record separator, which git
    still takes for text, so a file that holds one is not cut.
    """
    merged = _merge_lines(ours, base, theirs)
    if merged is not None or any(b"\x1e" in data for data in (ours, base, theirs)):
        return merged
    cut = _merge_lines(*(data.replace(_CUT, _CUT_MARK) for data in (ours, base, theirs)))
    return None if cut is None else cut.replace(_CUT_MARK, _CUT)


def _merge_lines(ours: bytes, base: bytes, theirs: bytes) -> bytes | None:
    import tempfile

    with tempfile.TemporaryDirectory(prefix="rouh-merge-") as folder:
        names = []
        for name, data in (("main", ours), ("deployed", base), ("changed", theirs)):
            path = os.path.join(folder, name)
            with open(path, "wb") as fh:
                fh.write(data)
            names.append(path)
        done = subprocess.run(["git", "merge-file", "-p", *names], capture_output=True,
                              timeout=120, check=False)
    return done.stdout if done.returncode == 0 else None


def _kept_in_place(path: str) -> bool:
    """A file Rouh changes in place rather than makes: a page, an
    `.object.json` whose title a rename changed (`owning.rename`), a
    quest's file (`rouh/quests.py`), a shared task's notes (`SHARED_NOTES`), or
    a task's own notes edited offline (`NOTES`)."""
    return (path.lower().endswith(PAGE)
            or os.path.basename(path) in (SIDECAR, SHARED_NOTES, *QUEST_FILES, *NOTES))


def _mtime(path: Path) -> float:
    try:
        return os.lstat(path).st_mtime
    except OSError:
        return 0.0


def _outermost(folders) -> list[str]:
    ordered = sorted(set(folders))
    keep: list[str] = []
    for folder in ordered:
        if not any(folder.startswith(f"{outer}/") for outer in keep):
            keep.append(folder)
    return keep


def _newest(folder: Path) -> float:
    newest = 0.0
    for dirpath, dirnames, filenames in os.walk(folder):
        dirnames[:] = [d for d in dirnames if d not in SKIP]
        for name in filenames:
            try:
                newest = max(newest, os.lstat(os.path.join(dirpath, name)).st_mtime)
            except OSError:
                pass
    return newest




# --- the one saver, if this machine is the one that saves ----------------------

_saver: Saver | None = None


def enabled() -> bool:
    """Whether this process saves what it makes. See the module's last paragraph."""
    if not config.save_workspace:
        return False
    root = os.path.realpath(config.assistant_repo or "")
    if not root or not os.path.isdir(root):
        return False
    if _git(workspace_repo.top(root), "remote", "get-url", "origin").returncode != 0:
        return False
    return bool(land_script()) and os.access(land_script(), os.X_OK)


def land_script() -> str:
    return config.land_script or os.path.join(config.app_dir or "", "land.sh")


def start() -> bool:
    """Start saving, if this machine is the one that saves. True when it is."""
    global _saver
    if _saver is not None:
        return True
    if not enabled():
        log.info("what Rouh makes in the workspace is not saved to main from here")
        return False
    from . import objecttree

    _saver = Saver(workspace=config.assistant_repo, land_script=land_script(),
                   land_dir=config.land_dir,
                   into=config.save_dir or os.path.join(config.data_dir, "workspace-saves"))
    objecttree.WRITTEN.append(_saver.poke)
    _saver.start()
    log.info("what Rouh makes in the workspace is saved to main, from %s", _saver.into)
    return True


def wait(timeout: float = 90.0) -> bool:
    """Wait for what Rouh has made to reach main. True at once where nothing saves."""
    return True if _saver is None else _saver.wait(timeout)


def poke() -> None:
    """Something in the workspace changed: save it soon. Nothing where nothing saves."""
    if _saver is not None:
        _saver.poke()
