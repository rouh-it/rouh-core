"""The Django admin, for whoever manages accounts on this install.

At ``/admin/``, behind the same sign-in as everything else, and open only to
an account marked staff (`python manage.py account add <name> --staff`, or
`is_staff` on the account). It is where a team member is added, given an
organisation, switched off, or given a new password - and where an
organisation says its people sign in with Google (its domain, and whether a
first sign-in makes the account).

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
