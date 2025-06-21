# core/admin.py

from django.contrib import admin
from .models import UserAgent, StreamProfile, CoreSettings

@admin.register(UserAgent)
class UserAgentAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "user_agent",
        "description",
        "is_active",
        "created_at",
        "updated_at",
    )
    search_fields = ("name", "user_agent", "description")
    list_filter = ("is_active",)
    readonly_fields = ("created_at", "updated_at")

@admin.register(StreamProfile)
class StreamProfileAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "command",
        "is_active",
        "user_agent",
    )
    search_fields = ("name", "command", "user_agent")
    list_filter = ("is_active",)

@admin.register(CoreSettings)
class CoreSettingsAdmin(admin.ModelAdmin):
    """
    CoreSettings Admin configuration.
    """
    list_display = (
        "key",
        "name",
        "value",
    )
    search_fields = ("key", "name", "value")
    # list_filter and readonly_fields for non-existent fields removed.
