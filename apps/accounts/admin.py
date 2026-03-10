from django.contrib import admin
from django.contrib.auth.admin import UserAdmin, GroupAdmin
from django.contrib.auth.models import Group
from .models import User, OIDCProvider

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


@admin.register(OIDCProvider)
class OIDCProviderAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'issuer_url', 'is_enabled', 'auto_create_users')
    list_filter = ('is_enabled',)
    prepopulated_fields = {'slug': ('name',)}
