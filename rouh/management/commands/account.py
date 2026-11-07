"""``python manage.py account``: make an account, change a password, list them.

The whole of it is in `rouh/accounts.py`; this is the door Django gives it.
"""
from django.core.management.base import BaseCommand

from rouh import accounts


class Command(BaseCommand):
    help = "Rouh's accounts: add, passwd, ensure, list, signout."

    def create_parser(self, prog_name, subcommand, **kwargs):
        return accounts.parser(f"{prog_name} {subcommand}")

    def run_from_argv(self, argv):
        # The parser is the command's own, whole, so the options Django adds to
        # every command are not in the way of the subcommands.
        import django

        django.setup()
        args = accounts.parser(f"{argv[0]} {argv[1]}").parse_args(argv[2:])
        raise SystemExit(accounts.run(args, out=self.stdout.write))

    def handle(self, *args, **options):  # pragma: no cover - run_from_argv does it
        raise NotImplementedError
