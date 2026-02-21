from django.contrib import admin

from apps.media_servers.models import MediaServerIntegration


@admin.register(MediaServerIntegration)
class MediaServerIntegrationAdmin(admin.ModelAdmin):
    list_display = (
        'name',
        'provider_type',
        'enabled',
        'add_to_vod',
        'sync_interval',
        'last_sync_status',
        'last_synced_at',
    )
    list_filter = ('provider_type', 'enabled', 'add_to_vod', 'last_sync_status')
    search_fields = ('name', 'base_url')
