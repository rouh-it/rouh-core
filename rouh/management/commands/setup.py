"""``python manage.py setup``: a fresh installation's first owner, organisation and workspace.

Petar, 20 October 2026: Rouh is to be installed fresh by other people, with
none of his data, grants, tokens, schedules or destinations (SETUP.md). This
is the one command a new installation runs after its environment is set:

    python manage.py setup --username alex --email alex@example.com \\
        --first-name Alex --last-name Morgan --org-name "Example Co" \\
        --zone Europe/Lisbon --pronouns "" --workspace /srv/rouh-workspace

It migrates the database, names the organisation, makes the owner's account
(asking for the password, never printing it unless `--generate` is given),
writes their profile (pronouns) and time zone, and makes an empty workspace in
the shape Rouh draws: Work and Personal, and Personal's Miscellaneous, which
is where a task the filing cannot place goes. Then it says which of the
installation's own settings are still blank, and that nothing is connected.

It refuses an installation that already has an owner, so it can never be run
over somebody's data by mistake, and a workspace that is not empty, unless it
is already a workspace this command made. Run again on the same installation
with the same values, it changes nothing and says so.
"""
from __future__ import annotations

import getpass
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

#: The starting workspace's projects: folder -> title. Personal's folder is
#: `private`, as everywhere (`objectindex.COLUMNS`, RENAME.md).
PROJECTS = {"work": "Work", "private": "Personal", "private/misc": "Miscellaneous"}

#: What a fresh installation has no connection to until its owner makes one, in Settings.
NOT_CONNECTED = ("Google (Rouh's own mailbox, calendar and Drive)", "the owner's own mailboxes",
                 "Telegram", "Slack", "Apple contacts", "Philips Hue", "Dreame", "Stripe",
                 "payment cards", "shipping addresses", "Cloudflare", "the meeting library")


