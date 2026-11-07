"""`python manage.py signin_email`: which email signs which account in to this Rouh (`rouh/signin.py`).

    signin_email list                      every address, its account, and which is primary
    signin_email set USERNAME EMAIL        make EMAIL the address that signs USERNAME in; the one
                                           before stays a second way in until EMAIL is used once
    signin_email remove USERNAME EMAIL     take an address off an account (never its last one)

For an administrator on the machine. The person changes their own on Anatomy, or, on a Rouh
connected to rouh.land, on rouh.land, which this Rouh then follows.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "List, set or remove the email addresses that sign accounts in to this Rouh."

    def add_arguments(self, parser):
        parser.add_argument("what", choices=["list", "set", "remove"])
        parser.add_argument("username", nargs="?")
        parser.add_argument("email", nargs="?")

    def handle(self, *args, **opt):
        from rouh import signin
        from rouh.models import SignInEmail, User

        if opt["what"] == "list":
            for row in SignInEmail.objects.select_related("user").order_by("user_id", "-primary", "added_at"):
                u = row.user
                self.stdout.write(f"{u.username:<32} {'guest' if u.is_guest else 'owner':<6} "
                                  f"{row.email:<40} {'primary' if row.primary else 'former, until the new one is used'}"
                                  f"  ({row.source or '-'})")
            return
        if not opt["username"] or not opt["email"]:
            raise CommandError("Give the account's username and the email.")
        user = User.objects.filter(username__iexact=opt["username"]).first()
        if user is None:
            raise CommandError(f"No account {opt['username']}.")
        try:
            if opt["what"] == "set":
                changed = signin.set_primary(user, opt["email"], source="admin")
                self.stdout.write(f"{signin.normal(opt['email'])} signs {user.username} in now."
                                  if changed else "Nothing changed: it is that account's address already.")
            else:
                gone = signin.remove_address(user, opt["email"])
                self.stdout.write("Removed." if gone else "That address was not on that account.")
        except ValueError as exc:
            raise CommandError(str(exc)) from None
