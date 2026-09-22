from django.apps import AppConfig


class VODConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.vod'
    verbose_name = 'Video on Demand'

    def ready(self):
        from . import signals  # noqa: F401
