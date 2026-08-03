from django.contrib import admin

from .models import (
    MediaLibraryExportRun,
    MediaLibraryExportTarget,
    MediaLibraryImportRun,
    MediaLibraryLocation,
    MediaLibrarySource,
)


@admin.register(MediaLibrarySource)
class MediaLibrarySourceAdmin(admin.ModelAdmin):
    list_display = ("name", "provider_type", "enabled", "last_sync_status")
    list_filter = ("provider_type", "enabled")
    search_fields = ("name", "base_url")


admin.site.register(MediaLibraryLocation)
admin.site.register(MediaLibraryImportRun)
admin.site.register(MediaLibraryExportTarget)
admin.site.register(MediaLibraryExportRun)

