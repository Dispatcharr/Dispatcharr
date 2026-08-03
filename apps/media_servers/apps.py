from django.apps import AppConfig


class MediaServersConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.media_servers"
    verbose_name = "Media Libraries"

    def ready(self):
        from . import signals  # noqa: F401

