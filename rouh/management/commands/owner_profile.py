"""``python manage.py owner_profile``: put an existing owner's private values where Rouh reads them.

Until 20 October 2026 some of what Rouh's prompts said about the person it
belongs to was written into the code: their pronouns, their company's name
(SETUP.md). The code says `‹his›` and `‹company›` now, filled in from the
person's profile and their organisation, so an installation that was running
before has to have those two filled in once, or its prompts would say the
person's name where they said "his" and "the owner's company" where they said
the company's name.

The values are never in the repository. They are given in a file of the
installation's own, outside it:

    python manage.py owner_profile --from /var/www/rouh/private/owner.json
    python manage.py owner_profile --from ... --dry-run     # say what would change
    python manage.py owner_profile --undo /var/www/rouh/backups/owner-profile-<when>.json

where the file says, for one account by its username:

    {"username": "alex", "pronouns": "he", "org_name": "Example Co", "zone": "Europe/Lisbon"}

Every key but `username` may be left out, and one that is left out is not
touched. Only what differs is written, and only what is missing or different
is changed: run twice, the second run changes nothing and says so. Before it
writes anything it saves what was there into a backup file (`--backups`,
the data directory's `backups/` unless said), and `--undo` with that file puts
every value back exactly as it was. It never touches anybody else's account,
and never anything but these values.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

KEYS = ("pronouns", "org_name", "zone")


def _now(user, org_id: str) -> dict:
    from rouh import clock, profile
    from rouh.models import Organisation, UserSetting

    held = profile._held(str(user.pk), org_id)
    zone = (UserSetting.objects.filter(user_id=str(user.pk), name=clock.SETTING)
            .values_list("value", flat=True).first())
    try:
        zone = (json.loads(zone) or {}).get("zone", "") if zone else ""
    except (TypeError, ValueError):
        zone = ""
    return {"pronouns": held.get("pronouns"),
            "org_name": Organisation.objects.filter(id=org_id).values_list("name", flat=True).first(),
            "zone": zone or None}


def _put(user, org_id: str, values: dict) -> None:
    from rouh import clock, owner, profile
    from rouh.models import Organisation, UserSetting

    if "pronouns" in values:
        held = profile._held(str(user.pk), org_id)
        if values["pronouns"] is None:
            held.pop("pronouns", None)
        else:
            held["pronouns"] = values["pronouns"]
        profile._keep(str(user.pk), org_id, held)
    if "org_name" in values and values["org_name"]:
        Organisation.objects.filter(id=org_id).update(name=values["org_name"])
    if "zone" in values:
        if values["zone"]:
            UserSetting.objects.update_or_create(
                user_id=str(user.pk), name=clock.SETTING,
                defaults={"org_id": org_id, "value": json.dumps({"zone": values["zone"]}),
                          "updated_at": time.time()})
        else:
            UserSetting.objects.filter(user_id=str(user.pk), name=clock.SETTING).delete()
    owner.forget()


class Command(BaseCommand):
    help = "Put an existing owner's pronouns, organisation name and time zone where Rouh reads them."

    def add_arguments(self, parser):
        parser.add_argument("--from", dest="source", default="", help="a JSON file outside the repository")
        parser.add_argument("--undo", default="", help="a backup this command wrote")
        parser.add_argument("--backups", default="", help="where backups are written")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opt):
        from django.db import transaction

        from rouh import accounts, clock, profile
        from rouh.config import config
        from rouh.models.accounts import DEFAULT_ORG_ID

        path = opt["undo"] or opt["source"]
        if not path:
            raise CommandError("Give --from <file> or --undo <backup>.")
        try:
            said = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise CommandError(f"{path} could not be read: {exc}") from None
        user = accounts.get_user(str(said.get("username") or ""))
        if user is None or user.is_guest:
            raise CommandError("There is no owner's account with that username. Nothing was changed.")
        org_id = user.org_id or DEFAULT_ORG_ID
        wanted = said.get("before") if opt["undo"] else {k: said[k] for k in KEYS if k in said}
        if not isinstance(wanted, dict):
            raise CommandError("That file is not a backup this command wrote.")
        if "pronouns" in wanted and wanted["pronouns"] not in (None, *profile.PRONOUNS):
            raise CommandError("pronouns are he, she or \"\".")
        if wanted.get("zone") and clock.zone_named(wanted["zone"]) is None:
            raise CommandError(f"{wanted['zone']} is not a time zone.")

        now = _now(user, org_id)
        changes = {k: v for k, v in wanted.items() if k in KEYS and now.get(k) != v}
        if not changes:
            self.stdout.write(f"{user.username}: nothing to change; every value is already as given.")
            return
        for k, v in changes.items():
            self.stdout.write(f"{user.username}: {k} {now.get(k)!r} -> {v!r}")
        if opt["dry_run"]:
            self.stdout.write("dry run: nothing was changed.")
            return
        folder = Path(opt["backups"] or os.path.join(config.data_dir, "backups"))
        folder.mkdir(parents=True, exist_ok=True)
        backup = folder / f"owner-profile-{time.strftime('%Y%m%dT%H%M%S')}.json"
        backup.write_text(json.dumps({"username": user.username, "at": time.time(),
                                      "before": {k: now.get(k) for k in changes}},
                                     indent=2, ensure_ascii=False), encoding="utf-8")
        os.chmod(backup, 0o600)
        with transaction.atomic():
            _put(user, org_id, changes)
        self.stdout.write(f"changed {len(changes)} value(s); the values before are in {backup} "
                          f"(--undo {backup} puts them back).")
