"""The Django admin, for whoever manages accounts on this install.

At ``/admin/``, behind the same sign-in as everything else, and open only to
an account marked staff (`is_staff` on the account). It is where the owner's
account is switched off or given a new password. Nobody else's account is
added here: a Rouh is its owner's alone, and other people open what is shared
with them through rouh.land (18 November 2026, `accounts.second_person`).

Nothing of anybody's own is shown here: not their chats, not their mail, not
a Google token. Those stay behind their own scoped queries.
"""
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Organisation, User


@admin.register(Organisation)
class OrganisationAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "sso_domain", "sso_auto_create")
    fields = ("id", "name", "sso_domain", "sso_auto_create")
    readonly_fields = ("id",)

    def has_add_permission(self, request):
        # An organisation is made with an id that other rows name. That is a
        # command's job, not a form's (`rouh.tenancy.Tenancy.add_organisation`).
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(User)
class RouhUserAdmin(UserAdmin):
    list_display = ("username", "email", "org", "is_org_admin", "is_staff", "is_active",
                    "last_login")
    list_filter = ("org", "is_org_admin", "is_staff", "is_active")
    fieldsets = UserAdmin.fieldsets + (
        ("Organisation", {"fields": ("org", "is_org_admin")}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ("Organisation", {"fields": ("email", "org", "is_org_admin")}),
    )

    def has_add_permission(self, request):
        # A Rouh is its owner's alone (`accounts.second_person`): the owner's account is made by
        # `manage.py setup` or the first run, and nobody else's is made at all.
        from .accounts import second_person

        return not second_person("")
