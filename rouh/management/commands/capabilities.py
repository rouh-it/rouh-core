"""``python manage.py capabilities``: what Rouh may do for contacts, and how the grants that were
there before grants were data stand now (CAPABILITIES.md).

    python manage.py capabilities              # the catalogue, the lock, and every owner's counts
    python manage.py capabilities --suspend    # suspend grants whose capability changed since

It reads, and with ``--suspend`` only suspends grants code can no longer stand behind, saying
why; it gives nothing, sends nothing and asks nobody anything.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from rouh import capabilities, capability_grants


class Command(BaseCommand):
    help = "The capability catalogue, its lock, and the migration of grants to data, per owner."

    def add_arguments(self, parser):
        parser.add_argument("--suspend", action="store_true",
                            help="Suspend grants whose capability changed incompatibly.")

    def handle(self, *args, **opts):
        from rouh.models import TrustedContact

        found = capabilities.catalogue()
        problems = capabilities.lock_problems(found, capabilities.read_lock())
        self.stdout.write(f"{len(found.caps)} capabilities: " + ", ".join(
            f"{c.id} v{c.version}" for c in found.actions()))
        for line in problems:
            self.stdout.write(f"  lock: {line}")
        owners = sorted(set(TrustedContact.objects.values_list("user_id", "org_id")))
        for user_id, org_id in owners:
            if opts["suspend"]:
                for one in capability_grants.suspend_incompatible(org_id, by="manage.py"):
                    self.stdout.write(f"  grant {one['id']} is {one['state']}: {one['why']}")
            got = capability_grants.migration_status(user_id, org_id)
            self.stdout.write(f"owner {user_id} in {org_id}:")
            for key, value in got.items():
                self.stdout.write(f"  {key}: {value}")
