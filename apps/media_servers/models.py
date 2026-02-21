from django.db import models
from django_celery_beat.models import PeriodicTask


class MediaServerIntegration(models.Model):
    class ProviderTypes(models.TextChoices):
        PLEX = 'plex', 'Plex'
        EMBY = 'emby', 'Emby'
        JELLYFIN = 'jellyfin', 'Jellyfin'

    class SyncStatus(models.TextChoices):
        IDLE = 'idle', 'Idle'
        RUNNING = 'running', 'Running'
        SUCCESS = 'success', 'Success'
        ERROR = 'error', 'Error'

    name = models.CharField(max_length=255, unique=True)
    provider_type = models.CharField(max_length=32, choices=ProviderTypes.choices)
    base_url = models.URLField(max_length=1000)
    api_token = models.CharField(max_length=1024, blank=True, default='')
    username = models.CharField(max_length=255, blank=True, default='')
    password = models.CharField(max_length=255, blank=True, default='')
    verify_ssl = models.BooleanField(default=True)
    enabled = models.BooleanField(default=True)
    add_to_vod = models.BooleanField(default=True)
    sync_interval = models.IntegerField(
        default=0,
        help_text='Auto-sync interval in hours (0 disables scheduled sync)',
    )
    include_libraries = models.JSONField(default=list, blank=True)
    sync_task = models.ForeignKey(
        PeriodicTask,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='media_server_integrations',
    )
    vod_account = models.ForeignKey(
        'm3u.M3UAccount',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='media_server_integrations',
    )
    last_synced_at = models.DateTimeField(null=True, blank=True)
    last_sync_status = models.CharField(
        max_length=16,
        choices=SyncStatus.choices,
        default=SyncStatus.IDLE,
    )
    last_sync_message = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        indexes = [
            models.Index(fields=['provider_type', 'enabled']),
        ]

    def __str__(self):
        return f'{self.name} ({self.get_provider_type_display()})'

    def save(self, *args, **kwargs):
        if self.base_url:
            self.base_url = self.base_url.rstrip('/')
        super().save(*args, **kwargs)

    @property
    def selected_library_ids(self) -> set[str]:
        values = self.include_libraries if isinstance(self.include_libraries, list) else []
        return {str(value).strip() for value in values if str(value).strip()}
