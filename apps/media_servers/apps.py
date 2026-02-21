from django.apps import AppConfig


class MediaServersConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.media_servers'
    label = 'media_servers'
    verbose_name = 'Media Servers'

    def ready(self):
        from apps.media_servers import signals  # noqa: F401
