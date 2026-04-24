from django.contrib import admin
from django.contrib.auth.admin import UserAdmin, GroupAdmin
from django.contrib.auth.models import Group
from .models import User

@admin.register(User)
class CustomUserAdmin(UserAdmin):
    fieldsets = (
        (None, {'fields': ('username', 'password', 'avatar_config', 'groups')}),
        ('Permissions', {'fields': ('is_staff', 'is_superuser', 'user_permissions')}),
        ('Important dates', {'fields': ('last_login', 'date_joined')}),
    )

# Unregister default Group admin and re-register it.
admin.site.unregister(Group)
admin.site.register(Group, GroupAdmin)
