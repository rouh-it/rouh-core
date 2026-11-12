"""``python manage.py code_release``: Rouh's releases on rouh.land, read and published from here.

    python manage.py code_release                    what is released, what would be next, and
                                                     what update_rouh's check says on this Rouh
    python manage.py code_release --publish          publish the newest commit of rouh-core's main
                                                     that passed Tests on main, as the release, now
    python manage.py code_release --publish <commit> publish that commit, if it qualifies
    python manage.py code_release --record-start     write down this Rouh's starting version (a
                                                     Rouh with Rouh's whole history: the Creator)

Task 140, step 140-18, and Petar on 12 November 2026: "There's nothing to update to." The release
is normally chosen and published by itself, once a day, after a checked change has run a whole day
here (`rouh/code_release.py`, ``once``), from this Rouh's own undo points. A release by hand
(``publish_by_hand``) takes the commits of rouh-core's main itself: the newest that passed master's
Tests on main, has run here a whole day (rouh.land refuses a younger one) and contains the release
before it. It is signed with this Rouh's daily key, so it runs only on the Creator Rouh,
the one rouh.land lists as a release maker.

A job reaches it through ``core_command`` (`rouh/core_commands.py`): ``code_release_status`` reads,
``code_release_publish`` publishes the newest that qualifies.
"""
from __future__ import annotations

import json

from django.core.management.base import BaseCommand


def status() -> str:
    from rouh import code_evolution, code_release, code_update, relay

    lines = []
    b = code_update.base()
    lines.append(f"This Rouh's code: {json.dumps(b)}")
    got = code_release.published()
    lines.append("Released on rouh.land: " + (f"{got['commit']} (live since {got.get('live_since') or '?'})"
                                             if got.get("commit") else "nothing yet"))
    s = code_release._state()
    if s.get("said"):
        lines.append(f"The last look: {s['said']}")
    points: list = []
    try:
        from rouh import guardface

        points = guardface.ask("points").get("points") or []
    except Exception:  # noqa: BLE001 - the commit times stand in
        pass
    nxt, why = code_release.newest_checked(str(got.get("commit") or ""), points)
    lines.append(f"Next by hand: {nxt}" if nxt else f"Next by hand: none ({why})")
    doc = code_evolution.ledger()
    if doc.get("installed"):
        lines.append(f"Starting version: {doc['installed']} ({doc.get('start_how') or 'recorded'})")
    else:
        lines.append("Starting version: not recorded")
    who = relay.owner()
    if who is not None:
        try:
            lines.append("update_rouh check: " + code_update.said(code_update.public(who, look=True)))
        except code_update.Refused as exc:
            lines.append(f"update_rouh check: {exc}")
    return "\n".join(lines)


class Command(BaseCommand):
    help = "Rouh's releases on rouh.land: what is released, and a release by hand."

    def add_arguments(self, parser):
        parser.add_argument("--publish", nargs="?", const="newest", default=None,
                            help="publish the newest commit that qualifies, or the one named")
        parser.add_argument("--record-start", action="store_true",
                            help="write down this Rouh's starting version")

    def handle(self, *args, **opts):
        from rouh import code_evolution, code_release, code_update

        if opts["record_start"]:
            doc = code_evolution.record_start(code_update.base())
            self.stdout.write(f"Starting version: {doc.get('installed') or 'could not be said'}"
                              + (f" ({doc.get('start_how')})" if doc.get("start_how") else ""))
        if opts["publish"]:
            commit = "" if opts["publish"] == "newest" else opts["publish"]
            try:
                got = code_release.publish_by_hand(commit)
            except Exception as exc:  # noqa: BLE001 - said
                self.stdout.write(f"Not released: {exc}")
            else:
                self.stdout.write(got["said"])
        self.stdout.write(status())
