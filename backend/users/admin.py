from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    list_display = ("username", "role", "full_name", "village", "district")
    list_filter = ("role", "is_active")
    fieldsets = DjangoUserAdmin.fieldsets + (
        (
            "GramSentinel",
            {"fields": ("role", "full_name", "village", "facility", "district")},
        ),
    )
