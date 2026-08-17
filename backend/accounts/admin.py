from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Child, ChildSchedule, User


class CustomUserAdmin(UserAdmin):
    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("Personal info", {"fields": ("first_name", "last_name", "email", "phone_number")}),
        ("Role", {"fields": ("role",)}),
        (
            "Permissions",
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                ),
                "classes": ["collapse"]
            },
        ),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
    )

class ChildScheduleInline(admin.TabularInline):
    model = ChildSchedule
    extra = 1


class ChildAdmin(admin.ModelAdmin):
    inlines = [ChildScheduleInline]


# Register your models here.
admin.site.register(User, CustomUserAdmin)
admin.site.register(Child, ChildAdmin)