class Command(BaseCommand):
    help = "Set up a fresh installation: its organisation, its owner and an empty workspace."

    def add_arguments(self, parser):
        parser.add_argument("--username", required=True, help="the owner's sign-in name")
        parser.add_argument("--email", default="", help="the owner's own email address")
        parser.add_argument("--first-name", default="", help="what Rouh calls the owner")
        parser.add_argument("--last-name", default="")
        parser.add_argument("--pronouns", default="", choices=("", "he", "she"),
                            help="he, she, or nothing, which has Rouh use the name instead")
        parser.add_argument("--org-name", default="", help="the owner's organisation or company")
        parser.add_argument("--zone", default="", help="the owner's time zone, such as Europe/Lisbon")
        parser.add_argument("--workspace", default="",
                            help="where the workspace is made (ROUH_ASSISTANT_REPO points Rouh at it)")
        parser.add_argument("--password", default="", help="better to be asked")
        parser.add_argument("--generate", action="store_true", help="make a password up and print it once")
        parser.add_argument("--no-migrate", action="store_true", help="the database is already migrated")

    def handle(self, *args, **opt):
        say = self.stdout.write
        if not opt["no_migrate"]:
            call_command("migrate", interactive=False, verbosity=0)
            say("database: migrated")

        from rouh import accounts, clock, owner, profile, tenancy
        from rouh.config import config
        from rouh.models import Organisation, User, UserSetting

        username = opt["username"].strip()
        others = User.objects.filter(is_active=True, is_guest=False).exclude(username__iexact=username)
        if others.exists():
            raise CommandError("This installation already has an owner, so it is not a fresh one. "
                               "Nothing was changed.")

        org_id = tenancy.DEFAULT_ORG_ID
        tenancy.ensure_organisation(org_id, opt["org_name"].strip())
        if opt["org_name"].strip():
            Organisation.objects.filter(id=org_id).update(name=opt["org_name"].strip())
        say(f"organisation: {Organisation.objects.get(id=org_id).name}")

        user = accounts.get_user(username)
        if user is None:
            password, made_up = self._password(opt)
            user = accounts.add_user(username, password, opt["email"], org_id=org_id)
            say(f"account: {username}, made, manages the organisation")
            if made_up:
                say(f"password: {password}")
                say("This is the only time it is printed.")
        else:
            say(f"account: {username}, already there")
        fields = []
        for field, key in (("first_name", "first_name"), ("last_name", "last_name"), ("email", "email")):
            value = opt[key].strip()
            if value and getattr(user, field) != value:
                setattr(user, field, value)
                fields.append(field)
        if fields:
            user.save(update_fields=fields)
        profile.save(str(user.pk), user.org_id or org_id, {"pronouns": opt["pronouns"]})

        if opt["zone"]:
            z = clock.zone_named(opt["zone"])
            if z is None:
                raise CommandError(f"{opt['zone']} is not a time zone. Give one like Europe/Lisbon.")
            UserSetting.objects.update_or_create(
                user_id=str(user.pk), name=clock.SETTING,
                defaults={"org_id": user.org_id or org_id, "value": json.dumps({"zone": z.key}),
                          "updated_at": time.time()})
            say(f"time zone: {z.key}")

        owner.forget()
        found = owner.of(user.pk)
        say(f"Rouh calls them: {owner.say('‹owner›', owner=found)}"
            f" ({owner.say('‹he›, ‹his›', owner=found)})")

        if opt["workspace"]:
            self._workspace(Path(opt["workspace"]).expanduser().resolve(), say)

        blank = [name for name, value in (
            ("ROUH_PUBLIC_URL", config.public_url), ("ROUH_MAIL_FROM", config.mail_from),
            ("ROUH_OWN_MAILBOXES", config.own_mailboxes)) if not str(value or "").strip()]
        say(f"default time zone for new people: {config.default_zone or 'UTC'}")
        if blank:
            say("still blank in this installation's environment: " + ", ".join(blank)
                + " (deploy/installation.env.example says what each is; until then, what needs one says so and does nothing)")
        say("not connected: " + ", ".join(NOT_CONNECTED) + ". Each is connected in Settings by the owner.")

    def _password(self, opt) -> tuple[str, bool]:
        from rouh import accounts

        if opt["generate"]:
            return accounts.generate_password(), True
        if opt["password"]:
            return opt["password"], False
        first = getpass.getpass("The owner's password: ")
        if not first or first != getpass.getpass("Again: "):
            raise CommandError("The two passwords were not the same, or empty. Nothing was made.")
        return first, False

    def _workspace(self, root: Path, say) -> None:
        from rouh import objecttree

        here = Path(__file__).resolve().parents[3]
        if (root == here or here in root.parents) or (root / objecttree.MAP_FILE).exists() \
                and not (root / ".rouh-setup").exists():
            raise CommandError(f"{root} is inside Rouh's own code, or is somebody's workspace "
                               "already. Give a folder of the new installation's own, outside "
                               "the code.")
        made_by_us = (root / ".rouh-setup").exists()
        if root.exists() and any(root.iterdir()) and not made_by_us:
            raise CommandError(f"{root} is not empty. Give an empty folder, or one this command made.")
        root.mkdir(parents=True, exist_ok=True)
        template = Path(__file__).resolve().parents[2] / "workspace_template"
        for item in template.iterdir():
            target = root / item.name
            if not target.exists():
                (shutil.copytree if item.is_dir() else shutil.copy2)(item, target)
        # No code is copied in: `rouh-task` and `rouh` are in Rouh's own `bin/`,
        # which every run has on its PATH (21 October 2026).
        for rel in PROJECTS:
            (root / rel).mkdir(parents=True, exist_ok=True)
        objecttree.ensure_sidecars(root, titles=PROJECTS)
        (root / objecttree.MAP_FILE).write_text(
            json.dumps(objecttree.build_map(root), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        (root / ".rouh-setup").write_text("made by python manage.py setup\n", encoding="utf-8")
        if not (root / ".git").exists() and shutil.which("git"):
            subprocess.run(["git", "init", "-q", str(root)], check=False)
        said = os.environ.get("ROUH_WORKSPACE") or os.environ.get("ROUH_ASSISTANT_REPO", "")
        say(f"workspace: {root} (set ROUH_WORKSPACE={root} in this installation's environment)"
            if said != str(root) else f"workspace: {root}")
