"""``python manage.py attachments_access``: who may open the person's attachments.

Every file the person attaches in a chat or in Gene therapy is kept under
`<data dir>/attachments`, readable by the app and by one group and by nobody
else (`attachments.DIR_MODE`, `FILE_MODE`). That group is
`config.attachments_group`, `rouh-attachments` on the server, and its members
are the users that are handed those files by their path: `rouh`, which runs the
crew's workers, and `assistant`, which runs the one program's runs.

Until 1 October 2026 the tree was group `rouh`, so a run of the one program
told to look at a screenshot got "Permission denied" (runs 3a2e5fca and
5fff87dd), and 5fff87dd went on to guess which filter Petar meant. Putting
`assistant` into group `rouh` was the other way to fix it and was not taken:
that group also opens the crew's worktrees and Rouh's own home.

    python manage.py attachments_access                       # say how it is
    python manage.py attachments_access --apply --member assistant

With no options it only says how things are. `--apply`, which needs root,
makes the group if there is none, puts the crew user and every `--member` in
it, and gives the whole tree to it: every directory 2750, every file 640, each
in the group. It changes nothing else, and running it again changes nothing.

A user added to a group has it in every process started after that, so a run
or a worker started afterwards can read the tree; one already running cannot.
New files need nothing: Rouh gives each one the group as it writes it, and the
set-group-id directories keep it on anything that arrives another way.
"""
from __future__ import annotations

import grp
import os
import pwd
import stat
import subprocess

from django.core.management.base import BaseCommand, CommandError

from rouh import attachments, filestore
from rouh.config import config


class Command(BaseCommand):
    help = "Show or set the group that may read the person's attachments."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true",
                            help="make the group, add its members and give the tree to it")
        parser.add_argument("--member", action="append", default=[],
                            help="a user to put in the group besides the crew user; repeatable")

    def handle(self, *args, **opts):
        name = config.attachments_group
        root = attachments.Attachments(config.data_dir).root
        members = [u for u in dict.fromkeys([config.crew_user, *opts["member"]]) if u]
        for user in members:
            try:
                pwd.getpwnam(user)
            except KeyError:
                raise CommandError(f"There is no user called {user} on this machine.")
        if opts["apply"]:
            if os.geteuid() != 0:
                raise CommandError("Changing groups needs root: run it with sudo.")
            self._apply(name, members, root)
            # And the one store every file lives in since 4 November 2026 (`rouh/filestore.py`),
            # which jobs change as well as read, so it is the group's to write.
            self._apply(name, [], filestore.root(), filestore.DIR_MODE, filestore.FILE_MODE)
        self._report(name, root)
        self._report(name, filestore.root())

    def _apply(self, name: str, members: list[str], root: str,
               dir_mode: int = attachments.DIR_MODE, file_mode: int = attachments.FILE_MODE) -> None:
        try:
            grp.getgrnam(name)
        except KeyError:
            subprocess.run(["groupadd", "--system", name], check=True)
            self.stdout.write(f"Made the group {name}.")
        have = set(grp.getgrnam(name).gr_mem)
        for user in members:
            if user not in have:
                subprocess.run(["usermod", "--append", "--groups", name, user], check=True)
                self.stdout.write(f"Put {user} in {name}.")
        gid = grp.getgrnam(name).gr_gid
        os.makedirs(root, exist_ok=True)
        changed = 0
        for path in self._tree(root):
            info = os.lstat(path)
            if stat.S_ISLNK(info.st_mode):
                continue
            mode = dir_mode if stat.S_ISDIR(info.st_mode) else file_mode
            if info.st_gid != gid:
                os.chown(path, -1, gid)
            if stat.S_IMODE(os.lstat(path).st_mode) != mode:
                os.chmod(path, mode)
            if info.st_gid != gid or stat.S_IMODE(info.st_mode) != mode:
                changed += 1
        self.stdout.write(f"Gave {changed} paths under {root} to {name}.")

    def _report(self, name: str, root: str) -> None:
        try:
            group = grp.getgrnam(name)
        except KeyError:
            self.stdout.write(f"There is no group {name}: nothing but the app and the crew "
                              "user's own group can read the attachments.")
            return
        self.stdout.write(f"{name} has {', '.join(group.gr_mem) or 'no members'}.")
        try:
            outside = sum(1 for p in self._tree(root) if os.lstat(p).st_gid != group.gr_gid)
        except PermissionError:
            self.stdout.write(f"{root} could not be read from here, so it was not counted.")
            return
        self.stdout.write(f"{outside} paths under {root} are in another group."
                          if outside else f"Everything under {root} is in {name}.")

    @staticmethod
    def _tree(root: str):
        yield root
        for here, dirs, files in os.walk(root):
            for one in dirs + files:
                yield os.path.join(here, one)
