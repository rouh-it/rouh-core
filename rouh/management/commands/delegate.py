"""``python manage.py delegate``: who may decide for the person, and over what.

The same grants as Settings > Trusted contacts > a contact > May decide for, and
Rouh's own `delegate` tool (`rouh/delegation.py`, DELEGATION.md). It is here for
a job working on this machine that the person asked to give, extend or take back
authority, which is their own explicit request to write it.

    python manage.py delegate
    python manage.py delegate --contact "Sam Rivera" --task 98 --read \
        --promise "The quest and goals Rouh makes for the open-source legal work, once she accepts"
    python manage.py delegate --contact "Sam Rivera" --goal 101 --quest 102
    python manage.py delegate --extend --contact "Sam Rivera" --goal 101 --quest 102
    python manage.py delegate --revoke <grant id>
    python manage.py delegate --dedupe            # list what a record above already gives
    python manage.py delegate --dedupe --apply    # and take those away, checked one by one

With no options it lists every grant and the last things delegates did. A grant
made here is the person's own, like a press in Settings; `--extend` is Rouh
keeping a promise the person already made, and is held to it (goals and quests
made after the promise only). Nothing here sends anything to anybody.

A grant is a record of the one permission (`rouh/task_access.py`): read < edit < decide.
`--dedupe` finds records of decide that say nothing their contact would not have anyway,
inherited from a quest or a task above (a goal's, once its quest is decided for), and with
`--apply` takes each away only after checking that what the contact may do stays the same.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from rouh import delegation, trusted


SAID = {"decide": "decides for", "edit": "may edit", "read": "may read"}


class _Who:
    def __init__(self, user_id, org_id):
        self.user_id, self.org_id = str(user_id), str(org_id)


def _owner(user: str, org: str):
    if user and org:
        return _Who(user, org)
    from rouh import telegram
    from rouh.tenancy import Tenancy

    owner = telegram.phone_owner(Tenancy())
    if owner is None:
        raise CommandError("Whose grants? Give --user and --org.")
    return _Who(owner.user_id, owner.org_id)


class Command(BaseCommand):
    help = "List, give, extend or take back a trusted contact's authority to decide."

    def add_arguments(self, parser):
        parser.add_argument("--user", default="", help="the person, by user id")
        parser.add_argument("--org", default="", help="their organisation")
        parser.add_argument("--contact", default="", help="the trusted contact: name or address")
        parser.add_argument("--goal", action="append", default=[], help="a goal, by number")
        parser.add_argument("--quest", action="append", default=[], help="a quest, by number")
        parser.add_argument("--task", action="append", default=[], help="a task, by number")
        parser.add_argument("--step", action="append", default=[],
                            help="a step on its own, by its number as said: 98-03")
        parser.add_argument("--read", action="store_true",
                            help="reading only: they decide nothing there")
        parser.add_argument("--edit", action="store_true",
                            help="editing: they change it and decide nothing there")
        parser.add_argument("--dedupe", action="store_true",
                            help="records of decide a record above already gives")
        parser.add_argument("--apply", action="store_true",
                            help="with --dedupe: take them away")
        parser.add_argument("--promise", default="",
                            help="what Rouh may extend it to once it is made, in words")
        parser.add_argument("--extend", action="store_true",
                            help="keep a promise already made: goals and quests only")
        parser.add_argument("--revoke", action="append", default=[], metavar="GRANT_ID",
                            help="take a grant back, at once")

    def handle(self, *args, **options):
        who = _owner(options["user"], options["org"])
        if options["dedupe"]:
            from rouh import task_access

            found = task_access.dedupe(who, apply=options["apply"])
            for one in found:
                state = ("taken away" if one.get("done") else "kept, it was not the same")\
                    if options["apply"] else "would go"
                self.stdout.write(f"{one['email']} {one['role']} on {one['rel']}: inherited from "
                                  f"{one['name'] or one['from']}; {state}")
            self.stdout.write(f"{len(found)} record(s) say no more than what they inherit.")
            return
        said: list[str] = []
        for ident in options["revoke"]:
            try:
                said.append(delegation.revoke(who, ident, channel="manage.py"))
            except delegation.Refused as exc:
                raise CommandError(str(exc)) from None
        wanted = [("goal", g) for g in options["goal"]] + \
            [("quest", q) for q in options["quest"]] + [("task", t) for t in options["task"]] + \
            [("step", t) for t in options["step"]]
        if wanted:
            contact = delegation.find_contact(who.user_id, who.org_id, options["contact"])
            if contact is None:
                raise CommandError("Which trusted contact? Give --contact as on Trusted contacts.")
            try:
                if options["extend"]:
                    said += delegation.extend(who, contact.id,
                                              goals=[r for k, r in wanted if k == "goal"],
                                              quests=[r for k, r in wanted if k == "quest"])
                else:
                    for kind, ref in wanted:
                        row = delegation.grant(who, contact.id, kind, ref,
                                               power="read" if options["read"] else
                                               "edit" if options["edit"] else "decide",
                                               pending=options["promise"], channel="manage.py")
                        said.append(f"{contact.name} {SAID.get(row.power, 'may read')} "
                                    f"{delegation.name_of_row(row)} (grant {row.id})"
                                    + (f"; promise: {row.pending}" if row.pending else "") + ".")
            except delegation.Refused as exc:
                raise CommandError(str(exc)) from None
        for line in said:
            self.stdout.write(line)
        if said:
            return
        for c in trusted.TrustStore().all(who.user_id, who.org_id):
            for d in delegation.listing(who.user_id, who.org_id, c.id):
                self.stdout.write(f"grant {d['id']}: {c.name} {SAID.get(d['power'], 'may read')} "
                                  f"{d['name']}" + (f"; promise: {d['pending']}"
                                                    if d["pending"] else ""))
        for a in delegation.acts(who.user_id, who.org_id, most=20, theirs=False):
            self.stdout.write(f"act {a['id']} {a['outcome']}: {a['said'] or a['why']}")
